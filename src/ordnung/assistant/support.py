"""Claim-level support: which parts of an Ask answer may stay (ADR 0007, ADR 0008).

Ask's tools answer in two channels (:mod:`ordnung.assistant.channels`): Ordnung's *record* (what
code computed, the person confirmed or the pipeline filed with verified evidence) and the *letter
text* (every word that comes from a letter). An answer is checked sentence by sentence against the
record of the records it cites, with this written policy:

1. **What is read.** Each sentence as the person will see it: citation markers, Markdown emphasis,
   code and link syntax (a link needs text: the web shows ``[](…)`` as written), backslash escapes
   and invisible characters (format characters and the other default-ignorable code points) are
   dropped and typographic punctuation is folded before reading, so ``31.**12**.2027`` reads as
   31.12.2027 — except that an underscore between two letters or digits stays (the web shows it as
   written) and so does an asterisk between two digits. A sentence ends at ``.``, ``!`` or ``?``
   followed by a capital letter (after optional quotes, markup or citation markers), never after a
   one-letter or listed abbreviation (:data:`ABBREVIATION`: ``z. B.``, ``vgl.``, ``Nr.``, ``Wed.``,
   ``p.``); every line is split on its own — except that a line continuing its paragraph, list item
   or quote after a soft line break (the web shows them as one text) joins the line before it when a
   date or amount stands across the break (``21.10.`` / ``2027``). A sentence *states*

   - a date when :func:`~ordnung.ingest.verify.parse_dates` finds one, or day, month (digits or
     Roman) and year apart by spaces, dots or middle dots (``31 12 2027``, ``31·XII·2027``), or
     ``31-Dec-2027``;
   - a date in any run of digit groups joined by single punctuation marks or symbols (:data:`_RUN`:
     ``31|12|2027``, ``31_12_2027``, ``31。12。2027``, ``2027.12.31``, a letter O, o, I or l inside a
     number: ``2O27``) that holds a day, a month and a year — or a year, a month and a day — anywhere
     in it and whatever follows it; the two marks between them may differ only around a four-digit
     year. When those groups are no calendar date the value is *unreadable*: it is never supported.
     A time after a date belongs to it (``2027-12-31T23:59``, ``2027-12-31Z``). A run after a label
     such as ``Tel.``, ``Wohnung`` or ``Az.`` is a number, and a phone number has no date shape;
   - a month with a year and no day: ``December 2027``, ``Dec '27``, ``Ende Dezember 2027``, ``end of
     2027`` (read as December), ``12/2027``, ``12.2027``, ``2027-12``;
   - an amount when :func:`~ordnung.ingest.verify.amount_matches` finds a number next to a currency
     (or a currency word: ``dollars``, ``pounds``, ``francs``), a number with one decimal or ``.-``
     next to a currency (``18,4 €``, ``€ 18.4``, ``18.- €``), or a bare number with two decimals
     that is neither a label number (``Raum 2.14``, ``Nr. 2.14``, ``Version 1.25``) nor a clock time
     — a time only with its unit after it or after the other end of its range (``10.30 Uhr``,
     ``8.00–12.00 Uhr``): "from 18.36 to 21.50" is money. A number followed by ``%``, "Prozent" or
     "percent" is a rate, not an amount.

   A sentence that starts like Ordnung's own note (:data:`NOTE_LABELS`, after any symbols, emoji or
   markup, followed by punctuation, a symbol or nothing — ``Checked by Ordnung:``, ``… Ordnung —``,
   ``… Ordnung ✓``) is left out, and the note says so: only the check writes that note.
2. **Cited records.** The records the sentence cites. A sentence that cites none takes those of the
   nearest sentence before it on its line that cites some, else of the nearest one after it (a
   trailing citation covers its line); a list item that cites none takes those of the line ending in
   ``:`` that leads the list.
3. **Supported.** A value is supported when it is in the record part of a cited record — a record that
   appeared in a record part of this turn's tool results. A record's part includes the records listed
   inside it or linked to it: a letter's to-dos and contracts, a contract's letter, a person's to-dos
   (``doc_id``, ``contract_id``, ``party_id``, ``source_doc_id``); a category's fixed costs
   (``money_summary``) belong to the contracts of that category. Dates without a year match by day and
   month; a month without a day matches a record date in that month. Today's date needs no citation.
   The overview totals Ordnung's code adds up over many records (``due_this_month``,
   ``fixed_costs_monthly``) support only a sentence without a citation of its own — a total can equal
   one record's amount, so it never backs a claim about a record. A sentence without a citation of its
   own may state the own date or amount (a to-do's due date, a contract's cancel-by date, a verified
   amount) of a record the answer cites elsewhere — code computed or verified it, so no letter can
   have put it there — and the check adds the citations of the records the value belongs to (a to-do
   before its letter, contract or person; a month can be several to-dos') to the sentence and says so
   in the note, so the person sees whose value it is ("… also cancelled by Wed 21 Oct 2026
   [item:tax objection]" shows the tax objection's chip, not the phone contract's).
4. **Shown as unconfirmed.** Two other kinds of value stay, in quotation marks (“…”, or „…“ in a
   German answer; quotation marks the answer already puts around it are used, straight ones turned
   into these): the flagged, unverified amount of a cited to-do or contract (``amount_unverified``,
   ``terms_unverified``: the record itself says the amount is only the letter's), so a real payment
   stays in a list; and a value the person wrote in this conversation — their words, never
   Ordnung's. The note says that quoted values are not confirmed.
5. **Left out.** Every other value is left out. One that only a letter's text holds (of a cited
   record; citing nothing, of any record read in this turn) is replaced by "[date only in the
   letter]" or "[amount only in the letter]": Ordnung shows a date or amount as its answer only when
   its record holds it, and the note says to open the letter. Any other is replaced by "[date left
   out]" or "[amount left out]" (with a month range's start: "Oct–" never stands alone). A sentence
   that keeps no supported or quoted value is removed — its words would carry the claim alone —
   unless every value it leaves out is a letter's: then its words are about the letter ("the letter
   claims the deadline moved to [date only in the letter]"), and a warning about injected text stays.
   A left-out value is never shown: when the edits of a sentence would leave one standing, the
   sentence is removed. When a value was left out or a person's value quoted, and the answer states
   none of the own dates (or amounts) of the records those sentences cite (citing nothing: of the
   records whose letter text holds the value), the note gives them with what they are — never as
   what the left-out value should have been: "For the records concerned, Ordnung has on file:
   deadline Wed 21 Oct 2026".
6. **Laws.** A § must be in the rules catalog, among the laws Ordnung's own Ideas state (the
   caller's ``catalog``: :func:`ordnung.assistant.ask.known_laws`) or in a record part (a list such
   as ``§ 622 Abs. 1, 3, 6 BGB`` keeps its law, so ``§ 622 BGB`` is known). Any other § — also one
   that only a letter names — removes its whole sentence: an unvouched legal basis can change what
   the sentence says ("under § 999 AO the deadline no longer applies"), so it is never kept with the
   law blanked.

The note — in the answer's language, under its label (:data:`NOTE_LABELS`) — says how many values,
sentences and lines were left out, and why. When nothing is left, Ask answers with a fixed fallback
and the note still says why.

The check is deterministic and linear in the size of the answer and the tool results: each sentence
is read a bounded number of times, each value is looked up in hash maps of the cited records, and
every pattern is bounded or cannot start twice inside the same run of characters (a run of ``[``, of
digits or of spaces is read once).

Known limits — documented, not bugs:

- Support is literal, not semantic: a value in a cited record supports a sentence that says
  something else about it ("you owe the library 640.00 € [item:rent]" passes when the rent to-do
  holds 640.00 €). A letter can therefore still steer *which* record the model cites.
- Dates in words ("next Friday", "end of the month", "early 2027", a bare year), calendar weeks
  (``KW 52/2027``), rates ("2.90 %") and claims without a date, amount or § ("there is no deadline")
  are not read; nor are day, month and two-digit year joined by two different marks (``31.12/27``:
  its ``31.12`` is read as an amount), digit groups apart only by spaces other than day, month and
  year (``2027 12 31``), dates in other scripts (``2027年12月31日``), or digits replaced by letters
  other than O, o, I and l. The prompt and the record are the only defence there. A sentence whose
  value was left out keeps its words ("the deadline moved to [date left out]"); the placeholder and
  the note show it, and Ordnung's own date stays wherever it is cited.
- A correct value that only a letter's text holds is shown only as "[date only in the letter]", and
  a correct § that only a letter names removes its sentence. A sentence whose values are all a
  letter's keeps its words — a warning about injected text, but also a sentence that repeats the
  letter's claim as if it were true ("the deadline was extended to [date only in the letter]"); the
  placeholder and the note, with Ordnung's own dates, show whose value it is. Which words of a
  sentence quote a letter is never decided from its wording; quotes the model marks for code are
  the next step if this costs too much in use (ADR 0008).
- A value the person wrote stays as their words even in a sentence that agrees with it; the note
  then gives Ordnung's own value next to it.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from ordnung.assistant.channels import parse_tool_result
from ordnung.assistant.citations import ID_PREFIXES, marker_spans, parse_citations
from ordnung.ingest.normalize import fold_punctuation
from ordnung.ingest.verify import MONTH_NUMBERS, DateMention, amount_matches, parse_dates
from ordnung.secretary.review import paragraph_spans, paragraphs_in

CITABLE_ID = re.compile(r"(?:doc|itm|ctr|pty)_[a-z0-9]+")
LINK_KEYS = ("doc_id", "contract_id", "party_id", "source_doc_id")
AMOUNT_KEYS = frozenset({"amount", "monthly", "monthly_cost", "due_this_month", "fixed_costs_monthly"})
"""Numeric fields that are money (other numbers — pages, months, counts — never support an amount)."""
AMOUNT_MAPS = frozenset({"fixed_costs_by_category", "fixed_costs_monthly_other_currencies"})
"""Fields whose values are all money (``{"rent": 640.0, …}``)."""
TODAY_KEY = "today"
"""The top-level record field every sentence may state (today's date)."""
TOTAL_KEYS = frozenset({"due_this_month", "fixed_costs_monthly", "fixed_costs_monthly_other_currencies"})
"""Top-level totals Ordnung's code adds up over many records: only a sentence without citations of its own may
state them (rule 3) — a total can equal one record's amount, so it never backs a claim about a record."""
CATEGORY_TOTALS = "fixed_costs_by_category"
CATEGORY_ROWS = "fixed_cost_contracts"
"""A category's fixed costs belong to the contracts of that category (``fixed_cost_contracts`` rows
carry their ``category``): in practice a category total is often one contract's cost."""
UNVERIFIED_FLAGS = ("amount_unverified", "terms_unverified")
"""Record flags saying a record's amounts are only in its letter text (policy rule 4)."""
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
"""The note gives the records' own values only when there are at most this many of a kind."""

NOTE_PREFIX = "Checked by Ordnung:"
NOTE_PREFIX_DE = "Von Ordnung geprüft:"
NOTE_LABELS = ("Checked by Ordnung", "Von Ordnung geprüft")
"""The label of the check's note (English, German); a line of the answer that starts like it is not
the model's to write (rule 1)."""

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
_LINK = re.compile(
    r"!?\[([^\[\]\n]{1,500})\]\([ \t]{0,20}[^\s()\[\]]{0,2000}(?:[ \t]{1,20}\"[^\"\n]{0,300}\")?[ \t]{0,20}\)"
)
"""Markdown link or image syntax with text (the web shows ``[](…)`` as written). Neither the text
nor the address may hold a bracket, and every part is bounded, so finding every link is linear in
the answer's length (a run of ``[`` is read once)."""
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
_MONTH_NAME = "|".join(sorted(MONTH_NUMBERS, key=len, reverse=True))
_RANGE_START_BEFORE = re.compile(rf"\b(?:{_MONTH_NAME})\.?\s?(?:[-–—]|bis|to|until)\s?$", re.IGNORECASE)
"""A month name that starts a range ending in a value (``Oct–Dec 2026``): it goes with that value."""
_WINDOW = 16
"""How far before a value its currency, weekday or range start is looked for (``Wednesday, `` is 11
characters)."""
_ROMAN_MONTHS = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10, "XI": 11,
    "XII": 12,
}  # fmt: skip
_LOOSE_SEP = r"(?:[ \t]*[^\w\s()\[\]{}<>\"'“”„‘’«»,;:][ \t]*|[ \t]+)"
_LOOSE_DATES = re.compile(
    rf"(?<![\w.,/·•∙‧-])(?P<d>0?[1-9]|[12]\d|3[01]){_LOOSE_SEP}"
    rf"(?P<m>0?[1-9]|1[0-2]|(?:XII|XI|IX|X|VIII|VII|VI|IV|V|III|II|I)(?![A-Za-z])){_LOOSE_SEP}"
    r"(?P<y>(?:19|20)\d{2})(?!\d)"
)
"""Day, month (digits or Roman) and year apart by spaces or by a mark with spaces around it:
``31 12 2027``, ``31 . 12 . 2027``, ``31 | 12 | 2027``, ``31·12·2027``, ``31.XII.2027``."""
_NAMED_DATES = re.compile(
    rf"(?<![\w.,/-])(?P<d>\d{{1,2}})[-/](?P<m>{_MONTH_NAME})\.?[-/](?P<y>(?:19|20)\d{{2}})(?!\d)",
    re.IGNORECASE,
)
"""Day, month name and year joined by hyphens or slashes: ``31-Dec-2027``, ``31/Dez/2027``."""
_MONTH_YEAR = re.compile(
    rf"\b(?:(?:end\s+of|ende)\s+)?(?P<m>{_MONTH_NAME})\b\.?,?\s*(?:(?P<y>(?:19|20)\d{{2}})|'(?P<ay>\d{{2}}))(?!\d)"
    r"|\b(?:end\s+of|ende|year-end|jahresende)\s+(?P<ey>(?:19|20)\d{2})(?!\d)",
    re.IGNORECASE,
)
"""A month and a year without a day: ``December 2027``, ``Dec '27``, ``Ende Dezember 2027``, ``end of
2027`` (read as December). Such a value states a month: a record date in that month supports it
(rule 3)."""
_GROUP = r"\d(?:[OoIl]?\d)*"
_MARK = r"(?:[^\w\s()\[\]{}<>\"'“”„‘’«»]|_)"
_RUN = re.compile(rf"(?<![\dOoIl])(?:{_GROUP})(?:{_MARK}(?:{_GROUP}))+")
"""Digit groups joined by single punctuation marks or symbols (an underscore too; not a bracket or a
quotation mark): ``31|12|2027``, ``2027-12-31``, ``31。12。2027``. A group may hold a letter O, o, I or
l between digits (``2O27``). Rule 1 reads the dates or the month in such a run; each iteration takes
a mark and a digit, so a run is read once."""
_SPLIT_RUN = re.compile(rf"(?P<group>{_GROUP})|(?P<mark>{_MARK})")
_LOOKALIKE_DIGITS = str.maketrans("OoIl", "0011")
_MONTH_MARKS = frozenset("./-_|")
"""Marks that join a month and a year (``12/2027``): not a decimal comma, a colon or a sign."""
_TIME_AFTER_DATE = re.compile(r"(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d{1,6})?)?)?(?:Z\b|[+-]\d{2}:?\d{2}\b)?")
"""A time written right after a date (``T23:59``, `` 23:59:00``, ``Z``, ``+01:00``): part of it."""


