from fastapi import APIRouter, HTTPException, Query

router = APIRouter()
VIDRIFT_EMBED_ORIGIN = "https://embed.vidrift.net"


def positive_int(value: object) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return 0
    return result if result > 0 else 0


def build_vidrift_movie_url(tmdb_id: int) -> str:
    tmdb_id = positive_int(tmdb_id)
    if not tmdb_id:
        raise ValueError("A positive TMDB movie ID is required")
    return f"{VIDRIFT_EMBED_ORIGIN}/embed/movie/{tmdb_id}"


def build_vidrift_tv_url(tmdb_id: int, season: int, episode: int) -> str:
    tmdb_id = positive_int(tmdb_id)
    season = positive_int(season)
    episode = positive_int(episode)
    if not tmdb_id or not season or not episode:
        raise ValueError("A positive TMDB series ID, season, and episode are required")
    return f"{VIDRIFT_EMBED_ORIGIN}/embed/tv/{tmdb_id}/{season}/{episode}"


@router.get("/api/vidrift/resolve")
async def resolve_vidrift(
    media_type: str = Query("movie", alias="type", pattern="^(movie|tv)$"),
    tmdb_id: int = Query(..., gt=0),
    season: int | None = Query(None, ge=1),
    episode: int | None = Query(None, ge=1),
):
    """Construct a VidRift embed URL without claiming title availability."""
    try:
        if media_type == "tv":
            if season is None or episode is None:
                raise HTTPException(status_code=422, detail="TV playback requires both season and episode.")
            url = build_vidrift_tv_url(tmdb_id, season, episode)
        else:
            url = build_vidrift_movie_url(tmdb_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "success": True,
        "type": media_type,
        "tmdbId": str(tmdb_id),
        "season": season if media_type == "tv" else None,
        "episode": episode if media_type == "tv" else None,
        "meta": {"provider": "VidRift", "availabilityVerified": False, "availability": "unverified"},
        "sources": [{"name": "VidRift", "url": url}],
    }
