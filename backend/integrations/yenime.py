import json
import logging
import os
import re
import tempfile
import threading
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Query

from core.cache_diagnostics import _InstrumentedAsyncClient
from core.settings import CACHE_ONLY_MODE, data_file, log_cache_only_metadata_block

router = APIRouter()
ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"
logger = logging.getLogger("torrent-studio")
_MAL_CACHE: dict[tuple[str, int | None], tuple[float, dict]] = {}
_MAL_CACHE_SECONDS = 30 * 24 * 3600
_MAL_NEGATIVE_CACHE_SECONDS = 60 * 60
_MAL_NETWORK_CACHE_SECONDS = 60
_MAL_CACHE_PATH = Path(os.getenv("YENIME_MAL_CACHE_PATH", data_file("yenime_mal_resolution_cache.json")))
_MAL_CACHE_LOCK = threading.Lock()
_ANILIST_COOLDOWN_UNTIL = 0.0
KNOWN_MAL_IDS = {
    "fullmetal alchemist brotherhood": 5114,
}


def valid_mal_id(value) -> bool:
    try:
        return isinstance(value, (int, str)) and str(value).strip().isdigit() and int(value) > 0
    except (TypeError, ValueError):
        return False


def valid_episode(value) -> bool:
    try:
        return isinstance(value, (int, str)) and str(value).strip().isdigit() and int(value) > 0
    except (TypeError, ValueError):
        return False


def build_yenime_url(mal_id, episode, stream_type="sub"):
    if not valid_mal_id(mal_id):
        raise ValueError("A positive MAL ID is required")
    if not valid_episode(episode):
        raise ValueError("A positive episode number is required")
    stream_type = str(stream_type) if stream_type is not None else ""
    if stream_type not in ("sub", "dub"):
        raise ValueError("Stream type must be sub or dub")
    base_url = f"https://player.yenime.net/anime/mal/{int(mal_id)}/{int(episode)}"
    return f"{base_url}?dub=1" if stream_type == "dub" else base_url


def normalize_anime_title(value) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def resolve_mal_from_anilist_candidates(title: str, year: int | None, candidates: list[dict]) -> dict:
    target = normalize_anime_title(title)
    exact = []
    for row in candidates:
        if not isinstance(row, dict) or not row.get("idMal"):
            continue
        titles = row.get("title") or {}
        names = [titles.get("english"), titles.get("romaji"), titles.get("native")]
        names.extend(row.get("synonyms") or [])
        normalized_names = {normalize_anime_title(name) for name in names if name}
        if target not in normalized_names:
            continue
        candidate_year = ((row.get("startDate") or {}).get("year"))
        if year and candidate_year and int(candidate_year) != int(year):
            continue
        exact.append(row)

    if len(exact) == 1:
        row = exact[0]
        return {"status": "resolved", "malId": int(row["idMal"]), "source": "AniList", "title": (row.get("title") or {}).get("english") or (row.get("title") or {}).get("romaji")}
    if len(exact) > 1:
        return {
            "status": "ambiguous",
            "malId": None,
            "source": "AniList",
            "message": "Multiple anime matches were found. Enter the MAL ID manually.",
            "matches": [
                {"malId": int(row["idMal"]), "title": (row.get("title") or {}).get("english") or (row.get("title") or {}).get("romaji"), "year": (row.get("startDate") or {}).get("year")}
                for row in exact[:10]
            ],
        }
    return {"status": "missing", "malId": None, "source": "AniList", "message": "No confident MAL ID match was found. Enter the MAL ID manually."}


def _read_mal_cache_document() -> dict:
    try:
        payload = json.loads(_MAL_CACHE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"entries": {}, "cooldownUntil": 0.0}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read persistent MAL resolution cache %s: %s", _MAL_CACHE_PATH, exc)
        return {"entries": {}, "cooldownUntil": 0.0}
    if not isinstance(payload, dict) or not isinstance(payload.get("entries", {}), dict):
        logger.warning("Persistent MAL resolution cache has an invalid shape: %s", _MAL_CACHE_PATH)
        return {"entries": {}, "cooldownUntil": 0.0}
    return payload


