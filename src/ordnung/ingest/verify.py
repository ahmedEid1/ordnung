"""Verification (SPEC §8 stage 5, §21): ground quotes on pages and check values against quotes.

* :func:`locate_quote` finds a model quote on the page texts — fuzzy (``partial_ratio`` ≥ 90 over
  normalised text) **and** exact for digits (every digit group of the quote must appear verbatim in
  the matched passage) — and maps the match back to highlight boxes on the page image.
* :func:`ground_evidence` turns that into :class:`~ordnung.models.Evidence` with a grounding level.
* :func:`spec_consistency` checks that a :class:`~ordnung.models.DateSpec` and an amount are
  actually stated by their quote (numbers, number words, units, explicit dates), and
  :func:`working_day_consistency` and :func:`day_of_month_consistency` that a recurrence's working day
  or day of the month is (:func:`working_days_named`, :func:`days_of_month_named`; a day stated as a
  schedule of dates counts: :func:`schedule_days_named`, and the middle of each quarter for a reading
  every three months from that middle: :func:`mid_quarter_named`);
  :func:`payment_day_sentence` finds the letter's one sentence stating a recurring payment's due day
  when its quote doesn't (:func:`payment_days_stated`).
* :func:`grade_reading` applies the § 21 confidence rubric's reading conditions to a date's receipt,
  and :func:`regrade` the same reading to the receipt of a schedule's next occurrence.
"""

from __future__ import annotations

import calendar
import functools
import itertools
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from rapidfuzz import fuzz

from ordnung.ingest.normalize import digit_tokens, fold_punctuation, normalise_with_map
from ordnung.ingest.text import PageText, Word
from ordnung.models import (
    LAST_WORKING_DAY,
    Box,
    ComputationReceipt,
    Confidence,
    DateSpec,
    Evidence,
    Grounding,
    Page,
    PeriodUnit,
    Recurrence,
)

MIN_SCORE = 90.0

# Reasons returned by spec_consistency (stable codes; the UI maps them to plain language).
AMBIGUOUS_DATE = "ambiguous_date"
DATE_WITHOUT_YEAR = "date_without_year"
DATE_NOT_IN_QUOTE = "date_not_in_quote"
PERIOD_NOT_IN_QUOTE = "period_not_in_quote"
AMOUNT_NOT_IN_QUOTE = "amount_not_in_quote"
INCOMPLETE_SPEC = "incomplete_spec"
# Returned by working_day_consistency: the reading's ``recurrence.working_day`` is not named by its quote.
WORKING_DAY_NOT_IN_QUOTE = "working_day_not_in_quote"
# Returned by day_of_month_consistency: the reading's ``recurrence.day_of_month`` is not named by its quote.
DAY_OF_MONTH_NOT_IN_QUOTE = "day_of_month_not_in_quote"

PageInput = PageText | Page | tuple[int, str, Sequence[Word | Sequence[Any]], str]
"""A page to search: a :class:`PageText`, a stored :class:`~ordnung.models.Page`, or
``(page, text, words, source)`` (``words`` as :class:`Word` or ``[text, x0, y0, x1, y1]`` rows;
``source`` is ``text``, ``transcript`` or ``none``)."""

_GROUNDING: dict[str, Grounding] = {"text": "verified", "transcript": "model_read"}


@dataclass(frozen=True, slots=True)
class Located:
    """Where a quote was found: page, fuzzy score, character span in the page text, highlight boxes."""

    page: int
    score: float
    start: int
    end: int
    boxes: list[Box] = field(default_factory=list)
    source: str = "text"


@dataclass(frozen=True, slots=True)
class _Page:
    number: int
    text: str
    words: tuple[Word, ...]
    source: str


# --------------------------------------------------------------------------------------------------
# Locating quotes
# --------------------------------------------------------------------------------------------------


def locate_quote(quote: str, pages: Sequence[PageInput]) -> Located | None:
    """Find ``quote`` on the best-matching page, or ``None``.

    Accepted only if the fuzzy score is ≥ :data:`MIN_SCORE` **and** every digit group of the quote
    (``15.10.2026``, ``1.234,56`` …) appears verbatim in the matched passage.
    """
    return _search(quote, pages)[0]


def ground_evidence(doc_id: str, quote: str, pages: Sequence[PageInput]) -> Evidence:
    """Evidence for ``quote``: ``verified`` on a text page (with boxes), ``model_read`` on an AI
    transcript, ``unverified`` otherwise (the best fuzzy score is kept for diagnostics)."""
    return check_quote(doc_id, quote, pages)[0]


@dataclass(frozen=True, slots=True)
class QuoteCheck:
    """How a quote was looked for (the facts a trace keeps, never the quote): the best fuzzy score on
    any page, the number of digit groups the exact-digits rule checked, and whether a passage that
    scored at least :data:`MIN_SCORE` had them all (``None``: no passage scored that high)."""

    best_score: float
    digit_groups: int
    digits_matched: bool | None


def check_quote(doc_id: str, quote: str, pages: Sequence[PageInput]) -> tuple[Evidence, QuoteCheck]:
    """:func:`ground_evidence` and how the search went."""
    located, check = _search(quote, pages)
    if located is None:
        return Evidence(doc_id=doc_id, quote=quote, grounding="unverified", score=check.best_score), check
    grounding = _GROUNDING.get(located.source, "unverified")
    evidence = Evidence(
        doc_id=doc_id,
        page=located.page,
        quote=quote,
        grounding=grounding,
        score=located.score,
        boxes=located.boxes if grounding == "verified" else [],
    )
    return evidence, check


def _search(quote: str, pages: Sequence[PageInput]) -> tuple[Located | None, QuoteCheck]:
    """The located quote (or ``None``) and how the search went."""
    norm_quote, _ = normalise_with_map(quote)
    if not norm_quote:
        return None, QuoteCheck(0.0, 0, None)
    quote_digits = [token for token, _, _ in digit_tokens(norm_quote)]
    candidates = []
    for page in map(_coerce, pages):
        norm, offsets = _normalised(page.text)
        if len(norm) < len(norm_quote):
            continue
        alignment = fuzz.partial_ratio_alignment(norm_quote, norm)
        if alignment is not None:
            candidates.append((alignment.score, page, norm, offsets, alignment))
    best = round(max((c[0] for c in candidates), default=0.0), 1)
    digits_matched: bool | None = None
    for score, page, norm, offsets, alignment in sorted(candidates, key=lambda c: -c[0]):
        if score < MIN_SCORE:
            break
        digits_matched = _digits_present(quote_digits, norm, alignment.dest_start, alignment.dest_end)
        if digits_matched:
            start, end = offsets[alignment.dest_start], offsets[alignment.dest_end - 1] + 1
            located = Located(page.number, round(score, 1), start, end, _boxes(page, start, end), page.source)
            return located, QuoteCheck(best, len(quote_digits), True)
    return None, QuoteCheck(best, len(quote_digits), digits_matched)


def _coerce(page: PageInput) -> _Page:
    if isinstance(page, PageText):
        return _Page(page.page, page.text, tuple(page.words), page.source)
    if isinstance(page, Page):
        return _Page(page.page, page.text, tuple(Word.from_row(w) for w in page.words), page.text_source)
    number, text, words, source = page
    return _Page(number, text, tuple(w if isinstance(w, Word) else Word.from_row(w) for w in words), source)


