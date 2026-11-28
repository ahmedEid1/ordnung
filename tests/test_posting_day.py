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
from ordnung.ingest import posting
from ordnung.ingest.plan import compute_item, needs_check, verify_extraction
from ordnung.ingest.posting import posting_statement, read_posting_day
from ordnung.ingest.verify import date_spans
from ordnung.models import DateSpec, DocumentExtraction, ExtractedFact, ExtractedItem
from ordnung.rules.deadlines import POSTED_ON_LETTER, TWO_POSTING_DAYS, PostingStatement, RuleContext
from ordnung.rules.due import compute_due
from test_api_support import ApiRouter, api_for

D = date.fromisoformat
LETTER = D("2026-10-16")
HEADER = (
    "Finanzamt Musterstadt · Postfach 10 20 30 · 12345 Musterstadt\n"
    "Frau Erika Beispiel   Ihr Zeichen   Bitte bei Antwort angeben\n"
    "Lindenweg 4   -   Steuernummer 123/456/78901\n"
    "12345 Musterstadt   Datum 16.10.2026\n"
)


#: The salutation that ends the letterhead, and the body's first sentence.
SALUTATION = "\nSehr geehrte Frau Beispiel,\nhiermit setzen wir die Steuer fest.\n"
#: The remedy notice that ends the letter.
REMEDY = "\nGegen diesen Bescheid ist der Einspruch gegeben."


def found(text: str, source: str = "text") -> PostingStatement | None:
    return posting_statement([(1, text, [], source)], LETTER)


def head(top: str) -> str:
    """A made-up letter with ``top`` in its letterhead: under the header's date line, above the salutation."""
    return f"{HEADER}{top}{SALUTATION}{REMEDY}"


def body(text: str) -> str:
    """A made-up letter with ``text`` in its body: after the salutation, before the remedy notice."""
    return f"{HEADER}{SALUTATION}{text}{REMEDY}"


def everywhere(text: str, *, heading: bool = True) -> Iterator[str]:
    """``text`` as a page of its own, in a letter's letterhead, in its body, and (``heading``) in its body under a
    notice's heading, the one place a sentence form counts."""
    yield text
    yield head(text)
    yield body(text)
    if heading:
        yield body(f"Hinweis: {text}")


def under_a_heading(sentence: str) -> str:
    """A made-up letter whose body ends with a notice's heading and ``sentence``."""
    return f"{HEADER}{SALUTATION}Hinweis: {sentence}\n"


def due(page: str, *, scope: str = "ao", region: str = "NW") -> str | None:
    """The objection deadline the engine gives for the made-up letter of Fri 16 Oct 2026 whose only page is
    ``page``: from the letter's date Fri 20 Nov (AO, NW) — a posting day the page states moves it."""
    spec = DateSpec(
        type="relative",
        anchor="deemed_delivery",
        amount=1,
        unit="months",
        delivery_rule="de_admin_post",
        nature="objection",
    )
    context = RuleContext(
        today=D("2026-10-27"),
        region=region,
        document_date=LETTER,
        delivery_scope=scope,
        posting=posting_statement([(1, page, [], "text")], LETTER),
    )
    return compute_due(spec, context).due_date


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


#: (id, page text, the posting day it states). Each a way an authority writes it: a field in the letterhead, a
#: sentence under a notice's heading.
CUES = [
    ("field-in-the-header", head("Tag der Aufgabe zur Post: 19.10.2026\n"), "2026-10-19"),
    ("field-datum-der-aufgabe", head("Datum der Aufgabe zur Post: Montag, 19. Oktober 2026"), "2026-10-19"),
    ("field-under-its-label", head("Tag der Aufgabe zur Post\n19.10.2026\n"), "2026-10-19"),
    ("field-without-a-colon", head("Tag der Aufgabe zur Post 19.10.2026"), "2026-10-19"),
    ("field-absendedatum", head("Absendedatum: 19.10.2026"), "2026-10-19"),
    ("field-versandt-am", head("Grundbesitzabgaben 2026\nVersandt am: 19.10.2026"), "2026-10-19"),
    ("field-tag-der-absendung", head("Tag der Absendung: 19.10.2026"), "2026-10-19"),
    ("field-datum-des-versands", head("Datum des Versands: 19.10.2026"), "2026-10-19"),
    ("field-short-weekday", head("Tag der Aufgabe zur Post: Mo., 19.10.2026"), "2026-10-19"),
    ("field-ist-der", head("Tag der Aufgabe zur Post ist der 19.10.2026."), "2026-10-19"),
    ("field-statute-s-note", head("Aufgabe zur Post am Montag, den 19.10.2026"), "2026-10-19"),
    ("field-zur-post-gegeben-am", head("Zur Post gegeben am 19.10.2026."), "2026-10-19"),
    # the letterhead's lines above may be any closed field: empty, a number, a colon, a full stop
    ("field-after-a-blank-line", head("\nTag der Aufgabe zur Post: 19.10.2026"), "2026-10-19"),
    ("field-after-a-number", head("Steuernummer 123/456/78901\nVersanddatum: 19.10.2026"), "2026-10-19"),
    ("field-after-a-colon", head("Bearbeitungsstand:\nVersanddatum: 19.10.2026"), "2026-10-19"),
    ("field-after-a-full-stop", head("Zimmer 4.\nVersanddatum: 19.10.2026"), "2026-10-19"),
    (
        "sentence-zur-post-gegeben",
        body("Hinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben. Er ergeht unter Vorbehalt."),
        "2026-10-19",
    ),
    (
        "sentence-zur-post-gegeben-worden",
        body("Hinweis: Dieser Bescheid ist am Montag, den 19.10.2026 zur Post gegeben worden."),
        "2026-10-19",
    ),
    (
        "sentence-wrapped",
        body("Hinweis: Dieser Bescheid wurde am 19.10.2026 zur\nPost gegeben."),
        "2026-10-19",
    ),
    (
        "sentence-der-post-uebergeben",
        body("Hinweis: Dieses Schreiben wurde am 19.10.2026 der Post übergeben."),
        "2026-10-19",
    ),
    (
        "sentence-versandt-this-letter",
        body("Hinweis: Dieser Bescheid wurde am 19.10.2026 versandt."),
        "2026-10-19",
    ),
    (
        "sentence-after-a-heading-on-its-line",
        f"{HEADER}Hinweis zur Bekanntgabe: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben.",
        "2026-10-19",
    ),
    ("english-field", head("Date of posting: 19 October 2026"), "2026-10-19"),
    ("english-sentence", body("Hinweis: This letter was posted on 19 October 2026."), "2026-10-19"),
    ("field-aufgegeben-zur-post", head("Aufgegeben zur Post am 19.10.2026"), "2026-10-19"),
    ("field-datum-des-postausgangs", head("Datum des Postausgangs: 19.10.2026"), "2026-10-19"),
    ("field-abgesendet-am", head("Abgesendet am 19.10.2026"), "2026-10-19"),
    ("field-absendung-am", head("Absendung am 19.10.2026"), "2026-10-19"),
    # a sentence that goes on on the next line after "am": the date is still its own
    (
        "sentence-wrapped-before-the-date",
        body("Hinweis: Dieser Bescheid wurde am\n19.10.2026 zur Post gegeben."),
        "2026-10-19",
    ),
    (
        "sentence-this-other-kind",
        body("Hinweis: Dieser Widerspruchsbescheid wurde am 19.10.2026 zur Post gegeben."),
        "2026-10-19",
    ),
    # "dem" after a weekday as well as "den"
    (
        "sentence-weekday-dem",
        body("Hinweis: Dieser Bescheid wurde am Montag, dem 19.10.2026 zur Post gegeben."),
        "2026-10-19",
    ),
    # plainer field labels, in the letterhead only
    ("field-aufgegeben-am", head("Aufgegeben am 19.10.2026"), "2026-10-19"),
    ("field-versand-am", head("Grundbesitzabgaben 2026\nVersand am 19.10.2026"), "2026-10-19"),
    ("field-versand-colon", head("Versand: 19.10.2026"), "2026-10-19"),
    ("field-absendevermerk", head("Absendevermerk: 19.10.2026"), "2026-10-19"),
    ("field-posted", head("Posted: 19 October 2026"), "2026-10-19"),
]


def test_each_cue_states_the_posting_day() -> None:
    def check(_id: str, text: str, day: str) -> None:
        statement = found(text)
        assert statement is not None and statement.day == D(day) and statement.other is None, statement
        assert statement.grounding == "verified" and statement.quote
        assert "Sehr geehrte" not in statement.quote and "Ihr Zeichen" not in statement.quote
        # and through the engine: counted from Mon 19 Oct (deemed delivery Thu 22 Oct), Mon 23 Nov
        assert due(text) == "2026-11-23", text

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
        for page in everywhere(text):
            assert found(page) == PostingStatement(), page

    check_rows(NEVER, check)


#: Wordings that counted in an earlier round and are no longer one of the closed forms: a label after other words
#: in its line or cell (Addendum 6: without word boxes only a label that starts its line), a sentence that is not a
#: whole clause of a listed form. The letter's date stays the start, the early side.
NO_LONGER = [
    ("a-label-after-other-cells", "Steuernummer 123/456   Datum 16.10.2026   Aufgabe zur Post: 19.10.2026"),
    ("a-label-in-mid-line", "Steuernummer 123/456/78901 Tag der Aufgabe zur Post 19.10.2026"),
    ("a-label-in-the-footer", "Seite 1 von 2 · Absendedatum: 19.10.2026 · Bankverbindung siehe Rückseite"),
    ("the-present-erfolgt-may-be-a-plan", "Die Aufgabe zur Post erfolgt am Mo 19.10.2026."),
    ("a-note-in-brackets", "Aufgabe zur Post (Absendevermerk): 19.10.2026"),
    ("a-label-after-a-lead", "Bitte beachten Sie: Tag der Aufgabe zur Post ist der 19.10.2026."),
    ("a-subject-with-a-date", "Der Bescheid vom 16.10.2026 wurde am 19. Oktober 2026 abgesandt."),
    ("more-in-the-label-s-cell", "Tag der Aufgabe zur Post: 19.10.2026 (Bekanntgabe: 23.10.2026)"),
    ("an-unlisted-subject", "Er wurde aufgegeben zur Post am 19.10.2026."),
    ("a-label-after-a-column", "Steuernummer 123/456/78901   Versand: 19.10.2026"),
    # a document named on the line above: the field may be that document's (here this letter's own subject: the
    # letter's date counts, the early side)
    ("a-document-on-the-line-above", "Bescheid über Grundbesitzabgaben\nVersandt am: 19.10.2026"),
    (
        "beside-the-sender-s-e-mail-without-boxes",
        "E-Mail: poststelle@finanzamt-musterstadt.example   Tag der Aufgabe zur Post: 19.10.2026",
    ),
    (
        "a-sentence-after-a-column",
        "E-Mail: poststelle@finanzamt-musterstadt.example   Der Bescheid wurde am 19.10.2026 zur Post gegeben.",
    ),
]

