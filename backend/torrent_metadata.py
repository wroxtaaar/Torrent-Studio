"""Moved out of main.py (see docs/main-split-plan.md)."""

import asyncio
import json
import re
import shutil
import tempfile
import time
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit

import httpx
import libtorrent as lt
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cache_diagnostics import _InstrumentedAsyncClient
from seedr_client import info_hash, normalize_magnet
from settings import (
    FAST_SEARCH_TEST_URL,
    FAST_SEARCH_TRACKERS,
    KNABEN_API_URL,
    TORRENT_METADATA_API_URL,
    TORRENT_METADATA_BACKGROUND_RETRY_SECONDS,
    TORRENT_METADATA_BACKGROUND_TTL_SECONDS,
    TORRENT_METADATA_CACHE_FILE,
    TORRENT_METADATA_ITORRENTS_BASE_URL,
    TORRENT_METADATA_ITORRENTS_TIMEOUT_SECONDS,
    TORRENT_METADATA_JOB_RETENTION_SECONDS,
    TORRENT_METADATA_JOB_TIMEOUT_SECONDS,
    logger,
)

router = APIRouter()


# Metadata is deliberately independent of Seedr. The cache survives requests
# within a Render instance, while the global libtorrent session keeps DHT state
# warm between magnets until the container is restarted.
_metadata_cache: dict[str, dict[str, Any]] = {}
_metadata_jobs: dict[str, dict[str, Any]] = {}
_libtorrent_session: Any | None = None
_libtorrent_session_lock: asyncio.Lock | None = None


class MagnetRequest(BaseModel):
    magnet: str
    folder_id: str | int | None = None
    torrent_name: str | None = None
    size: int | float | None = None
    # Browser clients may serialize indexes as strings; normalize them in the endpoint.
    selected_indexes: list[int | str] | None = None
    manifest: list[dict[str, Any]] | None = None


def decode_torrent_metadata(raw: bytes) -> dict[bytes, Any]:
    """Decode the small bencoded .torrent metadata file produced by aria2."""
    position = 0

    def parse() -> Any:
        nonlocal position
        if position >= len(raw):
            raise ValueError("unexpected end of bencode")

        marker = raw[position:position + 1]
        if marker == b"i":
            position += 1
            end = raw.find(b"e", position)
            if end < 0:
                raise ValueError("unterminated integer")
            value = int(raw[position:end])
            position = end + 1
            return value

        if marker == b"l":
            position += 1
            value = []
            while position < len(raw) and raw[position:position + 1] != b"e":
                value.append(parse())
            if position >= len(raw):
                raise ValueError("unterminated list")
            position += 1
            return value

        if marker == b"d":
            position += 1
            value: dict[bytes, Any] = {}
            while position < len(raw) and raw[position:position + 1] != b"e":
                key = parse()
                if not isinstance(key, bytes):
                    raise ValueError("dictionary key is not bytes")
                value[key] = parse()
            if position >= len(raw):
                raise ValueError("unterminated dictionary")
            position += 1
            return value

        if marker.isdigit():
            colon = raw.find(b":", position)
            if colon < 0:
                raise ValueError("invalid byte string")
            size = int(raw[position:colon])
            position = colon + 1
            end = position + size
            if end > len(raw):
                raise ValueError("byte string exceeds metadata")
            value = raw[position:end]
            position = end
            return value

        raise ValueError("invalid bencode token")

    value = parse()
    if position != len(raw):
        raise ValueError("trailing bencode data")
    if not isinstance(value, dict):
        raise ValueError("torrent metadata root is not a dictionary")
    return value

def _load_metadata_cache() -> None:
    global _metadata_cache
    try:
        if TORRENT_METADATA_CACHE_FILE.exists():
            data = json.loads(TORRENT_METADATA_CACHE_FILE.read_text("utf-8"))
            if isinstance(data, dict):
                _metadata_cache = {
                    str(key).lower(): value
                    for key, value in data.items()
                    if isinstance(value, dict)
                }
    except Exception as exc:
        logger.info("Metadata cache load skipped: %s", exc)


