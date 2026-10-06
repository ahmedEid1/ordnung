"""The round-5 limits review, RL-T4 / RL-T5 / RL-T1: a recurring to-do's rows and a direct debit's due box file no
dropped date while a transfer the letter asks for still does; an info block's rule for visits is no appointment
heading. Invented letters only."""

from datetime import date

import pytest

from ordnung.ingest.gaps import deadline_items
from ordnung.models import ExtractedItem
from test_reading_gaps import blank, page

HEAD = (
    "Telefonica Probe GmbH · Postfach 1 · 12345 Beispielhausen",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Datum: 01.10.2026",
    "Sehr geehrte Frau Probe,",
)
READING = {"sender": {"name": "Telefonica Probe GmbH", "kind": "company"}, "document_date": "2026-10-01"}


@pytest.mark.parametrize(
    ("lines", "due"),
    [
        (
            [
                "Den Rechnungsbetrag buchen wir per SEPA-Lastschrift von Ihrem Konto ab.",
                "Rechnungsbetrag: 39,99 EUR",
                "Fällig am: 15.10.2026",
            ],
            [],
        ),
        (
            [
                "Den Rechnungsbetrag buchen wir per SEPA-Lastschrift von Ihrem Konto ab.",
                "Eine Überweisung ist nicht erforderlich.",
                "Fälligkeitsdatum: 15.10.2026",
            ],
            [],
        ),
        (["Mandatsreferenz: MR-12345", "Rechnungsbetrag: 39,99 EUR", "Fällig am: 15.10.2026"], []),
        (
            [
                "Leider konnten wir den Betrag nicht von Ihrem Konto abbuchen.",
                "Bitte überweisen Sie den offenen Betrag von 39,99 EUR bis zum 15.10.2026.",
            ],
            ["2026-10-15"],
        ),
        (
            [
                "Die Lastschrift war nicht möglich.",
                "Bitte überweisen Sie den offenen Betrag von 39,99 EUR bis zum 15.10.2026.",
            ],
            ["2026-10-15"],
        ),
        (
            [
                "Bitte überweisen Sie den Betrag von 39,99 EUR bis zum 15.10.2026.",
                "Tipp: Zahlen Sie künftig bequem per SEPA-Lastschrift.",
            ],
            ["2026-10-15"],
        ),
        (
            [
                "Die monatlichen Vorauszahlungen ziehen wir weiterhin per Lastschrift ein.",
                "Bitte überweisen Sie die Nachzahlung von 245,00 EUR bis zum 15.11.2026.",
            ],
            ["2026-11-15"],
        ),
        (
            [
                "Bitte zahlen Sie den Betrag bis zum 15.10.2026.",
                "Tipp: Mit einem SEPA-Lastschriftmandat buchen wir künftig automatisch ab.",
            ],
            ["2026-10-15"],
        ),
    ],
    ids=[
        "sepa-box",
        "sepa-no-transfer",
        "mandate",
        "debit-failed",
        "debit-impossible",
        "sepa-tip",
        "advance-debit-back-payment",
        "pay-verb-beside-debit",
    ],
)
def test_a_debit_letter_files_no_payment_box_but_a_transfer_it_asks_for_stays(
    lines: list[str], due: list[str]
) -> None:
    items = deadline_items(blank(**READING), [page(*HEAD, *lines)], today=date(2026, 10, 3))
    assert [item.date.date for item in items] == due


def _monthly(first: str) -> ExtractedItem:
    return ExtractedItem.model_validate(
        {
            "kind": "payment",
            "title": "Abschlag",
            "quote": "",
            "amount": 85.0,
            "date": {"type": "fixed", "date": first, "nature": "payment"},
            "recurrence": {"interval": 1, "unit": "months"},
        }
    )


def test_an_installment_row_of_a_recurring_to_do_is_no_dropped_date() -> None:
    rows = [
        "Ihre neuen Abschläge:",
        "Fällig am 15.11.2026   85,00 EUR",
        "Fällig am 15.12.2026   85,00 EUR",
        "Fällig am 15.01.2027   85,00 EUR",
    ]
    reading = blank(**READING, items=[_monthly("2026-11-15")])
    assert deadline_items(reading, [page(*HEAD, *rows)], today=date(2026, 10, 3)) == []


def test_a_back_payment_a_day_before_an_advance_s_due_day_is_still_its_own() -> None:
    lines = [
        "Bitte überweisen Sie die Nachzahlung von 245,00 EUR bis zum 31.01.2027.",
        "Ihre monatliche Vorauszahlung beträgt ab dem 01.01.2027 220,00 EUR.",
    ]
    reading = blank(**READING, items=[_monthly("2027-01-01")])
    items = deadline_items(reading, [page(*HEAD, *lines)], today=date(2026, 10, 3))
    assert [item.date.date for item in items] == ["2027-01-31"]


FEE = (
    "",
    "Gebührenbescheid",
    "Sehr geehrte Frau Probe,",
    "wir setzen die Gebühr auf 85,00 EUR fest.",
    "Rechtsbehelfsbelehrung",
    "Gegen diesen Bescheid können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
)
TOWN = (
    "Stadt Beispielhausen · Rathausplatz 1 · 12345 Beispielhausen",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "",
    "Sachbearbeitung: Herr Muster",
)


@pytest.mark.parametrize(
    ("line", "start"),
    [
        ("Termine nach Vereinbarung", date(2026, 11, 6)),
        ("Termine nur nach Vereinbarung", date(2026, 11, 6)),
        ("Terminvereinbarung unter 0123-4567", date(2026, 11, 6)),
        ("Termin online buchen", date(2026, 11, 6)),
        ("Vorsprache nur mit Termin", date(2026, 11, 6)),
        ("Vorsprachen nur nach Terminvereinbarung", date(2026, 11, 6)),
        ("Termin", None),
        ("Ihr Termin", None),
        ("Einladung zum Gespräch", None),
    ],
)
def test_an_info_block_s_rule_for_visits_is_no_appointment_heading(line: str, start: date | None) -> None:
    from ordnung.ingest.gaps import _own_start, letter_date

    pages = [page(*TOWN, line, "Datum: 06.11.2026", *FEE)]
    assert letter_date(blank(), pages) == start
    assert _own_start(pages) == start
