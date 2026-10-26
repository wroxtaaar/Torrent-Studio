#!/usr/bin/env python3
"""Collect the NexStream failure reports users sent from the site and write nexstream_failures.json.

Reports are comments on one GitHub issue (see integrations/nexstream_reports.py). This reads them with
the `gh` CLI, so the VPS needs no extra credentials. The file is rebuilt from the issue every run, so the
issue itself is the durable store. A title counts as failing once it has NEXSTREAM_FAILURE_MIN_REPORTS
reports (default 1: a single report counts) and its newest one is younger than NEXSTREAM_FAILURE_DAYS (default 30), after which
it is given another chance.

    python maintenance/pull_nexstream_reports.py OUTPUT_DIR
Environment: NEXSTREAM_REPORT_REPO (default wroxtaaar/Torrent-Studio), NEXSTREAM_REPORT_ISSUE (required).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

MARKER = "nexstream-report:"


def parse_comments(comments, min_reports: int, days: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    seen: dict[int, dict] = {}
    for comment in comments:
        body = str((comment or {}).get("body") or "").strip()
        if not body.startswith(MARKER):
            continue
        try:
            data = json.loads(body[len(MARKER):])
            tmdb_id = int(data["tmdbId"])
            at = datetime.fromisoformat(str(data.get("at")).replace("Z", "+00:00"))
        except (ValueError, KeyError, TypeError):
            continue
        row = seen.setdefault(tmdb_id, {"title": "", "year": None, "reports": 0, "lastAt": at})
        row["reports"] += 1
        row["title"] = str(data.get("title") or row["title"])[:200]
        row["year"] = data.get("year") or row["year"]
        if at > row["lastAt"]:
            row["lastAt"] = at
    movies = {}
    for tmdb_id, row in seen.items():
        if row["reports"] >= min_reports and now - row["lastAt"] <= timedelta(days=days):
            movies[str(tmdb_id)] = {**row, "lastAt": row["lastAt"].strftime("%Y-%m-%dT%H:%M:%SZ")}
    return movies


def main() -> int:
    out_dir = Path(sys.argv[1])
    repo = os.getenv("NEXSTREAM_REPORT_REPO", "wroxtaaar/Torrent-Studio")
    issue = os.getenv("NEXSTREAM_REPORT_ISSUE", "").strip()
    target = out_dir / "nexstream_failures.json"
    if not issue.isdigit():
        print("NEXSTREAM_REPORT_ISSUE is not set: skipping failure reports.", flush=True)
        return 0
    try:
        raw = subprocess.run(
            ["gh", "api", "--paginate", "--slurp", f"repos/{repo}/issues/{issue}/comments?per_page=100"],
            check=True, capture_output=True, text=True, timeout=120).stdout
        comments = [c for page in json.loads(raw) for c in (page if isinstance(page, list) else [page])]
    except (subprocess.SubprocessError, ValueError, OSError) as exc:
        print(f"Could not read the failure reports ({type(exc).__name__}); keeping the previous file.", flush=True)
        return 0
    movies = parse_comments(
        comments,
        int(os.getenv("NEXSTREAM_FAILURE_MIN_REPORTS", "1")),
        int(os.getenv("NEXSTREAM_FAILURE_DAYS", "30")),
    )
    target.write_text(json.dumps({"movies": movies}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"NexStream failure reports: {len(comments)} comments -> {len(movies)} titles marked not playable.", flush=True)
    for tmdb_id, row in list(movies.items())[:30]:
        print(f"  {tmdb_id}  {row['title']} ({row['year'] or '?'})  reports={row['reports']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
