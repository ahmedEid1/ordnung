"""Dates written in a text (:func:`parse_dates`, :func:`date_spans`): the reading of written dates the
rules engine, the verification and the checks share, below them all (standard library and
:mod:`~ordnung.ingest.normalize` only)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ordnung.ingest.normalize import fold_punctuation


@dataclass(frozen=True, slots=True)
class DateMention:
    """A date written in a text. ``year`` is ``None`` when omitted ("bis 15.01."); ``ambiguous``
    marks numeric dates whose day/month order is unclear (03/05/2026 yields both readings)."""

    text: str
    day: int
    month: int
    year: int | None
    ambiguous: bool = False

    def as_date(self) -> date | None:
        return date(self.year, self.month, self.day) if self.year is not None else None


_MONTHS = {
    **dict.fromkeys(("januar", "jänner", "january", "jan"), 1),
    **dict.fromkeys(("februar", "february", "feb"), 2),
    **dict.fromkeys(("märz", "maerz", "marz", "march", "mär", "mar"), 3),
    **dict.fromkeys(("april", "apr"), 4),
    **dict.fromkeys(("mai", "may"), 5),
    **dict.fromkeys(("juni", "june", "jun"), 6),
    **dict.fromkeys(("juli", "july", "jul"), 7),
    **dict.fromkeys(("august", "aug"), 8),
    **dict.fromkeys(("september", "sept", "sep"), 9),
    **dict.fromkeys(("oktober", "october", "okt", "oct"), 10),
    **dict.fromkeys(("november", "nov"), 11),
    **dict.fromkeys(("dezember", "december", "dez", "dec"), 12),
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
MONTH_NUMBERS: dict[str, int] = dict(_MONTHS)
"""Month names and abbreviations (German and English, case-folded) → month number."""
_ORDINAL = r"(?:st|nd|rd|th)?"
# Travel documents print the month twice: "10 FEB / FÉV 2027" (ICAO bilingual format).
_BILINGUAL_MONTH = re.compile(
    rf"(\d{{1,2}}\s+(?:{_MONTH}))\.?\s*/\s*[^\W\d_]{{3,5}}\.?\s+(\d{{4}})", re.IGNORECASE
)
_DATE_PATTERN = re.compile(
    rf"""
      (?<![\w.,/-])(?P<iso_y>\d{{4}})-(?P<iso_m>\d{{1,2}})-(?P<iso_d>\d{{1,2}})(?![\w-])
    | (?<![\w.,/])(?P<dot_d>\d{{1,2}})\.\s?(?P<dot_m>\d{{1,2}})\.(?:\s?(?P<dot_y4>\d{{4}})|(?P<dot_y2>\d{{2}}))?(?!\d)
    | (?<![\w.,/])(?P<sl_a>\d{{1,2}})/(?P<sl_b>\d{{1,2}})/(?P<sl_y>\d{{4}}|\d{{2}})(?![\d/])
    | (?<![\w.,])(?P<dm_d>\d{{1,2}}){_ORDINAL}\.?\s*(?:of\s+)?(?P<dm_m>{_MONTH})\b\.?(?:,?\s*(?P<dm_y>\d{{4}}))?(?!\d)
    | \b(?P<md_m>{_MONTH})\b\.?\s*(?P<md_d>\d{{1,2}}){_ORDINAL}\b(?:,?\s*(?P<md_y>\d{{4}}))?(?!\d)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def parse_dates(text: str) -> list[DateMention]:
    """Dates written in ``text``: ``15.10.2026``, ``15.10.26``, ``15.01.`` (no year),
    ``15. Oktober 2026``, ``15 October 2026``, ``October 15, 2026``, ``2026-10-15``, ``03/05/2026``.

    Invalid calendar dates are skipped; an ambiguous slash date yields both readings.
    """
    mentions: list[DateMention] = []
    text = _BILINGUAL_MONTH.sub(r"\1 \2", text)
    for match in _DATE_PATTERN.finditer(fold_punctuation(text)):
        mentions.extend(m for m in _date_readings(match) if _valid(m))
    return mentions


def date_spans(folded: str) -> list[tuple[int, int, DateMention]]:
    """The dates of :func:`parse_dates` with where each stands, ``(start, end, mention)``, in ``folded``:
    a text already folded (:func:`~ordnung.ingest.normalize.fold_punctuation`), whose offsets these are
    (an ambiguous slash date gives both readings at the same span)."""
    return [
        (match.start(), match.end(), mention)
        for match in _DATE_PATTERN.finditer(folded)
        for mention in _date_readings(match)
        if _valid(mention)
    ]


def _date_readings(match: re.Match[str]) -> list[DateMention]:
    g = match.groupdict()
    raw = match.group().strip()
    if g["iso_y"]:
        return [DateMention(raw, int(g["iso_d"]), int(g["iso_m"]), int(g["iso_y"]))]
    if g["dot_d"]:
        year = int(g["dot_y4"]) if g["dot_y4"] else _two_digit_year(g["dot_y2"])
        return [DateMention(raw, int(g["dot_d"]), int(g["dot_m"]), year)]
    if g["sl_a"]:
        first, second, year = int(g["sl_a"]), int(g["sl_b"]), _two_digit_year(g["sl_y"])
        day_first = DateMention(raw, first, second, year)  # European reading
        if first == second:
            return [day_first]
        ambiguous = first <= 12 and second <= 12
        return [
            DateMention(raw, first, second, year, ambiguous),
            DateMention(raw, second, first, year, ambiguous),  # US reading (month/day)
        ]
    if g["dm_d"]:
        year = int(g["dm_y"]) if g["dm_y"] else None
        return [DateMention(raw, int(g["dm_d"]), _MONTHS[g["dm_m"].casefold()], year)]
    year = int(g["md_y"]) if g["md_y"] else None
    return [DateMention(raw, int(g["md_d"]), _MONTHS[g["md_m"].casefold()], year)]


def _two_digit_year(value: str | None) -> int | None:
    if value is None:
        return None
    year = int(value)
    if len(value) == 4:
        return year
    return 2000 + year if year < 70 else 1900 + year


def _valid(mention: DateMention) -> bool:
    try:
        date(mention.year if mention.year is not None else 2024, mention.month, mention.day)
    except ValueError:
        return False
    return True
