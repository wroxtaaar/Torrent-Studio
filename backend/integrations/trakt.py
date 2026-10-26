"""Trakt (https://trakt.tv) as an extra source: trending lists, and a rating fallback.

Free with an API key (client id): create an app at https://trakt.tv/oauth/applications and put the
"Client ID" in TRAKT_CLIENT_ID (several ids can be given, comma-separated, or as TRAKT_CLIENT_ID_2 ...).
Only GET requests are used, so no login or OAuth is needed. Trakt allows 1000 GETs per 5 minutes.

Nothing here runs in CACHE_ONLY_MODE (the Render default): the VPS scan reads Trakt and stores the result.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from core.settings import CACHE_ONLY_MODE, env_values

logger = logging.getLogger(__name__)
TRAKT_BASE = "https://api.trakt.tv"
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_SECONDS = 3 * 3600
_cursor = 0
_blocked_until = 0.0


def trakt_client_ids() -> list[str]:
    return env_values("TRAKT_CLIENT_IDS", "TRAKT_CLIENT_ID")


async def trakt_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET one Trakt endpoint; returns parsed JSON, or None when Trakt cannot answer (never raises)."""
    global _cursor, _blocked_until
    keys = trakt_client_ids()
    if CACHE_ONLY_MODE or not keys or time.time() < _blocked_until:
        return None
    cache_key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    hit = _CACHE.get(cache_key)
    if hit and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    key = keys[_cursor % len(keys)]
    _cursor += 1
    headers = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": key}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            response = await client.get(TRAKT_BASE + path, params=params, headers=headers)
    except httpx.HTTPError as exc:
        logger.info("Trakt %s failed: %s", path, type(exc).__name__)
        return None
    if response.status_code == 429:
        wait = int(response.headers.get("Retry-After") or 60)
        _blocked_until = time.time() + min(wait, 300)
        logger.info("Trakt rate limit: pausing %ss", wait)
        return None
    if response.status_code != 200:
        logger.info("Trakt %s answered HTTP %s", path, response.status_code)
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    _CACHE[cache_key] = (time.time(), data)
    return data


async def trakt_trending(kind: str, *, languages: str, countries: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
    """Trending movies ("movies") or shows ("shows"): [{title, year, tmdbId, imdbId, watchers}], best first."""
    params: dict[str, Any] = {"limit": limit, "languages": languages}
    if countries:
        params["countries"] = countries
    data = await trakt_get(f"/{kind}/trending", params)
    out: list[dict[str, Any]] = []
    for entry in data if isinstance(data, list) else []:
        item = (entry or {}).get("movie" if kind == "movies" else "show") or {}
        ids = item.get("ids") or {}
        tmdb = ids.get("tmdb")
        if not tmdb:
            continue
        out.append({"title": item.get("title"), "year": item.get("year"), "tmdbId": int(tmdb),
                    "imdbId": ids.get("imdb"), "watchers": entry.get("watchers")})
    return out


async def trakt_rating(kind: str, imdb_id: str = "", tmdb_id: int = 0) -> dict[str, Any] | None:
    """Trakt's own rating for a title: {"rating": 7.8, "votes": 1234} (not an IMDb rating)."""
    ident = imdb_id or ""
    if not ident and tmdb_id:
        found = await trakt_get(f"/search/tmdb/{int(tmdb_id)}", {"type": "movie" if kind == "movies" else "show"})
        first = (found or [None])[0] if isinstance(found, list) and found else None
        ids = ((first or {}).get("movie") or (first or {}).get("show") or {}).get("ids") or {}
        ident = str(ids.get("imdb") or ids.get("trakt") or "")
    if not ident:
        return None
    data = await trakt_get(f"/{kind}/{ident}/ratings")
    if not isinstance(data, dict) or not data.get("rating") or not data.get("votes"):
        return None
    return {"rating": round(float(data["rating"]), 1), "votes": int(data["votes"])}
