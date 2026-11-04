"""The final run's labels stay unread until its recording is published: before a live run of holdout4 or newkinds is
published in ``evals/results/``, no test but the readers of :data:`READERS` reads that split's letters or labels, and
no results file or row of ``items.csv`` shows them.

A split counts as recorded once a live, complete run of it is published: a results file directly in
``evals/results/`` (a file in a folder below it, as ``pending/``, is not published) whose ``meta`` says so. Until
then:

* the census of recorded readings (``tests/test_reading_gaps_census.py``) leaves the split out;
* no test module but the readers names one of its letters (an id or a file the manifest lists), selects entries by
  its name, or takes it as a ``split`` parameter;
* no results file but its live runs, and no row of ``evals/results/items.csv``, holds it, and the prediction cache of
  a read recorded into ``evals/results/pending/`` is never committed (``evals/.gitignore``).

The scan reads each module's syntax tree: it finds a test written to read the split, not every path by which a test
could. Made-up letters that borrow a final split's name are no letters the manifest lists, so they pass."""

from __future__ import annotations

import ast
import csv
import json
import subprocess
import sys
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import splits  # noqa: E402

TESTS = ROOT / "tests"
RESULTS = ROOT / "evals" / "results"
MANIFEST = ROOT / "evals" / "dataset" / "manifest.json"
#: The final run's splits: the registry's role ``final``.
FINAL = tuple(split.name for split in splits.REGISTRY if split.role == "final")
#: The test modules that read the final splits' labels before their recording (file name patterns), and why.
READERS = {
    "test_eval_dataset.py": "the dataset's own checks: every split's files, labels and wording",
    "test_eval_kinds.py": "every label's document kind is one the product knows",
    "test_verify_labels*.py": "the labels re-derived by the independent calculator",
    "test_generate_final.py": "the generator's final plug-in",
    "test_preregistration.py": "the pre-registration's hashes of the data",
    "test_prereg_*.py": "the pre-registration's tools: hashes, samplers and power from the data",
    "test_perturb_build.py": "the stress cells' builder, whose holdout4 letters are made up from earlier splits'",
    "test_final_labels_unused.py": "this guard's own examples",
}


def live_splits(results_dir: Path = RESULTS) -> set[str]:
    """The splits with a live, complete run published in ``results_dir``: a results file directly in it (not in a
    folder below it, as ``pending/``) whose ``meta`` names the split, with ``backend`` ``live``."""
    found: set[str] = set()
    for path in sorted(results_dir.glob("*.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8")).get("meta")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(meta, dict) and meta.get("backend") == "live" and not meta.get("partial"):
            split = meta.get("split")
            if isinstance(split, str):
                found.add(split)
    return found


def unrecorded_final_splits(results_dir: Path = RESULTS) -> set[str]:
    """The final splits with no live run published in ``results_dir`` yet: their labels stay unread."""
    return set(FINAL) - live_splits(results_dir)


def listed_letters(names: Iterable[str], manifest: Path = MANIFEST) -> set[str]:
    """The ids and files (``<split>/<file>``) the manifest lists for the splits ``names``."""
    wanted = set(names)
    entries = json.loads(manifest.read_text(encoding="utf-8"))["entries"]
    return {str(e[key]) for e in entries if e["split"] in wanted for key in ("id", "file")}


# --------------------------------------------------------------------------------------------------
# The scan of a test module
# --------------------------------------------------------------------------------------------------


class Hit(NamedTuple):
    line: int
    what: str


def _text(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _names(node: ast.AST, final: set[str]) -> set[str]:
    """The final splits ``node`` names: a string constant, or the constants of a tuple, list or set literal."""
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return set().union(*(_names(element, final) for element in node.elts))
    text = _text(node)
    return {text} & final if text is not None else set()


def _reads_a_split(node: ast.AST) -> bool:
    """Whether ``node`` reads an entry's split: ``entry.split``, ``entry["split"]`` or a name ``split``."""
    if isinstance(node, ast.Attribute):
        return node.attr == "split"
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == "split"
    return isinstance(node, ast.Name) and node.id == "split"


def _called(node: ast.Call) -> str:
    """The last part of the called name: ``parametrize`` for ``pytest.mark.parametrize``."""
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""


def _argnames(node: ast.AST) -> set[str]:
    """The parameter names of ``pytest.mark.parametrize``: ``"split, n"`` or ``("split", "n")``."""
    if isinstance(node, ast.Tuple | ast.List):
        return {text.strip() for element in node.elts if (text := _text(element)) is not None}
    return {name.strip() for name in (_text(node) or "").split(",")}


def _selections(tree: ast.AST) -> list[ast.Compare]:
    """The comparisons that choose what a loop or a branch goes on with: in a comprehension's ``if`` or the test of an
    ``if`` (an ``assert`` on a value read is a check, not a choice)."""
    tests: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.comprehension):
            tests.extend(node.ifs)
        elif isinstance(node, ast.If | ast.IfExp | ast.While):
            tests.append(node.test)
    return [node for test in tests for node in ast.walk(test) if isinstance(node, ast.Compare)]


