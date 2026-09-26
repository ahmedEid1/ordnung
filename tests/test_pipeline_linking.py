"""End-to-end linking across documents: threads, dunning, scam checks and contract changes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import (
    BEITRAG_IBAN,
    BEITRAG_LETTER,
    CANCELLATION_LETTER,
    DUNNING_LETTER,
    GYM_CONTRACT_LETTER,
    INVOICE_LETTER,
    PRICE_INCREASE_LETTER,
    SCAM_IBAN,
    SCAM_LETTER,
    TODAY,
    Letter,
    Router,
    fake_backend,
)
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.ingest.link import DUNNING_ITEM_NOTE
from ordnung.ingest.pipeline import add_file, reprocess, triggers_hook
from ordnung.models import Document
from ordnung.secretary.triggers import Ledger


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def ctx(data_dir: Path) -> Iterator[AppContext]:
    context = build_context(data_dir, backend_obj=fake_backend(Router()))
    yield context
    context.close()


async def read(ctx: AppContext, letter: Letter) -> Document:
    document = await add_file(ctx, letter.pdf(), f"{letter.marker}.pdf")
    await ctx.worker.run_until_idle()
    stored = ctx.store.get_document(document.id)
    assert stored is not None and stored.status in ("processed", "needs_review"), stored and stored.error
    return stored


async def test_invoice_and_dunning_share_party_and_thread(ctx: AppContext) -> None:
    invoice = await read(ctx, INVOICE_LETTER)
    dunning = await read(ctx, DUNNING_LETTER)

    assert dunning.party_id == invoice.party_id  # found by the customer number, despite the shorter name
    assert dunning.case_id == invoice.case_id
    party = ctx.store.get_party(invoice.party_id or "")
    assert party is not None and party.name == "Muster Telecom GmbH"
    assert "Muster Telecom" in party.aliases
    case = ctx.store.get_case(invoice.case_id or "")
    assert case is not None and case.reference == "R-2026-0815"
    assert ctx.store.counts()["parties"] == 1


async def test_dunning_flags_the_original_payment_but_never_closes_it(ctx: AppContext) -> None:
    invoice = await read(ctx, INVOICE_LETTER)
    dunning = await read(ctx, DUNNING_LETTER)

    [original] = ctx.store.list_items(doc_id=invoice.id)
    assert original.status == "open"
    assert original.priority != "critical"  # the reminder is the one to act on — pay once
    assert original.description is None  # "superseded" is worked out on read, never stored
    assert Ledger(ctx.store, clock.today()).is_superseded_by_reminder(original)
    assert any("payment reminder" in warning for warning in dunning.warnings)
    [reminder] = ctx.store.list_items(doc_id=dunning.id)
    assert reminder.case_id == original.case_id
    assert not Ledger(ctx.store, clock.today()).is_superseded_by_reminder(reminder)


async def test_the_invoice_page_notes_that_a_reminder_took_over_its_payment(ctx: AppContext) -> None:
    from ordnung.api.routes.documents import document_detail

    invoice = await read(ctx, INVOICE_LETTER)
    await read(ctx, DUNNING_LETTER)

    [payment] = document_detail(ctx.store, invoice.id, clock.today()).items
    assert payment.description == DUNNING_ITEM_NOTE


async def test_a_second_reminder_takes_over_from_the_first(ctx: AppContext) -> None:
    await read(ctx, INVOICE_LETTER)
    first = await read(ctx, DUNNING_LETTER)
    second = first.model_copy(update={"id": "doc_second00001", "doc_date": "2026-10-05"})
    ledger = Ledger(ctx.store, clock.today())
    ledger.documents[second.id] = second

    assert ledger.covering_reminders()[first.id].id == second.id
    [payment] = ctx.store.list_items(doc_id=first.id)
    assert ledger.is_superseded_by_reminder(payment)


async def test_look_alike_collector_with_new_iban_is_flagged(ctx: AppContext) -> None:
    genuine = await read(ctx, BEITRAG_LETTER)
    fake = await read(ctx, SCAM_LETTER)

    assert fake.party_id != genuine.party_id
    assert any(warning.startswith("Possible scam") for warning in fake.warnings)
    scam_party = ctx.store.get_party(fake.party_id or "")
    assert scam_party is not None and scam_party.ibans == []  # a suspicious IBAN is never learned
    genuine_party = ctx.store.get_party(genuine.party_id or "")
    assert genuine_party is not None and genuine_party.ibans == [BEITRAG_IBAN]
    assert fake.payment is not None and fake.payment.iban == SCAM_IBAN and fake.payment.iban_valid
    if triggers_hook() is not None:  # the triggers engine raises a scam Idea from the same finding
        scams = [idea for idea in ctx.store.list_suggestions() if idea.kind == "scam"]
        assert scams and any(ref.id == fake.id for ref in scams[0].refs)


async def test_reprocessing_the_genuine_letter_raises_no_scam_warning(ctx: AppContext) -> None:
    genuine = await read(ctx, BEITRAG_LETTER)
    reprocess(ctx, genuine.id)
    await ctx.worker.run_until_idle()
    again = ctx.store.get_document(genuine.id)
    assert again is not None and again.status == "processed"
    assert not any("scam" in warning for warning in again.warnings)


async def test_contract_letter_creates_a_computed_contract(ctx: AppContext) -> None:
    document = await read(ctx, GYM_CONTRACT_LETTER)
    [contract] = ctx.store.list_contracts()
    assert contract.source_doc_id == document.id
    assert contract.customer_number == "FIT-2024-001"
    assert contract.party_id == document.party_id
    assert contract.case_id == document.case_id
    assert contract.computed is not None
    assert contract.computed.regime == "bgb309_new"
    assert contract.evidence and contract.evidence[0].grounding == "verified"


async def test_price_increase_is_linked_and_recorded_but_not_applied(ctx: AppContext) -> None:
    await read(ctx, GYM_CONTRACT_LETTER)
    [before] = ctx.store.list_contracts()
    change = await read(ctx, PRICE_INCREASE_LETTER)

    [after] = ctx.store.list_contracts()
    assert after.cost_amount == before.cost_amount == 29.9
    assert change.party_id == before.party_id
    logged = [entry for entry in ctx.store.list_activity() if entry.kind == "contract.change"]
    assert logged and logged[0].ref_id == before.id
    assert logged[0].data["change"]["new_amount"] == 34.9


async def test_cancellation_confirmation_never_closes_the_contract(ctx: AppContext) -> None:
    await read(ctx, GYM_CONTRACT_LETTER)
    confirmation = await read(ctx, CANCELLATION_LETTER)

    [contract] = ctx.store.list_contracts()
    assert contract.status == "active"
    assert confirmation.party_id == contract.party_id
    logged = [entry for entry in ctx.store.list_activity() if entry.kind == "contract.change"]
    assert logged[0].ref_id == contract.id
    assert logged[0].data["change"]["type"] == "cancellation_confirmation"
    if triggers_hook() is not None:  # the triggers engine turns it into a "Confirm cancellation?" Idea
        ideas = [idea for idea in ctx.store.list_suggestions() if idea.rule_id == "confirm_cancellation"]
        assert ideas and ideas[0].status == "new"
        assert any(ref.id == contract.id for ref in ideas[0].refs)


async def test_change_without_a_known_contract_is_flagged(ctx: AppContext) -> None:
    change = await read(ctx, PRICE_INCREASE_LETTER)
    assert ctx.store.list_contracts() == []
    assert any("couldn't match this letter" in warning for warning in change.warnings)
