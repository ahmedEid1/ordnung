"""Recurring obligations are schedules (ordnung.recurrence): each test pins one point of the policy.

1 never overdue · 2 the schedule is (first occurrence, rule) · 3 as days pass, the first occurrence on
or after today · 4 done moves on and stays open (Undo brings it back), dismissed ends it · 5 every
occurrence's dates and receipt from the rules engine · 6 reading again never moves it backwards · 7 a
date set by hand stands in for the occurrence it replaced and is kept until it passes · 8 a working day
of each month (rent's by § 556b BGB). Realistic histories through the API are in
``test_regressions_recurrence.py`` and ``test_policy_recurring.py``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pytest

from helpers_secretary import add_doc
from ordnung.db.store import Store
from ordnung.ingest.plan import item_context
from ordnung.ingest.verify import AMOUNT_NOT_IN_QUOTE, MODEL_READ_NOTE, REASON_TEXT, UNVERIFIED_NOTE
from ordnung.models import ComputationReceipt, DateSpec, Item, Recurrence
from ordnung.recurrence import (
    LAW_DEFAULT_WARNING,
    LAW_REPLACED_WARNING,
    SCHEDULE_FIELDS,
    at_occurrence,
    describe,
    first_occurrence,
    first_scheduled,
    keeps_later_date,
    mark_done,
    moved_on,
    next_occurrence,
    occurrence,
    over_the_law,
    replaced_occurrence,
    roll_forward,
    roll_item,
    rolled,
    same_rule,
    schedule_rule,
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
    ctx = RuleContext(today=TODAY)
    assert keeps_later_date(paid_ahead, MONTHLY, spec, "2025-10-15", ctx)  # the wording doesn't matter
    assert not keeps_later_date(paid_ahead, MONTHLY, spec, "2027-02-15", ctx)  # the new date is later
    moved = spec.model_copy(update={"date": "2025-11-01"})
    assert not keeps_later_date(paid_ahead, MONTHLY, moved, "2025-11-01", ctx)  # another first occurrence
    quarterly = Recurrence(interval=3, unit="months")
    assert not keeps_later_date(paid_ahead, quarterly, spec, "2025-10-15", ctx)  # another rule
    details = spec.model_copy(
        update={"anchor": "explicit_date", "anchor_date": "2025-10-15", "shift_rule": "none"}
    )
    assert keeps_later_date(paid_ahead, MONTHLY, details, "2025-10-15", ctx)  # nor do its other details
    one_off = _item(store, due_date="2027-01-15", recurrence=None)
    assert not keeps_later_date(one_off, None, spec, "2025-10-15", ctx)


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


# --------------------------------------------------------------------------------------------------
# 8. a working day of each month
# --------------------------------------------------------------------------------------------------

BY_THE_THIRD = Recurrence(interval=1, unit="months", working_day=3)
#: 29 Sep 2026, for a payment on a lease.
RENT = RuleContext(today=date(2026, 9, 29), rent=True, letter_kind="rent_lease")


def _on_lease(today: date) -> RuleContext:
    return replace(RENT, today=today)


def _rent(store: Store, **fields: object) -> Item:
    """A lease's rent as read from "spätestens am dritten Werktag eines jeden Monats" (its sentence found in
    the letter): monthly, no date."""
    spec = DateSpec(type="none", nature="payment", text="spätestens am dritten Werktag eines jeden Monats")
    base = {
        "title": "Monthly rent",
        "due_date": None,
        "date_spec": spec,
        "amount": 640.0,
        "due_date_source": "none",
        "grounding": "verified",
    }
    return _item(store, **{**base, "origin": "extracted", **fields})


def _filed(item: Item, ctx: RuleContext) -> Item:
    """The item as reading its letter files it: its first occurrence, moved on if it has passed."""
    first = first_scheduled(item, ctx, postal_buffer_days=BUFFER)
    assert first is not None
    return rolled(first, ctx, postal_buffer_days=BUFFER) or first


def test_rent_is_due_by_the_working_day_of_each_month_saturdays_not_counted(store: Store) -> None:
    """The lease says "by the 3rd working day": each month's date is counted from its first, Monday to
    Friday without holidays (§ 556b Abs. 1 BGB, BGH VIII ZR 129/09) — Mon 5 Oct (3 Oct is a holiday),
    Wed 4 Nov, Thu 3 Dec, and Tue 7 Apr 2026 after Easter — never the day of the month the first one fell
    on (5 Nov, 7 Dec)."""
    october = _filed(_rent(store, recurrence=BY_THE_THIRD), RENT)
    assert (october.due_date, october.send_by, october.due_date_source) == (
        "2026-10-05",
        "2026-10-02",
        "computed",
    )
    receipt = october.computation
    assert receipt is not None
    assert receipt.summary == "Repeats every month on the 3rd working day; next on Mon 5 Oct 2026."
    assert {"unit_business_days", "bgb_556b", "bgb_675s"} <= set(receipt.rule_ids)
    assert (receipt.confidence, LAW_DEFAULT_WARNING in receipt.warnings) == ("high", False)  # the lease's day
    november = rolled(october, RuleContext(today=date(2026, 10, 6), rent=True), postal_buffer_days=BUFFER)
    assert november is not None and november.due_date == "2026-11-04"
    december = moved_on(november, RuleContext(today=date(2026, 11, 2), rent=True), postal_buffer_days=BUFFER)
    assert december is not None and december.due_date == "2026-12-03"
    april = _filed(_rent(store, recurrence=BY_THE_THIRD), RuleContext(today=date(2026, 3, 20), rent=True))
    assert april.due_date == "2026-04-07"


def test_other_working_days_count_saturday(store: Store) -> None:
    """Not rent, the working days are Werktage (Monday to Saturday): Tue 4 Aug 2026, not Wed 5 Aug; Sat
    4 Apr 2026 for a to-do, which a payment's due day leaves for Tue 7 Apr (§ 193 BGB, Easter Monday)."""
    july = RuleContext(today=date(2026, 7, 20))
    assert _filed(_rent(store, recurrence=BY_THE_THIRD), july).due_date == "2026-08-04"
    assert _filed(_rent(store, recurrence=BY_THE_THIRD), replace(july, rent=True)).due_date == "2026-08-05"
    spec = DateSpec(type="none", nature="other", text="am dritten Werktag")
    march = RuleContext(today=date(2026, 3, 20))
    task = _rent(store, kind="task", date_spec=spec, recurrence=BY_THE_THIRD)
    assert _filed(task, march).due_date == "2026-04-04"
    assert _filed(_rent(store, recurrence=BY_THE_THIRD), march).due_date == "2026-04-07"


