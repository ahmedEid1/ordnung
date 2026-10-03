"""Settings → Calendar → "Sync to your own calendar" (CalDAV, :mod:`ordnung.calendar.caldav`).

``GET /api/calendar/sync`` says whether calendar sync can be used on this computer (the password
store; never in the demo), whether a calendar is connected (address, user name, mode, whether the
app password is saved here) and what the last sync did — read on every page (background problems), so
it never builds the events. ``GET /api/calendar/sync/preview?mode=`` lists exactly what each event
would contain (how many the calendar gets). ``POST /api/calendar/sync/discover`` finds the
calendars that take events from a calendar's, an account's or a server's address (nothing is
stored). ``PUT /api/calendar/sync`` connects (or changes the
mode of) a calendar: the address is checked with the server first, then the app password goes to
the OS keyring and the events are sent. ``POST /api/calendar/sync/run`` sends what changed now;
``POST /api/calendar/sync/disconnect`` forgets the calendar and its password, optionally removing
Ordnung's events from it first.

The app password travels only over the loopback connection, in the request body, and is never
stored in the database, logged or returned. The status never reads the keyring: it asks which
password store there is, and whether the password is saved is what the last connect or sync found
(so opening Settings doesn't ask a locked keyring to unlock). A refusal answers ``{"detail": …, "code": <kind>}`` (``address``,
``auth``, ``not_calendar``, … — :data:`~ordnung.models.CalendarSyncErrorKind`) so the web app can
show it next to the right field.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import ApiState, CtxDep, StateDep
from ordnung.app_context import AppContext
from ordnung.calendar import caldav
from ordnung.calendar.secrets import KeyringSecrets, SecretStore
from ordnung.ingest.pipeline import run_triggers
from ordnung.models import (
    CalendarEventPreview,
    CalendarSyncErrorKind,
    CalendarSyncMode,
    CalendarSyncReport,
)

router = APIRouter(tags=["calendar"])

DEMO_MESSAGE = "The demo doesn't send Sam's dates anywhere. Install Ordnung to sync your own calendar."
_STATUS: dict[CalendarSyncErrorKind, int] = {
    "address": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "auth": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "forbidden": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "not_found": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "not_calendar": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "conflict": status.HTTP_409_CONFLICT,
    "unavailable": status.HTTP_409_CONFLICT,
    "not_connected": status.HTTP_409_CONFLICT,
    "network": status.HTTP_502_BAD_GATEWAY,
    "tls": status.HTTP_502_BAD_GATEWAY,
    "server": status.HTTP_502_BAD_GATEWAY,
}
REFUSALS: dict[int | str, dict[str, Any]] = {
    409: {
        "description": "Not connected, connected elsewhere, the demo, or no password store on this computer"
    },
    422: {"description": "The address, user name or app password can't be used (``code`` says which)"},
    502: {"description": "The calendar server couldn't be reached or answered with an error"},
}


def get_secrets() -> SecretStore:
    """Where app passwords are kept (the OS keyring; tests replace this dependency)."""
    return KeyringSecrets()


def get_transport() -> Any:
    """The HTTP transport to the calendar server (``None``: the network; tests use a fake server)."""
    return None


SecretsDep = Annotated[SecretStore, Depends(get_secrets)]
TransportDep = Annotated[Any, Depends(get_transport)]


class CalendarSyncStatus(BaseModel):
    """What Settings shows about calendar sync."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    available: bool = Field(description="Calendar sync can be used on this computer")
    unavailable: str | None = Field(default=None, description="Why not, in words")
    install_command: str | None = Field(default=None, description="The command that makes it available")
    connected: bool
    url: str | None = None
    username: str | None = None
    calendar_name: str | None = Field(default=None, description="The calendar's name on the server")
    mode: CalendarSyncMode = "discreet"
    password_saved: bool = Field(
        default=False,
        description="The app password was in this computer's keyring when Ordnung last needed it",
    )
    paused: bool = Field(default=False, description="Automatic syncing waits after a refused password")
    synced: int = Field(default=0, description="How many of Ordnung's events are in the calendar")
    last_sync: CalendarSyncReport | None = None


class CalendarSyncPreview(BaseModel):
    """Exactly what each event would contain in ``mode``."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    mode: CalendarSyncMode
    events: list[CalendarEventPreview]


class CalendarSyncConnect(BaseModel):
    """The calendar to connect; ``password: null`` keeps the saved app password (to change the mode)."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=caldav.MAX_URL_CHARS)
    username: str = Field(max_length=caldav.MAX_USERNAME_CHARS)
    password: str | None = None
    mode: CalendarSyncMode = "discreet"


class CalendarSyncFind(BaseModel):
    """Where to look for calendars, and the account to look with (nothing is stored)."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=caldav.MAX_URL_CHARS)
    username: str = Field(max_length=caldav.MAX_USERNAME_CHARS)
    password: str


class CalendarChoice(BaseModel):
    """A calendar that takes events."""

    url: str
    name: str | None = None


class CalendarSyncFound(BaseModel):
    """The calendars Ordnung could write into (the address itself first, when it is one)."""

    calendars: list[CalendarChoice]


class CalendarSyncDisconnect(BaseModel):
    """Whether to remove Ordnung's events from the calendar before forgetting it."""

    model_config = ConfigDict(extra="forbid")

    remove_events: bool = True


class CalendarSyncDisconnected(BaseModel):
    """How many of Ordnung's events were removed from the calendar."""

    removed: int


