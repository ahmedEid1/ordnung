"""The round-5 limits review (ADR 0015, "Review and known limits"): the false alarms and lost deadlines it found in the
check for incomplete readings, each repro a test — dropped dates that are options, period ends, instalments, debits,
paid or credited invoices, payouts and the full price beside a discount (FA-1 to FA-12, MISS-1); a decision whose
"Hiergegen" follows a hearing (FA-5) and a reminder's restated notice (MISS-2); conditional notices (FA-7, security
F1); opening hours, info blocks and a subject's own date under the date line (FA-8, RL-T1, R5D-6); town forms (R5D-1,
FA-6); a served Widerspruchsbescheid (R5D-4); a conflicted served letter keeping ``pzu`` (pzu V-1); the to-do's
wording, its Idea and the benchmark's counters (RL-T7, RL-T9). Invented letters only; no benchmark or prompt text."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from evals.metrics import DROPPED_DATE_NOTE

from fixtures_llm import Letter, Router
from ordnung import clock
from ordnung.ingest.gaps import DEADLINE_TITLE, deadline_items, formally_served, letter_date, remedy_notices
from ordnung.ingest.verify import DEADLINE_LEFT_OUT, REASON_TEXT
from ordnung.models import ExtractedItem
from test_api_support import api_for
from test_reading_gaps import blank, page
from test_reading_gaps_round2 import check_due
from test_reading_gaps_round5 import SERVED_LETTER, SERVED_MARKER


@pytest.fixture
def pinned_today() -> Iterator[None]:
    clock.set_today("2026-09-25")
    yield
    clock.set_today(None)


# --------------------------------------------------------------------------------------------------
# check:deadline: dates that are no deadline of the person's
# --------------------------------------------------------------------------------------------------

HEAD = (
    "Stadtwerke Beispielhausen GmbH · Werkstraße 1 · 12345 Beispielhausen",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Datum: 01.10.2026",
    "Rechnung",
    "Sehr geehrte Frau Probe,",
)
SENDER = {
    "sender": {"name": "Stadtwerke Beispielhausen GmbH", "kind": "utility"},
    "document_date": "2026-10-01",
}
#: A first sentence of the body: a label line of the header and a later sentence are no one clause.
FIRST = "anbei erhalten Sie Ihre Rechnung für September."


def dropped(*lines: str, items: tuple[ExtractedItem, ...] = (), warnings: tuple[str, ...] = ()) -> list[str]:
    reading = blank(**SENDER, items=list(items), warnings=list(warnings))
    return [
        item.date.date or ""
        for item in deadline_items(reading, [page(*HEAD, *lines)], today=date(2026, 10, 3))
    ]


def payment_item(quote: str, day: str | None, **extra: Any) -> ExtractedItem:
    spec = (
        {"type": "fixed", "date": day, "nature": "payment"} if day else {"type": "none", "nature": "payment"}
    )
    return ExtractedItem.model_validate(
        {"kind": "payment", "title": "Pay", "quote": quote, "amount": 85.0, "date": spec, **extra}
    )


@pytest.mark.parametrize(
    "lines",
    [
        ("Sie möchten Ihren Vertrag nicht verlängern? Dann senden Sie uns Ihre Kündigung bis zum 30.11.2026 zu.",),
        ("Möchten Sie Ihren Tarif wechseln? Dann teilen Sie uns dies bis zum 30.11.2026 mit.",),
        ("Sie möchten Ihren Tarif wechseln? Senden Sie das Formular bis zum 30.11.2026 zurück.",),
        ("Bei Interesse senden Sie uns das Formular bis zum 30.11.2026 zurück.",),
        ("Um am Bonusprogramm teilzunehmen, reichen Sie den Nachweis bis zum 30.11.2026 ein.",),
        ("Um das Angebot anzunehmen, senden Sie die Bestätigung bis zum 30.11.2026 zurück.",),
        ("Zur Auftragserteilung senden Sie uns das Formular bis zum 30.11.2026 zurück.",),
        ("Sie können Ihre Einwilligung jederzeit widerrufen; senden Sie dazu das Formular bis zum 30.11.2026 zurück.",),
        ("Zahlen Sie bis zum 15.10.2026 und sichern Sie sich 5 % Treuebonus.",),
    ],
    ids=["contract-option", "tariff-question", "tariff-statement", "interest", "bonus", "offer", "order", "revoke",
         "loyalty-bonus"],
)  # fmt: skip
def test_an_option_the_person_may_take_is_no_dropped_date(lines: tuple[str, ...]) -> None:
    """FA-3: a request for an option ("… möchten …? Dann senden Sie …") files nothing — a correct reading left it
    out (a Kündigung the person never asked to send)."""
    assert dropped(*lines) == []


@pytest.mark.parametrize(
    ("lines", "due"),
    [
        (("Um über Ihren Antrag entscheiden zu können, reichen Sie die Nachweise bis zum 30.10.2026 ein.",), "2026-10-30"),
        (("Um weitere Kosten zu vermeiden, überweisen Sie den Betrag bis zum 15.10.2026.",), "2026-10-15"),
        (("Bitte überweisen Sie den Betrag bis zum 15.10.2026, andernfalls leiten wir das Mahnverfahren ein.",), "2026-10-15"),
        (("Die Prämie ist am 15.10.2026 fällig.",), "2026-10-15"),
        (("Bitte zahlen Sie die Prämie bis zum 15.10.2026.",), "2026-10-15"),
        (("Wir möchten Sie bitten, den Betrag bis zum 15.10.2026 zu überweisen.",), "2026-10-15"),
        (("Gemäß unserem Angebot überweisen Sie den Betrag bis zum 15.10.2026.",), "2026-10-15"),
        (("Zahlbar bis 15.10.2026, ansonsten fallen Mahngebühren an.",), "2026-10-15"),
        (("Die Gebühr beträgt 85,00 EUR.", "Dann überweisen Sie den Betrag bis zum 15.10.2026."), "2026-10-15"),
        (("Um Ihren Anspruch auf Kindergeld zu sichern, reichen Sie die Bescheinigung bis zum 30.10.2026 ein.",), "2026-10-30"),
        (("Was müssen Sie tun?", "Bitte überweisen Sie den Betrag bis zum 15.10.2026."), "2026-10-15"),
        (("Haben Sie Fragen?", "Bitte überweisen Sie den Betrag bis zum 15.10.2026."), "2026-10-15"),
    ],
    ids=["reason-to-decide", "reason-costs", "otherwise-after", "premium-due", "premium-pay", "we-ask", "per-offer",
         "else-after", "then", "reason-claim", "w-question", "questions"],
)  # fmt: skip
def test_a_request_with_a_reason_or_after_a_heading_still_fires(lines: tuple[str, ...], due: str) -> None:
    """FA-3's counter-probes X1–X10: real requests keep their to-do."""
    assert dropped(*lines) == [due]


