"""The round-5 limits review, security lens (F1–F9, M1): conditional notices, instalments, a payment the reading
doubts, many send-by lines, a stamp on the first line, a letter not served so, a direct debit's box, the warning's
wording. Invented letters only."""

from __future__ import annotations

import time
from datetime import date, timedelta

import pytest

from ordnung.ingest.gaps import deadline_items, deadline_warning, formally_served, letter_date
from ordnung.ingest.plan import compute_item, verify_extraction
from ordnung.models import DocumentExtraction
from ordnung.rules import RuleContext


def page(*lines: str) -> tuple[int, str, list, str]:
    return (1, "\n".join(lines), [], "text")


def blank(**fields) -> DocumentExtraction:
    return DocumentExtraction.model_validate(
        {"kind": "other", "title": "L", "summary": "S", "explanation": "E", **fields}
    )


def check_due(pages, reading=None):
    reading = reading or blank()
    ver = verify_extraction("doc_x", reading, pages, check_reading=True)
    written = date.fromisoformat(reading.document_date) if reading.document_date else None
    ctx = RuleContext(today=date(2026, 11, 10), document_date=written)
    for v in ver.items:
        if v.slot_key == "check:reading":
            return compute_item(v, ctx, postal_buffer_days=3).due_date
    return "NOCHECK"


TOWN = [
    "Stadt Beispielhausen",
    "Ordnungsamt",
    "Rathausplatz 1",
    "12345 Beispielhausen",
    "",
    "Herrn Max Muster",
    "Musterweg 2",
    "12345 Beispielhausen",
    "",
]
BODY = [
    "Gebührenbescheid",
    "",
    "Sehr geehrter Herr Muster,",
    "hiermit setzen wir eine Gebühr von 50,00 EUR fest.",
]
PARTIAL = dict(
    document_date="2026-11-06",
    sender={"name": "Stadt Beispielhausen", "kind": "authority"},
    items=[{"kind": "payment", "title": "Pay", "quote": BODY[-1], "amount": 50.0, "date": {"type": "none"}}],
)


@pytest.mark.parametrize(
    ("notice", "due"),
    [
        (
            "Dieser Bußgeldbescheid wird rechtskräftig und vollstreckbar, wenn nicht innerhalb von zwei Wochen nach "
            "Zustellung Einspruch eingelegt worden ist.",
            "2026-11-20",
        ),
        (
            "Ist innerhalb eines Monats nach Bekanntgabe dieses Bescheides kein Widerspruch erhoben worden, wird er "
            "bestandskräftig.",
            "2026-12-09",
        ),
        (
            "Der Bescheid wird bestandskräftig, wenn nicht innerhalb eines Monats nach seiner Bekanntgabe Widerspruch "
            "erhoben wurde.",
            "2026-12-09",
        ),
    ],
)
def test_f1_a_conditional_notice_in_the_perfect_still_dates_the_check(notice: str, due: str) -> None:
    pages = [page(*TOWN, "Datum: 06.11.2026", *BODY, "Rechtsbehelfsbelehrung", notice)]
    assert check_due(pages) == due
    assert check_due(pages, blank(**PARTIAL)) == due


GRUND = [
    "Stadt Beispielhausen · Steueramt · Rathausplatz 1 · 12345 Beispielhausen",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "",
    "Datum: 01.10.2026",
    "Grundsteuerbescheid 2027",
    "Sehr geehrte Frau Probe,",
    "die Grundsteuer für 2027 wird auf 480,00 EUR festgesetzt.",
    "Die Grundsteuer wird wie folgt fällig:",
    "Fällig am 15.02.2027: 120,00 EUR",
    "Fällig am 15.05.2027: 120,00 EUR",
    "Fällig am 15.08.2027: 120,00 EUR",
    "Fällig am 15.11.2027: 120,00 EUR",
    "Bitte geben Sie bei jeder Zahlung das Kassenzeichen an.",
]


def test_f2_a_recurring_payment_s_later_instalments_are_the_reading_s() -> None:
    item = {
        "kind": "payment",
        "title": "Pay property tax",
        "quote": GRUND[10],
        "amount": 120.0,
        "date": {"type": "fixed", "date": "2027-02-15", "nature": "payment"},
        "recurrence": {"interval": 3, "unit": "months"},
    }
    reading = blank(
        document_date="2026-10-01", sender={"name": "Stadt Beispielhausen", "kind": "authority"}, items=[item]
    )
    assert deadline_items(reading, [page(*GRUND)], today=date(2026, 10, 3)) == []