@functools.lru_cache(maxsize=256)
def _normalised(text: str) -> tuple[str, tuple[int, ...]]:
    norm, offsets = normalise_with_map(text)
    return norm, tuple(offsets)


def _digits_present(quote_digits: list[str], norm: str, start: int, end: int) -> bool:
    """Exact-digits rule: each digit group of the quote is a whole digit group of the passage."""
    passage = {token for token, s, e in digit_tokens(norm) if s < end and e > start}
    return all(token in passage for token in quote_digits)


def _boxes(page: _Page, start: int, end: int) -> list[Box]:
    """Boxes of the words overlapping ``[start, end)``, merged per text line."""
    boxes: list[Box] = []
    previous_end: int | None = None
    for word, (w_start, w_end) in _word_spans(page.text, page.words):
        if w_end <= start or w_start >= end:
            continue
        if boxes and previous_end is not None and "\n" not in page.text[previous_end:w_start]:
            last = boxes[-1]
            boxes[-1] = Box(
                page=page.number,
                x0=min(last.x0, word.x0),
                y0=min(last.y0, word.y0),
                x1=max(last.x1, word.x1),
                y1=max(last.y1, word.y1),
            )
        else:
            boxes.append(Box(page=page.number, x0=word.x0, y0=word.y0, x1=word.x1, y1=word.y1))
        previous_end = w_end
    return boxes


def _word_spans(text: str, words: Sequence[Word]) -> list[tuple[Word, tuple[int, int]]]:
    """Character spans of the words in ``text`` (words are in reading order; unmatched are skipped)."""
    spans: list[tuple[Word, tuple[int, int]]] = []
    cursor = 0
    for word in words:
        index = text.find(word.text, cursor) if word.text else -1
        if index >= 0:
            cursor = index + len(word.text)
            spans.append((word, (index, cursor)))
    return spans


# --------------------------------------------------------------------------------------------------
# Parsing dates, amounts and periods
# --------------------------------------------------------------------------------------------------


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


_NUMBER_WORDS = {
    **dict.fromkeys(("ein", "eine", "einem", "einen", "eines", "einer", "one", "a", "an"), 1),
    **dict.fromkeys(("zwei", "two"), 2),
    **dict.fromkeys(("drei", "three"), 3),
    **dict.fromkeys(("vier", "four"), 4),
    **dict.fromkeys(("fünf", "fuenf", "five"), 5),
    **dict.fromkeys(("sechs", "six"), 6),
    **dict.fromkeys(("sieben", "seven"), 7),
    **dict.fromkeys(("acht", "eight"), 8),
    **dict.fromkeys(("neun", "nine"), 9),
    **dict.fromkeys(("zehn", "ten"), 10),
    **dict.fromkeys(("elf", "eleven"), 11),
    **dict.fromkeys(("zwölf", "zwoelf", "twelve"), 12),
    **dict.fromkeys(("vierzehn", "fourteen"), 14),
    **dict.fromkeys(("zwanzig", "twenty"), 20),
    **dict.fromkeys(("dreissig", "thirty"), 30),  # casefold("dreißig") == "dreissig"
}
_UNITS: dict[str, PeriodUnit] = {
    **dict.fromkeys(
        ("tag", "tage", "tagen", "tages", "kalendertag", "kalendertage", "kalendertagen"), "days"
    ),
    **dict.fromkeys(("day", "days"), "days"),
    **dict.fromkeys(("werktag", "werktage", "werktagen", "werktages"), "werktage"),
    **dict.fromkeys(
        (
            "arbeitstag",
            "arbeitstage",
            "arbeitstagen",
            "bankarbeitstag",
            "bankarbeitstage",
            "bankarbeitstagen",
        ),
        "business_days",
    ),
    **dict.fromkeys(("woche", "wochen", "week", "weeks"), "weeks"),
    **dict.fromkeys(("monat", "monate", "monaten", "monats", "month", "months"), "months"),
    **dict.fromkeys(("jahr", "jahre", "jahren", "jahres", "year", "years"), "years"),
}
_BUSINESS_QUALIFIERS = frozenset({"business", "working", "bank"})
_UNIT_QUALIFIERS = _BUSINESS_QUALIFIERS | {"calendar", "full", "volle", "vollen"}
_NUMBER_LOOKBACK = 3


def parse_periods(text: str) -> list[tuple[int, PeriodUnit]]:
    """``(amount, unit)`` periods stated in ``text`` with digits or number words
    ("innerhalb eines Monats" → ``(1, "months")``, "within 5 business days" → ``(5, "business_days")``)."""
    tokens = re.findall(r"[^\W_]+", fold_punctuation(text).casefold())
    periods: list[tuple[int, PeriodUnit]] = []
    for index, token in enumerate(tokens):
        unit = _UNITS.get(token)
        if unit is None:
            continue
        before = index - 1
        if unit == "days" and before >= 0 and tokens[before] in _BUSINESS_QUALIFIERS:
            unit = "business_days"
        while before >= 0 and tokens[before] in _UNIT_QUALIFIERS:
            before -= 1
        amount = _nearest_number(tokens, before)
        if amount is not None:
            periods.append((amount, unit))
    return periods


def _nearest_number(tokens: list[str], index: int) -> int | None:
    for position in range(index, max(index - _NUMBER_LOOKBACK, -1), -1):
        token = tokens[position]
        if token.isdecimal():
            return int(token)
        if token in _NUMBER_WORDS:
            return _NUMBER_WORDS[token]
    return None


_ORDINAL_WORDS: dict[str, int] = {
    **dict.fromkeys(("erst", "first"), 1),
    **dict.fromkeys(("zweit", "second"), 2),
    **dict.fromkeys(("dritt", "third"), 3),
    **dict.fromkeys(("viert", "fourth"), 4),
    **dict.fromkeys(("fünft", "fuenft", "fifth"), 5),
    **dict.fromkeys(("sechst", "sixth"), 6),
    **dict.fromkeys(("siebent", "siebt", "seventh"), 7),
    **dict.fromkeys(("acht", "eighth"), 8),
    **dict.fromkeys(("neunt", "ninth"), 9),
    **dict.fromkeys(("zehnt", "tenth"), 10),
}
_GERMAN_ORDINAL = "erst|zweit|dritt|viert|fünft|fuenft|sechst|siebent|siebt|acht|neunt|zehnt"
_ENGLISH_ORDINAL = "first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"
_WORKING_DAY_PHRASE = re.compile(
    rf"""(?<![\w.,])
    (?: (?P<digits>10|[1-9])(?:\.|st|nd|rd|th)
      | (?P<german>{_GERMAN_ORDINAL})e[mnrs]?
      | (?P<english>{_ENGLISH_ORDINAL})
      | (?P<last>letzte[mnrs]?|last)
    )
    [\s)]*
    (?:werktag|(?:bank)?arbeitstag|(?:bank[\s-]+)?(?:working|business)[\s-]+day)""",
    re.IGNORECASE | re.VERBOSE,
)


