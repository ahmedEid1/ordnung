"""Two dates for one obligation: the letter's own text checked for a second deadline statement
(:mod:`ordnung.ingest.conflicts`, SPEC § 8 stage 6, § 21)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import Letter
from ordnung import clock
from ordnung.api.routes.dates import recompute_document_items
from ordnung.ingest.conflicts import CONFLICTING_DATES, find_rivals, letter_statements
from ordnung.ingest.plan import ComputedDate, VerifiedItem, compute_item, needs_check, verify_extraction
from ordnung.models import DocumentExtraction, ExtractedItem
from ordnung.rules import RuleContext, catalog
from ordnung.rules.explain import fmt_date
from test_api_support import ApiRouter, api_for

BUFFER = 3


def item(quote: str, *, kind: str = "payment", money: float | None = None, **spec: Any) -> ExtractedItem:
    return ExtractedItem.model_validate(
        {"kind": kind, "title": "t", "date": spec or {"type": "none"}, "amount": money, "quote": quote}
    )


def fixed(quote: str, day: str, *, money: float | None = None, nature: str = "payment") -> ExtractedItem:
    kind = "payment" if nature == "payment" else "deadline"
    return item(quote, kind=kind, money=money, type="fixed", date=day, nature=nature, text=quote)


def read(text: str, *items: ExtractedItem, kind: str = "invoice") -> list[VerifiedItem]:
    reading = DocumentExtraction(kind=kind, title="Letter", summary="s", explanation="e", items=list(items))
    return verify_extraction("doc_x", reading, [(1, text, [], "text")]).items


def company(letter: date, today: date | None = None) -> RuleContext:
    """A company's letter (no deemed delivery), holidays nationwide."""
    return RuleContext(
        today=today or letter, document_date=letter, private_sender=True, sender_kind="company"
    )


def computed(verified: VerifiedItem, ctx: RuleContext) -> ComputedDate:
    return compute_item(verified, ctx, postal_buffer_days=BUFFER)


# --------------------------------------------------------------------------------------------------
# A real conflict: the earlier date, both named, "Please check"
# --------------------------------------------------------------------------------------------------

TWO_DATES = (
    "Musterstadt, 02.03.2026\n"
    "Rechnung Nr. DM-77\n"
    "Bitte überweisen Sie den Rechnungsbetrag von 120,00 EUR binnen 14 Tagen nach dem\n"
    "Rechnungsdatum.\n"
    "Zahlbar bis: 23.03.2026\n"
    "Betrag: 120,00 EUR\n"
)
BOX = fixed("Zahlbar bis: 23.03.2026", "2026-03-23", money=120.0)


def test_a_second_due_date_keeps_the_earlier_one_names_both_and_needs_a_check() -> None:
    [verified] = read(TWO_DATES, BOX)
    result = computed(verified, company(date(2026, 3, 2)))
    # 14 days after Mon 2 Mar 2026 is Mon 16 Mar 2026, a week before the box's date
    assert result.due_date == "2026-03-16"
    assert result.conflict
    assert result.source == "computed"
    receipt = result.receipt
    assert receipt is not None
    assert receipt.confidence == "low"
    assert CONFLICTING_DATES in receipt.rule_ids
    [warning] = [w for w in receipt.warnings if w.startswith("The letter gives two dates")]
    assert "Mon 16 Mar 2026" in warning and "Mon 23 Mar 2026" in warning
    assert "binnen 14 Tagen nach dem Rechnungsdatum" in warning and "Zahlbar bis: 23.03.2026" in warning
    # the receipt says why the date is the earlier one
    last = receipt.steps[-1]
    assert last.rule_id == CONFLICTING_DATES and last.date == "2026-03-16"
    assert "we keep the earliest" in last.label
    assert any(step.date == "2026-03-23" and step.rule_id == CONFLICTING_DATES for step in receipt.steps)
    assert last.citation == catalog.citation(CONFLICTING_DATES)


def test_the_to_do_is_marked_please_check_when_written(tmp_path: Path) -> None:
    from ordnung.ingest.plan import checked_evidence

    [verified] = read(TWO_DATES, BOX)
    assert verified.evidence.value_consistent  # its own sentence states its date …
    result = computed(verified, company(date(2026, 3, 2)))
    assert not checked_evidence(verified, result).value_consistent  # … but the letter gives another


def test_a_to_do_read_as_the_earlier_date_keeps_it_and_is_still_flagged() -> None:
    text = (
        "Musterstadt, 30.04.2026\n"
        "Bitte zahlen Sie den Rechnungsbetrag bis zum 13.05.2026 ohne Abzug.\n"
        "Fälligkeitsdatum: 20.05.2026\n"
        "Betrag: 56,90 EUR\n"
    )
    own = fixed(
        "Bitte zahlen Sie den Rechnungsbetrag bis zum 13.05.2026 ohne Abzug.", "2026-05-13", money=56.9
    )
    [verified] = read(text, own)
    result = computed(verified, company(date(2026, 4, 30)))
    assert result.due_date == "2026-05-13"
    assert result.conflict and result.source == "fixed"
    assert result.receipt is not None and result.receipt.confidence == "low"
    assert any("Wed 20 May 2026" in w for w in result.receipt.warnings)


