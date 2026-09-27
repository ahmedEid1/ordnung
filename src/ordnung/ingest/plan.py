"""From a validated extraction to ledger rows: verify, compute, plan (SPEC § 8 stages 5–7, § 21).

* :func:`verify_extraction` grounds every quote on the page texts (text layer → ``verified``,
  AI transcript → ``model_read``, not found → ``unverified``) and checks each item's DateSpec and
  amount against its quote (:func:`~ordnung.ingest.verify.spec_consistency`).
* :func:`compute_item` runs the rules engine and lowers the confidence per the § 21 rubric using
  the grounding and consistency results, listing the reasons in the receipt's warnings.
* :func:`write_plan` upserts items by ``slot_key`` (never touching rows the person edited), deletes
  stale extracted items, files the deadlines the law adds to high-stakes letters
  (:func:`sync_rule_items`) and writes the document's facts, status and activity entry. Reading a letter
  again keeps what the person did: letter facts they corrected (:func:`corrections`) and to-dos they
  acted on (paid, snoozed, dismissed …) or that repeat, which move to the new reading's slot when it
  quotes their sentence differently; a recurring to-do never moves back on its schedule
  (:mod:`ordnung.recurrence`, point 6).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Literal

from ordnung.clock import now_iso
from ordnung.db.store import Store
from ordnung.ingest.link import LinkResult
from ordnung.ingest.normalize import normalise_with_map
from ordnung.ingest.verify import (
    AMOUNT_NOT_IN_QUOTE,
    DATE_NOT_IN_QUOTE,
    DATE_WITHOUT_YEAR,
    PageInput,
    grade_reading,
    ground_evidence,
    parse_amounts,
    parse_dates,
    spec_consistency,
)
from ordnung.models import (
    DOCUMENT_KINDS,
    HIGH_STAKES_KINDS,
    ComputationReceipt,
    DateSpec,
    Document,
    DocumentExtraction,
    DocumentStatus,
    Evidence,
    ExtractedItem,
    Item,
    KeyFact,
    LetterKind,
    Party,
    PaymentDetails,
    Remedy,
)
from ordnung.recurrence import (
    SCHEDULE_FIELDS,
    at_occurrence,
    keeps_later_date,
    roll_forward,
    same_rule,
    same_schedule,
)
from ordnung.rules import RuleContext, compute_due, scope_for_party_kind
from ordnung.rules.advice import (
    LATE_STATEMENT_WARNING,
    RENT_INCREASE_PAYMENT_WARNING,
    statement_arrival,
    statement_late,
)
from ordnung.rules.deadlines import parse_date
from ordnung.rules.routing import (
    DerivedDeadline,
    alternative_notice,
    announced_end,
    computed_under,
    derived_deadlines,
    extraordinary_notice,
    is_court,
    is_labour_court,
    letter_kind,
    names_statement,
)
from ordnung.secretary.scam import iban_from_page, iban_valid, normalize_iban

DueDateSource = Literal["computed", "fixed", "manual", "none"]

_KIND_NOUNS: dict[str, tuple[str, str]] = {
    "deadline": ("deadline", "deadlines"),
    "payment": ("payment", "payments"),
    "appointment": ("appointment", "appointments"),
    "task": ("task", "tasks"),
    "expiry": ("expiry date", "expiry dates"),
    "reminder": ("reminder", "reminders"),
    "milestone": ("milestone", "milestones"),
}


# --------------------------------------------------------------------------------------------------
# Verify
# --------------------------------------------------------------------------------------------------


def slot_key(kind: str, quote: str) -> str:
    """Stable identity of an item within its document: ``sha1(kind|normalised quote)``."""
    normalised, _ = normalise_with_map(quote)
    return hashlib.sha1(f"{kind}|{normalised}".encode(), usedforsecurity=False).hexdigest()


def slot_keys(items: Sequence[ExtractedItem]) -> list[str]:
    """Slot keys for a document's items; repeats of the same kind and quote get ``#2``, ``#3`` …"""
    seen: Counter[str] = Counter()
    keys = []
    for item in items:
        key = slot_key(item.kind, item.quote)
        seen[key] += 1
        keys.append(key if seen[key] == 1 else f"{key}#{seen[key]}")
    return keys


@dataclass(frozen=True)
class VerifiedItem:
    """An extracted item with its evidence and the problems found between its values and quote."""

    item: ExtractedItem
    evidence: Evidence
    reasons: tuple[str, ...]
    slot_key: str

    @property
    def dated(self) -> bool:
        """Whether the item describes a date (fixed or relative)."""
        return self.item.date.type != "none"

    @property
    def needs_check(self) -> bool:
        """A dated item whose quote was not found or does not state its values ("Please check")."""
        return self.dated and (self.evidence.grounding == "unverified" or bool(self.reasons))