def _time_after(plain: str, end: int) -> int:
    """Where a date ending at ``end`` ends with the time written right after it."""
    found = _TIME_AFTER_DATE.match(plain, end)
    return found.end() if found else end


_REFERENCE_BEFORE = re.compile(
    r"(?:\b(?:Tel|Telefon|Phone|Fax|Mobil|Mobile|Handy|Wohnung|Apartment|Apt|Flat|Unit|Nr|No|Nummer|Number|"
    r"Az|Aktenzeichen|Ref|Reference|Referenz|Zeichen|Kundennummer|Vertragsnummer|Raum|Room|Zimmer)\.?:?)\s*$",
    re.IGNORECASE,
)
_CLOCK = re.compile(r"(?P<h>\d{1,2})[.,](?P<m>\d{2})")
_TIME_AFTER = re.compile(r"\s*(?:Uhr\b|h\b|hrs?\b|o'clock\b|a\.?\s?m\b\.?|p\.?\s?m\b\.?)", re.IGNORECASE)
_TIME_RANGE_AFTER = re.compile(
    r"\s*(?:-|bis|to|and|und)\s*(?P<h>\d{1,2})[.:,](?P<m>\d{2})(?![.,]?\d)", re.IGNORECASE
)
_PERCENT_AFTER = re.compile(r"\s?(?:%|Prozent\b|percent\b|per\s?cent\b|v\.\s?H\.)", re.IGNORECASE)
"""A number followed by a percent sign or word is a rate, not money (rates are not checked)."""
_SHORT_AMOUNT = re.compile(
    r"(?<![\w.,])(?P<int>\d{1,3}(?:\.\d{3})+|\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:(?P<sep>[.,])(?P<dec>\d)(?![\w.,]?\d|\w)|[.,](?P<dash>-{1,2})(?![\w-]))"
)
"""A number with one decimal or a ``.-`` dash (``18,4``, ``18.-``): money when a currency stands next
to it (``18,4 €``, ``€ 18.4``, ``18.- €``) — :func:`~ordnung.ingest.verify.amount_matches` reads only
two decimals and ``,-``."""
_LABEL_BEFORE = re.compile(
    r"(?:\b(?:Raum|Room|Zimmer|Zi|Rm|Nr|No|Nummer|Number|Version|Ver|v|Art|Abs|Kap|Kapitel|Chapter|"
    r"Section|Abschnitt|Seite|Page|pp?|S|Gleis|Platform|Tel|Etage|Floor|Stock|Haus|Building|Geb|Tür|"
    r"Door|Schalter|Counter|Desk|Platz|Seat)\.?|§)\s*$",
    re.IGNORECASE,
)
_FORGED_NOTE = re.compile(
    r"^[\W\d_]*(?:checked\s+by\s+ordnung|von\s+ordnung\s+gepr(?:ü|ue)ft)\s*(?:[^\w\s']|$)", re.IGNORECASE
)
"""A sentence that starts like the check's note (after any symbols, emoji, numbers or markup) and goes
on with punctuation or a symbol (``:``, ``—``, ``✓``, ``)``) or ends there — but not a sentence such as
"Checked by Ordnung's records, …", which is checked like any other."""
_QUOTE_CLOSERS: Mapping[str, str] = {
    '"': '"', "“": "”", "„": "“”", "«": "»", "»": "«", "‚": "‘’", "‹": "›", "›": "‹",
}  # fmt: skip
"""Quotation marks an answer may put around a value, and what closes each (single straight quotes
are apostrophes too, so they never count)."""
_MAX_QUOTE = 240
_MARKER_TYPES = {prefix: marker for marker, prefix in ID_PREFIXES.items()}
"""Id prefix → the marker type that cites it (``itm`` → ``item``)."""
_STOPS = frozenset(".!?:;")
_HOLDER_ORDER = {"itm": 0, "ctr": 1, "doc": 2, "pty": 3}
"""Which record a value shared through links belongs to first: a to-do's due date is the to-do's (its
letter, contract and person hold it too), a contract's cancel-by date the contract's."""

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


