"""Recurring obligations are schedules (ordnung.recurrence): each test pins one point of the policy.

1 never overdue · 2 the schedule is (first occurrence, rule) · 3 as days pass, the first occurrence on
or after today · 4 done moves on and stays open (Undo brings it back), dismissed ends it · 5 every
occurrence's dates and receipt from the rules engine · 6 reading again never moves it backwards · 7 a
date set by hand stands in for the occurrence it replaced and is kept until it passes. Realistic histories through the API are in ``test_regressions_recurrence.py``.
"""

from __future__ import annotations

from datetime import date

import pytest

from helpers_secretary import add_doc
from ordnung.db.store import Store
from ordnung.ingest.plan import item_context
from ordnung.ingest.verify import MODEL_READ_NOTE, REASON_TEXT
from ordnung.models import ComputationReceipt, DateSpec, Item, Recurrence
from ordnung.recurrence import (
    SCHEDULE_FIELDS,
    at_occurrence,
    describe,
    first_occurrence,
    keeps_later_date,
    mark_done,
    moved_on,
    next_occurrence,
    occurrence,
    replaced_occurrence,
    roll_forward,
    roll_item,
    rolled,
    same_rule,
    standing_in,
    undo_done,
)
from ordnung.rules import RuleContext
from ordnung.secretary.triggers import is_overdue

MONTHLY = Recurrence(interval=1, unit="months")
TODAY = date(2026, 9, 28)
BUFFER = 3


def nationwide(store: Store, item: Item, today: date) -> RuleContext:
    return RuleContext(today=today)


def _item(store: Store, **fields: object) -> Item:
    base = {
        "kind": "payment",
        "title": "Monthly advance payment",
        "due_date": "2025-10-15",
        "date_spec": DateSpec(type="fixed", date="2025-10-15", nature="payment"),
        "recurrence": MONTHLY,
        "amount": 48.0,
        "direction": "out",
        "due_date_source": "fixed",
    }
    return store.add_item(**{**base, **fields})


def _dates(store: Store, item_id: str) -> tuple[str, str | None, str | None]:
    item = store.get_item(item_id)
    assert item is not None
    return item.status, item.due_date, item.send_by


# --------------------------------------------------------------------------------------------------
# the schedule
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "rule", "after", "expected"),
    [
        (date(2025, 10, 15), MONTHLY, date(2026, 9, 28), date(2026, 10, 15)),
        (date(2025, 10, 15), MONTHLY, date(2026, 10, 15), date(2026, 10, 15)),
        (date(2026, 1, 31), MONTHLY, date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 1, 31), MONTHLY, date(2026, 3, 1), date(2026, 3, 31)),
        (date(2024, 2, 29), Recurrence(interval=1, unit="years"), date(2025, 1, 1), date(2025, 2, 28)),
        (date(2026, 2, 15), Recurrence(interval=3, unit="months"), date(2026, 9, 28), date(2026, 11, 15)),
        (date(2026, 9, 1), Recurrence(interval=2, unit="weeks"), date(2026, 9, 28), date(2026, 9, 29)),
        (date(2026, 12, 1), MONTHLY, date(2026, 9, 28), date(2026, 12, 1)),
    ],
)
def test_next_occurrence(first: date, rule: Recurrence, after: date, expected: date) -> None:
    assert next_occurrence(first, rule, after) == expected


def test_month_steps_keep_the_original_day() -> None:
    assert [occurrence(date(2026, 1, 31), MONTHLY, n) for n in range(4)] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]


def test_describe() -> None:
    assert describe(MONTHLY) == "every month"
    assert describe(Recurrence(interval=3, unit="months")) == "every 3 months"


def test_rules_that_give_the_same_dates_are_one_rule() -> None:
    assert same_rule(Recurrence(interval=1, unit="years"), Recurrence(interval=12, unit="months"))
    assert same_rule(Recurrence(interval=2, unit="weeks"), Recurrence(interval=14, unit="days"))
    assert same_rule(Recurrence(interval=0, unit="months"), MONTHLY)  # occurrence() steps at least 1
    assert not same_rule(Recurrence(interval=1, unit="years"), MONTHLY)
    assert not same_rule(MONTHLY, None) and same_rule(None, None)