def needs_check(item: Item) -> bool:
    """An open, dated to-do whose quote was not found or does not state its values, not yet confirmed
    (a to-do marked done or "not a real to-do" leaves nothing to check). A deadline the law adds
    (``origin="rule"``) quotes nothing, so it has nothing to check — unless it counts from an end date
    the letter doesn't write (:func:`sync_rule_items` gives it the termination's sentence as evidence,
    not stating that date)."""
    dated = item.due_date is not None or (item.date_spec is not None and item.date_spec.type != "none")
    if not dated or item.grounding == "user" or item.status not in ("open", "snoozed"):
        return False
    if item.origin == "rule":
        return any(not evidence.value_consistent for evidence in item.evidence)
    return item.grounding == "unverified" or any(not evidence.value_consistent for evidence in item.evidence)


@dataclass
class Verification:
    """Grounding results for everything a document's extraction quotes."""

    items: list[VerifiedItem]
    key_facts: list[KeyFact]
    contract_evidence: list[Evidence]
    change_evidence: Evidence | None = None
    remedy_evidence: Evidence | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        """Whether the document must be shown as "Please check"."""
        return any(verified.needs_check for verified in self.items)


def _page_text(page: PageInput) -> str:
    if isinstance(page, tuple):
        return page[1]
    return page.text


def _stated_in_document(item: ExtractedItem, reason: str, pages: Sequence[PageInput]) -> bool:
    """Whether a value missing from the item's own sentence is written elsewhere in the letter
    (e.g. the invoice total two lines above "payable within 14 days"), or is a schedule's
    occurrence rather than a single stated date."""
    if reason == AMOUNT_NOT_IN_QUOTE and item.amount is not None:
        return any(
            abs(value - item.amount) < 0.005 for page in pages for value in parse_amounts(_page_text(page))
        )
    if reason in (DATE_NOT_IN_QUOTE, DATE_WITHOUT_YEAR) and item.date.type == "fixed":
        if item.recurrence is not None:
            return True  # "every month on the 15th": the date is the next occurrence of the schedule
        target = item.date.date
        for page in pages:
            for mention in parse_dates(_page_text(page)):
                found = mention.as_date()
                if target is not None and found is not None and found.isoformat() == target:
                    return True
    return False


def consistency_reasons(item: ExtractedItem, pages: Sequence[PageInput]) -> tuple[str, ...]:
    """Why the item's quote doesn't state its DateSpec or amount — values written elsewhere in the
    letter excepted (the same grading when a letter is read and when its dates are recomputed)."""
    if item.date.type == "none" and item.amount is None:
        return ()
    _, found = spec_consistency(item.quote, item.date, item.amount)
    return tuple(reason for reason in found if not _stated_in_document(item, reason, pages))


def _verify_item(doc_id: str, item: ExtractedItem, key: str, pages: Sequence[PageInput]) -> VerifiedItem:
    evidence = ground_evidence(doc_id, item.quote, pages)
    reasons = consistency_reasons(item, pages)
    evidence = evidence.model_copy(update={"value_consistent": not reasons})
    return VerifiedItem(item=item, evidence=evidence, reasons=reasons, slot_key=key)


def _optional_evidence(doc_id: str, quote: str | None, pages: Sequence[PageInput]) -> Evidence | None:
    return ground_evidence(doc_id, quote, pages) if quote and quote.strip() else None


def verify_extraction(
    doc_id: str, extraction: DocumentExtraction, pages: Sequence[PageInput]
) -> Verification:
    """Ground every quote of ``extraction`` on ``pages`` and collect "please check" warnings."""
    items = [
        _verify_item(doc_id, item, key, pages)
        for item, key in zip(extraction.items, slot_keys(extraction.items), strict=True)
    ]
    verification = Verification(
        items=items,
        key_facts=[
            KeyFact(label=fact.label, value=fact.value, evidence=ground_evidence(doc_id, fact.quote, pages))
            for fact in extraction.key_facts
        ],
        contract_evidence=[
            ground_evidence(doc_id, quote, pages)
            for quote in (extraction.contract.quotes if extraction.contract else [])
        ],
        change_evidence=_optional_evidence(
            doc_id, extraction.change.quote if extraction.change else None, pages
        ),
        remedy_evidence=_optional_evidence(
            doc_id, extraction.remedy.quote if extraction.remedy else None, pages
        ),
    )
    verification.warnings = _verification_warnings(verification)
    return verification


