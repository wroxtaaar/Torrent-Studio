#!/usr/bin/env python3
"""Show exactly what Trakt returns, to settle which fields it offers (run with TRAKT_CLIENT_ID set).

    cd backend && CACHE_ONLY_MODE=false python maintenance/probe_trakt.py
"""
import asyncio
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("CACHE_ONLY_MODE", "false")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from integrations import mdblist, trakt  # noqa: E402


async def step(label: str, coro, limit: float = 25.0) -> None:
    """Run one probe step; a slow or failing call is reported, never allowed to stop the rest."""
    print(f"-> {label} ...", flush=True)
    try:
        result = await asyncio.wait_for(coro, limit)
    except asyncio.TimeoutError:
        print(f"   TIMED OUT after {limit:.0f}s", flush=True)
        return
    except Exception as exc:  # noqa: BLE001
        print(f"   FAILED: {type(exc).__name__}: {exc}", flush=True)
        return
    if isinstance(result, (dict, list)):
        text = json.dumps(result, indent=1)
        print("  ", text[:900] + (" ..." if len(text) > 900 else ""), flush=True)
    else:
        print("  ", result, flush=True)


async def main() -> None:
    if not trakt.trakt_client_ids():
        print("TRAKT_CLIENT_ID is not set.")
        return
    for kind, languages, countries in (("movies", "hi", "in"), ("movies", "hi", None), ("shows", "hi", None), ("movies", "en", None)):
        await step(f"trending {kind} languages={languages} countries={countries}",
                   trakt.trakt_trending(kind, languages=languages, countries=countries, limit=10))
    await step("movie details (Inception, extended=full)", trakt.trakt_get("/movies/tt1375666", {"extended": "full"}))
    await step("movie ratings (Inception)", trakt.trakt_get("/movies/tt1375666/ratings"))
    await step("rating helper", trakt.trakt_rating("movies", imdb_id="tt1375666"))
    if mdblist.mdblist_keys():
        await step("MDBList Inception (TMDB 27205)", mdblist.mdblist_imdb_rating("movie", tmdb_id=27205))
        await step("MDBList Breaking Bad (TMDB 1396)", mdblist.mdblist_imdb_rating("tv", tmdb_id=1396))
    else:
        print("MDBLIST_API_KEY is not set: skipping the MDBList check.")


asyncio.run(main())
