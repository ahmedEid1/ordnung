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
another way. A row is *overdue* only when its due date has passed, counted from that date — for a letter
you wrote, the day it must arrive by (``must_arrive_by``), else its send-by day. A fee paid in person at
an appointment (:func:`~ordnung.secretary.triggers.paid_at_appointment`) is paid on the appointment's
day — never a transfer. Money coming in is *expected* on its day, never paid.

**Snoozed to-dos.** Snoozing puts off Today's reminder, not the date: a to-do snoozed until a later day
(:func:`pending_items`) is still listed where its date puts it (*Act now*, *Pay this week*, *Decide*),
counts as overdue once its due date has passed and keeps its letter open.

**The steps** — a short written policy (ADR 0007); every list is capped at :data:`MAX_ROWS` rows and says
how many it left out:

0. *Act now* (only when there is something) — deadlines, tasks and appointments that are overdue or to
   act on today (a missed send-by day included), not payments (step 3) nor replies awaited (step 5).
1. *New since the last session* (the first time: *new in the last 7 days*) — letters that entered Ordnung
   after the last session's moment (without one: in the last 7 days), and older letters Ordnung has not read
   (:func:`~ordnung.secretary.brief.is_unread`: Today counts them until they are read, so the review lists
   them every week too); letters that need the person first (Please check, open or snoozed to-dos, scam
   signs, not read yet — being read, waiting for the person's answer from the watched folder, couldn't be
   read, or kept private and never read, which is never "nothing to do"), then newest first.
2. *Compare with the letter* — to-dos whose date Ordnung could not confirm against the letter
   (:func:`~ordnung.secretary.triggers.unconfirmed_reason`: not found in the letter, read by AI from a
   photo, or not matching its sentence — never once the person confirmed it) with a day to compare (a
   due date or a send-by day, :func:`has_day_to_compare`) that has not passed, and letters marked *Please
   check* with no such to-do (an undated to-do's letter included). The person's "The date looks right"
   vouches for the date only: a payment's amount is compared in its Pay panel (ADR 0012, point 3), and
   *Pay this week* warns about an amount by the GiroCode policy's own check
   (:func:`~ordnung.secretary.girocode_gate.amount_confirmed`).
3. *Pay this week* — the agenda's payments that are overdue or due within 7 days (and snoozed ones the
   agenda leaves out, by the same rule): transfers first (with the total per currency), then fees paid
   at an appointment (not in the total), then direct debits the sender collects (nothing to do but keep
   the money in the account); the summary counts the money summary's further payments of the next 30
   days. A scam letter's demand is never listed (the agenda leaves it out), nor an invoice a payment
   reminder took over.
4. *Post and keep proof* — letters drafted but not sent (with their send-by day, and the day they must
   arrive by beside it; once the send-by day has passed, the ways the letter's own send advice allows
   that reach them the same day — never a fax or e-mail for a letter that must be signed by hand, §§ 568,
   623 BGB), then sent letters still waiting for their answer that lack the proof their channel needs
   (:func:`~ordnung.drafts.proof.missing` — whenever they were sent), then the others sent since the last
   session, saying so when a proof shows they were delivered. What proves *sending* is not proof that it
   *arrived*: arrival (Zugang, § 130 BGB) is for the sender to prove — for an Einwurf-Einschreiben with
   the delivery record (Auslieferungsbeleg); the posting receipt with the online tracking status alone was
   not accepted as prima facie proof (BAG, 30.01.2025 – 2 AZR 68/24).
5. *Waiting for* — the *Waiting for* page's open entries (:func:`~ordnung.secretary.waiting.waiting_for`):
   replies to letters you sent, money a letter promised and promises made on the phone, in the page's
   order (overdue, then those a letter may have answered, then the rest); a letter the person said was
   answered is no longer waited for.
6. *Decide in the next 30 days* — the agenda's contract decisions (a cancellation that must be sent within
   30 days, or the contract renews) and deadlines for an objection, a declaration or a notice due from
   today on whose day to act is within 30 days — not those of a contract already listed (its row is the
   decision) nor those in *Act now*.
