"""People & organisations: the list, one party with its letters, to-dos, contracts and threads, and the Land
(Bundesland) a sender is in, which only the person can tell Ordnung.

A sender's Land decides the holidays of the dates its letters set and, for a Land authority, its delivery
rule (SPEC § 21 "Holidays"). Reading a letter never sets it; until the person does, those dates use
nationwide holidays and the 3-day rule at lower confidence — early, never late. Setting it (or "Don't know")
recomputes that sender's letters' to-dos, as a new home region recomputes every letter's.
"""

from __future__ import annotations

import asyncio
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ordnung.api.deps import CtxDep, StoreDep, TodayDep
from ordnung.api.routes.common import contracts_with_computations, ledger_changed, require, set_aside
from ordnung.api.routes.dates import recompute_party_items
from ordnung.db.store import Store
from ordnung.ingest.pipeline import ledger_lock
from ordnung.models import Party, PartyDetail
from ordnung.rules import normalize_region

router = APIRouter(tags=["parties"])


class PartyPatch(BaseModel):
    """What the person tells Ordnung about a sender."""

    model_config = ConfigDict(extra="forbid")

    region: str | None = Field(
        description="the Land (Bundesland) the sender is in, as a code like NW or BY; null: not known"
    )

    @field_validator("region")
    @classmethod
    def _known_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        code = normalize_region(value)
        if code is None:
            raise ValueError(f"“{value}” is not a German Bundesland (use a code like NW or BY).")
        return code


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


def _set_region(store: Store, party_id: str, region: str | None, today: date) -> Party:
    with store.tx():
        party = store.update_party(party_id, region=region)
        recompute_party_items(store, party_id, today)
    return party


@router.patch("/parties/{party_id}", response_model=Party)
async def update_party(party_id: str, patch: PartyPatch, ctx: CtxDep, today: TodayDep) -> Party:
    """Set the Land a sender is in (``null``: "Don't know"); a new one recomputes the dates of its letters."""
    party = require(ctx.store.get_party(party_id), "Unknown person or organisation.")
    if patch.region == party.region:
        return party
    async with ledger_lock():
        party = await asyncio.to_thread(_set_region, ctx.store, party_id, patch.region, today)
    await ledger_changed(ctx)
    return party
