"""Moved out of main.py (see docs/main-split-plan.md)."""

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from core.cache_diagnostics import _InstrumentedAsyncClient, _record_cache_event
from core.settings import (
    CACHE_FIRST,
    CACHE_ONLY_MODE,
    TMDB_API_KEYS,
    TMDB_IMAGE_BASE,
    TMDB_READ_ACCESS_TOKENS,
    WATCHMODE_API_KEYS,
    _CACHE_SEED_DIR,
    _split_env_keys,
    data_file,
    logger,
    stored_ttl,
)
from metadata.tmdb import _tmdb_get_json, _watchmode_get

router = APIRouter()


_POSTER_CACHE_SECONDS = stored_ttl(6 * 60 * 60)
# Titles with no poster are not asked about again for hours when cache-first is on.
_POSTER_NEGATIVE_CACHE_SECONDS = 6 * 60 * 60 if CACHE_FIRST else 2 * 60
_CINEMETA_BASE_URL = "https://v3-cinemeta.strem.io"
_poster_cache: dict[str, tuple[float, str | None]] = {}
_poster_inflight: dict[str, asyncio.Task[str | None]] = {}


def _poster_normalize_title(value: str) -> str:
    value = str(value or "").lower().replace("’", "'")
    # Torrent sources frequently vary only in punctuation/spelling. Treat
    # possessives as the same words and normalize common title variants.
    value = value.replace("&", " and ")
    value = value.replace("'", "")
    tokens = re.findall(r"[a-z0-9]+", value)
    token_aliases = {
        "v": "vs",
        "vs": "vs",
        "carribean": "caribbean",
    }
    tokens = [token_aliases.get(token, token) for token in tokens]
    normalized = " ".join(tokens).strip()
    return re.sub(r"^(?:the|a|an)\s+", "", normalized)


def _poster_title_matches(wanted: str, candidate: str) -> bool:
    """Accept only exact normalized titles to avoid unrelated poster artwork."""
    return bool(wanted and candidate and wanted == candidate)

def _poster_prepare_lookup_title(title: str, year: str = "") -> str:
    """Strip common release artifacts before querying poster providers."""
    value = str(title or "").strip()
    clean_year = str(year or "").strip()

    # The frontend can send both "(YEAR)" inside title and year=YEAR.
    if clean_year:
        value = re.sub(
            rf"\s*[\(\[\-:]?\s*{re.escape(clean_year)}\s*[\)\]]?\s*$",
            "",
            value,
            flags=re.I,
        )

    # Frontend poster candidates can end with a lone opening delimiter after
    # removing release information (e.g. "Batman Returns (").
    value = value.rstrip(" ([{").strip(" -._")

    # Strip season/episode information and everything after it. This lets a
    # series release such as "Batman The Animated Series S03E05 Time Out of Joint"
    # resolve to the series poster instead of treating the episode title as a movie.
    value = re.sub(
        r"\s+S\d{1,2}(?:E\d{1,3})?\b.*$",
        "",
        value,
        flags=re.I,
    ).strip(" -._([")

    return value.strip()

