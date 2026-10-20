#!/usr/bin/env python3
"""Move top-level code out of backend/main.py into a new module.

Part of the main.py split, see docs/main-split-plan.md. Pure standard library.

    # what would moving these lines do? (nothing is written)
    python3 -I scripts/refactor/extract.py plan  --module settings --lines 44-110,255-460

    # do it; verifies compile + undefined names + app structure, and undoes
    # everything automatically if a check fails
    python3 -I scripts/refactor/extract.py apply --module settings --lines 44-110,255-460

    # where do we stand?
    python3 -I scripts/refactor/extract.py status

    # list the top-level statements (to choose line ranges), optionally for a range
    python3 -I scripts/refactor/extract.py outline [--lines 2495-4310]

    # check every backend module for names that are used but never defined
    python3 -I scripts/refactor/extract.py check

Selecting code: ``--lines A-B,C-D`` takes every top-level statement that lies
inside one of the ranges (line numbers of the *current* main.py), ``--names
x,y`` additionally takes the statements that define those names.

What the tool does for you
* finds the imports the moved code needs and writes them in the new module
* replaces the moved code in main.py by one ``from module import ...`` that
  keeps every name main.py (and the maintenance scripts) still use
* turns ``@app.get(...)`` into ``@router.get(...)`` on a module-level
  ``router`` and registers it at the same position with ``app.include_router``
  so FastAPI's route order is unchanged
* turns ``@app.on_event("startup")`` into an explicit
  ``app.router.add_event_handler`` call at the same position
* refuses to move code that would end up importing main.py back (circular),
  that reassigns shared state with ``global`` in a different module than the
  variable lives in, or that touches the ``app`` object in other ways.
"""

from __future__ import annotations

import argparse
import os
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
THIRD_PARTY = {"httpx", "libtorrent", "cryptography", "bs4", "fastapi", "pydantic", "starlette"}
ROUTE_DECORATOR = re.compile(r"^@app\.(get|post|put|delete|patch|head|options)\(")
EVENT_DECORATOR = re.compile(r"^@app\.on_event\((['\"])(startup|shutdown)\1\)\s*$")


class ExtractError(Exception):
    pass


# --------------------------------------------------------------------------
# Selecting nodes
# --------------------------------------------------------------------------
def parse_ranges(text: str) -> list[tuple[int, int]]:
    ranges = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        a, _, b = part.partition("-")
        ranges.append((int(a), int(b or a)))
    return ranges


def select(nodes: list[lib.Node], lines_spec: str, names_spec: str) -> set[int]:
    chosen: set[int] = set()
    for a, b in parse_ranges(lines_spec or ""):
        for node in nodes:
            if node.code_start >= a and node.end <= b:
                chosen.add(node.idx)
    wanted = {n.strip() for n in (names_spec or "").split(",") if n.strip()}
    if wanted:
        for node in nodes:
            if not node.is_import and wanted & node.defines:
                chosen.add(node.idx)
    return {i for i in chosen if not nodes[i].is_import}


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def validate(nodes: list[lib.Node], chosen: set[int], module: str) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    defs = lib.definers(nodes)
    imports = lib.import_providers(nodes)
    label = lambda i: f"{nodes[i].label} (line {nodes[i].code_start})"  # noqa: E731

    for group in lib.tied_groups(nodes):
        inside, outside = group & chosen, group - chosen
        if inside and outside:
            names = sorted({n for i in group for n in nodes[i].defines | nodes[i].rebinds if not n.startswith("__")})[:6]
            errors.append(
                "these must move together (shared state or one name defined in several places): "
                + ", ".join(label(i) for i in sorted(outside))
                + f"  [involves {names}]"
            )

    for i in sorted(chosen):
        node = nodes[i]
        plain_route = bool(node.routes) or any(
            EVENT_DECORATOR.match(line.strip()) for line in _decorator_lines(node, nodes)
        )
        missing: dict[str, list[int]] = {}
        for name in node.refs:
            if name in imports or name in lib.BUILTIN_NAMES:
                continue
            if name == "app" and plain_route:
                continue  # the decorator is converted to the module's router
            for owner in defs.get(name, []):
                if owner not in chosen:
                    missing.setdefault(name, []).append(owner)
        if missing:
            errors.append(
                f"{label(i)} uses code that stays in main.py (would be a circular import): "
                + ", ".join(f"{n} (line {nodes[o[0]].code_start})" for n, o in sorted(missing.items())[:8])
            )

        if node.uses_app:
            if not plain_route:
                errors.append(f"{label(i)} uses the FastAPI `app` object directly; it must stay in main.py")

    # variables reassigned with `global` that other (staying) code reads
    for name, readers in lib.stale_readers(nodes).items():
        owners = defs.get(name, [])
        if owners and set(owners) <= chosen:
            outside = [r for r in readers if r not in chosen]
            if outside:
                errors.append(
                    f"`{name}` is reassigned at runtime but read by code that stays in main.py "
                    f"({', '.join(label(r) for r in outside[:4])}); move those too or read it via the module"
                )
    return errors, warnings


