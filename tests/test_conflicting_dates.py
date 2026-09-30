"""Two dates for one obligation: the letter's own text checked for a second deadline statement
(:mod:`ordnung.ingest.conflicts`, SPEC § 8 stage 6, § 21)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import Letter
from ordnung import clock
from ordnung.api.routes.dates import recompute_document_items
from ordnung.ingest.conflicts import CONFLICTING_DATES, find_rivals
from ordnung.ingest.plan import ComputedDate, VerifiedItem, compute_item, needs_check, verify_extraction
from ordnung.models import DocumentExtraction, ExtractedItem
from ordnung.rules import RuleContext, catalog
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


def needs_check_after(verified: VerifiedItem, result: ComputedDate) -> bool:
    from ordnung.ingest.plan import checked_evidence

    return not checked_evidence(verified, result).value_consistent


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
