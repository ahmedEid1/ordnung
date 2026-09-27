"""Compose a letter (SPEC §11, §21): fixed operative sentences, optional model text, checks, send guidance.

Code decides everything legally relevant: the kind of letter (an objection only when the letter's
Rechtsbehelfsbelehrung names an Einspruch or Widerspruch, or the law gives one: a court order or a
landlord's notice), the operative sentences (:mod:`ordnung.drafts.templates`, and
:mod:`ordnung.drafts.template_letters` for the everyday letters that ask for something, filled from
:class:`~ordnung.models.LetterDetails`), recipient and sender blocks, place and date, subject with
references, the end date of a cancellation (rules engine) and the send-by date
(:func:`ordnung.rules.send_guidance`). The model (purpose ``draft``) only writes optional polite free
text consistent with the person's instructions, the translation into the person's language and
notes; sentences citing a § are dropped. Without a model (a private letter, no Claude, an error) the
letter is still complete, with a code-built English translation.

:func:`mark_sent` records how and when the letter went out and creates a follow-up to-do 21 days
later; :func:`refresh_checks` re-runs the checks after the person edited a draft and
:func:`retranslate` translates an edited letter again (purpose ``draft``, translation only).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, cast, get_args

from pydantic import ValidationError
from rapidfuzz import fuzz

from ordnung.clock import now_iso
from ordnung.db.store import NotFoundError, Store
from ordnung.drafts import templates
from ordnung.drafts.checks import CheckContext, run_checks
from ordnung.drafts.template_letters import (
    ADDRESS_FRAMES,
    TEMPLATES,
    TemplateError,
    TemplateInput,
    template_letter,
)
from ordnung.drafts.templates import STATUTORY_REMEDIES, LetterLanguage, LetterParts, RemedyKind
from ordnung.ids import content_id, new_id
from ordnung.llm.base import ClaudeBadOutput, LLMError, LLMRequest, LLMResponse, ReplayMiss
from ordnung.llm.prompts import render
from ordnung.llm.schemas import draft_schema, draft_translation_schema
from ordnung.models import (
    AppSettings,
    ComputationReceipt,
    ComputationStep,
    Contract,
    DateSpec,
    Document,
    DocumentExtraction,
    Draft,
    DraftKind,
    DraftOutput,
    DraftTranslationOutput,
    Item,
    LetterDetails,
    Party,
    Profile,
    Remedy,
    SendChannel,
    SendGuidance,
    TemplateDraftKind,
)
from ordnung.rules import LAST_CHECKED, RuleContext, compute_due, send_guidance
from ordnung.rules.advice import ARREARS_CURE, HARDSHIP_EXCLUDED, billing_period_text
from ordnung.rules.consumer import long_withdrawal_end
from ordnung.rules.explain import fmt_date
from ordnung.rules.routing import (
    alternative_notice,
    extraordinary_notice,
    is_court,
    is_labour_court,
    may_be_court,
)
from ordnung.secretary.review import language_name, split_sentences, stable_hash, untrusted_json
from ordnung.secretary.scam import ibans_in_text, normalize_iban
from ordnung.secretary.triggers import Ledger, contract_area, contract_computation, parse_day, postal_buffer
from ordnung.tick import local_today

if TYPE_CHECKING:
    from ordnung.app_context import AppContext

log = logging.getLogger(__name__)

FOLLOWUP_DAYS = 21
#: Days to wait for a reply per kind of letter when it differs: a data request has one month from
#: receipt (Art. 12 Abs. 3 GDPR), plus the post.
FOLLOWUP_DAYS_BY_KIND = {"data_access": 35}
MAX_INSTRUCTIONS = 4000
MAX_FREE_TEXT = 3000
MAX_TRANSLATION = 8000
MAX_MODEL_NOTES = 3
MAX_NOTE_CHARS = 300
MAX_ENCLOSURES = 5
MAX_ENCLOSURE_CHARS = 80
MAX_SUBJECT_CHARS = 120
SAME_NAME_SCORE = 90.0

DRAFT_KINDS: tuple[str, ...] = get_args(DraftKind)
SEND_CHANNELS: tuple[str, ...] = get_args(SendChannel.model_fields["channel"].annotation)
_OPEN = ("open", "snoozed")
_KIND_LABELS = {
    "cancellation": "cancellation of a contract (Kündigung)",
    "objection": "objection against an official decision (Einspruch or Widerspruch)",
    "general_reply": "general reply to a letter",
    **{kind: spec.label for kind, spec in TEMPLATES.items()},
}
_SCHUFA_RE = re.compile(r"\bschufa\b", re.I)
_ENGLISH_REFERENCE_LABELS = {
    "steuernummer": "tax number",
    "aktenzeichen": "reference",
    "kundennummer": "customer number",
    "vertragsnummer": "contract number",
    "rechnungsnummer": "invoice number",
    "mitgliedsnummer": "membership number",
    "versicherungsnummer": "insurance number",
    "kassenzeichen": "payment reference (Kassenzeichen)",
}
_UNTRANSLATED: dict[LetterLanguage, str] = {
    "de": "(Ihr zusätzlicher Text ist nicht übersetzt.)",
    "en": "(Your additional text is not translated.)",
}
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_FRAME_LINE_RE = re.compile(
    r"^\s*(?:sehr geehrte|guten tag|hallo\b|liebe[rs]?\b|dear\b|mit freundlichen|freundliche grüße|"
    r"viele grüße|beste grüße|herzliche grüße|yours\b|kind regards|best regards|sincerely)",
    re.I,
)
_POSTCODE_CITY_RE = re.compile(r"\b\d{4,5}\s+(?P<city>[^\d,\n][^,\n]*)$")
_ADDRESSEE_PREFIX_RE = re.compile(r"^(?:beim|bei\s+(?:der|dem|den)|an\s+(?:das|den|die|der))\s+", re.I)
_ADDRESSEE_SUFFIX_RE = re.compile(
    r"\s+(?:schriftlich\s+)?(?:oder\s+zur\s+niederschrift\s+)?(?:einzulegen|einzureichen|zu\s+erheben)\.?$",
    re.I,
)
_SENDER_WORDS = ("oben genannt", "erlassen", "absender", "diese behörde", "dieser behörde", "unterzeichnet")
# First words that are written in lower case right after a German salutation ("…Herren, vielen Dank").
_LOWERCASE_STARTERS = frozenset(
    [
        "Vielen",
        "Herzlichen",
        "Hiermit",
        "Ich",
        "Wie",
        "Bitte",
        "Leider",
        "Gerne",
        "Gern",
        "Da",
        "Mit",
        "Nach",
        "Aufgrund",
        "Zu",
        "Zum",
        "Zur",
        "Anbei",
        "Am",
        "Im",
        "In",
        "Für",
        "Wir",
        "Danke",
        "Hierzu",
        "Bezüglich",
        "Nachdem",
        "Seit",
        "Wegen",
    ]
)


class DraftError(ValueError):
    """A letter Ordnung can't draft as asked; the message explains why in plain English."""


