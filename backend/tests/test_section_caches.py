import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from catalogues import section_caches


@pytest.mark.parametrize("section", sorted(section_caches.SECTION_CACHE_NAMES))
def test_section_cache_route_reads_only_requested_self_contained_file(monkeypatch, tmp_path, section):
    payload = {
        "schemaVersion": 1,
        "section": section,
        "metadataSelfContained": True,
        "subsections": {
            "movies": {
                "mediaType": "movie",
                "pageSize": 18,
                "results": [{
                    "id": 123,
                    "tmdbId": 123,
                    "title": "Example Anime",
                    "imdbRating": 8.1,
                    "ottAvailability": None,
                }],
            },
            "tv-popular": {
                "mediaType": "tv",
                "pageSize": 18,
                "pageCount": 1,
                "totalResults": 1,
                "results": [{
                    "id": 456,
                    "tmdbId": 456,
                    "title": "Example TV",
                    "imdbId": "tt0000456",
                    "streamingProviders": [{"name": "Example Provider", "type": "subscription"}],
                }],
            },
        },
    }
    (tmp_path / f"{section}.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "tmdb_movie_catalogue_cache.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(section_caches, "SECTION_CACHE_DIR", tmp_path)
    original_read_text = Path.read_text
    reads = []

    def track_read(path, *args, **kwargs):
        reads.append(path.name)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", track_read)

    result = asyncio.run(section_caches.api_get_section_cache(section))

    assert result == payload
    assert reads == [f"{section}.json"]


@pytest.mark.parametrize("section", ["unknown", "../anime", "anime/runtime"])
def test_section_cache_route_rejects_unknown_file_paths(section):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(section_caches.api_get_section_cache(section))
    assert exc.value.status_code == 404


def test_section_cache_route_reports_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(section_caches, "SECTION_CACHE_DIR", tmp_path)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(section_caches.api_get_section_cache("anime"))
    assert exc.value.status_code == 404
