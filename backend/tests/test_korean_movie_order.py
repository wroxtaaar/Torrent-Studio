import asyncio

from catalogues import catalogues_movies as movies
from catalogues.korean_movie_order import KOREAN_MOVIE_POPULARITY_ORDER


def test_korean_movie_order_keeps_50_list_first_and_appends_only_new_100_list_titles():
    imdb_ids = [imdb_id for imdb_id, _ in KOREAN_MOVIE_POPULARITY_ORDER]
    titles = [title for _, title in KOREAN_MOVIE_POPULARITY_ORDER]

    assert len(KOREAN_MOVIE_POPULARITY_ORDER) == 127
    assert len(imdb_ids) == len(set(imdb_ids))
    assert titles[:3] == ["Parasite", "Silenced", "My Sassy Girl"]
    assert titles[49:53] == ["Broker", "Hope", "Colony", "Possible Love"]


def test_popular_korean_catalogue_resolves_curated_titles_in_source_order(monkeypatch):
    async def fake_tmdb_get_json(path, params):
        imdb_id = path.split("/")[-1]
        title = next(title for candidate_id, title in KOREAN_MOVIE_POPULARITY_ORDER if candidate_id == imdb_id)
        return {
            "movie_results": [{
                "id": int(imdb_id[2:]),
                "title": title,
                "release_date": "2024-01-01",
                "poster_path": "/poster.jpg",
                "backdrop_path": "/backdrop.jpg",
                "overview": "Overview",
                "vote_average": 7.5,
                "genre_ids": [18],
            }]
        }

    monkeypatch.setattr(movies, "_tmdb_get_json", fake_tmdb_get_json)
    monkeypatch.setattr(movies, "_tmdb_movie_catalogue_cache", {})
    result = asyncio.run(movies._korean_movie_curated_page(1))

    assert [row["title"] for row in result["results"]] == [
        title for _, title in KOREAN_MOVIE_POPULARITY_ORDER[:18]
    ]
    assert result["totalResults"] == 127
    assert result["totalPages"] == 8