def letters_read(source: str, final: Iterable[str], letters: Iterable[str]) -> list[Hit]:
    """Where ``source`` reads letters of the ``final`` splits: a string naming one of ``letters`` (their ids and
    files), a comprehension or branch that selects entries by a final split's name, ``select_entries(…, split=…)``
    with one, or a ``split`` parameter that takes one."""
    wanted, listed = set(final), set(letters)
    folders = tuple(f"{split}/" for split in wanted)
    files = [letter for letter in listed if "/" in letter]
    tree = ast.parse(source)
    hits: list[Hit] = []
    for compare in _selections(tree):
        sides = [compare.left, *compare.comparators]
        for op, left, right in zip(compare.ops, sides, sides[1:], strict=False):
            for split_side, other in ((left, right), (right, left)):
                found = _names(other, wanted) if isinstance(op, ast.Eq | ast.In) else set()
                if found and _reads_a_split(split_side):
                    hits.append(Hit(compare.lineno, f"selects the letters of {', '.join(sorted(found))}"))
    for node in ast.walk(tree):
        text = _text(node)
        if text is not None and (
            text in listed
            or (any(folder in text for folder in folders) and any(file in text for file in files))
        ):
            hits.append(Hit(node.lineno, f"names a letter of a final split: {text!r}"))
        if isinstance(node, ast.Call) and _called(node) == "select_entries":
            for keyword in node.keywords:
                if keyword.arg == "split" and (found := _names(keyword.value, wanted)):
                    hits.append(Hit(node.lineno, f"selects the letters of {', '.join(sorted(found))}"))
        if isinstance(node, ast.Call) and _called(node) == "parametrize" and len(node.args) >= 2:
            if "split" in _argnames(node.args[0]):
                found = {text for element in ast.walk(node.args[1]) if (text := _text(element)) in wanted}
                if found:
                    hits.append(Hit(node.lineno, f"takes {', '.join(sorted(found))} as a split parameter"))
    return sorted(hits)


def _reader(path: Path) -> bool:
    return any(fnmatch(path.name, pattern) for pattern in READERS)


# --------------------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------------------


def _write(folder: Path, name: str, **meta: Any) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    data = {"meta": {"model": "claude-sonnet-5", "backend": "live", "partial": False, **meta}}
    (folder / name).write_text(json.dumps(data), encoding="utf-8")


