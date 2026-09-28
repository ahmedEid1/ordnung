"""Read models for the API: Today dashboard, timeline and life lanes (SPEC §13, §14).

Pure reads over a :class:`~ordnung.secretary.triggers.Ledger`: nothing here writes to the store.
Overdue is computed on read, contract dates are recomputed by the rules engine for ``today`` and
every list is sorted by stable keys so the same ledger always renders the same way.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from ordnung import clock
from ordnung.db.store import Store
from ordnung.models import (
    Area,
    AreaStatus,
    Contract,
    ContractComputation,
    Dashboard,
    DashboardStats,
    Document,
    Item,
    Lane,
    LaneBar,
    MoneySummary,
    MyNumbers,
    RefLink,
    Suggestion,
    TimelineEntry,
    TimelineMarker,
    WeeklySession,
)
from ordnung.numbers import NumbersInput, build_my_numbers
from ordnung.payments import is_collected_or_incoming, pays_on_site
from ordnung.rules.deadlines import sending_time_passed
from ordnung.rules.explain import fmt_date
from ordnung.secretary.brief import build_agenda
from ordnung.secretary.triggers import (
    Ledger,
    action_day,
    contract_area,
    day_label,
    expiry_class,
    is_decision,
    is_overdue,
    parse_day,
    priority_rank,
    was_history_when_filed,
)
from ordnung.secretary.week import build_weekly_session, pending_items, session_state
from ordnung.tick import local_today, simulated_day

ATTENTION_DAYS = 7
UPCOMING_DAYS = 30
DECISION_DAYS = 60
#: A life area's status follows the app's one urgency scale (``urgencyOf`` in ``web/src/lib/format.ts``):
#: overdue, today and tomorrow are urgent, the rest of the week needs attention. Direct debits, money
#: coming in and appointments never turn urgent — there is nothing to send (the web's ``cap: "warn"``).
URGENT_DAYS = 1
AREA_ATTENTION_DAYS = 7
RECENT_DOCUMENTS = 6
NOTICE_WINDOW_LEAD_DAYS = 30

#: The life areas' names, as ``AREA_COPY`` in ``web/src/lib/copy.ts`` says them. "residence" is the
#: residence-permit area: a flat, its rent and running costs are "home".
AREA_LABELS: dict[str, str] = {
    "residence": "Residence permit",
    "tax": "Tax",
    "study": "Study",
    "work": "Work",
    "home": "Home",
    "money": "Money",
    "health": "Health",
    "insurance": "Insurance",
    "mobility": "Getting around",
    "leisure": "Leisure",
    "family": "Family",
    "other": "Other",
}
AREA_ORDER: tuple[Area, ...] = (
    "residence",
    "tax",
    "study",
    "work",
    "home",
    "money",
    "health",
    "insurance",
    "mobility",
    "leisure",
    "family",
    "other",
)
LANE_ORDER: tuple[str, ...] = (
    "residence",
    "contracts",
    "tax",
    "study",
    "work",
    "home",
    "money",
    "health",
    "insurance",
    "mobility",
    "other",
)
_LANE_LABELS = {**AREA_LABELS, "contracts": "Contracts"}
_MARKER_KINDS = {
    "deadline": "deadline",
    "payment": "payment",
    "appointment": "appointment",
    "expiry": "expiry",
}
_TYPE_RANK = {"deadline": 0, "payment": 1, "expiry": 2, "appointment": 3, "contract": 4, "task": 5}

#: Letters about the home: the lease, the landlord's letters and statements, running costs and the
#: broadcasting fee (one per flat). The model sometimes reads them under "residence" — the
#: residence-permit area — so the read models show them and their to-dos under "home" (contracts:
#: :func:`~ordnung.secretary.triggers.contract_area`).
HOME_LETTER_KINDS = frozenset(
    {"rent_lease", "utility_bill", "landlord_notice", "rent_increase", "operating_costs", "broadcasting_fee"}
)
_HOME_PARTY_KINDS = frozenset({"landlord", "utility"})


# --------------------------------------------------------------------------------------------------
# life areas
# --------------------------------------------------------------------------------------------------


def _home_letter(ledger: Ledger, doc: Document | None) -> bool:
    if doc is None:
        return False
    party = ledger.parties.get(doc.party_id) if doc.party_id else None
    return doc.kind in HOME_LETTER_KINDS or (party is not None and party.kind in _HOME_PARTY_KINDS)


def document_area(ledger: Ledger, doc: Document) -> Area:
    """The life area a letter is shown under: its own, but a letter about the home is never shown under
    the residence permit (UI audit R1-backend-2)."""
    area: Area = doc.area or "other"
    return "home" if area == "residence" and _home_letter(ledger, doc) else area


def item_area(ledger: Ledger, item: Item) -> Area:
    """The life area a to-do is shown under: its own, but the rent or a back payment from a letter about
    the home is never shown under the residence permit."""
    if item.area == "residence" and _home_letter(ledger, ledger.document(item.doc_id)):
        return "home"
    return item.area


# --------------------------------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------------------------------


def _item_sort_key(item: Item, today: date) -> tuple[int, date, int, str]:
    day = action_day(item) or date.max
    return (0 if is_overdue(item, today) else 1, day, priority_rank(item.priority), item.id)


def _within(item: Item, today: date, first: int, last: int) -> bool:
    day = action_day(item)
    return day is not None and today + timedelta(days=first) <= day <= today + timedelta(days=last)


def _is_incoming_money(item: Item) -> bool:
    return item.kind == "payment" and item.direction == "in"


def _item_needs_check(item: Item) -> bool:
    """The item itself couldn't be confirmed against its letter (not merely a sibling in the letter)."""
    return item.grounding == "unverified" or any(not evidence.value_consistent for evidence in item.evidence)