# --------------------------------------------------------------------------------------------------
# sources: the ledger records a letter is about
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Sources:
    """The profile and ledger records a letter is about."""

    profile: Profile
    party: Party | None = None
    contract: Contract | None = None
    document: Document | None = None
    extraction: DocumentExtraction | None = None

    @property
    def case_id(self) -> str | None:
        """The thread of the source letter, else of the contract."""
        if self.document is not None and self.document.case_id:
            return self.document.case_id
        return self.contract.case_id if self.contract is not None else None

    @property
    def remedy(self) -> Remedy | None:
        """The remedy stated in the source letter (stored on the document, else in its extraction)."""
        if self.document is not None and self.document.remedy is not None:
            return self.document.remedy
        return self.extraction.remedy if self.extraction is not None else None

    @property
    def doc_date(self) -> date | None:
        """Date printed on the source letter."""
        return parse_day(self.document.doc_date) if self.document is not None else None


def _require_document(store: Store, doc_id: str | None) -> Document | None:
    if doc_id is None:
        return None
    document = store.get_document(doc_id)
    if document is None or document.deleted_at is not None:
        raise DraftError("That letter isn't in Ordnung any more.")
    return document


def _require_contract(store: Store, contract_id: str | None) -> Contract | None:
    if contract_id is None:
        return None
    contract = store.get_contract(contract_id)
    if contract is None:
        raise DraftError("That contract isn't in Ordnung any more.")
    return contract


def load_sources(
    store: Store,
    kind: str,
    *,
    doc_id: str | None = None,
    contract_id: str | None = None,
    party_id: str | None = None,
) -> Sources:
    """Load the records for a new letter; a cancellation finds the contract of its letter if not given."""
    document = _require_document(store, doc_id)
    contract = _require_contract(store, contract_id)
    if contract is None and document is not None and kind == "cancellation":
        contract = Ledger(store, local_today(store)).linked_contract(document)
    party_ref = (
        party_id or (contract.party_id if contract else None) or (document.party_id if document else None)
    )
    party = store.get_party(party_ref) if party_ref else None
    if party_id is not None and party is None:
        raise DraftError("That person or organisation isn't in Ordnung any more.")
    return Sources(
        profile=store.get_profile(),
        party=party,
        contract=contract,
        document=document,
        extraction=store.get_extraction(document.id) if document else None,
    )


def sources_for_draft(store: Store, draft: Draft) -> Sources:
    """The records a stored draft refers to (missing ones are left out)."""
    document = store.get_document(draft.doc_id) if draft.doc_id else None
    return Sources(
        profile=store.get_profile(),
        party=store.get_party(draft.party_id) if draft.party_id else None,
        contract=store.get_contract(draft.contract_id) if draft.contract_id else None,
        document=document,
        extraction=store.get_extraction(document.id) if document else None,
    )


# --------------------------------------------------------------------------------------------------
# addresses, references, place and date
# --------------------------------------------------------------------------------------------------


def address_lines(text: str | None) -> list[str]:
    """An address as lines (split at line breaks and commas)."""
    if not text:
        return []
    return [part.strip() for line in text.splitlines() for part in line.split(",") if part.strip()]


def _party_lines(party: Party | None) -> list[str]:
    if party is None:
        return []
    return [party.name, *address_lines(party.address)]


def _same_name(a: str, b: str) -> bool:
    return fuzz.token_set_ratio(a.casefold(), b.casefold()) >= SAME_NAME_SCORE


def _clean_addressee(text: str) -> str:
    text = " ".join(text.split())
    return _ADDRESSEE_SUFFIX_RE.sub("", _ADDRESSEE_PREFIX_RE.sub("", text)).strip()


def _objection_recipient(remedy: Remedy | None, party: Party | None) -> list[str]:
    """The addressee named in the remedy instructions (with the sender's address if it is the sender)."""
    addressee = _clean_addressee(remedy.addressee or "") if remedy is not None else ""
    if not addressee or any(word in addressee.casefold() for word in _SENDER_WORDS):
        return _party_lines(party)
    lines = address_lines(addressee)
    if len(lines) == 1 and party is not None and _same_name(lines[0], party.name):
        return [lines[0], *address_lines(party.address)]
    return lines


def recipient_block(kind: str, sources: Sources, details: LetterDetails | None = None) -> str:
    """Name and address of the recipient; for objections the addressee named in the remedy; for a
    template letter to someone not in Ordnung yet, the name and address the person typed."""
    if kind == "objection":
        return "\n".join(_objection_recipient(sources.remedy, sources.party))
    if sources.party is None and kind in TEMPLATES and details is not None and details.recipient:
        return "\n".join(address_lines(details.recipient))
    return "\n".join(_party_lines(sources.party))


def sender_block(profile: Profile) -> str:
    """The person's name and postal address."""
    return "\n".join(line for line in [profile.name.strip(), *address_lines(profile.address)] if line)


def place_date(profile: Profile, today: date, language: LetterLanguage) -> str:
    """``Musterstadt, 28.09.2026`` (town from the profile address; just the date without one)."""
    day = templates.format_date(today, language)
    for line in reversed(address_lines(profile.address)):
        match = _POSTCODE_CITY_RE.search(line)
        if match:
            return f"{match.group('city').strip()}, {day}"
    return day


def _reference_label(label: str, language: LetterLanguage) -> str:
    if language == "de":
        return label
    return _ENGLISH_REFERENCE_LABELS.get(label.strip().rstrip(":").casefold(), label)


def letter_reference(sources: Sources, language: LetterLanguage) -> str | None:
    """The reference line: the source letter's first reference, else the contract's customer number."""
    document = sources.document
    if document is not None and document.references:
        first = document.references[0]
        return f"{_reference_label(first.label.strip().rstrip(':'), language)} {first.value}".strip()
    if sources.contract is not None and sources.contract.customer_number:
        label = "Kundennummer" if language == "de" else "customer number"
        return f"{label} {sources.contract.customer_number}"
    return None


def known_references(sources: Sources) -> list[str]:
    """Every customer/reference number the recipient may know the matter by."""
    values: list[str] = []
    if sources.contract is not None and sources.contract.customer_number:
        values.append(sources.contract.customer_number)
    if sources.document is not None:
        values.extend(ref.value for ref in sources.document.references)
    if sources.extraction is not None:
        values.extend(ref.value for ref in sources.extraction.references)
    if sources.party is not None:
        values.extend(identifier.value for identifier in sources.party.identifiers)
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


# --------------------------------------------------------------------------------------------------
# the code-written frame
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Plan:
    """Everything decided by code before the model is asked."""

    kind: DraftKind
    language: LetterLanguage
    letter: LetterParts
    reference: LetterParts | None  # the frame in the translation language (English when not de/en)
    translation_language: str | None  # the person's language; None when no translation is needed
    guidance: SendGuidance
    notes: tuple[str, ...] = ()  # what code worked out for this letter (e.g. how long a withdrawal runs)
    private: tuple[tuple[str, str], ...] = ()  # (value, placeholder) the model never sees (_masked)


def _person_name(kind: str, party: Party | None) -> str | None:
    if kind == "objection" or party is None or party.kind != "person":
        return None
    return party.name


#: Why there is no hardship objection against a notice without notice period (the card says the same).
NO_HARDSHIP_OBJECTION = (
    "This reads as a notice without notice period (fristlos). The hardship objection (§ 574 BGB) doesn't apply "
    "to it: it is excluded whenever the landlord had grounds for such a notice (§ 574 Abs. 1 S. 2 BGB), so "
    f"Ordnung doesn't draft one. If it is for rent arrears (§ 569 Abs. 3 Nr. 2 BGB), {ARREARS_CURE}. Get advice "
    "at once, for example from a tenants' association."
)


