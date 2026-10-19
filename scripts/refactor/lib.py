"""Static analysis helpers for splitting backend/main.py into modules.

Everything here is pure standard library so it runs anywhere (no FastAPI needed).

A *node* is one top-level statement of the module together with the comments
and blank lines directly above it (its "segment"). For every node we compute:

* defines  - module-level names it creates (def/class/assignment/import)
* refs     - module-level names its code reads (including inside functions)
* rebinds  - module-level names a function in it reassigns via ``global``
"""

from __future__ import annotations

import ast
import builtins
import symtable
from dataclasses import dataclass, field
from pathlib import Path

BUILTIN_NAMES = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__"}


@dataclass
class Node:
    idx: int
    start: int  # first line of the segment (includes leading comments)
    code_start: int  # first line of the statement itself (including decorators)
    end: int
    kind: str
    label: str
    defines: set[str] = field(default_factory=set)
    refs: set[str] = field(default_factory=set)
    rebinds: set[str] = field(default_factory=set)
    is_import: bool = False
    routes: list[tuple[str, str]] = field(default_factory=list)  # (HTTP method, path)
    uses_app: bool = False  # touches the FastAPI ``app`` object directly


def _decorator_start(node: ast.stmt) -> int:
    start = node.lineno
    for dec in getattr(node, "decorator_list", []) or []:
        start = min(start, dec.lineno)
    return start


def _label(node: ast.stmt, lines: list[str]) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ("async def " if isinstance(node, ast.AsyncFunctionDef) else "def ") + node.name
    if isinstance(node, ast.ClassDef):
        return "class " + node.name
    return lines[node.lineno - 1].strip()[:70]


def _walk_tables(table: symtable.SymbolTable, top: bool, out: dict) -> None:
    for sym in table.get_symbols():
        name = sym.get_name()
        if top:
            if sym.is_referenced():
                out["refs"].add(name)
            if sym.is_assigned() or sym.is_imported() or sym.is_namespace():
                out["defines"].add(name)
        else:
            if sym.is_global() and (sym.is_referenced() or sym.is_assigned()):
                out["refs"].add(name)
            if sym.is_declared_global() and sym.is_assigned():
                out["rebinds"].add(name)
    for child in table.get_children():
        _walk_tables(child, False, out)


def _route_info(node: ast.stmt) -> list[tuple[str, str]]:
    found = []
    for dec in getattr(node, "decorator_list", []) or []:
        if (
            isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and isinstance(dec.func.value, ast.Name)
            and dec.func.value.id in {"app", "router"}
            and dec.func.attr in {"get", "post", "put", "delete", "patch", "head", "options"}
            and dec.args
            and isinstance(dec.args[0], ast.Constant)
        ):
            found.append((dec.func.attr.upper(), str(dec.args[0].value)))
    return found


def parse_nodes(path: Path) -> tuple[list[Node], list[str]]:
    source = path.read_text()
    lines = source.split("\n")
    tree = ast.parse(source)
    nodes: list[Node] = []
    prev_end = 0
    for idx, stmt in enumerate(tree.body):
        code_start = _decorator_start(stmt)
        seg_start = prev_end + 1
        end = stmt.end_lineno or code_start
        snippet = "\n".join(lines[code_start - 1 : end])
        table = symtable.symtable(snippet, f"<node {idx}>", "exec")
        info = {"refs": set(), "defines": set(), "rebinds": set()}
        _walk_tables(table, True, info)
        node = Node(
            idx=idx,
            start=seg_start,
            code_start=code_start,
            end=end,
            kind=type(stmt).__name__,
            label=_label(stmt, lines),
            defines=info["defines"],
            refs=info["refs"],
            rebinds=info["rebinds"],
            is_import=isinstance(stmt, (ast.Import, ast.ImportFrom)),
            routes=_route_info(stmt),
        )
        node.uses_app = "app" in node.refs
        nodes.append(node)
        prev_end = end
    if nodes:
        nodes[-1].end = len(lines) if lines[-1].strip() else len(lines) - 1
    return nodes, lines


def definers(nodes: list[Node]) -> dict[str, list[int]]:
    table: dict[str, list[int]] = {}
    for node in nodes:
        if node.is_import:
            continue
        for name in node.defines:
            table.setdefault(name, []).append(node.idx)
    return table


def import_providers(nodes: list[Node]) -> dict[str, int]:
    """name -> index of the top-level import statement that binds it."""
    out = {}
    for node in nodes:
        if node.is_import:
            for name in node.defines:
                out[name] = node.idx
    return out


def dependencies(nodes: list[Node]) -> dict[int, set[int]]:
    """node idx -> idx of nodes (non-import) whose names it reads."""
    defs = definers(nodes)
    deps: dict[int, set[int]] = {}
    for node in nodes:
        found: set[int] = set()
        for name in node.refs:
            for owner in defs.get(name, []):
                if owner != node.idx:
                    found.add(owner)
        deps[node.idx] = found
    return deps


def tied_groups(nodes: list[Node], include_readers: bool = False) -> list[set[int]]:
    """Groups of nodes that must live in the same module.

    * every node that defines the same name (``X = ...`` then ``X.update(...)``,
      or ``X = None`` then rebinding it) is tied together
    * a variable that functions reassign with ``global`` is tied to every node
      that reassigns it, because a ``global X`` inside another module would
      create a *different* variable
    * with ``include_readers`` the readers of such a variable are tied as well.
      By default they are not: other modules can read it through the owning
      module (``owner.X``), see ``stale_readers``.
    """
    parent = list(range(len(nodes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    defs = definers(nodes)
    for owners in defs.values():
        for other in owners[1:]:
            union(owners[0], other)

    rebound = {name for node in nodes for name in node.rebinds}
    for name in rebound:
        owners = defs.get(name, [])
        for node in nodes:
            if node.is_import:
                continue
            if name in node.rebinds or (include_readers and name in node.refs):
                for owner in owners:
                    union(owner, node.idx)

    groups: dict[int, set[int]] = {}
    for node in nodes:
        groups.setdefault(find(node.idx), set()).add(node.idx)
    return [g for g in groups.values() if len(g) > 1]


def stale_readers(nodes: list[Node]) -> dict[str, list[int]]:
    """For each ``global``-rebound variable: nodes that read it but never rebind it.

    If such a node ends up in a different module than the variable, a plain
    ``from owner import X`` would freeze the initial value. It must read
    ``owner.X`` instead (or move into the owner module).
    """
    rebound = {name for node in nodes for name in node.rebinds}
    out: dict[str, list[int]] = {}
    for name in sorted(rebound):
        readers = [
            node.idx
            for node in nodes
            if not node.is_import and name in node.refs and name not in node.rebinds and name not in node.defines
        ]
        out[name] = readers
    return out
