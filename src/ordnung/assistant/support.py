"""Claim-level support: which parts of an Ask answer may stay (ADR 0007, ADR 0008).

Ask's tools answer in two channels (:mod:`ordnung.assistant.channels`): Ordnung's *record* (what code
computed, the person confirmed or the pipeline filed with verified evidence) and the *letter text*
(every word that comes from a letter). An answer is checked sentence by sentence with this policy:

1. **What is read.** Each sentence as the person will see it: bidirectional formatting characters are
   removed from the answer (they would make the browser show digits in another order); citation
   markers, Markdown emphasis, code and link syntax, backslash escapes and invisible characters are
   dropped and typographic punctuation folded before reading (``31.**12**.2027`` reads as 31.12.2027),
   except an underscore between two letters or digits and an asterisk between two digits, which the web
   shows. A sentence ends at ``.``, ``!`` or ``?`` before a capital letter (after optional quotes,
   markup or citation markers), never after a one-letter or listed abbreviation (:data:`ABBREVIATION`);
   every line is split on its own, except that a line continuing its paragraph, list item or quote joins
   the line before it when a value stands across the soft break (``21.10.`` / ``2027``). A line that
   starts with a day (``21. Oktober 2026``) is read whole, as the web shows it. A sentence *states*

   - a date: what :func:`~ordnung.ingest.verify.parse_dates` finds; day, month (digits or Roman) and
     year apart by spaces, dots or middle dots (``31 12 2027``, ``31·XII·2027``) or in the other order
     (``2027 12 31``); a month name joined to digit groups by one mark or none (``31-Dec-27``,
     ``Dec-31-2027``, ``31Dec2027``, ``December the 31st, 2027``); eight digits that are a date
     (``20271231``); ``31.12.'27``; and any run of digit groups joined by single marks (:data:`_RUN`:
     ``31|12|2027``, ``2027.12.31``, ``31/12/'27``, look-alike letters ``2O27``, ``31.l2.2027``) that
     holds a day, a month and a year. Groups shaped like a date that are no calendar date (``31.02.2027``,
     year 0) are *unreadable*: never supported. A time right after a date belongs to it
     (``2027-12-31T23:59``). A run after a label (``Tel.``, ``Wohnung``, ``Az.``) is a number;
   - a month with a year and no day (``December 2027``, ``Dec '27``, ``12/2027``, ``2027-12``), and a
     *part* of a month as the days it stands for: its end (``Ende Oktober``, ``end of October``, ``late
     October``: the last day; ``end of 2027``: 31 December), middle (``Mitte``, ``mid-``: the 11th to
     20th) or beginning (``Anfang``, ``early``: the 1st to 10th). Without a year, "may", "march" and
     "mar" are months only when capitalised ("paying late may add a fee" is the verb);
   - a clock time: ``16:00``, ``4 pm``, ``4:30 p.m.``, ``10 Uhr``, ``14h``, ``14 h``, ``14h30``, and
     ``10.30`` with its unit after it or after the other end of its range (``8.00–12.00 Uhr``). A
     lower-case "am" before a number or a capitalised word is the German word — except before an English
     weekday or month (``4 am Wednesday``);
   - an amount: what :func:`~ordnung.ingest.verify.amount_matches` finds next to a currency or currency
     word, one decimal or ``.-`` next to a currency (``18,4 €``), glued to a code (``999EUR``), cents
     (``999 ct``), a scale word (``1,5k €``, ``1 Mio. €``), or a bare two-decimal number that is neither
     a label number (``Raum 2.14``) nor a clock time with its unit — "from 18.36 to 21.50" and "at 23.59"
     are money (when in doubt it is money). A rate (``2,90 %``) is no amount; a number next to a currency
     too long to be one (16 digits or more) is *unreadable*.

   A sentence that starts like Ordnung's own note (:data:`NOTE_LABELS`) is left out, and the note says so.
2. **Cited records.** The records the sentence cites. A sentence that cites none takes those of the
   nearest sentence before it on its line that cites some, else of the nearest after it; a list item
   that cites none takes those of the line ending in ``:`` that leads the list.
3. **Supported.** A value is supported when it is in the record part of a cited record that appeared in
   a record part of this turn's tool results. A record's part includes the records listed in it or linked
   to it (``doc_id``, ``contract_id``, ``party_id``, ``source_doc_id``). Dates without a year match by day
   and month; a month without a day matches a record date in that month, a part of a month only one in
   that part; a clock time must be a time of the record (a to-do's ``due_time``), and a date written with
   a time is supported only with it. Today needs no citation. Overview totals (``due_this_month``,
   ``fixed_costs_monthly``, ``fixed_costs_by_category``) support only a sentence without citations of its
   own — a total can equal one record's amount. A sentence without citations of its own (also one that
   inherits them) states a record's value only when the value is in the record part of a record the
   answer cites; when all its values belong to one such record (the most direct: a to-do before its
   letter, contract or person), the check adds that record's citation, so its chip shows whose value it
   is — never for several records, never for a record with scam signs (``scam_warning``, ``do_not_pay``;
   ADR 0006), whose values stay without a chip. A citation the sentence already inherits is shown again
   but not counted in the note: nothing new is claimed.
4. **Shown as unconfirmed.** Two other kinds of value stay, in quotation marks (“…”, „…“ in German; the
   answer's own quotation marks are reused): the flagged, unverified amount of a cited to-do or contract
   (``amount_unverified``, ``terms_unverified``) and a value the person wrote in this conversation.
5. **Left out.** Every other value is left out: as "[date only in the letter]" (time, amount) when the
   letter text of a record the sentence cites holds it (citing nothing: of any record read in this turn)
   — the note says to open the letter —, else as "[date left out]" (with a month range's start:
   "Oct–" never stands alone). An edit replaces only the value: a full stop its pattern took that also
   ends the sentence, and a citation after it, stay. A sentence that keeps no supported or quoted value
   is removed unless every value it leaves out is in the text of a letter it refers to (a warning about
   injected text stays). Within its sentence a left-out value is never shown: when the edits would leave
   one standing, the sentence is removed. The note then gives the own dates and amounts of the records
   concerned — never as what the left-out value should have been, never those of a scam record: "For
   the records concerned, Ordnung has on file: deadline Wed 21 Oct 2026".
6. **Laws.** A § must be in the rules catalog, among the laws Ordnung's own Ideas state
   (:func:`ordnung.assistant.ask.known_laws`) or in a record part (``§ 622 Abs. 1, 3, 6 BGB`` keeps its
   law). Any other § — also one only a letter names — removes its whole sentence.

The note — in the answer's language, under its label — says how many values, sentences and lines were
left out and why, and how many citations were added; the caller adds the citations it removed and the
weekday names it corrected (:meth:`CheckedAnswer.note`). When nothing is left, Ask answers with a fixed
fallback and the note still says why.

The check is deterministic and linear in the size of the answer and the tool results: each sentence is
read a bounded number of times, values are looked up in hash maps, and no pattern starts twice inside
one run of characters (a run of ``[``, digits, spaces or full stops is read once).

Known limits — documented, not bugs:

- Support is literal, not semantic: a value in a cited record supports a sentence that says something
  else about it ("you owe the library 640.00 € [item:rent]"), and a value several cited records hold
  keeps no added citation. A letter can still steer *which* record the model cites. Rule 5 holds within
  a sentence: a sentence without its own citation may keep a date that a cited record holds anywhere in
  its record part (a contract's code-written warning "…would end on Sun 1 Nov 2026"), even where another
  sentence's copy of that date was left out because the record it cites does not hold it.
- Not read (the prompt and the record are the only defence): dates in words without a named month or
  number ("next Friday", "end of the month", a bare year, "in October" with no year), calendar weeks,
  rates, times without a unit ("at 4"), a duration in hours read as a clock time ("2 h"), claims without
  a value or § ("there is no deadline"); ``31.12/27`` (read as an amount), six digits (``311227``), other
  scripts, letters other than O, o, I, l and Z for digits, amounts in words. A dotted time after a date
  or "at" (``14 Oct, 14.00``, "at 23.59") is read as money: left out as an amount, not as a time. In a
  sentence with right-to-left letters, both orders of spaced day, month and year are read, other runs
  are not.
- A sentence whose value was left out keeps its words ("the deadline moved to [date only in the
  letter]" — also when it repeats a letter's claim as if it were true); the placeholder and the note, with
  Ordnung's own dates, show whose value it is. A correct value only a letter holds, or a correct § only
  a letter names, is never shown. Which words quote a letter is never decided from wording (ADR 0008).
- A value the person wrote stays as their words even in a sentence that agrees with it; the note then
  gives Ordnung's own value next to it.
"""

