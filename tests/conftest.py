"""Shared pytest fixtures: a throw-away data directory and a :class:`Store` opened on it."""

from __future__ import annotations

import gc
from collections.abc import Iterator
from pathlib import Path

import pytest

from ordnung import clock, durable
from ordnung.assistant import ask
from ordnung.config import Paths
from ordnung.db.store import Store


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
    """A demo context dates records on its simulated day, and hand-off sync makes writes durable; never
    let either leak into the next test."""
    yield
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
