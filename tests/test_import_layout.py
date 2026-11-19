"""The package's import layers: which modules may import each other in a circle, read from the source alone.

The import graph is built from the code's syntax, once for the file: every ``import`` at module level and
inside a function counts (a lazy import still ties two modules together), an import under
``if TYPE_CHECKING:`` does not (it never runs). No interpreter is started and nothing is imported.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from helpers_tables import check_rows
from ordnung.config import PACKAGE_DIR

#: Every circle of modules that import each other, with why it is there. A new import that closes a circle
#: fails the test below; a refactor that ends one takes it out of this list.
ALLOWED_CYCLES: dict[frozenset[str], str] = {
    frozenset(
        {"ordnung.rules.deadlines", "ordnung.rules.letters"}
    ): "the letter rules build on the deadline receipts; deadlines imports them lazily where needed",
}

#: (module, modules that importing it must not load): a low layer stays light.
STAYS_LIGHT = [
    # the person's today and the day parsers: a leaf, below the store, the tick and the triggers
    ("ordnung.days", {"ordnung.db.store", "ordnung.tick", "ordnung.secretary.triggers"}),
    # the calendar file needs today and the ledger's facts, not the daily tick, the reading pipeline or the triggers
    ("ordnung.calendar.ics", {"ordnung.tick", "ordnung.ingest.pipeline", "ordnung.secretary.triggers"}),
    # recurring dates need the postal buffer from the rules engine, not the trigger engine
    ("ordnung.recurrence", {"ordnung.secretary.triggers"}),
    # the check for an incomplete reading sits below the plan that files its to-dos
    ("ordnung.ingest.gaps", {"ordnung.ingest.plan"}),
    # the sync engine reads the demo folder's marker, not the demo loader
    ("ordnung.sync.engine", {"ordnung.demo.loader"}),
    # the rules engine reads written dates from the leaf, not from the verification and the page reader below it;
    # one row for the package and one for each of its modules, since the package does not load them all
    ("ordnung.rules", {"ordnung.ingest.verify", "ordnung.ingest.text"}),
    *(
        (f"ordnung.rules.{path.stem}", {"ordnung.ingest.verify", "ordnung.ingest.text"})
        for path in sorted((PACKAGE_DIR / "rules").glob("*.py"))
        if path.stem != "__init__"
    ),
]


Graph = dict[str, dict[str, str]]


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(PACKAGE_DIR.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve(module: str, is_package: bool, level: int, name: str | None) -> str:
    """The absolute module a ``from ... import`` names, relative levels resolved."""
    if level == 0:
        return name or ""
    base = module.split(".") if is_package else module.split(".")[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join([*base, *([name] if name else [])])


def _edges(module: str, is_package: bool, tree: ast.Module, modules: set[str]) -> dict[str, str]:
    """The package modules ``module`` imports, each marked ``top`` (at import), ``lazy`` (in a function) or
    ``tc`` (only under ``TYPE_CHECKING``); an import reached more than one way keeps the strongest mark."""
    rank = {"top": 0, "lazy": 1, "tc": 2}
    found: dict[str, str] = {}

    def visit(node: ast.AST, kind: str) -> None:
        for child in ast.iter_child_nodes(node):
            mark = kind
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                mark = "lazy"
            if isinstance(child, ast.If) and "TYPE_CHECKING" in ast.unparse(child.test):
                mark = "tc"
            targets: list[str] = []
            if isinstance(child, ast.Import):
                targets = [alias.name for alias in child.names]
            elif isinstance(child, ast.ImportFrom):
                base = _resolve(module, is_package, child.level, child.module)
                for alias in child.names:
                    full = f"{base}.{alias.name}"
                    targets.append(full if full in modules else base)
            for target in targets:
                if not target.startswith("ordnung"):
                    continue
                while target not in modules and "." in target:
                    target = target.rsplit(".", 1)[0]
                if target != module and (target not in found or rank[mark] < rank[found[target]]):
                    found[target] = mark
            visit(child, mark)

    visit(tree, "top")
    return found


@pytest.fixture(scope="module")
def graph() -> Graph:
    """Every package module and the package modules it imports, parsed once for the tests of this file."""
    paths = {_module_name(path): path for path in sorted(PACKAGE_DIR.rglob("*.py"))}
    modules = set(paths)
    return {
        name: _edges(name, path.name == "__init__.py", ast.parse(path.read_text("utf-8")), modules)
        for name, path in paths.items()
    }


def _cycles(graph: Graph) -> set[frozenset[str]]:
    """The strongly connected sets of more than one module, lazy imports included, ``TYPE_CHECKING`` not."""
    edges = {a: sorted(b for b, kind in targets.items() if kind != "tc") for a, targets in graph.items()}
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: set[frozenset[str]] = set()
    for root in sorted(edges):
        if root in index:
            continue
        # Tarjan's algorithm without recursion: (module, its next edge to follow)
        work = [(root, 0)]
        while work:
            node, at = work.pop()
            if at == 0:
                index[node] = low[node] = len(index)
                stack.append(node)
                on_stack.add(node)
            for i in range(at, len(edges[node])):
                target = edges[node][i]
                if target not in index:
                    work.append((node, i + 1))
                    work.append((target, 0))
                    break
                if target in on_stack:
                    low[node] = min(low[node], index[target])
            else:
                if low[node] == index[node]:
                    part: set[str] = set()
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        part.add(member)
                        if member == node:
                            break
                    if len(part) > 1:
                        found.add(frozenset(part))
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
    return found


def test_the_only_import_cycles_are_the_named_ones(graph: Graph) -> None:
    """A layer never imports a higher one, at import or lazily: the circles left are the named ones."""
    assert len(graph) > 100
    cycles = _cycles(graph)
    assert {tuple(sorted(c)) for c in cycles} == {tuple(sorted(c)) for c in ALLOWED_CYCLES}


def _loaded_by(graph: Graph, module: str) -> set[str]:
    """The package modules ``import module`` loads: its imports at import time, theirs, and so on, with the
    parent packages of each (importing ``a.b.c`` runs ``a/__init__`` and ``a/b/__init__`` first)."""
    seen: set[str] = set()
    todo = [module]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        parts = name.split(".")
        todo.extend(".".join(parts[:i]) for i in range(1, len(parts)) if ".".join(parts[:i]) in graph)
        todo.extend(target for target, kind in graph[name].items() if kind == "top")
    return seen


def test_importing_these_modules_leaves_those_out(graph: Graph) -> None:
    def check(module: str, never: set[str]) -> None:
        assert module in graph
        assert _loaded_by(graph, module) & never == set()

    check_rows(STAYS_LIGHT, check)
