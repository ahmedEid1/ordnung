"""Two dates for one obligation: the letter's own text checked for a second deadline statement
(:mod:`ordnung.ingest.conflicts`, SPEC § 8 stage 6, § 21)."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from itertools import product
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import Letter
from helpers_tables import check_rows
from ordnung import clock
from ordnung.api.routes.dates import recompute_document_items
from ordnung.ingest import conflicts
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
    from ordnung.ingest.plan import checked_evidence

    [verified] = read(TWO_DATES, BOX)
    assert verified.evidence.value_consistent  # its own sentence states its date …
    result = computed(verified, company(date(2026, 3, 2)))
    assert not checked_evidence(verified, result).value_consistent  # … but the letter gives another
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


AN_EARLY_PAYMENT_DISCOUNT_DATE_IS_NO_SECOND_DUE_DATE = [
    "Zahlbar bis zum 10.02.2026 abzüglich 2 % Skonto.",
    "Bei Zahlung bis zum 10.02.2026 gewähren wir 2 % Skonto.",
    "Payable by 10 February 2026 less a 2 % discount.",
]


def test_an_early_payment_discount_date_is_no_second_due_date() -> None:
    """Skonto: paying after the discount date is not late, so the net date stays the to-do's date."""

    def check(discount: str) -> None:
        text = f"Musterstadt, 27.01.2026\nZahlbar bis zum 24.02.2026 ohne Abzug.\n{discount}\n"
        net = fixed("Zahlbar bis zum 24.02.2026 ohne Abzug.", "2026-02-24")
        [verified] = read(text, net)
        assert verified.rivals == ()
        result = computed(verified, company(date(2026, 1, 27)))
        assert result.due_date == "2026-02-24" and not result.conflict

    check_rows(AN_EARLY_PAYMENT_DISCOUNT_DATE_IS_NO_SECOND_DUE_DATE, check)


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


AN_INVOICE_HEADERS_OWN_DATE_IS_NO_SECOND_DUE_DATE_HEADERS = [
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
]


AN_INVOICE_HEADERS_OWN_DATE_IS_NO_SECOND_DUE_DATE_LETTER_DATES = [date(2026, 3, 2), None]


def test_an_invoice_headers_own_date_is_no_second_due_date() -> None:
    """The invoice's date stands on its own label: the next label's "Zahlbar", or a payment word of an
    earlier label, is not its — and the letter's own date is never a date to pay by."""

    def check(header: str, own_quote: str, letter_date: date | None) -> None:
        [verified] = read(f"Druckerei Muster GmbH\n{header}\n", fixed(own_quote, "2026-03-16", money=120.0))
        assert verified.rivals == ()
        ctx = RuleContext(
            today=date(2026, 3, 4), document_date=letter_date, private_sender=True, sender_kind="company"
        )
        result = computed(verified, ctx)
        assert result.due_date == "2026-03-16" and not result.conflict

    check_rows(
        [
            (header, own_quote, letter_date)
            for (header, own_quote), letter_date in product(
                AN_INVOICE_HEADERS_OWN_DATE_IS_NO_SECOND_DUE_DATE_HEADERS,
                AN_INVOICE_HEADERS_OWN_DATE_IS_NO_SECOND_DUE_DATE_LETTER_DATES,
            )
        ],
        check,
    )


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


A_DATE_FOR_ANOTHER_KIND_OF_PAYMENT_IS_NOT_A_SECOND_DATE = [
    pytest.param(
        "Stadtwerke, 02.03.2026\nDer Nachzahlungsbetrag von 120,00 EUR ist bis zum 31.03.2026 zu zahlen, "
        "die neuen Abschläge sind monatlich fällig, erstmals am 15.03.2026.\n",
        fixed(
            "Der Nachzahlungsbetrag von 120,00 EUR ist bis zum 31.03.2026 zu zahlen",
            "2026-03-31",
            money=120.0,
        ),
        id="new-instalments",
    ),
    pytest.param(
        "Finanzamt, 02.03.2026\nBitte zahlen Sie die Abschlusszahlung von 1.200,00 EUR bis zum 31.03.2026.\n"
        "Die nächste Vorauszahlung ist fällig am 10.03.2026.\n",
        fixed(
            "Bitte zahlen Sie die Abschlusszahlung von 1.200,00 EUR bis zum 31.03.2026.",
            "2026-03-31",
            money=1200.0,
        ),
        id="next-prepayment",
    ),
    pytest.param(
        "Finanzamt, 02.03.2026\nBitte zahlen Sie die Abschlusszahlung von 1.200,00 EUR bis zum 31.03.2026.\n"
        "Vorauszahlungen: Die Vorauszahlungen sind jeweils fällig am 10.06.2026 und 10.09.2026.\n",
        fixed(
            "Bitte zahlen Sie die Abschlusszahlung von 1.200,00 EUR bis zum 31.03.2026.",
            "2026-03-31",
            money=1200.0,
        ),
        id="prepayment-dates",
    ),
    pytest.param(
        "Versicherung AG, 02.03.2026\n"
        "Der Erstbeitrag von 60,00 EUR ist fällig am 01.04.2026 und wird von Ihrem Konto abgebucht.\n"
        "Bitte zahlen Sie den Restbetrag von 60,00 EUR bis zum 16.03.2026.\n",
        fixed("Bitte zahlen Sie den Restbetrag von 60,00 EUR bis zum 16.03.2026.", "2026-03-16", money=60.0),
        id="first-premium-debited",
    ),
]


def test_a_date_for_another_kind_of_payment_is_not_a_second_date() -> None:
    """Instalments, prepayments, a premium collected by direct debit: the letter's other payments, even
    when the reading did not list them as to-dos."""

    def check(text: str, own: ExtractedItem) -> None:
        [verified] = read(text, own, kind="utility_bill")
        assert verified.rivals == ()
        result = computed(verified, company(date(2026, 3, 2)))
        assert result.due_date == own.date.date and not result.conflict

    check_rows(A_DATE_FOR_ANOTHER_KIND_OF_PAYMENT_IS_NOT_A_SECOND_DATE, check)


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


A_NOTICE_OR_DECLARATION_DATED_TWICE_KEEPS_THE_EARLIER_AND_NEEDS_A_CHECK = [
    pytest.param(
        "Beispiel Versicherung AG, 02.03.2026\n"
        "Bitte reichen Sie die fehlenden Unterlagen bis zum 27.03.2026 ein.\n"
        "Frist für die Unterlagen: 20.03.2026\n",
        fixed(
            "Bitte reichen Sie die fehlenden Unterlagen bis zum 27.03.2026 ein.",
            "2026-03-27",
            nature="declaration",
        ),
        "2026-03-20",
        id="documents-label",
    ),
    pytest.param(
        "Beispiel Versicherung AG, 02.03.2026\n"
        "Bitte senden Sie den ausgefüllten Fragebogen innerhalb von 14 Tagen nach dem Datum dieses "
        "Schreibens zurück.\n"
        "Der Fragebogen muss bis spätestens 23.03.2026 bei uns eingehen.\n",
        fixed(
            "Der Fragebogen muss bis spätestens 23.03.2026 bei uns eingehen.",
            "2026-03-23",
            nature="declaration",
        ),
        "2026-03-16",
        id="questionnaire-period",
    ),
    pytest.param(
        "Studienwerk Muster, 02.03.2026\n"
        "Please return the signed form by 20 March 2026.\n"
        "The form must be received no later than 16 March 2026.\n",
        fixed("Please return the signed form by 20 March 2026.", "2026-03-20", nature="declaration"),
        "2026-03-16",
        id="english-form",
    ),
    pytest.param(
        "Muster Mobilfunk GmbH, 02.03.2026\n"
        "Ihre Kündigung muss uns bis spätestens 30.09.2026 vorliegen.\n"
        "Sie können den Vertrag bis zum 31.08.2026 kündigen.\n",
        fixed("Ihre Kündigung muss uns bis spätestens 30.09.2026 vorliegen.", "2026-09-30", nature="notice"),
        "2026-08-31",
        id="notice",
    ),
]


def test_a_notice_or_declaration_dated_twice_keeps_the_earlier_and_needs_a_check() -> None:
    def check(text: str, own: ExtractedItem, earlier: str) -> None:
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

    check_rows(A_NOTICE_OR_DECLARATION_DATED_TWICE_KEEPS_THE_EARLIER_AND_NEEDS_A_CHECK, check)


DOCUMENTS = fixed(
    "Bitte reichen Sie die fehlenden Unterlagen bis zum 27.03.2026 ein.", "2026-03-27", nature="declaration"
)


A_DECLARATIONS_GUARDS_LEAVE_OUT_WHAT_IS_NO_SECOND_DATE = [
    pytest.param("Die Unterlagen waren ursprünglich bis zum 13.03.2026 einzureichen.", id="past"),
    pytest.param("Wenn möglich, reichen Sie die Unterlagen bis zum 13.03.2026 ein.", id="optional"),
    pytest.param(
        "Künftige Unterlagen reichen Sie bitte jeweils bis zum 15. eines Monats ein, erstmals bis zum 13.03.2026.",
        id="series",
    ),
    pytest.param(
        "Wie mit Schreiben vom 16.02.2026 erbeten, sind die Unterlagen binnen 10 Tagen nach Erhalt unseres "
        "Schreibens einzureichen.",
        id="another-letters-period",
    ),
    pytest.param("Checkliste Unterlagen – Stand: 13.03.2026", id="label-names-no-deadline"),
    pytest.param("Den Fragebogen senden Sie bitte bis zum 13.03.2026 zurück.", id="another-thing"),
]


def test_a_declarations_guards_leave_out_what_is_no_second_date() -> None:
    """Written in the past, optional (as *Skonto* is for a payment), a series, a period from another
    letter, a label that names a date but no deadline, something else to send: none of them dates the
    to-do — the letter's real second date still does."""

    def check(other: str) -> None:
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

    check_rows(A_DECLARATIONS_GUARDS_LEAVE_OUT_WHAT_IS_NO_SECOND_DATE, check)


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
    # the letter's date not read: the original date is still history, before the day it arrived
    undated = replace(company(date(2026, 3, 12)), document_date=None, received_date=date(2026, 3, 12))
    result = computed(verified, undated)
    assert result.due_date == "2026-03-20"
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


A_NOTICES_GUARDS_LEAVE_OUT_ITS_END_AND_ANOTHER_RIGHT = [
    pytest.param(
        "Der Vertrag kann mit einer Frist von drei Monaten zum 31.12.2026 gekündigt werden.",
        id="the-end-it-takes-effect",
    ),
    pytest.param("Ihr Sonderkündigungsrecht können Sie bis zum 31.08.2026 ausüben.", id="a-special-right"),
]


def test_a_notices_guards_leave_out_its_end_and_another_right() -> None:
    """A notice "zum 31.12." names the end it takes effect, not the day it must arrive by; a special
    right to cancel is another obligation than the ordinary notice."""

    def check(other: str) -> None:
        text = (
            "Muster Mobilfunk GmbH, 02.03.2026\n"
            "Ihre Kündigung muss uns bis spätestens 30.09.2026 vorliegen.\n"
            f"{other}\n"
            "Kündigungen müssen bis zum 15.09.2026 bei uns eingehen.\n"
        )
        own = fixed(
            "Ihre Kündigung muss uns bis spätestens 30.09.2026 vorliegen.", "2026-09-30", nature="notice"
        )
        [verified] = read(text, own, kind="contract")
        result = computed(verified, company(date(2026, 3, 2)))
        assert result.due_date == "2026-09-15" and result.conflict
        [warning] = _two_dates(result)
        assert "Tue 15 Sep 2026" in warning and "Wed 30 Sep 2026" in warning

    check_rows(A_NOTICES_GUARDS_LEAVE_OUT_ITS_END_AND_ANOTHER_RIGHT, check)


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


A_HEADER_DATE_AFTER_THE_ONE_READ_IS_NAMED_AND_THE_EARLIER_DATE_KEPT = [
    "Datum: 16.03.2026",
    "Steuernummer 123/456/78901 · Datum: Montag, 16.03.2026",
    "Datum\n16.03.2026",
    "Datum   16.03.2026",
    "Date: 16 March 2026",
]


def test_a_header_date_after_the_one_read_is_named_and_the_earlier_date_kept() -> None:
    """The reading took the decision's date in the text (12 Mar) as the letter's; its header says 16 Mar.
    The date counted from 12 Mar is already the earlier: it stays, but the letter contradicts itself, so
    it is named and the to-do is "Please check"."""

    def check(header: str) -> None:
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

    check_rows(A_HEADER_DATE_AFTER_THE_ONE_READ_IS_NAMED_AND_THE_EARLIER_DATE_KEPT, check)


A_DATE_IN_THE_LETTERS_BODY_IS_NOT_ITS_OWN_DATE = [
    "Bescheid   Datum\nVorauszahlungen   02.03.2026",
    "Bescheid über Vorauszahlungen · Datum: 02.03.2026",
]


def test_a_date_in_the_letters_body_is_not_its_own_date() -> None:
    """Only the header's label counts — never a "Datum" in the letter's body (a table of earlier
    decisions, the old invoice a reminder lists), which would count the period from long before."""

    def check(table: str) -> None:
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

    check_rows(A_DATE_IN_THE_LETTERS_BODY_IS_NOT_ITS_OWN_DATE, check)


def test_only_the_first_header_date_that_reads_one_way_is_the_letters() -> None:
    def header_dates(header: str) -> list[date | None]:
        page = (1, f"Studienwerk Muster\n{header}\nDear Ms Muster,\nThank you.\n", [], "text")
        return [statement.letter_date for statement in letter_statements([page]) if statement.letter_date]

    assert header_dates("Date: 16/03/2026") == [date(2026, 3, 16)]
    assert header_dates("Date: 07/08/2026") == []  # 7 Aug or 8 Jul: it can't be told
    assert header_dates("Date: 16/03/2026\nDate: 18/03/2026") == [date(2026, 3, 16)]


# --------------------------------------------------------------------------------------------------
# the widened check: what must never be a second date
# --------------------------------------------------------------------------------------------------


def _alone(verified: VerifiedItem, ctx: RuleContext) -> ComputedDate:
    """The to-do's date as the reading gives it, without the letter's other statements."""
    return computed(VerifiedItem(verified.item, verified.evidence, verified.reasons, verified.slot_key), ctx)


HOW_LONG_A_DOCUMENT_IS_VALID_OR_AN_OPTIONAL_DAY_IS_NO_SECOND_SEND_BY_DATE = [
    pytest.param(
        "Die Schulbescheinigung Ihres Kindes gilt nur bis zum 30.09.2026. Bitte reichen Sie eine aktuelle "
        "Schulbescheinigung bis zum 31.10.2026 ein.",
        "Bitte reichen Sie eine aktuelle Schulbescheinigung bis zum 31.10.2026 ein.",
        "2026-10-31",
        id="certificate-valid-until",
    ),
    pytest.param(
        "Ihr Nachweis über die Krankenversicherung ist bis zum 30.09.2026 gültig. Bitte legen Sie uns einen "
        "neuen Nachweis bis zum 31.10.2026 vor.",
        "Bitte legen Sie uns einen neuen Nachweis bis zum 31.10.2026 vor.",
        "2026-10-31",
        id="proof-valid-until",
    ),
    pytest.param(
        "Ihre Arbeitsunfähigkeitsbescheinigung gilt bis zum 15.09.2026.\n"
        "Bitte reichen Sie die fehlenden Unterlagen bis zum 30.09.2026 ein.",
        "Bitte reichen Sie die fehlenden Unterlagen bis zum 30.09.2026 ein.",
        "2026-09-30",
        id="sick-note-valid-until",
    ),
    pytest.param(
        "Bitte reichen Sie die fehlenden Unterlagen bis zum 30.09.2026 ein.\n"
        "Unterlagen, die bis zum 15.09.2026 eingehen, bearbeiten wir noch im September.",
        "Bitte reichen Sie die fehlenden Unterlagen bis zum 30.09.2026 ein.",
        "2026-09-30",
        id="handled-first",
    ),
    pytest.param(
        "Bitte reichen Sie Ihre Steuererklärung bis zum 31.07.2026 ein.\n"
        "Wird die Erklärung von einem Steuerberater erstellt, verlängert sich die Abgabefrist bis zum "
        "01.03.2027.",
        "Bitte reichen Sie Ihre Steuererklärung bis zum 31.07.2026 ein.",
        "2026-07-31",
        id="adviser",
    ),
]


def test_how_long_a_document_is_valid_or_an_optional_day_is_no_second_send_by_date() -> None:
    """A certificate's validity, an earlier day documents are handled by, the longer period with
    a tax adviser — none is a second day to send the documents by."""

    def check(text: str, quote: str, due: str) -> None:
        own = fixed(quote, due, nature="declaration")
        [verified] = read(f"Familienkasse Musterstadt, 01.09.2026\n{text}\n", own, kind="authority_letter")
        assert verified.rivals == ()
        result = computed(verified, company(date(2026, 9, 1)))
        assert result.due_date == due and not result.conflict

    check_rows(HOW_LONG_A_DOCUMENT_IS_VALID_OR_AN_OPTIONAL_DAY_IS_NO_SECOND_SEND_BY_DATE, check)


CANCEL_BY = "Ihre Kündigung muss uns bis zum 30.09.2026 vorliegen."


