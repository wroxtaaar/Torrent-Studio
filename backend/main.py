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
    REGIONAL_MOVIE_PREBUILT_CACHE_PATH,
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

from imdb import _get_imdb_rating_record, router as imdb_router

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

from seedr_api import (
    get_seedr_metadata_tree,
    seedr_add,
    seedr_file_delete,
    seedr_folder_payload,
    seedr_quota,
    start_seedr_cleanup_worker,
    router as seedr_api_router,
)

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
app.include_router(seedr_api_router)

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
app.router.add_event_handler("startup", start_seedr_cleanup_worker)


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

from catalogues_movies import (
    _resolve_marvel_tmdb_movie_id,
    _start_regional_movie_catalogue_scheduler,
    _warm_extra_catalogues_on_startup,
    router as catalogues_movies_router,
)

from catalogues_tv import router as catalogues_tv_router
app.include_router(catalogues_tv_router)
app.include_router(catalogues_movies_router)


app.router.add_event_handler("startup", _warm_extra_catalogues_on_startup)


app.router.add_event_handler("startup", _start_regional_movie_catalogue_scheduler)

from search_metadata import router as search_metadata_router
app.include_router(search_metadata_router)


app.router.add_event_handler("startup", _warm_marvel_catalogue_on_startup)
app.include_router(imdb_router)


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
