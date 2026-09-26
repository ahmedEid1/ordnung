"""Hand-checked calendar facts for the expected dates in the manifest.

This module is deliberately independent of ``ordnung.rules``: the expected dates are written as
literals in the document modules (with the arithmetic spelled out in comments) and these helpers only
*assert* the facts the reasoning relies on (weekday, "is a business day", simple day/month steps).
The NRW public holidays are typed in by hand from the Easter dates (2024-03-31, 2025-04-20,
2026-04-05, 2027-03-28).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

NRW_HOLIDAYS: frozenset[str] = frozenset(
    {
        # 2024 (Easter Sunday 31.03.)
        "2024-01-01",
        "2024-03-29",
        "2024-04-01",
        "2024-05-01",
        "2024-05-09",
        "2024-05-20",
        "2024-05-30",
        "2024-10-03",
        "2024-11-01",
        "2024-12-25",
        "2024-12-26",
        # 2025 (Easter Sunday 20.04.)
        "2025-01-01",
        "2025-04-18",
        "2025-04-21",
        "2025-05-01",
        "2025-05-29",
        "2025-06-09",
        "2025-06-19",
        "2025-10-03",
        "2025-11-01",
        "2025-12-25",
        "2025-12-26",
        # 2026 (Easter Sunday 05.04.)
        "2026-01-01",
        "2026-04-03",
        "2026-04-06",
        "2026-05-01",
        "2026-05-14",
        "2026-05-25",
        "2026-06-04",
        "2026-10-03",
        "2026-11-01",
        "2026-12-25",
        "2026-12-26",
        # 2027 (Easter Sunday 28.03.)
        "2027-01-01",
        "2027-03-26",
        "2027-03-29",
        "2027-05-01",
        "2027-05-06",
        "2027-05-17",
        "2027-05-27",
        "2027-10-03",
        "2027-11-01",
        "2027-12-25",
        "2027-12-26",
    }
)

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def weekday(value: str) -> str:
    """Three-letter English weekday of an ISO date."""
    return _WEEKDAYS[date.fromisoformat(value).weekday()]


def checked(value: str, expected_weekday: str) -> str:
    """Return ``value`` after asserting its weekday (guards the hand-written reasoning)."""
    actual = weekday(value)
    if actual != expected_weekday:
        raise AssertionError(f"{value} is a {actual}, not a {expected_weekday}")
    return value


def is_business_day(value: str) -> bool:
    """Mon–Fri and not an NRW public holiday."""
    return weekday(value) not in ("Sat", "Sun") and value not in NRW_HOLIDAYS


def is_werktag(value: str) -> bool:
    """Mon–Sat and not an NRW public holiday."""
    return weekday(value) != "Sun" and value not in NRW_HOLIDAYS


def plus_days(value: str, days: int) -> str:
    """Calendar-day arithmetic."""
    return (date.fromisoformat(value) + timedelta(days=days)).isoformat()


def plus_months(value: str, months: int) -> str:
    """Same day number ``months`` later, clamped to the month end (§ 188 Abs. 2, 3 BGB)."""
    day = date.fromisoformat(value)
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1])).isoformat()


def expect(condition: bool, message: str) -> None:
    """Raise if a hand-checked fact does not hold (unlike ``assert`` this survives ``-O``)."""
    if not condition:
        raise AssertionError(message)
