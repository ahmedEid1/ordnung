"""What the person got from one letter, as plain data: the harness fills it, the checker judges it.

Nothing here imports the app: the calendar file is read with ``icalendar`` and the PDF with ``pypdfium2``, as a
calendar program or a PDF viewer would. An observation holds a letter's own words (to-do titles and quotes, the
draft's text) for the checker; none of them is ever written to the results (:mod:`evals.e2e.report`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal

from icalendar import Calendar
from pydantic import BaseModel, ConfigDict, Field

#: Why the app keeps a to-do off the calendar, the agenda and Today (``Ledger.is_set_aside``, and the calendar's
#: own "a one-off whose date had long passed when its letter was read").
SetAsideCause = Literal["scam_signs", "superseded_by_reminder", "covered_by_attachment", "history_when_filed"]


class _Data(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StoredItem(_Data):
    """One to-do the app stored for the letter."""

    id: str
    kind: str
    title: str = ""
    quote: str = ""
    due_date: str | None = None
    send_by: str | None = None
    amount: float | None = None
    status: str = "open"
    set_aside: list[SetAsideCause] = Field(default_factory=list)


class CalendarEvent(_Data):
    """One event of the calendar export: its day and the days its alarms fire on (the person's local days)."""

    uid: str
    #: the to-do the event belongs to (``None``: a contract decision's event)
    item_id: str | None = None
    start: str
    alarm_days: list[str] = Field(default_factory=list)


class AgendaProbe(_Data):
    """The to-dos the agenda behind the morning notification lists on ``day`` (overdue, today, next 7 days)."""

    day: str
    item_ids: list[str] = Field(default_factory=list)


class IdeaSeen(_Data):
    """One Idea after the daily tick: its rule, its day and what it refers to."""

    rule_id: str
    kind: str
    due_date: str | None = None
    item_ids: list[str] = Field(default_factory=list)
    doc_ids: list[str] = Field(default_factory=list)


class DraftSeen(_Data):
    """An objection letter as the person gets it (or the refusal to draft one)."""

    refused: bool = False
    #: the exception's type when the app refused or failed (never its message)
    error: str | None = None
    recipient_block: str = ""
    must_arrive_by: str | None = None
    send_by: str | None = None
    #: the text lines of the PDF, as a PDF reader extracts them
    pdf_lines: list[str] = Field(default_factory=list)
    #: the name the letter is signed with (the profile's)
    signer: str = ""
    #: the ids of the app's own draft checks that failed
    own_checks_failed: list[str] = Field(default_factory=list)


class LetterObservation(_Data):
    """Everything the harness saw for one benchmark letter."""

    entry_id: str
    #: the document's status after reading (``processed``, ``needs_review``, ``failed``)
    status: str = "processed"
    hidden_text: bool = False
    #: the app's scam verdict for the letter, as reason codes (:func:`evals.e2e.harness.reason_codes`)
    scam_reasons: list[str] = Field(default_factory=list)
    items: list[StoredItem] = Field(default_factory=list)
    events: list[CalendarEvent] = Field(default_factory=list)
    agenda: list[AgendaProbe] = Field(default_factory=list)
    ideas: list[IdeaSeen] = Field(default_factory=list)
    #: the objection letter asked for on a letter labelled with an Einspruch or Widerspruch
    draft: DraftSeen | None = None
    #: an objection letter asked for on a letter labelled without a remedy
    objection_on_none: Literal["refused", "drafted"] | None = None
    #: days ahead an item of a kind becomes an Idea (the profile's longest reminder)
    reminder_windows: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------------------------------
# reading what the person gets
# --------------------------------------------------------------------------------------------------


def _start_day(start: date | datetime) -> date:
    return start.date() if isinstance(start, datetime) else start


def _alarm_day(start: date | datetime, trigger: timedelta | datetime) -> date:
    """The local day an alarm fires on: an absolute trigger's own day, else the event's start plus the offset
    (an all-day event starts at 00:00 of its day)."""
    if isinstance(trigger, datetime):
        return trigger.date()
    begin = start if isinstance(start, datetime) else datetime.combine(start, datetime.min.time())
    return (begin + trigger).date()


def calendar_events(ics: bytes) -> list[CalendarEvent]:
    """Every event of an ``.ics`` file with the days its alarms fire on, in the file's order."""
    events = []
    for component in Calendar.from_ical(ics).walk("VEVENT"):
        start = component.decoded("dtstart")
        days = sorted(
            {_alarm_day(start, alarm.decoded("trigger")).isoformat() for alarm in component.walk("VALARM")}
        )
        events.append(
            CalendarEvent(uid=str(component.get("uid")), start=_start_day(start).isoformat(), alarm_days=days)
        )
    return events


def pdf_lines(data: bytes) -> list[str]:
    """The non-empty text lines of a PDF, page by page, as a PDF reader extracts them."""
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        lines: list[str] = []
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                text = textpage.get_text_range()
            finally:
                textpage.close()
                page.close()
            lines.extend(line.strip() for line in text.splitlines() if line.strip())
        return lines
    finally:
        document.close()
