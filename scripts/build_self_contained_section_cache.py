#!/usr/bin/env python3
"""Migrate metadata-only catalogue rows into nine self-contained section files."""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

SECTIONS = (
    "hollywood", "bollywood", "marvel", "dc", "highest-rated",
    "korean", "pakistani", "anime", "favourites",
)
PAGE_SIZE = 18
SHARED_METADATA_FILES = (
    "tmdb_movie_catalogue_cache.json",
    "tmdb_search_metadata_cache.json",
    "imdb_rating_cache.json",
    "tmdb_ott_availability_cache.json",
)
TMDB_FIELDS = (
    "tmdbId", "tmdbUrl", "year", "releaseDate", "overview",
    "posterUrl", "backdropUrl", "rating", "genres", "originCountry",
    "originalLanguage", "seriesType", "networks", "malId", "source",
    "trendingWeek", "trendingRank", "trendingWeeks",
)
OTT_FIELDS = (
    "movieId", "region", "status", "streamingProviders", "rentProviders",
    "buyProviders", "theatricalReleaseDate", "digitalReleaseDate",
    "providerLink", "checkedAt", "source", "providerAttribution", "attribution",
    "incomplete",
)
REGIONAL_TV_CATALOGUES = {
    "hollywood-popular": ("hollywood", "tv-popular"),
    "hollywood-trending": ("hollywood", "tv-trending"),
    "hollywood-latest": ("hollywood", "tv-latest"),
    "indian-popular": ("bollywood", "tv-popular"),
    "indian-trending": ("bollywood", "tv-trending"),
    "indian-latest": ("bollywood", "tv-latest"),
}
REGIONAL_TV_FIELDS = (
    "id", "tmdbId", "title", "name", "year", "releaseDate", "overview",
    "posterUrl", "backdropUrl", "rating", "genres", "tmdbUrl", "imdbId",
    "imdbRating", "imdbVotes", "imdbUrl", "imdbCheckedAt", "imdbRatingStatus",
    "ottAvailability", "streamingProviders", "providerLink", "originCountry",
    "originalLanguage", "source", "seriesType", "networks",
)
REGIONAL_TV_METADATA_FIELDS = tuple(
    field for field in REGIONAL_TV_FIELDS if field not in {"id", "title", "name"}
)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not read required JSON {path}: {exc}") from exc


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def numeric_id(value: Any) -> int:
    try:
        result = int(value)
        return result if result > 0 else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def page_offsets(result_count: int, page_size: int = PAGE_SIZE) -> list[int]:
    return [*range(0, result_count, page_size), result_count]


def valid_imdb_rating(value: Any) -> bool:
    try:
        rating = float(value)
        return 0 < rating <= 10
    except (TypeError, ValueError, OverflowError):
        return False


def year_of(row: dict[str, Any]) -> int:
    raw = row.get("year") or row.get("releaseDate") or row.get("firstAirDate")
    match = re.match(r"^(\d{4})", str(raw or ""))
    return int(match.group(1)) if match else 0


def normalized_title(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    normalized = re.sub(r"^(?:the|a|an)\s+", "", normalized)
    return re.sub(r"\bfour\b", "4", normalized)


def record_key(row: dict[str, Any], kind: str) -> tuple[str, str, int]:
    title = normalized_title(row.get("title") or row.get("name"))
    row_kind = str(row.get("mediaType") or kind).casefold()
    row_kind = "tv" if row_kind in {"tv", "series"} else "movie"
    return row_kind, title, year_of(row)


def cache_records(
    cache_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], dict[tuple[str, int], str]]:
    tmdb_movie = read_json(cache_dir / "tmdb_movie_catalogue_cache.json")
    tmdb_search = read_json(cache_dir / "tmdb_search_metadata_cache.json")
    imdb = read_json(cache_dir / "imdb_rating_cache.json")
    ott = read_json(cache_dir / "tmdb_ott_availability_cache.json")

    movie_rows: list[dict[str, Any]] = []
    catalogues = tmdb_movie.get("catalogues") if isinstance(tmdb_movie, dict) else None
    if isinstance(catalogues, dict):
        for node in catalogues.values():
            payload = node.get("payload") if isinstance(node, dict) else None
            results = payload.get("results") if isinstance(payload, dict) else None
            if isinstance(results, list):
                movie_rows.extend(row for row in results if isinstance(row, dict))

    search_rows = tmdb_search.get("results") if isinstance(tmdb_search, dict) else None
    imdb_rows = imdb.get("results") if isinstance(imdb, dict) else None
    ott_items = ott.get("items") if isinstance(ott, dict) else None
    if not isinstance(search_rows, list) or not isinstance(imdb_rows, list) or not isinstance(ott_items, dict):
        raise RuntimeError("One or more metadata caches have an unexpected schema")
    posters: dict[tuple[str, int], str] = {}
    poster_map = cache_dir.parent / "poster_map.json"
    if poster_map.is_file():
        poster_rows = read_json(poster_map)
        if isinstance(poster_rows, list):
            for entry in poster_rows:
                if not isinstance(entry, list) or len(entry) < 3:
                    continue
                title, raw_year, poster = entry[:3]
                normalized = normalized_title(title)
                try:
                    year = int(raw_year or 0)
                except (TypeError, ValueError, OverflowError):
                    year = 0
                poster_url = str(poster or "").strip()
                if normalized and poster_url.startswith(("https://", "http://")):
                    posters.setdefault((normalized, year), poster_url)
    return (
        movie_rows,
        [row for row in search_rows if isinstance(row, dict)],
        ott_items,
        [row for row in imdb_rows if isinstance(row, dict)],
        posters,
    )