@pytest.mark.parametrize(
    "line",
    [
        "Bitte überweisen Sie den Beitrag für den Zeitraum bis zum 31.12.2026 bis spätestens 15.10.2026.",
        "Bitte überweisen Sie den Beitrag für die Zeit bis zum 31.12.2026 innerhalb von 14 Tagen.",
        "Bitte zahlen Sie den Elternbeitrag für das Kita-Jahr bis zum 31.07.2027 jeweils zum Ersten.",
        "Bitte reichen Sie die Nachweise für die Zeit bis zum 31.12.2026 ein.",
        "Bitte überweisen Sie den Beitrag für den Zeitraum vom 01.10.2026 bis zum 31.12.2026.",
    ],
)
def test_a_period_s_end_is_never_a_dropped_date(line: str) -> None:
    """FA-4: "für den Zeitraum bis zum 31.12." is what the payment is for — never a payment due 77 days after the
    letter's own 15.10 (code's dates are never later than the letter says)."""
    assert dropped(line) == []


@pytest.mark.parametrize(
    "noun",
    [
        "den Jahresbeitrag",
        "den Monatsbeitrag",
        "die Zeitungsgebühr",
        "die Nachzahlung aus der Jahresabrechnung",
    ],
)
def test_a_period_s_word_inside_a_compound_is_still_a_payment(noun: str) -> None:
    """FA-4's counter-probes: the period's noun counts only as a whole word."""
    assert dropped(f"Bitte überweisen Sie {noun} bis zum 15.10.2026.") == ["2026-10-15"]


