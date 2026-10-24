#!/usr/bin/env bash
# Run on the VPS (cron). Refreshes cache data, publishes ONE bundle to a rolling GitHub
# release (old asset replaced, so GitHub never accumulates history), then asks Render to restart.
#
#   refresh_and_publish.sh hollywood-bollywood     # weekly
#   refresh_and_publish.sh franchise               # when you want Marvel/DC/classics updated
#   refresh_and_publish.sh publish-only            # just re-publish the current working copy
#
# Config in ~/.config/torrent-studio/env (chmod 600):
#   TMDB_API_KEY=... TMDB_READ_ACCESS_TOKEN=... WATCHMODE_API_KEY=... OMDB_API_KEY=...
#   GH_TOKEN=<fine-grained token: Contents read/write on this repo>
#   RENDER_DEPLOY_HOOK=https://api.render.com/deploy/srv-...?key=...
set -euo pipefail
# Everything runs inside a function so that `git pull` replacing this file mid-run is harmless.
main() {
GROUP="${1:?usage: $0 hollywood-bollywood|franchise|tv-imdb|imdb-dataset|publish-only}"
REPO="wroxtaaar/Torrent-Studio"
HOME_DIR="${TS_HOME:-$HOME/torrent-studio-refresh}"
mkdir -p "$HOME_DIR"; cd "$HOME_DIR"
if [ ! -d repo/.git ]; then git clone --depth 1 "https://github.com/$REPO.git" repo; fi
# fetch + reset (not pull): a plain pull fails on a shallow clone with "Cannot fast-forward to multiple branches"
git -C repo fetch -q --depth 1 origin main
git -C repo reset -q --hard FETCH_HEAD
# Load keys (repeated TMDB_READ_ACCESS_TOKEN lines are all kept, not just the last one).
eval "$(python3 repo/scripts/vps/load_env.py "$HOME/.config/torrent-studio/env")"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q -r repo/backend/requirements.txt

# The working copy persists between runs so the weekly and manual refreshes both keep their results.
export REFRESH_SEED_DIR="$HOME_DIR/seed"
[ -d "$REFRESH_SEED_DIR" ] || cp -r repo/backend/cache-seed "$REFRESH_SEED_DIR"

if [ "$GROUP" != "publish-only" ]; then
  ./venv/bin/python repo/scripts/refresh_seed.py "$GROUP"
fi

rm -rf out; ./venv/bin/python repo/scripts/make_cache_bundle.py "$REFRESH_SEED_DIR" out

gh release view cache-data -R "$REPO" >/dev/null 2>&1 || \
  gh release create cache-data -R "$REPO" --title "Cache data (rolling)" \
    --notes "Rolling cache bundle published by the VPS. The assets are replaced on every refresh."
gh release upload cache-data out/cache-bundle.tar.gz out/cache-bundle.json -R "$REPO" --clobber

curl -fsS -X POST "$RENDER_DEPLOY_HOOK" >/dev/null && echo "Render deploy triggered"
}
main "$@"
exit $?
