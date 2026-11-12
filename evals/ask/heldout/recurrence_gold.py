"""The gold of the questions about the to-dos that repeat (the recurrence ledger), standard library only.

Each function gets a to-do as recurrence.json gives it, with its truth item's kind, amount and direction added.

Weekends and holidays (§ 193 BGB): where a declaration is to be made or a performance rendered on a fixed day and
that day is a Saturday, a Sunday or a public holiday at the place of performance, the next working day takes its
place. So a payment or a task that falls on such a day moves forward to the next working day (Monday to Friday, not
a public holiday of Nordrhein-Westfalen). An appointment is no declaration and no performance: it stays on its day.
A working-day rule already lands on a working day, so it never moves.
"""

from __future__ import annotations

import calendar
import datetime
from collections.abc import Iterator
from typing import Any

# The public holidays of Nordrhein-Westfalen, written out by hand (Easter Sunday 2026: 5 April; 2027: 28 March).
HOLIDAYS_NW = {
    # 2026
    datetime.date(2026, 1, 1),  # Neujahr
    datetime.date(2026, 4, 3),  # Karfreitag
    datetime.date(2026, 4, 6),  # Ostermontag
    datetime.date(2026, 5, 1),  # Tag der Arbeit
    datetime.date(2026, 5, 14),  # Christi Himmelfahrt
    datetime.date(2026, 5, 25),  # Pfingstmontag
    datetime.date(2026, 6, 4),  # Fronleichnam
    datetime.date(2026, 10, 3),  # Tag der Deutschen Einheit
    datetime.date(2026, 11, 1),  # Allerheiligen
    datetime.date(2026, 12, 25),  # 1. Weihnachtstag
    datetime.date(2026, 12, 26),  # 2. Weihnachtstag
    # 2027
    datetime.date(2027, 1, 1),  # Neujahr
    datetime.date(2027, 3, 26),  # Karfreitag
    datetime.date(2027, 3, 29),  # Ostermontag
    datetime.date(2027, 5, 1),  # Tag der Arbeit
    datetime.date(2027, 5, 6),  # Christi Himmelfahrt
    datetime.date(2027, 5, 17),  # Pfingstmontag
    datetime.date(2027, 5, 27),  # Fronleichnam
    datetime.date(2027, 10, 3),  # Tag der Deutschen Einheit
    datetime.date(2027, 11, 1),  # Allerheiligen
    datetime.date(2027, 12, 25),  # 1. Weihnachtstag
    datetime.date(2027, 12, 26),  # 2. Weihnachtstag
}
COVERED_YEARS = (2026, 2027)

# Kinds of to-do that stay on their day whatever day it is.
FIXED_KINDS = ("appointment",)


def is_working_day(day: datetime.date) -> bool:
    """Monday to Friday and no public holiday of Nordrhein-Westfalen."""
    return day.weekday() < 5 and day not in HOLIDAYS_NW


def _next_working_day(day: datetime.date) -> datetime.date:
    while not is_working_day(day):
        day += datetime.timedelta(days=1)
    return day


def _nth_working_day(year: int, month: int, n: int) -> datetime.date:
    last = calendar.monthrange(year, month)[1]
    days = [datetime.date(year, month, d) for d in range(1, last + 1)]
    working = [d for d in days if is_working_day(d)]
    return working[-1] if n == -1 else working[n - 1]


def _add_months(year: int, month: int, count: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + count
    return index // 12, index % 12 + 1


def _unmoved(todo: dict[str, Any], k: int) -> datetime.date:
    """The k-th occurrence (k = 0 is the first) as the rule gives it, before any move."""
    first = datetime.date.fromisoformat(todo["first"])
    if k == 0:
        return first
    rule = todo.get("rule") or {}
    interval, unit = int(rule.get("interval", 1)), rule.get("unit", "months")
    if unit == "days":
        return first + datetime.timedelta(days=k * interval)
    if unit == "weeks":
        return first + datetime.timedelta(days=7 * k * interval)
    months = k * interval * (12 if unit == "years" else 1)
    year, month = _add_months(first.year, first.month, months)
    if rule.get("working_day") is not None:
        return _nth_working_day(year, month, int(rule["working_day"]))
    wanted = int(rule.get("day_of_month") or first.day)
    return datetime.date(year, month, min(wanted, calendar.monthrange(year, month)[1]))


def _moved(todo: dict[str, Any], day: datetime.date) -> datetime.date:
    if todo.get("kind") in FIXED_KINDS:
        return day
    if (todo.get("rule") or {}).get("working_day") is not None:
        return day
    if day.year not in COVERED_YEARS:
        raise ValueError(f"no holiday table for {day.year}")
    return _next_working_day(day)


# A move is three days at most (a Saturday before a Monday holiday); an occurrence whose unmoved day lies more
# than this before the asked range cannot reach it, so it is skipped unmoved (the table covers 2026 and 2027 only).
REACH = datetime.timedelta(days=10)


def _unmoved_series(todo: dict[str, Any], until: datetime.date) -> Iterator[datetime.date]:
    """Every occurrence as the rule gives it, before any move, up to ``until``."""
    k = 0
    while True:
        day = _unmoved(todo, k)
        if day > until:
            return
        yield day
        k += 1


def occurrences(todo: dict[str, Any], start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """Every occurrence from start to end (both included), each moved the same way."""
    found = []
    for day in _unmoved_series(todo, end):
        if day < start - REACH:
            continue
        moved = _moved(todo, day)
        if start <= moved <= end:
            found.append(moved)
    return found


def next_occurrence(todo: dict[str, Any], today: datetime.date) -> datetime.date:
    """The first occurrence on or after today, moved as a weekend or holiday moves it."""
    k = 0
    while True:
        day = _unmoved(todo, k)
        if day >= today - REACH:
            moved = _moved(todo, day)
            if moved >= today:
                return moved
        k += 1


def year_total(todo: dict[str, Any], year: int) -> float:
    """The to-do's amount summed over its occurrences that fall in that year."""
    amount = float(todo.get("amount") or 0.0)
    found = occurrences(todo, datetime.date(year, 1, 1), datetime.date(year, 12, 31))
    return round(amount * len(found), 2)
