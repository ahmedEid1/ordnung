"""Calendar export (SPEC §12): open dated to-dos and contract decision dates as an ``.ics`` file.

* One VEVENT per open (or snoozed) to-do with a date — all-day unless it has a time, which is then
  written in the person's time zone (with its VTIMEZONE). To-dos of letters with scam signs are left
  out, and so are invoice payments a later payment reminder took over (the reminder's is the one).
  The summary starts with a symbol per kind, and with ``⚠ check:`` when the date still needs the
  person's confirmation; the description says what to do, what happens otherwise, why this date and
  who it is with, and that it is not legal advice.
* For contracts with a renewal decision: a "post your cancellation" event on the send-by day and a
  "cancellation must arrive" event on the cancel-by day.
* VALARMs from ``Profile.reminder_days`` for the item's kind (09:00 local on the day for all-day
  events), plus one on the send-by day of a letter that must be posted before its deadline.
* UIDs are stable (``<id>@ordnung.local``) so re-importing updates events instead of duplicating
  them; DTSTAMP is the record's last change, so the same ledger always gives the same bytes.

:func:`mark_exported` stores when the person last exported (meta ``last_calendar_export_at``),
which drives the "new dates since your last calendar update" Idea.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from icalendar import Alarm, Calendar, Event

from ordnung.clock import now_iso
from ordnung.db.store import NotFoundError, Store
from ordnung.models import Contract, ContractComputation, Item, Profile
from ordnung.rules.explain import fmt_date
from ordnung.secretary.triggers import (
    CALENDAR_META_KEY,
    Ledger,
    eur,
    is_decision,
    parse_day,
    parse_timestamp,
)
from ordnung.tick import local_today

CALENDAR_NAME = "Ordnung"
PRODID = "-//Ordnung//Ordnung calendar export//EN"
UID_DOMAIN = "ordnung.local"
CHECK_PREFIX = "⚠ check: "
DONE_PREFIX = "✓ "
DISCLAIMER = "Not legal advice."
DEFAULT_TIMEZONE = "Europe/Berlin"
ALARM_HOUR = 9
EVENT_MINUTES = 60
SAME_DAY_TIMED_ALARM = timedelta(hours=-1)
OPEN_STATUSES = frozenset({"open", "snoozed"})
KIND_SYMBOLS: dict[str, str] = {
    "deadline": "⚑",
    "payment": "€",
    "appointment": "◷",
    "task": "☐",
    "expiry": "⌛",
    "reminder": "•",
    "milestone": "★",
}
SEND_BY_SYMBOL = "✉"
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def _zone(profile: Profile) -> ZoneInfo:
    try:
        return ZoneInfo(profile.timezone or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def _stamp(value: str | None) -> datetime:
    moment = parse_timestamp(value)
    return moment.astimezone(UTC) if moment else _EPOCH


def _uid(key: str) -> str:
    return f"{key}@{UID_DOMAIN}"


def item_uid(item_id: str) -> str:
    """The stable UID of a to-do's event."""
    return _uid(item_id)


def needs_check(item: Item) -> bool:
    """A date read from a letter that the person hasn't confirmed and Ordnung couldn't verify."""
    if item.origin != "extracted" or item.grounding == "user":
        return False
    unsure_evidence = any(not evidence.value_consistent for evidence in item.evidence)
    low_confidence = item.computation is not None and item.computation.confidence == "low"
    return item.grounding == "unverified" or unsure_evidence or low_confidence


def _parse_time(value: str | None) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------------
# alarms
# --------------------------------------------------------------------------------------------------


def _alarm(trigger: timedelta, text: str) -> Alarm:
    alarm = Alarm()
    alarm.add("action", "DISPLAY")
    alarm.add("description", text)
    alarm.add("trigger", trigger)
    return alarm


def _day_trigger(days_before: int, timed: bool) -> timedelta:
    """Offset from the event start: 09:00 local ``days_before`` days earlier (timed: same time)."""
    if timed:
        return timedelta(days=-days_before) if days_before else SAME_DAY_TIMED_ALARM
    return timedelta(days=-days_before, hours=ALARM_HOUR)


