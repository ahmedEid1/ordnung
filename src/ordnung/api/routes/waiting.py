"""What the person waits for (replies, money, promised callbacks) and the call notes that feed it.

``GET /api/waiting`` is worked out on read (:mod:`ordnung.secretary.waiting`); nothing here closes an
entry — the person closes the follow-up to-do, marks money received or says a promise was kept.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import CtxDep, StoreDep, TodayDep
from ordnung.api.routes.common import IsoDate, ledger_changed, require
from ordnung.models import CallNote, WaitingEntry
from ordnung.secretary import calls
from ordnung.views import waiting

router = APIRouter(tags=["waiting"])

UNKNOWN_CALL = "This call note doesn't exist (any more)."


class CallNoteCreate(BaseModel):
    """A phone call to note: when, with whom, what was said and what they promised (a promise with a
    day is waited for)."""

    model_config = ConfigDict(extra="forbid")

    party_id: str | None = None
    case_id: str | None = None
    called_on: IsoDate
    contact: str | None = Field(default=None, max_length=calls.MAX_CONTACT)
    summary: str = Field(min_length=1, max_length=calls.MAX_SUMMARY)
    promise: str | None = Field(default=None, max_length=calls.MAX_PROMISE)
    promise_due: IsoDate | None = None
    promise_amount: float | None = Field(default=None, ge=0)


class CallNotePatch(BaseModel):
    """Whether the call's promise was kept."""

    model_config = ConfigDict(extra="forbid")

    kept: bool


@router.get("/waiting", response_model=list[WaitingEntry])
def list_waiting(store: StoreDep, today: TodayDep) -> list[WaitingEntry]:
    """Replies, money and callbacks you are waiting for: overdue first, then by expected day, then the
    ones a letter may have answered."""
    return waiting(store, today)


@router.get("/calls", response_model=list[CallNote])
def list_calls(store: StoreDep, party_id: str | None = None, case_id: str | None = None) -> list[CallNote]:
    """Call notes, newest call first (of one person or organisation, or one thread)."""
    return store.list_call_notes(party_id=party_id, case_id=case_id)


@router.post("/calls", response_model=CallNote, status_code=status.HTTP_201_CREATED)
async def create_call(body: CallNoteCreate, ctx: CtxDep, today: TodayDep) -> CallNote:
    """Note a phone call. Nothing is sent anywhere; no AI reads it."""
    try:
        note = await asyncio.to_thread(calls.add_call_note, ctx.store, today=today, **body.model_dump())
    except calls.CallNoteError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await ledger_changed(ctx, triggers=False)
    return note


@router.patch("/calls/{call_id}", response_model=CallNote)
async def update_call(call_id: str, body: CallNotePatch, ctx: CtxDep, today: TodayDep) -> CallNote:
    """Say the promise made on the call was kept (or take that back)."""
    require(ctx.store.get_call_note(call_id), UNKNOWN_CALL)
    try:
        note = await asyncio.to_thread(calls.mark_kept, ctx.store, call_id, body.kept, today)
    except calls.CallNoteError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await ledger_changed(ctx, triggers=False)
    return note


@router.delete("/calls/{call_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_call(call_id: str, ctx: CtxDep) -> Response:
    """Delete a call note."""
    require(ctx.store.get_call_note(call_id), UNKNOWN_CALL)
    await asyncio.to_thread(ctx.store.delete_call_note, call_id)
    await ledger_changed(ctx, triggers=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