def _poster_title_aliases(title: str, year: str = "") -> list[str]:
    """Return provider-friendly title aliases for common torrent shorthand."""
    clean_title = str(title or "").strip()
    clean_year = str(year or "").strip()
    normalized = _poster_normalize_title(clean_title)
    aliases = [clean_title] if clean_title else []

    # Torrent sources often shorten sequel titles to a franchise number.
    # Keep this deliberately narrow so numeric titles do not create broad false matches.
    pirates_sequels = {
        "1": "Pirates of the Caribbean: The Curse of the Black Pearl",
        "2": "Pirates of the Caribbean: Dead Man's Chest",
        "3": "Pirates of the Caribbean: At World's End",
        "4": "Pirates of the Caribbean: On Stranger Tides",
        "5": "Pirates of the Caribbean: Dead Men Tell No Tales",
    }
    match = re.fullmatch(r"pirates of the caribbean ([1-5])", normalized)
    if match:
        alias = pirates_sequels[match.group(1)]
        if alias not in aliases:
            aliases.append(alias)

    # Common LimeTorrents naming variants differ from catalog titles. These
    # explicit aliases preserve exact matching and do not reopen broad substring
    # matches that previously returned unrelated artwork.
    known_aliases = {
        "avengers 2": ("Avengers: Age of Ultron", "2015"),
        "marvels the avengers": ("The Avengers", "2012"),
        "marvel s the avengers": ("The Avengers", "2012"),
        "superman the movie": ("Superman", "1978"),
        "superman movie": ("Superman", "1978"),
    }
    known = known_aliases.get(normalized)
    if known:
        alias, expected_year = known
        if not clean_year or clean_year == expected_year:
            if alias not in aliases:
                aliases.append(alias)

    # Cinemeta/IMDb listings may use the film's full subtitle instead of its
    # marketed short title. These remain exact normalized-title matches.
    if normalized == "birds of prey" and (not clean_year or clean_year == "2020"):
        for alias in (
            "Birds of Prey: And the Fantabulous Emancipation of One Harley Quinn",
            "Birds of Prey (and the Fantabulous Emancipation of One Harley Quinn)",
        ):
            if alias not in aliases:
                aliases.append(alias)

    return aliases

def _poster_title_parts(raw_title: str) -> tuple[str, str]:
    """Extract the movie title/year while removing common release-name debris."""
    value = str(raw_title or "").replace(".", " ").replace("_", " ")
    # Release helpers often append the real release year after the title
    # (e.g. "Wonder Woman 1984 2020"). Prefer the last year token so a year
    # that is part of the title is preserved.
    year_matches = list(re.finditer(r"\b((?:19|20)\d{2})\b", value))
    year_match = year_matches[-1] if year_matches else None
    year = year_match.group(1) if year_match else ""

    if year_match:
        value = value[:year_match.start()]

    # Clean bracketed tags before splitting on codec/quality markers. Doing
    # this in the opposite order leaves a dangling "[" in titles such as
    # "The Avengers 2 [1080p]", which then prevents an exact poster match.
    value = re.sub(r"\[[^\]]*(?:\]|$)", " ", value)
    value = re.sub(r"\([^)]*(?:\)|$)", " ", value)

    if not year_match:
        value = re.split(
            r"\b(?:2160p|1440p|1080p|720p|576p|480p|4k|8k|"
            r"web[- ]?dl|web[- ]?rip|webrip|bluray|brrip|hdrip|"
            r"dvdrip|dvd|cam|hdcam|telesync|telecine|scr|r5|r6|"
            r"x264|x265|h264|h265|hevc|xvid|divx|dts|aac|ac3|ddp|"
            r"eng|english|nlsub|proper|repack|remux|hdr10|hdr)\b",
            value,
            maxsplit=1,
            flags=re.I,
        )[0]

    # A few common LimeTorrents uploader tags don't have a preceding codec
    # marker, so remove them if they remain as the final token/group.
    value = re.sub(
        r"\s+(?:BlueLady(?:RG)?|Jaybob|HAGGiS|Voltage|DTRG|DOCUMENT|ViSiON|"
        r"SONiDO|SAiMORNY|LTT)$",
        "",
        value,
        flags=re.I,
    )
    value = re.sub(r"\s+", " ", value).strip(" -._[](){}")
    return value, year


def _poster_url_for_release(raw_title: str) -> str:
    title, year = _poster_title_parts(raw_title)
    if not title:
        return ""
    return f"/api/poster?{urlencode({'title': title, 'year': year})}"


