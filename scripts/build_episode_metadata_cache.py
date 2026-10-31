#!/usr/bin/env python3
"""Build the resumable TMDB TV episode cache from the nine section catalogues.

This is an explicit offline-deployment preparation step, not an application-startup
or catalogue-refresh task. Live TMDB access requires --allow-live-tmdb.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import httpx


SECTION_FILES = (
    "hollywood.json",
    "bollywood.json",
    "marvel.json",
    "dc.json",
    "highest-rated.json",
    "korean.json",
    "pakistani.json",
    "anime.json",
    "favourites.json",
)
TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w300"


class TmdbRequestError(RuntimeError):
    def __init__(self, status_code: int | None, message: str):
        super().__init__(message)
        self.status_code = status_code


def _environment_values(*names: str) -> list[str]:
    values: list[str] = []
    for name in names:
        variants = sorted(
            (key for key in os.environ if re.fullmatch(re.escape(name) + r"_?\d+", key)),
            key=lambda key: int(re.search(r"(\d+)$", key).group(1)),
        )
        for key in (name, *variants):
            for value in re.split(r"[,;\s]+", os.getenv(key, "").replace("\\n", " ")):
                value = value.strip().strip("\"'")
                if value and value not in values:
                    values.append(value)
    return values


def catalogue_tmdb_ids(seed_dir: Path) -> list[int]:
    """Read only the nine section documents and return unique TV TMDB IDs."""
    identifiers: set[int] = set()
    for filename in SECTION_FILES:
        document_path = seed_dir / filename
        document = json.loads(document_path.read_text(encoding="utf-8"))
        subsections = document.get("subsections")
        if not isinstance(subsections, dict):
            raise ValueError(f"{document_path} has no subsection object")
        for subsection in subsections.values():
            if not isinstance(subsection, dict) or str(subsection.get("mediaType") or "").casefold() not in {
                "tv", "series", "anime",
            }:
                continue
            results = subsection.get("results")
            if not isinstance(results, list):
                raise ValueError(f"{document_path} contains a TV subsection without results")
            for row in results:
                if not isinstance(row, dict):
                    continue
                raw_id = row.get("tmdbId") or row.get("id")
                if isinstance(raw_id, bool):
                    continue
                value = str(raw_id or "").strip()
                if value.isdigit() and int(value) > 0:
                    identifiers.add(int(value))
    return sorted(identifiers)


def read_episode_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"shows": {}}
    cache = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cache, dict) or not isinstance(cache.get("shows", {}), dict):
        raise ValueError(f"Episode cache is not a valid shows document: {path}")
    cache.setdefault("shows", {})
    return cache


def write_episode_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(cache, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _retry_after_seconds(value: str | None, fallback: float) -> float:
    if value:
        try:
            return max(0.0, min(300.0, float(value)))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, min(300.0, (retry_at - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                pass
    return fallback


def _season_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    seasons: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in payload.get("seasons") or []:
        if not isinstance(item, dict):
            continue
        try:
            season_number = int(item.get("season_number", 0))
        except (TypeError, ValueError):
            continue
        if season_number <= 0 or season_number in seen:
            continue
        seen.add(season_number)
        try:
            episode_count = max(0, int(item.get("episode_count", 0)))
        except (TypeError, ValueError):
            episode_count = 0
        seasons.append({
            "seasonNumber": season_number,
            "name": str(item.get("name") or f"Season {season_number}"),
            "episodeCount": episode_count,
        })
    return sorted(seasons, key=lambda season: season["seasonNumber"])


def _episode_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_episodes = payload.get("episodes")
    if not isinstance(raw_episodes, list):
        raise ValueError("TMDB season response has no episodes list")
    episodes = []
    for item in raw_episodes:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("episode_number", 0))
        except (TypeError, ValueError):
            continue
        if number <= 0:
            continue
        still_path = str(item.get("still_path") or "").strip()
        episodes.append({
            "episodeNumber": number,
            "name": str(item.get("name") or ""),
            "overview": str(item.get("overview") or "")[:500],
            "airDate": str(item.get("air_date") or ""),
            "still": TMDB_IMAGE_BASE + still_path if still_path else None,
        })
    return sorted(episodes, key=lambda episode: episode["episodeNumber"])


async def _tmdb_get(
    client: httpx.AsyncClient,
    path: str,
    credentials: list[tuple[str, str]],
    *,
    max_attempts: int,
    sleep: Any,
) -> dict[str, Any]:
    if not credentials:
        raise TmdbRequestError(None, "TMDB credentials are not configured")
    last_status: int | None = None
    last_error = "TMDB request failed"
    for attempt in range(max_attempts):
        saw_rate_limit = False
        for credential_type, credential in credentials:
            params = {"api_key": credential} if credential_type == "key" else None
            headers = {"Accept": "application/json"}
            if credential_type == "token":
                headers["Authorization"] = "Bearer " + credential
            try:
                response = await client.get(
                    f"{TMDB_API_BASE}{path}",
                    params=params,
                    headers=headers,
                )
            except httpx.RequestError as exc:
                last_error = f"TMDB network error ({type(exc).__name__})"
                continue
            last_status = response.status_code
            if response.status_code == 200:
                payload = response.json()
                if not isinstance(payload, dict):
                    raise TmdbRequestError(502, "TMDB returned an invalid response")
                return payload
            if response.status_code == 429:
                saw_rate_limit = True
                last_error = "TMDB rate limit reached"
                retry_after = _retry_after_seconds(
                    response.headers.get("Retry-After"),
                    min(2 ** attempt, 30),
                )
                if attempt + 1 < max_attempts:
                    await sleep(retry_after)
                break
            if response.status_code in {401, 403}:
                last_error = "TMDB rejected the configured credentials"
                continue
            if response.status_code >= 500:
                last_error = f"TMDB server error (HTTP {response.status_code})"
                continue
            raise TmdbRequestError(response.status_code, f"TMDB request failed (HTTP {response.status_code})")
        else:
            saw_rate_limit = False

        if attempt + 1 < max_attempts and not saw_rate_limit:
            await sleep(min(2 ** attempt, 30))
    if last_status in {401, 403} and last_error.startswith("TMDB rejected"):
        raise TmdbRequestError(last_status, last_error)
    raise TmdbRequestError(last_status, last_error)


def _cache_show(cache: dict[str, Any], tmdb_id: int) -> dict[str, Any]:
    shows = cache.setdefault("shows", {})
    show = shows.setdefault(str(tmdb_id), {
        "tmdbId": tmdb_id,
        "seasons": [],
        "episodesBySeason": {},
    })
    if not isinstance(show, dict):
        show = {"tmdbId": tmdb_id, "seasons": [], "episodesBySeason": {}}
        shows[str(tmdb_id)] = show
    show["tmdbId"] = tmdb_id
    if not isinstance(show.get("seasons"), list):
        show["seasons"] = []
    if not isinstance(show.get("episodesBySeason"), dict):
        show["episodesBySeason"] = {}
    return show


async def build_episode_cache(
    seed_dir: Path,
    cache_path: Path,
    credentials: list[tuple[str, str]],
    *,
    concurrency: int = 3,
    max_attempts: int = 5,
    client_factory: Any = httpx.AsyncClient,
    sleep: Any = asyncio.sleep,
) -> dict[str, Any]:
    ids = catalogue_tmdb_ids(seed_dir)
    cache = read_episode_cache(cache_path)
    save_lock = asyncio.Lock()
    show_limit = asyncio.Semaphore(max(1, concurrency))
    completed = 0
    skipped = 0
    failures: list[dict[str, Any]] = []

    async def persist() -> None:
        async with save_lock:
            write_episode_cache(cache_path, cache)

    async with client_factory(
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
    ) as client:
        async def process_show(tmdb_id: int) -> None:
            nonlocal completed, skipped
            async with show_limit:
                show = _cache_show(cache, tmdb_id)
                has_season_listing = (
                    show.get("seasonsFetched") is True
                    or (isinstance(show.get("seasons"), list) and bool(show["seasons"]))
                )
                if not has_season_listing:
                    try:
                        details = await _tmdb_get(
                            client,
                            f"/tv/{tmdb_id}",
                            credentials,
                            max_attempts=max_attempts,
                            sleep=sleep,
                        )
                    except (TmdbRequestError, ValueError) as exc:
                        failures.append({"tmdbId": tmdb_id, "season": None, "error": str(exc)})
                        return
                    show["seasons"] = _season_rows(details)
                    show["seasonsFetched"] = True
                    await persist()

                seasons = _season_rows({
                    "seasons": [
                        {
                            "season_number": item.get("seasonNumber"),
                            "name": item.get("name"),
                            "episode_count": item.get("episodeCount"),
                        }
                        for item in show.get("seasons") or []
                        if isinstance(item, dict)
                    ],
                })
                show["seasons"] = seasons
                episodes_by_season = show["episodesBySeason"]
                for season in seasons:
                    season_key = str(season["seasonNumber"])
                    if season_key in episodes_by_season and isinstance(episodes_by_season[season_key], list):
                        skipped += 1
                        continue
                    try:
                        payload = await _tmdb_get(
                            client,
                            f"/tv/{tmdb_id}/season/{season['seasonNumber']}",
                            credentials,
                            max_attempts=max_attempts,
                            sleep=sleep,
                        )
                        episodes = _episode_rows(payload)
                    except (TmdbRequestError, ValueError) as exc:
                        failures.append({
                            "tmdbId": tmdb_id,
                            "season": season["seasonNumber"],
                            "error": str(exc),
                        })
                        continue
                    episodes_by_season[season_key] = episodes
                    await persist()
                    completed += 1

        await asyncio.gather(*(process_show(tmdb_id) for tmdb_id in ids))

    return {
        "showsExamined": len(ids),
        "seasonsCompleted": completed,
        "seasonsSkipped": skipped,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "backend" / "cache-seed",
        help="directory containing the nine section JSON files",
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        help="episode cache output (defaults to <seed-dir>/runtime/nexstream_episode_metadata_cache.json)",
    )
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument(
        "--allow-live-tmdb",
        action="store_true",
        help="explicitly authorize TMDB requests for this cache-building operation",
    )
    args = parser.parse_args()
    if not args.allow_live_tmdb:
        parser.error("this explicit cache builder requires --allow-live-tmdb")
    if args.concurrency < 1:
        parser.error("--concurrency must be at least 1")
    if args.max_attempts < 1:
        parser.error("--max-attempts must be at least 1")

    seed_dir = args.seed_dir.resolve()
    cache_path = args.cache_path or seed_dir / "runtime" / "nexstream_episode_metadata_cache.json"
    credentials = [
        ("key", value)
        for value in _environment_values("TMDB_API_KEYS", "TMDB_API_KEY")
    ] + [
        ("token", value)
        for value in _environment_values(
            "TMDB_READ_ACCESS_TOKENS",
            "TMDB_READ_ACCESS_TOKEN",
            "TMDB_BEARER_TOKEN",
        )
    ]
    if not credentials:
        parser.error("configure a TMDB API key or read access token before running")

    summary = asyncio.run(build_episode_cache(
        seed_dir,
        cache_path,
        credentials,
        concurrency=args.concurrency,
        max_attempts=args.max_attempts,
    ))
    print(json.dumps(summary, indent=2))
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
