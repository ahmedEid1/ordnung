"""The posting day a letter's page states (``ingest.posting``, ADR 0026), and its way from a letter to the to-do.

Every letter here is made up (Musterstadt, Beispielhausen, fictional people and file numbers): the cues come from
how German authorities write the posting day — the statutes' "Aufgabe zur Post" (§ 122 Abs. 2 AO, § 41 Abs. 2
VwVfG, § 37 Abs. 2 SGB X), a header or footer field, a sentence that the decision was posted —, and the never-list
from the module's docstring.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import Letter
from helpers_tables import check_rows
from ordnung import clock
from ordnung.ingest.plan import compute_item, needs_check, verify_extraction
from ordnung.ingest.posting import posting_statement, read_posting_day
from ordnung.models import DateSpec, DocumentExtraction, ExtractedFact, ExtractedItem
from ordnung.rules.deadlines import POSTED_ON_LETTER, TWO_POSTING_DAYS, PostingStatement, RuleContext
from test_api_support import ApiRouter, api_for

D = date.fromisoformat
LETTER = D("2026-10-16")
HEADER = (
    "Finanzamt Musterstadt · Postfach 10 20 30 · 12345 Musterstadt\n"
    "Frau Erika Beispiel   Ihr Zeichen   Bitte bei Antwort angeben\n"
    "Lindenweg 4   -   Steuernummer 123/456/78901\n"
    "12345 Musterstadt   Datum 16.10.2026\n"
)


def found(text: str, source: str = "text") -> PostingStatement | None:
    return posting_statement([(1, text, [], source)], LETTER)


#: (id, page text, the posting day it states). Each a way an authority writes it.
CUES = [
    (
        "field-in-the-header",
        f"{HEADER}Tag der Aufgabe zur Post: 19.10.2026\n\nSehr geehrte Frau Beispiel,",
        "2026-10-19",
    ),
    (
        "field-in-a-column",
        "Steuernummer 123/456   Datum 16.10.2026   Aufgabe zur Post: 19.10.2026",
        "2026-10-19",
    ),
    (
        "field-on-a-single-spaced-line",
        "Steuernummer 123/456/78901 Tag der Aufgabe zur Post 19.10.2026",
        "2026-10-19",
    ),
    ("field-datum-der-aufgabe", "Datum der Aufgabe zur Post: Montag, 19. Oktober 2026", "2026-10-19"),
    ("field-under-its-label", "Tag der Aufgabe zur Post\n19.10.2026\n", "2026-10-19"),
    (
        "field-in-the-footer",
        "Seite 1 von 2 · Absendedatum: 19.10.2026 · Bankverbindung siehe Rückseite",
        "2026-10-19",
    ),
    ("field-versandt-am", "Bescheid über Grundbesitzabgaben\nVersandt am: 19.10.2026", "2026-10-19"),
    ("field-tag-der-absendung", "Tag der Absendung: 19.10.2026", "2026-10-19"),
    ("field-datum-des-versands", "Datum des Versands: 19.10.2026", "2026-10-19"),
    ("field-short-weekday", "Tag der Aufgabe zur Post: Mo., 19.10.2026", "2026-10-19"),
    ("sentence-erfolgt", "Die Aufgabe zur Post erfolgt am Mo 19.10.2026.", "2026-10-19"),
    ("field-with-a-note", "Aufgabe zur Post (Absendevermerk): 19.10.2026", "2026-10-19"),
    ("field-ist-der", "Bitte beachten Sie: Tag der Aufgabe zur Post ist der 19.10.2026.", "2026-10-19"),
    (
        "sentence-zur-post-gegeben",
        "Sehr geehrter Herr Muster,\nDieser Bescheid wurde am 19.10.2026 zur Post gegeben. Er ergeht unter Vorbehalt.",
        "2026-10-19",
    ),
    (
        "sentence-zur-post-gegeben-worden",
        "Der Bescheid ist am Montag, den 19.10.2026 zur Post gegeben worden.",
        "2026-10-19",
    ),
    ("sentence-wrapped", "Dieser Bescheid wurde am 19.10.2026 zur\nPost gegeben.", "2026-10-19"),
    ("sentence-aufgabe-am", "Die Aufgabe zur Post erfolgte am 19.10.2026.", "2026-10-19"),
    (
        "sentence-der-post-uebergeben",
        "Dieses Schreiben wurde am 19.10.2026 der Post übergeben.",
        "2026-10-19",
    ),
    ("sentence-versandt-this-letter", "Dieser Bescheid wurde am 19.10.2026 versandt.", "2026-10-19"),
    (
        "sentence-versandt-own-date",
        "Der Bescheid vom 16.10.2026 wurde am 19. Oktober 2026 abgesandt.",
        "2026-10-19",
    ),
    ("with-its-delivery-day", "Tag der Aufgabe zur Post: 19.10.2026 (Bekanntgabe: 23.10.2026)", "2026-10-19"),
    ("english-field", "Date of posting: 19 October 2026", "2026-10-19"),
    ("english-sentence", "This letter was posted on 19 October 2026.", "2026-10-19"),
    ("field-aufgegeben-zur-post", "Aufgegeben zur Post am 19.10.2026", "2026-10-19"),
    ("field-datum-des-postausgangs", "Datum des Postausgangs: 19.10.2026", "2026-10-19"),
    ("field-abgesendet-am", "Abgesendet am 19.10.2026", "2026-10-19"),
    ("field-absendung-am", "Absendung am 19.10.2026", "2026-10-19"),
    ("sentence-aufgegeben-zur-post", "Er wurde aufgegeben zur Post am 19.10.2026.", "2026-10-19"),
    # a sentence that goes on on the next line after "am": the date is still its own
    (
        "sentence-wrapped-before-the-date",
        "Dieser Bescheid wurde am\n19.10.2026 zur Post gegeben.",
        "2026-10-19",
    ),
    # a letter calls itself plainly "der Bescheid"
    ("sentence-the-decision", "Der Bescheid wurde am 19.10.2026 zur Post gegeben.", "2026-10-19"),
    (
        "sentence-this-other-kind",
        "Dieser Widerspruchsbescheid wurde am 19.10.2026 zur Post gegeben.",
        "2026-10-19",
    ),
    # "dem" after a weekday as well as "den"
    ("sentence-weekday-dem", "Der Bescheid wurde am Montag, dem 19.10.2026 zur Post gegeben.", "2026-10-19"),
    # plainer field labels, where a cell starts
    ("field-aufgegeben-am", "Aufgegeben am 19.10.2026", "2026-10-19"),
    ("field-versand-am", "Bescheid über Grundbesitzabgaben\nVersand am 19.10.2026", "2026-10-19"),
    ("field-versand-colon", "Steuernummer 123/456/78901   Versand: 19.10.2026", "2026-10-19"),
    ("field-absendevermerk", "Absendevermerk: 19.10.2026", "2026-10-19"),
    # the sender's own e-mail address beside the posting day says nothing about how the letter went out
    (
        "field-beside-the-sender-s-e-mail",
        "E-Mail: poststelle@finanzamt-musterstadt.example   Tag der Aufgabe zur Post: 19.10.2026",
        "2026-10-19",
    ),
    (
        "sentence-beside-the-sender-s-address",
        "E-Mail: poststelle@finanzamt-musterstadt.example   Der Bescheid wurde am 19.10.2026 zur Post gegeben.",
        "2026-10-19",
    ),
]


def test_each_cue_states_the_posting_day() -> None:
    def check(_id: str, text: str, day: str) -> None:
        statement = found(text)
        assert statement is not None and statement.day == D(day) and statement.other is None, statement
        assert statement.grounding == "verified" and statement.quote
        assert "Sehr geehrte" not in statement.quote and "Ihr Zeichen" not in statement.quote

    check_rows(CUES, check)


#: (id, page text). Each states a date near posting words that is NOT the day this letter was posted.
NEVER = [
    ("an-earlier-decision", "Der Bescheid vom 01.09.2026 wurde am 03.09.2026 zur Post gegeben."),
    ("our-earlier-letter", "Unser Schreiben vom 01.09.2026 haben wir am 02.09.2026 versandt."),
    ("the-person-s-letter", "Ihr Widerspruch wurde am 12.10.2026 zur Post gegeben."),
    ("the-person-did-it", "Sie haben das Formular am 12.10.2026 zur Post gegeben."),
    ("the-person-s-field", "Ihr Schreiben, abgesandt am 12.10.2026, ist eingegangen."),
    ("an-enclosure", "Die Anlage wurde am 19.10.2026 gesondert zur Post gegeben."),
    ("a-copy", "Eine Abschrift dieses Bescheids wurde am 19.10.2026 an Ihren Steuerberater versandt."),
    ("a-payment", "Bitte überweisen Sie den Betrag bis zum 19.11.2026."),
    ("a-deadline", "Senden Sie die Unterlagen spätestens am 30.10.2026 zur Post."),
    (
        "a-deadline-to-post-by",
        "Der Antrag gilt als rechtzeitig, wenn er spätestens am 30.10.2026 zur Post gegeben wurde.",
    ),
    ("a-payment-s-due-day", "Der Betrag ist am 19.10.2026 fällig und wurde zur Post gegeben."),
    ("the-future", "Der Bescheid wird am 19.10.2026 zur Post gegeben."),
    ("a-request", "Bitte geben Sie Ihre Erklärung bis 30.10.2026 zur Post."),
    ("negated", "Der Bescheid wurde nicht vor dem 19.10.2026 zur Post gegeben."),
    (
        "the-delivery-day",
        "Dieser Bescheid gilt am 23.10.2026 als bekannt gegeben (vierter Tag nach Aufgabe zur Post).",
    ),
    ("the-delivery-formula", "Er gilt am vierten Tag nach Aufgabe zur Post: 23.10.2026 als bekannt gegeben."),
    ("a-letter-s-date", "Ihr Schreiben vom 12.10.2026 haben wir erhalten."),
    ("a-shop-s-dispatch", "Ihre Bestellung wurde am 19.10.2026 versandt. Sendungsnummer 00340434"),
    ("a-shop-s-field", "Versandt am: 19.10.2026   Paket 1 von 2"),
    ("versandt-without-the-letter", "Der Bescheid wurde am 19.10.2026 versandt."),
    ("reads-two-ways", "Tag der Aufgabe zur Post: 03/05/2026"),
    ("no-year", "Tag der Aufgabe zur Post: 19.10."),
    (
        "the-letter-s-own-date-only",
        f"{HEADER}\nSehr geehrte Frau Beispiel,\nhiermit setzen wir die Steuer fest.",
    ),
    # a planned posting is no record of this letter's
    ("planned-in-brackets", "Versanddatum (voraussichtlich): 19.10.2026"),
    ("planned-geplant", "Versandtag (geplant): 19.10.2026"),
    ("planned-voraussichtlicher", "Voraussichtlicher Versandtag: 19.10.2026"),
    ("planned-geplante", "Geplante Aufgabe zur Post: 19.10.2026"),
    ("planned-naechste", "Nächste Aufgabe zur Post: 19.10.2026"),
    (
        "planned-another-decision-follows",
        "Der Rentenbescheid folgt mit gesonderter Post.\nVoraussichtliches Versanddatum: 19.10.2026",
    ),
    # another object's dispatch, or another letter's posting, in a field
    ("a-card-s-dispatch", "Ihre neue Gesundheitskarte – Versanddatum: 19.10.2026"),
    ("an-id-s-dispatch", "Ersatzausweis\nVersanddatum: 19.10.2026"),
    ("an-enclosure-s-field", "Anlage 1 (Berechnung)  Versanddatum 19.10.2026"),
    ("an-enclosure-s-field-in-a-list", "Anlage: Kontoauszug, Versanddatum 19.10.2026"),
    ("an-enclosure-s-label", "Beiliegend: Tag der Aufgabe zur Post: 19.10.2026"),
    ("an-enclosure-s-column", "Anlage zum Bescheid   Versanddatum: 19.10.2026"),
    ("another-decision-s-field", "Bescheid vom 12.10.2026 · Tag der Aufgabe zur Post: 19.10.2026"),
    ("another-decision-s-row", "Bescheid für 2024 | Datum 12.10.2026 | Aufgabe zur Post 19.10.2026"),
    ("sent-by-e-mail", "Versandt am: 19.10.2026 per E-Mail"),
    # another document posted, in the statutes' words: named by its own noun, or sent to someone else
    (
        "a-notice-to-another-office",
        "Die Kontrollmitteilung an das Finanzamt Beispielhausen wurde am 19.10.2026 zur Post gegeben.",
    ),
    ("a-notice-to-the-employer", "Eine Mitteilung an den Arbeitgeber wurde am 19.10.2026 zur Post gegeben."),
    ("a-demand-for-payment", "Die Zahlungsaufforderung wurde am 19.10.2026 zur Post gegeben."),
    ("other-decisions", "Die Bescheide für 2023 und 2024 wurden am 19.10.2026 zur Post gegeben."),
    ("another-kind-of-decision", "Der Widerspruchsbescheid wurde am 19.10.2026 zur Post gegeben."),
    # a label ending its line: the next line's first date may stand under another label
    (
        "another-column-s-date-under-the-label-s-line",
        "Finanzamt Musterstadt\nBekanntgabetag              Tag der Aufgabe zur Post\n"
        "23.10.2026                  19.10.2026\n",
    ),
    ("an-appointment-s-column", "Termin   Aufgabe zur Post\n22.10.2026   19.10.2026"),
    # a supposition or an example, not a record of this letter's posting
    (
        "a-supposition-wenn",
        "Wenn dieser Bescheid am 20.10.2026 zur Post gegeben wurde, gilt er am 24.10.2026 als bekannt gegeben.",
    ),
    (
        "a-supposition-sofern",
        "Sofern der Bescheid am 20.10.2026 zur Post gegeben wurde, gilt er am 24.10.2026 als bekannt gegeben.",
    ),
    (
        "a-supposition-falls",
        "Falls der Bescheid am 20.10.2026 zur Post gegeben wurde, gilt er am 24.10.2026 als bekannt gegeben.",
    ),
    ("an-example", "Beispiel: Aufgabe zur Post am 20.10.2026, Bekanntgabe am 24.10.2026."),
    (
        "an-example-z-b",
        "Ein Bescheid, der z. B. am 20.10.2026 zur Post gegeben wurde, gilt am 24.10.2026 als bekannt gegeben.",
    ),
    (
        "an-example-in-english",
        "If this letter was posted on 20 October 2026, it is deemed delivered on 23 October.",
    ),
    # a statute's label is held to a field's checks too: the line before it, and an e-mail
    ("a-plan-on-the-line-before", "Voraussichtlich:\nAufgabe zur Post 19.10.2026"),
    (
        "another-decision-follows-on-the-line-before",
        "Der Rentenbescheid folgt mit gesonderter Post.\nAufgabe zur Post: 19.10.2026",
    ),
    ("a-copy-on-the-line-before", "Abschrift\nTag der Aufgabe zur Post: 19.10.2026"),
    ("a-statute-s-label-by-e-mail", "Aufgabe zur Post: 19.10.2026 per E-Mail"),
    ("a-sentence-by-e-mail", "Dieser Bescheid wurde am 19.10.2026 per E-Mail versandt."),
    # a bracketed note that makes the day a plan or a bound; a second copy, posted again
    ("planned-vsl", "Versanddatum (vsl.): 19.10.2026"),
    ("planned-ca", "Versanddatum (ca.): 19.10.2026"),
    ("planned-plan", "Versanddatum (Plan): 19.10.2026"),
    ("planned-at-the-latest", "Absendetag (spätestens): 19.10.2026"),
    ("a-second-copy", "Zur Post gegeben am 19.10.2026 (Zweitschrift)"),
    ("posted-again", "Erneut zur Post gegeben am 19.10.2026"),
]


def test_what_never_counts_as_this_letter_s_posting_day() -> None:
    def check(_id: str, text: str) -> None:
        assert found(text) == PostingStatement()

    check_rows(NEVER, check)


def _box(text: str, x0: float, y0: float) -> list[Any]:
    """A word's box on a page (text, x0, y0, x1, y1), one character ≈ 0.01 of the page wide."""
    return [text, x0, y0, x0 + 0.01 * len(text), y0 + 0.012]