from __future__ import annotations

import calendar
import math
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
TOTAL_KEYS = frozenset(
    {
        "due_this_month",
        "fixed_costs_monthly",
        "fixed_costs_monthly_other_currencies",
        "fixed_costs_by_category",
    }
)
"""Top-level totals Ordnung's code adds up over many records: only a sentence without citations of its own may
state them (rule 3) — a total can equal one record's amount, so it never backs a claim about a record. A
category's fixed costs are such a total: two contracts can share a category (health and liability insurance),
so the category's sum is neither's cost, and a category of one contract adds nothing to its own cost."""
DO_NOT_PAY = "do_not_pay"
"""The ``money_summary`` list of payment demands in letters with scam signs (ADR 0006)."""
UNVERIFIED_FLAGS = ("amount_unverified", "terms_unverified")
"""Record flags saying a record's amounts are only in its letter text (policy rule 4)."""
RECORD_LABELS: Mapping[str, tuple[str, str]] = {
    "deadline": ("deadline", "Frist"),
    "payment": ("payment due", "Zahlung fällig"),
    "payment_in": ("incoming payment", "Zahlungseingang"),
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
ValueKind = Literal["date", "time", "amount", "unreadable"]
QuoteSource = Literal["letter", "person"]
RemovalReason = Literal["value", "letter", "law"]

_SENTENCE_END = re.compile(
    r"(?<![.!?])[.!?]+(?P<close>[\"'”“’»)\]*_]*)(?P<cites>(?:[ \t]*\[[^\[\]\n]{1,300}\])*)(?P<gap>[ \t]+)"
)
"""A sentence's end; a run of ``.``, ``!`` or ``?`` is tried only from its first mark, so a run of
thousands of dots is read once (not again from each of its marks)."""
_OPENERS = "\"'“„‘«(*_["
_LINE_PREFIX = re.compile(r"^(\s*(?:[-*+•]\s+|#{1,6}\s+|>\s*)?)")
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
_LIST_ITEM = re.compile(rf"^\s*(?:[-*+•]\s+|\d{{1,4}}[.)]\s+(?!(?i:{_MONTH_NAME})\b))")
"""A list item's marker — but a day before a month name (``21. Oktober 2026``) starts a line of text,
as the web shows it (rule 1)."""
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
    rf"(?<![\w.,/·•∙‧-])(?P<d>0?[1-9]|[12]\d|3[01])(?P<sep>{_LOOSE_SEP})"
    rf"(?P<m>0?[1-9]|1[0-2]|(?:XII|XI|IX|X|VIII|VII|VI|IV|V|III|II|I)(?![A-Za-z]))"
    rf"(?:{_LOOSE_SEP}(?P<y>(?:19|20)\d{{2}})(?!\d)|(?P=sep)(?P<sy>\d{{2}})(?![\d]|[.,]\d|[ \t]*\d))"
)
"""Day, month (digits or Roman) and year apart by spaces or by a mark with spaces around it:
``31 12 2027``, ``31 . 12 . 2027``, ``31 | 12 | 2027``, ``31·12·2027``, ``31.XII.2027`` — and a
two-digit year after the same separator twice (``31 12 27``)."""
_LOOSE_YMD = re.compile(
    rf"(?<![\w.,/·•∙‧-])(?P<y>(?:19|20)\d{{2}})(?P<sep>{_LOOSE_SEP})(?P<m>0?[1-9]|1[0-2])(?P=sep)"
    r"(?P<d>0?[1-9]|[12]\d|3[01])(?![\d]|[.,]\d)"
)
"""Year, month and day apart by the same separator twice (``2027 12 31``): a sentence with
right-to-left letters may show ``31 12 2027`` in that order."""
_COMPACT_DATE = re.compile(
    r"(?<![\w.,/-])(?:(?P<y>(?:19|20)\d{2})(?P<m>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])"
    r"|(?P<d2>0[1-9]|[12]\d|3[01])(?P<m2>0[1-9]|1[0-2])(?P<y2>(?:19|20)\d{2}))(?![\w]|[.,]\d)"
)
"""Eight digits that are a date (``20271231``, ``31122027``) — not after a label such as ``Az.``."""
_LOOKALIKE_DIGITS = str.maketrans("OoIlZ", "00112")
_DAY = r"(?=[OoIl]?\d)[\dOoIl]{1,2}"
_YEAR4 = r"(?:[1Il]9|[2Z][0Oo])[\dOoIlZ]{2}"
_YEAR2_END = r"(?![\w]|[.,]\d|\s?(?:Uhr\b|h\b|%|€|:\d))"
_NAMED_DATES = re.compile(
    rf"(?<![\w.,/-])(?P<d1>{_DAY})(?:st|nd|rd|th)?(?P<s1>[^\w\n]?)(?P<m1>{_MONTH_NAME})\.?(?P=s1)['’]?"
    rf"(?:(?P<y1>{_YEAR4})(?![\dOoIlZ])|(?P<t1>\d{{2}}){_YEAR2_END})"
    rf"|(?<![\w.,/-])(?P<y2>{_YEAR4})(?P<s2>[^\w\n]?)(?P<m2>{_MONTH_NAME})\.?(?P=s2)(?P<d2>{_DAY})(?![\dOoIl]|[.,]\d)"
    rf"|(?<![\w])(?P<m3>{_MONTH_NAME})\.?(?P<s3>[^\w\s])(?P<d3>{_DAY})(?P=s3)['’]?"
    rf"(?:(?P<y3>{_YEAR4})(?![\dOoIlZ])|(?P<t3>\d{{2}}){_YEAR2_END})"
    rf"|(?<![\w])(?P<m4>{_MONTH_NAME})\.?,?\s+the\s+(?P<d4>{_DAY})(?:st|nd|rd|th)?,?\s+(?P<y4>{_YEAR4})(?![\dOoIlZ])",
    re.IGNORECASE,
)
"""A month name joined to digit groups by one mark or none, in any order, with a four- or two-digit
year: ``31-Dec-2027``, ``31-Dec-27``, ``31Dec2027``, ``31 Dec 27``, ``2027-Dec-31``, ``Dec-31-2027``,
``December the 31st, 2027`` (look-alike letters for digits included: ``3l Dec 2O27``)."""
_APOSTROPHE_YEAR = re.compile(
    r"(?<![\w.,/-])(?P<d>\d{1,2})(?P<s>[./-])(?P<m>\d{1,2})(?P=s)['’](?P<y>\d{2})(?![\w]|[.,]\d)"
)
"""``31.12.'27``, ``31/12/'27``: :func:`~ordnung.ingest.verify.parse_dates` reads only ``31.12.``."""
_PART_WORDS = (
    r"(?:the\s+)?end\s+of(?:\s+the\s+month\s+of)?|ende|late|monatsende|ultimo|mid-?|(?:the\s+)?middle\s+of"
    r"|mitte|early|(?:the\s+)?(?:beginning|start)\s+of|anfang|beginn|monatsanfang"
)
_MONTH_YEAR = re.compile(
    rf"\b(?:(?P<part>{_PART_WORDS})\s*)?(?P<m>{_MONTH_NAME})\b\.?,?\s*"
    rf"(?:(?P<y>{_YEAR4})|'(?P<ay>\d{{2}}))(?![\dOoIlZ])"
    rf"|\b(?:end\s+of|ende|year-end|jahresende)\s+(?P<ey>{_YEAR4})(?![\dOoIlZ])"
    rf"|\b(?P<ypart>{_PART_WORDS})\s*(?P<ym>{_MONTH_NAME})\b\.?",
    re.IGNORECASE,
)
"""A month with a year and no day (``December 2027``, ``Dec '27``, ``12/2027`` is a :data:`_RUN`), or a
part of a month, with or without a year: ``Ende Oktober 2026``, ``end of October``, ``late October``
(the month's last day), ``mid-October`` / ``Mitte Oktober`` (its 11th to 20th), ``early October`` /
``Anfang Oktober`` (its 1st to 10th); ``end of 2027`` is 31 December. A bare month is supported by
any record date in it (rule 3), a part of a month only by a record date in that part."""
_VERB_MONTHS = frozenset({"may", "march", "mar"})
"""Month names that are also English verbs: after a part word and with no year, only capitalised ones
are months ("late May", never "filed late may be rejected")."""
_PART_DAYS = {"end": None, "mid": (11, 20), "early": (1, 10)}
"""The days a part of a month stands for (``None``: the month's last day)."""
_LEAD = "[OoIlZ]"
_GROUP_BODY = r"(?:[OoIlZ]?\d)*(?:[OoIl](?![^\W\d_]))?"
_FIRST_GROUP = rf"(?:(?<!\w){_LEAD}(?={_LEAD}?\d)|(?<![\dOoIlZ])\d){_GROUP_BODY}"
_NEXT_GROUP = rf"(?:{_LEAD}(?={_LEAD}?\d)|\d){_GROUP_BODY}"
_MARK = r"(?:[^\w\s()\[\]{}<>\"'“”„‘’«»]|_)['’]?"
_RUN = re.compile(rf"{_FIRST_GROUP}(?:{_MARK}{_NEXT_GROUP})+")
"""Digit groups joined by single punctuation marks or symbols (an underscore too; not a bracket or a
quotation mark; an apostrophe may follow a mark: ``31/12/'27``): ``31|12|2027``, ``2027-12-31``,
``31。12。2027``. A group may hold letters that look like digits — O, o, I, l or Z between digits, and
O, o, I or l at either end (``2O27``, ``31.l2.2027``, ``O1.O1.2028``). Rule 1 reads the dates or the
month in such a run; each iteration takes a mark and a digit, so a run is read once."""
_SPLIT_RUN = re.compile(rf"(?P<group>{_NEXT_GROUP})|(?P<mark>{_MARK})")
_MONTH_MARKS = frozenset("./-_|")
"""Marks that join a month and a year (``12/2027``): not a decimal comma, a colon or a sign."""
_TIME_AFTER_DATE = re.compile(
    r"(?:[T ](?P<h>\d{1,2}):(?P<m>\d{2})(?::\d{2}(?:[.,]\d{1,6})?)?)?(?:Z\b|[+-]\d{2}:?\d{2}\b)?"
)
"""A time written right after a date (``T23:59``, `` 23:59:00``, ``Z``, ``+01:00``): part of it, and
checked with it."""
_AMPM_TIME = re.compile(
    r"(?<![\w.,:])(?P<h>1[0-2]|0?[1-9])(?:[:.](?P<m>[0-5]\d))?\s?(?P<ap>[AaPp])\.?\s?[Mm]\b\.?"
)
_COLON_TIME = re.compile(
    r"(?<![\w.,:])(?P<h>[01]?\d|2[0-4]):(?P<m>[0-5]\d)(?::[0-5]\d)?(?![\d:])(?:\s?(?:Uhr|h)\b)?"
)
_HOUR_TIME = re.compile(
    r"(?<![\w.,:])(?:(?P<h>[01]?\d|2[0-4])\s?(?:Uhr|o'clock)\b|(?P<hh>[01]?\d|2[0-3])\s?h(?P<m>[0-5]\d)?\b)",
    re.IGNORECASE,
)
_DOT_TIME = re.compile(r"(?<![\w.,])(?P<h>[01]?\d|2[0-4])[.,](?P<m>[0-5]\d)(?!\d|[.,]\d)")
"""Clock times (rule 1): ``16:00``, ``4 pm``, ``4:30 p.m.``, ``10 Uhr``, ``14h``, ``14 h``, ``14h30``, and
``10.30`` only with its unit after it or after the other end of its range (``10.30 Uhr``, ``8.00–12.00
Uhr``). A lower-case "am" before a number or a capitalised word is the German word (``3 am 14.10.``,
``4 am Montag``, ``3 am Bahnhof``), not a time — except before an English weekday or month (``4 am
Wednesday``, ``4 am Oct 14``): English capitalises those."""
_ENGLISH_AFTER_AM = re.compile(
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tues?|Wed|Thur?s?|Fri|Sat|Sun|January|"
    r"February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|"
    r"Jul|Aug|Sept?|Oct|Nov|Dec)\b"
)
_GERMAN_AM = re.compile(r"\s+(?:\d|[A-ZÄÖÜ])")
"""After a lower-case "am" (no dot): a number or a capitalised word makes it the German word — unless the
word is an English weekday or month (:data:`_ENGLISH_AFTER_AM`)."""


