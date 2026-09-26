"""Which rules a high-stakes letter's dates follow (ADR 0002, ADR 0007).

The model reads, code decides. The extraction prompt and schema stay as they were recorded, so the
model never names these letters itself; code recognises them from its reading with two short
policies, and cases the policies do not decide are documented limitations, not bugs.

**1. The kind of letter** (:func:`classify_letter`), from structured parts of the reading first:

=========================  ============================================================================
``court_payment_order``    sent by a court (the sender's name ends a word in "gericht": Amtsgericht,
``enforcement_order``      Mahngericht — not a bailiff, *Gerichtsvollzieher*, or a court cashier,
                           *Gerichtskasse*) and the reading names a *Mahnbescheid* or a
                           *Vollstreckungsbescheid*. Which of the two the letter **is** is decided by,
                           in this order: the one its title names first; the remedy it states
                           (*Widerspruch* → Mahnbescheid, *Einspruch* → Vollstreckungsbescheid); a
                           Vollstreckungsbescheid named other than in the warning every Mahnbescheid
                           carries ("… kann ein Vollstreckungsbescheid ergehen", § 692 Abs. 1 Nr. 4
                           ZPO); else a Mahnbescheid. A court's later letter about the order (the
                           objection was received, the case is handed on: *Abgabenachricht*) is
                           neither. A debt collector threatening one is not a court, so its letter
                           stays a reminder.
``dismissal``              the reading reports a termination by the other side
                           (``termination_by_provider``) about a job (kind ``employment``, sender
                           ``employer`` or an employment contract)
``landlord_notice``        a termination by the other side about a tenancy (kind ``rent_lease``,
                           sender ``landlord`` or a rent contract)
``rent_increase``          a price increase about a tenancy whose *quoted* wording asks for consent
                           ("Zustimmung", "Vergleichsmiete", "Mietspiegel", § 558 BGB) — never from the
                           model's own prose — and that nowhere reads as an increase that needs no
                           consent (graduated or index rent, modernisation, operating-cost prepayments
                           under § 560 BGB, "no consent needed"), in German or English
=========================  ============================================================================

These are the letters whose *dates* depend on their kind, so the kind is filed with the letter. An
operating-cost statement's dates don't (its objection period is an ordinary twelve months), so it
is recognised on read for its card only (:func:`names_statement`: the reading names a Betriebs-, Heiz- or
Nebenkostenabrechnung in its title, or with a tenancy or a billing period, and the sender is not a
utility or a public body, which may ask for a statement without sending one); the person may still
file a letter as ``operating_costs``.

"The reading names" means its title, summary, quotes, date wordings and legal bases, never the
model's advice prose (``explanation``, ``warnings``), which may mention a Mahnbescheid as a threat.
Missed: a letter whose reading lacks these signals (e.g. no termination recorded) keeps the model's
kind; the person can set the kind on the letter's page, and its dates are then recomputed.

**2. The rule of a date** (:func:`kind_statute`, :func:`special_rule`): a date follows the statute
its ``legal_basis`` or wording cites, if its nature fits that statute (a date that isn't a
declaration is never a registration, an appointment never re-dated); if it cites none, a court
order's objection, payment and declaration dates follow the court rule (two weeks from delivery), a
rent increase's declarations and objections the consent period and a landlord's notice's objections
the § 574b period. Wordings that decide on their own: "Kündigungsschutzklage", "arbeitsuchend
melden" (a declaration, and not an authority's own fixed date), and a consumer "Widerrufsfrist/
-recht/-belehrung" from a sender that is not an authority (an authority's *Widerruf* is a
revocation) and that cites no other law's withdrawal right (insurance: VVG).

**3. Dates the law adds** (:func:`derived_deadlines`): these letters rarely state their most
important deadline (a dismissal never mentions the three weeks for a court action), so each kind
brings the deadlines the law sets, which the pipeline files as to-dos unless an extracted date
already follows that rule. A landlord's notice without notice period (*fristlos*/*außerordentlich*)
gets no objection to-do: the hardship objection doesn't apply to it (§ 574 Abs. 1 S. 2 BGB).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date

from ordnung.models import DateNature, DateSpec, DocumentExtraction, HighStakesKind, LetterKind, Priority
from ordnung.rules.tenancy import notice_objection_deadline

_COURT_SENDER = re.compile(r"gericht\b", re.I)
_MAHNBESCHEID = re.compile(r"mahnbescheid", re.I)
_VOLLSTRECKUNGSBESCHEID = re.compile(r"vollstreckungsbescheid", re.I)
_COURT_ORDER_NAME = re.compile(r"mahnbescheid|vollstreckungsbescheid", re.I)
#: The warning every Mahnbescheid carries (§ 692 Abs. 1 Nr. 4 ZPO): an enforcement order *may* follow.
_MAY = re.compile(r"\b(?:kann|können|könnte|darf|droht|could|can|may|might|will|would)\b", re.I)
_FOLLOWS = re.compile(r"ergeh|erwirk|erlass|beantrag|\bapply\b|\bobtain|\bissued?\b|\bfollow", re.I)
#: A court's later letter about an order: the objection was received, the case is handed on.
_FOLLOW_UP = re.compile(
    r"abgabenachricht|\bnach\s+(?:dem\s+|ihrem\s+|erhobenem\s+)?(?:widerspruch|einspruch)\b|"
    r"(?<!kein\s)(?<!keinen\s)\b(?:widerspruch|einspruch)\b(?:[^.!?\n]|\.(?=\d)){0,80}?\b(?:ist|wurde|sind)\s+"
    r"(?:hier\s+|fristgerecht\s+|rechtzeitig\s+|am\s+\S+\s+)?(?:eingegangen|erhoben|eingelegt)\b",
    re.I,
)
_FOLLOW_UP_TITLE = re.compile(
    r"\babgabe|abgegeben|objection (?:was |has been )?received|after (?:your|the) objection|"
    r"transferred|handed (?:on|over)",
    re.I,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ])|\n")
#: A § 558 request asks for consent — in the letter's own (German) wording.
_CONSENT = re.compile(r"zustimm|vergleichsmiete|mietspiegel|\b558[ab]?\b[^§]{0,20}\bBGB\b", re.I)
_NO_CONSENT_INCREASE = re.compile(
    r"staffelmiete|indexmiete|preisindex|modernisierung|\b55(?:7a|7b|9[a-e]?|60)\b[^§]{0,20}\bBGB\b|"
    r"anpassung\s+(?:der|ihrer)\s+\S*vorauszahlung|vorauszahlung\S*\s+(?:wird|werden)\s+(?:\S+\s+){0,3}"
    r"(?:angepasst|erhöht)|(?:keine|keiner|ohne|nicht)\s+(?:ihre\s+|ihrer\s+)?zustimmung|"
    r"zustimmung\s+(?:ist\s+)?(?:nicht|entbehrlich)|price index|index[- ](?:rent|linked)|indexed rent|"
    r"graduated|stepped rent|staggered rent|moderni[sz]|prepayment|advance payment|"
    r"(?:don't|do not|doesn't|does not|no)\s+(?:need\s+(?:to\s+|your\s+)?)?(?:agree|consent)",
    re.I,
)
_OPERATING_COSTS = re.compile(
    r"(?:betriebs|neben|heiz(?:ungs)?)kosten-?\s?abrechnung|(?:betriebs|neben)-\s*und\s+heizkostenabrechnung|"
    r"operating[- ]costs? statement|service[- ]charge statement",
    re.I,
)
_BILLING_PERIOD = re.compile(r"abrechnungs(?:zeitraum|periode|jahr)|billing (?:period|year)", re.I)
#: Senders that may ask for a statement but never send one (the Jobcenter wants to see it).
_NOT_A_LANDLORD = (
    "utility",
    "authority",
    "tax_office",
    "immigration_office",
    "health_insurer",
    "public_broadcaster",
)
_EXTRAORDINARY = re.compile(
    r"fristlos|außerordentlich|ausserordentlich|without notice|extraordinary|\b543\b[^§]{0,20}\bBGB\b|"
    r"\b569\b[^§]{0,20}\bBGB\b",
    re.I,
)

_SGB3_38 = re.compile(
    r"\b38\b[^§]{0,20}\bSGB\s*(?:III|3)\b|arbeits?suchend\s+(?:zu\s+)?(?:ge)?meld|"
    r"meld\w*\s+(?:\S+\s+){0,4}arbeits?suchend\b",
    re.I,
)
_BGB_558B = re.compile(r"\b558b\b[^§]{0,20}\bBGB\b", re.I)
_BGB_574B = re.compile(r"\b574b?\b[^§]{0,20}\bBGB\b", re.I)
_WITHDRAWAL = re.compile(
    r"\b35[56]\b[^§]{0,20}\bBGB\b|widerrufs(?:frist|recht|belehrung)|right of withdrawal|withdrawal period",
    re.I,
)
#: Withdrawal rights of other laws, with their own periods (insurance: 14 or 30 days, § 8, § 152 VVG).
_OTHER_WITHDRAWAL_LAW = re.compile(r"\b(?:VVG|FernUSG|KAGB|VermAnlG|WpPG)\b")

_EMPLOYMENT = ("employment", "employer")
_TENANCY = ("rent_lease", "landlord", "rent")
_DECLARING: tuple[DateNature, ...] = ("objection", "payment", "declaration")


def _quoted_text(extraction: DocumentExtraction) -> str:
    """The letter's own wording as the reading quotes it (quotes, date wordings, legal bases)."""
    parts: list[str] = []
    for item in extraction.items:
        parts += [item.quote, item.date.text, item.date.legal_basis or ""]
    for fact in extraction.key_facts:
        parts.append(fact.quote)
    if extraction.remedy is not None:
        remedy = extraction.remedy
        parts += [remedy.quote or "", remedy.period_text or "", remedy.form_text or ""]
    if extraction.change is not None:
        parts.append(extraction.change.quote)
    return "\n".join(part for part in parts if part)