def metadata_index(rows: list[dict[str, Any]], kind: str) -> tuple[dict[tuple[str, int], dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str, int], dict[str, Any]]]:
    by_tmdb: dict[tuple[str, int], dict[str, Any]] = {}
    by_imdb: dict[tuple[str, str], dict[str, Any]] = {}
    by_title: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        row_kind = str(row.get("mediaType") or kind).casefold()
        row_kind = "tv" if row_kind in {"tv", "series"} else "movie"
        tmdb_id = numeric_id(row.get("id")) or numeric_id(row.get("tmdbId"))
        imdb_id = str(row.get("imdbId") or "").strip()
        if tmdb_id:
            by_tmdb.setdefault((row_kind, tmdb_id), row)
        if re.fullmatch(r"tt\d+", imdb_id):
            by_imdb.setdefault((row_kind, imdb_id), row)
        key = record_key(row, row_kind)
        if key[1]:
            by_title.setdefault(key, row)
    return by_tmdb, by_imdb, by_title


def imdb_index(rows: list[dict[str, Any]]) -> tuple[dict[tuple[str, str, int], dict[str, Any]], dict[tuple[str, int], dict[str, Any]]]:
    indexed: dict[tuple[str, str, int], dict[str, Any]] = {}
    by_tmdb: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        kind = str(row.get("mediaType") or "movie").casefold()
        kind = "tv" if kind in {"tv", "series"} else "movie"
        key = record_key(row, kind)
        if key[1]:
            indexed.setdefault(key, row)
        tmdb_id = numeric_id(row.get("tmdbIdTried"))
        if tmdb_id:
            by_tmdb.setdefault((kind, tmdb_id), row)
    return indexed, by_tmdb


def fill_missing(row: dict[str, Any], source: dict[str, Any], fields: tuple[str, ...]) -> int:
    changed = 0
    for field in fields:
        value = source.get(field)
        if field == "imdbId" and value and not re.fullmatch(r"tt\d+", str(value)):
            continue
        if field == "imdbRating" and value is not None and not valid_imdb_rating(value):
            continue
        if field in {"posterUrl", "backdropUrl", "tmdbUrl", "imdbUrl"} and value:
            if not str(value).strip().startswith(("https://", "http://")):
                continue
        current = row.get(field)
        current_is_invalid = (
            (field == "imdbId" and current not in (None, "") and not re.fullmatch(r"tt\d+", str(current)))
            or (field == "imdbRating" and current not in (None, "") and not valid_imdb_rating(current))
            or (
                field in {"posterUrl", "backdropUrl", "tmdbUrl", "imdbUrl"}
                and current not in (None, "")
                and not str(current).strip().startswith(("https://", "http://"))
            )
        )
        if (current in (None, "", [], {}) or current_is_invalid) and value not in (None, "", [], {}):
            row[field] = value
            changed += 1
    return changed


