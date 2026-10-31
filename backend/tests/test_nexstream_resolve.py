import asyncio

import pytest
from fastapi import HTTPException

from integrations import nexstream


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _client(response, seen):
    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, url, **kwargs):
            seen.append((url, kwargs))
            return response

    return Client


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    monkeypatch.setattr(nexstream, "_get_nexstream_cache", lambda *a, **k: None)
    monkeypatch.setattr(nexstream, "_set_nexstream_cache", lambda *a, **k: None)


def test_default_provider_is_vidrift():
    result = asyncio.run(nexstream.resolve_nexstream(media_type="movie", tmdb_id=603, season=None, episode=None, provider="vidrift"))
    assert result["sources"][0]["name"] == "VidRift"
    assert result["sources"][0]["url"].startswith("https://embed.vidrift.net/")


def test_nexstream_needs_an_api_key(monkeypatch):
    monkeypatch.delenv("NEXSTREAM_API_KEY", raising=False)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(nexstream.resolve_nexstream(media_type="movie", tmdb_id=603, season=None, episode=None, provider="nexstream"))
    assert caught.value.status_code == 503 and "NEXSTREAM_API_KEY" in caught.value.detail


def test_nexstream_tv_requires_season_and_episode(monkeypatch):
    monkeypatch.setenv("NEXSTREAM_API_KEY", "k")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(nexstream.resolve_nexstream(media_type="tv", tmdb_id=1396, season=1, episode=None, provider="nexstream"))
    assert caught.value.status_code == 422


def test_nexstream_resolves_and_filters_unsupported_hosts(monkeypatch):
    monkeypatch.setenv("NEXSTREAM_API_KEY", "secret")
    seen = []
    payload = {"success": True, "sources": [
        {"name": "Bad", "url": "https://evil.example/embed/1"},
        {"name": "EmbedMaster", "url": "https://embedmaster.link/movie/603"},
        {"name": "Plain", "url": "http://embedmaster.link/movie/603"},
    ]}
    monkeypatch.setattr(nexstream, "_InstrumentedAsyncClient", _client(FakeResponse(200, payload), seen))
    result = asyncio.run(nexstream.resolve_nexstream(media_type="movie", tmdb_id=603, season=None, episode=None, provider="nexstream"))
    assert [source["url"] for source in result["sources"]] == ["https://embedmaster.link/movie/603"]
    assert result["meta"]["provider"] == "NexStream"
    assert seen[0][0].endswith("/api/movie/603") and seen[0][1]["params"] == {"apikey": "secret"}


def test_nexstream_failures_are_reported(monkeypatch):
    monkeypatch.setenv("NEXSTREAM_API_KEY", "k")
    monkeypatch.setattr(nexstream, "_InstrumentedAsyncClient", _client(FakeResponse(500, {}), []))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(nexstream.resolve_nexstream(media_type="tv", tmdb_id=1396, season=1, episode=1, provider="nexstream"))
    assert caught.value.status_code == 502 and "HTTP 500" in caught.value.detail
