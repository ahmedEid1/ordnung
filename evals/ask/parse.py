"""Reading dates and amounts out of an answer, for scoring — independent of the app's own parser.

The answer check in the app (``ordnung.assistant.support``) and this scorer must not share a parser:
a blind spot in one would then hide itself. This module reads the forms answers use — ``2026-10-21``,
``21.10.2026``, ``21.10.``, ``21 Oct 2026``, ``Wed 21 October``, ``21. Oktober 2026``,
``October 21, 2026``, ``21-10-2026``, ``94.99 €``, ``€94.99``, ``94,99 €``, ``EUR 1,560.00``,
``640 €`` — and notes whether a value stands inside the quotation marks the answer check puts around
a letter's words (“…”, or „…“ in a German answer). A date without a year is read in the year closest
to the sample life's today. The answer is read as it is shown: Markdown emphasis and code markers,
backslash escapes and invisible characters are dropped first, so ``31.**12**.2027`` is a date.

Numbers count as amounts when a currency stands next to them or when they have exactly two decimals.
Citation markers (``[item:itm_…]``) are removed first, so ids never read as numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from evals.ask.ledger import TODAY

_MONTHS = {
    **dict.fromkeys(("january", "jan", "januar", "jänner"), 1),
    **dict.fromkeys(("february", "feb", "februar"), 2),
    **dict.fromkeys(("march", "mar", "märz", "maerz", "mär"), 3),
    **dict.fromkeys(("april", "apr"), 4),
    **dict.fromkeys(("may", "mai"), 5),
    **dict.fromkeys(("june", "jun", "juni"), 6),
    **dict.fromkeys(("july", "jul", "juli"), 7),
    **dict.fromkeys(("august", "aug"), 8),
    **dict.fromkeys(("september", "sept", "sep"), 9),
    **dict.fromkeys(("october", "oct", "oktober", "okt"), 10),
    **dict.fromkeys(("november", "nov"), 11),
    **dict.fromkeys(("december", "dec", "dezember", "dez"), 12),
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DATE = re.compile(
    rf"""
      (?<![\d.])(?P<iy>\d{{4}})-(?P<im>\d{{2}})-(?P<id>\d{{2}})(?!\d)
    | (?<![\d.-])(?P<hd>\d{{1,2}})-(?P<hm>\d{{1,2}})-(?P<hy>\d{{4}})(?!\d)
    | (?<![\d.,])(?P<dd>\d{{1,2}})\.(?P<dm>\d{{1,2}})\.(?P<dy>\d{{4}}|\d{{2}}(?!\d))?
    | (?<![\d.,])(?P<wd>\d{{1,2}})(?:st|nd|rd|th)?\.?\s+(?:of\s+)?(?P<wm>{_MONTH})\b\.?(?:,?\s+(?P<wy>\d{{4}}))?
    | \b(?P<mm>{_MONTH})\b\.?\s+(?P<md>\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(?P<my>\d{{4}}))?
    """,
    re.IGNORECASE | re.VERBOSE,
)
_CURRENCY = r"(?:€|EUR\b|Euro\b|euros?\b)"
_AMOUNT = re.compile(
    rf"""
    (?P<pre>{_CURRENCY}\s?)?
    (?<![\d.,])(?P<num>\d{{1,3}}(?:[.,\u202f\u00a0]\d{{3}})+(?:[.,]\d{{2}})?|\d+(?:[.,]\d{{1,2}})?)(?![\d])
    (?P<dash>,-)?
    (?P<post>\s?{_CURRENCY})?
    """,
    re.IGNORECASE | re.VERBOSE,
)
_MARKER = re.compile(
    r"\[\s*[a-z]+\s*:\s*[a-z]{3}_[a-z0-9]+(?:\s*[,;]\s*[a-z]+\s*:\s*[a-z]{3}_[a-z0-9]+)*\s*\]", re.I
)
_QUOTED = re.compile(r"“[^“”\n]{0,80}”|„[^„“\n]{0,80}“")
_HIDDEN = re.compile(r"[*_`\u00ad\u200b-\u200f\u2060-\u2064\ufeff]|\\(?=[.\-*_`])")


@dataclass(frozen=True)
class Mention:
    """A date or an amount found in a text; ``quoted``: inside the answer check's “…”."""

    kind: Literal["date", "amount"]
    text: str
    quoted: bool
    date: date = TODAY
    cents: int = 0