def enrich_row(
    row: dict[str, Any],
    kind: str,
    tmdb_indexes: tuple[
        tuple[dict[tuple[str, int], dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str, int], dict[str, Any]]],
        tuple[dict[tuple[str, int], dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[tuple[str, str, int], dict[str, Any]]],
    ],
    imdb_indexes: tuple[dict[tuple[str, str, int], dict[str, Any]], dict[tuple[str, int], dict[str, Any]]],
    ott_items: dict[str, Any],
    poster_index: dict[tuple[str, int], str],
) -> int:
    changed = 0
    tmdb_id = numeric_id(row.get("id")) or numeric_id(row.get("tmdbId"))
    imdb_id = str(row.get("imdbId") or "").strip()
    key = record_key(row, kind)
    candidates: list[dict[str, Any]] = []
    for by_tmdb, by_imdb, by_title in tmdb_indexes:
        match = by_tmdb.get((kind, tmdb_id)) if tmdb_id else None
        if match is None and imdb_id:
            match = by_imdb.get((kind, imdb_id))
        if match is None:
            match = by_title.get(key)
        if match is not None and match not in candidates:
            candidates.append(match)

    for candidate in candidates:
        changed += fill_missing(row, candidate, TMDB_FIELDS)
        tmdb_id = numeric_id(row.get("id")) or numeric_id(row.get("tmdbId"))
        imdb_id = str(row.get("imdbId") or "").strip()

    imdb_by_title, imdb_by_tmdb = imdb_indexes
    imdb_record = imdb_by_tmdb.get((kind, tmdb_id)) if tmdb_id else None
    if imdb_record is None:
        imdb_record = imdb_by_title.get(key)
    if imdb_record and imdb_record.get("status") == "found":
        imdb_values = {
            "imdbId": imdb_record.get("imdbId"),
            "imdbRating": imdb_record.get("imdbRating"),
            "imdbVotes": imdb_record.get("imdbVotes"),
            "imdbUrl": imdb_record.get("imdbUrl"),
            "imdbCheckedAt": imdb_record.get("checkedAt"),
            "imdbRatingStatus": imdb_record.get("status"),
        }
        changed += fill_missing(row, imdb_values, tuple(imdb_values))
        if row.get("imdbRatingStatus") != "found":
            row["imdbRatingStatus"] = "found"
            changed += 1
    elif imdb_record:
        if valid_imdb_rating(row.get("imdbRating")):
            if row.get("imdbRatingStatus") != "found":
                row["imdbRatingStatus"] = "found"
                changed += 1
        else:
            status = imdb_record.get("status")
            if status and row.get("imdbRatingStatus") != status:
                row["imdbRatingStatus"] = status
                changed += 1
        if row.get("imdbCheckedAt") in (None, "") and imdb_record.get("checkedAt") not in (None, ""):
            row["imdbCheckedAt"] = imdb_record["checkedAt"]
            changed += 1

    if tmdb_id:
        for cache_key in (f"v2:{tmdb_id}:IN", f"{tmdb_id}:IN"):
            envelope = ott_items.get(cache_key)
            payload = envelope.get("payload") if isinstance(envelope, dict) else None
            if not isinstance(payload, dict) or str(payload.get("region") or "IN").upper() != "IN":
                continue
            availability = {field: payload[field] for field in OTT_FIELDS if field in payload}
            current_availability = row.get("ottAvailability")
            if not isinstance(current_availability, dict):
                current_availability = {}
                if row.get("ottAvailability") in (None, "", [], {}):
                    row["ottAvailability"] = current_availability
                    changed += 1
            for field, value in availability.items():
                if current_availability.get(field) in (None, "", [], {}) and value not in (None, "", [], {}):
                    current_availability[field] = value
                    changed += 1
            for field in ("streamingProviders", "rentProviders", "buyProviders", "providerLink"):
                value = availability.get(field)
                if row.get(field) in (None, "", [], {}) and value not in (None, "", [], {}):
                    row[field] = value
                    changed += 1
            break

    normalized = normalized_title(row.get("title") or row.get("name"))
    year = year_of(row)
    poster = poster_index.get((normalized, year)) or poster_index.get((normalized, 0))
    if poster and row.get("posterUrl") in (None, "", [], {}):
        row["posterUrl"] = poster
        changed += 1

    return changed


