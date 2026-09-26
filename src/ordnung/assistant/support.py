"""Claim-level support: which parts of an Ask answer may stay (ADR 0007, ADR 0008).

Ask's tools answer in two channels (:mod:`ordnung.assistant.channels`): Ordnung's *record* (what
code computed, the person confirmed or the pipeline filed with verified evidence) and the *letter
text* (every word that comes from a letter). An answer is checked sentence by sentence against the
record of the records it cites, with this written policy:

1. **What is read.** Each sentence as the person will see it: citation markers, Markdown emphasis,
   code and link syntax, backslash escapes and invisible format characters are dropped and
   typographic punctuation is folded before reading, so ``31.**12**.2027`` reads as 31.12.2027. A
   sentence ends at ``.``, ``!`` or ``?`` followed by a capital letter (after optional quotes, markup
   or citation markers), never after a one-letter or listed abbreviation (:data:`ABBREVIATION`:
   ``z. B.``, ``vgl.``, ``Nr.``, ``Wed.``, ``p.``); every line is split on its own. A sentence *states*
   a date when :func:`~ordnung.ingest.verify.parse_dates` finds one (plus ``31-12-2027`` and
   ``2027/12/31``) or a digit group shaped like a date that does not parse (it can never be
   supported); it states an amount when :func:`~ordnung.ingest.verify.amount_matches` finds a number
   next to a currency, or a bare number with two decimals that is neither a clock time (``10.30
   Uhr``, ``um 9.15``, ``8.00–12.00``) nor a label number (``Raum 2.14``, ``Nr. 2.14``, ``Version
   1.25``). A sentence that starts like Ordnung's own note (:data:`NOTE_PREFIX`) is dropped: only the
   check writes that note.
2. **Cited records.** The records the sentence cites. A sentence that cites none takes those of the
   nearest sentence before it on its line that cites some, else of the nearest one after it (a
   trailing citation covers its line); a list item that cites none takes those of the line ending in
   ``:`` that leads the list.
3. **Supported.** A value is supported when it is in the record part of a cited record — a record that
   appeared in a record part of this turn's tool results. A record's part includes the records listed
   inside it or linked to it: a letter's to-dos and contracts, a contract's letter, a person's to-dos
   (``doc_id``, ``contract_id``, ``party_id``, ``source_doc_id``). Dates without a year match by day
   and month. Today's date and the overview totals Ordnung's code adds up outside any one record
   (``money_summary``) need no citation.
4. **Quoted.** Any other value may stay only in quotation marks (“…”, or „…“ in a German answer):
   (a) when the letter text of a cited record holds it and the same clause of the sentence names a
   letter as its source (:data:`LETTER_QUOTE`: "the letter says …", "laut dem Schreiben …", "… per
   the letter"). A letter's text belongs to the to-dos and contracts filed from it too. When the
   answer states none of the quoted records' own dates (a to-do's due date, a contract's cancel-by
   date) or amounts, the note under the answer gives them ("Ordnung's record for what is quoted:
   deadline Wed 21 Oct 2026"), so a letter's date never stands alone; (b) when it is the flagged,
   unverified amount of a cited to-do or
   contract (``amount_unverified``, ``terms_unverified``), so a real payment stays in a list; (c) when
   the person wrote it in this conversation and the sentence cites no record: it is their words,
   never Ordnung's. A note under the answer says that quoted values are not confirmed.
5. **Left out.** Every other value is left out. In a sentence that keeps a supported or quoted value
   it is replaced by "[date left out]" or "[amount left out]", so a record's value is never lost
   because of another value next to it; a sentence with nothing to keep is removed. A § that is
   neither in the rules catalog nor in a record part is shown in quotation marks as a letter's words
   when the letter text of a record the sentence cites names it — or, in a sentence that cites
   nothing but names a letter as its source, when a letter read in this turn names it; any other
   such § removes its sentence. The note says how many values and
   sentences were left out, and why. When nothing is left, Ask answers with a fixed fallback.

The check is deterministic and linear in the size of the answer and the tool results: each sentence
is read once and each value is looked up in hash sets of the cited records.

Known limits — documented, not bugs:

- Support is literal, not semantic: a value in a cited record supports a sentence that says
  something else about it ("you owe the library 640.00 € [item:rent]" passes when the rent to-do
  holds 640.00 €). A letter can therefore still steer *which* record the model cites.
- Dates in words ("next Friday", "end of the month") and claims without a date or amount ("there
  is no deadline") are not read; the prompt and the record are the only defence there. A sentence
  whose value was left out keeps its words ("the deadline moved to [date left out]"); the
  placeholder and the note show it, and Ordnung's own date stays wherever it is cited.
- A quote is recognised only by the listed phrases; other wording is treated as Ordnung's own claim.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from ordnung.assistant.channels import parse_tool_result
from ordnung.assistant.citations import marker_spans, parse_citations
from ordnung.ingest.normalize import fold_punctuation
from ordnung.ingest.verify import DateMention, amount_matches, parse_dates
from ordnung.secretary.review import paragraph_spans, paragraphs_in

CITABLE_ID = re.compile(r"(?:doc|itm|ctr|pty)_[a-z0-9]+")
LINK_KEYS = ("doc_id", "contract_id", "party_id", "source_doc_id")
AMOUNT_KEYS = frozenset({"amount", "monthly", "monthly_cost", "due_this_month", "fixed_costs_monthly"})
"""Numeric fields that are money (other numbers — pages, months, counts — never support an amount)."""
AMOUNT_MAPS = frozenset({"fixed_costs_by_category", "fixed_costs_monthly_other_currencies"})
"""Fields whose values are all money (``{"rent": 640.0, …}``)."""
CONTEXT_KEYS = frozenset({"today", *AMOUNT_MAPS, "due_this_month", "fixed_costs_monthly"})
"""Top-level record fields that belong to no one record: overview values Ordnung's code worked out."""
UNVERIFIED_FLAGS = ("amount_unverified", "terms_unverified")
"""Record flags saying a record's amounts are only in its letter text (policy rule 4b)."""
RECORD_LABELS: Mapping[str, tuple[str, str]] = {
    "deadline": ("deadline", "Frist"),
    "payment": ("payment due", "Zahlung fällig"),
    "appointment": ("appointment", "Termin"),
    "expiry": ("expires", "läuft ab"),
    "cancel_by": ("cancel by", "kündigen bis"),
    "amount": ("amount", "Betrag"),
    "cost": ("cost", "Kosten"),
}
"""How the note names a record's own date or amount (English, German); other to-do kinds are "due"."""
MAX_RECORD_VALUES = 3
"""The note gives the quoted records' own values only when there are at most this many of a kind."""

