"""``make eval-reproduce``: every published number replayed from the recordings, with no model call, and compared
with ``evals/results/INDEX.json`` (``python -m evals.reproduce --check | --write``).

One command instead of seven. In a temporary folder, a few at a time, it replays:

* every recorded split with every condition (``evals.run``), and each repeat and final split once its recording
  exists; every per-letter results file of the pinned model is compared with the replay of its split, letter by
  letter and item by item;
* the replay without the sender's Land (``scripts/eval_without_land.py``), compared with the published file;
* the Ask benchmark, development set (and the held-out set once recorded), with the CI gate's thresholds and
  ``--check-docs``;
* each end-to-end run (``evals.e2e --compare``), each check ablation (``scripts/eval_ablate_checks.py --check``) and
  each stress run (``scripts/eval_perturb.py --check``) that has a results file;

then checks that the analysis (``evals.analysis --check``) and the presenter's pages (``evals.present --check``) are
what the results render, and that ``evals/results/items.csv`` is what the results files give (:mod:`evals.export`).
A cell whose recording is made after the code freeze (holdout4's three reads, newkinds, held-out Ask, the stress
cells) is listed as *not recorded yet*, never faked. It prints one scoreboard.

**INDEX.json** has one row per results file: its sha256, its role (the presenter's, :mod:`evals.present.model`), when
and how it was recorded, how this command checks it, and the verdict of the replay at HEAD — ``exact``,
``same-dates`` (every scored date and outcome equal, and the counts the pages read too; the fields that differ are
listed as drift: added since, removed, or other values) or ``changed``. A changed date is listed with the fix that
changed it (``because``: a commit, an ADR or the re-scored results file that shows it), written by a person:
``--write`` records a new change with an empty reason, and ``--check`` fails until it is declared. So is a count the
pages and gates read (dates right, late, missed) that moved by more than its dates did. Each condition also pins a
digest of the replay's metrics (``metrics_at_head``), so a number cannot move under a field that already drifts by
name: ``--check`` fails when it moves, and ``--write`` records the move with an empty reason (``metrics_moved``). A run of another model can't be replayed (its
recordings are not in the repository) and an older summary is superseded: both are checked by hash. A live Ask run as
recorded is never rewritten, and ``--check-docs`` checks it with the answers its own day's check gave, read from the
file: so its sha256 is pinned like a replay's metrics (by its row in the index too, so bytes rewritten to say they
are a re-scoring stay pinned) — ``--check`` fails when it moves, and ``--write`` records the move with an empty
reason (``sha256_moved``). The index also
pins the dataset's and the recordings' hashes, the CI gates (read from ``.github/workflows/ci.yml``) and every cell.

``--check`` exits 1 on any difference INDEX.json doesn't declare, a hash that moved, a failed check, a gate missed or a
stale ``items.csv``; 2 when the index is missing or a results file is of a kind nothing knows. ``--write`` rewrites the
index's computed fields (keeping every declared reason) and ``items.csv``, for a pull request that changes numbers on
purpose: its diff shows what moved.

A replay never reaches a model: with no ``ORDNUNG_CLAUDE_BIN`` the children get a path that doesn't exist, so a
stray call fails as "not installed"; nothing is written into the checkout but by ``--write``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from evals import export, harness, splits
from evals.present import PresentError
from evals.present import model as present_model
from evals.records import CONDITIONS
from evals.run import DATASET_DIR, DEFAULT_MODEL, RECORDED_DIR, RESULTS_DIR, ROOT

INDEX_NAME = "INDEX.json"
INDEX_PATH = RESULTS_DIR / INDEX_NAME
INDEX_SCHEMA = "ordnung-eval-index/1"
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"
ABOUT = (
    "Every results file with its sha256, role, recording and how `make eval-reproduce` checks it, the replay's "
    "verdict at HEAD and every changed date with the fix that changed it; the dataset's and the recordings' hashes, "
    "the CI gates and every cell. Written by `python -m evals.reproduce --write`; a change's `because` by a person."
)
#: The final run's reads per split (plan §6.2): each one a cell, *not recorded yet* until its results file exists.
FINAL_READS = {"holdout4": 3, "newkinds": 1}
ASK_HELDOUT_READS = 3
STRESS_CELLS = ("I1", "D1")
#: The planned cells that replay the final run's readings another way (plan EV9).
FINAL_E2E = ("holdout4", "newkinds")
FINAL_ABLATION = ("holdout4",)
#: What a run measures itself, never part of a comparison: the code's fingerprint, the wall-clock time and whether
#: the answer was live or replayed.
VOLATILE = frozenset({"prediction.fingerprint", "prediction.calls[].wall_ms", "prediction.calls[].backend"})
#: Drift is named down to this many parts of its path (``metrics.extraction``, ``prediction.calls[]``).
DRIFT_DEPTH = 2
VERDICTS = ("exact", "same-dates", "changed")
#: Roughly how long each kind of task takes (seconds, 4 cores): the longest start first.
WEIGHTS = {
    "without-land": 190,
    "e2e": 165,
    "ablation": 120,
    "stress": 120,
    "ask": 50,
    "benchmark": 30,
    "analysis": 5,
    "presenter": 6,
}
Say = Callable[[str], None]
_ASK_NAME = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<model>.+?)-ask(?P<heldout>-heldout)?(?:-r(?P<repeat>\d+))?"
    r"(?P<rescored>-rescored)?\.json$"
)
_HIDDEN = (".bad", ".tmp")


class ReproduceError(RuntimeError):
    """The inputs don't fit (a missing or unreadable index, a results file of an unknown kind): exit 2."""


@dataclass(frozen=True)
class Task:
    """One zero-token command: a replay into ``out`` (``None``: a check that only reads)."""

    name: str
    argv: list[str]
    out: Path | None = None
    #: Where its output goes (``None``: a temporary file).
    log: Path | None = None


@dataclass(frozen=True)
class Done:
    name: str
    rc: int
    seconds: float
    log: Path


# --------------------------------------------------------------------------------------------------
# Hashes and the static index (no replay)
# --------------------------------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree(folder: Path) -> list[Path]:
    return sorted(
        path
        for path in folder.rglob("*")
        if path.is_file()
        and not any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(folder).parts)
        and not path.name.endswith(_HIDDEN)
    )


def tree_sha256(folder: Path, files: Iterable[Path] | None = None) -> str:
    """sha256 over every file's relative path and sha256 (hidden files, set-aside and half-written ones left out)."""
    digest = hashlib.sha256()
    for path in files if files is not None else _tree(folder):
        digest.update(f"{path.relative_to(folder).as_posix()}\0{sha256_file(path)}\n".encode())
    return digest.hexdigest()


def dataset_info(dataset_dir: Path = DATASET_DIR) -> dict[str, Any]:
    files = _tree(dataset_dir)
    return {
        "manifest_sha256": sha256_file(dataset_dir / "manifest.json"),
        "files": len(files),
        "tree_sha256": tree_sha256(dataset_dir, files),
    }