def _row(y: float, *cells: tuple[float, str]) -> list[list[Any]]:
    """The boxes of a row of cells: each (x, words), its words one after the other."""
    boxes = []
    for x, words in cells:
        for word in words.split():
            boxes.append(_box(word, x, y))
            x += 0.01 * len(word) + 0.005
    return boxes


def _letterhead(value: str, left: str = "Lindenweg 4") -> tuple[str, list[list[Any]]]:
    """A made-up DIN 5008 letterhead's two rows: the address column on the left, the posting label alone in the
    information block's column on the right, and on the next row the address's ``left`` words beside the
    ``value`` under the label — the text layer reads each row as one line."""
    text = f"{'Frau Erika Beispiel':<29}Tag der Aufgabe zur Post\n{left:<29}{value}\n"
    words = _row(0.20, (0.10, "Frau Erika Beispiel"), (0.65, "Tag der Aufgabe zur Post"))
    return text, words + _row(0.215, (0.10, left), (0.65, value))


#: A letterhead's information block: labels in one row, their values in the next (made up). (id, page text, the
#: page's word boxes, the posting day it states — or None).
TWO_ROWS = [
    (
        "posting-column-on-the-right",
        "Bekanntgabetag              Tag der Aufgabe zur Post\n23.10.2026                  19.10.2026\n",
        _row(0.20, (0.40, "Bekanntgabetag"), (0.65, "Tag der Aufgabe zur Post"))
        + _row(0.215, (0.40, "23.10.2026"), (0.65, "19.10.2026")),
        "2026-10-19",
    ),
    (
        "posting-column-on-the-right-without-boxes",
        "Bekanntgabetag              Tag der Aufgabe zur Post\n23.10.2026                  19.10.2026\n",
        [],
        None,
    ),
    # the value is the last thing on its row: a posting column with another column's value after it is left out
    # (the letter's date counts: early, never late)
    (
        "posting-column-on-the-left",
        "Tag der Aufgabe zur Post    Bekanntgabetag\n19.10.2026                  23.10.2026\n",
        _row(0.20, (0.40, "Tag der Aufgabe zur Post"), (0.65, "Bekanntgabetag"))
        + _row(0.215, (0.40, "19.10.2026"), (0.65, "23.10.2026")),
        None,
    ),
    (
        "posting-column-on-the-left-without-boxes",
        "Tag der Aufgabe zur Post    Bekanntgabetag\n19.10.2026                  23.10.2026\n",
        [],
        None,
    ),
    (
        "an-appointment-s-column-with-boxes",
        "Termin   Aufgabe zur Post\n22.10.2026   19.10.2026",
        _row(0.30, (0.40, "Termin"), (0.60, "Aufgabe zur Post"))
        + _row(0.315, (0.40, "22.10.2026"), (0.60, "19.10.2026")),
        "2026-10-19",
    ),
    (
        "the-only-date-under-another-column",
        "Bekanntgabetag   Tag der Aufgabe zur Post\n23.10.2026\n",
        _row(0.20, (0.40, "Bekanntgabetag"), (0.65, "Tag der Aufgabe zur Post"))
        + _row(0.215, (0.40, "23.10.2026")),
        None,
    ),
    (
        "beside-the-address",
        "Frau Erika Beispiel          Tag der Aufgabe zur Post\nLindenweg 4                  19.10.2026\n",
        _row(0.20, (0.10, "Frau Erika Beispiel"), (0.65, "Tag der Aufgabe zur Post"))
        + _row(0.215, (0.10, "Lindenweg 4"), (0.65, "19.10.2026")),
        "2026-10-19",
    ),
    ("alone-under-its-label-without-boxes", "Versanddatum\n19.10.2026\n", [], "2026-10-19"),
    # form A: a weekday (and "den") before the value, with and without boxes
    ("a-weekday-under-the-label", *_letterhead("Mo., 19.10.2026"), "2026-10-19"),
    ("a-weekday-and-den-under-the-label", *_letterhead("Montag, den 19.10.2026"), "2026-10-19"),
    ("a-month-s-name-under-the-label", *_letterhead("19. Oktober 2026"), "2026-10-19"),
    ("a-short-weekday-without-boxes", "Tag der Aufgabe zur Post\nMo., 19.10.2026\n", [], "2026-10-19"),
    ("a-long-weekday-without-boxes", "Versanddatum\nMontag, 19.10.2026\n", [], "2026-10-19"),
    ("den-without-boxes", "Versanddatum\nden 19.10.2026\n", [], "2026-10-19"),
    # never: a transcript without boxes with the address's words on the value's line
    ("address-words-without-boxes", "Tag der Aufgabe zur Post\nLindenweg 4   Mo., 19.10.2026\n", [], None),
    # never: another field's label or date in the value's cell (a deemed delivery, a payment, an appointment, a
    # deadline, the reader's letter), a date with words after it, two dates in the cell
    ("another-field-s-date-in-the-cell", *_letterhead("Bekanntgabetag 23.10.2026"), None),
    ("a-payment-deadline-in-the-cell", *_letterhead("Zahlungsfrist 21.10.2026"), None),
    ("an-appointment-in-the-cell", *_letterhead("Gesprächstermin 19.10.2026"), None),
    ("a-deadline-s-label-in-the-cell", *_letterhead("Frist 19.10.2026"), None),
    ("the-reader-s-letter-in-the-cell", *_letterhead("Ihre Nachricht 18.10.2026"), None),
    ("a-date-with-words-after-it", *_letterhead("19.10.2026 Termin 10 Uhr"), None),
    ("a-date-with-a-time-after-it", *_letterhead("19.10.2026 10:00 Uhr"), None),
    ("two-dates-in-the-cell", *_letterhead("19.10.2026 / 21.10.2026"), None),
    # never: a date after "vom", "bis", "seit"
    ("vom-before-the-value", *_letterhead("vom 19.10.2026"), None),
    ("seit-before-the-value", *_letterhead("seit 19.10.2026"), None),
    ("bis-before-the-value-without-boxes", "Versanddatum\nbis 19.10.2026\n", [], None),
    # never: the address column's last words date the value ("Ihr Schreiben vom" … its date under the label), or
    # date another letter on the value's row
    ("another-column-s-vom", *_letterhead("12.10.2026", left="Ihr Schreiben vom"), None),
    ("another-column-s-seit", *_letterhead("12.10.2026", left="Versichert seit"), None),
    ("another-letter-s-date-on-the-row", *_letterhead("19.10.2026", left="Datum 12.10.2026"), None),
    # never: a value beyond the reach under its label, nor the next column's only value
    (
        "a-date-far-below-the-label",
        "Frau Erika Beispiel          Tag der Aufgabe zur Post\n                             19.10.2026\n",
        _row(0.20, (0.10, "Frau Erika Beispiel"), (0.65, "Tag der Aufgabe zur Post"))
        + _row(0.30, (0.65, "19.10.2026")),
        None,
    ),
    (
        "the-only-date-under-the-next-column",
        "Tag der Aufgabe zur Post    Bekanntgabetag\n                            19.10.2026\n",
        _row(0.20, (0.40, "Tag der Aufgabe zur Post"), (0.65, "Bekanntgabetag"))
        + _row(0.215, (0.65, "19.10.2026")),
        None,
    ),
    # the line's text is held to the same as the boxes, since a text layer may have words without a box: a date
    # followed by more on its line, and a date after another in its cell, are never the value
    (
        "words-after-the-date-without-their-boxes",
        "Frau Erika Beispiel          Tag der Aufgabe zur Post\nLindenweg 4                  19.10.2026 Termin 10 Uhr\n",
        _row(0.20, (0.10, "Frau Erika Beispiel"), (0.65, "Tag der Aufgabe zur Post"))
        + _row(0.215, (0.10, "Lindenweg 4"), (0.65, "19.10.2026")),
        None,
    ),
    (
        "a-date-before-it-in-its-cell-without-its-box",
        "Frau Erika Beispiel          Tag der Aufgabe zur Post\nLindenweg 4                  19.10.2026 / 21.10.2026\n",
        _row(0.20, (0.10, "Frau Erika Beispiel"), (0.65, "Tag der Aufgabe zur Post"))
        + _row(0.215, (0.10, "Lindenweg 4"), (0.65, "21.10.2026")),
        None,
    ),
    # never: a date in the address column, whatever stands under the label below it ("Zimmer 19")
    (
        "a-month-s-name-in-the-left-column",
        "Frau Erika Beispiel          Tag der Aufgabe zur Post\n19. Oktober 2026\n                             Zimmer 19\n",
        _row(0.20, (0.10, "Frau Erika Beispiel"), (0.65, "Tag der Aufgabe zur Post"))
        + _row(0.215, (0.10, "19. Oktober 2026"))
        + _row(0.23, (0.65, "Zimmer 19")),
        None,
    ),
    (
        "a-table-s-row",
        "Steuerart   Zeitraum   Aufgabe zur Post\nESt   2025   19.10.2026",
        _row(0.40, (0.10, "Steuerart"), (0.40, "Zeitraum"), (0.65, "Aufgabe zur Post"))
        + _row(0.415, (0.10, "ESt"), (0.40, "2025"), (0.65, "19.10.2026")),
        None,
    ),
]