NOTE_PREFIX = "Checked by Ordnung:"

_LETTER_WORDS = (
    r"letter|notice|document|reminder|invoice|bill|statement|card|contract|page|text|sender|e-?mail|"
    r"assessment|decision|form"
)
_SAYS = (
    r"says|say|said|states|stated|claims|claimed|writes|wrote|mentions|mentioned|asks|asked|demands|"
    r"demanded|reads|lists|listed|gives|gave|names|named|asserts|asserted|announces|announced|notes|"
    r"noted|explains|explained|warns|warned|adds|added|cites|cited|puts\s+it"
)
_DE_LETTER = r"Brief|Schreiben|Bescheid|Dokument|Rechnung|Mahnung|Absender|Text|Vertrag|Karte"
_SENDER_SPAN = "{1,60}"  # "the letter from <up to 60 characters> says"; bounded, so matching stays linear
LETTER_QUOTE = re.compile(
    rf"""
      \b(?:the|this|that|your|its|their)\s+(?:[\w-]+(?:\s+[\w-]+)?'s\s+)?(?:{_LETTER_WORDS})(?:'s\s+(?:page\s+)?text)?(?:\s+itself)?
        (?:\s+(?:from|of)\s+[^.;:!?\n]{_SENDER_SPAN}?)?\s+(?:also\s+)?(?:{_SAYS})\b
    | \baccording\s+to\s+(?:the|this|that|your)\s+(?:[\w-]+(?:\s+[\w-]+)?'s\s+)?(?:{_LETTER_WORDS})\b
    | \b(?:it|this)\s+says\s+in\s+the\s+(?:{_LETTER_WORDS})\b
    | \b(?:per|as\s+in)\s+(?:the|this|that|your)\s+(?:[\w-]+(?:\s+[\w-]+)?'s\s+)?(?:{_LETTER_WORDS})\b
    | \b(?:letter|notice)(?:'s)?\s+text\s*:
    | \bas\s+(?:the|this)\s+(?:{_LETTER_WORDS})\s+(?:says|states|puts\s+it)\b
    | \b(?:the\s+)?(?:letter|notice)'s\s+(?:own\s+)?(?:words|wording)\b
    | \b(?:laut|gemäß|gemaess)\s+(?:dem\s+|des\s+|diesem\s+|diesen\s+|ihrem\s+|ihres\s+)?(?:{_DE_LETTER})s?\b
    | \b(?:im|in\s+dem|in\s+diesem)\s+(?:{_DE_LETTER})\s+(?:steht|heißt\s+es|wird\s+behauptet)\b
    | \b(?:der|das|die|dieser|dieses|diese)\s+(?:{_DE_LETTER})\s+(?:sagt|schreibt|behauptet|nennt|gibt\s+an|
        verlangt|fordert|erwähnt)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
"""The phrases that name a letter as a value's source (policy rule 4a). When in doubt, it is not."""
CLAUSE_BREAK = re.compile(
    r";|\s-+\s|,\s*(?:so|therefore|thus|hence|but|however|yet|which\s+means|meaning|aber|jedoch|daher|"
    r"deshalb|somit|also)\b",
    re.IGNORECASE,
)
"""What ends a clause for rule 4a (read on folded text, where dashes are ``-``): a letter named in
one clause is not the source of a value in the next ("the letter says nothing else, so …")."""

ABBREVIATION = re.compile(
    r"(?:\b\d{1,2}|\b[^\W\d_]|[Ss]tr|\b(?:Abs|Nr|Nrn|Art|Kap|Anm|Tel|Dr|Prof|Hr|Hrn|St|Mr|Mrs|Ms|Rm|Zi|"
    r"(?i:ca|bzw|ggf|vgl|evtl|inkl|zzgl|bspw|sog|ff|approx|incl|excl|vs)|Mon|Tue|Tues|Wed|Thu|Thur|Thurs|Fri|"
    r"Sat|Sun|Mo|Di|Mi|Do|Fr|Sa|So))\.$"
)
"""Words after whose full stop a sentence never ends: one letter (``z. B.``, ``p.``, ``e.g.``), German
ordinal days (``21. Oktober``), and listed abbreviations of German and English answers."""

Verdict = Literal["kept", "quoted", "redacted", "removed"]
ValueKind = Literal["date", "amount", "unreadable"]
QuoteSource = Literal["letter", "person"]

_SENTENCE_END = re.compile(
    r"[.!?]+(?P<close>[\"'”“’»)\]*_]*)(?P<cites>(?:[ \t]*\[[^\[\]\n]{1,300}\])*)(?P<gap>[ \t]+)"
)
_OPENERS = "\"'“„‘«(*_["
_LINE_PREFIX = re.compile(r"^(\s*(?:[-*+•]\s+|#{1,6}\s+|>\s*)?)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+•]\s+|\d{1,4}[.)]\s+)")
_LINK = re.compile(r"!?\[([^\]\n]*)\]\(\s*[^)\s]*(?:\s+\"[^\"\n]*\")?\s*\)")
_ESCAPABLE = frozenset("\\`*_[]()#+-.!>~|{}")
_MARKUP = frozenset("*_`")
_NUMBER_CHAR = re.compile(r"[\d.,]")
_CURRENCY_AFTER = re.compile(r"(?:\s?(?:€|EUR\b|Euro\b|euros?\b))", re.IGNORECASE)
_CURRENCY_BEFORE = re.compile(r"(?:€|EUR|Euro)\s?$", re.IGNORECASE)
_WEEKDAY_BEFORE = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun|"
    r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|Mo|Di|Mi|Do|Fr|Sa|So)\.?,?\s$"
)
_EXTRA_DATES = re.compile(
    r"(?<![\w.,/-])(?:(?P<d>\d{1,2})-(?P<m>\d{1,2})-(?P<y>\d{4})|(?P<iy>\d{4})[/.](?P<im>\d{1,2})[/.](?P<id>\d{1,2}))"
    r"(?![\w/-]|[.,]\d)"
)
_DATE_LIKE = re.compile(r"(?<![\w.,/-])\d{1,4}[./-]\d{1,2}[./-]\d{2,4}(?![\w/-]|[.,]\d)")
_CLOCK = re.compile(r"(?P<h>\d{1,2})[.,](?P<m>\d{2})")
_TIME_AFTER = re.compile(r"\s*(?:Uhr\b|h\b|hrs?\b|o'clock\b|a\.?\s?m\b\.?|p\.?\s?m\b\.?)", re.IGNORECASE)
_TIME_BEFORE = re.compile(r"\b(?:um|ab|gegen|von|bis|at|from|until|till|between|zwischen)\s+$", re.IGNORECASE)
_TIME_RANGE_AFTER = re.compile(r"\s*(?:-|bis|to)\s*(?P<h>\d{1,2})[.:,](?P<m>\d{2})(?![.,]?\d)", re.IGNORECASE)
_TIME_RANGE_BEFORE = re.compile(r"(?<!\d)(?P<h>\d{1,2})[.:,](?P<m>\d{2})\s*(?:-|bis|to)\s*$", re.IGNORECASE)
_LABEL_BEFORE = re.compile(
    r"(?:\b(?:Raum|Room|Zimmer|Zi|Rm|Nr|No|Nummer|Number|Version|Ver|v|Art|Abs|Kap|Kapitel|Chapter|"
    r"Section|Abschnitt|Seite|Page|pp?|S|Gleis|Platform|Tel|Etage|Floor|Stock|Haus|Building|Geb|Tür|"
    r"Door|Schalter|Counter|Desk|Platz|Seat)\.?|§)\s*$",
    re.IGNORECASE,
)
_LAW_TAIL = re.compile(r"(?:\(\d+[a-z]?\))*(?:\s+[A-ZÄÖÜ][A-Za-zÄÖÜäöü]*[A-Z](?:\s+[IVX]{1,4}\b)?)?")
_FORGED_NOTE = re.compile(r"^[\s>#*\-+•\d.)\"'(\[]*checked\s+by\s+ordnung\b", re.IGNORECASE)