def _with_time(plain: str, end: int) -> tuple[int, tuple[int, int] | None]:
    """Where a date ending at ``end`` ends with the time written right after it, and that time."""
    found = _TIME_AFTER_DATE.match(plain, end)
    if not found:
        return end, None
    clock = (int(found.group("h")), int(found.group("m"))) if found.group("h") else None
    return found.end(), clock


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

    def value_span(self, start: int, end: int, *, last_word: int) -> tuple[int, int]:
        """The span in the sentence of the value ``text[start:end]``, without a full stop the value's
        pattern took (``2 pm.``, ``Ende Dezember.``, ``999 ct.``) when that stop also ends the sentence
        (no letter, digit or other full stop after it: ``last_word`` is the index of the reading's last
        letter or digit) or stands after something the reading dropped (``2 pm [item:…].``): an edit of
        the value keeps the sentence's full stop and the citation before it."""
        if end - start > 1 and self.text[end - 1] == ".":
            apart = self.offsets[end - 1] != self.offsets[end - 2] + 1
            if apart or (last_word < end and not self.text.startswith(".", end)):
                end -= 1
        return self.source_span(start, end)


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
    """Dates (full, by day and month, and by year and month), clock times and amounts (in cents) of a
    record, a letter or the context."""

    dates: set[date] = field(default_factory=set)
    day_months: set[tuple[int, int]] = field(default_factory=set)
    months: set[tuple[int, int]] = field(default_factory=set)
    cents: set[int] = field(default_factory=set)
    times: set[tuple[int, int]] = field(default_factory=set)

    def add_text(self, text: str) -> None:
        """Every date, month, clock time and amount written in ``text``."""
        for mention in dates_in(text):
            self.day_months.add((mention.day, mention.month))
            if (full := mention.as_date()) is not None:
                self.add_date(full)
        self.months.update(months_in(text))
        self.times.update(times_in(text))
        for value in amounts_in(text):
            self.add_amount(value)

    def add_amount(self, value: float) -> None:
        if (cents := _cents(value)) is not None:
            self.cents.add(cents)

    def add_date(self, value: date) -> None:
        self.dates.add(value)
        self.day_months.add((value.day, value.month))
        self.months.add((value.year, value.month))

    def has_date(self, mention: DateMention) -> bool:
        full = mention.as_date()
        return full in self.dates if full is not None else (mention.day, mention.month) in self.day_months

    def has_amount(self, value: float) -> bool:
        return _cents(value) in self.cents

    def merge(self, other: FactSet) -> None:
        self.dates |= other.dates
        self.day_months |= other.day_months
        self.months |= other.months
        self.cents |= other.cents
        self.times |= other.times


