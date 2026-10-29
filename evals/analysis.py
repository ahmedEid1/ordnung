"""The benchmark's analysis: exact statistics, harm and selective prediction, from results files alone.

It reads ``evals/results/*.json`` and nothing else: no model call, no replay, no change to the scorer
(``evals/metrics.py``) or to the records (``evals/records.py``, part of every recording's code digest).

* ``python -m evals.analysis`` — **the held-out splits re-analysed**: holdout, holdout2 and holdout3 as recorded
  (:data:`HELD_OUT_AS_RECORDED`, the held-out rows of ``docs/evals.md``), pooled, with the statistics of
  :mod:`evals.stats`. It is labelled *not pre-registered*: these statistics were chosen after the results were known.
  ``--write [--date D]`` writes ``evals/results/<D>-claude-sonnet-5-heldout-reanalysis.json``; ``--check`` renders it
  again and fails when the committed file differs.
* ``python -m evals.analysis --prereg FILE RESULTS…`` — **the pre-registered final run**: the reads the
  pre-registration names (its ``analysis`` section, :func:`default_prereg_analysis`), its primary families F1–F3 with
  Holm, the one-read sensitivity analysis, the descriptive secondary numbers and the decisions its rules take.
  ``--write`` / ``--check`` as above, for ``evals/results/<date>-claude-sonnet-5-final.json`` (the date of the last
  primary read).

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

Every output holds ids, counts, hashes and metric values only: never a letter's text, a title, a quote, a warning or
a date. Floats are rounded to :data:`SIGNIFICANT_DIGITS` significant digits, so a render is byte-identical on every
platform.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date as calendar_date
from pathlib import Path
from typing import Any

from evals import stats
from evals.metrics import DATE_TOOLS, TOOL_CONDITION, TOOL_PEERS, bootstrap_difference, bootstrap_ratio
from evals.records import CONDITIONS

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "evals" / "results"
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
    """``clear`` when the Holm-adjusted mid-p is below ``alpha`` and Bonett–Price excludes 0; ``suggestive`` when only
    the unadjusted mid-p is; else ``none``."""
    lo, hi = row["bonett_price"]
    excludes_zero = lo is not None and hi is not None and (lo > 0 or hi < 0)
    if row["holm_midp"] < alpha and excludes_zero:
        return "clear"
    return "suggestive" if row["midp"] < alpha else "none"


def _crossover(first: Sequence[Item], second: Sequence[Item], settings: Settings) -> dict[str, Any]:
    """The cost ratio at which the two conditions' harm-weighted losses are equal, with a letter-cluster bootstrap
    (``None`` / ``never``: the second never overtakes the first as a harmful date costs more)."""
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
    point = stats.crossover(*totals)
    draws: list[float] = []
    for drawn in stats.resample_indices(len(clusters), settings.crossover_resamples, settings.seed):
        value = stats.crossover(*(sum(map(column.__getitem__, drawn)) for column in columns))
        draws.append(math.inf if value is None else value)
    finite = sum(1 for value in draws if not math.isinf(value))

    def quantile(q: float) -> float | None:
        value = stats.percentile(draws, q)
        return None if value is None or math.isinf(value) else value

    alpha = (1.0 - settings.level) / 2.0 * 100.0
    return {
        "early": [totals[0], totals[2]],
        "harmful": [totals[1], totals[3]],
        "r_star": point,
        "share_with_crossover": finite / len(draws) if draws else None,
        "bootstrap": {
            "lo": quantile(alpha),
            "median": quantile(50.0),
            "hi": quantile(100.0 - alpha),
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
        "verdict": f"clear: Holm-adjusted mid-p below {settings.alpha} and the Bonett-Price interval excludes 0; "
        f"suggestive: the unadjusted mid-p below {settings.alpha}; else no clear difference",
        "harmful": "late or missed",
        "tiers": "please_check: low confidence, Please check, or found without a date; second_look: medium "
        "confidence; none: no flag, or missed",
        "aurc": "risk-coverage from the most confident tier down, errors spread evenly within a tier",
        "loss": "per 100 scored items: early + r * harmful",
        "crossover": f"r at which the losses are equal; letter-cluster bootstrap, {settings.crossover_resamples} "
        "resamples, percentile interval (null: never)",
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
            for key in ("n", "b", "c", "diff", "exact_p", "midp", "holm_midp", "bonett_price", "verdict")
        }
        claim["text"] = (
            f"{row['b']} vs {row['c']} discordant, exact p {p_text(row['exact_p'])} (mid-p {p_text(row['midp'])}, "
            f"Holm {p_text(row['holm_midp'])}): {VERDICTS[row['verdict']]}"
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
    if crossover is not None and crossover["r_star"] is not None:
        boot = crossover["bootstrap"]
        low = "never" if boot["lo"] is None else f"{boot['lo']:.1f}"
        high = "never" if boot["hi"] is None else f"{boot['hi']:.1f}"
        findings["rules_text_crossover"] = {
            "r_star": crossover["r_star"],
            "lo": boot["lo"],
            "hi": boot["hi"],
            "share_with_crossover": crossover["share_with_crossover"],
            "text": f"Ordnung's harm-weighted loss is the lower one until a late or missed date costs "
            f"{crossover['r_star']:.1f} early ones (95 % bootstrap range {low} to {high})",
        }
    return findings


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


def parse_prereg(data: Mapping[str, Any]) -> Prereg:
    """The ``analysis`` section of a pre-registration; ``AnalysisError`` when a field is missing or malformed (no
    field has a default: what the analysis does is what the pre-registration says)."""
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
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AnalysisError(f"the pre-registration's analysis section is malformed: {exc}") from exc
    if prereg.reference != REFERENCE:
        raise AnalysisError(f"the analysis compares Ordnung with the baselines, not {prereg.reference!r}")
    if prereg.primary_reads < 1 or any(reads != 1 for _, reads in prereg.secondary):
        raise AnalysisError("the primary split is read at least once and each secondary split once")
    if not set(prereg.noninferior_to) <= set(prereg.baselines):
        raise AnalysisError("a non-inferiority comparison names a condition that is not a baseline")
    return prereg


def _assign_reads(prereg: Prereg, runs: Sequence[Run]) -> tuple[list[Run], dict[str, Run]]:
    """The primary reads in order and the secondary runs by split; ``AnalysisError`` for anything that does not fit."""
    wanted = (prereg.reference, *prereg.baselines)
    primary: dict[int, Run] = {}
    secondary: dict[str, Run] = {}
    secondary_splits = {split for split, _ in prereg.secondary}
    for run in runs:
        label = run.name or f"{run.split} read {run.repeat}"
        if run.model != prereg.model:
            raise AnalysisError(f"{label}: model {run.model!r}, the pre-registration names {prereg.model!r}")
        if run.meta.get("partial"):
            raise AnalysisError(f"{label}: a filtered run does not cover its split")
        missing = [c for c in wanted if c not in run.conditions]
        if missing:
            raise AnalysisError(f"{label}: no answers of {', '.join(missing)}")
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
    for read in range(1, prereg.primary_reads + 1):
        if read not in primary:
            raise AnalysisError(f"{prereg.primary_split} read {read} is missing")
    for split, _ in prereg.secondary:
        if split not in secondary:
            raise AnalysisError(f"the {split} run is missing")
    reads = [primary[read] for read in range(1, prereg.primary_reads + 1)]
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


def _mean_clusters(
    rows: Mapping[tuple[str, str, int], Sequence[Item]], test: Callable[[Item], bool]
) -> list[tuple[float, float]]:
    """Per cluster: (hits over every read, items × reads). With the same reads for every item, the ratio is the mean
    over items of the per-item mean over reads; counted in integers, so the sums are exact on every Python."""
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for reads in rows.values():
        row = sums[reads[0].cluster]
        row[0] += sum(1 for item in reads if test(item))
        row[1] += len(reads)
    return [(float(row[0]), float(row[1])) for _, row in sorted(sums.items())]


def _family_pair(
    ours: Mapping[tuple[str, str, int], Sequence[Item]],
    theirs: Mapping[tuple[str, str, int], Sequence[Item]],
    test: Callable[[Item], bool],
    settings: Settings,
) -> dict[str, Any]:
    """F1 / F2: the per-item mean over reads, ours minus theirs; sign-flip test over clusters, paired bootstrap.

    Each cluster is counted in hits over every read (the per-item means times the number of reads), which changes
    neither the test (a common scale) nor the rates, and keeps every sum an exact integer."""
    sums: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for key, reads in ours.items():
        row = sums[reads[0].cluster]
        row[0] += sum(1 for item in reads if test(item))
        row[1] += sum(1 for item in theirs[key] if test(item))
        row[2] += len(reads)
    clusters = [row for _, row in sorted(sums.items())]
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


def _unstable(reads: Sequence[Item]) -> bool:
    return any(item.predicted != reads[0].predicted for item in reads[1:])


def _stability_pair(
    ours: Mapping[tuple[str, str, int], Sequence[Item]],
    theirs: Mapping[tuple[str, str, int], Sequence[Item]],
    settings: Settings,
) -> dict[str, Any]:
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


def _reading_agreement(rows: Mapping[tuple[str, str, int], Sequence[Item]]) -> dict[str, int]:
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


def multi_read(reads: Sequence[Run], prereg: Prereg) -> dict[str, Any]:
    """The primary split over its reads: per condition the per-read rates, the mean over reads, stability and the
    descriptive numbers; the families F1 (accuracy), F2 (harm) and F3 (stability) with Holm; the sensitivity
    analysis on read 1; and the decisions the pre-registered rules take."""
    settings = prereg.settings
    level = settings.level
    conditions = (prereg.reference, *prereg.baselines)
    k = len(reads)
    rows: dict[str, dict[tuple[str, str, int], list[Item]]] = {}
    for condition in conditions:
        table: dict[tuple[str, str, int], list[Item]] = defaultdict(list)
        for run in reads:
            for item in run.items[condition]:
                table[item.key].append(item)
        rows[condition] = dict(sorted(table.items()))
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
            "mean_accuracy": {"value": mean[0], "ci": [mean[1], mean[2]]},
            "mean_harmful": {"value": mean_harm[0], "ci": [mean_harm[1], mean_harm[2]]},
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
            "selective": selective(flat, level),
            "loss": {
                _ratio_key(r): stats.harm_loss(
                    sum(1 for i in flat if i.early), sum(1 for i in flat if i.harmful), len(flat), r
                )
                for r in settings.loss_ratios
            },
            "cost": _cost(letters, sum(1 for item in flat if item.right)),
            "latency_ms": _latency(letters),
        }
        if condition == prereg.reference:
            summary["reading_agreement"] = _reading_agreement(table)
        tool_use = _tool_use(letter_rows[condition])
        if tool_use is not None:
            summary["tool_use_consistency"] = tool_use
        summaries[condition] = summary
    ours = rows[prereg.reference]
    families: dict[str, dict[str, dict[str, Any]]] = {
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
        },
    }
    for name in ("F1_accuracy", "F2_harm"):
        family = families[name]
        for key, adjusted in zip(
            family, stats.holm([row["signflip"]["p"] for row in family.values()]), strict=True
        ):
            family[key]["holm"] = adjusted
    stability = families["F3_stability"]
    for key, adjusted in zip(stability, stats.holm([row["midp"] for row in stability.values()]), strict=True):
        stability[key]["holm"] = adjusted
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
    return {
        "split": prereg.primary_split,
        "reads": k,
        "items": n,
        "letters": len(first.letters[prereg.reference]),
        "clusters": len(clusters),
        "conditions": summaries,
        "families": families,
        "sensitivity_r1": sensitivity,
        "decisions": _decisions(families, summaries, prereg, n * k),
        "errors": [
            row
            for read, run in enumerate(reads, start=1)
            for row in _error_rows({c: run.items[c] for c in conditions}, read=read)
        ],
    }


def _decisions(
    families: Mapping[str, Mapping[str, Mapping[str, Any]]],
    summaries: Mapping[str, Mapping[str, Any]],
    prereg: Prereg,
    item_reads: int,
) -> dict[str, Any]:
    """The pre-registered decision rules (§6.11), as codes the presenter turns into its sentences."""
    settings = prereg.settings
    alpha, margin = settings.alpha, settings.noninferiority_margin
    accuracy = families["F1_accuracy"]

    def clear(baseline: str) -> bool:
        row = accuracy[_pair_key(prereg.reference, baseline)]
        lo = row["bootstrap"]["lo"]
        return bool(row["holm"] < alpha and lo is not None and lo > 0)

    decisions: dict[str, Any] = {}
    if "llm_only" in prereg.baselines:
        decisions["beats_llm_only"] = "clear" if clear("llm_only") else "no_clear_difference"
    if "llm_rules_text" in prereg.baselines:
        decisions["vs_llm_rules_text"] = "clear" if clear("llm_rules_text") else "level_within_noise"
    for baseline in prereg.noninferior_to:
        boot = accuracy[_pair_key(prereg.reference, baseline)]["bootstrap"]
        if boot["lo"] is not None and boot["lo"] > -margin:
            verdict = "non_inferior"
        elif boot["hi"] is not None and boot["hi"] < 0:
            verdict = "agent_higher" if baseline == TOOL_CONDITION else "baseline_higher"
        else:
            verdict = "cannot_tell"
        decisions[f"vs_{baseline}"] = verdict
    ours = summaries[prereg.reference]
    harmful = sum(row["k"] for row in ours["harmful_per_read"])
    decisions["harmful"] = {"dates": harmful, "reads": item_reads, "none": harmful == 0}
    if "llm_only" in prereg.baselines:
        row = families["F3_stability"][_pair_key(prereg.reference, "llm_only")]
        decisions["more_stable_than_llm_only"] = bool(row["holm"] < alpha and (row["diff"] or 0) < 0)
    recall = ours["selective"]["please_check"]["recall_wrong"]
    decisions["flags_caught"] = {"caught": recall["k"], "wrong": recall["n"]}
    return decisions


def final_analysis(
    prereg: Prereg,
    runs: Sequence[Run],
    *,
    pooled_with: Sequence[Run] = (),
    prereg_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The pre-registered final run: the primary split over its reads, each secondary split, and (exploratory) the
    earlier held-out splits pooled with the primary split's first read."""
    reads, secondary = _assign_reads(prereg, runs)
    settings = prereg.settings
    document: dict[str, Any] = {
        "schema": ANALYSIS_SCHEMA,
        "meta": {
            "kind": FINAL_KIND,
            "date": max(str(run.meta.get("date") or "") for run in reads),
            "model": prereg.model,
            "pre_registered": True,
            "label": "pre-registered",
            "prereg": dict(prereg_record or {}),
            "inputs": [
                run.input_record() for run in (*reads, *_sorted_runs(list(secondary.values())), *pooled_with)
            ],
            "settings": settings.to_dict(),
            "methods": _methods(settings),
        },
        "primary": multi_read(reads, prereg),
        "secondary": {
            split: single_read([run], settings, paired=False) for split, run in sorted(secondary.items())
        },
    }
    if pooled_with:
        pooled = single_read([*pooled_with, reads[0]], settings, paired=False)
        document["exploratory"] = {
            "pooled_held_out": {
                "label": "exploratory: splits recorded with different code, pooled after the results were known",
                "splits": [run.split for run in _sorted_runs([*pooled_with, reads[0]])],
                **pooled,
            }
        }
    return document