def test_two_dates_the_letter_gives_for_itself_count_the_period_from_the_earlier() -> None:
    text = (
        "Finanzamt Musterstadt\nDatum\n10.06.2026\n"
        "Mit diesem Bescheid vom 05.06.2026 setzen wir Zinsen in Höhe von 12,00 EUR fest.\n"
        "Einspruch ist binnen eines Monats nach Bekanntgabe möglich.\n"
    )
    objection = item(
        "Einspruch ist binnen eines Monats nach Bekanntgabe möglich.",
        kind="deadline",
        type="relative",
        amount=1,
        unit="months",
        anchor="deemed_delivery",
        delivery_rule="de_admin_post",
        nature="objection",
    )
    [verified] = read(text, objection, kind="tax_assessment")
    ctx = RuleContext(
        today=date(2026, 6, 12),
        document_date=date(2026, 6, 10),
        delivery_scope="ao",
        sender_kind="tax_office",
    )
    alone = compute_item(
        VerifiedItem(verified.item, verified.evidence, verified.reasons, verified.slot_key),
        ctx,
        postal_buffer_days=BUFFER,
    )
    result = computed(verified, ctx)
    # posted Fri 5 Jun: delivered Tue 9 Jun, one month → Thu 9 Jul; from Wed 10 Jun: Sun 14 → Mon 15 Jun → Wed 15 Jul
    assert alone.due_date == "2026-07-15"
    assert result.due_date == "2026-07-09"
    assert result.conflict
    assert result.receipt is not None
    assert any("gives two dates for itself" in w and "Fri 5 Jun 2026" in w for w in result.receipt.warnings)
    assert result.receipt.steps[0].rule_id == CONFLICTING_DATES  # where the earlier start comes from


# --------------------------------------------------------------------------------------------------
# No conflict
# --------------------------------------------------------------------------------------------------


def test_a_reminder_repeating_the_original_due_date_is_no_conflict() -> None:
    text = (
        "Musterstadt, 01.04.2026\n"
        "Zahlungserinnerung\n"
        "Rechnung vom 01.03.2026, ursprünglich fällig am 15.03.2026.\n"
        "Die Zahlung war am 15.03.2026 fällig.\n"
        "Bitte überweisen Sie 49,99 EUR bis zum 10.04.2026.\n"
    )
    own = fixed("Bitte überweisen Sie 49,99 EUR bis zum 10.04.2026.", "2026-04-10", money=49.99)
    [verified] = read(text, own, kind="dunning")
    result = computed(verified, company(date(2026, 4, 1)))
    assert result.due_date == "2026-04-10"
    assert not result.conflict
    assert result.receipt is not None and CONFLICTING_DATES not in result.receipt.rule_ids


def test_a_reminder_quoting_the_invoices_payment_terms_is_no_conflict() -> None:
    text = (
        "Musterstadt, 01.04.2026\n"
        "Zahlbar innerhalb von 14 Tagen nach Rechnungsdatum.\n"
        "Bitte überweisen Sie 49,99 EUR bis zum 20.04.2026.\n"
    )
    own = fixed("Bitte überweisen Sie 49,99 EUR bis zum 20.04.2026.", "2026-04-20", money=49.99)
    [verified] = read(text, own, kind="dunning")
    ctx = RuleContext(
        today=date(2026, 4, 1),
        document_date=date(2026, 4, 1),
        private_sender=True,
        sender_kind="company",
        letter_kind="dunning",
    )
    assert not computed(verified, ctx).conflict  # the terms count from the old invoice's date


def test_a_payment_date_and_an_objection_deadline_are_different_obligations() -> None:
    text = (
        "Stadt Musterstadt, 02.03.2026\n"
        "Bitte zahlen Sie die Gebühr von 80,00 EUR bis zum 20.03.2026.\n"
        "Gegen diesen Bescheid können Sie bis zum 06.04.2026 Widerspruch einlegen.\n"
    )
    pay = fixed("Bitte zahlen Sie die Gebühr von 80,00 EUR bis zum 20.03.2026.", "2026-03-20", money=80.0)
    objection = fixed(
        "Gegen diesen Bescheid können Sie bis zum 06.04.2026 Widerspruch einlegen.",
        "2026-04-06",
        nature="objection",
    )
    verified = read(text, pay, objection, kind="authority_letter")
    assert [v.rivals for v in verified] == [(), ()]
    ctx = RuleContext(today=date(2026, 3, 4), document_date=date(2026, 3, 2), delivery_scope="vwvfg")
    assert [computed(v, ctx).conflict for v in verified] == [False, False]


def test_an_objection_deadline_stated_twice_differently_is_a_conflict() -> None:
    text = (
        "Stadt Musterstadt, 02.03.2026\n"
        "Gegen diesen Bescheid können Sie bis zum 06.04.2026 Widerspruch einlegen.\n"
        "Frist für den Widerspruch: bis 02.04.2026\n"
    )
    objection = fixed(
        "Gegen diesen Bescheid können Sie bis zum 06.04.2026 Widerspruch einlegen.",
        "2026-04-06",
        nature="objection",
    )
    [verified] = read(text, objection, kind="authority_letter")
    ctx = RuleContext(today=date(2026, 3, 4), document_date=date(2026, 3, 2), delivery_scope="vwvfg")
    result = computed(verified, ctx)
    assert result.conflict and result.due_date == "2026-04-02"


def test_the_same_date_written_twice_is_no_conflict() -> None:
    text = (
        "Musterstadt, 30.04.2026\n"
        "Bitte zahlen Sie den Rechnungsbetrag bis zum 15.05.2026.\n"
        "Fälligkeitsdatum: 15.05.2026\n"
    )
    own = fixed("Bitte zahlen Sie den Rechnungsbetrag bis zum 15.05.2026.", "2026-05-15")
    [verified] = read(text, own)
    result = computed(verified, company(date(2026, 4, 30)))
    assert not result.conflict
    assert result.receipt is not None and result.receipt.confidence == "high"
    assert not needs_check_after(verified, result)


