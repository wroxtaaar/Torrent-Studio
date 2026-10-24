#!/usr/bin/env python3
"""Fill IMDb ratings from IMDb's free daily dataset -- no OMDb key, no daily request limit.

IMDb publishes title.ratings.tsv.gz (rating + votes for every title, keyed by IMDb id) at
https://datasets.imdbws.com/ . The files are free for PERSONAL, NON-COMMERCIAL use only
(see https://developer.imdb.com/non-commercial-datasets/). Each catalogue title's IMDb id comes from
TMDB (external_ids), so the match is exact. Titles that already have a rating are left alone;
titles the dataset has no rating for are skipped (nothing is stored for them).

Run from scripts/refresh_seed.py; set IMDB_DATASET_DIR to choose where the download is kept.
"""
from __future__ import annotations

import asyncio
import csv
import gzip
import json
import os
import sys
import time
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import settings  # noqa: E402
from metadata import imdb, tmdb  # noqa: E402

URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
WORK = Path(os.getenv("IMDB_DATASET_DIR") or Path.home() / ".cache" / "imdb-datasets")
DATASET = WORK / "title.ratings.tsv.gz"
ID_MAP = WORK / "tmdb_to_imdb.json"

TV_FILES = ("regional_tv_prebuilt_cache.json", "marvel_tv_catalogue_cache.json", "dc_tv_catalogue_cache.json",
            "marvel_web_series_catalogue.json", "classics_anime_tv_catalogue.json", "classics_web_series_tv_catalogue.json")
MOVIE_FILES = ("marvel_catalogue.json", "marvel_hindi_catalogue.json", "dc_live_action_catalogue.json",
               "dc_live_action_hindi_catalogue.json", "dc_animated_catalogue.json", "classics_catalogue.json",
               "bollywood_torrent_matched_catalogue.json", "latest_bollywood_catalogue.json", "latest_hollywood_catalogue.json")


def ensure_dataset() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    if DATASET.is_file() and time.time() - DATASET.stat().st_mtime < 20 * 3600:
        return
    print("Downloading IMDb ratings dataset ...", flush=True)
    request = urllib.request.Request(URL, headers={"User-Agent": "torrent-studio-imdb-dataset/1"})
    tmp = DATASET.with_suffix(".tmp")
    with urllib.request.urlopen(request, timeout=120) as response, open(tmp, "wb") as out:
        while chunk := response.read(1 << 20):
            out.write(chunk)
    os.replace(tmp, DATASET)


def load_ratings(wanted: set[str]) -> dict[str, tuple[float, int]]:
    found: dict[str, tuple[float, int]] = {}
    with gzip.open(DATASET, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        next(reader, None)
        for row in reader:
            if len(row) >= 3 and row[0] in wanted:
                try:
                    found[row[0]] = (float(row[1]), int(row[2]))
                except ValueError:
                    pass
    return found


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def year_of(row: dict[str, Any]) -> int:
    year = as_int(row.get("year"))
    if not year:
        year = as_int(str(row.get("releaseDate") or row.get("first_air_date") or "")[:4])
    return year


def targets() -> dict[tuple[str, str, int], int]:
    """(media type, title, year) -> TMDB id, for every title the site can show."""
    found: dict[tuple[str, str, int], int] = {}

    def add(media: str, title: Any, year: int, tmdb_id: Any) -> None:
        title, tid = str(title or "").strip(), as_int(tmdb_id)
        if title and tid > 0:
            found.setdefault((media, title, year), tid)

    def walk_tv(node: Any) -> None:
        if isinstance(node, dict):
            if (node.get("title") or node.get("name")) and (node.get("tmdbId") or node.get("id")) \
                    and (node.get("posterUrl") or node.get("overview") or node.get("year")):
                add("tv", node.get("title") or node.get("name"), year_of(node), node.get("tmdbId") or node.get("id"))
            for value in node.values():
                walk_tv(value)
        elif isinstance(node, list):
            for value in node:
                walk_tv(value)

    def read(name: str) -> Any:
        for folder in (settings.DATA_DIR, settings.DATA_DIR / "runtime"):
            path = folder / name
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        return None

    for name in TV_FILES:
        walk_tv(read(name))
    for name in MOVIE_FILES:
        for row in (read(name) or {}).get("results", []) if isinstance(read(name), dict) else []:
            if isinstance(row, dict):
                title = row.get("catalogueTitle") or row.get("marvelCatalogueTitle") or row.get("mediaTitle") or row.get("title")
                add("movie", title, year_of(row), row.get("tmdbId") or row.get("id"))
    regional = read("regional_movie_prebuilt_cache.json")
    if isinstance(regional, dict):
        for entry in (regional.get("movies") or {}).values():
            movie = entry.get("movie") if isinstance(entry, dict) else None
            if isinstance(movie, dict):
                add("movie", movie.get("title"), year_of(movie), movie.get("tmdbId") or movie.get("id"))
        for body in (regional.get("catalogues") or {}).values():
            for movie in (body or {}).get("final", []):
                if isinstance(movie, dict):
                    add("movie", movie.get("title"), year_of(movie), movie.get("tmdbId") or movie.get("id"))
    meta = read("tmdb_search_metadata_cache.json")
    for row in (meta or {}).get("results", []) if isinstance(meta, dict) else []:
        if isinstance(row, dict):
            add("tv" if row.get("mediaType") == "tv" else "movie", row.get("title"), year_of(row), row.get("tmdbId") or row.get("id"))
    return found


async def imdb_id_for(media: str, tmdb_id: int, memo: dict[str, str]) -> str:
    key = f"{media}:{tmdb_id}"
    if key in memo:
        return memo[key]
    try:
        details = await tmdb._tmdb_get_json(f"{media}/{tmdb_id}/external_ids", {}, request_timeout=10.0)
    except Exception as exc:  # network / rate limit: try again on the next run
        print(f"  TMDB lookup failed for {key}: {type(exc).__name__}", flush=True)
        return ""
    imdb_id = str(details.get("imdb_id") or "").strip()
    memo[key] = imdb_id if imdb_id.startswith("tt") else ""
    return memo[key]


CINEMETA = "https://v3-cinemeta.strem.io"


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


async def cinemeta_lookup(media: str, title: str, year: int, imdb_id: str) -> tuple[float, str] | None:
    """Fallback for titles the dataset has no rating for: Stremio's Cinemeta metadata (IMDb ratings)."""
    import httpx
    kind = "series" if media == "tv" else "movie"
    headers = {"User-Agent": "torrent-studio-imdb-fallback/1"}
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True) as client:
            if not imdb_id:
                response = await client.get(f"{CINEMETA}/catalog/{kind}/top/search={urllib.parse.quote(title)}.json")
                if response.status_code != 200:
                    return None
                for meta in response.json().get("metas", []):
                    meta_year = as_int(str(meta.get("year") or meta.get("releaseInfo") or "")[:4])
                    if _norm(meta.get("name")) == _norm(title) and (not year or not meta_year or meta_year == year):
                        imdb_id = str(meta.get("imdb_id") or meta.get("id") or "")
                        if meta.get("imdbRating"):
                            return float(meta["imdbRating"]), imdb_id
                        break
                if not imdb_id.startswith("tt"):
                    return None
            response = await client.get(f"{CINEMETA}/meta/{kind}/{imdb_id}.json")
            if response.status_code != 200:
                return None
            rating = (response.json().get("meta") or {}).get("imdbRating")
            return (float(rating), imdb_id) if rating else None
    except (httpx.HTTPError, ValueError, TypeError):
        return None


