"""What the person is waiting for: replies to letters they sent, money a letter promised them and
promises made on the phone — worked out on read from a :class:`~ordnung.secretary.triggers.Ledger`.

Policy (ADR 0006, 0007):

1. **Sent letters.** A letter marked as sent waits for what its kind asks for
   (:data:`ordnung.drafts.proof.WAITING_FOR`; an address change waits for nothing), expected by the
   date of its follow-up to-do (the person may move it). It is *answered* once
   :meth:`~ordnung.secretary.triggers.Ledger.reply_to` finds a letter linked to it (same thread, or a
   confirmation of the cancelled contract), *closed* once the person closed or deleted the follow-up,
   *overdue* after the expected day, else *waiting*.
2. **Money.** An open one-off payment to the person — a to-do of kind payment with direction ``in``
   and no recurrence, from a letter or typed in: a deposit or tax refund, a service-charge credit.
   Ordnung can't see a bank account, so it is waited for until the person marks it received (the
   to-do done), and overdue after its date. Recurring income (a salary, a stipend) is a schedule, not
   something owed; a letter with scam signs, or a date that was already history when the letter was
   filed, promises nothing.
3. **Calls.** A call note's promise with a date: *closed* once the person says it was kept, *answered*
   when a letter in the call's thread arrived on or after the call day, *overdue* after the promised
   day, else *waiting*. A promise without a date is only a note.
4. **Nothing is closed here.** *Answered* names the letter so the person can check it; closing is
   their click (ADR 0006).

Order: overdue, then waiting (by expected day, undated last), then answered.

Limits: a later letter of the same thread counts as the answer even when it is about something else
(it is named, so the person notices); money paid without a letter saying so stays "waiting" until the
person marks it received.
"""

from __future__ import annotations

from datetime import date

from ordnung.drafts.proof import channel_label, kind_info, waits_for
from ordnung.drafts.tracking import tracking_info
from ordnung.models import Area, CallNote, Document, Draft, Item, RefLink, WaitingEntry, WaitingStatus
from ordnung.secretary.triggers import (
    Ledger,
    contract_area,
    day_label,
    is_active,
    money,
    parse_day,
    was_history_when_filed,
)

_STATUS_ORDER: dict[str, int] = {"overdue": 0, "waiting": 1, "answered": 2, "closed": 3}


def _letter_day(doc: Document) -> date | None:
    return parse_day(doc.doc_date or doc.received_date or doc.created_at)


def _title(doc: Document) -> str:
    return doc.title or doc.filename


def _status(expected: date | None, today: date, *, answered: bool, closed: bool) -> WaitingStatus:
    if closed:
        return "closed"
    if answered:
        return "answered"
    return "overdue" if expected is not None and expected < today else "waiting"


# --------------------------------------------------------------------------------------------------
# sent letters
# --------------------------------------------------------------------------------------------------


def _letter_area(ledger: Ledger, draft: Draft) -> Area:
    contract = next((c for c in ledger.contracts if c.id == draft.contract_id), None)
    if contract is not None:
        return contract_area(contract)
    doc = ledger.document(draft.doc_id)
    return doc.area if doc is not None and doc.area else "other"


def _delivered_on(ledger: Ledger, draft: Draft) -> date | None:
    days = [
        day
        for proof in ledger.proofs_of(draft.id)
        if kind_info(proof.kind).arrival and (day := parse_day(proof.on_date)) is not None
    ]
    return min(days) if days else None


def _letter_note(ledger: Ledger, draft: Draft, status: WaitingStatus, reply: Document | None) -> str:
    today = ledger.today
    sent = parse_day(draft.sent_at)
    how = f" by {channel_label(draft.sent_channel)}" if draft.sent_channel else ""
    sent_words = f"Sent {day_label(sent, today)}{how}" if sent else f"Sent{how}"
    if status == "answered" and reply is not None:
        threaded = draft.case_id is not None and reply.case_id == draft.case_id
        link = "is in the same thread" if threaded else "confirms the cancellation"
        day = _letter_day(reply)
        when = f" of {day_label(day, today)}" if day else ""
        return f"Their letter “{_title(reply)}”{when} {link}. Check that it answers yours, then close this."
    if status == "closed":
        return f"{sent_words}. You closed the follow-up."
    delivered = _delivered_on(ledger, draft)
    proof = f" Your proof shows it was delivered on {day_label(delivered, today)}." if delivered else ""
    tracking = tracking_info(draft.tracking_number)
    number = f" Tracking number {tracking.display}." if tracking else ""
    if status == "overdue":
        return (
            f"{sent_words}; nothing linked to it has arrived since.{proof}{number} "
            "Send a short reminder or call them — and note what they say."
        )
    followup = ledger.followup_item(draft)
    remind = parse_day(followup.due_date) if followup else None
    later = f" Ordnung reminds you on {day_label(remind, today)} if nothing has come." if remind else ""
    return f"{sent_words}.{proof}{number}{later}"


def letter_entry(ledger: Ledger, draft: Draft) -> WaitingEntry | None:
    """The waiting entry of a sent letter (policy 1), closed ones included; ``None`` if it waits for nothing."""
    title = waits_for(draft.kind)
    if draft.status != "sent" or title is None:
        return None
    today = ledger.today
    followup = ledger.followup_item(draft)
    expected = parse_day(followup.due_date) if followup is not None else None
    reply = ledger.reply_to(draft)
    closed = followup is None or followup.status in ("done", "dismissed")
    status = _status(expected, today, answered=reply is not None, closed=closed)
    return WaitingEntry.model_validate(
        {
            "id": f"draft:{draft.id}",
            "source": "letter",
            "status": status,
            "title": title,
            "about": draft.subject or "Your letter",
            "note": _letter_note(ledger, draft, status, reply),
            "since": draft.sent_at[:10] if draft.sent_at else None,
            "expected_by": expected.isoformat() if expected else None,
            "party_id": draft.party_id,
            "party_name": ledger.party_name(draft.party_id),
            "area": _letter_area(ledger, draft),
            "ref": RefLink(type="draft", id=draft.id),
            "answered_by": RefLink(type="document", id=reply.id) if reply else None,
            "answered_on": (day.isoformat() if (day := _letter_day(reply)) else None) if reply else None,
            "followup_item_id": followup.id if followup is not None else None,
            "doc_id": draft.doc_id if ledger.document(draft.doc_id) else None,
        }
    )


