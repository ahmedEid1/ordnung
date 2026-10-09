"""Settings → Data → "Download encrypted backup" (:mod:`ordnung.backup`).

``GET /api/backup`` says what a backup would hold now (letters, files, size), what it would leave
out (symbolic links, never followed) and the passphrase rule.
``POST /api/backup`` with ``{"passphrase": …}`` answers with the encrypted backup file itself, sent
while it is made (:class:`~ordnung.backup.archive.BackupStream`, one step per file): nothing is kept
on disk, the database snapshot is consistent even while Ordnung keeps working, and a browser that
goes away stops it — what it received then has no sealed end and is refused on restore.

The passphrase travels only over the loopback connection, in the request body (a paired phone can't
ask for a backup: 403, also behind the phone listener's allow-list). It is used to derive
the key and is never stored, logged or echoed: a passphrase against the policy (12–1024 characters
and about 70 bits by Ordnung's estimate, as a new sync folder's: :func:`ordnung.backup.passphrase_problem`)
is refused with the rule, not the value, and request-validation errors never reach this field because it
accepts any string. The same backup as ``ordnung backup``.

``GET /api/backup`` also says when the newest copy kept elsewhere was made — a backup, or hand-off sync's
last save — and whether it is time for a backup (``last_copy``, :mod:`ordnung.backup.reminder`); a made
backup is noted in the privacy log (``backup.created``, local to this computer) once its stream is sealed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ordnung import backup as backups
from ordnung import clock
from ordnung.api.deps import ApiState, CtxDep, StateDep, TodayDep, require_computer
from ordnung.app_context import AppContext
from ordnung.backup import reminder
from ordnung.backup.archive import BackupStream
from ordnung.backup.container import FORMAT_VERSION
from ordnung.models import BackupCopy

router = APIRouter(tags=["backup"])

BACKUP_TYPE = "application/octet-stream"


class BackupInfo(BaseModel):
    """What a backup made now would hold."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    letters: int = Field(description="Letters, the trash included (as the backup holds them)")
    files: int = Field(description="Originals, page images and letter PDFs")
    bytes: int = Field(description="Their size plus the database's, before encryption")
    file_name: str = Field(description="The name the download gets")
    left_out: list[str] = Field(
        default_factory=list,
        description="Symbolic links under the backed-up folders (or a folder that is one), which a "
        "backup leaves out: it never follows links",
    )
    min_passphrase: int = backups.MIN_PASSPHRASE_CHARS
    format_version: int = FORMAT_VERSION
    last_copy: BackupCopy = Field(
        default_factory=BackupCopy,
        description="The newest copy kept elsewhere (a backup, or hand-off sync's last save) and whether "
        "it is time for a backup",
    )


class BackupRequest(BaseModel):
    """The passphrase that protects the backup (checked against the policy by the route)."""

    model_config = ConfigDict(extra="forbid")

    passphrase: str


async def last_copy(state: ApiState, today: date) -> BackupCopy:
    """The newest copy kept elsewhere and whether it is time for a backup (:mod:`ordnung.backup.reminder`):
    hand-off sync's save as the agent knows it (read here, on the event loop — never its folder), then the
    data folder's newest backup in a thread. Never due in the demo."""
    agent = state.sync
    summary = agent.summary
    sync = reminder.SyncCopy.of(
        connected=agent.connected,
        mode=agent.mode,
        saved_at=summary.last_saved_at if summary is not None else None,
    )
    return await asyncio.to_thread(
        reminder.for_store, state.ctx.store, sync=sync, demo=agent.is_demo, today=today
    )


def _info(ctx: AppContext, copy: BackupCopy) -> BackupInfo:
    files, size = backups.estimate(ctx.paths.data_dir)
    counts = ctx.store.counts()
    return BackupInfo(
        # the same count as the backup's own (every letter row; `ordnung backup` prints it too)
        letters=counts.get("documents", 0) + counts.get("trashed_documents", 0),
        files=files,
        bytes=size,
        file_name=backups.backup_file_name(clock.today()),
        left_out=backups.links_left_out(ctx.paths.data_dir),
        last_copy=copy,
    )


@router.get("/backup", response_model=BackupInfo, dependencies=[Depends(require_computer)])
async def backup_info(state: StateDep, today: TodayDep) -> BackupInfo:
    """What an encrypted backup would hold now, and how long its passphrase must be."""
    copy = await last_copy(state, today)
    return await asyncio.to_thread(_info, state.ctx, copy)


def _stream(ctx: AppContext, backup: BackupStream) -> Iterator[bytes]:
    yield from backup
    contents = backup.contents
    if contents is not None:
        ctx.store.log_activity("backup.created", backups.backup_message(contents))


@router.post(
    "/backup",
    response_class=StreamingResponse,
    responses={
        200: {"content": {BACKUP_TYPE: {}}, "description": "The encrypted backup file"},
        422: {
            "description": "The passphrase is too short, too long or too easy to guess (the rule, never the value)"
        },
    },
    dependencies=[Depends(require_computer)],
)
async def create_backup(body: BackupRequest, ctx: CtxDep) -> StreamingResponse:
    """An encrypted backup of everything (database, letters, page images, letter PDFs) as a download."""
    problem = backups.passphrase_problem(body.passphrase)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    stream = await asyncio.to_thread(BackupStream, ctx.paths.data_dir, body.passphrase)
    name = backups.backup_file_name(clock.today())
    return StreamingResponse(
        _stream(ctx, stream),
        media_type=BACKUP_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )
