"""Moved out of main.py (see docs/main-split-plan.md)."""

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException

from core.cache_diagnostics import _InstrumentedAsyncClient, _record_cache_event
from core.settings import (
    CACHE_ONLY_MODE,
    STREAMING_AVAILABILITY_API_BASE,
    STREAMING_AVAILABILITY_API_KEY,
    TMDB_API_BASE,
    TMDB_API_KEYS,
    TMDB_CATALOGUE_CACHE_FILE,
    TMDB_OTT_CACHE_FILE,
    TMDB_OTT_CACHE_SECONDS,
    TMDB_OTT_INCOMPLETE_CACHE_SECONDS,
    TMDB_OTT_MISSING_CACHE_SECONDS,
    TMDB_READ_ACCESS_TOKENS,
    WATCHMODE_API_BASE,
    WATCHMODE_API_KEYS,
    logger,
)

_PROVIDER_KEY_COOLDOWNS: dict[str, float] = {}
_PROVIDER_KEY_FAILURES: dict[str, int] = {}
_PROVIDER_KEY_CURSORS: dict[str, int] = {}
# Reuse metadata-provider connections and bound concurrent catalogue backfills.
_TMDB_HTTP_CLIENT: httpx.AsyncClient | None = None
_TMDB_REQUEST_SEMAPHORE = asyncio.Semaphore(4)
_WATCHMODE_HTTP_CLIENT: httpx.AsyncClient | None = None
_WATCHMODE_REQUEST_SEMAPHORE = asyncio.Semaphore(3)
_WATCHMODE_RATE_LIMITED_UNTIL = 0.0
_WATCHMODE_RESOLVED_TITLE_IDS: dict[int, int | None] = {}


def _provider_key_id(provider: str, key: str) -> str:
    return provider + ":" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _provider_key_available(provider: str, key: str) -> bool:
    return _PROVIDER_KEY_COOLDOWNS.get(_provider_key_id(provider, key), 0.0) <= time.time()


def _provider_key_failure(provider: str, key: str, seconds: float, reason: str) -> None:
    identity = _provider_key_id(provider, key)
    _PROVIDER_KEY_FAILURES[identity] = _PROVIDER_KEY_FAILURES.get(identity, 0) + 1
    _PROVIDER_KEY_COOLDOWNS[identity] = max(_PROVIDER_KEY_COOLDOWNS.get(identity, 0.0), time.time() + max(1.0, seconds))
    logger.warning("%s credential %s cooling down for %.0fs (%s; failures=%s)",
        provider, identity.rsplit(":", 1)[-1], max(1.0, seconds), reason, _PROVIDER_KEY_FAILURES[identity])


def _provider_key_success(provider: str, key: str) -> None:
    identity = _provider_key_id(provider, key)
    _PROVIDER_KEY_FAILURES.pop(identity, None)
    _PROVIDER_KEY_COOLDOWNS.pop(identity, None)


def _retry_after_seconds(response: httpx.Response, default: float = 60.0) -> float:
    try:
        return max(1.0, min(21600.0, float(str(response.headers.get("Retry-After") or "").strip())))
    except (TypeError, ValueError):
        return default