def _needs_attention(item: Item, today: date, review_docs: set[str]) -> bool:
    if _is_incoming_money(item) or was_history_when_filed(item):
        return False  # money coming in, or dates that were already history when the letter was filed
    if is_overdue(item, today):
        return True
    due, act = parse_day(item.due_date), action_day(item)
    still_relevant = due is None or due >= today
    if item.doc_id in review_docs and still_relevant and _item_needs_check(item):
        return True
    return (
        due is not None and act is not None and due >= today and act <= today + timedelta(days=ATTENTION_DAYS)
    )


def _attention(ledger: Ledger) -> list[Item]:
    today = ledger.today
    review_docs = {doc.id for doc in ledger.documents.values() if doc.status == "needs_review"}
    chosen = [item for item in ledger.actionable_items() if _needs_attention(item, today, review_docs)]
    return sorted(chosen, key=lambda item: _item_sort_key(item, today))


def _upcoming(ledger: Ledger, shown: Iterable[Item]) -> list[Item]:
    today = ledger.today
    skip = {item.id for item in shown}
    chosen = [
        item
        for item in ledger.actionable_items()
        if item.id not in skip
        and (parse_day(item.due_date) or date.min) >= today
        and _within(item, today, 0, UPCOMING_DAYS)
    ]
    return sorted(chosen, key=lambda item: _item_sort_key(item, today))


def _decisions(ledger: Ledger) -> list[Contract]:
    today = ledger.today
    chosen: list[Contract] = []
    confirmed = ledger.pending_confirmations()
    for contract in ledger.active_contracts():
        if contract.id in confirmed:
            continue
        comp = ledger.computation(contract)
        send = parse_day(comp.send_by)
        if is_decision(comp) and send is not None and (send - today).days <= DECISION_DAYS:
            chosen.append(contract.model_copy(update={"computed": comp}))
    return sorted(chosen, key=lambda c: (c.computed.send_by if c.computed else "", c.id))


def _is_outgoing_payment(item: Item) -> bool:
    return item.kind == "payment" and item.direction != "in" and item.amount is not None


def payments_due_this_month(ledger: Ledger) -> list[Item]:
    """Open outgoing euro payments due in today's month (what ``due_this_month`` adds up)."""
    month_start = ledger.today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return [
        item
        for item in ledger.actionable_items()
        if _is_outgoing_payment(item)
        and (item.currency or "EUR").upper() == "EUR"
        and month_start <= (parse_day(item.due_date) or date.min) < next_month
    ]


def money_summary(
    ledger: Ledger,
    *,
    counts: Callable[[Item], bool] | None = None,
    counts_contract: Callable[[Contract], bool] | None = None,
) -> MoneySummary:
    """Euro payments due this month, fixed costs per month (active contracts; in euros, other currencies
    each summed on their own) and upcoming payments.

    ``counts`` / ``counts_contract`` leave to-dos and contracts out of the totals (Ask's record adds
    up only verified amounts); the list of upcoming payments stays complete.
    """
    today = ledger.today
    payments = [item for item in ledger.actionable_items() if _is_outgoing_payment(item)]
    # a sum in euros: a $50 invoice is not €50 of it (payments in other currencies stay in the list)
    due_this_month = sum(
        item.amount or 0.0 for item in payments_due_this_month(ledger) if counts is None or counts(item)
    )
    upcoming = sorted(
        (item for item in payments if _within(item, today, 0, UPCOMING_DAYS)),
        key=lambda item: _item_sort_key(item, today),
    )
    by_category: dict[str, float] = {}
    other_currencies: dict[str, float] = {}  # a $20 subscription is not €20 of the fixed costs
    for contract in ledger.active_contracts():
        monthly = contract.monthly_cost()
        if monthly is None or (counts_contract is not None and not counts_contract(contract)):
            continue
        currency = contract.cost_currency.upper()
        if currency == "EUR":
            by_category[contract.category] = round(by_category.get(contract.category, 0.0) + monthly, 2)
        else:
            other_currencies[currency] = round(other_currencies.get(currency, 0.0) + monthly, 2)
    return MoneySummary(
        due_this_month=round(due_this_month, 2),
        fixed_costs_monthly=round(sum(by_category.values()), 2),
        fixed_costs_monthly_other_currencies=dict(sorted(other_currencies.items())),
        upcoming_payments=upcoming,
        by_category=dict(sorted(by_category.items())),
    )


@dataclass(frozen=True, order=True)
class _AreaDate:
    day: date  # the day to act (a direct debit's or money coming in: the day it moves)
    what: str
    capped: bool = False  # nothing to send (an appointment, a payment nobody sends by bank): never urgent