def _verification_warnings(verification: Verification) -> list[str]:
    warnings = []
    unchecked = sum(verified.needs_check for verified in verification.items)
    if unchecked:
        dates = "1 date" if unchecked == 1 else f"{unchecked} dates"
        warnings.append(f"Please check: {dates} could not be confirmed against the letter's text.")
    if verification.remedy_evidence and verification.remedy_evidence.grounding == "unverified":
        warnings.append(
            "We couldn't find the instructions on how to object (Rechtsbehelfsbelehrung) in the letter — please check them."
        )
    if verification.change_evidence and verification.change_evidence.grounding == "unverified":
        warnings.append("We couldn't find the announced change in the letter — please check it.")
    return warnings


# --------------------------------------------------------------------------------------------------
# Compute
# --------------------------------------------------------------------------------------------------


def remedy_text(remedy: Remedy | None) -> str:
    """The remedy notice's words (quote, addressee, period, form) for the delivery-scope check."""
    if remedy is None:
        return ""
    parts = (remedy.quote, remedy.addressee, remedy.period_text, remedy.form_text)
    return " ".join(part for part in parts if part)


def end_date_grounding(
    extraction: DocumentExtraction, pages: Sequence[PageInput]
) -> Literal["quote", "letter", "none"]:
    """Where the end a termination announces (:func:`~ordnung.rules.routing.announced_end`, read by the
    model) is written, as items' dates are checked (SPEC § 21): in the termination's own sentence, found
    on the page (``quote``); only elsewhere in the letter (``letter``); or nowhere in it (``none``: the
    model may have misread it, or worked it out from "gesetzliche Kündigungsfrist"). A reading without
    an end has nothing to ground (``quote``)."""
    end = announced_end(extraction)
    if end is None or extraction.change is None:
        return "quote"

    def writes_end(text: str) -> bool:
        return any(mention.as_date() == end for mention in parse_dates(text))

    quote = extraction.change.quote
    if writes_end(quote) and ground_evidence("", quote, pages).grounding != "unverified":
        return "quote"
    return "letter" if any(writes_end(_page_text(page)) for page in pages) else "none"


def rule_context(
    party: Party | None,
    document: Document,
    extraction: DocumentExtraction,
    today: date,
    *,
    recipient_region: str | None = None,
    country: str = "DE",
    filed_as: str | None = None,
    pages: Sequence[PageInput] = (),
) -> RuleContext:
    """Facts the rules engine needs besides the DateSpec (SPEC § 21).

    The holiday region is the sender's (``Party.region``; unknown → nationwide holidays only, the
    earlier date); ``recipient_region`` is where the person lives (``Profile.known_region``: only a
    Land they chose) and ``country`` their ``Profile.country`` (non-German → ``low`` confidence, as
    for contracts). The delivery scope follows the sender's kind, name and remedy notice (tax office →
    AO, health insurer or social-benefits agency → SGB X, other authorities → VwVfG; see
    :func:`ordnung.rules.scope_for_party_kind`). A received date on the document was entered by the person, so
    it counts as confirmed. ``filed_as`` is the letter's kind (default: the reading's, :func:`letter_kind`),
    which routes the dates of high-stakes letters; a termination's end date comes with it, graded against
    the letter's ``pages`` (:func:`end_date_grounding`; without pages it counts as not written). A court's
    letter is marked as one (and a labour court's), whatever kind it was filed as: its dates never use a
    delivery fiction and are never ``high``.
    """
    sender = extraction.sender
    kind = party.kind if party else (sender.kind if sender else None)
    name = party.name if party else (sender.name if sender else "")
    remedy = extraction.remedy
    return RuleContext(
        today=today,
        country=country,
        region=party.region if party else None,
        document_date=parse_date(extraction.document_date),
        received_date=parse_date(document.received_date),
        received_confirmed=document.received_date is not None,
        delivery_scope=scope_for_party_kind(
            kind,
            name=party.name if party else (sender.name if sender else None),
            remedy_type=remedy.type if remedy else None,
            remedy_text=remedy_text(remedy),
        ),
        recipient_region=recipient_region,
        letter_kind=filed_as or letter_kind(extraction),
        end_date=announced_end(extraction),
        end_date_grounding=end_date_grounding(extraction, pages),
        court=is_court(name, kind),
        labour_court=is_labour_court(name, kind),
    )


def document_context(store: Store, document: Document, today: date) -> RuleContext | None:
    """The :func:`rule_context` of a letter that was read: its stored reading with the letter's date
    as stored (the person may have corrected it), its sender and the person's region and country;
    ``None`` for a letter without a reading."""
    extraction = store.get_extraction(document.id)
    if extraction is None:
        return None
    extraction = extraction.model_copy(update={"document_date": document.doc_date})
    party = store.get_party(document.party_id) if document.party_id else None
    profile = store.get_profile()
    return rule_context(
        party,
        document,
        extraction,
        today,
        recipient_region=profile.known_region,
        country=profile.country,
        filed_as=document.kind,
        pages=store.list_pages(document.id),
    )


