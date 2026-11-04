"""The benchmark's analysis: exact statistics, harm and selective prediction, from results files alone.

It reads ``evals/results/*.json`` (and, for the final run, its pre-registration, the deviations file, the recordings'
day index and ledger, and the dataset's manifest) and nothing else: no model call, no replay, no change to the scorer
(``evals/metrics.py``) or to the records (``evals/records.py``, part of every recording's code digest).

* ``python -m evals.analysis`` — **the held-out splits re-analysed**: holdout, holdout2 and holdout3 as recorded
  (:data:`HELD_OUT_AS_RECORDED`, the held-out rows of ``docs/evals.md``), pooled, with the statistics of
  :mod:`evals.stats`. It is labelled *not pre-registered*: these statistics were chosen after the results were known.
  ``--write [--date D]`` writes ``evals/results/<D>-claude-sonnet-5-heldout-reanalysis.json``; ``--check`` renders it
  again and fails when the committed file differs.
* ``python -m evals.analysis --prereg FILE RESULTS…`` — **the pre-registered final run**: the reads the
  pre-registration names (its ``analysis`` section, :func:`default_prereg_analysis`), its primary families F1–F3 with
  Holm, the one-read sensitivity analysis, the descriptive secondary numbers and the decisions its rules take.
  ``--write`` / ``--check`` as above, for ``evals/results/<date>-claude-sonnet-5-final.json`` (``--date``, else the
  date of the last primary read).

The final run is analysed only as it was registered. Before any number, :func:`check_frozen` compares every read with
the pre-registration's frozen inputs: the fingerprints of the code and prompts, the model that answered (the ledger),
the dataset's manifest, a clean tree, each unit's day inside [``planned_day``, ``valid_until``] and its ``claude``
version (the day index, ``evals/recorded/<model>/final-days.json``), and a letter left without an answer. A unit is one
letter in one read, with all its conditions. A mismatch is refused unless a deviation recorded at the time names it
(the deviations file: posted on the pre-registration issue, with its time and the checkpoint commit that pushed it);
then it has its kind's fixed consequence (:data:`DEVIATION_CONSEQUENCES`), never one chosen after the results.

The pre-registration's fields read besides ``analysis``: ``registered.planned_day`` and ``valid_until``;
``frozen.fingerprints`` (per condition), ``frozen.cli_versions`` and ``frozen.served_models``;
``data.manifest_sha256``; ``deviation_kinds`` (it must be :data:`DEVIATION_CONSEQUENCES`); ``deviations_file``. A
deviation names what it applies to in ``applies_to``: ``split`` and ``repeat`` (a read), ``entries`` (its units),
``items`` (``label_error``: entry id, item index and the corrected date) or ``first_attempt`` (``retake``: entry id,
condition and the first attempt's outcome).

Definitions, in one place:

* a **scored item** is a required item with one concrete expected date (the scorer's ``outcome`` is not
  ``unscored``): the due-date accuracy denominator;
* **right** is the exact date; **late** / **early** a wrong date after / before the truth; **missed** not found;
  **declined** found without a date;
* **harmful = late or missed**, the safety endpoint (the scorer's "dangerously late" leaves a missed deadline out; it
  is still reported, for continuity with the CI gates);
* a **letter fully right** has every scored date right and no spurious dated item (the scorer's
  ``false_positives``), over the letters with at least one scored date (``letters_fully_right``) and over every letter
  (``letters_fully_right_all``);
* the **tier** of a date is what the person sees: ``please_check`` (low confidence or "Please check", or found
  without a date), ``second_look`` (medium confidence: "Worth a second look") or ``none`` (no flag — and a missed date,
  which shows nothing);
* a **cluster** is a letter together with the photo rendered from it, named with its split;
* an item is **unstable** over repeated reads when its date (or "no date") is not the same in every read.

Every output holds ids, counts, hashes and metric values only (and the days units were recorded on): never a letter's
text, a title, a quote, a warning or a date it names. Floats are rounded to :data:`SIGNIFICANT_DIGITS` significant digits, so a render is byte-identical on every
platform.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import date as calendar_date
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Any

from evals import stats
from evals.metrics import DATE_TOOLS, TOOL_CONDITION, TOOL_PEERS, bootstrap_difference, bootstrap_ratio
from evals.records import CONDITIONS

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "evals" / "results"
#: The final run's recordings (its day index and ledger, below ``<model>/``) and the dataset whose manifest the
#: pre-registration pins.
RECORDED_DIR = ROOT / "evals" / "recorded"
DATASET_DIR = ROOT / "evals" / "dataset"
DAY_INDEX_FILE = "final-days.json"
LEDGER_FILE = "ledger.jsonl"
MANIFEST_FILE = "manifest.json"
#: The pinned benchmark model: the re-analysis reads its held-out runs.
MODEL = "claude-sonnet-5"
ANALYSIS_SCHEMA = "ordnung-eval-analysis/1"
PREREG_SCHEMA = "ordnung-prereg-analysis/1"
REANALYSIS_KIND = "heldout-reanalysis"
FINAL_KIND = "final"
#: The held-out runs as recorded once (the held-out rows of docs/evals.md, ``tests/test_docs_claims.py``).
HELD_OUT_AS_RECORDED = (
    "2026-09-30-claude-sonnet-5-holdout.json",
    "2026-10-01-claude-sonnet-5-holdout2.json",
    "2026-10-06-claude-sonnet-5-holdout3.json",
)
SPLIT_ORDER = ("dev", "test", "holdout", "holdout2", "holdout3", "holdout4", "newkinds")
REFERENCE = "ordnung"
LOSS_RATIOS = (1, 2, 5, 10, 20, 50)
CROSSOVER_RESAMPLES = 2000
SIGNIFICANT_DIGITS = 10
TIERS = ("none", "second_look", "please_check")
#: How strongly a tier tells the person to check (the score of "this date may be wrong").
TIER_LEVEL = {"none": 0, "second_look": 1, "please_check": 2}
CONFIDENCES = ("high", "medium", "low", "none")
#: What the rules engine takes from Ordnung's reading: the DateSpec fields (not its quoted text), the letter's date and
#: the sender's kind. Two reads read an item alike when all of these are equal.
READING_FIELDS = (
    "type",
    "date",
    "time",
    "anchor",
    "anchor_date",
    "amount",
    "unit",
    "delivery_rule",
    "shift_rule",
    "nature",
)
#: The verdict of a one-read paired comparison (not pre-registered; the final run's rules are its own).
VERDICTS = {
    "clear": "a clear difference",
    "suggestive": "suggestive, not settled",
    "none": "no clear difference",
}
#: How the final run is analysed, as the pre-registration's ``analysis.rules`` names it: the code implements exactly
#: these, and :func:`parse_prereg` refuses any other value.
RULES = {
    "harmful": "late_or_missed",
    "instability": "date_or_no_date_differs_between_reads",
    "f1_f2_test": "cluster_signflip_two_sided_item_weighted",
    "interval": "paired_cluster_bootstrap_percentile",
    "f3_test": "mcnemar_midp_bonett_price",
    "multiplicity": "holm_within_each_family",
    "noninferiority": "signflip_test_inversion",
    "sensitivity_r1": "exact_mcnemar_midp_bonett_price",
}
#: The final run's one confirmatory decision: F1, Ordnung against the model alone. Every other is secondary.
CONFIRMATORY = {"family": "F1_accuracy", "baseline": "llm_only"}
#: The sensitivity analyses and exploratory blocks the code can give; the pre-registration names which it gives.
SENSITIVITIES = ("s_conv", "label_corrected", "first_attempt", "same_day_f3", "same_cli_f3")
EXPLORATORY = ("by_family", "by_modality", "by_adversarial_class", "by_recording_day", "pooled_held_out")
#: The fewest reads F3 (stability) is run on; with fewer, read 1's cluster tests are the primary analysis.
MIN_READS = 2
#: What a deviation of each kind does to the final run's analysis.
INVALID, EXCLUDE_READ, EXCLUDE_UNIT, INCLUDE, NOT_RUN, RETIRED, SENSITIVITY = (
    "invalid",
    "exclude_read",
    "exclude_unit",
    "include",
    "not_run",
    "retired",
    "sensitivity",
)
DEVIATION_EFFECTS = {
    "fingerprint": INVALID,
    "code_digest": INVALID,
    "prompt_hash": INVALID,
    "model": INVALID,
    "manifest_mismatch": EXCLUDE_READ,
    "dirty_tree": EXCLUDE_READ,
    "day_outside_window": EXCLUDE_UNIT,
    "cli_version": INCLUDE,
    "retake": INCLUDE,
    "unanswered": INCLUDE,
    "infrastructure": INCLUDE,
    "budget_cut": NOT_RUN,
    "window_closed": NOT_RUN,
    "retired_set": RETIRED,
    "label_error": SENSITIVITY,
    "scorer_bug": INCLUDE,
    "code_hash_changed": INCLUDE,
}
_NEVER_WAIVABLE = (
    "never waivable: the read is invalid; a mandatory read is recorded again inside the window if possible, "
    'otherwise "not recorded"'
)
_NOT_RUN = "the step is not run or not completed, and is published as such"
#: Each deviation kind's consequence, fixed before any recording: the pre-registration's ``deviation_kinds`` must be
#: this table, so the analysis applies what was registered.
DEVIATION_CONSEQUENCES = {
    "fingerprint": _NEVER_WAIVABLE,
    "code_digest": _NEVER_WAIVABLE,
    "prompt_hash": _NEVER_WAIVABLE,
    "model": _NEVER_WAIVABLE,
    "manifest_mismatch": "exclude the read",
    "dirty_tree": "exclude the read",
    "day_outside_window": "exclude the unit (listed; scored as not recorded)",
    "cli_version": "include; per-unit versions; same-CLI F3 sensitivity",
    "retake": "include the retaken unit; the first attempt is published; first-attempt sensitivity",
    "unanswered": "include, scored empty",
    "infrastructure": "include (calls lost, cost unknown)",
    "budget_cut": _NOT_RUN,
    "window_closed": _NOT_RUN,
    "retired_set": "the set is not analysed; every recorded unit is published",
    "label_error": "only from the blind review of the items any condition got wrong (an owner's finding goes "
    "through it too): the primary stays; label-corrected sensitivity",
    "scorer_bug": "the primary stays; re-scored files after publication",
    "code_hash_changed": "the runner-defect rule, or a presentation-only change listed per path",
}
#: A mismatch with the frozen inputs, and the deviation kinds that may name it.
_EXCUSED_BY = {
    "fingerprint": ("fingerprint", "code_digest", "prompt_hash"),
    "model": ("model",),
    "manifest_mismatch": ("manifest_mismatch",),
    "dirty_tree": ("dirty_tree",),
    "day_outside_window": ("day_outside_window",),
    "cli_version": ("cli_version",),
    "unanswered": ("unanswered",),
}
#: The outcomes a retake records for each first attempt.
FIRST_ATTEMPT_OUTCOMES = ("ok", "failed", "timeout", "infra")
_COMMENT_URL = re.compile(r"https://github\.com/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/issues/\d+#issuecomment-\d+")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_DEVIATIONS_PATH = re.compile(r"evals/preregistration/deviations-[^/]+\.json")


class AnalysisError(ValueError):
    """The inputs do not fit the analysis (a missing or doubled read, another model, different items …)."""


@dataclass(frozen=True)
class Settings:
    """How the analysis resamples and decides; the final run's come from its pre-registration."""

    seed: int = stats.SEED
    resamples: int = stats.BOOTSTRAP_RESAMPLES
    signflip_draws: int = stats.SIGNFLIP_DRAWS
    signflip_exact_max: int = stats.SIGNFLIP_EXACT_MAX
    crossover_resamples: int = CROSSOVER_RESAMPLES
    level: float = stats.CONFIDENCE_LEVEL
    alpha: float = 0.05
    noninferiority_margin: float = 0.05
    loss_ratios: tuple[float, ...] = LOSS_RATIOS

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["loss_ratios"] = list(self.loss_ratios)
        return data


# --------------------------------------------------------------------------------------------------
# Reading results files
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """One scored item of one condition in one read: ids and outcome, never its text or dates."""

    split: str
    entry_id: str
    index: int
    cluster: str
    family: str
    modality: str
    outcome: str
    direction: str | None
    days_off: int | None
    predicted: str | None
    flagged: bool
    confidence: str | None
    cause: str | None
    #: What the rules engine took from the reading (``READING_FIELDS``), as canonical JSON; ``None`` without one.
    reading: str | None
    #: The letter's today in this read: the day its unit was recorded (``None`` when the file does not say).
    day: str | None = None

    @property
    def key(self) -> tuple[str, str, int]:
        return self.split, self.entry_id, self.index

    @property
    def right(self) -> bool:
        return self.outcome == "correct"

    @property
    def late(self) -> bool:
        return self.direction == "late"

    @property
    def early(self) -> bool:
        return self.direction == "early"

    @property
    def missed(self) -> bool:
        return self.outcome == "missed"

    @property
    def declined(self) -> bool:
        return self.outcome == "declined"

    @property
    def harmful(self) -> bool:
        return self.late or self.missed

    @property
    def tier(self) -> str:
        if self.missed:
            return "none"
        if self.predicted is None or self.flagged:
            return "please_check"
        return "second_look" if self.confidence == "medium" else "none"


@dataclass(frozen=True)
class Letter:
    """One letter of one condition in one read: counts, cost and time."""

    split: str
    entry_id: str
    cluster: str
    scored: int
    right: int
    late: int
    spurious: int
    cost_usd: float
    latency_ms: int
    calls: int
    kind_ok: bool
    #: Calls of the date tools (``None``: the condition had no tools).
    date_tool_calls: int | None
    #: A model failure (scored, never retried) and an infrastructure error (no answer at all).
    failed: bool = False
    error: bool = False
    #: The scorer's adversarial checks that apply to the letter, and whether each passed.
    adversarial: tuple[tuple[str, bool], ...] = ()

    @property
    def fully_right(self) -> bool:
        return self.right == self.scored and self.spurious == 0


@dataclass(frozen=True)
class Run:
    """One results file, read for the analysis."""

    name: str
    sha256: str
    results: Mapping[str, Any]
    split: str
    repeat: int
    model: str
    conditions: tuple[str, ...]
    items: Mapping[str, tuple[Item, ...]]
    letters: Mapping[str, tuple[Letter, ...]]

    @property
    def meta(self) -> Mapping[str, Any]:
        meta: Mapping[str, Any] = self.results.get("meta") or {}
        return meta

    def input_record(self) -> dict[str, Any]:
        meta = self.meta
        return {
            "file": self.name,
            "sha256": self.sha256,
            "split": self.split,
            "repeat": self.repeat,
            "date": meta.get("date"),
            "commit": meta.get("commit"),
            "backend": meta.get("backend"),
        }


def _ordered_conditions(names: Sequence[str]) -> tuple[str, ...]:
    present = set(names)
    return tuple([c for c in CONDITIONS if c in present] + sorted(present - set(CONDITIONS)))