def _save_metadata_cache() -> None:
    try:
        TORRENT_METADATA_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = TORRENT_METADATA_CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_metadata_cache, ensure_ascii=False), "utf-8")
        tmp.replace(TORRENT_METADATA_CACHE_FILE)
    except Exception as exc:
        logger.info("Metadata cache save skipped: %s", exc)


async def _fetch_itorrents_metadata(info_hash_value: str) -> dict[str, Any] | None:
    """Try the public iTorrents descriptor cache before network metadata discovery."""
    target = info_hash_value.strip().lower()
    if not TORRENT_METADATA_ITORRENTS_BASE_URL or not re.fullmatch(r"[0-9a-f]{40}", target):
        return None

    url = f"{TORRENT_METADATA_ITORRENTS_BASE_URL}/{target}.torrent"
    try:
        async with _InstrumentedAsyncClient(
            timeout=TORRENT_METADATA_ITORRENTS_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "Torrent-Studio/1.0"},
        ) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return None
            body = response.content
    except httpx.HTTPError as exc:
        logger.info("iTorrents cache lookup failed for %s: %s", target, exc)
        return None

    if len(body) > 8 * 1024 * 1024 or not body.startswith(b"d") or b"4:info" not in body:
        return None

    try:
        result = _metadata_from_torrent_bytes(body, target, "itorrents_cache")
    except (ValueError, TypeError) as exc:
        logger.info("iTorrents returned invalid metadata for %s: %s", target, exc)
        return None
    logger.info("Metadata cache hit for %s via iTorrents", target)
    return result


