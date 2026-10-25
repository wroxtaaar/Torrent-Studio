"""The cache builder fills 3 full pages with watchable titles, and trending keeps adding earlier weeks."""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
THIS_WEEK_TRENDING = 3  # the stub only has 3 trending Bollywood titles this week


def movie(cat_group, n):
    return {"id": n, "tmdbId": n, "title": f"{cat_group} Film {n}", "year": 2025, "releaseDate": "2025-05-05"}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        m = re.match(r"/api/movies/catalogue/([a-z-]+)", url.path)
        if m:
            cat, page = m.group(1), int(qs["page"][0])
            assert qs.get("live") == ["true"]
            group = "bw" if cat.endswith("bollywood") else "hw"
            base = {"popular": 1000, "latest": 5000, "trending": 9000}[cat.split("-")[0]] + (0 if group == "bw" else 100000)
            if cat == "trending-bollywood":
                rows = [movie(group, base + i) for i in range(THIS_WEEK_TRENDING)] if page == 1 else []
                return self.reply({"results": rows, "totalPages": 1})
            rows = [movie(group, base + (page - 1) * 18 + i) for i in range(18)]
            return self.reply({"results": rows, "totalPages": 40})
        if url.path == "/api/search":
            title = qs["q"][0]
            n = int(re.search(r"Film (\d+)", title).group(1))
            # only every third title has a torrent
            rows = [{"title": title, "size": 500 * 1024**2, "magnetUrl": "magnet:?x"}] if n % 3 == 0 else []
            return self.reply(rows)
        if url.path.startswith("/api/tv/catalogue/"):
            return self.reply({"results": [{"id": 1, "title": "Show", "year": 2024}], "totalPages": 1, "totalResults": 1})
        self.send_response(404)
        self.end_headers()


def test_three_full_pages_of_watchable_titles_with_trending_history():
    httpd = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    this_week = (datetime.now(timezone.utc).date() - timedelta(days=datetime.now(timezone.utc).weekday()))
    older = [(this_week - timedelta(days=7 * k)).isoformat() for k in (1, 2)]
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        # Two earlier weeks of Bollywood trending (8 titles each; a few have no torrent).
        weeks = [{"weekOf": w, "catalogues": {"trending-bollywood": [
            {**movie("bw", 70000 + 100 * i + j), "trendingRank": j + 1} for j in range(8)]}} for i, w in enumerate(older)]
        (data / "regional_movie_trending_archive.json").write_text(json.dumps({"version": 1, "weeks": weeks}))
        env = {**os.environ, "HOME_DATA_DIR": str(data), "HOME_API_BASE": f"http://127.0.0.1:{httpd.server_port}",
               "REGIONAL_CACHE_DELAY_SECONDS": "0"}
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_regional_movie_cache.py")],
                              env=env, capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, proc.stdout[-1500:] + proc.stderr[-1500:]
        cache = json.loads((data / "regional_movie_prebuilt_cache.json").read_text())
        archive = json.loads((data / "regional_movie_trending_archive.json").read_text())
    httpd.shutdown()

    for cat, body in cache["catalogues"].items():
        final = body["final"]
        assert len(final) == 54, (cat, len(final))
        for row in final:  # everything shown has a torrent
            key = re.sub(r"[^a-z0-9]+", "", row["title"].casefold()) + "|" + str(row["year"])
            assert cache["movies"][key]["torrentDetails"]["results"], row["title"]

    trending = cache["catalogues"]["trending-bollywood"]["final"]
    weeks_shown = {row.get("trendingWeek") for row in trending if not row.get("trendingFill")}
    assert this_week.isoformat() in weeks_shown and set(older) & weeks_shown  # says which week it trended
    assert any(row.get("trendingFill") for row in trending)  # filled up from popular titles
    # this week is remembered in the archive so it counts again next week
    assert any(w["weekOf"] == this_week.isoformat() for w in archive["weeks"])


def _builder():
    import importlib.util
    spec = importlib.util.spec_from_file_location("regional_builder", ROOT / "scripts" / "build_regional_movie_cache.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_torrent_check_is_not_too_strict(monkeypatch=None):
    b = _builder()
    assert b.base_title("Dhood (Sandstorm)") == "Dhood"
    assert b.base_title("Afreet - A Never Ending Night") == "Afreet"
    assert b.query_variants("Dhood (Sandstorm)", 2026)[:2] == ["Dhood (Sandstorm) 2026", "Dhood (Sandstorm)"]
    rows = [{"title": "Dhood.2026.1080p.WEB-DL", "size": 700 * 1024**2, "magnetUrl": "magnet:?x"},
            {"title": "Dhood.2026.CAMRip", "size": 700 * 1024**2, "magnetUrl": "magnet:?x"},
            {"title": "Dhood.2026.tiny", "size": 10 * 1024**2, "magnetUrl": "magnet:?x"}]
    assert [r["title"] for r in b.usable_rows(rows, "Dhood (Sandstorm)")] == ["Dhood.2026.1080p.WEB-DL"]


def test_only_clear_failures_remove_a_title():
    b = _builder()
    empty = {"status": "empty", "results": []}
    old = {"nexStreamPlayable": True, "releaseDate": "2020-01-01"}
    new = {"nexStreamPlayable": True, "releaseDate": datetime.now(timezone.utc).date().isoformat()}
    assert not b.has_source({"movie": old, "torrentDetails": empty})  # no torrent and no OTT: age alone is not evidence
    assert b.has_source({"movie": old, "torrentDetails": None})  # never scanned: keep
    assert b.has_source({"movie": {**old, "ottAvailability": {"rentProviders": [{"name": "X"}]}}, "torrentDetails": empty})
    assert not b.has_source({"movie": new, "torrentDetails": empty})  # brand new, no torrent, no OTT
    assert b.has_source({"movie": {**new, "ottAvailability": {"streamingProviders": [{"name": "X"}]}}, "torrentDetails": empty})
    assert b.has_source({"movie": new, "torrentDetails": {"status": "ready", "results": [{}]}})
    assert b.has_source({"movie": {}, "torrentDetails": {"status": "unavailable", "results": []}})  # search failed: keep
    assert not b.has_source({"movie": {}, "torrentDetails": empty})