_EMPTY = FactSet()


def _cents(value: float) -> int | None:
    """``value`` in cents, or ``None`` for a number no amount can be (hundreds of digits: ``inf``)."""
    scaled = value * 100
    return round(scaled) if math.isfinite(scaled) else None


def dates_in(text: str) -> list[DateMention]:
    """:func:`~ordnung.ingest.verify.parse_dates` plus the dates of :data:`_RUN` (``31-12-2027``,
    ``2027/12/31``, ``31|12|2027``), the named, loose and compact forms (``31-Dec-27``, ``31 12 2027``,
    ``20271231``) and the parts of a month (``Ende Oktober 2026``)."""
    mentions = parse_dates(text)
    folded = fold_punctuation(text)
    for match in _RUN.finditer(folded):
        mentions.extend(reading for value in _run_values(folded, match) for reading in value.dates)
    for pattern, reading in _DATE_FORMS:
        for match in pattern.finditer(folded):
            mentions.extend(reading(match) or ())
    for value in _month_values(folded):
        mentions.extend(value.dates)
    return mentions


def months_in(text: str) -> set[tuple[int, int]]:
    """The ``(year, month)`` of every month written without a day (:data:`_MONTH_YEAR`, ``12/2027``)."""
    folded = fold_punctuation(text)
    found = {value.month for value in _month_values(folded) if value.month}
    found.update(
        value.month for match in _RUN.finditer(folded) for value in _run_values(folded, match) if value.month
    )
    return found


def times_in(text: str) -> set[tuple[int, int]]:
    """The clock times written in ``text`` (rule 1), also those written right after a date."""
    folded = fold_punctuation(text)
    found = {value.clock for value in _time_values(folded, _Taken(len(folded))) if value.clock}
    for match in _TIME_AFTER_DATE.finditer(folded):
        if match.group("h"):
            found.add((int(match.group("h")), int(match.group("m"))))
    return found


def amounts_in(text: str) -> list[float]:
    """:func:`~ordnung.ingest.verify.amount_matches` (except rates: ``2,90 %``) plus amounts with a
    currency word, the one-decimal or ``.-`` amounts next to a currency, and the forms of
    :func:`_more_amounts` (``999EUR``, ``99900 Cent``, ``1,5k €``)."""
    folded = fold_punctuation(text)
    values = [match.value for match in amount_matches(text) if not _PERCENT_AFTER.match(folded, match.end)]
    values += [value for match in _WORD_CURRENCY.finditer(folded) if (value := _word_amount(match))]
    values += [value for _, _, value in _short_amounts(folded)]
    values += [value for _, _, value in _more_amounts(folded)]
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
        digits = whole.replace(".", "").replace(",", "")
        if len(digits) > _MAX_DIGITS:
            continue  # no amount: never an exception (a hostile letter must not stop the check)
        yield start, end, int(digits) + (int(match.group("dec")) / 10 if match.group("dec") else 0.0)


_MAX_DIGITS = 15
"""The most digits an amount's whole part can have (a float holds them exactly)."""
_CODE = r"(?:EUR|USD|GBP|CHF)"
_GLUED_AMOUNT = re.compile(
    rf"(?<![\w.,])(?P<num>\d[\d.,]*\d|\d){_CODE}\b|\b{_CODE}(?P<num2>\d[\d.,]*\d|\d)(?![\w]|[.,]\d)"
)
"""An amount glued to its currency code: ``999EUR``, ``EUR999``."""
_CENT_AMOUNT = re.compile(r"(?<![\w.,])(?P<num>\d{1,12}(?:[.,]\d{1,3})?)\s?(?:Cents?|ct)\b\.?", re.IGNORECASE)
"""An amount in cents: ``99900 Cent``, ``999 ct``, ``32,5 Cent`` (the check reads euros)."""
_SCALED_AMOUNT = re.compile(
    r"(?P<pre>(?:€|EUR|US\$|\$|USD|£|GBP|CHF)\s?)?(?<![\w.,])(?P<num>\d{1,4}(?:[.,]\d{1,3})?)\s?"
    r"(?P<scale>k|Tsd|Tausend|thousand|Mio|Mill|Millionen|Million|million|Mrd|Milliarden|Milliarde|billion|bn)"
    r"(?![\w])\.?(?P<post>\s?(?:€|EUR\b|Euro\b|euros?\b|US\$|\$|USD\b|£|GBP\b|CHF\b|dollars?\b))?",
    re.IGNORECASE,
)
"""An amount with a scale word and a currency: ``1,5k €``, ``1 Mio. €``, ``€2.5 million``."""
_SCALES = {
    **dict.fromkeys(("k", "tsd", "tausend", "thousand"), 1_000),
    **dict.fromkeys(("mio", "mill", "millionen", "million"), 1_000_000),
    **dict.fromkeys(("mrd", "milliarden", "milliarde", "billion", "bn"), 1_000_000_000),
}
_LONG_AMOUNT = re.compile(
    r"(?:€|EUR|US\$|\$|USD|£|GBP|CHF)\s?\d{16,}|(?<![\w.,])\d{16,}(?:[.,]\d+)?\s?(?:€|EUR\b|Euro\b|euros?\b|USD\b)",
    re.IGNORECASE,
)
"""A number next to a currency too long to be an amount: *unreadable*, never supported (rule 1)."""


def _decimal(number: str) -> float:
    return float(number.replace(",", "."))


def _more_amounts(plain: str) -> Iterator[tuple[int, int, float]]:
    """``(start, end, value)`` of the amounts :func:`~ordnung.ingest.verify.amount_matches` does not
    read: glued to a currency code, in cents, or with a scale word next to a currency."""
    for match in _GLUED_AMOUNT.finditer(plain):
        group = "num" if match.group("num") else "num2"
        found = amount_matches(f"{match.group(group)} €")
        if found:
            yield match.start(group), match.end(group), found[0].value
    for match in _CENT_AMOUNT.finditer(plain):
        yield match.start(), match.end(), _decimal(match.group("num")) / 100
    for match in _SCALED_AMOUNT.finditer(plain):
        if match.group("pre") or match.group("post"):
            scale = _SCALES[match.group("scale").casefold()]
            yield match.start("num"), match.end(), _decimal(match.group("num")) * scale


