"""Unit tests for the Hollywood section cache merge rules."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import urllib.error
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "build_hollywood_section_cache.py"
SPEC = importlib.util.spec_from_file_location("hollywood_section_cache", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

TORRENT_SCRIPT = Path(__file__).resolve().parents[1] / "build_hollywood_torrent_cache.py"
TORRENT_SPEC = importlib.util.spec_from_file_location("hollywood_torrent_cache", TORRENT_SCRIPT)
TORRENT_MODULE = importlib.util.module_from_spec(TORRENT_SPEC)
assert TORRENT_SPEC and TORRENT_SPEC.loader
TORRENT_SPEC.loader.exec_module(TORRENT_MODULE)


class HollywoodCacheTests(unittest.TestCase):
    def test_highest_rated_is_not_a_hollywood_subsection(self):
        self.assertEqual(set(MODULE.SUBSECTIONS), {"popular", "trending", "latest"})
        self.assertNotIn("highestRated", MODULE.SUBSECTIONS)

    def test_missing_mode_preserves_existing_values(self):
        old = {"title": "Example", "posterUrl": "known-poster", "imdbRating": 8.1, "overview": ""}
        fresh = {"title": "Changed title", "posterUrl": "new-poster", "imdbRating": 9.0, "overview": "Synopsis"}
        merged = MODULE.merge_missing(old, fresh)
        self.assertEqual(merged["title"], "Example")
        self.assertEqual(merged["posterUrl"], "known-poster")
        self.assertEqual(merged["imdbRating"], 8.1)
        self.assertEqual(merged["overview"], "Synopsis")

    def test_deep_mode_preserves_existing_good_imdb_values(self):
        merged = MODULE.merge_deep(
            {"id": 603, "tmdbId": 603, "imdbId": "tt0133093", "imdbRating": 8.7},
            {"id": 603, "tmdbId": 603, "imdbId": "", "imdbRating": None, "overview": "Summary"},
        )
        self.assertEqual(merged["imdbId"], "tt0133093")
        self.assertEqual(merged["imdbRating"], 8.7)
        self.assertEqual(merged["overview"], "Summary")

    def test_explicit_tmdb_id_uses_existing_id(self):
        self.assertEqual(
            MODULE.with_explicit_tmdb_id({"id": 1807573, "title": "Chirp"})["tmdbId"],
            1807573,
        )

    def test_missing_mode_requires_tmdb_and_imdb_identifiers_and_rating(self):
        complete = {
            "id": 603, "tmdbId": 603, "title": "Example", "posterUrl": "/poster",
            "overview": "Summary", "imdbId": "tt0133093", "imdbRating": 8.7,
            "imdbRatingStatus": "found", "imdbCheckedAt": 1761690000,
        }
        self.assertTrue(MODULE.core_complete(complete))
        for field in (
            "tmdbId", "imdbId", "imdbRating", "imdbRatingStatus", "imdbCheckedAt",
            "posterUrl", "overview",
        ):
            incomplete = dict(complete)
            incomplete.pop(field)
            self.assertFalse(MODULE.core_complete(incomplete), field)

    def test_identity_prefers_imdb_id(self):
        self.assertEqual(
            MODULE.title_key({"title": "Old title", "imdbId": "TT1234567"}),
            MODULE.title_key({"title": "Renamed title", "imdbId": "tt1234567"}),
        )


    def test_metadata_cache_strips_torrent_fields(self):
        row = {"id": 603, "title": "The Matrix", "torrentMatch": {"infoHash": "abc"},
               "torrentMatches": [{"infoHash": "abc"}], "torrentDetails": {"results": []}}
        cleaned = MODULE.metadata_only(row)
        self.assertEqual(cleaned, {"id": 603, "title": "The Matrix"})

    def test_metadata_completeness_uses_api_fields(self):
        self.assertFalse(MODULE.core_complete({
            "id": 603, "tmdbId": 603, "title": "The Matrix",
            "posterUrl": "/poster", "overview": "Summary",
        }))

    def test_missing_imdb_id_and_rating_are_enriched_from_existing_api(self):
        movie = {"id": 1807573, "tmdbId": 1807573, "title": "Chirp", "year": 2024}
        called = {}

        def fake_request_json(url, *, label, retries=3):
            called["url"] = url
            called["label"] = label
            return {"matched": 1, "results": [{
                "query": "Chirp (2024)", "status": "found", "imdbId": "tt1234567",
                "imdbRating": 7.6, "imdbVotes": "1250", "checkedAt": 1761690000,
            }]}

        with patch.object(MODULE, "request_json", fake_request_json):
            result = MODULE.enrich_imdb([movie], "latest")
        self.assertEqual(result["idsResolved"], 1)
        self.assertEqual(result["ratingsFetched"], 1)
        self.assertEqual(movie["imdbId"], "tt1234567")
        self.assertEqual(movie["imdbRating"], 7.6)
        self.assertEqual(movie["imdbCheckedAt"], 1761690000)
        self.assertIn("persist=false", called["url"])
        self.assertIn("refresh_incomplete=true", called["url"])

    def test_existing_imdb_id_and_rating_are_preserved_after_failed_refresh(self):
        movie = {
            "title": "Chirp", "year": 2024, "imdbId": "tt1234567",
            "imdbRating": 6.9, "imdbRatingStatus": "found",
        }
        with patch.object(MODULE, "request_json", side_effect=RuntimeError("API unavailable")):
            MODULE.enrich_imdb([movie], "latest")
        self.assertEqual(movie["imdbId"], "tt1234567")
        self.assertEqual(movie["imdbRating"], 6.9)
        self.assertEqual(movie["imdbRatingStatus"], "found")

    def test_failed_imdb_lookup_does_not_replace_existing_rating(self):
        movie = {"title": "Chirp", "year": 2024, "imdbRating": 6.9}
        with patch.object(MODULE, "request_json", lambda *args, **kwargs: {"results": [{
                "query": "Chirp (2024)", "status": "unavailable",
            }]}):
            MODULE.enrich_imdb([movie], "latest")
        self.assertEqual(movie["imdbRating"], 6.9)
        self.assertEqual(movie["imdbRatingStatus"], "unavailable")

    def test_tmdb_details_fill_only_missing_fields(self):
        movie = {"tmdbId": 603, "overview": "Known overview", "posterUrl": ""}
        with patch.object(MODULE, "request_json", lambda *args, **kwargs: {
                "overview": "Fresh overview", "posterUrl": "https://image.test/poster.jpg",
            }):
            filled = MODULE.fill_tmdb_metadata([movie], "popular")
        self.assertEqual(filled, 1)
        self.assertEqual(movie["overview"], "Known overview")
        self.assertEqual(movie["posterUrl"], "https://image.test/poster.jpg")

    def test_catalogue_scan_is_limited_to_three_pages_and_54_records(self):
        pages = []

        def fake_page(key, page):
            pages.append(page)
            return {
                "totalPages": 12,
                "results": [{"id": (page * 100) + index, "title": f"Film {page}-{index}"} for index in range(25)],
            }

        with patch.object(MODULE, "request_page", fake_page), patch.object(MODULE.time, "sleep"):
            rows, info = MODULE.fetch_catalogue("popular-hollywood", [], "deep")
        self.assertEqual(pages, [1, 2, 3])
        self.assertEqual(len(rows), 54)
        self.assertEqual(info["pageCount"], 3)
        self.assertTrue(all(row["tmdbId"] == row["id"] for row in rows))

    def test_missing_mode_enriches_incomplete_cached_records_without_refetching_pages(self):
        cached = [{
            "id": 603, "tmdbId": 603, "title": "The Matrix", "posterUrl": "/poster",
            "overview": "Summary", "imdbId": "tt0133093",
        }]

        def fake_page(key, page):
            raise AssertionError("Missing mode should enrich the refresh-seed row in place")

        with patch.object(MODULE, "request_page", fake_page):
            rows, info = MODULE.fetch_catalogue("popular-hollywood", cached, "missing")
        self.assertEqual(info["source"], "refresh_seed")
        self.assertFalse(info["skipped"])
        self.assertIn("missing_imdb_rating", MODULE.incomplete_reasons(rows[0]))

    def test_missing_mode_skips_complete_cached_records_without_refetching(self):
        complete = {
            "id": 603, "tmdbId": 603, "title": "The Matrix", "posterUrl": "/poster",
            "overview": "Summary", "imdbId": "tt0133093", "imdbRating": 8.7,
            "imdbRatingStatus": "found", "imdbCheckedAt": 1761690000,
        }
        with patch.object(
            MODULE, "request_page",
            side_effect=AssertionError("Complete refresh-seed data should not be fetched again"),
        ):
            rows, info = MODULE.fetch_catalogue("popular-hollywood", [complete], "missing")
        self.assertTrue(info["skipped"])
        self.assertEqual(rows, [complete])

    def test_api_retry_logs_and_retries_transient_failures(self):
        responses = [urllib.error.URLError("temporary"), io.BytesIO(b'{"status":"ready"}')]
        sleep_mock = Mock()
        with patch.object(MODULE.urllib.request, "urlopen", Mock(side_effect=responses)), patch.object(
            MODULE.time, "sleep", sleep_mock,
        ):
            response = MODULE.request_json("http://api.test/health", label="health")
        self.assertEqual(response, {"status": "ready"})
        self.assertEqual(sleep_mock.call_count, 1)

    def test_api_rate_limit_is_not_retried_immediately(self):
        error = urllib.error.HTTPError("http://api.test/", 429, "rate limited", {}, None)
        urlopen = Mock(side_effect=error)
        with patch.object(MODULE.urllib.request, "urlopen", urlopen), self.assertRaises(
            urllib.error.HTTPError,
        ):
            MODULE.request_json("http://api.test/ratings", label="IMDb ratings")
        self.assertEqual(urlopen.call_count, 1)

    def test_catalogue_and_enrichment_requests_do_not_target_torrent_searches(self):
        self.assertIn("/api/movies/catalogue/popular-hollywood?", MODULE.catalogue_url("popular-hollywood", 1))
        self.assertIn("/api/catalogue/imdb-ratings?", MODULE._imdb_lookup_url([{
            "title": "Film", "tmdbId": 123,
        }])[0])
        self.assertNotIn("/api/torrent", MODULE.catalogue_url("popular-hollywood", 1))

    def test_main_writes_only_three_54_record_subsections_to_refresh_seed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            seed = Path(temp_dir)
            (seed / "hollywood.json").unlink(missing_ok=True)

            def fake_page(key, page):
                return {
                    "totalPages": 3,
                    "results": [
                        {"id": page * 100 + index, "title": f"{key} film {page}-{index}"}
                        for index in range(18)
                    ],
                }

            with (
                patch.object(MODULE, "SEED", seed),
                patch.object(MODULE, "OUTPUT", seed / "hollywood.json"),
                patch.object(MODULE, "request_json", lambda *args, **kwargs: {"status": "ready"}),
                patch.object(MODULE, "request_page", fake_page),
                patch.object(MODULE, "enrich_imdb", lambda *args: {"requested": 0, "idsResolved": 0, "ratingsFetched": 0}),
                patch.object(MODULE, "fill_tmdb_metadata", lambda *args: 0),
                patch.object(MODULE.time, "sleep"),
                patch("sys.argv", ["build_hollywood_section_cache.py", "deep"]),
            ):
                self.assertEqual(MODULE.main(), 0)

            document = json.loads((seed / "hollywood.json").read_text(encoding="utf-8"))
        self.assertEqual(set(document["subsections"]), {"popular", "trending", "latest"})
        for section in document["subsections"].values():
            self.assertEqual(len(section["results"]), 54)
            self.assertEqual(section["pageCount"], 3)
        self.assertEqual(document["safety"]["torrentSearches"], 0)
        self.assertEqual(document["safety"]["activeApplicationCacheWrites"], 0)



class HollywoodTorrentCacheTests(unittest.TestCase):
    def test_legacy_release_is_reduced_to_torrent_fields(self):
        release = TORRENT_MODULE.torrent_release({
            "tmdbId": 603, "title": "The Matrix (1999) 1080p",
            "infoHash": "abc123", "magnetUrl": "magnet:?xt=urn:btih:abc123",
            "overview": "This belongs in metadata, not torrent cache",
        })
        self.assertEqual(release["infoHash"], "abc123")
        self.assertNotIn("overview", release)

    def test_duplicate_releases_are_not_added_twice(self):
        target = {"matches": [{"infoHash": "abc123"}]}
        TORRENT_MODULE.add_release(target, {"infoHash": "abc123"})
        self.assertEqual(len(target["matches"]), 1)

    def test_torrent_cache_uses_tmdb_id(self):
        self.assertEqual(TORRENT_MODULE.movie_id({"id": 603}), "603")

if __name__ == "__main__":
    unittest.main()
