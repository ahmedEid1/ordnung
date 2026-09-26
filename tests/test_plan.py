"""Verification, confidence grading and writing items by slot (SPEC § 8 stages 5–7, § 21)."""

from __future__ import annotations

from datetime import date
from typing import Any

from ordnung.db.store import Store
from ordnung.ingest.link import LinkResult
from ordnung.ingest.plan import (
    ComputedDate,
    activity_message,
    compute_item,
    grade_receipt,
    payment_details,
    remedy_text,
    remedy_warnings,
    rule_context,
    slot_key,
    slot_keys,
    verify_extraction,
    write_items,
)
from ordnung.ingest.verify import MODEL_READ_NOTE, UNVERIFIED_NOTE
from ordnung.models import (
    ComputationReceipt,
    Document,
    DocumentExtraction,
    Evidence,
    ExtractedItem,
    Item,
    PaymentDetails,
    Profile,
    Recurrence,
    Remedy,
)
from ordnung.rules import RuleContext

PAGE_TEXT = (
    "Musterstadt, 15.09.2026\n"
    "Bitte zahlen Sie 49,99 EUR bis zum 15.10.2026.\n"
    "Der Einspruch ist innerhalb eines Monats nach Bekanntgabe einzulegen."
)
TEXT_PAGE = (1, PAGE_TEXT, [], "text")
TRANSCRIPT_PAGE = (1, PAGE_TEXT, [], "transcript")


def item(quote: str, *, kind: str = "payment", money: float | None = None, **date_spec: Any) -> ExtractedItem:
    spec = date_spec or {"type": "none"}
    return ExtractedItem.model_validate(
        {"kind": kind, "title": "t", "date": spec, "amount": money, "quote": quote}
    )


PAYMENT = item(
    "Bitte zahlen Sie 49,99 EUR bis zum 15.10.2026.",
    money=49.99,
    type="fixed",
    date="2026-10-15",
    nature="payment",
)
OBJECTION = item(
    "Der Einspruch ist innerhalb eines Monats nach Bekanntgabe einzulegen.",
    kind="deadline",
    type="relative",
    amount=1,
    unit="months",
    anchor="deemed_delivery",
    delivery_rule="de_admin_post",
    nature="objection",
)


def extraction(items: list[ExtractedItem], **fields: Any) -> DocumentExtraction:
    return DocumentExtraction(
        kind="invoice", title="Bill", summary="s", explanation="e", items=items, **fields
    )


# --------------------------------------------------------------------------------------------------
# Slot keys
# --------------------------------------------------------------------------------------------------


def test_slot_key_ignores_case_and_spacing_but_not_kind() -> None:
    assert slot_key("payment", "Bitte  zahlen\nSie") == slot_key("payment", "bitte zahlen sie")
    assert slot_key("payment", "x") != slot_key("deadline", "x")


def test_repeated_items_get_distinct_slots() -> None:
    keys = slot_keys([PAYMENT, PAYMENT, OBJECTION])
    assert keys[1] == f"{keys[0]}#2"
    assert len(set(keys)) == 3


# --------------------------------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------------------------------


def test_items_found_on_a_text_page_are_verified() -> None:
    result = verify_extraction("doc_x", extraction([PAYMENT, OBJECTION]), [TEXT_PAGE])
    assert [v.evidence.grounding for v in result.items] == ["verified", "verified"]
    assert all(v.evidence.value_consistent for v in result.items)
    assert not result.needs_review
    assert result.warnings == []


def test_transcript_pages_give_model_read() -> None:
    result = verify_extraction("doc_x", extraction([PAYMENT]), [TRANSCRIPT_PAGE])
    assert result.items[0].evidence.grounding == "model_read"
    assert not result.needs_review


def test_unfound_or_inconsistent_dated_items_need_review() -> None:
    wrong_amount = PAYMENT.model_copy(update={"amount": 59.99})
    result = verify_extraction("doc_x", extraction([wrong_amount]), [TEXT_PAGE])
    assert result.items[0].reasons == ("amount_not_in_quote",)
    assert not result.items[0].evidence.value_consistent
    assert result.needs_review

    missing = item("Zahlen Sie 10,00 EUR bis zum 01.11.2026.", type="fixed", date="2026-11-01")
    result = verify_extraction("doc_x", extraction([missing]), [TEXT_PAGE])
    assert result.items[0].evidence.grounding == "unverified"
    assert result.needs_review
    assert result.warnings == ["Please check: 1 date could not be confirmed against the letter's text."]


