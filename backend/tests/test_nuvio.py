from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

import main
from integrations import nuvio


class MockNuvioClient:
    def __init__(self, *, timeout, follow_redirects):
        assert timeout == 45
        assert follow_redirects is False
        self.requested_url = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url):
        self.requested_url = url
        return SimpleNamespace(
            status_code=200,
            is_error=False,
            is_redirect=False,
            json=lambda: {
                "streams": [
                    {
                        "name": "Example provider",
                        "title": "The Matrix · 1080p",
                        "url": "https://streams.example/video.m3u8",
                    },
                    {"name": "Unsafe", "title": "Ignored", "url": "http://internal.example/video.mp4"},
                    {"name": "Malformed", "title": "Ignored", "url": "javascript:alert(1)"},
                    {"name": "Invalid host", "title": "Ignored", "url": "https://[broken/video.mp4"},
                ]
            },
        )


def test_nuvio_movie_lookup_uses_documented_stremio_endpoint(monkeypatch):
    monkeypatch.setenv("NUVIO_BASE_URL", "http://nuvio:7000")
    client_instance = MockNuvioClient(timeout=45, follow_redirects=False)
    monkeypatch.setattr(nuvio.httpx, "AsyncClient", lambda **_kwargs: client_instance)

    response = TestClient(main.app).get("/api/nuvio/movies/tt0133093")

    assert response.status_code == 200
    assert client_instance.requested_url == "http://nuvio:7000/stream/movie/tt0133093.json"
    payload = response.json()
    assert payload["id"] == "tt0133093"
    assert len(payload["streams"]) == 1
    assert payload["streams"][0]["name"] == "Example provider"


def test_nuvio_supports_manifest_declared_tmdb_id_prefix(monkeypatch):
    monkeypatch.setenv("NUVIO_BASE_URL", "http://nuvio:7000")
    client_instance = MockNuvioClient(timeout=45, follow_redirects=False)
    monkeypatch.setattr(nuvio.httpx, "AsyncClient", lambda **_kwargs: client_instance)

    response = TestClient(main.app).get("/api/nuvio/movies/tmdb%3A603")

    assert response.status_code == 200
    assert client_instance.requested_url == "http://nuvio:7000/stream/movie/tmdb:603.json"


def test_nuvio_rejects_invalid_identifiers(monkeypatch):
    monkeypatch.setenv("NUVIO_BASE_URL", "http://nuvio:7000")
    response = TestClient(main.app).get("/api/nuvio/movies/603")
    assert response.status_code == 422


def test_nuvio_reports_missing_configuration(monkeypatch):
    monkeypatch.delenv("NUVIO_BASE_URL", raising=False)
    response = TestClient(main.app).get("/api/nuvio/movies/tt0133093")
    assert response.status_code == 503


def test_nuvio_timeout_is_reported(monkeypatch):
    monkeypatch.setenv("NUVIO_BASE_URL", "http://nuvio:7000")

    class TimeoutClient(MockNuvioClient):
        async def get(self, _url):
            raise httpx.TimeoutException("upstream timeout")

    monkeypatch.setattr(nuvio.httpx, "AsyncClient", TimeoutClient)
    response = TestClient(main.app).get("/api/nuvio/movies/tt0133093")
    assert response.status_code == 504
