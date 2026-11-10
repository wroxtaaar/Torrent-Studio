#!/usr/bin/env python3
"""Fetch torrent options ONLY for titles that have none yet, and keep everything already cached.

For each section it reads <section>.json (the lists the app shows), finds movie titles whose entry in
<section>-torrents.json has no releases, searches those, and merges the results in. Titles that already
have releases are never searched again. Needs the app running (it calls /api/search).

  python scripts/scan_missing_torrents.py                              # hollywood, bollywood, anime
  python scripts/scan_missing_torrents.py --sections highest-rated --pages 3
  python scripts/scan_missing_torrents.py --dry-run

Environment: REFRESH_SEED_DIR (default backend/cache-seed), HOME_API_BASE (default http://127.0.0.1:3000)
"""
from __future__ import annotations

import argparse, importlib.util, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mig", ROOT / "scripts" / "migrate_torrent_cache.py")
mig = importlib.util.module_from_spec(spec)
sys.modules["mig"] = mig
spec.loader.exec_module(mig)

API = os.getenv("HOME_API_BASE", "http://127.0.0.1:3000").rstrip("/")
SEED = Path(os.getenv("REFRESH_SEED_DIR") or ROOT / "backend" / "cache-seed")
SUBS = ("hollywood", "bollywood")


def search(query: str) -> list[dict]:
    url = f"{API}/api/search?q={urllib.parse.quote(query)}&limit=50"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "HighestRatedTopScan/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))
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


YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def year_ok(release_title: str, title: str, year: object) -> bool:
    """A release naming a different year is a different film (remake, sequel). No year in the name = accept."""
    if not year:
        return True
    own = set(YEAR.findall(str(title)))  # a year that is part of the film's own name (e.g. "2012") is not a release year
    found = set(YEAR.findall(str(release_title))) - own
    return not found or str(year) in found or any(abs(int(y) - int(year)) <= 1 for y in found)


def pick(cands: list[dict], title: str, year: object, limits: dict) -> list[dict]:
    return mig.select_releases([r for r in cands if year_ok(r["title"], title, year)], title, limits)


def variants(title: str, year: object) -> list[str]:
    base = str(title).split(":")[0].split(" - ")[0].strip()
    out: list[str] = []
    for q in (f"{title} {year}".strip(), title, f"{base} {year}".strip(), base):
        if q and q not in out:
            out.append(q)
    return out[:4]


def titles_to_scan(section: str, pages: int) -> tuple[dict, Path, list[tuple[str, dict]]]:
    doc = json.loads((SEED / f"{section}.json").read_text(encoding="utf-8"))
    path = SEED / f"{section}-torrents.json"
    if path.exists():
        out = json.loads(path.read_text(encoding="utf-8"))
    else:
        out = {"schemaVersion": 2, "kind": "torrent-options", "section": section, "trackers": [], "titles": {}}
    out.setdefault("limits", {"minSizeBytes": 104857600, "maxSizeBytes": None})
    titles = out.setdefault("titles", {})
    todo, seen = [], set()
    for sub, node in doc["subsections"].items():
        if not isinstance(node, dict) or node.get("mediaType") not in ("movie", "movies"):
            continue
        rows = node.get("results") or []
        if pages:
            rows = rows[: pages * int(node.get("pageSize") or 18)]
        for row in rows:
            tid = row.get("tmdbId") or row.get("id")
            key = f"movie:{tid}"
            if not tid or key in seen:
                continue
            seen.add(key)
            if not (titles.get(key) or {}).get("releases"):
                todo.append((key, row))
    return out, path, todo


def recheck(section: str, write: bool = True) -> int:
    path = SEED / f"{section}-torrents.json"
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    dropped = 0
    for key in list(data.get("titles", {})):
        entry = data["titles"][key]
        keep = [r for r in entry.get("releases", []) if year_ok(r.get("title", ""), entry.get("title", ""), entry.get("year"))]
        dropped += len(entry.get("releases", [])) - len(keep)
        if keep:
            entry["releases"] = keep
        else:
            del data["titles"][key]
    if dropped and write:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
    return dropped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sections", default="hollywood,bollywood,anime")
    ap.add_argument("--pages", type=int, default=0, help="only the first N pages of each list (0 = all)")
    ap.add_argument("--recheck", action="store_true",
                    help="first drop saved releases whose name shows a different year, so those titles are searched again")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    for section in [x.strip() for x in args.sections.split(",") if x.strip()]:
        if args.recheck:
            dropped = recheck(section, write=not args.dry_run)
            print(f"[{section}] recheck removed {dropped} releases with a different year", flush=True)
        out, path, todo = titles_to_scan(section, args.pages)
        titles, limits = out["titles"], out["limits"]
        print(f"[{section}] {len(todo)} titles without torrents", flush=True)
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
                if pick(cands, title, year, limits):
                    break
                time.sleep(0.4)
            chosen = pick(cands, title, year, limits)
            print(f"  [{i}/{len(todo)}] {title} ({year}): {len(chosen)} releases" + ("" if answered else "  (all searches failed)"), flush=True)
            if chosen:
                found += 1
                titles[key] = {"title": title, "year": int(year) if year else None,
                               "releases": [{k: v for k, v in r.items() if v not in ("", None)} for r in chosen]}
            if not args.dry_run and found and i % 10 == 0:  # save as we go, so an interrupted run loses almost nothing
                out["titles"] = dict(sorted(titles.items()))
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                os.replace(tmp, path)
        if args.dry_run or not todo:
            print(f"[{section}] {'dry run: would add' if args.dry_run else 'added'} {found} titles", flush=True)
            continue
        out["titles"] = dict(sorted(titles.items()))
        out["builtAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, path)
        print(f"[{section}] added {found} titles; file now has {len(titles)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
