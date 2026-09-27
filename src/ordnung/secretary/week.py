"""The weekly admin session: about ten minutes, seven steps, one gentle prompt (SPEC §9).

Everything a weekly review needs already exists on five pages (Inbox, Today, the Pay panel, Letters,
Contracts). This module arranges one snapshot of the ledger (:class:`~ordnung.secretary.triggers.Ledger`,
the agenda of :func:`~ordnung.secretary.brief.build_agenda` and the money summary) as steps. It never
closes, pays or sends anything (ADR 0006): each row links to where the person acts, and the only things
it stores are the moments of the last session and of a dismissed prompt (two ``meta`` keys, no table),
each as the person's day and the clock's moment (``2026-09-28|2026-09-28T09:12:00Z``): the day for the
prompt, the moment to compare with when letters arrived and to-dos were done.

**The day on a row** — one rule for every step, as Today words it: a transfer's day is its send-by day
("transfer by"), a letter's the day to post it ("send by"), an appointment's its day ("on"), an expiry's
the day it expires; anything else its due date. Once a send-by day has passed but the due date has not,
the day is *today* ("act today"), with the due date beside it: the money or letter can still arrive by
another way. A row is *overdue* only when its due date has passed, counted from that date. A fee paid in
person at an appointment (:func:`~ordnung.secretary.triggers.paid_at_appointment`) is paid on the
appointment's day — never a transfer.

**The steps** — a short written policy (ADR 0007); every list is capped at :data:`MAX_ROWS` rows and says
how many it left out:

0. *Act now* (only when there is something) — deadlines, tasks and appointments that are overdue or to
   act on today (a missed send-by day included), not payments (step 3) nor replies awaited (step 5).
1. *New since the last session* (the first time: *new in the last 7 days*) — letters that entered Ordnung
   after the last session's moment (without one: in the last 7 days), letters that need the person first
   (Please check, open or snoozed to-dos, scam signs, not read yet), then newest first.
2. *Please check* — values Ordnung could not confirm against the letter
   (:func:`~ordnung.secretary.triggers.unconfirmed_reason`: not found in the letter, read by AI from a
   photo, or not matching its sentence — never once the person confirmed it) of open to-dos still
   relevant (undated or not past), and letters marked *Please check* with no such to-do.
3. *Pay this week* — the agenda's payments that are overdue or due within 7 days: transfers first (with
   the total per currency), then fees paid at an appointment (not in the total), then direct debits the
   sender collects (nothing to do but keep the money in the account); the summary counts the money
   summary's further payments of the next 30 days. A scam letter's demand is never listed (the agenda
   leaves it out), nor an invoice a payment reminder took over.
4. *Post and keep proof* — letters drafted but not sent (with their send-by day), then letters marked sent
   since the last session with what proves sending by that channel.
5. *Waiting for* — replies to letters you sent: the open follow-up to-dos Ordnung adds when a letter is
   marked sent, the earliest first. (Hook: a dedicated "waiting for" list replaces this source when one
   exists.)
6. *Decide in the next 30 days* — the agenda's contract decisions (a cancellation that must be sent within
   30 days, or the contract renews) and deadlines for an objection, a declaration or a notice due from
   today on whose day to act is within 30 days — not those of a contract already listed (its row is the
   decision) nor those in *Act now*.
7. *File or archive* — to-dos done since the last session, letters whose last open or snoozed to-do was
   closed since then (file the paper), and letters that turned a year old since then with nothing open
   or snoozed (archive the paper; tax-relevant ones stay with the tax papers). Each letter is listed in
   the week it qualifies, not every week.

**The ending.** When deadlines, payments or tasks are overdue, the session ends saying how many
(:attr:`~ordnung.models.WeeklySession.overdue`) — never "All clear". Otherwise it ends *All clear until …*
the earliest day to act from today on (today when a send-by day was missed) of an open or snoozed
deadline, payment, task or appointment worth acting on (no direct debit, no money coming in) and of the
agenda's contract decisions.

**The prompt.** Today suggests the session once — when none was done and no prompt dismissed in the last
7 days, or on a Sunday 4 days after either — and only when a step has something to show. Doing the
session or dismissing the prompt stores the moment; nothing else nags. The session says the day Today
suggests it next (:func:`next_prompt_day`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ordnung.clock import now_iso
from ordnung.db.store import Store
from ordnung.models import (
    Document,
    Draft,
    Item,
    MoneySummary,
    RefLink,
    WeekDateRole,
    WeekEntry,
    WeeklySession,
    WeekStep,
)
from ordnung.payments import is_direct_debit
from ordnung.secretary.brief import Agenda, AgendaEntry
from ordnung.secretary.triggers import (
    Ledger,
    action_day,
    day_label,
    is_overdue,
    paid_at_appointment,
    parse_day,
    parse_timestamp,
    unconfirmed_reason,
)

SESSION_KEY = "weekly_session_at"
DISMISSED_KEY = "weekly_prompt_dismissed_at"
WEEK = 7
SUNDAY_AFTER = 4
DECIDE_DAYS = 30
MAX_ROWS = 8
MINUTES = 10
DECISION_NATURES = frozenset({"objection", "declaration", "notice"})
_ACT_KINDS = frozenset({"deadline", "payment", "task", "appointment"})
_NOW_KINDS = frozenset({"deadline", "task", "appointment"})
_OVERDUE_KINDS = frozenset({"deadline", "payment", "task"})

#: What proves a letter was sent, by the channel the person marked (``Draft.sent_channel``).
PROOF_BY_CHANNEL = {
    "registered_letter": "Keep the posting receipt (Einlieferungsbeleg) with a copy of the letter.",
    "letter": "An ordinary letter can't be proven: keep a copy, and note the day and post office.",
    "email": "Keep the sent e-mail, and the reply if one comes.",
    "fax": "Keep the fax transmission report (Sendebericht) with a copy of the letter.",
    "in_person": "Keep your copy with the receipt stamp (Eingangsstempel).",
    "online_button": "Save the confirmation page or e-mail.",
    "portal": "Save the confirmation page or e-mail.",
}
DEFAULT_PROOF = "Keep a copy and note how and when you sent it."
_CHECK_NOTES = {
    "unverified": "Not found in the letter — compare it with the letter.",
    "model_read": "Read by AI from a photo — compare it with the paper letter.",
    "mismatch": "Doesn't match its sentence in the letter — compare it with the letter.",
}
MISSED_TRANSFER_NOTE = (
    "The day to transfer it has passed: pay today by instant transfer (Echtzeitüberweisung) so it can "
    "still arrive by the due date."
)
MISSED_POST_NOTE = (
    "The last safe day to post it has passed, but the due date is still ahead: hand it in today, or send "
    "it a way that arrives in time (fax, or an online form the sender accepts)."
)
OVERDUE_NOTE = "Its date has passed: do it now, or contact the sender if you can't."
AT_APPOINTMENT_NOTE = "Paid at the appointment itself, not by transfer: bring a card or cash."


# --------------------------------------------------------------------------------------------------
# session state (meta)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Moment:
    """When something happened: the person's day (their calendar, as the app shows it) and the stored
    moment (the clock ``created_at`` and ``completed_at`` use, to compare with)."""

    day: date
    at: datetime


@dataclass(frozen=True)
class SessionState:
    """When the last session was done and the prompt last dismissed (``None``: never)."""

    last_session: Moment | None = None
    dismissed: Moment | None = None


def _read_moment(raw: str | None) -> Moment | None:
    """``"2026-09-28|2026-09-28T09:12:00Z"`` → a :class:`Moment` (``None`` when missing or unreadable)."""
    day_text, _, at_text = (raw or "").partition("|")
    day, at = parse_day(day_text) if len(day_text) == 10 else None, parse_timestamp(at_text)
    return Moment(day, at) if day is not None and at is not None else None


def _write_moment(store: Store, key: str, today: date) -> Moment:
    at = now_iso()
    store.set_meta(key, f"{today.isoformat()}|{at}")
    moment = _read_moment(store.get_meta(key))
    assert moment is not None
    return moment


def session_state(store: Store) -> SessionState:
    """The stored state (an unreadable value counts as never)."""
    return SessionState(
        _read_moment(store.get_meta(SESSION_KEY)), _read_moment(store.get_meta(DISMISSED_KEY))
    )


def record_session(store: Store, today: date) -> Moment:
    """Remember that the person went through the session now, on their ``today``."""
    moment = _write_moment(store, SESSION_KEY, today)
    store.log_activity("week.done", "Weekly session done")
    return moment


def dismiss_prompt(store: Store, today: date) -> Moment:
    """Remember that the person said "Not now" to Today's prompt, on their ``today``."""
    return _write_moment(store, DISMISSED_KEY, today)


