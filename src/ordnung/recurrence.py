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
   (Monday to Saturday) otherwise. Point 2's date only names the month it starts in — the month of the
   date the rules engine gives its DateSpec in its letter's context, so a rent increase's new rent never
   starts before § 558b BGB allows it; without one, the current month, or the later one its contract
   starts in (never for a rent increase's new rent: only a date its letter gives starts it). So the
   item is dated when its letter is read or its dates are recomputed (:func:`first_scheduled`), then
   moves on by points 3 and 4. A lease's rent paid every month that the lease gives no day and no
   working day is due by the law's third working day (§ 556b Abs. 1 BGB, :func:`schedule_rule`), one
   confidence level lower (``medium`` at most) and with a warning to check the lease — until the person
   gives it a date, which replaces the law's for every month (point 2; a later one says so on its
   receipt: :func:`over_the_law`). The same schedule read with the working day the law gave it is the
   same schedule (point 6). A rule in days or weeks has no working day. A working day the reading gives
   dates the item even when the item's quote doesn't name it, but then one confidence level lower, with
   a note to check it, and the item is "Please check" (``WORKING_DAY_NOT_IN_QUOTE``:
   :func:`~ordnung.ingest.plan.consistency_reasons`).
9. A later rent replaces the one it changes, from the month it starts (:func:`replacement`). The rents of a
   rent contract are its to-dos linked to it that pay out every month (not dismissed: :func:`is_rent`); each
   starts in the month of the date the rules engine gives its DateSpec in its letter's context — a lease's
   own rent that names none before all others (:func:`series_start`; ties by when it was filed, then id). A
   rent that starts in a later month and restates the whole of an earlier one — its letter's old amount is
   that rent's ("bisher 640,00 €"), or its amount is at least that rent's (:meth:`_Rent.restates`) — (a rent
   increase's new rent only once owed: § 558b Abs. 1 BGB, once the person marked a payment of it paid that
   they haven't undone) ends that earlier one before that month: marking it done or rolling it never moves it
   into or past it. A payment that is only part of the rent — a statement's new prepayment (§ 560 Abs. 4
   BGB), a heating advance, a parking space, an instalment — runs beside it. Its last occurrence stays (never
   overdue, point 1); marked paid, it closes, and the log says "Paid “Monthly rent” (Mon 5 Oct 2026) —
   replaced by “New monthly total rent €670” from Nov 2026" ("Undo" reopens it there, point 4). One already
   in or past that month when the later one is read or becomes owed (paid ahead, rolled on, or filed later)
   goes where this would have left it: back to its last occurrence before that month, closed if the person
   marked that one (or a later one) paid — the latest payment still standing: an "Undo" takes back the one
   before it — and the log says so (:func:`settle_rents`; never the daily tick). "Undo" on the payment that
   made an increase owed opens such a rent again after the occurrence last marked paid
   (:func:`undo_replaced`). The later rent keeps the due day of the one it follows — its working day (its own
   or the law's, point 8) or its day of the month, in every month (a kept 31st is each month's last day) —
   unless its own reading gives a working day or the person added it by hand (its schedule starts on their
   date, point 2): a letter that changes the rent changes the amount, not when rent is due, so its date only
   names the month it starts in (as point 8's) and its receipt says so (:func:`rent_due`); a date the person
   gives one undated so far stands in for its occurrence of that month (point 7, :func:`kept_occurrence`).
   Accepted limits, where the rents run side by side as before: a rent not linked to a rent contract, two
   that start in the same month, an undated one not from a lease, one whose amounts don't show that it
   restates the earlier one (a letter that states only the new net rent, or a lower rent without the old
   amount); and a rent once closed stays closed when the one that replaced it is dismissed or deleted later
   (the person sets it open again).
"""

from __future__ import annotations

import calendar
import itertools
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta

from ordnung.clock import now_iso
from ordnung.db.store import Store
from ordnung.ingest.verify import grade_reading, regrade
from ordnung.models import (
    Activity,
    ComputationReceipt,
    ComputationStep,
    Contract,
    DateNature,
    DateSpec,
    Item,
    Recurrence,
)
from ordnung.rules import RentDue, RuleContext, compute_due, get_rule
from ordnung.rules.advice import RENT_INCREASE_PAYMENT_WARNING
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
    "counted) — check your lease: if it names an earlier day (such as the 1st), that day applies and this date "
    "is too late."
)
#: The warning on a date set by hand later than the law's working day it replaces (point 8).
LAW_REPLACED_WARNING = (
    "Your date replaces the law's default (3rd working day, Saturdays not counted) for every month — if "
    "your lease names no day, the rent is due by then."
)

#: What the step of the receipt of a rent that keeps an earlier rent's due day says between whose day it is
#: and the start its letter names (point 9): "The lease's due day applies; the letter names Sun 1 Nov 2026 as
#: the start".
KEEPS_DAY_STEP = " applies; the letter names "

#: Statuses whose recurring item moves on as days pass (point 3).
ROLLING_STATUSES = ("open", "snoozed")
#: The activity entries of a recurring item's payments: marked done (paid), and "Undo" (point 4).
_PAYMENT_KINDS = ("item.done", "item.reopened")
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


def occurrence(first: date, rule: Recurrence, n: int, anchor_day: int | None = None) -> date:
    """The ``n``-th occurrence (0 = ``first``). Month steps keep the original day of the month (or
    ``anchor_day``, a day a rent keeps from the rent before it: point 9), clipped to shorter months (31 Jan →
    28/29 Feb → 31 Mar)."""
    step = max(1, rule.interval) * n
    if rule.unit == "days":
        return date.fromordinal(first.toordinal() + step)
    if rule.unit == "weeks":
        return date.fromordinal(first.toordinal() + 7 * step)
    months = step * (12 if rule.unit == "years" else 1)
    return _add_months(first, months, anchor_day or first.day)


def _occurrences(first: date, rule: Recurrence, since: date, anchor_day: int | None = None) -> Iterator[date]:
    """The schedule's occurrences (as scheduled) from the first one on or after ``since``."""
    for n in range(_MAX_STEPS):
        day = occurrence(first, rule, n, anchor_day)
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


def rule_working_day(rule: Recurrence | None) -> int | None:
    """The working day a rule dates its months by (point 8): its own in months or years, none in days or
    weeks (and none without a rule)."""
    return None if rule is None else _steps(rule)[2]


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
    with the law's third working day (§ 556b Abs. 1 BGB) for a lease's rent paid every month that the lease
    gives no day — only on the lease itself (``ctx.letter_kind``), never on another letter about the
    tenancy (a rent increase's new rent, whose first payment § 558b BGB dates once agreed, or a statement's
    new prepayment). A rent that changes an earlier one and gives no working day of its own keeps that one's
    (``ctx.rent_due``, point 9)."""
    rule, spec = item.recurrence, item.date_spec
    if rule is None:
        return None
    working_day = _steps(rule)[2]
    if working_day is None and ctx.rent_due is not None and _steps(rule)[1] == "months":
        working_day = ctx.rent_due.working_day
    if (
        working_day is None
        and _is_rent(item, ctx)
        and ctx.letter_kind == "rent_lease"
        and same_rule(rule, Recurrence())
        and spec is not None
        and spec.type == "none"
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


def _given(item: Item, ctx: RuleContext) -> date | None:
    """The date the rules engine gives the item's DateSpec in ``ctx`` before a weekend or holiday moves it
    (``None`` without one)."""
    spec = item.date_spec
    if spec is None or spec.type == "none":
        return None
    return _parse(compute_due(spec.model_copy(update={"shift_rule": "none"}), ctx).due_date)


def first_occurrence(item: Item, ctx: RuleContext) -> date | None:
    """Where the item's schedule starts (point 2): the date its DateSpec gives before a weekend or
    holiday moves it (a fixed date as written, a relative one counted in ``ctx``), else its current
    date. With a working day only the month counts (point 8): the first of the month of the date the rules
    engine gives its DateSpec in ``ctx`` (so a rent increase's new rent never starts before § 558b BGB
    allows it), else of its current date's or the current month — ``None`` for a rent increase's new rent
    without a date, which only a date its letter gives can start. A rent that keeps an earlier rent's day of
    the month (point 9) starts on that day of the month the rules engine's date names."""
    rule, spec, given = schedule_rule(item, ctx), item.date_spec, None
    by_working_day = rule is not None and rule.working_day is not None
    keeps = ctx.rent_due
    if spec is not None and spec.type == "fixed" and not by_working_day and keeps is None:
        given = _parse(spec.date)
    else:
        given = _given(item, ctx)
    start = given or _parse(item.due_date)
    if not by_working_day:
        if start is not None and keeps is not None and keeps.day is not None:
            return _add_months(start, 0, keeps.day)
        return start
    if start is None and ctx.letter_kind == "rent_increase":
        return None
    return (start or ctx.today).replace(day=1)


def _anchor_day(first: date, rule: Recurrence, ctx: RuleContext) -> int:
    """The day of the month the schedule's months are dated by: the day a rent keeps from the rent before it
    (point 9: a kept 31st stays the last day of every month, not the 30th its first month clipped it to),
    else its first occurrence's (with a working day, the month's first: point 8)."""
    kept = ctx.rent_due.day if ctx.rent_due is not None and rule.working_day is None else None
    return kept or first.day


def over_the_law(
    item: Item, due: str | None, receipt: ComputationReceipt | None
) -> ComputationReceipt | None:
    """Point 8: the ``receipt`` of a date ``due`` the person sets on rent the law's working day dates (its
    receipt says so), with a warning when that date is later than the law's: it replaces the law's day for
    every month (point 2), and if the lease names no day the law's is the one that counts."""
    by_law = item.computation is not None and LAW_DEFAULT_WARNING in item.computation.warnings
    if receipt is None or not by_law or due is None or item.due_date is None or due <= item.due_date:
        return receipt
    return receipt.model_copy(update={"warnings": [LAW_REPLACED_WARNING, *receipt.warnings]})


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


def kept_occurrence(item: Item, ctx: RuleContext, *, postal_buffer_days: int) -> date | None:
    """Point 9 for the date the person gives an undated rent that keeps an earlier rent's due day
    (``ctx.rent_due``; ``item`` with that date and the schedule it starts, point 2): the date of its occurrence
    scheduled in that date's month — the kept day, not the person's date, is where its months fall —, which
    the person's date stands in for (point 7), so paid, it moves on past that month. ``None`` for any other
    item."""
    rule, first, day = schedule_rule(item, ctx), first_occurrence(item, ctx), _parse(item.due_date)
    if ctx.rent_due is None or rule is None or first is None or day is None:
        return None
    month = day.replace(day=1)
    scheduled = next(_occurrences(first, rule, month, _anchor_day(first, rule, ctx)), None)
    if scheduled is None or (scheduled.year, scheduled.month) != (month.year, month.month):
        return None
    return _parse(_at(item, rule, first, scheduled, ctx, postal_buffer_days).due_date)


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


def _by_law(
    item: Item, rule: Recurrence, receipt: ComputationReceipt, ctx: RuleContext
) -> ComputationReceipt:
    """Point 8's notes on rent counted by working days: the rule it is due by (§ 556b Abs. 1 BGB), and when
    the working day is the law's, not the letter's, the warning to check the lease, one confidence level
    lower (``medium`` at most) — also on a rent that keeps the law's day of the rent before it (point 9)."""
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
    by_law = ctx.rent_due is None or ctx.rent_due.by_law
    if item.recurrence is not None and item.recurrence.working_day is None and by_law:
        update["warnings"] = [LAW_DEFAULT_WARNING, *receipt.warnings]
        update["confidence"] = "medium" if receipt.confidence == "high" else "low"
    return receipt.model_copy(update=update)


def _keeps_day(item: Item, receipt: ComputationReceipt, ctx: RuleContext) -> ComputationReceipt:
    """Point 9's note on a rent that keeps the due day of the rent before it: the start its letter names and
    whose day applies, next to the schedule it repeats on."""
    spec = item.date_spec
    given = _parse(spec.date) if spec is not None and spec.type == "fixed" else _given(item, ctx)
    if ctx.rent_due is None or given is None:
        return receipt
    source = ctx.rent_due.source
    step = ComputationStep(
        label=f"{source[:1].upper()}{source[1:]}{KEEPS_DAY_STEP}{_day(given)} as the start",
        date=given.isoformat(),
    )
    return receipt.model_copy(update={"steps": [receipt.steps[0], step, *receipt.steps[1:]]})


def _receipt(
    item: Item,
    rule: Recurrence,
    first: date,
    day: date,
    ctx: RuleContext,
    postal_buffer_days: int,
    reasons: Sequence[str] = (),
) -> ComputationReceipt:
    """The rules engine's receipt for the occurrence scheduled on ``day``, graded by how the letter was
    read: the rubric's notes on the item's receipt carry over (:func:`~ordnung.ingest.verify.regrade`),
    unless the person confirmed the item (or set its date: ``grounding="user"``); one undated so far (in its
    letter, point 8) by where its quote was found and ``reasons``, what its quote leaves out
    (:func:`~ordnung.ingest.plan.consistency_reasons`). A working day is counted in ``ctx`` without the
    letter's kind, so no letter rule re-dates it (point 8)."""
    counted = ctx if rule.working_day is None else replace(ctx, letter_kind=None)
    spec = _occurrence_spec(item, rule, day, ctx)
    computed = compute_due(spec, counted, postal_buffer_days=postal_buffer_days)
    undated = item.computation is None and item.due_date is None  # dated for the first time (point 8)
    if item.grounding != "user":
        computed = (
            grade_reading(computed, item.grounding, reasons)
            if undated
            else regrade(computed, item.computation)
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
    return _keeps_day(item, _by_law(item, rule, receipt, ctx) if _is_rent(item, ctx) else receipt, ctx)


def _at(
    item: Item,
    rule: Recurrence,
    first: date,
    day: date,
    ctx: RuleContext,
    postal_buffer_days: int,
    reasons: Sequence[str] = (),
) -> Item:
    """The item at the occurrence scheduled on ``day``, with its dates and receipt from the engine."""
    receipt = _receipt(item, rule, first, day, ctx, postal_buffer_days, reasons)
    source = item.due_date_source
    if item.origin == "extracted":  # the letter's schedule again, also after a date set by hand
        spec = item.date_spec
        fixed = (
            rule.working_day is None and ctx.rent_due is None and spec is not None and spec.type == "fixed"
        )
        source = "fixed" if fixed else "computed"
    return item.model_copy(
        update={
            "due_date": receipt.due_date,
            "send_by": receipt.send_by,
            "computation": receipt,
            "due_date_source": source,
        }
    )


def _following(
    item: Item, ctx: RuleContext, on_or_after: date, postal_buffer_days: int, reasons: Sequence[str] = ()
) -> tuple[date, Item] | None:
    """The first occurrence whose date (from the rules engine) is on or after ``on_or_after``: the day it
    is scheduled on and the item at it; ``None`` for an item without a schedule."""
    rule, first = schedule_rule(item, ctx), first_occurrence(item, ctx)
    if rule is None or first is None:
        return None
    # an occurrence scheduled earlier can be moved onto or past the day (a weekend, Easter, a working day)
    since = on_or_after - timedelta(days=_lookback(rule))
    for day in _occurrences(first, rule, since, _anchor_day(first, rule, ctx)):
        moved = _at(item, rule, first, day, ctx, postal_buffer_days, reasons)
        due = _parse(moved.due_date)
        if due is not None and due >= on_or_after:
            return day, moved
    raise ValueError("recurrence schedule does not reach the requested date")


def _moved(
    item: Item, ctx: RuleContext, on_or_after: date, postal_buffer_days: int, reasons: Sequence[str] = ()
) -> Item | None:
    """The item at the first occurrence whose date (from the rules engine) is on or after
    ``on_or_after``; ``None`` for an item without a schedule."""
    found = _following(item, ctx, on_or_after, postal_buffer_days, reasons)
    return found[1] if found is not None else None


def _until(
    item: Item, ctx: RuleContext, on_or_after: date, postal_buffer_days: int, ends: date | None
) -> Item | None:
    """:func:`_moved`, but ``None`` also when that occurrence is scheduled on or after ``ends``, the first
    day of the month a later rent replaces the item from (point 9: its series ends before it)."""
    found = _following(item, ctx, on_or_after, postal_buffer_days)
    if found is None or (ends is not None and found[0] >= ends):
        return None
    return found[1]


def at_occurrence(
    item: Item, due: str | None, ctx: RuleContext, *, postal_buffer_days: int, reasons: Sequence[str] = ()
) -> Item | None:
    """Point 6's kept occurrence: ``item`` (recomputed, or a new reading of the stored item) at the
    occurrence dated ``due`` (the stored date), with its dates and receipt from the engine in ``ctx``
    (point 5; ``reasons`` grade a reading without a date, :func:`first_scheduled`). The engine only moves a
    date later, so that is the last occurrence scheduled on or before ``due`` (in another holiday region it
    can fall on another day); a ``due`` off the schedule leads to the next occurrence. ``None`` for an item
    without a schedule."""
    rule, first, day = schedule_rule(item, ctx), first_occurrence(item, ctx), _parse(due)
    if rule is None or first is None or day is None:
        return None
    scheduled = _scheduled_by(first, rule, day, _anchor_day(first, rule, ctx))
    if scheduled is None:
        return _moved(item, ctx, day, postal_buffer_days, reasons)
    return _at(item, rule, first, scheduled, ctx, postal_buffer_days, reasons)


def _scheduled_by(first: date, rule: Recurrence, day: date, anchor_day: int) -> date | None:
    """The last occurrence scheduled on or before ``day`` (``None`` before the first): the one dated ``day``,
    as the engine only moves a date later (point 5)."""
    since = day - timedelta(days=_lookback(rule))
    occurrences = _occurrences(first, rule, since, anchor_day)
    scheduled = list(itertools.takewhile(lambda planned: planned <= day, occurrences))
    return scheduled[-1] if scheduled else None


def first_scheduled(
    item: Item,
    ctx: RuleContext,
    *,
    postal_buffer_days: int,
    starts: str | None = None,
    reasons: Sequence[str] = (),
) -> Item | None:
    """Point 8 when a letter is read or its dates are recomputed: an item whose rule has a working day
    (:func:`schedule_rule`) at its schedule's first occurrence (:func:`first_occurrence`), with its dates
    and receipt from the engine — an undated one starts in the current month, or in the month its contract
    ``starts`` if that is later (no rent before the tenancy begins), and is graded by ``reasons``, what its
    quote leaves out (:func:`~ordnung.ingest.plan.consistency_reasons`); :func:`rolled` then moves it on if
    it has passed. So is a rent that keeps an earlier rent's due day (``ctx.rent_due``, point 9). ``None``
    for any other item."""
    rule, first, start = schedule_rule(item, ctx), first_occurrence(item, ctx), _parse(starts)
    if rule is None or first is None or (rule.working_day is None and ctx.rent_due is None):
        return None
    undated = item.due_date is None and (item.date_spec is None or item.date_spec.type == "none")
    if undated and start is not None and start > first:
        first = start.replace(day=1)
    return _at(item, rule, first, first, ctx, postal_buffer_days, reasons)


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


def rolled(item: Item, ctx: RuleContext, *, postal_buffer_days: int, ends: date | None = None) -> Item | None:
    """Points 3 and 7: once its date (also one set by hand) has passed, the item moved to the first
    occurrence on or after ``ctx.today`` (and after the one a date set by hand replaced); ``None`` if
    nothing changes — also when that occurrence is scheduled on or after ``ends``, the month a later rent
    replaces it from (point 9: its last occurrence stays)."""
    onwards = _onwards(item, ctx.today)
    if not has_passed(item, ctx.today) or onwards is None:
        return None
    return _until(item, ctx, onwards, postal_buffer_days, ends)


def moved_on(
    item: Item, ctx: RuleContext, *, postal_buffer_days: int, ends: date | None = None
) -> Item | None:
    """Point 4: the item marked done, moved to the occurrence after the one it stands for (after its
    current date, or the occurrence a date set by hand replaced), not before ``ctx.today``, and open;
    ``None`` for an item without a schedule (it is done like any to-do), or when that occurrence is
    scheduled on or after ``ends``, the month a later rent replaces it from (point 9: it was the last)."""
    onwards = _onwards(item, ctx.today)
    if item.recurrence is None or onwards is None:
        return None
    moved = _until(item, ctx, onwards, postal_buffer_days, ends)
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
    stored: Item, recurrence: Recurrence | None, spec: DateSpec | None, due_date: str | None, ctx: RuleContext
) -> bool:
    """Point 6: whether the stored recurring item keeps its date over ``due_date``, newly computed for
    the schedule ``recurrence`` from ``spec``: the schedule is unchanged (:func:`same_schedule`, of the
    rules the dates follow in ``ctx``, :func:`schedule_rule` — the law's working day for a lease's rent is
    the lease's own third, point 8) and the stored date is the later one."""
    reading = stored.model_copy(update={"recurrence": recurrence, "date_spec": spec})
    followed = stored.model_copy(update={"recurrence": schedule_rule(stored, ctx)})
    return (
        same_schedule(followed, schedule_rule(reading, ctx), spec)
        and stored.due_date is not None
        and (due_date is None or stored.due_date > due_date)
    )


# --------------------------------------------------------------------------------------------------
# a later rent replaces the one it changes (point 9)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Replacement:
    """What ends a rent's series (point 9): the later rent and the first day of the month it starts in."""

    newer: Item
    starts: date

    def describe(self) -> str:
        """``replaced by “New monthly total rent €670” from Nov 2026``."""
        return f"replaced by “{self.newer.title}” from {self.starts:%b %Y}"


@dataclass(frozen=True)
class _Rent:
    """A rent that takes part in point 9, in its own context, with the first day of the month it starts in
    (``None``: a lease's own rent whose DateSpec gives no date, before all others) and the amount its letter
    says the change replaces (``replaces``: the change's old amount, "bisher 640,00 €"; ``None``: none)."""

    item: Item
    ctx: RuleContext
    start: date | None
    replaces: float | None = None

    @property
    def order(self) -> tuple[date, str, str]:
        """Oldest first: by start, then by when it was filed, then by id."""
        return (self.start or date.min, self.item.created_at, self.item.id)

    def restates(self, earlier: _Rent) -> bool:
        """Whether this rent restates the whole of the rent ``earlier``, so it can replace it and keep its due
        day: its letter's old amount is that rent's ("bisher 640,00 €"), or its amount is at least that rent's
        — not a statement's new prepayment (§ 560 Abs. 4 BGB), a heating advance, a parking space's rent or
        an instalment, which run beside it."""
        new, old = self.item.amount, earlier.item.amount
        if old is None:
            return False
        if self.replaces is not None and round(self.replaces, 2) == round(old, 2):
            return True
        return new is not None and new >= old


def is_rent(item: Item, contract: Contract | None) -> bool:
    """A rent of point 9: a payment out every month (not dismissed) linked to ``contract``, a rent
    contract."""
    rule = item.recurrence
    return (
        item.kind == "payment"
        and item.direction == "out"
        and item.status != "dismissed"
        and rule is not None
        and _steps(rule)[:2] == (1, "months")
        and contract is not None
        and contract.category == "rent"
        and item.contract_id == contract.id
    )


def series_start(item: Item, ctx: RuleContext) -> date | None:
    """The first day of the month a rent starts in (point 9): of the date the rules engine gives its DateSpec
    in its letter's context ``ctx`` (a rent increase's new rent never before § 558b BGB allows it); ``None``
    if it gives none."""
    given = _given(item, ctx)
    return given.replace(day=1) if given is not None else None


def _rent_contract(store: Store, item: Item) -> Contract | None:
    """The rent contract a payment every month is linked to (point 9); ``None`` for any other to-do."""
    if item.kind != "payment" or item.recurrence is None or item.contract_id is None:
        return None
    contract = store.get_contract(item.contract_id)
    return contract if contract is not None and contract.category == "rent" else None


def _replaced_amount(store: Store, item: Item) -> float | None:
    """The amount the letter of ``item`` says its change replaces (the change's old amount, "bisher 640,00
    €"); ``None`` when it names none."""
    extraction = store.get_extraction(item.doc_id) if item.doc_id else None
    change = extraction.change if extraction is not None else None
    return change.old_amount if change is not None else None


def _rent(store: Store, item: Item, contract: Contract | None, ctx: RuleContext) -> _Rent | None:
    """``item`` as a rent that takes part in point 9 — one its DateSpec starts, or a lease's own rent —,
    ``None`` for any other to-do (an undated rent not from a lease is an accepted limit)."""
    if not is_rent(item, contract):
        return None
    start = series_start(item, ctx)
    if start is None and ctx.letter_kind != "rent_lease":
        return None
    return _Rent(item, ctx, start, _replaced_amount(store, item))


def _other_rents(
    store: Store, item: Item, contract: Contract, today: date, context: ItemContext
) -> list[_Rent]:
    """The other rents of ``item``'s rent contract that take part in point 9, each in its own context
    (``context``), oldest first."""
    rents = [
        _rent(store, other, contract, context(store, other, today))
        for other in store.list_items(contract_id=contract.id)
        if other.id != item.id and is_rent(other, contract)
    ]
    return sorted((rent for rent in rents if rent is not None), key=lambda rent: rent.order)


def _earlier(start: date | None, later: date | None) -> bool:
    """Whether a rent that starts at ``start`` (``None``: a lease's own, before all others) starts in an
    earlier month than one that starts at ``later``."""
    return later is not None and (start or date.min) < later


def _standing(entries: Iterable[Activity]) -> Activity | None:
    """The latest payment that still stands of an item's ``item.done`` and ``item.reopened`` entries (newest
    first): each "Undo" (``item.reopened``) takes back the payment before it, so undoing a second payment
    leaves the first one standing."""
    undone = 0
    for entry in entries:
        if entry.kind == "item.reopened":
            undone += 1
        elif undone:
            undone -= 1
        else:
            return entry
    return None


def _last_payment(store: Store, item: Item) -> Activity | None:
    """The latest payment of ``item`` (marked done) that still stands (:func:`_standing`)."""
    return _standing(store.activity_about("item", item.id, kinds=_PAYMENT_KINDS))


def _owed(store: Store, rent: _Rent) -> bool:
    """Whether a later rent replaces the rents before it: always, but a rent increase's new rent only once
    the person agreed (§ 558b Abs. 1 BGB) — as far as Ordnung can tell, once they marked a payment of it paid
    that they haven't undone (paying it can count as agreeing; until then its receipt says the current rent
    stays due)."""
    return rent.ctx.letter_kind != "rent_increase" or _last_payment(store, rent.item) is not None


def replacement(store: Store, item: Item, ctx: RuleContext, context: ItemContext) -> Replacement | None:
    """Point 9: the later rent that replaces the rent ``item`` (in its context ``ctx``), and the month it
    starts in — the earliest a rent on its contract starts in after it, of the rents owed that restate the
    whole of it (:meth:`_Rent.restates`); ``None`` for a rent nothing replaces and for any other to-do.
    ``context`` gives the other rents' contexts."""
    contract = _rent_contract(store, item)
    rent = _rent(store, item, contract, ctx)
    if rent is None or contract is None:
        return None
    later = [
        other
        for other in _other_rents(store, item, contract, ctx.today, context)
        if _earlier(rent.start, other.start) and other.restates(rent) and _owed(store, other)
    ]
    first = min(later, key=lambda other: other.order) if later else None
    if first is None or first.start is None:
        return None
    return Replacement(first.item, first.start)


def rent_due(store: Store, item: Item, ctx: RuleContext, context: ItemContext) -> RentDue | None:
    """Point 9: the due day the rent ``item`` (in its context ``ctx``) keeps from the rent it follows — of the
    rents on its contract it restates (:meth:`_Rent.restates`), the one that starts last before it (of two,
    the one filed last) —: that rent's working day (its own, the law's, or one it keeps itself), else its day
    of the month. ``None`` when its own reading gives a working day, for a rent added by hand (its schedule
    starts on the date the person gave it, point 2), for a rent that follows none, and for any other to-do.
    ``context`` gives the other rents' contexts (without the day they keep: :func:`_kept_day` works that
    out)."""
    contract = _rent_contract(store, item)
    rent = _rent(store, item, contract, ctx)
    if rent is None or contract is None:
        return None
    return _kept_day(rent, _other_rents(store, item, contract, ctx.today, context))


def _kept_day(rent: _Rent, rents: Sequence[_Rent]) -> RentDue | None:
    """:func:`rent_due` of ``rent`` among the rents of its contract (``rents``, oldest first, each in its own
    context): the due day of the rent it follows, which keeps one itself from the rent before it — worked out
    down the same list, so each rent's context is asked for once."""
    item = rent.item
    rule = item.recurrence
    if item.origin == "manual" or rent.start is None or rule is None or rule.working_day is not None:
        return None
    before = [
        other
        for other in rents
        if other.item.id != item.id and _earlier(other.start, rent.start) and rent.restates(other)
    ]
    if not before:
        return None
    return _due_day(before[-1], _kept_day(before[-1], rents))


def _due_day(rent: _Rent, kept: RentDue | None) -> RentDue | None:
    """The due day of ``rent`` that a later rent keeps (point 9), with the one it keeps itself (``kept``): its
    working day, else its day of the month (``None`` if it has neither), and whose it is."""
    item = rent.item
    ctx = replace(rent.ctx, rent_due=kept)
    rule, first = schedule_rule(item, ctx), first_occurrence(item, ctx)
    lease = rent.ctx.letter_kind == "rent_lease"
    source = "the lease's due day" if lease else f"the due day of “{item.title}”"
    if rule is not None and rule.working_day is not None:
        own = item.recurrence is not None and item.recurrence.working_day is not None
        by_law = not own and (kept is None or kept.by_law)
        return RentDue(working_day=rule.working_day, by_law=by_law, source=source)
    if rule is None or first is None:
        return None
    return RentDue(day=_anchor_day(first, rule, ctx), source=source)


def with_rent_due(store: Store, item: Item, ctx: RuleContext, context: ItemContext) -> RuleContext:
    """``ctx`` with the due day the rent ``item`` keeps from the rent before it (``RuleContext.rent_due``,
    :func:`rent_due`; none for any other to-do). ``context`` gives the other rents' contexts without it."""
    due = rent_due(store, item, ctx, context)
    return ctx if due == ctx.rent_due else replace(ctx, rent_due=due)


def remembered(context: ItemContext) -> ItemContext:
    """``context``, working out each to-do's context once (by its id and the day) for one pass over the
    ledger — a letter read, a to-do changed, a day's tick —, as point 9 compares every rent of a contract
    with the others (asked for again each time, it grew with the fourth power of the rents: seconds for a
    long tenancy). A pass changes no to-do's letter, words or contract, which its context depends on."""
    known: dict[tuple[str, date], RuleContext] = {}

    def remembering(store: Store, item: Item, today: date) -> RuleContext:
        key = (item.id, today)
        if key not in known:
            known[key] = context(store, item, today)
        return known[key]

    return remembering


def _scheduled(item: Item, ctx: RuleContext) -> date | None:
    """The day the occurrence the item stands for (its own, or the one a date set by hand replaced: point
    7) is scheduled on; ``None`` if undated."""
    rule, first, day = schedule_rule(item, ctx), first_occurrence(item, ctx), replaced_occurrence(item)
    if rule is None or first is None or day is None:
        return None
    return _scheduled_by(first, rule, day, _anchor_day(first, rule, ctx))


def _last_before(
    item: Item, ctx: RuleContext, month: date, postal_buffer_days: int
) -> tuple[date, Item] | None:
    """The rent's last occurrence scheduled before ``month`` (a rent repeats every month): the day it is
    scheduled on and the rent at it, with its dates and receipt from the engine (point 5)."""
    rule, first = schedule_rule(item, ctx), first_occurrence(item, ctx)
    if rule is None or first is None:
        return None
    day = _add_months(month, -1, _anchor_day(first, rule, ctx))
    return day, _at(item, rule, first, day, ctx, postal_buffer_days)


def _with_note(
    previous: ComputationReceipt | None, receipt: ComputationReceipt | None
) -> ComputationReceipt | None:
    """``receipt`` with the note a rent increase's new rent carried in ``previous`` (only owed once agreed,
    § 558b Abs. 1 BGB): dating it again by the day it keeps (point 9) never makes it owed."""
    if receipt is None or previous is None or RENT_INCREASE_PAYMENT_WARNING not in previous.warnings:
        return receipt
    warnings = [*receipt.warnings, RENT_INCREASE_PAYMENT_WARNING]
    rule_ids = [*receipt.rule_ids, "bgb_558b"] if "bgb_558b" not in receipt.rule_ids else receipt.rule_ids
    return receipt.model_copy(update={"warnings": warnings, "rule_ids": rule_ids})


def _redated(item: Item, ctx: RuleContext, postal_buffer_days: int) -> Item | None:
    """Point 9: a rent that keeps the due day of the rent before it (or kept one), dated again when that
    rent came or went since, at the occurrence it stands at (point 6); ``None`` when nothing changes, and
    for one dated by hand."""
    steps = item.computation.steps if item.computation is not None else []
    kept = any(KEEPS_DAY_STEP in step.label for step in steps)
    keeps = ctx.rent_due is not None
    if item.due_date_source == "manual" or not (kept or keeps):
        return None
    moved = at_occurrence(item, item.due_date, ctx, postal_buffer_days=postal_buffer_days)
    if moved is None or (moved.due_date == item.due_date and kept == keeps):
        return None
    return moved.model_copy(update={"computation": _with_note(item.computation, moved.computation)})


def _close(store: Store, item: Item, last: Item, replaced: Replacement, message: str) -> Item:
    """Point 9: the rent ``item`` closed (done) at ``last``, its last occurrence, and the log saying what
    replaced it, with those dates for "Undo" (:func:`undo_done`), which reopens it there."""
    dates = {name: getattr(last, name) for name in SCHEDULE_FIELDS}
    completed = item.completed_at or now_iso()
    updated = store.update_item(item.id, **dates, status="done", snoozed_until=None, completed_at=completed)
    store.log_activity(
        "item.done",
        message,
        ref_type="item",
        ref_id=item.id,
        data={
            "due_date": last.due_date,
            "next_due_date": last.due_date,
            "undo": dates,
            "occurrence": was_for.isoformat() if (was_for := replaced_occurrence(last)) else None,
            "replaced_by": replaced.newer.id,
            "replaced_from": replaced.starts.isoformat(),
        },
    )
    return updated


def settle_rents(
    store: Store, today: date, context: ItemContext, *, contract_ids: Iterable[str | None] | None = None
) -> int:
    """Point 9 in the ledger, after a letter was read, its dates recomputed or a rent changed (never by the
    daily tick alone): on each rent contract (only those of ``contract_ids``, if given), an open or snoozed
    rent that stands in or past the month a later rent replaces it from goes back to its last occurrence
    before it, closed there if the person marked that one paid (:func:`_left_at_last`), and a rent that
    keeps the due day of the rent before it is dated again when that rent came or went (:func:`_redated`).
    ``context`` gives each to-do's context with the day it keeps; returns the number of rents changed."""
    wanted = None if contract_ids is None else {found for found in contract_ids if found}
    buffer = postal_buffer(store.get_profile())
    changed = 0
    for contract in store.list_contracts():
        if contract.category != "rent" or (wanted is not None and contract.id not in wanted):
            continue
        for item in store.list_items(contract_id=contract.id, status=ROLLING_STATUSES):
            if is_rent(item, contract):
                changed += _settled(store, item, context(store, item, today), context, buffer)
    return changed


def _settled(
    store: Store, item: Item, ctx: RuleContext, context: ItemContext, postal_buffer_days: int
) -> bool:
    """:func:`settle_rents` for one open or snoozed rent in its context ``ctx``: whether it changed."""
    replaced, scheduled = replacement(store, item, ctx, context), _scheduled(item, ctx)
    if replaced is not None and scheduled is not None and scheduled >= replaced.starts:
        last = _last_before(item, ctx, replaced.starts, postal_buffer_days)
        if last is not None and last[1].due_date is not None:
            _left_at_last(store, item, *last, replaced)
            return True
    redated = _redated(item, ctx, postal_buffer_days)
    if redated is None:
        return False
    _write(store, redated, SCHEDULE_FIELDS)
    return True


def _left_at_last(store: Store, item: Item, scheduled: date, last: Item, replaced: Replacement) -> None:
    """Point 9 for a rent already in or past the month a later rent replaces it from (paid ahead, rolled on
    or filed before that rent was read or owed): where points 3 and 4 would have left it had that rent been
    known — closed at ``last``, its last occurrence before that month (scheduled on ``scheduled``), if the
    person marked that one (or a later one) paid: the effect of their own click; else open there (point 1:
    never overdue)."""
    day = _parse(last.due_date)
    when = f" ({_day(day)})" if day is not None else ""
    marked = _marked(_last_payment(store, item))
    if marked is not None and marked >= scheduled:
        message = f"“{item.title}” ends with the payment marked paid{when} — {replaced.describe()}"
        _close(store, item, last, replaced, message)
        return
    _write(store, last, SCHEDULE_FIELDS)
    store.log_activity(
        "item.replaced",
        f"“{item.title}” is back at its last occurrence{when} — {replaced.describe()}",
        ref_type="item",
        ref_id=item.id,
        data={"replaced_by": replaced.newer.id, "replaced_from": replaced.starts.isoformat()},
    )


def _marked(entry: Activity | None) -> date | None:
    """The occurrence a payment marked paid (the one a date set by hand stood in for: point 7)."""
    return _parse(str(entry.data.get("occurrence") or entry.data.get("due_date") or "")) if entry else None


def undo_replaced(store: Store, item: Item, context: ItemContext, today: date) -> int:
    """Point 9 for the "Undo" of a payment of the rent ``item`` (:func:`undo_done` has just taken it back): a
    rent that payment closed — it made a rent increase's new rent owed, so :func:`settle_rents` closed the rent
    it replaces there (or the person then paid that one's last occurrence) — is open again when ``item`` no
    longer replaces it, at the occurrence after the latest one marked paid (point 4), not before ``today``;
    one another later rent ends before that stays closed. ``context`` gives each rent's context; returns
    the number of rents opened again."""
    entries = store.activity_about("item", item.id, kinds=_PAYMENT_KINDS)
    undone = entries[1] if len(entries) > 1 and entries[0].kind == "item.reopened" else None
    if undone is None or undone.kind != "item.done" or item.contract_id is None:
        return 0
    buffer = postal_buffer(store.get_profile())
    opened = 0
    for rent in store.list_items(contract_id=item.contract_id, status="done"):
        payments = store.activity_about("item", rent.id, kinds=_PAYMENT_KINDS)
        closed = payments[0] if payments else None
        if closed is None or closed.kind != "item.done" or closed.id < undone.id:
            continue
        ctx = context(store, rent, today)
        replaced = replacement(store, rent, ctx, context)
        if closed.data.get("replaced_by") != item.id or (
            replaced is not None and replaced.newer.id == item.id
        ):
            continue  # not closed by it, or still replaced by it (a payment of it that stands agreed it)
        marked = [day for day in (_marked(closed), _marked(_standing(payments[1:]))) if day is not None]
        onwards = max([today, *(day + timedelta(days=1) for day in marked)])
        moved = _until(rent, ctx, onwards, buffer, replaced.starts if replaced is not None else None)
        if moved is None or (due := _parse(moved.due_date)) is None:
            continue
        reopen = {"status": "open", "snoozed_until": None, "completed_at": None}
        _write(store, moved.model_copy(update=reopen), (*SCHEDULE_FIELDS, *reopen))
        message = (
            f"Reopened “{rent.title}” ({_day(due)}) — the payment of “{item.title}” that ended it was undone"
        )
        store.log_activity("item.reopened", message, ref_type="item", ref_id=rent.id)
        opened += 1
    return opened


# --------------------------------------------------------------------------------------------------
# the policy in the ledger
# --------------------------------------------------------------------------------------------------


def _write(store: Store, moved: Item, names: tuple[str, ...]) -> Item:
    return store.update_item(moved.id, **{name: getattr(moved, name) for name in names})


def roll_item(
    store: Store, item: Item, ctx: RuleContext, *, postal_buffer_days: int, ends: date | None = None
) -> Item:
    """Point 3 for one stored item: its current occurrence, written (the item itself if nothing moves) —
    never one scheduled on or after ``ends``, the month a later rent replaces it from (point 9)."""
    moved = rolled(item, ctx, postal_buffer_days=postal_buffer_days, ends=ends)
    return item if moved is None else _write(store, moved, SCHEDULE_FIELDS)


def roll_forward(store: Store, today: date, context: ItemContext) -> int:
    """Point 3 for the whole ledger: move every open or snoozed recurring item whose date has passed
    to its current occurrence, each in ``context(store, item, today)`` — a rent a later one replaces never
    into or past the month that one starts (point 9: :func:`replacement`); returns the count."""
    buffer = postal_buffer(store.get_profile())
    changed = 0
    for item in store.list_items(status=ROLLING_STATUSES):
        if has_passed(item, today):
            ctx = context(store, item, today)
            replaced = replacement(store, item, ctx, context)
            ends = replaced.starts if replaced is not None else None
            moved = roll_item(store, item, ctx, postal_buffer_days=buffer, ends=ends)
            changed += moved is not item
    return changed


def _done_verb(item: Item) -> str:
    if item.kind == "payment":
        return "Received" if item.direction == "in" else "Paid"
    return "Done"


def mark_done(
    store: Store,
    item: Item,
    ctx: RuleContext,
    *,
    postal_buffer_days: int,
    replaced: Replacement | None = None,
) -> Item | None:
    """Point 4 in the ledger: the recurring item marked done stays open. A dated one moves on to its
    next occurrence; the activity log says "Paid “Rent” (Thu 1 Oct 2026) — next on Sun 1 Nov 2026" and
    keeps the dates of the occurrence marked done for :func:`undo_done`. An undated one stays as it is
    ("Paid “Rent” — repeats every month"). A rent a later one ``replaced`` whose next occurrence would be in
    or past the month that one starts was at its last: it closes there (done), and the log says "Paid
    “Monthly rent” (Mon 5 Oct 2026) — replaced by “New monthly total rent €670” from Nov 2026" (point 9).
    ``None`` for an item that doesn't repeat: it is done like any to-do."""
    if item.recurrence is None:
        return None
    ends = replaced.starts if replaced is not None else None
    moved = moved_on(item, ctx, postal_buffer_days=postal_buffer_days, ends=ends)
    was, now = _parse(item.due_date), _parse(moved.due_date if moved else None)
    if moved is None and was is not None and replaced is not None:  # its last occurrence (point 9)
        message = f"{_done_verb(item)} “{item.title}” ({_day(was)}) — {replaced.describe()}"
        return _close(store, item, item, replaced, message)
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
            "occurrence": was_for.isoformat() if (was_for := replaced_occurrence(item)) else None,
        },
    )
    return updated


def undo_done(store: Store, item: Item) -> Item | None:
    """Point 4's "Undo": the recurring item set open again while it stands at the occurrence
    :func:`mark_done` moved it to goes back to the occurrence marked done, with its dates as they were
    (a rent closed at its last occurrence, point 9, is open there again); the log says "Reopened “Rent”
    (Thu 1 Oct 2026)". ``None`` when there is nothing to undo: the item was not marked done, has moved
    since, or was reopened already."""
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
