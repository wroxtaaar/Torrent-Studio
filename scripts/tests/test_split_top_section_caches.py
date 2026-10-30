"""Regression tests for metadata-only top-section cache splitting."""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "split_top_section_caches.py"
SPEC = importlib.util.spec_from_file_location("split_top_section_caches", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class MarvelSeriesSplitterTests(unittest.TestCase):
    def test_legacy_marvel_uses_only_top_level_catalogue_cards(self):
        payload = {
            "results": [{
                "key": "wandavision",
                "title": "WandaVision",
                "year": 2021,
                "tmdbId": 85271,
                "posterUrl": "/poster.jpg",
                "torrent": {"results": [{"title": "WandaVision S01E01 1080p"}]},
                "nexStream": {"streams": [{"title": "WandaVision S01E01 WEB-DL"}]},
                "episodes": [{
                    "title": "WandaVision S01E01",
                    "tmdbId": 999001,
                    "posterUrl": "/episode.jpg",
                    "torrentResults": [{"title": "WandaVision S01E01 1080p"}],
                }],
            }],
        }

        rows = MODULE.collect_top_level_results(payload)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "WandaVision")
        self.assertEqual(rows[0]["tmdbId"], 85271)
        self.assertNotIn("torrent", rows[0])
        self.assertNotIn("nexStream", rows[0])
        self.assertNotIn("episodes", rows[0])

    def test_nested_episode_titles_are_not_collected(self):
        payload = {
            "results": [{
                "title": "Loki",
                "year": 2021,
                "tmdbId": 84958,
                "posterUrl": "/loki.jpg",
                "episodes": [{
                    "title": "Loki S01E01 1080p WEB-DL",
                    "tmdbId": 999002,
                    "posterUrl": "/episode.jpg",
                }],
            }],
        }

        rows = MODULE.collect_top_level_results(payload)

        self.assertEqual([row["title"] for row in rows], ["Loki"])


if __name__ == "__main__":
    unittest.main()