@dataclass
class _AreaFacts:
    items: list[Item] = field(default_factory=list)
    dates: list[_AreaDate] = field(default_factory=list)
    overdue: list[Item] = field(default_factory=list)
    contracts: int = 0
    documents: int = 0


def _no_transfer(item: Item) -> bool:
    """A payment nobody sends by bank: a direct debit, money coming in, or paid in person on site."""
    return is_collected_or_incoming(item) or pays_on_site(item)


def _nothing_to_send(item: Item) -> bool:
    """A date to know, not to act by: an appointment, or a payment nobody sends by bank."""
    return item.kind == "appointment" or _no_transfer(item)


def area_day(item: Item) -> date | None:
    """The day a to-do is listed under in its life area: the day to act — but a payment nobody sends by
    bank (a direct debit, money coming in, a fee paid by card at the appointment) by its due day: its
    "send by" is a transfer's and means nothing there, as the to-do itself shows it (``isDirectDebit``
    in ``web/src/lib/payments.ts``, ``paysOnSite`` in ``web/src/features/document/item-meta.ts``)."""
    return parse_day(item.due_date) if _no_transfer(item) else action_day(item)


def _collect_areas(ledger: Ledger) -> dict[str, _AreaFacts]:
    today = ledger.today
    facts: dict[str, _AreaFacts] = {}
    for doc in ledger.documents.values():
        facts.setdefault(document_area(ledger, doc), _AreaFacts()).documents += 1
    for item in ledger.actionable_items():
        area = facts.setdefault(item_area(ledger, item), _AreaFacts())
        area.items.append(item)
        day = area_day(item)
        if is_overdue(item, today):
            area.overdue.append(item)
        elif day is not None and (parse_day(item.due_date) or day) >= today:
            area.dates.append(_AreaDate(max(day, today), item.title, _nothing_to_send(item)))
    for contract in ledger.active_contracts():
        area = facts.setdefault(contract_area(contract), _AreaFacts())
        area.contracts += 1
        comp = ledger.computation(contract)
        send = parse_day(comp.send_by)
        if is_decision(comp) and send is not None:
            area.dates.append(_AreaDate(send, f"Decide on {contract.name}"))
    return facts


_STATUS_RANK = {"ok": 0, "attention": 1, "urgent": 2}


def _date_status(entry: _AreaDate, today: date) -> str:
    days = (entry.day - today).days
    if days <= URGENT_DAYS and not entry.capped:
        return "urgent"
    return "attention" if days <= AREA_ATTENTION_DAYS else "ok"


def _area_status(area: Area, facts: _AreaFacts, today: date) -> AreaStatus:
    upcoming = sorted(facts.dates)
    first = upcoming[0] if upcoming else None
    # overdue is urgent; else the loudest of its dates (a direct debit tomorrow only needs attention)
    levels = ["urgent"] if facts.overdue else [_date_status(entry, today) for entry in upcoming]
    status = max(levels, key=_STATUS_RANK.__getitem__, default="ok")
    if facts.overdue:
        headline = f"Overdue: {facts.overdue[0].title}"
    elif first is not None:
        headline = f"{first.what} — {day_label(first.day, today)}"
    elif facts.contracts:
        headline = f"{facts.contracts} active contract{'s' if facts.contracts != 1 else ''}"
    else:
        headline = f"{facts.documents} letter{'s' if facts.documents != 1 else ''}, nothing due"
    return AreaStatus.model_validate(
        {
            "area": area,
            "label": AREA_LABELS[area],
            "status": status,
            "headline": headline,
            "next_date": first.day.isoformat() if first else None,
            "count": len(facts.items),
        }
    )


def area_statuses(ledger: Ledger) -> list[AreaStatus]:
    """Life at a glance: one status per area that has letters, open items or contracts."""
    facts = _collect_areas(ledger)
    return [_area_status(area, facts[area], ledger.today) for area in AREA_ORDER if area in facts]


def grounding_ratio(items: Iterable[Item]) -> float:
    """Share of extracted items whose evidence was found in the letter or confirmed by the person."""
    extracted = [item for item in items if item.origin == "extracted" and item.evidence]
    if not extracted:
        return 0.0
    grounded = sum(1 for item in extracted if item.grounding in ("verified", "user"))
    return round(grounded / len(extracted), 3)


def _new_ideas(store: Store, today: date) -> list[Suggestion]:
    ideas = [
        idea
        for idea in store.list_suggestions(status=("new", "snoozed"))
        if idea.status == "new" or (parse_day(idea.snoozed_until) or date.max) <= today
    ]
    return sorted(ideas, key=lambda idea: (priority_rank(idea.priority), idea.due_date or "9999", idea.id))


def recent_letter_key(doc: Document) -> tuple[str, str]:
    """Recent letters newest first by the day each one is listed under: when it arrived, else its own
    date, else when it was added (the day the Today page shows, so 20 Sep never lists above 21 Sep)."""
    return (doc.received_date or doc.doc_date or doc.created_at[:10], doc.id)