def _reading_text(extraction: DocumentExtraction) -> str:
    """What the letter says according to the reading (not the model's advice prose)."""
    parts = [extraction.title, extraction.summary, _quoted_text(extraction)]
    for item in extraction.items:
        parts.append(item.title)
    for fact in extraction.key_facts:
        parts += [fact.label, fact.value]
    if extraction.remedy is not None:
        parts.append(extraction.remedy.addressee or "")
    return "\n".join(part for part in parts if part)


def _about(extraction: DocumentExtraction, markers: tuple[str, ...]) -> bool:
    """Whether the letter's kind, its sender's kind or its contract's category is one of ``markers``."""
    sender = extraction.sender.kind if extraction.sender else None
    category = extraction.contract.category if extraction.contract else None
    return extraction.kind in markers or sender in markers or category in markers


def _names_enforcement_order(text: str) -> bool:
    """Whether ``text`` names a Vollstreckungsbescheid other than in the Mahnbescheid's warning that
    one may follow (a sentence with "kann … ergehen/erwirken/beantragen", "can apply for …")."""
    return any(
        _VOLLSTRECKUNGSBESCHEID.search(sentence) and not (_MAY.search(sentence) and _FOLLOWS.search(sentence))
        for sentence in _SENTENCE.split(text)
    )


