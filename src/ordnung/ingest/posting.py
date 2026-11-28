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

Where they may stand is closed too. Fields count only in the first page's letterhead: its lines before the
salutation (without a salutation, nothing shows where the letterhead ends: no field). A sentence counts only right
under a notice's heading. And only this letter's pages are read: a later page whose header gives another letter's
date ends the reading (another letter in the same upload has its own posting day).

* **A field beside its label** (``field-*``): a posting label (:data:`_LABEL`: "Tag der Aufgabe zur Post",
  "Aufgabe zur Post", "Zur Post gegeben", "Absendedatum", "Versanddatum", "Versandt", "Date of posting", …), then
  only a colon, "am" / "on" or "ist der", a weekday, "den" / "dem", the date and a full stop, and nothing else to
  the end of its line ("Tag der Aufgabe zur Post: Mo., 19.10.2026"). The label starts its text line and opens a
  field there (:func:`_opens_a_field`: in the information block by the boxes, or with a capital under a closed line
  — empty, or ending in a full stop, a colon, a date or a number, never a line of prose that runs on into it); or,
  where the page has word boxes, it starts its cell in the letterhead's information block: right of the address
  window and above the salutation by the boxes (:func:`_in_info_block`).
* **A field under its label** (``TWO_ROWS``): a label ending its line over its value, as a letterhead's
  information block prints a column's label above its value — on the page right under the label (by the words'
  boxes), the last thing on its row and the only words in the label's column there but a weekday ("Mo.,
  19.10.2026"); without boxes, the label alone on its line over the date alone on its line (a weekday allowed).
  The label opens its field as above.
