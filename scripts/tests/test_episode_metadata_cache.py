import asyncio
import importlib.util
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

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

    def isolate_anime_section(self):
        path = self.seed / "anime.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["subsections"]["movies"]["results"] = []
        document["subsections"]["series"]["results"] = []
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

    def test_anime_records_use_section_conventions_and_deduplicate_tmdb_ids(self):
        for filename in MODULE.SECTION_FILES:
            (self.seed / filename).write_text(json.dumps({"subsections": {}}), encoding="utf-8")
        (self.seed / "anime.json").write_text(json.dumps({
            "subsections": {
                "movies": {
                    "mediaType": "movie",
                    "results": [{"tmdbId": 100, "title": "Anime Film", "releaseDate": "2020-01-01"}],
                },
                "series": {
                    "mediaType": "tv",
                    "results": [{"tmdbId": 101, "title": "Anime Series", "year": 2018}],
                },
            },
        }), encoding="utf-8")
        (self.seed / "favourites.json").write_text(json.dumps({
            "subsections": {
                "anime": {
                    "mediaType": "tv",
                    "results": [
                        {"id": 101, "title": "Anime Series Extended", "year": 2018},
                        {"tmdbId": 102, "title": "Favourite Anime"},
                    ],
                },
            },
        }), encoding="utf-8")
        (self.seed / "bollywood.json").write_text(json.dumps({
            "subsections": {
                "tv-popular": {
                    "mediaType": "tv",
                    "results": [{"id": 103, "title": "Flagged Anime", "anime": True}],
                },
            },
        }), encoding="utf-8")
        (self.seed / "marvel.json").write_text(json.dumps({
            "subsections": {
                "series": {
                    "mediaType": "tv",
                    "results": [{"id": 104, "title": "Not Anime"}],
                },
            },
        }), encoding="utf-8")

        records = MODULE.anime_catalogue_records(self.seed)
        self.assertEqual([row["tmdbId"] for row in records], [100, 101, 102, 103])
        self.assertEqual(records[0]["year"], 2020)
        self.assertEqual(records[1]["title"], "Anime Series Extended")

    def test_mal_builder_skips_cached_ids_and_resumes_after_temporary_failure(self):
        self.isolate_anime_section()

        class FakeResolver:
            _ANILIST_COOLDOWN_UNTIL = 0

            def __init__(self):
                self.mappings = {}
                self.calls = []
                self.fail_once = True

            def get_cached_mal_mapping(self, tmdb_id):
                return self.mappings.get(tmdb_id)

            async def fetch_anilist_mal_resolution(self, title, year, *, tmdb_id):
                self.calls.append(tmdb_id)
                if self.fail_once:
                    self.fail_once = False
                    return {"status": "unavailable", "message": "AniList network request failed"}
                self.mappings[tmdb_id] = {"tmdbId": tmdb_id, "malId": tmdb_id + 5000}
                return {"status": "resolved", "malId": tmdb_id + 5000}

        resolver = FakeResolver()
        summary = asyncio.run(MODULE.build_mal_id_cache(self.seed, resolver, batch_size=1))
        self.assertEqual(summary["animeRecordsExamined"], 1)
        self.assertEqual(summary["malResolutionFailures"], 1)
        self.assertEqual(resolver.calls, [102])

        resumed = asyncio.run(MODULE.build_mal_id_cache(self.seed, resolver, batch_size=1))
        self.assertEqual(resumed["malMappingsAdded"], 1)
        self.assertEqual(resolver.calls, [102, 102])

        skipped = asyncio.run(MODULE.build_mal_id_cache(self.seed, resolver, batch_size=1))
        self.assertEqual(skipped["malMappingsSkipped"], 1)
        self.assertEqual(resolver.calls, [102, 102])

    def test_mal_builder_waits_out_anilist_retry_after_without_repeating_record(self):
        self.isolate_anime_section()

        class FakeResolver:
            def __init__(self):
                self._ANILIST_COOLDOWN_UNTIL = MODULE.time.time() + 5
                self.calls = []

            def get_cached_mal_mapping(self, _tmdb_id):
                return None

            async def fetch_anilist_mal_resolution(self, _title, _year, *, tmdb_id):
                self.calls.append(tmdb_id)
                return {"status": "unavailable", "message": "AniList is rate limiting requests"}

        resolver = FakeResolver()
        waits = []

        async def fake_sleep(delay):
            waits.append(delay)

        result = asyncio.run(MODULE.build_mal_id_cache(
            self.seed,
            resolver,
            batch_size=1,
            sleep=fake_sleep,
        ))
        self.assertEqual(resolver.calls, [102])
        self.assertEqual(result["malResolutionFailures"], 1)
        self.assertEqual(len(waits), 1)
        self.assertGreater(waits[0], 4)

    def test_cache_bundle_includes_the_persistent_mal_mapping_file(self):
        (self.seed / "unrelated.json").unlink()
        runtime = self.seed / "runtime"
        runtime.mkdir()
        for filename, payload in (
            ("tmdb_movie_catalogue_cache.json", {"catalogues": {}}),
            ("tmdb_search_metadata_cache.json", {"results": []}),
            ("imdb_rating_cache.json", {"results": []}),
            ("tmdb_ott_availability_cache.json", {"items": {}}),
        ):
            (runtime / filename).write_text(json.dumps(payload), encoding="utf-8")
        catalogue_keys = (
            "hollywood-popular", "hollywood-trending", "hollywood-latest",
            "indian-popular", "indian-trending", "indian-latest",
        )
        (self.seed / "regional_tv_prebuilt_cache.json").write_text(json.dumps({
            "catalogues": {
                key: {"pages": [{"page": 1, "results": [{"id": 700, "title": key}]}]}
                for key in catalogue_keys
            },
        }), encoding="utf-8")
        mal_cache = runtime / "yenime_mal_resolution_cache.json"
        mal_cache.write_text(json.dumps({
            "version": 2,
            "entries": {},
            "tmdbMappings": {
                "101": {"tmdbId": 101, "malId": 5114, "title": "Example", "source": "AniList", "resolvedAt": "now"},
            },
            "cooldownUntil": 0,
        }), encoding="utf-8")
        output = self.root / "bundle-out"
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[1] / "make_cache_bundle.py"),
                str(self.seed),
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        with tarfile.open(output / "cache-bundle.tar.gz", "r:gz") as bundle:
            archived = json.load(bundle.extractfile("runtime/yenime_mal_resolution_cache.json"))
        self.assertEqual(archived["tmdbMappings"]["101"]["malId"], 5114)

        manifest = json.loads((output / "cache-bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["bundle"], f"cache-bundle-{manifest['version']}.tar.gz")
        self.assertTrue((output / manifest["bundle"]).is_file())


if __name__ == "__main__":
    unittest.main()