def dashboard(store: Store, today: date) -> Dashboard:
    """The Today page: attention (overdue, due within 7 days, needs review), coming up (8–30 days),
    decisions (contracts with send-by within 60 days), money, life areas, new Ideas, recent letters
    and ledger stats."""
    ledger = Ledger(store, today)
    attention = _attention(ledger)
    counts = store.counts()
    first_name = ledger.profile.name.split()[0] if ledger.profile.name.strip() else ""
    recent = sorted(ledger.documents.values(), key=recent_letter_key, reverse=True)[:RECENT_DOCUMENTS]
    return Dashboard(
        today=today.isoformat(),
        greeting_name=first_name,
        simulated=clock.simulated() or simulated_day(store) is not None,
        attention=attention,
        upcoming=_upcoming(ledger, attention),
        decisions=_decisions(ledger),
        money=money_summary(ledger),
        areas=area_statuses(ledger),
        suggestions=_new_ideas(store, today),
        recent_documents=recent,
        stats=DashboardStats(
            documents=counts.get("documents", 0),
            open_items=counts.get("open_items", 0),
            contracts=counts.get("active_contracts", 0),
            parties=counts.get("parties", 0),
            verified_ratio=grounding_ratio(ledger.items),
        ),
    )


# --------------------------------------------------------------------------------------------------
# timeline
# --------------------------------------------------------------------------------------------------


def _document_entries(ledger: Ledger) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []
    for doc in ledger.documents.values():
        day = doc.doc_date or doc.received_date or doc.created_at[:10]
        entries.append(
            TimelineEntry.model_validate(
                {
                    "id": doc.id,
                    "date": day,
                    "type": "document",
                    "title": doc.title or doc.filename,
                    "subtitle": doc.summary,
                    "status": doc.status,
                    "priority": doc.urgency or "normal",
                    "area": document_area(ledger, doc),
                    "ref": RefLink(type="document", id=doc.id),
                    "party_name": ledger.party_name(doc.party_id),
                }
            )
        )
    return entries


def _item_entries(ledger: Ledger) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []
    for item in ledger.items:
        if item.due_date is None or item.status == "dismissed":
            continue
        status = "overdue" if is_overdue(item, ledger.today) else item.status
        # a fee paid by card at the appointment has no day to transfer by: its own words say how to pay
        send_by = None if pays_on_site(item) else item.send_by
        subtitle = (
            # the usual time to post has passed: a letter posted today may arrive too late (review round 4)
            f"Must arrive by {day_label(parse_day(item.due_date) or ledger.today, ledger.today)}"
            if send_by and sending_time_passed(item.computation)
            else f"Send by {day_label(parse_day(send_by) or ledger.today, ledger.today)}"
            if send_by
            else None
        )
        # a scam letter's demand is no bill: no amount (it isn't "to pay") and no "send by"
        suspicious = ledger.is_suspicious_item(item)
        if suspicious:
            subtitle = "Possible scam — don't pay before you've checked with the sender"
        entries.append(
            TimelineEntry.model_validate(
                {
                    "id": item.id,
                    "date": item.due_date,
                    "time": item.due_time,
                    "type": item.kind,
                    "title": item.title,
                    "subtitle": subtitle or item.action,
                    "status": status,
                    "priority": "normal" if suspicious else item.priority,
                    "area": item_area(ledger, item),
                    "ref": RefLink(type="item", id=item.id),
                    "party_name": ledger.party_name(item.party_id),
                    "amount": None if suspicious else item.amount,
                    "currency": None if suspicious else item.currency,
                }
            )
        )
    return entries


def _contract_entry(contract: Contract, key: str, day: str, title: str, ledger: Ledger) -> TimelineEntry:
    return TimelineEntry.model_validate(
        {
            "id": f"{contract.id}:{key}",
            "date": day,
            "type": "contract",
            "title": title,
            "status": contract.status,
            "priority": "high" if key in ("send_by", "cancel_by") else "normal",
            "area": contract_area(contract),
            "ref": RefLink(type="contract", id=contract.id),
            "party_name": ledger.party_name(contract.party_id),
        }
    )


def _contract_entries(ledger: Ledger) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []
    for contract in ledger.contracts:
        if contract.status != "active":
            if contract.end_date:
                entries.append(
                    _contract_entry(contract, "end", contract.end_date, f"{contract.name} ends", ledger)
                )
            continue
        comp = ledger.computation(contract)
        if is_decision(comp) and comp.send_by and comp.cancel_by:
            name = contract.name
            entries.append(
                _contract_entry(contract, "send_by", comp.send_by, f"Send the cancellation of {name}", ledger)
            )
            entries.append(
                _contract_entry(
                    contract, "cancel_by", comp.cancel_by, f"Cancellation of {name} must arrive", ledger
                )
            )
        if comp.current_term_end:
            entries.append(
                _contract_entry(
                    contract, "term_end", comp.current_term_end, f"{contract.name}: term ends", ledger
                )
            )
    return entries


def _draft_entries(store: Store, ledger: Ledger) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []
    for draft in store.list_drafts(status="sent"):
        if not draft.sent_at:
            continue
        entries.append(
            TimelineEntry.model_validate(
                {
                    "id": draft.id,
                    "date": draft.sent_at[:10],
                    "type": "draft",
                    "title": f"Sent: {draft.subject or draft.kind.replace('_', ' ')}",
                    "subtitle": draft.sent_channel,
                    "status": draft.status,
                    "ref": RefLink(type="draft", id=draft.id),
                    "party_name": ledger.party_name(draft.party_id),
                }
            )
        )
    return entries


