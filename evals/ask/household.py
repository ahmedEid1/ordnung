"""The Ask benchmark's household group: does Ask say whose a number is? (ADR 0025)

**The ledger** is a copy of the base ledger with one person added to the household, *Alex Rivera*, and two letters
that are his filed for him through Ordnung's own household code (no model call): the health insurer's
contribution notice and the passport (:data:`FILED`). In the sample life those two letters are the person's, so
the fixture first makes them Alex's (:func:`readdress`): on every page, in Ordnung's reading of them and in their
case's title, the person's given name becomes his (they share the surname) and the person's health insurance
number and passport number become his own (:data:`MEMBER_NUMBERS`, with the passport's machine-readable lines'
check digits worked out again). Nothing else of them changes: the sender, the dates, the amounts and the to-dos are
the letters' own. His numbers stand on no letter of the person's, and the person's numbers those letters showed
are left on none (a test checks both), so whose each number is has one answer: Alex's. The person's tax ID, on
their tax assessment, stays theirs. His id is derived from his name (:data:`MEMBER_ID`), so the ledger, its
fingerprint and the recordings' keys are the same on every run.

**The questions** are hand-written (:func:`household_questions`). Their gold is the household ledger's truth — the
sample life's truth and what the fixture wrote on Alex's letters — never Ordnung's output: Alex's numbers
(:data:`MEMBER_NUMBERS`) and his passport's expiry (the truth's), the person's tax ID (the truth's) — and where the
person has none of their own (their health insurance number, their passport), an answer that leads with saying
so.

**Scoring** (:func:`evals.ask.score.score_household`): an answer passes when it states its gold (a number
compared without spaces, a date read by :mod:`evals.ask.parse`) or leads with saying the person has none of
their own, and every sentence that states a value of Alex's names him while no sentence that states the
person's own tax ID does. A list item counts as naming him when the line that leads into its list does. The
group is reported apart (``summary["household"]``): the headline numbers keep counting the other questions.
"""

from __future__ import annotations

import contextlib
import math
import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from evals.ask.ledger import LedgerError, SampleLife, copy_database
from evals.ask.questions import TruthDoc, ValueKind, load_truth
from evals.metrics import DEFAULT_RESAMPLES, DEFAULT_SEED, bootstrap_ratio
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.demo.loader import DB_NAME
from ordnung.ids import content_id
from ordnung.secretary import household

if TYPE_CHECKING:
    from evals.ask.score import Scored