def test_a_label_ending_its_line_takes_only_the_date_under_it() -> None:
    """A posting label that ends its line takes the next line's date only where it stands under the label on the
    page (the words' boxes), as the header's "Datum" is read; without boxes only a label and a date each alone on
    their line; never a table's row — so another column's date (the day of delivery, an appointment) is never the
    posting day."""

    def check(_id: str, text: str, words: list[list[Any]], day: str | None) -> None:
        statement = posting_statement([(1, text, words, "text")], LETTER)
        assert statement is not None
        assert statement.day == (D(day) if day else None), statement

    check_rows(TWO_ROWS, check)


def test_a_photo_s_transcription_is_model_read_unless_a_text_page_says_it_too() -> None:
    field = "Tag der Aufgabe zur Post: 19.10.2026"
    photo = found(field, "transcript")
    assert photo is not None and (photo.day, photo.grounding) == (D("2026-10-19"), "model_read")
    both = posting_statement([(1, field, [], "transcript"), (2, field, [], "text")], LETTER)
    assert both is not None and both.grounding == "verified"


def test_a_photo_s_doubt_counts_once_for_its_to_do() -> None:
    """A photo letter: the to-do's quote and the posting day both come from the transcript. The posting day keeps
    the date at most ``medium`` and the quote read from a transcript lowers it one level: counted once, ``medium``
    — not ``low`` for one photo (``ingest.plan.compute_item``)."""
    page = (
        1,
        "Tag der Aufgabe zur Post: 19.10.2026\nDer Einspruch ist innerhalb eines Monats einzulegen.",
        [],
        "transcript",
    )
    item = ExtractedItem(
        kind="deadline",
        title="Object",
        date=DateSpec(
            type="relative",
            anchor="deemed_delivery",
            amount=1,
            unit="months",
            delivery_rule="de_admin_post",
            nature="objection",
        ),
        quote="Der Einspruch ist innerhalb eines Monats einzulegen.",
    )
    extraction = DocumentExtraction(
        kind="tax_assessment",
        title="Tax",
        summary="Tax.",
        explanation="Object.",
        document_date="2026-10-16",
        items=[item],
    )
    [verified] = verify_extraction("doc", extraction, [page]).items
    assert verified.evidence.grounding == "model_read"
    context = RuleContext(
        today=D("2026-10-22"),
        region="NW",
        document_date=LETTER,
        delivery_scope="ao",
        posting=posting_statement([page], LETTER),
    )
    computed = compute_item(verified, context, postal_buffer_days=4)
    assert computed.due_date == "2026-11-23"
    assert computed.receipt is not None and computed.receipt.confidence == "medium"