def timeline(store: Store, start: date, end: date, *, today: date | None = None) -> list[TimelineEntry]:
    """Everything dated between ``start`` and ``end`` (inclusive): letters by their date, to-dos by
    due date, contract milestones (send-by, must-arrive-by, term end) and sent letters.

    ``past`` is relative to ``today`` (default: the person's today, :func:`ordnung.tick.local_today`).
    """
    day = today or local_today(store)
    ledger = Ledger(store, day)
    everything = [
        *_document_entries(ledger),
        *_item_entries(ledger),
        *_contract_entries(ledger),
        *_draft_entries(store, ledger),
    ]
    first, last = start.isoformat(), end.isoformat()
    chosen = [entry for entry in everything if first <= entry.date <= last]
    for entry in chosen:
        entry.past = entry.date < day.isoformat()
    return sorted(chosen, key=lambda e: (e.date, e.time or "", _TYPE_RANK.get(e.type, 9), e.title, e.id))


# --------------------------------------------------------------------------------------------------
# life lanes
# --------------------------------------------------------------------------------------------------


@dataclass
class _Lanes:
    start: date
    end: date
    today: date
    bars: dict[str, list[LaneBar]] = field(default_factory=dict)
    markers: dict[str, list[TimelineMarker]] = field(default_factory=dict)

    def bar(self, lane: str, bar: LaneBar) -> None:
        first, last = parse_day(bar.start), parse_day(bar.end)
        if first is None or last is None or last < self.start or first > self.end or last < first:
            return
        clipped = max(first, self.start).isoformat(), min(last, self.end).isoformat()
        markers = [m for m in bar.markers if self.start.isoformat() <= m.date <= self.end.isoformat()]
        self.bars.setdefault(lane, []).append(
            bar.model_copy(update={"start": clipped[0], "end": clipped[1], "markers": markers})
        )

    def marker(self, lane: str, marker: TimelineMarker) -> None:
        if self.start.isoformat() <= marker.date <= self.end.isoformat():
            self.markers.setdefault(lane, []).append(marker)

    def build(self) -> list[Lane]:
        lanes: list[Lane] = []
        for lane_id in LANE_ORDER:
            bars = sorted(self.bars.get(lane_id, []), key=lambda b: (b.start, b.end, b.id))
            markers = sorted(self.markers.get(lane_id, []), key=lambda m: (m.date, m.label))
            if bars or markers:
                area = lane_id if lane_id in AREA_LABELS else "other"
                lanes.append(
                    Lane.model_validate(
                        {
                            "id": lane_id,
                            "label": _LANE_LABELS[lane_id],
                            "area": area,
                            "bars": bars,
                            "markers": markers,
                        }
                    )
                )
        return lanes


def _status_for(day: date, today: date, urgent_days: int, attention_days: int) -> str:
    days = (day - today).days
    if days < 0:
        return "past"
    if days <= urgent_days:
        return "urgent"
    return "attention" if days <= attention_days else "ok"


def _marker(
    day: str, label: str, kind: str, *, area: Area | None = None, ref: RefLink | None = None
) -> TimelineMarker:
    return TimelineMarker.model_validate(
        {"date": day, "label": label, "kind": kind, "area": area, "ref": ref}
    )


def _item_marker(item: Item, area: Area) -> TimelineMarker:
    return _marker(
        item.due_date or "",
        item.title,
        _MARKER_KINDS.get(item.kind, "other"),
        area=area,
        ref=RefLink(type="item", id=item.id),
    )


def _residence_bar(ledger: Ledger, item: Item, klass: str, lanes: _Lanes) -> None:
    expiry = parse_day(item.due_date)
    if expiry is None:
        return
    doc = ledger.document(item.doc_id)
    start = parse_day(doc.doc_date) if doc else None
    permit = klass == "permit"
    ref = RefLink(type="item", id=item.id)
    markers = [_marker(expiry.isoformat(), "Expires", "expiry", area="residence", ref=ref)]
    if permit:
        markers.insert(
            0,
            _marker(
                expiry.isoformat(),
                "Apply before this date (§ 81 Abs. 4 AufenthG)",
                "deadline",
                area="residence",
                ref=ref,
            ),
        )
    lanes.bar(
        "residence",
        LaneBar.model_validate(
            {
                "id": item.id,
                "label": "Residence permit" if permit else item.title,
                "start": (start or lanes.start).isoformat(),
                "end": expiry.isoformat(),
                "kind": "validity",
                "status": _status_for(expiry, ledger.today, 30, 90 if permit else 180),
                "markers": markers,
                "ref": ref,
                "area": "residence",
            }
        ),
    )


