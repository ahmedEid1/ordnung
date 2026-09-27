"""Proof of a sent letter: the overview, the tracking number, proof files and the "Nachweis" PDF.

Proof files are uploaded like letters (multipart ``file``) with ``kind``, ``on_date`` and ``note``; they
are stored private (never sent to AI) and belong to the letter (:mod:`ordnung.drafts.sent`). Every write
answers the letter's new :class:`~ordnung.models.ProofOverview`.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import CtxDep, StoreDep, TodayDep
from ordnung.api.routes.common import IsoDate, ledger_changed
from ordnung.drafts import sent
from ordnung.drafts.proof import MAX_NOTE
from ordnung.drafts.tracking import MAX_INPUT
from ordnung.ingest.intake import MAX_BYTES, IntakeError
from ordnung.models import ProofKind, ProofOverview

router = APIRouter(tags=["drafts"])


class TrackingUpdate(BaseModel):
    """A sent letter's tracking number (``null`` or empty removes it)."""

    model_config = ConfigDict(extra="forbid")

    tracking_number: str | None = Field(default=None, max_length=MAX_INPUT)


class ProofPatch(BaseModel):
    """Corrections to a proof: what it is, the day it shows (``null`` removes it) and a note."""

    model_config = ConfigDict(extra="forbid")

    kind: ProofKind | None = None
    on_date: IsoDate | None = None
    note: str | None = Field(default=None, max_length=MAX_NOTE)


@router.get("/drafts/{draft_id}/proof", response_model=ProofOverview)
def get_proof(draft_id: str, store: StoreDep, today: TodayDep) -> ProofOverview:
    """A letter's proof: tracking number, proofs with what each shows, timeline, what's missing and
    what the letter waits for."""
    return sent.overview(store, draft_id, today)


@router.put("/drafts/{draft_id}/tracking", response_model=ProofOverview)
async def set_tracking(draft_id: str, body: TrackingUpdate, ctx: CtxDep, today: TodayDep) -> ProofOverview:
    """Save the tracking number of a sent letter (checked: a mistyped check digit is refused)."""
    await asyncio.to_thread(sent.set_tracking, ctx.store, draft_id, body.tracking_number)
    await ledger_changed(ctx)
    return sent.overview(ctx.store, draft_id, today)


@router.post("/drafts/{draft_id}/proofs", response_model=ProofOverview, status_code=status.HTTP_201_CREATED)
async def add_proof(
    draft_id: str,
    ctx: CtxDep,
    today: TodayDep,
    file: Annotated[
        UploadFile, File(description="The proof: a photo or PDF of a receipt, a fax report, an e-mail …")
    ],
    kind: Annotated[ProofKind, Form(description="What the proof is")],
    on_date: Annotated[IsoDate | None, Form(description="The day it shows (posted, delivered …)")] = None,
    note: Annotated[str | None, Form(max_length=MAX_NOTE)] = None,
) -> ProofOverview:
    """Attach a proof file to a sent letter. The file is kept private: it is never sent to AI."""
    data = await file.read(MAX_BYTES + 1)
    try:
        await sent.add_proof(
            ctx, draft_id, data, file.filename or "proof", kind=kind, on_date=on_date, note=note, today=today
        )
    except IntakeError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await ledger_changed(ctx)
    return sent.overview(ctx.store, draft_id, today)


@router.patch("/drafts/{draft_id}/proofs/{proof_id}", response_model=ProofOverview)
async def update_proof(
    draft_id: str, proof_id: str, body: ProofPatch, ctx: CtxDep, today: TodayDep
) -> ProofOverview:
    """Correct what a proof is, the day it shows or its note."""
    fields = body.model_dump(exclude_unset=True)
    await asyncio.to_thread(
        sent.update_proof,
        ctx.store,
        draft_id,
        proof_id,
        today=today,
        kind=fields.get("kind"),
        on_date=fields.get("on_date"),
        note=fields.get("note"),
        clear_date="on_date" in fields and fields["on_date"] is None,
    )
    await ledger_changed(ctx)
    return sent.overview(ctx.store, draft_id, today)


@router.delete("/drafts/{draft_id}/proofs/{proof_id}", response_model=ProofOverview)
async def remove_proof(draft_id: str, proof_id: str, ctx: CtxDep, today: TodayDep) -> ProofOverview:
    """Remove a proof; its file is deleted for good unless another proof uses it."""
    await asyncio.to_thread(sent.remove_proof, ctx.store, draft_id, proof_id)
    await ledger_changed(ctx)
    return sent.overview(ctx.store, draft_id, today)


@router.get("/drafts/{draft_id}/proof.pdf", response_class=Response)
async def nachweis_pdf(draft_id: str, store: StoreDep, today: TodayDep) -> Response:
    """The Nachweis: a summary with the timeline, the letter as sent and every proof file, as one PDF."""
    body = await asyncio.to_thread(sent.nachweis_pdf, store, draft_id, today)
    return Response(
        body,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="nachweis-{draft_id}.pdf"',
            "Cache-Control": "no-store",
        },
    )