# --------------------------------------------------------------------------------------------------
# 1. never overdue because a month passed
# --------------------------------------------------------------------------------------------------


def test_a_recurring_item_is_never_overdue(store: Store) -> None:
    """Even before the day's roll moved it on, a schedule is not an unpaid bill; a one-off one is."""
    recurring = _item(store, due_date="2026-09-15")
    one_off = _item(store, due_date="2026-09-15", recurrence=None)
    assert not is_overdue(recurring, TODAY)
    assert is_overdue(one_off, TODAY)


# --------------------------------------------------------------------------------------------------
# 2. the schedule is (first occurrence, rule)
# --------------------------------------------------------------------------------------------------


def test_the_schedule_starts_at_the_fixed_date_spec(store: Store) -> None:
    """The stored date is only where the schedule stands: occurrences are counted from the DateSpec,
    so a month-end schedule keeps its day after February."""
    advance = _item(store, due_date="2026-06-15")
    month_end = _item(
        store,
        due_date="2026-02-28",
        date_spec=DateSpec(type="fixed", date="2026-01-31", nature="payment"),
    )
    assert first_occurrence(advance, RuleContext(today=TODAY)) == date(2025, 10, 15)
    moved = rolled(advance, RuleContext(today=TODAY), postal_buffer_days=BUFFER)
    assert moved is not None and moved.due_date == "2026-10-15"
    moved = rolled(month_end, RuleContext(today=date(2026, 3, 1)), postal_buffer_days=BUFFER)
    assert moved is not None and moved.due_date == "2026-03-31"


def test_a_relative_date_spec_is_counted_in_its_letters_context(store: Store) -> None:
    """10 days after the letter of 21 Jan is Sat 31 Jan (the payment moves to Mon 2 Feb): the schedule
    starts on the 31st, as counted before the weekend moved it, so February's is on the 28th, not the
    2nd. Without the letter's date the schedule runs from the item's current date."""
    item = _item(
        store,
        due_date="2026-02-02",
        date_spec=DateSpec(type="relative", amount=10, unit="days", anchor="document_date", nature="payment"),
    )
    letter = RuleContext(today=date(2026, 2, 3), document_date=date(2026, 1, 21))
    assert first_occurrence(item, letter) == date(2026, 1, 31)
    moved = rolled(item, letter, postal_buffer_days=BUFFER)
    assert moved is not None and moved.due_date == "2026-02-28"
    assert first_occurrence(item, RuleContext(today=date(2026, 2, 3))) == date(2026, 2, 2)


# --------------------------------------------------------------------------------------------------
# 3. as days pass: the first occurrence on or after today
# --------------------------------------------------------------------------------------------------


def test_roll_forward_moves_open_and_snoozed_recurring_items_only(store: Store) -> None:
    recurring = _item(store)
    snoozed = _item(store, status="snoozed", snoozed_until="2026-10-02")
    dismissed = _item(store, status="dismissed")
    one_off = _item(store, recurrence=None)
    future = _item(store, due_date="2026-12-15", date_spec=DateSpec(type="fixed", date="2026-12-15"))

    assert roll_forward(store, TODAY, nationwide) == 2
    assert _dates(store, recurring.id)[:2] == ("open", "2026-10-15")
    moved = store.get_item(snoozed.id)
    assert moved is not None
    assert (moved.status, moved.snoozed_until, moved.due_date) == ("snoozed", "2026-10-02", "2026-10-15")
    assert _dates(store, dismissed.id)[:2] == ("dismissed", "2025-10-15")  # a dismissed series has ended
    assert _dates(store, one_off.id)[:2] == ("open", "2025-10-15")
    assert _dates(store, future.id)[:2] == ("open", "2026-12-15")
    assert roll_forward(store, TODAY, nationwide) == 0  # idempotent


