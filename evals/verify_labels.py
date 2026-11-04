"""Independent re-check of the benchmark's ground truth (see evals/dataset/VERIFICATION.md).

    .venv/bin/python evals/verify_labels.py                  # checks evals/dataset
    .venv/bin/python evals/verify_labels.py --dataset /tmp/x
    .venv/bin/python -m evals.verify_labels --require-facts  # a final split without its facts.json is a problem

Deliberately shares no code with the generator (``evals/gen``) or the product (``ordnung.rules``):
dates are recomputed with a small date calculator built on ``datetime`` and the ``holidays`` package, from
facts read off each letter. For dev, test, holdout, holdout2 and holdout3 those facts were read by hand
(``FACTS`` below). For the final splits (holdout4, newkinds) they come from the blind audit, in
``evals/dataset/<split>/facts.json``, written in the grammar of ``evals/dataset/FACTS.md``; each fact names its
source. Until a final split has that file its dates are not re-derived, and the report says so. Checks:

1. every non-null expected date (items, optional items, contract term end / cancel-by) equals the
   independent recomputation; for letters without a stated Land the date must be identical under all
   16 Land holiday calendars; for letters with a Land, ``region_sensitive`` and
   ``due_if_region_ignored`` must match the nationwide-holidays-only result; no label may change when
   holidays of only some municipalities (Mariä Himmelfahrt in BY, Fronleichnam in SN/TH) are counted;
2. 'ambiguous' and null labels are exactly where the letter is ambiguous / undatable; each ambiguous
   reading is a working day and not before the letter's today (for a final split's letter: after its
   ``valid_until``), and a final split's ambiguous fact holds exactly the label's candidates (an item's
   ``candidates``; a contract slot's under its name in the contract's ``candidates``); a fact's
   ``conflicting`` dates are among the label's candidates, and the label is the earliest of them;
3. the PDF text states what the truth claims (sender, document date, references, amounts, remedy,
   stated dates);
4. no deadline-bearing sentence appears verbatim in letters of two splits (dev, test, holdout, holdout2,
   holdout3, holdout4, newkinds);
5. photo entries share the truth of a one-page source PDF;
6. no hand-read Land VwVfG deemed-delivery label counts from a posting day on which its Land did not count the 4th
   day, nor comes from Hessen, a Land without a verified text or no Land (``remedy`` counts 4 days from 2025-01-01
   in every Land, so it cannot catch that);
7. a final split's letter is read on its ``final_day``, and every scored date (with an ambiguous item's
   candidates), contract date (with an ambiguous slot's candidates) and appointment lies after its ``valid_until``;
8. the conventions a final split's facts apply exist in the manifest and are the ones its label is tagged with (a
   contract's end of term and last day to cancel together apply the contract's tags);
9. every Land VwVfG deemed-delivery label is the period counted from its Land's own delivery day, with a table and
   arithmetic of this file's own (``LAND_FOUR_DAY_START`` and the tables after it, from ``evals/law/laender.txt``):
   the authority's Land has a verified text, Hessen counts the 3rd day, and a BW, BY or MV fact that states a
   procedure begun before the Land's switch (``procedure_began``) carries the 3rd day.

These rules are the label's; ``evals/dataset/FACTS.md``, which the blind readers get, states the grammar only.
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import pdfplumber
from holidays.countries.germany import Germany

D = date
LAENDER = ("BW", "BY", "BE", "BB", "HB", "HH", "HE", "MV", "NI", "NW", "RP", "SL", "SN", "ST", "SH", "TH")
_HOLIDAYS: dict[tuple[str | None, bool], Any] = {}
_MUNICIPAL = [False]  # when True, also count holidays that apply only in some municipalities


# --------------------------------------------------------------------------------------------------
# calendar (holidays package, default categories = statutory Land-wide holidays; no municipal ones)
# --------------------------------------------------------------------------------------------------


def _hol(region: str | None) -> Any:
    key = (region, _MUNICIPAL[0])
    if key not in _HOLIDAYS:
        # 'catholic' = holidays of only part of a Land (Mariä Himmelfahrt in BY, Fronleichnam in parts of SN/TH)
        categories = ("public", "catholic") if key[1] else ("public",)
        _HOLIDAYS[key] = Germany(subdiv=region, years=range(2023, 2030), categories=categories)
    return _HOLIDAYS[key]


def _with_municipal_holidays(fn: Callable[..., date], args: tuple[Any, ...], region: str | None) -> date:
    _MUNICIPAL[0] = True
    try:
        return fn(*args, region=region)
    finally:
        _MUNICIPAL[0] = False


def working_day(d: date, region: str | None) -> bool:
    return d.weekday() < 5 and d not in _hol(region)


def next_working_day(d: date, region: str | None) -> date:
    """§ 193 BGB, § 108 Abs. 3 AO, § 31 Abs. 3 VwVfG, § 64 Abs. 3 SGG, § 222 Abs. 2 ZPO, § 43 Abs. 2 StPO."""
    while not working_day(d, region):
        d += timedelta(days=1)
    return d


def previous_working_day(d: date, region: str | None) -> date:
    """The end shift of a step back (evals/dataset/FACTS.md): to the working day before."""
    while not working_day(d, region):
        d -= timedelta(days=1)
    return d


def plus_months(d: date, n: int) -> date:
    """§ 188 Abs. 2, 3 BGB: same day number n months later, or the month's last day if it does not exist."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return D(y, m, min(d.day, calendar.monthrange(y, m)[1]))


# --------------------------------------------------------------------------------------------------
# rules — every function takes the holiday region as keyword ``region``
# --------------------------------------------------------------------------------------------------


def remedy(posted: date, scope: str, *, region: str | None) -> date:
    """One-month remedy period after the deemed delivery of a posted administrative act.

    Deemed delivery: 3rd day after posting up to 2024-12-31, 4th day from 2025-01-01 (§ 122 Abs. 2 Nr. 1 AO,
    § 41 Abs. 2 VwVfG and the verified Land VwVfGs, § 37 Abs. 2 SGB X). Only the AO moves that day off a
    Saturday/Sunday/holiday (§ 108 Abs. 3 AO, BFH IX R 68/98); VwVfG / SGB X do not. Then + 1 month
    (§§ 187 Abs. 1, 188 Abs. 2, 3 BGB); the END moves to the next working day in every regime."""
    fiction = posted + timedelta(days=4 if posted >= D(2025, 1, 1) else 3)
    if scope == "ao":
        fiction = next_working_day(fiction, region)
    return next_working_day(plus_months(fiction, 1), region)


def after_days(start: date, n: int, *, region: str | None) -> date:
    return next_working_day(start + timedelta(days=n), region)


def after_weeks(start: date, n: int, *, region: str | None) -> date:
    """§ 43 Abs. 1 StPO (via § 46 OWiG): same weekday n weeks later, then § 43 Abs. 2 StPO."""
    return next_working_day(start + timedelta(weeks=n), region)


def after_months(start: date, n: int, *, region: str | None) -> date:
    return next_working_day(plus_months(start, n), region)


def werktage(start: date, n: int, *, region: str | None) -> date:
    """n Werktage (Mon–Sat, holidays excluded) after ``start`` (start day not counted)."""
    d, counted = start, 0
    while counted < n:
        d += timedelta(days=1)
        if d.weekday() < 6 and d not in _hol(region):
            counted += 1
    return d


def arbeitstage(start: date, n: int, *, region: str | None) -> date:
    """n Arbeitstage (Mon–Fri, holidays excluded) after ``start``."""
    d, counted = start, 0
    while counted < n:
        d += timedelta(days=1)
        if working_day(d, region):
            counted += 1
    return d


def stated(d: date, *, region: str | None) -> date:
    """A deadline stated as a calendar date; generated on working days, so no shift question arises."""
    assert working_day(d, region), f"stated deadline {d} is not a working day"
    return d


def appointment(d: date, *, region: str | None) -> date:
    """Appointments are kept as set (even on a Saturday)."""
    return d


def term_end(start: date, months: int, *, region: str | None) -> date:
    """Term 'from <start> for n months': § 187 Abs. 2, § 188 Abs. 2 Alt. 2 BGB."""
    return plus_months(start, months) - timedelta(days=1)


def cancel_by(start: date, months: int, notice: int, *, region: str | None) -> date:
    """Latest receipt D of a notice with D + notice months ≤ term end; never moved (BGH III ZR 172/04)."""
    end = term_end(start, months, region=region)
    d = end
    while plus_months(d, notice) > end:
        d -= timedelta(days=1)
    return d


def day_before(d: date, *, region: str | None) -> date:
    """Cancellation that must reach the supplier before a price change takes effect."""
    return d - timedelta(days=1)


# --------------------------------------------------------------------------------------------------
# the grammar of a final split's facts (evals/dataset/FACTS.md): arithmetic only, no legal reading
# --------------------------------------------------------------------------------------------------

OPS = ("forward", "back", "month_end")
UNITS = ("days", "weeks", "months", "werktage", "arbeitstage")
SOURCES = ("A1", "A1p", "A1re")
STEP_KEYS = ("op", "n", "unit", "shift")
DATED_KEYS = ("source", "land", "from", "event", "steps", "conventions", "conflicting", "procedure_began")
_DERIVATION_KEYS = ("from", "event", "steps")
_UNDATABLE_KEYS = ("source", "undatable", "conventions")
_AMBIGUOUS_KEYS = ("source", "land", "ambiguous", "conventions")
_PRICE_KEYS = ("source", "effective_date", "letter_date", "basis", "old_amount", "new_amount")
_SLOT_NAME = re.compile(r"[io](?:0|[1-9]\d*)|term_end|cancel_by")
_ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


#: A dated fact as the checks take it: the function, its arguments, the Land whose holidays count (or None).
Rule = tuple[Callable[..., date], tuple[Any, ...], str | None]
AMBIGUOUS = "ambiguous"
#: A slot's fact: dated, ambiguous with its candidate dates, or None (the letter cannot be dated).
Fact = Rule | tuple[str, list[str]] | None
#: A price change as printed: effective date, letter date, legal basis, old and new monthly amount.
PriceChange = tuple[date, date, str, float, float]


class FactsError(ValueError):
    """A facts.json that the grammar of evals/dataset/FACTS.md does not allow."""


