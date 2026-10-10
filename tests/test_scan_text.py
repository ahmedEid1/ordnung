"""A scan's scanner text (``derived/<doc_id>/scan-text.json``, ADR 0020): the file format, and that only the
store and the text stage ever touch it — so no prompt, evidence check or Ask tool can reach it."""

from __future__ import annotations

import ast
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from ordnung.config import PACKAGE_DIR
from ordnung.db import scan_text


def test_scanner_text_round_trips(tmp_path: Path) -> None:
    scan_text.write(tmp_path, "doc_a", {1: "Wasserzähler Ablesung", 3: "Seite drei"})
    assert scan_text.read(tmp_path, "doc_a") == {1: "Wasserzähler Ablesung", 3: "Seite drei"}
    assert scan_text.present(tmp_path, "doc_a")
    stored = json.loads(scan_text.path(tmp_path, "doc_a").read_text("utf-8"))
    assert stored == {"version": 1, "pages": {"1": "Wasserzähler Ablesung", "3": "Seite drei"}}
    assert scan_text.path(tmp_path, "doc_a") == tmp_path / "doc_a" / "scan-text.json"


def test_an_empty_map_means_looked_and_found_nothing(tmp_path: Path) -> None:
    """An empty ``pages`` map is kept (the catch-up looked, nothing there), so it never looks again."""
    scan_text.write(tmp_path, "doc_a", {})
    assert scan_text.present(tmp_path, "doc_a") and scan_text.read(tmp_path, "doc_a") == {}
    scan_text.remove(tmp_path, "doc_a")
    assert not scan_text.present(tmp_path, "doc_a")
    scan_text.remove(tmp_path, "doc_a")  # already gone: nothing to do


def test_each_page_is_capped(tmp_path: Path) -> None:
    scan_text.write(tmp_path, "doc_a", {1: "x" * (scan_text.MAX_PAGE_CHARS + 50)})
    assert len(scan_text.read(tmp_path, "doc_a")[1]) == scan_text.MAX_PAGE_CHARS


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b"\xff\xfe",
        b"[]",
        b'{"version": 2, "pages": {"1": "neuer"}}',
        b'{"version": 1}',
        b'{"version": 1, "pages": []}',
        b'{"version": 1, "pages": {"eins": "x"}}',
        b'{"version": 1, "pages": {"1": 5}}',
    ],
)
def test_a_garbage_or_other_version_file_reads_as_nothing(tmp_path: Path, content: bytes) -> None:
    target = scan_text.path(tmp_path, "doc_a")
    target.parent.mkdir()
    target.write_bytes(content)
    assert scan_text.read(tmp_path, "doc_a") == {}


def test_a_missing_file_reads_as_nothing(tmp_path: Path) -> None:
    assert scan_text.read(tmp_path, "doc_a") == {}
    assert not scan_text.present(tmp_path, "doc_a")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_the_file_is_private_and_written_atomically(tmp_path: Path) -> None:
    scan_text.write(tmp_path, "doc_a", {1: "Text"})
    target = scan_text.path(tmp_path, "doc_a")
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(target.parent).st_mode) == 0o700
    scan_text.write(tmp_path, "doc_a", {1: "Neu"})
    assert sorted(path.name for path in target.parent.iterdir()) == ["scan-text.json"]  # no .part left


def test_a_doc_id_never_names_a_file_outside_its_folder(tmp_path: Path) -> None:
    for bad in ("..", "../x", "a/b", "", "."):
        with pytest.raises(ValueError):
            scan_text.path(tmp_path, bad)


# --------------------------------------------------------------------------------------------------
# Who may touch it
# --------------------------------------------------------------------------------------------------

#: The only modules that may import ``ordnung.db.scan_text``: the store (reads and writes it) and the
#: text stage (asks the store to write it).
ALLOWED_IMPORTERS = {"db/store.py", "ingest/pipeline.py"}
#: Modules that read letters for a model, check evidence or answer Ask: they may not even name it.
NEVER_NAMED_IN = ("assistant/", "secretary/", "llm/", "drafts/")
NEVER_NAMED_IN_FILES = {
    f"ingest/{name}.py" for name in ("verify", "conflicts", "gaps", "extract", "transcribe", "plan", "link")
}


def _modules() -> list[tuple[str, ast.Module, str]]:
    found = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        source = path.read_text("utf-8")
        found.append((path.relative_to(PACKAGE_DIR).as_posix(), ast.parse(source), source))
    return found


def _imports_scan_text(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(alias.name == "ordnung.db.scan_text" for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[-1] == "scan_text":
                return True
            if module in ("ordnung.db", "") and any(alias.name == "scan_text" for alias in node.names):
                return True
    return False


def test_only_the_store_and_the_text_stage_touch_the_scanner_text() -> None:
    """Importers of :mod:`ordnung.db.scan_text` are the store and the pipeline's text stage, nothing else;
    no module that builds a prompt, checks evidence or answers Ask even names ``scan_text``."""
    modules = _modules()
    assert len(modules) > 100
    importers = {name for name, tree, _ in modules if _imports_scan_text(tree)}
    assert "db/store.py" in importers and importers <= ALLOWED_IMPORTERS, importers
    named = {
        name
        for name, _, source in modules
        if "scan_text" in source and (name.startswith(NEVER_NAMED_IN) or name in NEVER_NAMED_IN_FILES)
    }
    assert named == set()


def test_the_import_guard_sees_every_way_of_importing_it() -> None:
    for source in (
        "import ordnung.db.scan_text",
        "from ordnung.db import scan_text",
        "from ordnung.db.scan_text import read",
        "from . import scan_text",
        "from .scan_text import read",
    ):
        assert _imports_scan_text(ast.parse(source)), source
    assert not _imports_scan_text(ast.parse("from ordnung.db import store"))