def _alarms(
    summary: str, days: Iterable[int], *, timed: bool, start: datetime | date, send_by: date | None = None
) -> list[Alarm]:
    triggers: dict[timedelta, str] = {}
    for days_before in sorted({day for day in days if day >= 0}, reverse=True):
        when = "today" if days_before == 0 else f"in {days_before} day{'s' if days_before != 1 else ''}"
        triggers.setdefault(_day_trigger(days_before, timed), f"{summary} — {when}")
    if send_by is not None:
        start_day = start.date() if isinstance(start, datetime) else start
        if timed and isinstance(start, datetime):
            morning = datetime.combine(send_by, time(ALARM_HOUR), tzinfo=start.tzinfo)
            offset = morning - start
        else:
            offset = timedelta(days=(send_by - start_day).days, hours=ALARM_HOUR)
        triggers.setdefault(offset, f"{summary} — post it today")
    return [_alarm(trigger, text) for trigger, text in sorted(triggers.items())]


# --------------------------------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------------------------------


def _base_event(uid: str, summary: str, description: str, stamp: datetime) -> Event:
    event = Event()
    event.add("uid", uid)
    event.add("dtstamp", stamp)
    event.add("last-modified", stamp)
    event.add("summary", summary)
    event.add("description", description)
    return event


def _set_all_day(event: Event, day: date) -> None:
    event.add("dtstart", day)
    event.add("dtend", day + timedelta(days=1))
    event.add("transp", "TRANSPARENT")


def _item_summary(item: Item) -> str:
    symbol = KIND_SYMBOLS.get(item.kind, "•")
    text = f"{symbol} {item.title}"
    if item.status not in OPEN_STATUSES:
        return DONE_PREFIX + text
    return CHECK_PREFIX + text if needs_check(item) else text


def _amount(item: Item) -> str | None:
    if item.amount is None:
        return None
    if (item.currency or "EUR").upper() == "EUR":
        return eur(item.amount)
    return f"{item.amount:.2f} {item.currency}"


def _item_description(ledger: Ledger, item: Item, due: date, send_by: date | None) -> str:
    doc = ledger.document(item.doc_id)
    party = ledger.party_name(item.party_id or (doc.party_id if doc else None))
    amount = _amount(item)
    receipt = item.computation.summary if item.computation else None
    lines = [
        f"What to do: {item.action}" if item.action else None,
        f"Post it by {fmt_date(send_by)} so it arrives by {fmt_date(due)}." if send_by else None,
        f"If ignored: {item.consequence}" if item.consequence else None,
        f"Amount: {amount}" if amount else None,
        f"Why this date: {receipt}" if receipt else None,
        f"With: {party}" if party else None,
        "Please check this date in Ordnung — it couldn't be confirmed in the letter."
        if needs_check(item) and item.status in OPEN_STATUSES
        else None,
        DISCLAIMER,
    ]
    return "\n".join(line for line in lines if line)


def item_event(ledger: Ledger, item: Item, profile: Profile) -> Event:
    """The calendar event of one dated to-do (with its reminders while it is open)."""
    due = parse_day(item.due_date)
    if due is None:
        raise ValueError("This to-do has no date to add to a calendar.")
    send = parse_day(item.send_by)
    send_by = send if send is not None and send < due else None
    summary = _item_summary(item)
    event = _base_event(
        _uid(item.id), summary, _item_description(ledger, item, due, send_by), _stamp(item.updated_at)
    )
    start_time = _parse_time(item.due_time)
    start: datetime | date
    if start_time is None:
        start = due
        _set_all_day(event, due)
    else:
        start = datetime.combine(due, start_time, tzinfo=_zone(profile))
        event.add("dtstart", start)
        event.add("dtend", start + timedelta(minutes=EVENT_MINUTES))
    if item.location:
        event.add("location", item.location)
    event.add("categories", [item.kind])
    if item.status in OPEN_STATUSES:
        days = profile.reminder_days.get(item.kind, [])
        for alarm in _alarms(summary, days, timed=start_time is not None, start=start, send_by=send_by):
            event.add_component(alarm)
    return event


