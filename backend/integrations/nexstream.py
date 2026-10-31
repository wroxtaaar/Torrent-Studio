"""Experimental NexStream resolver and title search used by the isolated test page.

Provider credentials stay on the server. Only approved HTTPS EmbedMaster player
URLs are returned to the browser; no direct media URLs are exposed by this adapter.
"""
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from core.cache_diagnostics import _InstrumentedAsyncClient, _record_cache_event
from fastapi import APIRouter, HTTPException, Query
from core.settings import CACHE_ONLY_MODE, _CACHE_SEED_DIR, data_file, log_cache_only_metadata_block, stored_ttl
from integrations.vidrift import build_vidrift_movie_url, build_vidrift_tv_url

router = APIRouter()
logger = logging.getLogger("torrent-studio")
NEXSTREAM_API_BASE = "https://api.codespecters.com"
TMDB_API_BASE = "https://api.themoviedb.org/3"
ALLOWED_EMBED_HOSTS = {"embedmaster.link", "www.embedmaster.link"}
_NEXSTREAM_CACHE_PATH = Path(os.getenv("NEXSTREAM_CACHE_PATH", data_file("nexstream_cache.json")))
_NEXSTREAM_CACHE_SEED_PATH = Path(
    os.getenv("NEXSTREAM_CACHE_SEED_PATH", str(_CACHE_SEED_DIR / "runtime" / "nexstream_cache.json"))
)
_NEXSTREAM_EPISODE_CACHE_PATH = Path(
    os.getenv("NEXSTREAM_EPISODE_CACHE_PATH", data_file("nexstream_episode_metadata_cache.json"))
)
_NEXSTREAM_EPISODE_CACHE_SEED_PATH = Path(
    os.getenv(
        "NEXSTREAM_EPISODE_CACHE_SEED_PATH",
        str(_CACHE_SEED_DIR / "runtime" / "nexstream_episode_metadata_cache.json"),
    )
)
_NEXSTREAM_CACHE_LOCK = threading.Lock()
_NEXSTREAM_EPISODE_CACHE_LOCK = threading.RLock()
_NEXSTREAM_SEARCH_CACHE_TTL = stored_ttl(24 * 60 * 60)
_NEXSTREAM_RESOLVE_CACHE_TTL = 5 * 60


