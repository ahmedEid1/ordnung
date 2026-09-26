"""Claim-level support: which parts of an Ask answer may stay (ADR 0007, ADR 0008).

Ask's tools answer in two channels (:mod:`ordnung.assistant.channels`): Ordnung's *record* (what
code computed, the person confirmed or the pipeline filed with verified evidence) and the *letter
text* (every word that comes from a letter). An answer is checked sentence by sentence against the
record of the records it cites, with this written policy:

1. **What is read.** Each sentence as the person will see it: citation markers, Markdown emphasis,
   code and link syntax, backslash escapes and invisible characters (format characters and the
   other default-ignorable code points) are dropped and typographic punctuation is folded before
   reading, so ``31.**12**.2027`` reads as 31.12.2027. A sentence ends at ``.``, ``!`` or ``?``
   followed by a capital letter (after optional quotes, markup or citation markers), never after a
   one-letter or listed abbreviation (:data:`ABBREVIATION`: ``z. B.``, ``vgl.``, ``Nr.``, ``Wed.``,
   ``p.``); every line is split on its own. A sentence *states* a date when
   :func:`~ordnung.ingest.verify.parse_dates` finds one (plus ``31-12-2027``, ``2027/12/31`` and
   day, month and year apart by spaces or dots, ``31 12 2027``, ``31·XII·2027``) or a digit group
   shaped like a date that does not parse (it can never be supported); it states an amount when
   :func:`~ordnung.ingest.verify.amount_matches` finds a number next to a currency (or a currency
   word: ``dollars``, ``pounds``, ``francs``), or a bare number with two decimals that is neither a
   clock time (``10.30 Uhr``, ``um 9.15``, ``8.00–12.00``) nor a label number (``Raum 2.14``, ``Nr.
   2.14``, ``Version 1.25``). A sentence that starts like Ordnung's own note (:data:`NOTE_PREFIX`)
   is dropped: only the check writes that note.
2. **Cited records.** The records the sentence cites. A sentence that cites none takes those of the
   nearest sentence before it on its line that cites some, else of the nearest one after it (a
   trailing citation covers its line); a list item that cites none takes those of the line ending in
   ``:`` that leads the list.
3. **Supported.** A value is supported when it is in the record part of a cited record — a record that
   appeared in a record part of this turn's tool results. A record's part includes the records listed
   inside it or linked to it: a letter's to-dos and contracts, a contract's letter, a person's to-dos
   (``doc_id``, ``contract_id``, ``party_id``, ``source_doc_id``). Dates without a year match by day
   and month. Today's date and the overview totals Ordnung's code adds up outside any one record
   (``money_summary``) need no citation, and a sentence without a citation of its own may state the
   own date or amount (a to-do's due date, a contract's cancel-by date, a verified amount) of any
   record the answer cites — code computed or verified it, so no letter can have put it there.
4. **Quoted.** Any other value may stay only in quotation marks (“…”, or „…“ in a German answer;
   quotation marks the answer already puts around it are used, straight ones turned into these):
   (a) when a letter's text holds it and the value's clause names a letter as its source
   (:data:`LETTER_QUOTE`: "the letter says …", "the letter's text contains a line claiming …",
   "laut dem Schreiben …", "… per the letter"). The letter must be that of a record the sentence
   cites — a letter's text belongs to the to-dos and contracts filed from it too — or, in a
   sentence that cites nothing, of any record read in this turn. A clause ends at ``;``, a dash,
   ``, and``/``, but``/``, so`` …, and around a contrast (``unlike …,``, ``while``, ``whereas``);
   a phrase like "the letter says" names the source only of what follows it, and a negated one
   ("unlike what the letter says", "the letter says nothing") names none; (b) when it is the
   flagged, unverified amount of a cited to-do or contract (``amount_unverified``,
   ``terms_unverified``), so a real payment stays in a list; (c) when the person wrote it in this
   conversation: it is their words, never Ordnung's. A note under the answer says that quoted
   values are not confirmed, and — when the answer states none of them — gives the own dates
   (a to-do's due date, a contract's cancel-by date) or amounts of the records the quote belongs to
   (the cited ones; with none cited, those whose letter text holds the value): "Ordnung's record for
   what is quoted: deadline Wed 21 Oct 2026", so a letter's or the person's date never stands alone.
5. **Left out.** Every other value is left out. In a sentence that keeps a supported or quoted value
   it is replaced by "[date left out]" or "[amount left out]", so a record's value is never lost
   because of another value next to it; a sentence with nothing to keep is removed. A § that is
   neither in the rules catalog nor in a record part is shown in quotation marks as a letter's words
   when the letter text of a record the sentence cites names it — or, in a sentence that cites
   nothing but names a letter as its source, when a letter read in this turn names it; any other
   such § is replaced by "[law left out]" in a sentence that keeps a value, else its sentence is
   removed. No left-out value is ever shown: when the edits of a sentence would leave one standing,
   the sentence is removed. The note — in the answer's language — says how many values and
   sentences were left out, and why. When nothing is left, Ask answers with a fixed fallback and
   the note still says why.

The check is deterministic and linear in the size of the answer and the tool results: each sentence
is read a bounded number of times, each value is looked up in hash maps of the cited records, and
the phrases and clause breaks of a sentence are found once.

Known limits — documented, not bugs:

- Support is literal, not semantic: a value in a cited record supports a sentence that says
  something else about it ("you owe the library 640.00 € [item:rent]" passes when the rent to-do
  holds 640.00 €). A letter can therefore still steer *which* record the model cites.
- Dates in words ("next Friday", "end of the month") and claims without a date or amount ("there
  is no deadline") are not read; the prompt and the record are the only defence there. A sentence
  whose value was left out keeps its words ("the deadline moved to [date left out]"); the
  placeholder and the note show it, and Ordnung's own date stays wherever it is cited.
- A quote is recognised only by the listed phrases; other wording is treated as Ordnung's own
  claim, so a correct letter value in it is left out. The phrases decide only *how* a letter's value
  is shown (quoted, or left out) — never that it is Ordnung's.
- A value the person wrote stays as their words even in a sentence that agrees with it; the note
  then gives Ordnung's own value next to it.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
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
    r"noted|explains|explained|warns|warned|adds|added|cites|cited|contains|contained|includes|"
    r"included|puts\s+it"
)
_DE_LETTER = r"Brief|Schreiben|Bescheid|Dokument|Rechnung|Mahnung|Absender|Text|Vertrag|Karte"
_OWNER = r"(?:[\w-]+(?:\s+[\w-]+)?'s\s+)?"  # "the tax office's letter"
_SENDER_SPAN = "{1,60}"  # "the letter from <up to 60 characters> says"; bounded, so matching stays linear
LETTER_QUOTE = re.compile(
    rf"""
      (?P<lead>
        \b(?:the|this|that|your|its|their)\s+{_OWNER}(?:{_LETTER_WORDS})(?:\s+(?:text|page))?
          (?:'s\s+(?:[\w-]+\s+)?text)?(?:\s+itself)?
          (?:\s+(?:from|of|for)\s+[^.;:!?\n]{_SENDER_SPAN}?)?\s+(?:also\s+)?(?:{_SAYS})\b
      | \b(?:note|line|sentence|passage|paragraph|instruction|message|block|section|statement)\b
          [^.;:!?\n]{{0,80}}?\b(?:claiming|saying|stating|asserting)\b
      | \b(?:letter|notice)(?:'s)?\s+text\s*:
      | \b(?:im|in\s+dem|in\s+diesem)\s+(?:{_DE_LETTER})\s+(?:steht|heißt\s+es|wird\s+behauptet)\b
      | \b(?:der|das|die|dieser|dieses|diese)\s+(?:{_DE_LETTER})\s+(?:sagt|schreibt|behauptet|nennt|gibt\s+an|
          verlangt|fordert|erwähnt|enthält)\b
      )
    | (?P<either>
        \baccording\s+to\s+(?:the|this|that|your)\s+{_OWNER}(?:{_LETTER_WORDS})\b
      | \b(?:it|this)\s+says\s+in\s+the\s+(?:{_LETTER_WORDS})\b
      | \b(?:per|as\s+in)\s+(?:the|this|that|your)\s+{_OWNER}(?:{_LETTER_WORDS})\b
      | \bas\s+(?:the|this)\s+(?:{_LETTER_WORDS})\s+(?:says|states|puts\s+it)\b
      | \b(?:the\s+)?(?:letter|notice)'s\s+(?:own\s+)?(?:words|wording|terms)\b
      | \b(?:laut|gemäß|gemaess)\s+(?:dem\s+|des\s+|diesem\s+|diesen\s+|ihrem\s+|ihres\s+)?(?:{_DE_LETTER})s?\b
      )
    """,
    re.IGNORECASE | re.VERBOSE,
)
"""The phrases that name a letter as a value's source (policy rule 4a). A ``lead`` phrase ("the
letter says") names the source of what follows it, an ``either`` phrase ("per the letter") of its
whole clause. When in doubt, it is not."""
CLAUSE_BREAK = re.compile(
    r";|\s-+\s|,\s*(?:so|therefore|thus|hence|but|however|yet|which\s+means|meaning|and|or|aber|jedoch|"
    r"daher|deshalb|somit|also|und|oder)\b",
    re.IGNORECASE,
)
"""What ends a clause for rule 4a (read on folded text, where dashes are ``-``): a letter named in
one clause is not the source of a value in the next ("the letter says nothing else, so …")."""
CONTRAST = re.compile(
    r"\b(?:unlike|while|whilst|whereas|although|though|despite|in\s+contrast\s+to|contrary\s+to|obwohl|"
    r"während|wohingegen|anders\s+als|entgegen|trotz)\b",
    re.IGNORECASE,
)
"""A contrast starts a clause of its own that ends at its first comma ("Unlike what the letter
says, your deadline is …": the letter is not the source of what follows the comma)."""
_NEGATED_BEFORE = re.compile(
    r"\b(?:unlike|contrary\s+to|in\s+contrast\s+to|not|anders\s+als|entgegen|im\s+gegensatz\s+zu)\s+"
    r"(?:to\s+)?(?:what\s+|dem,?\s+was\s+|was\s+)?$",
    re.IGNORECASE,
)
_NEGATED_AFTER = re.compile(r"\s*(?:nothing|no|not|never|nichts|nicht|kein\w*|nie)\b", re.IGNORECASE)

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
RemovalReason = Literal["value", "letter", "law"]

_SENTENCE_END = re.compile(
    r"[.!?]+(?P<close>[\"'”“’»)\]*_]*)(?P<cites>(?:[ \t]*\[[^\[\]\n]{1,300}\])*)(?P<gap>[ \t]+)"
)
_OPENERS = "\"'“„‘«(*_["
_LINE_PREFIX = re.compile(r"^(\s*(?:[-*+•]\s+|#{1,6}\s+|>\s*)?)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+•]\s+|\d{1,4}[.)]\s+)")
_LINK = re.compile(r"!?\[([^\]\n]*)\]\(\s*[^)\s]*(?:\s+\"[^\"\n]*\")?\s*\)")
_ESCAPABLE = frozenset("\\`*_[]()#+-.!>~|{}")
_MARKUP = frozenset("*_`")
_IGNORABLE = (
    (0x034F, 0x034F),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x2065, 0x2065),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0xE0000, 0xE0FFF),
)
"""Default-ignorable code points that are not format characters (Cf): a combining grapheme joiner,
Hangul fillers, variation selectors … — shown as nothing (Unicode DerivedCoreProperties)."""
_CURRENCY_WORDS = r"dollars?|pounds?(?:\s+sterling)?|francs?|franken"
_CURRENCY_AFTER = re.compile(
    rf"\s?(?:€|EUR\b|Euro\b|euros?\b|US\$|\$|USD\b|£|GBP\b|CHF\b|{_CURRENCY_WORDS}\b)", re.IGNORECASE
)
_CURRENCY_BEFORE = re.compile(r"(?:€|EUR|Euro|US\$|\$|USD|£|GBP|CHF)\s?$", re.IGNORECASE)
_WORD_CURRENCY = re.compile(
    rf"(?<![\w.,])(?P<num>\d[\d.,]*\d|\d)\s?(?:US\s?)?(?:{_CURRENCY_WORDS})\b", re.IGNORECASE
)
"""Amounts with a currency word :func:`~ordnung.ingest.verify.amount_matches` does not read."""
_WEEKDAY_BEFORE = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun|"
    r"Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|Mo|Di|Mi|Do|Fr|Sa|So)\.?,?\s$"
)
_WINDOW = 16
"""How far before a value its currency or weekday is looked for (``Wednesday, `` is 11 characters)."""
_EXTRA_DATES = re.compile(
    r"(?<![\w.,/-])(?:(?P<d>\d{1,2})-(?P<m>\d{1,2})-(?P<y>\d{4})|(?P<iy>\d{4})[/.](?P<im>\d{1,2})[/.](?P<id>\d{1,2}))"
    r"(?![\w/-]|[.,]\d)"
)
_ROMAN_MONTHS = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11,
    "XII": 12,
}  # fmt: skip
_LOOSE_SEP = r"(?:[ \t]*[./·•∙‧-][ \t]*|[ \t]+)"
_LOOSE_DATES = re.compile(
    rf"(?<![\w.,/·•∙‧-])(?P<d>0?[1-9]|[12]\d|3[01]){_LOOSE_SEP}"
    rf"(?P<m>0?[1-9]|1[0-2]|(?:XII|XI|IX|X|VIII|VII|VI|IV|V|III|II|I)(?![A-Za-z])){_LOOSE_SEP}"
    r"(?P<y>(?:19|20)\d{2})(?![\w/-]|[.,]\d)"
)
"""Day, month (digits or Roman) and year apart by spaces, dots or middle dots: ``31 12 2027``,
``31 . 12 . 2027``, ``31·12·2027``, ``31.XII.2027``."""
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
_QUOTE_CLOSERS: Mapping[str, str] = {
    '"': '"', "“": "”", "„": "“”", "«": "»", "»": "«", "‚": "‘’", "‹": "›", "›": "‹",
}  # fmt: skip
"""Quotation marks an answer may put around a value, and what closes each (single straight quotes
are apostrophes too, so they never count)."""
_MAX_QUOTE = 240

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