A_CONTRACTS_TERM_OR_SERVICE_END_IS_NO_SECOND_CANCELLATION_DEADLINE = [
    pytest.param(
        f"{CANCEL_BY}\nDer Versicherungsschutz besteht bis zum 31.12.2026, wenn Sie kündigen.",
        CANCEL_BY,
        id="cover-lasts",
    ),
    pytest.param(
        f"{CANCEL_BY}\nBei Kündigung werden Sie bis zum 31.12.2026 weiter beliefert.",
        CANCEL_BY,
        id="supply-goes-on",
    ),
    pytest.param(
        f"{CANCEL_BY}\nNach Ihrer Kündigung können Sie das Studio bis zum 31.12.2026 weiter nutzen.",
        CANCEL_BY,
        id="use-goes-on",
    ),
    pytest.param(
        "Your cancellation must reach us by 30 September 2026.\n"
        "If you cancel, your service continues until 31 December 2026.",
        "Your cancellation must reach us by 30 September 2026.",
        id="service-continues",
    ),
    pytest.param(
        "Your cancellation must reach us by 30 September 2026.\n"
        "Your contract runs until 31 December 2026 and will then terminate automatically.",
        "Your cancellation must reach us by 30 September 2026.",
        id="contract-runs",
    ),
    pytest.param(
        f"{CANCEL_BY}\nIhr Preis ist bis zum 31.03.2027 garantiert und kann bis dahin nicht gekündigt werden.",
        CANCEL_BY,
        id="price-guaranteed",
    ),
    pytest.param(
        "Ihr Vertrag läuft bis zum 31.12.2026; eine Kündigung muss bis zum 30.09.2026 bei uns eingehen.",
        "eine Kündigung muss bis zum 30.09.2026 bei uns eingehen",
        id="term-then-notice",
    ),
    pytest.param(
        "Wenn Sie nicht bis zum 30.09.2026 kündigen, verlängert sich der Vertrag bis zum 30.09.2027.",
        "Wenn Sie nicht bis zum 30.09.2026 kündigen",
        id="renewal",
    ),
    pytest.param(
        "Mindestlaufzeit bis 31.12.2026, Kündigung bis 30.09.2026",
        "Kündigung bis 30.09.2026",
        id="minimum-term",
    ),
]


def test_a_contracts_term_or_service_end_is_no_second_cancellation_deadline() -> None:
    """How long cover, supply, a term or a price lasts — even in a sentence that speaks of
    cancelling — is not the day a cancellation must arrive by."""

    def check(text: str, quote: str) -> None:
        own = fixed(quote, "2026-09-30", nature="notice")
        [verified] = read(f"Muster Versicherung AG, 01.06.2026\n{text}\n", own, kind="contract")
        assert verified.rivals == ()
        result = computed(verified, company(date(2026, 6, 1)))
        assert result.due_date == "2026-09-30" and not result.conflict

    check_rows(A_CONTRACTS_TERM_OR_SERVICE_END_IS_NO_SECOND_CANCELLATION_DEADLINE, check)


def _box(text: str, x0: float, y0: float) -> list[Any]:
    """A word's box on a page (text, x0, y0, x1, y1), one character ≈ 0.01 of the page wide."""
    return [text, x0, y0, x0 + 0.01 * len(text), y0 + 0.012]


def test_an_old_invoices_date_in_a_reminders_table_is_not_its_own() -> None:
    """A reminder dated in its first line ("Musterstadt, 01.09.2026", no salutation) lists the
    invoice in a table — "Rechnungsnummer | Datum" over "RE-2026-123 | 14.07.2026". Counted from that
    date, the payment "7 Tage nach Zugang dieses Schreibens" was due on 21 Jul, before the letter itself."""
    quote = "Bitte zahlen Sie den Betrag innerhalb von 7 Tagen nach Zugang dieses Schreibens."
    text = (
        "Inkasso Muster GmbH\nMusterstadt, 01.09.2026\nRechnungsnummer | Datum\nRE-2026-123 | 14.07.2026\n"
        f"Offener Betrag 120,00 EUR. {quote}\n"
    )
    own = item(quote, money=120.0, type="relative", amount=7, unit="days", anchor="receipt", nature="payment")
    words = [_box("Datum", 0.4, 0.30), _box("14.07.2026", 0.4, 0.32)]
    reading = DocumentExtraction(kind="dunning", title="Letter", summary="s", explanation="e", items=[own])
    [verified] = verify_extraction("doc_x", reading, [(1, text, words, "text")]).items
    assert not any(rival.letter_date for rival in verified.rivals)
    ctx = replace(company(date(2026, 9, 1)), letter_kind="dunning")
    result = computed(verified, ctx)
    assert result.due_date == "2026-09-08" and not result.conflict


ANOTHER_DECISIONS_OR_AN_OFFENCES_DATE_IS_NOT_THE_LETTERS = [
    pytest.param(
        "Datum des Bescheids: 10.08.2026\nDatum: 25.09.2026",
        date(2026, 9, 25),
        "vwvfg",
        id="the-decision-ruled-on",
    ),
    pytest.param(
        "Datum: 28.08.2026\nTatort: Hauptstraße 5   Datum: 14.08.2026   Uhrzeit: 14:32",
        date(2026, 8, 28),
        "vwvfg",
        id="an-offence-after-the-header",
    ),
    pytest.param(
        "Tatort: Hauptstraße 5   Datum: 14.08.2026   Uhrzeit: 14:32",
        date(2026, 8, 28),
        "vwvfg",
        id="an-offence-in-the-header",
    ),
]


def test_another_decisions_or_an_offences_date_is_not_the_letters() -> None:
    """A Widerspruchsbescheid's "Datum des Bescheids" names the decision it rules on; a
    fine's "Tatort … Datum … Uhrzeit" names the offence. Counted from either, the Klage or the Einspruch was
    weeks too early."""

    def check(header: str, letter: date, scope: str) -> None:
        text = (
            f"Landratsamt Musterkreis\n{header}\n"
            "Sehr geehrte Damen und Herren,\n"
            "Einspruch ist binnen eines Monats nach Bekanntgabe möglich.\n"
        )
        [verified] = read(text, INTEREST_OBJECTION, kind="authority_letter")
        ctx = RuleContext(today=letter, document_date=letter, delivery_scope=scope)
        result = computed(verified, ctx)
        assert result.due_date == _alone(verified, ctx).due_date and not result.conflict

    check_rows(ANOTHER_DECISIONS_OR_AN_OFFENCES_DATE_IS_NOT_THE_LETTERS, check)


def test_a_claims_table_in_a_court_order_is_not_its_date_for_the_laws_deadline() -> None:
    """A Mahnbescheid without a salutation lists the claim "Kaufvertrag   500,00 EUR
    12.03.2026" under "Hauptforderung   Betrag   Datum" — the date is in the column, but it is the
    contract's: the § 692 ZPO deadline still counts from the letter's own date."""
    from ordnung.ingest.conflicts import law_rivals, settle_law
    from ordnung.rules import compute_due
    from ordnung.rules.routing import derived_deadlines

    text = (
        "Amtsgericht Hagen - Zentrales Mahngericht\nMahnbescheid\nHagen, 01.09.2026\n"
        "Hauptforderung   Betrag   Datum\nKaufvertrag   500,00 EUR   12.03.2026\n"
        "Sie können binnen zwei Wochen seit der Zustellung Widerspruch erheben.\n"
    )
    words = [_box("Datum", 0.7, 0.30), _box("12.03.2026", 0.7, 0.32)]
    [order] = derived_deadlines("court_payment_order", end=None, letter_date=date(2026, 9, 1))
    ctx = RuleContext(today=date(2026, 9, 2), document_date=date(2026, 9, 1), court=True)
    rivals = law_rivals(order.spec, [(1, text, words, "text")])
    receipt = compute_due(order.spec, ctx, postal_buffer_days=BUFFER)
    assert rivals == () and settle_law(receipt, order.spec, rivals, ctx, postal_buffer_days=BUFFER) is None


A_DATE_NEAR_THE_HEADER_LABEL_THAT_IS_NOT_ITS_VALUE_IS_NOT_THE_LETTERS = [
    pytest.param("Ihr Termin / Datum: 20.10.2026", [], id="appointment"),
    pytest.param("Ihr Termin   Datum: 20.10.2026", [], id="appointment-column"),
    pytest.param(
        "Zustelldatum   Datum\n15.09.2026",
        [_box("Zustelldatum", 0.1, 0.2), _box("Datum", 0.6, 0.2), _box("15.09.2026", 0.1, 0.22)],
        id="another-column",
    ),
    pytest.param("Zustelldatum   Datum\n15.09.2026", [], id="no-boxes"),
    pytest.param(
        "Datum\nIhr Schreiben vom 15.09.2026",
        [_box("Datum", 0.6, 0.2), _box("15.09.2026", 0.6, 0.22)],
        id="after-vom",
    ),
    pytest.param(
        "Datum\n15.09.2026 Eingang",
        [_box("Datum", 0.6, 0.2), _box("15.09.2026", 0.6, 0.22)],
        id="not-ending-its-line",
    ),
]


def test_a_date_near_the_header_label_that_is_not_its_value_is_not_the_letters() -> None:
    """An appointment's date, a date under another column, after "vom" or not
    ending the label's next line is never read as the letter's own date."""

    def check(header: str, words: list[Any]) -> None:
        page = (1, f"Stadt Musterstadt\n{header}\nSehr geehrte Damen und Herren,\nDanke.\n", words, "text")
        assert [statement for statement in letter_statements([page]) if statement.letter_date] == []

    check_rows(A_DATE_NEAR_THE_HEADER_LABEL_THAT_IS_NOT_ITS_VALUE_IS_NOT_THE_LETTERS, check)


def test_a_column_label_with_its_value_right_under_it_is_the_letters_date() -> None:
    """The column layout of a printed letter: "… 44135 Musterstadt   Datum" over "Lindenweg 12   27.03.2026",
    the date right under the label on the page — and its evidence quotes the page's own line."""
    page = (
        1,
        "Stadt Musterstadt · Rathausplatz 1 · 44135 Musterstadt   Datum\nLindenweg 12   27.03.2026\n"
        "Sehr geehrte Damen und Herren,\nDanke.\n",
        [_box("Datum", 0.7, 0.2), _box("27.03.2026", 0.7, 0.22)],
        "text",
    )
    [header] = [statement for statement in letter_statements([page]) if statement.letter_date]
    assert header.letter_date == date(2026, 3, 27) and header.quote == "Lindenweg 12 27.03.2026"


def test_a_header_ends_at_the_letters_first_sentence_without_a_salutation() -> None:
    """A letter without a salutation — its header ends with its first sentence, so a
    "Datum:" after it (a receipt it confirms) is not the letter's date."""
    page = (
        1,
        "Stadtwerke Musterstadt\nKundennummer 4711\nWir bestätigen den Eingang Ihrer Unterlagen. Vielen Dank.\n"
        "Datum: 15.09.2026\n",
        [],
        "text",
    )
    assert [statement for statement in letter_statements([page]) if statement.letter_date] == []
    page = (
        1,
        "Stadtwerke Musterstadt\nDatum: 15.09.2026\nWir bestätigen den Eingang Ihrer Unterlagen.\n",
        [],
        "text",
    )
    assert [statement.letter_date for statement in letter_statements([page]) if statement.letter_date] == [
        date(2026, 9, 15)
    ]


def test_an_optional_day_in_the_to_dos_own_sentence_leaves_the_date_to_the_reading() -> None:
    """A "möglichst bis" in the to-do's own sentence: which date must be met is the reading's to
    tell, so the letter's other date is no rival."""
    quote = "Bitte reichen Sie die fehlenden Unterlagen möglichst bis zum 20.03.2026 ein."
    text = f"Beispiel Versicherung AG, 02.03.2026\n{quote}\nFrist für die Unterlagen: 27.03.2026\n"
    [verified] = read(text, fixed(quote, "2026-03-20", nature="declaration"), kind="other")
    assert verified.rivals == ()
    assert not computed(verified, company(date(2026, 3, 2))).conflict


def test_a_letter_date_far_from_the_one_read_or_a_date_before_the_letter_is_never_kept() -> None:
    """A date the letter gives for itself weeks from the one read is another's; and no rival
    ever moves a date before the letter's own date as read."""
    text = (
        "Finanzamt Musterstadt\nDatum: 16.02.2026\nSehr geehrte Damen und Herren,\n"
        "Einspruch ist binnen eines Monats nach Bekanntgabe möglich.\n"
    )
    [verified] = read(text, INTEREST_OBJECTION, kind="tax_assessment")
    assert {rival.letter_date for rival in verified.rivals} == {date(2026, 2, 16)}
    result = computed(verified, _tax_office(date(2026, 3, 12)))  # 24 days apart: not the letter's
    assert result.due_date == "2026-04-16" and not result.conflict

    quote = "Bitte zahlen Sie innerhalb von 3 Tagen nach dem Datum dieses Schreibens."
    text = f"Muster GmbH\nDatum: 02.03.2026\nSehr geehrte Damen und Herren,\n{quote}\n"
    own = item(quote, type="relative", amount=3, unit="days", anchor="document_date", nature="payment")
    [verified] = read(text, own)
    assert {rival.letter_date for rival in verified.rivals} == {date(2026, 3, 2)}
    result = computed(verified, company(date(2026, 3, 12)))  # from 2 Mar: Thu 5 Mar, before the letter
    assert result.due_date == "2026-03-16" and not result.conflict


A_DECLARATION_DATE_WITHOUT_THE_ACT_IT_IS_THE_LAST_DAY_FOR_IS_NO_RIVAL = [
    pytest.param(
        "Die Bescheinigungen, die Sie einreichen, müssen bis zum 30.09.2026 gültig sein.",
        "Bitte reichen Sie die Bescheinigungen bis zum 31.10.2026 ein.",
        {"type": "fixed", "date": "2026-10-31"},
        id="valid-until",
    ),
    pytest.param(
        "Wir benötigen die Unterlagen für die Zeit bis zum 15.09.2026.",
        "Bitte reichen Sie die Unterlagen bis zum 31.10.2026 ein.",
        {"type": "fixed", "date": "2026-10-31"},
        id="covers-until",
    ),
    pytest.param(
        "Unterlagen, die Sie einreichen, bleiben 6 Monate nach Zugang dieses Schreibens gültig.",
        "Bitte reichen Sie die Unterlagen innerhalb von 4 Wochen nach Zugang dieses Schreibens ein.",
        {"type": "relative", "amount": 4, "unit": "weeks", "anchor": "receipt"},
        id="valid-for-a-period",
    ),
    pytest.param(
        "Wir prüfen die Unterlagen innerhalb von 10 Tagen nach Zugang dieses Schreibens.",
        "Bitte reichen Sie die Unterlagen innerhalb von 4 Wochen nach Zugang dieses Schreibens ein.",
        {"type": "relative", "amount": 4, "unit": "weeks", "anchor": "receipt"},
        id="checked-within",
    ),
]


def test_a_declaration_date_without_the_act_it_is_the_last_day_for_is_no_rival() -> None:
    def check(other: str, quote: str, spec: dict[str, Any]) -> None:
        own = item(quote, kind="deadline", nature="declaration", **spec)
        [verified] = read(
            f"Familienkasse Musterstadt, 01.09.2026\n{quote}\n{other}\n", own, kind="authority_letter"
        )
        assert verified.rivals == ()

    check_rows(A_DECLARATION_DATE_WITHOUT_THE_ACT_IT_IS_THE_LAST_DAY_FOR_IS_NO_RIVAL, check)


def test_a_cancellation_named_after_the_date_in_another_clause_is_no_notice_deadline() -> None:
    """ "Bitte senden Sie uns die Geräte bis zum 31.12.2026 zurück, wenn Sie gekündigt haben": the date is
    for the devices, the cancellation only its condition."""
    text = (
        f"Muster Kabel GmbH, 01.06.2026\n{CANCEL_BY}\n"
        "Bitte senden Sie uns die Geräte bis zum 31.12.2026 zurück, wenn Sie gekündigt haben.\n"
    )
    [verified] = read(text, fixed(CANCEL_BY, "2026-09-30", nature="notice"), kind="contract")
    assert verified.rivals == ()


A_TABLES_OR_AN_APPOINTMENTS_DATE_COLUMN_IS_NOT_THE_LETTERS_DATE = [
    pytest.param(
        "Muster GmbH\nArtikel   Menge   Preis\nKabel   2   10,00 EUR\nDatum: 05.09.2026\n",
        [],
        id="after-a-table",
    ),
    pytest.param(
        "Muster GmbH\nRechnung   Betrag   Datum\nRE-1   120,00 EUR   05.09.2026\nSehr geehrte Damen und Herren,\n",
        [_box("Datum", 0.7, 0.2), _box("05.09.2026", 0.7, 0.22)],
        id="table-column",
    ),
    pytest.param(
        "Muster GmbH\nIhr Termin   Datum\n10:30 Uhr   20.10.2026\nSehr geehrte Damen und Herren,\n",
        [_box("Datum", 0.7, 0.2), _box("20.10.2026", 0.7, 0.22)],
        id="appointment-column",
    ),
]


def test_a_tables_or_an_appointments_date_column_is_not_the_letters_date() -> None:
    def check(text: str, words: list[Any]) -> None:
        assert [
            statement for statement in letter_statements([(1, text, words, "text")]) if statement.letter_date
        ] == []

    check_rows(A_TABLES_OR_AN_APPOINTMENTS_DATE_COLUMN_IS_NOT_THE_LETTERS_DATE, check)


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

            # recomputing the letter's dates (a changed region or postal buffer) keeps the earlier, still flagged
            recompute_document_items(store, document, date(2026, 9, 26))
            again = store.get_item(court.id)
            assert again is not None and again.due_date == "2026-10-12" and needs_check(again)
            assert again.computation is not None and CONFLICTING_DATES in again.computation.rule_ids

            # the person corrects the letter's date to the one in its text: one date, nothing to check
            patched = await api.client.patch(f"/api/documents/{doc_id}", json={"doc_date": "2026-09-21"})
            assert patched.status_code == 200
            corrected = store.get_item(court.id)
            assert corrected is not None and corrected.due_date == "2026-10-12" and not needs_check(corrected)
            assert (
                corrected.computation is not None and CONFLICTING_DATES not in corrected.computation.rule_ids
            )

            # once its arrival is confirmed, the law counts from that day: one date, nothing to check
            patched = await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-25"})
            assert patched.status_code == 200
            after = store.get_item(court.id)
            assert after is not None and after.due_date == "2026-10-16"
            assert after.computation is not None and CONFLICTING_DATES not in after.computation.rule_ids
            assert not needs_check(after)
    finally:
        clock.set_today(None)


