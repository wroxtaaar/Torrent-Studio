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

_strict_match = mig.title_phrase_match


def _loose_match(release_title: str, expected: list[str]) -> bool:
    """Exact phrase, or for titles of 3+ words: at least 80% of the title's words present in the release name
    (release names often add words, e.g. 'Movie 09', 'Part 1', '2160p', that TMDB titles don't have)."""
    if _strict_match(release_title, expected):
        return True
    have = set(mig.normalize_title(release_title).split())
    for needle in expected:
        words = needle.split()
        if len(words) >= 3 and sum(w in have for w in words) / len(words) >= 0.8:
            return True
    return False


sys.path.insert(0, str(ROOT / "scripts"))
import torrent_misses  # noqa: E402

mig.title_phrase_match = _loose_match  # used by select_releases() inside the migration module
API = os.getenv("HOME_API_BASE", "http://127.0.0.1:3000").rstrip("/")
SEED = Path(os.getenv("REFRESH_SEED_DIR") or ROOT / "backend" / "cache-seed")
SUBS = ("hollywood", "bollywood")


NATIVE: set[str] = set()  # movies from Bollywood lists: already Hindi, so no Hindi search
SOURCE = "all"  # set from --source: fast | prowlarr | all


def search(query: str, also_hindi: bool = True) -> list[dict]:
    url = f"{API}/api/search?q={urllib.parse.quote(query)}&limit=50&any_size=true&source={SOURCE}" + ("" if also_hindi else "&also_hindi=false")
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
    detail = str(row.get("infoUrl") or row.get("sourceUrl") or "")
    if not h and not detail.startswith("https://"):
        return None
    try:
        size = int(row.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return {"infoHash": h, "title": str(row.get("title") or ""), "size": size,
            "seeders": int(row.get("seeders") or 0), "leechers": int(row.get("leechers") or 0),
            "indexer": str(row.get("indexer") or row.get("source") or ""), "infoUrl": detail}


YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def year_ok(release_title: str, title: str, year: object) -> bool:
    """A release naming a different year is a different film (remake, sequel). No year in the name = accept."""
    if not year:
        return True
    own = set(YEAR.findall(str(title)))  # a year that is part of the film's own name (e.g. "2012") is not a release year
    found = set(YEAR.findall(str(release_title))) - own
    return not found or str(year) in found or any(abs(int(y) - int(year)) <= 1 for y in found)


def resolve_hashes(cands: list[dict], title: str, year: object, limits: dict, budget: int = 6) -> None:
    """1337x lists a title without its hash (the magnet sits on the detail page). Resolve the best few that
    look right (name, year, size) so they can be cached, the way the app does when a card is prepared."""
    need = [r for r in cands if not r["infoHash"] and r.get("infoUrl") and year_ok(r["title"], title, year)
            and r["size"] >= limits["minSizeBytes"] and (limits["maxSizeBytes"] is None or r["size"] <= limits["maxSizeBytes"])
            and mig.title_phrase_match(r["title"], mig.expected_titles(title)) and not DANGEROUS_TITLE.search(r["title"])]
    need.sort(key=lambda r: -r["seeders"])
    for r in need[:budget]:
        try:
            body = json.dumps({"infoUrl": r["infoUrl"]}).encode()
            req = urllib.request.Request(f"{API}/api/search/resolve-magnet", data=body,
                                         headers={"Content-Type": "application/json", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as resp:
                r["infoHash"] = mig.info_hash_of(json.loads(resp.read().decode("utf-8")).get("infoHash"), "") or ""
        except Exception:
            pass
        time.sleep(0.5)


def pick(cands: list[dict], title: str, year: object, limits: dict) -> list[dict]:
    unique = {}
    for r in cands:  # the same release shows up in several query variants
        if r["infoHash"] and year_ok(r["title"], title, year):
            unique.setdefault(r["infoHash"], r)
    return mig.select_releases(list(unique.values()), title, limits)


DANGEROUS_EXT = {".exe", ".scr", ".msi", ".bat", ".cmd", ".com", ".vbs", ".jar", ".apk", ".lnk", ".dll", ".dmg", ".pif"}
VIDEO_EXT = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".ts", ".m2ts", ".wmv", ".webm", ".flv", ".mpg", ".mpeg", ".vob", ".iso"}
DANGEROUS_TITLE = re.compile(r"\.(?:exe|scr|msi|bat|cmd|vbs|jar|apk|lnk)(?:$|[\s\]\)])", re.I)
MIN_REAL_VIDEO = 300 * 1024 ** 2
REVIEW_FILE = SEED.parent / "logs" / "torrent-review.jsonl"


def inspect_files(info_hash: str, info_url: str = "") -> list[dict] | None:
    """File list of a torrent from its metadata (no payload download), or None when it can't be resolved in time."""
    body = json.dumps({"magnet": f"magnet:?xt=urn:btih:{info_hash}", "sourceUrl": info_url}).encode()
    try:
        req = urllib.request.Request(f"{API}/api/v2/torrents/inspect-magnet", data=body,
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for _ in range(8):
            if isinstance(data.get("files"), list):
                return data["files"]
            if data.get("status") != "resolving":
                return None
            time.sleep(2)
            with urllib.request.urlopen(f"{API}/api/v2/torrents/inspect-magnet/status?jobId={info_hash}", timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    return None


def verdict(files: list[dict]) -> tuple[str, str]:
    """('ok'|'reject'|'review', reason) from file names and sizes only."""
    def ext(f): return os.path.splitext(str(f.get("path") or f.get("name") or ""))[1].lower()
    def size(f):
        try: return int(f.get("size") or f.get("length") or 0)
        except (TypeError, ValueError): return 0
    bad = [f for f in files if ext(f) in DANGEROUS_EXT]
    if bad:
        return "reject", "contains " + str(bad[0].get("name") or bad[0].get("path"))
    if any(ext(f) in VIDEO_EXT for f in files):
        return "ok", ""
    biggest = max(files, key=size, default=None)
    if biggest and size(biggest) >= MIN_REAL_VIDEO:
        return "review", f"largest file '{biggest.get('name') or biggest.get('path')}' is {size(biggest) // 1024 ** 2} MB but has no video extension"
    return "reject", "no video file"


def vet(releases: list[dict], title: str, year: object, verify: bool) -> list[dict]:
    """Drop executables and fake releases. Releases that might be fine under a wrong extension go to a review list."""
    kept = []
    for r in releases:
        if DANGEROUS_TITLE.search(r["title"]):
            print(f"      x {r['title'][:70]}: executable in the name", flush=True)
            continue
        if verify:
            files = inspect_files(r["infoHash"], r.get("infoUrl", ""))
            if files:
                state, why = verdict(files)
                if state != "ok":
                    print(f"      x {r['title'][:60]}: {why}" + ("  [REVIEW]" if state == "review" else ""), flush=True)
                    if state == "review":
                        REVIEW_FILE.parent.mkdir(parents=True, exist_ok=True)
                        with REVIEW_FILE.open("a", encoding="utf-8") as fh:
                            fh.write(json.dumps({"title": title, "year": year, "release": r["title"], "infoHash": r["infoHash"],
                                                 "size": r["size"], "reason": why}, ensure_ascii=False) + "\n")
                    continue
        kept.append(r)
    return kept


def variants(title: str, year: object) -> list[str]:
    base = str(title).split(":")[0].split(" - ")[0].strip()
    out: list[str] = []
    for q in (f"{title} {year}".strip(), title, f"{base} {year}".strip(), base):
        if q and q not in out:
            out.append(q)
    return out[:4]


def is_series_row(sub: str, node: dict, row: dict) -> bool:
    """A series must never be searched as a movie: its list, its own mediaType or its TMDB link says it is one."""
    return (str(sub).startswith("tv") or node.get("mediaType") in ("tv", "series") or row.get("mediaType") in ("tv", "series")
            or "/tv/" in str(row.get("tmdbUrl") or "") or bool(row.get("firstAirDate")))


def series_only_ids(doc: dict) -> set[str]:
    """TMDB ids that appear only as series in this section (TMDB reuses numbers between movies and series)."""
    tv, movie = set(), set()
    for sub, node in doc["subsections"].items():
        if not isinstance(node, dict):
            continue
        for row in node.get("results") or []:
            tid = str(row.get("tmdbId") or row.get("id") or "")
            if tid:
                (tv if is_series_row(sub, node, row) else movie).add(tid)
    return tv - movie


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
        native = section == "bollywood" or sub == "bollywood"   # already Hindi: no extra Hindi search
        rows = node.get("results") or []
        if pages:
            rows = rows[: pages * int(node.get("pageSize") or 18)]
        for row in rows:
            tid = row.get("tmdbId") or row.get("id")
            key = f"movie:{tid}"
            if not tid or key in seen or is_series_row(sub, node, row):
                continue
            seen.add(key)
            if native:
                NATIVE.add(key)
            if not (titles.get(key) or {}).get("releases"):
                todo.append((key, row))
    return out, path, todo


HINDI = re.compile(r"(?:^|[^a-z0-9])(?:hindi|hin)(?:$|[^a-z0-9])", re.IGNORECASE)


def hindi_todo(section: str, pages: int) -> tuple[dict, Path, list[tuple[str, dict]]]:
    """Listed movies (first ``pages`` pages of each list when set) whose saved releases include no Hindi one.
    Bollywood lists, and the Bollywood list inside Highest rated, are already Hindi and are skipped."""
    out, path, _ = titles_to_scan(section, pages)
    doc = json.loads((SEED / f"{section}.json").read_text(encoding="utf-8"))
    todo, seen = [], set()
    for sub, node in doc["subsections"].items():
        if not isinstance(node, dict) or node.get("mediaType") not in ("movie", "movies"):
            continue
        if section == "bollywood" or sub == "bollywood":
            continue
        rows = node.get("results") or []
        if pages:
            rows = rows[: pages * int(node.get("pageSize") or 18)]
        for row in rows:
            tid = row.get("tmdbId") or row.get("id")
            key = f"movie:{tid}"
            if not tid or key in seen or key in NATIVE or is_series_row(sub, node, row):
                continue
            seen.add(key)
            if not any(HINDI.search(r.get("title", "")) for r in (out["titles"].get(key) or {}).get("releases", [])):
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
        keep = [r for r in entry.get("releases", []) if year_ok(r.get("title", ""), entry.get("title", ""), entry.get("year")) and not DANGEROUS_TITLE.search(r.get("title", ""))]
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
    ap.add_argument("--no-verify-files", action="store_true",
                    help="skip reading each torrent's file list (faster, but fake .exe releases are only caught by name)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--source", choices=("fast", "prowlarr", "all"), default="all",
                    help="fast = normal providers only; prowlarr = Prowlarr only (second pass); all = fast, then Prowlarr if empty")
    ap.add_argument("--add-hindi", action="store_true",
                    help="only look for Hindi releases of listed movies that have none saved; keeps saved releases")
    ap.add_argument("--ignore-rest", action="store_true", help="also search titles that were tried within the rest period")
    args = ap.parse_args()
    global SOURCE
    SOURCE = args.source
    misses = torrent_misses.load()
    record_misses = args.source in ("prowlarr", "all") and not args.dry_run

    for section in [x.strip() for x in args.sections.split(",") if x.strip()]:
        if args.recheck:
            dropped = recheck(section, write=not args.dry_run)
            print(f"[{section}] recheck removed {dropped} releases (different year or executable in the name)", flush=True)
        doc = json.loads((SEED / f"{section}.json").read_text(encoding="utf-8"))
        saved_path = SEED / f"{section}-torrents.json"
        if saved_path.exists():
            data = json.loads(saved_path.read_text(encoding="utf-8"))
            only_tv = series_only_ids(doc)
            stray = [k for k in (data.get("titles") or {}) if k.startswith("movie:") and k.split(":", 1)[1] in only_tv]
            if stray and not args.dry_run:   # series that an earlier run searched as movies
                for k in stray:
                    del data["titles"][k]
                tmp = saved_path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                os.replace(tmp, saved_path)
                print(f"[{section}] removed {len(stray)} series that had been searched as movies", flush=True)
        out, path, todo = hindi_todo(section, args.pages) if args.add_hindi else titles_to_scan(section, args.pages)
        titles, limits = out["titles"], out["limits"]
        miss_prefix = "hindi:" if args.add_hindi else ""
        if not args.ignore_rest:
            resting = [t for t in todo if torrent_misses.resting(misses, miss_prefix + t[0])]
            todo = [t for t in todo if t not in resting]
            if resting:
                print(f"[{section}] {len(resting)} titles resting (nobody had them in the last {torrent_misses.DAYS} days)", flush=True)
        print(f"[{section}] {len(todo)} titles without torrents ({args.source})", flush=True)
        found = 0
        for i, (key, row) in enumerate(todo, 1):
            title, year = str(row.get("title") or ""), row.get("year")
            cands, answered = [], 0
            for q in variants(title, year):
                try:
                    rows = search(q, also_hindi=key not in NATIVE)
                except Exception as exc:
                    print(f"  ! {title}: {q}: {exc}", flush=True)
                    continue
                answered += 1
                cands += [r for r in map(to_release, rows) if r and (not args.add_hindi or HINDI.search(r["title"]))]
                if pick(cands, title, year, limits):
                    break
                time.sleep(0.4)
            if args.add_hindi:
                cands = [c for c in cands if HINDI.search(c["title"])]
            if not pick(cands, title, year, limits):
                resolve_hashes(cands, title, year, limits)
            chosen = vet(pick(cands, title, year, limits), title, year, not args.no_verify_files)
            print(f"  [{i}/{len(todo)}] {title} ({year}): {len(chosen)} releases" + ("" if answered else "  (all searches failed)"), flush=True)
            if record_misses:
                torrent_misses.record(miss_prefix + key, bool(chosen), misses)
            if args.source == "prowlarr":
                time.sleep(2)
            if chosen:
                found += 1
                new = [{k: v for k, v in r.items() if v not in ("", None)} for r in chosen]
                if args.add_hindi:  # keep the saved releases, Hindi ones first
                    have = {r["infoHash"] for r in new}
                    new += [r for r in (titles.get(key) or {}).get("releases", []) if r.get("infoHash") not in have]
                titles[key] = {"title": title, "year": int(year) if year else None, "releases": new}
            if record_misses and i % 10 == 0:
                torrent_misses.save(misses)
            if not args.dry_run and found and i % 10 == 0:  # save as we go, so an interrupted run loses almost nothing
                out["titles"] = dict(sorted(titles.items()))
                tmp = path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                os.replace(tmp, path)
        if record_misses:
            torrent_misses.save(misses)
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
