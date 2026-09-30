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
from ordnung.rules.contracts import DayOfMonth, Notice

router = APIRouter(tags=["contracts"])

NOT_FOUND = "Unknown contract."
ContractStatus = Literal["active", "cancelled", "ended"]
_NOTICE_FIELDS = frozenset({"notice_value", "notice_unit", "notice_basis"})
#: What the card's notice edit saves: the notice period and its basis, the contract's day of the month for
#: notice and a fixed-term job's early notice. Saving any of them records the terms as the person's.
_NOTICE_TERMS = _NOTICE_FIELDS | {"notice_day", "notice_before_end"}
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
    #: The contract's day of the month for notice (``None`` clears it): cleared too when notice terms are saved
    #: without it (an Undo puts it back with them).
    notice_day: int | None = Field(default=None, ge=1, le=31)
    #: A fixed-term job its contract lets be ended earlier by ordinary notice (read for a job only).
    notice_before_end: bool = False
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


def entered_notice(contract: Contract) -> str | None:
    """The contract's notice terms in words, as the person entered them on its card — ``None`` when they give
    no dates by themselves. A notice period with its basis ("three months' notice to the end of a month"; a
    job's without one runs to the 15th or the end of a month, § 622 Abs. 1 BGB), or the day of the month notice
    must arrive by when the basis is the end of a month, with the period asked for too ("notice by the 10th of
    the month, to the end of that month"; ``rules.contracts.DayOfMonth``). A job's early notice is named when
    its end date allows it ("…, also before the fixed term ends")."""
    value, unit, basis = contract.notice_value, contract.notice_unit, contract.notice_basis
    period = Notice(value, unit) if value is not None and unit is not None else None
    job = contract.category == "employment"
    if contract.notice_day is not None and basis == "end_of_month":
        words = f"{DayOfMonth(contract.notice_day, period).phrase}, to the end of that month"
    elif period is not None and basis is not None:
        words = f"{period.phrase} {_NOTICE_BASIS_WORDS[basis]}"
    elif period is not None and job:
        words = f"{period.phrase} to the 15th or the end of a month"
    else:
        return None
    if job and contract.end_date is not None and contract.notice_before_end:
        words += ", also before the fixed term ends"
    return words


def notice_evidence(contract: Contract) -> list[Evidence]:
    """The contract's evidence once the person has corrected its notice terms: with one quote
    ``confirmed by the person`` (grounding ``user``) that states them (:func:`entered_notice`) — "three
    months' notice to the end of a month" — so the card stops asking to check what the person has just
    entered (the rules' confidence stays as it is); without one when they give no dates by themselves (an
    Undo back to none). The letter's own quotes are kept."""
    kept = [evidence for evidence in contract.evidence if evidence.grounding != "user"]
    quote = entered_notice(contract)
    if quote is None:
        return kept
    return [*kept, Evidence(doc_id=contract.source_doc_id or "", quote=quote, grounding="user")]


def _update(store: Store, contract_id: str, patch: ContractPatch, today: date) -> Contract:
    require(store.get_contract(contract_id), NOT_FOUND)
    changes = patch.model_dump(exclude_unset=True)
    if _NOTICE_FIELDS & changes.keys():
        # the person's notice terms replace the letter's day of the month unless they give one with them: the
        # rules apply a period and a day both where both are read (``rules.contracts._notice_day``), so only the
        # data can let the person's entry decide
        changes.setdefault("notice_day", None)
    if changes.get("party_id") is not None:
        require(store.get_party(changes["party_id"]), "Unknown person or organisation.")
    if changes.get("case_id") is not None:
        require(store.get_case(changes["case_id"]), "Unknown thread.")
    with store.tx():
        current = store.update_contract(contract_id, **changes)
        if _NOTICE_TERMS & changes.keys():
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