#: The person of the household the group adds, and his id (derived from his name: the same on every run).
MEMBER_NAME = "Alex Rivera"
MEMBER_ID = content_id("hhm", "evals.ask household", MEMBER_NAME)
#: The letters filed for him, made his first (:func:`readdress`): the health insurer's contribution notice and the
#: passport.
FILED = ("krankenkasse_beitragsbescheid", "reisepass")
#: The truth's labels of the numbers the questions ask about, by letter.
HEALTH_NUMBER = ("krankenkasse_beitragsbescheid", "Versicherten-Nr.")
PASSPORT_NUMBER = ("reisepass", "Passport No.")
TAX_ID = ("steuerbescheid_2025", "IdNr.")
#: Alex's own numbers, which his letters show in place of the person's: a Krankenversichertennummer whose check
#: digit is right (§ 290 SGB V) and a passport number of the same shape as the person's.
MEMBER_NUMBERS: Mapping[tuple[str, str], str] = {
    HEALTH_NUMBER: "M472059139",
    PASSPORT_NUMBER: "C4703958",
}
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
    spaces; dates), or ``none_of_own``: the person has none of their own, so the answer leads with saying so and
    states no value of the kind it ``asks`` for (:func:`evals.ask.score.abstains`; else its gold's kinds)."""

    id: str
    text: str
    values: tuple[str, ...] = ()
    dates: tuple[date, ...] = ()
    none_of_own: bool = False
    asks: tuple[ValueKind, ...] = ()

    def __post_init__(self) -> None:
        if not self.asks:
            kinds: list[ValueKind] = []
            if self.values:
                kinds.append("number")
            if self.dates:
                kinds.append("date")
            object.__setattr__(self, "asks", tuple(kinds))

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
    """Alex's numbers (the health insurance and passport numbers his letters show, :data:`MEMBER_NUMBERS`) and his
    passport's expiry, and the person's own tax ID — the expiry and the tax ID read from the sample life's truth."""
    loaded = truth if truth is not None else load_truth()
    return HouseholdTruth(
        member_values=(compact(MEMBER_NUMBERS[HEALTH_NUMBER]), compact(MEMBER_NUMBERS[PASSPORT_NUMBER])),
        member_dates=(_expiry(loaded, PASSPORT_NUMBER[0]),),
        own_values=(_reference(loaded, *TAX_ID),),
    )


def household_questions(truth: Mapping[str, TruthDoc] | None = None) -> list[HouseholdQuestion]:
    """The five questions, with gold from the household ledger's truth."""
    loaded = truth if truth is not None else load_truth()
    health, passport = compact(MEMBER_NUMBERS[HEALTH_NUMBER]), _expiry(loaded, PASSPORT_NUMBER[0])
    return [
        HouseholdQuestion(
            "hh-my-health-number", "What is my health insurance number?", none_of_own=True, asks=("number",)
        ),
        HouseholdQuestion(
            "hh-alex-health-number", "What is Alex's health insurance number?", values=(health,)
        ),
        HouseholdQuestion("hh-alex-passport", "When does Alex's passport expire?", dates=(passport,)),
        HouseholdQuestion(
            "hh-my-passport", "When does my passport expire?", none_of_own=True, asks=("date",)
        ),
        HouseholdQuestion("hh-my-tax-id", "What is my tax ID?", values=(_reference(loaded, *TAX_ID),)),
    ]


@dataclass(frozen=True)
class _Member:
    """Alex as a change of the household's list sends him (``household.MemberLike``), with his own id."""

    id: str | None
    name: str
    signs: bool = True


def build_household(base: Path, target: Path, life: SampleLife) -> Path:
    """A copy of the base ledger's database in ``target`` with Alex in the household and :data:`FILED`, made his
    (:func:`readdress`), filed for him by the household code the app's Settings and letter pages use."""
    copy_database(base, target)
    letters = [life.doc_ids[slug] for slug in FILED]
    stamps = _stamps(target, letters)
    store = Store.open(Paths(target))
    try:
        for slug, doc_id in zip(FILED, letters, strict=True):
            mine = {label: number for (of, label), number in MEMBER_NUMBERS.items() if of == slug}
            readdress(store, doc_id, numbers=mine)
        household.change(store, base=household.version([]), members=[_Member(MEMBER_ID, MEMBER_NAME)])
        household.file(store, dict.fromkeys(letters, MEMBER_ID))
    finally:
        store.close()
    _restore_stamps(target, stamps)
    return target


def _stamps(target: Path, doc_ids: Sequence[str]) -> list[tuple[str, str, str]]:
    """``(table, id, updated_at)`` of the letters and their cases, as the base ledger set them (the start of
    their day, :func:`evals.ask.ledger.build_base`)."""
    marks = ", ".join("?" * len(doc_ids))
    with contextlib.closing(sqlite3.connect(target / DB_NAME)) as db:
        rows = db.execute(f"SELECT 'documents', id, updated_at FROM documents WHERE id IN ({marks})", doc_ids)
        cases = db.execute(
            f"SELECT 'cases', id, updated_at FROM cases WHERE id IN "
            f"(SELECT case_id FROM documents WHERE id IN ({marks}))",
            doc_ids,
        )
        return [*rows.fetchall(), *cases.fetchall()]


def _restore_stamps(target: Path, stamps: Sequence[tuple[str, str, str]]) -> None:
    """Put back the stamps :func:`readdress` moved to the time of the run: listings break ties by them, so a
    tool's answer — and with it a recorded one — would otherwise depend on the hour of the run."""
    with contextlib.closing(sqlite3.connect(target / DB_NAME)) as db, db:
        for table, row_id, updated_at in stamps:
            db.execute(f"UPDATE {table} SET updated_at = ? WHERE id = ?", (updated_at, row_id))


def mrz_check_digit(field: str) -> str:
    """The check digit of a field of a passport's machine-readable lines (ICAO Doc 9303, part 3): the sum of
    each character's value (a digit its own, A–Z 10–35, the filler ``<`` 0) times 7, 3, 1, 7, 3, 1 …, modulo 10."""
    total = 0
    for index, char in enumerate(field):
        value = 0 if char == "<" else int(char) if char.isdigit() else ord(char) - ord("A") + 10
        total += value * (7, 3, 1)[index % 3]
    return str(total % 10)


_MRZ = re.compile(r"(?=[A-Z0-9<]*<)[A-Z0-9<]{30,}")


def _machine_line(line: str, given: tuple[str, str], numbers: Mapping[str, str]) -> str:
    """A passport's machine-readable line (ICAO Doc 9303, TD3) with the given name or the passport number
    replaced: the name line keeps its length (fillers taken off or added at its end); the number line gets the
    number's and the composite check digit worked out again (the composite covers the number, birth date and
    expiry with their check digits and the optional data)."""
    old, new = given[0].upper(), given[1].upper()
    if line.startswith("P"):
        named = re.sub(rf"(?<=<<){re.escape(old)}(?=<|$)", new, line)
        cut = named[len(line) :]
        if cut.strip("<"):
            raise LedgerError("The new given name does not fit the passport's name line.")
        return named[: len(line)].ljust(len(line), "<")
    for number, replacement in numbers.items():
        field = number.ljust(9, "<")
        if line.startswith(field) and len(replacement) <= 9:
            head = replacement.ljust(9, "<")
            line = head + mrz_check_digit(head) + line[10:]
            return line[:-1] + mrz_check_digit(line[0:10] + line[13:20] + line[21:-1])
    return line


def _swapped(text: str, given: tuple[str, str], numbers: Mapping[str, str]) -> str:
    """``text`` with the person's given name (as written, or in capitals) and their numbers (as written, with or
    without spaces) replaced by Alex's; a passport's machine-readable lines by :func:`_machine_line`."""
    lines = []
    for line in text.split("\n"):
        if _MRZ.fullmatch(line):
            lines.append(_machine_line(line, given, numbers))
            continue
        for number, replacement in numbers.items():
            line = re.sub(r"\s*".join(map(re.escape, number)), replacement, line)
        for old, new in ((given[0], given[1]), (given[0].upper(), given[1].upper())):
            line = re.sub(rf"\b{re.escape(old)}\b", new, line)
        lines.append(line)
    return "\n".join(lines)


def _swapped_value(value: Any, swap: Callable[[str], str]) -> Any:
    if isinstance(value, str):
        return swap(value)
    if isinstance(value, list):
        return [_swapped_value(item, swap) for item in value]
    if isinstance(value, dict):
        return {key: _swapped_value(item, swap) for key, item in value.items()}
    return value


def readdress(store: Store, doc_id: str, *, numbers: Mapping[str, str]) -> None:
    """Make one of the person's letters Alex's: on its pages, in Ordnung's reading of it (the record, the stored
    reading and the letter's text kept beside it, as the reading pipeline writes it) and in its case's title, the
    person's given name becomes his, and each reference labelled as in ``numbers`` (label → his number) shows
    his number. He shares the person's surname, so it stays. Nothing else changes."""
    person, member = (store.get_profile().name or "").split(), MEMBER_NAME.split()
    if not person or person[-1] != member[-1]:
        raise LedgerError(
            f"{MEMBER_NAME} must share the person's surname for the letters to be re-addressed."
        )
    document = store.get_document(doc_id)
    if document is None:
        raise LedgerError(f"The ledger has no document {doc_id} to re-address.")
    olds = {ref.label: compact(ref.value) for ref in document.references}
    if missing := set(numbers) - set(olds):
        raise LedgerError(f"{doc_id} shows no {', '.join(sorted(missing))}.")
    swaps = {olds[label]: compact(number) for label, number in numbers.items()}

    def swap(text: str) -> str:
        return _swapped(text, (person[0], member[0]), swaps)

    for page in store.list_pages(doc_id):
        store.set_page_text(doc_id, page.page, swap(page.text), page.text_source)
    record = document.model_dump(mode="json")
    changed = {key: new for key, value in record.items() if (new := _swapped_value(value, swap)) != value}
    reading = store.get_extraction(doc_id)
    if reading is not None:
        changed["extraction"] = type(reading).model_validate(
            _swapped_value(reading.model_dump(mode="json"), swap)
        )
    store.update_document(doc_id, **changed, text=store.get_document_text(doc_id))
    case = store.get_case(document.case_id) if document.case_id else None
    if case is not None and case.title:
        store.update_case(case.id, title=swap(case.title))


def summarise_household(
    scored: Sequence[Scored], *, seed: int = DEFAULT_SEED, resamples: int = DEFAULT_RESAMPLES
) -> dict[str, Any]:
    """The household block of the summary: how many questions, how many got no answer, the share whose answer
    gives its gold and says whose each number is (``attribution``, final and raw, with 95 % intervals), how many
    final answers call a date still open passed (``harmful``) and what they cost (API-equivalent)."""

    def rate(correct: Callable[[Scored], bool | None]) -> dict[str, Any]:
        units = [(s.cluster, float(bool(correct(s))), 1.0) for s in scored]
        return bootstrap_ratio(units, resamples=resamples, seed=seed).to_dict()

    return {
        "questions": len(scored),
        "not_answered": sum(1 for s in scored if not s.answered),
        "attribution": rate(lambda s: s.correct_final),
        "attribution_raw": rate(lambda s: s.correct_raw),
        "harmful": sum(1 for s in scored if s.called_passed_final),
        "cost_usd": math.fsum(s.cost_usd for s in scored if s.answered),
    }
