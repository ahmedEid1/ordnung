"""The final run's CI gates are its own replays. For every read of the final run with a published live results file
(each read of holdout4 and newkinds, and each run of the held-out Ask set), ``.github/workflows/ci.yml`` replays it
with thresholds at that read's replay, and ``evals/results/INDEX.json`` holds the same gate:

* a benchmark read: ``--min-accuracy`` is Ordnung's exact-date accuracy floored to 3 decimals, and
  ``--max-dangerous-late`` Ordnung's dangerously-late rate rounded up at 4 decimals (the flag takes a rate:
  ``evals/run.py``, ``gate_failures``);
* a held-out Ask run: ``--min-strict-accuracy`` is the strict answer accuracy floored to 3 decimals, and
  ``--max-harmful`` the number of harmful answers (a count: ``evals/ask/__main__.py``, ``strict_gate_failures``).

A read's numbers are its live results file's. ``make eval-reproduce`` holds the replay at HEAD to that file, and the
file's row in INDEX.json says so: the file's sha256, and for a benchmark read Ordnung's dates replayed the same with
the same dates right. A gate at any other threshold (set by hand), a second gate for one read, or a gate for a read not
published fails. While no final read is published and no gate names one, this skips.
"""

from __future__ import annotations

import hashlib
import json
import math
import shlex
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import splits  # noqa: E402

CI = ROOT / ".github" / "workflows" / "ci.yml"
RESULTS = ROOT / "evals" / "results"
#: The final run's splits: the registry's role ``final``.
FINAL = tuple(split.name for split in splits.REGISTRY if split.role == "final")
#: The Ask set of the final run.
ASK_SET = "heldout"
#: The commands a gate runs: a replay of the reading benchmark, or of the Ask set.
BENCHMARK_COMMANDS = ("ordnung eval", "-m evals.run")
ASK_COMMAND = "-m evals.ask"


@dataclass(frozen=True)
class Read:
    """One published live read of the final run: ``kind`` is ``benchmark`` (``split`` a final split) or ``ask``
    (``split`` the held-out set)."""

    kind: str
    split: str
    repeat: int
    file: str
    data: Mapping[str, Any]


@dataclass(frozen=True)
class Gate:
    """One gate command of the workflow: its kind, split (or Ask set), repeat and options (a flag maps to ``""``)."""

    kind: str
    split: str
    repeat: int
    options: Mapping[str, str]
    line: str
    #: Why the gate cannot fail (a shell operator or a redirection after its command, ``continue-on-error``), or
    #: ``None``.
    defeated: str | None = None


