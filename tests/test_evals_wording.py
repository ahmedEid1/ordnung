"""The evaluation's code says why a thing is so, not which plan item, review or batch asked for it.

The evaluation plan, its addendum and the runbook are not in this repository, so a reader cannot follow a reference
to them: a plan item (``EV8``) or section, the addendum's items, a review or review round, a development batch (E2's,
E3a), a runbook commit (``commit A``) or step (``R7``), a design document's weakness or a batch's guard id. This test
reads the evaluation's code (``evals/**/*.py``), the stress cells' README, ``scripts/eval_perturb.py``, the ``needs``
of the results index's cells and every test's skip reason for those tags. It prints where a tag is and which kind,
never the line.

Kept on purpose, and allowed here by name:

* the Ask development set's chronology (:data:`evals.ask.report.NOTES`), the published history that makes the set
  not held out; results files carry it as recorded;
* the development set's label (``LABELS["dev"]``), a disclosure with no id;
* the three notes :mod:`evals.ask.report` writes into the published re-scorings (``SCHEMA_2_NOTE``, the gate's note
  and the answer check's note), which the re-scored files and ``docs/evals-ask.md`` carry as written;
* ``R1 R2 R3``, the metavariables of three runs or reads.

Subject matter that looks alike matches no pattern: the end-to-end endpoint E2, letter ids such as ``…-E2``, the
pre-registration's phase 2, the blind review of the items a condition got wrong, the format ids ``ev8-…``.
"""

from __future__ import annotations

import ast
import bisect
import json
import re
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: What a process tag looks like, by kind.
TAGS = {
    "a plan item or section": re.compile(
        r"\bEV\d+\b|\bplan §|\(§\d[\d.]*\)|\bevaluation plan\b|\bthe plan's\b"
    ),
    "the plan's addendum": re.compile(r"\baddendum, item\b"),
    "a review": re.compile(r"(?i:\breview rounds?\b|\bfinal review\b|\breviewer's\b)"),
    "a development batch": re.compile(r"\bE2's\b|\bThe E2\b|, E2\)|(?i:(?<![0-9a-f])e3a(?![0-9a-f]))"),
    "a runbook commit": re.compile(r"\bcommit [AB]\b"),
    "a design weakness or a guard id": re.compile(r"\bweakness \d|\bG1 guard\b"),
    "a runbook step": re.compile(r"(?<!R2 )\bR[367]\b"),
}
#: Folders under ``evals/`` that hold data, not the evaluation's code.
DATA_DIRS = frozenset({"dataset", "recorded", "prompts", "results"})
ASK_REPORT = "evals/ask/report.py"


def _sources() -> list[Path]:
    code = sorted(
        path
        for path in (ROOT / "evals").rglob("*.py")
        if not DATA_DIRS & set(path.relative_to(ROOT / "evals").parts[:-1])
    )
    return [*code, ROOT / "evals" / "perturb" / "README.md", ROOT / "scripts" / "eval_perturb.py"]


def _flat(text: str) -> tuple[str, list[int]]:
    """The text as one line (indentation and comment marks gone, so a tag split over two lines is still seen),
    with where each line starts in it."""
    starts: list[int] = []
    parts: list[str] = []
    at = 0
    for line in text.splitlines():
        part = re.sub(r"^\s*(?:#:?\s*)?", "", line)
        starts.append(at)
        parts.append(part)
        at += len(part) + 1
    return " ".join(parts), starts


def _tags(text: str) -> Iterator[tuple[int, str, str]]:
    """``(line, kind, tag)`` of every process tag in ``text`` (lines from 1)."""
    flat, starts = _flat(text)
    for kind, pattern in TAGS.items():
        for match in pattern.finditer(flat):
            yield bisect.bisect_right(starts, match.start()), kind, match.group(0)


def _kept_lines(tree: ast.Module) -> dict[str, range]:
    """The lines of ``evals/ask/report.py`` kept on purpose, by name (see the module docstring)."""
    kept: dict[str, range] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {target.id for target in targets if isinstance(target, ast.Name)}
            for name in sorted(names & {"NOTES", "SCHEMA_2_NOTE"}):
                assert node.value is not None
                kept[name] = range(node.value.lineno, (node.value.end_lineno or node.value.lineno) + 1)
            if "LABELS" in names and isinstance(node.value, ast.Dict):
                for key, value in zip(node.value.keys, node.value.values, strict=True):
                    if isinstance(key, ast.Constant) and key.value == "dev":
                        kept['LABELS["dev"]'] = range(value.lineno, (value.end_lineno or value.lineno) + 1)
        if isinstance(node, ast.FunctionDef) and node.name in ("_gate_note", "_answer_check_note"):
            returns = [stmt for stmt in node.body if isinstance(stmt, ast.Return) and stmt.value is not None]
            for stmt in returns[-1:]:
                kept[node.name] = range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1)
    return kept


