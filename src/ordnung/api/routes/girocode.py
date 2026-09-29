"""GiroCodes (EPC QR codes that pre-fill a transfer in a banking app).

``GET /api/documents/{id}`` carries each payment's code — or why there is none — in ``girocodes``
(:mod:`ordnung.secretary.girocode_gate`). The one write is ``POST /api/items/{id}/girocode/confirm``:
the person compared the transfer details the app shows with the paper letter ("These match the
letter"). The body repeats those details; the answer is the payment's code. It is 409 when the
details changed since the person saw them, or when the code is refused for another reason — a
confirmation never unlocks a letter with scam signs.
"""

from __future__ import annotations

import asyncio
from datetime import date

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from ordnung.api.deps import CtxDep, TodayDep
from ordnung.api.routes.common import require
from ordnung.db.store import Store
from ordnung.ingest.pipeline import ledger_lock
from ordnung.models import GiroCode, TransferValues
from ordnung.secretary.girocode_gate import CheckRefused, record_check

router = APIRouter(tags=["items"])


class GiroCodeConfirm(BaseModel):
    """The transfer details the person compared with the paper letter, exactly as they were shown."""

    model_config = ConfigDict(extra="forbid")

    payee: str | None = None
    iban: str | None = None
    reference: str | None = None
    amount: float | None = None


def _confirm(store: Store, item_id: str, body: GiroCodeConfirm, today: date) -> tuple[GiroCode, str | None]:
    item = require(store.get_item(item_id), "Unknown to-do.")
    try:
        code = record_check(store, item, TransferValues.model_validate(body.model_dump()), today)
    except CheckRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return code, item.doc_id


@router.post(
    "/items/{item_id}/girocode/confirm",
    response_model=GiroCode,
    responses={
        404: {"description": "Unknown to-do."},
        409: {
            "description": "Nothing to compare: the details changed since they were shown, the payment has "
            "a code already, or it has no code for another reason (the reason is the detail)."
        },
    },
)
async def confirm_girocode(item_id: str, body: GiroCodeConfirm, ctx: CtxDep, today: TodayDep) -> GiroCode:
    """ "These match the letter": the person compared a payment's details with the paper letter."""
    async with ledger_lock():
        code, doc_id = await asyncio.to_thread(_confirm, ctx.store, item_id, body, today)
    ctx.bus.publish("document.updated", doc_id=doc_id)
    return code
