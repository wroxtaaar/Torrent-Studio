#!/usr/bin/env python3
"""Best-effort: overlay the latest published cache bundle onto the bundled seed.

Runs at container start, before the app. The bundle (cache-bundle.tar.gz + cache-bundle.json)
is published by the refresh job on the VPS to a rolling GitHub release. Any problem
(offline, bad checksum, corrupt JSON, unsafe archive) leaves the seed baked into the image
untouched, and this script always exits 0 so it can never stop the app from starting.

Env: CACHE_BUNDLE_BASE_URL (default: the cache-data release; "off" disables),
     CACHE_SEED_DIR (default /app/cache-seed).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://github.com/wroxtaaar/Torrent-Studio/releases/download/cache-data"
VERSION_FILE = ".bundle-version"
MANIFEST = "cache-bundle.json"
BUNDLE = "cache-bundle.tar.gz"
MAX_BYTES = 120 * 1024 * 1024


def _get(url: str, timeout: float, limit: int = MAX_BYTES) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "torrent-studio-cache-fetch/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("download too large")
    return data


def _safe_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    members = []
    for m in tar.getmembers():
        parts = Path(m.name).parts
        if m.isdir():
            continue
        if not m.isreg() or m.name.startswith("/") or ".." in parts:
            raise ValueError(f"unsafe archive member: {m.name}")
        members.append(m)
    return members


def apply_bundle(seed: Path, base: str) -> str:
    base = base.rstrip("/")
    manifest = json.loads(_get(f"{base}/{MANIFEST}", 10, 1024 * 1024))
    version = str(manifest["version"])
    version_path = seed / VERSION_FILE
    if version_path.is_file() and version_path.read_text().strip() == version:
        return f"already at {version}"

    blob = _get(f"{base}/{BUNDLE}", 90)
    if hashlib.sha256(blob).hexdigest() != manifest["sha256"]:
        raise ValueError("checksum mismatch")

    with tempfile.TemporaryDirectory(prefix="cache-bundle-", dir=str(seed.parent)) as tmp:
        stage = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            members = _safe_members(tar)
            for m in members:
                dest = stage / m.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
        for f in stage.rglob("*.json"):  # refuse to install anything that does not parse
            json.loads(f.read_text(encoding="utf-8"))
        if not any(stage.glob("*.json")):
            raise ValueError("bundle has no catalogue files")

        # Replace the pre-split pages as a unit. In a container image the old `pages` directory sits in a
        # read-only lower layer and cannot be renamed (EXDEV), so build the new one beside it, delete
        # the old one, and only rename the directory we just created ourselves.
        if (stage / "pages").is_dir():
            new_pages = seed / "pages.new"
            shutil.rmtree(new_pages, ignore_errors=True)
            shutil.copytree(stage / "pages", new_pages)
            shutil.rmtree(seed / "pages", ignore_errors=True)
            os.rename(new_pages, seed / "pages")
        for f in stage.rglob("*"):
            if f.is_file() and f.relative_to(stage).parts[0] != "pages":
                dest = seed / f.relative_to(stage)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))  # falls back to copy when a rename is not possible
    version_path.write_text(version)
    return f"installed {version}"


def main() -> int:
    base = os.getenv("CACHE_BUNDLE_BASE_URL", DEFAULT_BASE).strip()
    if not base or base.lower() in ("off", "false", "0", "none"):
        print("cache bundle: disabled")
        return 0
    seed = Path(os.getenv("CACHE_SEED_DIR", "/app/cache-seed"))
    try:
        print("cache bundle:", apply_bundle(seed, base))
    except Exception as exc:  # never block startup
        print(f"cache bundle: skipped ({type(exc).__name__}: {exc}); using the seed baked into the image")
    return 0


if __name__ == "__main__":
    sys.exit(main())
