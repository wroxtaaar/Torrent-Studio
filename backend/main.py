import asyncio
from html import unescape
import base64
import contextvars
import secrets
from datetime import date, datetime, timedelta, timezone
from collections import deque
import gzip
import json
import hashlib
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit

import httpx
import libtorrent as lt
from cryptography.fernet import Fernet, InvalidToken
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel


from cache_diagnostics import (
    _CACHE_DIAGNOSTICS,
    _CACHE_DIAGNOSTICS_STARTED_AT,
    _UPSTREAM_FEATURE,
    _InstrumentedAsyncClient,
    _record_cache_event,
    _record_upstream_request,
    _upstream_provider_name,
    _upstream_endpoint_group,
)
from nexstream import nexstream_api_key_configured, resolve_nexstream_movie

from settings import (
    ALLOW_LEGACY_SEEDR_TOKEN,
    APP_NAME,
    CACHE_ONLY_MODE,
    CORS_ORIGINS,
    CORS_ORIGIN_REGEX,
    DC_TV_CATALOGUE_CACHE_FILE,
    DEBUG_ENDPOINTS_ENABLED,
    FAST_SEARCH_TEST_URL,
    FAST_SEARCH_TRACKERS,
    FEEDBACK_GLOBAL_RATE_LIMIT,
    FEEDBACK_RATE_LIMIT,
    FEEDBACK_RATE_WINDOW_SECONDS,
    GITHUB_FEEDBACK_REPO,
    GITHUB_FEEDBACK_TOKEN,
    IMDB_RATING_CACHE_FILE,
    IMDB_RATING_CACHE_TTL_SECONDS,
    IMDB_RATING_LOOKUP_VERSION,
    IMDB_RATING_NOT_FOUND_TTL_SECONDS,
    KNABEN_API_URL,
    MARVEL_TV_CATALOGUE_CACHE_FILE,
    MAX_SEARCH_RESULT_SIZE_BYTES,
    MIN_SEARCH_RESULT_SIZE_BYTES,
    REGIONAL_MOVIE_CACHE_PAGE_SIZE,
    REGIONAL_MOVIE_CACHE_TTL_SECONDS,
    REGIONAL_MOVIE_CATALOGUE_KEYS,
    REGIONAL_MOVIE_PREWARM_PAGES,
    REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE,
    REGIONAL_MOVIE_TRENDING_ARCHIVE_WEEKS,
    REGIONAL_TV_PREBUILT_CACHE_FILE,
    SEARCH_CACHE_MAX_ENTRIES,
    SEARCH_CACHE_MIN_RESULTS,
    SEARCH_CACHE_SECONDS,
    SEARCH_CACHE_STALE_SECONDS,
    SEARCH_COMPOUND_ALIASES,
    SEARCH_SOURCE_TIMEOUT_SECONDS,
    SEARCH_TOTAL_TIMEOUT_SECONDS,
    SEEDR_BASE,
    SEEDR_DEVICE_AUTHORIZE_URL,
    SEEDR_DEVICE_CLIENT_ID,
    SEEDR_DEVICE_CODE_URL,
    SEEDR_MEDIA_BASE,
    SEEDR_PAT_BASE,
    SEEDR_SESSION_COOKIE,
    SEEDR_SESSION_SAMESITE,
    SEEDR_SESSION_SECRET,
    SEEDR_SESSION_TTL_SECONDS,
    SEEDR_TOKEN,
    SEEDR_V2_BASE,
    STREAMING_AVAILABILITY_API_BASE,
    STREAMING_AVAILABILITY_API_KEY,
    SYNOPSIS_CACHE_RETRY_INTERVAL_SECONDS,
    TMDB_API_BASE,
    TMDB_API_KEYS,
    TMDB_CATALOGUE_CACHE_FILE,
    TMDB_CATALOGUE_CACHE_SECONDS,
    TMDB_COMPANY_CACHE_SECONDS,
    TMDB_IMAGE_BASE,
    TMDB_OTT_CACHE_FILE,
    TMDB_OTT_CACHE_SECONDS,
    TMDB_OTT_INCOMPLETE_CACHE_SECONDS,
    TMDB_OTT_MISSING_CACHE_SECONDS,
    TMDB_READ_ACCESS_TOKENS,
    TMDB_SEARCH_METADATA_CACHE_FILE,
    TMDB_SEARCH_METADATA_QUERY_TTL_SECONDS,
    TMDB_SYNOPSIS_LOOKUP_VERSION,
    TORRENT_METADATA_API_URL,
    TORRENT_METADATA_BACKGROUND_RETRY_SECONDS,
    TORRENT_METADATA_BACKGROUND_TTL_SECONDS,
    TORRENT_METADATA_CACHE_FILE,
    TORRENT_METADATA_ITORRENTS_BASE_URL,
    TORRENT_METADATA_ITORRENTS_TIMEOUT_SECONDS,
    TORRENT_METADATA_JOB_RETENTION_SECONDS,
    TORRENT_METADATA_JOB_TIMEOUT_SECONDS,
    TORRENT_SEARCH_API_URL,
    WATCHMODE_API_BASE,
    WATCHMODE_API_KEYS,
    YTS_API_HOSTS,
    _CACHE_SEED_DIR,
    _split_env_keys,
    logger,
)

from shared import (
    SeedrError,
    _MANUAL_TORRENT_SEARCH,
    _REGIONAL_MOVIE_CATALOGUE_FORCE_REFRESH,
    _REGIONAL_MOVIE_SOURCE_FORCE_REFRESH,
    _REGIONAL_MOVIE_SOURCE_REFRESHED_KEYS,
    _seedr_request_session_id,
    _seedr_request_token,
)

from tmdb import (
    _OMDB_REQUEST_SEMAPHORE,
    _PROVIDER_KEY_CURSORS,
    _close_tmdb_http_client,
    _omdb_client,
    _omdb_rate_limit_for,
    _omdb_rate_limited_until,
    _provider_key_available,
    _provider_key_failure,
    _provider_key_success,
    _read_tmdb_ott_persistent_cache,
    _read_tmdb_persistent_cache,
    _retry_after_seconds,
    _tmdb_company_id_cache,
    _tmdb_company_inflight,
    _tmdb_fetch_movie_ott_availability,
    _tmdb_get_json,
    _tmdb_movie_catalogue_cache,
    _tmdb_movie_catalogue_inflight,
    _tmdb_ott_cache,
    _tmdb_ott_disk_key,
    _tmdb_ott_inflight,
    _tmdb_ott_ttl,
    _watchmode_get,
    _watchmode_provider_rows,
    _write_tmdb_ott_persistent_cache,
    _write_tmdb_persistent_cache,
)

_IMDB_RATING_CACHE: dict[str, dict[str, Any]] | None = None
_IMDB_RATING_CACHE_LOCK = asyncio.Lock()
_IMDB_RATING_INFLIGHT: dict[str, asyncio.Task[dict[str, Any]]] = {}

from feedback import router as feedback_router

from seedr_session import (
    _clear_seedr_session_token,
    _seedr_get_session,
    _seedr_new_session,
    _seedr_restore_session,
    _seedr_session_auth_mode,
    _seedr_session_cookie_value,
    _seedr_session_csrf_ok,
    _seedr_session_fingerprint,
    _seedr_session_token,
    _seedr_sessions,
    current_seedr_token,
    normalize_seedr_token,
)

from search_providers import (
    LIMETORRENTS_HOSTS,
    X1337_HOSTS,
    _normalize_title,
    _search_1337x_uncached,
    _search_tokens,
    parse_size,
    search_1337x,
    search_1337x_direct,
    search_limetorrents,
    search_yts_movies,
)

# Rolling server-side byte counters for browser media streams. This is more
# reliable than Resource Timing for long-lived media responses, which browsers
# may report with transferSize=0 until the response completes.
_media_download_stats: dict[str, deque[tuple[float, int]]] = {}
_media_stats_lock = asyncio.Lock()
_MEDIA_STATS_WINDOW_SECONDS = 5.0

def _record_media_bytes(file_id: str, amount: int) -> None:
    if amount <= 0:
        return
    now = time.monotonic()
    bucket = _media_download_stats.setdefault(file_id, deque())
    bucket.append((now, amount))
    cutoff = now - _MEDIA_STATS_WINDOW_SECONDS
    while bucket and bucket[0][0] < cutoff:
        bucket.popleft()

def _media_download_speed(file_id: str) -> float:
    now = time.monotonic()
    bucket = _media_download_stats.get(file_id)
    if not bucket:
        return 0.0
    cutoff = now - _MEDIA_STATS_WINDOW_SECONDS
    while bucket and bucket[0][0] < cutoff:
        bucket.popleft()
    if not bucket:
        return 0.0
    total = sum(amount for _, amount in bucket)
    span = max(0.5, now - bucket[0][0])
    return total / span

from torrent_metadata import MagnetRequest, router as torrent_metadata_router


app = FastAPI(title=APP_NAME)


def _diagnostic_feature_for_path(path: str) -> str:
    cleaned = re.sub(r"/movie-\d+(?=/|$)", "/movie-{id}", path or "/")
    cleaned = re.sub(r"(?<=/)\d+(?=/|$)", "{id}", cleaned)
    return "request:" + cleaned[:120]


@app.middleware("http")
async def _set_upstream_diagnostic_feature(request: Request, call_next):
    token = _UPSTREAM_FEATURE.set(_diagnostic_feature_for_path(request.url.path))
    try:
        return await call_next(request)
    finally:
        _UPSTREAM_FEATURE.reset(token)


@app.exception_handler(SeedrError)
async def handle_seedr_error(request: Request, exc: SeedrError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "detail": exc.detail,
            "code": exc.code,
            "provider": "seedr",
        },
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from http_cache import (
    _DATE_SORTED_EXTRA_CATALOGUES,
    _fast_json_response,
    _file_signature,
    _memoized_file_read,
    _page_catalogue_payload,
    _prebuilt_catalogue_page,
)

@app.middleware("http")
async def attach_seedr_session(request: Request, call_next):
    raw_cookie = str(request.cookies.get(SEEDR_SESSION_COOKIE) or "").strip()
    restored = _seedr_restore_session(raw_cookie)
    is_new = False

    if restored:
        session_id, restored_session = restored
        _seedr_sessions[session_id] = restored_session
    elif raw_cookie in _seedr_sessions:
        session_id = raw_cookie
    else:
        session_id, _ = _seedr_new_session()
        is_new = True

    session = _seedr_get_session(session_id)
    session["last_seen"] = time.time()

    token_ctx = _seedr_request_token.set(_seedr_session_token(session_id))
    session_ctx = _seedr_request_session_id.set(session_id)
    try:
        path = request.url.path or ""
        method = request.method.upper()
        # Every state-changing API call needs the session CSRF token, not only
        # /api/seedr/*: compatibility routes such as /api/files/delete and
        # /api/v2/torrents/* also act on the connected Seedr account.
        if path.startswith("/api/") and method not in {"GET", "HEAD", "OPTIONS"}:
            if not _seedr_session_csrf_ok(request):
                response = JSONResponse(
                    status_code=403,
                    content={"error": "Seedr session security check failed.", "code": "SEEDR_CSRF_INVALID"},
                )
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
    finally:
        _seedr_request_token.reset(token_ctx)
        _seedr_request_session_id.reset(session_ctx)

    is_https = (
        request.url.scheme.lower() == "https"
        or str(request.headers.get("x-forwarded-proto") or "").lower() == "https"
    )
    response.set_cookie(
        SEEDR_SESSION_COOKIE,
        _seedr_session_cookie_value(session_id, session),
        max_age=SEEDR_SESSION_TTL_SECONDS,
        httponly=True,
        secure=is_https,
        samesite=SEEDR_SESSION_SAMESITE if is_https else "lax",
        path="/",
    )

    now = time.time()
    if len(_seedr_sessions) > 2000:
        stale = [
            sid for sid, item in _seedr_sessions.items()
            if now - float(item.get("last_seen") or now) > SEEDR_SESSION_TTL_SECONDS
        ]
        for sid in stale:
            _seedr_sessions.pop(sid, None)

    return response


@app.middleware("http")
async def add_timing_allow_origin(request: Request, call_next):
    # Allows the frontend to read Resource Timing transfer sizes for the
    # cross-origin Render media stream when the frontend is hosted on Vercel.
    response = await call_next(request)
    response.headers["Timing-Allow-Origin"] = "*"
    return response

from seedr_client import (
    add_task,
    arr,
    folder_name,
    info_hash,
    legacy_seedr_list_contents,
    normalize_file,
    normalize_magnet,
    rename_seedr_folder,
    seedr_data,
    seedr_error_message,
    seedr_request,
    seedr_root_request,
    seedr_task_folder_id,
    seedr_task_name,
    task_complete,
    task_contents,
    task_id,
    unwrap_seedr_task,
)

SEEDR_FOLDER_CONCURRENCY = 8
_seedr_folder_semaphore = asyncio.Semaphore(SEEDR_FOLDER_CONCURRENCY)

# Library metadata is shared between the Files explorer and the Seedr Library
# so opening the Files tab does not trigger the same Seedr tree walk twice.
SEEDR_METADATA_CACHE_SECONDS = 5
SEEDR_FOLDER_CACHE_SECONDS = 15
_seedr_metadata_cache: tuple[float, dict[str, Any]] | None = None
_seedr_metadata_task: asyncio.Task | None = None
_seedr_folder_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_seedr_torrent_names: dict[str, str] = {}
_seedr_torrent_names_by_task: dict[str, str] = {}

SEEDR_AUTO_DELETE_SECONDS = 2 * 60 * 60
SEEDR_CLEANUP_FILE = Path("/app/.seedr_cleanup.json")
_seedr_cleanup_jobs: dict[str, dict[str, Any]] = {}
_seedr_cleanup_worker_task: asyncio.Task | None = None


def _load_seedr_cleanup_jobs() -> None:
    global _seedr_cleanup_jobs
    try:
        raw = SEEDR_CLEANUP_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            _seedr_cleanup_jobs = {
                str(k): v for k, v in data.items()
                if isinstance(v, dict) and float(v.get("deleteAt") or 0) > 0
            }
    except Exception:
        _seedr_cleanup_jobs = {}


def _save_seedr_cleanup_jobs() -> None:
    try:
        SEEDR_CLEANUP_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SEEDR_CLEANUP_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_seedr_cleanup_jobs, separators=(",", ":")), encoding="utf-8")
        tmp.replace(SEEDR_CLEANUP_FILE)
    except Exception as exc:
        logger.info("Could not persist Seedr cleanup schedule: %s", exc)


def schedule_seedr_cleanup(
    task_id_value: str,
    torrent_name: str,
    folder_id: str = "",
    added_at: float | None = None,
) -> None:
    tid = str(task_id_value or "").strip()
    if not tid:
        return

    now = time.time()
    started = float(added_at or now)
    _seedr_cleanup_jobs[tid] = {
        "taskId": tid,
        "torrentName": str(torrent_name or "").strip() or f"Torrent {tid}",
        "folderId": str(folder_id or "").strip(),
        "addedAt": started,
        "deleteAt": started + SEEDR_AUTO_DELETE_SECONDS,
    }
    _save_seedr_cleanup_jobs()


