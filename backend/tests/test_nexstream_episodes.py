import asyncio
import json

import pytest
from fastapi import HTTPException

from integrations import nexstream


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses, **_kwargs):
        self.responses = responses
        self.requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.responses(url, kwargs)


def _show_payload(season_numbers=(1, 2)):
    return {
        "seasons": [
            {"season_number": number, "name": f"Season {number}", "episode_count": 1}
            for number in season_numbers
        ],
    }


def test_persistent_episode_cache_serves_empty_and_populated_seasons(monkeypatch, tmp_path):
    cache_path = tmp_path / "episodes.json"
    monkeypatch.setattr(nexstream, "_NEXSTREAM_EPISODE_CACHE_PATH", cache_path)
    monkeypatch.setattr(nexstream, "_NEXSTREAM_EPISODE_CACHE_LOCK", nexstream.threading.RLock())
    seasons = [{"seasonNumber": 1, "name": "Season 1", "episodeCount": 1}]
    episode = {"episodeNumber": 1, "name": "Pilot", "overview": "", "airDate": "", "still": None}

    nexstream._write_episode_cache(101, seasons, 1, [episode])
    nexstream._write_episode_cache(102, seasons, 1, [])

    populated = nexstream._episode_cache_response(nexstream._read_episode_cache_document(), 101, 1)
    empty = nexstream._episode_cache_response(nexstream._read_episode_cache_document(), 102, 1)
    assert populated["episodes"] == [episode]
    assert populated["status"] == "ready"
    assert empty["episodes"] == []
    assert empty["status"] == "no_episodes"


def test_bundle_merge_preserves_persistent_seasons_and_adds_missing_data():
    persistent = {
        "shows": {
            "101": {
                "tmdbId": 101,
                "seasons": [{"seasonNumber": 1, "name": "Existing", "episodeCount": 2}],
                "episodesBySeason": {"1": []},
            },
        },
    }
    bundled = {
        "shows": {
            "101": {
                "tmdbId": 101,
                "seasonsFetched": True,
                "seasons": [
                    {"seasonNumber": 1, "name": "Bundled", "episodeCount": 99},
                    {"seasonNumber": 2, "name": "Season 2", "episodeCount": 3},
                ],
                "episodesBySeason": {"1": [{"episodeNumber": 1}], "2": []},
            },
            "102": {
                "tmdbId": 102,
                "seasonsFetched": True,
                "seasons": [],
                "episodesBySeason": {},
            },
        },
    }

    assert nexstream._merge_episode_cache_data(persistent, bundled)
    assert persistent["shows"]["101"]["seasons"][0]["name"] == "Existing"
    assert persistent["shows"]["101"]["episodesBySeason"]["1"] == []
    assert persistent["shows"]["101"]["episodesBySeason"]["2"] == []
    assert persistent["shows"]["102"]["seasonsFetched"] is True
    assert not nexstream._merge_episode_cache_data(persistent, bundled)


def test_bundled_episode_cache_restores_into_persistent_storage(monkeypatch, tmp_path):
    seed_path = tmp_path / "seed.json"
    persistent_path = tmp_path / "data" / "episodes.json"
    seed_path.write_text(json.dumps({
        "shows": {
            "101": {
                "tmdbId": 101,
                "seasonsFetched": True,
                "seasons": [],
                "episodesBySeason": {},
            },
        },
    }), encoding="utf-8")
    monkeypatch.setattr(nexstream, "_NEXSTREAM_EPISODE_CACHE_SEED_PATH", seed_path)
    monkeypatch.setattr(nexstream, "_NEXSTREAM_EPISODE_CACHE_PATH", persistent_path)

    nexstream._seed_nexstream_episode_cache()

    restored = json.loads(persistent_path.read_text(encoding="utf-8"))
    assert restored["shows"]["101"]["seasonsFetched"] is True
    assert restored["shows"]["101"]["episodesBySeason"] == {}


