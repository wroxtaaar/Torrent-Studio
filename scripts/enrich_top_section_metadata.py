#!/usr/bin/env python3
"""Metadata-only enrichment for the nine top-level section seed JSON files.

Preserves section membership/order. Reads shared IMDb/OTT caches, calls only
TMDB metadata and IMDb metadata endpoints, and writes only <section>.json files.
Never reads/writes paired *-torrents.json files or calls torrent search routes.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from metadata.imdb import _imdb_rating_cache_key  # noqa: E402

HOME = Path(os.getenv("TS_HOME") or Path.home() / "torrent-studio-refresh")
SEED = Path(os.getenv("REFRESH_SEED_DIR") or HOME / "seed").resolve()
API = os.getenv("HOME_API_BASE", "http://127.0.0.1:10000").rstrip("/")
REGION = os.getenv("OTT_REGION", "IN").upper()
SECTIONS = (
    "hollywood", "bollywood", "marvel", "dc", "highest-rated",
    "korean", "pakistani", "anime", "favourites",
)
TV_SUBSECTIONS = {
    ("marvel", "series"), ("dc", "series"), ("highest-rated", "tv"),
    ("korean", "series"), ("pakistani", "series"), ("anime", "series"),
    ("favourites", "series"), ("favourites", "anime"),
}
TORRENT_KEYS = {
    "torrent", "torrents", "torrentdetails", "torrentmatch", "torrentmatches",
    "cachedtorrentdetails", "torrentreleases", "torrentresults", "magnet",
    "magneturl", "infohash", "hash", "downloadurl", "seeders", "leechers",
    "nexstream", "episodes",
}
VALID_IMDB = re.compile(r"^tt\d+$")


def log(event: str, **data: Any) -> None:
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def request_json(url: str, timeout: int = 60) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "TorrentStudio-SectionMetadataRefresh/1.0",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("API returned a non-object JSON response")
    return value


def valid_id(value: Any) -> int:
    try:
        n = int(value)
        return n if n > 0 else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def image_url(value: Any, size: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    # Strip repeated TMDB size prefixes, including malformed /w500/w780/... paths.
    if "image.tmdb.org/t/p/" in raw:
        tail = raw.split("/t/p/", 1)[1]
        parts = tail.split("/")
        while parts and re.fullmatch(r"w\d+|original", parts[0]):
            parts.pop(0)
        filename = "/".join(parts).lstrip("/")
        return f"https://image.tmdb.org/t/p/{size}/{filename}" if filename else ""
    if raw.startswith("/"):
        raw = raw.lstrip("/")
        while re.match(r"^(?:w\d+|original)/", raw):
            raw = raw.split("/", 1)[1]
        return f"https://image.tmdb.org/t/p/{size}/{raw}" if raw else ""
    return raw


def media_type(section: str, subsection: str, node: dict[str, Any]) -> str:
    if node.get("mediaType") in {"tv", "series"} or (section, subsection) in TV_SUBSECTIONS:
        return "tv"
    return "movie"


def cache_key_for(row: dict[str, Any], kind: str) -> str:
    title = str(row.get("title") or row.get("name") or "").strip()
    raw_year = row.get("year") or row.get("releaseDate") or row.get("firstAirDate") or ""
    match = re.match(r"^(\d{4})", str(raw_year))
    year = int(match.group(1)) if match else 0
    return _imdb_rating_cache_key(title, year, kind) if title else ""


def apply_imdb(row: dict[str, Any], record: dict[str, Any]) -> int:
    changed = 0
    imdb_id = str(record.get("imdbId") or "").strip()
    if VALID_IMDB.fullmatch(imdb_id) and not VALID_IMDB.fullmatch(str(row.get("imdbId") or "")):
        row["imdbId"] = imdb_id
        changed += 1
    rating = record.get("imdbRating")
    try:
        rating = float(rating)
    except (TypeError, ValueError):
        rating = 0
    if 0 < rating <= 10 and not row.get("imdbRating"):
        row["imdbRating"] = rating
        changed += 1
    for source, target in (("imdbVotes", "imdbVotes"), ("imdbUrl", "imdbUrl")):
        if empty(row.get(target)) and not empty(record.get(source)):
            row[target] = record[source]
            changed += 1
    if record.get("checkedAt") and not row.get("imdbCheckedAt"):
        row["imdbCheckedAt"] = record["checkedAt"]
        changed += 1
    if record.get("status"):
        row["imdbRatingStatus"] = record["status"]
    return changed


def movie_ott(ott_items: dict[str, Any], tmdb_id: int) -> dict[str, Any] | None:
    for key in (f"v2:{tmdb_id}:{REGION}", f"{tmdb_id}:{REGION}"):
        envelope = ott_items.get(key)
        payload = envelope.get("payload") if isinstance(envelope, dict) else None
        if isinstance(payload, dict):
            return payload
    return None


def metadata_url(kind: str, tmdb_id: int) -> str:
    prefix = "/api/tv/tmdb-metadata/" if kind == "tv" else "/api/movies/tmdb-metadata/"
    return API + prefix + str(tmdb_id)


def enrich_imdb_batches(rows: list[tuple[dict[str, Any], str, int]], cache: dict[str, dict[str, Any]]) -> int:
    pending = []
    for row, kind, tmdb_id in rows:
        key = cache_key_for(row, kind)
        cached = cache.get(key)
        if cached and cached.get("status") == "found":
            apply_imdb(row, cached)
        if not (VALID_IMDB.fullmatch(str(row.get("imdbId") or "")) and row.get("imdbRating")):
            title = str(row.get("title") or row.get("name") or "").strip()
            raw_year = row.get("year") or row.get("releaseDate") or row.get("firstAirDate") or ""
            match = re.match(r"^(\d{4})", str(raw_year))
            year = match.group(1) if match else ""
            query = f"{title} ({year})" if year else title
            if title:
                pending.append((row, kind, tmdb_id, query))
    fetched = 0
    for start in range(0, len(pending), 80):
        batch = pending[start:start + 80]
        params = [("persist", "false"), ("refresh_incomplete", "true")]
        for row, kind, tmdb_id, query in batch:
            params.extend([
                ("titles", query), ("media_types", kind), ("tmdb_ids", str(tmdb_id)),
            ])
        url = API + "/api/catalogue/imdb-ratings?" + urllib.parse.urlencode(params)
        try:
            payload = request_json(url, timeout=180)
        except Exception as exc:
            log("imdb_batch_failed", batch=start // 80 + 1, count=len(batch), error=str(exc))
            continue
        by_query = {str(item.get("query") or "").casefold(): item
                    for item in payload.get("results", []) if isinstance(item, dict)}
        for row, kind, tmdb_id, query in batch:
            result = by_query.get(query.casefold())
            if not result:
                continue
            # A TMDB identity mismatch must never overwrite the curated row.
            returned = valid_id(result.get("tmdbIdTried"))
            if returned and tmdb_id and returned != tmdb_id:
                continue
            fetched += apply_imdb(row, result)
            cache_key = cache_key_for(row, kind)
            if cache_key:
                cache[cache_key] = result
        log("imdb_batch_complete", batch=start // 80 + 1, requested=len(batch),
            matched=int(payload.get("matched") or 0))
        time.sleep(0.2)
    return fetched


def main() -> int:
    if not SEED.is_dir():
        raise SystemExit(f"Seed directory not found: {SEED}")
    health = request_json(API + "/api/health", timeout=10)
    if not health:
        raise SystemExit("Application API health check failed")

    imdb_doc = read_json(SEED / "runtime" / "imdb_rating_cache.json", {})
    imdb_rows = imdb_doc.get("results", []) if isinstance(imdb_doc, dict) else []
    imdb_cache = {
        str(item.get("cacheKey")): item for item in imdb_rows
        if isinstance(item, dict) and item.get("cacheKey")
    }
    ott_doc = read_json(SEED / "runtime" / "tmdb_ott_availability_cache.json", {})
    ott_items = ott_doc.get("items", {}) if isinstance(ott_doc, dict) else {}
    if not isinstance(ott_items, dict):
        ott_items = {}

    totals = {"sections": 0, "records": 0, "tmdbLookups": 0,
              "metadataFieldsFilled": 0, "imdbFieldsFilled": 0, "ottCacheHits": 0}
    for section in SECTIONS:
        path = SEED / f"{section}.json"
        doc = read_json(path)
        if not isinstance(doc, dict) or not isinstance(doc.get("subsections"), dict):
            log("section_skipped", section=section, reason="missing_or_invalid_section_json")
            continue
        pending_imdb: list[tuple[dict[str, Any], str, int]] = []
        section_counts = {"records": 0, "tmdbLookups": 0, "metadataFieldsFilled": 0,
                          "imdbFieldsFilled": 0, "ottCacheHits": 0}
        for subsection, node in doc["subsections"].items():
            if not isinstance(node, dict) or not isinstance(node.get("results"), list):
                continue
            kind = media_type(section, subsection, node)
            for row in node["results"]:
                if not isinstance(row, dict):
                    continue
                section_counts["records"] += 1
                tmdb_id = valid_id(row.get("tmdbId") or row.get("id"))
                imdb_id = str(row.get("imdbId") or "").strip()
                if not tmdb_id and VALID_IMDB.fullmatch(imdb_id):
                    try:
                        resolved = request_json(
                            API + "/api/catalogue/tmdb-find/" + imdb_id
                            + "?" + urllib.parse.urlencode({"media_type": kind})
                        )
                        tmdb_id = valid_id(resolved.get("tmdbId")) if resolved.get("found") else 0
                        if tmdb_id:
                            row["tmdbId"] = tmdb_id
                            section_counts["metadataFieldsFilled"] += 1
                            log("tmdb_id_resolved", section=section, subsection=subsection,
                                title=row.get("title"), imdbId=imdb_id, tmdbId=tmdb_id)
                    except Exception as exc:
                        log("tmdb_id_resolution_failed", section=section, subsection=subsection,
                            title=row.get("title"), imdbId=imdb_id, error=str(exc))
                    time.sleep(float(os.getenv("SECTION_METADATA_DELAY_SECONDS", "0.15")))
                elif tmdb_id and not row.get("tmdbId"):
                    row["tmdbId"] = tmdb_id
                    section_counts["metadataFieldsFilled"] += 1

                # Repair URLs in place without changing image identity.
                for field, size in (("posterUrl", "w500"), ("backdropUrl", "w780")):
                    repaired = image_url(row.get(field), size)
                    if repaired and repaired != row.get(field):
                        row[field] = repaired
                        section_counts["metadataFieldsFilled"] += 1

                if tmdb_id:
                    cached_ott = movie_ott(ott_items, tmdb_id) if kind == "movie" else None
                    if cached_ott and not isinstance(row.get("ottAvailability"), dict):
                        row["ottAvailability"] = cached_ott
                        row["streamingProviders"] = cached_ott.get("streamingProviders") or row.get("streamingProviders") or []
                        section_counts["ottCacheHits"] += 1
                    missing = (
                        empty(row.get("overview")) or empty(row.get("posterUrl"))
                        or empty(row.get("backdropUrl")) or empty(row.get("releaseDate"))
                        or (kind == "tv" and not isinstance(row.get("ottAvailability"), dict))
                    )
                    if missing:
                        try:
                            details = request_json(metadata_url(kind, tmdb_id))
                            for field in ("title", "year", "releaseDate", "overview",
                                          "posterUrl", "backdropUrl", "rating", "tmdbUrl",
                                          "imdbId", "streamingProviders", "ottAvailability"):
                                value = details.get(field)
                                if not empty(row.get(field)) or empty(value):
                                    continue
                                if field == "posterUrl":
                                    value = image_url(value, "w500")
                                elif field == "backdropUrl":
                                    value = image_url(value, "w780")
                                row[field] = value
                                section_counts["metadataFieldsFilled"] += 1
                            section_counts["tmdbLookups"] += 1
                        except Exception as exc:
                            log("tmdb_lookup_failed", section=section, subsection=subsection,
                                title=row.get("title"), tmdbId=tmdb_id, mediaType=kind, error=str(exc))
                        time.sleep(float(os.getenv("SECTION_METADATA_DELAY_SECONDS", "0.15")))
                pending_imdb.append((row, kind, tmdb_id))

        section_counts["imdbFieldsFilled"] = enrich_imdb_batches(pending_imdb, imdb_cache)
        doc["builtAt"] = datetime.now(timezone.utc).isoformat()
        doc["metadataRefresh"] = {
            "mode": "metadata-only",
            "region": REGION,
            "torrentSearches": 0,
            "torrentFilesRead": 0,
            "torrentFilesWritten": 0,
            "curatedOrderPreserved": True,
        }
        atomic_write(path, doc)
        totals["sections"] += 1
        totals["records"] += section_counts["records"]
        for key in ("tmdbLookups", "metadataFieldsFilled", "imdbFieldsFilled", "ottCacheHits"):
            totals[key] += section_counts[key]
        log("section_written", section=section, **section_counts)

    log("metadata_refresh_complete", **totals,
        imdbCacheRecords=len(imdb_rows), ottCacheEntries=len(ott_items),
        torrentSearches=0, torrentFilesRead=0, torrentFilesWritten=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