def item_context(store: Store, item: Item, today: date) -> RuleContext:
    """The context of a to-do's dates: its letter's (:func:`document_context`), else nationwide
    holidays in the person's country (a to-do added by hand)."""
    document = store.get_document(item.doc_id) if item.doc_id else None
    found = document_context(store, document, today) if document is not None else None
    return found or RuleContext(today=today, country=store.get_profile().country)


@dataclass(frozen=True)
class ComputedDate:
    """The rules engine's result for one item."""

    receipt: ComputationReceipt | None
    due_date: str | None
    send_by: str | None
    source: DueDateSource


def grade_receipt(receipt: ComputationReceipt, verified: VerifiedItem) -> ComputationReceipt:
    """Apply the § 21 confidence rubric's reading conditions (quote located, quote stating the
    DateSpec: :func:`~ordnung.ingest.verify.grade_reading`) on top of the engine's own grade."""
    return grade_reading(receipt, verified.evidence.grounding, verified.reasons)


def compute_item(verified: VerifiedItem, ctx: RuleContext, *, postal_buffer_days: int) -> ComputedDate:
    """Due date, send-by date and receipt of one item (no receipt for undated items)."""
    spec = verified.item.date
    if spec.type == "none":
        return ComputedDate(receipt=None, due_date=None, send_by=None, source="none")
    receipt = grade_receipt(compute_due(spec, ctx, postal_buffer_days=postal_buffer_days), verified)
    source: DueDateSource = (
        "none" if receipt.due_date is None else ("fixed" if spec.type == "fixed" else "computed")
    )
    return ComputedDate(receipt=receipt, due_date=receipt.due_date, send_by=receipt.send_by, source=source)


def is_statement(kind: str | None, extraction: DocumentExtraction | None) -> bool:
    """Whether a letter is an operating-cost statement: filed as one, or — as its dates don't depend on its
    kind — recognised from its reading when it isn't filed as another high-stakes kind or as a reminder
    (:func:`~ordnung.rules.routing.names_statement`: only the statement itself, never a reminder about
    an old statement's back-payment)."""
    if kind == "operating_costs":
        return True
    return (
        kind not in (*HIGH_STAKES_KINDS, "dunning") and extraction is not None and names_statement(extraction)
    )


def late_statement_warning(statement: bool, title: str | None, text: str, ctx: RuleContext) -> str | None:
    """The warning an operating-cost statement's back-payment carries when the letter's card calls it too
    late (:func:`~ordnung.rules.advice.statement_late`, from the same arrival day, Land and text — the
    statement's own date when the text dates it before the letter, :func:`~ordnung.rules.advice.
    statement_arrival`): it may not be owed (§ 556 Abs. 3 S. 3 BGB). The to-do stays open — the landlord
    may not be responsible for the delay, and nothing is ever dismissed for the person (ADR 0006)."""
    if not statement:
        return None
    body = f"{title or ''}\n{text}"
    received = ctx.received_date if ctx.received_confirmed and ctx.received_date else ctx.document_date
    arrival = statement_arrival(body, received, ctx.received_confirmed, ctx.document_date)
    late = statement_late(body, arrival.arrived, arrival.confirmed, ctx.recipient_region, named=arrival.named)
    return LATE_STATEMENT_WARNING if late else None


@dataclass(frozen=True)
class PaymentNote:
    """A warning a letter's outgoing payment to-dos carry in their receipt, with the rule it cites.
    ``recurring``: recurring payments carry it too (a rent increase's new rent), not only one-off ones (a
    late statement's back-payment — never the new monthly prepayment)."""

    warning: str
    rule_id: str
    recurring: bool


def payment_note(
    kind: str | None, extraction: DocumentExtraction | None, title: str | None, text: str, ctx: RuleContext
) -> PaymentNote | None:
    """The note a letter's payments carry: a rent increase's new rent is only owed once the person
    agrees (§ 558b Abs. 1 BGB); a late statement's back-payment may not be owed
    (:func:`late_statement_warning`)."""
    if kind == "rent_increase":
        return PaymentNote(RENT_INCREASE_PAYMENT_WARNING, "bgb_558b", recurring=True)
    warning = late_statement_warning(is_statement(kind, extraction), title, text, ctx)
    return PaymentNote(warning, "bgb_556_3", recurring=False) if warning else None


