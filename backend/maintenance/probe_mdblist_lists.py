#!/usr/bin/env python3
"""Look at MDBList's own lists (freshness and items) for Bollywood trending (run with MDBLIST_API_KEY set).

    cd backend && CACHE_ONLY_MODE=false python maintenance/probe_mdblist_lists.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import httpx  # noqa: E402
from integrations.mdblist import MDBLIST_BASE, mdblist_keys  # noqa: E402


async def get(client: httpx.AsyncClient, key: str, path: str, **params):
    print(f"-> {path} {params or ''}", flush=True)
    try:
        r = await asyncio.wait_for(client.get(MDBLIST_BASE + path, params={"apikey": key, **params}), 25)
    except Exception as exc:  # noqa: BLE001
        print(f"   FAILED: {type(exc).__name__}: {exc}", flush=True)
        return None
    print(f"   HTTP {r.status_code}", flush=True)
    try:
        return r.json()
    except ValueError:
        print("   not JSON:", r.text[:200])
        return None


def show(data, limit=1400):
    text = json.dumps(data, indent=1, ensure_ascii=False)
    print("  ", text[:limit] + (" ..." if len(text) > limit else ""), flush=True)


def rows(data, kind):
    out = []
    for row in (data or {}).get(kind) or []:
        out.append((row.get("rank"), row.get("title"), row.get("release_year") or row.get("year"),
                    row.get("id") or (row.get("ids") or {}).get("tmdb"), row.get("language")))
    return out


async def main() -> None:
    keys = mdblist_keys()
    if not keys:
        print("MDBLIST_API_KEY is not set.")
        return
    async with httpx.AsyncClient(timeout=20) as client:
        info = await get(client, keys[0], "/lists/apollocat/trending-bollywood-movies")
        show(info)
        items = await get(client, keys[0], "/lists/apollocat/trending-bollywood-movies/items", limit=15)
        if isinstance(items, dict):
            print("   keys:", list(items))
            for kind in ("movies", "shows"):
                print(f"   {kind}:", rows(items, kind)[:15])
        else:
            show(items)
        for query in ("bollywood", "indian web series", "hindi series"):
            found = await get(client, keys[0], "/lists/search", query=query)
            if isinstance(found, list):
                for lst in found[:8]:
                    print("   ", lst.get("user_name"), "/", lst.get("slug"), "|", lst.get("name"), "| items:", lst.get("items"),
                          "| updated:", lst.get("updated"), "| mediatype:", lst.get("mediatype"))
            else:
                show(found, 500)


asyncio.run(main())
