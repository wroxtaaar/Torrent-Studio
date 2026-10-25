#!/usr/bin/env python3
"""Pick up titles newly added to the Classics lists, keeping everything already stored.

Movies: every listed title is searched again; torrent rows found earlier are kept when a search misses.
Web series / anime: the curated lists are resolved through TMDB and only titles missing from the stored
catalogue are added, so existing cards (and their saved details) are untouched.
Run from backend/ with APP_DATA_DIR set (scripts/refresh_seed.py does this).
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogues import catalogues_extra, catalogues_tv  # noqa: E402


def title_key(row: dict) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(row.get("title") or "").casefold())


async def rebuild_tv() -> None:
    keys = ("classics-web-series", "classics-anime")
    stored = {key: catalogues_tv._load_bundled_classics_tv_cache(key) for key in keys}
    catalogues_tv._load_bundled_classics_tv_cache = lambda key: None  # force a fresh resolve of the lists
    for key in keys:
        catalogues_tv._CLASSICS_TV_CATALOGUE_CACHE.pop(key, None)
        built = await catalogues_tv._get_classics_tv_catalogue(key)
        old = stored.get(key)
        if not old:
            continue
        have = {title_key(row) for row in old["results"]}
        added = [row for row in built["results"] if title_key(row) not in have and row.get("posterUrl")]
        # Resolved with no TMDB match at all (no poster, no overview): not worth a blank card.
        merged = {**old, "results": sorted(
            old["results"] + added,
            key=lambda row: (str(row.get("releaseDate") or row.get("year") or ""), str(row.get("title") or "")),
            reverse=True)}
        merged["totalResults"] = len(merged["results"])
        path = Path(str(catalogues_tv.DATA_DIR)) / catalogues_tv._CLASSICS_TV_CACHE_FILES[key]
        path.write_text(json.dumps(merged, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{key}: {len(old['results'])} stored + {len(added)} new = {len(merged['results'])}", flush=True)


async def main() -> None:
    built = await catalogues_extra._build_extra_catalogue("classics")
    rows = (built or {}).get("results") or [] if isinstance(built, dict) else []
    kill = sorted({str(r.get("title")) for r in rows if "kill bill" in str(r.get("title") or "").casefold()})
    print(f"classics movies: {len(rows)} rows; Kill Bill titles: {kill or 'NONE'}", flush=True)
    await rebuild_tv()


if __name__ == "__main__":
    asyncio.run(main())