def test_the_law_dates_a_monthly_rent_its_lease_leaves_undated(store: Store) -> None:
    """A lease's monthly rent read without a day is due by the law's third working day (§ 556b Abs. 1 BGB),
    with a warning to check the lease, at most ``medium``."""
    rent = _rent(store)
    rule = schedule_rule(rent, RENT)
    assert rule is not None and rule.working_day == 3
    october = _filed(rent, RENT)
    assert (october.due_date, october.send_by) == ("2026-10-05", "2026-10-02")
    receipt = october.computation
    assert receipt is not None and receipt.warnings[0] == LAW_DEFAULT_WARNING
    assert receipt.confidence == "medium" and "bgb_556b" in receipt.rule_ids
    assert receipt.steps[1].label == "Rent is due by the 3rd working day of the month; Saturdays don't count"
    november = rolled(october, _on_lease(date(2026, 10, 6)), postal_buffer_days=BUFFER)
    assert november is not None and november.due_date == "2026-11-04"
    assert november.computation is not None and LAW_DEFAULT_WARNING in november.computation.warnings


def test_an_undated_rent_is_graded_by_where_its_sentence_was_found(store: Store) -> None:
    """Its sentence not found in the letter, the lease's own working day is ``medium`` and the law's
    ``low``, and both say why; once dated, each occurrence is graded as the first one was (point 5)."""
    own = _filed(_rent(store, recurrence=BY_THE_THIRD, grounding="unverified"), RENT)
    assert own.computation is not None and own.computation.confidence == "medium"
    assert UNVERIFIED_NOTE in own.computation.warnings
    by_law = _filed(_rent(store, grounding="unverified"), RENT)
    assert by_law.computation is not None and by_law.computation.confidence == "low"
    assert {UNVERIFIED_NOTE, LAW_DEFAULT_WARNING} <= set(by_law.computation.warnings)
    november = rolled(by_law, _on_lease(date(2026, 10, 6)), postal_buffer_days=BUFFER)
    assert november is not None and november.computation is not None
    assert (november.computation.confidence, UNVERIFIED_NOTE in november.computation.warnings) == (
        "low",
        True,
    )


