# Splitting `backend/main.py`

`backend/main.py` grew to ~16,400 lines (627 top-level statements, 93 routes).
This document is the plan and the progress tracker for breaking it into
modules **without changing behavior**. It is written so the work can be done in
small steps, across separate sessions: every step leaves `main` green and
pushed, so it is safe to stop after any step.

**To continue:** open the first unchecked step below and follow
[How to do a step](#how-to-do-a-step). Tick the box (and edit anything that
turned out different) in the same commit as the step.

## Progress

- [x] **Step 1 – Safety net and tooling** (`scripts/refactor/`, structure snapshot test, ruff check in CI)
- [x] **Step 2 – `settings.py` + `shared.py` + `http_cache.py`**: all plain configuration (env vars, flags, keys/bases, TTLs, file paths, search limits, CORS values, logger); request-scoped context variables and `SeedrError` in `shared.py`; response-memo helpers in `http_cache.py`. Runtime *state* (caches, semaphores, HTTP clients, rate-limit timestamps) deliberately stayed in `main.py` and moves with its owner in the later steps.
- [x] **Step 3 – `seedr_session.py` + `feedback.py`**: cookie session, CSRF, token normalisation (`normalize_seedr_token` moves here to break a cycle), feedback route and rate limit
- [x] **Step 4 – `seedr_client.py`**: low-level Seedr API (`seedr_request`, legacy + v2 helpers, task helpers, magnet normalisation). The cleanup worker (`_cleanup_seedr_job` calls the `seedr_folder_delete` route, and `_seedr_cleanup_jobs` is rebound next to the cancel helpers) stays in main.py and moves in step 15 with the delete routes.
- [ ] **Step 5 – `torrent_metadata.py`**: .torrent decoding, libtorrent, metadata jobs, inspect-magnet routes
- [ ] **Step 6 – `tmdb.py` (+ `ott.py`)**: TMDB / Watchmode / OMDB HTTP clients, persistent TMDB caches, OTT lookups
- [ ] **Step 7 – `posters.py`**
- [ ] **Step 8 – `search_providers.py`**: 1337x, YTS, EZTV, LimeTorrents, Knaben, torrents-csv, apibay, ranking, `/api/search*`
- [ ] **Step 9 – `catalogues_extra.py` + `synopsis_enrichment.py`**: Marvel and extra catalogues, bundled-cache seeding, synopsis enrichment
- [ ] **Step 10 – `catalogues_tv.py`**
- [ ] **Step 11 – `catalogues_movies.py`**: regional movie catalogues, schedulers
- [ ] **Step 12 – `search_metadata.py` + `imdb.py`**: availability, metadata, IMDb ratings
- [ ] **Step 13 – Seedr routes, part 1**: connect / auth / quota / add / task progress
- [ ] **Step 14 – Seedr routes, part 2**: library, folders, downloads
- [ ] **Step 15 – Seedr media**: HLS, ffprobe, subtitles, audio/video streaming, cancel and delete
- [ ] **Step 16 – `compat_routes.py`** and the remaining small routes (`/health`, `/api/health`, cache report, resolve-magnet)
- [ ] **Step 17 – Final cleanup**: `main.py` becomes app assembly only; point the maintenance scripts and tests at the new modules; remove the duplicate dead route; README architecture note

Frontend (`TorrentSearchPanel.tsx` ~5.6k lines, `App.tsx` ~3.7k lines) is a
separate plan, to be written after this one.

> The order is by dependency (lowest layer first) and was checked with the
> analysis tool: e.g. search providers call the poster helpers, the poster
> helpers call TMDB, so TMDB → posters → search providers.

## How to do a step

```bash
python3 -I scripts/refactor/stubcheck.py --check        # baseline: must print "structure matches snapshot"
python3 -I scripts/refactor/extract.py status           # sizes
python3 -I scripts/refactor/extract.py outline --lines 4312-5070   # choose line ranges
python3 -I scripts/refactor/extract.py plan  --module posters --lines 4312-5070
python3 -I scripts/refactor/extract.py apply --module posters --lines 4312-5070
```

`apply` writes `backend/<module>.py`, replaces the code in `main.py` with one
`from <module> import ...`, converts `@app.get` to a module `router` that is
included at the *same position* (route order matters), turns
`@app.on_event` into an explicit `app.router.add_event_handler` at the same
position, then verifies compile + undefined names + app structure and **undoes
everything if anything fails**. `plan` explains what blocks a move (code that
would have to import `main` back, shared state that must move together…).

Resolve what `plan` reports by moving the blocking definitions in the same
step (list them in `--lines`/`--names`) or by moving them to an already
extracted module first. Then:

1. Update tests that patched moved names (`apply` lists them), e.g.
   `monkeypatch.setattr(main, "X", …)` must now patch the module where `X`
   is *used*.
2. `python3 -I scripts/refactor/extract.py check` and
   `python3 -I scripts/refactor/stubcheck.py --check`.
3. Commit, push to `main`, wait for CI (backend tests, undefined-name check,
   structure snapshot, frontend, Docker) to be green.
4. Tick the step above.

