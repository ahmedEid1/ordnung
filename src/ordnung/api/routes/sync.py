"""Settings → Your computers: hand-off sync between the person's computers (policy: :mod:`ordnung.sync`).

* ``GET /api/sync`` — whether sync can be used here, this computer's mode (in use, standing by), the
  folder, the other computers, what is arriving, a choice to make, problems, notices and kept copies.
  It is answered from memory: it never touches the sync folder or reads the password store.
* ``POST /api/sync/inspect`` — what a folder would be: ``new``, ``existing`` (a sync to join) or
  ``refused`` (with the reason), and whether the data folder itself sits in a synced folder.
* ``PUT /api/sync`` — set up a new sync folder, or join an existing one; joining with letters on both
  sides answers the choice first (``keep`` answers it).
* ``PATCH /api/sync`` — rename this computer, or answer a problem: "This is the same computer", "Keep
  this computer's data as it is", give up an unfinished take-over; dismiss a notice.
* ``DELETE /api/sync`` — disconnect this computer (the folder and the other computers keep everything);
  it asks for a second confirmation while no other computer has this one's latest changes.
* ``POST /api/sync/use-here`` — "Use Ordnung here": take over (or wait until everything has arrived;
  ``older_copy`` uses the copy this computer has; ``cancel`` stops a waiting take-over).
* ``POST /api/sync/choose`` — which computer's Ordnung to keep, when both changed.
* ``POST /api/sync/save`` — save now; ``hand_over`` also stands by.
* ``POST /api/sync/passphrase`` — type the passphrase again (the password store lost it).
* ``POST /api/sync/refill`` — fill an emptied folder again from this computer (the one in use).
* ``DELETE /api/sync/computers/{key}`` — forget a lost computer (a kept copy first when it has changes
  nowhere else).
* ``GET /api/sync/kept/{name}`` and ``DELETE /api/sync/kept/{name}`` — download or delete a kept copy.

The passphrase travels only over the loopback connection, in the request body, and is never stored in
the database, logged or returned; request fields that carry it accept any string, so a validation error
never echoes it. Every write here is computer-only (a paired phone gets 403, also behind the phone
listener's allow-list), never in the demo (409 ``unavailable``). A refusal answers
``{"detail": …, "code": <kind>}`` (:data:`ordnung.sync.SyncErrorKind`) with the status
:data:`ordnung.sync.ERROR_STATUS` gives it.

Until the sync agent is wired in, sync is off here: the status says so and every write answers 409
``not_connected``.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import ApiState, CtxDep, StateDep, require_computer
from ordnung.app_context import AppContext
from ordnung.calendar.secrets import KeyringSecrets, SecretStore
from ordnung.demo.loader import is_demo_dir
from ordnung.sync import (
    DEMO_MESSAGE,
    ERROR_STATUS,
    NAME_MAX_CHARS,
    NOT_CONNECTED_MESSAGE,
    CalendarMatch,
    ComputerState,
    SyncActivity,
    SyncErrorKind,
    SyncMode,
    SyncNoticeCode,
    SyncProblemAction,
    SyncProblemCode,
)

router = APIRouter(tags=["sync"])
COMPUTER = [Depends(require_computer)]

KEPT_TYPE = "application/octet-stream"
NO_KEPT_COPY = "There's no saved copy of that name (any more)."
NO_COMPUTER = "No other computer of this sync has that number."

_RESPONSE = ConfigDict(json_schema_serialization_defaults_required=True)
_REQUEST = ConfigDict(extra="forbid")


_STATUS_OF: dict[str, int] = {str(code): status_code for code, status_code in ERROR_STATUS.items()}


def _refusals(**codes: str) -> dict[int | str, dict[str, Any]]:
    """``responses=`` for the refusal codes given (code → when), grouped by their status."""
    grouped: dict[int, list[str]] = {}
    for code, when in codes.items():
        grouped.setdefault(_STATUS_OF[code], []).append(f"{when} (``{code}``)")
    return {status_code: {"description": "; ".join(whens)} for status_code, whens in sorted(grouped.items())}


_DEMO = "the demo, or no usable password store on this computer"
_NOT_CONNECTED = "this computer isn't syncing"


# --------------------------------------------------------------------------------------------------
# dependencies
# --------------------------------------------------------------------------------------------------


def get_secrets() -> SecretStore:
    """Where this computer keeps the sync passphrase (the OS keyring; tests replace this dependency)."""
    return KeyringSecrets()


SecretsDep = Annotated[SecretStore, Depends(get_secrets)]


# --------------------------------------------------------------------------------------------------
# models: answers
# --------------------------------------------------------------------------------------------------


class SyncLetter(BaseModel):
    """A letter in a side's summary: its title and the calendar date it was added (no clock time)."""

    model_config = _RESPONSE

    label: str
    added_on: str