def _found_in_sources() -> list[str]:
    found = []
    kept = _kept_lines(ast.parse((ROOT / ASK_REPORT).read_text(encoding="utf-8")))
    for path in _sources():
        name = path.relative_to(ROOT).as_posix()
        for line, kind, tag in _tags(path.read_text(encoding="utf-8")):
            if name == ASK_REPORT and any(line in lines for lines in kept.values()):
                continue
            found.append(f"{name}:{line}: {kind} ({tag})")
    return found


def _needs(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "needs" and isinstance(item, str):
                yield item
            else:
                yield from _needs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _needs(item)


def _skip_reasons() -> Iterator[tuple[str, int, str]]:
    """``(file, line, reason)`` of every skip, skip mark and expected failure in ``tests/``."""
    calls = {"pytest.skip", "pytest.mark.skip", "pytest.mark.skipif", "pytest.xfail", "pytest.mark.xfail"}
    for path in sorted((ROOT / "tests").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or ast.unparse(node.func) not in calls:
                continue
            texts = [
                *node.args,
                *(keyword.value for keyword in node.keywords if keyword.arg in ("reason", "msg")),
            ]
            for text in texts:
                if isinstance(text, ast.Constant) and isinstance(text.value, str):
                    yield path.relative_to(ROOT).as_posix(), node.lineno, text.value


def test_the_evaluation_s_code_names_no_plan_item_review_or_batch() -> None:
    assert len(_sources()) > 50  # the scan reads the evaluation's code, not an empty folder
    found = _found_in_sources()
    assert not found, "process tags (say why instead):\n" + "\n".join(found)


def test_the_kept_history_is_where_the_allow_list_says() -> None:
    """The allow-list names things that exist: a rename would otherwise let a tag through unseen."""
    kept = _kept_lines(ast.parse((ROOT / ASK_REPORT).read_text(encoding="utf-8")))
    assert set(kept) == {"NOTES", "SCHEMA_2_NOTE", 'LABELS["dev"]', "_gate_note", "_answer_check_note"}
    assert len(kept["NOTES"]) > 100  # the chronology, kept whole


def test_the_results_index_s_cells_need_no_plan_item() -> None:
    index = json.loads((ROOT / "evals" / "results" / "INDEX.json").read_text(encoding="utf-8"))
    needs = sorted(set(_needs(index)))
    assert needs  # cells not recorded yet say what they need
    found = [f"{need!r}: {kind} ({tag})" for need in needs for _, kind, tag in _tags(need)]
    assert not found, "\n".join(found)


def test_no_skip_reason_names_a_plan_item_or_a_runbook_commit() -> None:
    found = [
        f"{name}:{line}: {kind} ({tag})"
        for name, line, reason in _skip_reasons()
        for _, kind, tag in _tags(reason)
    ]
    assert not found, "\n".join(found)


def test_the_patterns_see_the_tags_and_not_the_subject_matter() -> None:
    tagged = [
        "the final run (plan EV9)",
        "(plan §7, R3 and R6)",
        "(the evaluation plan's\n    addendum, item 8)",
        "review round 3 of phase 2",
        "Final review",
        "E2's household copy",
        "E3A_RESCORING",
        "_e3a_check_note",
        "(an open date called passed, E2)",
        "EV8's commit A",
        "the harness design's weakness 2",
        "(tools wrap it: E2's G1 guard)",
        "the cells' recording (plan §7, R7)",
        "The pre-registered decision rules (§6.11)",
    ]
    for text in tagged:
        assert list(_tags(text)), text
    plain = [
        "the end-to-end endpoint E2 reminded in time (E2)",
        "holdout-invoice_relative-E2",
        "the pre-registration's phase 2",
        "the blind review of the items any condition got wrong",
        "--final R1 R2 R3 --write",
        "--noise-floor-from-runs R1 R2 R3",
        '"format": "ev8-derived/1"',
        "SPEC §12c",
        "§ 556 BGB",
        "sha256 4be3a91c",
    ]
    for text in plain:
        assert not list(_tags(text)), text