def test_undated_items_never_need_review() -> None:
    task = item("Ein Satz, der nicht im Brief steht.", kind="task")
    assert not verify_extraction("doc_x", extraction([task]), [TEXT_PAGE]).needs_review


def test_key_facts_contract_and_remedy_quotes_are_grounded() -> None:
    data = extraction(
        [],
        key_facts=[{"label": "Amount", "value": "49.99", "quote": "Bitte zahlen Sie 49,99 EUR"}],
        remedy={"type": "einspruch", "quote": "Das steht nirgends im Brief."},
        contract={"name": "c", "quotes": ["Der Einspruch ist innerhalb eines Monats"]},
    )
    result = verify_extraction("doc_x", data, [TEXT_PAGE])
    assert result.key_facts[0].evidence is not None and result.key_facts[0].evidence.grounding == "verified"
    assert result.contract_evidence[0].grounding == "verified"
    assert result.remedy_evidence is not None and result.remedy_evidence.grounding == "unverified"
    assert any("Rechtsbehelfsbelehrung" in warning for warning in result.warnings)


# --------------------------------------------------------------------------------------------------
# Compute & grading
# --------------------------------------------------------------------------------------------------


def verified_item(extracted: ExtractedItem, page: tuple[int, str, list[Any], str] = TEXT_PAGE) -> Any:
    return verify_extraction("doc_x", extraction([extracted]), [page]).items[0]


def test_grading_keeps_high_for_verified_consistent_items() -> None:
    receipt = ComputationReceipt(due_date="2026-10-15", confidence="high")
    graded = grade_receipt(receipt, verified_item(PAYMENT))
    assert graded.confidence == "high" and graded.warnings == []


def test_grading_lowers_for_model_read_and_unverified() -> None:
    receipt = ComputationReceipt(due_date="2026-10-15", confidence="high")
    photo = grade_receipt(receipt, verified_item(PAYMENT, TRANSCRIPT_PAGE))
    assert photo.confidence == "medium" and photo.warnings == [MODEL_READ_NOTE]
    lost = item("Nicht im Brief: 01.11.2026", type="fixed", date="2026-11-01")
    unverified = grade_receipt(receipt.model_copy(update={"confidence": "medium"}), verified_item(lost))
    assert unverified.confidence == "low"
    assert UNVERIFIED_NOTE in unverified.warnings


def test_ambiguous_dates_are_always_low() -> None:
    page = (1, "Please pay by 03/05/2027.", [], "text")
    ambiguous = item("Please pay by 03/05/2027.", type="fixed", date="2027-05-03")
    graded = grade_receipt(ComputationReceipt(due_date="2027-05-03"), verified_item(ambiguous, page))
    assert graded.confidence == "low"
    assert any("two ways" in warning for warning in graded.warnings)


def test_compute_item_sources() -> None:
    ctx = RuleContext(today=date(2026, 9, 25), document_date=date(2026, 9, 15), delivery_scope="ao")
    fixed = compute_item(verified_item(PAYMENT), ctx, postal_buffer_days=4)
    assert (fixed.due_date, fixed.source) == ("2026-10-15", "fixed")
    computed = compute_item(verified_item(OBJECTION), ctx, postal_buffer_days=4)
    assert (computed.due_date, computed.source) == ("2026-10-21", "computed")
    undated = compute_item(
        verified_item(item("Bitte zahlen Sie 49,99 EUR", kind="task")), ctx, postal_buffer_days=4
    )
    assert undated == ComputedDate(receipt=None, due_date=None, send_by=None, source="none")


def test_rule_context_from_party_and_document(store: Store) -> None:
    party = store.add_party(name="Finanzamt", kind="tax_office", region="BY")
    document = store.add_document(
        sha256="d" * 64, filename="x", mime="application/pdf", file_path="x", received_date="2026-09-20"
    )
    ctx = rule_context(
        party, document, extraction([], document_date="2026-09-15"), date(2026, 9, 25), recipient_region="NW"
    )
    assert ctx.region == "BY" and ctx.recipient_region == "NW" and ctx.delivery_scope == "ao"
    assert ctx.document_date == date(2026, 9, 15)
    assert ctx.received_date == date(2026, 9, 20) and ctx.received_confirmed
    fallback = rule_context(
        None,
        document.model_copy(update={"received_date": None}),
        extraction([], sender={"name": "AOK", "kind": "health_insurer"}),
        date(2026, 9, 25),
    )
    assert fallback.delivery_scope == "sgbx" and fallback.region is None and not fallback.received_confirmed