async def _fetch_source_torrent_descriptor(source_url: str, info_hash_value: str) -> dict[str, Any] | None:
    """Try to obtain a real .torrent descriptor from a trusted search detail URL."""
    if not source_url:
        return None

    try:
        parsed = urlsplit(source_url)
        host = (parsed.hostname or "").lower().rstrip(".")
    except Exception:
        return None

    # Search results currently expose Knaben detail URLs. Keep this narrowly
    # scoped rather than turning the endpoint into an arbitrary URL fetcher.
    allowed_hosts = {
        "knaben.org", "www.knaben.org", "api.knaben.org",
        "knaben.eu", "www.knaben.eu",
        "knaben.xyz", "www.knaben.xyz",
    }
    if host not in allowed_hosts:
        return None

    candidates = [source_url]
    try:
        async with _InstrumentedAsyncClient(
            timeout=8.0,
            follow_redirects=True,
            headers={"User-Agent": "Torrent-Studio/1.0"},
        ) as client:
            response = await client.get(source_url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()

            if "bittorrent" in content_type or source_url.lower().split("?", 1)[0].endswith(".torrent"):
                candidates = [str(response.url)]
                raw = response.content
            else:
                html = response.text
                soup = BeautifulSoup(html, "html.parser")
                for anchor in soup.find_all("a", href=True):
                    href = str(anchor.get("href") or "").strip()
                    absolute = urljoin(str(response.url), href)
                    if absolute.lower().split("?", 1)[0].endswith(".torrent"):
                        candidates.append(absolute)

                # Some indexers expose a download attribute without a .torrent
                # suffix in the visible URL.
                for anchor in soup.find_all("a", href=True):
                    href = str(anchor.get("href") or "").strip()
                    absolute = urljoin(str(response.url), href)
                    label = " ".join(anchor.stripped_strings).lower()
                    if "torrent" in label and absolute not in candidates:
                        candidates.append(absolute)

                raw = None

            for candidate in candidates[:8]:
                try:
                    if raw is None or candidate != str(response.url):
                        descriptor = await client.get(candidate)
                        descriptor.raise_for_status()
                        candidate_type = descriptor.headers.get("content-type", "").lower()
                        body = descriptor.content
                    else:
                        candidate_type = content_type
                        body = raw

                    if len(body) > 8 * 1024 * 1024:
                        continue
                    if body.startswith(b"d") and b"4:info" in body:
                        return _metadata_from_torrent_bytes(
                            body,
                            info_hash_value,
                            "search_torrent_descriptor",
                        )
                except Exception:
                    continue
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Direct torrent descriptor lookup failed: %s", exc)

    return None


def _metadata_magnet_with_trackers(magnet: str) -> str:
    """Add the known-good HTTP trackers used by the fast WebTorrent test."""
    try:
        parsed = urlsplit(magnet)
        params = parse_qs(parsed.query, keep_blank_values=True)
        rebuilt: list[tuple[str, str]] = []
        for key in ("xt", "dn"):
            for value in params.get(key, []):
                if value:
                    rebuilt.append((key, str(value)))
        existing = {str(value).strip() for value in params.get("tr", []) if value}
        for tracker in FAST_SEARCH_TRACKERS:
            if tracker not in existing:
                rebuilt.append(("tr", tracker))
        return "magnet:?" + urlencode(rebuilt, doseq=True)
    except Exception:
        return magnet


async def _fetch_fast_test_metadata(magnet: str, info_hash_value: str) -> dict[str, Any] | None:
    """Use the proven WebTorrent resolver service as a metadata-only race participant."""
    if not FAST_SEARCH_TEST_URL:
        return None

    try:
        async with _InstrumentedAsyncClient(
            timeout=4.0,
            follow_redirects=True,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        ) as client:
            response = await client.post(
                FAST_SEARCH_TEST_URL + "/api/metadata",
                json={"magnet": magnet},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.info("Fast WebTorrent metadata service failed for %s: %s", info_hash_value, exc)
        return None

    if not isinstance(payload, dict):
        return None

    if str(payload.get("status") or "").lower() == "completed" and isinstance(payload.get("files"), list):
        metadata = payload
    else:
        job_id = str(payload.get("jobId") or "").strip()
        if not job_id:
            return None

        deadline = time.monotonic() + min(
            12.0,
            max(0.0, TORRENT_METADATA_JOB_TIMEOUT_SECONDS),
        )
        metadata = None
        while time.monotonic() < deadline:
            await asyncio.sleep(0.75)
            remaining = max(0.5, deadline - time.monotonic())
            try:
                async with _InstrumentedAsyncClient(
                    timeout=min(3.0, remaining),
                    follow_redirects=True,
                    headers={"Accept": "application/json"},
                ) as poll_client:
                    poll_response = await poll_client.get(
                        FAST_SEARCH_TEST_URL + "/api/metadata-jobs/" + quote(job_id, safe=""),
                    )
                    if poll_response.status_code == 404:
                        return None
                    poll_response.raise_for_status()
                    poll = poll_response.json()
            except (httpx.HTTPError, ValueError, TypeError):
                continue

            job = poll.get("job") if isinstance(poll, dict) else None
            if not isinstance(job, dict):
                continue
            if str(job.get("status") or "").lower() == "completed":
                candidate = job.get("metadata")
                if isinstance(candidate, dict) and isinstance(candidate.get("files"), list):
                    metadata = candidate
                    break
            if str(job.get("status") or "").lower() == "failed":
                return None

        if metadata is None:
            return None

    returned_hash = str(metadata.get("infoHash") or metadata.get("hash") or "").strip().lower()
    if returned_hash and returned_hash != info_hash_value.lower():
        logger.info(
            "Fast WebTorrent metadata hash mismatch: wanted %s, got %s",
            info_hash_value,
            returned_hash,
        )
        return None

    raw_files = metadata.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        return None

    files: list[dict[str, Any]] = []
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or item.get("name") or "").strip()
        if not path:
            continue
        files.append({
            "index": int(item.get("index") if item.get("index") is not None else index),
            "name": str(item.get("name") or path),
            "size": int(float(item.get("size") or 0)),
            "path": path,
            "type": "file",
            "priority": 1,
        })
    if not files:
        return None

    result = {
        "name": str(metadata.get("name") or files[0]["name"]),
        "hash": info_hash_value.lower(),
        "files": files,
        "totalSize": sum(int(item["size"]) for item in files),
        "source": "webtorrent_fast_test",
        "pending": False,
        "createdPreview": False,
        "message": "Torrent metadata loaded without starting Seedr.",
    }
    return result


def _metadata_from_torrent_bytes(raw: bytes, info_hash_value: str, source: str) -> dict[str, Any]:
    meta = decode_torrent_metadata(raw)
    info = meta.get(b"info")
    if not isinstance(info, dict):
        raise ValueError("torrent metadata has no info dictionary")

    def btext(value: Any) -> str:
        return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")

    name = btext(info.get(b"name")) or f"Torrent {info_hash_value[:8]}"
    files: list[dict[str, Any]] = []
    multi = info.get(b"files")
    if isinstance(multi, list):
        for index, item in enumerate(multi):
            if not isinstance(item, dict):
                continue
            parts = item.get(b"path") or []
            relative = "/".join(btext(part) for part in parts) if isinstance(parts, list) else btext(parts)
            files.append({
                "index": index,
                "name": relative or name,
                "size": int(item.get(b"length") or 0),
                "path": relative or name,
                "type": "file",
                "priority": 1,
            })
    else:
        files.append({
            "index": 0,
            "name": name,
            "size": int(info.get(b"length") or 0),
            "path": name,
            "type": "file",
            "priority": 1,
        })

    result = {
        "name": name,
        "hash": info_hash_value.lower(),
        "files": files,
        "totalSize": sum(int(item.get("size") or 0) for item in files),
        "source": source,
        "pending": False,
        "createdPreview": False,
        "message": "Torrent metadata loaded without starting Seedr.",
    }
    _metadata_cache[info_hash_value.lower()] = result
    _save_metadata_cache()
    return result


async def _get_libtorrent_session() -> Any:
    global _libtorrent_session, _libtorrent_session_lock
    if _libtorrent_session is not None:
        return _libtorrent_session
    if _libtorrent_session_lock is None:
        _libtorrent_session_lock = asyncio.Lock()
    async with _libtorrent_session_lock:
        if _libtorrent_session is not None:
            return _libtorrent_session
        session = lt.session()
        session.apply_settings({
            "enable_dht": False,
            "enable_lsd": False,
            "enable_upnp": False,
            "enable_natpmp": False,
            "enable_outgoing_tcp": True,
            "enable_outgoing_utp": True,
            "enable_incoming_tcp": True,
            "enable_incoming_utp": True,
            "listen_interfaces": "0.0.0.0:0",
            "dht_bootstrap_nodes": "",
            "announce_to_all_trackers": True,
            "announce_to_all_tiers": True,
            "connection_speed": 50,
            "handshake_timeout": 10,
        })
        _libtorrent_session = session
        logger.info("Started persistent libtorrent metadata session")
        return session


def _metadata_from_libtorrent_sync(magnet: str, info_hash_value: str) -> dict[str, Any]:
    tmp = tempfile.mkdtemp(prefix="torrent-metadata-lt-")
    session = _libtorrent_session
    if session is None:
        raise RuntimeError("libtorrent session is not initialized")

    handle = None
    try:
        atp = lt.parse_magnet_uri(_metadata_magnet_with_trackers(magnet))
        atp.save_path = tmp
        atp.flags = atp.flags | lt.torrent_flags.upload_mode
        atp.flags = atp.flags & ~lt.torrent_flags.auto_managed
        handle = session.add_torrent(atp)

        deadline = time.monotonic() + TORRENT_METADATA_JOB_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if handle.has_metadata():
                ti = handle.torrent_file()
                if ti is None:
                    raise RuntimeError("libtorrent returned metadata without torrent info")
                fs = ti.layout()
                files = []
                for index in range(fs.num_files()):
                    path = str(fs.file_path(index))
                    files.append({
                        "index": index,
                        "name": path,
                        "size": int(fs.file_size(index)),
                        "path": path,
                        "type": "file",
                        "priority": 1,
                    })
                return {
                    "name": str(ti.name() or f"Torrent {info_hash_value[:8]}"),
                    "hash": info_hash_value.lower(),
                    "files": files,
                    "totalSize": sum(int(item["size"]) for item in files),
                    "source": "libtorrent_metadata",
                    "pending": False,
                    "createdPreview": False,
                    "message": "Torrent metadata loaded without starting Seedr.",
                }

            for alert in session.pop_alerts():
                message = str(alert)
                if "error" in message.lower() or "tracker" in message.lower():
                    logger.info("libtorrent metadata alert: %s", message[:500])
            time.sleep(0.2)

        status = handle.status()
        raise TimeoutError(
            f"Metadata is still resolving (state={status.state}, "
            f"peers={status.num_peers}, seeds={status.num_seeds})"
        )
    finally:
        try:
            if handle is not None and handle.is_valid():
                session.remove_torrent(handle)
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


async def _schedule_metadata_job_expiry(job_id: str) -> None:
    try:
        await asyncio.sleep(TORRENT_METADATA_JOB_RETENTION_SECONDS)
    except asyncio.CancelledError:
        return
    job = _metadata_jobs.get(job_id)
    if job and job.get("status") in {"ready", "error"}:
        _metadata_jobs.pop(job_id, None)


async def _run_metadata_job(job_id: str, magnet: str, info_hash_value: str) -> None:
    """Keep retrying independent metadata sources for up to the configured background TTL."""
    job = _metadata_jobs[job_id]
    started_at = float(job.get("startedAt") or time.time())
    deadline_at = float(job.get("deadlineAt") or (started_at + TORRENT_METADATA_BACKGROUND_TTL_SECONDS))
    job.update({
        "status": "resolving",
        "startedAt": started_at,
        "updatedAt": time.time(),
        "deadlineAt": deadline_at,
        "rounds": int(job.get("rounds") or 0),
    })

    async def resolve_libtorrent() -> dict[str, Any] | None:
        session = await _get_libtorrent_session()
        return await asyncio.to_thread(
            _metadata_from_libtorrent_sync,
            magnet,
            info_hash_value,
        )

    while time.time() < deadline_at:
        job["rounds"] = int(job.get("rounds") or 0) + 1
        job["updatedAt"] = time.time()

        # Shared public cache is the fastest path and costs no torrent peer work.
        cached_result = await _fetch_itorrents_metadata(info_hash_value)
        if cached_result:
            job.update({
                "status": "ready",
                "result": cached_result,
                "error": None,
                "updatedAt": time.time(),
            })
            logger.info("Metadata job %s resolved via iTorrents cache on round %s", job_id, job["rounds"])
            asyncio.create_task(_schedule_metadata_job_expiry(job_id))
            return

        remote_task = asyncio.create_task(
            _fetch_remote_torrent_metadata(magnet, info_hash_value)
        )
        knaben_task = asyncio.create_task(_lookup_knaben_by_hash(info_hash_value))
        webtorrent_task = asyncio.create_task(
            _fetch_fast_test_metadata(
                _metadata_magnet_with_trackers(magnet),
                info_hash_value,
            )
        )
        libtorrent_task = asyncio.create_task(resolve_libtorrent())
        tasks = (remote_task, knaben_task, webtorrent_task, libtorrent_task)
        errors: list[str] = []
        winner: dict[str, Any] | None = None

        try:
            # Race the independent remote/indexer/libtorrent paths. The first
            # usable file list wins; the libtorrent worker finishes before a
            # retry round begins so the same torrent is never added twice.
            for task in asyncio.as_completed(tasks):
                try:
                    result = await task
                except TimeoutError as exc:
                    errors.append(str(exc))
                    continue
                except Exception as exc:
                    errors.append(str(exc))
                    continue
                if result and isinstance(result, dict) and result.get("files"):
                    winner = result
                    break

            if winner:
                _metadata_cache[info_hash_value.lower()] = winner
                _save_metadata_cache()
                job.update({
                    "status": "ready",
                    "result": winner,
                    "error": None,
                    "updatedAt": time.time(),
                })
                logger.info(
                    "Metadata job %s resolved via %s on round %s",
                    job_id,
                    winner.get("source", "unknown"),
                    job["rounds"],
                )
                return
        finally:
            for task in (remote_task, knaben_task, webtorrent_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                remote_task,
                knaben_task,
                webtorrent_task,
                return_exceptions=True,
            )

            # asyncio.to_thread cannot force-stop the libtorrent worker.
            # When another resolver already won, let that worker finish in the
            # shared session without delaying the successful response. When the
            # round failed, wait for it before starting the next retry round so
            # the same torrent is never added twice concurrently.
            if winner is None:
                try:
                    await libtorrent_task
                except Exception as exc:
                    errors.append(str(exc))

        if time.time() >= deadline_at:
            break
        delay = min(
            max(0, TORRENT_METADATA_BACKGROUND_RETRY_SECONDS),
            max(0, deadline_at - time.time()),
        )
        job["updatedAt"] = time.time()
        if delay > 0:
            await asyncio.sleep(delay)

    job.update({
        "status": "error",
        "error": "Torrent metadata could not be resolved within 6 hours.",
        "updatedAt": time.time(),
    })
    logger.warning("Metadata job %s exhausted its background deadline", job_id)
    asyncio.create_task(_schedule_metadata_job_expiry(job_id))


_load_metadata_cache()


# Compatibility endpoints for the preserved UI. They intentionally do not run
# qBittorrent or maintain local torrent storage; Seedr is the only transfer backend.
@router.get("/api/v2/torrents/info")
async def empty_torrents(filter: str | None = None):
    return []

def _libtorrent_metadata_sync(magnet: str) -> tuple[str, str, list[dict[str, Any]], int]:
    """Resolve only torrent metadata using libtorrent; never request content pieces."""
    tmp = tempfile.mkdtemp(prefix="torrent-metadata-lt-")
    ses = None
    handle = None
    try:
        ses = lt.session()

        # Explicitly enable the discovery paths needed for magnet metadata on
        # a cloud host. Keep UPnP/NAT-PMP/LSd off: they are not useful on
        # Render and can add connection delay. DHT + tracker access remain on.
        ses.apply_settings({
            "enable_dht": True,
            "enable_lsd": False,
            "enable_upnp": False,
            "enable_natpmp": False,
            "enable_outgoing_tcp": True,
            "enable_outgoing_utp": True,
            "enable_incoming_tcp": True,
            "enable_incoming_utp": True,
            "listen_interfaces": "0.0.0.0:0",
            "dht_bootstrap_nodes": (
                "router.bittorrent.com:6881,"
                "router.utorrent.com:6881,"
                "dht.transmissionbt.com:6881"
            ),
            "use_dht_as_fallback": False,
            "announce_to_all_trackers": True,
            "announce_to_all_tiers": True,
            "connection_speed": 50,
            "handshake_timeout": 10,
        })

        atp = lt.parse_magnet_uri(magnet)
        atp.save_path = tmp

        # upload_mode prevents piece requests. Disable auto-management so the
        # session cannot later take the torrent out of upload mode automatically.
        atp.flags = atp.flags | lt.torrent_flags.upload_mode
        atp.flags = atp.flags & ~lt.torrent_flags.auto_managed

        handle = ses.add_torrent(atp)

        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if handle.has_metadata():
                break
            for alert in ses.pop_alerts():
                message = str(alert)
                if "error" in message.lower() or "tracker" in message.lower() or "dht" in message.lower():
                    logger.info("libtorrent alert for %s: %s", info_hash(magnet), message[:500])
            time.sleep(0.15)

        if not handle.has_metadata():
            status = handle.status()
            raise TimeoutError(
                f"libtorrent metadata timeout (state={status.state}, "
                f"peers={status.num_peers}, seeds={status.num_seeds})"
            )

        ti = handle.torrent_file()
        if ti is None:
            raise RuntimeError("libtorrent reported metadata but torrent_file() is empty")

        fs = ti.layout()
        torrent_name = str(ti.name() or "")
        files: list[dict[str, Any]] = []
        for index in range(fs.num_files()):
            path = str(fs.file_path(index))
            size = int(fs.file_size(index))
            if not path:
                continue
            files.append({
                "index": index,
                "name": path,
                "size": size,
                "path": path,
                "type": "file",
                "priority": 1,
            })

        total_size = sum(int(item.get("size") or 0) for item in files)
        return torrent_name, magnet, files, total_size
    finally:
        try:
            if ses is not None and handle is not None and handle.is_valid():
                ses.remove_torrent(handle)
        except Exception:
            pass
        try:
            if ses is not None:
                del ses
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


async def _fetch_remote_torrent_metadata(magnet: str, info_hash_value: str) -> dict[str, Any] | None:
    """Use the public torrent-metadata resolver as a metadata-only fallback."""
    if not TORRENT_METADATA_API_URL:
        return None
    try:
        # This service resolves BEP-9 metadata from a magnet without starting
        # a file download. Give Fly.io enough time to wake a sleeping instance.
        async with _InstrumentedAsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.post(
                TORRENT_METADATA_API_URL.rstrip("/") + "/",
                json={"query": magnet},
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("Remote metadata service failed for %s: %s", info_hash_value, exc)
        return None

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None
    returned_hash = str(data.get("infoHash") or "").strip().lower()
    if returned_hash and returned_hash != info_hash_value.lower():
        logger.info("Remote metadata hash mismatch: wanted %s, got %s", info_hash_value, returned_hash)
        return None

    raw_files = data.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        return None

    files: list[dict[str, Any]] = []
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or item.get("name") or "").strip()
        if not path:
            continue
        files.append({
            "index": index,
            "name": str(item.get("name") or path),
            "size": int(float(item.get("size") or 0)),
            "path": path,
            "type": "file",
            "priority": 1,
        })
    if not files:
        return None

    result = {
        "name": str(data.get("name") or files[0]["name"]),
        "hash": info_hash_value.lower(),
        "files": files,
        "totalSize": sum(int(item["size"]) for item in files),
        "source": "remote_torrent_metadata",
        "pending": False,
        "createdPreview": False,
        "message": "Torrent metadata loaded without starting Seedr.",
    }
    _metadata_cache[info_hash_value.lower()] = result
    _save_metadata_cache()
    return result


async def _lookup_knaben_by_hash(info_hash_value: str) -> dict[str, Any] | None:
    """Find and parse a Knaben cached descriptor for an exact info-hash."""
    target = info_hash_value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", target):
        return None

    payload_base = {
        "search_type": "100%",
        "query": target,
        "from": 0,
        "size": 20,
        "hide_unsafe": False,
        "hide_xxx": False,
    }

    async with _InstrumentedAsyncClient(timeout=6.0, follow_redirects=True) as client:
        for field in ("hash", None):
            payload = dict(payload_base)
            if field:
                payload["search_field"] = field
            try:
                response = await client.post(
                    KNABEN_API_URL,
                    json=payload,
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError):
                continue

            hits = data.get("hits") if isinstance(data, dict) else None
            if not isinstance(hits, list):
                continue

            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                hit_hash = str(hit.get("hash") or "").strip().lower()
                if hit_hash != target:
                    continue

                descriptor = str(hit.get("link") or "").strip()
                if descriptor:
                    parsed = await _fetch_source_torrent_descriptor(descriptor, target)
                    if parsed:
                        return parsed

                details = str(hit.get("details") or "").strip()
                if details:
                    parsed = await _fetch_source_torrent_descriptor(details, target)
                    if parsed:
                        return parsed
    return None


@router.post("/api/v2/torrents/inspect-magnet")
async def seedr_inspect_magnet(body: dict[str, Any]):
    """Return cached metadata immediately or start a background resolver."""
    raw_magnet = str(body.get("magnet") or body.get("source") or "").strip()
    if not raw_magnet:
        raise HTTPException(400, "A magnet link is required")

    magnet = normalize_magnet(raw_magnet)
    h = info_hash(magnet)
    if not h:
        raise HTTPException(400, "A valid BTIH magnet link is required")
    h = h.lower()

    cached = _metadata_cache.get(h)
    if cached:
        return cached

    # Shared public cache is the fastest metadata path for both pasted magnets
    # and search results. It never starts Seedr or requests payload pieces.
    cached_descriptor = await _fetch_itorrents_metadata(h)
    if cached_descriptor:
        return cached_descriptor

    # Search results can carry a detail URL. When that page exposes a real
    # .torrent descriptor, use it before touching DHT/trackers.
    descriptor_url = str(body.get("descriptorUrl") or "").strip()
    source_url = str(body.get("sourceUrl") or body.get("infoUrl") or "").strip()

    # First use an actual descriptor URL returned by the indexer.
    for candidate_url in (descriptor_url, source_url):
        if candidate_url:
            descriptor_result = await _fetch_source_torrent_descriptor(candidate_url, h)
            if descriptor_result:
                return descriptor_result

    # Search results may have an exact hash cached by Knaben. For a pasted
    # magnet there is no source URL, so do this lookup in the background rather
    # than making the user wait on a second network request before the job starts.
    if descriptor_url or source_url:
        try:
            hash_result = await _lookup_knaben_by_hash(h)
        except Exception as exc:
            logger.info("Knaben hash lookup failed for %s: %s", h, exc)
            hash_result = None
        if hash_result:
            return hash_result

    job_id = h
    existing = _metadata_jobs.get(job_id)
    if existing and existing.get("status") == "ready" and existing.get("result"):
        return existing["result"]

    if not existing or existing.get("status") == "error":
        now = time.time()
        _metadata_jobs[job_id] = {
            "status": "queued",
            "jobId": job_id,
            "hash": h,
            "name": str(parse_qs(urlsplit(magnet).query).get("dn", [""])[0] or "").strip(),
            "startedAt": now,
            "updatedAt": now,
            "deadlineAt": now + TORRENT_METADATA_BACKGROUND_TTL_SECONDS,
            "rounds": 0,
            "error": None,
        }
        asyncio.create_task(_run_metadata_job(job_id, magnet, h))

    # Give a fast first attempt a short window. Slow metadata resolution
    # continues in the background and is polled by the frontend.
    for _ in range(10):
        await asyncio.sleep(0.2)
        job = _metadata_jobs.get(job_id, {})
        if job.get("status") == "ready" and job.get("result"):
            return job["result"]
        if job.get("status") == "error":
            raise HTTPException(502, str(job.get("error") or "Metadata lookup failed"))

    return JSONResponse(
        status_code=202,
        content={
            "status": "resolving",
            "jobId": job_id,
            "hash": h,
            "source": "libtorrent_metadata",
            "message": "Torrent metadata is still resolving. Seedr has not been started.",
        },
    )


@router.get("/api/v2/torrents/metadata-jobs")
async def seedr_metadata_jobs():
    now = time.time()
    jobs: list[dict[str, Any]] = []
    for job in _metadata_jobs.values():
        started = float(job.get("startedAt") or now)
        deadline = float(job.get("deadlineAt") or started)
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        files = result.get("files") if isinstance(result.get("files"), list) else []
        jobs.append({
            "jobId": str(job.get("jobId") or job.get("hash") or ""),
            "hash": str(job.get("hash") or "").lower(),
            "name": str(job.get("name") or result.get("name") or "").strip(),
            "status": str(job.get("status") or "resolving"),
            "rounds": int(job.get("rounds") or 0),
            "startedAt": started,
            "updatedAt": float(job.get("updatedAt") or started),
            "deadlineAt": deadline,
            "elapsedSeconds": max(0, int(now - started)),
            "remainingSeconds": max(0, int(deadline - now)),
            "fileCount": len(files),
            "totalSize": int(result.get("totalSize") or 0),
            "source": str(result.get("source") or "background_metadata"),
            "error": str(job.get("error") or "") or None,
        })
    jobs.sort(key=lambda item: float(item.get("startedAt") or 0), reverse=True)
    return {
        "jobs": jobs,
        "backgroundTtlSeconds": TORRENT_METADATA_BACKGROUND_TTL_SECONDS,
        "retentionSeconds": TORRENT_METADATA_JOB_RETENTION_SECONDS,
    }


@router.get("/api/v2/torrents/inspect-magnet/status")
async def seedr_inspect_magnet_status(jobId: str = Query(...)):
    job = _metadata_jobs.get(jobId.lower())
    if not job:
        cached = _metadata_cache.get(jobId.lower())
        if cached:
            return cached
        raise HTTPException(404, "Metadata job not found")

    if job.get("status") == "ready" and job.get("result"):
        return job["result"]

    if job.get("status") == "error":
        raise HTTPException(502, str(job.get("error") or "Metadata lookup failed"))

    now = time.time()
    started = float(job.get("startedAt") or now)
    deadline = float(job.get("deadlineAt") or started)
    return {
        "status": "resolving",
        "jobId": jobId,
        "hash": jobId,
        "name": str(job.get("name") or ""),
        "rounds": int(job.get("rounds") or 0),
        "startedAt": started,
        "updatedAt": float(job.get("updatedAt") or started),
        "deadlineAt": deadline,
        "elapsedSeconds": max(0, int(now - started)),
        "remainingSeconds": max(0, int(deadline - now)),
        "source": "background_metadata",
        "message": job.get("error") or "Torrent metadata is still resolving in the background. Seedr has not been started.",
    }
