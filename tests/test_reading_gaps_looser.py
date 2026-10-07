"""The dropped-date check (``check:deadline``) in looser words and for dates written without their year (ADR 0015,
2026-10-07).

The corpus (``tests/data/deadline_looser_corpus.json``) was written from general knowledge of German and English
letters, never from the benchmark's: each positive is a sentence (or a request line and a label below it) that sets a
date the person must pay or send something by, in words the strict check did not read ("Ihre Zahlung wird bis …
erwartet", "Ihr Betrag muss bis … bei uns eingegangen sein", "Wir bitten Sie um Zahlung bis …", "Zahlungsfrist: …"
under "Bitte überweisen Sie …", "Your payment must be received by …", or a date without its year); each negative is
a sentence built to look like one but whose date is no deadline of the person's (a condition, the past, the sender's
or another's act, money coming to her, a debit, an appointment, a discount, a validity, an option, an offer or event,
a holiday, a period's end, a remedy, a statement's cut-off, an old line, a year the sentence leaves unknown). The
review of 2026-10-07 moved 118 positives to the negatives, each with its reason (``"moved"``: no second-person
marker, a label on a page that asks for nothing, a third party, a date without its year more than 92 days into the
next year), and pinned the two negatives the strict path files as on base 0ff51e3 (``"strict_as_base"``: documented
limits, never silenced there). Every sentence stands in a minimal letter whose reading has its sender and date but no
to-do: a positive files exactly one to-do of its kind on its date, a negative none. Invented letters only.
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ordnung.ingest.gaps import YEARLESS_REACH, YEARLESS_ROLL, deadline_items, yearless_date
from ordnung.ingest.verify import PageInput
from ordnung.models import DocumentExtraction, ExtractedItem
from test_reading_gaps import blank, page

CORPUS = json.loads(
    (Path(__file__).parent / "data" / "deadline_looser_corpus.json").read_text(encoding="utf-8")
)
POSITIVES: list[dict[str, Any]] = CORPUS["positives"]
NEGATIVES: list[dict[str, Any]] = CORPUS["negatives"]
#: Negatives the strict path files as on base 0ff51e3 (a third party's strict request): documented, never silenced.
STRICT_AS_BASE: list[dict[str, Any]] = CORPUS["strict_as_base"]
#: The day the corpus was written against: every positive's date is after it and after its letter's date.
TODAY = date(2026, 10, 7)


def letter(sentence: str, written: date | None, lang: str = "de") -> PageInput:
    """A minimal letter: a letterhead, the address, its date (when given), the salutation, the sentence, the close."""
    return page(
        "Beispiel Service GmbH · Musterstraße 1 · 12345 Beispielhausen",
        "Frau Mara Probe",
        "Probeweg 2",
        "12345 Beispielhausen",
        *([f"Datum: {written:%d.%m.%Y}"] if written is not None else []),
        "Sehr geehrte Frau Probe," if lang == "de" else "Dear Ms Probe,",
        sentence,
        "Mit freundlichen Grüßen" if lang == "de" else "Yours sincerely,",
    )


def reading(written: date | None, items: list[ExtractedItem] | None = None) -> DocumentExtraction:
    """A reading with the sender and the letter's date (when given) and no to-do, or ``items``."""
    fields: dict[str, Any] = {"sender": {"name": "Beispiel Service GmbH", "kind": "company"}}
    if written is not None:
        fields["document_date"] = written.isoformat()
    if items:
        fields["items"] = [item.model_dump() for item in items]
    return blank(**fields)


def filed(
    sentence: str,
    written: date | None,
    lang: str = "de",
    *,
    today: date = TODAY,
    items: list[ExtractedItem] | None = None,
) -> list[tuple[str | None, str]]:
    found = deadline_items(reading(written, items), [letter(sentence, written, lang)], today=today)
    return [(item.date.date, item.date.nature) for item in found]


def _id(entry: dict[str, Any]) -> str:
    return f"{entry.get('family') or entry.get('category')}-{entry['sentence'][:40]}"


def test_the_corpus_is_large_enough_and_every_move_has_its_reason() -> None:
    assert len(POSITIVES) >= 150 and len(NEGATIVES) >= 400
    assert {entry["kind"] for entry in POSITIVES} == {"payment", "declaration"}
    assert any(not entry["has_year"] for entry in POSITIVES) and any(
        not entry["has_year"] for entry in NEGATIVES
    )
    # a sentence moved by the review keeps its reason, never dropped silently
    moved = [entry for entry in NEGATIVES if "moved" in entry]
    assert len(moved) == 118 and all(entry["moved"] and entry["why"] for entry in moved)
    assert not any("moved" in entry for entry in POSITIVES)
    assert all(entry["moved"] and entry["files"] for entry in STRICT_AS_BASE)
    sentences = [entry["sentence"] for entry in [*POSITIVES, *NEGATIVES, *STRICT_AS_BASE]]
    assert len(sentences) == len(set(sentences))


