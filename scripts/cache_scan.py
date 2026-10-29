#!/usr/bin/env python3
"""Run a safe targeted cache scan in missing-only or deep-rewrite mode.

This pilot operates on the regional/Highest Rated cache documents used by
build_new_sections_cache.py. It never invokes torrent-search endpoints.

Usage:
  python scripts/cache_scan.py missing
  python scripts/cache_scan.py deep

Environment:
  REFRESH_SEED_DIR, HOME_API_BASE
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_new_sections_cache.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("torrent_studio_targeted_cache_builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load cache builder: {BUILDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def identity(row: dict[str, Any]) -> str:
    title = row.get("title") or row.get("name") or ""
    year = row.get("year") or ""
    tmdb_id = row.get("tmdbId") or row.get("id") or ""
    imdb_id = row.get("imdbId") or ""
    if imdb_id:
        return "imdb:" + str(imdb_id).casefold()
    if tmdb_id:
        return "tmdb:" + str(tmdb_id)
    return norm(title) + "|" + str(year)


def missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def merge_missing(old: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    """Keep known values; backfill only absent fields from the newly fetched row."""
    merged = dict(old)
    for key, value in fresh.items():
        if missing(merged.get(key)) and not missing(value):
            merged[key] = value
    return merged


def rows_from_movie_cache(path: Path) -> dict[str, dict[str, Any]]:
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for catalogue in (cache.get("catalogues") or {}).values():
        if not isinstance(catalogue, dict):
            continue
        for row in catalogue.get("final") or []:
            if isinstance(row, dict):
                rows[identity(row)] = row
    for entry in (cache.get("movies") or {}).values():
        if isinstance(entry, dict) and isinstance(entry.get("movie"), dict):
            rows[identity(entry["movie"])] = entry["movie"]
    return rows


def rows_from_tv_cache(path: Path) -> dict[str, dict[str, Any]]:
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for catalogue in (cache.get("catalogues") or {}).values():
        if not isinstance(catalogue, dict):
            continue
        for page in catalogue.get("pages") or []:
            if not isinstance(page, dict):
                continue
            for row in page.get("results") or []:
                if isinstance(row, dict):
                    rows[identity(row)] = row
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("missing", "deep"), help="missing preserves populated fields; deep rewrites from current API data")
    args = parser.parse_args()
    builder = load_builder()
    seed = Path(builder.SEED)
    movie_path = seed / "runtime" / "regional_movie_prebuilt_cache.json"
    tv_path = seed / "regional_tv_prebuilt_cache.json"

    if args.mode == "missing":
        old_movies = rows_from_movie_cache(movie_path)
        old_tv = rows_from_tv_cache(tv_path)
        original_fetch = builder.fetch_pages

        def fetch_pages_missing(endpoint: str, key: str, target: int | None):
            fresh_rows, metadata = original_fetch(endpoint, key, target)
            old_index = old_movies if endpoint.endswith("/movies/catalogue") else old_tv
            merged_rows = []
            for row in fresh_rows:
                previous = old_index.get(identity(row))
                merged_rows.append(merge_missing(previous, row) if previous else row)
            return merged_rows, metadata

        builder.fetch_pages = fetch_pages_missing
        print(json.dumps({
            "event": "scan_started",
            "mode": "missing",
            "scope": ["regional movies", "regional TV", "Highest Rated"],
            "policy": "preserve populated fields; backfill missing fields only",
            "torrent_searches": 0,
        }), flush=True)
    else:
        print(json.dumps({
            "event": "scan_started",
            "mode": "deep",
            "scope": ["regional movies", "regional TV", "Highest Rated"],
            "policy": "replace fetched catalogue rows with current API results",
            "torrent_searches": 0,
        }), flush=True)

    # Each builder writes atomically and refuses empty catalogue replacements.
    builder.build_movies()
    builder.build_tv()
    print(json.dumps({"event": "scan_complete", "mode": args.mode, "seed": str(seed), "torrent_searches": 0}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