def working_days_named(text: str) -> set[int]:
    """The working days (1–10, and -1 for the last) ``text`` names as an ordinal before *Werktag*,
    *Arbeitstag* (also *Bankarbeitstag*), "working day" or "business day" (also "bank working day"): a German
    ordinal word in any ending ("ersten" … "zehnten", "letzten"), digits with a full stop ("3. Werktag") or an
    English ordinal ("third", "3rd", "last"). "spätestens am dritten Werktag eines jeden Monats" → ``{3}``,
    "am letzten Bankarbeitstag des Monats" → ``{-1}``. A number of working days (a period: "innerhalb von 3
    Werktagen") names none, nor does a larger ordinal ("13. Werktag")."""
    named: set[int] = set()
    for match in _WORKING_DAY_PHRASE.finditer(fold_punctuation(text)):
        digits, word = match.group("digits"), match.group("german") or match.group("english")
        if match.group("last"):
            named.add(LAST_WORKING_DAY)
        else:
            named.add(int(digits) if digits else _ORDINAL_WORDS[word.casefold()])
    return named


_DAY_NUMBER = r"3[01]|[12]\d|0?[1-9]"
_EVERY_MONTH = r"(?:eines|des|jeden|jedes)\s+(?:jeden\s+)?(?:kalender)?monats"
_A_WORKING_DAY = r"\s*\)?\s*(?:werktag|(?:bank)?arbeitstag|(?:bank[\s-]+)?(?:working|business)[\s-]+day)"
_DAY_OF_MONTH_PHRASE = re.compile(
    rf"""(?<![\w.,])
    (?: (?:zum|am|bis|jeweils)\s+(?:(?:zum|am)\s+)?(?P<after>{_DAY_NUMBER})\.(?!\d)(?!{_A_WORKING_DAY})
      | (?P<before>{_DAY_NUMBER})\.\s*{_EVERY_MONTH}
      | (?P<english>{_DAY_NUMBER})(?:st|nd|rd|th)\b(?!{_A_WORKING_DAY})
      | (?P<start>monatsanfang|monatsbeginn|monatserste[mnr]?|(?:anfang|beginn|erste[mn]?(?:\s+tag)?)\s+{_EVERY_MONTH}
          |(?:start|beginning|first\s+day)\s+of\s+(?:each|every|the)\s+month)
      | (?P<middle>monatsmitte\b|mitte\s+{_EVERY_MONTH}|mid[\s-]*month\b|middle\s+of\s+(?:each|every|the)\s+month\b)
      | (?P<end>monatsende|monatsletzten|(?:ende|letzten\s+tag)\s+{_EVERY_MONTH}|zum\s+letzten\b(?!{_A_WORKING_DAY})
          |(?:end|last\s+day)\s+of\s+(?:each|every|the)\s+month)
    )""",
    re.IGNORECASE | re.VERBOSE,
)
# A month's start, middle and end in words are its 1st, 15th and last day (§ 192 BGB); the app dates a 31st
# on each month's last day (``Recurrence.day_of_month``).
_MONTH_START, _MONTH_MIDDLE, _MONTH_END = 1, 15, 31
# Words that make a month's start, middle or end a bound or a stretch of time, not the day ("ab Monatsanfang",
# "nach der Monatsmitte", "vor dem Monatsende", "um die Monatsmitte", "gegen Monatsende", "zwischen
# Monatsmitte und Monatsende", "after the middle of the month") — as digits name a day only after *zum*, *am*,
# *bis* or *jeweils*.
_BOUND_BEFORE = re.compile(
    r"""(?:\b(?:ab|nach|vor|seit|um|gegen|from|after|before|since|around|towards?)\s+
           (?:(?:der|dem|den|die|des|the)\s+)?
         |\b(?:zwischen|between)\s+(?:\S+\s+){0,6}?)$""",
    re.IGNORECASE | re.VERBOSE,
)


def days_of_month_named(text: str, rule: Recurrence | None = None, first: date | None = None) -> set[int]:
    """The days of the month (1–31) ``text`` names: digits with a full stop after *zum*, *am*, *bis* or
    *jeweils* ("jeweils zum 15.", "zum 1. eines Monats") or before *eines/des/jeden Monats*, an English
    ordinal ("the 1st"), and the start (1), middle (15) or end (31, a month's last day) of a month in words, as
    § 192 BGB reads them ("Monatsanfang", "zum Monatsersten", "am ersten Tag eines Monats", "zur Monatsmitte",
    "Mitte des Monats", "mid-month", "zum Monatsende", "zum Letzten", "end of the month") — never after a word
    that makes it a bound or a stretch of time ("ab Monatsanfang", "nach der Monatsmitte", "vor dem
    Monatsende", "zwischen Monatsmitte und Monatsende"). A date ("am 15.10.2026") names none, nor does a working
    day ("zum 3. Werktag") — but with ``rule`` (the recurrence the day is read for) a day its dates state as a
    schedule does (:func:`schedule_days_named`), and with ``first`` (the reading's first date, as its letter
    writes it) the middle of each quarter or three-month period (:func:`mid_quarter_named`)."""
    named: set[int] = set()
    plain = fold_punctuation(text)
    for match in _DAY_OF_MONTH_PHRASE.finditer(plain):
        digits = match.group("after") or match.group("before") or match.group("english")
        if digits:
            named.add(int(digits))
        elif _BOUND_BEFORE.search(plain, 0, match.start()):
            continue
        elif match.group("start"):
            named.add(_MONTH_START)
        elif match.group("middle"):
            named.add(_MONTH_MIDDLE)
        else:
            named.add(_MONTH_END)
    return named | _rule_days_named(text, rule, first)


def _rule_days_named(text: str, rule: Recurrence | None, first: date | None) -> set[int]:
    """The days ``text`` names only for its reading — ``rule``, its recurrence, and ``first``, its first date:
    as a schedule of dates (:func:`schedule_days_named`) or as the middle of each quarter
    (:func:`mid_quarter_named`)."""
    return schedule_days_named(text, rule) | mid_quarter_named(text, rule, first)


