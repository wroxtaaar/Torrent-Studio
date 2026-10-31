import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_yenime_module():
    spec = importlib.util.spec_from_file_location("yenime_integration", ROOT / "integrations" / "yenime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_yenime_url_for_mal_episode_sub_and_dub():
    yenime = _load_yenime_module()
    assert yenime.build_yenime_url(5114, 1, "sub") == "https://player.yenime.net/anime/mal/5114/1"
    assert yenime.build_yenime_url("5114", "2", "dub") == "https://player.yenime.net/anime/mal/5114/2?dub=1"


@pytest.mark.parametrize("mal_id", [0, -1, "", "abc", 1.5, None])
def test_build_yenime_url_rejects_invalid_mal_ids(mal_id):
    yenime = _load_yenime_module()
    with pytest.raises(ValueError, match="MAL ID"):
        yenime.build_yenime_url(mal_id, 1, "sub")


@pytest.mark.parametrize("episode", [0, -1, "", "abc", 1.5, None])
def test_build_yenime_url_rejects_invalid_episode_numbers(episode):
    yenime = _load_yenime_module()
    with pytest.raises(ValueError, match="episode"):
        yenime.build_yenime_url(5114, episode, "sub")


@pytest.mark.parametrize("stream_type", ["", "raw", "SUB", None])
def test_build_yenime_url_rejects_invalid_stream_types(stream_type):
    yenime = _load_yenime_module()
    with pytest.raises(ValueError, match="Stream type"):
        yenime.build_yenime_url(5114, 1, stream_type)


def test_resolver_reports_availability_unverified():
    yenime = _load_yenime_module()
    result = yenime.build_yenime_url(5114, 1, "sub")
    assert result.startswith("https://player.yenime.net/anime/mal/")


def test_existing_catalogue_mal_id_is_used_directly():
    yenime = _load_yenime_module()
    assert yenime.normalize_anime_title("Fullmetal Alchemist: Brotherhood") == "fullmetal alchemist brotherhood"
    assert yenime.KNOWN_MAL_IDS[yenime.normalize_anime_title("Fullmetal Alchemist: Brotherhood")] == 5114


def test_successful_resolution_matches_title_alternate_title_and_year():
    yenime = _load_yenime_module()
    candidates = [{"idMal": 16498, "title": {"romaji": "Shingeki no Kyojin", "english": "Attack on Titan", "native": "進撃の巨人"}, "synonyms": ["AoT"], "startDate": {"year": 2013}}]
    result = yenime.resolve_mal_from_anilist_candidates("Attack on Titan", 2013, candidates)
    assert result["status"] == "resolved"
    assert result["malId"] == 16498


def test_ambiguous_resolution_is_not_selected():
    yenime = _load_yenime_module()
    candidates = [
        {"idMal": 100, "title": {"romaji": "Example", "english": "Example", "native": ""}, "synonyms": [], "startDate": {"year": 2020}},
        {"idMal": 101, "title": {"romaji": "Example", "english": "Example", "native": ""}, "synonyms": [], "startDate": {"year": 2021}},
    ]
    result = yenime.resolve_mal_from_anilist_candidates("Example", None, candidates)
    assert result["status"] == "ambiguous"
    assert result["malId"] is None


def test_missing_resolution_requires_manual_mal_id():
    yenime = _load_yenime_module()
    result = yenime.resolve_mal_from_anilist_candidates("Unknown Anime", 2024, [])
    assert result["status"] == "missing"
    assert result["malId"] is None


def test_episode_selection_is_preserved_in_url():
    yenime = _load_yenime_module()
    assert yenime.build_yenime_url(16498, 12, "sub") == "https://player.yenime.net/anime/mal/16498/12"
    assert yenime.build_yenime_url(16498, 12, "dub") == "https://player.yenime.net/anime/mal/16498/12?dub=1"


def test_resolved_mal_id_is_looked_up_only_once(monkeypatch, tmp_path):
    import asyncio

    import integrations.yenime as yenime

    calls = []
    media = [{"idMal": 5114, "synonyms": [], "title": {"romaji": "Hagane no Renkinjutsushi", "english": "Fullmetal Alchemist: Brotherhood", "native": ""}, "startDate": {"year": 2009}}]

    class FakeResponse:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"Page": {"media": media}}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            calls.append(1)
            return FakeResponse()

    monkeypatch.setattr(yenime, "_InstrumentedAsyncClient", FakeClient)
    monkeypatch.setattr(yenime, "CACHE_ONLY_MODE", False)
    monkeypatch.setattr(yenime, "_MAL_CACHE_PATH", tmp_path / "mal-cache.json")
    monkeypatch.setattr(yenime, "KNOWN_MAL_IDS", {})
    monkeypatch.setattr(yenime, "_ANILIST_COOLDOWN_UNTIL", 0)
    yenime._MAL_CACHE.clear()
    first = asyncio.run(yenime.fetch_anilist_mal_resolution("Fullmetal Alchemist Brotherhood", 2009))
    second = asyncio.run(yenime.fetch_anilist_mal_resolution("Fullmetal Alchemist Brotherhood", 2009))
    assert first["status"] == "resolved" and first["malId"] == 5114
    assert second == first and len(calls) == 1
    yenime._MAL_CACHE.clear()