def test_two_posting_days_that_differ_are_both_kept() -> None:
    statement = found(
        "Tag der Aufgabe zur Post: 21.10.2026\n\nDieser Bescheid wurde am 19.10.2026 zur Post gegeben."
    )
    assert statement is not None
    assert (statement.day, statement.other) == (D("2026-10-19"), D("2026-10-21"))
    assert statement.quote == "Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."
    assert statement.other_quote == "Tag der Aufgabe zur Post: 21.10.2026"
    agree = found(
        "Tag der Aufgabe zur Post: 19.10.2026\n\nDieser Bescheid wurde am 19.10.2026 zur Post gegeben."
    )
    assert agree is not None and (agree.day, agree.other) == (D("2026-10-19"), None)


#: (id, a key fact's label, its value, the later posting day it names — or None).
KEY_FACTS = [
    ("german-label", "Tag der Aufgabe zur Post", "19.10.2026", "2026-10-19"),
    ("english-label", "Posting date", "19 October 2026", "2026-10-19"),
    ("dispatch", "Date of dispatch", "Mon 19 Oct 2026", "2026-10-19"),
    ("on-the-letter-s-date", "Versanddatum", "16.10.2026", None),
    ("the-delivery-day", "Deemed delivery (4th day after posting)", "23.10.2026", None),
    ("a-deadline", "Objection deadline", "23.11.2026", None),
    ("not-a-posting-label", "Tax year", "2025", None),
    ("two-dates", "Versanddatum", "19.10.2026 / 20.10.2026", None),
]


