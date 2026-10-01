"""Case model and truth builders shared by all families.

A *case* is one benchmark document: the letter to render plus its ground truth. Truth items are
built from a ``calc(region)`` closure so the generator can prove, for every dated item, that

* the label does not depend on municipal-only holidays (never well-defined), and
* when the authority's Land is unknown, no Land's holiday calendar would change the date
  (so "unknown region → nationwide holidays only" and the legally correct date coincide).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from . import law
from .law import Derivation, fmt
from .pdf import Letter
from .text import rng_for

Calc = Callable[[str | None], tuple[date, Derivation]]

DOCUMENT_KINDS = {
    "tax_assessment",
    "tax_letter",
    "authority_letter",
    "residence_permit",
    "social_insurance",
    "health_insurance",
    "invoice",
    "dunning",
    "contract",
    "contract_change",
    "price_increase",
    "cancellation_confirmation",
    "payslip",
    "bank_letter",
    "insurance",
    "rent_lease",
    "utility_bill",
    "university",
    "employment",
    "appointment",
    "fine",
    "receipt",
    "identity_document",
    "broadcasting_fee",
    "certificate",
    "personal",
    "other",
}  # fmt: skip  (models.DocumentKind, copied — the generator must not import the product)
ITEM_KINDS = {"deadline", "payment", "appointment", "task", "expiry"}
NATURES = {"objection", "payment", "declaration", "notice", "appointment", "other"}
REMEDIES = {"einspruch", "widerspruch", "klage", "none", "unclear"}
WARNINGS = {"scam", "injection", "hidden_text", "conflicting_dates", "missing_date"}
#: The template variants of each split: dev (prompts may be tuned on it), test (published), holdout (written after
#: extraction prompt 11, recorded once with frozen prompts), holdout2 (written after the release's last code change,
#: recorded once, nothing tuned on it). Adversarial letters are one-offs in test, holdout and holdout2.
SPLIT_VARIANTS = {"dev": ("A", "B"), "test": ("C", "D"), "holdout": ("E", "F"), "holdout2": ("G", "H")}


@dataclass
class Case:
    id: str
    split: str  # dev | test | holdout | holdout2
    family: str
    variant: str
    letter: Letter
    truth: dict[str, Any]
    today: date
    authority_region: str | None
    key_phrases: list[str]
    recipient_region: str | None = None
    hidden_phrases: list[str] = field(default_factory=list)
    photo: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        t = self.truth
        assert t["kind"] in DOCUMENT_KINDS, t["kind"]
        assert t["remedy_type"] in REMEDIES, t["remedy_type"]
        assert set(t["expected_warnings"]) <= WARNINGS
        for item in [*t["items"], *t.get("optional_items", [])]:
            assert item["kind"] in ITEM_KINDS, item
            assert item["nature"] in NATURES, item
            due = item["expected_due"]
            if due not in (None, "ambiguous"):
                assert date.fromisoformat(due) >= self.today, (self.id, "deadline before today", due)
        assert self.id.startswith(f"{self.split}-"), self.id
        if self.family == "adversarial":
            assert self.split != "dev", self.id
        else:
            assert self.variant in SPLIT_VARIANTS[self.split], self.id


def today_after(anchor: date, case_id: str, lo: int = 2, hi: int = 6) -> date:
    """The day the person reads the letter: ``anchor`` + 2..6 days (seeded per case)."""
    return anchor + timedelta(days=rng_for("today", case_id).randint(lo, hi))


# --------------------------------------------------------------------------------------------------
# truth items
# --------------------------------------------------------------------------------------------------


def dated_item(
    *,
    kind: str,
    nature: str,
    title: str,
    calc: Calc,
    region: str | None,
    spec: dict[str, Any],
    rule: str,
    amount: float | None = None,
    expected_time: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """An item whose expected date is computed by ``calc`` under the label's region."""
    due, why = calc(region)
    # 1) municipal-only holidays must never matter
    with law.municipal_holidays_counted():
        assert calc(region)[0] == due, f"{title}: label depends on a municipal-only holiday"
        if region is None:
            for land in law.LAENDER:
                assert calc(land)[0] == due, f"{title}: label depends on a municipal-only holiday ({land})"
    # 2) sensitivity to the Land's holidays
    national = calc(None)[0]
    by_land = {land: calc(land)[0] for land in law.LAENDER}
    if region is None:
        differing = sorted(land for land, d in by_land.items() if d != due)
        assert not differing, f"{title}: region unknown but {differing} holidays would change {due}"
        sensitive = False
    else:
        sensitive = national != due
    item: dict[str, Any] = {
        "kind": kind,
        "nature": nature,
        "title": title,
        "expected_due": due.isoformat(),
        "expected_time": expected_time,
        "spec": spec,
        "amount": amount,
        "derivation": f"{rule} {why.text()} Expected: {fmt(due)}.",
        "region_sensitive": sensitive,
    }
    if sensitive:
        item["due_if_region_ignored"] = national.isoformat()
    if note:
        item["note"] = note
    return item


