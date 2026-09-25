"""Recurring obligations: regression tests from the review rounds, restated for the schedule policy
(ordnung.recurrence): whatever was ticked off, a series moves on and is never held back as unpaid."""

from __future__ import annotations

from datetime import date

from ordnung.db.store import Store
from ordnung.models import DateSpec, Item, Recurrence
from ordnung.recurrence import moved_on, rolled
from ordnung.rules import RuleContext
from ordnung.secretary.triggers import is_direct_debit, is_overdue

MONTHLY = Recurrence(interval=1, unit="months")
BUFFER = 3


def _paid(item: Item, day: date) -> Item:
    moved = moved_on(item, RuleContext(today=day), postal_buffer_days=BUFFER)
    assert moved is not None and moved.status == "open"
    return moved


def _roll_on(item: Item, days: list[date]) -> Item:
    for day in days:
        item = rolled(item, RuleContext(today=day), postal_buffer_days=BUFFER) or item
    return item


def test_a_paid_occurrence_does_not_depend_on_how_often_the_roll_runs(store: Store) -> None:
    """Rent due 1 Oct is paid early. Whether Ordnung then runs daily or not until 2 Nov, the ledger is
    the same (it used to depend on when the roll happened to run)."""
    rent = store.add_item(
        kind="payment",
        title="Rent",
        due_date="2026-10-01",
        date_spec=DateSpec(type="fixed", date="2026-01-01", nature="payment"),
        recurrence=MONTHLY,
        amount=800.0,
    )
    paid = _paid(rent, date(2026, 9, 25))
    daily = _roll_on(paid, [date(2026, 10, 2), date(2026, 11, 2)])
    late = _roll_on(paid, [date(2026, 11, 2)])
    assert (daily.status, daily.due_date) == (late.status, late.due_date) == ("open", "2026-12-01")


def test_a_recurring_direct_debit_ticked_off_once_is_never_overdue(store: Store) -> None:
    """Most recurring payments in Germany are direct debits: the sender collects them. After the person
    ticked one collection off, the next ones must not turn overdue (inviting a transfer on top of the
    debit): the series moves on to the next collection."""
    debit = store.add_item(
        kind="payment",
        title="Rundfunkbeitrag",
        action="Wird per Lastschrift von Ihrem Konto abgebucht",
        due_date="2026-10-15",
        date_spec=DateSpec(type="fixed", date="2026-01-15", nature="payment"),
        recurrence=MONTHLY,
        amount=18.36,
    )
    item = _roll_on(_paid(debit, date(2026, 9, 25)), [date(2026, 11, 16), date(2026, 11, 20)])
    assert is_direct_debit(item)
    assert not is_overdue(item, date(2026, 11, 20)), item.due_date
    assert item.due_date == "2026-12-15"


def test_recurring_money_coming_in_moves_on_after_it_was_ticked_off(store: Store) -> None:
    received = store.add_item(
        kind="payment",
        title="Scholarship",
        direction="in",
        due_date="2026-10-01",
        date_spec=DateSpec(type="fixed", date="2026-01-01", nature="payment"),
        recurrence=MONTHLY,
        amount=300.0,
    )
    item = _roll_on(_paid(received, date(2026, 10, 1)), [date(2026, 10, 2), date(2026, 11, 20)])
    assert (item.status, item.due_date) == ("open", "2026-12-01")


def test_a_recurring_appointment_moves_on_after_one_was_marked_done(store: Store) -> None:
    """A weekly appointment ticked off once must not stop at the next session and sit in the past
    (missing from Today, the Timeline and the calendar feed)."""
    attended = store.add_item(
        kind="appointment",
        title="Physiotherapy",
        due_date="2026-10-05",
        date_spec=DateSpec(type="fixed", date="2026-10-05", nature="appointment"),
        recurrence=Recurrence(interval=1, unit="weeks"),
    )
    item = _roll_on(_paid(attended, date(2026, 10, 5)), [date(2026, 10, 6), date(2026, 10, 20)])
    assert not is_overdue(item, date(2026, 10, 20))
    assert (item.status, item.due_date) == ("open", "2026-10-26")
