"""Period arithmetic under §§ 187, 188 BGB (applied via § 108 AO, § 31 VwVfG, § 26 SGB X, § 64 SGG, § 43 StPO).

Two start modes (SPEC § 21):

* ``event`` — the period starts with an event during a day (delivery, receipt, a letter's date). That
  day is not counted (§ 187 Abs. 1 BGB). A period in weeks/months/years ends on the day with the same
  weekday name or day number as the event day (§ 188 Abs. 2 Alt. 1 BGB); if that day number does not
  exist in the last month, on the last day of that month (§ 188 Abs. 3 BGB). There is no
  end-of-month rule: 30 Apr + 1 month = 30 May.
* ``day_start`` — the period starts at the beginning of a day, e.g. a contract term "from 01.03.2024
  for 24 months". The first day counts (§ 187 Abs. 2 BGB); the period ends on the day *before* the
  day with the same number (§ 188 Abs. 2 Alt. 2 BGB), so that term ends on 28.02.2026.

Only the end of a period can move off a weekend or holiday; that shift is applied by the caller
(:func:`shift_to_business_day`), because notice periods never shift (BGH III ZR 172/04).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Literal

from ordnung.models import ComputationStep, PeriodUnit
from ordnung.rules import calendar_de, catalog
from ordnung.rules.explain import capitalize_first, fmt_date, fmt_period, reason_phrase

PeriodMode = Literal["event", "day_start"]


def days_in_month(year: int, month: int) -> int:
    """Number of days in ``month`` of ``year``."""
    return calendar.monthrange(year, month)[1]


def _month_shift(d: date, months: int) -> tuple[int, int]:
    index = d.year * 12 + (d.month - 1) + months
    return index // 12, index % 12 + 1


def add_months(d: date, months: int) -> date:
    """Same day number ``months`` later (or earlier), clamped to the month's last day (§ 188 Abs. 3 BGB)."""
    year, month = _month_shift(d, months)
    return date(year, month, min(d.day, days_in_month(year, month)))


def _step(label: str, d: date | None, rule_id: str) -> ComputationStep:
    return ComputationStep(
        label=label,
        date=d.isoformat() if d else None,
        rule_id=rule_id,
        citation=catalog.citation(rule_id),
    )


def _event_end(start: date, amount: int, unit: PeriodUnit, region: str | None) -> tuple[date, str]:
    if unit == "days":
        return start + timedelta(days=amount), "bgb_188"
    if unit == "weeks":
        return start + timedelta(weeks=amount), "bgb_188"
    if unit == "business_days":
        return calendar_de.add_business_days(start, amount, region), "unit_business_days"
    if unit == "werktage":
        return calendar_de.add_werktage(start, amount, region), "unit_werktage"
    months = amount * 12 if unit == "years" else amount
    end = add_months(start, months)
    return end, "bgb_188_3" if end.day != start.day else "bgb_188"


def _day_start_end(start: date, amount: int, unit: PeriodUnit, region: str | None) -> tuple[date, str]:
    if unit == "days":
        return start + timedelta(days=amount - 1), "bgb_188"
    if unit == "weeks":
        return start + timedelta(weeks=amount) - timedelta(days=1), "bgb_188"
    if unit == "business_days":
        return calendar_de.add_business_days(start - timedelta(days=1), amount, region), "unit_business_days"
    if unit == "werktage":
        return calendar_de.add_werktage(start - timedelta(days=1), amount, region), "unit_werktage"
    months = amount * 12 if unit == "years" else amount
    year, month = _month_shift(start, months)
    if start.day <= days_in_month(year, month):
        return date(year, month, start.day) - timedelta(days=1), "bgb_188"
    return date(year, month, days_in_month(year, month)), "bgb_188_3"


def add_period(
    start: date,
    amount: int,
    unit: PeriodUnit,
    *,
    mode: PeriodMode = "event",
    region: str | None = None,
) -> tuple[date, list[ComputationStep]]:
    """Compute the last day of a period of ``amount`` ``unit`` starting at ``start``.

    ``mode="event"``: ``start`` is the event day and is not counted (§ 187 Abs. 1 BGB).
    ``mode="day_start"``: ``start`` is the first day of the period and counts (§ 187 Abs. 2 BGB).
    ``region`` only matters for ``business_days`` and ``werktage``. The end is *not* moved off
    weekends or holidays here. ``amount`` must be ≥ 0 (≥ 1 for ``day_start``).
    Returns the end date and explanation steps.
    """
    if amount < 0 or (mode == "day_start" and amount < 1):
        raise ValueError(f"invalid period amount {amount} for mode {mode}")
    period = fmt_period(amount, unit)
    if mode == "event":
        end, rule_id = _event_end(start, amount, unit, region)
        steps = [
            _step(f"Counting starts the day after {fmt_date(start)}", start, "bgb_187_1"),
            _step(capitalize_first(f"{period} later: {fmt_date(end)}"), end, rule_id),
        ]
        return end, steps
    end, rule_id = _day_start_end(start, amount, unit, region)
    steps = [
        _step(f"The period starts on {fmt_date(start)}, and that day counts", start, "bgb_187_2"),
        _step(capitalize_first(f"{period} from that day run until {fmt_date(end)}"), end, rule_id),
    ]
    return end, steps


def _latest_before_counted_days(end: date, amount: int, region: str | None, *, werktage: bool) -> date:
    counts = calendar_de.is_werktag if werktage else calendar_de.is_business_day
    d, found = end, 0
    while found < amount:
        if counts(d, region):
            found += 1
        d -= timedelta(days=1)
    return d


def latest_receipt_for(end: date, amount: int, unit: PeriodUnit, region: str | None = None) -> date:
    """Latest day a declaration can arrive so that a period of ``amount`` ``unit`` fits before ``end``.

    Backward counterpart of :func:`add_period` in event mode: the result ``r`` is the latest day with
    ``add_period(r, amount, unit) <= end``. Example: a contract ending 30 Nov with one month's notice
    needs the notice by 31 Oct (a notice received on 31 Oct runs until 30 Nov, § 188 Abs. 3 BGB).
    ``amount`` must be ≥ 0.
    """
    if amount < 0:
        raise ValueError(f"invalid period amount {amount}")
    if unit == "days":
        return end - timedelta(days=amount)
    if unit == "weeks":
        return end - timedelta(weeks=amount)
    if unit in ("business_days", "werktage"):
        return _latest_before_counted_days(end, amount, region, werktage=unit == "werktage")
    months = amount * 12 if unit == "years" else amount
    candidate = add_months(end, -months)
    while add_months(candidate + timedelta(days=1), months) <= end:
        candidate += timedelta(days=1)
    return candidate


def shift_to_business_day(d: date, region: str | None, rule_id: str) -> tuple[date, list[ComputationStep]]:
    """Move a period's last day off Saturdays, Sundays and public holidays (§ 193 BGB and siblings).

    Returns ``d`` unchanged (and a confirming step) if it already is a business day.
    """
    shifted = calendar_de.next_business_day(d, region)
    if shifted == d:
        return d, [_step(f"{fmt_date(d)} is a working day, so it stays", d, rule_id)]
    why = reason_phrase(calendar_de.day_kind(d, region))
    return shifted, [
        _step(f"{fmt_date(d)} is {why}, so the deadline moves to {fmt_date(shifted)}", shifted, rule_id)
    ]