The offline tools exist because the authoring sandbox cannot install FastAPI.
CI runs the same checks against the real FastAPI app, which is the final judge.

## Things that bite (found by the analysis)

* **Route order is behavior.** FastAPI uses the first matching route. The
  snapshot test (`backend/tests/test_app_structure.py`, data in
  `backend/tests/snapshots/app_structure.json`) pins the order of routes,
  middleware, exception handlers and startup/shutdown hooks. If a step
  intentionally changes it, regenerate with
  `python3 -I scripts/refactor/stubcheck.py --write` and say why in the commit.
* **Variables reassigned with `global`** must live in the same module as every
  function that reassigns them, otherwise the function silently creates a
  different variable. The tool enforces this. Groups that must move together:
  * TMDB/OMDB/Watchmode HTTP clients and rate-limit timestamps
    (`_TMDB_HTTP_CLIENT`, `_OMDB_HTTP_CLIENT`, `_WATCHMODE_*`) with
    `_tmdb_get_json`, `_watchmode_get`, `_close_tmdb_http_client` **and
    `_fetch_imdb_rating`** (it reassigns the OMDB client). When IMDb moves
    (step 12) give the OMDB client its own accessor in `tmdb.py` first.
  * Seedr metadata cache/task with `get_seedr_metadata_tree`,
    `_prepare_seedr_space`, `_cancel_seedr_task_and_partial_folder`, the
    cancel/replace helpers and the delete routes.
  * Seedr cleanup jobs/worker, libtorrent session, metadata cache, the Marvel
    catalogue task, classics OTT enrichment task, both synopsis enrichment
    task groups, `_BUNDLED_POSTERS`, `_IMDB_RATING_CACHE`.
  * Tip: `python3 -I scripts/refactor/extract.py outline` shows `[rebinds …]` next to such statements.
* **Config that sits in the wrong block.** `_CACHE_SEED_DIR` (line ~6148) and
  `REGIONAL_TV_PREBUILT_CACHE_FILE` (~9172) are plain configuration used by
  several layers; they move to `settings.py` in step 2, which removes the
  catalogue ↔ memo/posters/TV cycles.
* **`normalize_seedr_token`** is used by the session code but defined in the
  Seedr client block; it moves to `seedr_session.py` (step 3).
* **Middleware, `app = FastAPI(...)`, CORS and the exception handler stay in
  `main.py`** (they use `app` directly and their order is pinned).
* **Maintenance scripts do `import main`** and use 20 names from it:
  `MARVEL_CATALOGUE_PATH, MARVEL_MOVIE_SEARCHES, TMDB_API_KEYS,
  TMDB_CATALOGUE_CACHE_FILE, TMDB_OTT_CACHE_FILE, TMDB_OTT_CACHE_SECONDS,
  TMDB_READ_ACCESS_TOKENS, WATCHMODE_API_KEYS, _EXTRA_CATALOGUE_PATHS,
  _normalize_title, _read_tmdb_ott_persistent_cache,
  _read_tmdb_persistent_cache, _resolve_marvel_tmdb_movie_id,
  _tmdb_fetch_movie_ott_availability, _tmdb_get_json, _tmdb_ott_cache,
  _watchmode_get, _watchmode_provider_rows,
  _write_tmdb_ott_persistent_cache, search_1337x`.
  `apply` keeps these importable from `main`; `test_app_structure.py` fails if
  one disappears. Step 17 points the scripts at the real modules.
* **Modules stay flat in `backend/`.** Several modules locate files relative to
  `__file__`; keeping the same directory keeps those paths valid. The Dockerfile
  copies `backend/` as-is, so no change is needed there.
* **A route is registered twice:** `/api/seedr/files/{file_id}/subtitle`
  (`seedr_file_subtitle`, ~lines 2482 and 15368). The first always wins, the
  second is dead. Both are kept until step 17, then the dead one is removed.
* **Already fixed on the way:** two names used but never defined
  (`is_anime_film` in the Marvel TV builder, `_discover_latest_catalogue_jobs`
  in the extra-catalogue builder), see the commit "Fix two references to
  names that were never defined".

## What was built in step 1

| File | Purpose |
| --- | --- |
| `scripts/refactor/lib.py` | Static analysis (stdlib only): per top-level statement, what it defines, reads and reassigns with `global` |
| `scripts/refactor/extract.py` | `status`, `outline`, `plan`, `apply`, `check` (see above) |
| `scripts/refactor/stubcheck.py` | Imports `main.py` against recording stand-ins for FastAPI & co. and prints/compares the app structure |
| `backend/tests/app_structure.py` | Shared extraction of routes/middleware/hooks (used by CI and by `stubcheck.py`) |
| `backend/tests/test_app_structure.py` | CI test: real app vs snapshot; scripts' `main.<name>` still exist |
| `backend/tests/snapshots/app_structure.json` | The snapshot (derived two independent ways: static source analysis and stub import) |
| `.github/workflows/ci.yml` | Adds `ruff --select F821,F823` (undefined names) to the backend job |
| `backend/tests/conftest.py` | On GitHub Actions, failing tests also print `::error` annotations (readable without the full log) |
