"""Hand-curated changes applied to a section document when it is served.

The cache files in cache-seed are overwritten at container start by the published data bundle (see
maintenance/fetch_cache_bundle.py), so editing them by hand does not last. Changes listed here are applied on top of
whatever the file contains, every time the section is read.
"""
from __future__ import annotations

import copy
from typing import Any

# (title, year) pairs removed from a section's subsection.
HIDDEN: dict[tuple[str, str], frozenset[tuple[str, int]]] = {
    ("pakistani", "series"): frozenset({
        ("Daam", 2010), ("Mora Piya", 2011), ("Shehr-e-Zaat", 2012), ("Jackson Heights", 2014), ("Maat", 2011),
        ("Ishq Gumshuda", 2010), ("Meri Zaat Zarrae Benishan", 2009), ("Kahi Unkahi", 2012), ("Badi Aapa", 2012),
        ("Gul-e-Rana", 2015), ("Dhoop Kinare", 1987), ("Dhuwan", 1994), ("Tanhaiyaan", 1985),
        ("Choti Si Zindagi", 2016), ("Sar-e-Rah", 2023), ("Khan", 2017), ("Aunn Zara", 2013),
        ("Ishq Zahe Naseeb", 2019), ("Ehd-e-Wafa", 2019),
    }),
}

# Rows shown first in a subsection (kept in this order). A row already present (same tmdbId) is moved to the top.
PINNED: dict[tuple[str, str], list[dict[str, Any]]] = {
    ("pakistani", "series"): [{
        "id": 328722, "title": "Dar-e-Nijaat", "year": 2026, "releaseDate": "", "overview": "", "posterUrl": "",
        "backdropUrl": "", "rating": 0, "tmdbUrl": "https://www.themoviedb.org/tv/328722", "streamingProviders": [],
        "providerLink": "", "originalLanguage": "ur", "originCountry": ["PK"],
        "source": "TMDB + curated Pakistani drama order", "imdbRatingStatus": "not_found", "imdbRating": None,
        "imdbVotes": None, "imdbId": None, "imdbUrl": None, "tmdbId": 328722,
        "ottAvailability": {"status": "unavailable", "region": "IN", "streamingProviders": [], "rentProviders": [],
                            "buyProviders": [], "source": "TMDB"},
        "mediaType": "tv", "genres": [], "imdbCheckedAt": None, "rentProviders": [], "buyProviders": [],
    }],
}


def _year(row: dict[str, Any]) -> int:
    try:
        return int(row.get("year") or 0)
    except (TypeError, ValueError):
        return 0


def apply_curation(section: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return ``payload`` with the hidden rows removed and the pinned rows first; page counts are recomputed."""
    subsections = payload.get("subsections")
    if not isinstance(subsections, dict):
        return payload
    changed = False
    for (name, sub), hidden in HIDDEN.items():
        if name != section or sub not in subsections:
            continue
        block = subsections[sub]
        rows = [row for row in block.get("results", []) if (row.get("title"), _year(row)) not in hidden]
        pinned = [copy.deepcopy(row) for row in PINNED.get((name, sub), [])]
        pinned_ids = {str(row.get("tmdbId") or row.get("id")) for row in pinned}
        rows = pinned + [row for row in rows if str(row.get("tmdbId") or row.get("id")) not in pinned_ids]
        size = int(block.get("pageSize") or 18)
        block = dict(block)
        block["results"] = rows
        block["totalResults"] = len(rows)
        block["pageCount"] = max(1, (len(rows) + size - 1) // size)
        block["pageOffsets"] = list(range(0, len(rows), size)) + [len(rows)]
        subsections = {**subsections, sub: block}
        changed = True
    return {**payload, "subsections": subsections} if changed else payload
