"""Moved out of main.py (see docs/main-split-plan.md)."""

import asyncio
import json
import os
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from core.cache_diagnostics import _record_cache_event
from catalogues.catalogues_extra import (
    MARVEL_MOVIE_SEARCHES,
    _EXTRA_CATALOGUES,
    _EXTRA_CATALOGUE_PATHS,
    _ensure_extra_catalogue_refresh,
    _extra_catalogue_monthly_scheduler,
    _extra_catalogue_states,
    _extra_catalogue_tasks,
    _extra_item_year,
    _lookup_catalogue_synopsis,
    _read_extra_catalogue,
    _schedule_tmdb_catalogue_synopsis_enrichment,
    _write_extra_catalogue,
)
from core.http_cache import (
    _DATE_SORTED_EXTRA_CATALOGUES,
    _fast_json_response,
    _file_signature,
    _page_catalogue_payload,
    _prebuilt_catalogue_page,
)
from metadata.imdb import _get_imdb_rating_record
from integrations.nexstream import nexstream_api_key_configured, resolve_nexstream_movie
from core.settings import (
    BACKFILL_MISSING_METADATA,
    CACHE_FIRST,
    CACHE_ONLY_MODE,
    REGIONAL_MOVIE_CACHE_PAGE_SIZE,
    REGIONAL_MOVIE_CACHE_TTL_SECONDS,
    REGIONAL_MOVIE_CATALOGUE_KEYS,
    REGIONAL_MOVIE_PREBUILT_CACHE_PATH,
    REGIONAL_MOVIE_PREWARM_PAGES,
    REGIONAL_CACHE_REQUIRE_SOURCE,
    REGIONAL_MOVIE_TRENDING_ARCHIVE_FILE,
    REGIONAL_MOVIE_TRENDING_ARCHIVE_WEEKS,
    TMDB_CATALOGUE_CACHE_SECONDS,
    TMDB_COMPANY_CACHE_SECONDS,
    TMDB_IMAGE_BASE,
    TMDB_OTT_CACHE_SECONDS,
    _CACHE_SEED_DIR,
    data_file,
    logger,
    stored_ttl,
)
from core.shared import (
    _REGIONAL_MOVIE_CATALOGUE_FORCE_REFRESH,
    _REGIONAL_MOVIE_SOURCE_FORCE_REFRESH,
    _REGIONAL_MOVIE_SOURCE_REFRESHED_KEYS,
)
from metadata.tmdb import (
    _read_tmdb_ott_persistent_cache,
    _read_tmdb_persistent_cache,
    _tmdb_company_id_cache,
    _tmdb_company_inflight,
    _tmdb_fetch_movie_ott_availability,
    _tmdb_get_json,
    _tmdb_movie_catalogue_cache,
    _tmdb_movie_catalogue_inflight,
    _tmdb_ott_cache,
    _tmdb_ott_inflight,
    _tmdb_ott_ttl,
    _write_tmdb_ott_persistent_cache,
    _write_tmdb_persistent_cache,
)

router = APIRouter()


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


def _regional_entry_has_source(entry: dict[str, Any], row: dict[str, Any]) -> bool:
    """Cached titles must be watchable: at least one torrent, or playable on NexStream.

    Entries whose torrent scan never ran (no torrentDetails at all) are kept, so an unscanned
    seed does not become an empty catalogue.
    """
    if not REGIONAL_CACHE_REQUIRE_SOURCE:
        return True
    if row.get("nexStreamPlayable") is True:
        return True
    details = entry.get("torrentDetails")
    if not isinstance(details, dict):
        return True
    return bool(details.get("results"))


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
            if not _regional_entry_has_source(entry, row):
                continue
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


