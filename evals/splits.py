"""The benchmark's splits in one place: their role and their letter variants; whether their letters exist and whether
they are recorded is read from the data.

``evals/run.py`` reads this registry for ``--split`` and for the held-out rules (a held-out or final split is
recorded once, its run never rewrites ``docs/evals.md``, and a replay of it needs ``--results-dir``, so it never
lands beside its recording). A new split is one row here plus its letters (``evals/gen``), nothing else in the
runner.

Roles, in the order the splits were written:

* ``development`` — ``dev``: prompts and code were tuned on it;
* ``iterated`` — ``test``: the published split, re-scored as the code changed;
* ``held-out`` — ``holdout``, ``holdout2``, ``holdout3``: each written after a freeze and recorded once, nothing
  tuned on it;
* ``final`` — ``holdout4`` and ``newkinds``: written blind after the 0.4.0 freeze for the pre-registered final run.
  They are declared before their letters exist, so the run that adds them adds data only.

A split's state comes from the data, never from a constant here (each top-level ``evals/*.py`` file is in every
condition's fingerprint, so adding letters or a recording edits none of them):

* its letters exist when the manifest has entries of it (:func:`has_letters`);
* it is recorded once a live results file of it is published in ``evals/results/`` (:func:`recorded`); a file in a
  folder below it, as ``evals/results/pending/``, is not published.

``evals/report.py`` keeps its own ``HELD_OUT_SPLITS`` for the published page (``tests/test_harness_run_index.py``
checks that it names this registry's held-out splits, in order).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Role = Literal["development", "iterated", "held-out", "final"]

EVALS_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = EVALS_DIR / "dataset" / "manifest.json"
RESULTS_DIR = EVALS_DIR / "results"


@dataclass(frozen=True)
class Split:
    """One split of the benchmark."""

    name: str
    role: Role
    #: The letter variants written for it (``evals/gen/common.py``'s ``SPLIT_VARIANTS``); empty when its letters
    #: are not variants of the twelve families.
    variants: tuple[str, ...]

    @property
    def held_out(self) -> bool:
        """Recorded once, never tuned on, and never the published page's own run."""
        return self.role in ("held-out", "final")


REGISTRY: tuple[Split, ...] = (
    Split("dev", "development", ("A", "B")),
    Split("test", "iterated", ("C", "D")),
    Split("holdout", "held-out", ("E", "F")),
    Split("holdout2", "held-out", ("G", "H")),
    Split("holdout3", "held-out", ("I", "J")),
    Split("holdout4", "final", ("K", "L", "M", "N")),
    Split("newkinds", "final", ()),
)

_BY_NAME = {split.name: split for split in REGISTRY}
#: A run's results file, ``<date>-<model>-<split>[-r<N>].json`` (not a re-scoring, a partial run or another kind).
_RUN_FILE = re.compile(
    r"^\d{4}-\d{2}-\d{2}-.+-(?:" + "|".join(map(re.escape, _BY_NAME)) + r")(?:-r\d+)?\.json$"
)


def names() -> tuple[str, ...]:
    """Every split's name, in the order they were written."""
    return tuple(split.name for split in REGISTRY)


def get(name: str) -> Split:
    """The split called ``name`` (``KeyError`` for an unknown one)."""
    return _BY_NAME[name]


def is_held_out(name: str) -> bool:
    """Whether ``name`` is a held-out or final split (an unknown name is not)."""
    split = _BY_NAME.get(name)
    return split is not None and split.held_out


def is_final(name: str) -> bool:
    """Whether ``name`` is one of the final run's splits (an unknown name is not)."""
    split = _BY_NAME.get(name)
    return split is not None and split.role == "final"


def has_letters(name: str, manifest: Path = MANIFEST_PATH) -> bool:
    """Whether the manifest has entries of the split ``name``."""
    entries = json.loads(manifest.read_text(encoding="utf-8")).get("entries") or []
    return any(isinstance(entry, dict) and entry.get("split") == name for entry in entries)


def _live_split(path: Path) -> str | None:
    """The split a published live run's results file holds (``None``: a replay, a partial run, not a run)."""
    try:
        meta = json.loads(path.read_text(encoding="utf-8")).get("meta")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(meta, dict) or meta.get("backend") != "live" or meta.get("partial"):
        return None
    split = meta.get("split")
    return split if isinstance(split, str) else None


def recorded(results_dir: Path = RESULTS_DIR) -> tuple[str, ...]:
    """The splits with a published live results file in ``results_dir`` (not in a folder below it), in order."""
    found = {_live_split(path) for path in sorted(results_dir.glob("*.json")) if _RUN_FILE.match(path.name)}
    return tuple(name for name in names() if name in found)


def is_recorded(name: str, results_dir: Path = RESULTS_DIR) -> bool:
    """Whether a live results file of the split ``name`` is published in ``results_dir``."""
    return name in recorded(results_dir)
