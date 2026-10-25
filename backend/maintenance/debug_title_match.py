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


async def main(title: str, year: int) -> None:
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
