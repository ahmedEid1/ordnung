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
  "Datum der Aufgabe zur Post", "Aufgabe zur Post am …", "Zur Post gegeben am …", "Absendedatum", "Absendetag",
  "Tag der Absendung", "Abgesandt am", "Versanddatum", "Versandt am", "Postausgang", "Date of posting:",
  "Posting date:", "Posted on:"), or such a label alone on its line with the date alone on the next;
* a sentence in the statutes' own words: "Aufgabe zur Post am …", "… am 19.10.2026 zur Post gegeben /
  aufgegeben", "der Post übergeben", "zur Post gegeben am …";
* a sentence that this letter was sent on a day, in plainer words ("versandt", "abgesandt", "abgeschickt",
  "verschickt", "posted", "mailed", "sent"): only when it names this letter ("dieser Bescheid", "dieses
  Schreiben", "this letter", or the decision of the letter's own date: "Der Bescheid vom <its date> wurde am …
  versandt").

What never counts (each a test):

* another letter's or an earlier decision's posting day: a sentence naming a letter by another date ("Der
  Bescheid vom 01.09.2026 wurde am 03.09.2026 zur Post gegeben"), or "Ihr Schreiben", "unser Schreiben vom …";
* the person's own letter or act ("Ihr Widerspruch …", "Sie haben … zur Post gegeben", "your letter");
* an enclosure or a copy ("Die Anlage wurde gesondert versandt", "Abschrift", "Kopie");
* a payment or a deadline: a date after "bis", "spätestens", "innerhalb", "by", "until", or a sentence about
  paying;
* the day a letter counts as delivered ("gilt am vierten Tag nach Aufgabe zur Post als bekannt gegeben", "Tag
  nach der Aufgabe zur Post"), or a date after "vom" ("Schreiben vom …");
* a posting day in the future tense, as a request or negated ("wird am … zur Post gegeben", "bitte geben Sie …
  zur Post", "nicht vor dem …");
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

from ordnung.ingest.conflicts import _PAYMENT_CUE, _clauses, _one_date, _page_text
from ordnung.ingest.normalize import fold_punctuation
from ordnung.ingest.verify import PageInput, date_spans
from ordnung.models import Grounding
from ordnung.rules.deadlines import PostingStatement

#: How far (characters) a posting cue may stand from its date in a sentence.
_REACH = 80
#: A weekday before the date, written out or short, as a field often prints it: "Sa.,
#: 19.12.2026", "Mo 19.10.2026", "Sat, 19 Dec 2026".
_DAY = (
    r"(?:(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|monday|tuesday|wednesday|thursday"
    r"|friday|saturday|sunday),?\s*|(?:mo|di|mi|do|fr|sa|so|mon|tue|wed|thu|fri|sat|sun)\.?,?\s+)?"
)

#: The labels of a posting day's field, right before its date. The statutes' own words and the labels for the
#: posting day stand anywhere in a line ("Steuernummer 123/456/78901 Tag der Aufgabe zur Post: 19.10.2026");
#: plainer words only where a cell starts (a line's start, a column's gap, "|" or "·": "Versandt am: …"), so that
#: a sentence about something sent is read as a sentence.
_STRONG_LABEL = (
    r"(?:(?:tag|datum)\s+(?:der\s+(?:aufgabe\s+zur\s+post|postaufgabe|absendung|versendung)|des\s+versand(?:e)?s)"
    r"|aufgabe\s+zur\s+post|zur\s+post\s+(?:auf)?gegeben|postaufgabe|absende(?:datum|tag)|versand(?:datum|tag)"
    r"|date\s+of\s+(?:posting|dispatch)|posting\s+date)"
)
_WEAK_LABEL = r"(?:abgesandt|abgeschickt|versandt|versendet|postausgang|date\s+posted|posted|mailed)"
#: What may stand between a label and its date: "am", a short note in brackets ("Aufgabe zur Post (Absendetag):"),
#: a colon, "ist der" ("Tag der Aufgabe zur Post ist der 19.10.2026").
_LABEL_END = rf"(?:\s*\([^()\n]{{1,30}}\))?(?:\s+(?:am|on|ist\s+(?:der|am)|is))?\s*:?\s*{_DAY}(?:den\s+)?$"
_FIELD_BEFORE = re.compile(
    rf"(?:(?<!\w){_STRONG_LABEL}|(?:^|\s{{2,}}|\t|[|·])\s*{_WEAK_LABEL}){_LABEL_END}", re.IGNORECASE
)
_FIELD_ALONE = re.compile(rf"^\s*(?:{_STRONG_LABEL}|{_WEAK_LABEL})(?:\s+(?:am|on))?\s*:?\s*$", re.IGNORECASE)
#: Words right before a field's label that make it another's: the day a letter counts as delivered ("am vierten
#: Tag nach Aufgabe zur Post"), the person's or the sender's earlier letter ("Ihr Schreiben, abgesandt am").
_LABEL_NOT_THIS = re.compile(
    r"\b(?:nach|ihr\w*|unser\w*|your|our|after)\s+(?:der\s+|dem\s+|the\s+)?\S*\s*$", re.IGNORECASE
)

#: The statutes' words just before the date: "Aufgabe zur Post am …", "Tag der Aufgabe zur Post ist der …",
#: "zur Post gegeben am …", "der Post übergeben am …".
_STATUTE_BEFORE = re.compile(
    r"(?:aufgabe\s+zur\s+post(?:\s+(?:am|ist\s+(?:der|am)|erfolgte?\s+am))?\s*:?"
    r"|zur\s+post\s+(?:auf)?gegeben(?:\s+worden)?\s+am|der\s+post\s+übergeben(?:\s+worden)?\s+am)"
    rf"\s*{_DAY}(?:den\s+)?$",
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
_SENT_BEFORE = re.compile(rf"\b{_SENT_WORDS}(?:\s+worden)?\s+(?:am|on)\s*{_DAY}(?:den\s+)?$", re.IGNORECASE)
_SENT_AFTER = re.compile(rf"^\W*(?:\S+\s+){{0,3}}?{_SENT_WORDS}\b", re.IGNORECASE)
_ON_BEFORE = re.compile(rf"\b(?:am|on)\s*{_DAY}(?:den\s+)?$", re.IGNORECASE)
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
    r"|\bdurchschrift\w*|\bgesondert\w*|\bseparat\w*|\benclos\w*|\battach\w*|\bcop(?:y|ies)\b|\bseparately\b",
    re.IGNORECASE,
)
#: A date that is a deadline, not a day past: "bis", "spätestens", "innerhalb", "by", "until".
_DEADLINE_BEFORE = re.compile(
    rf"\b(?:bis|spätestens|innerhalb|binnen|ab|seit|vor|by|before|until|from|since|no\s+later\s+than)"
    rf"(?:\s+(?:zum|am|spätestens))*\s*{_DAY}(?:den\s+)?$",
    re.IGNORECASE,
)
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


def _fields(text: str, grounding: Grounding) -> list[_Found]:
    """Posting days in a field: a posting label right before one date that reads one way ("Tag der Aufgabe zur
    Post: 19.10.2026", "Versandt am: 19.10.2026" where a cell starts), or the label alone on its line and the date
    alone on the next. Never on a line about goods sent, nor after "nach" or another's letter."""
    found: list[_Found] = []
    lines = fold_punctuation(text).splitlines()
    for index, line in enumerate(lines):
        if _GOODS.search(line):
            continue
        spans = [(start, end) for start, end, _ in date_spans(line)]
        for start, end in dict.fromkeys(spans):
            label = _FIELD_BEFORE.search(line[:start])
            day = _one_date(line, start, end)
            if label is None or day is None or _LABEL_NOT_THIS.search(line[: label.start()][-30:]):
                continue
            found.append(_Found(day, _short(line[label.start() : end]).lstrip("|· "), grounding))
        if _FIELD_ALONE.match(line) and index + 1 < len(lines):
            following = lines[index + 1].strip()
            dated = {(start, end) for start, end, _ in date_spans(following)}
            if len(dated) == 1:
                [(start, end)] = dated
                day = _one_date(following, start, end)
                if day is not None and (start, end) == (0, len(following)):
                    found.append(_Found(day, _short(f"{line} {following}"), grounding))
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


def _sentences(text: str, grounding: Grounding, letter_date: date | None) -> list[_Found]:
    """Posting days a sentence states for this letter (see the module docstring). What makes a posting another's
    is read in its own words: the lines from its cue to its date (a letter's header is one long clause without a
    full stop, whose "Ihr Zeichen" or "Bitte bei Antwort angeben" says nothing about the posting)."""
    found: list[_Found] = []
    for clause, dates in _clauses(text):
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
            last = end if ahead else end + cue.end()
            line_start = clause.rfind("\n", 0, first) + 1
            line_end = clause.find("\n", last)
            own = clause[line_start : len(clause) if line_end < 0 else line_end]
            statute = cue.re in (_STATUTE_BEFORE, _STATUTE_AFTER)
            if (
                _NOT_THIS.search(own)
                or _NOT_DONE.search(own)
                or _ENCLOSURE.search(own)
                or _PAYMENT_CUE.search(own)
                or _names_another(own, letter_date)
                or _DELIVERED_BEFORE.search(clause[max(0, first - 30) : first])
            ):
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
        found += _fields(text, grounding)
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