def _tax_bar(ledger: Ledger, item: Item, lanes: _Lanes) -> None:
    due = parse_day(item.due_date)
    doc = ledger.document(item.doc_id)
    start = (parse_day(doc.doc_date) if doc else None) or parse_day(item.created_at) or due
    if due is None or start is None:
        return
    ref = RefLink(type="item", id=item.id)
    markers = [_marker(due.isoformat(), "Must arrive by", "deadline", area="tax", ref=ref)]
    if item.send_by:
        markers.insert(0, _marker(item.send_by, "Send by", "send_by", area="tax", ref=ref))
    lanes.bar(
        "tax",
        LaneBar.model_validate(
            {
                "id": item.id,
                "label": item.title,
                "start": start.isoformat(),
                "end": due.isoformat(),
                "kind": "period",
                "status": "past"
                if item.status != "open" and due < ledger.today
                else _status_for(due, ledger.today, 7, 30),
                "markers": markers,
                "ref": ref,
                "area": "tax",
            }
        ),
    )


def _route_item(ledger: Ledger, item: Item, lanes: _Lanes) -> None:
    """Each dated item goes to exactly one lane — its life area's (bars for validity and objection
    windows); every bar and marker says its area and to-do, so the lanes can be filtered and opened."""
    area = item_area(ledger, item)
    if item.kind == "expiry" and area == "residence":
        klass = expiry_class(item, ledger.document(item.doc_id))
        if klass in ("permit", "identity"):
            _residence_bar(ledger, item, klass, lanes)
            return
    if area == "tax" and item.kind == "deadline":
        _tax_bar(ledger, item, lanes)
        return
    # payments too, whatever the amount: the rent in Home, the Deutschlandticket in Getting around
    lanes.marker(area if area in LANE_ORDER else "other", _item_marker(item, area))


#: Regimes under which a contract that isn't cancelled simply runs on, cancellable at any time.
_ROLLING_REGIMES = frozenset({"bgb309_new", "tkg56", "stromgvv20", "sgbv175"})


def renews_for_a_term(contract: Contract, comp: ContractComputation) -> bool:
    """Whether an uncancelled contract really renews for a fixed term (otherwise it runs on and can be
    cancelled at any time with its notice period — § 309 Nr. 9 BGB since 2022, § 56 TKG, …)."""
    return comp.regime not in _ROLLING_REGIMES and bool(contract.renewal_term_months)


_FIXED_TERM_CAVEATS = {
    "employment622": (
        " If you keep working after that with the employer's knowledge and the employer does not object "
        "without delay, it continues with no fixed term (§ 15 Abs. 6 TzBfG)."
    ),
    "rent573c": (
        " If you keep living there after that and neither side objects within two weeks, it continues "
        "with no fixed term (§ 545 BGB) — unless the lease excludes that rule, as many leases do."
    ),
}
"""What turns a fixed-term employment or tenancy into an open-ended one — by conduct, not by doing
nothing (§ 15 Abs. 1 and 6 TzBfG, § 545 BGB)."""
_FIXED_TERM_NOTICE = {
    "employment622": (
        " A fixed-term job ends then by itself, with no notice (§ 15 Abs. 1 TzBfG). Ending it earlier by "
        "ordinary notice needs a notice clause in the contract or a collective agreement (§ 15 Abs. 4 TzBfG) "
        "— many have one, for example after the probation period; without one it can still end earlier by "
        "a written agreement with the employer (§ 623 BGB), or for a serious reason by notice without a "
        "notice period (§ 626 BGB). If you may claim unemployment benefit afterwards, register as "
        "job-seeking with the Agentur für Arbeit at least 3 months before it ends, or within 3 days of "
        "learning the end date if that is later (§ 38 Abs. 1 SGB III); registering late can block the "
        "benefit for a week (§ 159 Abs. 6 SGB III)."
    ),
    "rent573c": (
        " A flat let for a fixed term usually counts as open-ended unless the landlord gave one of the legal "
        "reasons for the fixed term in writing when it was signed (§ 575 Abs. 1 BGB). If it counts as "
        "open-ended, leaving needs notice like any open-ended lease (§ 573c BGB) — but courts often read the "
        "agreed end date as both sides giving up ordinary notice until then (BGH, 10 Jul 2013, VIII ZR "
        "388/12), so ending it earlier may not be possible; check the contract or get advice. Exceptions "
        "include a "
        "room in a student or youth hall of residence, a flat let only for temporary use, a furnished room "
        "in the landlord's own flat that is not let for lasting use with a family or partner, and housing a "
        "public body or welfare organisation rents to pass on to people in urgent need (§ 549 Abs. 2 and 3 "
        "BGB): there a fixed term ends by itself. So check the contract before relying on the end date."
    ),
}
"""What the end date of a fixed-term job or flat let means. A job ends by itself on its date (§ 15 Abs. 1
TzBfG); ending it *earlier* by ordinary notice needs an agreed notice clause (§ 15 Abs. 4 TzBfG) — a
written termination agreement (§ 623 BGB) or notice for cause (§ 626 BGB) end it early without one —, and
everyone whose job ends must register as job-seeking 3 months before the end (§ 38 Abs. 1 SGB III; not in
a company apprenticeship); for whoever then claims unemployment benefit, a late registration costs a
one-week block (§ 159 Abs. 1 S. 2 Nr. 9 and Abs. 6 SGB III), so the text the person reads puts it as
advice for that case. A flat let's fixed term usually needs a written legal reason, or the lease counts
as open-ended and leaving needs notice (§ 575 Abs. 1 S. 2 BGB) — though courts often read the agreed end
date as a mutual waiver of ordinary notice until then (BGH, 10 Jul 2013, VIII ZR 388/12), so leaving
earlier may not be possible — except where § 575 does not apply (§ 549 Abs. 2 and 3 BGB: student
or youth halls, temporary use, a furnished room in the landlord's flat not let for lasting use with a
family or partner, housing a public body or welfare organisation lets on to people in urgent need). The
rules engine reads none of these clauses (it applies ``fixed_term`` to every such contract with an end
date), so for a flat let Ask's record says notice may still be needed; the engine's own summary for a
flat let says so too (``rules/explain.py``, :func:`~ordnung.rules.explain.contract_fixed_end_sentence`)."""