* **A sentence that records this letter's posting** (``sentence-*``), right under a notice's heading that starts
  its text line (:data:`_HEADING`: "Hinweis:", "Hinweis zur Bekanntgabe:", "Bitte beachten Sie:", "Vermerk:"), the
  rest of the heading's clause from its first word to its end (:data:`_FORMS`):
  - "Dieser Bescheid", "Dieser Brief", "Dieses Schreiben" or "Dieser <listed compound>" ("Dieser
    Widerspruchsbescheid"), then "wurde am <date> zur Post gegeben / zur Post aufgegeben / der Post übergeben /
    versandt / abgesandt", or "ist am <date> … worden";
  - "This letter / notice / decision was posted / mailed / sent on <date>";
  each "am" with an optional weekday and "den" / "dem", the clause ending after its last word (a full stop at
  most). The subject names THIS letter: never plain "Der Bescheid" / "Das Schreiben", and no form without a
  subject ("Die Aufgabe zur Post erfolgte am …"; "Zur Post gegeben am …" is a field of the letterhead).

Everything else does not count. In particular, by construction and each a row (``NEVER``, ``NO_LONGER``,
``BESIDE_AFTER_WORDS``, ``SUPPOSED``, ``REVIEWED``, ``PLACES_NEVER``, ``THIS_LETTER_ONLY``, ``BODY_FIELDS``,
``WRAPPED``: every false find of the reviews): a sentence anywhere but under a heading (after another sentence's
end, the salutation or a line ending in a date: a worked example, a supposition, another person's decision); a
clause that opens with a verb, goes on after its form (", so gilt …"), or holds a word the form does not name (an
adjective or a phrase inside the subject, "erneut", "spätestens", "bis zum", the future); a field in the body, the
remedy notice, a table or on a later page (an example's, a date to post by, a planned dispatch); a label in
mid-sentence, after other words in its cell or under a line of prose that runs on into it; a date with words after
it in its cell; a date that reads two ways (03/05/2026) or names no year. A field's channel is not read: a letter
sent electronically counts from its sending as one by post counts from its posting (§ 122 Abs. 2a AO, § 41 Abs. 2
S. 2 VwVfG, § 37 Abs. 2 S. 2 SGB X: also the fourth day).

On the field paths a few lists still decide what the layout cannot see, each a row a planted bug fails: the line
above a field (:func:`_another_s`: a plan, an enclosure or a copy, a card or an ID, goods, a future or a negation —
"Voraussichtlich:", "Abschrift", "Ihre Bestellung 4711" over "Versanddatum: …"; :data:`_DOCUMENT_ABOVE` beside a
label: a document named there), and the other columns of the label's and the value's rows (a future or a negation,
another letter's date, "vom" before the value).

A letter served formally — by Postzustellungsurkunde (§ 3 VwZG), "Einschreiben mit Rückschein", "gegen
Empfangsbekenntnis", under § 5 VwZG, the ZPO's service sections or a Land's service law (:data:`_SERVED_FORMALLY`)
— counts from its service, never from its posting: the statement says so (``formal``) and the engine keeps the
letter's date. A plain Einschreiben does count from its posting (§ 4 Abs. 2 S. 2 VwZG: "am vierten Tag nach der
Aufgabe zur Post"), as does every letter by ordinary post.

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
    header,
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
    r"\b(?:wird|werden|würde|würden|soll|sollen|sollte|sollten|geben\s+sie|senden\s+sie"
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
#: subject names THIS letter: "Dieser" / "Dieses" / "This" and the noun a letter calls itself by. Never plain "Der" /
#: "Das" ("Der Bescheid", "Das Schreiben" may be another decision's, an example's or the reader's own letter: "der" is
#: listed only for "der Post übergeben"), and no subjectless form ("Die Aufgabe zur Post erfolgte am …", "Zur Post
#: gegeben am …": they name no letter).
_WORDS: dict[str, tuple[str, ...]] = {
    "DIESER": ("dieser",),
    "DER": ("der",),
    "DIESES": ("dieses",),
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
    "ZUR": ("zur",),
    "POST": ("post",),
    "WURDE": ("wurde",),
    "IST": ("ist",),
    "WORDEN": ("worden",),
    "AM": ("am",),
    "DEN": ("den", "dem"),
    "WOCHENTAG": (
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
    ),
    "WEEKDAY": (
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

_SUBJECT = r"(?:DIESER (?:NOUN_M|COMPOUND_M)|DIESES NOUN_N)"
_ON_DAY = r"AM (?:WOCHENTAG (?:DOT )?(?:COMMA )?)?(?:DEN )?DATE"
_POSTED = r"(?:ZUR POST GEGEBEN|DER POST UEBERGEBEN|VERSANDT)"
#: The sentence forms that record this letter's posting, each a sequence over :data:`_WORDS`' classes that must
#: be the whole clause (a full stop at most after it).
_FORMS: dict[str, re.Pattern[str]] = {
    name: re.compile(rf"{form}(?: DOT)?")
    for name, form in {
        # "Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."
        "wurde": rf"{_SUBJECT} WURDE {_ON_DAY} {_POSTED}",
        # "Dieser Bescheid ist am Montag, den 19.10.2026 zur Post gegeben worden."
        "ist-worden": rf"{_SUBJECT} IST {_ON_DAY} {_POSTED} WORDEN",
        # "This letter was posted on 19 October 2026."
        "english": r"THIS NOUN_E WAS POSTED ON (?:WEEKDAY (?:COMMA )?)?DATE",
    }.items()
}

#: The heading of a notice, the one place a sentence form may stand: it starts its text line and is closed by its
#: colon ("Hinweis:", "Wichtiger Hinweis:", "Bitte beachten Sie:", "Vermerk:", "Hinweis zur Bekanntgabe:"), and the
#: form follows it on its line or the next. A notice under such a heading records a fact about this letter. Any other
#: words before the form ("Beispiel:", "Rechenbeispiel.", another sentence, a line that ends in a date) may lead into
#: an example, a supposition or another letter's story: the form is refused there.
_HEADING = re.compile(
    r"(?:hinweise?(?:\s+zur\s+(?:bekanntgabe|zustellung|absendung))?|wichtiger\s+hinweis|bitte\s+beachten\s+sie"
    r"|vermerk)\s*:\s*",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------------------------------
# Formal service with a proof of receipt
# --------------------------------------------------------------------------------------------------

#: The letter served formally, in any of the ways the page may name it. Its period runs from the service, never from
#: a posting day: by Postzustellungsurkunde (§ 3 VwZG with §§ 177 to 182 ZPO: the day the postman hands it over, which
#: the envelope records; "PZU" for short), by "Einschreiben mit Rückschein" (§ 4 Abs. 2 S. 1 VwZG: the Rückschein
#: proves the day), "gegen Empfangsbekenntnis" or "gegen EB" (§ 5 Abs. 4 VwZG: the day the person signs), under § 3
#: or § 5 VwZG cited in any way ("§ 5 Abs. 4 S. 1 VwZG", "§§ 5, 10 VwZG", "Paragraph 5 VwZG"), under the ZPO's
#: service sections (§§ 173 to 178 ZPO, "§§ 177 ff. ZPO"), under a Land's service law ("Landeszustellungsgesetz",
#: "LZG") or "förmlich zugestellt". A plain Einschreiben is not here: it counts as served on the fourth day after its
#: posting (§ 4 Abs. 2 S. 2 VwZG: "am vierten Tag nach der Aufgabe zur Post"), so its posting day is the start as for
#: any letter by post. Only ever an off switch, so it may be broad: a word the letter uses in another sense (a tip on
#: how to send an objection with a Rückschein) keeps the letter's date, the early side.
_SERVED_FORMALLY = re.compile(
    r"rückschein\w*|empfangsbekenntnis\w*|\bgegen\s+eb\b|(?:post)?zustellungsurkunde\w*|\bpzu\b"
    r"|(?:§§?|paragraph)\s*[35]\b[^\n]{0,24}vwzg|förmlich\w*\s+(?:zu(?:zu)?stell|zugestellt)\w*"
    r"|§§?\s*17[3-8]\b[^\n]{0,16}zpo|landeszustellungs\w*|\blzg\b",
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


def _opens_a_field(label: str, previous: str, words: list[Box]) -> bool:
    """Whether a posting label that starts its text line opens a field there, not a wrapped line of prose: by the
    first page's word boxes it stands in the letterhead's information block (:func:`_in_info_block`); or it starts
    with a capital, as a field's label does, and the line ``previous`` to it is closed — empty, or ending in a full
    stop, a colon, a date or a number ("Steuernummer 123/456/78901"). A line that ends in a word, a comma or a hyphen
    may run on into the label ("Ihr Einspruch ist nur dann rechtzeitig, wenn er bei" over "Aufgabe zur Post am …"):
    no."""
    if words and _in_info_block(words, label):
        return True
    previous = previous.rstrip()
    # a date ends in a number or a full stop ("19.10."), so it needs no test of its own
    return label[:1].isupper() and (not previous or previous[-1] in ".:" or previous[-1].isdigit())


def _another_s(lines: Sequence[str], previous: str) -> bool:
    """Whether a field's rows ``lines`` (its label's and its value's, with the other columns' words on them) or the
    line ``previous`` to them make its posting day something else's: a plan ("voraussichtlich", "geplant",
    "Nächste Aufgabe zur Post"), a future, a request or a negation, an enclosure or a copy ("Anlage", "Abschrift",
    "Zweitschrift"), a card, an ID or documents sent, goods. The label's own cell is closed (:data:`_FIELD`); these
    read what stands around it."""
    text = "\n".join(lines)
    return any(
        pattern.search(text) or pattern.search(previous)
        for pattern in (_NOT_DONE, _PLANNED, _OBJECT, _ENCLOSURE, _GOODS)
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


def _letterhead(lines: list[str]) -> list[str]:
    """The lines of a page's letterhead: those before its salutation ("Sehr geehrte Frau Beispiel,"). Without a
    salutation there is no evidence where the letterhead ends and the body starts, so none."""
    return next((lines[:index] for index, line in enumerate(lines) if _SALUTATION.match(line.strip())), [])


def _fields(text: str, words: list[Box], grounding: Grounding, letter_date: date | None) -> list[_Found]:
    """Posting days in a field of the first page's letterhead (see the module docstring): only its lines before the
    salutation (:func:`_letterhead`) — never the body, the remedy notice, a table or a footer, where a field may be
    an example's, a date to post by or a planned dispatch. There, a label right before one date
    that reads one way, with nothing else to the end of its line, the label opening a field at its line's start
    (:func:`_opens_a_field`) or starting its cell in the information block (:func:`_in_info_block`); or a label
    ending its line with its value on the next (:func:`_under_labels`). Never a row that dates another letter, plans
    the posting or is about an enclosure, a card, documents or goods (:func:`_another_s`)."""
    found: list[_Found] = []
    lines = _letterhead(fold_punctuation(text).splitlines())
    for index, line in enumerate(lines):
        previous = lines[index - 1] if index else ""
        spans = [(start, end) for start, end, _ in date_spans(line)]
        for start, end in dict.fromkeys(spans):
            field = _FIELD.search(line[:start])
            day = _one_date(line, start, end)
            if field is None or day is None or not _FIELD_END.fullmatch(line[end:]):
                continue
            label = field.start("label")
            if line[:label].strip():
                # a label starting its cell: only in the information block by the boxes (no table's row)
                if not (
                    words
                    and not _TABLE_ROW.search(line[:label].rstrip())
                    and _in_info_block(words, field["label"])
                ):
                    continue
                above = _CELL_BREAK.split(previous)[-1]  # the label's column
            elif _opens_a_field(field["label"], previous, words):
                above = previous
            else:
                continue
            if (
                _another_s([line], above)
                or _DOCUMENT_ABOVE.search(above)
                or _dates_another(line, (start, end), letter_date)
                # the label's column right above dates another letter ("Ihre Nachricht vom 12.10.2026" over
                # "Abgesandt am: …"): the field may be that letter's
                or _dates_another(_CELL_BREAK.split(above)[-1], (-1, -1), letter_date)
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
        if line.lstrip().startswith(name):
            if not _opens_a_field(name, previous, words):
                continue  # a wrapped line of prose, not a field's label
        elif not _in_info_block(words, name):
            continue  # a cell's label only in the information block by the boxes
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
            elif not re.fullmatch(rf"\s*{_DAY}{_DEN}{re.escape(value)}\s*", following, re.IGNORECASE):
                # without boxes: a date alone on its line (a weekday allowed), under a label alone on its line (a
                # label in a cell needs the boxes, above)
                continue
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
    """Posting days a sentence records for this letter: a closed form (:func:`_form`) right under a notice's heading
    (:data:`_HEADING`) that starts its text line — the rest of the heading's clause
    (:func:`ordnung.ingest.conflicts._clauses`), on the heading's line or the next, is the whole form. Nowhere else:
    after another sentence's end, after the salutation or after a line that ends in a date, the words before may
    lead into it ("Ein Beispiel.", "Angenommen, …", "Ihr Ehemann erhält einen eigenen Bescheid.")."""
    found: list[_Found] = []
    for clause, _ in _clauses(text):
        # where the clause starts: the text's start, or after a sentence's end that a line break follows
        lead = clause[: len(clause) - len(clause.lstrip())]
        lines = clause.strip().split("\n")
        for index, line in enumerate(lines):
            if index == 0 and lead and "\n" not in lead:
                continue  # the clause starts in mid-line, after another sentence's end
            heading = _HEADING.match(line)
            if heading is None:
                continue
            sentence = " ".join([line[heading.end() :], *lines[index + 1 :]]).strip()
            if (form := _form(sentence)) is not None:
                found.append(_Found(form[1], _short(sentence), grounding))
                break
    return found


def _served_formally(pages: Sequence[PageInput]) -> bool:
    """Whether the letter's pages say it is served formally (:data:`_SERVED_FORMALLY`): every page of the upload, as
    the switch only ever keeps the letter's date."""
    return any(_SERVED_FORMALLY.search(fold_punctuation(_page_text(page)[0])) for page in pages)


#: A date in a page's header after a letter's date label ("Datum 22.10.2026", "Datum: 22.10.2026", "Date 22 Oct
#: 2026"): the date of the letter that page starts.
_PAGE_DATED = re.compile(r"\b(?:datum|date)\s*:?\s*$", re.IGNORECASE)


def _page_date(text: str) -> date | None:
    """The date a page's header (:func:`ordnung.ingest.conflicts.header`) gives after a letter's date label, if one:
    the date of the letter that page starts. Read more loosely than the letter's own date is
    (:func:`ordnung.ingest.conflicts._header_date`), since it can only end the reading early."""
    for line in header(fold_punctuation(text).splitlines()):
        for start, end, _ in date_spans(line):
            if _PAGE_DATED.search(line[:start]) and (day := _one_date(line, start, end)) is not None:
                return day
    return None


def _letter_s_pages(pages: Sequence[PageInput], letter_date: date | None) -> list[PageInput]:
    """This letter's pages of the upload: the first, and each after it up to one whose header gives another
    letter's date (:func:`_page_date`) — a later letter in the same upload, whose posting day is its own. That page
    and every page after it are not read. ``letter_date``: the letter's date as read, else the first page's."""
    own = letter_date if letter_date is not None else _page_date(_page_text(pages[0])[0])
    kept = [pages[0]]
    for page in pages[1:]:
        day = _page_date(_page_text(page)[0])
        if day is not None and day != own:
            break
        kept.append(page)
    return kept


def posting_statement(pages: Sequence[PageInput], letter_date: date | None = None) -> PostingStatement | None:
    """The posting day the letter's ``pages`` state for this letter (see the module docstring); ``None`` without
    pages (nothing was read), an empty statement when they state none. ``letter_date``: the letter's own date as
    read, by which a field's row may date another letter ("Ihr Schreiben vom …" beside the value)."""
    if not pages:
        return None
    found: list[_Found] = []
    for index, page in enumerate(_letter_s_pages(pages, letter_date)):
        text, grounding = _page_text(page)
        if index == 0:
            found += _fields(text, _page_words(page), grounding, letter_date)
        found += _sentences(text, grounding)
    formal = _served_formally(pages)
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