def test_an_undated_rent_is_graded_by_what_its_sentence_leaves_out(store: Store) -> None:
    """Its sentence gives no amount (and the letter writes it nowhere else): the rubric's quote check fails,
    so the lease's own working day is ``medium``, and each later occurrence is graded the same (point 5)."""
    missing = (AMOUNT_NOT_IN_QUOTE,)
    first = first_scheduled(
        _rent(store, recurrence=BY_THE_THIRD), RENT, postal_buffer_days=BUFFER, reasons=missing
    )
    assert first is not None and first.computation is not None
    assert first.computation.confidence == "medium"
    assert REASON_TEXT[AMOUNT_NOT_IN_QUOTE] in first.computation.warnings
    october = rolled(first, RENT, postal_buffer_days=BUFFER)
    assert october is not None and october.computation is not None
    assert (october.computation.confidence, october.due_date) == ("medium", "2026-10-05")


@pytest.mark.parametrize(
    ("fields", "ctx"),
    [
        ({}, RuleContext(today=RENT.today)),  # neither a lease nor a rent contract
        ({"recurrence": Recurrence(interval=3, unit="months")}, RENT),  # not every month
        ({"date_spec": DateSpec(type="fixed", date="2026-10-01", nature="payment")}, RENT),  # the lease's day
        ({"kind": "task"}, RENT),  # not a payment
        ({}, replace(RENT, letter_kind="rent_increase")),  # a rent increase's new rent: § 558b BGB dates it
        # a payment under the rent contract on another letter (a statement's new prepayment, a rent
        # increase's current rent): not the lease's rent
        ({}, replace(RENT, letter_kind="operating_costs")),
        ({}, replace(RENT, letter_kind=None)),
    ],
)
def test_the_laws_day_is_only_for_a_monthly_rent_its_lease_leaves_undated(
    store: Store, fields: dict[str, object], ctx: RuleContext
) -> None:
    item = _rent(store, **fields)
    rule = schedule_rule(item, ctx)
    assert rule is not None and rule.working_day is None
    assert first_scheduled(item, ctx, postal_buffer_days=BUFFER) is None


def test_a_working_day_belongs_to_a_rule_in_months() -> None:
    """A working day is part of the rule (it gives other dates), in months or years; in days or weeks
    there is none."""
    assert describe(BY_THE_THIRD) == "every month on the 3rd working day"
    assert describe(Recurrence(interval=3, working_day=1)) == "every 3 months on the 1st working day"
    weekly = Recurrence(interval=1, unit="weeks", working_day=2)
    assert describe(weekly) == "every week"
    assert not same_rule(BY_THE_THIRD, MONTHLY)
    assert same_rule(Recurrence(unit="years", working_day=5), Recurrence(interval=12, working_day=5))
    assert same_rule(weekly, Recurrence(interval=1, unit="weeks"))
    item = Item(id="i", kind="payment", title="t", recurrence=weekly, created_at="", updated_at="")
    rule = schedule_rule(item, RENT)
    assert rule is not None and rule.working_day is None