def is_invisible(char: str) -> bool:
    """A character shown as nothing: a format character (Cf) or another default-ignorable one."""
    if unicodedata.category(char) == "Cf":
        return True
    code = ord(char)
    return code >= 0x034F and any(low <= code <= high for low, high in _IGNORABLE)


def read_as_shown(source: str) -> Reading:
    """``source`` without citation markers, Markdown markup and invisible characters, punctuation folded."""
    skip = bytearray(len(source))
    for start, end in marker_spans(source):
        skip[start:end] = b"\x01" * (end - start)
    for match in _LINK.finditer(source):
        if skip.find(1, match.start(), match.end()) >= 0:
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
        elif char in _MARKUP or is_invisible(char):
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
        for value in amounts_in(text):
            self.add_amount(value)

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
    """:func:`~ordnung.ingest.verify.parse_dates` plus ``31-12-2027``, ``2027/12/31`` and the loose
    forms of :data:`_LOOSE_DATES`."""
    mentions = parse_dates(text)
    folded = fold_punctuation(text)
    for match in _EXTRA_DATES.finditer(folded):
        mentions.extend(_extra_reading(match))
    for match in _LOOSE_DATES.finditer(folded):
        mentions.extend(_loose_reading(match))
    return mentions


def amounts_in(text: str) -> list[float]:
    """:func:`~ordnung.ingest.verify.amount_matches` plus amounts with a currency word."""
    values = [match.value for match in amount_matches(text)]
    values += [
        value for match in _WORD_CURRENCY.finditer(fold_punctuation(text)) if (value := _word_amount(match))
    ]
    return values