# fmt: off
_DE_WORDS = frozenset({
    "der", "die", "das", "und", "ist", "nicht", "sie", "ihre", "ihr", "ihren", "ihrem", "bis", "zum", "zur",
    "den", "dem", "ein", "eine", "einen", "mit", "für", "auf", "wird", "werden", "bitte", "muss", "müssen",
    "haben", "laut", "frist", "betrag",
})
_EN_WORDS = frozenset({
    "the", "and", "is", "not", "you", "your", "by", "to", "of", "an", "with", "for", "on", "will", "be",
    "please", "must", "have", "has", "deadline", "amount",
})
# fmt: on
_WORD = re.compile(r"[^\W\d_]+")


# --------------------------------------------------------------------------------------------------
# reading a sentence as it is shown
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    """A sentence as the person sees it (policy rule 1); ``offsets[i]`` is the index in the sentence of
    the character ``text[i]`` came from."""

    text: str
    offsets: tuple[int, ...]

    def source_span(self, start: int, end: int) -> tuple[int, int]:
        """The span in the sentence of ``text[start:end]`` (markup inside it included)."""
        return self.offsets[start], self.offsets[end - 1] + 1


def read_as_shown(source: str) -> Reading:
    """``source`` without citation markers, Markdown markup and invisible characters, punctuation folded."""
    skip = bytearray(len(source))
    for start, end in marker_spans(source):
        skip[start:end] = b"\x01" * (end - start)
    for match in _LINK.finditer(source):
        if any(skip[match.start() : match.end()]):
            continue
        text_start, text_end = match.span(1)  # a link shows its text, an image its description
        skip[match.start() : text_start] = b"\x01" * (text_start - match.start())
        skip[text_end : match.end()] = b"\x01" * (match.end() - text_end)
    chars: list[str] = []
    offsets: list[int] = []
    index = 0
    while index < len(source):
        char = source[index]
        if skip[index]:
            index += 1
            continue
        if char == "\\" and index + 1 < len(source) and source[index + 1] in _ESCAPABLE:
            index += 1  # an escaped character is shown as itself
            char = source[index]
        elif char in _MARKUP or unicodedata.category(char) == "Cf":
            index += 1
            continue
        for folded in fold_punctuation(char):
            chars.append(folded)
            offsets.append(index)
        index += 1
    return Reading("".join(chars), tuple(offsets))


# --------------------------------------------------------------------------------------------------
# facts
# --------------------------------------------------------------------------------------------------


