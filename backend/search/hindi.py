"""Hindi detection for torrent release names, so Hindi releases can be searched for and listed first."""
from __future__ import annotations

import re

_HINDI = re.compile(r"(?:^|[^a-z0-9])(?:hindi|hin)(?:$|[^a-z0-9])", re.IGNORECASE)


def is_hindi(title: object) -> bool:
    return bool(_HINDI.search(str(title or "")))


def hindi_first(rows: list) -> list:
    """Stable: Hindi releases first, everything else keeps its order."""
    return sorted(rows, key=lambda row: 0 if is_hindi(row.get("title") if isinstance(row, dict) else row) else 1)