# --------------------------------------------------------------------------------------------------
# How a decision names its own date, and how it names another's
# --------------------------------------------------------------------------------------------------


def _own_dates(sentence: str, *, above: str = "") -> list[date]:
    """The dates a made-up letter of the Stadt Musterstadt gives for itself in its text (its header has none)."""
    page = (1, f"Stadt Musterstadt\nSehr geehrte Frau Beispiel,\n{above}{sentence}\n", [], "text")
    return [statement.letter_date for statement in letter_statements([page]) if statement.letter_date]


#: The one form that counts as a decision naming its own date (``conflicts._own_decision``), one row for each of its
#: listed verbs and words. A "|" marks where the form is complete (right after the speaker: the sentence is not
#: read further); every word before it stands in one of the form's places, and those places are walked by
#: test_an_unlisted_word_in_any_place_of_the_form_refuses_it.
FORMS_THAT_COUNT = [
    pytest.param(
        "Mit Bescheid vom 09.06.2026 entscheiden wir| über Ihren Antrag wie folgt:", id="entscheiden"
    ),
    pytest.param("Mit Bescheid vom 09.06.2026 setzen wir| die Gebühr auf 80,00 EUR fest.", id="setzen"),
    pytest.param("Mit dem Bescheid vom 09.06.2026 lehnen wir| Ihren Antrag ab.", id="lehnen-mit-dem"),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 bewilligen wir| Ihnen Wohngeld für zwölf Monate.", id="bewilligen"
    ),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 gewähren wir| Ihnen einen Zuschuss von 300,00 EUR.", id="gewaehren"
    ),
    pytest.param("Mit Bescheid vom 09.06.2026 fordern wir| 120,00 EUR zurück.", id="fordern"),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 erheben wir| eine Verwaltungsgebühr von 25,00 EUR.", id="erheben"
    ),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 stellen wir| fest, dass die Erlaubnis erloschen ist.", id="stellen"
    ),
    pytest.param(
        "Mit Schreiben vom 09.06.2026 teilen wir| Ihnen mit, dass die Gebühr fällig ist.",
        id="teilen-schreiben",
    ),
    pytest.param("Mit Bescheid vom 09.06.2026 ändern wir| die Festsetzung der Hundesteuer.", id="aendern"),
    pytest.param("Mit Bescheid vom 09.06.2026 heben wir| die Festsetzung vom Mai auf.", id="heben"),
    pytest.param("Mit Bescheid vom 09.06.2026 erstatten wir| Ihnen 40,00 EUR.", id="erstatten"),
    pytest.param("Mit Bescheid vom 09.06.2026 erlassen wir| die Säumniszuschläge.", id="erlassen"),
    pytest.param(
        "Mit dem Schreiben vom 09.06.2026 bestätigen wir| die Abmeldung Ihres Hundes.",
        id="bestaetigen-mit-dem",
    ),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 weisen wir| Ihren Widerspruch als unbegründet zurück.", id="weisen"
    ),
    pytest.param("Mit Bescheid vom 09.06.2026 ordnen wir| die Beseitigung des Containers an.", id="ordnen"),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 verpflichten wir| Sie, den Zaun zu entfernen.", id="verpflichten"
    ),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 untersagen wir| Ihnen das Abstellen des Anhängers.", id="untersagen"
    ),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 widerrufen wir| die Erlaubnis zur Sondernutzung.", id="widerrufen"
    ),
    pytest.param("Mit Bescheid vom 09.06.2026 nehmen wir| die Bewilligung zurück.", id="nehmen"),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 berichtigen wir| die Festsetzung der Gebühr.", id="berichtigen"
    ),
    pytest.param("Mit Bescheid vom 09.06.2026 versagen wir| die beantragte Leistung.", id="versagen"),
    pytest.param("Mit Bescheid vom 09.06.2026 entziehen wir| Ihnen die Erlaubnis.", id="entziehen"),
    pytest.param("Mit Bescheid vom 09.06.2026 erteilen wir| Ihnen die Genehmigung.", id="erteilen"),
    pytest.param("Mit Bescheid vom 09.06.2026 genehmigen wir| den Umbau des Carports.", id="genehmigen"),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 erhöhen wir| die Vorauszahlungen auf 60,00 EUR.", id="erhoehen"
    ),
    pytest.param("Mit Bescheid vom 09.06.2026 mindern wir| den Beitrag auf 30,00 EUR.", id="mindern"),
    pytest.param("Mit Bescheid vom 09.06.2026 senken wir| die Gebühr auf 50,00 EUR.", id="senken"),
    pytest.param("Mit Bescheid vom 09.06.2026 stunden wir| die Forderung bis zum Jahresende.", id="stunden"),
    pytest.param("Mit Bescheid vom 09.06.2026 verlängern wir| die Erlaubnis um ein Jahr.", id="verlaengern"),
    pytest.param(
        "mit Bescheid vom 09.06.2026 setzen wir| den Beitrag neu fest.", id="lower-case-after-the-salutation"
    ),
    pytest.param("Mit Bescheid vom 9. Juni 2026 setzen wir| die Gebühr fest.", id="month-name"),
]


def _as_ich(marked: str) -> str:
    """The same row as a head of office writes it: "setzen wir" → "setze ich"."""
    for verb, own in zip(conflicts._DECISION_VERBS, conflicts._DECISION_VERBS_I, strict=True):
        if f" {verb} wir|" in marked:
            return marked.replace(f" {verb} wir|", f" {own} ich|")
    raise AssertionError(marked)


def test_the_form_that_counts_is_a_date_the_letter_gives_for_itself() -> None:
    def check(marked: str) -> None:
        for sentence in (marked, _as_ich(marked)):
            assert _own_dates(sentence.replace("|", "")) == [date(2026, 6, 9)], sentence

    check_rows(FORMS_THAT_COUNT, check)


#: The 14 verbs this check has always read, with "wir".
MAIN_VERBS = (
    "entscheiden", "setzen", "lehnen", "bewilligen", "gewähren", "fordern", "erheben", "stellen", "teilen",
    "ändern", "heben", "erstatten", "erlassen", "bestätigen",
)  # fmt: skip
#: The verbs read beyond those, and why: they are the other regulating verbs of administrative German, chosen as a
#: rule of the language, not for any one letter (no row and no measured letter needs them more than that). Their rows
#: in FORMS_THAT_COUNT show each one counts as written, so a misspelt entry fails; they are not what justifies it.
REGULATING_VERBS = (
    "weisen", "ordnen", "verpflichten", "untersagen", "widerrufen", "nehmen", "berichtigen", "versagen", "entziehen",
    "erteilen", "genehmigen", "erhöhen", "mindern", "senken", "stunden", "verlängern",
)  # fmt: skip


def test_the_forms_lists_are_these_words() -> None:
    """The form's lists and patterns are pinned word for word, so widening one is a reviewed edit of this test. The
    speaker "ich" is read beside "wir" because an authority headed by one person decides in the first person singular
    (the code's comment on ``_DECISION_VERBS_I``); each speaker takes its own verb forms only."""
    assert conflicts._DECISION_VERBS == MAIN_VERBS + REGULATING_VERBS
    assert set(conflicts._SPEAKER_VERBS) == {"wir", "ich"}
    assert conflicts._SPEAKER_VERBS["wir"] == set(conflicts._DECISION_VERBS)
    assert conflicts._SPEAKER_VERBS["ich"] == set(conflicts._DECISION_VERBS_I)
    assert not set(conflicts._DECISION_VERBS) & set(conflicts._DECISION_VERBS_I)  # "setze wir" never counts
    assert conflicts._OWN_CUE.pattern == r"\bmit\s+(?:dem\s+)?(?:bescheid|schreiben)\s+vom\s*$"
    assert conflicts._OWN_VERB.pattern == r"[ \t]+(?P<verb>[^\W\d_]+)[ \t]+(?P<speaker>[^\W\d_]+)\b"
    assert conflicts._SENTENCE_ENDED.pattern == r"(?:(?<![^\W\d_])[^\W\d_]{4,}\.|[!?])[ \t]*\n?[ \t]*$"
    assert conflicts._SALUTATION_ENDS.pattern == r"(?:^|\n)[ \t]*(?P<salutation>[^\n,]*),[ \t]*\n?[ \t]*$"
    assert conflicts._FIELD_LINE.pattern == (
        r"(?:^|\n)[ \t]*(?:[A-ZÄÖÜ][a-zäöüß]+[ \t]+|(?:[^\n]*·[ \t]*)?(?:Datum|Date):[ \t]*)(?P<value>\d[^\n]*?)"
        r"[ \t]*\n[ \t]*$"
    )
    rows = [row.values[0] for row in FORMS_THAT_COUNT]
    for verb in conflicts._DECISION_VERBS:
        assert any(f" {verb} wir|" in row for row in rows), verb
    assert any(row.startswith("Mit dem Bescheid") for row in rows)
    assert any(row.startswith("Mit dem Schreiben") for row in rows)
    assert any(row.startswith("Mit Schreiben") for row in rows)


def _page_dates(*pages: str) -> list[date]:
    """The dates a made-up upload of these pages gives for the letter itself."""
    read = [(number, text, [], "text") for number, text in enumerate(pages, 1)]
    return [statement.letter_date for statement in letter_statements(read) if statement.letter_date]


#: Made-up pages on which the form opens where it may (``conflicts._opens``): the page's first words, a capital after
#: a sentence's end ("." after a word, "!" or "?"), the salutation's comma (the salutation alone on its line, on the
#: same line as the form or the line above), and the line under a header's "Datum:" field or a table's row of one
#: word and a date. Each gives 09.06.2026 for the letter itself.
PLACES_THAT_COUNT = [
    pytest.param("Mit Bescheid vom 09.06.2026 setzen wir die Gebühr fest.", id="the-pages-first-words"),
    pytest.param(
        "Stadt Musterstadt\nSehr geehrte Frau Beispiel, mit Bescheid vom 09.06.2026 setzen wir die Gebühr fest.",
        id="salutation-same-line",
    ),
    pytest.param(
        "Stadt Musterstadt\nSehr geehrte Frau Dr. Beispiel,\nmit Bescheid vom 09.06.2026 lehne ich den Antrag ab.",
        id="salutation-with-an-abbreviation",
    ),
    pytest.param(
        "Stadt Musterstadt\nSehr geehrte Damen und Herren,\nMit Bescheid vom 09.06.2026 setzen wir die Gebühr fest.",
        id="salutation-then-a-capital",
    ),
    pytest.param(
        "Stadt Musterstadt\nGuten Tag Herr Muster,\nmit Schreiben vom 09.06.2026 teilen wir Ihnen die Höhe mit.",
        id="guten-tag",
    ),
    pytest.param(
        "Stadt Musterstadt\nSehr geehrte Frau Beispiel,\nwir schreiben wegen der Hundesteuer. Mit Bescheid vom "
        "09.06.2026 setzen wir die Steuer fest.",
        id="after-a-sentence",
    ),
    pytest.param(
        "Stadt Musterstadt\nSehr geehrte Frau Beispiel,\nIhr Antrag ist vollständig.\nMit Bescheid vom "
        "09.06.2026 bewillige ich das Wohngeld.",
        id="after-a-sentence-on-the-line-above",
    ),
    pytest.param(
        "Stadt Musterstadt\nSehr geehrte Frau Beispiel,\nwas ändert sich? Mit Bescheid vom 09.06.2026 senken wir "
        "die Gebühr.",
        id="after-a-question",
    ),
    pytest.param(
        "Stadt Musterstadt · Ordnungsamt\nDatum: 09.06.2026\nMit Bescheid vom 09.06.2026 setzen wir die Gebühr fest.",
        id="under-the-headers-datum",
    ),
    pytest.param(
        "Stadt Musterstadt\nSehr geehrte Damen und Herren,\nBescheid Datum\nVorauszahlungen   02.03.2026\n"
        "mit Bescheid vom 09.06.2026 setzen wir Zinsen fest.",
        id="under-a-table-row",
    ),
    pytest.param(
        "Stadt Musterstadt\nSehr geehrte Damen und Herren,\nBescheid über Vorauszahlungen · Datum: 02.03.2026\n"
        "mit Bescheid vom 09.06.2026 setzen wir Zinsen fest.",
        id="under-a-fields-datum",
    ),
]


def test_the_form_opens_only_where_its_sentence_starts() -> None:
    check_rows(PLACES_THAT_COUNT, lambda page: _assert_in(date(2026, 6, 9), _page_dates(page)))


def _assert_in(day: date, found: list[date]) -> None:
    assert day in found


def _assert_not_in(day: date, found: list[date]) -> None:
    assert day not in found