async def _cleanup_seedr_job(tid: str, job: dict[str, Any]) -> bool:
    folder_id = str(job.get("folderId") or "").strip()
    torrent_name = str(job.get("torrentName") or f"Torrent {tid}").strip()

    # Seedr may expose the folder only after the task starts.
    if not folder_id:
        try:
            raw = seedr_data(await seedr_request(f"/tasks/{quote(tid)}"))
            task = unwrap_seedr_task(raw)
            folder_id = seedr_task_folder_id(task)
            if folder_id:
                job["folderId"] = folder_id
                _save_seedr_cleanup_jobs()
        except HTTPException as exc:
            if exc.status_code == 404:
                _seedr_cleanup_jobs.pop(tid, None)
                _save_seedr_cleanup_jobs()
                return True
            return False
        except Exception:
            return False

    if not folder_id or not folder_id.isdigit() or folder_id == "0":
        return False

    # Stop the Seedr task first so an active transfer cannot keep rebuilding
    # files while the folder is being removed.
    try:
        await seedr_request(f"/tasks/{quote(tid)}", "DELETE")
    except HTTPException as exc:
        if exc.status_code != 404:
            logger.info("Seedr task cleanup failed for %s: HTTP %s", tid, exc.status_code)
            return False
    except Exception as exc:
        logger.info("Seedr task cleanup failed for %s: %s", tid, exc)
        return False

    try:
        await seedr_folder_delete(folder_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            logger.info("Seedr folder cleanup failed for %s (%s): HTTP %s", torrent_name, folder_id, exc.status_code)
            return False
    except Exception as exc:
        logger.info("Seedr folder cleanup failed for %s (%s): %s", torrent_name, folder_id, exc)
        return False

    _seedr_cleanup_jobs.pop(tid, None)
    _save_seedr_cleanup_jobs()
    logger.info("Auto-deleted Seedr torrent after 2 hours: %s (task=%s folder=%s)", torrent_name, tid, folder_id)
    return True


async def _seedr_cleanup_worker() -> None:
    while True:
        try:
            now = time.time()
            due = [
                (tid, job)
                for tid, job in list(_seedr_cleanup_jobs.items())
                if float(job.get("deleteAt") or 0) <= now
            ]
            for tid, job in due:
                await _cleanup_seedr_job(tid, job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("Seedr cleanup worker error: %s", exc)
        await asyncio.sleep(30)



async def collect_folder(folder_id: str, path: str = "/", depth: int = 0) -> list[dict[str, Any]]:
    if depth > 8:
        return []

    async with _seedr_folder_semaphore:
        try:
            payload = seedr_data(await seedr_request(f"/fs/folder/{quote(folder_id)}/contents"))
        except HTTPException as exc:
            if exc.status_code == 404:
                return []
            raise

    if not isinstance(payload, dict):
        return []

    files: list[dict[str, Any]] = []
    for raw in arr(payload, ("files", "items")):
        item = normalize_file(raw, folder_id)
        item["folderPath"] = path
        item["url"] = None
        files.append(item)

    child_jobs: list[asyncio.Future] = []
    for raw in arr(payload, ("folders", "directories")):
        child_id = str(raw.get("id") or raw.get("folder_id") or "") if isinstance(raw, dict) else ""
        if not child_id:
            continue

        child_name = (
            str(raw.get("name") or raw.get("title") or child_id)
            if isinstance(raw, dict)
            else child_id
        )
        child_path = path.rstrip("/") + "/" + child_name
        child_jobs.append(collect_folder(child_id, child_path, depth + 1))

    if child_jobs:
        children = await asyncio.gather(*child_jobs, return_exceptions=True)
        for child in children:
            if isinstance(child, list):
                files.extend(child)

    return files

def _safe_download_filename(filename: str, fallback: str) -> str:
    value = str(filename or "").strip().replace("\r", "").replace("\n", "")
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:240] or fallback


async def _stream_seedr_download(url: str):
    client = _InstrumentedAsyncClient(timeout=None, follow_redirects=True)
    request = client.build_request("GET", url, headers={"Accept": "*/*"})
    response = await client.send(request, stream=True)

    if response.status_code >= 400:
        try:
            detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
        finally:
            await response.aclose()
            await client.aclose()
        raise HTTPException(response.status_code, detail or "Seedr download request failed")

    content_type = response.headers.get("content-type") or "application/octet-stream"
    content_length = response.headers.get("content-length")
    content_range = response.headers.get("content-range")

    async def body():
        try:
            async for chunk in response.aiter_bytes(1024 * 1024):
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    headers = {
        "Content-Disposition": "",
        "Accept-Ranges": response.headers.get("accept-ranges", "bytes"),
        "Cache-Control": "no-store",
    }
    if content_length:
        headers["Content-Length"] = content_length
    if content_range:
        headers["Content-Range"] = content_range

    return body, content_type, headers


async def download_url(file_id: str) -> dict[str, str]:
    payload = seedr_data(await seedr_request(f"/download/file/{quote(file_id)}/url"))
    if isinstance(payload, dict):
        url = str(payload.get("url") or payload.get("download_url") or payload.get("downloadUrl") or payload.get("direct_url") or "")
        name = str(payload.get("name") or payload.get("filename") or "")
    else:
        url, name = str(payload or ""), ""
    if not url:
        raise HTTPException(502, "Seedr did not return a download URL")
    return {"url": url, "name": name}

def _srt_to_webvtt(text: str) -> str:
    """Convert a UTF-8/legacy SRT subtitle into browser-compatible WebVTT."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    lines = normalized.split("\n")
    output = ["WEBVTT", ""]
    for line in lines:
        if "-->" in line:
            line = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d{3})", r"\1.\2", line)
        output.append(line)
    result = "\n".join(output)
    return result if result.endswith("\n") else result + "\n"


async def _seedr_subtitle_text(file_id: str, filename: str) -> tuple[str, str]:
    result = await download_url(file_id)
    url = result["url"]
    lower = (filename or result.get("name") or "").lower()
    async with _InstrumentedAsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        raw = response.content

    if lower.endswith(".vtt"):
        text = raw.decode("utf-8-sig", errors="replace")
        if not text.lstrip().startswith("WEBVTT"):
            text = _srt_to_webvtt(text)
    elif lower.endswith(".srt"):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
        text = _srt_to_webvtt(text)
    else:
        raise HTTPException(415, "Only SRT and WebVTT subtitle files are supported")
    return text, "text/vtt; charset=utf-8"


@app.get("/api/seedr/files/{file_id}/subtitle")
async def seedr_file_subtitle(
    file_id: str,
    filename: str = Query(""),
):
    """Proxy a Seedr SRT/VTT file as WebVTT for the browser <track> element."""
    text, content_type = await _seedr_subtitle_text(file_id, filename)
    return Response(
        content=text,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )

from posters import (
    _canonical_catalogue_poster_url,
    _catalogue_row_has_3d_quality,
    _catalogue_row_is_excluded_franchise_title,
    _poster_lookup,
    _poster_url_for_release,
    _sort_cached_catalogue_results,
    router as posters_router,
)
app.include_router(posters_router)

@app.get("/")
async def root():
    return {"name": APP_NAME, "status": "ok"}

@app.on_event("startup")
async def start_seedr_cleanup_worker():
    global _seedr_cleanup_worker_task
    _load_seedr_cleanup_jobs()
    if _seedr_cleanup_worker_task is None or _seedr_cleanup_worker_task.done():
        _seedr_cleanup_worker_task = asyncio.create_task(_seedr_cleanup_worker())


@app.get("/health")
async def health():
    return {"status": "ok", "seedrConfigured": bool(current_seedr_token()), "torrentSearchApi": TORRENT_SEARCH_API_URL}

@app.post("/api/search/resolve-magnet")
async def resolve_search_magnet(body: dict[str, Any]):
    """Resolve a provider detail page to a magnet only when the user prepares it."""
    info_url = str(body.get("infoUrl") or body.get("info_url") or "").strip()
    if not info_url:
        raise HTTPException(400, "A provider detail URL is required.")

    parsed = urlsplit(info_url)
    allowed_hosts = {
        str(host).lower().removeprefix("www.")
        for host in (*X1337_HOSTS, *LIMETORRENTS_HOSTS)
    }
    hostname = str(parsed.hostname or "").lower().removeprefix("www.")
    if parsed.scheme != "https" or hostname not in allowed_hosts:
        raise HTTPException(400, "The provider URL is not allowed.")

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        # Follow redirects manually so every hop is checked against the
        # allowlist BEFORE it is requested (httpx would otherwise fetch an
        # unapproved redirect target and we would only notice afterwards).
        async with _InstrumentedAsyncClient(timeout=8.0, follow_redirects=False, headers=headers) as client:
            current_url = info_url
            response = None
            for _ in range(6):
                response = await client.get(current_url)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = response.headers.get("location")
                if not location:
                    break
                next_url = urljoin(current_url, location)
                next_parts = urlsplit(next_url)
                next_host = str(next_parts.hostname or "").lower().removeprefix("www.")
                if next_parts.scheme != "https" or next_host not in allowed_hosts:
                    raise HTTPException(400, "The provider redirected to an unapproved domain.")
                current_url = next_url
            else:
                raise HTTPException(502, "The torrent provider redirected too many times.")
            response.raise_for_status()
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        logger.info("Lazy magnet resolution failed for provider URL %s: %s", info_url, exc)
        raise HTTPException(502, "Could not reach the torrent provider. Please try another result.") from exc

    # Prefer a real magnet anchor when the detail page includes one.
    # Parsing hrefs handles HTML-escaped ampersands better than scanning the
    # entire page for arbitrary strings.
    page = BeautifulSoup(response.text or "", "html.parser")
    magnet = ""
    for anchor in page.select('a[href^="magnet:"]'):
        candidate = unescape(str(anchor.get("href") or "")).strip()
        if info_hash(candidate):
            magnet = candidate
            break

    if not magnet:
        match = re.search(
            r"magnet:\?xt=urn:btih:[^\"<\s]+",
            response.text,
            re.IGNORECASE,
        )
        if match:
            candidate = unescape(match.group(0))
            if info_hash(candidate):
                magnet = candidate

    if not magnet:
        # LimeTorrents also exposes a hash on its download-icon/.torrent URL.
        # Recover a standard magnet when the detail page omits a magnet anchor.
        download_anchor = (
            page.select_one("a.csprite_dl14[href]")
            or page.select_one("a[href*='/download/']")
        )
        download_href = str(download_anchor.get("href") or "").strip() if download_anchor else ""
        hash_match = re.search(
            r"(?i)(?<![0-9a-f])([0-9a-f]{40})(?![0-9a-f])",
            download_href,
        )
        if hash_match:
            digest = hash_match.group(1).lower()
            title_node = page.select_one("#content h1, h1, .tt-name")
            display_name = (
                title_node.get_text(" ", strip=True)
                if title_node is not None
                else Path(parsed.path).stem.replace("-", " ")
            )
            magnet = f"magnet:?xt=urn:btih:{digest}&dn={quote(display_name, safe='')}"
            for tracker in (
                "udp://tracker.opentrackr.org:1337/announce",
                "udp://open.stealth.si:80/announce",
            ):
                magnet += "&tr=" + quote(tracker, safe="")

    digest = info_hash(magnet)
    if not digest:
        raise HTTPException(404, "The provider did not expose a usable magnet/hash for this result.")
    return {"magnet": magnet, "infoHash": digest}

from catalogues_extra import (
    MARVEL_CATALOGUE_PATH,
    MARVEL_MOVIE_SEARCHES,
    _CACHE_SEED_FILES,
    _EXTRA_CATALOGUES,
    _EXTRA_CATALOGUE_PATHS,
    _RUNTIME_CACHE_SEED_FILES,
    _TMDB_CATALOGUE_SYNOPSIS_ENRICHMENT_STATE,
    _ensure_extra_catalogue_refresh,
    _extra_catalogue_monthly_scheduler,
    _extra_catalogue_states,
    _extra_catalogue_tasks,
    _extra_item_year,
    _initialize_catalogue_caches,
    _lookup_catalogue_synopsis,
    _normalize_synopsis_match_title,
    _read_extra_catalogue,
    _schedule_tmdb_catalogue_synopsis_enrichment,
    _start_catalogue_synopsis_enrichment,
    _start_tmdb_catalogue_synopsis_enrichment,
    _synopsis_cache_paths,
    _warm_marvel_catalogue_on_startup,
    _write_extra_catalogue,
    _write_synopsis_cache,
    router as catalogues_extra_router,
)
app.include_router(catalogues_extra_router)


app.router.add_event_handler("startup", _initialize_catalogue_caches)
app.router.add_event_handler("startup", _start_catalogue_synopsis_enrichment)

# Register only after the callback above exists; earlier startup hooks are defined
# further up the module and must not reference this function prematurely.
app.router.add_event_handler("startup", _start_tmdb_catalogue_synopsis_enrichment)


@app.get("/api/movies/catalogue-cache/synopsis-enrichment")
async def api_tmdb_catalogue_synopsis_enrichment_status():
    """Return progress for TMDB synopsis enrichment in the persistent catalogue JSON."""
    return dict(_TMDB_CATALOGUE_SYNOPSIS_ENRICHMENT_STATE)
app.router.add_event_handler("shutdown", _close_tmdb_http_client)


async def _tmdb_discovered_company_ids(franchise: str) -> list[str]:
    normalized = franchise.strip().lower()
    now = time.monotonic()
    cached = _tmdb_company_id_cache.get(normalized)
    if cached and now - cached[0] < TMDB_COMPANY_CACHE_SECONDS:
        _record_cache_event("tmdb_company_ids", "memory_hit")
        return cached[1]

    _record_cache_event("tmdb_company_ids", "miss")
    task = _tmdb_company_inflight.get(normalized)
    if task is None or task.done():
        task = asyncio.create_task(_tmdb_load_company_ids(normalized))
        _tmdb_company_inflight[normalized] = task
    try:
        return await task
    finally:
        if task.done() and _tmdb_company_inflight.get(normalized) is task:
            _tmdb_company_inflight.pop(normalized, None)


async def _tmdb_load_company_ids(franchise: str) -> list[str]:
    if franchise == "marvel":
        ids = {"420", "19551", "38679", "2301", "13252"}
        queries = ("Marvel Studios", "Marvel Entertainment", "Marvel Animation", "Marvel Productions")
    else:
        ids = {"9993"}
        queries = ("DC Entertainment", "DC Films", "DC Comics")

    async def search_company(query: str) -> list[str]:
        try:
            payload = await _tmdb_get_json("search/company", {"query": query, "page": 1})
        except HTTPException as exc:
            logger.info("TMDB company lookup failed for %s: %s", query, exc.detail)
            return []
        found: list[str] = []
        for row in payload.get("results") or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            company_id = row.get("id")
            if not name or not isinstance(company_id, (int, str)):
                continue
            lower_name = name.casefold()
            if franchise == "marvel" and "marvel" not in lower_name:
                continue
            if franchise == "dc" and not (
                "dc entertainment" in lower_name
                or "dc films" in lower_name
                or "dc comics" in lower_name
                or lower_name.startswith("dc ")
            ):
                continue
            found.append(str(company_id))
        return found

    discovered = await asyncio.gather(*(search_company(query) for query in queries))
    for values in discovered:
        ids.update(values)
    result = sorted(ids, key=lambda value: (value not in {"420", "9993"}, int(value)))[:20]
    _tmdb_company_id_cache[franchise] = (time.monotonic(), result)
    return result


def _tmdb_release_date_is_released(value: Any, today: str) -> bool:
    """Return True only when a real ISO release date is on or before today's UTC date."""
    release_text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_text):
        return False
    try:
        release_date = datetime.strptime(release_text, "%Y-%m-%d").date()
        cutoff_date = datetime.strptime(today, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return release_date <= cutoff_date


_BOLLYWOOD_COMEDY_SPECIAL_TITLES = {
    "madhurvirlicasualtea",
    "maheepsinghfir",
    "abijitgangulybaby",
}
_BOLLYWOOD_COMEDY_SPECIAL_DESCRIPTION = re.compile(
    r"\bstand[\s-]?up(?:\s+comedy)?\s+(?:special|show|performance)\b"
    r"|\b(?:\d+(?:st|nd|rd|th)?\s+)?(?:comedy|comic)\s+special\b"
    r"|\blive\s+(?:comedy|stand[\s-]?up)\s+(?:special|show|performance)\b",
    re.IGNORECASE,
)


def _is_bollywood_comedy_special(row: dict[str, Any]) -> bool:
    title = str(row.get("title") or row.get("name") or row.get("original_title") or "").strip()
    title_key = re.sub(r"[^a-z0-9]+", "", title.casefold())
    if title_key in _BOLLYWOOD_COMEDY_SPECIAL_TITLES:
        return True
    description = " ".join(
        str(row.get(field) or "")
        for field in ("overview", "tagline", "description")
    )
    return bool(_BOLLYWOOD_COMEDY_SPECIAL_DESCRIPTION.search(description))


async def _tmdb_fetch_movie_catalogue(catalogue_key: str, page: int, released_only: bool = True) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date().isoformat()
    params: dict[str, Any] = {
        "include_adult": "false",
        "include_video": "false",
        "language": "en-US",
        "page": page,
        "sort_by": "primary_release_date.desc",
    }
    if released_only:
        params["release_date.lte"] = today

    regional_modes = {
        "popular-bollywood": ("hi", "popular"),
        "trending-bollywood": ("hi", "trending"),
        "latest-bollywood": ("hi", "latest"),
        "popular-hollywood": ("en", "popular"),
        "trending-hollywood": ("en", "trending"),
        "latest-hollywood": ("en", "latest"),
    }
    if catalogue_key in {"marvel", "dc-live-action", "dc-animated"}:
        franchise = "marvel" if catalogue_key == "marvel" else "dc"
        company_ids = await _tmdb_discovered_company_ids(franchise)
        params["with_companies"] = "|".join(company_ids)
        if catalogue_key == "dc-animated":
            params["with_genres"] = "16"
        elif catalogue_key == "dc-live-action":
            params["without_genres"] = "16"
        payload = await _tmdb_get_json("discover/movie", params)
    elif catalogue_key in regional_modes:
        language_code, mode = regional_modes[catalogue_key]
        if mode == "trending":
            # TMDB's trending feed uses a different ranking signal from Popular.
            # Filter the feed by original language so the two menus stay distinct.
            payload = await _tmdb_get_json("trending/movie/week", {
                "language": "en-US",
                "page": page,
                "include_adult": "false",
            })
            # Keep Trending faithful to TMDB's weekly trending ranking. The
            # endpoint is global, so a language filter can produce short pages;
            # do not pad them with popularity-ranked Discover results. The
            # regional page builder scans subsequent trending pages as needed.
            payload = {
                **payload,
                "results": [
                    row for row in (payload.get("results") or [])
                    if isinstance(row, dict)
                    and str(row.get("original_language") or "").lower() == language_code
                ],
            }
        else:
            params["with_original_language"] = language_code
            params["sort_by"] = (
                "popularity.desc" if mode == "popular"
                else "release_date.desc" if mode == "latest"
                else "primary_release_date.desc"
            )
            if mode == "latest":
                # Use release_date rather than primary_release_date: many English-
                # language TMDB records have no primary_release_date, so that filter
                # can return future/undated records which the released-only guard
                # then rejects, leaving the entire Latest Hollywood page empty.
                recent_cutoff = datetime.fromtimestamp(time.time() - 5 * 365 * 86400, timezone.utc).date()
                params["release_date.gte"] = recent_cutoff.isoformat()
            payload = await _tmdb_get_json("discover/movie", params)
            if mode == "latest" and not (payload.get("results") or []):
                # TMDB's primary_release_date filter can return an empty page
                # for English-language films with regional-only release dates.
                # Retry using the broader release_date fields while retaining
                # the language and five-year window.
                fallback_params = dict(params)
                fallback_params.pop("primary_release_date.gte", None)
                fallback_params["release_date.gte"] = recent_cutoff.isoformat()
                fallback_params["sort_by"] = "release_date.desc"
                fallback = await _tmdb_get_json("discover/movie", fallback_params)
                if fallback.get("results"):
                    payload = fallback
                else:
                    # Last fallback: popularity ranking inside the same date
                    # window. This avoids a permanently empty catalogue when
                    # the release-date sort/filter combination is sparse.
                    fallback_params["sort_by"] = "popularity.desc"
                    fallback = await _tmdb_get_json("discover/movie", fallback_params)
                    if fallback.get("results"):
                        payload = fallback
    else:
        raise HTTPException(status_code=404, detail="Unknown movie catalogue.")

    raw_results = payload.get("results") or []

    # TMDB's company-based Marvel Discover feed can omit this special even
    # though it is an officially released Marvel title. Resolve it by exact
    # title/year and merge it into page 1 so it is visible in the main catalogue.
    if catalogue_key == "marvel" and page == 1:
        def punisher_special_key(value: Any) -> str:
            key = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
            presentation_prefix = "a marvel television special presentation "
            if key.startswith(presentation_prefix):
                key = key[len(presentation_prefix):]
            return key

        expected_punisher_key = "the punisher one last kill"
        already_in_page = any(
            isinstance(item, dict)
            and punisher_special_key(item.get("title") or item.get("original_title")) == expected_punisher_key
            for item in raw_results
        )
        if not already_in_page:
            try:
                special_search = await _tmdb_get_json("search/movie", {
                    "query": "The Punisher: One Last Kill",
                    "year": 2026,
                    "include_adult": "false",
                    "language": "en-US",
                    "page": 1,
                })
            except HTTPException as exc:
                logger.info("Could not resolve The Punisher: One Last Kill for Marvel catalogue: %s", exc.detail)
            else:
                special_item = next((
                    item for item in (special_search.get("results") or [])
                    if isinstance(item, dict)
                    and punisher_special_key(item.get("title") or item.get("original_title")) == expected_punisher_key
                    and re.match(r"^2026", str(item.get("release_date") or ""))
                    and (not released_only or _tmdb_release_date_is_released(item.get("release_date"), today))
                ), None)
                if special_item:
                    raw_results = list(raw_results)
                    raw_results.append(special_item)
                    payload = dict(payload)
                    payload["results"] = raw_results
                    payload["total_results"] = int(payload.get("total_results") or (len(raw_results) - 1)) + 1
                    payload["total_pages"] = max(
                        int(payload.get("total_pages") or 1),
                        (int(payload["total_results"]) + 19) // 20,
                    )
                    # Keep the injected title in the same newest-first order as
                    # the Discover response, including the fast first-paint path.
                    raw_results.sort(key=lambda item: (
                        str(item.get("release_date") or ""),
                        float(item.get("popularity") or 0),
                    ), reverse=True)

    results: list[dict[str, Any]] = []
    regional = regional_modes.get(catalogue_key)
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        if regional and str(item.get("original_language") or "").lower() != regional[0]:
            continue
        title = str(item.get("title") or item.get("original_title") or "").strip()
        if not title:
            continue
        if catalogue_key == "latest-bollywood" and _is_bollywood_comedy_special(item):
            continue
        release_date = str(item.get("release_date") or "").strip()
        if released_only and not _tmdb_release_date_is_released(release_date, today):
            continue
        year_match = re.match(r"^(\d{4})", release_date)
        poster_path = str(item.get("poster_path") or "").strip()
        backdrop_path = str(item.get("backdrop_path") or "").strip()
        results.append({
            "id": item.get("id"),
            "title": title,
            "year": int(year_match.group(1)) if year_match else None,
            "releaseDate": release_date,
            "overview": str(item.get("overview") or "").strip(),
            "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "",
            "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "",
            "rating": float(item.get("vote_average") or 0),
            "genres": [int(genre) for genre in (item.get("genre_ids") or []) if str(genre).isdigit()],
            "source": "TMDB",
        })

    total_pages = max(1, min(500, int(payload.get("total_pages") or 1)))
    current_page = max(1, min(500, int(payload.get("page") or page)))
    return {
        "catalogue": catalogue_key,
        "releasedOnly": released_only,
        "provider": "TMDB",
        "page": current_page,
        "totalPages": total_pages,
        "totalResults": int(payload.get("total_results") or len(results)),
        "results": results,
        "attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
    }

MARVEL_WEB_SERIES: tuple[tuple[str, int], ...] = (
    ("WandaVision", 2021), ("The Falcon and the Winter Soldier", 2021), ("Loki", 2021),
    ("What If...?", 2021), ("Hawkeye", 2021), ("Moon Knight", 2022), ("Ms. Marvel", 2022),
    ("She-Hulk: Attorney at Law", 2022), ("Secret Invasion", 2023), ("Echo", 2024),
    ("Agatha All Along", 2024), ("Daredevil: Born Again", 2025), ("Ironheart", 2025),
    ("Eyes of Wakanda", 2025), ("Wonder Man", 2026), ("VisionQuest", 2026),
    ("Marvel Zombies", 2025), ("Your Friendly Neighborhood Spider-Man", 2025), ("X-Men '97", 2024),
    ("I Am Groot", 2022), ("Marvel Studios: Legends", 2021),
    ("Marvel's Avengers", 2018), ("Marvel Rising", 2018),
    ("Legion", 2017), ("The Gifted", 2017), ("Agents of S.H.I.E.L.D.", 2013),
    ("Agent Carter", 2015), ("Inhumans", 2017), ("Runaways", 2017), ("Cloak & Dagger", 2018),
    ("Daredevil", 2015), ("Jessica Jones", 2015), ("Luke Cage", 2016), ("Iron Fist", 2017),
    ("The Defenders", 2017), ("The Punisher", 2017), ("Helstrom", 2020), ("Blade: The Series", 2006),
    ("Mutant X", 2001), ("Avengers Assemble", 2013), ("Guardians of the Galaxy", 2015),
    ("Ultimate Spider-Man", 2012), ("Hulk and the Agents of S.M.A.S.H.", 2013),
    ("The Spectacular Spider-Man", 2008), ("Wolverine and the X-Men", 2009),
    ("X-Men: The Animated Series", 1992), ("Spider-Man: The Animated Series", 1994),
    ("Fantastic Four", 1994), ("Iron Man", 1994), ("The Incredible Hulk", 1996),
    ("Silver Surfer", 1998), ("Spider-Man Unlimited", 1999),
    ("The Avengers: Earth's Mightiest Heroes", 2010), ("Wolverine", 2011),
)
DC_WEB_SERIES: tuple[tuple[str, int], ...] = (
    ("Adventures of Superman", 1952), ("Batman", 1966), ("Shazam!", 1974), ("Wonder Woman", 1975),
    ("Superboy", 1988), ("Swamp Thing", 1990), ("The Flash", 1990), ("Lois & Clark: The New Adventures of Superman", 1993),
    ("Smallville", 2001), ("Birds of Prey", 2002), ("Human Target", 2010), ("Arrow", 2012),
    ("The Flash", 2014), ("Constantine", 2014), ("Gotham", 2014), ("Supergirl", 2015), ("iZombie", 2015),
    ("Legends of Tomorrow", 2016), ("Lucifer", 2016), ("Preacher", 2016), ("Powerless", 2017),
    ("Krypton", 2018), ("Titans", 2018), ("Black Lightning", 2018), ("Doom Patrol", 2019), ("Pennyworth", 2019),
    ("Swamp Thing", 2019), ("Watchmen", 2019), ("Batwoman", 2019), ("Stargirl", 2020),
    ("Superman & Lois", 2021), ("Sweet Tooth", 2021), ("Y: The Last Man", 2021), ("Naomi", 2022),
    ("The Sandman", 2022), ("Peacemaker", 2022), ("Gotham Knights", 2023), ("Dead Boy Detectives", 2024), ("The Penguin", 2024), ("Lanterns", 2026),
)

_MARVEL_TV_CATALOGUE_CACHE: dict[str, Any] = {"expiresAt": 0.0, "payload": None}
_DC_TV_CATALOGUE_CACHE: dict[str, Any] = {"expiresAt": 0.0, "payload": None}
def _load_persistent_tv_catalogue(cache: dict[str, Any], path: Path) -> dict[str, Any] | None:
    """Load a completed TV catalogue from persistent storage; it has no time-based expiry."""
    store = "tv_catalogue:" + path.stem
    if cache.get("payload"):
        _record_cache_event(store, "memory_hit")
        return cache["payload"]
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if (
            isinstance(payload, dict)
            and isinstance(payload.get("results"), list)
            and payload["results"]
            # Provider enrichment was added after the original permanent cache.
            # Rebuild older cache files once so cards gain streaming-service data.
            and all(isinstance(item, dict) and isinstance(item.get("streamingProviders"), list) for item in payload["results"])
        ):
            cache.update({"expiresAt": float("inf"), "payload": payload})
            _record_cache_event(store, "persistent_hit")
            _record_cache_event(store, "persistent_rows_served", len(payload["results"]))
            logger.info("Loaded persistent TV catalogue cache %s (%d titles)", path.name, len(payload["results"]))
            return payload
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Persistent TV catalogue cache unavailable at %s: %s", path, exc)
    _record_cache_event(store, "miss")
    return None


def _save_persistent_tv_catalogue(path: Path, payload: dict[str, Any]) -> None:
    """Atomically persist TV metadata so container restarts never trigger a full TMDB scan."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        logger.info("Saved persistent TV catalogue cache %s (%d titles)", path.name, len(payload.get("results") or []))
    except OSError as exc:
        logger.warning("Could not persist TV catalogue cache %s: %s", path, exc)


async def _tv_streaming_providers(tmdb_id: int) -> list[dict[str, Any]]:
    """Resolve India streaming/rent/buy providers for one TMDB TV series."""
    if CACHE_ONLY_MODE:
        _record_cache_event("tv_streaming_availability", "cache_only_miss_blocked")
        return []
    _record_cache_event("tv_streaming_availability", "live_provider_lookup")
    try:
        payload = await _tmdb_get_json(f"tv/{tmdb_id}/watch/providers", {})
    except Exception as exc:
        logger.info("TMDB TV provider lookup failed for %s: %s", tmdb_id, exc)
        return []
    region = (payload.get("results") or {}).get("IN") or {}
    providers: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str]] = set()
    for category, kind in (
        ("flatrate", "subscription"),
        ("free", "free"),
        ("ads", "ads"),
        ("rent", "rent"),
        ("buy", "buy"),
    ):
        for item in region.get(category) or []:
            name = str(item.get("provider_name") or "").strip()
            if not name:
                continue
            try:
                provider_id = int(item.get("provider_id")) if item.get("provider_id") is not None else None
            except (TypeError, ValueError):
                provider_id = None
            identity = (provider_id, name.casefold())
            if identity in seen:
                continue
            seen.add(identity)
            logo_path = str(item.get("logo_path") or "").strip()
            providers.append({
                "providerId": provider_id,
                "name": name,
                "type": kind,
                "region": "IN",
                "logoUrl": "https://image.tmdb.org/t/p/w92" + logo_path if logo_path else "",
                "webUrl": str(region.get("link") or ""),
            })
    return providers


@app.get("/api/tv/catalogue/marvel")
async def api_tmdb_marvel_tv_catalogue(page: int = Query(1, ge=1, le=500)):
    """Return cards for the curated Marvel TV/web-series list, enriched from TMDB."""
    cached_payload = _load_persistent_tv_catalogue(_MARVEL_TV_CATALOGUE_CACHE, MARVEL_TV_CATALOGUE_CACHE_FILE)
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS) and not cached_payload:
        raise HTTPException(status_code=503, detail="TMDB credentials are not configured.")

    semaphore = asyncio.Semaphore(3)

    async def resolve_series(title: str, year: int) -> dict[str, Any]:
        fallback = {
            "id": f"marvel-tv:{re.sub(r'[^a-z0-9]+', '-', title.casefold()).strip('-')}:{year}",
            "title": title,
            "year": year,
            "releaseDate": str(year),
            "overview": "",
            "posterUrl": "",
            "backdropUrl": "",
            "rating": 0.0,
            "tmdbUrl": "",
            "streamingProviders": [],
            "providerLink": "",
            "source": "Curated Marvel series list",
        }
        async with semaphore:
            try:
                payload = await _tmdb_get_json("search/tv", {
                    "query": title,
                    "first_air_date_year": year,
                    "include_adult": "false",
                    "language": "en-US",
                    "page": 1,
                })
            except HTTPException as exc:
                logger.info("TMDB Marvel TV lookup failed for %s (%s): %s", title, year, exc.detail)
                return fallback
            target = _normalize_title(title)
            candidates = [row for row in (payload.get("results") or []) if isinstance(row, dict) and row.get("id")]
            candidates.sort(key=lambda row: (
                _normalize_title(str(row.get("name") or "")) == target,
                str(row.get("first_air_date") or "").startswith(str(year)),
                float(row.get("popularity") or 0),
            ), reverse=True)
            if not candidates:
                return fallback
            item = candidates[0]
            air_date = str(item.get("first_air_date") or "").strip()
            year_match = re.match(r"^(\d{4})", air_date)
            poster_path = str(item.get("poster_path") or "").strip()
            backdrop_path = str(item.get("backdrop_path") or "").strip()
            tmdb_id = int(item["id"])
            return {
                "id": tmdb_id,
                "title": title,
                "year": int(year_match.group(1)) if year_match else year,
                "releaseDate": air_date,
                "overview": str(item.get("overview") or "").strip(),
                "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "",
                "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "",
                "rating": float(item.get("vote_average") or 0),
                "tmdbUrl": f"https://www.themoviedb.org/tv/{tmdb_id}",
                "streamingProviders": await _tv_streaming_providers(tmdb_id),
                "providerLink": "",
                "source": "TMDB",
            }

    if cached_payload:
        # Extend existing persistent catalogues additively. Never discard existing
        # entries: official Marvel titles missing from an older cache are appended.
        results = list(cached_payload.get("results") or [])
        known_titles = {_normalize_title(str(row.get("title") or "")) for row in results if isinstance(row, dict)}
        missing = [
            (title, year) for title, year in MARVEL_WEB_SERIES
            if _normalize_title(title) not in known_titles
        ]
        if missing and (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
            additions = await asyncio.gather(*(resolve_series(title, year) for title, year in missing))
            results.extend(additions)
            cached_payload = {**cached_payload, "results": results, "totalResults": len(results),
                              "provider": "TMDB + curated Marvel series list"}
            _save_persistent_tv_catalogue(MARVEL_TV_CATALOGUE_CACHE_FILE, cached_payload)
        _MARVEL_TV_CATALOGUE_CACHE.update({"expiresAt": float("inf"), "payload": cached_payload})
        return cached_payload

    results = await asyncio.gather(*(resolve_series(title, year) for title, year in MARVEL_WEB_SERIES))
    result = {
        "catalogue": "marvel-web-series",
        "page": 1,
        "totalPages": 1,
        "totalResults": len(results),
        "provider": "TMDB + curated Marvel series list",
        "results": results,
    }
    _MARVEL_TV_CATALOGUE_CACHE.update({"expiresAt": float("inf"), "payload": result})
    _save_persistent_tv_catalogue(MARVEL_TV_CATALOGUE_CACHE_FILE, result)
    return result


@app.get("/api/tv/catalogue/dc-live-action")
async def api_tmdb_dc_live_action_tv_catalogue(page: int = Query(1, ge=1, le=500)):
    """Return curated live-action DC TV series cards enriched from TMDB."""
    cached_payload = _load_persistent_tv_catalogue(_DC_TV_CATALOGUE_CACHE, DC_TV_CATALOGUE_CACHE_FILE)
    if cached_payload:
        return cached_payload
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        raise HTTPException(status_code=503, detail="TMDB credentials are not configured.")
    semaphore = asyncio.Semaphore(3)
    async def resolve_series(title: str, year: int) -> dict[str, Any]:
        fallback = {"id": f"dc-tv:{re.sub(r'[^a-z0-9]+', '-', title.casefold()).strip('-')}:{year}", "title": title, "year": year, "releaseDate": str(year), "overview": "", "posterUrl": "", "backdropUrl": "", "rating": 0.0, "tmdbUrl": "", "streamingProviders": [], "providerLink": "", "source": "Curated DC live-action series list"}
        async with semaphore:
            try:
                payload = await _tmdb_get_json("search/tv", {"query": title, "first_air_date_year": year, "include_adult": "false", "language": "en-US", "page": 1})
            except HTTPException as exc:
                logger.info("TMDB DC TV lookup failed for %s (%s): %s", title, year, exc.detail)
                return fallback
            target = _normalize_title(title)
            candidates = [row for row in (payload.get("results") or []) if isinstance(row, dict) and row.get("id")]
            candidates.sort(key=lambda row: (_normalize_title(str(row.get("name") or "")) == target, str(row.get("first_air_date") or "").startswith(str(year)), float(row.get("popularity") or 0)), reverse=True)
            if not candidates: return fallback
            item = candidates[0]
            air_date = str(item.get("first_air_date") or "").strip()
            year_match = re.match(r"^(\d{4})", air_date)
            poster_path = str(item.get("poster_path") or "").strip()
            backdrop_path = str(item.get("backdrop_path") or "").strip()
            tmdb_id = int(item["id"])
            return {"id": tmdb_id, "title": title, "year": int(year_match.group(1)) if year_match else year, "releaseDate": air_date, "overview": str(item.get("overview") or "").strip(), "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "", "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "", "rating": float(item.get("vote_average") or 0), "tmdbUrl": f"https://www.themoviedb.org/tv/{tmdb_id}", "streamingProviders": await _tv_streaming_providers(tmdb_id), "providerLink": "", "source": "TMDB"}
    results = await asyncio.gather(*(resolve_series(title, year) for title, year in DC_WEB_SERIES))
    result = {"catalogue": "dc-live-action-web-series", "page": 1, "totalPages": 1, "totalResults": len(results), "provider": "TMDB + curated DC live-action series list", "results": results}
    _DC_TV_CATALOGUE_CACHE.update({"expiresAt": float("inf"), "payload": result})
    _save_persistent_tv_catalogue(DC_TV_CATALOGUE_CACHE_FILE, result)
    return result




# Curated Classics TV and anime catalogues. These use NexStream/TMDB cards,
# not torrent searches.
_CLASSICS_TV_CATALOGUES: dict[str, list[tuple[str, int]]] = {
    "classics-web-series": [
        ("Breaking Bad", 2008), ("Better Call Saul", 2015), ("Arrow", 2012),
        ("The Flash", 2014), ("Marvel's Daredevil", 2015),
        ("The Queen's Gambit", 2020), ("Sherlock", 2010),
        ("How I Met Your Mother", 2005), ("The Last of Us", 2023),
        ("Peaky Blinders", 2013), ("The Big Bang Theory", 2007),
        ("Chernobyl", 2019), ("Dark", 2017), ("Succession", 2018),
        ("The Wire", 2002), ("The Office", 2005), ("Wednesday", 2022),
        ("Squid Game", 2021), ("Stranger Things", 2016),
        ("Game of Thrones", 2011), ("Severance", 2022),
        ("True Detective", 2014), ("Billions", 2016),
        ("The Studio", 2025), ("Secret Level", 2024),
        ("Love, Death & Robots", 2019), ("Two and a Half Men", 2003),
        ("Person of Interest", 2011),
    ],
    "classics-anime": [
        ("Death Note", 2006), ("Attack on Titan", 2013), ("Code Geass", 2006),
        ("Monster", 2004), ("Dragon Ball", 1986), ("Dragon Ball Z", 1989),
        ("Dragon Ball GT", 1996), ("Dragon Ball Z Kai", 2009), ("Super Dragon Ball Heroes", 2018), ("Dragon Ball Super", 2015),
        ("Dragon Ball Daima", 2024), ("Naruto", 2002),
        ("Naruto: Shippuden", 2007), ("Bleach", 2004), ("One Piece", 1999),
        ("One-Punch Man", 2015), ("Terror in Resonance", 2014),
        ("My Hero Academia", 2016), ("Fullmetal Alchemist: Brotherhood", 2009),
        ("Demon Slayer: Kimetsu no Yaiba", 2019), ("Vinland Saga", 2019),
        ("Cowboy Bebop", 1998), ("Jujutsu Kaisen", 2020), ("Hunter x Hunter", 2011),
        ("Hajime no Ippo", 2000), ("Chainsaw Man", 2022), ("Berserk", 1997),
        ("Parasyte: The Maxim", 2014), ("Avatar: The Last Airbender", 2005),
    ],
}
_CLASSICS_TV_CATALOGUE_CACHE: dict[str, dict[str, Any]] = {}
_CLASSICS_TV_CACHE_FILES = {
    "classics-web-series": "classics_web_series_tv_catalogue.json",
    "classics-anime": "classics_anime_tv_catalogue.json",
}


def _load_bundled_classics_tv_cache(catalogue_key: str) -> dict[str, Any] | None:
    filename = _CLASSICS_TV_CACHE_FILES.get(catalogue_key)
    if not filename:
        return None
    candidates = (
        _CACHE_SEED_DIR / filename,
        Path(os.getenv("APP_DATA_DIR", "/app/data")) / filename,
    )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("catalogue") == catalogue_key and isinstance(payload.get("results"), list):
                return payload
        except (OSError, ValueError, AttributeError):
            continue
    return None


async def _get_classics_tv_catalogue(catalogue_key: str) -> dict[str, Any]:
    titles = _CLASSICS_TV_CATALOGUES.get(catalogue_key)
    if titles is None:
        raise HTTPException(status_code=404, detail="Unknown Classics TV catalogue.")
    cached = _CLASSICS_TV_CATALOGUE_CACHE.get(catalogue_key)
    if cached is not None:
        _record_cache_event("classics_tv:" + catalogue_key, "memory_hit")
        return cached
    bundled = _load_bundled_classics_tv_cache(catalogue_key)
    if bundled is not None:
        _record_cache_event("classics_tv:" + catalogue_key, "bundled_hit")
        _CLASSICS_TV_CATALOGUE_CACHE[catalogue_key] = bundled
        return bundled
    _record_cache_event("classics_tv:" + catalogue_key, "miss")
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        raise HTTPException(status_code=503, detail="TMDB credentials are not configured.")
    semaphore = asyncio.Semaphore(3)

    async def resolve_series(title: str, year: int) -> dict[str, Any]:
        fallback = {
            "id": f"classics-tv:{re.sub(r'[^a-z0-9]+', '-', title.casefold()).strip('-')}:{year}",
            "title": title, "year": year, "releaseDate": str(year), "overview": "",
            "posterUrl": "", "backdropUrl": "", "rating": 0.0, "tmdbUrl": "",
            "streamingProviders": [], "providerLink": "", "source": "Curated Classics list",
        }
        async with semaphore:
            try:
                is_anime_film = title == "Akira"
                payload = await _tmdb_get_json("search/movie" if is_anime_film else "search/tv", {
                    "query": title,
                    ("year" if is_anime_film else "first_air_date_year"): year,
                    "include_adult": "false", "language": "en-US", "page": 1,
                })
            except HTTPException as exc:
                logger.info("TMDB Classics TV lookup failed for %s (%s): %s", title, year, exc.detail)
                return fallback
            target = _normalize_title(title)
            candidates = [row for row in (payload.get("results") or []) if isinstance(row, dict) and row.get("id")]
            candidates.sort(key=lambda row: (
                _normalize_title(str(row.get("name") or "")) == target,
                str(row.get("first_air_date") or "").startswith(str(year)),
                float(row.get("popularity") or 0),
            ), reverse=True)
            if not candidates:
                return fallback
            item = candidates[0]
            air_date = str(item.get("first_air_date") or "").strip()
            year_match = re.match(r"^(\d{4})", air_date)
            poster_path = str(item.get("poster_path") or "").strip()
            backdrop_path = str(item.get("backdrop_path") or "").strip()
            tmdb_id = int(item["id"])
            return {
                "id": tmdb_id, "title": title,
                "year": int(year_match.group(1)) if year_match else year,
                "releaseDate": air_date, "overview": str(item.get("overview") or "").strip(),
                "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "",
                "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "",
                "rating": float(item.get("vote_average") or 0),
                "tmdbUrl": f"https://www.themoviedb.org/{'movie' if is_anime_film else 'tv'}/{tmdb_id}",
                "streamingProviders": [] if is_anime_film else await _tv_streaming_providers(tmdb_id),
                "providerLink": "", "source": "TMDB",
            }

    results = await asyncio.gather(*(resolve_series(title, year) for title, year in titles))
    results.sort(key=lambda row: (str(row.get("releaseDate") or row.get("year") or ""), str(row.get("title") or "")), reverse=True)
    result = {
        "catalogue": catalogue_key, "page": 1, "totalPages": 1,
        "totalResults": len(results), "provider": "TMDB + curated Classics list", "results": results,
    }
    _CLASSICS_TV_CATALOGUE_CACHE[catalogue_key] = result

    # Persist the resolved catalogue so the manual GitHub snapshot workflow can
    # copy it from APP_DATA_DIR and seed ephemeral deployments with a warm cache.
    filename = _CLASSICS_TV_CACHE_FILES[catalogue_key]
    cache_path = Path(os.getenv("APP_DATA_DIR", "/app/data")) / filename
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
        temporary_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary_path.replace(cache_path)
        logger.info("Persisted Classics TV catalogue cache %s (%s titles)", filename, len(results))
    except OSError as exc:
        logger.warning("Could not persist Classics TV catalogue cache %s: %s", filename, exc)

    return result


@app.get("/api/tv/catalogue/classics-web-series")
async def api_tmdb_classics_web_series_catalogue():
    return await _get_classics_tv_catalogue("classics-web-series")


@app.get("/api/tv/catalogue/classics-anime")
async def api_tmdb_classics_anime_catalogue():
    return await _get_classics_tv_catalogue("classics-anime")


def _read_regional_tv_prebuilt_page(catalogue_key: str, page: int) -> dict[str, Any] | None:
    """Read one page from the persistent TV catalogue built by scripts/build_regional_movie_cache.py."""
    try:
        if not REGIONAL_TV_PREBUILT_CACHE_FILE.exists():
            return None
        payload = json.loads(REGIONAL_TV_PREBUILT_CACHE_FILE.read_text(encoding="utf-8"))
        # The cache builder writes "version", not "schemaVersion". Accept both
        # formats so valid snapshots created by the VPS builder are actually used.
        cache_version = int(payload.get("schemaVersion") or payload.get("version") or 0)
        if cache_version < 3:
            return None
        catalogue = (payload.get("catalogues") or {}).get(catalogue_key) or {}
        # The builder marks snapshots with status/seriesCount; the API's own
        # writer uses verifiedWebSeries. Accept either valid persisted format.
        pages = catalogue.get("pages") or []
        is_verified = bool(catalogue.get("verifiedWebSeries")) or (
            catalogue.get("status") in {"ready", "partial"} and bool(pages)
        )
        if not is_verified:
            return None
        for entry in pages:
            if int(entry.get("page") or 0) == page:
                rows = [row for row in (entry.get("results") or []) if isinstance(row, dict)]
                if catalogue_key.startswith("indian-"):
                    excluded_titles = {"gangaa", "dearishq", "mastram"}
                    rows = [
                        row for row in rows
                        if re.sub(r"[^a-z0-9]+", "", str(row.get("title") or row.get("name") or "").casefold()) not in excluded_titles
                    ]
                return {
                    "catalogue": catalogue_key,
                    "page": page,
                    "totalPages": max(1, len(pages)),
                    "totalResults": int(catalogue.get("totalResults") or catalogue.get("seriesCount") or 0),
                    "provider": "Persistent TMDB + verified India OTT availability",
                    "results": rows,
                    "prebuilt": True,
                }
    except Exception as exc:
        logger.warning("Could not read regional TV prebuilt cache for %s page %s: %s", catalogue_key, page, exc)
    return None


def _save_regional_tv_prebuilt_pages(catalogue_key: str, rows: list[dict[str, Any]]) -> None:
    """Store three 18-item pages in the persistent VPS TV catalogue."""
    try:
        REGIONAL_TV_PREBUILT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schemaVersion": 3, "catalogues": {}}
        if REGIONAL_TV_PREBUILT_CACHE_FILE.exists():
            try:
                existing = json.loads(REGIONAL_TV_PREBUILT_CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    payload = existing
            except Exception:
                logger.warning("Regional TV cache unreadable; rebuilding its document")
        payload["schemaVersion"] = 3
        catalogues = payload.setdefault("catalogues", {})
        if not isinstance(catalogues, dict):
            catalogues = {}
            payload["catalogues"] = catalogues
        # Persist every discovered page, not only the first three. Page 4+
        # requires more discovery/enrichment on its first request; saving all
        # verified rows prevents repeating that expensive work on every visit.
        page_count = max(3, (len(rows) + 17) // 18)
        pages = [{"page": n + 1, "results": rows[n * 18:(n + 1) * 18]} for n in range(page_count)]
        catalogues[catalogue_key] = {
            "verifiedWebSeries": True,
            "totalResults": len(rows),
            "seriesCount": len(rows),
            "pages": pages,
        }
        temporary = REGIONAL_TV_PREBUILT_CACHE_FILE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temporary.replace(REGIONAL_TV_PREBUILT_CACHE_FILE)
    except Exception as exc:
        logger.warning("Could not save regional TV catalogue %s: %s", catalogue_key, exc)


_REGIONAL_TV_PAGE_CACHE: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_REGIONAL_TV_PAGE_CACHE_TTL = 6 * 60 * 60
_REGIONAL_TV_DISCOVERY_CACHE = _REGIONAL_TV_PAGE_CACHE
_INDIAN_LINEAR_TV_NETWORKS = {
    "starplus", "colors", "zee tv", "zeetv", "sony entertainment television",
    "sony sab", "sab tv", "dd national", "andtv", "&tv", "star bharat",
    "sony pal", "dangal tv", "sun tv", "star utsav",
}


@app.get("/api/tv/catalogue/{catalogue_key}")
async def api_tmdb_regional_tv_catalogue(catalogue_key: str, page: int = Query(1, ge=1, le=500)):
    """Return Hindi Indian OTT web-series, excluding non-Hindi and non-scripted TV formats."""
    configs = {
        "indian-popular": ("IN", "hi", "popularity.desc"),
        "indian-trending": ("IN", "hi", "popularity.desc"),
        "indian-latest": ("IN", "hi", "first_air_date.desc"),
        "hollywood-popular": ("US", "en", "popularity.desc"),
        "hollywood-trending": ("US", "en", "popularity.desc"),
        "hollywood-latest": ("US", "en", "first_air_date.desc"),
    }
    if catalogue_key not in configs:
        raise HTTPException(status_code=404, detail="Unknown TV catalogue.")
    # Indian Popular and Trending exclude scripted series whose TMDB network
    # metadata identifies Zee TV, Star Plus, Colors, or Sony TV as a broadcaster.
    exclude_indian_broadcast_networks = catalogue_key in {"indian-popular", "indian-trending"}
    excluded_network_names = {
        "zee tv", "zeetv", "star plus", "starplus", "colors", "colorstv",
        "sony tv", "sony entertainment television", "sony entertainment tv",
        "set india", "sony sab",
    }
    # TMDB's genre 10766 is Soap. TMDB genre tagging is not complete for every
    # Indian serial, so retain a small, exact-title safety list for known soaps.
    # Keep names normalized and exact-match only to avoid excluding unrelated titles.
    known_indian_soap_titles = {
        "agniphera", "bhabiji ghar par hain", "devon ke dev mahadev",
        "jiji maa", "radha krishn", "sirf tum", "pushpa impossible",
        "yeh rishta kya kehlata hai", "kundali bhagya", "kumkum bhagya",
        "anupamaa", "ghum hai kisikey pyaar mein", "imli", "udne ki aasha",
        "taarak mehta ka ooltah chashmah", "sasural simar ka", "saath nibhaana saathiya",
        "diya aur baati hum", "yeh hai mohabbatein", "kasautii zindagii kay",
        "naagin", "ishqbaaaz", "shakti astitva ke ehsaas ki", "choti sarrdaarni",
        "molkki", "pinjara khubsurti ka", "mere angne mein", "swaragini",
        "balika vadhu", "uttaran", "pavitra rishta", "kumkum",
    }

    def _normalized_tv_title(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()

    def has_soap_genre(genres: Any) -> bool:
        return isinstance(genres, list) and any(
            isinstance(genre, dict) and str(genre.get("id") or "").strip() == "10766"
            for genre in genres
        )

    def is_known_indian_soap(*titles: Any) -> bool:
        return any(_normalized_tv_title(title) in known_indian_soap_titles for title in titles if title)

    def has_excluded_broadcast_network(networks: Any) -> bool:
        if not isinstance(networks, list):
            return False
        for network in networks:
            if not isinstance(network, dict):
                continue
            name = re.sub(r"[^a-z0-9]+", " ", str(network.get("name") or "").casefold()).strip()
            compact = name.replace(" ", "")
            if name in excluded_network_names or compact in {n.replace(" ", "") for n in excluded_network_names}:
                return True
        return False

    async def filter_cached_networks(result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            return result
        if not exclude_indian_broadcast_networks:
            rows = result.get("results")
            if isinstance(rows, list):
                filtered_by_year = []
                for row in rows:
                    try:
                        air_date = str(row.get("releaseDate") or row.get("first_air_date") or "").strip()
                        if air_date and datetime.strptime(air_date[:10], "%Y-%m-%d").date() >= datetime(2015, 1, 1).date():
                            filtered_by_year.append(row)
                    except (TypeError, ValueError):
                        continue
                updated = dict(result)
                updated["results"] = filtered_by_year[:18]
                updated["totalResults"] = len(filtered_by_year)
                updated["pageSize"] = 18
                return updated
            return result
        rows = result.get("results")
        if not isinstance(rows, list):
            return result
        filtered = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                tmdb_id = int(row.get("id") or 0)
                if not tmdb_id:
                    continue
                # Always resolve canonical metadata for cached entries. Old cache
                # rows predate the soap filter and cannot be trusted on their own.
                details = await _tmdb_get_json(f"tv/{tmdb_id}", {})
                networks = details.get("networks") if isinstance(details.get("networks"), list) else []
                genres = details.get("genres") if isinstance(details.get("genres"), list) else []
                titles = (details.get("name"), details.get("original_name"), row.get("title"), row.get("name"))
                series_type = str(details.get("type") or row.get("seriesType") or "").casefold()
                if series_type not in {"scripted", "miniseries"}:
                    continue
                air_date = str(details.get("first_air_date") or row.get("releaseDate") or row.get("first_air_date") or "").strip()
                try:
                    if not air_date or datetime.strptime(air_date[:10], "%Y-%m-%d").date() < datetime(2015, 1, 1).date():
                        continue
                except ValueError:
                    continue
                if has_soap_genre(genres) or is_known_indian_soap(*titles):
                    continue
                # Fail closed when network metadata is missing: this catalogue
                # must not leak linear-TV entries merely because metadata is absent.
                if not networks or has_excluded_broadcast_network(networks):
                    continue
                row = dict(row)
                row["networks"] = networks
                row["genres"] = genres
                row["seriesType"] = series_type
            except Exception as exc:
                logger.info("Skipping cached TV item %s because its metadata could not be verified: %s", row.get("id"), type(exc).__name__)
                continue
            filtered.append(row)
        result = dict(result)
        result["results"] = filtered
        result["totalResults"] = len(filtered)
        return result

    # Use only pages explicitly marked as verified by this endpoint.
    prebuilt = _read_regional_tv_prebuilt_page(catalogue_key, page)
    if prebuilt is not None:
        _record_cache_event("regional_tv_catalogue", "prebuilt_hit")
        return prebuilt
    _record_cache_event("regional_tv_catalogue", "prebuilt_miss")

    country, language, sort_by = configs[catalogue_key]
    cache_key = (catalogue_key, page)
    cached = _REGIONAL_TV_DISCOVERY_CACHE.get(cache_key)
    cache_ttl = 900 if catalogue_key.endswith("-trending") else 21600
    if cached and time.monotonic() - cached[0] < cache_ttl and not exclude_indian_broadcast_networks:
        _record_cache_event("regional_tv_catalogue", "memory_hit")
        return await filter_cached_networks(cached[1])
    _record_cache_event("regional_tv_catalogue", "discovery_miss")
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        raise HTTPException(status_code=503, detail="TMDB credentials are not configured.")

    today = datetime.now(timezone.utc).date().isoformat()
    try:
        # Build UI pages from the filtered result set, not raw TMDB pages.
        # Continue fetching source pages until this page has 18 eligible series
        # (or TMDB runs out), so strict Indian web-series filters don't leave gaps.
        source_page = 1
        source_total_pages = 1
        eligible_rows: list[dict[str, Any]] = []
        seen_ids: set[int] = set()
        # Build enough verified rows to fill the requested page, then persist
        # every verified row so later visits to deeper pages can use disk cache.
        required_count = max(54, page * 18)

        while source_page <= source_total_pages and len(eligible_rows) < required_count:
            payload = await _tmdb_get_json("discover/tv", {
                "include_adult": "false",
                "language": "en-US",
                "sort_by": sort_by,
                "with_origin_country": country,
                "with_original_language": language,
                "with_type": "2|4",
                "watch_region": "IN",
                "with_watch_monetization_types": "flatrate|free|ads",
                "first_air_date.gte": "2015-01-01",
                "first_air_date.lte": today,
                "page": source_page,
            })
            source_total_pages = max(1, min(int(payload.get("total_pages") or 1), 500))

            # Resolve independent series concurrently. The old sequential loop
            # made page 4+ wait for two remote requests per candidate in series.
            tv_lookup_semaphore = asyncio.Semaphore(8)

            async def verify_tv_item(item: Any) -> dict[str, Any] | None:
                if not isinstance(item, dict) or not item.get("id"):
                    return None
                try:
                    tmdb_id = int(item["id"])
                except (TypeError, ValueError):
                    return None
                origins = item.get("origin_country") or []
                original_language = str(item.get("original_language") or "").casefold()
                if country not in origins or original_language != language:
                    return None
                air_date = str(item.get("first_air_date") or "").strip()
                try:
                    parsed_air_date = datetime.strptime(air_date[:10], "%Y-%m-%d").date()
                    if parsed_air_date < datetime(2015, 1, 1).date() or parsed_air_date > datetime.now(timezone.utc).date():
                        return None
                except ValueError:
                    return None

                async with tv_lookup_semaphore:
                    try:
                        details = await _tmdb_get_json(f"tv/{tmdb_id}", {})
                    except Exception as exc:
                        logger.info("Skipping TV item %s because series type could not be verified: %s", tmdb_id, type(exc).__name__)
                        return None
                    series_type = str(details.get("type") or item.get("type") or "").casefold()
                    if series_type not in {"scripted", "miniseries"}:
                        return None

                    networks = details.get("networks") if isinstance(details.get("networks"), list) else []
                    genres = details.get("genres") if isinstance(details.get("genres"), list) else []
                    title_candidates = (details.get("name"), details.get("original_name"), item.get("name"), item.get("original_name"))
                    title_keys = {
                        re.sub(r"[^a-z0-9]+", "", str(title or "").casefold())
                        for title in title_candidates
                    }
                    if catalogue_key.startswith("indian-") and title_keys.intersection({"gangaa", "dearishq", "mastram"}):
                        return None
                    if exclude_indian_broadcast_networks:
                        if has_soap_genre(genres) or is_known_indian_soap(*title_candidates):
                            return None
                        if not networks or has_excluded_broadcast_network(networks):
                            return None

                    try:
                        providers = await _tv_streaming_providers(tmdb_id)
                    except Exception as exc:
                        logger.info("Skipping TV item %s because OTT availability could not be verified: %s", tmdb_id, type(exc).__name__)
                        return None
                    providers = [
                        provider for provider in providers
                        if str(provider.get("type") or "").casefold() in {"subscription", "free", "ads"}
                    ]
                    if not providers:
                        return None

                poster = str(item.get("poster_path") or details.get("poster_path") or "").strip()
                backdrop = str(item.get("backdrop_path") or details.get("backdrop_path") or "").strip()
                year_match = re.match(r"^(\d{4})", air_date)
                return {
                    "id": tmdb_id,
                    "title": str(item.get("name") or details.get("name") or "").strip(),
                    "year": int(year_match.group(1)) if year_match else None,
                    "releaseDate": air_date,
                    "overview": str(item.get("overview") or details.get("overview") or "").strip(),
                    "posterUrl": TMDB_IMAGE_BASE + poster if poster else "",
                    "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop if backdrop else "",
                    "rating": float(item.get("vote_average") or details.get("vote_average") or 0),
                    "tmdbUrl": f"https://www.themoviedb.org/tv/{tmdb_id}",
                    "streamingProviders": providers,
                    "providerLink": "",
                    "source": "TMDB",
                    "originalLanguage": original_language,
                    "originCountry": origins,
                    "seriesType": series_type,
                    "networks": networks,
                    "genres": genres,
                }

            verified_rows = await asyncio.gather(
                *(verify_tv_item(item) for item in payload.get("results", [])),
                return_exceptions=True,
            )
            for row in verified_rows:
                if isinstance(row, dict) and row.get("id") not in seen_ids:
                    eligible_rows.append(row)
                    seen_ids.add(int(row["id"]))
            source_page += 1
    except HTTPException:
        raise

    _save_regional_tv_prebuilt_pages(catalogue_key, eligible_rows)
    start_index = (page - 1) * 18
    results = eligible_rows[start_index:start_index + 18]
    # UI pages are 18 filtered titles each. Estimate the number of pages from
    # TMDB's candidate count; the last page may be shorter after verification.
    total_eligible_pages = max(1, (int(payload.get("total_results") or len(eligible_rows)) + 17) // 18)
    result = {
        "catalogue": catalogue_key, "page": page,
        "totalPages": total_eligible_pages,
        "totalResults": len(eligible_rows),
        "pageSize": 18,
        "provider": "TMDB + verified India OTT availability",
        "results": results,
    }
    _REGIONAL_TV_DISCOVERY_CACHE[cache_key] = (time.monotonic(), result)
    return result


async def _apply_movie_release_eligibility(payload: dict[str, Any], *, enabled: bool = True) -> dict[str, Any]:
    """Show films streaming on Indian OTT, or otherwise only after one month."""
    if not enabled or not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return payload
    today = datetime.now(timezone.utc).date()
    rows = [row for row in payload.get("results", []) if isinstance(row, dict)]
    semaphore = asyncio.Semaphore(4)

    async def eligible(row: dict[str, Any]) -> bool:
        # Older releases qualify without an OTT lookup. This avoids spending
        # provider quota on films that already pass the 30-day rule.
        raw_date = str(row.get("releaseDate") or row.get("release_date") or "").strip()
        try:
            release_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            release_date = None
        if release_date is not None and release_date <= today and (today - release_date).days >= 30:
            return True

        # Recent releases qualify only with verified subscription/free/ad-supported
        # streaming in India; rent/buy listings do not satisfy this rule.
        try:
            movie_id = int(row.get("tmdbId") or row.get("id") or 0)
        except (TypeError, ValueError):
            movie_id = 0
        if movie_id > 0:
            saved = row.get("ottAvailability")
            if isinstance(saved, dict):
                checked_at = str(saved.get("checkedAt") or "").strip()
                try:
                    checked_dt = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
                    if checked_dt.tzinfo is None:
                        checked_dt = checked_dt.replace(tzinfo=timezone.utc)
                    saved_is_fresh = 0 <= (datetime.now(timezone.utc) - checked_dt).total_seconds() < TMDB_OTT_CACHE_SECONDS
                except (TypeError, ValueError):
                    saved_is_fresh = False
                status = str(saved.get("status") or "").casefold()
                providers = saved.get("streamingProviders") or []
                if saved_is_fresh and status == "streaming" and providers:
                    return True
            async with semaphore:
                try:
                    ott_key = (movie_id, "IN")
                    now_monotonic = time.monotonic()
                    cached_ott = _tmdb_ott_cache.get(ott_key)
                    availability = None
                    stale_availability = cached_ott[1] if cached_ott else None
                    if cached_ott and now_monotonic - cached_ott[0] < _tmdb_ott_ttl(cached_ott[1]):
                        availability = cached_ott[1]
                    if availability is None:
                        persistent_ott = _read_tmdb_ott_persistent_cache(ott_key)
                        if persistent_ott:
                            saved_at, persistent_payload = persistent_ott
                            if 0 <= time.time() - saved_at < _tmdb_ott_ttl(persistent_payload):
                                availability = persistent_payload
                                _tmdb_ott_cache[ott_key] = (time.monotonic(), availability)
                            elif stale_availability is None:
                                stale_availability = persistent_payload
                    if availability is None:
                        try:
                            availability = await asyncio.wait_for(
                                _tmdb_fetch_movie_ott_availability(movie_id, "IN"), timeout=12
                            )
                        except Exception:
                            if stale_availability is None:
                                raise
                            availability = stale_availability
                        else:
                            _tmdb_ott_cache[ott_key] = (time.monotonic(), availability)
                            _write_tmdb_ott_persistent_cache(ott_key, availability)
                    status = str(availability.get("status") or "").casefold() if isinstance(availability, dict) else ""
                    providers = availability.get("streamingProviders") or [] if isinstance(availability, dict) else []
                    if status == "streaming" and providers:
                        row["ottAvailability"] = availability
                        return True
                except Exception as exc:
                    logger.info("OTT eligibility lookup failed for movie %s: %s", movie_id, type(exc).__name__)

        # Missing, future, or too-recent release dates do not qualify unless
        # verified Indian OTT streaming was confirmed above.
        return False

    flags = await asyncio.gather(*(eligible(row) for row in rows))
    filtered = [row for row, keep in zip(rows, flags) if keep]
    result = dict(payload)
    result["results"] = filtered
    result["totalResults"] = len(filtered)
    result["releaseEligibility"] = "streaming-in-india-or-30-days"
    return result


def _regional_movie_week_start(value: date | None = None) -> str:
    current = value or datetime.now(timezone.utc).date()
    return (current - timedelta(days=current.weekday())).isoformat()


def _read_regional_movie_trending_archive() -> dict[str, Any]:
    try:
        payload = json.loads(REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": 1, "weeks": []}
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Could not read weekly regional trending archive: %s", exc)
        return {"version": 1, "weeks": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("weeks"), list):
        logger.warning("Ignoring invalid weekly regional trending archive")
        return {"version": 1, "weeks": []}
    return payload


def _write_regional_movie_trending_archive(payload: dict[str, Any]) -> bool:
    try:
        REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_path = REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE.with_name(
            REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE.name + "." + uuid.uuid4().hex + ".tmp"
        )
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_path, REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE)
        return True
    except (OSError, TypeError, ValueError) as exc:
        logger.exception("Could not write weekly regional trending archive: %s", exc)
        return False


def _regional_movie_trending_archive_page(catalogue_key: str, page: int) -> dict[str, Any] | None:
    cache_key = (catalogue_key + "|weekly-archive-v1", page)
    cached = _tmdb_movie_catalogue_cache.get(cache_key)
    if cached:
        return cached[1]

    archive = _read_regional_movie_trending_archive()
    snapshots = [
        week for week in archive["weeks"]
        if isinstance(week, dict)
        and isinstance(week.get("catalogues"), dict)
        and isinstance(week["catalogues"].get(catalogue_key), list)
    ]
    snapshots.sort(key=lambda week: str(week.get("weekOf") or ""), reverse=True)
    if not snapshots:
        return None

    unique_rows: dict[str, dict[str, Any]] = {}
    for week in snapshots:
        week_of = str(week.get("weekOf") or "")
        rows = week["catalogues"][catalogue_key]
        for rank, source_row in enumerate(rows, 1):
            if not isinstance(source_row, dict):
                continue
            row = dict(source_row)
            title = str(row.get("title") or row.get("name") or "").strip()
            if not title:
                continue
            identity = str(row.get("tmdbId") or row.get("id") or "").strip()
            if not identity:
                identity = re.sub(r"[^a-z0-9]+", "", title.casefold()) + "|" + str(row.get("year") or "")
            existing = unique_rows.get(identity)
            if existing:
                history = list(existing.get("trendingWeeks") or [])
                if week_of and week_of not in history:
                    history.append(week_of)
                    existing["trendingWeeks"] = history
                continue
            row["trendingWeek"] = week_of
            row["trendingRank"] = int(row.get("trendingRank") or rank)
            row["trendingWeeks"] = [week_of] if week_of else []
            unique_rows[identity] = row

    rows = list(unique_rows.values())
    page_size = REGIONAL_MOVIE_CACHE_PAGE_SIZE
    total_results = len(rows)
    total_pages = max(1, (total_results + page_size - 1) // page_size)
    start = (page - 1) * page_size
    response = {
        "catalogue": catalogue_key,
        "releasedOnly": True,
        "provider": "TMDB weekly trending archive",
        "page": page,
        "totalPages": total_pages,
        "totalResults": total_results,
        "pageSize": page_size,
        "results": rows[start:start + page_size],
        "releaseEligibility": "streaming-in-india-or-30-days",
        "attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
    }
    _tmdb_movie_catalogue_cache[cache_key] = (time.monotonic(), response)
    return response


def _save_regional_movie_trending_week(
    week_of: str,
    catalogue_key: str,
    rows: list[dict[str, Any]],
) -> bool:
    archive = _read_regional_movie_trending_archive()
    weeks = [
        week for week in archive["weeks"]
        if isinstance(week, dict) and str(week.get("weekOf") or "") != week_of
    ]
    current_week = next(
        (
            week for week in archive["weeks"]
            if isinstance(week, dict) and str(week.get("weekOf") or "") == week_of
        ),
        None,
    )
    if current_week is None:
        current_week = {"weekOf": week_of, "catalogues": {}}
    catalogues = current_week.get("catalogues")
    if not isinstance(catalogues, dict):
        catalogues = {}
    catalogues[catalogue_key] = [
        {**row, "trendingWeek": week_of, "trendingRank": rank}
        for rank, row in enumerate(rows, 1)
    ]
    current_week["catalogues"] = catalogues
    weeks.append(current_week)
    weeks.sort(key=lambda week: str(week.get("weekOf") or ""), reverse=True)
    archive.update({
        "version": 1,
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "weeks": weeks[:REGIONAL_MOVIE_TRENDING_ARCHIVE_WEEKS],
    })
    if not _write_regional_movie_trending_archive(archive):
        return False
    for key in ("trending-hollywood", "trending-bollywood"):
        for cache_key in [item for item in _tmdb_movie_catalogue_cache if item[0] == key + "|weekly-archive-v1"]:
            _tmdb_movie_catalogue_cache.pop(cache_key, None)
    return True


def _cache_only_regional_movie_catalogue(catalogue_key: str, page: int) -> dict[str, Any] | None:
    """Build a regional movie page from shipped snapshots when live TMDB is disabled."""
    if catalogue_key.startswith("trending-"):
        archive_page = _regional_movie_trending_archive_page(catalogue_key, page)
        if archive_page is not None:
            return archive_page

    page_size = REGIONAL_MOVIE_CACHE_PAGE_SIZE
    today = datetime.now(timezone.utc).date().isoformat()
    rows_by_identity: dict[str, dict[str, Any]] = {}
    prebuilt_paths = (
        REGIONAL_MOVIE_PREBUILT_CACHE_PATH,
        _CACHE_SEED_DIR / "runtime" / "regional_movie_prebuilt_cache.json",
    )
    seen_paths: set[str] = set()
    for path in prebuilt_paths:
        identity = str(path)
        if identity in seen_paths:
            continue
        seen_paths.add(identity)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not read regional movie snapshot %s: %s", path, exc)
            continue
        movies = payload.get("movies") if isinstance(payload, dict) else None
        if not isinstance(movies, dict):
            continue
        for entry in movies.values():
            if not isinstance(entry, dict) or catalogue_key not in (entry.get("catalogues") or []):
                continue
            movie = entry.get("movie")
            if not isinstance(movie, dict):
                continue
            row = dict(movie)
            if catalogue_key == "latest-bollywood" and row.get("nexStreamPlayable") is not True:
                continue
            if catalogue_key == "latest-bollywood" and _is_bollywood_comedy_special(row):
                continue
            release_date = str(row.get("releaseDate") or row.get("release_date") or "").strip()
            if release_date and not _tmdb_release_date_is_released(release_date[:10], today):
                continue
            row.setdefault("tmdbId", row.get("id"))
            row.setdefault("source", "Bundled TMDB cache")
            movie_id = str(row.get("tmdbId") or row.get("id") or "").strip()
            title_key = re.sub(r"[^a-z0-9]+", "", str(row.get("title") or "").casefold())
            key = movie_id or (title_key + "|" + str(row.get("year") or ""))
            if key.strip("|"):
                rows_by_identity.setdefault(key, row)

    if not rows_by_identity and catalogue_key == "latest-hollywood":
        seed_path = _CACHE_SEED_DIR / "latest_hollywood_catalogue.json"
        try:
            payload = json.loads(seed_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            payload = {}
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not read Hollywood latest snapshot %s: %s", seed_path, exc)
            payload = {}
        for source_row in payload.get("results", []) if isinstance(payload, dict) else []:
            if not isinstance(source_row, dict):
                continue
            row = dict(source_row)
            row["title"] = str(
                row.get("catalogueTitle") or row.get("mediaTitle") or row.get("title") or ""
            ).strip()
            if not row["title"]:
                continue
            release_date = str(row.get("releaseDate") or row.get("release_date") or "").strip()
            if release_date and not _tmdb_release_date_is_released(release_date[:10], today):
                continue
            key = str(row.get("tmdbId") or "").strip() or (
                re.sub(r"[^a-z0-9]+", "", row["title"].casefold())
                + "|" + str(row.get("year") or "")
            )
            if not row.get("id"):
                row["id"] = row.get("tmdbId") or key
            row.setdefault("source", "Bundled Hollywood latest cache")
            rows_by_identity.setdefault(key, row)

    if not rows_by_identity:
        return None

    rows = sorted(
        rows_by_identity.values(),
        key=lambda row: (
            str(row.get("releaseDate") or row.get("release_date") or ""),
            re.sub(r"[^a-z0-9]+", "", str(row.get("title") or "").casefold()),
        ),
        reverse=True,
    )
    total_results = len(rows)
    total_pages = max(1, (total_results + page_size - 1) // page_size)
    start = (page - 1) * page_size
    return {
        "catalogue": catalogue_key,
        "releasedOnly": True,
        "provider": "Bundled TMDB cache",
        "page": page,
        "totalPages": total_pages,
        "totalResults": total_results,
        "pageSize": page_size,
        "results": rows[start:start + page_size],
        "releaseEligibility": "streaming-in-india-or-30-days",
        "attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
    }


def _regional_movie_cache_page_is_usable(payload: dict[str, Any], page: int) -> bool:
    results = payload.get("results")
    if not isinstance(results, list):
        return False
    try:
        total_results = int(payload.get("totalResults") or 0)
        total_pages = int(payload.get("totalPages") or 0)
    except (TypeError, ValueError, OverflowError):
        return bool(results)
    return bool(results) or total_results == 0 or page > total_pages


async def _fetch_paginated_regional_movie_catalogue(catalogue_key: str, page: int) -> dict[str, Any]:
    """Build stable 18-item display pages from eligible regional movie candidates."""
    page_size = REGIONAL_MOVIE_CACHE_PAGE_SIZE
    wanted = page * page_size + 1
    is_trending = catalogue_key.startswith("trending-")
    is_bollywood_latest = catalogue_key == "latest-bollywood"
    force_refresh = _REGIONAL_MOVIE_SOURCE_FORCE_REFRESH.get()
    refreshed_source_keys = _REGIONAL_MOVIE_SOURCE_REFRESHED_KEYS.get()
    # Trending is global; language + India release/OTT eligibility can discard
    # most candidates. Scan up to 30 weekly-trending pages to fill each
    # 18-card regional page without borrowing popularity-ranked Discover rows.
    max_source_pages = min(30, max(3, page)) if is_bollywood_latest else 30
    source_cache_variant = (
        "|trending-v4" if is_trending
        else "|released-v7" if catalogue_key == "latest-bollywood"
        else "|released-v6"
    )
    source_cache_prefix = catalogue_key + source_cache_variant
    seen_ids: set[str] = set()
    eligible_rows: list[dict[str, Any]] = []
    source_total_pages = max_source_pages
    exhausted = True

    for source_page in range(1, max_source_pages + 1):
        cache_key = (source_cache_prefix, source_page)
        refresh_source_page = force_refresh and (
            refreshed_source_keys is None or cache_key not in refreshed_source_keys
        )
        cached = _tmdb_movie_catalogue_cache.get(cache_key)
        source_payload = cached[1] if (
            not refresh_source_page and cached
            and time.monotonic() - cached[0] < REGIONAL_MOVIE_CACHE_TTL_SECONDS
        ) else None
        if source_payload is not None:
            _record_cache_event("regional_movie_source_page", "memory_hit")
        if cached and source_payload is None:
            _tmdb_movie_catalogue_cache.pop(cache_key, None)
        if source_payload is None and not refresh_source_page:
            persistent = _read_tmdb_persistent_cache(cache_key)
            if persistent and 0 <= time.time() - persistent[0] < REGIONAL_MOVIE_CACHE_TTL_SECONDS:
                _record_cache_event("regional_movie_source_page", "persistent_hit")
                source_payload = persistent[1]
                _tmdb_movie_catalogue_cache[cache_key] = (time.monotonic(), source_payload)
        if source_payload is None:
            _record_cache_event("regional_movie_source_page", "miss")
            source_payload = await _tmdb_fetch_movie_catalogue(catalogue_key, source_page, True)
            _tmdb_movie_catalogue_cache[cache_key] = (time.monotonic(), source_payload)
            _write_tmdb_persistent_cache(cache_key, source_payload)
            if refreshed_source_keys is not None:
                refreshed_source_keys.add(cache_key)
        source_total_pages = min(
            max_source_pages,
            500,
            max(1, int(source_payload.get("totalPages") or source_page)),
        )
        filtered_payload = await _apply_movie_release_eligibility(source_payload, enabled=True)
        source_candidates: list[dict[str, Any]] = []
        for row in filtered_payload.get("results") or []:
            if not isinstance(row, dict):
                continue
            if is_bollywood_latest and _is_bollywood_comedy_special(row):
                continue
            title_key = re.sub(r"[^a-z0-9]+", "", str(row.get("title") or row.get("name") or "").casefold())
            # Filter known catalogue contamination before pagination, allowing
            # later source candidates to backfill the page to 18 cards.
            excluded_regional_titles = {"tantesiska", "kunwaridulhan", "mastram"}
            if catalogue_key == "popular-bollywood" and title_key in excluded_regional_titles:
                continue
            identity = str(row.get("id") or row.get("tmdbId") or row.get("title") or "").strip()
            if not identity or identity in seen_ids:
                continue
            seen_ids.add(identity)
            source_candidates.append(row)
        if is_bollywood_latest and source_candidates:
            playable_rows = await _filter_nexstream_playable_movies(source_candidates)
            eligible_rows.extend(playable_rows)
        else:
            eligible_rows.extend(source_candidates)
        if len(eligible_rows) >= wanted:
            exhausted = source_page >= source_total_pages
            break
        if source_page >= source_total_pages:
            exhausted = True
            break
        exhausted = False

    start = (page - 1) * page_size
    page_rows = eligible_rows[start:start + page_size]
    if exhausted:
        total_pages = max(1, (len(eligible_rows) + page_size - 1) // page_size)
    else:
        # Progressive pagination: the next display page is available, and its
        # request will scan further source pages if the user continues.
        total_pages = max(page + 1, (len(eligible_rows) + page_size - 1) // page_size)
    return {
        "catalogue": catalogue_key,
        "releasedOnly": True,
        "provider": "TMDB + verified India OTT availability",
        "page": page,
        "totalPages": total_pages,
        "totalResults": len(eligible_rows) if exhausted else max(len(eligible_rows), (page + 1) * page_size),
        "pageSize": page_size,
        "results": page_rows,
        "releaseEligibility": "streaming-in-india-or-30-days",
        "attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
    }


async def _enrich_regional_movie_catalogue_metadata(
    payload: dict[str, Any],
) -> dict[str, Any]:
    rows = payload.get("results")
    if not isinstance(rows, list):
        return payload

    semaphore = asyncio.Semaphore(4)

    async def enrich(row: Any) -> None:
        if not isinstance(row, dict):
            return
        try:
            movie_id = int(row.get("tmdbId") or row.get("id") or 0)
        except (TypeError, ValueError):
            movie_id = 0
        title = str(row.get("title") or "").strip()
        try:
            year = int(row.get("year") or 0)
        except (TypeError, ValueError):
            year = 0
        if movie_id <= 0 or not title:
            return

        async with semaphore:
            try:
                rating = await _get_imdb_rating_record(
                    title, year, "movie", movie_id,
                )
                row["imdbRatingStatus"] = str(rating.get("status") or "unavailable")
                for source_field, target_field in (
                    ("imdbRating", "imdbRating"),
                    ("imdbVotes", "imdbVotes"),
                    ("imdbId", "imdbId"),
                    ("imdbUrl", "imdbUrl"),
                    ("checkedAt", "imdbCheckedAt"),
                ):
                    value = rating.get(source_field)
                    if value is not None:
                        row[target_field] = value
            except Exception:
                logger.warning(
                    "IMDb enrichment failed for regional movie %s (%s)",
                    title, movie_id, exc_info=True,
                )
                row["imdbRatingStatus"] = "unavailable"

            try:
                row["ottAvailability"] = await api_tmdb_movie_ott_availability(
                    movie_id, region="IN",
                )
            except Exception as exc:
                logger.info(
                    "OTT enrichment unavailable for regional movie %s (%s): %s",
                    title, movie_id, type(exc).__name__,
                )
                row["ottAvailability"] = {
                    "movieId": movie_id,
                    "region": "IN",
                    "status": "unavailable",
                    "streamingProviders": [],
                    "rentProviders": [],
                    "buyProviders": [],
                    "checkedAt": datetime.now(timezone.utc).isoformat(),
                }

    await asyncio.gather(*(enrich(row) for row in rows))
    return payload


async def _filter_nexstream_playable_movies(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not nexstream_api_key_configured():
        raise HTTPException(
            status_code=503,
            detail="NEXSTREAM_API_KEY is required to build the playable Bollywood Latest catalogue.",
        )
    if not rows:
        return []

    semaphore = asyncio.Semaphore(4)

    async def check(row: dict[str, Any]) -> dict[str, Any]:
        try:
            movie_id = int(row.get("tmdbId") or row.get("id") or 0)
        except (TypeError, ValueError):
            movie_id = 0
        if movie_id <= 0:
            return {"success": False, "sources": []}
        async with semaphore:
            return await resolve_nexstream_movie(movie_id)

    checks = await asyncio.gather(
        *(check(row) for row in rows),
        return_exceptions=True,
    )
    playable_rows = []
    transient_failures = 0
    for row, result in zip(rows, checks):
        if isinstance(result, BaseException):
            if not isinstance(result, Exception):
                raise result
            transient_failures += 1
            logger.info(
                "NexStream playback check failed for %s (%s): %s",
                row.get("title"), row.get("id"), type(result).__name__,
            )
            continue
        sources = result.get("sources")
        if result.get("success") and isinstance(sources, list) and sources:
            row["nexStreamPlayable"] = True
            row["nexStreamCheckedAt"] = datetime.now(timezone.utc).isoformat()
            playable_rows.append(row)

    if not playable_rows and transient_failures:
        raise HTTPException(
            status_code=503,
            detail="NexStream checks failed before any playable Bollywood Latest title could be verified.",
        )
    if transient_failures:
        logger.warning(
            "Publishing %s verified NexStream titles; %s movie checks failed.",
            len(playable_rows), transient_failures,
        )
    return playable_rows


@app.get("/api/movies/catalogue/{catalogue_key}")
async def api_tmdb_movie_catalogue(
    catalogue_key: str,
    page: int = Query(1, ge=1, le=500),
    released_only: bool = Query(True),
    max_size_gb: int = Query(5, ge=1, le=5),
    basic: bool = Query(False),
):
    allowed = {
        "marvel", "dc-live-action", "dc-animated",
        "popular-bollywood", "trending-bollywood", "latest-bollywood",
        "popular-hollywood", "trending-hollywood", "latest-hollywood",
    }
    if catalogue_key not in allowed:
        raise HTTPException(status_code=404, detail="Unknown movie catalogue.")

    if basic:
        # Fast first paint for deep pages: return basic source metadata immediately;
        # the frontend replaces this with the fully eligible/enriched page.
        fast_variant = (
            "|fast-basic-v4" if catalogue_key == "latest-bollywood"
            else "|fast-basic-v3" if catalogue_key == "marvel"
            else "|fast-basic-v2"
        )
        fast_key = (catalogue_key + fast_variant, page)
        fast_cached = _tmdb_movie_catalogue_cache.get(fast_key)
        if fast_cached and time.monotonic() - fast_cached[0] < 900:
            _record_cache_event("movie_catalogue", "fast_memory_hit")
            return fast_cached[1]
        _record_cache_event("movie_catalogue", "fast_miss")
        raw = await _tmdb_fetch_movie_catalogue(catalogue_key, page, True)
        rows = [row for row in (raw.get("results") or []) if isinstance(row, dict)]
        normalized_titles = {
            re.sub(r"[^a-z0-9]+", "", str(row.get("title") or "").casefold())
            for row in rows
        }
        # Keep the same permanent exclusions in the fast first-paint response.
        excluded_bollywood = {"tantesiska", "kunwaridulhan", "mastram"}
        if catalogue_key == "popular-bollywood":
            rows = [row for row in rows if re.sub(r"[^a-z0-9]+", "", str(row.get("title") or "").casefold()) not in excluded_bollywood]
        if catalogue_key in {"popular-bollywood", "trending-bollywood", "latest-bollywood"}:
            rows = [row for row in rows if re.sub(r"[^a-z0-9]+", "", str(row.get("title") or "").casefold()) not in {"gangaa", "dearishq", "mastram"}]
        if catalogue_key == "latest-bollywood":
            rows = await _filter_nexstream_playable_movies(rows)
        fast_payload = dict(raw)
        fast_payload.update({"catalogue": catalogue_key, "page": page, "results": rows[:18], "pageSize": 18, "basic": True})
        _tmdb_movie_catalogue_cache[fast_key] = (time.monotonic(), fast_payload)
        return fast_payload

    if released_only and catalogue_key in {
        "popular-bollywood", "trending-bollywood", "latest-bollywood",
        "popular-hollywood", "trending-hollywood", "latest-hollywood",
    }:
        force_refresh = _REGIONAL_MOVIE_CATALOGUE_FORCE_REFRESH.get()
        if catalogue_key.startswith("trending-") and not force_refresh:
            archived_page = _regional_movie_trending_archive_page(catalogue_key, page)
            if archived_page is not None:
                _record_cache_event("movie_catalogue", "weekly_trending_archive_hit")
                return archived_page

        eligible_cache_key = (catalogue_key + "|eligible-v6", page)
        eligible_cached = _tmdb_movie_catalogue_cache.get(eligible_cache_key)
        stale_payload = None
        if eligible_cached:
            cached_payload = eligible_cached[1]
            if _regional_movie_cache_page_is_usable(cached_payload, page):
                stale_payload = cached_payload
                if (
                    not force_refresh
                    and time.monotonic() - eligible_cached[0] < REGIONAL_MOVIE_CACHE_TTL_SECONDS
                ):
                    _record_cache_event("movie_catalogue", "eligible_memory_hit")
                    return cached_payload
            else:
                logger.warning(
                    "Ignoring empty regional movie cache page %s for %s with a positive total",
                    page, catalogue_key,
                )
                _tmdb_movie_catalogue_cache.pop(eligible_cache_key, None)
        eligible_persistent = _read_tmdb_persistent_cache(eligible_cache_key)
        if eligible_persistent:
            payload = eligible_persistent[1]
            if _regional_movie_cache_page_is_usable(payload, page):
                if stale_payload is None:
                    stale_payload = payload
                if (
                    not force_refresh
                    and 0 <= time.time() - eligible_persistent[0] < REGIONAL_MOVIE_CACHE_TTL_SECONDS
                ):
                    _record_cache_event("movie_catalogue", "eligible_persistent_hit")
                    age_seconds = max(0.0, time.time() - eligible_persistent[0])
                    _tmdb_movie_catalogue_cache[eligible_cache_key] = (
                        time.monotonic() - age_seconds,
                        payload,
                    )
                    return payload
            else:
                logger.warning(
                    "Ignoring empty regional movie cache page %s for %s with a positive total",
                    page, catalogue_key,
                )
        if CACHE_ONLY_MODE:
            bundled_payload = _cache_only_regional_movie_catalogue(catalogue_key, page)
            if bundled_payload is not None:
                bundled_payload = await _enrich_regional_movie_catalogue_metadata(
                    bundled_payload,
                )
                _record_cache_event("movie_catalogue", "bundled_cache_hit")
                _tmdb_movie_catalogue_cache[eligible_cache_key] = (time.monotonic(), bundled_payload)
                logger.info(
                    "Serving bundled regional movie catalogue %s page %s (%s titles)",
                    catalogue_key, page, bundled_payload["totalResults"],
                )
                return bundled_payload
            if stale_payload is not None:
                stale_response = dict(stale_payload)
                stale_response["stale"] = True
                stale_response["cacheWarning"] = "Live TMDB refresh is disabled; showing the last saved catalogue."
                return stale_response
            raise HTTPException(
                status_code=503,
                detail=f"No saved movie catalogue is available for {catalogue_key}; configure TMDB credentials to load it.",
            )
        _record_cache_event("movie_catalogue", "eligible_miss")
        try:
            payload = await _fetch_paginated_regional_movie_catalogue(catalogue_key, page)
            payload = await _enrich_regional_movie_catalogue_metadata(payload)
        except Exception as exc:
            if stale_payload is None:
                raise
            logger.exception(
                "Regional movie catalogue refresh failed for %s page %s; serving stale cached data",
                catalogue_key, page,
            )
            stale_response = dict(stale_payload)
            stale_response["stale"] = True
            stale_response["cacheWarning"] = "TMDB is temporarily unavailable; showing the last saved catalogue."
            return stale_response
        _tmdb_movie_catalogue_cache[eligible_cache_key] = (time.monotonic(), payload)
        _write_tmdb_persistent_cache(eligible_cache_key, payload)
        return payload

    # Keep released-only and include-upcoming responses in separate cache slots.
    is_trending_catalogue = catalogue_key.startswith("trending-")
    cache_variant = (
        "|trending-v4" if is_trending_catalogue
        else ("|released-v7" if catalogue_key == "marvel" else "|released-v6") if released_only
        else ("|upcoming-v4" if catalogue_key == "marvel" else "|upcoming-v3")
    )
    cache_key = (catalogue_key + cache_variant, page)
    now = time.monotonic()
    is_regional_movie_catalogue = catalogue_key in {
        "popular-bollywood", "trending-bollywood", "latest-bollywood",
        "popular-hollywood", "trending-hollywood", "latest-hollywood",
    }
    # Regional movie pages 1-3 are durable VPS catalogue snapshots. Keep using
    # them across restarts/TTL expiry; refresh only when a page has never been saved.
    durable_regional_page = is_regional_movie_catalogue and not is_trending_catalogue and page <= 3
    cache_ttl = min(TMDB_CATALOGUE_CACHE_SECONDS, 900) if catalogue_key.startswith("trending-") else TMDB_CATALOGUE_CACHE_SECONDS
    cached = _tmdb_movie_catalogue_cache.get(cache_key)
    if cached and (durable_regional_page or now - cached[0] < cache_ttl):
        _record_cache_event("movie_catalogue", "memory_hit")
        _schedule_tmdb_catalogue_synopsis_enrichment(cached[1])
        return await _apply_movie_release_eligibility(cached[1], enabled=released_only)

    # A disk cache survives container restarts, unlike the in-memory TTL cache.
    persistent = None if is_trending_catalogue else _read_tmdb_persistent_cache(cache_key)
    if persistent:
        saved_at, persistent_payload = persistent
        age_seconds = max(0.0, time.time() - saved_at)
        if durable_regional_page or age_seconds < cache_ttl:
            _record_cache_event("movie_catalogue", "persistent_hit")
            _tmdb_movie_catalogue_cache[cache_key] = (
                time.monotonic() - age_seconds,
                persistent_payload,
            )
            _schedule_tmdb_catalogue_synopsis_enrichment(persistent_payload)
            return await _apply_movie_release_eligibility(persistent_payload, enabled=released_only)

    _record_cache_event("movie_catalogue", "miss")
    task = _tmdb_movie_catalogue_inflight.get(cache_key)
    if task is None or task.done():
        task = asyncio.create_task(_tmdb_fetch_movie_catalogue(catalogue_key, page, released_only))
        _tmdb_movie_catalogue_inflight[cache_key] = task
    try:
        payload = await task
        _tmdb_movie_catalogue_cache[cache_key] = (time.monotonic(), payload)
        if not is_trending_catalogue:
            _write_tmdb_persistent_cache(cache_key, payload)
        _schedule_tmdb_catalogue_synopsis_enrichment(payload)
        return await _apply_movie_release_eligibility(payload, enabled=released_only)
    except HTTPException as exc:
        # Prefer a stale response over an empty screen when TMDB has an outage.
        stale_payload = cached[1] if cached else (persistent[1] if persistent else None)
        if stale_payload:
            stale_response = dict(stale_payload)
            stale_response["stale"] = True
            stale_response["cacheWarning"] = exc.detail
            logger.warning("Serving stale TMDB catalogue %s page %s after upstream failure", catalogue_key, page)
            _schedule_tmdb_catalogue_synopsis_enrichment(stale_response)
            return await _apply_movie_release_eligibility(stale_response, enabled=released_only)
        raise
    except Exception as exc:
        logger.exception("TMDB movie catalogue failed for %s page %s", catalogue_key, page)
        stale_payload = cached[1] if cached else (persistent[1] if persistent else None)
        if stale_payload:
            stale_response = dict(stale_payload)
            stale_response["stale"] = True
            stale_response["cacheWarning"] = "TMDB is temporarily unavailable; showing the last cached catalogue."
            _schedule_tmdb_catalogue_synopsis_enrichment(stale_response)
            return await _apply_movie_release_eligibility(stale_response, enabled=released_only)
        raise HTTPException(status_code=502, detail="Could not load the movie catalogue from TMDB.") from exc
    finally:
        if task.done() and _tmdb_movie_catalogue_inflight.get(cache_key) is task:
            _tmdb_movie_catalogue_inflight.pop(cache_key, None)


@app.get("/api/movies/ott/{movie_id}")
async def api_tmdb_movie_ott_availability(
    movie_id: int,
    region: str = Query("IN", min_length=2, max_length=2),
    force: bool = Query(False),
):
    """Return cached streaming, rental, purchase and digital-release data for one movie."""
    if movie_id < 1:
        raise HTTPException(status_code=404, detail="Unknown movie.")

    region = region.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", region):
        raise HTTPException(status_code=422, detail="Region must be a two-letter country code.")

    cache_key = (movie_id, region)
    cached = _tmdb_ott_cache.get(cache_key)
    stale_payload = cached[1] if cached else None
    if cached and not force and time.monotonic() - cached[0] < _tmdb_ott_ttl(cached[1]):
        _record_cache_event("ott", "memory_hit")
        return cached[1]

    persistent = None if force else _read_tmdb_ott_persistent_cache(cache_key)
    if persistent:
        saved_at, persistent_payload = persistent
        if 0 <= time.time() - saved_at < _tmdb_ott_ttl(persistent_payload):
            _record_cache_event("ott", "persistent_hit")
            _tmdb_ott_cache[cache_key] = (time.monotonic(), persistent_payload)
            return persistent_payload
        if stale_payload is None:
            stale_payload = persistent_payload

    # Serve expired-but-usable data immediately. Refresh in the background so
    # slow or rate-limited providers cannot block catalogue cards.
    if stale_payload is not None and not force:
        _record_cache_event("ott", "stale_hit")
        task = _tmdb_ott_inflight.get(cache_key)
        if not CACHE_ONLY_MODE and (task is None or task.done()):
            async def refresh_stale_ott_cache():
                try:
                    payload = await _tmdb_fetch_movie_ott_availability(movie_id, region)
                    _tmdb_ott_cache[cache_key] = (time.monotonic(), payload)
                    _write_tmdb_ott_persistent_cache(cache_key, payload)
                except Exception:
                    logger.warning(
                        "Background OTT refresh failed for movie %s in %s; keeping stale cache",
                        movie_id, region, exc_info=True,
                    )
                finally:
                    current = asyncio.current_task()
                    if _tmdb_ott_inflight.get(cache_key) is current:
                        _tmdb_ott_inflight.pop(cache_key, None)

            task = asyncio.create_task(refresh_stale_ott_cache())
            _tmdb_ott_inflight[cache_key] = task
        stale_response = dict(stale_payload)
        stale_response["stale"] = True
        stale_response["cacheWarning"] = "Showing cached OTT availability while it refreshes."
        return stale_response

    # A forced request intentionally bypasses stored entries; otherwise this is
    # a true cache miss. The helper blocks provider lookup when OTT_CACHE_ONLY=true.
    _record_cache_event("ott", "force_bypass" if force else "miss")
    task = _tmdb_ott_inflight.get(cache_key)
    owns_inflight_task = False
    if force:
        task = asyncio.create_task(_tmdb_fetch_movie_ott_availability(movie_id, region))
    elif task is None or task.done():
        task = asyncio.create_task(_tmdb_fetch_movie_ott_availability(movie_id, region))
        _tmdb_ott_inflight[cache_key] = task
        owns_inflight_task = True
    try:
        payload = await task
        _tmdb_ott_cache[cache_key] = (time.monotonic(), payload)
        _write_tmdb_ott_persistent_cache(cache_key, payload)
        return payload
    except HTTPException as exc:
        if stale_payload:
            stale_response = dict(stale_payload)
            stale_response["stale"] = True
            stale_response["cacheWarning"] = exc.detail
            return stale_response
        raise
    except Exception as exc:
        logger.exception("TMDB OTT availability failed for movie %s in %s", movie_id, region)
        if stale_payload:
            stale_response = dict(stale_payload)
            stale_response["stale"] = True
            stale_response["cacheWarning"] = "OTT availability is temporarily unavailable; showing the last cached result."
            return stale_response
        raise HTTPException(status_code=502, detail="Could not load OTT availability from TMDB.") from exc
    finally:
        if owns_inflight_task and task.done() and _tmdb_ott_inflight.get(cache_key) is task:
            _tmdb_ott_inflight.pop(cache_key, None)


def _marvel_ott_normalize_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


async def _resolve_marvel_tmdb_movie_id(title: str, year: int) -> tuple[int | None, str]:
    """Resolve a curated Marvel title from the saved review manifest, then TMDB search."""
    expected = _marvel_ott_normalize_title(title)

    # Reuse the user's manually reviewed manifest when it is mounted in /app/data.
    # This avoids wasting TMDB search calls for IDs that have already been resolved.
    manifest_path = Path(os.getenv(
        "MARVEL_TMDB_ID_REVIEW_PATH",
        "/app/data/marvel_tmdb_id_review.json",
    ))
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = manifest.get("movies", []) if isinstance(manifest, dict) else []
        matches = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_title = str(row.get("title") or row.get("movieTitle") or row.get("searchTitle") or "")
            row_year = row.get("year")
            row_id = row.get("tmdbId", row.get("movieId", row.get("id")))
            if _marvel_ott_normalize_title(row_title) == expected and (not row_year or int(row_year) == year):
                if isinstance(row_id, int) and row_id > 0:
                    matches.append(row_id)
        if len(set(matches)) == 1:
            return matches[0], "saved_manifest"
    except (OSError, ValueError, TypeError, AttributeError):
        pass

    # Render's OTT cache-only mode must not resolve unknown movie IDs over TMDB.
    # The reviewed manifest above remains the allowed offline ID source.
    if CACHE_ONLY_MODE:
        _record_cache_event("marvel_ott_backfill", "cache_only_id_miss_blocked")
        return None, "cache_only_no_saved_id"

    errors = []
    for params in (
        {"query": title, "year": year, "include_adult": "false", "language": "en-US", "page": 1},
        {"query": title, "include_adult": "false", "language": "en-US", "page": 1},
    ):
        try:
            payload = await _tmdb_get_json("search/movie", params)
        except Exception as exc:
            errors.append(str(getattr(exc, "detail", "") or type(exc).__name__))
            await asyncio.sleep(0.5)
            continue

        candidates = []
        for row in payload.get("results") or []:
            if not isinstance(row, dict) or not isinstance(row.get("id"), int):
                continue
            names = {
                _marvel_ott_normalize_title(row.get("title")),
                _marvel_ott_normalize_title(row.get("original_title")),
            }
            release_year = str(row.get("release_date") or "")[:4]
            if expected in names and (not release_year or release_year == str(year) or "year" not in params):
                candidates.append(row)
        ids = {int(row["id"]) for row in candidates}
        if len(ids) == 1:
            return next(iter(ids)), "exact_match" if "year" in params else "exact_match_year_fallback"
        if len(ids) > 1:
            return None, "ambiguous_exact_match"

    if errors:
        logger.warning("Marvel OTT ID lookup failed for %s (%s): %s", title, year, "; ".join(errors))
        return None, "lookup_failed: " + errors[-1][:180]
    return None, "no_exact_tmdb_match"


@app.get("/api/movies/ott/backfill/marvel")
async def api_backfill_marvel_ott(
    offset: int = Query(0, ge=0),
    limit: int = Query(5, ge=1, le=10),
    region: str = Query("IN", min_length=2, max_length=2),
    force: bool = Query(False),
):
    """One-time, resumable Marvel OTT backfill. Results are saved to the permanent disk cache."""
    region = region.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", region):
        raise HTTPException(status_code=422, detail="Region must be a two-letter country code.")
    total = len(MARVEL_MOVIE_SEARCHES)
    if offset >= total:
        return {"status": "complete", "offset": offset, "limit": limit, "total": total, "processed": 0, "results": []}

    batch = MARVEL_MOVIE_SEARCHES[offset:offset + limit]
    results: list[dict[str, Any]] = []
    for title, year in batch:
        movie_id, resolution = await _resolve_marvel_tmdb_movie_id(title, year)
        if movie_id is None:
            results.append({
                "title": title, "year": year, "status": "unresolved_tmdb_id",
                "resolution": resolution, "movieId": None,
            })
            continue

        cache_key = (movie_id, region)
        saved = _read_tmdb_ott_persistent_cache(cache_key)
        memory = _tmdb_ott_cache.get(cache_key)
        payload = None
        if not force and saved:
            payload = saved[1]
        elif not force and memory:
            payload = memory[1]
        if payload is None:
            try:
                payload = await _tmdb_fetch_movie_ott_availability(movie_id, region)
            except Exception as exc:
                results.append({
                    "title": title, "year": year, "status": "lookup_failed",
                    "resolution": resolution, "movieId": movie_id,
                    "error": str(getattr(exc, "detail", "") or type(exc).__name__),
                })
                continue
            _write_tmdb_ott_persistent_cache(cache_key, payload)
            _tmdb_ott_cache[cache_key] = (time.monotonic(), payload)

        providers = payload.get("streamingProviders") or []
        rent = payload.get("rentProviders") or []
        buy = payload.get("buyProviders") or []
        results.append({
            "title": title, "year": year, "movieId": movie_id,
            "resolution": resolution,
            "status": "streaming_info_found" if providers else "no_streaming_provider_reported",
            "streamingProviders": [p.get("name") for p in providers if isinstance(p, dict)],
            "rentProviders": [p.get("name") for p in rent if isinstance(p, dict)],
            "buyProviders": [p.get("name") for p in buy if isinstance(p, dict)],
            "providerLink": payload.get("providerLink"),
            "cacheSaved": bool(saved) or payload is not None,
        })

    counts: dict[str, int] = {}
    for row in results:
        key = str(row.get("status") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return {
        "status": "batch_processed",
        "region": region,
        "offset": offset,
        "limit": limit,
        "total": total,
        "processed": len(results),
        "nextOffset": offset + len(batch),
        "counts": counts,
        "results": results,
    }


@app.get("/api/catalogue/extra/{catalogue_key}")
async def api_extra_catalogue(catalogue_key: str, request: Request, page: int = Query(0, ge=0), page_size: int = Query(0, ge=0, le=200)):
    if catalogue_key not in _EXTRA_CATALOGUES:
        raise HTTPException(404, "Unknown catalogue")
    if CACHE_ONLY_MODE:
        prebuilt = _prebuilt_catalogue_page(request, catalogue_key, page, page_size)
        if prebuilt is not None:
            return prebuilt
    cached = _read_extra_catalogue(catalogue_key)
    _record_cache_event("extra_catalogue", "hit" if cached else "miss")
    if cached and CACHE_ONLY_MODE:
        return _fast_json_response(request, "extra:%s:%d:%d" % (catalogue_key, page, page_size), _file_signature(_EXTRA_CATALOGUE_PATHS[catalogue_key]), lambda: _page_catalogue_payload({
            "status": "ready", "builtAt": cached.get("builtAt"),
            "completed": int(cached.get("titlesQueried") or 0), "total": int(cached.get("titlesQueried") or 0),
            "resultCount": int(cached.get("resultCount") or len(cached["results"])),
            "movieCount": int(cached.get("movieCount") or 0), "refreshing": False,
            "results": cached["results"]}, page, page_size,
            sort_by_release_date=catalogue_key in _DATE_SORTED_EXTRA_CATALOGUES))
    if catalogue_key == "classics" and cached:
        _schedule_classics_movie_ott_enrichment()
    await _ensure_extra_catalogue_refresh(catalogue_key)
    state = _extra_catalogue_states[catalogue_key]
    # For monthly catalogues, stale-but-useful data is returned immediately while
    # the refresh runs; first-ever builds report progress for the UI to poll.
    if cached:
        response_payload = {
            "status": "ready",
            "builtAt": cached.get("builtAt"),
            "completed": int(cached.get("titlesQueried") or 0),
            "total": int(cached.get("titlesQueried") or 0),
            "resultCount": int(cached.get("resultCount") or len(cached["results"])),
            "movieCount": int(cached.get("movieCount") or 0),
            "refreshing": bool(_extra_catalogue_tasks.get(catalogue_key) and not _extra_catalogue_tasks[catalogue_key].done()),
            "results": cached["results"],
        }
        if page > 0 and page_size > 0:
            return _fast_json_response(
                request,
                "extra:%s:%d:%d" % (catalogue_key, page, page_size),
                _file_signature(_EXTRA_CATALOGUE_PATHS[catalogue_key]),
                lambda: _page_catalogue_payload(
                    response_payload,
                    page,
                    page_size,
                    sort_by_release_date=catalogue_key in _DATE_SORTED_EXTRA_CATALOGUES,
                ),
            )
        return response_payload
    return {**state, "results": []}


_classics_ott_enrichment_task: asyncio.Task | None = None

async def _enrich_classics_movie_ott_cache() -> None:
    """Backfill India OTT metadata for existing Favourites movie cache rows."""
    key = "classics"
    path = _EXTRA_CATALOGUE_PATHS[key]
    try:
        payload = _read_extra_catalogue(key)
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            return
        rows = payload["results"]
        semaphore = asyncio.Semaphore(3)
        changed = False

        async def enrich(row: dict[str, Any]) -> None:
            nonlocal changed
            existing = row.get("ottAvailability")
            if isinstance(existing, dict):
                checked_at = str(existing.get("checkedAt") or "").strip()
                status = str(existing.get("status") or "").casefold()
                try:
                    checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
                    if checked.tzinfo is None:
                        checked = checked.replace(tzinfo=timezone.utc)
                    fresh = 0 <= (datetime.now(timezone.utc) - checked).total_seconds() < _tmdb_ott_ttl(existing)
                except (TypeError, ValueError):
                    fresh = False
                if fresh and status not in {"unknown", "error", "pending"}:
                    return

            title = str(row.get("catalogueTitle") or row.get("mediaTitle") or row.get("title") or "").strip()
            if not title:
                return
            try:
                year = int(row.get("year") or _extra_item_year(row))
            except (TypeError, ValueError):
                year = 0
            tmdb_id = int(row.get("tmdbId") or 0) if str(row.get("tmdbId") or "").isdigit() else 0
            async with semaphore:
                try:
                    # If the catalogue row already has a TMDB ID, consult the shared
                    # cache before resolving metadata. The previous order performed a
                    # network metadata lookup for every Favourites row on every cold
                    # start, even when OTT availability was already cached.
                    availability = None
                    resolved_id = tmdb_id
                    if resolved_id > 0:
                        cache_key = (resolved_id, "IN")
                        memory = _tmdb_ott_cache.get(cache_key)
                        if memory and isinstance(memory[1], dict):
                            age = max(0.0, time.monotonic() - memory[0])
                            if age < _tmdb_ott_ttl(memory[1]):
                                availability = memory[1]
                        if availability is None:
                            persistent = _read_tmdb_ott_persistent_cache(cache_key)
                            if persistent and isinstance(persistent[1], dict):
                                age = max(0.0, time.time() - persistent[0])
                                if age < _tmdb_ott_ttl(persistent[1]):
                                    availability = persistent[1]
                                    _tmdb_ott_cache[cache_key] = (time.monotonic() - age, availability)
                        if isinstance(availability, dict) and str(availability.get("status") or "").casefold() not in {"unknown", "error", "pending"}:
                            row["ottAvailability"] = availability
                            row["ottEnrichedAt"] = datetime.now(timezone.utc).isoformat()
                            changed = True
                            return

                    # In cache-only mode, a missing OTT entry must not fan out into
                    # Watchmode/TMDB title-search calls just to obtain an ID for a backfill.
                    if CACHE_ONLY_MODE:
                        _record_cache_event("classics_ott_enrichment", "cache_only_miss_skipped")
                        return

                    # Only resolve metadata when there is no usable cached OTT entry.
                    metadata = await asyncio.wait_for(_lookup_catalogue_synopsis(title, year, tmdb_id), timeout=15)
                    resolved_id = int((metadata or {}).get("tmdbId") or (metadata or {}).get("id") or tmdb_id)
                    if resolved_id <= 0:
                        return
                    cache_key = (resolved_id, "IN")
                    if availability is None:
                        memory = _tmdb_ott_cache.get(cache_key)
                        if memory and isinstance(memory[1], dict):
                            age = max(0.0, time.monotonic() - memory[0])
                            if age < _tmdb_ott_ttl(memory[1]):
                                availability = memory[1]
                    if availability is None:
                        persistent = _read_tmdb_ott_persistent_cache(cache_key)
                        if persistent and isinstance(persistent[1], dict):
                            age = max(0.0, time.time() - persistent[0])
                            if age < _tmdb_ott_ttl(persistent[1]):
                                availability = persistent[1]
                                _tmdb_ott_cache[cache_key] = (time.monotonic() - age, availability)
                    if availability is None:
                        availability = await asyncio.wait_for(_tmdb_fetch_movie_ott_availability(resolved_id, "IN"), timeout=18)
                        if isinstance(availability, dict):
                            _write_tmdb_ott_persistent_cache(cache_key, availability)
                            _tmdb_ott_cache[cache_key] = (time.monotonic(), availability)
                    if not isinstance(availability, dict) or str(availability.get("status") or "").casefold() in {"unknown", "error", "pending"}:
                        return
                    row["tmdbId"] = resolved_id
                    row["ottAvailability"] = availability
                    _tmdb_ott_cache[(resolved_id, "IN")] = (time.monotonic(), availability)
                    _write_tmdb_ott_persistent_cache((resolved_id, "IN"), availability)
                    row["ottEnrichedAt"] = datetime.now(timezone.utc).isoformat()
                    if metadata:
                        for field in ("tmdbUrl", "releaseDate", "rating", "posterUrl", "backdropUrl", "overview", "genres"):
                            if not row.get(field) and metadata.get(field):
                                row[field] = metadata[field]
                    changed = True
                except Exception as exc:
                    logger.info("Favourites OTT enrichment failed for %s: %s", title, type(exc).__name__)

        await asyncio.gather(*(enrich(row) for row in rows if isinstance(row, dict)))
        if changed:
            payload["results"] = rows
            payload["ottEnrichedAt"] = datetime.now(timezone.utc).isoformat()
            _write_extra_catalogue(key, payload)
            logger.info("Enriched Favourites movie cache with India OTT data")
    except Exception:
        logger.exception("Favourites movie OTT cache enrichment failed")


def _schedule_classics_movie_ott_enrichment() -> None:
    global _classics_ott_enrichment_task
    if CACHE_ONLY_MODE:
        return
    if _classics_ott_enrichment_task is None or _classics_ott_enrichment_task.done():
        _classics_ott_enrichment_task = asyncio.create_task(_enrich_classics_movie_ott_cache())


async def _warm_extra_catalogues_on_startup() -> None:
    # Catalogue builds are deliberately lazy. The old startup warm-up launched
    # all stale/missing catalogues together and flooded every upstream provider.
    asyncio.create_task(_extra_catalogue_monthly_scheduler())


app.router.add_event_handler("startup", _warm_extra_catalogues_on_startup)


def _regional_movie_cache_refresh_delay() -> float:
    oldest_saved_at = time.time()
    for catalogue_key in REGIONAL_MOVIE_CATALOGUE_KEYS:
        for page in range(1, REGIONAL_MOVIE_PREWARM_PAGES + 1):
            cached = _read_tmdb_persistent_cache((catalogue_key + "|eligible-v6", page))
            if not cached or not _regional_movie_cache_page_is_usable(cached[1], page):
                return 0
            oldest_saved_at = min(oldest_saved_at, cached[0])

    archive = _read_regional_movie_trending_archive()
    if not archive.get("builtAt"):
        return 0
    try:
        archive_built_at = datetime.fromisoformat(
            str(archive["builtAt"]).replace("Z", "+00:00")
        ).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0
    oldest_saved_at = min(oldest_saved_at, archive_built_at)
    return max(0.0, REGIONAL_MOVIE_CACHE_TTL_SECONDS - (time.time() - oldest_saved_at))


async def _warm_regional_movie_catalogue_pages() -> bool:
    if CACHE_ONLY_MODE:
        logger.info("Regional movie catalogue warm-up skipped: cache-only mode is enabled.")
        return True

    refresh_succeeded = True
    refreshed_source_keys: set[tuple[str, int]] = set()
    for catalogue_key in REGIONAL_MOVIE_CATALOGUE_KEYS:
        is_trending = catalogue_key.startswith("trending-")
        catalogue_refresh_succeeded = True
        trending_rows: list[dict[str, Any]] = []
        for page in range(1, REGIONAL_MOVIE_PREWARM_PAGES + 1):
            refresh_token = _REGIONAL_MOVIE_CATALOGUE_FORCE_REFRESH.set(True)
            source_token = _REGIONAL_MOVIE_SOURCE_FORCE_REFRESH.set(True)
            refreshed_token = _REGIONAL_MOVIE_SOURCE_REFRESHED_KEYS.set(refreshed_source_keys)
            try:
                payload = await api_tmdb_movie_catalogue(
                    catalogue_key,
                    page=page,
                    released_only=True,
                    max_size_gb=5,
                    basic=False,
                )
            except Exception:
                refresh_succeeded = False
                catalogue_refresh_succeeded = False
                logger.exception(
                    "Weekly regional movie cache refresh failed for %s page %s",
                    catalogue_key, page,
                )
                continue
            finally:
                _REGIONAL_MOVIE_SOURCE_REFRESHED_KEYS.reset(refreshed_token)
                _REGIONAL_MOVIE_SOURCE_FORCE_REFRESH.reset(source_token)
                _REGIONAL_MOVIE_CATALOGUE_FORCE_REFRESH.reset(refresh_token)

            result_count = len(payload.get("results") or [])
            if payload.get("cacheWarning"):
                refresh_succeeded = False
                catalogue_refresh_succeeded = False
                logger.warning(
                    "Regional movie cache kept stale data for %s page %s: %s",
                    catalogue_key, page, payload["cacheWarning"],
                )
            elif result_count != REGIONAL_MOVIE_CACHE_PAGE_SIZE:
                logger.warning(
                    "Regional movie cache %s page %s has %s titles; TMDB may have fewer eligible titles.",
                    catalogue_key, page, result_count, REGIONAL_MOVIE_CACHE_PAGE_SIZE,
                )
            else:
                logger.info(
                    "Regional movie cache ready: %s page %s (%s titles).",
                    catalogue_key, page, result_count,
                )
            if is_trending:
                trending_rows.extend(
                    row for row in (payload.get("results") or []) if isinstance(row, dict)
                )

        if is_trending:
            week_of = _regional_movie_week_start()
            if trending_rows and catalogue_refresh_succeeded:
                if _save_regional_movie_trending_week(week_of, catalogue_key, trending_rows):
                    logger.info(
                        "Saved %s unique weekly trend candidates for %s (%s).",
                        len(trending_rows), catalogue_key, week_of,
                    )
                else:
                    refresh_succeeded = False
            elif not trending_rows:
                refresh_succeeded = False
                logger.warning(
                    "No weekly trending candidates were returned for %s; preserving earlier snapshots.",
                    catalogue_key,
                )
    return refresh_succeeded


async def _regional_movie_catalogue_weekly_scheduler() -> None:
    while True:
        delay = _regional_movie_cache_refresh_delay()
        if delay > 0:
            logger.info(
                "Regional movie caches are current; next weekly refresh in %s seconds.",
                int(delay),
            )
            await asyncio.sleep(delay)

        refresh_succeeded = await _warm_regional_movie_catalogue_pages()
        delay = REGIONAL_MOVIE_CACHE_TTL_SECONDS if refresh_succeeded else 6 * 60 * 60
        logger.info(
            "Next regional movie catalogue refresh in %s seconds.",
            int(delay),
        )
        await asyncio.sleep(delay)


async def _start_regional_movie_catalogue_scheduler() -> None:
    asyncio.create_task(_regional_movie_catalogue_weekly_scheduler())


app.router.add_event_handler("startup", _start_regional_movie_catalogue_scheduler)


@app.get("/api/catalogue/ott/search")
async def api_search_saved_ott(titles: list[str] = Query(..., min_length=1, max_length=80)):
    """Look up saved OTT enrichment by title from persistent franchise catalogue caches only."""
    _record_cache_event("saved_ott_title_search", "lookup")
    # Read the persistent OTT JSON once for the entire title search. The cache
    # file may contain over a thousand rows; parsing the complete file once per
    # catalogue row turns a cache-only lookup into unnecessary repeated I/O.
    try:
        ott_disk = json.loads(TMDB_OTT_CACHE_FILE.read_text(encoding="utf-8"))
        ott_items = ott_disk.get("items", {}) if isinstance(ott_disk, dict) else {}
        if not isinstance(ott_items, dict):
            ott_items = {}
    except (OSError, ValueError, TypeError):
        ott_items = {}

    source_paths = [MARVEL_CATALOGUE_PATH, *_EXTRA_CATALOGUE_PATHS.values()]
    saved_rows: list[dict[str, Any]] = []
    seen_rows: set[tuple[str, str]] = set()
    for source_path in source_paths:
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            title = str(row.get("catalogueTitle") or row.get("marvelCatalogueTitle") or row.get("mediaTitle") or row.get("title") or "").strip()
            if not title:
                continue
            year = str(row.get("year") or "")
            identity = (_normalize_title(re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", title)), year)
            if identity in seen_rows:
                continue
            availability = row.get("ottAvailability")
            tmdb_id = row.get("tmdbId")
            try:
                tmdb_id = int(tmdb_id or 0)
            except (TypeError, ValueError):
                tmdb_id = 0
            # Catalogue rows are not the only source of saved OTT data. The shared
            # runtime cache is bundled into the image and may already contain a
            # result for this TMDB ID even when the catalogue row predates enrichment.
            if not isinstance(availability, dict) and tmdb_id > 0:
                cached = _tmdb_ott_cache.get((tmdb_id, "IN"))
                if cached and isinstance(cached[1], dict):
                    availability = cached[1]
                if not isinstance(availability, dict):
                    envelope = ott_items.get(_tmdb_ott_disk_key((tmdb_id, "IN")))
                    persistent_payload = envelope.get("payload") if isinstance(envelope, dict) else None
                    if isinstance(persistent_payload, dict):
                        availability = persistent_payload
                        _tmdb_ott_cache[(tmdb_id, "IN")] = (time.monotonic(), availability)
            if not isinstance(availability, dict):
                continue
            seen_rows.add(identity)
            saved_rows.append({
                "title": title,
                "year": year or None,
                "tmdbId": tmdb_id or row.get("tmdbId"),
                "ottAvailability": availability,
            })

    # Also use title-to-TMDB-ID mappings in the general saved metadata/catalogue
    # cache. This makes OTT entries reusable even when their title is not in a
    # Marvel/DC/Classics catalogue snapshot.
    for row in _read_search_metadata_catalogue_rows():
        if not isinstance(row, dict):
            continue
        raw_title = str(
            row.get("catalogueTitle") or row.get("marvelCatalogueTitle")
            or row.get("mediaTitle") or row.get("title") or row.get("name") or ""
        ).strip()
        if not raw_title:
            continue
        try:
            tmdb_id = int(row.get("tmdbId") or row.get("id") or 0)
        except (TypeError, ValueError):
            tmdb_id = 0
        if tmdb_id <= 0:
            continue
        availability = row.get("ottAvailability")
        if not isinstance(availability, dict):
            envelope = ott_items.get(_tmdb_ott_disk_key((tmdb_id, "IN")))
            availability = envelope.get("payload") if isinstance(envelope, dict) else None
        if not isinstance(availability, dict):
            continue
        year_value = row.get("year")
        title_identity = (
            _normalize_title(re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", raw_title)),
            str(year_value or ""),
        )
        if title_identity in seen_rows:
            continue
        seen_rows.add(title_identity)
        saved_rows.append({
            "title": raw_title,
            "year": str(year_value or "") or None,
            "tmdbId": tmdb_id,
            "ottAvailability": availability,
        })

    requested = []
    for raw in titles:
        title = re.sub(r"\s+", " ", str(raw or "")).strip()
        if title:
            requested.append({"title": title, "normalized": _normalize_title(re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", title))})

    matches = []
    for request in requested:
        candidates = [row for row in saved_rows
            if _normalize_title(re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", row["title"])) == request["normalized"]]
        if candidates:
            matches.append({"query": request["title"], "found": True, "entries": candidates[:3]})
        else:
            matches.append({"query": request["title"], "found": False, "entries": []})
    matched_count = sum(1 for item in matches if item.get("found"))
    _record_cache_event("saved_ott_title_search", "title_hit" if matched_count else "title_miss")
    _record_cache_event("saved_ott_title_search", "matched_rows", sum(len(item.get("entries") or []) for item in matches))
    return {"status": "ready", "results": matches}


app.router.add_event_handler("startup", _warm_marvel_catalogue_on_startup)


_watchmode_search_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_WATCHMODE_SEARCH_CACHE_TTL = 6 * 60 * 60
_TVMAZE_SEARCH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _availability_normalize_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _availability_title_is_relevant(query: str, title: Any) -> bool:
    """Reject distant partial-title matches while allowing modest subtitle/region suffixes."""
    target = _availability_normalize_title(query)
    candidate = _availability_normalize_title(title)
    if not target or not candidate:
        return False
    if target == candidate:
        return True
    # Containment is useful for regional editions and subtitles, but not arbitrary
    # longer titles that happen to begin with the requested words.
    max_extra = max(4, int(len(target) * 0.5))
    if target in candidate:
        return len(candidate) - len(target) <= max_extra
    if candidate in target:
        return len(target) - len(candidate) <= max_extra
    return False


def _availability_canonical_type(value: Any) -> str:
    kind = str(value or "").casefold().replace("-", "_").replace(" ", "_")
    if any(token in kind for token in ("tv", "series", "show", "episode")):
        return "tv"
    if any(token in kind for token in ("movie", "film", "feature")):
        return "movie"
    return kind or "unknown"


async def _fallback_tvmaze_search(query: str, timeout: httpx.Timeout) -> list[dict[str, Any]]:
    """Metadata-only fallback used only when Watchmode and TMDB find no title."""
    cache_key = query.casefold()
    cached = _TVMAZE_SEARCH_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _WATCHMODE_SEARCH_CACHE_TTL:
        return cached[1]
    try:
        async with _InstrumentedAsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get("https://api.tvmaze.com/search/shows", params={"q": query})
        if response.status_code != 200:
            return []
        payload = response.json()
    except (httpx.HTTPError, ValueError, TypeError):
        return []
    target = _availability_normalize_title(query)
    matches = []
    for row in payload if isinstance(payload, list) else []:
        show = row.get("show") if isinstance(row, dict) else None
        if not isinstance(show, dict) or not show.get("id"):
            continue
        title = str(show.get("name") or "").strip()
        if not title:
            continue
        normalized = _availability_normalize_title(title)
        if not _availability_title_is_relevant(query, title):
            continue
        premiered = str(show.get("premiered") or "")
        network = show.get("network") or show.get("webChannel") or {}
        matches.append({
            "id": str(show["id"]), "title": title, "year": premiered[:4] or None,
            "type": "tv", "providers": [], "status": "not_confirmed", "source": "TVmaze",
            "tvmazeId": show["id"], "imdbId": (show.get("externals") or {}).get("imdb"),
            "overview": re.sub(r"<[^>]+>", " ", str(show.get("summary") or "")).strip(),
            "network": network.get("name") if isinstance(network, dict) else None,
            "url": show.get("url"),
        })
    matches.sort(key=lambda item: (
        _availability_normalize_title(item.get("title")) == target,
        bool(item.get("year")),
    ), reverse=True)
    matches = matches[:5]
    _TVMAZE_SEARCH_CACHE[cache_key] = (time.time(), matches)
    return matches


async def _fallback_omdb_search(query: str, timeout: httpx.Timeout) -> list[dict[str, Any]]:
    """OMDb metadata fallback; OMDb does not provide streaming availability."""
    keys = _split_env_keys(os.getenv("OMDB_API_KEYS", ""), os.getenv("OMDB_API_KEY", ""))
    if CACHE_ONLY_MODE or not keys:
        return []
    target = _availability_normalize_title(query)
    for key in keys:
        try:
            async with _InstrumentedAsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get("https://www.omdbapi.com/", params={"apikey": key, "s": query})
            if response.status_code != 200:
                continue
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            continue
        matches = []
        for row in payload.get("Search") or []:
            title = str(row.get("Title") or "").strip()
            imdb_id = str(row.get("imdbID") or "").strip()
            if not title or not imdb_id:
                continue
            normalized = _availability_normalize_title(title)
            if not _availability_title_is_relevant(query, title):
                continue
            kind = "tv" if str(row.get("Type") or "").casefold() == "series" else "movie"
            matches.append({
                "id": imdb_id, "title": title, "year": row.get("Year"), "type": kind,
                "providers": [], "status": "not_confirmed", "source": "OMDb",
                "imdbId": imdb_id, "poster": row.get("Poster"),
            })
        if matches:
            matches.sort(key=lambda item: _availability_normalize_title(item["title"]) == target, reverse=True)
            return matches[:5]
        # Search returned no titles; try the next configured key only on auth errors
        # is intentionally avoided here so rate limits cannot be bypassed.
        if payload.get("Response") == "False":
            return []
    return []


@app.get("/api/search/availability")
async def api_search_availability(q: str = Query(..., min_length=2, max_length=160)):
    """Bound streaming lookups so slow provider APIs cannot leave the UI scanning forever."""
    query = re.sub(r"\s+", " ", q).strip()
    try:
        # Upstream providers have their own timeouts and retries; apply one total
        # budget to the whole lookup so nested retries cannot accumulate indefinitely.
        return await asyncio.wait_for(_api_search_availability_impl(query), timeout=12.0)
    except asyncio.TimeoutError:
        logger.info("Streaming availability lookup timed out for query %r", query)
        return {
            "status": "unavailable",
            "query": query,
            "title": query,
            "year": None,
            "matches": [],
            "providers": [],
            "message": "Streaming availability timed out. Torrent results are still available.",
        }


async def _api_search_availability_impl(q: str) -> dict[str, Any]:
    """Search Watchmode and TMDB first; use TVmaze/OMDb for metadata only if neither finds a title."""
    query = re.sub(r"\s+", " ", q).strip()
    cache_key = query.casefold()
    now = time.time()
    cached = _watchmode_search_cache.get(cache_key)
    if cached and now - cached[0] < _WATCHMODE_SEARCH_CACHE_TTL:
        _record_cache_event("availability_search", "hit")
        return cached[1]

    _record_cache_event("availability_search", "miss")
    if CACHE_ONLY_MODE:
        # This endpoint previously searched Watchmode/TMDB directly, bypassing the
        # movie-ID OTT cache-only guard. Reuse saved, title-matched OTT enrichment.
        try:
            saved_payload = await api_search_saved_ott(titles=[query])
        except Exception:
            saved_payload = {"results": []}
        saved_results = saved_payload.get("results") if isinstance(saved_payload, dict) else []
        saved_match = next((
            item for item in saved_results
            if isinstance(item, dict) and _availability_normalize_title(item.get("query")) == _availability_normalize_title(query)
        ), {})
        saved_entries = saved_match.get("entries") if isinstance(saved_match, dict) else []
        matches: list[dict[str, Any]] = []
        merged_providers: list[dict[str, Any]] = []
        seen_providers: set[tuple[str, str]] = set()
        for entry in saved_entries if isinstance(saved_entries, list) else []:
            if not isinstance(entry, dict):
                continue
            availability = entry.get("ottAvailability")
            if not isinstance(availability, dict):
                continue
            providers: list[dict[str, Any]] = []
            for source_field, kind in (
                ("streamingProviders", "subscription"),
                ("rentProviders", "rent"),
                ("buyProviders", "buy"),
            ):
                for provider in availability.get(source_field) or []:
                    if not isinstance(provider, dict):
                        continue
                    name = str(provider.get("name") or "").strip()
                    if not name:
                        continue
                    normalized_provider = {
                        "providerId": provider.get("providerId"),
                        "name": name,
                        "region": str(availability.get("region") or "IN").upper(),
                        "type": kind,
                        "webUrl": str(provider.get("webUrl") or availability.get("providerLink") or ""),
                        "logoUrl": str(provider.get("logoUrl") or ""),
                    }
                    providers.append(normalized_provider)
                    identity = (name.casefold(), kind)
                    if identity not in seen_providers:
                        seen_providers.add(identity)
                        merged_providers.append(normalized_provider)
            matches.append({
                "id": str(entry.get("tmdbId") or ""),
                "tmdbId": entry.get("tmdbId"),
                "title": str(entry.get("title") or query),
                "year": entry.get("year"),
                "type": "movie",
                "providers": providers[:24],
                "status": "ready" if providers else "not_confirmed",
                "source": str(availability.get("source") or "Saved OTT cache"),
            })
        result = {
            "status": "ready" if merged_providers else ("not_confirmed" if matches else "not_cached"),
            "query": query,
            "title": matches[0].get("title", query) if matches else query,
            "year": matches[0].get("year") if matches else None,
            "matches": matches[:10],
            "providers": merged_providers[:24],
            "source": "Saved OTT cache",
            "cacheOnly": True,
            "message": "" if matches else "No saved OTT entry matched this title; live provider lookups are disabled on this service.",
        }
        _watchmode_search_cache[cache_key] = (time.time(), result)
        _record_cache_event("availability_search", "cache_only_saved_hit" if matches else "cache_only_miss_blocked")
        return result

    timeout = httpx.Timeout(8.0, connect=3.0)
    target = _availability_normalize_title(query)
    primary_matches: list[dict[str, Any]] = []
    primary_errors = []

    # Primary source 1: Watchmode. Search both films and TV series automatically.
    if WATCHMODE_API_KEYS:
        try:
            response = await _watchmode_get("/search/", params={
                "search_field": "name", "search_value": query, "types": "movie,tv_series,tv_miniseries,tv_movie"
            }, timeout=timeout)
            if response is not None and response.status_code < 400:
                data = response.json()
                titles = data.get("title_results", []) if isinstance(data, dict) else []
                titles = [item for item in titles if isinstance(item, dict) and item.get("id")
                    and _availability_title_is_relevant(query, item.get("name"))]
                titles.sort(key=lambda item: (
                    _availability_normalize_title(item.get("name")) == target,
                    bool(item.get("year")),
                ), reverse=True)
                selected, seen_ids = [], set()
                for item in titles:
                    wid = str(item.get("id") or "")
                    if not wid or wid in seen_ids:
                        continue
                    kind = str(item.get("type") or "").casefold()
                    if kind and not any(token in kind for token in ("movie", "film", "feature", "tv", "show", "series")):
                        continue
                    seen_ids.add(wid)
                    selected.append(item)
                    if len(selected) >= 6:
                        break

                async def resolve_watchmode(item: dict[str, Any]) -> dict[str, Any]:
                    wid = str(item.get("id") or "")
                    kind = str(item.get("type") or "").lower()
                    try:
                        resp = await _watchmode_get(
                            f"/title/{quote(wid, safe='')}/sources/",
                            params={"regions": "IN"}, timeout=timeout)
                        raw = resp.json() if resp is not None and resp.status_code < 400 else []
                    except (httpx.HTTPError, ValueError, TypeError):
                        raw = []
                    providers, seen_sources = [], set()
                    for source in raw if isinstance(raw, list) else []:
                        if not isinstance(source, dict):
                            continue
                        name = str(source.get("name") or source.get("source_name") or "").strip()
                        if not name:
                            continue
                        region = str(source.get("region") or "IN").upper()
                        provider_type = str(source.get("type") or "").lower()
                        identity = (name.casefold(), region, provider_type)
                        if identity in seen_sources:
                            continue
                        seen_sources.add(identity)
                        logo_url = str(
                            source.get("logo_url") or source.get("logoUrl") or source.get("logo")
                            or source.get("image_url") or source.get("image") or ""
                        ).strip()
                        logo_path = str(source.get("logo_path") or "").strip()
                        if not logo_url and logo_path:
                            logo_url = (
                                "https://image.tmdb.org/t/p/w92" + logo_path
                                if logo_path.startswith("/") else logo_path
                            )
                        providers.append({
                            "providerId": source.get("source_id", source.get("id")),
                            "name": name,
                            "region": region,
                            "type": provider_type,
                            "webUrl": source.get("web_url") or source.get("ios_url") or source.get("android_url") or "",
                            "logoUrl": logo_url,
                        })
                    return {"id": wid, "title": str(item.get("name") or query), "year": item.get("year"),
                        "type": kind or "unknown", "tmdbId": item.get("tmdb_id"), "providers": providers[:24],
                        "status": "ready" if providers else "not_confirmed", "source": "Watchmode"}

                primary_matches.extend(await asyncio.gather(*(resolve_watchmode(item) for item in selected)))
            else:
                primary_errors.append("Watchmode unavailable")
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            primary_errors.append("Watchmode " + type(exc).__name__)

    # Primary source 2: search movies and TV concurrently. A movie miss or a
    # movie with no providers must not delay or suppress the TV-series lookup.
    if TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS:
        media_specs = (
            ("movie", "search/movie", "title", "release_date"),
            ("tv", "search/tv", "name", "first_air_date"),
        )

        async def search_tmdb_media(spec: tuple[str, str, str, str]) -> tuple[str, str, str, list[dict[str, Any]]]:
            media_type, search_path, title_key, date_key = spec
            try:
                payload = await _tmdb_get_json(search_path, {
                    "query": query, "include_adult": "false", "language": "en-US", "page": 1
                })
            except Exception as exc:
                primary_errors.append("TMDB " + type(exc).__name__)
                return media_type, title_key, date_key, []
            rows = []
            for row in payload.get("results") or []:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                title = str(row.get(title_key) or "").strip()
                if not title or not _availability_title_is_relevant(query, title):
                    continue
                rows.append(row)
            rows.sort(key=lambda row: (
                _availability_normalize_title(row.get(title_key)) == target,
                bool(row.get(date_key)),
                float(row.get("popularity") or 0),
            ), reverse=True)
            return media_type, title_key, date_key, rows[:3]

        searched_media = await asyncio.gather(*(search_tmdb_media(spec) for spec in media_specs))

        async def resolve_tmdb_match(
            media_type: str, title_key: str, date_key: str, row: dict[str, Any]
        ) -> dict[str, Any]:
            tmdb_id = int(row["id"])
            try:
                provider_data = await _tmdb_get_json(f"{media_type}/{tmdb_id}/watch/providers", {})
            except Exception as exc:
                primary_errors.append("TMDB providers " + type(exc).__name__)
                provider_data = {}
            region_data = (provider_data.get("results") or {}).get("IN") or {}
            providers = []
            for category, kind in (("flatrate", "subscription"), ("free", "free"),
                                   ("ads", "ads"), ("rent", "rent"), ("buy", "buy")):
                for provider in region_data.get(category) or []:
                    name = str(provider.get("provider_name") or "").strip()
                    if name:
                        logo_path = str(provider.get("logo_path") or "").strip()
                        providers.append({
                            "providerId": provider.get("provider_id"),
                            "name": name,
                            "region": "IN",
                            "type": kind,
                            "webUrl": region_data.get("link") or "",
                            "logoUrl": "https://image.tmdb.org/t/p/w92" + logo_path if logo_path else "",
                        })
            return {
                "id": str(tmdb_id), "title": str(row.get(title_key) or query),
                "year": str(row.get(date_key) or "")[:4] or None,
                "type": media_type, "tmdbId": tmdb_id, "providers": providers[:24],
                "status": "ready" if providers else "not_confirmed", "source": "TMDB",
            }

        # Resolve providers concurrently too. This makes the fallback quick when
        # the exact movie has no listing: the TV-series provider result can win
        # without waiting for every unrelated movie candidate.
        tmdb_candidates = [
            (media_type, title_key, date_key, row)
            for media_type, title_key, date_key, rows in searched_media
            for row in rows
        ]
        if tmdb_candidates:
            primary_matches.extend(await asyncio.gather(*(
                resolve_tmdb_match(media_type, title_key, date_key, row)
                for media_type, title_key, date_key, row in tmdb_candidates
            )))

    # De-duplicate same title/media/ID across sources; merge their provider entries.
    deduped: list[dict[str, Any]] = []
    index_by_identity: dict[tuple[str, str], int] = {}
    for match in primary_matches:
        identity = (_availability_canonical_type(match.get("type")),
                    _availability_normalize_title(match.get("title")))
        if identity in index_by_identity:
            existing = deduped[index_by_identity[identity]]
            existing_providers = existing.get("providers") or []
            provider_indexes = {
                (str(provider.get("name") or "").casefold(), str(provider.get("type") or "").casefold()): provider
                for provider in existing_providers
            }
            for provider in match.get("providers") or []:
                key = (str(provider.get("name") or "").casefold(), str(provider.get("type") or "").casefold())
                previous_provider = provider_indexes.get(key)
                if previous_provider is None:
                    existing_providers.append(provider)
                    provider_indexes[key] = provider
                    continue
                for field in ("webUrl", "providerId"):
                    if not previous_provider.get(field) and provider.get(field):
                        previous_provider[field] = provider[field]
            existing["providers"] = existing_providers
            if match.get("source") not in str(existing.get("source") or ""):
                existing["source"] = str(existing.get("source") or "") + " + " + str(match.get("source") or "")
            existing["status"] = "ready" if existing.get("providers") else "not_confirmed"
        else:
            index_by_identity[identity] = len(deduped)
            deduped.append(match)

    # Only use TVmaze/OMDb when both primary catalogues returned no title match.
    if not deduped:
        fallback_matches = await _fallback_tvmaze_search(query, timeout)
        if not fallback_matches:
            fallback_matches = await _fallback_omdb_search(query, timeout)
        if fallback_matches:
            result = {"status": "not_confirmed", "query": query, "title": fallback_matches[0]["title"],
                "year": fallback_matches[0].get("year"), "matches": fallback_matches, "providers": [],
                "source": fallback_matches[0].get("source"),
                "message": "Metadata match found, but no streaming provider could be confirmed by Watchmode or TMDB."}
        else:
            result = {"status": "not_found" if not primary_errors else "unavailable", "query": query,
                "title": query, "year": None, "matches": [], "providers": [],
                "message": "No title match found in Watchmode, TMDB, TVmaze, or OMDb."}
        _watchmode_search_cache[cache_key] = (time.time(), result)
        return result

    deduped.sort(key=lambda item: (
        _availability_normalize_title(item.get("title")) == target,
        bool(item.get("providers")),
        bool(item.get("year")),
    ), reverse=True)

    merged_providers, merged_provider_index = [], {}
    for match in deduped:
        for provider in match.get("providers") or []:
            identity = (str(provider.get("name") or "").casefold(),
                        str(provider.get("region") or "IN").upper(),
                        str(provider.get("type") or "").casefold())
            existing_provider = merged_provider_index.get(identity)
            if existing_provider is None:
                merged_provider_index[identity] = provider
                merged_providers.append(provider)
                continue
            for field in ("webUrl", "providerId"):
                if not existing_provider.get(field) and provider.get(field):
                    existing_provider[field] = provider[field]
    result = {
        "status": "ready" if merged_providers else "not_confirmed",
        "query": query, "title": deduped[0].get("title") or query, "year": deduped[0].get("year"),
        "matches": deduped[:10], "providers": merged_providers[:24],
        "source": "Watchmode + TMDB",
    }
    _watchmode_search_cache[cache_key] = (time.time(), result)
    return result



# Small, independent TMDB lookup for the quick search cards. This intentionally
# does not wait for torrent metadata or Watchmode source resolution.
_TMDB_SEARCH_METADATA_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TMDB_SEARCH_METADATA_CACHE_TTL = 1800.0


@app.get("/api/search/metadata")
async def api_search_metadata(q: str = Query(..., min_length=2, max_length=160)):
    """Return poster, synopsis, release year and TMDB link for fast search cards."""
    query = re.sub(r"\s+", " ", q).strip()
    cache_key = query.casefold()
    now = time.time()
    cached = _TMDB_SEARCH_METADATA_CACHE.get(cache_key)
    if cached and now - cached[0] < _TMDB_SEARCH_METADATA_CACHE_TTL:
        _record_cache_event("search_metadata", "memory_hit")
        return cached[1]
    _record_cache_event("search_metadata", "miss")

    # Disk-backed query envelopes survive process/container restarts. The per-title
    # cache below remains durable indefinitely and is refreshed whenever a new
    # successful lookup supplies better data.
    persistent_cache = _read_persistent_search_metadata_cache()
    query_entry = (persistent_cache.get("queries") or {}).get(cache_key)
    try:
        query_saved_at = int((query_entry or {}).get("savedAt") or 0)
    except (TypeError, ValueError):
        query_saved_at = 0
    if (
        isinstance(query_entry, dict)
        and now - query_saved_at < TMDB_SEARCH_METADATA_QUERY_TTL_SECONDS
    ):
        # Read newer reference-only envelopes; continue to support any legacy
        # envelope from a previous deployment.
        cached_response = query_entry.get("response")
        if isinstance(cached_response, dict) and cached_response.get("status") == "ready":
            _record_cache_event("search_metadata", "persistent_query_hit")
            _TMDB_SEARCH_METADATA_CACHE[cache_key] = (now, cached_response)
            return cached_response
        key_rows = query_entry.get("keys", [])
        requested_keys = {
            (
                str(key.get("title") or ""),
                int(key.get("year") or 0),
                str(key.get("mediaType") or "movie"),
                str(key.get("tmdbId") or ""),
            )
            for key in key_rows if isinstance(key, dict)
        } if isinstance(key_rows, list) else set()
        cached_results: list[dict[str, Any]] = []
        for raw in persistent_cache.get("results", []):
            if not isinstance(raw, dict):
                continue
            candidate = _search_metadata_cache_candidate(raw)
            if not candidate:
                continue
            row_key = (
                _normalize_title(candidate["title"]),
                int(candidate.get("year") or 0),
                str(candidate.get("mediaType") or "movie"),
                str(candidate.get("tmdbId") or ""),
            )
            if row_key in requested_keys:
                cached_results.append(candidate)
        if cached_results:
            _record_cache_event("search_metadata", "persistent_title_hit")
            _record_cache_event("search_metadata", "persistent_rows_served", len(cached_results))
            cached_response = {
                "status": "ready",
                "query": query,
                "source": "Persistent synopsis cache",
                "results": cached_results[:30],
            }
            _TMDB_SEARCH_METADATA_CACHE[cache_key] = (now, cached_response)
            return cached_response

    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        return {"status": "unavailable", "query": query, "source": "TMDB", "results": []}

    try:
        # Give the helper time to try each configured token on key-specific
        # failures. Use a shorter per-token timeout for this non-blocking UI lookup.
        payload = await asyncio.wait_for(
            _tmdb_get_json("search/multi", {
                "query": query,
                "include_adult": "false",
                "language": "en-US",
                "page": 1,
            }, request_timeout=3.5),
            timeout=14.0,
        )
    except Exception as exc:
        logger.info("TMDB quick metadata search failed for %r: %s", query, type(exc).__name__)
        return {"status": "unavailable", "query": query, "source": "TMDB", "results": []}

    results: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("media_type") or "").lower()
        if media_type not in {"movie", "tv"} or not item.get("id"):
            continue
        title = str((item.get("title") if media_type == "movie" else item.get("name")) or "").strip()
        # TMDB has already ranked these results for the submitted query. Do not
        # apply the stricter Watchmode availability matcher here: franchise titles
        # such as "The Amazing Spider-Man 2" are valid hits for "Spider-Man".
        if not title:
            continue
        release_date = str(
            (item.get("release_date") if media_type == "movie" else item.get("first_air_date")) or ""
        ).strip()
        year_match = re.match(r"^(\d{4})", release_date)
        poster_path = str(item.get("poster_path") or "").strip()
        backdrop_path = str(item.get("backdrop_path") or "").strip()
        tmdb_id = int(item["id"])
        results.append({
            "id": tmdb_id,
            "tmdbId": tmdb_id,
            "title": title,
            "year": int(year_match.group(1)) if year_match else None,
            "mediaType": media_type,
            "overview": str(item.get("overview") or "").strip(),
            "posterUrl": TMDB_IMAGE_BASE + poster_path if poster_path else "",
            "backdropUrl": "https://image.tmdb.org/t/p/w780" + backdrop_path if backdrop_path else "",
            "rating": float(item.get("vote_average") or 0),
            "tmdbUrl": f"https://www.themoviedb.org/{media_type}/{tmdb_id}",
            "source": "TMDB",
        })

    target = _availability_normalize_title(query)
    results.sort(key=lambda item: (
        _availability_normalize_title(item["title"]) == target,
        bool(item.get("year")),
        float(item.get("rating") or 0),
    ), reverse=True)
    response = {
        "status": "ready" if results else "not_found",
        "query": query,
        "source": "TMDB",
        "results": results[:30],
    }
    if response["status"] == "ready":
        _persist_search_metadata_cache_rows(results[:30], query=query, query_response=response)
        if len(_TMDB_SEARCH_METADATA_CACHE) > 300:
            expired_keys = [
                key for key, value in _TMDB_SEARCH_METADATA_CACHE.items()
                if now - value[0] >= _TMDB_SEARCH_METADATA_CACHE_TTL
            ]
            for key in expired_keys:
                _TMDB_SEARCH_METADATA_CACHE.pop(key, None)
            if len(_TMDB_SEARCH_METADATA_CACHE) > 300:
                _TMDB_SEARCH_METADATA_CACHE.pop(next(iter(_TMDB_SEARCH_METADATA_CACHE)), None)
        _TMDB_SEARCH_METADATA_CACHE[cache_key] = (now, response)
    return response


def _search_metadata_cache_candidate(raw: dict[str, Any]) -> dict[str, Any] | None:
    title = str(
        raw.get("catalogueTitle") or raw.get("marvelCatalogueTitle")
        or raw.get("mediaTitle") or raw.get("title") or raw.get("name") or ""
    ).strip()
    if not title:
        return None

    year_value = raw.get("year")
    release_date = str(raw.get("releaseDate") or raw.get("release_date") or raw.get("first_air_date") or "")
    try:
        year = int(year_value) if year_value else 0
    except (TypeError, ValueError):
        year = 0
    if not year and re.match(r"^\d{4}", release_date):
        year = int(release_date[:4])
    if not year:
        year_match = re.search(r"\b((?:19|20)\d{2})\b\s*\)?\s*$", title)
        if year_match:
            year = int(year_match.group(1))

    canonical_title = re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", title).strip()
    normalized = _normalize_title(canonical_title)
    if not normalized:
        return None

    media_type = str(raw.get("mediaType") or raw.get("media_type") or "movie").lower()
    if media_type not in {"movie", "tv"}:
        media_type = "movie"
    tmdb_id = raw.get("tmdbId") or raw.get("id")
    try:
        numeric_id = int(tmdb_id) if tmdb_id else 0
    except (TypeError, ValueError):
        numeric_id = 0
    overview = re.sub(r"\s+", " ", str(raw.get("overview") or "")).strip()
    # Keep rows with a known TMDB ID even when overview is empty. The batch
    # endpoint can hydrate those rows from TMDB's movie-details endpoint.

    def _number(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    poster_url = str(raw.get("posterUrl") or raw.get("poster_url") or "")
    if not poster_url and str(raw.get("poster_path") or "").strip():
        poster_url = TMDB_IMAGE_BASE + str(raw["poster_path"]).strip()
    backdrop_url = str(raw.get("backdropUrl") or raw.get("backdrop_url") or "")
    if not backdrop_url and str(raw.get("backdrop_path") or "").strip():
        backdrop_url = "https://image.tmdb.org/t/p/w780" + str(raw["backdrop_path"]).strip()
    tmdb_url = str(raw.get("tmdbUrl") or raw.get("tmdb_url") or "")
    if not tmdb_url and numeric_id:
        tmdb_url = f"https://www.themoviedb.org/{media_type}/{numeric_id}"

    return {
        "id": numeric_id or ("cached:" + normalized + (":" + str(year) if year else "")),
        "tmdbId": numeric_id or None,
        "title": canonical_title,
        "year": year or None,
        "mediaType": media_type,
        "overview": overview,
        "posterUrl": poster_url,
        "backdropUrl": backdrop_url,
        "rating": _number(raw.get("rating") or raw.get("vote_average")),
        "tmdbUrl": tmdb_url,
        "source": str(raw.get("source") or "VPS catalogue cache"),
        "synopsisCheckedAt": raw.get("synopsisCheckedAt"),
        "synopsisLookupVersion": raw.get("synopsisLookupVersion"),
    }


def _read_persistent_search_metadata_cache() -> dict[str, Any]:
    try:
        payload = json.loads(TMDB_SEARCH_METADATA_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload.setdefault("results", [])
            payload.setdefault("queries", {})
            return payload
    except (OSError, ValueError, TypeError):
        pass
    return {"version": 1, "results": [], "queries": {}}


def _write_persistent_search_metadata_cache(payload: dict[str, Any]) -> None:
    # The same atomic/fsync writer used by the catalogue snapshots keeps this
    # cache safe across container restarts and interrupted writes.
    _write_synopsis_cache(TMDB_SEARCH_METADATA_CACHE_FILE, payload)


def _persist_search_metadata_cache_rows(
    raw_rows: list[dict[str, Any]],
    *,
    query: str | None = None,
    query_response: dict[str, Any] | None = None,
) -> int:
    """Persist per-title metadata permanently without duplicating synopsis text in query envelopes."""
    disk = _read_persistent_search_metadata_cache()
    rows = disk.get("results", [])
    if not isinstance(rows, list):
        rows = []
    index: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        candidate = _search_metadata_cache_candidate(raw)
        if not candidate:
            continue
        key = (
            _normalize_title(candidate["title"]),
            int(candidate.get("year") or 0),
            str(candidate.get("mediaType") or "movie"),
            str(candidate.get("tmdbId") or ""),
        )
        index[key] = {**raw, **candidate}

    now = int(time.time())
    added = 0
    query_keys: list[dict[str, Any]] = []
    seen_query_keys: set[tuple[str, int, str, str]] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        candidate = _search_metadata_cache_candidate(raw)
        if not candidate:
            continue
        key = (
            _normalize_title(candidate["title"]),
            int(candidate.get("year") or 0),
            str(candidate.get("mediaType") or "movie"),
            str(candidate.get("tmdbId") or ""),
        )
        previous = index.get(key, {})
        # Do not replace a previously stored synopsis or useful artwork with blanks.
        merged = {**previous, **candidate}
        for field in ("overview", "posterUrl", "backdropUrl", "tmdbUrl", "tmdbId", "year", "rating"):
            if candidate.get(field) in (None, "", 0):
                if previous.get(field) not in (None, "", 0):
                    merged[field] = previous[field]
        merged["cacheUpdatedAt"] = now
        if not previous or merged != previous:
            added += 1
        index[key] = merged
        if query and query_response and query_response.get("status") == "ready" and key not in seen_query_keys:
            seen_query_keys.add(key)
            query_keys.append({
                "title": key[0],
                "year": key[1],
                "mediaType": key[2],
                "tmdbId": key[3],
            })

    if query and query_response and query_response.get("status") == "ready":
        queries = disk.get("queries", {})
        if not isinstance(queries, dict):
            queries = {}
        queries[re.sub(r"\s+", " ", query).strip().casefold()] = {
            "savedAt": now,
            "keys": query_keys,
        }
        # Query envelopes only store references; actual synopsis text exists once
        # per title in results and is retained permanently.
        if len(queries) > 1000:
            queries = dict(sorted(
                queries.items(),
                key=lambda pair: int((pair[1] or {}).get("savedAt") or 0),
                reverse=True,
            )[:1000])
        disk["queries"] = queries

    max_rows = 8000
    merged_rows = list(index.values())
    merged_rows.sort(key=lambda item: int(item.get("cacheUpdatedAt") or 0), reverse=True)
    disk["version"] = 1
    disk["updatedAt"] = now
    disk["results"] = merged_rows[:max_rows]
    try:
        _write_persistent_search_metadata_cache(disk)
    except OSError as exc:
        logger.warning("Could not persist search-card synopsis cache: %s", exc)
    return added



def _persist_search_metadata_overview(tmdb_id: int, overview: str) -> int:
    """Persist a newly fetched overview into any matching runtime catalogue row."""
    overview = re.sub(r"\s+", " ", str(overview or "")).strip()
    if tmdb_id < 1 or not overview:
        return 0

    updated_rows = 0
    now = int(time.time())
    for _name, path in _synopsis_cache_paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            continue
        changed = False
        for row in rows:
            if not isinstance(row, dict) or str(row.get("overview") or "").strip():
                continue
            try:
                row_id = int(row.get("tmdbId") or row.get("id") or 0)
            except (TypeError, ValueError):
                row_id = 0
            if row_id != tmdb_id:
                continue
            row["overview"] = overview
            row["synopsisCheckedAt"] = now
            row["synopsisLookupVersion"] = TMDB_SYNOPSIS_LOOKUP_VERSION
            changed = True
            updated_rows += 1
        if changed:
            try:
                _write_synopsis_cache(path, payload)
                logger.info("Saved fetched TMDB synopsis for ID %s into %s", tmdb_id, path.name)
            except OSError as exc:
                logger.warning("Could not persist synopsis for TMDB ID %s in %s: %s", tmdb_id, path.name, exc)

    # Popular/Trending/Latest responses are stored in a separate persistent file.
    try:
        disk = json.loads(TMDB_CATALOGUE_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(disk, dict):
            disk = {}
    except (OSError, ValueError, TypeError):
        disk = {}
    catalogues = disk.get("catalogues", {})
    disk_changed = False
    if isinstance(catalogues, dict):
        for envelope in catalogues.values():
            payload = envelope.get("payload") if isinstance(envelope, dict) else None
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict) or str(row.get("overview") or "").strip():
                    continue
                try:
                    row_id = int(row.get("tmdbId") or row.get("id") or 0)
                except (TypeError, ValueError):
                    row_id = 0
                if row_id == tmdb_id:
                    row["overview"] = overview
                    row["synopsisCheckedAt"] = now
                    row["synopsisLookupVersion"] = TMDB_SYNOPSIS_LOOKUP_VERSION
                    updated_rows += 1
                    disk_changed = True

    if disk_changed:
        temporary: Path | None = None
        try:
            TMDB_CATALOGUE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                prefix=TMDB_CATALOGUE_CACHE_FILE.stem + "-synopsis-",
                suffix=".tmp", dir=str(TMDB_CATALOGUE_CACHE_FILE.parent), delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(disk, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, TMDB_CATALOGUE_CACHE_FILE)
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not persist dynamic catalogue synopsis for TMDB ID %s: %s", tmdb_id, exc)
        finally:
            if temporary is not None and temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    pass

    # Keep in-memory catalogue responses consistent with the disk cache.
    for cache_key, entry in list(_tmdb_movie_catalogue_cache.items()):
        payload = entry[1]
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or str(row.get("overview") or "").strip():
                continue
            try:
                row_id = int(row.get("tmdbId") or row.get("id") or 0)
            except (TypeError, ValueError):
                row_id = 0
            if row_id == tmdb_id:
                row["overview"] = overview
                row["synopsisCheckedAt"] = now
                row["synopsisLookupVersion"] = TMDB_SYNOPSIS_LOOKUP_VERSION
    return updated_rows


async def _lookup_search_metadata_by_tmdb_id(item: dict[str, Any]) -> dict[str, Any] | None:
    """Fetch a missing synopsis using the cached row's authoritative TMDB ID."""
    try:
        tmdb_id = int(item.get("tmdbId") or item.get("id") or 0)
    except (TypeError, ValueError):
        tmdb_id = 0
    if tmdb_id < 1:
        return None

    details: dict[str, Any] | None = None
    for language in ("en-US", "en"):
        try:
            details = await asyncio.wait_for(
                _tmdb_get_json(
                    f"movie/{tmdb_id}",
                    {"language": language},
                    request_timeout=3.0,
                ),
                timeout=4.5,
            )
        except Exception as exc:
            logger.info("On-demand synopsis lookup failed for TMDB ID %s (%s): %s",
                tmdb_id, language, type(exc).__name__)
            continue
        overview = re.sub(r"\s+", " ", str(details.get("overview") or "")).strip()
        if overview:
            return {
                "overview": overview,
                "tmdbId": tmdb_id,
                "tmdbUrl": f"https://www.themoviedb.org/movie/{tmdb_id}",
                "rating": float(details.get("vote_average") or item.get("rating") or 0),
                "posterUrl": (
                    TMDB_IMAGE_BASE + str(details.get("poster_path")).strip()
                    if str(details.get("poster_path") or "").strip()
                    else str(item.get("posterUrl") or "")
                ),
                "backdropUrl": (
                    "https://image.tmdb.org/t/p/w780" + str(details.get("backdrop_path")).strip()
                    if str(details.get("backdrop_path") or "").strip()
                    else str(item.get("backdropUrl") or "")
                ),
                "synopsisCheckedAt": int(time.time()),
                "synopsisLookupVersion": TMDB_SYNOPSIS_LOOKUP_VERSION,
            }
        # Only issue the alternate-language request if TMDB answered but had no overview.
    return None


def _read_search_metadata_catalogue_rows() -> list[dict[str, Any]]:
    """Read metadata from the persistent VPS JSON snapshots used by the catalogues."""
    candidates: list[dict[str, Any]] = []
    for _name, path in _synopsis_cache_paths():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        if isinstance(rows, list):
            candidates.extend(row for row in rows if isinstance(row, dict))

    # Query search results and successful synopses are kept separately so arbitrary
    # searches survive restarts even when they are not in a prebuilt catalogue.
    persistent_metadata = _read_persistent_search_metadata_cache()
    persistent_rows = persistent_metadata.get("results", [])
    if isinstance(persistent_rows, list):
        candidates.extend(row for row in persistent_rows if isinstance(row, dict))

    # Popular, Trending and Latest are stored separately from franchise snapshots.
    try:
        disk = json.loads(TMDB_CATALOGUE_CACHE_FILE.read_text(encoding="utf-8"))
        catalogues = disk.get("catalogues", {}) if isinstance(disk, dict) else {}
        for envelope in catalogues.values() if isinstance(catalogues, dict) else []:
            payload = envelope.get("payload") if isinstance(envelope, dict) else None
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            if isinstance(rows, list):
                candidates.extend(row for row in rows if isinstance(row, dict))
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return candidates


def _imdb_rating_cache_key(title: str, year: int = 0, media_type: str = "movie") -> str:
    resolved_type = "tv" if str(media_type or "movie").casefold() in {"tv", "series"} else "movie"
    return f"{resolved_type}|{_normalize_synopsis_match_title(title)}|{int(year or 0)}"


def _parse_imdb_rating_title(value: str) -> tuple[str, int]:
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    match = re.search(r"\s*\(?((?:18|19|20|21)\d{2})\)?\s*$", raw)
    year = int(match.group(1)) if match else 0
    title = raw[:match.start()].strip() if match else raw
    if not title or not 1870 <= year <= 2100:
        return raw, 0
    return title, year


def _load_imdb_rating_cache() -> dict[str, dict[str, Any]]:
    global _IMDB_RATING_CACHE
    if _IMDB_RATING_CACHE is not None:
        return _IMDB_RATING_CACHE
    cache: dict[str, dict[str, Any]] = {}
    try:
        payload = json.loads(IMDB_RATING_CACHE_FILE.read_text(encoding="utf-8"))
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or "").strip()
                try:
                    year = int(row.get("year") or 0)
                except (TypeError, ValueError):
                    year = 0
                key = str(row.get("cacheKey") or (_imdb_rating_cache_key(title, year) if title else ""))
                if key:
                    cache[key] = row
    except (OSError, ValueError, TypeError):
        pass
    _IMDB_RATING_CACHE = cache
    return cache