def _word_amount(match: re.Match[str]) -> float | None:
    found = amount_matches(f"{match.group('num')} €")
    return found[0].value if found else None


def _extra_reading(match: re.Match[str]) -> list[DateMention]:
    if match.group("d"):
        day, month, year = int(match.group("d")), int(match.group("m")), int(match.group("y"))
    else:
        day, month, year = int(match.group("id")), int(match.group("im")), int(match.group("iy"))
    return _valid_mention(match.group(), day, month, year)


def _loose_reading(match: re.Match[str]) -> list[DateMention]:
    month_text = match.group("m")
    month = _ROMAN_MONTHS.get(month_text.upper()) or int(month_text)
    return _valid_mention(match.group(), int(match.group("d")), month, int(match.group("y")))


def _valid_mention(text: str, day: int, month: int, year: int) -> list[DateMention]:
    try:
        date(year, month, day)
    except ValueError:
        return []
    return [DateMention(text, day, month, year)]


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


class _Taken:
    """The characters of a reading already claimed by a value (so each character counts once)."""

    def __init__(self, length: int) -> None:
        self.mask = bytearray(length)

    def free(self, start: int, end: int) -> bool:
        return self.mask.find(1, start, end) < 0

    def take(self, start: int, end: int) -> None:
        if start >= 0:
            self.mask[start:end] = b"\x01" * (end - start)