#: A label beside its date after other words in its line or cell (the third protocol review: each moved a right
#: deadline three days late): never through the field path, whatever the other cells say.
BESIDE_AFTER_WORDS = [
    ("another-year-s-decision", "Bescheid für 2024 - Tag der Aufgabe zur Post: 19.10.2026"),
    ("a-first-decision-s-row", "Erstbescheid über Grundsteuer   Absendedatum: 19.10.2026"),
    ("a-reminder-s-row", "1. Mahnung   Versanddatum: 19.10.2026"),
    ("a-reminder-s-table-row", "2. Mahnung | Versandt am: 19.10.2026"),
    ("a-decision-on-an-objection-s-row", "Widerspruchsbescheid   Tag der Aufgabe zur Post: 19.10.2026"),
    ("a-return-receipt-s-row", "Rückschein   Versanddatum: 19.10.2026"),
    (
        "a-strong-label-in-a-sentence",
        "Den Bescheid für Ihren Ehemann betreffend gilt als Tag der Aufgabe zur Post: 19.10.2026",
    ),
    ("a-contested-posting-day", "Bestrittener Tag der Aufgabe zur Post: 19.10.2026"),
    ("a-claimed-posting-day", "Vom Kläger behaupteter Tag der Aufgabe zur Post: 19.10.2026"),
]

