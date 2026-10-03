"""The round-5 limits review, dates lens (R5D-1 to R5D-4): town forms, an as-of date in the body, a stamp on the first
line, and the envelope never starting another decision's notice. Invented letters only."""

from __future__ import annotations

from datetime import date

import pytest

from ordnung.ingest.gaps import formally_served, letter_date
from test_reading_gaps import blank, page
from test_reading_gaps_round5 import computed

NOTICE = "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden."
LETTER_DAY = date(2026, 11, 6)


def town_letter(sender_town: str, place: str) -> list:
    return [
        page(
            f"Stadt Musterort · Ordnungsamt · Hauptstraße 1 · {sender_town}",
            "Frau Mara Probe",
            "Probeweg 2",
            "63065 Offenbach am Main",
            "",
            f"{place}, 06.11.2026",
            "",
            "Gebührenbescheid",
            "Sehr geehrte Frau Probe,",
            "mit diesem Bescheid setzen wir eine Gebühr von 85,00 EUR fest.",
            "Rechtsbehelfsbelehrung",
            NOTICE,
        )
    ]


@pytest.mark.parametrize(
    ("sender_town", "place"),
    [
        ("60275 Frankfurt am Main", "Frankfurt a. M."),
        ("60275 Frankfurt am Main", "Frankfurt a.M."),
        ("60275 Frankfurt am Main", "Frankfurt-Höchst"),
        ("60326 Frankfurt/Main", "Frankfurt am Main"),
        ("79098 Freiburg im Breisgau", "Freiburg i. Br."),
        ("06108 Halle/Saale", "Halle (Saale)"),
        ("45468 Mülheim an der Ruhr", "Mülheim a. d. Ruhr"),
        ("61348 Bad Homburg", "Bad Homburg v. d. Höhe"),
    ],
)
def test_a_town_written_short_or_with_its_district_is_the_letter_s_own_place(
    sender_town: str, place: str
) -> None:
    assert letter_date(blank(), town_letter(sender_town, place), today=date(2026, 11, 20)) == LETTER_DAY


def test_a_town_over_the_recipient_s_name_is_that_town_alone() -> None:
    pages = [
        page(
            "Bezirksamt Mitte von Berlin",
            "13341 Berlin",
            "Frau Mara Probe",
            "Probeweg 2",
            "10115 Berlin",
            "",
            "Berlin-Mitte, 06.11.2026",
            "",
            "Gebührenbescheid",
            "Sehr geehrte Frau Probe,",
            "mit diesem Bescheid setzen wir eine Gebühr von 85,00 EUR fest.",
            "Rechtsbehelfsbelehrung",
            NOTICE,
        )
    ]
    assert letter_date(blank(), pages, today=date(2026, 11, 20)) == LETTER_DAY


def test_a_bodys_as_of_date_is_no_date_of_the_letter_s() -> None:
    pages = [
        page(
            "Stadt Beispielhausen · Kasse · Rathausplatz 1 · 12345 Beispielhausen",
            "Frau Mara Probe",
            "Probeweg 2",
            "12345 Beispielhausen",
            "",
            "Datum: 06.11.2026",
            "",
            "Festsetzung von Säumniszuschlägen",
            "Sehr geehrte Frau Probe,",
            "mit diesem Bescheid setzen wir Säumniszuschläge von 12,00 EUR fest.",
            f"Forderungsaufstellung, Stand: {day}",
            "Rechtsbehelfsbelehrung",
            NOTICE,
        )
        for day in ("15.10.2026",)
    ]
    assert letter_date(blank(), pages, today=date(2026, 11, 20)) == LETTER_DAY
    assert letter_date(blank(document_date="2026-11-06"), pages, today=date(2026, 11, 20)) == LETTER_DAY


def test_a_received_stamp_on_the_first_line_never_starts_a_letter_dated_at_its_foot() -> None:
    pages = [
        page(
            "20.11.2026",
            "EINGANG",
            "Stadt Beispielhausen · Ordnungsamt · Rathausplatz 1 · 12345 Beispielhausen",
            "Frau Mara Probe",
            "Probeweg 2",
            "12345 Beispielhausen",
            "",
            "Gebührenbescheid",
            "Sehr geehrte Frau Probe,",
            "mit diesem Bescheid setzen wir eine Gebühr von 85,00 EUR fest.",
            "Rechtsbehelfsbelehrung",
            NOTICE,
            "Mit freundlichen Grüßen",
            "Beispielhausen, den 06.11.2026",
            "Der Bürgermeister",
        )
    ]
    start = letter_date(blank(), pages, today=date(2026, 11, 25))
    assert start is None or start <= LETTER_DAY


@pytest.mark.parametrize(
    "notice",
    [
        "Hiergegen kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
        "Gegen den Bescheid vom 27.10.2026 kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
    ],
)
def test_the_envelope_never_starts_another_decision_s_notice(notice: str) -> None:
    pages = [
        page(
            "Stadt Beispielhausen · Kasse · Rathausplatz 1 · 12345 Beispielhausen",
            "Mit Postzustellungsurkunde",
            "Frau Mara Probe",
            "Probeweg 2",
            "12345 Beispielhausen",
            "",
            "Datum: 06.11.2026",
            "",
            "Zahlungserinnerung",
            "Sehr geehrte Frau Probe,",
            "mit Gebührenbescheid vom 27.10.2026 wurde eine Gebühr von 85,00 EUR festgesetzt, die noch offen ist.",
            "Rechtsbehelfsbelehrung",
            notice,
        )
    ]
    assert not formally_served(pages)
    [(_verified, result)] = computed(blank(), pages, "2026-11-09")
    # the 27.10 decision, notified on the 30th at the earliest: 30 Nov at the latest
    assert result.due_date is not None and result.due_date <= "2026-11-30"


def test_a_served_decision_naming_its_own_noun_stays_served() -> None:
    pages = [
        page(
            "Stadt Beispielhausen · Ordnungsamt · Rathausplatz 1 · 12345 Beispielhausen",
            "Mit Postzustellungsurkunde",
            "Frau Mara Probe",
            "Probeweg 2",
            "12345 Beispielhausen",
            "",
            "Datum: 06.11.2026",
            "",
            "Gebührenbescheid",
            "Sehr geehrte Frau Probe,",
            "mit diesem Bescheid setzen wir eine Gebühr von 85,00 EUR fest.",
            "Rechtsbehelfsbelehrung",
            "Gegen den Gebührenbescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
        )
    ]
    assert formally_served(pages)