def test_a_period_giving_the_same_date_is_no_conflict() -> None:
    text = (
        "Musterstadt, 02.03.2026\n"
        "Zahlbar innerhalb von 14 Tagen nach Rechnungsdatum.\n"
        "Zahlbar bis: 16.03.2026\n"
    )
    [verified] = read(text, fixed("Zahlbar bis: 16.03.2026", "2026-03-16"))
    assert not computed(verified, company(date(2026, 3, 2))).conflict


@pytest.mark.parametrize(
    "discount",
    [
        "Zahlbar bis zum 10.02.2026 abzüglich 2 % Skonto.",
        "Bei Zahlung bis zum 10.02.2026 gewähren wir 2 % Skonto.",
        "Payable by 10 February 2026 less a 2 % discount.",
    ],
)
def test_an_early_payment_discount_date_is_no_second_due_date(discount: str) -> None:
    """Skonto: paying after the discount date is not late, so the net date stays the to-do's date."""
    text = f"Musterstadt, 27.01.2026\nZahlbar bis zum 24.02.2026 ohne Abzug.\n{discount}\n"
    net = fixed("Zahlbar bis zum 24.02.2026 ohne Abzug.", "2026-02-24")
    [verified] = read(text, net)
    assert verified.rivals == ()
    result = computed(verified, company(date(2026, 1, 27)))
    assert result.due_date == "2026-02-24" and not result.conflict


def test_a_to_do_read_from_the_discount_sentence_is_left_to_the_reading() -> None:
    text = "Musterstadt, 27.01.2026\nZahlbar bis zum 24.02.2026 ohne Abzug.\nZahlbar bis zum 10.02.2026 abzüglich 2 % Skonto.\n"
    discount = fixed("Zahlbar bis zum 10.02.2026 abzüglich 2 % Skonto.", "2026-02-10")
    [verified] = read(text, discount)
    assert verified.rivals == ()


def test_another_to_dos_date_or_amount_is_not_a_second_date() -> None:
    text = (
        "Musterstadt, 20.04.2026\n"
        "Die erste Rate ist bis zum 15.05.2026 zu zahlen.\n"
        "Die zweite Rate ist bis zum 15.06.2026 zu zahlen.\n"
        "Die Mahngebühr von 5,00 EUR ist bis zum 01.06.2026 zu zahlen.\n"
    )
    first = fixed("Die erste Rate ist bis zum 15.05.2026 zu zahlen.", "2026-05-15", money=100.0)
    second = fixed("Die zweite Rate ist bis zum 15.06.2026 zu zahlen.", "2026-06-15", money=100.0)
    verified = read(text, first, second)
    assert [v.rivals for v in verified] == [(), ()]


def test_a_changed_decision_naming_the_old_one_is_not_the_letters_own_date() -> None:
    text = (
        "Finanzamt Musterstadt, 10.06.2026\n"
        "Der Bescheid vom 14.01.2026 wird geändert.\n"
        "Mit Bescheid vom 14.01.2026 hatten wir die Steuer auf 900,00 EUR festgesetzt.\n"
        "Einspruch ist binnen eines Monats nach Bekanntgabe möglich.\n"
    )
    objection = item(
        "Einspruch ist binnen eines Monats nach Bekanntgabe möglich.",
        kind="deadline",
        type="relative",
        amount=1,
        unit="months",
        anchor="deemed_delivery",
        delivery_rule="de_admin_post",
        nature="objection",
    )
    [verified] = read(text, objection, kind="tax_assessment")
    assert verified.rivals == ()


def test_recurring_undated_and_incoming_to_dos_are_not_checked() -> None:
    monthly = ExtractedItem.model_validate(
        {
            "kind": "payment",
            "title": "t",
            "date": {"type": "fixed", "date": "2026-03-23", "nature": "payment"},
            "recurrence": {"interval": 1, "unit": "months"},
            "quote": "Zahlbar bis: 23.03.2026",
        }
    )
    refund = BOX.model_copy(update={"direction": "in"})
    undated = item("Zahlbar bis: 23.03.2026")
    pages = [(1, TWO_DATES, [], "text")]
    assert find_rivals(monthly, [monthly], pages) == ()
    assert find_rivals(refund, [refund], pages) == ()
    assert find_rivals(undated, [undated], pages) == ()


@pytest.mark.parametrize(
    ("header", "own_quote"),
    [
        (
            "Rechnung Nr. RV-12\nRechnungsdatum: 02.03.2026\nZahlbar bis: 16.03.2026\nBetrag: 120,00 EUR",
            "Zahlbar bis: 16.03.2026",
        ),
        (
            "Gesamtbetrag fällig: 120,00 EUR\nDatum: 02.03.2026\nZahlbar bis: 16.03.2026",
            "Zahlbar bis: 16.03.2026",
        ),
        (
            "Rechnungsdatum: 02.03.2026 · Zahlbar bis: 16.03.2026\nBetrag: 120,00 EUR",
            "Zahlbar bis: 16.03.2026",
        ),
        ("Invoice date: 02.03.2026\nDue date: 16.03.2026\nAmount: 120.00 EUR", "Due date: 16.03.2026"),
        (
            "Total due: 120.00 EUR\nInvoice date: 02.03.2026\nPayment due: 16.03.2026",
            "Payment due: 16.03.2026",
        ),
    ],
)
@pytest.mark.parametrize("letter_date", [date(2026, 3, 2), None])
def test_an_invoice_headers_own_date_is_no_second_due_date(
    header: str, own_quote: str, letter_date: date | None
) -> None:
    """The invoice's date stands on its own label: the next label's "Zahlbar", or a payment word of an
    earlier label, is not its — and the letter's own date is never a date to pay by."""
    [verified] = read(f"Druckerei Muster GmbH\n{header}\n", fixed(own_quote, "2026-03-16", money=120.0))
    assert verified.rivals == ()
    ctx = RuleContext(
        today=date(2026, 3, 4), document_date=letter_date, private_sender=True, sender_kind="company"
    )
    result = computed(verified, ctx)
    assert result.due_date == "2026-03-16" and not result.conflict