def merge_regional_tv_row(row: dict[str, Any], source: dict[str, Any]) -> int:
    metadata = dict(source)
    if not numeric_id(metadata.get("tmdbId")):
        source_id = numeric_id(metadata.get("id"))
        if source_id:
            metadata["tmdbId"] = source_id
    changed = fill_missing(row, metadata, REGIONAL_TV_METADATA_FIELDS)
    source_ott = source.get("ottAvailability")
    current_ott = row.get("ottAvailability")
    if isinstance(source_ott, dict):
        if not isinstance(current_ott, dict):
            row["ottAvailability"] = dict(source_ott)
            changed += 1
        else:
            changed += fill_missing(current_ott, source_ott, tuple(source_ott))
    for field in ("streamingProviders", "rentProviders", "buyProviders", "providerLink"):
        value = source.get(field)
        if row.get(field) in (None, "", [], {}) and value not in (None, "", [], {}):
            row[field] = value
            changed += 1
    if not isinstance(row.get("ottAvailability"), dict):
        availability = availability_from_provider_rows(row.get("streamingProviders"))
        if availability:
            row["ottAvailability"] = availability
            changed += 1
            for field in ("rentProviders", "buyProviders", "providerLink"):
                value = availability.get(field)
                if row.get(field) in (None, "", [], {}) and value not in (None, "", [], {}):
                    row[field] = value
                    changed += 1
    if valid_imdb_rating(row.get("imdbRating")) and row.get("imdbRatingStatus") != "found":
        row["imdbRatingStatus"] = "found"
        changed += 1
    return changed


def availability_from_provider_rows(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, list):
        return None
    streaming: list[dict[str, Any]] = []
    rent: list[dict[str, Any]] = []
    buy: list[dict[str, Any]] = []
    region = "IN"
    for provider in value:
        if not isinstance(provider, dict) or not str(provider.get("name") or "").strip():
            continue
        kind = str(provider.get("type") or "").casefold()
        if kind in {"subscription", "streaming", "free", "ads", "addon"}:
            streaming.append(provider)
        elif kind == "rent":
            rent.append(provider)
        elif kind == "buy":
            buy.append(provider)
        provider_region = str(provider.get("region") or "").strip().upper()
        if provider_region:
            region = provider_region
    if not (streaming or rent or buy):
        return None
    status = "streaming" if streaming else "rent_buy"
    return {
        "region": region,
        "status": status,
        "streamingProviders": streaming,
        "rentProviders": rent,
        "buyProviders": buy,
        "providerLink": next(
            (str(provider.get("webUrl") or "").strip() for provider in value
             if isinstance(provider, dict) and str(provider.get("webUrl") or "").strip()),
            "",
        ),
        "source": "regional-tv-prebuilt-cache",
    }


def merge_regional_tv_subsection(existing: dict[str, Any], source: dict[str, Any]) -> int:
    source_rows = source.get("results")
    existing_rows = existing.get("results")
    if not isinstance(source_rows, list) or not isinstance(existing_rows, list):
        return 0
    by_tmdb: dict[int, dict[str, Any]] = {}
    by_imdb: dict[str, dict[str, Any]] = {}
    by_title: dict[tuple[str, str, int], dict[str, Any]] = {}
    for candidate in source_rows:
        if not isinstance(candidate, dict):
            continue
        tmdb_id = numeric_id(candidate.get("tmdbId")) or numeric_id(candidate.get("id"))
        imdb_id = str(candidate.get("imdbId") or "").strip()
        key = record_key(candidate, "tv")
        if tmdb_id:
            by_tmdb.setdefault(tmdb_id, candidate)
        if re.fullmatch(r"tt\d+", imdb_id):
            by_imdb.setdefault(imdb_id, candidate)
        if key[1]:
            by_title.setdefault(key, candidate)

    changed = 0
    for row in existing_rows:
        if not isinstance(row, dict):
            continue
        tmdb_id = numeric_id(row.get("id")) or numeric_id(row.get("tmdbId"))
        imdb_id = str(row.get("imdbId") or "").strip()
        candidate = by_tmdb.get(tmdb_id) if tmdb_id else None
        if candidate is None and re.fullmatch(r"tt\d+", imdb_id):
            candidate = by_imdb.get(imdb_id)
        if candidate is None:
            candidate = by_title.get(record_key(row, "tv"))
        if candidate is not None:
            changed += merge_regional_tv_row(row, candidate)
    return changed


