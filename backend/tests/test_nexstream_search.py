import asyncio
import json

import pytest
from fastapi import HTTPException

from integrations import nexstream


def _seed(tmp_path):
    (tmp_path / "anime.json").write_text(json.dumps({"subsections": {
        "series": {"mediaType": "tv", "results": [
            {"id": 1, "title": "The Flash", "releaseDate": "2014-10-07", "posterUrl": "p.jpg"},
            {"id": 2, "title": "Flash Gordon", "year": 1980},
            {"id": 3, "title": "Naruto"},
        ]},
        "movies": {"mediaType": "movie", "results": [{"id": 9, "title": "The Flash"}]},
    }}), encoding="utf-8")
    (tmp_path / "notes.json").write_text("{not json", encoding="utf-8")


def test_local_title_results_match_by_word_prefix_and_media_type(monkeypatch, tmp_path):
    _seed(tmp_path)
    monkeypatch.setattr(nexstream, "_CACHE_SEED_DIR", tmp_path)
    rows = nexstream._local_title_results("the flash", "tv")
    assert [row["id"] for row in rows] == [1]
    assert rows[0]["type"] == "tv" and rows[0]["poster"] == "p.jpg"
    # Partial words match, exact/leading matches rank first, wrong media type is excluded.
    assert [row["id"] for row in nexstream._local_title_results("flas", "tv")] == [2, 1]
    assert [row["id"] for row in nexstream._local_title_results("flash", "movie")] == [9]
    assert nexstream._local_title_results("zzz", "tv") == []


def test_search_falls_back_to_bundled_titles_when_tmdb_is_unreachable(monkeypatch, tmp_path):
    _seed(tmp_path)
    monkeypatch.setattr(nexstream, "_CACHE_SEED_DIR", tmp_path)
    monkeypatch.setattr(nexstream, "_get_nexstream_cache", lambda *a, **k: None)

    async def unreachable(*_a, **_k):
        raise HTTPException(status_code=502, detail="Could not connect to TMDB title search.")

    monkeypatch.setattr(nexstream, "_search_tmdb_live", unreachable)
    result = asyncio.run(nexstream.search_titles(query="The Flash", media_type="tv", force_refresh=True))
    assert result["success"] and result["source"] == "bundled-cache"
    assert result["results"][0]["id"] == 1


def test_search_in_cache_only_mode_reports_unavailable_not_a_connection_error(monkeypatch, tmp_path):
    monkeypatch.setattr(nexstream, "_CACHE_SEED_DIR", tmp_path)
    monkeypatch.setattr(nexstream, "CACHE_ONLY_MODE", True)
    monkeypatch.setattr(nexstream, "_get_nexstream_cache", lambda *a, **k: None)

    async def unreachable(*_a, **_k):
        raise HTTPException(status_code=502, detail="Could not connect to TMDB title search.")

    monkeypatch.setattr(nexstream, "_search_tmdb_live", unreachable)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(nexstream.search_titles(query="Nothing Cached", media_type="tv", force_refresh=True))
    assert caught.value.status_code == 503
    assert "no cached title" in caught.value.detail
    assert "Could not connect to TMDB" in caught.value.detail


def test_live_search_opts_out_of_the_cache_only_block(monkeypatch):
    seen = {}

    class Response:
        status_code = 200

        def json(self):
            return {"results": [{"id": 5, "name": "The Flash", "first_air_date": "2014-10-07"}]}

    class Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, *_a, **_k):
            return Response()

    monkeypatch.setattr(nexstream, "_InstrumentedAsyncClient", Client)
    monkeypatch.setattr(nexstream, "_env_values", lambda *n: ["tok"] if "TMDB_READ_ACCESS_TOKENS" in n else [])
    monkeypatch.setattr(nexstream, "_set_nexstream_cache", lambda *a, **k: None)
    result = asyncio.run(nexstream._search_tmdb_live("The Flash", "tv", "tv", "search:tv:the flash"))
    assert result["results"][0]["id"] == 5
    assert seen["allow_in_cache_only"] is True

    monkeypatch.setenv("LIVE_TITLE_SEARCH", "false")
    assert nexstream._live_title_search_allowed() is False
