"""HD download links from a self-hosted Nuvio Streams add-on (https://github.com/tapframe/NuvioStreamsAddon).

The add-on is a separate Node service that runs next to this app (default http://localhost:7777). For one movie
it returns direct HTTP file links with the quality and size written in each stream's name/title. This module
asks it, turns the answer into a short list of quality options, and keeps the answer for a while because a
lookup takes 5-20 s (the add-on queries several sites).

Rules:
* Only called when a user opens a movie card (never by page loads or pagination).
* With NUVIO_URL unset, or the add-on down/slow/empty, the result is "unavailable" and the card simply
  shows no HD button.
* Links are returned percent-encoded and https-only; the browser downloads straight from the file host.

No FastAPI import here so it can be tested on its own.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

MAX_OPTIONS = 12
SUCCESS_TTL_S = 20 * 60      # links may expire, so do not keep them long
EMPTY_TTL_S = 10 * 60        # remember "nothing" briefly so repeated clicks do not rescrape
MAX_CACHE_ENTRIES = 500

_QUALITY = (("2160p", re.compile(r"\b(?:2160p|4k|uhd)\b", re.I)),
            ("1080p", re.compile(r"\b1080p\b", re.I)),
            ("720p", re.compile(r"\b720p\b", re.I)),
            ("480p", re.compile(r"\b(?:480p|576p)\b", re.I)))
_RANK = {"2160p": 4, "1080p": 3, "720p": 2, "480p": 1, "other": 0}
_LABEL = {"2160p": "4K", "1080p": "1080p", "720p": "720p", "480p": "480p", "other": "HD"}
_SIZE = re.compile(r"([\d.]+)\s*(TB|GB|MB|KB)\b", re.I)
_UNITS = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3, "TB": 1024 ** 4}
_TAGS = (("REMUX", re.compile(r"\bremux\b", re.I)), ("HDR", re.compile(r"\bhdr(?:10)?\+?\b", re.I)),
         ("DV", re.compile(r"\b(?:dv|dolby[ ._-]?vision)\b", re.I)), ("IMAX", re.compile(r"\bimax\b", re.I)))

Fetcher = Callable[[str], Awaitable[dict[str, Any] | None]]
Prober = Callable[[str], Awaitable[bool]]
PROBE_CONCURRENCY = 6
PLAYER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_INFLIGHT: dict[str, "asyncio.Future[list[dict[str, Any]]]"] = {}


def _quality_of(text: str) -> str:
    for name, pattern in _QUALITY:
        if pattern.search(text):
            return name
    return "other"


def _size_of(text: str) -> int:
    matches = _SIZE.findall(text or "")
    if not matches:
        return 0
    number, unit = matches[-1]
    try:
        return int(float(number) * _UNITS[unit.upper()])
    except (ValueError, OverflowError):
        return 0


def safe_url(raw: str) -> str:
    """https only, spaces/brackets in the file name percent-encoded (they break plain links)."""
    try:
        parts = urlsplit(str(raw or "").strip())
    except ValueError:
        return ""
    if parts.scheme != "https" or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/:@%+,;=~!$&'()*-._"), parts.query, ""))


def format_size(size: int) -> str:
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.1f} GB".replace(".0 GB", " GB")
    return f"{max(1, round(size / 1024 ** 2))} MB" if size else ""


def parse_streams(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Quality options from the add-on's ``{"streams": [...]}`` answer, best quality first, bigger files first."""
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for stream in (payload or {}).get("streams") or []:
        if not isinstance(stream, dict):
            continue
        url = safe_url(stream.get("url"))
        if not url or url in seen:
            continue
        name, title = str(stream.get("name") or ""), str(stream.get("title") or "")
        lines = [line.strip() for line in title.splitlines() if line.strip()]
        filename = lines[0] if lines else ""
        size = _size_of(lines[-1] if len(lines) > 1 else "") or _size_of(name)
        quality = _quality_of(f"{name} {filename}")
        tags = [tag for tag, pattern in _TAGS if pattern.search(f"{name} {filename}")]
        seen.add(url)
        options.append({
            "key": str(len(options)),
            "quality": quality,
            "label": " · ".join(part for part in (_LABEL[quality], format_size(size), " ".join(tags)) if part),
            "size": size,
            "filename": filename,
            "url": url,
        })
    options.sort(key=lambda o: (-_RANK[o["quality"]], -o["size"], o["filename"]))
    options = options[:MAX_OPTIONS]
    for index, option in enumerate(options):
        option["key"] = str(index)
    return options


async def http_fetcher(url: str, timeout_s: float = 45.0) -> dict[str, Any] | None:
    import httpx  # noqa: PLC0415 (only the live path needs it)

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(url, headers={"Accept": "application/json"})
        return response.json() if response.status_code == 200 else None
    except Exception:  # an add-on hiccup must never break the movie card
        return None