def test_the_roll_does_not_depend_on_how_often_it_runs(store: Store) -> None:
    """Ordnung opened every day or once after three months: the same occurrence."""
    daily, once = _item(store, due_date="2026-10-15"), _item(store, due_date="2026-10-15")
    context = RuleContext(today=date(2026, 12, 20))
    day = date(2026, 10, 1)
    item = daily
    while day <= date(2026, 12, 20):
        item = rolled(item, RuleContext(today=day), postal_buffer_days=BUFFER) or item
        day = date.fromordinal(day.toordinal() + 1)
    late = rolled(once, context, postal_buffer_days=BUFFER)
    assert late is not None
    assert (item.status, item.due_date, item.send_by) == (late.status, late.due_date, late.send_by)
    assert item.due_date == "2027-01-15"


# --------------------------------------------------------------------------------------------------
# 4. done moves on and stays open; dismissed ends the series
# --------------------------------------------------------------------------------------------------


def test_marking_done_moves_to_the_occurrence_after_the_current_one(store: Store) -> None:
    rent = _item(
        store,
        title="Rent",
        amount=650.0,
        due_date="2026-10-01",
        date_spec=DateSpec(type="fixed", date="2026-01-01", nature="payment"),
    )
    paid = mark_done(store, rent, RuleContext(today=TODAY), postal_buffer_days=BUFFER)
    assert paid is not None
    assert (paid.status, paid.due_date, paid.completed_at) == ("open", "2026-11-01", None)
    [entry] = [entry for entry in store.list_activity() if entry.kind == "item.done"]
    assert entry.message == "Paid “Rent” (Thu 1 Oct 2026) — next on Sun 1 Nov 2026"
    assert entry.ref_id == rent.id


def test_paying_a_passed_occurrence_moves_on_to_today_at_the_earliest(store: Store) -> None:
    """Paid late (the roll hadn't run): the next occurrence is the current one, not an old one."""
    rent = _item(store, due_date="2026-08-01", date_spec=DateSpec(type="fixed", date="2026-01-01"))
    moved = moved_on(rent, RuleContext(today=TODAY), postal_buffer_days=BUFFER)
    assert moved is not None and (moved.status, moved.due_date) == ("open", "2026-10-01")


def test_marking_an_undated_recurring_item_done_keeps_it_open(store: Store) -> None:
    """Without a date there is no occurrence to move on to: it stays open as it is (only dismissing
    ends a series)."""
    fee = _item(store, due_date=None, date_spec=DateSpec(type="none", nature="payment"), status="done")
    kept = mark_done(store, fee, RuleContext(today=TODAY), postal_buffer_days=BUFFER)
    assert kept is not None and (kept.status, kept.due_date, kept.completed_at) == ("open", None, None)
    [entry] = [entry for entry in store.list_activity() if entry.kind == "item.done"]
    assert entry.message == "Paid “Monthly advance payment” — repeats every month"
    assert undo_done(store, kept) is None  # nothing moved, nothing to undo


def test_a_one_off_item_is_done_like_any_to_do(store: Store) -> None:
    one_off = _item(store, recurrence=None, due_date="2026-10-01")
    assert mark_done(store, one_off, RuleContext(today=TODAY), postal_buffer_days=BUFFER) is None


def test_undo_brings_back_the_occurrence_marked_done_with_its_dates(store: Store) -> None:
    ctx = RuleContext(today=TODAY)
    rent = _item(
        store,
        title="Rent",
        due_date="2026-09-01",
        date_spec=DateSpec(type="fixed", date="2026-01-01", nature="payment"),
    )
    rent = roll_item(store, rent, ctx, postal_buffer_days=BUFFER)
    paid = mark_done(store, rent, ctx, postal_buffer_days=BUFFER)
    assert paid is not None and (paid.status, paid.due_date) == ("open", "2026-11-01")
    undone = undo_done(store, paid)
    assert undone is not None and undone.status == "open"
    assert [getattr(undone, name) for name in SCHEDULE_FIELDS] == [
        getattr(rent, name) for name in SCHEDULE_FIELDS
    ]
    assert store.list_activity(1)[0].message == "Reopened “Rent” (Thu 1 Oct 2026)"
    assert undo_done(store, undone) is None  # undone already


