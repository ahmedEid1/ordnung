"""The day a letter was handed to the post, as its own page states it (SPEC § 8 stage 6, § 21; ADR 0026).

An authority's letter counts as delivered on the 4th day "nach der Aufgabe zur Post" (§ 122 Abs. 2 Nr. 1 AO,
§ 41 Abs. 2 S. 1 VwVfG, § 37 Abs. 2 S. 1 SGB X), not after its printed date — and many authorities print the
posting day on the letter, a day or a few later than its date: a field in the header ("Tag der Aufgabe zur Post:
19.10.2026", "Absendedatum: …"), or a sentence ("Dieser Bescheid wurde am 19.10.2026 zur Post gegeben"). The model
may read that day or not; this module reads it in code, on the letter's own text, so that the rules engine may
start the deemed delivery there (:class:`~ordnung.rules.deadlines.PostingStatement`,
:func:`~ordnung.rules.deadlines._stated_posting`). The app (:func:`ordnung.ingest.plan.rule_context`) and the
benchmark's Ordnung condition (``evals.conditions.ordnung_rule_context``) both call :func:`posting_statement`.

The forms are closed: each names what may stand in every place, and a word it does not name refuses it — unknown
means no. A wording outside them leaves the letter's date as the start, the early and safe side. What counts (each
form rows of ``tests/test_posting_day.py``: ``CUES``, ``INFO_BLOCK``, ``TWO_ROWS``, ``SENTENCES`` and
``SENTENCE_PLACES``; the sentences' slots are walked by ``test_an_unlisted_word_in_any_slot_refuses_the_sentence``):

* **A field beside its label** (``field-*``): a posting label (:data:`_LABEL`: "Tag der Aufgabe zur Post",
  "Aufgabe zur Post", "Zur Post gegeben", "Absendedatum", "Versanddatum", "Versandt", "Date of posting", …), then
  only a colon, "am" / "on" or "ist der", a weekday, "den" / "dem", the date and a full stop, and nothing else to
  the end of its line ("Tag der Aufgabe zur Post: Mo., 19.10.2026"). The label starts its text line — or, where the
  page has word boxes, starts its cell in the letterhead's information block on the first page: right of the
  address window and above the salutation by the boxes (:func:`_in_info_block`). So the statute's own label as a
  note ("Aufgabe zur Post am …") is a field too, never a looser sentence.
* **A field under its label** (``TWO_ROWS``): a label ending its line over its value, as a letterhead's
  information block prints a column's label above its value — on the page right under the label (by the words'
  boxes), the last thing on its row and the only words in the label's column there but a weekday ("Mo.,
  19.10.2026"); without boxes, the label alone on its line over the date alone on its line (a weekday allowed).
* **A sentence that records this letter's posting** (``sentence-*``), as a whole clause from its first word to
  its end (:data:`_FORMS`):
  - "Dieser / Der Bescheid", "Dieser / Der Brief", "Dieses / Das Schreiben", or "Dieser <listed compound>"
    ("Dieser Widerspruchsbescheid"), then "wurde am <date> zur Post gegeben / zur Post aufgegeben / der Post
    übergeben / versandt / abgesandt", or "ist am <date> … worden";
  - "Die Aufgabe zur Post erfolgte am <date>" / "ist am <date> erfolgt";
  - the printed note "Zur Post gegeben am <date>";
  - "This letter / notice / decision was posted / mailed / sent on <date>";
  each "am" with an optional weekday and "den" / "dem", the clause ending after its last word (a full stop at
  most). It may open the letter's text, follow a sentence's end, the salutation's line or a line that ends in a
  date (a header's field), or follow a listed heading and its colon (:data:`_HEADING`: "Hinweis:", "Bitte beachten
  Sie:").

Everything else does not count. In particular, by construction and each a row (``NEVER``, ``NO_LONGER``,
``BESIDE_AFTER_WORDS``, ``SUPPOSED``, ``REVIEWED``: every false find of the reviews): a clause that opens
with a verb (a supposition: "Wurde der Bescheid am … zur Post gegeben, …"), goes on after its form (", so gilt
…", "gilt … als bekannt gegeben"), opens with "Wenn", "Falls", "Sofern", "Bei", "Im Fall", "Beispiel:" or any
other word the form does not name; a subject the form does not name (another decision, the person's objection, a
leaflet, a copy for someone else; "der ursprüngliche Bescheid", "der Bescheid für 2024": an adjective or a phrase
inside the subject is an unlisted word); a second posting ("erneut", "ein zweites Mal"), "spätestens", "bis zum",
a plan, the future ("wird … zur Post gegeben", "erfolgt am"), the statute quoted ("gilt am vierten Tag nach
Aufgabe zur Post als bekannt gegeben"); a label in mid-sentence or after other words in its cell ("Bescheid für
2024 - Tag der Aufgabe zur Post: …", "Bestrittener Tag der Aufgabe zur Post"); a table's or the body's row with
other cells; a date with words after it in its cell; a date that reads two ways (03/05/2026) or names no year.

On the field paths a few lists still decide what the layout cannot see, each a row a planted bug fails: the line
above a field (:func:`_another_s`: a plan, an enclosure or a copy, a card or an ID, goods — "Voraussichtlich:",
"Abschrift", "Ersatzausweis" over "Versanddatum: …"; :data:`_DOCUMENT_ABOVE` beside a label: a document named there,
"Bescheid für 2023" over "Aufgabe zur Post: …"), and the other columns of the label's and the value's rows (a
future or a negation, another letter's date, "vom" before the value).

A letter served formally under the VwZG with a proof of its receipt — "Einschreiben mit Rückschein", "gegen
Empfangsbekenntnis", "§ 5 VwZG" — counts from that receipt (§ 4 Abs. 2 S. 1, § 5 VwZG), never from its posting:
the statement says so (``formal``) and the engine keeps the letter's date. A plain Einschreiben does count from
its posting (§ 4 Abs. 2 S. 2 VwZG: the third day after it), as does every letter by ordinary post.

One posting day, or several statements that agree: that day, the first sentence or field as the quote, and the
grounding of the page it stands on (a text layer: ``verified``; a photo's transcription: ``model_read``, if no
text page says it too). Two different days: the earlier is the day, the later ``other`` — the engine then
counts from the earlier and marks the to-do "Please check". Code-side only (no model call).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from ordnung.ingest.conflicts import (
    _ANOTHER_DATE,
    _SALUTATION,
    _TABLE_ROW,
    _UNDER_REACH,
    Box,
    _clauses,
    _one_date,
    _page_text,
    _page_words,
)
from ordnung.ingest.normalize import fold_punctuation
from ordnung.ingest.verify import PageInput, date_spans
from ordnung.models import ExtractedFact, Grounding
from ordnung.rules.deadlines import PostingStatement

#: A weekday before the date, written out or short, as a field often prints it: "Sa.,
#: 19.12.2026", "Mo 19.10.2026", "Sat, 19 Dec 2026".
_DAY = (
    r"(?:(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|monday|tuesday|wednesday|thursday"
    r"|friday|saturday|sunday),?\s*|(?:mo|di|mi|do|fr|sa|so|mon|tue|wed|thu|fri|sat|sun)\.?,?\s+)?"
)
#: The article a date may take after its weekday or "am": "am Montag, den 19.10.2026", "am Montag, dem 19.10.2026".
_DEN = r"(?:(?:den|dem)\s+)?"

# --------------------------------------------------------------------------------------------------
# Fields
# --------------------------------------------------------------------------------------------------

#: The labels of a posting day's field: the statutes' own words ("Tag der Aufgabe zur Post", "Aufgabe zur Post",
#: "Zur Post gegeben"), the labels authorities print for it, and plainer words ("Versandt am", "Aufgegeben am",
#: "Versand:"). Each only where a cell starts (:data:`_FIELD`), so that a sentence about something sent is never
#: read as a field.
_LABEL = (
    r"(?:(?:tag|datum)\s+(?:der\s+(?:aufgabe\s+zur\s+post|postaufgabe|absendung|versendung)|des\s+versand(?:e)?s)"
    r"|datum\s+des\s+postausgang(?:e)?s|aufgabe\s+zur\s+post|aufgegeben\s+zur\s+post|zur\s+post\s+(?:auf)?gegeben"
    r"|postaufgabe|absende(?:datum|tag|vermerk)|versand(?:datum|tag)"
    r"|date\s+of\s+(?:posting|dispatch)|posting\s+date"
    r"|abgesandt|abgesendet|abgeschickt|absendung|aufgegeben\b|versandt|versand\b|versendet|postausgang"
    r"|date\s+posted|posted|mailed)"
)
#: A field beside its label, up to its date: the label starts its line or a column's cell (after a gap of two
#: spaces or more), then only "am" / "on" / "ist der", a colon, a weekday and "den" / "dem" ("Tag der Aufgabe zur
#: Post ist der 19.10.2026", "Versandt am: Mo., 19.10.2026").
_FIELD = re.compile(
    rf"(?:^|\s{{2,}})(?P<label>{_LABEL})(?:\s+(?:am|on|ist\s+der))?\s*:?\s*{_DAY}{_DEN}$", re.IGNORECASE
)
#: After a field's date: at most a full stop, then its line ends.
_FIELD_END = re.compile(r"\s*\.?\s*")
#: A label ending its line, its value on the next: "Tag der Aufgabe zur Post" over "19.10.2026", as a letterhead's
#: information block prints a column's label above its value (read as :func:`ordnung.ingest.conflicts._header_date`
#: reads "Datum"); the label starts its line or a cell.
_FIELD_LINE_END = re.compile(rf"(?:^|\s{{2,}}|\t|[|·])\s*{_LABEL}(?:\s+(?:am|on))?\s*:?\s*$", re.IGNORECASE)
#: A posting label alone in a cell of a row of labels: "Tag der Aufgabe zur Post   Bekanntgabetag".
_FIELD_CELL = re.compile(rf"{_LABEL}(?:\s+(?:am|on))?\s*:?", re.IGNORECASE)
#: Where the letterhead's information block starts (DIN 5008: 125 mm of the page's 210, right of the address
#: window, which ends at 105 mm), as a share of the page's width.
_INFO_BLOCK_LEFT = 0.5

#: A future posting, a request or a negation in a field's rows: "wird … zur Post gegeben", "nicht".
_NOT_DONE = re.compile(
    r"\b(?:wird|werden|würde|würden|soll|sollen|sollte|sollten|voraussichtlich|geben\s+sie|senden\s+sie"
    r"|schicken\s+sie|nicht|kein\w*|will|shall|would|not|never)\b",
    re.IGNORECASE,
)
#: An enclosure or a copy sent: its own posting.
_ENCLOSURE = re.compile(
    r"\b\w*(?:anlage|beilage)\w*|\bbeigefügt\w*|\bbeiliegend\w*|\banbei\b|\bkopie\w*|\babschrift\w*"
    r"|\bdurchschrift\w*|\bzweitschrift\w*|\bgesondert\w*|\bseparat\w*|\berneut\w*|\bnochmals\b|\benclos\w*"
    r"|\battach\w*|\bcop(?:y|ies)\b|\bseparately\b",
    re.IGNORECASE,
)
#: A posting day that is a plan, not a record: "Versanddatum (voraussichtlich)", "Geplante Aufgabe zur Post",
#: "Nächste Aufgabe zur Post", "Der Bescheid folgt".
_PLANNED = re.compile(
    r"\b(?:voraussichtlich\w*|geplant\w*|vorgesehen\w*|nächste\w*|künftig\w*|frühestens|folgt|folgen|demnächst"
    r"|expected|planned|scheduled|next)\b",
    re.IGNORECASE,
)
#: Things an authority sends besides a letter, whose own dispatch a field may date: a health insurance card, an ID,
#: documents, a certificate ("Ersatzausweis" over "Versanddatum: …").
_OBJECT = re.compile(
    r"\w*(?:karte|ausweis|dokument|unterlage|bescheinigung|urkunde|plakette)\w*|\b(?:cards?|documents?|certificates?)\b",
    re.IGNORECASE,
)
#: Goods sent: a shop's dispatch, never a letter's posting.
_GOODS = re.compile(
    r"\b(?:bestellung\w*|ware\w*|artikel|lieferung\w*|paket\w*|päckchen|sendungsnummer|sendungsverfolgung"
    r"|tracking|order\w*|parcel\w*|shipment\w*|package\w*|goods)\b",
    re.IGNORECASE,
)
#: A document named on the line right above a field beside its label: the field may be that document's ("Bescheid
#: für 2023" over "Aufgabe zur Post: …", "Erinnerung" over "Versanddatum: …"), never surely this letter's. Not the
#: way it is sent ("Einschreiben").
_DOCUMENT_ABOVE = re.compile(
    r"\b(?!einschreiben)\w*(?:bescheid|schreiben|brief|mitteilung|aufforderung|erinnerung|mahnung|rechnung|antrag|erklärung)\w*",
    re.IGNORECASE,
)
#: A letter's date label right before a date ("Datum 12.10.2026", "vom 12.10.2026", "dated"): on a posting day's row,
#: a date other than the letter's own makes the row another letter's ("Ihr Schreiben vom 12.10.2026" in the address
#: column beside the value).
_DATED = re.compile(r"(?:\bvom|\bdatum|\bdate|\bdated)\s*:?\s*$", re.IGNORECASE)
#: Where a field's cell ends: a column's gap, a tab, "|" or "·".
_CELL_BREAK = re.compile(r"\s{2,}|\t|[|·]")

# --------------------------------------------------------------------------------------------------
# Sentences: closed forms over closed word classes
# --------------------------------------------------------------------------------------------------

#: The word classes of the sentence forms, each a closed list. A word in none of them refuses every form. The
#: subject's nouns are how a letter calls itself; a compound only after "Dieser" (the letter naming itself: "Dieser
#: Widerspruchsbescheid"), never after "Der" (which may be the decision a Widerspruchsbescheid rules on).
_WORDS: dict[str, tuple[str, ...]] = {
    "DIESER": ("dieser",),
    "DER": ("der",),
    "DIESES": ("dieses",),
    "DAS": ("das",),
    "DIE": ("die",),
    "NOUN_M": ("bescheid", "brief"),
    "NOUN_N": ("schreiben",),
    "COMPOUND_M": (
        "steuerbescheid",
        "widerspruchsbescheid",
        "änderungsbescheid",
        "festsetzungsbescheid",
        "leistungsbescheid",
        "gebührenbescheid",
        "beitragsbescheid",
    ),
    "AUFGABE": ("aufgabe",),
    "ZUR": ("zur",),
    "POST": ("post",),
    "WURDE": ("wurde",),
    "IST": ("ist",),
    "ERFOLGTE": ("erfolgte",),
    "ERFOLGT": ("erfolgt",),
    "WORDEN": ("worden",),
    "AM": ("am",),
    "DEN": ("den", "dem"),
    "WEEKDAY": (
        "montag",
        "dienstag",
        "mittwoch",
        "donnerstag",
        "freitag",
        "samstag",
        "sonntag",
        "mo",
        "di",
        "mi",
        "do",
        "fr",
        "sa",
        "so",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "mon",
        "tue",
        "wed",
        "thu",
        "fri",
        "sat",
        "sun",
    ),
    # the statute's "zur Post gegeben" (§ 122 Abs. 2 AO: "Aufgabe zur Post"), and its plainer participles: a past
    # record that this letter was sent, which no other channel's word ("per E-Mail": unlisted) may qualify
    "GEGEBEN": ("gegeben", "aufgegeben"),
    "UEBERGEBEN": ("übergeben",),
    "VERSANDT": ("versandt", "abgesandt"),
    "THIS": ("this",),
    "NOUN_E": ("letter", "notice", "decision"),
    "WAS": ("was",),
    "POSTED": ("posted", "mailed", "sent"),
    "ON": ("on",),
    "DOT": (".",),
    "COMMA": (",",),
}
_CLASS_OF = {word: name for name, words in _WORDS.items() for word in words}
#: Where the date stands in a clause's tokens.
_DATE_TOKEN = "\x00"
_TOKENS = re.compile(rf"{_DATE_TOKEN}|[^\W\d_]+(?:-[^\W\d_]+)*|\S")

_SUBJECT = r"(?:(?:DIESER|DER) NOUN_M|DIESER COMPOUND_M|(?:DIESES|DAS) NOUN_N)"
_ON_DAY = r"AM (?:WEEKDAY (?:DOT )?(?:COMMA )?)?(?:DEN )?DATE"
_POSTED = r"(?:ZUR POST GEGEBEN|DER POST UEBERGEBEN|VERSANDT)"
#: The sentence forms that record this letter's posting, each a sequence over :data:`_WORDS`' classes that must
#: be the whole clause (a full stop at most after it).
_FORMS: dict[str, re.Pattern[str]] = {
    name: re.compile(rf"{form}(?: DOT)?")
    for name, form in {
        # "Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."
        "wurde": rf"{_SUBJECT} WURDE {_ON_DAY} {_POSTED}",
        # "Der Bescheid ist am Montag, den 19.10.2026 zur Post gegeben worden."
        "ist-worden": rf"{_SUBJECT} IST {_ON_DAY} {_POSTED} WORDEN",
        # "Die Aufgabe zur Post erfolgte am 19.10.2026." — never the present "erfolgt am", which may be a plan
        "aufgabe-erfolgte": rf"DIE AUFGABE ZUR POST ERFOLGTE {_ON_DAY}",
        "aufgabe-ist-erfolgt": rf"DIE AUFGABE ZUR POST IST {_ON_DAY} ERFOLGT",
        # the printed note "Zur Post gegeben am 19.10.2026."
        "note": rf"ZUR POST GEGEBEN {_ON_DAY}",
        # "This letter was posted on 19 October 2026."
        "english": r"THIS NOUN_E WAS POSTED ON (?:WEEKDAY (?:COMMA )?)?DATE",
    }.items()
}

#: A notice's heading that may stand before a sentence form, closed by its colon: "Hinweis:", "Wichtiger Hinweis:",
#: "Bitte beachten Sie:", "Vermerk:", "Hinweis zur Bekanntgabe:". Any other words before a colon ("Beispiel:",
#: "Musterfall:", "Rechenbeispiel:") lead into an example or a supposition: unlisted, so the form is refused.
_HEADING = re.compile(
    r"(?:hinweise?(?:\s+zur\s+(?:bekanntgabe|zustellung|absendung))?|wichtiger\s+hinweis|bitte\s+beachten\s+sie"
    r"|vermerk)\s*:\s*",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------------------------------
# Formal service with a proof of receipt
# --------------------------------------------------------------------------------------------------

#: The letter served under the VwZG with a proof of its receipt: by "Einschreiben mit Rückschein" (§ 4 Abs. 2 S. 1
#: VwZG: the Rückschein proves the day), "gegen Empfangsbekenntnis" (§ 5 Abs. 4 VwZG: the day the person signs), or
#: "§ 5 VwZG" named. Its period runs from that receipt, never from a posting day. A plain Einschreiben is not here:
#: it counts as served on the third day after its posting (§ 4 Abs. 2 S. 2 VwZG), so its posting day is the start
#: as for any letter by post. Only ever an off switch: a "Rückschein" the letter names otherwise (a tip on how to
#: send an objection) keeps the letter's date, the early side.
_SERVED_WITH_RECEIPT = re.compile(
    r"rückschein\w*|empfangsbekenntnis\w*|§\s*5\s+(?:abs(?:atz|\.)\s*\d+\s+(?:s(?:atz|\.)\s*\d+\s+)?)?vwzg",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Found:
    day: date
    quote: str
    grounding: Grounding


def _short(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _cell_bounds(line: str, start: int, end: int) -> tuple[int, int]:
    """Where the cell of ``line`` that holds ``line[start:end]`` starts and ends: from the column's gap, tab, "|" or
    "·" before it to the one after it."""
    breaks = [(m.start(), m.end()) for m in _CELL_BREAK.finditer(line)]
    lo = max((e for s, e in breaks if e <= start), default=0)
    hi = min((s for s, e in breaks if s >= end), default=len(line))
    return lo, hi


def _dates_another(line: str, own: tuple[int, int], letter_date: date | None) -> bool:
    """Whether ``line`` dates another letter than this one, beside the posting day at ``own``: a letter's date label
    or "vom" with another date than the letter's own ("Datum 12.10.2026", "Ihr Schreiben vom 12.10.2026") — another
    column's field about another letter."""
    for start, end, mention in date_spans(line):
        if (start, end) == own or not _DATED.search(line[:start][-20:]):
            continue
        if letter_date is None or mention.as_date() != letter_date:
            return True
    return False


