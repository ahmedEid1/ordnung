"""Deterministic secretary triggers — the ledger turned into "Ideas" (SPEC §9, §21).

Every trigger reads a :class:`Ledger` (one consistent snapshot of the store for one day) and returns
:class:`~ordnung.models.Suggestion` models with ``source="rule"``: refs to real ids, an action named
after what the person does ("Draft cancellation", "Pay", "Check the letter"), a priority and the day
to act by. Dates come from stored items or from the rules engine — never from a model.

Fingerprints are ``rule_id:entity_id:hash(triggering values)``: while the facts stay the same an
Idea keeps its identity (and the person's "dismissed"/"snoozed" choice); when they change, a fresh
Idea replaces it and the old one expires. :func:`run_and_reconcile` persists everything. Nothing in
this module closes, dismisses or marks an obligation — overdue is computed on read (SPEC §21).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ordnung.clock import now_iso
from ordnung.db.store import Store
from ordnung.drafts.proof import (
    PROOF_SOURCE,
    RecordedAnswer,
    channel_label,
    delivery_record_obtainable,
    followup_item_id,
)
from ordnung.drafts.tracking import tracking_info
from ordnung.ids import content_id
from ordnung.ingest.attachments import attached_to, attachment_ids, is_email
from ordnung.ingest.gaps import CHECK_SLOT
from ordnung.ingest.link import attachment_repeats, reminder_covers
from ordnung.models import (
    PAYMENT_DEMAND_KINDS,
    Area,
    CallNote,
    CancellationSent,
    ComputationReceipt,
    Contract,
    ContractComputation,
    Document,
    DocumentExtraction,
    Draft,
    ExtractedChange,
    Item,
    Party,
    Priority,
    Profile,
    Proof,
    Suggestion,
    SuggestionAction,
    SuggestionKind,
    SuggestionRef,
)
from ordnung.payments import is_collected_or_incoming, is_direct_debit
from ordnung.rules import RuleContext, compute_contract, get_rule, price_increase_window
from ordnung.rules.deadlines import POSTAL_BUFFER_DAYS, sending_time_passed
from ordnung.rules.explain import fmt_date

try:  # the scam checks are optional: the triggers work without them
    from ordnung.secretary import scam as _scam
except ImportError:  # pragma: no cover - only while the module is absent
    _scam = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

#: Item kinds that can be overdue (appointments and milestones simply pass; expiries have their own rule).
OVERDUE_KINDS = frozenset({"deadline", "payment", "task"})
#: Item kinds reported by ``deadline_soon`` (expiries are handled by ``expiry_soon``).
SOON_KINDS = frozenset({"deadline", "payment", "task", "appointment", "reminder", "milestone"})
CANCEL_WINDOW_DAYS = 60
IDENTITY_WINDOW_DAYS = 180
PERMIT_WINDOW_DAYS = 90
PASSPORT_MARGIN_DAYS = 180
PASSPORT_CHECK_HORIZON_DAYS = 365
TAX_SEASON_LAST_MONTH = 7
FOLLOWUP_LATE_DAYS = 14
CALENDAR_META_KEY = "last_calendar_export_at"
#: calendar sync's connection record (:data:`ordnung.calendar.caldav.STATE_KEY`)
CALENDAR_SYNC_META_KEY = "calendar_sync"
STUDENT_PERMIT_RULE = "student_permit_info"

_DEFAULT_WINDOWS = {"deadline": 14, "payment": 7, "appointment": 2, "task": 3, "reminder": 0, "milestone": 7}
_DEFAULT_EXPIRY_WINDOW = 90
_PRIORITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "normal": 2, "low": 3}
_PRICE_RULES = ("enwg_41_5", "stromgvv_5_3", "tkg_57", "vvg_40", "sgbv_175_4_zb")
_INTERVAL_PER_YEAR = {"monthly": 12, "quarterly": 4, "yearly": 1}

_PERMIT_WORDS = (
    "aufenthalt",
    "residence permit",
    "residence title",
    "fiktionsbescheinigung",
    "visa",
    "visum",
    "blue card",
    "blaue karte",
)
_IDENTITY_WORDS = ("passport", "reisepass", "personalausweis", "identity card", "id card", "ausweis")
_SCAM_WORDS = (
    "scam",
    "phish",
    "fraud",
    "betrug",
    "suspicious",
    "verdächtig",
    "fake",
    "gefälscht",
    "impersonat",
    "mismatch",
    "instructions addressed",
    "embedded instruction",
    "prompt injection",
    "hidden text",
)
_PERMIT_LINKS = (
    "https://www.gesetze-im-internet.de/aufenthg_2004/__16b.html",
    "https://www.studierendenwerke.de",
)


# --------------------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------------------


def parse_day(value: str | None) -> date | None:
    """``YYYY-MM-DD`` (or an ISO timestamp) → date; ``None`` for missing or malformed values."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_timestamp(value: str | None) -> datetime | None:
    """ISO-8601 timestamp (``Z`` allowed) → aware datetime; ``None`` for missing or malformed values."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def day_label(day: date, today: date) -> str:
    """``Wed 30 Sep`` (the year only when it differs from ``today``'s)."""
    return fmt_date(day, year=day.year != today.year)


def in_days(days: int) -> str:
    """Countdown wording: ``today`` / ``tomorrow`` / ``in 5 days`` / ``yesterday`` / ``3 days ago``."""
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days == -1:
        return "yesterday"
    return f"in {days} days" if days > 0 else f"{-days} days ago"


def eur(amount: float) -> str:
    """``€84`` / ``€94.99`` / ``€1,234.50``."""
    if float(amount).is_integer():
        return f"€{amount:,.0f}"
    return f"€{amount:,.2f}"


def money(amount: float, currency: str | None) -> str:
    """:func:`eur` for euros (or no currency given), ``50.00 USD`` for another currency."""
    code = (currency or "EUR").upper()
    return eur(amount) if code == "EUR" else f"{amount:,.2f} {code}"


def priority_rank(priority: str) -> int:
    """Sort key for priorities (critical first)."""
    return _PRIORITY_RANK.get(priority, len(_PRIORITY_RANK))


def fingerprint(rule_id: str, entity_id: str, *values: object) -> str:
    """``rule_id:entity_id:<10 hex chars of the triggering values>``."""
    raw = json.dumps(values, default=str, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"{rule_id}:{entity_id}:{digest}"


_GERMAN_WORDS = re.compile(
    r"\b(der|die|das|und|nicht|wir|Sie|Ihr|Ihre|ist|wird|werden|bei|mit|zu|auf|dem|den|des|ein|eine|für|oder|von|bis|zum|zur|im|am|sich|bitte)\b"
)
_ENGLISH_WORDS = re.compile(r"\b(the|and|you|your|to|of|is|will|be|for|by|if|it|this|with)\b", re.I)


def english(text: str | None) -> str | None:
    """``text`` unless it is a German sentence copied from the letter (Ideas are written in English)."""
    if not text:
        return None
    german = len(_GERMAN_WORDS.findall(text)) + (1 if re.search(r"[äöüß]", text, re.I) else 0)
    return None if german >= 2 and german > len(_ENGLISH_WORDS.findall(text)) else text


def _sentences(*parts: str | None) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


#: A reading's own verdict at the end of a title: "… (Likely Scam)", "… [possible scam]".
_SCAM_VERDICT = re.compile(r"\s*[(\[][^()\[\]]*\b(?:scam|fraud|betrug|phishing)\b[^()\[\]]*[)\]]\s*$", re.I)
_STRAIGHT_QUOTED = re.compile(r'"([^"\n]*)"')


def _letter_title(title: str) -> str:
    """A letter's title inside an Idea's: without the reading's own scam verdict (the Idea says it) and
    with the app's typographic quotes."""
    return _STRAIGHT_QUOTED.sub("“\\1”", _SCAM_VERDICT.sub("", title)).strip() or title


def _ref(type_: str, id_: str) -> SuggestionRef:
    return SuggestionRef.model_validate({"type": type_, "id": id_})


def _open(target_type: str, target_id: str, label: str) -> SuggestionAction:
    return SuggestionAction(type="open", target_type=target_type, target_id=target_id, label=label)


def _draft(kind: str, target_type: str, target_id: str, label: str) -> SuggestionAction:
    return SuggestionAction.model_validate(
        {
            "type": "draft",
            "draft_kind": kind,
            "target_type": target_type,
            "target_id": target_id,
            "label": label,
        }
    )


@dataclass(frozen=True)
class IdeaText:
    """The words of an Idea."""

    title: str
    body: str
    rationale: str | None = None


def make_idea(
    rule_id: str,
    entity_id: str,
    values: Iterable[object],
    text: IdeaText,
    *,
    kind: SuggestionKind,
    priority: Priority,
    refs: list[SuggestionRef],
    action: SuggestionAction,
    due_date: date | None,
) -> Suggestion:
    """A rule Idea with its fingerprint and deterministic id (``content_id("sug", fingerprint)``)."""
    fp = fingerprint(rule_id, entity_id, *values)
    now = now_iso()
    return Suggestion(
        id=content_id("sug", fp),
        kind=kind,
        title=text.title,
        body=text.body,
        rationale=text.rationale,
        priority=priority,
        fingerprint=fp,
        refs=list({(ref.type, ref.id): ref for ref in refs}.values()),
        action=action,
        source="rule",
        rule_id=rule_id,
        due_date=due_date.isoformat() if due_date else None,
        created_at=now,
        updated_at=now,
    )


# --------------------------------------------------------------------------------------------------
# item & contract facts shared by triggers, views and the brief
# --------------------------------------------------------------------------------------------------


def is_active(item: Item, today: date) -> bool:
    """Open, or snoozed until a day that has come."""
    if item.status == "open":
        return True
    wake = parse_day(item.snoozed_until)
    return item.status == "snoozed" and wake is not None and wake <= today


def action_day(item: Item) -> date | None:
    """The day to act: ``send_by`` when it comes first, else the due date."""
    due, send = parse_day(item.due_date), parse_day(item.send_by)
    if send is not None and (due is None or send <= due):
        return send
    return due


def paid_at_appointment(item: Item, items: Iterable[Item]) -> bool:
    """Whether a payment is made in person at an appointment: it has a clock time, and its letter sets an
    appointment on the same day (``items``: the ledger's). Its send-by date is a bank transfer's
    (§ 675s BGB), which means nothing there: it is paid on the day, not transferred ahead."""
    if item.kind != "payment" or not item.due_time or item.doc_id is None:
        return False
    return any(
        other.kind == "appointment" and other.doc_id == item.doc_id and other.due_date == item.due_date
        for other in items
    )


UNCONFIRMED_REASONS = ("mismatch", "unverified", "model_read")
"""Why a value is not confirmed against its letter (:func:`unconfirmed_reason`)."""


def unconfirmed_reason(item: Item) -> str | None:
    """Why an item's date or amount is not confirmed against its letter: ``mismatch`` (its quote does
    not state the value), ``unverified`` (not found in the letter) or ``model_read`` (read by AI from a
    photo) — ``None`` once the person confirmed it (grounding ``user``) or when the letter confirms it."""
    if item.grounding == "user":
        return None
    if any(not evidence.value_consistent for evidence in item.evidence):
        return "mismatch"
    return item.grounding if item.grounding in UNCONFIRMED_REASONS else None


#: An item whose date was already this many days in the past when its letter was read is history
#: (e.g. the first meter reading in an old contract confirmation), not an overdue obligation.
HISTORICAL_GRACE_DAYS = 14


def was_history_when_filed(item: Item) -> bool:
    """The item's date lay well before the day Ordnung read the letter (backfilled archive)."""
    due, filed = parse_day(item.due_date), parse_day(item.filed_on)
    return due is not None and filed is not None and (filed - due).days > HISTORICAL_GRACE_DAYS


def is_overdue(item: Item, today: date) -> bool:
    """Computed on read: an active deadline/payment/task whose due date has passed — unless it was
    already history when the letter was filed, it repeats (a schedule shows its next occurrence and
    is never overdue, see :mod:`ordnung.recurrence`), or it is money coming in: the person doesn't owe it
    (walkthrough of phase 2: a salary transfer showed as "Overdue")."""
    due = parse_day(item.due_date)
    return (
        item.kind in OVERDUE_KINDS
        and not (item.kind == "payment" and item.direction == "in")
        and item.recurrence is None
        and due is not None
        and due < today
        and is_active(item, today)
        and not was_history_when_filed(item)
    )


def postal_buffer(profile: Profile) -> int:
    """Business days a letter needs: the person's setting, never less than the §21 default."""
    return max(profile.postal_buffer_days, POSTAL_BUFFER_DAYS)


def contract_computation(
    contract: Contract, party: Party | None, today: date, profile: Profile
) -> ContractComputation:
    """Fresh cancellation dates for ``contract`` as of ``today`` (regional holidays of the party's Land)."""
    ctx = RuleContext(today=today, country=profile.country, region=party.region if party else None)
    terms = contract.terms(party.kind if party else None)
    return compute_contract(terms, ctx, postal_buffer_days=postal_buffer(profile))


def is_decision(computation: ContractComputation) -> bool:
    """A real renewal decision: a cancellation deadline guarding a term that would otherwise continue.

    Rolling deadlines (rent, employment, monthly exits) have no ``next_renewal`` and are no decision.
    """
    return bool(computation.cancel_by and computation.send_by and computation.next_renewal)


#: Contracts for the flat: its lease, energy, phone and internet. Never the residence-permit area.
_HOME_CATEGORIES = frozenset({"rent", "energy", "gas", "internet", "mobile"})


def contract_area(contract: Contract) -> Area:
    """The life area of a contract (its own, or derived from its category). "residence" is the
    residence-permit area: a lease or an energy, phone or internet contract read under it is "home"."""
    if contract.area == "residence" and contract.category in _HOME_CATEGORIES:
        return "home"
    if contract.area != "other":
        return contract.area
    by_category: dict[str, Area] = {
        "mobile": "home",
        "internet": "home",
        "energy": "home",
        "gas": "home",
        "rent": "home",
        "streaming": "leisure",
        "gym": "leisure",
        "membership": "leisure",
        "insurance": "insurance",
        "employment": "work",
        "transport": "mobility",
        "bank": "money",
    }
    return by_category.get(contract.category, "other")


def expiry_class(item: Item, doc: Document | None) -> str:
    """``permit`` (residence title), ``identity`` (passport/ID card) or ``other``."""
    title = item.title.casefold()
    if any(word in title for word in _IDENTITY_WORDS):
        return "identity"
    if any(word in title for word in _PERMIT_WORDS):
        return "permit"
    if doc is not None and doc.kind == "residence_permit":
        return "permit"
    if doc is not None and doc.kind == "identity_document":
        return "identity"
    return "other"


@dataclass(frozen=True)
class PriceIncreaseWindow:
    """A statutory special cancellation window a price increase opened
    (:meth:`Ledger.price_increase_windows`): the letter, the contract it belongs to, the letter's reading,
    the day the new price applies, and the rules engine's receipt, whose ``due_date`` (``due``) is the last
    day a cancellation may arrive."""

    letter: Document
    contract: Contract
    change: ExtractedChange
    effective: date
    due: date
    receipt: ComputationReceipt


class Ledger:
    """A read-only snapshot of the store as of ``today`` (loaded once per trigger run or view)."""

    def __init__(self, store: Store, today: date) -> None:
        self.store = store
        self.today = today
        self.profile = store.get_profile()
        # proof files belong to their letter (``drafts.proof``): they are no letters of the ledger
        self.documents: dict[str, Document] = {
            doc.id: doc for doc in store.list_documents(exclude_source=PROOF_SOURCE)
        }
        self.items: list[Item] = store.list_items()
        self.contracts: list[Contract] = store.list_contracts()
        self.parties: dict[str, Party] = {party.id: party for party in store.list_parties()}
        self._computations: dict[str, ContractComputation] = {}
        self._extractions: dict[str, DocumentExtraction | None] = {}
        self._sent_drafts: list[Draft] | None = None
        self._scam_reasons: dict[str, list[str]] = {}
        self._covered: dict[str, Document] | None = None
        self._attached: dict[str, Document] | None = None
        self._attachments: dict[str, list[Document]] | None = None
        self._proofs: dict[str, list[Proof]] | None = None
        self._replies: dict[str, Document | None] = {}
        self._call_notes: list[CallNote] | None = None
        self._price_windows: list[PriceIncreaseWindow] | None = None

    def party_name(self, party_id: str | None) -> str | None:
        """Display name of a party (``None`` if unknown)."""
        party = self.parties.get(party_id) if party_id else None
        return party.name if party else None

    def document(self, doc_id: str | None) -> Document | None:
        """A live (non-trashed) document."""
        return self.documents.get(doc_id) if doc_id else None

    def active_items(self) -> list[Item]:
        """Open (or woken-up snoozed) items."""
        return [item for item in self.items if is_active(item, self.today)]

    def actionable_items(self) -> list[Item]:
        """Active items that are safe to present as something to do (none :meth:`is_set_aside`)."""
        return [item for item in self.active_items() if not self.is_set_aside(item)]

    def is_set_aside(self, item: Item) -> bool:
        """An item that is never presented as something to do, whatever its status — on Today, in the
        weekly session, the calendar and its sync, the money figures: one of a letter with scam signs,
        an invoice payment a later payment reminder took over (the reminder is the one to act on), or an
        e-mail's payment its attached bill repeats (the bill is the one to act on, or the reminder that
        took the bill over; it stays set aside after the bill is paid, so nothing asks for the money
        twice)."""
        return (
            self.is_suspicious_item(item)
            or self.is_superseded_by_reminder(item)
            or self.is_covered_by_attachment(item)
        )

    def covering_reminders(self) -> dict[str, Document]:
        """Letter id → the live payment reminder (Mahnung) that took over its payments (cached).

        Worked out on read: only reminders that are not in the trash and show no scam signs count,
        whichever of the letters was read first.
        """
        if self._covered is None:
            reminders = [
                doc
                for doc in self.documents.values()
                if doc.kind in PAYMENT_DEMAND_KINDS and not self.scam_reasons(doc)
            ]
            self._covered = {
                doc.id: reminder
                for reminder in sorted(reminders, key=lambda d: (d.doc_date or "", d.created_at, d.id))
                for doc in self.documents.values()
                if reminder_covers(reminder, doc)
            }
        return self._covered

    def is_superseded_by_reminder(self, item: Item) -> bool:
        """An invoice payment whose payment reminder (Mahnung) arrived: act on the reminder instead.
        Never a recurring one: a reminder about arrears does not cover the payments still to come."""
        return (
            item.kind == "payment"
            and item.recurrence is None
            and item.doc_id is not None
            and item.doc_id in self.covering_reminders()
        )

    def attachments_of(self, email: Document) -> list[Document]:
        """The live letters without scam signs that came attached to ``email``: those it added
        (``source="email:<id>"``) and those Ordnung already had when it came (recorded ``known``).
        Worked out once per snapshot, for every e-mail."""
        if self._attachments is None:
            self._attachments = {}
            for doc in sorted(self.documents.values(), key=lambda d: (d.created_at, d.id)):
                parent = attached_to(doc)
                if parent is not None:
                    self._attachments.setdefault(parent, []).append(doc)
            for email_id, doc_ids in attachment_ids(self.store).items():
                listed = self._attachments.setdefault(email_id, [])
                seen = {doc.id for doc in listed}
                for doc_id in doc_ids:
                    known = self.documents.get(doc_id)
                    if known is not None and known.id not in seen and known.id != email_id:
                        listed.append(known)
                        seen.add(known.id)
        return [doc for doc in self._attachments.get(email.id, []) if not self.scam_reasons(doc)]

    def covering_attachments(self) -> dict[str, Document]:
        """Payment to-do id of an e-mail → the attachment of that e-mail that asks for the same payment
        (cached; :func:`~ordnung.ingest.link.attachment_repeats`).

        Worked out on read: only attachments that are not in the trash and show no scam signs count
        (:meth:`attachments_of`), whichever of the letters was read first. An attachment's payments the
        e-mail itself took over as a payment reminder don't count: the one to act on must stay. So a
        reminder e-mail with its invoice attached keeps its own to-do (it takes the invoice's over,
        :meth:`covering_reminders`), and the two never set each other aside. A bill another reminder took
        over still counts, so the e-mail that repeats it stays set aside and that reminder is the one
        payment to act on.
        """
        if self._attached is None:
            covering = self.covering_reminders()
            items_of: dict[str, list[Item]] = {}
            for item in self.items:
                if item.doc_id and item.kind == "payment":
                    items_of.setdefault(item.doc_id, []).append(item)
            self._attached = {}
            for item in self.items:
                email = self.documents.get(item.doc_id or "")
                if email is None or item.kind != "payment" or not is_email(email):
                    continue
                for attachment in self.attachments_of(email):
                    payments = items_of.get(attachment.id, [])
                    taker = covering.get(attachment.id)
                    if taker is not None and taker.id == email.id:
                        payments = [p for p in payments if not self.is_superseded_by_reminder(p)]
                    if attachment_repeats(email, item, attachment, payments):
                        self._attached[item.id] = attachment
                        break
        return self._attached

    def is_covered_by_attachment(self, item: Item) -> bool:
        """An e-mail's payment its attached bill asks for too: act on the bill instead."""
        return item.kind == "payment" and item.id in self.covering_attachments()

    def active_contracts(self) -> list[Contract]:
        """Contracts still running."""
        return [contract for contract in self.contracts if contract.status == "active"]

    def computation(self, contract: Contract) -> ContractComputation:
        """Fresh contract dates (cached per contract for this snapshot)."""
        if contract.id not in self._computations:
            party = self.parties.get(contract.party_id) if contract.party_id else None
            self._computations[contract.id] = contract_computation(contract, party, self.today, self.profile)
        return self._computations[contract.id]

    def extraction(self, doc_id: str) -> DocumentExtraction | None:
        """The stored model extraction of a document (cached)."""
        if doc_id not in self._extractions:
            self._extractions[doc_id] = self.store.get_extraction(doc_id)
        return self._extractions[doc_id]

    def sent_drafts(self) -> list[Draft]:
        """Letters marked as sent, newest first."""
        if self._sent_drafts is None:
            self._sent_drafts = self.store.list_drafts(status="sent")
        return self._sent_drafts

    def decided_contracts(self) -> set[str]:
        """Active contracts whose end is decided: a letter confirms their cancellation
        (:meth:`pending_confirmations`), or the person marked their own cancellation as sent
        (:func:`cancellations_sent`). Neither is a decision to make any more — no "decide by", no
        cancellation Idea, no send-by date in the calendar (walkthrough of phase 2)."""
        return set(self.pending_confirmations()) | set(cancellations_sent(self.sent_drafts()))

    def proofs_of(self, draft_id: str) -> list[Proof]:
        """The proofs recorded for a sent letter (cached; proofs whose file is in the trash are left out)."""
        if self._proofs is None:
            self._proofs = {}
            for proof in self.store.list_proofs():
                self._proofs.setdefault(proof.draft_id, []).append(proof)
        return self._proofs.get(draft_id, [])

    def call_notes(self) -> list[CallNote]:
        """Every call note, newest call first (cached)."""
        if self._call_notes is None:
            self._call_notes = self.store.list_call_notes()
        return self._call_notes

    def followup_item(self, draft: Draft) -> Item | None:
        """The follow-up to-do created when the letter was marked as sent (``None`` once deleted)."""
        wanted = followup_item_id(draft.id)
        return next((item for item in self.items if item.id == wanted), None)

    def letter_after(
        self, case_id: str | None, since: date, *, exclude: str | None = None, contract_id: str | None = None
    ) -> Document | None:
        """The earliest live incoming letter without scam signs, other than ``exclude``, dated (else
        received, else added) on or after ``since``, that is in thread ``case_id`` — or, when
        ``contract_id`` is given, confirms the cancellation of that contract."""
        found: list[tuple[str, str, Document]] = []
        for doc in self.documents.values():
            day = doc.doc_date or doc.received_date or doc.created_at[:10]
            if doc.id == exclude or doc.direction != "incoming" or (parse_day(day) or date.min) < since:
                continue
            threaded = case_id is not None and doc.case_id == case_id
            if not (threaded or (contract_id is not None and self._confirms(doc, contract_id))):
                continue
            if not self.scam_reasons(doc):
                found.append((day, doc.created_at, doc))
        return min(found, key=lambda entry: (entry[0], entry[1], entry[2].id))[2] if found else None

    def _confirms(self, doc: Document, contract_id: str) -> bool:
        extraction = self.extraction(doc.id)
        change = extraction.change if extraction else None
        confirms = doc.kind == "cancellation_confirmation" or (
            change is not None and change.type == "cancellation_confirmation"
        )
        contract = self.linked_contract(doc) if confirms else None
        return contract is not None and contract.id == contract_id

    def reply_to(self, draft: Draft) -> Document | None:
        """The letter that *may* have answered a sent letter (cached), or ``None``.

        Written policy: the earliest live incoming letter without scam signs, other than the letter it
        answered, dated (else received, else added) on or after the day it was sent, that is in the same
        thread (:mod:`ordnung.ingest.link` threads letters by reference), or — for a cancellation of a
        contract — confirms the cancellation of that contract. Nothing is closed because of it (ADR 0006):
        the waiting entry and the follow-up Idea say which letter it was, and the person checks it.
        Limit: any later letter of the thread counts (a new tax assessment under the same tax number, a
        monthly invoice); so it is only a *possible* answer — never proof of arrival, never written
        into the Nachweis. What counts as an answer is :meth:`answer_of`.
        """
        if draft.id not in self._replies:
            sent = parse_day(draft.sent_at) if draft.status == "sent" else None
            contract = draft.contract_id if draft.kind == "cancellation" else None
            self._replies[draft.id] = (
                self.letter_after(draft.case_id, sent, exclude=draft.doc_id, contract_id=contract)
                if sent is not None
                else None
            )
        return self._replies[draft.id]

    def answer_of(self, draft: Draft) -> RecordedAnswer | None:
        """The *confirmed* answer to a sent letter (``drafts.proof`` policy 3), or ``None``: the person's
        word that it was answered (with the letter they named, if it is still here), else — for a
        cancellation of a contract — a confirmation of that contract's cancellation that arrived after
        it was sent. A letter that is only in the same thread is no confirmed answer (:meth:`reply_to`)."""
        if draft.status != "sent":
            return None
        if draft.answered_on:
            named = self.document(draft.answer_doc_id)
            if named is not None:
                return RecordedAnswer(None, named, "letter")
            return RecordedAnswer(draft.answered_on[:10], None, "noted")
        sent = parse_day(draft.sent_at)
        if draft.kind != "cancellation" or not draft.contract_id or sent is None:
            return None
        confirmation = self.letter_after(None, sent, exclude=draft.doc_id, contract_id=draft.contract_id)
        return RecordedAnswer(None, confirmation, "confirmation") if confirmation is not None else None

    def is_dunning_item(self, item: Item) -> bool:
        """Items of a payment reminder are reported by ``dunning_escalation`` only."""
        doc = self.document(item.doc_id)
        return doc is not None and doc.kind == "dunning"

    def scam_reasons(self, doc: Document) -> list[str]:
        """Scam warning signs of an incoming letter (cached; empty for outgoing letters and notes)."""
        if doc.id not in self._scam_reasons:
            party = self.parties.get(doc.party_id) if doc.party_id else None
            found = _scam_reasons(self.store, doc, party) if doc.direction == "incoming" else []
            self._scam_reasons[doc.id] = found
        return self._scam_reasons[doc.id]

    def scam_signs(self, doc: Document) -> list[str]:
        """The warning signs a letter with scam signs shows — on its page and in its Idea, one list and one
        count (:func:`scam_signs`); empty for a letter without scam signs."""
        reasons = self.scam_reasons(doc)
        return scam_signs(doc, reasons) if reasons else []

    def is_suspicious_item(self, item: Item) -> bool:
        """Items of a letter with scam signs are never suggested as something to pay or do."""
        doc = self.document(item.doc_id)
        return doc is not None and bool(self.scam_reasons(doc))

    def pending_confirmations(self) -> dict[str, tuple[Document, date | None]]:
        """Active contracts with a cancellation confirmation: contract id → (letter, effective day)."""
        found: dict[str, tuple[Document, date | None]] = {}
        for doc in sorted(self.documents.values(), key=lambda d: (d.doc_date or "", d.id)):
            extraction = self.extraction(doc.id)
            change = extraction.change if extraction else None
            confirms = doc.kind == "cancellation_confirmation" or (
                change is not None and change.type == "cancellation_confirmation"
            )
            contract = self.linked_contract(doc) if confirms else None
            if contract is not None and contract.status == "active":
                effective = parse_day(change.effective_date if change else None) or parse_day(
                    contract.end_date
                )
                found[contract.id] = (doc, effective)
        return found

    def price_increase_windows(self) -> list[PriceIncreaseWindow]:
        """The statutory special cancellation windows still open after a price increase (§ 41 Abs. 5 EnWG,
        § 57 TKG, § 40 VVG, § 175 Abs. 4 SGB V), one per letter, in the ledger's letter order (cached).

        A letter opens one when its reading is a price increase with an effective date and it belongs to
        an active contract (:meth:`linked_contract`); the rules engine computes the window
        (:func:`~ordnung.rules.price_increase_window`, with the letter's own date as the earliest possible
        arrival), and it counts while its last day has not passed. A health insurer's opens only with a
        higher Zusatzbeitrag stated as numbers (:func:`zusatzbeitrag_raised`). The ``price_increase_right``
        Idea and Ask's record read these same windows, so Ask never states a right the Idea withholds.
        """
        if self._price_windows is None:
            self._price_windows = []
            for doc in self.documents.values():
                extraction = self.extraction(doc.id)
                change = extraction.change if extraction else None
                effective = parse_day(change.effective_date) if change else None
                if change is None or change.type != "price_increase" or effective is None:
                    continue
                contract = self.linked_contract(doc)
                if contract is None or contract.status != "active":
                    continue
                party = self.parties.get(contract.party_id or "")
                ctx = RuleContext(
                    today=self.today,
                    country=self.profile.country,
                    region=party.region if party else None,
                    document_date=parse_day(doc.doc_date),
                )
                # notified_on=None: the letter's own date is the earliest possible arrival (safety policy)
                receipt = price_increase_window(
                    effective,
                    contract.category,
                    None,
                    ctx,
                    is_basic_supply=contract.is_basic_supply,
                    party_kind=party.kind if party else None,
                    postal_buffer_days=postal_buffer(self.profile),
                )
                due = parse_day(receipt.due_date)
                if due is None or due < self.today:
                    continue
                if "sgbv_175_4_zb" in receipt.rule_ids and not zusatzbeitrag_raised(change):
                    continue  # no higher Zusatzbeitrag stated as numbers: no special right claimed
                self._price_windows.append(
                    PriceIncreaseWindow(doc, contract, change, effective, due, receipt)
                )
        return self._price_windows

    def reminder_window(self, kind: str) -> int:
        """How many days ahead an item of ``kind`` becomes an Idea (the longest reminder)."""
        days = self.profile.reminder_days.get(kind)
        if days:
            return max(days)
        return _DEFAULT_WINDOWS.get(kind, _DEFAULT_EXPIRY_WINDOW if kind == "expiry" else 0)

    def linked_contract(self, doc: Document) -> Contract | None:
        """The contract a letter belongs to: via its items, the contract's evidence, a customer number
        in the letter's references, or the party's only active contract."""
        by_id = {contract.id: contract for contract in self.contracts}
        for item in self.items:
            if item.doc_id == doc.id and item.contract_id in by_id:
                return by_id[item.contract_id]
        for contract in self.contracts:
            if contract.source_doc_id == doc.id or any(ev.doc_id == doc.id for ev in contract.evidence):
                return contract
        if doc.party_id is None:
            return None
        for reference in doc.references:
            found = self.store.find_contract(doc.party_id, reference.value)
            if found is not None:
                return by_id.get(found.id, found)
        running = [c for c in self.active_contracts() if c.party_id == doc.party_id]
        return running[0] if len(running) == 1 else None


# --------------------------------------------------------------------------------------------------
# item actions
# --------------------------------------------------------------------------------------------------


def item_action(ledger: Ledger, item: Item) -> SuggestionAction:
    """The one verb for an item: Pay · Draft objection · Draft cancellation · Check the letter."""
    doc = ledger.document(item.doc_id)
    nature = item.date_spec.nature if item.date_spec else "other"
    if item.kind == "payment":
        return _open("document", doc.id, "Pay") if doc else _open("item", item.id, "Pay")
    if nature == "objection" and doc and doc.remedy and doc.remedy.type in ("einspruch", "widerspruch"):
        return _draft("objection", "document", doc.id, "Draft objection")
    if nature == "notice" and item.contract_id:
        return _draft("cancellation", "contract", item.contract_id, "Draft cancellation")
    if doc is not None:
        return _open("document", doc.id, "Check the letter")
    return _open("item", item.id, "Open the to-do")


def _item_refs(ledger: Ledger, item: Item) -> list[SuggestionRef]:
    refs = [_ref("item", item.id)]
    if ledger.document(item.doc_id):
        refs.append(_ref("document", item.doc_id or ""))
    if item.contract_id:
        refs.append(_ref("contract", item.contract_id))
    return refs


def _source_line(ledger: Ledger, item: Item) -> str | None:
    doc = ledger.document(item.doc_id)
    if doc is None:
        return None
    sender = ledger.party_name(doc.party_id)
    written = parse_day(doc.doc_date)
    parts = ["From the letter"]
    if written:
        parts.append(f"of {day_label(written, ledger.today)}")
    if sender:
        parts.append(f"from {sender}")
    return " ".join(parts) + "."


def _item_priority(kind: str, days_left: int) -> Priority:
    if kind in ("deadline", "payment"):
        if days_left <= 3:
            return "critical"
        return "high" if days_left <= 7 else "normal"
    return "high" if days_left <= 1 else "normal"


# --------------------------------------------------------------------------------------------------
# triggers
# --------------------------------------------------------------------------------------------------


def _handled_elsewhere(ledger: Ledger, item: Item) -> bool:
    """Money coming in, direct debits (the sender collects them — nothing to do), payment reminders
    (``dunning_escalation``), letters with scam signs (``scam_warning``) and payments another letter
    took over (a payment reminder, an e-mail's attached bill) never become "do this by" Ideas."""
    return (
        is_collected_or_incoming(item)
        or ledger.is_dunning_item(item)
        or ledger.is_suspicious_item(item)
        or ledger.is_superseded_by_reminder(item)
        or ledger.is_covered_by_attachment(item)
    )


def deadline_soon(ledger: Ledger) -> list[Suggestion]:
    """Open dated items whose day to act is within their reminder window (default 14 d deadlines,
    7 d payments). Payment reminders (dunning) are left to ``dunning_escalation``."""
    ideas: list[Suggestion] = []
    today = ledger.today
    for item in ledger.active_items():
        due, act = parse_day(item.due_date), action_day(item)
        if item.kind not in SOON_KINDS or due is None or act is None or due < today:
            continue
        if _handled_elsewhere(ledger, item):
            continue
        days = (act - today).days
        if days > ledger.reminder_window(item.kind):
            continue
        ideas.append(_soon_idea(ledger, item, due, act, days))
    return ideas


def _soon_idea(ledger: Ledger, item: Item, due: date, act: date, days: int) -> Suggestion:
    today = ledger.today
    if item.kind == "appointment":
        when = f"on {day_label(due, today)}" + (f" at {item.due_time}" if item.due_time else "")
    elif item.kind == "payment":
        when = f"pay by {day_label(act, today)}"
    elif sending_time_passed(item.computation):
        when = f"must arrive by {day_label(due, today)}"
    elif act < due:
        when = f"send by {day_label(act, today)}"
    else:
        when = f"due {day_label(due, today)}"
    send_note = None
    if act < due:
        send_note = f"Send it by {day_label(act, today)} so it arrives by {day_label(due, today)}."
    if days < 0 or sending_time_passed(item.computation):
        send_note = "The usual sending time has passed — use the fastest channel allowed today."
    english_consequence = english(item.consequence)
    consequence = f"If you don't: {english_consequence.rstrip('.')}." if english_consequence else None
    body = _sentences(
        english(item.action) or english(item.description),
        send_note,
        consequence,
        f"That's {in_days(max(days, 0))}.",
    )
    rationale = item.computation.summary if item.computation and item.computation.summary else None
    return make_idea(
        "deadline_soon",
        item.id,
        (item.due_date, item.send_by),
        IdeaText(f"{item.title}: {when}", body, rationale or _source_line(ledger, item)),
        kind="deadline",
        priority=_item_priority(item.kind, days),
        refs=_item_refs(ledger, item),
        action=item_action(ledger, item),
        due_date=max(act, today),
    )


def overdue(ledger: Ledger) -> list[Suggestion]:
    """Active deadlines, payments and tasks whose due date has passed (computed on read)."""
    ideas: list[Suggestion] = []
    today = ledger.today
    for item in ledger.active_items():
        due = parse_day(item.due_date)
        if due is None or not is_overdue(item, today) or _handled_elsewhere(ledger, item):
            continue
        consequence = f"If it stays undone: {item.consequence.rstrip('.')}." if item.consequence else None
        body = _sentences(
            f"This was due on {day_label(due, today)} ({in_days((due - today).days)}).",
            consequence,
            "If you've already dealt with it, mark it as done; otherwise act today and consider getting advice.",
        )
        ideas.append(
            make_idea(
                "overdue",
                item.id,
                (item.due_date,),
                IdeaText(f"Overdue: {item.title}", body, _source_line(ledger, item)),
                kind="deadline",
                priority="critical" if item.kind in ("deadline", "payment") else "high",
                refs=_item_refs(ledger, item),
                action=item_action(ledger, item),
                due_date=due,
            )
        )
    return ideas


def _citations(rule_ids: Iterable[str], wanted: Iterable[str] | None = None) -> str:
    chosen = [rid for rid in rule_ids if wanted is None or rid in wanted]
    texts: list[str] = []
    for rid in chosen:
        try:
            citation = get_rule(rid).citation
        except KeyError:
            continue
        if citation not in texts:
            texts.append(citation)
    return "; ".join(texts)


def _cost_line(contract: Contract) -> str | None:
    monthly = contract.monthly_cost()
    if monthly is None:
        return None
    return f"It costs {eur(monthly)} a month ({eur(round(monthly * 12, 2))} a year)."


def contract_cancel_window(ledger: Ledger) -> list[Suggestion]:
    """Active contracts whose cancellation must be sent within 60 days to avoid a renewal."""
    ideas: list[Suggestion] = []
    today = ledger.today
    decided = ledger.decided_contracts()
    for contract in ledger.active_contracts():
        comp = ledger.computation(contract)
        send = parse_day(comp.send_by)
        if not is_decision(comp) or send is None or (send - today).days > CANCEL_WINDOW_DAYS:
            continue
        if contract.id in decided:
            continue
        days = (send - today).days
        term_end = parse_day(comp.current_term_end)
        keep = None
        if term_end is not None:
            keep = f"If you keep it, you don't need to do anything — it continues after {day_label(term_end, today)}."
        body = _sentences(comp.summary, _cost_line(contract), keep)
        closes = in_days(((parse_day(comp.cancel_by) or send) - today).days)
        citations = _citations(comp.rule_ids[:1])
        rationale = f"The cancellation window closes {closes}" + (f" ({citations})." if citations else ".")
        refs = [_ref("contract", contract.id)]
        if contract.party_id in ledger.parties:
            refs.append(_ref("party", contract.party_id or ""))
        if ledger.document(contract.source_doc_id):
            refs.append(_ref("document", contract.source_doc_id or ""))
        ideas.append(
            make_idea(
                "contract_cancel_window",
                contract.id,
                (comp.cancel_by, comp.current_term_end),
                IdeaText(
                    f"Decide on your {contract.name} — send by {day_label(send, today)}", body, rationale
                ),
                kind="deadline",
                priority="critical" if days <= 3 else "high" if days <= 14 else "normal",
                refs=refs,
                action=_draft("cancellation", "contract", contract.id, "Draft cancellation"),
                due_date=send,
            )
        )
    return ideas


def yearly_extra_cost(old: float | None, new: float | None, interval: str | None) -> float | None:
    """Extra cost per year of a price change (``None`` when it can't be normalised)."""
    per_year = _INTERVAL_PER_YEAR.get(interval or "")
    if old is None or new is None or per_year is None:
        return None
    return round((new - old) * per_year, 2)


#: A contribution rate as a number: "2,5 %", "2.5%", "2,50 Prozent".
_RATE = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:%|prozent\b|percent\b)", re.I)


def contribution_rate(text: str | None) -> float | None:
    """The one percentage in ``text`` (``None`` for none, or for several: which one is meant is unclear)."""
    rates = _RATE.findall(text or "")
    return float(rates[0].replace(",", ".")) if len(rates) == 1 else None


def zusatzbeitrag_raised(change: ExtractedChange) -> bool:
    """Whether a health insurer's price increase opens the special right to cancel (§ 175 Abs. 4 S. 5
    SGB V), which only a higher additional contribution rate (Zusatzbeitrag) does — not a contribution
    that rises because the income did.

    Reading which rate a letter talks about is the model's job, not code's: the change must state the
    rate as numbers, old and new (``unit_price_old``/``unit_price_new`` with one percentage each), and
    the new one must be higher. Anything else gets no special-right Idea: a missed Idea is acceptable,
    a wrong legal claim is not (a genuine raise letter must state the right itself, and Ordnung files
    that as the letter's own to-do)."""
    old, new = contribution_rate(change.unit_price_old), contribution_rate(change.unit_price_new)
    return old is not None and new is not None and new > old


def price_increase_right(ledger: Ledger) -> list[Suggestion]:
    """Price-increase letters linked to an active contract with a statutory special cancellation
    window still open (:meth:`Ledger.price_increase_windows`)."""
    ideas: list[Suggestion] = []
    today = ledger.today
    for window in ledger.price_increase_windows():
        doc, contract, change, receipt = window.letter, window.contract, window.change, window.receipt
        due = window.due
        old = change.old_amount if change.old_amount is not None else contract.cost_amount
        extra = yearly_extra_cost(old, change.new_amount, change.cost_interval or contract.cost_interval)
        who = ledger.party_name(contract.party_id) or contract.name
        cost = f": +{eur(extra)}/year extra cost" if extra is not None and extra > 0 else ""
        title = f"{who} raises prices{cost} — you may cancel until {day_label(due, today)}"
        act = parse_day(receipt.send_by) or due
        body = _sentences(receipt.summary, *receipt.warnings[:1], "Compare offers before you decide.")
        rationale = (
            f"Special right to cancel after a price increase ({_citations(receipt.rule_ids, _PRICE_RULES)})."
        )
        switch = "sgbv_175_4_zb" in receipt.rule_ids
        action = (
            _open("document", doc.id, "Compare insurers")
            if switch
            else _draft("cancellation", "contract", contract.id, "Draft cancellation")
        )
        days = (act - today).days
        ideas.append(
            make_idea(
                "price_increase_right",
                doc.id,
                (change.effective_date, receipt.due_date, extra),
                IdeaText(title, body, rationale),
                kind="deadline",
                priority="critical" if days <= 3 else "high" if days <= 14 else "normal",
                refs=[_ref("document", doc.id), _ref("contract", contract.id)],
                action=action,
                due_date=max(act, today),
            )
        )
    return ideas


def _expiry_window(ledger: Ledger, klass: str) -> int:
    if klass == "permit":
        return PERMIT_WINDOW_DAYS
    if klass == "identity":
        return IDENTITY_WINDOW_DAYS
    return ledger.reminder_window("expiry")


RESIDENCE_EXTENSION_LAW = "§ 81 Abs. 4 AufenthG"
"""Applying before a residence permit expires keeps it in force until the office decides."""
STUDENT_WORK_LAW = "§ 16b Abs. 3 AufenthG"
"""How much a student with a residence permit may work."""
IDEA_LAWS = (RESIDENCE_EXTENSION_LAW, STUDENT_WORK_LAW)
"""The § citations Ordnung's own Ideas state outside the rules catalog: Ask's check knows them like
the catalog's (ADR 0008), so a correct "§ 81 Abs. 4 AufenthG" is not taken for an unvouched law."""


def _expiry_text(klass: str, item: Item, expiry: date, today: date) -> IdeaText:
    day = day_label(expiry, today)
    past = expiry < today
    if klass == "permit":
        if past:
            return IdeaText(
                f"Your residence permit expired on {day}",
                "Contact the immigration office (Ausländerbehörde) right away and get advice — the "
                "Studierendenwerk, your international office or a migration counselling service can help.",
                f"Residence permits must be extended before they expire ({RESIDENCE_EXTENSION_LAW}).",
            )
        return IdeaText(
            f"Residence permit expires {day} — apply for the extension now",
            "Apply at the immigration office (Ausländerbehörde) before it expires. If you apply in time, "
            f"your current permit continues to count until they decide ({RESIDENCE_EXTENSION_LAW}) — ask for a "
            "Fiktionsbescheinigung. Appointments are often booked out for weeks.",
            f"Residence permits: apply before expiry ({RESIDENCE_EXTENSION_LAW}).",
        )
    if klass == "identity":
        return IdeaText(
            f"Your {'passport or ID' if 'ausweis' in item.title.casefold() else 'passport'} "
            f"{'expired on' if past else 'expires'} {day}",
            "Renewing a passport or ID card can take weeks or months (embassy or consulate appointments), "
            "so start early. Your residence permit can usually only run as long as your passport is valid.",
            f"Identity documents are flagged {IDENTITY_WINDOW_DAYS} days before they expire.",
        )
    return IdeaText(
        f"{item.title}: {'expired' if past else 'expires'} {day}",
        _sentences(item.action or item.description, f"That's {in_days((expiry - today).days)}."),
    )


def expiry_soon(ledger: Ledger) -> list[Suggestion]:
    """Expiring documents: passport/ID 180 days ahead, residence permit 90 days (apply before expiry,
    § 81 Abs. 4 AufenthG), other expiries within their reminder window. Expired ones too."""
    ideas: list[Suggestion] = []
    today = ledger.today
    for item in ledger.active_items():
        expiry = parse_day(item.due_date)
        if item.kind != "expiry" or expiry is None:
            continue
        doc = ledger.document(item.doc_id)
        klass = expiry_class(item, doc)
        days = (expiry - today).days
        if days > _expiry_window(ledger, klass):
            continue
        if klass == "permit":
            priority: Priority = "critical" if days <= 30 else "high"
            label = "Check the permit"
        elif klass == "identity":
            priority = "high" if days <= 60 else "normal"
            label = "Check the passport"
        else:
            priority = "high" if days <= 7 else "normal"
            label = "Check the letter"
        action = _open("document", doc.id, label) if doc else _open("item", item.id, "Open the to-do")
        ideas.append(
            make_idea(
                "expiry_soon",
                item.id,
                (item.due_date, klass),
                _expiry_text(klass, item, expiry, today),
                kind="deadline",
                priority=priority,
                refs=_item_refs(ledger, item),
                action=action,
                due_date=expiry,
            )
        )
    return ideas


def _expiries(ledger: Ledger, klass: str) -> list[tuple[Item, date]]:
    found: list[tuple[Item, date]] = []
    for item in ledger.active_items():
        expiry = parse_day(item.due_date)
        if item.kind == "expiry" and expiry and expiry_class(item, ledger.document(item.doc_id)) == klass:
            found.append((item, expiry))
    return sorted(found, key=lambda pair: (pair[1], pair[0].id))


def passport_before_permit(ledger: Ledger) -> list[Suggestion]:
    """A passport expiring before (or within 180 days after) the residence permit: the permit can
    usually only be extended as long as the passport is valid, so renew the passport first."""
    today = ledger.today
    permits = [
        (item, day)
        for item, day in _expiries(ledger, "permit")
        if (day - today).days <= PASSPORT_CHECK_HORIZON_DAYS
    ]
    if not permits:
        return []
    permit, permit_day = permits[0]
    ideas: list[Suggestion] = []
    for passport, passport_day in _expiries(ledger, "identity"):
        if passport_day > permit_day + timedelta(days=PASSPORT_MARGIN_DAYS):
            continue
        relation = "before" if passport_day < permit_day else "soon after"
        body = _sentences(
            f"Your passport expires on {day_label(passport_day, today)} — {relation} your residence permit "
            f"({day_label(permit_day, today)}).",
            "The immigration office (Ausländerbehörde) usually extends a permit only as long as your passport "
            "is valid, which would mean another appointment soon. Ask your embassy or consulate about a new "
            "passport now.",
        )
        doc = ledger.document(passport.doc_id)
        action = (
            _open("document", doc.id, "Check the passport")
            if doc
            else _open("item", passport.id, "Open the to-do")
        )
        ideas.append(
            make_idea(
                "passport_before_permit",
                passport.id,
                (passport.due_date, permit.due_date),
                IdeaText(
                    "Renew your passport before extending your residence permit",
                    body,
                    f"Passport expires within {PASSPORT_MARGIN_DAYS} days of the residence permit.",
                ),
                kind="risk",
                priority="high",
                refs=[*_item_refs(ledger, passport), *_item_refs(ledger, permit)],
                action=action,
                due_date=permit_day,
            )
        )
    return ideas


def _matching_draft(ledger: Ledger, item: Item) -> Draft | None:
    for draft in ledger.sent_drafts():
        links = (
            (draft.contract_id, item.contract_id),
            (draft.case_id, item.case_id),
            (draft.doc_id, item.doc_id),
            (draft.party_id, item.party_id),
        )
        if any(mine is not None and mine == theirs for mine, theirs in links):
            return draft
    return None


def _followup_draft(ledger: Ledger, item: Item) -> Draft | None:
    """The sent letter whose follow-up to-do ``item`` is (its id is derived from the letter's)."""
    return next((draft for draft in ledger.sent_drafts() if followup_item_id(draft.id) == item.id), None)


def _proof_sentences(ledger: Ledger, draft: Draft) -> list[str]:
    """What the letter's proof adds to a reminder: the delivery day and the tracking number."""
    today = ledger.today
    said: list[str] = []
    delivered = sorted(
        day
        for proof in ledger.proofs_of(draft.id)
        if proof.kind in ("delivery_record", "return_receipt") and (day := parse_day(proof.on_date))
    )
    if delivered:
        said.append(
            f"Your proof shows it was delivered on {day_label(delivered[0], today)} — say so when you remind them."
        )
    tracking = tracking_info(draft.tracking_number)
    if tracking is not None:
        said.append(f"Quote the tracking number {tracking.display} if you call.")
    return said


def _answered_idea(ledger: Ledger, item: Item, draft: Draft, reply: Document, due: date) -> Suggestion:
    today = ledger.today
    who = ledger.party_name(reply.party_id) or ledger.party_name(item.party_id) or "They"
    reply_day = parse_day(reply.doc_date or reply.received_date or reply.created_at)
    when = f" of {day_label(reply_day, today)}" if reply_day else ""
    sent_day = parse_day(draft.sent_at)
    sent = f", sent {day_label(sent_day, today)}" if sent_day else ""
    body = _sentences(
        f"Their letter “{reply.title or reply.filename}”{when} came after yours (“{draft.subject}”{sent}).",
        "Check that it answers your letter, then mark the follow-up done.",
    )
    answer = ledger.answer_of(draft)
    confirmed = answer is not None and answer.document is not None and answer.document.id == reply.id
    # a letter that is only in the same thread may be about something else: ask, don't state
    title = (
        f"{who} confirmed — close the follow-up?"
        if confirmed
        else f"A letter from {who} came — is it the answer?"
    )
    if who == "They" and not confirmed:
        title = "A letter came in the same thread — is it the answer?"
    return make_idea(
        "followup_due",
        item.id,
        (item.due_date, "answered", reply.id),
        IdeaText(title, body, f"Follow-up date {day_label(due, today)}."),
        kind="followup",
        priority="normal",
        refs=[_ref("item", item.id), _ref("draft", draft.id), _ref("document", reply.id)],
        action=_open("draft", draft.id, "Open the letter"),
        due_date=due,
    )


def followup_due(ledger: Ledger) -> list[Suggestion]:
    """A sent letter's follow-up item (created when a draft is marked as sent) has become due.

    With the letter's proof state: when a letter linked to it arrived (:meth:`Ledger.reply_to`) the Idea
    asks the person to check that answer and close the follow-up (it closes nothing itself); otherwise a
    recorded delivery day and tracking number are named for the reminder. A letter without proof keeps
    the plain reminder.
    """
    ideas: list[Suggestion] = []
    today = ledger.today
    for item in ledger.active_items():
        due = parse_day(item.due_date)
        if item.origin != "draft" or due is None or due > today:
            continue
        exact = _followup_draft(ledger, item)
        reply = ledger.reply_to(exact) if exact is not None else None
        if exact is not None and reply is not None:
            ideas.append(_answered_idea(ledger, item, exact, reply, due))
            continue
        draft = exact or _matching_draft(ledger, item)
        refs = [_ref("item", item.id)]
        sent = None
        if draft is not None:
            refs.append(_ref("draft", draft.id))
            sent_day = parse_day(draft.sent_at)
            if sent_day:
                sent = f"You sent “{draft.subject}” on {day_label(sent_day, today)}."
        if item.contract_id:
            refs.append(_ref("contract", item.contract_id))
            action = _draft("general_reply", "contract", item.contract_id, "Write a follow-up")
        elif ledger.document(item.doc_id):
            refs.append(_ref("document", item.doc_id or ""))
            action = _draft("general_reply", "document", item.doc_id or "", "Write a follow-up")
        else:
            action = _open("item", item.id, "Open the to-do")
        body = _sentences(
            sent,
            "If you haven't had an answer, send a short reminder or call them — and keep a note of it.",
            *(_proof_sentences(ledger, exact) if exact is not None else ()),
        )
        ideas.append(
            make_idea(
                "followup_due",
                item.id,
                (item.due_date,),
                IdeaText(f"Follow-up due: {item.title}", body, f"Follow-up date {day_label(due, today)}."),
                kind="followup",
                priority="high" if (today - due).days > FOLLOWUP_LATE_DAYS else "normal",
                refs=refs,
                action=action,
                due_date=due,
            )
        )
    return ideas


#: Days after sending before a registered cancellation or objection without proof becomes an Idea.
PROOF_GRACE_DAYS = 2
#: Letters whose proof of arrival decides a deadline (``proof_missing`` watches these).
PROOF_WATCHED_KINDS = frozenset({"cancellation", "objection"})


def proof_missing(ledger: Ledger) -> list[Suggestion]:
    """A cancellation or objection sent by Einschreiben has no tracking number and no proof two days on.

    Not raised when an answer from them shows it arrived (:meth:`Ledger.answer_of` — a later letter that
    is merely in the same thread is not one, and the person's word that it was answered shows nothing
    about arrival: ``drafts.proof`` policy 3), when the person closed its follow-up themselves, or once
    Deutsche Post no longer issues the delivery record (15 months after posting). Once a tracking
    number or a proof is added the Idea expires.
    """
    ideas: list[Suggestion] = []
    today = ledger.today
    for draft in ledger.sent_drafts():
        sent = parse_day(draft.sent_at)
        if (
            draft.kind not in PROOF_WATCHED_KINDS
            or draft.sent_channel != "registered_letter"
            or sent is None
            or (today - sent).days < PROOF_GRACE_DAYS
            or draft.tracking_number
            or ledger.proofs_of(draft.id)
            or not delivery_record_obtainable(draft, today)
        ):
            continue
        answer = ledger.answer_of(draft)
        if answer is not None and answer.how != "noted":
            continue
        followup = ledger.followup_item(draft)
        # "I got an answer" closes the follow-up too, but says nothing about arrival
        if answer is None and followup is not None and followup.status in ("done", "dismissed"):
            continue
        who = ledger.party_name(draft.party_id) or "the recipient"
        what = "cancellation" if draft.kind == "cancellation" else "objection"
        body = _sentences(
            f"You sent “{draft.subject}” on {day_label(sent, today)} by Einschreiben, but Ordnung has no "
            "tracking number or receipt for it.",
            "Add the tracking number and a photo of the posting receipt (Einlieferungsbeleg) — or, for an "
            "Einschreiben bought online, the number next to the stamp's square code — and ask Deutsche "
            "Post for the delivery record (Auslieferungsbeleg); they issue it only within 15 months of "
            "posting. Together with the posting receipt, that is what courts have accepted as a sign "
            "that a letter arrived — never as proof of what was inside.",
        )
        refs = [_ref("draft", draft.id)]
        if draft.contract_id:
            refs.append(_ref("contract", draft.contract_id))
        if draft.doc_id and ledger.document(draft.doc_id):
            refs.append(_ref("document", draft.doc_id))
        ideas.append(
            make_idea(
                "proof_missing",
                draft.id,
                (draft.sent_at,),
                IdeaText(
                    f"Keep the proof of your {what} to {who}",
                    body,
                    "The posting receipt with the online tracking status alone was not accepted as proof "
                    "that a letter arrived (BAG 2 AZR 68/24).",
                ),
                kind="followup",
                priority="normal",
                refs=refs,
                action=_open("draft", draft.id, "Add proof"),
                due_date=None,
            )
        )
    return ideas


def _unsure_items(items: Iterable[Item]) -> list[Item]:
    return [
        item
        for item in items
        if item.grounding == "unverified" or any(not ev.value_consistent for ev in item.evidence)
    ]


def please_check(ledger: Ledger) -> list[Suggestion]:
    """Documents that need the person's review ("Please check")."""
    ideas: list[Suggestion] = []
    today = ledger.today
    active = ledger.active_items()
    for doc in ledger.documents.values():
        if doc.status != "needs_review":
            continue
        doc_items = [item for item in active if item.doc_id == doc.id]
        unsure = _unsure_items(doc_items)
        days = [day for day in (action_day(item) for item in doc_items) if day is not None]
        first = min(days) if days else None
        if any(item.slot_key == CHECK_SLOT for item in unsure):
            # the to-do Ordnung added itself: nothing was "not found" — the reading came back incomplete
            body = (
                "Claude's reading of this letter came back incomplete, so Ordnung added a to-do from the "
                "letter's own words. Open the letter and check it."
            )
        elif unsure:
            listed = ", ".join(item.title for item in unsure[:3])
            body = f"We couldn't find some dates or amounts in the letter ({listed}). Open it and confirm or correct them."
        else:
            body = "Some details of this letter need your confirmation before Ordnung relies on them."
        ideas.append(
            make_idea(
                "please_check",
                doc.id,
                tuple(sorted(item.id for item in unsure)),
                IdeaText(f"Please check: {doc.title or doc.filename}", body),
                kind="info",
                priority="high" if first is not None and (first - today).days <= 14 else "normal",
                refs=[_ref("document", doc.id), *(_ref("item", item.id) for item in unsure)],
                action=_open("document", doc.id, "Check the letter"),
                due_date=first,
            )
        )
    return ideas


def _earlier_invoice(ledger: Ledger, dunning: Document) -> Document | None:
    candidates = [
        doc
        for doc in ledger.documents.values()
        if doc.kind == "invoice"
        and doc.party_id
        and doc.party_id == dunning.party_id
        and doc.doc_date
        and (dunning.doc_date is None or doc.doc_date <= dunning.doc_date)
    ]
    return max(candidates, key=lambda doc: (doc.doc_date or "", doc.id), default=None)


#: Senders that are public bodies: a library's, a university's or an authority's fee is never taken to
#: a debt collector or a court payment order — they add reminder fees and, in the end, collect it
#: themselves (administrative enforcement). UI audit R1-backend-7: a €4.50 library fee warned of a
#: Mahnbescheid.
PUBLIC_CREDITOR_KINDS = frozenset(
    {"authority", "tax_office", "immigration_office", "university", "public_broadcaster"}
)
_PRIVATE_UNPAID = (
    "If it stays unpaid, the next step is usually a debt collector or a court payment order "
    "(Mahnbescheid), which adds costs."
)
_PUBLIC_UNPAID = (
    "If it stays unpaid, more reminder fees can follow, and a public body can in the end collect it "
    "itself (administrative enforcement)."
)


def dunning_escalation(ledger: Ledger) -> list[Suggestion]:
    """Payment reminders (Mahnungen) with an open payment: pay, or object if you don't owe it. What
    follows if it stays unpaid depends on the sender: a company's claim goes to a debt collector or a
    court payment order, a public body's is collected by the body itself (:data:`PUBLIC_CREDITOR_KINDS`)."""
    ideas: list[Suggestion] = []
    today = ledger.today
    active = ledger.active_items()
    for doc in ledger.documents.values():
        payments = [
            i
            for i in active
            if i.doc_id == doc.id
            and i.kind == "payment"
            and i.due_date
            and not ledger.is_superseded_by_reminder(i)
            and not ledger.is_covered_by_attachment(i)
        ]
        if doc.kind != "dunning" or not payments or ledger.scam_reasons(doc):
            continue  # letters with scam signs get a scam warning instead of "pay"
        payment = min(payments, key=lambda i: (action_day(i) or today, i.id))
        act = action_day(payment) or today
        who = ledger.party_name(doc.party_id) or "the sender"
        amount = f" {eur(payment.amount)}" if payment.amount is not None else ""
        days = (act - today).days
        title = (
            f"Overdue reminder from {who}: pay{amount} now"
            if days < 0
            else f"Pay {who} reminder{amount} by {day_label(act, today)}"
        )
        invoice = _earlier_invoice(ledger, doc)
        invoice_day = parse_day(invoice.doc_date) if invoice else None
        party = ledger.parties.get(doc.party_id) if doc.party_id else None
        body = _sentences(
            "This is a payment reminder (Mahnung)"
            + (f" for the invoice of {day_label(invoice_day, today)}." if invoice_day else "."),
            _PUBLIC_UNPAID if party is not None and party.kind in PUBLIC_CREDITOR_KINDS else _PRIVATE_UNPAID,
            f"If you already paid, tell {who} when and keep the proof; if you don't owe it, say so in writing.",
        )
        refs = [_ref("document", doc.id), _ref("item", payment.id)]
        if invoice is not None:
            refs.append(_ref("document", invoice.id))
        ideas.append(
            make_idea(
                "dunning_escalation",
                doc.id,
                (payment.id, payment.due_date, payment.amount),
                IdeaText(title, body, f"Payment reminder, due {in_days(days)}."),
                kind="risk",
                priority="critical" if days <= 7 else "high",
                refs=refs,
                action=_open("document", doc.id, "Pay"),
                due_date=max(act, today),
            )
        )
    return ideas


def is_checksum_note(warning: str) -> bool:
    """A warning that only says an IBAN fails its checksum (added by the pipeline or the model)."""
    text = warning.casefold()
    return "iban" in text and ("check digit" in text or "checksum" in text)


def iban_fails_checksum(doc: Document) -> bool:
    """The letter's payment IBAN fails its ISO 13616 checksum."""
    payment = doc.payment
    if payment is None or not payment.iban:
        return False
    if payment.iban_valid is not None:
        return payment.iban_valid is False
    return _scam is not None and not _scam.iban_valid(_scam.normalize_iban(payment.iban))


#: Warnings that are no scam sign of their own: the reading's count of dates it couldn't confirm, a "Please
#: check" note, the note that the reading came back incomplete (``ordnung.ingest.gaps.gap_warning``), and text
#: meant for software — said once, as hidden text (as ``otherWarnings``, ``scamSigns`` and
#: ``isHiddenTextWarning`` in ``web/src/features/document/Warnings.tsx``).
_NOT_A_SIGN = re.compile(
    r"^(?:please check\b|\d+\s+dates?\s+could not be confirmed)|invisible text|hidden text"
    r"|addressed to (?:an? )?(?:AI|KI)\b|\bKI-Assistent|AI assistant|prompt injection"
    r"|^Claude's reading of this letter came back almost blank|^This letter explains how to (?:object|challenge it "
    r"in court), but Claude's reading",
    re.I,
)
HIDDEN_TEXT_SIGN = "The letter contains hidden text that you can't see on the page."


def scam_signs(doc: Document, reasons: Sequence[str]) -> list[str]:
    """Every warning sign of a letter with scam signs (``reasons``, :func:`_scam_reasons`, not empty), as
    its page and its Idea list them — one list, one count (walkthrough of phase 2: the Idea said "5
    warning signs", the page "the 3 strongest of 7", and hidden text was said twice). Once a letter shows
    scam signs, each warning its reading carries is one more — except notes that are no sign
    (:data:`_NOT_A_SIGN`) —, hidden text is said once, in Ordnung's words, and the code's findings come
    too (a payee that doesn't match, a failing IBAN)."""
    signs = [HIDDEN_TEXT_SIGN] if doc.hidden_text else []
    signs.extend(w for w in doc.warnings if w.strip() and not _NOT_A_SIGN.search(w))
    signs.extend(r for r in reasons if not _NOT_A_SIGN.search(r))
    return list(dict.fromkeys(signs))


def _scam_reasons(store: Store, doc: Document, party: Party | None) -> list[str]:
    """Hidden text, scam-like warnings and — via :mod:`ordnung.secretary.scam` — an IBAN or payee that
    doesn't match what the sender (or a look-alike organisation) used before.

    An IBAN that only fails its checksum is almost always a misprint or a misread digit (a scammer
    needs an account that works), so on its own it is no scam sign — :func:`iban_misprint` reports
    it calmly. Next to other signs it is listed as one more.
    """
    reasons: list[str] = []
    if doc.hidden_text:
        reasons.append(HIDDEN_TEXT_SIGN)
    reasons.extend(
        w
        for w in doc.warnings
        if any(word in w.casefold() for word in _SCAM_WORDS)
        and not is_checksum_note(w)
        and not (doc.hidden_text and _NOT_A_SIGN.search(w))  # hidden text is said once
    )
    finding = None
    if _scam is not None and party is not None and doc.payment is not None:
        finding = _scam.payment_mismatch(store, party, doc.payment, exclude_doc_id=doc.id)
        if finding is not None and finding.kind != "invalid_iban":
            reasons.append(finding.message)
    if reasons and doc.payment and doc.payment.iban and iban_fails_checksum(doc):
        reasons.append(
            f"The IBAN {doc.payment.iban} fails its checksum, so it can't be a real account number."
        )
    return list(dict.fromkeys(reasons))


def scam_warning(ledger: Ledger) -> list[Suggestion]:
    """Scam indicators found by code (hidden text, invalid IBAN, payee mismatch) or flagged in the
    document's warnings."""
    ideas: list[Suggestion] = []
    today = ledger.today
    active = ledger.active_items()
    for doc in ledger.documents.values():
        reasons = ledger.scam_signs(doc)
        if not reasons:
            continue
        pay_days = [action_day(i) for i in active if i.doc_id == doc.id and i.kind == "payment"]
        due = min((day for day in pay_days if day is not None), default=None)
        body = _sentences(
            *reasons,
            "Don't pay or reply until you've checked with the sender using contact details you already know "
            "— not the ones in this letter.",
        )
        refs = [_ref("document", doc.id)]
        if doc.party_id in ledger.parties:
            refs.append(_ref("party", doc.party_id or ""))
        ideas.append(
            make_idea(
                "scam_warning",
                doc.id,
                tuple(sorted(reasons)),
                IdeaText(
                    f"Possible scam: {_letter_title(doc.title or doc.filename)}",
                    body,
                    "1 warning sign." if len(reasons) == 1 else f"{len(reasons)} warning signs.",
                ),
                kind="scam",
                priority="critical",
                refs=refs,
                action=_open("document", doc.id, "See why"),
                due_date=max(due, today) if due else None,
            )
        )
    return ideas


def iban_misprint(ledger: Ledger) -> list[Suggestion]:
    """A letter asks you to transfer money to an IBAN that fails its checksum, with no other scam signs:
    most likely a misprint (or a misread photo). An Info Idea to check it before paying — no alarm."""
    ideas: list[Suggestion] = []
    today = ledger.today
    active = ledger.actionable_items()
    for doc in ledger.documents.values():
        payment = doc.payment
        if doc.direction != "incoming" or payment is None or not payment.iban or not iban_fails_checksum(doc):
            continue
        if ledger.scam_reasons(doc):
            continue  # scam_warning lists the checksum next to the other signs
        days = [
            day
            for item in active
            if item.doc_id == doc.id
            and item.kind == "payment"
            and item.direction != "in"
            and not is_direct_debit(item)
            for day in (action_day(item),)
            if day is not None
        ]
        if not days:
            continue  # nothing to transfer: the IBAN doesn't matter
        who = ledger.party_name(doc.party_id) or "the sender"
        iban = _scam.format_iban(_scam.normalize_iban(payment.iban)) if _scam is not None else payment.iban
        refs = [_ref("document", doc.id)]
        if doc.party_id in ledger.parties:
            refs.append(_ref("party", doc.party_id or ""))
        ideas.append(
            make_idea(
                "iban_misprint",
                doc.id,
                (payment.iban,),
                IdeaText(
                    f"The IBAN from {who} looks misprinted — check it before you pay",
                    _sentences(
                        f"{iban} doesn't pass the bank check, so a transfer to it would fail.",
                        "Most likely a digit is misprinted or was misread. Compare it with the paper letter; if "
                        f"it's printed like that, ask {who} for the right account number.",
                    ),
                    "The IBAN's check digits don't match (ISO 13616).",
                ),
                kind="info",
                priority="normal",
                refs=refs,
                action=_open("document", doc.id, "Check the letter"),
                due_date=max(min(days), today),
            )
        )
    return ideas


def tax_documents(ledger: Ledger) -> list[Suggestion]:
    """January–July: collect last year's tax-relevant letters for the tax return."""
    today = ledger.today
    if today.month > TAX_SEASON_LAST_MONTH:
        return []
    year = today.year - 1
    docs = sorted(
        (
            doc
            for doc in ledger.documents.values()
            if doc.tax_relevant and (parse_day(doc.doc_date) or date.min).year == year
        ),
        key=lambda doc: (doc.doc_date or "", doc.id),
    )
    if not docs:
        return []
    body = _sentences(
        f"{len(docs)} letter(s) from {year} could matter for your tax return — payslips, insurance, "
        "receipts for work or study costs.",
        "If you have to file a return it is usually due by the end of July; filing voluntarily is possible "
        "for four years and often brings money back.",
    )
    return [
        make_idea(
            "tax_documents",
            str(year),
            tuple(doc.id for doc in docs),
            IdeaText(
                f"Your {year} tax documents are ready to collect",
                body,
                f"{len(docs)} tax-relevant letter(s).",
            ),
            kind="tax",
            priority="normal",
            refs=[_ref("document", doc.id) for doc in docs[:10]],
            action=_open("document", docs[0].id, "See the documents"),
            due_date=date(today.year, 7, 31),
        )
    ]


def _changed_after(stamp: str, since: datetime | None) -> bool:
    if since is None:
        return True
    moment = parse_timestamp(stamp)
    return moment is None or moment > since


def calendar_outdated(ledger: Ledger) -> list[Suggestion]:
    """Open future dates (items and contract send-by days) added or changed since the last .ics export.

    Not while a calendar is connected for calendar sync (paused or not): it gets the dates by itself,
    and importing the file into it as well would clash with the synced events (the same UIDs)."""
    if ledger.store.get_meta(CALENDAR_SYNC_META_KEY):
        return []
    today = ledger.today
    raw = ledger.store.get_meta(CALENDAR_META_KEY)
    since = parse_timestamp(raw)
    dates: list[tuple[date, SuggestionRef]] = []
    for item in ledger.active_items():
        due = parse_day(item.due_date)
        if due is not None and due >= today and _changed_after(item.updated_at, since):
            dates.append((action_day(item) or due, _ref("item", item.id)))
    for contract in ledger.active_contracts():
        comp = ledger.computation(contract)
        send = parse_day(comp.send_by)
        if is_decision(comp) and send is not None and _changed_after(contract.updated_at, since):
            dates.append((send, _ref("contract", contract.id)))
    if not dates:
        return []
    dates.sort(key=lambda pair: (pair[0], pair[1].id))
    count = len(dates)
    title = (
        f"{count} new date{'s' if count != 1 else ''} since your last calendar update"
        if since
        else f"Add your {count} date{'s' if count != 1 else ''} to your calendar"
    )
    body = "Download the calendar file and import it, so your phone reminds you even when Ordnung is closed."
    return [
        make_idea(
            "calendar_outdated",
            "calendar",
            (raw or "never", *(f"{ref.type}:{ref.id}" for _, ref in dates)),
            IdeaText(title, body),
            kind="hygiene",
            priority="normal",
            refs=[ref for _, ref in dates[:10]],
            action=SuggestionAction(type="none", target_type="calendar", label="Add to calendar"),
            due_date=dates[0][0],
        )
    ]


def cancellations_sent(sent: Iterable[Draft]) -> dict[str, CancellationSent]:
    """Contract id → the person's latest cancellation of it among ``sent`` (letters marked as sent,
    newest first): a ``cancellation`` letter that names the contract."""
    found: dict[str, CancellationSent] = {}
    for draft in sent:
        if draft.kind == "cancellation" and draft.status == "sent" and draft.contract_id:
            sent_on = parse_day(draft.sent_at)
            found.setdefault(
                draft.contract_id,
                CancellationSent(
                    draft_id=draft.id,
                    sent_on=sent_on.isoformat() if sent_on else None,
                    channel=draft.sent_channel,
                ),
            )
    return found


def _sent_cancellation(ledger: Ledger, contract_id: str) -> Draft | None:
    """The person's latest cancellation of this contract that was marked as sent."""
    return next(
        (
            draft
            for draft in ledger.sent_drafts()
            if draft.kind == "cancellation" and draft.contract_id == contract_id
        ),
        None,
    )


def _cancellation_sent_line(ledger: Ledger, draft: Draft) -> str:
    sent = parse_day(draft.sent_at)
    when = f" on {day_label(sent, ledger.today)}" if sent else ""
    tracking = tracking_info(draft.tracking_number)
    how = f" (tracking number {tracking.display})" if tracking else ""
    return (
        f"It answers your cancellation sent{when} by {channel_label(draft.sent_channel)}{how}: keep the two "
        "together as your proof."
    )


def confirm_cancellation(ledger: Ledger) -> list[Suggestion]:
    """A cancellation confirmation arrived for a contract that is still marked active.

    When the person's own cancellation of that contract was marked as sent, the Idea names it (how and
    when it went, its tracking number) and links it, so the confirmation is kept with the proof.
    """
    ideas: list[Suggestion] = []
    today = ledger.today
    by_id = {contract.id: contract for contract in ledger.contracts}
    for contract_id, (doc, effective) in sorted(ledger.pending_confirmations().items()):
        contract = by_id[contract_id]
        when = f" effective {day_label(effective, today)}" if effective else ""
        who = ledger.party_name(doc.party_id) or ledger.party_name(contract.party_id) or "The provider"
        mine = _sent_cancellation(ledger, contract.id)
        body = _sentences(
            f"{who} confirmed that your contract ends{' on ' + day_label(effective, today) if effective else ''}.",
            _cancellation_sent_line(ledger, mine) if mine is not None else None,
            "Check that this matches what you asked for, then confirm it so Ordnung stops tracking its "
            "deadlines and costs.",
        )
        refs = [_ref("document", doc.id), _ref("contract", contract.id)]
        if mine is not None:
            refs.append(_ref("draft", mine.id))
        ideas.append(
            make_idea(
                "confirm_cancellation",
                doc.id,
                (contract.id, effective.isoformat() if effective else None),
                IdeaText(f"Confirm cancellation of {contract.name}{when}?", body),
                kind="followup",
                priority="normal",
                refs=refs,
                action=SuggestionAction(
                    type="mark_done",
                    target_type="contract",
                    target_id=contract.id,
                    label="Confirm cancellation",
                ),
                due_date=effective,
            )
        )
    return ideas


def student_permit_info(ledger: Ledger) -> list[Suggestion]:
    """Static info card on working with a student residence permit (replaces a work-days trigger, §21)."""
    if not ledger.profile.is_student_visa:
        return []
    permits = sorted(
        (doc for doc in ledger.documents.values() if doc.kind == "residence_permit"),
        key=lambda doc: (doc.doc_date or "", doc.id),
    )
    refs = [_ref("document", permits[-1].id)] if permits else []
    action = (
        _open("document", permits[-1].id, "Check the permit")
        if permits
        else SuggestionAction(type="none", label="Read the rules")
    )
    body = _sentences(
        "A student residence permit lets you work up to 140 full or 280 half days a year, plus student "
        f"jobs at your university ({STUDENT_WORK_LAW}).",
        "Check the conditions printed on your permit (Nebenbestimmungen) and ask the international "
        "office or the Studierendenwerk before taking on more.",
        "Law: " + _PERMIT_LINKS[0] + " · Advice: " + _PERMIT_LINKS[1],
    )
    return [
        make_idea(
            STUDENT_PERMIT_RULE,
            "profile",
            ("v1",),
            IdeaText(
                "Working on a student permit: know your limits",
                body,
                "You told us you study on a residence permit.",
            ),
            kind="info",
            priority="low",
            refs=refs,
            action=action,
            due_date=None,
        )
    ]


Trigger = Callable[[Ledger], list[Suggestion]]

#: Every rule in evaluation order (the keys are the ``rule_id``s stored on the Ideas).
TRIGGERS: dict[str, Trigger] = {
    "deadline_soon": deadline_soon,
    "overdue": overdue,
    "contract_cancel_window": contract_cancel_window,
    "price_increase_right": price_increase_right,
    "expiry_soon": expiry_soon,
    "passport_before_permit": passport_before_permit,
    "followup_due": followup_due,
    "proof_missing": proof_missing,
    "please_check": please_check,
    "dunning_escalation": dunning_escalation,
    "scam_warning": scam_warning,
    "iban_misprint": iban_misprint,
    "tax_documents": tax_documents,
    "calendar_outdated": calendar_outdated,
    "confirm_cancellation": confirm_cancellation,
    STUDENT_PERMIT_RULE: student_permit_info,
}


# --------------------------------------------------------------------------------------------------
# running & persisting
# --------------------------------------------------------------------------------------------------


def run_triggers(store: Store, today: date) -> dict[str, list[Suggestion]]:
    """Evaluate every trigger against the store as of ``today`` (reads only).

    Returns ``{rule_id: [Suggestion, …]}`` for every rule (empty lists included); within a rule each
    fingerprint appears once.
    """
    ledger = Ledger(store, today)
    results: dict[str, list[Suggestion]] = {}
    for rule_id, trigger in TRIGGERS.items():
        unique = {idea.fingerprint: idea for idea in trigger(ledger)}
        results[rule_id] = list(unique.values())
    return results


@dataclass(frozen=True)
class TriggerRun:
    """Outcome of :func:`run_and_reconcile`."""

    live: int
    new: int
    expired: int
    by_rule: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        """JSON-friendly counts (for bus events and API responses)."""
        return {"live": self.live, "new": self.new, "expired": self.expired, "by_rule": dict(self.by_rule)}


def run_and_reconcile(store: Store, today: date) -> TriggerRun:
    """Run all triggers, upsert their Ideas and expire rule Ideas that no longer fire.

    ``new`` counts Ideas that were absent or expired before (the person sees them as new). The
    person's status on existing Ideas (dismissed, snoozed, accepted) is kept by the store. Publishes
    nothing — the caller announces ``suggestions.updated``.
    """
    results = run_triggers(store, today)
    live: list[str] = []
    new = 0
    with store.tx():
        for ideas in results.values():
            for idea in ideas:
                before = store.get_suggestion(idea.id)
                store.upsert_suggestion(idea)
                if before is None or before.status == "expired":
                    new += 1
                live.append(idea.fingerprint)
        expired = store.reconcile_suggestions(results.keys(), live)
    return TriggerRun(
        live=len(live),
        new=new,
        expired=expired,
        by_rule={rule_id: len(ideas) for rule_id, ideas in results.items()},
    )