def test_the_letters_own_date_is_never_a_second_date_to_pay_by() -> None:
    text = "Musterstadt, 02.03.2026\nDer Betrag ist fällig am 02.03.2026.\nZahlbar bis: 16.03.2026\n"
    [verified] = read(text, fixed("Zahlbar bis: 16.03.2026", "2026-03-16"))
    assert [rival.statement for rival in verified.rivals] == ["fällig am 02.03.2026"]
    assert not computed(verified, company(date(2026, 3, 2))).conflict


def test_a_payment_request_wrapped_over_two_lines_is_still_a_second_date() -> None:
    text = (
        "Musterstadt, 02.03.2026\n"
        "Bitte überweisen Sie den Betrag von 120,00 EUR bis\n"
        "zum 09.03.2026.\n"
        "Zahlbar bis: 16.03.2026\n"
    )
    [verified] = read(text, fixed("Zahlbar bis: 16.03.2026", "2026-03-16", money=120.0))
    result = computed(verified, company(date(2026, 3, 2)))
    assert result.conflict and result.due_date == "2026-03-09"


def test_a_reminder_whose_own_date_was_not_read_keeps_the_original_due_date_as_history() -> None:
    text = (
        "Zahlungserinnerung\n"
        "Die Rechnung vom 01.03.2026 ist fällig am 15.03.2026.\n"
        "Bitte überweisen Sie 49,99 EUR bis zum 10.04.2026.\n"
    )
    own = fixed("Bitte überweisen Sie 49,99 EUR bis zum 10.04.2026.", "2026-04-10", money=49.99)
    [verified] = read(text, own, kind="dunning")
    ctx = RuleContext(
        today=date(2026, 4, 2),
        document_date=None,
        private_sender=True,
        sender_kind="company",
        letter_kind="dunning",
    )
    result = computed(verified, ctx)
    assert result.due_date == "2026-04-10" and not result.conflict
    # the day it arrived counts before today when it is known
    arrived = replace(ctx, today=date(2026, 4, 20), received_date=date(2026, 4, 2))
    assert not computed(verified, arrived).conflict


@pytest.mark.parametrize(
    ("text", "own"),
    [
        (
            "Stadtwerke, 02.03.2026\nDer Nachzahlungsbetrag von 120,00 EUR ist bis zum 31.03.2026 zu zahlen, "
            "die neuen Abschläge sind monatlich fällig, erstmals am 15.03.2026.\n",
            fixed(
                "Der Nachzahlungsbetrag von 120,00 EUR ist bis zum 31.03.2026 zu zahlen",
                "2026-03-31",
                money=120.0,
            ),
        ),
        (
            "Finanzamt, 02.03.2026\nBitte zahlen Sie die Abschlusszahlung von 1.200,00 EUR bis zum 31.03.2026.\n"
            "Die nächste Vorauszahlung ist fällig am 10.03.2026.\n",
            fixed(
                "Bitte zahlen Sie die Abschlusszahlung von 1.200,00 EUR bis zum 31.03.2026.",
                "2026-03-31",
                money=1200.0,
            ),
        ),
        (
            "Finanzamt, 02.03.2026\nBitte zahlen Sie die Abschlusszahlung von 1.200,00 EUR bis zum 31.03.2026.\n"
            "Vorauszahlungen: Die Vorauszahlungen sind jeweils fällig am 10.06.2026 und 10.09.2026.\n",
            fixed(
                "Bitte zahlen Sie die Abschlusszahlung von 1.200,00 EUR bis zum 31.03.2026.",
                "2026-03-31",
                money=1200.0,
            ),
        ),
        (
            "Versicherung AG, 02.03.2026\n"
            "Der Erstbeitrag von 60,00 EUR ist fällig am 01.04.2026 und wird von Ihrem Konto abgebucht.\n"
            "Bitte zahlen Sie den Restbetrag von 60,00 EUR bis zum 16.03.2026.\n",
            fixed(
                "Bitte zahlen Sie den Restbetrag von 60,00 EUR bis zum 16.03.2026.", "2026-03-16", money=60.0
            ),
        ),
    ],
    ids=["new-instalments", "next-prepayment", "prepayment-dates", "first-premium-debited"],
)
def test_a_date_for_another_kind_of_payment_is_not_a_second_date(text: str, own: ExtractedItem) -> None:
    """Instalments, prepayments, a premium collected by direct debit: the letter's other payments, even
    when the reading did not list them as to-dos."""
    [verified] = read(text, own, kind="utility_bill")
    assert verified.rivals == ()
    result = computed(verified, company(date(2026, 3, 2)))
    assert result.due_date == own.date.date and not result.conflict