async def _save_imdb_rating_cache_record(record: dict[str, Any]) -> None:
    key = str(record.get("cacheKey") or "")
    if not key:
        return
    async with _IMDB_RATING_CACHE_LOCK:
        cache = _load_imdb_rating_cache()
        cache[key] = record
        payload = {
            "version": 1,
            "updatedAt": int(time.time()),
            "results": list(cache.values())[-10000:],
        }
        try:
            _write_synopsis_cache(IMDB_RATING_CACHE_FILE, payload)
        except OSError as exc:
            logger.warning("Could not persist IMDb rating cache: %s", exc)


async def _fetch_imdb_rating(
    title: str,
    year: int,
    cache_key: str,
    media_type: str = "movie",
    tmdb_id: int = 0,
) -> dict[str, Any]:
    keys = _split_env_keys(os.getenv("OMDB_API_KEYS", ""), os.getenv("OMDB_API_KEY", ""))
    now = int(time.time())
    normalized_type = "tv" if str(media_type or "movie").casefold() in {"tv", "series"} else "movie"
    omdb_type = "series" if normalized_type == "tv" else "movie"
    base = {
        "cacheKey": cache_key,
        "title": title,
        "year": year or None,
        "mediaType": normalized_type,
        "checkedAt": now,
        "lookupVersion": IMDB_RATING_LOOKUP_VERSION,
        "tmdbIdTried": tmdb_id or None,
    }
    if not keys:
        return {**base, "status": "unavailable", "reason": "OMDb API key is not configured"}
    if time.time() < _omdb_rate_limited_until():
        return {**base, "status": "rate_limited", "cacheable": False}

    provider = "omdb"
    start_index = _PROVIDER_KEY_CURSORS.get(provider, 0) % len(keys)
    ordered = keys[start_index:] + keys[:start_index]
    _PROVIDER_KEY_CURSORS[provider] = (start_index + 1) % len(keys)
    timeout = httpx.Timeout(5.0, connect=2.5)
    target = _normalize_synopsis_match_title(title)

    async def call_omdb(key: str, params: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        try:
            client = _omdb_client(timeout)
            async with _OMDB_REQUEST_SEMAPHORE:
                response = await client.get(
                    "https://www.omdbapi.com/",
                    params={"apikey": key, **params, "r": "json"},
                    timeout=timeout,
                )
        except httpx.HTTPError as exc:
            logger.info("OMDb rating lookup failed for %r (%s): %s", title, type(exc).__name__)
            return None, "transient"

        if response.status_code == 429:
            _provider_key_failure(provider, key, _retry_after_seconds(response), "HTTP 429")
            _omdb_rate_limit_for(1800)
            return None, "rate_limited"
        if response.status_code in {401, 403}:
            _provider_key_failure(provider, key, 3600, f"HTTP {response.status_code}")
            return None, "invalid_key"
        if response.status_code >= 500:
            return None, "transient"
        if response.status_code >= 400:
            return None, "unavailable"
        try:
            payload = response.json()
        except (ValueError, TypeError):
            return None, "unavailable"

        if str(payload.get("Response") or "").casefold() == "false":
            error = str(payload.get("Error") or "")
            lowered_error = error.casefold()
            if "request limit reached" in lowered_error:
                # Do not try another key to bypass the account's daily quota.
                _omdb_rate_limit_for(3600)
                return None, "rate_limited"
            if "invalid api key" in lowered_error:
                _provider_key_failure(provider, key, 3600, "invalid API key")
                return None, "invalid_key"
        return payload, "ok"

    async def lookup_by_tmdb_imdb_id(key: str) -> dict[str, Any] | None:
        """Use TMDB's IMDb ID as an authoritative fallback when title search misses."""
        if tmdb_id < 1:
            return None
        try:
            if normalized_type == "tv":
                tmdb_details = await _tmdb_get_json(
                    f"tv/{tmdb_id}/external_ids", {}, request_timeout=3.0,
                )
            else:
                tmdb_details = await _tmdb_get_json(
                    f"movie/{tmdb_id}",
                    {"language": "en-US"},
                    request_timeout=3.0,
                )
        except Exception as exc:
            logger.info("TMDB IMDb-ID fallback failed for %s (%s): %s",
                tmdb_id, type(exc).__name__, title)
            return None

        imdb_id = str(tmdb_details.get("imdb_id") or "").strip()
        if not re.fullmatch(r"tt\d+", imdb_id):
            return None
        details, state = await call_omdb(key, {"i": imdb_id})
        if state == "rate_limited":
            return {**base, "status": "rate_limited", "reason": "OMDb rate limit reached", "cacheable": False}
        if state != "ok" or not details or str(details.get("Response") or "").casefold() == "false":
            return None

        returned_id = str(details.get("imdbID") or "").strip()
        returned_year_match = re.search(r"\b((?:18|19|20|21)\d{2})\b", str(details.get("Year") or ""))
        returned_year = int(returned_year_match.group(1)) if returned_year_match else 0
        # The TMDB-to-IMDb ID relationship is authoritative. IMDb/OMDb may
        # classify a special differently or use a different premiere year.
        if returned_id != imdb_id:
            return None

        raw_rating = str(details.get("imdbRating") or "").strip()
        try:
            imdb_rating = float(raw_rating) if raw_rating.casefold() != "n/a" else None
        except (TypeError, ValueError):
            imdb_rating = None
        return {
            **base,
            "title": title,
            "year": year or returned_year or None,
            "status": "found",
            "imdbRating": imdb_rating,
            "imdbVotes": str(details.get("imdbVotes") or "").strip() or None,
            "imdbId": imdb_id,
            "imdbUrl": f"https://www.imdb.com/title/{imdb_id}/",
            "ratingLookupSource": "tmdb_imdb_id",
        }

    for key in ordered:
        if not _provider_key_available(provider, key):
            continue

        params: dict[str, Any] = {"t": title, "type": omdb_type}
        if 1870 <= year <= 2100:
            params["y"] = year
        payload, state = await call_omdb(key, params)
        if state == "rate_limited":
            return {**base, "status": "rate_limited", "reason": "OMDb rate limit reached", "cacheable": False}
        if state in {"transient", "invalid_key"}:
            continue
        if state != "ok" or payload is None:
            return {**base, "status": "unavailable", "reason": "OMDb request failed", "cacheable": False}

        if str(payload.get("Response") or "").casefold() == "false":
            error = str(payload.get("Error") or "")
            lowered_error = error.casefold()
            if "movie not found" in lowered_error or "series not found" in lowered_error or "not found" in lowered_error:
                # Title lookups can miss a valid entry; use OMDb search and then
                # fetch details by IMDb ID, but only accept an exact title/year.
                search_params: dict[str, Any] = {"s": title, "type": omdb_type}
                if 1870 <= year <= 2100:
                    search_params["y"] = year
                search_payload, search_state = await call_omdb(key, search_params)
                if search_state == "rate_limited":
                    return {**base, "status": "rate_limited", "reason": "OMDb rate limit reached", "cacheable": False}
                if search_state in {"transient", "invalid_key"}:
                    continue
                if search_state != "ok" or not search_payload:
                    return {**base, "status": "unavailable", "reason": "OMDb search failed", "cacheable": False}
                candidates: list[tuple[int, dict[str, Any]]] = []
                for row in search_payload.get("Search") or []:
                    if not isinstance(row, dict):
                        continue
                    candidate_title = str(row.get("Title") or "").strip()
                    candidate_id = str(row.get("imdbID") or "").strip()
                    if not candidate_title or not re.fullmatch(r"tt\d+", candidate_id):
                        continue
                    if _normalize_synopsis_match_title(candidate_title) != target:
                        continue
                    year_match = re.search(r"\b((?:18|19|20|21)\d{2})\b", str(row.get("Year") or ""))
                    candidate_year = int(year_match.group(1)) if year_match else 0
                    if year and candidate_year and candidate_year != year:
                        continue
                    if year and not candidate_year:
                        continue
                    candidates.append((0 if year and candidate_year == year else 1, row))
                if not candidates:
                    direct_match = await lookup_by_tmdb_imdb_id(key)
                    if direct_match:
                        return direct_match
                    return {**base, "status": "not_found", "reason": "OMDb returned no exact title/year match"}
                candidates.sort(key=lambda item: item[0])
                selected_id = str(candidates[0][1].get("imdbID") or "").strip()
                payload, details_state = await call_omdb(key, {"i": selected_id, "type": omdb_type})
                if details_state == "rate_limited":
                    return {**base, "status": "rate_limited", "reason": "OMDb rate limit reached", "cacheable": False}
                if details_state in {"transient", "invalid_key"}:
                    continue
                if details_state != "ok" or payload is None or str(payload.get("Response") or "").casefold() == "false":
                    return {**base, "status": "unavailable", "reason": "OMDb title details lookup failed", "cacheable": False}
            else:
                return {**base, "status": "not_found", "reason": error or "OMDb returned no match"}

        returned_title = str(payload.get("Title") or "").strip()
        returned_year_match = re.search(r"\b((?:18|19|20|21)\d{2})\b", str(payload.get("Year") or ""))
        returned_year = int(returned_year_match.group(1)) if returned_year_match else 0
        candidate = _normalize_synopsis_match_title(returned_title)
        returned_type = str(payload.get("Type") or "").casefold()
        wanted_type = "series" if normalized_type == "tv" else "movie"
        if (
            not returned_title
            or candidate != target
            or (year and returned_year != year)
            or (returned_type and returned_type != wanted_type)
        ):
            # Never display another title's score just because OMDb returned a nearby match.
            # TMDB's IMDb ID is safer than accepting a fuzzy title result.
            direct_match = await lookup_by_tmdb_imdb_id(key)
            if direct_match:
                return direct_match
            return {
                **base,
                "status": "not_found",
                "reason": "OMDb title/year/type did not exactly match the requested entry",
            }

        imdb_id = str(payload.get("imdbID") or "").strip()
        raw_rating = str(payload.get("imdbRating") or "").strip()
        try:
            imdb_rating = float(raw_rating) if raw_rating.casefold() != "n/a" else None
        except (TypeError, ValueError):
            imdb_rating = None
        record = {
            **base,
            "title": title,
            "year": year or returned_year or None,
            "status": "found",
            "imdbRating": imdb_rating,
            "imdbVotes": str(payload.get("imdbVotes") or "").strip() or None,
            "imdbId": imdb_id if re.fullmatch(r"tt\d+", imdb_id) else None,
            "imdbUrl": f"https://www.imdb.com/title/{imdb_id}/" if re.fullmatch(r"tt\d+", imdb_id) else None,
        }
        _provider_key_success(provider, key)
        return record

    return {**base, "status": "unavailable", "reason": "No usable OMDb key or transient upstream error", "cacheable": False}

async def _get_imdb_rating_record(
    title: str, year: int, media_type: str = "movie", tmdb_id: int = 0
) -> dict[str, Any]:
    normalized_type = "tv" if str(media_type or "movie").casefold() in {"tv", "series"} else "movie"
    cache_key = _imdb_rating_cache_key(title, year, normalized_type)
    cached = _load_imdb_rating_cache().get(cache_key)
    now = int(time.time())
    if CACHE_ONLY_MODE:
        # Never call OMDb/TMDB; serve whatever is stored, however old.
        _record_cache_event("imdb_rating", "hit" if cached else "miss")
        return cached or {
            "status": "unavailable", "title": title, "year": year or None,
            "mediaType": normalized_type, "cacheKey": cache_key,
            "reason": "Not in bundled cache",
        }
    # A miss recorded before a TMDB id was available deserves one retry with the id.
    if (
        cached
        and tmdb_id > 0
        and not cached.get("tmdbIdTried")
        and (cached.get("status") != "found" or cached.get("imdbRating") is None)
    ):
        cached = None
    if cached:
        try:
            checked_at = int(cached.get("checkedAt") or 0)
            lookup_version = int(cached.get("lookupVersion") or 0)
        except (TypeError, ValueError):
            checked_at = lookup_version = 0
        if (
            lookup_version >= (
                IMDB_RATING_LOOKUP_VERSION
                if cached.get("status") != "found" or cached.get("imdbRating") is None
                else 4
            )
            and checked_at
            and now - checked_at < (
                IMDB_RATING_NOT_FOUND_TTL_SECONDS
                if cached.get("status") != "found" or cached.get("imdbRating") is None
                else IMDB_RATING_CACHE_TTL_SECONDS
            )
        ):
            _record_cache_event("imdb_rating", "hit")
            return cached

    _record_cache_event("imdb_rating", "miss")
    task = _IMDB_RATING_INFLIGHT.get(cache_key)
    if task is None or task.done():
        async def fetch_and_save() -> dict[str, Any]:
            result = await _fetch_imdb_rating(title, year, cache_key, normalized_type, tmdb_id)
            if result.get("status") in {"found", "not_found"} and result.get("cacheable", True):
                result.pop("cacheable", None)
                await _save_imdb_rating_cache_record(result)
            return result

        task = asyncio.create_task(fetch_and_save())
        _IMDB_RATING_INFLIGHT[cache_key] = task
    try:
        return await task
    finally:
        if task.done() and _IMDB_RATING_INFLIGHT.get(cache_key) is task:
            _IMDB_RATING_INFLIGHT.pop(cache_key, None)

@app.get("/api/catalogue/imdb-ratings")
async def api_catalogue_imdb_ratings(
    titles: list[str] = Query(..., min_length=1, max_length=80),
    media_types: list[str] = Query(default=[]),
    tmdb_ids: list[int] = Query(default=[]),
):
    """Return cached IMDb ratings, using TMDB's IMDb ID to resolve ambiguous titles."""
    requested: dict[str, tuple[str, int, str, str, int]] = {}
    for index, raw in enumerate(titles[:80]):
        title, year = _parse_imdb_rating_title(raw)
        if not title:
            continue
        supplied_type = media_types[index] if index < len(media_types) else "movie"
        media_type = "tv" if str(supplied_type or "movie").casefold() in {"tv", "series"} else "movie"
        try:
            tmdb_id = max(0, int(tmdb_ids[index])) if index < len(tmdb_ids) else 0
        except (TypeError, ValueError):
            tmdb_id = 0
        key = _imdb_rating_cache_key(title, year, media_type)
        requested.setdefault(key, (title, year, media_type, raw, tmdb_id))
    if not requested:
        return {"status": "ready", "results": []}

    results = await asyncio.gather(
        *(
            _get_imdb_rating_record(title, year, media_type, tmdb_id)
            for title, year, media_type, _raw, tmdb_id in requested.values()
        ),
        return_exceptions=True,
    )
    output = []
    for (title, year, media_type, raw, _tmdb_id), result in zip(requested.values(), results):
        if isinstance(result, Exception):
            logger.info("IMDb rating lookup failed for %r (%s)", title, type(result).__name__)
            output.append({
                "query": raw, "title": title, "year": year or None,
                "mediaType": media_type, "status": "unavailable",
            })
            continue
        output.append({
            **result,
            "query": raw,
            # Preserve the requested title/year for reliable client-side card matching.
            "title": title,
            "year": year or result.get("year"),
            "mediaType": media_type,
        })
    statuses = {str(item.get("status") or "") for item in output}
    return {
        "status": "ready" if statuses <= {"found", "not_found"} else "partial",
        "requested": len(requested),
        "matched": sum(1 for item in output if item.get("status") == "found" and item.get("imdbRating") is not None),
        "results": output,
    }

@app.get("/api/search/metadata/batch")
async def api_search_metadata_batch(
    titles: list[str] = Query(..., min_length=2, max_length=180),
):
    """Resolve search-card metadata from persistent VPS catalogue JSON by exact title/year."""
    requested = list(dict.fromkeys(
        re.sub(r"\s+", " ", str(value or "")).strip()
        for value in titles[:80] if str(value or "").strip()
    ))
    if not requested:
        return {"status": "ready", "source": "VPS catalogue cache", "results": []}

    candidates = []
    seen_rows: set[tuple[str, int, str, str]] = set()
    for raw in _read_search_metadata_catalogue_rows():
        item = _search_metadata_cache_candidate(raw)
        if not item:
            continue
        identity = (
            _normalize_title(item["title"]),
            int(item.get("year") or 0),
            str(item.get("mediaType") or "movie"),
            str(item.get("tmdbId") or ""),
        )
        if identity not in seen_rows:
            seen_rows.add(identity)
            candidates.append(item)

    matched: list[dict[str, Any]] = []
    missing_synopsis_candidates: dict[int, dict[str, Any]] = {}
    seen_matches: set[tuple[str, int, str]] = set()
    for requested_title in requested:
        year_match = re.search(r"\s*\(?((?:19|20)\d{2})\)?\s*$", requested_title)
        requested_year = int(year_match.group(1)) if year_match else 0
        clean_title = re.sub(r"\s*\(?((?:19|20)\d{2})\)?\s*$", "", requested_title).strip()
        target = _normalize_title(clean_title)
        if not target:
            continue
        options = [item for item in candidates if _normalize_title(item["title"]) == target]
        same_year = [item for item in options if int(item.get("year") or 0) == requested_year] if requested_year else []
        unknown_year = [item for item in options if not int(item.get("year") or 0)]
        if same_year:
            selected = same_year
        elif unknown_year:
            selected = unknown_year if len(unknown_year) == 1 else []
        elif not requested_year and options:
            selected = options
        elif len(options) == 1:
            selected = options
        else:
            selected = []
        if not selected:
            continue
        selected.sort(key=lambda item: (
            bool(item.get("overview")),
            bool(item.get("tmdbId")),
            float(item.get("rating") or 0),
        ), reverse=True)
        best = selected[0]
        match_key = (
            _normalize_title(best["title"]),
            int(best.get("year") or 0),
            str(best.get("mediaType") or "movie"),
        )
        if match_key not in seen_matches:
            seen_matches.add(match_key)
            matched.append(best)
        if not str(best.get("overview") or "").strip():
            try:
                missing_id = int(best.get("tmdbId") or best.get("id") or 0)
            except (TypeError, ValueError):
                missing_id = 0
            if missing_id > 0:
                missing_synopsis_candidates.setdefault(missing_id, best)

    # The saved catalogues can know a movie's TMDB ID even when the discover/search
    # list originally supplied no overview. Hydrate a small batch of those misses by
    # ID, then write the successful synopsis back into the persistent JSON caches.
    # Bound concurrency/work so a large catalogue search does not turn into a slow scan.
    semaphore = asyncio.Semaphore(4)
    async def hydrate_missing(item_id: int, item: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
        async with semaphore:
            metadata = await _lookup_search_metadata_by_tmdb_id(item)
            return item_id, metadata

    selected_missing = list(missing_synopsis_candidates.items())[:12]
    if selected_missing:
        hydrated = await asyncio.gather(
            *(hydrate_missing(item_id, item) for item_id, item in selected_missing),
            return_exceptions=True,
        )
        for value in hydrated:
            if isinstance(value, Exception) or not isinstance(value, tuple):
                continue
            item_id, metadata = value
            if not metadata or not str(metadata.get("overview") or "").strip():
                continue
            for item in matched:
                try:
                    existing_id = int(item.get("tmdbId") or item.get("id") or 0)
                except (TypeError, ValueError):
                    existing_id = 0
                if existing_id != item_id:
                    continue
                item.update(metadata)
                item["source"] = "TMDB movie details"
            persisted_item = {**item, **metadata}
            _persist_search_metadata_cache_rows([persisted_item])
            saved_rows = _persist_search_metadata_overview(item_id, metadata["overview"])
            logger.info("Hydrated missing search-card synopsis for TMDB ID %s; persisted rows=%s",
                item_id, saved_rows)

    # Permanently save successful overview hits from any of the catalogue sources.
    matched = [item for item in matched if str(item.get("overview") or "").strip()]
    if matched:
        _persist_search_metadata_cache_rows(matched)

    # Never send blank synopsis entries if no details lookup could recover them;
    # this keeps the response list focused on usable saved metadata.
    return {
        "status": "ready",
        "source": "VPS catalogue cache",
        "requested": len(requested),
        "matched": len(matched),
        "results": matched,
    }


@app.get("/api/search")
async def api_search(request: Request, q: str = Query(..., min_length=1), limit: int = Query(50, ge=1, le=50)):
    prepare_intent = request.headers.get("x-prepare-intent", "missing")
    prepare_trace = request.headers.get("x-prepare-trace", "missing")
    if prepare_intent != "missing" or prepare_trace != "missing":
        logger.info(
            "PREPARE_TRACE event=live-search-request intent=%s trace=%s query=%r",
            prepare_intent, prepare_trace, q,
        )
    # Live torrent-provider access is explicitly scoped to this user-triggered endpoint.
    token = _MANUAL_TORRENT_SEARCH.set(True)
    try:
        return await search_1337x(q, limit)
    finally:
        _MANUAL_TORRENT_SEARCH.reset(token)

REGIONAL_MOVIE_PREBUILT_CACHE_PATH = Path(os.getenv("REGIONAL_MOVIE_PREBUILT_CACHE_PATH", "/app/data/regional_movie_prebuilt_cache.json"))


@app.get("/api/regional-movies/prebuilt")
async def api_regional_movie_prebuilt(
    request: Request,
    title: str = Query(..., min_length=1, max_length=200),
    year: str = Query("", max_length=4),
):
    """Serve precomputed regional catalogue and torrent details from persistent VPS JSON."""
    prepare_intent = request.headers.get("x-prepare-intent", "missing")
    prepare_trace = request.headers.get("x-prepare-trace", "missing")
    logger.info(
        "PREPARE_TRACE event=prebuilt-request intent=%s trace=%s title=%r year=%s referer=%r",
        prepare_intent, prepare_trace, title, year, request.headers.get("referer", ""),
    )

    def cache_title_key(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())

    try:
        payload = json.loads(REGIONAL_MOVIE_PREBUILT_CACHE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"status": "cache_missing", "movie": None, "torrentDetails": None}
    except Exception as exc:
        logger.warning("Could not read regional movie cache: %s", exc)
        return {"status": "cache_unavailable", "movie": None, "torrentDetails": None}
    movies = payload.get("movies") if isinstance(payload, dict) else {}
    key = cache_title_key(title) + "|" + str(year or "")
    entry = (movies or {}).get(key)
    if not entry and not year:
        matches = [value for item_key, value in (movies or {}).items()
                   if item_key.startswith(cache_title_key(title) + "|")]
        entry = matches[0] if len(matches) == 1 else None
    if not isinstance(entry, dict):
        _record_cache_event("regional_movie_prebuilt", "miss")
        logger.info(
            "PREPARE_TRACE event=prebuilt-result intent=%s trace=%s cache=miss title=%r year=%s",
            prepare_intent, prepare_trace, title, year,
        )
        return {"status": "not_cached", "movie": None, "torrentDetails": None,
                "builtAt": payload.get("builtAt")}
    _record_cache_event("regional_movie_prebuilt", "hit")
    cached_details = entry.get("torrentDetails")
    cached_rows = cached_details.get("results") if isinstance(cached_details, dict) else cached_details
    logger.info(
        "PREPARE_TRACE event=prebuilt-result intent=%s trace=%s cache=hit cached_variants=%s title=%r year=%s",
        prepare_intent, prepare_trace, len(cached_rows) if isinstance(cached_rows, list) else 0, title, year,
    )

    # Apply the current size window to saved torrent results at read time too.
    # This filters old snapshots without mutating the persistent cache file.
    torrent_details = entry.get("torrentDetails")
    if isinstance(torrent_details, dict):
        filtered_details = dict(torrent_details)
        cached_results = torrent_details.get("results")
        if isinstance(cached_results, list):
            kept_results = []
            for result in cached_results:
                if not isinstance(result, dict):
                    continue
                try:
                    size_bytes = int(result.get("size") or 0)
                except (TypeError, ValueError, OverflowError):
                    size_bytes = 0
                if MIN_SEARCH_RESULT_SIZE_BYTES <= size_bytes <= MAX_SEARCH_RESULT_SIZE_BYTES:
                    kept_results.append(result)
            filtered_details["results"] = kept_results
            filtered_details["filteredOutBySize"] = len(cached_results) - len(kept_results)
        torrent_details = filtered_details
    elif isinstance(torrent_details, list):
        kept_results = []
        for result in torrent_details:
            if not isinstance(result, dict):
                continue
            try:
                size_bytes = int(result.get("size") or 0)
            except (TypeError, ValueError, OverflowError):
                size_bytes = 0
            if MIN_SEARCH_RESULT_SIZE_BYTES <= size_bytes <= MAX_SEARCH_RESULT_SIZE_BYTES:
                kept_results.append(result)
        torrent_details = kept_results

    return {
        "status": "ready",
        "builtAt": payload.get("builtAt"),
        "movie": entry.get("movie"),
        "catalogues": entry.get("catalogues", []),
        "torrentDetails": torrent_details,
    }



def _cache_file_snapshot(name: str, path: Path, *, bundled: bool = False) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": name,
        "file": path.name,
        "exists": False,
        "bytes": 0,
        "modifiedAt": None,
        "entryCount": None,
        "entryGroups": {},
        "bundledSnapshot": bundled,
    }
    try:
        if not path.is_file():
            return row
        stat = path.stat()
        row["exists"] = True
        row["bytes"] = stat.st_size
        row["modifiedAt"] = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            groups: dict[str, int] = {}
            for key in ("items", "catalogues", "queries", "movies", "results", "ratings", "entries", "records", "pages", "shows"):
                value = payload.get(key)
                if isinstance(value, (dict, list)):
                    groups[key] = len(value)
            row["entryGroups"] = groups
            for key in ("items", "movies", "results", "entries", "records", "ratings", "catalogues", "pages", "shows"):
                if key in groups:
                    row["entryCount"] = groups[key]
                    break
            if row["entryCount"] is None:
                row["entryCount"] = len(payload)
        elif isinstance(payload, list):
            row["entryCount"] = len(payload)
        else:
            row["entryCount"] = 0
    except (OSError, ValueError, TypeError):
        row["parseError"] = True
    return row


@app.get("/api/cache/report")
async def api_cache_report():
    """Inventory saved cache data and report process-local cache/use counters."""
    if not DEBUG_ENDPOINTS_ENABLED:
        # Reveals server file paths and internal counters; hidden unless enabled.
        raise HTTPException(404, "Not found")
    runtime_paths: dict[str, Path] = {
        name: path for name, path in _RUNTIME_CACHE_SEED_FILES.items()
    }
    runtime_paths["marvel_catalogue.json"] = MARVEL_CATALOGUE_PATH
    runtime_paths["marvel_web_series_catalogue.json"] = Path(
        os.getenv("MARVEL_WEB_SERIES_CATALOGUE_PATH", "/app/data/marvel_web_series_catalogue.json")
    )
    runtime_paths["bollywood_torrent_matched_catalogue.json"] = Path(
        os.getenv("BOLLYWOOD_TORRENT_CATALOGUE_PATH", str(Path(os.getenv("APP_DATA_DIR", "/app/data")) / "bollywood_torrent_matched_catalogue.json"))
    )
    runtime_paths["torrent_metadata_cache"] = TORRENT_METADATA_CACHE_FILE
    runtime_paths["regional_tv_prebuilt_cache.json"] = REGIONAL_TV_PREBUILT_CACHE_FILE
    runtime_paths["regional_movie_prebuilt_cache.json"] = REGIONAL_MOVIE_PREBUILT_CACHE_PATH
    runtime_paths["classics_web_series_tv_catalogue.json"] = Path(os.getenv("APP_DATA_DIR", "/app/data")) / "classics_web_series_tv_catalogue.json"
    runtime_paths["classics_anime_tv_catalogue.json"] = Path(os.getenv("APP_DATA_DIR", "/app/data")) / "classics_anime_tv_catalogue.json"
    runtime_paths["nexstream_cache.json"] = Path(os.getenv("NEXSTREAM_CACHE_PATH", "/app/data/nexstream_cache.json"))
    runtime_paths["nexstream_episode_metadata_cache.json"] = Path(os.getenv("NEXSTREAM_EPISODE_CACHE_PATH", "/app/data/nexstream_episode_metadata_cache.json"))
    for key, path in _EXTRA_CATALOGUE_PATHS.items():
        runtime_paths["catalogue:" + key] = path
    runtime_files = [
        _cache_file_snapshot(name, path)
        for name, path in sorted(runtime_paths.items())
    ]

    bundled_paths: dict[str, Path] = {
        name: _CACHE_SEED_DIR / name for name in _CACHE_SEED_FILES
    }
    for name in (
        "tmdb_movie_catalogue_cache.json",
        "tmdb_search_metadata_cache.json",
        "imdb_rating_cache.json",
        "tmdb_ott_availability_cache.json",
        "marvel_tv_catalogue_cache.json",
        "dc_tv_catalogue_cache.json",
        "regional_movie_prebuilt_cache.json",
        "nexstream_cache.json",
        "nexstream_episode_metadata_cache.json",
    ):
        bundled_paths["runtime/" + name] = _CACHE_SEED_DIR / "runtime" / name
    bundled_files = [
        _cache_file_snapshot(name, path, bundled=True)
        for name, path in sorted(bundled_paths.items())
    ]

    memory_store_names = (
        "_tmdb_ott_cache", "_tmdb_movie_catalogue_cache", "_tmdb_company_id_cache",
        "_TMDB_SEARCH_METADATA_CACHE", "_IMDB_RATING_CACHE", "_search_cache",
        "_poster_cache", "_watchmode_search_cache", "_TVMAZE_SEARCH_CACHE",
        "_metadata_cache", "_seedr_folder_cache", "_REGIONAL_TV_PAGE_CACHE",
        "_REGIONAL_TV_DISCOVERY_CACHE", "_REGIONAL_TV_PREBUILT_CACHE",
        "_MARVEL_TV_CATALOGUE_CACHE", "_DC_TV_CATALOGUE_CACHE",
        "_CLASSICS_TV_CATALOGUE_CACHE", "_seedr_ffprobe_cache",
        "_seedr_media_info_cache", "_seedr_embedded_subtitle_cache",
    )
    memory_stores: dict[str, Any] = {}
    for name in memory_store_names:
        value = globals().get(name)
        if isinstance(value, (dict, list, tuple, set)):
            memory_stores[name.lstrip("_")] = len(value)
        elif value is None:
            memory_stores[name.lstrip("_")] = None

    cache_events = {
        store: dict(events)
        for store, events in sorted(_CACHE_DIAGNOSTICS["cache_events"].items())
    }
    explicit_cache_hits = sum(
        int(count)
        for events in cache_events.values()
        for event, count in events.items()
        if "hit" in event
    )
    explicit_cache_misses = sum(
        int(count)
        for events in cache_events.values()
        for event, count in events.items()
        if "miss" in event or "bypass" in event
    )
    blocked_live_lookups = sum(
        int(count)
        for events in cache_events.values()
        for event, count in events.items()
        if "blocked" in event
    )
    availability_live_lookup_events = sum(
        int(count)
        for events in cache_events.values()
        for event, count in events.items()
        if "live_provider_lookup" in event
    )
    cache_use_summary = {
        "explicitCacheHitEvents": explicit_cache_hits,
        "explicitCacheMissOrBypassEvents": explicit_cache_misses,
        "blockedLiveLookupEvents": blocked_live_lookups,
        "availabilityLiveLookupEvents": availability_live_lookup_events,
        "hitRatePercentAmongExplicitHitMissEvents": round(
            100 * explicit_cache_hits / (explicit_cache_hits + explicit_cache_misses), 2
        ) if explicit_cache_hits + explicit_cache_misses else None,
        "scope": "Only explicitly instrumented cache-decision points. Not a whole-app hit rate or catalogue-row percentage.",
    }
    upstream = {
        "requests": int(_CACHE_DIAGNOSTICS["upstream_requests"]),
        "failures": int(_CACHE_DIAGNOSTICS["upstream_failures"]),
        "byProvider": dict(sorted(_CACHE_DIAGNOSTICS["upstream_by_provider"].items())),
        "byEndpoint": dict(sorted(
            _CACHE_DIAGNOSTICS["upstream_by_endpoint"].items(),
            key=lambda pair: pair[1],
            reverse=True,
        )[:100]),
        "byFeature": dict(sorted(
            _CACHE_DIAGNOSTICS["upstream_by_feature"].items(),
            key=lambda pair: pair[1],
            reverse=True,
        )[:150]),
        "statusCodes": dict(sorted(_CACHE_DIAGNOSTICS["upstream_status_codes"].items())),
    }
    now = time.time()
    return {
        "status": "ok",
        "measurementStartedAt": datetime.fromtimestamp(_CACHE_DIAGNOSTICS_STARTED_AT, timezone.utc).isoformat(),
        "measurementScope": "This worker process only; counters reset on worker restart and are not aggregated across Render instances.",
        "ottCacheOnly": CACHE_ONLY_MODE,
        "uptimeSeconds": max(0, int(now - _CACHE_DIAGNOSTICS_STARTED_AT)),
        "cacheEvents": cache_events,
        "cacheUseSummary": cache_use_summary,
        "outboundHttp": upstream,
        "memoryCacheSizes": memory_stores,
        "runtimeCacheFiles": runtime_files,
        "bundledCacheSnapshots": bundled_files,
        "notes": [
            "File entry counts describe saved inventory; they are not cache-hit counts.",
            "Cache event counters measure only the explicitly instrumented cache decision points.",
            "Outbound HTTP counts cover backend requests issued through instrumented httpx clients, grouped by provider and endpoint without query strings or credentials.",
            "NexStream search and episode caches are measured by the shared diagnostics module; frontend localStorage hit counts and Vercel serverless cache hits are outside this backend report.",
            "A cache hit means that path returned or reused an entry; outbound request totals show actual httpx requests attempted by this worker.",
        ],
    }


@app.get("/api/health")
async def api_health():
    return {"name": APP_NAME, "status": "ok"}

@app.get("/api/seedr/session")
async def seedr_session(request: Request):
    """Initialize the browser session quickly; provider health checks happen on demand."""
    session_id = _seedr_request_session_id.get().strip()
    session = _seedr_get_session(session_id)
    # Session bootstrap must not wait on Seedr. The CSRF token is needed before
    # the browser can submit a PAT, and a slow provider must not cause POST 403s.
    # Actual token/API failures are reported by the operation the user requests.
    return {
        "connected": bool(current_seedr_token()),
        "csrfToken": str(session.get("csrf_token") or ""),
    }


async def _validate_seedr_pat(token: str) -> None:
    """Validate a Seedr PAT sequentially; avoid bursts of concurrent auth requests."""
    token = normalize_seedr_token(token)
    if not token:
        raise SeedrError("SEEDR_PAT_MISSING", 400, "A Seedr Personal Access Token is required.")

    endpoints = (
        f"{SEEDR_PAT_BASE}/user",
        f"{SEEDR_PAT_BASE}/tasks",
        f"{SEEDR_PAT_BASE}/fs/root/contents",
        f"{SEEDR_V2_BASE}/tasks",
        f"{SEEDR_V2_BASE}/fs/root/contents",
    )
    outcomes: list[str] = []
    saw_unauthorized = False
    timeout = httpx.Timeout(8.0, connect=3.0)

    # The endpoints have been verified to accept the current PAT when called
    # individually. Do not fan out concurrently: concurrent probes previously
    # all failed at the transport layer despite these same endpoints succeeding
    # when tested one at a time. Stop on the first 2xx response.
    async with _InstrumentedAsyncClient(timeout=timeout, follow_redirects=True) as client:
        for url in endpoints:
            try:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                logger.info(
                    "Seedr PAT validation transport error: endpoint=%s error=%s",
                    url,
                    type(exc).__name__,
                )
                outcomes.append(f"{url}=transport:{type(exc).__name__}")
                continue

            if 200 <= response.status_code < 300:
                logger.info(
                    "Seedr PAT validation succeeded: endpoint=%s status=%s",
                    url,
                    response.status_code,
                )
                return

            if response.status_code == 401:
                saw_unauthorized = True
                outcomes.append(f"{url}=401")
                continue

            if response.status_code in {403, 404, 405}:
                outcomes.append(f"{url}={response.status_code}")
                continue

            try:
                payload = response.json() if response.content else {}
                reason = str(
                    payload.get("error_description")
                    or payload.get("reason_phrase")
                    or payload.get("message")
                    or payload.get("error")
                    or ""
                ).strip() if isinstance(payload, dict) else ""
            except (ValueError, TypeError):
                reason = ""

            # Retry the next known API variant for transient/provider-specific
            # errors rather than concluding the token is invalid prematurely.
            outcomes.append(f"{url}=HTTP{response.status_code}")
            logger.info(
                "Seedr PAT validation endpoint returned HTTP %s: endpoint=%s reason=%s",
                response.status_code,
                url,
                reason[:160],
            )

    logger.warning(
        "Seedr PAT validation found no successful endpoint: %s",
        ", ".join(outcomes),
    )
    if saw_unauthorized and not any("transport:" in row for row in outcomes):
        raise SeedrError(
            "SEEDR_PAT_REJECTED",
            401,
            "Seedr rejected the Personal Access Token. Copy a fresh PAT from Seedr and try again.",
        )

    raise SeedrError(
        "SEEDR_PAT_VALIDATION_FAILED",
        502,
        "Could not validate the Seedr token using the account API. Please retry shortly.",
    )


@app.post("/api/seedr/connect/pat")
async def seedr_connect_pat(request: Request):
    session_id = _seedr_request_session_id.get().strip()
    session = _seedr_get_session(session_id)

    try:
        payload = await request.json()
    except Exception:
        payload = None

    if not isinstance(payload, dict):
        raise HTTPException(400, "Request body must be JSON.")

    raw_pat = payload.get("pat") or payload.get("token")
    if not isinstance(raw_pat, str):
        raise HTTPException(400, "A Seedr Personal Access Token is required.")

    pat = normalize_seedr_token(raw_pat)
    if not pat:
        raise HTTPException(400, "A Seedr Personal Access Token is required.")

    await _validate_seedr_pat(pat)

    session["access_token"] = pat
    session["refresh_token"] = ""
    session["token_type"] = "Bearer"
    session["auth_mode"] = "pat"
    session["device"] = None
    session["last_seen"] = time.time()

    logger.info(
        "Seedr PAT connected: session=%s token_length=%s",
        _seedr_session_fingerprint(session_id),
        len(pat),
    )
    return {"status": "connected", "connected": True}


@app.post("/api/seedr/connect/start")
async def seedr_connect_start(request: Request):
    session_id = _seedr_request_session_id.get().strip()
    session = _seedr_get_session(session_id)

    logger.info(
        "Seedr connect start: session=%s cookie_present=%s has_device=%s has_token=%s",
        _seedr_session_fingerprint(session_id),
        bool(request.cookies.get(SEEDR_SESSION_COOKIE)),
        bool(isinstance(session.get("device"), dict)),
        bool(_seedr_session_token(session_id)),
    )

    token = current_seedr_token()
    if token:
        return {"status": "connected", "connected": True}

    try:
        async with _InstrumentedAsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(
                SEEDR_DEVICE_CODE_URL,
                params={"client_id": SEEDR_DEVICE_CLIENT_ID},
                headers={"Accept": "application/json"},
            )
        raw = response.text
        try:
            data = response.json() if raw else {}
        except Exception:
            data = {}

        if response.status_code >= 400 or not isinstance(data, dict):
            detail = seedr_error_message(response.status_code, data, raw)
            raise SeedrError("SEEDR_DEVICE_CODE_FAILED", 502, detail)

        device_code = str(data.get("device_code") or data.get("deviceCode") or "").strip()
        user_code = str(data.get("user_code") or data.get("userCode") or "").strip()
        verification_url = str(
            data.get("verification_url")
            or data.get("verificationUrl")
            or "https://www.seedr.cc/devices"
        ).strip()
        expires_in = int(float(data.get("expires_in") or data.get("expiresIn") or 900))

        if not device_code or not user_code:
            raise SeedrError(
                "SEEDR_DEVICE_CODE_INVALID",
                502,
                "Seedr returned an incomplete device authorization response.",
            )

        session["device"] = {
            "device_code": device_code,
            "user_code": user_code,
            "verification_url": verification_url,
            "expires_at": time.time() + max(60, expires_in),
            "created_at": time.time(),
        }
        session["last_seen"] = time.time()

        poll_interval = int(float(data.get("interval") or 5))
        poll_interval = max(2, min(30, poll_interval))
        session["device"]["interval"] = poll_interval
        logger.info(
            "Seedr connect start stored device: session=%s expires_in=%s interval=%s",
            _seedr_session_fingerprint(session_id),
            expires_in,
            poll_interval,
        )
        return {
            "status": "pending",
            "connected": False,
            "userCode": user_code,
            "verificationUrl": verification_url,
            "expiresIn": expires_in,
            "interval": poll_interval,
        }
    except SeedrError:
        raise
    except Exception as exc:
        logger.warning("Seedr device-code request failed: %s", exc)
        raise SeedrError(
            "SEEDR_DEVICE_CODE_FAILED",
            502,
            "Could not start Seedr account authorization right now.",
        ) from exc


def _extract_seedr_access_token(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("access_token", "accessToken", "token"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate.strip():
                normalized = normalize_seedr_token(candidate)
                if normalized:
                    return normalized

        for key in ("data", "result", "response"):
            nested = payload.get(key)
            token = _extract_seedr_access_token(nested)
            if token:
                return token
    return ""


@app.get("/api/seedr/connect/status")
async def seedr_connect_status(request: Request):
    session_id = _seedr_request_session_id.get().strip()
    session = _seedr_get_session(session_id)
    token = _seedr_session_token(session_id)
    device = session.get("device")

    logger.info(
        "Seedr connect status: session=%s cookie_present=%s has_device=%s has_token=%s",
        _seedr_session_fingerprint(session_id),
        bool(request.cookies.get(SEEDR_SESSION_COOKIE)),
        bool(isinstance(device, dict)),
        bool(token),
    )

    if token:
        try:
            token_ctx = _seedr_request_token.set(token)
            try:
                await seedr_request("/user")
            finally:
                _seedr_request_token.reset(token_ctx)
            session["device"] = None
            return {"status": "connected", "connected": True}
        except SeedrError as exc:
            if exc.status_code == 401:
                _clear_seedr_session_token(session_id)
            else:
                return {"status": "pending", "connected": False}

    device = session.get("device")
    if not isinstance(device, dict):
        return {
            "status": "error",
            "connected": False,
            "code": "SEEDR_SESSION_LOST",
            "message": "The Seedr connection session was lost. Start the connection again.",
        }

    expires_at = float(device.get("expires_at") or 0)
    if expires_at and time.time() >= expires_at:
        session["device"] = None
        return {
            "status": "expired",
            "connected": False,
            "message": "The Seedr authorization code expired. Start a new connection.",
        }

    device_code = str(device.get("device_code") or "").strip()
    if not device_code:
        session["device"] = None
        return {
            "status": "error",
            "connected": False,
            "message": "Seedr did not provide a usable device code.",
        }

    try:
        async with _InstrumentedAsyncClient(timeout=10, follow_redirects=True) as client:
            # Seedr's device authorization endpoint expects the original
            # device_code. The current Seedr client implementations pass only
            # device_code here; do not add client_id to this request.
            response = await client.get(
                SEEDR_DEVICE_AUTHORIZE_URL,
                params={"device_code": device_code},
                headers={"Accept": "application/json"},
            )

        raw = response.text
        try:
            data = response.json() if raw else {}
        except Exception:
            data = {}

        access_token = _extract_seedr_access_token(data)
        logger.info(
            "Seedr device authorization poll: http=%s token_present=%s error=%s message=%s",
            response.status_code,
            bool(access_token),
            str(data.get("error") or data.get("code") or "")[:120] if isinstance(data, dict) else "",
            str(
                (data.get("error_description") or data.get("message") or data.get("error") or "")
                if isinstance(data, dict) else ""
            )[:200],
        )
        if access_token:
            refresh_token = ""
            token_type = "Bearer"
            if isinstance(data, dict):
                refresh_token = str(data.get("refresh_token") or data.get("refreshToken") or "").strip()
                token_type = str(data.get("token_type") or "Bearer").strip() or "Bearer"
                for key in ("data", "result", "response"):
                    nested = data.get(key)
                    if isinstance(nested, dict):
                        refresh_token = refresh_token or str(
                            nested.get("refresh_token") or nested.get("refreshToken") or ""
                        ).strip()
                        token_type = str(nested.get("token_type") or token_type).strip() or token_type

            session["access_token"] = access_token
            session["refresh_token"] = refresh_token
            session["token_type"] = token_type
            session["device"] = None
            session["last_seen"] = time.time()

            token_ctx = _seedr_request_token.set(access_token)
            try:
                await seedr_request("/user")
            except SeedrError:
                _clear_seedr_session_token(session_id)
                raise
            finally:
                _seedr_request_token.reset(token_ctx)

            return {"status": "connected", "connected": True}

        error_code = ""
        error_message = ""
        if isinstance(data, dict):
            error_code = str(data.get("error") or data.get("code") or "").strip().lower()
            error_message = str(
                data.get("error_description")
                or data.get("message")
                or data.get("error")
                or ""
            ).strip()

        pending = (
            response.status_code in {400, 409, 428}
            and (
                not error_code
                or "pending" in error_code
                or "authorize" in error_code
                or "not_authorized" in error_code
                or "not approved" in error_message.lower()
            )
        )
        if pending:
            return {
                "status": "pending",
                "connected": False,
                "expiresIn": max(0, int(expires_at - time.time())),
                "interval": max(2, min(30, int(float(device.get("interval") or 5)))),
            }

        if response.status_code >= 400:
            if response.status_code == 401:
                session["device"] = None
                return {
                    "status": "error",
                    "connected": False,
                    "message": "Seedr rejected this authorization request.",
                }
            return {
                "status": "error",
                "connected": False,
                "message": error_message or seedr_error_message(response.status_code, data, raw),
            }

        return {
            "status": "pending",
            "connected": False,
            "expiresIn": max(0, int(expires_at - time.time())),
        }
    except SeedrError:
        raise
    except Exception as exc:
        logger.info("Seedr device authorization poll failed: %s", exc)
        return {
            "status": "pending",
            "connected": False,
            "expiresIn": max(0, int(expires_at - time.time())),
        }


@app.post("/api/seedr/connect/disconnect")
async def seedr_connect_disconnect(request: Request):
    session_id = _seedr_request_session_id.get().strip()
    _clear_seedr_session_token(session_id)
    return {"status": "disconnected", "connected": False}


@app.get("/api/seedr/token-diagnostic")
async def seedr_token_diagnostic():
    if not current_seedr_token():
        return {
            "configured": False,
            "code": "SEEDR_TOKEN_MISSING",
            "tokenLength": 0,
            "tokenFingerprint": None,
            "checks": {},
        }

    token = normalize_seedr_token(current_seedr_token())
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12] if token else None

    async def check(path: str) -> dict[str, Any]:
        try:
            await seedr_request(path)
            return {"ok": True, "status": 200}
        except SeedrError as exc:
            return {"ok": False, "status": exc.status_code, "code": exc.code, "message": exc.detail}
        except Exception as exc:
            return {"ok": False, "status": 0, "code": "LOCAL_ERROR", "message": str(exc)[:200]}

    result: dict[str, Any] = {
        "configured": True,
        "code": "SEEDR_TOKEN_PRESENT",
        "checks": {
            "user": await check("/tasks" if _seedr_session_auth_mode(_seedr_request_session_id.get().strip()) == "pat" else "/user"),
        },
    }
    if DEBUG_ENDPOINTS_ENABLED:
        # Token metadata is only returned when debugging is explicitly enabled.
        result["tokenLength"] = len(token)
        result["tokenFingerprint"] = fingerprint
    return result


@app.get("/api/seedr/auth-status")
async def seedr_auth_status():
    if not current_seedr_token():
        return {
            "configured": False,
            "authenticated": False,
            "code": "SEEDR_TOKEN_MISSING",
            "message": "Seedr API token is not configured in Render.",
        }

    try:
        # The old working integration treats a successful /user call as the
        # authentication test. Do the same here; /user is explicitly documented
        # by Seedr for Bearer-authenticated requests.
        await seedr_request(
            "/tasks" if _seedr_session_auth_mode(_seedr_request_session_id.get().strip()) == "pat" else "/user"
        )
        return {
            "configured": True,
            "authenticated": True,
            "code": "SEEDR_AUTH_OK",
        }
    except SeedrError as exc:
        return {
            "configured": True,
            "authenticated": False,
            "code": exc.code,
            "message": exc.detail,
        }



@app.get("/api/seedr/quota")
async def seedr_quota():
    if not current_seedr_token():
        return {"configured": False, "maxSpace": 0, "usedSpace": 0, "remainingSpace": 0}

    try:
        is_pat = _seedr_session_auth_mode(_seedr_request_session_id.get().strip()) == "pat"
        result = seedr_data(await seedr_request("/fs/root/contents" if is_pat else "/user"))
        storage = result.get("account", {}).get("storage", {}) if isinstance(result, dict) else {}
        if not isinstance(storage, dict):
            storage = result.get("storage", {}) if isinstance(result, dict) else {}
        result_dict = result if isinstance(result, dict) else {}
        if is_pat:
            max_space = int(float(
                result_dict.get("space_max", 0)
                or result_dict.get("max_space", 0)
                or result_dict.get("maxSpace", 0)
                or storage.get("limit", 0)
            ))
            used = int(float(
                result_dict.get("space_used", 0)
                or result_dict.get("used_space", 0)
                or result_dict.get("usedSpace", 0)
                or storage.get("used", 0)
            ))
        else:
            max_space = int(float(
                storage.get("limit")
                or storage.get("max_space")
                or storage.get("maxSpace")
                or result_dict.get("max_space", 0)
                or result_dict.get("space_max", 0)
                or 0
            ))
            used = int(float(
                storage.get("used")
                or storage.get("used_space")
                or storage.get("usedSpace")
                or result_dict.get("used_space", 0)
                or result_dict.get("space_used", 0)
                or 0
            ))
    except SeedrError:
        raise
    except Exception as exc:
        logger.warning("Seedr quota parsing failed: %s", exc)
        raise SeedrError(
            "SEEDR_QUOTA_UNAVAILABLE",
            503,
            "Seedr account storage information is temporarily unavailable.",
        ) from exc

    if not (max_space > 0) or used < 0 or used > max_space:
        raise SeedrError(
            "SEEDR_QUOTA_UNAVAILABLE",
            503,
            "Seedr account storage information is temporarily unavailable.",
        )

    return {
        "configured": True,
        "maxSpace": max_space,
        "usedSpace": used,
        "remainingSpace": max(0, max_space - used),
    }

async def _prepare_seedr_space(
    required_bytes: int,
    *,
    force_one: bool = False,
) -> list[dict[str, Any]]:
    """Free old completed Seedr folders; optionally force at least one deletion after a quota rejection."""
    required = max(0, int(required_bytes or 0))
    if required <= 0:
        return []

    quota = await seedr_quota()
    remaining = int(quota.get("remainingSpace") or 0)
    if remaining >= required and not force_one:
        return []

    library = await get_seedr_metadata_tree(force_refresh=True)
    folders = [
        folder for folder in (library.get("folders") or [])
        if isinstance(folder, dict)
        and str(folder.get("folderId") or folder.get("id") or "").strip()
        and str(folder.get("folderId") or folder.get("id") or "").strip() != "0"
    ]

    # Prefer actual Seedr task timestamps so the oldest completed torrent is
    # removed first. Fall back to the library order when a provider response
    # does not expose a timestamp.
    task_meta: dict[str, dict[str, Any]] = {}
    active_folder_ids: set[str] = set()
    try:
        tasks_payload = seedr_data(await seedr_request("/tasks"))
        for raw_task in arr(tasks_payload, ("tasks", "torrents", "items")):
            task = unwrap_seedr_task(seedr_data(raw_task))
            if not task:
                continue
            folder_id = seedr_task_folder_id(task)
            if not folder_id:
                continue
            if not task_complete(task):
                active_folder_ids.add(str(folder_id))
            task_meta[str(folder_id)] = task
    except (HTTPException, SeedrError):
        pass

    def task_timestamp(task: dict[str, Any]) -> float:
        for key in (
            "created_at", "createdAt", "created", "added_at", "addedAt",
            "time_added", "timeAdded", "timestamp", "date_added", "dateAdded",
        ):
            value = task.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return float(value if value < 10_000_000_000 else value / 1000)
            if isinstance(value, str) and value.strip():
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return parsed.timestamp()
                except Exception:
                    continue
        return 0.0

    candidates: list[tuple[int, float, dict[str, Any]]] = []
    for index, folder in enumerate(folders):
        folder_id = str(folder.get("folderId") or folder.get("id") or "").strip()
        if not folder_id or folder_id in active_folder_ids:
            continue
        task = task_meta.get(folder_id, {})
        candidates.append((index, task_timestamp(task), folder))

    candidates.sort(key=lambda item: (item[1] if item[1] > 0 else float("inf"), item[0]))

    deleted: list[dict[str, Any]] = []
    for _, _, folder in candidates:
        if remaining >= required and (not force_one or deleted):
            break

        folder_id = str(folder.get("folderId") or folder.get("id") or "").strip()
        folder_name = str(folder.get("torrentName") or folder.get("name") or folder_id).strip()
        folder_size = max(0, int(float(folder.get("totalSize") or 0)))

        try:
            await seedr_request(f"/fs/folder/{quote(folder_id)}", "DELETE")
            deleted.append({
                "folderId": folder_id,
                "name": folder_name,
                "size": folder_size,
            })
            remaining += folder_size
            _seedr_folder_cache.pop(folder_id, None)
        except (HTTPException, SeedrError) as exc:
            logger.warning(
                "Seedr automatic cleanup skipped folder=%s status=%s detail=%s",
                folder_id,
                getattr(exc, "status_code", 0),
                getattr(exc, "detail", str(exc)),
            )

    global _seedr_metadata_cache
    _seedr_metadata_cache = None
    _seedr_folder_cache.clear()

    if remaining < required:
        raise SeedrError(
            "SEEDR_QUOTA_UNAVAILABLE",
            413,
            "Seedr does not have enough space for this torrent, even after removing older completed files.",
        )

    logger.info(
        "Seedr automatic cleanup freed=%s required=%s deleted=%s",
        sum(int(item.get("size") or 0) for item in deleted),
        required,
        len(deleted),
    )
    return deleted


@app.post("/api/seedr/add")
async def seedr_add(request: Request):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    # Direct Seedr mode:
    # validate without changing the input, then forward that exact string.
    try:
        payload = await request.json()
    except Exception:
        payload = None

    if not isinstance(payload, dict):
        raise HTTPException(400, "Request body must be JSON.")

    raw_magnet = payload.get("magnet")
    if not isinstance(raw_magnet, str) or not raw_magnet:
        raise HTTPException(400, "A magnet link is required.")

    if not info_hash(raw_magnet):
        raise HTTPException(400, "A valid BTIH magnet link is required")

    requested_folder = str(payload.get("folder_id") or "").strip()
    folder = int(requested_folder) if requested_folder.isdigit() else 0
    auto_cleanup = bool(payload.get("auto_cleanup"))
    required_bytes = max(0, int(float(payload.get("required_bytes") or 0)))

    session_id = _seedr_request_session_id.get().strip()
    logger.info(
        "Seedr add start: session=%s mode=%s magnet_length=%s magnet_info_hash=%s "
        "requested_folder=%s resolved_folder=%s",
        _seedr_session_fingerprint(session_id),
        _seedr_session_auth_mode(session_id),
        len(raw_magnet),
        info_hash(raw_magnet),
        requested_folder or "<none>",
        folder,
    )

    # Treat every new Seedr add as replacing the prior unfinished transfer.
    # Do not depend on frontend localStorage/current-notice state: an old task
    # may still exist after a page refresh or backend/container restart.
    replace_task_id = str(payload.get("replace_task_id") or "").strip()
    cancelled_tasks = await _cancel_active_seedr_tasks_for_replacement(replace_task_id)

    deleted_folders: list[dict[str, Any]] = [
        {
            "folderId": str(item.get("folderId") or ""),
            "name": str(item.get("name") or "Cancelled Seedr task"),
            "size": max(0, int(item.get("size") or 0)),
        }
        for item in cancelled_tasks
        if item.get("folderDeleted") and str(item.get("folderId") or "").strip()
    ]
    if auto_cleanup and required_bytes > 0:
        deleted_folders.extend(await _prepare_seedr_space(required_bytes))

    try:
        task = unwrap_seedr_task(await add_task(raw_magnet, folder))
    except SeedrError as exc:
        reason = str(exc.detail or "").lower()
        is_storage_shortage = (
            exc.status_code == 413
            or "not enough space" in reason
            or "insufficient storage" in reason
            or "insufficient space" in reason
        )
        if not (is_storage_shortage and auto_cleanup and required_bytes > 0):
            logger.exception(
                "Seedr add failed: session=%s mode=%s code=%s status=%s detail=%s",
                _seedr_session_fingerprint(session_id),
                _seedr_session_auth_mode(session_id),
                exc.code,
                exc.status_code,
                exc.detail,
            )
            raise

        # Seedr can reject a new magnet even when its quota endpoint appears to
        # have enough free bytes (for example, while an old transfer is stuck
        # reserving space). Cancelled tasks are already removed; now delete at
        # least one oldest completed folder and retry the same requested magnet
        # exactly once.
        logger.warning(
            "Seedr reported insufficient space after preflight; reclaiming one more completed folder before retry: required=%s",
            required_bytes,
        )
        deleted_folders.extend(await _prepare_seedr_space(required_bytes, force_one=True))
        try:
            task = unwrap_seedr_task(await add_task(raw_magnet, folder))
        except SeedrError as retry_exc:
            logger.exception(
                "Seedr retry after storage cleanup failed: session=%s code=%s status=%s detail=%s",
                _seedr_session_fingerprint(session_id),
                retry_exc.code,
                retry_exc.status_code,
                retry_exc.detail,
            )
            raise
    except Exception as exc:
        logger.exception(
            "Seedr add unexpected failure: session=%s mode=%s exception_type=%s exception=%s",
            _seedr_session_fingerprint(session_id),
            _seedr_session_auth_mode(session_id),
            type(exc).__name__,
            str(exc)[:2000],
        )
        raise
    tid = task_id(task)
    if not tid:
        raise HTTPException(502, "Seedr did not return a task id")

    task_folder_id = seedr_task_folder_id(task)
    task_name = seedr_task_name(task) or f"Torrent {tid}"
    schedule_seedr_cleanup(str(tid), task_name, task_folder_id)

    logger.info(
        "Seedr add success: session=%s mode=%s task_id=%s folder_id=%s task_name=%s",
        _seedr_session_fingerprint(session_id),
        _seedr_session_auth_mode(session_id),
        tid,
        task_folder_id or "<none>",
        task_name[:300],
    )

    return {
        "backend": "seedr",
        "task_id": int(tid) if tid.isdigit() else tid,
        "id": int(tid) if tid.isdigit() else tid,
        "torrent_name": task_name,
        "folder_id": task_folder_id,
        "deleted_folders": deleted_folders,
        "cancelled_tasks": cancelled_tasks,
    }

def _seedr_file_folder_id(files: list[dict[str, Any]]) -> str:
    """Return the actual torrent folder id exposed by completed file rows."""
    for file in files:
        folder_id = str(file.get("folderId") or "").strip()
        if folder_id:
            return folder_id
    return ""


def _seedr_effective_task_folder_id(
    task: dict[str, Any],
    files: list[dict[str, Any]] | None = None,
) -> str:
    """Prefer the created torrent folder over the destination parent folder."""
    task_folder_id = seedr_task_folder_id(task)
    file_folder_id = _seedr_file_folder_id(files or [])

    if file_folder_id and (
        not task_folder_id
        or file_folder_id != task_folder_id
        or task_folder_id == "0"
    ):
        return file_folder_id
    return task_folder_id


def _remember_seedr_cleanup_folder(tid: str, folder_id: str) -> None:
    folder_id = str(folder_id or "").strip()
    if not folder_id:
        return
    job = _seedr_cleanup_jobs.get(str(tid).strip())
    if not job:
        return
    if str(job.get("folderId") or "").strip() == folder_id:
        return
    job["folderId"] = folder_id
    _save_seedr_cleanup_jobs()


@app.get("/api/seedr/tasks/{tid}/progress")
async def seedr_task_progress(tid: str):
    """Fast polling endpoint: only fetch task state/progress from Seedr."""
    try:
        raw = seedr_data(await seedr_request(f"/tasks/{quote(tid)}"))
    except HTTPException as exc:
        if exc.status_code == 404:
            return {
                "taskId": tid,
                "status": "not_found",
                "progress": 0,
                "name": "",
                "folderId": "",
            }
        raise

    task = (
        raw.get("task")
        if isinstance(raw, dict) and isinstance(raw.get("task"), dict)
        else (raw if isinstance(raw, dict) else {})
    )
    progress = float(task.get("progress") or 0)
    complete = task_complete(task)
    if complete:
        progress = 100

    state = str(task.get("state") or task.get("status") or "").lower()
    status = "completed" if complete else (
        "waiting" if state in {"queued", "pending", "waiting", "paused", "stopped"} else "downloading"
    )

    task_folder_id = seedr_task_folder_id(task)
    completed_files: list[dict[str, Any]] = []
    if complete:
        try:
            completed_files = await task_contents(tid)
        except (HTTPException, SeedrError):
            completed_files = []

    effective_folder_id = _seedr_effective_task_folder_id(task, completed_files)
    task_id_value = str(tid).strip()

    canonical_name = str(
        _seedr_torrent_names_by_task.get(task_id_value)
        or _seedr_torrent_names.get(effective_folder_id)
        or seedr_task_name(task)
        or ""
    ).strip()

    if effective_folder_id and canonical_name:
        _seedr_torrent_names[effective_folder_id] = canonical_name
        if complete:
            _remember_seedr_cleanup_folder(task_id_value, effective_folder_id)
        # Seedr can expose the folder only after the task starts. Rename at
        # that point, rather than only immediately after /tasks POST.
        # Do not call Seedr folder-management endpoints from the free-account
        # progress path. The task state itself is sufficient for polling.

    seedr_task_display_name = canonical_name
    return {
        "taskId": tid,
        "status": status,
        "progress": progress,
        "name": seedr_task_display_name,
        "folderId": effective_folder_id,
    }

@app.get("/api/seedr/tasks/{tid}")
async def seedr_task(tid: str):
    try:
        raw = seedr_data(await seedr_request(f"/tasks/{quote(tid)}"))
    except HTTPException as exc:
        if exc.status_code == 404:
            return {"taskId": tid, "status": "not_found", "progress": 0, "files": [], "downloadUrl": None}
        raise
    task = raw.get("task") if isinstance(raw, dict) and isinstance(raw.get("task"), dict) else (raw if isinstance(raw, dict) else {})
    progress = float(task.get("progress") or 0)
    complete = task_complete(task)
    if complete:
        progress = 100
    files = await task_contents(tid)
    folder_id = _seedr_effective_task_folder_id(task, files)
    _remember_seedr_cleanup_folder(str(tid).strip(), folder_id)
    task_id_value = str(tid).strip()
    canonical_name = str(
        _seedr_torrent_names_by_task.get(task_id_value)
        or _seedr_torrent_names.get(folder_id)
        or seedr_task_name(task)
        or ""
    ).strip()
    if folder_id and canonical_name:
        previous_name = _seedr_torrent_names.get(folder_id)
        _seedr_torrent_names[folder_id] = canonical_name
        if previous_name != canonical_name:
            try:
                await rename_seedr_folder(folder_id, canonical_name)
            except Exception:
                pass
            global _seedr_metadata_cache
            _seedr_metadata_cache = None
    folderNameValue = canonical_name or (await folder_name(folder_id) if folder_id else "")
    for f in files:
        f["folderPath"] = "/Torrent Studio" + ("/" + folderNameValue if folderNameValue else "")
        # Do not resolve direct Seedr URLs while polling/finalizing a task.
        # A fresh URL is generated only by an explicit download/copy/stream action.
        f["url"] = None
    return {"taskId": tid, "name": str(task.get("title") or task.get("name") or ""), "folderName": folderNameValue, "folderId": folder_id, "status": "completed" if complete else "downloading", "progress": progress, "task": task, "files": files, "downloadUrl": None}

async def seedr_folder_payload(folder_id: str) -> dict[str, Any]:
    """Fetch one Seedr folder level, with a short-lived in-process cache."""
    folder_id = str(folder_id).strip()
    if not folder_id:
        return {}

    now = asyncio.get_running_loop().time()
    cached = _seedr_folder_cache.get(folder_id)
    if cached and now - cached[0] < SEEDR_FOLDER_CACHE_SECONDS:
        return cached[1]

    async with _seedr_folder_semaphore:
        # Re-check after waiting for the semaphore so concurrent callers do
        # not issue duplicate Seedr requests for the same folder.
        now = asyncio.get_running_loop().time()
        cached = _seedr_folder_cache.get(folder_id)
        if cached and now - cached[0] < SEEDR_FOLDER_CACHE_SECONDS:
            return cached[1]

        try:
            # Root access is inconsistent across Seedr API variants/accounts.
            # Prefer the normal bearer-authenticated filesystem endpoint, then
            # fall back to the dedicated root endpoint and finally the legacy
            # list_contents endpoint. A failure in one variant must not be
            # presented as a token failure when another variant works.
            if folder_id == "0":
                root_errors: list[str] = []

                try:
                    payload = seedr_data(await seedr_request("/fs/folder/0/contents"))
                    logger.info("Seedr library root resolved via bearer fs endpoint")
                except (HTTPException, SeedrError) as exc:
                    root_errors.append(f"fs:{getattr(exc, 'status_code', 0)}")
                    try:
                        payload = seedr_data(await seedr_root_request())
                        logger.info("Seedr library root resolved via dedicated root endpoint")
                    except (HTTPException, SeedrError) as root_exc:
                        root_errors.append(f"root:{getattr(root_exc, 'status_code', 0)}")
                        try:
                            payload = seedr_data(await legacy_seedr_list_contents("0"))
                            logger.info("Seedr library root resolved via legacy list_contents endpoint")
                        except (HTTPException, SeedrError) as legacy_exc:
                            root_errors.append(f"legacy:{getattr(legacy_exc, 'status_code', 0)}")
                            logger.warning(
                                "Seedr library root resolution failed across all API variants: %s",
                                ",".join(root_errors),
                            )
                            raise legacy_exc
            else:
                payload = seedr_data(await seedr_request(f"/fs/folder/{quote(folder_id)}/contents"))
        except HTTPException as exc:
            if exc.status_code == 404:
                return {}
            raise

    result = payload if isinstance(payload, dict) else {}
    _seedr_folder_cache[folder_id] = (asyncio.get_running_loop().time(), result)
    return result


def direct_folder_summary(folder_id: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    files = arr(payload, ("files", "items"))
    folders = arr(payload, ("folders", "directories"))
    total_size = 0
    valid_files = 0
    for raw in files:
        if not isinstance(raw, dict):
            continue
        try:
            size = int(float(raw.get("size") or 0))
        except Exception:
            size = 0
        total_size += max(0, size)
        if str(raw.get("id") or raw.get("file_id") or "").strip():
            valid_files += 1

    return {
        "id": str(folder_id),
        "folderId": str(folder_id),
        "name": Path(path.rstrip("/")).name or "Root Files",
        "path": path,
        "filesCount": valid_files,
        "totalSize": total_size,
        "folderCount": len([x for x in folders if isinstance(x, dict)]),
    }


async def build_seedr_metadata_tree(
    folder_id: str,
    path: str,
    folder_name_overrides: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Build the first library response from the root and its immediate child
    folders. Child contents are fetched concurrently so folder cards already
    have exact file counts/sizes when the browser receives this response.
    """
    folder_name_overrides = folder_name_overrides or {}
    payload = await seedr_folder_payload(folder_id)
    summary = direct_folder_summary(folder_id, path, payload)

    child_entries: list[tuple[str, str, dict[str, Any]]] = []
    for raw in arr(payload, ("folders", "directories")):
        if not isinstance(raw, dict):
            continue
        child_id = str(raw.get("id") or raw.get("folder_id") or "").strip()
        if not child_id:
            continue
        folder_override = str(folder_name_overrides.get(child_id) or "").strip()
        child_name = (
            folder_override
            or str(raw.get("name") or raw.get("title") or child_id).strip()
            or child_id
        )
        child_path = path.rstrip("/") + "/" + child_name
        child_entries.append((child_id, child_name, raw))

    async def load_child(entry: tuple[str, str, dict[str, Any]]) -> dict[str, Any]:
        child_id, child_name, raw = entry
        child_payload = await seedr_folder_payload(child_id)

        # Older Seedr folders can be exposed with their raw 40-character
        # identifier as the visible name. For a single-file torrent we can
        # recover the human title from the actual file name and normalize the
        # folder once, so existing downloads also get fixed on refresh.
        effective_child_name = child_name
        child_files = arr(child_payload, ("files", "items"))
        if (
            re.fullmatch(r"[0-9a-fA-F]{40}", effective_child_name)
            and len(child_files) == 1
            and isinstance(child_files[0], dict)
        ):
            raw_file_name = str(
                child_files[0].get("name")
                or child_files[0].get("title")
                or ""
            ).strip()
            inferred_name = Path(raw_file_name.replace("\\", "/")).name
            inferred_name = Path(inferred_name).stem.strip()
            if inferred_name:
                try:
                    renamed = await rename_seedr_folder(child_id, inferred_name)
                except Exception:
                    renamed = False
                _seedr_torrent_names[child_id] = inferred_name
                effective_child_name = inferred_name
                if renamed:
                    logger.info(
                        "Renamed legacy hash-named Seedr folder %s to %s",
                        child_id,
                        inferred_name,
                    )

        child_summary = direct_folder_summary(
            child_id,
            path.rstrip("/") + "/" + effective_child_name,
            child_payload,
        )

        # Some Seedr responses expose size/count directly on the folder item;
        # use those only when the contents endpoint did not provide a value.
        if child_summary["filesCount"] == 0:
            for key in ("files_count", "file_count", "filesCount", "fileCount", "count"):
                value = raw.get(key)
                if value is not None:
                    try:
                        child_summary["filesCount"] = max(0, int(value))
                        break
                    except (TypeError, ValueError):
                        pass

        if child_summary["totalSize"] == 0:
            for key in ("size", "total_size", "totalSize"):
                value = raw.get(key)
                if value is not None:
                    try:
                        child_summary["totalSize"] = max(0, int(float(value)))
                        break
                    except (TypeError, ValueError):
                        pass

        child_summary["torrentName"] = (
            _seedr_torrent_names.get(child_id)
            or folder_name_overrides.get(child_id)
            or (effective_child_name if re.fullmatch(r"[0-9a-fA-F]{40}", child_name) is None else "")
            or ""
        )
        child_summary["folderCount"] = len(
            [x for x in arr(child_payload, ("folders", "directories")) if isinstance(x, dict)]
        )
        return child_summary

    children: list[dict[str, Any]] = []
    if child_entries:
        results = await asyncio.gather(
            *(load_child(entry) for entry in child_entries),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, dict):
                children.append(result)

    # The top-level library badge represents all files in its visible torrent
    # folders, not just files placed directly in the root.
    summary["filesCount"] += sum(int(item.get("filesCount") or 0) for item in children)
    summary["totalSize"] += sum(int(item.get("totalSize") or 0) for item in children)
    summary["folderCount"] = len(children)

    return summary, children


async def get_seedr_metadata_tree(force_refresh: bool = False) -> dict[str, Any]:
    global _seedr_metadata_cache, _seedr_metadata_task

    if not current_seedr_token():
        return {"configured": False, "root": None, "folders": []}

    now = asyncio.get_running_loop().time()

    if force_refresh:
        # A completed Seedr task can become visible in the filesystem a few
        # seconds after the metadata cache was populated. Clear both caches so
        # the completion flow can see the new folder immediately.
        _seedr_metadata_cache = None
        _seedr_folder_cache.clear()

    if _seedr_metadata_cache and now - _seedr_metadata_cache[0] < SEEDR_METADATA_CACHE_SECONDS:
        return _seedr_metadata_cache[1]

    if _seedr_metadata_task is not None and not _seedr_metadata_task.done():
        return await _seedr_metadata_task

    async def build() -> dict[str, Any]:
        # Seedr's account root is exposed through a dedicated endpoint.
        # Keep SEEDR_LIBRARY_FOLDER_ID as an optional override for deployments
        # that want to start from a specific existing folder.
        root = "0"

        # Resolve human-readable torrent names from Seedr task metadata in one
        # call. The folder contents/counts and task list are independent, so
        # fetch them concurrently without adding a serial round trip.
        folder_name_overrides: dict[str, str] = dict(_seedr_torrent_names)
        task_folders: list[tuple[str, str]] = []
        try:
            tasks_payload = seedr_data(await seedr_request("/tasks"))
            for raw_task in arr(tasks_payload, ("tasks", "torrents", "items")):
                task = unwrap_seedr_task(seedr_data(raw_task))
                if not task:
                    continue

                task_folder_id = seedr_task_folder_id(task)
                task_name = seedr_task_name(task)

                if task_folder_id:
                    task_folders.append((task_folder_id, task_name))

                if task_folder_id and task_name:
                    # The title supplied by our search/add flow is canonical.
                    # Seedr's task title can contain provider/site prefixes
                    # (for example "www.UIndex.org - ..."), so never let task
                    # metadata overwrite an existing canonical title.
                    if task_folder_id not in _seedr_torrent_names:
                        _seedr_torrent_names[task_folder_id] = task_name
                    folder_name_overrides[task_folder_id] = (
                        _seedr_torrent_names.get(task_folder_id) or task_name
                    )
        except (HTTPException, SeedrError):
            # Folder metadata remains usable even when task-name lookup fails.
            pass

        try:
            root_summary, children = await build_seedr_metadata_tree(
                root,
                "/Torrent Studio",
                folder_name_overrides,
            )
        except (HTTPException, SeedrError) as exc:
            # Some Seedr tokens can authenticate and manage transfers while
            # denying the account-root filesystem listing. Do not turn that
            # provider limitation into a library-wide error. Reconstruct the
            # visible library from the task list and each task's own contents.
            if getattr(exc, "status_code", 0) not in {401, 403}:
                raise

            # First collect folder IDs from the task list. Seedr may expose
            # the created folder only after a task has started/completed, so
            # also resolve task contents below when the task object has no
            # folder_created_id.
            task_candidates: list[dict[str, Any]] = []
            try:
                tasks_payload = seedr_data(await seedr_request("/tasks"))
                for raw_task in arr(tasks_payload, ("tasks", "torrents", "items")):
                    task = unwrap_seedr_task(seedr_data(raw_task))
                    if task:
                        task_candidates.append(task)
            except (HTTPException, SeedrError):
                task_candidates = []

            unique_folders: dict[str, str] = {}

            for task in task_candidates:
                tid = task_id(task)
                task_name = (
                    seedr_task_name(task)
                    or (folder_name_overrides.get(seedr_task_folder_id(task)) if seedr_task_folder_id(task) else "")
                    or f"Torrent {tid}"
                ).strip()
                folder_id = seedr_task_folder_id(task)

                # If the task itself does not expose its created folder, the
                # task contents endpoint often does. This is the same endpoint
                # already used by the completion/progress flow.
                if tid and (not folder_id or folder_id == "0"):
                    try:
                        task_files = await task_contents(tid)
                        folder_id = _seedr_file_folder_id(task_files)
                    except (HTTPException, SeedrError):
                        folder_id = ""

                if folder_id and folder_id != root:
                    unique_folders.setdefault(
                        folder_id,
                        folder_name_overrides.get(folder_id)
                        or _seedr_torrent_names.get(folder_id)
                        or task_name
                        or folder_id,
                    )

            # Preserve any folder IDs already learned from task metadata.
            for folder_id, task_name in task_folders:
                if folder_id and folder_id != root:
                    unique_folders.setdefault(
                        folder_id,
                        folder_name_overrides.get(folder_id)
                        or _seedr_torrent_names.get(folder_id)
                        or task_name
                        or folder_id,
                    )

            async def load_task_folder(folder_id: str, name: str) -> dict[str, Any] | None:
                try:
                    payload = await seedr_folder_payload(folder_id)
                except (HTTPException, SeedrError):
                    return None
                if not payload:
                    return None
                summary = direct_folder_summary(
                    folder_id,
                    "/Torrent Studio/" + name,
                    payload,
                )
                summary["torrentName"] = name
                summary["folderCount"] = len(
                    [x for x in arr(payload, ("folders", "directories")) if isinstance(x, dict)]
                )
                return summary

            if unique_folders:
                results = await asyncio.gather(
                    *(load_task_folder(folder_id, name) for folder_id, name in unique_folders.items()),
                    return_exceptions=True,
                )
                children = [result for result in results if isinstance(result, dict)]
            else:
                children = []

            # A denied root listing is a capability limitation, not an
            # authentication failure. Returning an empty but valid library
            # keeps Search/Prepare/Stream usable even for an account with no
            # folders exposed through the token.
            root_summary = {
                "id": root,
                "folderId": root,
                "name": "Torrent Studio",
                "path": "/Torrent Studio",
                "filesCount": sum(int(item.get("filesCount") or 0) for item in children),
                "totalSize": sum(int(item.get("totalSize") or 0) for item in children),
                "folderCount": len(children),
            }

        return {
            "configured": True,
            "root": root_summary,
            "folders": children,
        }

    _seedr_metadata_task = asyncio.create_task(build())
    try:
        result = await _seedr_metadata_task
        _seedr_metadata_cache = (asyncio.get_running_loop().time(), result)
        return result
    finally:
        _seedr_metadata_task = None


@app.get("/api/seedr/library")
async def seedr_library_metadata(fresh: bool = Query(False)):
    return await get_seedr_metadata_tree(force_refresh=fresh)


@app.get("/api/seedr/folders/{folder_id}/contents")
async def seedr_folder_contents(folder_id: str):
    if not current_seedr_token():
        return {"configured": False, "folderId": folder_id, "files": [], "folders": []}

    payload = await seedr_folder_payload(folder_id)
    files: list[dict[str, Any]] = []
    for raw in arr(payload, ("files", "items")):
        file = normalize_file(raw, folder_id)
        file["url"] = None
        files.append(file)

    folders: list[dict[str, Any]] = []
    for raw in arr(payload, ("folders", "directories")):
        if not isinstance(raw, dict):
            continue
        child_id = str(raw.get("id") or raw.get("folder_id") or "").strip()
        if not child_id:
            continue
        child_name = str(raw.get("name") or raw.get("title") or child_id).strip() or child_id
        folders.append({"id": child_id, "folderId": child_id, "name": child_name})

    return {"configured": True, "folderId": folder_id, "files": files, "folders": folders}


@app.get("/api/seedr/files")
async def seedr_files():
    # Backwards-compatible full file endpoint. New UI code uses
    # /api/seedr/library + /api/seedr/folders/{id}/contents instead.
    if not current_seedr_token():
        return {"configured": False, "files": []}

    root = "0"

    result = await collect_folder(root, "/Torrent Studio")
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result:
        item_id = str(item.get("id") or "")
        if item_id and item_id not in seen:
            seen.add(item_id)
            unique.append(item)

    return {"configured": True, "files": unique}

@app.get("/api/seedr/files/{file_id}/download/url")
async def seedr_file_download_url(file_id: str):
    # Resolve a fresh direct Seedr URL only when the user explicitly requests it.
    return await download_url(file_id)

@app.get("/api/seedr/files/{file_id}/download")
async def seedr_file_download(file_id: str):
    # Redirect the browser to Seedr's temporary direct URL so large downloads
    # do not flow through the Render Free instance.
    result = await download_url(file_id)
    return RedirectResponse(result["url"], status_code=307)


@app.get("/api/seedr/files/{file_id}/download/direct")
async def seedr_file_download_direct(
    file_id: str,
    filename: str = Query(""),
):
    """Stream a Seedr file with an explicit browser download filename."""
    result = await download_url(file_id)
    filename_value = _safe_download_filename(
        filename or result.get("name") or "",
        f"seedr-file-{file_id}",
    )
    body, content_type, headers = await _stream_seedr_download(result["url"])
    ascii_name = filename_value.encode("ascii", errors="ignore").decode("ascii").strip() or f"seedr-file-{file_id}"
    headers["Content-Disposition"] = (
        'attachment; filename="' + ascii_name.replace('"', "_") + '"'
        + "; filename*=UTF-8''" + quote(filename_value, safe="")
    )
    return StreamingResponse(
        body(),
        media_type=content_type,
        headers=headers,
    )


async def seedr_folder_download_url(folder_id: str) -> str:
    folder_id = str(folder_id or "").strip()
    if not folder_id or not folder_id.isdigit():
        raise HTTPException(400, "Invalid Seedr folder id")

    # Known-good Torrent Studio implementation:
    # initialize a temporary archive and let Seedr return the signed URL.
    archive_id = str(uuid.uuid4())
    payload = seedr_data(
        await seedr_request(
            f"/download/archive/init/{quote(archive_id)}",
            "PUT",
            {"archive_arr": [{"type": "folder", "id": int(folder_id)}]},
        )
    )

    if isinstance(payload, dict):
        url = str(
            payload.get("url")
            or payload.get("download_url")
            or payload.get("downloadUrl")
            or payload.get("signed_url")
            or payload.get("signedUrl")
            or ""
        ).strip()
    elif isinstance(payload, str):
        url = payload.strip()
    else:
        url = ""

    if not url:
        raise HTTPException(502, "Seedr did not return a folder download URL")
    return url


@app.get("/api/seedr/folders/{folder_id}/download/url")
async def seedr_folder_download_url_api(folder_id: str):
    # Resolve the temporary direct Seedr folder URL only on an explicit click.
    url = await seedr_folder_download_url(folder_id)
    return {"url": url}

@app.get("/api/seedr/folders/{folder_id}/download")
async def seedr_folder_download(folder_id: str):
    # Redirect the browser to Seedr's temporary direct folder URL rather than
    # streaming the archive through Render.
    url = await seedr_folder_download_url(folder_id)
    return RedirectResponse(url, status_code=307)


@app.get("/api/seedr/folders/{folder_id}/download/direct")
async def seedr_folder_download_direct(
    folder_id: str,
    filename: str = Query(""),
):
    """Stream a Seedr folder archive with an explicit .zip filename."""
    url = await seedr_folder_download_url(folder_id)
    filename_value = _safe_download_filename(
        filename,
        f"seedr-folder-{folder_id}.zip",
    )
    if not filename_value.lower().endswith(".zip"):
        filename_value += ".zip"

    body, content_type, headers = await _stream_seedr_download(url)
    ascii_name = filename_value.encode("ascii", errors="ignore").decode("ascii").strip() or f"seedr-folder-{folder_id}.zip"
    headers["Content-Disposition"] = (
        'attachment; filename="' + ascii_name.replace('"', "_") + '"'
        + "; filename*=UTF-8''" + quote(filename_value, safe="")
    )
    return StreamingResponse(
        body(),
        media_type=content_type or "application/zip",
        headers=headers,
    )

# HLS stream sources are kept server-side. The browser receives a same-origin
# manifest URL so the Seedr access token never needs to be exposed to the client.
SEEDR_HLS_CACHE_SECONDS = 600
_seedr_hls_sources: dict[str, tuple[float, str, set[str]]] = {}


def _seedr_media_url(file_id: str, media_type: str) -> str:
    if media_type == "video":
        endpoint = f"/media/hls/{quote(file_id)}"
    elif media_type == "audio":
        endpoint = f"/media/mp3/{quote(file_id)}"
    else:
        raise HTTPException(400, "Unsupported Seedr media type")
    return SEEDR_MEDIA_BASE.rstrip("/") + endpoint + "?access_token=" + quote(current_seedr_token(), safe="")

def seedr_v2_bearer_token() -> str:
    """Accept a raw Seedr PAT or MediaFusion-style base64 JSON token."""
    raw = current_seedr_token().strip()
    if not raw:
        return ""
    try:
        decoded = base64.b64decode(raw, validate=True).decode("utf-8")
        payload = json.loads(decoded)
        token = str(payload.get("access_token") or "").strip() if isinstance(payload, dict) else ""
        if token:
            return token
    except Exception:
        pass
    return raw


async def seedr_v2_request(path: str) -> Any:
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")
    bearer = seedr_v2_bearer_token()
    if not bearer:
        raise HTTPException(503, "Seedr access token is empty")
    url = SEEDR_V2_BASE.rstrip("/") + "/" + str(path).lstrip("/")
    async with _InstrumentedAsyncClient(timeout=httpx.Timeout(35.0, connect=8.0), follow_redirects=True) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {bearer}", "Accept": "application/json"},
        )
    raw = response.text
    try:
        data = response.json() if raw else None
    except Exception:
        data = raw
    if response.status_code >= 400:
        raise HTTPException(
            response.status_code,
            seedr_error_message(response.status_code, data, raw),
        )
    return data

async def seedr_v2_video_url(file_id: str, audio_index: int | None = None) -> str:
    """Use Seedr V2 current presentation URL, with direct-download fallback."""
    if not file_id:
        return ""
    try:
        presentation_path = f"/presentations/file/{quote(file_id)}/video"
        if audio_index is not None and audio_index >= 0:
            presentation_path += "?" + urlencode({"audio": str(audio_index)})
        payload = seedr_data(await seedr_v2_request(presentation_path))
        if isinstance(payload, dict):
            link = payload.get("link")
            link_url = link.get("url") if isinstance(link, dict) else ""
            url = str(payload.get("url") or payload.get("stream_url") or link_url or "").strip()
            if url.startswith(("http://", "https://")):
                return url
    except HTTPException:
        pass

    try:
        payload = seedr_data(await seedr_v2_request(f"/download/file/{quote(file_id)}/url"))
        if isinstance(payload, dict):
            url = str(payload.get("url") or payload.get("download_url") or "").strip()
            if url.startswith(("http://", "https://")):
                return url
    except HTTPException:
        pass

    return ""


def _absolute_hls_uri(base_url: str, uri: str) -> str:
    absolute = urljoin(base_url, uri)
    # Some HLS manifests use one access query string on the playlist URL and
    # omit it from relative segment/variant URLs. Carry it forward.
    if not urlsplit(uri).query:
        base_query = urlsplit(base_url).query
        if base_query and not urlsplit(absolute).query:
            absolute += "?" + base_query
    return absolute


def _encode_hls_target(url: str) -> str:
    return base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_hls_target(value: str) -> str:
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding).decode("utf-8")
    except Exception as exc:
        raise HTTPException(400, "Invalid HLS resource token") from exc


def _rewrite_hls_manifest(file_id: str, manifest_text: str, base_url: str) -> str:
    lines = manifest_text.splitlines()
    rewritten: list[str] = []

    def proxy_url(absolute: str) -> str:
        return "/api/seedr/hls/" + quote(file_id, safe="") + "/resource?u=" + _encode_hls_target(absolute)

    for line in lines:
        current = line
        def replace_uri(match: re.Match[str]) -> str:
            uri = match.group(1)
            return 'URI="' + proxy_url(_absolute_hls_uri(base_url, uri)) + '"'
        current = re.sub(r'URI="([^"]+)"', replace_uri, current)

        stripped = current.strip()
        if stripped and not stripped.startswith("#"):
            current = proxy_url(_absolute_hls_uri(base_url, stripped))
        rewritten.append(current)

    return "\n".join(rewritten) + ("\n" if manifest_text.endswith("\n") else "")


async def _presentation_is_hls(url: str) -> bool:
    """Probe a Seedr presentation URL without downloading the full media file."""
    if not url:
        return False
    try:
        async with _InstrumentedAsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url, headers={"Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,video/*,*/*", "Range": "bytes=0-2047"})
        content_type = str(response.headers.get("content-type") or "").lower()
        prefix = response.content[:2048].decode("utf-8", errors="ignore")
        return "mpegurl" in content_type or "#EXTM3U" in prefix
    except Exception as exc:
        logger.info("Seedr presentation probe failed: %s", exc)
        return False


async def _fetch_seedr_hls_manifest(file_id: str) -> tuple[str, str]:
    """Resolve a browser-playable HLS manifest from Seedr V2, then v1 fallback."""
    candidates: list[str] = []
    presentation_url = await seedr_v2_video_url(file_id)
    if presentation_url:
        candidates.append(presentation_url)
    # Seedr's legacy HLS endpoint explicitly requests a converted browser stream.
    candidates.append(_seedr_media_url(file_id, "video"))

    last_detail = "Seedr did not return an HLS manifest"
    for upstream_url in dict.fromkeys(candidates):
        try:
            async with _InstrumentedAsyncClient(timeout=35, follow_redirects=True) as client:
                response = await client.get(
                    upstream_url,
                    headers={"Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,*/*"},
                )
            if response.status_code >= 400:
                last_detail = response.text[:500] or f"Seedr returned HTTP {response.status_code}"
                continue

            content_type = str(response.headers.get("content-type") or "").lower()
            text = response.text
            if "#EXTM3U" not in text[:200]:
                last_detail = f"Seedr returned {content_type or 'non-HLS content'}"
                continue

            final_url = str(response.url)
            host = urlsplit(final_url).hostname or ""
            if not host:
                last_detail = "Seedr returned an invalid HLS URL"
                continue

            allowed_hosts = {host.lower()}
            for raw_uri in re.findall(r'(?:URI="([^"]+)"|^([^#\s][^\r\n]*))', text, flags=re.M):
                uri = raw_uri[0] or raw_uri[1]
                if uri:
                    try:
                        ref_host = urlsplit(_absolute_hls_uri(final_url, uri)).hostname
                        if ref_host:
                            allowed_hosts.add(ref_host.lower())
                    except Exception:
                        pass

            _seedr_hls_sources[file_id] = (
                asyncio.get_running_loop().time() + SEEDR_HLS_CACHE_SECONDS,
                final_url,
                allowed_hosts,
            )
            logger.info("Seedr HLS manifest resolved: file=%s source=%s", file_id, urlsplit(final_url).hostname)
            return text, final_url
        except Exception as exc:
            last_detail = str(exc)
            continue

    raise HTTPException(502, last_detail)

async def _get_hls_source(file_id: str) -> tuple[str, set[str]]:
    now = asyncio.get_running_loop().time()
    cached = _seedr_hls_sources.get(file_id)
    if cached and cached[0] > now:
        return cached[1], cached[2]

    _manifest, final_url = await _fetch_seedr_hls_manifest(file_id)
    cached = _seedr_hls_sources[file_id]
    return final_url, cached[2]


async def resolve_seedr_stream_id(file_id: str, name: str = "") -> str:
    """Resolve the Seedr playback file identifier without requiring HLS."""
    candidate = str(file_id or "").strip()
    if candidate:
        try:
            presentation = await seedr_v2_video_url(candidate)
            if presentation:
                return candidate
        except HTTPException:
            pass
        try:
            await _fetch_seedr_hls_manifest(candidate)
            return candidate
        except HTTPException:
            pass

    if not name:
        raise HTTPException(404, "Seedr playback file could not be resolved")

    try:
        result = seedr_data(await seedr_request(f"/search/fs?query={quote(name)}"))
    except HTTPException as exc:
        raise HTTPException(exc.status_code, "Seedr file lookup failed") from exc

    candidates = arr(result, ("files", "items"))
    wanted_name = Path(name).name.lower()
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        raw_name = str(raw.get("name") or raw.get("title") or "").strip()
        if raw_name.lower() != wanted_name:
            continue

        # Match MediaFusion: Seedr V2 playback uses the actual file id.
        resolved = str(
            raw.get("id")
            or raw.get("file_id")
            or raw.get("folder_file_id")
            or raw.get("folderFileId")
            or ""
        ).strip()
        if not resolved:
            continue

        try:
            await _fetch_seedr_hls_manifest(resolved)
            logger.info("Seedr playback id resolved by filename: %s -> %s", name, resolved)
            return resolved
        except HTTPException:
            continue

    raise HTTPException(404, f"No playable Seedr stream found for {name}")


@app.get("/api/seedr/files/stream")
async def seedr_file_stream(
    file_id: str = Query(""),
    type: str = Query("video"),
    name: str = Query(""),
):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    resolved_id = await resolve_seedr_stream_id(file_id, name)

    if type == "video":
        # Restore the tested direct-browser-stream strategy from
        # fix-seedr-direct-browser-stream:
        #   1) ask Seedr V2 for its presentation URL;
        #   2) if it is a browser-playable direct presentation, proxy it with
        #      Range support;
        #   3) otherwise use the existing HLS proxy.
        presentation_url = await seedr_v2_video_url(resolved_id)
        if presentation_url and not await _presentation_is_hls(presentation_url):
            return {
                "url": "/api/seedr/media/video/" + quote(resolved_id, safe=""),
                "externalUrl": presentation_url,
                "name": name or resolved_id,
                "resolvedFileId": resolved_id,
                "protocol": "direct",
            }

        try:
            await _fetch_seedr_hls_manifest(resolved_id)
            return {
                "url": "/api/seedr/hls/" + quote(resolved_id, safe=""),
                "externalUrl": presentation_url or _seedr_media_url(resolved_id, "video"),
                "name": name or resolved_id,
                "resolvedFileId": resolved_id,
                "protocol": "hls",
            }
        except HTTPException:
            if presentation_url:
                return {
                    "url": "/api/seedr/media/video/" + quote(resolved_id, safe=""),
                    "externalUrl": presentation_url,
                    "name": name or resolved_id,
                    "resolvedFileId": resolved_id,
                    "protocol": "direct",
                }
            raise

    return {
        "url": "/api/seedr/media/audio/" + quote(resolved_id, safe=""),
        "externalUrl": _seedr_media_url(resolved_id, "audio"),
        "name": name or resolved_id,
        "resolvedFileId": resolved_id,
        "protocol": "mp3",
    }

@app.get("/api/seedr/hls/{file_id}")
async def seedr_hls_manifest(file_id: str):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    manifest, final_url = await _fetch_seedr_hls_manifest(file_id)
    cached = _seedr_hls_sources.get(file_id)
    allowed_hosts = cached[2] if cached else {urlsplit(final_url).hostname.lower()}
    rewritten = _rewrite_hls_manifest(file_id, manifest, final_url)

    return Response(
        content=rewritten,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/seedr/hls/{file_id}/resource")
async def seedr_hls_resource(request: Request, file_id: str, u: str = Query(...)):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    target = _decode_hls_target(u)
    parsed = urlsplit(target)
    host = (parsed.hostname or "").lower()
    if not host:
        raise HTTPException(400, "Invalid HLS target URL")

    try:
        base_url, allowed_hosts = await _get_hls_source(file_id)
    except HTTPException:
        raise

    if host not in allowed_hosts:
        raise HTTPException(403, "HLS resource host is not allowed")

    headers: dict[str, str] = {"Accept": "*/*"}
    if request is not None:
        range_header = request.headers.get("range")
        if range_header:
            headers["Range"] = range_header

    async with _InstrumentedAsyncClient(timeout=35, follow_redirects=True) as client:
        response = await client.get(target, headers=headers)

    if response.status_code >= 400:
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/octet-stream"),
            headers={"Access-Control-Allow-Origin": "*"},
        )

    content_type = str(response.headers.get("content-type") or "").lower()
    body = response.content
    _record_media_bytes(file_id, len(body))

    if "mpegurl" in content_type or "#EXTM3U" in body[:200].decode("utf-8", errors="ignore"):
        text = body.decode("utf-8", errors="replace")
        final_url = str(response.url)
        final_host = urlsplit(final_url).hostname
        if final_host:
            allowed_hosts.add(final_host.lower())
        _seedr_hls_sources[file_id] = (
            asyncio.get_running_loop().time() + SEEDR_HLS_CACHE_SECONDS,
            final_url,
            allowed_hosts,
        )
        body = _rewrite_hls_manifest(file_id, text, final_url).encode("utf-8")
        content_type = "application/vnd.apple.mpegurl"

    response_headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-store",
        "Accept-Ranges": response.headers.get("accept-ranges", "bytes"),
    }
    for header in ("content-range", "content-length", "etag", "last-modified"):
        if response.headers.get(header):
            response_headers[header.title()] = response.headers[header]

    return Response(
        content=body,
        status_code=response.status_code,
        media_type=content_type or "application/octet-stream",
        headers=response_headers,
    )


async def _seedr_media_source_url(file_id: str) -> str:
    result = await download_url(file_id)
    url = str(result.get("url") or "").strip()
    if not url:
        raise HTTPException(502, "Seedr returned no media URL")
    return url


_SEEDR_FFPROBE_CACHE_SECONDS = 600
_seedr_ffprobe_cache: dict[str, tuple[float, dict[str, Any]]] = {}


async def _ffprobe_seedr_file(file_id: str) -> dict[str, Any]:
    """Inspect a Seedr file and reuse the result for media/subtitle requests.

    The same MKV was previously probed once for track discovery and then probed
    again when the user selected an embedded subtitle. Reusing the probe keeps
    Render Free from doing the expensive remote MKV inspection twice.
    """
    now = asyncio.get_running_loop().time()
    cached = _seedr_ffprobe_cache.get(file_id)
    if cached and cached[0] > now:
        return cached[1]

    source_url = await _seedr_media_source_url(file_id)
    command = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        "-analyzeduration", "10M",
        "-probesize", "20M",
        source_url,
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=45)
    except asyncio.TimeoutError as exc:
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        raise HTTPException(504, "Media track inspection timed out") from exc
    except FileNotFoundError as exc:
        raise HTTPException(503, "FFmpeg is not installed on the media server") from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-1000:]
        raise HTTPException(502, detail or "FFprobe could not inspect the Seedr file")

    try:
        data = json.loads(stdout.decode("utf-8", errors="replace"))
    except Exception as exc:
        raise HTTPException(502, "FFprobe returned invalid metadata") from exc

    _seedr_ffprobe_cache[file_id] = (now + _SEEDR_FFPROBE_CACHE_SECONDS, data)
    return data


_SEEDR_MEDIA_INFO_CACHE_SECONDS = 600
_seedr_media_info_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_SEEDR_EMBEDDED_SUBTITLE_CACHE_SECONDS = 600
_seedr_embedded_subtitle_cache: dict[str, tuple[float, bytes]] = {}


def _stream_tags(stream: dict[str, Any]) -> dict[str, Any]:
    raw = stream.get("tags")
    if not isinstance(raw, dict):
        return {}
    # FFprobe normally emits lowercase Matroska tag keys, but some containers
    # expose alternate casing/names. Normalize them before building labels.
    return {str(key).strip().lower(): value for key, value in raw.items()}


def _track_language(stream: dict[str, Any]) -> str:
    tags = _stream_tags(stream)
    for key in ("language", "lang", "language-eng", "language_ietf"):
        value = str(tags.get(key) or "").strip().lower()
        if value:
            return value.split("-")[0]
    return ""


def _track_title(stream: dict[str, Any], fallback: str) -> str:
    tags = _stream_tags(stream)
    for key in ("title", "handler_name", "name", "track_name"):
        value = str(tags.get(key) or "").strip()
        if value:
            return value
    return fallback


@app.get("/api/seedr/media-info/{file_id}")
async def seedr_media_info(file_id: str):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    cached = _seedr_media_info_cache.get(file_id)
    now = asyncio.get_running_loop().time()
    if cached and cached[0] > now:
        return cached[1]

    data = await _ffprobe_seedr_file(file_id)
    streams = data.get("streams") if isinstance(data, dict) else []
    if not isinstance(streams, list):
        streams = []

    language_names = {
        "en": "English", "eng": "English",
        "hi": "Hindi", "hin": "Hindi",
        "fr": "French", "fra": "French",
        "de": "German", "deu": "German",
        "es": "Spanish", "spa": "Spanish",
        "it": "Italian", "ita": "Italian",
        "pt": "Portuguese", "por": "Portuguese",
        "ru": "Russian", "rus": "Russian",
        "ja": "Japanese", "jpn": "Japanese",
        "ko": "Korean", "kor": "Korean",
        "zh": "Chinese", "zho": "Chinese",
        "ar": "Arabic", "ara": "Arabic",
        "bn": "Bengali", "ben": "Bengali",
    }

    audio_tracks = []
    subtitle_tracks = []
    audio_index = 0
    subtitle_index = 0

    for stream in streams:
        if not isinstance(stream, dict):
            continue
        codec_type = str(stream.get("codec_type") or "").lower()
        tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
        lang = _track_language(stream)
        title = _track_title(stream, "")
        disposition = stream.get("disposition") if isinstance(stream.get("disposition"), dict) else {}
        if codec_type == "audio":
            language_label = language_names.get(lang, lang.upper() if lang else "")
            # Keep the raw mix title separate from the language. The frontend
            # combines them into a clearer label such as "English (BD 5.1)".
            label = title or language_label or f"Audio {audio_index + 1}"
            audio_tracks.append({
                "index": audio_index,
                "streamIndex": int(stream.get("index") or 0),
                "language": lang,
                "title": label,
                "codec": str(stream.get("codec_name") or "").upper(),
                "channels": int(stream.get("channels") or 0),
                "default": bool(disposition.get("default")),
            })
            audio_index += 1
        elif codec_type == "subtitle":
            codec = str(stream.get("codec_name") or "").lower()
            # Bitmap subtitle codecs cannot be represented as browser WebVTT.
            if codec in {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"}:
                continue
            language_label = language_names.get(lang, lang.upper() if lang else "")
            forced = bool(disposition.get("forced"))
            default = bool(disposition.get("default"))
            codec_label = {
                "subrip": "SRT",
                "ass": "ASS",
                "ssa": "SSA",
                "webvtt": "WebVTT",
                "mov_text": "Text",
                "text": "Text",
            }.get(codec, codec.upper() or "Text")
            # Preserve the real Matroska title/language whenever available.
            # Some MKVs contain no subtitle language/title tags at all. In that
            # case the old fallback produced identical entries such as
            # "SRT", making it impossible to tell tracks apart. Give unnamed
            # tracks a stable ordinal while keeping the real language when one
            # is available.
            if title:
                label = title
            elif language_label:
                label = f"{language_label} {subtitle_index + 1}"
            else:
                label = f"{codec_label} {subtitle_index + 1}"

            if forced and "forced" not in label.lower():
                label += " · Forced"
            elif default and "default" not in label.lower():
                label += " · Default"
            stream_index = int(stream.get("index") or 0)
            subtitle_tracks.append({
                "index": subtitle_index,
                "streamIndex": stream_index,
                "language": lang,
                "title": label,
                "codec": str(stream.get("codec_name") or "").upper(),
                "url": f"/api/seedr/media-info/{quote(file_id, safe='')}/subtitle?stream={stream_index}&name={quote(label, safe='')}",
            })
            subtitle_index += 1

    result = {
        "name": str((data.get("format") or {}).get("filename") or file_id) if isinstance(data, dict) else file_id,
        "audioTracks": audio_tracks,
        "subtitleTracks": subtitle_tracks,
    }
    _seedr_media_info_cache[file_id] = (now + _SEEDR_MEDIA_INFO_CACHE_SECONDS, result)
    return result


@app.get("/api/seedr/media-info/{file_id}/subtitle")
async def seedr_embedded_subtitle(
    file_id: str,
    track: int | None = Query(None, ge=0),
    stream: int | None = Query(None, ge=0),
    name: str = Query("subtitle"),
):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    cache_key = f"{file_id}:{track}"
    now = asyncio.get_running_loop().time()
    cached = _seedr_embedded_subtitle_cache.get(cache_key)
    if cached and cached[0] > now:
        return Response(
            content=cached[1],
            media_type="text/vtt; charset=utf-8",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "private, max-age=600",
                "Content-Disposition": f'inline; filename="{Path(name).name.replace(chr(34), "_")}.vtt"',
            },
        )

    # Reuses the media-info FFprobe result instead of probing the remote MKV
    # a second time when the user selects an embedded subtitle.
    data = await _ffprobe_seedr_file(file_id)
    streams = data.get("streams") if isinstance(data, dict) else []
    subtitle_streams = [
        stream for stream in streams
        if isinstance(stream, dict) and str(stream.get("codec_type") or "").lower() == "subtitle"
        and str(stream.get("codec_name") or "").lower() not in {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle"}
    ]
    if stream is not None:
        selected = next(
            (
                item for item in subtitle_streams
                if int(item.get("index") or -1) == stream
            ),
            None,
        )
        if selected is None:
            raise HTTPException(404, "Subtitle stream not found")
        stream_index = int(selected.get("index") or 0)
        cache_key = f"{file_id}:stream:{stream_index}"
    else:
        if track is None or track >= len(subtitle_streams):
            raise HTTPException(404, "Subtitle track not found")
        stream_index = int(subtitle_streams[track].get("index") or 0)
        cache_key = f"{file_id}:{track}"

    source_url = await _seedr_media_source_url(file_id)
    command = [
        "ffmpeg", "-v", "error", "-nostdin",
        "-i", source_url,
        "-map", f"0:{stream_index}",
        "-c:s", "webvtt",
        "-f", "webvtt",
        "pipe:1",
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
    except asyncio.TimeoutError as exc:
        try:
            process.kill()
            await process.wait()
        except Exception:
            pass
        raise HTTPException(504, "Subtitle extraction timed out") from exc

    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-1000:]
        raise HTTPException(502, detail or "Subtitle extraction failed")

    _seedr_embedded_subtitle_cache[cache_key] = (
        now + _SEEDR_EMBEDDED_SUBTITLE_CACHE_SECONDS,
        stdout,
    )

    return Response(
        content=stdout,
        media_type="text/vtt; charset=utf-8",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "private, max-age=600",
            "Content-Disposition": f'inline; filename="{Path(name).name.replace(chr(34), "_")}.vtt"',
        },
    )


async def _stream_selected_audio(file_id: str, audio_index: int, start: float = 0.0) -> StreamingResponse:
    data = await _ffprobe_seedr_file(file_id)
    streams = data.get("streams") if isinstance(data, dict) else []
    audio_streams = [
        stream for stream in streams
        if isinstance(stream, dict) and str(stream.get("codec_type") or "").lower() == "audio"
    ]
    if audio_index >= len(audio_streams):
        raise HTTPException(404, "Audio track not found")

    source_url = await _seedr_media_source_url(file_id)
    stream = audio_streams[audio_index]
    video_streams = [
        item for item in streams
        if isinstance(item, dict) and str(item.get("codec_type") or "").lower() == "video"
    ]
    video_codec = str((video_streams[0] if video_streams else {}).get("codec_name") or "").lower()

    command = [
        "ffmpeg", "-v", "error", "-nostdin",
        *([ "-ss", str(max(0.0, start)) ] if start > 0 else []),
        "-i", source_url,
        "-map", "0:v:0",
        "-map", f"0:a:{audio_index}",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4",
        "pipe:1",
    ]
    if video_codec in {"h264", "avc1"}:
        command[command.index("-c:a"):command.index("-c:a")] = ["-c:v", "copy"]
    else:
        command[command.index("-c:a"):command.index("-c:a")] = [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
        ]

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def body():
        try:
            while True:
                chunk = await process.stdout.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except Exception:
                    pass
            try:
                await process.wait()
            except Exception:
                pass

    return StreamingResponse(
        body(),
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.get("/api/seedr/media/video/{file_id}/stats")
async def seedr_video_media_stats(file_id: str):
    return {
        "bytesPerSecond": round(_media_download_speed(file_id), 2),
        "windowSeconds": _MEDIA_STATS_WINDOW_SECONDS,
    }

@app.get("/api/seedr/media/video/{file_id}")
async def seedr_video_media(
    file_id: str,
    request: Request,
    audio: int | None = Query(None, ge=0),
    start: float = Query(0.0, ge=0.0),
):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    if audio is not None:
        return await _stream_selected_audio(file_id, audio, start=start)

    upstream_url = await seedr_v2_video_url(file_id)
    if not upstream_url:
        raise HTTPException(404, "Seedr returned no video presentation URL")

    headers = {"Accept": "video/*,application/octet-stream,*/*"}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    client = _InstrumentedAsyncClient(timeout=60, follow_redirects=True)
    try:
        response = await client.send(
            client.build_request("GET", upstream_url, headers=headers),
            stream=True,
        )
    except Exception:
        await client.aclose()
        raise

    if response.status_code >= 400:
        body = await response.aread()
        status = response.status_code
        content_type = response.headers.get("content-type", "application/octet-stream")
        await response.aclose()
        await client.aclose()
        return Response(
            content=body,
            status_code=status,
            media_type=content_type,
            headers={"Access-Control-Allow-Origin": "*"},
        )

    response_headers = {
        "Access-Control-Allow-Origin": "*",
        "Accept-Ranges": response.headers.get("accept-ranges", "bytes"),
        "Cache-Control": "no-store",
    }
    for header in ("content-range", "content-length", "etag", "last-modified"):
        if response.headers.get(header):
            response_headers[header.title()] = response.headers[header]

    async def body_stream():
        try:
            async for chunk in response.aiter_bytes():
                _record_media_bytes(file_id, len(chunk))
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        body_stream(),
        status_code=response.status_code,
        media_type=response.headers.get("content-type", "video/mp4"),
        headers=response_headers,
    )


@app.get("/api/seedr/media/audio/{file_id}")
async def seedr_audio_media_route(
    file_id: str,
    request: Request,
    track: int = Query(0, ge=0),
    start: float = Query(0.0, ge=0.0),
):
    """Stream one Seedr audio track as browser-compatible fragmented MP4.

    This route is used for alternate-audio playback so the video element never
    has to be replaced. Keeping video on its original timeline avoids the
    shortened-duration and A/V drift caused by remuxing the whole video when a
    user changes audio tracks.
    """
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    data = await _ffprobe_seedr_file(file_id)
    streams = data.get("streams") if isinstance(data, dict) else []
    audio_streams = [
        stream for stream in streams
        if isinstance(stream, dict) and str(stream.get("codec_type") or "").lower() == "audio"
    ]
    if track >= len(audio_streams):
        raise HTTPException(404, "Audio track not found")

    source_url = await _seedr_media_source_url(file_id)
    source = audio_streams[track]
    codec = str(source.get("codec_name") or "").lower()

    command = [
        "ffmpeg", "-v", "error", "-nostdin",
        *(["-ss", str(max(0.0, start))] if start > 0 else []),
        "-i", source_url,
        "-map", f"0:a:{track}",
    ]

    # Emit a plain MP3 stream for the hidden browser audio element.
    # MP3 is broadly supported by Chrome/Edge/Android and does not require the
    # fragmented MP4/WebM demuxers that can stall on a non-seekable pipe.
    command += [
        "-vn",
        "-sn",
        "-dn",
        "-ac", "2",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        "-f", "mp3",
        "pipe:1",
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(503, "FFmpeg is not installed on the media server") from exc

    async def body():
        try:
            while True:
                chunk = await process.stdout.read(512 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except Exception:
                    pass
            try:
                await process.wait()
            except Exception:
                pass

    return StreamingResponse(
        body(),
        media_type="audio/mpeg",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "Access-Control-Allow-Origin": "*",
        },
    )

@app.get("/api/seedr/files/{file_id}/subtitle")
async def seedr_file_subtitle(
    file_id: str,
    filename: str = Query(""),
):
    """Return a Seedr sidecar subtitle as browser-compatible WebVTT."""
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")

    requested_name = Path(filename or "").name
    extension = requested_name.rsplit(".", 1)[-1].lower() if "." in requested_name else ""
    if extension not in {"srt", "vtt"}:
        raise HTTPException(400, "Only SRT and VTT subtitles are supported")

    result = await download_url(file_id)
    upstream_url = str(result.get("url") or "").strip()
    if not upstream_url:
        raise HTTPException(502, "Seedr returned no subtitle URL")

    async with _InstrumentedAsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(upstream_url)
        if response.status_code >= 400:
            raise HTTPException(response.status_code, "Seedr subtitle download failed")

    text = response.content.decode("utf-8-sig", errors="replace")
    if extension == "srt":
        # Convert the common SRT timestamp format to WebVTT.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(
            r"(\d{2}:\d{2}:\d{2}),(\d{3})",
            r"\1.\2",
            text,
        )
        text = "WEBVTT\n\n" + text.lstrip()
    elif not text.lstrip().startswith("WEBVTT"):
        text = "WEBVTT\n\n" + text.lstrip()

    return Response(
        content=text,
        media_type="text/vtt; charset=utf-8",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-store",
            "Content-Disposition": "inline; filename=\"" + requested_name.replace('"', '_') + "\"",
        },
    )

async def _cancel_seedr_task_and_partial_folder(
    tid: str,
    task: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stop an unfinished Seedr task and remove its partial folder, never a completed download."""
    global _seedr_metadata_cache

    task_id_value = str(tid or "").strip()
    if not task_id_value:
        raise HTTPException(400, "A Seedr task id is required")

    task_found = isinstance(task, dict) and bool(task)
    task_value = task if isinstance(task, dict) else {}
    if not task_found:
        try:
            raw = seedr_data(await seedr_request(f"/tasks/{quote(task_id_value, safe='')}"))
            task_value = unwrap_seedr_task(raw)
            task_found = bool(task_value)
        except (HTTPException, SeedrError) as exc:
            if getattr(exc, "status_code", 0) != 404:
                raise
            task_value = {}

    complete = task_complete(task_value) if task_found else False
    active = task_found and not complete
    task_name = seedr_task_name(task_value) or f"Torrent {task_id_value}"
    folder_id = seedr_task_folder_id(task_value) if task_found else ""
    task_files: list[dict[str, Any]] = []

    # Some Seedr API variants expose the created folder only in task contents.
    if active and not folder_id:
        try:
            task_files = await task_contents(task_id_value)
            folder_id = (
                _seedr_effective_task_folder_id(task_value, task_files)
                or _seedr_file_folder_id(task_files)
            )
        except (HTTPException, SeedrError):
            task_files = []

    folder_size = 0
    for file in task_files:
        if not isinstance(file, dict):
            continue
        try:
            folder_size += max(0, int(float(file.get("size") or 0)))
        except (TypeError, ValueError):
            continue
    task_deleted = False
    if task_found:
        try:
            await seedr_request(f"/tasks/{quote(task_id_value, safe='')}", "DELETE")
            task_deleted = True
        except (HTTPException, SeedrError) as exc:
            status_code = getattr(exc, "status_code", 0)
            if status_code == 405:
                try:
                    await seedr_request(f"/tasks/{quote(task_id_value, safe='')}/delete", "POST")
                    task_deleted = True
                except (HTTPException, SeedrError) as fallback_exc:
                    if getattr(fallback_exc, "status_code", 0) != 404:
                        raise
            elif status_code != 404:
                raise

    folder_deleted = False
    if active and folder_id and folder_id != "0":
        # Seedr can remove the task before its partial folder is ready to be
        # deleted. Retry the folder DELETE with backoff instead of returning an
        # error that forces the user to click Prepare a second time.
        max_delete_attempts = 5
        last_delete_error: Exception | None = None
        for attempt in range(max_delete_attempts):
            try:
                await seedr_request(f"/fs/folder/{quote(folder_id, safe='')}", "DELETE")
                folder_deleted = True
                last_delete_error = None
                break
            except (HTTPException, SeedrError) as exc:
                status_code = getattr(exc, "status_code", 0)
                if status_code == 404:
                    # A previous attempt or Seedr's own task deletion already
                    # removed the transient folder.
                    folder_deleted = True
                    last_delete_error = None
                    break

                last_delete_error = exc
                if attempt + 1 < max_delete_attempts:
                    delay = min(0.75 * (2 ** attempt), 4.0)
                    logger.warning(
                        "Seedr partial-folder delete retry task=%s folder=%s attempt=%s/%s delay_seconds=%.2f status=%s detail=%s",
                        task_id_value,
                        folder_id,
                        attempt + 1,
                        max_delete_attempts,
                        delay,
                        status_code,
                        getattr(exc, "detail", str(exc)),
                    )
                    await asyncio.sleep(delay)

        if not folder_deleted:
            # Do not abort the new Prepare solely because the partial-folder
            # deletion endpoint briefly failed. The old task has already been
            # cancelled; continue to quota cleanup and the requested add, which
            # will trigger the existing storage-recovery retry if necessary.
            logger.error(
                "Seedr partial-folder deletion did not confirm success after retries; continuing with new add task=%s folder=%s status=%s detail=%s",
                task_id_value,
                folder_id,
                getattr(last_delete_error, "status_code", 0),
                getattr(last_delete_error, "detail", str(last_delete_error)),
            )

    _seedr_cleanup_jobs.pop(task_id_value, None)
    _seedr_torrent_names_by_task.pop(task_id_value, None)
    if folder_id:
        _seedr_torrent_names.pop(folder_id, None)
        _seedr_folder_cache.pop(folder_id, None)
    _save_seedr_cleanup_jobs()
    _seedr_metadata_cache = None
    _seedr_folder_cache.clear()

    return {
        "taskId": task_id_value,
        "name": task_name,
        "found": task_found,
        "active": active,
        "completed": complete,
        "taskDeleted": task_deleted,
        "folderId": folder_id,
        "folderDeleted": folder_deleted,
        "size": folder_size,
    }


async def _cancel_active_seedr_tasks_for_replacement(
    replace_task_id: str = "",
) -> list[dict[str, Any]]:
    """Cancel all unfinished tasks in the connected Seedr account before a new torrent is added."""
    explicit_id = str(replace_task_id or "").strip()
    tracked_ids = {str(task_id_value).strip() for task_id_value in _seedr_cleanup_jobs}
    tracked_ids.discard("")

    try:
        payload = seedr_data(await seedr_request("/tasks"))
    except (HTTPException, SeedrError) as exc:
        logger.warning("Could not list Seedr tasks before replacement: %s", getattr(exc, "detail", str(exc)))
        raise SeedrError(
            "SEEDR_TASK_LIST_FAILED",
            503,
            "Could not check the current Seedr download before replacing it. Please retry.",
        ) from exc

    cancelled: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_task in arr(payload, ("tasks", "torrents", "items")):
        task = unwrap_seedr_task(seedr_data(raw_task))
        if not task:
            continue
        task_id_value = task_id(task)
        if task_id_value:
            seen_ids.add(task_id_value)
        if not task_id_value or task_complete(task):
            continue
        if task_id_value in {str(item.get("taskId") or "") for item in cancelled}:
            continue

        result = await _cancel_seedr_task_and_partial_folder(task_id_value, task)
        if result.get("active"):
            cancelled.append(result)

    # A tracked or explicitly selected task may be temporarily absent from the
    # list endpoint. Check those IDs directly so stale Seedr tasks do not survive
    # simply because the backend restarted or /tasks omitted a row.
    fallback_ids = tracked_ids | ({explicit_id} if explicit_id else set())
    for task_id_value in sorted(fallback_ids - seen_ids):
        try:
            result = await _cancel_seedr_task_and_partial_folder(task_id_value)
        except (HTTPException, SeedrError) as exc:
            logger.warning(
                "Seedr replacement could not cancel stale task=%s: %s",
                task_id_value,
                getattr(exc, "detail", str(exc)),
            )
            raise
        if result.get("active"):
            cancelled.append(result)

    if cancelled:
        logger.info(
            "Seedr replacement cancelled %s unfinished task(s): %s",
            len(cancelled),
            ",".join(str(item.get("taskId") or "") for item in cancelled),
        )
    else:
        logger.info("Seedr replacement found no unfinished Seedr tasks")
    return cancelled


@app.delete("/api/seedr/tasks/{tid}")
async def seedr_task_delete(tid: str):
    if not current_seedr_token():
        raise HTTPException(503, "Seedr is not configured")
    return await _cancel_seedr_task_and_partial_folder(tid)

@app.delete("/api/seedr/files/{file_id}")
async def seedr_file_delete(file_id: str):
    global _seedr_metadata_cache
    result = await seedr_request(f"/fs/file/{quote(file_id)}", "DELETE")
    _seedr_metadata_cache = None
    _seedr_folder_cache.clear()
    return result

@app.delete("/api/seedr/folders/{folder_id}")
async def seedr_folder_delete(folder_id: str):
    global _seedr_metadata_cache
    result = await seedr_request(f"/fs/folder/{quote(folder_id)}", "DELETE")
    _seedr_metadata_cache = None
    _seedr_folder_cache.clear()
    return result
app.include_router(torrent_metadata_router)



@app.get("/api/v2/torrents/files")
async def empty_torrent_files(hash: str):
    return []

@app.post("/api/v2/torrents/pause")
async def noop_pause(body: dict[str, Any]):
    return {}

@app.post("/api/v2/torrents/resume")
async def noop_resume(body: dict[str, Any]):
    return {}

@app.post("/api/v2/torrents/delete")
async def noop_delete(body: dict[str, Any]):
    return {}

@app.post("/api/v2/torrents/filePrio")
async def noop_prio(body: dict[str, Any]):
    return {}

@app.get("/api/files")
async def files_compat(
    folder: str = "/",
    search: str = "",
    type: str = "all",
    folder_id: str = "",
):
    # Only load files for the folder currently open in the UI. Folder metadata
    # is returned separately by /api/folders.
    target_id = folder_id.strip()
    if not target_id:
        target_id = "0" if folder in {"/", "/Torrent Studio"} else ""

    if not target_id.isdigit():
        metadata = await get_seedr_metadata_tree()
        for item in metadata.get("folders", []) if isinstance(metadata, dict) else []:
            if str(item.get("path") or "") == folder:
                target_id = str(item.get("id") or "")
                break

    if not target_id.isdigit():
        return []

    payload = await seedr_folder_payload(target_id)
    result = []
    for raw in arr(payload, ("files", "items")):
        f = normalize_file(raw, target_id)
        name = f["name"]
        if search and search.lower() not in name.lower():
            continue

        lower = name.lower()
        if type != "all":
            if type == "video" and not re.search(r"\.(mkv|mp4|m4v|webm|avi|mov|m3u8|ts)$", lower):
                continue
            if type == "audio" and not re.search(r"\.(mp3|wav|flac|aac|ogg|m4a)$", lower):
                continue
            if type == "document" and not re.search(r"\.(pdf|txt|doc|docx|xls|xlsx|ppt|pptx|csv)$", lower):
                continue
            if type == "archive" and not re.search(r"\.(zip|rar|7z|tar|gz|bz2)$", lower):
                continue

        folder_path = folder if folder not in {"", "/"} else "/Torrent Studio"
        result.append({
            "id": f["id"],
            "name": name,
            "path": folder_path.rstrip("/") + "/" + name,
            "folder": folder_path,
            "size": f["size"],
            "type": "video" if re.search(r"\.(mp4|mkv|webm|avi|mov|m4v|m3u8|ts)$", lower) else "other",
            "mimeType": "video/mp4" if re.search(r"\.mp4$", lower) else "application/octet-stream",
            "createdAt": 0,
            "isStreamable": bool(re.search(r"\.(mp4|mkv|webm|avi|mov|m3u8|ts|mp3|m4a|flac|aac|ogg)$", lower)),
            "ownerId": "seedr",
            "ownerName": "Seedr",
            "downloadUrl": f"/api/seedr/files/{f['id']}/download",
            "streamUrl": "",
        })
    return result


@app.get("/api/folders")
async def folders_compat():
    metadata = await get_seedr_metadata_tree()
    return [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or "Folder"),
            "path": str(item.get("path") or "/"),
            "ownerId": "seedr",
            "ownerName": "Seedr",
            "isShared": False,
            "permissions": {},
            "createdAt": 0,
            "filesCount": int(item.get("filesCount") or 0),
            "totalSize": int(item.get("totalSize") or 0),
        }
        for item in metadata.get("folders", [])
    ] if isinstance(metadata, dict) else []

@app.get("/api/storage/stats")
async def storage_stats():
    q = await seedr_quota()
    metadata = await get_seedr_metadata_tree()
    root = metadata.get("root") if isinstance(metadata, dict) else {}
    used = int(q.get("usedSpace") or 0)
    total = int(q.get("maxSpace") or 0)
    pct = (used / total * 100) if total else 0
    return {
        "totalBytes": total,
        "usedBytes": used,
        "freeBytes": max(0, total-used),
        "usedPercentage": pct,
        "filesCount": int((root or {}).get("filesCount") or 0),
        "torrentsCount": 0,
        "isUnlimited": False,
        "serverCapacityLabel": "Seedr cloud storage",
        "alertLevel": "critical" if pct > 90 else "warning" if pct > 80 else "normal",
    }

@app.get("/api/users")
async def users():
    user = {"id": "seedr-user", "name": "Seedr User", "email": "", "role": "admin", "avatar": ""}
    return {"users": [user], "activeUserId": user["id"], "activeUser": user}

@app.get("/api/logs")
async def logs():
    return []

@app.post("/api/logs/clear")
async def clear_logs():
    return {}

@app.get("/api/notifications")
async def notifications():
    return []

@app.post("/api/notifications/read")
async def notifications_read():
    return {}

@app.post("/api/notifications/test")
async def notifications_test():
    return {}

@app.get("/api/cleanup/settings")
async def cleanup_settings():
    return {"autoCleanCompletedDays": 7, "autoPurgeOrphans": False, "autoCleanTempFiles": False, "storageThresholdPercent": 80}

@app.post("/api/cleanup/settings")
async def update_cleanup_settings(body: dict[str, Any]):
    return body

@app.post("/api/cleanup/run")
async def run_cleanup():
    return {"bytesFreed": 0, "filesRemoved": 0, "tempRemoved": 0, "orphansRemoved": 0}
app.include_router(feedback_router)


@app.get("/api/qbt/settings")
async def qbt_settings():
    return {"isExternal": False, "host": "", "username": "", "connected": False, "version": "Seedr backend"}

@app.post("/api/qbt/settings")
async def update_qbt_settings(body: dict[str, Any]):
    return {"isExternal": False, "host": "", "username": "", "connected": False, "version": "Seedr backend"}

@app.post("/api/files/delete")
async def delete_file_compat(body: dict[str, Any]):
    return await seedr_file_delete(str(body.get("id") or ""))

@app.post("/api/files/rename")
async def rename_file_compat(body: dict[str, Any]):
    raise HTTPException(501, "Rename is not exposed by this Seedr API deployment")

@app.post("/api/files/move")
async def move_file_compat(body: dict[str, Any]):
    raise HTTPException(501, "Move is not exposed by this Seedr API deployment")

@app.post("/api/files/folder")
async def create_folder_compat(body: dict[str, Any]):
    raise HTTPException(501, "Folder creation is not exposed by this Seedr API deployment")

@app.post("/api/folders/share")
async def share_folder_compat(body: dict[str, Any]):
    raise HTTPException(501, "Sharing is not provided by Seedr")

@app.post("/api/users/switch")
async def switch_user(body: dict[str, Any]):
    return {"activeUser": {"id": "seedr-user", "name": "Seedr User", "email": "", "role": "admin", "avatar": ""}}

@app.post("/api/users/create")
async def create_user(body: dict[str, Any]):
    raise HTTPException(501, "Multi-user accounts are not provided by this deployment")

@app.get("/api/search/torrents/add")
async def search_add_info():
    return JSONResponse({"added": False, "reason": "Use the Seedr magnet action"}, status_code=405)

@app.post("/api/search/torrents/add")
async def search_torrent_add(body: dict[str, Any]):
    source = str(body.get("source") or "")
    magnet = source if source.lower().startswith("magnet:") else ""
    if not magnet and body.get("infoHash"):
        magnet = "magnet:?xt=urn:btih:" + str(body["infoHash"])
    if not magnet:
        return {"added": False, "reason": "no_magnet_or_info_hash"}
    result = await seedr_add(
        MagnetRequest(
            magnet=magnet,
            torrent_name=str(body.get("torrent_name") or "").strip() or None,
        )
    )
    return {"added": True, **result}

# Dedicated episode lookup for the standalone Marvel scanner. Reuse Home's
# existing multi-provider search pipeline rather than scraping 1337x directly.
@app.get("/api/search/episode")
async def search_episode_release(
    title: str = Query(..., min_length=1, max_length=180),
    season: int = Query(..., ge=1, le=99),
    episode: int = Query(..., ge=1, le=999),
):
    query = f"{title.strip()} S{season:02d}E{episode:02d}"
    try:
        candidates = await _search_1337x_uncached(query, allow_series_fallback=False)
    except Exception as exc:
        logger.warning("Episode release search failed for %r: %s", query, exc)
        raise HTTPException(status_code=502, detail="Episode release search temporarily failed")

    token = re.compile(rf"(?i)(?<![A-Z0-9])S{season:02d}E{episode:02d}(?![0-9])")
    rejected_pack = re.compile(r"(?i)\b(complete series|season pack|all seasons|complete season)\b")
    results = []
    seen = set()
    for item in candidates if isinstance(candidates, list) else []:
        name = str(item.get("title") or "").strip()
        if not name or not token.search(name) or rejected_pack.search(name):
            continue
        link = str(item.get("url") or item.get("detailUrl") or item.get("magnet") or "").strip()
        identity = link or name.casefold()
        if identity in seen:
            continue
        seen.add(identity)
        results.append({
            "title": name,
            "url": link,
            "episode": f"S{season:02d}E{episode:02d}",
            "provider": str(item.get("indexer") or item.get("provider") or ""),
            "seeders": item.get("seeders"),
            "size": item.get("size"),
            "infoHash": item.get("infoHash") or item.get("info_hash"),
            "magnet": item.get("magnet") or item.get("magnetUrl"),
        })
        if len(results) >= 8:
            break
    return {
        "status": "found" if results else "not_found",
        "query": query,
        "results": results,
        "providers": sorted({item["provider"] for item in results if item["provider"]}),
    }