def _reading(prediction: Mapping[str, Any] | None, pred_index: int | None) -> str | None:
    if prediction is None or pred_index is None:
        return None
    items = prediction.get("items") or []
    if not 0 <= pred_index < len(items):
        return None
    spec = items[pred_index].get("spec")
    if not isinstance(spec, Mapping):
        return None
    reading = {field: spec.get(field) for field in READING_FIELDS}
    reading["document_date"] = prediction.get("document_date")
    reading["sender_kind"] = prediction.get("sender_kind")
    return json.dumps(reading, sort_keys=True, ensure_ascii=True)


def load_run(results: Mapping[str, Any], *, name: str = "", sha256: str = "") -> Run:
    """A results document read for the analysis (its scores; its predictions only for what the engine read)."""
    meta = results.get("meta") or {}
    split = str(meta.get("split") or "")
    entries = results.get("entries") or []
    named = meta.get("conditions") or sorted(
        {c for entry in entries for c in (entry.get("conditions") or {})}
    )
    conditions = _ordered_conditions([str(c) for c in named])
    items: dict[str, list[Item]] = {c: [] for c in conditions}
    letters: dict[str, list[Letter]] = {c: [] for c in conditions}
    for entry in entries:
        told = entry.get("simulated_today") or entry.get("today")
        for condition in conditions:
            value = (entry.get("conditions") or {}).get(condition) or {}
            score = value.get("score")
            if score is None:
                continue
            prediction = value.get("prediction")
            cluster = f"{split}/{score.get('cluster') or entry['id']}"
            scored = [item for item in score.get("items") or [] if item.get("outcome") != "unscored"]
            for item in scored:
                items[condition].append(
                    Item(
                        split=split,
                        entry_id=str(entry["id"]),
                        index=int(item["index"]),
                        cluster=cluster,
                        family=str(entry.get("family") or score.get("family") or ""),
                        modality=str(entry.get("modality") or score.get("modality") or ""),
                        outcome=str(item["outcome"]),
                        direction=item.get("direction"),
                        days_off=item.get("days_off"),
                        predicted=item.get("predicted"),
                        flagged=bool(item.get("flagged")),
                        confidence=item.get("confidence"),
                        cause=item.get("cause"),
                        reading=_reading(prediction, item.get("pred_index")),
                        day=str(told) if told else None,
                    )
                )
            tool_calls = score.get("tool_calls")
            letters[condition].append(
                Letter(
                    split=split,
                    entry_id=str(entry["id"]),
                    cluster=cluster,
                    scored=len(scored),
                    right=sum(1 for item in scored if item.get("outcome") == "correct"),
                    late=sum(1 for item in scored if item.get("direction") == "late"),
                    spurious=int(score.get("false_positives") or 0),
                    cost_usd=float(score.get("cost_usd") or 0.0),
                    latency_ms=int(score.get("latency_ms") or 0),
                    calls=int(score.get("calls") or 0),
                    kind_ok=bool(score.get("kind_ok")),
                    date_tool_calls=None
                    if tool_calls is None
                    else sum(int(tool_calls.get(name) or 0) for name in DATE_TOOLS),
                    failed=bool(score.get("failed")),
                    error=bool(score.get("error")),
                    adversarial=tuple(
                        sorted(
                            (str(name), bool(passed))
                            for name, passed in (score.get("adversarial") or {}).items()
                            if passed is not None
                        )
                    ),
                )
            )
    return Run(
        name=name,
        sha256=sha256,
        results=results,
        split=split,
        repeat=int(meta.get("repeat") or 1),
        model=str(meta.get("model") or ""),
        conditions=conditions,
        items={c: tuple(v) for c, v in items.items()},
        letters={c: tuple(v) for c, v in letters.items()},
    )


def read_run(path: Path) -> Run:
    """A results file read for the analysis, with the sha256 of its bytes."""
    data = path.read_bytes()
    return load_run(json.loads(data), name=path.name, sha256=hashlib.sha256(data).hexdigest())


def _split_rank(split: str) -> tuple[int, str]:
    return (SPLIT_ORDER.index(split) if split in SPLIT_ORDER else len(SPLIT_ORDER), split)


def _sorted_runs(runs: Sequence[Run]) -> list[Run]:
    return sorted(runs, key=lambda run: (_split_rank(run.split), run.repeat, run.name))


# --------------------------------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------------------------------


def rate(k: int, n: int, level: float = stats.CONFIDENCE_LEVEL) -> dict[str, Any]:
    """``k / n`` with its Clopper–Pearson interval (``None`` for no items)."""
    if n <= 0:
        return {"k": k, "n": n, "value": None, "ci": [None, None]}
    lo, hi = stats.clopper_pearson(k, n, level=level)
    return {"k": k, "n": n, "value": k / n, "ci": [lo, hi]}


def _ratio_key(r: float) -> str:
    return str(int(r)) if float(r).is_integer() else repr(float(r))


def _pair_key(first: str, second: str) -> str:
    return f"{first}-vs-{second}"


def selective(items: Sequence[Item], level: float) -> dict[str, Any]:
    """Selective prediction: per tier the right, wrong and harmful dates; how well "Please check" (and any flag)
    catches the wrong and the harmful dates; the dates shown without a flag; AUROC and AURC of the tier."""
    n = len(items)
    wrong = [item for item in items if not item.right]
    harmful = [item for item in items if item.harmful]
    tiers = {
        tier: {
            "items": sum(1 for item in items if item.tier == tier),
            "right": sum(1 for item in items if item.tier == tier and item.right),
            "wrong": sum(1 for item in items if item.tier == tier and not item.right),
            "harmful": sum(1 for item in items if item.tier == tier and item.harmful),
        }
        for tier in TIERS
    }

    def flags(chosen: set[str]) -> dict[str, Any]:
        flagged = [item for item in items if item.tier in chosen]
        caught = sum(1 for item in flagged if not item.right)
        caught_harm = sum(1 for item in flagged if item.harmful)
        return {
            "share": rate(len(flagged), n, level),
            "precision": rate(caught, len(flagged), level),
            "recall_wrong": rate(caught, len(wrong), level),
            "recall_harmful": rate(caught_harm, len(harmful), level),
        }

    unflagged = [item for item in items if item.tier == "none"]
    risk = stats.aurc([-TIER_LEVEL[item.tier] for item in items], [not item.right for item in items])
    return {
        "tiers": tiers,
        "please_check": flags({"please_check"}),
        "any_flag": flags({"second_look", "please_check"}),
        "unflagged": {
            "coverage": rate(len(unflagged), n, level),
            "accuracy": rate(sum(1 for item in unflagged if item.right), len(unflagged), level),
            "harmful": rate(sum(1 for item in unflagged if item.harmful), len(unflagged), level),
        },
        "auroc": stats.auroc(
            [TIER_LEVEL[item.tier] for item in wrong], [TIER_LEVEL[item.tier] for item in items if item.right]
        ),
        "aurc": risk.to_dict() if risk is not None else None,
    }


def _cost(letters: Sequence[Letter], right: int) -> dict[str, Any]:
    with_calls = [letter for letter in letters if letter.calls]
    total = math.fsum(letter.cost_usd for letter in letters)
    return {
        "usd_total": total,
        "letters": len(with_calls),
        "usd_per_letter": total / len(with_calls) if with_calls else None,
        "usd_per_right_date": total / right if right else None,
    }


def _latency(letters: Sequence[Letter]) -> dict[str, Any]:
    values = [float(letter.latency_ms) for letter in letters if letter.calls]
    return {
        "p50": stats.percentile(values, 50),
        "p95": stats.percentile(values, 95),
        "mean": math.fsum(values) / len(values) if values else None,
    }


def condition_summary(items: Sequence[Item], letters: Sequence[Letter], settings: Settings) -> dict[str, Any]:
    """One condition over one read of its letters: rates with exact intervals, harm, strictness, selective
    prediction, harm-weighted loss, cost and latency."""
    level = settings.level
    n = len(items)
    right = sum(1 for item in items if item.right)
    early = sum(1 for item in items if item.early)
    harmful = sum(1 for item in items if item.harmful)
    dated_letters = [letter for letter in letters if letter.scored]
    by_confidence = {
        confidence: {
            "right": sum(1 for i in items if (i.confidence or "none") == confidence and i.right),
            "wrong": sum(1 for i in items if (i.confidence or "none") == confidence and not i.right),
        }
        for confidence in CONFIDENCES
    }
    return {
        "items": n,
        "exact": rate(right, n, level),
        "late": rate(sum(1 for item in items if item.late), n, level),
        "early": rate(early, n, level),
        "missed": rate(sum(1 for item in items if item.missed), n, level),
        "declined": rate(sum(1 for item in items if item.declined), n, level),
        "harmful": rate(harmful, n, level),
        "days_late": sorted(int(item.days_off or 0) for item in items if item.late),
        "days_early": sorted(int(item.days_off or 0) for item in items if item.early),
        "letters_fully_right": rate(
            sum(1 for letter in dated_letters if letter.fully_right), len(dated_letters), level
        ),
        "letters_fully_right_all": rate(
            sum(1 for letter in letters if letter.fully_right), len(letters), level
        ),
        "spurious_dated_items": sum(letter.spurious for letter in letters),
        "letters_with_spurious": sum(1 for letter in letters if letter.spurious),
        "kind_recognised": rate(sum(1 for letter in letters if letter.kind_ok), len(letters), level),
        "by_confidence": by_confidence,
        "selective": selective(items, level),
        "loss": {_ratio_key(r): stats.harm_loss(early, harmful, n, r) for r in settings.loss_ratios},
        "cost": _cost(letters, right),
        "latency_ms": _latency(letters),
    }


def _published_settings(runs: Sequence[Run]) -> tuple[int, int] | None:
    """The seed and resamples the runs' own scorer used, when they all used the same."""
    found = {(run.meta.get("seed"), run.meta.get("resamples")) for run in runs}
    if len(found) != 1:
        return None
    seed, resamples = found.pop()
    return (int(seed), int(resamples)) if seed is not None and resamples is not None else None


def _letter_units(letters: Sequence[Letter], hit: Callable[[Letter], int]) -> list[tuple[str, float, float]]:
    """The scorer's bootstrap units, one per letter (letters without a scored date too, as it stores them)."""
    return [(letter.cluster, float(hit(letter)), float(letter.scored)) for letter in letters]


def _published_ci(
    letters: Sequence[Letter], hit: Callable[[Letter], int], published: tuple[int, int]
) -> list[Any]:
    seed, resamples = published
    estimate = bootstrap_ratio(_letter_units(letters, hit), resamples=resamples, seed=seed)
    return [estimate.lo, estimate.hi]


def _by_cluster(
    first: Mapping[tuple[str, str, int], Item],
    second: Mapping[tuple[str, str, int], Item],
    keys: Sequence[tuple[str, str, int]],
    indicator: Callable[[Item], bool],
) -> list[tuple[str, int, int, int]]:
    """Per cluster: (cluster, the first's hits, the second's hits, items), in cluster order."""
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for key in keys:
        row = sums[first[key].cluster]
        row[0] += int(indicator(first[key]))
        row[1] += int(indicator(second[key]))
        row[2] += 1
    return [(cluster, row[0], row[1], row[2]) for cluster, row in sorted(sums.items())]


def paired_one_read(
    first_items: Sequence[Item],
    second_items: Sequence[Item],
    indicator: Callable[[Item], bool],
    settings: Settings,
) -> dict[str, Any]:
    """Two conditions on the same items, one read: the discordant pairs, exact and mid-p McNemar, Bonett–Price, and
    the clustered view (sign-flip test over letter clusters, paired cluster bootstrap). ``diff`` is the first's rate
    of ``indicator`` minus the second's."""
    first = {item.key: item for item in first_items}
    second = {item.key: item for item in second_items}
    keys = sorted(first.keys() & second.keys())
    n = len(keys)
    b = sum(1 for key in keys if indicator(first[key]) and not indicator(second[key]))
    c = sum(1 for key in keys if not indicator(first[key]) and indicator(second[key]))
    clusters = _by_cluster(first, second, keys, indicator)
    flip = stats.cluster_signflip(
        [row[1] - row[2] for row in clusters],
        exact_max=settings.signflip_exact_max,
        draws=settings.signflip_draws,
        seed=settings.seed,
    )
    boot = stats.paired_cluster_bootstrap(
        [(float(row[1]), float(row[2]), float(row[3])) for row in clusters],
        resamples=settings.resamples,
        seed=settings.seed,
        level=settings.level,
    )
    return {
        "n": n,
        "b": b,
        "c": c,
        "diff": (b - c) / n if n else None,
        "exact_p": stats.mcnemar_exact(b, c),
        "midp": stats.mcnemar_midp(b, c),
        "bonett_price": list(stats.bonett_price(b, c, n, level=settings.level)) if n else [None, None],
        "signflip": flip.to_dict(),
        "cluster_bootstrap": boot.to_dict(),
    }


def _with_holm(family: dict[str, dict[str, Any]], alpha: float) -> dict[str, dict[str, Any]]:
    """Holm within the family, for the exact, the mid-p and the sign-flip p-values; and each pair's verdict."""
    keys = list(family)
    for source, target in (("exact_p", "holm_exact"), ("midp", "holm_midp")):
        for key, adjusted in zip(keys, stats.holm([family[k][source] for k in keys]), strict=True):
            family[key][target] = adjusted
    for key, adjusted in zip(keys, stats.holm([family[k]["signflip"]["p"] for k in keys]), strict=True):
        family[key]["signflip"]["holm"] = adjusted
    for row in family.values():
        row["verdict"] = _verdict(row, alpha)
    return family


def _verdict(row: Mapping[str, Any], alpha: float) -> str:
    """``clear`` when the Holm-adjusted exact McNemar p and the Holm-adjusted letter-cluster sign-flip p are both below
    ``alpha`` and Bonett–Price excludes 0 (the item-level mid-p treats a letter and its photo as two independent
    pairs, so it alone never makes a difference clear); ``suggestive`` when the unadjusted mid-p is below ``alpha``;
    else ``none``."""
    lo, hi = row["bonett_price"]
    excludes_zero = lo is not None and hi is not None and (lo > 0 or hi < 0)
    if row["holm_exact"] < alpha and row["signflip"]["holm"] < alpha and excludes_zero:
        return "clear"
    return "suggestive" if row["midp"] < alpha else "none"