#: Made-up pages on which "Mit Bescheid vom D <listed verb> wir / ich" stands where the form does not open, and D is
#: another decision's or letter's date (09.06.2026 or 02.03.2026, never the letter's own): the reviews' rows. A line
#: of nouns ending in a number, a label of another kind, a line ending in ":" (a quotation's lead-in), a heading, a
#: list's mark, an abbreviation's full stop, ";", words between the salutation's comma and "mit", the verb on the
#: next line, and an enclosure's or another letter's page. None may count.
H = "Stadt Musterstadt · Ordnungsamt\nDatum: 16.06.2026\nSehr geehrte Frau Beispiel,\n"
N = "Stadt Musterstadt · Ordnungsamt\nDatum: 16.06.2026\n"
F = "Stadt Musterstadt\n"
G = "Sehr geehrte Frau Beispiel,\n"
PLACES_THAT_DO_NOT_COUNT = [
    # a line of capitalised words broken after a number, or a label of another kind
    pytest.param(N + "Ihren Widerspruch Az. 32-117/2026\nmit Schreiben vom 09.06.2026 weisen wir als unbegründet zurück.", id="F01"),
    pytest.param(N + "Die Erlaubnis Nr. 4711\nmit Bescheid vom 09.06.2026 widerrufen wir mit Wirkung für die Zukunft.", id="F02"),
    pytest.param(N + "Die Abwassergebühr 2025\nmit Bescheid vom 09.06.2026 erhöhen wir ab Juli um 12,00 EUR.", id="F03"),
    pytest.param(N + "Die Vorauszahlungen 2026\nmit Bescheid vom 09.06.2026 mindern wir auf 40,00 EUR.", id="F04"),
    pytest.param(N + "Die Frist Kassenzeichen 5512\nmit Schreiben vom 09.06.2026 verlängern wir bis Ende Juli.", id="F05"),
    pytest.param(N + "Den Fehler Az. 77-4/2026\nmit Bescheid vom 09.06.2026 berichtigen wir nach § 42 VwVfG.", id="F06"),
    pytest.param(N + "Ihren Bauantrag Nr. 2026/88\nmit Schreiben vom 09.06.2026 genehmigen wir nicht.", id="F07"),
    pytest.param(N + "Die Forderung Kassenzeichen 600123\nmit Bescheid vom 09.06.2026 stunden wir nicht weiter.", id="F08"),
    pytest.param(N + "Ihren Antrag Az. 12/2026\nmit Schreiben vom 09.06.2026 nehmen wir zu den Akten.", id="F09"),
    pytest.param(N + "Die Grundsteuer 2026\nmit Bescheid vom 09.06.2026 senken wir nicht.", id="F10"),
    pytest.param(N + "Ihr Einwand zum Aktenzeichen: 4711\nmit Schreiben vom 09.06.2026 weisen wir zurück.", id="F11"),
    pytest.param(N + "Die Kosten Höhe 80,00\nmit Bescheid vom 09.06.2026 erhöhen wir nicht.", id="F12"),
    pytest.param(N + "Ihren Antrag Nr. 17\nmit Schreiben vom 09.06.2026 lehne ich erneut ab, wie im Bescheid ausgeführt.", id="F13"),
    pytest.param(N + "Die Fahrerlaubnis Klasse B 2019\nmit Bescheid vom 09.06.2026 entziehen wir, wie Ihnen bekannt.", id="F15"),
    pytest.param(N + "Den Ausschank Nr. 3\nmit Bescheid vom 09.06.2026 untersagen wir bis heute.", id="F16"),
    pytest.param(N + "Bescheid 2026\nmit Bescheid vom 09.06.2026 widerrufen wir", id="C06"),
    pytest.param(N + "Schreiben 4711\nmit Schreiben vom 09.06.2026 nehmen wir", id="C07"),
    pytest.param(N + "Bescheid Schreiben 09.06.2026\nmit Bescheid vom 09.06.2026 ordnen wir", id="C08"),
    pytest.param(F + G + "Zu Ihrem Widerspruch Az. 32-117/2026\nmit Bescheid vom 02.03.2026 nehmen wir wie folgt Stellung.\n", id="fresh-F1"),
    pytest.param(F + G + "Ihr Schreiben Nr. 4711\nmit Bescheid vom 02.03.2026 stunden wir nicht, wie Sie meinen.\n", id="fresh-F2"),
    pytest.param(F + G + "Anlage 2\nmit Bescheid vom 02.03.2026 verlängern wir die Erlaubnis.\n", id="fresh-F3"),
    pytest.param(F + G + "Ihre Rechnung: 4711\nmit Schreiben vom 02.03.2026 berichtige ich Ihnen nichts.\n", id="fresh-F4"),
    pytest.param(F + G + "Ihren Widerspruch Az. 32-117/2026\nmit Schreiben vom 02.03.2026 weisen wir als unbegründet zurück.\n", id="fresh-F5"),
    pytest.param(F + G + "Ihren Antrag Nr. 4711\nmit Schreiben vom 02.03.2026 lehne ich ab.\n", id="fresh-F6"),
    pytest.param(F + G + "Betreff: Ihr Widerspruch gegen den Bescheid Nr. 12\nmit Schreiben vom 02.03.2026 weisen wir ihn zurück.\n", id="a-colon-in-mid-line"),
    pytest.param(F + G + "Kassenzeichen: 600123\nmit Bescheid vom 02.03.2026 stunde ich die Forderung.\n", id="a-label-of-another-kind"),
    pytest.param(F + G + "Eingang: 01.06.2026\nmit Bescheid vom 02.03.2026 weisen wir Ihren Widerspruch zurück.\n", id="another-label-with-a-date"),
    # a line ending in ":" that leads into a quotation or a report
    pytest.param(H + "Sie schrieben uns:\nMit Schreiben vom 09.06.2026 widerrufe ich meine Einwilligung zur Lastschrift.\nDas nehmen wir zur Kenntnis.", id="Q01"),
    pytest.param(H + "Ihr Bevollmächtigter trägt vor:\nMit Schreiben vom 09.06.2026 nehme ich den Antrag meiner Mandantin zurück.\nDem folgen wir.", id="Q02"),
    pytest.param(H + "Unser Bescheid lautete im Tenor:\nMit Bescheid vom 09.06.2026 untersagen wir Ihnen das Abstellen des Wohnwagens.\nDiesen Bescheid heben wir nunmehr auf.", id="Q03"),
    pytest.param(H + "Ihr Vermieter hat erklärt:\nMit Schreiben vom 09.06.2026 erhöhe ich die Miete um 30,00 EUR.\nDas berücksichtigen wir beim Wohngeld.", id="Q04"),
    pytest.param(H + "Das Landratsamt Musterkreis teilte mit:\nMit Bescheid vom 09.06.2026 entziehen wir Herrn Muster die Fahrerlaubnis.\nWir sind daran gebunden.", id="Q05"),
    pytest.param(H + "Sie und Ihr Ehemann schrieben:\nMit Schreiben vom 09.06.2026 widerrufen wir die Einzugsermächtigung.\nDer Widerruf ist wirksam.", id="Q06"),
    pytest.param(H + "Ihr Arbeitgeber bescheinigt:\nMit Schreiben vom 09.06.2026 verlängere ich den Vertrag von Frau Beispiel bis 2027.\nDas Einkommen rechnen wir an.", id="Q07"),
    pytest.param(H + "Auszug aus Ihrem Widerspruch\nMit Schreiben vom 09.06.2026 widerrufe ich die Zustimmung zur Abbuchung.\nWir prüfen das.", id="Q08"),
    pytest.param(H + "Die Schule hat mitgeteilt:\nMit Schreiben vom 09.06.2026 berichtige ich das Zeugnis von Lena Beispiel.\nWir legen es zugrunde.", id="Q09"),
    pytest.param(H + "Die Eigentümerin erklärte:\nMit Schreiben vom 09.06.2026 genehmige ich den Umbau.\nDie Genehmigung liegt uns vor.", id="Q10"),
    pytest.param(H + "das Amt für Soziales schreibt: Mit Bescheid vom 09.06.2026 entscheide ich über die Hilfe. Wir schließen uns an.", id="I12"),
    pytest.param(F + G + "Sie tragen vor:\nMit Bescheid vom 02.03.2026 widerrufen wir die Erlaubnis.\nDas trifft nicht zu.\n", id="fresh-C1"),
    pytest.param(F + G + "Das Landratsamt hat uns Folgendes mitgeteilt:\nMit Bescheid vom 02.03.2026 untersagen wir den Betrieb.\n", id="fresh-C2"),
    pytest.param(F + G + "Auszug aus dem Bescheid des Landratsamts:\nMit Bescheid vom 02.03.2026 entziehen wir die Fahrerlaubnis.\n", id="fresh-C3"),
    pytest.param(F + G + "In Ihrem Widerspruch zitieren Sie den Bescheid so:\nMit Bescheid vom 02.03.2026 ordne ich den Abriss an.\nDieser Bescheid ist aufgehoben.\n", id="fresh-C4"),
    pytest.param(F + G + "Ihr Widerspruch richtet sich gegen den Satz\nMit Bescheid vom 02.03.2026 erhöhen wir die Vorauszahlungen.\n", id="fresh-C5"),
    pytest.param(F + G + "Zur Erinnerung, der frühere Bescheid lautete\nMit Bescheid vom 02.03.2026 genehmigen wir den Umbau.\n", id="fresh-C6"),
    pytest.param(F + G + "Sie tragen vor:\nMit Bescheid vom 02.03.2026 setzen wir die Gebühr fest.\n", id="fresh-M1"),
    # a heading over a part of the letter
    pytest.param(H + "Sachverhalt\nMit Bescheid vom 09.06.2026 erteilen wir Ihnen die Erlaubnis unter Auflagen.\nGründe\nDie Auflage wurde nicht erfüllt.", id="H01"),
    pytest.param(H + "Bisheriger Bescheid\nMit Bescheid vom 09.06.2026 genehmigen wir 12 Stellplätze.\nNeuer Bescheid\nWir genehmigen 10 Stellplätze.", id="H02"),
    pytest.param(H + "Vorgang\nMit Bescheid vom 09.06.2026 verpflichten wir Sie zur Beseitigung.", id="H03"),
    pytest.param(H + "Widerspruch gegen den Bescheid\nMit Bescheid vom 09.06.2026 versagen wir die Leistung.", id="H04"),
    pytest.param(H + "Begründung\nMit Bescheid vom 09.06.2026 widerrufe ich die Zulassung. Dagegen richtet sich Ihr Widerspruch.", id="H05"),
    pytest.param(H + "Bescheide im Jahr 2026\nMit Bescheid vom 09.06.2026 erhöhen wir den Abschlag\nMit Bescheid vom 16.06.2026 senken wir ihn wieder", id="H06"),
    pytest.param(H + "Erstbescheid Änderung\nMit Bescheid vom 09.06.2026 mindern wir den Satz um 10 %.", id="M01"),
    pytest.param(H + "Seite 2 von 2\nMit Bescheid vom 09.06.2026 verlängern wir die Erlaubnis um ein Jahr, so der frühere Bescheid.", id="M11"),
    pytest.param(N + "Bescheid\nMit Bescheid vom 09.06.2026 berichtigen wir", id="C12"),
    pytest.param(N + "Schreiben vom 16.06.2026\nMit Schreiben vom 09.06.2026 teile ich mit", id="C20"),
    pytest.param(N + "Bescheid 1\nmit dem Bescheid vom 09.06.2026 versagen wir\nBescheid 2\nmit dem Bescheid vom 16.06.2026 genehmigen wir", id="C17"),
    pytest.param(F + G + "Gebührenbescheid\nMit Bescheid vom 02.03.2026 setzen wir die Gebühr fest.\n", id="a-heading-of-one-word"),
    # a list's mark, an abbreviation's full stop, ";", a bullet
    pytest.param(H + "zum Verlauf:\n1. Mit Bescheid vom 09.06.2026 widerrufen wir die Erlaubnis.\n2. Dagegen legten Sie Widerspruch ein.", id="L01"),
    pytest.param(H + "der Sachstand:\n1. Antrag vom 01.06.2026.\n2. Mit Bescheid vom 09.06.2026 erteilen wir die Genehmigung.\n3. Heute ändern wir sie.", id="L02"),
    pytest.param(H + "Verlauf:\n1. Mit Schreiben vom 09.06.2026 ordne ich die Anhörung an.\n2. Sie äußerten sich nicht.", id="L03"),
    pytest.param(H + "Übersicht:\nI. Mit Bescheid vom 09.06.2026 berichtigen wir den Betrag.\nII. Heute setzen wir die Zinsen fest.", id="L04"),
    pytest.param(H + "Bisher:\n2. Mit Bescheid vom 09.06.2026 stunden wir die Forderung.\n3. Die Stundung ist abgelaufen.", id="L05"),
    pytest.param(H + "Chronologie\n4. Mit Schreiben vom 09.06.2026 genehmigen wir den Antrag.\n5. Der Antrag wurde zurückgenommen.", id="L06"),
    pytest.param(N + "1. Mit Bescheid vom 09.06.2026 erteilen wir\n2. Mit Bescheid vom 16.06.2026 widerrufen wir", id="C09"),
    pytest.param(H + "Ihr Widerspruch vom 10.06.2026, Az. Mit Schreiben vom 09.06.2026 weisen wir darauf hin.", id="M10"),
    pytest.param(H + "Stand der Sache: Ihr Antrag liegt vor; Mit Bescheid vom 09.06.2026 entziehen wir die Erlaubnis.", id="M02"),
    pytest.param(H + "Ihre Fragen:\n• Mit Bescheid vom 09.06.2026 senken wir den Abschlag, das ist richtig.", id="M12"),
    # words between the salutation's comma and "mit"
    pytest.param(F + "Sehr geehrte Frau Beispiel, Sie meinen, mit Bescheid vom 02.03.2026 widerrufen wir die Erlaubnis. Das trifft nicht zu.\n", id="fresh-S1"),
    pytest.param(F + "Sehr geehrter Herr Muster, Sie schreiben, mit Bescheid vom 02.03.2026 lehne ich Ihren Antrag ab. Das ist ein Irrtum.\n", id="fresh-S2"),
    pytest.param(F + "Sehr geehrte Frau Beispiel, anders als Sie annehmen, mit Bescheid vom 02.03.2026 entziehen wir Ihnen nichts.\n", id="fresh-S3"),
    pytest.param(F + "Sehr geehrte Frau Beispiel, Ihr Anwalt behauptet, mit Bescheid vom 02.03.2026 untersage ich Ihnen den Betrieb.\n", id="fresh-S4"),
    pytest.param(F + "Sehr geehrte Damen und Herren, Ihre Mandantin trägt vor, mit Bescheid vom 02.03.2026 versagen wir die Leistung.\n", id="fresh-S5"),
    pytest.param(F + "Sehr geehrte Frau Beispiel,\nwie Sie richtig schreiben,\nmit Bescheid vom 02.03.2026 widerrufe ich die Erlaubnis nicht.\n", id="fresh-S6"),
    pytest.param(F + "Sehr geehrte Frau Beispiel, Sie meinen, mit Bescheid vom 02.03.2026 lehnen wir Ihren Antrag ab.\n", id="fresh-M2"),
    # the verb on the next line
    pytest.param(H + "Mit Bescheid vom 09.06.2026\nwiderrufen wir die Erlaubnis. So stand es im Bescheid.", id="M08"),
]  # fmt: skip


#: An enclosure's or another letter's page in the same upload: a decision's own date is read on the letter's first
#: sheet only (a form feed starts another sheet).
ANOTHER_SHEET = [
    pytest.param(H + "anbei erhalten Sie eine Kopie unseres Bescheids.\n", "Stadt Musterstadt\nAbschrift\nMit Bescheid vom 09.06.2026 untersagen wir Ihnen die Nutzung der Garage.", id="E01"),
    pytest.param(H + "als Anlage übersenden wir den Bescheid erneut.\n", "Der Oberbürgermeister\nMit Bescheid vom 09.06.2026 versage ich die Erlaubnis.", id="E02"),
    pytest.param(H + "wir bestätigen den Eingang Ihres Schreibens (Anlage).\n", "Erika Beispiel, Musterweg 1\nMit Schreiben vom 09.06.2026 widerrufe ich den Dauerauftrag.", id="E03"),
    pytest.param(H + "das Schreiben des Kreises liegt bei.\n", "Landkreis Musterkreis\nMit Bescheid vom 09.06.2026 ordnen wir die Untersuchung an.", id="E04"),
    pytest.param(H + "wir erinnern an die Zahlung. Kopie:\n", "Stadtkasse Musterstadt\nMit Bescheid vom 09.06.2026 erteilen wir Ihnen die Sondernutzungserlaubnis gegen 50,00 EUR.", id="E05"),
    pytest.param(H + "der vorläufige Bescheid ist beigefügt; er wird nun endgültig.\n", "Jobcenter Musterstadt\nMit Bescheid vom 09.06.2026 bewillige ich vorläufig Leistungen.", id="E06"),
    pytest.param(H + "die Stundungsverfügung liegt bei.\n", "Finanzamt Musterstadt\nMit Bescheid vom 09.06.2026 stunde ich die Steuer bis 30.09.2026.", id="E07"),
    pytest.param(H + "zum Vergleich der frühere Bescheid:\n", "Stadt Musterstadt\nMit Bescheid vom 09.06.2026 erhöhe ich den Beitrag auf 90,00 EUR.", id="E08"),
    pytest.param(F + G + "hiermit heben wir den Bescheid vom 02.03.2026 auf.\n\nAnlage: Kopie des Bescheids\n", "Mit Bescheid vom 02.03.2026 erteilen wir Ihnen die Erlaubnis.\n", id="fresh-P1"),
]  # fmt: skip


def test_the_form_at_a_place_where_it_does_not_open_does_not_count() -> None:
    def check(page: str) -> None:
        found = re.search(
            r"(?:Bescheid|Schreiben) vom (\d{2})\.(\d{2})\.(\d{4})\s+[^\W\d_]+ (?:wir|ich)\b", page
        )
        assert found is not None
        day, month, year = (int(part) for part in found.groups())
        _assert_not_in(date(year, month, day), _page_dates(page))

    check_rows(PLACES_THAT_DO_NOT_COUNT, check, at_least=70)


def test_a_later_sheet_is_not_read_for_the_decisions_own_date() -> None:
    """Each enclosure, as a second page and after a form feed on the first, gives no date of its own; the same words as
    the letter's own first sheet do (so the sheet, not the words, decides)."""

    def check(letter: str, enclosure: str) -> None:
        other = date(2026, 6, 9) if "09.06.2026" in enclosure else date(2026, 3, 2)
        _assert_not_in(other, _page_dates(letter, enclosure))
        _assert_not_in(other, _page_dates(f"{letter}\f{enclosure}"))
        _assert_in(other, _page_dates(f"{F}{G}{enclosure.splitlines()[-1]}"))

    check_rows(ANOTHER_SHEET, check)


def test_a_line_above_that_is_no_field_does_not_open_the_form() -> None:
    """In lower case under the salutation's line the form opens only under a header's "Datum:" field or a table's row
    of one word and a date; never after words of its own sentence on the line above, a sentence broken right after a
    date or a number among them."""
    for above, sentence in (
        ("Nach Anhörung\n", "mit Schreiben vom 09.06.2026 setzen wir die Gebühr fest."),
        ("Anders als\n", "mit Bescheid vom 09.06.2026 setzen wir die Gebühr fest."),
        ("Gebührenbescheid\n", "Mit Bescheid vom 09.06.2026 setzen wir die Gebühr fest."),
        # a sentence the text layer broke right after a date or a number (the reviews' rows)
        (
            "Ihren Widerspruch gegen den Bescheid vom 02.06.2026\n",
            "mit Schreiben vom 05.06.2026 weisen wir als unbegründet zurück.",
        ),
        (
            "Ihr Widerspruch vom 03.06.2026\n",
            "mit Bescheid vom 01.06.2026 setzen wir die Gebühr fest, wie Sie meinen.",
        ),
        ("Ihre Unterlagen zum Antrag 4711\n", "mit Schreiben vom 09.06.2026 erhalten Sie anbei zurück."),
        ("Ihre Zahlung zum Kassenzeichen 4711\n", "mit Bescheid vom 09.06.2026 wird verrechnet."),
        ("Ihre Zahlung zum Kassenzeichen 4711\n", "mit Bescheid vom 09.06.2026 setzen wir die Gebühr fest."),
        ("Die Kopien zu Ihrem Antrag vom 01.03.2026\n", "mit Schreiben vom 09.06.2026 erhalten Sie zurück."),
        (
            "Den Widerspruch gegen den Bescheid Nr. 12\n",
            "mit Schreiben vom 09.06.2026 bestätigen wir den Eingang.",
        ),
    ):
        found = re.search(r"vom (\d{2})\.(\d{2})\.(\d{4})", sentence)
        assert found is not None
        day, month, year = (int(part) for part in found.groups())
        assert date(year, month, day) not in _own_dates(sentence, above=above), above


#: Words of no listed place in the form, one of each kind it must refuse: an inflected participle, an adjective, a
#: determiner, a possessive, prepositions that are not listed (with the noun each governs, so that only the
#: preposition decides), a noun, a temporal adverb, a past auxiliary, the present auxiliary, "erhalten", the reader
#: as a speaker and a file number between the date and the verb.
UNLISTED_WORDS = (
    "festgesetzten", "bewilligten", "vorläufig", "alle", "unser", "Ihrem", "gegen Antrag", "aus Antrag",
    "nach Antrag", "Antrag", "bereits", "wurde", "wird", "erhalten", "Sie", "Az. 4711,",
)  # fmt: skip


def _places(marked: str) -> list[int]:
    """Where a word can be put into a counted row's places: the row's start and every space before its "|", never
    inside its date."""
    form = marked[: marked.index("|")]
    day = re.search(r"\d{2}\.\d{2}\.\d{4}|\d{1,2}\. [A-ZÄÖÜ][a-zäöü]+ \d{4}", form)
    assert day is not None
    return [0] + [i + 1 for i, char in enumerate(form) if char == " " and not day.start() <= i < day.end()]