def stated_values(plain: str) -> list[Value]:
    """The dates and amounts a sentence states, in reading order (``plain``: the sentence as read)."""
    values = _date_values(plain)
    taken = _Taken(len(plain))
    for value in values:
        taken.take(value.start, value.end)
    for pattern, reading in ((_EXTRA_DATES, _extra_reading), (_LOOSE_DATES, _loose_reading)):
        for match in pattern.finditer(plain):
            if taken.free(*match.span()):
                readings = tuple(reading(match))
                kind: ValueKind = "date" if readings else "unreadable"
                values.append(Value(match.group(), kind, *match.span(), dates=readings))
                taken.take(*match.span())
    for match in _DATE_LIKE.finditer(plain):
        if taken.free(*match.span()):
            values.append(Value(match.group(), "unreadable", *match.span()))
            taken.take(*match.span())
    for amount in amount_matches(plain):
        span = (amount.start, amount.end)
        if not taken.free(*span) or not (amount.has_currency or _is_money(plain, *span)):
            continue
        values.append(Value(amount.number, "amount", *span, amount=amount.value))
        taken.take(*span)
    for match in _WORD_CURRENCY.finditer(plain):
        span = match.span("num")
        if taken.free(*span) and (worth := _word_amount(match)) is not None:
            values.append(Value(match.group("num"), "amount", *span, amount=worth))
            taken.take(*span)
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
    note gives for quoted records (rule 4); ``label`` says what it is (a key of :data:`RECORD_LABELS`)."""

    kind: Literal["date", "amount"]
    label: str
    day: date | None = None
    cents: int = 0
    currency: str = "EUR"


@dataclass
class _Index:
    """Which records hold each date and amount (for the records a value belongs to in rule 4)."""

    dates: dict[date, set[str]] = field(default_factory=lambda: defaultdict(set))
    day_months: dict[tuple[int, int], set[str]] = field(default_factory=lambda: defaultdict(set))
    cents: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))

    def add(self, record_id: str, facts: FactSet) -> None:
        for day in facts.dates:
            self.dates[day].add(record_id)
        for pair in facts.day_months:
            self.day_months[pair].add(record_id)
        for cents in facts.cents:
            self.cents[cents].add(record_id)

    def holders(self, value: Value) -> set[str]:
        if value.kind == "amount" and value.amount is not None:
            return set(self.cents.get(round(value.amount * 100), ()))
        found: set[str] = set()
        for reading in value.dates:
            full = reading.as_date()
            found |= (
                self.dates.get(full, set())
                if full
                else self.day_months.get((reading.day, reading.month), set())
            )
        return found


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
    letter_index: _Index = field(default_factory=_Index, compare=False)

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
        index = _Index()
        for record_id, facts in letters.items():
            index.add(record_id, facts)
        return cls(
            record=dict(collector.record),
            letters=dict(letters),
            unverified=dict(unverified),
            own={key: frozenset(values) for key, values in collector.own.items()},
            context=collector.context,
            person=words,
            seen_ids=frozenset(collector.seen),
            paragraphs=frozenset(collector.paragraphs),
            letter_index=index,
        )

    def supports(self, value: Value, cited: Collection[str]) -> bool:
        """Policy rule 3: in the context, or in the record part of a cited record."""
        return value.found_in(self.context) or any(
            value.found_in(self.record.get(ref_id, _EMPTY)) for ref_id in cited
        )

    def is_own_value(self, value: Value, records: Collection[str]) -> bool:
        """Policy rule 3 (last part): the own date or amount of one of ``records``."""
        return any(_states(value, own) for ref_id in records for own in self.own.get(ref_id, ()))

    def quotes(self, value: Value, cited: Collection[str]) -> bool:
        """Policy rule 4a (second half): in the letter text of a cited record."""
        return any(value.found_in(self.letters.get(ref_id, _EMPTY)) for ref_id in cited)

    def letter_holders(self, value: Value) -> set[str]:
        """The records read in this turn whose letter text holds ``value``."""
        return self.letter_index.holders(value)

    def unverified_amount(self, value: Value, cited: Collection[str]) -> bool:
        """Policy rule 4b: the flagged, unverified amount of a cited record."""
        return value.kind == "amount" and any(
            value.found_in(self.unverified.get(ref_id, _EMPTY)) for ref_id in cited
        )

    def said_by_person(self, value: Value) -> bool:
        """Policy rule 4c: the person wrote this value in the conversation."""
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

    def own_values(self, records: Collection[str], kind: str) -> list[RecordValue]:
        """The records' own dates (``kind="date"``) or amounts, in a stable order."""
        found = {value for ref_id in records for value in self.own.get(ref_id, ()) if value.kind == kind}
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
    """Quotation marks, placeholders, formats and the note's wording for the words the check adds."""

    open_quote: str
    close_quote: str
    date_left_out: str
    amount_left_out: str
    law_left_out: str
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

    def quoted(self, text: str) -> str:
        return f"{self.open_quote}{text}{self.close_quote}"


