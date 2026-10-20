"""Moved out of main.py (see docs/main-split-plan.md)."""

import re
import time
from collections import deque
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.cache_diagnostics import _InstrumentedAsyncClient
from core.settings import (
    FEEDBACK_GLOBAL_RATE_LIMIT,
    FEEDBACK_RATE_LIMIT,
    FEEDBACK_RATE_WINDOW_SECONDS,
    GITHUB_FEEDBACK_REPO,
    GITHUB_FEEDBACK_TOKEN,
    logger,
)

router = APIRouter()


_feedback_hits: dict[str, deque] = {}
_feedback_global_hits: deque = deque()


class FeedbackRequest(BaseModel):
    type: str
    rating: int | None = None
    message: str
    name: str | None = None


def _feedback_client_key(request: Request) -> str:
    # Render sits behind a proxy; the left-most X-Forwarded-For entry is the client.
    forwarded = str(request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _enforce_feedback_rate_limit(request: Request) -> None:
    now = time.monotonic()
    cutoff = now - FEEDBACK_RATE_WINDOW_SECONDS

    while _feedback_global_hits and _feedback_global_hits[0] < cutoff:
        _feedback_global_hits.popleft()
    if len(_feedback_global_hits) >= FEEDBACK_GLOBAL_RATE_LIMIT:
        raise HTTPException(429, "Feedback is temporarily unavailable. Please try again later.")

    key = _feedback_client_key(request)
    hits = _feedback_hits.setdefault(key, deque())
    while hits and hits[0] < cutoff:
        hits.popleft()
    if len(hits) >= FEEDBACK_RATE_LIMIT:
        raise HTTPException(429, "You have sent feedback too many times. Please try again later.")

    hits.append(now)
    _feedback_global_hits.append(now)

    # Keep the table bounded.
    if len(_feedback_hits) > 5000:
        for stale_key in [k for k, v in _feedback_hits.items() if not v or v[-1] < cutoff]:
            _feedback_hits.pop(stale_key, None)


@router.post("/api/feedback")
async def submit_feedback(body: FeedbackRequest, request: Request):
    feedback_type = str(body.type or "").strip().lower()
    if feedback_type not in {"review", "suggestion", "bug"}:
        raise HTTPException(400, "Invalid feedback type")

    message = str(body.message or "").strip()
    if len(message) < 5:
        raise HTTPException(400, "Feedback is too short")
    if len(message) > 3000:
        raise HTTPException(400, "Feedback is too long")

    name = str(body.name or "").strip()[:80]
    rating = int(body.rating) if body.rating is not None else None
    if feedback_type == "review" and (rating is None or rating < 1 or rating > 5):
        raise HTTPException(400, "A review rating from 1 to 5 is required")
    if feedback_type != "review":
        rating = None

    if not GITHUB_FEEDBACK_TOKEN:
        raise HTTPException(503, "Feedback is not configured yet")

    repo = GITHUB_FEEDBACK_REPO.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise HTTPException(500, "Feedback repository is not configured correctly")

    _enforce_feedback_rate_limit(request)

    label = {"review": "Review", "suggestion": "Suggestion", "bug": "Bug report"}[feedback_type]
    title_prefix = {"review": "Review", "suggestion": "Suggestion", "bug": "Bug report"}[feedback_type]
    title_text = message.replace("\\n", " ").strip()
    title_text = re.sub(r"\s+", " ", title_text)[:70] or "New feedback"

    if feedback_type == "review" and rating is not None:
        stars = "⭐" * rating
        title = f"{stars} {rating}/5 Review"
    else:
        title = title_prefix

    if name:
        title += f" — {name}"

    submitted_at = datetime.now(timezone.utc).isoformat()

    body_lines = [
        f"# {('⭐' * rating + ' ' + str(rating) + '/5 Review') if feedback_type == 'review' and rating is not None else label}",
        "",
    ]
    if name:
        body_lines.append(f"**👤 Name:** {name}")
    else:
        body_lines.append("**👤 Name:** Anonymous")
    if rating is not None:
        body_lines.append(f"**⭐ Rating:** {rating}/5")
    body_lines.extend([
        f"**🕒 Submitted:** {submitted_at}",
        "",
        "### 💬 Feedback",
        "",
        f"> {message.replace(chr(10), chr(10) + '> ')}",
    ])
    # The visitor IP is only used for rate limiting; it is never written to the issue.

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_FEEDBACK_TOKEN}",
        "X-GitHub-Api-Version": "2026-03-10",
        "User-Agent": "Torrent-Studio-Feedback",
    }
    try:
        async with _InstrumentedAsyncClient(timeout=12.0) as client:
            response = await client.post(
                f"https://api.github.com/repos/{repo}/issues",
                headers=headers,
                json={"title": title, "body": "\n".join(body_lines)},
            )
    except httpx.HTTPError as exc:
        logger.warning("Feedback submission failed: %s", exc)
        raise HTTPException(502, "Feedback service is temporarily unavailable")

    if response.status_code != 201:
        try:
            detail = response.json().get("message")
        except Exception:
            detail = None
        logger.warning("GitHub feedback submission failed: HTTP %s %s", response.status_code, detail or "")
        raise HTTPException(502, "Feedback could not be submitted right now")

    try:
        issue = response.json()
    except Exception:
        issue = {}
    return {"submitted": True, "issueUrl": issue.get("html_url")}
