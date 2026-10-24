#!/usr/bin/env python3
"""Store an IMDb rating record for every web series / anime in the TV catalogues.

Run by scripts/refresh_seed.py so the bundle already holds them and Render never has to ask OMDb.
Titles that already have a stored record are skipped (cache-first); transient failures are not stored.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import settings  # noqa: E402
from metadata import imdb  # noqa: E402

TV_FILES = (
    "regional_tv_prebuilt_cache.json", "marvel_tv_catalogue_cache.json", "dc_tv_catalogue_cache.json",
    "marvel_web_series_catalogue.json", "classics_anime_tv_catalogue.json", "classics_web_series_tv_catalogue.json",
)


def shows(node: Any):
    if isinstance(node, dict):
        title = str(node.get("title") or node.get("name") or "").strip()
        ident = node.get("tmdbId") or node.get("id")
        if title and ident and (node.get("posterUrl") or node.get("overview") or node.get("year")):
            try:
                year = int(node.get("year") or str(node.get("releaseDate") or node.get("first_air_date") or "")[:4] or 0)
            except ValueError:
                year = 0
            try:
                tmdb_id = int(ident)
            except (TypeError, ValueError):
                tmdb_id = 0
            yield title, year, tmdb_id
        for value in node.values():
            yield from shows(value)
    elif isinstance(node, list):
        for value in node:
            yield from shows(value)


async def main() -> None:
    wanted: dict[tuple[str, int], int] = {}
    for name in TV_FILES:
        path = settings.DATA_DIR / name
        if path.is_file():
            for title, year, tmdb_id in shows(json.loads(path.read_text(encoding="utf-8"))):
                wanted.setdefault((title, year), tmdb_id)
    print(f"TV titles: {len(wanted)}", flush=True)
    found = missing = 0
    for index, ((title, year), tmdb_id) in enumerate(wanted.items(), 1):
        record = await imdb._get_imdb_rating_record(title, year, "tv", tmdb_id)
        if record.get("status") == "found" and record.get("imdbRating") is not None:
            found += 1
        else:
            missing += 1
        if index % 50 == 0:
            print(f"  {index}/{len(wanted)} (found {found}, none {missing})", flush=True)
    print(f"IMDb ratings for TV: found {found}, no rating {missing}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