def objection_remedy(sources: Sources) -> RemedyKind:
    """The remedy an objection letter uses; raises :class:`DraftError` unless it is Einspruch/Widerspruch.

    Court orders and a landlord's notice have the remedy the law gives them (a Widerspruch against a
    court payment order, an Einspruch against an enforcement order, the tenant's Widerspruch), whatever
    their instructions were read as — except a landlord's notice without notice period that gives none
    in the alternative (:func:`~ordnung.rules.routing.extraordinary_notice`): the hardship objection
    doesn't apply to it, and the letter's card offers none either.
    """
    if sources.document is None:
        raise DraftError("Choose the decision (the letter) you want to object to.")
    reading = sources.extraction
    if (
        sources.document.kind == "landlord_notice"
        and reading is not None
        and extraordinary_notice(reading, sources.doc_date)
        and not alternative_notice(reading)
    ):
        raise DraftError(NO_HARDSHIP_OBJECTION)
    statutory = STATUTORY_REMEDIES.get(sources.document.kind or "")
    if statutory is not None:
        return statutory
    remedy = sources.remedy
    kind = remedy.type if remedy is not None else "none"
    if kind == "einspruch":
        return "einspruch"
    if kind == "widerspruch":
        return "widerspruch"
    if kind == "klage":
        raise DraftError(
            "This decision can only be challenged in court (Klage). Ordnung doesn't draft court actions — "
            "please get advice quickly (for example from a Verbraucherzentrale, a Mieterverein or a lawyer); "
            "the period is usually one month."
        )
    if kind == "unclear":
        raise DraftError(
            "We couldn't tell from the letter whether an Einspruch or a Widerspruch is the right remedy. "
            "Check the instructions at the end of the letter (Rechtsbehelfsbelehrung) or get advice."
        )
    raise DraftError(
        "The letter doesn't say how to object (no Rechtsbehelfsbelehrung found), so Ordnung can't draft an "
        "objection. Missing instructions can mean a one-year period (§ 356 Abs. 2 AO, § 58 Abs. 2 VwGO, "
        "§ 66 Abs. 2 SGG) — please get advice."
    )


def extendable(item: Item) -> bool:
    """A deadline someone set and may extend when asked: not one the law sets (a deadline the law adds,
    ``origin="rule"``, or an objection period)."""
    return item.origin != "rule" and not (item.date_spec is not None and item.date_spec.nature == "objection")


def _earliest_open(
    store: Store, sources: Sources, kinds: tuple[str, ...], *, extendable_only: bool = False
) -> Item | None:
    if sources.document is None:
        return None
    items = [
        item
        for item in store.list_items(doc_id=sources.document.id, status=_OPEN, include_undated=False)
        if item.kind in kinds
        and parse_day(item.due_date) is not None
        and (extendable(item) or not extendable_only)
    ]
    return min(items, key=lambda item: item.due_date or "") if items else None


#: Letters whose deadlines the law sets and nobody extends on request (§ 224 Abs. 1 ZPO, § 4 KSchG):
#: asking for more time would only cost the person the deadline.
_NO_EXTENSION: dict[str, str] = {
    "court_payment_order": (
        "The period to pay or object to a court payment order is set by law (two weeks, § 692 ZPO; one week at "
        "a labour court, § 46a ArbGG), and no one can extend it by being asked. Object in time instead — the "
        "letter's page offers the objection — or get advice at the court's Rechtsantragstelle."
    ),
    "enforcement_order": (
        "The period to object to an enforcement order can't be extended (Notfrist: two weeks, § 339 ZPO; one "
        "week at a labour court, § 59 ArbGG). Object in time instead — the letter's page offers the objection "
        "— or get advice at once."
    ),
    "dismissal": (
        "The three weeks for a court action against a dismissal are set by law (§ 4 KSchG) — your employer "
        "can't extend them. Get advice now (see the card on the letter)."
    ),
}
#: An offer to pay in instalments acknowledges the claim (review round 1): the limitation period starts again
#: (§ 212 Abs. 1 Nr. 1 BGB), the claim is hard to dispute later, and a payment on a time-barred claim can't be
#: reclaimed (§ 214 Abs. 2 BGB) — the card of a court order says old claims may be time-barred.
ACKNOWLEDGES_CLAIM = (
    "Offering instalments acknowledges the claim: the limitation period starts again (§ 212 Abs. 1 Nr. 1 BGB) "
    "and it is hard to dispute later — and money paid on a time-barred claim can't be reclaimed (§ 214 Abs. 2 "
    "BGB). If you think the claim is wrong or time-barred, object or get debt advice first."
)
_COURT_INSTALMENTS = (
    "A court doesn't agree instalments — the claimant does. Write to the claimant instead (the order names them "
    "as the Antragsteller), and still pay or object by the court's deadline: an offer to pay in instalments "
    f"doesn't stop the order. {ACKNOWLEDGES_CLAIM}"
)


def template_refusal(kind: str, letter_kind: str | None) -> str | None:
    """Why a template letter can't answer a letter of ``letter_kind``, or ``None``: more time against a
    deadline the law sets (a court order, a dismissal), instalments offered to a court."""
    if kind == "extension_request" and letter_kind in _NO_EXTENSION:
        return _NO_EXTENSION[letter_kind]
    if kind == "payment_plan" and letter_kind in ("court_payment_order", "enforcement_order"):
        return _COURT_INSTALMENTS
    return None


def template_input(
    store: Store, kind: str, sources: Sources, details: LetterDetails, language: LetterLanguage
) -> TemplateInput:
    """What a template letter can use: the person's details, the letter and contract it is about, the
    profile, and defaults from the ledger (the letter's earliest open deadline someone may extend, its
    payment, its billing period). The letter's title is never the topic: it is the model's (English)
    summary, not what the person ordered."""
    party, document = sources.party, sources.document
    deadline = _earliest_open(store, sources, ("deadline", "task"), extendable_only=True)
    payment = _earliest_open(store, sources, ("payment",))
    text = store.get_document_text(document.id) if document is not None else ""
    topic = sources.contract.name if sources.contract else None
    return TemplateInput(
        details=details,
        reference=letter_reference(sources, language),
        doc_date=sources.doc_date,
        topic=topic,
        address=sources.profile.address or None,
        iban=sources.profile.iban or None,
        person_name=_person_name(kind, party),
        tax_office=party is not None and party.kind == "tax_office",
        schufa=bool(_SCHUFA_RE.search(party.name if party else details.recipient or "")),
        deadline=parse_day(deadline.due_date) if deadline else None,
        amount=payment.amount if payment else None,
        period=billing_period_text(text, before=sources.doc_date) if text else None,
    )


