#!/usr/bin/env python3
"""Check the per-section metadata cache files (<section>.json) before they are published.

Offline and read-only. Hard failures (exit code 1): a torrent field or stale stream field inside a card,
a duplicate title, a card with no title. Everything else (no poster, no overview, no TMDB id, no IMDb id)
is only counted, because those gaps are what the enrichment step fills in on later runs.

    python scripts/validate_section_caches.py [--seed DIR]      (default: REFRESH_SEED_DIR or ~/torrent-studio-refresh/seed)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("split_top_section_caches", HERE / "split_top_section_caches.py")
split = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(split)

SECTIONS = ("marvel", "dc", "hollywood", "bollywood", "korean", "pakistani", "anime", "favourites", "highest-rated")
GAPS = (("tmdbId", "no tmdbId"), ("imdbId", "no imdbId"), ("posterUrl", "no poster"), ("overview", "no overview"))


def forbidden_keys(row: dict) -> list[str]:
    return sorted(k for k in row if split.is_torrent_field(str(k)) or k in split.LEGACY_STREAM_KEYS)


def check_subsection(rows: list) -> tuple[list[str], dict[str, int]]:
    """(hard problems, gap counts) for one subsection's rows."""
    problems: list[str] = []
    gaps = {label: 0 for _, label in GAPS}
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not split.title(row):
            problems.append(f"row {index}: no title")
            continue
        bad = forbidden_keys(row)
        if bad:
            problems.append(f"{split.title(row)}: forbidden fields {bad}")
        key = split.identity(row)
        if key in seen:
            problems.append(f"{split.title(row)}: duplicate ({key})")
        seen.add(key)
        for field, label in GAPS:
            if row.get(field) in (None, "", 0):
                gaps[label] += 1
    return problems, gaps


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", default=os.getenv("REFRESH_SEED_DIR") or str(Path.home() / "torrent-studio-refresh" / "seed"))
    seed = Path(parser.parse_args().seed)
    failed = False
    for section in SECTIONS:
        path = seed / f"{section}.json"
        if not path.exists():
            print(f"{section}: MISSING ({path.name})")
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"{section}: UNREADABLE ({exc})")
            failed = True
            continue
        for name, body in (doc.get("subsections") or {}).items():
            rows = body.get("results") or []
            problems, gaps = check_subsection(rows)
            total = body.get("totalResults")
            if total is not None and total != len(rows):
                problems.append(f"totalResults {total} != {len(rows)} rows")
            gap_text = ", ".join(f"{label} {count}" for label, count in gaps.items() if count)
            print(f"{section}/{name}: {len(rows)} rows" + (f" ({gap_text})" if gap_text else "") + ("  FAIL" if problems else ""))
            for problem in problems[:10]:
                print("    " + problem)
            failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
