"""People & organisations: the list and one party with its letters, to-dos, contracts and threads."""

from __future__ import annotations

from fastapi import APIRouter

from ordnung.api.deps import StoreDep, TodayDep
from ordnung.api.routes.common import contracts_with_computations, require
from ordnung.models import Item, ItemAside, Party, PartyDetail
from ordnung.secretary.triggers import Ledger, was_history_when_filed

router = APIRouter(tags=["parties"])


@router.get("/parties", response_model=list[Party])
def list_parties(store: StoreDep) -> list[Party]:
    """Every person and organisation, by name."""
    return store.list_parties()


def _aside(ledger: Ledger, item: Item) -> ItemAside | None:
    """Why an open to-do is not one to act on (the same rules as Today), or ``None``."""
    if item.status in ("done", "dismissed"):
        return None
    if ledger.is_suspicious_item(item):
        return ItemAside(item_id=item.id, reason="suspicious")
    if ledger.is_superseded_by_reminder(item):
        reminder = ledger.covering_reminders()[item.doc_id or ""]
        return ItemAside(item_id=item.id, reason="replaced", replaced_by=reminder.id)
    if ledger.is_covered_by_attachment(item):
        bill = ledger.covering_attachments()[item.id]
        return ItemAside(item_id=item.id, reason="attached", replaced_by=bill.id)
    if item.recurrence is None and was_history_when_filed(item):
        return ItemAside(item_id=item.id, reason="history")
    return None


@router.get("/parties/{party_id}", response_model=PartyDetail)
def get_party(party_id: str, store: StoreDep, today: TodayDep) -> PartyDetail:
    """One party with its letters (newest first), to-dos (not dismissed), contracts and threads.

    ``set_aside`` names the open to-dos that are not something to do — an invoice payment a payment
    reminder took over, a date that was already history when the letter was read, a letter with
    scam signs — so the drawer can list them apart instead of as overdue.
    """
    party = require(store.get_party(party_id), "Unknown person or organisation.")
    items = [item for item in store.list_items(party_id=party_id) if item.status != "dismissed"]
    ledger = Ledger(store, today)
    return PartyDetail(
        party=party,
        documents=store.list_documents(party_id=party_id),
        items=items,
        contracts=contracts_with_computations(store, store.list_contracts(party_id=party_id), today),
        cases=store.list_cases(party_id=party_id),
        set_aside=[aside for item in items if (aside := _aside(ledger, item)) is not None],
    )