def test_a_date_set_by_hand_comes_back_as_it_was(store: Store) -> None:
    ctx = RuleContext(today=TODAY)
    moved = _item(
        store, due_date="2026-10-17", send_by="2026-10-16", due_date_source="manual", grounding="user"
    )
    paid = mark_done(store, moved, ctx, postal_buffer_days=BUFFER)
    assert paid is not None and paid.due_date == "2026-11-15"
    undone = undo_done(store, paid)
    assert undone is not None
    assert (undone.due_date, undone.send_by, undone.due_date_source) == ("2026-10-17", "2026-10-16", "manual")


def test_there_is_nothing_to_undo_once_the_item_moved_on(store: Store) -> None:
    rent = _item(store, due_date="2026-10-15")
    paid = mark_done(store, rent, RuleContext(today=TODAY), postal_buffer_days=BUFFER)
    assert paid is not None and paid.due_date == "2026-11-15"
    later = roll_item(store, paid, RuleContext(today=date(2026, 11, 17)), postal_buffer_days=BUFFER)
    assert later.due_date == "2026-12-15"
    assert undo_done(store, later) is None


def test_money_coming_in_is_received_not_paid(store: Store) -> None:
    grant = _item(store, title="Scholarship", direction="in", due_date="2026-10-01")
    mark_done(store, grant, RuleContext(today=TODAY), postal_buffer_days=BUFFER)
    [entry] = [entry for entry in store.list_activity() if entry.kind == "item.done"]
    assert entry.message.startswith("Received “Scholarship”")


# --------------------------------------------------------------------------------------------------
# 5. every occurrence's dates come from the rules engine
# --------------------------------------------------------------------------------------------------


def test_each_occurrence_gets_the_engines_send_by_date_and_receipt(store: Store) -> None:
    moved = rolled(_item(store), RuleContext(today=TODAY), postal_buffer_days=BUFFER)
    assert moved is not None
    assert (moved.due_date, moved.send_by) == ("2026-10-15", "2026-10-14")  # one day for a transfer
    receipt = moved.computation
    assert receipt is not None
    assert receipt.summary == "Repeats every month since Wed 15 Oct 2025; next on Thu 15 Oct 2026."
    assert receipt.due_date == "2026-10-15" and "bgb_675s" in receipt.rule_ids


def test_a_weekend_occurrence_moves_as_its_date_spec_says(store: Store) -> None:
    """15 Nov 2026 is a Sunday: "next business day" makes it Monday 16 Nov, which is still the current
    occurrence on the 16th."""
    spec = DateSpec(type="fixed", date="2025-10-15", nature="payment", shift_rule="next_business_day")
    item = _item(store, due_date="2026-10-15", date_spec=spec)
    november = rolled(item, RuleContext(today=date(2026, 10, 16)), postal_buffer_days=BUFFER)
    assert november is not None and (november.due_date, november.send_by) == ("2026-11-16", "2026-11-13")
    assert rolled(november, RuleContext(today=date(2026, 11, 16)), postal_buffer_days=BUFFER) is None
    december = rolled(november, RuleContext(today=date(2026, 11, 17)), postal_buffer_days=BUFFER)
    assert december is not None and december.due_date == "2026-12-15"


def test_how_the_letter_was_read_grades_every_occurrence(store: Store) -> None:
    """The rubric's notes on how the letter was read (here: from a photo, the amount not in the
    sentence) grade each occurrence, as when it was read; an earlier occurrence's own warnings and
    grade don't carry over. Once the person confirmed the item, nothing lowers it."""
    amount = REASON_TEXT["amount_not_in_quote"]
    read = ComputationReceipt(
        due_date="2026-10-15", confidence="low", warnings=["Holiday in some states", MODEL_READ_NOTE, amount]
    )
    photo = _item(store, due_date="2026-10-15", computation=read, grounding="model_read")
    moved = rolled(photo, RuleContext(today=date(2026, 11, 17)), postal_buffer_days=BUFFER)
    assert moved is not None and moved.computation is not None and moved.due_date == "2026-12-15"
    assert (moved.computation.confidence, moved.computation.warnings) == ("low", [MODEL_READ_NOTE, amount])
    again = rolled(moved, RuleContext(today=date(2026, 12, 16)), postal_buffer_days=BUFFER)
    assert again is not None and again.computation is not None
    assert (again.computation.confidence, again.computation.warnings) == ("low", [MODEL_READ_NOTE, amount])
    confirmed = rolled(
        photo.model_copy(update={"grounding": "user"}),
        RuleContext(today=date(2026, 11, 17)),
        postal_buffer_days=BUFFER,
    )
    assert confirmed is not None and confirmed.computation is not None
    assert (confirmed.computation.confidence, confirmed.computation.warnings) == ("high", [])


