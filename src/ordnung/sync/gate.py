"""The standby gate: every write to the API passes it, from the computer's listener and the phone's
(policy: :mod:`ordnung.sync`; design §15.5).

``create_app`` adds :class:`SyncGate` *before* :class:`~ordnung.api.security.SecurityMiddleware`, so it
sits inside it: the computer's requests reach it after ``SecurityMiddleware``'s own checks, a phone's
after :class:`~ordnung.api.phone_gate.PhoneGate` — both call the inner application, which starts here.
Nothing in ``security.py`` changes.

For a request whose method isn't safe (anything but ``GET`` and ``HEAD``) on a path under ``/api`` but
not under :data:`~ordnung.sync.API_PATH` (``/api/sync`` and ``/api/sync/…``, matched by whole path
segments: ``/api/syncfoo`` is gated), the gate:

1. asks the agent whether writes are refused now — another computer is in use (except
   :data:`~ordnung.sync.ALLOWED_IN_STANDBY`), or data is being brought over or saved behind the fence —
   and if so answers 409 ``{"detail", "code": "standby"}`` before the body is read and before any
   handler runs (a phone's refused write is then not logged as a change, phone design M4);
2. otherwise counts the write as in flight while it runs (the fence waits until none is), and marks it
   as the person's — :data:`~ordnung.db.store.PERSON_WRITE`, so every transaction it commits bumps the
   person counter — unless it is in :data:`~ordnung.sync.NOT_PERSON_CHANGES` or sync isn't counting
   (not connected);
3. after it finished, tells the agent a person's write happened (the next save follows soon).

Safe methods pass untouched: the status, pages and the live events never wait for sync.
"""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from typing import Protocol

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ordnung.api.security import SAFE_METHODS
from ordnung.db.store import PERSON_WRITE
from ordnung.sync import ALLOWED_IN_STANDBY, API_PATH, NOT_PERSON_CHANGES, Operation

API_PREFIX = "/api"


class GateAgent(Protocol):
    """What the gate asks of the sync agent (:class:`~ordnung.sync.agent.SyncAgent`)."""

    def write_refusal(self, operation: Operation) -> str | None: ...
    def admitted(self) -> AbstractContextManager[None]: ...
    @property
    def counts_person_writes(self) -> bool: ...
    def person_wrote(self) -> None: ...


def _pattern(template: str) -> re.Pattern[str]:
    return re.compile(re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)) + r"\Z")


_KNOWN: tuple[tuple[Operation, re.Pattern[str]], ...] = tuple(
    (operation, _pattern(operation[1])) for operation in sorted(ALLOWED_IN_STANDBY | NOT_PERSON_CHANGES)
)


def is_sync_path(path: str) -> bool:
    """``/api/sync`` or a path below it (whole segments only)."""
    return path == API_PATH or path.startswith(API_PATH + "/")


def is_api_path(path: str) -> bool:
    return path == API_PREFIX or path.startswith(API_PREFIX + "/")


def operation_of(method: str, path: str) -> Operation:
    """The operation of a request as the gate's lists name it: the template of a listed operation
    (``DELETE /api/phone/devices/{device_id}``), else the request's own method and path."""
    for operation, pattern in _KNOWN:
        if operation[0] == method and pattern.match(path):
            return operation
    return (method, path)


def gated(method: str, path: str) -> bool:
    """Whether a request passes the gate's checks: a write to the API outside hand-off sync's own."""
    return method not in SAFE_METHODS and is_api_path(path) and not is_sync_path(path)


class SyncGate:
    """ASGI middleware (see the module docstring)."""

    def __init__(self, app: ASGIApp, *, agent: GateAgent) -> None:
        self.app = app
        self.agent = agent

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope["method"]).upper()
        path = str(scope["path"])
        if not gated(method, path):
            await self.app(scope, receive, send)
            return
        operation = operation_of(method, path)
        refusal = self.agent.write_refusal(operation)
        if refusal is not None:
            response = JSONResponse({"detail": refusal, "code": "standby"}, status_code=409)
            await response(scope, receive, send)
            return
        person = self.agent.counts_person_writes and operation not in NOT_PERSON_CHANGES
        with self.agent.admitted():
            token = PERSON_WRITE.set(person)
            try:
                await self.app(scope, receive, send)
            finally:
                PERSON_WRITE.reset(token)
        if person:
            self.agent.person_wrote()