def _shown_markup(source: str, index: int) -> bool:
    """Whether a ``*`` or ``_`` is shown as written: an underscore between two letters or digits
    (the web never reads one as emphasis) or an asterisk between two digits (read as the mark
    between digit groups, so ``31*12*2027`` is never hidden as ``31122027``)."""
    char = source[index]
    if char == "`" or index == 0 or index + 1 >= len(source):
        return False
    before, after = source[index - 1], source[index + 1]
    if char == "_":
        return before.isalnum() and after.isalnum()
    return before.isdigit() and after.isdigit()


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
        elif (char in _MARKUP and not _shown_markup(source, index)) or is_invisible(char):
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
    """Dates (full, by day and month, and by year and month) and amounts (in cents) of a record, a
    letter or the context."""

    dates: set[date] = field(default_factory=set)
    day_months: set[tuple[int, int]] = field(default_factory=set)
    months: set[tuple[int, int]] = field(default_factory=set)
    cents: set[int] = field(default_factory=set)

    def add_text(self, text: str) -> None:
        """Every date, month and amount written in ``text``."""
        for mention in dates_in(text):
            self.day_months.add((mention.day, mention.month))
            if (full := mention.as_date()) is not None:
                self.add_date(full)
        self.months.update(months_in(text))
        for value in amounts_in(text):
            self.add_amount(value)

    def add_amount(self, value: float) -> None:
        self.cents.add(round(value * 100))

    def add_date(self, value: date) -> None:
        self.dates.add(value)
        self.day_months.add((value.day, value.month))
        self.months.add((value.year, value.month))

    def has_date(self, mention: DateMention) -> bool:
        full = mention.as_date()
        return full in self.dates if full is not None else (mention.day, mention.month) in self.day_months

    def has_amount(self, value: float) -> bool:
        return round(value * 100) in self.cents

    def merge(self, other: FactSet) -> None:
        self.dates |= other.dates
        self.day_months |= other.day_months
        self.months |= other.months
        self.cents |= other.cents


_EMPTY = FactSet()


def dates_in(text: str) -> list[DateMention]:
    """:func:`~ordnung.ingest.verify.parse_dates` plus the dates of :data:`_RUN` (``31-12-2027``,
    ``2027/12/31``, ``31|12|2027``), ``31-Dec-2027`` and the loose forms of :data:`_LOOSE_DATES`."""
    mentions = parse_dates(text)
    folded = fold_punctuation(text)
    for match in _RUN.finditer(folded):
        mentions.extend(reading for value in _run_values(folded, match) for reading in value.dates)
    for pattern, reading in _DATE_FORMS:
        for match in pattern.finditer(folded):
            mentions.extend(reading(match))
    return mentions


def months_in(text: str) -> set[tuple[int, int]]:
    """The ``(year, month)`` of every month written without a day (:data:`_MONTH_YEAR`, ``12/2027``)."""
    folded = fold_punctuation(text)
    found = {_month_of(match) for match in _MONTH_YEAR.finditer(folded)}
    found.update(
        value.month for match in _RUN.finditer(folded) for value in _run_values(folded, match) if value.month
    )
    return found


def amounts_in(text: str) -> list[float]:
    """:func:`~ordnung.ingest.verify.amount_matches` (except rates: ``2,90 %``) plus amounts with a
    currency word and the one-decimal or ``.-`` amounts next to a currency."""
    folded = fold_punctuation(text)
    values = [match.value for match in amount_matches(text) if not _PERCENT_AFTER.match(folded, match.end)]
    values += [value for match in _WORD_CURRENCY.finditer(folded) if (value := _word_amount(match))]
    values += [value for _, _, value in _short_amounts(folded)]
    return values


