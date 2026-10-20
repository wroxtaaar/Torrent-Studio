"""Moved out of main.py (see docs/main-split-plan.md)."""

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from core.cache_diagnostics import _record_cache_event
from search.search_providers import _normalize_title
from core.settings import (
    CACHE_ONLY_MODE,
    DC_TV_CATALOGUE_CACHE_FILE,
    MARVEL_TV_CATALOGUE_CACHE_FILE,
    REGIONAL_TV_PREBUILT_CACHE_FILE,
    TMDB_API_KEYS,
    TMDB_IMAGE_BASE,
    TMDB_READ_ACCESS_TOKENS,
    _CACHE_SEED_DIR,
    logger,
)
from metadata.tmdb import _tmdb_get_json

router = APIRouter()


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


@router.get("/api/tv/catalogue/marvel")
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


@router.get("/api/tv/catalogue/dc-live-action")
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


@router.get("/api/tv/catalogue/classics-web-series")
async def api_tmdb_classics_web_series_catalogue():
    return await _get_classics_tv_catalogue("classics-web-series")


@router.get("/api/tv/catalogue/classics-anime")
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


@router.get("/api/tv/catalogue/{catalogue_key}")
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