_SOURCE_LINES: dict[int, list[str]] = {}


def _decorator_lines(node: lib.Node, nodes: list[lib.Node]) -> list[str]:
    lines = _SOURCE_LINES.get(0, [])
    return lines[node.code_start - 1 : node.end] if lines else []


# --------------------------------------------------------------------------
# Imports
# --------------------------------------------------------------------------
def import_table(lines: list[str], nodes: list[lib.Node]) -> dict[str, tuple[str, str | None, str, int]]:
    """name -> (kind, module, original_name, level) for names bound by top-level imports."""
    table = {}
    for node in nodes:
        if not node.is_import:
            continue
        stmt = ast.parse("\n".join(lines[node.code_start - 1 : node.end])).body[0]
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                bound = alias.asname or alias.name.split(".")[0]
                table[bound] = ("import", alias.name, alias.asname or "", 0)
        else:
            for alias in stmt.names:
                bound = alias.asname or alias.name
                table[bound] = ("from", stmt.module, alias.name, stmt.level)
    return table


def render_imports(needed: set[str], table: dict, local_modules: set[str]) -> list[str]:
    plain: dict[str, set[str]] = {"std": set(), "third": set(), "local": set()}
    froms: dict[str, dict[str, set[tuple[str, str]]]] = {"std": {}, "third": {}, "local": {}}

    def bucket(module: str) -> str:
        root = module.split(".")[0]
        if root in local_modules:
            return "local"
        if root in THIRD_PARTY:
            return "third"
        return "std" if root in sys.stdlib_module_names else "third"

    for name in sorted(needed):
        if name not in table:
            continue
        kind, module, original, _level = table[name]
        if kind == "import":
            text = f"import {module}" + (f" as {original}" if original else "")
            plain[bucket(module)].add(text)
        else:
            alias = f"{original} as {name}" if original != name else name
            froms[bucket(module)].setdefault(module, set()).add((original, alias))

    out: list[str] = []
    for group in ("std", "third", "local"):
        block = sorted(plain[group], key=lambda t: t.split()[1])
        for module in sorted(froms[group]):
            aliases = sorted({a for _o, a in froms[group][module]})
            one = f"from {module} import " + ", ".join(aliases)
            if len(one) <= 100:
                block.append(one)
            else:
                block.append(f"from {module} import (\n" + "".join(f"    {a},\n" for a in aliases) + ")")
        if block:
            out.extend(block + [""])
    return out


# --------------------------------------------------------------------------
# The move
# --------------------------------------------------------------------------
def segment(lines: list[str], node: lib.Node) -> list[str]:
    return lines[node.start - 1 : node.end]


def strip_blank_edges(seg: list[str]) -> list[str]:
    start, end = 0, len(seg)
    while start < end and not seg[start].strip():
        start += 1
    while end > start and not seg[end - 1].strip():
        end -= 1
    return seg[start:end]