def prompt_due(state: SessionState, today: date) -> bool:
    """Whether Today may suggest the session (module policy): 7 days after the last session or dismissed
    prompt — on a Sunday 4 days after — and never before either."""
    known = [moment.day for moment in (state.last_session, state.dismissed) if moment is not None]
    if not known:
        return True
    since = (today - max(known)).days
    return since >= WEEK or (today.weekday() == 6 and since >= SUNDAY_AFTER)


def next_prompt_day(state: SessionState, today: date) -> date | None:
    """The first day after ``today`` on which :func:`prompt_due` holds (``None`` when it is due today)."""
    if prompt_due(state, today):
        return None
    day = today + timedelta(days=1)
    while not prompt_due(state, day):  # at most a week on
        day += timedelta(days=1)
    return day


# --------------------------------------------------------------------------------------------------
# the day on a row
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class When:
    """The day a row shows and what it means (module policy, "The day on a row")."""

    day: date | None
    role: WeekDateRole | None
    due: date | None = None  # the due date, when the row's day is an earlier day to act

    @property
    def missed(self) -> bool:
        """The send-by day passed, the due date has not: act today."""
        return self.role == "act_today"


def _plain_role(item: Item) -> WeekDateRole:
    if item.kind == "payment":
        return "pay_by"
    if item.kind == "task":
        return "by"
    if item.kind in ("reminder", "milestone"):
        return "on"
    return "due"