class SyncProgress(BaseModel):
    """How far a first save, or bringing a version over, has got."""

    model_config = _RESPONSE

    done: int = Field(description="Files done")
    total: int = Field(description="Files in all")
    bytes_done: int
    bytes_total: int


class SyncComputer(BaseModel):
    """A computer of this sync, as this computer sees it (never its id)."""

    model_config = _RESPONSE

    key: int = Field(description="A small number for the UI, stable per computer (``choose``, ``forget``)")
    name: str = Field(description="The name it was given (“anna-thinkpad”)")
    this: bool = Field(description="This computer")
    in_use: bool = Field(description="It is the one in use")
    state: ComputerState = Field(
        description="What its latest head says: ``in_use``, ``standing_by``, ``closed`` (Ordnung was closed "
        "there while in use), ``left`` (it disconnected) or ``unknown`` (its head can't be read now)"
    )
    arrived_at: str | None = Field(
        default=None, description="This computer's clock: when that computer's latest change arrived here"
    )
    has_latest: bool | None = Field(
        default=None,
        description="This computer's latest saved version has fully arrived there (null: can't tell, or "
        "this computer)",
    )
    app_version: str = Field(description="The Ordnung version it runs")
    calendar: CalendarMatch = Field(
        description="Calendar sync there, compared with this computer's: ``none``; ``same`` calendar and "
        "mode; ``different_mode`` (the same calendar in another mode); ``other`` (another calendar, or "
        "none here)"
    )


class SyncArriving(BaseModel):
    """A version still arriving from the sync tool."""

    model_config = _RESPONSE

    from_computer: str = Field(description="The computer it comes from")
    have: int = Field(description="Files already here")
    need: int = Field(description="Files it needs in all")
    have_bytes: int
    need_bytes: int
    since: str = Field(description="This computer's clock: when waiting began")
    stalled: bool = Field(description="Nothing more arrived for 30 minutes")
    online_only: int = Field(
        description="Files the sync tool keeps online-only on this computer (placeholders, dataless files): "
        "they arrive only once the folder is available offline"
    )


class SyncProblem(BaseModel):
    """Why sync is paused or needs the person (the web shows the words, never the code)."""

    model_config = _RESPONSE

    code: SyncProblemCode
    title: str = Field(description="A short title for people")
    message: str = Field(description="What happened and what to do, for people")
    actions: list[SyncProblemAction] = Field(
        description="What the person can do about it, the main action first (none: wait, or the message says)"
    )


class SyncSide(BaseModel):
    """One computer's Ordnung in a choice."""

    model_config = _RESPONSE

    key: int = Field(description="The computer's ``key`` (what ``choose`` takes)")
    computer: str
    this: bool
    letters: int = Field(description="Letters in that Ordnung")
    added: int = Field(description="Letters added there since the two last agreed")
    newest: list[SyncLetter] = Field(description="Up to three letters, newest added first")
    arrived_at: str | None = Field(default=None, description="This computer's clock: when it arrived here")
    complete: bool = Field(description="It has fully arrived here (choosing one that hasn't waits for it)")
    arriving: SyncArriving | None = Field(default=None, description="What is still arriving of it")


class SyncChoice(BaseModel):
    """Both computers changed something: which computer's Ordnung to keep (the other is kept as a copy)."""

    model_config = _RESPONSE

    joining: bool = Field(description="This computer is joining and already has its own letters")
    sides: list[SyncSide]
    chosen: int | None = Field(
        default=None,
        description="The side chosen while it still arrives: kept as soon as it is here (``use-here`` with "
        "``cancel`` stops waiting)",
    )


class SyncKept(BaseModel):
    """A kept copy: this computer's data saved before it was replaced (an encrypted backup)."""

    model_config = _RESPONSE

    name: str = Field(description="Its file name (``ordnung-kept-2026-10-07-0912.ordnung-backup``)")
    path: str = Field(description="Where it is on this computer (for ``ordnung restore``)")
    size: int
    created_at: str = Field(description="This computer's clock")
    why: str = Field(description="Why it was kept, for people (“before you kept desktop's Ordnung”)")


