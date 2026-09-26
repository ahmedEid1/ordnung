"""Which rules a high-stakes letter's dates follow (ADR 0002, ADR 0007).

The model reads, code decides. The extraction prompt and schema stay as they were recorded, so the
model never names these letters itself; code recognises them from its reading with two short
policies, and cases the policies do not decide are documented limitations, not bugs.

**1. The kind of letter** (:func:`classify_letter`), from structured parts of the reading first:

=========================  ============================================================================
``enforcement_order``      sent by a court (the sender's name ends a word in "gericht": Amtsgericht,
                           Mahngericht — not a bailiff, *Gerichtsvollzieher*, or a court cashier,
                           *Gerichtskasse*) and the reading names a *Vollstreckungsbescheid*
``court_payment_order``    sent by a court and the reading names a *Mahnbescheid*. A debt collector
                           threatening one is not a court, so its letter stays a reminder.
``dismissal``              the reading reports a termination by the other side
                           (``termination_by_provider``) about a job (kind ``employment``, sender
                           ``employer`` or an employment contract)
``landlord_notice``        a termination by the other side about a tenancy (kind ``rent_lease``,
                           sender ``landlord`` or a rent contract)
``rent_increase``          a price increase about a tenancy that asks for consent ("Zustimmung",
                           "Vergleichsmiete", "Mietspiegel", § 558 BGB) — not a graduated or index
                           rent or a modernisation increase, which need no consent
=========================  ============================================================================

These are the letters whose *dates* depend on their kind, so the kind is filed with the letter. An
operating-cost statement's dates don't (its objection period is an ordinary twelve months), so it
is recognised on read for its card only (:func:`names_statement`: the reading names a Betriebs-, Heiz- or
Nebenkostenabrechnung and the sender is not a utility); the person may still file a letter as
``operating_costs``.

"The reading names" means its title, summary, quotes, date wordings and legal bases, never the
model's advice prose (``explanation``, ``warnings``), which may mention a Mahnbescheid as a threat.
Missed: a letter whose reading lacks these signals (e.g. no termination recorded) keeps the model's
kind; the person can set the kind on the letter, and its dates are then recomputed.

**2. The rule of a date** (:func:`kind_statute`, :func:`special_rule`): a date follows the statute
its ``legal_basis`` or wording cites; if it cites none, a court order's objection, payment and
declaration periods follow the court rule (two weeks from delivery), a rent increase's declarations
the consent period and a landlord's notice's objections the § 574b period. Wordings that decide on
their own: "Kündigungsschutzklage", "arbeitsuchend", and a consumer "Widerrufsfrist/-recht/
-belehrung" from a sender that is not an authority (an authority's *Widerruf* is a revocation).

**3. Dates the law adds** (:func:`derived_deadlines`): these letters rarely state their most
important deadline (a dismissal never mentions the three weeks for a court action), so each kind
brings the deadlines the law sets, which the pipeline files as to-dos unless an extracted date
already follows that rule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date

from ordnung.models import DateNature, DateSpec, DocumentExtraction, HighStakesKind, LetterKind, Priority

_COURT_SENDER = re.compile(r"gericht\b", re.I)
_MAHNBESCHEID = re.compile(r"mahnbescheid", re.I)
_VOLLSTRECKUNGSBESCHEID = re.compile(r"vollstreckungsbescheid", re.I)
_CONSENT = re.compile(
    r"zustimm|vergleichsmiete|mietspiegel|\b558\b[^§]{0,20}\bBGB\b|\bconsent\b|\bagree", re.I
)
_NO_CONSENT_INCREASE = re.compile(
    r"staffelmiete|indexmiete|verbraucherpreisindex|modernisierung|\b55(?:7a|7b|9)\b[^§]{0,20}\bBGB\b", re.I
)
_OPERATING_COSTS = re.compile(
    r"(?:betriebs|neben|heiz(?:ungs)?)kosten-?\s?abrechnung|(?:betriebs|neben)-\s*und\s+heizkostenabrechnung|"
    r"operating[- ]costs? statement|service[- ]charge statement",
    re.I,
)

_SGB3_38 = re.compile(r"\b38\b[^§]{0,20}\bSGB\s*(?:III|3)\b|arbeits?suchend", re.I)
_BGB_558B = re.compile(r"\b558b\b[^§]{0,20}\bBGB\b", re.I)
_BGB_574B = re.compile(r"\b574b?\b[^§]{0,20}\bBGB\b", re.I)
_WITHDRAWAL = re.compile(
    r"\b35[56]\b[^§]{0,20}\bBGB\b|widerrufs(?:frist|recht|belehrung)|right of withdrawal|withdrawal period",
    re.I,
)

_EMPLOYMENT = ("employment", "employer")
_TENANCY = ("rent_lease", "landlord", "rent")
_DECLARING: tuple[DateNature, ...] = ("objection", "payment", "declaration")


def _reading_text(extraction: DocumentExtraction) -> str:
    """What the letter says according to the reading (not the model's advice prose)."""
    parts = [extraction.title, extraction.summary]
    for item in extraction.items:
        parts += [item.title, item.quote, item.date.text, item.date.legal_basis or ""]
    for fact in extraction.key_facts:
        parts += [fact.label, fact.value, fact.quote]
    if extraction.remedy is not None:
        remedy = extraction.remedy
        parts += [remedy.quote or "", remedy.period_text or "", remedy.addressee or ""]
    if extraction.change is not None:
        parts.append(extraction.change.quote)
    return "\n".join(part for part in parts if part)


def _about(extraction: DocumentExtraction, markers: tuple[str, ...]) -> bool:
    """Whether the letter's kind, its sender's kind or its contract's category is one of ``markers``."""
    sender = extraction.sender.kind if extraction.sender else None
    category = extraction.contract.category if extraction.contract else None
    return extraction.kind in markers or sender in markers or category in markers


def classify_letter(extraction: DocumentExtraction) -> HighStakesKind | None:
    """The high-stakes kind of a letter from the model's reading, or ``None`` (policy 1 above)."""
    text = _reading_text(extraction)
    sender = extraction.sender
    if sender is not None and _COURT_SENDER.search(sender.name):
        if _VOLLSTRECKUNGSBESCHEID.search(text):
            return "enforcement_order"
        if _MAHNBESCHEID.search(text):
            return "court_payment_order"
    change = extraction.change.type if extraction.change else None
    tenancy = _about(extraction, _TENANCY)
    if change == "termination_by_provider":
        if _about(extraction, _EMPLOYMENT):
            return "dismissal"
        if tenancy:
            return "landlord_notice"
    if (
        tenancy
        and change == "price_increase"
        and _CONSENT.search(text)
        and not _NO_CONSENT_INCREASE.search(text)
    ):
        return "rent_increase"
    return None


def names_statement(extraction: DocumentExtraction) -> bool:
    """Whether a reading is an operating-cost statement (its card is worked out on read)."""
    sender = extraction.sender
    return bool(_OPERATING_COSTS.search(_reading_text(extraction))) and (
        sender is None or sender.kind != "utility"
    )


def letter_kind(extraction: DocumentExtraction) -> LetterKind:
    """The kind a letter is filed as: its high-stakes kind, else the model's."""
    return classify_letter(extraction) or extraction.kind


def announced_end(extraction: DocumentExtraction) -> date | None:
    """The end of the job or tenancy a termination announces (its effective date), if stated."""
    change = extraction.change
    if change is None or change.type != "termination_by_provider" or not change.effective_date:
        return None
    try:
        return date.fromisoformat(change.effective_date.strip()[:10])
    except ValueError:
        return None


def kind_statute(letter: str | None, spec: DateSpec) -> str | None:
    """The court rule a court order gives its relative dates when their wording cites no statute."""
    if spec.type != "relative" or spec.nature not in _DECLARING:
        return None
    if letter == "court_payment_order":
        return "zpo_692"
    if letter == "enforcement_order" and spec.nature == "objection":
        return "zpo_339"
    return None


def special_rule(spec: DateSpec, letter: str | None, *, authority: bool) -> str | None:
    """The letter rule computed by :mod:`ordnung.rules.letters` for ``spec``, or ``None``.

    ``authority``: the sender is a public authority (its *Widerruf* is a revocation, not a consumer's
    withdrawal). Dates with no date type are never routed.
    """
    if spec.type == "none":
        return None
    haystack = f"{spec.legal_basis or ''} {spec.text}"
    if _SGB3_38.search(haystack):
        return "sgb3_38"
    if _BGB_558B.search(haystack) or (
        letter == "rent_increase" and spec.nature in ("declaration", "objection")
    ):
        return "bgb_558b"
    if _BGB_574B.search(haystack) or (letter == "landlord_notice" and spec.nature == "objection"):
        return "bgb_574b"
    if not authority and spec.nature != "objection" and _WITHDRAWAL.search(haystack):
        return "bgb_355"
    return None


# --------------------------------------------------------------------------------------------------
# dates the law adds
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DerivedDeadline:
    """A deadline the law sets for a kind of letter, as a to-do the pipeline files (policy 3)."""

    rule_id: str
    title: str
    action: str
    consequence: str
    priority: Priority
    spec: DateSpec


def _relative(amount: int, unit: str, nature: DateNature, legal_basis: str, text: str) -> DateSpec:
    return DateSpec.model_validate(
        {
            "type": "relative",
            "anchor": "receipt",
            "amount": amount,
            "unit": unit,
            "nature": nature,
            "legal_basis": legal_basis,
            "text": text,
        }
    )


_COURT_ORDER = DerivedDeadline(
    rule_id="zpo_692",
    title="Pay or object to the court payment order (Mahnbescheid)",
    action=(
        "If you don't owe the money, or not all of it, object (Widerspruch) on the form that came with "
        "the order, or online. If you owe it, pay the claimant."
    ),
    consequence=(
        "After two weeks the claimant can ask for an enforcement order (Vollstreckungsbescheid), and the "
        "money can then be collected by a bailiff."
    ),
    priority="critical",
    spec=_relative(
        2,
        "weeks",
        "objection",
        "§ 692 Abs. 1 Nr. 3 ZPO",
        "binnen zwei Wochen seit der Zustellung des Mahnbescheids",
    ),
)
_ENFORCEMENT = DerivedDeadline(
    rule_id="zpo_339",
    title="Object to the enforcement order (Einspruch)",
    action="Send your objection (Einspruch) in writing to the court that issued it — get advice first.",
    consequence="After two weeks the order can no longer be challenged and can be enforced for good.",
    priority="critical",
    spec=_relative(
        2, "weeks", "objection", "§ 700 Abs. 1, § 339 Abs. 1 ZPO", "Einspruchsfrist zwei Wochen ab Zustellung"
    ),
)
_COURT_ACTION = DerivedDeadline(
    rule_id="kschg_4",
    title="Get advice now: court action against the dismissal (Kündigungsschutzklage)",
    action=(
        "If you think the dismissal is wrong, talk to your union, an employment lawyer or the labour "
        "court's Rechtsantragstelle today. Only a court action filed in time keeps your rights."
    ),
    consequence="If no court action reaches the labour court in time, the dismissal counts as valid (§ 7 KSchG).",
    priority="critical",
    spec=_relative(
        3, "weeks", "objection", "§ 4 S. 1 KSchG", "innerhalb von drei Wochen nach Zugang der Kündigung"
    ),
)
_REGISTER = DerivedDeadline(
    rule_id="sgb3_38",
    title="Register as job-seeking (arbeitsuchend) at the Agentur für Arbeit",
    action="Register online, by phone or in person. Your details and the end date of the job are enough for now.",
    consequence="Registering late can cost you one week of unemployment benefit (Sperrzeit).",
    priority="high",
    spec=_relative(3, "days", "declaration", "§ 38 Abs. 1 SGB III", "arbeitsuchend melden"),
)
_CONSENT_DECISION = DerivedDeadline(
    rule_id="bgb_558b",
    title="Decide whether to agree to the rent increase",
    action=(
        "Check the increase (rent index, the rent cap, 15 months since the last one) before you agree — "
        "a tenants' association can help. You don't have to answer earlier."
    ),
    consequence="If you haven't agreed by then, the landlord can take you to court for your consent.",
    priority="high",
    spec=_relative(2, "months", "declaration", "§ 558b Abs. 2 BGB", "Zustimmung zur Mieterhöhung"),
)
_NOTICE_OBJECTION = DerivedDeadline(
    rule_id="bgb_574b",
    title="Decide whether to object to the notice (Widerspruch)",
    action=(
        "If moving out would be a hardship for you or your household (illness, old age, no other flat), you "
        "can object and ask to stay (§ 574 BGB). Talk to a tenants' association first."
    ),
    consequence="After this day the landlord may refuse to continue the tenancy.",
    priority="high",
    spec=_relative(
        -2, "months", "objection", "§ 574b Abs. 2 BGB", "spätestens zwei Monate vor der Beendigung"
    ),
)


def derived_deadlines(letter: str | None, *, end: date | None) -> list[DerivedDeadline]:
    """The deadlines the law adds to a kind of letter; ``end`` is the end its termination announces.

    The objection to a landlord's notice counts back from the end of the tenancy, so it is only
    added when that end is known.
    """
    if letter == "court_payment_order":
        return [_COURT_ORDER]
    if letter == "enforcement_order":
        return [_ENFORCEMENT]
    if letter == "dismissal":
        return [_COURT_ACTION, _REGISTER]
    if letter == "rent_increase":
        return [_CONSENT_DECISION]
    if letter == "landlord_notice" and end is not None:
        spec = _NOTICE_OBJECTION.spec.model_copy(
            update={"anchor": "explicit_date", "anchor_date": end.isoformat()}
        )
        return [replace(_NOTICE_OBJECTION, spec=spec)]
    return []