def test_rule_context_marks_a_private_sender_but_not_an_unknown_one(store: Store) -> None:
    """A company's letter has no deemed delivery (the engine counts it from arrival); a party of kind
    ``other`` is the app's "don't know" and keeps the earliest plausible deemed delivery; a sender filed
    as an insurer whose letter names a Widerspruch is an authority's decision."""
    document = store.add_document(sha256="f" * 64, filename="x", mime="application/pdf", file_path="x")
    company = store.add_party(name="Muster GmbH", kind="company")
    assert rule_context(company, document, extraction([]), date(2026, 9, 25)).private_sender is True
    unknown = store.add_party(name="Stadt Musterstadt")  # kind "other" by default
    assert rule_context(unknown, document, extraction([]), date(2026, 9, 25)).private_sender is False
    misfiled = rule_context(
        None,
        document,
        extraction([], sender={"name": "AOK Nordost", "kind": "insurer"}, remedy={"type": "widerspruch"}),
        date(2026, 9, 25),
    )
    assert misfiled.private_sender is False and misfiled.delivery_scope is None


def test_rule_context_recognises_social_law_senders_filed_as_authority(store: Store) -> None:
    """Benchmark finding: job centres and pension insurers are read as a plain ``authority``, which
    applied the VwVfG (and a Land's 3-day rule) instead of § 37 SGB X."""
    document = store.add_document(sha256="e" * 64, filename="x", mime="application/pdf", file_path="x")
    jobcenter = store.add_party(name="Jobcenter Beispielkreis", kind="authority")
    ctx = rule_context(jobcenter, document, extraction([]), date(2026, 5, 1))
    assert ctx.delivery_scope == "sgbx"
    by_remedy = rule_context(
        None,
        document,
        extraction(
            [],
            sender={"name": "Kreis Beispiel", "kind": "authority"},
            remedy={
                "type": "widerspruch",
                "quote": "Gegen die Entscheidung des Widerspruchs ist Klage beim Sozialgericht möglich.",
            },
        ),
        date(2026, 5, 1),
    )
    assert by_remedy.delivery_scope == "sgbx"
    child_benefit = rule_context(
        None,
        document,
        extraction(
            [], sender={"name": "Familienkasse Nord", "kind": "authority"}, remedy={"type": "einspruch"}
        ),
        date(2026, 5, 1),
    )
    assert child_benefit.delivery_scope == "ao"
    assert remedy_text(None) == ""
    assert (
        remedy_text(Remedy(type="widerspruch", addressee="Jobcenter", period_text="ein Monat"))
        == "Jobcenter ein Monat"
    )


def test_remedy_warnings_and_payment_details() -> None:
    assert remedy_warnings(Remedy(type="klage"))[0].startswith(
        "This decision can only be challenged in court"
    )
    assert "one-year" in remedy_warnings(Remedy(type="unclear"))[0]
    assert remedy_warnings(Remedy(type="einspruch")) == remedy_warnings(None) == []
    details = payment_details(PaymentDetails(iban="de89 3704 0044 0532 0130 00"))
    assert details is not None and details.iban == "DE89370400440532013000" and details.iban_valid


def test_a_misread_iban_is_taken_from_the_page() -> None:
    """Demo finding: the model read "DE05 1234 5600 0004 4556 60" as DE05123456000044556660 (one zero
    too many), which failed the checksum and raised a false "misprinted IBAN" warning."""
    page = "Bankverbindung: Musterbank, IBAN DE05 1234 5600 0004 4556 60 · BIC MUSKDEM1XXX"
    fixed = payment_details(PaymentDetails(iban="DE05123456000044556660"), page)
    assert fixed is not None and fixed.iban == "DE05123456000004455660" and fixed.iban_valid
    # a page that really prints a broken IBAN stays flagged
    broken = payment_details(
        PaymentDetails(iban="DE05123456000044556660"), "IBAN DE05 1234 5600 0044 5566 60"
    )
    assert broken is not None and broken.iban == "DE05123456000044556660" and broken.iban_valid is False
    # an unrelated IBAN on the page is never swapped in
    other = payment_details(PaymentDetails(iban="DE05123456000044556660"), "IBAN DE89 3704 0044 0532 0130 00")
    assert other is not None and other.iban == "DE05123456000044556660" and not other.iban_valid


# --------------------------------------------------------------------------------------------------
# Writing items
# --------------------------------------------------------------------------------------------------