def _another_s(lines: Sequence[str], previous: str) -> bool:
    """Whether a field's rows ``lines`` (its label's and its value's, with the other columns' words on them) or the
    line ``previous`` to them make its posting day something else's: a plan ("voraussichtlich", "geplant",
    "Nächste Aufgabe zur Post"), a future, a request or a negation, an enclosure or a copy ("Anlage", "Abschrift",
    "Zweitschrift"), a card, an ID or documents sent, goods. The label's own cell is closed (:data:`_FIELD`); these
    read what stands around it."""
    text = "\n".join(lines)
    return bool(
        _NOT_DONE.search(text)
        or any(
            pattern.search(text) or pattern.search(previous)
            for pattern in (_PLANNED, _OBJECT, _ENCLOSURE, _GOODS)
        )
    )


def _label_box(words: list[Box], label: str) -> Box | None:
    """Where the words of ``label`` ("Tag der Aufgabe zur Post") stand on the page, as one box — the first run of
    the page's words that spells it."""
    tokens = [t for t in (_token(word) for word in label.split()) if t]
    texts = [_token(box[0]) for box in words]
    for index in range(len(words) - len(tokens) + 1):
        if tokens and texts[index : index + len(tokens)] == tokens:
            run = words[index : index + len(tokens)]
            x0, y0 = min(b[1] for b in run), min(b[2] for b in run)
            return label, x0, y0, max(b[3] for b in run), max(b[4] for b in run)
    return None


