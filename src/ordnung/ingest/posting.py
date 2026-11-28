"""The day a letter was handed to the post, as its own page states it (SPEC § 8 stage 6, § 21; ADR 0026).

An authority's letter counts as delivered on the 4th day "nach der Aufgabe zur Post" (§ 122 Abs. 2 Nr. 1 AO,
§ 41 Abs. 2 S. 1 VwVfG, § 37 Abs. 2 S. 1 SGB X), not after its printed date — and many authorities print the
posting day on the letter, a day or a few later than its date: a field in the header or the footer ("Tag der
Aufgabe zur Post: 19.10.2026", "Absendedatum: …"), or a sentence ("Dieser Bescheid wurde am 19.10.2026 zur Post
gegeben"). The model may read that day or not; this module reads it in code, on the letter's own text, so that
the rules engine may start the deemed delivery there (:class:`~ordnung.rules.deadlines.PostingStatement`,
:func:`~ordnung.rules.deadlines._stated_posting`). The app (:func:`ordnung.ingest.plan.rule_context`) and the
benchmark's Ordnung condition (``evals.conditions.ordnung_rule_context``) both call :func:`posting_statement`.

What counts — a date the letter gives as the day *this* letter was posted:

* a field: a cell of its own that is a posting label and a date ("Tag der Aufgabe zur Post: 19.10.2026",
  "Datum der Aufgabe zur Post", "Aufgabe zur Post am …", "Zur Post gegeben am …", "Aufgegeben zur Post am …",
  "Absendedatum", "Absendetag", "Absendevermerk", "Tag der Absendung", "Absendung am", "Abgesandt am",
  "Abgesendet am", "Aufgegeben am", "Versanddatum", "Versandt am", "Versand am", "Versand:", "Postausgang", "Datum
  des Postausgangs", "Date of posting:", "Posting date:", "Posted on:"), or such a label above its date, as a
  letterhead's information block prints a column's label over its value: on the page right under the label (by
  the words' boxes), the last thing on its row and the only words in the label's column there but a weekday
  ("Mo., 19.10.2026"); or, without boxes, the label alone on its line over the date alone on its line (a weekday
  allowed) — never another column's date, another field's date stacked under the label ("Bekanntgabetag
  23.10.2026", "Zahlungsfrist …"), a date with more after it, two dates in the cell, nor a table's row;
* a sentence in the statutes' own words: "Aufgabe zur Post am …", "… am 19.10.2026 zur Post gegeben /
  aufgegeben", "der Post übergeben", "zur Post gegeben am …" — with no subject, or about this letter ("Dieser
  Bescheid", plainly "Der Bescheid", "Das Schreiben"), never about a document named by its own noun or sent to
  someone else ("Die Zahlungsaufforderung …", "Eine Mitteilung an den Arbeitgeber …");
* a sentence that this letter was sent on a day, in plainer words ("versandt", "abgesandt", "abgeschickt",
  "verschickt", "posted", "mailed", "sent"): only when it names this letter ("dieser Bescheid", "dieses
  Schreiben", "this letter", or the decision of the letter's own date: "Der Bescheid vom <its date> wurde am …
  versandt").

What never counts (each a test):

* another letter's or an earlier decision's posting day: a sentence or a field's line naming a letter by another
  date ("Der Bescheid vom 01.09.2026 wurde am 03.09.2026 zur Post gegeben", "Bescheid für 2024 | Datum
  12.10.2026 | Aufgabe zur Post …"), another document posted ("Die Kontrollmitteilung an das Finanzamt …"), or
  "Ihr Schreiben", "unser Schreiben vom …";
* the person's own letter or act ("Ihr Widerspruch …", "Sie haben … zur Post gegeben", "your letter");
* an enclosure, a copy or a second posting ("Die Anlage wurde gesondert versandt", "Anlage 1   Versanddatum …",
  "Abschrift" on the line or the line before, "Zweitschrift", "Erneut zur Post gegeben");
* a card, an ID or documents sent ("Ihre neue Gesundheitskarte - Versanddatum: …");
* sent another way than by post ("Versandt am: … per E-Mail", "… wurde per E-Mail versandt"), in a field as in a
  sentence (the sender's own e-mail address beside it is no such word);
* a payment or a deadline: a date after "bis", "spätestens", "innerhalb", "by", "until", or a sentence about
  paying;
* a supposition or an example ("Wenn dieser Bescheid am … zur Post gegeben wurde, gilt er …", "Sofern …",
  "Beispiel: Aufgabe zur Post am …", "z. B.");
* the day a letter counts as delivered ("gilt am vierten Tag nach Aufgabe zur Post als bekannt gegeben", "Tag
  nach der Aufgabe zur Post"), or a date after "vom" ("Schreiben vom …");
* a posting day in the future tense, planned, as a request or negated ("wird am … zur Post gegeben",
  "Versanddatum (voraussichtlich)", "(vsl.)", "(ca.)", "(spätestens)", "Geplante Aufgabe zur Post", a plan on the
  line before, "bitte geben Sie … zur Post", "nicht vor dem …"), in a sentence or a field;
* goods sent ("Ihre Bestellung wurde am … versandt", "Paket", "Sendungsnummer") — a shop's invoice is no
  authority's decision anyway: the engine lets a posting day start only an authority's deemed delivery by post
  (:func:`~ordnung.rules.deadlines._compute_relative`), never a company's period from arrival;
* a date that reads two ways (03/05/2026) or names no year.

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
    _PAYMENT_CUE,
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

#: How far (characters) a posting cue may stand from its date in a sentence.
_REACH = 80
#: A weekday before the date, written out or short, as a field often prints it: "Sa.,
#: 19.12.2026", "Mo 19.10.2026", "Sat, 19 Dec 2026".
_DAY = (
    r"(?:(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|monday|tuesday|wednesday|thursday"
    r"|friday|saturday|sunday),?\s*|(?:mo|di|mi|do|fr|sa|so|mon|tue|wed|thu|fri|sat|sun)\.?,?\s+)?"
)
#: The article a date may take after its weekday or "am": "am Montag, den 19.10.2026", "am Montag, dem 19.10.2026".
_DEN = r"(?:(?:den|dem)\s+)?"

#: The labels of a posting day's field, right before its date. The statutes' own words and the labels for the
#: posting day stand anywhere in a line ("Steuernummer 123/456/78901 Tag der Aufgabe zur Post: 19.10.2026");
#: plainer words only where a cell starts (a line's start, a column's gap, "|" or "·": "Versandt am: …"), so that
#: a sentence about something sent is read as a sentence.
_STRONG_LABEL = (
    r"(?:(?:tag|datum)\s+(?:der\s+(?:aufgabe\s+zur\s+post|postaufgabe|absendung|versendung)|des\s+versand(?:e)?s)"
    r"|datum\s+des\s+postausgang(?:e)?s|aufgabe\s+zur\s+post|aufgegeben\s+zur\s+post|zur\s+post\s+(?:auf)?gegeben"
    r"|postaufgabe|absende(?:datum|tag|vermerk)|versand(?:datum|tag)"
    r"|date\s+of\s+(?:posting|dispatch)|posting\s+date)"
)
#: "Aufgegeben am", "Versand am", "Versand:" are field labels only where a cell starts: in a sentence "aufgegeben"
#: may be an order's or a plan's ("Sie haben … aufgegeben"), "Versand" a shop's.
_WEAK_LABEL = (
    r"(?:abgesandt|abgesendet|abgeschickt|absendung|aufgegeben\b|versandt|versand\b|versendet|postausgang"
    r"|date\s+posted|posted|mailed)"
)
#: What may stand between a label and its date: "am", a short note in brackets ("Aufgabe zur Post (Absendetag):"),
#: a colon, "ist der" ("Tag der Aufgabe zur Post ist der 19.10.2026").
_LABEL_END = rf"(?:\s*\([^()\n]{{1,30}}\))?(?:\s+(?:am|on|ist\s+(?:der|am)|is))?\s*:?\s*{_DAY}{_DEN}$"
_FIELD_BEFORE = re.compile(
    rf"(?:(?<!\w){_STRONG_LABEL}|(?:^|\s{{2,}}|\t|[|·])\s*{_WEAK_LABEL}){_LABEL_END}", re.IGNORECASE
)
#: A label ending its line, its value on the next: "Tag der Aufgabe zur Post" over "19.10.2026", as a letterhead's
#: information block prints a column's label above its value (read as :func:`ordnung.ingest.conflicts._header_date`
#: reads "Datum").
_FIELD_LINE_END = re.compile(
    rf"(?:(?<!\w){_STRONG_LABEL}|(?:^|\s{{2,}}|\t|[|·])\s*{_WEAK_LABEL})(?:\s+(?:am|on))?\s*:?\s*$",
    re.IGNORECASE,
)
#: A posting label alone in a cell of a row of labels: "Tag der Aufgabe zur Post   Bekanntgabetag".
_FIELD_CELL = re.compile(rf"(?:{_STRONG_LABEL}|{_WEAK_LABEL})(?:\s+(?:am|on))?\s*:?", re.IGNORECASE)
#: Words right before a field's label that make it another's: the day a letter counts as delivered ("am vierten
#: Tag nach Aufgabe zur Post"), the person's or the sender's earlier letter ("Ihr Schreiben, abgesandt am").
_LABEL_NOT_THIS = re.compile(
    r"\b(?:nach|ihr\w*|unser\w*|your|our|after)\s+(?:der\s+|dem\s+|the\s+)?\S*\s*$", re.IGNORECASE
)

#: The statutes' words just before the date: "Aufgabe zur Post am …", "Tag der Aufgabe zur Post ist der …",
#: "zur Post gegeben am …", "der Post übergeben am …".
_STATUTE_BEFORE = re.compile(
    r"(?:aufgabe\s+zur\s+post(?:\s+(?:am|ist\s+(?:der|am)|erfolgte?\s+am))?\s*:?"
    r"|zur\s+post\s+(?:auf)?gegeben(?:\s+worden)?\s+am|aufgegeben\s+zur\s+post\s+am"
    r"|der\s+post\s+übergeben(?:\s+worden)?\s+am)"
    rf"\s*{_DAY}{_DEN}$",
    re.IGNORECASE,
)
#: The statutes' words after the date: "am 19.10.2026 zur Post gegeben", "… der Post übergeben".
_STATUTE_AFTER = re.compile(
    r"^\W*(?:\S+\s+){0,3}?(?:zur\s+post\s+(?:auf)?gegeben|der\s+post\s+übergeben|zur\s+post\s+gebracht)\b",
    re.IGNORECASE,
)
#: Plainer words that a letter was sent, before or after "am <date>" / "on <date>".
_SENT_WORDS = (
    r"(?:versandt|versendet|abgesandt|abgesendet|abgeschickt|verschickt|postalisch\s+übersandt|übersandt"
    r"|posted|mailed|sent(?:\s+by\s+post)?)"
)
_SENT_BEFORE = re.compile(rf"\b{_SENT_WORDS}(?:\s+worden)?\s+(?:am|on)\s*{_DAY}{_DEN}$", re.IGNORECASE)
_SENT_AFTER = re.compile(rf"^\W*(?:\S+\s+){{0,3}}?{_SENT_WORDS}\b", re.IGNORECASE)
_ON_BEFORE = re.compile(rf"\b(?:am|on)\s*{_DAY}{_DEN}$", re.IGNORECASE)
#: The letter naming itself: "dieser Bescheid", "dieses Schreiben", "vorliegende Mitteilung", "this letter".
_THIS_LETTER = re.compile(
    r"\b(?:dies(?:e[mnrs]?)?|vorliegende[mnrs]?)\s+\w*(?:bescheid|schreiben|brief|mitteilung|entscheidung"
    r"|festsetzung|benachrichtigung|verfügung)\w*|\bthis\s+(?:letter|notice|decision|assessment)\b",
    re.IGNORECASE,
)
#: A letter named by a date ("Bescheid vom 01.09.2026"): this one only when that date is the letter's own.
_NAMED_BY_DATE = re.compile(
    r"\b\w*(?:bescheid|schreiben|brief|mitteilung|entscheidung|festsetzung|verfügung)\w*\s+vom\s*$",
    re.IGNORECASE,
)
#: Words that make the posting someone else's: the person's letter or act, the sender's earlier one.
_NOT_THIS = re.compile(
    r"\b(?:Ihr|Ihre|Ihren|Ihrem|Ihres|Ihrer)\b|\bSie\s+(?:haben|hatten|sind|waren)\b|\b(?:haben|hatten)\s+Sie\b"
    r"|\bvon\s+Ihnen\b|\b(?:unser|unsere|unseren|unserem|unseres)\s+\w*(?:schreiben|brief|bescheid|mitteilung)"
    r"|\b(?:your|our)\s+(?:letter|notice|objection|application|appeal)|\byou\s+(?:posted|sent|mailed)\b",
)
#: A future posting, a request or a negation: "wird … zur Post gegeben", "geben Sie … zur Post", "nicht" (a mere
#: "Bitte beachten Sie:" before a statement asks nothing of the posting).
_NOT_DONE = re.compile(
    r"\b(?:wird|werden|würde|würden|soll|sollen|sollte|sollten|voraussichtlich|geben\s+sie|senden\s+sie"
    r"|schicken\s+sie|nicht|kein\w*|will|shall|would|not|never)\b",
    re.IGNORECASE,
)
#: The day a letter counts as delivered, not the day it was posted: the statutes' words right after "nach" ("am
#: vierten Tag nach Aufgabe zur Post: 23.10.2026").
_DELIVERED_BEFORE = re.compile(r"\b(?:nach|after)\s+(?:der\s+|dem\s+)?$", re.IGNORECASE)
#: An enclosure or a copy sent: its own posting.
_ENCLOSURE = re.compile(
    r"\b\w*(?:anlage|beilage)\w*|\bbeigefügt\w*|\bbeiliegend\w*|\banbei\b|\bkopie\w*|\babschrift\w*"
    r"|\bdurchschrift\w*|\bzweitschrift\w*|\bgesondert\w*|\bseparat\w*|\berneut\w*|\bnochmals\b|\benclos\w*"
    r"|\battach\w*|\bcop(?:y|ies)\b|\bseparately\b",
    re.IGNORECASE,
)
#: A date that is a deadline, not a day past: "bis", "spätestens", "innerhalb", "by", "until".
_DEADLINE_BEFORE = re.compile(
    rf"\b(?:bis|spätestens|innerhalb|binnen|ab|seit|vor|by|before|until|from|since|no\s+later\s+than)"
    rf"(?:\s+(?:zum|am|spätestens))*\s*{_DAY}{_DEN}$",
    re.IGNORECASE,
)
#: A posting day that is a plan, not a record: "Versanddatum (voraussichtlich)", "Geplante Aufgabe zur Post",
#: "Nächste Aufgabe zur Post", "Der Bescheid folgt".
_PLANNED = re.compile(
    r"\b(?:voraussichtlich\w*|geplant\w*|vorgesehen\w*|nächste\w*|künftig\w*|frühestens|folgt|folgen|demnächst"
    r"|expected|planned|scheduled|next)\b",
    re.IGNORECASE,
)
#: A field's note in brackets that makes its day a plan or a bound, not a record: "Versanddatum (vsl.)", "(ca.)",
#: "(Plan)", "Absendetag (spätestens)". Only in brackets: on a line of its own "ca." is any estimate.
_PLANNED_NOTE = re.compile(r"\([^()\n]*\b(?:vsl|ca|plan|spätestens|soll)\b[^()\n]*\)", re.IGNORECASE)
#: A sentence that does not record this letter's posting but supposes one or gives an example: "Wenn dieser
#: Bescheid am … zur Post gegeben wurde, gilt er am … als bekannt gegeben", "Sofern …", "Beispiel: Aufgabe zur
#: Post am …".
_HYPOTHETICAL = re.compile(
    r"\b(?:wenn|falls|sofern|soweit|angenommen|beispielsweise|beispielrechnung|etwa|if|example)\b"
    r"|\b(?:zum\s+)?beispiel\b\s*[:(]|\bzum\s+beispiel\b|\bz\.\s*b\.|\be\.\s*g\.",
    re.IGNORECASE,
)
#: Things an authority sends besides a letter, whose own dispatch a field may date: a health insurance card, an ID,
#: documents, a certificate ("Ihre neue Gesundheitskarte - Versanddatum: …").
_OBJECT = re.compile(
    r"\w*(?:karte|ausweis|dokument|unterlage|bescheinigung|urkunde|plakette)\w*|\b(?:cards?|documents?|certificates?)\b",
    re.IGNORECASE,
)
#: Another way of sending than the post: an e-mail, a portal (its own day under § 122 Abs. 2a AO, never this one).
_ELECTRONIC = re.compile(
    r"\be-?mail\w*|\bde-mail\b|\belektronisch\w*|\bportal\w*|\bonline\b|\belster\b|\belectronic\w*",
    re.IGNORECASE,
)
#: The sender's own contact details, which a letterhead's line may carry beside a posting day in another column: an
#: address ("poststelle@finanzamt-musterstadt.de", "www.…"), or its label ("E-Mail: …"). They say nothing about how
#: this letter went out.
_CONTACT = re.compile(
    r"\S+@\S+|\b(?:www\.|https?://)\S+|\b(?:e-?mail|de-mail|internet|web|homepage)[ \t]*:[ \t]*\S*",
    re.IGNORECASE,
)
#: A letter's date label right before a date ("Datum 12.10.2026", "vom 12.10.2026", "dated"): on a posting day's line,
#: a date other than the letter's own makes the line another letter's ("Bescheid für 2024 | Datum 12.10.2026 |
#: Aufgabe zur Post 19.10.2026" is a row about another decision).
_DATED = re.compile(r"(?:\bvom|\bdatum|\bdate|\bdated)\s*:?\s*$", re.IGNORECASE)
#: Where a field's cell ends: a column's gap, a tab, "|" or "·".
_CELL_BREAK = re.compile(r"\s{2,}|\t|[|·]")
#: A line that ends unfinished, so that a sentence goes on on the next: a hyphen, a preposition, an article, an
#: auxiliary ("Dieser Bescheid wurde am" over "19.10.2026 zur Post gegeben"). A line ending in a label ("Tag der
#: Aufgabe zur Post") is finished: the date on the next line may be another column's.
_UNFINISHED = re.compile(
    r"(?:-|\b(?:am|an|den|der|des|dem|die|das|zur|zum|ist|sind|wurde|wurden|worden|erfolgte|erfolgt|on|the|of|was"
    r"|were|is))\s*$",
    re.IGNORECASE,
)
#: A document's noun in a sentence's subject: another document than this letter, unless it is how a letter calls
#: itself (:data:`_OWN_NOUNS`) or the sentence names this letter.
_DOCUMENT = re.compile(
    r"\b\w*(?:bescheid|schreiben|brief|mitteilung|aufforderung|erinnerung|mahnung|entscheidung|festsetzung"
    r"|verfügung|benachrichtigung|erklärung|antrag|formular|rechnung|karte|ausweis|dokument|unterlage"
    r"|bescheinigung|urkunde)\w*",
    re.IGNORECASE,
)
_OWN_NOUNS = frozenset({"bescheid", "schreiben", "brief"})
#: Someone a document was sent to: "an das Finanzamt Beispielhausen", "an den Arbeitgeber".
_ADDRESSEE = re.compile(r"\ban\s+(?:das|den|die|dem|einen?|eine[mr]?)\b", re.IGNORECASE)
#: Goods sent: a shop's dispatch, never a letter's posting.
_GOODS = re.compile(
    r"\b(?:bestellung\w*|ware\w*|artikel|lieferung\w*|paket\w*|päckchen|sendungsnummer|sendungsverfolgung"
    r"|tracking|order\w*|parcel\w*|shipment\w*|package\w*|goods)\b",
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


def _cell(line: str, start: int, end: int) -> str:
    """The cell of ``line`` that holds ``line[start:end]`` (:func:`_cell_bounds`)."""
    lo, hi = _cell_bounds(line, start, end)
    return line[lo:hi]


def _dates_another(line: str, own: tuple[int, int], letter_date: date | None) -> bool:
    """Whether ``line`` dates another letter than this one, beside the posting day at ``own``: a letter named by
    another date ("Bescheid vom 12.10.2026"), or a letter's date label with another date than the letter's own
    ("Datum 12.10.2026") — a table's row about another decision."""
    if _names_another(line, letter_date):
        return True
    for start, end, mention in date_spans(line):
        if (start, end) == own or not _DATED.search(line[:start][-20:]):
            continue
        if letter_date is None or mention.as_date() != letter_date:
            return True
    return False