#: Suppositions and examples, none of which records a posting (the third law review: each moved the date three
#: days later than the law, at high confidence).
SUPPOSED = [
    (
        "verb-first-ist-worden",
        "Ist dieser Bescheid am 19.10.2026 zur Post gegeben worden, gilt er am 23.10.2026 als bekannt gegeben.",
    ),
    (
        "verb-first-erfolgte",
        "Erfolgte die Aufgabe zur Post am 19.10.2026, so gilt der Bescheid am 23.10.2026 als bekannt gegeben.",
    ),
    (
        "verb-first-wurde",
        "Wurde der Bescheid am 19.10.2026 zur Post gegeben, beginnt die Frist am 24.10.2026.",
    ),
    ("im-fall", "Im Fall der Aufgabe zur Post am 19.10.2026 endet die Frist am 23.11.2026."),
    ("bei", "Bei einer Aufgabe zur Post am 19.10.2026 wäre der Bescheid am 23.10.2026 bekannt gegeben."),
    (
        "gesetzt-den-fall",
        "Gesetzt den Fall, der Bescheid wurde am 19.10.2026 zur Post gegeben, so gilt er am 23.10.2026 als bekannt "
        "gegeben.",
    ),
    (
        "rechenbeispiel",
        "Rechenbeispiel: Aufgabe zur Post am 19.10.2026, Bekanntgabe am 23.10.2026, Fristende am 23.11.2026.",
    ),
    ("musterfall", "Musterfall: Der Bescheid wurde am 19.10.2026 zur Post gegeben."),
    (
        "unterstellt",
        "Unterstellt, die Aufgabe zur Post erfolgte am 19.10.2026, so gilt der Bescheid am 23.10.2026 als bekannt "
        "gegeben.",
    ),
    (
        "zur-veranschaulichung",
        "Zur Veranschaulichung: Aufgabe zur Post am 19.10.2026 = Bekanntgabe am 23.10.2026.",
    ),
    (
        "illustration",
        "Illustration: posted on 19 October 2026, the notice counts as delivered on 23 October 2026.",
    ),
    (
        "bei-only-listed-words",
        "Bei Aufgabe zur Post am 19.10.2026 gilt der Bescheid am 23.10.2026 als bekannt gegeben.",
    ),
    ("question", "Wurde der Bescheid am 19.10.2026 zur Post gegeben?"),
    (
        "so-after-it",
        "Der Bescheid wurde am 19.10.2026 zur Post gegeben, so gilt er am 23.10.2026 als bekannt gegeben.",
    ),
    ("gilt-als-after-it", "Die Aufgabe zur Post erfolgte am 19.10.2026 und gilt als Beginn der Frist."),
    ("falls-on-the-line-before", "Falls\nDer Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ("beispiel-on-the-line-before", "Beispiel:\nDer Bescheid wurde am 19.10.2026 zur Post gegeben."),
]

#: Another document's, another person's or another time's posting, a doubt, a bound, a plan: the reviewers'
#: made-up sentences and fields (three rounds, two lenses), each refused by the closed forms.
REVIEWED = [
    # another decision or document, by an adjective, a genitive or a phrase in its subject, or by its own noun
    ("the-previous-year-s", "Der Bescheid des Vorjahres wurde am 19.10.2026 zur Post gegeben."),
    ("the-first", "Der erste Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ("the-second", "Der zweite Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ("the-original", "Der ursprüngliche Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ("the-earlier", "Der frühere Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ("the-changed", "Der geänderte Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ("the-contested", "Der angefochtene Bescheid wurde am 19.10.2026 zur Post gegeben."),
    (
        "the-court-s-letter",
        "Das Schreiben des Amtsgerichts Musterstadt wurde am 19.10.2026 zur Post gegeben.",
    ),
    ("to-another-person", "Der Bescheid an Herrn Max Mustermann wurde am 19.10.2026 zur Post gegeben."),
    ("to-the-husband", "Der Bescheid an Ihren Ehemann wurde am 19.10.2026 zur Post gegeben."),
    ("against-another-person", "Bescheid gegen Herrn Max Mustermann wurde am 19.10.2026 zur Post gegeben."),
    ("for-another-year", "Der Bescheid für 2024 wurde am 19.10.2026 zur Post gegeben."),
    ("for-2023", "Der Bescheid für 2023 wurde am 19.10.2026 zur Post gegeben."),
    (
        "about-another-tax",
        "Der Bescheid über die Hundesteuer wurde am 19.10.2026 zur Post gegeben; dieser Bescheid ändert ihn.",
    ),
    ("the-income-tax-2024", "Der Einkommensteuerbescheid 2024 wurde am 19.10.2026 zur Post gegeben."),
    ("an-initial-decision", "Der Ausgangsbescheid wurde am 19.10.2026 zur Post gegeben."),
    ("a-liability-decision", "Der Haftungsbescheid wurde am 19.10.2026 zur Post gegeben."),
    ("advance-payments", "Der Vorauszahlungsbescheid wurde am 19.10.2026 zur Post gegeben."),
    (
        "advance-payments-quoted",
        "Der Bescheid über Vorauszahlungen, zur Post gegeben am 19.10.2026, bleibt unberührt.",
    ),
    ("another-office-s", "Das Finanzamt Beispielhausen hat seinen Bescheid am 19.10.2026 zur Post gegeben."),
    (
        "with-another-decision",
        "Dieses Schreiben wurde zusammen mit dem Bescheid der Stadtkasse am 19.10.2026 versandt.",
    ),
    ("the-city-treasury-s", "Der Bescheid der Stadtkasse wurde am 19.10.2026 zur Post gegeben."),
    ("our-reminder", "Unser Erinnerungsschreiben wurde am 19.10.2026 zur Post gegeben."),
    ("a-reminder", "Die Mahnung wurde am 19.10.2026 zur Post gegeben."),
    ("a-reminder-versandt", "Die Mahnung wurde am 19.10.2026 versandt."),
    ("a-reminder-zur-post", "Die Erinnerung wurde am 19.10.2026 zur Post gegeben."),
    ("an-invoice", "Die Rechnung wurde am 19.10.2026 versandt."),
    (
        "information-to-another-office",
        "Die Auskunft an die Familienkasse wurde am 19.10.2026 zur Post gegeben.",
    ),
    ("a-leaflet", "Das Merkblatt wurde am 19.10.2026 zur Post gegeben."),
    ("a-form", "Der Vordruck wurde am 19.10.2026 zur Post gegeben."),
    ("a-questionnaire", "Der Fragebogen wurde am 19.10.2026 zur Post gegeben."),
    ("a-transfer-slip", "Der Überweisungsträger wurde am 19.10.2026 zur Post gegeben."),
    ("a-hearing-letter", "Das Anhörungsschreiben wurde am 19.10.2026 zur Post gegeben."),
    (
        "a-copy-for-the-adviser",
        "Die Ausfertigung für den Steuerberater wurde am 19.10.2026 zur Post gegeben.",
    ),
    ("a-forwarding", "Die Nachsendung wurde am 19.10.2026 zur Post gegeben."),
    (
        "also-to-the-representative",
        "Dieser Bescheid wurde am 19.10.2026 auch an Ihren Bevollmächtigten versandt.",
    ),
    ("the-card", "Die elektronische Gesundheitskarte wurde am 19.10.2026 versandt."),
    ("a-statement-of-account", "Kontoauszug Nr. 10, versandt am 19.10.2026"),
    ("an-earlier-quoted", "Mit Bescheid vom 01.09.2026, zur Post gegeben am 19.10.2026, setzten wir fest"),
    ("an-earlier-quoted-in", "Im Bescheid für 2024, zur Post gegeben am 19.10.2026, wurde festgesetzt"),
    (
        "a-hearing-quoted",
        "Mit Schreiben vom 12.10.2026, zur Post gegeben am 19.10.2026, haben wir Sie angehört.",
    ),
    (
        "against-the-decision-of",
        "Gegen den Bescheid vom 01.10.2026 (zur Post gegeben am 19.10.2026) können Sie Einspruch einlegen.",
    ),
    (
        "our-earlier-posted",
        "Unser Bescheid vom 02.10.2026 wurde am 05.10.2026 zur Post gegeben; er ist bestandskräftig.",
    ),
    ("a-change-to-be-sent", "Der Änderungsbescheid vom 20.10.2026 wird gesondert versandt."),
    ("the-other-subject", "Die Aufgabe zur Post am 19.10.2026 betraf den Erstbescheid."),
    (
        "for-the-remedy",
        "Laut Vermerk der Poststelle erfolgte die Aufgabe zur Post am 19.10.2026 für die Abhilfe.",
    ),
    ("plural-decisions", "Die Bescheide für 2023 und 2024 wurden am 19.10.2026 zur Post gegeben."),
    (
        "a-lowercase-adviser",
        "Steuerbescheid. Erinnerung: das schreiben ihres Steuerberaters wurde am 19.10.2026 zur Post gegeben.",
    ),
    ("english-a-reminder", "The reminder was posted on 19 October 2026."),
    ("english-our-previous", "Our previous notice was posted on 19 October 2026."),
    ("english-for-the-neighbour", "The decision for your neighbour was posted on 19 October 2026."),
    ("english-an-item", "Your item was posted on 19 October 2026."),
    ("english-your-letter", "Your letter, posted on 19 October 2026, reached us."),
    ("english-your-letter-arrived", "Your letter, posted on 19 October 2026, arrived."),
    # the person's letter or act
    (
        "the-person-s-declaration",
        "Wir haben Ihre Erklärung erhalten, die am 19.10.2026 zur Post gegeben wurde.",
    ),
    (
        "the-person-s-tax-return",
        "Die Steuererklärung der Frau Beispiel wurde am 19.10.2026 zur Post gegeben.",
    ),
    ("by-postmark", "Laut Poststempel wurde der Einspruch am 19.10.2026 zur Post gegeben."),
    (
        "the-person-s-objection",
        "Der Einspruch wurde am 19.10.2026 zur Post gegeben und ging am 21.10.2026 ein.",
    ),
    (
        "the-person-s-objection-quoted",
        "Ihr Einspruch, zur Post gegeben am 19.10.2026, ist fristgerecht eingegangen.",
    ),
    ("the-person-posted", "Laut Poststempel haben Sie Ihre Erklärung am 19.10.2026 zur Post gegeben."),
    ("by-the-person", "Die Steuererklärung wurde von Ihnen am 19.10.2026 zur Post gegeben."),
    ("the-person-s-letter-received", "Wir haben Ihr am 19.10.2026 abgesandtes Schreiben erhalten."),
    ("forwarded", "Ihr Antrag wurde am 19.10.2026 an die Krankenkasse versandt."),
    (
        "to-the-adviser",
        "Eine Durchschrift ging an Ihren Steuerberater; dem Steuerberater wurde der Bescheid am 19.10.2026 zur Post gegeben.",
    ),
    ("english-you-posted", "You posted your appeal on 19 October 2026."),
    # a doubt, a claim, a question
    ("a-doubted-posting", "Die behauptete Aufgabe zur Post am 19.10.2026 ist zweifelhaft."),
    ("a-disputed-posting", "Die Aufgabe zur Post am 19.10.2026 bestreitet die Klägerin."),
    ("an-unclear-posting", "Ob die Aufgabe zur Post am 19.10.2026 erfolgte, ist unklar."),
    ("should-have-been", "Der Bescheid hätte am 19.10.2026 zur Post gegeben werden müssen."),
    (
        "by-mistake",
        "Der Bescheid wurde versehentlich am 19.10.2026 an eine falsche Anschrift zur Post gegeben.",
    ),
    ("to-an-old-address", "Der Bescheid wurde am 19.10.2026 an Ihre alte Anschrift zur Post gegeben."),
    ("not-but", "Die Aufgabe zur Post erfolgte nicht am 16.10.2026, sondern erst am 19.10.2026."),
    ("made-and-posted", "Der Bescheid wurde am 14.10.2026 erstellt und am 19.10.2026 zur Post gegeben."),
    # a second posting
    (
        "returned-and-posted-again",
        "Die Sendung kam am 19.10.2026 als unzustellbar zurück und wurde erneut zur Post gegeben.",
    ),
    ("a-second-time", "Der Bescheid wurde am 19.10.2026 ein zweites Mal zur Post gegeben."),
    (
        "once-more",
        "Da die erste Sendung zurückkam, haben wir den Bescheid am 19.10.2026 noch einmal zur Post gegeben.",
    ),
    ("again", "Der Bescheid wurde am 19.10.2026 erneut zur Post gegeben."),
    (
        "already-and-again",
        "Dieser Bescheid wurde bereits am 19.10.2026 zur Post gegeben und wird Ihnen erneut übersandt.",
    ),
    ("newly-posted", "Neu zur Post gegeben am 19.10.2026"),
    ("originally-posted", "Ursprünglich zur Post gegeben am 19.10.2026"),
    # a bound, a deadline, a plan, the future
    ("at-the-latest", "Dieser Bescheid wurde spätestens am 19.10.2026 versandt."),
    ("bis-zum", "Dieser Bescheid wurde bis zum 19.10.2026 abgesandt."),
    ("no-later-than", "This notice was posted no later than 19 October 2026."),
    ("must-be-posted-by", "Die Unterlagen müssen bis zum 19.10.2026 zur Post gegeben sein."),
    ("in-time-if", "Der Antrag gilt als rechtzeitig, wenn er am 19.10.2026 zur Post gegeben ist."),
    ("post-it-by", "Geben Sie den Antrag bis zum 19.10.2026 zur Post."),
    ("must-be-posted-by-2", "Die Erklärung muss bis 30.10.2026 zur Post gegeben sein."),
    ("decisive-at-the-latest", "Maßgeblich ist der Tag der Aufgabe zur Post, spätestens der 30.10.2026."),
    ("goes-to-the-post", "Der Bescheid geht am 19.10.2026 zur Post."),
    ("planned-for", "Die Aufgabe zur Post ist für den 19.10.2026 geplant."),
    ("planned-for-2", "Die Aufgabe zur Post ist für den 19.10.2026 vorgesehen."),
    ("a-field-expected", "Aufgabe zur Post voraussichtlich 19.10.2026"),
    ("only-on", "Die Aufgabe zur Post erfolgt erst am 19.10.2026."),
    ("will-only-be", "Der Abhilfebescheid wird erst am 19.10.2026 zur Post gegeben."),
    ("shall-be", "Der Bescheid soll am 19.10.2026 zur Post gegeben werden."),
    ("planned-field", "Versand geplant am 19.10.2026."),
    ("expected-sent", "Der Bescheid wird voraussichtlich am 19.10.2026 versandt."),
    ("a-reminder-we-will-post", "Die Mahnung zu diesem Bescheid geben wir am 19.10.2026 zur Post."),
    (
        "planned-after-payment",
        "Erst nach Zahlung wird der Bescheid zur Post gegeben; Aufgabe zur Post am 19.10.2026 vorgesehen.",
    ),
    ("from-on", "Versand ab 19.10.2026"),
    (
        "from-on-decisions",
        "Ab dem 19.10.2026 zur Post gegebene Bescheide gelten am vierten Tag als bekannt gegeben.",
    ),
    ("english-planned", "This notice will be posted on 19 October 2026."),
    ("english-post-by", "Please post your reply by 19 October 2026."),
    (
        "english-had-it-been",
        "Had it been posted on 19 October 2026, it would count as delivered on 23 October.",
    ),
    # the statute or an explanation quoted, a delivery day
    (
        "an-explanation",
        "Hinweis zur Fristberechnung: Aufgabe zur Post am 19.10.2026, Bekanntgabe am 23.10.2026.",
    ),
    ("a-model-calculation", "Musterrechnung: Aufgabe zur Post am 19.10.2026, Bekanntgabe 23.10.2026"),
    (
        "a-general-note",
        "Hinweis: Ein schriftlicher Bescheid gilt am vierten Tag nach der Aufgabe zur Post als bekannt gegeben, z. B. bei "
        "Aufgabe zur Post am 19.10.2026 am 23.10.2026.",
    ),
    ("an-example", "Beispiel: Aufgabe zur Post am 19.10.2026, Bekanntgabe am 23.10.2026."),
    ("an-example-field", "Beispiel: Bescheid zur Post gegeben am 19.10.2026"),
    (
        "a-supposition-wenn",
        "Wenn der Bescheid am 19.10.2026 zur Post gegeben wurde, gilt er am 23.10.2026 als bekannt gegeben.",
    ),
    (
        "a-supposition-falls",
        "Falls dieser Bescheid erst am 19.10.2026 zur Post gegeben wurde, verschiebt sich die Frist.",
    ),
    (
        "a-supposition-sofern",
        "Sofern der Bescheid am 19.10.2026 zur Post gegeben wurde, endet die Frist am 23.11.2026.",
    ),
    ("the-delivery-day-field", "Bekanntgabetag (vierter Tag nach der Aufgabe zur Post): 23.10.2026"),
    ("the-delivery-day", "Als Tag der Bekanntgabe gilt der 23.10.2026."),
    ("served", "Zugestellt am 19.10.2026 durch Postzustellungsurkunde."),
    ("arrived", "Posteingang: 19.10.2026"),
    ("received", "Eingegangen am 19.10.2026"),
    # sent another way, or goods
    ("by-e-mail", "Dieser Bescheid wurde am 19.10.2026 per E-Mail versandt."),
    ("electronically", "Dieser Bescheid wurde am 19.10.2026 elektronisch bereitgestellt (ELSTER)."),
    ("electronically-sent", "Dieser Bescheid wurde am 19.10.2026 elektronisch übermittelt."),
    ("to-the-mailbox", "Dieser Bescheid wurde am 19.10.2026 in Ihr Postfach versandt."),
    ("in-the-mailbox", "Bereitgestellt im Postfach am 19.10.2026"),
    ("by-fax-first", "Vorab per Telefax am 19.10.2026 versandt."),
    ("a-field-by-e-mail", "Aufgabe zur Post: 19.10.2026 per E-Mail"),
    ("an-order", "Ihre Bestellung wurde am 19.10.2026 versandt."),
    ("goods", "Ihre Ware wurde am 19.10.2026 an Sie versandt."),
    ("goods-field", "Versandt am: 19.10.2026  Sendung 4711"),
    ("by-a-carrier", "Versandt am 19.10.2026 mit DHL, Sendungsnummer 123456789"),
    ("an-order-s-row", "Versanddatum: 19.10.2026   Lieferdatum: 21.10.2026   Bestellnummer 4711"),
    ("english-shipped", "Your order was shipped on 19 October 2026."),
    # fields on another line's or another column's account
    ("a-card-on-the-line-before", "Ihre neue Gesundheitskarte\nTag der Aufgabe zur Post: 19.10.2026"),
    ("a-card-on-the-line-before-2", "Ihre neue Gesundheitskarte\nVersanddatum: 19.10.2026"),
    ("an-id-on-the-line-before", "Ersatzausweis\nAufgabe zur Post: 19.10.2026"),
    ("an-enclosure-on-the-line-before", "Anlage 1 (Berechnung)\nTag der Aufgabe zur Post 19.10.2026"),
    (
        "a-plan-on-the-line-before-2",
        "Der Rentenbescheid folgt mit gesonderter Post.\nVersanddatum: 19.10.2026",
    ),
    ("an-order-on-the-line-before", "Ihre Bestellung 4711\nZur Post gegeben am: 19.10.2026"),
    ("another-decision-on-the-line-before", "Bescheid für 2023\nAufgabe zur Post: 19.10.2026"),
    ("a-reminder-on-the-line-before", "Erinnerung\nVersanddatum: 19.10.2026"),
    ("an-enclosure-s-note", "Anlagen: Berechnungsbogen (Tag der Aufgabe zur Post: 19.10.2026)"),
    ("a-copy-s-note", "Ihr Steuerberater erhält eine Durchschrift; Versanddatum 19.10.2026."),
    ("the-reference", "Bezug: Ihr Schreiben vom 12.10.2026, abgesandt am 13.10.2026"),
    (
        "the-person-s-field-labels",
        "Eingangsdatum Ihres Schreibens: 14.10.2026   Versanddatum Ihres Schreibens: 19.10.2026",
    ),
    ("a-preliminary-decision-s-row", "Vorbescheid   Aufgabe zur Post: 19.10.2026"),
    (
        "decisions-rows",
        "Bescheid 2024   Aufgabe zur Post 19.10.2026\nBescheid 2025   Aufgabe zur Post 22.10.2026",
    ),
    ("a-fee-decision-s-cell", "Bescheid über Gebühren | Aufgabe zur Post: 19.10.2026"),
    ("another-office-s-cell", "Stadtkasse Musterstadt   Absendedatum: 19.10.2026"),
    ("unknown-and-arrival", "Tag der Aufgabe zur Post: unbekannt, Eingang 19.10.2026"),
    ("a-table", "Lfd. Nr.   Gegenstand   Versanddatum\n1   Erinnerung   19.10.2026"),
    ("two-columns-of-a-row", "Datum 16.10.2026     Versandtag 19.10.2026"),
    ("the-person-s-application-s", "Absendedatum Ihres Antrags: 19.10.2026"),
    ("a-return", "Rücksendung bitte bis 30.10.2026. Versandkostenfrei."),
    ("filing-date", "Abgabedatum der Erklärung: 19.10.2026"),
    ("the-person-s-postmark", "Datum des Poststempels Ihrer Sendung: 19.10.2026"),
    # a label with more words in its cell than the closed form lists
    ("a-reminder-s-label", "Versanddatum der Zahlungserinnerung: 19.10.2026"),
    ("a-reminder-s-label-2", "Versandtag der Mahnung: 19.10.2026"),
    ("a-decision-s-label", "Versanddatum des Widerspruchsbescheids: 19.10.2026"),
    ("a-refund-s-label", "Versanddatum Ihrer Erstattung: 19.10.2026"),
    ("a-reply-s-label", "Versanddatum der Rückantwort: 19.10.2026"),
    ("a-file-s-label", "Postausgang Ihrer Akte: 19.10.2026"),
    ("a-bound-label", "Absendung Ihrer Unterlagen bis: 19.10.2026"),
    ("a-request-label", "Bitte Absendetag angeben: 19.10.2026"),
    ("an-application-s-label", "Versanddatum Antrag: 19.10.2026"),
    ("a-reminder-s-label-3", "Versanddatum Erinnerung: 19.10.2026"),
    ("a-decision-s-label-2", "Versanddatum Vorauszahlungsbescheid 2027: 19.10.2026"),
    ("planned-soll", "Versanddatum (Soll): 19.10.2026"),
    ("two-ways", "Tag der Aufgabe zur Post: 10/11/2026"),
]

#: A closed form in a place where the words before it may lead into an example, a supposition or another letter's
#: story: after another sentence's end, after a line that ends in a date, after the salutation, at the text's start
#: (the fifth review: each moved a right deadline later, at high confidence). Only a notice's heading starting its
#: line is a form's place now; each row also with the self-naming subject, so the place refuses it, not its words.
_PLACES_NEVER = [
    (
        "an-example-in-whole-sentences",
        "Ein Beispiel zur Fristberechnung. {subject} wurde am 20.10.2026 zur Post gegeben. Er gilt dann am "
        "23.10.2026 als bekannt gegeben.",
    ),
    ("a-worked-example-s-heading-line", "Rechenbeispiel.\n{subject} wurde am 21.10.2026 zur Post gegeben."),
    (
        "nehmen-wir-an",
        "Nehmen wir an, Sie erhalten den Bescheid spät. {subject} wurde am 22.10.2026 versandt. Dann beginnt die "
        "Frist am 26.10.2026.",
    ),
    ("angenommen-and-a-semicolon", "Angenommen, es ist so; {subject} wurde am 20.10.2026 zur Post gegeben."),
    (
        "so-berechnen-sie",
        "So berechnen Sie die Frist: Ein Beispiel. {subject} wurde am 21.10.2026 abgesandt.",
    ),
    (
        "a-question-then-its-answer",
        "Wann beginnt die Frist? {subject} wurde am 20.10.2026 zur Post gegeben. Dann gilt er am 23.10.2026 als "
        "bekannt gegeben.",
    ),
    (
        "english-for-example",
        "For example. This letter was posted on 20 October 2026. It then counts as received.",
    ),
    ("english-suppose", "Suppose it was late! This notice was mailed on 21 October 2026."),
    # a lead line that ends in a date (not the letter's header)
    (
        "angenommen-a-dated-line",
        "Angenommen, Sie erhalten einen Bescheid vom 16.10.2026\n{subject} wurde am 19.10.2026 zur Post gegeben.",
    ),
    (
        "an-example-s-dated-line",
        "Beispiel zu einem Bescheid vom 16.10.2026\n{subject} wurde am 19.10.2026 zur Post gegeben. Dann gilt er am "
        "22.10.2026 als bekannt gegeben.",
    ),
    (
        "another-person-s-dated-line",
        "Ihr Ehemann, Herr Max Beispiel, geb. 01.02.1970\n{subject} wurde am 19.10.2026 versandt.",
    ),
    (
        "a-neighbour-s-decision-dated",
        "Grundsteuerbescheid 2025 Ihres Nachbarn vom 15.10.2026\n{subject} wurde am 19.10.2026 versandt.",
    ),
    # after a sentence's end in mid-paragraph
    (
        "another-person-s-decision",
        "Ihr Ehemann erhält einen eigenen Bescheid. {subject} wurde am 19.10.2026 versandt.",
    ),
    (
        "an-example-s-own-date",
        "Beispiel: Ein Bescheid trägt das Datum 16.10.2026. {subject} wurde am 19.10.2026 zur Post gegeben. Er gilt "
        "dann am 22.10.2026 als bekannt gegeben.",
    ),
    (
        "an-earlier-application",
        "So war es auch bei Ihrem Antrag auf Stundung. {subject} wurde am 19.10.2026 abgesandt.",
    ),
    # the places the last round still let a form stand
    ("after-a-sentence", "Die Steuer wird festgesetzt. {subject} wurde am 19.10.2026 zur Post gegeben."),
    ("after-the-salutation", "Sehr geehrte Frau Beispiel,\n{subject} wurde am 19.10.2026 zur Post gegeben."),
    ("after-the-header-s-date", f"{HEADER}{{subject}} wurde am 19.10.2026 zur Post gegeben."),
    ("at-the-text-s-start", "{subject} wurde am 19.10.2026 zur Post gegeben."),
    # a heading that does not start its line
    (
        "a-heading-after-a-sentence-s-end",
        "Die Steuer ist fällig. Hinweis: {subject} wurde am 19.10.2026 zur Post gegeben.",
    ),
    ("a-heading-after-other-words", "Beispiel Hinweis: {subject} wurde am 19.10.2026 zur Post gegeben."),
]
PLACES_NEVER = [
    (f"{name}-{key}", text.replace("{subject}", subject))
    for name, text in _PLACES_NEVER
    for key, subject in (("der", "Der Bescheid"), ("dieser", "Dieser Bescheid"))
]
#: The rows about a form's place, which a heading put before them would make a form's own place.
PLACES = {name for name, _ in PLACES_NEVER}

#: Records that name no letter or another one (the fifth review: closed forms built from listed words only). The
#: subject must name THIS letter ("Dieser" / "Dieses" / "This"); plain "Der" / "Das" and the subjectless forms no
#: longer count anywhere.
THIS_LETTER_ONLY = [
    ("der-brief", "Hinweis: Der Brief wurde am 20.10.2026 versandt."),
    ("das-schreiben", "Hinweis: Das Schreiben wurde am 20.10.2026 abgesandt."),
    ("der-bescheid-ist-worden", "Hinweis: Der Bescheid ist am 20.10.2026 versandt worden."),
    ("die-aufgabe-erfolgte", "Hinweis: Die Aufgabe zur Post erfolgte am 20.10.2026."),
    ("die-aufgabe-ist-erfolgt", "Hinweis: Die Aufgabe zur Post ist am 20.10.2026 erfolgt."),
    ("zur-post-gegeben-a-note", "Hinweis: Zur Post gegeben am 20.10.2026."),
    ("the-reader-s-letter", "Wir haben Ihr Schreiben erhalten. Das Schreiben wurde am 20.10.2026 abgesandt."),
    (
        "a-copy-for-the-adviser",
        "Eine Kopie erhält Ihr Steuerberater. Der Brief wurde am 21.10.2026 versandt.",
    ),
    ("the-reader-s-own-letter", "Hinweis: Ihr Brief wurde am 20.10.2026 versandt."),
    ("a-delivery", "Hinweis: Dieser Bescheid wurde am 20.10.2026 zugestellt."),
    ("an-application", "Hinweis: Der Antrag wurde am 20.10.2026 versandt."),
    ("a-deadline-weekday", "Hinweis: Dieser Bescheid wurde am spätestens 20.10.2026 versandt."),
    ("a-bound", "Hinweis: Dieser Bescheid wurde bis 20.10.2026 versandt."),
    ("a-future", "Hinweis: Dieser Bescheid wird am 20.10.2026 versandt."),
    ("english-delivered", "Hinweis: This letter was delivered on 20 October 2026."),
    ("another-determiner", "Hinweis: Jener Bescheid wurde am 20.10.2026 versandt."),
    ("without-am", "Hinweis: Dieser Bescheid wurde 20.10.2026 zur Post gegeben."),
    ("a-date-that-reads-two-ways", "Hinweis: Dieser Bescheid wurde am 03/05/2026 zur Post gegeben."),
    ("two-dates", "Hinweis: Dieser Bescheid wurde am 19.10.2026 und am 20.10.2026 zur Post gegeben."),
]

#: A field outside the first page's letterhead: in the body or the remedy notice, after the salutation — a worked
#: example, a date to post by, a plan, another document's record (the fifth review: each moved a right deadline
#: later). In the letterhead, a field is this letter's own; in the body it never counts, whatever the line above.
BODY_FIELDS = [
    ("an-example", "Beispiel:\nTag der Aufgabe zur Post: 20.10.2026\nBekanntgabetag: 23.10.2026"),
    ("so-rechnen-sie", "So rechnen Sie:\nZur Post gegeben am 21.10.2026"),
    ("angenommen", "Angenommen:\nVersanddatum: 22.10.2026"),
    ("an-english-example", "Example:\nDate of posting: 20 October 2026"),
    ("a-date-to-post-by", "Rücksendung bis spätestens\nAbsendedatum: 22.10.2026"),
    ("a-reply-s-deadline", "Frist für Ihre Antwort\nAbsendedatum: 22.10.2026"),
    ("an-english-date-to-post-by", "Please return the form by\nPosting date: 22 October 2026"),
    ("a-planned-second-copy", "Die Zweitausfertigung soll Ihnen zugehen am\nVersanddatum: 22.10.2026"),
    ("an-english-plan", "We will send the decision again.\nPosting date: 22 October 2026"),
    ("a-copy-s-recipient", "Nachrichtlich:\nSteuerberatung Muster GmbH, Musterstadt\nVersandt am 21.10.2026"),
    ("a-reminder-s-level", "Mahnstufe 1\nVersandt am: 21.10.2026"),
    (
        "another-year-s-decision-two-lines-above",
        "Bescheid für 2024\nSteuernummer 123/456/78901\nTag der Aufgabe zur Post: 21.10.2026",
    ),
    ("by-e-mail", "Per E-Mail\nVersandt am 21.10.2026"),
    ("in-the-tax-portal", "Bereitgestellt im Postfach (ELSTER)\nVersandt am: 21.10.2026"),
    ("by-fax", "Telefax an 01234-5678\nAbgesendet am 21.10.2026"),
    ("a-transfer", "Überweisung\nAbgesendet am: 21.10.2026"),
    ("a-small-ad", "Kleinanzeige Nr. 4711\nAufgegeben am 21.10.2026"),
    ("a-newsletter", "Newsletter\nVersendet am 21.10.2026"),
    ("a-label-alone", "Tag der Aufgabe zur Post:\n21.10.2026"),
]

#: A posting label that starts a wrapped line of prose (the line above runs on into it) or that a lower-case word
#: starts: never a field, in the letterhead as in the body (the fifth review: each moved a right deadline later).
WRAPPED = [
    (
        "a-supposition-wrapped-before-the-label",
        "Bitte beachten Sie: Ihr Einspruch ist nur dann rechtzeitig, wenn er bei\nAufgabe zur Post am 21.10.2026.",
    ),
    ("a-form-s-dispatch", "Das Formular, das Sie angefordert hatten, wurde\nversandt am 21.10.2026."),
    ("a-licence-s-dispatch", "Ihr neuer Führerschein wurde von der Bundesdruckerei\nversandt am 21.10.2026."),
    ("the-reader-s-objection", "Ihren Widerspruch haben Sie nach Ihren Angaben\naufgegeben am 21.10.2026."),
    ("by-the-postmark", "Ihr Einspruch wurde laut Poststempel\nabgesandt am 21.10.2026."),
    ("a-refund", "Die Erstattung wurde an Ihre Bank\nversendet am 21.10.2026."),
    ("a-power-of-attorney", "Die Vollmacht Ihres Steuerberaters wurde uns\nzur Post gegeben am 21.10.2026."),
    (
        "english-the-reader-s-objection",
        "Your objection, according to the envelope, was\nposted on 21 October 2026.",
    ),
    ("english-a-reminder", "The payment reminder to your landlord was\nmailed on 21 October 2026."),
    ("a-label-alone-wrapped", "Ihr Antrag auf Erstattung wurde\nabgesandt\n21.10.2026"),
    ("a-label-after-a-comma", "Ihre Unterlagen haben wir geprüft,\nVersandt am 21.10.2026"),
    ("a-label-after-a-hyphen", "Ihre Unterlagen wurden am Schalter ab-\nVersandt am 21.10.2026"),
]


#: A field in the letterhead under a closed line (it ends in a number, a colon or a full stop, so the field opens)
#: that names what makes the posting day another thing's: each decided by one list of :func:`posting._another_s`
#: or by :data:`posting._DOCUMENT_ABOVE`. (id, the letterhead's lines.)
ABOVE_A_FIELD = [
    ("a-plan-above", "Voraussichtlich:\nVersanddatum: 19.10.2026"),
    ("a-negation-above", "Nicht zugestellt:\nVersanddatum: 19.10.2026"),
    ("an-id-card-above", "Ersatzausweis Nr. 4711\nVersanddatum: 19.10.2026"),
    ("an-enclosure-above", "Anlage 1\nTag der Aufgabe zur Post: 19.10.2026"),
    ("an-order-above", "Ihre Bestellung 4711\nVersanddatum: 19.10.2026"),
    ("another-decision-above", "Bescheid für 2023\nAufgabe zur Post: 19.10.2026"),
    ("an-enclosure-above-a-label-over-its-value", "Anlage 1\nVersanddatum\n19.10.2026"),
    ("a-future-above-a-label-over-its-value", "Wird nachgereicht:\nVersanddatum\n19.10.2026"),
]


def test_what_stands_above_a_field_can_make_it_another_s() -> None:
    def check(_id: str, top: str) -> None:
        assert found(head(top)) == PostingStatement(), top
        assert due(head(top)) == "2026-11-20", top

    check_rows(ABOVE_A_FIELD, check)


def test_a_field_counts_only_in_the_first_page_s_letterhead() -> None:
    """In the body (after the salutation) a field never counts, nor on a page without a salutation, where nothing
    shows where its letterhead ends: the letter's date's deadline, Fri 20 Nov (AO, NW; VwVfG, BY)."""

    def check(_id: str, text: str) -> None:
        for page in (text, body(text), f"{text}{REMEDY}"):
            assert found(page) == PostingStatement(), page
            assert due(page) == "2026-11-20" and due(page, scope="vwvfg", region="BY") == "2026-11-20", page

    check_rows(BODY_FIELDS, check)


def test_a_wrapped_line_of_prose_is_no_field() -> None:
    def check(_id: str, text: str) -> None:
        for page in (text, head(text), body(text)):
            assert found(page) == PostingStatement(), page
            assert due(page) == "2026-11-20", page

    check_rows(WRAPPED, check)


#: Lead lines that run on into the next line (a word, a comma, a hyphen at their end), each of the words a sentence
#: wraps at: none may stand right above a field's label that starts its line.
_RUNNING_ON = (
    "Der Bescheid wurde",
    "Ihr Einspruch ist nur dann rechtzeitig, wenn er bei",
    "Your objection was",
    "Die Vollmacht wurde uns",
    "Die Erstattung wurde an Ihre Bank",
    "Wir haben die Unterlagen geprüft,",
    "Die Unterlagen wurden ab-",
)
#: A field's lines that count in the letterhead under a closed line (each also a CUES row).
_FIELD_LINES = (
    "Tag der Aufgabe zur Post: 19.10.2026",
    "Datum der Aufgabe zur Post: Montag, 19. Oktober 2026",
    "Tag der Aufgabe zur Post\n19.10.2026",
    "Absendedatum: 19.10.2026",
    "Versandt am: 19.10.2026",
    "Aufgabe zur Post am Montag, den 19.10.2026",
    "Zur Post gegeben am 19.10.2026.",
    "Date of posting: 19 October 2026",
    "Aufgegeben am 19.10.2026",
    "Abgesendet am 19.10.2026",
    "Versand: 19.10.2026",
    "Posted: 19 October 2026",
)


def test_a_line_that_runs_on_never_opens_a_field() -> None:
    """Every field line: counted under a closed line in the letterhead; never under a line that runs on into it,
    and never with its label in lower case (prose that wrapped before a participle: "wurde" over "versandt am …"),
    whatever stands above."""
    for field in _FIELD_LINES:
        statement = found(head(f"Steuernummer 123/456/78901\n{field}"))
        assert statement is not None and statement.day == D("2026-10-19"), field
        for lead in _RUNNING_ON:
            assert found(head(f"{lead}\n{field}")) == PostingStatement(), (lead, field)
        lower = field[0].lower() + field[1:]
        for lead in ("Steuernummer 123/456/78901", "", "Bearbeitungsstand:"):
            assert found(head(f"{lead}\n{lower}")) == PostingStatement(), (lead, lower)


def _two_column_rows(top: float, rows: list[tuple[str, str]]) -> tuple[str, list[list[Any]]]:
    """Rows of two columns (the left at 0.10, the right at 0.65 of the page's width), as text lines and boxes."""
    text = "".join(f"{left:<30}{right}\n" for left, right in rows)
    words: list[list[Any]] = []
    for index, (left, right) in enumerate(rows):
        words += _row(top + 0.015 * index, (0.10, left), (0.65, right))
    return text, words


def test_a_table_in_the_body_is_never_the_letterhead_s_field() -> None:
    """A two-column table under the salutation, its right column headed by a posting label, the boxes saying the
    value is right under it: the body's, never a field of the letterhead (Fri 20 Nov, from the letter's date)."""
    salutation = "Sehr geehrte Frau Beispiel,"
    for lead in ("folgende Schreiben werden versandt:", "wir haben folgende Schreiben versandt:"):
        table, table_words = _two_column_rows(
            0.40, [("Mahnung", "Versanddatum"), ("Vollstreckungsankündigung", "22.10.2026")]
        )
        text = f"{HEADER}{salutation}\n{lead}\n{table}"
        words = _row(0.35, (0.10, salutation)) + _row(0.37, (0.10, lead)) + table_words
        statement = posting_statement([(1, text, words, "text")], LETTER)
        assert statement == PostingStatement(), lead
    # without a salutation the page shows no letterhead: a reminder's table there is not one either
    table, table_words = _two_column_rows(
        0.40, [("Schriftstück", "Versandt"), ("Erinnerung 2025", "22.10.2026")]
    )
    assert posting_statement([(1, table, table_words, "text")], LETTER) == PostingStatement()


#: Two letters in one upload (made up): page 1 this tax assessment of Fri 16 Oct 2026, page 2 a later decision
#: with its own header date and its own posting day. (id, the second page, the posting day found or None.)
TWO_LETTERS = [
    (
        "a-later-decision-s-sentence",
        "Finanzamt Musterstadt   Datum 22.10.2026\nÄnderungsbescheid\nSehr geehrte Frau Beispiel,\n"
        "Hinweis: Dieser Bescheid wurde am 23.10.2026 zur Post gegeben.",
        None,
    ),
    (
        "a-later-decision-s-field",
        "Finanzamt Musterstadt   Datum: 22.10.2026\nTag der Aufgabe zur Post: 23.10.2026\nSehr geehrte Frau Beispiel,",
        None,
    ),
    (
        "and-a-page-after-it",
        "Finanzamt Musterstadt   Datum 22.10.2026\nÄnderungsbescheid",
        None,
    ),
    # this letter's own second page (no other date in its header, or its own): its notice counts
    (
        "this-letter-s-second-page",
        "Seite 2\nHinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben.",
        "2026-10-19",
    ),
    # a date in this letter's second page's header after no letter's date label: not another letter's
    (
        "a-reference-date-on-this-letter-s-second-page",
        "Seite 2 zum Bescheid, Ihr Schreiben vom 12.10.2026\n"
        "Hinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben.",
        "2026-10-19",
    ),
    (
        "this-letter-s-date-on-its-second-page",
        "Datum 16.10.2026   Seite 2\nHinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben.",
        "2026-10-19",
    ),
]


def test_only_this_letter_s_pages_are_read() -> None:
    """A later letter in the same upload gives no posting day to this one: from the first page whose header dates
    another letter, nothing is read (Fri 20 Nov, from the letter's date); this letter's own later pages are."""
    spec = DateSpec(
        type="relative",
        anchor="deemed_delivery",
        amount=1,
        unit="months",
        delivery_rule="de_admin_post",
        nature="objection",
    )
    first = body("Die Steuer wird festgesetzt.")

    def check(_id: str, second: str, day: str | None) -> None:
        pages: list[Any] = [(1, first, [], "text"), (2, second, [], "text")]
        if _id == "and-a-page-after-it":
            pages.append((3, "Hinweis: Dieser Bescheid wurde am 23.10.2026 zur Post gegeben.", [], "text"))
        statement = posting_statement(pages, LETTER)
        assert statement is not None and statement.day == (D(day) if day else None), statement
        context = RuleContext(
            today=D("2026-10-27"), region="NW", document_date=LETTER, delivery_scope="ao", posting=statement
        )
        assert compute_due(spec, context).due_date == ("2026-11-23" if day else "2026-11-20")

    check_rows(TWO_LETTERS, check)
    # without the letter's date as read, the first page's header date is this letter's: a page with that date is
    # read, a page with another ends the reading
    first_page = (1, f"Finanzamt Musterstadt   Datum: 16.10.2026\n{SALUTATION}", [], "text")
    own = (
        2,
        "Datum 16.10.2026   Seite 2\nHinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben.",
        [],
        "text",
    )
    other = (2, TWO_LETTERS[0][1], [], "text")
    statement = posting_statement([first_page, own], None)
    assert statement is not None and statement.day == D("2026-10-19"), statement
    assert posting_statement([first_page, other], None) == PostingStatement()


def test_reviewed_wordings_never_count_as_this_letter_s_posting_day() -> None:
    """Every false find of the reviews, and every wording that no longer counts: refused by the closed forms."""

    def check(_id: str, text: str) -> None:
        for page in everywhere(text, heading=_id not in PLACES):
            statement = found(page)
            assert statement is not None and statement.day is None, page

    check_rows(
        [*NO_LONGER, *BESIDE_AFTER_WORDS, *SUPPOSED, *REVIEWED, *PLACES_NEVER, *THIS_LETTER_ONLY], check
    )


def test_a_refused_wording_keeps_the_letter_s_date_s_deadline() -> None:
    """Through the engine, for the wordings that moved a right deadline later in an earlier round: a made-up tax
    assessment dated Fri 16 Oct 2026 (AO, NW; and under the VwVfG in BY), the wording in its letterhead, in its body
    and under a notice's heading — the objection deadline counts from the letter's date (Fri 20 Nov), never from the
    19th (Mon 23 Nov) or a later day."""

    def check(_id: str, text: str) -> None:
        for page in everywhere(text, heading=_id not in PLACES):
            assert due(page) == "2026-11-20", page
            assert due(page, scope="vwvfg", region="BY") == "2026-11-20", page

    check_rows(
        [*NO_LONGER, *BESIDE_AFTER_WORDS, *SUPPOSED, *REVIEWED, *PLACES_NEVER, *THIS_LETTER_ONLY], check
    )


#: The closed sentence forms, each with several ways of filling its slots (id, the sentence, the form's name); each
#: counts under a notice's heading (:data:`SENTENCE_PLACES`).
SENTENCES = [
    ("wurde-dieser-bescheid", "Dieser Bescheid wurde am 19.10.2026 zur Post gegeben.", "wurde"),
    ("wurde-dieser-brief", "Dieser Brief wurde am 19.10.2026 zur Post gegeben.", "wurde"),
    ("wurde-dieses-schreiben", "Dieses Schreiben wurde am 19. Oktober 2026 der Post übergeben.", "wurde"),
    ("wurde-abgesandt", "Dieses Schreiben wurde am 19.10.2026 abgesandt.", "wurde"),
    ("wurde-a-compound", "Dieser Widerspruchsbescheid wurde am 19.10.2026 zur Post gegeben.", "wurde"),
    ("wurde-aufgegeben", "Dieser Steuerbescheid wurde am 19.10.2026 zur Post aufgegeben.", "wurde"),
    # every listed compound, each the letter naming itself after "Dieser"
    *(
        (f"wurde-dieser-{noun.casefold()}", f"Dieser {noun} wurde am 19.10.2026 zur Post gegeben.", "wurde")
        for noun in ("Festsetzungsbescheid", "Leistungsbescheid", "Gebührenbescheid", "Beitragsbescheid")
    ),
    ("wurde-a-short-weekday", "Dieser Bescheid wurde am Mo., 19.10.2026 zur Post gegeben.", "wurde"),
    ("wurde-a-weekday-and-den", "Dieser Bescheid wurde am Montag, den 19.10.2026 versandt.", "wurde"),
    ("wurde-without-a-full-stop", "Dieser Bescheid wurde am 19.10.2026 zur Post gegeben", "wurde"),
    ("wurde-wrapped", "Dieser Bescheid wurde am\n19.10.2026 zur\nPost gegeben.", "wurde"),
    ("ist-worden", "Dieser Bescheid ist am 19.10.2026 zur Post gegeben worden.", "ist-worden"),
    (
        "ist-worden-schreiben",
        "Dieses Schreiben ist am Montag, dem 19.10.2026 der Post übergeben worden.",
        "ist-worden",
    ),
    ("ist-worden-versandt", "Dieser Änderungsbescheid ist am 19.10.2026 versandt worden.", "ist-worden"),
    ("english-letter", "This letter was posted on 19 October 2026.", "english"),
    ("english-notice-mailed", "This notice was mailed on Monday, 19 October 2026.", "english"),
    ("english-decision-sent", "This decision was sent on 19 October 2026.", "english"),
]
#: Where a counted sentence may stand: only right under a notice's heading that starts its text line, the form on
#: the heading's line or the next (id, page text).
SENTENCE_PLACES = [
    ("after-hinweis", "Hinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ("after-hinweise", "Hinweise: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ("after-hinweis-zur-zustellung", "Hinweis zur Zustellung: Dieser Bescheid wurde am 19.10.2026 versandt."),
    ("after-hinweis-zur-absendung", "Hinweis zur Absendung: Dieser Brief wurde am 19.10.2026 versandt."),
    ("after-wichtiger-hinweis", "Wichtiger Hinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ("after-bitte-beachten-sie", "Bitte beachten Sie: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ("a-heading-on-a-line", f"{HEADER}Vermerk: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."),
    (
        "the-form-on-the-heading-s-next-line",
        body("Hinweis:\nDieser Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ),
    ("in-the-body", body("Hinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben.")),
    (
        "after-a-sentence-on-the-line-before",
        body("Die Steuer ist fällig.\nHinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."),
    ),
]


def test_each_closed_sentence_form_counts() -> None:
    def check(_id: str, text: str, form: str) -> None:
        statement = found(under_a_heading(text))
        assert statement is not None and statement.day == D("2026-10-19"), statement
        assert posting._form(" ".join(text.split())) == (form, D("2026-10-19"))
        # only under a heading: not alone, not after the salutation, not in the letterhead
        for page in (text, body(text), head(text), f"{HEADER}{text}"):
            assert found(page) == PostingStatement(), page

    check_rows(SENTENCES, check)

    def place(_id: str, text: str) -> None:
        statement = found(text)
        assert statement is not None and statement.day == D("2026-10-19"), statement
        assert due(text) == "2026-11-23"

    check_rows(SENTENCE_PLACES, place)


#: Words no closed form lists, one for each kind of slot: an adjective (before the subject's noun), a phrase after
#: it, an adverb (before "am"), a word after the participle, an opener.
UNLISTED = ("neue", "für 2024", "bereits", "erneut", "Wenn", "nicht")


def _variants(text: str) -> Iterator[str]:
    """``text`` with each word of :data:`UNLISTED` put into every slot in turn: inserted before each word and before
    its full stop, and in place of its full stop, of a comma and of each word that is not part of its date."""
    body = " ".join((text[:-1] if text.endswith(".") else text).split())
    words = body.split()
    starts = [len(" ".join(words[:index])) + (1 if index else 0) for index in range(len(words))]
    spans = [(start, end) for start, end, _ in date_spans(body)]
    dated = {i for i, at in enumerate(starts) if any(s < at + len(words[i]) and at < e for s, e in spans)}
    for filler in UNLISTED:
        yield f"{body} {filler}"  # in place of its full stop
        for index in range(len(words) + 1):
            yield " ".join([*words[:index], filler, *words[index:]]) + "."
        for index in range(len(words)):
            if index not in dated:
                yield " ".join([*words[:index], filler, *words[index + 1 :]]) + "."
            if words[index].endswith(","):  # in place of a comma ("am Montag, den …")
                yield " ".join([*words[:index], words[index][:-1], filler, *words[index + 1 :]]) + "."


def test_an_unlisted_word_in_any_slot_refuses_the_sentence() -> None:
    """Unknown means no: in every counted sentence, a word of no listed class in any slot — inserted anywhere
    before its end, or in place of any word but its date — refuses the form, and the page states no posting day."""

    def check(_id: str, text: str, _form: str) -> None:
        for variant in _variants(text):
            statement = found(under_a_heading(variant))
            assert statement is not None and statement.day is None, variant

    check_rows(SENTENCES, check)


#: Every weekday a form lists, each in a counted sentence on its own day of the week after the letter's date (Fri
#: 16 Oct 2026): Mon 19 to Sun 25 Oct.
_DAYS = (
    ("Montag", "Mo", "Monday", "Mon"),
    ("Dienstag", "Di", "Tuesday", "Tue"),
    ("Mittwoch", "Mi", "Wednesday", "Wed"),
    ("Donnerstag", "Do", "Thursday", "Thu"),
    ("Freitag", "Fr", "Friday", "Fri"),
    ("Samstag", "Sa", "Saturday", "Sat"),
    ("Sonntag", "So", "Sunday", "Sun"),
)
WEEKDAYS = [
    row
    for offset, (long, short, english, english_short) in enumerate(_DAYS)
    for row in (
        (
            f"{short}",
            f"Dieser Bescheid wurde am {short}., {19 + offset}.10.2026 zur Post gegeben.",
            19 + offset,
        ),
        (f"{long}", f"Dieser Bescheid wurde am {long}, den {19 + offset}.10.2026 versandt.", 19 + offset),
        (f"{english}", f"This letter was posted on {english}, {19 + offset} October 2026.", 19 + offset),
        (
            f"{english_short}",
            f"This notice was mailed on {english_short}, {19 + offset} October 2026.",
            19 + offset,
        ),
    )
]


def test_each_listed_weekday_counts_on_its_day() -> None:
    def check(_id: str, text: str, day: int) -> None:
        statement = found(under_a_heading(text))
        assert statement is not None and statement.day == date(2026, 10, day), statement

    check_rows(WEEKDAYS, check)


#: The grammar, word for word: a word added to a class fails this test until its rows are written.
EXPECTED_WORDS = {
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
        *("montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"),
        *("mo", "di", "mi", "do", "fr", "sa", "so"),
    ),
    "WEEKDAY": (
        *("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"),
        *("mon", "tue", "wed", "thu", "fri", "sat", "sun"),
    ),
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
#: The headings a form may stand under, and their forms with "zur …".
EXPECTED_HEADING = (
    r"(?:hinweise?(?:\s+zur\s+(?:bekanntgabe|zustellung|absendung))?|wichtiger\s+hinweis|bitte\s+beachten\s+sie"
    r"|vermerk)\s*:\s*"
)


def test_the_closed_lists_are_pinned_and_each_word_is_used() -> None:
    """Every list is as written here, and every listed word is a word of a counted row (``SENTENCES``,
    ``WEEKDAYS``): no word stands in a list that no row needs."""
    assert posting._WORDS == EXPECTED_WORDS
    assert posting._HEADING.pattern == EXPECTED_HEADING
    used = {
        token.casefold()
        for _id, text, *_ in (*SENTENCES, *WEEKDAYS)
        for token in posting._TOKENS.findall(text)
    }
    unused = {word for words in posting._WORDS.values() for word in words} - used
    assert not unused, unused


_HEADINGS = (
    "Hinweis",
    "Hinweise",
    "Hinweis zur Bekanntgabe",
    "Wichtiger Hinweis",
    "Bitte beachten Sie",
    "Vermerk",
)


def test_an_unlisted_word_in_the_heading_s_slot_refuses_the_sentence() -> None:
    """The heading is the form's lead: an unlisted word before it, inside it or in place of its colon, or the
    heading after another sentence's end on its line, refuses the form."""
    sentence = "Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."
    for heading in _HEADINGS:
        page = f"{HEADER}{SALUTATION}{heading}: {sentence}\n"
        statement = found(page)
        assert statement is not None and statement.day == D("2026-10-19"), page
        first, *rest = heading.split()
        for filler in UNLISTED:
            for variant in (
                f"{filler} {heading}: {sentence}",
                f"{' '.join([first, filler, *rest])}: {sentence}",
                f"{heading} {filler}: {sentence}",
                f"{heading} {filler} {sentence}",
                f"Die Steuer ist fällig. {heading}: {sentence}",
                f"{filler}. {heading}: {sentence}",
            ):
                assert found(f"{HEADER}{SALUTATION}{variant}\n") == PostingStatement(), variant
        assert found(f"{HEADER}{SALUTATION}{heading} {sentence}\n") == PostingStatement(), heading


def _letterhead_block(
    label_x: float,
    *,
    salutation: str | None = "below",
    value: str = "19.10.2026",
    field: str = "Tag der Aufgabe zur Post: {value}",
    above: str = "Datum: 16.10.2026",
    left: str = "Lindenweg 4",
    above_left: str = "Frau Erika Beispiel",
) -> tuple[str, list[list[Any]]]:
    """A made-up first page: the address column on the left and, on the same text line, the information block's
    posting ``field`` (``Tag der Aufgabe zur Post: <value>``) starting at ``label_x``, under the block's ``above``
    row; the salutation ``below`` the block and left of it, ``right`` of the label, ``above`` it, or none."""
    field = field.format(value=value)
    text = f"{above_left:<40}{above}\n{left:<40}{field}\n"
    words = _row(0.20, (0.10, above_left), (label_x, above))
    words += _row(0.215, (0.10, left), (label_x, field))
    greeting = "Sehr geehrte Frau Beispiel,"
    if salutation == "below":
        text += f"\n{greeting}\n"
        words += _row(0.35, (0.10, greeting))
    elif salutation == "right":
        text += f"\n{greeting}\n"
        words += _row(0.35, (label_x + 0.05, greeting))
    elif salutation == "above":
        # the text layer reads the salutation after the block, its box stands above it; the body's first line
        # below the block, left of it, is no salutation
        text += f"\n{greeting}\ndie Steuer wird festgesetzt.\n"
        words = _row(0.10, (0.10, greeting)) + words + _row(0.35, (0.10, "die Steuer wird festgesetzt."))
    return text, words


#: A field beside its label that starts a cell, not its line: only in the first page's information block by the
#: word boxes (id, page text, boxes, the page's number in the letter, the posting day or None).
INFO_BLOCK = [
    ("in-the-information-block", *_letterhead_block(0.62), 0, "2026-10-19"),
    ("in-the-block-with-a-weekday", *_letterhead_block(0.62, value="Mo., 19.10.2026"), 0, "2026-10-19"),
    ("without-boxes", _letterhead_block(0.62)[0], [], 0, None),
    ("left-of-the-block", *_letterhead_block(0.42), 0, None),
    ("no-salutation-below", *_letterhead_block(0.62, salutation=None), 0, None),
    ("on-a-later-page", *_letterhead_block(0.62), 1, None),
    ("words-after-the-date", *_letterhead_block(0.62, value="19.10.2026 (Montag)"), 0, None),
    # the salutation must stand below the block and start left of it: right of the label, or above it, the label
    # is not in a letterhead's information block (the text layer reads the salutation's line first or last)
    ("the-salutation-right-of-the-label", *_letterhead_block(0.62, salutation="right"), 0, None),
    ("the-salutation-above-the-label", *_letterhead_block(0.62, salutation="above"), 0, None),
    # the block's row above dates another letter in the label's column: the field may be that letter's; the
    # letter's own date there is the block's own "Datum" field (the first row)
    (
        "another-letter-s-date-above",
        *_letterhead_block(0.62, above="Ihre Nachricht vom 12.10.2026", field="Abgesandt am: {value}"),
        0,
        None,
    ),
    # another letter's date on the label's row ("Ihr Schreiben vom 12.10.2026" in the address column), and the
    # letter's own date there (counts)
    (
        "another-letter-s-date-on-the-row",
        *_letterhead_block(0.62, left="Ihr Schreiben vom 12.10.2026"),
        0,
        None,
    ),
    # the dispatch note right above the label in the block's column: the way it is sent, not a document
    ("einschreiben-above-the-label", *_letterhead_block(0.62, above="Einschreiben"), 0, "2026-10-19"),
    # a company's name in the address column above the label's row: only the label's column above is read
    (
        "a-company-s-name-in-the-address-column-above",
        *_letterhead_block(0.62, above_left="Kartenhaus GmbH"),
        0,
        "2026-10-19",
    ),
    (
        "the-letter-s-own-date-on-the-row",
        *_letterhead_block(0.62, left="Ihr Schreiben vom 16.10.2026"),
        0,
        "2026-10-19",
    ),
    # a word before the label in its cell (after one space, not a column's gap)
    (
        "a-word-before-the-label-in-its-cell",
        *_letterhead_block(0.62, field="Bestrittener Versandtag: {value}"),
        0,
        None,
    ),
    # a three-cell row in the block: a table's row, never a field
    (
        "a-table-s-row-in-the-block",
        *_letterhead_block(
            0.62, left="Lindenweg 4   Zimmer 12   Raum 3", field="Tag der Aufgabe zur Post: {value}"
        ),
        0,
        None,
    ),
]


def test_a_label_starting_a_cell_counts_only_in_the_information_block() -> None:
    def check(_id: str, text: str, words: list[list[Any]], at: int, day: str | None) -> None:
        pages: list[Any] = [(1, "Seite 1", [], "text")] if at else []
        pages.append((len(pages) + 1, text, words, "text"))
        statement = posting_statement(pages, LETTER)
        assert statement is not None and statement.day == (D(day) if day else None), statement

    check_rows(INFO_BLOCK, check)


#: A letter served formally, or by a plain Einschreiben (made up): (id, the words naming its service, served
#: formally). Each stands in the letterhead's posting day's letter, above its header, in its letterhead and in its
#: body.
SERVICE = [
    (
        "einschreiben-mit-rueckschein",
        "Dieser Bescheid wird Ihnen durch Einschreiben mit Rückschein zugestellt.",
        True,
    ),
    ("gegen-empfangsbekenntnis", "Gegen Empfangsbekenntnis", True),
    ("gegen-eb", "Gegen EB", True),
    ("section-5", "Zustellung nach § 5 Abs. 4 VwZG", True),
    ("section-5-with-its-sentence", "Zustellung nach § 5 Absatz 4 Satz 1 VwZG", True),
    ("section-5-among-others", "Zugestellt gemäß §§ 5, 10 VwZG", True),
    ("paragraph-5-written-out", "Zustellung nach Paragraph 5 VwZG", True),
    ("a-pzu", "Mit Postzustellungsurkunde", True),
    ("a-pzu-in-a-sentence", "Die Zustellung erfolgt durch Postzustellungsurkunde (§ 3 VwZG).", True),
    ("a-zustellungsurkunde", "Zustellung durch die Post mit Zustellungsurkunde.", True),
    ("pzu-for-short", "Zustellung mit PZU", True),
    ("section-3", "Zustellung nach § 3 VwZG.", True),
    ("section-3-with-its-subsection", "Zustellung gemäß § 3 Abs. 2 VwZG", True),
    ("the-zpo-s-sections", "Zustellung nach §§ 177 ff. ZPO", True),
    ("the-zpo-s-section-178", "Ersatzzustellung nach § 178 ZPO", True),
    ("a-land-s-service-law", "Zustellung nach dem Landeszustellungsgesetz", True),
    ("a-land-s-service-law-for-short", "Zustellung nach § 3 LZG", True),
    ("served-formally", "Dieser Bescheid wird Ihnen förmlich zugestellt.", True),
    ("a-formal-service", "Förmliche Zustellung", True),
    (
        "a-plain-einschreiben",
        "Die Zustellung erfolgt mittels Einschreiben durch Übergabe (§ 4 VwZG).",
        False,
    ),
    ("ordinary-post", "", False),
]


def test_a_letter_served_formally_never_counts_from_its_posting() -> None:
    """Served formally — by Postzustellungsurkunde (§ 3 VwZG, §§ 177 ff. ZPO), with a Rückschein or an
    Empfangsbekenntnis (§ 4 Abs. 2 S. 1, § 5 VwZG), under a Land's service law — the letter counts from its
    service, so the page's posting day never starts its period (Fri 20 Nov, from the letter's date); a plain
    Einschreiben counts from its posting (§ 4 Abs. 2 S. 2 VwZG: the fourth day after it), so it does (Mon 23 Nov),
    as a letter by ordinary post."""
    spec = DateSpec(
        type="relative",
        anchor="deemed_delivery",
        amount=1,
        unit="months",
        delivery_rule="de_admin_post",
        nature="objection",
    )
    field = "Tag der Aufgabe zur Post: 19.10.2026"

    def check(_id: str, service: str, formal: bool) -> None:
        for page in (
            f"{service}\n{head(field)}",
            f"{HEADER}{field}\n\n{service}{SALUTATION}",
            f"{head(field)}\n{service}",
        ):
            statement = found(page)
            assert (
                statement is not None and statement.day == D("2026-10-19") and statement.formal == formal
            ), page
            context = RuleContext(
                today=D("2026-10-22"),
                region="NW",
                document_date=LETTER,
                delivery_scope="vwvfg",
                posting=statement,
            )
            assert compute_due(spec, context).due_date == ("2026-11-20" if formal else "2026-11-23"), page

    check_rows(SERVICE, check)


def _letterhead(
    value: str,
    left: str = "Lindenweg 4",
    *,
    label: str = "Tag der Aufgabe zur Post",
    top: str = "Frau Erika Beispiel",
    value_x: float = 0.65,
    value_y: float = 0.215,
) -> tuple[str, list[list[Any]]]:
    """A made-up DIN 5008 letterhead's two rows: the address column on the left (``top``, then ``left``), the
    posting ``label`` alone in the information block's column on the right, and on the next row the address's
    ``left`` words beside the ``value`` under the label (its box at ``value_x``, ``value_y``) — the text layer reads
    each row as one line."""
    text = f"{top:<29}{label}\n{left:<29}{value}\n"
    words = _row(0.20, (0.10, top), (0.65, label))
    return text, words + _row(0.215, (0.10, left)) + _row(value_y, (value_x, value))


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
    # the label alone on its text line in the block, the address column's name on the line above (the text layer
    # reads the label's row as the label alone): the boxes put it in the information block, so it opens its field
    (
        "the-label-alone-on-its-text-line-in-the-block",
        "Frau Erika Beispiel\nTag der Aufgabe zur Post\nLindenweg 4                  19.10.2026\n",
        _row(0.20, (0.10, "Frau Erika Beispiel"))
        + _row(0.215, (0.65, "Tag der Aufgabe zur Post"))
        + _row(0.23, (0.10, "Lindenweg 4"), (0.65, "19.10.2026")),
        "2026-10-19",
    ),
    (
        "the-label-alone-on-its-text-line-left-of-the-block",
        "Frau Erika Beispiel\nTag der Aufgabe zur Post\nLindenweg 4                  19.10.2026\n",
        _row(0.20, (0.10, "Frau Erika Beispiel"))
        + _row(0.215, (0.40, "Tag der Aufgabe zur Post"))
        + _row(0.23, (0.10, "Lindenweg 4"), (0.40, "19.10.2026")),
        None,
    ),
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
    # a future or a negation in the value row's other column: the posting is not done
    ("a-future-in-the-row-s-other-column", *_letterhead("19.10.2026", left="Wird nachgereicht"), None),
    ("a-negation-in-the-row-s-other-column", *_letterhead("19.10.2026", left="Nicht zugestellt"), None),
    # a date in the label's column whose box stands above the label (the text layer put it on the next line)
    ("a-date-above-the-label-by-its-box", *_letterhead("19.10.2026", value_y=0.19), None),
    # a label after a word in its cell (no column's gap before it): never its cell's label
    (
        "a-word-before-the-label-ending-its-line",
        *_letterhead("19.10.2026", label="Bestrittener Versandtag", value_x=0.78),
        None,
    ),
    # a label alone in the first cell of a row of labels, the other column with no value on the value's row
    (
        "a-label-in-the-first-cell-of-a-row-of-labels",
        "Tag der Aufgabe zur Post    Bekanntgabetag\n19.10.2026\n",
        _row(0.20, (0.62, "Tag der Aufgabe zur Post"), (0.85, "Bekanntgabetag"))
        + _row(0.215, (0.62, "19.10.2026")),
        "2026-10-19",
    ),
    # a label in a cell left of the information block, its value right under it: not the block's
    (
        "a-cell-s-label-left-of-the-block",
        "Termin   Aufgabe zur Post\n22.10.2026   19.10.2026",
        _row(0.20, (0.25, "Termin"), (0.40, "Aufgabe zur Post"))
        + _row(0.215, (0.25, "22.10.2026"), (0.40, "19.10.2026")),
        None,
    ),
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
        _row(0.20, (0.10, "Steuerart"), (0.40, "Zeitraum"), (0.65, "Aufgabe zur Post"))
        + _row(0.215, (0.10, "ESt"), (0.40, "2025"), (0.65, "19.10.2026")),
        None,
    ),
]


def test_a_label_ending_its_line_takes_only_the_date_under_it() -> None:
    """A posting label that ends its line takes the next line's date only where it stands under the label on the
    page (the words' boxes), as the header's "Datum" is read; without boxes only a label and a date each alone on
    their line; never a table's row — so another column's date (the day of delivery, an appointment) is never the
    posting day."""

    salutation = "Sehr geehrte Frau Beispiel,"

    def check(_id: str, text: str, words: list[list[Any]], day: str | None) -> None:
        # the letterhead ends at the salutation, below the rows and to their left
        page = f"{text}\n{salutation}\n"
        boxes = [*words, *_row(0.35, (0.10, salutation))] if words else []
        statement = posting_statement([(1, page, boxes, "text")], LETTER)
        assert statement is not None
        assert statement.day == (D(day) if day else None), statement
        # never in the body: the same rows under the salutation
        below = [[box[0], box[1], box[2] + 0.3, box[3], box[4] + 0.3] for box in words]
        under = posting_statement(
            [(1, f"{salutation}\n{text}", [*_row(0.10, (0.10, salutation)), *below], "text")], LETTER
        )
        assert under == PostingStatement(), under

    check_rows(TWO_ROWS, check)


def test_a_photo_s_transcription_is_model_read_unless_a_text_page_says_it_too() -> None:
    field = head("Tag der Aufgabe zur Post: 19.10.2026")
    photo = found(field, "transcript")
    assert photo is not None and (photo.day, photo.grounding) == (D("2026-10-19"), "model_read")
    # its second page, a text layer, says it too (in a notice: a later page's letterhead is never read)
    notice = "Hinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."
    both = posting_statement([(1, field, [], "transcript"), (2, notice, [], "text")], LETTER)
    assert both is not None and both.grounding == "verified"


def test_a_photo_s_doubt_counts_once_for_its_to_do() -> None:
    """A photo letter: the to-do's quote and the posting day both come from the transcript. The posting day keeps
    the date at most ``medium`` and the quote read from a transcript lowers it one level: counted once, ``medium``
    — not ``low`` for one photo (``ingest.plan.compute_item``)."""
    page = (
        1,
        head("Tag der Aufgabe zur Post: 19.10.2026")
        + "\nDer Einspruch ist innerhalb eines Monats einzulegen.",
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
        body("Hinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben.").replace(
            SALUTATION, f"Tag der Aufgabe zur Post: 21.10.2026\n{SALUTATION}"
        )
    )
    assert statement is not None
    assert (statement.day, statement.other) == (D("2026-10-19"), D("2026-10-21"))
    assert statement.quote == "Dieser Bescheid wurde am 19.10.2026 zur Post gegeben."
    assert statement.other_quote == "Tag der Aufgabe zur Post: 21.10.2026"
    agree = found(
        body("Hinweis: Dieser Bescheid wurde am 19.10.2026 zur Post gegeben.").replace(
            SALUTATION, f"Tag der Aufgabe zur Post: 19.10.2026\n{SALUTATION}"
        )
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
                added
                for line in POSTED_LATER.pages[0]
                for added in (
                    (line.replace("Aufgabeprobe", "Zweiaufgabe"),)
                    if "Aufgabeprobe" in line
                    else (line, "Absendetag: 20.10.2026")  # a second field, on its own line
                    if line.startswith("Tag der Aufgabe")
                    else (line,)
                )
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