def with_payment_note(
    computed: ComputedDate, item: ExtractedItem | Item, note: PaymentNote | None
) -> ComputedDate:
    """A payment's receipt with its letter's :class:`PaymentNote` and its rule. Only money the person
    pays: never a credit or refund (``direction`` "in"), and a recurring payment only when the note says
    so."""
    receipt = computed.receipt
    if note is None or receipt is None or item.kind != "payment" or item.direction == "in":
        return computed
    if item.recurrence is not None and not note.recurring:
        return computed
    rule_ids = receipt.rule_ids if note.rule_id in receipt.rule_ids else [*receipt.rule_ids, note.rule_id]
    updated = receipt.model_copy(update={"warnings": [*receipt.warnings, note.warning], "rule_ids": rule_ids})
    return replace(computed, receipt=updated)


def remedy_warnings(remedy: Remedy | None) -> list[str]:
    """Warning cards for remedies Ordnung cannot help with (§ 21 "Remedies & letters")."""
    if remedy is None:
        return []
    if remedy.type == "klage":
        return [
            "This decision can only be challenged in court (Klage) — get advice (e.g. a Verbraucherzentrale) in time."
        ]
    if remedy.type == "unclear":
        return [
            "The instructions on how to object are unclear — get advice. If they are missing or wrong, a "
            "one-year period may apply (§ 356 Abs. 2 AO, § 58 Abs. 2 VwGO, § 66 Abs. 2 SGG)."
        ]
    return []


# --------------------------------------------------------------------------------------------------
# Plan (write)
# --------------------------------------------------------------------------------------------------


@dataclass
class PlanResult:
    """The written document and its extracted items."""

    document: Document
    items: list[Item]


def payment_details(payment: PaymentDetails | None, page_text: str = "") -> PaymentDetails | None:
    """Payment details with the IBAN normalised and its checksum result.

    An IBAN whose checksum fails is looked up in the letter's text: when the page prints a valid IBAN
    that is almost the same, the model misread it and the printed one is kept (code reads digits
    exactly; SPEC § 21 grounding).
    """
    if payment is None:
        return None
    if not payment.iban:
        return payment.model_copy(update={"iban": None, "iban_valid": None})
    iban = normalize_iban(payment.iban)
    if not iban_valid(iban):
        iban = iban_from_page(iban, page_text) or iban
    return payment.model_copy(update={"iban": iban, "iban_valid": iban_valid(iban)})


#: Letter facts the person can correct (``PATCH /api/documents/{id}``) → the extraction's field.
CORRECTABLE_FIELDS: dict[str, str] = {
    "title": "title",
    "kind": "kind",
    "area": "area",
    "doc_date": "document_date",
}


def _read_facts(extraction: DocumentExtraction) -> dict[str, Any]:
    """The letter facts as :func:`write_plan` stores them from a reading (its kind as code files it)."""
    doc_date = parse_date(extraction.document_date)
    return {
        "title": extraction.title,
        "kind": letter_kind(extraction),
        "area": extraction.area,
        "doc_date": doc_date.isoformat() if doc_date else None,
    }


#: The activity entry that records a kind the person chose for a letter (``data["kind"]``).
KIND_CHOSEN = "document.kind"


def corrections(
    document: Document, previous: DocumentExtraction | None, *, chosen_kind: str | None = None
) -> dict[str, Any]:
    """The letter facts the person corrected: those that differ from the model's last reading (its
    kind as code files it).

    The kind is a correction only when the person chose it (``chosen_kind``, from the
    :data:`KIND_CHOSEN` activity entry) or when it is none of the kinds code may have filed: not the
    kind code files the reading as, not the model's own kind and not a high-stakes kind (which only code
    or the person's choice assigns). A letter filed by an older Ordnung under the model's kind (a
    Mahnbescheid as ``dunning``) therefore gets its high-stakes kind when it is read again, one an older
    Ordnung filed as a court order that the policy no longer recognises gets the model's kind back, and
    a kind the person picked on the letter's page — even the model's own — is kept.
    """
    if previous is None:
        return {}
    found = {
        name: getattr(document, name)
        for name, value in _read_facts(previous).items()
        if getattr(document, name) != value
    }
    if (
        "kind" in found
        and document.kind != chosen_kind
        and (document.kind == previous.kind or document.kind in HIGH_STAKES_KINDS)
    ):
        del found["kind"]
    return found


def with_corrections(extraction: DocumentExtraction, corrected: dict[str, Any]) -> DocumentExtraction:
    """The reading with the person's corrections applied (what dates, links and the letter use).

    The reading keeps the model's vocabulary: a kind only code assigns stays out of it (see
    :func:`filed_kind`).
    """
    update = {
        CORRECTABLE_FIELDS[name]: value
        for name, value in corrected.items()
        if name != "kind" or value in DOCUMENT_KINDS
    }
    return extraction.model_copy(update=update) if update else extraction


def filed_kind(reading: DocumentExtraction, corrected: dict[str, Any]) -> LetterKind:
    """The kind a letter is filed as: the person's correction, else the kind code reads from it."""
    kind: LetterKind = corrected.get("kind") or letter_kind(reading)
    return kind


