"""FastAPI dependencies and the per-app state the routes share.

``create_app`` stores one :class:`ApiState` on ``app.state.ordnung``; routes reach the application
context, the store and the app's "today" through the ``*Dep`` aliases below. The state also owns the
API's own background tasks (the on-demand Ideas review) and the cached Claude CLI status shown by
``GET /api/health`` (probed at most every 10 minutes, never with a model call). "Run check"
(``GET /api/health?probe=1``) runs the doctor with one tiny live call, at most once a minute.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, Request

from ordnung.app_context import AppContext
from ordnung.db.store import Store
from ordnung.doctor import DoctorReport, run_doctor
from ordnung.llm import claude_cli
from ordnung.models import ClaudeStatus
from ordnung.tick import local_today

log = logging.getLogger(__name__)

CLAUDE_STATUS_TTL_S = 10 * 60.0
PROBE_INTERVAL_S = 60.0
_CLI_BACKENDS = frozenset({"claude", "claude_cli"})

StatusProbe = Callable[[], Awaitable[ClaudeStatus]]
DoctorRunner = Callable[..., Awaitable[DoctorReport]]
"""``run_doctor(data_dir, *, probe=...)`` — replaceable in tests."""


# --------------------------------------------------------------------------------------------------
# Claude CLI status (zero-token)
# --------------------------------------------------------------------------------------------------


def _signed_in(status: dict[str, Any] | None) -> bool | None:
    """``loggedIn`` from ``claude auth status`` (``None`` when the answer can't be read)."""
    if status is None:
        return None
    value = status.get("loggedIn", status.get("logged_in"))
    return value if isinstance(value, bool) else None


def _status_detail(installed: bool, signed_in: bool | None) -> str:
    if not installed:
        return "The claude command-line tool was not found. Install Claude Code and sign in to let Ordnung read letters."
    if signed_in is False:
        return "Claude is installed but not signed in. Run “claude” once in a terminal and sign in."
    detail = "Signed in with your Claude account." if signed_in else "Claude is installed."
    if os.environ.get("ANTHROPIC_API_KEY"):
        detail += (
            " ANTHROPIC_API_KEY is set, so calls are billed to that API key instead of your subscription."
        )
    return detail


async def probe_claude_cli() -> ClaudeStatus:
    """Check the local ``claude`` CLI without spending tokens: ``--version`` and ``auth status``."""
    path = claude_cli.find_claude()
    if path is None:
        return ClaudeStatus(installed=False, detail=_status_detail(False, None))
    version, auth = await asyncio.gather(claude_cli.version(path), claude_cli.auth_status(path))
    signed_in = _signed_in(auth)
    return ClaudeStatus(
        installed=True, version=version, path=path, ok=signed_in, detail=_status_detail(True, signed_in)
    )


class ClaudeStatusCache:
    """The Claude CLI status, probed at most once per ``ttl_s`` seconds (one probe at a time).

    Backends that never run the CLI (recorded demo answers, the test fake) are reported without
    probing, so tests and the demo never start a ``claude`` process.
    """

    def __init__(self, probe: StatusProbe = probe_claude_cli, *, ttl_s: float = CLAUDE_STATUS_TTL_S) -> None:
        self.probe = probe
        self.ttl_s = ttl_s
        self._value: tuple[float, ClaudeStatus] | None = None
        self._lock = asyncio.Lock()

    def remember(self, status: ClaudeStatus) -> None:
        """Store a status found by a fuller check (``/api/health?probe=1``) as the cached one."""
        self._value = (time.monotonic(), status)

    async def get(self, backend_name: str, *, uses_cli: bool) -> ClaudeStatus:
        """The cached status (refreshed when older than the TTL)."""
        if not uses_cli:
            return ClaudeStatus(
                installed=False,
                detail=f"This session uses the “{backend_name}” backend; Claude is not called.",
            )
        async with self._lock:
            now = time.monotonic()
            if self._value is None or now - self._value[0] > self.ttl_s:
                self._value = (now, await self.probe())
            return self._value[1]


class RateLimit:
    """Allows one call per ``interval_s`` seconds (the live Claude check spends a few tokens)."""

    def __init__(self, interval_s: float) -> None:
        self.interval_s = interval_s
        self._last: float | None = None

    def acquire(self) -> int:
        """``0`` when the call may run now (and counts from now), else the seconds left to wait."""
        now = time.monotonic()
        if self._last is not None and now - self._last < self.interval_s:
            return max(1, round(self.interval_s - (now - self._last)))
        self._last = now
        return 0


def backend_uses_cli(ctx: AppContext) -> bool:
    """Whether the model backend runs the ``claude`` CLI (directly or as a replay fallback)."""
    backend = ctx.llm.backend
    fallback = getattr(backend, "fallback", None)
    names = {backend.name, getattr(fallback, "name", "")}
    return bool(names & _CLI_BACKENDS)


# --------------------------------------------------------------------------------------------------
# Background tasks owned by the API
# --------------------------------------------------------------------------------------------------


class BackgroundTasks:
    """Named fire-and-forget tasks (one per name at a time), cancelled when the app shuts down."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def running(self, name: str) -> bool:
        """Whether a task with this name is still running."""
        task = self._tasks.get(name)
        return task is not None and not task.done()

    def start(self, name: str, coro: Coroutine[Any, Any, None]) -> bool:
        """Start ``coro`` as ``name`` unless one is running (then ``coro`` is closed, ``False``)."""
        if self.running(name):
            coro.close()
            return False
        task = asyncio.create_task(coro, name=f"ordnung-api-{name}")
        task.add_done_callback(self._finished)
        self._tasks[name] = task
        return True

    @staticmethod
    def _finished(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and task.exception() is not None:
            log.error("background task %s failed", task.get_name(), exc_info=task.exception())

    async def wait(self, name: str) -> None:
        """Wait for the task ``name`` to finish (no-op if none)."""
        task = self._tasks.get(name)
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(task)

    async def stop(self) -> None:
        """Cancel every running task and wait for them."""
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()


# --------------------------------------------------------------------------------------------------
# State and dependencies
# --------------------------------------------------------------------------------------------------


@dataclass(eq=False)
class ApiState:
    """What the routes share: the application context, the server mode and API-owned helpers."""

    ctx: AppContext
    demo: bool = False
    token: str | None = None
    claude: ClaudeStatusCache = field(default_factory=ClaudeStatusCache)
    background: BackgroundTasks = field(default_factory=BackgroundTasks)
    doctor: DoctorRunner = run_doctor
    probe_limit: RateLimit = field(default_factory=lambda: RateLimit(PROBE_INTERVAL_S))


def get_state(request: Request) -> ApiState:
    """The :class:`ApiState` of the running app."""
    state: ApiState = request.app.state.ordnung
    return state


def get_ctx(state: Annotated[ApiState, Depends(get_state)]) -> AppContext:
    """The application context (store, model service, event bus, worker)."""
    return state.ctx


def get_store(ctx: Annotated[AppContext, Depends(get_ctx)]) -> Store:
    """The ledger database."""
    return ctx.store


def get_today(store: Annotated[Store, Depends(get_store)]) -> date:
    """The app's today: the person's local date (profile time zone) or the pinned demo date."""
    return local_today(store)


StateDep = Annotated[ApiState, Depends(get_state)]
CtxDep = Annotated[AppContext, Depends(get_ctx)]
StoreDep = Annotated[Store, Depends(get_store)]
TodayDep = Annotated[date, Depends(get_today)]
