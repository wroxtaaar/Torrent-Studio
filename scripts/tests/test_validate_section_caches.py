"""The section-cache validator flags torrent fields, stale stream fields and duplicates; gaps are only counted."""
import importlib.util
import json
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "validate_section_caches.py"
SPEC = importlib.util.spec_from_file_location("validate_section_caches", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_clean_rows_pass_and_gaps_are_counted():
    rows = [{"title": "A", "tmdbId": 1, "posterUrl": "/p", "overview": "o", "imdbId": "tt1"},
            {"title": "B", "tmdbId": 2}]
    problems, gaps = MODULE.check_subsection(rows)
    assert problems == []
    assert gaps["no poster"] == 1 and gaps["no overview"] == 1 and gaps["no imdbId"] == 1 and gaps["no tmdbId"] == 0


def test_torrent_stale_stream_duplicates_and_missing_titles_fail():
    rows = [{"title": "A", "tmdbId": 1, "magnetUrl": "magnet:?x"},
            {"title": "B", "tmdbId": 2, "nexStreamPlayable": False},
            {"title": "C", "tmdbId": 3}, {"title": "C", "tmdbId": 3},
            {"tmdbId": 4}]
    problems, _ = MODULE.check_subsection(rows)
    text = " | ".join(problems)
    assert "forbidden fields" in text and "magnetUrl" in text and "nexStreamPlayable" in text
    assert "duplicate" in text and "no title" in text


def test_direct_stream_broken_flag_is_allowed():
    problems, _ = MODULE.check_subsection([{"title": "A", "tmdbId": 1, "directStreamBroken": True}])
    assert problems == []


def test_self_contained_validation_requires_all_nine_api_document_shapes():
    with tempfile.TemporaryDirectory() as temporary:
        seed = Path(temporary)
        for section in MODULE.SELF_CONTAINED_SECTIONS:
            (seed / f"{section}.json").write_text(json.dumps({
                "section": section,
                "metadataSelfContained": True,
                "subsections": {},
            }), encoding="utf-8")

        assert MODULE.validate_self_contained_documents(seed) == []

        (seed / "anime.json").write_text(json.dumps({
            "section": "wrong-section",
            "metadataSelfContained": False,
            "subsections": [],
        }), encoding="utf-8")
        (seed / "dc.json").unlink()
        problems = MODULE.validate_self_contained_documents(seed)

        assert any("anime.json: section must equal" in problem for problem in problems)
        assert any("anime.json: metadataSelfContained must be true" in problem for problem in problems)
        assert any("anime.json: subsections must be an object" in problem for problem in problems)
        assert any("dc.json: cannot read valid JSON" in problem for problem in problems)
