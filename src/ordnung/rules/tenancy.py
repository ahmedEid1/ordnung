"""Tenancy letters: a rent increase request, the landlord's notice and the operating-cost statement.

Pure date functions; :mod:`ordnung.rules.letters` turns them into receipts.

* **Rent increase request** (*Mieterhöhungsverlangen*, § 558b BGB): the tenant has until the end of
  the second calendar month after the month the request arrived to agree ("Überlegungsfrist"); the
  higher rent is owed from the first day of the third month, and only after consent. Example
  (Mieterverein zu Hamburg): arrived 15 January → decide by 31 March, new rent from 1 April.
* **Objection to the landlord's notice** (§ 574b Abs. 2 BGB): it must reach the landlord at the
  latest two months before the tenancy ends. The period is counted backwards from the end day
  (:func:`~ordnung.rules.periods.latest_receipt_for`): ends 31 October → by 31 August. A period
  counted backwards never moves to a later day.
* **Operating-cost statement** (§ 556 Abs. 3 BGB): it must reach the tenant by the end of the twelfth
  month after the billing period ends, else a back-payment is no longer owed unless the landlord was
  not responsible for the delay; the tenant's objections are due twelve months after it arrived.

Safety policy for the statement check (SPEC § 21): the harmful mistake here is telling someone they
need not pay when they must, so every uncertainty is resolved in the landlord's favour — the later
of the two readings of "end of the twelfth month", the weekend/holiday shift of § 193 BGB (with
*any* Land's holiday when the region is unknown) and, when the arrival day is not confirmed, a
statement dated on or before the deadline counts as on time. A statement is called late only when
it certainly is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ordnung.rules import calendar_de
from ordnung.rules.periods import add_months, days_in_month, latest_receipt_for

#: The two caps of § 558 Abs. 3 BGB, in per cent within three years.
RENT_CAP_PERCENT = 20.0
RENT_CAP_TIGHT_MARKET_PERCENT = 15.0


def month_end(d: date) -> date:
    """The last day of ``d``'s month."""
    return date(d.year, d.month, days_in_month(d.year, d.month))


def consent_period(received: date) -> tuple[date, date]:
    """``(last day to agree, first day of the higher rent)`` for a request that arrived on ``received``.

    The last day is the end of the second calendar month after the month of arrival (§ 558b Abs. 2
    BGB); the higher rent is owed from the next day, the start of the third month (§ 558b Abs. 1 BGB).
    """
    last = month_end(add_months(received.replace(day=1), 2))
    return last, last + timedelta(days=1)


def notice_objection_deadline(tenancy_end: date) -> date:
    """Last day an objection to the landlord's notice can arrive: two months before the tenancy ends."""
    return latest_receipt_for(tenancy_end, 2, "months")


def rent_increase_percent(old: float, new: float) -> float | None:
    """How much the rent rises, in per cent rounded to one decimal (``None`` for unusable amounts)."""
    if old <= 0 or new <= 0:
        return None
    return round((new - old) / old * 100, 1)


def _latest_working_day_on_or_after(d: date, region: str | None) -> date:
    """``d`` moved to a working day as § 193 BGB would, the latest way plausible.

    With a known region its holidays count; without one, a holiday in any Land counts too, because
    the tenant's own Land might have it.
    """
    while not calendar_de.is_business_day(d, region) or (
        region is None and calendar_de.regional_holiday_lands(d)
    ):
        d += timedelta(days=1)
    return d


@dataclass(frozen=True)
class StatementCheck:
    """Whether an operating-cost statement arrived in time (§ 556 Abs. 3 BGB).

    ``late`` is ``True`` only when the statement certainly arrived after ``deadline``, ``False`` when it
    arrived in time, ``None`` when the arrival day is unknown and the letter's date does not decide it.
    ``raw_deadline`` is the end of the twelfth month before any weekend/holiday shift: a statement that
    arrived after it is on time only by that shift, which the card says (its use here is disputed).
    ``objections_by`` is the last day the tenant's objections can arrive.
    """

    period_end: date
    raw_deadline: date
    deadline: date
    arrived: date
    arrival_confirmed: bool
    late: bool | None
    objections_by: date


def statement_check(
    period_end: date, arrived: date, *, confirmed: bool, region: str | None = None
) -> StatementCheck:
    """Check a statement for the billing period ending ``period_end`` that arrived on ``arrived``.

    ``arrived`` is the confirmed arrival day, or else the statement's own date (it can only have
    arrived later). ``region`` is the tenant's Land (where the statement must arrive). The deadline is
    the last day of the twelfth month after the period ends, moved off weekends and holidays; the
    objection deadline is twelve months after arrival, moved the same way (§ 193 BGB).
    """
    raw_deadline = month_end(add_months(period_end, 12))
    deadline = _latest_working_day_on_or_after(raw_deadline, region)
    if arrived > deadline:
        late: bool | None = True
    elif confirmed:
        late = False
    else:
        late = None
    objections_by = calendar_de.next_business_day(add_months(arrived, 12), region)
    return StatementCheck(
        period_end=period_end,
        raw_deadline=raw_deadline,
        deadline=deadline,
        arrived=arrived,
        arrival_confirmed=confirmed,
        late=late,
        objections_by=objections_by,
    )