def _token(word: str) -> str:
    return fold_punctuation(word).strip(":.,;()|·").casefold()


def _in_info_block(words: list[Box], label: str) -> bool:
    """Whether the posting label ``label`` stands, by the first page's word boxes, in the letterhead's information
    block: it starts right of the address window (:data:`_INFO_BLOCK_LEFT`), and the letter's salutation stands
    below it, starting left of it — so the label is above the letter's body, not in it. Without that evidence, no."""
    box = _label_box(words, label)
    if box is None or box[1] < _INFO_BLOCK_LEFT:
        return False
    texts = [_token(found[0]) for found in words]
    return any(
        _SALUTATION.match(" ".join(texts[index : index + 2])) and found[2] > box[4] and found[1] < box[1]
        for index, found in enumerate(words)
    )


def _under_label(words: list[Box], label: str, value: str) -> bool:
    """Whether the date ``value`` stands on the page right under the posting label ``label`` as its column's value
    (as :func:`ordnung.ingest.conflicts._under` reads "Datum"): the words that spell it, in order, start on a row
    below the label's within ``_UNDER_REACH`` and overlap the run of ALL the label's words — and on that row the
    label's column (every word that does not end left of the label) holds nothing but the date, with at most a
    weekday and "den" before it. So another field's date stacked under the label ("Bekanntgabetag 23.10.2026",
    "Zahlungsfrist …"), a date with words after it ("19.10.2026 Termin 10 Uhr") or two dates in the cell are never
    the posting day; the address column's words to the left are another column's."""
    box = _label_box(words, label)
    tokens = [t for t in (_token(word) for word in value.split()) if t]
    if box is None or not tokens:
        return False
    texts = [_token(found[0]) for found in words]
    spelled = r"\s+".join(map(re.escape, value.split()))
    cell_value = re.compile(rf"{_DAY}{_DEN}{spelled}", re.IGNORECASE)
    for index in range(len(words) - len(tokens) + 1):
        if texts[index : index + len(tokens)] != tokens:
            continue
        run = words[index : index + len(tokens)]
        x0, y0, x1, y1 = (
            min(b[1] for b in run),
            min(b[2] for b in run),
            max(b[3] for b in run),
            max(b[4] for b in run),
        )
        if not (box[2] < y0 < box[4] + _UNDER_REACH and min(box[3], x1) > max(box[1], x0)):
            continue
        # the run's text row: the words whose middle lies within its height; the label's column on it
        row = sorted(
            (found for found in words if y0 <= (found[2] + found[4]) / 2 <= y1 and found[3] > box[1]),
            key=lambda found: found[1],
        )
        if cell_value.fullmatch(" ".join(fold_punctuation(found[0]) for found in row)):
            return True
    return False