# The middle of each quarter ("zur Quartalsmitte", "Mitte des Quartals", "Mitte eines jeden
# Kalendervierteljahres", "mid-quarter", "the middle of each quarter") or of each three-month period ("in der
# Mitte eines Dreimonatszeitraums", § 7 Abs. 3 RBStV; "Mitte eines Zeitraums von drei Monaten", "Mitte eines
# dreimonatigen Zeitraums", "Mitte eines 3-Monats-Zeitraums", "the middle of each 3-month period").
_MID_QUARTER_PHRASE = re.compile(
    r"""(?<![\w.,])
    (?: (?P<quarter>quartalsmitte\b
          |mitte\s+(?:eines|des|jeden|jedes)\s+(?:(?:jeden|jeweiligen)\s+)?(?:kalender)?(?:quartals|vierteljahr(?:e)?s)\b
          |mid[\s-]*quarter\b|middle\s+of\s+(?:each|every|the|a)\s+(?:calendar\s+)?quarter\b)
      | (?P<period>mitte\s+(?:eines|des|jeden|jedes)\s+(?:(?:jeden|jeweiligen)\s+)?
            (?:(?:drei|3)[\s-]*monats[\s-]*zeitraum(?:e)?s|(?:drei|3)[\s-]*monatigen\s+zeitraum(?:e)?s
              |zeitraum(?:e)?s\s+von\s+(?:drei|3)\s+monaten)\b
          |middle\s+of\s+(?:each|every|the|a)\s+(?:three|3)[\s-]*months?\s+period\b)
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def mid_quarter_named(text: str, rule: Recurrence | None, first: date | None) -> set[int]:
    """The 15th, when ``text`` puts the payment in the middle of each quarter or three-month period ("in der
    Mitte eines Dreimonatszeitraums", "zur Quartalsmitte", "mid-quarter": :data:`_MID_QUARTER_PHRASE`) and
    the reading is a recurrence every three months (``rule``) whose first date (``first``) is that middle: the
    15th of February, May, August or November for a quarter, the 15th of any month for a three-month period.
    Else none — another interval, another first date, or none.

    ``first`` must be a date the letter itself writes (its caller checks: a date the item's quote or a page
    states, :func:`~ordnung.ingest.plan.first_date_written`): the phrase says the payment falls in the middle of
    a period, not which months make the periods, so only the letter's own due date anchors the month — a
    reading that moves it by a month or two (15.10. or 15.12. for a fee due 15.11.2026) is a 15th, too, and
    stays to be checked. A relative or undated reading has no such date.

    Why the 15th: a period of three months from the 1st of a month has its middle one and a half months on,
    and half a month is 15 days counted last (§ 189 BGB, which § 186 BGB applies to the dates of laws and
    contracts), so the middle is the end of the 15th of its second month — the middle of that month, too
    (§ 192 BGB). § 7 Abs. 3 RBStV has the broadcasting fee paid "in der Mitte eines Dreimonatszeitraums";
    its periods start on the 1st of the month the duty to pay begins (§ 7 Abs. 1 RBStV) and run from there,
    not by the calendar, so the Beitragsservice collects on the 15th of the middle month of each one (15
    February, May, August and November for a duty from January) and any 15th can be such a middle. A quarter
    (*Quartal*, *Vierteljahr*) is the calendar's, January to March and so on, so its middle is the 15th of
    February, May, August or November only. A first date off the 15th, or for a quarter a 15th in another
    month (15 January is in a quarter's first month), is no middle the phrase states and stays to be checked."""
    if _interval_months(rule) != 3 or first is None or first.day != _MONTH_MIDDLE:
        return set()
    for match in _MID_QUARTER_PHRASE.finditer(fold_punctuation(text)):
        if match.group("period") or first.month % 3 == 2:
            return {_MONTH_MIDDLE}
    return set()


_ON_THE = r"\s+(?:(?:am|zum|bis|on|by)\s+)?(?:(?:dem|den|the)\s+)?$"
# Wording that makes the date right after it recur ("fällig jeweils am 15.11.2026", "every quarter on 15
# November 2026", "every three months on …"; never "each form by …") …
_RECURS_FROM = re.compile(
    rf"""(?:\bjeweils
          |\b(?:each|every)\s+
             (?:(?:calendar|billing|payment|instal+ment|other|two|three|four|six|\d{{1,2}})\s+)?
             (?:months?|quarters?|weeks?|periods?|half[\s-]years?)\s+(?:on|by))
        {_ON_THE}""",
    re.IGNORECASE | re.VERBOSE,
)
# … or recur every year, before it ("jährlich zum 01.12.2026", "each year on 1 December 2026") or after it
# ("01.12.2026 eines jeden Jahres", "1 December 2026 of each year").
_YEARLY_FROM = re.compile(
    rf"(?:\b(?:all)?j(?:ä|ae)hrlich|\bannually|\byearly|\b(?:each|every)\s+year(?:\s+(?:on|by))?){_ON_THE}",
    re.IGNORECASE,
)
_YEARLY_UNTIL = re.compile(
    r"""\s*(?:(?:eines|des)\s+)?(?:jeden|jedes)\s+(?:kalender)?jahres\b
       |\s*(?:of\s+)?(?:each|every)\s+year\b
       |\s*(?:all)?j(?:ä|ae)hrlich\b""",
    re.IGNORECASE | re.VERBOSE,
)
# Due wording right before a date ("Hauptfälligkeit 01.12.", "zahlbar zum 01.12.", "due on 1 December") or
# right after it ("zum 01.12. fällig"): what a date without a year needs to be a yearly due day.
_DUE_BEFORE = re.compile(
    r"""(?:f(?:ä|ae)llig(?:keit)?|zahlbar|zu\s+zahlen|abgebucht|eingezogen
         |\bdue|\bpayable|\bdebited|\bcollected)
        \s*:?\s+(?:(?:jeweils|immer|stets|spätestens|am|zum|bis|on|by|the|dem|den)\s+){0,3}$""",
    re.IGNORECASE | re.VERBOSE,
)
_DUE_AFTER = re.compile(
    r"\s+(?:[^\W\d_]+\s+)?(?:f(?:ä|ae)llig|zahlbar|zu\s+zahlen|abgebucht|eingezogen|due|payable)\b",
    re.IGNORECASE,
)
# The words a marker below may have between it and its date ("erstmals jeweils am", "Beginn: den").
_THEN = r"\s*:?\s+(?:(?:jeweils|am|zum|ab|mit|vom|on|from|the|dem|den)\s+){0,3}$"
# A date the schedule starts from, never its day ("ab dem 01.11.2026", "from 1 November 2026", "beginning 1
# November 2026", "mit Wirkung zum 01.11.2026", "Der Vertrag beginnt am 01.11.", "Versicherungsbeginn:
# 01.11.2026", "erstmals am 01.12.2026", "die erste Rate ist am 01.12.2026", "first payment on …").
_STARTS_FROM = re.compile(
    rf"""(?:\bab|\bvom|\bseit|\bbeginnend|\bmit\s+wirkung\s+(?:zum|vom|ab)
         |\bbeginn(?:t|en)?|\bbegann|[^\W\d_]+beginn|\berstmal(?:s|ig)|\bzum\s+ersten\s+mal
         |\b(?:erste[mnrs]?|first)(?:\s+[^\W\d_]+){{0,3}}
         |\bfrom|\bstart(?:s|ed|ing)?|\bbegin(?:s|ning)?|\bcommenc(?:es|ed|ing)|\bas\s+(?:of|from)
         |\beffective(?:\s+date)?|\bwith\s+effect\s+(?:from|on)|\bstart\s+date)
       {_THEN}""",
    re.IGNORECASE | re.VERBOSE,
)
# A date that dates a letter, an invoice or a state, ends something, or is a notice date or a reference day — no
# due day ("Rechnungsdatum 15.10.2026", "Schreiben vom 01.10.2026", "Stand 01.11.2026", "endet am 01.11.2028",
# "Vertragsende 01.11.", "kündbar zum 31.03.", "Kündigungstermine: 31.03.", "zu den Stichtagen 31.03."); a
# month's, quarter's or year's end is a calendar day, which may well be due ("zum Quartalsende am 31.03.").
_NOT_DUE = re.compile(
    rf"""(?:\b(?!f(?:ä|ae)lligkeits|zahlungs|abbuchungs|buchungs|einzugs|lastschrift|termin)[^\W\d_]*datum
         |\bdatiert|\bstand|\bschreiben|\brechnung|\bbrief
         |\b[^\W\d_]*k(?:ü|ue)ndig[^\W\d_]*|\b[^\W\d_]*k(?:ü|ue)ndbar|\b[^\W\d_]*stichtag[^\W\d_]*
         |\bcancel[^\W\d_]*
         |\bende[nt]?|\bendete|\b(?!(?:halb)?(?:monats|quartals|vierteljahres|jahres)ende)[^\W\d_]+ende
         |\bablauf|\bbis\s+(?:zum\s+)?ende
         |\b(?:letter|invoice|issue|document)\s+date|\bdated|\bletter|\bas\s+at
         |\bends?|\bending|\bexpir(?:es|y|ing)|\bvalid\s+(?:until|to|through))
       {_THEN}""",
    re.IGNORECASE | re.VERBOSE,
)
# A clause or section number, which reads like a date without a year ("Ziffer 1.3.", "Nr. 1.1.", "§ 2.1.").
_CLAUSE = re.compile(
    r"""(?:§|\b(?:ziffer|ziff|nr|nummer|no|abschnitt|abschn|abs|absatz|punkt|pkt|klausel|tarif|artikel|art
        |kapitel|anlage|position|pos|section|sec|clause|item|chapter|paragraph|para|version))\.?\s*$""",
    re.IGNORECASE | re.VERBOSE,
)
# Between the two dates of a period ("Versicherungsjahr 01.12. – 30.11.", "vom 01.01.2026 bis 31.12.2026"); a
# dash joins a period's two dates only, three or more dates a dash joins are a list.
_UNTIL = re.compile(r"\s*(?:bis(?:\s+(?:zum|einschlie(?:ß|ss)lich))?|to|until|through)\s*", re.IGNORECASE)
_DASH = re.compile(r"\s*-\s*")
# Between two dates of one list ("10.03., 10.06., 10.09. und 10.12.", "am 01.12.2026 und am 01.12.2027").
_LISTED = re.compile(r"\s*(?:(?:[,;/&-]|und|and|sowie)\s*)+(?:(?:am|zum|on|the|dem|den)\s+)*", re.IGNORECASE)
# Wording a list of two dates needs before it to be a schedule ("Die Raten sind am …", "Abbuchung am …"), and a
# list of month ends on different days ("Die Abschläge sind am 31.03., 30.06., …"); a notice date is none
# ("Kündigungstermine").
_SCHEDULE_WORDS = re.compile(
    r"""f(?:ä|ae)llig|zahlbar|zu\s+zahlen|zahlung|(?<!kündigungs)(?<!kuendigungs)termin
        |\b(?:teil|monats|quartals|jahres)?rat(?:e|en)\b
        |abbuch|abgebucht|eingezogen|lastschrift|abschl(?:a|ä|ae)g
        |\bdue\b|payable|\binstal+ments?\b|\bpayments?\b|\bdebit""",
    re.IGNORECASE | re.VERBOSE,
)


def schedule_days_named(text: str, rule: Recurrence | None) -> set[int]:
    """The days of the month ``text`` states as the schedule of a recurrence every ``rule.interval`` months
    or years (none for a rule in days or weeks, or without one):

    * the day of three or more of its dates that fit the rule's interval — a whole number of intervals
      apart ("fällig jeweils am 10.03., 10.06., 10.09. und 10.12." every 3 months → 10; a year's dates
      without a year by their month) — or of two such dates one list joins after schedule or due wording
      ("Die Raten sind am 15.02.2027 und 15.08.2027 zu zahlen", "Abbuchung am 01.12.2026 und am 01.12.2027");
    * the day of a date without a year for a rule of a year or more, with due wording beside it
      ("Hauptfälligkeit 01.12.", "Der Jahresbeitrag ist zum 01.12. fällig", "due on 1 December");
    * the day of a date that wording makes recur ("jeweils am 15.11.2026", "every quarter on 15 November
      2026"), every year for a rule of a year or more ("jährlich zum 01.12.2026", "each year on 1 December
      2026", "01.12.2026 eines jeden Jahres").

    The dates one list joins ("10.03., 10.06., 10.09. und 10.12.") count for the day the whole list states
    (:func:`_list_day`): the day all of them are on, or the 31st — each month's last day — when each is on
    the last day of its month though not all on one day, with schedule or due wording before or due wording
    after it ("Abschläge fällig am 31.03., 30.06., 30.09. und 31.12." every 3 months → 31; never "Der Vertrag
    ist zum 31.03., 30.06., 30.09. oder 31.12. kündbar"). Every date of a list must fit: a list with a date on
    another day ("15.01., 15.04., 16.07. und 15.10.", also debit dates a weekend moved: "15.01.2029,
    16.04.2029, …") or off the rule's interval states another schedule than the reading's, and none of its
    dates counts; nor does any after wording that dates a letter, ends something or gives notice or reference
    days ("Die Abrechnungszeiträume enden am 31.03., 30.06., 30.09. und 31.12.", "Stichtage").

    A date the schedule starts from counts for none ("ab dem 01.11.2026", "from 1 November 2026", "beginning
    1 November 2026", "beginnt am", "Versicherungsbeginn", "erstmals", "first … on"): a single start date is
    never the recurring day. Nor does a date on its own ("fällig am 15.11.2026"), an ambiguous one
    (03/05/2026), one that dates a letter or an invoice or ends something ("Rechnungsdatum", "Stand", "endet
    am", "Vertragsende"), a clause number ("Ziffer 1.3.") or one that begins or ends a period
    ("Versicherungsjahr 01.12. – 30.11.")."""
    months = _interval_months(rule)
    if months is None:
        return set()
    plain = fold_punctuation(text)
    placed = date_spans(plain)
    spans = sorted({(start, end) for start, end, _ in placed})
    no_dates = _period_edges(plain, spans) | _clause_numbers(plain, spans)
    dates = [
        (start, end, mention)
        for start, end, mention in placed
        if not mention.ambiguous and (start, end) not in no_dates and not _STARTS_FROM.search(plain, 0, start)
    ]
    lists: list[list[tuple[int, int, DateMention]]] = []
    last_end = -1
    for start, end, mention in sorted(dates, key=lambda placed_date: placed_date[0]):
        if lists and _LISTED.fullmatch(plain, last_end, start):
            lists[-1].append((start, end, mention))
        else:
            lists.append([(start, end, mention)])
        last_end = end
    stated: list[tuple[list[tuple[int, int, DateMention]], int]] = []
    for group in lists:
        mentions = [mention for _, _, mention in group]
        day = _list_day(mentions, months)
        # Wording that dates a letter or ends something speaks for the whole list after it: "Die
        # Abrechnungszeiträume enden am 31.03., 30.06., 30.09. und 31.12." gives no due date at all.
        if day is None or _NOT_DUE.search(plain, 0, group[0][0]):
            continue
        # Month ends on different days are a schedule only as one ("Die Abschläge sind am …", "… fällig"),
        # never as notice dates or reference days ("Der Vertrag ist zum 31.03., 30.06., … kündbar").
        if len({mention.day for mention in mentions}) > 1 and not (
            _SCHEDULE_WORDS.search(plain, 0, group[0][0])
            or _DUE_BEFORE.search(plain, 0, group[0][0])
            or _DUE_AFTER.match(plain, group[-1][1])
        ):
            continue
        stated.append((group, day))
    yearly = months % 12 == 0
    named = {
        day
        for group, day in stated
        for start, end, mention in group
        if _RECURS_FROM.search(plain, 0, start)
        or (
            yearly
            and (
                (
                    mention.year is None
                    and (_DUE_BEFORE.search(plain, 0, start) or _DUE_AFTER.match(plain, end))
                )
                or _YEARLY_FROM.search(plain, 0, start)
                or _YEARLY_UNTIL.match(plain, end)
            )
        )
    }
    for day in {day for _, day in stated} - named:
        steps = _interval_steps(
            [mention for group, on in stated if on == day for _, _, mention in group], months
        )
        listed = any(
            on == day
            and len(_interval_steps([mention for _, _, mention in group], months)) >= 2
            and _SCHEDULE_WORDS.search(plain, 0, group[0][0])
            for group, on in stated
        )
        if len(steps) >= 3 or (len(steps) == 2 and listed):
            named.add(day)
    return named


def _list_day(mentions: Sequence[DateMention], months: int) -> int | None:
    """The day of the month the dates of one list (or a date on its own) state for a rule every ``months``
    months: the day all of them are on, or the 31st — each month's last day — when each is on the last day
    of its month (:func:`on_month_end`) though not all on one day; ``None`` for a list with a date on another
    day, or whose dates are no whole number of ``months`` apart (:func:`_interval_steps`). Dates all on the
    30th that end their months ("30.06. und 30.09.") state the 30th only: the 31st would be another day in
    March and December, which they don't show."""
    if not _interval_steps(mentions, months):
        return None
    days = {mention.day for mention in mentions}
    if len(days) == 1:
        return days.pop()
    return _MONTH_END if all(on_month_end(mention) for mention in mentions) else None


def on_month_end(mention: DateMention) -> bool:
    """Whether a date is on the last day of its month: in its year, or — without one — in every year, which a
    date in February never is (28.02. is its last day in three years of four, 29.02. in the fourth)."""
    if mention.year is None:
        # A common year: every month but February has the same length in every year.
        return mention.month != 2 and mention.day == calendar.monthrange(2001, mention.month)[1]
    return mention.day == calendar.monthrange(mention.year, mention.month)[1]


def _period_edges(plain: str, spans: Sequence[tuple[int, int]]) -> set[tuple[int, int]]:
    """The spans of ``spans`` (dates in ``plain``, in order) that begin or end a period: two dates *bis*,
    *to* or *until* joins ("vom 01.01.2026 bis 31.12.2026"), or exactly two a dash joins ("01.12. – 30.11.";
    a chain of three or more dashed dates is a list, "10.03.2026 – 10.06.2026 – 10.09.2026")."""
    pairs = list(itertools.pairwise(spans))
    dashed = [bool(_DASH.fullmatch(plain, first[1], second[0])) for first, second in pairs]
    return {
        edge
        for index, (first, second) in enumerate(pairs)
        if _UNTIL.fullmatch(plain, first[1], second[0])
        or (
            dashed[index]
            and not (index > 0 and dashed[index - 1])
            and not (index + 1 < len(pairs) and dashed[index + 1])
        )
        for edge in (first, second)
    }


def _clause_numbers(plain: str, spans: Sequence[tuple[int, int]]) -> set[tuple[int, int]]:
    """The spans of ``spans`` (dates in ``plain``, in order) that are clause or section numbers: after a
    clause word ("Ziffer 1.3.", "§ 2.1."), and the ones a list joins to it ("Ziffer 1.3., 1.6. und 1.9.")."""
    clauses: set[tuple[int, int]] = set()
    for index, span in enumerate(spans):
        joined = (
            index > 0
            and spans[index - 1] in clauses
            and _LISTED.fullmatch(plain, spans[index - 1][1], span[0])
        )
        if joined or _CLAUSE.search(plain, 0, span[0]):
            clauses.add(span)
    return clauses


def _interval_months(rule: Recurrence | None) -> int | None:
    """A rule's interval in months (every year is 12), ``None`` for a rule in days or weeks, or none."""
    if rule is None or rule.unit in ("days", "weeks"):
        return None
    return max(1, rule.interval) * (12 if rule.unit == "years" else 1)


def _interval_steps(mentions: Sequence[DateMention], months: int) -> list[int]:
    """The different months of ``mentions`` (by year and month, or — when one has no year — by month
    alone: "10.03., 10.06., 10.09. und 10.12."), when each is a whole number of ``months`` after the one
    before; else none."""
    if any(mention.year is None for mention in mentions):
        steps = sorted({mention.month for mention in mentions})
    else:
        steps = sorted(
            {mention.year * 12 + mention.month for mention in mentions if mention.year is not None}
        )
    if all((later - earlier) % months == 0 for earlier, later in itertools.pairwise(steps)):
        return steps
    return []


# --------------------------------------------------------------------------------------------------
# A recurring payment's due day stated elsewhere in its letter
# --------------------------------------------------------------------------------------------------

DueDay = tuple[Literal["working_day", "day_of_month"], int]
"""A recurring payment's due day: ``("working_day", 3)`` (the 3rd working day, -1 the last) or
``("day_of_month", 1)`` (the 1st, 31 a month's last day)."""

# Words of paying a sum when it falls due — paying, debiting, collecting, falling due — matched as whole words
# or word parts that only paying has: "Zahlung", "zahlbar", "zu zahlen" but not "Anzahl"; "Abbuchung",
# "abgebucht", "Lastschrift(einzug)", "eingezogen" but not "Einzug" alone (moving in); "überweisen", "fällig",
# "zu leisten", "entrichten"; "pay", "payable", "paid", "debit", "due", "collected", "transfer". A sum's name
# alone is none ("Beitrag", "Betrag", "Miete", "Abschlag", "rent", "instalment": "Den neuen Rechnungsbetrag
# teilen wir Ihnen jeweils zur Monatsmitte mit" says when a letter comes, not when a payment is due).
_PAYMENT_WORDS = re.compile(
    r"zahl(?:ung|bar|en\b|e\b|st\b|t\b|te\b|ten\b)|abbuch|abgebucht|lastschrift|einzugserm|eingezogen"
    r"|einzuziehen|einziehen|überweis|ueberweis|fällig|faellig|\bzu\s+leisten\b|entricht"
    r"|\bpay(?:s|ing|ments?|able)?\b|\bpaid\b|\bdebit|\bdue\b(?!\s+to\b)|\bcollect(?:s|ed|ion)?\b|\btransfer",
    re.IGNORECASE,
)
# A day that is no payment's due day, though a payment word is near: a notice period or an objection
# ("Die Kündigung muss bis zum 10. eines Monats …"), late fees from a day on ("Mahngebühren werden ab dem 15.
# fällig"), or a contract's start, end or term ("Ihr Vertrag endet zum Monatsende, der Beitrag …").
_NOT_A_PAYMENT = re.compile(
    r"kündig|kuendig|widerruf|widersp|einspruch|cancel|terminat|notice|withdraw|objection"
    r"|mahn|verzug|säumnis|saeumnis|\blate\b|overdue|arrear|penalt|\bab\s+(?:dem|den)\b|\b(?:from|after)\s+the\b"
    r"|\bendet\b|\benden\b|beginnt|vertragsende|vertragsbeginn|laufzeit|gültig|gueltig|in\s+kraft"
    r"|\bends\b|\bbegins\b|\bstarts\b|\bexpir|\bcommenc|\bterm\b|\beffective\b",
    re.IGNORECASE,
)
_MONTH_NAME = (
    r"januar|january|jan|februar|february|feb|märz|maerz|march|mär|mrz|mar|april|apr|mai|may|juni|june|jun"
    r"|juli|july|jul|august|aug|september|sept|sep|oktober|october|okt|oct|november|nov|dezember|december|dez|dec"
)
_NAMED_DATE = re.compile(
    rf"""(?<![\w.,])(?:{_DAY_NUMBER})(?:\.|st|nd|rd|th)?\s*(?:of\s+)?(?:{_MONTH_NAME})\b\.?
      | \b(?:{_MONTH_NAME})\.?\s+(?:{_DAY_NUMBER})(?:st|nd|rd|th)?\b""",
    re.IGNORECASE | re.VERBOSE,
)
# Where a line breaks inside a phrase ("… bis zum" / "10. eines Monats …", "am 3." / "Werktag …", "am
# dritten" / "Werktag …").
_CUT_PHRASE = re.compile(
    rf"""(?:\b(?:zum|am|bis|jeweils|spätestens|des|eines|jeden|jedes|dem|den|der|zur|the|on|by|of
            |(?:{_GERMAN_ORDINAL}|letzt)e[mnrs]?|{_ENGLISH_ORDINAL}|last)|\d\.)$""",
    re.IGNORECASE | re.VERBOSE,
)
# A line that goes on with the day's noun ("… am 3." / "Werktag", "… zum 15. eines" / "Monats").
_GOES_ON = re.compile(r"(?:werktag|(?:bank)?arbeitstag|monat)", re.IGNORECASE)
_RUNS_ON = re.compile(r"[a-zäöüß0-9(]")
# A word hyphenated across the break ("Monats-" / "anfang"), joined as the quote grounding joins it.
_HYPHENATED = re.compile(r"[^\W\d_]-$")
_SENTENCE_END = re.compile(r"(?<=[^\d\s][.!?])\s+(?=[\"(]?[A-ZÄÖÜ])")


def _sentences(text: str) -> list[str]:
    """A page's sentences on one line each: a line joins the one before when the sentence runs on (it
    starts in lower case, with a digit or a bracket after a line without a full stop), the break falls
    inside a phrase (after "zum", "3." or "dritten", or before "Werktag" or "Monats") or inside a hyphenated
    word ("Monats-" / "anfang" is "Monatsanfang"); a blank line ends a paragraph; sentences end at a full
    stop, question or exclamation mark before a capital (never after a digit: "am 3. Werktag")."""
    lines: list[str] = []
    joins = False
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            joins = False
            continue
        last = lines[-1] if lines and joins else None
        if last is not None and _HYPHENATED.search(last) and line[0].islower():
            lines[-1] = f"{last[:-1]}{line}"
        elif last is not None and (
            _CUT_PHRASE.search(last)
            or (last[-1] not in ".!?:" and (_RUNS_ON.match(line) or _GOES_ON.match(line)))
        ):
            lines[-1] = f"{last} {line}"
        else:
            lines.append(line)
        joins = True
    return [sentence for line in lines for sentence in _SENTENCE_END.split(line) if sentence]


def due_days_named(text: str, rule: Recurrence | None = None, first: date | None = None) -> set[DueDay]:
    """The due days ``text`` names: its working days (:func:`working_days_named`) and days of the month
    (:func:`days_of_month_named`, with ``rule`` and ``first`` those it states for that reading: a schedule of
    dates, the middle of each quarter)."""
    return {("working_day", day) for day in working_days_named(text)} | {
        ("day_of_month", day) for day in days_of_month_named(text, rule, first)
    }


def payment_days_stated(
    text: str, rule: Recurrence | None = None, first: date | None = None
) -> list[tuple[str, set[DueDay]]]:
    """The sentences of a page's ``text`` that state the day a recurring payment is due, each with the days
    it states: a sentence about paying a sum when it falls due ("zu zahlen", "zahlbar", "Abbuchung",
    "Lastschrift", "eingezogen", "fällig", "debit", "due" …, never a sum's name alone: "Beitrag", "Miete") that
    names a working day or a day of the month (:func:`due_days_named`: "Abbuchung zum Monatsanfang", "jeweils
    zum 15.", "zur Monatsmitte", "am 3. Werktag eines jeden Monats") — not a date with a month name ("am 1.
    Oktober") unless its dates state the day as a schedule of ``rule``, the payment's recurrence
    (:func:`schedule_days_named`: "Hauptfälligkeit 01.12. eines jeden Jahres" every year), or the middle of
    each quarter for that recurrence and ``first``, its first date as the letter writes it
    (:func:`mid_quarter_named`: "in der Mitte eines Dreimonatszeitraums" every 3 months from a 15th) — and no
    sentence about a notice period, a cancellation or an objection ("Die Kündigung muss bis zum 10. eines
    Monats eingehen")."""
    stated: list[tuple[str, set[DueDay]]] = []
    for sentence in _sentences(text):
        folded = fold_punctuation(sentence)
        if not _PAYMENT_WORDS.search(folded) or _NOT_A_PAYMENT.search(folded):
            continue
        read: set[DueDay] = {("day_of_month", day) for day in _rule_days_named(folded, rule, first)}
        days = due_days_named(_NAMED_DATE.sub(" ", folded)) | read
        if days:
            stated.append((sentence, days))
    return stated


def payment_day_sentence(
    texts: Sequence[str],
    due: DueDay,
    quote: str = "",
    rule: Recurrence | None = None,
    first: date | None = None,
) -> str | None:
    """The sentence of a letter (``texts``: its pages' text) stating ``due`` as the day a recurring payment is
    due, when that is the only such day the letter states (:func:`payment_days_stated`, read for ``rule``, the
    payment's recurrence, and ``first``, its first date as the letter writes it) and ``quote`` (the to-do's own
    sentence) names no other; else ``None`` — no such day, another one, or two different ones."""
    if due_days_named(quote, rule, first) - {due}:
        return None
    stated = [found for text in texts for found in payment_days_stated(text, rule, first)]
    if not stated or set().union(*(days for _, days in stated)) != {due}:
        return None
    return stated[0][0]


# --------------------------------------------------------------------------------------------------
# Spec consistency
# --------------------------------------------------------------------------------------------------


def spec_consistency(quote: str, spec: DateSpec, amount: float | None) -> tuple[bool, list[str]]:
    """Whether a DateSpec (and an item amount) is stated by its quote — SPEC §21.

    * fixed: ``spec.date`` must be a date written in the quote (a date without year is flagged);
    * relative: amount + unit must be written in the quote (digits or number words; 2 weeks ≡ 14
      days, 1 year ≡ 12 months; ``Werktage`` is ``werktage``, not ``business_days``); an explicit
      anchor date must be written in the quote;
    * an item amount must appear in the quote;
    * ambiguous numeric dates (03/05/2026) are always flagged.

    Returns ``(ok, reasons)``; ``ok`` is ``True`` iff ``reasons`` is empty.
    """
    mentions = parse_dates(quote)
    reasons: list[str] = []
    if any(m.ambiguous for m in mentions):
        reasons.append(AMBIGUOUS_DATE)
    if spec.type == "fixed":
        reasons.extend(_fixed_reasons(spec, mentions))
    elif spec.type == "relative":
        reasons.extend(_relative_reasons(quote, spec, mentions))
    if amount is not None and not any(abs(value - amount) < 0.005 for value in parse_amounts(quote)):
        reasons.append(AMOUNT_NOT_IN_QUOTE)
    return not reasons, reasons


def _fixed_reasons(spec: DateSpec, mentions: list[DateMention]) -> list[str]:
    target = _iso_date(spec.date)
    if target is None:
        return [INCOMPLETE_SPEC]
    if any(m.as_date() == target for m in mentions):
        return []
    yearless = [m for m in mentions if m.year is None]
    reasons = [DATE_WITHOUT_YEAR] if yearless else []
    if not any((m.day, m.month) == (target.day, target.month) for m in yearless):
        reasons.append(DATE_NOT_IN_QUOTE)
    return reasons


def _relative_reasons(quote: str, spec: DateSpec, mentions: list[DateMention]) -> list[str]:
    if spec.amount is None or spec.unit is None:
        return [INCOMPLETE_SPEC]
    reasons: list[str] = []
    stated = {_canonical_period(n, u) for n, u in parse_periods(quote)}
    if _canonical_period(spec.amount, spec.unit) not in stated:
        reasons.append(PERIOD_NOT_IN_QUOTE)
    if spec.anchor == "explicit_date":
        anchor = _iso_date(spec.anchor_date)
        if anchor is None or not any(m.as_date() == anchor for m in mentions):
            reasons.append(DATE_NOT_IN_QUOTE)
    return reasons


def working_day_consistency(quote: str, working_day: int | None) -> list[str]:
    """Whether a recurrence's working day (``Recurrence.working_day``, "spätestens am dritten Werktag eines
    jeden Monats" is 3) is stated by its item's quote: ``[WORKING_DAY_NOT_IN_QUOTE]`` unless the quote names
    that ordinal (:func:`working_days_named`); ``[]`` for a recurrence without one. Only the quote counts
    here: the working day is the reading's claim about that sentence (the letter's one sentence stating
    when the payment is due can still vouch for it: :func:`payment_day_sentence`)."""
    if working_day is None or working_day in working_days_named(quote):
        return []
    return [WORKING_DAY_NOT_IN_QUOTE]


def day_of_month_consistency(
    quote: str, day: int | None, rule: Recurrence | None = None, first: date | None = None
) -> list[str]:
    """Whether a recurrence's day of the month (``Recurrence.day_of_month``, "zum 1. eines Monats" is 1) is
    stated by its item's quote: ``[DAY_OF_MONTH_NOT_IN_QUOTE]`` unless the quote names that day
    (:func:`days_of_month_named`), in words ("zur Monatsmitte" is 15) or — for ``rule``, the recurrence — as a
    schedule of dates ("fällig jeweils am 10.03., 10.06., 10.09. und 10.12." every 3 months, "31.03., 30.06.,
    30.09. und 31.12." the 31st: :func:`schedule_days_named`; never a single start date, "ab dem 01.11.2026"),
    or as the middle of each quarter for a reading every 3 months whose first date ``first`` — one its letter
    writes — is that middle (:func:`mid_quarter_named`); ``[]`` for a recurrence without one. Only the quote
    counts, as for a working day (:func:`working_day_consistency`)."""
    if day is None or day in days_of_month_named(quote, rule, first):
        return []
    return [DAY_OF_MONTH_NOT_IN_QUOTE]


def _canonical_period(amount: int, unit: PeriodUnit) -> tuple[int, PeriodUnit]:
    """Equal periods in one form: weeks → days (§ 188 Abs. 2 BGB ends both on the same weekday),
    years → months."""
    if unit == "weeks":
        return amount * 7, "days"
    if unit == "years":
        return amount * 12, "months"
    return amount, unit


def _iso_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------------
# How well a date was read (§ 21 confidence rubric)
# --------------------------------------------------------------------------------------------------

REASON_TEXT: dict[str, str] = {
    AMBIGUOUS_DATE: "The date in the letter can be read two ways (day/month) — please check it.",
    DATE_WITHOUT_YEAR: "The letter gives this date without a year — please check the year.",
    DATE_NOT_IN_QUOTE: "This date doesn't appear in the sentence it was taken from — please check it.",
    PERIOD_NOT_IN_QUOTE: "The period (e.g. “one month”) doesn't appear in the sentence it was taken from — please check it.",
    AMOUNT_NOT_IN_QUOTE: "The amount doesn't appear in the sentence it was taken from — please check it.",
    INCOMPLETE_SPEC: "Part of the date description is missing — please check it.",
    WORKING_DAY_NOT_IN_QUOTE: "The working day (e.g. “the 3rd working day”) doesn't appear in the sentence it was taken from — please check it.",
    DAY_OF_MONTH_NOT_IN_QUOTE: "The day of the month (e.g. “on the 1st of each month”) doesn't appear in the sentence it was taken from — please check it.",
}
UNVERIFIED_NOTE = "We couldn't find this sentence in the letter — please check the date against the letter."
MODEL_READ_NOTE = "This was read by AI from a photo or scan — compare the date with the paper letter."
_GROUNDING_NOTES: dict[Grounding, str] = {"unverified": UNVERIFIED_NOTE, "model_read": MODEL_READ_NOTE}
_NOTED_REASONS = {text: reason for reason, text in REASON_TEXT.items()}
_FAILURES: dict[Confidence, int] = {"high": 0, "medium": 1, "low": 2}


def grade_reading(
    receipt: ComputationReceipt, grounding: Grounding, reasons: Sequence[str]
) -> ComputationReceipt:
    """Apply the § 21 confidence rubric's reading conditions on top of the engine's own grade.

    Each failed condition (quote not located in the page text, quote not stating the DateSpec, the
    amount, the working day or the day of the month: any ``reasons``) lowers the confidence one level; an ambiguous numeric
    date makes it ``low``. Reasons are added to the receipt's warnings (:data:`REASON_TEXT`).
    """
    failures = _FAILURES[receipt.confidence]
    notes: list[str] = []
    if grounding in _GROUNDING_NOTES:
        failures += 1
        notes.append(_GROUNDING_NOTES[grounding])
    if reasons:
        failures += 1
        notes.extend(REASON_TEXT.get(reason, reason) for reason in reasons)
    if AMBIGUOUS_DATE in reasons:
        failures = max(failures, 2)
    confidence: Confidence = "high" if failures == 0 else "medium" if failures == 1 else "low"
    return receipt.model_copy(update={"confidence": confidence, "warnings": [*receipt.warnings, *notes]})


def regrade(receipt: ComputationReceipt, graded: ComputationReceipt | None) -> ComputationReceipt:
    """``receipt`` graded by the reading ``graded`` was graded by, as the notes :func:`grade_reading`
    added to it say: the next occurrence of a schedule is read from the same sentence. Nothing else
    of ``graded`` carries over (not the confidence or warnings its own date had)."""
    notes = graded.warnings if graded is not None else []
    grounding: Grounding = next(
        (found for found, note in _GROUNDING_NOTES.items() if note in notes), "verified"
    )
    reasons = [_NOTED_REASONS[note] for note in notes if note in _NOTED_REASONS]
    return grade_reading(receipt, grounding, reasons)