def add_doc(store: Store) -> Document:
    return store.add_document(sha256="e" * 64, filename="bill.pdf", mime="application/pdf", file_path="b.pdf")


def write(store: Store, doc_id: str, items: list[ExtractedItem]) -> list[Item]:
    data = extraction(items)
    verification = verify_extraction(doc_id, data, [TEXT_PAGE])
    ctx = RuleContext(today=date(2026, 9, 25), document_date=date(2026, 9, 15))
    computed = [compute_item(v, ctx, postal_buffer_days=4) for v in verification.items]
    return write_items(
        store,
        doc_id,
        verification,
        computed,
        data,
        LinkResult(),
        today=ctx.today,
        ctx=ctx,
        postal_buffer_days=4,
    )


def test_write_items_upserts_by_slot_and_keeps_user_edits(store: Store) -> None:
    document = add_doc(store)
    payment, objection = write(store, document.id, [PAYMENT, OBJECTION])
    assert payment.evidence == [Evidence.model_validate(payment.evidence[0].model_dump())]
    assert payment.due_date_source == "fixed" and objection.due_date_source == "computed"
    store.update_item(objection.id, title="My own title", user_modified=True)
    store.update_item(payment.id, status="done")

    changed = PAYMENT.model_copy(update={"title": "Pay the bill"})
    rewritten = write(store, document.id, [changed])
    assert rewritten[0].id == payment.id
    assert rewritten[0].title == "Pay the bill"
    assert rewritten[0].status == "done"  # the person's status is never reset
    kept = store.get_item(objection.id)
    assert kept is not None and kept.title == "My own title"

    write(store, document.id, [])  # the edited and the paid to-do stay; nothing else was read
    assert {i.id for i in store.list_items(doc_id=document.id)} == {objection.id, payment.id}


def test_a_to_do_the_person_acted_on_moves_to_a_reworded_reading(store: Store) -> None:
    """Reading the letter again with the sentence quoted differently must not bring back a paid bill."""
    document = add_doc(store)
    [payment] = write(store, document.id, [PAYMENT])
    store.update_item(payment.id, status="done")

    reworded = PAYMENT.model_copy(update={"quote": "Wir bitten Sie, 49,99 EUR bis zum 15.10.2026 zu zahlen."})
    fee = PAYMENT.model_copy(update={"quote": "Bitte zahlen Sie 5,00 EUR bis zum 15.10.2026.", "amount": 5.0})
    [again, new_fee] = write(store, document.id, [reworded, fee])
    assert again.id == payment.id and again.status == "done"  # same obligation: still paid
    assert new_fee.id != payment.id and new_fee.status == "open"  # another amount: a new to-do
    assert len(store.list_items(doc_id=document.id)) == 2


def test_a_recurring_to_do_moves_to_a_reading_that_corrects_its_amount(store: Store) -> None:
    """Two advance payments of one schedule (monthly from 15 Oct); electricity is paid ahead to
    December. Read again with both sentences quoted differently and electricity's amount corrected:
    each keeps its own to-do (a reading with the stored amount is matched first), and the corrected
    one keeps its paid-ahead occurrence (recurrence.py, point 6)."""
    monthly = {"type": "fixed", "date": "2026-10-15", "nature": "payment"}
    power = item("Abschlag Strom: 50,00 EUR monatlich ab 15.10.2026", money=50.0, **monthly)
    gas = item("Abschlag Gas: 30,00 EUR monatlich ab 15.10.2026", money=30.0, **monthly)
    power, gas = (reading.model_copy(update={"recurrence": Recurrence()}) for reading in (power, gas))
    document = add_doc(store)
    stored_power, stored_gas = write(store, document.id, [power, gas])
    store.update_item(stored_power.id, due_date="2026-12-15")  # paid ahead

    corrected = power.model_copy(
        update={"quote": "Strom: monatlich 55,00 EUR ab dem 15.10.2026", "amount": 55.0}
    )
    reworded = gas.model_copy(update={"quote": "Gas: monatlich 30,00 EUR ab dem 15.10.2026"})
    again_power, again_gas = write(store, document.id, [corrected, reworded])
    assert (again_power.id, again_power.amount, again_power.due_date) == (stored_power.id, 55.0, "2026-12-15")
    assert (again_gas.id, again_gas.due_date) == (stored_gas.id, "2026-10-15")
    assert len(store.list_items(doc_id=document.id)) == 2


