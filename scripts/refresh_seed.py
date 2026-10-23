#!/usr/bin/env python3
"""Refresh part of backend/cache-seed with live provider data (run from CI or locally).

    python scripts/refresh_seed.py hollywood-bollywood   # weekly workflow
    python scripts/refresh_seed.py franchise             # manual workflow (Marvel, DC, classics)

Needs TMDB / Watchmode / OMDb keys in the environment. It works on a temporary copy of the
seed, runs the backend with CACHE_FIRST=false so stale entries are really refreshed, and then
copies back only the files of that group that changed (and still parse as JSON). Nothing is
written to the seed if a step fails, so a bad run can never blank the bundled data.
"""
import json, os, shutil, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SEED = Path(os.getenv("REFRESH_SEED_DIR") or BACKEND / "cache-seed")  # VPS keeps its own working copy

# Files that live in runtime/ inside the seed (flat inside APP_DATA_DIR).
SHARED_RUNTIME = [
    "tmdb_movie_catalogue_cache.json", "tmdb_search_metadata_cache.json",
    "imdb_rating_cache.json", "tmdb_ott_availability_cache.json",
]
GROUPS = {
    "hollywood-bollywood": {
        "top": ["regional_tv_prebuilt_cache.json"],
        "runtime": SHARED_RUNTIME + [
            "regional_movie_prebuilt_cache.json", "regional_movie_trending_archive.json", "nexstream_cache.json",
        ],
    },
    "franchise": {
        "top": [
            "marvel_catalogue.json", "marvel_hindi_catalogue.json", "marvel_web_series_catalogue.json",
            "dc_live_action_catalogue.json", "dc_live_action_hindi_catalogue.json",
            "dc_animated_catalogue.json", "classics_catalogue.json",
        ],
        "runtime": SHARED_RUNTIME + ["marvel_tv_catalogue_cache.json", "dc_tv_catalogue_cache.json"],
    },
}


def stage(data_dir: Path) -> None:
    for f in SEED.glob("*.json"):
        shutil.copy2(f, data_dir / f.name)
    for f in (SEED / "runtime").glob("*.json"):
        shutil.copy2(f, data_dir / f.name)


def run(cmd, env, **kw):
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, env=env, check=True, **kw)


def wait_ready(base, proc, seconds=180):
    for _ in range(seconds):
        if proc.poll() is not None:
            raise SystemExit("backend exited early")
        try:
            urllib.request.urlopen(base + "/api/health", timeout=3).read()
            return
        except Exception:
            time.sleep(1)
    raise SystemExit("backend did not become healthy")


def refresh_hollywood_bollywood(env, data_dir):
    port = env.setdefault("PORT", "10111")
    base = f"http://127.0.0.1:{port}"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "fullstack_app:app", "--host", "127.0.0.1", "--port", port],
        cwd=BACKEND, env=env)
    try:
        wait_ready(base, server)
        env = {**env, "HOME_DATA_DIR": str(data_dir), "HOME_API_BASE": base}
        run([sys.executable, str(ROOT / "scripts" / "build_regional_movie_cache.py")], env)
    finally:
        server.terminate()
        try:
            server.wait(20)
        except subprocess.TimeoutExpired:
            server.kill()


def refresh_franchise(env, data_dir):
    run([sys.executable, "maintenance/refresh_franchise_ott.py", "--region", "IN"], env, cwd=BACKEND)
    run([sys.executable, "-c",
         "import asyncio; from catalogues import catalogues_extra as c; asyncio.run(c._enrich_catalogue_synopses())"],
        env, cwd=BACKEND)


def valid_json(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except Exception:
        return False


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in GROUPS:
        raise SystemExit(__doc__)
    group = sys.argv[1]
    if not any(os.getenv(k) for k in ("TMDB_API_KEY", "TMDB_API_KEYS", "TMDB_READ_ACCESS_TOKEN", "TMDB_READ_ACCESS_TOKENS")):
        raise SystemExit("No TMDB key in the environment; refusing to run (nothing would be refreshed).")
    with tempfile.TemporaryDirectory(prefix="seed-refresh-") as tmp:
        data_dir = Path(tmp) / "data"
        data_dir.mkdir()
        stage(data_dir)
        env = {
            **os.environ,
            "APP_DATA_DIR": str(data_dir),
            "CACHE_SEED_DIR": str(Path(tmp) / "no-seed"),  # already staged; do not re-seed
            "CACHE_ONLY_MODE": "false",
            "CACHE_FIRST": "false",  # stale entries must really be refreshed here
            "BACKFILL_MISSING_METADATA": "true",
            "PYTHONPATH": str(BACKEND),
        }
        if group == "hollywood-bollywood":
            refresh_hollywood_bollywood(env, data_dir)
        else:
            refresh_franchise(env, data_dir)

        changed = []
        spec = GROUPS[group]
        for sub, names in (("", spec["top"]), ("runtime", spec["runtime"])):
            for name in names:
                new, old = data_dir / name, SEED / sub / name
                if not new.is_file() or not valid_json(new):
                    continue
                if old.is_file() and old.read_bytes() == new.read_bytes():
                    continue
                shutil.copy2(new, old)
                changed.append(str((old).relative_to(SEED)))
        print("CHANGED:", json.dumps(changed))


if __name__ == "__main__":
    main()