def _contract_description(ledger: Ledger, contract: Contract, comp: ContractComputation) -> str:
    party = ledger.party_name(contract.party_id)
    monthly = contract.monthly_cost()
    lines = [
        comp.summary or None,
        f"With: {party}" if party else None,
        f"Costs {eur(monthly)} a month." if monthly is not None else None,
        "Draft the cancellation in Ordnung (Letters) if you want to leave.",
        DISCLAIMER,
    ]
    return "\n".join(line for line in lines if line)


def contract_events(ledger: Ledger, contract: Contract, profile: Profile) -> list[Event]:
    """Send-by and cancel-by events of a contract renewal decision (reminders on the day to act)."""
    comp = ledger.computation(contract)
    cancel_by, send_by = parse_day(comp.cancel_by), parse_day(comp.send_by)
    if not is_decision(comp) or cancel_by is None:
        return []
    description = _contract_description(ledger, contract, comp)
    stamp = _stamp(contract.updated_at)
    reminders = profile.reminder_days.get("deadline", [])
    events: list[Event] = []
    separate_send = send_by is not None and send_by < cancel_by
    if send_by is not None and separate_send:
        summary = f"{SEND_BY_SYMBOL} Post your cancellation: {contract.name}"
        event = _base_event(_uid(f"{contract.id}-send-by"), summary, description, stamp)
        _set_all_day(event, send_by)
        for alarm in _alarms(summary, reminders, timed=False, start=send_by):
            event.add_component(alarm)
        events.append(event)
    summary = f"{KIND_SYMBOLS['deadline']} Cancellation must arrive: {contract.name}"
    event = _base_event(_uid(f"{contract.id}-cancel-by"), summary, description, stamp)
    _set_all_day(event, cancel_by)
    if not separate_send:
        for alarm in _alarms(summary, reminders, timed=False, start=cancel_by):
            event.add_component(alarm)
    events.append(event)
    return events


# --------------------------------------------------------------------------------------------------
# the calendar
# --------------------------------------------------------------------------------------------------


def _calendar(profile: Profile) -> Calendar:
    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("x-wr-calname", CALENDAR_NAME)
    calendar.add("x-wr-timezone", str(_zone(profile)))
    return calendar


def _exported_items(ledger: Ledger, include_done: bool) -> list[Item]:
    """Dated to-dos, without letters with scam signs and without invoice payments a later payment
    reminder took over (the reminder is the one to act on, as on the agenda)."""
    return [
        item
        for item in ledger.items
        if item.due_date
        and (include_done or item.status in OPEN_STATUSES)
        and not ledger.is_suspicious_item(item)
        and not ledger.is_superseded_by_reminder(item)
    ]


def _events(
    store: Store, ledger: Ledger, profile: Profile, include_done: bool, only_item_id: str | None
) -> list[Event]:
    if only_item_id is not None:
        item = store.get_item(only_item_id)
        if item is None:
            raise NotFoundError(f"items: no row with id {only_item_id!r}")
        return [item_event(ledger, item, profile)]
    events = [item_event(ledger, item, profile) for item in _exported_items(ledger, include_done)]
    confirmed = ledger.pending_confirmations()
    for contract in ledger.active_contracts():
        if contract.id not in confirmed:
            events.extend(contract_events(ledger, contract, profile))
    return events


def _sort_key(event: Event) -> tuple[str, str]:
    start = event.decoded("dtstart")
    return (start.isoformat(), str(event.get("uid")))


def build_ics(store: Store, *, include_done: bool = False, only_item_id: str | None = None) -> bytes:
    """The ``.ics`` export: every open dated to-do and contract decision, or just ``only_item_id``.

    ``include_done`` also exports finished, dismissed and missed to-dos (without reminders). Raises
    :class:`~ordnung.db.store.NotFoundError` for an unknown ``only_item_id`` and ``ValueError`` when
    that to-do has no date.
    """
    profile = store.get_profile()
    ledger = Ledger(store, local_today(store))
    calendar = _calendar(profile)
    for event in sorted(_events(store, ledger, profile, include_done, only_item_id), key=_sort_key):
        calendar.add_component(event)
    calendar.add_missing_timezones()
    return bytes(calendar.to_ical())


def mark_exported(store: Store) -> str:
    """Remember that the person exported the calendar now; returns the stored timestamp."""
    stamp = now_iso()
    store.set_meta(CALENDAR_META_KEY, stamp)
    return stamp
