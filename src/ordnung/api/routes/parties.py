"""People & organisations: the list and one party with its letters, to-dos, contracts and threads."""

from __future__ import annotations

from fastapi import APIRouter

from ordnung.api.deps import StoreDep, TodayDep
from ordnung.api.routes.common import contracts_with_computations, require, set_aside
from ordnung.models import Party, PartyDetail

router = APIRouter(tags=["parties"])


@router.get("/parties", response_model=list[Party])
def list_parties(store: StoreDep) -> list[Party]:
    """Every person and organisation, by name."""
    return store.list_parties()


@router.get("/parties/{party_id}", response_model=PartyDetail)
def get_party(party_id: str, store: StoreDep, today: TodayDep) -> PartyDetail:
    """One party with its letters (newest first), to-dos (not dismissed), contracts and threads.

    ``set_aside`` names the open to-dos that are not something to do — an invoice payment a payment
    reminder took over, a date that was already history when the letter was read, a letter with
    scam signs — so the drawer can list them apart instead of as overdue.
    """
    party = require(store.get_party(party_id), "Unknown person or organisation.")
    items = [item for item in store.list_items(party_id=party_id) if item.status != "dismissed"]
    return PartyDetail(
        party=party,
        documents=store.list_documents(party_id=party_id),
        items=items,
        contracts=contracts_with_computations(store, store.list_contracts(party_id=party_id), today),
        cases=store.list_cases(party_id=party_id),
        set_aside=set_aside(store, items, today),
    )
