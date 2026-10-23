"""Hollywood/Bollywood: pages 1-3 (18 titles each) come from the cache, later pages from the live API."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_three_cached_pages_then_live_pages_continue_without_repeats():
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "CACHE_ONLY_MODE": "false", "CACHE_FIRST": "true", "BACKFILL_MISSING_METADATA": "false",
            "TMDB_API_KEY": "k", "TMDB_READ_ACCESS_TOKEN": "t", "SEEDR_SESSION_SECRET": "test-only-session-secret",
            "APP_DATA_DIR": str(Path(tmp) / "data"), "CACHE_SEED_DIR": str(Path(tmp) / "seed"),
        }
        proc = subprocess.run([sys.executable, str(BACKEND / "tests" / "cached_pages_driver.py")],
                              cwd=BACKEND, env=env, capture_output=True, text=True, timeout=300)
    line = next((l for l in proc.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line, proc.stdout[-2000:] + proc.stderr[-2000:]
    out = json.loads(line[7:])

    cached_ids = set()
    for page in ("p1", "p2", "p3"):
        assert out[page]["status"] == 200 and out[page]["n"] == 18, out[page]
        assert out[page]["totalPages"] == 4  # the UI is told that more pages exist
        cached_ids |= set(out[page]["ids"])
    assert len(cached_ids) == 54
    assert out["live_calls_after_cached_pages"] == []  # pages 1-3 never touched the live API

    assert out["p4"]["status"] == 200 and out["p4"]["n"] == 18
    assert not cached_ids & set(out["p4"]["ids"])  # continues after the cache, no repeats