def final_reads(results_dir: Path) -> list[Read]:
    """The final run's published live reads: the results files directly in ``results_dir`` (``pending/`` is not
    published) of a final split's live, complete run, or of a live run of the held-out Ask set (the file of its
    three runs, ``…-final.json``, is not a run)."""
    reads = []
    for path in sorted(results_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        meta = data.get("meta")
        if isinstance(meta, dict) and meta.get("split") in FINAL:
            if meta.get("backend") == "live" and not meta.get("partial"):
                reads.append(Read("benchmark", meta["split"], int(meta.get("repeat", 1)), path.name, data))
        elif (
            data.get("benchmark") == "ask"
            and data.get("set") == ASK_SET
            and data.get("backend") == "live"
            and isinstance(data.get("questions"), list)
            and not path.name.endswith("-final.json")
        ):
            reads.append(Read("ask", ASK_SET, int(data.get("repeat", 1)), path.name, data))
    return reads


def floored(k: int, n: int, places: int) -> Fraction:
    """``k / n`` rounded down at ``places`` decimals."""
    return Fraction(math.floor(Fraction(k, n) * 10**places), 10**places)


def rounded_up(k: int, n: int, places: int) -> Fraction:
    """``k / n`` rounded up at ``places`` decimals."""
    return Fraction(math.ceil(Fraction(k, n) * 10**places), 10**places)


def thresholds(read: Read) -> dict[str, Fraction]:
    """The gate's thresholds that ``read``'s replay gives, by option."""
    if read.kind == "benchmark":
        ordnung = read.data["metrics"]["ordnung"]
        right, late = ordnung["due_date_accuracy"], ordnung["dangerous_late_rate"]
        return {
            "--min-accuracy": floored(int(right["k"]), int(right["n"]), 3),
            "--max-dangerous-late": rounded_up(int(late["k"]), int(late["n"]), 4),
        }
    summary = read.data["summary"]
    strict = summary["strict_accuracy"]
    return {
        "--min-strict-accuracy": floored(int(strict["k"]), int(strict["n"]), 3),
        "--max-harmful": Fraction(len(summary["harmful_answers"])),
    }


def number(text: object) -> Fraction | None:
    """A threshold as written (``"0.973"``, ``0.973``, ``"2"``), exactly; ``None`` if it is not a number."""
    try:
        return Fraction(Decimal(str(text)))
    except (InvalidOperation, ValueError, OverflowError):  # not a number, NaN, an infinity
        return None


def options(args: Sequence[str]) -> dict[str, str]:
    """``--name value`` and ``--name=value`` pairs of a command; a flag maps to ``""``."""
    found: dict[str, str] = {}
    for at, arg in enumerate(args):
        if not arg.startswith("--"):
            continue
        name, equals, value = arg.partition("=")
        if equals:
            found[name] = value
        elif at + 1 < len(args) and not args[at + 1].startswith("--"):
            found[name] = args[at + 1]
        else:
            found[name] = ""
    return found


def workflow_gates(workflow: Mapping[str, Any]) -> list[Gate]:
    """Every gate command of the final run in any job of ``workflow``: a benchmark replay of a final split
    (``ordnung eval`` or ``python -m evals.run``) or a replay of the held-out Ask set (``python -m evals.ask``)."""
    gates = []
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            allowed = job.get("continue-on-error") or step.get("continue-on-error")
            for line in str(step.get("run") or "").replace("\\\n", " ").splitlines():
                marker = next((m for m in (*BENCHMARK_COMMANDS, ASK_COMMAND) if m in line), None)
                if marker is None:
                    continue
                tail = line.split(marker, 1)[1]
                found = options(shlex.split(tail))
                defeated = _defeated(tail) or ("continue-on-error" if allowed else None)
                repeat = int(found.get("--repeat") or 1)
                if marker == ASK_COMMAND:
                    if found.get("--set") == ASK_SET:
                        gates.append(Gate("ask", ASK_SET, repeat, found, line.strip(), defeated))
                elif found.get("--split") in FINAL:
                    gates.append(Gate("benchmark", found["--split"], repeat, found, line.strip(), defeated))
    return gates


def _defeated(command: str) -> str | None:
    """The shell operator or redirection after a gate's command (its failure would not fail the step), or ``None``."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    for token in lexer:
        if token and all(char in "();<>|&" for char in token):
            return f"{token!r} after the command"
    return None


def _index_gate(read: Read, gates: Mapping[str, Any]) -> list[Mapping[str, str]]:
    """The gates of INDEX.json that stand for ``read``, as options: a benchmark read's ``benchmark/<split>/r<N>`` (or
    ``benchmark/<split>`` with that repeat, run 1 by default), a held-out Ask run's by the arguments it records."""
    found: list[Mapping[str, str]] = []
    for name, gate in gates.items():
        if not isinstance(gate, Mapping):
            continue
        if read.kind == "benchmark":
            own = name == f"benchmark/{read.split}/r{read.repeat}" or (
                name == f"benchmark/{read.split}" and int(gate.get("repeat", 1)) == read.repeat
            )
            if own:
                found.append(
                    {
                        "--min-accuracy": str(gate.get("min_accuracy")),
                        "--max-dangerous-late": str(gate.get("max_dangerous_late")),
                    }
                )
        elif isinstance(gate.get("args"), list):
            args = options([str(arg) for arg in gate["args"]])
            if args.get("--set") == ASK_SET and int(args.get("--repeat") or 1) == read.repeat:
                found.append(args)
    return found


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate_problems(
    reads: Sequence[Read], gates: Sequence[Gate], index: Mapping[str, Any], results_dir: Path
) -> list[str]:
    """What keeps each read's gates from being its replay's, in the workflow and in INDEX.json."""
    problems: list[str] = []
    rows = {row.get("file"): row for row in index.get("results") or [] if isinstance(row, Mapping)}
    for read in reads:
        label = f"{read.split} r{read.repeat} ({read.file})"
        want = thresholds(read)
        mine = [g for g in gates if (g.kind, g.split, g.repeat) == (read.kind, read.split, read.repeat)]
        if not mine:
            problems.append(f"{label}: no gate in ci.yml replays it")
        elif len(mine) > 1:
            problems.append(f"{label}: {len(mine)} gates in ci.yml replay it, not one")
        for gate in mine:
            if gate.defeated is not None:
                problems.append(f"{label}: its gate in ci.yml cannot fail ({gate.defeated})")
            for option, value in want.items():
                if number(gate.options.get(option)) != value:
                    problems.append(
                        f"{label}: ci.yml has {option} {gate.options.get(option)!r}, its replay gives {float(value)}"
                    )
            today = gate.options.get("--today")
            if read.kind == "ask" and today is not None and today != read.data.get("today"):
                problems.append(
                    f"{label}: ci.yml replays it for {today}, it was recorded for {read.data.get('today')}"
                )
        indexed = _index_gate(read, index.get("gates") or {})
        if len(indexed) != 1:
            problems.append(f"{label}: {len(indexed)} gates in INDEX.json stand for it, not one")
        for gate_options in indexed:
            for option, value in want.items():
                if number(gate_options.get(option)) != value:
                    problems.append(
                        f"{label}: INDEX.json has {option} {gate_options.get(option)!r}, its replay gives "
                        f"{float(value)}"
                    )
        row = rows.get(read.file)
        if row is None or row.get("sha256") != _sha256(results_dir / read.file):
            problems.append(f"{label}: INDEX.json has no row for the file as it is")
        elif read.kind == "benchmark":
            ordnung = (row.get("conditions") or {}).get("ordnung") or {}
            right = read.data["metrics"]["ordnung"]["due_date_accuracy"]
            replayed = [int(x) for x in ordnung.get("right_at_head") or []]
            if ordnung.get("verdict") not in ("exact", "same-dates") or replayed != [
                int(right["k"]),
                int(right["n"]),
            ]:
                problems.append(f"{label}: INDEX.json does not hold Ordnung's replay at HEAD to the file")
    published = {(read.kind, read.split, read.repeat) for read in reads}
    for gate in gates:
        if (gate.kind, gate.split, gate.repeat) not in published:
            problems.append(f"a gate for {gate.split} r{gate.repeat}, a read not published: {gate.line}")
    return problems


