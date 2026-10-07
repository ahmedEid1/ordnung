"""Settings → Your computers: hand-off sync between the person's computers (policy: :mod:`ordnung.sync`).

* ``GET /api/sync`` — whether sync can be used here, this computer's mode (in use, standing by), the
  folder, the other computers, what is arriving, a choice to make, problems, notices and kept copies.
  It is answered from memory: it never touches the sync folder or reads the password store.
* ``POST /api/sync/inspect`` — what a folder would be: ``new``, ``existing`` (a sync to join) or
  ``refused`` (with the reason), and whether the data folder itself sits in a synced folder.
* ``PUT /api/sync`` — set up a new sync folder, or join an existing one; joining with letters on both
  sides answers the choice first (``keep`` answers it). While the folder is missing or holds another
  sync, it points this computer at its folder again (only a folder of this very sync is accepted).
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
:data:`ordnung.sync.ERROR_STATUS` gives it (raised as :class:`~ordnung.sync.SyncError`).

The work is the sync agent's (:class:`~ordnung.sync.agent.SyncAgent`, ``ApiState.sync``): it holds the
status in memory, serialises every operation, and runs the folder's blocking work in its own thread.
The password store comes through :func:`get_secrets` (tests replace it).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse, Response

from ordnung.api.deps import StateDep, require_computer
from ordnung.calendar.secrets import SecretStore
from ordnung.sync import ERROR_STATUS, SyncError, SyncRefused
from ordnung.sync.agent import SyncAgent
from ordnung.sync.status import (
    SyncChange,
    SyncChoose,
    SyncConnect,
    SyncConnected,
    SyncDisconnect,
    SyncFolderInfo,
    SyncInspect,
    SyncPassphrase,
    SyncSave,
    SyncStatus,
    SyncUseHere,
)

router = APIRouter(tags=["sync"])
COMPUTER = [Depends(require_computer)]

KEPT_TYPE = "application/octet-stream"
NO_KEPT_COPY = "There's no saved copy of that name (any more)."


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


def get_secrets(state: StateDep) -> SecretStore:
    """Where this computer keeps the sync passphrase (the agent's: the OS keyring; tests replace this
    dependency)."""
    return state.sync.secrets


SecretsDep = Annotated[SecretStore, Depends(get_secrets)]


# a body left out means every field's default (``POST /api/sync/save`` alone saves now)
_NO_DISCONNECT_BODY = SyncDisconnect()
_NO_USE_HERE_BODY = SyncUseHere()
_NO_SAVE_BODY = SyncSave()


async def _status(agent: SyncAgent, secrets: SecretStore) -> SyncStatus:
    """The status from memory; whether a password store can be used is asked without reading one."""
    keyring = None if agent.is_demo else await asyncio.to_thread(secrets.problem)
    return agent.status(keyring)


# --------------------------------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------------------------------


@router.get("/sync", response_model=SyncStatus)
async def sync_status(state: StateDep, secrets: SecretsDep) -> SyncStatus:
    """Whether sync can be used here, this computer's mode, the other computers, a choice, problems,
    notices and kept copies (from memory: never the folder or the password store)."""
    return await _status(state.sync, secrets)


@router.post(
    "/sync/inspect",
    response_model=SyncFolderInfo,
    responses=_refusals(unavailable=_DEMO, not_connected=_NOT_CONNECTED),
    dependencies=COMPUTER,
)
async def inspect_sync_folder(body: SyncInspect, state: StateDep) -> SyncFolderInfo:
    """What ``folder`` would be: a new sync, one to join, or refused (and why). Nothing is written."""
    return await state.sync.inspect(body.folder)


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
async def connect_sync(body: SyncConnect, state: StateDep, secrets: SecretsDep) -> SyncConnected:
    """Set up a new sync folder (the passphrase twice in the form) or join an existing one; joining
    while this computer has letters answers the choice first, unless ``keep`` answers it."""
    if state.sync.is_demo:
        raise SyncRefused()
    missing = await asyncio.to_thread(secrets.problem)
    if missing is not None:  # the passphrase could be kept nowhere
        raise SyncError("unavailable", str(missing))
    choice = await state.sync.connect(
        body.folder, body.name, body.passphrase, keep=body.keep, secrets=secrets
    )
    return SyncConnected(status=await _status(state.sync, secrets), choice=choice)


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
async def change_sync(body: SyncChange, state: StateDep, secrets: SecretsDep) -> SyncStatus:
    """Rename this computer, answer a problem, or dismiss a notice."""
    await state.sync.change(
        name=body.name,
        confirm_same_computer=body.confirm_same_computer,
        keep_as_is=body.keep_as_is,
        abandon_pull=body.abandon_pull,
        dismiss_notice=body.dismiss_notice,
    )
    return await _status(state.sync, secrets)


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
    state: StateDep, secrets: SecretsDep, body: SyncDisconnect = _NO_DISCONNECT_BODY
) -> SyncStatus:
    """Disconnect this computer: its last changes are saved first, its head says it left, and
    ``<data>/sync/`` goes (kept copies stay). The folder and the other computers keep everything."""
    await state.sync.disconnect(forget_passphrase=body.forget_passphrase, unreceived_ok=body.unreceived_ok)
    return await _status(state.sync, secrets)


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
    state: StateDep, secrets: SecretsDep, body: SyncUseHere = _NO_USE_HERE_BODY
) -> SyncStatus:
    """“Use Ordnung here”: bring everything over and make this computer the one in use — or wait until
    it has arrived (``take_over_waiting``), or answer with the choice when both computers changed."""
    await state.sync.use_here(older_copy=body.older_copy, cancel=body.cancel)
    return await _status(state.sync, secrets)


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
async def choose_sync(body: SyncChoose, state: StateDep, secrets: SecretsDep) -> SyncStatus:
    """Keep the chosen computer's Ordnung; the other one is kept as an encrypted copy on its own
    computer. Choosing makes this computer the one in use."""
    await state.sync.choose(body.keep)
    return await _status(state.sync, secrets)


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
async def save_sync(state: StateDep, secrets: SecretsDep, body: SyncSave = _NO_SAVE_BODY) -> SyncStatus:
    """Save into the sync folder now; ``hand_over`` then stands by."""
    await state.sync.save(hand_over=body.hand_over)
    return await _status(state.sync, secrets)


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
async def sync_passphrase(body: SyncPassphrase, state: StateDep, secrets: SecretsDep) -> SyncStatus:
    """Type the passphrase again: checked against the folder, then kept in the password store."""
    await state.sync.set_passphrase(body.passphrase, secrets=secrets)
    return await _status(state.sync, secrets)


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
async def refill_sync(state: StateDep, secrets: SecretsDep) -> SyncStatus:
    """Fill an emptied sync folder again from this computer (never done by itself: an unmounted share
    looks empty too)."""
    await state.sync.refill()
    return await _status(state.sync, secrets)


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
async def forget_computer(key: int, state: StateDep, secrets: SecretsDep) -> SyncStatus:
    """Forget a lost computer: its changes that are nowhere else are kept as a copy here first. It
    still knows the passphrase (a new sync folder locks it out)."""
    await state.sync.forget(key)
    return await _status(state.sync, secrets)


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
    path = state.sync.kept_file(name)
    if path is None:
        raise SyncError("not_found", NO_KEPT_COPY)
    return FileResponse(
        path,
        media_type=KEPT_TYPE,
        filename=name,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete(
    "/sync/kept/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_refusals(unavailable=_DEMO, not_found="no kept copy of that name"),
    dependencies=COMPUTER,
)
async def delete_kept(name: str, state: StateDep) -> Response:
    """Delete a kept copy for good."""
    if not await state.sync.delete_kept(name):
        raise SyncError("not_found", NO_KEPT_COPY)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