_FIXED_TERM_PAST = {
    "employment622": (
        " If you still work there with the employer's knowledge and the employer did not object without "
        "delay, the job continues with no fixed term (§ 15 Abs. 6 TzBfG); if you stopped working then, it "
        "ended on that date."
    ),
    "rent573c": (
        " If you still live there, the lease may not have ended: a flat let whose fixed term has no legal "
        "reason given in writing counts as open-ended from the start (§ 575 Abs. 1 S. 2 BGB), and a lease used "
        "on after its end continues with no fixed term unless a side objected within two weeks (§ 545 BGB) — "
        "unless the lease excludes that rule. Check the contract or get advice."
    ),
}
"""What a passed end date means for an active fixed-term job or flat let: it may never have ended, or it
may continue by conduct (§ 575 Abs. 1 S. 2 and § 545 BGB, § 15 Abs. 6 TzBfG) — never simply "ended"."""


def continuation(contract: Contract, comp: ContractComputation, *, today: date | None = None) -> str:
    """What happens if the contract is not cancelled, in plain words.

    A fixed-term contract (the rules engine applied ``fixed_term``) ends by itself on its end date — for
    employment and tenancies with what :data:`_FIXED_TERM_NOTICE` says (ending a job earlier needs an
    agreed notice clause; a flat let may count as open-ended) and what :data:`_FIXED_TERM_CAVEATS` says
    turns it into an open-ended one by conduct; once that date has passed, a job or flat let may still
    run (:data:`_FIXED_TERM_PAST`). Otherwise it either renews for a fixed term or runs on, cancellable at
    any time.
    """
    end = parse_day(comp.current_term_end) if "fixed_term" in comp.rule_ids else None
    if end is not None:
        if today is not None and end < today:
            if comp.regime in _FIXED_TERM_PAST:
                return (
                    f"Its fixed term's end date, {fmt_date(end)}, has passed.{_FIXED_TERM_PAST[comp.regime]}"
                )
            return f"Its fixed term ended on {fmt_date(end)}."
        if comp.regime in _FIXED_TERM_NOTICE:
            notice, caveat = _FIXED_TERM_NOTICE[comp.regime], _FIXED_TERM_CAVEATS[comp.regime]
            return f"Its fixed term ends on {fmt_date(end)}.{notice}{caveat}"
        return f"It ends by itself on {fmt_date(end)}; no cancellation is needed."
    if not renews_for_a_term(contract, comp):
        return "It continues with no fixed term and can then be cancelled at any time with its notice period."
    months = contract.renewal_term_months
    return f"It renews for {months} months unless it is cancelled in time."


def fixed_term_summary(comp: ContractComputation, *, today: date, active: bool = True) -> str | None:
    """The summary Ask's record gives a fixed-term job or flat let instead of the engine's (``None``: keep
    the engine's): a job ends by itself on its date (§ 15 Abs. 1 TzBfG), a flat let may still need
    notice (:data:`_FIXED_TERM_NOTICE`); both point to ``if_not_cancelled`` for the rest. Once the end
    date has passed, an ``active`` one may still run (:data:`_FIXED_TERM_PAST`) — never the engine's
    "This contract ended on …"."""
    end = parse_day(comp.current_term_end) if "fixed_term" in comp.rule_ids else None
    if end is None or comp.regime not in _FIXED_TERM_NOTICE:
        return None
    if end < today:
        if not active:
            return None
        if comp.regime == "employment622":
            return (
                f"This job's fixed-term end date, {fmt_date(end)}, has passed: if you still work there, it may "
                "continue with no fixed term (§ 15 Abs. 6 TzBfG) — see if_not_cancelled."
            )
        return (
            f"This flat let's fixed-term end date, {fmt_date(end)}, has passed: if you still live there, it may "
            "not have ended (§ 575 Abs. 1 S. 2 BGB, § 545 BGB) — see if_not_cancelled."
        )
    if comp.regime == "employment622":
        return (
            f"This job's fixed term ends on {fmt_date(end)}: it ends then by itself, with no notice (§ 15 Abs. 1 "
            "TzBfG) — see if_not_cancelled for ending it earlier, for registering as job-seeking and for what "
            "makes it open-ended."
        )
    return (
        f"This contract's fixed term ends on {fmt_date(end)}; it may still need notice to end then — see "
        "if_not_cancelled."
    )


