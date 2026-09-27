"""Call notes (Gesprächsnotizen): what the person noted about a phone call — when, with whom, what was
said and what was promised. No model is involved; the note is theirs, word for word.

Policy:

* A note belongs to a person or organisation, a thread, or both (a thread brings its sender along).
* The call can't be in the future. A promise may have a day (then it is waited for,
  :mod:`ordnung.secretary.waiting`) and an amount; neither makes sense without the promise itself, and a
  promised day can't lie before the call.
* "Kept" is the person's click (it closes the waiting entry); it can be taken back.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ordnung.db.store import NotFoundError, Store
from ordnung.models import CallNote
from ordnung.secretary.triggers import parse_day

MAX_SUMMARY = 2000
MAX_PROMISE = 300
MAX_CONTACT = 120


class CallNoteError(ValueError):
    """A call note that can't be saved; the message is written for the person."""


def _clean(text: str | None) -> str | None:
    return " ".join(text.split()) if text and text.strip() else None


def add_call_note(
    store: Store,
    *,
    today: date,
    called_on: str,
    summary: str,
    party_id: str | None = None,
    case_id: str | None = None,
    contact: str | None = None,
    promise: str | None = None,
    promise_due: str | None = None,
    promise_amount: float | None = None,
) -> CallNote:
    """Save a call note by the module's policy (raises :class:`CallNoteError` with the reason)."""
    case = store.get_case(case_id) if case_id else None
    if case_id and case is None:
        raise CallNoteError("That thread isn't in Ordnung any more.")
    party_id = party_id or (case.party_id if case else None)
    if not party_id and not case_id:
        raise CallNoteError("Choose who you spoke to.")
    if party_id and store.get_party(party_id) is None:
        raise CallNoteError("That person or organisation isn't in Ordnung any more.")
    called = parse_day(called_on)
    if called is None:
        raise CallNoteError(f"“{called_on}” is not a date.")
    if called > today:
        raise CallNoteError("The call can't be in the future.")
    text = (summary or "").strip()
    if not text:
        raise CallNoteError("Write down what was said.")
    promised = _clean(promise)
    due = parse_day(promise_due) if promise_due else None
    if (due is not None or promise_amount is not None) and not promised:
        raise CallNoteError("Say what they promised, too.")
    if due is not None and due < called:
        raise CallNoteError("The promised day is before the call.")
    fields: dict[str, Any] = {
        "party_id": party_id,
        "case_id": case_id,
        "called_on": called.isoformat(),
        "contact": _clean(contact),
        "summary": text[:MAX_SUMMARY],
        "promise": promised[:MAX_PROMISE] if promised else None,
        "promise_due": due.isoformat() if due else None,
        "promise_amount": promise_amount,
    }
    with store.tx():
        note = store.add_call_note(**fields)
        store.log_activity(
            "call.noted",
            f"Noted a call on {note.called_on}" + (f" with {note.contact}" if note.contact else ""),
            ref_type="party" if note.party_id else "case",
            ref_id=note.party_id or note.case_id,
        )
    return note


def mark_kept(store: Store, call_id: str, kept: bool, today: date) -> CallNote:
    """Say a call's promise was kept (``kept``) or take that back."""
    note = store.get_call_note(call_id)
    if note is None:
        raise NotFoundError(f"call_notes: no row with id {call_id!r}")
    if not note.promise:
        raise CallNoteError("This call has no promise to keep.")
    return store.update_call_note(call_id, promise_kept_on=today.isoformat() if kept else None)