def test_occurrences_use_the_holidays_of_the_context(store: Store) -> None:
    """6 Jan is a holiday in Bavaria only: the occurrence moves to 7 Jan there."""
    spec = DateSpec(type="fixed", date="2026-01-06", nature="payment", shift_rule="next_business_day")
    item = _item(store, due_date="2026-12-06", date_spec=spec)
    day = date(2027, 1, 2)
    nationwide_ = rolled(item, RuleContext(today=day), postal_buffer_days=BUFFER)
    bavaria = rolled(item, RuleContext(today=day, recipient_region="BY"), postal_buffer_days=BUFFER)
    assert nationwide_ is not None and nationwide_.due_date == "2027-01-06"
    assert bavaria is not None and bavaria.due_date == "2027-01-07"


def test_an_items_context_is_its_letters_else_nationwide(store: Store) -> None:
    party = store.add_party(name="Stadtwerke Musterstadt", kind="utility", region="BY")
    letter = add_doc(
        store,
        "stadtwerke",
        kind="contract",
        party_id=party.id,
        doc_date="2026-09-01",
        extraction={"kind": "contract", "title": "Contract", "summary": "s", "explanation": "e"},
    )
    from_letter = _item(store, doc_id=letter, party_id=party.id)
    by_hand = _item(store, origin="manual", party_id=party.id)
    assert item_context(store, from_letter, TODAY).region == "BY"
    assert item_context(store, by_hand, TODAY) == RuleContext(today=TODAY)


# --------------------------------------------------------------------------------------------------
# 6. reading the letter again never moves it backwards
# --------------------------------------------------------------------------------------------------


def test_a_later_stored_date_of_the_same_schedule_is_kept(store: Store) -> None:
    paid_ahead = _item(store, due_date="2027-01-15")
    spec = DateSpec(type="fixed", date="2025-10-15", nature="payment", text="jeweils zum 15.")
    assert keeps_later_date(paid_ahead, MONTHLY, spec, "2025-10-15")  # the wording doesn't matter
    assert not keeps_later_date(paid_ahead, MONTHLY, spec, "2027-02-15")  # the new date is later
    moved = spec.model_copy(update={"date": "2025-11-01"})
    assert not keeps_later_date(paid_ahead, MONTHLY, moved, "2025-11-01")  # another first occurrence
    quarterly = Recurrence(interval=3, unit="months")
    assert not keeps_later_date(paid_ahead, quarterly, spec, "2025-10-15")  # another rule
    details = spec.model_copy(
        update={"anchor": "explicit_date", "anchor_date": "2025-10-15", "shift_rule": "none"}
    )
    assert keeps_later_date(paid_ahead, MONTHLY, details, "2025-10-15")  # nor do its other details
    one_off = _item(store, due_date="2027-01-15", recurrence=None)
    assert not keeps_later_date(one_off, None, spec, "2025-10-15")