def _word_amount(match: re.Match[str]) -> float | None:
    found = amount_matches(f"{match.group('num')} €")
    return found[0].value if found else None


def _short_amounts(plain: str) -> Iterator[tuple[int, int, float]]:
    """``(start, end, value)`` of each :data:`_SHORT_AMOUNT` with a currency next to it."""
    for match in _SHORT_AMOUNT.finditer(plain):
        start, end = match.span()
        if (
            _CURRENCY_AFTER.match(plain, end) is None
            and _CURRENCY_BEFORE.search(plain, max(0, start - _WINDOW), start) is None
        ):
            continue
        whole = match.group("int")
        if match.group("sep") and match.group("sep") in whole:
            continue  # "1.234.5": the decimal mark cannot also group thousands
        units = int(whole.replace(".", "").replace(",", ""))
        yield start, end, units + (int(match.group("dec")) / 10 if match.group("dec") else 0.0)


def _month_of(match: re.Match[str]) -> tuple[int, int]:
    if match.group("ey"):
        return int(match.group("ey")), 12
    year = int(match.group("y")) if match.group("y") else _year(match.group("ay"))
    return year, MONTH_NUMBERS[match.group("m").casefold()]


def _loose_reading(match: re.Match[str]) -> list[DateMention]:
    month_text = match.group("m")
    month = _ROMAN_MONTHS.get(month_text.upper()) or int(month_text)
    return _valid_mention(match.group(), int(match.group("d")), month, int(match.group("y")))


def _named_reading(match: re.Match[str]) -> list[DateMention]:
    month = MONTH_NUMBERS[match.group("m").casefold()]
    return _valid_mention(match.group(), int(match.group("d")), month, int(match.group("y")))


_DATE_FORMS: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], list[DateMention]]], ...] = (
    (_LOOSE_DATES, _loose_reading),
    (_NAMED_DATES, _named_reading),
)


def _valid_mention(text: str, day: int, month: int, year: int) -> list[DateMention]:
    try:
        date(year, month, day)
    except ValueError:
        return []
    return [DateMention(text, day, month, year)]


@dataclass(frozen=True)
class Value:
    """A date or amount a sentence states: its text as read, where it stands in the reading, and its
    readings (``unreadable``: shaped like a date but not one — never supported; ``month``: a month
    stated without a day, ``(year, month)``)."""

    text: str
    kind: ValueKind
    start: int
    end: int
    dates: tuple[DateMention, ...] = ()
    amount: float | None = None
    month: tuple[int, int] | None = None

    def found_in(self, facts: FactSet) -> bool:
        if self.kind == "amount" and self.amount is not None:
            return facts.has_amount(self.amount)
        if self.month is not None:
            return self.month in facts.months
        return any(facts.has_date(reading) for reading in self.dates)  # a slash date may read two ways


def _is_year(group: str) -> bool:
    return len(group) == 4 and group[:2] in ("19", "20")


def _date_shaped(first: str, second: str, third: str, marks: tuple[str, str]) -> Literal["dmy", "ymd", None]:
    """Whether three digit groups hold a day, a month and a year (``dmy``) or a year, a month and a
    day (``ymd``). A four-digit year makes any short day and month a date (unreadable if it is none).
    A two-digit year needs the same mark twice, never a colon (``10:05:30`` is a time), and the three
    groups must be the whole run (the caller checks): a dot, slash or hyphen makes any short day and
    month a date, another mark only a plausible one — so a time range (``10.30–12.00``) is no date."""
    short = len(first) <= 2 and len(second) <= 2
    if short and len(third) == 4:
        return "dmy"
    if _is_year(first) and len(second) <= 2 and len(third) <= 2:
        return "ymd"
    mark = marks[0]
    if not (short and len(third) == 2 and mark == marks[1] and mark != ":"):
        return None
    return "dmy" if mark in "./-" or (1 <= int(first) <= 31 and 1 <= int(second) <= 12) else None


def _year(group: str) -> int:
    """A year as written: two digits are read as :func:`~ordnung.ingest.verify.parse_dates` does."""
    year = int(group)
    if len(group) != 2:
        return year
    return 2000 + year if year < 70 else 1900 + year