def _crossover(first: Sequence[Item], second: Sequence[Item], settings: Settings) -> dict[str, Any]:
    """Where the two conditions' harm-weighted losses cross as a harmful date costs more (:func:`stats.crossover_outcome`:
    which side is lower, and ``r*`` when they cross), with a letter-cluster bootstrap: the share of resamples with each
    outcome, and the interval of ``r*`` over the resamples that cross the same way as the point estimate."""
    a = {item.key: item for item in first}
    b = {item.key: item for item in second}
    keys = sorted(a.keys() & b.keys())
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for key in keys:
        row = sums[a[key].cluster]
        row[0] += int(a[key].early)
        row[1] += int(a[key].harmful)
        row[2] += int(b[key].early)
        row[3] += int(b[key].harmful)
    clusters = [sums[name] for name in sorted(sums)]
    columns = [[row[i] for row in clusters] for i in range(4)]
    totals = [sum(column) for column in columns]
    outcome, point = stats.crossover_outcome(*totals)
    counts = dict.fromkeys(stats.CROSSOVER_OUTCOMES, 0)
    draws: list[float] = []
    resamples = stats.resample_indices(len(clusters), settings.crossover_resamples, settings.seed)
    for drawn in resamples:
        found, value = stats.crossover_outcome(*(sum(map(column.__getitem__, drawn)) for column in columns))
        counts[found] += 1
        if found == outcome and value is not None:
            draws.append(value)
    alpha = (1.0 - settings.level) / 2.0 * 100.0
    return {
        "early": [totals[0], totals[2]],
        "harmful": [totals[1], totals[3]],
        "outcome": outcome,
        "r_star": point,
        "shares": {name: count / len(resamples) if resamples else None for name, count in counts.items()},
        "bootstrap": {
            "lo": stats.percentile(draws, alpha),
            "median": stats.percentile(draws, 50.0),
            "hi": stats.percentile(draws, 100.0 - alpha),
            "draws": len(draws),
            "resamples": settings.crossover_resamples,
            "seed": settings.seed,
        },
    }


def _error_rows(
    items_by_condition: Mapping[str, Sequence[Item]], read: int | None = None
) -> list[dict[str, Any]]:
    rows = []
    for condition, items in items_by_condition.items():
        for item in sorted(items, key=lambda i: (_split_rank(i.split), i.entry_id, i.index)):
            if item.right:
                continue
            row: dict[str, Any] = {
                "condition": condition,
                "split": item.split,
                "entry_id": item.entry_id,
                "item": item.index,
                "family": item.family,
                "modality": item.modality,
                "outcome": item.outcome,
                "direction": item.direction,
                "days_off": item.days_off,
                "confidence": item.confidence,
                "flagged": item.flagged,
                "tier": item.tier,
                "cause": item.cause,
            }
            if read is not None:
                row["read"] = read
            rows.append(row)
    return rows


# --------------------------------------------------------------------------------------------------
# One read of one or more splits (the held-out re-analysis, a secondary split, the exploratory pool)
# --------------------------------------------------------------------------------------------------


#: The one-read paired families, Ordnung against each baseline (Holm within each): accuracy, harm (late or missed)
#: and dangerously late (the CI gates' metric, for continuity).
_FAMILIES: tuple[tuple[str, Callable[[Item], bool]], ...] = (
    ("accuracy", lambda i: i.right),
    ("harmful", lambda i: i.harmful),
    ("late", lambda i: i.late),
)
#: The rates each split's own row shows.
_SPLIT_RATES: tuple[tuple[str, Callable[[Item], bool]], ...] = (
    ("exact", lambda i: i.right),
    ("harmful", lambda i: i.harmful),
    ("late", lambda i: i.late),
    ("early", lambda i: i.early),
    ("missed", lambda i: i.missed),
)


def _check_single_read(runs: Sequence[Run]) -> tuple[str, tuple[str, ...]]:
    if not runs:
        raise AnalysisError("no results files to analyse")
    splits = [run.split for run in runs]
    if len(set(splits)) != len(splits):
        raise AnalysisError(f"each split is read once here, but {', '.join(splits)} were given")
    models = {run.model for run in runs}
    if len(models) != 1:
        raise AnalysisError(f"the runs are of different models: {', '.join(sorted(models))}")
    for run in runs:
        if run.meta.get("partial"):
            raise AnalysisError(f"{run.name or run.split}: a filtered run does not cover its split")
    shared = [c for c in runs[0].conditions if all(c in run.conditions for run in runs)]
    if REFERENCE not in shared:
        raise AnalysisError("every run must hold Ordnung's answers")
    return models.pop(), tuple(shared)


def single_read(runs: Sequence[Run], settings: Settings, *, paired: bool = True) -> dict[str, Any]:
    """One read of one or more splits, pooled: per condition the rates (exact intervals, and the scorer's published
    interval beside them), harm, strictness, selective prediction, loss, cost and latency; with ``paired``, the
    paired families (Holm within each), the crossovers, each split's rows and every wrong date by id."""
    runs = _sorted_runs(runs)
    _, conditions = _check_single_read(runs)
    items = {c: [item for run in runs for item in run.items[c]] for c in conditions}
    letters = {c: [letter for run in runs for letter in run.letters[c]] for c in conditions}
    published = _published_settings(runs)
    summaries: dict[str, Any] = {}
    for condition in conditions:
        summary = condition_summary(items[condition], letters[condition], settings)
        if published is not None:
            summary["exact"]["published_ci"] = _published_ci(letters[condition], lambda x: x.right, published)
            summary["late"]["published_ci"] = _published_ci(letters[condition], lambda x: x.late, published)
        summaries[condition] = summary
    body: dict[str, Any] = {
        "items": len(items[REFERENCE]),
        "letters": len(letters[REFERENCE]),
        "clusters": len({item.cluster for item in items[REFERENCE]}),
        "conditions": summaries,
    }
    if not paired:
        return body
    baselines = [c for c in conditions if c != REFERENCE]
    families: dict[str, dict[str, dict[str, Any]]] = {}
    for name, indicator in _FAMILIES:
        families[name] = {
            _pair_key(REFERENCE, other): paired_one_read(items[REFERENCE], items[other], indicator, settings)
            for other in baselines
        }
    families["agent"] = {
        _pair_key(TOOL_CONDITION, peer): paired_one_read(
            items[TOOL_CONDITION], items[peer], lambda i: i.right, settings
        )
        for peer in TOOL_PEERS
        if TOOL_CONDITION in conditions and peer in conditions
    }
    for rows in families.values():
        _with_holm(rows, settings.alpha)
    if published is not None:
        seed, resamples = published
        for family, hit in (
            ("accuracy", lambda x: x.right),
            ("late", lambda x: x.late),
            ("agent", lambda x: x.right),
        ):
            for key, row in families[family].items():
                first, second = key.split("-vs-", 1)
                estimate = bootstrap_difference(
                    _letter_units(letters[first], hit),
                    _letter_units(letters[second], hit),
                    resamples=resamples,
                    seed=seed,
                )
                row["published_bootstrap"] = {"value": estimate.value, "ci": [estimate.lo, estimate.hi]}
    body["paired"] = families
    body["crossover"] = {
        _pair_key(REFERENCE, other): _crossover(items[REFERENCE], items[other], settings)
        for other in baselines
    }
    by_split: dict[str, Any] = {}
    for run in runs:
        by_split[run.split] = {
            "conditions": {
                c: {
                    key: rate(sum(1 for i in run.items[c] if test(i)), len(run.items[c]), settings.level)
                    for key, test in _SPLIT_RATES
                }
                for c in conditions
            },
            "paired_accuracy": {
                _pair_key(REFERENCE, other): _discordant(
                    run.items[REFERENCE], run.items[other], lambda i: i.right
                )
                for other in baselines
            },
        }
    body["by_split"] = by_split
    body["errors"] = _error_rows(items)
    return body


def _discordant(
    first: Sequence[Item], second: Sequence[Item], indicator: Callable[[Item], bool]
) -> dict[str, Any]:
    a = {item.key: item for item in first}
    b = {item.key: item for item in second}
    keys = a.keys() & b.keys()
    bb = sum(1 for key in keys if indicator(a[key]) and not indicator(b[key]))
    cc = sum(1 for key in keys if not indicator(a[key]) and indicator(b[key]))
    return {
        "n": len(keys),
        "b": bb,
        "c": cc,
        "exact_p": stats.mcnemar_exact(bb, cc),
        "midp": stats.mcnemar_midp(bb, cc),
    }


# --------------------------------------------------------------------------------------------------
# The held-out re-analysis
# --------------------------------------------------------------------------------------------------


def p_text(p: float) -> str:
    """A p-value for a sentence: three decimals, or two significant digits below 0.001."""
    if p >= 0.001:
        return f"{p:.3f}"
    mantissa, exponent = f"{p:.1e}".split("e")
    return f"{mantissa}e{int(exponent)}"


def _methods(settings: Settings) -> dict[str, str]:
    return {
        "single_rate": "clopper-pearson",
        "published_ci": "the scorer's interval as docs/evals.md publishes it: a percentile bootstrap over letters, "
        "a Wilson interval over letters at a rate of 0 or 1",
        "paired_one_read": "exact McNemar (two-sided) on the discordant pairs, mid-p beside it; Bonett-Price interval",
        "paired_clustered": f"sign-flip test over letter clusters (exact up to {settings.signflip_exact_max} non-zero "
        f"clusters, else {settings.signflip_draws} seeded draws); paired cluster bootstrap, {settings.resamples} "
        "resamples, percentile interval",
        "multiplicity": "Holm within each family",
        "verdict": f"clear: the Holm-adjusted exact p and the Holm-adjusted cluster sign-flip p both below "
        f"{settings.alpha}, and the Bonett-Price interval excludes 0; suggestive: the unadjusted mid-p below "
        f"{settings.alpha}; else no clear difference",
        "harmful": "late or missed",
        "tiers": "please_check: low confidence, Please check, or found without a date; second_look: medium "
        "confidence; none: no flag, or missed (a missed deadline shows nothing, so it counts among the deadlines "
        "without a flag)",
        "selective_reads": "one read: every item once; over repeated reads, read 1's items, and each wrong date "
        "counted once (caught: flagged Please check in every read in which it was wrong)",
        "mean_over_reads": "cluster bootstrap, percentile interval; Clopper-Pearson over the clusters when every "
        "resample is equal",
        "aurc": "risk-coverage from the most confident tier down, errors spread evenly within a tier",
        "loss": "per 100 scored items: early + r * harmful",
        "crossover": f"r at which the losses are equal, when they cross; letter-cluster bootstrap, "
        f"{settings.crossover_resamples} resamples: the share of each outcome (a lower then b, b lower then a, a "
        "lower at every r, b lower at every r, identical), and the percentile interval of r over the resamples that "
        "cross the same way as the point estimate",
    }


def _points(value: float) -> str:
    return f"{value * 100:+.1f}"


def _findings(body: Mapping[str, Any]) -> dict[str, Any]:
    findings: dict[str, Any] = {
        "flags": {
            condition: {
                "caught": summary["selective"]["please_check"]["recall_wrong"]["k"],
                "wrong": summary["selective"]["please_check"]["recall_wrong"]["n"],
            }
            for condition, summary in body["conditions"].items()
        }
    }
    row = body["paired"]["accuracy"].get(_pair_key(REFERENCE, "llm_rules_text"))
    if row is not None:
        claim: dict[str, Any] = {
            key: row[key]
            for key in (
                "n",
                "b",
                "c",
                "diff",
                "exact_p",
                "holm_exact",
                "midp",
                "holm_midp",
                "bonett_price",
                "verdict",
            )
        }
        claim["text"] = (
            f"{row['b']} vs {row['c']} discordant, exact p {p_text(row['exact_p'])}, Holm-adjusted "
            f"{p_text(row['holm_exact'])} (mid-p {p_text(row['midp'])}, Holm-adjusted {p_text(row['holm_midp'])}): "
            f"{VERDICTS[row['verdict']]}"
        )
        published = row.get("published_bootstrap")
        if published is not None and published["value"] is not None and None not in published["ci"]:
            claim["published"] = published
            claim["published_text"] = (
                f"{_points(published['value'])} points, 95 % interval {_points(published['ci'][0])} to "
                f"{_points(published['ci'][1])}"
            )
        findings["rules_text_claim"] = claim
    crossover = body["crossover"].get(_pair_key(REFERENCE, "llm_rules_text"))
    if crossover is not None and crossover["outcome"] == "a_then_b":
        boot, shares = crossover["bootstrap"], crossover["shares"]
        findings["rules_text_crossover"] = {
            "r_star": crossover["r_star"],
            "lo": boot["lo"],
            "hi": boot["hi"],
            "shares": shares,
            "text": f"Ordnung's harm-weighted loss is the lower one until a late or missed date costs "
            f"{crossover['r_star']:.1f} early ones; in {_share(shares['a_then_b'])} of {boot['resamples']:,} "
            f"resamples of the letters the losses cross the same way (95 % of those crossings between "
            f"{boot['lo']:.1f} and {boot['hi']:.1f}), and in {_share(shares['a_lower'])} Ordnung's loss is the lower "
            "one whatever a harmful date costs",
        }
    return findings


def _share(value: float) -> str:
    return f"{value * 100:.0f} %"


def reanalyse(runs: Sequence[Run], *, date: str, settings: Settings | None = None) -> dict[str, Any]:
    """The held-out runs as recorded, pooled and re-analysed: labelled not pre-registered."""
    settings = settings or Settings()
    ordered = _sorted_runs(runs)
    model, _ = _check_single_read(ordered)
    body = single_read(ordered, settings)
    return {
        "schema": ANALYSIS_SCHEMA,
        "meta": {
            "kind": REANALYSIS_KIND,
            "date": date,
            "model": model,
            "pre_registered": False,
            "label": "not pre-registered",
            "note": "The held-out splits as recorded once, each with the code and prompts of its day, pooled and "
            "re-analysed with the final run's statistics after their results were known.",
            "splits": [run.split for run in ordered],
            "inputs": [run.input_record() for run in ordered],
            "settings": settings.to_dict(),
            "methods": _methods(settings),
        },
        **body,
        "findings": _findings(body),
    }


# --------------------------------------------------------------------------------------------------
# The pre-registered final run
# --------------------------------------------------------------------------------------------------


def default_prereg_analysis() -> dict[str, Any]:
    """The ``analysis`` section of the final run's pre-registration, as the evaluation plan sets it (§6)."""
    return {
        "schema": PREREG_SCHEMA,
        "model": MODEL,
        "primary": {"split": "holdout4", "reads": 3},
        "secondary": [{"split": "newkinds", "reads": 1}],
        "reference": REFERENCE,
        "baselines": ["llm_only", "llm_rules_text", "llm_rules_tool"],
        "noninferior_to": ["llm_rules_tool"],
        "seed": stats.SEED,
        "signflip": {"exact_max": stats.SIGNFLIP_EXACT_MAX, "draws": stats.SIGNFLIP_DRAWS},
        "bootstrap_resamples": stats.BOOTSTRAP_RESAMPLES,
        "crossover_resamples": CROSSOVER_RESAMPLES,
        "alpha": 0.05,
        "level": stats.CONFIDENCE_LEVEL,
        "noninferiority_margin": 0.05,
        "loss_ratios": list(LOSS_RATIOS),
        "pool_with": list(HELD_OUT_AS_RECORDED),
        "rules": dict(RULES),
        "min_reads": MIN_READS,
        "confirmatory": dict(CONFIRMATORY),
        "sensitivities": list(SENSITIVITIES),
        "exploratory": list(EXPLORATORY),
    }


@dataclass(frozen=True)
class Prereg:
    """The pre-registration's ``analysis`` section, checked."""

    model: str
    primary_split: str
    primary_reads: int
    secondary: tuple[tuple[str, int], ...]
    reference: str
    baselines: tuple[str, ...]
    noninferior_to: tuple[str, ...]
    pool_with: tuple[str, ...]
    settings: Settings
    min_reads: int = MIN_READS
    sensitivities: tuple[str, ...] = SENSITIVITIES
    exploratory: tuple[str, ...] = EXPLORATORY