def when(item: Item, today: date, *, in_person: bool = False) -> When:
    """The day to show for ``item`` on ``today`` (``in_person``: a fee paid at an appointment)."""
    due, send = parse_day(item.due_date), parse_day(item.send_by)
    payment = item.kind == "payment" and item.direction != "in"
    if item.kind == "appointment":
        return When(due, "on")
    if item.kind == "expiry":
        return When(due, "expires")
    if payment and is_direct_debit(item):
        return When(due, "collected")
    if payment and in_person:
        return When(due, "at_appointment")
    if due is not None and due < today:  # overdue: counted from the due date, not the send-by day
        return When(due, _plain_role(item))
    if send is not None and send < today:
        return When(today, "act_today", due)
    if send is not None and (due is None or send <= due):
        return When(send, "transfer_by" if payment else "send_by", due if due != send else None)
    return When(due, _plain_role(item))


def _act_on(item: Item, today: date, *, in_person: bool = False) -> date | None:
    """The day to act from today on (a missed send-by day is today; a fee at an appointment its day)."""
    act = parse_day(item.due_date) if in_person else action_day(item)
    return max(act, today) if act is not None else None


# --------------------------------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------------------------------


def _item_entry(ledger: Ledger, item: Item, **fields: object) -> WeekEntry:
    doc = ledger.document(item.doc_id)
    party = item.party_id or (doc.party_id if doc else None)
    shown = when(item, ledger.today, in_person=paid_at_appointment(item, ledger.items))
    data: dict[str, object] = {
        "key": f"item:{item.id}",
        "ref": RefLink(type="item", id=item.id),
        "title": item.title,
        "kind": item.kind,
        "date": shown.day.isoformat() if shown.day else None,
        "date_role": shown.role,
        "due_date": shown.due.isoformat() if shown.due else None,
        "amount": item.amount,
        "currency": item.currency,
        "party_id": party,
        "party_name": ledger.party_name(party),
        "doc_id": item.doc_id,
        "status": item.status,
        "overdue": is_overdue(item, ledger.today),
        "item": item,
    }
    data.update(fields)
    return WeekEntry.model_validate(data)