def _served_by(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    response = data.get("response") if isinstance(data, dict) else None
    return response.get("model") if isinstance(response, dict) else None


def recordings_info(recorded_dir: Path = RECORDED_DIR, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """Per recordings folder: its cassettes by purpose, how many a replay at HEAD asks for (the request lock's
    entries) and how many only an earlier run did, who answered them, and the hashes of the folder and its locks."""
    info: dict[str, Any] = {}
    for name in (model, f"ask/{model}", f"ask-heldout/{model}", f"stress/{model}"):
        folder = recorded_dir / name
        if not folder.is_dir():
            continue
        files = _tree(folder)
        cassettes = [path for path in files if path.parent != folder]
        lock = folder / harness.LOCK_FILE
        locked: dict[str, Any] = json.loads(lock.read_text(encoding="utf-8")) if lock.is_file() else {}
        keys = {f"{path.parent.name}/{path.name.split('.', 1)[0]}" for path in cassettes}
        served = Counter(_served_by(path) == model for path in cassettes)
        ledger = folder / harness.LEDGER_FILE
        info[name] = {
            "cassettes": len(cassettes),
            "by_purpose": dict(sorted(Counter(path.parent.name for path in cassettes).items())),
            "locked": len(keys & locked.keys()),
            "history_only": len(keys - locked.keys()),
            "served_by_pinned_model": served[True],
            "served_by_another_model": served[False],
            "tree_sha256": tree_sha256(folder, files),
            "requests_lock_sha256": sha256_file(lock) if lock.is_file() else None,
            "prompts_lock_sha256": sha256_file(folder / "prompts.lock.json")
            if (folder / "prompts.lock.json").is_file()
            else None,
            "ledger_lines": len(ledger.read_text(encoding="utf-8").splitlines()) if ledger.is_file() else 0,
        }
    return info


def _options(args: Sequence[str]) -> dict[str, list[str]]:
    """``--name value …`` → ``{"--name": [values]}`` (a flag without values maps to ``[]``)."""
    found: dict[str, list[str]] = {}
    current: str | None = None
    for arg in args:
        if arg.startswith("--"):
            current = arg
            found[current] = []
        elif current is not None:
            found[current].append(arg)
    return found


def ci_gates(path: Path = CI_PATH) -> dict[str, Any]:
    """The gates the ``backend-slow`` job of ``ci.yml`` runs: each split's replay (``benchmark/<split>``), the Ask
    benchmark's arguments (``ask/dev``) and the published file the replay without the Land must equal."""
    try:
        import yaml  # PyYAML comes with uvicorn[standard]
    except ImportError as exc:  # pragma: no cover - a dependency of the app
        raise ReproduceError("reading the CI gates needs PyYAML (it comes with uvicorn[standard])") from exc
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    gates: dict[str, Any] = {}
    for step in workflow["jobs"]["backend-slow"]["steps"]:
        run = str(step.get("run", ""))
        for line in run.splitlines():
            if "ordnung eval" not in line:
                continue
            options = _options(shlex.split(line.split("ordnung eval", 1)[1]))
            split = (options.get("--split") or ["test"])[0]
            gates[f"benchmark/{split}"] = {
                "conditions": options.get("--conditions") or "all",
                "min_accuracy": float(options["--min-accuracy"][0]),
                "max_dangerous_late": float(options["--max-dangerous-late"][0]),
            }
        if "-m evals.ask" in run:
            gates["ask/dev"] = {"args": shlex.split(run.split("-m evals.ask", 1)[1])}
        if "eval_without_land" in run:
            gates["without-land"] = {"published": Path(step["env"]["PUBLISHED"]).name}
    return dict(sorted(gates.items()))


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReproduceError(f"{path.name}: not a readable results file ({exc})") from exc
    if not isinstance(data, dict):
        raise ReproduceError(f"{path.name}: not a results file")
    return data


def _kind(name: str, data: Mapping[str, Any]) -> tuple[str, str]:
    """``(kind, role)`` of one results file: the presenter's, plus the stress run it doesn't render yet."""
    schema = data.get("schema")
    if isinstance(schema, str) and schema.startswith("ordnung-eval-stress/"):
        return "stress", "final"
    try:
        return present_model.kind_of(name, data), present_model.role_of(name, data)
    except PresentError as exc:
        raise ReproduceError(str(exc)) from exc


def _row(path: Path, data: Mapping[str, Any], kind: str, role: str) -> dict[str, Any]:
    meta: Mapping[str, Any] = data["meta"] if isinstance(data.get("meta"), dict) else {}
    row: dict[str, Any] = {"file": path.name, "sha256": sha256_file(path), "kind": kind, "role": role}
    if kind == "run":
        row.update(split=meta["split"], repeat=int(meta.get("repeat", 1)))
        day = meta.get("recording_day")
        if role in ("final", "held-out") and day and day not in (meta.get("simulated_today") or [day]):
            raise ReproduceError(
                f"{path.name}: a {role} recording made on {day} for letters of {', '.join(meta['simulated_today'])} "
                "— two todays: its letters are built for the day they are recorded (the plan's addendum, item 8)"
            )
    elif kind == "ask":
        match = _ASK_NAME.match(path.name)
        row.update(
            set="heldout" if match and match["heldout"] else "dev",
            repeat=int(match["repeat"]) if match and match["repeat"] else 1,
            schema=int(data.get("schema", 1)),
        )
        if _ask_rescoring(data):  # a re-scoring of a live run's recordings (schema 2, named -rescored)
            row["rescores"] = data["recorded"]
    elif kind == "e2e":
        row["splits"] = sorted(meta.get("splits") or [])
    elif kind in ("checks-ablated", "without-land"):
        row["splits"] = sorted(data.get("splits") or {})
    elif kind == "analysis":
        row["analysis"] = meta.get("kind")
    if kind == "ask":
        recorded = {
            "date": data.get("date"),
            "commit": None,
            "backend": "replay" if _ask_rescoring(data) else "live",
        }
    else:
        recorded = {
            "date": meta.get("date"),
            "commit": meta.get("commit"),
            "backend": meta.get("backend") or ("analysis" if kind == "analysis" else None),
        }
    row["recorded"] = recorded
    return row


def _ask_rescoring(data: Mapping[str, Any]) -> bool:
    """Whether an Ask results file re-scores a live run (schema 2 says so; every live run writes schema 2 too, with
    its own date as "recorded"): the same reading as :func:`evals.ask.report.is_rescoring`."""
    return int(data.get("schema", 1)) >= 2 and data.get("backend") == "replay"


def _made(row: Mapping[str, Any]) -> tuple[str, ...]:
    """The order a group's files were made in: by name, and an Ask set's by date with a day's re-scoring after its
    live run (``…-ask-rescored.json`` sorts before ``…-ask.json`` by name)."""
    if row["kind"] == "ask":
        return (str(row["recorded"]["date"]), str("rescores" in row), row["file"])
    return (row["file"],)


def _group(row: Mapping[str, Any], data: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """Rows of one group are versions of one summary: the newest is checked, the others superseded (``None``: every
    row stands alone)."""
    kind = row["kind"]
    if row["role"] == "archive" or kind == "run":
        return None
    if kind == "ask":
        return ("ask", row["set"], row["repeat"])
    if kind == "e2e":
        meta = data.get("meta") or {}
        return ("e2e", tuple(row["splits"]), bool(meta.get("partial")))
    if kind in ("checks-ablated", "without-land", "stress"):
        return (kind, tuple(row.get("splits", ())))
    return ("analysis", row.get("analysis"))


CHECKS = {
    "ask": "ask --check-docs",
    "without-land": "without-land replay",
    "e2e": "e2e --compare",
    "checks-ablated": "ablation --check",
    "analysis": "analysis --check",
    "stress": "stress --check",
}


def _checks(
    rows: list[dict[str, Any]], data: Mapping[str, Mapping[str, Any]], gates: Mapping[str, Any]
) -> None:
    """Set each row's ``check`` (and ``gates``): replay, hash, or the command that checks the newest of its kind."""
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        row["gates"] = []
        if row["role"] == "archive":
            row["check"] = "hash"
            continue
        if row["kind"] == "run":
            row["check"] = "replay"
            continue
        key = _group(row, data[row["file"]])
        assert key is not None
        groups.setdefault(key, []).append(row)
    for members in groups.values():
        members.sort(key=_made)
        newest = members[-1]
        checked = [newest]
        if newest["kind"] == "ask" and newest["schema"] >= 2:
            # Ask's --check-docs also checks the newest run as recorded (schema 1) before a re-scoring
            older = [row for row in members[:-1] if row["schema"] == 1]
            checked += older[-1:]
        for row in members:
            row["check"] = CHECKS[row["kind"]] if row in checked else "hash"
    published = (gates.get("without-land") or {}).get("published")
    for row in rows:
        if row["kind"] == "ask" and row["check"] != "hash" and row["set"] == "dev" and "ask/dev" in gates:
            row["gates"] = ["ask/dev"]
        if row["file"] == published:
            row["gates"] = ["without-land"]


def _cells(
    rows: Sequence[Mapping[str, Any]], data: Mapping[str, Mapping[str, Any]], gates: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Every cell: replayed (with the files it checks) or not recorded yet (with what it waits for)."""
    cells: list[dict[str, Any]] = []
    runs: dict[tuple[str, int], list[str]] = {}
    for row in rows:
        if row["kind"] == "run" and row["check"] == "replay":
            runs.setdefault((row["split"], row["repeat"]), []).append(row["file"])
    for split in splits.names():
        reads = set(range(1, FINAL_READS.get(split, 1) + 1)) | {
            repeat for name, repeat in runs if name == split
        }
        for repeat in sorted(reads):
            files = runs.get((split, repeat), [])
            cell: dict[str, Any] = {"cell": f"benchmark/{split}/r{repeat}", "conditions": list(CONDITIONS)}
            if split in FINAL_READS and not files:
                cell.update(
                    status="not recorded yet",
                    needs="its letters, written blind after the code freeze (plan EV8), and their recording "
                    "(plan §7)",
                )
            elif not splits.get(split).recorded and not files:  # pragma: no cover - a declared split
                cell.update(status="not recorded yet", needs="its letters and their recording")
            else:
                cell.update(status="replayed", checks=sorted(files))
                if repeat == 1 and f"benchmark/{split}" in gates:
                    cell["gate"] = f"benchmark/{split}"
            cells.append(cell)
    checked = [row for row in rows if row["check"] not in ("hash", "replay")]

    def add(name: str, kind: str, members: list[Mapping[str, Any]], status: str, needs: str) -> None:
        if members:
            cell = {"cell": name, "status": status, "checks": sorted(row["file"] for row in members)}
            if kind in gates:
                cell["gate"] = kind
            cells.append(cell)
        else:
            cells.append({"cell": name, "status": "not recorded yet", "needs": needs})

    without_land = [row for row in checked if row["kind"] == "without-land"]
    if without_land:
        add("without-land", "without-land", without_land, "replayed", "")
    asks: dict[tuple[str, int], list[Mapping[str, Any]]] = {}
    for row in checked:
        if row["kind"] == "ask":
            asks.setdefault((row["set"], row["repeat"]), []).append(row)
    for (set_name, repeat), members in sorted(asks.items()):
        if set_name == "dev":
            add(f"ask/dev/r{repeat}", "ask/dev" if repeat == 1 else "", members, "replayed", "")
    for repeat in sorted(set(range(1, ASK_HELDOUT_READS + 1)) | {r for s, r in asks if s == "heldout"}):
        add(
            f"ask/heldout/r{repeat}",
            "",
            asks.get(("heldout", repeat), []),
            "replayed",
            "the held-out questions and attacks, written blind after the code freeze (plan EV10), and their "
            "recording (plan §7, R3 and R6)",
        )
    for kind, prefix, planned, needs in (
        ("e2e", "e2e", FINAL_E2E, "holdout4's and newkinds' recorded readings (plan EV9)"),
        ("checks-ablated", "ablation", FINAL_ABLATION, "holdout4's recorded readings (plan EV9)"),
    ):
        members = [row for row in checked if row["kind"] == kind]
        names = {"-".join(row["splits"]): row for row in members}
        for joined, row in sorted(names.items()):
            add(f"{prefix}/{joined}", "", [row], "replayed", "")
        joined = "-".join(sorted(planned))
        if joined not in names:
            add(f"{prefix}/{joined}", "", [], "", needs)
    stress = [row for row in checked if row["kind"] == "stress"]
    for name in STRESS_CELLS:
        covering = [row for row in stress if name in (data[row["file"]].get("meta") or {}).get("cells", [])]
        add(
            f"stress/{name}",
            "",
            covering,
            "replayed",
            "the blind templates and the stress manifest (plan EV8, commit A) and the cells' recording (plan §7, R7)",
        )
    analyses = {row.get("analysis"): row for row in checked if row["kind"] == "analysis"}
    add(
        "analysis/heldout-reanalysis",
        "",
        [analyses["heldout-reanalysis"]] if "heldout-reanalysis" in analyses else [],
        "re-rendered",
        "the held-out splits' results files",
    )
    add(
        "analysis/final",
        "",
        [analyses["final"]] if "final" in analyses else [],
        "re-rendered",
        "the final run (plan EV9) and the pre-registration (plan EV8, commit B)",
    )
    cells.append({"cell": "presenter", "status": "re-rendered"})
    return cells


def static_index(results_dir: Path = RESULTS_DIR, *, ci: Path = CI_PATH) -> dict[str, Any]:
    """Everything the index says that needs no replay: hashes, roles, checks, gates and cells."""
    gates = ci_gates(ci)
    rows: list[dict[str, Any]] = []
    data: dict[str, dict[str, Any]] = {}
    for path in sorted(results_dir.glob("*.json")):
        if path.name == INDEX_NAME:
            continue
        loaded = _load(path)
        kind, role = _kind(path.name, loaded)
        data[path.name] = loaded
        rows.append(_row(path, loaded, kind, role))
    _checks(rows, data, gates)
    return {
        "schema": INDEX_SCHEMA,
        "about": ABOUT,
        "pinned_model": DEFAULT_MODEL,
        "dataset": dataset_info(),
        "recordings": recordings_info(),
        "gates": gates,
        "cells": _cells(rows, data, gates),
        "results": rows,
    }


#: A row's fields that a replay decides (everything else is static).
DYNAMIC = ("verdict", "conditions")


def is_as_recorded(row: Mapping[str, Any]) -> bool:
    """Whether a row is a live Ask run as recorded (of either schema; a re-scoring is the replay's): a recording is
    never rewritten, so its sha256 is pinned (:func:`pin_recordings`)."""
    return row.get("kind") == "ask" and (row.get("recorded") or {}).get("backend") == "live"


def _pinned(committed: Mapping[str, Any], fresh: Mapping[str, Any]) -> bool:
    """Whether a row's sha256 is pinned: a run as recorded by its bytes or by the committed index (a recording
    rewritten to say it is a re-scoring is still the recording), or one whose move is already declared there."""
    return is_as_recorded(fresh) or is_as_recorded(committed) or committed.get("sha256_moved") is not None


def _rewritten(row: Mapping[str, Any]) -> str | None:
    """The problem with a declared move of a run as recorded that has no reason yet."""
    moved = row.get("sha256_moved")
    if moved is None or str(moved.get("because", "")).strip():
        return None
    return (
        f"{row['file']}: a run as recorded is never rewritten, but its sha256 moved since {INDEX_NAME} pinned it "
        f"(was {moved.get('from')}), undeclared: restore its bytes, or say in its sha256_moved.because which commit "
        "or ADR changed it"
    )


def pin_recordings(fresh: dict[str, Any], committed: Mapping[str, Any] | None) -> list[str]:
    """``--write``: a run as recorded whose sha256 moved since the committed index pinned it gets the move with an
    empty reason (``sha256_moved``), which a person gives; a declared move stays while the bytes do. The problems
    of the moves that have no reason."""
    old_rows = {row["file"]: row for row in (committed or {}).get("results", [])}
    problems = []
    for row in fresh["results"]:
        old = old_rows.get(row["file"])
        if old is None or not _pinned(old, row):
            continue
        if old.get("sha256") != row["sha256"]:
            row["sha256_moved"] = {"from": old.get("sha256"), "because": ""}
        elif old.get("sha256_moved") is not None:
            row["sha256_moved"] = dict(old["sha256_moved"])
        problem = _rewritten(row)
        if problem:
            problems.append(problem)
    return problems


def static_problems(committed: Mapping[str, Any], fresh: Mapping[str, Any]) -> list[str]:
    """Where the committed index's static part differs from the checkout's (empty when it doesn't); and a run as
    recorded whose bytes moved, or whose declared move has no reason."""
    problems = [
        f"{INDEX_NAME}: {key} is not what the checkout gives: run python -m evals.reproduce --write"
        for key in ("schema", "pinned_model", "dataset", "recordings", "gates", "cells")
        if committed.get(key) != fresh.get(key)
    ]
    rows = {row["file"]: row for row in committed.get("results", [])}
    fresh_rows = {row["file"]: row for row in fresh["results"]}
    problems += [f"{name}: no row in {INDEX_NAME}" for name in sorted(fresh_rows.keys() - rows.keys())]
    problems += [
        f"{name}: a row in {INDEX_NAME}, but no such results file"
        for name in sorted(rows.keys() - fresh_rows.keys())
    ]
    for name in sorted(rows.keys() & fresh_rows.keys()):
        for key, value in fresh_rows[name].items():
            if key not in DYNAMIC and rows[name].get(key) != value:
                if key == "sha256" and _pinned(rows[name], fresh_rows[name]):
                    problems.append(
                        f"{name}: a run as recorded is never rewritten, but its sha256 is not the one {INDEX_NAME} "
                        "pinned: restore its bytes, or run --write and say in its sha256_moved.because which commit "
                        "or ADR changed it"
                    )
                    continue
                problems.append(f"{name}: {key} is not what the file gives (in {INDEX_NAME}: run --write)")
        rewritten = _rewritten(rows[name])
        if rewritten:
            problems.append(rewritten)
    if [row["file"] for row in committed.get("results", [])] != sorted(rows):
        problems.append(f"{INDEX_NAME}: its rows are not in file order")
    return problems


def load_index(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReproduceError(f"{path}: not a readable index ({exc})") from exc
    if not isinstance(data, dict) or data.get("schema") != INDEX_SCHEMA:
        raise ReproduceError(f"{path}: not an index of schema {INDEX_SCHEMA}")
    return data


def dumps_index(index: Mapping[str, Any]) -> str:
    return json.dumps(index, ensure_ascii=False, indent=1) + "\n"


# --------------------------------------------------------------------------------------------------
# A published run against its replay
# --------------------------------------------------------------------------------------------------


class _Drift:
    def __init__(self) -> None:
        self.found: dict[str, set[str]] = {"added": set(), "removed": set(), "values": set()}

    def add(self, kind: str, path: str) -> None:
        self.found[kind].add(".".join(path.split(".")[:DRIFT_DEPTH]))

    def as_dict(self) -> dict[str, list[str]]:
        return {kind: sorted(paths) for kind, paths in self.found.items()}

    def __bool__(self) -> bool:
        return any(self.found.values())


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _diff(old: Any, new: Any, path: str, drift: _Drift) -> None:
    if path in VOLATILE:
        return
    if isinstance(old, dict) and isinstance(new, dict):
        for key in old.keys() | new.keys():
            sub = f"{path}.{key}"
            if sub in VOLATILE:
                continue
            if key not in new:
                drift.add("removed", sub)
            elif key not in old:
                drift.add("added", sub)
            else:
                _diff(old[key], new[key], sub, drift)
    elif isinstance(old, list) and isinstance(new, list):
        if len(old) != len(new):
            drift.add("values", path + "[]")
        for first, second in zip(old, new, strict=False):
            _diff(first, second, path + "[]", drift)
    elif _number(old) and _number(new):
        if not math.isclose(float(old), float(new), rel_tol=1e-9, abs_tol=1e-12):
            drift.add("values", path)
    elif old != new:
        drift.add("values", path)


def _state(item: Mapping[str, Any] | None) -> dict[str, Any]:
    if item is None:
        return {"outcome": None, "predicted": None}
    return {"outcome": item.get("outcome"), "predicted": item.get("predicted")}


def _item_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (item.get("outcome"), item.get("predicted"), item.get("direction"), item.get("days_off"))


def _scored(item: Mapping[str, Any] | None) -> bool:
    return item is not None and item.get("outcome") != "unscored"


def _direction(recorded: Mapping[str, Any], at_head: Mapping[str, Any]) -> str:
    if at_head["outcome"] == "correct" and recorded["outcome"] != "correct":
        return "better"
    if recorded["outcome"] == "correct" and at_head["outcome"] != "correct":
        return "worse"
    return "other"


def _item_changes(
    entry_id: str, old: Mapping[str, Any] | None, new: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """The scored items of one letter whose date or outcome differs (an unscored item's date moves no number)."""
    before = {int(item["index"]): item for item in (old or {}).get("items", [])}
    after = {int(item["index"]): item for item in (new or {}).get("items", [])}
    changes = []
    for index in sorted(before.keys() | after.keys()):
        first, second = before.get(index), after.get(index)
        if not (_scored(first) or _scored(second)):
            continue
        if first is not None and second is not None and _item_key(first) == _item_key(second):
            continue
        recorded, at_head = _state(first), _state(second)
        changes.append(
            {
                "entry_id": entry_id,
                "item": index,
                "recorded": recorded,
                "at_head": at_head,
                "direction": _direction(recorded, at_head),
                "because": "",
            }
        )
    return changes


def _right(metrics: Mapping[str, Any] | None) -> list[int] | None:
    return _count(metrics, "due_date_accuracy")


def _count(metrics: Mapping[str, Any] | None, key: str) -> list[int] | None:
    rate = (metrics or {}).get(key)
    if not isinstance(rate, Mapping) or rate.get("k") is None or rate.get("n") is None:
        return None
    return [int(rate["k"]), int(rate["n"])]


#: The counts the pages and the CI gates read, and the scored items each one counts: such a count may move only with
#: its dates (a moved date is a change of its own); anything else that moves it is a change that needs a reason.
AGGREGATES: tuple[tuple[str, Callable[[Mapping[str, Any]], bool], bool], ...] = (
    ("due_date_accuracy", lambda item: item.get("outcome") == "correct", True),
    ("dangerous_late_rate", lambda item: item.get("direction") == "late", False),
    ("missed_rate", lambda item: item.get("outcome") == "missed", False),
)
#: Floats in the metrics digest are read to this many significant digits (a sum in another order is the same value).
DIGEST_DIGITS = 10


def _canonical(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return repr(value)
        rounded = float(f"{value:.{DIGEST_DIGITS}g}")
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return repr(value)


def metrics_digest(metrics: Mapping[str, Any] | None) -> str | None:
    """A digest of one condition's metrics as the replay gives them (floats to :data:`DIGEST_DIGITS` significant
    digits): INDEX.json pins it, so a number may not move under a field that already drifts by name alone."""
    if metrics is None:
        return None
    text = json.dumps(_canonical(metrics), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _item_counts(entries: Iterable[Mapping[str, Any]], condition: str) -> dict[str, list[int]]:
    """Per aggregate: (items it counts, scored items) over the entries' scores of ``condition``."""
    counts = {key: [0, 0] for key, _, _ in AGGREGATES}
    for entry in entries:
        score = ((entry.get("conditions") or {}).get(condition) or {}).get("score") or {}
        for item in score.get("items") or []:
            if not _scored(item):
                continue
            for key, counted, _ in AGGREGATES:
                counts[key][0] += int(counted(item))
                counts[key][1] += 1
    return counts


def _aggregate_changes(
    metrics: Mapping[str, Any] | None,
    head_metrics: Mapping[str, Any] | None,
    recorded_items: Mapping[str, list[int]],
    head_items: Mapping[str, list[int]],
) -> list[dict[str, Any]]:
    """The published counts that moved by more than their dates moved: each a change with an empty ``because``."""
    changes = []
    for key, _, higher_is_better in AGGREGATES:
        recorded, at_head = _count(metrics, key), _count(head_metrics, key)
        if recorded is None or at_head is None:
            continue
        # what the dates explain: each count moves with its own items, so its offset from them stays the same
        offset = [recorded[0] - recorded_items[key][0], recorded[1] - recorded_items[key][1]]
        offset_at_head = [at_head[0] - head_items[key][0], at_head[1] - head_items[key][1]]
        if offset == offset_at_head:
            continue
        if recorded[1] != at_head[1] or recorded[0] == at_head[0]:
            direction = "other"
        else:
            direction = "better" if (at_head[0] > recorded[0]) == higher_is_better else "worse"
        changes.append(
            {
                "entry_id": f"metrics.{key}",
                "item": None,
                "recorded": {"outcome": key, "predicted": f"{recorded[0]}/{recorded[1]}"},
                "at_head": {"outcome": key, "predicted": f"{at_head[0]}/{at_head[1]}"},
                "direction": direction,
                "because": "",
            }
        )
    return changes


def compare_run(published: Mapping[str, Any], replayed: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Per condition of ``published``: the verdict, its dates right as recorded and at HEAD, the drift and every
    changed date (with an empty ``because``)."""
    at_head = {entry["id"]: entry for entry in replayed.get("entries", [])}
    compared: dict[str, dict[str, Any]] = {}
    for condition in published["meta"]["conditions"]:
        drift = _Drift()
        changes: list[dict[str, Any]] = []
        for entry in published["entries"]:
            mine = entry["conditions"].get(condition) or {}
            head_entry = at_head.get(entry["id"])
            if head_entry is None:
                drift.add("removed", "entries[]")
            theirs = ((head_entry or {}).get("conditions") or {}).get(condition) or {}
            _diff(mine.get("prediction"), theirs.get("prediction"), "prediction", drift)
            _diff(mine.get("score"), theirs.get("score"), "score", drift)
            changes += _item_changes(entry["id"], mine.get("score"), theirs.get("score"))
        if set(at_head) - {entry["id"] for entry in published["entries"]}:
            drift.add("added", "entries[]")
        metrics = published.get("metrics", {}).get(condition)
        head_metrics = replayed.get("metrics", {}).get(condition)
        _diff(metrics, head_metrics, "metrics", drift)
        changes += _aggregate_changes(
            metrics,
            head_metrics,
            _item_counts(published["entries"], condition),
            _item_counts(at_head.values(), condition),
        )
        compared[condition] = {
            "verdict": "changed" if changes else ("same-dates" if drift else "exact"),
            "right": _right(metrics),
            "right_at_head": _right(head_metrics),
            "drift": drift.as_dict(),
            "changes": changes,
            "metrics_at_head": metrics_digest(head_metrics),
        }
    return compared


def _worst(conditions: Mapping[str, Mapping[str, Any]]) -> str:
    return max((verdict["verdict"] for verdict in conditions.values()), key=VERDICTS.index, default="exact")


def _change_key(change: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        change["entry_id"],
        change["item"],
        json.dumps(change["recorded"], sort_keys=True),
        json.dumps(change["at_head"], sort_keys=True),
    )


def _said(state: Mapping[str, Any]) -> str:
    return f"{state['outcome']} {state['predicted'] or 'no date'}"


def _place(change: Mapping[str, Any]) -> str:
    """A changed date's letter and item, or a count's name."""
    return change["entry_id"] if change.get("item") is None else f"{change['entry_id']} item {change['item']}"


def _moved(where: str, verdict: Mapping[str, Any]) -> str | None:
    """The problem with a declared move of the replay's metrics that has no reason yet."""
    moved = verdict.get("metrics_moved")
    if moved is None or str(moved.get("because", "")).strip():
        return None
    return (
        f"{where}: the replay's metrics moved since {INDEX_NAME} pinned them (was {moved.get('from')}), undeclared: say "
        "in its metrics_moved.because which commit or ADR changed them"
    )


def run_problems(row: Mapping[str, Any], fresh: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """What the replay gives that the row doesn't declare, or declares and no longer gives."""
    name = row.get("file", "")
    committed: Mapping[str, Mapping[str, Any]] = row.get("conditions") or {}
    problems = []
    for condition in sorted(committed.keys() | fresh.keys()):
        old, new = committed.get(condition), fresh.get(condition)
        where = f"{name} {condition}"
        if old is None or new is None:
            problems.append(f"{where}: in {INDEX_NAME} but not in the file, or the other way round")
            continue
        for field in ("verdict", "right", "right_at_head", "drift"):
            if old.get(field) != new.get(field):
                problems.append(
                    f"{where}: {field} is {old.get(field)} in {INDEX_NAME} but {new.get(field)} at HEAD"
                )
        if old.get("metrics_at_head") != new.get("metrics_at_head"):
            problems.append(
                f"{where}: the replay's metrics moved since {INDEX_NAME} pinned them ({old.get('metrics_at_head')} → "
                f"{new.get('metrics_at_head')}): run --write and say in its metrics_moved.because which commit or "
                "ADR changed them"
            )
        unexplained = _moved(where, old)
        if unexplained:
            problems.append(unexplained)
        declared = {_change_key(change): change for change in old.get("changes", [])}
        given = {_change_key(change): change for change in new["changes"]}
        for key, change in given.items():
            label = f"{where} {_place(change)}"
            moved = f"{_said(change['recorded'])} → {_said(change['at_head'])}"
            if key not in declared:
                problems.append(
                    f"{label}: changed since its recording ({moved}), undeclared: run --write and say in "
                    f"{INDEX_NAME} which commit, ADR or re-scored results file changed it"
                )
            elif not str(declared[key].get("because", "")).strip():
                problems.append(
                    f"{label}: changed since its recording ({moved}), undeclared: give its because"
                )
        for key, change in declared.items():
            if key not in given:
                problems.append(
                    f"{where} {_place(change)}: declared in {INDEX_NAME}, but the replay no longer gives it"
                )
    return problems


def merge_conditions(
    row: Mapping[str, Any] | None, fresh: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """``fresh`` with the reasons the row gave for the changes the replay still gives; and, when the replay's metrics
    moved since the row pinned them, that move with an empty reason (a person gives it), else the row's move."""
    reasons: dict[tuple[str, tuple[Any, ...]], str] = {}
    committed: Mapping[str, Mapping[str, Any]] = (row or {}).get("conditions") or {}
    for condition, verdict in committed.items():
        for change in verdict.get("changes", []):
            reasons[(condition, _change_key(change))] = str(change.get("because", ""))
    merged = json.loads(json.dumps(fresh))
    for condition, verdict in merged.items():
        for change in verdict["changes"]:
            change["because"] = reasons.get((condition, _change_key(change)), "")
        old = committed.get(condition) or {}
        pinned = old.get("metrics_at_head")
        if pinned is not None and pinned != verdict.get("metrics_at_head"):
            verdict["metrics_moved"] = {"from": pinned, "because": ""}
        elif old.get("metrics_moved") is not None:
            verdict["metrics_moved"] = dict(old["metrics_moved"])
    return dict(merged)


def undeclared(row: Mapping[str, Any]) -> list[str]:
    problems = [
        f"{row['file']} {condition} {_place(change)}: changed since its recording "
        f"({_said(change['recorded'])} → {_said(change['at_head'])}), undeclared: say in {INDEX_NAME} which commit, "
        "ADR or re-scored results file changed it"
        for condition, verdict in (row.get("conditions") or {}).items()
        for change in verdict["changes"]
        if not str(change.get("because", "")).strip()
    ]
    for condition, verdict in (row.get("conditions") or {}).items():
        moved = _moved(f"{row['file']} {condition}", verdict)
        if moved:
            problems.append(moved)
    return problems


# --------------------------------------------------------------------------------------------------
# The tasks
# --------------------------------------------------------------------------------------------------


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name)


def _python(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def task_of(row: Mapping[str, Any]) -> str | None:
    """The task that checks a row (``None``: its hash only)."""
    check = row.get("check")
    if check == "replay":
        return f"benchmark/{row['split']}/r{row['repeat']}"
    if check == "ask --check-docs":
        return f"ask/{row['set']}/r{row['repeat']}"
    if check == "without-land replay":
        return "without-land"
    if check == "e2e --compare":
        return "e2e/" + "-".join(row["splits"])
    if check == "ablation --check":
        return "ablation/" + "-".join(row["splits"])
    if check == "analysis --check":
        return f"analysis/{row['analysis']}"
    if check == "stress --check":
        return "stress"
    return None


def plan(index: Mapping[str, Any], results_dir: Path, work: Path) -> list[Task]:
    """The zero-token commands that check every replayed cell and every checked row, longest first."""
    today = date.today().isoformat()
    default = results_dir.resolve() == RESULTS_DIR.resolve()
    tasks: list[Task] = []
    for cell in index["cells"]:
        name, status = cell["cell"], cell["status"]
        if status != "replayed" or not name.startswith("benchmark/"):
            continue
        _, split, read = name.split("/")
        out = work / _safe(name)
        argv = _python(
            "evals.run",
            "--split",
            split,
            "--repeat",
            read.removeprefix("r"),
            "--results-dir",
            str(out),
            "--date",
            today,
            "--quiet",
            "--no-docs",
        )
        tasks.append(Task(name, argv, out))
    for row in index["results"]:
        name = task_of(row)
        if name is None or name.startswith("benchmark/") or any(task.name == name for task in tasks):
            continue
        path = results_dir / row["file"]
        data = _load(path)
        if row["kind"] == "without-land":
            out = work / "without-land"
            argv = _python(
                "scripts.eval_without_land",
                "--date",
                str(row["recorded"]["date"]),
                "--splits",
                *list(data["splits"]),
                "--out",
                str(out),
            )
            tasks.append(Task(name, argv, out))
        elif row["kind"] == "ask":
            if row["set"] == "dev" and row["repeat"] == 1 and "ask/dev" in index["gates"]:
                args = list(index["gates"]["ask/dev"]["args"])
            else:
                args = ["--set", row["set"], "--repeat", str(row["repeat"])]
            if row["set"] == "heldout" and data.get("today"):
                # built, asked and scored for the day it was recorded (the plan's addendum, item 8)
                args += ["--today", str(data["today"])]
            if "--check-docs" not in args:
                args.append("--check-docs")
            if not default:
                args += ["--results-dir", str(results_dir)]
            tasks.append(Task(name, _python("evals.ask", *args)))
        elif row["kind"] == "e2e":
            known = sorted({str(aside["entry_id"]) for aside in data.get("set_aside", [])})
            argv = _python(
                "evals.e2e",
                "--splits",
                *list((data.get("meta") or {}).get("splits") or []),
                "--no-write",
                "--compare",
                str(path),
                "--exact-parity",
                "--max-late-reminders",
                "0",
                "--known-set-aside",
                *known,
            )
            tasks.append(Task(name, argv))
        elif row["kind"] == "checks-ablated":
            tasks.append(Task(name, _python("scripts.eval_ablate_checks", "--check", str(path))))
        elif row["kind"] == "stress":
            out = work / "stress"
            argv = _python(
                "scripts.eval_perturb",
                "--quiet",
                "--out",
                str(out),
                "--build-dir",
                str(work / "stress-build"),
                "--check",
                str(path),
            )
            built_for = (data.get("meta") or {}).get("today")
            if built_for:  # its cells were built for the day they were recorded (the plan's addendum, item 8)
                argv += ["--today", str(built_for)]
            tasks.append(Task(name, argv, out))
        elif row["kind"] == "analysis":
            if row.get("analysis") == "final":
                meta = data.get("meta") or {}
                inputs = [str(results_dir / str(item["file"])) for item in meta.get("inputs", [])]
                argv = _python(
                    "evals.analysis",
                    "--prereg",
                    str((meta.get("prereg") or {}).get("file")),
                    *inputs,
                    "--check",
                )
            else:
                argv = _python("evals.analysis", "--check")
            if not default:
                argv += ["--results-dir", str(results_dir), "--out-dir", str(results_dir)]
            tasks.append(Task(name, argv))
    present = _python("evals.present", "--check")
    if not default:
        present += ["--results-dir", str(results_dir)]
    tasks.append(Task("presenter", present))
    logs = work / "logs"
    tasks = [Task(task.name, task.argv, task.out, logs / f"{_safe(task.name)}.log") for task in tasks]
    return sorted(tasks, key=lambda task: (-WEIGHTS.get(task.name.split("/", 1)[0], 10), task.name))


def child_env(work: Path) -> dict[str, str]:
    """The children's environment: no model to reach (unless a fake one is named), no OCR, no demo recording."""
    env = dict(os.environ)
    env.setdefault("ORDNUNG_CLAUDE_BIN", str(work / "no-claude"))
    env.setdefault("ORDNUNG_OCR", "off")
    env.pop("ORDNUNG_RECORD", None)
    return env


def run_tasks(tasks: Sequence[Task], *, jobs: int, env: Mapping[str, str], say: Say) -> dict[str, Done]:
    """Run every task, ``jobs`` at a time, each with its output in a log beside its folder."""

    def one(task: Task) -> Done:
        log = task.log or Path(tempfile.mkstemp(prefix=f"{_safe(task.name)}-", suffix=".log")[1])
        log.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with log.open("w", encoding="utf-8") as handle:
            rc = subprocess.run(
                task.argv, cwd=ROOT, env=dict(env), stdout=handle, stderr=subprocess.STDOUT, check=False
            ).returncode
        seconds = time.monotonic() - started
        say(f"  {task.name}: {'ok' if rc == 0 else f'exit {rc}'} ({seconds:.0f} s)")
        return Done(task.name, rc, seconds, log)

    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        return {done.name: done for done in pool.map(one, tasks)}


def _tail(log: Path, lines: int = 12) -> str:
    try:
        text = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(f"    {line}" for line in text[-lines:])


def replays_of(tasks: Sequence[Task], done: Mapping[str, Done]) -> dict[str, dict[str, Any]]:
    """The results file each replay that ran wrote (by task name)."""
    found = {}
    for task in tasks:
        if task.out is None or task.name not in done or done[task.name].rc != 0:
            continue
        written = sorted(task.out.glob("*.json"))
        if len(written) == 1:
            found[task.name] = _load(written[0])
    return found


def without_land_problems(published: Mapping[str, Any], replayed: Mapping[str, Any] | None) -> list[str]:
    """Like CI's step: the replay gives the published numbers, split by split."""
    if replayed is None:
        return ["without-land: the replay wrote no results file"]
    old, new = published.get("splits", {}), replayed.get("splits", {})
    return [
        f"without-land {split}: the replay doesn't give the published numbers"
        for split in sorted(old.keys() | new.keys())
        if old.get(split) != new.get(split)
    ]


def gate_problems(
    index: Mapping[str, Any], replays: Mapping[str, Mapping[str, Any]], done: Mapping[str, Done]
) -> tuple[list[str], list[str]]:
    """``(problems, scoreboard parts)``: the CI gates held to the replays (as ``evals.run``'s ``gate_failures``)."""
    problems: list[str] = []
    parts: list[str] = []
    late_ok = True
    for name, gate in index["gates"].items():
        if name.startswith("benchmark/"):
            split = name.split("/", 1)[1]
            if f"benchmark/{split}/r1" not in done:  # a partial run (--only)
                continue
            replay = replays.get(f"benchmark/{split}/r1")
            if replay is None:
                problems.append(f"gate {name}: no replay to hold it to")
                parts.append(f"{split} ✗")
                continue
            metrics = replay["metrics"]["ordnung"]
            accuracy, late = metrics["due_date_accuracy"], metrics["dangerous_late_rate"]
            ok = accuracy.get("value") is not None and accuracy["value"] >= gate["min_accuracy"]
            late_ok &= late.get("value") is not None and late["value"] <= gate["max_dangerous_late"]
            if not ok:
                problems.append(
                    f"gate {name}: Ordnung {int(accuracy['k'])}/{int(accuracy['n'])} < {gate['min_accuracy']}"
                )
            if late.get("value") is None or late["value"] > gate["max_dangerous_late"]:
                problems.append(
                    f"gate {name}: Ordnung dangerously late {late.get('value')} > {gate['max_dangerous_late']}"
                )
            parts.append(
                f"{split} {int(accuracy['k'])}/{int(accuracy['n'])} ≥ {gate['min_accuracy']} {'✓' if ok else '✗'}"
            )
    if parts:
        parts.append(f"late 0 everywhere {'✓' if late_ok else '✗'}")
    if "ask/dev" in index["gates"] and "ask/dev/r1" in done:
        parts.append(f"Ask {'✓' if done['ask/dev/r1'].rc == 0 else '✗'}")
    return problems, parts


# --------------------------------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------------------------------


def _verify(
    fresh: dict[str, Any],
    committed: Mapping[str, Any] | None,
    results_dir: Path,
    replays: Mapping[str, Mapping[str, Any]],
    done: Mapping[str, Done],
    *,
    write: bool,
) -> list[str]:
    """Give each fresh row its verdict (and a run's per-condition comparison); the problems found on the way."""
    problems: list[str] = []
    old_rows = {row["file"]: row for row in (committed or {}).get("results", [])}
    for row in fresh["results"]:
        old = old_rows.get(row["file"])
        if row["check"] == "hash":
            row["verdict"] = "archived" if row["role"] == "archive" else "superseded"
            if not write and old is not None and old.get("verdict") != row["verdict"]:
                problems.append(
                    f"{row['file']}: its verdict is {old.get('verdict')} in {INDEX_NAME}, {row['verdict']} now"
                )
            continue
        task = task_of(row)
        if task not in done:  # a partial run (--only): keep what the index says
            for key in DYNAMIC:
                if old is not None and key in old:
                    row[key] = old[key]
            continue
        if row["check"] == "replay":
            replay = replays.get(str(task))
            if replay is None:
                problems.append(f"{row['file']}: no replay of {task} to compare with")
                for key in DYNAMIC:
                    if old is not None and key in old:
                        row[key] = old[key]
                continue
            compared = compare_run(_load(results_dir / row["file"]), replay)
            if not write and old is not None:
                problems += run_problems(old, compared)
            row["verdict"] = _worst(compared)
            row["conditions"] = merge_conditions(old, compared)
            if write or old is None:
                problems += undeclared(row)
            continue
        ok = done[str(task)].rc == 0
        if ok and row["kind"] == "without-land":
            failed = without_land_problems(_load(results_dir / row["file"]), replays.get(str(task)))
            problems += failed
            ok = not failed
        row["verdict"] = "checked" if ok else "failed"
        if not write and old is not None and old.get("verdict") != row["verdict"] and ok:
            problems.append(
                f"{row['file']}: its verdict is {old.get('verdict')} in {INDEX_NAME}, {row['verdict']} now"
            )
    return problems


def scoreboard(
    index: Mapping[str, Any], gates: Sequence[str], *, seconds: float, jobs: int, items: str
) -> list[str]:
    counts = Counter(row.get("verdict") for row in index["results"])
    rows = index["results"]
    waiting = [cell["cell"] for cell in index["cells"] if cell["status"] == "not recorded yet"]
    replayed = [cell["cell"] for cell in index["cells"] if cell["status"] != "not recorded yet"]
    lines = [
        f"reproduced with no model call in {seconds:.0f} s ({jobs} at a time)",
        f"results files {len(rows)}: exact {counts['exact']} · same dates {counts['same-dates']} · changed by a "
        f"declared fix {counts['changed']} · checked {counts['checked']} · superseded {counts['superseded']} · "
        f"archived {counts['archived']}" + (f" · failed {counts['failed']}" if counts["failed"] else ""),
        f"cells: replayed or re-rendered {len(replayed)} · not recorded yet {len(waiting)}"
        + (f" ({', '.join(waiting)})" if waiting else ""),
    ]
    recordings = index.get("recordings", {})
    if recordings:
        lines.append(
            "recordings: "
            + " · ".join(
                f"{name} {info['cassettes']} ({info['locked']} asked for at HEAD, {info['history_only']} history only)"
                for name, info in recordings.items()
            )
            + f" · served by {index['pinned_model']}: "
            + (
                "all"
                if all(info["served_by_another_model"] == 0 for info in recordings.values())
                else "NOT all"
            )
        )
    if gates:
        lines.append("gates: " + " · ".join(gates))
    lines.append(f"items.csv: {items}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.reproduce", description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check", action="store_true", help="exit 1 on any difference INDEX.json doesn't declare"
    )
    mode.add_argument(
        "--write", action="store_true", help="rewrite INDEX.json's computed fields and items.csv"
    )
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1), help="commands at a time")
    parser.add_argument(
        "--only", nargs="+", metavar="CELL", help="only these tasks (e.g. benchmark/test/r1 e2e)"
    )
    parser.add_argument(
        "--work", type=Path, help="keep the replays and logs in this folder (default: a temporary one)"
    )
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--index", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--items", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.write and args.only:
        parser.error("--write needs every task (no --only)")

    def say(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    results_dir: Path = args.results_dir
    index_path: Path = args.index or results_dir / INDEX_NAME
    items_path: Path = args.items or results_dir / export.ITEMS_CSV.name
    try:
        fresh = static_index(results_dir)
        committed = load_index(index_path) if index_path.is_file() else None
    except ReproduceError as exc:
        say(f"python -m evals.reproduce: {exc}")
        return 2
    if committed is None and args.check:
        say(f"python -m evals.reproduce: {index_path.name} is missing: run python -m evals.reproduce --write")
        return 2
    problems = static_problems(committed, fresh) if committed is not None and args.check else []
    work: Path = args.work or Path(tempfile.mkdtemp(prefix="ordnung-reproduce-"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        tasks = plan(fresh, results_dir, work)
        if args.only:
            tasks = [
                task
                for task in tasks
                if any(task.name == o or task.name.startswith(o.rstrip("/") + "/") for o in args.only)
            ]
        env = child_env(work)
        say(f"replaying {len(tasks)} commands, {args.jobs} at a time, into {work} (no model is called)")
        started = time.monotonic()
        done = run_tasks(tasks, jobs=args.jobs, env=env, say=say)
        seconds = time.monotonic() - started
        for name, result in sorted(done.items()):
            if result.rc != 0:
                problems.append(
                    f"{name}: failed (exit {result.rc}); the end of its log:\n{_tail(result.log)}"
                )
        replays = replays_of(tasks, done)
        problems += _verify(fresh, committed, results_dir, replays, done, write=args.write)
        gate_failed, gates = gate_problems(fresh, replays, done)
        problems += gate_failed
        served = [name for name, info in fresh["recordings"].items() if info["served_by_another_model"]]
        problems += [
            f"recordings {name}: some were answered by another model than {DEFAULT_MODEL}" for name in served
        ]
        if args.write:
            problems += pin_recordings(fresh, committed)
            index_path.write_text(dumps_index(fresh), encoding="utf-8")
            export.write(results_dir, items_path)
            say(f"wrote {index_path} and {items_path}")
            items = "written"
        else:
            stale = export.check(results_dir, items_path)
            problems += stale
            items = "✗" if stale else "✓"
        for line in scoreboard(fresh, gates, seconds=seconds, jobs=args.jobs, items=items):
            print(line, flush=True)
        for problem in problems:
            say(f"✗ {problem}")
        if problems:
            say(f"{len(problems)} problem(s){'' if args.write else ': nothing in INDEX.json declares them'}")
        return 1 if problems else 0
    except (ReproduceError, export.ExportError) as exc:
        say(f"python -m evals.reproduce: {exc}")
        return 2
    finally:
        if args.work is None:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