def test_mal_resolution_persists_success_and_negative_results(monkeypatch, tmp_path):
    import asyncio

    import integrations.yenime as yenime

    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return {"data": {"Page": {"media": [
                {"idMal": 16498, "synonyms": [], "title": {"english": "Attack on Titan", "romaji": "", "native": ""}, "startDate": {"year": 2013}},
            ]}}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, *args, **kwargs):
            calls.append(1)
            return FakeResponse()

    monkeypatch.setattr(yenime, "_InstrumentedAsyncClient", FakeClient)
    monkeypatch.setattr(yenime, "CACHE_ONLY_MODE", False)
    monkeypatch.setattr(yenime, "_MAL_CACHE_PATH", tmp_path / "mal-cache.json")
    monkeypatch.setattr(yenime, "KNOWN_MAL_IDS", {})
    monkeypatch.setattr(yenime, "_ANILIST_COOLDOWN_UNTIL", 0)
    yenime._MAL_CACHE.clear()

    result = asyncio.run(yenime.fetch_anilist_mal_resolution("Attack on Titan", 2013))
    yenime._MAL_CACHE.clear()
    persisted = asyncio.run(yenime.fetch_anilist_mal_resolution("Attack on Titan", 2013))

    assert result["status"] == "resolved" and result["malId"] == 16498
    assert persisted == result
    assert calls == [1]


def test_anilist_429_sets_persistent_cooldown_and_suppresses_other_lookups(monkeypatch, tmp_path):
    import asyncio
    import json

    import integrations.yenime as yenime

    calls = []

    class FakeResponse:
        status_code = 429
        headers = {"Retry-After": "30"}

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, *args, **kwargs):
            calls.append(1)
            return FakeResponse()

    cache_path = tmp_path / "mal-cache.json"
    monkeypatch.setattr(yenime, "_InstrumentedAsyncClient", FakeClient)
    monkeypatch.setattr(yenime, "CACHE_ONLY_MODE", False)
    monkeypatch.setattr(yenime, "_MAL_CACHE_PATH", cache_path)
    monkeypatch.setattr(yenime, "KNOWN_MAL_IDS", {})
    monkeypatch.setattr(yenime, "_ANILIST_COOLDOWN_UNTIL", 0)
    yenime._MAL_CACHE.clear()

    first = asyncio.run(yenime.fetch_anilist_mal_resolution("Black Clover", 2017))
    yenime._MAL_CACHE.clear()
    monkeypatch.setattr(yenime, "_ANILIST_COOLDOWN_UNTIL", 0)
    second = asyncio.run(yenime.fetch_anilist_mal_resolution("Cyberpunk Edgerunners", 2022))
    document = json.loads(cache_path.read_text(encoding="utf-8"))

    assert first["status"] == second["status"] == "unavailable"
    assert "rate limiting" in second["message"]
    assert document["cooldownUntil"] > 0
    assert 29 <= document["cooldownUntil"] - yenime.time.time() <= 30
    assert calls == [1]


def test_missing_mal_resolution_is_persistently_negative_cached(monkeypatch, tmp_path):
    import asyncio

    import integrations.yenime as yenime

    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return {"data": {"Page": {"media": []}}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, *args, **kwargs):
            calls.append(1)
            return FakeResponse()

    monkeypatch.setattr(yenime, "_InstrumentedAsyncClient", FakeClient)
    monkeypatch.setattr(yenime, "CACHE_ONLY_MODE", False)
    monkeypatch.setattr(yenime, "_MAL_CACHE_PATH", tmp_path / "mal-cache.json")
    monkeypatch.setattr(yenime, "KNOWN_MAL_IDS", {})
    monkeypatch.setattr(yenime, "_ANILIST_COOLDOWN_UNTIL", 0)
    yenime._MAL_CACHE.clear()

    first = asyncio.run(yenime.fetch_anilist_mal_resolution("Uncatalogued Series", 2024))
    yenime._MAL_CACHE.clear()
    second = asyncio.run(yenime.fetch_anilist_mal_resolution("Uncatalogued Series", 2024))

    assert first["status"] == second["status"] == "missing"
    assert calls == [1]


