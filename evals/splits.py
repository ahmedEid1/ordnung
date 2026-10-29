"""The benchmark's splits in one place: their role, their letter variants and whether they are recorded yet.

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

``evals/report.py`` keeps its own ``HELD_OUT_SPLITS`` for the published page (``tests/test_harness_run_index.py``
checks that it names this registry's held-out splits, in order).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Role = Literal["development", "iterated", "held-out", "final"]


@dataclass(frozen=True)
class Split:
    """One split of the benchmark."""

    name: str
    role: Role
    #: The letter variants written for it (``evals/gen/common.py``'s ``SPLIT_VARIANTS``); empty when its letters
    #: are not variants of the twelve families.
    variants: tuple[str, ...]
    #: Whether its letters and recordings exist yet.
    recorded: bool = True

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
    Split("holdout4", "final", ("K", "L", "M", "N"), recorded=False),
    Split("newkinds", "final", (), recorded=False),
)

_BY_NAME = {split.name: split for split in REGISTRY}


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


def recorded() -> tuple[str, ...]:
    """The splits whose letters and recordings exist, in order."""
    return tuple(split.name for split in REGISTRY if split.recorded)
