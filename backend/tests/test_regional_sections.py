import asyncio
import json

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


def test_pakistani_movies_reject_indian_origin_and_keep_pakistani_english_titles(monkeypatch):
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
                    "origin_country": ["PK"],
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
                {
                    "id": 4,
                    "title": "Hindi Bollywood Film",
                    "original_language": "hi",
                    "origin_country": ["IN"],
                    "release_date": "2024-01-01",
                },
                {
                    "id": 5,
                    "title": "Cross-border Film",
                    "original_language": "ur",
                    "origin_country": ["PK", "IN"],
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


def test_pakistani_trending_archive_filters_indian_entries(monkeypatch):
    monkeypatch.setattr(movies, "_tmdb_movie_catalogue_cache", {})
    monkeypatch.setattr(movies, "_read_regional_movie_trending_archive", lambda: {
        "weeks": [{
            "weekOf": "2025-01-01",
            "catalogues": {
                "trending-pakistani": [
                    {"id": 1, "title": "Pakistani Film", "originCountry": ["PK"]},
                    {"id": 2, "title": "Indian Film", "originCountry": ["IN"], "originalLanguage": "hi"},
                ],
            },
        }],
    })

    result = movies._regional_movie_trending_archive_page("trending-pakistani", 1)

    assert [row["title"] for row in result["results"]] == ["Pakistani Film"]


def test_pakistani_prebuilt_movies_filter_indian_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(movies, "REGIONAL_MOVIE_PREBUILT_CACHE_PATH", tmp_path / "prebuilt.json")
    monkeypatch.setattr(movies, "_CACHE_SEED_DIR", tmp_path)
    monkeypatch.setattr(movies, "read_json_cached", lambda path: {
        "catalogues": {
            "popular-pakistani": {
                "final": [
                    {"id": 1, "title": "Pakistani Film", "originCountry": ["PK"]},
                    {"id": 2, "title": "Indian Film", "originCountry": ["IN"], "originalLanguage": "hi"},
                ],
            },
        },
    })

    result = movies._prebuilt_final_page("popular-pakistani", 1)

    assert [row["title"] for row in result["results"]] == ["Pakistani Film"]


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


def test_pakistani_tv_cache_filter_rejects_indian_titles():
    assert tv._is_pakistani_tv_row({"originCountry": ["PK"], "originalLanguage": "ur"})
    assert not tv._is_pakistani_tv_row({"originCountry": ["IN"], "originalLanguage": "hi"})
    assert not tv._is_pakistani_tv_row({"originCountry": ["PK", "IN"], "originalLanguage": "ur"})


def test_pakistani_tv_prebuilt_pages_backfill_after_filtering(monkeypatch, tmp_path):
    rows = [
        {"id": index, "title": f"Pakistani Series {index}", "originCountry": ["PK"]}
        for index in range(19)
    ]
    rows.insert(3, {"id": 99, "title": "Indian Series", "originCountry": ["IN"]})
    cache_path = tmp_path / "regional-tv.json"
    cache_path.write_text(json.dumps({
        "schemaVersion": 3,
        "catalogues": {
            "pakistani-popular": {
                "status": "ready",
                "seriesCount": len(rows),
                "pages": [{"page": 1, "results": rows}],
            },
        },
    }), encoding="utf-8")
    monkeypatch.setattr(tv, "REGIONAL_TV_PREBUILT_CACHE_FILE", cache_path)

    first_page = tv._read_regional_tv_prebuilt_page("pakistani-popular", 1)
    second_page = tv._read_regional_tv_prebuilt_page("pakistani-popular", 2)

    assert len(first_page["results"]) == 18
    assert len(second_page["results"]) == 1
    assert first_page["totalResults"] == 19
    assert all(row["originCountry"] == ["PK"] for row in first_page["results"] + second_page["results"])


def test_regional_tv_response_is_enriched_with_imdb_rating(monkeypatch):
    async def get_rating(title, year, media_type, tmdb_id):
        assert (title, year, media_type, tmdb_id) == ("Example Series", 2024, "tv", 12)
        return {
            "status": "found",
            "imdbRating": 8.2,
            "imdbVotes": 1234,
            "imdbId": "tt0000012",
            "imdbUrl": "https://www.imdb.com/title/tt0000012/",
        }

    monkeypatch.setattr(tv, "_get_imdb_rating_record", get_rating)
    payload = {"results": [{"id": 12, "title": "Example Series", "year": 2024}]}

    result = asyncio.run(tv._enrich_regional_tv_imdb_ratings(payload))

    assert result["results"][0]["imdbRating"] == 8.2
    assert result["results"][0]["imdbId"] == "tt0000012"
    assert result["results"][0]["imdbRatingStatus"] == "found"


def test_regional_tv_rows_deduplicate_same_series_by_id_and_title_year():
    rows = [
        {"id": 101, "title": "Example Drama", "year": 2022},
        {"id": 101, "title": "Example Drama", "year": 2022},
        {"id": 202, "title": " Example Drama! ", "year": 2022},
        {"id": 303, "title": "Another Drama", "year": 2022},
    ]

    result = tv._dedupe_regional_tv_rows(rows)

    assert [row["id"] for row in result] == [101, 303]



def test_korean_tv_prebuilt_results_apply_release_type_origin_and_ott_filters(monkeypatch):
    async def get_json(path, params):
        tmdb_id = int(path.split("/")[-1])
        return {
            1: {
                "id": 1, "name": "Old Korean Drama", "first_air_date": "2014-12-01",
                "origin_country": ["KR"], "original_language": "ko", "type": "Scripted",
                "genres": [{"id": 18, "name": "Drama"}],
            },
            2: {
                "id": 2, "name": "Eligible Korean Drama", "first_air_date": "2022-01-01",
                "origin_country": ["KR"], "original_language": "ko", "type": "Scripted",
                "genres": [{"id": 18, "name": "Drama"}],
            },
            3: {
                "id": 3, "name": "Korean Variety Show", "first_air_date": "2022-01-01",
                "origin_country": ["KR"], "original_language": "ko", "type": "Reality",
                "genres": [{"id": 10764, "name": "Reality"}],
            },
            4: {
                "id": 4, "name": "Non-Korean Series", "first_air_date": "2022-01-01",
                "origin_country": ["US"], "original_language": "en", "type": "Scripted",
                "genres": [{"id": 18, "name": "Drama"}],
            },
        }[tmdb_id]

    async def streaming_providers(tmdb_id):
        return [{"name": "Example OTT", "type": "subscription"}] if tmdb_id == 2 else []

    async def enrich(payload):
        return payload

    monkeypatch.setattr(tv, "_read_regional_tv_prebuilt_page", lambda *args: {
        "catalogue": "korean-popular",
        "page": 1,
        "totalPages": 1,
        "totalResults": 4,
        "results": [
            {"id": 1, "title": "Old Korean Drama", "releaseDate": "2014-12-01"},
            {"id": 2, "title": "Eligible Korean Drama", "releaseDate": "2022-01-01"},
            {"id": 3, "title": "Korean Variety Show", "releaseDate": "2022-01-01"},
            {"id": 4, "title": "Non-Korean Series", "releaseDate": "2022-01-01"},
        ],
    })
    monkeypatch.setattr(tv, "_tmdb_get_json", get_json)
    monkeypatch.setattr(tv, "_tv_streaming_providers", streaming_providers)
    monkeypatch.setattr(tv, "_enrich_regional_tv_imdb_ratings", enrich)

    result = asyncio.run(tv.api_tmdb_regional_tv_catalogue("korean-popular", page=1))

    assert [row["title"] for row in result["results"]] == ["Eligible Korean Drama"]