def _run_values(plain: str, match: re.Match[str]) -> list[Value]:
    """The dates or the month a :data:`_RUN` states: every three groups in it shaped like a date (a
    time right after it belongs to it), else a month and a four-digit year when the run is just
    those two (``12/2027``). A run after a label (``Az. 12-3-2027``) states none."""
    offset = match.start()
    if _REFERENCE_BEFORE.search(plain, max(0, offset - 24), offset):
        return []
    groups: list[tuple[str, int, int]] = []
    marks: list[str] = []
    for part in _SPLIT_RUN.finditer(match.group()):
        if part.group("group"):
            digits = part.group("group").translate(_LOOKALIKE_DIGITS)
            groups.append((digits, offset + part.start(), offset + part.end()))
        else:
            marks.append(part.group("mark"))
    values: list[Value] = []
    index = 0
    while index + 2 < len(groups):
        (first, start, _), (second, _, _), (third, _, end) = groups[index : index + 3]
        shape = _date_shaped(first, second, third, (marks[index], marks[index + 1]))
        if shape is None or (shape == "dmy" and len(third) == 2 and len(groups) != 3):
            index += 1  # a two-digit year only as a whole run: "030-12-34-56" is a phone number
            continue
        index += 3
        text = plain[start:end]
        if shape == "ymd":
            readings = _valid_mention(text, int(third), int(second), int(first))
        else:
            year = _year(third)
            readings = _valid_mention(text, int(first), int(second), year)
            if not readings or (marks[index - 3] == "/" and first != second):
                readings += _valid_mention(text, int(second), int(first), year)  # month first
        if not readings:
            values.append(Value(text, "unreadable", start, end))
            continue
        end = _time_after(plain, end)
        values.append(Value(plain[start:end], "date", start, end, dates=tuple(readings)))
    if values or len(groups) != 2 or not (marks[0] in _MONTH_MARKS or not marks[0].isascii()):
        return values
    (first, start, _), (second, _, end) = groups
    month_text, year_text = (second, first) if _is_year(first) and len(second) == 2 else (first, second)
    if _is_year(year_text) and len(month_text) <= 2 and 1 <= int(month_text) <= 12:
        return [Value(plain[start:end], "date", start, end, month=(int(year_text), int(month_text)))]
    return []


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
    """The dates, months and amounts a sentence states, in reading order (``plain``: the sentence as
    read). A one-decimal amount next to a currency (``€ 18.4``) is read before the dates, so it is
    never taken for a date without a year."""
    taken = _Taken(len(plain))
    values = [
        Value(plain[start:end], "amount", start, end, amount=worth)
        for start, end, worth in _short_amounts(plain)
    ]
    for value in values:
        taken.take(value.start, value.end)
    for value in _date_values(plain):
        if value.start < 0 or taken.free(value.start, value.end):
            values.append(value)
            taken.take(value.start, value.end)
    for match in _RUN.finditer(plain):
        for value in _run_values(plain, match):
            if taken.free(value.start, value.end):
                values.append(value)
                taken.take(value.start, value.end)
    for pattern, reading in _DATE_FORMS:
        for match in pattern.finditer(plain):
            if taken.free(*match.span()):
                readings = tuple(reading(match))
                start, end = match.span()
                end = _time_after(plain, end) if readings else end
                kind: ValueKind = "date" if readings else "unreadable"
                values.append(Value(plain[start:end], kind, start, end, dates=readings))
                taken.take(start, end)
    for match in _MONTH_YEAR.finditer(plain):
        if taken.free(*match.span()):
            values.append(Value(match.group(), "date", *match.span(), month=_month_of(match)))
            taken.take(*match.span())
    for amount in amount_matches(plain):
        span = (amount.start, amount.end)
        if not taken.free(*span) or _PERCENT_AFTER.match(plain, amount.end):
            continue
        if not (amount.has_currency or _is_money(plain, *span)):
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
    two readings, which stay one value; a time right after a date belongs to it)."""
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
        end = start + len(raw)
        cursor = end
        end = _time_after(plain, end)
        values.append(Value(plain[start:end], "date", start, end, dates=tuple(group)))
    return values


def _is_money(plain: str, start: int, end: int) -> bool:
    """A bare two-decimal number is money unless it is a label number or a clock time — a time only
    with its unit, after it or after the other end of its range (``10.30 Uhr``, ``8.00–12.00 Uhr``):
    "from 18.36 to 21.50" is money (rule 1). When in doubt, it is money."""
    if _LABEL_BEFORE.search(plain, max(0, start - 24), start):
        return False
    if not _is_clock(_CLOCK.fullmatch(plain, start, end)):
        return True
    if _TIME_AFTER.match(plain, end):
        return False
    partner = _TIME_RANGE_AFTER.match(plain, end)
    return not (_is_clock(partner) and partner is not None and _TIME_AFTER.match(plain, partner.end()))


def _is_clock(match: re.Match[str] | None) -> bool:
    return match is not None and int(match.group("h")) <= 24 and int(match.group("m")) <= 59


# --------------------------------------------------------------------------------------------------
# what this turn's tool results establish
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordValue:
    """A record's own date (a to-do's due date, a contract's cancel-by date) or amount, which the
    note gives (rule 5); ``label`` says what it is (a key of :data:`RECORD_LABELS`)."""

    kind: Literal["date", "amount"]
    label: str
    day: date | None = None
    cents: int = 0
    currency: str = "EUR"


@dataclass
class _Index:
    """Which records hold each date and amount (for the records a value belongs to in rule 5)."""

    dates: dict[date, set[str]] = field(default_factory=lambda: defaultdict(set))
    day_months: dict[tuple[int, int], set[str]] = field(default_factory=lambda: defaultdict(set))
    months: dict[tuple[int, int], set[str]] = field(default_factory=lambda: defaultdict(set))
    cents: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))

    def add(self, record_id: str, facts: FactSet) -> None:
        for day in facts.dates:
            self.dates[day].add(record_id)
        for pair in facts.day_months:
            self.day_months[pair].add(record_id)
        for month in facts.months:
            self.months[month].add(record_id)
        for cents in facts.cents:
            self.cents[cents].add(record_id)

    def holders(self, value: Value) -> set[str]:
        if value.kind == "amount" and value.amount is not None:
            return set(self.cents.get(round(value.amount * 100), ()))
        if value.month is not None:
            return set(self.months.get(value.month, ()))
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
    linked to it; a category's fixed costs count for the contracts of that category); ``letters``:
    those of its letter text (and of the records crediting it); ``unverified``: the amounts of records
    whose record flags them as unverified (they sit in the letter text); ``own``: each record's own
    deadlines and amounts; ``context``: today, which any sentence may state; ``totals``: Ordnung's
    overview totals, which only a sentence without own citations may state; ``person``: values the
    person wrote; ``seen_ids``: every citable id in a record part; ``paragraphs``: the § citations of
    the rules catalog and the record parts.
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
    totals: FactSet = field(default_factory=FactSet)

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
            totals=collector.totals,
        )

    def supports(self, value: Value, cited: Collection[str], *, totals: bool | None = None) -> bool:
        """Policy rule 3: today; an overview total in a sentence with no citation of its own (``totals``,
        by default when ``cited`` is empty); or a value in the record part of a cited record."""
        if value.found_in(self.context):
            return True
        if (not cited if totals is None else totals) and value.found_in(self.totals):
            return True
        return any(value.found_in(self.record.get(ref_id, _EMPTY)) for ref_id in cited)

    def own_holders(self, value: Value, records: Sequence[str]) -> list[str]:
        """Policy rule 3 (last part): the records of ``records`` that ``value`` belongs to — of those
        whose own date or amount it states, the most direct kind (a to-do before the contract, letter
        or person it is linked to: :data:`_HOLDER_ORDER`; a month can be several to-dos' own), in the
        order of ``records``, so the citations the check adds depend on nothing but the answer."""
        holders = [ref for ref in records if any(_states(value, own) for own in self.own.get(ref, ()))]
        ranks = [_HOLDER_ORDER.get(ref.split("_", 1)[0], len(_HOLDER_ORDER)) for ref in holders]
        return [ref for ref, rank in zip(holders, ranks, strict=True) if rank == min(ranks)]

    def in_letter(self, value: Value, cited: Collection[str]) -> bool:
        """Whether the letter text of a cited record holds ``value`` (citing nothing: of any record
        read in this turn) — the note then says to open the letter (rule 5)."""
        if not cited:
            return bool(self.letter_holders(value))
        return any(value.found_in(self.letters.get(ref_id, _EMPTY)) for ref_id in cited)

    def letter_holders(self, value: Value) -> set[str]:
        """The records read in this turn whose letter text holds ``value``."""
        return self.letter_index.holders(value)

    def unverified_amount(self, value: Value, cited: Collection[str]) -> bool:
        """Policy rule 4: the flagged, unverified amount of a cited record."""
        return value.kind == "amount" and any(
            value.found_in(self.unverified.get(ref_id, _EMPTY)) for ref_id in cited
        )

    def said_by_person(self, value: Value) -> bool:
        """Policy rule 4: the person wrote this value in the conversation."""
        return value.found_in(self.person)

    def knows_paragraph(self, number: str, law: str | None) -> bool:
        """A § citation from the catalog or a record part (a bare number: any law with it)."""
        if law is not None:
            return (number, law) in self.paragraphs
        return any(known == number for known, _ in self.paragraphs)

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
        self.totals = FactSet()
        self.seen: set[str] = set()
        self.paragraphs: set[tuple[str, str | None]] = set()

    def walk(self, node: Any) -> None:
        """Collect one record part: its top-level ``today`` is the context, its totals are the totals,
        and a category's fixed costs go to the record parts of the contracts of that category."""
        if isinstance(node, dict):
            self._category_totals(node)
        self._visit(node, frozenset(), key=None, money=False, pool=None, top=True)

    def _category_totals(self, node: Mapping[str, Any]) -> None:
        totals, rows = node.get(CATEGORY_TOTALS), node.get(CATEGORY_ROWS)
        if not isinstance(totals, dict) or not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            ref, total = row.get("id"), totals.get(row.get("category"))
            if isinstance(ref, str) and CITABLE_ID.fullmatch(ref) and isinstance(total, int | float):
                self.record[ref].add_amount(float(total))

    def _visit(
        self,
        node: Any,
        owners: frozenset[str],
        *,
        key: str | None,
        money: bool,
        pool: FactSet | None,
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
                    pool=self._pool(child_key) if top else pool,
                )
        elif isinstance(node, list):
            for value in node:
                self._visit(value, owners, key=key, money=money, pool=pool)
        else:
            self._scalar(node, owners, key=key, money=money, pool=pool)

    def _pool(self, key: str) -> FactSet | None:
        """Where a top-level field that belongs to no record goes (``None``: nowhere)."""
        if key == TODAY_KEY:
            return self.context
        return self.totals if key in TOTAL_KEYS else None

    def _scalar(
        self, value: Any, owners: frozenset[str], *, key: str | None, money: bool, pool: FactSet | None
    ) -> None:
        bags = [self.record[owner] for owner in owners] or ([pool] if pool is not None else [])
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
    """Dates and amounts of letter text; ``text=False``: only the money fields (the filed amounts)."""
    if isinstance(node, dict):
        for child_key, value in node.items():
            _collect_letter(value, bag, money=money or child_key in AMOUNT_MAPS, key=child_key, text=text)
    elif isinstance(node, list):
        for value in node:
            _collect_letter(value, bag, money=money, key=key, text=text)
    elif isinstance(node, str):
        if text:
            bag.add_text(node)
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
    date_in_letter: str
    amount_in_letter: str
    weekdays: tuple[str, ...]
    german: bool

    @property
    def note_prefix(self) -> str:
        """The note's label as stored and printed (``Checked by Ordnung:``)."""
        return NOTE_PREFIX_DE if self.german else NOTE_PREFIX

    def date(self, day: date) -> str:
        weekday = self.weekdays[day.weekday()]
        return f"{weekday} {day:%d.%m.%Y}" if self.german else f"{weekday} {day.day} {day:%b %Y}"

    def amount(self, value: RecordValue) -> str:
        number = f"{value.cents / 100:,.2f}"
        if self.german:
            number = number.replace(",", " ").replace(".", ",").replace(" ", ".")
        return f"{number} €" if value.currency == "EUR" else f"{number} {value.currency}"

    def placeholder(self, kind: ValueKind, *, letter: bool = False) -> str:
        """What stands for a left-out value (``letter``: only a letter's text holds it)."""
        if letter:
            return self.amount_in_letter if kind == "amount" else self.date_in_letter
        return self.amount_left_out if kind == "amount" else self.date_left_out

    def record_value(self, value: RecordValue) -> str:
        """``deadline Wed 21 Oct 2026`` / ``Frist Mi. 21.10.2026``."""
        english, german = RECORD_LABELS.get(value.label, ("due", "fällig"))
        shown = self.date(value.day) if value.day is not None else self.amount(value)
        return f"{german if self.german else english} {shown}"

    def quoted(self, text: str) -> str:
        return f"{self.open_quote}{text}{self.close_quote}"


ENGLISH = Style(
    "“", "”", "[date left out]", "[amount left out]", "[date only in the letter]", "[amount only in the letter]",
    ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), german=False,
)  # fmt: skip
GERMAN = Style(
    "„", "“", "[Datum weggelassen]", "[Betrag weggelassen]", "[Datum nur im Brief]", "[Betrag nur im Brief]",
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
    # (English one, English many, German one, German many); {n} is the count. The label says who
    # checked ("Checked by Ordnung:"), so the texts do not start with "Ordnung" again.
    "removed_value": (
        "Left out 1 sentence: its date or amount isn't in the letter, to-do or contract it refers to.",
        "Left out {n} sentences: their dates or amounts aren't in the letters, to-dos or contracts they "
        "refer to.",
        "1 Satz weggelassen: Sein Datum oder Betrag steht nicht im Brief, in der Aufgabe oder im Vertrag, "
        "auf den er sich bezieht.",
        "{n} Sätze weggelassen: Ihre Daten oder Beträge stehen nicht in den Briefen, Aufgaben oder "
        "Verträgen, auf die sie sich beziehen.",
    ),
    "removed_letter": (
        "Left out 1 sentence: its date or amount is only in a letter's text, which Ordnung has not "
        "confirmed — open the letter to read it.",
        "Left out {n} sentences: their dates or amounts are only in a letter's text, which Ordnung has not "
        "confirmed — open the letter to read them.",
        "1 Satz weggelassen: Sein Datum oder Betrag steht nur im Text eines Briefs, den Ordnung nicht "
        "bestätigt hat – öffnen Sie den Brief, um ihn zu lesen.",
        "{n} Sätze weggelassen: Ihre Daten oder Beträge stehen nur im Text eines Briefs, den Ordnung nicht "
        "bestätigt hat – öffnen Sie den Brief, um sie zu lesen.",
    ),
    "redacted": (
        "1 date or amount is marked “left out”: it isn't in what its sentence refers to.",
        "{n} dates or amounts are marked “left out”: they aren't in what their sentences refer to.",
        "1 Datum oder Betrag ist als „weggelassen“ markiert: Er steht nicht in dem, worauf sich sein Satz "
        "bezieht.",
        "{n} Daten oder Beträge sind als „weggelassen“ markiert: Sie stehen nicht in dem, worauf sich ihre "
        "Sätze beziehen.",
    ),
    "redacted_letter": (
        "1 date or amount is marked “only in the letter”: Ordnung's records don't hold it, so it isn't "
        "shown — open the letter to read it.",
        "{n} dates or amounts are marked “only in the letter”: Ordnung's records don't hold them, so they "
        "aren't shown — open the letter to read them.",
        "1 Datum oder Betrag ist als „nur im Brief“ markiert: Ordnungs Unterlagen enthalten ihn nicht, "
        "deshalb wird er nicht gezeigt – öffnen Sie den Brief, um ihn zu lesen.",
        "{n} Daten oder Beträge sind als „nur im Brief“ markiert: Ordnungs Unterlagen enthalten sie nicht, "
        "deshalb werden sie nicht gezeigt – öffnen Sie den Brief, um sie zu lesen.",
    ),
    "removed_law": (
        "Left out 1 sentence: it names a law that is in neither Ordnung's rules nor its records.",
        "Left out {n} sentences: they name laws that are in neither Ordnung's rules nor its records.",
        "1 Satz weggelassen: Er nennt ein Gesetz, das weder in Ordnungs Regeln noch in seinen Unterlagen "
        "steht.",
        "{n} Sätze weggelassen: Sie nennen Gesetze, die weder in Ordnungs Regeln noch in seinen Unterlagen "
        "stehen.",
    ),
    "added": (
        "Added 1 citation: a sentence without its own states the date or amount of a record the answer "
        "cites elsewhere.",
        "Added {n} citations where a sentence without its own states the date or amount of records the "
        "answer cites elsewhere.",
        "1 Quelle ergänzt: Ein Satz ohne eigene Quelle nennt das Datum oder den Betrag eines Eintrags, den "
        "die Antwort an anderer Stelle zitiert.",
        "{n} Quellen ergänzt, wo ein Satz ohne eigene Quelle Daten oder Beträge von Einträgen nennt, die "
        "die Antwort an anderer Stelle zitiert.",
    ),
    "forged": (
        "Left out 1 line that looked like this note: only Ordnung writes it.",
        "Left out {n} lines that looked like this note: only Ordnung writes it.",
        "1 Zeile weggelassen, die wie dieser Hinweis aussah: Nur Ordnung schreibt ihn.",
        "{n} Zeilen weggelassen, die wie dieser Hinweis aussahen: Nur Ordnung schreibt ihn.",
    ),
}
_QUOTE_NOTES: Mapping[frozenset[str], tuple[str, str]] = {
    frozenset({"letter"}): (
        "Amounts in quotation marks are the letter's, read from a photo or not found on its page; Ordnung "
        "has not confirmed them.",
        "Beträge in Anführungszeichen stammen aus dem Brief, von einem Foto gelesen oder nicht auf seiner "
        "Seite gefunden; Ordnung hat sie nicht bestätigt.",
    ),
    frozenset({"person"}): (
        "Text in quotation marks is your own words; Ordnung has not confirmed it.",
        "Text in Anführungszeichen stammt von Ihnen selbst; Ordnung hat ihn nicht bestätigt.",
    ),
    frozenset({"letter", "person"}): (
        "Text in quotation marks is a letter's unverified amount or your own words; Ordnung has not "
        "confirmed it.",
        "Text in Anführungszeichen ist ein ungeprüfter Betrag aus einem Brief oder stammt von Ihnen selbst; "
        "Ordnung hat ihn nicht bestätigt.",
    ),
}
_RECORD_LEAD = (
    "For the records concerned, Ordnung has on file",
    "Zu den betroffenen Einträgen hat Ordnung gespeichert",
)


