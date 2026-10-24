"""Moved out of main.py (see docs/main-split-plan.md)."""

import asyncio
import json
import os
import re
import time
from typing import Any

import httpx
from fastapi import APIRouter, Query

from core.cache_diagnostics import _record_cache_event
from catalogues.catalogues_extra import _normalize_synopsis_match_title, _write_synopsis_cache
from core.settings import (
    CACHE_FIRST,
    CACHE_ONLY_MODE,
    IMDB_RATING_CACHE_FILE,
    IMDB_RATING_CACHE_TTL_SECONDS,
    IMDB_RATING_LOOKUP_VERSION,
    IMDB_RATING_NOT_FOUND_TTL_SECONDS,
    _split_env_keys,
    env_values,
    logger,
)
from metadata.tmdb import (
    _OMDB_REQUEST_SEMAPHORE,
    _PROVIDER_KEY_CURSORS,
    _omdb_client,
    _omdb_rate_limit_for,
    _omdb_rate_limited_until,
    _provider_key_available,
    _provider_key_failure,
    _provider_key_success,
    _retry_after_seconds,
    _tmdb_get_json,
)

router = APIRouter()


_IMDB_RATING_CACHE: dict[str, dict[str, Any]] | None = None
_IMDB_RATING_CACHE_LOCK = asyncio.Lock()
_IMDB_RATING_INFLIGHT: dict[str, asyncio.Task[dict[str, Any]]] = {}


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
    keys = env_values("OMDB_API_KEYS", "OMDB_API_KEY")
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

    def limited(key: str, seconds: float, reason: str) -> str:
        """Pause this key; move on to the next key if one is left, else pause OMDb as a whole."""
        _provider_key_failure(provider, key, seconds, reason)
        if any(other != key and _provider_key_available(provider, other) for other in ordered):
            return "invalid_key"  # the callers' "try the next key" state
        _omdb_rate_limit_for(seconds)
        return "rate_limited"

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
            return None, limited(key, _retry_after_seconds(response, 1800.0), "HTTP 429")
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
                # This key's daily quota is used up: another key (another account) may still have some.
                return None, limited(key, 3600.0, "daily request limit reached")
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
        if state in {"transient", "invalid_key"}:  # not an answer about the title: never store a miss
            return {**base, "status": "unavailable", "reason": "OMDb key unavailable", "cacheable": False}
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
    if cached and CACHE_FIRST:
        # Cache-first: any stored record is final. Only titles with no record are looked up.
        _record_cache_event("imdb_rating", "hit")
        return cached
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

@router.get("/api/catalogue/imdb-ratings")
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