def test_an_unlisted_word_in_any_place_of_the_form_refuses_it() -> None:
    """Unknown means no: every counted row, with "wir" and with "ich", with a word of no listed place put into each
    of its places in turn, is no date of the letter's own."""
    cases = [
        pytest.param(marked.replace("|", ""), at, word, id=f"{row.id}{speaker}@{at}:{word}")
        for row in FORMS_THAT_COUNT
        for speaker, marked in (("", row.values[0]), ("-ich", _as_ich(row.values[0])))
        for at in _places(marked)
        for word in UNLISTED_WORDS
    ]
    assert len(cases) > 3000

    def check(sentence: str, at: int, word: str) -> None:
        assert _own_dates(f"{sentence[:at]}{word} {sentence[at:]}") == []

    check_rows(cases, check)


#: What may stand right before a counted row (``{}`` is the row, with its first letter as given) and does not open the
#: form: a line of capitalised nouns that ends in a number, labels of another kind, a line ending in ":", headings,
#: lists' marks, an abbreviation's full stop, ";", another sheet (a second page, or a form feed on the first), a label of
#: another kind with a date, and a lower-case "mit" after a sentence's end.
FIXED_LEADS = (
    G + "Ihren Widerspruch Az. 32-117/2026\n{lower}", G + "Die Erlaubnis Nr. 4711\n{lower}", G + "Anlage 2\n{lower}",
    G + "Bescheid 2026\n{lower}", G + "Die Abwassergebühr 2025\n{upper}", G + "Kassenzeichen: 600123\n{lower}",
    G + "Betreff: Ihr Widerspruch gegen den Bescheid Nr. 12\n{lower}", G + "Sie schrieben uns:\n{upper}",
    G + "Das Landratsamt Musterkreis teilte mit:\n{lower}", G + "Sachverhalt\n{upper}", G + "Gebührenbescheid\n{upper}",
    G + "Bisheriger Bescheid\n{upper}", G + "1. {upper}", G + "I. {upper}", G + "a) {upper}", G + "• {upper}",
    G + "- {upper}", G + "Zum Verlauf:\n2. {upper}", G + "Ihr Zeichen Az. {upper}", G + "Ihr Antrag liegt vor; {upper}",
    G + "anbei die Kopie.\f{upper}", G + "anbei die Kopie.\fLandratsamt Musterkreis\n{upper}",
    G + "Eingang: 01.06.2026\n{lower}", G + "Das ist bestandskräftig.\n{lower}", G + "Das ist bestandskräftig. {lower}",
)  # fmt: skip
#: The same with a word of no listed place (``{word}``): between the salutation's comma and "mit", alone on the line
#: above, as a label above, and as a noun with a number above.
WORD_LEADS = (
    "Sehr geehrte Frau Beispiel, {word}, {lower}", "Sehr geehrte Frau Beispiel, {word},\n{lower}",
    G + "{word}\n{upper}", G + "{word}:\n{upper}", G + "{word} 4711\n{lower}", G + "Ihr {word} Nr. 4711\n{lower}",
)  # fmt: skip


def test_no_lead_but_the_named_places_opens_the_form() -> None:
    """For every counted row, with "wir" and with "ich": a fixed lead of each kind the form must not open after, every
    unlisted word in each lead slot, the verb moved to the next line, and the row on a second page, give no date of
    the letter's own. The places that do open it are PLACES_THAT_COUNT."""
    cases = []
    for row in FORMS_THAT_COUNT:
        for speaker, marked in (("", row.values[0]), ("-ich", _as_ich(row.values[0]))):
            upper = marked.replace("|", "")
            upper = upper[0].upper() + upper[1:]
            lower = upper[0].lower() + upper[1:]
            pages = [F + lead.format(upper=upper, lower=lower) for lead in FIXED_LEADS]
            pages += [
                F + lead.format(word=word, upper=upper, lower=lower)
                for lead in WORD_LEADS
                for word in UNLISTED_WORDS
            ]
            pages.append(F + G + re.sub(r"(\d{4}) ", r"\1\n", upper, count=1))
            cases += [pytest.param(page, id=f"{row.id}{speaker}:{index}") for index, page in enumerate(pages)]
            cases.append(
                pytest.param(F + G + "anbei die Kopie.\n", F + upper, id=f"{row.id}{speaker}:second-page")
            )
    assert len(cases) > 7000

    def check(*pages: str) -> None:
        _assert_not_in(date(2026, 6, 9), _page_dates(*pages))

    check_rows(cases, check)


#: Sentences that name the letter's own decision but fall outside the one form, so do not count (recall given up on
#: purpose: precision comes first). The letter's header date still counts for them. The passive, "ergeht", "erhalten
#: Sie", "Der Bescheid vom … ergeht", the verb before "mit" and English read the same when a letter tells of an
#: earlier decision, a set-off, a revocation or another authority's act, so none of them counts.
OWN_BUT_OUTSIDE_THE_FORMS = [
    pytest.param(
        "Mit Bescheid vom 09.06.2026 wird die Grundsteuer auf 312,00 EUR festgesetzt.", id="passive"
    ),
    pytest.param("Mit Bescheid vom 09.06.2026 werden Gebühren von 80,00 EUR erhoben.", id="passive-plural"),
    pytest.param("Mit Bescheid vom 09.06.2026 ergeht folgende Entscheidung:", id="ergeht"),
    pytest.param("Mit Schreiben vom 09.06.2026 erhalten Sie die Abrechnung.", id="erhalten-sie"),
    pytest.param("Der Bescheid vom 09.06.2026 ergeht unter dem Vorbehalt der Nachprüfung.", id="der-ergeht"),
    pytest.param(
        "Die Gebühr wird mit Bescheid vom 09.06.2026 auf 80,00 EUR festgesetzt.", id="verb-before-mit"
    ),
    pytest.param("Hiermit wird mit Bescheid vom 09.06.2026 die Erlaubnis erteilt.", id="hiermit-wird-mit"),
    pytest.param(
        "Hiermit wird mit Bescheid vom 09.06.2026 die Erlaubnis widerrufen.", id="hiermit-wird-widerrufen"
    ),
    pytest.param("Ihnen wird mit Bescheid vom 09.06.2026 eine Erlaubnis erteilt.", id="ihnen-wird-mit"),
    pytest.param("By decision dated 9 June 2026 we refuse your application.", id="en-present"),
    pytest.param("By our decision dated 9 June 2026, we hereby set the fee at EUR 80.00.", id="en-hereby"),
    pytest.param("Hereby, by decision dated 9 June 2026, we refuse your application.", id="en-hereby-first"),
    pytest.param(
        "With the notice dated 9 June 2026 the fee is hereby assessed at EUR 80.00.", id="en-passive"
    ),
    pytest.param("Mit Gebührenbescheid vom 09.06.2026 setzen wir die Gebühr fest.", id="compound-noun"),
    pytest.param(
        "Mit Bescheid vom 09.06.2026, Az. 32-117/2026, setzen wir die Gebühr fest.", id="file-number"
    ),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 (Kassenzeichen 4711) setze ich das Zwangsgeld fest.", id="bracket"
    ),
    pytest.param("Mit Schreiben vom 09.06.2026 bitten wir Sie um Zahlung.", id="bitten-asks"),
    pytest.param("Mit Schreiben vom 09.06.2026 erinnern wir Sie an die Zahlung.", id="erinnern-reminds"),
    pytest.param(
        "Hiermit setzen wir mit Bescheid vom 09.06.2026 die Gebühr fest.", id="active-verb-before-mit"
    ),
    pytest.param(
        "Betreff: Hundesteuer 2026 Mit Bescheid vom 09.06.2026 setzen wir die Steuer fest.",
        id="after-a-subject-line",
    ),
    pytest.param(
        "Gemäß § 35 VwVfG setzen wir mit Bescheid vom 09.06.2026 die Gebühr fest.", id="after-a-statute"
    ),
    # each speaker with its own verb form only
    pytest.param("Mit Bescheid vom 09.06.2026 setze wir die Gebühr fest.", id="setze-wir"),
    pytest.param("Mit Bescheid vom 09.06.2026 setzen ich die Gebühr fest.", id="setzen-ich"),
    # places the form does not open at, so its own date is given up there too (the line above or the opening decide)
    pytest.param(
        "Gebührenbescheid Hundesteuer\nMit Bescheid vom 09.06.2026 ändere ich die Festsetzung.",
        id="under-a-heading",
    ),
    pytest.param(
        "Vorauszahlungen 2026   48,00\nmit Bescheid vom 09.06.2026 erhöhen wir den Betrag.",
        id="under-a-row-ending-in-an-amount",
    ),
    pytest.param(
        "Kassenzeichen: 600123\nmit Bescheid vom 09.06.2026 stunde ich die Forderung.",
        id="under-another-label",
    ),
    pytest.param(
        "Wir entscheiden:\n1. Mit Bescheid vom 09.06.2026 setzen wir die Gebühr fest.",
        id="after-a-lists-mark",
    ),
    pytest.param("Mit Bescheid vom 09.06.2026\nsetzen wir die Gebühr fest.", id="the-verb-on-the-next-line"),
    pytest.param(
        "Wir entscheiden wie folgt:\nMit Bescheid vom 09.06.2026 untersage ich die Nutzung.",
        id="under-a-colon",
    ),
    pytest.param(
        "Ihr Antrag liegt uns vor. Mit Bescheid vom 09.06.2026 lehnen wir ihn ab.",
        id="after-a-sentence-ending-in-a-short-word",
    ),
]


def test_an_own_decision_outside_the_forms_does_not_count() -> None:
    check_rows(OWN_BUT_OUTSIDE_THE_FORMS, lambda sentence: _assert_equal(_own_dates(sentence), []))


#: The form's known limit, pinned so that a change to it is seen. A sentence that tells of another decision in the
#: form itself (first person, present tense, a listed verb right after the date, at a place where the form opens)
#: counts: the check does not read past the speaker. Main's form counts the same sentences with its own verbs ("Mit
#: Bescheid vom … fordern wir 80,00 EUR, die bis heute nicht bezahlt sind"). It costs some days on the early side,
#: with "Please check" (the earlier of two dates within 14 days is kept), which is the safe side; a letter that names
#: two dates for itself and is not seen would cost days on the late side, unflagged. Each row's 09.06.2026 (09.03.2026)
#: is another decision's, and it counts. The last row is the table row's place, which main's own test needs.
KNOWN_LIMIT = [
    pytest.param(
        G + "Mit Schreiben vom 09.03.2026 teilen wir, die Erben, Ihnen mit, so Ihr Anwalt.", id="I5"
    ),
    pytest.param(
        G
        + "Mit Bescheid vom 09.03.2026 fordern wir 80,00 EUR, die bis heute nicht bezahlt sind. Wir mahnen hiermit.",
        id="J1",
    ),
    pytest.param(
        G + "Mit Bescheid vom 09.03.2026 setzen wir eine Gebühr fest, die Sie bisher nicht gezahlt haben.",
        id="J2",
    ),
    pytest.param(
        H
        + "wir fassen zusammen. Mit Bescheid vom 09.06.2026 widerrufen wir die Erlaubnis; dieser Bescheid ist "
        "bestandskräftig.",
        id="P01",
    ),
    pytest.param(
        H + "Mit Bescheid vom 09.06.2026 stunden wir die Steuer bis zum 30.09.2026. Die Raten sind fällig.",
        id="P15",
    ),
    pytest.param(
        H + "Mit Schreiben vom 09.06.2026 fordere ich Sie zur Zahlung auf. Heute mahne ich die Zahlung an.",
        id="I04",
    ),
    pytest.param(
        H
        + "Mit Bescheid vom 09.06.2026 bewillige ich vorläufig Leistungen. Nun setze ich sie endgültig fest.",
        id="I05",
    ),
    pytest.param(
        "Stadt Musterstadt\nDatum: 16.06.2026\nSehr geehrter Herr Muster,\nmit Bescheid vom 09.06.2026 widerrufen wir "
        "die Erlaubnis; heute setzen wir die Kosten fest.",
        id="S06",
    ),
    pytest.param(H + "Mit dem Schreiben vom 09.06.2026 nehme ich Stellung, schrieben Sie uns.", id="M09"),
    pytest.param(
        N + "Mit Bescheid vom 09.06.2026 ändere ich, mit Bescheid vom 16.06.2026 setze ich fest.", id="C05"
    ),
    pytest.param(
        N + "Mit Bescheid vom 09.06.2026 widerrufe ich. Mit Bescheid vom 16.06.2026 erteile ich.", id="C19"
    ),
    pytest.param(N + "Bescheid 09.06.2026\nmit Bescheid vom 09.06.2026 heben wir", id="C21"),
]


def test_the_forms_known_limit_counts_as_documented() -> None:
    def check(page: str) -> None:
        found = re.search(r"vom (\d{2})\.(\d{2})\.(\d{4}) [^\W\d_]+ (?:wir|ich)\b", page)
        assert found is not None
        day, month, year = (int(part) for part in found.groups())
        _assert_in(date(year, month, day), _page_dates(f"{F}{page}" if page.startswith(G) else page))

    check_rows(KNOWN_LIMIT, check)


def _assert_equal(found: object, expected: object) -> None:
    assert found == expected


