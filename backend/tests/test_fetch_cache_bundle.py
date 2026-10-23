import hashlib, io, json, sys, tarfile, threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "maintenance"))
import fetch_cache_bundle as fcb  # noqa: E402


def make_bundle(dirpath: Path, files: dict[str, bytes], version="v1", sha=None):
    dirpath.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    blob = buf.getvalue()
    (dirpath / "cache-bundle.tar.gz").write_bytes(blob)
    (dirpath / "cache-bundle.json").write_text(json.dumps(
        {"version": version, "sha256": sha or hashlib.sha256(blob).hexdigest()}))


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "www"
    root.mkdir()
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield root, f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def seed_dir(tmp_path):
    seed = tmp_path / "seed"
    (seed / "pages").mkdir(parents=True)
    (seed / "pages" / "old.json.gz").write_bytes(b"x")
    (seed / "marvel_catalogue.json").write_text('{"old": true}')
    return seed


def test_installs_bundle_and_replaces_pages(tmp_path, server):
    root, base = server
    make_bundle(root, {"marvel_catalogue.json": b'{"new": 1}', "runtime/imdb_rating_cache.json": b"{}",
                       "pages/marvel/1.json.gz": b"gz"})
    seed = seed_dir(tmp_path)
    assert "installed v1" in fcb.apply_bundle(seed, base)
    assert json.loads((seed / "marvel_catalogue.json").read_text()) == {"new": 1}
    assert (seed / "runtime" / "imdb_rating_cache.json").is_file()
    assert (seed / "pages" / "marvel" / "1.json.gz").is_file() and not (seed / "pages" / "old.json.gz").exists()
    assert "already at v1" in fcb.apply_bundle(seed, base)


def test_bad_checksum_leaves_seed_untouched(tmp_path, server):
    root, base = server
    make_bundle(root, {"marvel_catalogue.json": b'{"new": 1}'}, sha="0" * 64)
    seed = seed_dir(tmp_path)
    with pytest.raises(ValueError):
        fcb.apply_bundle(seed, base)
    assert json.loads((seed / "marvel_catalogue.json").read_text()) == {"old": True}


def test_corrupt_json_and_unsafe_paths_rejected(tmp_path, server):
    root, base = server
    seed = seed_dir(tmp_path)
    make_bundle(root, {"marvel_catalogue.json": b"{not json"}, version="v2")
    with pytest.raises(ValueError):
        fcb.apply_bundle(seed, base)
    make_bundle(root, {"../evil.json": b"{}"}, version="v3")
    with pytest.raises(ValueError):
        fcb.apply_bundle(seed, base)
    assert json.loads((seed / "marvel_catalogue.json").read_text()) == {"old": True}
    assert not (tmp_path / "evil.json").exists()


def test_main_never_raises_when_unreachable(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CACHE_BUNDLE_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("CACHE_SEED_DIR", str(seed_dir(tmp_path)))
    assert fcb.main() == 0
    assert "skipped" in capsys.readouterr().out