ENGLISH = Style(
    "“", "”", "[date left out]", "[amount left out]", "[law left out]",
    ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), german=False,
)  # fmt: skip
GERMAN = Style(
    "„", "“", "[Datum weggelassen]", "[Betrag weggelassen]", "[Gesetz weggelassen]",
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


_NOTE_TEXTS: Mapping[str, tuple[str, str, str, str]] = {
    # (English one, English many, German one, German many); {n} is the count
    "removed_value": (
        "Ordnung left out 1 sentence: it couldn't match its date or amount to the letter, to-do or "
        "contract the sentence refers to.",
        "Ordnung left out {n} sentences: it couldn't match their dates or amounts to the letters, to-dos "
        "or contracts they refer to.",
        "Ordnung hat 1 Satz weggelassen: Sein Datum oder Betrag passt zu keinem Brief, keiner Aufgabe und "
        "keinem Vertrag, auf den er sich bezieht.",
        "Ordnung hat {n} Sätze weggelassen: Ihre Daten oder Beträge passen zu keinem Brief, keiner Aufgabe "
        "und keinem Vertrag, auf den sie sich beziehen.",
    ),
    "removed_letter": (
        "Ordnung left out 1 sentence: its date or amount is only in a letter's text, and the sentence "
        "didn't say it quotes the letter.",
        "Ordnung left out {n} sentences: their dates or amounts are only in a letter's text, and the "
        "sentences didn't say they quote the letter.",
        "Ordnung hat 1 Satz weggelassen: Sein Datum oder Betrag steht nur im Text eines Briefs, und der "
        "Satz sagt nicht, dass er den Brief zitiert.",
        "Ordnung hat {n} Sätze weggelassen: Ihre Daten oder Beträge stehen nur im Text eines Briefs, und die "
        "Sätze sagen nicht, dass sie den Brief zitieren.",
    ),
    "removed_law": (
        "Ordnung left out 1 sentence: it names a law that is neither in Ordnung's rules nor in a letter "
        "it refers to.",
        "Ordnung left out {n} sentences: they name laws that are neither in Ordnung's rules nor in a "
        "letter they refer to.",
        "Ordnung hat 1 Satz weggelassen: Er nennt ein Gesetz, das weder in Ordnungs Regeln noch in einem "
        "Brief steht, auf den er sich bezieht.",
        "Ordnung hat {n} Sätze weggelassen: Sie nennen Gesetze, die weder in Ordnungs Regeln noch in einem "
        "Brief stehen, auf den sie sich beziehen.",
    ),
    "redacted": (
        "1 date or amount is marked “left out”: Ordnung couldn't match it to what its sentence refers to.",
        "{n} dates or amounts are marked “left out”: Ordnung couldn't match them to what their sentences "
        "refer to.",
        "1 Datum oder Betrag ist als „weggelassen“ markiert: Er passt nicht zu dem, worauf sich sein Satz "
        "bezieht.",
        "{n} Daten oder Beträge sind als „weggelassen“ markiert: Sie passen nicht zu dem, worauf sich ihre "
        "Sätze beziehen.",
    ),
    "redacted_law": (
        "1 law is marked “left out”: it is neither in Ordnung's rules nor in a letter its sentence refers to.",
        "{n} laws are marked “left out”: they are neither in Ordnung's rules nor in a letter their "
        "sentences refer to.",
        "1 Gesetz ist als „weggelassen“ markiert: Es steht weder in Ordnungs Regeln noch in einem Brief, "
        "auf den sich sein Satz bezieht.",
        "{n} Gesetze sind als „weggelassen“ markiert: Sie stehen weder in Ordnungs Regeln noch in einem "
        "Brief, auf den sich ihre Sätze beziehen.",
    ),
}
_QUOTE_NOTES: Mapping[frozenset[str], tuple[str, str]] = {
    frozenset({"letter"}): (
        "Text in quotation marks is quoted from a letter; Ordnung has not confirmed it.",
        "Text in Anführungszeichen ist aus einem Brief zitiert; Ordnung hat ihn nicht bestätigt.",
    ),
    frozenset({"person"}): (
        "Text in quotation marks is your own words; Ordnung has not confirmed it.",
        "Text in Anführungszeichen sind Ihre eigenen Worte; Ordnung hat sie nicht bestätigt.",
    ),
    frozenset({"letter", "person"}): (
        "Text in quotation marks is quoted from a letter or your own words; Ordnung has not confirmed it.",
        "Text in Anführungszeichen ist aus einem Brief zitiert oder sind Ihre eigenen Worte; Ordnung hat "
        "ihn nicht bestätigt.",
    ),
}


def _counted(key: str, count: int, style: Style) -> str | None:
    if not count:
        return None
    one, many, one_de, many_de = _NOTE_TEXTS[key]
    text = (one_de if count == 1 else many_de) if style.german else (one if count == 1 else many)
    return text.format(n=count)


# --------------------------------------------------------------------------------------------------
# checking an answer
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SentenceCheck:
    """The verdict on one sentence that states a date, an amount or a §.

    ``values``: what it states, as read; ``unsupported``: those not in the record part of a record it
    cites (quoted or left out); ``left_out``: those replaced by a placeholder, or every unsupported
    value of a removed sentence; ``laws_left_out``: § citations replaced by a placeholder;
    ``reason``: why a sentence was removed; ``result``: the sentence as it stays in the answer (empty
    when removed); ``quote_refs``: for each value quoted as a letter's or the person's words (not
    rule 4b), its kind and the records it belongs to (whose own values the note gives).
    """

    text: str
    verdict: Verdict
    values: tuple[str, ...]
    unsupported: tuple[str, ...] = ()
    result: str = ""
    left_out: tuple[str, ...] = ()
    reason: RemovalReason | None = None
    quoted_from: tuple[QuoteSource, ...] = ()
    supported: tuple[Value, ...] = ()
    quote_refs: tuple[tuple[ValueKind, frozenset[str]], ...] = ()
    laws_left_out: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckedAnswer:
    """The answer after the check, and the verdict on every sentence that stated something checkable."""

    text: str
    sentences: tuple[SentenceCheck, ...]
    forged_notes: int = 0
    record_values: tuple[str, ...] = ()
    style: Style = ENGLISH

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
        """The visible note under the answer, with its prefix, in the answer's language (``None``
        when nothing was changed)."""
        style = self.style
        kept = [check for check in self.sentences if check.verdict != "removed"]
        parts = [
            _counted("removed_value", sum(1 for c in self.removed if c.reason == "value"), style),
            _counted("removed_letter", sum(1 for c in self.removed if c.reason == "letter"), style),
            _counted("redacted", sum(len(c.left_out) for c in kept), style),
            _counted("removed_law", sum(1 for c in self.removed if c.reason == "law"), style),
            _counted("redacted_law", sum(len(c.laws_left_out) for c in kept), style),
        ]
        sources = frozenset(source for check in self.quoted for source in check.quoted_from)
        if sources:
            english, german = _QUOTE_NOTES[sources]
            parts.append(german if style.german else english)
        if self.record_values:
            lead = (
                "Laut Ordnung gilt für das Zitierte"
                if style.german
                else "Ordnung's record for what is quoted"
            )
            parts.append(f"{lead}: {'; '.join(self.record_values)}.")
        shown = [part for part in parts if part]
        return f"{NOTE_PREFIX} {' '.join(shown)}" if shown else None


def check_answer(
    text: str, evidence: TurnEvidence, *, citable: Collection[str], style: Style | None = None
) -> CheckedAnswer:
    """Apply the policy of this module to ``text``; ``citable`` are the ids that may stay cited."""
    style = style or style_for(text)
    answer_cited = frozenset(c.id for c in parse_citations(text) if c.id in citable)
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
        for sentence, mine, cited in zip(sentences, own, _inherit(own, lead if item else []), strict=True):
            reading = read_as_shown(sentence)
            if _FORGED_NOTE.match(reading.text):
                forged += 1
                continue
            check = check_sentence(
                sentence,
                evidence,
                cited=cited,
                style=style,
                reading=reading,
                answer_cited=() if mine else answer_cited,
            )
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
    return CheckedAnswer(
        "\n".join(lines), tuple(checks), forged, _record_values(checks, evidence, style), style
    )


def _record_values(checks: Sequence[SentenceCheck], evidence: TurnEvidence, style: Style) -> tuple[str, ...]:
    """Rule 4: the own dates and amounts of the records quoted values belong to, when the answer
    states none of them (at most :data:`MAX_RECORD_VALUES` of a kind), as the note words them."""
    shown: list[str] = []
    stated = [value for check in checks if check.result for value in check.supported]
    for kind in ("date", "amount"):
        records = {
            ref
            for check in checks
            if check.result
            for quoted, refs in check.quote_refs
            if quoted == kind
            for ref in refs
        }
        own = evidence.own_values(records, kind)
        if own and len(own) <= MAX_RECORD_VALUES and not any(_states(v, r) for v in stated for r in own):
            shown += [style.record_value(value) for value in own]
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
    answer_cited: Collection[str] = (),
) -> SentenceCheck | None:
    """The verdict on one sentence (``None`` when it states no date, amount or §); ``cited`` are the
    citable records it cites or inherits (rule 2); ``answer_cited`` those the whole answer cites, for a
    sentence without citations of its own (rule 3)."""
    reading = reading or read_as_shown(sentence)
    plain = reading.text
    values = stated_values(plain)
    laws = list(paragraph_spans(plain))
    if not values and not laws:
        return None
    stated = tuple(value.text for value in values)
    frames = _Frames.of(plain)
    letter_laws: list[tuple[int, int]] = []
    unknown_laws: list[tuple[str, int, int]] = []
    for number, law, start, end in laws:
        if evidence.knows_paragraph(number, law):
            continue
        framed = bool(cited) or frames.names_letter  # uncited: the letter must be named
        if framed and evidence.letter_names_paragraph(number, law, cited):
            letter_laws.append((start, end))
        else:
            unknown_laws.append((f"§ {number} {law or ''}".strip(), start, end))
    supported = [
        evidence.supports(value, cited) or evidence.is_own_value(value, answer_cited) for value in values
    ]
    quoted: dict[int, tuple[QuoteSource, frozenset[str]]] = {}
    left: list[int] = []
    letter_only = True  # every left-out value is in a letter the sentence could have quoted
    for index, value in enumerate(values):
        if supported[index]:
            continue
        holders = frozenset(cited) if cited else frozenset(evidence.letter_holders(value))
        if evidence.unverified_amount(value, cited):
            quoted[index] = ("letter", frozenset())  # rule 4b: the record already gives it as unverified
        elif evidence.said_by_person(value):
            quoted[index] = ("person", holders)
        elif (evidence.quotes(value, cited) if cited else bool(holders)) and frames.frames_value(value):
            quoted[index] = ("letter", holders)
        else:
            left.append(index)
            letter_only = letter_only and (evidence.quotes(value, cited) if cited else bool(holders))
    unsupported = tuple(values[i].text for i in sorted([*quoted, *left]))
    if not unsupported and not letter_laws and not unknown_laws:
        return SentenceCheck(sentence, "kept", stated, result=sentence, supported=tuple(values))
    left_texts = tuple(values[i].text for i in left)
    law_names = tuple(name for name, _, _ in unknown_laws)
    keeps = bool(quoted) or bool(letter_laws) or any(supported)
    unplaced = any(values[i].start < 0 for i in (*quoted, *left))
    if unplaced or not keeps:
        reason: RemovalReason = "law" if unknown_laws and not left else ("letter" if letter_only else "value")
        return SentenceCheck(
            sentence,
            "removed",
            stated,
            unsupported + law_names,
            left_out=left_texts + law_names,
            reason=reason,
        )
    result = _apply(sentence, reading, values, quoted, left, letter_laws, unknown_laws, style)
    if result is None or _still_shows(result, left_texts):
        return SentenceCheck(
            sentence,
            "removed",
            stated,
            unsupported + law_names,
            left_out=left_texts + law_names,
            reason="value",
        )
    sources: list[QuoteSource] = [source for source, _ in quoted.values()]
    if letter_laws:
        sources.append("letter")
    return SentenceCheck(
        sentence,
        "redacted" if left or unknown_laws else "quoted",
        stated,
        unsupported,
        result=result,
        left_out=left_texts,
        quoted_from=tuple(dict.fromkeys(sources)),
        supported=tuple(value for value, ok in zip(values, supported, strict=True) if ok),
        quote_refs=tuple((values[i].kind, refs) for i, (_, refs) in quoted.items() if refs),
        laws_left_out=law_names,
    )


