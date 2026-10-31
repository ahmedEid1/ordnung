"""Shared pytest fixtures: a throw-away data directory and a :class:`Store` opened on it."""

from __future__ import annotations

import asyncio
import gc
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ordnung import clock, durable
from ordnung.assistant import ask
from ordnung.config import OCR_SWITCH, Paths
from ordnung.db.store import Store


@pytest.fixture(autouse=True)
def _text_in_pictures_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text in pictures (ADR 0024) is off in every test, so a Tesseract installed on this computer or runner never
    reads a test's letters. A test that wants it on says so: ``monkeypatch.delenv("ORDNUNG_OCR")``."""
    monkeypatch.setenv(OCR_SWITCH, "off")


@pytest.fixture(autouse=True)
def _no_claude_from_the_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``claude`` and the backend a test uses are the ones it sets, never what the shell that runs pytest
    exports (the e2e config, the replay scripts and ``make capture`` export the fake Claude as
    ``ORDNUNG_CLAUDE_BIN``)."""
    monkeypatch.delenv("ORDNUNG_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("ORDNUNG_BACKEND", raising=False)


@pytest.fixture
def claude_exits_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every model call (``claude -p``) has exited before Ordnung writes its request: a broken install dies at
    start (``env: node: No such file or directory``) and often wins that race; here it always does. For a
    ``claude`` that exits without reading (``tests/fake_claude.py``'s ``exit_before_reading``)."""
    spawn = asyncio.create_subprocess_exec

    async def exited_first(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
        proc = await spawn(*args, **kwargs)
        if "-p" in args:  # not ``--version`` or ``auth status``
            await proc.wait()
            await asyncio.sleep(0.05)  # the closed pipe is noticed
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", exited_first)


@pytest.fixture(autouse=True)
def _ledger_memo_verified() -> Iterator[None]:
    """Ask keeps its ledger fingerprint per state of the ledger (``ask._LEDGER_MEMO``). In every test, each
    value it hands out from the memo is worked out again and compared; a difference fails the test here (not
    inside Ask, which turns an exception into an error event that could hide it)."""
    memo = ask._LEDGER_MEMO
    memo.verify = True
    yield
    found, memo.mismatches[:] = list(memo.mismatches), []
    assert found == [], f"Ask's ledger memo handed out a stale fingerprint: {found}"


@pytest.fixture(autouse=True)
def _real_stamps() -> Iterator[None]:
    """A demo context pins the clock to its simulated day and dates records on it, and hand-off sync makes
    writes durable; never let any of them leak into the next test."""
    yield
    clock.set_today(None)
    clock.stamp_simulated_day(False)
    durable.set_durable(False)  # hand-off sync turns process-wide fsyncs on; not for the next test


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """An empty Ordnung data directory inside pytest's tmp_path."""
    path = tmp_path / "data"
    path.mkdir()
    return path


@pytest.fixture
def paths(data_dir: Path) -> Paths:
    """The standard data-dir layout (files/, derived/, drafts/) under ``data_dir``."""
    return Paths(data_dir).ensure()


@pytest.fixture
def store(paths: Paths) -> Iterator[Store]:
    """A migrated, empty store; closed after the test."""
    opened = Store.open(paths)
    yield opened
    opened.close()


@pytest.fixture
def collection_paused() -> Iterator[None]:
    """No garbage collection while a test drives a parser to the recursion limit. A finalizer of
    an earlier test's garbage that runs at that depth (an unclosed connection's warning, a store's
    thread finalizers) has no stack left and fails, and pytest charges that to this test; so earlier
    garbage is collected first, at an ordinary depth."""
    gc.collect()
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            gc.enable()
