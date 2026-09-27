"""Settings → Data → "Download encrypted backup" (:mod:`ordnung.backup`).

``GET /api/backup`` says what a backup would hold now (letters, files, size) and the passphrase rule.
``POST /api/backup`` with ``{"passphrase": …}`` answers with the encrypted backup file itself, sent
while it is made (:class:`~ordnung.backup.archive.BackupStream`, one step per file): nothing is kept
on disk, the database snapshot is consistent even while Ordnung keeps working, and a browser that
goes away stops it — what it received then has no sealed end and is refused on restore.

The passphrase travels only over the loopback connection, in the request body. It is used to derive
the key and is never stored, logged or echoed: a passphrase against the policy (at least 12
characters, at most 1024) is refused with the rule, not the value, and request-validation errors
never reach this field because it accepts any string. The same backup as ``ordnung backup``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ordnung import backup as backups
from ordnung import clock
from ordnung.api.deps import CtxDep
from ordnung.app_context import AppContext
from ordnung.backup.archive import BackupStream
from ordnung.backup.container import FORMAT_VERSION

router = APIRouter(tags=["backup"])

BACKUP_TYPE = "application/octet-stream"


class BackupInfo(BaseModel):
    """What a backup made now would hold."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    letters: int = Field(description="Letters (not counting the trash)")
    files: int = Field(description="Originals, page images and letter PDFs")
    bytes: int = Field(description="Their size plus the database's, before encryption")
    file_name: str = Field(description="The name the download gets")
    min_passphrase: int = backups.MIN_PASSPHRASE_CHARS
    format_version: int = FORMAT_VERSION


class BackupRequest(BaseModel):
    """The passphrase that protects the backup (checked against the policy by the route)."""

    model_config = ConfigDict(extra="forbid")

    passphrase: str


def _info(ctx: AppContext) -> BackupInfo:
    files, size = backups.estimate(ctx.paths.data_dir)
    return BackupInfo(
        letters=ctx.store.counts().get("documents", 0),
        files=files,
        bytes=size,
        file_name=backups.backup_file_name(clock.today()),
    )


@router.get("/backup", response_model=BackupInfo)
async def backup_info(ctx: CtxDep) -> BackupInfo:
    """What an encrypted backup would hold now, and how long its passphrase must be."""
    return await asyncio.to_thread(_info, ctx)


def _stream(ctx: AppContext, backup: BackupStream) -> Iterator[bytes]:
    yield from backup
    contents = backup.contents
    if contents is not None:
        ctx.store.log_activity(
            "backup.created",
            f"Made an encrypted backup ({contents.letters} letters, {contents.files} files)",
        )


@router.post(
    "/backup",
    response_class=StreamingResponse,
    responses={
        200: {"content": {BACKUP_TYPE: {}}, "description": "The encrypted backup file"},
        422: {"description": "The passphrase is too short or too long (the rule, never the value)"},
    },
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