def _apply(
    sentence: str,
    reading: Reading,
    values: Sequence[Value],
    quoted: Mapping[int, tuple[QuoteSource, frozenset[str]]],
    left: Sequence[int],
    letter_laws: Sequence[tuple[int, int]],
    unknown_laws: Sequence[tuple[str, int, int]],
    style: Style,
) -> str | None:
    """The sentence with its quotes and placeholders (``None`` when two edits would overlap)."""
    pairs = _QuotePairs(sentence)
    edits: list[tuple[int, int, str]] = []
    for start, end in letter_laws:  # a § only a letter names: the letter's words ("§81(4) AufenthG")
        tail = _LAW_TAIL.match(reading.text, end)
        edits += pairs.quote(*reading.source_span(start, tail.end() if tail else end), style)
    for _, start, end in unknown_laws:
        tail = _LAW_TAIL.match(reading.text, end)
        begin, stop = reading.source_span(start, tail.end() if tail else end)
        if sentence[begin - 1 : begin] == "(" and sentence[stop : stop + 1] == ")":
            begin, stop = begin - 1, stop + 1  # "(§ 573c BGB)" → "[law left out]", not "([law left out])"
        edits.append((begin, stop, style.law_left_out))
    spans = {i: reading.source_span(values[i].start, values[i].end) for i in (*quoted, *left)}
    previous_end = 0
    for index in sorted(spans, key=lambda i: spans[i][0]):
        core_begin, core_end = spans[index]
        begin, end = _widen(sentence, core_begin, core_end, values[index].kind)
        if begin < previous_end:  # a currency between two values belongs to the first
            begin = core_begin
        previous_end = end
        if index in quoted:
            edits += pairs.quote(begin, end, style)
        else:
            edits.append((begin, end, style.placeholder(values[index].kind)))
    result = sentence
    limit = len(sentence) + 1
    for begin, end, replacement in sorted(set(edits), reverse=True):
        if end > limit:
            return None  # never drop an edit: the caller removes the sentence instead
        result = result[:begin] + replacement + result[end:]
        limit = begin
    return result