def _canonical_catalogue_poster_url(item: dict[str, Any]) -> str:
    """Build a poster URL from canonical catalogue metadata, not a torrent filename."""
    # Keep a known-good TMDB CDN URL when the catalogue already has one. The old
    # rewrite replaced these working image URLs with a title-search endpoint that
    # can return 404, leaving the whole poster area blank.
    existing = str(item.get("posterUrl") or item.get("poster_url") or "").strip()
    if existing:
        try:
            parts = urlsplit(existing)
            if (
                parts.scheme in {"http", "https"}
                and (parts.hostname or "").casefold() == "image.tmdb.org"
                and "/t/p/" in parts.path
            ):
                return existing
        except Exception:
            pass
    poster_path = str(item.get("poster_path") or item.get("posterPath") or "").strip()
    if poster_path.startswith("/"):
        return "https://image.tmdb.org/t/p/w500" + poster_path

    title = str(
        item.get("marvelCatalogueTitle")
        or item.get("catalogueTitle")
        or item.get("mediaTitle")
        or item.get("title")
        or ""
    ).strip()
    if not title:
        return ""
    year = str(item.get("year") or "").strip()

    # These cached release names previously resolved to unrelated poster art.
    # Pin them to canonical TMDB poster files for the exact title/year.
    poster_key_title = re.sub(r"\[[^\]]*(?:\]|$)", " ", title)
    poster_key_title = re.sub(r"\([^)]*(?:\)|$)", " ", poster_key_title)
    if year:
        poster_key_title = re.sub(rf"\s*{re.escape(year)}\s*$", "", poster_key_title)
    poster_key_title = re.split(
        r"\b(?:2160p|1440p|1080p|720p|576p|480p|4k|8k|3d|uhd|hdrip|webrip|web[- ]?dl|bluray|blu[- ]?ray|brrip|bdrip|hdtv|x264|x265|h264|h265|hevc)\b",
        poster_key_title,
        maxsplit=1,
        flags=re.I,
    )[0]
    poster_key = re.sub(r"[^a-z0-9]+", "", poster_key_title.casefold())
    if year == "2014" and poster_key in {"theamazingspiderman2", "amazingspiderman2"}:
        return "https://image.tmdb.org/t/p/w500/bU7nTmvmy0h3VUP01v1T2imgH6N.jpg"
    if year == "2020" and poster_key == "wonderwoman1984":
        return "https://image.tmdb.org/t/p/w500/8UlWHLMpgZm9bx6QYh0NFoq67TZ.jpg"

    params = {"title": title}
    if year:
        params["year"] = year
    return "/api/poster?" + urlencode(params)


_EXCLUDED_FRANCHISE_TITLE_KEYS = {
    "avengersconfidentialblackwidowpunisher",
    "ironmanrisetechnovore",
    "nextavengersheroesoftomorrow",
}


def _catalogue_row_has_3d_quality(item: dict[str, Any]) -> bool:
    marker = re.compile(r"(?:^|[^a-z0-9])3[ ._-]*d(?:$|[^a-z0-9])", re.I)
    for field in ("quality", "title", "releaseName", "qualityLabel", "resolution"):
        if marker.search(str(item.get(field) or "")):
            return True
    return False


def _catalogue_row_is_excluded_franchise_title(item: dict[str, Any]) -> bool:
    for field in ("catalogueTitle", "marvelCatalogueTitle", "mediaTitle", "title"):
        raw = str(item.get(field) or "").strip()
        if not raw:
            continue
        normalized = re.sub(r"[^a-z0-9]+", "", raw.casefold())
        if any(normalized.startswith(excluded) for excluded in _EXCLUDED_FRANCHISE_TITLE_KEYS):
            return True
    return False


def _cached_catalogue_year(item: Any) -> int:
    if not isinstance(item, dict):
        return 0
    try:
        year = int(item.get("year") or 0)
        if 1880 <= year <= 2100:
            return year
    except (TypeError, ValueError):
        pass
    for field in ("catalogueTitle", "marvelCatalogueTitle", "mediaTitle", "title"):
        matches = re.findall(r"\b((?:19|20)\d{2})\b", str(item.get(field) or ""))
        if matches:
            try:
                return int(matches[-1])
            except (TypeError, ValueError):
                continue
    return 0


def _sort_cached_catalogue_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> tuple[int, str, int]:
        title = str(item.get("catalogueTitle") or item.get("marvelCatalogueTitle") or item.get("mediaTitle") or item.get("title") or "")
        normalized = re.sub(r"[^a-z0-9]+", "", title.casefold())
        try:
            seeders = int(float(item.get("seeders") or 0))
        except (TypeError, ValueError):
            seeders = 0
        return (-_cached_catalogue_year(item), normalized, -seeders)
    return sorted(results, key=key)