def build(main_lines: list[str], nodes: list[lib.Node], chosen: set[int], module: str, export_extra: set[str]):
    table = import_table(main_lines, nodes)
    local_modules = {p.stem for p in BACKEND.glob("*.py")} | {module}
    ordered = sorted(chosen)
    hooks: dict[int, tuple[str, str]] = {}  # node idx -> (kind, function name)
    has_routes = any(nodes[i].routes for i in ordered)

    # --- body of the new module
    body: list[str] = []
    previous: int | None = None
    for i in ordered:
        seg = segment(main_lines, nodes[i])
        converted: list[str] = []
        for line in seg:
            event = EVENT_DECORATOR.match(line)
            if event:
                hooks[i] = (event.group(2), nodes[i].label.split()[-1])
                continue
            converted.append(ROUTE_DECORATOR.sub(lambda m: f"@router.{m.group(1)}(", line))
        seg = converted
        if previous is not None and i == previous + 1:
            body.extend(seg)  # adjacent in the original: keep spacing as it was
        else:
            if body:
                body.extend(["", ""])
            body.extend(strip_blank_edges(seg) if not body else strip_blank_edges(seg))
        previous = i

    needed = set()
    for i in ordered:
        needed |= nodes[i].refs
    needed_imports = {n for n in needed if n in table}
    if has_routes:
        needed_imports.add("APIRouter")
        table.setdefault("APIRouter", ("from", "fastapi", "APIRouter", 0))

    header = [f'"""Moved out of main.py (see docs/main-split-plan.md)."""', ""]
    header += render_imports(needed_imports, table, local_modules)
    if has_routes:
        header += ["router = APIRouter()", "", ""]
    text = "\n".join(header + body).rstrip("\n") + "\n"
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    # --- names the rest of main.py (and the scripts) still need
    defined = set()
    for i in ordered:
        defined |= nodes[i].defines
    remaining_refs = set()
    for node in nodes:
        if node.idx not in chosen:
            remaining_refs |= node.refs
    exported = {n for n in defined if n in remaining_refs} | {n for n in export_extra if n in defined}
    exported |= {fn for (_k, fn) in hooks.values()}
    import_names = sorted(exported)
    if has_routes:
        import_names.append(f"router as {module}_router")

    # --- the new main.py
    new_main: list[str] = []
    first = ordered[0]
    inserted = False
    for node in nodes:
        if node.idx in chosen:
            if not inserted:
                if import_names:
                    if new_main and new_main[-1].strip():
                        new_main.append("")
                    one = f"from {module} import " + ", ".join(import_names)
                    if len(one) <= 100:
                        new_main.append(one)
                    else:
                        new_main.append(f"from {module} import (")
                        new_main.extend(f"    {n}," for n in import_names)
                        new_main.append(")")
                inserted = True
            if node.idx in hooks:
                kind, fn = hooks[node.idx]
                new_main.append(f'app.router.add_event_handler("{kind}", {fn})')
            if node.routes and not any(
                other.routes for other in nodes if other.idx in chosen and other.idx < node.idx
            ):
                new_main.append(f"app.include_router({module}_router)")
            continue
        new_main.extend(segment(main_lines, node))
    # header comments/imports before first node and trailing text are part of node segments already
    return text, "\n".join(new_main).rstrip("\n") + "\n", import_names


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def undefined_names(path: Path) -> list[str]:
    nodes, _ = lib.parse_nodes(path)
    defs = lib.definers(nodes)
    imports = lib.import_providers(nodes)
    problems = []
    for node in nodes:
        for name in sorted(node.refs):
            if name not in defs and name not in imports and name not in lib.BUILTIN_NAMES:
                problems.append(f"{path.name}:{node.code_start} {node.label}: undefined name `{name}`")
    return problems


def run_checks(paths: list[Path]) -> list[str]:
    problems: list[str] = []
    for path in paths:
        proc = subprocess.run([sys.executable, "-I", "-m", "py_compile", str(path)], capture_output=True, text=True)
        if proc.returncode:
            problems.append(proc.stderr.strip())
    if problems:
        return problems
    for path in paths:
        problems += undefined_names(path)
    if problems:
        return problems
    if os.environ.get("ALLOW_STRUCTURE_CHANGE"):
        # The caller reviewed that moving routes only reorders unrelated static
        # paths, and regenerates the snapshot with `stubcheck.py --write`.
        return problems
    proc = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts/refactor/stubcheck.py"), "--check"], capture_output=True, text=True
    )
    if proc.returncode:
        problems.append("app structure changed:\n" + proc.stdout + proc.stderr)
    return problems


def script_and_test_usage(module_names: set[str]) -> tuple[set[str], list[str]]:
    """main.<name> used by maintenance scripts (must keep working) and by tests (need retargeting)."""
    scripts: set[str] = set()
    for path in BACKEND.glob("*.py"):
        if path.name in {"main.py", "fullstack_app.py"}:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "main":
                scripts.add(node.attr)
    tests: list[str] = []
    for path in (BACKEND / "tests").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "main":
                if node.attr in module_names:
                    tests.append(f"{path.name}: main.{node.attr}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in module_names
            ):
                tests.append(f"{path.name}: monkeypatch.setattr(..., {node.args[1].value!r})")
    return scripts, sorted(set(tests))


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------
def load() -> tuple[list[lib.Node], list[str]]:
    nodes, lines = lib.parse_nodes(BACKEND / "main.py")
    _SOURCE_LINES[0] = lines
    return nodes, lines