def test_cache_only_mal_resolution_does_not_create_http_client(monkeypatch, tmp_path):
    import asyncio

    import integrations.yenime as yenime

    monkeypatch.setattr(yenime, "CACHE_ONLY_MODE", True)
    monkeypatch.setattr(yenime, "_MAL_CACHE_PATH", tmp_path / "mal-cache.json")
    monkeypatch.setattr(yenime, "KNOWN_MAL_IDS", {})
    yenime._MAL_CACHE.clear()

    def unexpected_client(*_args, **_kwargs):
        raise AssertionError("AniList client must not be constructed in cache-only mode")

    monkeypatch.setattr(yenime, "_InstrumentedAsyncClient", unexpected_client)
    result = asyncio.run(yenime.fetch_anilist_mal_resolution("Some Anime", 2024))
    assert result["status"] == "unavailable"
    assert "cache-only" in result["message"]


def test_manual_mal_id_resolution_does_not_contact_anilist(monkeypatch):
    import asyncio

    import integrations.yenime as yenime

    def unexpected_resolver(*_args, **_kwargs):
        raise AssertionError("A supplied MAL ID must bypass automatic resolution")

    monkeypatch.setattr(yenime, "fetch_anilist_mal_resolution", unexpected_resolver)
    result = asyncio.run(yenime.resolve_mal_id("Example", mal_id=1234))
    assert result["status"] == "resolved"
    assert result["malId"] == 1234


def test_cached_tmdb_mapping_is_available_in_cache_only_mode(monkeypatch, tmp_path):
    import asyncio

    import integrations.yenime as yenime

    cache_path = tmp_path / "mal-cache.json"
    monkeypatch.setattr(yenime, "_MAL_CACHE_PATH", cache_path)
    monkeypatch.setattr(yenime, "_MAL_CACHE_SEED_PATH", tmp_path / "absent-seed.json")
    monkeypatch.setattr(yenime, "CACHE_ONLY_MODE", True)
    yenime._MAL_CACHE.clear()
    yenime._write_mal_cache_document({
        "version": yenime._MAL_CACHE_VERSION,
        "entries": {},
        "tmdbMappings": {
            "105248": {
                "tmdbId": 105248,
                "malId": 42310,
                "title": "Cyberpunk: Edgerunners",
                "source": "AniList",
                "resolvedAt": "2026-10-30T00:00:00+00:00",
            },
        },
        "cooldownUntil": 0,
    })

    def unexpected_client(*_args, **_kwargs):
        raise AssertionError("Cache-only mapping lookup must not contact AniList")

    monkeypatch.setattr(yenime, "_InstrumentedAsyncClient", unexpected_client)
    result = asyncio.run(yenime.resolve_mal_id(
        "Cyberpunk: Edgerunners",
        year=2022,
        tmdb_id=105248,
    ))

    assert result["status"] == "resolved"
    assert result["malId"] == 42310


def test_cache_only_miss_explains_refresh_and_never_contacts_anilist(monkeypatch, tmp_path):
    import asyncio

    import integrations.yenime as yenime

    monkeypatch.setattr(yenime, "_MAL_CACHE_PATH", tmp_path / "mal-cache.json")
    monkeypatch.setattr(yenime, "_MAL_CACHE_SEED_PATH", tmp_path / "absent-seed.json")
    monkeypatch.setattr(yenime, "CACHE_ONLY_MODE", True)
    monkeypatch.setattr(yenime, "KNOWN_MAL_IDS", {})
    yenime._MAL_CACHE.clear()

    def unexpected_client(*_args, **_kwargs):
        raise AssertionError("A cache-only MAL miss must not contact AniList")

    monkeypatch.setattr(yenime, "_InstrumentedAsyncClient", unexpected_client)
    result = asyncio.run(yenime.resolve_mal_id("Unknown Anime", tmdb_id=90001))
    assert result["status"] == "unavailable"
    assert "cache refresh" in result["message"]


