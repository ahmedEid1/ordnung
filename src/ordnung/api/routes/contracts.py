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
from ordnung.models import Area, Contract, ContractCategory, CostInterval, Evidence, NoticeBasis, NoticeUnit
from ordnung.rules.explain import fmt_period, notice_phrase

router = APIRouter(tags=["contracts"])

NOT_FOUND = "Unknown contract."
ContractStatus = Literal["active", "cancelled", "ended"]
_NOTICE_FIELDS = frozenset({"notice_value", "notice_unit", "notice_basis"})
#: How a notice period runs, in words (as ``NOTICE_BASIS_COPY`` in ``web/src/lib/copy.ts``).
_NOTICE_BASIS_WORDS: dict[NoticeBasis, str] = {
    "end_of_term": "to the end of the term",
    "any_time": "at any time",
    "end_of_month": "to the end of a month",
}


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
    #: The contract's day of the month for notice: cleared when notice terms are saved without it (an Undo
    #: puts it back with them).
    notice_day: int | None = Field(default=None, ge=1, le=31)
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


def notice_evidence(contract: Contract) -> list[Evidence]:
    """The contract's evidence once the person has corrected its notice terms: with one quote
    ``confirmed by the person`` (grounding ``user``) that states them — "three months' notice to the
    end of a month" — when all three are set, so the card stops asking to check what the person has
    just entered (the rules' confidence stays as it is); without one when they are not (an Undo back
    to none). The letter's own quotes are kept."""
    kept = [evidence for evidence in contract.evidence if evidence.grounding != "user"]
    value, unit, basis = contract.notice_value, contract.notice_unit, contract.notice_basis
    if value is None or unit is None or basis is None:
        return kept
    quote = f"{notice_phrase(fmt_period(value, unit))} {_NOTICE_BASIS_WORDS[basis]}"
    return [*kept, Evidence(doc_id=contract.source_doc_id or "", quote=quote, grounding="user")]


def _update(store: Store, contract_id: str, patch: ContractPatch, today: date) -> Contract:
    require(store.get_contract(contract_id), NOT_FOUND)
    changes = patch.model_dump(exclude_unset=True)
    if _NOTICE_FIELDS & changes.keys():
        # the person's notice terms replace the letter's day of the month: the rules apply both where both
        # are read (``rules.contracts._notice_day``), so only the data can let the person's entry decide
        changes.setdefault("notice_day", None)
    if changes.get("party_id") is not None:
        require(store.get_party(changes["party_id"]), "Unknown person or organisation.")
    if changes.get("case_id") is not None:
        require(store.get_case(changes["case_id"]), "Unknown thread.")
    with store.tx():
        current = store.update_contract(contract_id, **changes)
        if _NOTICE_FIELDS & changes.keys():
            current = store.update_contract(contract_id, evidence=notice_evidence(current))
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
