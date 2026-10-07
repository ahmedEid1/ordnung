"""Shared helpers for hand-off sync's server, API and command-line tests (no tests here): short timings,
an app per "computer" with the fake engine (:mod:`sync_fake_engine`) and an in-memory password store,
its lifespan running, and waiting for the agent's loop."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from fake_caldav import MemorySecrets
from ordnung.api.deps import ApiState
from ordnung.api.routes import sync as sync_routes
from ordnung.sync import agent as agent_module
from ordnung.sync.agent import SyncAgent
from sync_fake_engine import FakeEngine
from test_api_support import Api, api_for, lifespan

#: Five unrelated words: passes the new folder's passphrase rule (about 70 bits).
PASSPHRASE = "aqua-blunt-clay-dove-erupt"

FAST = {
    "WATCH_S": 0.02,
    "PUSH_PERSON_QUIET_S": 0.05,
    "PUSH_QUIET_S": 0.15,
    "PUSH_MAX_WAIT_S": 1.0,
    "SCAN_S": 0.1,
    "WAIT_POLL_S": 0.05,
    "START_DECIDE_S": 3.0,
    "FENCE_WAIT_S": 1.0,
    "FOLDER_OP_TIMEOUT_S": 1.0,
    "SHUTDOWN_PUSH_S": 2.0,
    "PUSH_RETRY_S": (0.05,),
}


def fast_sync(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> None:
    """The agent's timings in tenths of seconds."""
    for name, value in {**FAST, **overrides}.items():
        monkeypatch.setattr(agent_module, name, value)


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
    engine: FakeEngine | None = None,
    secrets: MemorySecrets | None = None,
    start: bool = True,
    **kwargs: Any,
) -> AsyncIterator[Api]:
    """An app on ``data_dir`` with the fake engine and an in-memory password store (its lifespan runs
    when ``start``)."""
    async with api_for(data_dir, **kwargs) as api:
        agent = agent_of(api)
        engine = engine or FakeEngine()
        agent.engine = engine  # type: ignore[assignment]
        store = secrets if secrets is not None else engine.keyring(data_dir)
        agent.secrets = store
        api.app.dependency_overrides[sync_routes.get_secrets] = lambda: store
        if not start:
            yield api
            return
        async with lifespan(api.app):
            yield api


async def eventually(check: Callable[[], Any], *, within: float = 5.0, step: float = 0.02) -> Any:
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
