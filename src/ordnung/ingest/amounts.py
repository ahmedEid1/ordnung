"""Money amounts in text (German ``1.234,56`` and English ``1,234.56``): the one parser that grounds an
amount on a letter (:mod:`ordnung.ingest.verify`) and compares an e-mail's two parts
(:mod:`ordnung.ingest.email_text`). A leaf: it imports only the text normaliser."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ordnung.ingest.normalize import fold_punctuation

_CURRENCY = r"(?:€|\beur(?:o|os)?\b|\$|\busd\b|£|\bgbp\b|\bchf\b)"
_AMOUNT_PATTERN = re.compile(
    rf"(?P<pre>{_CURRENCY}\s*)?(?:[-−]\s*)?(?<![\d.,])(?P<num>\d[\d.,]*\d|\d)(?!\d)"
    rf"(?P<dash>,-{{1,2}})?(?P<post>\s*{_CURRENCY})?",
    re.IGNORECASE,
)


def parse_amounts(text: str) -> list[float]:
    """Money amounts in ``text`` (German ``1.234,56`` and English ``1,234.56`` formats).

    Numbers with two decimals always count; whole numbers only next to a currency (``50 €``,
    ``EUR 1.200``, ``99,- €``). Dates and reference numbers are not amounts.
    """
    return [value for _, value in amount_mentions(text)]


def amount_mentions(text: str) -> list[tuple[str, float]]:
    """:func:`parse_amounts` with each amount's digits as written (``("1.234,56", 1234.56)``)."""
    return [(match.number, match.value) for match in amount_matches(text)]


@dataclass(frozen=True, slots=True)
class AmountMatch:
    """An amount found by :func:`amount_matches`: its digits as written, its value, the span of the
    digits in the *folded* text (:func:`~ordnung.ingest.normalize.fold_punctuation`) and whether a
    currency stands next to it."""

    number: str
    value: float
    start: int
    end: int
    has_currency: bool


def amount_matches(text: str) -> list[AmountMatch]:
    """The amounts of :func:`parse_amounts`, with where they stand and whether a currency marks them."""
    matches: list[AmountMatch] = []
    for match in _AMOUNT_PATTERN.finditer(fold_punctuation(text)):
        has_currency = bool(match.group("pre") or match.group("post") or match.group("dash"))
        value = _amount_value(match.group("num"), has_currency)
        if value is not None:
            start, end = match.span("num")
            matches.append(AmountMatch(match.group("num"), value, start, end, has_currency))
    return matches


def _amount_value(number: str, has_currency: bool) -> float | None:
    """The value of a number as written, or ``None`` when it is not a well-formed amount (a malformed
    one such as ``12,34..56`` or an OCR slip like ``15,.09.26`` is not an amount — it never raises)."""
    separators = {ch for ch in number if ch in ".,"}
    if not separators:
        return _float(number) if has_currency else None
    if len(separators) == 2:
        decimal = "." if number.rfind(".") > number.rfind(",") else ","
        integer, _, fraction = number.rpartition(decimal)
        groups = integer.split("," if decimal == "." else ".")
        if len(fraction) == 2 and fraction.isdecimal() and _thousands_groups(groups):
            return _float("".join(groups) + "." + fraction)
        return None
    parts = number.split(separators.pop())
    if len(parts) == 2 and len(parts[1]) == 2 and all(part.isdecimal() for part in parts):
        return _float(f"{parts[0]}.{parts[1]}")
    if has_currency and _thousands_groups(parts):
        return _float("".join(parts))
    return None


def _thousands_groups(groups: list[str]) -> bool:
    """``1.234.567``: a first group of one to three digits, then groups of exactly three digits."""
    return (
        1 <= len(groups[0]) <= 3
        and all(len(g) == 3 for g in groups[1:])
        and all(g.isdecimal() for g in groups)
    )


def _float(digits: str) -> float | None:
    """The number, or ``None`` when it is none or too large to be an amount (hundreds of digits read as
    ``inf``, whose cents no code can compute)."""
    try:
        value = float(digits)
    except ValueError:  # defensive: the checks above only pass digits and one decimal point
        return None
    return value if math.isfinite(value) else None
