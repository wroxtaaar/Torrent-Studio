#!/usr/bin/env python3
"""Build persistent regional movie and web-series catalogues plus movie torrent searches.

Each movie/series catalogue is filled independently to 50 unique eligible entries
when the API can supply them. Titles may intentionally occur in multiple catalogues.
A failed page does not abort other catalogues, and prior good snapshots are retained.
"""
import json, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(os.getenv("HOME_DATA_DIR", "/home/ubuntu/home-data"))
API = os.getenv("HOME_API_BASE", "http://127.0.0.1:10000").rstrip("/")
CACHE = BASE / "regional_movie_prebuilt_cache.json"
TV_CACHE = BASE / "regional_tv_prebuilt_cache.json"
STATE = BASE / "regional_movie_prebuilt_state.json"
CATALOGUES = (
    "popular-bollywood", "trending-bollywood", "latest-bollywood",
    "popular-hollywood", "trending-hollywood", "latest-hollywood",
)
# Target for the TV catalogues. Movie catalogues use FINAL_PER_CATALOGUE below.
TARGET_PER_CATALOGUE = int(os.getenv("REGIONAL_CACHE_MOVIES_PER_CATALOGUE", "50"))
PAGE_LIMIT = int(os.getenv("REGIONAL_CACHE_PAGES", "30"))
TORRENT_LIMIT = 50
# Set REGIONAL_CACHE_TORRENT_SCAN=false to refresh only catalogue pages and keep the
# torrent matches from the previous build (torrent sites are slow/blocked on CI runners).
TORRENT_SCAN = os.getenv("REGIONAL_CACHE_TORRENT_SCAN", "true").strip().lower() not in ("0", "false", "no", "off")
MAX_SIZE = 5 * 1024**3
# Same lower bound the app applies when it reads saved torrents; a row below it would be hidden anyway.
MIN_SIZE = int(os.getenv("REGIONAL_CACHE_MIN_SIZE_MB", "100")) * 1024**2
SCAN_VERSION = 2  # bump to force one re-scan of older (possibly too strict) "empty" results
BAD_QUALITY = re.compile(r"(?:camrip|hdcam|telesync|telecine|dvdscr|screener|workprint)", re.I)