SKONTO = "Bei Zahlung bis 10.10.2026 gewähren wir 2 % Skonto."


def test_the_full_price_beside_a_payment_dated_by_its_discount_is_the_same_one() -> None:
    """FA-9: the reading dated the payment by its Skonto day; "Zahlbar bis 31.10.2026 ohne Abzug" is the same
    payment — but a reading without a payment still gets it, and another payment beside it still fires."""
    discounted = payment_item(SKONTO, "2026-10-10")
    assert dropped("Zahlbar bis 31.10.2026 ohne Abzug.", SKONTO, items=(discounted,)) == []
    assert dropped("Zahlbar bis 31.10.2026 ohne Abzug.") == ["2026-10-31"]
    deposit = "Bitte überweisen Sie die Kaution von 300,00 EUR bis zum 20.10.2026."
    assert dropped("Zahlbar bis 31.10.2026 ohne Abzug.", SKONTO, deposit, items=(discounted,)) == [
        "2026-10-20"
    ]


@pytest.mark.parametrize(
    ("lines", "due"),
    [
        (
            (
                "Fällig am: 01.11.2026",
                FIRST,
                "Den Beitrag buchen wir zum Fälligkeitstermin von Ihrem Konto ab.",
            ),
            [],
        ),
        (("Der Betrag ist am 01.11.2026 fällig.", "Wir buchen den Betrag von Ihrem Konto ab."), []),
        (
            ("Zahlbar bis 01.11.2026", FIRST, "Zahlung per Lastschrift ist leider nicht möglich."),
            ["2026-11-01"],
        ),
        (
            ("Zahlbar bis 01.11.2026", FIRST, "Gerne können Sie uns ein SEPA-Lastschriftmandat erteilen."),
            ["2026-11-01"],
        ),
    ],
    ids=["debited-box", "debited-due", "debit-impossible", "mandate-offered"],
)
def test_a_debit_done_waves_off_a_label_date_one_offered_or_failed_does_not(
    lines: tuple[str, ...], due: list[str]
) -> None:
    """FA-10 / RL-T5: the debit's own day is no transfer to make; a debit that failed or is only offered is."""
    assert dropped(*lines) == due


@pytest.mark.parametrize(
    "lines",
    [
        ("Fälligkeitsdatum: 15.10.2026", FIRST, "Der Rechnungsbetrag wurde bereits per PayPal beglichen."),
        ("Zahlungsziel: 15.10.2026", FIRST, "Betrag dankend erhalten."),
        ("Gutschrift Nr. 4711", "Fällig am: 15.10.2026", FIRST),
        ("Fällig am: 15.10.2026", FIRST, "Status: bezahlt"),
        ("Fällig am: 15.10.2026", FIRST, "Der Erstattungsbetrag wird auf Ihr Konto überwiesen."),
        ("Zahlungstermin: 30.10.2026", FIRST, "Die Auszahlung erfolgt auf das bekannte Konto."),
    ],
    ids=["paid-paypal", "received", "credit-note", "status-paid", "refund", "payout"],
)
def test_a_paid_invoice_a_credit_note_or_a_payout_files_no_payment(lines: tuple[str, ...]) -> None:
    """MISS-1 and the refunds of the tests lens (M1): a "Fällig am:" box on a letter that is settled or pays out is
    never "check before you pay"."""
    assert dropped(*lines) == []


