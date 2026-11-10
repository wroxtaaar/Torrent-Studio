#!/usr/bin/env bash
# Scheduled refresh of the Hollywood + Bollywood Popular / Trending / Latest catalogues.
# Rebuilds them, publishes the cache bundle (Render is redeployed by refresh_and_publish.sh),
# then restarts the VPS container so it loads the new bundle at start-up.
#
#   scripts/vps/auto_refresh.sh daily    # quick (scheduled Wednesdays): catalogue pages only, no torrent searches
#   scripts/vps/auto_refresh.sh weekly   # scheduled Sundays: catalogue lists only, no torrent searches (fast)
#   scripts/vps/auto_refresh.sh full     # same plus a torrent search for every title (slow, manual)
#   scripts/vps/auto_refresh.sh install  # remove old cron entries (Actions schedules it now)
#
# Logs: ~/torrent-studio-refresh/logs/auto-refresh.log
set -euo pipefail
MODE="${1:-}"
HOME_DIR="${TS_HOME:-$HOME/torrent-studio-refresh}"
SELF="$(readlink -f "$0")"
CONTAINER="${TS_CONTAINER:-torrent-studio}"
LOG_DIR="$HOME_DIR/logs"; mkdir -p "$LOG_DIR"

case "$MODE" in
  install)
    # The schedule now lives in .github/workflows/refresh-cache.yml; this only removes old cron entries.
    TMP="$(mktemp)"; crontab -l 2>/dev/null | grep -v 'auto_refresh.sh' > "$TMP" || true
    crontab "$TMP"; rm -f "$TMP"; echo "Old cron entries removed (GitHub Actions runs the weekly refresh)."; exit 0 ;;
  daily)  export REGIONAL_CACHE_TORRENT_SCAN=false ;;
  weekly) export REGIONAL_CACHE_TORRENT_SCAN=false ;;   # catalogue lists only: minutes, not hours
  full)   export REGIONAL_CACHE_TORRENT_SCAN=true ;;    # also searches torrents for every title (slow)
  *) echo "Usage: $0 daily|weekly|full|install" >&2; exit 2 ;;
esac

exec 9>"${XDG_RUNTIME_DIR:-/tmp}/torrent-studio-auto-refresh.lock"
flock -n 9 || { echo "$(date -Is) another refresh is running; skipping"; exit 0; }

# Only Hollywood, Bollywood and Anime movies change weekly (TMDB). Everything else is fixed and not touched.
export REFRESH_SCOPE=weekly
export REGIONAL_CACHE_ALLOW_PARTIAL=true   # one failed page must not stop the whole refresh from publishing
export TS_FORCE_TORRENT_SCAN="$REGIONAL_CACHE_TORRENT_SCAN"
export REGIONAL_CACHE_CATALOGUES="popular-hollywood,trending-hollywood,latest-hollywood,popular-bollywood,trending-bollywood,latest-bollywood,popular-anime"
export TS_FORCE_CATALOGUES="$REGIONAL_CACHE_CATALOGUES"
echo "$(date -Is) ===== $MODE refresh start"
D="$(dirname "$SELF")"
# 1) refresh the source catalogues (and publish once), 2) merge them into the section files the app
# serves (hollywood.json / bollywood.json), 3) publish again so the new lists go live.
bash "$D/refresh_and_publish.sh" hollywood-bollywood
SKIP_NEW_SOURCES=1 HOME_API_BASE="${HOME_API_BASE:-http://127.0.0.1:3000}" bash "$D/build_section_caches.sh"
# Torrent options only for titles that have none yet (the app is still up on the old data; the scan only needs /api/search).
export REFRESH_SEED_DIR="$HOME_DIR/seed"
"$HOME_DIR/venv/bin/python" "$D/../scan_missing_torrents.py" --sections hollywood,bollywood,anime || echo "torrent scan failed; continuing"
bash "$D/refresh_and_publish.sh" publish-only
echo "$(date -Is) published; restarting $CONTAINER"
docker restart "$CONTAINER" >/dev/null
echo "$(date -Is) ===== $MODE refresh done"