def cmd_status(_args) -> int:
    nodes, lines = load()
    total = len(lines)
    print(f"backend/main.py: {total} lines, {len(nodes)} top-level statements, "
          f"{sum(len(n.routes) for n in nodes)} routes")
    for path in sorted(BACKEND.glob("*.py")):
        if path.name != "main.py":
            print(f"  {path.name:34s} {len(path.read_text().splitlines()):6d} lines")
    return 0


def cmd_outline(args) -> int:
    nodes, _lines = load()
    ranges = parse_ranges(args.lines) if args.lines else []
    for node in nodes:
        if node.is_import:
            continue
        if ranges and not any(a <= node.code_start and node.end <= b for a, b in ranges):
            continue
        extra = "  " + " ".join(f"{m} {path}" for m, path in node.routes) if node.routes else ""
        flags = []
        if node.rebinds:
            flags.append("rebinds " + ",".join(sorted(node.rebinds)))
        if node.uses_app and not node.routes:
            flags.append("uses app")
        suffix = f"  [{'; '.join(flags)}]" if flags else ""
        print(f"{node.code_start:6d}-{node.end:<6d} {node.label}{extra}{suffix}")
    return 0


def cmd_check(_args) -> int:
    paths = sorted(p for p in BACKEND.glob("*.py"))
    problems = []
    for path in paths:
        problems += undefined_names(path)
    print("\n".join(problems) if problems else f"no undefined names in {len(paths)} modules")
    return 1 if problems else 0


def cmd_move(args, apply: bool) -> int:
    nodes, lines = load()
    chosen = select(nodes, args.lines, args.names)
    if not chosen:
        print("nothing selected (check --lines / --names against `status`)")
        return 2
    target = BACKEND / f"{args.module}.py"
    if target.exists() and not args.append:
        print(f"{target.name} already exists (use --append to add to it)")
        return 2

    errors, warnings = validate(nodes, chosen, args.module)
    moved_lines = sum(nodes[i].end - nodes[i].start + 1 for i in chosen)
    print(f"selected {len(chosen)} statements, ~{moved_lines} lines, "
          f"{sum(len(nodes[i].routes) for i in chosen)} routes")
    for w in warnings:
        print("  warning:", w)
    if errors:
        print("cannot move yet:")
        for e in errors:
            print("  -", e)
        return 1

    defined = set().union(*(nodes[i].defines for i in chosen))
    scripts_used, tests_used = script_and_test_usage(defined)
    text, new_main, import_names = build(lines, nodes, chosen, args.module, scripts_used)
    print(f"main.py will import {len(import_names)} names from {args.module}")
    if tests_used:
        print("  tests refer to moved names via `main` and must be pointed at the new module:")
        for t in tests_used:
            print("   ", t)
    if not apply:
        print("(plan only; nothing written)")
        return 0

    backups = {BACKEND / "main.py": (BACKEND / "main.py").read_text()}
    existed = target.exists()
    if existed:
        backups[target] = target.read_text()
    try:
        target.write_text(text)
        (BACKEND / "main.py").write_text(new_main)
        problems = run_checks([BACKEND / "main.py", target])
    except Exception as exc:  # noqa: BLE001
        problems = [f"{type(exc).__name__}: {exc}"]
    if problems:
        for path, content in backups.items():
            path.write_text(content)
        if not existed and target.exists():
            target.unlink()
        print("checks failed, everything was restored:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"ok: {args.module}.py written ({len(text.splitlines())} lines), main.py now "
          f"{len(new_main.splitlines())} lines; all checks passed")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--module", required=True)
        p.add_argument("--lines", default="")
        p.add_argument("--names", default="")
        p.add_argument("--append", action="store_true", help="add to an existing module (not implemented yet)")
    sub.add_parser("status")
    sub.add_parser("check")
    outline = sub.add_parser("outline")
    outline.add_argument("--lines", default="")
    args = parser.parse_args(argv[1:])
    if args.cmd == "outline":
        return cmd_outline(args)
    if args.cmd == "status":
        return cmd_status(args)
    if args.cmd == "check":
        return cmd_check(args)
    return cmd_move(args, apply=args.cmd == "apply")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