def _frame(
    kind: str,
    sources: Sources,
    language: LetterLanguage,
    *,
    end_date: date | None,
    suspend_enforcement: bool,
    template: TemplateInput | None = None,
) -> LetterParts:
    person = _person_name(kind, sources.party)
    if kind in TEMPLATES:
        if sources.party is None and not (template is not None and template.details.recipient):
            raise DraftError("Choose who the letter is for, or type their name and address.")
        assert template is not None  # plan_letter builds it for template kinds
        try:
            return template_letter(cast(TemplateDraftKind, kind), language, template)
        except TemplateError as exc:
            raise DraftError(str(exc)) from exc
    if kind == "cancellation":
        if sources.contract is None:
            raise DraftError(
                "Choose the contract you want to cancel (add it under Contracts if it's missing)."
            )
        return templates.cancellation(
            language,
            contract_name=sources.contract.name,
            customer_number=sources.contract.customer_number,
            end_date=end_date,
            person_name=person,
        )
    if kind == "objection":
        return templates.objection(
            language,
            remedy=objection_remedy(sources),
            document_kind=sources.document.kind if sources.document else None,
            doc_date=sources.doc_date,
            reference=letter_reference(sources, language),
            suspend_enforcement=suspend_enforcement,
            flat=", ".join(address_lines(sources.profile.address)) or None,
        )
    if sources.party is None:
        raise DraftError("Choose who the letter is for.")
    return templates.general_reply(
        language,
        doc_date=sources.doc_date,
        reference=letter_reference(sources, language),
        topic=sources.contract.name if sources.contract else None,
        person_name=person,
    )


def _earliest_due(items: list[Item]) -> date | None:
    days = [day for day in (parse_day(item.due_date) for item in items) if day is not None]
    return min(days) if days else None


#: Financial services keep the right to withdraw past twelve months when the instructions were missing
#: (§ 356 Abs. 4 S. 2 BGB), so an expired right is only ever "most likely" expired.
_FINANCIAL_SERVICES = "(Contracts for financial services, such as loans or insurance, follow other rules.)"


def _withdrawal_due(details: LetterDetails, profile: Profile, today: date) -> tuple[date | None, list[str]]:
    """The last day to send a withdrawal (§§ 355, 356 BGB) and notes on it, from when the goods came or
    the contract was made; ``None`` without either date. A right that has most likely run out is said
    to have, with the exception for financial services, instead of a date in the past as a deadline.

    While the 14 days run they are the date, even when the person says the instructions were missing
    (``instructions_missing``): whether instructions were proper is a legal judgement, so the 12 months
    and 14 days are only a note — the earliest plausible date is the one to act on (SPEC § 21). Only once
    the 14 days have passed does the longer period become the date."""
    start = parse_day(details.received_on) or parse_day(details.ordered_on)
    if start is None:
        return None, [
            "Add when you ordered or received it: Ordnung then shows how long you can withdraw (usually 14 days)."
        ]
    end, _ = long_withdrawal_end(start)
    expired = (
        f"Even without proper instructions, the right to withdraw ended on {fmt_date(end)} at the latest (12 months "
        f"and 14 days, § 356 Abs. 4 BGB), so it has most likely expired. {_FINANCIAL_SERVICES} Get advice before "
        "you send it."
    )
    spec = DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date=start.isoformat(),
        amount=14,
        unit="days",
        nature="declaration",
        legal_basis="§ 355 BGB",
    )
    receipt = compute_due(spec, RuleContext(today=today, recipient_region=profile.known_region))
    due = parse_day(receipt.due_date)
    if due is None or due >= today:
        notes = [receipt.summary] if due else []
        if due is not None and details.instructions_missing:
            notes.append(
                f"If you were really never properly told about the right to withdraw, it lasts until {fmt_date(end)} "
                "at the latest (12 months and 14 days, § 356 Abs. 4 BGB). Whether the instructions were proper is "
                f"hard to tell, so don't rely on it: send it by {fmt_date(due)}."
            )
        return due, notes
    if details.instructions_missing:
        if end < today:
            return end, [expired]
        return end, [
            f"The 14 days ended on {fmt_date(due)}. Without proper instructions on the right to withdraw, it lasts "
            f"until {fmt_date(end)} at the latest (12 months and 14 days, § 356 Abs. 4 BGB). Sending it in time is "
            "enough — get advice if you're unsure the instructions were missing."
        ]
    if end < today:
        return due, [f"The 14 days ended on {fmt_date(due)}. {expired}"]
    return due, [
        f"The 14 days ended on {fmt_date(due)}. If you were never properly told about the right to withdraw, "
        f"it lasts until {fmt_date(end)} — tick that option; otherwise get advice before you send it."
    ]


def _letter_due(store: Store, kind: str, sources: Sources, today: date) -> tuple[date | None, date | None]:
    """``(end date for a cancellation, day the letter must arrive)``."""
    if kind == "cancellation" and sources.contract is not None:
        comp = contract_computation(sources.contract, sources.party, today, sources.profile)
        end = parse_day(comp.earliest_exit) or parse_day(comp.current_term_end)
        return end, parse_day(comp.cancel_by)
    if sources.document is None:
        return None, None
    items = [
        item
        for item in store.list_items(doc_id=sources.document.id, status=_OPEN, include_undated=False)
        if item.kind in ("deadline", "task")
    ]
    if kind == "objection":
        objections = [item for item in items if item.date_spec and item.date_spec.nature == "objection"]
        items = objections or [item for item in items if item.kind == "deadline"]
    if kind == "payment_plan":
        payment = _earliest_open(store, sources, ("payment",))
        return None, parse_day(payment.due_date) if payment else None
    if kind == "extension_request":
        items = [item for item in items if extendable(item)]
    elif kind in TEMPLATES:
        return None, None
    return None, _earliest_due(items)


def translation_language(profile: Profile, letter_language: str) -> str | None:
    """The language a letter is translated into for the person (``None``: it is already theirs)."""
    user_language = profile.language.split("-")[0].lower() or "en"
    return None if user_language == letter_language else user_language


def plan_letter(
    store: Store,
    kind: DraftKind,
    sources: Sources,
    language: LetterLanguage,
    *,
    suspend_enforcement: bool = False,
    today: date,
    details: LetterDetails | None = None,
) -> Plan:
    """The code-written frame, reference translation and send guidance of a letter."""
    refusal = template_refusal(kind, sources.document.kind if sources.document else None)
    if refusal is not None:
        raise DraftError(refusal)
    end_date, due = _letter_due(store, kind, sources, today)
    facts = details or LetterDetails()
    notes: list[str] = []
    if kind == "withdrawal":
        due, notes = _withdrawal_due(facts, sources.profile, today)
    elif kind == "extension_request":
        due = min(day for day in (due, parse_day(facts.deadline)) if day) if due or facts.deadline else None

    def frame(frame_language: LetterLanguage) -> LetterParts:
        template = template_input(store, kind, sources, facts, frame_language) if kind in TEMPLATES else None
        return _frame(
            kind,
            sources,
            frame_language,
            end_date=end_date,
            suspend_enforcement=suspend_enforcement,
            template=template,
        )

    letter = frame(language)
    translation = translation_language(sources.profile, language)
    reference_language: LetterLanguage = "de" if translation == "de" else "en"
    reference = frame(reference_language) if translation else None
    party = sources.party
    # a recipient typed in has no kind: only a court's full name makes it one; "AG Hagen" (or "LG
    # Electronics", which can't be told apart) may be one, so it gets a court's channels and a note
    recipient = party.name if party else (facts.recipient or "").strip().split("\n")[0]
    court = is_court(recipient, party.kind if party else None)
    unsure = party is None and not court and may_be_court(recipient)
    guidance = send_guidance(
        kind,
        contract_category=sources.contract.category if sources.contract else None,
        party_kind=party.kind if party else None,
        letter_kind=sources.document.kind if sources.document else None,
        due=due,
        region=party.region if party else None,
        today=today,
        postal_buffer_days=postal_buffer(sources.profile),
        court=court,
        labour_court=is_labour_court(recipient, party.kind if party else None),
        court_unsure=unsure,
    )
    return Plan(
        kind, language, letter, reference, translation, guidance, tuple(notes), private_values(sources, facts)
    )