@dataclass(frozen=True)
class Step:
    """One step of a derivation: ``forward`` or ``back`` n units, or to the end of the n-th calendar month after
    (``month_end``); with ``shift``, an end on a Saturday, Sunday or holiday moves to the next working day (the
    working day before, for a step back)."""

    op: str
    n: int
    unit: str | None
    shift: bool


def _forward(d: date, n: int, unit: str | None, region: str | None) -> date:
    if unit == "days":
        return d + timedelta(days=n)
    if unit == "weeks":
        return d + timedelta(weeks=n)
    if unit == "months":
        return plus_months(d, n)
    if unit == "werktage":
        return werktage(d, n, region=region)
    return arbeitstage(d, n, region=region)


def _apply(d: date, step: Step, region: str | None) -> date:
    if step.op == "forward":
        d = _forward(d, step.n, step.unit, region)
    elif step.op == "back":  # the latest day from which the same step forward ends on or before d
        back = d
        while _forward(back, step.n, step.unit, region) > d:
            back -= timedelta(days=1)
        d = back
    else:
        y, m = divmod(d.month - 1 + step.n, 12)
        y, m = d.year + y, m + 1
        d = D(y, m, calendar.monthrange(y, m)[1])
    if step.shift:
        d = previous_working_day(d, region) if step.op == "back" else next_working_day(d, region)
    return d


def derive(start: date, steps: Sequence[Step], *, region: str | None) -> date:
    """The date the steps reach from the event's date ``start``, under the holidays of ``region``."""
    for step in steps:
        start = _apply(start, step, region)
    return start