@pytest.mark.parametrize("entry", POSITIVES, ids=[_id(entry) for entry in POSITIVES])
def test_a_looser_wording_files_one_to_do_of_its_kind_on_its_date(entry: dict[str, Any]) -> None:
    written = date.fromisoformat(entry["letter_date"])
    assert filed(entry["sentence"], written, entry["lang"]) == [(entry["date"], entry["kind"])]


@pytest.mark.parametrize("entry", NEGATIVES, ids=[_id(entry) for entry in NEGATIVES])
def test_a_date_that_is_no_deadline_of_the_person_s_files_nothing(entry: dict[str, Any]) -> None:
    written = date.fromisoformat(entry["letter_date"])
    assert filed(entry["sentence"], written, entry["lang"]) == []


@pytest.mark.parametrize("entry", STRICT_AS_BASE, ids=[_id(entry) for entry in STRICT_AS_BASE])
def test_the_strict_path_s_false_alarms_stay_as_on_base(entry: dict[str, Any]) -> None:
    written = date.fromisoformat(entry["letter_date"])
    assert filed(entry["sentence"], written, entry["lang"]) == [tuple(found) for found in entry["files"]]


# --------------------------------------------------------------------------------------------------
# Dates without their year
# --------------------------------------------------------------------------------------------------


def test_a_day_and_month_is_that_day_after_the_letter_s_date() -> None:
    assert yearless_date(23, 10, date(2026, 10, 5)) == date(2026, 10, 23)
    assert yearless_date(15, 1, date(2026, 12, 10)) == date(2027, 1, 15)  # December's letter, January's day
    assert yearless_date(31, 12, date(2026, 12, 30)) == date(2026, 12, 31)
    assert yearless_date(5, 10, date(2026, 10, 5)) is None  # the letter's own day: next year's is too far on


def test_a_day_and_month_is_read_within_half_a_year_this_year_or_a_quarter_into_the_next() -> None:
    assert (YEARLESS_REACH, YEARLESS_ROLL) == (182, 92)
    assert yearless_date(1, 7, date(2026, 1, 1)) == date(2026, 7, 1)  # 181 days on
    assert yearless_date(3, 7, date(2026, 1, 1)) is None  # 183 days on
    written = date(2026, 10, 5)
    assert yearless_date(5, 1, written) == date(2027, 1, 5)  # 92 days into the next year
    assert yearless_date(6, 1, written) is None  # 93 days: an old line, never next year's date
    assert (
        yearless_date(5, 4, written) is None
    )  # half a year on, but a day of April before the letter's: an old line
    assert yearless_date(30, 9, written) is None  # within half a year before the letter's date: past


def test_the_29th_of_february_is_read_only_in_a_leap_year_within_reach() -> None:
    assert yearless_date(29, 2, date(2026, 10, 1)) is None  # 2027 has none
    assert yearless_date(29, 2, date(2027, 12, 1)) == date(2028, 2, 29)  # 90 days on
    assert yearless_date(29, 2, date(2027, 10, 1)) is None  # 151 days on: too far into the next year


def test_a_date_without_its_year_rolls_over_into_january() -> None:
    written = date(2026, 12, 10)
    sentence = "Der Restbetrag ist bis 15.01. zu begleichen."
    assert filed(sentence, written, today=date(2026, 12, 11)) == [("2027-01-15", "payment")]
    assert filed(
        "Ihre Unterlagen müssen uns bis zum 8. Januar vorliegen.", written, today=date(2026, 12, 11)
    ) == [("2027-01-08", "declaration")]


@pytest.mark.parametrize(
    ("sentence", "expected"),
    [
        ("Ihre Zahlung wird bis zum 1. Dezember erwartet.", [("2026-12-01", "payment")]),
        ("Ihre Zahlung wird bis zum 1. April erwartet.", []),  # 178 days into the next year: an old line
        ("Ihre Zahlung wird bis zum 15. Mai erwartet.", []),
        ("Wir erwarten Ihre Unterlagen bis 30.09.", []),  # before the letter's date: past
    ],
)
def test_a_date_without_its_year_must_fall_soon_after_the_letter(
    sentence: str, expected: list[tuple[str, str]]
) -> None:
    assert filed(sentence, date(2026, 10, 5)) == expected