def _item_fields(
    verified: VerifiedItem,
    computed: ComputedDate,
    extraction: DocumentExtraction,
    links: LinkResult,
    today: date,
) -> dict[str, Any]:
    item = verified.item
    return {
        "kind": item.kind,
        "title": item.title,
        "action": item.action,
        "consequence": item.consequence,
        "due_date": computed.due_date,
        "due_time": item.date.time,
        "send_by": computed.send_by,
        "date_spec": item.date,
        "computation": computed.receipt,
        "amount": item.amount,
        "currency": item.currency,
        "direction": item.direction,
        "recurrence": item.recurrence,
        "priority": item.priority,
        "area": extraction.area,
        "party_id": links.party.id if links.party else None,
        "case_id": links.case.id if links.case else None,
        "contract_id": links.contract.id if links.contract else None,
        "evidence": [verified.evidence],
        "grounding": verified.evidence.grounding,
        "due_date_source": computed.source,
        "origin": "extracted",
        "location": item.location,
        "filed_on": today.isoformat(),
    }


def _date_key(spec: DateSpec) -> dict[str, Any]:
    """What a DateSpec says about the date, without the wording it was read from."""
    return spec.model_dump(exclude={"text", "legal_basis"})


def _same_obligation(item: Item, verified: VerifiedItem, *, same_amount: bool) -> bool:
    """A stored to-do and a new reading describe the same obligation: same kind, amount and date spec,
    or for a recurring one the same schedule (:func:`~ordnung.recurrence.same_schedule`: the rule and
    first occurrence) with any amount unless ``same_amount`` (reading the letter again corrects a
    misread amount). A recurring to-do the person edited also matches a reading of its rule that gives
    no date (the letter leaves it undated; the person gave it its first occurrence). An undated to-do
    without an amount can't be told apart from another one, so it never matches."""
    new = verified.item
    if (new.date.type == "none" and new.amount is None) or item.kind != new.kind or item.date_spec is None:
        return False
    if item.amount == new.amount and _date_key(item.date_spec) == _date_key(new.date):
        return True
    if same_amount and item.amount != new.amount:
        return False
    if same_schedule(item, new.recurrence, new.date):
        return True
    return item.user_modified and new.date.type == "none" and same_rule(item.recurrence, new.recurrence)


def carry_over(store: Store, doc_id: str, verification: Verification) -> int:
    """Move to-dos the person acted on (status changed or edited) and recurring ones to the new
    reading's slot when it quotes their sentence differently, so "paid" or "snoozed" survives reading
    the letter again and a recurring to-do stays at the occurrence it has reached.

    A recurring to-do matches a reading of its schedule whatever amount it reads, but readings with
    its amount are matched first (two payments of one schedule keep theirs).

    Returns the number of to-dos moved.
    """
    new_keys = {verified.slot_key for verified in verification.items}
    stored = [item for item in store.list_items(doc_id=doc_id) if item.origin == "extracted"]
    taken = {item.slot_key for item in stored}
    acted = [
        item
        for item in stored
        if item.slot_key not in new_keys
        and (item.status != "open" or item.user_modified or item.recurrence is not None)
    ]
    unmatched = [verified for verified in verification.items if verified.slot_key not in taken]
    moved = 0
    for same_amount in (True, False):
        for verified in list(unmatched):
            match = next(
                (item for item in acted if _same_obligation(item, verified, same_amount=same_amount)), None
            )
            if match is not None:
                store.update_item(match.id, slot_key=verified.slot_key)
                acted.remove(match)
                unmatched.remove(verified)
                moved += 1
    return moved


def write_items(
    store: Store,
    doc_id: str,
    verification: Verification,
    computed: Sequence[ComputedDate],
    extraction: DocumentExtraction,
    links: LinkResult,
    *,
    today: date,
    ctx: RuleContext,
    postal_buffer_days: int,
) -> list[Item]:
    """Upsert the document's items by slot (after :func:`carry_over`) and delete its stale extracted
    ones — never those the person acted on. ``today`` is the day the items are filed; ``computed``
    was computed in ``ctx`` with ``postal_buffer_days``.

    A recurring to-do keeps its stored occurrence when it is later than the new reading's (the
    schedule's first occurrence) and the schedule is the same
    (:func:`~ordnung.recurrence.keeps_later_date`): reading the letter again never moves it backwards.
    That occurrence is dated and graded by the new reading (:func:`~ordnung.recurrence.at_occurrence`).
    """
    carry_over(store, doc_id, verification)
    stored = {item.slot_key: item for item in store.list_items(doc_id=doc_id)}
    items = []
    for verified, result in zip(verification.items, computed, strict=True):
        fields = _item_fields(verified, result, extraction, links, today)
        existing = stored.get(verified.slot_key)
        new = verified.item
        if existing is not None and keeps_later_date(existing, new.recurrence, new.date, result.due_date):
            reading = existing.model_copy(update=fields)
            kept = at_occurrence(reading, existing.due_date, ctx, postal_buffer_days=postal_buffer_days)
            fields |= {name: getattr(kept or existing, name) for name in SCHEDULE_FIELDS}
        items.append(store.upsert_item_by_slot(doc_id, verified.slot_key, **fields))
    store.delete_stale_extracted_items(doc_id, [verified.slot_key for verified in verification.items])
    return items