7. *File or archive* — to-dos done since the last session, letters whose last open or snoozed to-do was
   closed since then (file the paper), and letters that turned a year old since then with nothing open
   or snoozed (archive the paper; tax-relevant ones stay with the tax papers). Each letter is listed in
   the week it qualifies, not every week.

**The ending.** When something is overdue — a deadline, payment or task past its due date (snoozed or
not), a letter to send past the day it had to arrive by (unless a to-do of its letter carries that day and
is counted), or an entry of *Waiting for* past its day — the session ends saying how many
(:attr:`~ordnung.models.WeeklySession.overdue`; the rows counted carry ``overdue``) — never "All clear".
Otherwise it ends *All clear until …* the earliest day to act from today on (today when a send-by day was
missed) of an open or snoozed deadline, payment, task or appointment worth acting on (no direct debit, no
money coming in) and of the agenda's contract decisions — or, when that day is today, with how many of
them are to act on today (:attr:`~ordnung.models.WeeklySession.due_today`).

**The prompt.** Today suggests the session once — when none was done and no prompt dismissed in the last
7 days, or on a Sunday 4 days after either — and only when a step has something to show. Doing the
session or dismissing the prompt stores the moment; nothing else nags. The session says the day Today
suggests it next (:func:`next_prompt_day`).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ordnung.clock import now_iso
from ordnung.db.store import Store
from ordnung.drafts.proof import RecordedProof, missing
from ordnung.models import (
    Contract,
    Document,
    Draft,
    Item,
    MoneySummary,
    RefLink,
    SendGuidance,
    WaitingEntry,
    WeekDateRole,
    WeekEntry,
    WeeklySession,
    WeekStep,
)
from ordnung.payments import is_direct_debit
from ordnung.rules.send import same_day_channels, send_guidance
from ordnung.secretary.brief import Agenda, AgendaEntry, is_unread
from ordnung.secretary.girocode_gate import amount_confirmed
from ordnung.secretary.triggers import (
    Ledger,
    action_day,
    day_label,
    is_active,
    is_overdue,
    paid_at_appointment,
    parse_day,
    parse_timestamp,
    unconfirmed_reason,
)
from ordnung.secretary.waiting import delivered_on, waiting_for

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