# --------------------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------------------


def test_the_thresholds_are_the_replay_floored_or_rounded_up() -> None:
    assert floored(109, 112, 3) == Fraction(973, 1000)  # 0.97321…
    assert floored(49, 50, 3) == Fraction(98, 100)  # exactly 0.98 stays 0.98
    assert floored(2, 3, 3) == Fraction(666, 1000)  # down, never to the nearest
    assert rounded_up(2, 112, 4) == Fraction(179, 10000)  # 0.017857… is a rate, not the count 2
    assert rounded_up(1, 112, 4) == Fraction(90, 10000)  # up, never to the nearest
    assert rounded_up(1, 16, 4) == Fraction(625, 10000) and rounded_up(0, 112, 4) == 0
    assert (
        number("0.0179") == Fraction(179, 10000) and number(0.973) == Fraction(973, 1000) and number("2") == 2
    )
    assert number(None) is None and number("") is None and number("x") is None
    assert number("nan") is None and number("inf") is None and number("-Infinity") is None


def _run(split: str, repeat: int, right: tuple[int, int], late: tuple[int, int]) -> dict[str, Any]:
    return {
        "meta": {
            "split": split,
            "repeat": repeat,
            "backend": "live",
            "partial": False,
            "model": "claude-sonnet-5",
        },
        "metrics": {
            "ordnung": {
                "due_date_accuracy": {"k": float(right[0]), "n": float(right[1])},
                "dangerous_late_rate": {"k": float(late[0]), "n": float(late[1])},
            }
        },
    }


