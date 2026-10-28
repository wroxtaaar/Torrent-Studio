from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


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
    return f"https://megaplay.buzz/stream/mal/{int(mal_id)}/{int(episode)}/{stream_type}"


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