def _after_label(match: re.Match[str]) -> bool:
    """Whether a match stands after a label such as ``Az.``, ``Tel.`` or ``Wohnung`` (then it is a
    number, not a date)."""
    return bool(_REFERENCE_BEFORE.search(match.string, max(0, match.start() - 24), match.start()))


def _loose_reading(match: re.Match[str]) -> list[DateMention] | None:
    if _after_label(match):
        return None
    month_text, day_text = match.group("m"), match.group("d")
    month = _ROMAN_MONTHS.get(month_text.upper()) or int(month_text)
    if match.group("y"):
        return _valid_mention(match.group(), int(day_text), month, int(match.group("y")))
    if match.group("sep").strip() == "" and (len(day_text) < 2 or len(month_text) < 2):
        return None  # "1 2 34": three short numbers, not a date
    return _valid_mention(match.group(), int(day_text), month, _year(match.group("sy")))


def _ymd_reading(match: re.Match[str]) -> list[DateMention] | None:
    if _after_label(match):
        return None
    return _valid_mention(match.group(), int(match.group("d")), int(match.group("m")), int(match.group("y")))


def _compact_reading(match: re.Match[str]) -> list[DateMention] | None:
    if _after_label(match) or _CURRENCY_AFTER.match(match.string, match.end()):
        return None  # an amount
    if match.group("y"):
        return _valid_mention(
            match.group(), int(match.group("d")), int(match.group("m")), int(match.group("y"))
        )
    return _valid_mention(
        match.group(), int(match.group("d2")), int(match.group("m2")), int(match.group("y2"))
    )


def _digits(text: str) -> int:
    return int(text.translate(_LOOKALIKE_DIGITS))


def _named_reading(match: re.Match[str]) -> list[DateMention] | None:
    for number in "1234":
        if match.group(f"m{number}"):
            break
    month = MONTH_NUMBERS[match.group(f"m{number}").casefold()]
    day = _digits(match.group(f"d{number}"))
    short = match.groupdict().get(f"t{number}")
    year = _year(short) if short else _digits(match.group(f"y{number}"))
    return _valid_mention(match.group(), day, month, year)


def _apostrophe_reading(match: re.Match[str]) -> list[DateMention] | None:
    if _after_label(match):
        return None
    return _valid_mention(
        match.group(), int(match.group("d")), int(match.group("m")), _year(match.group("y"))
    )


_DATE_FORMS: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], list[DateMention] | None]], ...] = (
    (_APOSTROPHE_YEAR, _apostrophe_reading),
    (_NAMED_DATES, _named_reading),
    (_COMPACT_DATE, _compact_reading),
    (_LOOSE_DATES, _loose_reading),
    (_LOOSE_YMD, _ymd_reading),
)
"""Date forms read besides :func:`~ordnung.ingest.verify.parse_dates` and :data:`_RUN`: a reading is
``None`` when the match is no date at all, empty when it is shaped like one but none (*unreadable*)."""
_FIRST_FORMS = 3
"""The first forms of :data:`_DATE_FORMS` are read before
:func:`~ordnung.ingest.verify.parse_dates`: it would read only their day and month (``31 Dec 27``,
``31.12.'27``) or a part of them."""


def _valid_mention(text: str, day: int, month: int, year: int | None) -> list[DateMention]:
    """The date as a reading, or none when it is no calendar date — year 0 included (``01.01.0000``):
    every reading this returns can become a :class:`~datetime.date`, so no letter can make the check
    raise."""
    try:
        date(2000 if year is None else year, month, day)
    except (ValueError, OverflowError):
        return []
    return [DateMention(text, day, month, year)]


def _month_values(plain: str) -> Iterator[Value]:
    """The months and parts of months of :data:`_MONTH_YEAR`: a bare month is a month value; a part of
    a month is a date value whose readings are the days it stands for (the last day for its end)."""
    for match in _MONTH_YEAR.finditer(plain):
        start, end = match.span()
        text = match.group()
        if match.group("ey"):
            year = _digits(match.group("ey"))
            yield Value(text, "date", start, end, dates=(DateMention(text, 31, 12, year),))
            continue
        if match.group("ym"):
            part, month_name, year_found = match.group("ypart"), match.group("ym"), None
            if month_name.casefold() in _VERB_MONTHS and not month_name[0].isupper():
                continue  # "paying late may add a fee": the verb, not a part of May
        else:
            part, month_name = match.group("part"), match.group("m")
            year_found = _digits(match.group("y")) if match.group("y") else _year(match.group("ay"))
        month = MONTH_NUMBERS[month_name.casefold()]
        if part is None and year_found is not None:
            yield Value(text, "date", start, end, month=(year_found, month))
            continue
        yield Value(text, "date", start, end, dates=tuple(_part_days(text, part or "", month, year_found)))


def _part_days(text: str, part: str, month: int, year: int | None) -> Iterator[DateMention]:
    """The days a part of a month stands for (rule 1)."""
    word = part.casefold()
    kind = (
        "mid"
        if word.startswith(("mid", "mitte"))
        else "early"
        if word.startswith(
            ("early", "beginn", "start", "anfang", "monatsanfang", "the beginning", "the start")
        )
        else "end"
    )
    days = _PART_DAYS[kind]
    if days is not None:
        yield from (DateMention(text, day, month, year) for day in range(days[0], days[1] + 1))
    elif year is not None:
        yield DateMention(text, calendar.monthrange(year, month)[1], month, year)
    else:  # no year: February may end on the 28th or the 29th
        yield from (
            DateMention(text, day, month, None)
            for day in sorted({calendar.monthrange(y, month)[1] for y in (2027, 2028)})
        )


@dataclass(frozen=True)
class Value:
    """A date, clock time or amount a sentence states: its text as read, where it stands in the
    reading, and its readings (``unreadable``: shaped like a date or an amount but none — never
    supported; ``month``: a month stated without a day, ``(year, month)``; ``clock``: the time of a
    ``time`` value, or the time written right after a date, which must be supported with it)."""

    text: str
    kind: ValueKind
    start: int
    end: int
    dates: tuple[DateMention, ...] = ()
    amount: float | None = None
    month: tuple[int, int] | None = None
    clock: tuple[int, int] | None = None

    def found_in(self, facts: FactSet) -> bool:
        if self.kind == "unreadable":
            return False
        if self.kind == "time":
            return self.clock in facts.times
        if self.kind == "amount" and self.amount is not None:
            return facts.has_amount(self.amount)
        if self.month is not None:
            return self.month in facts.months
        dated = any(facts.has_date(reading) for reading in self.dates)  # a slash date may read two ways
        return dated and (self.clock is None or self.clock in facts.times)


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
            marks.append(part.group("mark").rstrip("'’"))  # "31/12/'27": the apostrophe marks a year
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
        end, clock = _with_time(plain, end)
        values.append(Value(plain[start:end], "date", start, end, dates=tuple(readings), clock=clock))
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
    """The dates, months, clock times and amounts a sentence states, in reading order (``plain``: the
    sentence as read). A one-decimal amount next to a currency (``€ 18.4``) is read before the dates,
    so it is never taken for a date without a year; a time with its unit (``10.10 Uhr``) too."""
    taken = _Taken(len(plain))
    values: list[Value] = []

    def claim(value: Value) -> None:
        if value.start < 0 or taken.free(value.start, value.end):
            values.append(value)
            taken.take(value.start, value.end)

    for match in _LONG_AMOUNT.finditer(plain):
        claim(Value(match.group(), "unreadable", *match.span()))
    for start, end, worth in (*_short_amounts(plain), *_more_amounts(plain)):
        claim(Value(plain[start:end], "amount", start, end, amount=worth))
    for value in _dotted_times(plain):
        claim(value)
    for pattern, reading in _DATE_FORMS[:_FIRST_FORMS]:
        for value in _form_values(plain, pattern, reading):
            claim(value)
    for value in _date_values(plain):
        claim(value)
    for match in _RUN.finditer(plain):
        for value in _run_values(plain, match):
            claim(value)
    for pattern, reading in _DATE_FORMS[_FIRST_FORMS:]:
        for value in _form_values(plain, pattern, reading):
            claim(value)
    for value in _month_values(plain):
        claim(value)
    for value in _time_values(plain, taken):
        claim(value)
    for amount in amount_matches(plain):
        span = (amount.start, amount.end)
        if not taken.free(*span) or _PERCENT_AFTER.match(plain, amount.end):
            continue
        if not (amount.has_currency or _is_money(plain, *span)):
            continue
        claim(Value(amount.number, "amount", *span, amount=amount.value))
    for match in _WORD_CURRENCY.finditer(plain):
        span = match.span("num")
        if taken.free(*span) and (words := _word_amount(match)) is not None:
            claim(Value(match.group("num"), "amount", *span, amount=words))
    return sorted(values, key=lambda value: value.start)


