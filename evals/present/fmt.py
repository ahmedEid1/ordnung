"""How numbers are written on every page and chart (standard library only): one decimal, k of n, one dash."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

DASH = "–"
MINUS = "−"
_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def pct(value: float | None) -> str:
    """A rate as a percentage with one decimal: ``97.0 %``."""
    return "n/a" if value is None else f"{value * 100:.1f} %"


def num(value: float | None) -> str:
    """A rate in percent, one decimal, without the sign: ``97.0``."""
    return "n/a" if value is None else f"{value * 100:.1f}"


def ci(bounds: Sequence[float | None]) -> str:
    """An interval in percent: ``93.2–99.0``."""
    low, high = bounds
    return f"{num(low)}{DASH}{num(high)}"


def points(value: float | None) -> str:
    """A difference of two rates in percentage points, signed: ``+5.4``, ``−2.4``."""
    if value is None:
        return "n/a"
    text = f"{value * 100:+.1f}"
    return text.replace("-", MINUS)


def interval_points(bounds: Sequence[float | None]) -> str:
    """A difference's interval in points: ``+0.6 to +10.6``."""
    low, high = bounds
    return f"{points(low)} to {points(high)}"


def p_value(p: float) -> str:
    """A p-value as a sentence gives it after ``p``: ``< 0.001``, else three decimals (``0.064``)."""
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def kn(metric: Mapping[str, Any]) -> str:
    """``163/168``."""
    return f"{int(metric['k'])}/{int(metric['n'])}"


def of(metric: Mapping[str, Any]) -> str:
    """``163 of 168``."""
    return f"{int(metric['k'])} of {int(metric['n'])}"


def usd(value: float | None, digits: int = 4) -> str:
    return "n/a" if value is None else f"${value:.{digits}f}"


def seconds(ms: float | None) -> str:
    return "n/a" if ms is None else f"{ms / 1000:.1f} s"


def words(n: int) -> str:
    """A small count in words, as a sentence writes it."""
    return _WORDS[n] if 0 <= n < len(_WORDS) else str(n)


def join(parts: Sequence[str]) -> str:
    """``a, b and c``."""
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]