def _sent_electronically(text: str) -> bool:
    """Whether ``text`` says the letter went out another way than by post (an e-mail, a portal) — the sender's own
    e-mail or web address beside it says nothing about that (:data:`_CONTACT`)."""
    return bool(_ELECTRONIC.search(_CONTACT.sub(" ", text)))


def _another_s(lines: Sequence[str], previous: str, own: str) -> bool:
    """Whether a statement's ``lines`` (a field's label's and value's, or a sentence's) or the line ``previous`` to
    them make its posting day something else's: a plan ("voraussichtlich", "geplant", "Nächste Aufgabe zur Post",
    "(vsl.)"), a future, a request or a negation, a supposition or an example ("Wenn …", "Beispiel:"), an enclosure
    or a copy ("Anlage", "Beiliegend", "Zweitschrift"), a card, an ID or documents sent, goods. Its own cell
    ``own`` must not name another way of sending (an e-mail, a portal). The sender's contact details are no words
    of the statement's (:data:`_CONTACT`)."""
    text = _CONTACT.sub(" ", "\n".join(lines))
    previous = _CONTACT.sub(" ", previous)
    return bool(
        _NOT_DONE.search(text)
        or _PLANNED_NOTE.search(text)
        or _HYPOTHETICAL.search(text)
        or _sent_electronically(own)
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


def _fields(text: str, words: list[Box], grounding: Grounding, letter_date: date | None) -> list[_Found]:
    """Posting days in a field: a posting label right before one date that reads one way ("Tag der Aufgabe zur
    Post: 19.10.2026", "Versandt am: 19.10.2026" where a cell starts), or a label ending its line with its value on
    the next (:func:`_under_labels`); never a table's row. Never after "nach" or another's letter, nor on a line that
    dates another letter, plans or supposes the posting or is about an enclosure, a card, documents or goods
    (:func:`_another_s`)."""
    found: list[_Found] = []
    lines = fold_punctuation(text).splitlines()
    for index, line in enumerate(lines):
        previous = lines[index - 1] if index else ""
        spans = [(start, end) for start, end, _ in date_spans(line)]
        for start, end in dict.fromkeys(spans):
            label = _FIELD_BEFORE.search(line[:start])
            day = _one_date(line, start, end)
            if (
                label is None
                or day is None
                or _LABEL_NOT_THIS.search(line[: label.start()][-30:])
                or _another_s([line], previous, _cell(line, label.start(), end))
                or _dates_another(line, (start, end), letter_date)
            ):
                continue
            found.append(_Found(day, _short(line[label.start() : end]).lstrip("|· "), grounding))
        if index + 1 < len(lines) and not _TABLE_ROW.search(line):
            found += _under_labels(line, lines[index + 1].rstrip(), previous, words, grounding, letter_date)
    return found


def _labels_above(line: str, words: list[Box]) -> list[str]:
    """The posting labels in ``line`` whose value may stand on the next line: one ending the line ("…   Tag der
    Aufgabe zur Post"), and, where the page's word boxes can tell the columns apart, one alone in its cell
    ("Tag der Aufgabe zur Post   Bekanntgabetag")."""
    names = []
    label = _FIELD_LINE_END.search(line)
    if label is not None and not _LABEL_NOT_THIS.search(line[: label.start()][-30:]):
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
            if _another_s([line, following], previous, f"{name} {following[lo:hi]}") or _dates_another(
                following, (start, end), letter_date
            ):
                continue
            found.append(_Found(day, _short(f"{name} {value}"), grounding))
    return found


def _names_this_letter(clause: str, letter_date: date | None) -> bool:
    """Whether the sentence names this letter: "dieser Bescheid", "this letter", or a letter named by the
    letter's own date ("Der Bescheid vom <its date>")."""
    if _THIS_LETTER.search(clause):
        return True
    named = [
        found
        for start, end, mention in date_spans(clause)
        if _NAMED_BY_DATE.search(clause[:start]) and (found := mention.as_date()) is not None
    ]
    return bool(named) and letter_date is not None and all(day == letter_date for day in named)


def _names_another(clause: str, letter_date: date | None) -> bool:
    """Whether the sentence names a letter by another date than the letter's own ("Der Bescheid vom 01.09.2026 …")
    — or by any date, when the letter's own is not known."""
    for start, _, mention in date_spans(clause):
        day = mention.as_date()
        if _NAMED_BY_DATE.search(clause[:start]) and (letter_date is None or day != letter_date):
            return True
    return False


def _about_another(subject: str, letter_date: date | None) -> bool:
    """Whether the words before a posting in the statutes' words make it another document's: a document named by
    its own noun ("Die Zahlungsaufforderung", "Der Widerspruchsbescheid", "Die Bescheide für 2023 und 2024") or one
    sent to someone ("Eine Mitteilung an den Arbeitgeber"), unless the sentence names this letter ("Dieser
    Widerspruchsbescheid"). A letter calls itself plainly "der Bescheid", "das Schreiben", "der Brief"; a sentence
    with no subject ("Aufgabe zur Post am …") is the letter's own record."""
    nouns = [found.group().casefold() for found in _DOCUMENT.finditer(subject)]
    sent_to = _ADDRESSEE.search(subject)
    if not sent_to and all(noun in _OWN_NOUNS for noun in nouns):
        return False
    return not _names_this_letter(subject, letter_date)


def _sentences(text: str, grounding: Grounding, letter_date: date | None) -> list[_Found]:
    """Posting days a sentence states for this letter (see the module docstring). What makes a posting another's
    is read in its own words: the lines from its cue to its date (a letter's header is one long clause without a
    full stop, whose "Ihr Zeichen" or "Bitte bei Antwort angeben" says nothing about the posting), the line before
    them (as a field's: "Abschrift" over "Tag der Aufgabe zur Post: …") and, for a supposition ("Wenn dieser
    Bescheid am … zur Post gegeben wurde"), the sentence's words before its cue."""
    found: list[_Found] = []
    clauses = _clauses(text)
    flat = "".join(clause for clause, _ in clauses)
    offset = 0  # where the clause starts in the letter's text: the clauses are its consecutive pieces
    for clause, dates in clauses:
        at_clause, offset = offset, offset + len(clause)
        spans = [(start, end) for start, end, _ in dates]
        for index, (start, end, day) in enumerate(dates):
            if spans.count((start, end)) > 1:
                continue  # a date that reads two ways
            lo = dates[index - 1][1] if index > 0 else 0
            hi = dates[index + 1][0] if index + 1 < len(dates) else len(clause)
            before = clause[max(lo, start - _REACH) : start]
            after = clause[end : min(hi, end + _REACH)]
            if _DEADLINE_BEFORE.search(before):
                continue
            cue = (
                _STATUTE_BEFORE.search(before)
                or _SENT_BEFORE.search(before)
                or (_ON_BEFORE.search(before) and (_STATUTE_AFTER.match(after) or _SENT_AFTER.match(after)))
            )
            if not cue:
                continue
            ahead = cue.re in (_STATUTE_BEFORE, _SENT_BEFORE)
            first = start - len(before) + cue.start() if ahead else start
            # the words before the date are its label's only on one line, or where a sentence goes on: a label ending
            # its line ("Tag der Aufgabe zur Post" over "23.10.2026   19.10.2026") is a field's, whose value may be
            # another column's (:func:`_fields` reads it by the page's boxes)
            said = (
                start - len(before) + (cue.start() if ahead else (_ON_BEFORE.search(before) or cue).start())
            )
            if any(
                not _UNFINISHED.search(clause[max(0, at - 30) : at])
                for at in (i for i in range(said, start) if clause[i] == "\n")
            ):
                continue
            last = end if ahead else end + cue.end()
            line_start = clause.rfind("\n", 0, first) + 1
            line_end = clause.find("\n", last)
            own = clause[line_start : len(clause) if line_end < 0 else line_end]
            statute = cue.re in (_STATUTE_BEFORE, _STATUTE_AFTER)
            # the line before the statement's first line (it may end the previous sentence)
            here = flat.rfind("\n", 0, at_clause + line_start + 1) + 1
            previous = flat[flat.rfind("\n", 0, here - 1) + 1 : here - 1] if here > 0 else ""
            # the words before the cue that may suppose it: the sentence's and its line's ("Ein Bescheid, der z. B.")
            supposed = flat[max(at_clause + first - 120, min(at_clause, here)) : at_clause + first]
            if (
                _NOT_THIS.search(own)
                or _PLANNED.search(own)
                or _PAYMENT_CUE.search(own)
                or _another_s([own], previous, own)
                or _HYPOTHETICAL.search(_CONTACT.sub(" ", supposed))
                or _dates_another(own, (start - line_start, end - line_start), letter_date)
                or _DELIVERED_BEFORE.search(clause[max(0, first - 30) : first])
            ):
                continue
            if statute and _about_another(clause[max(0, line_start - 120) : first], letter_date):
                continue
            if not statute and (
                _GOODS.search(own)
                or not _names_this_letter(
                    clause[max(0, line_start - 120) : len(own) + line_start], letter_date
                )
            ):
                continue
            found.append(_Found(day, _short(own), grounding))
    return found


def posting_statement(pages: Sequence[PageInput], letter_date: date | None = None) -> PostingStatement | None:
    """The posting day the letter's ``pages`` state for this letter (see the module docstring); ``None`` without
    pages (nothing was read), an empty statement when they state none. ``letter_date``: the letter's own date as
    read, by which a sentence may name this letter ("Der Bescheid vom <its date> wurde am … zur Post gegeben")."""
    if not pages:
        return None
    found: list[_Found] = []
    for page in pages:
        text, grounding = _page_text(page)
        found += _fields(text, _page_words(page), grounding, letter_date)
        found += _sentences(text, grounding, letter_date)
    if not found:
        return PostingStatement()
    days = sorted({statement.day for statement in found})
    first = next(statement for statement in found if statement.day == days[0])
    # a text page that says it too makes it as sure as any verified fact
    sure: Literal["verified", "model_read"] = (
        "verified"
        if any(statement.grounding == "verified" for statement in found if statement.day == days[0])
        else "model_read"
    )
    if len(days) == 1:
        return PostingStatement(day=days[0], quote=first.quote, grounding=sure)
    last = next(statement for statement in found if statement.day == days[-1])
    return PostingStatement(
        day=days[0], quote=first.quote, grounding=sure, other=days[-1], other_quote=last.quote
    )


#: A key fact's label that names a posting day: the field labels above, and the plain English a reading may use
#: ("Posting date", "Date posted", "Mailed on", "Handed to the post"). Never the day of delivery or a deadline.
_READ_LABEL = re.compile(
    rf"{_STRONG_LABEL}|{_WEAK_LABEL}|\bpost(?:ing|ed)\b|\bmail(?:ed|ing)\b|\bdispatch\w*|\bhanded\s+to\s+the\s+post",
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
