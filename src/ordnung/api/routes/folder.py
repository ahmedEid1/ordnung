"""The watched folder and the letters waiting for the person (SPEC § 8, § 14.8).

* ``GET /api/folder`` — the folder, whether it is watched (or why not), whether new files are read
  at once, how many letters wait, and the last files it brought in.
* ``POST /api/documents/held/read`` — "Read these": the given held letters (and a held e-mail's held
  attachments) may be sent to Claude and are queued for reading. Ids that no longer wait are
  reported as ``skipped``. The zero-token demo can't read new letters (``409``).
* ``POST /api/documents/held/keep-private`` — "Keep private": they stay on this computer, as if
  added with "Keep private — no AI".

The ids are always the ones the person saw: a file that arrived after the list was shown is not
answered for them (:mod:`ordnung.ingest.held`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import ApiState, StateDep, StoreDep
from ordnung.api.routes.documents import DEMO_UPLOAD_MESSAGE
from ordnung.ingest import held
from ordnung.ingest.pipeline import release_held
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
        waiting=len(held.waiting(store)),
        suggested=str(state.ctx.paths.inbox.resolve()),
        recent=recent_pickups(store),
    )


def _announce(state: ApiState, documents: list[Document]) -> None:
    for document in documents:
        state.ctx.bus.publish("document.updated", doc_id=document.id)
    state.ctx.bus.publish("folder.updated", state=state.folder.state)


@router.post("/documents/held/read", response_model=HeldResult)
async def read_held(body: HeldRequest, state: StateDep) -> HeldResult:
    """“Read these”: the waiting letters may be sent to Claude; they are queued for reading."""
    if not state.reads_letters:
        raise HTTPException(status.HTTP_409_CONFLICT, DEMO_UPLOAD_MESSAGE)
    result = release_held(state.ctx, body.doc_ids)
    _announce(state, result.documents)
    return HeldResult(documents=result.documents, jobs=result.jobs, skipped=result.skipped)


@router.post("/documents/held/keep-private", response_model=HeldResult)
async def keep_held_private(body: HeldRequest, state: StateDep) -> HeldResult:
    """“Keep private”: the waiting letters stay on this computer and are never sent to Claude."""
    result = held.keep_private(state.ctx.store, body.doc_ids)
    _announce(state, result.documents)
    return HeldResult(documents=result.documents, skipped=result.skipped)
