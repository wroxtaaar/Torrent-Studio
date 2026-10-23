"""Moved out of main.py (see docs/main-split-plan.md)."""

import json
import os
import re
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Query, Request

from core.cache_diagnostics import (
    _CACHE_DIAGNOSTICS,
    _CACHE_DIAGNOSTICS_STARTED_AT,
    _InstrumentedAsyncClient,
    _record_cache_event,
)
from catalogues.catalogues_extra import (
    MARVEL_CATALOGUE_PATH,
    _CACHE_SEED_FILES,
    _EXTRA_CATALOGUE_PATHS,
    _RUNTIME_CACHE_SEED_FILES,
    _TMDB_CATALOGUE_SYNOPSIS_ENRICHMENT_STATE,
)
from search.search_providers import LIMETORRENTS_HOSTS, X1337_HOSTS
from seedr.seedr_client import info_hash
from seedr.seedr_session import current_seedr_token
from core.settings import (
    APP_NAME,
    CACHE_ONLY_MODE,
    DATA_DIR,
    DEBUG_ENDPOINTS_ENABLED,
    MAX_SEARCH_RESULT_SIZE_BYTES,
    MIN_SEARCH_RESULT_SIZE_BYTES,
    REGIONAL_MOVIE_PREBUILT_CACHE_PATH,
    REGIONAL_TV_PREBUILT_CACHE_FILE,
    TORRENT_METADATA_CACHE_FILE,
    TORRENT_SEARCH_API_URL,
    _CACHE_SEED_DIR,
    data_file,
    logger,
)

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "seedrConfigured": bool(current_seedr_token()), "torrentSearchApi": TORRENT_SEARCH_API_URL}

@router.post("/api/search/resolve-magnet")
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


@router.get("/api/movies/catalogue-cache/synopsis-enrichment")
async def api_tmdb_catalogue_synopsis_enrichment_status():
    """Return progress for TMDB synopsis enrichment in the persistent catalogue JSON."""
    return dict(_TMDB_CATALOGUE_SYNOPSIS_ENRICHMENT_STATE)


@router.get("/api/regional-movies/prebuilt")
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


@router.get("/api/cache/report")
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
        os.getenv("MARVEL_WEB_SERIES_CATALOGUE_PATH", data_file("marvel_web_series_catalogue.json"))
    )
    runtime_paths["bollywood_torrent_matched_catalogue.json"] = Path(
        os.getenv("BOLLYWOOD_TORRENT_CATALOGUE_PATH", str(Path(str(DATA_DIR)) / "bollywood_torrent_matched_catalogue.json"))
    )
    runtime_paths["torrent_metadata_cache"] = TORRENT_METADATA_CACHE_FILE
    runtime_paths["regional_tv_prebuilt_cache.json"] = REGIONAL_TV_PREBUILT_CACHE_FILE
    runtime_paths["regional_movie_prebuilt_cache.json"] = REGIONAL_MOVIE_PREBUILT_CACHE_PATH
    runtime_paths["classics_web_series_tv_catalogue.json"] = Path(str(DATA_DIR)) / "classics_web_series_tv_catalogue.json"
    runtime_paths["classics_anime_tv_catalogue.json"] = Path(str(DATA_DIR)) / "classics_anime_tv_catalogue.json"
    runtime_paths["nexstream_cache.json"] = Path(os.getenv("NEXSTREAM_CACHE_PATH", data_file("nexstream_cache.json")))
    runtime_paths["nexstream_episode_metadata_cache.json"] = Path(os.getenv("NEXSTREAM_EPISODE_CACHE_PATH", data_file("nexstream_episode_metadata_cache.json")))
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


@router.get("/api/health")
async def api_health():
    return {"name": APP_NAME, "status": "ok"}
