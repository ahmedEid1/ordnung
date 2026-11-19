"""Whether the pre-registered final run is published in this checkout, for the tests that pin what the repository
holds before it: the publish PR adds the final run's reads, its analysis and the files made from them all at once
(evals/results), so a test that knows today's results files says what changes once the final analysis is there.

The presenter's tests also render synthetic final runs over today's results files (``tests/helpers_final.py`` links
every committed results file into a temporary checkout beside a synthetic final analysis). Once the real final run is
published, :func:`results_before_publication` gives them the results folder as it was before the publish PR: every
committed results file but the final run's own (:func:`final_run_files`)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from evals import analysis, splits
from evals.present import model as present_model

ROOT = Path(__file__).resolve().parents[1]

RESULTS = ROOT / "evals" / "results"
#: The final run's splits: the registry's role ``final``.
FINAL_SPLITS = tuple(split.name for split in splits.REGISTRY if split.role == "final")


def final_published(results: Path = RESULTS) -> bool:
    """Whether ``results`` holds the pre-registered final analysis (``python -m evals.analysis --prereg …``)."""
    for path in sorted(results.glob(f"*-{analysis.FINAL_KIND}.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        meta = data.get("meta") if isinstance(data, dict) else None
        if isinstance(meta, dict) and data.get("schema") == analysis.ANALYSIS_SCHEMA:
            if meta.get("kind") == analysis.FINAL_KIND:
                return True
    return False


def of_the_final_run(name: str, data: Mapping[str, Any]) -> bool:
    """Whether the results file ``name`` (its JSON ``data``) is one the publish PR adds: the final run's own (the
    presenter's role ``final``: its reads, its analysis, the held-out Ask set's runs and their file of runs, the stress
    test), or a replay or re-scoring of one of its splits (without the sender's Land, with the checks off, end to
    end)."""
    if present_model.role_of(name, data) == "final":
        return True
    kind = present_model.kind_of(name, data)
    found = data.get("meta")
    meta: Mapping[str, Any] = found if isinstance(found, Mapping) else {}
    if kind == "run":
        replayed = {meta.get("split")}
    elif kind == "e2e":
        replayed = set(meta.get("splits") or ())
    else:
        replayed = set(data.get("splits") or ())
    return bool(replayed & set(FINAL_SPLITS))


def final_run_files(results: Path = RESULTS) -> list[str]:
    """The names of the final run's files in ``results`` (:func:`of_the_final_run`), sorted; none before the publish
    PR."""
    names = []
    for path in sorted(results.glob("*.json")):
        if path.name in present_model.NOT_RESULTS:
            continue
        if of_the_final_run(path.name, json.loads(path.read_text(encoding="utf-8"))):
            names.append(path.name)
    return names


def results_before_publication(folder: Path, results: Path = RESULTS) -> Path:
    """``folder`` made the results folder as it was before the publish PR: a link to every file of ``results`` but the
    final run's (:func:`final_run_files`), read only. ``INDEX.json`` is linked as it is (the presenter does not read
    it). Before the publish PR every file is linked."""
    left_out = set(final_run_files(results))
    folder.mkdir(parents=True, exist_ok=True)
    for path in sorted(results.glob("*.json")):
        if path.name not in left_out:
            (folder / path.name).symlink_to(path.resolve())
    return folder