class SyncNotice(BaseModel):
    """Something the person should know about once (dismissed with ``PATCH /api/sync``)."""

    model_config = _RESPONSE

    id: str
    code: SyncNoticeCode
    message: str = Field(description="For people")
    kept: str | None = Field(default=None, description="The kept copy it is about (its name)")
    at: str = Field(description="This computer's clock")


class SyncStatus(BaseModel):
    """What Settings → Your computers, the top bar and the standing-by screen show."""

    model_config = _RESPONSE

    available: bool = Field(
        description="Sync can be used on this computer (a password store; never the demo)"
    )
    unavailable: str | None = Field(default=None, description="Why not, in words")
    install_command: str | None = Field(default=None, description="The command that makes it available")
    connected: bool = Field(description="This computer syncs through a folder")
    mode: SyncMode = Field(
        description="``off`` (not connected), ``starting``, ``in_use`` (this computer is the one in use) or "
        "``standing_by`` (another computer is: writes are refused)"
    )
    activity: SyncActivity = Field(
        description="``idle``, ``saving``, ``waiting`` (for the sync tool), ``bringing_over`` (writes are "
        "refused for a moment) or ``keeping`` (writing a kept copy)"
    )
    progress: SyncProgress | None = None
    folder: str | None = Field(default=None, description="The sync folder on this computer")
    this_computer: str | None = Field(default=None, description="This computer's name")
    suggested_name: str = Field(description="The name offered when setting up (this computer's host name)")
    in_use_on: str | None = Field(default=None, description="The computer in use")
    computers: list[SyncComputer] = Field(default_factory=list, description="Every computer, this one too")
    last_saved_at: str | None = Field(
        default=None, description="This computer's clock: its last save into the folder"
    )
    pending_changes: bool = Field(
        default=False, description="This computer has changes that aren't in the sync folder yet"
    )
    others_have_latest: bool = Field(
        default=False,
        description="Another computer has received everything of this computer's (Disconnect and Delete "
        "everything ask twice when not)",
    )
    up_to_date: bool = Field(
        default=False, description="Standing by: the newest version has fully arrived here"
    )
    base_from: str | None = Field(
        default=None, description="Whose version this computer's data is (“the copy this computer has”)"
    )
    base_arrived_at: str | None = Field(default=None, description="This computer's clock: when it arrived")
    arriving: SyncArriving | None = None
    take_over_waiting: bool = Field(
        default=False, description="“Use Ordnung here” waits until everything has arrived"
    )
    choice: SyncChoice | None = Field(default=None, description="Both computers changed: which to keep")
    problem: SyncProblem | None = None
    notices: list[SyncNotice] = Field(default_factory=list)
    kept: list[SyncKept] = Field(default_factory=list, description="Kept copies on this computer")
    kept_warning: bool = Field(default=False, description="The kept copies take more than 2 GB in all")
    data_folder_synced: bool = Field(
        default=False,
        description="Ordnung's data folder itself is inside a synced folder, so the sync tool uploads it "
        "unencrypted",
    )


class SyncFolderInfo(BaseModel):
    """What a folder would be for sync (nothing is written)."""

    model_config = _RESPONSE

    kind: Literal["new", "existing", "refused"] = Field(
        description="``new``: missing or empty (apart from sync-tool files): a new sync starts there; "
        "``existing``: a sync to join; ``refused``: it can't be used (``problem`` says why)"
    )
    folder: str = Field(description="The folder as Ordnung would use it (resolved)")
    problem: str | None = Field(default=None, description="Why it can't be used, for people")
    examples: list[str] = Field(
        default_factory=list, description="Up to three names of other files found in it"
    )
    data_folder_synced: bool = Field(
        description="Ordnung's data folder itself is inside a synced folder (a warning, never a refusal)"
    )
    links_left_out: list[str] = Field(
        default_factory=list,
        description="Symbolic links in the data folder that sync leaves out (it never follows links)",
    )


class SyncConnected(BaseModel):
    """The result of setting up or joining: the status, or the choice to answer first."""

    model_config = _RESPONSE

    status: SyncStatus
    choice: SyncChoice | None = Field(
        default=None,
        description="Joining while this computer has its own letters: send ``keep`` to answer (nothing "
        "is connected yet)",
    )