def _fields(
    text: str, words: list[Box], grounding: Grounding, letter_date: date | None, *, first: bool
) -> list[_Found]:
    """Posting days in a field (see the module docstring): a label right before one date that reads one way, with
    nothing else to the end of its line, the label starting its line — or, on the ``first`` page with word boxes,
    its cell in the letterhead's information block (:func:`_in_info_block`); or a label ending its line with its
    value on the next (:func:`_under_labels`). Never a table's row, nor a row that dates another letter, plans the
    posting or is about an enclosure, a card, documents or goods (:func:`_another_s`)."""
    found: list[_Found] = []
    lines = fold_punctuation(text).splitlines()
    for index, line in enumerate(lines):
        previous = lines[index - 1] if index else ""
        spans = [(start, end) for start, end, _ in date_spans(line)]
        for start, end in dict.fromkeys(spans):
            field = _FIELD.search(line[:start])
            day = _one_date(line, start, end)
            if field is None or day is None or not _FIELD_END.fullmatch(line[end:]):
                continue
            label = field.start("label")
            # the label starts its text line, or its cell in the first page's information block (no table's row)
            if line[:label].strip() and not (
                first
                and words
                and not _TABLE_ROW.search(line[:label].rstrip())
                and _in_info_block(words, field["label"])
            ):
                continue
            above = (
                _CELL_BREAK.split(previous)[-1] if line[:label].strip() else previous
            )  # the label's column
            if (
                _another_s([line], above)
                or _DOCUMENT_ABOVE.search(above)
                or _dates_another(line, (start, end), letter_date)
            ):
                continue
            found.append(_Found(day, _short(line[label:end]), grounding))
        if index + 1 < len(lines) and not _TABLE_ROW.search(line):
            found += _under_labels(line, lines[index + 1].rstrip(), previous, words, grounding, letter_date)
    return found