def test_only_the_occurrence_is_kept_its_dates_are_the_engines_now(store: Store) -> None:
    """The kept occurrence is dated in the current context: 6 Jan (moved to the next business day) is
    a holiday in Bavaria only, so the occurrence that stood on 7 Jan in Bavaria is on 6 Jan in NRW (not
    February's), and back on 7 Jan in Bavaria. A date off the schedule leads to the next occurrence."""
    spec = DateSpec(type="fixed", date="2026-01-06", nature="payment", shift_rule="next_business_day")
    bavaria = RuleContext(today=date(2026, 12, 8), recipient_region="BY")
    nrw = RuleContext(today=date(2026, 12, 8), recipient_region="NW")
    paid_ahead = _item(store, due_date="2027-01-07", date_spec=spec)
    in_nrw = at_occurrence(paid_ahead, paid_ahead.due_date, nrw, postal_buffer_days=BUFFER)
    assert in_nrw is not None and (in_nrw.due_date, in_nrw.send_by) == ("2027-01-06", "2027-01-05")
    assert in_nrw.computation is not None and in_nrw.computation.holiday_calendar == "Nordrhein-Westfalen"
    back = at_occurrence(in_nrw, in_nrw.due_date, bavaria, postal_buffer_days=BUFFER)
    assert back is not None and (back.due_date, back.send_by) == ("2027-01-07", "2027-01-05")
    off = at_occurrence(paid_ahead, "2027-01-20", nrw, postal_buffer_days=BUFFER)
    assert off is not None and off.due_date == "2027-02-08"  # Sat 6 Feb → Mon 8 Feb
    one_off = paid_ahead.model_copy(update={"recurrence": None})
    assert at_occurrence(one_off, "2027-01-07", nrw, postal_buffer_days=BUFFER) is None


# --------------------------------------------------------------------------------------------------
# 7. a date set by hand is kept until it passes
# --------------------------------------------------------------------------------------------------


def test_a_date_set_by_hand_is_kept_until_it_passes_then_the_schedule_applies(store: Store) -> None:
    """The 15 Nov payment moved to the 17th by hand: kept on the 16th; on the 18th the item is back on
    its schedule (the 15th of the month) with the letter's dates again."""
    item = _item(store, due_date="2026-11-17", due_date_source="manual", user_modified=True)
    assert rolled(item, RuleContext(today=date(2026, 11, 16)), postal_buffer_days=BUFFER) is None
    moved = rolled(item, RuleContext(today=date(2026, 11, 18)), postal_buffer_days=BUFFER)
    assert moved is not None
    assert (moved.due_date, moved.due_date_source) == ("2026-12-15", "fixed")


def test_a_date_set_by_hand_stands_in_for_the_occurrence_it_replaced(store: Store) -> None:
    """Monday 19 Oct's appointment moved to Friday 16 Oct by hand (its receipt names the 19th): once the
    16th has passed, and when it is marked done, the next one is 26 Oct, not the 19th it replaced.
    Moved later (to Wednesday 21 Oct), the next one is 26 Oct too."""
    weekly = Recurrence(interval=1, unit="weeks")
    by_hand = standing_in(ComputationReceipt(due_date="2026-10-16"), date(2026, 10, 19))
    earlier = _item(
        store,
        kind="appointment",
        due_date="2026-10-16",
        date_spec=DateSpec(type="fixed", date="2026-10-12", nature="appointment"),
        recurrence=weekly,
        computation=by_hand,
        due_date_source="manual",
        grounding="user",
    )
    assert replaced_occurrence(earlier) == date(2026, 10, 19)
    assert rolled(earlier, RuleContext(today=date(2026, 10, 16)), postal_buffer_days=BUFFER) is None
    after = rolled(earlier, RuleContext(today=date(2026, 10, 17)), postal_buffer_days=BUFFER)
    assert after is not None and after.due_date == "2026-10-26"
    assert replaced_occurrence(after) == date(2026, 10, 26)  # back on its schedule
    done = moved_on(earlier, RuleContext(today=date(2026, 10, 16)), postal_buffer_days=BUFFER)
    assert done is not None and done.due_date == "2026-10-26"
    later = earlier.model_copy(
        update={
            "due_date": "2026-10-21",
            "computation": standing_in(ComputationReceipt(due_date="2026-10-21"), date(2026, 10, 19)),
        }
    )
    after = rolled(later, RuleContext(today=date(2026, 10, 22)), postal_buffer_days=BUFFER)
    assert after is not None and after.due_date == "2026-10-26"
