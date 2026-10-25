#!/usr/bin/env python3
"""Why is a title missing from a catalogue? Shows what the torrent search returns and which rows the matcher accepts.

  cd ~/torrent-studio-refresh/repo/backend
  eval "$(python3 ../scripts/vps/load_env.py ~/.config/torrent-studio/env)"
  ../../venv/bin/python maintenance/debug_title_match.py "Kill Bill: Vol. 1" 2003
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from catalogues import catalogues_extra as extra  # noqa: E402


async def providers(query: str) -> None:
    """Each provider on its own, so a blocked one is visible."""
    calls = {
        "search_1337x": extra.search_1337x(query, limit=50, allow_series_fallback=False),
        "1337x direct": extra.search_1337x_direct(query, limit=50, pages=1, category="Movies", provider_query=query),
        "limetorrents": extra.search_limetorrents(query, limit=30, pages=1),
    }
    for name, call in calls.items():
        try:
            items = await asyncio.wait_for(call, timeout=40)
            print(f"   [{name}] {query!r}: {len(items)} results" + (f", first: {str(items[0].get('title'))[:70]}" if items else ""))
        except Exception as exc:
            print(f"   [{name}] {query!r}: FAILED {type(exc).__name__}: {exc}")


async def main(title: str, year: int) -> None:
    print("providers, one by one (Inception is a control that must return results):")
    for query in ("Inception 2010", "Kill Bill", f"{title} {year}"):
        await providers(query)
    for query in (f"{title} {year}", title, title.replace(":", "").replace(".", "")):
        try:
            items = await asyncio.wait_for(extra.search_1337x(query, limit=50, allow_series_fallback=False), timeout=40)
        except Exception as exc:
            print(f"query {query!r}: FAILED {type(exc).__name__}: {exc}")
            continue
        accepted = [item for item in items if extra._marvel_result_matches_title(item, title, year)]
        print(f"query {query!r}: {len(items)} results, {len(accepted)} accepted by the matcher")
        for item in items[:12]:
            ok = "OK  " if item in accepted else "skip"
            print(f"   {ok} {str(item.get('title'))[:90]}  [{item.get('indexer')}, seeders {item.get('seeders')}]")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2])))
