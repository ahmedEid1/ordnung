"""Number and date formatting the way German (and British-English) letters print them."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

MONTHS_DE = (
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
)
MONTHS_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
WEEKDAYS_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")

CENT = Decimal("0.01")


def money(value: Decimal | str | int) -> Decimal:
    """Parse/round to a two-decimal ``Decimal`` (commercial rounding)."""
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def de_num(value: Decimal | str | int, decimals: int = 2) -> str:
    """``1234.5`` → ``1.234,50`` (German grouping and decimal comma)."""
    quant = Decimal(1).scaleb(-decimals) if decimals else Decimal(1)
    number = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    sign = "-" if number < 0 else ""
    text = f"{abs(number):,.{decimals}f}"
    return sign + text.replace(",", "X").replace(".", ",").replace("X", ".")


def eur(value: Decimal | str | int) -> str:
    """``1234.5`` → ``1.234,50 €``."""
    return f"{de_num(value)} €"


def en_eur(value: Decimal | str | int) -> str:
    """``450`` → ``EUR 450.00`` (British style used by the English letter)."""
    return f"EUR {Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP):,.2f}"


def iso(value: str) -> date:
    """Parse an ISO date."""
    return date.fromisoformat(value)


def de_date(value: str) -> str:
    """``2026-09-15`` → ``15.09.2026``."""
    return iso(value).strftime("%d.%m.%Y")


def de_date_long(value: str) -> str:
    """``2026-09-15`` → ``15. September 2026``."""
    day = iso(value)
    return f"{day.day}. {MONTHS_DE[day.month - 1]} {day.year}"


def de_weekday_date(value: str) -> str:
    """``2026-10-14`` → ``Mittwoch, 14.10.2026``."""
    return f"{WEEKDAYS_DE[iso(value).weekday()]}, {de_date(value)}"


def en_date(value: str) -> str:
    """``2026-09-05`` → ``5 September 2026``."""
    day = iso(value)
    return f"{day.day} {MONTHS_EN[day.month - 1]} {day.year}"