def _doc_entry(ledger: Ledger, doc: Document, **fields: object) -> WeekEntry:
    data: dict[str, object] = {
        "key": f"document:{doc.id}",
        "ref": RefLink(type="document", id=doc.id),
        "title": doc.title or doc.filename,
        "kind": doc.kind or "other",
        "date": doc.created_at[:10],
        "date_role": "added",
        "party_id": doc.party_id,
        "party_name": ledger.party_name(doc.party_id),
        "doc_id": doc.id,
        "status": doc.status,
    }
    data.update(fields)
    return WeekEntry.model_validate(data)


def _draft_entry(ledger: Ledger, draft: Draft, **fields: object) -> WeekEntry:
    data: dict[str, object] = {
        "key": f"draft:{draft.id}",
        "ref": RefLink(type="draft", id=draft.id),
        "title": draft.subject or "Your letter",
        "kind": draft.kind,
        "party_id": draft.party_id,
        "party_name": ledger.party_name(draft.party_id),
        "doc_id": draft.doc_id,
        "status": draft.status,
    }
    data.update(fields)
    return WeekEntry.model_validate(data)


def _contract_entry(ledger: Ledger, entry: AgendaEntry, **fields: object) -> WeekEntry:
    """A contract decision of the agenda: send the cancellation by its day, or it renews."""
    today = ledger.today
    send = parse_day(entry.date)
    contract = next((c for c in ledger.contracts if c.id == entry.id), None)
    cancel_by = parse_day(ledger.computation(contract).cancel_by) if contract is not None else None
    missed = send is not None and send < today
    data: dict[str, object] = {
        "key": f"contract:{entry.id}",
        "ref": RefLink(type="contract", id=entry.id),
        "title": entry.title,
        "kind": "contract",
        "date": today.isoformat() if missed else entry.date,
        "date_role": "act_today" if missed else "decide_by",
        "due_date": cancel_by.isoformat() if missed and cancel_by else None,
        "party_name": entry.party,
        "doc_id": entry.doc_id,
        "note": MISSED_POST_NOTE if missed else "Renews unless you send a cancellation by then.",
        "tone": "warn" if missed else "neutral",
    }
    data.update(fields)
    return WeekEntry.model_validate(data)


def _step(step_id: str, title: str, entries: Sequence[WeekEntry], summary: str, **fields: object) -> WeekStep:
    return WeekStep.model_validate(
        {
            "id": step_id,
            "title": title,
            "summary": summary,
            "entries": list(entries[:MAX_ROWS]),
            "more": max(0, len(entries) - MAX_ROWS),
            **fields,
        }
    )


