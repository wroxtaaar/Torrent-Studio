#!/usr/bin/env python3
"""Build a separate Hollywood metadata seed without searching torrent providers.

Outputs hollywood.json under REFRESH_SEED_DIR (default ~/torrent-studio-refresh/seed).
Only Popular, Trending and Latest are processed, with at most three 18-movie pages
per subsection. The running API supplies TMDB/IMDb metadata; this script never
publishes the generated seed or changes the running application's caches.

Modes:
  python scripts/build_hollywood_section_cache.py missing
  python scripts/build_hollywood_section_cache.py deep
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REFRESH_HOME = Path(os.getenv("TS_HOME") or Path.home() / "torrent-studio-refresh")
SEED = Path(os.getenv("REFRESH_SEED_DIR") or REFRESH_HOME / "seed").resolve()
API = os.getenv("HOME_API_BASE", "http://127.0.0.1:10000").rstrip("/")
OUTPUT = SEED / "hollywood.json"
PAGE_SIZE = 18
MAX_PAGES = 3
MAX_RECORDS = PAGE_SIZE * MAX_PAGES
SUBSECTIONS = {
    "popular": "popular-hollywood",
    "trending": "trending-hollywood",
    "latest": "latest-hollywood",
}
TORRENT_FIELDS = {"torrentDetails", "torrentMatch", "torrentMatches", "cachedTorrentDetails"}
VALID_IMDB_ID = re.compile(r"^tt\d+$")


def log(event: str, **fields: Any) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def request_json(url: str, *, label: str, retries: int = 3) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "TorrentStudio-HollywoodCache/1.0"},
    )
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError(f"{label} returned a non-object JSON payload")
            return payload
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            retryable = not isinstance(exc, urllib.error.HTTPError) or exc.code >= 500
            log(
                "api_error",
                request=label,
                attempt=attempt,
                maxAttempts=retries,
                error=str(exc),
                retryable=retryable,
            )
            if not retryable or attempt == retries:
                raise
            delay = min(8.0, float(2 ** (attempt - 1)))
            log("api_retry", request=label, attempt=attempt + 1, delaySeconds=delay)
            time.sleep(delay)
    raise RuntimeError(f"{label} failed without a response")


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def catalogue_url(key: str, page: int) -> str:
    query = urllib.parse.urlencode({
        "page": page,
        "live": "true",
        "cache_write": "false",
    })
    return f"{API}/api/movies/catalogue/{urllib.parse.quote(key, safe='')}?{query}"


def request_page(key: str, page: int) -> dict[str, Any]:
    payload = request_json(catalogue_url(key, page), label=f"{key} page {page}")
    if not isinstance(payload.get("results"), list):
        raise RuntimeError(f"Unexpected catalogue response for {key} page {page}")
    return payload


def title_key(row: dict[str, Any]) -> str:
    imdb = str(row.get("imdbId") or "").strip().casefold()
    if imdb:
        return "imdb:" + imdb
    tmdb = row.get("tmdbId") or row.get("id")
    if tmdb not in (None, ""):
        return "tmdb:" + str(tmdb)
    title = re.sub(r"[^a-z0-9]+", "", str(row.get("title") or row.get("name") or "").casefold())
    year = row.get("year") or str(row.get("releaseDate") or "")[:4]
    return f"title:{title}:{year}"


def identity_keys(row: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    tmdb_id = valid_tmdb_id(row.get("tmdbId")) or valid_tmdb_id(row.get("id"))
    if tmdb_id:
        keys.append("tmdb:" + str(tmdb_id))
    imdb_id = str(row.get("imdbId") or "").strip().casefold()
    if VALID_IMDB_ID.fullmatch(imdb_id):
        keys.append("imdb:" + imdb_id)
    title = re.sub(r"[^a-z0-9]+", "", str(row.get("title") or row.get("name") or "").casefold())
    year = row.get("year") or str(row.get("releaseDate") or "")[:4]
    if title:
        keys.append(f"title:{title}:{year}")
    if not keys and title_key(row):
        keys.append(title_key(row))
    return keys


def valid_tmdb_id(value: Any) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return number if number > 0 else 0


def valid_imdb_rating(value: Any) -> float:
    try:
        rating = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return rating if 0 < rating <= 10 else 0


def empty(value: Any) -> bool:
    if isinstance(value, str):
        return not value.strip()
    return value is None or value == "" or value == [] or value == {}


def valid_timestamp(value: Any) -> bool:
    if isinstance(value, (int, float)):
        return value > 0
    return bool(str(value or "").strip())


def imdb_complete(row: dict[str, Any]) -> bool:
    return (
        bool(VALID_IMDB_ID.fullmatch(str(row.get("imdbId") or "").strip()))
        and bool(valid_imdb_rating(row.get("imdbRating")))
        and row.get("imdbRatingStatus") == "found"
        and valid_timestamp(row.get("imdbCheckedAt"))
    )


def metadata_only(row: dict[str, Any]) -> dict[str, Any]:
    """Keep torrent payloads exclusively in the paired *-torrents.json file."""
    return {key: value for key, value in row.items() if key not in TORRENT_FIELDS}


def with_explicit_tmdb_id(row: dict[str, Any]) -> dict[str, Any]:
    result = metadata_only(row)
    tmdb_id = valid_tmdb_id(result.get("tmdbId")) or valid_tmdb_id(result.get("id"))
    if tmdb_id:
        result["tmdbId"] = tmdb_id
    return result


def merge_missing(old: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    result = metadata_only(old)
    for key, value in metadata_only(fresh).items():
        if empty(result.get(key)) and not empty(value):
            result[key] = value
    return with_explicit_tmdb_id(result)


def merge_deep(old: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    result = metadata_only(old)
    preserve_if_good = {"imdbId", "imdbRating", "imdbVotes", "imdbUrl", "tmdbId"}
    for key, value in metadata_only(fresh).items():
        if empty(value):
            continue
        if key in preserve_if_good and not empty(result.get(key)):
            continue
        result[key] = value
    return with_explicit_tmdb_id(result)


def incomplete_reasons(row: dict[str, Any]) -> list[str]:
    reasons = []
    if not valid_tmdb_id(row.get("tmdbId")):
        reasons.append("missing_tmdb_id")
    if not str(row.get("title") or "").strip():
        reasons.append("missing_title")
    if empty(row.get("posterUrl")):
        reasons.append("missing_poster")
    if empty(row.get("overview")):
        reasons.append("missing_overview")
    if not VALID_IMDB_ID.fullmatch(str(row.get("imdbId") or "").strip()):
        reasons.append("missing_imdb_id")
    if not valid_imdb_rating(row.get("imdbRating")):
        reasons.append("missing_imdb_rating")
    if row.get("imdbRatingStatus") != "found":
        reasons.append("missing_imdb_status")
    if not valid_timestamp(row.get("imdbCheckedAt")):
        reasons.append("missing_imdb_checked_at")
    return reasons


def core_complete(row: dict[str, Any]) -> bool:
    return not incomplete_reasons(row)


def cached_rows(section: dict[str, Any]) -> list[dict[str, Any]]:
    rows = section.get("results") or []
    return [row for row in rows if isinstance(row, dict)][:MAX_RECORDS] if isinstance(rows, list) else []


def fetch_catalogue(
    key: str,
    existing: list[dict[str, Any]],
    mode: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if mode == "missing" and existing:
        rows = [with_explicit_tmdb_id(row) for row in existing[:MAX_RECORDS]]
        metadata_fields_filled = 0
        for before, row in zip(existing[:MAX_RECORDS], rows):
            if not valid_tmdb_id(before.get("tmdbId")) and valid_tmdb_id(row.get("tmdbId")):
                metadata_fields_filled += 1
                log("metadata_field_filled", subsection=key, tmdbId=row["tmdbId"], field="tmdbId", source="cached_id")
        page_count = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        for page in range(1, page_count + 1):
            start = (page - 1) * PAGE_SIZE
            log(
                "page_inspected",
                subsection=key,
                page=page,
                source="refresh_seed",
                recordsInspected=len(rows[start:start + PAGE_SIZE]),
            )
        all_complete = all(core_complete(row) for row in rows)
        return rows, {
            "catalogue": key,
            "pageCount": page_count,
            "totalResults": len(rows),
            "recordsInspected": len(rows),
            "metadataFieldsFilled": metadata_fields_filled,
            "skipped": all_complete,
            "reason": "all_cached_records_have_required_metadata" if all_complete else "enriching_incomplete_cached_records",
            "source": "refresh_seed",
        }

    old_by_identity: dict[str, dict[str, Any]] = {}
    for old in existing:
        for identity in identity_keys(old):
            old_by_identity.setdefault(identity, old)

    rows: list[dict[str, Any]] = []
    page_count = 0
    records_inspected = 0
    metadata_fields_filled = 0
    source_total_pages = 1
    for page in range(1, MAX_PAGES + 1):
        log("page_started", subsection=key, page=page, maxPages=MAX_PAGES, pageSize=PAGE_SIZE)
        payload = request_page(key, page)
        page_count += 1
        source_total_pages = max(1, int(payload.get("totalPages") or page))
        page_rows = [
            row for row in payload["results"]
            if isinstance(row, dict) and (row.get("title") or row.get("name"))
        ][:PAGE_SIZE]
        records_inspected += len(page_rows)
        log("page_inspected", subsection=key, page=page, recordsInspected=len(page_rows))
        for fresh_source in page_rows:
            fresh = with_explicit_tmdb_id(fresh_source)
            previous = next(
                (old_by_identity[identity] for identity in identity_keys(fresh)
                 if identity in old_by_identity),
                None,
            )
            if previous:
                row = merge_missing(previous, fresh) if mode == "missing" else merge_deep(previous, fresh)
            else:
                row = fresh
            rows.append(with_explicit_tmdb_id(row))
            for field in ("tmdbId", "overview", "posterUrl"):
                if empty((previous or {}).get(field)) and not empty(row.get(field)):
                    metadata_fields_filled += 1
                    log(
                        "metadata_field_filled",
                        subsection=key,
                        tmdbId=row.get("tmdbId"),
                        field=field,
                        source="catalogue",
                    )
        if page >= source_total_pages or not page_rows:
            break
        if page < MAX_PAGES:
            time.sleep(float(os.getenv("HOLLYWOOD_CACHE_DELAY_SECONDS", "0.1")))

    if not rows:
        raise RuntimeError(f"Refusing to replace {key}: API returned zero usable rows")
    if mode == "missing":
        present = {identity for row in rows for identity in identity_keys(row)}
        for old in existing:
            if len(rows) >= MAX_RECORDS:
                break
            if not any(identity in present for identity in identity_keys(old)):
                rows.append(with_explicit_tmdb_id(old))
                present.update(identity_keys(old))
    rows = rows[:MAX_RECORDS]
    return rows, {
        "catalogue": key,
        "pageCount": page_count,
        "sourcePageCount": source_total_pages,
        "totalResults": len(rows),
        "recordsInspected": records_inspected,
        "metadataFieldsFilled": metadata_fields_filled,
        "skipped": False,
    }


def _imdb_lookup_url(rows: list[dict[str, Any]]) -> tuple[str, dict[str, dict[str, Any]]]:
    params: list[tuple[str, str]] = [("persist", "false"), ("refresh_incomplete", "true")]
    requested: dict[str, dict[str, Any]] = {}
    for row in rows:
        if imdb_complete(row):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        year = row.get("year") or str(row.get("releaseDate") or "")[:4]
        query_title = f"{title} ({year})" if str(year).isdigit() else title
        tmdb_id = valid_tmdb_id(row.get("tmdbId"))
        identity = f"{query_title.casefold()}|{tmdb_id}"
        if identity in requested:
            continue
        requested[identity] = {"title": query_title, "tmdbId": tmdb_id}
        params.append(("titles", query_title))
        params.append(("media_types", "movie"))
        params.append(("tmdb_ids", str(tmdb_id)))
    return f"{API}/api/catalogue/imdb-ratings?{urllib.parse.urlencode(params)}", requested


def set_imdb_rating_status(row: dict[str, Any], result_status: str = "unavailable") -> None:
    """Keep IMDb identity resolution distinct from IMDb rating availability."""
    imdb_id = str(row.get("imdbId") or "").strip()
    has_id = bool(VALID_IMDB_ID.fullmatch(imdb_id))
    has_rating = bool(valid_imdb_rating(row.get("imdbRating")))
    if has_id and has_rating:
        row["imdbRatingStatus"] = "found"
    elif has_id and result_status not in {"unavailable", "rate_limited"}:
        row["imdbRatingStatus"] = "id_found_no_rating"
    else:
        row["imdbRatingStatus"] = result_status or "unavailable"


def enrich_imdb(rows: list[dict[str, Any]], subsection: str) -> dict[str, int]:
    url, requested = _imdb_lookup_url(rows)
    if not requested:
        return {"requested": 0, "idsResolved": 0, "ratingsFetched": 0}
    try:
        payload = request_json(url, label=f"{subsection} IMDb enrichment")
    except Exception as exc:
        log("imdb_batch_failed", subsection=subsection, requested=len(requested), error=str(exc))
        for row in rows:
            if not (
                VALID_IMDB_ID.fullmatch(str(row.get("imdbId") or "").strip())
                and valid_imdb_rating(row.get("imdbRating"))
            ):
                set_imdb_rating_status(row, "unavailable")
        return {"requested": len(requested), "idsResolved": 0, "ratingsFetched": 0}

    by_query = {
        str(item.get("query") or "").casefold(): item
        for item in payload.get("results", [])
        if isinstance(item, dict)
    }
    ids_resolved = 0
    ratings_fetched = 0
    for row in rows:
        if imdb_complete(row):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        year = row.get("year") or str(row.get("releaseDate") or "")[:4]
        query_title = f"{title} ({year})" if str(year).isdigit() else title
        result = by_query.get(query_title.casefold())
        if not result:
            if not (
                VALID_IMDB_ID.fullmatch(str(row.get("imdbId") or "").strip())
                and valid_imdb_rating(row.get("imdbRating"))
            ):
                set_imdb_rating_status(row, "unavailable")
            continue
        returned_tmdb_id = valid_tmdb_id(result.get("tmdbIdTried"))
        row_tmdb_id = valid_tmdb_id(row.get("tmdbId"))
        if returned_tmdb_id and row_tmdb_id and returned_tmdb_id != row_tmdb_id:
            log(
                "imdb_result_identity_mismatch",
                subsection=subsection,
                title=title,
                requestedTmdbId=row_tmdb_id,
                returnedTmdbId=returned_tmdb_id,
            )
            if not (
                VALID_IMDB_ID.fullmatch(str(row.get("imdbId") or "").strip())
                and valid_imdb_rating(row.get("imdbRating"))
            ):
                set_imdb_rating_status(row, "unavailable")
            continue
        returned_id = str(result.get("imdbId") or "").strip()
        if not VALID_IMDB_ID.fullmatch(str(row.get("imdbId") or "").strip()) and VALID_IMDB_ID.fullmatch(returned_id):
            row["imdbId"] = returned_id
            ids_resolved += 1
        returned_rating = valid_imdb_rating(result.get("imdbRating"))
        if not valid_imdb_rating(row.get("imdbRating")) and returned_rating:
            row["imdbRating"] = returned_rating
            ratings_fetched += 1
        for source, target in (("imdbVotes", "imdbVotes"), ("imdbUrl", "imdbUrl")):
            if empty(row.get(target)) and not empty(result.get(source)):
                row[target] = result[source]
        if result.get("checkedAt") is not None:
            row["imdbCheckedAt"] = result["checkedAt"]
        set_imdb_rating_status(row, str(result.get("status") or "unavailable"))
    log(
        "imdb_enrichment_complete",
        subsection=subsection,
        requested=len(requested),
        idsResolved=ids_resolved,
        ratingsFetched=ratings_fetched,
        apiMatched=payload.get("matched", 0),
    )
    return {"requested": len(requested), "idsResolved": ids_resolved, "ratingsFetched": ratings_fetched}


def fill_tmdb_metadata(rows: list[dict[str, Any]], subsection: str) -> int:
    fields_filled = 0
    for row in rows:
        missing_fields = [field for field in ("overview", "posterUrl") if empty(row.get(field))]
        tmdb_id = valid_tmdb_id(row.get("tmdbId"))
        if not missing_fields or not tmdb_id:
            continue
        url = f"{API}/api/movies/tmdb-metadata/{tmdb_id}"
        try:
            details = request_json(url, label=f"{subsection} TMDB metadata {tmdb_id}")
        except Exception as exc:
            log(
                "metadata_lookup_failed",
                subsection=subsection,
                tmdbId=tmdb_id,
                missingFields=missing_fields,
                error=str(exc),
            )
            continue
        for field in missing_fields:
            value = details.get(field)
            if not empty(value):
                row[field] = value
                fields_filled += 1
                log("metadata_field_filled", subsection=subsection, tmdbId=tmdb_id, field=field)
    return fields_filled


def summarize_rows(rows: list[dict[str, Any]], subsection: str) -> dict[str, Any]:
    incomplete = []
    for row in rows:
        reasons = incomplete_reasons(row)
        if reasons:
            item = {"title": row.get("title"), "tmdbId": row.get("tmdbId"), "reasons": reasons}
            incomplete.append(item)
            log("record_incomplete", subsection=subsection, **item)
    return {
        "records": len(rows),
        "complete": len(rows) - len(incomplete),
        "incomplete": len(incomplete),
        "incompleteReasons": {
            reason: sum(reason in item["reasons"] for item in incomplete)
            for reason in sorted({reason for item in incomplete for reason in item["reasons"]})
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("missing", "deep"))
    args = parser.parse_args()
    if not SEED.is_dir():
        raise SystemExit(f"Refresh seed directory does not exist: {SEED}")

    health = request_json(f"{API}/api/health", label="API health check")
    if not health:
        raise SystemExit("API health check returned an empty payload")

    previous_doc = read_json(OUTPUT)
    previous_sections = previous_doc.get("subsections") if isinstance(previous_doc.get("subsections"), dict) else {}
    result_sections: dict[str, Any] = {}
    report: list[dict[str, Any]] = []
    for subsection, key in SUBSECTIONS.items():
        log("subsection_started", subsection=subsection, catalogue=key, mode=args.mode)
        old_section = previous_sections.get(subsection) if isinstance(previous_sections.get(subsection), dict) else {}
        old_rows = cached_rows(old_section)
        try:
            rows, info = fetch_catalogue(key, old_rows, args.mode)
            if not info.get("skipped"):
                imdb_info = enrich_imdb(rows, subsection)
                metadata_filled = fill_tmdb_metadata(rows, subsection)
                info["imdb"] = imdb_info
                info["metadataFieldsFilled"] = int(info.get("metadataFieldsFilled") or 0) + metadata_filled
            else:
                info["imdb"] = {"requested": 0, "idsResolved": 0, "ratingsFetched": 0}
                info.setdefault("metadataFieldsFilled", 0)
        except Exception as exc:
            log("subsection_failed", subsection=subsection, catalogue=key, error=str(exc))
            if not old_rows:
                raise RuntimeError(f"{key} failed and has no prior cache to preserve: {exc}") from exc
            rows = old_rows[:MAX_RECORDS]
            info = {
                "catalogue": key,
                "pageCount": 0,
                "totalResults": len(rows),
                "preservedAfterError": str(exc),
                "imdb": {"requested": 0, "idsResolved": 0, "ratingsFetched": 0},
                "metadataFieldsFilled": 0,
            }
        summary = summarize_rows(rows, subsection)
        info["summary"] = summary
        result_sections[subsection] = {
            "catalogueKey": key,
            "mediaType": "movie",
            "pageSize": PAGE_SIZE,
            "pageCount": min(MAX_PAGES, int(info.get("pageCount") or 0)),
            "totalResults": len(rows),
            "builtAt": datetime.now(timezone.utc).isoformat(),
            "results": rows[:MAX_RECORDS],
            **({"status": "preserved-after-error"} if info.get("preservedAfterError") else {}),
        }
        report.append(info)
        log("subsection_complete", subsection=subsection, **info)

    document = dict(previous_doc)
    document.update({
        "schemaVersion": 1,
        "section": "hollywood",
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "subsections": result_sections,
        "safety": {
            "torrentSearches": 0,
            "torrentDataStoredSeparately": True,
            "activeApplicationCacheWrites": 0,
            "source": "existing Torrent Studio movie/IMDb/TMDB metadata APIs",
        },
    })
    atomic_write(OUTPUT, document)
    overall = {
        "path": str(OUTPUT),
        "mode": args.mode,
        "maxPagesPerSubsection": MAX_PAGES,
        "pageSize": PAGE_SIZE,
        "maxRecordsPerSubsection": MAX_RECORDS,
        "subsections": report,
        "torrent_searches": 0,
        "active_application_cache_writes": 0,
    }
    log("hollywood_section_cache_written", **overall)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
