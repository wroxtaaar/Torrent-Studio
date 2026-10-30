#!/usr/bin/env python3
"""Split existing Torrent Studio seed catalogues into one metadata/torrent pair per top section.

Migration only: reads existing seed JSON files, performs no API calls, no provider
searches, and no publishing/deployment. Existing output records are preserved and
merged by IMDb/TMDB identity before source rows are added.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path(os.getenv("TS_HOME") or Path.home() / "torrent-studio-refresh")
SEED = Path(os.getenv("REFRESH_SEED_DIR") or HOME / "seed").resolve()
PAGE_SIZE = 18
TORRENT_KEYS = {
    "torrentDetails", "torrentMatch", "torrentMatches", "cachedTorrentDetails",
    "torrentReleases", "torrentResults", "releases", "releaseGroups",
}
REGIONAL_MOVIE = {
    "popular-hollywood": ("hollywood", "popular"),
    "trending-hollywood": ("hollywood", "trending"),
    "latest-hollywood": ("hollywood", "latest"),
    "popular-bollywood": ("bollywood", "popular"),
    "trending-bollywood": ("bollywood", "trending"),
    "latest-bollywood": ("bollywood", "latest"),
    "highest-rated-hollywood": ("highest-rated", "hollywood"),
    "highest-rated-bollywood": ("highest-rated", "bollywood"),
    "popular-korean": ("korean", "movies"),
    "popular-pakistani": ("pakistani", "movies"),
    "popular-anime": ("anime", "movies"),
}
REGIONAL_TV = {
    "highest-rated-popular": ("highest-rated", "tv"),
    "korean-popular": ("korean", "series"),
    "pakistani-popular": ("pakistani", "series"),
    "anime-popular": ("anime", "series"),
}
LEGACY_FILES = {
    "latest_hollywood_catalogue.json": ("hollywood", "latest"),
    "latest_bollywood_catalogue.json": ("bollywood", "latest"),
    "bollywood_torrent_matched_catalogue.json": ("bollywood", "torrent-matched"),
    "marvel_catalogue.json": ("marvel", "movies"),
    "marvel_hindi_catalogue.json": ("marvel", "hindi-movies"),
    "marvel_web_series_catalogue.json": ("marvel", "series"),
    "dc_live_action_catalogue.json": ("dc", "live-action"),
    "dc_live_action_hindi_catalogue.json": ("dc", "hindi-live-action"),
    "dc_animated_catalogue.json": ("dc", "animated"),
    "classics_catalogue.json": ("favourites", "movies"),
    "classics_web_series_tv_catalogue.json": ("favourites", "series"),
    "classics_anime_tv_catalogue.json": ("favourites", "anime"),
}
RUNTIME_FILES = {
    "marvel_tv_catalogue_cache.json": ("marvel", "series"),
    "dc_tv_catalogue_cache.json": ("dc", "series"),
}

def log(event: str, **data: Any) -> None:
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)

def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

def atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise

def title(row: dict[str, Any]) -> str:
    return str(row.get("title") or row.get("name") or "").strip()

def identity(row: dict[str, Any]) -> str:
    imdb = str(row.get("imdbId") or "").strip().lower()
    if re.fullmatch(r"tt\d+", imdb):
        return "imdb:" + imdb
    tmdb = row.get("tmdbId") or row.get("id")
    if tmdb not in (None, "") and str(tmdb).isdigit():
        return "tmdb:" + str(tmdb)
    clean = re.sub(r"[^a-z0-9]+", "", title(row).casefold())
    year = row.get("year") or str(row.get("releaseDate") or "")[:4]
    return f"title:{clean}:{year}" if clean else ""

def collect_rows(value: Any) -> list[dict[str, Any]]:
    """Collect title records from legacy shapes (results/pages/final/items/catalogue)."""
    found: list[dict[str, Any]] = []
    seen_objects: set[int] = set()
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if id(node) in seen_objects: return
            seen_objects.add(id(node))
            if title(node) and any(k in node for k in ("id", "tmdbId", "imdbId", "posterUrl", "overview", "year", "releaseDate")):
                found.append(node)
            for child in node.values(): walk(child)
        elif isinstance(node, list):
            for child in node: walk(child)
    walk(value)
    dedup: dict[str, dict[str, Any]] = {}
    for row in found:
        key = identity(row)
        if key:
            dedup.setdefault(key, row)
    return list(dedup.values())

def metadata_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in TORRENT_KEYS}

def torrent_payload(row: dict[str, Any]) -> dict[str, Any]:
    data = {k: v for k, v in row.items() if k in TORRENT_KEYS}
    # Legacy torrent-matched files sometimes use provider-specific field names.
    for key, value in row.items():
        low = key.casefold()
        if any(token in low for token in ("torrent", "magnet", "seed", "release", "provider")):
            data.setdefault(key, value)
    return data

def merge_rows(existing: list[dict[str, Any]], incoming: list[dict[str, Any]], *, metadata: bool) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in existing + incoming:
        key = identity(row)
        if not key: continue
        clean = metadata_row(row) if metadata else row
        if key not in merged:
            merged[key] = dict(clean)
            order.append(key)
        else:
            current = merged[key]
            for field, value in clean.items():
                if current.get(field) in (None, "", [], {}) and value not in (None, "", [], {}):
                    current[field] = value
    return [merged[k] for k in order]

def subsection_doc(section: str, previous: Any) -> dict[str, Any]:
    if isinstance(previous, dict) and previous.get("section") == section:
        return previous
    return {"schemaVersion": 1, "section": section, "subsections": {}}

def get_existing_rows(doc: dict[str, Any], sub: str) -> list[dict[str, Any]]:
    node = (doc.get("subsections") or {}).get(sub) or {}
    rows = node.get("results") if isinstance(node, dict) else []
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []

def source_for_file(name: str) -> Path | None:
    candidates = [SEED / name, SEED / "runtime" / name]
    return next((p for p in candidates if p.is_file()), None)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report planned records without writing")
    args = parser.parse_args()
    if not SEED.is_dir():
        raise SystemExit(f"Seed directory not found: {SEED}")

    incoming: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    torrent_incoming: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    source_report: list[dict[str, Any]] = []

    # Regional movie cache: extract the curated final lists, not intermediate candidates.
    regional = read_json(SEED / "runtime" / "regional_movie_prebuilt_cache.json")
    if isinstance(regional, dict):
        catalogues = regional.get("catalogues") or {}
        for key, target in REGIONAL_MOVIE.items():
            node = catalogues.get(key) if isinstance(catalogues, dict) else None
            rows = node.get("final") if isinstance(node, dict) else []
            if not isinstance(rows, list) or not rows:
                continue
            pair = target
            incoming[pair].extend(r for r in rows if isinstance(r, dict) and title(r))
            for row in rows:
                if isinstance(row, dict) and torrent_payload(row):
                    torrent_incoming[pair].append({"movie": metadata_row(row), "torrentData": torrent_payload(row)})
            source_report.append({"source": "regional_movie_prebuilt_cache.json", "catalogue": key, "records": len(rows)})

    # Regional TV cache stores pages[].results.
    regional_tv = read_json(SEED / "regional_tv_prebuilt_cache.json")
    if isinstance(regional_tv, dict):
        catalogues = regional_tv.get("catalogues") or {}
        for key, target in REGIONAL_TV.items():
            node = catalogues.get(key) if isinstance(catalogues, dict) else None
            rows: list[dict[str, Any]] = []
            if isinstance(node, dict):
                pages = node.get("pages") or []
                for page in pages:
                    if isinstance(page, dict) and isinstance(page.get("results"), list):
                        rows.extend(r for r in page["results"] if isinstance(r, dict) and title(r))
                if not rows and isinstance(node.get("results"), list):
                    rows = [r for r in node["results"] if isinstance(r, dict) and title(r)]
            if rows:
                incoming[target].extend(rows)
                source_report.append({"source": "regional_tv_prebuilt_cache.json", "catalogue": key, "records": len(rows)})

    # Legacy franchise, classics and regional source files.
    for filename, target in {**LEGACY_FILES, **RUNTIME_FILES}.items():
        path = source_for_file(filename)
        if not path:
            continue
        payload = read_json(path)
        rows = collect_rows(payload)
        if not rows:
            log("source_empty_or_unrecognized", source=str(path))
            continue
        incoming[target].extend(rows)
        for row in rows:
            data = torrent_payload(row)
            if data:
                torrent_incoming[target].append({"movie": metadata_row(row), "torrentData": data})
        source_report.append({"source": str(path.relative_to(SEED)), "records": len(rows)})

    # Existing Hollywood pair and prior section outputs are inputs too; preserve their data.
    section_names = sorted({section for section, _ in incoming} | {
        p.stem for p in SEED.glob("*.json") if p.stem in {
            "hollywood", "bollywood", "marvel", "dc", "highest-rated",
            "korean", "pakistani", "anime", "favourites"
        }
    })
    totals: dict[str, Any] = {}
    now = datetime.now(timezone.utc).isoformat()
    for section in section_names:
        out_path = SEED / f"{section}.json"
        old_doc = subsection_doc(section, read_json(out_path))
        old_subs = old_doc.get("subsections") if isinstance(old_doc.get("subsections"), dict) else {}
        new_subs = dict(old_subs)
        section_counts: dict[str, int] = {}
        subs = {sub for sec, sub in incoming if sec == section}
        for sub in sorted(subs):
            previous_rows = get_existing_rows(old_doc, sub)
            rows = merge_rows(previous_rows, incoming[(section, sub)], metadata=True)
            new_subs[sub] = {
                "catalogueKey": sub,
                "mediaType": "tv" if sub in {"series", "anime", "tv"} else "movie",
                "pageSize": PAGE_SIZE,
                "pageCount": (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE,
                "totalResults": len(rows),
                "builtAt": now,
                "results": rows,
            }
            section_counts[sub] = len(rows)
        old_doc.update({
            "schemaVersion": 1,
            "section": section,
            "builtAt": now,
            "mode": "legacy-migration",
            "subsections": new_subs,
            "safety": {
                "torrentSearches": 0,
                "torrentDataStoredSeparately": True,
                "activeApplicationCacheWrites": 0,
                "source": "existing seed JSON files only",
            },
        })
        totals[section] = section_counts
        if not args.dry_run and section_counts:
            atomic_write(out_path, old_doc)

        torrent_path = SEED / f"{section}-torrents.json"
        old_torrent_doc = read_json(torrent_path)
        if not isinstance(old_torrent_doc, dict):
            old_torrent_doc = {"schemaVersion": 1, "section": section, "subsections": {}}
        old_torrent_subs = old_torrent_doc.get("subsections") if isinstance(old_torrent_doc.get("subsections"), dict) else {}
        new_torrent_subs = dict(old_torrent_subs)
        torrent_counts: dict[str, int] = {}
        for sec, sub in sorted(torrent_incoming):
            if sec != section: continue
            old_node = new_torrent_subs.get(sub) or {}
            old_rows = old_node.get("results") if isinstance(old_node, dict) else []
            old_rows = old_rows if isinstance(old_rows, list) else []
            rows = merge_rows(old_rows, torrent_incoming[(sec, sub)], metadata=False)
            new_torrent_subs[sub] = {
                "catalogueKey": sub,
                "builtAt": now,
                "totalResults": len(rows),
                "results": rows,
            }
            torrent_counts[sub] = len(rows)
        old_torrent_doc.update({
            "schemaVersion": 1,
            "section": section,
            "builtAt": now,
            "mode": "legacy-migration",
            "subsections": new_torrent_subs,
            "safety": {"torrentSearches": 0, "source": "existing cached torrent fields only"},
        })
        if not args.dry_run and torrent_counts:
            atomic_write(torrent_path, old_torrent_doc)
        totals[section] = {"metadata": section_counts, "torrent": torrent_counts}

    log("section_split_complete", seed=str(SEED), dryRun=args.dry_run, sections=totals, sources=source_report,
        filesWritten=0 if args.dry_run else sum(1 for v in totals.values() if any(v.get(k) for k in ("metadata", "torrent"))))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