def _labels_above(line: str, words: list[Box]) -> list[str]:
    """The posting labels in ``line`` whose value may stand on the next line: one ending the line ("…   Tag der
    Aufgabe zur Post"), and, where the page's word boxes can tell the columns apart, one alone in its cell
    ("Tag der Aufgabe zur Post   Bekanntgabetag")."""
    names = []
    label = _FIELD_LINE_END.search(line)
    if label is not None:
        names.append(line[label.start() :].strip().lstrip("|·").strip())
    if words:
        cells = (cell.strip() for cell in _CELL_BREAK.split(line))
        names += [cell for cell in cells if _FIELD_CELL.fullmatch(cell) and cell not in names]
    return names


def _under_labels(
    line: str, following: str, previous: str, words: list[Box], grounding: Grounding, letter_date: date | None
) -> list[_Found]:
    """Posting days on the line ``following`` a line of labels: a date under its posting label on the page (by
    the words' boxes, :func:`_under_label`), or, without boxes, a label alone on its line over a date alone on its
    line (a weekday and "den" may stand before it: "Mo., 19.10.2026"). Either way the date is the last thing on
    its line, with no other date in its cell and no "vom", "bis", "ab" before it."""
    found = []
    spans = date_spans(following)
    for name in _labels_above(line, words):
        for start, end, _ in spans:
            day = _one_date(following, start, end)
            value = following[start:end]
            lo, hi = _cell_bounds(following, start, end)
            if (
                day is None
                or _ANOTHER_DATE.search(following[:start])
                or following[end:].strip()  # the value ends its line
                or any(lo <= s and e <= hi and (e <= start or s >= end) for s, e, _ in spans)  # a second date
            ):
                continue
            if words:
                if not _under_label(words, name, value):
                    continue  # under another column, or not its column's only value
            elif line.strip() != name or not re.fullmatch(
                rf"\s*{_DAY}{_DEN}{re.escape(value)}\s*", following, re.IGNORECASE
            ):
                continue  # without boxes: a label alone over a date alone on its line (a weekday allowed)
            if _another_s([line, following], previous) or _dates_another(
                following, (start, end), letter_date
            ):
                continue
            found.append(_Found(day, _short(f"{name} {value}"), grounding))
    return found