# --------------------------------------------------------------------------------------------------
# models: requests
# --------------------------------------------------------------------------------------------------


class SyncInspect(BaseModel):
    """A folder to look at."""

    model_config = _REQUEST

    folder: str = Field(max_length=4096)


class SyncConnect(BaseModel):
    """Set up a new sync folder or join one (the passphrase is checked by the route)."""

    model_config = _REQUEST

    folder: str = Field(max_length=4096)
    name: str = Field(description=f"This computer's name (1 to {NAME_MAX_CHARS} characters)")
    passphrase: str
    keep: Literal["this", "folder"] | None = Field(
        default=None,
        description="Joining while this computer has its own letters: keep this computer's Ordnung, or "
        "the folder's (the other is kept as a copy)",
    )


class SyncChange(BaseModel):
    """Small changes and answers to a problem (each optional)."""

    model_config = _REQUEST

    name: str | None = Field(default=None, description="A new name for this computer")
    confirm_same_computer: bool = Field(
        default=False, description="“This is the same computer” (after the data folder moved or was copied)"
    )
    keep_as_is: bool = Field(
        default=False,
        description="“Keep this computer's data as it is” (after it went back in time and the last saved "
        "state can't be put back)",
    )
    abandon_pull: bool = Field(
        default=False, description="Give up a take-over that couldn't finish (this computer stands by)"
    )
    dismiss_notice: str | None = Field(default=None, description="A notice's ``id``")


class SyncDisconnect(BaseModel):
    """Disconnect this computer."""

    model_config = _REQUEST

    forget_passphrase: bool = Field(default=True, description="Also remove it from the password store")
    unreceived_ok: bool = Field(
        default=False,
        description="Disconnect although no other computer has this computer's latest changes yet (the "
        "second confirmation)",
    )


class SyncUseHere(BaseModel):
    """“Use Ordnung here”."""

    model_config = _REQUEST

    older_copy: bool = Field(
        default=False, description="Use the copy this computer has now instead of waiting for what arrives"
    )
    cancel: bool = Field(default=False, description="Stop a waiting take-over (or a waiting choice)")


class SyncChoose(BaseModel):
    """Which computer's Ordnung to keep."""

    model_config = _REQUEST

    keep: int = Field(description="The chosen side's ``key``")


class SyncSave(BaseModel):
    """Save now."""

    model_config = _REQUEST

    hand_over: bool = Field(default=False, description="Then stand by, so another computer can take over")


class SyncPassphrase(BaseModel):
    """The passphrase typed again (checked against the folder by the route)."""

    model_config = _REQUEST

    passphrase: str


# a body left out means every field's default (``POST /api/sync/save`` alone saves now)
_NO_DISCONNECT_BODY = SyncDisconnect()
_NO_USE_HERE_BODY = SyncUseHere()
_NO_SAVE_BODY = SyncSave()


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------


def _refusal(code: SyncErrorKind, detail: str) -> JSONResponse:
    return JSONResponse(status_code=ERROR_STATUS[code], content={"detail": detail, "code": code})


def _demo(state: ApiState, ctx: AppContext) -> bool:
    return state.demo or ctx.settings.demo or is_demo_dir(ctx.paths.data_dir)


def _suggested_name() -> str:
    """This computer's host name without its domain (“anna-thinkpad”), as a computer's name."""
    host = socket.gethostname().split(".", 1)[0].strip()
    return host[:NAME_MAX_CHARS] or "This computer"


def _status(state: ApiState, ctx: AppContext, secrets: SecretStore) -> SyncStatus:
    demo = _demo(state, ctx)
    problem = None if demo else secrets.problem()
    unavailable = DEMO_MESSAGE if demo else (str(problem) if problem is not None else None)
    return SyncStatus(
        available=unavailable is None,
        unavailable=unavailable,
        install_command=problem.install if problem is not None else None,
        connected=False,
        mode="off",
        activity="idle",
        suggested_name=_suggested_name(),
    )


def _write_refused(state: ApiState, ctx: AppContext) -> JSONResponse:
    """What every write answers while sync is off (the demo first)."""
    if _demo(state, ctx):
        return _refusal("unavailable", DEMO_MESSAGE)
    return _refusal("not_connected", NOT_CONNECTED_MESSAGE)


