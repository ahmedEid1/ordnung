"""Contracts: the list (with cancellation dates computed on read for today) and corrections."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import CtxDep, StoreDep, TodayDep
from ordnung.api.routes.common import IsoDate, contracts_with_computations, ledger_changed, require
from ordnung.db.store import Store
from ordnung.models import Area, Contract, ContractCategory, CostInterval, NoticeBasis, NoticeUnit

router = APIRouter(tags=["contracts"])

NOT_FOUND = "Unknown contract."
ContractStatus = Literal["active", "cancelled", "ended"]


class ContractPatch(BaseModel):
    """Corrections to a contract's terms; its dates are recomputed by the rules engine."""

    model_config = ConfigDict(extra="forbid")

    party_id: str | None = None
    case_id: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: ContractCategory | None = None
    customer_number: str | None = None
    concluded_date: IsoDate | None = None
    start_date: IsoDate | None = None
    initial_term_months: int | None = Field(default=None, ge=0, le=600)
    renewal_term_months: int | None = Field(default=None, ge=0, le=600)
    notice_value: int | None = Field(default=None, ge=0, le=1000)
    notice_unit: NoticeUnit | None = None
    notice_basis: NoticeBasis | None = None
    end_date: IsoDate | None = None
    is_basic_supply: bool | None = None
    cost_amount: float | None = None
    cost_currency: str | None = None
    cost_interval: CostInterval | None = None
    is_consumer: bool | None = None
    status: ContractStatus | None = None
    area: Area | None = None


@router.get("/contracts", response_model=list[Contract])
def list_contracts(
    store: StoreDep, today: TodayDep, status: ContractStatus | None = None, party_id: str | None = None
) -> list[Contract]:
    """Contracts by name, each with its cancellation dates computed for today."""
    return contracts_with_computations(store, store.list_contracts(status=status, party_id=party_id), today)


def _update(store: Store, contract_id: str, patch: ContractPatch, today: date) -> Contract:
    require(store.get_contract(contract_id), NOT_FOUND)
    changes = patch.model_dump(exclude_unset=True)
    if changes.get("party_id") is not None:
        require(store.get_party(changes["party_id"]), "Unknown person or organisation.")
    if changes.get("case_id") is not None:
        require(store.get_case(changes["case_id"]), "Unknown thread.")
    with store.tx():
        current = store.update_contract(contract_id, **changes)
        fresh = contracts_with_computations(store, [current], today)[0]
        stored = store.update_contract(contract_id, computed=fresh.computed)
    return stored.model_copy(update={"cancellable": fresh.cancellable, "cancel_hint": fresh.cancel_hint})


@router.patch("/contracts/{contract_id}", response_model=Contract)
async def update_contract(contract_id: str, patch: ContractPatch, ctx: CtxDep, today: TodayDep) -> Contract:
    """Correct a contract (terms, cost, status); returns it with freshly computed dates."""
    contract = await asyncio.to_thread(_update, ctx.store, contract_id, patch, today)
    ctx.bus.publish("contract.updated", contract_id=contract_id)
    await ledger_changed(ctx)
    return contract
