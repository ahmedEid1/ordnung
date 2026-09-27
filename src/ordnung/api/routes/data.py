"""“Delete everything” (Settings → Data): ``DELETE /api/data`` wipes the data folder and starts over.

The request must carry ``{"confirm": "DELETE"}`` (the word the person typed). Reading jobs and the
API's background work stop first; then the database is emptied in place (dropped, re-created and
vacuumed, so nothing deleted stays in the file) and Ordnung's files — originals, page images, letter
PDFs, the inbox folder — are removed. The data-folder lock and ``server.json`` stay, so the running
server keeps working and the command line still finds it. Entries Ordnung did not create (for
example when the data folder was pointed at a folder with other files) are never touched; they are
listed in the answer. The zero-token demo refuses (409): ``ordnung demo --reset`` starts it over.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ordnung import clock
from ordnung.api.deps import StateDep
from ordnung.app_context import SIMULATED_TODAY_KEY, AppContext
from ordnung.locking import LOCK_NAME
from ordnung.server import SERVER_FILE

router = APIRouter(tags=["data"])
log = logging.getLogger(__name__)

DEMO_MESSAGE = (
    "This is the demo, so there is nothing of yours to delete. "
    "To start over with Sam's original letters, run `ordnung demo --reset`."
)
KEPT_FILES = frozenset({LOCK_NAME, SERVER_FILE})
_DB_SUFFIXES = ("", "-wal", "-shm", "-journal")
WORKER_GRACE_S = 2.0


class DeleteEverything(BaseModel):
    """The typed confirmation."""

    model_config = ConfigDict(extra="forbid")

    confirm: Literal["DELETE"] = Field(description='Exactly "DELETE" — what the person typed to confirm')


class DataDeleted(BaseModel):
    """What "Delete everything" removed."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    removed: list[str] = Field(
        default_factory=list, description="Entries of the data folder that were deleted"
    )
    kept: list[str] = Field(
        default_factory=list, description="Entries Ordnung did not create, left untouched"
    )


def _ordnung_entries(ctx: AppContext) -> frozenset[str]:
    """Names in the data folder that Ordnung itself creates (besides the lock and ``server.json``)."""
    paths = ctx.paths
    folders = {paths.files.name, paths.derived.name, paths.drafts.name, paths.inbox.name}
    return frozenset(folders | {paths.db.name + suffix for suffix in _DB_SUFFIXES})


def _is_ordnung_entry(name: str, known: frozenset[str]) -> bool:
    # ``.server.json.<pid>.part``: an interrupted atomic write of server.json
    return name in known or (name.startswith(f".{SERVER_FILE}.") and name.endswith(".part"))


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def wipe_data_dir(ctx: AppContext) -> DataDeleted:
    """Empty the database in place and delete Ordnung's files (keeping the lock and ``server.json``)."""
    data_dir = ctx.paths.data_dir
    known = _ordnung_entries(ctx)
    db_files = {ctx.paths.db.name + suffix for suffix in _DB_SUFFIXES}
    ctx.store.wipe()
    result = DataDeleted()
    for entry in sorted(data_dir.iterdir(), key=lambda path: path.name):
        name = entry.name
        if name in KEPT_FILES:
            continue
        if not _is_ordnung_entry(name, known):
            result.kept.append(name)
            continue
        if name not in db_files:  # the database files were emptied in place (they stay open)
            _remove(entry)
        result.removed.append(name)
    ctx.paths.ensure()
    if result.kept:
        log.warning("delete everything: left entries Ordnung did not create: %s", ", ".join(result.kept))
    return result


@router.delete(
    "/data",
    response_model=DataDeleted,
    responses={409: {"description": "The demo can't be deleted (``ordnung demo --reset`` starts it over)."}},
)
async def delete_everything(body: DeleteEverything, state: StateDep) -> DataDeleted:
    """Delete every letter, date, contract, draft, chat and setting — Ordnung starts over empty.

    ``body`` must be ``{"confirm": "DELETE"}`` (422 otherwise)."""
    ctx = state.ctx
    if state.demo or ctx.settings.demo:
        raise HTTPException(status.HTTP_409_CONFLICT, DEMO_MESSAGE)
    pinned = bool(ctx.settings.simulated_today or ctx.store.get_meta(SIMULATED_TODAY_KEY))
    worker_was_running = ctx.worker.running
    await state.background.stop()
    await state.folder.pause()  # nothing may be added while the data goes; the setting goes with it
    await ctx.worker.stop(grace=WORKER_GRACE_S)
    try:
        result = await asyncio.to_thread(wipe_data_dir, ctx)
    except BaseException:
        with contextlib.suppress(Exception):  # what stays is watched again, as its settings say
            ctx.reload_settings()
            await state.folder.reconfigure()
        raise
    finally:
        if worker_was_running:
            with contextlib.suppress(Exception):
                await ctx.worker.start()
    if pinned:
        clock.set_today(None)
    ctx.reload_settings()
    await state.folder.reconfigure()
    for event in ("profile.updated", "item.updated", "suggestions.updated"):
        ctx.bus.publish(event)
    return result
