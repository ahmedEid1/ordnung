"""Read models for the API: Today dashboard, timeline and life lanes (SPEC §13, §14).

Pure reads over a :class:`~ordnung.secretary.triggers.Ledger`: nothing here writes to the store.
Overdue is computed on read, contract dates are recomputed by the rules engine for ``today`` and
every list is sorted by stable keys so the same ledger always renders the same way.
"""

from __future__ import annotations

from collections.abc import Iterable
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
    Item,
    Lane,
    LaneBar,
    MoneySummary,
    RefLink,
    Suggestion,
    TimelineEntry,
    TimelineMarker,
)
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
from ordnung.tick import local_today, simulated_day

ATTENTION_DAYS = 7
UPCOMING_DAYS = 30
DECISION_DAYS = 60
URGENT_DAYS = 3
AREA_ATTENTION_DAYS = 14
RECENT_DOCUMENTS = 6
LARGE_PAYMENT_EUR = 50.0
NOTICE_WINDOW_LEAD_DAYS = 30

AREA_LABELS: dict[str, str] = {
    "residence": "Residence",
    "tax": "Tax",
    "study": "Study",
    "work": "Work",
    "home": "Home",
    "money": "Money",
    "health": "Health",
    "insurance": "Insurance",
    "mobility": "Mobility",
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


def money_summary(ledger: Ledger) -> MoneySummary:
    """Euro payments due this month, fixed costs per month (active contracts; in euros, other currencies
    each summed on their own) and upcoming payments."""
    today = ledger.today
    month_start = today.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    payments = [item for item in ledger.actionable_items() if _is_outgoing_payment(item)]
    # a sum in euros: a $50 invoice is not €50 of it (payments in other currencies stay in the list)
    due_this_month = sum(
        item.amount or 0.0
        for item in payments
        if (item.currency or "EUR").upper() == "EUR"
        and month_start <= (parse_day(item.due_date) or date.min) < next_month
    )
    upcoming = sorted(
        (item for item in payments if _within(item, today, 0, UPCOMING_DAYS)),
        key=lambda item: _item_sort_key(item, today),
    )
    by_category: dict[str, float] = {}
    other_currencies: dict[str, float] = {}  # a $20 subscription is not €20 of the fixed costs
    for contract in ledger.active_contracts():
        monthly = contract.monthly_cost()
        if monthly is None:
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


@dataclass
class _AreaFacts:
    items: list[Item] = field(default_factory=list)
    dates: list[tuple[date, str]] = field(default_factory=list)  # (day to act, what)
    overdue: list[Item] = field(default_factory=list)
    contracts: int = 0
    documents: int = 0


def _collect_areas(ledger: Ledger) -> dict[str, _AreaFacts]:
    today = ledger.today
    facts: dict[str, _AreaFacts] = {}
    for doc in ledger.documents.values():
        facts.setdefault(doc.area or "other", _AreaFacts()).documents += 1
    for item in ledger.actionable_items():
        area = facts.setdefault(item.area, _AreaFacts())
        area.items.append(item)
        day = action_day(item)
        if is_overdue(item, today):
            area.overdue.append(item)
        elif day is not None and (parse_day(item.due_date) or day) >= today:
            area.dates.append((max(day, today), item.title))
    for contract in ledger.active_contracts():
        area = facts.setdefault(contract_area(contract), _AreaFacts())
        area.contracts += 1
        comp = ledger.computation(contract)
        send = parse_day(comp.send_by)
        if is_decision(comp) and send is not None:
            area.dates.append((send, f"Decide on {contract.name}"))
    return facts


def _area_status(area: Area, facts: _AreaFacts, today: date) -> AreaStatus:
    upcoming = sorted(facts.dates)
    first = upcoming[0] if upcoming else None
    days = (first[0] - today).days if first else None
    if facts.overdue or (days is not None and days <= URGENT_DAYS):
        status = "urgent"
    elif days is not None and days <= AREA_ATTENTION_DAYS:
        status = "attention"
    else:
        status = "ok"
    if facts.overdue:
        headline = f"Overdue: {facts.overdue[0].title}"
    elif first is not None:
        headline = f"{first[1]} — {day_label(first[0], today)}"
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
            "next_date": first[0].isoformat() if first else None,
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


def dashboard(store: Store, today: date) -> Dashboard:
    """The Today page: attention (overdue, due within 7 days, needs review), coming up (8–30 days),
    decisions (contracts with send-by within 60 days), money, life areas, new Ideas, recent letters
    and ledger stats."""
    ledger = Ledger(store, today)
    attention = _attention(ledger)
    counts = store.counts()
    first_name = ledger.profile.name.split()[0] if ledger.profile.name.strip() else ""
    recent = sorted(
        ledger.documents.values(),
        key=lambda doc: (doc.doc_date or doc.received_date or "", doc.id),
        reverse=True,
    )[:RECENT_DOCUMENTS]
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
                    "area": doc.area or "other",
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
        subtitle = (
            f"Send by {day_label(parse_day(item.send_by) or ledger.today, ledger.today)}"
            if item.send_by
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
                    "area": item.area,
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


def _marker(day: str, label: str, kind: str) -> TimelineMarker:
    return TimelineMarker.model_validate({"date": day, "label": label, "kind": kind})


def _item_marker(item: Item) -> TimelineMarker:
    return _marker(item.due_date or "", item.title, _MARKER_KINDS.get(item.kind, "other"))


def _residence_bar(ledger: Ledger, item: Item, klass: str, lanes: _Lanes) -> None:
    expiry = parse_day(item.due_date)
    if expiry is None:
        return
    doc = ledger.document(item.doc_id)
    start = parse_day(doc.doc_date) if doc else None
    permit = klass == "permit"
    markers = [_marker(expiry.isoformat(), "Expires", "expiry")]
    if permit:
        markers.insert(
            0, _marker(expiry.isoformat(), "Apply before this date (§ 81 Abs. 4 AufenthG)", "deadline")
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
                "ref": RefLink(type="item", id=item.id),
            }
        ),
    )