def parse_prereg(data: Mapping[str, Any]) -> Prereg:
    """The ``analysis`` section of a pre-registration; ``AnalysisError`` when a field is missing or malformed, or names
    a rule the code does not implement (no field has a default: what the analysis does is what the pre-registration
    says)."""
    section = data.get("analysis")
    if not isinstance(section, Mapping):
        raise AnalysisError("the pre-registration has no analysis section")
    expected = default_prereg_analysis()
    missing = sorted(set(expected) - set(section))
    if missing:
        raise AnalysisError(f"the pre-registration's analysis section lacks {', '.join(missing)}")
    if section["schema"] != PREREG_SCHEMA:
        raise AnalysisError(
            f"the pre-registration's analysis schema is {section['schema']!r}, not {PREREG_SCHEMA!r}"
        )
    try:
        primary = section["primary"]
        secondary = tuple((str(s["split"]), int(s["reads"])) for s in section["secondary"])
        prereg = Prereg(
            model=str(section["model"]),
            primary_split=str(primary["split"]),
            primary_reads=int(primary["reads"]),
            secondary=secondary,
            reference=str(section["reference"]),
            baselines=tuple(str(b) for b in section["baselines"]),
            noninferior_to=tuple(str(b) for b in section["noninferior_to"]),
            pool_with=tuple(str(name) for name in section["pool_with"]),
            settings=Settings(
                seed=int(section["seed"]),
                resamples=int(section["bootstrap_resamples"]),
                signflip_draws=int(section["signflip"]["draws"]),
                signflip_exact_max=int(section["signflip"]["exact_max"]),
                crossover_resamples=int(section["crossover_resamples"]),
                level=float(section["level"]),
                alpha=float(section["alpha"]),
                noninferiority_margin=float(section["noninferiority_margin"]),
                loss_ratios=tuple(float(r) for r in section["loss_ratios"]),
            ),
            min_reads=int(section["min_reads"]),
            sensitivities=tuple(str(name) for name in section["sensitivities"]),
            exploratory=tuple(str(name) for name in section["exploratory"]),
        )
        rules = dict(section["rules"])
        confirmatory = dict(section["confirmatory"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalysisError(f"the pre-registration's analysis section is malformed: {exc}") from exc
    if prereg.reference != REFERENCE:
        raise AnalysisError(f"the analysis compares Ordnung with the baselines, not {prereg.reference!r}")
    if prereg.primary_reads < 1 or any(reads != 1 for _, reads in prereg.secondary):
        raise AnalysisError("the primary split is read at least once and each secondary split once")
    if not set(prereg.noninferior_to) <= set(prereg.baselines):
        raise AnalysisError("a non-inferiority comparison names a condition that is not a baseline")
    differing = sorted(key for key in rules.keys() | RULES.keys() if rules.get(key) != RULES.get(key))
    if differing:
        raise AnalysisError(
            f"the pre-registration's rules differ from the ones the analysis implements in {', '.join(differing)}"
        )
    if not 1 <= prereg.min_reads <= prereg.primary_reads:
        raise AnalysisError(
            f"min_reads {prereg.min_reads} is not between 1 and the {prereg.primary_reads} reads"
        )
    if confirmatory != CONFIRMATORY or CONFIRMATORY["baseline"] not in prereg.baselines:
        raise AnalysisError(f"the confirmatory decision the analysis implements is {CONFIRMATORY}")
    for name, known in (("sensitivities", SENSITIVITIES), ("exploratory", EXPLORATORY)):
        unknown = [value for value in getattr(prereg, name) if value not in known]
        if unknown:
            raise AnalysisError(
                f"the analysis has no {name} {', '.join(unknown)} (it knows {', '.join(known)})"
            )
    return prereg


# --------------------------------------------------------------------------------------------------
# The frozen inputs and the deviations recorded at the time
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Frozen:
    """What the pre-registration pins besides its ``analysis`` section: the reads are checked against it."""

    planned_day: str
    valid_until: str
    fingerprints: Mapping[str, str]
    cli_versions: tuple[str, ...]
    served_models: tuple[str, ...]
    manifest_sha256: str
    deviations_file: str


def _iso_day(value: Any) -> str:
    """``value`` when it is a day ``YYYY-MM-DD``; ``ValueError`` otherwise."""
    text = str(value)
    if calendar_date.fromisoformat(text).isoformat() != text:
        raise ValueError(f"{text!r} is not a day YYYY-MM-DD")
    return text


def _kinds_table(raw: Any) -> dict[str, str]:
    """The pre-registration's table of deviation kinds: ``{kind: consequence}``, ``{kind: {"consequence": …}}`` or a
    list of ``{"kind", "consequence"}``."""
    rows = raw.items() if isinstance(raw, Mapping) else ((row["kind"], row) for row in raw)
    table = {}
    for kind, value in rows:
        consequence = value.get("consequence") if isinstance(value, Mapping) else value
        if not isinstance(consequence, str):
            raise TypeError(f"the consequence of {kind!r} is not a text")
        table[str(kind)] = consequence
    return table


def parse_frozen(data: Mapping[str, Any]) -> Frozen:
    """The frozen inputs of a pre-registration; ``AnalysisError`` when one is missing or malformed, or when its table
    of deviation kinds is not the one the analysis applies (:data:`DEVIATION_CONSEQUENCES`)."""
    try:
        registered, frozen, dataset = data["registered"], data["frozen"], data["data"]
        found = Frozen(
            planned_day=_iso_day(registered["planned_day"]),
            valid_until=_iso_day(registered["valid_until"]),
            fingerprints={str(c): str(value) for c, value in frozen["fingerprints"].items()},
            cli_versions=tuple(str(value) for value in frozen["cli_versions"]),
            served_models=tuple(str(value) for value in frozen["served_models"]),
            manifest_sha256=str(dataset["manifest_sha256"]),
            deviations_file=str(data["deviations_file"]),
        )
        table = _kinds_table(data["deviation_kinds"])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise AnalysisError(
            f"the pre-registration lacks a frozen input the reads are checked against: {exc}"
        ) from exc
    if found.valid_until < found.planned_day:
        raise AnalysisError("the pre-registration's window ends before it starts")
    differing = sorted(
        kind
        for kind in table.keys() | DEVIATION_CONSEQUENCES.keys()
        if table.get(kind) != DEVIATION_CONSEQUENCES.get(kind)
    )
    if differing:
        raise AnalysisError(
            "the pre-registration's table of deviation kinds is not the one the analysis applies "
            f"(it differs in {', '.join(differing)})"
        )
    return found


@dataclass(frozen=True)
class Deviation:
    """One entry of the deviations file, recorded at the time it happened."""

    id: str
    kind: str
    step: str
    #: What it applies to (its ``applies_to``): a read (``split``, ``repeat``) and its units (``entries``).
    split: str | None
    repeat: int | None
    entries: frozenset[str]
    #: ``label_error``: (entry id, item index, the corrected date).
    items: tuple[tuple[str, int, str], ...]
    #: ``retake``: (entry id, condition, the first attempt's outcome).
    first_attempt: tuple[tuple[str, str, str], ...]
    #: Its id, kind, step, times, issue comment and checkpoint, for the output (never its text).
    record: Mapping[str, Any]

    @property
    def effect(self) -> str:
        return DEVIATION_EFFECTS[self.kind]

    def names(self, split: str, repeat: int) -> bool:
        """Whether it applies to this read."""
        return self.split == split and self.repeat == repeat


def _deviation_problems(entry: Mapping[str, Any]) -> list[str]:
    """Why an entry does not count as a deviation recorded at the time (none: it counts)."""
    problems = []
    kind = entry.get("kind")
    if kind not in DEVIATION_CONSEQUENCES:
        problems.append(f"kind {kind!r} is not in the registered table")
    elif entry.get("consequence") != DEVIATION_CONSEQUENCES[str(kind)]:
        problems.append(f"its consequence is not the one registered for {kind}")
    if not isinstance(entry.get("step"), str) or not entry["step"]:
        problems.append("no step")
    if not _COMMENT_URL.fullmatch(str(entry.get("issue_comment_url") or "")):
        problems.append("no comment on the pre-registration issue (issue_comment_url)")
    try:
        datetime.fromisoformat(str(entry.get("created_at")).replace("Z", "+00:00"))
    except ValueError:
        problems.append("no time it was recorded (created_at)")
    if not _COMMIT.fullmatch(str(entry.get("checkpoint_sha") or "")):
        problems.append("no checkpoint commit that pushed it (checkpoint_sha)")
    applies = entry.get("applies_to", {})
    try:
        _applies_to(applies)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        problems.append(f"applies_to is malformed ({exc})")
    return problems


def _applies_to(applies: Any) -> tuple[Any, ...]:
    """``applies_to`` read: (split, repeat, entries, items, first_attempt); ``ValueError`` for anything malformed."""
    if not isinstance(applies, Mapping):
        raise TypeError("not an object")
    split = applies.get("split")
    if split is not None and not isinstance(split, str):
        raise TypeError("split is not a text")
    repeat = applies.get("repeat")
    if repeat is not None and (isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1):
        raise ValueError("repeat is not a read number")
    entries = applies.get("entries") or []
    if not all(isinstance(entry, str) for entry in entries):
        raise TypeError("entries are not ids")
    items = tuple(
        (str(item["entry_id"]), int(item["item"]), _iso_day(item["date"]))
        for item in applies.get("items") or []
    )
    first = tuple(
        (str(row["entry_id"]), str(row["condition"]), str(row["outcome"]))
        for row in applies.get("first_attempt") or []
    )
    for _, condition, outcome in first:
        if condition not in CONDITIONS or outcome not in FIRST_ATTEMPT_OUTCOMES:
            raise ValueError(f"a first attempt of {condition!r} with outcome {outcome!r}")
    return split, repeat, frozenset(entries), items, first


def load_deviations(path: Path) -> list[Deviation]:
    """The deviations file; ``AnalysisError`` naming an entry that was not recorded at the time (no issue comment, no
    time, no checkpoint commit), is not of a registered kind or has another consequence than its kind's."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"the deviations file cannot be read: {exc}") from exc
    if not isinstance(raw, list):
        raise AnalysisError(f"{path.name} is not a list of deviations")
    found: list[Deviation] = []
    for position, entry in enumerate(raw, start=1):
        ident = entry.get("id") if isinstance(entry, Mapping) else None
        label = f"deviation {ident or f'#{position}'}"
        if not isinstance(entry, Mapping) or not isinstance(ident, str) or not ident:
            raise AnalysisError(f"{label} is not an entry with an id")
        problems = _deviation_problems(entry)
        if problems:
            raise AnalysisError(
                f"{label}: {'; '.join(problems)}. A deviation counts only as recorded at the time"
            )
        if any(known.id == ident for known in found):
            raise AnalysisError(f"{label} is in the file twice")
        split, repeat, entries, items, first = _applies_to(entry.get("applies_to", {}))
        record = {
            key: entry.get(key)
            for key in (
                "id",
                "kind",
                "step",
                "consequence",
                "at",
                "created_at",
                "issue_comment_url",
                "checkpoint_sha",
            )
        }
        found.append(
            Deviation(
                ident, str(entry["kind"]), str(entry["step"]), split, repeat, entries, items, first, record
            )
        )
    return found


@dataclass
class Checked:
    """What :func:`check_frozen` found: the reads the analysis uses, and what it left out and why."""

    runs: list[Run]
    #: (split, read, entry id) → (the unit's day, its claude version).
    units: dict[tuple[str, int, str], tuple[str | None, str | None]]
    #: (split, read) → the deviations that say why that read is not analysed.
    missing: dict[tuple[str, int], dict[str, Any]]
    left_out: list[tuple[Run, dict[str, Any]]] = field(default_factory=list)
    units_excluded: list[dict[str, Any]] = field(default_factory=list)
    unanswered: list[dict[str, Any]] = field(default_factory=list)
    cli_versions: dict[str, list[str]] = field(default_factory=dict)
    deviations: list[Deviation] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


def _run_label(run: Run) -> str:
    return run.name or f"{run.split} read {run.repeat}"


def _entries_of(run: Run) -> list[Mapping[str, Any]]:
    return [entry for entry in run.results.get("entries") or [] if isinstance(entry, Mapping)]


def _without(run: Run, entries: Collection[str]) -> Run:
    """The run without these letters (every condition)."""
    if not entries:
        return run
    return replace(
        run,
        items={c: tuple(i for i in items if i.entry_id not in entries) for c, items in run.items.items()},
        letters={
            c: tuple(x for x in letters if x.entry_id not in entries) for c, letters in run.letters.items()
        },
    )


def _fingerprint_mismatch(run: Run, frozen: Frozen, conditions: Sequence[str]) -> list[str]:
    """The conditions whose fingerprint (the run's, or any prediction's) is not the registered one."""
    registered = frozen.fingerprints
    found = run.meta.get("fingerprints")
    if not isinstance(found, Mapping):
        found = {}
    bad = {c for c in conditions if found.get(c) != registered.get(c)}
    for entry in _entries_of(run):
        for condition in conditions:
            prediction = ((entry.get("conditions") or {}).get(condition) or {}).get("prediction") or {}
            made_with = prediction.get("fingerprint")
            if made_with and made_with != registered.get(condition):
                bad.add(condition)
    return sorted(bad)


def check_frozen(
    prereg: Prereg,
    frozen: Frozen,
    runs: Sequence[Run],
    deviations: Sequence[Deviation],
    *,
    day_index: Mapping[str, Any],
    ledger: Sequence[Mapping[str, Any]],
) -> Checked:
    """Every read against the pre-registration's frozen inputs; each mismatch must be named by a deviation recorded at
    the time, and then has its kind's consequence. ``AnalysisError`` lists every mismatch no deviation names."""
    retired = [d.id for d in deviations if d.effect == RETIRED]
    if retired:
        raise AnalysisError(
            f"the final set was retired ({', '.join(retired)}): its recorded units are published as they are, and "
            "it is not analysed as the final run"
        )
    wanted = (prereg.reference, *prereg.baselines)
    analysed = {prereg.primary_split, *(split for split, _ in prereg.secondary)}
    checked = Checked(runs=[], units={}, missing={}, deviations=list(deviations))
    unnamed: list[str] = []
    excluded: list[dict[str, Any]] = []
    lines_checked = 0
    for run in runs:
        label = _run_label(run)
        if run.model != prereg.model:
            raise AnalysisError(f"{label}: model {run.model!r}, the pre-registration names {prereg.model!r}")
        if run.split not in analysed:
            raise AnalysisError(f"{label}: the pre-registration names no {run.split!r} split")
        if run.meta.get("backend") != "live":
            raise AnalysisError(
                f"{label}: not a live recording (backend {run.meta.get('backend')!r}); the final run is analysed as "
                "recorded"
            )
        # (mismatch, entry id or None, the condition or None, what differs)
        found: list[tuple[str, str | None, str | None, str]] = []
        bad = _fingerprint_mismatch(run, frozen, wanted)
        if bad:
            found.append(
                (
                    "fingerprint",
                    None,
                    None,
                    f"the code or prompts of {', '.join(bad)} are not the registered ones",
                )
            )
        ids = {str(entry.get("id")) for entry in _entries_of(run)}
        lines = [
            line
            for line in ledger
            if int(line.get("repeat") or 1) == run.repeat and ids.intersection(line.get("docs") or ())
        ]
        served = {str(line["served_model"]) for line in lines if line.get("served_model")}
        if not served:
            raise AnalysisError(f"{label}: no ledger line names the model that answered its calls")
        lines_checked += len(lines)
        if not served <= set(frozen.served_models):
            found.append(
                ("model", None, None, "a call was answered by a model the pre-registration does not name")
            )
        if (run.meta.get("dataset") or {}).get("manifest_sha256") != frozen.manifest_sha256:
            found.append(("manifest_mismatch", None, None, "its letters are not the registered build"))
        dirty = run.meta.get("dirty")
        if not isinstance(dirty, list) or any(not _DEVIATIONS_PATH.fullmatch(str(path)) for path in dirty):
            # the deviations file, appended to at the time and committed with the next checkpoint, is no code
            found.append(("dirty_tree", None, None, "recorded from a tree with changes"))
        index = (day_index.get(run.split) or {}).get(f"r{run.repeat}") or {}
        versions = set()
        for entry in sorted(_entries_of(run), key=lambda e: str(e.get("id"))):
            entry_id = str(entry.get("id"))
            unit = index.get(entry_id)
            if not isinstance(unit, Mapping) or not unit.get("day") or not unit.get("cli"):
                raise AnalysisError(f"{label}: {entry_id} has no day and claude version in the day index")
            day, cli = str(unit["day"]), str(unit["cli"])
            told = entry.get("simulated_today") or entry.get("today")
            if told and str(told) != day:
                raise AnalysisError(
                    f"{label}: {entry_id} was told {told}, the day index records {day}: one unit has one day"
                )
            checked.units[(run.split, run.repeat, entry_id)] = (day, cli)
            versions.add(cli)
            if not frozen.planned_day <= day <= frozen.valid_until:
                found.append(
                    (
                        "day_outside_window",
                        entry_id,
                        None,
                        f"recorded on {day}, outside {frozen.planned_day} to {frozen.valid_until}",
                    )
                )
            if cli not in frozen.cli_versions:
                found.append(("cli_version", entry_id, None, f"recorded with claude {cli}"))
            for condition in wanted:
                if any(
                    letter.entry_id == entry_id and letter.error for letter in run.letters.get(condition, ())
                ):
                    found.append(("unanswered", entry_id, condition, f"{condition} has no answer"))
        checked.cli_versions[f"{run.split}/r{run.repeat}"] = sorted(versions)
        leave: dict[str, tuple[str, list[str]]] = {}  # mismatch → (its effect, the deviations naming it)
        # what a read that stays brings: its excluded units and its letters left without an answer
        units_out: dict[str, dict[str, Any]] = {}
        unanswered: list[dict[str, Any]] = []
        for mismatch, unit_id, which, detail in found:
            names = [
                d
                for d in deviations
                if d.kind in _EXCUSED_BY[mismatch]
                and d.names(run.split, run.repeat)
                and (unit_id is None or unit_id in d.entries or (mismatch == "cli_version" and not d.entries))
            ]
            if not names:
                unit = f" {unit_id}" if unit_id else ""
                unnamed.append(
                    f"{label}: {mismatch}{unit} ({detail}): no deviation recorded at the time names it"
                )
                continue
            ids_named = sorted(d.id for d in names)
            effect = DEVIATION_EFFECTS[names[0].kind]
            if effect in (INVALID, EXCLUDE_READ):
                leave[mismatch] = (effect, sorted({*leave.get(mismatch, (effect, []))[1], *ids_named}))
            elif effect == EXCLUDE_UNIT and unit_id is not None:
                row = units_out.setdefault(
                    unit_id,
                    {
                        "split": run.split,
                        "repeat": run.repeat,
                        "entry_id": unit_id,
                        "day": checked.units[(run.split, run.repeat, unit_id)][0],
                        "deviations": [],
                    },
                )
                row["deviations"] = sorted({*row["deviations"], *ids_named})
            elif mismatch == "unanswered":
                unanswered.append(
                    {
                        "split": run.split,
                        "read": run.repeat,
                        "entry_id": unit_id,
                        "condition": which,
                        "deviations": ids_named,
                    }
                )
        if leave:
            effects = {effect for effect, _ in leave.values()}
            checked.left_out.append(
                (
                    run,
                    {
                        "split": run.split,
                        "repeat": run.repeat,
                        "file": run.name,
                        "sha256": run.sha256,
                        "mismatches": sorted(leave),
                        "deviations": sorted({ident for _, ids in leave.values() for ident in ids}),
                        "effect": INVALID if INVALID in effects else EXCLUDE_READ,
                    },
                )
            )
        else:
            checked.runs.append(run)
            excluded.extend(units_out.values())
            checked.unanswered.extend(unanswered)
    if unnamed:
        raise AnalysisError("; ".join(unnamed))
    checked.units_excluded = sorted(excluded, key=lambda row: (row["split"], row["repeat"], row["entry_id"]))
    gone: dict[str, set[str]] = defaultdict(set)
    for row in checked.units_excluded:
        gone[row["split"]].add(row["entry_id"])
    checked.runs = [_without(run, gone[run.split]) for run in checked.runs]
    checked.unanswered = [row for row in checked.unanswered if row["entry_id"] not in gone[row["split"]]]
    present = {(run.split, run.repeat) for run in checked.runs}
    for split, reads in ((prereg.primary_split, prereg.primary_reads), *prereg.secondary):
        for read in range(1, reads + 1):
            if (split, read) in present:
                continue
            names = [
                d for d in deviations if d.effect in (INVALID, EXCLUDE_READ, NOT_RUN) and d.names(split, read)
            ]
            if names:
                checked.missing[(split, read)] = {
                    "read": read,
                    "kinds": sorted({d.kind for d in names}),
                    "deviations": sorted(d.id for d in names),
                }
    checked.evidence["ledger"] = {"lines": lines_checked}
    checked.evidence["day_index"] = {"units": len(checked.units)}
    return checked


def _read_day_index(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise AnalysisError(f"no day index {path.name}: the final run's units have no recorded day")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"the day index {path.name} is not JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise AnalysisError(f"the day index {path.name} is not an object")
    return data


def _read_ledger(path: Path) -> list[Mapping[str, Any]]:
    if not path.is_file():
        return []
    lines = []
    for text in path.read_text(encoding="utf-8").splitlines():
        if text.strip():
            line = json.loads(text)
            if isinstance(line, Mapping):
                lines.append(line)
    return lines


def _conventions(path: Path, registered: str) -> dict[tuple[str, int], frozenset[str]]:
    """Per (entry id, item index): the dates the other reading of a disputed convention gives (the manifest's
    ``convention_alternatives``); ``AnalysisError`` unless the manifest is the registered one."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AnalysisError(f"the dataset's manifest cannot be read: {exc}") from exc
    if hashlib.sha256(raw).hexdigest() != registered:
        raise AnalysisError("the dataset's manifest is not the one the pre-registration pins")
    found = {}
    for entry in json.loads(raw).get("entries") or []:
        for index, item in enumerate((entry.get("truth") or {}).get("items") or []):
            dates = item.get("convention_alternatives") or []
            if dates:
                found[(str(entry["id"]), index)] = frozenset(str(day) for day in dates)
    return found


# --------------------------------------------------------------------------------------------------
# The pre-registered final run
# --------------------------------------------------------------------------------------------------


def _assign_reads(
    prereg: Prereg, runs: Sequence[Run], missing: Mapping[tuple[str, int], Any] | None = None
) -> tuple[list[Run], dict[str, Run]]:
    """The primary reads in order and the secondary runs by split; ``AnalysisError`` for anything that does not fit.
    A read may be missing only when a deviation recorded at the time says why (``missing``), and never read 1."""
    missing = missing or {}
    wanted = (prereg.reference, *prereg.baselines)
    primary: dict[int, Run] = {}
    secondary: dict[str, Run] = {}
    secondary_splits = {split for split, _ in prereg.secondary}
    for run in runs:
        label = _run_label(run)
        if run.model != prereg.model:
            raise AnalysisError(f"{label}: model {run.model!r}, the pre-registration names {prereg.model!r}")
        if run.meta.get("partial"):
            raise AnalysisError(f"{label}: a filtered run does not cover its split")
        absent = [c for c in wanted if c not in run.conditions]
        if absent:
            raise AnalysisError(f"{label}: no answers of {', '.join(absent)}")
        if run.split == prereg.primary_split:
            if run.repeat in primary:
                raise AnalysisError(f"read {run.repeat} of {run.split} was given twice")
            if not 1 <= run.repeat <= prereg.primary_reads:
                raise AnalysisError(f"{label}: read {run.repeat} is not one the pre-registration names")
            primary[run.repeat] = run
        elif run.split in secondary_splits:
            if run.split in secondary:
                raise AnalysisError(f"{run.split} was given twice")
            secondary[run.split] = run
        else:
            raise AnalysisError(f"{label}: the pre-registration names no {run.split!r} split")
    if 1 not in primary:
        raise AnalysisError(
            f"{prereg.primary_split} read 1 is missing: the final run's analysis starts from it"
        )
    for read in range(2, prereg.primary_reads + 1):
        if read not in primary and (prereg.primary_split, read) not in missing:
            raise AnalysisError(
                f"{prereg.primary_split} read {read} is missing and no deviation recorded at the time says why"
            )
    for split, _ in prereg.secondary:
        if split not in secondary and (split, 1) not in missing:
            raise AnalysisError(f"the {split} run is missing and no deviation recorded at the time says why")
    reads = [primary[read] for read in sorted(primary)]
    first = {c: sorted(item.key for item in reads[0].items[c]) for c in wanted}
    if any(first[c] != first[prereg.reference] for c in wanted):
        raise AnalysisError(f"the conditions of {prereg.primary_split} read 1 do not hold the same items")
    letters = sorted(letter.entry_id for letter in reads[0].letters[prereg.reference])
    for run in reads[1:]:
        same = all(
            sorted(item.key for item in run.items[c]) == first[c] for c in wanted
        ) and letters == sorted(letter.entry_id for letter in run.letters[prereg.reference])
        if not same:
            raise AnalysisError(f"the {prereg.primary_split} reads do not hold the same items")
    return reads, secondary


Rows = Mapping[tuple[str, str, int], Sequence[Item]]


def _mean_clusters(rows: Rows, test: Callable[[Item], bool]) -> list[tuple[float, float]]:
    """Per cluster: (hits over every read, items × reads). With the same reads for every item, the ratio is the mean
    over items of the per-item mean over reads; counted in integers, so the sums are exact on every Python."""
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for reads in rows.values():
        row = sums[reads[0].cluster]
        row[0] += sum(1 for item in reads if test(item))
        row[1] += len(reads)
    return [(float(row[0]), float(row[1])) for _, row in sorted(sums.items())]


def _cluster_sums(ours: Rows, theirs: Rows, test: Callable[[Item], bool]) -> list[list[int]]:
    """Per cluster, in cluster order: [our hits, their hits, item-reads], over every read."""
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for key, reads in ours.items():
        row = sums[reads[0].cluster]
        row[0] += sum(1 for item in reads if test(item))
        row[1] += sum(1 for item in theirs[key] if test(item))
        row[2] += len(reads)
    return [row for _, row in sorted(sums.items())]


def _family_pair(
    ours: Rows, theirs: Rows, test: Callable[[Item], bool], settings: Settings
) -> dict[str, Any]:
    """F1 / F2: the per-item mean over reads, ours minus theirs; sign-flip test over clusters, paired bootstrap.

    Each cluster is counted in hits over every read (the per-item means times the number of reads), which changes
    neither the test (a common scale) nor the rates, and keeps every sum an exact integer."""
    clusters = _cluster_sums(ours, theirs, test)
    item_reads = sum(row[2] for row in clusters)
    flip = stats.cluster_signflip(
        [row[0] - row[1] for row in clusters],
        exact_max=settings.signflip_exact_max,
        draws=settings.signflip_draws,
        seed=settings.seed,
    )
    boot = stats.paired_cluster_bootstrap(
        [(float(row[0]), float(row[1]), float(row[2])) for row in clusters],
        resamples=settings.resamples,
        seed=settings.seed,
        level=settings.level,
    )
    return {
        "n": len(ours),
        "first": sum(row[0] for row in clusters) / item_reads,
        "second": sum(row[1] for row in clusters) / item_reads,
        "diff": sum(row[0] - row[1] for row in clusters) / item_reads,
        "signflip": flip.to_dict(),
        "bootstrap": boot.to_dict(),
    }


def _drawn_flips(pairs: Sequence[tuple[int, int]], draws: int, seed: int) -> Iterator[tuple[int, int]]:
    """For ``draws`` random sign patterns (``random.Random(seed).getrandbits``, bit b for cluster b): the summed
    differences and item-reads of the flipped clusters, by 8-bit tables."""
    chunks = []
    for start in range(0, len(pairs), 8):
        part = pairs[start : start + 8]
        masks = range(1 << len(part))
        chunks.append(
            (
                start,
                [sum(d for bit, (d, _) in enumerate(part) if mask >> bit & 1) for mask in masks],
                [sum(n for bit, (_, n) in enumerate(part) if mask >> bit & 1) for mask in masks],
            )
        )
    rng = random.Random(seed)
    width = len(pairs)
    for _ in range(draws):
        mask = rng.getrandbits(width)
        flipped_d = flipped_n = 0
        for start, d_table, n_table in chunks:
            byte = (mask >> start) & 0xFF
            flipped_d += d_table[byte]
            flipped_n += n_table[byte]
        yield flipped_d, flipped_n


def _order_statistic(ordered: Sequence[tuple[Fraction, int]], rank: int) -> Fraction:
    """The ``rank``-th value (1-based) of values given with their counts, in order."""
    seen = 0
    for value, count in ordered:
        seen += count
        if seen >= rank:
            return value
    raise ValueError("rank beyond the values")


def signflip_interval(
    clusters: Sequence[tuple[int, int]], *, level: float, exact_max: int, draws: int, seed: int
) -> dict[str, Any]:
    """The interval of a paired difference δ (per item-read) by inverting the two-sided cluster sign-flip test.

    ``clusters`` gives per cluster the difference of hits (first minus second, over every read) and its item-reads.
    δ is kept when the sign-flip test of the cluster totals centred on δ (``d − δ·n``) does not reject at
    ``1 − level``. A sign pattern that flips the clusters F counts against δ unless δ lies between F's own
    difference per item-read and the rest's; both sides hold the estimate, so the p-value falls away from it on each
    side and the kept set is an interval whose ends are order statistics of those differences (exact fractions).
    Every pattern is counted up to ``exact_max`` clusters; beyond, ``draws`` patterns are drawn with ``seed`` and
    ``p = (hits + 1) / (draws + 1)``, as :func:`evals.stats.cluster_signflip` does. Clipped to [−1, 1]: a test that
    cannot reject keeps all of it."""
    pairs = [(int(d), int(n)) for d, n in clusters if n > 0]
    exact = len(pairs) <= exact_max
    result: dict[str, Any] = {
        "lo": None,
        "hi": None,
        "estimate": None,
        "clusters": len(pairs),
        "method": "exact" if exact else "monte-carlo",
        "draws": None if exact else draws,
        "seed": None if exact else seed,
        "level": level,
    }
    if not pairs:
        return result
    total_d, total_n = sum(d for d, _ in pairs), sum(n for _, n in pairs)
    alpha = 1 - Fraction(level).limit_denominator(stats.MAX_DENOMINATOR)
    counts: Counter[tuple[int, int]]
    if exact:
        counts = Counter({(0, 0): 1})
        for d, n in pairs:
            step: Counter[tuple[int, int]] = Counter()
            for (a, b), count in counts.items():
                step[(a, b)] += count
                step[(a + d, b + n)] += count
            counts = step
        need = math.ceil(alpha * 2 ** len(pairs))
    else:
        counts = Counter(_drawn_flips(pairs, draws, seed))
        need = math.ceil(alpha * (draws + 1) - 1)
    # flipping nothing or everything never counts against any δ
    rank = need - counts.pop((0, 0), 0) - counts.pop((total_d, total_n), 0)
    lo, hi = Fraction(-1), Fraction(1)
    if rank > 0:
        lows, highs = [], []
        for (a, b), count in counts.items():
            flipped, rest = Fraction(a, b), Fraction(total_d - a, total_n - b)
            lows.append((min(flipped, rest), count))
            highs.append((max(flipped, rest), count))
        lo = max(lo, _order_statistic(sorted(lows), rank))
        hi = min(hi, _order_statistic(sorted(highs, reverse=True), rank))
    result.update(lo=float(lo), hi=float(hi), estimate=total_d / total_n)
    return result


def noninferiority_decision(lo: float | None, hi: float | None, margin: float, baseline: str) -> str:
    """The pre-registered rule against a baseline Ordnung must not trail by more than ``margin``: the baseline is
    higher only when the whole interval is below 0 (an upper end of exactly 0 is not); else not worse by more than
    the margin when the lower end is above −margin; else we cannot tell."""
    if hi is not None and hi < 0:
        return "agent_higher" if baseline == TOOL_CONDITION else "baseline_higher"
    if lo is not None and lo > -margin:
        return "non_inferior"
    return "cannot_tell"


def _unstable(reads: Sequence[Item]) -> bool:
    return any(item.predicted != reads[0].predicted for item in reads[1:])


def _stability_pair(ours: Rows, theirs: Rows, settings: Settings) -> dict[str, Any]:
    """F3: unstable items, ours minus theirs: mid-p McNemar (exact beside it) and Bonett–Price."""
    keys = sorted(ours)
    b = sum(1 for key in keys if _unstable(ours[key]) and not _unstable(theirs[key]))
    c = sum(1 for key in keys if not _unstable(ours[key]) and _unstable(theirs[key]))
    n = len(keys)
    return {
        "n": n,
        "b": b,
        "c": c,
        "diff": (b - c) / n if n else None,
        "midp": stats.mcnemar_midp(b, c),
        "exact_p": stats.mcnemar_exact(b, c),
        "bonett_price": list(stats.bonett_price(b, c, n, level=settings.level)) if n else [None, None],
    }


def _reading_agreement(rows: Rows) -> dict[str, int]:
    """Over the items read in every read: the same reading each time; a changed reading the engine absorbed (same
    date); and the same reading with another date (which only something besides the reading can cause)."""
    read = [reads for reads in rows.values() if all(item.reading is not None for item in reads)]
    same = [all(item.reading == reads[0].reading for item in reads) for reads in read]
    return {
        "items": len(read),
        "same_reading": sum(same),
        "absorbed": sum(
            1 for reads, alike in zip(read, same, strict=True) if not alike and not _unstable(reads)
        ),
        "same_reading_other_date": sum(
            1 for reads, alike in zip(read, same, strict=True) if alike and _unstable(reads)
        ),
    }


def _tool_use(letters: Sequence[Sequence[Letter]]) -> dict[str, int] | None:
    """Letters where the agent asked a date tool in every read, in some, in none (``None`` without tools)."""
    if any(letter.date_tool_calls is None for reads in letters for letter in reads):
        return None
    every = sum(1 for reads in letters if all(letter.date_tool_calls for letter in reads))
    none = sum(1 for reads in letters if not any(letter.date_tool_calls for letter in reads))
    return {
        "letters": len(letters),
        "date_tool_every_read": every,
        "date_tool_some_reads": len(letters) - every - none,
        "date_tool_no_read": none,
    }


@dataclass(frozen=True)
class _Context:
    """What the final run's analysis knows besides the reads: each unit's day and claude version, the deviations and
    the disputed conventions' other dates."""

    units: Mapping[tuple[str, int, str], tuple[str | None, str | None]] = field(default_factory=dict)
    deviations: Sequence[Deviation] = ()
    conventions: Mapping[tuple[str, int], frozenset[str]] = field(default_factory=dict)
    unanswered: Sequence[Mapping[str, Any]] = ()


def _rows(
    reads: Sequence[Run], conditions: Sequence[str]
) -> dict[str, dict[tuple[str, str, int], list[Item]]]:
    """Per condition and item: its outcome in each read, in read order."""
    rows: dict[str, dict[tuple[str, str, int], list[Item]]] = {}
    for condition in conditions:
        table: dict[tuple[str, str, int], list[Item]] = defaultdict(list)
        for run in reads:
            for item in run.items[condition]:
                table[item.key].append(item)
        rows[condition] = dict(sorted(table.items()))
    return rows


def _f3_runs(prereg: Prereg, reads: int) -> bool:
    return reads >= max(2, prereg.min_reads)


def _families(rows: Mapping[str, Rows], prereg: Prereg, reads: int) -> dict[str, Any]:
    """F1 (accuracy) and F2 (harm) with Holm on the sign-flip p, and F3 (stability) with Holm on the mid-p when there
    are enough reads (``None`` otherwise)."""
    settings = prereg.settings
    ours = rows[prereg.reference]
    families: dict[str, Any] = {
        "F1_accuracy": {
            _pair_key(prereg.reference, b): _family_pair(ours, rows[b], lambda i: i.right, settings)
            for b in prereg.baselines
        },
        "F2_harm": {
            _pair_key(prereg.reference, b): _family_pair(ours, rows[b], lambda i: i.harmful, settings)
            for b in prereg.baselines
        },
        "F3_stability": {
            _pair_key(prereg.reference, b): _stability_pair(ours, rows[b], settings) for b in prereg.baselines
        }
        if _f3_runs(prereg, reads)
        else None,
    }
    for name in ("F1_accuracy", "F2_harm"):
        family = families[name]
        for key, adjusted in zip(
            family, stats.holm([row["signflip"]["p"] for row in family.values()]), strict=True
        ):
            family[key]["holm"] = adjusted
    if families["F3_stability"] is not None:
        _holm_midp(families["F3_stability"])
    return families


def _holm_midp(family: dict[str, dict[str, Any]]) -> None:
    for key, adjusted in zip(family, stats.holm([row["midp"] for row in family.values()]), strict=True):
        family[key]["holm"] = adjusted


def _noninferiority(rows: Mapping[str, Rows], prereg: Prereg, accuracy: Mapping[str, Any]) -> dict[str, Any]:
    """Against each baseline Ordnung must not trail by more than the margin: the inverted cluster sign-flip gives the
    interval the rule reads; the bootstrap interval and the error counts are beside it, descriptive."""
    settings = prereg.settings
    blocks = {}
    for baseline in prereg.noninferior_to:
        pair = _pair_key(prereg.reference, baseline)
        sums = _cluster_sums(rows[prereg.reference], rows[baseline], lambda i: i.right)
        bound = signflip_interval(
            [(a - b, n) for a, b, n in sums],
            level=settings.level,
            exact_max=settings.signflip_exact_max,
            draws=settings.signflip_draws,
            seed=settings.seed,
        )
        ours, theirs = sum(n - a for a, _, n in sums), sum(n - b for _, b, n in sums)
        blocks[pair] = {
            "margin": settings.noninferiority_margin,
            "bound": bound,
            "bootstrap": accuracy[pair]["bootstrap"],
            "errors": {"ours": ours, "theirs": theirs, "ratio": ours / theirs if theirs else None},
            "decision": noninferiority_decision(
                bound["lo"], bound["hi"], settings.noninferiority_margin, baseline
            ),
        }
    return blocks


def _decision_key(baseline: str) -> str:
    return "beats_llm_only" if baseline == "llm_only" else f"vs_{baseline}"


def _comparisons(families: Mapping[str, Any], prereg: Prereg, ni: Mapping[str, Any]) -> dict[str, Any]:
    """The pre-registered rules for each comparison, as codes: F1 against the model alone and the rules
    text, non-inferiority against the agent, and F2 against every baseline."""
    alpha = prereg.settings.alpha

    def judged(row: Mapping[str, Any], ahead: str, behind: str, otherwise: str) -> str:
        """``ahead`` (Ordnung's rate higher), ``behind`` (lower), each by Holm and an interval on one side of 0."""
        lo, hi = row["bootstrap"]["lo"], row["bootstrap"]["hi"]
        if row["holm"] < alpha and lo is not None and lo > 0:
            return ahead
        if row["holm"] < alpha and hi is not None and hi < 0:
            return behind
        return otherwise

    accuracy, harm = families["F1_accuracy"], families["F2_harm"]
    decisions: dict[str, Any] = {}
    if "llm_only" in prereg.baselines:
        row = accuracy[_pair_key(prereg.reference, "llm_only")]
        decisions["beats_llm_only"] = judged(row, "clear", "baseline_ahead", "no_clear_difference")
    if "llm_rules_text" in prereg.baselines:
        row = accuracy[_pair_key(prereg.reference, "llm_rules_text")]
        decisions["vs_llm_rules_text"] = judged(row, "clear", "baseline_ahead", "level_within_noise")
    for baseline in prereg.noninferior_to:
        decisions[f"vs_{baseline}"] = ni[_pair_key(prereg.reference, baseline)]["decision"]
    for baseline in prereg.baselines:
        row = harm[_pair_key(prereg.reference, baseline)]
        decisions[f"f2_vs_{baseline}"] = judged(row, "more", "fewer", "no_clear_difference")
    return decisions


def _decisions(
    families: Mapping[str, Any],
    summaries: Mapping[str, Mapping[str, Any]],
    prereg: Prereg,
    item_reads: int,
    ni: Mapping[str, Any],
) -> dict[str, Any]:
    """The pre-registered decision rules (§6.11), as codes the presenter turns into its sentences."""
    decisions = _comparisons(families, prereg, ni)
    ours = summaries[prereg.reference]
    harmful = sum(row["k"] for row in ours["harmful_per_read"])
    decisions["harmful"] = {"dates": harmful, "reads": item_reads, "none": harmful == 0}
    if "llm_only" in prereg.baselines:
        stability = families["F3_stability"]
        if stability is None:
            decisions["more_stable_than_llm_only"] = None
        else:
            row = stability[_pair_key(prereg.reference, "llm_only")]
            decisions["more_stable_than_llm_only"] = bool(
                row["holm"] < prereg.settings.alpha and (row["diff"] or 0) < 0
            )
    flags = ours["flags_over_reads"]
    decisions["flags_caught"] = {
        "caught": flags["caught_dates"],
        "wrong": flags["wrong_dates"],
        "caught_reads": flags["caught_reads"],
        "wrong_reads": flags["wrong_reads"],
    }
    return decisions


def _decision_roles(decisions: Mapping[str, Any]) -> dict[str, str]:
    """One confirmatory decision (F1 against the model alone); harm and the flags are counts; the rest secondary."""
    confirmatory = _decision_key(CONFIRMATORY["baseline"])
    return {
        key: "confirmatory"
        if key == confirmatory
        else "descriptive"
        if key in ("harmful", "flags_caught")
        else "secondary"
        for key in decisions
    }


def multi_read(reads: Sequence[Run], prereg: Prereg, *, context: _Context | None = None) -> dict[str, Any]:
    """The primary split over its reads: per condition the per-read rates, the mean over reads, stability and the
    descriptive numbers; the families F1 (accuracy), F2 (harm) and F3 (stability, with at least ``min_reads``
    reads) with Holm; non-inferiority by the inverted sign-flip test; the sensitivity analysis on read 1; and the
    decisions the pre-registered rules take, one of them confirmatory."""
    context = context or _Context()
    settings = prereg.settings
    level = settings.level
    conditions = (prereg.reference, *prereg.baselines)
    k = len(reads)
    rows = _rows(reads, conditions)
    letter_rows = {
        c: [
            [letter for run in reads for letter in run.letters[c] if letter.entry_id == entry_id]
            for entry_id in sorted(letter.entry_id for letter in reads[0].letters[c])
        ]
        for c in conditions
    }
    n = len(rows[prereg.reference])
    summaries: dict[str, Any] = {}
    for condition in conditions:
        table = rows[condition]
        flat = [item for run in reads for item in run.items[condition]]
        letters = [letter for run in reads for letter in run.letters[condition]]
        right_matrix = [[item.right for item in items] for items in table.values()]
        mean = stats.cluster_bootstrap(
            _mean_clusters(table, lambda i: i.right),
            resamples=settings.resamples,
            seed=settings.seed,
            level=level,
        )
        mean_harm = stats.cluster_bootstrap(
            _mean_clusters(table, lambda i: i.harmful),
            resamples=settings.resamples,
            seed=settings.seed,
            level=level,
        )
        first_read = list(reads[0].items[condition])
        exact_runs = [sum(1 for item in run.items[condition] if item.right) for run in reads]
        summary: dict[str, Any] = {
            "exact_per_read": [rate(right, n, level) for right in exact_runs],
            "harmful_per_read": [
                rate(sum(1 for item in run.items[condition] if item.harmful), n, level) for run in reads
            ],
            "late_per_read": [
                rate(sum(1 for item in run.items[condition] if item.late), n, level) for run in reads
            ],
            "exact_range": [min(exact_runs), max(exact_runs)],
            "mean_accuracy": {"value": mean.value, "ci": [mean.lo, mean.hi], "method": mean.method},
            "mean_harmful": {
                "value": mean_harm.value,
                "ci": [mean_harm.lo, mean_harm.hi],
                "method": mean_harm.method,
            },
            "pass_all": rate(*stats.pass_all_k(right_matrix), level),
            "pass_any": rate(*stats.pass_any_k(right_matrix), level),
            "unstable": rate(
                *stats.flip_rate([[item.predicted for item in items] for items in table.values()]), level
            ),
            "harmful_any_read": rate(
                sum(1 for items in table.values() if any(i.harmful for i in items)), n, level
            ),
            "late_any_read": rate(sum(1 for items in table.values() if any(i.late for i in items)), n, level),
            "run_noise_share": stats.run_noise_share([[int(x) for x in row] for row in right_matrix]),
            # one item is one trial: read 1's items (an item wrong alike in every read is one wrong date, not three)
            "selective": selective(first_read, level),
            "flags_over_reads": _flags_over_reads(table, level),
            "loss": {
                _ratio_key(r): stats.harm_loss(
                    sum(1 for i in flat if i.early), sum(1 for i in flat if i.harmful), len(flat), r
                )
                for r in settings.loss_ratios
            },
            "cost": _cost(letters, sum(1 for item in flat if item.right)),
            "latency_ms": _latency(letters),
            "model_failed_per_read": [sum(1 for x in run.letters[condition] if x.failed) for run in reads],
            "unanswered_per_read": [sum(1 for x in run.letters[condition] if x.error) for run in reads],
        }
        if condition == prereg.reference:
            summary["reading_agreement"] = _reading_agreement(table)
        tool_use = _tool_use(letter_rows[condition])
        if tool_use is not None:
            summary["tool_use_consistency"] = tool_use
        summaries[condition] = summary
    families = _families(rows, prereg, k)
    ni = _noninferiority(rows, prereg, families["F1_accuracy"])
    first = reads[0]
    sensitivity = {}
    for name, indicator in (("accuracy", lambda i: i.right), ("harmful", lambda i: i.harmful)):
        sensitivity[name] = _with_holm(
            {
                _pair_key(prereg.reference, b): paired_one_read(
                    first.items[prereg.reference], first.items[b], indicator, settings
                )
                for b in prereg.baselines
            },
            settings.alpha,
        )
    clusters = {item.cluster for item in first.items[prereg.reference]}
    decisions = _decisions(families, summaries, prereg, n * k, ni)
    confirmatory = _decision_key(CONFIRMATORY["baseline"])
    return {
        "split": prereg.primary_split,
        "reads": k,
        "reads_registered": prereg.primary_reads,
        "reads_used": [run.repeat for run in reads],
        "items": n,
        "letters": len(first.letters[prereg.reference]),
        "clusters": len(clusters),
        "conditions": summaries,
        "families": families,
        "not_run": {}
        if families["F3_stability"] is not None
        else {"F3_stability": f"fewer reads than min_reads ({max(2, prereg.min_reads)})"},
        "noninferiority": ni,
        "sensitivity_r1": sensitivity,
        "decisions": decisions,
        "decision_roles": _decision_roles(decisions),
        "confirmatory": {
            "decision": confirmatory,
            "family": CONFIRMATORY["family"],
            "pair": _pair_key(prereg.reference, CONFIRMATORY["baseline"]),
            "code": decisions.get(confirmatory),
        },
        "errors": [
            row
            for run in reads
            for row in _error_rows({c: run.items[c] for c in conditions}, read=run.repeat)
        ],
        "unanswered": [
            {key: row[key] for key in ("read", "entry_id", "condition", "deviations")}
            for row in context.unanswered
            if row["split"] == prereg.primary_split
        ],
    }


def _flags_over_reads(rows: Rows, level: float) -> dict[str, Any]:
    """ "Please check" over repeated reads, each date once: the dates wrong in at least one read, and of those the
    ones flagged Please check in every read in which they were wrong (caught); the item × read counts beside them."""
    wrong = [reads for reads in rows.values() if any(not item.right for item in reads)]
    caught = [
        reads for reads in wrong if all(item.tier == "please_check" for item in reads if not item.right)
    ]
    return {
        "reads": max((len(reads) for reads in rows.values()), default=0),
        "wrong_dates": len(wrong),
        "caught_dates": len(caught),
        "wrong_reads": sum(1 for reads in rows.values() for item in reads if not item.right),
        "caught_reads": sum(
            1 for reads in rows.values() for item in reads if not item.right and item.tier == "please_check"
        ),
        "caught": rate(len(caught), len(wrong), level),
    }


#: The pre-registered decision codes (§6.11) and the sentence each stands for; the presenter's phase 2 fills the
#: placeholders from the final analysis (``{d}``: Ordnung minus the baseline in points, ``{ci}``: its interval).
DECISION_SENTENCES = {
    "clear": "Ordnung is ahead of {baseline} ({d} points, 95 % CI {ci}).",
    "baseline_ahead": "{baseline} is ahead of Ordnung ({d} points, 95 % CI {ci}).",
    "no_clear_difference": "Against {baseline}: no clear difference ({d} points, 95 % CI {ci}).",
    "level_within_noise": "Against {baseline}: level within noise ({d} points, 95 % CI {ci}).",
    "non_inferior": "{baseline} is not ahead by more than 5 points ({d} points, 95 % CI {ci}).",
    "agent_higher": "The agent scored higher ({d} points, 95 % CI {ci}).",
    "baseline_higher": "{baseline} scored higher ({d} points, 95 % CI {ci}).",
    "cannot_tell": "Against {baseline}, we cannot tell whether Ordnung is within 5 points ({d} points, 95 % CI {ci}).",
    "fewer": "Fewer late or missed dates than {baseline} ({d} points, 95 % CI {ci}).",
    "more": "More late or missed dates than {baseline} ({d} points, 95 % CI {ci}).",
}


# --------------------------------------------------------------------------------------------------
# Sensitivity analyses: beside the primary, never instead of it
# --------------------------------------------------------------------------------------------------


def _rescored(
    rows: Mapping[str, Rows], reads: Sequence[Run], change: Callable[[str, int, Item], Item]
) -> tuple[dict[str, Rows], int]:
    """The rows with ``change(condition, read, item)`` applied to every item, and how many it changed."""
    changed = 0
    new: dict[str, Rows] = {}
    for condition, table in rows.items():
        new_table = {}
        for key, items in table.items():
            row = []
            for run, item in zip(reads, items, strict=True):
                after = change(condition, run.repeat, item)
                changed += after != item
                row.append(after)
            new_table[key] = row
        new[condition] = new_table
    return new, changed


def _against(item: Item, label: str) -> Item:
    """The item scored against another label date (a date not given stays missed or declined)."""
    try:
        predicted, truth = (
            calendar_date.fromisoformat(str(item.predicted)),
            calendar_date.fromisoformat(label),
        )
    except ValueError:
        return item
    if predicted == truth:
        return replace(item, outcome="correct", direction=None, days_off=None)
    direction = "late" if predicted > truth else "early"
    return replace(item, outcome="wrong", direction=direction, days_off=(predicted - truth).days)


def _sensitivity_numbers(rows: Mapping[str, Rows], prereg: Prereg, reads: int) -> dict[str, Any]:
    """What a sensitivity analysis gives beside the primary: per condition the dates right per read, the mean and
    the harmful item-reads; F1 and F2 with Holm; non-inferiority; and the comparisons' codes."""
    settings = prereg.settings
    conditions = {
        condition: {
            "exact_per_read": [sum(1 for items in table.values() if items[i].right) for i in range(reads)],
            "mean_accuracy": sum(1 for items in table.values() for item in items if item.right)
            / max(1, sum(len(items) for items in table.values())),
            "harmful_item_reads": sum(1 for items in table.values() for item in items if item.harmful),
        }
        for condition, table in rows.items()
    }
    ours = rows[prereg.reference]
    families: dict[str, Any] = {
        name: {
            _pair_key(prereg.reference, b): _family_pair(ours, rows[b], test, settings)
            for b in prereg.baselines
        }
        for name, test in (("F1_accuracy", lambda i: i.right), ("F2_harm", lambda i: i.harmful))
    }
    for family in families.values():
        for key, adjusted in zip(
            family, stats.holm([row["signflip"]["p"] for row in family.values()]), strict=True
        ):
            family[key]["holm"] = adjusted
    ni = _noninferiority(rows, prereg, families["F1_accuracy"])
    return {
        "conditions": conditions,
        **families,
        "noninferiority": ni,
        "decisions": _comparisons(families, prereg, ni),
    }


def _same_rows_f3(
    rows: Mapping[str, Rows], prereg: Prereg, keys: Sequence[tuple[str, str, int]]
) -> dict[str, Any]:
    ours = rows[prereg.reference]
    subset = {key: ours[key] for key in keys}
    family = {
        _pair_key(prereg.reference, b): _stability_pair(
            subset, {key: rows[b][key] for key in keys}, prereg.settings
        )
        for b in prereg.baselines
    }
    _holm_midp(family)
    return family


def _rescoring(
    name: str, rows: Mapping[str, Rows], prereg: Prereg, context: _Context
) -> tuple[dict[str, Any], Callable[[str, int, Item], Item]]:
    """A sensitivity analysis that scores some items again: what it applies, and the change it makes to an item of a
    condition in a read."""
    split = prereg.primary_split
    if name == "s_conv":
        alternatives = context.conventions
        tagged = sum(1 for key in rows[prereg.reference] if (key[1], key[2]) in alternatives)

        def other_reading(condition: str, read: int, item: Item) -> Item:
            dates = alternatives.get((item.entry_id, item.index))
            if dates and not item.right and item.predicted in dates:
                return replace(item, outcome="correct", direction=None, days_off=None)
            return item

        return {"tagged_items": tagged}, other_reading
    if name == "label_corrected":
        errors = [d for d in context.deviations if d.kind == "label_error" and d.split == split]
        corrected = {(entry, index): day for d in errors for entry, index, day in d.items}

        def corrected_label(condition: str, read: int, item: Item) -> Item:
            label = corrected.get((item.entry_id, item.index))
            return item if label is None else _against(item, label)

        return {"deviations": sorted(d.id for d in errors)}, corrected_label
    retakes = [d for d in context.deviations if d.kind == "retake" and d.split == split]
    timed_out = {
        (d.repeat, entry, condition)
        for d in retakes
        for entry, condition, outcome in d.first_attempt
        if outcome == "timeout"
    }

    def first_attempt(condition: str, read: int, item: Item) -> Item:
        if (read, item.entry_id, condition) not in timed_out:
            return item
        return replace(item, outcome="missed", direction=None, days_off=None, predicted=None, flagged=False)

    return {"deviations": sorted(d.id for d in retakes)}, first_attempt


def _sensitivities(
    rows: Mapping[str, Rows], reads: Sequence[Run], prereg: Prereg, context: _Context
) -> dict[str, Any]:
    """The pre-registered sensitivity analyses, each beside the primary and never instead of it."""
    found: dict[str, Any] = {}
    for name in prereg.sensitivities:
        if name in ("same_day_f3", "same_cli_f3"):
            found[name] = _same_unit_f3(name, rows, reads, prereg, context)
            continue
        block, change = _rescoring(name, rows, prereg, context)
        new, changed = _rescored(rows, reads, change)
        block["items_changed"] = changed
        if changed:
            block.update(_sensitivity_numbers(new, prereg, len(reads)))
        else:
            block["same_as_primary"] = True
        found[name] = block
    return found


def _same_unit_f3(
    name: str, rows: Mapping[str, Rows], reads: Sequence[Run], prereg: Prereg, context: _Context
) -> dict[str, Any]:
    """F3 on the items whose reads share one recording day (``same_day_f3``) or one claude version
    (``same_cli_f3``, given only when the versions differ)."""
    ours = rows[prereg.reference]
    which = 0 if name == "same_day_f3" else 1

    def values(key: tuple[str, str, int]) -> set[str | None]:
        return {
            context.units.get((prereg.primary_split, run.repeat, key[1]), (None, None))[which]
            for run in reads
        }

    block: dict[str, Any] = {}
    if which == 1:
        versions = sorted({value for key in ours for value in values(key) if value is not None})
        block["versions"] = versions
        if len(versions) <= 1:
            return {**block, "same_as_primary": True}
    if not _f3_runs(prereg, len(reads)):
        return {**block, "not_run": f"fewer reads than min_reads ({max(2, prereg.min_reads)})"}
    keys = [key for key in ours if len(values(key)) == 1 and None not in values(key)]
    block["items"] = len(keys)
    if len(keys) == len(ours):
        block["same_as_primary"] = True
    else:
        block["F3_stability"] = _same_rows_f3(rows, prereg, keys) if keys else None
    return block


# --------------------------------------------------------------------------------------------------
# Exploratory blocks: rates only, no test and no p-value
# --------------------------------------------------------------------------------------------------


def _grouped(
    rows: Mapping[str, Rows],
    reads: Sequence[Run],
    prereg: Prereg,
    group_of: Callable[[Run, Item], str],
) -> dict[str, Any]:
    level = prereg.settings.level
    groups: dict[str, dict[str, list[Item]]] = defaultdict(lambda: defaultdict(list))
    for condition, table in rows.items():
        for items in table.values():
            for run, item in zip(reads, items, strict=True):
                groups[group_of(run, item)][condition].append(item)
    return {
        group: {
            "item_reads": len(by[prereg.reference]),
            "conditions": {
                condition: {
                    "exact": rate(sum(1 for i in found if i.right), len(found), level),
                    "harmful": rate(sum(1 for i in found if i.harmful), len(found), level),
                }
                for condition, found in ((c, by[c]) for c in rows)
            },
        }
        for group, by in sorted(groups.items())
    }


def _exploratory(
    rows: Mapping[str, Rows],
    reads: Sequence[Run],
    prereg: Prereg,
    context: _Context,
    pooled: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The pre-registered exploratory blocks: rates with Clopper–Pearson intervals, never a test or a p-value."""
    level = prereg.settings.level
    split = prereg.primary_split
    label = "exploratory: rates over item-reads, with no test"
    blocks: dict[str, Any] = {}
    for name in prereg.exploratory:
        if name == "by_family":
            blocks[name] = {"label": label, "groups": _grouped(rows, reads, prereg, lambda run, i: i.family)}
        elif name == "by_modality":
            blocks[name] = {
                "label": label,
                "groups": _grouped(rows, reads, prereg, lambda run, i: i.modality),
            }
        elif name == "by_recording_day":

            def day_of(run: Run, item: Item) -> str:
                day = context.units.get((split, run.repeat, item.entry_id), (item.day, None))[0]
                return day or "unknown"

            blocks[name] = {"label": label, "groups": _grouped(rows, reads, prereg, day_of)}
        elif name == "by_adversarial_class":
            counts: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
            for condition in rows:
                for run in reads:
                    for letter in run.letters[condition]:
                        for check, passed in letter.adversarial:
                            counts[check][condition][0] += int(passed)
                            counts[check][condition][1] += 1
            blocks[name] = {
                "label": "exploratory: the scorer's adversarial checks over letter-reads, with no test",
                "groups": {
                    check: {"conditions": {c: rate(by[c][0], by[c][1], level) for c in rows}}
                    for check, by in sorted(counts.items())
                },
            }
        elif name == "pooled_held_out" and pooled is not None:
            blocks[name] = pooled
    return blocks


def _units_of(runs: Sequence[Run]) -> dict[tuple[str, int, str], tuple[str | None, str | None]]:
    """Each unit's day (its letters' today) and the run's claude version, from the results files alone."""
    units: dict[tuple[str, int, str], tuple[str | None, str | None]] = {}
    for run in runs:
        cli = run.meta.get("cli_version")
        for entry in _entries_of(run):
            day = entry.get("simulated_today") or entry.get("today")
            units[(run.split, run.repeat, str(entry.get("id")))] = (
                str(day) if day else None,
                str(cli) if cli else None,
            )
    return units


def _final_methods(prereg: Prereg) -> dict[str, str]:
    settings = prereg.settings
    return {
        "confirmatory": "one confirmatory decision: F1, Ordnung against the model alone (the Holm-adjusted "
        "sign-flip p below alpha and the bootstrap interval on one side of 0); every other comparison is secondary, "
        "with Holm within its family",
        "noninferiority": f"the {settings.level:g} interval of the difference by inverting the cluster sign-flip "
        "test: a difference d is kept when the two-sided test of the cluster totals centred on d (hits minus d times "
        f"item-reads) does not reject (exact up to {settings.signflip_exact_max} clusters, else "
        f"{settings.signflip_draws} seeded draws); the baseline is higher only when the whole interval is below 0, "
        f"Ordnung not worse by more than {settings.noninferiority_margin:g} when its lower end is above minus that; "
        "the bootstrap interval and the error counts are descriptive",
        "reads": f"F3 on at least {max(2, prereg.min_reads)} reads; with fewer, the cluster tests on read 1 are the "
        "primary, McNemar beside them, and F3 is not run",
        "deviations": "a read or unit that differs from the frozen inputs is analysed only as a deviation recorded "
        "at the time says: never waivable (left out), excluded, or included and listed",
        "sensitivities": "s_conv: a date a disputed convention's other reading gives counts as right; "
        "label_corrected: the labels the blind review corrected; first_attempt: a timed-out first attempt of a "
        "retaken unit counts as missed; same_day_f3 and same_cli_f3: F3 on the items whose reads share one day, or "
        "one claude version",
        "exploratory": "rates with Clopper-Pearson intervals over item-reads (letter-reads for the adversarial "
        "checks); no test, no p-value",
    }


def final_analysis(
    prereg: Prereg,
    runs: Sequence[Run],
    *,
    pooled_with: Sequence[Run] = (),
    prereg_record: Mapping[str, Any] | None = None,
    checked: Checked | None = None,
    conventions: Mapping[tuple[str, int], frozenset[str]] | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """The pre-registered final run: the primary split over its reads, each secondary split, the sensitivity analyses
    and the exploratory blocks (the earlier held-out splits pooled with the primary split's first read among them).

    ``checked`` is what :func:`check_frozen` found (:func:`final_from_files` gives it); without it every registered
    read must be there and no letter may be left without an answer."""
    missing = checked.missing if checked is not None else {}
    reads, secondary = _assign_reads(prereg, runs, missing)
    if checked is None:
        unanswered = sorted(
            {
                f"{_run_label(run)}: {letter.entry_id}"
                for run in (*reads, *secondary.values())
                for letters in run.letters.values()
                for letter in letters
                if letter.error
            }
        )
        if unanswered:
            raise AnalysisError(
                f"letters without an answer ({', '.join(unanswered)}): only an unanswered deviation recorded at "
                "the time lets one be scored empty"
            )
    context = _Context(
        units=checked.units if checked is not None else _units_of([*reads, *secondary.values()]),
        deviations=checked.deviations if checked is not None else (),
        conventions=conventions or {},
        unanswered=checked.unanswered if checked is not None else (),
    )
    settings = prereg.settings
    conditions = (prereg.reference, *prereg.baselines)
    primary = multi_read(reads, prereg, context=context)
    primary["reads_missing"] = [
        info for (split, _), info in sorted(missing.items()) if split == prereg.primary_split
    ]
    secondary_blocks: dict[str, Any] = {}
    for split, _ in sorted(prereg.secondary):
        if split not in secondary:
            secondary_blocks[split] = {"not_recorded": missing[(split, 1)]}
            continue
        run = secondary[split]
        body = single_read([run], settings, paired=False)
        for condition in conditions:
            letters = run.letters[condition]
            body["conditions"][condition]["model_failed"] = sum(1 for x in letters if x.failed)
            body["conditions"][condition]["unanswered"] = sum(1 for x in letters if x.error)
        body["unanswered"] = [
            {key: row[key] for key in ("read", "entry_id", "condition", "deviations")}
            for row in context.unanswered
            if row["split"] == split
        ]
        secondary_blocks[split] = body
    rows = _rows(reads, conditions)
    pooled = None
    if pooled_with:
        pooled = {
            "label": "exploratory: splits recorded with different code, pooled after the results were known",
            "splits": [run.split for run in _sorted_runs([*pooled_with, reads[0]])],
            **single_read([*pooled_with, reads[0]], settings, paired=False),
        }
    left_out = [run for run, _ in checked.left_out] if checked is not None else []
    inputs = (
        [run.input_record() | {"role": "primary"} for run in reads]
        + [run.input_record() | {"role": "secondary"} for run in _sorted_runs(list(secondary.values()))]
        + [run.input_record() | {"role": "left_out"} for run in _sorted_runs(left_out)]
        + [run.input_record() | {"role": "pooled"} for run in pooled_with]
    )
    meta: dict[str, Any] = {
        "kind": FINAL_KIND,
        "date": date or max(str(run.meta.get("date") or "") for run in reads),
        "model": prereg.model,
        "pre_registered": True,
        "label": "pre-registered",
        "prereg": dict(prereg_record or {}),
        "inputs": inputs,
        "settings": settings.to_dict(),
        "analysis": {
            "rules": dict(RULES),
            "min_reads": prereg.min_reads,
            "confirmatory": dict(CONFIRMATORY),
            "sensitivities": list(prereg.sensitivities),
            "exploratory": list(prereg.exploratory),
        },
        "methods": _methods(settings) | _final_methods(prereg),
    }
    if checked is not None:
        meta["frozen_check"] = {
            "reads_left_out": [row for _, row in checked.left_out],
            "units_excluded": checked.units_excluded,
            "cli_versions": checked.cli_versions,
            **checked.evidence,
        }
        meta["deviations"] = [dict(d.record) for d in checked.deviations]
    return {
        "schema": ANALYSIS_SCHEMA,
        "meta": meta,
        "primary": primary,
        "secondary": secondary_blocks,
        "sensitivities": _sensitivities(rows, reads, prereg, context),
        "exploratory": _exploratory(rows, reads, prereg, context, pooled),
    }


def _repo_path(path: Path) -> str:
    """The path from the repository's root (where ``evals/reproduce.py`` runs its checks), else the absolute one."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _from_root(name: str) -> Path:
    path = Path(name)
    return path if path.is_absolute() else ROOT / path


def final_from_files(
    prereg_path: Path,
    paths: Sequence[Path],
    *,
    results_dir: Path | None = None,
    recorded_dir: Path | None = None,
    dataset_dir: Path | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """:func:`final_analysis` from a pre-registration file and results files, after :func:`check_frozen`: the
    deviations file it names, the day index and the ledger (in ``recorded_dir``), the dataset's manifest (in
    ``dataset_dir``, for S-conv) and ``pool_with`` (read in ``results_dir``)."""
    results_dir = results_dir or RESULTS_DIR
    recorded_dir = recorded_dir or RECORDED_DIR
    dataset_dir = dataset_dir or DATASET_DIR
    raw = prereg_path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"the pre-registration is not JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise AnalysisError("the pre-registration is not a JSON object")
    prereg = parse_prereg(data)
    frozen = parse_frozen(data)
    deviations_path = _from_root(frozen.deviations_file)
    deviations = load_deviations(deviations_path)
    runs = [read_run(path) for path in paths]
    folder = recorded_dir / _safe(prereg.model)
    day_index_path, ledger_path = folder / DAY_INDEX_FILE, folder / LEDGER_FILE
    checked = check_frozen(
        prereg,
        frozen,
        runs,
        deviations,
        day_index=_read_day_index(day_index_path),
        ledger=_read_ledger(ledger_path),
    )
    checked.evidence["deviations_file"] = {
        "file": _repo_path(deviations_path),
        "sha256": hashlib.sha256(deviations_path.read_bytes()).hexdigest(),
        "entries": len(deviations),
    }
    checked.evidence["day_index"]["file"] = _repo_path(day_index_path)
    checked.evidence["ledger"]["file"] = _repo_path(ledger_path)
    conventions = {}
    if "s_conv" in prereg.sensitivities:
        manifest = dataset_dir / MANIFEST_FILE
        conventions = _conventions(manifest, frozen.manifest_sha256)
        checked.evidence["manifest"] = {"file": _repo_path(manifest), "sha256": frozen.manifest_sha256}
    pooled = [read_run(results_dir / name) for name in prereg.pool_with]
    record = {"file": _repo_path(prereg_path), "sha256": hashlib.sha256(raw).hexdigest()}
    return final_analysis(
        prereg,
        checked.runs,
        pooled_with=pooled,
        prereg_record=record,
        checked=checked,
        conventions=conventions,
        date=date,
    )


# --------------------------------------------------------------------------------------------------
# Rendering and the command line
# --------------------------------------------------------------------------------------------------


def _rounded(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return float(f"{value:.{SIGNIFICANT_DIGITS}g}")
    if isinstance(value, Mapping):
        return {str(key): _rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_rounded(item) for item in value]
    raise TypeError(f"cannot render {type(value).__name__}")


def render(document: Mapping[str, Any]) -> str:
    """The document as JSON text: floats rounded, the keys in the order the analysis writes them."""
    return json.dumps(_rounded(document), ensure_ascii=False, indent=1) + "\n"


def _safe(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


def output_name(date: str, model: str, kind: str) -> str:
    """``<date>-<model>-<kind>.json``, as the results files are named."""
    return f"{date}-{_safe(model)}-{kind}.json"


def _differing_keys(old: Any, new: Any) -> list[str]:
    if isinstance(old, Mapping) and isinstance(new, Mapping):
        return sorted(key for key in old.keys() | new.keys() if old.get(key) != new.get(key))
    return ["(document)"]


def _check(path: Path, text: str) -> int:
    if not path.is_file():
        print(f"{path}: no such file to check", file=sys.stderr)
        return 1
    committed = path.read_text(encoding="utf-8")
    if committed == text:
        print(f"{path.name}: up to date", file=sys.stderr)
        return 0
    try:
        keys = _differing_keys(json.loads(committed), json.loads(text))
    except json.JSONDecodeError:
        keys = ["(not JSON)"]
    print(f"{path.name}: differs from a fresh render (in {', '.join(keys) or 'formatting'})", file=sys.stderr)
    return 1


def _summary_lines(document: Mapping[str, Any]) -> list[str]:
    """Numbers only, for the terminal."""
    lines = [f"{document['meta']['kind']} ({document['meta']['label']}), {document['meta']['date']}"]
    body = document.get("primary") or document
    for condition, summary in body["conditions"].items():
        if "exact" in summary:
            exact, harmful = summary["exact"], summary["harmful"]
            lo, hi = exact["ci"]
            lines.append(
                f"  {condition}: exact {exact['k']}/{exact['n']} [{lo * 100:.1f}-{hi * 100:.1f}], harmful "
                f"{harmful['k']}/{harmful['n']}, please-check caught "
                f"{summary['selective']['please_check']['recall_wrong']['k']} of "
                f"{summary['selective']['please_check']['recall_wrong']['n']} wrong"
            )
        else:
            lines.append(
                f"  {condition}: exact per read {[row['k'] for row in summary['exact_per_read']]} of "
                f"{summary['exact_per_read'][0]['n']}, unstable {summary['unstable']['k']}"
            )
    for family, pairs in (body.get("paired") or body.get("families") or {}).items():
        for key, row in (pairs or {}).items():
            if "b" in row:
                lines.append(f"  {family} {key}: {row['b']} vs {row['c']}, exact p {p_text(row['exact_p'])}")
            else:
                lines.append(f"  {family} {key}: diff {row['diff']:+.3f}, p {p_text(row['signflip']['p'])}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m evals.analysis [RESULTS.json …] [--prereg FILE] [--write | --check]``"""
    parser = argparse.ArgumentParser(
        prog="python -m evals.analysis",
        description="The benchmark analysis from results files alone: the held-out splits re-analysed, or the "
        "pre-registered final run (--prereg).",
    )
    parser.add_argument(
        "results",
        nargs="*",
        type=Path,
        help="results files (default for the re-analysis: the held-out runs as recorded, in --results-dir)",
    )
    parser.add_argument("--prereg", type=Path, metavar="FILE", help="analyse the pre-registered final run")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="write the analysis to --out-dir")
    mode.add_argument(
        "--check", action="store_true", help="fail when the written analysis is not a fresh render"
    )
    parser.add_argument(
        "--date",
        help="the analysis's date, in its file name (default: today for the re-analysis written; the last primary "
        "read's for the final run)",
    )
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR, help="where results files are read")
    parser.add_argument(
        "--out-dir", type=Path, help="where the analysis is written or checked (default: --results-dir)"
    )
    args = parser.parse_args(argv)
    out_dir: Path = args.out_dir or args.results_dir
    try:
        if args.prereg is not None:
            if not args.results:
                parser.error("--prereg needs the results files of the final run")
            document = final_from_files(
                args.prereg, args.results, results_dir=args.results_dir, date=args.date
            )
            path = out_dir / output_name(document["meta"]["date"], document["meta"]["model"], FINAL_KIND)
        else:
            paths = args.results or [args.results_dir / name for name in HELD_OUT_AS_RECORDED]
            runs = [read_run(path) for path in paths]
            if args.check:
                # the committed re-analysis is rendered again with its own date (the newest, if there are several)
                pattern = f"*-{_safe(MODEL)}-{REANALYSIS_KIND}.json"
                committed = sorted(out_dir.glob(pattern))
                if not committed:
                    print(f"{out_dir}: no {pattern} to check", file=sys.stderr)
                    return 1
                path = committed[-1]
                document = reanalyse(runs, date=path.name[:10])
            else:
                document = reanalyse(runs, date=args.date or calendar_date.today().isoformat())
                meta = document["meta"]
                path = out_dir / output_name(meta["date"], meta["model"], REANALYSIS_KIND)
    except (AnalysisError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = render(document)
    if args.check:
        return _check(path, text)
    if args.write:
        out_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}", file=sys.stderr)
        return 0
    print("\n".join(_summary_lines(json.loads(text))))
    return 0


__all__ = [
    "ANALYSIS_SCHEMA",
    "CONFIRMATORY",
    "DECISION_SENTENCES",
    "DEVIATION_CONSEQUENCES",
    "DEVIATION_EFFECTS",
    "EXPLORATORY",
    "FINAL_KIND",
    "HELD_OUT_AS_RECORDED",
    "MIN_READS",
    "PREREG_SCHEMA",
    "REANALYSIS_KIND",
    "RULES",
    "SENSITIVITIES",
    "AnalysisError",
    "Checked",
    "Deviation",
    "Frozen",
    "Item",
    "Letter",
    "Prereg",
    "Run",
    "Settings",
    "check_frozen",
    "condition_summary",
    "default_prereg_analysis",
    "final_analysis",
    "final_from_files",
    "load_deviations",
    "load_run",
    "main",
    "multi_read",
    "noninferiority_decision",
    "output_name",
    "paired_one_read",
    "parse_frozen",
    "parse_prereg",
    "rate",
    "read_run",
    "reanalyse",
    "render",
    "selective",
    "signflip_interval",
    "single_read",
]


if __name__ == "__main__":
    raise SystemExit(main())
