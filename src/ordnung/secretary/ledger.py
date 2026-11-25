"""The ledger's facts and the Idea helpers that the Ideas, the read models and Ask share.

The facts: :class:`Ledger` (one consistent snapshot of the store for one day) and its row cache, what an item
or a contract is on a day (active, its action day, overdue, decided, its area and computation), a letter's scam
signs, the cancellations sent and a health insurer's Zusatzbeitrag. The Idea helpers: :class:`IdeaText`,
:func:`make_idea`, :func:`english` and the small text helpers the triggers (:mod:`ordnung.secretary.triggers`),
the moving checklist (:mod:`ordnung.secretary.moving`) and the sender's Land (:mod:`ordnung.secretary.sender_land`)
build their Ideas with.

This module sits below the triggers, every read model and Ask. It builds on the store, the models, the rules
engine, the day parsers (:mod:`ordnung.days`), the proof of sending, the reading's attachment and link helpers
and the scam checks, none of which import it back.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import weakref
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from typing import TYPE_CHECKING, Any, cast

from ordnung.clock import now_iso
from ordnung.days import parse_day
from ordnung.db.store import Store
from ordnung.drafts.proof import (
    PROOF_SOURCE,
    RecordedAnswer,
    followup_item_id,
)
from ordnung.ids import content_id
from ordnung.ingest.attachments import attached_to, attachment_ids, is_email
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
from ordnung.rules import RuleContext, compute_contract, price_increase_window
from ordnung.rules.deadlines import postal_buffer
from ordnung.rules.explain import fmt_date

if TYPE_CHECKING:
    from ordnung.recurrence import ItemContext
    from ordnung.secretary.household import HouseholdMember

try:  # the scam checks are optional: the triggers work without them
    from ordnung.secretary import scam as _scam
except ImportError:  # pragma: no cover - only while the module is absent
    _scam = None  # type: ignore[assignment]

#: Item kinds that can be overdue (appointments and milestones simply pass; expiries have their own rule).
OVERDUE_KINDS = frozenset({"deadline", "payment", "task"})
IDENTITY_WINDOW_DAYS = 180
PERMIT_WINDOW_DAYS = 90
CALENDAR_META_KEY = "last_calendar_export_at"
#: The scam warning's rule (:func:`~ordnung.secretary.triggers.scam_warning`): the person dismisses it with
#: *I checked — it's genuine* (:attr:`Ledger.scam_checked`); Ask's ledger token watches its rows
#: (``db.store.LEDGER_SUGGESTION_RULES``).
SCAM_RULE = "scam_warning"

_DEFAULT_WINDOWS = {"deadline": 14, "payment": 7, "appointment": 2, "task": 3, "reminder": 0, "milestone": 7}
_DEFAULT_EXPIRY_WINDOW = 90
_PRIORITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "normal": 2, "low": 3}

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


# --------------------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------------------


def letter_day(doc: Document) -> date | None:
    """The day a letter is filed under by year (the tax year, the export's folders): the date printed on
    it, else the day it arrived (``None``: neither is known)."""
    return parse_day(doc.doc_date) or parse_day(doc.received_date)


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
    (a salary transfer showed as "Overdue")."""
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


@dataclass
class _Rows:
    """The rows a :class:`Ledger` reads, as of one state of the database: every letter once (in the
    trash and proof files too, by sender for the scam checks), the to-dos, contracts and parties, the scam
    warnings the person dismissed — and, once worked out, what depends on nothing else: each letter's scam
    warning signs and its reading, the letters the person checked, and which payment reminders took over
    which letters' payments."""

    profile: Profile
    documents: dict[str, Document]
    by_party: dict[str, list[Document]]
    items: list[Item]
    contracts: list[Contract]
    parties: list[Party]
    #: the fingerprints of the scam warnings the person dismissed (*I checked — it's genuine*)
    dismissed_scams: frozenset[str] = frozenset()
    scam_reasons: dict[str, list[str]] = field(default_factory=dict)
    scam_checked: frozenset[str] | None = None
    extractions: dict[str, DocumentExtraction | None] = field(default_factory=dict)
    covered: dict[str, Document] | None = None

    @classmethod
    def load(cls, store: Store) -> _Rows:
        with store.snapshot():
            every = store.list_documents(include_deleted=True)
            by_party: dict[str, list[Document]] = {}
            for doc in every:
                if doc.party_id:
                    by_party.setdefault(doc.party_id, []).append(doc)
            return cls(
                profile=store.get_profile(),
                # proof files belong to their letter (``drafts.proof``): they are no letters of the ledger
                documents={
                    doc.id: doc for doc in every if doc.deleted_at is None and doc.source != PROOF_SOURCE
                },
                by_party=by_party,
                items=store.list_items(),
                contracts=store.list_contracts(),
                parties=store.list_parties(),
                dismissed_scams=frozenset(
                    idea.fingerprint
                    for idea in store.list_suggestions(status="dismissed")
                    if idea.rule_id == SCAM_RULE and idea.source == "rule"
                ),
            )


class _RowsStore:
    """The store as the scam checks (:mod:`ordnung.secretary.scam`) read it, answered from :class:`_Rows`:
    a sender's letters (in the trash too), the parties and the profile. Any other read goes to the store."""

    def __init__(self, store: Store, rows: _Rows) -> None:
        self._store = store
        self._rows = rows

    def list_documents(self, *args: Any, **filters: Any) -> list[Document]:
        if not args and filters.keys() == {"party_id", "include_deleted"} and filters["include_deleted"]:
            return list(self._rows.by_party.get(filters["party_id"], ()))
        return self._store.list_documents(*args, **filters)

    def list_parties(self) -> list[Party]:
        return list(self._rows.parties)

    def get_profile(self) -> Profile:
        return self._rows.profile

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


class _RowsCache:
    """The rows last loaded from one store, shared by every Ledger built while the database stays as it
    was — the Ledgers of one request, and of the requests after it until something changes, in whichever
    of the API's threads they run.

    Whether it changed is :meth:`Store.commit_stamp`, which every thread compares alike: after a commit the
    first thread to look loads the rows once, under the lock, and the threads waiting there take them
    (each thread compared its own token before, so four threads after one change made four loads of a few
    seconds each at 3,000 letters). The stamp is read before the rows: rows newer than their stamp only
    cost one load too many. Inside a transaction, which may read what isn't committed, the rows are loaded
    afresh and not kept.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: _Rows | None = None
        self._stamp: tuple[int, int] | None = None
        self._loads = 0

    def rows(self, store: Store) -> _Rows:
        if store.commit_stamp() is None:  # inside a transaction
            return _Rows.load(store)
        with self._lock:
            # read again under the lock: a thread that waited here takes the rows the one before it loaded
            stamp = store.commit_stamp()
            if self._rows is None or stamp is None or stamp != self._stamp:
                self._rows = _Rows.load(store)
                self._stamp = stamp
                self._loads += 1
            return self._rows


_CACHES: weakref.WeakKeyDictionary[Store, _RowsCache] = weakref.WeakKeyDictionary()
_CACHES_LOCK = threading.Lock()


def _rows_of(store: Store) -> _Rows:
    with _CACHES_LOCK:
        cache = _CACHES.get(store)
        if cache is None:
            cache = _CACHES[store] = _RowsCache()
    return cache.rows(store)


class Ledger:
    """A read-only snapshot of the store as of ``today``. The rows are loaded once per state of the
    database (:class:`_RowsCache`), so the Ledgers of a request and of the requests after it share them;
    what depends on ``today`` is worked out per Ledger."""

    def __init__(self, store: Store, today: date) -> None:
        self.store = store
        self.today = today
        self._rows = _rows_of(store)
        self.profile = self._rows.profile
        self.documents: dict[str, Document] = dict(self._rows.documents)
        self.items: list[Item] = list(self._rows.items)
        self.contracts: list[Contract] = list(self._rows.contracts)
        self.parties: dict[str, Party] = {party.id: party for party in self._rows.parties}
        self._computations: dict[str, ContractComputation] = {}
        self._sent_drafts: list[Draft] | None = None
        self._attached: dict[str, Document] | None = None
        self._attachments: dict[str, list[Document]] | None = None
        self._proofs: dict[str, list[Proof]] | None = None
        self._replies: dict[str, Document | None] = {}
        self._call_notes: list[CallNote] | None = None
        self._price_windows: list[PriceIncreaseWindow] | None = None
        self._items_by_doc: dict[str, list[Item]] | None = None
        self._items_by_party: dict[str, list[Item]] | None = None

    @cached_property
    def tax_choices(self) -> dict[str, bool]:
        """The person's own "For taxes" choices by letter id (:meth:`Store.tax_choices`), for
        :func:`~ordnung.secretary.tax_choice.for_taxes`. Read on first use only, on purpose: of Ask's tools
        only ``get_document`` reads them, and the weekly review's snapshot does; Ask's other tools build Ledgers
        and never read the row."""
        return self.store.tax_choices()

    @cached_property
    def household_filed(self) -> dict[str, HouseholdMember]:
        """Each live letter the person filed for someone of their household, with that person
        (:func:`ordnung.secretary.household.filed`). Read on first use only, like :attr:`tax_choices`."""
        from ordnung.secretary import household

        return household.filed(household.load(self.store), self.documents)

    def member_of(self, doc_id: str | None) -> HouseholdMember | None:
        """The person of the household a letter is filed for (:attr:`household_filed`); ``None`` for the
        person's own letter, a letter in the trash and no letter at all."""
        return self.household_filed.get(doc_id) if doc_id else None

    def named_member(self, doc_id: str | None) -> HouseholdMember | None:
        """:meth:`member_of` for an Idea's words: ``None`` for a letter kept private too, since an Idea's title
        reaches Claude (the weekly review's existing Ideas and the daily note's new ones; ADR 0025)."""
        doc = self.document(doc_id)
        return None if doc is None or doc.ai_private else self.member_of(doc_id)

    @cached_property
    def _items_by_id(self) -> dict[str, Item]:
        return {item.id: item for item in self.items}

    def letters_of(self, refs: Iterable[SuggestionRef]) -> set[str]:
        """The letters an Idea refers to: its letters, each to-do's letter and the letter each of the person's
        own letters answers. A contract or a sender is no letter."""
        letters: set[str | None] = set()
        for ref in refs:
            if ref.type == "document":
                letters.add(ref.id)
            elif ref.type == "item":
                item = self._items_by_id.get(ref.id)
                letters.add(item.doc_id if item is not None else None)
            elif ref.type == "draft":
                draft = next((d for d in self.sent_drafts() if d.id == ref.id), None) or self.store.get_draft(
                    ref.id
                )
                letters.add(draft.doc_id if draft is not None else None)
        return {letter for letter in letters if letter}

    def idea_member(self, refs: Iterable[SuggestionRef]) -> HouseholdMember | None:
        """The person of the household an Idea is about: every letter it refers to (:meth:`letters_of`, at least
        one) is filed for them and none is private (:meth:`named_member`). Letters of two people, one of the
        person's own, a private one, or none: no one."""
        if not self.household_filed:
            return None
        people = [self.named_member(letter) for letter in self.letters_of(refs)]
        if not people or None in people or len({member.id for member in people if member}) != 1:
            return None
        return people[0]

    @cached_property
    def item_contexts(self) -> ItemContext:
        """The context of each to-do's dates (:func:`ordnung.ingest.plan.item_contexts`), worked out once per
        Ledger and shared by everything that answers from it."""
        from ordnung.ingest.plan import item_contexts

        return item_contexts()

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

    def items_of(self, doc_id: str) -> list[Item]:
        """A letter's to-dos, whatever their status, in ledger order (indexed once per Ledger: a page or the Ideas
        refresh that looks at every letter's to-dos never scans every to-do for each letter)."""
        if self._items_by_doc is None:
            self._items_by_doc = {}
            for item in self.items:
                if item.doc_id:
                    self._items_by_doc.setdefault(item.doc_id, []).append(item)
        return self._items_by_doc.get(doc_id, [])

    def items_of_party(self, party_id: str) -> list[Item]:
        """A sender's to-dos, whatever their status, in ledger order (indexed once per Ledger, as :meth:`items_of`)."""
        if self._items_by_party is None:
            self._items_by_party = {}
            for item in self.items:
                if item.party_id:
                    self._items_by_party.setdefault(item.party_id, []).append(item)
        return self._items_by_party.get(party_id, [])

    def actionable_items(self) -> list[Item]:
        """Active items that are safe to present as something to do (none :meth:`is_set_aside`)."""
        return [item for item in self.active_items() if not self.is_set_aside(item)]

    def is_set_aside(self, item: Item) -> bool:
        """An item that is never presented as something to do, whatever its status — on Today, in the
        weekly session, the calendar and its sync, the money figures: one of a letter with scam signs the
        person hasn't checked (:meth:`shows_scam_signs`), an invoice payment a later payment reminder took
        over (the reminder is the one to act on), or an e-mail's payment its attached bill repeats (the bill
        is the one to act on, or the reminder that took the bill over; it stays set aside after the bill is
        paid, so nothing asks for the money twice)."""
        return (
            self.is_suspicious_item(item)
            or self.is_superseded_by_reminder(item)
            or self.is_covered_by_attachment(item)
        )

    def covering_reminders(self) -> dict[str, Document]:
        """Letter id → the live payment reminder (Mahnung) that took over its payments (worked out once
        per state of the database).

        Worked out on read: only reminders that are not in the trash and show no scam signs (or ones the
        person checked, :meth:`shows_scam_signs`) count, whichever of the letters was read first.
        """
        if self._rows.covered is None:
            reminders = [
                doc
                for doc in self.documents.values()
                if doc.kind in PAYMENT_DEMAND_KINDS and not self.shows_scam_signs(doc)
            ]
            in_case: dict[str, list[Document]] = {}  # a reminder covers only letters of its own case
            for doc in self.documents.values():
                if doc.case_id:
                    in_case.setdefault(doc.case_id, []).append(doc)
            self._rows.covered = {
                doc.id: reminder
                for reminder in sorted(reminders, key=lambda d: (d.doc_date or "", d.created_at, d.id))
                for doc in in_case.get(reminder.case_id or "", [])
                if reminder_covers(reminder, doc)
            }
        return self._rows.covered

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
        """The live letters without scam signs (or with signs the person checked, :meth:`shows_scam_signs`) that
        came attached to ``email``: those it added (``source="email:<id>"``) and those Ordnung already had when
        it came (recorded ``known``). Worked out once per snapshot, for every e-mail."""
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
        return [doc for doc in self._attachments.get(email.id, []) if not self.shows_scam_signs(doc)]

    def covering_attachments(self) -> dict[str, Document]:
        """Payment to-do id of an e-mail → the attachment of that e-mail that asks for the same payment
        (cached; :func:`~ordnung.ingest.link.attachment_repeats`).

        Worked out on read: only attachments that are not in the trash and show no scam signs the person
        hasn't checked count (:meth:`attachments_of`), whichever of the letters was read first. An
        attachment's payments the e-mail itself took over as a payment reminder don't count: the one to act
        on must stay. So a reminder e-mail with its invoice attached keeps its own to-do (it takes the
        invoice's over, :meth:`covering_reminders`), and the two never set each other aside. A bill another
        reminder took over still counts, so the e-mail that repeats it stays set aside and that reminder is
        the one payment to act on.
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
        """The stored model extraction of a document (read once per state of the database)."""
        known = self._rows.extractions
        if doc_id not in known:
            known[doc_id] = self.store.get_extraction(doc_id)
        return known[doc_id]

    def sent_drafts(self) -> list[Draft]:
        """Letters marked as sent, newest first."""
        if self._sent_drafts is None:
            self._sent_drafts = self.store.list_drafts(status="sent")
        return self._sent_drafts

    def decided_contracts(self) -> set[str]:
        """Active contracts whose end is decided: a letter confirms their cancellation
        (:meth:`pending_confirmations`), or the person marked their own cancellation as sent
        (:func:`cancellations_sent`). Neither is a decision to make any more — no "decide by", no
        cancellation Idea, no send-by date in the calendar."""
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
        """The earliest live incoming letter without scam signs (or with signs the person checked), other
        than ``exclude``, dated (else received, else added) on or after ``since``, that is in thread
        ``case_id`` — or, when ``contract_id`` is given, confirms the cancellation of that contract."""
        found: list[tuple[str, str, Document]] = []
        for doc in self.documents.values():
            day = doc.doc_date or doc.received_date or doc.created_at[:10]
            if doc.id == exclude or doc.direction != "incoming" or (parse_day(day) or date.min) < since:
                continue
            threaded = case_id is not None and doc.case_id == case_id
            if not (threaded or (contract_id is not None and self._confirms(doc, contract_id))):
                continue
            if not self.shows_scam_signs(doc):
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

        Written policy: the earliest live incoming letter without scam signs (or with signs the person
        checked), other than the letter it answered, dated (else received, else added) on or after the day
        it was sent, that is in the same thread (:mod:`ordnung.ingest.link` threads letters by reference),
        or — for a cancellation of a contract — confirms the cancellation of that contract. Nothing is closed
        because of it (ADR 0006): the waiting entry and the follow-up Idea say which letter it was, and the
        person checks it.
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
        """Scam warning signs of an incoming letter (empty for outgoing letters and notes), the sender's
        earlier letters read from the shared rows. Worked out once per state of the database for the
        letter as the rows hold it; a copy read elsewhere (another version, one in the trash) each time."""
        if doc.direction != "incoming":
            return []
        party = self.parties.get(doc.party_id) if doc.party_id else None
        reads = cast(Store, _RowsStore(self.store, self._rows))
        held = self._rows.documents.get(doc.id)
        if held is not doc and held != doc:
            return _scam_reasons(reads, doc, party)
        known = self._rows.scam_reasons
        if doc.id not in known:
            known[doc.id] = _scam_reasons(reads, doc, party)
        return known[doc.id]

    def scam_signs(self, doc: Document) -> list[str]:
        """The warning signs a letter with scam signs shows — on its page and in its Idea, one list and one
        count (:func:`scam_signs`); empty for a letter without scam signs."""
        reasons = self.scam_reasons(doc)
        return scam_signs(doc, reasons) if reasons else []

    @property
    def scam_checked(self) -> frozenset[str]:
        """The live letters the person checked: they pressed *I checked — it's genuine*, which dismisses the
        letter's scam warning, and the letter still shows the signs that warning listed (the fingerprint the
        warning has now, :func:`scam_fingerprint`). A new sign makes a new warning, so the letter shows scam signs
        again until that one is dismissed too. Worked out once per state of the database."""
        rows = self._rows
        if rows.scam_checked is None:
            warned = {fingerprint.rsplit(":", 1)[0] for fingerprint in rows.dismissed_scams}
            rows.scam_checked = frozenset(
                doc.id
                for doc in rows.documents.values()
                if f"{SCAM_RULE}:{doc.id}" in warned and self._checked(doc)
            )
        return rows.scam_checked

    def _checked(self, doc: Document) -> bool:
        signs = self.scam_signs(doc)
        return bool(signs) and scam_fingerprint(doc.id, signs) in self._rows.dismissed_scams

    def shows_scam_signs(self, doc: Document) -> bool:
        """The letter shows scam signs (:meth:`scam_reasons`) the person hasn't checked (:attr:`scam_checked`).
        Whatever lists, counts, reminds or covers asks this: a checked letter's to-dos are to-dos again. The
        scam warning itself, the GiroCode gate (ADR 0012: a check never unlocks a code) and the letter's own
        record of its signs read :meth:`scam_reasons`."""
        if not self.scam_reasons(doc):
            return False
        held = self._rows.documents.get(doc.id)
        return not (doc.id in self.scam_checked if held is doc or held == doc else self._checked(doc))

    def is_suspicious_item(self, item: Item) -> bool:
        """Items of a letter with scam signs the person hasn't checked are never suggested as something to pay
        or do (:meth:`shows_scam_signs`)."""
        doc = self.document(item.doc_id)
        return doc is not None and self.shows_scam_signs(doc)

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


RESIDENCE_EXTENSION_LAW = "§ 81 Abs. 4 AufenthG"
"""Applying before a residence permit expires keeps it in force until the office decides."""
STUDENT_WORK_LAW = "§ 16b Abs. 3 AufenthG"
"""How much a student with a residence permit may work."""
REGISTRATION_LAW = "§ 17 Abs. 1 BMG"
"""Registering a new home within two weeks of moving in (the moving checklist, :mod:`ordnung.secretary.moving`)."""
IDEA_LAWS = (RESIDENCE_EXTENSION_LAW, STUDENT_WORK_LAW, REGISTRATION_LAW)
"""The § citations Ordnung's own Ideas state outside the rules catalog: Ask's check knows them like
the catalog's (ADR 0008), so a correct "§ 81 Abs. 4 AufenthG" is not taken for an unvouched law."""