@dataclass
class FactSet:
    """Dates (full, and by day and month), amounts (in cents) and § citations of a record, a letter
    or the context."""

    dates: set[date] = field(default_factory=set)
    day_months: set[tuple[int, int]] = field(default_factory=set)
    cents: set[int] = field(default_factory=set)
    laws: set[tuple[str, str | None]] = field(default_factory=set)

    def add_text(self, text: str) -> None:
        """Every date and amount written in ``text``."""
        for mention in dates_in(text):
            self.day_months.add((mention.day, mention.month))
            if (full := mention.as_date()) is not None:
                self.dates.add(full)
        for match in amount_matches(text):
            self.add_amount(match.value)

    def add_amount(self, value: float) -> None:
        self.cents.add(round(value * 100))

    def add_date(self, value: date) -> None:
        self.dates.add(value)
        self.day_months.add((value.day, value.month))

    def has_date(self, mention: DateMention) -> bool:
        full = mention.as_date()
        return full in self.dates if full is not None else (mention.day, mention.month) in self.day_months

    def has_amount(self, value: float) -> bool:
        return round(value * 100) in self.cents

    def has_law(self, number: str, law: str | None) -> bool:
        """A § citation (a bare number: any law with it)."""
        if law is not None:
            return (number, law) in self.laws
        return any(known == number for known, _ in self.laws)

    def merge(self, other: FactSet) -> None:
        self.dates |= other.dates
        self.day_months |= other.day_months
        self.cents |= other.cents
        self.laws |= other.laws


_EMPTY = FactSet()


def dates_in(text: str) -> list[DateMention]:
    """:func:`~ordnung.ingest.verify.parse_dates` plus ``31-12-2027`` and ``2027/12/31``."""
    mentions = parse_dates(text)
    for match in _EXTRA_DATES.finditer(fold_punctuation(text)):
        mentions.extend(_extra_reading(match))
    return mentions


def _extra_reading(match: re.Match[str]) -> list[DateMention]:
    if match.group("d"):
        day, month, year = int(match.group("d")), int(match.group("m")), int(match.group("y"))
    else:
        day, month, year = int(match.group("id")), int(match.group("im")), int(match.group("iy"))
    try:
        date(year, month, day)
    except ValueError:
        return []
    return [DateMention(match.group(), day, month, year)]


@dataclass(frozen=True)
class Value:
    """A date or amount a sentence states: its text as read, where it stands in the reading, and its
    readings (``unreadable``: shaped like a date but not one — never supported)."""

    text: str
    kind: ValueKind
    start: int
    end: int
    dates: tuple[DateMention, ...] = ()
    amount: float | None = None

    def found_in(self, facts: FactSet) -> bool:
        if self.kind == "amount" and self.amount is not None:
            return facts.has_amount(self.amount)
        return any(facts.has_date(reading) for reading in self.dates)  # a slash date may read two ways


def stated_values(plain: str) -> list[Value]:
    """The dates and amounts a sentence states, in reading order (``plain``: the sentence as read)."""
    values = _date_values(plain)
    taken = [(value.start, value.end) for value in values]
    for match in _EXTRA_DATES.finditer(plain):
        if not _overlaps(match.span(), taken):
            readings = tuple(_extra_reading(match))
            kind: ValueKind = "date" if readings else "unreadable"
            values.append(Value(match.group(), kind, *match.span(), dates=readings))
            taken.append(match.span())
    for match in _DATE_LIKE.finditer(plain):
        if not _overlaps(match.span(), taken):
            values.append(Value(match.group(), "unreadable", *match.span()))
            taken.append(match.span())
    for amount in amount_matches(plain):
        span = (amount.start, amount.end)
        if _overlaps(span, taken) or not (amount.has_currency or _is_money(plain, *span)):
            continue
        values.append(Value(amount.number, "amount", *span, amount=amount.value))
    return sorted(values, key=lambda value: value.start)


def _date_values(plain: str) -> list[Value]:
    """:func:`~ordnung.ingest.verify.parse_dates` with where each date stands (a slash date may have
    two readings, which stay one value)."""
    groups: list[list[DateMention]] = []
    for mention in parse_dates(plain):
        last = groups[-1][-1] if groups else None
        if (
            last is not None
            and mention.ambiguous
            and last.text == mention.text
            and (last.day, last.month) == (mention.month, mention.day)
        ):
            groups[-1].append(mention)
        else:
            groups.append([mention])
    values: list[Value] = []
    cursor = 0
    for group in groups:
        raw = group[0].text
        start = plain.find(raw, cursor)
        if start < 0:
            start = plain.find(raw)
        if start < 0:  # a rewritten form (a bilingual month): stated, but it cannot be marked in place
            values.append(Value(raw, "date", -1, -1, dates=tuple(group)))
            continue
        cursor = start + len(raw)
        values.append(Value(raw, "date", start, start + len(raw), dates=tuple(group)))
    return values