def test_a_remedy_period_mentioning_the_payment_duty_is_no_payment_period() -> None:
    text = (
        "Stadt Musterstadt, 02.03.2026\n"
        "Bitte zahlen Sie die Gebühr von 80,00 EUR bis zum 16.03.2026.\n"
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Zugang Widerspruch erhoben werden; "
        "die Zahlungspflicht bleibt davon unberührt.\n"
    )
    pay = fixed("Bitte zahlen Sie die Gebühr von 80,00 EUR bis zum 16.03.2026.", "2026-03-16", money=80.0)
    [verified] = read(text, pay, kind="authority_letter")
    assert verified.rivals == ()
    ctx = RuleContext(today=date(2026, 3, 4), document_date=date(2026, 3, 2), delivery_scope="vwvfg")
    assert not computed(verified, ctx).conflict


def test_another_remedys_deadline_is_not_a_second_objection_deadline() -> None:
    text = (
        "Amtsgericht, 02.03.2026\n"
        "Gegen den Beschluss ist die Beschwerde bis zum 30.03.2026 zulässig.\n"
        "Eine Klage ist bis zum 02.04.2026 möglich.\n"
    )
    complaint = fixed(
        "Gegen den Beschluss ist die Beschwerde bis zum 30.03.2026 zulässig.",
        "2026-03-30",
        nature="objection",
    )
    [verified] = read(text, complaint, kind="authority_letter")
    assert verified.rivals == ()
    ctx = RuleContext(today=date(2026, 3, 4), document_date=date(2026, 3, 2))
    assert not computed(verified, ctx).conflict


def needs_check_after(verified: VerifiedItem, result: ComputedDate) -> bool:
    from ordnung.ingest.plan import checked_evidence

    return not checked_evidence(verified, result).value_consistent


# --------------------------------------------------------------------------------------------------
# Notices and declarations: a cancellation, a form, documents or a statement to send by a day
# --------------------------------------------------------------------------------------------------


def _said(result: ComputedDate) -> str:
    """Everything the receipt says: its warnings and its steps."""
    receipt = result.receipt
    assert receipt is not None
    return " ".join([*receipt.warnings, *(step.label for step in receipt.steps)])


def _two_dates(result: ComputedDate) -> list[str]:
    """The receipt's warnings that the letter gives another date for the to-do."""
    receipt = result.receipt
    assert receipt is not None
    return [warning for warning in receipt.warnings if warning.startswith("The letter gives two dates")]


@pytest.mark.parametrize(
    ("text", "own", "earlier"),
    [
        (
            "Beispiel Versicherung AG, 02.03.2026\n"
            "Bitte reichen Sie die fehlenden Unterlagen bis zum 27.03.2026 ein.\n"
            "Frist für die Unterlagen: 20.03.2026\n",
            fixed(
                "Bitte reichen Sie die fehlenden Unterlagen bis zum 27.03.2026 ein.",
                "2026-03-27",
                nature="declaration",
            ),
            "2026-03-20",
        ),
        (
            "Beispiel Versicherung AG, 02.03.2026\n"
            "Bitte senden Sie den ausgefüllten Fragebogen innerhalb von 14 Tagen nach dem Datum dieses "
            "Schreibens zurück.\n"
            "Der Fragebogen muss bis spätestens 23.03.2026 bei uns eingehen.\n",
            fixed(
                "Der Fragebogen muss bis spätestens 23.03.2026 bei uns eingehen.",
                "2026-03-23",
                nature="declaration",
            ),
            "2026-03-16",  # 14 days after Mon 2 Mar
        ),
        (
            "Studienwerk Muster, 02.03.2026\n"
            "Please return the signed form by 20 March 2026.\n"
            "The form must be received no later than 16 March 2026.\n",
            fixed("Please return the signed form by 20 March 2026.", "2026-03-20", nature="declaration"),
            "2026-03-16",
        ),
        (
            "Muster Mobilfunk GmbH, 02.03.2026\n"
            "Ihre Kündigung muss uns bis spätestens 30.09.2026 vorliegen.\n"
            "Sie können den Vertrag bis zum 31.08.2026 kündigen.\n",
            fixed(
                "Ihre Kündigung muss uns bis spätestens 30.09.2026 vorliegen.", "2026-09-30", nature="notice"
            ),
            "2026-08-31",
        ),
    ],
    ids=["documents-label", "questionnaire-period", "english-form", "notice"],
)
def test_a_notice_or_declaration_dated_twice_keeps_the_earlier_and_needs_a_check(
    text: str, own: ExtractedItem, earlier: str
) -> None:
    [verified] = read(text, own, kind="other")
    result = computed(verified, company(date(2026, 3, 2)))
    assert result.due_date == earlier
    assert result.conflict
    receipt = result.receipt
    assert receipt is not None and receipt.confidence == "low" and CONFLICTING_DATES in receipt.rule_ids
    [warning] = _two_dates(result)
    assert fmt_date(date.fromisoformat(own.date.date or "")) in warning
    assert fmt_date(date.fromisoformat(earlier)) in warning
    assert needs_check_after(verified, result)


DOCUMENTS = fixed(
    "Bitte reichen Sie die fehlenden Unterlagen bis zum 27.03.2026 ein.", "2026-03-27", nature="declaration"
)


