import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "build_episode_metadata_cache.py"
SPEC = importlib.util.spec_from_file_location("build_episode_metadata_cache", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, get_response, **_kwargs):
        self.get_response = get_response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, **kwargs):
        return await self.get_response(url, **kwargs)


class EpisodeMetadataCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.seed = self.root / "seed"
        self.seed.mkdir()
        self.cache_path = self.seed / "runtime" / "nexstream_episode_metadata_cache.json"
        for filename in MODULE.SECTION_FILES:
            (self.seed / filename).write_text(json.dumps({
                "section": filename[:-5],
                "subsections": {
                    "movies": {
                        "mediaType": "movie",
                        "results": [{"tmdbId": 999}],
                    },
                    "series": {
                        "mediaType": "tv",
                        "results": [{"tmdbId": 101, "title": "Show"}],
                    },
                    "anime": {
                        "mediaType": "anime",
                        "results": [{"id": 102, "title": "Anime"}],
                    },
                },
            }), encoding="utf-8")
        (self.seed / "unrelated.json").write_text("not parsed", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def remove_anime_test_record(self):
        for filename in MODULE.SECTION_FILES:
            path = self.seed / filename
            document = json.loads(path.read_text(encoding="utf-8"))
            document["subsections"]["anime"]["results"] = []
            path.write_text(json.dumps(document), encoding="utf-8")

    @staticmethod
    def detail_payload(seasons=(1, 2)):
        return {
            "seasons": [
                {"season_number": number, "name": f"Season {number}", "episode_count": 1}
                for number in seasons
            ],
        }

    @staticmethod
    def episode_payload(number):
        return {
            "episodes": [{
                "episode_number": number,
                "name": f"Episode {number}",
                "overview": "Description",
                "air_date": "2024-01-01",
                "still_path": "/still.jpg",
            }],
        }

    def test_reads_only_nine_section_files_and_deduplicates_tmdb_ids(self):
        self.assertEqual(MODULE.catalogue_tmdb_ids(self.seed), [101, 102])

    def test_build_fetches_every_missing_season_and_persists_each_completion(self):
        calls = []
        persisted_seasons = []
        original_write = MODULE.write_episode_cache

        def write_and_observe(path, cache):
            original_write(path, cache)
            saved = json.loads(path.read_text(encoding="utf-8"))
            persisted_seasons.append(sorted(saved["shows"]["101"]["episodesBySeason"]))

        async def response(url, **_kwargs):
            calls.append(url)
            if "/season/" in url:
                number = int(url.rsplit("/", 1)[-1])
                return FakeResponse(200, self.episode_payload(number))
            return FakeResponse(200, self.detail_payload())

        MODULE.write_episode_cache = write_and_observe
        try:
            result = asyncio.run(MODULE.build_episode_cache(
                self.seed, self.cache_path, [("key", "test-key")],
                client_factory=lambda **kwargs: FakeClient(response, **kwargs),
                max_attempts=1, sleep=lambda _delay: asyncio.sleep(0),
            ))
        finally:
            MODULE.write_episode_cache = original_write

        cache = json.loads(self.cache_path.read_text(encoding="utf-8"))["shows"]
        self.assertEqual(result["showsExamined"], 2)
        self.assertEqual(cache["101"]["episodesBySeason"].keys(), {"1", "2"})
        self.assertEqual(cache["101"]["episodesBySeason"]["2"][0]["still"], "https://image.tmdb.org/t/p/w300/still.jpg")
        self.assertIn(["1"], persisted_seasons)
        self.assertIn(["1", "2"], persisted_seasons)
        self.assertEqual(sum("/season/" in url for url in calls), 4)

    def test_resume_skips_cached_seasons_and_fetches_only_missing_seasons(self):
        self.remove_anime_test_record()
        self.cache_path.parent.mkdir(parents=True)
        self.cache_path.write_text(json.dumps({"shows": {
            "101": {
                "tmdbId": 101,
                "seasons": [
                    {"seasonNumber": 1, "name": "Season 1", "episodeCount": 1},
                    {"seasonNumber": 2, "name": "Season 2", "episodeCount": 1},
                ],
                "episodesBySeason": {"1": []},
            },
        }}), encoding="utf-8")
        calls = []

        async def response(url, **_kwargs):
            calls.append(url)
            return FakeResponse(200, self.episode_payload(1))

        summary = asyncio.run(MODULE.build_episode_cache(
            self.seed, self.cache_path, [("key", "test-key")],
            client_factory=lambda **kwargs: FakeClient(response, **kwargs),
            max_attempts=1,
        ))

        self.assertEqual(summary["seasonsSkipped"], 1)
        self.assertEqual(sum("/season/" in url for url in calls), 1)
        self.assertFalse(any(url.endswith("/tv/101") for url in calls))
        cache = json.loads(self.cache_path.read_text(encoding="utf-8"))["shows"]["101"]
        self.assertEqual(cache["episodesBySeason"]["1"], [])
        self.assertEqual(len(cache["episodesBySeason"]["2"]), 1)

    def test_failed_season_is_not_marked_and_can_be_retried(self):
        self.remove_anime_test_record()
        calls = []
        fail_season_two = True

        async def response(url, **_kwargs):
            nonlocal fail_season_two
            calls.append(url)
            if "/season/2" in url and fail_season_two:
                return FakeResponse(500, {})
            if "/season/" in url:
                return FakeResponse(200, self.episode_payload(1))
            return FakeResponse(200, self.detail_payload())

        first = asyncio.run(MODULE.build_episode_cache(
            self.seed, self.cache_path, [("key", "test-key")],
            client_factory=lambda **kwargs: FakeClient(response, **kwargs),
            max_attempts=1,
        ))
        after_failure = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertNotIn("2", after_failure["shows"]["101"]["episodesBySeason"])
        fail_season_two = False
        second = asyncio.run(MODULE.build_episode_cache(
            self.seed, self.cache_path, [("key", "test-key")],
            client_factory=lambda **kwargs: FakeClient(response, **kwargs),
            max_attempts=1,
        ))

        self.assertTrue(first["failures"])
        self.assertEqual(second["seasonsCompleted"], 1)
        self.assertIn("2", json.loads(self.cache_path.read_text(encoding="utf-8"))["shows"]["101"]["episodesBySeason"])

    def test_tmdb_429_honors_retry_after(self):
        calls = []
        waits = []

        async def response(url, **_kwargs):
            calls.append(url)
            if len(calls) == 1:
                return FakeResponse(429, {}, {"Retry-After": "7"})
            if "/season/" in url:
                return FakeResponse(200, {"episodes": []})
            return FakeResponse(200, {"seasons": []})

        async def sleep(delay):
            waits.append(delay)

        summary = asyncio.run(MODULE.build_episode_cache(
            self.seed, self.cache_path, [("key", "test-key")],
            client_factory=lambda **kwargs: FakeClient(response, **kwargs),
            max_attempts=2, sleep=sleep,
        ))

        self.assertEqual(waits[0], 7)
        self.assertEqual(summary["seasonsCompleted"], 0)
        self.assertFalse(summary["failures"])

    def test_concurrency_is_bounded(self):
        active = 0
        maximum_active = 0

        async def response(url, **_kwargs):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.001)
            active -= 1
            if "/season/" in url:
                return FakeResponse(200, {"episodes": []})
            return FakeResponse(200, self.detail_payload(seasons=(1,)))

        asyncio.run(MODULE.build_episode_cache(
            self.seed, self.cache_path, [("key", "test-key")],
            client_factory=lambda **kwargs: FakeClient(response, **kwargs),
            concurrency=2, max_attempts=1,
        ))

        self.assertEqual(maximum_active, 2)


if __name__ == "__main__":
    unittest.main()