# --------------------------------------------------------------------------------------------------
# the model's part: free text, translation, notes
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Written:
    """What the model contributed (after sanitising), or the code fallback."""

    paragraphs: tuple[str, ...] = ()
    translation: str = ""
    notes: tuple[str, ...] = ()
    enclosures: tuple[str, ...] = ()
    subject: str | None = None
    by_model: bool = False
    removed_citations: bool = False
    failure: str | None = None


Private = tuple[tuple[str, str], ...]
_ADDRESS_LABELS = ("your address", "your new address", "your old address")


def private_values(sources: Sources, details: LetterDetails) -> Private:
    """The person's addresses and IBAN, which template letters may contain but the model never sees
    (docs/privacy.md: "never put into a prompt"), each with its own placeholder, so an
    answer that repeats a placeholder can be given the value back (:func:`_unmasked`). Longest values
    first, so a whole address is replaced before its lines."""
    found: dict[str, str] = {}
    iban = normalize_iban(sources.profile.iban)
    if iban:
        found[iban] = "[your IBAN]"
        found.setdefault(" ".join(iban[start : start + 4] for start in range(0, len(iban), 4)), "[your IBAN]")
    for label, text in zip(
        _ADDRESS_LABELS, (sources.profile.address, details.new_address, details.old_address), strict=True
    ):
        lines = address_lines(text)
        if lines:
            found.setdefault(", ".join(lines), f"[{label}]")
        if len(lines) > 1:
            for number, line in enumerate(lines, 1):
                found.setdefault(line, f"[{label}, line {number}]")
    return _longest_first(found)


def _longest_first(found: dict[str, str]) -> Private:
    return tuple(sorted(found.items(), key=lambda pair: (-len(pair[0]), pair[0])))


def letter_private_values(draft: Draft, sources: Sources) -> Private:
    """:func:`private_values` for a stored letter, whose template facts weren't kept: the profile's
    address and IBAN, the sender block's address, every valid IBAN in the letter and the addresses the
    template sentences carry (:data:`~ordnung.drafts.template_letters.ADDRESS_FRAMES`)."""
    found = dict(private_values(sources, LetterDetails()))
    for number, line in enumerate(draft.sender_block.splitlines()[1:], 1):
        if line.strip():
            found.setdefault(line.strip(), f"[your address, line {number}]")
    text = f"{draft.subject}\n{draft.body}"
    others = 0
    for iban in ibans_in_text(text):
        if iban not in found:
            others += 1
            found[iban] = f"[IBAN {others}]"
        grouped = " ".join(iban[start : start + 4] for start in range(0, len(iban), 4))
        found.setdefault(grouped, found[iban])
    addresses = 0
    for match in ADDRESS_FRAMES.finditer(text):
        value = next(group for group in match.groups() if group).strip()
        if value and value not in found:
            addresses += 1
            found[value] = f"[an address {addresses}]"
    return _longest_first(found)


def _masked(text: str, private: Private) -> str:
    for value, placeholder in private:
        text = text.replace(value, placeholder)
    return text


def _unmasked(text: str, private: Private) -> str:
    """The model's text with the values its placeholders stand for (the letter shows real values; an
    IBAN masked in two spellings comes back without spaces)."""
    values: dict[str, str] = {}
    for value, placeholder in reversed(private):  # shortest first
        values.setdefault(placeholder, value)
    for placeholder, value in values.items():
        text = re.compile(re.escape(placeholder), re.I).sub(value.replace("\\", "\\\\"), text)
    return text


def _parts_payload(parts: LetterParts, private: Private = ()) -> dict[str, object]:
    return {
        "subject": _masked(parts.subject, private),
        "salutation": parts.salutation,
        "fixed_paragraphs": [_masked(paragraph, private) for paragraph in parts.paragraphs],
        "closing": parts.closing,
    }


def _about_payload(sources: Sources) -> dict[str, object]:
    document, contract = sources.document, sources.contract
    return {
        "document": None
        if document is None
        else {
            "title": document.title,
            "kind": document.kind,
            "date": document.doc_date,
            "summary": document.summary,
            "references": [ref.model_dump() for ref in document.references],
        },
        "contract": None
        if contract is None
        else {
            "name": contract.name,
            "category": contract.category,
            "customer_number": contract.customer_number,
        },
    }


def model_payload(plan: Plan, sources: Sources, recipient: str) -> dict[str, object]:
    """The letter and background as the model sees it (no ids, no wall-clock data, and the person's
    addresses and IBAN replaced by placeholders: :func:`private_values`)."""
    reference = None
    if plan.reference is not None:
        reference_language = "de" if plan.translation_language == "de" else "en"
        reference = {
            "language": language_name(reference_language),
            **_parts_payload(plan.reference, plan.private),
        }
    return {
        "kind": plan.kind,
        "letter": _parts_payload(plan.letter, plan.private),
        "reference_translation": reference,
        "recipient": recipient.splitlines()[0] if recipient else None,
        "about": _about_payload(sources),
    }


def draft_request(
    plan: Plan, sources: Sources, recipient: str, instructions: str, settings: AppSettings
) -> LLMRequest:
    """The ``draft`` model call: document-derived text wrapped in ``<untrusted_document>``."""
    payload = model_payload(plan, sources, recipient)
    user_language = language_name(sources.profile.language)
    translation = language_name(plan.translation_language) if plan.translation_language else "none"
    system_version, system = render("draft_system")
    version, prompt = render(
        "draft",
        kind=_KIND_LABELS[plan.kind],
        letter_language=language_name(plan.language),
        translation_language=translation,
        user_language=user_language,
        context=untrusted_json(payload),
        instructions=untrusted_json(instructions),
    )
    basis = {
        "payload": payload,
        "instructions": instructions,
        "language": plan.language,
        "translation": plan.translation_language,
        "user_language": sources.profile.language,
    }
    return LLMRequest.model_validate(
        {
            "purpose": "draft",
            "prompt": prompt,
            "system": system,
            "schema": draft_schema(),
            "model": settings.models.draft,
            "cache_key": "draft:" + stable_hash(basis),
            "prompt_version": f"{system_version}+{version}",
            "doc_ids": [sources.document.id] if sources.document else [],
            "timeout_s": 120.0,
        }
    )


def _output(response: LLMResponse) -> DraftOutput | None:
    try:
        if response.data is not None:
            return DraftOutput.model_validate(response.data)
        return DraftOutput.model_validate_json(response.text)
    except ValidationError:
        return None


def _lowercase_start(paragraph: str) -> str:
    first = paragraph.split(" ", 1)[0]
    return paragraph[:1].lower() + paragraph[1:] if first in _LOWERCASE_STARTERS else paragraph