@pytest.mark.parametrize(
    "other",
    [
        "Die Unterlagen waren ursprünglich bis zum 13.03.2026 einzureichen.",
        "Wenn möglich, reichen Sie die Unterlagen bis zum 13.03.2026 ein.",
        "Künftige Unterlagen reichen Sie bitte jeweils bis zum 15. eines Monats ein, erstmals bis zum 13.03.2026.",
        "Wie mit Schreiben vom 16.02.2026 erbeten, sind die Unterlagen binnen 10 Tagen nach Erhalt unseres "
        "Schreibens einzureichen.",
        "Checkliste Unterlagen – Stand: 13.03.2026",
        "Den Fragebogen senden Sie bitte bis zum 13.03.2026 zurück.",
    ],
    ids=["past", "optional", "series", "another-letters-period", "label-names-no-deadline", "another-thing"],
)
def test_a_declarations_guards_leave_out_what_is_no_second_date(other: str) -> None:
    """Written in the past, optional (as *Skonto* is for a payment), a series, a period from another
    letter, a label that names a date but no deadline, something else to send: none of them dates the
    to-do — the letter's real second date still does."""
    text = (
        "Beispiel Versicherung AG, 02.03.2026\n"
        "Bitte reichen Sie die fehlenden Unterlagen bis zum 27.03.2026 ein.\n"
        f"{other}\n"
        "Frist für die Unterlagen: 20.03.2026\n"
    )
    [verified] = read(text, DOCUMENTS, kind="other")
    result = computed(verified, company(date(2026, 3, 2)))
    assert result.due_date == "2026-03-20" and result.conflict  # the label's date, and no other
    [warning] = _two_dates(result)
    assert "Fri 20 Mar 2026" in warning and "Fri 27 Mar 2026" in warning


def test_a_reminder_repeating_the_declarations_original_date_is_no_second_date() -> None:
    text = (
        "Beispiel Versicherung AG, 12.03.2026\n"
        "Erinnerung\n"
        "In unserem Schreiben vom 16.02.2026 baten wir Sie, die Unterlagen bis zum 06.03.2026 einzureichen.\n"
        "Bitte reichen Sie die fehlenden Unterlagen bis zum 27.03.2026 ein.\n"
        "Frist für die Unterlagen: 20.03.2026\n"
    )
    [verified] = read(text, DOCUMENTS, kind="other")
    result = computed(verified, company(date(2026, 3, 12)))
    assert result.due_date == "2026-03-20" and result.conflict
    [warning] = _two_dates(result)
    assert "Fri 20 Mar 2026" in warning and "Fri 27 Mar 2026" in warning


def test_another_declarations_date_is_not_a_second_date() -> None:
    text = (
        "Jobcenter Musterstadt, 02.03.2026\n"
        "Bitte reichen Sie die Lohnabrechnungen bis zum 27.03.2026 ein.\n"
        "Die Kontoauszüge reichen Sie bitte bis zum 13.03.2026 ein.\n"
        "Frist für die Unterlagen: 20.03.2026\n"
    )
    payslips = fixed(
        "Bitte reichen Sie die Lohnabrechnungen bis zum 27.03.2026 ein.", "2026-03-27", nature="declaration"
    )
    statements = fixed(
        "Die Kontoauszüge reichen Sie bitte bis zum 13.03.2026 ein.", "2026-03-13", nature="declaration"
    )
    first, _ = read(text, payslips, statements, kind="authority_letter")
    assert [rival.statement for rival in first.rivals] == ["Frist für die Unterlagen: 20.03.2026"]
    assert computed(first, company(date(2026, 3, 2))).due_date == "2026-03-20"


@pytest.mark.parametrize(
    "other",
    [
        "Der Vertrag kann mit einer Frist von drei Monaten zum 31.12.2026 gekündigt werden.",
        "Ihr Sonderkündigungsrecht können Sie bis zum 31.08.2026 ausüben.",
    ],
    ids=["the-end-it-takes-effect", "a-special-right"],
)
def test_a_notices_guards_leave_out_its_end_and_another_right(other: str) -> None:
    """A notice "zum 31.12." names the end it takes effect, not the day it must arrive by; a special
    right to cancel is another obligation than the ordinary notice."""
    text = (
        "Muster Mobilfunk GmbH, 02.03.2026\n"
        "Ihre Kündigung muss uns bis spätestens 30.09.2026 vorliegen.\n"
        f"{other}\n"
        "Kündigungen müssen bis zum 15.09.2026 bei uns eingehen.\n"
    )
    own = fixed("Ihre Kündigung muss uns bis spätestens 30.09.2026 vorliegen.", "2026-09-30", nature="notice")
    [verified] = read(text, own, kind="contract")
    result = computed(verified, company(date(2026, 3, 2)))
    assert result.due_date == "2026-09-15" and result.conflict
    [warning] = _two_dates(result)
    assert "Tue 15 Sep 2026" in warning and "Wed 30 Sep 2026" in warning


# --------------------------------------------------------------------------------------------------
# The letter's own date in its header
# --------------------------------------------------------------------------------------------------

INTEREST_OBJECTION = item(
    "Einspruch ist binnen eines Monats nach Bekanntgabe möglich.",
    kind="deadline",
    type="relative",
    amount=1,
    unit="months",
    anchor="deemed_delivery",
    delivery_rule="de_admin_post",
    nature="objection",
)


def _tax_office(letter: date) -> RuleContext:
    return RuleContext(
        today=date(2026, 3, 18), document_date=letter, delivery_scope="ao", sender_kind="tax_office"
    )