def _overlaps(span: tuple[int, int], taken: Iterable[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in taken)


def _is_money(plain: str, start: int, end: int) -> bool:
    """A bare two-decimal number is money unless it is a clock time or a label number (rule 1)."""
    before, after = plain[max(0, start - 24) : start], plain[end : end + 24]
    if _LABEL_BEFORE.search(before):
        return False
    if not _is_clock(_CLOCK.fullmatch(plain, start, end)):
        return True
    return not (
        _TIME_AFTER.match(after)
        or _TIME_BEFORE.search(before)
        or _is_clock(_TIME_RANGE_AFTER.match(after))
        or _is_clock(_TIME_RANGE_BEFORE.search(before))
    )


def _is_clock(match: re.Match[str] | None) -> bool:
    return match is not None and int(match.group("h")) <= 24 and int(match.group("m")) <= 59


# --------------------------------------------------------------------------------------------------
# what this turn's tool results establish
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordValue:
    """A record's own date (a to-do's due date, a contract's cancel-by date) or amount, which the
    note gives for quoted records (rule 4a); ``label`` says what it is (a key of :data:`RECORD_LABELS`)."""

    kind: Literal["date", "amount"]
    label: str
    day: date | None = None
    cents: int = 0
    currency: str = "EUR"


@dataclass(frozen=True)
class TurnEvidence:
    """What the tool results of one Ask turn establish, by record id.

    ``record``: the dates and amounts of each record's record part (and of the records inside it or
    linked to it); ``letters``: those of its letter text (and of the records crediting it), with the §
    citations the letter names; ``unverified``: the amounts of records whose record flags them as
    unverified (they sit in the letter text); ``own``: each record's own deadlines and amounts;
    ``context``: values that need no citation; ``person``: values the person wrote; ``seen_ids``:
    every citable id in a record part; ``paragraphs``: the § citations of the rules catalog and the
    record parts.
    """

    record: Mapping[str, FactSet]
    letters: Mapping[str, FactSet]
    unverified: Mapping[str, FactSet]
    own: Mapping[str, frozenset[RecordValue]]
    context: FactSet
    person: FactSet
    seen_ids: frozenset[str]
    paragraphs: frozenset[tuple[str, str | None]]

    @classmethod
    def from_results(
        cls,
        results: Iterable[str],
        *,
        today: date,
        person: Iterable[str] = (),
        catalog: Iterable[str] = (),
    ) -> TurnEvidence:
        """Read the turn's rendered tool results; ``person`` are the person's own questions."""
        collector = _Collector()
        collector.context.add_date(today)
        words = FactSet()
        for text in person:
            words.add_text(text)
        for text in catalog:
            collector.paragraphs.update(paragraphs_in(text))
        letter_fields: list[tuple[str, Any]] = []
        for text in results:
            parsed = parse_tool_result(text)
            if parsed.record is not None:
                collector.walk(parsed.record)
            letter_fields += [(key, value) for key, value in parsed.letters.items() if isinstance(key, str)]
        letters: dict[str, FactSet] = defaultdict(FactSet)
        unverified: dict[str, FactSet] = defaultdict(FactSet)
        for record_id, fields in letter_fields:
            bag = FactSet()
            _collect_letter(fields, bag, money=False, key=None)
            owed = FactSet()
            if record_id in collector.flagged:
                _collect_letter(fields, owed, money=False, key=None, text=False)
            for owner in collector.credit.get(record_id, {record_id}):
                letters[owner].merge(bag)
                unverified[owner].merge(owed)
        return cls(
            record=dict(collector.record),
            letters=dict(letters),
            unverified=dict(unverified),
            own={key: frozenset(values) for key, values in collector.own.items()},
            context=collector.context,
            person=words,
            seen_ids=frozenset(collector.seen),
            paragraphs=frozenset(collector.paragraphs),
        )

    def supports(self, value: Value, cited: Collection[str]) -> bool:
        """Policy rule 3: in the context, or in the record part of a cited record."""
        return value.found_in(self.context) or any(
            value.found_in(self.record.get(ref_id, _EMPTY)) for ref_id in cited
        )

    def quotes(self, value: Value, cited: Collection[str]) -> bool:
        """Policy rule 4a (second half): in the letter text of a cited record."""
        return any(value.found_in(self.letters.get(ref_id, _EMPTY)) for ref_id in cited)

    def unverified_amount(self, value: Value, cited: Collection[str]) -> bool:
        """Policy rule 4b: the flagged, unverified amount of a cited record."""
        return value.kind == "amount" and any(
            value.found_in(self.unverified.get(ref_id, _EMPTY)) for ref_id in cited
        )

    def said_by_person(self, value: Value) -> bool:
        """Policy rule 4c (first half): the person wrote this value in the conversation."""
        return value.found_in(self.person)

    def knows_paragraph(self, number: str, law: str | None) -> bool:
        """A § citation from the catalog or a record part (a bare number: any law with it)."""
        if law is not None:
            return (number, law) in self.paragraphs
        return any(known == number for known, _ in self.paragraphs)

    def letter_names_paragraph(self, number: str, law: str | None, cited: Collection[str]) -> bool:
        """A § citation in the letter text of a cited record — or, with nothing cited, of any record."""
        pool = cited or self.letters
        return any(self.letters.get(ref_id, _EMPTY).has_law(number, law) for ref_id in pool)

    def own_values(self, cited: Collection[str], kind: str) -> list[RecordValue]:
        """The cited records' own dates (``kind="date"``) or amounts, in a stable order."""
        found = {value for ref_id in cited for value in self.own.get(ref_id, ()) if value.kind == kind}
        return sorted(found, key=lambda v: (v.day or date.min, v.cents, v.currency, v.label))


class _Collector:
    """Walks record parts: which record ids get credit for each value (itself, parents and links)."""

    def __init__(self) -> None:
        self.record: dict[str, FactSet] = defaultdict(FactSet)
        self.credit: dict[str, set[str]] = defaultdict(set)
        self.own: dict[str, set[RecordValue]] = defaultdict(set)
        self.flagged: set[str] = set()
        self.context = FactSet()
        self.seen: set[str] = set()
        self.paragraphs: set[tuple[str, str | None]] = set()

    def walk(self, node: Any) -> None:
        """Collect one record part (its top-level overview fields are the context)."""
        self._visit(node, frozenset(), key=None, money=False, context=False, top=True)

    def _visit(
        self,
        node: Any,
        owners: frozenset[str],
        *,
        key: str | None,
        money: bool,
        context: bool,
        top: bool = False,
    ) -> None:
        if isinstance(node, dict):
            here = owners | frozenset(_citable_ids(node))
            own = node.get("id")
            if isinstance(own, str) and CITABLE_ID.fullmatch(own):
                self.credit[own].update(here)
                for linked in here:  # and the linked records' letter text belongs to this one
                    self.credit[linked].update((linked, own))
                if any(node.get(flag) for flag in UNVERIFIED_FLAGS):
                    self.flagged.add(own)
            for value in _own_values(node, key):
                for owner in here:
                    self.own[owner].add(value)
            for child_key, value in node.items():
                self._visit(
                    value,
                    here,
                    key=child_key,
                    money=money or child_key in AMOUNT_MAPS,
                    context=context or (top and child_key in CONTEXT_KEYS),
                )
        elif isinstance(node, list):
            for value in node:
                self._visit(value, owners, key=key, money=money, context=context)
        else:
            self._scalar(node, owners, key=key, money=money, context=context)

    def _scalar(
        self, value: Any, owners: frozenset[str], *, key: str | None, money: bool, context: bool
    ) -> None:
        bags = [self.record[owner] for owner in owners] or ([self.context] if context else [])
        if isinstance(value, str):
            if CITABLE_ID.fullmatch(value):
                self.seen.add(value)
                return
            self.paragraphs.update(paragraphs_in(value))
            for bag in bags:
                bag.add_text(value)
        elif isinstance(value, int | float) and not isinstance(value, bool) and (money or key in AMOUNT_KEYS):
            for bag in bags:
                bag.add_amount(float(value))


def _own_values(node: Mapping[str, Any], key: str | None) -> Iterator[RecordValue]:
    """A record node's own date and amount: a to-do's due date (labelled by its kind) and verified
    amount, a contract's cancel-by date (in ``dates`` or ``computation``) and cost."""
    ref = node.get("id")
    if isinstance(ref, str) and ref.startswith("itm_") and (day := _iso_day(node.get("due_date"))):
        kind = str(node.get("kind") or "")
        yield RecordValue("date", kind if kind in RECORD_LABELS else "due", day=day)
    if (day := _iso_day(node.get("cancel_by"))) is not None:
        yield RecordValue("date", "cancel_by", day=day)
    amount = node.get("amount")
    if isinstance(amount, int | float) and not isinstance(amount, bool):
        label = "cost" if key == "cost" else "amount"
        currency = str(node.get("currency") or "EUR").upper()
        yield RecordValue("amount", label, cents=round(amount * 100), currency=currency)


def _iso_day(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _citable_ids(node: Mapping[str, Any]) -> Iterator[str]:
    """The record's own id and the records it links to."""
    for key in ("id", *LINK_KEYS):
        value = node.get(key)
        if isinstance(value, str) and CITABLE_ID.fullmatch(value):
            yield value


def _collect_letter(node: Any, bag: FactSet, *, money: bool, key: str | None, text: bool = True) -> None:
    """Dates, amounts and laws of letter text; ``text=False``: only the money fields (the filed amounts)."""
    if isinstance(node, dict):
        for child_key, value in node.items():
            _collect_letter(value, bag, money=money or child_key in AMOUNT_MAPS, key=child_key, text=text)
    elif isinstance(node, list):
        for value in node:
            _collect_letter(value, bag, money=money, key=key, text=text)
    elif isinstance(node, str):
        if text:
            bag.add_text(node)
            bag.laws.update(paragraphs_in(node))
    elif isinstance(node, int | float) and not isinstance(node, bool) and (money or key in AMOUNT_KEYS):
        bag.add_amount(float(node))


# --------------------------------------------------------------------------------------------------
# how the check writes (English or German answers)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Style:
    """Quotation marks, placeholders and formats for the words the check adds to an answer."""

    open_quote: str
    close_quote: str
    date_left_out: str
    amount_left_out: str
    record_label: str
    weekdays: tuple[str, ...]
    german: bool

    def date(self, day: date) -> str:
        weekday = self.weekdays[day.weekday()]
        return f"{weekday} {day:%d.%m.%Y}" if self.german else f"{weekday} {day.day} {day:%b %Y}"

    def amount(self, value: RecordValue) -> str:
        number = f"{value.cents / 100:,.2f}"
        if self.german:
            number = number.replace(",", " ").replace(".", ",").replace(" ", ".")
        return f"{number} €" if value.currency == "EUR" else f"{number} {value.currency}"

    def placeholder(self, kind: ValueKind) -> str:
        return self.amount_left_out if kind == "amount" else self.date_left_out

    def record_value(self, value: RecordValue) -> str:
        """``deadline Wed 21 Oct 2026`` / ``Frist Mi. 21.10.2026``."""
        english, german = RECORD_LABELS.get(value.label, ("due", "fällig"))
        shown = self.date(value.day) if value.day is not None else self.amount(value)
        return f"{german if self.german else english} {shown}"


ENGLISH = Style(
    "“", "”", "[date left out]", "[amount left out]", "Ordnung's record",
    ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), german=False,
)  # fmt: skip
GERMAN = Style(
    "„", "“", "[Datum weggelassen]", "[Betrag weggelassen]", "laut Ordnung",
    ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."), german=True,
)  # fmt: skip


def style_for(text: str) -> Style:
    """German when the answer has more common German than English words, else English."""
    german = english = 0
    for word in _WORD.findall(text):
        folded = word.casefold()
        german += folded in _DE_WORDS
        english += folded in _EN_WORDS
    return GERMAN if german > english else ENGLISH


# --------------------------------------------------------------------------------------------------
# checking an answer
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SentenceCheck:
    """The verdict on one sentence that states a date, an amount or a §.

    ``values``: what it states, as read; ``unsupported``: those not in the record part of a record it
    cites (quoted or left out); ``left_out``: those replaced by a placeholder, or every unsupported
    value of a removed sentence; ``reason``: why a sentence was removed (``value`` or ``law``);
    ``result``: the sentence as it stays in the answer (empty when removed).
    """

    text: str
    verdict: Verdict
    values: tuple[str, ...]
    unsupported: tuple[str, ...] = ()
    result: str = ""
    left_out: tuple[str, ...] = ()
    reason: Literal["value", "law"] | None = None
    quoted_from: tuple[QuoteSource, ...] = ()
    supported: tuple[Value, ...] = ()
    letter_quotes: tuple[tuple[ValueKind, frozenset[str]], ...] = ()


@dataclass(frozen=True)
class CheckedAnswer:
    """The answer after the check, and the verdict on every sentence that stated something checkable."""

    text: str
    sentences: tuple[SentenceCheck, ...]
    forged_notes: int = 0
    record_values: tuple[str, ...] = ()

    @property
    def removed(self) -> list[SentenceCheck]:
        return [check for check in self.sentences if check.verdict == "removed"]

    @property
    def redacted(self) -> list[SentenceCheck]:
        return [check for check in self.sentences if check.verdict == "redacted"]

    @property
    def quoted(self) -> list[SentenceCheck]:
        return [check for check in self.sentences if check.quoted_from]

    def note(self) -> str | None:
        """The visible note under the answer, with its prefix (``None`` when nothing was changed)."""
        parts = []
        by_value = sum(1 for check in self.removed if check.reason == "value")
        by_law = sum(1 for check in self.removed if check.reason == "law")
        left_out = sum(len(check.left_out) for check in self.redacted)
        if by_value == 1:
            parts.append("1 sentence was left out: its date or amount is not in the record it cites.")
        elif by_value:
            parts.append(
                f"{by_value} sentences were left out: their dates or amounts are not in the records they cite."
            )
        if left_out == 1:
            parts.append("1 date or amount is marked “left out”: it is not in the record its sentence cites.")
        elif left_out:
            parts.append(
                f"{left_out} dates or amounts are marked “left out”: they are not in the records their "
                "sentences cite."
            )
        if by_law == 1:
            parts.append(
                "1 sentence was left out: it names a law that is not in Ordnung's rules or in a letter it cites."
            )
        elif by_law:
            parts.append(
                f"{by_law} sentences were left out: they name laws that are not in Ordnung's rules or in a "
                "letter they cite."
            )
        sources = {source for check in self.quoted for source in check.quoted_from}
        if sources:
            origin = {
                frozenset({"letter"}): "quoted from a letter",
                frozenset({"person"}): "your own words",
            }.get(frozenset(sources), "quoted from a letter or your own words")
            parts.append(f"Values in quotation marks are {origin}; Ordnung has not confirmed them.")
        if self.record_values:
            parts.append(f"Ordnung's record for what is quoted: {'; '.join(self.record_values)}.")
        return f"{NOTE_PREFIX} {' '.join(parts)}" if parts else None


def check_answer(
    text: str, evidence: TurnEvidence, *, citable: Collection[str], style: Style | None = None
) -> CheckedAnswer:
    """Apply the policy of this module to ``text``; ``citable`` are the ids that may stay cited."""
    style = style or style_for(text)
    lines: list[str] = []
    checks: list[SentenceCheck] = []
    forged = 0
    lead: list[str] = []  # the records the line leading a list cites (rule 2)
    for line in text.splitlines():
        prefix = _LINE_PREFIX.match(line)
        start = prefix.group(1) if prefix else ""
        body = line[len(start) :]
        if not body.strip():
            lines.append(line)
            continue
        item = bool(_LIST_ITEM.match(line))
        sentences = sentences_of(body)
        own = [[c.id for c in parse_citations(sentence) if c.id in citable] for sentence in sentences]
        kept = []
        for sentence, cited in zip(sentences, _inherit(own, lead if item else []), strict=True):
            reading = read_as_shown(sentence)
            if _FORGED_NOTE.match(reading.text):
                forged += 1
                continue
            check = check_sentence(sentence, evidence, cited=cited, style=style, reading=reading)
            if check is None:
                kept.append(sentence)
                continue
            checks.append(check)
            if check.result:
                kept.append(check.result)
        if kept:
            lines.append(start + " ".join(kept))
        line_ids = list(dict.fromkeys(ref for ids in own for ref in ids))
        if read_as_shown(body).text.rstrip().endswith(":") and (line_ids or not item):
            lead = line_ids
        elif not item:
            lead = []
    return CheckedAnswer("\n".join(lines), tuple(checks), forged, _record_values(checks, evidence))


def _record_values(checks: Sequence[SentenceCheck], evidence: TurnEvidence) -> tuple[str, ...]:
    """Rule 4a: the own dates and amounts of the records a letter's quoted values cite, when the
    answer states none of them (at most :data:`MAX_RECORD_VALUES` of a kind), as the note words them."""
    shown: list[str] = []
    stated = [value for check in checks if check.result for value in check.supported]
    for kind in ("date", "amount"):
        cited = {
            ref for check in checks for quoted, refs in check.letter_quotes if quoted == kind for ref in refs
        }
        own = evidence.own_values(cited, kind)
        if own and len(own) <= MAX_RECORD_VALUES and not any(_states(v, r) for v in stated for r in own):
            shown += [ENGLISH.record_value(value) for value in own]
    return tuple(shown)


def _inherit(own: Sequence[list[str]], fallback: list[str]) -> list[list[str]]:
    """Rule 2 on one line: a sentence without citations takes the nearest earlier ones, else the
    nearest later ones, else ``fallback`` (the list's lead line)."""
    before: list[list[str]] = []
    last: list[str] = []
    for ids in own:
        last = ids or last
        before.append(last)
    after: list[list[str]] = [[] for _ in own]
    following: list[str] = []
    for index in range(len(own) - 1, -1, -1):
        following = own[index] or following
        after[index] = following
    return [own[i] or before[i] or after[i] or fallback for i in range(len(own))]


def sentences_of(body: str) -> list[str]:
    """Split one line into sentences (policy rule 1): at ``.``, ``!`` or ``?`` followed by a capital
    letter, with the citation markers after the full stop kept in the sentence they close."""
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(body):
        after = match.end()
        while after < len(body) and body[after] in _OPENERS and body[after] != "[":
            after += 1
        if after >= len(body) or not body[after].isupper():
            continue
        head = body[max(start, match.start() - 12) : match.start() + 1]  # abbreviations are short: linear
        if body[match.start()] == "." and ABBREVIATION.search(head):
            continue
        sentences.append(body[start : match.start("gap")].strip())
        start = match.end()
    sentences.append(body[start:].strip())
    return [sentence for sentence in sentences if sentence]


def check_sentence(
    sentence: str,
    evidence: TurnEvidence,
    *,
    cited: Collection[str],
    style: Style = ENGLISH,
    reading: Reading | None = None,
) -> SentenceCheck | None:
    """The verdict on one sentence (``None`` when it states no date, amount or §); ``cited`` are the
    citable records it cites or inherits (rule 2)."""
    reading = reading or read_as_shown(sentence)
    plain = reading.text
    values = stated_values(plain)
    laws = list(paragraph_spans(plain))
    if not values and not laws:
        return None
    stated = tuple(value.text for value in values)
    letter_laws: list[tuple[int, int]] = []
    for number, law, start, end in laws:
        if evidence.knows_paragraph(number, law):
            continue
        named = f"§ {number} {law or ''}".strip()
        framed = bool(cited) or bool(LETTER_QUOTE.search(plain))  # uncited: the letter must be named
        if not (framed and evidence.letter_names_paragraph(number, law, cited)):
            return SentenceCheck(sentence, "removed", stated, (named,), left_out=(named,), reason="law")
        letter_laws.append((start, end))
    supported = [evidence.supports(value, cited) for value in values]
    quoted: dict[int, QuoteSource] = {}
    left: list[int] = []
    for index, value in enumerate(values):
        if supported[index]:
            continue
        if evidence.unverified_amount(value, cited):
            quoted[index] = "letter"
        elif not cited and evidence.said_by_person(value):
            quoted[index] = "person"
        elif evidence.quotes(value, cited) and _framed(plain, value):
            quoted[index] = "letter"
        else:
            left.append(index)
    unsupported = tuple(values[i].text for i in sorted([*quoted, *left]))
    if not unsupported and not letter_laws:
        return SentenceCheck(sentence, "kept", stated, result=sentence, supported=tuple(values))
    unplaced = any(values[i].start < 0 for i in (*quoted, *left))
    if unplaced or (left and not quoted and not letter_laws and not any(supported)):
        return SentenceCheck(sentence, "removed", stated, unsupported, left_out=unsupported, reason="value")
    edits: list[tuple[int, int, str]] = []
    for start, end in letter_laws:  # a § only a letter names: the letter's words ("§81(4) AufenthG")
        tail = _LAW_TAIL.match(plain, end)
        begin, stop = reading.source_span(start, tail.end() if tail else end)
        if sentence[begin - 1 : begin] not in (ENGLISH.open_quote, GERMAN.open_quote):
            edits.append((begin, stop, f"{style.open_quote}{sentence[begin:stop]}{style.close_quote}"))
    for index in quoted:
        begin, end = _widen(sentence, *reading.source_span(values[index].start, values[index].end))
        if sentence[begin - 1 : begin] not in (ENGLISH.open_quote, GERMAN.open_quote):  # not yet quoted
            edits.append((begin, end, f"{style.open_quote}{sentence[begin:end]}{style.close_quote}"))
    for index in left:
        begin, end = _widen(sentence, *reading.source_span(values[index].start, values[index].end))
        edits.append((begin, end, style.placeholder(values[index].kind)))
    result = sentence
    limit = len(sentence)
    for begin, end, replacement in sorted(edits, reverse=True):
        if end > limit:
            continue  # overlaps the edit after it (a currency shared by two values)
        result = result[:begin] + replacement + result[end:]
        limit = begin
    sources: list[QuoteSource] = [*quoted.values()]
    if letter_laws:
        sources.append("letter")
    return SentenceCheck(
        sentence,
        "redacted" if left else "quoted",
        stated,
        unsupported,
        result=result,
        left_out=tuple(values[i].text for i in left),
        quoted_from=tuple(dict.fromkeys(sources)),
        supported=tuple(value for value, ok in zip(values, supported, strict=True) if ok),
        letter_quotes=tuple(
            (values[i].kind, frozenset(cited))
            for i, source in quoted.items()
            if source == "letter" and not evidence.unverified_amount(values[i], cited)
        ),
    )


def _framed(plain: str, value: Value) -> bool:
    """Rule 4a: a phrase naming a letter stands in the same clause as the value."""
    clause_start = 0
    clause_end = len(plain)
    for match in CLAUSE_BREAK.finditer(plain):
        if match.end() <= value.start:
            clause_start = match.end()
        elif match.start() >= value.end:
            clause_end = match.start()
            break
    return bool(LETTER_QUOTE.search(plain[clause_start:clause_end]))


def _states(value: Value, record: RecordValue) -> bool:
    if record.kind == "amount":
        return value.amount is not None and round(value.amount * 100) == record.cents
    return record.day is not None and any(
        reading.as_date() == record.day
        or (reading.year is None and (reading.day, reading.month) == (record.day.day, record.day.month))
        for reading in value.dates
    )


def _widen(sentence: str, begin: int, end: int) -> tuple[int, int]:
    """A value's span with its currency (``18,43 €``, ``€ 18.43``) or weekday (``Fri 31.12.2027``)."""
    if after := _CURRENCY_AFTER.match(sentence, end):
        end = after.end()
    head = sentence[:begin]
    if before := _CURRENCY_BEFORE.search(head) or _WEEKDAY_BEFORE.search(head):
        begin = before.start()
    return begin, end


def quote_value(sentence: str, needle: str, style: Style = ENGLISH) -> str:
    """``sentence`` with the first unquoted value read as ``needle`` (plus its currency or weekday) in
    quotation marks — found as the sentence is shown, so markup or a non-breaking space inside it does
    not hide it."""
    reading = read_as_shown(sentence)
    for value in stated_values(reading.text):
        if value.text != needle:
            continue
        begin, end = _widen(sentence, *reading.source_span(value.start, value.end))
        if sentence[begin - 1 : begin] in (ENGLISH.open_quote, GERMAN.open_quote):
            continue
        return f"{sentence[:begin]}{style.open_quote}{sentence[begin:end]}{style.close_quote}{sentence[end:]}"
    return sentence


def split_note(text: str) -> tuple[str, str | None]:
    """A stored answer split into its body and the check's note (without :data:`NOTE_PREFIX`).

    The check drops every model-written sentence that starts like the note, so only the note it
    appends itself can be the last paragraph starting with the prefix.
    """
    head, sep, tail = text.rpartition("\n\n")
    last = tail if sep else text
    if last.startswith(NOTE_PREFIX) and "\n" not in last:
        return (head.rstrip() if sep else ""), last[len(NOTE_PREFIX) :].strip()
    return text, None