async def _watchmode_get(path: str, *, params: dict[str, Any] | None = None,
    timeout: httpx.Timeout | float = 10.0, auth_header: bool = True) -> httpx.Response | None:
    """Rotate keys when available, but honor Watchmode's shared rate-limit cooldown."""
    global _WATCHMODE_RATE_LIMITED_UNTIL
    if CACHE_ONLY_MODE or not WATCHMODE_API_KEYS:
        return None
    # Watchmode rate limits and monthly credits are plan/account governed. Once any
    # credential receives 429, pause all credentials in this process instead of
    # immediately retrying the same account through another key.
    if _WATCHMODE_RATE_LIMITED_UNTIL > time.time():
        logger.debug("Watchmode request skipped during shared rate-limit cooldown (%s)", path)
        return None
    provider = "watchmode"
    request_params = dict(params or {})
    start = _PROVIDER_KEY_CURSORS.get(provider, 0) % len(WATCHMODE_API_KEYS)
    ordered = WATCHMODE_API_KEYS[start:] + WATCHMODE_API_KEYS[:start]
    _PROVIDER_KEY_CURSORS[provider] = (start + 1) % len(WATCHMODE_API_KEYS)
    last_response = None
    transient_failed: list[str] = []
    eligible = 0

    async def attempt(key: str) -> tuple[httpx.Response | None, bool]:
        nonlocal last_response, eligible
        global _WATCHMODE_RATE_LIMITED_UNTIL
        if not _provider_key_available(provider, key):
            return None, False
        eligible += 1
        headers = {"Accept": "application/json"}
        query = dict(request_params)
        if auth_header:
            headers["X-API-Key"] = key
            query.pop("apiKey", None)
        else:
            query["apiKey"] = key
        try:
            global _WATCHMODE_HTTP_CLIENT
            if _WATCHMODE_HTTP_CLIENT is None or _WATCHMODE_HTTP_CLIENT.is_closed:
                _WATCHMODE_HTTP_CLIENT = _InstrumentedAsyncClient(
                    timeout=httpx.Timeout(10.0, connect=4.0),
                    follow_redirects=True,
                    headers={"Accept": "application/json"},
                    limits=httpx.Limits(
                        max_connections=6,
                        max_keepalive_connections=3,
                        keepalive_expiry=30.0,
                    ),
                )
            async with _WATCHMODE_REQUEST_SEMAPHORE:
                response = await _WATCHMODE_HTTP_CLIENT.get(
                    f"{WATCHMODE_API_BASE}{path}",
                    params=query,
                    headers=headers,
                    timeout=timeout,
                )
            last_response = response
            if response.status_code < 300:
                _provider_key_success(provider, key)
                return response, True
            if response.status_code == 429:
                # Watchmode documents plan-level request limits and account-level
                # quota. Treat 429 as a provider-wide cooldown, not a per-key issue.
                retry_after = _retry_after_seconds(response)
                _WATCHMODE_RATE_LIMITED_UNTIL = max(
                    _WATCHMODE_RATE_LIMITED_UNTIL, time.time() + retry_after
                )
                _provider_key_failure(provider, key, retry_after, "HTTP 429 (shared cooldown)")
                logger.warning(
                    "Watchmode shared cooldown activated for %.0fs on %s (limit=%s remaining=%s quota_used=%s)",
                    retry_after, path,
                    response.headers.get("X-RateLimit-Limit", "unknown"),
                    response.headers.get("X-RateLimit-Remaining", "unknown"),
                    response.headers.get("X-Account-Quota-Used", "unknown"),
                )
                return response, True
            if response.status_code == 401:
                _provider_key_failure(provider, key, 3600, "HTTP 401")
                return None, False
            if response.status_code == 403:
                # A plan/access restriction is not a transient credential failure.
                _provider_key_failure(provider, key, 3600, "HTTP 403")
                return response, True
            if response.status_code >= 500:
                transient_failed.append(key)
                return None, False
            return response, True
        except httpx.HTTPError as exc:
            logger.info("Watchmode transport failure for %s credential %s: %s",
                path, _provider_key_id(provider, key).rsplit(":", 1)[-1], type(exc).__name__)
            transient_failed.append(key)
            return None, False

    for key in ordered:
        response, terminal = await attempt(key)
        if response is not None and terminal:
            return response
    if transient_failed:
        await asyncio.sleep(0.75)
        retry_keys = list(dict.fromkeys(transient_failed))
        transient_failed.clear()
        for key in retry_keys:
            response, terminal = await attempt(key)
            if response is not None and terminal:
                return response
        # Transport failures and HTTP 5xx responses do not prove the key is invalid.
        # Keep the key eligible; explicit 401/403/429 responses have their own policy.
    if last_response is not None:
        return last_response
    if not eligible:
        logger.info("All Watchmode keys are cooling down for %s", path)
    return None
_tmdb_api_connect_failure_until = 0.0
_OMDB_HTTP_CLIENT: httpx.AsyncClient | None = None
_OMDB_REQUEST_SEMAPHORE = asyncio.Semaphore(4)
_OMDB_RATE_LIMITED_UNTIL = 0.0


def _omdb_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    """Shared OMDb HTTP client, created on first use (owned by this module)."""
    global _OMDB_HTTP_CLIENT
    if _OMDB_HTTP_CLIENT is None or _OMDB_HTTP_CLIENT.is_closed:
        _OMDB_HTTP_CLIENT = _InstrumentedAsyncClient(
            timeout=timeout,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=8,
                max_keepalive_connections=4,
                keepalive_expiry=30.0,
            ),
        )
    return _OMDB_HTTP_CLIENT