def _continuation_label(contract: Contract, comp: ContractComputation) -> str:
    """What happens on ``next_renewal``: a real renewal for a fixed term, or running on month by month."""
    if not renews_for_a_term(contract, comp):
        return "Continues · cancel any time"
    months = contract.renewal_term_months
    return f"Renews for {months} months" if months != 12 else "Renews for a year"


def _contract_bars(ledger: Ledger, contract: Contract, lanes: _Lanes) -> None:
    comp = ledger.computation(contract)
    today = ledger.today
    begin = parse_day(contract.start_date) or parse_day(contract.concluded_date) or lanes.start
    known_end = parse_day(comp.current_term_end) or parse_day(contract.end_date)
    finish = known_end or lanes.end
    employment = contract.category == "employment"
    lane = "work" if employment else "contracts"
    area = contract_area(contract)
    ref = RefLink(type="contract", id=contract.id)
    markers = []
    if comp.next_renewal:
        label = _continuation_label(contract, comp)
        markers.append(_marker(comp.next_renewal, label, "renewal", area=area, ref=ref))
    send, cancel = parse_day(comp.send_by), parse_day(comp.cancel_by)
    decision = is_decision(comp) and send is not None and cancel is not None
    lanes.bar(
        lane,
        LaneBar.model_validate(
            {
                "id": contract.id,
                "label": contract.name,
                "start": begin.isoformat(),
                "end": max(finish, begin).isoformat(),
                "kind": "contract",
                "status": _status_for(send, today, 14, DECISION_DAYS) if decision and send else "ok",
                "markers": markers,
                "ref": ref,
                "area": area,
                "open_end": known_end is None,
            }
        ),
    )
    if not decision or send is None or cancel is None:
        return
    lanes.bar(
        lane,
        LaneBar.model_validate(
            {
                "id": f"{contract.id}:notice",
                "label": f"{contract.name}: notice window",
                "start": (send - timedelta(days=NOTICE_WINDOW_LEAD_DAYS)).isoformat(),
                "end": cancel.isoformat(),
                "kind": "notice_window",
                "status": _status_for(send, today, 14, DECISION_DAYS),
                "markers": [
                    _marker(send.isoformat(), "Send by", "send_by", area=area, ref=ref),
                    _marker(cancel.isoformat(), "Must arrive by", "cancel_by", area=area, ref=ref),
                ],
                "ref": ref,
                "area": area,
            }
        ),
    )


def lanes(store: Store, start: date, end: date, *, today: date | None = None) -> list[Lane]:
    """Year-ahead life lanes between ``start`` and ``end``: Residence permit (permit and passport
    validity, "apply before" marker), Contracts (term bars, notice windows with send-by/must-arrive-by
    markers), Tax (objection windows), Study, Work (employment term), Home, Money, Health, Insurance,
    Getting around, Other — each dated to-do in its life area's lane, payments of any amount too. Only
    lanes with data, in that order; bars are clipped to the range (``open_end``: a contract with no end
    date). Every bar and marker carries its life area and the to-do or contract it stands for."""
    day = today or local_today(store)
    ledger = Ledger(store, day)
    collected = _Lanes(start=start, end=end, today=day)
    for item in ledger.items:
        if item.due_date is not None and item.status != "dismissed" and not ledger.is_suspicious_item(item):
            _route_item(ledger, item, collected)
    for contract in ledger.active_contracts():
        _contract_bars(ledger, contract, collected)
    return collected.build()


# --------------------------------------------------------------------------------------------------
# My numbers and the weekly session
# --------------------------------------------------------------------------------------------------


def my_numbers(store: Store, today: date, *, shareable_only: bool = False) -> MyNumbers:
    """The *My numbers* page (:mod:`ordnung.numbers`) over a snapshot of the ledger.

    ``shareable_only`` leaves out letters marked "Keep private — no AI" and their to-dos (Ask's tool,
    ADR 0006): a private letter's to-do is never a case's next step there.
    """
    ledger = Ledger(store, today)
    private = {doc.id for doc in ledger.documents.values() if shareable_only and doc.ai_private}
    documents = [doc for doc in ledger.documents.values() if doc.id not in private]
    items = [item for item in ledger.items if item.doc_id not in private]
    return build_my_numbers(
        NumbersInput(
            today=today,
            documents=documents,
            parties=ledger.parties,
            cases={case.id: case for case in store.list_cases()},
            items=items,
            open_items=[item for item in pending_items(ledger) if item.doc_id not in private],
            extractions={doc.id: ledger.extraction(doc.id) for doc in documents},
            suspicious=frozenset(doc.id for doc in documents if ledger.scam_reasons(doc)),
            expiry_classes={
                item.id: expiry_class(item, ledger.document(item.doc_id))
                for item in items
                if item.kind == "expiry"
            },
            own_iban=ledger.profile.iban or None,
        )
    )


def weekly_session(store: Store, today: date) -> WeeklySession:
    """The weekly admin session (:mod:`ordnung.secretary.week`): the agenda of
    :func:`~ordnung.secretary.brief.build_agenda`, the money summary and the ledger's letters, drafts
    and to-dos, arranged as seven steps."""
    ledger = Ledger(store, today)
    return build_weekly_session(
        ledger,
        agenda=build_agenda(store, today),
        money=money_summary(ledger),
        drafts=store.list_drafts(),
        state=session_state(store),
    )