def _tax_bar(ledger: Ledger, item: Item, lanes: _Lanes) -> None:
    due = parse_day(item.due_date)
    doc = ledger.document(item.doc_id)
    start = (parse_day(doc.doc_date) if doc else None) or parse_day(item.created_at) or due
    if due is None or start is None:
        return
    markers = [_marker(due.isoformat(), "Must arrive by", "deadline")]
    if item.send_by:
        markers.insert(0, _marker(item.send_by, "Send by", "send_by"))
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
                "ref": RefLink(type="item", id=item.id),
            }
        ),
    )


def _route_item(ledger: Ledger, item: Item, lanes: _Lanes) -> None:
    """Each dated item goes to exactly one lane (bars for validity and objection windows)."""
    if item.kind == "expiry" and item.area == "residence":
        klass = expiry_class(item, ledger.document(item.doc_id))
        if klass in ("permit", "identity"):
            _residence_bar(ledger, item, klass, lanes)
            return
    if item.area == "tax" and item.kind == "deadline":
        _tax_bar(ledger, item, lanes)
        return
    if item.area in ("residence", "tax", "study", "work"):
        lanes.marker(item.area, _item_marker(item))
        return
    if item.kind == "payment":
        if (item.amount or 0.0) >= LARGE_PAYMENT_EUR:
            lanes.marker("money", _item_marker(item))
        return
    lane = item.area if item.area in LANE_ORDER else "other"
    lanes.marker(lane, _item_marker(item))


#: Regimes under which a contract that isn't cancelled simply runs on, cancellable at any time.
_ROLLING_REGIMES = frozenset({"bgb309_new", "tkg56", "stromgvv20", "sgbv175"})


def renews_for_a_term(contract: Contract, comp: ContractComputation) -> bool:
    """Whether an uncancelled contract really renews for a fixed term (otherwise it runs on and can be
    cancelled at any time with its notice period — § 309 Nr. 9 BGB since 2022, § 56 TKG, …)."""
    return comp.regime not in _ROLLING_REGIMES and bool(contract.renewal_term_months)


def continuation(contract: Contract, comp: ContractComputation) -> str:
    """What happens on ``next_renewal`` if the contract is not cancelled, in plain words."""
    if not renews_for_a_term(contract, comp):
        return "It continues with no fixed term and can then be cancelled at any time with its notice period."
    months = contract.renewal_term_months
    return f"It renews for {months} months unless it is cancelled in time."


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
    finish = parse_day(comp.current_term_end) or parse_day(contract.end_date) or lanes.end
    employment = contract.category == "employment"
    lane = "work" if employment else "contracts"
    markers = []
    if comp.next_renewal:
        markers.append(_marker(comp.next_renewal, _continuation_label(contract, comp), "renewal"))
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
                "ref": RefLink(type="contract", id=contract.id),
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
                    _marker(send.isoformat(), "Send by", "send_by"),
                    _marker(cancel.isoformat(), "Must arrive by", "cancel_by"),
                ],
                "ref": RefLink(type="contract", id=contract.id),
            }
        ),
    )


def lanes(store: Store, start: date, end: date, *, today: date | None = None) -> list[Lane]:
    """Year-ahead life lanes between ``start`` and ``end``: Residence (permit and passport validity,
    "apply before" marker), Contracts (term bars, notice windows with send-by/must-arrive-by markers),
    Tax (objection windows), Study, Work (employment term), Home, Money (payments ≥ €50), Health,
    Insurance, Mobility, Other. Only lanes with data, in that order; bars are clipped to the range."""
    day = today or local_today(store)
    ledger = Ledger(store, day)
    collected = _Lanes(start=start, end=end, today=day)
    for item in ledger.items:
        if item.due_date is not None and item.status != "dismissed" and not ledger.is_suspicious_item(item):
            _route_item(ledger, item, collected)
    for contract in ledger.active_contracts():
        _contract_bars(ledger, contract, collected)
    return collected.build()
