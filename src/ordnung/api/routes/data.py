"""“Delete everything” (Settings → Data): ``DELETE /api/data`` wipes the data folder and starts over.

The request must carry ``{"confirm": "DELETE"}`` (the word the person typed). Reading jobs and the
API's background work stop first. When a calendar is connected for calendar sync, Ordnung's events
are removed from it and its app password from the OS keyring before anything else (only Ordnung
knows which events are its own, and the database that says so is about to go); if that can't be
done — the server can't be reached, the password isn't there — nothing is deleted and the answer
(409) says how to go on: try again, or disconnect the calendar first and leave its events there.
Phone access stops first and forgets its phones (the database holds them; phone access's certificates
in ``phone/`` go with Ordnung's files). Then the database is emptied in place (dropped, re-created and
vacuumed, so nothing deleted stays in the file) and Ordnung's files — originals, page images, letter
PDFs, the inbox folder, phone access's certificates — are removed.
No calendar sync runs meanwhile (it would write its record back into the emptied database). The
data-folder lock and ``server.json`` stay, so the running server keeps working and the command line
still finds it. Entries Ordnung did not create (for
example when the data folder was pointed at a folder with other files) are never touched; they are
listed in the answer, which also tells the browser to empty its cache (``Clear-Site-Data``). The
zero-token demo refuses (409): ``ordnung demo --reset``, once the demo is stopped, starts it over. A
paired phone can never ask for it (403).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field

from ordnung import clock
from ordnung.api.deps import StateDep, require_computer
from ordnung.api.routes.calendar_sync import SecretsDep, TransportDep
from ordnung.api.routes.documents import CLEAR_CACHE
from ordnung.app_context import SIMULATED_TODAY_KEY, AppContext
from ordnung.calendar import caldav
from ordnung.calendar.secrets import SecretStore
from ordnung.locking import LOCK_NAME
from ordnung.server import SERVER_FILE

router = APIRouter(tags=["data"])
log = logging.getLogger(__name__)

DEMO_MESSAGE = (
    "This is the demo, so there is nothing of yours to delete. To start over with Sam's original letters, "
    "stop the demo (Ctrl+C where it runs), then run “ordnung demo --reset”."
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
    calendar_events_removed: int | None = Field(
        default=None,
        description="Ordnung's events removed from the connected calendar first (null: none was connected)",
    )


class CalendarNotCleared(RuntimeError):
    """The connected calendar's events (or its password) couldn't be removed: nothing was deleted."""


def _ordnung_entries(ctx: AppContext) -> frozenset[str]:
    """Names in the data folder that Ordnung itself creates (besides the lock and ``server.json``)."""
    paths = ctx.paths
    folders = {paths.files.name, paths.derived.name, paths.drafts.name, paths.inbox.name, paths.phone.name}
    return frozenset(folders | {paths.db.name + suffix for suffix in _DB_SUFFIXES})


def _is_ordnung_entry(name: str, known: frozenset[str]) -> bool:
    # ``.server.json.<pid>.part``: an interrupted atomic write of server.json
    return name in known or (name.startswith(f".{SERVER_FILE}.") and name.endswith(".part"))


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _forget_calendar(ctx: AppContext, secrets: SecretStore, transport: Any) -> int | None:
    """Remove Ordnung's events from the connected calendar and forget its password (``None``: no
    calendar is connected); :class:`CalendarNotCleared` when that can't be done."""
    state = caldav.load_state(ctx.store)
    if state is None:
        return None
    try:
        return caldav.disconnect(ctx.store, secrets, remove_events=True, transport=transport)
    except caldav.CalDavError as exc:
        where = state.calendar_name or caldav.host_of(state.url)
        raise CalendarNotCleared(
            f"Ordnung's events in your calendar “{where}” couldn't be removed, so nothing was deleted: {exc} "
            "Try again — or disconnect the calendar in Settings → Calendar first (you can leave its "
            "events there), then delete everything."
        ) from None


def wipe_data_dir(ctx: AppContext, secrets: SecretStore | None = None, transport: Any = None) -> DataDeleted:
    """Clear the connected calendar, then empty the database in place and delete Ordnung's files
    (keeping the lock and ``server.json``)."""
    from ordnung.calendar.secrets import KeyringSecrets

    data_dir = ctx.paths.data_dir
    known = _ordnung_entries(ctx)
    db_files = {ctx.paths.db.name + suffix for suffix in _DB_SUFFIXES}
    with caldav.exclusive():  # no sync may write its record back into the emptied database
        events_removed = _forget_calendar(ctx, secrets or KeyringSecrets(), transport)
        ctx.store.wipe()
    result = DataDeleted(calendar_events_removed=events_removed)
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
    responses={
        409: {
            "description": "The demo can't be deleted (``ordnung demo --reset`` starts it over), or the "
            "connected calendar's events couldn't be removed (nothing was deleted)."
        }
    },
    dependencies=[Depends(require_computer)],
)
async def delete_everything(
    body: DeleteEverything,
    state: StateDep,
    secrets: SecretsDep,
    transport: TransportDep,
    response: Response,
) -> DataDeleted:
    """Delete every letter, date, contract, draft, chat and setting — Ordnung starts over empty
    (Ordnung's events leave a connected calendar first), and the browser empties its cache.

    ``body`` must be ``{"confirm": "DELETE"}`` (422 otherwise)."""
    ctx = state.ctx
    if state.demo or ctx.settings.demo:
        raise HTTPException(status.HTTP_409_CONFLICT, DEMO_MESSAGE)
    pinned = bool(ctx.settings.simulated_today or ctx.store.get_meta(SIMULATED_TODAY_KEY))
    worker_was_running = ctx.worker.running
    await state.background.stop()
    await state.folder.pause()  # nothing may be added while the data goes; the setting goes with it
    await state.phone.forget()  # no phone may reach what is going; its record and certificates go too
    await ctx.worker.stop(grace=WORKER_GRACE_S)
    try:
        result = await asyncio.to_thread(wipe_data_dir, ctx, secrets, transport)
    except BaseException as exc:
        with contextlib.suppress(Exception):  # what stays is watched again, as its settings say
            ctx.reload_settings()
            await state.folder.reconfigure()
        with contextlib.suppress(Exception):  # and phones reach it again, if phone access was on
            await state.phone.start_if_enabled()
        if isinstance(exc, CalendarNotCleared):  # nothing was deleted
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
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
    response.headers.update(CLEAR_CACHE)
    return result