def _court_order(extraction: DocumentExtraction) -> HighStakesKind | None:
    """Which court order a court's letter is (policy 1: title, remedy, wording), or ``None``."""
    text = _reading_text(extraction)
    if not _COURT_ORDER_NAME.search(text):
        return None
    if _FOLLOW_UP_TITLE.search(extraction.title) or _FOLLOW_UP.search(f"{extraction.title}\n{text}"):
        return None
    named = _COURT_ORDER_NAME.search(extraction.title)
    if named is not None:
        return "enforcement_order" if _VOLLSTRECKUNGSBESCHEID.match(named.group()) else "court_payment_order"
    remedy = extraction.remedy.type if extraction.remedy else None
    if remedy == "einspruch":
        return "enforcement_order"
    if remedy == "widerspruch":
        return "court_payment_order"
    return "enforcement_order" if _names_enforcement_order(text) else "court_payment_order"


def classify_letter(extraction: DocumentExtraction) -> HighStakesKind | None:
    """The high-stakes kind of a letter from the model's reading, or ``None`` (policy 1 above)."""
    sender = extraction.sender
    if sender is not None and _COURT_SENDER.search(sender.name):
        court_order = _court_order(extraction)
        if court_order is not None:
            return court_order
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
        and _CONSENT.search(_quoted_text(extraction))
        and not _NO_CONSENT_INCREASE.search(_reading_text(extraction))
    ):
        return "rent_increase"
    return None


