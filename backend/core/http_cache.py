"""Moved out of main.py (see docs/main-split-plan.md)."""

import gzip
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import Response

from core.settings import _CACHE_SEED_DIR

# ---- Fast catalogue serving -------------------------------------------------
# Catalogue snapshots are several MB. Parse/normalise once per file version and
# keep the serialized (and gzipped) response so each page view is a memory copy.
_FILE_MEMO: dict[str, tuple[tuple[int, int], Any]] = {}
_RESPONSE_MEMO: dict[str, tuple[Any, bytes, bytes]] = {}


def _file_signature(path: Path) -> tuple[int, int]:
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0)


def _memoized_file_read(memo_key: str, path: Path, reader):
    sig = _file_signature(path)
    hit = _FILE_MEMO.get(memo_key)
    if hit and hit[0] == sig:
        return hit[1]
    value = reader()
    # The reader may rewrite the file after normalising; re-stat so we cache the final version.
    _FILE_MEMO[memo_key] = (_file_signature(path), value)
    return value


def _fast_json_response(request: Request, memo_key: str, signature: Any, build) -> Response:
    entry = _RESPONSE_MEMO.get(memo_key)
    if entry is None or entry[0] != signature:
        raw = json.dumps(build(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        entry = (signature, raw, gzip.compress(raw, compresslevel=6))
        _RESPONSE_MEMO[memo_key] = entry
    headers = {"Cache-Control": "public, max-age=300", "Vary": "Accept-Encoding"}
    if "gzip" in (request.headers.get("accept-encoding") or "").casefold():
        headers["Content-Encoding"] = "gzip"
        return Response(entry[2], media_type="application/json", headers=headers)
    return Response(entry[1], media_type="application/json", headers=headers)


def _catalogue_group_key(item: dict[str, Any], index: int = 0) -> str:
    title = re.sub(r"[^a-z0-9]+", "", str(
        item.get("catalogueTitle") or item.get("marvelCatalogueTitle")
        or item.get("mediaTitle") or item.get("title") or ""
    ).casefold())
    if title:
        return title
    # Preserve grouping for rows that lack titles but carry a stable media/release ID.
    for field in ("tmdbId", "tmdb_id", "movieId", "movie_id", "imdbId", "imdb_id",
                  "infoHash", "info_hash", "magnet", "id"):
        value = str(item.get(field) or "").strip().casefold()
        if value:
            return field + ":" + value
    # Avoid treating all malformed/untitled rows as the same movie.
    return "__untitled_row_" + str(index)


def _page_catalogue_payload(
    payload: dict[str, Any],
    page: int,
    page_size: int,
    sort_by_release_date: bool = False,
) -> dict[str, Any]:
    """Slice a catalogue by movie (all torrent rows of a title stay together)."""
    if page <= 0 or page_size <= 0:
        return payload
    groups: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(payload["results"]):
        groups.setdefault(_catalogue_group_key(row, index), []).append(row)
    keys = list(groups)
    if sort_by_release_date:
        def sort_key(key: str) -> tuple[int, str]:
            rows = groups[key]
            movie = next((row for row in rows if row.get("releaseDate") or row.get("release_date")), rows[0])
            raw_date = str(movie.get("releaseDate") or movie.get("release_date") or "").strip()
            try:
                release_date = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
            except (TypeError, ValueError):
                year_match = re.search(r"\b((?:19|20)\d{2})\b", raw_date)
                try:
                    year = int(movie.get("year") or (year_match.group(1) if year_match else 0))
                except (TypeError, ValueError):
                    year = 0
                release_date = date(year, 1, 1) if 1 <= year <= 9999 else date.min
            title = str(
                movie.get("catalogueTitle") or movie.get("marvelCatalogueTitle")
                or movie.get("mediaTitle") or movie.get("title") or ""
            )
            normalized_title = re.sub(r"[^a-z0-9]+", "", title.casefold())
            return -release_date.toordinal(), normalized_title

        keys.sort(key=sort_key)
    total_pages = max(1, -(-len(keys) // page_size))
    start = (page - 1) * page_size
    rows = [row for key in keys[start:start + page_size] for row in groups[key]]
    return {**payload, "results": rows, "page": page, "pageSize": page_size,
            "totalPages": total_pages, "totalMovies": len(keys)}


_PREBUILT_PAGE_SIZE = 18
_PREBUILT_PAGE_MEMO: dict[str, bytes] = {}
_DATE_SORTED_EXTRA_CATALOGUES = {
    "dc-live-action",
    "dc-live-action-hindi",
    "dc-animated",
    "classics",
}


def _prebuilt_catalogue_page(request: Request, key: str, page: int, page_size: int) -> Response | None:
    """Serve a build-time pre-split catalogue page without parsing the big file."""
    if page <= 0 or page_size != _PREBUILT_PAGE_SIZE:
        return None
    memo_key = f"{key}:{page}"
    blob = _PREBUILT_PAGE_MEMO.get(memo_key)
    if blob is None:
        try:
            blob = (_CACHE_SEED_DIR / "pages" / key / f"{page}.json.gz").read_bytes()
        except OSError:
            return None
        _PREBUILT_PAGE_MEMO[memo_key] = blob
    headers = {"Cache-Control": "public, max-age=300", "Vary": "Accept-Encoding"}
    if "gzip" in (request.headers.get("accept-encoding") or "").casefold():
        headers["Content-Encoding"] = "gzip"
        return Response(blob, media_type="application/json", headers=headers)
    return Response(gzip.decompress(blob), media_type="application/json", headers=headers)