def test_a_later_posting_day_among_the_reading_s_key_facts() -> None:
    """A key fact labelled as a posting day, one date later than the letter's: only ever a note for the engine
    (``RuleContext.posting_read``); never a fact about delivery or a deadline."""

    def check(_id: str, label: str, value: str, day: str | None) -> None:
        fact = ExtractedFact(label=label, value=value, quote=value)
        assert read_posting_day([fact], LETTER) == (D(day) if day else None)

    check_rows(KEY_FACTS, check)
    assert read_posting_day([ExtractedFact(label="Versanddatum", value="19.10.2026", quote="")], None) is None


def test_without_pages_nothing_was_read() -> None:
    """No pages (a to-do added by hand, a context built without the letter): ``None``, so the engine keeps
    today's behaviour, as for the rules tools."""
    assert posting_statement([], LETTER) is None
    assert posting_statement([(1, "", [], "none")], LETTER) == PostingStatement()


# ------------------------------------------------------------------------------- from a letter to the to-do

TODAY = "2026-10-22"

#: A made-up tax assessment dated Fri 16 Oct 2026 that states it was posted Mon 19 Oct, with a reading that
#: names the objection period from deemed delivery (and leaves the posting day out, as a reading may).
POSTED_LATER = Letter(
    marker="Aufgabeprobe",
    pages=(
        (
            "Finanzamt Musterstadt · Postfach 10 20 30 · 12345 Musterstadt",
            "SPECIMEN Aufgabeprobe",
            "Steuernummer 123/456/78901   Datum 16.10.2026",
            "Tag der Aufgabe zur Post: 19.10.2026",
            "Bescheid für 2025 über Einkommensteuer",
            "Sehr geehrte Frau Beispiel,",
            "die Einkommensteuer wird auf 1.234,00 EUR festgesetzt.",
            "Rechtsbehelfsbelehrung",
            "Gegen diesen Bescheid ist der Einspruch gegeben. Der Einspruch ist innerhalb eines Monats nach",
            "Bekanntgabe dieses Bescheides beim Finanzamt Musterstadt einzulegen.",
        ),
    ),
    payload={
        "kind": "tax_assessment",
        "title": "Income tax 2025",
        "summary": "Income tax assessment.",
        "explanation": "You may object within a month.",
        "sender": {"name": "Finanzamt Musterstadt", "kind": "tax_office"},
        "document_date": "2026-10-16",
        "remedy": {"type": "einspruch", "quote": "Gegen diesen Bescheid ist der Einspruch gegeben."},
        "items": [
            {
                "kind": "deadline",
                "title": "Object to the assessment",
                "date": {
                    "type": "relative",
                    "anchor": "deemed_delivery",
                    "amount": 1,
                    "unit": "months",
                    "delivery_rule": "de_admin_post",
                    "nature": "objection",
                    "legal_basis": "§ 355 AO",
                },
                "quote": "Der Einspruch ist innerhalb eines Monats nach",
            }
        ],
    },
)


