"""People & organisations: the list and one party with its letters, to-dos, contracts and threads."""

from __future__ import annotations

from fastapi import APIRouter

from ordnung.api.deps import StoreDep, TodayDep
from ordnung.api.routes.common import contracts_with_computations, require
from ordnung.models import Party, PartyDetail

router = APIRouter(tags=["parties"])


@router.get("/parties", response_model=list[Party])
def list_parties(store: StoreDep) -> list[Party]:
    """Every person and organisation, by name."""
    return store.list_parties()


@router.get("/parties/{party_id}", response_model=PartyDetail)
def get_party(party_id: str, store: StoreDep, today: TodayDep) -> PartyDetail:
    """One party with its letters (newest first), to-dos (not dismissed), contracts and threads."""
    party = require(store.get_party(party_id), "Unknown person or organisation.")
    return PartyDetail(
        party=party,
        documents=store.list_documents(party_id=party_id),
        items=[item for item in store.list_items(party_id=party_id) if item.status != "dismissed"],
        contracts=contracts_with_computations(store, store.list_contracts(party_id=party_id), today),
        cases=store.list_cases(party_id=party_id),
    )