INKASSO = [
    "Inkasso Schnell und Partner, Hauptstraße 9, 10115 Berlin",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Datum: 24.09.2026",
    "Letzte Mahnung",
    "Sehr geehrte Frau Probe,",
    "Ihr Konto weist einen offenen Betrag von 289,90 EUR auf.",
    "Zahlen Sie den Betrag bis zum 08.10.2026 auf das Konto IBAN LT12 1000 0111 0100 1000.",
    "Mit freundlichen Grüßen",
]
SENDER_INKASSO = {"name": "Inkasso Schnell und Partner", "kind": "company"}


@pytest.mark.parametrize(
    "warning",
    [
        "The payee account is a Lithuanian IBAN although the creditor is German.",
        "Check whether you really owe this money before paying.",
    ],
)
def test_f3_a_payment_the_reading_doubts_is_never_brought_back(warning: str) -> None:
    reading = blank(kind="dunning", document_date="2026-09-24", sender=SENDER_INKASSO, warnings=[warning])
    assert deadline_items(reading, [page(*INKASSO)], today=date(2026, 9, 25)) == []
    plain = blank(kind="dunning", document_date="2026-09-24", sender=SENDER_INKASSO)
    assert [i.date.date for i in deadline_items(plain, [page(*INKASSO)], today=date(2026, 9, 25))] == [
        "2026-10-08"
    ]


def test_f4_f5_many_send_by_lines_are_capped_and_fast() -> None:
    lines = [
        "Stadtwerke Beispielhausen GmbH · Werkstraße 1 · 12345 Beispielhausen",
        "Frau Mara Probe",
        "Probeweg 2",
        "12345 Beispielhausen",
        "Datum: 01.10.2026",
        "Rechnung",
        "Sehr geehrte Frau Probe,",
    ]
    lines += [
        f"Bitte reichen Sie Unterlage {n} bis zum {(date(2026, 10, 10) + timedelta(days=n)):%d.%m.%Y} ein."
        for n in range(60)
    ]
    reading = blank(
        kind="invoice",
        document_date="2026-10-01",
        sender={"name": "Stadtwerke Beispielhausen GmbH", "kind": "utility"},
    )
    started = time.monotonic()
    found = deadline_items(reading, [page(*lines)], today=date(2026, 10, 3))
    assert len(found) <= 3
    assert time.monotonic() - started < 5


@pytest.mark.parametrize("top", ["20.11.2026", "13.11.2026", "06.12.2026", "20.11.26"])
def test_f6_a_date_written_at_the_top_never_starts_the_check_after_the_closing_date(top: str) -> None:
    notice = [
        "Rechtsbehelfsbelehrung",
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
    ]
    pages = [page(top, *TOWN, *BODY, *notice, "Beispielhausen, den 06.11.2026", "Im Auftrag", "Meier")]
    start = letter_date(blank(), pages)
    assert start is None or start <= date(2026, 11, 6)


def test_f7_a_letter_that_is_not_served_so_is_not_marked() -> None:
    notice = "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden."
    line = "Dieser Bescheid wird Ihnen nicht mit Postzustellungsurkunde, sondern mit einfachem Brief bekannt gegeben."
    pages = [page(*TOWN, "Datum: 06.11.2026", *BODY, line, "Rechtsbehelfsbelehrung", notice)]
    assert not formally_served(pages)
    served = [
        page(
            *TOWN, "Datum: 06.11.2026", "Mit Postzustellungsurkunde", *BODY, "Rechtsbehelfsbelehrung", notice
        )
    ]
    assert formally_served(served)


def test_m1_a_direct_debit_s_due_box_is_no_payment_to_make() -> None:
    lines = [
        "Telefon Beispiel GmbH · Postfach 1 · 12345 Beispielhausen",
        "Frau Mara Probe",
        "Probeweg 2",
        "12345 Beispielhausen",
        "",
        "Rechnungsdatum: 01.10.2026",
        "Rechnung Nr. 4711",
        "Rechnungsbetrag: 39,99 EUR",
        "Fällig am: 15.10.2026",
        "",
        "Sehr geehrte Frau Probe,",
        "anbei erhalten Sie Ihre Rechnung für September 2026.",
        "Den Rechnungsbetrag buchen wir per SEPA-Lastschrift von Ihrem Konto ab.",
    ]
    debit = {
        "kind": "payment",
        "title": "Direct debit of the phone bill",
        "quote": lines[-1],
        "amount": 39.99,
        "date": {"type": "none"},
    }
    sender = {"name": "Telefon Beispiel GmbH", "kind": "telecom"}
    for items in ([], [debit]):
        reading = blank(kind="invoice", document_date="2026-10-01", sender=sender, items=items)
        assert deadline_items(reading, [page(*lines)], today=date(2026, 10, 3)) == []


def test_f9_one_dropped_date_is_one_to_do() -> None:
    assert "as a to-do" in deadline_warning(1)
    assert "as to-dos" in deadline_warning(2)