def request(path, timeout=90):
    req = urllib.request.Request(API + path, headers={"Accept": "application/json", "User-Agent": "HomeRegionalCacheBuilder/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s or "").casefold())


def movie_key(movie):
    return norm(movie.get("title")) + "|" + str(movie.get("year") or "")


FINAL_PER_CATALOGUE = int(os.getenv("REGIONAL_CACHE_FINAL_PER_CATALOGUE", "54"))  # 3 pages x 18
MAX_CANDIDATES = int(os.getenv("REGIONAL_CACHE_MAX_CANDIDATES", "450"))
ARCHIVE = BASE / "regional_movie_trending_archive.json"
ORDER = ("popular-bollywood", "popular-hollywood", "latest-bollywood", "latest-hollywood",
         "trending-bollywood", "trending-hollywood")
# A scanned title is reused for a while so a weekly run only scans what is new.
REUSE_DAYS = {"ready": 14, "empty": 1}
NEXSTREAM_REUSE_DAYS = 7


def week_start(today=None):
    today = today or datetime.now(timezone.utc).date()
    return (today - timedelta(days=today.weekday())).isoformat()


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_nexstream_failures():
    """tmdb ids users reported as not playable (written by maintenance/pull_nexstream_reports.py)."""
    try:
        data = json.loads((BASE / "nexstream_failures.json").read_text(encoding="utf-8"))
        return {int(k) for k in (data.get("movies") or {})}
    except (OSError, ValueError, TypeError, AttributeError):
        return set()


NEXSTREAM_FAILED = load_nexstream_failures()


def movie_tmdb_id(movie):
    value = movie.get("tmdbId") or movie.get("id")
    return int(value) if str(value).isdigit() else 0


def nexstream_broken(entry):
    """True when NexStream is known not to play this title: its API said no, or users reported it."""
    tmdb_id = movie_tmdb_id(entry["movie"])
    return (entry.get("nexStream") or {}).get("ok") is False or (tmdb_id > 0 and tmdb_id in NEXSTREAM_FAILED)


def has_source(entry):
    """Show a title when it has a usable torrent, or NexStream is not known to be broken for it.

    NexStream cannot be verified from a server, so only a definite "no" (its API refusing the title, or
    users' failure reports) takes it away. A scan that never ran or whose searches failed ("unavailable")
    is not evidence of absence either: keep the title."""
    details = entry.get("torrentDetails")
    if isinstance(details, dict) and details.get("results"):
        return True
    if not nexstream_broken(entry):
        return True
    return not isinstance(details, dict) or details.get("status") == "unavailable"


TRANSIENT_NEXSTREAM = ("could not connect", "invalid response", "http 5", "http 429", "http 403", "not configured", "timed out")


def check_nexstream(tmdb_id):
    """Ask NexStream (through the local backend) whether it has this movie: True, False, or None when unsure."""
    if tmdb_id <= 0:
        return None
    try:
        data = request(f"/api/nexstream/resolve?type=movie&tmdb_id={tmdb_id}", timeout=30)
        return True if data.get("success") and data.get("sources") else False
    except urllib.error.HTTPError as exc:
        try:
            detail = str(json.loads(exc.read().decode("utf-8")).get("detail") or "")
        except (ValueError, OSError):
            return None
        if exc.code == 502 and detail and not any(word in detail.casefold() for word in TRANSIENT_NEXSTREAM):
            return False  # NexStream answered and has nothing for this title
        return None
    except Exception:
        return None


def nexstream_state(movie, old_entry):
    """Reuse a definite answer for NEXSTREAM_REUSE_DAYS, otherwise ask again."""
    old = (old_entry or {}).get("nexStream")
    if isinstance(old, dict) and old.get("ok") in (True, False):
        try:
            checked = datetime.fromisoformat(str(old.get("checkedAt")).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - checked < timedelta(days=NEXSTREAM_REUSE_DAYS):
                return old
        except ValueError:
            pass
    return {"ok": check_nexstream(movie_tmdb_id(movie)), "checkedAt": datetime.now(timezone.utc).isoformat()}


def fresh_enough(details):
    if not isinstance(details, dict):
        return False
    days = REUSE_DAYS.get(details.get("status"))
    if details.get("status") == "empty" and details.get("scanVersion") != SCAN_VERSION:
        return False
    try:
        scanned = datetime.fromisoformat(str(details.get("scannedAt")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return days is not None and (datetime.now(timezone.utc) - scanned) < timedelta(days=days)


def base_title(title):
    """Title without a bracketed alias or a subtitle: 'Dhood (Sandstorm)' -> 'Dhood'."""
    base = re.split(r"\s+[-\u2013\u2014:]\s+|\s*\(", str(title or ""), maxsplit=1)[0].strip()
    return base if len(norm(base)) >= 3 else str(title or "").strip()


def query_variants(title, year):
    base = base_title(title)
    out = []
    for q in (title + (" " + str(year) if year else ""), title, base + (" " + str(year) if year else ""), base):
        q = q.strip()
        if q and q not in out:
            out.append(q)
    return out[:4]


def usable_rows(rows, title):
    targets = {t for t in (norm(title), norm(base_title(title))) if t}
    good = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("title") or "")
        media = str(row.get("mediaTitle") or "")
        try:
            size = int(row.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        has_link = bool(row.get("magnetUrl") or row.get("downloadUrl") or row.get("sourceUrl"))
        if not has_link or size < MIN_SIZE or size > MAX_SIZE or BAD_QUALITY.search(name):
            continue
        if any(t in norm(name) or t in norm(media) for t in targets):
            good.append(row)
    return good


def scan_torrents(movie, old_details):
    """Search torrents for one movie with several query shapes; keeps the old result when searches fail.

    "empty" is only recorded after every variant answered and none had a usable release, because
    the app trusts the saved result and never searches live for catalogue cards.
    """
    title = str(movie.get("title") or "").strip()
    year = movie.get("year")
    variants = query_variants(title, year)
    query = variants[0] if variants else title
    if not TORRENT_SCAN:
        return old_details
    if fresh_enough(old_details):
        return old_details
    answered = 0
    for variant in variants:
        try:
            response = request("/api/search?q=" + urllib.parse.quote(variant) + "&limit=" + str(TORRENT_LIMIT), timeout=150)
        except Exception as exc:
            print(json.dumps({"event": "torrent_error", "title": title, "query": variant, "error": str(exc)}), flush=True)
            continue
        answered += 1
        rows = response if isinstance(response, list) else response.get("results", response.get("torrents", []))
        good = usable_rows(rows, title)
        time.sleep(float(os.getenv("REGIONAL_CACHE_DELAY_SECONDS", "0.4")))
        if good:
            return {"query": variant, "results": good, "scannedAt": datetime.now(timezone.utc).isoformat(),
                    "status": "ready", "scanVersion": SCAN_VERSION}
    if answered < len(variants):
        # Some searches failed: not proof of "nothing". Keep what we knew, or mark unknown.
        return old_details or {"query": query, "results": [], "status": "unavailable"}
    return {"query": query, "results": [], "scannedAt": datetime.now(timezone.utc).isoformat(),
            "status": "empty", "scanVersion": SCAN_VERSION}


def api_candidates(cat, failures):
    """Walk a catalogue's live pages; every title is a candidate (NexStream playback is marked, not filtered)."""
    for page in range(1, PAGE_LIMIT + 1):
        data = error = None
        for attempt in range(1, 4):
            try:
                data = request("/api/movies/catalogue/" + cat + "?page=" + str(page) + "&released_only=true&live=true")
                break
            except Exception as exc:
                error = str(exc)
                if attempt < 3:
                    time.sleep(attempt)
        if data is None:
            print(json.dumps({"event": "catalogue_error", "catalogue": cat, "page": page, "error": error}), flush=True)
            failures.append(cat)
            return
        rows = [r for r in data.get("results", []) if isinstance(r, dict) and str(r.get("title") or "").strip()]
        print(json.dumps({"event": "catalogue_page", "catalogue": cat, "page": page, "pageMovies": len(rows)}), flush=True)
        yield from rows
        if page >= max(1, int(data.get("totalPages") or 1)):
            return
        time.sleep(float(os.getenv("REGIONAL_CACHE_DELAY_SECONDS", "0.4")))


def trending_candidates(cat, popular_rows, failures):
    """This week's trending, then earlier weeks from the archive, then popular titles to fill the gap."""
    this_week = week_start()
    current = []
    for rank, row in enumerate(api_candidates(cat, failures), 1):
        current.append({**row, "trendingWeek": this_week, "trendingRank": rank})
    archive = read_json(ARCHIVE, {"version": 1, "weeks": []})
    weeks = [w for w in archive.get("weeks", []) if isinstance(w, dict) and w.get("weekOf") != this_week]
    if current:  # remember this week so it keeps counting in later weeks
        entry = next((w for w in archive.get("weeks", []) if isinstance(w, dict) and w.get("weekOf") == this_week), None)
        entry = entry or {"weekOf": this_week, "catalogues": {}}
        entry.setdefault("catalogues", {})[cat] = current
        weeks.append(entry)
        weeks.sort(key=lambda w: str(w.get("weekOf") or ""), reverse=True)
        archive.update({"version": 1, "builtAt": datetime.now(timezone.utc).isoformat(), "weeks": weeks[:52]})
        atomic_json(ARCHIVE, archive)
    yield from current
    for week in sorted(weeks, key=lambda w: str(w.get("weekOf") or ""), reverse=True):
        for rank, row in enumerate((week.get("catalogues") or {}).get(cat) or [], 1):
            if isinstance(row, dict):
                yield {**row, "trendingWeek": week.get("weekOf"), "trendingRank": row.get("trendingRank") or rank}
    for row in popular_rows:
        yield {**row, "trendingFill": True}


def build_movies(old):
    """Build each catalogue's finished list: only titles that can be watched, until 3 pages are full."""
    old_movies = old.get("movies", {})
    movies, catalogues, failures, candidates_by_cat = {}, {}, [], {}
    for cat in ORDER:
        region = "bollywood" if cat.endswith("bollywood") else "hollywood"
        if cat.startswith("trending-"):
            generator = trending_candidates(cat, candidates_by_cat.get("popular-" + region, []), failures)
        else:
            generator = api_candidates(cat, failures)
        final, seen, checked = [], set(), 0
        collected = []
        for movie in generator:
            key = movie_key(movie)
            if key in seen or key == "|":
                continue
            seen.add(key)
            checked += 1
            collected.append(movie)
            entry = movies.get(key)
            if entry is None:
                entry = movies[key] = {"movie": movie, "catalogues": []}
                entry["torrentDetails"] = scan_torrents(movie, (old_movies.get(key) or {}).get("torrentDetails"))
                entry["nexStream"] = nexstream_state(movie, old_movies.get(key))
            if cat not in entry["catalogues"]:
                entry["catalogues"].append(cat)
            if has_source(entry):
                movie = {**movie, "nexStreamPlayable": not nexstream_broken(entry)}  # False hides the Play button
                final.append(movie)
                if len(final) % 10 == 0:
                    print(json.dumps({"event": "progress", "catalogue": cat, "shown": len(final), "checked": checked}), flush=True)
            if len(final) >= FINAL_PER_CATALOGUE or checked >= MAX_CANDIDATES:
                break
        candidates_by_cat[cat] = collected
        if cat in failures and not final:
            prior = (old.get("catalogues", {}).get(cat) or {}).get("final")
            if prior:  # a failed refresh never blanks a catalogue that worked before
                final = prior
                print(json.dumps({"event": "catalogue_preserved", "catalogue": cat, "movies": len(final)}), flush=True)
        catalogues[cat] = {
            "builtAt": datetime.now(timezone.utc).isoformat(),
            "targetMovies": FINAL_PER_CATALOGUE,
            "movieCount": len(final),
            "candidatesChecked": checked,
            "final": final,
            "status": "ready" if len(final) >= FINAL_PER_CATALOGUE else "partial",
        }
        print(json.dumps({"event": "catalogue_cached", "catalogue": cat, "shown": len(final), "checked": checked,
                          "status": catalogues[cat]["status"]}), flush=True)
    return movies, catalogues, failures


def main():
    old = {}
    if CACHE.exists():
        try:
            old = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            old = {}
    cache = {"version": 3, "builtAt": old.get("builtAt"), "status": "building",
             "targetPerCatalogue": FINAL_PER_CATALOGUE, "catalogues": {}, "movies": {}}
    movies, cache["catalogues"], failed_catalogues = build_movies(old)
    cache["movies"] = movies
    atomic_json(CACHE, cache)

    # Prebuild six Indian/Hollywood TV-series catalogues separately from movies.
    # These pages are served by the backend as a persistent snapshot, so browsing
    # the section does not require live TMDB requests on every visit.
    tv_old = {}
    if TV_CACHE.exists():
        try:
            candidate = json.loads(TV_CACHE.read_text(encoding="utf-8"))
            if int(candidate.get("version") or 0) >= 3:
                tv_old = candidate
        except Exception:
            tv_old = {}
    tv_cache = {
        "version": 3,
        "builtAt": tv_old.get("builtAt"),
        "catalogues": tv_old.get("catalogues", {}),
        "targetPerCatalogue": TARGET_PER_CATALOGUE,
        "status": "building",
    }
    tv_catalogues = (
        "indian-popular", "indian-trending", "indian-latest",
        "hollywood-popular", "hollywood-trending", "hollywood-latest",
    )
    failed_tv_catalogues = []
    for cat in tv_catalogues:
        prior = tv_cache["catalogues"].get(cat, {})
        pages = []
        seen = set()
        total_pages = PAGE_LIMIT
        failed = False
        for page in range(1, PAGE_LIMIT + 1):
            data = None
            error = None
            for attempt in range(1, 4):
                try:
                    data = request("/api/tv/catalogue/" + cat + "?page=" + str(page) + "&refresh=true")
                    break
                except Exception as exc:
                    error = str(exc)
                    if attempt < 3:
                        time.sleep(attempt)
            if data is None:
                print(json.dumps({"event": "tv_catalogue_error", "catalogue": cat, "page": page, "error": error}), flush=True)
                failed = True
                break
            rows = data.get("results", [])
            pages.append({
                "page": page,
                "results": rows,
                "totalPages": data.get("totalPages", 1),
                "totalResults": data.get("totalResults", 0),
            })
            for show in rows:
                if not isinstance(show, dict) or not str(show.get("title") or "").strip():
                    continue
                seen.add(str(show.get("id") or (norm(show.get("title")) + "|" + str(show.get("year") or ""))))
            try:
                total_pages = max(1, int(data.get("totalPages") or 1))
            except (TypeError, ValueError):
                total_pages = PAGE_LIMIT
            print(json.dumps({"event": "tv_catalogue_page", "catalogue": cat, "page": page, "pageSeries": len(rows), "uniqueSeries": len(seen), "target": TARGET_PER_CATALOGUE}), flush=True)
            if len(seen) >= TARGET_PER_CATALOGUE or page >= total_pages:
                break
            time.sleep(float(os.getenv("REGIONAL_CACHE_DELAY_SECONDS", "0.4")))
        if failed:
            failed_tv_catalogues.append(cat)
            if prior.get("pages"):
                pages = prior["pages"]
                print(json.dumps({"event": "tv_catalogue_preserved", "catalogue": cat, "pages": len(pages)}), flush=True)
        count = len({str(show.get("id") or (norm(show.get("title")) + "|" + str(show.get("year") or ""))) for p in pages for show in p.get("results", []) if isinstance(show, dict) and show.get("title")})
        tv_cache["catalogues"][cat] = {
            "builtAt": datetime.now(timezone.utc).isoformat(),
            "targetSeries": TARGET_PER_CATALOGUE,
            "seriesCount": count,
            "totalResults": max((int(p.get("totalResults") or 0) for p in pages), default=count),
            "pages": pages,
            "status": "ready" if count >= TARGET_PER_CATALOGUE else "partial",
        }
        tv_cache["builtAt"] = datetime.now(timezone.utc).isoformat()
        tv_cache["status"] = "building"
        atomic_json(TV_CACHE, tv_cache)
        print(json.dumps({"event": "tv_catalogue_cached", "catalogue": cat, "series": count, "status": tv_cache["catalogues"][cat]["status"]}), flush=True)
    tv_cache["builtAt"] = datetime.now(timezone.utc).isoformat()
    tv_cache["status"] = "partial" if failed_tv_catalogues or any(v.get("status") != "ready" for v in tv_cache["catalogues"].values()) else "ready"
    tv_cache["failedCatalogues"] = failed_tv_catalogues
    atomic_json(TV_CACHE, tv_cache)
    print(json.dumps({"event": "tv_catalogues_complete", "status": tv_cache["status"], "catalogues": {k: v.get("seriesCount", 0) for k, v in tv_cache["catalogues"].items()}, "file": str(TV_CACHE)}), flush=True)

    cache["movies"] = movies
    cache["builtAt"] = datetime.now(timezone.utc).isoformat()
    cache["status"] = "partial" if failed_catalogues or any(v.get("status") != "ready" for v in cache["catalogues"].values()) else "ready"
    cache["movieCount"] = len(movies)
    cache["torrentMovieCount"] = sum(bool((x.get("torrentDetails") or {}).get("results")) for x in movies.values())
    cache["failedCatalogues"] = failed_catalogues
    atomic_json(CACHE, cache)
    print(json.dumps({"event": "complete", "status": cache["status"], "failedCatalogues": failed_catalogues, "failedTvCatalogues": failed_tv_catalogues, "catalogues": {k: v.get("movieCount", 0) for k, v in cache["catalogues"].items()}, "movieCount": cache["movieCount"], "torrentMovieCount": cache["torrentMovieCount"], "file": str(CACHE)}), flush=True)
    if failed_catalogues or failed_tv_catalogues:
        sys.exit(1)


if __name__ == "__main__":
    main()