def _write_mal_cache_document(payload: dict) -> None:
    _MAL_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=_MAL_CACHE_PATH.parent,
            prefix="yenime-mal-cache-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, _MAL_CACHE_PATH)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _mal_cache_key(title: str, year: int | None) -> tuple[str, int | None]:
    return normalize_anime_title(title), int(year) if year is not None else None


def _mal_persistent_key(cache_key: tuple[str, int | None]) -> str:
    normalized_title, year = cache_key
    return normalized_title + "|" + (str(year) if year is not None else "")


def _read_cached_mal_resolution(cache_key: tuple[str, int | None], now: float) -> dict | None:
    global _ANILIST_COOLDOWN_UNTIL
    memory_hit = _MAL_CACHE.get(cache_key)
    if memory_hit and memory_hit[0] > now:
        return memory_hit[1]
    with _MAL_CACHE_LOCK:
        document = _read_mal_cache_document()
    _ANILIST_COOLDOWN_UNTIL = max(
        _ANILIST_COOLDOWN_UNTIL,
        float(document.get("cooldownUntil") or 0),
    )
    entry = (document.get("entries") or {}).get(_mal_persistent_key(cache_key))
    if not isinstance(entry, dict):
        return None
    expires_at = float(entry.get("expiresAt") or 0)
    result = entry.get("result")
    if expires_at <= now or not isinstance(result, dict):
        return None
    _MAL_CACHE[cache_key] = (expires_at, result)
    return result


def _store_mal_resolution(
    cache_key: tuple[str, int | None],
    result: dict,
    *,
    ttl: float,
    cooldown_until: float | None = None,
) -> None:
    global _ANILIST_COOLDOWN_UNTIL
    now = time.time()
    _MAL_CACHE[cache_key] = (now + max(0.0, ttl), result)
    persistent_key = _mal_persistent_key(cache_key)
    with _MAL_CACHE_LOCK:
        document = _read_mal_cache_document()
        entries = document.setdefault("entries", {})
        document["entries"] = {
            key: value
            for key, value in entries.items()
            if isinstance(value, dict) and float(value.get("expiresAt") or 0) > now
        }
        document["entries"][persistent_key] = {
            "cachedAt": now,
            "expiresAt": now + max(0.0, ttl),
            "result": result,
        }
        if cooldown_until is not None:
            document["cooldownUntil"] = max(
                float(document.get("cooldownUntil") or 0),
                cooldown_until,
            )
            _ANILIST_COOLDOWN_UNTIL = max(_ANILIST_COOLDOWN_UNTIL, cooldown_until)
        try:
            _write_mal_cache_document(document)
        except OSError as exc:
            logger.warning("Could not persist MAL resolution cache %s: %s", _MAL_CACHE_PATH, exc)


