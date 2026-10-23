"""Run by test_cached_pages.py in a fresh interpreter (live mode on, synthetic 60-title cache)."""
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
seed = Path(os.environ["CACHE_SEED_DIR"])
(seed / "runtime").mkdir(parents=True)
movies = {}
for i in range(60):
    movies[f"m{i}|2025"] = {"catalogues": ["popular-hollywood"], "movie": {
        "id": 1000 + i, "tmdbId": 1000 + i, "title": f"Cached {i}", "year": 2025,
        "releaseDate": f"2025-{1 + i // 5:02d}-{1 + i % 5:02d}"}}
(seed / "runtime" / "regional_movie_prebuilt_cache.json").write_text(json.dumps({"movies": movies}))

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
from catalogues import catalogues_movies as cm  # noqa: E402

live_calls = []


async def fake_source(catalogue_key, source_page, released_only=True):
    live_calls.append(source_page)
    # Source page 1 overlaps the cached titles; later pages are brand new.
    base = 1000 if source_page == 1 else 5000 + source_page * 100
    return {"page": source_page, "totalPages": 40, "results": [
        {"id": base + n, "tmdbId": base + n, "title": f"Live {source_page}-{n}", "year": 2024,
         "releaseDate": "2024-01-01"} for n in range(20)]}


async def passthrough(payload, *a, **k):
    return payload

cm._tmdb_fetch_movie_catalogue = fake_source
cm._apply_movie_release_eligibility = passthrough
cm._enrich_regional_movie_catalogue_metadata = passthrough

out = {}
with TestClient(main.app, raise_server_exceptions=False) as client:
    for page in (1, 2, 3):
        r = client.get(f"/api/movies/catalogue/popular-hollywood?page={page}")
        body = r.json()
        out[f"p{page}"] = {"status": r.status_code, "n": len(body.get("results", [])),
                           "totalPages": body.get("totalPages"), "ids": [x["id"] for x in body.get("results", [])]}
    out["live_calls_after_cached_pages"] = list(live_calls)
    r = client.get("/api/movies/catalogue/popular-hollywood?page=4")
    body = r.json()
    out["p4"] = {"status": r.status_code, "n": len(body.get("results", [])), "totalPages": body.get("totalPages"),
                 "ids": [x["id"] for x in body.get("results", [])]}
print("RESULT " + json.dumps(out))
