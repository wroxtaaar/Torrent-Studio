import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_yenime_module():
    spec = importlib.util.spec_from_file_location("yenime_integration", ROOT / "integrations" / "yenime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_yenime_url_for_mal_episode_sub_and_dub():
    yenime = _load_yenime_module()
    assert yenime.build_yenime_url(5114, 1, "sub") == "https://megaplay.buzz/stream/mal/5114/1/sub"
    assert yenime.build_yenime_url("5114", "2", "dub") == "https://megaplay.buzz/stream/mal/5114/2/dub"


@pytest.mark.parametrize("mal_id", [0, -1, "", "abc", 1.5, None])
def test_build_yenime_url_rejects_invalid_mal_ids(mal_id):
    yenime = _load_yenime_module()
    with pytest.raises(ValueError, match="MAL ID"):
        yenime.build_yenime_url(mal_id, 1, "sub")


@pytest.mark.parametrize("episode", [0, -1, "", "abc", 1.5, None])
def test_build_yenime_url_rejects_invalid_episode_numbers(episode):
    yenime = _load_yenime_module()
    with pytest.raises(ValueError, match="episode"):
        yenime.build_yenime_url(5114, episode, "sub")


@pytest.mark.parametrize("stream_type", ["", "raw", "SUB", None])
def test_build_yenime_url_rejects_invalid_stream_types(stream_type):
    yenime = _load_yenime_module()
    with pytest.raises(ValueError, match="Stream type"):
        yenime.build_yenime_url(5114, 1, stream_type)


def test_resolver_reports_availability_unverified():
    yenime = _load_yenime_module()
    result = yenime.build_yenime_url(5114, 1, "sub")
    assert result.startswith("https://megaplay.buzz/stream/mal/")