def _refusal(exc: caldav.CalDavError) -> JSONResponse:
    return JSONResponse(status_code=_STATUS[exc.kind], content={"detail": str(exc), "code": exc.kind})


def _demo(state: ApiState, ctx: AppContext) -> JSONResponse | None:
    if state.demo or ctx.store.get_settings().demo:
        return JSONResponse(status_code=409, content={"detail": DEMO_MESSAGE, "code": "unavailable"})
    return None


def _status(ctx: AppContext, secrets: SecretStore, demo: bool) -> CalendarSyncStatus:
    store = ctx.store
    problem = None if demo else secrets.problem()
    unavailable = DEMO_MESSAGE if demo else (str(problem) if problem is not None else None)
    connection = caldav.load_state(store)
    mode = connection.mode if connection is not None else "discreet"
    saved = connection is not None and connection.password_saved and problem is None and not demo
    return CalendarSyncStatus(
        available=unavailable is None,
        unavailable=unavailable,
        install_command=problem.install if problem is not None else None,
        connected=connection is not None,
        url=connection.url if connection else None,
        username=connection.username if connection else None,
        calendar_name=connection.calendar_name if connection else None,
        mode=mode,
        password_saved=saved,
        paused=connection.paused if connection else False,
        synced=len(connection.events) if connection else 0,
        last_sync=connection.last if connection else None,
    )


@router.get("/calendar/sync", response_model=CalendarSyncStatus)
async def calendar_sync_status(state: StateDep, ctx: CtxDep, secrets: SecretsDep) -> CalendarSyncStatus:
    """Whether calendar sync can be used here, the connected calendar and the last sync."""
    demo = state.demo or ctx.store.get_settings().demo
    return await asyncio.to_thread(_status, ctx, secrets, demo)


@router.get("/calendar/sync/preview", response_model=CalendarSyncPreview)
async def calendar_sync_preview(
    ctx: CtxDep, mode: Annotated[CalendarSyncMode, Query()] = "discreet"
) -> CalendarSyncPreview:
    """Every event exactly as calendar sync would send it in ``mode`` (nothing is sent)."""
    events = await asyncio.to_thread(caldav.preview, ctx.store, mode)
    return CalendarSyncPreview(mode=mode, events=events)


@router.post("/calendar/sync/discover", response_model=CalendarSyncFound, responses=REFUSALS)
async def calendar_sync_discover(
    body: CalendarSyncFind, state: StateDep, ctx: CtxDep, transport: TransportDep
) -> CalendarSyncFound | JSONResponse:
    """The calendars that take events at or under ``url`` (the account's calendar home, found the
    way calendar apps find it). Nothing is stored or written."""
    refused = _demo(state, ctx)
    if refused is not None:
        return refused
    try:
        found = await asyncio.to_thread(
            caldav.discover, body.url, body.username, body.password, transport=transport
        )
    except caldav.CalDavError as exc:
        return _refusal(exc)
    return CalendarSyncFound(calendars=[CalendarChoice(url=c.url, name=c.name) for c in found])


@router.put("/calendar/sync", response_model=CalendarSyncStatus, responses=REFUSALS)
async def calendar_sync_connect(
    body: CalendarSyncConnect, state: StateDep, ctx: CtxDep, secrets: SecretsDep, transport: TransportDep
) -> CalendarSyncStatus | JSONResponse:
    """Connect a calendar (checked with its server first) and send the events; or change the mode."""
    refused = _demo(state, ctx)
    if refused is not None:
        return refused

    def work() -> CalendarSyncStatus:
        caldav.connect(
            ctx.store,
            secrets,
            url=body.url,
            username=body.username,
            password=body.password,
            mode=body.mode,
            transport=transport,
        )
        return _status(ctx, secrets, False)

    try:
        result = await asyncio.to_thread(work)
    except caldav.CalDavError as exc:
        return _refusal(exc)
    await run_triggers(ctx)  # a connected calendar gets the dates: no "import the calendar file" Idea
    return result


@router.post("/calendar/sync/run", response_model=CalendarSyncStatus, responses=REFUSALS)
async def calendar_sync_run(
    state: StateDep, ctx: CtxDep, secrets: SecretsDep, transport: TransportDep
) -> CalendarSyncStatus | JSONResponse:
    """Send what changed now (the report is in ``last_sync``; a paused sync resumes)."""
    refused = _demo(state, ctx)
    if refused is not None:
        return refused

    def work() -> CalendarSyncStatus | None:
        if caldav.sync(ctx.store, secrets, transport=transport) is None:
            return None
        return _status(ctx, secrets, False)

    result = await asyncio.to_thread(work)
    if result is None:
        return _refusal(caldav.CalDavError("not_connected", "No calendar is connected."))
    return result


@router.post("/calendar/sync/disconnect", response_model=CalendarSyncDisconnected, responses=REFUSALS)
async def calendar_sync_disconnect(
    body: CalendarSyncDisconnect, ctx: CtxDep, secrets: SecretsDep, transport: TransportDep
) -> CalendarSyncDisconnected | JSONResponse:
    """Forget the calendar and its app password — first removing Ordnung's events if asked (only those)."""
    try:
        removed = await asyncio.to_thread(
            caldav.disconnect, ctx.store, secrets, remove_events=body.remove_events, transport=transport
        )
    except caldav.CalDavError as exc:
        return _refusal(exc)
    await run_triggers(ctx)  # the calendar file is the way to a calendar again
    return CalendarSyncDisconnected(removed=removed)
