"""The benchmark's letters and labels are made without the product: nothing under ``evals/gen/`` imports ``ordnung``,
so no label comes from the code it scores. Nor do the generator's entry point, the independent check of the labels and
the dataset's tests (``evals/generate.py``, ``evals/verify_labels.py``, ``tests/test_eval_dataset.py``): they run
where the product is not installed, as the letters' writers run them.

Two checks: each file's syntax tree names no ``ordnung`` import (``import``, ``from … import``, ``importlib`` or
``__import__`` with a constant name), and the files import in a fresh interpreter that refuses to import ``ordnung``
(so an import through another module fails too).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
#: What the letters' writers run, besides every module of evals/gen/.
RUN_WITHOUT_THE_PRODUCT = (
    EVALS / "generate.py",
    EVALS / "verify_labels.py",
    ROOT / "tests" / "test_eval_dataset.py",
)


def _product(name: str | None) -> bool:
    return name is not None and (name == "ordnung" or name.startswith("ordnung."))


def product_imports(source: str) -> list[int]:
    """The lines of ``source`` that import ``ordnung`` or a module of it."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import) and any(_product(alias.name) for alias in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and _product(node.module):
            lines.append(node.lineno)
        elif isinstance(node, ast.Call):
            func = node.func
            called = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else ""
            )
            first = node.args[0] if node.args else None
            if (
                called in ("import_module", "__import__")
                and isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and _product(first.value)
            ):
                lines.append(node.lineno)
    return sorted(lines)


def _files() -> list[Path]:
    return [*sorted((EVALS / "gen").rglob("*.py")), *RUN_WITHOUT_THE_PRODUCT]


def test_the_scan_finds_every_way_to_import_the_product() -> None:
    source = """\
import ordnung
import json, ordnung.models as models
from ordnung.rules import engine
from ordnung import clock
importlib.import_module("ordnung.models")
__import__("ordnung")
from . import law
from .common import Case
import ordnungsamt
from evals.gen import common
"""
    assert product_imports(source) == [1, 2, 3, 4, 5, 6]


def test_nothing_the_writers_run_imports_the_product() -> None:
    found = {
        path.relative_to(ROOT).as_posix(): lines
        for path in _files()
        if (lines := product_imports(path.read_text(encoding="utf-8")))
    }
    assert len(_files()) > 10 and not found, found


#: Imports every module of ``gen`` and each file the writers run, with ``ordnung`` refused; ``python -I`` from a
#: folder of its own, so neither PYTHONPATH nor the checkout's folder lends it the product.
REFUSING = """\
import importlib
import importlib.abc
import importlib.util
import pkgutil
import sys


class Refuse(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == "ordnung" or name.startswith("ordnung."):
            raise ImportError(f"{name} is the product: the letters are made without it")
        return None


sys.meta_path.insert(0, Refuse())
evals, files = sys.argv[1], sys.argv[2:]
sys.path[:0] = [evals]  # as the writers run them: gen importable from evals/
import gen

modules = [importlib.import_module(f"gen.{info.name}") for info in pkgutil.walk_packages(gen.__path__)]
for number, file in enumerate(files):
    spec = importlib.util.spec_from_file_location(f"written_{number}", file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
print("imported", len(modules), "modules of gen and", len(files), "files")
"""


def test_every_file_the_writers_run_imports_without_the_product(tmp_path: Path) -> None:
    files = [str(path) for path in RUN_WITHOUT_THE_PRODUCT]
    done = subprocess.run(
        [sys.executable, "-I", "-c", REFUSING, str(EVALS), *files],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    modules = len([path for path in (EVALS / "gen").glob("*.py") if path.name != "__init__.py"])
    assert done.stdout.strip() == f"imported {modules} modules of gen and {len(files)} files"