def _form(clause: str) -> tuple[str, date] | None:
    """The closed sentence form (:data:`_FORMS`) the whole ``clause`` is, and the day it states — ``None`` when a
    word of it is of no listed class, when it holds more or less than one date, or when its date reads two ways."""
    spans = date_spans(clause)
    if len({(start, end) for start, end, _ in spans}) != 1:
        return None
    start, end, _ = spans[0]
    day = _one_date(clause, start, end)
    if day is None:
        return None
    tokens = _TOKENS.findall(f"{clause[:start]} {_DATE_TOKEN} {clause[end:]}")
    classes = " ".join(
        "DATE" if token == _DATE_TOKEN else _CLASS_OF.get(token.casefold(), "?") for token in tokens
    )
    return next(((name, day) for name, form in _FORMS.items() if form.fullmatch(classes)), None)


def _sentences(text: str, grounding: Grounding) -> list[_Found]:
    """Posting days a sentence records for this letter: a whole clause (:func:`ordnung.ingest.conflicts._clauses`)
    that is one of the closed forms (:func:`_form`), after at most a listed heading (:data:`_HEADING`: "Hinweis:").
    A clause runs on over lines that end without a full stop, so the sentence may also start a line of it after the
    salutation's line ("Sehr geehrte Frau Beispiel,"), after a line that ends in a date (a header's field: "Datum
    16.10.2026"), or on a line that opens with a listed heading; never after any other line, whose words may lead
    into it ("Beispiel:", "Wenn")."""
    found: list[_Found] = []
    for clause, _ in _clauses(text):
        lines = clause.strip().split("\n")
        for index in range(len(lines)):
            rest = " ".join(lines[index:]).strip()
            heading = _HEADING.match(rest)
            if index and heading is None and not _ends_a_lead(lines[index - 1]):
                continue
            sentence = rest[heading.end() :].strip() if heading else rest
            if (form := _form(sentence)) is not None:
                found.append(_Found(form[1], _short(sentence), grounding))
                break
    return found