def is_scam_warning(warning: str) -> bool:
    """A warning that says a letter may be a scam (its reading's, or the payment check's) — not one that
    only says an IBAN fails its checksum."""
    return any(word in warning.casefold() for word in _SCAM_WORDS) and not is_checksum_note(warning)


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
    r"in court), but Claude's reading|^Claude's reading of this letter left out"
    # the completeness re-ask's answer was used (ordnung.ingest.extract.REASK_WARNING)
    r"|^Claude's first answer for this letter left out",
    re.I,
)
HIDDEN_TEXT_SIGN = "The letter contains hidden text that you can't see on the page."


def scam_signs(doc: Document, reasons: Sequence[str]) -> list[str]:
    """Every warning sign of a letter with scam signs (``reasons``, :func:`_scam_reasons`, not empty), as
    its page and its Idea list them — one list, one count (the Idea said "5
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

    An IBAN that only fails its checksum is almost always a misprint or a misread digit (a scammer needs an
    account that works), so on its own it is no scam sign — :func:`~ordnung.secretary.triggers.iban_misprint`
    reports it calmly. Next to other signs it is listed as one more.
    """
    reasons: list[str] = []
    if doc.hidden_text:
        reasons.append(HIDDEN_TEXT_SIGN)
    reasons.extend(
        w
        for w in doc.warnings
        if is_scam_warning(w) and not (doc.hidden_text and _NOT_A_SIGN.search(w))  # hidden text is said once
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


def scam_fingerprint(doc_id: str, signs: Sequence[str]) -> str:
    """The fingerprint of a letter's scam warning (:func:`~ordnung.secretary.triggers.scam_warning`): the signs
    it lists, so a new sign makes a new warning, and a dismissed one (the person's check,
    :attr:`Ledger.scam_checked`) holds only for the signs the person saw."""
    return fingerprint(SCAM_RULE, doc_id, *sorted(signs))


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
