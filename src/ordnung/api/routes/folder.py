"""The watched folder and the letters waiting for the person (SPEC § 8, § 14.8).

* ``GET /api/folder`` — the folder, whether it is watched (or why not), whether new files are read
  at once (and whether they can be read here at all), how many letters wait, and the last files it
  brought in.
* ``POST /api/documents/held/read`` — "Read these": the given held letters (and a held e-mail's held
  attachments) may be sent to Claude and are queued for reading. Ids that no longer wait are
  reported as ``skipped``. The zero-token demo can't read new letters (``409``, ``code: demo_replay``).
* ``POST /api/documents/held/keep-private`` — "Keep private": they stay on this computer, as if
  added with "Keep private — no AI".
* ``POST /api/documents/held/wait`` — undo "Keep private": letters kept private by that answer (and
  never read by Claude since) wait again.

The ids are always the ones the person saw: a file that arrived after the list was shown is not
answered for them (:mod:`ordnung.ingest.held`). At most :data:`MAX_HELD_IDS` per request; the web app
sends more in several.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import ApiState, StateDep, StoreDep
from ordnung.api.routes.documents import demo_replay_refusal
from ordnung.db.store import Store
from ordnung.ingest import held
from ordnung.ingest.pipeline import announce_job
from ordnung.ingest.watcher import recent_pickups
from ordnung.models import Document, FolderStatus, Job

router = APIRouter(tags=["folder"])

MAX_HELD_IDS = 500


class HeldRequest(BaseModel):
    """The waiting letters the person answered for (as shown to them)."""

    model_config = ConfigDict(extra="forbid")

    doc_ids: list[str] = Field(min_length=1, max_length=MAX_HELD_IDS)


class HeldResult(BaseModel):
    """What an answer changed: the letters, the reading jobs queued (Read only), ids no longer waiting."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    documents: list[Document] = Field(default_factory=list)
    jobs: list[Job] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list, description="ids that were not waiting (any more)")


@router.get("/folder", response_model=FolderStatus)
def folder_status(state: StateDep, store: StoreDep) -> FolderStatus:
    """The watched folder: its path, whether it is watched, the letters waiting and the last files."""
    settings = store.get_settings()
    watcher = state.folder
    return FolderStatus(
        folder=settings.inbox_dir,
        state=watcher.state,
        problem=watcher.problem,
        auto_read=settings.inbox_auto_read,
        can_read=state.reads_letters,
        waiting=len(held.waiting(store)),
        suggested=str(state.ctx.paths.inbox.resolve()),
        recent=recent_pickups(store),
    )


async def _answer(
    state: ApiState, answer: Callable[[Store, Sequence[str]], held.ConsentResult], doc_ids: Sequence[str]
) -> held.ConsentResult:
    """Run an answer's transaction off the event loop (up to 500 letters, an e-mail's attachments and
    activity entries each), then tell the worker about the jobs it queued."""
    result = await asyncio.to_thread(answer, state.ctx.store, doc_ids)
    for job in result.jobs:
        announce_job(state.ctx, job)
    return result


def _announce(state: ApiState, documents: list[Document]) -> None:
    for document in documents:
        state.ctx.bus.publish("document.updated", doc_id=document.id)
    state.ctx.bus.publish("folder.updated", state=state.folder.state)


@router.post("/documents/held/read", response_model=HeldResult)
async def read_held(body: HeldRequest, state: StateDep) -> HeldResult | JSONResponse:
    """“Read these”: the waiting letters may be sent to Claude; they are queued for reading."""
    if not state.reads_letters:
        return demo_replay_refusal()
    result = await _answer(state, held.release, body.doc_ids)
    _announce(state, result.documents)
    return HeldResult(documents=result.documents, jobs=result.jobs, skipped=result.skipped)


@router.post("/documents/held/keep-private", response_model=HeldResult)
async def keep_held_private_route(body: HeldRequest, state: StateDep) -> HeldResult:
    """“Keep private”: the waiting letters stay on this computer and are never sent to Claude."""
    result = await _answer(state, held.keep_private, body.doc_ids)
    _announce(state, result.documents)
    return HeldResult(documents=result.documents, jobs=result.jobs, skipped=result.skipped)


@router.post("/documents/held/wait", response_model=HeldResult)
async def wait_again(body: HeldRequest, state: StateDep) -> HeldResult:
    """Undo “Keep private”: letters kept private from waiting (never read by Claude) wait again."""
    result = await _answer(state, held.back_to_waiting, body.doc_ids)
    _announce(state, result.documents)
    return HeldResult(documents=result.documents, skipped=result.skipped)