@pytest.fixture
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.mark.usefixtures("pinned_today")
async def test_a_letter_s_posting_day_reaches_the_stored_to_do(data_dir: Path) -> None:
    """Through the app's own path (upload, read, verify, compute, plan): the page's posting day starts the deemed
    delivery — posted Mon 19 Oct → Fri 23 Oct → Mon 23 Nov —, the receipt says where it was found and names the
    letter's date's deadline (Fri 20 Nov) as the safe date, and the to-do is as sure as any verified fact."""
    router = ApiRouter()
    router.letters = (POSTED_LATER, *router.letters)
    router.payloads[POSTED_LATER.marker] = POSTED_LATER.extraction()
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("steuer.pdf", POSTED_LATER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [objection] = [item for item in api.ctx.store.list_items(doc_id=doc_id) if item.kind == "deadline"]
        assert objection.due_date == "2026-11-23"
        receipt = objection.computation
        assert receipt is not None and receipt.safe_date == "2026-11-20"
        assert POSTED_ON_LETTER in receipt.rule_ids and receipt.confidence == "high"
        assert any("“Tag der Aufgabe zur Post: 19.10.2026”" in step.label for step in receipt.steps)
        assert not needs_check(objection)


@pytest.mark.usefixtures("pinned_today")
async def test_two_posting_days_on_a_letter_make_its_to_do_please_check(data_dir: Path) -> None:
    letter = Letter(
        marker="Zweiaufgabe",
        pages=(
            tuple(
                line.replace("Aufgabeprobe", "Zweiaufgabe")
                if "Aufgabeprobe" in line
                else line + "   Absendetag: 20.10.2026"
                if line.startswith("Tag der Aufgabe")
                else line
                for line in POSTED_LATER.pages[0]
            ),
        ),
        payload=POSTED_LATER.payload,
    )
    router = ApiRouter()
    router.letters = (letter, *router.letters)
    router.payloads[letter.marker] = letter.extraction()
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("zwei.pdf", letter.pdf())))["documents"][0]["id"]
        await api.read_all()
        [objection] = [item for item in api.ctx.store.list_items(doc_id=doc_id) if item.kind == "deadline"]
        assert objection.due_date == "2026-11-23"  # from the earlier, Mon 19 Oct
        assert objection.computation is not None and TWO_POSTING_DAYS in objection.computation.rule_ids
        assert objection.computation.confidence == "low" and needs_check(objection)