def _ask(repeat: int, strict: tuple[int, int], harmful: list[str]) -> dict[str, Any]:
    return {
        "benchmark": "ask",
        "schema": 2,
        "set": ASK_SET,
        "repeat": repeat,
        "backend": "live",
        "today": "2026-12-08",
        "summary": {
            "strict_accuracy": {"k": float(strict[0]), "n": float(strict[1])},
            "harmful_answers": harmful,
        },
        "questions": [],
        "attacks": [],
    }


WORKFLOW = """\
jobs:
  backend-slow:
    steps:
      - name: Benchmark replayed (earlier splits)
        run: .venv/bin/ordnung eval --split holdout --conditions ordnung --min-accuracy 0.98 --max-dangerous-late 0
      - name: Final run replayed
        run: |
          .venv/bin/ordnung eval --split holdout4 --repeat 1 --conditions ordnung --min-accuracy 0.973 \\
            --max-dangerous-late 0.0179 --quiet
          .venv/bin/ordnung eval --split holdout4 --repeat 2 --conditions ordnung --min-accuracy 0.964 --max-dangerous-late 0 --quiet
          .venv/bin/ordnung eval --split newkinds --conditions ordnung --min-accuracy 0.928 --max-dangerous-late 0 --quiet
      - name: Ask benchmark (replayed)
        run: >-
          .venv/bin/python -m evals.ask --min-accuracy 0.85 --min-strict-accuracy 0.86 --max-harmful 6 --check-docs
      - name: Held-out Ask replayed
        run: .venv/bin/python -m evals.ask --set heldout --today 2026-12-08 --min-strict-accuracy 0.798 --max-harmful 2
"""