#: What must never count as the letter's own date: an earlier decision that the letter changes, revokes, compares
#: with, replaces, refers to, names as a thing or names in the past; the decision an objection decision rules on;
#: the invoice a reminder names; the person's own letter. Every such form the docs name is a row here.
ANOTHER_DECISIONS_DATE = [
    pytest.param("Der Bescheid vom 09.06.2026 wird aufgehoben.", id="revoked"),
    pytest.param("Hiermit heben wir den Bescheid vom 09.06.2026 auf.", id="hiermit-revoked"),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 wurde die Steuer auf 900,00 EUR festgesetzt.", id="past-passive"
    ),
    pytest.param("Mit Bescheid vom 09.06.2026 hatten wir die Steuer festgesetzt.", id="pluperfect"),
    pytest.param("Mit Bescheid vom 09.06.2026 haben wir die Steuer festgesetzt.", id="perfect"),
    pytest.param("Mit Bescheid vom 09.06.2026 ist die Steuer festgesetzt worden.", id="perfect-passive"),
    pytest.param("Mit Bescheid vom 09.06.2026 setzte die Stadt die Gebühr fest.", id="narrated-past"),
    pytest.param(
        "Die mit Bescheid vom 09.06.2026 festgesetzte Steuer wird auf 800,00 EUR herabgesetzt.",
        id="attribute",
    ),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 bewilligte Leistungen werden aufgehoben.", id="attribute-no-article"
    ),
    pytest.param(
        "Der Betrag wird mit den mit Bescheid vom 09.06.2026 festgesetzten Zinsen verrechnet.",
        id="attribute-after-a-verb",
    ),
    pytest.param(
        "Die Zahlung wird auf mit Bescheid vom 09.06.2026 festgesetzte Gebühren angerechnet.",
        id="attribute-without-an-article",
    ),
    pytest.param(
        "Die Steuer wird in Abänderung des Bescheides vom 09.06.2026 auf 800,00 EUR festgesetzt.",
        id="abaenderung",
    ),
    pytest.param(
        "Unter Bezugnahme auf den Bescheid vom 09.06.2026 wird die Steuer neu festgesetzt.", id="bezug"
    ),
    pytest.param(
        "Die Steuer wird unter Bezugnahme mit Bescheid vom 09.06.2026 erhoben.", id="bezug-before-mit"
    ),
    pytest.param(
        "Ihr Widerspruch vom 20.06.2026 gegen den Bescheid vom 09.06.2026 wird zurückgewiesen.",
        id="objection-decision",
    ),
    pytest.param("Die Steuer wird wie mit Bescheid vom 09.06.2026 mitgeteilt erhoben.", id="wie"),
    pytest.param(
        "Die Leistung wird in Verbindung mit dem Bescheid vom 09.06.2026 gezahlt.", id="in-verbindung"
    ),
    pytest.param("Der Zuschlag wird zusammen mit dem Bescheid vom 09.06.2026 erhoben.", id="zusammen-mit"),
    pytest.param("Die Gebühr wird bereits mit Bescheid vom 09.06.2026 erhoben.", id="bereits"),
    pytest.param("Die Bewilligung wird mit Wirkung vom 09.06.2026 aufgehoben.", id="mit-wirkung-vom"),
    pytest.param("Mit Schreiben vom 09.06.2026 wurden Sie zur Zahlung aufgefordert.", id="reminder-past"),
    pytest.param("Unsere Rechnung vom 09.06.2026 ist noch offen.", id="reminder-invoice"),
    pytest.param(
        "Wir bitten um Zahlung des mit Bescheid vom 09.06.2026 festgesetzten Betrags.", id="reminder-amount"
    ),
    pytest.param(
        "Mit Ihrem Schreiben vom 09.06.2026 haben Sie Widerspruch erhoben.", id="the-persons-letter"
    ),
    pytest.param("Mit Schreiben vom 09.06.2026 beantragen Sie Wohngeld.", id="the-persons-application"),
    pytest.param(
        "Ihr Widerspruch mit Schreiben vom 09.06.2026 wird als unbegründet zurückgewiesen.",
        id="the-persons-objection-named-by-its-letter",
    ),
    pytest.param(
        "Ihrem Antrag mit Schreiben vom 09.06.2026 wird stattgegeben.", id="the-persons-application-granted"
    ),
    pytest.param(
        "Auf Ihren Antrag mit Schreiben vom 09.06.2026 werden Ihnen Leistungen bewilligt.",
        id="auf-ihren-antrag-mit-schreiben",
    ),
    pytest.param(
        "Wir bestätigen den Eingang Ihres Antrags mit Schreiben vom 09.06.2026.", id="eingang-bestaetigt"
    ),
    pytest.param(
        "Wir nehmen Stellung zu Ihrem Widerspruch mit Schreiben vom 09.06.2026 und weisen ihn zurück.",
        id="stellung-zum-widerspruch",
    ),
    pytest.param(
        "Hiermit stunden wir die Forderung aus der Rechnung mit Schreiben vom 09.06.2026.",
        id="the-invoice-named-by-its-letter",
    ),
    pytest.param(
        "Nach Anhörung mit Schreiben vom 09.06.2026 ergeht folgender Bescheid.", id="hearing-ergeht"
    ),
    pytest.param(
        "Nach Anhörung mit Schreiben vom 09.06.2026 setzen wir die Gebühr fest.", id="hearing-setzen-wir"
    ),
    pytest.param("Das Guthaben wird mit dem Bescheid vom 09.06.2026 verrechnet.", id="verrechnet-mit-dem"),
    pytest.param("Die Erstattung wird mit Bescheid vom 09.06.2026 verrechnet.", id="verrechnet"),
    pytest.param("Wir verrechnen das Guthaben mit dem Bescheid vom 09.06.2026.", id="wir-verrechnen"),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 verrechnen wir das Guthaben.", id="verrechnen-wir-after-the-date"
    ),
    pytest.param(
        "Hiermit wird die Ihnen mit Bescheid vom 09.06.2026 befristet erteilte Erlaubnis widerrufen.",
        id="pronoun-and-adverb-attribute",
    ),
    pytest.param(
        "Hiermit widerrufen wir die Ihnen mit Bescheid vom 09.06.2026 unbefristet erteilte Erlaubnis.",
        id="pronoun-and-adverb-attribute-verb-first",
    ),
    pytest.param(
        "Hiermit wird der Ihnen mit Bescheid vom 09.06.2026 zuletzt bewilligte Betrag zurückgefordert.",
        id="pronoun-and-zuletzt-attribute",
    ),
    pytest.param(
        "Hiermit wird die Ihnen mit Bescheid vom 09.06.2026 im Umfang von 80,00 EUR erteilte Erlaubnis widerrufen.",
        id="pronoun-before-mit",
    ),
    pytest.param(
        "Hiermit werden mit Bescheid vom 09.06.2026 vorläufig bewilligte Leistungen endgültig festgesetzt.",
        id="adverb-before-the-attribute",
    ),
    pytest.param("Mit unserem Bescheid vom 09.06.2026 setzen wir die Steuer fest.", id="unserem"),
    pytest.param(
        "Die Gebühr, festgesetzt mit Bescheid vom 09.06.2026, wird auf 50,00 EUR ermäßigt.",
        id="participle-between-commas",
    ),
    pytest.param(
        "Der Betrag, zuletzt geändert mit Bescheid vom 09.06.2026, wird erneut angepasst.",
        id="adverb-participle-between-commas",
    ),
    pytest.param(
        "Der Widerspruch, eingelegt mit Schreiben vom 09.06.2026, wird zurückgewiesen.",
        id="the-persons-letter-between-commas",
    ),
    pytest.param(
        "Der Betrag, zuletzt geändert mit Bescheid vom 09.06.2026 wird erneut angepasst.",
        id="participle-phrase-its-closing-comma-lost",
    ),
    pytest.param(
        "Anders als mit Bescheid vom 09.06.2026 wird die Gebühr nunmehr auf 50,00 EUR festgesetzt.",
        id="anders-als",
    ),
    pytest.param(
        "Die Gebühr wird statt mit Bescheid vom 09.06.2026 nun mit diesem Bescheid festgesetzt.", id="statt"
    ),
    pytest.param(
        "Die Gebühr wird anstatt mit Bescheid vom 09.06.2026 nun mit diesem Bescheid festgesetzt.",
        id="anstatt",
    ),
    pytest.param(
        "Die Gebühr wird gegenüber mit Bescheid vom 09.06.2026 nun um 20,00 EUR erhöht.", id="gegenueber"
    ),
    pytest.param(
        "Hiermit wird die Vollstreckung aus mit Bescheid vom 09.06.2026 auf 80,00 EUR festgesetzten Forderungen"
        " eingeleitet.",
        id="preposition-opens-an-attribute-aus",
    ),
    pytest.param(
        "Wir erinnern an die Zahlung von mit Bescheid vom 09.06.2026 für das Jahr 2025 erhobenen Beiträgen.",
        id="preposition-opens-an-attribute-von",
    ),
    pytest.param(
        "Säumniszuschläge werden auf mit Bescheid vom 09.06.2026 bereits bestandskräftig festgesetzte Beträge"
        " erhoben.",
        id="preposition-opens-an-attribute-auf",
    ),
    pytest.param(
        "Die Gebühr wird für mit Bescheid vom 09.06.2026 im Mai erteilte Genehmigungen erhoben.",
        id="preposition-opens-an-attribute-fuer",
    ),
    pytest.param("By our decision dated 9 June 2026 we granted the benefit.", id="en-past"),
    pytest.param(
        "As announced in our letter of 9 June 2026, we hereby revoke the permit.", id="en-as-announced"
    ),
    pytest.param("As set out in our letter of 9 June 2026, we hereby request payment.", id="en-as-set-out"),
    pytest.param("As we wrote in our letter of 9 June 2026, we hereby request payment.", id="en-as-we-wrote"),
    pytest.param(
        "Further to the points set out in our letter of 9 June 2026, we hereby request payment.",
        id="en-reported-without-as",
    ),
    pytest.param("Our decision of 9 June 2026 is hereby revoked.", id="en-revoked"),
    pytest.param(
        "By decision dated 9 June 2026, which is hereby amended, the fee was set.", id="en-relative-clause"
    ),
    pytest.param(
        "In accordance with the notice dated 9 June 2026 we hereby request payment of the outstanding amount.",
        id="en-in-accordance-with",
    ),
    pytest.param(
        "In connection with our letter of 9 June 2026 we inform you that the hearing is postponed.",
        id="en-in-connection-with",
    ),
    pytest.param(
        "Compared with the assessment of 9 June 2026, the tax is hereby increased by EUR 40.",
        id="en-compared-with",
    ),
    pytest.param("Unlike in the notice of 9 June 2026, the fee is hereby set at EUR 50.", id="en-unlike-in"),
    pytest.param(
        "In addition to the amount set in the notice of 9 June 2026, a late fee is hereby charged.",
        id="en-in-addition-to",
    ),
    pytest.param(
        "The fee assessed in the notice of 9 June 2026 at EUR 80 is hereby reduced to EUR 50.",
        id="en-the-fee-assessed-in",
    ),
    pytest.param(
        "Following up on the matter dealt with in our letter of 9 June 2026, the fee is hereby reduced.",
        id="en-following-up-on",
    ),
    pytest.param(
        "In the notice of 9 June 2026 fees at EUR 80 are hereby reduced to EUR 50.",
        id="en-the-earlier-notices-amount-before-is-hereby",
    ),
]


#: Every sentence the three precision reviews of this check wrote to name another decision's date (their probes,
#: made-up letters of the Stadt Musterstadt): none may count. They are refused by the forms' closed slots now, not
#: by rules of their own.
THE_REVIEWS_FALSE_RIVALS = [
    # review 1: every sentence of its probe that names another decision's date
    "Mit diesem Bescheid wird der Bescheid vom 05.06.2026 aufgehoben.",
    "Gegen den mit Bescheid vom 05.06.2026 festgesetzten Betrag haben Sie Widerspruch erhoben.",
    "Wie Ihnen mit Bescheid vom 05.06.2026 mitgeteilt wurde, ist die Gebühr fällig.",
    "Die Forderung wird wie bisher mit Bescheid vom 05.06.2026 erhoben.",
    "Ihr Widerspruch mit Schreiben vom 05.06.2026 wird als unbegründet zurückgewiesen.",
    "Ihrem Antrag mit Schreiben vom 05.06.2026 wird stattgegeben.",
    "Der Widerspruch, eingelegt mit Schreiben vom 05.06.2026, wird zurückgewiesen.",
    "Die Gebühr, festgesetzt mit Bescheid vom 05.06.2026, wird auf 50,00 EUR ermäßigt.",
    "Der Betrag, zuletzt geändert mit Bescheid vom 05.06.2026, wird erneut angepasst.",
    "Hiermit wird die Ihnen mit Bescheid vom 05.06.2026 befristet erteilte Erlaubnis widerrufen.",
    "Hiermit widerrufen wir die Ihnen mit Bescheid vom 05.06.2026 unbefristet erteilte Erlaubnis.",
    "Hiermit wird der Ihnen mit Bescheid vom 05.06.2026 zuletzt bewilligte Betrag zurückgefordert.",
    "Hiermit wird die Ihnen mit Bescheid vom 05.06.2026 erteilte Erlaubnis widerrufen.",
    "Nach Anhörung mit Schreiben vom 05.06.2026 setzen wir die Gebühr fest.",
    "Nach Anhörung mit Schreiben vom 05.06.2026 ergeht folgender Bescheid.",
    "Auf Ihren Antrag mit Schreiben vom 05.06.2026 werden Ihnen Leistungen bewilligt.",
    "Wir bestätigen den Eingang Ihres Antrags mit Schreiben vom 05.06.2026.",
    "Wir nehmen Stellung zu Ihrem Widerspruch mit Schreiben vom 05.06.2026 und weisen ihn zurück.",
    "Das Guthaben wird mit dem Bescheid vom 05.06.2026 verrechnet.",
    "Wir verrechnen das Guthaben mit dem Bescheid vom 05.06.2026.",
    "Die Erstattung wird mit Bescheid vom 05.06.2026 verrechnet.",
    "As announced in our letter of 5 June 2026, we hereby revoke the permit.",
    "As set out in our letter of 5 June 2026, we hereby request payment.",
    "The fee assessed in the notice of 5 June 2026 at EUR 80.00 is hereby reduced.",
    "The amount set in the notice of 5 June 2026 is hereby reduced.",
    "Mit Rechnung vom 05.06.2026 haben wir Ihnen 80,00 EUR berechnet.",
    "Unsere Rechnung vom 05.06.2026 wird hiermit storniert.",
    "Als Anlage erhalten Sie eine Kopie des Bescheides vom 05.06.2026.",
    "Mit Schreiben vom 05.06.2026 wird von Ihnen Widerspruch eingelegt.",
    "Die Steuer wird in Abänderung des Bescheides vom 05.06.2026 auf 800,00 EUR festgesetzt.",
    "Der Bescheid vom 05.06.2026 wird hiermit zurückgenommen.",
    "Mit Bescheid vom 05.06.2026 wurde die Steuer festgesetzt; sie wird nun herabgesetzt.",
    "Der Säumniszuschlag wird auf den mit Bescheid vom 05.06.2026 festgesetzten Betrag erhoben.",
    "Wir erinnern Sie an die Zahlung der mit Bescheid vom 05.06.2026 festgesetzten Gebühr.",
    "Die Zinsen werden ab dem mit Bescheid vom 05.06.2026 bestimmten Tag berechnet.",
    "Ihr Einspruch gegen den Bescheid vom 05.06.2026 wird zurückgewiesen.",
    "Die mit Schreiben vom 05.06.2026 übersandte Rechnung wird hiermit berichtigt.",
    "Hiermit stunden wir die Forderung aus der Rechnung mit Schreiben vom 05.06.2026.",
    # review 2: every sentence of its probe that names another decision's date
    "Mit Bescheid vom 12.05.2026 haben wir die Gebühr auf 80,00 EUR festgesetzt.",
    "Mit Bescheid vom 12.05.2026 setzten wir die Gebühr auf 80,00 EUR fest.",
    "Der Änderungsbescheid vom 12.05.2026 wird hiermit aufgehoben.",
    "Anders als mit Bescheid vom 12.05.2026 wird die Gebühr nunmehr auf 50,00 EUR festgesetzt.",
    "Abweichend von der Festsetzung mit Bescheid vom 12.05.2026 wird die Gebühr ermäßigt.",
    "Hiermit wird die Vollstreckung aus mit Bescheid vom 12.05.2026 auf 80,00 EUR festgesetzten Forderungen eingeleitet.",
    "Wir erinnern an die Zahlung von mit Bescheid vom 12.05.2026 für das Jahr 2025 erhobenen Beiträgen.",
    "Säumniszuschläge werden auf mit Bescheid vom 12.05.2026 bereits bestandskräftig festgesetzte Beträge erhoben.",
    "In accordance with the notice dated 12 May 2026 we hereby request payment of the outstanding amount.",
    "In connection with our letter of 12 May 2026 we inform you that the hearing is postponed.",
    "Compared with the assessment of 12 May 2026, the tax is hereby increased by EUR 40.",
    "Unlike in the notice of 12 May 2026, the fee is hereby set at EUR 50.",
    "In addition to the amount set in the notice of 12 May 2026, a late fee is hereby charged.",
    "The fee assessed in the notice of 12 May 2026 at EUR 80 is hereby reduced to EUR 50.",
    "Following up on the matter dealt with in our letter of 12 May 2026, the fee is hereby reduced.",
    "Wir weisen darauf hin, dass mit Bescheid vom 12.05.2026 die Gebühr festgesetzt wurde.",
    "Beigefügt erhalten Sie den Bescheid vom 12.05.2026 in Kopie.",
    "Im Zusammenhang mit dem Bescheid vom 12.05.2026 teilen wir Ihnen Folgendes mit.",
    "We hereby revoke our decision of 12 May 2026.",
    "In our letter of 12 May 2026 we asked you to pay EUR 80.00.",
    # (its 'Mit Bescheid vom 30.05.2026 wird der mit Bescheid vom 12.05.2026 festgesetzte Betrag geändert.' is in the revoking test: the first date is that letter's own)
    "Die Mahngebühr wird zusätzlich zu dem mit Bescheid vom 12.05.2026 erhobenen Betrag fällig.",
    "Ebenso wie mit Bescheid vom 12.05.2026 wird die Gebühr auch für 2027 erhoben.",
    "Mit Rechnung vom 12.05.2026 wird Ihnen der Betrag von 80,00 EUR berechnet.",
    "Die Forderung wird nicht mehr, wie zunächst mit Bescheid vom 12.05.2026 vorgesehen, erhoben.",
    "Soweit Ihnen mit Bescheid vom 12.05.2026 Leistungen bewilligt wurden, wird dieser Bescheid aufgehoben.",
    "Die Gebühr wird statt mit Bescheid vom 12.05.2026 nun mit diesem Bescheid festgesetzt.",
    "Die Gebühr wird insoweit abweichend von mit Bescheid vom 12.05.2026 getroffenen Regelungen festgesetzt.",
    "Ihr Einspruch, den Sie mit Schreiben vom 12.05.2026 eingelegt haben, wird zurückgewiesen.",
    "Wir bedanken uns für Ihre Nachricht; mit Schreiben vom 12.05.2026 bitten Sie um Ratenzahlung.",
    "Die Raten werden wie mit Schreiben vom 12.05.2026 vereinbart eingezogen.",
    "Hiermit wird auch die mit Schreiben vom 12.05.2026 gewährte Stundung widerrufen.",
    "Die Gebühr wird nach Maßgabe des mit Bescheid vom 12.05.2026 festgelegten Tarifs berechnet.",
    "Insoweit wird auf die Begründung im Bescheid vom 12.05.2026 verwiesen.",
    "Die Gebühr wird für die mit Bescheid vom 12.05.2026 erteilte Genehmigung erhoben.",
    "Die Gebühr wird für mit Bescheid vom 12.05.2026 erteilte Genehmigungen erhoben.",
    "Die Gebühr wird für mit Bescheid vom 12.05.2026 im Mai erteilte Genehmigungen erhoben.",
    "Die Erstattung wird mit Bescheid vom 12.05.2026 in Höhe von 50,00 EUR aufgerechnet, der noch offen ist.",
    "Die Kosten werden um den mit Bescheid vom 12.05.2026 erstatteten Betrag gemindert.",
    "Die Kosten werden um mit Bescheid vom 12.05.2026 schon erstattete 50,00 EUR gemindert.",
    # review 3: every sentence of its probe that names another decision's date
    "Hiermit wird Ihr mit Schreiben vom 12.05.2026 bei der Stadt Musterstadt eingelegter Widerspruch zurückgewiesen.",
    "Hiermit wird Ihr mit Schreiben vom 12.05.2026 fristgerecht und formgerecht eingelegter Widerspruch zurückgewiesen.",
    "Hiermit wird unser mit Schreiben vom 12.05.2026 an Sie gerichtetes Angebot widerrufen.",
    "Hiermit wird ein mit Bescheid vom 12.05.2026 zu Unrecht gewährter Betrag von 200,00 EUR zurückgefordert.",
    "Hiermit werden alle mit Bescheid vom 12.05.2026 für 2025 bewilligten Leistungen aufgehoben.",
    "Hiermit werden sämtliche mit Bescheid vom 12.05.2026 für das Jahr 2025 erhobenen Beiträge erstattet.",
    "Hiermit werden mit Bescheid vom 12.05.2026 nur vorläufig bewilligte Leistungen endgültig festgesetzt.",
    "Die Gebühr wird in mit Bescheid vom 12.05.2026 für 2025 festgesetzter Höhe erneut erhoben.",
    "Die Kosten werden durch mit Bescheid vom 12.05.2026 zum 1. Juli bewilligte Zuschüsse gedeckt.",
    "Die Gebühr wird einschließlich mit Bescheid vom 12.05.2026 für 2025 festgesetzter Zinsen erhoben.",
    "Die Gebühr wird zuzüglich mit Bescheid vom 12.05.2026 auf 10,00 EUR festgesetzter Mahngebühren fällig.",
    "Die Gebühr wird nunmehr entgegen mit Bescheid vom 12.05.2026 im Mai getroffener Festsetzung ermäßigt.",
    "Die Gebühr wird ohne mit Bescheid vom 12.05.2026 im Mai gewährte Ermäßigung erhoben.",
    "In the notice of 12 May 2026, the following error is hereby corrected:",
    "In the notice of 12 May 2026 the amount stated is hereby corrected to EUR 50.",
    "In our letter of 12 May 2026 the deadline given is hereby extended to the end of June.",
    "Your objection to the notice of 12 May 2026 is hereby rejected.",
    "With the notice of 12 May 2026, which we hereby revoke, you were granted a permit.",
    "By the decision of 12 May 2026 the permit was granted; it is hereby revoked.",
    "In our letter of 12 May 2026 we informed you of the hearing.",
    "Mit Bescheid vom 12.05.2026 setzte die Stadt Musterstadt die Gebühr fest.",
    "Mit Schreiben vom 12.05.2026 erheben Sie Widerspruch.",
    "Mit Schreiben vom 12.05.2026 teilten wir Ihnen mit, dass die Frist abläuft.",
    "Nachdem Ihnen mit Bescheid vom 12.05.2026 Wohngeld bewilligt wurde, wird die Zahlung eingestellt.",
    "Das mit Bescheid vom 12.05.2026 eingeleitete Verfahren wird eingestellt.",
    "Gegen den mit Bescheid vom 12.05.2026 erlassenen Bußgeldbescheid haben Sie Einspruch eingelegt.",
    "Die mit Rechnung vom 12.05.2026 geforderte Zahlung steht noch aus.",
    "Als Anlage erhalten Sie eine Kopie des Bescheides vom 12.05.2026.",
    "Wir verweisen auf unseren Bescheid vom 12.05.2026.",
    "Hiermit wird die Ihnen mit Bescheid vom 12.05.2026 erteilte Erlaubnis widerrufen.",
    "Ihr mit Schreiben vom 12.05.2026 eingelegter Widerspruch wird zurückgewiesen.",
    "Hiermit wird der Widerspruch gegen mit Bescheid vom 12.05.2026 im Mai festgesetzte Gebühren zurückgewiesen.",
    "Ihrem Antrag mit Schreiben vom 12.05.2026 wird entsprochen.",
    "Mit Schreiben vom 12.05.2026 beantragen Sie die Stundung.",
    "Die Rechnung vom 12.05.2026 wird hiermit storniert.",
    "Der Bescheid vom 12.05.2026 wird mit Wirkung für die Zukunft widerrufen.",
    "Hiermit wird eine mit Bescheid vom 12.05.2026 ab Juni bewilligte Leistung eingestellt.",
    "Hiermit werden diese mit Bescheid vom 12.05.2026 für 2025 erhobenen Gebühren erstattet.",
    "Unter Aufhebung des Bescheides vom 12.05.2026 wird die Gebühr neu festgesetzt.",
    "Die Gebühr wird zusätzlich mit Bescheid vom 12.05.2026 im Mai festgesetzt, wie Ihnen bekannt ist.",
    "Hiermit wird keine mit Bescheid vom 12.05.2026 für 2025 gewährte Zahlung zurückgefordert.",
    "Hiermit werden beide mit Bescheid vom 12.05.2026 für 2025 erteilten Genehmigungen widerrufen.",
]