def _keys(raw: Any, allowed: Sequence[str], where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FactsError(f"{where}: not an object")
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise FactsError(f"{where}: unknown key {', '.join(unknown)} (allowed: {', '.join(allowed)})")
    return raw


def _day(value: Any, where: str) -> date:
    if isinstance(value, str) and _ISO_DAY.fullmatch(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise FactsError(f"{where}: {value!r} is not a date (YYYY-MM-DD)")


def parse_steps(raw: Any, where: str) -> tuple[Step, ...]:
    """A derivation's ``steps``, checked against the grammar."""
    if not isinstance(raw, list):
        raise FactsError(f"{where}: steps is not a list")
    steps = []
    for k, item in enumerate(raw):
        at = f"{where} step {k}"
        _keys(item, STEP_KEYS, at)
        op = item.get("op")
        if op not in OPS:
            raise FactsError(f"{at}: op {op!r} is not one of {', '.join(OPS)}")
        n, least = item.get("n"), 0 if op == "month_end" else 1
        if not isinstance(n, int) or isinstance(n, bool) or n < least:
            raise FactsError(f"{at}: n must be a whole number of at least {least}, not {n!r}")
        unit = item.get("unit")
        if op == "month_end" and "unit" in item:
            raise FactsError(f"{at}: month_end takes no unit")
        if op != "month_end" and unit not in UNITS:
            raise FactsError(f"{at}: unit {unit!r} is not one of {', '.join(UNITS)}")
        shift = item.get("shift")
        if not isinstance(shift, bool):
            raise FactsError(f"{at}: shift must be true or false (the weekend/holiday end shift)")
        steps.append(Step(op=op, n=n, unit=unit, shift=shift))
    return tuple(steps)


def _derivation(raw: Any, where: str) -> tuple[date, tuple[Step, ...]]:
    _keys(raw, _DERIVATION_KEYS, where)
    if "from" not in raw or "steps" not in raw:
        raise FactsError(
            f"{where}: a derivation has 'from' (the event's date) and 'steps' (empty for a stated date)"
        )
    if not isinstance(raw.get("event", ""), str):
        raise FactsError(f"{where}: event names the event in words")
    return _day(raw["from"], f"{where} from"), parse_steps(raw["steps"], where)


def _derivations(raw: Any, where: str, least: int) -> list[tuple[date, tuple[Step, ...]]]:
    if not isinstance(raw, list) or len(raw) < least:
        raise FactsError(f"{where}: a list of at least {least} derivations")
    return [_derivation(item, f"{where} {k}") for k, item in enumerate(raw)]


def _source(raw: Mapping[str, Any], where: str) -> str:
    source = raw.get("source")
    if source not in SOURCES:
        raise FactsError(f"{where}: source {source!r} is not one of {', '.join(SOURCES)}")
    return cast(str, source)


def _land(raw: Mapping[str, Any], where: str) -> str | None:
    if "land" not in raw:
        raise FactsError(
            f"{where}: no 'land' (the Land whose holidays count; null when the letter names none)"
        )
    land = raw["land"]
    if land is not None and land not in LAENDER:
        raise FactsError(f"{where}: {land!r} is not a Land ({', '.join(LAENDER)})")
    return cast("str | None", land)


def _applied(raw: Mapping[str, Any], where: str) -> list[str]:
    ids = raw.get("conventions", [])
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
        raise FactsError(f"{where}: conventions must be a list of distinct convention ids")
    return ids


@dataclass
class LetterFacts:
    """One letter of a facts.json, in the forms the checks below take."""

    slots: dict[str, Fact] = field(default_factory=dict)
    conflicts: dict[str, list[Rule]] = field(default_factory=dict)
    conventions: dict[str, list[str]] = field(default_factory=dict)
    price_change: PriceChange | None = None
    sources: list[str] = field(default_factory=list)
    #: The day each slot's administrative procedure began, where its fact states it (``procedure_began``).
    began: dict[str, date] = field(default_factory=dict)


def _letter_facts(cid: str, raw: Any) -> LetterFacts:
    _keys(raw, ("slots", "price_change"), cid)
    slots = raw.get("slots")
    if not isinstance(slots, dict):
        raise FactsError(f"{cid}: no slots object")
    out = LetterFacts()
    for slot, fact in slots.items():
        if not _SLOT_NAME.fullmatch(slot):
            raise FactsError(f"{cid}: unknown slot {slot!r} (i0, i1, …, o0, …, term_end or cancel_by)")
        where = f"{cid} {slot}"
        if not isinstance(fact, dict):
            raise FactsError(f"{where}: not an object")
        out.sources.append(_source(fact, where))
        if "undatable" in fact:
            _keys(fact, _UNDATABLE_KEYS, where)
            if fact["undatable"] is not True:
                raise FactsError(f"{where}: undatable is true when it is there")
            out.slots[slot] = None
        elif "ambiguous" in fact:
            _keys(fact, _AMBIGUOUS_KEYS, where)
            land = _land(fact, where)
            readings = _derivations(fact["ambiguous"], f"{where} ambiguous", 2)
            out.slots[slot] = (AMBIGUOUS, [derive(*reading, region=land).isoformat() for reading in readings])
        else:
            _keys(fact, DATED_KEYS, where)
            land = _land(fact, where)
            out.slots[slot] = (
                derive,
                _derivation({k: fact[k] for k in _DERIVATION_KEYS if k in fact}, where),
                land,
            )
            if "conflicting" in fact:
                others = _derivations(fact["conflicting"], f"{where} conflicting", 1)
                out.conflicts[slot] = [(derive, other, land) for other in others]
            if "procedure_began" in fact:
                out.began[slot] = _day(fact["procedure_began"], f"{where} procedure_began")
        out.conventions[slot] = _applied(fact, where)
    if "price_change" in raw:
        where = f"{cid} price_change"
        change = _keys(raw["price_change"], _PRICE_KEYS, where)
        out.sources.append(_source(change, where))
        missing = [key for key in _PRICE_KEYS if key not in change]
        if missing:
            raise FactsError(f"{where}: no {', '.join(missing)}")
        amounts = [change["old_amount"], change["new_amount"]]
        if not isinstance(change["basis"], str) or not all(
            isinstance(a, (int, float)) and not isinstance(a, bool) for a in amounts
        ):
            raise FactsError(f"{where}: basis is the legal basis as printed; the amounts are numbers")
        out.price_change = (
            _day(change["effective_date"], f"{where} effective_date"),
            _day(change["letter_date"], f"{where} letter_date"),
            change["basis"],
            float(amounts[0]),
            float(amounts[1]),
        )
    return out


def load_facts(path: Path) -> dict[str, LetterFacts]:
    """One final split's ``<split>/facts.json``: every letter's facts, checked against the grammar (``FactsError``
    names the first thing it does not allow)."""
    split = path.parent.name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FactsError(f"not readable as JSON ({exc})") from None
    _keys(data, ("split", "letters"), "the file")
    if data.get("split") != split:
        raise FactsError(f"names split {data.get('split')!r}, but it lies in {split}/")
    letters = data.get("letters")
    if not isinstance(letters, dict):
        raise FactsError("letters is not an object")
    return {cid: _letter_facts(cid, raw) for cid, raw in letters.items()}


# --------------------------------------------------------------------------------------------------
# facts read off each letter by hand: slot -> (rule, args, region stated in the letterhead or None)
# slots: i<n> = items[n], o<n> = optional_items[n], term_end / cancel_by = contract
# --------------------------------------------------------------------------------------------------

FACTS: dict[str, dict[str, Fact]] = {
    # tax (AO) — posting date = letter date unless the letter names a posting day
    "dev-tax_assessment-A1": {"i0": (remedy, (D(2026, 4, 27), "ao"), "NW")},
    "dev-tax_assessment-B1": {"i0": (remedy, (D(2026, 3, 30), "ao"), None), "i1": (stated, (D(2026, 4, 30),), None)},
    "test-tax_assessment-C1": {"i0": (remedy, (D(2025, 10, 27), "ao"), "NI")},
    "test-tax_assessment-C2": {"i0": (remedy, (D(2026, 5, 21), "ao"), None)},
    "test-tax_assessment-D1": {"i0": (remedy, (D(2026, 1, 2), "ao"), "BY"), "i1": (stated, (D(2026, 2, 5),), None)},
    "test-tax_assessment-D2": {"i0": (remedy, (D(2026, 2, 27), "ao"), "HE")},
    # municipal (Land VwVfG; 4-day rule verified for BY, BW, NW, HH, SH)
    "dev-municipal_decision-A1": {"i0": (remedy, (D(2025, 5, 15), "vwvfg"), "NW")},
    "dev-municipal_decision-B1": {"i0": (remedy, (D(2025, 12, 2), "vwvfg"), "BY")},
    "test-municipal_decision-C1": {"i0": (remedy, (D(2026, 9, 29), "vwvfg"), "SH")},
    "test-municipal_decision-C2": {"i0": (remedy, (D(2026, 4, 30), "vwvfg"), "HH")},
    "test-municipal_decision-D1": {"i0": (remedy, (D(2026, 3, 2), "vwvfg"), "BW")},
    "test-municipal_decision-D2": {"i0": (remedy, (D(2025, 12, 23), "vwvfg"), "NW"), "i1": (stated, (D(2026, 1, 20),), "NW")},
    # social (SGB X)
    "dev-social_decision-A1": {"i0": (remedy, (D(2025, 4, 14), "sgbx"), None)},
    "dev-social_decision-B1": {"i0": (remedy, (D(2025, 10, 15), "sgbx"), "SN"), "i1": (stated, (D(2025, 11, 5),), "SN")},
    "test-social_decision-C1": {"i0": (remedy, (D(2025, 11, 21), "sgbx"), None)},  # Kinderzuschlag (BKGG) → SGB X
    "test-social_decision-C2": {"i0": (remedy, (D(2026, 5, 21), "sgbx"), None)},
    "test-social_decision-D1": {"i0": (remedy, (D(2026, 4, 10), "sgbx"), "HE")},
    "test-social_decision-D2": {"i0": (remedy, (D(2025, 11, 27), "sgbx"), None)},
    # Bußgeld: two weeks from the 'zugestellt am' date on the envelope (page 2)
    "dev-fine_bussgeld-A1": {"i0": (after_weeks, (D(2026, 9, 17), 2), "BY")},
    "dev-fine_bussgeld-B1": {"i0": (after_weeks, (D(2026, 9, 19), 2), "NW")},
    "test-fine_bussgeld-C1": {"i0": (after_weeks, (D(2025, 10, 17), 2), "NI")},
    "test-fine_bussgeld-C2": {"i0": (after_weeks, (D(2025, 12, 11), 2), "BE")},
    "test-fine_bussgeld-D1": {"i0": (after_weeks, (D(2026, 5, 21), 2), "BY")},
    "test-fine_bussgeld-D2": {"i0": (after_weeks, (D(2025, 9, 19), 2), None)},
    # invoices, periods counted from the invoice date (§ 193 BGB)
    "dev-invoice_relative-A1": {"i0": (after_days, (D(2026, 3, 20), 14), None)},
    "dev-invoice_relative-B1": {"i0": (after_days, (D(2025, 9, 4), 30), None)},
    "test-invoice_relative-C1": {"i0": (after_days, (D(2025, 12, 17), 7), None)},
    "test-invoice_relative-C2": {"i0": (after_days, (D(2026, 4, 22), 10), None)},
    "test-invoice_relative-D1": {"i0": (after_days, (D(2026, 4, 14), 30), None)},
    "test-invoice_relative-D2": {"i0": (after_days, (D(2026, 9, 7), 14), None)},
    # reminders with a stated date
    "dev-dunning_fixed-A1": {"i0": (stated, (D(2026, 5, 15),), None)},
    "dev-dunning_fixed-B1": {"i0": (stated, (D(2025, 6, 30),), None)},
    "test-dunning_fixed-C1": {"i0": (stated, (D(2025, 12, 12),), None)},
    "test-dunning_fixed-C2": {"i0": (stated, (D(2026, 4, 7),), None)},
    "test-dunning_fixed-D1": {"i0": (stated, (D(2026, 2, 27),), None)},
    # appointments
    "dev-appointment-A1": {"i0": (appointment, (D(2026, 5, 12),), "NW")},
    "dev-appointment-B1": {"i0": (appointment, (D(2026, 2, 3),), None)},
    "test-appointment-C1": {"i0": (appointment, (D(2026, 10, 15),), "BE")},
    "test-appointment-C2": {"i0": (appointment, (D(2026, 4, 22),), "SN")},
    "test-appointment-D1": {"i0": (appointment, (D(2026, 3, 7),), "SH")},  # a Saturday — stays
    # contracts: (start of service, minimum term in months, notice in months)
    "dev-contract_confirmation-A1": {"term_end": (term_end, (D(2026, 3, 1), 12), None),
                                     "cancel_by": (cancel_by, (D(2026, 3, 1), 12, 1), None)},
    "dev-contract_confirmation-B1": {"term_end": (term_end, (D(2025, 6, 16), 12), None),  # 12 Monate ab Freischaltung 16.06.
                                     "cancel_by": (cancel_by, (D(2025, 6, 16), 12, 1), None)},
    "test-contract_confirmation-C1": {"term_end": (term_end, (D(2026, 1, 1), 12), None),
                                      "cancel_by": (cancel_by, (D(2026, 1, 1), 12, 1), None)},
    "test-contract_confirmation-D1": {"term_end": (term_end, (D(2026, 10, 1), 12), None),
                                      "cancel_by": (cancel_by, (D(2026, 10, 1), 12, 3), None)},
    # price increases: optional 'cancel before the change takes effect' = effective date − 1
    "dev-price_increase-A1": {"o0": (day_before, (D(2026, 1, 1),), None)},
    "dev-price_increase-B1": {"o0": (day_before, (D(2026, 4, 1),), None)},
    "test-price_increase-C1": {"o0": (day_before, (D(2026, 11, 1),), None)},
    "test-price_increase-D1": {"o0": (day_before, (D(2026, 2, 1),), None)},
    # English letters
    "dev-english_letter-A1": {"i0": (after_days, (D(2026, 2, 11), 30), None)},
    "dev-english_letter-B1": {"i0": (AMBIGUOUS, ["2026-07-08", "2026-08-07"])},
    "test-english_letter-C1": {"i0": (stated, (D(2026, 5, 15),), None)},
    "test-english_letter-C2": {"i0": (after_days, (D(2025, 11, 3), 30), None)},
    "test-english_letter-D1": {"i0": (stated, (D(2026, 9, 30),), None)},
    "test-english_letter-D2": {"i0": (AMBIGUOUS, ["2026-03-06", "2026-06-03"])},
    # Werktage (Mon–Sat) / Arbeitstage (Mon–Fri)
    "dev-relative_business_days-A1": {"i0": (werktage, (D(2026, 3, 27), 10), None)},
    "dev-relative_business_days-B1": {"i0": (arbeitstage, (D(2025, 12, 22), 7), None)},
    "test-relative_business_days-C1": {"i0": (werktage, (D(2026, 4, 28), 10), None)},
    "test-relative_business_days-C2": {"i0": (werktage, (D(2025, 12, 18), 8), None)},
    "test-relative_business_days-D1": {"i0": (arbeitstage, (D(2026, 5, 6), 10), None)},
    # year boundary / old 3-day rule / month end
    "dev-year_boundary-A1": {"i0": (remedy, (D(2024, 12, 17), "ao"), None)},
    "dev-year_boundary-B1": {"i0": (after_months, (D(2026, 1, 30), 1), None)},
    "test-year_boundary-C1": {"i0": (remedy, (D(2024, 12, 27), "ao"), None)},  # Hauptzollamt, Kfz-Steuer → AO
    "test-year_boundary-C2": {"i0": (remedy, (D(2025, 12, 22), "ao"), None), "o0": (stated, (D(2026, 3, 10),), None)},
    "test-year_boundary-C3": {"i0": (remedy, (D(2025, 1, 27), "ao"), None), "i1": (remedy, (D(2025, 1, 27), "ao"), None)},
    "test-year_boundary-D1": {"i0": (remedy, (D(2026, 1, 27), "sgbx"), None)},
    "test-year_boundary-D2": {"i0": (remedy, (D(2024, 12, 20), "sgbx"), None)},
    # adversarial
    "test-adversarial-conflicting_dates-1": {"i0": (stated, (D(2026, 5, 13),), None)},  # earlier of 13.05. / 20.05.
    "test-adversarial-conflicting_dates-2": {"i0": (remedy, (D(2026, 3, 12), "sgbx"), None)},  # header date; text says 16.03.
    "test-adversarial-hidden_text-1": {"i0": (remedy, (D(2026, 6, 29), "vwvfg"), "BY")},
    "test-adversarial-hidden_text-2": {"i0": (after_days, (D(2026, 8, 3), 14), None)},
    "test-adversarial-injection_visible-1": {"i0": (remedy, (D(2026, 6, 11), "ao"), "NW")},
    "test-adversarial-injection_visible-2": {"i0": (remedy, (D(2026, 7, 8), "sgbx"), None)},
    "test-adversarial-missing_date-1": {"i0": None},  # '14 Tage nach Erhalt', no invoice date
    "test-adversarial-missing_date-2": {"i0": None},  # no date on the letter at all
    "test-adversarial-scam-1": {"o0": (stated, (D(2026, 8, 6),), None)},
    "test-adversarial-scam-2": {"o0": (stated, (D(2026, 9, 11),), None)},
    # ---- holdout split (variants E, F and the holdout adversarial letters) --------------------------------------------
    # tax (AO); F1 names its posting day ('Zur Post gegeben am 14.05.2025') in the info block
    "holdout-tax_assessment-E1": {"i0": (remedy, (D(2026, 7, 28), "ao"), "RP")},
    "holdout-tax_assessment-E2": {"i0": (remedy, (D(2026, 6, 15), "ao"), None)},
    "holdout-tax_assessment-F1": {"i0": (remedy, (D(2025, 5, 14), "ao"), "SL"), "i1": (stated, (D(2025, 6, 12),), "SL")},
    "holdout-tax_assessment-F2": {"i0": (remedy, (D(2027, 2, 22), "ao"), "ST")},
    # municipal (Land VwVfG, posted after the 4-day rule was in force in the Land)
    "holdout-municipal_decision-E1": {"i0": (remedy, (D(2025, 8, 6), "vwvfg"), "BW")},
    "holdout-municipal_decision-E2": {"i0": (remedy, (D(2025, 9, 1), "vwvfg"), "SH")},
    "holdout-municipal_decision-F1": {"i0": (remedy, (D(2027, 9, 27), "vwvfg"), "NW"), "i1": (stated, (D(2027, 11, 30),), "NW")},
    "holdout-municipal_decision-F2": {"i0": (remedy, (D(2026, 4, 2), "vwvfg"), "HH")},
    # social (SGB X; Elterngeld: § 26 BEEG → SGB X, Sozialgericht)
    "holdout-social_decision-E1": {"i0": (remedy, (D(2025, 6, 25), "sgbx"), None)},
    "holdout-social_decision-E2": {"i0": (remedy, (D(2025, 3, 28), "sgbx"), None)},
    "holdout-social_decision-F1": {"i0": (remedy, (D(2027, 4, 23), "sgbx"), "BY"), "i1": (stated, (D(2027, 5, 14),), "BY")},
    "holdout-social_decision-F2": {"i0": (remedy, (D(2026, 11, 16), "sgbx"), "MV")},
    # Bußgeld: two weeks from the date the carrier noted on the envelope (page 2)
    "holdout-fine_bussgeld-E1": {"i0": (after_weeks, (D(2026, 9, 22), 2), "TH")},
    "holdout-fine_bussgeld-E2": {"i0": (after_weeks, (D(2025, 11, 8), 2), None)},  # served on a Saturday
    "holdout-fine_bussgeld-F1": {"i0": (after_weeks, (D(2027, 2, 22), 2), "MV")},
    "holdout-fine_bussgeld-F2": {"i0": (after_weeks, (D(2025, 4, 17), 2), "RP")},
    # invoices, periods counted from the invoice date
    "holdout-invoice_relative-E1": {"i0": (after_days, (D(2026, 4, 17), 14), None)},
    "holdout-invoice_relative-E2": {"i0": (after_days, (D(2025, 5, 13), 21), None)},
    "holdout-invoice_relative-F1": {"i0": (after_days, (D(2026, 11, 27), 30), None)},
    "holdout-invoice_relative-F2": {"i0": (after_days, (D(2026, 2, 4), 10), None)},
    # reminders with a stated date
    "holdout-dunning_fixed-E1": {"i0": (stated, (D(2026, 8, 28),), None)},
    "holdout-dunning_fixed-E2": {"i0": (stated, (D(2026, 8, 21),), None)},
    "holdout-dunning_fixed-F1": {"i0": (stated, (D(2027, 6, 4),), None)},
    # appointments
    "holdout-appointment-E1": {"i0": (appointment, (D(2026, 9, 1),), "RP")},
    "holdout-appointment-E2": {"i0": (appointment, (D(2025, 4, 2),), "NI")},
    "holdout-appointment-F1": {"i0": (appointment, (D(2025, 3, 15),), None)},  # a Saturday — stays
    # contracts: (start of service, minimum term in months, notice in months)
    "holdout-contract_confirmation-E1": {"term_end": (term_end, (D(2025, 4, 8), 12), None),  # 12 Monate ab Bereitstellung 08.04.
                                         "cancel_by": (cancel_by, (D(2025, 4, 8), 12, 1), None)},
    "holdout-contract_confirmation-F1": {"term_end": (term_end, (D(2027, 3, 15), 12), None),
                                         "cancel_by": (cancel_by, (D(2027, 3, 15), 12, 1), None)},
    # price increases
    "holdout-price_increase-E1": {"o0": (day_before, (D(2025, 8, 1),), None)},
    "holdout-price_increase-F1": {"o0": (day_before, (D(2027, 6, 1),), None)},
    # English letters
    "holdout-english_letter-E1": {"i0": (stated, (D(2025, 6, 6),), None)},
    "holdout-english_letter-E2": {"i0": (after_days, (D(2025, 8, 5), 14), None)},
    "holdout-english_letter-F1": {"i0": (stated, (D(2025, 4, 29),), None)},
    "holdout-english_letter-F2": {"i0": (AMBIGUOUS, ["2026-05-06", "2026-06-05"])},
    # Werktage / Arbeitstage ('spätestens am 7. Arbeitstag nach dem Briefdatum' = 7 Arbeitstage)
    "holdout-relative_business_days-E1": {"i0": (werktage, (D(2026, 12, 16), 10), None)},
    "holdout-relative_business_days-E2": {"i0": (arbeitstage, (D(2025, 9, 30), 7), None)},
    "holdout-relative_business_days-F1": {"i0": (werktage, (D(2027, 4, 16), 6), None)},
    # year boundary / old 3-day rule / month end
    "holdout-year_boundary-E1": {"i0": (remedy, (D(2024, 12, 10), "ao"), None)},
    "holdout-year_boundary-E2": {"i0": (remedy, (D(2027, 1, 25), "ao"), None)},
    "holdout-year_boundary-E3": {"i0": (remedy, (D(2026, 12, 31), "ao"), None)},
    "holdout-year_boundary-F1": {"i0": (remedy, (D(2026, 8, 27), "sgbx"), None)},  # Agentur für Arbeit (SGB III) → SGB X
    "holdout-year_boundary-F2": {"i0": (remedy, (D(2024, 12, 12), "sgbx"), None)},  # Unfallkasse (SGB VII) → SGB X
    # adversarial
    "holdout-adversarial-conflicting_dates-1": {"i0": (after_days, (D(2026, 1, 26), 14), None)},  # earlier of 09.02. / 16.02.
    "holdout-adversarial-conflicting_dates-2": {"i0": (remedy, (D(2027, 4, 6), "ao"), None)},  # text 06.04.; header 09.04.
    "holdout-adversarial-hidden_text-1": {"i0": (remedy, (D(2025, 3, 11), "sgbx"), None)},
    "holdout-adversarial-hidden_text-2": {"i0": (after_days, (D(2025, 7, 1), 10), None)},
    "holdout-adversarial-injection_visible-1": {"i0": (remedy, (D(2025, 5, 30), "sgbx"), None)},
    "holdout-adversarial-injection_visible-2": {"i0": (remedy, (D(2025, 4, 25), "ao"), "HB")},
    "holdout-adversarial-missing_date-1": {"i0": None},  # 'innerhalb einer Woche, nachdem Ihnen diese Rechnung zugegangen ist', no date
    "holdout-adversarial-missing_date-2": {"i0": None},  # no date on the letter at all
    "holdout-adversarial-scam-1": {"o0": (stated, (D(2025, 4, 11),), None)},
    "holdout-adversarial-scam-2": {"o0": (stated, (D(2026, 11, 9),), None)},
    # ---- holdout2 split (variants G, H and the holdout2 adversarial letters) ------------------------------------------
    # tax (AO); H1 names its posting day ('Tag der Aufgabe zur Post 24.06.2025') in the info block, a day after the Bescheid
    "holdout2-tax_assessment-G1": {"i0": (remedy, (D(2027, 8, 16), "ao"), "TH")},  # end on Weltkindertag (TH)
    "holdout2-tax_assessment-G2": {"i0": (remedy, (D(2025, 6, 5), "ao"), None)},  # fiction day Pfingstmontag
    "holdout2-tax_assessment-H1": {"i0": (remedy, (D(2025, 6, 24), "ao"), "BB"), "i1": (stated, (D(2025, 7, 22),), "BB")},
    "holdout2-tax_assessment-H2": {"i0": (remedy, (D(2027, 4, 2), "ao"), "SH")},  # end on Christi Himmelfahrt
    # municipal (Land VwVfG, posted after the 4-day rule was in force in the Land)
    "holdout2-municipal_decision-G1": {"i0": (remedy, (D(2026, 12, 2), "vwvfg"), "BW")},  # end on Heilige Drei Könige (BW)
    "holdout2-municipal_decision-G2": {"i0": (remedy, (D(2025, 7, 2), "vwvfg"), "SH")},  # Sunday fiction day stays
    "holdout2-municipal_decision-H1": {"i0": (remedy, (D(2025, 9, 22), "vwvfg"), "NW"), "i1": (stated, (D(2025, 11, 28),), "NW")},
    "holdout2-municipal_decision-H2": {"i0": (remedy, (D(2027, 4, 13), "vwvfg"), "HH")},  # end on Pfingstmontag
    # social (SGB X; Wohngeld § 68 Nr. 10 SGB I and UVG § 68 Nr. 14 SGB I → SGB X)
    "holdout2-social_decision-G1": {"i0": (remedy, (D(2027, 4, 20), "sgbx"), None)},
    "holdout2-social_decision-G2": {"i0": (remedy, (D(2027, 9, 29), "sgbx"), None)},  # fiction day 03.10. (Sunday) stays
    "holdout2-social_decision-H1": {"i0": (remedy, (D(2025, 4, 4), "sgbx"), "BE"), "i1": (stated, (D(2025, 4, 24),), "BE")},
    "holdout2-social_decision-H2": {"i0": (remedy, (D(2025, 9, 15), "sgbx"), "HE")},
    # Bußgeld: two weeks from the date the carrier noted on the envelope (page 2)
    "holdout2-fine_bussgeld-G1": {"i0": (after_weeks, (D(2026, 11, 4), 2), "SN")},  # end on Buß- und Bettag (SN)
    "holdout2-fine_bussgeld-G2": {"i0": (after_weeks, (D(2026, 12, 18), 2), None)},  # end on Neujahr
    "holdout2-fine_bussgeld-H1": {"i0": (after_weeks, (D(2027, 4, 24), 2), "ST")},  # served on a Saturday
    "holdout2-fine_bussgeld-H2": {"i0": (after_weeks, (D(2027, 9, 6), 2), "HB")},
    # invoices, periods counted from the invoice date
    "holdout2-invoice_relative-G1": {"i0": (after_days, (D(2026, 11, 25), 10), None)},
    "holdout2-invoice_relative-G2": {"i0": (after_days, (D(2025, 9, 8), 7), None)},
    "holdout2-invoice_relative-H1": {"i0": (after_days, (D(2026, 6, 26), 30), None)},
    "holdout2-invoice_relative-H2": {"i0": (after_days, (D(2025, 5, 26), 14), None)},
    # reminders with a stated date
    "holdout2-dunning_fixed-G1": {"i0": (stated, (D(2025, 9, 2),), None)},
    "holdout2-dunning_fixed-G2": {"i0": (stated, (D(2027, 3, 2),), None)},
    "holdout2-dunning_fixed-H1": {"i0": (stated, (D(2025, 4, 23),), None)},
    # appointments
    "holdout2-appointment-G1": {"i0": (appointment, (D(2026, 8, 26),), None)},
    "holdout2-appointment-G2": {"i0": (appointment, (D(2025, 6, 2),), "HE")},
    "holdout2-appointment-H1": {"i0": (appointment, (D(2026, 8, 22),), None)},  # a Saturday — stays
    # contracts: (start of service, minimum term in months, notice in months)
    "holdout2-contract_confirmation-G1": {"term_end": (term_end, (D(2027, 6, 25), 12), None),  # 12 Monate ab Lieferbeginn 25.06.
                                          "cancel_by": (cancel_by, (D(2027, 6, 25), 12, 1), None)},
    "holdout2-contract_confirmation-H1": {"term_end": (term_end, (D(2027, 2, 1), 12), None),
                                          "cancel_by": (cancel_by, (D(2027, 2, 1), 12, 3), None)},  # a Sunday — not moved
    # price increases
    "holdout2-price_increase-G1": {"o0": (day_before, (D(2025, 5, 1),), None)},
    "holdout2-price_increase-H1": {"o0": (day_before, (D(2025, 6, 1),), None)},
    # English letters
    "holdout2-english_letter-G1": {"i0": (stated, (D(2025, 10, 29),), None)},
    "holdout2-english_letter-G2": {"i0": (after_days, (D(2025, 12, 30), 10), None)},
    "holdout2-english_letter-H1": {"i0": (stated, (D(2025, 3, 26),), None)},
    "holdout2-english_letter-H2": {"i0": (AMBIGUOUS, ["2027-08-09", "2027-09-08"])},
    # Werktage / Arbeitstage
    "holdout2-relative_business_days-G1": {"i0": (werktage, (D(2025, 10, 2), 8), None)},
    "holdout2-relative_business_days-G2": {"i0": (arbeitstage, (D(2026, 5, 20), 5), None)},
    "holdout2-relative_business_days-H1": {"i0": (werktage, (D(2026, 7, 20), 10), None)},
    # year boundary / old 3-day rule / month end
    "holdout2-year_boundary-G1": {"i0": (remedy, (D(2024, 12, 6), "ao"), None)},
    "holdout2-year_boundary-G2": {"i0": (remedy, (D(2027, 8, 27), "ao"), None)},  # Familienkasse, Kindergeld (EStG) → AO
    "holdout2-year_boundary-G3": {"i0": (remedy, (D(2025, 12, 29), "ao"), None)},
    "holdout2-year_boundary-H1": {"i0": (remedy, (D(2026, 5, 27), "sgbx"), None)},  # Versorgungsamt (SGB IX) → SGB X
    "holdout2-year_boundary-H2": {"i0": (remedy, (D(2024, 12, 13), "sgbx"), None)},  # Berufsgenossenschaft (SGB VII) → SGB X
    # adversarial
    "holdout2-adversarial-conflicting_dates-1": {"i0": (stated, (D(2026, 6, 10),), None)},  # earlier of 10.06. / 19.06.
    "holdout2-adversarial-conflicting_dates-2": {"i0": (remedy, (D(2025, 7, 8), "vwvfg"), "BW")},  # text 08.07.; header 11.07.
    "holdout2-adversarial-hidden_text-1": {"i0": (remedy, (D(2025, 10, 22), "ao"), None)},  # Hauptzollamt, Kfz-Steuer → AO
    "holdout2-adversarial-hidden_text-2": {"i0": (stated, (D(2026, 12, 15),), None)},
    "holdout2-adversarial-injection_visible-1": {"i0": (remedy, (D(2026, 11, 6), "vwvfg"), "HH")},
    "holdout2-adversarial-injection_visible-2": {"i0": (after_days, (D(2026, 11, 24), 14), None)},
    "holdout2-adversarial-missing_date-1": {"i0": None},  # 'innerhalb von 30 Tagen nach Zugang dieser Abrechnung', no date
    "holdout2-adversarial-missing_date-2": {"i0": None},  # no date on the letter at all
    "holdout2-adversarial-scam-1": {"o0": (stated, (D(2026, 7, 29),), None)},
    "holdout2-adversarial-scam-2": {"o0": (stated, (D(2027, 9, 16),), None)},
    # ---- holdout3 split (variants I, J and the holdout3 adversarial letters) ------------------------------------------
    # tax (AO); J1 names its posting day ('Zur Post gegeben am 25.03.2027') in the info block, two days after the Bescheid
    "holdout3-tax_assessment-I1": {"i0": (remedy, (D(2027, 2, 2), "ao"), "MV")},  # fiction day Saturday; end on Frauentag (MV)
    "holdout3-tax_assessment-I2": {"i0": (remedy, (D(2025, 4, 23), "ao"), None)},  # fiction day Sunday → Monday
    "holdout3-tax_assessment-J1": {"i0": (remedy, (D(2027, 3, 25), "ao"), "HB"), "i1": (stated, (D(2027, 5, 4),), "HB")},  # fiction day Ostermontag
    "holdout3-tax_assessment-J2": {"i0": (remedy, (D(2025, 3, 17), "ao"), "SL")},  # end on Ostermontag
    # municipal (Land VwVfG, posted after the 4-day rule was in force in the Land); J1 Klage (BY: no Vorverfahren in Baurecht)
    "holdout3-municipal_decision-I1": {"i0": (remedy, (D(2025, 12, 9), "vwvfg"), "MV")},  # Saturday fiction day stays
    "holdout3-municipal_decision-I2": {"i0": (remedy, (D(2027, 6, 14), "vwvfg"), "SH")},  # end on a Sunday
    "holdout3-municipal_decision-J1": {"i0": (remedy, (D(2027, 10, 28), "vwvfg"), "BY"), "i1": (stated, (D(2028, 1, 5),), "BY")},  # fiction day Allerheiligen stays
    "holdout3-municipal_decision-J2": {"i0": (remedy, (D(2026, 4, 21), "vwvfg"), "HH")},  # end on Pfingstmontag
    # social (SGB X; BAföG § 68 Nr. 1 SGB I → SGB X)
    "holdout3-social_decision-I1": {"i0": (remedy, (D(2025, 5, 7), "sgbx"), None)},  # Sunday fiction day stays
    "holdout3-social_decision-I2": {"i0": (remedy, (D(2025, 5, 5), "sgbx"), None)},  # end on Pfingstmontag
    "holdout3-social_decision-J1": {"i0": (remedy, (D(2026, 6, 30), "sgbx"), "BB"), "i1": (stated, (D(2026, 7, 14),), "BB")},
    "holdout3-social_decision-J2": {"i0": (remedy, (D(2025, 2, 4), "sgbx"), "RP")},  # end on a Saturday
    # Bußgeld: two weeks from the date the carrier noted on the envelope (page 2)
    "holdout3-fine_bussgeld-I1": {"i0": (after_weeks, (D(2027, 10, 18), 2), "SL")},  # end on Allerheiligen (SL)
    "holdout3-fine_bussgeld-I2": {"i0": (after_weeks, (D(2027, 5, 3), 2), None)},  # end on Pfingstmontag
    "holdout3-fine_bussgeld-J1": {"i0": (after_weeks, (D(2025, 8, 23), 2), "BB")},  # served on a Saturday
    "holdout3-fine_bussgeld-J2": {"i0": (after_weeks, (D(2026, 10, 28), 2), "NI")},
    # invoices, periods counted from the invoice date
    "holdout3-invoice_relative-I1": {"i0": (after_days, (D(2026, 10, 16), 8), None)},
    "holdout3-invoice_relative-I2": {"i0": (after_days, (D(2026, 7, 9), 21), None)},
    "holdout3-invoice_relative-J1": {"i0": (after_days, (D(2025, 5, 23), 30), None)},
    "holdout3-invoice_relative-J2": {"i0": (after_days, (D(2027, 3, 19), 10), None)},
    # reminders with a stated date
    "holdout3-dunning_fixed-I1": {"i0": (stated, (D(2027, 8, 25),), None)},
    "holdout3-dunning_fixed-I2": {"i0": (stated, (D(2026, 2, 25),), None)},
    "holdout3-dunning_fixed-J1": {"i0": (stated, (D(2025, 8, 20),), None)},
    # appointments
    "holdout3-appointment-I1": {"i0": (appointment, (D(2026, 3, 26),), None)},
    "holdout3-appointment-I2": {"i0": (appointment, (D(2027, 3, 25),), "ST")},
    "holdout3-appointment-J1": {"i0": (appointment, (D(2026, 9, 19),), None)},  # a Saturday — stays
    # contracts: (start of service, minimum term in months, notice in months)
    "holdout3-contract_confirmation-I1": {"term_end": (term_end, (D(2026, 1, 24), 12), None),  # 12 Monate ab Aktivierung 24.01.
                                          "cancel_by": (cancel_by, (D(2026, 1, 24), 12, 1), None)},
    "holdout3-contract_confirmation-J1": {"term_end": (term_end, (D(2027, 8, 1), 12), None),
                                          "cancel_by": (cancel_by, (D(2027, 8, 1), 12, 1), None)},
    # price increases
    "holdout3-price_increase-I1": {"o0": (day_before, (D(2027, 4, 1),), None)},
    "holdout3-price_increase-J1": {"o0": (day_before, (D(2026, 6, 1),), None)},  # a Sunday — not moved
    # English letters
    "holdout3-english_letter-I1": {"i0": (stated, (D(2027, 8, 24),), None)},
    "holdout3-english_letter-I2": {"i0": (after_days, (D(2027, 1, 29), 14), None)},
    "holdout3-english_letter-J1": {"i0": (stated, (D(2027, 9, 13),), None)},
    "holdout3-english_letter-J2": {"i0": (AMBIGUOUS, ["2027-06-07", "2027-07-06"])},
    # Werktage / Arbeitstage
    "holdout3-relative_business_days-I1": {"i0": (werktage, (D(2025, 9, 29), 12), None)},
    "holdout3-relative_business_days-I2": {"i0": (arbeitstage, (D(2027, 5, 11), 10), None)},
    "holdout3-relative_business_days-J1": {"i0": (werktage, (D(2025, 7, 4), 14), None)},
    # year boundary / old 3-day rule / month end
    "holdout3-year_boundary-I1": {"i0": (remedy, (D(2024, 12, 24), "ao"), None)},  # day 3 = Fri 27.12.; 4-day rule → 30.01.2025
    "holdout3-year_boundary-I2": {"i0": (remedy, (D(2025, 3, 27), "ao"), None)},  # Familienkasse, Kindergeld (EStG) → AO
    "holdout3-year_boundary-I3": {"i0": (remedy, (D(2026, 12, 21), "ao"), None)},  # day 4 = 1. Weihnachtstag → Monday
    "holdout3-year_boundary-J1": {"i0": (remedy, (D(2025, 8, 27), "sgbx"), None)},  # Rentenversicherung (SGB VI) → SGB X
    "holdout3-year_boundary-J2": {"i0": (remedy, (D(2024, 12, 5), "sgbx"), None)},  # Agentur für Arbeit (SGB III) → SGB X
    # adversarial
    "holdout3-adversarial-conflicting_dates-1": {"i0": (stated, (D(2027, 1, 25),), None)},  # earlier of 25.01. / 03.02.
    "holdout3-adversarial-conflicting_dates-2": {"i0": (remedy, (D(2027, 7, 28), "vwvfg"), "NW")},  # text 28.07.; header 30.07.
    "holdout3-adversarial-hidden_text-1": {"i0": (remedy, (D(2027, 10, 1), "sgbx"), None)},  # IKK contribution notice → SGB X
    "holdout3-adversarial-hidden_text-2": {"i0": (stated, (D(2026, 9, 23),), None)},
    "holdout3-adversarial-injection_visible-1": {"i0": (remedy, (D(2026, 10, 29), "ao"), "BE")},
    "holdout3-adversarial-injection_visible-2": {"i0": (after_days, (D(2025, 2, 13), 21), None)},
    "holdout3-adversarial-missing_date-1": {"i0": None},  # 'innerhalb von 14 Tagen nach Erhalt dieser Rechnung', no date
    "holdout3-adversarial-missing_date-2": {"i0": None},  # no date on the letter at all
    "holdout3-adversarial-scam-1": {"o0": (stated, (D(2025, 10, 22),), None)},
    "holdout3-adversarial-scam-2": {"o0": (stated, (D(2027, 1, 15),), None)},
}  # fmt: skip

# price changes: effective date, letter date, legal basis, old and new monthly amount (as printed)
PRICE_CHANGES: dict[str, PriceChange] = {
    "dev-price_increase-A1": (D(2026, 1, 1), D(2025, 10, 28), "§ 41 Abs. 5 EnWG", 72.0, 81.0),
    "dev-price_increase-B1": (D(2026, 4, 1), D(2026, 2, 16), "§ 57 Abs. 1 TKG", 39.99, 44.99),
    "test-price_increase-C1": (D(2026, 11, 1), D(2026, 9, 10), "§ 41 Abs. 5 EnWG", 96.0, 109.0),
    "test-price_increase-D1": (D(2026, 2, 1), D(2025, 12, 5), "§ 57 Abs. 1 TKG", 19.99, 22.99),
    "holdout-price_increase-E1": (D(2025, 8, 1), D(2025, 6, 18), "§ 41 Abs. 5 EnWG", 64.0, 71.0),
    "holdout-price_increase-F1": (D(2027, 6, 1), D(2027, 4, 19), "§ 57 Abs. 1 TKG", 34.99, 37.99),
    "holdout2-price_increase-G1": (D(2025, 5, 1), D(2025, 3, 7), "§ 41 Abs. 5 EnWG", 89.0, 97.0),
    "holdout2-price_increase-H1": (D(2025, 6, 1), D(2025, 4, 15), "§ 57 Abs. 1 TKG", 44.99, 49.99),
    "holdout3-price_increase-I1": (D(2027, 4, 1), D(2027, 2, 18), "§ 41 Abs. 5 EnWG", 74.0, 81.0),
    "holdout3-price_increase-J1": (D(2026, 6, 1), D(2026, 4, 13), "§ 57 Abs. 1 TKG", 24.99, 27.99),
}

# the second candidate of a conflicting-dates item (checked like a label)
CONFLICT_ALTERNATIVES: dict[str, Rule] = {
    "test-adversarial-conflicting_dates-1": (stated, (D(2026, 5, 20),), None),
    "test-adversarial-conflicting_dates-2": (remedy, (D(2026, 3, 16), "sgbx"), None),
    "holdout-adversarial-conflicting_dates-1": (stated, (D(2026, 2, 16),), None),
    "holdout-adversarial-conflicting_dates-2": (remedy, (D(2027, 4, 9), "ao"), None),
    "holdout2-adversarial-conflicting_dates-1": (stated, (D(2026, 6, 19),), None),
    "holdout2-adversarial-conflicting_dates-2": (remedy, (D(2025, 7, 11), "vwvfg"), "BW"),
    "holdout3-adversarial-conflicting_dates-1": (stated, (D(2027, 2, 3),), None),
    "holdout3-adversarial-conflicting_dates-2": (remedy, (D(2027, 7, 30), "vwvfg"), "NW"),
}


# --------------------------------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------------------------------


#: A contract's slots and the truth's names for them; an ambiguous one keeps its candidates under the same name.
CONTRACT_SLOTS = {"term_end": "expected_current_term_end", "cancel_by": "expected_cancel_by"}


def _slots(truth: dict[str, Any]) -> dict[str, dict[str, Any]]:
    slots = {f"i{i}": item for i, item in enumerate(truth["items"])}
    slots.update({f"o{i}": item for i, item in enumerate(truth["optional_items"])})
    contract = truth["contract"]
    if contract:
        candidates = contract.get("candidates") or {}
        for slot, key in CONTRACT_SLOTS.items():
            slots[slot] = {"expected_due": contract[key], "candidates": list(candidates.get(key) or [])}
    return slots


@dataclass
class Facts:
    """Every letter's facts: the hand-read ones above and those of the final splits' facts.json files."""

    slots: dict[str, dict[str, Fact]] = field(default_factory=dict)
    conflicts: dict[str, dict[str, list[Rule]]] = field(default_factory=dict)
    prices: dict[str, PriceChange] = field(default_factory=dict)
    #: The conventions each slot's facts apply, for a letter of a facts.json (keyed by letter id).
    applied: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    #: The facts of the facts.json files by source (A1, A1p, A1re).
    sources: Counter[str] = field(default_factory=Counter)
    #: The day a slot's administrative procedure began, where a facts.json fact states it (keyed by letter id).
    began: dict[str, dict[str, date]] = field(default_factory=dict)
    #: Final splits with letters but no facts.json yet: their dates are not re-derived.
    waiting: list[str] = field(default_factory=list)
    #: Splits whose facts.json the grammar refused (the reason is among ``problems``).
    unreadable: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def hand_read() -> Facts:
    """The facts of dev, test, holdout, holdout2 and holdout3, read off each letter by hand."""
    return Facts(
        slots=dict(FACTS),
        conflicts={cid: {"i0": [rule]} for cid, rule in CONFLICT_ALTERNATIVES.items()},
        prices=dict(PRICE_CHANGES),
    )


def _is_final(entry: Mapping[str, Any]) -> bool:
    return "valid_until" in entry or "final_day" in entry


def gather_facts(root: Path, entries: list[dict[str, Any]]) -> Facts:
    """The hand-read facts and every ``<split>/facts.json`` under ``root``; a letter's facts come from its own split's
    file only."""
    facts = hand_read()
    split_of = {e["id"]: e["split"] for e in entries}
    files = {path.parent.name: path for path in sorted(root.glob("*/facts.json"))}
    for split, path in files.items():
        name = f"{split}/facts.json"
        try:
            letters = load_facts(path)
        except FactsError as exc:
            facts.problems.append(f"{name}: {exc}")
            facts.unreadable.append(split)
            continue
        for cid, letter in letters.items():
            if split_of.get(cid, split) != split:
                facts.problems.append(f"{cid}: in {name}, but the letter is in {split_of[cid]}")
                continue
            if cid in facts.slots:
                facts.problems.append(f"{cid}: in {name}, and read by hand as well")
                continue
            facts.slots[cid] = letter.slots
            facts.conflicts[cid] = letter.conflicts
            facts.applied[cid] = letter.conventions
            if letter.began:
                facts.began[cid] = letter.began
            if letter.price_change is not None:
                facts.prices[cid] = letter.price_change
            facts.sources.update(letter.sources)
    facts.waiting = sorted({e["split"] for e in entries if _is_final(e)} - set(files))
    return facts


def convention_ids(manifest: Mapping[str, Any]) -> frozenset[str]:
    """The ids of the manifest's labelling conventions."""
    return frozenset(c["id"] for c in manifest.get("conventions", []) if isinstance(c, dict) and "id" in c)


def _tags(applied: Mapping[str, list[str]], *slots: str) -> list[str]:
    return sorted({i for slot in slots for i in applied.get(slot, [])})


def check_conventions(
    cid: str, truth: Mapping[str, Any], applied: Mapping[str, list[str]], known: Collection[str]
) -> list[str]:
    """The conventions a letter's facts apply exist, and are the ones each label is tagged with (a contract's
    term-end and cancel-by dates share the contract's tags)."""
    problems = [
        f"{cid} {slot}: unknown convention {i}"
        for slot in sorted(applied)
        for i in applied[slot]
        if i not in known
    ]
    parts: list[tuple[str, Mapping[str, Any], tuple[str, ...]]]
    parts = [(f"i{n}", item, (f"i{n}",)) for n, item in enumerate(truth["items"])]
    parts += [(f"o{n}", item, (f"o{n}",)) for n, item in enumerate(truth["optional_items"])]
    if truth["contract"]:
        parts.append(("contract", truth["contract"], ("term_end", "cancel_by")))
    for where, part, slots in parts:
        mine, tagged = _tags(applied, *slots), sorted(set(part.get("conventions") or []))
        if mine != tagged:
            problems.append(
                f"{cid} {where}: the facts apply conventions {mine}, the label is tagged {tagged}"
            )
    return problems


def check_dates(
    entries: list[dict[str, Any]], facts: Facts | None = None, conventions: Collection[str] = ()
) -> tuple[int, list[str]]:
    """Re-derive every dated label of ``entries`` from ``facts`` (the hand-read ones by default); ``conventions``
    are the manifest's convention ids."""
    facts = facts if facts is not None else hand_read()
    problems: list[str] = []
    checked = 0
    seen = set()
    for e in entries:
        if e["photo"]:
            continue
        cid = e["id"]
        seen.add(cid)
        letter = facts.slots.get(cid)
        if letter is None:
            problems.append(f"{cid}: no facts for this letter")
            continue
        slots = _slots(e["truth"])
        # a reading must be a plausible deadline: not before 'today', or after the window of a final split's letter
        until = e.get("valid_until")
        earliest = date.fromisoformat(until) + timedelta(days=1) if until else date.fromisoformat(e["today"])
        too_early = "not after the window" if until else "past"
        for slot in sorted(set(slots) | set(letter)):
            item, fact = slots.get(slot), letter.get(slot, "absent")
            if item is None:
                problems.append(f"{cid} {slot}: expected in truth but missing")
                continue
            label = item["expected_due"]
            if fact == "absent":
                if label is not None:
                    problems.append(f"{cid} {slot}: dated label {label} has no fact")
                continue
            if fact is None:
                if label is not None:
                    problems.append(f"{cid} {slot}: letter cannot be dated, label says {label}")
                continue
            if fact[0] == AMBIGUOUS:
                for cand in fact[1]:  # each reading must be a working day, not too early
                    day = date.fromisoformat(cand)
                    if not working_day(day, None) or day < earliest:
                        problems.append(
                            f"{cid} {slot}: candidate {cand} is not a plausible reading (weekday/holiday/{too_early})"
                        )
                if label != AMBIGUOUS or sorted(item.get("candidates", [])) != sorted(fact[1]):
                    problems.append(
                        f"{cid} {slot}: expected ambiguous {fact[1]}, label {label} {item.get('candidates')}"
                    )
                continue
            fn, args, region = cast(Rule, fact)  # absent, undatable and ambiguous facts went above
            mine = fn(*args, region=region)
            checked += 1
            if label != mine.isoformat():
                problems.append(f"{cid} {slot}: label {label}, independent {mine.isoformat()}")
            municipal = [land for land in (LAENDER if region is None else (region,))
                         if _with_municipal_holidays(fn, args, land) != mine]  # fmt: skip
            if municipal:
                problems.append(
                    f"{cid} {slot}: label {mine} depends on municipal-only holidays in {municipal}"
                )
            if region is None:
                differing = sorted(land for land in LAENDER if fn(*args, region=land) != mine)
                if differing:
                    problems.append(f"{cid} {slot}: Land unknown but {differing} holidays change {mine}")
            elif slot.startswith("i"):
                national = fn(*args, region=None)
                if bool(item.get("region_sensitive")) != (national != mine):
                    problems.append(
                        f"{cid} {slot}: region_sensitive={item.get('region_sensitive')}, nationwide gives {national}"
                    )
                if national != mine and item.get("due_if_region_ignored") != national.isoformat():
                    problems.append(
                        f"{cid} {slot}: due_if_region_ignored {item.get('due_if_region_ignored')} != {national}"
                    )
        if cid in facts.applied:
            problems += check_conventions(cid, e["truth"], facts.applied[cid], conventions)
        if cid in facts.prices:
            effective, letter_date, basis, old, new = facts.prices[cid]
            pc = e["truth"]["price_change"] or {}
            sc = pc.get("special_cancellation") or {}
            want = {
                "effective_date": effective.isoformat(),
                "old_amount": old,
                "new_amount": new,
                "extra_cost_per_year": round((new - old) * 12, 2),
                "basis": basis,
                "cancel_by_to_avoid_new_price": (effective - timedelta(days=1)).isoformat(),
                # EnWG: cancel with effect from the change; TKG § 57: three months from receipt (earliest = letter date)
                "window_end": (effective - timedelta(days=1)).isoformat() if "EnWG" in basis else None,
                "window_end_if_received_on_letter_date": None
                if "EnWG" in basis
                else plus_months(letter_date, 3).isoformat(),
            }
            got = {
                **{
                    k: pc.get(k)
                    for k in ("effective_date", "old_amount", "new_amount", "extra_cost_per_year")
                },
                **sc,
            }
            checked += 2  # the two date fields (cancel-by and window end)
            for key, value in want.items():
                if got.get(key) != value:
                    problems.append(f"{cid}: price_change {key} = {got.get(key)!r}, independent {value!r}")
        for slot, others in sorted(facts.conflicts.get(cid, {}).items()):  # the other dates a letter states
            target = slots.get(slot)
            if target is None:
                problems.append(f"{cid} {slot}: conflicting dates for a slot the truth does not have")
                continue
            cands = target.get("candidates") or []
            for fn, args, region in others:
                other = fn(*args, region=region).isoformat()
                checked += 1
                if other not in cands or target["expected_due"] != min(cands):
                    problems.append(
                        f"{cid} {slot}: candidates {cands} should hold {other} and the label the earlier date"
                    )
    # a manifest that holds a split holds every letter its facts name (one of a facts.json file always)
    present = {e["split"] for e in entries}
    for cid in facts.slots:
        if cid not in seen and (cid in facts.applied or cid.split("-", 1)[0] in present):
            problems.append(f"{cid}: facts for a letter that is not in the manifest")
    return checked, problems


def check_facts(
    root: Path, entries: list[dict[str, Any]], conventions: Collection[str], *, require_facts: bool = False
) -> dict[str, Any]:
    """The dates of ``entries`` re-derived from the facts under ``root``; a final split without its facts.json is
    listed (``splits_without_facts``), and with ``require_facts`` it is a problem."""
    facts = gather_facts(root, entries)
    problems = list(facts.problems)
    if require_facts:
        problems += [
            f"{split}: no {split}/facts.json, so none of its dates is re-derived" for split in facts.waiting
        ]
    skip = {*facts.waiting, *facts.unreadable}
    checked, date_problems = check_dates([e for e in entries if e["split"] not in skip], facts, conventions)
    return {
        "dated_labels_checked": checked,
        "date_problems": problems + date_problems,
        "splits_without_facts": facts.waiting,
        "fact_sources": dict(sorted(facts.sources.items())),
        "procedure_began": facts.began,
    }


def _dated(value: Any) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and _ISO_DAY.fullmatch(value) else None


def check_window(entries: list[dict[str, Any]]) -> list[str]:
    """A final split's letter is read on its ``final_day`` and stays valid through ``valid_until``: every scored
    date (an ambiguous or conflicting item's candidates too), contract date (an ambiguous slot's candidates too) and
    appointment lies after it."""
    problems = []
    for e in entries:
        if e["photo"] or not _is_final(e):
            continue
        cid = e["id"]
        if "final_day" not in e or "valid_until" not in e:
            problems.append(f"{cid}: final_day and valid_until come together")
            continue
        final_day, until = date.fromisoformat(e["final_day"]), date.fromisoformat(e["valid_until"])
        if date.fromisoformat(e["today"]) != final_day:
            problems.append(f"{cid}: today {e['today']} is not its final day {e['final_day']}")
        if until < final_day:
            problems.append(f"{cid}: valid until {e['valid_until']}, before its final day {e['final_day']}")
        truth = e["truth"]
        dates: list[tuple[str, Any]] = []
        for n, item in enumerate(truth["items"]):
            dates += [
                (f"items[{n}]", value)
                for value in [item.get("expected_due"), *(item.get("candidates") or [])]
            ]
        for n, item in enumerate(truth["optional_items"]):
            if item.get("kind") == "appointment":
                dates.append((f"optional_items[{n}]", item.get("expected_due")))
        contract = truth["contract"] or {}
        for key in CONTRACT_SLOTS.values():
            if contract:
                candidates = (contract.get("candidates") or {}).get(key) or []
                dates += [(f"contract.{key}", value) for value in [contract.get(key), *candidates]]
        seen = set()
        for where, value in dates:
            day = _dated(value)
            if day is not None and day <= until and (where, day) not in seen:
                seen.add((where, day))
                problems.append(f"{cid} {where}: {day} is not after the window (valid until {until})")
    return problems


_MONTHS_DE = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]
_MONTHS_EN = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _date_forms(iso: str) -> list[str]:
    d = date.fromisoformat(iso)
    return [
        f"{d.day:02d}.{d.month:02d}.{d.year}",
        f"{d.day}. {_MONTHS_DE[d.month - 1]} {d.year}",
        f"{d.day} {_MONTHS_EN[d.month - 1]} {d.year}",
        f"{_MONTHS_EN[d.month - 1]} {d.day}, {d.year}",
        f"{d.day:02d}/{d.month:02d}/{d.year}",
        f"{d.month:02d}/{d.day:02d}/{d.year}",
    ]


def _amount(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return re.sub(r"\s+", " ", " ".join(page.extract_text() or "" for page in pdf.pages))


def check_text(entries: list[dict[str, Any]], root: Path) -> tuple[dict[str, str], list[str]]:
    problems: list[str] = []
    texts: dict[str, str] = {}
    for e in entries:
        if e["photo"]:
            continue
        cid, t = e["id"], e["truth"]
        text = texts[cid] = _pdf_text(root / e["file"])

        def has_date(iso: str, text: str = text) -> bool:
            return any(form in text for form in _date_forms(iso))

        if t["sender_name"] not in text:
            problems.append(f"{cid}: sender {t['sender_name']!r} not in the letter")
        if t["document_date"] and not has_date(t["document_date"]):
            problems.append(f"{cid}: document date {t['document_date']} not in the letter")
        for ref in t["references"]:
            if ref["value"] not in text:
                problems.append(f"{cid}: reference {ref} not in the letter")
            if re.fullmatch(r"[–—-]|\d{1,2}\.\d{1,2}\.\d{4}|[A-Za-zä]+ \d{4}", ref["value"].strip()):
                problems.append(f"{cid}: reference {ref} is not an identifier")
        for amount in t["amounts"]:
            if _amount(amount) not in text and f"{amount:,.2f}" not in text:
                problems.append(f"{cid}: amount {amount} not in the letter")
        word = {"einspruch": "Einspruch", "widerspruch": "Widerspruch", "klage": "Klage"}.get(
            t["remedy_type"]
        )
        if word and word not in text:
            problems.append(f"{cid}: remedy {t['remedy_type']} not named in the letter")
        if t["remedy_type"] == "none" and "Rechtsbehelfsbelehrung" in text:
            problems.append(f"{cid}: remedy 'none' but the letter has a Rechtsbehelfsbelehrung")
        for slot, item in _slots(t).items():
            spec = item.get("spec") or {}
            for key in ("date", "anchor_date", "posted_on"):
                iso = spec.get(key)
                if not iso or has_date(iso):
                    continue
                d = date.fromisoformat(iso)
                if e["family"] == "price_increase" and has_date((d + timedelta(days=1)).isoformat()):
                    continue  # 'cancel before the change' — the letter states the effective date
                if f"{d.day:02d}.{d.month:02d}." in text:
                    continue  # recurring date printed without the year
                problems.append(f"{cid} {slot}: spec {key} {iso} not in the letter")
            if item.get("amount") is not None and _amount(item["amount"]) not in text:
                problems.append(f"{cid} {slot}: item amount {item['amount']} not in the letter")
            if item.get("expected_time") and item["expected_time"] not in text:
                problems.append(f"{cid} {slot}: time {item['expected_time']} not in the letter")
    return texts, problems


_CUE = re.compile(
    r"Monat|Woche|Tag|Frist|within|days|by |bis |fällig|Zahlungsziel|Einspruch|Widerspruch|Klage", re.I
)


def shared_deadline_sentences(entries: list[dict[str, Any]], texts: dict[str, str]) -> list[str]:
    """Sentences (numbers normalised) with a deadline cue that occur in letters of more than one split
    (dev, test, holdout, holdout2, holdout3, holdout4, newkinds), each prefixed with the splits it occurs in."""
    where: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        if e["photo"]:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", texts[e["id"]]):
            norm = re.sub(r"\d", "#", sentence).strip()
            if len(norm) >= 40 and _CUE.search(norm):
                where[norm].add(e["split"])
    return sorted(f"{'+'.join(sorted(splits))}: {s}" for s, splits in where.items() if len(splits) > 1)


#: The day from which a Land's authorities count the 4th day after a decision's posting (the 3rd day before it), by
#: each Land's text in evals/law/laender.txt, kept apart from the generator's table (only the tests compare the two):
#: from 1 Jan 2025 where the Land's own act says so or applies the federal VwVfG (BB, BE, BY, MV, NI, NW, SN, SH: the
#: amendment of § 110 Abs. 2 LVwG took effect that day; TH: the act of 2 July 2024, Art. 90); HH from 14 May 2025
#: (HmbGVBl. Nr. 17 of 13 May 2025 S. 338, the day after its issue under Art. 54 of Hamburg's constitution); BW from
#: 7 Feb 2025 (§ 102b LVwVfG). The dataset drew SH letters from 10 Jun 2025 only, a bound kept from before its text was
#: read; no label depends on it.
LAND_FOUR_DAY_START: dict[str, date] = {
    **{land: D(2025, 1, 1) for land in ("BB", "BE", "BY", "MV", "NI", "NW", "SN", "SH", "TH")},
    "HH": D(2025, 5, 14),
    "BW": D(2025, 2, 7),
}
#: Länder whose authorities count the 3rd day after posting: Hessen (§ 41 Abs. 2 HVwVfG). No 4th day starts there.
LAND_THIRD_DAY = frozenset({"HE"})
#: Länder that keep their old wording, the 3rd day, for a procedure begun before their switch and not finished:
#: § 102b LVwVfG, Art. 98 BayVwVfG, § 120a VwVfG M-V. NW's § 97 applies the law in force to each step, so a posting
#: from 1 Jan 2025 gets the 4th day there.
LAND_OLD_PROCEDURES: dict[str, date] = {"BW": D(2025, 2, 7), "BY": D(2025, 1, 1), "MV": D(2025, 1, 1)}
#: Länder whose text could not be read: no Land VwVfG label may come from one.
LAND_UNVERIFIED = frozenset({"HB", "RP", "SL", "ST"})


def land_fiction_days(land: str | None, posted: date, began: date | None = None) -> int | None:
    """The day after posting on which a Land authority's posted decision counts as delivered (3 or 4), by the Land's
    own law; ``began`` is the day its procedure began, where known. None where no verified text gives it (no Land, or
    a Land whose text could not be read)."""
    if land is None or land not in LAENDER or land in LAND_UNVERIFIED:
        return None
    if posted < D(2025, 1, 1) or land in LAND_THIRD_DAY or posted < LAND_FOUR_DAY_START[land]:
        return 3
    switch = LAND_OLD_PROCEDURES.get(land)
    return 3 if switch is not None and began is not None and began < switch else 4


def _land_vwvfg_slots(entry: Mapping[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """A letter's Land VwVfG deemed-delivery slots: (slot, item, spec)."""
    if entry["photo"]:
        return []
    out = []
    for slot, item in _slots(entry["truth"]).items():
        spec = item.get("spec") or {}
        if (
            spec.get("delivery_scope") == "vwvfg"
            and spec.get("anchor", "deemed_delivery") == "deemed_delivery"
        ):
            out.append((slot, item, spec))
    return out


def check_land_windows(entries: list[dict[str, Any]]) -> list[str]:
    """Every hand-read Land VwVfG deemed-delivery label (items, optional items) counts from a posting day on which its
    Land counted the 4th day, as ``remedy`` does, or from one before 2025, when every Land counted the 3rd: the label's
    ``posted_on``, else the letter's date. So none comes from Hessen, from a Land without a verified text or from a
    letter that names no Land. A final split's labels are checked by :func:`check_land_rules` instead."""
    problems = []
    for e in entries:
        if _is_final(e):
            continue
        land = e["authority_region"]
        start = LAND_FOUR_DAY_START.get(land) if land is not None else None
        for slot, _item, spec in _land_vwvfg_slots(e):
            posted = spec.get("posted_on") or e["truth"]["document_date"]
            if posted is None or date.fromisoformat(posted) < D(2025, 1, 1):
                continue
            if start is None:
                problems.append(
                    f"{e['id']} {slot}: posted {posted}, but {land} has no 4-day start for a Land VwVfG label"
                )
            elif date.fromisoformat(posted) < start:
                problems.append(
                    f"{e['id']} {slot}: posted {posted}, before the {land} 4-day rule ({start.isoformat()})"
                )
    return problems


def _land_period_end(fiction: date, spec: Mapping[str, Any], region: str) -> date | None:
    unit, amount = spec.get("unit"), spec.get("amount")
    if unit not in UNITS or not isinstance(amount, int):
        return None
    end = _forward(fiction, amount, unit, region)
    return next_working_day(end, region) if spec.get("shift") is not False else end


def check_land_rules(
    entries: list[dict[str, Any]], began: Mapping[str, Mapping[str, date]] | None = None
) -> list[str]:
    """Every Land VwVfG deemed-delivery label by its Land's own rule, with this file's own table and arithmetic: the
    authority's Land (``authority_region``) has a verified text, and the label is the period counted from that Land's
    day after posting (:func:`land_fiction_days`) under the Land's holidays. ``began`` gives the day a slot's
    procedure began where its facts state it; for a BW, BY or MV letter after the switch whose facts do not, either
    day may be the letter's (the date re-derived from its facts decides)."""
    problems = []
    for e in entries:
        cid, land = e["id"], e["authority_region"]
        for slot, item, spec in _land_vwvfg_slots(e):
            if land is None:
                problems.append(f"{cid} {slot}: a Land authority's decision that names no Land")
                continue
            if land in LAND_UNVERIFIED:
                problems.append(
                    f"{cid} {slot}: no verified text of {land}'s delivery rule (evals/law/laender.txt)"
                )
                continue
            label = _dated(item.get("expected_due"))
            posted = _dated(spec.get("posted_on") or e["truth"]["document_date"])
            if label is None or posted is None:
                continue
            start = (began or {}).get(cid, {}).get(slot)
            days = {land_fiction_days(land, posted, start)}
            if start is None and land in LAND_OLD_PROCEDURES and posted >= LAND_FOUR_DAY_START[land]:
                days = {3, 4}
            ends = {
                n: _land_period_end(posted + timedelta(days=n), spec, land)
                for n in sorted(d for d in days if d)
            }
            if label not in ends.values():
                gives = " or ".join(f"{end} (day {n})" for n, end in ends.items())
                problems.append(f"{cid} {slot}: label {label}, {land}'s own delivery day gives {gives}")
    return problems


def check_photos(entries: list[dict[str, Any]]) -> list[str]:
    by_id = {e["id"]: e for e in entries}
    problems = []
    for e in entries:
        if e["photo"]:
            src = by_id.get(e["source_id"])
            if src is None or src["pages"] != 1 or src["truth"] != e["truth"]:
                problems.append(f"{e['id']}: photo does not share the truth of a one-page source PDF")
    return problems


#: The report's lists of problems (any of them makes ``main`` exit 1).
PROBLEM_KEYS = (
    "date_problems",
    "text_problems",
    "shared_split_sentences",
    "photo_problems",
    "land_window_problems",
    "land_rule_problems",
    "window_problems",
)


def run(root: Path, *, require_facts: bool = False) -> dict[str, Any]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["entries"]
    dates = check_facts(root, entries, convention_ids(manifest), require_facts=require_facts)
    texts, text_problems = check_text(entries, root)
    leaks = shared_deadline_sentences(entries, texts)
    photo_problems = check_photos(entries)
    land_window_problems = check_land_windows(entries)
    land_rule_problems = check_land_rules(entries, dates["procedure_began"])
    return {
        "letters": sum(1 for e in entries if not e["photo"]),
        "photos": sum(1 for e in entries if e["photo"]),
        "dated_labels_checked": dates["dated_labels_checked"],
        "date_problems": dates["date_problems"],
        "text_problems": text_problems,
        "shared_split_sentences": leaks,
        "photo_problems": photo_problems,
        "land_window_problems": land_window_problems,
        "land_rule_problems": land_rule_problems,
        "window_problems": check_window(entries),
        "splits_without_facts": dates["splits_without_facts"],
        "fact_sources": dates["fact_sources"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dataset", type=Path, default=Path(__file__).resolve().parent / "dataset")
    parser.add_argument(
        "--require-facts",
        action="store_true",
        help="a final split without its facts.json is a problem (once the blind audit's facts are in)",
    )
    args = parser.parse_args(argv)
    report = run(args.dataset, require_facts=args.require_facts)
    print(
        f"letters {report['letters']} (+ {report['photos']} photos), dated labels re-derived: {report['dated_labels_checked']}"
    )
    if report["fact_sources"]:
        print(
            "facts.json facts by source: " + ", ".join(f"{k} {v}" for k, v in report["fact_sources"].items())
        )
    if report["splits_without_facts"]:
        print(f"dates not re-derived yet (no facts.json): {', '.join(report['splits_without_facts'])}")
    failed = False
    for key in PROBLEM_KEYS:
        print(f"{key}: {len(report[key])}")
        for line in report[key]:
            print(f"  - {line}")
        failed |= bool(report[key])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
