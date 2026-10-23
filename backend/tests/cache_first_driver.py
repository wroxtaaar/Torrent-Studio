"""Run in a fresh interpreter by test_cache_first.py.

Starts the real app with live-provider mode ON (fake API keys, CACHE_ONLY_MODE=false) but with
the bundled cache installed and every outbound HTTP request blocked and recorded. Whatever the
app asks for that is already cached must not reach the network.
"""
import json
import sys
import time
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
calls: list[list[str]] = []
current = ["startup"]


async def _blocked_async(self, request, *args, **kwargs):
    calls.append([current[0], request.method, str(request.url)[:160]])
    raise httpx.ConnectError("blocked: outbound HTTP is not allowed in this test", request=request)


def _blocked_sync(self, request, *args, **kwargs):
    calls.append([current[0], request.method, str(request.url)[:160]])
    raise httpx.ConnectError("blocked: outbound HTTP is not allowed in this test", request=request)


httpx.AsyncClient.send = _blocked_async
httpx.Client.send = _blocked_sync

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from core import settings  # noqa: E402

assert settings.CACHE_FIRST and not settings.CACHE_ONLY_MODE, "driver needs live mode + cache-first"
seed = settings._CACHE_SEED_DIR
ott_ids = sorted({k.replace("v2:", "").split(":")[0]
                  for k in json.loads((seed / "runtime" / "tmdb_ott_availability_cache.json").read_text())["items"]})[:25]
imdb_rows = json.loads((seed / "runtime" / "imdb_rating_cache.json").read_text())["results"]
imdb_titles = [f"{r['title']} ({r['year']})" for r in imdb_rows if r.get("status") == "found" and r.get("year")][:20]
posters = json.loads((seed / "poster_map.json").read_text())[:20]

paths: list[str] = []
for kind in ("popular", "trending", "latest"):
    for region in ("bollywood", "hollywood"):
        for page in (1, 2, 3):
            paths.append(f"/api/movies/catalogue/{kind}-{region}?page={page}")
for key in ("marvel", "dc-live-action", "dc-animated"):
    paths.append(f"/api/movies/catalogue/{key}?page=1")
for key in main._EXTRA_CATALOGUES:
    paths.append(f"/api/catalogue/extra/{key}?page=1&page_size=18")
paths += ["/api/catalogue/marvel?page=1&page_size=18", "/api/regional-movies/prebuilt"]
for key in ("indian-popular", "indian-trending", "indian-latest", "hollywood-popular",
            "hollywood-trending", "hollywood-latest", "marvel", "dc-live-action",
            "classics-web-series", "classics-anime"):
    paths.append(f"/api/tv/catalogue/{key}")
paths += [f"/api/movies/ott/{movie_id}?region=IN" for movie_id in ott_ids]
from urllib.parse import quote  # noqa: E402
paths.append("/api/catalogue/imdb-ratings?" + "&".join("titles=" + quote(t) for t in imdb_titles))
paths += [f"/api/poster/resolve?title={quote(t)}&year={y}" for t, y, _url in posters]

statuses: dict[str, int] = {}
errors: dict[str, str] = {}
with TestClient(main.app, raise_server_exceptions=False) as client:
    time.sleep(1)
    for path in paths:
        current[0] = path.split("?")[0] + ("?" + path.split("?")[1][:40] if "?" in path else "")
        try:
            statuses[path] = client.get(path).status_code
        except Exception as exc:  # a crashing endpoint is reported, not fatal
            statuses[path] = 599
            errors[path] = f"{type(exc).__name__}: {str(exc)[:200]}"
    # Give background tasks started by the requests a moment to run.
    time.sleep(3)
print("RESULT=" + json.dumps({"calls": calls, "statuses": statuses, "errors": errors}))