#: More of how authorities name an earlier decision, made up: objection decisions, corrections, set-offs,
#: reminders, enforcement, revocations and the final setting of benefits granted provisionally, in German and
#: English. None may count; several use only words of the listed classes, set where no form has a slot for them.
MORE_EARLIER_DECISIONS = [
    pytest.param(
        "Auf Ihren Widerspruch vom 09.06.2026 wird der Bescheid aufgehoben.", id="auf-ihren-widerspruch"
    ),
    pytest.param(
        "Der Widerspruch gegen den Bescheid vom 09.06.2026 wird als unbegründet zurückgewiesen.",
        id="objection-decision-gegen-den-bescheid",
    ),
    pytest.param(
        "Den Widerspruch mit Schreiben vom 09.06.2026 weisen wir zurück.", id="den-widerspruch-mit-schreiben"
    ),
    pytest.param("Der Bescheid vom 09.06.2026 wird hiermit berichtigt.", id="correction"),
    pytest.param(
        "Der Bescheid vom 09.06.2026 ist offenbar unrichtig und wird nach § 42 VwVfG berichtigt.",
        id="correction-42",
    ),
    pytest.param(
        "In dem Bescheid vom 09.06.2026 wird der Betrag auf 80,00 EUR berichtigt.", id="correction-in-dem"
    ),
    pytest.param(
        "Die mit Bescheid vom 09.06.2026 gewährte Leistung wird endgültig festgesetzt.",
        id="final-setting-attribute",
    ),
    pytest.param(
        "Die Leistungen, die Ihnen mit Bescheid vom 09.06.2026 vorläufig bewilligt wurden, werden endgültig festgesetzt.",
        id="final-setting-relative-clause",
    ),
    pytest.param(
        "Endgültig festgesetzt werden die mit Bescheid vom 09.06.2026 vorläufig bewilligten Leistungen.",
        id="final-setting-participle-first",
    ),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 vorläufig bewilligte Leistungen werden nunmehr endgültig festgesetzt.",
        id="final-setting-opening-attribute",
    ),
    pytest.param(
        "Die Erstattungsforderung wird mit der mit Bescheid vom 09.06.2026 bewilligten Nachzahlung aufgerechnet.",
        id="set-off-attribute",
    ),
    pytest.param("Wir rechnen mit der Forderung aus dem Bescheid vom 09.06.2026 auf.", id="set-off-aus-dem"),
    pytest.param("Die Nachzahlung wird mit dem Bescheid vom 09.06.2026 verbunden.", id="verbunden"),
    pytest.param(
        "Die Forderung aus dem Bescheid vom 09.06.2026 ist trotz Mahnung nicht beglichen.", id="reminder-open"
    ),
    pytest.param(
        "Wir mahnen die mit Bescheid vom 09.06.2026 festgesetzte Gebühr an.", id="reminder-attribute"
    ),
    pytest.param(
        "Wegen der mit Bescheid vom 09.06.2026 festgesetzten Forderung wird die Vollstreckung eingeleitet.",
        id="enforcement-wegen",
    ),
    pytest.param("Die Pfändung erfolgt aufgrund des Bescheides vom 09.06.2026.", id="enforcement-aufgrund"),
    pytest.param(
        "Die Säumniszuschläge werden auf den mit Bescheid vom 09.06.2026 festgesetzten Betrag erhoben.",
        id="surcharge-attribute",
    ),
    pytest.param("Hiermit widerrufen wir den Bescheid vom 09.06.2026.", id="revocation-widerrufen-wir"),
    pytest.param(
        "Der Bescheid vom 09.06.2026 wird mit Wirkung für die Zukunft widerrufen.",
        id="revocation-for-the-future",
    ),
    pytest.param("Hiermit wird der Bescheid vom 09.06.2026 aufgehoben.", id="revocation-hiermit-wird-der"),
    pytest.param(
        "Die Ihnen mit Bescheid vom 09.06.2026 bewilligte Leistung wird zurückgefordert.",
        id="die-ihnen-bewilligte",
    ),
    pytest.param(
        "Die Gebühr wird mit Bescheid vom 09.06.2026 und diesem Bescheid festgesetzt.", id="und-diesem"
    ),
    pytest.param(
        "Die Gebühr wird mit Bescheid vom 09.06.2026 festgesetzt, der jedoch aufgehoben ist.",
        id="participle-not-ending-the-sentence",
    ),
    pytest.param("Die Gebühr wird gemäß Bescheid vom 09.06.2026 erhoben.", id="gemaess"),
    pytest.param("Die Gebühr wird nach dem Bescheid vom 09.06.2026 festgesetzt.", id="nach-dem"),
    pytest.param("Die Gebühr wird wie im Bescheid vom 09.06.2026 festgesetzt erhoben.", id="wie-im"),
    pytest.param("Im Bescheid vom 09.06.2026 wurde die Gebühr zu hoch festgesetzt.", id="im-bescheid-wurde"),
    pytest.param(
        "Gegen den Bescheid vom 09.06.2026 haben Sie fristgerecht Widerspruch erhoben.", id="gegen-den"
    ),
    pytest.param(
        "Mit Ihrem Widerspruch vom 09.06.2026 wenden Sie sich gegen den Bescheid.", id="ihr-widerspruch"
    ),
    pytest.param(
        "Mit Widerspruch vom 09.06.2026 wird der Bescheid angefochten.", id="the-persons-objection-noun"
    ),
    pytest.param("Der Bescheid vom 09.06.2026 erging ohne Anhörung.", id="der-bescheid-erging"),
    pytest.param("Mit Schreiben vom 09.06.2026 erhielten Sie die Abrechnung.", id="erhielten-sie"),
    pytest.param("With our notice of 9 June 2026 we informed you that the fee is due.", id="en-we-informed"),
    pytest.param(
        "Mit Schreiben vom 09.06.2026 teilen Sie mit, dass Sie umgezogen sind.",
        id="the-persons-letter-teilen-sie",
    ),
    pytest.param(
        "Mit Schreiben vom 09.06.2026 wird von Ihnen die Erstattung beantragt.",
        id="the-persons-letter-passive",
    ),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 hatte das Jobcenter vorläufig Leistungen bewilligt.",
        id="pluperfect-jobcenter",
    ),
    pytest.param(
        "Mit Bescheid vom 09.06.2026 waren Ihnen Leistungen bewilligt worden.", id="pluperfect-passive"
    ),
    pytest.param(
        "Nachdem mit Bescheid vom 09.06.2026 die Gebühr festgesetzt wurde, wird nun gemahnt.", id="nachdem"
    ),
    pytest.param(
        "Soweit mit Bescheid vom 09.06.2026 Leistungen bewilligt werden, bleibt es dabei.", id="soweit"
    ),
    pytest.param(
        "Ihnen wird mitgeteilt, dass der Bescheid vom 09.06.2026 bestandskräftig ist.", id="dass-der-bescheid"
    ),
    pytest.param("In our decision of 9 June 2026 we refused your application.", id="en-in-our-decision"),
    pytest.param("In the notice of 9 June 2026 the fee is hereby corrected to EUR 50.", id="en-correction"),
    pytest.param("By decision dated 9 June 2026 the fee was assessed at EUR 80.", id="en-was-assessed"),
    pytest.param(
        "With reference to the notice dated 9 June 2026, we hereby request payment.",
        id="en-with-reference-to",
    ),
    pytest.param(
        "Your objection to the notice dated 9 June 2026 is hereby rejected.", id="en-objection-decision"
    ),
    pytest.param(
        "The decision of 9 June 2026 is hereby revoked with effect for the future.", id="en-revocation"
    ),
    pytest.param(
        "Further to our notice dated 9 June 2026 we remind you that the fee is outstanding.", id="en-reminder"
    ),
    pytest.param(
        "The amount assessed by decision dated 9 June 2026 is set off against your refund.", id="en-set-off"
    ),
    pytest.param("By decision dated 9 June 2026, as amended, we assessed the fee.", id="en-as-amended"),
    pytest.param(
        "Enforcement is hereby started for the amount set by notice dated 9 June 2026.", id="en-enforcement"
    ),
    pytest.param("We refer to our decision dated 9 June 2026 and hereby set the fee.", id="en-we-refer-to"),
    pytest.param(
        "By our decision dated 9 June 2026 we had granted the benefit provisionally.", id="en-pluperfect"
    ),
    pytest.param("With your letter dated 9 June 2026 you objected to the fee.", id="en-your-letter"),
    pytest.param("By decision dated 9 June 2026 you were granted a permit.", id="en-you-were-granted"),
    pytest.param(
        "By decision dated 9 June 2026 the provisional fee is hereby assessed at EUR 80.",
        id="en-two-words-before-is",
    ),
]


