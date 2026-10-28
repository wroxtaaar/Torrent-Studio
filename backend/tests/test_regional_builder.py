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
        if url.path == "/api/nexstream/resolve":  # NexStream has nothing for any of these titles
            data = json.dumps({"detail": "NexStream could not resolve this title."}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
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
        for row in final:  # NexStream has none of them, so everything shown has a torrent
            assert row.get("nexStreamPlayable") is False
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


def test_only_torrents_confirm_catalogue_source_and_legacy_failures_are_ignored():
    b = _builder()
    empty = {"status": "empty", "results": []}
    assert b.has_source({"movie": {"id": 1}, "torrentDetails": {"status": "ready", "results": [{}]}})
    assert not b.has_source({"movie": {"id": 1}, "torrentDetails": empty})
    assert not b.has_source({"movie": {"id": 1}, "torrentDetails": empty, "nexStream": {"ok": True}})
    assert not b.has_source({"movie": {"id": 603}, "torrentDetails": empty, "nexStream": {"ok": False}})
    assert b.has_source({"movie": {"id": 603}, "torrentDetails": {"status": "ready", "results": [{}]}})
    assert b.has_source({"movie": {"id": 1}, "torrentDetails": {"status": "unavailable", "results": []}})
    assert not b.nexstream_broken({"movie": {"id": 603}})


def test_legacy_nexstream_answers_are_never_preserved_as_vidrift_verification():
    b = _builder()
    legacy = {"nexStream": {"ok": False, "checkedAt": datetime.now(timezone.utc).isoformat()}}
    state = b.nexstream_state({"id": 5}, legacy)
    assert state["ok"] is None
    assert state["provider"] == "VidRift"
    assert state["availabilityVerified"] is False


def test_failure_reports_need_enough_recent_comments():
    import importlib.util
    from datetime import datetime, timezone
    spec = importlib.util.spec_from_file_location("pull_reports", ROOT / "backend" / "maintenance" / "pull_nexstream_reports.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    def comment(tmdb, at):
        return {"body": 'nexstream-report:{"tmdbId":%d,"title":"T","year":2026,"at":"%s"}' % (tmdb, at)}
    comments = [comment(1, "2026-10-20T00:00:00Z"), comment(1, "2026-10-21T00:00:00Z"),  # two reports: failing
                comment(2, "2026-10-21T00:00:00Z"),                                      # one report: not enough
                comment(3, "2026-08-01T00:00:00Z"), comment(3, "2026-08-02T00:00:00Z"),  # too old: forgiven
                {"body": "random chatter"}]
    assert set(module.parse_comments(comments, 2, 30, now)) == {"1"}


def test_detail_score_counts_filled_in_card_details():
    b = _builder()
    full = {"posterUrl": "p", "overview": "o", "imdbRating": 7.1, "nexStreamPlayable": True,
            "ottAvailability": {"streamingProviders": [{"name": "X"}]}}
    assert b.detail_score(full, {"torrentDetails": {"results": [{}]}}) == 6
    bare = {"id": 1}
    assert b.detail_score(bare, {"torrentDetails": {"status": "empty", "results": []}}) == 0
    assert b.detail_score({"ottAvailability": {"status": "not_confirmed", "incomplete": True}}, {}) == 0