#: A made-up health insurer's decision (SGB X) dated Fri 16 Oct 2026 that dates the dispatch of the person's new
#: card, not its own posting.
A_CARD_S_DISPATCH = Letter(
    marker="Kartenprobe",
    pages=(
        (
            "Musterkasse Musterstadt · Postfach 4 · 12345 Musterstadt",
            "SPECIMEN Kartenprobe",
            "Versichertennummer A123456789   Datum 16.10.2026",
            "Ihre neue Gesundheitskarte – Versanddatum: 19.10.2026",
            "Bescheid über Ihre Familienversicherung",
            "Sehr geehrter Herr Beispiel,",
            "die Familienversicherung Ihrer Tochter endet am 31.10.2026.",
            "Rechtsbehelfsbelehrung",
            "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
        ),
    ),
    payload={
        "kind": "health_insurance",
        "title": "Family insurance ends",
        "summary": "Family insurance ends.",
        "explanation": "You may object within a month.",
        "sender": {"name": "Musterkasse Musterstadt", "kind": "health_insurer"},
        "document_date": "2026-10-16",
        "remedy": {"type": "widerspruch", "quote": "Gegen diesen Bescheid kann innerhalb eines Monats"},
        "items": [
            {
                "kind": "deadline",
                "title": "Object to the decision",
                "date": {
                    "type": "relative",
                    "anchor": "deemed_delivery",
                    "amount": 1,
                    "unit": "months",
                    "delivery_rule": "de_admin_post",
                    "nature": "objection",
                    "legal_basis": "§ 84 SGG",
                },
                "quote": "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
            }
        ],
    },
)


