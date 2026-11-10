"""Playback problem reports from the player's "Not playing? Report" prompt.

One JSON line per report goes to <data dir>/playback-reports.jsonl (on the VPS: the app's data volume).
Read them with: docker exec torrent-studio tail -n 50 /app/data/playback-reports.jsonl
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from core.settings import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter()
_ip_times: dict[str, deque[float]] = {}


class PlaybackReport(BaseModel):
    title: str = Field(default="", max_length=200)
    detail: str = Field(default="", max_length=400)   # release name / file
    player: str = Field(default="", max_length=40)
    reason: str = Field(default="", max_length=60)


@router.post("/api/playback/report")
async def report_playback(report: PlaybackReport, request: Request):
    now = time.time()
    ip = request.client.host if request.client else "unknown"
    times = _ip_times.setdefault(ip, deque())
    while times and now - times[0] > 3600:
        times.popleft()
    if len(times) >= 30:
        return {"ok": False}
    times.append(now)
    line = json.dumps({**report.model_dump(), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}, ensure_ascii=False)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with (DATA_DIR / "playback-reports.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        logger.warning("Playback report not stored: %s", exc)
        return {"ok": False}
    return {"ok": True}