def _seed_nexstream_cache() -> None:
    """Restore the bundled Nexstream cache only when persistent data is absent."""
    try:
        if _NEXSTREAM_CACHE_PATH.is_file() and _NEXSTREAM_CACHE_PATH.stat().st_size > 0:
            return
        if not _NEXSTREAM_CACHE_SEED_PATH.is_file() or _NEXSTREAM_CACHE_SEED_PATH.stat().st_size == 0:
            return
        payload = json.loads(_NEXSTREAM_CACHE_SEED_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return
        _NEXSTREAM_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _NEXSTREAM_CACHE_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
    except (OSError, ValueError, TypeError):
        # Cache seeding is best-effort and must never prevent API startup.
        return


_seed_nexstream_cache()


def _seed_nexstream_episode_cache() -> None:
    """Merge bundled episode metadata without replacing persistent season entries."""
    try:
        if (
            not _NEXSTREAM_EPISODE_CACHE_SEED_PATH.is_file()
            or _NEXSTREAM_EPISODE_CACHE_SEED_PATH.stat().st_size == 0
        ):
            return
        payload = json.loads(
            _NEXSTREAM_EPISODE_CACHE_SEED_PATH.read_text(encoding="utf-8")
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("shows"), dict):
            return
        with _NEXSTREAM_EPISODE_CACHE_LOCK:
            if _NEXSTREAM_EPISODE_CACHE_PATH.is_file():
                try:
                    persistent = json.loads(
                        _NEXSTREAM_EPISODE_CACHE_PATH.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    logger.warning(
                        "Could not merge bundled episode metadata into unreadable cache %s: %s",
                        _NEXSTREAM_EPISODE_CACHE_PATH,
                        exc,
                    )
                    return
                if not isinstance(persistent, dict) or not isinstance(persistent.get("shows", {}), dict):
                    logger.warning(
                        "Could not merge bundled episode metadata into invalid cache %s",
                        _NEXSTREAM_EPISODE_CACHE_PATH,
                    )
                    return
            else:
                persistent = {"shows": {}}
            if _merge_episode_cache_data(persistent, payload):
                _write_episode_cache_document(persistent)
    except (OSError, ValueError, TypeError):
        logger.exception("Could not seed bundled NexStream episode metadata")


def _read_nexstream_cache() -> dict[str, dict]:
    try:
        payload = json.loads(_NEXSTREAM_CACHE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _get_nexstream_cache(key: str, ttl: int):
    store = "nexstream_search" if key.startswith("search:") else "nexstream_resolve"
    with _NEXSTREAM_CACHE_LOCK:
        entry = _read_nexstream_cache().get(key)
    if not isinstance(entry, dict):
        _record_cache_event(store, "miss")
        return None
    cached_at = entry.get("cachedAt")
    if not isinstance(cached_at, (int, float)) or time.time() - cached_at >= ttl:
        _record_cache_event(store, "expired_miss")
        return None
    value = entry.get("value")
    if not isinstance(value, dict):
        _record_cache_event(store, "invalid_miss")
        return None
    _record_cache_event(store, "persistent_hit")
    if key.startswith("search:"):
        _record_cache_event(store, "result_rows_served", len(value.get("results") or []))
    else:
        _record_cache_event(store, "source_rows_served", len(value.get("sources") or []))
    return value


def _set_nexstream_cache(key: str, value: dict) -> None:
    _NEXSTREAM_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _NEXSTREAM_CACHE_LOCK:
        cache = _read_nexstream_cache()
        now = time.time()
        # Keep the persistent cache bounded and discard old/expired records.
        cache = {
            cache_key: entry
            for cache_key, entry in cache.items()
            if isinstance(entry, dict)
            and isinstance(entry.get("cachedAt"), (int, float))
            and now - entry["cachedAt"] < _NEXSTREAM_SEARCH_CACHE_TTL
        }
        cache[key] = {"cachedAt": now, "value": value}
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(_NEXSTREAM_CACHE_PATH.parent),
                prefix="nexstream-cache-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(cache, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, _NEXSTREAM_CACHE_PATH)
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    pass


def _env_values(*names: str) -> list[str]:
    from core.settings import env_values
    return env_values(*names)


def nexstream_api_key_configured() -> bool:
    """Compatibility name: VidRift has a public embed and requires no API key."""
    return True


async def resolve_nexstream_movie(tmdb_id: int) -> dict:
    """Return a VidRift player URL for a valid TMDB movie ID.

    VidRift documents iframe embeds, not a server-side title-availability API.
    This confirms URL compatibility only; it does not verify that playback works.
    """
    if tmdb_id <= 0:
        raise HTTPException(status_code=404, detail="Unknown movie.")
    return {
        "success": True,
        "type": "movie",
        "tmdbId": str(tmdb_id),
        "season": None,
        "episode": None,
        "meta": {"provider": "VidRift", "availabilityVerified": False, "availability": "unverified"},
        "sources": [{
            "name": "VidRift",
            "url": build_vidrift_movie_url(tmdb_id),
        }],
    }


@router.get("/api/nexstream/search")
async def search_titles(
    query: str = Query(..., min_length=2, max_length=120),
    media_type: str = Query("movie", alias="type", pattern="^(movie|tv)$"),
):
    """Search TMDB by title so testers don't need to know TMDB IDs."""
    # Cache first: a stored answer must work even on a deployment without TMDB credentials.
    endpoint = "movie" if media_type == "movie" else "tv"
    normalized_query = " ".join(query.split()).casefold()
    cache_key = f"search:{media_type}:{normalized_query}"
    cached = _get_nexstream_cache(cache_key, _NEXSTREAM_SEARCH_CACHE_TTL)
    if cached is not None:
        return cached

    api_keys = _env_values("TMDB_API_KEYS", "TMDB_API_KEY")
    bearer_tokens = _env_values("TMDB_READ_ACCESS_TOKENS", "TMDB_READ_ACCESS_TOKEN", "TMDB_BEARER_TOKEN")
    if not api_keys and not bearer_tokens:
        raise HTTPException(
            status_code=503,
            detail="TMDB credentials are not configured on the test server.",
        )

    params = {"query": query.strip(), "include_adult": "false", "page": "1"}
    payload = None
    last_status = None
    connection_errors = 0

    async with _InstrumentedAsyncClient(timeout=httpx.Timeout(12.0), follow_redirects=True) as client:
        # A broken connection for one credential must not prevent trying the others.
        for key in api_keys:
            try:
                response = await client.get(
                    f"{TMDB_API_BASE}/search/{endpoint}",
                    params={**params, "api_key": key},
                    headers={"Accept": "application/json"},
                )
            except httpx.RequestError:
                connection_errors += 1
                continue

            last_status = response.status_code
            if response.status_code == 200:
                payload = response.json()
                break
            if response.status_code == 429:
                raise HTTPException(status_code=429, detail="TMDB search rate limit reached. Try again shortly.")

        if payload is None:
            for token in bearer_tokens:
                try:
                    response = await client.get(
                        f"{TMDB_API_BASE}/search/{endpoint}",
                        params=params,
                        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                    )
                except httpx.RequestError:
                    connection_errors += 1
                    continue

                last_status = response.status_code
                if response.status_code == 200:
                    payload = response.json()
                    break
                if response.status_code == 429:
                    raise HTTPException(status_code=429, detail="TMDB search rate limit reached. Try again shortly.")

    if payload is None:
        if last_status in (401, 403):
            raise HTTPException(status_code=502, detail="TMDB rejected the configured credentials.")
        if connection_errors and last_status is None:
            raise HTTPException(status_code=502, detail="Could not connect to TMDB title search.")
        raise HTTPException(status_code=502, detail="TMDB title search failed.")

    results = []
    for item in payload.get("results", [])[:12]:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        title = item.get("title") if media_type == "movie" else item.get("name")
        results.append({
            "id": int(item["id"]),
            "title": str(title or "Untitled"),
            "date": str((item.get("release_date") if media_type == "movie" else item.get("first_air_date")) or ""),
            "overview": str(item.get("overview") or "")[:400],
            "poster": f"https://image.tmdb.org/t/p/w185{item['poster_path']}" if item.get("poster_path") else None,
            "type": media_type,
        })
    result = {"success": True, "type": media_type, "results": results}
    _set_nexstream_cache(cache_key, result)
    return result




def _merge_episode_cache_data(persistent: dict, bundled: dict) -> bool:
    """Merge only missing shows, season metadata, and completed episode lists."""
    persistent_shows = persistent.setdefault("shows", {})
    bundled_shows = bundled.get("shows") or {}
    changed = False
    for tmdb_id, bundled_show in bundled_shows.items():
        if not isinstance(bundled_show, dict):
            continue
        if tmdb_id not in persistent_shows or not isinstance(persistent_shows[tmdb_id], dict):
            persistent_shows[tmdb_id] = json.loads(json.dumps(bundled_show))
            changed = True
            continue
        persistent_show = persistent_shows[tmdb_id]
        if persistent_show.get("tmdbId") is None and bundled_show.get("tmdbId") is not None:
            persistent_show["tmdbId"] = bundled_show["tmdbId"]
            changed = True
        persistent_seasons = persistent_show.setdefault("seasons", [])
        if not isinstance(persistent_seasons, list):
            persistent_seasons = persistent_show["seasons"] = []
            changed = True
        known_seasons = {
            str(item.get("seasonNumber"))
            for item in persistent_seasons
            if isinstance(item, dict) and item.get("seasonNumber") is not None
        }
        for season in bundled_show.get("seasons") or []:
            if not isinstance(season, dict) or season.get("seasonNumber") is None:
                continue
            season_key = str(season["seasonNumber"])
            if season_key not in known_seasons:
                persistent_seasons.append(json.loads(json.dumps(season)))
                known_seasons.add(season_key)
                changed = True
        if persistent_show.get("seasonsFetched") is not True and bundled_show.get("seasonsFetched") is True:
            persistent_show["seasonsFetched"] = True
            changed = True
        persistent_episodes = persistent_show.setdefault("episodesBySeason", {})
        if not isinstance(persistent_episodes, dict):
            persistent_episodes = persistent_show["episodesBySeason"] = {}
            changed = True
        for season, episodes in (bundled_show.get("episodesBySeason") or {}).items():
            if season not in persistent_episodes and isinstance(episodes, list):
                persistent_episodes[season] = json.loads(json.dumps(episodes))
                changed = True
    return changed


def _write_episode_cache_document(data: dict) -> None:
    _NEXSTREAM_EPISODE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(_NEXSTREAM_EPISODE_CACHE_PATH.parent),
            prefix="nexstream-episodes-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, _NEXSTREAM_EPISODE_CACHE_PATH)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _read_episode_cache_document() -> dict:
    try:
        with _NEXSTREAM_EPISODE_CACHE_LOCK:
            if not _NEXSTREAM_EPISODE_CACHE_PATH.is_file():
                _record_cache_event("nexstream_episode_metadata", "miss")
                return {"shows": {}}
            data = json.loads(_NEXSTREAM_EPISODE_CACHE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("shows", {}), dict):
            raise ValueError("invalid episode cache document")
        return data
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("Could not read NexStream episode cache %s: %s", _NEXSTREAM_EPISODE_CACHE_PATH, exc)
        _record_cache_event("nexstream_episode_metadata", "read_error_miss")
        return {"shows": {}}


def _episode_cache_response(data: dict, tmdb_id: int, season: int) -> dict | None:
    show = (data.get("shows") or {}).get(str(tmdb_id))
    if not isinstance(show, dict):
        _record_cache_event("nexstream_episode_metadata", "miss")
        return None
    seasons = show.get("seasons") if isinstance(show.get("seasons"), list) else []
    episodes_by_season = show.get("episodesBySeason")
    if not isinstance(episodes_by_season, dict):
        episodes_by_season = {}
    season_key = str(season)
    if season_key in episodes_by_season and isinstance(episodes_by_season[season_key], list):
        episodes = episodes_by_season[season_key]
        _record_cache_event("nexstream_episode_metadata", "persistent_hit")
        _record_cache_event("nexstream_episode_metadata", "episode_rows_served", len(episodes))
        return {
            "success": True,
            "status": "ready" if episodes else "no_episodes",
            "tmdbId": tmdb_id,
            "seasons": seasons,
            "selectedSeason": season,
            "episodes": episodes,
            "cached": True,
        }
    if show.get("seasonsFetched") is True and not seasons:
        _record_cache_event("nexstream_episode_metadata", "persistent_hit")
        return {
            "success": True,
            "status": "no_seasons",
            "tmdbId": tmdb_id,
            "seasons": [],
            "selectedSeason": season,
            "episodes": [],
            "cached": True,
        }
    return None


def _write_episode_cache(
    tmdb_id: int,
    seasons: list,
    season: int | None,
    episodes: list | None,
) -> None:
    with _NEXSTREAM_EPISODE_CACHE_LOCK:
        data = _read_episode_cache_document()
        show = (data.setdefault("shows", {})).setdefault(
            str(tmdb_id),
            {"tmdbId": tmdb_id, "seasons": [], "episodesBySeason": {}},
        )
        show["tmdbId"] = tmdb_id
        show["seasons"] = seasons
        show["seasonsFetched"] = True
        episode_map = show.setdefault("episodesBySeason", {})
        if season is not None and episodes is not None:
            episode_map[str(season)] = episodes
        _write_episode_cache_document(data)

_seed_nexstream_episode_cache()


@router.get("/api/nexstream/episodes")
async def get_tv_episodes(
    tmdb_id: int = Query(..., gt=0),
    season: int = Query(1, ge=1),
):
    """Serve persisted episode metadata first; fetch TMDB only on cache misses."""
    if tmdb_id <= 0:
        raise HTTPException(status_code=422, detail="Invalid TMDB ID.")
    if season <= 0:
        raise HTTPException(status_code=422, detail="Invalid season number.")
    cache_document = _read_episode_cache_document()
    cached = _episode_cache_response(cache_document, tmdb_id, season)
    if cached is not None:
        return cached
    show_cache = (cache_document.get("shows") or {}).get(str(tmdb_id)) or {}
    known_seasons = show_cache.get("seasons") if isinstance(show_cache, dict) else []
    if isinstance(known_seasons, list) and known_seasons and not any(
        isinstance(item, dict) and int(item.get("seasonNumber", 0) or 0) == season
        for item in known_seasons
    ):
        raise HTTPException(status_code=404, detail=f"Season {season} is not available for TMDB show {tmdb_id}.")
    if CACHE_ONLY_MODE:
        _record_cache_event("nexstream_episode_metadata", "cache_only_miss_blocked")
        log_cache_only_metadata_block("TMDB")
        raise HTTPException(
            status_code=404,
            detail=f"Episode metadata for TMDB show {tmdb_id}, season {season}, is not present in the local cache.",
        )
    api_keys = _env_values("TMDB_API_KEYS", "TMDB_API_KEY")
    bearer_tokens = _env_values("TMDB_READ_ACCESS_TOKENS", "TMDB_READ_ACCESS_TOKEN", "TMDB_BEARER_TOKEN")
    if not api_keys and not bearer_tokens:
        raise HTTPException(status_code=503, detail="TMDB authentication is not configured.")

    async with _InstrumentedAsyncClient(timeout=httpx.Timeout(12.0), follow_redirects=True) as client:
        async def tmdb_get(path: str):
            last_status = None
            connection_errors = 0
            for key in api_keys:
                try:
                    response = await client.get(f"{TMDB_API_BASE}{path}", params={"api_key": key}, headers={"Accept": "application/json"})
                except httpx.RequestError:
                    connection_errors += 1
                    continue
                last_status = response.status_code
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 429:
                    raise HTTPException(status_code=429, detail="TMDB rate limit reached. Try again shortly.")
            for token in bearer_tokens:
                try:
                    response = await client.get(f"{TMDB_API_BASE}{path}", headers={"Accept": "application/json", "Authorization": f"Bearer {token}"})
                except httpx.RequestError:
                    connection_errors += 1
                    continue
                last_status = response.status_code
                if response.status_code == 200:
                    return response.json()
                if response.status_code == 429:
                    raise HTTPException(status_code=429, detail="TMDB rate limit reached. Try again shortly.")
            if last_status in (401, 403):
                raise HTTPException(status_code=502, detail="TMDB authentication failed. Check the configured credentials.")
            if connection_errors and last_status is None:
                raise HTTPException(status_code=502, detail="Network connection to TMDB failed while loading episode metadata.")
            if last_status == 404:
                if path.endswith("/season/" + str(season)):
                    raise HTTPException(status_code=404, detail=f"TMDB has no episode metadata for season {season} of show {tmdb_id}.")
                raise HTTPException(status_code=404, detail=f"TMDB show {tmdb_id} was not found; the TMDB ID may be invalid.")
            raise HTTPException(status_code=502, detail=f"TMDB episode metadata failed (HTTP {last_status or 'unknown'}).")

        show = await tmdb_get(f"/tv/{tmdb_id}")
        seasons = [
            {"seasonNumber": int(item.get("season_number", 0)), "name": str(item.get("name") or f"Season {item.get('season_number', 0)}"), "episodeCount": int(item.get("episode_count", 0))}
            for item in show.get("seasons", [])
            if isinstance(item, dict) and int(item.get("season_number", 0)) > 0
        ]
        if not seasons:
            _write_episode_cache(tmdb_id, [], None, None)
            return {
                "success": True,
                "status": "no_seasons",
                "tmdbId": tmdb_id,
                "seasons": [],
                "selectedSeason": season,
                "episodes": [],
            }
        if not any(item["seasonNumber"] == season for item in seasons):
            _write_episode_cache(tmdb_id, seasons, None, None)
            raise HTTPException(status_code=404, detail=f"Season {season} is not available for TMDB show {tmdb_id}.")
        _write_episode_cache(tmdb_id, seasons, None, None)
        season_data = await tmdb_get(f"/tv/{tmdb_id}/season/{season}")
    episodes = [
        {
            "episodeNumber": int(item.get("episode_number", 0)),
            "name": str(item.get("name") or ""),
            "overview": str(item.get("overview") or "")[:500],
            "airDate": str(item.get("air_date") or ""),
            "still": f"https://image.tmdb.org/t/p/w300{item['still_path']}" if item.get("still_path") else None,
        }
        for item in season_data.get("episodes", [])
        if isinstance(item, dict) and int(item.get("episode_number", 0)) > 0
    ]
    _write_episode_cache(tmdb_id, seasons, season, episodes)
    return {
        "success": True,
        "status": "ready" if episodes else "no_episodes",
        "tmdbId": tmdb_id,
        "seasons": seasons,
        "selectedSeason": season,
        "episodes": episodes,
    }


@router.get("/api/nexstream/resolve")
async def resolve_nexstream(
    media_type: str = Query("movie", alias="type", pattern="^(movie|tv)$"),
    tmdb_id: int = Query(..., gt=0),
    season: int | None = Query(None, ge=1),
    episode: int | None = Query(None, ge=1),
):
    """Compatibility route returning VidRift embed URLs for movies and episodes."""
    if media_type == "tv":
        if season is None or episode is None:
            raise HTTPException(status_code=422, detail="TV playback requires both season and episode.")
        url = build_vidrift_tv_url(tmdb_id, season, episode)
    else:
        url = build_vidrift_movie_url(tmdb_id)
    return {
        "success": True,
        "type": media_type,
        "tmdbId": str(tmdb_id),
        "season": season if media_type == "tv" else None,
        "episode": episode if media_type == "tv" else None,
        "meta": {"provider": "VidRift", "availabilityVerified": False, "availability": "unverified"},
        "sources": [{"name": "VidRift", "url": url}],
    }