def names_statement(extraction: DocumentExtraction) -> bool:
    """Whether a reading is an operating-cost statement (its card is worked out on read): it names
    one — in its title, or with a tenancy or a billing period — and doesn't come from a utility or a
    public body (policy 1)."""
    text = _reading_text(extraction)
    sender = extraction.sender
    if not _OPERATING_COSTS.search(text) or (sender is not None and sender.kind in _NOT_A_LANDLORD):
        return False
    return (
        bool(_OPERATING_COSTS.search(extraction.title))
        or _about(extraction, _TENANCY)
        or bool(_BILLING_PERIOD.search(text))
    )


def extraordinary_notice(extraction: DocumentExtraction) -> bool:
    """Whether a termination reads as one without notice period (*fristlos*, *außerordentlich*)."""
    return bool(_EXTRAORDINARY.search(_reading_text(extraction)))


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
    """The court rule a court order gives its dates when their wording cites no statute."""
    if spec.type == "none" or spec.nature not in _DECLARING:
        return None
    if letter == "court_payment_order":
        return "zpo_692"
    if letter == "enforcement_order" and spec.nature == "objection":
        return "zpo_339"
    return None


def special_rule(spec: DateSpec, letter: str | None, *, authority: bool) -> str | None:
    """The letter rule computed by :mod:`ordnung.rules.letters` for ``spec``, or ``None`` (policy 2).

    ``authority``: the sender is a public authority (its *Widerruf* is a revocation, not a consumer's
    withdrawal, and its own fixed dates are never re-dated). Dates with no date type are never routed,
    and a date is only routed to a rule its nature fits.
    """
    if spec.type == "none":
        return None
    haystack = f"{spec.legal_basis or ''} {spec.text}"
    if (
        spec.nature == "declaration"
        and not (authority and spec.type == "fixed")
        and _SGB3_38.search(haystack)
    ):
        return "sgb3_38"
    if spec.nature in ("declaration", "objection") and (
        _BGB_558B.search(haystack) or letter == "rent_increase"
    ):
        return "bgb_558b"
    if spec.nature == "objection" and (_BGB_574B.search(haystack) or letter == "landlord_notice"):
        return "bgb_574b"
    if (
        not authority
        and spec.nature not in ("objection", "appointment")
        and _WITHDRAWAL.search(haystack)
        and not _OTHER_WITHDRAWAL_LAW.search(haystack)
    ):
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
    consequence=(
        "After this day the landlord may refuse to continue the tenancy — unless they didn't tell you in time "
        "about this right, its form and its deadline (then you can still object at the first court hearing)."
    ),
    priority="high",
    spec=_relative(
        -2, "months", "objection", "§ 574b Abs. 2 BGB", "spätestens zwei Monate vor der Beendigung"
    ),
)


def derived_deadlines(
    letter: str | None, *, end: date | None, letter_date: date | None = None, extraordinary: bool = False
) -> list[DerivedDeadline]:
    """The deadlines the law adds to a kind of letter; ``end`` is the end its termination announces.

    The objection to a landlord's notice counts back from the end of the tenancy, so it is only
    added when that end is known — and not for a notice without notice period (``extraordinary``, or an
    end less than two months after the letter's date ``letter_date``): the hardship objection doesn't
    apply to it (§ 574 Abs. 1 S. 2 BGB), and its card points to advice instead.
    """
    if letter == "court_payment_order":
        return [_COURT_ORDER]
    if letter == "enforcement_order":
        return [_ENFORCEMENT]
    if letter == "dismissal":
        return [_COURT_ACTION, _REGISTER]
    if letter == "rent_increase":
        return [_CONSENT_DECISION]
    if letter == "landlord_notice" and end is not None and not extraordinary:
        if letter_date is not None and notice_objection_deadline(end) < letter_date:
            return []
        spec = _NOTICE_OBJECTION.spec.model_copy(
            update={"anchor": "explicit_date", "anchor_date": end.isoformat()}
        )
        return [replace(_NOTICE_OBJECTION, spec=spec)]
    return []
