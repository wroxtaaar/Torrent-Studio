import asyncio

from catalogues import catalogues_movies as movies
from catalogues import catalogues_tv as tv


def test_new_regional_movie_catalogue_pages_contain_18_entries(monkeypatch):
    async def fetch_source_page(catalogue_key, page, released_only=True):
        return {
            "page": page,
            "totalPages": 1,
            "totalResults": 20,
            "results": [
                {
                    "id": index,
                    "title": f"Anime {index}",
                    "releaseDate": "2025-01-01",
                }
                for index in range(20)
            ],
        }

    async def enrich(payload):
        return payload

    monkeypatch.setattr(movies, "CACHE_ONLY_MODE", False)
    monkeypatch.setattr(movies, "CACHE_FIRST", False)
    monkeypatch.setattr(movies, "_tmdb_movie_catalogue_cache", {})
    monkeypatch.setattr(movies, "_read_tmdb_persistent_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(movies, "_write_tmdb_persistent_cache", lambda *args, **kwargs: None)
    monkeypatch.setattr(movies, "_tmdb_fetch_movie_catalogue", fetch_source_page)
    monkeypatch.setattr(movies, "_enrich_regional_movie_catalogue_metadata", enrich)

    result = asyncio.run(
        movies._api_tmdb_movie_catalogue("popular-anime", 1, True, 5, False)
    )

    assert result["pageSize"] == 18
    assert len(result["results"]) == 18


def test_pakistani_movies_include_titles_from_pakistan_not_only_urdu(monkeypatch):
    async def get_json(path, params):
        return {
            "page": 1,
            "total_pages": 1,
            "total_results": 3,
            "results": [
                {
                    "id": 1,
                    "title": "Pakistani English Film",
                    "original_language": "en",
                    "release_date": "2024-01-01",
                },
                {
                    "id": 2,
                    "title": "Pakistani Punjabi Film",
                    "original_language": "pa",
                    "origin_country": ["PK"],
                    "release_date": "2024-01-01",
                },
                {
                    "id": 3,
                    "title": "Unrelated English Film",
                    "original_language": "en",
                    "origin_country": ["US"],
                    "release_date": "2024-01-01",
                },
            ],
        }

    monkeypatch.setattr(movies, "_tmdb_get_json", get_json)
    result = asyncio.run(movies._tmdb_fetch_movie_catalogue("popular-pakistani", 1))

    assert [row["title"] for row in result["results"]] == [
        "Pakistani English Film",
        "Pakistani Punjabi Film",
    ]


def test_pakistani_tv_discovery_includes_punjabi_language_series(monkeypatch, tmp_path):
    async def get_json(path, params):
        if path == "discover/tv":
            assert params["with_origin_country"] == "PK"
            assert "with_original_language" not in params
            return {
                "page": 1,
                "total_pages": 1,
                "total_results": 1,
                "results": [{
                    "id": 101,
                    "name": "Punjabi Pakistani Series",
                    "original_language": "pa",
                    "origin_country": ["PK"],
                    "first_air_date": "2025-01-01",
                }],
            }
        return {
            "id": 101,
            "name": "Punjabi Pakistani Series",
            "original_name": "Punjabi Pakistani Series",
            "type": "Scripted",
            "first_air_date": "2025-01-01",
        }

    async def streaming_providers(tmdb_id):
        return [{"name": "Example", "type": "subscription"}]

    monkeypatch.setattr(tv, "_read_regional_tv_prebuilt_page", lambda *args: None)
    monkeypatch.setattr(tv, "_REGIONAL_TV_DISCOVERY_CACHE", {})
    monkeypatch.setattr(tv, "_tmdb_get_json", get_json)
    monkeypatch.setattr(tv, "_tv_streaming_providers", streaming_providers)
    monkeypatch.setattr(tv, "TMDB_READ_ACCESS_TOKENS", ["test-token"])
    monkeypatch.setattr(tv, "REGIONAL_TV_PREBUILT_CACHE_FILE", tmp_path / "regional-tv.json")

    result = asyncio.run(tv.api_tmdb_regional_tv_catalogue("pakistani-popular", page=1))

    assert result["pageSize"] == 18
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Punjabi Pakistani Series"