@pytest.mark.usefixtures("pinned_today")
async def test_a_card_s_dispatch_day_never_moves_the_letter_s_deadline(data_dir: Path) -> None:
    """Through the app's own path: the card's "Versanddatum" is not this letter's posting day, so the objection
    counts from the letter's date — Fri 16 Oct → Tue 20 Oct (§ 37 Abs. 2 SGB X) → Fri 20 Nov — not from 19 Oct."""
    router = ApiRouter()
    router.letters = (A_CARD_S_DISPATCH, *router.letters)
    router.payloads[A_CARD_S_DISPATCH.marker] = A_CARD_S_DISPATCH.extraction()
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("karte.pdf", A_CARD_S_DISPATCH.pdf())))["documents"][0]["id"]
        await api.read_all()
        [objection] = [item for item in api.ctx.store.list_items(doc_id=doc_id) if item.kind == "deadline"]
        assert objection.due_date == "2026-11-20"
        assert objection.computation is not None and POSTED_ON_LETTER not in objection.computation.rule_ids


@pytest.mark.usefixtures("pinned_today")
async def test_a_posting_day_only_the_reading_s_key_facts_name_is_named_on_the_to_do(data_dir: Path) -> None:
    """Through the app's own path: the page states no posting day, the reading names one (Mon 19 Oct) only among
    its key facts. The date stays the letter's date's (Fri 20 Nov), the receipt names the later deadline (Mon 23
    Nov), and the to-do is one level less sure."""
    letter = Letter(
        marker="Faktprobe",
        pages=(
            tuple(
                line.replace("Aufgabeprobe", "Faktprobe")
                for line in POSTED_LATER.pages[0]
                if not line.startswith("Tag der Aufgabe")
            ),
        ),
        payload={
            **POSTED_LATER.payload,
            "key_facts": [
                {"label": "Tag der Aufgabe zur Post", "value": "19.10.2026", "quote": "19.10.2026"}
            ],
        },
    )
    router = ApiRouter()
    router.letters = (letter, *router.letters)
    router.payloads[letter.marker] = letter.extraction()
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("fakt.pdf", letter.pdf())))["documents"][0]["id"]
        await api.read_all()
        [objection] = [item for item in api.ctx.store.list_items(doc_id=doc_id) if item.kind == "deadline"]
        assert objection.due_date == "2026-11-20"
        receipt = objection.computation
        assert receipt is not None and receipt.confidence == "medium"
        assert any("the deadline is Mon 23 Nov 2026" in warning for warning in receipt.warnings), (
            receipt.warnings
        )
