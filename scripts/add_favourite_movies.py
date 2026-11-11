#!/usr/bin/env python3
"""Append movies to Favourites -> Movies by TMDB id (skips ones already there), then run
scripts/enrich_top_section_metadata.py --section favourites --mode missing to fill posters/overview/ratings.

  python scripts/add_favourite_movies.py [--seed-dir DIR]
"""
import argparse, json, os, sys
from math import ceil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOVIES = [  # (tmdbId, title, year)
    (24420, "The Time Traveler's Wife", 2009),
    (2135, "The Time Machine", 2002),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-dir", type=Path, default=Path(os.getenv("REFRESH_SEED_DIR") or ROOT / "backend" / "cache-seed"))
    path = ap.parse_args().seed_dir / "favourites.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    node = doc["subsections"]["movies"]
    have = {str(r.get("tmdbId") or r.get("id")) for r in node["results"]}
    added = 0
    for tid, title, year in MOVIES:
        if str(tid) in have:
            continue
        node["results"].append({
            "id": tid, "tmdbId": tid, "title": title, "year": year, "releaseDate": f"{year}-01-01",
            "mediaType": "movie", "catalogueKey": "classics", "source": "VPS catalogue cache",
            "posterUrl": "https://image.tmdb.org/t/p/w500/api/poster", "tmdbUrl": f"https://www.themoviedb.org/movie/{tid}",
        })
        added += 1
    node["totalResults"] = len(node["results"])
    node["pageCount"] = ceil(len(node["results"]) / int(node.get("pageSize") or 18))
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    print(f"added {added}; Favourites movies now {node['totalResults']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