async def http_prober(url: str, timeout_s: float = 15.0) -> bool:
    """Is this file link usable right now? Asks the way a player does (open-ended range) and looks only at the status,
    so no file data is read. The file hosts are often Google Drive files that are blocked for a day once their download
    quota is used up (HTTP 403); those must not be offered."""
    import httpx  # noqa: PLC0415 (only the live path needs it)

    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True) as client:
            async with client.stream("GET", url, headers={"Range": "bytes=0-", "User-Agent": PLAYER_UA}) as response:
                return response.status_code in (200, 206)
    except Exception:
        return False


async def keep_alive(options: list[dict[str, Any]], prober: Prober) -> list[dict[str, Any]]:
    """Only the options whose link the prober accepts, in the same order (keys renumbered)."""
    gate = asyncio.Semaphore(PROBE_CONCURRENCY)

    async def check(option: dict[str, Any]) -> bool:
        async with gate:
            try:
                return bool(await prober(option["url"]))
            except Exception:
                return False

    flags = await asyncio.gather(*(check(option) for option in options))
    alive = [option for option, ok in zip(options, flags) if ok]
    for index, option in enumerate(alive):
        option["key"] = str(index)
    return alive


async def _cached(key: str, produce: Callable[[], Awaitable[list[dict[str, Any]]]], now: Callable[[], float]) -> list[dict[str, Any]]:
    """Answer from the cache, share one in-flight scrape between simultaneous clicks, remember empty answers briefly."""
    cached = _CACHE.get(key)
    if cached is not None and cached[0] > now():
        return cached[1]
    pending = _INFLIGHT.get(key)
    if pending is not None:
        return await asyncio.shield(pending)
    future: asyncio.Future[list[dict[str, Any]]] = asyncio.get_running_loop().create_future()
    _INFLIGHT[key] = future
    options: list[dict[str, Any]] = []
    try:
        options = await produce()
        if len(_CACHE) >= MAX_CACHE_ENTRIES:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = (now() + (SUCCESS_TTL_S if options else EMPTY_TTL_S), options)
        return options
    finally:
        _INFLIGHT.pop(key, None)
        if not future.done():
            future.set_result(options)


async def lookup(
    base_url: str,
    tmdb_id: str | int,
    *,
    fetcher: Fetcher | None = None,
    prober: Prober | None = None,
    now: Callable[[], float] = time.monotonic,
) -> list[dict[str, Any]]:
    """Quality options for one movie from the add-on at ``base_url``; ``[]`` when not configured, not found, or unavailable.

    Links that are not usable right now (e.g. a Google Drive download quota used up) are dropped by probing each one."""
    base = str(base_url or "").strip().rstrip("/")
    tmdb = str(tmdb_id or "").strip()
    if not base or not tmdb.isdigit():
        return []

    async def produce() -> list[dict[str, Any]]:
        options = parse_streams(await (fetcher or http_fetcher)(f"{base}/stream/movie/tmdb:{tmdb}.json"))
        return await keep_alive(options, prober or http_prober) if options else []

    return await _cached(tmdb, produce, now)


def _options_from_api(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Options out of another Torrent Studio's /api/nuvio/streams answer. Re-validated: only https links, known fields."""
    options: list[dict[str, Any]] = []
    for raw in (payload or {}).get("options") or []:
        if not isinstance(raw, dict):
            continue
        url = safe_url(raw.get("url"))
        quality = raw.get("quality") if raw.get("quality") in _RANK else "other"
        if not url:
            continue
        try:
            size = max(0, int(raw.get("size") or 0))
        except (TypeError, ValueError):
            size = 0
        options.append({"key": str(len(options)), "quality": quality, "label": str(raw.get("label") or "")[:120], "size": size,
                        "filename": str(raw.get("filename") or "")[:300], "url": url})
    return options[:MAX_OPTIONS]


async def remote_lookup(
    api_base_url: str,
    tmdb_id: str | int,
    *,
    fetcher: Fetcher | None = None,
    now: Callable[[], float] = time.monotonic,
) -> list[dict[str, Any]]:
    """Same options, asked from another Torrent Studio that has the add-on (e.g. Render asking the VPS).

    ``api_base_url`` is that app's address, e.g. http://203.0.113.5:3000 . The answer is cached here as well."""
    base = str(api_base_url or "").strip().rstrip("/")
    tmdb = str(tmdb_id or "").strip()
    if not base or not tmdb.isdigit():
        return []

    async def produce() -> list[dict[str, Any]]:
        return _options_from_api(await (fetcher or http_fetcher)(f"{base}/api/nuvio/streams?tmdb_id={tmdb}"))

    return await _cached("remote:" + tmdb, produce, now)


def clear_cache() -> None:
    _CACHE.clear()
    _INFLIGHT.clear()


__all__ = ["clear_cache", "format_size", "keep_alive", "lookup", "parse_streams", "remote_lookup", "safe_url"]
