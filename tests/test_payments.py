"""How a payment is made (:mod:`ordnung.payments`): a direct debit in a to-do's words or a letter's
sentence, a returned debit, moving in or a transfer asked for that is none, the reference to type without
its label, and a fee paid in person. The web app mirrors the same cases (``web/src/lib/payments.test.ts``,
``paysOnSite`` in ``web/src/features/document/item-meta.ts``)."""

from __future__ import annotations

from typing import Any

import pytest

from ordnung.models import Item
from ordnung.payments import (
    asks_for_transfer,
    debit_in_sentence,
    is_collected_or_incoming,
    is_direct_debit,
    payment_reference,
    pays_on_site,
)


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
        ("Monatliche Abbuchung Deutschlandticket", None),
        ("Monthly mobile fee", "Ensure sufficient funds for the monthly SEPA direct debit of 34.99 €."),
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
    ("title", "action"),
    [
        # a debit that failed, in the to-do's own words and with no "transfer" in its action: the person
        # pays it now, so it keeps its "Pay" and its reminders
        ("Beitrag nachzahlen – konnte nicht eingezogen werden", "Pay 55.08 € by 15.10.2026"),
        (
            "Rundfunkbeitrag nachzahlen – Lastschrift konnte nicht eingelöst werden",
            "Pay 49.99 € by 01.10.2026",
        ),
        ("Pay Rundfunkbeitrag (amount could not be debited)", "Pay 55.08 € by 15.10.2026"),
        ("Mitgliedsbeitrag nach Rücklastschrift", "Pay 47.40 € by 12.12.2025"),
        ("Gym fee: direct debit was returned by the bank", "Pay 47.40 € including the fee"),
        ("Abbuchung fehlgeschlagen", "Pay 29.90 € by 15.10.2026"),
        ("Die Lastschrift wurde mangels Deckung nicht ausgeführt", "Pay 29.90 € plus 3.00 € fee"),
        # a mandate's reference alone doesn't say who moves the money: the mandate may have ended
        ("Beitrag (Mandatsreferenz M-4711)", "Mandate was cancelled; please pay yourself"),
        # "einziehen" is also moving in: a newcomer's first rent and deposit keep their reminders
        ("Die erste Miete von 640 € zahlen, sobald Sie eingezogen sind", None),
        ("Kaution von 1.560 € vor dem Einziehen bezahlen", None),
        ("First rent", "Pay the first rent of 640 € once you have moved in (eingezogen)"),
    ],
)
def test_a_to_do_whose_debit_failed_or_that_moves_in_is_a_payment_to_make(
    title: str, action: str | None
) -> None:
    assert not is_direct_debit(todo(title, action))


@pytest.mark.parametrize(
    ("title", "action"),
    [
        ("Pay the returned direct debit plus the €3 fee", None),
        ("Rücklastschriftgebühr 3,00 € bezahlen", None),
        ("Rundfunkbeitrag: direct debit failed", "Pay 55.08 € by 15.10.2026"),
        # a warning word in another part doesn't hide the failure its own part states
        ("Rücklastschrift Rundfunkbeitrag", "Pay 55.08 € if you haven't yet"),
    ],
)
def test_a_failed_debit_stated_as_a_fact_is_still_one(title: str, action: str | None) -> None:
    assert not is_direct_debit(todo(title, action))


@pytest.mark.parametrize(
    ("title", "action"),
    [
        # the demo's new rent: the person changes their own standing order; the debit is only the alternative
        (
            "New monthly total rent €670",
            "Adjust your standing order to the new total rent unless you use direct debit.",
        ),
        ("Neue Gesamtmiete", "Dauerauftrag auf 670 € anpassen, falls Sie nicht per Lastschrift zahlen"),
        ("Beitrag bisher per Lastschrift", "Set up a standing order for the monthly fee"),
        ("Miete per Lastschrift", "Richten Sie einen Dauerauftrag über 670 € ein"),
    ],
)
def test_a_standing_order_to_set_up_or_change_is_a_transfer(title: str, action: str) -> None:
    """A standing order (Dauerauftrag) the person sets up or changes is their own transfer: the to-do is no
    direct debit, so its date gets a send-by day (the demo's €670 rent had none)."""
    item = todo(title, action)
    assert asks_for_transfer(action)
    assert not is_direct_debit(item) and not is_collected_or_incoming(item)


