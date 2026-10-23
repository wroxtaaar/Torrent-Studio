# Bundled cache seed

Everything the app needs to show catalogues and title details **without calling any
provider** (TMDB, Watchmode, OMDb, IMDb, iTunes, NexStream). It ships inside the Docker
image so a fresh Render instance is fast from the first request.

## Layout

| Path | Contents |
|---|---|
| `*_catalogue.json` | Franchise / classics / latest catalogues (Marvel, DC, Bollywood, Hollywood, classics, TV). Rows already embed tmdbId, poster and overview. |
| `poster_map.json` | Title → poster URL lookups. |
| `regional_tv_prebuilt_cache.json` | Prebuilt regional TV pages. |
| `tmdb_ott_availability_cache.json` | OTT availability per title/region (`v2:<id>:<REGION>`). |
| `runtime/` | Files the app also *writes* at run time: TMDB catalogue pages, search metadata, regional movie pages, IMDb ratings, NexStream caches, TV caches. |

Run `python scripts/cache_report.py` for a per-file coverage table (rows, tmdbId, poster, overview).

## How it is used

1. On startup each seed file is copied into `APP_DATA_DIR` (default `/app/data`) **only if the
   destination does not already exist**; the OTT cache is merged. Anything the app learned at
   run time is therefore never overwritten by a redeploy.
2. With `CACHE_FIRST=true` (default) any stored entry — seed or runtime, any age — is served
   as-is. Providers are only asked for entries that do not exist. A user-triggered refresh
   (`force=true`, "clear TMDB cache") still bypasses this.
3. `CACHE_ONLY_MODE=true` (current Render setting) goes further: no provider calls at all.
4. `BACKFILL_MISSING_METADATA=false` additionally stops background gap-filling (synopsis / OTT).

| Env var | Default | Meaning |
|---|---|---|
| `CACHE_FIRST` | `true` | Serve stored data regardless of age. |
| `CACHE_ONLY_MODE` | `false` (`true` on Render) | Never call providers. |
| `BACKFILL_MISSING_METADATA` | `true` | Background enrichment of missing synopsis/OTT. |
| `APP_DATA_DIR` | `/app/data` | Runtime cache directory (point at a Render disk to keep it across deploys). |
| `CACHE_SEED_DIR` | `/app/cache-seed` | Where the seed is read from. |

## Known gaps

Three titles (43 rows) have no synopsis: *Doctor Strange: The Sorcerer Supreme*,
*Deathstroke: Knights & Dragons*, *The Raid: Redemption*. The Marvel movie catalogue only has
page 1 of an older variant. Both need a one-off refresh with real API keys
(`CACHE_ONLY_MODE=false`, `BACKFILL_MISSING_METADATA=true`), then commit the refreshed files.

## Tests

`backend/tests/test_cache_first.py` hits ~100 cached endpoints with all outbound HTTP blocked
and fails if any provider request is attempted.
