"""The final run's labels stay unread until its recording is published.

A split counts as recorded once a live, complete run of it is published: a results file directly in
``evals/results/`` (a file in a folder below it, as ``pending/``, is not published) whose ``meta`` says so. Until
then the census of recorded readings (``tests/test_reading_gaps_census.py``) leaves the split out, and the prediction
cache of a read recorded into ``evals/results/pending/`` is never committed (``evals/.gitignore``)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, NamedTuple

from evals import splits

ROOT = Path(__file__).resolve().parents[1]

RESULTS = ROOT / "evals" / "results"
#: The final run's splits: the registry's role ``final``.
FINAL = tuple(split.name for split in splits.REGISTRY if split.role == "final")


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