def final_from_files(
    prereg_path: Path, paths: Sequence[Path], *, results_dir: Path = RESULTS_DIR
) -> dict[str, Any]:
    """:func:`final_analysis` from a pre-registration file and results files (``pool_with`` read in ``results_dir``)."""
    raw = prereg_path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnalysisError(f"the pre-registration is not JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise AnalysisError("the pre-registration is not a JSON object")
    prereg = parse_prereg(data)
    runs = [read_run(path) for path in paths]
    pooled = [read_run(results_dir / name) for name in prereg.pool_with]
    record = {"file": prereg_path.name, "sha256": hashlib.sha256(raw).hexdigest()}
    return final_analysis(prereg, runs, pooled_with=pooled, prereg_record=record)


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
        for key, row in pairs.items():
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
    parser.add_argument("--date", help="the re-analysis's date for --write (default: today)")
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
            document = final_from_files(args.prereg, args.results, results_dir=args.results_dir)
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
    "FINAL_KIND",
    "HELD_OUT_AS_RECORDED",
    "PREREG_SCHEMA",
    "REANALYSIS_KIND",
    "AnalysisError",
    "Item",
    "Letter",
    "Prereg",
    "Run",
    "Settings",
    "condition_summary",
    "default_prereg_analysis",
    "final_analysis",
    "final_from_files",
    "load_run",
    "main",
    "multi_read",
    "output_name",
    "paired_one_read",
    "parse_prereg",
    "rate",
    "read_run",
    "reanalyse",
    "render",
    "selective",
    "single_read",
]


if __name__ == "__main__":
    raise SystemExit(main())
