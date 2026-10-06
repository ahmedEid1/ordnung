"""The final verification of the round-5 limits fix pass: residual false alarms and lost dates it left — a paid invoice
or a payout in other common words, a negated "erhalten"/"beglichen", a decision that decides itself while naming an
open amount, a received stamp on page 1 of a letter dated at the foot of a later page. Invented letters only."""

from __future__ import annotations

from datetime import date

import pytest

from ordnung.ingest.gaps import deadline_items, letter_date
from ordnung.models import DocumentExtraction
from test_reading_gaps import blank, page
from test_reading_gaps_round2 import check_due

SHOP = (
    "Versandhaus Beispiel GmbH · Lagerstraße 3 · 33330 Gütersloh",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Rechnungsdatum: 01.10.2026",
    "Rechnung Nr. R-4711",
    "Sehr geehrte Frau Probe,",
    "vielen Dank für Ihre Bestellung.",
    "Rechnungsbetrag: 39,99 EUR",
)
SHOP_READING = blank(
    sender={"name": "Versandhaus Beispiel GmbH", "kind": "retailer"}, document_date="2026-10-01"
)


def dropped(head: tuple[str, ...], *lines: str, reading: DocumentExtraction = SHOP_READING) -> list[str]:
    return [
        item.date.date or ""
        for item in deadline_items(reading, [page(*head, *lines)], today=date(2026, 10, 3))
    ]


@pytest.mark.parametrize(
    "paid",
    [
        "Zahlungsstatus: Bezahlt",
        "Bezahlt am 01.10.2026 per PayPal.",
        "Bezahlt mit PayPal",
        "Zahlung erhalten am 01.10.2026",
        "Zahlungsart: PayPal (bezahlt)",
        "Wir haben Ihre Zahlung erhalten.",
    ],
)
def test_a_paid_invoice_in_other_words_files_no_payment(paid: str) -> None:
    assert dropped(SHOP, "Fälligkeitsdatum: 15.10.2026", paid) == []


@pytest.mark.parametrize(
    "unpaid",
    [
        "Leider haben wir den Rechnungsbetrag bisher nicht erhalten.",
        "Die Rechnung ist noch nicht beglichen.",
        "Bis heute ist keine Zahlung eingegangen.",
    ],
)
def test_a_reminder_saying_the_amount_is_not_paid_still_files_its_due_date(unpaid: str) -> None:
    assert dropped(SHOP, unpaid, "Zahlbar bis: 15.10.2026") == ["2026-10-15"]


BENEFIT = (
    "Stadt Beispielhausen · Rathausplatz 1 · 12345 Beispielhausen",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Datum: 01.10.2026",
    "Bescheid",
    "Sehr geehrte Frau Probe,",
    "wir bewilligen Ihnen monatlich 212,00 EUR.",
)
BENEFIT_READING = blank(
    sender={"name": "Stadt Beispielhausen", "kind": "authority"}, document_date="2026-10-01"
)


@pytest.mark.parametrize(
    "payout",
    [
        "Das Wohngeld wird monatlich im Voraus auf Ihr Konto überwiesen.",
        "Wir überweisen den Betrag auf Ihr Konto.",
        "Die Zahlung erfolgt auf Ihr Konto.",
        "Der Betrag wird Ihrem Konto gutgeschrieben.",
        "Wir zahlen den Betrag auf Ihr Konto.",
    ],
)
def test_a_payout_in_other_words_files_no_payment(payout: str) -> None:
    assert dropped(BENEFIT, payout, "Zahlungstermin: 30.10.2026", reading=BENEFIT_READING) == []


STREET = (
    "Stadt Beispielhausen · Rathausplatz 1 · 12345 Beispielhausen",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "",
    "Datum: 01.10.2026",
)
HIER = "Hiergegen kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden."
DECIDED = blank(document_date="2026-10-01", sender={"name": "Stadt Beispielhausen", "kind": "authority"})


@pytest.mark.parametrize(
    ("heading", "body"),
    [
        (
            "Ablehnung Ihres Antrags auf Stundung",
            "Ihren Antrag vom 01.09.2026 auf Stundung der noch offenen Gebühr von 85,00 EUR lehnen wir ab.",
        ),
        ("Ablehnung Ihres Antrags auf Erlass", "Ihr Antrag auf Erlass der offenen Forderung wird abgelehnt."),
        ("Mahnung", "Für diese Mahnung setzen wir eine Mahngebühr von 5,00 EUR fest."),
    ],
)
def test_a_letter_that_decides_itself_is_no_reminder_whatever_amount_it_names_open(
    heading: str, body: str
) -> None:
    """MISS-2's reminder rule undated these (main and eff43fa dated them from the letter, its own decision)."""
    pages = [page(*STREET, heading, "Sehr geehrte Frau Probe,", body, "Rechtsbehelfsbelehrung", HIER)]
    assert check_due(pages, DECIDED) is not None


def test_a_reminder_restating_its_decision_s_notice_stays_undated() -> None:
    body = "am 03.09.2026 haben wir eine Gebühr von 85,00 EUR festgesetzt, die noch offen ist."
    pages = [
        page(*STREET, "Zahlungserinnerung", "Sehr geehrte Frau Probe,", body, "Rechtsbehelfsbelehrung", HIER)
    ]
    assert check_due(pages, DECIDED) is None


def test_a_stamp_on_page_one_is_lowered_to_the_closing_date_of_a_later_page() -> None:
    """R5D-3 / F6 on a two-page letter: "12.10.2026" over "EINGANG" on page 1, the letter dated only on page 2."""
    first = page(
        "12.10.2026",
        "EINGANG",
        "Gemeinde Beispielhausen · Rathausplatz 1 · 12345 Beispielhausen",
        "Frau Mara Probe",
        "Probeweg 2",
        "12345 Beispielhausen",
        "",
        "Bescheid über Abwassergebühren 2026",
        "Sehr geehrte Frau Probe,",
        "wir setzen die Abwassergebühren auf 312,00 EUR fest.",
    )
    second = page(
        "Rechtsbehelfsbelehrung",
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
        "Beispielhausen, den 07.10.2026",
        number=2,
    )
    assert letter_date(blank(), [first, second], today=date(2026, 10, 13)) == date(2026, 10, 7)