def test_cache_only_miss_returns_specific_error_without_http_client(monkeypatch, tmp_path, caplog):
    caplog.set_level("INFO", logger="torrent-studio")
    monkeypatch.setattr(nexstream, "_NEXSTREAM_EPISODE_CACHE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(nexstream, "CACHE_ONLY_MODE", True)
    monkeypatch.setenv("LIVE_TITLE_SEARCH", "false")

    def unexpected_client(*_args, **_kwargs):
        raise AssertionError("TMDB client must not be constructed on a strict cache miss")

    monkeypatch.setattr(nexstream, "_InstrumentedAsyncClient", unexpected_client)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(nexstream.get_tv_episodes(987654, 1))

    assert exc.value.status_code == 404
    assert "not present in the local cache" in exc.value.detail
    assert "[CACHE-ONLY] Metadata lookup blocked: provider=TMDB" in caplog.text


def test_cached_no_seasons_is_distinct_from_missing_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "episodes.json"
    cache_path.write_text(json.dumps({
        "shows": {
            "101": {
                "tmdbId": 101,
                "seasons": [],
                "seasonsFetched": True,
                "episodesBySeason": {},
            },
        },
    }), encoding="utf-8")
    monkeypatch.setattr(nexstream, "_NEXSTREAM_EPISODE_CACHE_PATH", cache_path)
    monkeypatch.setattr(nexstream, "CACHE_ONLY_MODE", True)
    monkeypatch.setenv("LIVE_TITLE_SEARCH", "false")

    result = asyncio.run(nexstream.get_tv_episodes(101, 1))
    assert result["status"] == "no_seasons"
    assert result["episodes"] == []


def test_live_episode_lookup_caches_seasons_episodes_and_uses_bearer_token(monkeypatch, tmp_path):
    cache_path = tmp_path / "episodes.json"
    monkeypatch.setattr(nexstream, "_NEXSTREAM_EPISODE_CACHE_PATH", cache_path)
    monkeypatch.setattr(nexstream, "_NEXSTREAM_EPISODE_CACHE_LOCK", nexstream.threading.RLock())
    monkeypatch.setattr(nexstream, "CACHE_ONLY_MODE", False)
    monkeypatch.setattr(nexstream, "_env_values", lambda *names: ["test-token"] if "TMDB_READ_ACCESS_TOKENS" in names else [])
    requests = []

    def responses(url, kwargs):
        if "/tv/101/season/1" in url:
            return FakeResponse(200, {
                "episodes": [{
                    "episode_number": 1,
                    "name": "Pilot",
                    "overview": "Intro",
                    "air_date": "2024-01-01",
                    "still_path": "/still.jpg",
                }],
            })
        return FakeResponse(200, _show_payload())

    class Client(FakeClient):
        def __init__(self, **_kwargs):
            pass

        async def get(self, url, **kwargs):
            requests.append((url, kwargs))
            return responses(url, kwargs)

    monkeypatch.setattr(nexstream, "_InstrumentedAsyncClient", Client)

    result = asyncio.run(nexstream.get_tv_episodes(101, 1))
    assert result["status"] == "ready"
    assert result["episodes"][0]["name"] == "Pilot"
    assert json.loads(cache_path.read_text(encoding="utf-8"))["shows"]["101"]["episodesBySeason"]["1"]
    assert all(
        request[1]["headers"].get("Authorization") == "Bearer test-token"
        for request in requests
    )

    repeat = asyncio.run(nexstream.get_tv_episodes(101, 1))
    assert repeat["cached"] is True
    assert len(requests) == 2


def test_http_429_is_reported_as_rate_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(nexstream, "_NEXSTREAM_EPISODE_CACHE_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(nexstream, "CACHE_ONLY_MODE", False)
    monkeypatch.setattr(nexstream, "_env_values", lambda *_names: ["test-key"])

    class Client(FakeClient):
        def __init__(self, **_kwargs):
            pass

        async def get(self, url, **kwargs):
            return FakeResponse(429, {})

    monkeypatch.setattr(nexstream, "_InstrumentedAsyncClient", Client)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(nexstream.get_tv_episodes(101, 1))

    assert exc.value.status_code == 429
    assert "rate limit" in exc.value.detail


def test_cache_only_episode_miss_goes_live_for_a_searched_show(monkeypatch, tmp_path):
    monkeypatch.setattr(nexstream, "_NEXSTREAM_EPISODE_CACHE_PATH", tmp_path / "episodes.json")
    monkeypatch.setattr(nexstream, "_NEXSTREAM_EPISODE_CACHE_LOCK", nexstream.threading.RLock())
    monkeypatch.setattr(nexstream, "CACHE_ONLY_MODE", True)
    monkeypatch.delenv("LIVE_TITLE_SEARCH", raising=False)
    monkeypatch.setattr(nexstream, "_env_values", lambda *n: ["tok"] if "TMDB_READ_ACCESS_TOKENS" in n else [])
    seen = {}

    def responses(url, kwargs):
        if "/season/1" in url:
            return FakeResponse(200, {"episodes": [{"episode_number": 1, "name": "Pilot"}]})
        return FakeResponse(200, _show_payload((1,)))

    class Client(FakeClient):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            super().__init__(responses)

    monkeypatch.setattr(nexstream, "_InstrumentedAsyncClient", Client)
    result = asyncio.run(nexstream.get_tv_episodes(tmdb_id=65579, season=1))
    assert result["status"] == "ready" and result["episodes"][0]["name"] == "Pilot"
    assert seen["allow_in_cache_only"] is True
