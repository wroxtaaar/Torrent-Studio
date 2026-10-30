import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()
SECTION_CACHE_NAMES = frozenset({
    "hollywood", "bollywood", "marvel", "dc", "highest-rated",
    "korean", "pakistani", "anime", "favourites",
})
SECTION_CACHE_DIR = Path(__file__).resolve().parents[1] / "cache-seed"


@router.get("/api/sections/{section}")
async def api_get_section_cache(section: str) -> dict[str, Any]:
    if section not in SECTION_CACHE_NAMES:
        raise HTTPException(status_code=404, detail="Section cache not found")
    path = SECTION_CACHE_DIR / f"{section}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Section cache is not installed") from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Section cache could not be read") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("section") != section
        or payload.get("metadataSelfContained") is not True
        or not isinstance(payload.get("subsections"), dict)
    ):
        raise HTTPException(status_code=500, detail="Section cache has an invalid document shape")
    return payload
