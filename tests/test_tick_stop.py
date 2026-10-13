"""Stopping the daily tick while one of its checks runs in a worker thread, and the store closing after.

A full test run crashed once ("Fatal Python error: Segmentation fault"): the daily tick's thread was in
calendar sync, inside ``Store.get_meta``, while the store closed. Cancelling the tick left that thread
running, and closing the store closed the connection the thread was using (SQLite connections are shared
between threads here). Stopping the tick now waits for its thread — at most :data:`ordnung.tick.STOP_WAIT_S`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from helpers_secretary import TODAY
from ordnung import clock
from ordnung import tick as tick_module
from ordnung.calendar import caldav
from ordnung.db.store import Store
from ordnung.ingest.pipeline import ledger_lock
from ordnung.llm.runtime import LLMService
from ordnung.tick import DailyTick
from sync_fake_engine import FakeEngine
from sync_support import PASSPHRASE, computer, connect, fast_sync, state_of


@dataclass
class Bus:
    events: list[str] = field(default_factory=list)

    def publish(self, type: str, **data: Any) -> None:
        self.events.append(type)


@dataclass
class Ctx:
    store: Store
    llm: LLMService | None = None
    bus: Bus = field(default_factory=Bus)


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("ORDNUNG_TODAY", raising=False)
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


class Held:
    """Holds a worker thread inside a call until :meth:`release` (and says when it got in and out)."""

    def __init__(self, call: Callable[..., Any]) -> None:
        self.call = call
        self.inside = threading.Event()
        self.released = threading.Event()
        self.out = threading.Event()
        self.outcome: list[object] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.inside.set()
        if not self.released.wait(10):
            raise AssertionError("never released")
        try:
            result = self.call(*args, **kwargs)
        except BaseException as exc:
            self.outcome.append(exc)
            raise
        else:
            self.outcome.append("done")
            return result
        finally:
            self.out.set()

    async def entered(self) -> None:
        assert await asyncio.to_thread(self.inside.wait, 10), "the tick never got there"

    def release(self) -> None:
        self.released.set()


def hold_meta_read(monkeypatch: pytest.MonkeyPatch, store: Store, key: str) -> Held:
    """Hold the thread that reads the meta value ``key`` inside ``Store.get_meta``."""
    real = store.get_meta
    held = Held(real)

    def get_meta(name: str) -> str | None:
        return held(name) if name == key else real(name)

    monkeypatch.setattr(store, "get_meta", get_meta)
    return held


async def not_done_after(task: asyncio.Task[None], seconds: float) -> bool:
    done, _ = await asyncio.wait({task}, timeout=seconds)
    return not done


async def test_stopping_waits_for_the_calendar_thread_before_the_store_closes(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = hold_meta_read(monkeypatch, store, caldav.STATE_KEY)  # calendar sync's first read
    tick = DailyTick(Ctx(store), calendar_sync=caldav.scheduled_sync, startup_grace_s=0)
    tick.start()
    await held.entered()
    stopping = asyncio.create_task(tick.stop())
    try:
        assert await not_done_after(stopping, 0.3), "stop() returned while the tick's thread was in the store"
    finally:
        held.release()
    await stopping
    assert held.outcome == ["done"]  # its read finished before stop() returned …
    store.close()  # … so closing now closes no connection that is in use


async def test_cancelling_the_days_work_keeps_the_ledger_lock_until_its_thread_ends(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The day's work runs under the ledger lock (letters being read link and reconcile under it too): a
    cancel let go of the lock while the thread was still reconciling."""
    held = Held(tick_module.run_and_reconcile)
    monkeypatch.setattr(tick_module, "run_and_reconcile", held)
    tick = DailyTick(Ctx(store), startup_grace_s=0)
    tick.start()
    await held.entered()
    stopping = asyncio.create_task(tick.stop())
    try:
        assert await not_done_after(stopping, 0.3)
        assert ledger_lock().locked(), "the ledger lock was let go while the day's work still ran"
    finally:
        held.release()
    await stopping
    assert held.outcome == ["done"] and not ledger_lock().locked()


async def test_two_stops_at_once_both_wait_for_the_days_work(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The computer standing by stops its background work while the app's own stop runs: the second cancel
    must not cut the first one's wait, or both return with the thread still reconciling and the ledger lock
    let go."""
    held = Held(tick_module.run_and_reconcile)
    monkeypatch.setattr(tick_module, "run_and_reconcile", held)
    tick = DailyTick(Ctx(store), startup_grace_s=0)
    tick.start()
    await held.entered()
    first = asyncio.create_task(tick.stop())
    await asyncio.sleep(0.05)
    second = asyncio.create_task(tick.stop())
    try:
        assert await not_done_after(first, 0.3) and not second.done()
        assert ledger_lock().locked(), "the ledger lock was let go while the day's work still ran"
    finally:
        held.release()
    await asyncio.gather(first, second)
    assert held.outcome == ["done"] and not ledger_lock().locked()


async def test_stopping_gives_up_on_a_thread_that_hangs(
    store: Store, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(tick_module, "STOP_WAIT_S", 0.2)
    held = Held(lambda _store: None)
    tick = DailyTick(Ctx(store), calendar_sync=held, startup_grace_s=0)
    tick.start()
    await held.entered()
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="ordnung.tick"):
        await asyncio.wait_for(tick.stop(), 5)
    assert time.monotonic() - started < 5
    assert "still running" in caplog.text
    held.release()
    assert await asyncio.to_thread(held.out.wait, 10)


async def test_an_app_without_its_lifespan_stops_the_background_work_its_sync_agent_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """How the crash came about: the laptop's app (no lifespan) joined with the wrong passphrase, and its
    sync agent started the background work again, as after any failed join. Nothing stopped it, and the
    test closed the store with the laptop's daily tick inside it (``sync_support.computer``)."""
    fast_sync(monkeypatch)
    (tmp_path / "Nextcloud").mkdir()
    folder = tmp_path / "Nextcloud" / "Ordnung"
    engine = FakeEngine()
    async with (
        computer(tmp_path / "desk", engine=engine) as desk,
        computer(tmp_path / "lap", engine=engine, start=False) as lap,
    ):
        await connect(desk, folder, "desktop")
        wrong = await lap.client.put(
            "/api/sync", json={"folder": str(folder), "name": "laptop", "passphrase": PASSPHRASE[::-1]}
        )
        assert wrong.status_code == 422
        laptop = state_of(lap)
        task = laptop.tick._task
        assert laptop.background_on and task is not None  # started again by the agent
    assert not laptop.background_on and task.done()