@pytest.mark.parametrize(
    "header",
    [
        "Datum: 16.03.2026",
        "Steuernummer 123/456/78901 · Datum: Montag, 16.03.2026",
        "Finanzamt Musterstadt · Postfach 1 · 12345 Musterstadt   Datum\n16.03.2026",
        "Datum   16.03.2026",
        "Date: 16 March 2026",
    ],
)
def test_a_header_date_after_the_one_read_is_named_and_the_earlier_date_kept(header: str) -> None:
    """The reading took the decision's date in the text (12 Mar) as the letter's; its header says 16 Mar.
    The date counted from 12 Mar is already the earlier: it stays, but the letter contradicts itself, so
    it is named and the to-do is "Please check"."""
    text = (
        f"Finanzamt Musterstadt\n{header}\n"
        "Sehr geehrte Damen und Herren,\n"
        "mit Bescheid vom 12.03.2026 setzen wir Zinsen in Höhe von 12,00 EUR fest.\n"
        "Einspruch ist binnen eines Monats nach Bekanntgabe möglich.\n"
    )
    [verified] = read(text, INTEREST_OBJECTION, kind="tax_assessment")
    result = computed(verified, _tax_office(date(2026, 3, 12)))
    # posted Thu 12 Mar: delivered Mon 16 Mar, one month → Thu 16 Apr; from Mon 16 Mar: Fri 20 Mar → Mon 20 Apr
    assert result.due_date == "2026-04-16"
    assert result.conflict
    receipt = result.receipt
    assert receipt is not None and receipt.confidence == "low"
    [warning] = [w for w in receipt.warnings if "gives two dates for itself" in w]
    assert "Thu 12 Mar 2026" in warning and "Mon 16 Mar 2026" in warning and "Mon 20 Apr 2026" in warning
    assert needs_check_after(verified, result)


@pytest.mark.parametrize(
    "table",
    ["Bescheid   Datum\nVorauszahlungen   02.03.2026", "Bescheid über Vorauszahlungen · Datum: 02.03.2026"],
)
def test_a_date_in_the_letters_body_is_not_its_own_date(table: str) -> None:
    """Only the header's label counts — never a "Datum" in the letter's body (a table of earlier
    decisions, the old invoice a reminder lists), which would count the period from long before."""
    body = (
        "Sehr geehrte Damen und Herren,\n"
        f"{table}\n"
        "mit Bescheid vom 12.03.2026 setzen wir Zinsen in Höhe von 12,00 EUR fest.\n"
        "Einspruch ist binnen eines Monats nach Bekanntgabe möglich.\n"
    )
    [unlabelled] = read(f"Finanzamt Musterstadt\nMusterstadt, 16.03.2026\n{body}", INTEREST_OBJECTION)
    assert {rival.letter_date for rival in unlabelled.rivals} == {date(2026, 3, 12)}
    [labelled] = read(f"Finanzamt Musterstadt\nDatum: 16.03.2026\n{body}", INTEREST_OBJECTION)
    assert {rival.letter_date for rival in labelled.rivals} == {date(2026, 3, 16), date(2026, 3, 12)}
    result = computed(labelled, _tax_office(date(2026, 3, 12)))
    assert result.due_date == "2026-04-16" and result.conflict
    assert "Mon 16 Mar 2026" in _said(result) and "Mon 2 Mar 2026" not in _said(result)


def test_only_the_first_header_date_that_reads_one_way_is_the_letters() -> None:
    def header_dates(header: str) -> list[date | None]:
        page = (1, f"Studienwerk Muster\n{header}\nDear Ms Muster,\nThank you.\n", [], "text")
        return [statement.letter_date for statement in letter_statements([page]) if statement.letter_date]

    assert header_dates("Date: 16/03/2026") == [date(2026, 3, 16)]
    assert header_dates("Date: 07/08/2026") == []  # 7 Aug or 8 Jul: it can't be told
    assert header_dates("Date: 16/03/2026\nDate: 18/03/2026") == [date(2026, 3, 16)]


# --------------------------------------------------------------------------------------------------
# Through the pipeline, and when the letter's dates are recomputed
# --------------------------------------------------------------------------------------------------

TWO_DATES_LETTER = Letter(
    marker="Rechnung Nr. DM-77",
    pages=(
        (
            "Druckerei Muster GmbH · Satzweg 1 · 12345 Musterstadt",
            "SPECIMEN",
            "Musterstadt, 02.03.2026",
            "Rechnung Nr. DM-77",
            "Bitte überweisen Sie den Rechnungsbetrag von 120,00 EUR",
            "binnen 14 Tagen nach dem Rechnungsdatum.",
            "Zahlbar bis: 23.03.2026",
        ),
    ),
    payload={
        "kind": "invoice",
        "area": "money",
        "title": "Print order",
        "sender": {"name": "Druckerei Muster GmbH", "kind": "company"},
        "document_date": "2026-03-02",
        "summary": "Druckerei Muster bills 120.00 EUR.",
        "explanation": "Pay the bill.",
        "items": [
            {
                "kind": "payment",
                "title": "Pay the print order",
                "date": {
                    "type": "fixed",
                    "date": "2026-03-23",
                    "nature": "payment",
                    "text": "Zahlbar bis: 23.03.2026",
                },
                "amount": 120.0,
                "currency": "EUR",
                "direction": "out",
                "quote": "Zahlbar bis: 23.03.2026",
            }
        ],
    },
)


def _router() -> ApiRouter:
    router = ApiRouter()
    router.letters = (TWO_DATES_LETTER, *router.letters)
    router.payloads[TWO_DATES_LETTER.marker] = TWO_DATES_LETTER.extraction()
    return router