@pytest.mark.parametrize(
    "lines",
    [
        ("Ihre Vorauszahlungen haben Sie bereits gezahlt.", "Die Nachzahlung von 120,00 EUR ist am 15.10.2026 fällig."),
        ("Ein Teilbetrag von 50,00 EUR wurde bereits bezahlt.", "Der Restbetrag ist bis zum 15.10.2026 zu zahlen."),
        ("Fällig am: 15.10.2026", FIRST, "Sollten Sie den Betrag bereits bezahlt haben, ist dieses Schreiben gegenstandslos."),
    ],
    ids=["advance-paid", "part-paid", "conditional"],
)  # fmt: skip
def test_a_part_paid_or_a_payment_only_maybe_made_still_fires(lines: tuple[str, ...]) -> None:
    assert dropped(*lines) == ["2026-10-15"]


QUARTERLY = {"interval": 3, "unit": "months"}
ROWS = (
    "Die Grundsteuer wird wie folgt fällig:",
    "Fällig am 15.02.2027: 120,00 EUR",
    "Fällig am 15.05.2027: 120,00 EUR",
    "Fällig am 15.08.2027: 120,00 EUR",
    "Fällig am 15.11.2027: 120,00 EUR",
)


def test_the_rows_of_an_undated_recurring_payment_on_its_day_are_its_own() -> None:
    """FA-1's no-first-date case: a quarterly payment read without a date but with its day (the 15th) covers the
    letter's rows on that day once there are two or more; without a day it covers nothing."""
    every_15th = payment_item("Vierteljährlich zum 15.", None, recurrence={**QUARTERLY, "day_of_month": 15})
    assert dropped(*ROWS, items=(every_15th,)) == []
    no_day = payment_item("Die Grundsteuer wird vierteljährlich fällig.", None, recurrence=QUARTERLY)
    assert dropped(*ROWS, items=(no_day,)) == [
        "2027-02-15"
    ]  # the later rows: rivals of the first, the earliest kept


def test_a_first_date_an_undated_recurring_payment_left_out_still_fires() -> None:
    monthly = payment_item(
        "Abschlag monatlich zum 15.", None, recurrence={"interval": 1, "unit": "months", "day_of_month": 15}
    )
    assert dropped("Der Abschlag ist erstmals am 15.11.2026 fällig.", items=(monthly,)) == ["2026-11-15"]


def test_a_back_payment_before_the_first_advance_is_its_own() -> None:
    """RL-T4's counter-probe: a Nachzahlung on the advance's day of the month but before its first date."""
    advance = payment_item(
        "Ihr Abschlag beträgt 85,00 EUR monatlich.",
        "2026-11-15",
        recurrence={"interval": 1, "unit": "months"},
    )
    nachzahlung = "Die Nachzahlung von 245,00 EUR ist am 15.10.2026 fällig."
    assert dropped(nachzahlung, "Ihr Abschlag beträgt 85,00 EUR monatlich.", items=(advance,)) == [
        "2026-10-15"
    ]


def test_the_to_do_is_a_cross_check_and_quotes_its_own_line() -> None:
    """The to-do asks the person to check the letter, never demands; a date in the header box quotes that line alone,
    never the letterhead and the address above it (FA-12)."""
    lines = (*HEAD[:5], "Zahlungsziel: 15.10.2026", "Rechnung Nr. 4711")
    [item] = deadline_items(blank(**SENDER), [page(*lines)], today=date(2026, 10, 3))
    assert item.quote == "Zahlungsziel: 15.10.2026"
    assert item.title == DEADLINE_TITLE == "Check this date in the letter"
    assert item.action is not None and "check whether it applies to you before acting" in item.action
    assert "Thu 15 Oct 2026" in item.action and item.priority != "high"


# --------------------------------------------------------------------------------------------------
# The check's start and notices
# --------------------------------------------------------------------------------------------------

