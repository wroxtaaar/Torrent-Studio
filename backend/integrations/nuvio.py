from collections import defaultdict, deque
import os
import re
import time
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter()
_NUVIO_ID = re.compile(r"(?:tt\d{5,12}|tmdb:[1-9]\d{0,19})")
_LOOKUP_LIMIT = 20
_LOOKUP_WINDOW_SECONDS = 60
_lookup_requests: dict[str, deque[float]] = defaultdict(deque)


def _nuvio_base_url() -> str:
    value = os.getenv("NUVIO_BASE_URL", "").strip().rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=503, detail="Nuvio Streams is not configured. Set NUVIO_BASE_URL on the backend.")
    return value


def _check_lookup_limit(request: Request) -> None:
    now = time.monotonic()
    client_key = request.client.host if request.client else "unknown"
    recent = _lookup_requests[client_key]
    while recent and recent[0] <= now - _LOOKUP_WINDOW_SECONDS:
        recent.popleft()
    if len(recent) >= _LOOKUP_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Nuvio lookup limit reached. Try again shortly.",
        )
    recent.append(now)


@router.get("/api/nuvio/movies/{nuvio_id}")
async def get_nuvio_movie_streams(nuvio_id: str, request: Request):
    if not _NUVIO_ID.fullmatch(nuvio_id):
        raise HTTPException(
            status_code=422,
            detail="A valid IMDb ID or tmdb:<id> identifier is required.",
        )

    _check_lookup_limit(request)
    base_url = _nuvio_base_url()
    started_at = time.perf_counter()
    endpoint = f"{base_url}/stream/movie/{quote(nuvio_id, safe=':')}.json"
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.get(endpoint)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Nuvio source lookup timed out.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Could not connect to Nuvio Streams.") from exc

    if response.status_code == 404:
        payload = {}
    elif response.is_error or response.is_redirect:
        raise HTTPException(status_code=502, detail=f"Nuvio Streams returned HTTP {response.status_code}.")
    else:
        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Nuvio Streams returned malformed JSON.") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("streams", []), list):
        raise HTTPException(status_code=502, detail="Nuvio Streams returned an unexpected response.")

    streams = []
    for stream in payload.get("streams", [])[:100]:
        if not isinstance(stream, dict):
            continue
        source_url = stream.get("url")
        if not isinstance(source_url, str) or len(source_url) > 8192:
            continue
        try:
            parsed_url = urlsplit(source_url)
        except ValueError:
            continue
        if (
            parsed_url.scheme.lower() != "https"
            or not parsed_url.hostname
            or parsed_url.username
            or parsed_url.password
            or parsed_url.fragment
        ):
            continue
        streams.append({
            "name": stream.get("name", "")[:200] if isinstance(stream.get("name"), str) else "",
            "title": stream.get("title", "")[:500] if isinstance(stream.get("title"), str) else "",
            "url": source_url,
        })

    return {
        "id": nuvio_id,
        "streams": streams,
        "durationMs": round((time.perf_counter() - started_at) * 1000),
    }