def _ends_a_lead(line: str) -> bool:
    """Whether a sentence may start on the line after ``line`` (:func:`_sentences`): ``line`` is the salutation's,
    ending in a comma, or ends in a date."""
    line = line.rstrip()
    if _SALUTATION.match(line) and line.endswith(","):
        return True
    return any(end == len(line) for _, end, _ in date_spans(line))


def _served_with_receipt(pages: Sequence[PageInput]) -> bool:
    """Whether the letter's pages say it is served under the VwZG with a proof of receipt
    (:data:`_SERVED_WITH_RECEIPT`)."""
    return any(_SERVED_WITH_RECEIPT.search(fold_punctuation(_page_text(page)[0])) for page in pages)


def posting_statement(pages: Sequence[PageInput], letter_date: date | None = None) -> PostingStatement | None:
    """The posting day the letter's ``pages`` state for this letter (see the module docstring); ``None`` without
    pages (nothing was read), an empty statement when they state none. ``letter_date``: the letter's own date as
    read, by which a field's row may date another letter ("Ihr Schreiben vom …" beside the value)."""
    if not pages:
        return None
    found: list[_Found] = []
    for index, page in enumerate(pages):
        text, grounding = _page_text(page)
        found += _fields(text, _page_words(page), grounding, letter_date, first=index == 0)
        found += _sentences(text, grounding)
    formal = _served_with_receipt(pages)
    if not found:
        return PostingStatement(formal=formal)
    days = sorted({statement.day for statement in found})
    first = next(statement for statement in found if statement.day == days[0])
    # a text page that says it too makes it as sure as any verified fact
    sure: Literal["verified", "model_read"] = (
        "verified"
        if any(statement.grounding == "verified" for statement in found if statement.day == days[0])
        else "model_read"
    )
    if len(days) == 1:
        return PostingStatement(day=days[0], quote=first.quote, grounding=sure, formal=formal)
    last = next(statement for statement in found if statement.day == days[-1])
    return PostingStatement(
        day=days[0], quote=first.quote, grounding=sure, other=days[-1], other_quote=last.quote, formal=formal
    )


