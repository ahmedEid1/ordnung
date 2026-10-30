"""Amounts the way German letters print them, and ISO dates."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

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


def iso(value: str) -> date:
    """Parse an ISO date."""
    return date.fromisoformat(value)
