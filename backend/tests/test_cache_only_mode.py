"""Strict cache-only mode must block metadata providers without affecting torrent providers."""

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from core import cache_diagnostics
from integrations import mdblist
from metadata import imdb, tmdb


@pytest.mark.parametrize(
    ("url", "log_message"),
    [
        ("https://api.themoviedb.org/3/movie/1", "provider=TMDB"),
        ("https://api.watchmode.com/v1/title/1", "OTT lookup blocked"),
        ("https://api.movieofthenight.com/v4/shows/movie/1", "OTT lookup blocked"),
        ("https://www.omdbapi.com/?t=Example", "IMDb lookup blocked"),
        ("https://v3.sg.media-imdb.com/suggestion/titles/x/example.json", "IMDb lookup blocked"),
        ("https://api.tvmaze.com/search/shows?q=Example", "provider=TVmaze"),
        ("https://itunes.apple.com/search?term=Example", "provider=Apple iTunes"),
        ("https://v3-cinemeta.strem.io/catalog/movie/top/search=Example.json", "provider=Cinemeta"),
        ("https://graphql.anilist.co", "provider=AniList"),
    ],
)
def test_instrumented_client_blocks_metadata_hosts_in_cache_only_mode(monkeypatch, caplog, url, log_message):
    sent = []
    caplog.set_level(logging.INFO, logger="torrent-studio")

    async def transport(request):
        sent.append(request.url.host)
        return httpx.Response(200, request=request)

    monkeypatch.setattr(cache_diagnostics, "CACHE_ONLY_MODE", True)

    async def run():
        client = cache_diagnostics._InstrumentedAsyncClient(transport=httpx.MockTransport(transport))
        try:
            with pytest.raises(httpx.RequestError):
                await client.get(url)
        finally:
            await client.aclose()

    asyncio.run(run())
    assert sent == []
    assert log_message in caplog.text


def test_cache_only_does_not_block_torrent_provider_http(monkeypatch):
    async def transport(request):
        return httpx.Response(200, request=request)

    monkeypatch.setattr(cache_diagnostics, "CACHE_ONLY_MODE", True)

    async def run():
        async with cache_diagnostics._InstrumentedAsyncClient(
            transport=httpx.MockTransport(transport),
        ) as client:
            response = await client.get("https://api.knaben.org/v1/search")
            assert response.status_code == 200

    asyncio.run(run())


def test_tmdb_lookup_is_rejected_before_client_creation(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="torrent-studio")
    monkeypatch.setattr(tmdb, "CACHE_ONLY_MODE", True)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(tmdb._tmdb_get_json("movie/1"))
    assert exc.value.status_code == 503
    assert "Metadata lookup blocked: provider=TMDB" in caplog.text


def test_imdb_refresh_override_cannot_bypass_cache_only_mode(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="torrent-studio")
    monkeypatch.setattr(imdb, "CACHE_ONLY_MODE", True)
    monkeypatch.setattr(imdb, "_load_imdb_rating_cache", lambda: {})

    async def unexpected_fetch(*args, **kwargs):
        raise AssertionError("IMDb lookup must not run in cache-only mode")

    monkeypatch.setattr(imdb, "_fetch_imdb_rating", unexpected_fetch)
    record = asyncio.run(
        imdb._get_imdb_rating_record(
            "Example",
            2020,
            "tv",
            refresh_incomplete=True,
            persist=False,
        )
    )
    assert record["status"] == "unavailable"
    assert "IMDb lookup blocked" in caplog.text


def test_omdb_and_mdblist_paths_are_blocked_before_http_client_creation(monkeypatch):
    monkeypatch.setattr(imdb, "CACHE_ONLY_MODE", True)
    monkeypatch.setattr(mdblist, "CACHE_ONLY_MODE", True)
    monkeypatch.setattr(mdblist, "mdblist_keys", lambda: ["test-key"])
    calls = []

    def unexpected_client(*args, **kwargs):
        calls.append(True)
        raise AssertionError("No direct metadata HTTP client should be created")

    monkeypatch.setattr(imdb, "_omdb_client", unexpected_client)
    monkeypatch.setattr(mdblist.httpx, "AsyncClient", unexpected_client)

    record = asyncio.run(imdb._fetch_imdb_rating_omdb("Example", 2020, "movie|example|2020"))
    rating = asyncio.run(mdblist.mdblist_imdb_rating("movie", tmdb_id=1))
    items = asyncio.run(mdblist.mdblist_list_items("example/list"))
    assert record["status"] == "unavailable"
    assert rating is None
    assert items == []
    assert calls == []


def test_cache_only_forces_backfill_off_even_if_environment_conflicts():
    backend = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "CACHE_ONLY_MODE": "true",
        "BACKFILL_MISSING_METADATA": "true",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from core.settings import CACHE_ONLY_MODE, BACKFILL_MISSING_METADATA; "
            "print(f'{CACHE_ONLY_MODE=},{BACKFILL_MISSING_METADATA=}')",
        ],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "CACHE_ONLY_MODE=True,BACKFILL_MISSING_METADATA=False" in result.stdout