async def main() -> None:
    cache = imdb._load_imdb_rating_cache()
    wanted = targets()
    todo = {}
    for (media, title, year), tmdb_id in wanted.items():
        record = cache.get(imdb._imdb_rating_cache_key(title, year, media))
        if not (record and record.get("status") == "found" and record.get("imdbRating") is not None):
            todo[(media, title, year)] = tmdb_id
    print(f"Titles: {len(wanted)}, without an IMDb rating yet: {len(todo)}", flush=True)
    if not todo:
        return

    ensure_dataset()
    memo: dict[str, str] = {}
    if ID_MAP.is_file():
        memo = json.loads(ID_MAP.read_text(encoding="utf-8"))
    semaphore = asyncio.Semaphore(6)

    async def resolve(item: tuple[tuple[str, str, int], int]) -> tuple[tuple[str, str, int], int, str]:
        (media, title, year), tmdb_id = item
        async with semaphore:
            return (media, title, year), tmdb_id, await imdb_id_for(media, tmdb_id, memo)

    resolved = await asyncio.gather(*(resolve(item) for item in todo.items()))
    WORK.mkdir(parents=True, exist_ok=True)
    ID_MAP.write_text(json.dumps(memo), encoding="utf-8")
    ratings = load_ratings({imdb_id for _, _, imdb_id in resolved if imdb_id})

    now = int(time.time())
    added = no_id = no_rating = from_cinemeta = 0
    leftovers: list[tuple[str, str, int, int, str]] = []
    for (media, title, year), tmdb_id, imdb_id in resolved:
        rating = ratings.get(imdb_id) if imdb_id else None
        if rating is None:
            leftovers.append((media, title, year, tmdb_id, imdb_id))
            continue
        key = imdb._imdb_rating_cache_key(title, year, media)
        cache[key] = {
            "cacheKey": key, "title": title, "year": year or None, "mediaType": media, "checkedAt": now,
            "lookupVersion": settings.IMDB_RATING_LOOKUP_VERSION, "tmdbIdTried": tmdb_id,
            "status": "found", "imdbRating": rating[0], "imdbVotes": f"{rating[1]:,}",
            "imdbId": imdb_id, "imdbUrl": f"https://www.imdb.com/title/{imdb_id}/",
            "ratingLookupSource": "imdb_dataset",
        }
        added += 1

    # Anything still without a rating (very new, or no IMDb id on TMDB): ask Cinemeta.
    gate = asyncio.Semaphore(5)

    async def fallback(item: tuple[str, str, int, int, str]):
        async with gate:
            return item, await cinemeta_lookup(item[0], item[1], item[2], item[4])

    for (media, title, year, tmdb_id, imdb_id), found in await asyncio.gather(*(fallback(i) for i in leftovers)):
        if found is None:
            no_id += 0 if imdb_id else 1
            no_rating += 1 if imdb_id else 0
            continue
        rating_value, found_id = found
        key = imdb._imdb_rating_cache_key(title, year, media)
        cache[key] = {
            "cacheKey": key, "title": title, "year": year or None, "mediaType": media, "checkedAt": now,
            "lookupVersion": settings.IMDB_RATING_LOOKUP_VERSION, "tmdbIdTried": tmdb_id,
            "status": "found", "imdbRating": rating_value, "imdbVotes": None,
            "imdbId": found_id if found_id.startswith("tt") else None,
            "imdbUrl": f"https://www.imdb.com/title/{found_id}/" if found_id.startswith("tt") else None,
            "ratingLookupSource": "cinemeta",
        }
        from_cinemeta += 1
    imdb._write_synopsis_cache(imdb.IMDB_RATING_CACHE_FILE, {
        "version": 1, "updatedAt": now, "results": list(cache.values())[-20000:]})
    print(f"IMDb dataset: ratings added {added}, from Cinemeta {from_cinemeta}, "
          f"still without a rating {no_id + no_rating}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