async def test_a_letter_with_two_dates_is_filed_with_the_earlier_and_stays_so(data_dir: Path) -> None:
    clock.set_today("2026-03-04")
    try:
        async with api_for(data_dir, router=_router()) as api:
            body = await api.upload(("druck.pdf", TWO_DATES_LETTER.pdf()))
            await api.read_all()
            doc_id = body["documents"][0]["id"]
            store = api.ctx.store
            [stored] = [i for i in store.list_items(doc_id=doc_id) if i.origin == "extracted"]
            assert stored.due_date == "2026-03-16"
            assert stored.computation is not None and stored.computation.confidence == "low"
            assert needs_check(stored)
            document = store.get_document(doc_id)
            assert document is not None and document.status == "needs_review"

            # confirming the arrival day recomputes the dates: the earlier one stays, still "Please check"
            patched = await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-03-03"})
            assert patched.status_code == 200
            [again] = [i for i in store.list_items(doc_id=doc_id) if i.origin == "extracted"]
            assert again.due_date == "2026-03-16"
            assert again.computation is not None and CONFLICTING_DATES in again.computation.rule_ids
            assert needs_check(again)

            # a letter read before the check: recomputing its dates settles them and marks the to-do
            evidence = [e.model_copy(update={"value_consistent": True}) for e in again.evidence]
            store.update_item(again.id, evidence=evidence, due_date="2026-03-23", computation=None)
            document = store.get_document(doc_id)
            assert document is not None
            recompute_document_items(store, document, date(2026, 3, 4))
            settled = store.get_item(again.id)
            assert settled is not None and settled.due_date == "2026-03-16"
            assert needs_check(settled)
    finally:
        clock.set_today(None)


DISMISSAL_TWO_DATES = Letter(
    marker="Kündigung Ihres Arbeitsverhältnisses PN-4471",
    pages=(
        (
            "Café Kranz GmbH · Marktplatz 3 · 12345 Musterstadt",
            "SPECIMEN",
            "Musterstadt, 24.09.2026",
            "Kündigung Ihres Arbeitsverhältnisses PN-4471",
            "Sehr geehrte Frau Rivera,",
            "mit diesem Schreiben vom 21.09.2026",
            "kündigen wir das Arbeitsverhältnis fristgerecht zum 31.12.2026.",
        ),
    ),
    payload={
        "kind": "employment",
        "area": "work",
        "title": "Dismissal by Café Kranz",
        "sender": {"name": "Café Kranz GmbH", "kind": "employer"},
        "document_date": "2026-09-24",
        "summary": "Your employer ends your job on 31 Dec 2026.",
        "explanation": "Your job ends.",
        "items": [],
        "change": {
            "type": "termination_by_provider",
            "effective_date": "2026-12-31",
            "quote": "kündigen wir das Arbeitsverhältnis fristgerecht zum 31.12.2026",
        },
        "urgency": "high",
    },
)


async def test_a_deadline_the_law_adds_counts_from_the_earlier_of_the_letters_two_dates(
    data_dir: Path,
) -> None:
    """A dismissal dated 24 Sep in its header and 21 Sep in its text: the three weeks for the court action
    (§ 4 KSchG) count from its arrival — unknown, so from its date, the earlier one: Mon 12 Oct, not Thu 15
    Oct. The receipt says why, the warning names both and the to-do is "Please check"; the registration
    (three months before the end) doesn't depend on the letter's date and stays as it is."""
    router = ApiRouter()
    router.letters = (DISMISSAL_TWO_DATES, *router.letters)
    router.payloads[DISMISSAL_TWO_DATES.marker] = DISMISSAL_TWO_DATES.extraction()
    clock.set_today("2026-09-26")
    try:
        async with api_for(data_dir, router=router) as api:
            body = await api.upload(("kuendigung.pdf", DISMISSAL_TWO_DATES.pdf()))
            await api.read_all()
            doc_id = body["documents"][0]["id"]
            store = api.ctx.store
            document = store.get_document(doc_id)
            assert document is not None and document.kind == "dismissal"
            rules = {item.slot_key: item for item in store.list_items(doc_id=doc_id) if item.origin == "rule"}
            court, register = rules["rule:kschg_4"], rules["rule:sgb3_38"]
            assert court.due_date == "2026-10-12"
            receipt = court.computation
            assert (
                receipt is not None and receipt.confidence == "low" and CONFLICTING_DATES in receipt.rule_ids
            )
            [warning] = [w for w in receipt.warnings if "gives two dates for itself" in w]
            assert (
                "Mon 21 Sep 2026" in warning and "Thu 24 Sep 2026" in warning and "Thu 15 Oct 2026" in warning
            )
            assert (
                receipt.steps[-1].rule_id == CONFLICTING_DATES and "The law counts" in receipt.steps[-1].label
            )
            assert needs_check(court) and court.evidence and not court.evidence[0].value_consistent
            assert register.due_date == "2026-09-30" and not needs_check(register)
            assert document.status == "needs_review"

            # once its arrival is confirmed, the law counts from that day: one date, nothing to check
            patched = await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-25"})
            assert patched.status_code == 200
            after = store.get_item(court.id)
            assert after is not None and after.due_date == "2026-10-16"
            assert after.computation is not None and CONFLICTING_DATES not in after.computation.rule_ids
            assert not needs_check(after)
    finally:
        clock.set_today(None)