def _counted(key: str, count: int, style: Style) -> str | None:
    if not count:
        return None
    one, many, one_de, many_de = _NOTE_TEXTS[key]
    text = (one_de if count == 1 else many_de) if style.german else (one if count == 1 else many)
    return text.format(n=count)


def labelled_note(note: str) -> str:
    """``note`` (without its label) under the label in its own language, as stored and printed."""
    return f"{style_for(note).note_prefix} {note}"


# --------------------------------------------------------------------------------------------------
# checking an answer
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SentenceCheck:
    """The verdict on one sentence that states a date, an amount or a §.

    ``values``: what it states, as read; ``unsupported``: those not in the record part of a record it
    cites (quoted or left out; for a sentence removed for its law, the § citations); ``left_out``:
    those replaced by a placeholder, or every unsupported value of a removed sentence (``in_letter``
    of them only in a letter's text); ``reason``: why a sentence was removed; ``result``: the sentence
    as it stays in the answer (empty when removed; with the citations the check added);
    ``record_refs``: for each value left out or quoted as the person's words, its kind and the records
    it belongs to (whose own values the note gives); ``added``: the ids whose citation the check added.
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
    record_refs: tuple[tuple[ValueKind, frozenset[str]], ...] = ()
    in_letter: int = 0
    added: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckedAnswer:
    """The answer after the check, and the verdict on every sentence that stated something checkable;
    ``forged_notes``: the lines left out because they started like the check's note."""

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

    @property
    def changed(self) -> bool:
        """Whether the check left anything out (a sentence, a value or a line) or added a citation."""
        return bool(
            self.removed or self.redacted or self.forged_notes or any(c.added for c in self.sentences)
        )

    def note(self) -> str | None:
        """The visible note under the answer, with its label, in the answer's language (``None``
        when nothing was changed)."""
        style = self.style
        kept = [check for check in self.sentences if check.verdict != "removed"]
        in_letter = sum(check.in_letter for check in kept)
        parts = [
            _counted("removed_value", sum(1 for c in self.removed if c.reason == "value"), style),
            _counted("removed_letter", sum(1 for c in self.removed if c.reason == "letter"), style),
            _counted("redacted", sum(len(c.left_out) for c in kept) - in_letter, style),
            _counted("redacted_letter", in_letter, style),
            _counted("removed_law", sum(1 for c in self.removed if c.reason == "law"), style),
            _counted("forged", self.forged_notes, style),
            _counted("added", sum(len(c.added) for c in kept), style),
        ]
        sources = frozenset(source for check in self.quoted for source in check.quoted_from)
        if sources:
            english, german = _QUOTE_NOTES[sources]
            parts.append(german if style.german else english)
        if self.record_values:
            lead = _RECORD_LEAD[1] if style.german else _RECORD_LEAD[0]
            parts.append(f"{lead}: {'; '.join(self.record_values)}.")
        shown = [part for part in parts if part]
        return f"{style.note_prefix} {' '.join(shown)}" if shown else None