def _omdb_rate_limited_until() -> float:
    return _OMDB_RATE_LIMITED_UNTIL


def _omdb_rate_limit_for(seconds: float) -> None:
    global _OMDB_RATE_LIMITED_UNTIL
    _OMDB_RATE_LIMITED_UNTIL = time.time() + seconds


_tmdb_ott_cache: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}
_tmdb_ott_inflight: dict[tuple[int, str], asyncio.Task[dict[str, Any]]] = {}
_tmdb_movie_catalogue_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
_tmdb_movie_catalogue_inflight: dict[tuple[str, int], asyncio.Task[dict[str, Any]]] = {}
_tmdb_company_id_cache: dict[str, tuple[float, list[str]]] = {}
_tmdb_company_inflight: dict[str, asyncio.Task[list[str]]] = {}
_tmdb_cache_clear_last_at = 0.0


def _tmdb_cache_disk_key(cache_key: tuple[str, int]) -> str:
    return cache_key[0] + ":" + str(cache_key[1])


def _read_tmdb_persistent_cache(cache_key: tuple[str, int]) -> tuple[float, dict[str, Any]] | None:
    try:
        payload = json.loads(TMDB_CATALOGUE_CACHE_FILE.read_text(encoding="utf-8"))
        row = (payload.get("catalogues") or {}).get(_tmdb_cache_disk_key(cache_key))
        if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
            return None
        saved_at = float(row.get("savedAt") or 0)
        if saved_at <= 0:
            return None
        return saved_at, row["payload"]
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _write_tmdb_persistent_cache(cache_key: tuple[str, int], payload: dict[str, Any]) -> None:
    try:
        TMDB_CATALOGUE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            disk = json.loads(TMDB_CATALOGUE_CACHE_FILE.read_text(encoding="utf-8"))
            if not isinstance(disk, dict):
                disk = {}
        except (OSError, ValueError, TypeError):
            disk = {}
        catalogues = disk.get("catalogues")
        if not isinstance(catalogues, dict):
            catalogues = {}
        catalogues[_tmdb_cache_disk_key(cache_key)] = {
            "savedAt": time.time(),
            "payload": payload,
        }
        # Keep the file bounded if an unusual client requests many pages.
        if len(catalogues) > 300:
            ordered = sorted(
                catalogues.items(),
                key=lambda pair: float((pair[1] or {}).get("savedAt") or 0),
                reverse=True,
            )
            catalogues = dict(ordered[:300])
        disk["catalogues"] = catalogues
        temp_path = TMDB_CATALOGUE_CACHE_FILE.with_name(
            TMDB_CATALOGUE_CACHE_FILE.name + "." + uuid.uuid4().hex + ".tmp"
        )
        temp_path.write_text(json.dumps(disk, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_path, TMDB_CATALOGUE_CACHE_FILE)
    except (OSError, ValueError, TypeError) as exc:
        # Caching is best-effort; it must never turn a successful API response into a failure.
        logger.info("Could not write TMDB persistent cache: %s", exc)


def _tmdb_ott_disk_key(cache_key: tuple[int, str]) -> str:
    # Version the persistent key so deployments can deliberately refresh stale
    # provider listings without deleting the historical cache file by hand.
    return "v2:" + str(cache_key[0]) + ":" + cache_key[1]


def _tmdb_ott_ttl(payload: Any) -> float:
    """Providers found -> long cache; nothing found -> short cache so it self-heals."""
    if isinstance(payload, dict) and payload.get("incomplete"):
        # A provider (e.g. Streaming Availability) errored or hit its quota: retry soon.
        return TMDB_OTT_INCOMPLETE_CACHE_SECONDS
    if isinstance(payload, dict) and any(
        payload.get(key) for key in ("streamingProviders", "rentProviders", "buyProviders")
    ):
        return TMDB_OTT_CACHE_SECONDS
    return TMDB_OTT_MISSING_CACHE_SECONDS


def _read_tmdb_ott_persistent_cache(cache_key: tuple[int, str]) -> tuple[float, dict[str, Any]] | None:
    try:
        payload = json.loads(TMDB_OTT_CACHE_FILE.read_text(encoding="utf-8"))
        row = (payload.get("items") or {}).get(_tmdb_ott_disk_key(cache_key))
        if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
            return None
        saved_at = float(row.get("savedAt") or 0)
        if saved_at <= 0:
            return None
        return saved_at, row["payload"]
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _write_tmdb_ott_persistent_cache(cache_key: tuple[int, str], payload: dict[str, Any]) -> None:
    try:
        TMDB_OTT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            disk = json.loads(TMDB_OTT_CACHE_FILE.read_text(encoding="utf-8"))
            if not isinstance(disk, dict):
                disk = {}
        except (OSError, ValueError, TypeError):
            disk = {}
        items = disk.get("items")
        if not isinstance(items, dict):
            items = {}
        items[_tmdb_ott_disk_key(cache_key)] = {
            "savedAt": time.time(),
            "payload": payload,
        }
        # Keep every saved OTT lookup permanently. Evicting old entries would
        # cause repeat provider lookups when a previously viewed film is opened.
        disk["items"] = items
        temp_path = TMDB_OTT_CACHE_FILE.with_name(
            TMDB_OTT_CACHE_FILE.name + "." + uuid.uuid4().hex + ".tmp"
        )
        temp_path.write_text(json.dumps(disk, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_path, TMDB_OTT_CACHE_FILE)
    except (OSError, ValueError, TypeError) as exc:
        # A cache write failure must not hide otherwise usable availability data.
        logger.info("Could not write TMDB OTT cache: %s", exc)


def _tmdb_watch_provider_rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("provider_name") or "").strip()
        provider_id = item.get("provider_id")
        if not name:
            continue
        identity = str(provider_id if provider_id is not None else name.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        logo_path = str(item.get("logo_path") or "").strip()
        rows.append({
            "providerId": provider_id,
            "name": name,
            "logoUrl": "https://image.tmdb.org/t/p/w92" + logo_path if logo_path else "",
        })
    return rows


async def _resolve_watchmode_title_id(movie_id: int) -> int | None:
    """Resolve and memoize the native Watchmode title ID for a TMDB movie ID."""
    if movie_id in _WATCHMODE_RESOLVED_TITLE_IDS:
        return _WATCHMODE_RESOLVED_TITLE_IDS[movie_id]
    if not WATCHMODE_API_KEYS:
        return None
    try:
        response = await _watchmode_get(
            "/search/",
            params={"search_field": "tmdb_movie_id", "search_value": str(movie_id), "types": "movie"},
            timeout=httpx.Timeout(10.0, connect=4.0),
        )
        if response is None or response.status_code >= 400:
            status = response.status_code if response is not None else "no response"
            logger.info("Watchmode ID resolution failed for TMDB movie %s (%s)", movie_id, status)
            return None
        payload = response.json()
        results = payload.get("title_results") if isinstance(payload, dict) else None
        matches: set[int] = set()
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict):
                    continue
                try:
                    result_tmdb_id = int(item.get("tmdb_id") or 0)
                    watchmode_id = int(item.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                if (
                    result_tmdb_id == movie_id
                    and str(item.get("type") or "").casefold() == "movie"
                    and watchmode_id > 0
                ):
                    matches.add(watchmode_id)
        resolved = next(iter(matches)) if len(matches) == 1 else None
        _WATCHMODE_RESOLVED_TITLE_IDS[movie_id] = resolved
        if resolved is None:
            logger.info("Watchmode has no unambiguous native title ID for TMDB movie %s", movie_id)
        return resolved
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.info("Watchmode ID resolution failed for TMDB movie %s: %s", movie_id, type(exc).__name__)
        return None


async def _watchmode_movie_sources(movie_id: int, region: str) -> list[dict[str, Any]]:
    """Look up sources by TMDB ID, falling back to Watchmode's native title ID."""
    if not WATCHMODE_API_KEYS:
        return []
    try:
        response = await _watchmode_get(
            f"/title/movie-{movie_id}/sources/",
            params={"regions": region},
            timeout=httpx.Timeout(10.0, connect=4.0),
        )
        if response is None:
            return []
        if response.status_code < 400:
            payload = response.json()
            if not isinstance(payload, list):
                logger.info("Watchmode returned an unexpected source payload for TMDB movie %s", movie_id)
                return []
            rows = [item for item in payload if isinstance(item, dict)]
            if rows:
                return rows
            # A valid empty response can mean the TMDB-formatted ID did not map
            # to a Watchmode record. Resolve the native ID before concluding empty.
        elif response.status_code != 404:
            logger.info("Watchmode source lookup failed for TMDB movie %s (%s)", movie_id, response.status_code)
            return []

        watchmode_id = await _resolve_watchmode_title_id(movie_id)
        if watchmode_id is None:
            return []
        fallback = await _watchmode_get(
            f"/title/{watchmode_id}/sources/",
            params={"regions": region},
            timeout=httpx.Timeout(10.0, connect=4.0),
        )
        if fallback is None or fallback.status_code >= 400:
            status = fallback.status_code if fallback is not None else "no response"
            logger.info("Watchmode native-ID source lookup failed for TMDB movie %s (%s)", movie_id, status)
            return []
        payload = fallback.json()
        if not isinstance(payload, list):
            logger.info("Watchmode returned an unexpected native-ID source payload for TMDB movie %s", movie_id)
            return []
        return [item for item in payload if isinstance(item, dict)]
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.info("Watchmode source lookup failed for movie %s in %s: %s", movie_id, region, type(exc).__name__)
        return []


def _watchmode_provider_rows(rows: list[dict[str, Any]], accepted_types: set[str]) -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        name = str(item.get("name") or item.get("source_name") or "").strip()
        kind = str(item.get("type") or item.get("source_type") or "").strip().lower()
        if not name or kind not in accepted_types:
            continue
        provider_id = item.get("source_id", item.get("id"))
        identity = str(provider_id if provider_id is not None else name.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        logo = str(item.get("logo_url") or item.get("logo") or "").strip()
        providers.append({
            "providerId": provider_id,
            "name": name,
            "logoUrl": logo,
            "webUrl": str(item.get("web_url") or item.get("url") or "").strip(),
        })
    return providers


async def _streaming_availability_movie_sources(movie_id: int, region: str) -> tuple[list[dict[str, Any]], bool]:
    """Return normalized provider rows and whether the lookup failed."""
    if not STREAMING_AVAILABILITY_API_KEY:
        return [], False
    try:
        async with _InstrumentedAsyncClient(
            timeout=httpx.Timeout(10.0, connect=4.0),
            follow_redirects=True,
            headers={"Accept": "application/json", "X-API-Key": STREAMING_AVAILABILITY_API_KEY},
        ) as client:
            response = await client.get(
                f"{STREAMING_AVAILABILITY_API_BASE}/shows/movie/{movie_id}",
                params={"country": region.lower(), "series_granularity": "show"},
            )
        if response.status_code >= 300:
            logger.info("Streaming Availability API returned HTTP %s for movie %s", response.status_code, movie_id)
            return [], True
        payload = response.json()
        if not isinstance(payload, dict):
            return [], True
        options_by_country = payload.get("streamingOptions")
        if not isinstance(options_by_country, dict):
            return [], True
        options = options_by_country.get(region.lower()) or []
        if not isinstance(options, list):
            return [], True
        normalized: list[dict[str, Any]] = []
        for option in options:
            if not isinstance(option, dict):
                continue
            service = option.get("service") if isinstance(option.get("service"), dict) else {}
            name = str(service.get("name") or "").strip()
            if not name:
                continue
            kind = str(option.get("type") or "").lower()
            if kind not in {"subscription", "free", "addon", "rent", "buy"}:
                continue
            images = service.get("imageSet") if isinstance(service.get("imageSet"), dict) else {}
            normalized.append({
                "providerId": service.get("id") or name.casefold(),
                "name": name,
                "logoUrl": str(images.get("darkThemeImage") or images.get("lightThemeImage") or ""),
                "webUrl": str(option.get("link") or service.get("homePage") or "").strip(),
                "type": kind,
            })
        return normalized, False
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.info("Streaming Availability API lookup failed for movie %s: %s", movie_id, type(exc).__name__)
        return [], True


def _streaming_availability_provider_rows(rows: list[dict[str, Any]], accepted_types: set[str]) -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        if str(item.get("type") or "").lower() not in accepted_types:
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        identity = str(item.get("providerId") or name.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        providers.append({
            "providerId": item.get("providerId"),
            "name": name,
            "logoUrl": str(item.get("logoUrl") or ""),
            "webUrl": str(item.get("webUrl") or ""),
        })
    return providers


async def _tmdb_fetch_movie_ott_availability(movie_id: int, region: str) -> dict[str, Any]:
    # Render serves OTT availability from the bundled/persistent cache only.
    # Never spend provider API quota refreshing streaming information at runtime.
    if CACHE_ONLY_MODE:
        cached = _tmdb_ott_cache.get((movie_id, region.upper()))
        if cached and isinstance(cached[1], dict):
            _record_cache_event("ott", "cache_only_memory_hit")
            return cached[1]
        persistent = _read_tmdb_ott_persistent_cache((movie_id, region.upper()))
        if persistent and isinstance(persistent[1], dict):
            _record_cache_event("ott", "cache_only_persistent_hit")
            return persistent[1]
        _record_cache_event("ott", "cache_only_miss_blocked")
        raise HTTPException(
            status_code=503,
            detail="OTT availability is not present in the local cache; live provider lookups are disabled.",
        )

    _record_cache_event("ott", "live_provider_lookup")
    # Prefer Watchmode for legal platform availability when configured. Keep TMDB
    # as a fallback and as the source of regional release-date metadata.
    watchmode_rows, release_result = await asyncio.gather(
        _watchmode_movie_sources(movie_id, region),
        _tmdb_get_json(f"movie/{movie_id}/release_dates"),
        return_exceptions=True,
    )
    if isinstance(watchmode_rows, Exception):
        watchmode_rows = []
    if isinstance(release_result, Exception):
        logger.info("Could not load digital release dates for TMDB movie %s: %s", movie_id, release_result)
        release_payload: dict[str, Any] = {}
    else:
        release_payload = release_result if isinstance(release_result, dict) else {}

    watchmode_streaming = _watchmode_provider_rows(watchmode_rows, {"sub", "free", "ads", "tve", "subscription"})
    watchmode_rent = _watchmode_provider_rows(watchmode_rows, {"rent", "rental"})
    watchmode_buy = _watchmode_provider_rows(watchmode_rows, {"buy", "purchase"})

    availability_rows: list[dict[str, Any]] = []
    availability_failed = False
    if not (watchmode_streaming or watchmode_rent or watchmode_buy):
        availability_rows, availability_failed = await _streaming_availability_movie_sources(movie_id, region)
    availability_streaming = _streaming_availability_provider_rows(availability_rows, {"subscription", "free", "addon"})
    availability_rent = _streaming_availability_provider_rows(availability_rows, {"rent"})
    availability_buy = _streaming_availability_provider_rows(availability_rows, {"buy"})

    # TMDB/JustWatch is the final fallback when neither Watchmode nor Streaming Availability has providers.
    tmdb_provider_result: dict[str, Any] = {}
    tmdb_provider_lookup_failed = False
    if not (watchmode_streaming or watchmode_rent or watchmode_buy or availability_streaming or availability_rent or availability_buy):
        try:
            result = await _tmdb_get_json(f"movie/{movie_id}/watch/providers")
            if isinstance(result, dict):
                tmdb_provider_result = result
            else:
                tmdb_provider_lookup_failed = True
        except Exception as exc:
            tmdb_provider_lookup_failed = True
            logger.info("TMDB provider fallback failed for movie %s: %s", movie_id, exc)

    # Don't cache provider outages as an empty availability result.
    if tmdb_provider_lookup_failed and availability_failed and not (watchmode_streaming or watchmode_rent or watchmode_buy):
        raise HTTPException(status_code=503, detail="Streaming availability could not be verified because the availability providers are temporarily unavailable.")
    if tmdb_provider_lookup_failed and not (watchmode_streaming or watchmode_rent or watchmode_buy or availability_streaming or availability_rent or availability_buy):
        raise HTTPException(status_code=503, detail="Streaming availability could not be verified because Watchmode and TMDB fallback are temporarily unavailable.")

    all_regions = (tmdb_provider_result.get("results") or {}) if isinstance(tmdb_provider_result, dict) else {}
    region_payload = all_regions.get(region) or {}
    streaming = watchmode_streaming or availability_streaming or (
        _tmdb_watch_provider_rows(region_payload.get("flatrate"))
        + _tmdb_watch_provider_rows(region_payload.get("free"))
        + _tmdb_watch_provider_rows(region_payload.get("ads"))
    )
    rent = watchmode_rent or availability_rent or _tmdb_watch_provider_rows(region_payload.get("rent"))
    buy = watchmode_buy or availability_buy or _tmdb_watch_provider_rows(region_payload.get("buy"))
    availability_source = (
        "Watchmode" if watchmode_streaming or watchmode_rent or watchmode_buy
        else "Streaming Availability API" if availability_streaming or availability_rent or availability_buy
        else "TMDB"
    )

    def merge_providers(groups: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for group in groups:
            for provider in group:
                identity = str(provider.get("providerId") or provider.get("name", "").casefold())
                if identity not in seen:
                    seen.add(identity)
                    merged.append(provider)
        return merged

    streaming = merge_providers([streaming])
    rent = merge_providers([rent])
    buy = merge_providers([buy])

    digital_dates: list[str] = []
    theatrical_dates: list[str] = []
    for region_release in release_payload.get("results") or []:
        if not isinstance(region_release, dict) or str(region_release.get("iso_3166_1") or "").upper() != region:
            continue
        for release in region_release.get("release_dates") or []:
            if not isinstance(release, dict):
                continue
            release_type = str(release.get("type") or "")
            if release_type not in {"2", "3", "4"}:
                continue
            day = str(release.get("release_date") or "").strip()[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                try:
                    datetime.strptime(day, "%Y-%m-%d")
                    if release_type == "4":
                        digital_dates.append(day)
                    else:
                        # Types 2 and 3 are limited and wide theatrical releases.
                        theatrical_dates.append(day)
                except ValueError:
                    continue

    digital_release_date = min(digital_dates) if digital_dates else None
    theatrical_release_date = min(theatrical_dates) if theatrical_dates else None
    today = datetime.now(timezone.utc).date().isoformat()
    if streaming:
        status = "streaming"
    elif rent or buy:
        status = "rent_buy"
    elif digital_release_date and digital_release_date > today:
        status = "digital_scheduled"
    elif digital_release_date:
        # A listed digital release date does not guarantee subscription streaming.
        status = "digital_release_known"
    else:
        status = "not_confirmed"

    provider_link = str(region_payload.get("link") or "").strip()
    if not provider_link:
        provider_link = f"https://www.themoviedb.org/movie/{movie_id}/watch?locale={region}"

    return {
        "movieId": movie_id,
        "region": region,
        "status": status,
        "streamingProviders": streaming,
        "rentProviders": rent,
        "buyProviders": buy,
        "theatricalReleaseDate": theatrical_release_date,
        "digitalReleaseDate": digital_release_date,
        "providerLink": provider_link,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        # True when no providers were found AND an upstream lookup failed, so "nothing
        # found" may just be a provider error/quota; it is re-checked within minutes.
        "incomplete": bool(
            not (streaming or rent or buy) and (availability_failed or tmdb_provider_lookup_failed)
        ),
        "source": availability_source,
        "providerAttribution": ("Streaming availability data powered by Watchmode." if availability_source == "Watchmode" else "Streaming availability data powered by Streaming Availability API." if availability_source == "Streaming Availability API" else "Streaming availability data powered by JustWatch via TMDB."),
        "attribution": "This product uses the TMDB API but is not endorsed or certified by TMDB.",
    }

async def _tmdb_get_json(path: str, params: dict[str, Any] | None = None, *, request_timeout: float = 12.0) -> dict[str, Any]:
    if CACHE_ONLY_MODE:
        raise HTTPException(status_code=503, detail="Cache-only mode: live TMDB lookups are disabled.")
    credentials = [("bearer", token) for token in TMDB_READ_ACCESS_TOKENS] + [("api_key", key) for key in TMDB_API_KEYS]
    if not credentials:
        raise HTTPException(status_code=503, detail="TMDB credentials are not configured. Set TMDB_API_KEYS and/or TMDB_READ_ACCESS_TOKENS.")
    provider = "tmdb"
    start = _PROVIDER_KEY_CURSORS.get(provider, 0) % len(credentials)
    ordered = credentials[start:] + credentials[:start]
    _PROVIDER_KEY_CURSORS[provider] = (start + 1) % len(credentials)
    query = dict(params or {})
    last_response = None
    transient_failed: list[tuple[str, str]] = []
    last_error = None

    async def attempt(kind: str, credential: str) -> dict[str, Any] | None:
        nonlocal last_response, last_error
        fingerprint = kind + ":" + credential
        identity = _provider_key_id(provider, fingerprint)
        if _PROVIDER_KEY_COOLDOWNS.get(identity, 0.0) > time.time():
            return None
        headers = {"Accept": "application/json"}
        request_params = dict(query)
        if kind == "bearer":
            headers["Authorization"] = "Bearer " + credential
        else:
            request_params["api_key"] = credential
        try:
            global _TMDB_HTTP_CLIENT
            if _TMDB_HTTP_CLIENT is None or _TMDB_HTTP_CLIENT.is_closed:
                _TMDB_HTTP_CLIENT = _InstrumentedAsyncClient(
                    timeout=httpx.Timeout(12.0, connect=4.0),
                    follow_redirects=True,
                    headers={"Accept": "application/json"},
                    limits=httpx.Limits(
                        max_connections=8,
                        max_keepalive_connections=4,
                        keepalive_expiry=30.0,
                    ),
                )
            async with _TMDB_REQUEST_SEMAPHORE:
                response = await _TMDB_HTTP_CLIENT.get(
                    f"{TMDB_API_BASE}/{path.lstrip('/')}",
                    params=request_params,
                    headers=headers,
                    timeout=httpx.Timeout(
                        request_timeout,
                        connect=min(4.0, request_timeout),
                    ),
                )
            last_response = response
            if 200 <= response.status_code < 300:
                _provider_key_success(provider, fingerprint)
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
                last_error = ValueError("TMDB returned non-object JSON")
                transient_failed.append((kind, credential))
                return None
            if response.status_code == 429:
                # Respect provider quotas instead of switching accounts to bypass them.
                _provider_key_failure(provider, fingerprint, _retry_after_seconds(response), "HTTP 429")
                raise HTTPException(status_code=503, detail="TMDB rate limit reached; retry after the provider cooldown.")
            if response.status_code == 401:
                _provider_key_failure(provider, fingerprint, 3600, "HTTP 401")
                return None
            if response.status_code == 403:
                # A credential may lack permission for this endpoint; cool it down
                # and try the remaining configured credentials before failing.
                _provider_key_failure(provider, fingerprint, 3600, "HTTP 403")
                return None
            if response.status_code >= 500:
                transient_failed.append((kind, credential))
                return None
            response.raise_for_status()
            return None
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=502, detail=f"TMDB returned HTTP {exc.response.status_code}.") from exc
        except (httpx.RequestError, ValueError) as exc:
            last_error = exc
            logger.info("TMDB request failed for %s credential %s: %s", path,
                _provider_key_id(provider, fingerprint).rsplit(":", 1)[-1], type(exc).__name__)
            transient_failed.append((kind, credential))
            return None

    for kind, credential in ordered:
        payload = await attempt(kind, credential)
        if payload is not None:
            return payload
    if transient_failed:
        await asyncio.sleep(0.75)
        retry_credentials = list(dict.fromkeys(transient_failed))
        transient_failed.clear()
        for kind, credential in retry_credentials:
            payload = await attempt(kind, credential)
            if payload is not None:
                return payload
        # Transport failures and upstream 5xx responses do not mean a credential
        # is invalid. Keep those credentials eligible; only explicit HTTP 401/403/429
        # responses should trigger credential-specific cooldowns.
    if last_response is not None and last_response.status_code == 429:
        raise HTTPException(status_code=503, detail="All eligible TMDB credentials are rate-limited or cooling down; retry shortly.")
    if last_response is not None and last_response.status_code in {401, 403}:
        raise HTTPException(status_code=503, detail="TMDB credentials were rejected or are cooling down. Check the configured keys.")
    logger.warning("TMDB request exhausted available credentials for %s (%s)", path, type(last_error).__name__ if last_error else "no eligible credential")
    raise HTTPException(status_code=503, detail="TMDB is temporarily unavailable or all credentials are cooling down. Cached catalogues will be used when available.")


async def _close_tmdb_http_client() -> None:
    """Close pooled metadata clients cleanly when the application shuts down."""
    global _TMDB_HTTP_CLIENT, _WATCHMODE_HTTP_CLIENT, _OMDB_HTTP_CLIENT
    if _TMDB_HTTP_CLIENT is not None and not _TMDB_HTTP_CLIENT.is_closed:
        await _TMDB_HTTP_CLIENT.aclose()
    _TMDB_HTTP_CLIENT = None
    if _WATCHMODE_HTTP_CLIENT is not None and not _WATCHMODE_HTTP_CLIENT.is_closed:
        await _WATCHMODE_HTTP_CLIENT.aclose()
    _WATCHMODE_HTTP_CLIENT = None
    if _OMDB_HTTP_CLIENT is not None and not _OMDB_HTTP_CLIENT.is_closed:
        await _OMDB_HTTP_CLIENT.aclose()
    _OMDB_HTTP_CLIENT = None
