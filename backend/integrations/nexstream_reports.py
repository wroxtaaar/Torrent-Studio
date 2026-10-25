"""Shared NexStream failure reports.

The browser reports a title whose NexStream playback does not work. Render's free plan keeps no disk, so
each report is forwarded as a comment on one GitHub issue (the durable store). The VPS refresh reads
those comments (maintenance/pull_nexstream_reports.py) and the cache builder stops showing Play, or the
whole title when it has no torrent, for titles reported enough times.

Render env (all three needed, otherwise reports are only kept in memory until the next restart):
  NEXSTREAM_REPORT_TOKEN   fine-grained GitHub token with Issues: read and write on the repository
  NEXSTREAM_REPORT_REPO    e.g. wroxtaaar/Torrent-Studio
  NEXSTREAM_REPORT_ISSUE   issue number whose comments hold the reports
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()
MARKER = "nexstream-report:"
_FORWARD_EVERY_SECONDS = 24 * 3600  # one comment per title per day per server process
_MAX_FORWARDS_PER_DAY = 300
_MAX_PER_IP_PER_HOUR = 30
_forwarded: dict[int, float] = {}
_forward_times: deque[float] = deque()
_ip_times: dict[str, deque[float]] = {}
memory_reports: dict[int, dict] = {}


class NexStreamReport(BaseModel):
    tmdbId: int = Field(gt=0, lt=100_000_000)
    title: str = Field(default="", max_length=200)
    year: int | None = Field(default=None, ge=1870, le=2100)
    reason: str = Field(default="player_not_working", pattern="^(resolve_failed|player_not_working)$")


def _allowed(ip: str, now: float) -> bool:
    times = _ip_times.setdefault(ip, deque())
    while times and now - times[0] > 3600:
        times.popleft()
    if len(times) >= _MAX_PER_IP_PER_HOUR:
        return False
    times.append(now)
    return True


async def _forward(report: NexStreamReport) -> bool:
    token = os.getenv("NEXSTREAM_REPORT_TOKEN", "").strip()
    repo = os.getenv("NEXSTREAM_REPORT_REPO", "").strip()
    issue = os.getenv("NEXSTREAM_REPORT_ISSUE", "").strip()
    if not (token and repo and issue.isdigit()):
        return False
    body = MARKER + json.dumps({
        "tmdbId": report.tmdbId, "title": report.title, "year": report.year, "reason": report.reason,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, separators=(",", ":"))
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"https://api.github.com/repos/{repo}/issues/{issue}/comments",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                json={"body": body},
            )
        if response.status_code >= 300:
            logger.warning("NexStream report not stored: GitHub answered %s", response.status_code)
            return False
        return True
    except httpx.HTTPError as exc:
        logger.warning("NexStream report not stored: %s", type(exc).__name__)
        return False


@router.post("/api/nexstream/report")
async def report_nexstream_failure(report: NexStreamReport, request: Request):
    now = time.time()
    ip = request.client.host if request.client else "unknown"
    if not _allowed(ip, now):
        return {"ok": False, "stored": False}
    memory_reports[report.tmdbId] = {"title": report.title, "year": report.year, "at": now}
    if now - _forwarded.get(report.tmdbId, 0) < _FORWARD_EVERY_SECONDS:
        return {"ok": True, "stored": True}
    while _forward_times and now - _forward_times[0] > 86400:
        _forward_times.popleft()
    if len(_forward_times) >= _MAX_FORWARDS_PER_DAY:
        return {"ok": True, "stored": False}
    _forwarded[report.tmdbId] = now
    _forward_times.append(now)
    stored = await _forward(report)
    return {"ok": True, "stored": stored}