def test_activity_message() -> None:
    now = "2026-09-25T10:00:00Z"
    items = [
        Item(id=f"itm_{n}", kind=kind, title="t", created_at=now, updated_at=now)
        for n, kind in enumerate(["payment", "deadline", "deadline"])
    ]
    assert (
        activity_message("Tax", items, "Finanzamt")
        == "Read “Tax” · 2 deadlines, 1 payment · linked to Finanzamt"
    )
    assert activity_message("Note", [], None) == "Read “Note” · no dates"


def test_rule_context_carries_the_person_s_country_and_only_a_chosen_region(store: Store) -> None:
    """Audit B integration: letters honour ``Profile.country`` like contracts do, and the default region
    of a profile that never chose one is not "known" (it would move payments on the wrong holidays)."""
    document = store.add_document(sha256="e" * 64, filename="x", mime="application/pdf", file_path="x")
    ctx = rule_context(None, document, extraction([]), date(2026, 9, 25), country="AT")
    assert ctx.country == "AT" and ctx.recipient_region is None
    assert Profile().known_region is None
    assert Profile(region="BY", onboarded=True).known_region == "BY"


# --------------------------------------------------------------------------------------------------
# regressions from the recorded demo: values stated elsewhere in the letter are not "please check"
# --------------------------------------------------------------------------------------------------


def test_amount_stated_elsewhere_in_the_letter_is_not_flagged() -> None:
    from ordnung.ingest.plan import verify_extraction
    from ordnung.models import DateSpec, DocumentExtraction, ExtractedItem

    page = (
        1,
        "Rechnungsbetrag 89,99 €\nZahlbar innerhalb von 14 Tagen nach Rechnungsdatum ohne Abzug.",
        [],
        "text",
    )
    item = ExtractedItem(
        kind="payment",
        title="Pay the invoice",
        date=DateSpec(type="relative", anchor="document_date", amount=14, unit="days", nature="payment"),
        amount=89.99,
        quote="Zahlbar innerhalb von 14 Tagen nach Rechnungsdatum ohne Abzug.",
    )
    extraction = DocumentExtraction(
        kind="invoice", title="Invoice", summary="s", explanation="e", items=[item]
    )
    verification = verify_extraction("doc_x", extraction, [page])
    assert not verification.needs_review
    assert verification.items[0].evidence.value_consistent


def test_amount_missing_from_the_whole_letter_is_still_flagged() -> None:
    from ordnung.ingest.plan import verify_extraction
    from ordnung.models import DateSpec, DocumentExtraction, ExtractedItem

    page = (1, "Zahlbar innerhalb von 14 Tagen nach Rechnungsdatum.", [], "text")
    item = ExtractedItem(
        kind="payment",
        title="Pay",
        date=DateSpec(type="relative", anchor="document_date", amount=14, unit="days", nature="payment"),
        amount=120.0,
        quote="Zahlbar innerhalb von 14 Tagen nach Rechnungsdatum.",
    )
    extraction = DocumentExtraction(
        kind="invoice", title="Invoice", summary="s", explanation="e", items=[item]
    )
    assert verify_extraction("doc_x", extraction, [page]).needs_review


def test_fixed_date_stated_elsewhere_and_recurring_schedules_are_not_flagged() -> None:
    from ordnung.ingest.plan import verify_extraction
    from ordnung.models import DateSpec, DocumentExtraction, ExtractedItem, Recurrence

    text = "Termin: Mittwoch, 14.10.2026, 10:30 Uhr\nDie Gebühr in Höhe von 100,00 € zahlen Sie vor Ort.\nAbbuchung zum Monatsanfang."
    page = (1, text, [], "text")
    fee = ExtractedItem(
        kind="payment",
        title="Fee",
        date=DateSpec(type="fixed", date="2026-10-14", nature="payment"),
        amount=100.0,
        quote="Die Gebühr in Höhe von 100,00 € zahlen Sie vor Ort.",
    )
    monthly = ExtractedItem(
        kind="payment",
        title="Monthly ticket",
        date=DateSpec(type="fixed", date="2026-10-01", nature="payment"),
        recurrence=Recurrence(interval=1, unit="months"),
        quote="Abbuchung zum Monatsanfang.",
    )
    extraction = DocumentExtraction(
        kind="contract", title="Letter", summary="s", explanation="e", items=[fee, monthly]
    )
    assert not verify_extraction("doc_x", extraction, [page]).needs_review


def test_passport_bilingual_month_dates_parse() -> None:
    from datetime import date

    from ordnung.ingest.verify import parse_dates

    assert [m.as_date() for m in parse_dates("Date of expiry 10 FEB / FÉV 2027")] == [date(2027, 2, 10)]
