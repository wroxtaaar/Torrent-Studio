"""Unit tests for the Hollywood section cache merge rules."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "build_hollywood_section_cache.py"
SPEC = importlib.util.spec_from_file_location("hollywood_section_cache", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


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

    def test_complete_core_record_is_detected(self):
        self.assertTrue(MODULE.core_complete({
            "title": "Example", "posterUrl": "/poster", "overview": "Summary",
            "imdbId": "tt1234567", "imdbRating": 7.5,
        }))

    def test_missing_rating_is_a_gap(self):
        self.assertFalse(MODULE.core_complete({
            "title": "Example", "posterUrl": "/poster", "overview": "Summary",
            "imdbId": "tt1234567", "imdbRating": None,
        }))

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
        self.assertTrue(MODULE.core_complete({
            "id": 603, "title": "The Matrix", "posterUrl": "/poster", "overview": "Summary",
        })


if __name__ == "__main__":
    unittest.main()
