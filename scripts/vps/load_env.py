#!/usr/bin/env python3
"""Print `export` lines for an env file, keeping every line of repeated credential names.

A plain `source` keeps only the LAST of several `TMDB_READ_ACCESS_TOKEN=...` lines. Here repeated
TMDB_/WATCHMODE_/OMDB_ entries are joined with commas so all of them are used.

    eval "$(python3 load_env.py ~/.config/torrent-studio/env)"
"""
import shlex
import sys

values: dict[str, str] = {}
for raw in open(sys.argv[1], encoding="utf-8"):
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    if line.startswith("export "):
        line = line[7:].lstrip()
    key, value = line.split("=", 1)
    key, value = key.strip(), value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if key in values and key.startswith(("TMDB_", "WATCHMODE_", "OMDB_")):
        value = values[key] + "," + value
    values[key] = value
for key, value in values.items():
    print(f"export {key}={shlex.quote(value)}")
