"""The re-review of the dropped-date check's looser path (ADR 0015, 2026-10-07), after which the path was narrowed.

Every confirmed false alarm and every wrong date of the re-review is a case here
(``tests/data/deadline_looser_rereview.json``): its letter files exactly what base 0ff51e3 files for it (nothing, for
all but the strict path's own dates). Dates without their year are read nowhere again; the looser wordings that
filed those false alarms are gone; what stays is a request that asks the person in its own words at its sentence's
start ("Senden Sie uns …", "Bitte gleichen Sie … aus", "Bitte lassen Sie uns … zukommen", "Wir bitten Sie um Zahlung
…", "Bitte bis … überweisen", "Kindly pay …", "Please ensure …") and a label on a page that asks for its kind. Each
guard that stays has a test here or in ``test_reading_gaps_looser_review.py`` that fails without it. Invented letters
only.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ordnung.ingest.gaps import (
    _OPTION_ASKED,
    _W_QUESTION,
    _label_kind,
    _noun_kind,
    _nouns_kind,
    _offers_option,
    deadline_items,
)
from ordnung.ingest.verify import PageInput
from ordnung.models import DocumentExtraction, ExtractedItem
from test_reading_gaps import blank, page
from test_reading_gaps_looser import TODAY, filed, reading

CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).parent / "data" / "deadline_looser_rereview.json").read_text(encoding="utf-8")
)
HEADS = {
    "de": (
        "Beispiel Service GmbH · Musterstraße 1 · 12345 Beispielhausen",
        "Frau Mara Probe",
        "Probeweg 2",
        "12345 Beispielhausen",
    ),
    "en": (
        "Example Services Ltd · 1 High Street · London",
        "Ms Mara Probe",
        "Probeweg 2",
        "12345 Beispielhausen",
    ),
}
W = date(2026, 10, 5)
PAYS = [("2026-10-23", "payment")]
SENDS = [("2026-10-23", "declaration")]


def _case_letter(case: dict[str, Any]) -> tuple[DocumentExtraction, PageInput]:
    written = date.fromisoformat(case["written"])
    german = case["lang"] == "de"
    return reading(written), page(
        *HEADS[case["head"]],
        f"Datum: {written:%d.%m.%Y}",
        "Sehr geehrte Frau Probe," if german else "Dear Ms Probe,",
        *case["body"],
        "Mit freundlichen Grüßen" if german else "Yours sincerely,",
    )


def test_the_re_review_s_cases_are_all_here() -> None:
    assert len(CASES) == 271
    assert len({case["id"] for case in CASES}) == len(CASES)
    # nothing new: base 0ff51e3 files a date for only a few of them (its own strict dates, kept)
    assert sum(1 for case in CASES if case["expected"]) <= 10


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_a_confirmed_false_alarm_or_wrong_date_files_only_what_base_files(case: dict[str, Any]) -> None:
    extraction, letter_page = _case_letter(case)
    found = deadline_items(extraction, [letter_page], today=date.fromisoformat(case["today"]))
    assert [[item.date.date, item.date.nature] for item in found] == case["expected"], case["finding"]


def in_letter(*lines: str, lang: str = "de") -> list[tuple[str | None, str]]:
    found = deadline_items(
        reading(W),
        [
            page(
                *HEADS[lang],
                "Datum: 05.10.2026",
                "Sehr geehrte Frau Probe," if lang == "de" else "Dear Ms Probe,",
                *lines,
                "Mit freundlichen Grüßen" if lang == "de" else "Yours sincerely,",
            )
        ],
        today=TODAY,
    )
    return [(item.date.date, item.date.nature) for item in found]


# --------------------------------------------------------------------------------------------------
# Dates without their year: read nowhere (the year a sentence names, a year-shaped number, "next year", an old line)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "written", "lang"),
    [
        ("Bitte überweisen Sie den Betrag bis zum 15.11.", W, "de"),
        ("Zahlbar bis: 15.11.", W, "de"),
        ("Please pay by 15 November.", W, "en"),
        ("Bitte überweisen Sie den Betrag bis zum 15.01.", date(2026, 12, 10), "de"),
        ("Bitte gleichen Sie den Betrag bis zum 23.10. aus.", W, "de"),
        ("Bitte überweisen Sie den Beitrag.\nZahlungsfrist: 23.10.", W, "de"),
        ("Bitte reichen Sie die Unterlagen bis zum 31.12. des Jahres 2027 ein.", W, "de"),
        (
            "Bitte reichen Sie die Unterlagen bis zum 31. März des nächsten Jahres ein.",
            date(2026, 1, 10),
            "de",
        ),
    ],
)
def test_a_date_without_its_year_files_nothing(sentence: str, written: date, lang: str) -> None:
    assert filed(sentence, written, lang, today=written) == []


def test_the_same_requests_with_their_year_file() -> None:
    assert filed("Bitte überweisen Sie den Betrag bis zum 15.11.2026.", W) == [("2026-11-15", "payment")]
    assert filed("Bitte gleichen Sie den Betrag bis zum 23.10.2026 aus.", W) == PAYS
    assert filed("Bitte überweisen Sie den Beitrag.\nZahlungsfrist: 23.10.2026", W) == PAYS


# --------------------------------------------------------------------------------------------------
# What stays: a request in the person's own words, at its sentence's start
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sentence", "lang", "expected"),
    [
        ("Senden Sie uns die Unterlagen bis zum 23.10.2026.", "de", SENDS),
        ("Bitte senden Sie uns Ihren Steuerbescheid bis zum 23.10.2026.", "de", SENDS),
        ("Bitte gleichen Sie den offenen Betrag bis zum 23.10.2026 aus.", "de", PAYS),
        ("Bitte lassen Sie uns die fehlenden Belege bis zum 23.10.2026 zukommen.", "de", SENDS),
        ("Wir bitten Sie um Zahlung bis zum 23.10.2026.", "de", PAYS),
        ("Bitte bis zum 23.10.2026 überweisen.", "de", PAYS),
        ("Bitte bis 23.10.2026 ausgefüllt und unterschrieben zurücksenden.", "de", SENDS),
        ("Kindly pay the outstanding amount by 23 October 2026.", "en", PAYS),
        ("Please ensure that your payment reaches us by 23 October 2026.", "en", PAYS),
        ("Bitte überweisen Sie den Betrag auf unser Konto.\nZahlungsfrist: 23.10.2026", "de", PAYS),
        ("Bitte überweisen Sie den Betrag.\nZahlungseingang bis: 23.10.2026 | 120,00 € | offen", "de", PAYS),
        ("Bitte senden Sie uns die Unterlagen.\nAbgabetermin: 23.10.2026", "de", SENDS),
        ("Bitte füllen Sie den Bogen aus.\nRückantwort erbeten bis Freitag, 23.10.2026.", "de", SENDS),
        ("Please return the signed form to us.\nReply by: 23 October 2026", "en", SENDS),
    ],
)
def test_a_request_in_the_person_s_own_words_still_files(
    sentence: str, lang: str, expected: list[tuple[str, str]]
) -> None:
    assert filed(sentence, W, lang) == expected


@pytest.mark.parametrize(
    ("sentence", "lang"),
    [
        # a condition or group no list names, before the request (finding: conditions and groups)
        ("Bei Nichtgefallen senden Sie uns die Ware bis zum 23.10.2026.", "de"),
        ("Sobald Sie umgezogen sind, senden Sie uns Ihre neue Anschrift bis zum 23.10.2026.", "de"),
        ("Bei Inanspruchnahme der Ratenzahlung bitte bis zum 23.10.2026 überweisen.", "de"),
        ("Als Grenzgänger lassen Sie uns bitte Ihre Bescheinigung bis zum 23.10.2026 zukommen.", "de"),
        ("When moving out, please ensure the keys reach us by 23 October 2026.", "en"),
        ("For self-employed members, kindly return the form by 23 October 2026.", "en"),
        # any other words before it, too (a miss, never a false alarm: precision first)
        ("Den Betrag bitte bis zum 23.10.2026 überweisen.", "de"),
        ("Daher bitten wir Sie um Zahlung bis zum 23.10.2026.", "de"),
    ],
)
def test_words_before_the_request_in_its_sentence_file_nothing(sentence: str, lang: str) -> None:
    assert filed(sentence, W, lang) == []


def test_a_request_after_the_greeting_s_line_opens_its_sentence() -> None:
    assert in_letter("bitte gleichen Sie den offenen Betrag bis zum 23.10.2026 aus.") == PAYS
    assert in_letter("• Bitte bis zum 23.10.2026 überweisen.") == PAYS


@pytest.mark.parametrize(
    "sentence",
    [
        # a possessive alone names no one as the one to act
        "Wir bitten um Rücksendung Ihres unterschriebenen Vertrags bis zum 23.10.2026.",
        "Wir bitten um Zahlung Ihrer Versicherung bis zum 23.10.2026.",
        # "sie" (they), not "Sie"
        "Senden sie uns die Unterlagen bis zum 23.10.2026.",
        # "Sie" in the sentence, but not as the one the sender asks
        "Wir bitten um Rücksendung des Vertrags, den Sie bis zum 23.10.2026 unterschreiben.",
    ],
)
def test_a_request_that_does_not_name_the_person_as_the_one_to_act_files_nothing(sentence: str) -> None:
    assert filed(sentence, W) == []


@pytest.mark.parametrize(
    "sentence",
    [
        "Bitte bis zum 23.10.2026 abwarten und erst danach überweisen.",
        "Bitte bis zum 23.10.2026 nichts überweisen.",
        "Bitte bis zum 23.10.2026 warten und dann überweisen.",
        "Bitte bis zum 23.10.2026 abwarten und überweisen.",
        "Bitte bis zum 23.10.2026 nicht überweisen.",
    ],
)
def test_bitte_bis_with_a_wait_or_a_negation_before_the_infinitive_files_nothing(sentence: str) -> None:
    assert filed(sentence, W) == []


# --------------------------------------------------------------------------------------------------
# Labels: a window's first day, a statement's or overview's page
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lines", "lang"),
    [
        (("Bitte überweisen Sie den Beitrag.", "Zahlungsfrist: 01.11.2026 bis spätestens 15.11.2026"), "de"),
        (("Bitte überweisen Sie den Beitrag.", "Zahlungsfrist: 01.11.2026 bis einschl. 15.11.2026"), "de"),
        (("Bitte reichen Sie die Unterlagen ein.", "Abgabefrist: 01.11.2026 bis inkl. 15.11.2026"), "de"),
        (("Bitte überweisen Sie den Beitrag.", "Zahlungsfrist: 01.11.2026 bis Monatsende"), "de"),
        (("Bitte reichen Sie die Unterlagen ein.", "Abgabefrist: 01.11.2026 – Ende November"), "de"),
        (("Bitte überweisen Sie den Beitrag.", "Zahlungsfrist: 01.11.2026 zzgl. 14 Tage"), "de"),
        (("Please pay the invoice.", "Payment deadline: 1 November 2026 up to 15 November 2026"), "en"),
        (("Please pay the invoice.", "Payment deadline: 1 November 2026 until the end of the month"), "en"),
    ],
)
def test_a_label_s_date_with_more_words_after_it_on_its_line_files_nothing(
    lines: tuple[str, ...], lang: str
) -> None:
    assert in_letter(*lines, lang=lang) == []


def test_a_label_s_date_followed_by_a_field_separator_or_a_bracket_files() -> None:
    assert in_letter("Bitte überweisen Sie den Betrag.", "Zahlung bis: 23.10.2026 · 120,00 €") == PAYS
    assert (
        in_letter("Bitte senden Sie uns die Unterlagen.", "Abgabefrist: 23.10.2026 (Eingang bei uns)")
        == SENDS
    )


@pytest.mark.parametrize(
    ("lines", "lang"),
    [
        (("Umsatzübersicht Oktober", "Ihre Zahlung muss bis zum 30.10.2026 bei uns eingegangen sein, damit sie in "
          "dieser Übersicht erscheint."), "de"),
        (("Your quarterly overview", "Your payment must reach us by 30 October 2026 to be listed in this overview."),
         "en"),
        (("Kontoauszug Oktober", "Bitte überweisen Sie den Saldo.", "Letzter Zahlungstag: 30.10.2026"), "de"),
    ],
)  # fmt: skip
def test_a_statement_s_cut_off_files_nothing(lines: tuple[str, ...], lang: str) -> None:
    assert in_letter(*lines, lang=lang) == []


# --------------------------------------------------------------------------------------------------
# The kind: the verb and the nouns must agree; a compound counts by its last part; "rate" only whole
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "Senden Sie uns den ausstehenden Betrag bis zum 23.10.2026.",
        "Bitte senden Sie uns Ihre Zahlung bis zum 23.10.2026.",
        "Bitte senden Sie uns Ihre Rechnung über die erbrachten Leistungen bis zum 23.10.2026.",
        "Bitte lassen Sie uns Ihre Steuer-ID bis zum 23.10.2026 zukommen.",
        "Bitte lassen Sie uns Ihre Gebühren-Übersicht bis zum 23.10.2026 zukommen.",
        "Bitte lassen Sie uns Ihre Inserate bis zum 23.10.2026 zukommen.",
    ],
)
def test_an_unclear_kind_files_nothing(sentence: str) -> None:
    assert filed(sentence, W) == []


def test_a_word_ending_in_rate_names_no_rate() -> None:
    assert (
        filed("Please ensure that your accurate meter readings reach us by 23 October 2026.", W, "en") == []
    )
    assert (
        _noun_kind("accurate") is None and _noun_kind("Inserate") is None and _noun_kind("Monatsrate") is None
    )
    assert _noun_kind("Rate") == ("payment", False) and _noun_kind("rates") is None


def test_a_hyphenated_compound_counts_by_its_last_part() -> None:
    assert _nouns_kind("Ihre Steuer-ID") is None  # its first part names money, its last part nothing: unclear
    assert _nouns_kind("Ihre Gebühren-Übersicht") is None
    assert _nouns_kind("die Kfz-Steuer") == "payment"
    assert _nouns_kind("den Miet-Nachweis") == "declaration"
    assert _nouns_kind("die Steuer-Bescheinigung") is None  # the parts disagree: unclear


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ("\nZahlungsfrist: ", "payment"),
        ("\nLetzter Zahlungstag: ", "payment"),
        ("\nZahlungseingang bis: ", "payment"),
        ("\nPayment deadline: ", "payment"),
        ("\nDeadline for payment: ", "payment"),
        ("\nRücksendung bis: ", "declaration"),
        # a compound whose last word is no payment, or a payment that is only what a document is about
        ("\nFrist für die Zahlungsbestätigung: ", None),
        ("\nFrist für den Zahlungsnachweis: ", None),
        ("\nFrist für Ihren Überweisungsbeleg: ", None),
        ("\nDeadline for proof of payment: ", None),
    ],
)
def test_a_label_s_kind_is_its_whole_word_s(words: str, expected: str | None) -> None:
    assert _label_kind(words, words) == expected


def test_a_verb_on_the_label_s_line_tells_its_kind() -> None:
    assert in_letter("Bitte überweisen Sie den Betrag.", "Rest überweisen – Frist: 23.10.2026") == PAYS
    assert in_letter("Bitte überweisen Sie den Betrag.", "Rest – Frist: 23.10.2026") == []  # no kind named


def test_a_label_for_proof_of_payment_files_nothing() -> None:
    assert (
        in_letter("Bitte überweisen Sie den Betrag umgehend.", "Frist für den Zahlungsnachweis: 20.11.2026")
        == []
    )
    assert (
        in_letter(
            "Please pay the outstanding amount.", "Deadline for proof of payment: 20 November 2026", lang="en"
        )
        == []
    )


# --------------------------------------------------------------------------------------------------
# What a page of holidays or opening hours does and does not stop (ADR 0015 says exactly this)
# --------------------------------------------------------------------------------------------------


def test_a_holiday_or_opening_hours_page_stops_its_labels_not_a_request_in_the_person_s_own_words() -> None:
    hours = "Unsere Öffnungszeiten: Mo–Fr 8–16 Uhr."
    assert in_letter(hours, "Bitte überweisen Sie den Betrag.", "Zahlungsfrist: 20.11.2026") == []
    assert in_letter(hours, "Bitte gleichen Sie den Betrag bis zum 20.11.2026 aus.") == [
        ("2026-11-20", "payment")
    ]
    assert in_letter("Bitte überweisen Sie den Betrag.", "Zahlungsfrist: 20.11.2026") == [
        ("2026-11-20", "payment")
    ]
    # in the request's own sentence, a holiday's or closing's word stops it
    assert (
        in_letter("Bitte bis zum 20.11.2026 überweisen, da wir über die Feiertage geschlossen haben.") == []
    )


# --------------------------------------------------------------------------------------------------
# Each guard that stays, alone: a sentence it stops, and the same sentence without its word, which files
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("guarded", "control", "lang"),
    [
        # _NOT_OWED (the strict path's words): a condition
        ("Bitte bis zum 23.10.2026 überweisen, falls noch offen.", "Bitte bis zum 23.10.2026 überweisen.", "de"),
        # _LOOSE_NOT_OWED: an option, a cut-off, the earliest day
        ("Bitte bis zum 23.10.2026 überweisen, wenn möglich.", "Bitte bis zum 23.10.2026 überweisen.", "de"),
        ("Bitte bis zum 23.10.2026 freiwillig überweisen.", "Bitte bis zum 23.10.2026 überweisen.", "de"),
        ("Kindly pay the amount by 23 October 2026 at the earliest.", "Kindly pay the amount by 23 October 2026.",
         "en"),
        # _LOOSE_CONDITION: "ggf.", "bei Bedarf", "in case of"
        ("Bitte ggf. bis zum 23.10.2026 überweisen.", "Bitte bis zum 23.10.2026 überweisen.", "de"),
        ("Bitte bei Bedarf bis zum 23.10.2026 überweisen.", "Bitte bis zum 23.10.2026 überweisen.", "de"),
        ("Kindly pay the amount by 23 October 2026 in case of a claim.", "Kindly pay the amount by 23 October 2026.",
         "en"),
        # _SENDER_ACTS: the sender's own processing
        (
            "Bitte bis zum 23.10.2026 überweisen, damit wir die Bearbeitung abschließen.",
            "Bitte bis zum 23.10.2026 überweisen.",
            "de",
        ),
        # _SENDER_DID: the sender's past request in the same sentence
        ("Bitte bis zum 23.10.2026 überweisen, wie wir Sie im Mai gebeten haben; wir haben Sie aufgefordert.",
         "Bitte bis zum 23.10.2026 überweisen.", "de"),
        # _DONE: done or only stated
        ("Bitte bis zum 23.10.2026 überweisen – das hat sich erledigt.", "Bitte bis zum 23.10.2026 überweisen.", "de"),
        ("Kindly pay the amount by 23 October 2026; it has been received.", "Kindly pay the amount by 23 October 2026.",
         "en"),
        # _NOT_A_DEMAND: an offer, a survey, a contest
        ("Senden Sie uns den Fragebogen zur Kundenumfrage bis zum 23.10.2026.",
         "Senden Sie uns den Fragebogen bis zum 23.10.2026.", "de"),
        # _CLOSED: a holiday or closing in the request's own sentence
        ("Bitte bis zum 23.10.2026 überweisen, da wir über die Feiertage geschlossen haben.",
         "Bitte bis zum 23.10.2026 überweisen.", "de"),
        # _REMEDY: a remedy's sentence is the remedy check's (as on the strict path)
        ("Senden Sie uns Ihren Widerspruch bis zum 23.10.2026.", "Senden Sie uns Ihre Antwort bis zum 23.10.2026.",
         "de"),
        # _PERIOD_END: what the payment is for
        ("Bitte gleichen Sie den Beitrag für den Zeitraum bis zum 31.12.2026 aus.",
         "Bitte gleichen Sie den Beitrag bis zum 31.12.2026 aus.", "de"),
        # _RANGE_START: a window's first day (words and labels no other guard stops)
        ("Kindly pay the amount by 1 November 2026 to 15 November 2026.", "Kindly pay the amount by 1 November 2026.",
         "en"),
        # _VERB_FIRST and _GROUP_ONLY: a label in a sentence opened by a condition's verb or a group
        ("Bitte senden Sie uns die Unterlagen.\nHaben Sie Kinder unter 18 Jahren, Frist für den Nachweis: "
         "23.10.2026", "Bitte senden Sie uns die Unterlagen.\nFrist für den Nachweis: 23.10.2026", "de"),
        ("Bitte senden Sie uns die Unterlagen.\nFür Mitglieder – Abgabefrist: 23.10.2026",
         "Bitte senden Sie uns die Unterlagen.\nAbgabefrist: 23.10.2026", "de"),
        # _TO_YOU: money that comes to the person
        ("Senden Sie uns die Unterlagen bis zum 23.10.2026, damit wir Ihnen das Kindergeld zahlen.",
         "Senden Sie uns die Unterlagen bis zum 23.10.2026.", "de"),
        # _THIRD_PARTY: another party in the sentence
        ("Senden Sie uns die Bescheinigung Ihres Arbeitgebers bis zum 23.10.2026.",
         "Senden Sie uns die Bescheinigung bis zum 23.10.2026.", "de"),
    ],
)  # fmt: skip
def test_each_guard_alone_stops_a_request(guarded: str, control: str, lang: str) -> None:
    assert filed(guarded, W, lang) == []
    assert filed(control, W, lang) != []


def test_a_labelled_sentence_s_window_files_nothing() -> None:
    lines = ("Bitte füllen Sie den Bogen aus.", "Rückantwort erbeten bis 01.11.2026 – 15.11.2026.")
    assert in_letter(*lines) == []
    assert in_letter(lines[0], "Rückantwort erbeten bis 01.11.2026.") == [("2026-11-01", "declaration")]


def test_a_strict_date_on_the_page_is_its_request_for_a_label() -> None:
    """A strict date of the person's still counts as the page's request for a label of its kind (its own date past
    when the letter is read, so it covers nothing)."""
    lines = ("Die Nachweise sind bis zum 06.10.2026 vorzulegen.", "Abgabefrist: 23.10.2026")
    assert in_letter(*lines) == SENDS
    assert in_letter(lines[1]) == []


def test_a_strict_date_in_a_guarded_sentence_neither_covers_nor_asks() -> None:
    lines = ("Falls noch offen, überweisen Sie den Rest bis zum 30.11.2026.",)
    assert in_letter(*lines, "Bitte gleichen Sie den Betrag bis zum 23.10.2026 aus.") == PAYS
    assert in_letter(*lines, "Zahlungsfrist: 23.10.2026") == []


@pytest.mark.parametrize(
    "ask",
    [
        "Falls noch offen, überweisen Sie den Betrag.",  # a condition (_NOT_OWED)
        "Bitte überweisen Sie den Betrag nicht.",  # a negation (_LOOSE_NOT_OWED)
    ],
)
def test_a_page_s_request_in_a_condition_or_negation_asks_for_no_label(ask: str) -> None:
    assert in_letter(ask, "Zahlungsfrist: 23.10.2026") == []
    assert in_letter("Bitte überweisen Sie den Betrag.", "Zahlungsfrist: 23.10.2026") == PAYS


def test_the_letter_s_own_date_or_one_past_when_read_files_nothing() -> None:
    sentence = "Bitte gleichen Sie den Betrag bis zum {} aus."
    assert filed(sentence.format("05.10.2026"), W, today=date(2026, 10, 1)) == []  # the letter's own date
    assert filed(sentence.format("06.10.2026"), W) == []  # past when the letter is read (07.10.)
    assert filed(sentence.format("06.10.2026"), W, today=date(2026, 10, 6)) == [("2026-10-06", "payment")]


def test_a_reading_s_to_do_or_instalment_near_a_looser_date_of_another_kind_covers_it() -> None:
    sentence = "Senden Sie uns die Unterlagen bis zum 15.11.2026."

    def payment(on: str, monthly: bool) -> ExtractedItem:
        return ExtractedItem.model_validate(
            {
                "kind": "payment",
                "title": "Pay",
                "date": {"type": "fixed", "date": on, "nature": "payment"},
                "quote": "Rate",
                **({"recurrence": {"freq": "monthly", "day_of_month": 15}} if monthly else {}),
            }
        )

    assert filed(sentence, W) == [("2026-11-15", "declaration")]
    assert (
        filed(sentence, W, items=[payment("2026-11-13", False)]) == []
    )  # within 3 days of the reading's to-do
    assert filed(sentence, W, items=[payment("2026-10-15", True)]) == []  # a later instalment's day
    assert filed(sentence, W, items=[payment("2026-10-15", False)]) == [("2026-11-15", "declaration")]


def test_the_full_price_beside_the_reading_s_payment_files_nothing() -> None:
    undated = ExtractedItem.model_validate(
        {
            "kind": "payment",
            "title": "Pay",
            "date": {"type": "none", "nature": "payment"},
            "quote": "Rechnung",
        }
    )
    assert filed("Bitte gleichen Sie den Betrag ohne Abzug bis zum 23.10.2026 aus.", W, items=[undated]) == []
    assert filed("Bitte gleichen Sie den Betrag bis zum 23.10.2026 aus.", W, items=[undated]) == PAYS


def test_the_sender_s_name_is_no_third_party() -> None:
    sparkasse = (
        "Sparkasse Beispielhausen · Markt 1 · 12345 Beispielhausen",
        "Frau Mara Probe",
        "Datum: 05.10.2026",
        "Sehr geehrte Frau Probe,",
        "Bitte gleichen Sie den Betrag bei der Sparkasse bis zum 23.10.2026 aus.",
        "Mit freundlichen Grüßen",
    )
    extraction = blank(
        sender={"name": "Sparkasse Beispielhausen", "kind": "company"}, document_date="2026-10-05"
    )
    found = deadline_items(extraction, [page(*sparkasse)], today=TODAY)
    assert [(item.date.date, item.date.nature) for item in found] == PAYS
    other = blank(sender={"name": "Stadtwerke Beispielhausen", "kind": "company"}, document_date="2026-10-05")
    assert deadline_items(other, [page(*sparkasse)], today=TODAY) == []


def test_a_purpose_of_the_sender_s_is_struck_out_before_its_acts_are_read() -> None:
    sentence = "Damit wir Ihren Antrag bearbeiten können, senden Sie uns die Unterlagen bis zum 23.10.2026."
    assert filed(sentence, W) == []  # words before the request: it no longer opens its sentence
    assert filed("Senden Sie uns die Unterlagen zur Bearbeitung bis zum 23.10.2026.", W) == SENDS


@pytest.mark.parametrize(
    ("lines", "control"),
    [
        # _STATUS: a status letter's page
        (("Sachstand Ihres Antrags", "Bitte senden Sie uns die Unterlagen.", "Abgabefrist: 23.10.2026"),
         ("Ihr Antrag", "Bitte senden Sie uns die Unterlagen.", "Abgabefrist: 23.10.2026")),
        # _NOT_A_DEMAND on the page: an offer's page
        (("Unser Angebot für Sie", "Bitte senden Sie uns die Unterlagen.", "Abgabefrist: 23.10.2026"),
         ("Unser Schreiben an Sie", "Bitte senden Sie uns die Unterlagen.", "Abgabefrist: 23.10.2026")),
        # _CLOSED on the page: office hours in a sentence of their own
        (("Unsere Sprechzeiten haben sich geändert.", "Bitte senden Sie uns die Unterlagen.", "Abgabefrist: 23.10.2026"),
         ("Unsere Telefonnummer hat sich geändert.", "Bitte senden Sie uns die Unterlagen.", "Abgabefrist: 23.10.2026")),
        # the page asks for the other kind only
        (("Bitte überweisen Sie den Betrag.", "Abgabefrist: 23.10.2026"),
         ("Bitte senden Sie uns die Unterlagen.", "Abgabefrist: 23.10.2026")),
    ],
)  # fmt: skip
def test_each_page_guard_alone_stops_a_label(lines: tuple[str, ...], control: tuple[str, ...]) -> None:
    assert in_letter(*lines) == []
    assert in_letter(*control) == SENDS


def test_a_page_that_says_nothing_needs_doing_files_nothing() -> None:
    assert (
        in_letter("Sie müssen nichts weiter tun.", "Bitte gleichen Sie den Betrag bis zum 23.10.2026 aus.")
        == []
    )
    assert in_letter("Bitte gleichen Sie den Betrag bis zum 23.10.2026 aus.") == PAYS


def test_an_option_offered_by_the_question_before_files_nothing() -> None:
    assert (
        in_letter("Sie möchten Ihren Vertrag verlängern?", "Senden Sie uns das Formular bis zum 23.10.2026.")
        == []
    )
    assert in_letter("Senden Sie uns das Formular bis zum 23.10.2026.") == SENDS
    # a W-question heading offers nothing
    assert in_letter("Was müssen Sie tun?", "Senden Sie uns das Formular bis zum 23.10.2026.") == SENDS


def test_the_obligation_must_go_to_the_sender() -> None:
    assert filed("Senden Sie die Unterlagen bis zum 23.10.2026 an die Gemeinde.", W) == []
    assert filed("Senden Sie die Unterlagen bis zum 23.10.2026 an uns zurück.", W) == SENDS
    assert filed("Please ensure the form reaches the council office by 23 October 2026.", W, "en") == []


def test_a_paid_or_debited_letter_gates_a_looser_payment() -> None:
    assert (
        in_letter(
            "Der Rechnungsbetrag wurde bereits beglichen.",
            "Bitte gleichen Sie den Betrag bis zum 23.10.2026 aus.",
        )
        == []
    )
    assert (
        in_letter(
            "Die Gebühr wird per SEPA-Lastschrift eingezogen.",
            "Bitte gleichen Sie den Betrag bis zum 23.10.2026 aus.",
        )
        == []
    )
    assert in_letter("Bitte gleichen Sie den Betrag bis zum 23.10.2026 aus.") == PAYS


def test_a_reading_s_warning_that_doubts_the_money_stops_the_looser_path() -> None:
    lines = ("Bitte gleichen Sie den Betrag bis zum 23.10.2026 aus.",)
    doubted = blank(
        sender={"name": "Beispiel Service GmbH", "kind": "company"},
        document_date="2026-10-05",
        warnings=["The payee IBAN differs from the sender's usual account."],
    )
    letter_page = page(*HEADS["de"], "Datum: 05.10.2026", "Sehr geehrte Frau Probe,", *lines)
    assert deadline_items(doubted, [letter_page], today=TODAY) == []
    assert in_letter(*lines) == PAYS


def test_a_reading_s_dated_to_do_of_the_kind_covers_a_looser_date() -> None:
    sentence = "Bitte gleichen Sie den Betrag bis zum 23.10.2026 aus."
    other = ExtractedItem.model_validate(
        {
            "kind": "payment",
            "title": "Pay",
            "date": {"type": "fixed", "date": "2026-11-30", "nature": "payment"},
            "quote": "Rechnung",
        }
    )
    assert filed(sentence, W, items=[other]) == []
    assert filed(sentence, W) == PAYS


# --------------------------------------------------------------------------------------------------
# Long untrusted text: no scan per date, no regex that backtracks over the page
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        # many greetings' lines and many dates in one sentence (each date's region found by bisection)
        "\n".join(["Hallo,"] * 10 + ["01.11.2026 x"]) * 1500,
        # a long question before a dated request: the base path skips it ("Wenn"), the looser path reads the question
        # only after its last but one "?"
        "möchten " * 25000 + "? Wenn Sie Fragen haben, rufen Sie uns bis zum 23.10.2026 an.",
    ],
    ids=["greetings-and-dates", "option-question"],
)
def test_the_looser_path_stays_fast_on_long_untrusted_text(body: str) -> None:
    started = time.monotonic()
    deadline_items(reading(W), [page(*HEADS["de"], "Datum: 05.10.2026", body)], today=TODAY)
    assert time.monotonic() - started < 5


def test_the_option_question_is_read_as_the_strict_path_reads_it_in_linear_time() -> None:
    for asked in [
        "Sie möchten Ihren Vertrag nicht verlängern?",
        "Möchten Sie wechseln? Haben Sie Fragen?",
        "Haben Sie Fragen? Möchten Sie wechseln?",
        "Was müssen Sie tun? Möchten Sie wechseln?",
        "Möchten Sie wechseln",
        "Möchten Sie wechseln? ",
    ]:
        assert _offers_option(asked) == bool(
            _OPTION_ASKED.search(asked.strip()) and not _W_QUESTION.match(asked.strip())
        ), asked
    started = time.monotonic()
    assert not _offers_option("möchten " * 25000 + "? x ?")
    assert _offers_option("x ? " + "möchten " * 25000 + "?")
    assert time.monotonic() - started < 1