#: A key fact's label that names a posting day: the field labels above, and the plain English a reading may use
#: ("Posting date", "Date posted", "Mailed on", "Handed to the post"). Never the day of delivery or a deadline.
_READ_LABEL = re.compile(
    rf"{_LABEL}|\bpost(?:ing|ed)\b|\bmail(?:ed|ing)\b|\bdispatch\w*|\bhanded\s+to\s+the\s+post",
    re.IGNORECASE,
)
_NOT_READ_LABEL = re.compile(
    r"zustell\w*|zugang|zugegangen|bekanntgabe|bekannt\s+gegeben|eingang|frist\w*|fällig\w*|deliver\w*|receiv\w*"
    r"|receipt|deemed|served|due|deadline",
    re.IGNORECASE,
)


def read_posting_day(facts: Sequence[ExtractedFact], letter_date: date | None) -> date | None:
    """A posting day later than the letter's date that the reading names among its key facts (a fact labelled as
    one, whose value is one date that reads one way): the earliest, if several. Never a fact about delivery or a
    deadline, and never more than a note: the engine names the deadline it would give and lowers the confidence
    (:func:`ordnung.rules.deadlines._read_posting_note`), it never starts the period there — only code's own find
    on the page does (:func:`posting_statement`)."""
    if letter_date is None:
        return None
    days = []
    for fact in facts:
        label = fold_punctuation(fact.label)
        if not _READ_LABEL.search(label) or _NOT_READ_LABEL.search(label):
            continue
        value = fold_punctuation(fact.value)
        spans = [(start, end) for start, end, _ in date_spans(value)]
        if len(set(spans)) != 1:
            continue
        day = _one_date(value, *spans[0])
        if day is not None and day > letter_date:
            days.append(day)
    return min(days, default=None)