STREET = (
    "Stadt Beispielhausen · Rathausplatz 1 · 12345 Beispielhausen",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
)
FEE = (
    "",
    "Gebührenbescheid",
    "Sehr geehrte Frau Probe,",
    "wir setzen die Gebühr auf 85,00 EUR fest.",
    "Rechtsbehelfsbelehrung",
    "Gegen diesen Bescheid können Sie innerhalb eines Monats nach Bekanntgabe Widerspruch einlegen.",
)
OWN = date(2026, 11, 6)


@pytest.mark.parametrize(
    ("sender", "place", "start"),
    [
        ("60275 Frankfurt am Main", "Frankfurt a. M.", OWN),
        ("60326 Frankfurt", "Frankfurt am Main", OWN),
        ("80331 München", "Muenchen", OWN),
        ("80331 Muenchen", "München", OWN),
        ("06108 Halle (Saale)", "Halle/Saale", OWN),
        ("61348 Bad Homburg vor der Höhe", "Bad Homburg v. d. H.", OWN),
        ("66386 St. Ingbert", "St. Ingbert", OWN),
        ("60275 Frankfurt am Main", "Frankfurt Hauptwache", None),
        ("60326 Frankfurt", "Frankfurt Hauptwache", None),
    ],
)
def test_a_town_s_spelling_district_or_river_is_its_own_another_word_is_not(
    sender: str, place: str, start: date | None
) -> None:
    """R5D-1 / FA-6 and M4: short forms, rivers, umlauts spelled out are the page's town; "Frankfurt Hauptwache" (a
    place in it, planted with the letter's date unread) never is."""
    pages = [
        page(
            f"Stadt Musterort · Ordnungsamt · Hauptstraße 1 · {sender}",
            "Frau Mara Probe",
            "Probeweg 2",
            "63065 Offenbach am Main",
            "",
            f"{place}, 06.11.2026",
            *FEE,
        )
    ]
    assert letter_date(blank(), pages, today=date(2026, 11, 20)) == start


@pytest.mark.parametrize(
    ("below", "start"),
    [
        ("Sprechzeiten: Mo–Fr 08:00–12:00 Uhr", OWN),
        ("Öffnungszeiten Mo. - Fr. 8.00 - 12.00 Uhr", OWN),
        ("Telefon 0123 4567-0 (Mo–Fr 8–12 Uhr)", OWN),
        ("09:00 – 10:00 Uhr", None),
        ("10:00-11:30 Uhr, Raum 2.14", None),
        ("Sprechzeit im Zimmer 2.14 um 10:00 Uhr", None),
    ],
)
def test_opening_hours_under_the_date_line_are_no_appointment_s_time(below: str, start: date | None) -> None:
    """FA-8: hours that say so or run Mo–Fr leave the date line the letter's; a time range alone, or one with a room,
    is an appointment's (no start while the letter's date is unread)."""
    assert letter_date(blank(), [page(*STREET, "06.11.2026", below, *FEE)], today=date(2026, 11, 20)) == start


def test_a_subject_naming_its_own_date_and_time_leaves_the_date_line_the_letter_s() -> None:
    """R5D-6: "Meldeaufforderung zum 05.10.2026 um 9:00 Uhr" under the date line is that date's time."""
    lines = (*STREET, "21.09.2026", "Meldeaufforderung zum 05.10.2026 um 9:00 Uhr", *FEE)
    assert letter_date(blank(), [page(*lines)], today=date(2026, 9, 25)) == date(2026, 9, 21)


@pytest.mark.parametrize(
    ("above", "start"),
    [
        ("Terminvergabe", OWN),
        ("Einladungsmanagement", OWN),
        ("Terminservice", OWN),
        ("Terminbestätigung", None),
    ],
)
def test_a_department_s_name_above_datum_is_no_appointment_heading(above: str, start: date | None) -> None:
    """R5D-6 and RL-T1: "Terminvergabe" over "Datum:" is the sender's department; "Terminbestätigung" over a date and a
    room is an appointment's block (with the letter's own date unread: no start)."""
    day = "06.11.2026" if start else "20.11.2026"
    lines = (*STREET, "", above, f"Datum: {day}", "Ort: Raum 2.14", *FEE)
    assert letter_date(blank(), [page(*lines)], today=date(2026, 12, 20)) == start


