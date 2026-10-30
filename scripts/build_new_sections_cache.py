#!/usr/bin/env python3
"""Refresh only the new regional/Highest Rated catalogue metadata caches.

This script talks to an already-running Torrent Studio API. It never calls the
torrent-search endpoint. It merges selected catalogue keys into the existing
regional cache documents, preserving every unrelated catalogue and movie row.

Usage:
  HOME_API_BASE=http://127.0.0.1:10000 \
  REFRESH_SEED_DIR=/home/ubuntu/torrent-studio-refresh/seed \
  python scripts/build_new_sections_cache.py
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SEED = Path(os.getenv("REFRESH_SEED_DIR") or ROOT / "backend" / "cache-seed").resolve()
API = os.getenv("HOME_API_BASE", "http://127.0.0.1:10000").rstrip("/")
PAGE_SIZE = 18
# Full IMDb Top lists are intentionally retained; regional lists are capped at
# three pages to keep this metadata-only refresh bounded.
MOVIE_TARGETS = {
    "highest-rated-hollywood": None,
    "highest-rated-bollywood": None,
    "popular-korean": 54,
    "popular-anime": 54,
}
TV_TARGETS = {
    "highest-rated-popular": 100,
    "korean-popular": 54,
    "pakistani-popular": 54,
    "anime-popular": 54,
}


def read_json(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except (OSError, ValueError, TypeError):
        return default


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(temp, path)


def request_json(path: str) -> dict[str, Any]:
    url = API + path
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "TorrentStudioTargetedCache/1.0"})
    with urllib.request.urlopen(req, timeout=120) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("results"), list):
        raise RuntimeError(f"Unexpected API payload for {path}")
    return value


def fetch_pages(endpoint: str, key: str, target: int | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    first: dict[str, Any] = {}
    page = 1
    max_pages = 500 if target is None else max(1, (target + PAGE_SIZE - 1) // PAGE_SIZE)
    while page <= max_pages and (target is None or len(rows) < target):
        url = f"{endpoint}/{urllib.parse.quote(key, safe='')}?page={page}"
        payload = request_json(url)
        if not first:
            first = payload
        page_rows = [row for row in payload["results"] if isinstance(row, dict) and (row.get("title") or row.get("name"))]
        rows.extend(page_rows)
        print(json.dumps({"event": "page", "catalogue": key, "page": page, "rows": len(page_rows), "total": len(rows)}), flush=True)
        if page >= int(payload.get("totalPages") or page):
            break
        page += 1
        time.sleep(float(os.getenv("TARGETED_CACHE_DELAY_SECONDS", "0.15")))
    if target is not None:
        rows = rows[:target]
    if not rows:
        raise RuntimeError(f"Refusing to replace {key}: API returned zero usable rows")
    return rows, first


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def movie_identity(row: dict[str, Any]) -> str:
    return norm(row.get("title") or row.get("name")) + "|" + str(row.get("year") or "")


def build_movies() -> None:
    path = SEED / "runtime" / "regional_movie_prebuilt_cache.json"
    old = read_json(path, {"version": 3, "catalogues": {}, "movies": {}})
    if not isinstance(old, dict):
        raise RuntimeError(f"Invalid movie cache document: {path}")
    old_catalogues = old.setdefault("catalogues", {})
    old_movies = old.setdefault("movies", {})
    if not isinstance(old_catalogues, dict) or not isinstance(old_movies, dict):
        raise RuntimeError("Movie cache has unexpected schema; refusing to overwrite it")

    summaries = {}
    for key, target in MOVIE_TARGETS.items():
        rows, meta = fetch_pages("/api/movies/catalogue", key, target)
        # Preserve source ordering (especially the IMDb curated ranking).
        old_catalogues[key] = {
            **(old_catalogues.get(key) if isinstance(old_catalogues.get(key), dict) else {}),
            "builtAt": datetime.now(timezone.utc).isoformat(),
            "targetMovies": target or int(meta.get("totalResults") or len(rows)),
            "movieCount": len(rows),
            "candidatesChecked": len(rows),
            "final": rows,
            "status": "ready" if target is None or len(rows) >= target else "partial",
            "metadataOnly": True,
        }
        for row in rows:
            identity = movie_identity(row)
            if not identity or identity == "|":
                continue
            previous = old_movies.get(identity)
            entry = dict(previous) if isinstance(previous, dict) else {}
            entry["movie"] = row
            cats = list(entry.get("catalogues") or [])
            if key not in cats:
                cats.append(key)
            entry["catalogues"] = cats
            # Keep any prior torrent details, but never create or initiate a scan.
            entry.setdefault("torrentDetails", {"query": str(row.get("title") or ""), "results": [], "status": "unavailable"})
            old_movies[identity] = entry
        summaries[key] = len(rows)

    old.update({"version": max(3, int(old.get("version") or 0)), "builtAt": datetime.now(timezone.utc).isoformat(), "status": "targeted-merge"})
    atomic_json(path, old)
    print(json.dumps({"event": "movie_cache_saved", "path": str(path), "catalogues": summaries}), flush=True)


def build_tv() -> None:
    path = SEED / "regional_tv_prebuilt_cache.json"
    old = read_json(path, {"schemaVersion": 3, "catalogues": {}})
    if not isinstance(old, dict):
        raise RuntimeError(f"Invalid TV cache document: {path}")
    catalogues = old.setdefault("catalogues", {})
    if not isinstance(catalogues, dict):
        raise RuntimeError("TV cache has unexpected schema; refusing to overwrite it")

    summaries = {}
    for key, target in TV_TARGETS.items():
        rows, meta = fetch_pages("/api/tv/catalogue", key, target)
        page_count = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        catalogues[key] = {
            "verifiedWebSeries": True,
            "totalResults": int(meta.get("totalResults") or len(rows)),
            "seriesCount": len(rows),
            "pages": [
                {"page": number + 1, "results": rows[number * PAGE_SIZE:(number + 1) * PAGE_SIZE]}
                for number in range(page_count)
            ],
            "builtAt": datetime.now(timezone.utc).isoformat(),
            "metadataOnly": True,
        }
        summaries[key] = len(rows)

    old["schemaVersion"] = max(3, int(old.get("schemaVersion") or old.get("version") or 0))
    old["builtAt"] = datetime.now(timezone.utc).isoformat()
    atomic_json(path, old)
    print(json.dumps({"event": "tv_cache_saved", "path": str(path), "catalogues": summaries}), flush=True)


def main() -> int:
    if not SEED.is_dir():
        raise SystemExit(f"Seed directory does not exist: {SEED}")
    health = urllib.request.urlopen(API + "/api/health", timeout=5)
    if health.status != 200:
        raise SystemExit(f"API health check failed: HTTP {health.status}")
    # Each cache is updated atomically after its selected catalogue pages have
    # been fetched. A failed catalogue never writes an empty replacement.
    build_movies()
    build_tv()
    print(json.dumps({"event": "targeted_cache_build_complete", "seed": str(SEED), "torrent_scans": 0}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