async def _cinemeta_poster_lookup(title: str, year: str = "") -> str | None:
    """Resolve title/year through Cinemeta's catalog, then use its stable ID metadata."""
    clean_title = str(title or "").strip()
    clean_year = str(year or "").strip()
    if not clean_title:
        return None

    title_aliases = _poster_title_aliases(clean_title, clean_year)
    wanted_titles = [_poster_normalize_title(value) for value in title_aliases]
    queries = []
    for alias in title_aliases:
        for query_value in (
            f"{alias} {clean_year}".strip(),
            alias,
        ):
            if query_value and query_value not in queries:
                queries.append(query_value)

    try:
        async with _InstrumentedAsyncClient(timeout=4, follow_redirects=True) as client:
            for media_type in ("movie", "series"):
                for query_value in queries:
                    encoded = quote(query_value, safe="")
                    response = await client.get(
                        f"{_CINEMETA_BASE_URL}/catalog/{media_type}/top/search={encoded}.json",
                        headers={"Accept": "application/json", "User-Agent": "TorrentStudio/1.0"},
                    )
                    if response.status_code != 200:
                        continue

                    data = response.json()
                    metas = data.get("metas") if isinstance(data, dict) else None
                    if not isinstance(metas, list):
                        continue

                    candidates: list[tuple[int, str, str]] = []
                    for row in metas:
                        if not isinstance(row, dict):
                            continue
                        name = str(row.get("name") or "").strip()
                        candidate = _poster_normalize_title(name)
                        poster = str(row.get("poster") or "").strip()
                        imdb_id = str(row.get("id") or "").strip()
                        if not name or not any(_poster_title_matches(wanted, candidate) for wanted in wanted_titles):
                            continue

                        candidate_year = str(
                            row.get("releaseInfo")
                            or row.get("year")
                            or ""
                        ).strip()

                        # Once the torrent/search result gives us a year, do not
                        # allow a different-year title just because its name is a
                        # fuzzy/contained match (e.g. "Justice League" 2017 must
                        # never satisfy "Justice League: War" 2014).
                        if clean_year:
                            candidate_year_value = candidate_year[:4]
                            if not candidate_year_value or candidate_year_value != clean_year:
                                continue

                        score = 100
                        if clean_year and candidate_year:
                            if candidate_year == clean_year or candidate_year.startswith(clean_year):
                                score += 120
                            else:
                                score -= 80
                        if poster:
                            score += 30
                        if imdb_id.startswith("tt"):
                            score += 10
                        candidates.append((score, poster, imdb_id))

                    if not candidates:
                        continue

                    candidates.sort(key=lambda item: item[0], reverse=True)
                    _score, poster, imdb_id = candidates[0]
                    if poster:
                        return poster

                    if imdb_id.startswith("tt"):
                        meta_response = await client.get(
                            f"{_CINEMETA_BASE_URL}/meta/{media_type}/{quote(imdb_id, safe='')}.json",
                            headers={"Accept": "application/json", "User-Agent": "TorrentStudio/1.0"},
                        )
                        if meta_response.status_code == 200:
                            meta_data = meta_response.json()
                            meta = meta_data.get("meta") if isinstance(meta_data, dict) else None
                            poster = str(meta.get("poster") or "").strip() if isinstance(meta, dict) else ""
                            if poster:
                                return poster
    except Exception:
        pass

    return None