DECIDED = blank(document_date="2026-10-01", sender={"name": "Stadt Beispielhausen", "kind": "authority"})


def _rejection(first: str, decision: str) -> list[tuple[int, str, list[Any], str]]:
    return [
        page(
            *STREET,
            "",
            "Datum: 01.10.2026",
            "",
            decision,
            "Sehr geehrte Frau Probe,",
            first,
            "Rechtsbehelfsbelehrung",
            "Hiergegen kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
        )
    ]


def test_a_hearing_before_a_rejection_never_undates_its_hiergegen() -> None:
    """FA-5: "Mit Schreiben vom 15.08. haben wir Sie angehört" is the hearing before this decision, which doesn't call
    itself one — dated from the letter as on main; an information letter naming an earlier rejection stays undated
    (its "Hiergegen" may be that one's)."""
    heard = _rejection(
        "Mit Schreiben vom 15.08.2026 haben wir Sie zu der beabsichtigten Ablehnung angehört. Ihr Antrag wird abgelehnt.",
        "Ablehnung Ihres Antrags auf Wohngeld",
    )
    assert check_due(heard, DECIDED) == "2026-11-04"
    told = _rejection("Mit Schreiben vom 01.08.2026 haben wir Ihren Antrag abgelehnt.", "Information")
    assert check_due(told, DECIDED) is None


def test_a_reminder_s_hiergegen_restating_the_decision_s_notice_is_undated() -> None:
    """MISS-2: a Zahlungserinnerung of 24.09 whose "Hiergegen" restates the notice of the decision of 03.09 was dated
    from the reminder, 21 days late (on main too): now undated."""
    pages = [
        page(
            *STREET,
            "",
            "Datum: 24.09.2026",
            "",
            "Zahlungserinnerung",
            "Sehr geehrte Frau Probe,",
            "am 03.09.2026 haben wir eine Gebühr von 85,00 EUR festgesetzt, die noch offen ist.",
            "Rechtsbehelfsbelehrung",
            "Hiergegen kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
        )
    ]
    assert check_due(pages) is None


@pytest.mark.parametrize(
    "sentence",
    [
        "Die Frist für den Widerspruch beträgt einen Monat nach Bekanntgabe; sie ist gewahrt, wenn der Widerspruch "
        "rechtzeitig bei der Behörde eingelegt wurde.",
        "Die Klage muss innerhalb eines Monats nach Zustellung erhoben werden; die Frist ist nur gewahrt, wenn die Klage "
        "vor ihrem Ablauf eingereicht wurde.",
    ],
)
def test_a_notice_with_a_condition_in_the_past_stays_a_notice(sentence: str) -> None:
    """FA-7: "wurde" inside a condition reports nothing — only a decision on a remedy reports one lodged."""
    pages = [page(*STREET, "", "Datum: 06.11.2026", *FEE[:4], "Rechtsbehelfsbelehrung", sentence)]
    assert len(remedy_notices(pages)) == 1


def _served_decision(
    notice: str, heading: str = "Widerspruchsbescheid"
) -> list[tuple[int, str, list[Any], str]]:
    return [
        page(
            "Landratsamt Beispielkreis · Rathausplatz 1 · 12345 Beispielhausen",
            "Mit Postzustellungsurkunde",
            "Frau Mara Probe",
            "Probeweg 2",
            "12345 Beispielhausen",
            "",
            "Datum: 06.11.2026",
            "",
            heading,
            "Sehr geehrte Frau Probe,",
            "Ihr Widerspruch vom 10.07.2026 wird zurückgewiesen.",
            "Rechtsbehelfsbelehrung",
            notice,
        )
    ]


