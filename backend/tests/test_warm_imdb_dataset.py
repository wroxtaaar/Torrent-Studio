import asyncio
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintenance"))
import warm_imdb_dataset as wid  # noqa: E402
from core import settings  # noqa: E402
from metadata import imdb, tmdb  # noqa: E402


def test_ratings_come_from_the_dataset_through_tmdb_imdb_ids(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "regional_tv_prebuilt_cache.json").write_text(json.dumps(
        {"catalogues": {"x": {"pages": [{"results": [{"id": 11, "title": "Show A", "year": 2020, "posterUrl": "/p"}]}]}}}))
    (data / "marvel_catalogue.json").write_text(json.dumps(
        {"results": [{"title": "Film B (2021) [1080p]", "mediaTitle": "Film B", "year": 2021, "tmdbId": 22}]}))
    work = tmp_path / "work"
    work.mkdir()
    dataset = work / "title.ratings.tsv.gz"
    with gzip.open(dataset, "wt") as handle:
        handle.write("tconst\taverageRating\tnumVotes\ntt0000011\t8.4\t12345\ntt0000022\t7.1\t999\n")

    async def fake_tmdb(path, params=None, *, request_timeout=12.0):
        return {"imdb_id": {"tv/11/external_ids": "tt0000011", "movie/22/external_ids": "tt0000022"}[path]}

    cache_file = tmp_path / "imdb_rating_cache.json"
    monkeypatch.setattr(settings, "DATA_DIR", data)
    monkeypatch.setattr(imdb, "IMDB_RATING_CACHE_FILE", cache_file)
    monkeypatch.setattr(imdb, "_IMDB_RATING_CACHE", None)
    monkeypatch.setattr(tmdb, "_tmdb_get_json", fake_tmdb)
    monkeypatch.setattr(wid, "WORK", work)
    monkeypatch.setattr(wid, "DATASET", dataset)
    monkeypatch.setattr(wid, "ID_MAP", work / "ids.json")

    asyncio.run(wid.main())

    records = {r["cacheKey"]: r for r in json.loads(cache_file.read_text())["results"]}
    show = records[imdb._imdb_rating_cache_key("Show A", 2020, "tv")]
    film = records[imdb._imdb_rating_cache_key("Film B", 2021, "movie")]
    assert (show["imdbRating"], show["imdbVotes"], show["imdbId"]) == (8.4, "12,345", "tt0000011")
    assert film["imdbRating"] == 7.1 and film["ratingLookupSource"] == "imdb_dataset"
    assert (work / "ids.json").is_file()  # ids are remembered between runs
