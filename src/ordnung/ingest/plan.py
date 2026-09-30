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

Verifying and planning describe what they decided on the ``trace`` span they are given (a step per
quote and per to-do, :mod:`ordnung.trace.facts`); without one they record nothing.
"""

from __future__ import annotations

import hashlib
import re
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
    check_quote,
    day_of_month_consistency,
    grade_reading,
    ground_evidence,
    parse_amounts,
    parse_dates,
    spec_consistency,
    working_day_consistency,
)
from ordnung.models import (
    DOCUMENT_KINDS,
    HIGH_STAKES_KINDS,
    ComputationReceipt,
    Contract,
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
from ordnung.payments import is_collected_or_incoming, pays_on_site
from ordnung.recurrence import (
    SCHEDULE_FIELDS,
    ItemContext,
    at_occurrence,
    first_scheduled,
    keeps_later_date,
    remembered,
    roll_forward,
    rule_day_of_month,
    rule_working_day,
    same_rule,
    same_schedule,
    settle_rents,
    with_rent_due,
)
from ordnung.rules import RuleContext, compute_due, is_private_sender, scope_for_party_kind
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
    is_court,
    is_labour_court,
    is_social_court,
    letter_kind,
    names_statement,
    notice_without_period,
    objection_dated,
    objection_excluded,
)
from ordnung.secretary.scam import iban_from_page, iban_valid, invalid_iban_message, normalize_iban
from ordnung.trace import facts
from ordnung.trace.spans import NO_SPAN, Span

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
        """Whether the item describes a date: fixed or relative, or the working day or day of the month its
        recurrence dates each month by (:func:`~ordnung.recurrence.rule_working_day`,
        :func:`~ordnung.recurrence.rule_day_of_month`, points 8 and 10)."""
        rule = self.item.recurrence
        return (
            self.item.date.type != "none"
            or rule_working_day(rule) is not None
            or rule_day_of_month(rule) is not None
        )

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
    """Why the item's quote doesn't state its DateSpec, amount, working day or day of the month — a date or
    amount written elsewhere in the letter excepted (the same grading when a letter is read and when its
    dates are recomputed).

    A working day (``recurrence.working_day``) counts only when the quote names that ordinal
    (:func:`~ordnung.ingest.verify.working_day_consistency`); otherwise the reason is
    ``WORKING_DAY_NOT_IN_QUOTE``, and as with every reason the item's evidence is not
    ``value_consistent`` (the to-do is "Please check" and never shown as confirmed by the letter) and
    its receipt is one confidence level lower, with the reason's note (:func:`~ordnung.ingest.verify.
    grade_reading`), for every occurrence of its schedule (:func:`~ordnung.ingest.verify.regrade`). The
    working day still dates the to-do (:mod:`ordnung.recurrence`, point 8). A day of the month that dates it
    (``recurrence.day_of_month`` without a working day, point 10) is graded the same way
    (:func:`~ordnung.ingest.verify.day_of_month_consistency`, ``DAY_OF_MONTH_NOT_IN_QUOTE``)."""
    found: list[str] = []
    if item.date.type != "none" or item.amount is not None:
        found = spec_consistency(item.quote, item.date, item.amount)[1]
    working_day = item.recurrence.working_day if item.recurrence is not None else None
    found += working_day_consistency(item.quote, working_day)
    found += day_of_month_consistency(item.quote, rule_day_of_month(item.recurrence))
    return tuple(reason for reason in found if not _stated_in_document(item, reason, pages))


def _verify_item(
    doc_id: str, item: ExtractedItem, key: str, pages: Sequence[PageInput], *, index: int, trace: Span
) -> VerifiedItem:
    with trace.span("verify", "Quote", key=f"item:{key}") as step:
        evidence, check = check_quote(doc_id, item.quote, pages)
        reasons = consistency_reasons(item, pages)
        evidence = evidence.model_copy(update={"value_consistent": not reasons})
        step.set(**facts.quote("item", evidence, check, index=index, reasons=reasons, slot_key=key))
    return VerifiedItem(item=item, evidence=evidence, reasons=reasons, slot_key=key)


def _grounded(
    doc_id: str,
    quote: str,
    pages: Sequence[PageInput],
    *,
    target: facts.QuoteTarget,
    index: int,
    trace: Span,
) -> Evidence:
    with trace.span("verify", "Quote", key=f"{target}:{index}") as step:
        evidence, check = check_quote(doc_id, quote, pages)
        step.set(**facts.quote(target, evidence, check, index=index))
    return evidence


def _optional_evidence(
    doc_id: str, quote: str | None, pages: Sequence[PageInput], *, target: facts.QuoteTarget, trace: Span
) -> Evidence | None:
    if not quote or not quote.strip():
        return None
    return _grounded(doc_id, quote, pages, target=target, index=0, trace=trace)


def verify_extraction(
    doc_id: str, extraction: DocumentExtraction, pages: Sequence[PageInput], *, trace: Span = NO_SPAN
) -> Verification:
    """Ground every quote of ``extraction`` on ``pages`` and collect "please check" warnings.

    ``trace`` gets a ``verify`` step with one step per quote (:func:`ordnung.trace.facts.quote`).
    """
    with trace.span("verify", "Check quotes", key="quotes", stage="verify") as step:
        items = [
            _verify_item(doc_id, item, key, pages, index=index, trace=step)
            for index, (item, key) in enumerate(
                zip(extraction.items, slot_keys(extraction.items), strict=True)
            )
        ]
        verification = Verification(
            items=items,
            key_facts=[
                KeyFact(
                    label=fact.label,
                    value=fact.value,
                    evidence=_grounded(doc_id, fact.quote, pages, target="key_fact", index=index, trace=step),
                )
                for index, fact in enumerate(extraction.key_facts)
            ],
            contract_evidence=[
                _grounded(doc_id, quote, pages, target="contract", index=index, trace=step)
                for index, quote in enumerate(extraction.contract.quotes if extraction.contract else [])
            ],
            change_evidence=_optional_evidence(
                doc_id,
                extraction.change.quote if extraction.change else None,
                pages,
                target="change",
                trace=step,
            ),
            remedy_evidence=_optional_evidence(
                doc_id,
                extraction.remedy.quote if extraction.remedy else None,
                pages,
                target="remedy",
                trace=step,
            ),
        )
        verification.warnings = _verification_warnings(verification)
        grounded = [
            *(verified.evidence for verified in items),
            *(fact.evidence for fact in verification.key_facts if fact.evidence is not None),
            *verification.contract_evidence,
            *(e for e in (verification.change_evidence, verification.remedy_evidence) if e is not None),
        ]
        step.set(
            **facts.verification(
                [evidence.grounding for evidence in grounded],
                sum(verified.needs_check for verified in items),
            )
        )
    return verification


def _verification_warnings(verification: Verification) -> list[str]:
    warnings = []
    unchecked = sum(verified.needs_check for verified in verification.items)
    if unchecked:
        dates = "1 date" if unchecked == 1 else f"{unchecked} dates"
        # no "Please check:" before it: the letter's page shows it under that heading (UI audit R1-backend-7)
        warnings.append(f"{dates.capitalize()} could not be confirmed against the letter's text.")
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
    :func:`ordnung.rules.scope_for_party_kind`); a sender of a private kind (a company, a landlord, a
    bank, an employer …) whose letter shows no administrative act has no deemed delivery at all
    (:func:`ordnung.rules.is_private_sender`: an Einspruch, Widerspruch or Klage counts only with a
    remedy notice naming an administrative route; for a kind a public body may be filed as, or a period
    whose own words name an administrative act, a late arrival never makes the date later than deemed
    delivery would, :func:`ordnung.rules.deadlines.may_be_public`). A received date on the document was
    entered by the person, so it counts as confirmed. ``filed_as`` is the letter's kind (default: the
    reading's, :func:`letter_kind`), which routes the dates of high-stakes letters; a termination's end
    date comes with it, graded against the letter's ``pages`` (:func:`end_date_grounding`; without pages
    it counts as not written). A court's letter is marked as one (and a labour court's), whatever kind it
    was filed as: its dates never use a delivery fiction and are never ``high``. A lease's payments are
    rent (``RuleContext.rent``, :mod:`ordnung.recurrence` point 8).
    """
    sender = extraction.sender
    kind = party.kind if party else (sender.kind if sender else None)
    name = party.name if party else (sender.name if sender else "")
    remedy = extraction.remedy
    remedy_type = remedy.type if remedy else None
    notice = remedy_text(remedy)
    scope = scope_for_party_kind(
        kind,
        name=party.name if party else (sender.name if sender else None),
        remedy_type=remedy_type,
        remedy_text=notice,
    )
    return RuleContext(
        today=today,
        country=country,
        region=party.region if party else None,
        document_date=parse_date(extraction.document_date),
        received_date=parse_date(document.received_date),
        received_confirmed=document.received_date is not None,
        delivery_scope=scope,
        recipient_region=recipient_region,
        private_sender=is_private_sender(kind, scope=scope, remedy_type=remedy_type, remedy_text=notice),
        sender_kind=kind,
        letter_kind=filed_as or letter_kind(extraction),
        end_date=announced_end(extraction),
        end_date_grounding=end_date_grounding(extraction, pages),
        ends_on_arrival=(filed_as or letter_kind(extraction)) == "dismissal"
        and notice_without_period(extraction, parse_date(extraction.document_date)) is not None,
        court=is_court(name, kind),
        labour_court=is_labour_court(name, kind),
        social_court=is_social_court(name, kind),
        rent=(filed_as or letter_kind(extraction)) == "rent_lease",
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
    holidays in the person's country (a to-do added by hand) — either way for this to-do
    (:func:`for_item`: one paid in person, collected or coming in gets no send-by day, and one linked
    to a rent contract belongs to a home's tenancy, ``RuleContext.rent``), and a rent that changes an
    earlier one keeps that one's due day (:func:`rent_context`)."""
    return rent_context(store, item, own_context(store, item, today))


def item_contexts() -> ItemContext:
    """:func:`item_context` for one pass over the ledger (a letter read, a to-do changed, a day's tick): each
    to-do's context, and its own without the due day a rent keeps, worked out once — point 9 of
    :mod:`ordnung.recurrence` compares every rent of a contract with the others
    (:func:`~ordnung.recurrence.remembered`)."""
    own = remembered(own_context)

    def context(store: Store, item: Item, today: date) -> RuleContext:
        return with_rent_due(store, item, own(store, item, today), own)

    return remembered(context)


def rent_context(store: Store, item: Item, ctx: RuleContext) -> RuleContext:
    """``ctx``, the context of ``item``'s dates, with the due day it keeps from the rent before it on its
    rent contract (``RuleContext.rent_due``, :mod:`ordnung.recurrence` point 9; unchanged for any other
    to-do)."""
    return with_rent_due(store, item, ctx, own_context)


def own_context(store: Store, item: Item, today: date) -> RuleContext:
    """:func:`item_context` without the due day a rent keeps from the rent before it (what point 9 of
    :mod:`ordnung.recurrence` compares rents in)."""
    document = store.get_document(item.doc_id) if item.doc_id else None
    found = document_context(store, document, today) if document is not None else None
    contract = store.get_contract(item.contract_id) if item.contract_id else None
    if found is not None and document is not None:
        note = rent_increase_note(document.kind, store.get_extraction(document.id))
        return for_item(found, item, note, contract)
    return for_item(RuleContext(today=today, country=store.get_profile().country), item, None, contract)


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
    """Due date, send-by date and receipt of one item (no receipt for undated items).

    The item's quote — its whole sentence, where the spec's ``text`` holds only the date expression —
    is the period's own words too (``RuleContext.quote``): for a sender filed as private, one naming an
    administrative act keeps a late arrival from moving the date later, as the spec's words do
    (:func:`ordnung.rules.deadlines.may_be_public`); it never brings deemed delivery back.
    """
    spec = verified.item.date
    if spec.type == "none":
        return ComputedDate(receipt=None, due_date=None, send_by=None, source="none")
    ctx = replace(ctx, quote=verified.item.quote)
    receipt = grade_receipt(compute_due(spec, ctx, postal_buffer_days=postal_buffer_days), verified)
    source: DueDateSource = (
        "none" if receipt.due_date is None else ("fixed" if spec.type == "fixed" else "computed")
    )
    return ComputedDate(receipt=receipt, due_date=receipt.due_date, send_by=receipt.send_by, source=source)


def is_statement(kind: str | None, extraction: DocumentExtraction | None, *, chosen: bool = False) -> bool:
    """Whether a letter is an operating-cost statement: filed as one, or — as its dates don't depend on its
    kind — recognised from its reading when it isn't filed as another high-stakes kind or as a reminder
    (:func:`~ordnung.rules.routing.names_statement`: the model names it one, ``operating_costs``, or the
    reading names one; only the statement itself, never a reminder about an old statement's back-payment),
    and the person didn't choose its kind (``chosen``: a letter they filed as a utility bill is one — review
    round 2 of phase 2: the recognition overrode their choice)."""
    if kind == "operating_costs":
        return True
    return (
        not chosen
        and kind not in (*HIGH_STAKES_KINDS, "dunning")
        and extraction is not None
        and names_statement(extraction)
    )


def kind_chosen(store: Store, document: Document) -> bool:
    """Whether the person chose the letter's kind as it is filed (its newest :data:`KIND_CHOSEN` entry)."""
    entry = store.last_activity("document", document.id, [KIND_CHOSEN])
    return entry is not None and entry.data.get("kind") == document.kind


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
    late statement's back-payment — never the new monthly prepayment). ``current``: the rent before the
    increase and ``starts`` the day it takes effect, as read — a payment of the current rent, or one due
    before the increase, is owed as ever and never carries the note (review round 2 of phase 2)."""

    warning: str
    rule_id: str
    recurring: bool
    current: float | None = None
    starts: date | None = None

    def is_current(self, item: ExtractedItem | Item) -> bool:
        """Whether a payment is the rent as it is now, not the increase: the current rent's amount, or a date
        the letter writes before the increase takes effect."""
        amount = item.amount
        if (
            self.current is not None
            and amount is not None
            and round(amount * 100) == round(self.current * 100)
        ):
            return True
        spec = item.date if isinstance(item, ExtractedItem) else item.date_spec
        written = parse_date(spec.date) if spec is not None and spec.type == "fixed" else None
        return self.starts is not None and written is not None and written < self.starts

    def applies(self, item: ExtractedItem | Item) -> bool:
        """Whether a payment the person makes (never a credit) carries the note: a recurring one only when
        the note says so, never the current rent (:meth:`is_current`)."""
        if item.kind != "payment" or item.direction == "in":
            return False
        if item.recurrence is not None and not self.recurring:
            return False
        return not self.is_current(item)


def rent_increase_note(kind: str | None, extraction: DocumentExtraction | None) -> PaymentNote | None:
    """A rent increase's :class:`PaymentNote`: its new rent is only owed once the person agrees (§ 558b Abs.
    1 BGB) — with the current rent and the day the increase takes effect, as read."""
    if kind != "rent_increase":
        return None
    change = extraction.change if extraction is not None else None
    return PaymentNote(
        RENT_INCREASE_PAYMENT_WARNING,
        "bgb_558b",
        recurring=True,
        current=change.old_amount if change is not None else None,
        starts=parse_date(change.effective_date) if change is not None else None,
    )


def _rent_contract(contract: Contract | None) -> bool:
    """Whether a to-do's contract is the tenancy of a home: its payments are rent (§ 556b Abs. 1 BGB)."""
    return contract is not None and contract.category == "rent"


def for_item(
    ctx: RuleContext, item: ExtractedItem | Item, note: PaymentNote | None, contract: Contract | None = None
) -> RuleContext:
    """The context a to-do's date is computed in: a rent increase's current rent (:meth:`PaymentNote.
    is_current`) is owed as ever, so it is never re-dated to the new rent's earliest day (§ 558b Abs. 1 BGB,
    review round 2 of phase 2) — it is computed like a payment on any other letter. A payment made in person
    (:func:`~ordnung.payments.pays_on_site`) gets no bank transfer's send-by day (UI audit R1-backend-8), nor
    does one nobody transfers: a direct debit the sender collects, or money coming in
    (:func:`~ordnung.payments.is_collected_or_incoming`; walkthrough of phase 2). A to-do linked to a rent
    ``contract`` belongs to a home's tenancy, as one on a lease does (``RuleContext.rent``: its payments are
    rent, :mod:`ordnung.recurrence` point 8)."""
    if _rent_contract(contract):
        ctx = replace(ctx, rent=True)
    if pays_on_site(item):
        ctx = replace(ctx, in_person=True)
    if is_collected_or_incoming(item):
        ctx = replace(ctx, collected=True)
    if note is not None and note.rule_id == "bgb_558b" and item.kind == "payment" and note.is_current(item):
        return replace(ctx, letter_kind=None)
    return ctx


#: The summary of the receipt an undated payment gets for its note (it has no date of its own).
UNDATED_NOTE_SUMMARY = "The letter gives no date for this payment."


def payment_note(
    kind: str | None,
    extraction: DocumentExtraction | None,
    title: str | None,
    text: str,
    ctx: RuleContext,
    *,
    chosen: bool = False,
) -> PaymentNote | None:
    """The note a letter's payments carry: a rent increase's new rent is only owed once the person
    agrees (§ 558b Abs. 1 BGB); a late statement's back-payment may not be owed
    (:func:`late_statement_warning`; ``chosen``: the person chose the letter's kind, :func:`is_statement`)."""
    if kind == "rent_increase":
        return rent_increase_note(kind, extraction)
    warning = late_statement_warning(is_statement(kind, extraction, chosen=chosen), title, text, ctx)
    return PaymentNote(warning, "bgb_556_3", recurring=False) if warning else None


def with_payment_note(
    computed: ComputedDate, item: ExtractedItem | Item, note: PaymentNote | None
) -> ComputedDate:
    """A payment's receipt with its letter's :class:`PaymentNote` and its rule, when it applies
    (:meth:`PaymentNote.applies`). A payment without a date gets a receipt for the note alone — the page
    and Ask read the note from the receipt, so an undated new rent is never shown as owed (review round 2
    of phase 2)."""
    if note is None or not note.applies(item):
        return computed
    receipt = computed.receipt or ComputationReceipt(due_date=None, summary=UNDATED_NOTE_SUMMARY)
    return replace(computed, receipt=noted_receipt(receipt, note.warning, note.rule_id))


def noted_receipt(receipt: ComputationReceipt, warning: str, rule_id: str) -> ComputationReceipt:
    """``receipt`` with a payment note and the rule it cites (each once)."""
    rule_ids = receipt.rule_ids if rule_id in receipt.rule_ids else [*receipt.rule_ids, rule_id]
    warnings = receipt.warnings if warning in receipt.warnings else [*receipt.warnings, warning]
    return receipt.model_copy(update={"warnings": warnings, "rule_ids": rule_ids})


#: The payment notes a receipt can carry, with the rule each cites (:func:`payment_note`).
PAYMENT_NOTES: dict[str, str] = {
    RENT_INCREASE_PAYMENT_WARNING: "bgb_558b",
    LATE_STATEMENT_WARNING: "bgb_556_3",
}


def kept_payment_note(
    previous: ComputationReceipt | None, receipt: ComputationReceipt | None
) -> ComputationReceipt | None:
    """A payment's new receipt (a date the person set, or none) with the payment note its previous one
    carried: setting the new rent's date by hand never makes it owed (review round 2 of phase 2)."""
    notes = [warning for warning in (previous.warnings if previous else []) if warning in PAYMENT_NOTES]
    if not notes:
        return receipt
    kept = receipt or ComputationReceipt(due_date=None, summary=UNDATED_NOTE_SUMMARY)
    for warning in notes:
        kept = noted_receipt(kept, warning, PAYMENT_NOTES[warning])
    return kept


def first_dated(
    item: Item,
    ctx: RuleContext,
    *,
    postal_buffer_days: int,
    starts: str | None,
    reasons: Sequence[str] = (),
) -> Item | None:
    """:func:`~ordnung.recurrence.first_scheduled` (a to-do dated by its working day when its letter is read
    or its dates are recomputed) with the payment note its receipt carried (:func:`kept_payment_note`): a
    rent increase's new rent dated so is still only owed once the person agrees (§ 558b Abs. 1 BGB)."""
    first = first_scheduled(item, ctx, postal_buffer_days=postal_buffer_days, starts=starts, reasons=reasons)
    if first is None:
        return None
    return first.model_copy(update={"computation": kept_payment_note(item.computation, first.computation)})


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


#: A sentence about an IBAN's check digits ("does not pass the standard IBAN checksum").
_IBAN_CHECK_CLAIM = re.compile(
    r"\biban\b.*(?:check ?sum|check digits?|prüfsumme|prüfziffer|mod(?:ulo)?[ -]?97)"
    r"|(?:check ?sum|check digits?|prüfsumme|prüfziffer).*\biban\b",
    re.I | re.S,
)
#: Words that make such a sentence a claim that the check fails.
_NEGATIVE = re.compile(
    r"n't\b|\b(?:not|fails?|failed|failing|invalid|wrong|incorrect|ungültig|falsch|nicht)\b", re.I
)
#: Where a warning's sentences end: a full stop, then a capital letter or an opening quote or bracket.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ„“\"(])")


def square_iban_claims(warnings: Sequence[str], payment: PaymentDetails | None) -> list[str]:
    """The model's warnings with its claims about the payment IBAN's check digits squared with Ordnung's
    own check (``payment.iban_valid``, ISO 13616; ADR 0002: code checks digits, the model reads).

    Policy (UI audit R1-backend-7: "does not pass the standard IBAN checksum" was stored for a valid IBAN):
    a sentence that speaks of an IBAN's checksum or check digits is dropped when the check contradicts it —
    it says the check fails and the IBAN passes, or the IBAN fails —; a warning left without sentences is
    dropped. When the IBAN fails, Ordnung says so in its own words, once (:func:`invalid_iban_message`, as
    the payment check does). Without an IBAN there is nothing to check, and the warnings stay as read. The
    web squares warnings stored before this the same way (``squareIbanClaims``).
    """
    if payment is None or not payment.iban or payment.iban_valid is None:
        return list(warnings)
    valid = payment.iban_valid
    kept: list[str] = []
    dropped = False
    for warning in warnings:
        sentences = _SENTENCE_BREAK.split(warning.strip())
        left = [
            s for s in sentences if not (_IBAN_CHECK_CLAIM.search(s) and (not valid or _NEGATIVE.search(s)))
        ]
        dropped = dropped or len(left) < len(sentences)
        if left:
            kept.append(" ".join(left))
    if dropped and not valid:
        kept.append(invalid_iban_message(payment.iban))
    return kept


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
    kind code files the reading as, not the model's own kind and not a high-stakes kind (which only code,
    checking the one the model names, or the person's choice assigns). A letter filed by an older Ordnung
    under the model's kind (a Mahnbescheid as ``dunning``) therefore gets its high-stakes kind when it is
    read again, one an older Ordnung filed as a court order that the policy no longer recognises gets the
    model's kind back, and a kind the person picked on the letter's page — even the model's own — is kept.
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

    The reading keeps the model's vocabulary: a high-stakes kind, which only code or the person's choice
    files, stays out of its ``kind`` (see :func:`filed_kind`).
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
    no date (the letter leaves it undated; the person gave it its first occurrence) — also with a day of
    the month its own rule doesn't have (read before prompt 12 gave one). An undated to-do without an
    amount can't be told apart from another one, so it never matches."""
    new = verified.item
    if (new.date.type == "none" and new.amount is None) or item.kind != new.kind or item.date_spec is None:
        return False
    if item.amount == new.amount and _date_key(item.date_spec) == _date_key(new.date):
        return True
    if same_amount and item.amount != new.amount:
        return False
    if same_schedule(item, new.recurrence, new.date):
        return True
    if not item.user_modified or new.date.type != "none":
        return False
    rule = new.recurrence
    if rule is not None and rule_day_of_month(item.recurrence) is None:
        rule = rule.model_copy(update={"day_of_month": None})
    return same_rule(item.recurrence, rule)


def carry_over(store: Store, doc_id: str, verification: Verification) -> int:
    """Move to-dos the person acted on (status changed or edited) and recurring ones to the new
    reading's slot when it quotes their sentence differently, so "paid" or "snoozed" survives reading
    the letter again and a recurring to-do stays at the occurrence it has reached.

    A recurring to-do matches a reading of its schedule whatever amount it reads, but readings with
    its amount are matched first (two payments of one schedule keep theirs).

    Returns the number of to-dos moved.
    """
    return len(_carry_over(store, doc_id, verification))


def _carry_over(store: Store, doc_id: str, verification: Verification) -> set[str]:
    """:func:`carry_over`, returning the new slots the moved to-dos took."""
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
    moved: set[str] = set()
    for same_amount in (True, False):
        for verified in list(unmatched):
            match = next(
                (item for item in acted if _same_obligation(item, verified, same_amount=same_amount)), None
            )
            if match is not None:
                store.update_item(match.id, slot_key=verified.slot_key)
                acted.remove(match)
                unmatched.remove(verified)
                moved.add(verified.slot_key)
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
    trace: Span = NO_SPAN,
) -> list[Item]:
    """Upsert the document's items by slot (after :func:`carry_over`) and delete its stale extracted
    ones — never those the person acted on. ``today`` is the day the items are filed; ``computed``
    was computed in ``ctx`` with ``postal_buffer_days``.

    A recurring to-do keeps its stored occurrence when it is later than the new reading's (the
    schedule's first occurrence) and the schedule is the same
    (:func:`~ordnung.recurrence.keeps_later_date`): reading the letter again never moves it backwards.
    That occurrence is dated and graded by the new reading (:func:`~ordnung.recurrence.at_occurrence`).
    Any other one whose rule has a working day starts at its schedule's first occurrence, with its
    payment note (:func:`first_dated`, point 8). Each to-do's dates are those of its own context
    (:func:`for_item`, with the letter's contract), and a rent that changes an earlier one on its rent
    contract keeps that one's due day (:func:`rent_context`, point 9).

    ``trace`` gets one step per to-do saying what was done with it and why
    (:func:`ordnung.trace.facts.planned`), and the number of stale to-dos removed.
    """
    moved = _carry_over(store, doc_id, verification)
    stored = {item.slot_key: item for item in store.list_items(doc_id=doc_id)}
    note = rent_increase_note(ctx.letter_kind, extraction)
    items = []
    for index, (verified, result) in enumerate(zip(verification.items, computed, strict=True)):
        with trace.span("plan", "To-do", key=f"item:{verified.slot_key}") as step:
            fields = _item_fields(verified, result, extraction, links, today)
            existing = stored.get(verified.slot_key)
            new = verified.item
            # the reading as the to-do it becomes: a rent keeps the due day of the rent before it (point 9)
            unsaved = {"id": "", "status": "open", "created_at": "", "updated_at": "", **fields}
            becomes = existing.model_copy(update=fields) if existing else Item.model_construct(**unsaved)
            item_ctx = rent_context(store, becomes, for_item(ctx, new, note, links.contract))
            action: facts.PlanAction = "created" if existing is None else "updated"
            if existing is not None and keeps_later_date(
                existing, new.recurrence, new.date, result.due_date, item_ctx
            ):
                reading = existing.model_copy(update=fields)
                kept = at_occurrence(
                    reading,
                    existing.due_date,
                    item_ctx,
                    postal_buffer_days=postal_buffer_days,
                    reasons=verified.reasons,
                )
                fields |= {name: getattr(kept or existing, name) for name in SCHEDULE_FIELDS}
                action = "kept_later_date"
            if existing is not None and existing.user_modified:
                action = "kept_edited"  # upsert_item_by_slot leaves a to-do the person edited as it is
            item = store.upsert_item_by_slot(doc_id, verified.slot_key, **fields)
            if action in ("created", "updated"):
                starts = links.contract.start_date if links.contract else None
                first = first_dated(
                    item,
                    item_ctx,
                    postal_buffer_days=postal_buffer_days,
                    starts=starts,
                    reasons=verified.reasons,
                )
                if first is not None:
                    item = store.update_item(
                        item.id, **{name: getattr(first, name) for name in SCHEDULE_FIELDS}
                    )
            step.set(**facts.planned(action, item, index=index, moved=verified.slot_key in moved))
        items.append(item)
    removed = store.delete_stale_extracted_items(
        doc_id, [verified.slot_key for verified in verification.items]
    )
    trace.set(removed=removed)
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
    with the facts its reading gives: the end a termination announces, the letter's date and arrival (a
    notice too short for its period, :func:`~ordnung.rules.routing.short_notice`), whether the
    hardship objection is out of the question (:func:`~ordnung.rules.routing.objection_excluded`), whether
    the notice is given in the alternative and whether the letter gives an objection date of its own that
    can be computed without the end (:func:`~ordnung.rules.routing.objection_dated`)."""
    return derived_deadlines(
        kind,
        end=ctx.end_date,
        letter_date=ctx.document_date,
        arrived=ctx.received_date if ctx.received_confirmed else None,
        region=ctx.recipient_region,
        labour_court=ctx.labour_court,
        extraordinary=extraction is not None and objection_excluded(extraction, ctx.document_date),
        alternative=extraction is not None and alternative_notice(extraction),
        dated=extraction is not None and any(objection_dated(item.date) for item in extraction.items),
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
    trace: Span = NO_SPAN,
) -> list[Item]:
    """File the deadlines the law adds to a high-stakes letter as to-dos (``origin="rule"``).

    A deadline is left out when one of the letter's own to-dos was computed under its rule
    (:func:`~ordnung.rules.routing.computed_under`) — unless that to-do's date is later than the law's
    (or has none): the law's own date is then filed next to it, never hidden behind a later one (the
    earliest plausible date, SPEC § 21). Dates come straight from the rules engine: there
    is no quote to grade — except the end a termination announces, which the model read: a to-do that
    counts from an end the letter doesn't write (the engine cites ``termination_end``, ``low``) gets the
    termination's sentence (``end_evidence``) as evidence that doesn't state its value, so it is marked
    "Please check" (:func:`needs_check`). Rule to-dos the letter no longer has (its kind was corrected) are deleted
    unless the person acted on them; those the person edited are kept as they are. With ``create``
    false (a recompute after the region, buffer or arrival day changed) only the rule to-dos that still
    exist are updated: one the person deleted stays deleted — only reading the letter or choosing its
    kind files it again. Returns the letter's rule to-dos.

    ``trace`` gets one ``rules`` step per deadline the law adds (:func:`ordnung.trace.facts.law_deadline`:
    filed, or why not) and the number of rule to-dos removed.
    """
    own = [
        (item.date_spec, item.computation.rule_ids, item.due_date)
        for item in store.list_items(doc_id=document.id)
        if item.origin == "extracted" and item.date_spec is not None and item.computation is not None
    ]
    receipts = {
        entry.rule_id: compute_due(entry.spec, ctx, postal_buffer_days=postal_buffer_days)
        for entry in derived
    }
    wanted = [
        entry
        for entry in derived
        if not any(
            computed_under(spec, rule_ids, entry.rule_id)
            and not _later_than_the_law(due, receipts[entry.rule_id].due_date)
            for spec, rule_ids, due in own
        )
    ]
    slots = {RULE_SLOT_PREFIX + entry.rule_id for entry in wanted}
    existing: set[str | None] = set()
    removed = 0
    for item in store.list_items(doc_id=document.id):
        if item.origin != "rule":
            continue
        existing.add(item.slot_key)
        if item.slot_key not in slots and item.status == "open" and not item.user_modified:
            store.delete_item(item.id)
            removed += 1
    filed = []
    for entry in derived:
        slot = RULE_SLOT_PREFIX + entry.rule_id
        receipt = receipts[entry.rule_id]
        with trace.span("rules", "Deadline the law adds", key=f"law:{entry.rule_id}") as step:
            if entry not in wanted or (not create and slot not in existing):
                reason = "covered" if entry not in wanted else "deleted_by_you"
                step.set(**facts.law_deadline(entry.rule_id, receipt, filed=False, reason=reason))
                continue
            evidence = []
            if END_NOT_WRITTEN in receipt.rule_ids:
                quote = end_evidence or Evidence(doc_id=document.id, quote="", grounding="unverified")
                evidence = [quote.model_copy(update={"value_consistent": False})]
            fields = _rule_item_fields(entry, receipt, document=document, today=today, evidence=evidence)
            item = store.upsert_item_by_slot(document.id, slot, **fields)
            step.set(
                **facts.law_deadline(entry.rule_id, receipt, filed=True, reason="filed"), item_id=item.id
            )
        filed.append(item)
    if removed:
        trace.set(rule_removed=removed)
    return filed


def _later_than_the_law(own: str | None, law: str | None) -> bool:
    """Whether a letter's own date for a deadline the law adds is later than the law's (or missing)."""
    return law is not None and (own is None or own > law)


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
    trace: Span = NO_SPAN,
) -> PlanResult:
    """Write items, document facts and status, re-index search and log the activity entry.

    ``extraction`` is the reading with the person's corrections applied (:func:`with_corrections`);
    ``model_reading`` is the model's own, stored as the letter's extraction (default: ``extraction``)
    so later readings can still tell which facts the person corrected. ``kind`` is the kind the letter
    is filed as (:func:`filed_kind`; default: the reading's) and ``derived`` the deadlines the law adds
    to it (:func:`sync_rule_items`). ``today`` is the person's day; ``computed`` was computed in
    ``ctx`` with ``postal_buffer_days``. ``trace`` gets the ``plan`` step (:func:`write_items`,
    :func:`sync_rule_items`) with the status the letter ends with.
    """
    with trace.span("plan", "Plan to-dos", key="plan", stage="plan") as step:
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
            trace=step,
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
            trace=step,
        )
    items = [*items, *rule_items]
    # the stored to-dos decide: one the person confirmed, paid or dismissed was kept and needs no check
    unsure = any(needs_check(item) for item in store.list_items(doc_id=document.id))
    status: DocumentStatus = "needs_review" if unsure else "processed"
    step.set(status=status, needs_check=sum(needs_check(item) for item in items))
    stamp = now_iso()
    doc_date = parse_date(extraction.document_date)
    payment = payment_details(extraction.payment, full_text)
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
        warnings=unique([*square_iban_claims(extraction.warnings, payment), *warnings]),
        tax_relevant=extraction.tax_relevant,
        tax_note=extraction.tax_note,
        remedy=extraction.remedy,
        payment=payment,
        hidden_text=hidden_text,
        status=status,
        error=None,
        ai_processed_at=stamp,
        processed_at=stamp,
        extraction=model_reading or extraction,
        text=full_text,
    )
    if any(item.recurrence for item in items):  # in the letter's context, now that it is stored
        contexts = item_contexts()
        roll_forward(store, today, contexts)
        # a later rent replaces the one it changes, and keeps its due day (ordnung.recurrence, point 9)
        settle_rents(store, today, contexts, contract_ids=[item.contract_id for item in items])
        items = [store.get_item(item.id) or item for item in items]
        step.set(rolled_forward=True)
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