@pytest.mark.parametrize(
    "notice",
    [
        "Gegen den Bescheid vom 03.06.2026 in Gestalt dieses Widerspruchsbescheides kann innerhalb eines Monats nach "
        "Zustellung Klage erhoben werden.",
        "Gegen den Bescheid vom 03.06.2026 und diesen Widerspruchsbescheid kann innerhalb eines Monats nach Zustellung "
        "Klage erhoben werden.",
    ],
)
def test_a_served_widerspruchsbescheid_naming_the_first_decision_stays_served(notice: str) -> None:
    """R5D-4's narrowed rule: a notice naming an earlier decision turns the envelope off only when it names neither
    this letter nor a decision on a remedy — a Widerspruchsbescheid's period runs from its own service (§ 74 VwGO)."""
    assert formally_served(_served_decision(notice))


# --------------------------------------------------------------------------------------------------
# A served letter whose reading conflicts with its notice keeps asking for the envelope (pzu V-1)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("months", [1, 2])
async def test_a_conflicted_served_letter_still_cites_the_envelope(
    data_dir: Path, pinned_today: None, months: int
) -> None:
    """V-1: when settling keeps the letter's own notice (the reading says two months, the notice one), the receipt
    still cites ``pzu`` — so the app asks for the date on the yellow envelope, never "When did it arrive?" with Today."""
    payload = copy.deepcopy(SERVED_LETTER.payload)
    payload["items"][0]["date"]["amount"] = months
    letter = Letter(marker=SERVED_MARKER, pages=SERVED_LETTER.pages, payload=payload)
    async with api_for(data_dir, router=Router(letters=(letter,))) as api:
        body = await api.upload((f"{SERVED_MARKER}.pdf", letter.pdf()))
        await api.read_all()
        doc_id = str(body["documents"][0]["id"])
        [item] = (await api.client.get(f"/api/documents/{doc_id}")).json()["items"]
        assert "pzu" in item["computation"]["rule_ids"]


# --------------------------------------------------------------------------------------------------
# The Idea and the benchmark's counters
# --------------------------------------------------------------------------------------------------


def test_the_benchmark_tells_a_dropped_date_from_the_objection_check() -> None:
    """RL-T9: the counters tell the two code-made to-dos apart by the receipt's note."""
    assert REASON_TEXT[DEADLINE_LEFT_OUT].startswith(DROPPED_DATE_NOTE)


async def test_a_dropped_date_s_idea_never_offers_pay(data_dir: Path, pinned_today: None) -> None:
    """RL-T7 / pzu-5: the please-check Idea says the reading left the date out (it was found), and code's payment
    to-do never gets a "Pay" button."""
    from ordnung.secretary.triggers import Ledger, item_action, please_check
    from test_reading_gaps_round5 import DROPPED_LETTER, DROPPED_MARKER

    async with api_for(data_dir, router=Router(letters=(DROPPED_LETTER,))) as api:
        body = await api.upload((f"{DROPPED_MARKER}.pdf", DROPPED_LETTER.pdf()))
        await api.read_all()
        doc_id = str(body["documents"][0]["id"])
        ledger = Ledger(api.ctx.store, clock.today())
        [item] = api.ctx.store.list_items(doc_id=doc_id)
        assert item_action(ledger, item).label == "Check the letter"
        [idea] = [idea for idea in please_check(ledger) if idea.refs[0].id == doc_id]
        assert "left out a date the letter sets for you" in idea.body
        assert "couldn't find" not in idea.body


@pytest.mark.parametrize(("stamp", "start"), [("20.11.2026", OWN), ("13.11.2026", OWN), ("06.12.2026", None)])
def test_a_stamp_on_the_date_line_is_lowered_to_the_letter_s_own_date_at_its_foot(
    stamp: str, start: date | None
) -> None:
    """A received stamp alone in the date line's place under the address, the letter dated only above its signature:
    the foot's date lowers it (more than 14 days apart, no start) — as a date on the first line (security F6)."""
    lines = (*STREET, stamp, *FEE, "Mit freundlichen Grüßen", "Beispielhausen, den 06.11.2026")
    assert letter_date(blank(), [page(*lines)], today=date(2026, 12, 20)) == start
