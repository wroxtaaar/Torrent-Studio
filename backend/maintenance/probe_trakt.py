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
from integrations import trakt  # noqa: E402


async def main() -> None:
    if not trakt.trakt_client_ids():
        print("TRAKT_CLIENT_ID is not set.")
        return
    for kind, languages, countries in (("movies", "hi", "in"), ("movies", "en", None), ("shows", "hi", "in")):
        items = await trakt.trakt_trending(kind, languages=languages, countries=countries, limit=10)
        print(f"trending {kind} languages={languages} countries={countries}: {len(items)}")
        for item in items[:5]:
            print("   ", item)
    for path in ("/movies/tt1375666?extended=full", "/movies/tt1375666/ratings"):
        data = await trakt.trakt_get(path.split("?")[0], {"extended": "full"} if "?" in path else None)
        print(path, "->", json.dumps(data, indent=1)[:900] if data else data)
    print("rating helper:", await trakt.trakt_rating("movies", imdb_id="tt1375666"))


asyncio.run(main())