def free_paragraphs(text: str, *, signer: str = "") -> tuple[list[str], bool]:
    """Model free text as paragraphs: salutations, closings and signatures dropped, sentences citing
    a § removed (second value: whether any were), at most :data:`MAX_FREE_TEXT` characters."""
    paragraphs: list[str] = []
    removed = False
    used = 0
    for block in _PARAGRAPH_BREAK.split(text.strip()):
        lines = [
            line.strip()
            for line in block.splitlines()
            if line.strip() and not _FRAME_LINE_RE.match(line) and line.strip() != signer
        ]
        sentences = split_sentences(" ".join(lines))
        kept = [sentence for sentence in sentences if "§" not in sentence]
        removed = removed or len(kept) != len(sentences)
        paragraph = " ".join(kept)
        if not paragraph or used + len(paragraph) > MAX_FREE_TEXT:
            continue
        paragraphs.append(paragraph)
        used += len(paragraph)
    return paragraphs, removed


def _single_lines(values: list[str], *, limit: int, max_chars: int) -> tuple[str, ...]:
    cleaned = (" ".join(value.split()) for value in values)
    return tuple(dict.fromkeys(value for value in cleaned if value and len(value) <= max_chars))[:limit]


def _written_from(output: DraftOutput, plan: Plan, signer: str) -> Written:
    """The model's answer as the letter uses it, with the person's values back where it repeated a
    placeholder (:func:`private_values`)."""
    output = output.model_copy(
        update={
            "subject": _unmasked(output.subject, plan.private),
            "body": _unmasked(output.body, plan.private),
            "body_translation": _unmasked(output.body_translation, plan.private),
            "notes_for_user": [_unmasked(note, plan.private) for note in output.notes_for_user],
        }
    )
    paragraphs, removed = free_paragraphs(output.body, signer=signer)
    if plan.language == "de" and not plan.letter.paragraphs and paragraphs:
        paragraphs[0] = _lowercase_start(paragraphs[0])
    subject = " ".join(output.subject.split())
    usable_subject = subject if subject and len(subject) <= MAX_SUBJECT_CHARS and "§" not in subject else None
    translation = output.body_translation.strip() if plan.translation_language else ""
    return Written(
        paragraphs=tuple(paragraphs),
        translation=translation[:MAX_TRANSLATION],
        notes=tuple(
            note
            for note in _single_lines(output.notes_for_user, limit=MAX_MODEL_NOTES, max_chars=MAX_NOTE_CHARS)
            if "§" not in note
        ),
        enclosures=_single_lines(output.enclosures, limit=MAX_ENCLOSURES, max_chars=MAX_ENCLOSURE_CHARS),
        subject=usable_subject,
        by_model=True,
        removed_citations=removed,
    )


async def write_with_model(
    ctx: AppContext, plan: Plan, sources: Sources, recipient: str, instructions: str
) -> Written:
    """Ask the model for free text, translation and notes; a code fallback when it can't be used."""
    if sources.document is not None and sources.document.ai_private:
        return Written(failure="private")
    request = draft_request(plan, sources, recipient, instructions, ctx.settings)
    try:
        response = await ctx.llm.complete(request)
    except ReplayMiss as exc:
        log.info("draft: no recorded answer, using the fixed text only (%s)", exc)
        return Written(failure="replay")
    except LLMError as exc:
        log.info("draft: model unavailable, using the fixed text only (%s)", exc)
        return Written(failure="unavailable")
    output = _output(response)
    if output is None:
        log.warning("draft: the model's answer didn't match the schema; using the fixed text only")
        return Written(failure="unreadable")
    return _written_from(output, plan, sources.profile.name.strip())


# --------------------------------------------------------------------------------------------------
# assembling the draft
# --------------------------------------------------------------------------------------------------


def _letter_text(parts: LetterParts, paragraphs: tuple[str, ...]) -> str:
    return "\n\n".join([parts.salutation, *parts.paragraphs, *paragraphs])


def fallback_translation(
    parts: LetterParts, signer: str, language: LetterLanguage, *, free_text: bool = False
) -> str:
    """A translation built from the fixed templates (used when the model gives none).

    ``free_text``: the letter also has free text, which this translation can't include.
    """
    label = "Betreff" if language == "de" else "Subject"
    if free_text:
        extra: tuple[str, ...] = (_UNTRANSLATED[language],)
    else:
        extra = () if parts.paragraphs else (templates.BODY_PLACEHOLDER[language],)
    sign_off = "\n".join(line for line in (parts.closing, signer) if line)
    head = f"{label}: {parts.subject}" if parts.subject else ""
    return "\n\n".join(line for line in (head, _letter_text(parts, extra), sign_off) if line)


def _translation(plan: Plan, written: Written, signer: str) -> tuple[str, bool]:
    """``(translation, whether it is the code fallback)``."""
    if plan.translation_language is None:
        return "", False
    if written.translation:
        return written.translation, False
    if plan.reference is None:
        return "", False
    reference_language: LetterLanguage = "de" if plan.translation_language == "de" else "en"
    text = fallback_translation(
        plan.reference, signer, reference_language, free_text=bool(written.paragraphs)
    )
    return text, True


def _body_paragraphs(plan: Plan, written: Written) -> tuple[str, ...]:
    if written.paragraphs or plan.letter.paragraphs:
        return written.paragraphs
    return (templates.BODY_PLACEHOLDER[plan.language],)


#: What the person should know about each template letter (the law, not advice).
_TEMPLATE_NOTES: dict[str, tuple[str, ...]] = {
    "extension_request": (
        "Add a short reason in your wishes — offices decide case by case. Deadlines set by law (objections, "
        "court deadlines) can't be extended by asking: meet them anyway.",
    ),
    "defect_notice": (
        "Report defects straight away: if you don't, you can lose the right to reduce the rent for that time "
        "(§ 536c BGB). Describe the defect in German if you can, and keep photos.",
    ),
    "data_access": (
        "They must answer within one month of receiving it. SCHUFA also offers this free copy online "
        "('Datenkopie nach Art. 15 DSGVO') at meineschufa.de.",
        "If they ask you to prove who you are, send only what they need.",
    ),
    "receipts_inspection": (
        "Your objections to the statement must reach the landlord within 12 months of receiving it (§ 556 Abs. 3 BGB).",
    ),
    "deposit_return": (
        "There is no fixed legal deadline: landlords often take a few months and may keep part of the deposit "
        "until the next operating-cost statement.",
    ),
    "address_change": ("Registering at the Bürgeramt within two weeks of moving in is a separate duty.",),
}


#: What an objection the law gives a letter does (the other objections: :data:`_OBJECTION_NOTE`).
STATUTORY_OBJECTION_NOTES: dict[str, str] = {
    "court_payment_order": (
        "This letter objects to the whole claim; no reasons are needed. To object to only part of it (for "
        "example only the interest or the costs), don't send this letter: use the form that came with the "
        "order and tick how much you object to, or go to the court's Rechtsantragstelle. Send the form or "
        "this letter, not both. Get advice if you're unsure."
    ),
    "landlord_notice": (
        "The objection only helps if moving out would be a hardship for you or your household. Talk to "
        "a tenants' association before you send it; the reasons follow on request."
    ),
}
_OBJECTION_NOTE = (
    "The letter files the objection and says the reasons will follow. Get advice before you send "
    "reasons or if you're unsure."
)


