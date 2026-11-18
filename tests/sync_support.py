"""Shared helpers for hand-off sync's server, API and command-line tests (no tests here): short timings,
an app per "computer" with the fake engine (:mod:`sync_fake_engine`) or the real one (:class:`RealEngine`)
and an in-memory password store, its lifespan running, and waiting for the agent's loop."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from fake_caldav import MemorySecrets
from ordnung.api.deps import SHUTDOWN_GRACE_S, ApiState
from ordnung.api.routes import sync as sync_routes
from ordnung.sync import agent as agent_module
from ordnung.sync import facade
from ordnung.sync.agent import SyncAgent
from sync_fake_engine import FakeEngine
from test_api_support import Api, api_for, lifespan

#: Five unrelated words: passes the new folder's passphrase rule (about 70 bits).
PASSPHRASE = "aqua-blunt-clay-dove-erupt"

#: The agent's timings for tests: short, but for a folder call's limit (``FOLDER_OP_TIMEOUT_S``), which is a loaded
#: machine's 10 s (the app's own is 30 s). Under 1 s, calls that were not meant to hang ran out now and then on a slow
#: CI runner: the second computer's scan as it joined, and with the real engine a look that copies the database,
#: which then went on running after the app stopped, holding ordnung.db open (on Windows a file still open can't be
#: replaced). A test that makes a folder call hang on purpose asks for 1 s (:func:`short_folder_limit`).
FAST = {
    "WATCH_S": 0.02,
    "PUSH_PERSON_QUIET_S": 0.05,
    "PUSH_QUIET_S": 0.15,
    "PUSH_MAX_WAIT_S": 1.0,
    "SCAN_S": 0.1,
    "WAIT_POLL_S": 0.05,
    "START_DECIDE_S": 3.0,
    "FENCE_WAIT_S": 1.0,
    "FOLDER_OP_TIMEOUT_S": 10.0,
    "UNREACHABLE_SCAN_S": 1.0,
    "SHUTDOWN_PUSH_S": 2.0,
    "PUSH_RETRY_S": (0.05,),
}


#: A folder call's limit for a test that makes one hang on purpose: short, so the test does not wait out FAST's 10 s.
HANG_FOLDER_OP_TIMEOUT_S = 1.0


class RealEngine(facade.RealEngine):
    """The real engine (the façade over the sync core) with an in-memory password store per computer,
    as :class:`~sync_fake_engine.FakeEngine` offers them (``computer(engine=RealEngine())``)."""

    def __init__(self) -> None:
        super().__init__()
        self.keyrings: dict[Path, MemorySecrets] = {}

    def keyring(self, data_dir: Path) -> MemorySecrets:
        return self.keyrings.setdefault(Path(data_dir).resolve(), MemorySecrets())


def fast_sync(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    """The agent's timings in tenths of seconds (a folder call's limit aside: see :data:`FAST`)."""
    for name, value in {**FAST, **overrides}.items():
        monkeypatch.setattr(agent_module, name, value)


def short_folder_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A folder call's limit of :data:`HANG_FOLDER_OP_TIMEOUT_S`, on top of the timings already set: for a test that
    makes a folder call hang on purpose."""
    monkeypatch.setattr(agent_module, "FOLDER_OP_TIMEOUT_S", HANG_FOLDER_OP_TIMEOUT_S)


def agent_of(api: Api) -> SyncAgent:
    state: ApiState = api.app.state.ordnung
    return state.sync


def state_of(api: Api) -> ApiState:
    state: ApiState = api.app.state.ordnung
    return state


@asynccontextmanager
async def computer(
    data_dir: Path,
    *,
    engine: FakeEngine | RealEngine | None = None,
    secrets: MemorySecrets | None = None,
    start: bool = True,
    **kwargs: Any,
) -> AsyncIterator[Api]:
    """An app on ``data_dir`` with the fake engine (or ``engine``) and an in-memory password store (its
    lifespan runs when ``start``). When the block ends, no engine call still uses the data folder — but
    one the test made hang and never released."""
    async with api_for(data_dir, **kwargs) as api:
        agent = agent_of(api)
        engine = engine or FakeEngine()
        agent.engine = engine  # type: ignore[assignment]
        store = secrets if secrets is not None else engine.keyring(data_dir)
        agent.secrets = store
        api.app.dependency_overrides[sync_routes.get_secrets] = lambda: store
        if not start:
            try:
                yield api
            finally:
                await agent.dispose()  # no lifespan stops the agent …
                state = state_of(api)
                if state.background_on:  # … nor the background work it started (after a failed join)
                    await state.stop_background(final=True)
                    await state.drain(SHUTDOWN_GRACE_S)  # the store closes next
            return
        async with lifespan(api.app):
            yield api
        hang = getattr(engine, "hang", None)
        if not (isinstance(hang, threading.Event) and not hang.is_set()):
            # the app's stop waits for a running engine call only so long; on a slow runner (Windows)
            # the next step, copying a data folder over this one, must not race the call
            await eventually(lambda: not agent._thread.busy, within=30)


async def eventually(check: Callable[[], Any], *, within: float = 15.0, step: float = 0.02) -> Any:
    """Wait until ``check()`` is truthy (an assertion failure names what it last returned)."""
    deadline = time.monotonic() + within
    last: Any = None
    while time.monotonic() < deadline:
        last = check()
        if last:
            return last
        await asyncio.sleep(step)
    raise AssertionError(f"not reached within {within} s (last: {last!r})")


async def connect(api: Api, folder: Path, name: str, **body: Any) -> Any:
    """``PUT /api/sync``; returns the JSON answer (asserting 200)."""
    response = await api.client.put(
        "/api/sync", json={"folder": str(folder), "name": name, "passphrase": PASSPHRASE, **body}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def status(api: Api) -> dict[str, Any]:
    response = await api.client.get("/api/sync")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found
