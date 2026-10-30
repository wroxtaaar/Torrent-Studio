import re
import time

import httpx
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

ANILIST_GRAPHQL_URL = "https://graphql.anilist.co"
_MAL_CACHE: dict[tuple[str, int | None], tuple[float, dict]] = {}  # resolved answers only
_MAL_CACHE_SECONDS = 30 * 24 * 3600
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


async def fetch_anilist_mal_resolution(title: str, year: int | None, timeout_seconds: float = 8.0) -> dict:
    known = KNOWN_MAL_IDS.get(normalize_anime_title(title))
    if known:
        return {"status": "resolved", "malId": known, "source": "catalogue", "title": title}

    cache_key = (normalize_anime_title(title), year)
    hit = _MAL_CACHE.get(cache_key)
    if hit and time.time() - hit[0] < _MAL_CACHE_SECONDS:
        return hit[1]  # a resolved title is not looked up again

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
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            response = await client.post(ANILIST_GRAPHQL_URL, json={"query": query, "variables": {"search": title}}, headers={"Accept": "application/json", "User-Agent": "Torrent-Studio/1.0"})
        response.raise_for_status()
        payload = response.json()
        candidates = (((payload.get("data") or {}).get("Page") or {}).get("media") or [])
        result = resolve_mal_from_anilist_candidates(title, year, candidates)
        if result.get("status") == "resolved":
            _MAL_CACHE[cache_key] = (time.time(), result)
        return result
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {"status": "unavailable", "malId": None, "source": "AniList", "message": f"Automatic MAL ID resolution is unavailable: {exc}"}


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