def test_a_working_days_schedule_starts_in_the_month_of_its_first_date(store: Store) -> None:
    """Point 2's date only names the month; without one, the month of the item's date, else the current
    month."""
    november = DateSpec(type="fixed", date="2026-11-15", nature="payment")
    assert first_occurrence(_rent(store, recurrence=BY_THE_THIRD, date_spec=november), RENT) == date(
        2026, 11, 1
    )
    assert first_occurrence(_rent(store, recurrence=BY_THE_THIRD), RENT) == date(2026, 9, 1)
    dated = _rent(store, recurrence=BY_THE_THIRD, due_date="2026-12-03")
    assert first_occurrence(dated, RENT) == date(2026, 12, 1)
    assert first_occurrence(_rent(store), RuleContext(today=RENT.today)) is None  # no schedule, no date


def test_a_rent_increases_new_rent_starts_no_earlier_than_the_law_allows(store: Store) -> None:
    """A rent increase's new rent "ab dem 01.11.2026, bis zum 3. Werktag" in a request dated 24 Sep: by law
    the higher rent can be owed from 1 Dec at the earliest (§ 558b Abs. 1 BGB), so its schedule starts in
    December (Thu 3 Dec), not on Wed 4 Nov; without a date it has no schedule at all — only a date its
    letter gives starts it, never the current month."""
    letter = RuleContext(
        today=date(2026, 9, 29), rent=True, letter_kind="rent_increase", document_date=date(2026, 9, 24)
    )
    early = DateSpec(type="fixed", date="2026-11-01", nature="payment", text="ab dem 01.11.2026")
    new_rent = _rent(store, recurrence=BY_THE_THIRD, date_spec=early, due_date="2026-12-01")
    assert first_occurrence(new_rent, letter) == date(2026, 12, 1)
    first = first_scheduled(new_rent, letter, postal_buffer_days=BUFFER)
    assert first is not None and first.due_date == "2026-12-03"
    undated = _rent(store, recurrence=BY_THE_THIRD)
    assert first_occurrence(undated, letter) is None
    assert first_scheduled(undated, letter, postal_buffer_days=BUFFER) is None


def test_an_undated_rent_starts_no_earlier_than_its_tenancy(store: Store) -> None:
    """A lease signed in September for a flat from 1 Dec: the first rent is December's (Thu 3 Dec), not
    October's; a tenancy that began long ago changes nothing, nor does it move a date the letter gives."""
    later = first_scheduled(_rent(store), RENT, postal_buffer_days=BUFFER, starts="2026-12-01")
    assert later is not None and later.due_date == "2026-12-03"
    earlier = first_scheduled(_rent(store), RENT, postal_buffer_days=BUFFER, starts="2020-05-01")
    assert earlier is not None and earlier.due_date == "2026-09-03"  # then moved on as days pass
    october = DateSpec(type="fixed", date="2026-10-01", nature="payment")
    written = _rent(store, recurrence=BY_THE_THIRD, date_spec=october)
    dated = first_scheduled(written, RENT, postal_buffer_days=BUFFER, starts="2026-12-01")
    assert dated is not None and dated.due_date == "2026-10-05"


def test_no_letter_rule_re_dates_a_working_day(store: Store) -> None:
    """A rent increase's new rent, "from 1 Dec, by the 3rd working day": each month's working day, never
    § 558b's first day of the new rent again (which would repeat for every month)."""
    spec = DateSpec(type="fixed", date="2026-12-01", nature="payment", text="ab dem 01.12.2026")
    new_rent = _rent(store, recurrence=BY_THE_THIRD, date_spec=spec)
    letter = RuleContext(
        today=date(2027, 2, 10), rent=True, letter_kind="rent_increase", document_date=date(2026, 9, 20)
    )
    first = first_scheduled(new_rent, letter, postal_buffer_days=BUFFER)
    assert first is not None and first.due_date == "2026-12-03"
    assert _filed(new_rent, letter).due_date == "2027-03-03"