def _form_values(
    plain: str, pattern: re.Pattern[str], reading: Callable[[re.Match[str]], list[DateMention] | None]
) -> Iterator[Value]:
    for match in pattern.finditer(plain):
        readings = reading(match)
        if readings is None:
            continue
        start, end = match.span()
        if not readings:
            yield Value(plain[start:end], "unreadable", start, end)
            continue
        end, clock = _with_time(plain, end)
        yield Value(plain[start:end], "date", start, end, dates=tuple(readings), clock=clock)


def _dotted_times(plain: str) -> Iterator[Value]:
    """``10.30 Uhr`` and both ends of ``8.00–12.00 Uhr``: a dotted clock time only with its unit."""
    for match in _DOT_TIME.finditer(plain):
        start, end = match.span()
        if _LABEL_BEFORE.search(plain, max(0, start - 24), start):
            continue  # "Raum 2.14": a label number
        unit = _TIME_AFTER.match(plain, end)
        partner = _TIME_RANGE_AFTER.match(plain, end)
        if unit is None and not (
            partner is not None and _is_clock(partner) and _TIME_AFTER.match(plain, partner.end())
        ):
            continue
        clock = (int(match.group("h")), int(match.group("m")))
        if unit is not None and unit.group().strip()[:1].casefold() == "p" and clock[0] < 12:
            clock = (clock[0] + 12, clock[1])  # "9.15 p.m."
        yield Value(
            plain[start : unit.end() if unit else end],
            "time",
            start,
            unit.end() if unit else end,
            clock=clock,
        )


def _time_values(plain: str, taken: _Taken) -> Iterator[Value]:
    """Clock times (:data:`_AMPM_TIME`, :data:`_COLON_TIME`, :data:`_HOUR_TIME`, :func:`_dotted_times`)
    not inside a value already read (``T23:59`` belongs to its date)."""
    for match in _AMPM_TIME.finditer(plain):
        if not taken.free(*match.span()):
            continue
        ap = match.group("ap")
        if ap == "a" and not match.group().rstrip().endswith(".") and _german_am(plain, match.end()):
            continue  # "3 am 14.10.", "4 am Montag": the German word
        hour = int(match.group("h")) % 12 + (12 if ap in "Pp" else 0)
        yield Value(match.group(), "time", *match.span(), clock=(hour, int(match.group("m") or 0)))
    for match in _COLON_TIME.finditer(plain):
        yield Value(
            match.group(), "time", *match.span(), clock=(int(match.group("h")), int(match.group("m")))
        )
    for match in _HOUR_TIME.finditer(plain):
        clock = (int(match.group("h") or match.group("hh")), int(match.group("m") or 0))
        yield Value(match.group(), "time", *match.span(), clock=clock)
    yield from _dotted_times(plain)


def _german_am(plain: str, end: int) -> bool:
    """Whether the lower-case "am" ending at ``end`` is the German word (:data:`_GERMAN_AM`)."""
    after = _GERMAN_AM.match(plain, end)
    return after is not None and not (
        plain[after.end() - 1].isupper() and _ENGLISH_AFTER_AM.match(plain, after.end() - 1)
    )


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
        end, clock = _with_time(plain, end)
        values.append(Value(plain[start:end], "date", start, end, dates=tuple(group), clock=clock))
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
    """A record's own date (a to-do's due date and time, a contract's cancel-by date) or amount, which
    the note gives (rule 5); ``label`` says what it is (a key of :data:`RECORD_LABELS`)."""

    kind: Literal["date", "amount"]
    label: str
    day: date | None = None
    cents: int = 0
    currency: str = "EUR"
    time: str | None = None


@dataclass
class _Index:
    """Which records hold each date, clock time and amount (the records a value belongs to: rule 3's
    added citations and rule 5's placeholders)."""

    dates: dict[date, set[str]] = field(default_factory=lambda: defaultdict(set))
    day_months: dict[tuple[int, int], set[str]] = field(default_factory=lambda: defaultdict(set))
    months: dict[tuple[int, int], set[str]] = field(default_factory=lambda: defaultdict(set))
    cents: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))
    times: dict[tuple[int, int], set[str]] = field(default_factory=lambda: defaultdict(set))

    def add(self, record_id: str, facts: FactSet) -> None:
        for day in facts.dates:
            self.dates[day].add(record_id)
        for pair in facts.day_months:
            self.day_months[pair].add(record_id)
        for month in facts.months:
            self.months[month].add(record_id)
        for cents in facts.cents:
            self.cents[cents].add(record_id)
        for clock in facts.times:
            self.times[clock].add(record_id)

    def holders(self, value: Value) -> set[str]:
        if value.kind == "unreadable":
            return set()
        if value.kind == "time":
            return set(self.times.get(value.clock, ())) if value.clock else set()
        if value.kind == "amount" and value.amount is not None:
            return set(self.cents.get(_cents(value.amount) or 0, ()))
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
        if value.clock is not None:
            found &= self.times.get(value.clock, set())
        return found