def check_answer(
    text: str, evidence: TurnEvidence, *, citable: Collection[str], style: Style | None = None
) -> CheckedAnswer:
    """Apply the policy of this module to ``text``; ``citable`` are the ids that may stay cited."""
    style = style or style_for(text)
    answer_cited = tuple(dict.fromkeys(c.id for c in parse_citations(text) if c.id in citable))
    lines: list[str] = []
    checks: list[SentenceCheck] = []
    forged = 0
    lead: list[str] = []  # the records the line leading a list cites (rule 2)
    for unit in _units(text.splitlines()):
        line = unit[0]
        start = _line_prefix(line)
        body = line[len(start) :]
        if not body.strip():
            lines.append(line)
            continue
        continuation = _continuation_prefix(unit[1]) if len(unit) > 1 else ""
        body = "\n".join([body, *(extra[len(_continuation_prefix(extra)) :] for extra in unit[1:])])
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
                cites_own=bool(mine),
            )
            if check is None:
                kept.append(sentence)
                continue
            checks.append(check)
            if check.result:
                kept.append(check.result)
        if kept:
            lines.append(start + " ".join(kept).replace("\n", "\n" + continuation))
        line_ids = list(dict.fromkeys(ref for ids in own for ref in ids))
        if read_as_shown(body).text.rstrip().endswith(":") and (line_ids or not item):
            lead = line_ids
        elif not item:
            lead = []
    return CheckedAnswer(
        "\n".join(lines), tuple(checks), forged, _record_values(checks, evidence, style), style
    )


_FENCE_LINE = re.compile(r"^\s{0,3}(?:```|~~~)")
_HEADING_LINE = re.compile(r"^\s{0,3}#{1,6}\s")
_RULE_LINE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_QUOTE_LINE = re.compile(r"^\s{0,3}>\s?")
_INDENT = re.compile(r"^\s+")
_JUNCTION = 60
"""How much of each line around a soft line break is read to find a value across it."""


def _starts_block(line: str) -> bool:
    return any(
        pattern.match(line) for pattern in (_FENCE_LINE, _HEADING_LINE, _RULE_LINE, _QUOTE_LINE, _LIST_ITEM)
    )


def _continuation_prefix(line: str) -> str:
    """A continuation line's quote marker or indentation (not part of what it shows)."""
    found = _QUOTE_LINE.match(line) or _INDENT.match(line)
    return found.group() if found else ""


def _line_prefix(line: str) -> str:
    """A line's list, heading or quote marker (rule 1: not part of what it shows)."""
    found = _LINE_PREFIX.match(line)
    return found.group(1) if found else ""


def soft_breaks(lines: Sequence[str]) -> list[bool]:
    """``breaks[i]``: line ``i + 1`` continues the Markdown block of line ``i`` — a paragraph, a list
    item (indented continuation) or a quote — so the answer shows the two lines as one text, as the
    web app's Markdown does (policy rule 1)."""
    breaks = [False] * max(0, len(lines) - 1)
    fenced = False
    block: str | None = None
    for index, line in enumerate(lines):
        if _FENCE_LINE.match(line):
            fenced, block = not fenced, None
            continue
        if fenced or not line.strip():
            block = None
            continue
        continues = (
            (block == "quote" and _QUOTE_LINE.match(line) is not None)
            or (block == "paragraph" and not _starts_block(line))
            or (block == "item" and _INDENT.match(line) is not None and not _starts_block(line.strip()))
        )
        if continues:
            breaks[index - 1] = True
            continue
        if _HEADING_LINE.match(line) or _RULE_LINE.match(line):
            block = None
        elif _QUOTE_LINE.match(line):
            block = "quote"
        elif _LIST_ITEM.match(line):
            block = "item"
        else:
            block = "paragraph"
    return breaks


def _units(lines: Sequence[str]) -> list[list[str]]:
    """The lines, each on its own (rule 1) — except that a line continuing its block after a soft line
    break joins the line before it when a value stands across the break (``21.10.`` / ``2027``)."""
    breaks = soft_breaks(lines)
    units: list[list[str]] = []
    for index, line in enumerate(lines):
        if index and breaks[index - 1] and _value_across(lines[index - 1], line, first=len(units[-1]) == 1):
            units[-1].append(line)
        else:
            units.append([line])
    return units


def _value_across(before: str, after: str, *, first: bool) -> bool:
    """Whether a date or amount (with its currency or weekday) spans the break between two lines."""
    head = before[len(_line_prefix(before) if first else _continuation_prefix(before)) :]
    tail = after[len(_continuation_prefix(after)) :]
    left = head[-_JUNCTION:]
    window = f"{left}\n{tail[:_JUNCTION]}"
    reading = read_as_shown(window)
    try:
        cut = reading.offsets.index(len(left))
    except ValueError:
        return False
    for value in stated_values(reading.text):
        begin, end = _widen(reading.text, value.start, value.end, value.kind)
        if value.start >= 0 and begin < cut < end:
            return True
    return False