def _count(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


def _pending_items(ledger: Ledger) -> list[Item]:
    """Open or snoozed (however long) to-dos worth acting on: no letter with scam signs, no invoice a
    payment reminder took over. A snoozed to-do is still the person's."""
    return [
        item
        for item in ledger.items
        if item.status in ("open", "snoozed")
        and not ledger.is_suspicious_item(item)
        and not ledger.is_superseded_by_reminder(item)
    ]


def _missed_note(item: Item, shown: When) -> str | None:
    if not shown.missed:
        return None
    return MISSED_TRANSFER_NOTE if item.kind == "payment" else MISSED_POST_NOTE


@dataclass(frozen=True)
class _Window:
    """The session's reference points: today, and when "since the last session" starts."""

    today: date
    since_day: date
    since_stamp: datetime | None  # the last session's moment (None: the week before today)

    def after(self, stamp: str | None) -> bool:
        """Whether a record stamped ``stamp`` is new in this session."""
        moment = parse_timestamp(stamp)
        if moment is None:
            return False
        if self.since_stamp is not None:
            return moment >= self.since_stamp
        return moment.date() >= self.since_day

    def on_or_after(self, day: str | None) -> bool:
        parsed = parse_day(day)
        return parsed is not None and self.since_day <= parsed <= self.today


# --------------------------------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------------------------------


def _act_now(ledger: Ledger) -> tuple[WeekStep | None, set[str]]:
    """The *Act now* step (``None`` when nothing is overdue or to act on today) and every item it holds,
    also those left out of its rows."""
    today = ledger.today
    overdue, due_today = [], []
    for item in ledger.actionable_items():
        if item.kind not in _NOW_KINDS or item.origin == "draft":
            continue
        due = parse_day(item.due_date)
        if is_overdue(item, today):
            overdue.append(item)
        elif due is not None and due >= today and _act_on(item, today) == today:
            due_today.append(item)
    held = {item.id for item in (*overdue, *due_today)}
    if not held:
        return None, held
    rows = [
        _item_entry(ledger, item, note=OVERDUE_NOTE, tone="danger")
        for item in sorted(overdue, key=lambda i: (i.due_date or "", i.id))
    ]
    for item in sorted(due_today, key=lambda i: (i.due_date or "", i.id)):
        row = _item_entry(ledger, item)
        note = _missed_note(item, when(item, today))
        rows.append(row.model_copy(update={"note": note, "tone": "warn"}))
    parts = [f"{len(overdue)} overdue"] if overdue else []
    if due_today:
        parts.append(f"{len(due_today)} to do today")
    return _step("now", "Act now", rows, " · ".join(parts)), held


def _new_letters(ledger: Ledger, window: _Window, *, first: bool) -> WeekStep:
    pending = _pending_items(ledger)
    fresh = [doc for doc in ledger.documents.values() if window.after(doc.created_at)]

    def open_count(doc: Document) -> int:
        return sum(1 for item in pending if item.doc_id == doc.id)

    def row(doc: Document) -> WeekEntry:
        count = open_count(doc)
        if ledger.scam_reasons(doc):
            return _doc_entry(
                ledger, doc, note="Shows signs of a scam — don't pay or reply yet.", tone="danger"
            )
        if doc.status == "needs_review":
            return _doc_entry(ledger, doc, note="Please check what Ordnung read.", tone="warn")
        if doc.status in ("queued", "processing"):
            return _doc_entry(ledger, doc, note="Still being read.")
        if doc.status == "failed":
            return _doc_entry(ledger, doc, note="Couldn't be read — open it to try again.", tone="warn")
        note = f"{_count(count, 'open to-do')}" if count else "Nothing to do — filed."
        return _doc_entry(ledger, doc, note=note, tone="neutral" if count else "ok")

    def needs_you(doc: Document) -> bool:
        return bool(ledger.scam_reasons(doc)) or doc.status != "processed" or open_count(doc) > 0

    newest = sorted(fresh, key=lambda doc: (doc.created_at, doc.id), reverse=True)
    ordered = [doc for doc in newest if needs_you(doc)] + [doc for doc in newest if not needs_you(doc)]
    since = day_label(window.since_day, window.today)
    summary = (
        f"{_count(len(ordered), 'letter')} since {since}" if ordered else f"No new letters since {since}"
    )
    title = f"New in the last {WEEK} days" if first else "New since your last session"
    return _step("new", title, [row(doc) for doc in ordered], summary)


def _to_check(ledger: Ledger) -> WeekStep:
    today = ledger.today
    rows: list[WeekEntry] = []
    covered: set[str] = set()
    for item in sorted(ledger.actionable_items(), key=lambda i: (action_day(i) or date.max, i.id)):
        reason = unconfirmed_reason(item)
        due = parse_day(item.due_date)
        if reason is None or (due is not None and due < today) or item.origin == "draft":
            continue
        covered.add(item.doc_id or "")
        rows.append(_item_entry(ledger, item, note=_CHECK_NOTES[reason], tone="warn"))
    for doc in sorted(ledger.documents.values(), key=lambda d: (d.created_at, d.id), reverse=True):
        if doc.status == "needs_review" and doc.id not in covered and not ledger.scam_reasons(doc):
            rows.append(
                _doc_entry(
                    ledger,
                    doc,
                    note="Some details need your confirmation.",
                    tone="warn",
                    date=None,
                    date_role=None,
                )
            )
    summary = f"{_count(len(rows), 'thing')} to compare with the letter" if rows else "Nothing to check"
    return _step("check", "Please check", rows, summary)


def _pay(ledger: Ledger, agenda: Agenda, money: MoneySummary) -> WeekStep:
    by_id = {item.id: item for item in ledger.items}
    entries: list[AgendaEntry] = [
        entry
        for entry in (*agenda.overdue, *agenda.today, *agenda.next_7_days)
        if entry.kind == "payment" and entry.id in by_id
    ]
    transfers, in_person, debits = [], [], []
    for entry in entries:
        item = by_id[entry.id]
        row = _item_entry(ledger, item)
        if row.date_role == "collected":
            debits.append(row.model_copy(update={"note": "Collected by direct debit: keep it covered."}))
            continue
        if row.date_role == "at_appointment":
            in_person.append(row.model_copy(update={"note": AT_APPOINTMENT_NOTE}))
            continue
        note = _missed_note(item, when(item, ledger.today))
        if item.amount is not None and item.grounding not in ("verified", "user"):
            note = " ".join(
                part
                for part in (note, "The amount wasn't confirmed against the letter — check it before paying.")
                if part
            )
        tone = "danger" if row.overdue else "warn" if note else "neutral"
        transfers.append(row.model_copy(update={"note": note, "tone": tone}))
    totals: dict[str, float] = {}
    for row in transfers:
        if row.amount is not None:
            code = (row.currency or "EUR").upper()
            totals[code] = round(totals.get(code, 0.0) + row.amount, 2)
    euros = totals.pop("EUR", None)
    extras = [f"{_count(len(in_person), 'fee')} to pay at an appointment"] if in_person else []
    if debits:
        extras.append(f"{_count(len(debits), 'direct debit')} to cover")
    if transfers:
        summary = ", ".join([f"{_count(len(transfers), 'transfer')} to make", *extras])
    elif extras:
        summary = "Nothing to transfer; " + ", ".join(extras)
    else:
        summary = "Nothing to pay this week"
    shown = {row.ref.id for row in (*transfers, *in_person, *debits)}
    later = [item for item in money.upcoming_payments if item.id not in shown]
    if later:
        summary += f" · {_count(len(later), 'more payment')} in the next 30 days"
    return _step(
        "pay",
        "Pay this week",
        [*transfers, *in_person, *debits],
        summary,
        total=euros,
        total_other_currencies=dict(sorted(totals.items())),
    )


def _post(ledger: Ledger, drafts: Iterable[Draft], window: _Window) -> WeekStep:
    unsent, sent = [], []
    for draft in drafts:
        if draft.status in ("draft", "final"):
            guidance = draft.send_guidance
            send_by = guidance.send_by if guidance else None
            unsent.append(
                _draft_entry(
                    ledger,
                    draft,
                    date=send_by,
                    date_role="send_by" if send_by else None,
                    note="Not sent yet — send it, then mark it as sent.",
                    tone="warn",
                    overdue=bool(send_by and send_by < ledger.today.isoformat()),
                )
            )
        elif draft.status == "sent" and window.on_or_after(draft.sent_at):
            proof = PROOF_BY_CHANNEL.get(draft.sent_channel or "", DEFAULT_PROOF)
            # HOOK(proof): once a letter can carry its proof of sending, list the ones still without it here
            sent.append(
                _draft_entry(
                    ledger,
                    draft,
                    date=draft.sent_at[:10] if draft.sent_at else None,
                    date_role="sent",
                    note=proof,
                )
            )
    unsent.sort(key=lambda row: (row.date or "9999-12-31", row.key))
    sent.sort(key=lambda row: (row.date or "", row.key), reverse=True)
    parts = [_count(len(unsent), "letter") + " to send"] if unsent else []
    if sent:
        parts.append(f"{len(sent)} sent — keep the proof")
    return _step("post", "Post and keep proof", [*unsent, *sent], " · ".join(parts) or "Nothing to post")


def _waiting(ledger: Ledger) -> WeekStep:
    # HOOK(waiting-for): a dedicated "waiting for" list, when it exists, is the source of this step.
    rows = []
    for item in sorted(ledger.active_items(), key=lambda i: (i.due_date or "9999-12-31", i.id)):
        if item.origin != "draft":
            continue
        due = parse_day(item.due_date)
        late = due is not None and due <= ledger.today
        note = "No reply yet? Call them or send a short reminder." if late else item.description
        rows.append(
            _item_entry(
                ledger,
                item,
                date=item.due_date,
                date_role="reply_by",
                due_date=None,
                note=note,
                tone="warn" if late else "neutral",
            )
        )
    summary = f"Waiting for {_count(len(rows), 'reply', 'replies')}" if rows else "Not waiting for any reply"
    return _step("waiting", "Waiting for", rows, summary)


def _decide(ledger: Ledger, agenda: Agenda, acting_now: set[str]) -> WeekStep:
    today = ledger.today
    rows: list[WeekEntry] = [_contract_entry(ledger, entry) for entry in agenda.decisions]
    decided = {entry.id for entry in agenda.decisions}
    for item in ledger.actionable_items():
        act, due = _act_on(item, today), parse_day(item.due_date)
        nature = item.date_spec.nature if item.date_spec else "other"
        if (
            item.kind != "deadline"
            or nature not in DECISION_NATURES
            or item.origin == "draft"
            or item.id in acting_now  # Act now lists it
            or item.contract_id in decided  # the contract's own decision row says it
            or act is None
            or due is None
            or due < today
            or (act - today).days > DECIDE_DAYS
        ):
            continue
        note = {
            "objection": "Decide whether to object before then.",
            "declaration": "Decide and answer before then.",
            "notice": "Decide whether to give notice before then.",
        }[nature]
        row = _item_entry(ledger, item, note=note)
        missed = _missed_note(item, when(item, today))
        rows.append(row.model_copy(update={"note": missed, "tone": "warn"}) if missed else row)
    rows.sort(key=lambda row: (row.date or "9999-12-31", row.key))
    summary = (
        f"{_count(len(rows), 'decision')} in the next {DECIDE_DAYS} days"
        if rows
        else f"No decisions due in the next {DECIDE_DAYS} days"
    )
    return _step("decide", f"Decide in the next {DECIDE_DAYS} days", rows, summary)


def _file(ledger: Ledger, window: _Window) -> WeekStep:
    done = [item for item in ledger.items if item.status == "done" and window.after(item.completed_at)]
    # a snoozed to-do still keeps its letter open: the person put it off, not away
    open_docs = {item.doc_id for item in ledger.items if item.status in ("open", "snoozed") and item.doc_id}
    done_docs = {item.doc_id for item in done if item.doc_id}
    rows = [
        _item_entry(
            ledger,
            item,
            date=(item.completed_at or "")[:10] or None,
            date_role="done",
            due_date=None,
            overdue=False,
            tone="ok",
        )
        for item in sorted(done, key=lambda i: (i.completed_at or "", i.id), reverse=True)
    ]
    for doc in sorted(ledger.documents.values(), key=lambda d: (d.doc_date or "", d.id), reverse=True):
        if doc.id in open_docs or ledger.scam_reasons(doc):
            continue
        tax = " Keep it with your tax papers." if doc.tax_relevant else ""
        if doc.id in done_docs:
            rows.append(_doc_entry(ledger, doc, note=f"Everything done — file the paper.{tax}", tone="ok"))
            continue
        dated = parse_day(doc.doc_date)
        birthday = (
            dated.replace(year=dated.year + 1)
            if dated and not (dated.month == 2 and dated.day == 29)
            else None
        )
        if birthday is not None and window.since_day <= birthday <= window.today:
            rows.append(
                _doc_entry(
                    ledger,
                    doc,
                    date=doc.doc_date,
                    date_role=None,
                    note=f"A year old with nothing open — move the paper to your archive.{tax}",
                )
            )
    todos = sum(1 for row in rows if row.ref.type == "item")
    letters = len(rows) - todos
    parts = [f"{_count(todos, 'to-do')} done"] if todos else []
    if letters:
        parts.append(f"{_count(letters, 'letter')} to file")
    return _step("file", "File or archive", rows, " · ".join(parts) or "Nothing to file this week")


# --------------------------------------------------------------------------------------------------
# the ending
# --------------------------------------------------------------------------------------------------


def _worth_acting(item: Item) -> bool:
    return item.kind in _ACT_KINDS and not (
        item.kind == "payment" and (item.direction == "in" or is_direct_debit(item))
    )


def overdue_count(ledger: Ledger) -> int:
    """Deadlines, payments and tasks past their due date (not replies awaited, direct debits or money
    coming in): while any is, the session never ends "All clear"."""
    return sum(
        1
        for item in ledger.actionable_items()
        if item.kind in _OVERDUE_KINDS
        and item.origin != "draft"
        and _worth_acting(item)
        and is_overdue(item, ledger.today)
    )


def next_deadline(ledger: Ledger, agenda: Agenda) -> WeekEntry | None:
    """The earliest day to act from today on (module policy, "The ending"): open or snoozed to-dos not
    yet overdue, and the agenda's contract decisions."""
    today = ledger.today
    chosen: tuple[date, str, Item | AgendaEntry] | None = None
    for item in _pending_items(ledger):
        due = parse_day(item.due_date)
        if not _worth_acting(item) or (due is not None and due < today):
            continue
        act = _act_on(item, today, in_person=paid_at_appointment(item, ledger.items))
        if act is not None and (chosen is None or (act, item.id) < chosen[:2]):
            chosen = (act, item.id, item)
    for decision in agenda.decisions:
        send = parse_day(decision.date)
        day = max(send, today) if send is not None else None
        if day is not None and (chosen is None or (day, decision.id) < chosen[:2]):
            chosen = (day, decision.id, decision)
    if chosen is None:
        return None
    found = chosen[2]
    if isinstance(found, AgendaEntry):
        return _contract_entry(ledger, found, note=None, tone="neutral")
    return _item_entry(ledger, found)


def build_weekly_session(
    ledger: Ledger, *, agenda: Agenda, money: MoneySummary, drafts: Sequence[Draft], state: SessionState
) -> WeeklySession:
    """The steps for ``ledger.today`` (module policy)."""
    today = ledger.today
    last = state.last_session
    since_day = last.day if last is not None else today - timedelta(days=WEEK)
    window = _Window(today=today, since_day=min(since_day, today), since_stamp=last.at if last else None)
    now, acting_now = _act_now(ledger)
    steps = [
        *([now] if now is not None else []),
        _new_letters(ledger, window, first=last is None),
        _to_check(ledger),
        _pay(ledger, agenda, money),
        _post(ledger, drafts, window),
        _waiting(ledger),
        _decide(ledger, agenda, acting_now),
        _file(ledger, window),
    ]
    has_something = any(step.entries for step in steps)
    upcoming = next_prompt_day(state, today)
    return WeeklySession(
        today=today.isoformat(),
        since=window.since_day.isoformat(),
        last_session=last.day.isoformat() if last else None,
        due=has_something and prompt_due(state, today),
        next_prompt=upcoming.isoformat() if upcoming else None,
        minutes=MINUTES,
        steps=steps,
        overdue=overdue_count(ledger),
        next_deadline=next_deadline(ledger, agenda),
    )
