"""Parse big JSON cache files once, and again only when the file changes on disk.

Several lookups read a multi-MB cache file for every single request. On a small
instance (Render free is ~0.1 CPU) that parsing dominates the response time. Callers
get a *private copy* of the part they ask for, so they can keep mutating it freely.
"""
import copy
import json
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_MEMO: dict[str, tuple[int, int, Any]] = {}


def read_json_cached(path: Path) -> Any:
    """Return the parsed JSON of `path` (shared object -- do not mutate it).

    Raises OSError / ValueError like a plain read + json.loads would.
    """
    stat = path.stat()
    key = str(path)
    with _LOCK:
        hit = _MEMO.get(key)
        if hit and hit[0] == stat.st_mtime_ns and hit[1] == stat.st_size:
            return hit[2]
    data = json.loads(path.read_text(encoding="utf-8"))
    with _LOCK:
        _MEMO[key] = (stat.st_mtime_ns, stat.st_size, data)
    return data


def private_copy(value: Any) -> Any:
    return copy.deepcopy(value)


def forget(path: Path | None = None) -> None:
    """Drop one file (or everything) from the memo; used by tests."""
    with _LOCK:
        if path is None:
            _MEMO.clear()
        else:
            _MEMO.pop(str(path), None)
