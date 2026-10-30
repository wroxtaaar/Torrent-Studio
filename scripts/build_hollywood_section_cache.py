#!/usr/bin/env python3
"""Build the self-contained Hollywood section cache without torrent searches.

Outputs hollywood.json under REFRESH_SEED_DIR (default backend/cache-seed).
Subsections are Popular, Trending and Latest. Highest Rated is a separate
Top section and is intentionally not part of hollywood.json. Each subsection
stores movie metadata; previously cached torrent details are preserved when matched.

Modes:
  python scripts/build_hollywood_section_cache.py missing
  python scripts/build_hollywood_section_cache.py deep

This script does not invoke torrent-search endpoints or publish/deploy anything.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SEED = Path(os.getenv("REFRESH_SEED_DIR") or ROOT / "backend" / "cache-seed").resolve()
API = os.getenv("HOME_API_BASE", "http://127.0.0.1:10000").rstrip("/")
OUTPUT = SEED / "hollywood.json"
PAGE_SIZE = 18
SUBSECTIONS = {
    "popular": "popular-hollywood",
    "trending": "trending-hollywood",
    "latest": "latest-hollywood",
}
CORE_FIELDS = ("id", "title", "posterUrl", "overview")
TORRENT_FIELDS = {"torrentDetails", "torrentMatch", "torrentMatches", "cachedTorrentDetails"}


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def request_page(key: str, page: int) -> dict[str, Any]:
    endpoint = f"{API}/api/movies/catalogue/{urllib.parse.quote(key, safe='')}?page={page}"
    request = urllib.request.Request(endpoint, headers={"Accept": "application/json", "User-Agent": "TorrentStudio-HollywoodCache/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RuntimeError(f"Unexpected catalogue response for {key} page {page}")
    return payload


def title_key(row: dict[str, Any]) -> str:
    imdb = str(row.get("imdbId") or "").strip().casefold()
    if imdb:
        return "imdb:" + imdb
    tmdb = row.get("tmdbId") or row.get("id")
    if tmdb not in (None, ""):
        return "tmdb:" + str(tmdb)
    title = re.sub(r"[^a-z0-9]+", "", str(row.get("title") or row.get("name") or "").casefold())
    year = row.get("year") or str(row.get("releaseDate") or "")[:4]
    return f"title:{title}:{year}"


def empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def metadata_only(row: dict[str, Any]) -> dict[str, Any]:
    """Keep torrent payloads exclusively in the paired *-torrents.json file."""
    return {key: value for key, value in row.items() if key not in TORRENT_FIELDS}


def merge_missing(old: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    result = metadata_only(old)
    for key, value in metadata_only(fresh).items():
        if empty(result.get(key)) and not empty(value):
            result[key] = value
    return result


def core_complete(row: dict[str, Any]) -> bool:
    return all(not empty(row.get(field)) for field in CORE_FIELDS)


def cached_rows(section: dict[str, Any]) -> list[dict[str, Any]]:
    rows = section.get("results") or []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def fetch_catalogue(key: str, existing: list[dict[str, Any]], mode: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if mode == "missing" and existing and all(core_complete(row) for row in existing):
        return existing, {
            "catalogue": key,
            "pageCount": int((existing and (len(existing) + PAGE_SIZE - 1) // PAGE_SIZE) or 1),
            "totalResults": len(existing),
            "skipped": True,
            "reason": "all_cached_cards_have_core_fields",
        }

    old_by_id = {title_key(row): row for row in existing if title_key(row)}
    rows: list[dict[str, Any]] = []
    first: dict[str, Any] = {}
    # Keep the API's own paging and order. Stop on its declared final page.
    for page in range(1, 501):
        payload = request_page(key, page)
        if not first:
            first = payload
        page_rows = [row for row in payload["results"] if isinstance(row, dict) and (row.get("title") or row.get("name"))]
        for fresh in page_rows:
            previous = old_by_id.get(title_key(fresh))
            if mode == "missing" and previous:
                row = merge_missing(previous, fresh)
            else:
                row = metadata_only(fresh)
            rows.append(row)
        total_pages = int(payload.get("totalPages") or page)
        if page >= total_pages or not page_rows:
            break
        time.sleep(float(os.getenv("HOLLYWOOD_CACHE_DELAY_SECONDS", "0.1")))

    if not rows:
        raise RuntimeError(f"Refusing to replace {key}: API returned zero usable rows")
    if mode == "missing":
        # Preserve old records if the API's current page set is temporarily shorter.
        present = {title_key(row) for row in rows}
        rows.extend(metadata_only(row) for row in existing if title_key(row) not in present)
    return rows, {
        "catalogue": key,
        "pageCount": int(first.get("totalPages") or max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)),
        "totalResults": int(first.get("totalResults") or len(rows)),
        "skipped": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("missing", "deep"))
    args = parser.parse_args()
    if not SEED.is_dir():
        raise SystemExit(f"Seed directory does not exist: {SEED}")
    health_request = urllib.request.Request(API + "/api/health", headers={"Accept": "application/json"})
    with urllib.request.urlopen(health_request, timeout=5) as response:
        if response.status != 200:
            raise SystemExit(f"API health check failed: HTTP {response.status}")

    previous_doc = read_json(OUTPUT)
    previous_sections = previous_doc.get("subsections") if isinstance(previous_doc.get("subsections"), dict) else {}
    result_sections: dict[str, Any] = {}
    report = []
    for subsection, key in SUBSECTIONS.items():
        old_section = previous_sections.get(subsection) if isinstance(previous_sections.get(subsection), dict) else {}
        old_rows = cached_rows(old_section)
        try:
            rows, info = fetch_catalogue(key, old_rows, args.mode)
        except Exception as exc:
            # Do not drop a populated subsection because an upstream/API call failed.
            if not old_rows:
                raise RuntimeError(f"{key} failed and has no prior cache to preserve: {exc}") from exc
            rows = old_rows
            info = {"catalogue": key, "preservedAfterError": str(exc), "totalResults": len(old_rows)}
        result_sections[subsection] = {
            "catalogueKey": key,
            "mediaType": "movie",
            "pageSize": PAGE_SIZE,
            "totalResults": len(rows),
            "builtAt": datetime.now(timezone.utc).isoformat(),
            "results": rows,
            **({"status": "preserved-after-error"} if info.get("preservedAfterError") else {}),
        }
        report.append(info)

    # Keep unknown prior top-level fields for forward compatibility.
    document = dict(previous_doc)
    document.update({
        "schemaVersion": 1,
        "section": "hollywood",
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "subsections": result_sections,
        "safety": {"torrentSearches": 0, "torrentDataStoredSeparately": True,
                   "source": "existing Torrent Studio movie catalogue API"},
    })
    atomic_write(OUTPUT, document)
    print(json.dumps({"event": "hollywood_section_cache_written", "path": str(OUTPUT), "mode": args.mode, "subsections": report, "torrent_searches": 0}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
