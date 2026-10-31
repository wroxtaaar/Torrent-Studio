#!/usr/bin/env python3
"""Pack a seed directory into cache-bundle.tar.gz + cache-bundle.json (checksum, version).

    python scripts/make_cache_bundle.py <seed_dir> <out_dir>

Pre-splits the catalogue pages first so the app never has to do that on a slow instance.
"""
import hashlib, json, shutil, subprocess, sys, tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
seed, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)

subprocess.run([sys.executable, str(ROOT / "backend" / "maintenance" / "build_catalogue_pages.py"), str(seed)], check=True)

bundle = out / "cache-bundle.tar.gz"
with tarfile.open(bundle, "w:gz") as tar:
    for f in sorted(seed.rglob("*")):
        rel = f.relative_to(seed)
        if f.is_file() and rel.name not in ("README.md", ".bundle-version") and "pages.old" not in rel.parts:
            json.loads(f.read_bytes()) if f.suffix == ".json" else None  # fail early on corrupt files
            tar.add(f, arcname=rel.as_posix())

digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + digest[:8]
immutable_bundle_name = f"cache-bundle-{version}.tar.gz"
shutil.copy2(bundle, out / immutable_bundle_name)
manifest = {
    "version": version,
    "sha256": digest,
    "size": bundle.stat().st_size,
    "bundle": immutable_bundle_name,
    "createdAt": datetime.now(timezone.utc).isoformat(),
}
(out / "cache-bundle.json").write_text(json.dumps(manifest, indent=2))
print(json.dumps(manifest))