#: A sent letter this week whose channel asks for no particular proof (nothing is missing, none kept).
DEFAULT_PROOF = "Keep a copy and note how and when you sent it."
_CHECK_NOTES = {
    "unverified": "Its date wasn't found in the letter — compare it with the letter.",
    "model_read": "Its date was read by AI from a photo — compare it with the paper letter.",
    "mismatch": "Its date doesn't match its sentence in the letter — compare it with the letter.",
}
UNCONFIRMED_AMOUNT_NOTE = (
    "The amount wasn't confirmed against the letter — compare it in the Pay panel before paying."
)
MISSED_TRANSFER_NOTE = (
    "The day to transfer it has passed: pay today by instant transfer (Echtzeitüberweisung) so it can "
    "still arrive by the due date."
)
#: A missed send-by day without the letter's own send advice: no way to send it is named, since the
#: letter's form may rule out all but a signed letter (a notice on a flat or a job, §§ 568, 623 BGB).
MISSED_POST_NOTE = (
    "The last safe day to post it has passed, but the due date is still ahead: take it there yourself "
    "today, or use another way that reaches them in time — only one its form allows (a notice that must "
    "be signed by hand can't go by fax or e-mail)."
)
_MISSED_POST_WAYS = (
    "The last safe day to post it has passed, but the due date is still ahead: use a way that reaches "
    "them today — {ways}."
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
    store.log_activity("week.done", "Weekly review done")
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
        return "expected" if item.direction == "in" else "pay_by"
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
    if item.kind == "payment" and not payment:  # money coming in: expected on its day, never paid
        return When(due, "expected")
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


def is_past_due(item: Item, today: date) -> bool:
    """:func:`~ordnung.secretary.triggers.is_overdue`, also for a to-do snoozed until a later day: snoozing
    puts off the reminder, not the due date. Money coming in is never overdue: it is not the person's to
    pay."""
    if item.kind == "payment" and item.direction == "in":
        return False
    return is_overdue(item.model_copy(update={"status": "open"}) if item.status == "snoozed" else item, today)


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
        "overdue": counts_overdue(item, ledger.today),
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


#: Contracts that after their term only continue month to month, cancellable any time with at most a month's
#: notice (§ 309 Nr. 9 BGB, § 56 Abs. 3 TKG): they don't renew for another term (walkthrough of phase 2).
_CONTINUES_MONTHLY = ("bgb309_new", "tkg56")


def _keeps_going(regime: str | None) -> str:
    """What happens when no cancellation is sent by the contract's day: a new term, or month to month."""
    if regime in _CONTINUES_MONTHLY:
        return "Continues after its term unless you send a cancellation by then — then cancellable monthly."
    return "Renews unless you send a cancellation by then."


def _contract_entry(ledger: Ledger, entry: AgendaEntry, **fields: object) -> WeekEntry:
    """A contract decision of the agenda: send the cancellation by its day, or it renews."""
    today = ledger.today
    send = parse_day(entry.date)
    contract = next((c for c in ledger.contracts if c.id == entry.id), None)
    computation = ledger.computation(contract) if contract is not None else None
    cancel_by = parse_day(computation.cancel_by) if computation is not None else None
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
        "note": missed_post_note(_cancellation_guidance(ledger, contract))
        if missed
        else _keeps_going(computation.regime if computation is not None else None),
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


def pending_items(ledger: Ledger) -> list[Item]:
    """Open or snoozed (however long) to-dos worth acting on — none set aside
    (:meth:`~ordnung.secretary.triggers.Ledger.is_set_aside`: a letter with scam signs, an invoice a
    payment reminder took over, an e-mail's payment its attached bill repeats). A snoozed to-do is still
    the person's (module policy, "Snoozed to-dos")."""
    return [
        item for item in ledger.items if item.status in ("open", "snoozed") and not ledger.is_set_aside(item)
    ]


def _missed_note(item: Item, shown: When) -> str | None:
    if not shown.missed:
        return None
    return MISSED_TRANSFER_NOTE if item.kind == "payment" else MISSED_POST_NOTE


def missed_post_note(guidance: SendGuidance | None) -> str:
    """What to say once a letter's last safe day to post has passed but not the day it must arrive by:
    the ways its send advice allows that reach them today (:func:`~ordnung.rules.send.same_day_channels`
    — in person only, for a letter that must be signed by hand), or, without advice, none named."""
    if guidance is None or not guidance.channels:
        return MISSED_POST_NOTE
    ways = "; ".join(channel.label for channel in same_day_channels(guidance)) or "take it there yourself"
    return _MISSED_POST_WAYS.format(ways=ways)


def _cancellation_guidance(ledger: Ledger, contract: Contract | None) -> SendGuidance | None:
    """The send advice for cancelling ``contract`` (its form and channels, by its category)."""
    if contract is None:
        return None
    party = ledger.parties.get(contract.party_id) if contract.party_id else None
    return send_guidance(
        "cancellation",
        contract_category=contract.category,
        party_kind=party.kind if party else None,
        today=ledger.today,
    )


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
    for item in pending_items(ledger):
        if item.kind not in _NOW_KINDS or item.origin == "draft":
            continue
        due = parse_day(item.due_date)
        if is_past_due(item, today):
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


def _never_read(doc: Document) -> bool:
    """A letter kept private that no model read: Ordnung can't say what it asks, so never "nothing to do"."""
    return doc.ai_private and not doc.ai_processed_at


def _new_letters(ledger: Ledger, window: _Window, *, first: bool) -> WeekStep:
    open_by_doc = Counter(item.doc_id for item in pending_items(ledger))
    fresh = [doc for doc in ledger.documents.values() if window.after(doc.created_at)]
    unread = [doc for doc in ledger.documents.values() if not window.after(doc.created_at) and is_unread(doc)]

    def open_count(doc: Document) -> int:
        return open_by_doc[doc.id]

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
        if doc.status == "held":
            return _doc_entry(
                ledger, doc, note="Not read yet — read it with Claude or keep it private.", tone="warn"
            )
        if count:
            return _doc_entry(ledger, doc, note=_count(count, "open to-do"))
        if _never_read(doc):
            return _doc_entry(ledger, doc, note="Kept private — not read, so look through it yourself.")
        return _doc_entry(ledger, doc, note="Nothing to do — filed.", tone="ok")

    def needs_you(doc: Document) -> bool:
        return (
            bool(ledger.scam_reasons(doc))
            or doc.status != "processed"
            or open_count(doc) > 0
            or _never_read(doc)
        )

    newest = sorted([*fresh, *unread], key=lambda doc: (doc.created_at, doc.id), reverse=True)
    ordered = [doc for doc in newest if needs_you(doc)] + [doc for doc in newest if not needs_you(doc)]
    since = day_label(window.since_day, window.today)
    summary = f"{_count(len(fresh), 'letter')} since {since}" if fresh else f"No new letters since {since}"
    if unread:
        summary += f" · {_count(len(unread), 'older letter')} not read yet"
    title = f"New in the last {WEEK} days" if first else "New since your last review"
    return _step("new", title, [row(doc) for doc in ordered], summary)


def has_day_to_compare(item: Item) -> bool:
    """Whether a to-do has a day the person can compare with the letter (its due date or its send-by
    day). An undated to-do ("Return the form if you disagree") has none: *Compare with the letter* would
    ask them to confirm a date that isn't there; its letter is listed instead while it is marked *Please
    check*."""
    return parse_day(item.due_date) is not None or parse_day(item.send_by) is not None


def _to_check(ledger: Ledger) -> WeekStep:
    today = ledger.today
    rows: list[WeekEntry] = []
    covered: set[str] = set()
    for item in sorted(ledger.actionable_items(), key=lambda i: (action_day(i) or date.max, i.id)):
        reason = unconfirmed_reason(item)
        due = parse_day(item.due_date)
        if (
            reason is None
            or not has_day_to_compare(item)
            or (due is not None and due < today)
            or item.origin == "draft"
        ):
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
    summary = f"{_count(len(rows), 'thing')} to compare with the letter" if rows else "Nothing to compare"
    return _step("check", "Compare with the letter", rows, summary)


def _snoozed_payments(ledger: Ledger) -> list[Item]:
    """Payments snoozed until a later day (the agenda leaves them out) that its rule would list: overdue,
    or with a day to act within 7 days."""
    today = ledger.today
    found = []
    for item in pending_items(ledger):
        due, act = parse_day(item.due_date), _act_on(item, today)
        if (
            item.kind != "payment"
            or item.direction == "in"
            or is_active(item, today)  # awake: the agenda has it
            or due is None
            or act is None
        ):
            continue
        if is_past_due(item, today) or (due >= today and (act - today).days <= WEEK):
            found.append(item)
    return found


def _pay_order(item: Item, today: date) -> tuple[int, date]:
    """The agenda's order: overdue first (by due date), then by the day to act."""
    if is_past_due(item, today):
        return 0, parse_day(item.due_date) or today
    return 1, _act_on(item, today) or today


def _pay(ledger: Ledger, agenda: Agenda, money: MoneySummary) -> WeekStep:
    by_id = {item.id: item for item in ledger.items}
    listed = [
        by_id[entry.id]
        for entry in (*agenda.overdue, *agenda.today, *agenda.next_7_days)
        if entry.kind == "payment" and entry.id in by_id
    ]
    listed += [item for item in _snoozed_payments(ledger) if item.id not in {i.id for i in listed}]
    listed.sort(key=lambda item: _pay_order(item, ledger.today))  # stable: the agenda's order kept
    transfers, in_person, debits = [], [], []
    for item in listed:
        row = _item_entry(ledger, item)
        if row.date_role == "collected":
            debits.append(row.model_copy(update={"note": "Collected by direct debit: keep it covered."}))
            continue
        if row.date_role == "at_appointment":
            in_person.append(row.model_copy(update={"note": AT_APPOINTMENT_NOTE}))
            continue
        note = _missed_note(item, when(item, ledger.today))
        # the GiroCode policy's check (a letter's amount), never the to-do's grounding (about its date)
        if item.amount is not None and item.doc_id is not None and not amount_confirmed(ledger.store, item):
            note = " ".join(part for part in (note, UNCONFIRMED_AMOUNT_NOTE) if part)
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


def _unsent_entry(ledger: Ledger, draft: Draft) -> WeekEntry:
    """A letter to send: its send-by day, the day it must arrive by beside it; once the send-by day has
    passed but not the day to arrive by, act today — overdue only when that day has passed too, and
    counted as overdue unless a to-do of the letter it answers carries that same day and is counted
    (:func:`counts_overdue`; it is counted there)."""
    today = ledger.today
    guidance = draft.send_guidance
    send = parse_day(guidance.send_by) if guidance else None
    arrive = parse_day(guidance.must_arrive_by) if guidance else None
    due = arrive or send
    note = "Not sent yet — send it, then mark it as sent."
    if due is not None and due < today:
        carried = draft.doc_id is not None and any(
            item.doc_id == draft.doc_id and item.due_date == due.isoformat() and counts_overdue(item, today)
            for item in pending_items(ledger)
        )
        return _draft_entry(
            ledger,
            draft,
            date=due.isoformat(),
            date_role="due" if arrive else "send_by",
            note=note,
            tone="danger",
            overdue=not carried,
        )
    if send is not None and send < today:
        return _draft_entry(
            ledger,
            draft,
            date=today.isoformat(),
            date_role="act_today",
            due_date=due.isoformat() if due else None,
            note=f"{missed_post_note(guidance)} Then mark it as sent.",
            tone="warn",
        )
    shown = send or arrive
    return _draft_entry(
        ledger,
        draft,
        date=shown.isoformat() if shown else None,
        date_role=("send_by" if send else "due") if shown else None,
        due_date=arrive.isoformat() if arrive and send and arrive != send else None,
        note=note,
        tone="warn",
    )


def _sent_entry(ledger: Ledger, draft: Draft, window: _Window) -> WeekEntry | None:
    """A sent letter in *Post and keep proof* (module policy, step 4), or ``None``: one still waiting for
    its answer that lacks the proof its channel needs (:func:`~ordnung.drafts.proof.missing`, whenever it
    was sent), else one sent since the last session, saying it was delivered when a proof shows it."""
    today = ledger.today
    proofs = [
        RecordedProof(kind=proof.kind, on_date=proof.on_date, created_day="", note=proof.note, document=None)
        for proof in ledger.proofs_of(draft.id)
    ]
    lacking = missing(draft, proofs, answer=ledger.answer_of(draft), today=today)
    followup = ledger.followup_item(draft)
    settled = draft.answered_on is not None or followup is None or followup.status in ("done", "dismissed")
    sent = draft.sent_at[:10] if draft.sent_at else None
    if lacking and not settled:
        more = len(lacking) - 1
        note = lacking[0] + (f" (And {_count(more, 'thing')} more on the letter's page.)" if more else "")
        return _draft_entry(ledger, draft, date=sent, date_role="sent", note=note, tone="warn")
    if not window.on_or_after(draft.sent_at):
        return None
    delivered = delivered_on(ledger, draft)
    if delivered is not None:
        note = f"Delivered on {day_label(delivered, today)}, as your proof shows — keep it with a copy of the letter."
    elif lacking:
        note = lacking[0]
    elif proofs:
        note = "Its proof is kept in Ordnung — keep a copy of the letter as sent with it."
    else:
        note = DEFAULT_PROOF
    return _draft_entry(
        ledger,
        draft,
        date=sent,
        date_role="sent",
        note=note,
        tone="ok" if delivered or (proofs and not lacking) else "neutral",
    )


def _post(ledger: Ledger, drafts: Iterable[Draft], window: _Window) -> WeekStep:
    unsent: list[WeekEntry] = []
    sent: list[WeekEntry] = []
    for draft in drafts:
        if draft.status in ("draft", "final"):
            unsent.append(_unsent_entry(ledger, draft))
        elif draft.status == "sent" and (row := _sent_entry(ledger, draft, window)) is not None:
            sent.append(row)
    unsent.sort(key=lambda row: (row.date or "9999-12-31", row.key))
    sent.sort(key=lambda row: (row.date or "", row.key), reverse=True)
    sent.sort(key=lambda row: row.tone != "warn")  # stable: proof still to add first, newest first
    parts = [_count(len(unsent), "letter") + " to send"] if unsent else []
    lacking = sum(1 for row in sent if row.tone == "warn")
    if sent:
        whose = "its" if lacking == 1 else "their"
        parts.append(f"{len(sent)} sent" + (f" — {lacking} without all {whose} proof" if lacking else ""))
    return _step("post", "Post and keep proof", [*unsent, *sent], " · ".join(parts) or "Nothing to post")


#: The day a waited-for thing is expected by, by where it comes from (:mod:`ordnung.secretary.waiting`).
_WAITING_ROLE: dict[str, WeekDateRole] = {"letter": "reply_by", "money": "expected", "call": "promised_by"}
_WAITING_TONE = {"overdue": "danger", "answered": "warn"}


def _waiting_entry(ledger: Ledger, entry: WaitingEntry) -> WeekEntry:
    """A row of *Waiting for*: the *Waiting for* page's entry, in its words."""
    about = {"letter": f"Your letter “{entry.about}”: ", "call": f"{entry.about}: "}.get(entry.source, "")
    item = next((i for i in ledger.items if i.id == entry.ref.id), None) if entry.ref.type == "item" else None
    return WeekEntry.model_validate(
        {
            "key": f"waiting:{entry.id}",
            "ref": entry.ref,
            "title": entry.title,
            "kind": {"letter": "draft", "money": "payment", "call": "call"}[entry.source],
            "date": entry.expected_by,
            "date_role": _WAITING_ROLE[entry.source] if entry.expected_by else None,
            "amount": entry.amount,
            "currency": entry.currency,
            "party_id": entry.party_id,
            "party_name": entry.party_name,
            "doc_id": entry.doc_id,
            "status": entry.status,
            "note": about + entry.note,
            "tone": _WAITING_TONE.get(entry.status, "neutral"),
            "overdue": entry.status == "overdue",
            "item": item,
        }
    )


def _waiting(ledger: Ledger, entries: Sequence[WaitingEntry]) -> WeekStep:
    """*Waiting for*: the *Waiting for* page's open entries (:func:`~ordnung.secretary.waiting.waiting_for`)
    — replies to letters you sent, money a letter promised, promises made on the phone — in the page's order:
    overdue first, then those a letter may have answered."""
    rows = [_waiting_entry(ledger, entry) for entry in entries]
    late = sum(1 for entry in entries if entry.status == "overdue")
    if not rows:
        summary = "Not waiting for anything"
    else:
        summary = f"Waiting for {_count(len(rows), 'thing')}" + (f" · {late} overdue" if late else "")
    return _step("waiting", "Waiting for", rows, summary)


def _decide(ledger: Ledger, agenda: Agenda, acting_now: set[str]) -> WeekStep:
    today = ledger.today
    rows: list[WeekEntry] = [_contract_entry(ledger, entry) for entry in agenda.decisions]
    decided = {entry.id for entry in agenda.decisions}
    for item in pending_items(ledger):
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
    open_docs = {item.doc_id for item in pending_items(ledger) if item.doc_id}
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


def counts_overdue(item: Item, today: date) -> bool:
    """A deadline, payment or task past its due date, snoozed or not — not a letter's follow-up (the
    *Waiting for* entry counts it), a direct debit or money coming in."""
    return (
        item.kind in _OVERDUE_KINDS
        and item.origin != "draft"
        and _worth_acting(item)
        and is_past_due(item, today)
    )


def overdue_count(ledger: Ledger) -> int:
    """The to-dos :func:`counts_overdue` holds for (not those set aside)."""
    return sum(1 for item in pending_items(ledger) if counts_overdue(item, ledger.today))


def deadlines(ledger: Ledger, agenda: Agenda) -> list[WeekEntry]:
    """Every day to act from today on (module policy, "The ending"), the earliest first: open or snoozed
    to-dos not yet overdue, and the agenda's contract decisions. Each row's ``date`` is its day to act."""
    today = ledger.today
    found: list[tuple[date, str, Item | AgendaEntry]] = []
    for item in pending_items(ledger):
        due = parse_day(item.due_date)
        if not _worth_acting(item) or (due is not None and due < today):
            continue
        act = _act_on(item, today, in_person=paid_at_appointment(item, ledger.items))
        if act is not None:
            found.append((act, item.id, item))
    for decision in agenda.decisions:
        send = parse_day(decision.date)
        if send is not None:
            found.append((max(send, today), decision.id, decision))
    return [
        _contract_entry(ledger, record, note=None, tone="neutral")
        if isinstance(record, AgendaEntry)
        else _item_entry(ledger, record)
        for _, _, record in sorted(found, key=lambda chosen: chosen[:2])
    ]


def next_deadline(ledger: Ledger, agenda: Agenda) -> WeekEntry | None:
    """The earliest of :func:`deadlines` (``None``: nothing to act on from today on)."""
    found = deadlines(ledger, agenda)
    return found[0] if found else None


def build_weekly_session(
    ledger: Ledger, *, agenda: Agenda, money: MoneySummary, drafts: Sequence[Draft], state: SessionState
) -> WeeklySession:
    """The steps for ``ledger.today`` (module policy)."""
    today = ledger.today
    last = state.last_session
    since_day = last.day if last is not None else today - timedelta(days=WEEK)
    window = _Window(today=today, since_day=min(since_day, today), since_stamp=last.at if last else None)
    now, acting_now = _act_now(ledger)
    waiting = waiting_for(ledger)
    post = _post(ledger, drafts, window)
    steps = [
        *([now] if now is not None else []),
        _new_letters(ledger, window, first=last is None),
        _to_check(ledger),
        _pay(ledger, agenda, money),
        post,
        _waiting(ledger, waiting),
        _decide(ledger, agenda, acting_now),
        _file(ledger, window),
    ]
    unsent_overdue = sum(
        1 for draft in drafts if draft.status in ("draft", "final") and _unsent_entry(ledger, draft).overdue
    )
    overdue = (
        overdue_count(ledger) + unsent_overdue + sum(1 for entry in waiting if entry.status == "overdue")
    )
    has_something = any(step.entries for step in steps)
    upcoming = next_prompt_day(state, today)
    ahead = deadlines(ledger, agenda)
    return WeeklySession(
        today=today.isoformat(),
        since=window.since_day.isoformat(),
        last_session=last.day.isoformat() if last else None,
        due=has_something and prompt_due(state, today),
        next_prompt=upcoming.isoformat() if upcoming else None,
        minutes=MINUTES,
        steps=steps,
        overdue=overdue,
        next_deadline=ahead[0] if ahead else None,
        due_today=sum(1 for row in ahead if row.date == today.isoformat()),
    )
