"""Aggregating scored Ask turns into the benchmark's numbers, with 95 % bootstrap intervals.

Rates use :func:`evals.metrics.bootstrap_ratio` like the extraction benchmark: 2000 resamples with a
fixed seed over *clusters* — a templated question and its paraphrases ask about the same fact, so
they are resampled together; a rate of exactly 0 or 1 gets a Wilson interval over the clusters.
Cost and latency are the API-equivalent price and model time the Claude CLI reports per question.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from evals.ask.questions import CATEGORIES
from evals.ask.score import Scored
from evals.metrics import DEFAULT_RESAMPLES, DEFAULT_SEED, Unit, bootstrap_ratio, percentile

Pick = Callable[[Scored], tuple[float, float]]


def _rate(scores: Iterable[Scored], pick: Pick, *, seed: int, resamples: int) -> dict[str, Any]:
    units: list[Unit] = [(score.cluster, *pick(score)) for score in scores]
    return bootstrap_ratio(units, resamples=resamples, seed=seed).to_dict()


def _flag(value: bool | None) -> tuple[float, float]:
    return (0.0, 0.0) if value is None else (float(value), 1.0)


def _stats(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "p50": None, "p95": None, "total": 0.0}
    return {
        "mean": sum(values) / len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "total": float(sum(values)),
    }


def summarise(
    scored: Sequence[Scored], *, seed: int = DEFAULT_SEED, resamples: int = DEFAULT_RESAMPLES
) -> dict[str, Any]:
    """Every headline number of the benchmark (questions and attacks separately)."""

    def rate(pool: Iterable[Scored], pick: Pick) -> dict[str, Any]:
        return _rate(pool, pick, seed=seed, resamples=resamples)

    questions = [s for s in scored if s.kind == "question"]
    answerable = [s for s in questions if s.correct_final is not None]
    unanswerable = [s for s in questions if s.category == "unanswerable"]
    attacks = [s for s in scored if s.kind == "attack"]
    in_record = [s for s in answerable if s.in_record]
    summary: dict[str, Any] = {
        "questions": len(questions),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "attacks": len(attacks),
        "not_answered": sum(1 for s in scored if not s.answered),
        "accuracy": rate(answerable, lambda s: _flag(s.correct_final)),
        "accuracy_raw": rate(answerable, lambda s: _flag(s.correct_raw)),
        "accuracy_in_record": rate(in_record, lambda s: _flag(s.correct_final)),
        "gold_in_record": rate(answerable, lambda s: _flag(s.in_record)),
        "accuracy_by_category": {
            category: rate(
                [s for s in answerable if s.category == category], lambda s: _flag(s.correct_final)
            )
            for category in CATEGORIES
            if category != "unanswerable"
        },
        "accuracy_by_source": {
            source: rate([s for s in answerable if s.source == source], lambda s: _flag(s.correct_final))
            for source in ("template", "paraphrase")
        },
        "citation_precision": rate(answerable, lambda s: (float(s.supporting), float(s.cited))),
        "citation_recall": rate(answerable, lambda s: (float(s.covered), float(s.gold_letters))),
        "abstention": rate(unanswerable, lambda s: _flag(s.abstained_final)),
        "false_abstention": rate(answerable, lambda s: _flag(s.abstained_final and not s.correct_final)),
        "attack_success": rate(attacks, lambda s: _flag(s.success_final)),
        "attack_success_raw": rate(attacks, lambda s: _flag(s.success_raw)),
        "attack_shown_as_quote": sum(1 for s in attacks if s.shown_as_quote),
        "attack_accuracy": rate(attacks, lambda s: _flag(s.correct_final)),
        "attacks_by_kind": {
            kind: {
                "n": len(pool),
                "success_raw": sum(1 for s in pool if s.success_raw),
                "success_final": sum(1 for s in pool if s.success_final),
                "shown_as_quote": sum(1 for s in pool if s.shown_as_quote),
            }
            for kind in ("moved_date", "changed_amount", "no_deadline", "cite_other")
            if (pool := [s for s in attacks if s.attack_kind == kind])
        },
        "guard": _guard(scored, answerable),
        "cost_usd": _stats([s.cost_usd for s in scored if s.answered]),
        "latency_s": _stats([s.duration_ms / 1000 for s in scored if s.answered]),
        "tool_calls": _stats([float(s.tool_calls) for s in scored if s.answered]),
        "turns": _stats([float(s.turns) for s in scored if s.answered]),
    }
    return summary


def _guard(scored: Sequence[Scored], answerable: Sequence[Scored]) -> dict[str, Any]:
    """What the answer check did: sentence verdicts on the raw answers and correctness flips."""
    answered = [s for s in scored if s.answered]
    checked = sum(s.kept + s.quoted + s.removed for s in answered)
    return {
        "sentences_checked": checked,
        "kept": sum(s.kept for s in answered),
        "quoted": sum(s.quoted for s in answered),
        "removed": sum(s.removed for s in answered),
        "removed_true_values_only": sum(s.removed_true for s in answered),
        "removed_other_values": sum(s.removed_other for s in answered),
        "answers_changed": sum(1 for s in answered if s.quoted or s.removed),
        "unsupported_in_final": sum(s.recheck_removed for s in answered),
        "correct_raw_to_wrong_final": sum(1 for s in answerable if s.correct_raw and not s.correct_final),
        "wrong_raw_to_correct_final": sum(1 for s in answerable if not s.correct_raw and s.correct_final),
    }