def test_a_date_without_its_year_on_a_letter_without_a_date_files_nothing() -> None:
    assert filed("Wir bitten Sie um Zahlung bis zum 23.10.", None) == []
    assert filed("Bitte überweisen Sie den Betrag.\nZahlungsfrist: 23. Oktober", None) == []
    # its year written, the same wording still files
    assert filed("Wir bitten Sie um Zahlung bis zum 23.10.2026.", None) == [("2026-10-23", "payment")]


@pytest.mark.parametrize(
    "sentence",
    [
        "Wir bitten Sie um Zahlung bis zum 23/10.",  # a slash date needs its year: day and month can't be told apart
        "Wir bitten Sie um Zahlung bis zum 23.10 auf unser Konto.",  # no full stop after the month: no date
        "Wir bitten Sie um Zahlung bis zum 03/05/2027.",  # its year written, but day and month ambiguous
    ],
)
def test_an_ambiguous_date_without_its_year_files_nothing(sentence: str) -> None:
    assert filed(sentence, date(2026, 10, 5)) == []


def test_the_reading_s_own_to_do_and_quote_cover_a_date_without_its_year() -> None:
    sentence = "Der Restbetrag ist bis 15.01. zu begleichen."
    written, today = date(2026, 12, 10), date(2026, 12, 11)
    quoting = ExtractedItem.model_validate(
        {
            "kind": "payment",
            "title": "Pay the rest",
            "date": {"type": "none", "nature": "payment"},
            "quote": sentence,
        }
    )
    assert filed(sentence, written, today=today, items=[quoting]) == []  # the reading quotes its sentence

    def due(on: str) -> ExtractedItem:
        return ExtractedItem.model_validate(
            {
                "kind": "payment",
                "title": "Pay",
                "date": {"type": "fixed", "date": on, "nature": "payment"},
                "quote": "Rechnung",
            }
        )

    assert (
        filed(sentence, written, today=today, items=[due("2027-01-13")]) == []
    )  # within 3 days of the reading's
    # a dated payment of the reading: a second payment date without its year is likelier its own (2026-10-07 review)
    assert filed(sentence, written, today=today, items=[due("2027-02-15")]) == []
    # a dated declaration of the reading covers no payment
    declaration = due("2027-02-15").model_copy(
        update={
            "kind": "deadline",
            "date": due("2027-02-15").date.model_copy(update={"nature": "declaration"}),
        }
    )
    assert filed(sentence, written, today=today, items=[declaration]) == [("2027-01-15", "payment")]


def test_a_month_s_name_without_the_year_ends_no_sentence() -> None:
    """ "30. Oktober" keeps its full stop: the sentence is not cut after "30"."""
    assert filed("Ihre Zahlung wird bis zum 30. Oktober erwartet.", date(2026, 10, 5)) == [
        ("2026-10-30", "payment")
    ]
    assert filed(
        "Bitte senden Sie uns die Unterlagen.\nFrist: 30.10. (Eingang der Unterlagen bei uns)",
        date(2026, 10, 5),
    ) == [("2026-10-30", "declaration")]


# --------------------------------------------------------------------------------------------------
# Beyond the corpus: the wordings in a letter's flow, and more distractors
# --------------------------------------------------------------------------------------------------

SPARKASSE = (
    "Sparkasse Beispielhausen · Markt 1 · 12345 Beispielhausen",
    "Frau Mara Probe",
    "Probeweg 2",
    "12345 Beispielhausen",
    "Datum: 05.10.2026",
    "Kundennummer: 4711",
    "Sehr geehrte Frau Probe,",
)
INVOICE_EN = (
    "Example Services Ltd · 1 High Street · London",
    "Ms Mara Probe",
    "Invoice No. 12345",
    "Customer No: 998",
    "Date: 05.10.2026",
    "Dear Ms Probe,",
)


def in_flow(head: tuple[str, ...], *lines: str) -> list[tuple[str | None, str]]:
    found = deadline_items(reading(date(2026, 10, 5)), [page(*head, *lines)], today=TODAY)
    return [(item.date.date, item.date.nature) for item in found]


PAYS = [("2026-10-23", "payment")]
SENDS = [("2026-10-23", "declaration")]