#: Slot of a deadline the law adds to a letter: one per rule (:func:`sync_rule_items`).
RULE_SLOT_PREFIX = "rule:"
#: The rule a receipt cites when it counts from an end date the letter doesn't write.
END_NOT_WRITTEN = "termination_end"


def _rule_item_fields(
    derived: DerivedDeadline,
    receipt: ComputationReceipt,
    *,
    document: Document,
    today: date,
    evidence: list[Evidence],
) -> dict[str, Any]:
    return {
        "kind": "deadline",
        "title": derived.title,
        "action": derived.action,
        "consequence": derived.consequence,
        "due_date": receipt.due_date,
        "send_by": receipt.send_by,
        "date_spec": derived.spec,
        "computation": receipt,
        "priority": derived.priority,
        "area": document.area or "other",
        "party_id": document.party_id,
        "case_id": document.case_id,
        "evidence": evidence,
        # the letter's kind is Claude's reading; the date is the law's (nothing in the letter to quote)
        "grounding": "model_read",
        "due_date_source": "computed" if receipt.due_date else "none",
        "origin": "rule",
        "filed_on": today.isoformat(),
    }


def law_deadlines(
    kind: str | None, extraction: DocumentExtraction | None, ctx: RuleContext
) -> list[DerivedDeadline]:
    """The deadlines the law adds to a letter of ``kind`` (:func:`ordnung.rules.routing.derived_deadlines`)
    with the facts its reading gives: the end a termination announces, the letter's date and whether
    the notice has no notice period (and gives none in the alternative)."""
    return derived_deadlines(
        kind,
        end=ctx.end_date,
        letter_date=ctx.document_date,
        labour_court=ctx.labour_court,
        extraordinary=extraction is not None
        and extraordinary_notice(extraction, ctx.document_date)
        and not alternative_notice(extraction),
    )


def sync_rule_items(
    store: Store,
    document: Document,
    derived: Sequence[DerivedDeadline],
    ctx: RuleContext,
    *,
    today: date,
    postal_buffer_days: int,
    create: bool = True,
    end_evidence: Evidence | None = None,
) -> list[Item]:
    """File the deadlines the law adds to a high-stakes letter as to-dos (``origin="rule"``).

    A deadline is left out when one of the letter's own to-dos was computed under its rule
    (:func:`~ordnung.rules.routing.computed_under`). Dates come straight from the rules engine: there
    is no quote to grade — except the end a termination announces, which the model read: a to-do that
    counts from an end the letter doesn't write (the engine cites ``termination_end``, ``low``) gets the
    termination's sentence (``end_evidence``) as evidence that doesn't state its value, so it is marked
    "Please check" (:func:`needs_check`). Rule to-dos the letter no longer has (its kind was corrected) are deleted
    unless the person acted on them; those the person edited are kept as they are. With ``create``
    false (a recompute after the region, buffer or arrival day changed) only the rule to-dos that still
    exist are updated: one the person deleted stays deleted — only reading the letter or choosing its
    kind files it again. Returns the letter's rule to-dos.
    """
    own = [
        (item.date_spec, item.computation.rule_ids)
        for item in store.list_items(doc_id=document.id)
        if item.origin == "extracted" and item.date_spec is not None and item.computation is not None
    ]
    wanted = [
        entry
        for entry in derived
        if not any(computed_under(spec, rule_ids, entry.rule_id) for spec, rule_ids in own)
    ]
    slots = {RULE_SLOT_PREFIX + entry.rule_id for entry in wanted}
    existing: set[str | None] = set()
    for item in store.list_items(doc_id=document.id):
        if item.origin != "rule":
            continue
        existing.add(item.slot_key)
        if item.slot_key not in slots and item.status == "open" and not item.user_modified:
            store.delete_item(item.id)
    filed = []
    for entry in wanted:
        slot = RULE_SLOT_PREFIX + entry.rule_id
        if not create and slot not in existing:
            continue
        receipt = compute_due(entry.spec, ctx, postal_buffer_days=postal_buffer_days)
        evidence = []
        if END_NOT_WRITTEN in receipt.rule_ids:
            quote = end_evidence or Evidence(doc_id=document.id, quote="", grounding="unverified")
            evidence = [quote.model_copy(update={"value_consistent": False})]
        fields = _rule_item_fields(entry, receipt, document=document, today=today, evidence=evidence)
        filed.append(store.upsert_item_by_slot(document.id, slot, **fields))
    return filed