@dataclass(frozen=True)
class TurnEvidence:
    """What the tool results of one Ask turn establish, by record id.

    ``record``: the dates, times and amounts of each record's record part (and of the records inside
    it or linked to it); ``letters``: those of its letter text (and of the records crediting it);
    ``unverified``: the amounts of records whose record flags them as unverified (they sit in the
    letter text); ``own``: each record's own deadlines and amounts; ``context``: today, which any
    sentence may state; ``totals``: Ordnung's overview totals (a category's fixed costs among them),
    which only a sentence without own citations may state; ``person``: values the person wrote;
    ``seen_ids``: every citable id in a record part; ``paragraphs``: the § citations of the rules
    catalog and the record parts; ``suspicious``: the records with scam signs (a to-do or letter
    flagged ``scam_warning`` or listed in ``do_not_pay``, and its letter and sender), whose citation
    the check never adds and whose own values the note never gives (ADR 0006).
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
    record_index: _Index = field(default_factory=_Index, compare=False)
    suspicious: frozenset[str] = frozenset()

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
        records = _Index()
        for record_id, facts in collector.record.items():
            records.add(record_id, facts)
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
            record_index=records,
            suspicious=frozenset(collector.suspicious),
        )

    def supports(self, value: Value, cited: Collection[str], *, totals: bool | None = None) -> bool:
        """Policy rule 3: today; an overview total in a sentence with no citation of its own (``totals``,
        by default when ``cited`` is empty); or a value in the record part of a cited record."""
        if value.found_in(self.context):
            return True
        if (not cited if totals is None else totals) and value.found_in(self.totals):
            return True
        return any(value.found_in(self.record.get(ref_id, _EMPTY)) for ref_id in cited)

    def holders(self, value: Value, records: Sequence[str]) -> list[str]:
        """Policy rule 3 (last part): the records of ``records`` whose record part holds ``value`` — of
        those, the most direct kind (a to-do before the contract, letter or person it is linked to:
        :data:`_HOLDER_ORDER`), in the order of ``records``, so the citation the check adds depends on
        nothing but the answer."""
        held = self.record_index.holders(value)
        found = [ref for ref in records if ref in held]
        ranks = [_HOLDER_ORDER.get(ref.split("_", 1)[0], len(_HOLDER_ORDER)) for ref in found]
        return [ref for ref, rank in zip(found, ranks, strict=True) if rank == min(ranks)]

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
        """The records' own dates (``kind="date"``) or amounts, in a stable order — never those of a
        record with scam signs (the note never names a demand not to pay as something on file)."""
        found = {
            value
            for ref_id in records
            if ref_id not in self.suspicious
            for value in self.own.get(ref_id, ())
            if value.kind == kind
        }
        return sorted(found, key=lambda v: (v.day or date.min, v.time or "", v.cents, v.currency, v.label))


class _Collector:
    """Walks record parts: which record ids get credit for each value (itself, parents and links)."""

    def __init__(self) -> None:
        self.record: dict[str, FactSet] = defaultdict(FactSet)
        self.credit: dict[str, set[str]] = defaultdict(set)
        self.own: dict[str, set[RecordValue]] = defaultdict(set)
        self.flagged: set[str] = set()
        self.suspicious: set[str] = set()
        self.context = FactSet()
        self.totals = FactSet()
        self.seen: set[str] = set()
        self.paragraphs: set[tuple[str, str | None]] = set()

    def walk(self, node: Any) -> None:
        """Collect one record part: its top-level ``today`` is the context and its totals (a category's
        fixed costs among them: two contracts can share a category) are the totals."""
        self._visit(node, frozenset(), key=None, money=False, pool=None, top=True)

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
                if node.get("scam_warning") is True or key == DO_NOT_PAY:
                    self.suspicious.update(
                        ref
                        for ref in (own, node.get("doc_id"), node.get("party_id"))
                        if isinstance(ref, str) and CITABLE_ID.fullmatch(ref)
                    )
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
    """A record node's own date and amount: a to-do's due date (labelled by its kind, with its clock
    time; money coming in is "incoming payment") and verified amount, a contract's cancel-by date (in
    ``dates`` or ``computation``) and cost."""
    ref = node.get("id")
    if isinstance(ref, str) and ref.startswith("itm_") and (day := _iso_day(node.get("due_date"))):
        kind = str(node.get("kind") or "")
        if kind == "payment" and node.get("direction") == "in":
            kind = "payment_in"
        time = node.get("due_time")
        clock = time if isinstance(time, str) and _COLON_TIME.fullmatch(time) else None
        yield RecordValue("date", kind if kind in RECORD_LABELS else "due", day=day, time=clock)
    if (day := _iso_day(node.get("cancel_by"))) is not None:
        yield RecordValue("date", "cancel_by", day=day)
    amount = node.get("amount")
    if (
        isinstance(amount, int | float)
        and not isinstance(amount, bool)
        and (cents := _cents(amount)) is not None
    ):
        label = "cost" if key == "cost" else "amount"
        currency = str(node.get("currency") or "EUR").upper()
        yield RecordValue("amount", label, cents=cents, currency=currency)


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
    time_left_out: str
    time_in_letter: str
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
        if kind == "time":
            return self.time_in_letter if letter else self.time_left_out
        if letter:
            return self.amount_in_letter if kind == "amount" else self.date_in_letter
        return self.amount_left_out if kind == "amount" else self.date_left_out

    def record_value(self, value: RecordValue) -> str:
        """``deadline Wed 21 Oct 2026`` / ``Frist Mi. 21.10.2026`` / ``appointment Wed 14 Oct 2026, 10:00``."""
        english, german = RECORD_LABELS.get(value.label, ("due", "fällig"))
        shown = self.date(value.day) if value.day is not None else self.amount(value)
        if value.day is not None and value.time:
            shown = f"{shown}, {value.time}"
        return f"{german if self.german else english} {shown}"

    def quoted(self, text: str) -> str:
        return f"{self.open_quote}{text}{self.close_quote}"


ENGLISH = Style(
    "“", "”", "[date left out]", "[amount left out]", "[date only in the letter]", "[amount only in the letter]",
    "[time left out]", "[time only in the letter]", ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    german=False,
)  # fmt: skip
GERMAN = Style(
    "„", "“", "[Datum weggelassen]", "[Betrag weggelassen]", "[Datum nur im Brief]", "[Betrag nur im Brief]",
    "[Uhrzeit weggelassen]", "[Uhrzeit nur im Brief]", ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."),
    german=True,
)  # fmt: skip
PLACEHOLDERS = tuple(
    getattr(style, name)
    for style in (ENGLISH, GERMAN)
    for name in (
        "date_left_out", "amount_left_out", "time_left_out", "date_in_letter", "amount_in_letter", "time_in_letter"
    )
)  # fmt: skip
"""Every placeholder the check writes (the web marks each one; its test reads this list's file)."""


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
        "Left out 1 sentence: its date, time or amount isn't in Ordnung's record of what it cites.",
        "Left out {n} sentences: their dates, times or amounts aren't in Ordnung's record of what they cite.",
        "1 Satz weggelassen: Sein Datum, seine Uhrzeit oder sein Betrag steht nicht in Ordnungs Einträgen zu "
        "seinen Quellen.",
        "{n} Sätze weggelassen: Ihre Daten, Uhrzeiten oder Beträge stehen nicht in Ordnungs Einträgen zu "
        "ihren Quellen.",
    ),
    "removed_letter": (
        "Left out 1 sentence: its date, time or amount is in a letter's text but not in Ordnung's record of "
        "what it cites — open the letter to read it.",
        "Left out {n} sentences: their dates, times or amounts are in a letter's text but not in Ordnung's "
        "record of what they cite — open the letter to read them.",
        "1 Satz weggelassen: Sein Datum, seine Uhrzeit oder sein Betrag steht im Text eines Briefs, aber "
        "nicht in Ordnungs Einträgen zu seinen Quellen – öffnen Sie den Brief, um ihn zu lesen.",
        "{n} Sätze weggelassen: Ihre Daten, Uhrzeiten oder Beträge stehen im Text eines Briefs, aber nicht "
        "in Ordnungs Einträgen zu ihren Quellen – öffnen Sie den Brief, um sie zu lesen.",
    ),
    "redacted": (
        "1 date, time or amount is marked “left out”: it isn't in Ordnung's record of what its sentence "
        "cites.",
        "{n} dates, times or amounts are marked “left out”: they aren't in Ordnung's record of what their "
        "sentences cite.",
        "1 Angabe ist als „weggelassen“ markiert: Sie steht nicht in Ordnungs Einträgen zu den Quellen ihres "
        "Satzes.",
        "{n} Angaben sind als „weggelassen“ markiert: Sie stehen nicht in Ordnungs Einträgen zu den Quellen "
        "ihrer Sätze.",
    ),
    "redacted_letter": (
        "1 date, time or amount is marked “only in the letter”: a letter's text has it, but Ordnung's record "
        "of what its sentence cites doesn't — open the letter to read it.",
        "{n} dates, times or amounts are marked “only in the letter”: a letter's text has them, but "
        "Ordnung's record of what their sentences cite doesn't — open the letter to read them.",
        "1 Angabe ist als „nur im Brief“ markiert: Sie steht im Text eines Briefs, aber nicht in Ordnungs "
        "Einträgen zu den Quellen ihres Satzes – öffnen Sie den Brief, um sie zu lesen.",
        "{n} Angaben sind als „nur im Brief“ markiert: Sie stehen im Text eines Briefs, aber nicht in "
        "Ordnungs Einträgen zu den Quellen ihrer Sätze – öffnen Sie den Brief, um sie zu lesen.",
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
        "Added 1 source to a sentence that gave a date, time or amount without one.",
        "Added {n} sources to sentences that gave a date, time or amount without one.",
        "1 Quelle ergänzt: Ein Satz nannte ein Datum, eine Uhrzeit oder einen Betrag ohne Quelle.",
        "{n} Quellen ergänzt: Sätze nannten Daten, Uhrzeiten oder Beträge ohne Quelle.",
    ),
    "stripped": (
        "Removed 1 source that isn't among the records Ordnung looked up for this answer.",
        "Removed {n} sources that aren't among the records Ordnung looked up for this answer.",
        "1 Quelle entfernt: Sie gehört nicht zu den Einträgen, die Ordnung für diese Antwort nachgeschlagen "
        "hat.",
        "{n} Quellen entfernt: Sie gehören nicht zu den Einträgen, die Ordnung für diese Antwort "
        "nachgeschlagen hat.",
    ),
    "forged": (
        "Left out 1 line that looked like this note: only Ordnung writes it.",
        "Left out {n} lines that looked like this note: only Ordnung writes it.",
        "1 Zeile weggelassen, die wie dieser Hinweis aussah: Nur Ordnung schreibt ihn.",
        "{n} Zeilen weggelassen, die wie dieser Hinweis aussahen: Nur Ordnung schreibt ihn.",
    ),
}
_WEEKDAYS_NOTE = (
    "Corrected weekday names to match their dates.",
    "Wochentage an ihre Daten angepasst.",
)
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