async def _tmdb_poster_lookup(title: str, year: str = "") -> str | None:
    """Resolve an exact-title poster from TMDB movies or TV series.

    Torrent releases often include episode numbers, while the poster belongs to
    the parent series. Search both media types and only accept normalized exact
    title matches; this avoids returning artwork for a loosely related title.
    """
    if not (TMDB_READ_ACCESS_TOKENS or TMDB_API_KEYS):
        return None

    clean_title = str(title or "").strip()
    clean_year = str(year or "").strip()
    if not clean_title:
        return None

    # Strip common season/episode suffixes so "Lanterns S01E08" resolves to
    # the series "Lanterns", not a movie with a similar name.
    search_title = re.sub(
        r"\s+(?:s\d{1,2}e\d{1,3}|season\s+\d{1,2}(?:\s+episode\s+\d{1,3})?|\d{1,2}x\d{1,3})\b.*$",
        "",
        clean_title,
        flags=re.IGNORECASE,
    ).strip() or clean_title
    aliases = _poster_title_aliases(search_title, clean_year)
    wanted_titles = {_poster_normalize_title(alias) for alias in aliases if alias}
    params_base: dict[str, Any] = {"include_adult": "false", "language": "en-US", "page": 1}

    async def search_media(media_type: str, alias: str) -> list[tuple[float, str]]:
        params = dict(params_base)
        params["query"] = alias
        if clean_year.isdigit() and len(clean_year) == 4:
            params["year" if media_type == "movie" else "first_air_date_year"] = clean_year
        try:
            data = await _tmdb_get_json(f"search/{media_type}", params)
        except Exception as exc:
            logger.debug("TMDB %s poster search failed for '%s': %s", media_type, alias, type(exc).__name__)
            return []

        candidates: list[tuple[float, str]] = []
        title_keys = ("title", "original_title") if media_type == "movie" else ("name", "original_name")
        date_key = "release_date" if media_type == "movie" else "first_air_date"
        for row in data.get("results") or []:
            if not isinstance(row, dict):
                continue
            name = next((str(row.get(key) or "").strip() for key in title_keys if row.get(key)), "")
            normalized = _poster_normalize_title(name)
            date_value = str(row.get(date_key) or "").strip()
            candidate_year = date_value[:4] if re.match(r"^\d{4}-\d{2}-\d{2}$", date_value) else ""
            poster_path = str(row.get("poster_path") or "").strip()
            if not name or not poster_path or normalized not in wanted_titles:
                continue
            if clean_year and candidate_year and candidate_year != clean_year:
                continue
            score = 100.0
            if normalized == _poster_normalize_title(search_title):
                score += 100
            if clean_year and candidate_year == clean_year:
                score += 100
            score += float(row.get("vote_average") or 0)
            score += min(float(row.get("vote_count") or 0), 10000) / 1000
            candidates.append((score, poster_path))
        return candidates

    try:
        for alias in aliases[:4]:
            # Both endpoints are independent and fast to query concurrently.
            movie_candidates, tv_candidates = await asyncio.gather(
                search_media("movie", alias),
                search_media("tv", alias),
            )
            candidates = movie_candidates + tv_candidates
            if candidates:
                candidates.sort(key=lambda item: item[0], reverse=True)
                return TMDB_IMAGE_BASE + candidates[0][1]
    except Exception as exc:
        logger.debug("TMDB poster lookup failed for '%s (%s)': %s", clean_title, clean_year, type(exc).__name__)
    return None

_BUNDLED_POSTERS: dict[str, str] | None = None


_POSTER_RUNTIME_FILE = Path(os.getenv("POSTER_LOOKUP_CACHE_FILE", data_file("poster_lookup_cache.json")))
_RUNTIME_POSTERS: dict[str, str] | None = None


