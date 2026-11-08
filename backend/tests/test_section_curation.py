import json
from pathlib import Path

from catalogues.section_curation import apply_curation

SEED = Path(__file__).resolve().parents[1] / "cache-seed" / "pakistani.json"


def _titles(payload):
    return [row["title"] for row in payload["subsections"]["series"]["results"]]


def test_pakistani_curation_hides_removed_titles_and_pins_dar_e_nijaat():
    out = apply_curation("pakistani", json.loads(SEED.read_text(encoding="utf-8")))
    titles = _titles(out)
    assert titles[0] == "Dar-e-Nijaat"
    for removed in ("Daam", "Mora Piya", "Shehr-e-Zaat", "Jackson Heights", "Maat", "Ishq Gumshuda", "Khan", "Ehd-e-Wafa"):
        assert removed not in titles
    block = out["subsections"]["series"]
    assert block["totalResults"] == len(titles)
    assert block["pageOffsets"][-1] == len(titles)
    assert block["pageCount"] == (len(titles) + block["pageSize"] - 1) // block["pageSize"]


def test_curation_is_idempotent_and_leaves_other_sections_alone():
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    once = apply_curation("pakistani", payload)
    twice = apply_curation("pakistani", once)
    assert _titles(once) == _titles(twice)
    assert apply_curation("hollywood", payload) is payload
