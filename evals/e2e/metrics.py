"""The end-to-end numbers: verdicts (:mod:`evals.e2e.check`) summed per split, pooled, per modality and family.

**Pooled** is every split of the run but ``dev`` (the split prompts were tuned on); ``all`` is every letter run
(the CI gates read it). A rate is the benchmark's estimate (:func:`evals.metrics.bootstrap_ratio`): ``k / n`` with a
95 % bootstrap interval over letters, a photo resampled with the PDF it was rendered from (``Entry.cluster``), the
Wilson interval over letters at 0 or 1. Imports nothing of the app.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from evals.e2e.check import DRAFT_ELEMENTS, LetterVerdict, ObligationVerdict
from evals.metrics import DEFAULT_RESAMPLES, DEFAULT_SEED, bootstrap_ratio

#: The split the prompts were tuned on: reported apart, never pooled.
TUNED_SPLIT = "dev"

Unit = tuple[str, float, float]


def _obligation_id(letter: LetterVerdict, obligation: ObligationVerdict) -> str:
    return f"{letter.entry_id}#{obligation.index}"


class _Rates:
    def __init__(self, *, seed: int, resamples: int) -> None:
        self.seed = seed
        self.resamples = resamples

    def __call__(self, units: Sequence[Unit]) -> dict[str, Any]:
        return bootstrap_ratio(units, seed=self.seed, resamples=self.resamples).to_dict()

    def obligations(
        self,
        letters: Sequence[LetterVerdict],
        hit: Callable[[ObligationVerdict], bool],
        counted: Callable[[ObligationVerdict], bool] = lambda _o: True,
    ) -> dict[str, Any]:
        units = []
        for letter in letters:
            chosen = [o for o in letter.obligations if counted(o)]
            units.append((letter.cluster, float(sum(1 for o in chosen if hit(o))), float(len(chosen))))
        return self(units)

    def letters(
        self, letters: Sequence[LetterVerdict], hit: Callable[[LetterVerdict], bool]
    ) -> dict[str, Any]:
        return self([(letter.cluster, float(hit(letter)), 1.0) for letter in letters])


def _lead_days(letters: Iterable[LetterVerdict]) -> dict[str, Any]:
    leads = [o.lead_days for letter in letters for o in letter.obligations if o.lead_days is not None]
    if not leads:
        return {"min": None, "median": None, "max": None}
    return {"min": min(leads), "median": float(statistics.median(leads)), "max": max(leads)}


def _parity(letters: Sequence[LetterVerdict]) -> dict[str, Any]:
    judged = [(letter, o) for letter in letters for o in letter.obligations if o.parity is not None]
    return {
        "k": sum(1 for _, o in judged if o.parity),
        "n": len(judged),
        "differ": [_obligation_id(letter, o) for letter, o in judged if not o.parity],
    }


def _scam(letters: Sequence[LetterVerdict], rate: _Rates) -> dict[str, Any]:
    scams = [letter for letter in letters if letter.scam_gold]
    genuine = [letter for letter in letters if not letter.scam_gold]
    set_aside = [
        (letter, o)
        for letter in genuine
        for o in letter.obligations
        if o.not_reminded is not None and o.not_reminded.startswith("set_aside:")
    ]
    return {
        "scam_letters": len(scams),
        "scam_idea": rate.letters(scams, lambda letter: letter.scam_idea),
        "kept_off_the_calendar": rate.letters(scams, lambda letter: letter.calendar_events == 0),
        "in_the_calendar": [
            {"entry_id": letter.entry_id, "events": letter.calendar_events}
            for letter in scams
            if letter.calendar_events
        ],
        "without_scam_idea": [letter.entry_id for letter in scams if not letter.scam_idea],
        "genuine_letters": len(genuine),
        "false_scam_idea": rate.letters(genuine, lambda letter: letter.scam_idea),
        "false_scam_idea_ids": [letter.entry_id for letter in genuine if letter.scam_idea],
        "set_aside_obligations": len(set_aside),
        "set_aside_by_cause": dict(sorted(Counter(o.not_reminded or "" for _, o in set_aside).items())),
    }


def _drafts(letters: Sequence[LetterVerdict], rate: _Rates) -> dict[str, Any]:
    asked = [letter for letter in letters if letter.draft is not None]
    drafted = [letter for letter in asked if letter.draft is not None and not letter.draft.refused]
    elements: dict[str, dict[str, Any]] = {}
    for element in DRAFT_ELEMENTS:
        judged = [
            letter
            for letter in drafted
            if letter.draft is not None and letter.draft.elements.get(element) is not None
        ]
        failed = [
            letter.entry_id
            for letter in judged
            if letter.draft is not None and letter.draft.elements.get(element) is False
        ]
        elements[element] = {"k": len(judged) - len(failed), "n": len(judged), "failed": failed}
    own_failed: Counter[str] = Counter(
        check for letter in drafted if letter.draft is not None for check in letter.draft.own_checks_failed
    )
    nones = [letter for letter in letters if letter.objection_on_none is not None]
    return {
        "letters": len(asked),
        "refused": [letter.entry_id for letter in asked if letter.draft is not None and letter.draft.refused],
        "complete": rate.letters(asked, lambda letter: letter.draft is not None and letter.draft.complete),
        "elements": elements,
        "own_checks_all_pass": {
            "k": sum(
                1 for letter in drafted if letter.draft is not None and not letter.draft.own_checks_failed
            ),
            "n": len(drafted),
        },
        "own_checks_failed": dict(sorted(own_failed.items())),
        "objection_refused_without_remedy": rate.letters(
            nones, lambda letter: letter.objection_on_none == "refused"
        ),
        "drafted_without_remedy": [
            letter.entry_id for letter in nones if letter.objection_on_none != "refused"
        ],
    }


def block(letters: Sequence[LetterVerdict], rate: _Rates) -> dict[str, Any]:
    """Every number for a group of letters."""
    obligations = [o for letter in letters for o in letter.obligations]
    return {
        "letters": len(letters),
        "obligations": len(obligations),
        "parity": _parity(letters),
        "exact": rate.obligations(letters, lambda o: o.exact),
        "reminded_in_time": rate.obligations(letters, lambda o: o.reminded),
        "lead_days": _lead_days(letters),
        "late_reminders": [
            _obligation_id(letter, o) for letter in letters for o in letter.obligations if o.late_reminder
        ],
        "not_reminded": dict(sorted(Counter(o.not_reminded for o in obligations if o.not_reminded).items())),
        "morning_note": rate.obligations(letters, lambda o: o.morning_note),
        "idea_right": rate.obligations(letters, lambda o: bool(o.idea_right), lambda o: o.idea_due),
        "scam": _scam(letters, rate),
        "drafts": _drafts(letters, rate),
    }


def small_block(letters: Sequence[LetterVerdict], rate: _Rates) -> dict[str, Any]:
    """The reminder numbers alone, for a modality or a family."""
    obligations = [o for letter in letters for o in letter.obligations]
    return {
        "letters": len(letters),
        "obligations": len(obligations),
        "exact": rate.obligations(letters, lambda o: o.exact),
        "reminded_in_time": rate.obligations(letters, lambda o: o.reminded),
        "not_reminded": dict(sorted(Counter(o.not_reminded for o in obligations if o.not_reminded).items())),
        "morning_note": rate.obligations(letters, lambda o: o.morning_note),
    }


def pooled_splits(splits: Iterable[str]) -> list[str]:
    """The splits pooled for the headline: every split run but the tuned one."""
    return [split for split in splits if split != TUNED_SPLIT]


def summarise(
    verdicts: Sequence[LetterVerdict], *, seed: int = DEFAULT_SEED, resamples: int = DEFAULT_RESAMPLES
) -> dict[str, Any]:
    """The numbers of a run: ``all``, ``pooled``, ``by_split``, ``by_modality`` and ``by_family`` (the last two
    pooled)."""
    rate = _Rates(seed=seed, resamples=resamples)
    splits = list(dict.fromkeys(verdict.split for verdict in verdicts))
    pooled_names = set(pooled_splits(splits))
    pooled = [verdict for verdict in verdicts if verdict.split in pooled_names]
    modalities = sorted({verdict.modality for verdict in pooled}, key=lambda name: name != "text")
    families = sorted({verdict.family for verdict in pooled})
    return {
        "all": block(verdicts, rate),
        "pooled": block(pooled, rate),
        "by_split": {split: block([v for v in verdicts if v.split == split], rate) for split in splits},
        "by_modality": {
            name: small_block([v for v in pooled if v.modality == name], rate) for name in modalities
        },
        "by_family": {name: small_block([v for v in pooled if v.family == name], rate) for name in families},
    }


def set_aside(verdicts: Iterable[LetterVerdict]) -> list[dict[str, Any]]:
    """Every genuine obligation the app set aside, by id, with the cause and the app's scam verdict as codes."""
    return [
        {
            "entry_id": letter.entry_id,
            "split": letter.split,
            "family": letter.family,
            "variant": letter.variant,
            "modality": letter.modality,
            "index": o.index,
            "kind": o.kind,
            "nature": o.nature,
            "date_right": o.exact,
            "cause": o.not_reminded,
            "scam_reasons": list(letter.scam_reasons),
            "scam_idea": letter.scam_idea,
        }
        for letter in verdicts
        for o in letter.obligations
        if o.not_reminded is not None and o.not_reminded.startswith("set_aside:")
    ]
