#!/usr/bin/env python3
"""Offline coverage report for backend/cache-seed (no network, no API keys).

Usage: python scripts/cache_report.py [seed_dir]
Lists, per catalogue file, how many titles there are and how many already carry
the fields the app needs (tmdbId, poster, overview; OTT lives in tmdb_ott_availability_cache.json) so Render never has to ask.
"""
import json, sys
from pathlib import Path

seed = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "backend" / "cache-seed")


def rows(node):
    """Yield every dict that looks like a title row."""
    if isinstance(node, dict):
        if ("title" in node or "name" in node) and any(k in node for k in ("tmdbId", "tmdb_id", "id", "poster", "posterUrl")):
            yield node
        else:
            for v in node.values():
                yield from rows(v)
    elif isinstance(node, list):
        for v in node:
            yield from rows(v)


def has(r, *keys):
    return any(r.get(k) for k in keys)


print(f"{'file':52} {'rows':>6} {'tmdb':>6} {'poster':>7} {'overview':>9}")
for f in sorted(seed.glob("*.json")) + sorted((seed / "runtime").glob("*.json")):
    try:
        data = json.loads(f.read_text())
    except Exception as e:
        print(f"{f.name:52} unreadable: {e}")
        continue
    rs = list(rows(data))
    if not rs:
        print(f"{f.name:52} {'-':>6} (key/value cache, {f.stat().st_size // 1024} KB)")
        continue
    n = len(rs)
    print(f"{f.relative_to(seed).as_posix():52} {n:6} "
          f"{sum(has(r,'tmdbId','tmdb_id') for r in rs):6} "
          f"{sum(has(r,'poster','posterUrl','poster_url') for r in rs):7} "
          f"{sum(has(r,'overview','synopsis','description') for r in rs):9}")