def test_a_final_split_is_unrecorded_until_a_live_run_of_it_is_published(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    assert FINAL == ("holdout4", "newkinds")
    assert unrecorded_final_splits(results) == {"holdout4", "newkinds"}
    # not published, a replay, a partial run, files of other kinds: none records it
    _write(results / "pending", "2026-12-08-claude-sonnet-5-holdout4.json", split="holdout4")
    _write(results, "2026-12-08-claude-sonnet-5-newkinds-rescored.json", split="newkinds", backend="replay")
    _write(results, "2026-12-08-claude-sonnet-5-holdout4-partial.json", split="holdout4", partial=True)
    (results / "INDEX.json").write_text(json.dumps({"cells": []}), encoding="utf-8")
    (results / "notes.json").write_text("[1, 2]", encoding="utf-8")
    assert unrecorded_final_splits(results) == {"holdout4", "newkinds"}
    _write(results, "2026-12-09-claude-sonnet-5-holdout4-r2.json", split="holdout4", repeat=2)
    assert unrecorded_final_splits(results) == {"newkinds"}
    # the checked-out results: the earlier splits are recorded
    assert live_splits() >= {"dev", "test", "holdout", "holdout2", "holdout3"}


class _Letter(NamedTuple):
    id: str
    split: str


def test_the_census_reads_a_final_split_only_once_it_is_recorded(tmp_path: Path) -> None:
    """The census replays every recorded reading of the benchmark: a final split's letters join it with their
    split's published live run, never before (``tests/test_reading_gaps_census.py``)."""
    import test_reading_gaps_census as census

    letters = [
        _Letter("holdout3-a-J1", "holdout3"),
        _Letter("holdout4-a-K1", "holdout4"),
        _Letter("n-1", "newkinds"),
    ]
    results = tmp_path / "results"
    results.mkdir()
    assert [letter.id for letter in census.recorded_letters(letters, results)] == ["holdout3-a-J1"]
    _write(results, "2026-12-08-claude-sonnet-5-holdout4.json", split="holdout4")
    assert [letter.id for letter in census.recorded_letters(letters, results)] == [
        "holdout3-a-J1",
        "holdout4-a-K1",
    ]


def test_the_scan_finds_each_way_a_test_reads_a_final_split_s_letters() -> None:
    letters = {"holdout4-tax_assessment-K1", "holdout4/holdout4-tax_assessment-K1.pdf"}
    read = """\
import pytest
ONE = "holdout4-tax_assessment-K1"
FILE = ROOT / "evals/dataset/holdout4/holdout4-tax_assessment-K1.pdf"
mine = [e for e in entries if e.split == "holdout4"]
both = [e for e in entries if e["split"] in ("holdout3", "newkinds")]
picked = select_entries(manifest, split="holdout4")
@pytest.mark.parametrize("split", ["dev", "holdout4"])
def test_x(split): ...
@pytest.mark.parametrize(("split", "n"), [("newkinds", 1)])
def test_y(split, n): ...
for entry in entries:
    if entry.split == "holdout4":
        pass
"""
    hits = letters_read(read, FINAL, letters)
    assert hits == [
        (2, "names a letter of a final split: 'holdout4-tax_assessment-K1'"),
        (3, "names a letter of a final split: 'evals/dataset/holdout4/holdout4-tax_assessment-K1.pdf'"),
        (4, "selects the letters of holdout4"),
        (5, "selects the letters of newkinds"),
        (6, "selects the letters of holdout4"),
        (7, "takes holdout4 as a split parameter"),
        (9, "takes newkinds as a split parameter"),
        (12, "selects the letters of holdout4"),
    ]
    harmless = """\
assert splits.names()[-2:] == ("holdout4", "newkinds")
assert splits.get("holdout4").variants == ("K", "L", "M", "N")
others = [e for e in entries if e.split != "holdout4"]
made_up = {"id": "holdout4-x-K1", "split": "holdout4", "file": "holdout4/holdout4-x-K1.pdf"}
cell, run = "benchmark/holdout4/r1", f"holdout4-r{n}.json"
data["meta"].update(split="holdout4", repeat=2)
assert argv[argv.index("--split") + 1] == "holdout4"
assert source["split"] == "holdout4" and run.split == "newkinds"
@pytest.mark.parametrize("kind", ["holdout4"])
def test_z(kind): ...
"""
    assert letters_read(harmless, FINAL, letters) == []
    assert letters_read(read, (), ()) == []  # once both are recorded, nothing is scanned for


def test_no_test_reads_a_final_split_s_letters_before_its_recording() -> None:
    unrecorded = unrecorded_final_splits()
    letters = listed_letters(unrecorded)
    found = {
        path.relative_to(ROOT).as_posix(): hits
        for path in sorted(TESTS.rglob("*.py"))
        if not _reader(path) and (hits := letters_read(path.read_text(encoding="utf-8"), unrecorded, letters))
    }
    assert not found, (
        f"tests read letters of {', '.join(sorted(unrecorded))} before their recording is published: {found}"
    )


def test_no_results_file_shows_a_final_split_before_its_recording() -> None:
    """A replay of a final split written beside the results, or its rows in items.csv, would publish what Ordnung and
    the baselines do on letters whose recording is not published."""
    unrecorded = unrecorded_final_splits()
    shown = []
    for path in sorted(RESULTS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data.get("meta") if isinstance(data, dict) else None
        if isinstance(meta, dict) and meta.get("split") in unrecorded:
            shown.append(path.name)
    assert not shown, f"results files of a final split before a live run of it: {shown}"
    with (RESULTS / "items.csv").open(encoding="utf-8", newline="") as handle:
        rows = sum(1 for row in csv.DictReader(handle) if row["split"] in unrecorded)
    assert rows == 0, f"{rows} row(s) of items.csv for a final split before a live run of it"


def _ignored(path: str) -> bool:
    done = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT, check=False)
    assert done.returncode in (0, 1), path
    return done.returncode == 0


def test_a_pending_read_s_prediction_cache_is_never_committed() -> None:
    """A final read recorded into ``evals/results/pending/`` (``--results-dir``) keeps its per-letter prediction cache
    beside it, in ``pending/cache/`` (``evals/run.py``): ignored, so a checkpoint commits the pending results file and
    never the predictions cached for it."""
    assert _ignored("evals/results/pending/cache/2026-12-08-holdout4/one-letter.json")
    assert _ignored("evals/results/cache/2026-12-08-holdout4/one-letter.json")
    assert not _ignored("evals/results/pending/2026-12-08-claude-sonnet-5-holdout4.json")