def _published(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    """Four live reads (holdout4 r1 and r2, newkinds, held-out Ask r1) with INDEX.json rows and gates to match."""
    results = tmp_path / "results"
    results.mkdir()
    files = {
        "2026-12-08-claude-sonnet-5-holdout4.json": _run("holdout4", 1, (109, 112), (2, 112)),
        "2026-12-09-claude-sonnet-5-holdout4-r2.json": _run("holdout4", 2, (108, 112), (0, 112)),
        "2026-12-08-claude-sonnet-5-newkinds.json": _run("newkinds", 1, (26, 28), (0, 28)),
        "2026-12-08-claude-sonnet-5-ask-heldout.json": _ask(1, (83, 104), ["ho-a", "ho-b"]),
    }
    rows = []
    for name, data in files.items():
        (results / name).write_text(json.dumps(data), encoding="utf-8")
        row: dict[str, Any] = {"file": name, "sha256": _sha256(results / name)}
        if "meta" in data:
            right = data["metrics"]["ordnung"]["due_date_accuracy"]
            row["conditions"] = {
                "ordnung": {"verdict": "exact", "right_at_head": [int(right["k"]), int(right["n"])]}
            }
        rows.append(row)
    # what is not a published read: a pending checkpoint, a replay, the file of three Ask runs
    (results / "pending").mkdir()
    (results / "pending" / "2026-12-10-claude-sonnet-5-holdout4-r3.json").write_text(
        json.dumps(_run("holdout4", 3, (1, 2), (1, 2))), encoding="utf-8"
    )
    replay = {**_run("newkinds", 1, (1, 2), (1, 2)), "meta": {"split": "newkinds", "backend": "replay"}}
    (results / "2026-12-12-claude-sonnet-5-newkinds-rescored.json").write_text(
        json.dumps(replay), encoding="utf-8"
    )
    (results / "2026-12-12-claude-sonnet-5-ask-heldout-final.json").write_text(
        json.dumps({**_ask(1, (1, 2), []), "kind": "ask-heldout-final"}), encoding="utf-8"
    )
    index = {
        "gates": {
            "benchmark/holdout": {"min_accuracy": 0.98, "max_dangerous_late": 0.0},
            "benchmark/holdout4": {"min_accuracy": 0.973, "max_dangerous_late": 0.0179},
            "benchmark/holdout4/r2": {"min_accuracy": 0.964, "max_dangerous_late": 0.0},
            "benchmark/newkinds": {"min_accuracy": 0.928, "max_dangerous_late": 0.0},
            "ask/dev": {
                "args": ["--min-accuracy", "0.85", "--min-strict-accuracy", "0.86", "--max-harmful", "6"]
            },
            "ask/heldout": {
                "args": [
                    "--set",
                    "heldout",
                    "--today",
                    "2026-12-08",
                    "--min-strict-accuracy",
                    "0.798",
                    "--max-harmful",
                    "2",
                ]
            },
        },
        "results": rows,
    }
    return results, index


def _problems(results: Path, index: Mapping[str, Any], workflow: str = WORKFLOW) -> list[str]:
    yaml = pytest.importorskip("yaml")  # PyYAML comes with uvicorn[standard]
    return gate_problems(final_reads(results), workflow_gates(yaml.safe_load(workflow)), index, results)


def test_gates_at_each_read_s_replay_hold(tmp_path: Path) -> None:
    results, index = _published(tmp_path)
    reads = final_reads(results)
    assert sorted((r.kind, r.split, r.repeat) for r in reads) == [
        ("ask", "heldout", 1),
        ("benchmark", "holdout4", 1),
        ("benchmark", "holdout4", 2),
        ("benchmark", "newkinds", 1),
    ]
    assert _problems(results, index) == []


def test_a_threshold_set_by_hand_fails(tmp_path: Path) -> None:
    results, index = _published(tmp_path)
    lowered = WORKFLOW.replace("--min-accuracy 0.964", "--min-accuracy 0.95")
    assert _problems(results, index, lowered) == [
        "holdout4 r2 (2026-12-09-claude-sonnet-5-holdout4-r2.json): ci.yml has --min-accuracy '0.95', its replay "
        "gives 0.964"
    ]
    # the dangerously-late count where the flag takes a rate
    count = WORKFLOW.replace("--max-dangerous-late 0.0179", "--max-dangerous-late 2")
    assert len(_problems(results, index, count)) == 1
    # a rate rounded the usual way, not up, lets a replay that is worse than the recording pass
    nearest = WORKFLOW.replace("--max-dangerous-late 0.0179", "--max-dangerous-late 0.0178")
    assert len(_problems(results, index, nearest)) == 1
    harm = WORKFLOW.replace("--max-harmful 2", "--max-harmful 3")
    assert _problems(results, index, harm) == [
        "heldout r1 (2026-12-08-claude-sonnet-5-ask-heldout.json): ci.yml has --max-harmful '3', its replay gives 2.0"
    ]
    other_day = WORKFLOW.replace("--today 2026-12-08", "--today 2026-12-09")
    assert len(_problems(results, index, other_day)) == 1


def test_a_missing_doubled_or_early_gate_fails(tmp_path: Path) -> None:
    results, index = _published(tmp_path)
    without = WORKFLOW.replace(
        "          .venv/bin/ordnung eval --split newkinds --conditions ordnung --min-accuracy 0.928 "
        "--max-dangerous-late 0 --quiet\n",
        "",
    )
    assert _problems(results, index, without) == [
        "newkinds r1 (2026-12-08-claude-sonnet-5-newkinds.json): no gate in ci.yml replays it"
    ]
    twice = (
        WORKFLOW
        + "      - run: .venv/bin/python -m evals.run --split newkinds --min-accuracy 0.928 --max-dangerous-late 0\n"
    )
    assert _problems(results, index, twice) == [
        "newkinds r1 (2026-12-08-claude-sonnet-5-newkinds.json): 2 gates in ci.yml replay it, not one"
    ]
    early = (
        WORKFLOW
        + "      - run: .venv/bin/ordnung eval --split holdout4 --repeat 3 --min-accuracy 0.9 --max-dangerous-late 0\n"
    )
    (problem,) = _problems(results, index, early)
    assert problem.startswith("a gate for holdout4 r3, a read not published:")


def test_a_gate_that_cannot_fail_fails(tmp_path: Path) -> None:
    """A gate at the replay's thresholds whose failure the shell or the step throws away (``|| true``, a pipe, a
    redirection, ``continue-on-error``) holds nothing: it is refused like a threshold moved by hand."""
    results, index = _published(tmp_path)
    for tail in (" || true", " || echo ignored", "; true", " | cat", " > /dev/null", " &"):
        defeated = WORKFLOW.replace(
            "--min-accuracy 0.964 --max-dangerous-late 0 --quiet",
            f"--min-accuracy 0.964 --max-dangerous-late 0 --quiet{tail}",
        )
        assert defeated != WORKFLOW
        (problem,) = _problems(results, index, defeated)
        assert problem.startswith("holdout4 r2 (") and "cannot fail" in problem, (tail, problem)
    ask = WORKFLOW.replace("--max-harmful 2\n", "--max-harmful 2 || echo ignored\n")
    assert ask != WORKFLOW
    (problem,) = _problems(results, index, ask)
    assert problem.startswith("heldout r1 (") and "cannot fail" in problem
    allowed = WORKFLOW.replace(
        "      - name: Final run replayed\n",
        "      - name: Final run replayed\n        continue-on-error: true\n",
    )
    assert allowed != WORKFLOW
    assert any("cannot fail" in problem for problem in _problems(results, index, allowed))


def test_the_index_holds_the_same_gate_for_the_file_as_it_is(tmp_path: Path) -> None:
    results, index = _published(tmp_path)
    collapsed = json.loads(json.dumps(index))
    del collapsed["gates"]["benchmark/holdout4/r2"]  # one gate per split: r2's is missing
    assert _problems(results, collapsed) == [
        "holdout4 r2 (2026-12-09-claude-sonnet-5-holdout4-r2.json): 0 gates in INDEX.json stand for it, not one"
    ]
    by_hand = json.loads(json.dumps(index))
    by_hand["gates"]["benchmark/newkinds"]["min_accuracy"] = 0.9
    assert len(_problems(results, by_hand)) == 1
    stale = json.loads(json.dumps(index))
    stale["results"][0]["sha256"] = "0" * 64
    assert _problems(results, stale) == [
        "holdout4 r1 (2026-12-08-claude-sonnet-5-holdout4.json): INDEX.json has no row for the file as it is"
    ]
    moved = json.loads(json.dumps(index))
    moved["results"][1]["conditions"]["ordnung"].update(verdict="changed", right_at_head=[107, 112])
    assert _problems(results, moved) == [
        "holdout4 r2 (2026-12-09-claude-sonnet-5-holdout4-r2.json): INDEX.json does not hold Ordnung's replay at "
        "HEAD to the file"
    ]


def test_the_index_reproduce_writes_from_ci_yml_holds_a_gate_per_read(tmp_path: Path) -> None:
    """INDEX.json's gates are what ``python -m evals.reproduce --write`` reads from ci.yml (``reproduce.ci_gates``).
    From a workflow with one gate per read (two holdout4 reads at their own thresholds, newkinds, a held-out Ask
    run), it must give the index one gate per read, and keep the Ask benchmark's own gate the development set's."""
    yaml = pytest.importorskip("yaml")  # PyYAML comes with uvicorn[standard]
    from evals import reproduce

    results, index = _published(tmp_path)
    one_line = WORKFLOW.replace(" \\\n            --max-dangerous-late", " --max-dangerous-late")
    workflow = tmp_path / "ci.yml"
    workflow.write_text(one_line, encoding="utf-8")  # reproduce reads a gate command on one line
    written = reproduce.ci_gates(workflow)
    reads, gates = final_reads(results), workflow_gates(yaml.safe_load(one_line))
    assert gate_problems(reads, gates, index, results) == []  # the workflow holds a gate per read
    assert gate_problems(reads, gates, {**index, "gates": written}, results) == []
    assert "heldout" not in written["ask/dev"]["args"]


def test_the_final_run_s_gates_are_its_replays() -> None:
    yaml = pytest.importorskip("yaml")  # PyYAML comes with uvicorn[standard]
    reads = final_reads(RESULTS)
    gates = workflow_gates(yaml.safe_load(CI.read_text(encoding="utf-8")))
    if not reads and not gates:
        pytest.skip("no read of the final run is published yet, and no gate names one")
    index = json.loads((RESULTS / "INDEX.json").read_text(encoding="utf-8"))
    assert gate_problems(reads, gates, index, RESULTS) == []
