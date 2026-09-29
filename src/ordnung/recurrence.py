"""Recurring obligations (rent, monthly advance payments, quarterly fees, an appointment series).

Ordnung cannot see payments or attendance, so a recurring item is a *schedule*, not a list of
occurrences to tick off. The policy (each point is pinned by tests; cases outside it are accepted
limits, not bugs):

1. A recurring item always shows its next occurrence and is never overdue because a month passed
   (a missed payment surfaces through the reminder letter it brings).
2. The schedule is (first occurrence, rule); rules that give the same dates are one rule (every year
   is every 12 months, every week every 7 days). The first occurrence is the date the item's
   ``date_spec`` gives before a weekend or holiday moves it: a fixed date as written, or a relative
   one counted in its letter's context (:func:`first_occurrence`). A to-do whose DateSpec gives no
   date (added by hand, or undated in its letter) gets a fixed one at the first date the person gives
   it. (A relative DateSpec that gives no date in its context runs from the item's current date.)
3. As days pass (:func:`roll_forward`), an open or snoozed recurring item whose date is before today
   moves to the first occurrence on or after today (after a date set by hand: point 7). Nothing else
   changes; a second run changes nothing.
4. Marking it done (paid) does not close it: it moves to the occurrence after its current one (after
   the one a date set by hand replaced: point 7), not before today, and stays open
   (:func:`mark_done`); an undated one has no occurrence to move to and stays open as it is. "Undo"
   (setting it open again while it stands where marking it done moved it) brings back the
   occurrence marked done, with its dates as they were (:func:`undo_done`). Dismissing it ends the
   series.
5. Every occurrence's date comes from the rules engine, as a fixed date of the item's nature in its
   letter's :class:`~ordnung.rules.RuleContext` (else nationwide holidays), so weekend and holiday
   shifts and the send-by date (transfer or postal buffer) are right for each occurrence. Its receipt
   is the engine's for that occurrence, graded by how the letter was read (the rubric's notes carry
   over; none once the person confirmed the item or set a date), never by an earlier occurrence's.
6. Reading the letter again or recomputing its dates never moves it backwards: while the schedule is
   the same (the same rule and first occurrence, however the DateSpec's other details were read), it
   keeps the later of its stored occurrence and the new one (:func:`keeps_later_date`). Only the
   occurrence is kept: its dates and receipt are point 5's, from the new reading or context
   (:func:`at_occurrence`). A new reading that quotes its sentence differently takes it over.
7. A date set by hand stands in for the occurrence the item stood at when it was set (moved again, it
   still stands in for that one); its receipt names it (:func:`replaced_occurrence`). It is kept
   until it passes. Then, as when it is marked done, the schedule continues after the occurrence it
   replaced (points 3 and 4 count from there): paid early, the same payment is never asked for again.
8. A rule with a working day (``Recurrence.working_day``: "spätestens am dritten Werktag eines jeden
   Monats" is 3) is dated in each of its months by counting that many working days from the month's
   first (point 5; no letter rule re-dates it): Monday to Friday without public holidays for rent (a
   payment whose letter is a lease or whose contract is a rent contract, ``RuleContext.rent``: § 556b
   Abs. 1 BGB as the BGH reads it for rent, VIII ZR 129/09 — Saturday does not count), Werktage
   (Monday to Saturday) otherwise. Point 2's date only names the month it starts in (without one, the
   current month, or the later one its contract starts in), so the item is dated when its letter is
   read or its dates are recomputed (:func:`first_scheduled`), then moves on by points 3 and 4. Rent
   paid every month whose letter gives no day and no working day is due by the law's third working day
   (§ 556b Abs. 1 BGB, :func:`schedule_rule`), one confidence level lower (``medium`` at most) and with
   a warning to check the lease — until the person gives it a date, which replaces the law's (point 2),
   and never for a rent increase's new rent (§ 558b BGB dates it). A rule in days or weeks has no
   working day.
"""

from __future__ import annotations

import calendar
import itertools
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import date, timedelta

from ordnung.db.store import Store
from ordnung.ingest.verify import grade_reading, regrade
from ordnung.models import (
    ComputationReceipt,
    ComputationStep,
    DateNature,
    DateSpec,
    Item,
    Recurrence,
)
from ordnung.rules import RuleContext, compute_due, get_rule
from ordnung.secretary.triggers import postal_buffer

