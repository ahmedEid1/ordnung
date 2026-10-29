"""The Ask benchmark's household group: does Ask say whose a number is? (ADR 0025)

**The ledger** is a copy of the base ledger with one person added to the household, *Alex Rivera*, and two of
the sample life's letters filed for him through Ordnung's own household code (no model call): the health
insurer's contribution notice and the passport (:data:`FILED`). The numbers those two letters show — the health
insurance number, the passport's number and its expiry — stand on no letter of the person's own (the truth's
references and the ledger's agree; a test checks both), so whose each is has one answer: Alex's. The person's
tax ID, on their tax assessment, stays theirs. His id is derived from his name (:data:`MEMBER_ID`), so the
ledger, its fingerprint and the recordings' keys are the same on every run.

**The questions** are hand-written (:func:`household_questions`). Their gold comes from the sample life's truth
and the filing, never from Ordnung's output: Alex's numbers and passport expiry, the person's tax ID — and where
the person has none of their own (their health insurance number, their passport), an answer that leads with
saying so.

**Scoring** (:func:`evals.ask.score.score_household`): an answer passes when it states its gold (a number
compared without spaces, a date read by :mod:`evals.ask.parse`) or leads with saying the person has none of
their own, and every sentence that states a value of Alex's names him while no sentence that states the
person's own tax ID does. A list item counts as naming him when the line that leads into its list does. The
group is reported apart (``summary["household"]``): the headline numbers keep counting the other questions.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from evals.ask.ledger import SampleLife, copy_database
from evals.ask.questions import TruthDoc, load_truth
from evals.metrics import DEFAULT_RESAMPLES, DEFAULT_SEED, bootstrap_ratio
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.ids import content_id
from ordnung.secretary import household

if TYPE_CHECKING:
    from evals.ask.score import Scored

#: The person of the household the group adds, and his id (derived from his name: the same on every run).
MEMBER_NAME = "Alex Rivera"
MEMBER_ID = content_id("hhm", "evals.ask household", MEMBER_NAME)
#: The letters filed for him: the health insurer's contribution notice and the passport.
FILED = ("krankenkasse_beitragsbescheid", "reisepass")
#: The truth's labels of the numbers the questions ask about, by letter.
HEALTH_NUMBER = ("krankenkasse_beitragsbescheid", "Versicherten-Nr.")
PASSPORT_NUMBER = ("reisepass", "Passport No.")
TAX_ID = ("steuerbescheid_2025", "IdNr.")
CATEGORY = "household"


@dataclass(frozen=True)
class HouseholdTruth:
    """What the truth says of the household ledger: Alex's numbers and dates, and the person's own numbers."""

    member_values: tuple[str, ...]
    member_dates: tuple[date, ...]
    own_values: tuple[str, ...]


@dataclass(frozen=True)
class HouseholdQuestion:
    """One question of the household group: the values its answer must state (numbers, compared without
    spaces; dates), or ``none_of_own``: the person has none of their own, so the answer leads with saying so."""

    id: str
    text: str
    values: tuple[str, ...] = ()
    dates: tuple[date, ...] = ()
    none_of_own: bool = False

    @property
    def cluster(self) -> str:
        return self.id

    def gold(self) -> dict[str, Any]:
        return {
            "values": list(self.values),
            "dates": [day.isoformat() for day in self.dates],
            "none_of_own": self.none_of_own,
        }


def compact(text: str) -> str:
    """``text`` without white space (a number as it may be written with or without spaces)."""
    return "".join(text.split())


def _reference(truth: Mapping[str, TruthDoc], slug: str, label: str) -> str:
    return compact(next(ref["value"] for ref in truth[slug].truth["references"] if ref["label"] == label))


def _expiry(truth: Mapping[str, TruthDoc], slug: str) -> date:
    return next(
        date.fromisoformat(item["expected_due"])
        for item in truth[slug].truth["items"]
        if item["kind"] == "expiry"
    )


def household_truth(truth: Mapping[str, TruthDoc] | None = None) -> HouseholdTruth:
    """Alex's numbers (the health insurance and passport numbers) and his passport's expiry, and the person's
    own tax ID — read from the sample life's truth."""
    loaded = truth if truth is not None else load_truth()
    return HouseholdTruth(
        member_values=(_reference(loaded, *HEALTH_NUMBER), _reference(loaded, *PASSPORT_NUMBER)),
        member_dates=(_expiry(loaded, PASSPORT_NUMBER[0]),),
        own_values=(_reference(loaded, *TAX_ID),),
    )


def household_questions(truth: Mapping[str, TruthDoc] | None = None) -> list[HouseholdQuestion]:
    """The five questions, with gold from the truth and the filing."""
    loaded = truth if truth is not None else load_truth()
    health, passport = _reference(loaded, *HEALTH_NUMBER), _expiry(loaded, PASSPORT_NUMBER[0])
    return [
        HouseholdQuestion("hh-my-health-number", "What is my health insurance number?", none_of_own=True),
        HouseholdQuestion(
            "hh-alex-health-number", "What is Alex's health insurance number?", values=(health,)
        ),
        HouseholdQuestion("hh-alex-passport", "When does Alex's passport expire?", dates=(passport,)),
        HouseholdQuestion("hh-my-passport", "When does my passport expire?", none_of_own=True),
        HouseholdQuestion("hh-my-tax-id", "What is my tax ID?", values=(_reference(loaded, *TAX_ID),)),
    ]


@dataclass(frozen=True)
class _Member:
    """Alex as a change of the household's list sends him (``household.MemberLike``), with his own id."""

    id: str | None
    name: str
    signs: bool = True


def build_household(base: Path, target: Path, life: SampleLife) -> Path:
    """A copy of the base ledger's database in ``target`` with Alex in the household and :data:`FILED` filed for
    him, by the household code the app's Settings and letter pages use."""
    copy_database(base, target)
    store = Store.open(Paths(target))
    try:
        household.change(store, base=household.version([]), members=[_Member(MEMBER_ID, MEMBER_NAME)])
        household.file(store, {life.doc_ids[slug]: MEMBER_ID for slug in FILED})
    finally:
        store.close()
    return target


def summarise_household(
    scored: Sequence[Scored], *, seed: int = DEFAULT_SEED, resamples: int = DEFAULT_RESAMPLES
) -> dict[str, Any]:
    """The household block of the summary: how many questions, how many got no answer, the share whose answer
    gives its gold and says whose each number is (``attribution``, final and raw, with 95 % intervals) and
    what they cost (API-equivalent)."""

    def rate(correct: Callable[[Scored], bool | None]) -> dict[str, Any]:
        units = [(s.cluster, float(bool(correct(s))), 1.0) for s in scored]
        return bootstrap_ratio(units, resamples=resamples, seed=seed).to_dict()

    return {
        "questions": len(scored),
        "not_answered": sum(1 for s in scored if not s.answered),
        "attribution": rate(lambda s: s.correct_final),
        "attribution_raw": rate(lambda s: s.correct_raw),
        "cost_usd": math.fsum(s.cost_usd for s in scored if s.answered),
    }
