# Torrent Studio

A self-hostable movie and series discovery app built to run as **one Docker web service on Render**.

▶️ **[Try the live app](https://torrent-studio-e5v2.onrender.com)**

## What it does

- Browse curated movies, TV series, anime, and regional catalogues.
- Discover posters, synopses, ratings, and streaming information when available.
- Find titles and use torrent/Seedr features to prepare transfers and manage files through your personal Seedr account.
- Use bundled catalogue data to reduce unnecessary live metadata requests.

Torrent availability and provider features depend on the configured services and available results. Use the app only with content you have the right to access.

## Run your own instance on Render

1. Fork this repository.
2. Create a **Web Service** in Render, connect your fork, and select **Docker**.
3. Add `SEEDR_SESSION_SECRET` as an environment variable, then deploy.

Generate a secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Optional integrations can use `TMDB_READ_ACCESS_TOKEN` / `TMDB_API_KEY`, `WATCHMODE_API_KEY`, `OMDB_API_KEY`, and `NEXSTREAM_API_KEY`. Add credentials in Render's environment settings—never commit secrets.

## Run locally with Docker

Requirements: Docker and the Docker Compose plugin.

```bash
git clone https://github.com/wroxtaaar/Torrent-Studio.git
cd Torrent-Studio
cp .env.example .env
```

Set `SEEDR_SESSION_SECRET` in `.env`, then run:

```bash
docker compose up --build -d
```

Open [http://localhost:10000](http://localhost:10000). Health check: [http://localhost:10000/api/health](http://localhost:10000/api/health).

### Webtor torrent streaming experiment

Torrent-result cards include **Test Webtor**, which embeds the official [Webtor Embed SDK](https://github.com/webtor-io/embed-sdk-js) using the hosted `https://webtor.io` service. Choose **Play** to open its embedded video mode or **Download** to open the SDK's embedded download mode. Select a file in that interface to start its download. Webtor retrieves the torrent and serves media/download bytes directly to the browser; Torrent Studio does not proxy media data. **Copy magnet** remains available as a fallback. No Webtor credentials or additional service are required.

The optional [self-hosted Webtor image](https://github.com/webtor-io/self-hosted) can also be integrated with the SDK's `baseUrl`, but it must be deployed and secured separately. When hosted on the same VPS, torrent traffic and file delivery use that VPS and do not provide the bandwidth savings of the hosted service.

## Tech stack

React + Vite · FastAPI · Docker · Render

The frontend and backend run in one service, and bundled catalogue snapshots help reduce repeated requests. Actual resource usage depends on traffic, cache size, integrations, and the Render instance.

## Backend layout

`backend/main.py` only assembles the FastAPI app (middleware, error handler, startup/shutdown hooks and router includes); `backend/fullstack_app.py` adds the frontend on top of it. The code lives in packages next to them:

| Package | Modules |
| --- | --- |
| `core/` | `settings` (all configuration), `shared` (request context, `SeedrError`), `http_cache`, `cache_diagnostics` |
| `seedr/` | `seedr_session` (cookie session, CSRF), `seedr_client` (low-level Seedr API), `seedr_api` (all `/api/seedr/*` routes) |
| `metadata/` | `tmdb` (TMDB/Watchmode/OMDb clients and caches), `imdb`, `posters`, `search_metadata` |
| `search/` | `search_providers` (1337x, YTS, EZTV, ...), `torrent_metadata` (.torrent / magnet inspection) |
| `catalogues/` | `catalogues_extra` (Marvel/extra, synopsis enrichment), `catalogues_tv`, `catalogues_movies` |
| `routes/` | `feedback`, `compat_routes` (qBittorrent-style stubs), `misc_routes` (health, cache report, ...) |
| `integrations/` | `nexstream` |
| `maintenance/` | one-off scripts run with `docker exec` (cache refresh, ID resolution) |

Route registration order matters in FastAPI, so it is pinned by `backend/tests/test_app_structure.py`. History of the split: [docs/main-split-plan.md](docs/main-split-plan.md).

## Notes

- Personal Seedr use requires a session secret; follow Seedr's terms and authorization flow.
- Render's default filesystem may not persist across replacements. Use persistent storage or a cache-sync workflow for data that must survive.
- Third-party providers have their own terms, quotas, and attribution requirements.
- **License:** No license file is included yet; add one before inviting reuse or redistribution.

Issues and contributions are welcome. Please never commit API keys, session secrets, or private configuration.