def _still_shows(result: str, left_texts: Sequence[str]) -> bool:
    """Whether a value that was left out can still be read in the edited sentence (then it goes)."""
    if not left_texts:
        return False
    remaining = {value.text for value in stated_values(read_as_shown(result).text)}
    return any(text in remaining for text in left_texts)


class _QuotePairs:
    """The quotation marks a sentence already has (one level, each at most :data:`_MAX_QUOTE` long)."""

    def __init__(self, sentence: str) -> None:
        self.sentence = sentence
        self.pairs: list[tuple[int, int]] = []
        opened: int | None = None
        for index, char in enumerate(sentence):
            if opened is not None and char in _QUOTE_CLOSERS[sentence[opened]]:
                if index - opened <= _MAX_QUOTE:
                    self.pairs.append((opened, index))
                opened = None
            elif opened is None and char in _QUOTE_CLOSERS:
                opened = index
        self.starts = [start for start, _ in self.pairs]

    def around(self, begin: int, end: int) -> tuple[int, int] | None:
        at = bisect_right(self.starts, begin - 1) - 1
        if at >= 0 and self.pairs[at][0] < begin and end <= self.pairs[at][1]:
            return self.pairs[at]
        return None

    def quote(self, begin: int, end: int, style: Style) -> list[tuple[int, int, str]]:
        """Edits that show ``sentence[begin:end]`` in quotation marks: the answer's own, in the
        check's form, when it has them around it; else new ones."""
        pair = self.around(begin, end)
        if pair is None:
            return [(begin, end, style.quoted(self.sentence[begin:end]))]
        opening, closing = pair
        if (self.sentence[opening], self.sentence[closing]) in {("“", "”"), ("„", "“"), ("„", "”")}:
            return []  # already in typographic quotation marks
        return [(opening, opening + 1, style.open_quote), (closing, closing + 1, style.close_quote)]


