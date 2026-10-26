"""MDBList: reading the IMDb rating from its record, and the OMDb-then-MDBList fallback order."""

import asyncio

import metadata.imdb as imdb
from integrations.mdblist import parse_imdb_rating


def test_imdb_rating_is_read_from_the_ratings_list():
    record = {"ids": {"imdb": "tt1375666", "tmdb": 27205},
              "ratings": [{"source": "tmdb", "value": 83, "votes": 1},
                          {"source": "imdb", "value": 8.8, "votes": 2500000, "score": 88}]}
    assert parse_imdb_rating(record) == {"imdbRating": 8.8, "imdbVotes": "2,500,000", "imdbId": "tt1375666"}
    assert parse_imdb_rating({"ratings": [{"source": "imdb", "value": None}]}) is None
    assert parse_imdb_rating({"ratings": [{"source": "trakt", "value": 7.0}]}) is None
    assert parse_imdb_rating(None) is None


def test_mdblist_is_asked_only_when_omdb_has_no_rating(monkeypatch):
    calls = []

    async def omdb(title, year, cache_key, media_type="movie", tmdb_id=0):
        return {"status": "not_found", "title": title, "year": year, "mediaType": media_type, "cacheKey": cache_key}

    async def mdblist(media_type, tmdb_id=0, imdb_id=""):
        calls.append((media_type, tmdb_id))
        return {"imdbRating": 7.1, "imdbVotes": "900", "imdbId": "tt9"}

    monkeypatch.setattr(imdb, "_fetch_imdb_rating_omdb", omdb)
    monkeypatch.setattr(imdb, "mdblist_imdb_rating", mdblist)
    record = asyncio.run(imdb._fetch_imdb_rating("X", 2026, "movie|x|2026", "movie", 42))
    assert record["status"] == "found" and record["imdbRating"] == 7.1 and record["ratingLookupSource"] == "mdblist"
    assert calls == [("movie", 42)]

    async def omdb_found(title, year, cache_key, media_type="movie", tmdb_id=0):
        return {"status": "found", "imdbRating": 6.0, "title": title, "cacheKey": cache_key}

    monkeypatch.setattr(imdb, "_fetch_imdb_rating_omdb", omdb_found)
    record = asyncio.run(imdb._fetch_imdb_rating("X", 2026, "movie|x|2026", "movie", 42))
    assert record["imdbRating"] == 6.0 and calls == [("movie", 42)]  # no second MDBList call