def _runtime_posters() -> dict[str, str]:
    """Posters found by earlier live lookups; persisted so a restart does not repeat them."""
    global _RUNTIME_POSTERS
    if _RUNTIME_POSTERS is None:
        loaded: dict[str, str] = {}
        try:
            raw = json.loads(_POSTER_RUNTIME_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                loaded = {str(k): str(v) for k, v in raw.items() if v}
        except (OSError, ValueError, TypeError):
            pass
        _RUNTIME_POSTERS = loaded
    return _RUNTIME_POSTERS


def _remember_poster(cache_key: str, url: str) -> None:
    posters = _runtime_posters()
    if posters.get(cache_key) == url:
        return
    posters[cache_key] = url
    try:
        _POSTER_RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_path = _POSTER_RUNTIME_FILE.with_name(_POSTER_RUNTIME_FILE.name + ".tmp")
        temp_path.write_text(json.dumps(posters, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_path, _POSTER_RUNTIME_FILE)
    except OSError as exc:
        logger.info("Could not persist poster lookup cache: %s", exc)


def _bundled_poster(clean_title: str, clean_year: str) -> str | None:
    """Poster URLs harvested from the bundled caches (no network)."""
    global _BUNDLED_POSTERS
    if _BUNDLED_POSTERS is None:
        loaded: dict[str, str] = {}
        try:
            for title, year, url in json.loads((_CACHE_SEED_DIR / "poster_map.json").read_text(encoding="utf-8")):
                loaded.setdefault(f"{_poster_normalize_title(title)}|{year}", url)
        except (OSError, ValueError, TypeError):
            pass
        _BUNDLED_POSTERS = loaded
    return _BUNDLED_POSTERS.get(f"{_poster_normalize_title(clean_title)}|{clean_year}")


async def _watchmode_poster_lookup(title: str, year: str = "") -> str | None:
    """Use Watchmode only when configured; accept only exact title/year matches."""
    if CACHE_ONLY_MODE or not WATCHMODE_API_KEYS:
        return None
    clean_title = str(title or "").strip()
    clean_year = str(year or "").strip()
    if not clean_title:
        return None

    for alias in _poster_title_aliases(clean_title, clean_year)[:3]:
        try:
            response = await _watchmode_get(
                "/search/",
                params={"search_field": "name", "search_value": alias, "types": "movie,tv"},
                timeout=5.0,
            )
            if response is None or response.status_code != 200:
                continue
            data = response.json()
            rows = data.get("title_results") if isinstance(data, dict) else []
            matches = []
            wanted = _poster_normalize_title(alias)
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or row.get("title") or "").strip()
                candidate = _poster_normalize_title(name)
                candidate_year = str(row.get("year") or "").strip()[:4]
                if not name or candidate != wanted:
                    continue
                if clean_year and candidate_year != clean_year:
                    continue
                if not row.get("id"):
                    continue
                matches.append(row)
            if not matches:
                continue
            details = await asyncio.gather(*[
                _watchmode_get(f"/title/{int(row['id'])}/details/",
                    timeout=5.0)
                for row in matches[:2]
            ])
            for detail_response in details:
                if detail_response is None or detail_response.status_code != 200:
                    continue
                detail = detail_response.json()
                if not isinstance(detail, dict):
                    continue
                poster = str(detail.get("posterLarge") or detail.get("posterMedium") or detail.get("poster") or "").strip()
                if poster.startswith("https://") or poster.startswith("http://"):
                    return poster
        except Exception as exc:
            logger.debug("Watchmode poster lookup failed for '%s (%s)': %s", clean_title, clean_year, type(exc).__name__)
    return None


async def _omdb_poster_lookup(title: str, year: str = "") -> str | None:
    """Use OMDb as a low-priority fallback with strict title/year validation."""
    if CACHE_ONLY_MODE:
        return None
    keys = _split_env_keys(os.getenv("OMDB_API_KEYS", ""), os.getenv("OMDB_API_KEY", ""))
    if not keys:
        return None
    clean_title = str(title or "").strip()
    clean_year = str(year or "").strip()
    if not clean_title:
        return None

    aliases = _poster_title_aliases(clean_title, clean_year)[:3]
    async with _InstrumentedAsyncClient(timeout=httpx.Timeout(5.0, connect=3.0), follow_redirects=True) as client:
        for alias in aliases:
            for key in keys:
                try:
                    params = {"apikey": key, "t": alias, "type": "movie"}
                    if clean_year:
                        params["y"] = clean_year
                    response = await client.get("https://www.omdbapi.com/", params=params)
                    if response.status_code != 200:
                        continue
                    data = response.json()
                    if not isinstance(data, dict) or str(data.get("Response") or "").lower() != "true":
                        continue
                    candidate = _poster_normalize_title(str(data.get("Title") or ""))
                    candidate_year = str(data.get("Year") or "").strip()[:4]
                    if candidate != _poster_normalize_title(alias):
                        continue
                    if clean_year and candidate_year != clean_year:
                        continue
                    poster = str(data.get("Poster") or "").strip()
                    if poster.startswith(("https://", "http://")) and poster.casefold() != "n/a":
                        return poster
                except Exception as exc:
                    logger.debug("OMDb poster lookup failed for '%s (%s)': %s", clean_title, clean_year, type(exc).__name__)
    return None


async def _poster_lookup_uncached(clean_title: str, clean_year: str, cache_key: str) -> str | None:
    # Check the bundled poster index before any network lookup, even when live
    # metadata is enabled. It contains verified TMDB poster URLs and avoids
    # repeated title-search requests (or blank posters after upstream timeouts).
    bundled = _bundled_poster(clean_title, clean_year)
    if bundled:
        _poster_cache[cache_key] = (time.time(), bundled)
        return bundled
    learned = _runtime_posters().get(cache_key)
    if learned:
        _poster_cache[cache_key] = (time.time(), learned)
        return learned
    now = time.time()
    if CACHE_ONLY_MODE:
        # Cache-only deployments never contact any poster provider (TMDB, Watchmode,
        # OMDb, IMDb suggestions, iTunes or Cinemeta).
        _poster_cache[cache_key] = (now, None)
        return None
    # Prefer TMDB's year-filtered movie results to prevent a similarly named
    # title from supplying the wrong artwork. Other sources remain fallbacks.
    poster = None if CACHE_ONLY_MODE else await _tmdb_poster_lookup(clean_title, clean_year)
    if not poster and not CACHE_ONLY_MODE:
        poster = await _watchmode_poster_lookup(clean_title, clean_year)
    if not poster and not CACHE_ONLY_MODE:
        poster = await _omdb_poster_lookup(clean_title, clean_year)

    try:
        title_aliases = _poster_title_aliases(clean_title, clean_year)
        wanted_titles = [_poster_normalize_title(value) for value in title_aliases]
        wanted_year = clean_year
        candidates: list[tuple[int, str]] = []
        async with _InstrumentedAsyncClient(timeout=4, follow_redirects=True) as client:
            for alias in title_aliases:
                query = quote((alias + " " + clean_year).strip(), safe="")
                response = await client.get(
                    f"https://v3.sg.media-imdb.com/suggestion/titles/x/{query}.json?includeVideos=0",
                    headers={"Accept": "application/json"},
                )
                if response.status_code != 200:
                    continue
                data = response.json()
                for row in data.get("d") or []:
                    if not isinstance(row, dict):
                        continue
                    image = str((row.get("i") or {}).get("imageUrl") or "").strip()
                    candidate = _poster_normalize_title(str(row.get("l") or ""))
                    candidate_year = str(row.get("y") or "")
                    # Ignore episodes, shorts, games, and other unrelated title types.
                    # Search suggestions can contain similarly named fan clips with
                    # artwork that is not the poster for the requested movie/series.
                    media_kind = str(row.get("qid") or "").lower()
                    if media_kind not in {"movie", "tvseries", "tvminiseries", "tvmovie"}:
                        continue
                    if not image or not any(_poster_title_matches(wanted, candidate) for wanted in wanted_titles):
                        continue
                    if wanted_year:
                        if not candidate_year or candidate_year != wanted_year:
                            continue
                    score = 100
                    if wanted_year and candidate_year == wanted_year:
                        score += 100
                    if str(row.get("qid") or "") == "movie":
                        score += 10
                    score += max(0, 20 - int(row.get("rank") or 20))
                    candidates.append((score, image))
                if candidates and not poster:
                    candidates.sort(key=lambda pair: pair[0], reverse=True)
                    poster = candidates[0][1]
    except Exception:
        pass

    if not poster:
        try:
            title_aliases = _poster_title_aliases(clean_title, clean_year)
            wanted_titles = [_poster_normalize_title(value) for value in title_aliases]
            wanted_year = clean_year
            candidates: list[tuple[int, str]] = []
            async with _InstrumentedAsyncClient(timeout=4, follow_redirects=True) as client:
                for alias in title_aliases:
                    response = await client.get(
                        "https://itunes.apple.com/search",
                        params={"term": (alias + " " + clean_year).strip(), "limit": "25"},
                        headers={"Accept": "application/json"},
                    )
                    if response.status_code != 200:
                        continue
                    data = response.json()
                    for row in data.get("results") or []:
                        if str(row.get("kind") or "") != "feature-movie" or not row.get("artworkUrl100"):
                            continue
                        candidate = _poster_normalize_title(str(row.get("trackName") or row.get("collectionName") or ""))
                        candidate_year = str(row.get("releaseDate") or "")[:4]
                        if not any(_poster_title_matches(wanted, candidate) for wanted in wanted_titles):
                            continue
                        if wanted_year:
                            if not candidate_year or candidate_year != wanted_year:
                                continue
                        score = 100
                        if wanted_year and candidate_year == wanted_year:
                            score += 100
                        candidates.append((score, str(row["artworkUrl100"]).replace("100x100bb", "600x600bb")))
                if candidates:
                    candidates.sort(key=lambda pair: pair[0], reverse=True)
                    poster = candidates[0][1]
        except Exception:
            pass

    # Cinemeta is intentionally last: it is a metadata/identity fallback and
    # never sits on the torrent-search critical path.
    if not poster:
        poster = await _cinemeta_poster_lookup(clean_title, clean_year)

    _poster_cache[cache_key] = (now, poster)
    if poster:
        _remember_poster(cache_key, poster)
    return poster


async def _poster_lookup(title: str, year: str = "") -> str | None:
    clean_year = str(year or "").strip()
    clean_title = _poster_prepare_lookup_title(title, clean_year)
    if not clean_title:
        return None

    cache_key = f"{_poster_normalize_title(clean_title)}|{clean_year}"
    now = time.time()
    cached = _poster_cache.get(cache_key)
    cache_ttl = _POSTER_CACHE_SECONDS if cached and cached[1] else _POSTER_NEGATIVE_CACHE_SECONDS
    if cached and now - cached[0] < cache_ttl:
        _record_cache_event("poster", "hit")
        return cached[1]

    _record_cache_event("poster", "miss")
    existing = _poster_inflight.get(cache_key)
    if existing is not None and not existing.done():
        _record_cache_event("poster", "inflight_join")
        try:
            return await asyncio.shield(existing)
        except Exception:
            return None

    task = asyncio.create_task(_poster_lookup_uncached(clean_title, clean_year, cache_key))
    _poster_inflight[cache_key] = task
    try:
        return await asyncio.shield(task)
    finally:
        if _poster_inflight.get(cache_key) is task:
            _poster_inflight.pop(cache_key, None)


# Return a lightweight redirect to the image CDN instead of proxying image bytes
# through the Render instance. The latter can time out on CDN connections and caused
# every poster to remain blank. Keep size selection here so w185 can load first.
def _poster_url_for_size(poster_url: str, size: str) -> str:
    url = str(poster_url or "").strip()
    if not url:
        return ""
    width = 185 if size == "w185" else 780
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").casefold()
        path = parts.path
        if host == "image.tmdb.org":
            # Replace the TMDB size segment without depending on a fragile regex.
            marker = "/t/p/"
            marker_index = path.find(marker)
            if marker_index >= 0:
                size_start = marker_index + len(marker)
                slash_index = path.find("/", size_start)
                if slash_index >= 0:
                    path = path[:size_start] + size + path[slash_index:]
        elif host.endswith("media-amazon.com") or host == "images-na.ssl-images-amazon.com":
            marker = "_V1_"
            marker_index = path.find(marker)
            if marker_index >= 0:
                path = path[:marker_index] + f"_V1_UX{width}_.jpg"
        elif "mzstatic.com" in host:
            path = re.sub(r"[0-9]+x[0-9]+bb", f"{width}x{width}bb", path)
        return parts._replace(path=path).geturl()
    except Exception:
        return url


@router.get("/api/poster")
async def api_poster(
    title: str = Query(..., min_length=1),
    year: str = Query(""),
    size: str = Query("w185"),
):
    poster = await _poster_lookup(title, year)
    if not poster:
        raise HTTPException(404, "Poster not found")
    size = size if size in {"w185", "w780"} else "w185"
    return RedirectResponse(
        _poster_url_for_size(poster, size),
        status_code=302,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/api/poster/resolve")
async def api_poster_resolve(title: str = Query(..., min_length=1), year: str = Query("")):
    poster = await _poster_lookup(title, year)
    if not poster:
        raise HTTPException(404, "Poster not found")
    return {"url": poster}
