"""Titles no provider had a release for, with the date they were last tried.

Scanners skip a title for TORRENT_MISS_DAYS (default 14) after a miss, so brand-new releases get a rest
period instead of being searched every week. Kept outside the cache, in <TS_HOME>/state/torrent-misses.json.
"""
from __future__ import annotations

import json, os
from datetime import date, timedelta
from pathlib import Path

DAYS = int(os.getenv("TORRENT_MISS_DAYS", "14"))
FILE = Path(os.getenv("TORRENT_MISS_FILE") or Path(os.getenv("TS_HOME") or Path.home() / "torrent-studio-refresh") / "state" / "torrent-misses.json")


def load() -> dict[str, str]:
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def resting(misses: dict[str, str], key: str) -> bool:
    try:
        return date.fromisoformat(misses[key]) > date.today() - timedelta(days=DAYS)
    except Exception:
        return False


def record(key: str, found: bool, misses: dict[str, str]) -> None:
    if found:
        misses.pop(key, None)
    else:
        misses[key] = date.today().isoformat()


def save(misses: dict[str, str]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(misses, indent=0, sort_keys=True), encoding="utf-8")
    os.replace(tmp, FILE)