async def _fetch_paginated_regional_movie_catalogue(
    catalogue_key: str, page: int,
    skip_ids: set[str] | None = None, skip_pages: int = 0,
) -> dict[str, Any]:
    """Build stable 18-item display pages from eligible regional movie candidates.

    With skip_ids/skip_pages the first `skip_pages` pages are served from the cache, so this
    page continues right after them: those titles are left out and counting starts after them.
    """
    page_size = REGIONAL_MOVIE_CACHE_PAGE_SIZE
    live_page = page - skip_pages
    wanted = live_page * page_size + 1
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
    seen_ids: set[str] = set(skip_ids or ())
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

    start = (live_page - 1) * page_size
    page_rows = eligible_rows[start:start + page_size]
    if exhausted:
        total_pages = max(1, (len(eligible_rows) + page_size - 1) // page_size)
    else:
        # Progressive pagination: the next display page is available, and its
        # request will scan further source pages if the user continues.
        total_pages = max(live_page + 1, (len(eligible_rows) + page_size - 1) // page_size)
    total_pages += skip_pages
    return {
        "catalogue": catalogue_key,
        "releasedOnly": True,
        "provider": "TMDB + verified India OTT availability",
        "page": page,
        "totalPages": total_pages,
        "totalResults": skip_pages * page_size + (
            len(eligible_rows) if exhausted else max(len(eligible_rows), (live_page + 1) * page_size)
        ),
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


def _cached_regional_identities(catalogue_key: str) -> set[str] | None:
    """Titles held by the cached first pages, or None unless those pages are completely full.

    Pages beyond the cached ones come from the live API; they must continue after these
    titles instead of repeating them.
    """
    page_size = REGIONAL_MOVIE_CACHE_PAGE_SIZE
    identities: set[str] = set()
    total = 0
    for cached_page in range(1, REGIONAL_MOVIE_PREWARM_PAGES + 1):
        payload = _cache_only_regional_movie_catalogue(catalogue_key, cached_page)
        rows = [row for row in ((payload or {}).get("results") or []) if isinstance(row, dict)]
        total += len(rows)
        for row in rows:
            for field in ("id", "tmdbId", "title"):
                value = str(row.get(field) or "").strip()
                if value:
                    identities.add(value)
    return identities if total >= REGIONAL_MOVIE_PREWARM_PAGES * page_size else None


def _with_more_pages(payload: dict[str, Any], page: int) -> dict[str, Any]:
    """When the cached pages are full, tell the UI that further pages exist (served live)."""
    page_size = REGIONAL_MOVIE_CACHE_PAGE_SIZE
    cached_pages = REGIONAL_MOVIE_PREWARM_PAGES
    if CACHE_ONLY_MODE or page > cached_pages or not isinstance(payload, dict):
        return payload
    try:
        total_results = int(payload.get("totalResults") or 0)
        total_pages = int(payload.get("totalPages") or 0)
    except (TypeError, ValueError):
        return payload
    if total_results < cached_pages * page_size or total_pages > cached_pages:
        return payload
    return {**payload, "totalPages": cached_pages + 1,
            "totalResults": max(total_results, (cached_pages + 1) * page_size)}


@router.get("/api/movies/catalogue/{catalogue_key}")
async def api_tmdb_movie_catalogue(
    catalogue_key: str,
    page: int = Query(1, ge=1, le=500),
    released_only: bool = Query(True),
    max_size_gb: int = Query(5, ge=1, le=5),
    basic: bool = Query(False),
):
    payload = await _api_tmdb_movie_catalogue(catalogue_key, page, released_only, max_size_gb, basic)
    if not basic and released_only and catalogue_key in REGIONAL_MOVIE_CATALOGUE_KEYS:
        return _with_more_pages(payload, page)
    return payload


async def _api_tmdb_movie_catalogue(
    catalogue_key: str,
    page: int,
    released_only: bool,
    max_size_gb: int,
    basic: bool,
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
        eligible_persistent = _read_tmdb_persistent_cache(eligible_cache_key, any_version=True)
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
        # Cache-first: the bundled snapshot is tried before TMDB, not only in cache-only mode.
        if CACHE_ONLY_MODE or (CACHE_FIRST and not force_refresh and page <= REGIONAL_MOVIE_PREWARM_PAGES):
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
        if CACHE_ONLY_MODE:
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
            skip_ids = _cached_regional_identities(catalogue_key) if page > REGIONAL_MOVIE_PREWARM_PAGES else None
            payload = await _fetch_paginated_regional_movie_catalogue(
                catalogue_key, page, skip_ids, REGIONAL_MOVIE_PREWARM_PAGES if skip_ids else 0,
            )
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
    durable_regional_page = is_regional_movie_catalogue and not is_trending_catalogue and page <= REGIONAL_MOVIE_PREWARM_PAGES
    cache_ttl = stored_ttl(min(TMDB_CATALOGUE_CACHE_SECONDS, 900)) if catalogue_key.startswith("trending-") else TMDB_CATALOGUE_CACHE_SECONDS
    cached = _tmdb_movie_catalogue_cache.get(cache_key)
    if cached and (durable_regional_page or now - cached[0] < cache_ttl):
        _record_cache_event("movie_catalogue", "memory_hit")
        _schedule_tmdb_catalogue_synopsis_enrichment(cached[1])
        return await _apply_movie_release_eligibility(cached[1], enabled=released_only)

    # A disk cache survives container restarts, unlike the in-memory TTL cache.
    persistent = None if is_trending_catalogue else _read_tmdb_persistent_cache(cache_key, any_version=True)
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


@router.get("/api/movies/ott/{movie_id}")
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
        data_file("marvel_tmdb_id_review.json"),
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


@router.get("/api/movies/ott/backfill/marvel")
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


@router.get("/api/catalogue/extra/{catalogue_key}")
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
    if CACHE_ONLY_MODE or not BACKFILL_MISSING_METADATA:
        return
    if _classics_ott_enrichment_task is None or _classics_ott_enrichment_task.done():
        _classics_ott_enrichment_task = asyncio.create_task(_enrich_classics_movie_ott_cache())


async def _warm_extra_catalogues_on_startup() -> None:
    # Catalogue builds are deliberately lazy. The old startup warm-up launched
    # all stale/missing catalogues together and flooded every upstream provider.
    asyncio.create_task(_extra_catalogue_monthly_scheduler())


def _regional_page_is_stored(catalogue_key: str, page: int) -> bool:
    """True when this page can be served without TMDB: stored at runtime or in the bundled snapshot."""
    cached = _read_tmdb_persistent_cache((catalogue_key + "|eligible-v6", page), any_version=True)
    if cached and _regional_movie_cache_page_is_usable(cached[1], page):
        return True
    return CACHE_FIRST and _cache_only_regional_movie_catalogue(catalogue_key, page) is not None


def _regional_movie_cache_refresh_delay() -> float:
    if CACHE_FIRST:
        # Cache-first never refreshes pages that exist; it only has to fill pages that do not.
        for catalogue_key in REGIONAL_MOVIE_CATALOGUE_KEYS:
            for page in range(1, REGIONAL_MOVIE_PREWARM_PAGES + 1):
                if not _regional_page_is_stored(catalogue_key, page):
                    return 0
        return float(REGIONAL_MOVIE_CACHE_TTL_SECONDS)
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
            if CACHE_FIRST and _regional_page_is_stored(catalogue_key, page):
                # Cache-first: never re-query TMDB for a page that is already stored.
                continue
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
                    "Regional movie cache %s page %s has %s titles (expected %s); TMDB may have fewer eligible titles.",
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
