#!/usr/bin/env python3
"""Show what NexStream's player page returns for some TMDB ids (run on the VPS).

  python3 scripts/vps/probe_nexstream.py 603 1794929 1799668
Compare a film you know plays (603 = The Matrix) with titles that do not.
"""
import re, sys, urllib.error, urllib.request

for tmdb_id in sys.argv[1:] or ["603"]:
    url = "https://embedmaster.link/movie/" + tmdb_id
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)", "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            status, body = r.status, r.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read(50_000).decode("utf-8", "replace")
    except Exception as exc:
        print(tmdb_id, "ERROR", exc); continue
    text = re.sub(r"\s+", " ", re.sub(r"<(script|style)[\s\S]*?</\1>|<[^>]+>", " ", body, flags=re.I)).strip()
    title = re.search(r"<title>(.*?)</title>", body, re.I | re.S)
    print(f"{tmdb_id}: HTTP {status}, {len(body)} bytes, title={title.group(1).strip() if title else None!r}")
    print("   text:", text[:300])
