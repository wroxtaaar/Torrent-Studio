#!/usr/bin/env python3
"""Fill missing torrent options for Highest Rated Hollywood + Bollywood, first N pages (default 3).

Run on the VPS (needs the backend running, it calls /api/search). Only titles without releases are
searched; existing entries are kept. Writes highest-rated-torrents.json in the seed directory.

  python scripts/scan_highest_rated_top.py            # pages 1-3
  python scripts/scan_highest_rated_top.py --pages 5 --dry-run

Environment: REFRESH_SEED_DIR (default backend/cache-seed), HOME_API_BASE (default http://127.0.0.1:10000)
"""
from __future__ import annotations

import argparse, importlib.util, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mig", ROOT / "scripts" / "migrate_torrent_cache.py")
mig = importlib.util.module_from_spec(spec)
sys.modules["mig"] = mig
spec.loader.exec_module(mig)

API = os.getenv("HOME_API_BASE", "http://127.0.0.1:10000").rstrip("/")
SEED = Path(os.getenv("REFRESH_SEED_DIR") or ROOT / "backend" / "cache-seed")
SUBS = ("hollywood", "bollywood")


def search(query: str) -> list[dict]:
    url = f"{API}/api/search?q={urllib.parse.quote(query)}&limit=50"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "HighestRatedTopScan/1.0"})
    with urllib.request.urlopen(req, timeout=150) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, list) else data.get("results", data.get("torrents", []))


def to_release(row: dict) -> dict | None:
    magnet = row.get("magnetUrl") or ""
    h = mig.info_hash_of(row.get("infoHash") or row.get("hash"), magnet)
    if not h:
        return None
    try:
        size = int(row.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return {"infoHash": h, "title": str(row.get("title") or ""), "size": size,
            "seeders": int(row.get("seeders") or 0), "leechers": int(row.get("leechers") or 0),
            "indexer": str(row.get("indexer") or row.get("source") or ""), "infoUrl": str(row.get("infoUrl") or row.get("sourceUrl") or "")}


def variants(title: str, year: object) -> list[str]:
    base = str(title).split(":")[0].split(" - ")[0].strip()
    out: list[str] = []
    for q in (f"{title} {year}".strip(), title, f"{base} {year}".strip(), base):
        if q and q not in out:
            out.append(q)
    return out[:4]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    doc = json.loads((SEED / "highest-rated.json").read_text(encoding="utf-8"))
    path = SEED / "highest-rated-torrents.json"
    out = json.loads(path.read_text(encoding="utf-8"))
    limits = out.get("limits") or {"minSizeBytes": 104857600, "maxSizeBytes": None}
    titles = out.setdefault("titles", {})

    todo = []
    for sub in SUBS:
        s = doc["subsections"][sub]
        rows = s["results"][: args.pages * int(s.get("pageSize") or 18)]
        for row in rows:
            tid = row.get("tmdbId") or row.get("id")
            key = f"movie:{tid}"
            if not (titles.get(key) or {}).get("releases"):
                todo.append((key, row))
    print(f"{len(todo)} titles need a scan", flush=True)

    found = 0
    for i, (key, row) in enumerate(todo, 1):
        title, year = str(row.get("title") or ""), row.get("year")
        cands, answered = [], 0
        for q in variants(title, year):
            try:
                rows = search(q)
            except Exception as exc:
                print(f"  ! {title}: {q}: {exc}", flush=True)
                continue
            answered += 1
            cands += [r for r in map(to_release, rows) if r]
            chosen = mig.select_releases(cands, title, limits)
            if chosen:
                break
            time.sleep(0.4)
        chosen = mig.select_releases(cands, title, limits)
        print(f"[{i}/{len(todo)}] {title} ({year}): {len(chosen)} releases" + ("" if answered else "  (all searches failed)"), flush=True)
        if chosen:
            found += 1
            titles[key] = {"title": title, "year": int(year) if year else None,
                           "releases": [{k: v for k, v in r.items() if v not in ("", None)} for r in chosen]}

    out["titles"] = dict(sorted(titles.items()))
    out["builtAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if args.dry_run:
        print(f"dry run: would add {found} titles")
        return 0
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)
    print(f"added {found} titles; file now has {len(titles)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
