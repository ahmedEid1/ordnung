"""Letters (drafts): compose, read, edit (checks re-run), translate again after edits, delete, the DIN
5008 PDF (and its print preview as an image) and "I sent it" (which creates a follow-up to-do 21 days
later)."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import CtxDep, StoreDep
from ordnung.api.routes.common import IsoDate, ledger_changed, replay_only, require
from ordnung.db.store import Store
from ordnung.drafts import pdf
from ordnung.drafts.compose import MAX_INSTRUCTIONS, compose, mark_sent, refresh_checks, retranslate
from ordnung.models import Draft, DraftKind, LetterDetails

router = APIRouter(tags=["drafts"])

NOT_FOUND = "Unknown letter."
DEMO_TRANSLATE_MESSAGE = (
    "The demo replays recorded answers, so it can't translate your changes. "
    "Run `ordnung serve` (with Claude Code signed in) to re-translate letters you edited."
)


class DraftCreate(BaseModel):
    """What to write: the kind of letter and what it is about."""

    model_config = ConfigDict(extra="forbid")

    kind: DraftKind
    party_id: str | None = None
    doc_id: str | None = None
    contract_id: str | None = None
    case_id: str | None = Field(
        default=None, description="accepted for symmetry; the thread follows the letter"
    )
    instructions: str = Field(default="", max_length=MAX_INSTRUCTIONS)
    language: Literal["de", "en"] = "de"
    details: LetterDetails | None = Field(
        default=None, description="the facts a template letter needs (withdrawal, payment plan …)"
    )
    suspend_enforcement: bool = Field(
        default=False,
        description=(
            "an objection also applies to suspend enforcement (einstweilige Einstellung at a court, "
            "Aussetzung der Vollziehung at an authority); ignored for other letters and a court payment order"
        ),
    )


class DraftPatch(BaseModel):
    """Edits the person makes to a draft (the checks run again)."""

    model_config = ConfigDict(extra="forbid")

    subject: str | None = None
    body: str | None = None
    body_translation: str | None = None
    sender_block: str | None = None
    recipient_block: str | None = None
    place_date: str | None = None
    enclosures: list[str] | None = None
    status: Literal["draft", "final"] | None = None


class MarkSentRequest(BaseModel):
    """How and when the letter was sent."""

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(min_length=1)
    date: IsoDate


@router.get("/drafts", response_model=list[Draft])
def list_drafts(store: StoreDep) -> list[Draft]:
    """Every letter, newest first."""
    return store.list_drafts()


@router.post("/drafts", response_model=Draft, status_code=status.HTTP_201_CREATED)
async def create_draft(body: DraftCreate, ctx: CtxDep) -> Draft:
    """Draft a cancellation, objection, reply or template letter (withdrawal, more time, instalments,
    defect, data access, receipts, deposit, new address): fixed legal wording, model-written courtesy
    text and translation, automatic checks and "how to send it"."""
    return await compose(
        ctx,
        body.kind,
        doc_id=body.doc_id,
        contract_id=body.contract_id,
        party_id=body.party_id,
        instructions=body.instructions,
        language=body.language,
        details=body.details,
        suspend_enforcement=body.suspend_enforcement,
    )


@router.get("/drafts/{draft_id}", response_model=Draft)
def get_draft(draft_id: str, store: StoreDep) -> Draft:
    """One letter."""
    return require(store.get_draft(draft_id), NOT_FOUND)


def _edit(store: Store, draft_id: str, patch: DraftPatch) -> Draft:
    require(store.get_draft(draft_id), NOT_FOUND)
    changes = {
        name: value for name, value in patch.model_dump(exclude_unset=True).items() if value is not None
    }
    with store.tx():
        if changes:
            store.update_draft(draft_id, **changes)
        return refresh_checks(store, draft_id)


@router.patch("/drafts/{draft_id}", response_model=Draft)
async def update_draft(draft_id: str, patch: DraftPatch, ctx: CtxDep) -> Draft:
    """Edit the letter; the checks (placeholders, references, dates …) run again."""
    return await asyncio.to_thread(_edit, ctx.store, draft_id, patch)


@router.post(
    "/drafts/{draft_id}/translate",
    response_model=Draft,
    responses={409: {"description": "The zero-token demo can't ask the model for a new translation."}},
)
async def translate_draft(draft_id: str, ctx: CtxDep) -> Draft:
    """Translate the letter again, as it stands after your edits (only the translation changes)."""
    require(ctx.store.get_draft(draft_id), NOT_FOUND)
    if replay_only(ctx):
        raise HTTPException(status.HTTP_409_CONFLICT, DEMO_TRANSLATE_MESSAGE)
    return await retranslate(ctx, draft_id)


@router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_draft(draft_id: str, ctx: CtxDep) -> Response:
    """Delete a letter."""
    require(ctx.store.get_draft(draft_id), NOT_FOUND)
    await asyncio.to_thread(ctx.store.delete_draft, draft_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _pdf(store: Store, draft_id: str) -> bytes:
    return pdf.render(require(store.get_draft(draft_id), NOT_FOUND), store.get_profile())


@router.get("/drafts/{draft_id}/pdf", response_class=Response)
async def draft_pdf(draft_id: str, store: StoreDep) -> Response:
    """The letter as a printable DIN 5008 PDF."""
    body = await asyncio.to_thread(_pdf, store, draft_id)
    return Response(
        body,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{draft_id}.pdf"', "Cache-Control": "no-store"},
    )


def _preview(store: Store, draft_id: str) -> bytes:
    return pdf.render_preview(require(store.get_draft(draft_id), NOT_FOUND), store.get_profile())


@router.get("/drafts/{draft_id}/preview.png", response_class=Response)
async def draft_preview(draft_id: str, store: StoreDep) -> Response:
    """The printable letter as one PNG, page under page (the web app's print preview)."""
    body = await asyncio.to_thread(_preview, store, draft_id)
    return Response(body, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/drafts/{draft_id}/sent", response_model=Draft)
async def draft_sent(draft_id: str, body: MarkSentRequest, ctx: CtxDep) -> Draft:
    """Record that the letter was sent (channel and day) and add a follow-up to-do."""
    draft, item = await asyncio.to_thread(mark_sent, ctx, draft_id, body.channel, body.date)
    await ledger_changed(ctx, item_id=item.id)
    return draft