def _year_near(day: int, month: int) -> date | None:
    candidates = []
    for year in (TODAY.year - 1, TODAY.year, TODAY.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    return min(candidates, key=lambda value: abs((value - TODAY).days), default=None)


def _date(day: str, month: int, year: str | None) -> date | None:
    try:
        if year is None:
            return _year_near(int(day), month)
        full = int(year) if len(year) == 4 else 2000 + int(year)
        return date(full, month, int(day))
    except ValueError:
        return None


def _amount(number: str) -> float | None:
    """``1.560,00`` / ``1,560.00`` / ``94,99`` / ``640`` → float (``None`` when it is no amount)."""
    compact = re.sub(r"[\u202f\u00a0]", ".", number)
    decimal_at = max(compact.rfind("."), compact.rfind(","))
    if decimal_at >= 0 and len(compact) - decimal_at - 1 == 2:
        whole, cents = compact[:decimal_at], compact[decimal_at + 1 :]
    elif decimal_at >= 0 and len(compact) - decimal_at - 1 == 3:
        whole, cents = compact, "00"  # thousands: 1.560
    elif decimal_at >= 0:
        return None
    else:
        whole, cents = compact, "00"
    digits = re.sub(r"[.,]", "", whole)
    return float(f"{digits}.{cents}") if digits.isdigit() else None


def mentions(text: str) -> list[Mention]:
    """Every date and amount in ``text``, in reading order."""
    plain = _HIDDEN.sub("", _MARKER.sub("", text))
    quotes = [(match.start(), match.end()) for match in _QUOTED.finditer(plain)]

    def quoted(start: int, end: int) -> bool:
        return any(q_start < start and end < q_end for q_start, q_end in quotes)

    found: list[tuple[int, Mention]] = []
    taken: list[tuple[int, int]] = []
    for match in _DATE.finditer(plain):
        g = match.groupdict()
        if g["iy"]:
            value = _date(g["id"], int(g["im"]), g["iy"]) if 1 <= int(g["im"]) <= 12 else None
        elif g["hd"]:
            value = _date(g["hd"], int(g["hm"]), g["hy"]) if 1 <= int(g["hm"]) <= 12 else None
        elif g["dd"]:
            value = _date(g["dd"], int(g["dm"]), g["dy"]) if 1 <= int(g["dm"]) <= 12 else None
        elif g["wd"]:
            value = _date(g["wd"], _MONTHS[g["wm"].lower()], g["wy"])
        else:
            value = _date(g["md"], _MONTHS[g["mm"].lower()], g["my"])
        if value is not None:
            span = match.span()
            taken.append(span)
            found.append((span[0], Mention("date", match.group(), quoted(*span), date=value)))
    for match in _AMOUNT.finditer(plain):
        span = match.span("num")
        if any(start <= span[0] < end for start, end in taken):
            continue  # the day or year of a date
        has_currency = bool(match.group("pre") or match.group("post") or match.group("dash"))
        number = match.group("num")
        two_decimals = bool(re.search(r"[.,]\d{2}$", number))
        if not (has_currency or two_decimals):
            continue
        amount = _amount(number)
        if amount is not None:
            found.append(
                (span[0], Mention("amount", match.group().strip(), quoted(*span), cents=round(amount * 100)))
            )
    return [mention for _, mention in sorted(found, key=lambda pair: pair[0])]


def stated(text: str, *, include_quoted: bool = True) -> tuple[set[date], set[int]]:
    """The dates and amounts (cents) ``text`` states; ``include_quoted=False`` leaves out quotes."""
    dates: set[date] = set()
    cents: set[int] = set()
    for mention in mentions(text):
        if mention.quoted and not include_quoted:
            continue
        if mention.kind == "date":
            dates.add(mention.date)
        else:
            cents.add(mention.cents)
    return dates, cents