_MAX_STEPS = 10_000  # safety net against pathological schedules
#: Days the rules engine can move a fixed date to a later working day (Good Friday → Tuesday is 4).
_SHIFT_DAYS = 7
#: Days before a day that a working day's month can start (point 8): a month, as a month's 10th working day,
#: moved past a holiday, is under three weeks into it.
_WORKING_DAY_SPAN = 31
_KIND_NATURES: dict[str, DateNature] = {"payment": "payment", "appointment": "appointment"}
#: The working day rent is due by when the lease names no day (§ 556b Abs. 1 BGB; point 8).
RENT_WORKING_DAY = 3
#: The warning on an occurrence the law's working day dates (point 8).
LAW_DEFAULT_WARNING = (
    "The lease gives no day Ordnung could date; this is the law's default (3rd working day, Saturdays not "
    "counted) — check your lease."
)

#: Statuses whose recurring item moves on as days pass (point 3).
ROLLING_STATUSES = ("open", "snoozed")
#: The item fields that say where its schedule stands (what points 3, 4 and 6 move or keep).
SCHEDULE_FIELDS = ("due_date", "send_by", "computation", "due_date_source")
#: The step of a date set by hand's receipt that names the occurrence it stands in for (point 7).
REPLACED_STEP = "Moved by you from"
#: The RuleContext of an item's dates as of a day: its letter's, else nationwide
#: (:func:`ordnung.ingest.plan.item_context`).
ItemContext = Callable[[Store, Item, date], RuleContext]


# --------------------------------------------------------------------------------------------------
# the schedule
# --------------------------------------------------------------------------------------------------


def _add_months(start: date, months: int, anchor_day: int) -> date:
    index = start.month - 1 + months
    year, month = start.year + index // 12, index % 12 + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))


def occurrence(first: date, rule: Recurrence, n: int) -> date:
    """The ``n``-th occurrence (0 = ``first``). Month steps keep the original day of the month, clipped
    to shorter months (31 Jan → 28/29 Feb → 31 Mar)."""
    step = max(1, rule.interval) * n
    if rule.unit == "days":
        return date.fromordinal(first.toordinal() + step)
    if rule.unit == "weeks":
        return date.fromordinal(first.toordinal() + 7 * step)
    months = step * (12 if rule.unit == "years" else 1)
    return _add_months(first, months, first.day)


def _occurrences(first: date, rule: Recurrence, since: date) -> Iterator[date]:
    """The schedule's occurrences (as scheduled) from the first one on or after ``since``."""
    for n in range(_MAX_STEPS):
        day = occurrence(first, rule, n)
        if day >= since:
            yield day


def next_occurrence(first: date, rule: Recurrence, on_or_after: date) -> date:
    """The first occurrence of the schedule that is on or after ``on_or_after`` (as scheduled)."""
    for day in _occurrences(first, rule, on_or_after):
        return day
    raise ValueError("recurrence schedule does not reach the requested date")


def describe(rule: Recurrence) -> str:
    """``every month`` / ``every 3 months`` / ``every year`` / ``every month on the 3rd working day``."""
    unit = rule.unit.rstrip("s")
    every = f"every {unit}" if rule.interval <= 1 else f"every {rule.interval} {rule.unit}"
    working_day = _steps(rule)[2]
    return every if working_day is None else f"{every} on the {_ordinal(working_day)} working day"