def activity_message(title: str, items: Sequence[Item], party_name: str | None) -> str:
    """``Read "Tax assessment 2025" · 1 deadline, 1 payment · linked to Finanzamt Musterstadt``."""
    counts = Counter(item.kind for item in items)
    parts = [
        f"{count} {_KIND_NOUNS[kind][0] if count == 1 else _KIND_NOUNS[kind][1]}"
        for kind, count in sorted(counts.items(), key=lambda entry: list(_KIND_NOUNS).index(entry[0]))
    ]
    message = f"Read “{title}” · {', '.join(parts) if parts else 'no dates'}"
    return f"{message} · linked to {party_name}" if party_name else message


def unique(values: Sequence[str]) -> list[str]:
    """``values`` without repeats or empty strings, first occurrence kept."""
    return list(dict.fromkeys(value for value in values if value and value.strip()))


def write_plan(
    store: Store,
    *,
    document: Document,
    extraction: DocumentExtraction,
    verification: Verification,
    computed: Sequence[ComputedDate],
    links: LinkResult,
    warnings: Sequence[str],
    text_mode: Literal["text", "vision"],
    hidden_text: bool,
    full_text: str,
    today: date,
    ctx: RuleContext,
    postal_buffer_days: int,
    model_reading: DocumentExtraction | None = None,
    kind: LetterKind | None = None,
    derived: Sequence[DerivedDeadline] = (),
) -> PlanResult:
    """Write items, document facts and status, re-index search and log the activity entry.

    ``extraction`` is the reading with the person's corrections applied (:func:`with_corrections`);
    ``model_reading`` is the model's own, stored as the letter's extraction (default: ``extraction``)
    so later readings can still tell which facts the person corrected. ``kind`` is the kind the letter
    is filed as (:func:`filed_kind`; default: the reading's) and ``derived`` the deadlines the law adds
    to it (:func:`sync_rule_items`). ``today`` is the person's day; ``computed`` was computed in
    ``ctx`` with ``postal_buffer_days``.
    """
    items = write_items(
        store,
        document.id,
        verification,
        computed,
        extraction,
        links,
        today=today,
        ctx=ctx,
        postal_buffer_days=postal_buffer_days,
    )
    rule_items = sync_rule_items(
        store,
        document.model_copy(
            update={
                "area": extraction.area,
                "party_id": links.party.id if links.party else None,
                "case_id": links.case.id if links.case else None,
            }
        ),
        derived,
        ctx,
        today=today,
        postal_buffer_days=postal_buffer_days,
        end_evidence=verification.change_evidence,
    )
    items = [*items, *rule_items]
    # the stored to-dos decide: one the person confirmed, paid or dismissed was kept and needs no check
    unsure = any(needs_check(item) for item in store.list_items(doc_id=document.id))
    status: DocumentStatus = "needs_review" if unsure else "processed"
    stamp = now_iso()
    doc_date = parse_date(extraction.document_date)
    updated = store.update_document(
        document.id,
        kind=kind or letter_kind(extraction),
        area=extraction.area,
        title=extraction.title,
        summary=extraction.summary,
        explanation=extraction.explanation,
        language=extraction.language,
        doc_date=doc_date.isoformat() if doc_date else None,
        party_id=links.party.id if links.party else None,
        case_id=links.case.id if links.case else None,
        urgency=extraction.urgency,
        text_mode=text_mode,
        key_facts=verification.key_facts,
        references=extraction.references,
        warnings=unique([*extraction.warnings, *warnings]),
        tax_relevant=extraction.tax_relevant,
        tax_note=extraction.tax_note,
        remedy=extraction.remedy,
        payment=payment_details(extraction.payment, full_text),
        hidden_text=hidden_text,
        status=status,
        error=None,
        ai_processed_at=stamp,
        processed_at=stamp,
        extraction=model_reading or extraction,
        text=full_text,
    )
    if any(item.recurrence for item in items):  # in the letter's context, now that it is stored
        roll_forward(store, today, item_context)
        items = [store.get_item(item.id) or item for item in items]
    store.reindex_document(document.id)
    store.log_activity(
        "document.processed",
        activity_message(extraction.title, items, links.party.name if links.party else None),
        ref_type="document",
        ref_id=document.id,
        data={
            "status": status,
            "items": len(items),
            "party_id": links.party.id if links.party else None,
            "case_id": links.case.id if links.case else None,
        },
    )
    return PlanResult(document=updated, items=items)