# --------------------------------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------------------------------


@router.get("/sync", response_model=SyncStatus)
async def sync_status(state: StateDep, ctx: CtxDep, secrets: SecretsDep) -> SyncStatus:
    """Whether sync can be used here, this computer's mode, the other computers, a choice, problems,
    notices and kept copies (from memory: never the folder or the password store)."""
    return await asyncio.to_thread(_status, state, ctx, secrets)


@router.post(
    "/sync/inspect",
    response_model=SyncFolderInfo,
    responses=_refusals(unavailable=_DEMO, not_connected=_NOT_CONNECTED),
    dependencies=COMPUTER,
)
async def inspect_sync_folder(
    body: SyncInspect, state: StateDep, ctx: CtxDep
) -> SyncFolderInfo | JSONResponse:
    """What ``folder`` would be: a new sync, one to join, or refused (and why). Nothing is written."""
    return _write_refused(state, ctx)


@router.put(
    "/sync",
    response_model=SyncConnected,
    responses=_refusals(
        unavailable=_DEMO,
        already_connected="this computer already syncs",
        newer_ordnung="the folder was set up by a newer Ordnung",
        full="the folder already serves 8 computers",
        not_arrived="the folder's key file hasn't fully arrived yet",
        not_connected=_NOT_CONNECTED,
        folder="the folder can't be used",
        name="the name is empty or too long",
        passphrase="a new folder's passphrase is too short or too easy to guess",
        wrong_passphrase="the passphrase doesn't open this folder",
        no_space="this computer lacks the space to bring Ordnung over",
    ),
    dependencies=COMPUTER,
)
async def connect_sync(body: SyncConnect, state: StateDep, ctx: CtxDep) -> SyncConnected | JSONResponse:
    """Set up a new sync folder (the passphrase twice in the form) or join an existing one; joining
    while this computer has letters answers the choice first, unless ``keep`` answers it."""
    return _write_refused(state, ctx)


@router.patch(
    "/sync",
    response_model=SyncStatus,
    responses=_refusals(
        unavailable=_DEMO,
        not_connected=_NOT_CONNECTED,
        not_needed="there's nothing to confirm or give up now",
        name="the name is empty or too long",
    ),
    dependencies=COMPUTER,
)
async def change_sync(body: SyncChange, state: StateDep, ctx: CtxDep) -> SyncStatus | JSONResponse:
    """Rename this computer, answer a problem, or dismiss a notice."""
    return _write_refused(state, ctx)


@router.delete(
    "/sync",
    response_model=SyncStatus,
    responses=_refusals(
        unavailable=_DEMO,
        not_received="no other computer has this computer's latest changes yet: ``unreceived_ok`` goes on",
    ),
    dependencies=COMPUTER,
)
async def disconnect_sync(
    state: StateDep, ctx: CtxDep, secrets: SecretsDep, body: SyncDisconnect = _NO_DISCONNECT_BODY
) -> SyncStatus | JSONResponse:
    """Disconnect this computer: its last changes are saved first, its head says it left, and
    ``<data>/sync/`` goes (kept copies stay). The folder and the other computers keep everything."""
    if _demo(state, ctx):
        return _refusal("unavailable", DEMO_MESSAGE)
    return await asyncio.to_thread(_status, state, ctx, secrets)  # not connected: nothing to do


@router.post(
    "/sync/use-here",
    response_model=SyncStatus,
    responses=_refusals(
        unavailable=_DEMO,
        not_connected=_NOT_CONNECTED,
        newer_ordnung="the other computer runs a newer Ordnung: update Ordnung here",
        pull_unfinished="a take-over must finish first",
        passphrase_needed="the passphrase isn't in the password store",
        folder_problem="the folder has a problem that stops a take-over",
        no_space="this computer lacks the space to take over",
    ),
    dependencies=COMPUTER,
)
async def use_sync_here(
    state: StateDep, ctx: CtxDep, body: SyncUseHere = _NO_USE_HERE_BODY
) -> SyncStatus | JSONResponse:
    """“Use Ordnung here”: bring everything over and make this computer the one in use — or wait until
    it has arrived (``take_over_waiting``), or answer with the choice when both computers changed."""
    return _write_refused(state, ctx)


