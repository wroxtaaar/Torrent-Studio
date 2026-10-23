"""Cache-first guard: data that is already cached must never trigger a provider request.

tests/cache_first_driver.py boots the real app with provider keys configured and
CACHE_ONLY_MODE off, installs the bundled cache seed into an empty data directory and
blocks every outbound HTTP request. Any request it records is a cache leak.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def run():
    with tempfile.TemporaryDirectory() as data_dir:
        env = {
            **os.environ,
            "CACHE_ONLY_MODE": "false",
            "CACHE_FIRST": "true",
            "TMDB_API_KEY": "test-key",
            "TMDB_READ_ACCESS_TOKEN": "test-token",
            "WATCHMODE_API_KEY": "test-key",
            "OMDB_API_KEY": "test-key",
            "SEEDR_SESSION_SECRET": "test-only-session-secret",
            "APP_DATA_DIR": data_dir,
            "CACHE_SEED_DIR": str(BACKEND / "cache-seed"),
        }
        proc = subprocess.run(
            [sys.executable, str(BACKEND / "tests" / "cache_first_driver.py")],
            cwd=BACKEND, env=env, capture_output=True, text=True, timeout=600,
        )
        assert proc.returncode == 0, (proc.stderr or proc.stdout)[-1800:]
        line = next(l for l in proc.stdout.splitlines() if l.startswith("RESULT="))
        yield json.loads(line[len("RESULT="):]), Path(data_dir)


def test_cached_data_never_reaches_a_provider(run):
    result, _ = run
    calls = result["calls"]
    summary = {}
    for endpoint, method, url in calls:
        summary.setdefault(endpoint, []).append(url)
    detail = " | ".join(f"{endpoint} -> {urls[0]} (+{len(urls) - 1} more)" for endpoint, urls in list(summary.items())[:12])
    assert not calls, f"{len(calls)} provider request(s) despite cached data: {detail}"


def test_seeded_endpoints_answer_from_cache(run):
    result, _ = run
    failing = {path: status for path, status in result["statuses"].items() if status >= 500}
    assert not failing, f"endpoints failed with the bundled cache only: {dict(list(failing.items())[:8])}"


def test_runtime_cache_is_installed_from_the_seed(run):
    _, data_dir = run
    for name in ("tmdb_movie_catalogue_cache.json", "imdb_rating_cache.json", "tmdb_ott_availability_cache.json"):
        assert (data_dir / name).is_file(), f"{name} was not seeded into APP_DATA_DIR"
