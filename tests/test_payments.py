"""How a payment is made (ordnung.payments): a direct debit in a to-do's words or a letter's sentence,
a returned debit or a transfer asked for that is none, and the reference to type without its label.
The web app mirrors the to-do rule and the reference (``web/src/lib/payments.test.ts``)."""

from __future__ import annotations

import pytest

from ordnung.models import Item
from ordnung.payments import debit_in_sentence, is_direct_debit, payment_reference


def todo(title: str, action: str | None = None) -> Item:
    return Item.model_validate(
        {
            "id": "itm_x",
            "kind": "payment",
            "title": title,
            "action": action,
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T00:00:00Z",
        }
    )


@pytest.mark.parametrize(
    ("title", "action"),
    [
        ("Monthly fee", "Collected by direct debit"),
        ("Monatsbeitrag", "Wird per Bankeinzug eingezogen"),
        ("Jahresbeitrag", "Will be debited from your account"),
        ("Beitrag (Mandatsreferenz M-4711)", None),
        ("Monatliche Abbuchung Deutschlandticket", None),
    ],
)
def test_a_to_do_naming_a_debit_is_one(title: str, action: str | None) -> None:
    assert is_direct_debit(todo(title, action))


@pytest.mark.parametrize(
    ("title", "action"),
    [
        ("Pay the invoice", "Transfer 49.99 EUR by 15.09.2026"),
        # a returned debit's to-do asks for a transfer
        ("Rücklastschrift", "Bitte überweisen Sie den Betrag zuzüglich der Bankgebühr"),
        ("Kaution vor dem Einzug", None),  # "Einzug" alone is moving in
    ],
)
def test_a_to_do_asking_for_a_transfer_is_none(title: str, action: str | None) -> None:
    assert not is_direct_debit(todo(title, action))


@pytest.mark.parametrize(
    "sentence",
    [
        "Der Monatsbeitrag von 29,90 € wird zum 1. eines Monats per SEPA-Lastschrift eingezogen.",
        "Der Monatsbeitrag von 29,90 € wird per Bankeinzug von Ihrem Konto eingezogen.",
        "Den Betrag von 29,90 € ziehen wir am 01.10.2026 von Ihrem Konto ein (Mandatsreferenz M-4711).",
        "Der Betrag von 29,90 € wird wie gewohnt von Ihrem Konto DE12 3456 eingezogen.",
        "Wir ziehen den Betrag am 15.10. ein.",
        "Den Betrag buchen wir am 15.10. ab",
        "Wir buchen den Beitrag wie bisher zum 15. eines Monats ab, den neuen Betrag erstmals am 15.10.2026.",
        "Der nächste Jahresbeitrag in Höhe von 59,90 € wird am 01.12.2026 von Ihrem Konto abgebucht.",
        "Zahlungsweise SEPA-Lastschrift, Gläubiger-ID DE58ZZZ00000330471",
        "Your next premium of EUR 59.90 will be debited from your account on 1 December.",
        # a transfer waved off
        "Eine Überweisung ist nicht nötig, wir buchen den Betrag ab.",
        "Sie müssen nichts überweisen: der Betrag wird abgebucht.",
        "Bitte überweisen Sie den Betrag nicht, er wird per Lastschrift eingezogen.",
    ],
)
def test_a_sentence_naming_a_debit_speaks_of_one(sentence: str) -> None:
    assert debit_in_sentence(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "Bitte überweisen Sie 49,99 EUR bis zum 15.09.2026.",
        # a returned or failed debit: now the person transfers
        "Ihre Lastschrift wurde von Ihrer Bank zurückgegeben. Bitte überweisen Sie 49,99 EUR bis zum 15.09.2026.",
        "Rücklastschrift: bitte zahlen Sie 49,99 EUR zzgl. 3,00 EUR Gebühr.",
        "Die Lastschrift konnte nicht eingelöst werden. Bitte überweisen Sie den Betrag.",
        "Der Betrag konnte leider nicht von Ihrem Konto abgebucht werden.",
        "Your direct debit was returned by your bank.",
        # a mandate offered as the alternative to the transfer asked for
        "Bitte überweisen Sie 55,08 € bis zum 15.11.2026 oder erteilen Sie uns ein SEPA-Lastschriftmandat.",
        "Sofern Sie uns kein SEPA-Lastschriftmandat erteilt haben, überweisen Sie den Betrag bitte bis zum 15.11.",
        # "ab" and "ein" that close no debit
        "Bitte geben Sie das Buch bis zum 15.10. ab.",
        "Der Betrag ist ab dem 01.10. fällig.",
        "Ziehen Sie ein Ticket am Automaten.",
    ],
)
def test_a_sentence_asking_for_a_transfer_or_naming_a_returned_debit_speaks_of_none(sentence: str) -> None:
    assert not debit_in_sentence(sentence)


@pytest.mark.parametrize(
    ("reference", "typed"),
    [
        ("Kassenzeichen 5126 0184 5122", "5126 0184 5122"),
        ("Kassenzeichen: 5126 0184-5122", "5126 0184-5122"),
        ("Aktenzeichen OA/VW/2026/55012", "OA/VW/2026/55012"),
        ("Az. 5 C 123/26", "5 C 123/26"),
        ("Rechnung Nr. R-2026-0815", "R-2026-0815"),
        ("Rechnungsnr.: 0815", "0815"),
        ("Kunden-Nr. 4711", "4711"),
        ("Verwendungszweck: Kundennummer 12345", "12345"),
        ("Beitragsnummer 457 812 309", "457 812 309"),
        ("Reference RF18 5390 0754 7034", "RF18 5390 0754 7034"),
        ("Invoice no. 2026-17", "2026-17"),
        # no label, or nothing but the label: unchanged
        ("MV-2025-0412 NK 2025", "MV-2025-0412 NK 2025"),
        ("AZ-2026-12", "AZ-2026-12"),
        ("Kassenzeichen", "Kassenzeichen"),
        ("Referenz: ABC", "Referenz: ABC"),
        ("  457 812 309 ", "457 812 309"),
    ],
)
def test_the_reference_to_type_has_no_label(reference: str, typed: str) -> None:
    assert payment_reference(reference) == typed