def complete_row_fields(row: dict[str, Any], kind: str) -> None:
    tmdb_id = numeric_id(row.get("id")) or numeric_id(row.get("tmdbId"))
    if row.get("id") in (None, "") and tmdb_id:
        row["id"] = tmdb_id
    elif "id" not in row:
        row["id"] = tmdb_id or None
    row["tmdbId"] = tmdb_id or None
    if not row.get("mediaType"):
        row["mediaType"] = kind
    if row.get("year") in (None, ""):
        year = year_of(row)
        row["year"] = year or None
    if row.get("releaseDate") in (None, "") and row.get("firstAirDate"):
        row["releaseDate"] = row["firstAirDate"]
    defaults = {
        "year": None,
        "releaseDate": "",
        "overview": "",
        "posterUrl": "",
        "backdropUrl": "",
        "rating": None,
        "genres": [],
        "tmdbUrl": f"https://www.themoviedb.org/{'tv' if kind == 'tv' else 'movie'}/{tmdb_id}" if tmdb_id else "",
        "imdbId": None,
        "imdbRating": None,
        "imdbVotes": None,
        "imdbUrl": None,
        "imdbCheckedAt": None,
        "imdbRatingStatus": None,
        "ottAvailability": None,
        "streamingProviders": [],
        "rentProviders": [],
        "buyProviders": [],
        "providerLink": "",
    }
    for field, value in defaults.items():
        if field not in row or (field == "tmdbUrl" and row[field] in (None, "")):
            row[field] = value