def test_normal_mode_resolves_and_persists_tmdb_mapping(monkeypatch, tmp_path):
    import asyncio
    import json

    import integrations.yenime as yenime

    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return {"data": {"Page": {"media": [
                {"idMal": 42310, "synonyms": [], "title": {"english": "Cyberpunk: Edgerunners", "romaji": "", "native": ""}, "startDate": {"year": 2022}},
            ]}}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def post(self, *args, **kwargs):
            calls.append(1)
            return FakeResponse()

    cache_path = tmp_path / "mal-cache.json"
    monkeypatch.setattr(yenime, "_MAL_CACHE_PATH", cache_path)
    monkeypatch.setattr(yenime, "_MAL_CACHE_SEED_PATH", tmp_path / "absent-seed.json")
    monkeypatch.setattr(yenime, "_InstrumentedAsyncClient", FakeClient)
    monkeypatch.setattr(yenime, "CACHE_ONLY_MODE", False)
    monkeypatch.setattr(yenime, "KNOWN_MAL_IDS", {})
    monkeypatch.setattr(yenime, "_ANILIST_COOLDOWN_UNTIL", 0)
    yenime._MAL_CACHE.clear()

    result = asyncio.run(yenime.resolve_mal_id(
        "Cyberpunk: Edgerunners",
        year=2022,
        tmdb_id=105248,
    ))
    mapping = json.loads(cache_path.read_text(encoding="utf-8"))["tmdbMappings"]["105248"]

    assert result["status"] == "resolved"
    assert result["malId"] == 42310
    assert mapping["title"] == "Cyberpunk: Edgerunners"
    assert mapping["source"] == "AniList"
    assert mapping["resolvedAt"]
    assert calls == [1]


def test_bundled_mal_cache_merge_preserves_valid_mappings_and_adds_missing(monkeypatch, tmp_path):
    import json

    import integrations.yenime as yenime

    persistent_path = tmp_path / "persistent.json"
    seed_path = tmp_path / "seed.json"
    persistent_path.write_text(json.dumps({
        "version": 1,
        "entries": {"preserved": {"result": {"status": "resolved", "malId": 44}, "expiresAt": 9999999999}},
        "tmdbMappings": {
            "1": {"tmdbId": 1, "malId": 44, "title": "Existing", "source": "manual", "resolvedAt": "old"},
            "2": {"tmdbId": 2, "malId": 0, "title": "Invalid", "source": "AniList", "resolvedAt": "old"},
        },
        "cooldownUntil": 0,
    }), encoding="utf-8")
    seed_path.write_text(json.dumps({
        "version": 2,
        "entries": {
            "preserved": {"result": {"status": "unavailable", "malId": None}, "expiresAt": 9999999999},
            "new": {"result": {"status": "missing", "malId": None}, "expiresAt": 9999999999},
        },
        "tmdbMappings": {
            "1": {"tmdbId": 1, "malId": 99, "title": "Do not replace", "source": "AniList", "resolvedAt": "new"},
            "2": {"tmdbId": 2, "malId": 55, "title": "Added", "source": "AniList", "resolvedAt": "new"},
            "3": {"tmdbId": 3, "malId": None, "title": "Failed", "source": "AniList", "resolvedAt": "new"},
            "4": {"malId": 66, "title": "Missing TMDB ID", "source": "AniList", "resolvedAt": "new"},
        },
        "cooldownUntil": 100,
    }), encoding="utf-8")
    monkeypatch.setattr(yenime, "_MAL_CACHE_PATH", persistent_path)
    monkeypatch.setattr(yenime, "_MAL_CACHE_SEED_PATH", seed_path)

    yenime._seed_yenime_mal_cache()
    merged = json.loads(persistent_path.read_text(encoding="utf-8"))
    assert merged["tmdbMappings"]["1"]["malId"] == 44
    assert merged["tmdbMappings"]["2"]["malId"] == 55
    assert "3" not in merged["tmdbMappings"]
    assert "4" not in merged["tmdbMappings"]
    assert merged["entries"]["preserved"]["result"]["malId"] == 44
    assert "new" not in merged["entries"]
    assert merged["cooldownUntil"] == 100


def test_manual_mal_id_overrides_cached_or_automatic_resolution(monkeypatch):
    import asyncio

    import integrations.yenime as yenime

    def unexpected_resolver(*_args, **_kwargs):
        raise AssertionError("Manual MAL ID must take precedence over automatic resolution")

    monkeypatch.setattr(yenime, "fetch_anilist_mal_resolution", unexpected_resolver)
    result = asyncio.run(yenime.resolve_mal_id(
        "Cyberpunk: Edgerunners",
        mal_id=999,
        tmdb_id=105248,
    ))
    assert result["status"] == "resolved"
    assert result["malId"] == 999