@pytest.mark.parametrize(
    ("title", "action"),
    [
        ("Monthly rent collected by direct debit", "Cancel your standing order: the rent is now debited."),
        ("Miete per Lastschrift", "Dauerauftrag löschen – die Miete wird ab November abgebucht."),
        ("Beitrag per Lastschrift", "Bitte kündigen Sie Ihren Dauerauftrag."),
        ("Beitrag per Lastschrift", "Bitte stellen Sie Ihren Dauerauftrag ein."),
        ("Beitrag per Lastschrift", "Dauerauftrag einstellen"),
        ("Fee collected by direct debit", "Stop your standing order; you no longer need it."),
        ("Monatsbeitrag per Bankeinzug", "Ihren Dauerauftrag brauchen Sie nicht mehr."),
    ],
)
def test_a_standing_order_to_end_asks_for_no_transfer(title: str, action: str) -> None:
    """A standing order the person is told to cancel, stop or delete, because the payee now collects, is no
    transfer: the direct debit stays one."""
    assert not asks_for_transfer(action)
    assert is_direct_debit(todo(title, action))


def described(title: str, description: str) -> Item:
    return todo(title).model_copy(update={"description": description})


@pytest.mark.parametrize(
    ("title", "description"),
    [
        # a warning of what a returned debit costs is stock wording on a direct-debit bill
        (
            "Monthly fee €49.90 collected by direct debit",
            "Keep the account covered; a returned debit (Rücklastschrift) costs €3.",
        ),
        (
            "Rechnung Oktober 49,99 € per Lastschrift",
            "Collected by SEPA direct debit on 15 Oct; a returned debit costs €3.",
        ),
        ("Beitrag per Lastschrift", "Bei Rücklastschrift berechnen wir 3,00 € Gebühr."),
        ("Beitrag per Lastschrift", "Sollte die Lastschrift nicht eingelöst werden, fallen Gebühren an."),
        ("Beitrag per Lastschrift", "Im Falle einer Rücklastschrift tragen Sie die Kosten."),
        ("Beitrag per Lastschrift", "If the debit is returned, the bank charges a fee."),
        # "returned" or "zurückgegeben" without a debit beside it is anything returned
        ("Router rental collected by direct debit", "The router must be returned within 14 days."),
        ("Leihgerät per Lastschrift", "Das Gerät muss zurückgegeben werden."),
    ],
)
def test_a_warning_of_a_failed_debit_or_something_returned_keeps_the_debit(
    title: str, description: str
) -> None:
    assert is_direct_debit(described(title, description))