def regional_tv_subsections(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    payload = read_json(path)
    catalogues = payload.get("catalogues") if isinstance(payload, dict) else None
    if not isinstance(catalogues, dict):
        raise RuntimeError(f"Invalid regional TV cache: {path}")

    sections: dict[str, dict[str, dict[str, Any]]] = {}
    for catalogue_key, (section, subsection_name) in REGIONAL_TV_CATALOGUES.items():
        catalogue = catalogues.get(catalogue_key)
        pages = catalogue.get("pages") if isinstance(catalogue, dict) else None
        if not isinstance(pages, list) or not pages:
            raise RuntimeError(f"Missing TV catalogue pages: {catalogue_key}")

        rows: list[dict[str, Any]] = []
        for expected_page, page in enumerate(pages, start=1):
            if not isinstance(page, dict) or not isinstance(page.get("results"), list):
                raise RuntimeError(f"Invalid TV catalogue page: {catalogue_key}/{expected_page}")
            if numeric_id(page.get("page")) and numeric_id(page["page"]) != expected_page:
                raise RuntimeError(f"TV catalogue pages are out of order: {catalogue_key}")
            for source_row in page["results"]:
                if not isinstance(source_row, dict):
                    raise RuntimeError(f"Invalid TV record: {catalogue_key}/{expected_page}")
                row = {field: source_row[field] for field in REGIONAL_TV_FIELDS if field in source_row}
                if not str(row.get("title") or row.get("name") or "").strip():
                    raise RuntimeError(f"TV record has no title: {catalogue_key}/{expected_page}")
                if not row.get("title") and row.get("name"):
                    row["title"] = row["name"]
                row["mediaType"] = "tv"
                rows.append(row)

        if not rows:
            raise RuntimeError(f"TV catalogue has no records: {catalogue_key}")
        sections.setdefault(section, {})[subsection_name] = {
            "catalogueKey": catalogue_key,
            "mediaType": "tv",
            "pageSize": PAGE_SIZE,
            "pageCount": (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE,
            "pageOffsets": page_offsets(len(rows)),
            "totalResults": len(rows),
            "results": rows,
        }
    return sections


def migrate(
    source_dir: Path,
    cache_dir: Path,
    output_dir: Path,
    regional_tv_cache: Path | None = None,
    sections: tuple[str, ...] = SECTIONS,
) -> dict[str, Any]:
    invalid_sections = set(sections) - set(SECTIONS)
    if invalid_sections:
        raise ValueError(f"Unknown sections requested: {', '.join(sorted(invalid_sections))}")
    tmdb_movie_rows, tmdb_search_rows, ott_items, imdb_rows, poster_index = cache_records(cache_dir)
    tmdb_indexes = (
        metadata_index(tmdb_movie_rows, "movie"),
        metadata_index(tmdb_search_rows, "movie"),
    )
    imdb_indexes = imdb_index(imdb_rows)
    tv_subsections = regional_tv_subsections(regional_tv_cache) if regional_tv_cache else {}
    summary: dict[str, Any] = {}
    for section in sections:
        path = source_dir / f"{section}.json"
        document = read_json(path)
        subsections = document.get("subsections") if isinstance(document, dict) else None
        if not isinstance(subsections, dict):
            raise RuntimeError(f"Invalid section document: {path}")
        regional_cache_fields_migrated = 0
        for subsection_name, node in tv_subsections.get(section, {}).items():
            if subsection_name in subsections:
                if isinstance(subsections[subsection_name], dict):
                    regional_changed = merge_regional_tv_subsection(subsections[subsection_name], node)
                    regional_cache_fields_migrated += regional_changed
                else:
                    regional_changed = 0
                if regional_changed:
                    print(
                        f"[{section}/{subsection_name}] regional_cache_fields_migrated={regional_changed}",
                        flush=True,
                    )
                continue
            subsections[subsection_name] = node
        changed = 0
        row_count = 0
        incomplete_by_subsection: dict[str, dict[str, int]] = {}
        for subsection, node in subsections.items():
            results = node.get("results") if isinstance(node, dict) else None
            if not isinstance(results, list):
                raise RuntimeError(f"Invalid results array: {section}/{subsection}")
            kind = "tv" if node.get("mediaType") in {"tv", "series"} else "movie"
            incomplete: dict[str, int] = {}
            for row in results:
                if not isinstance(row, dict):
                    continue
                row_count += 1
                changed += enrich_row(row, kind, tmdb_indexes, imdb_indexes, ott_items, poster_index)
                complete_row_fields(row, kind)
                required = {
                    "tmdbId": bool(numeric_id(row.get("tmdbId"))),
                    "imdbId": bool(re.fullmatch(r"tt\d+", str(row.get("imdbId") or ""))),
                    "imdbRating": valid_imdb_rating(row.get("imdbRating")),
                    "imdbVotes": row.get("imdbVotes") not in (None, ""),
                    "imdbUrl": bool(str(row.get("imdbUrl") or "").startswith(("https://", "http://"))),
                    "rating": valid_imdb_rating(row.get("rating")),
                    "posterUrl": bool(row.get("posterUrl")),
                    "backdropUrl": bool(row.get("backdropUrl")),
                    "overview": bool(row.get("overview")),
                    "releaseDate": bool(row.get("releaseDate")),
                    "ottAvailability": isinstance(row.get("ottAvailability"), dict),
                }
                for field, is_complete in required.items():
                    if not is_complete:
                        incomplete[field] = incomplete.get(field, 0) + 1
            node["pageSize"] = PAGE_SIZE
            node["pageCount"] = (len(results) + PAGE_SIZE - 1) // PAGE_SIZE
            node["totalResults"] = len(results)
            if kind == "tv":
                node["pageOffsets"] = page_offsets(len(results))
            incomplete_by_subsection[subsection] = incomplete
        document["section"] = section
        document["schemaVersion"] = max(1, int(document.get("schemaVersion") or 1))
        metadata_sources = list(SHARED_METADATA_FILES)
        if (cache_dir.parent / "poster_map.json").is_file():
            metadata_sources.append("poster_map.json")
        if section in tv_subsections:
            metadata_sources.append(regional_tv_cache.name if regional_tv_cache else "regional_tv_prebuilt_cache.json")
        document["metadataSources"] = metadata_sources
        document["metadataSelfContained"] = True
        atomic_write(output_dir / f"{section}.json", document)
        summary[section] = {
            "records": row_count,
            "cacheFieldsMigrated": changed,
            "regionalCacheFieldsMigrated": regional_cache_fields_migrated,
            "incompleteBySubsection": incomplete_by_subsection,
        }
        print(
            f"[{section}] records={row_count} cache_fields_migrated={changed} "
            f"incomplete={json.dumps(incomplete_by_subsection, sort_keys=True)}",
            flush=True,
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True, help="directory with the nine section JSON files")
    parser.add_argument("--cache-dir", type=Path, required=True, help="directory containing the four shared metadata JSON files")
    parser.add_argument("--regional-tv-cache", type=Path, help="optional temporary source for missing Hollywood/Bollywood TV subsections")
    parser.add_argument("--sections", nargs="+", choices=SECTIONS, default=SECTIONS, help="section files to write; defaults to all nine")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "backend" / "cache-seed")
    args = parser.parse_args()
    summary = migrate(
        args.source_dir.resolve(),
        args.cache_dir.resolve(),
        args.output_dir.resolve(),
        args.regional_tv_cache.resolve() if args.regional_tv_cache else None,
        tuple(args.sections),
    )
    print(json.dumps({"sections": summary, "output": str(args.output_dir.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