# --------------------------------------------------------------------------------------------------
# money promised by a letter
# --------------------------------------------------------------------------------------------------


def _is_money_owed(ledger: Ledger, item: Item) -> bool:
    return (
        item.kind == "payment"
        and item.direction == "in"
        and item.recurrence is None
        and is_active(item, ledger.today)
        and not ledger.is_suspicious_item(item)
        and not was_history_when_filed(item)
    )


def _money_entry(ledger: Ledger, item: Item) -> WaitingEntry:
    today = ledger.today
    doc = ledger.document(item.doc_id)
    due = parse_day(item.due_date)
    status = _status(due, today, answered=False, closed=False)
    who = ledger.party_name(item.party_id)
    sum_words = money(item.amount, item.currency) if item.amount is not None else "The money"
    by = f" by {day_label(due, today)}" if due else ""
    if doc is not None:
        day = _letter_day(doc)
        source = f"Promised in “{_title(doc)}”" + (f" of {day_label(day, today)}" if day else "")
    else:
        source = "You noted this"
    if status == "overdue":
        ask = f"ask {who} about it" if who else "ask about it"
        note = f"{source}; it was due on {day_label(due, today) if due else ''}. If it hasn't arrived, {ask}."
    else:
        note = f"{source}: {sum_words}{by}. Ordnung can't see your bank account — mark it received when it arrives."
    since = (doc.doc_date if doc is not None and doc.doc_date else None) or item.created_at[:10]
    return WaitingEntry.model_validate(
        {
            "id": f"item:{item.id}",
            "source": "money",
            "status": status,
            "title": item.title,
            "about": _title(doc) if doc is not None else "Added by you",
            "note": note,
            "since": since,
            "expected_by": due.isoformat() if due else None,
            "party_id": item.party_id,
            "party_name": who,
            "amount": item.amount,
            "currency": item.currency,
            "area": item.area,
            "ref": RefLink(type="item", id=item.id),
            "followup_item_id": item.id,
            "doc_id": doc.id if doc is not None else None,
        }
    )


# --------------------------------------------------------------------------------------------------
# promises made on the phone
# --------------------------------------------------------------------------------------------------


def call_entry(ledger: Ledger, call: CallNote) -> WaitingEntry | None:
    """The waiting entry of a call note's dated promise (policy 3); ``None`` without one."""
    due = parse_day(call.promise_due)
    called = parse_day(call.called_on)
    if not call.promise or due is None or called is None:
        return None
    today = ledger.today
    answer = ledger.letter_after(call.case_id, called) if call.case_id else None
    status = _status(due, today, answered=answer is not None, closed=call.promise_kept_on is not None)
    who = call.contact or ledger.party_name(call.party_id) or "They"
    said = f"{who} promised this on the phone on {day_label(called, today)}, by {day_label(due, today)}."
    if status == "answered" and answer is not None:
        day = _letter_day(answer)
        when = f" of {day_label(day, today)}" if day else ""
        note = f"Their letter “{_title(answer)}”{when} arrived after the call — check whether it keeps the promise."
    elif status == "overdue":
        note = f"{said} Call them again and note what they say."
    elif status == "closed":
        kept = parse_day(call.promise_kept_on)
        note = f"Kept on {day_label(kept, today)}." if kept else "Kept."
    else:
        note = said
    area: Area = "other"
    case = ledger.store.get_case(call.case_id) if call.case_id else None
    if case is not None:
        area = case.area
    return WaitingEntry.model_validate(
        {
            "id": f"call:{call.id}",
            "source": "call",
            "status": status,
            "title": call.promise,
            "about": f"Call with {call.contact}" if call.contact else "Phone call",
            "note": note,
            "since": call.called_on,
            "expected_by": due.isoformat(),
            "party_id": call.party_id,
            "party_name": ledger.party_name(call.party_id),
            "amount": call.promise_amount,
            "area": area,
            "ref": RefLink(type="call", id=call.id),
            "answered_by": RefLink(type="document", id=answer.id) if answer else None,
            "answered_on": (day.isoformat() if (day := _letter_day(answer)) else None) if answer else None,
        }
    )


# --------------------------------------------------------------------------------------------------
# everything
# --------------------------------------------------------------------------------------------------


def _sort_key(entry: WaitingEntry) -> tuple[int, str, str]:
    return (_STATUS_ORDER[entry.status], entry.expected_by or "9999-99-99", entry.id)


def waiting_for(ledger: Ledger, *, include_closed: bool = False) -> list[WaitingEntry]:
    """Every waiting entry (policies 1–3), in the module's order; closed ones only when asked."""
    entries = [entry for draft in ledger.sent_drafts() if (entry := letter_entry(ledger, draft)) is not None]
    entries += [_money_entry(ledger, item) for item in ledger.items if _is_money_owed(ledger, item)]
    entries += [entry for call in ledger.call_notes() if (entry := call_entry(ledger, call)) is not None]
    if not include_closed:
        entries = [entry for entry in entries if entry.status != "closed"]
    return sorted(entries, key=_sort_key)