@router.post(
    "/sync/choose",
    response_model=SyncStatus,
    responses=_refusals(
        unavailable=_DEMO,
        not_connected=_NOT_CONNECTED,
        no_choice="there's nothing to choose, or no such side",
        not_arrived="the chosen side hasn't arrived and can't be waited for",
        passphrase_needed="the passphrase is needed to keep this computer's copy",
        folder_problem="the folder has a problem that stops this",
        no_space="this computer lacks the space for it",
    ),
    dependencies=COMPUTER,
)
async def choose_sync(body: SyncChoose, state: StateDep, ctx: CtxDep) -> SyncStatus | JSONResponse:
    """Keep the chosen computer's Ordnung; the other one is kept as an encrypted copy on its own
    computer. Choosing makes this computer the one in use."""
    return _write_refused(state, ctx)


@router.post(
    "/sync/save",
    response_model=SyncStatus,
    responses=_refusals(
        unavailable=_DEMO,
        not_connected=_NOT_CONNECTED,
        standby="another computer is in use",
        folder_problem="the folder can't be written now",
    ),
    dependencies=COMPUTER,
)
async def save_sync(
    state: StateDep, ctx: CtxDep, body: SyncSave = _NO_SAVE_BODY
) -> SyncStatus | JSONResponse:
    """Save into the sync folder now; ``hand_over`` then stands by."""
    return _write_refused(state, ctx)


@router.post(
    "/sync/passphrase",
    response_model=SyncStatus,
    responses=_refusals(
        unavailable=_DEMO,
        not_connected=_NOT_CONNECTED,
        wrong_passphrase="the passphrase doesn't open this folder",
    ),
    dependencies=COMPUTER,
)
async def sync_passphrase(body: SyncPassphrase, state: StateDep, ctx: CtxDep) -> SyncStatus | JSONResponse:
    """Type the passphrase again: checked against the folder, then kept in the password store."""
    return _write_refused(state, ctx)


@router.post(
    "/sync/refill",
    response_model=SyncStatus,
    responses=_refusals(
        unavailable=_DEMO,
        not_connected=_NOT_CONNECTED,
        not_needed="the folder isn't empty, or another computer is in use",
    ),
    dependencies=COMPUTER,
)
async def refill_sync(state: StateDep, ctx: CtxDep) -> SyncStatus | JSONResponse:
    """Fill an emptied sync folder again from this computer (never done by itself: an unmounted share
    looks empty too)."""
    return _write_refused(state, ctx)


@router.delete(
    "/sync/computers/{key}",
    response_model=SyncStatus,
    responses=_refusals(
        unavailable=_DEMO,
        not_connected=_NOT_CONNECTED,
        in_use="that computer is the one in use (take over first)",
        not_arrived="its latest changes haven't arrived here, so they can't be kept yet",
        passphrase_needed="the passphrase is needed to keep its changes",
        no_space="this computer lacks the space to keep its changes",
        not_found="no other computer has that number",
    ),
    dependencies=COMPUTER,
)
async def forget_computer(key: int, state: StateDep, ctx: CtxDep) -> SyncStatus | JSONResponse:
    """Forget a lost computer: its changes that are nowhere else are kept as a copy here first. It
    still knows the passphrase (a new sync folder locks it out)."""
    return _write_refused(state, ctx)


@router.get(
    "/sync/kept/{name}",
    response_class=FileResponse,
    responses={
        200: {"content": {KEPT_TYPE: {}}, "description": "The kept copy (an encrypted backup)"},
        **_refusals(not_found="no kept copy of that name"),
    },
    dependencies=COMPUTER,
)
async def download_kept(name: str, state: StateDep) -> Response:
    """A kept copy as a download (open it with ``ordnung restore`` and the sync passphrase). ``name``
    must match :data:`~ordnung.sync.KEPT_RE` and be listed in the status."""
    return _refusal("not_found", NO_KEPT_COPY)  # none is listed while sync is off


@router.delete(
    "/sync/kept/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_refusals(unavailable=_DEMO, not_found="no kept copy of that name"),
    dependencies=COMPUTER,
)
async def delete_kept(name: str, state: StateDep, ctx: CtxDep) -> Response:
    """Delete a kept copy for good."""
    if _demo(state, ctx):
        return _refusal("unavailable", DEMO_MESSAGE)
    return _refusal("not_found", NO_KEPT_COPY)  # none is listed while sync is off
