"""Guards for the main.py split.

The route table, middleware order and startup hooks are recorded in
``snapshots/app_structure.json``. FastAPI matches routes in registration
order, so reordering routes (even by accident while moving code between
modules) can change which handler answers a request. These tests fail when
that structure changes.

To accept an intentional change, regenerate the snapshot (it is derived two
independent ways, see scripts/refactor/stubcheck.py)::

    python3 -I scripts/refactor/stubcheck.py --write
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SNAPSHOT = Path(__file__).parent / "snapshots" / "app_structure.json"


def _structure(module_name: str) -> dict:
    # A fresh interpreter: importing fullstack_app edits main.app in place, and
    # other tests have already imported main.
    code = (
        "import json, sys; sys.path.insert(0, 'tests'); "
        f"import app_structure, {module_name}; "
        f"print('STRUCTURE=' + json.dumps(app_structure.extract({module_name}.app)))"
    )
    env = {**os.environ, "CACHE_ONLY_MODE": "true", "SEEDR_SESSION_SECRET": "test-only-session-secret"}
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=240
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    line = next(l for l in proc.stdout.splitlines() if l.startswith("STRUCTURE="))
    return json.loads(line[len("STRUCTURE="):])


def _describe(expected: dict, actual: dict) -> str:
    problems = []
    for part in ("routes", "middleware", "exception_handlers", "startup", "shutdown"):
        exp, act = expected.get(part), actual.get(part)
        if exp == act:
            continue
        message = f"{part}: expected {len(exp or [])} items, got {len(act or [])}"
        if isinstance(exp, list) and isinstance(act, list):
            for index, (a, b) in enumerate(zip(exp, act)):
                if a != b:
                    message += f"; first difference at {index}: expected {a} got {b}"
                    break
            else:
                extra = exp[len(act):] or act[len(exp):]
                message += f"; extra items: {extra[:3]}"
        if part == "routes" and isinstance(act, list):
            message += f"; actual last routes: {[r[1] for r in act[-6:]]}"
        problems.append(message)
    return " || ".join(problems)


@pytest.fixture(scope="module")
def expected():
    return json.loads(SNAPSHOT.read_text())


@pytest.mark.parametrize("module_name", ["main", "fullstack_app"])
def test_app_structure_matches_snapshot(module_name, expected):
    actual = _structure(module_name)
    assert actual == expected[module_name], _describe(expected[module_name], actual)


def test_names_used_by_maintenance_scripts_still_exist_on_main():
    """backend/*.py scripts do `import main` and read main.<name>."""
    import main

    used: dict[str, set[str]] = {}
    for path in BACKEND.glob("*.py"):
        if path.name in {"main.py", "fullstack_app.py"}:
            continue
        tree = ast.parse(path.read_text())
        imports_main = any(
            isinstance(node, ast.Import) and any(alias.name == "main" for alias in node.names)
            for node in ast.walk(tree)
        )
        if not imports_main:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "main":
                used.setdefault(node.attr, set()).add(path.name)

    missing = {name: sorted(files) for name, files in used.items() if not hasattr(main, name)}
    assert not missing, f"scripts use names that main no longer exposes: {missing}"