def _record_values(checks: Sequence[SentenceCheck], evidence: TurnEvidence, style: Style) -> tuple[str, ...]:
    """Rule 5: the own dates and amounts of the records whose value was left out or quoted as the
    person's words, when the answer states none of them (at most :data:`MAX_RECORD_VALUES` of a
    kind), as the note words them."""
    shown: list[str] = []
    stated = [value for check in checks if check.result for value in check.supported]
    for kind in ("date", "amount"):
        records = {
            ref
            for check in checks
            if check.reason != "law"
            for value_kind, refs in check.record_refs
            if (value_kind == "amount") == (kind == "amount")
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
    answer_cited: Sequence[str] = (),
    cites_own: bool | None = None,
) -> SentenceCheck | None:
    """The verdict on one sentence (``None`` when it states no date, amount or §); ``cited`` are the
    citable records it cites or inherits (rule 2); ``answer_cited`` those the whole answer cites, for
    a sentence without citations of its own (rule 3: the first whose own value it states is cited in
    it); ``cites_own``: whether it has citations of its own (default: whether ``cited`` is non-empty) —
    only a sentence without may state an overview total."""
    reading = reading or read_as_shown(sentence)
    plain = reading.text
    values = stated_values(plain)
    laws = list(paragraph_spans(plain))
    if not values and not laws:
        return None
    stated = tuple(value.text for value in values)
    unknown_laws = [
        f"§ {number} {law or ''}".strip()
        for number, law, _, _ in laws
        if not evidence.knows_paragraph(number, law)
    ]
    if unknown_laws:  # a law nobody vouches for can change what the whole sentence means: it goes
        return SentenceCheck(
            sentence, "removed", stated, tuple(unknown_laws), left_out=tuple(unknown_laws), reason="law"
        )
    added: dict[str, None] = {}
    supported: list[bool] = []
    for value in values:
        if evidence.supports(value, cited, totals=None if cites_own is None else not cites_own):
            supported.append(True)
            continue
        holders = evidence.own_holders(value, answer_cited)
        added.update(dict.fromkeys(holders))  # the citations say whose value it is
        supported.append(bool(holders))
    quoted: dict[int, tuple[QuoteSource, frozenset[str]]] = {}
    left: list[int] = []
    letter: set[int] = set()  # left out, but a letter's text holds it: "[date only in the letter]"
    refs: list[tuple[ValueKind, frozenset[str]]] = []
    for index, value in enumerate(values):
        if supported[index]:
            continue
        holders_of = frozenset(cited) if cited else frozenset(evidence.letter_holders(value))
        if evidence.unverified_amount(value, cited):
            quoted[index] = ("letter", frozenset())  # rule 4: the record already gives it as unverified
            continue
        refs.append((value.kind, holders_of))
        if evidence.said_by_person(value):
            quoted[index] = ("person", holders_of)
        else:
            left.append(index)
            if evidence.in_letter(value, cited):
                letter.add(index)
    in_letter = len(letter)
    unsupported = tuple(values[i].text for i in sorted([*quoted, *left]))
    ids = tuple(added)
    if not unsupported:
        cited_result = _add_citations(sentence, ids)
        return SentenceCheck(
            sentence, "kept", stated, result=cited_result, supported=tuple(values), added=ids
        )
    left_texts = tuple(values[i].text for i in left)
    unplaced = any(values[i].start < 0 for i in (*quoted, *left))
    only_letters = bool(left) and in_letter == len(left)
    if unplaced or not (quoted or any(supported) or only_letters):
        reason: RemovalReason = "letter" if only_letters else "value"
        return SentenceCheck(
            sentence,
            "removed",
            stated,
            unsupported,
            left_out=left_texts,
            reason=reason,
            record_refs=tuple(refs),
            in_letter=in_letter,
        )
    result = _apply(sentence, reading, values, quoted, left, letter, style)
    if result is None or _still_shows(result, left_texts):
        return SentenceCheck(
            sentence,
            "removed",
            stated,
            unsupported,
            left_out=left_texts,
            reason="value",
            record_refs=tuple(refs),
            in_letter=in_letter,
        )
    return SentenceCheck(
        sentence,
        "redacted" if left else "quoted",
        stated,
        unsupported,
        result=_add_citations(result, ids),
        left_out=left_texts,
        quoted_from=tuple(dict.fromkeys(source for source, _ in quoted.values())),
        supported=tuple(value for value, ok in zip(values, supported, strict=True) if ok),
        record_refs=tuple(refs),
        in_letter=in_letter,
        added=ids,
    )


def _add_citations(sentence: str, ids: Sequence[str]) -> str:
    """``sentence`` with a citation of each of ``ids`` before its closing punctuation (rule 3)."""
    present = {citation.id for citation in parse_citations(sentence)}
    fresh = [ref for ref in ids if ref not in present]
    if not fresh:
        return sentence
    markers = "".join(f"[{_MARKER_TYPES[ref.split('_', 1)[0]]}:{ref}]" for ref in fresh)
    cut = len(sentence.rstrip())
    while cut and sentence[cut - 1] in _STOPS:
        cut -= 1
    return f"{sentence[:cut].rstrip()} {markers}{sentence[cut:]}"


def _apply(
    sentence: str,
    reading: Reading,
    values: Sequence[Value],
    quoted: Mapping[int, tuple[QuoteSource, frozenset[str]]],
    left: Sequence[int],
    letter: Collection[int],
    style: Style,
) -> str | None:
    """The sentence with its quotes and placeholders (``None`` when two edits would overlap);
    ``letter``: the left-out values a letter's text holds."""
    pairs = _QuotePairs(sentence)
    edits: list[tuple[int, int, str]] = []
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
            edits.append((begin, end, style.placeholder(values[index].kind, letter=index in letter)))
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


def _states(value: Value, record: RecordValue) -> bool:
    if record.kind == "amount":
        return value.amount is not None and round(value.amount * 100) == record.cents
    if value.month is not None:
        return record.day is not None and (record.day.year, record.day.month) == value.month
    return record.day is not None and any(
        reading.as_date() == record.day
        or (reading.year is None and (reading.day, reading.month) == (record.day.day, record.day.month))
        for reading in value.dates
    )


def _widen(sentence: str, begin: int, end: int, kind: ValueKind) -> tuple[int, int]:
    """An amount's span with its currency (``18,43 €``, ``€ 18.43``), a date's with its weekday (``Fri
    31.12.2027``) or the month that starts its range (``Oct–Dec 2026``); only :data:`_WINDOW`
    characters before it are read."""
    window = max(0, begin - _WINDOW)
    if kind == "amount":
        if after := _CURRENCY_AFTER.match(sentence, end):
            end = after.end()
        if before := _CURRENCY_BEFORE.search(sentence, window, begin):
            begin = before.start()
    elif before := _WEEKDAY_BEFORE.search(sentence, window, begin) or _RANGE_START_BEFORE.search(
        sentence, window, begin
    ):
        begin = before.start()
    return begin, end


def split_note(text: str) -> tuple[str, str | None]:
    """A stored answer split into its body and the check's note (without its label, in either
    language).

    The check drops every model-written line that starts like the note, so only the note it appends
    itself can be the last paragraph starting with the label.
    """
    head, sep, tail = text.rpartition("\n\n")
    last = tail if sep else text
    for prefix in (NOTE_PREFIX, NOTE_PREFIX_DE):
        if last.startswith(prefix) and "\n" not in last:
            return (head.rstrip() if sep else ""), last[len(prefix) :].strip()
    return text, None