@pytest.mark.parametrize(
    "sentence",
    [
        "Der Monatsbeitrag von 29,90 € wird zum 1. eines Monats per SEPA-Lastschrift eingezogen.",
        "Der Monatsbeitrag von 29,90 € wird per Bankeinzug von Ihrem Konto eingezogen.",
        "Den Betrag von 29,90 € ziehen wir am 01.10.2026 von Ihrem Konto ein (Mandatsreferenz M-4711).",
        "Der Betrag von 29,90 € wird wie gewohnt von Ihrem Konto DE12 3456 eingezogen.",
        "Der Betrag wird am 15.10. von Ihrem Konto eingezogen.",
        "Wir ziehen den Betrag am 15.10. ein.",
        "Den Betrag buchen wir am 15.10. ab",
        "Wir buchen den Beitrag wie bisher zum 15. eines Monats ab, den neuen Betrag erstmals am 15.10.2026.",
        "Der nächste Jahresbeitrag in Höhe von 59,90 € wird am 01.12.2026 von Ihrem Konto abgebucht.",
        "Zahlungsweise SEPA-Lastschrift, Gläubiger-ID DE58ZZZ00000330471",
        "Mandatsreferenz M-4711, Gläubiger-ID DE58ZZZ00000330471",
        "Your next premium of EUR 59.90 will be debited from your account on 1 December.",
        # a transfer waved off in its own clause
        "Eine Überweisung ist nicht nötig, wir buchen den Betrag ab.",
        "Eine Überweisung ist nicht nötig: den Betrag von 29,90 € ziehen wir ein.",
        "Sie müssen nichts überweisen: der Betrag wird abgebucht.",
        "Bitte überweisen Sie den Betrag nicht, er wird per Lastschrift eingezogen.",
        "Keine Überweisung nötig – der Betrag wird per Lastschrift eingezogen.",
        "You don't need to transfer anything: the amount is collected by direct debit.",
    ],
)
def test_a_sentence_naming_a_debit_speaks_of_one(sentence: str) -> None:
    assert debit_in_sentence(sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        # the stock warning on a direct-debit bill: no failure happened, the money is collected
        "Der Betrag von 49,90 € wird am 01.10.2026 per SEPA-Lastschrift von Ihrem Konto abgebucht; bei einer "
        "Rücklastschrift berechnen wir 3,00 € Gebühr.",
        "Wir buchen 29,90 € am 15.10. per SEPA-Lastschrift ab, sollte die Lastschrift nicht eingelöst werden, "
        "fallen Gebühren an.",
        "Der Betrag wird am 15.10. abgebucht. Bei Rücklastschrift berechnen wir 3,00 € Gebühr.",
        "Der Beitrag wird per Lastschrift eingezogen (für jede Rücklastschrift berechnen wir 3,00 €).",
        "The amount will be debited on 15 October; a returned debit costs €3.",
        # a failure in another clause than the debit it names cancels nothing: no code is the safe side
        "Der Beitrag wird ab sofort wieder abgebucht, die letzte Lastschrift wurde zurückgegeben.",
    ],
)
def test_a_failure_only_warned_of_or_in_another_clause_keeps_the_debit(sentence: str) -> None:
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
        "Die Lastschrift wurde mangels Deckung nicht ausgeführt. Bitte überweisen Sie 49,99 EUR.",
        "Die Lastschrift wurde mangels Deckung nicht ausgeführt.",
        "Die Abbuchung vom 01.09.2026 war leider nicht möglich. Bitte überweisen Sie 49,99 EUR.",
        "Die Abbuchung vom 01.09.2026 war leider nicht möglich.",
        "Der Lastschrifteinzug ist fehlgeschlagen.",
        "Der Beitrag konnte nicht eingezogen werden. Bitte überweisen Sie 49,99 EUR bis zum 01.10.2026.",
        # a mandate offered as the alternative to the transfer asked for — the negation belongs to the
        # debit's clause, not to the transfer
        "Bitte überweisen Sie 55,08 € bis zum 15.11.2026 oder erteilen Sie uns ein SEPA-Lastschriftmandat.",
        "Sofern Sie uns kein SEPA-Lastschriftmandat erteilt haben, überweisen Sie den Betrag bitte bis zum 15.11.",
        "Sofern Sie nicht am Lastschriftverfahren teilnehmen, überweisen Sie den Betrag von 49,99 EUR bitte "
        "bis zum 15.09.2026.",
        "Wenn Sie nicht per Lastschrift zahlen, überweisen Sie bitte 55,08 €.",
        "Da die Lastschrift mangels Deckung nicht ausgeführt wurde, überweisen Sie bitte 49,99 EUR.",
        "Leider konnten wir keinen Zahlungseingang feststellen. Bitte überweisen Sie 49,99 € (Mandatsreferenz M-1).",
        # "ab" and "ein" that close no debit
        "Bitte geben Sie das Buch bis zum 15.10. ab.",
        "Der Betrag ist ab dem 01.10. fällig.",
        "Ziehen Sie ein Ticket am Automaten.",
        # "einziehen" is also moving in: it names neither the account nor the money
        "Die erste Miete von 640,00 € ist zu zahlen, sobald Sie eingezogen sind.",
        "Die Kaution von 1.560,00 € ist zu zahlen, bevor Sie einziehen.",
        "Sie ziehen am 01.11.2026 ein. Die erste Miete von 640,00 € ist bis zum 03.11.2026 fällig.",
        "Bitte überweisen Sie die Kaution auf unser Konto, bevor Sie einziehen.",
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


STAMPS = {"created_at": "2026-09-28T08:00:00Z", "updated_at": "2026-09-28T08:00:00Z"}


def payment(**fields: Any) -> Item:
    return Item.model_validate({"id": "itm_x", "kind": "payment", "title": "Fee", **STAMPS, **fields})


@pytest.mark.parametrize(
    ("action", "on_site"),
    [
        ("Pay the 4,50 € in fees at the service desk or the payment machine.", True),
        ("Pay the €100 fee on site at the appointment by girocard (cash is not accepted).", True),
        ("Gebühr vor Ort mit EC-Karte bezahlen.", True),
        ("Transfer 55.08 € to the Beitragsservice, or pay in cash.", False),  # a transfer first
        ("Transfer the amount by the deadline.", False),
        ("Pay the fee at the service desk or by standing order.", False),  # a transfer too
        (None, False),
    ],
)
def test_pays_on_site(action: str | None, on_site: bool) -> None:
    """UI audit R1-backend-8: a fee paid by card at the appointment has no bank "send by"."""
    assert pays_on_site(payment(action=action)) is on_site


def test_nothing_else_is_paid_on_site() -> None:
    at_desk = "Pay at the service desk."
    assert not pays_on_site(payment(action=at_desk, direction="in"))  # money coming in
    assert not pays_on_site(payment(title="SEPA-Lastschrift", action=at_desk))  # collected by the sender
    assert not pays_on_site(payment(kind="task", action=at_desk))
    debit = payment(action="Ensure sufficient funds for the direct debit.")
    assert is_direct_debit(debit) and is_collected_or_incoming(debit) and not pays_on_site(debit)