@dataclass(frozen=True)
class _Frames:
    """Where a sentence names a letter as a value's source (rule 4a), found once per sentence:
    for each clause, where its first leading phrase ends and whether it has a whole-clause phrase."""

    breaks: tuple[int, ...]
    lead_end: tuple[float, ...]
    either: tuple[bool, ...]
    names_letter: bool

    @classmethod
    def of(cls, plain: str) -> _Frames:
        cuts: list[int] = []
        for match in CLAUSE_BREAK.finditer(plain):
            cuts.append(match.start())
        for match in CONTRAST.finditer(plain):
            cuts.append(match.start())
            comma = plain.find(",", match.end())
            if comma >= 0:
                cuts.append(comma)
        breaks = tuple(sorted(set(cuts)))
        lead_end: list[float] = [float("inf")] * (len(breaks) + 1)
        either = [False] * (len(breaks) + 1)
        names = False
        for match in LETTER_QUOTE.finditer(plain):
            names = True
            if _NEGATED_BEFORE.search(plain, max(0, match.start() - 40), match.start()):
                continue
            clause = bisect_right(breaks, match.start())
            if match.group("either"):
                either[clause] = True
            elif not _NEGATED_AFTER.match(plain, match.end()):
                lead_end[clause] = min(lead_end[clause], match.end())
        return cls(breaks, tuple(lead_end), tuple(either), names)

    def frames_value(self, value: Value) -> bool:
        clause = bisect_right(self.breaks, value.start)
        if clause < len(self.breaks) and value.end > self.breaks[clause]:
            return False  # a value across a clause break belongs to neither clause
        return self.either[clause] or self.lead_end[clause] <= value.start


def _states(value: Value, record: RecordValue) -> bool:
    if record.kind == "amount":
        return value.amount is not None and round(value.amount * 100) == record.cents
    return record.day is not None and any(
        reading.as_date() == record.day
        or (reading.year is None and (reading.day, reading.month) == (record.day.day, record.day.month))
        for reading in value.dates
    )


def _widen(sentence: str, begin: int, end: int, kind: ValueKind) -> tuple[int, int]:
    """An amount's span with its currency (``18,43 €``, ``€ 18.43``), a date's with its weekday (``Fri
    31.12.2027``); only :data:`_WINDOW` characters before it are read."""
    window = max(0, begin - _WINDOW)
    if kind == "amount":
        if after := _CURRENCY_AFTER.match(sentence, end):
            end = after.end()
        if before := _CURRENCY_BEFORE.search(sentence, window, begin):
            begin = before.start()
    elif before := _WEEKDAY_BEFORE.search(sentence, window, begin):
        begin = before.start()
    return begin, end


def quote_value(sentence: str, needle: str, style: Style = ENGLISH) -> str:
    """``sentence`` with the first unquoted value read as ``needle`` (plus its currency or weekday) in
    quotation marks — found as the sentence is shown, so markup or a non-breaking space inside it does
    not hide it."""
    reading = read_as_shown(sentence)
    pairs = _QuotePairs(sentence)
    for value in stated_values(reading.text):
        if value.text != needle:
            continue
        begin, end = _widen(sentence, *reading.source_span(value.start, value.end), value.kind)
        edits = pairs.quote(begin, end, style)
        if not edits:
            continue
        result = sentence
        for start, stop, replacement in sorted(edits, reverse=True):
            result = result[:start] + replacement + result[stop:]
        return result
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