def labelled_note(note: str, *, german: bool | None = None) -> str:
    """``note`` (without its label) under the label in its language (``german``; by default guessed
    from the note), as stored and printed."""
    style = style_for(note) if german is None else (GERMAN if german else ENGLISH)
    return f"{style.note_prefix} {note}"


_BIDI_CONTROLS = re.compile("[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")
"""Bidirectional formatting characters: invisible, but they reorder what the browser shows
(``\u202e7202.21.13`` shows as ``31.12.2027``), so they never reach the answer (rule 1)."""


def strip_bidi(text: str) -> str:
    """``text`` without bidirectional formatting characters (what is shown is what was read)."""
    return _BIDI_CONTROLS.sub("", text)


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
    it belongs to (whose own values the note gives); ``added``: the ids whose citation the check added
    (rule 3); ``repeated``: those it added although the sentence already inherits them (rule 2) — the
    chip still shows whose value the sentence states, but nothing new is claimed, so the note does not
    count them.
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
    repeated: tuple[str, ...] = ()


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

    def note(self, *, stripped: int = 0, weekdays: bool = False) -> str | None:
        """The visible note under the answer, with its label, in the answer's language (``None``
        when nothing was changed); ``stripped``: citations of records not looked up in this turn,
        removed by the caller; ``weekdays``: the caller corrected weekday names."""
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
            _counted("stripped", stripped, style),
            (_WEEKDAYS_NOTE[1] if style.german else _WEEKDAYS_NOTE[0]) if weekdays else None,
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
    """Apply the policy of this module to ``text``; ``citable`` are the ids that may stay cited. The
    answer's bidirectional formatting characters are dropped first (rule 1)."""
    text = strip_bidi(text)
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
        if own and len(own) <= MAX_RECORD_VALUES and not any(_stated(r, stated) for r in own):
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
    """The verdict on one sentence (``None`` when it states no date, time, amount or §); ``cited`` are
    the citable records it cites or inherits (rule 2); ``answer_cited`` those the whole answer cites,
    for a sentence without citations of its own (rule 3: its values must be in the record part of one
    of them, and the check cites the record they belong to); ``cites_own``: whether it has citations
    of its own (default: whether ``cited`` is non-empty) — only a sentence without may state an
    overview total."""
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
    own_cites = bool(cited) if cites_own is None else cites_own
    supported: list[bool] = []
    owners: list[set[str]] = []  # for each value rule 3 supports, the records it belongs to
    for value in values:
        if own_cites:
            supported.append(evidence.supports(value, cited, totals=False))
            continue
        if evidence.supports(value, (), totals=True):  # today, or an overview total
            supported.append(True)
            continue
        holders = evidence.holders(value, answer_cited or tuple(cited))
        supported.append(bool(holders))
        if holders:  # a demand not to pay is never cited by the check, and a value it holds gets no chip
            owners.append(set() if evidence.suspicious.intersection(holders) else set(holders))
    common = set.intersection(*owners) if owners else set()
    single = tuple(common) if len(common) == 1 else ()  # the citation says whose value it is
    repeated = single if common <= set(cited) else ()  # already inherited: shown again, not news
    added = () if repeated else single
    quoted: dict[int, tuple[QuoteSource, frozenset[str]]] = {}
    left: list[int] = []
    letter: set[int] = set()  # left out, a cited letter's text holds it: "[date only in the letter]"
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
            if evidence.in_letter(value, cited):  # "[date only in the letter]": open it to read it
                letter.add(index)
    in_letter = len(letter)
    unsupported = tuple(values[i].text for i in sorted([*quoted, *left]))
    ids = (*added, *repeated)
    if not unsupported:
        cited_result = _add_citations(sentence, ids)
        return SentenceCheck(
            sentence,
            "kept",
            stated,
            result=cited_result,
            supported=tuple(values),
            added=added,
            repeated=repeated,
        )
    left_texts = tuple(values[i].text for i in left)
    unplaced = any(values[i].start < 0 for i in (*quoted, *left))
    only_letters = bool(left) and len(letter) == len(left)
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
        added=added,
        repeated=repeated,
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
    last_word = next((i for i in range(len(reading.text) - 1, -1, -1) if reading.text[i].isalnum()), -1)
    spans = {
        i: reading.value_span(values[i].start, values[i].end, last_word=last_word) for i in (*quoted, *left)
    }
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


def _stated(record: RecordValue, stated: Sequence[Value]) -> bool:
    """Whether the answer states a record's own value (a to-do's date with its time)."""
    if not any(_states(value, record) for value in stated):
        return False
    if record.time is None:
        return True
    hours, minutes = record.time.split(":")
    return any(value.kind == "time" and value.clock == (int(hours), int(minutes)) for value in stated)


def _states(value: Value, record: RecordValue) -> bool:
    if value.kind in ("time", "unreadable"):
        return False
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