def undated_item(
    *,
    kind: str,
    nature: str,
    title: str,
    spec: dict[str, Any],
    derivation: str,
    expected_due: str | None = None,
    amount: float | None = None,
    note: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """An item without a single computable date (``expected_due`` None or 'ambiguous')."""
    item: dict[str, Any] = {
        "kind": kind,
        "nature": nature,
        "title": title,
        "expected_due": expected_due,
        "expected_time": None,
        "spec": spec,
        "amount": amount,
        "derivation": derivation,
        "region_sensitive": False,
    }
    if note:
        item["note"] = note
    item.update(extra)
    return item


def spec(
    type_: str,
    *,
    anchor: str | None = None,
    amount: int | None = None,
    unit: str | None = None,
    delivery_scope: str | None = None,
    posted_on: date | None = None,
    anchor_date: date | None = None,
    date_: date | None = None,
    time: str | None = None,
    shift: bool | None = None,
) -> dict[str, Any]:
    return {
        "type": type_,
        "anchor": anchor,
        "amount": amount,
        "unit": unit,
        "delivery_scope": delivery_scope,
        "posted_on": posted_on.isoformat() if posted_on else None,
        "anchor_date": anchor_date.isoformat() if anchor_date else None,
        "date": date_.isoformat() if date_ else None,
        "time": time,
        "shift": shift,
    }


# -- concrete item builders --------------------------------------------------------------------------

REMEDY_RULES = {
    "ao": (
        "§ 108 Abs. 3 AO",
        "Einspruch against a tax administrative act: one month after Bekanntgabe (§ 355 Abs. 1 AO).",
    ),
    "vwvfg_widerspruch": (
        "§ 31 Abs. 3 VwVfG / § 57 Abs. 2 VwGO i.V.m. § 222 Abs. 2 ZPO",
        "Widerspruch: one month after Bekanntgabe (§ 70 Abs. 1 VwGO); Land VwVfG 4-day fiction without shift.",
    ),
    "vwvfg_klage": (
        "§ 57 Abs. 2 VwGO i.V.m. § 222 Abs. 2 ZPO",
        "Klage (no Vorverfahren): one month after Bekanntgabe (§ 74 Abs. 1 S. 2 VwGO); Land VwVfG 4-day fiction without shift.",
    ),
    "sgbx": (
        "§ 64 Abs. 3 SGG / § 26 Abs. 3 SGB X",
        "Widerspruch: one month after Bekanntgabe (§ 84 Abs. 1 SGG).",
    ),
}


def objection_item(
    *,
    posted: date,
    scope: str,
    remedy: str,
    region: str | None,
    title: str,
    note: str | None = None,
    kind: str = "deadline",
    nature: str = "objection",
    rule: str | None = None,
    money: float | None = None,
    shift_citation: str | None = None,
) -> dict[str, Any]:
    """One-month period after the deemed notification of a posted administrative act (remedy period,
    or a payment period the authority set 'innerhalb eines Monats nach Bekanntgabe'). ``shift_citation``
    names the rule that moves the end where it is not the scope's usual one (e.g. an SGB X decision that
    goes to the administrative courts)."""
    key = "ao" if scope == "ao" else ("sgbx" if scope == "sgbx" else f"vwvfg_{remedy}")
    default_shift, default_rule = REMEDY_RULES[key]
    shift_citation = shift_citation or default_shift
    rule = rule or default_rule

    def calc(region: str | None) -> tuple[date, Derivation]:
        why = Derivation()
        notified = law.deemed_delivery(posted, scope, region, why)
        end = law.period_end(notified, 1, "months", region, why, shift=True, shift_citation=shift_citation)
        return end, why

    return dated_item(
        kind=kind,
        nature=nature,
        title=title,
        calc=calc,
        region=region,
        spec=spec(
            "relative",
            anchor="deemed_delivery",
            amount=1,
            unit="months",
            delivery_scope=scope,
            posted_on=posted,
            shift=True,
        ),
        rule=rule,
        amount=money,
        note=note,
    )


def event_period_item(
    *,
    event: date,
    amount: int,
    unit: str,
    region: str | None,
    kind: str,
    nature: str,
    title: str,
    anchor: str,
    rule: str,
    shift_citation: str,
    money: float | None = None,
    note: str | None = None,
    forbid_saturday_end: bool = False,
    require_no_shift: bool = False,
) -> dict[str, Any]:
    """A period counted from an event day that is stated in the document (letter date, Zustellung)."""

    def calc(region: str | None) -> tuple[date, Derivation]:
        why = Derivation()
        raw = law.raw_period_end(event, amount, unit, region, why)
        if forbid_saturday_end:
            # A Werktage count ending on a Saturday would raise a § 193 BGB question — never generated.
            assert raw.weekday() != 5, f"{title}: Werktage period ends on a Saturday ({raw})"
        if require_no_shift:
            assert law.is_working_day(raw, region), f"{title}: raw end {raw} would need a shift"
        end = law.shift_to_working_day(raw, region, why, shift_citation)
        return end, why

    return dated_item(
        kind=kind,
        nature=nature,
        title=title,
        calc=calc,
        region=region,
        spec=spec(
            "relative",
            anchor=anchor,
            amount=amount,
            unit=unit,
            anchor_date=event if anchor == "explicit_date" else None,
            shift=True,
        ),
        rule=rule,
        amount=money,
        note=note,
    )


def fixed_item(
    *,
    due: date,
    region: str | None,
    kind: str,
    nature: str,
    title: str,
    rule: str,
    time: str | None = None,
    money: float | None = None,
    note: str | None = None,
    appointment: bool = False,
) -> dict[str, Any]:
    """A date stated verbatim in the letter. Deadlines are generated on working days only, so the
    § 193 BGB / § 108 Abs. 3 AO question for fixed dates never arises; appointments never move."""

    def calc(region: str | None) -> tuple[date, Derivation]:
        why = Derivation()
        if appointment:
            why.add(
                f"Appointment on {fmt(due)}" + (f" at {time}" if time else "")
                + " as stated; appointments are kept as set, even on a weekend or holiday (no shift)."
            )  # fmt: skip
        else:
            assert law.is_working_day(due, region), f"{title}: fixed deadline {due} is not a working day"
            why.add(
                f"Fixed date stated in the letter: {fmt(due)}; it is a working day, so no shift question arises."
            )
        return due, why

    return dated_item(
        kind=kind,
        nature=nature,
        title=title,
        calc=calc,
        region=region,
        spec=spec("fixed", anchor="explicit_date", date_=due, time=time, shift=not appointment),
        rule=rule,
        amount=money,
        expected_time=time,
        note=note,
    )


_MONTHS = "Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember"
_NOT_AN_IDENTIFIER = re.compile(rf"[–—-]|\d{{1,2}}\.\d{{1,2}}\.\d{{4}}|(?:{_MONTHS}) \d{{4}}")


def identifier_references(references: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Info-block lines that are references a person would quote. A placeholder dash ('Ihr Zeichen –'), a date
    ('Ihr Schreiben vom 08.09.2025') or a billing month ('Rechnung Februar 2026') is printed on the letter but is not an
    identifier, so it is not a reference label."""
    return [(label, value) for label, value in references if not _NOT_AN_IDENTIFIER.fullmatch(value.strip())]


def truth(
    *,
    kind: str,
    sender: str,
    document_date: date | None,
    references: list[tuple[str, str]],
    amounts: list[float],
    remedy: str = "none",
    items: list[dict[str, Any]],
    optional_items: list[dict[str, Any]] | None = None,
    contract: dict[str, Any] | None = None,
    price_change: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    expect_low_confidence: bool = False,
    lang: str = "de",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "kind_also_accepted": [],  # filled in by generate.py for letters that honestly fit two document kinds
        "language": lang,
        "sender_name": sender,
        "document_date": document_date.isoformat() if document_date else None,
        "references": [
            {"label": label, "value": value} for label, value in identifier_references(references)
        ],
        "amounts": amounts,
        "remedy_type": remedy,
        "items": items,
        "optional_items": optional_items or [],
        "contract": contract,
        "price_change": price_change,
        "expected_warnings": warnings or [],
        "expect_low_confidence": expect_low_confidence,
    }