def test_the_latest_working_day_of_a_month_stays_in_its_month(store: Store) -> None:
    """The 10th working day of January 2027 in Bavaria (1 and 6 Jan are holidays) is Mon 18 Jan: kept as
    January's (point 6), and marking it done moves on to February's (Fri 12 Feb), not past it."""
    bavaria = replace(RENT, today=date(2027, 1, 5), recipient_region="BY")
    january = _filed(_rent(store, recurrence=Recurrence(working_day=10)), bavaria)
    assert (january.due_date, january.send_by) == ("2027-01-18", "2027-01-15")
    kept = at_occurrence(january, january.due_date, bavaria, postal_buffer_days=BUFFER)
    assert kept is not None and kept.due_date == "2027-01-18"
    done = moved_on(january, bavaria, postal_buffer_days=BUFFER)
    assert done is not None and done.due_date == "2027-02-12"


def test_the_same_schedule_read_with_the_laws_working_day_keeps_its_later_date(store: Store) -> None:
    """Point 6 with point 8: the lease's rent the law dated, paid ahead to Wed 4 Nov, read again with its
    working day (3, the day the law gave it) is the same schedule, so it keeps 4 Nov — it is not asked for
    again for October; read with another working day, it is another schedule."""
    paid_ahead = _filed(_rent(store), RENT).model_copy(update={"due_date": "2026-11-04"})
    spec = paid_ahead.date_spec
    assert keeps_later_date(paid_ahead, BY_THE_THIRD, spec, None, RENT)
    kept = at_occurrence(
        paid_ahead.model_copy(update={"recurrence": BY_THE_THIRD}),
        "2026-11-04",
        RENT,
        postal_buffer_days=BUFFER,
    )
    assert kept is not None and kept.due_date == "2026-11-04"
    assert kept.computation is not None and LAW_DEFAULT_WARNING not in kept.computation.warnings
    assert not keeps_later_date(paid_ahead, Recurrence(working_day=1), spec, None, RENT)
    # not on the lease, the law gives it no working day: another schedule
    assert not keeps_later_date(paid_ahead, BY_THE_THIRD, spec, None, replace(RENT, letter_kind=None))


def test_a_date_set_by_hand_later_than_the_laws_says_it_replaces_it(store: Store) -> None:
    """Point 8: a date the person gives a rent the law dates replaces the law's day for every month; a later
    one (9 Oct for Mon 5 Oct) says so on its receipt, an earlier one (the lease's "bis zum 1.") needs no
    word, nor does a date on rent the law doesn't date."""
    october = _filed(_rent(store), RENT)
    receipt = ComputationReceipt(due_date="2026-10-09")
    later = over_the_law(october, "2026-10-09", receipt)
    assert later is not None and later.warnings == [LAW_REPLACED_WARNING]
    assert over_the_law(october, "2026-10-01", receipt) == receipt
    assert over_the_law(october, None, None) is None
    own = _filed(_rent(store, recurrence=BY_THE_THIRD), RENT)
    assert over_the_law(own, "2026-10-09", receipt) == receipt


def test_a_lease_or_a_rent_contract_makes_a_to_dos_payments_rent(store: Store) -> None:
    lease = add_doc(
        store,
        "mietvertrag",
        kind="rent_lease",
        doc_date="2026-09-01",
        extraction={"kind": "rent_lease", "title": "Lease", "summary": "s", "explanation": "e"},
    )
    flat = store.add_contract(name="Flat", category="rent")
    gym = store.add_contract(name="Gym", category="gym")
    assert item_context(store, _item(store, doc_id=lease), TODAY).rent
    assert item_context(store, _item(store, origin="manual", contract_id=flat.id), TODAY).rent
    assert not item_context(store, _item(store, origin="manual", contract_id=gym.id), TODAY).rent