def _anilist_retry_after(value: str | None) -> float:
    fallback = 60.0
    if not value:
        return fallback
    try:
        return max(1.0, min(3600.0, float(value)))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(1.0, min(3600.0, (retry_at - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return fallback


async def fetch_anilist_mal_resolution(title: str, year: int | None, timeout_seconds: float = 8.0) -> dict:
    known = KNOWN_MAL_IDS.get(normalize_anime_title(title))
    if known:
        return {"status": "resolved", "malId": known, "source": "catalogue", "title": title}

    cache_key = _mal_cache_key(title, year)
    now = time.time()
    cached = _read_cached_mal_resolution(cache_key, now)
    if cached is not None:
        return cached
    if CACHE_ONLY_MODE:
        log_cache_only_metadata_block("AniList")
        return {
            "status": "unavailable",
            "malId": None,
            "source": "AniList",
            "message": "Automatic MAL resolution is disabled because this deployment is cache-only. Enter the MAL ID manually.",
        }
    if now < _ANILIST_COOLDOWN_UNTIL:
        remaining = max(1.0, _ANILIST_COOLDOWN_UNTIL - now)
        result = {
            "status": "unavailable",
            "malId": None,
            "source": "AniList",
            "message": f"AniList is rate limiting requests. Retry in about {int(remaining)} seconds or enter the MAL ID manually.",
        }
        _store_mal_resolution(cache_key, result, ttl=remaining)
        return result

    query = """
    query($search: String) {
      Page(page: 1, perPage: 10) {
        media(search: $search, type: ANIME) {
          idMal
          synonyms
          title { romaji english native }
          startDate { year }
        }
      }
    }
    """
    try:
        async with _InstrumentedAsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            response = await client.post(ANILIST_GRAPHQL_URL, json={"query": query, "variables": {"search": title}}, headers={"Accept": "application/json", "User-Agent": "Torrent-Studio/1.0"})
        if response.status_code == 429:
            retry_seconds = _anilist_retry_after(response.headers.get("Retry-After"))
            cooldown_until = time.time() + retry_seconds
            result = {
                "status": "unavailable",
                "malId": None,
                "source": "AniList",
                "message": f"AniList is rate limiting requests. Retry in about {int(retry_seconds)} seconds or enter the MAL ID manually.",
            }
            _store_mal_resolution(
                cache_key,
                result,
                ttl=retry_seconds,
                cooldown_until=cooldown_until,
            )
            return result
        if response.status_code >= 500:
            result = {
                "status": "unavailable",
                "malId": None,
                "source": "AniList",
                "message": f"AniList is temporarily unavailable (HTTP {response.status_code}). Enter the MAL ID manually.",
            }
            _store_mal_resolution(cache_key, result, ttl=_MAL_NETWORK_CACHE_SECONDS)
            return result
        if response.status_code >= 400:
            result = {
                "status": "unavailable",
                "malId": None,
                "source": "AniList",
                "message": f"AniList rejected the lookup (HTTP {response.status_code}). Enter the MAL ID manually.",
            }
            _store_mal_resolution(cache_key, result, ttl=_MAL_NEGATIVE_CACHE_SECONDS)
            return result
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("errors"):
            result = {
                "status": "unavailable",
                "malId": None,
                "source": "AniList",
                "message": "AniList returned an invalid resolution response. Enter the MAL ID manually.",
            }
            _store_mal_resolution(cache_key, result, ttl=_MAL_NEGATIVE_CACHE_SECONDS)
            return result
        candidates = (((payload.get("data") or {}).get("Page") or {}).get("media") or [])
        result = resolve_mal_from_anilist_candidates(title, year, candidates)
        _store_mal_resolution(
            cache_key,
            result,
            ttl=_MAL_CACHE_SECONDS if result.get("status") == "resolved" else _MAL_NEGATIVE_CACHE_SECONDS,
        )
        return result
    except httpx.RequestError as exc:
        result = {
            "status": "unavailable",
            "malId": None,
            "source": "AniList",
            "message": f"AniList network request failed ({type(exc).__name__}). Enter the MAL ID manually.",
        }
        _store_mal_resolution(cache_key, result, ttl=_MAL_NETWORK_CACHE_SECONDS)
        return result
    except (ValueError, TypeError) as exc:
        logger.warning("Could not parse AniList MAL resolution for %s: %s", title, exc)
        result = {
            "status": "unavailable",
            "malId": None,
            "source": "AniList",
            "message": "AniList returned an invalid resolution response. Enter the MAL ID manually.",
        }
        _store_mal_resolution(cache_key, result, ttl=_MAL_NEGATIVE_CACHE_SECONDS)
        return result


@router.get("/api/yenime/resolve-mal")
async def resolve_mal_id(title: str = Query(..., min_length=1), year: int | None = Query(None, ge=1900, le=2100), mal_id: int | None = Query(None, ge=1, alias="malId")):
    if mal_id is not None:
        return {"status": "resolved", "malId": mal_id, "source": "catalogue", "title": title}
    return await fetch_anilist_mal_resolution(title, year)


@router.get("/api/yenime/resolve")
async def resolve_yenime(
    mal_id: int = Query(..., ge=1, alias="malId"),
    episode: int = Query(..., ge=1),
    stream_type: str = Query("sub", pattern="^(sub|dub)$", alias="type"),
):
    try:
        url = build_yenime_url(mal_id, episode, stream_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "url": url,
        "provider": "Yenime",
        "availability": "unverified",
        "availabilityVerified": False,
        "malId": mal_id,
        "episode": episode,
        "type": stream_type,
    }
