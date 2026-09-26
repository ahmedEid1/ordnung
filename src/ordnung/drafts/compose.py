"""Compose a letter (SPEC §11, §21): fixed operative sentences, optional model text, checks, send guidance.

Code decides everything legally relevant: the kind of letter (an objection only when the letter's
Rechtsbehelfsbelehrung names an Einspruch or Widerspruch), the operative sentences
(:mod:`ordnung.drafts.templates`), recipient and sender blocks, place and date, subject with
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
from ordnung.drafts.templates import LetterLanguage, LetterParts, RemedyKind
from ordnung.ids import content_id, new_id
from ordnung.llm.base import ClaudeBadOutput, LLMError, LLMRequest, LLMResponse, ReplayMiss
from ordnung.llm.prompts import render
from ordnung.llm.schemas import draft_schema, draft_translation_schema
from ordnung.models import (
    AppSettings,
    ComputationReceipt,
    ComputationStep,
    Contract,
    Document,
    DocumentExtraction,
    Draft,
    DraftKind,
    DraftOutput,
    DraftTranslationOutput,
    Item,
    Party,
    Profile,
    Remedy,
    SendChannel,
    SendGuidance,
)
from ordnung.rules import LAST_CHECKED, send_guidance
from ordnung.secretary.review import language_name, split_sentences, stable_hash, untrusted_json
from ordnung.secretary.triggers import Ledger, contract_area, contract_computation, parse_day, postal_buffer
from ordnung.tick import local_today

if TYPE_CHECKING:
    from ordnung.app_context import AppContext

log = logging.getLogger(__name__)

FOLLOWUP_DAYS = 21
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
}
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
_SUSPEND_RE = re.compile(r"aussetzung der vollziehung|suspen(?:d|sion of) (?:the )?enforcement", re.I)
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


def recipient_block(kind: str, sources: Sources) -> str:
    """Name and address of the recipient; for objections the addressee named in the remedy."""
    if kind == "objection":
        return "\n".join(_objection_recipient(sources.remedy, sources.party))
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


def _person_name(kind: str, party: Party | None) -> str | None:
    if kind == "objection" or party is None or party.kind != "person":
        return None
    return party.name


def objection_remedy(sources: Sources) -> RemedyKind:
    """The remedy an objection letter uses; raises :class:`DraftError` unless it is Einspruch/Widerspruch."""
    if sources.document is None:
        raise DraftError("Choose the decision (the letter) you want to object to.")
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


def _frame(
    kind: str,
    sources: Sources,
    language: LetterLanguage,
    *,
    end_date: date | None,
    suspend_enforcement: bool,
) -> LetterParts:
    person = _person_name(kind, sources.party)
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
) -> Plan:
    """The code-written frame, reference translation and send guidance of a letter."""
    end_date, due = _letter_due(store, kind, sources, today)
    letter = _frame(kind, sources, language, end_date=end_date, suspend_enforcement=suspend_enforcement)
    translation = translation_language(sources.profile, language)
    reference_language: LetterLanguage = "de" if translation == "de" else "en"
    reference = (
        _frame(kind, sources, reference_language, end_date=end_date, suspend_enforcement=suspend_enforcement)
        if translation
        else None
    )
    party = sources.party
    guidance = send_guidance(
        kind,
        contract_category=sources.contract.category if sources.contract else None,
        party_kind=party.kind if party else None,
        due=due,
        region=party.region if party else None,
        today=today,
        postal_buffer_days=postal_buffer(sources.profile),
    )
    return Plan(kind, language, letter, reference, translation, guidance)


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


def _parts_payload(parts: LetterParts) -> dict[str, object]:
    return {
        "subject": parts.subject,
        "salutation": parts.salutation,
        "fixed_paragraphs": list(parts.paragraphs),
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
    """The letter and background as the model sees it (no ids, no wall-clock data)."""
    reference = None
    if plan.reference is not None:
        reference_language = "de" if plan.translation_language == "de" else "en"
        reference = {"language": language_name(reference_language), **_parts_payload(plan.reference)}
    return {
        "kind": plan.kind,
        "letter": _parts_payload(plan.letter),
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


def _notes(plan: Plan, written: Written, fallback_used: bool) -> list[str]:
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
    if plan.kind == "objection":
        notes.append(
            "The letter files the objection and says the reasons will follow. Get advice before you send "
            "reasons or if you're unsure."
        )
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
    known_ids = [*known_references(sources), profile.email, profile.phone]
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
        raise DraftError(f"Ordnung can draft a cancellation, an objection or a general reply, not “{kind}”.")
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
) -> Draft:
    """Draft, check and store a letter; raises :class:`DraftError` when it can't be drafted as asked.

    ``suspend_enforcement`` (or instructions asking for "Aussetzung der Vollziehung") adds the
    application to suspend enforcement to an objection.
    """
    draft_kind, letter_language = _validate_request(kind, language)
    store, today = ctx.store, local_today(ctx.store)
    instructions = instructions.strip()[:MAX_INSTRUCTIONS]
    suspend = suspend_enforcement or bool(_SUSPEND_RE.search(instructions))
    sources = load_sources(store, draft_kind, doc_id=doc_id, contract_id=contract_id, party_id=party_id)
    plan = plan_letter(store, draft_kind, sources, letter_language, suspend_enforcement=suspend, today=today)
    recipient = recipient_block(draft_kind, sources)
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
        notes_for_user=_notes(plan, written, fallback_used),
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


def translation_request(draft: Draft, sources: Sources, target: str, settings: AppSettings) -> LLMRequest:
    """The ``draft`` model call that only translates the letter as it stands (subject and text)."""
    letter = {"subject": draft.subject, "text": draft.body}
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
    request = translation_request(draft, sources, target, ctx.settings)
    response = await ctx.llm.complete(request)
    text = _translation_text(response)
    if not text and response.cache_hit:  # an unusable answer from the cache: ask afresh once
        text = _translation_text(await ctx.llm.complete(request, use_cache=False))
    if not text:
        raise ClaudeBadOutput("The translation couldn't be read. Please try again.")
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
    due = sent_on + timedelta(days=FOLLOWUP_DAYS)
    who = sources.party.name if sources.party else None
    sent_label = templates.format_date(sent_on, "en")
    receipt = ComputationReceipt(
        due_date=due.isoformat(),
        summary=f"You sent the letter on {sent_label}; {FOLLOWUP_DAYS} days later is {templates.format_date(due, 'en')}.",
        steps=[
            ComputationStep(label="Letter sent", date=sent_on.isoformat()),
            ComputationStep(label=f"{FOLLOWUP_DAYS} days to wait for a reply", date=due.isoformat()),
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