#: Every sentence the attack on the closed rebuild wrote to name another decision's or letter's date (its probe,
#: made-up letters of the Stadt Musterstadt), by route: a state an earlier decision left (A), a present passive
#: telling of one (B), a set-off or comparison (C), "ergeht" (D), English (E), the verb before "mit" with another
#: authority (F), a line broken after a number (G), a heading (H), the person's letter, an invoice or an enclosure
#: (I), reminders and enforcement (J), a correction or revocation (K), a provisional decision made final (L),
#: another authority after the verb (M), and its rows built from listed words only (Z); then the contract review's own (a quote, a line broken after a
#: date, a heading, and its refused sentences verbatim). None may count. Its three rows in the first person and the
#: present tense with one of main's verbs (I5, J1, J2) count on main as here: they are the form's known limit
#: (KNOWN_LIMIT).
THE_CLOSED_ATTACKS_FALSE_RIVALS = [
    pytest.param(
        "Mit Bescheid vom 09.03.2026 erhalten Sie seit dem 01.01.2026 Wohngeld in Höhe von 210,00 EUR monatlich.",
        id="A1",
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 erhalten Sie laufend Leistungen nach dem SGB II; diese Leistungen ändern wir nun.",
        id="A2",
    ),
    pytest.param(
        "Mit Bewilligungsbescheid vom 09.03.2026 erhalten Sie bis zum 30.09.2026 Elterngeld.", id="A3"
    ),
    pytest.param(
        "Mit Schreiben vom 09.03.2026 erhalten Sie von der Familienkasse eine Abrechnung, auf die wir verweisen.",
        id="A4",
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 erhalten Sie bereits eine Erstattung; eine zweite ist nicht möglich.",
        id="A5",
    ),
    pytest.param(
        "Mit Rentenbescheid vom 09.03.2026 erhalten Sie eine Rente, die wir als Einkommen anrechnen.", id="A6"
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 wird der Grundsteuermessbetrag vom Finanzamt festgesetzt; daran ist die Stadt gebunden.",
        id="B1",
    ),
    pytest.param(
        "Mit Feststellungsbescheid vom 09.03.2026 werden die Besteuerungsgrundlagen festgestellt, an die wir gebunden sind.",
        id="B2",
    ),
    pytest.param(
        "Mit Grundlagenbescheid vom 09.03.2026 wird über den Messbetrag entschieden; diesen Bescheid erlässt das Finanzamt.",
        id="B3",
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 werden Ihnen Leistungen vorläufig bewilligt; diese setzen wir heute endgültig fest.",
        id="B4",
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 wird der Betrag von 80,00 EUR zum 01.04.2026 fällig, den Sie noch nicht gezahlt haben.",
        id="B5",
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 wird Ihr Antrag abgelehnt. Hiergegen richtet sich Ihr Widerspruch.",
        id="B6",
    ),
    pytest.param("Mit Mahnbescheid vom 09.03.2026 wird die Forderung gerichtlich geltend gemacht.", id="B7"),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 werden die Vorauszahlungen angepasst, die das Finanzamt erhebt.", id="B8"
    ),
    pytest.param(
        "Mit Vollstreckungsbescheid vom 09.03.2026 wird die Forderung tituliert; wir vollstrecken daraus.",
        id="B9",
    ),
    pytest.param("Mit Bescheid vom 09.03.2026 wird nach Ihrer Auffassung zu viel gefordert.", id="B10"),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 wird laut Ihrem Widerspruch die Gebühr falsch berechnet.", id="B11"
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 wird, wie Sie schreiben, die Gebühr doppelt erhoben.", id="B12"
    ),
    pytest.param("Mit dem Bescheid vom 09.03.2026 wird Ihr Guthaben von 80,00 EUR verrechnet.", id="C1"),
    pytest.param("Mit dem Bescheid vom 09.03.2026 wird die Erstattung aufgerechnet.", id="C2"),
    pytest.param("Mit dem Bescheid vom 09.03.2026 wird dieser Bescheid verbunden.", id="C3"),
    pytest.param("Mit dem Bescheid vom 09.03.2026 werden die neuen Zahlen verglichen.", id="C4"),
    pytest.param("Mit Bescheid vom 09.03.2026 wird verrechnet, was Sie zu viel gezahlt haben.", id="C5"),
    pytest.param("Mit dem Abrechnungsbescheid vom 09.03.2026 wird die Nachzahlung verrechnet.", id="C6"),
    pytest.param("Mit dem Bescheid vom 09.03.2026 werden Ihre Zahlungen abgeglichen.", id="C7"),
    pytest.param(
        "Der Bescheid vom 09.03.2026 ergeht weiterhin unter Vorbehalt der Nachprüfung; das ändert dieser Bescheid nicht.",
        id="D1",
    ),
    pytest.param(
        "Der Mahnbescheid vom 09.03.2026 ergeht an Ihren früheren Wohnsitz, wie Sie vortragen.", id="D2"
    ),
    pytest.param(
        "Der Änderungsbescheid vom 09.03.2026 ergeht kraft Gesetzes vorläufig, wir heben ihn hiermit auf.",
        id="D3",
    ),
    pytest.param("Mit Bescheid vom 09.03.2026 ergeht nach Ihrer Ansicht eine falsche Entscheidung.", id="D4"),
    pytest.param(
        "Der Widerspruchsbescheid vom 09.03.2026 ergeht nach Angaben des Landratsamts kostenfrei.", id="D5"
    ),
    pytest.param(
        "By decision dated 9 March 2026 we set the fee at EUR 80.00. That decision is revoked.", id="E1"
    ),
    pytest.param("By notice dated 9 March 2026, we set your rent subsidy; we now amend it.", id="E2"),
    pytest.param("With our notice of 9 March 2026 we set a deadline that you missed.", id="E3"),
    pytest.param("By the decision of 9 March 2026 we set the fee too high, so we correct it below.", id="E4"),
    pytest.param(
        "By decision dated 9 March 2026 we grant you housing benefit until December, as you know.", id="E5"
    ),
    pytest.param("With the notice dated 9 March 2026 we inform you every year about the tax.", id="E6"),
    pytest.param("By our decision of 9 March 2026, we request payment, which is still outstanding.", id="E7"),
    pytest.param("By decision dated 9 March 2026 we hereby set off your refund.", id="E8"),
    pytest.param("With decision dated 9 March 2026 we compare the figures below.", id="E9"),
    pytest.param(
        "By the notice dated 9 March 2026, the fee is hereby assessed by the tax office, not by us.", id="E10"
    ),
    pytest.param(
        "Der Grundsteuermessbetrag wird mit Bescheid vom 09.03.2026 des Finanzamts festgesetzt.", id="F1"
    ),
    pytest.param("Das Wohngeld wird mit Bescheid vom 09.03.2026 von der Wohngeldstelle bewilligt.", id="F2"),
    pytest.param("Die Steuer wird mit Bescheid vom 09.03.2026 von dem Finanzamt erhoben.", id="F3"),
    pytest.param("Die Rente wird mit Bescheid vom 09.03.2026 der Rentenversicherung gewährt.", id="F4"),
    pytest.param("Der Kinderzuschlag wird mit Bescheid vom 09.03.2026 der Familienkasse abgelehnt.", id="F5"),
    pytest.param(
        "Die Kosten werden mit Bescheid vom 09.03.2026 im Widerspruchsverfahren festgesetzt.", id="F6"
    ),
    pytest.param(
        "Die Leistung wird mit Bescheid vom 09.03.2026 des Jobcenters für den Monat April erstattet.", id="F7"
    ),
    pytest.param(
        "Ihnen wird mit Bescheid vom 09.03.2026 von der Krankenkasse ein Zuschuss gewährt.", id="F8"
    ),
    pytest.param("Der Bescheid wird mit Bescheid vom 09.03.2026 des Landratsamts aufgehoben.", id="F9"),
    pytest.param(
        "Die Gebühr wird mit Bescheid vom 09.03.2026 unter Vorbehalt der Nachprüfung des Finanzamts erhoben.",
        id="F10",
    ),
    pytest.param(
        "Ihre Unterlagen zum Antrag 4711\nmit Schreiben vom 09.03.2026 erhalten Sie anbei zurück.", id="G1"
    ),
    pytest.param(
        "Die Kopien zu Ihrem Antrag vom 01.03.2026\nmit Schreiben vom 09.03.2026 erhalten Sie zurück.",
        id="G2",
    ),
    pytest.param(
        "Wegen der Gebühr 80,00 EUR für 2026\nmit Bescheid vom 09.03.2026 wird auf die Anlage verwiesen.",
        id="G3",
    ),
    pytest.param(
        "Ihre Zahlung zum Kassenzeichen 4711\nmit Bescheid vom 09.03.2026 wird verrechnet.", id="G4"
    ),
    pytest.param(
        "Den Widerspruch gegen den Bescheid Nr. 12\nmit Schreiben vom 09.03.2026 erhalten Sie in Kopie.",
        id="G5",
    ),
    pytest.param("Sachverhalt:\nMit Bescheid vom 09.03.2026 wird Ihr Antrag abgelehnt.", id="H1"),
    pytest.param(
        "Bisheriger Verlauf\nMit Bescheid vom 09.03.2026 werden Ihnen 300,00 EUR erstattet.", id="H2"
    ),
    pytest.param(
        "Zur Erinnerung:\nMit Bescheid vom 09.03.2026 erhalten Sie eine Nachforderung über 80,00 EUR.",
        id="H3",
    ),
    pytest.param(
        "Verlauf: 1. Mit Bescheid vom 09.03.2026 wird die Gebühr erhoben. 2. Sie zahlen nicht.", id="H4"
    ),
    pytest.param(
        "Hinweis zum Vorbescheid\nMit Bescheid vom 09.03.2026 ergeht nur eine vorläufige Entscheidung.",
        id="H5",
    ),
    pytest.param("Mit Schreiben vom 09.03.2026 bitten wir als Eheleute um Aufschub, schreiben Sie.", id="I1"),
    pytest.param("Mit Ihrem Schreiben vom 09.03.2026 erhalten Sie unsere Antwort.", id="I2"),
    pytest.param("Mit Rechnung vom 09.03.2026 erhalten Sie die Kosten des Gutachters.", id="I3"),
    pytest.param(
        "Mit Schreiben vom 09.03.2026 erhalten Sie die Anlage, die wir Ihnen erneut beifügen.", id="I4"
    ),
    pytest.param("Anlage: Mit Bescheid vom 09.03.2026 erhalten Sie die Abrechnung.", id="I6"),
    pytest.param(
        "Mit Kostenbescheid vom 09.03.2026 erhalten Sie die Rechnung des Abschleppdienstes.", id="I7"
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 wird eine Gebühr festgesetzt, die noch offen ist; wir vollstrecken sie.",
        id="J3",
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 werden Säumniszuschläge erhoben, die wir jetzt beitreiben.", id="J4"
    ),
    pytest.param("Mit Bescheid vom 09.03.2026 erinnern wir Sie zum zweiten Mal; heute mahnen wir.", id="J5"),
    pytest.param(
        "Mit Leistungsbescheid vom 09.03.2026 wird der Betrag gefordert, aus dem wir nun vollstrecken.",
        id="J6",
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 wird Ihnen zu Unrecht Wohngeld bewilligt; diesen Bescheid nehmen wir zurück.",
        id="K1",
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 wird die Gebühr irrtümlich zu hoch festgesetzt. Wir berichtigen das.",
        id="K2",
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 werden 100,00 EUR erstattet, nach diesem Bescheid nur 60,00 EUR.",
        id="K3",
    ),
    pytest.param("Mit Bescheid vom 09.03.2026 ergeht ein Bescheid, den wir hiermit widerrufen.", id="K4"),
    pytest.param(
        "Die Gebühr wird mit Bescheid vom 09.03.2026 auf 80,00 EUR festgesetzt, nicht wie jetzt auf 60,00 EUR.",
        id="K5",
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 wird Ihnen ein Zuschuss gewährt, der hiermit widerrufen wird.", id="K6"
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 werden Ihnen Leistungen vorläufig gewährt. Abschließend setzen wir fest:",
        id="L1",
    ),
    pytest.param("Mit vorläufigem Bescheid vom 09.03.2026 erhalten Sie 400,00 EUR.", id="L2"),
    pytest.param(
        "Die Leistungen werden mit Bescheid vom 09.03.2026 vorläufig bewilligt; nun entscheiden wir abschließend.",
        id="L3",
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 ergehen die Festsetzungen vorläufig; dieser Bescheid ist endgültig.",
        id="L4",
    ),
    pytest.param("Mit Bescheid vom 09.03.2026 wird vom Landratsamt die Fahrerlaubnis entzogen.", id="M1"),
    pytest.param("Mit Bescheid vom 09.03.2026 werden durch die Bundesagentur Leistungen bewilligt.", id="M2"),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 erhalten Sie von der Deutschen Rentenversicherung eine Rente.", id="M3"
    ),
    pytest.param("Mit Schreiben vom 09.03.2026 erhalten Sie vom Amtsgericht eine Ladung.", id="M4"),
    pytest.param("Die Steuer wird mit Bescheid vom 09.03.2026 von dem Finanzamt festgesetzt.", id="Z1"),
    pytest.param("Der Messbetrag wird mit Bescheid vom 09.03.2026 des Finanzamts festgesetzt.", id="Z2"),
    pytest.param("Die Rente wird mit Bescheid vom 09.03.2026 von der Rentenversicherung gewährt.", id="Z3"),
    pytest.param("Der Antrag wird mit Bescheid vom 09.03.2026 der Familienkasse abgelehnt.", id="Z4"),
    pytest.param(
        "Die Kosten werden mit Bescheid vom 09.03.2026 im Widerspruchsverfahren festgesetzt.", id="Z5"
    ),
    pytest.param(
        "Die Erstattung wird mit Bescheid vom 09.03.2026 von dem Jobcenter zurückgefordert.", id="Z6"
    ),
    pytest.param(
        "Mit Bescheid vom 09.03.2026 werden Ihnen von der Wohngeldstelle 200,00 EUR bewilligt.", id="Z7"
    ),
    pytest.param("Mit Bescheid vom 09.03.2026 erhalten Sie von der Rentenversicherung 400,00 EUR.", id="Z8"),
    pytest.param("Mit Schreiben vom 09.03.2026 erhalten Sie von dem Amtsgericht die Ladung.", id="Z9"),
    pytest.param("By decision dated 9 March 2026 we set the fee.", id="Z10"),
    pytest.param("By the notice of 9 March 2026 we set the tax.", id="Z11"),
    pytest.param("Der Bescheid vom 09.03.2026 ergeht von dem Finanzamt.", id="Z12"),
    pytest.param("Mit Bescheid vom 09.03.2026 ergeht von der Kreiskasse die Festsetzung.", id="Z13"),
    pytest.param("Das Guthaben wird mit dem Bescheid vom 09.03.2026 aufgerechnet.", id="Z14"),
    pytest.param(
        "Der Zuschuss wird mit Bescheid vom 09.03.2026 unter dem Vorbehalt der Familienkasse gewährt.",
        id="Z15",
    ),
    pytest.param(
        "Ihnen wird mit Bescheid vom 09.03.2026 von der Familienkasse ein Zuschlag gewährt.", id="Z16"
    ),
    pytest.param("Der Bescheid wird mit Bescheid vom 09.03.2026 des Landratsamts aufgehoben.", id="Z17"),
    pytest.param(
        "Die Gebühr wird mit Bescheid vom 09.03.2026 für den Bescheid des Landratsamts erhoben.", id="Z18"
    ),
    pytest.param("Mit dem Bescheid vom 09.03.2026 wird der Bescheid von der Kreiskasse geändert.", id="Z19"),
    pytest.param(
        "Die Leistung wird mit Bescheid vom 09.03.2026 in dem Verfahren des Jobcenters bewilligt.", id="Z20"
    ),
    pytest.param("With the notice of 9 March 2026 the fee is hereby assessed.", id="Z21"),
    pytest.param(
        "Die Gebühr wird mit Bescheid vom 09.03.2026 von 80,00 EUR auf 60,00 EUR geändert.", id="Z22"
    ),
    pytest.param("Die Steuer wird mit Bescheid vom 09.03.2026 für 2025 festgesetzt.", id="Z23"),
    pytest.param("Mit Bescheid vom 09.03.2026 wird Ihnen von dem Finanzamt die Steuer erstattet.", id="Z24"),
    pytest.param("Der Beitrag wird mit Bescheid vom 09.03.2026 von der Krankenkasse erhoben.", id="Z25"),
    pytest.param(
        "Im Widerspruchsverfahren gilt:\nMit Bescheid vom 01.06.2026 wird die Gebühr festgesetzt; dieser Bescheid ist rechtswidrig.",
        id="quoted-or-wrapped-0",
    ),
    pytest.param(
        "Sie tragen vor: Mit Bescheid vom 01.06.2026 setzen wir die Gebühr fest.", id="quoted-or-wrapped-1"
    ),
    pytest.param(
        "Ihr Widerspruch vom 03.06.2026\nmit Bescheid vom 01.06.2026 setzen wir die Gebühr fest, wie Sie meinen.",
        id="quoted-or-wrapped-2",
    ),
    pytest.param(
        "„Mit Bescheid vom 01.06.2026 setzen wir die Gebühr fest.“ So steht es in Ihrem Bescheid.",
        id="quoted-or-wrapped-3",
    ),
    pytest.param(
        '"Mit Bescheid vom 01.06.2026 setzen wir die Gebühr fest." heißt es dort.', id="quoted-or-wrapped-4"
    ),
    pytest.param(
        "Der Bescheid vom 01.06.2026 bleibt bestehen; der Bescheid vom 03.06.2026 ergeht gesondert.",
        id="quoted-or-wrapped-5",
    ),
    pytest.param(
        "Mit Bescheid vom 01.06.2026 ergehen die Gebühren des Vorjahres nicht mehr.", id="quoted-or-wrapped-6"
    ),
    pytest.param(
        "Mit Schreiben vom 01.06.2026 erhalten Sie keine weitere Nachricht von uns, wie Sie wünschten.",
        id="quoted-or-wrapped-7",
    ),
    pytest.param(
        "Zu Ziffer 2:\nMit Bescheid vom 01.06.2026 werden die Kosten festgesetzt, die wir mit diesem Bescheid aufheben.",
        id="quoted-or-wrapped-14",
    ),
    pytest.param(
        "Vorgang 2026/17   01.06.2026\nmit Bescheid vom 01.06.2026 wird dieser Vorgang ersetzt.",
        id="quoted-or-wrapped-15",
    ),
    # the contract review's refused sentences, verbatim
    pytest.param("Die Gebühr wird mit Bescheid vom 01.06.2026 aufgehoben.", id="contract-8"),
    pytest.param("Ihnen wird mit Bescheid vom 01.06.2026 die Erlaubnis erteilt.", id="contract-9"),
    pytest.param("Die Erlaubnis wird nunmehr mit Bescheid vom 01.06.2026 aufgehoben.", id="contract-10"),
    pytest.param("By notice dated 1 June 2026 we revoke the decision dated 3 June 2026.", id="contract-11"),
    pytest.param("Hereby, with the notice of 1 June 2026, we confirm the fee.", id="contract-12"),
    pytest.param("With the notice of 1 June 2026, the fees are hereby assessed.", id="contract-13"),
    pytest.param("Mit Bescheid vom 01.06.2026 (Az. 3-4) wird nichts geändert.", id="contract-16"),
    pytest.param("Mit Bescheid vom 01.06.2026 werden.", id="contract-17"),
]


def test_another_decisions_date_is_not_the_letters_own() -> None:
    check_rows(
        [
            *ANOTHER_DECISIONS_DATE,
            *THE_REVIEWS_FALSE_RIVALS,
            *MORE_EARLIER_DECISIONS,
            *THE_CLOSED_ATTACKS_FALSE_RIVALS,
        ],
        lambda sentence: _assert_equal(_own_dates(sentence), []),
        at_least=300,
    )


def test_a_decision_that_revokes_an_earlier_one_gives_only_its_own_date() -> None:
    """The new decision's date is its own; the old decision's, named in the same sentence, is not."""
    assert _own_dates(
        "Mit Bescheid vom 10.06.2026 heben wir die mit Bescheid vom 05.06.2026 bewilligten Leistungen auf."
    ) == [date(2026, 6, 10)]
    assert _own_dates("Mit Bescheid vom 10.06.2026 heben wir den Bescheid vom 05.06.2026 auf.") == [
        date(2026, 6, 10)
    ]
    assert _own_dates(
        "Mit Bescheid vom 30.05.2026 ändern wir den mit Bescheid vom 12.05.2026 festgesetzten Betrag."
    ) == [date(2026, 5, 30)]


def test_a_decision_dated_a_day_before_its_header_counts_from_the_earlier_date() -> None:
    """A made-up municipal fee decision dated Wed 10 Jun 2026 in its header names its decision Tue 9 Jun 2026 in
    its text ("mit Bescheid vom … setzen wir … fest"): the objection month counts from the earlier date, the
    receipt names both and the to-do is "Please check"."""
    from ordnung.ingest.plan import checked_evidence

    text = (
        "Stadt Musterstadt · Ordnungsamt\nDatum: 10.06.2026\nSehr geehrte Frau Beispiel,\n"
        "mit Bescheid vom 09.06.2026 setzen wir für die Sondernutzung eine Gebühr von 80,00 EUR fest.\n"
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.\n"
    )
    objection = item(
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
        kind="deadline",
        type="relative",
        amount=1,
        unit="months",
        anchor="deemed_delivery",
        delivery_rule="de_admin_post",
        nature="objection",
    )
    [verified] = read(text, objection, kind="authority_letter")
    assert {rival.letter_date for rival in verified.rivals} == {date(2026, 6, 9), date(2026, 6, 10)}
    ctx = RuleContext(
        today=date(2026, 6, 12), document_date=date(2026, 6, 10), delivery_scope="vwvfg", region="NW"
    )
    alone = _alone(verified, ctx)
    result = computed(verified, ctx)
    # posted Tue 9 Jun: delivered Sat 13 Jun (no move under the VwVfG), one month → Mon 13 Jul;
    # posted Wed 10 Jun: delivered Sun 14 Jun → Tue 14 Jul
    assert alone.due_date == "2026-07-14"
    assert result.due_date == "2026-07-13"
    assert result.conflict
    assert not checked_evidence(verified, result).value_consistent  # "Please check"
    receipt = result.receipt
    assert receipt is not None and receipt.confidence == "low" and CONFLICTING_DATES in receipt.rule_ids
    [warning] = [w for w in receipt.warnings if "gives two dates for itself" in w]
    assert "Tue 9 Jun 2026" in warning and "Wed 10 Jun 2026" in warning


def test_an_earlier_decision_named_a_day_before_the_letter_is_no_second_date() -> None:
    """The same letter that changes a decision of the day before ("Der Bescheid vom … wird geändert", "Mit
    Bescheid vom … wurde …"): one date, its own, nothing to check."""
    text = (
        "Stadt Musterstadt · Ordnungsamt\nDatum: 10.06.2026\nSehr geehrte Frau Beispiel,\n"
        "der Bescheid vom 09.06.2026 wird geändert. Mit Bescheid vom 09.06.2026 wurde die Gebühr auf 90,00 EUR "
        "festgesetzt. Die mit Bescheid vom 09.06.2026 festgesetzte Gebühr wird auf 80,00 EUR herabgesetzt.\n"
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.\n"
    )
    objection = item(
        "Gegen diesen Bescheid kann innerhalb eines Monats nach Bekanntgabe Widerspruch erhoben werden.",
        kind="deadline",
        type="relative",
        amount=1,
        unit="months",
        anchor="deemed_delivery",
        delivery_rule="de_admin_post",
        nature="objection",
    )
    [verified] = read(text, objection, kind="authority_letter")
    assert {rival.letter_date for rival in verified.rivals} == {date(2026, 6, 10)}
    ctx = RuleContext(
        today=date(2026, 6, 12), document_date=date(2026, 6, 10), delivery_scope="vwvfg", region="NW"
    )
    result = computed(verified, ctx)
    assert result.due_date == "2026-07-14" and not result.conflict