def _kind_notes(plan: Plan, sources: Sources) -> list[str]:
    """Notes about what this kind of letter does and doesn't do."""
    letter_kind = sources.document.kind if sources.document else None
    if plan.kind == "objection":
        notes = [STATUTORY_OBJECTION_NOTES.get(letter_kind or "", _OBJECTION_NOTE)]
        reading = sources.extraction
        if (
            letter_kind == "landlord_notice"
            and reading is not None
            and extraordinary_notice(reading, sources.doc_date)
        ):
            # only drafted for the notice given in the alternative (:func:`objection_remedy`)
            notes.append(HARDSHIP_EXCLUDED)
        return notes
    notes = list(_TEMPLATE_NOTES.get(plan.kind, ()))
    if plan.kind == "payment_plan":
        tax = sources.party is not None and sources.party.kind == "tax_office"
        notes += (
            ["The tax office usually charges interest on a deferral."]
            if tax
            else ["Until they agree, the full amount stays due.", ACKNOWLEDGES_CLAIM]
        )
    if plan.kind == "deposit_return" and not sources.profile.iban:
        notes.append("Add your IBAN in Settings → Profile, or type it where the letter says [IBAN].")
    return notes


def _notes(plan: Plan, written: Written, fallback_used: bool, sources: Sources) -> list[str]:
    notes: list[str] = []
    if written.failure == "private":
        notes.append("This letter's source is kept private, so it was drafted without AI.")
    elif written.failure == "replay":
        # the zero-token demo has no recording for this letter: it is complete without one
        notes.append(
            "The demo uses Ordnung's fixed sentences only. With Claude connected, it also writes a short "
            "polite paragraph in your words."
        )
    elif written.failure is not None:
        # the reason is logged, never shown: it can hold internal details (SPEC §21 privacy)
        notes.append("The AI couldn't help this time, so the letter uses Ordnung's fixed sentences only.")
    if not written.paragraphs and not plan.letter.paragraphs:
        notes.append(
            f"Write your message where the letter says “{templates.BODY_PLACEHOLDER[plan.language]}”."
        )
    if written.removed_citations:
        notes.append("A sentence citing a law was removed — Ordnung letters don't argue legal points.")
    if plan.guidance.form == "written_form" and plan.guidance.form_note:
        notes.append(plan.guidance.form_note)
    notes.extend(plan.notes)
    notes.extend(_kind_notes(plan, sources))
    if fallback_used and plan.translation_language not in ("de", "en"):
        notes.append("The translation is in English because the AI translation wasn't available.")
    notes.extend(written.notes)
    checked = templates.format_date(date.fromisoformat(LAST_CHECKED), "en")
    notes.append(f"Based on the law as of {checked}. Not legal advice. Not reviewed by a lawyer.")
    return notes


def check_context(
    store: Store, sources: Sources, draft: Draft, *, channel: str | None = None
) -> CheckContext:
    """What the checks compare ``draft`` against, from the ledger."""
    profile, party, document = sources.profile, sources.party, sources.document
    doc_text = store.get_document_text(document.id) if document else ""
    remedy = sources.remedy
    known_ids = [*known_references(sources), profile.email, profile.phone, profile.iban]
    known_texts = [profile.address, doc_text]
    if party is not None:
        known_ids.extend([*party.ibans, party.email or "", party.phone or ""])
        known_texts.append(party.address or "")
    if document is not None and document.payment is not None and document.payment.iban:
        known_ids.append(document.payment.iban)
    if remedy is not None:
        known_texts.extend(text for text in (remedy.addressee, remedy.quote, remedy.form_text) if text)
    return CheckContext(
        references=tuple(known_references(sources)),
        doc_date=sources.doc_date,
        known_ids=tuple(value for value in known_ids if value),
        known_texts=tuple(text for text in known_texts if text),
        source_text="\n".join(text for text in (doc_text, remedy.quote if remedy else None) if text),
        guidance=draft.send_guidance,
        channel=channel,
    )


def _validate_request(kind: str, language: str) -> tuple[DraftKind, LetterLanguage]:
    if kind not in DRAFT_KINDS:
        raise DraftError(
            f"Ordnung drafts cancellations, objections, replies and its letter templates — not “{kind}”."
        )
    if language not in templates.LETTER_LANGUAGES:
        raise DraftError("Letters can be written in German or English.")
    return cast(DraftKind, kind), cast(LetterLanguage, language)


async def compose(
    ctx: AppContext,
    kind: str,
    *,
    doc_id: str | None = None,
    contract_id: str | None = None,
    party_id: str | None = None,
    instructions: str = "",
    language: str = "de",
    suspend_enforcement: bool = False,
    details: LetterDetails | None = None,
) -> Draft:
    """Draft, check and store a letter; raises :class:`DraftError` when it can't be drafted as asked.

    ``suspend_enforcement`` (the person ticked it; never read from the free-text wishes, where "don't
    suspend enforcement" would read the same) adds the application to suspend enforcement to an
    objection. ``details`` are the facts a template letter needs
    (:data:`~ordnung.drafts.template_letters.TEMPLATES`).
    """
    draft_kind, letter_language = _validate_request(kind, language)
    store, today = ctx.store, local_today(ctx.store)
    instructions = instructions.strip()[:MAX_INSTRUCTIONS]
    sources = load_sources(store, draft_kind, doc_id=doc_id, contract_id=contract_id, party_id=party_id)
    plan = plan_letter(
        store,
        draft_kind,
        sources,
        letter_language,
        suspend_enforcement=suspend_enforcement,
        today=today,
        details=details,
    )
    recipient = recipient_block(draft_kind, sources, details)
    written = await write_with_model(ctx, plan, sources, recipient, instructions)
    signer = sources.profile.name.strip()
    translation, fallback_used = _translation(plan, written, signer)
    now = now_iso()
    draft = Draft(
        id=new_id("drf"),
        kind=draft_kind,
        language=letter_language,
        party_id=sources.party.id if sources.party else None,
        case_id=sources.case_id,
        doc_id=sources.document.id if sources.document else None,
        contract_id=sources.contract.id if sources.contract else None,
        sender_block=sender_block(sources.profile),
        recipient_block=recipient,
        place_date=place_date(sources.profile, today, letter_language),
        subject=plan.letter.subject or written.subject or "",
        body=_letter_text(plan.letter, _body_paragraphs(plan, written)),
        body_translation=translation,
        enclosures=list(written.enclosures),
        notes_for_user=_notes(plan, written, fallback_used, sources),
        send_guidance=plan.guidance,
        created_at=now,
        updated_at=now,
    )
    draft.checks = run_checks(draft, check_context(store, sources, draft))
    with store.tx():
        stored = store.add_draft(**draft.model_dump())
        store.log_activity(
            "draft.created",
            f"Drafted a letter: {stored.subject or _KIND_LABELS[draft_kind]}",
            ref_type="draft",
            ref_id=stored.id,
            data={"kind": draft_kind, "ai": written.by_model},
        )
    ctx.bus.publish("draft.created", draft_id=stored.id, kind=draft_kind)
    return stored


def refresh_checks(store: Store, draft_id: str, *, channel: str | None = None) -> Draft:
    """Re-run the checks of a stored draft (after the person edited it) and save them."""
    draft = store.get_draft(draft_id)
    if draft is None:
        raise NotFoundError(f"drafts: no row with id {draft_id!r}")
    sources = sources_for_draft(store, draft)
    checks = run_checks(draft, check_context(store, sources, draft, channel=channel))
    return store.update_draft(draft_id, checks=checks)