@pytest.mark.parametrize(
    ("head", "lines", "expected"),
    [
        (
            SPARKASSE,
            ("leider ist Ihre Zahlung noch nicht eingegangen.", "Wir bitten Sie um Zahlung des offenen Betrags bis",
             "zum 23.10.2026."),
            PAYS,
        ),
        # (no one named as the one to pay: the looser path stays silent, 2026-10-07 review)
        (SPARKASSE, ("Wir bitten um Zahlung des offenen Betrags bis zum 23.10.2026.",), []),
        (
            SPARKASSE,
            ("vielen Dank für Ihr Schreiben.",
             "Damit wir Ihren Antrag bearbeiten können, benötigen wir die Unterlagen bis zum 23.10.2026."),
            SENDS,
        ),
        (SPARKASSE, ("bitte beachten Sie, dass die Zahlung bis zum 23.10.2026 bei uns eingegangen sein muss.",), PAYS),
        (SPARKASSE, ("Bis zum 23.10.2026 erwarten wir Ihre Rückmeldung.",), SENDS),
        (SPARKASSE, ("Bitte gleichen Sie den offenen Betrag bis zum 23.10.2026 aus.",), PAYS),
        (SPARKASSE, ("Senden Sie uns die Unterlagen bis zum 23.10.2026.",), SENDS),
        (SPARKASSE, ("Ihre Unterlagen werden bis zum 23.10.2026 bei uns benötigt.",), SENDS),
        (SPARKASSE, ("Die Unterlagen werden bis zum 23.10.2026 benötigt.",), []),
        (INVOICE_EN, ("Your payment must be received by 23 October 2026.",), PAYS),
        (INVOICE_EN, ("Payment must be received by 23 October 2026.",), []),
        (INVOICE_EN, ("You are required to pay the balance by 23 October 2026.",), PAYS),
        (INVOICE_EN, ("Kindly pay the outstanding amount by 23 October 2026.",), PAYS),
        (SPARKASSE, ("Wir erwarten die Entscheidung des Gerichts bis zum 23.10.2026.",), []),
        (SPARKASSE, ("Wir erwarten, dass Ihre Bank den Betrag bis zum 23.10.2026 zurückbucht.",), []),
        (SPARKASSE, ("Gewinnspiel – Einsendeschluss: 23.10.2026",), []),
        (SPARKASSE, ("Die Lieferung muss bis zum 23.10.2026 erfolgen.",), []),
        (SPARKASSE, ("Ihre Versicherung muss die Unterlagen bis zum 23.10.2026 vorlegen.",), []),
        (SPARKASSE, ("Die Rückzahlung an Sie muss bis zum 23.10.2026 erfolgen.",), []),
        (
            SPARKASSE,
            ("Wir bitten um Ihr Verständnis, dass die Bearbeitung der Unterlagen bis zum 23.10.2026 dauert.",),
            [],
        ),
        (SPARKASSE, ("Anmeldeformulare müssen bis zum 23.10.2026 vorliegen.",), []),
        (SPARKASSE, ("Sie können die Unterlagen bis zum 23.10.2026 nachreichen.",), []),
        (SPARKASSE, ("Ihre Zahlung vom 28.09. ist eingegangen.", "Zahlungen bis 30.09. sind berücksichtigt."), []),
        (INVOICE_EN, ("We expect to complete the repair by 23 October 2026.",), []),
        (INVOICE_EN, ("Your new card is expected by 23 October 2026.",), []),
        (INVOICE_EN, ("Applications can be submitted by 23 October 2026.",), []),
    ],
)  # fmt: skip
def test_looser_wordings_in_a_letter_s_flow(
    head: tuple[str, ...], lines: tuple[str, ...], expected: list[tuple[str, str]]
) -> None:
    assert in_flow(head, *lines) == expected


@pytest.mark.parametrize(
    "line",
    [
        "Wir erwarten " + "Zahlung " * 4000 + "bis zum 23.10.2026",
        "sollten " * 4000 + "bis 23.10.2026 vorliegen",
        "Zahlungsfrist " * 4000 + "läuft am 23.10.2026 ab",
        "\n".join("Zahlung bis: 23.10.2026" for _ in range(1500)),
        " ".join("Die Zahlung wird bis 15.11. erwartet" for _ in range(1500)),
        "kann " * 4000 + "werden",
    ],
    ids=["long-gap", "sollten", "frist", "many-fields", "many-yearless", "kann"],
)
def test_the_looser_patterns_stay_fast_on_long_untrusted_text(line: str) -> None:
    started = time.monotonic()
    found = deadline_items(reading(date(2026, 10, 5)), [letter(line, date(2026, 10, 5))], today=TODAY)
    assert len(found) <= 3
    assert time.monotonic() - started < 5