def _ordinal(number: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(number, f"{number}th")


def _steps(rule: Recurrence) -> tuple[int, str, int | None]:
    """The rule as :func:`occurrence` steps it, with its working day (point 8): every year →
    ``(12, "months", None)``, every 2 weeks → ``(14, "days", None)`` (a rule in days or weeks has none)."""
    interval = max(1, rule.interval)
    if rule.unit == "years":
        return 12 * interval, "months", rule.working_day
    if rule.unit == "weeks":
        return 7 * interval, "days", None
    return interval, rule.unit, rule.working_day if rule.unit == "months" else None


def same_rule(first: Recurrence | None, second: Recurrence | None) -> bool:
    """Whether two rules give the same dates (point 2): every year is every 12 months."""
    if first is None or second is None:
        return first is second
    return _steps(first) == _steps(second)


def _is_rent(item: Item, ctx: RuleContext) -> bool:
    """A payment whose letter is a lease or whose contract is a rent contract (point 8)."""
    return ctx.rent and item.kind == "payment"


def schedule_rule(item: Item, ctx: RuleContext) -> Recurrence | None:
    """The rule the item's dates follow (point 8): its own, without a working day in days or weeks, and
    with the law's third working day (§ 556b Abs. 1 BGB) for rent paid every month whose letter gives no
    day — not a rent increase's new rent, whose first payment § 558b BGB dates (once agreed)."""
    rule, spec = item.recurrence, item.date_spec
    if rule is None:
        return None
    working_day = _steps(rule)[2]
    if (
        working_day is None
        and _is_rent(item, ctx)
        and same_rule(rule, Recurrence())
        and spec is not None
        and spec.type == "none"
        and ctx.letter_kind != "rent_increase"
    ):
        working_day = RENT_WORKING_DAY
    return rule if working_day == rule.working_day else rule.model_copy(update={"working_day": working_day})


def _lookback(rule: Recurrence) -> int:
    """How long before a day an occurrence can be scheduled whose date the rules engine moves onto or past
    it: a weekend or Easter (:data:`_SHIFT_DAYS`), or a working day counted from its month's first."""
    return _SHIFT_DAYS if rule.working_day is None else _WORKING_DAY_SPAN


def _day(value: date) -> str:
    return f"{value:%a} {value.day} {value:%b %Y}"


def _parse(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def first_occurrence(item: Item, ctx: RuleContext) -> date | None:
    """Where the item's schedule starts (point 2): the date its DateSpec gives before a weekend or
    holiday moves it (a fixed date as written, a relative one counted in ``ctx``), else its current
    date; with a working day, the first of that date's month, else of the current month (point 8)."""
    spec, given = item.date_spec, None
    if spec is not None and spec.type == "fixed":
        given = spec.date
    elif spec is not None and spec.type == "relative":
        given = compute_due(spec.model_copy(update={"shift_rule": "none"}), ctx).due_date
    start = _parse(given) or _parse(item.due_date)
    rule = schedule_rule(item, ctx)
    if rule is None or rule.working_day is None:
        return start
    return (start or ctx.today).replace(day=1)


def replaced_occurrence(item: Item) -> date | None:
    """The date of the occurrence the item stands for (point 7): the one a date set by hand replaced,
    as its receipt names it, else its own date."""
    steps = item.computation.steps if item.computation is not None else []
    named = next((step.date for step in steps if step.label == REPLACED_STEP), None)
    return _parse(named) or _parse(item.due_date)


def standing_in(receipt: ComputationReceipt, replaced: date) -> ComputationReceipt:
    """The receipt of a date set by hand, naming the occurrence it stands in for (point 7)."""
    step = ComputationStep(label=REPLACED_STEP, date=replaced.isoformat())
    return receipt.model_copy(update={"steps": [step, *receipt.steps]})


# --------------------------------------------------------------------------------------------------
# an occurrence's dates (point 5)
# --------------------------------------------------------------------------------------------------


def _occurrence_spec(item: Item, rule: Recurrence, day: date, ctx: RuleContext) -> DateSpec:
    """The occurrence scheduled on ``day`` as a DateSpec of the item's nature (moved as its DateSpec says):
    that date, or with a working day that many working days counted from ``day``, its month's first
    (point 8: business days for rent, Werktage otherwise)."""
    spec = item.date_spec or DateSpec(
        type="none", nature=_KIND_NATURES.get(item.kind, "other"), shift_rule="none"
    )
    if rule.working_day is None:
        return DateSpec(
            type="fixed",
            date=day.isoformat(),
            time=spec.time,
            nature=spec.nature,
            shift_rule=spec.shift_rule,
            legal_basis=spec.legal_basis,
            text=spec.text,
        )
    return DateSpec(
        type="relative",
        anchor="explicit_date",
        anchor_date=(day - timedelta(days=1)).isoformat(),
        amount=rule.working_day,
        unit="business_days" if _is_rent(item, ctx) else "werktage",
        time=spec.time,
        nature=spec.nature,
        shift_rule=spec.shift_rule,
        legal_basis=spec.legal_basis,
        text=spec.text,
    )


def _by_law(item: Item, rule: Recurrence, receipt: ComputationReceipt) -> ComputationReceipt:
    """Point 8's notes on rent counted by working days: the rule it is due by (§ 556b Abs. 1 BGB), and when
    the working day is the law's, not the letter's, the warning to check the lease, one confidence level
    lower (``medium`` at most)."""
    if rule.working_day is None:
        return receipt
    rent, ordinal = get_rule("bgb_556b"), _ordinal(rule.working_day)
    step = ComputationStep(
        label=f"Rent is due by the {ordinal} working day of the month; Saturdays don't count",
        date=receipt.due_date,
        rule_id=rent.id,
        citation=rent.citation,
    )
    update: dict[str, object] = {
        "steps": [receipt.steps[0], step, *receipt.steps[1:]],
        "rule_ids": [*receipt.rule_ids, rent.id],
    }
    if item.recurrence is not None and item.recurrence.working_day is None:
        update["warnings"] = [LAW_DEFAULT_WARNING, *receipt.warnings]
        update["confidence"] = "medium" if receipt.confidence == "high" else "low"
    return receipt.model_copy(update=update)


def _receipt(
    item: Item, rule: Recurrence, first: date, day: date, ctx: RuleContext, postal_buffer_days: int
) -> ComputationReceipt:
    """The rules engine's receipt for the occurrence scheduled on ``day``, graded by how the letter was
    read: the rubric's notes on the item's receipt carry over (:func:`~ordnung.ingest.verify.regrade`),
    unless the person confirmed the item (or set its date: ``grounding="user"``); one undated so far (in its
    letter, point 8) by where its quote was found. A working day is counted in ``ctx`` without the letter's
    kind, so no letter rule re-dates it (point 8)."""
    counted = ctx if rule.working_day is None else replace(ctx, letter_kind=None)
    spec = _occurrence_spec(item, rule, day, ctx)
    computed = compute_due(spec, counted, postal_buffer_days=postal_buffer_days)
    undated = item.computation is None and item.due_date is None  # dated for the first time (point 8)
    if item.grounding != "user":
        computed = (
            grade_reading(computed, item.grounding, ()) if undated else regrade(computed, item.computation)
        )
    due = _parse(computed.due_date)
    since = f"Repeats {describe(rule)}"
    if rule.working_day is None:  # a working day says itself which day of the month it is
        since = f"{since} since {_day(first)}"
    receipt = computed.model_copy(
        update={
            "summary": f"{since}; next on {_day(due)}." if due else computed.summary,
            "steps": [ComputationStep(label=since, date=day.isoformat()), *computed.steps],
        }
    )
    return _by_law(item, rule, receipt) if _is_rent(item, ctx) else receipt


def _at(
    item: Item, rule: Recurrence, first: date, day: date, ctx: RuleContext, postal_buffer_days: int
) -> Item:
    """The item at the occurrence scheduled on ``day``, with its dates and receipt from the engine."""
    receipt = _receipt(item, rule, first, day, ctx, postal_buffer_days)
    source = item.due_date_source
    if item.origin == "extracted":  # the letter's schedule again, also after a date set by hand
        fixed = rule.working_day is None and item.date_spec is not None and item.date_spec.type == "fixed"
        source = "fixed" if fixed else "computed"
    return item.model_copy(
        update={
            "due_date": receipt.due_date,
            "send_by": receipt.send_by,
            "computation": receipt,
            "due_date_source": source,
        }
    )


def _moved(item: Item, ctx: RuleContext, on_or_after: date, postal_buffer_days: int) -> Item | None:
    """The item at the first occurrence whose date (from the rules engine) is on or after
    ``on_or_after``; ``None`` for an item without a schedule."""
    rule, first = schedule_rule(item, ctx), first_occurrence(item, ctx)
    if rule is None or first is None:
        return None
    # an occurrence scheduled earlier can be moved onto or past the day (a weekend, Easter, a working day)
    for day in _occurrences(first, rule, on_or_after - timedelta(days=_lookback(rule))):
        moved = _at(item, rule, first, day, ctx, postal_buffer_days)
        due = _parse(moved.due_date)
        if due is not None and due >= on_or_after:
            return moved
    raise ValueError("recurrence schedule does not reach the requested date")


def at_occurrence(item: Item, due: str | None, ctx: RuleContext, *, postal_buffer_days: int) -> Item | None:
    """Point 6's kept occurrence: ``item`` (recomputed, or a new reading of the stored item) at the
    occurrence dated ``due`` (the stored date), with its dates and receipt from the engine in ``ctx``
    (point 5). The engine only moves a date later, so that is the last occurrence scheduled on or
    before ``due`` (in another holiday region it can fall on another day); a ``due`` off the schedule
    leads to the next occurrence. ``None`` for an item without a schedule."""
    rule, first, day = schedule_rule(item, ctx), first_occurrence(item, ctx), _parse(due)
    if rule is None or first is None or day is None:
        return None
    since = day - timedelta(days=_lookback(rule))
    scheduled = list(itertools.takewhile(lambda planned: planned <= day, _occurrences(first, rule, since)))
    if not scheduled:
        return _moved(item, ctx, day, postal_buffer_days)
    return _at(item, rule, first, scheduled[-1], ctx, postal_buffer_days)


def first_scheduled(
    item: Item, ctx: RuleContext, *, postal_buffer_days: int, starts: str | None = None
) -> Item | None:
    """Point 8 when a letter is read or its dates are recomputed: an item whose rule has a working day
    (:func:`schedule_rule`) at its schedule's first occurrence, with its dates and receipt from the engine
    — the date its DateSpec gives only names the month, and an undated one starts in the current month,
    or in the month its contract ``starts`` if that is later (no rent before the tenancy begins);
    :func:`rolled` then moves it on if it has passed. ``None`` for any other item."""
    rule, first, start = schedule_rule(item, ctx), first_occurrence(item, ctx), _parse(starts)
    if rule is None or rule.working_day is None or first is None:
        return None
    undated = item.due_date is None and (item.date_spec is None or item.date_spec.type == "none")
    if undated and start is not None and start > first:
        first = start.replace(day=1)
    return _at(item, rule, first, first, ctx, postal_buffer_days)


# --------------------------------------------------------------------------------------------------
# the policy on one item
# --------------------------------------------------------------------------------------------------


def has_passed(item: Item, today: date) -> bool:
    """An open or snoozed recurring item whose date is before ``today`` (what point 3 moves)."""
    due = _parse(item.due_date)
    return item.recurrence is not None and item.status in ROLLING_STATUSES and due is not None and due < today


def _onwards(item: Item, today: date) -> date | None:
    """Where points 3 and 4 move the item on from: after the occurrence it stands for (its own, or
    the one a date set by hand replaced: point 7), not before ``today``; ``None`` if undated."""
    replaced = replaced_occurrence(item)
    return max(replaced + timedelta(days=1), today) if replaced is not None else None


def rolled(item: Item, ctx: RuleContext, *, postal_buffer_days: int) -> Item | None:
    """Points 3 and 7: once its date (also one set by hand) has passed, the item moved to the first
    occurrence on or after ``ctx.today`` (and after the one a date set by hand replaced); ``None`` if
    nothing changes."""
    onwards = _onwards(item, ctx.today)
    if not has_passed(item, ctx.today) or onwards is None:
        return None
    return _moved(item, ctx, onwards, postal_buffer_days)


def moved_on(item: Item, ctx: RuleContext, *, postal_buffer_days: int) -> Item | None:
    """Point 4: the item marked done, moved to the occurrence after the one it stands for (after its
    current date, or the occurrence a date set by hand replaced), not before ``ctx.today``, and open;
    ``None`` for an item without a schedule (it is done like any to-do)."""
    onwards = _onwards(item, ctx.today)
    if item.recurrence is None or onwards is None:
        return None
    moved = _moved(item, ctx, onwards, postal_buffer_days)
    if moved is None:
        return None
    return moved.model_copy(update={"status": "open", "snoozed_until": None, "completed_at": None})


def _schedule(recurrence: Recurrence | None, spec: DateSpec | None) -> tuple[object, object]:
    """Point 2's schedule: the rule (as it steps) and the first occurrence, a fixed DateSpec's date. (Of
    another DateSpec, everything it says about the date decides the first occurrence.)"""
    rule = _steps(recurrence) if recurrence is not None else None
    first = _parse(spec.date) if spec is not None and spec.type == "fixed" else None
    if first is not None or spec is None:
        return rule, first
    return rule, spec.model_dump(exclude={"text", "legal_basis"})


def same_schedule(item: Item, recurrence: Recurrence | None, spec: DateSpec | None) -> bool:
    """Whether a recurring item runs on the schedule of ``recurrence`` from ``spec``: the same rule
    (:func:`same_rule`) and first occurrence, whatever else of the DateSpec (an anchor, a shift rule,
    the words) was read."""
    if item.recurrence is None:
        return False
    return _schedule(item.recurrence, item.date_spec) == _schedule(recurrence, spec)


def keeps_later_date(
    stored: Item, recurrence: Recurrence | None, spec: DateSpec | None, due_date: str | None
) -> bool:
    """Point 6: whether the stored recurring item keeps its date over ``due_date``, newly computed for
    the schedule ``recurrence`` from ``spec``: the schedule is unchanged (:func:`same_schedule`) and
    the stored date is the later one."""
    return (
        same_schedule(stored, recurrence, spec)
        and stored.due_date is not None
        and (due_date is None or stored.due_date > due_date)
    )


# --------------------------------------------------------------------------------------------------
# the policy in the ledger
# --------------------------------------------------------------------------------------------------


def _write(store: Store, moved: Item, names: tuple[str, ...]) -> Item:
    return store.update_item(moved.id, **{name: getattr(moved, name) for name in names})


def schedule_item(
    store: Store, item: Item, ctx: RuleContext, *, postal_buffer_days: int, starts: str | None = None
) -> Item:
    """Point 8 for one stored item its letter's reading just wrote (its contract ``starts`` on that day):
    its working-day schedule's first occurrence, written (the item itself for any other)."""
    scheduled = first_scheduled(item, ctx, postal_buffer_days=postal_buffer_days, starts=starts)
    return item if scheduled is None else _write(store, scheduled, SCHEDULE_FIELDS)


def roll_item(store: Store, item: Item, ctx: RuleContext, *, postal_buffer_days: int) -> Item:
    """Point 3 for one stored item: its current occurrence, written (the item itself if nothing moves)."""
    moved = rolled(item, ctx, postal_buffer_days=postal_buffer_days)
    return item if moved is None else _write(store, moved, SCHEDULE_FIELDS)


def roll_forward(store: Store, today: date, context: ItemContext) -> int:
    """Point 3 for the whole ledger: move every open or snoozed recurring item whose date has passed
    to its current occurrence, each in ``context(store, item, today)``; returns the count."""
    buffer = postal_buffer(store.get_profile())
    changed = 0
    for item in store.list_items(status=ROLLING_STATUSES):
        if has_passed(item, today):
            moved = roll_item(store, item, context(store, item, today), postal_buffer_days=buffer)
            changed += moved is not item
    return changed


def _done_verb(item: Item) -> str:
    if item.kind == "payment":
        return "Received" if item.direction == "in" else "Paid"
    return "Done"


def mark_done(store: Store, item: Item, ctx: RuleContext, *, postal_buffer_days: int) -> Item | None:
    """Point 4 in the ledger: the recurring item marked done stays open. A dated one moves on to its
    next occurrence; the activity log says "Paid “Rent” (Thu 1 Oct 2026) — next on Sun 1 Nov 2026" and
    keeps the dates of the occurrence marked done for :func:`undo_done`. An undated one stays as it is
    ("Paid “Rent” — repeats every month"). ``None`` for an item that doesn't repeat: it is done like
    any to-do."""
    if item.recurrence is None:
        return None
    moved = moved_on(item, ctx, postal_buffer_days=postal_buffer_days)
    was, now = _parse(item.due_date), _parse(moved.due_date if moved else None)
    if moved is None or was is None or now is None:  # undated: no occurrence to move on to
        updated = store.update_item(item.id, status="open", snoozed_until=None, completed_at=None)
        message = f"{_done_verb(item)} “{item.title}” — repeats {describe(item.recurrence)}"
        store.log_activity("item.done", message, ref_type="item", ref_id=item.id)
        return updated
    updated = _write(store, moved, (*SCHEDULE_FIELDS, "status", "snoozed_until", "completed_at"))
    store.log_activity(
        "item.done",
        f"{_done_verb(item)} “{item.title}” ({_day(was)}) — next on {_day(now)}",
        ref_type="item",
        ref_id=item.id,
        data={
            "due_date": item.due_date,
            "next_due_date": updated.due_date,
            "undo": {name: getattr(item, name) for name in SCHEDULE_FIELDS},
        },
    )
    return updated


def undo_done(store: Store, item: Item) -> Item | None:
    """Point 4's "Undo": the recurring item set open again while it stands at the occurrence
    :func:`mark_done` moved it to goes back to the occurrence marked done, with its dates as they were;
    the log says "Reopened “Rent” (Thu 1 Oct 2026)". ``None`` when there is nothing to undo: the item
    was not marked done, has moved since, or was reopened already."""
    entry = store.last_activity("item", item.id, kinds=("item.done", "item.reopened"))
    if item.recurrence is None or entry is None or entry.kind != "item.done":
        return None
    dates = entry.data.get("undo")
    if not isinstance(dates, dict) or entry.data.get("next_due_date") != item.due_date:
        return None
    reopened = store.update_item(item.id, **{name: dates[name] for name in SCHEDULE_FIELDS if name in dates})
    day = _parse(reopened.due_date)
    message = f"Reopened “{item.title}”" + (f" ({_day(day)})" if day else "")
    store.log_activity("item.reopened", message, ref_type="item", ref_id=item.id)
    return reopened
