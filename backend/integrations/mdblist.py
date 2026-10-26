"""MDBList (https://mdblist.com) as a fallback source of IMDb ratings.

Free with an API key (Account page -> API key, about 1000 requests a day): put it in MDBLIST_API_KEY
(several keys: comma-separated, or MDBLIST_API_KEY_2 ...). One call by TMDB or IMDb id returns the
ratings from IMDb, TMDB, Trakt, Rotten Tomatoes and others. Used only when OMDb could not answer.
Nothing runs in CACHE_ONLY_MODE (the Render default).
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from core.settings import CACHE_ONLY_MODE, env_values

logger = logging.getLogger(__name__)
MDBLIST_BASE = "https://api.mdblist.com"
_cursor = 0
_blocked_until = 0.0


def mdblist_keys() -> list[str]:
    return env_values("MDBLIST_API_KEYS", "MDBLIST_API_KEY")


def parse_imdb_rating(payload: Any) -> dict[str, Any] | None:
    """{"imdbRating": 7.9, "imdbVotes": "12,345", "imdbId": "tt..."} from an MDBList title record, or None."""
    if not isinstance(payload, dict):
        return None
    ids = payload.get("ids") if isinstance(payload.get("ids"), dict) else {}
    imdb_id = str(ids.get("imdb") or payload.get("imdbid") or "").strip() or None
    for entry in payload.get("ratings") or []:
        if not isinstance(entry, dict) or str(entry.get("source") or "").casefold() != "imdb":
            continue
        try:
            value = float(entry.get("value"))
        except (TypeError, ValueError):
            continue
        if not 0 < value <= 10:
            continue
        votes = entry.get("votes")
        return {"imdbRating": round(value, 1), "imdbVotes": f"{int(votes):,}" if str(votes or "").isdigit() else None,
                "imdbId": imdb_id}
    return None


async def mdblist_imdb_rating(media_type: str, *, tmdb_id: int = 0, imdb_id: str = "") -> dict[str, Any] | None:
    """IMDb rating through MDBList for a movie ("movie") or series ("tv"); None when it has none or cannot answer."""
    global _cursor, _blocked_until
    keys = mdblist_keys()
    if CACHE_ONLY_MODE or not keys or time.time() < _blocked_until:
        return None
    kind = "show" if media_type == "tv" else "movie"
    if imdb_id:
        path = f"/imdb/{kind}/{imdb_id}"
    elif tmdb_id > 0:
        path = f"/tmdb/{kind}/{int(tmdb_id)}"
    else:
        return None
    key = keys[_cursor % len(keys)]
    _cursor += 1
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=4.0)) as client:
            response = await client.get(MDBLIST_BASE + path, params={"apikey": key})
    except httpx.HTTPError as exc:
        logger.info("MDBList %s failed: %s", path, type(exc).__name__)
        return None
    if response.status_code == 429:
        _blocked_until = time.time() + 3600  # the daily quota is used up: stop asking for an hour
        return None
    if response.status_code != 200:
        return None
    try:
        return parse_imdb_rating(response.json())
    except ValueError:
        return None
