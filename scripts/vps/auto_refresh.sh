#!/usr/bin/env bash
# Scheduled refresh of the Hollywood + Bollywood Popular / Trending / Latest catalogues.
# Rebuilds them, publishes the cache bundle (Render is redeployed by refresh_and_publish.sh),
# then restarts the VPS container so it loads the new bundle at start-up.
#
#   scripts/vps/auto_refresh.sh daily    # quick (scheduled Wednesdays): catalogue pages only, no torrent searches
#   scripts/vps/auto_refresh.sh weekly   # full, scheduled Sundays 3:30 am IST: also searches torrents for new titles
#   scripts/vps/auto_refresh.sh install  # add the weekly job to this user's crontab (safe to repeat)
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
    TMP="$(mktemp)"
    crontab -l 2>/dev/null | grep -v 'auto_refresh.sh' > "$TMP" || true
    {
      echo "CRON_TZ=Asia/Kolkata"
      echo "30 3 * * 0  bash $SELF weekly >> $LOG_DIR/auto-refresh.log 2>&1   # auto_refresh.sh"
    } >> "$TMP"
    crontab "$TMP"; rm -f "$TMP"
    echo "Installed. Current crontab:"; crontab -l; exit 0 ;;
  daily)  export REGIONAL_CACHE_TORRENT_SCAN=false ;;
  weekly) export REGIONAL_CACHE_TORRENT_SCAN=true ;;
  *) echo "Usage: $0 daily|weekly|install" >&2; exit 2 ;;
esac

exec 9>"${XDG_RUNTIME_DIR:-/tmp}/torrent-studio-auto-refresh.lock"
flock -n 9 || { echo "$(date -Is) another refresh is running; skipping"; exit 0; }

echo "$(date -Is) ===== $MODE refresh start"
bash "$(dirname "$SELF")/refresh_and_publish.sh" hollywood-bollywood
echo "$(date -Is) published; restarting $CONTAINER"
docker restart "$CONTAINER" >/dev/null
echo "$(date -Is) ===== $MODE refresh done"
