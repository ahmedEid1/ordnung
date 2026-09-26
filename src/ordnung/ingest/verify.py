"""Verification (SPEC §8 stage 5, §21): ground quotes on pages and check values against quotes.

* :func:`locate_quote` finds a model quote on the page texts — fuzzy (``partial_ratio`` ≥ 90 over
  normalised text) **and** exact for digits (every digit group of the quote must appear verbatim in
  the matched passage) — and maps the match back to highlight boxes on the page image.
* :func:`ground_evidence` turns that into :class:`~ordnung.models.Evidence` with a grounding level.
* :func:`spec_consistency` checks that a :class:`~ordnung.models.DateSpec` and an amount are
  actually stated by their quote (numbers, number words, units, explicit dates).
* :func:`grade_reading` applies the § 21 confidence rubric's reading conditions to a date's receipt,
  and :func:`regrade` the same reading to the receipt of a schedule's next occurrence.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from rapidfuzz import fuzz

from ordnung.ingest.normalize import digit_tokens, fold_punctuation, normalise_with_map
from ordnung.ingest.text import PageText, Word
from ordnung.models import (
    Box,
    ComputationReceipt,
    Confidence,
    DateSpec,
    Evidence,
    Grounding,
    Page,
    PeriodUnit,
)

MIN_SCORE = 90.0

# Reasons returned by spec_consistency (stable codes; the UI maps them to plain language).
AMBIGUOUS_DATE = "ambiguous_date"
DATE_WITHOUT_YEAR = "date_without_year"
DATE_NOT_IN_QUOTE = "date_not_in_quote"
PERIOD_NOT_IN_QUOTE = "period_not_in_quote"
AMOUNT_NOT_IN_QUOTE = "amount_not_in_quote"
INCOMPLETE_SPEC = "incomplete_spec"

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
    located, best = _search(quote, pages)
    if located is None:
        return Evidence(doc_id=doc_id, quote=quote, grounding="unverified", score=best)
    grounding = _GROUNDING.get(located.source, "unverified")
    return Evidence(
        doc_id=doc_id,
        page=located.page,
        quote=quote,
        grounding=grounding,
        score=located.score,
        boxes=located.boxes if grounding == "verified" else [],
    )


def _search(quote: str, pages: Sequence[PageInput]) -> tuple[Located | None, float]:
    """The located quote (or ``None``) and the best fuzzy score seen on any page."""
    norm_quote, _ = normalise_with_map(quote)
    if not norm_quote:
        return None, 0.0
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
    for score, page, norm, offsets, alignment in sorted(candidates, key=lambda c: -c[0]):
        if score < MIN_SCORE:
            break
        if _digits_present(quote_digits, norm, alignment.dest_start, alignment.dest_end):
            start, end = offsets[alignment.dest_start], offsets[alignment.dest_end - 1] + 1
            located = Located(page.number, round(score, 1), start, end, _boxes(page, start, end), page.source)
            return located, best
    return None, best


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
    try:
        return float(digits)
    except ValueError:  # defensive: the checks above only pass digits and one decimal point
        return None


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

    Each failed condition (quote not located in the page text, quote not stating the DateSpec)
    lowers the confidence one level; an ambiguous numeric date makes it ``low``. Reasons are added
    to the receipt's warnings.
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