# --------------------------------------------------------------------------------------------------
# translating an edited letter again
# --------------------------------------------------------------------------------------------------


def translation_request(
    draft: Draft, sources: Sources, target: str, settings: AppSettings, private: Private = ()
) -> LLMRequest:
    """The ``draft`` model call that only translates the letter as it stands (subject and text), with
    the person's addresses and IBAN replaced by placeholders (``private``: :func:`letter_private_values`)."""
    letter = {"subject": _masked(draft.subject, private), "text": _masked(draft.body, private)}
    system_version, system = render("draft_translate_system")
    version, prompt = render(
        "draft_translate",
        letter_language=language_name(draft.language),
        translation_language=language_name(target),
        letter=untrusted_json(letter),
    )
    basis = {"letter": letter, "language": draft.language, "translation": target}
    return LLMRequest.model_validate(
        {
            "purpose": "draft",
            "prompt": prompt,
            "system": system,
            "schema": draft_translation_schema(),
            "model": settings.models.draft,
            "cache_key": "draft-translation:" + stable_hash(basis),
            "prompt_version": f"{system_version}+{version}",
            "doc_ids": [sources.document.id] if sources.document else [],
            "timeout_s": 120.0,
        }
    )


def _translation_text(response: LLMResponse) -> str:
    try:
        if response.data is not None:
            output = DraftTranslationOutput.model_validate(response.data)
        else:
            output = DraftTranslationOutput.model_validate_json(response.text)
    except ValidationError:
        return ""
    return output.body_translation.strip()[:MAX_TRANSLATION]


async def retranslate(ctx: AppContext, draft_id: str) -> Draft:
    """Translate a (edited) letter again into the person's language; only the translation changes.

    Raises :class:`DraftError` when there is nothing to translate or the letter's source is kept
    private, :class:`~ordnung.llm.base.LLMError` when the model can't help.
    """
    store = ctx.store
    draft = store.get_draft(draft_id)
    if draft is None:
        raise NotFoundError(f"drafts: no row with id {draft_id!r}")
    sources = sources_for_draft(store, draft)
    if sources.document is not None and sources.document.ai_private:
        raise DraftError(
            "This letter is about a letter you keep private, so Ordnung doesn't send it to the AI."
        )
    target = translation_language(sources.profile, draft.language)
    if target is None:
        raise DraftError("This letter is already in your language, so there is nothing to translate.")
    if not draft.body.strip():
        raise DraftError("The letter is empty — write it first, then translate it.")
    private = letter_private_values(draft, sources)
    request = translation_request(draft, sources, target, ctx.settings, private)
    response = await ctx.llm.complete(request)
    text = _translation_text(response)
    if not text and response.cache_hit:  # an unusable answer from the cache: ask afresh once
        text = _translation_text(await ctx.llm.complete(request, use_cache=False))
    if not text:
        raise ClaudeBadOutput("The translation couldn't be read. Please try again.")
    text = _unmasked(text, private)
    with store.tx():
        updated = store.update_draft(draft_id, body_translation=text)
        store.log_activity(
            "draft.translated",
            f"Translated your letter again: {draft.subject or _KIND_LABELS[draft.kind]}",
            ref_type="draft",
            ref_id=draft_id,
        )
    return updated


# --------------------------------------------------------------------------------------------------
# marking a letter as sent
# --------------------------------------------------------------------------------------------------


def _channel_label(draft: Draft, channel: str) -> str:
    guidance = draft.send_guidance
    entry = (
        next((option for option in guidance.channels if option.channel == channel), None)
        if guidance
        else None
    )
    return entry.label if entry else channel.replace("_", " ")


def _followup_fields(draft: Draft, sources: Sources, sent_on: date, channel: str) -> dict[str, object]:
    wait = FOLLOWUP_DAYS_BY_KIND.get(draft.kind, FOLLOWUP_DAYS)
    due = sent_on + timedelta(days=wait)
    who = sources.party.name if sources.party else None
    sent_label = templates.format_date(sent_on, "en")
    receipt = ComputationReceipt(
        due_date=due.isoformat(),
        summary=f"You sent the letter on {sent_label}; {wait} days later is {templates.format_date(due, 'en')}.",
        steps=[
            ComputationStep(label="Letter sent", date=sent_on.isoformat()),
            ComputationStep(label=f"{wait} days to wait for a reply", date=due.isoformat()),
        ],
        confidence="high",
    )
    if sources.contract is not None:
        area = contract_area(sources.contract)
    else:
        area = sources.document.area if sources.document and sources.document.area else "other"
    return {
        "kind": "task",
        "title": f"Check for a reply from {who}" if who else "Check for a reply to your letter",
        "description": f"You sent “{draft.subject}” on {sent_label} ({_channel_label(draft, channel)}).",
        "action": "If nothing has arrived, call them or send a short reminder — and keep a note of it.",
        "due_date": due.isoformat(),
        "due_date_source": "computed",
        "computation": receipt,
        "status": "open",
        "priority": "normal",
        "area": area,
        "party_id": draft.party_id,
        "case_id": draft.case_id,
        "contract_id": draft.contract_id,
        "doc_id": draft.doc_id,
        "grounding": "user",
        "origin": "draft",
    }


def _save_followup(store: Store, draft: Draft, fields: dict[str, object]) -> Item:
    item_id = content_id("itm", "followup", draft.id)
    existing = store.get_item(item_id)
    if existing is None:
        return store.add_item(id=item_id, **fields)
    if existing.user_modified:
        return existing
    return store.update_item(item_id, **fields)


def mark_sent(ctx: AppContext, draft_id: str, channel: str, sent_on: date | str) -> tuple[Draft, Item]:
    """Record that a letter was sent (how and when) and create its follow-up to-do 21 days later.

    The checks are re-run with the channel, so a rent or employment notice sent by e-mail is flagged.
    Marking the same letter again updates its follow-up instead of adding another one.
    """
    store = ctx.store
    draft = store.get_draft(draft_id)
    if draft is None:
        raise NotFoundError(f"drafts: no row with id {draft_id!r}")
    if channel not in SEND_CHANNELS:
        raise DraftError(f"Unknown way of sending: “{channel}”.")
    day = sent_on if isinstance(sent_on, date) else parse_day(sent_on)
    if day is None:
        raise DraftError(f"“{sent_on}” is not a date.")
    if day > local_today(store):  # the person's today, as in the app (not the computer's date)
        raise DraftError("The sending date can't be in the future.")
    sources = sources_for_draft(store, draft)
    sent = draft.model_copy(update={"status": "sent", "sent_at": day.isoformat(), "sent_channel": channel})
    checks = run_checks(sent, check_context(store, sources, sent, channel=channel))
    with store.tx():
        updated = store.update_draft(
            draft_id, status="sent", sent_at=day.isoformat(), sent_channel=channel, checks=checks
        )
        item = _save_followup(store, updated, _followup_fields(updated, sources, day, channel))
        store.log_activity(
            "draft.sent",
            f"Marked “{updated.subject}” as sent ({_channel_label(updated, channel)})",
            ref_type="draft",
            ref_id=draft_id,
            data={"channel": channel, "sent_on": day.isoformat(), "followup_item_id": item.id},
        )
    ctx.bus.publish("draft.sent", draft_id=draft_id, item_id=item.id)
    ctx.bus.publish("item.updated", item_id=item.id)
    return updated, item
