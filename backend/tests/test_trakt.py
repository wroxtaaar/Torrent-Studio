"""Trakt: trending parsing, the shared-id merge, and being off without a key or in cache-only mode."""

import asyncio

import integrations.trakt as trakt


def test_trending_is_parsed_and_titles_without_a_tmdb_id_are_dropped(monkeypatch):
    async def fake_get(path, params=None):
        assert path == "/movies/trending" and params["languages"] == "hi" and params["countries"] == "in"
        return [{"watchers": 9, "movie": {"title": "A", "year": 2026, "ids": {"tmdb": 11, "imdb": "tt1"}}},
                {"watchers": 5, "movie": {"title": "B", "year": 2026, "ids": {"imdb": "tt2"}}}]

    monkeypatch.setattr(trakt, "trakt_get", fake_get)
    items = asyncio.run(trakt.trakt_trending("movies", languages="hi", countries="in"))
    assert items == [{"title": "A", "year": 2026, "tmdbId": 11, "imdbId": "tt1", "watchers": 9}]


def test_nothing_is_requested_in_cache_only_mode_or_without_a_key(monkeypatch):
    monkeypatch.setattr(trakt, "trakt_client_ids", lambda: ["k"])
    monkeypatch.setattr(trakt, "CACHE_ONLY_MODE", True)
    assert asyncio.run(trakt.trakt_get("/movies/trending")) is None
    monkeypatch.setattr(trakt, "CACHE_ONLY_MODE", False)
    monkeypatch.setattr(trakt, "trakt_client_ids", lambda: [])
    assert asyncio.run(trakt.trakt_get("/movies/trending")) is None


def test_trakt_and_tmdb_lists_alternate_and_share_one_row_per_title():
    from catalogues.catalogues_movies import _interleave_unique
    tmdb = [{"id": 1}, {"id": 2}, {"id": 3}]
    other = [{"id": 2}, {"id": 9}]
    assert [row["id"] for row in _interleave_unique(tmdb, other)] == [1, 2, 9, 3]
