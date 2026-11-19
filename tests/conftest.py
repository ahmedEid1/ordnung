"""Shared pytest fixtures: a throw-away data directory and a :class:`Store` opened on it."""

from __future__ import annotations

import asyncio
import gc
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from hypothesis import settings

import helpers_store
from ordnung import clock, durable
from ordnung.assistant import ask
from ordnung.config import OCR_SWITCH, Paths
from ordnung.db.store import Store

# One Hypothesis profile for every test, loaded before any test module is imported, so a test runs the same
# examples alone, in a subset, in a parallel worker or in the whole suite. No example database: no examples are
# saved in the checkout and no run replays another run's failures. A test that wants another number of examples
# says so with its own ``@settings``.
settings.register_profile("ordnung", max_examples=150, deadline=None, database=None)
settings.load_profile("ordnung")

# The terminal's size is never the tests': a CLI test sets the width it reads its output at (CliRunner's COLUMNS).
# Rich reads COLUMNS once, when a console is made, and keeps it as a fixed width, so ``ordnung.cli``'s consoles,
# made when a test module imports it, would keep whatever the environment held then. A pytest-xdist worker is
# started with the controller's terminal size in its environment (readline exports it there as COLUMNS and LINES,
# 80 and 24 without a terminal), so without this the CLI tests wrap their output at 80 columns in parallel runs only.
for _name in ("COLUMNS", "LINES"):
    os.environ.pop(_name, None)


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


@pytest.fixture(scope="session", autouse=True)
def _migrated_template(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """One migrated, empty database per test process (``helpers_store``), built with the real ``Store.open`` before
    any test runs; the ``store`` fixture and ``api_for`` start a test's data folder from a copy of it."""
    helpers_store.TEMPLATE = helpers_store.build_template(tmp_path_factory.mktemp("migrated"))
    yield
    helpers_store.TEMPLATE = None


@pytest.fixture
def store(paths: Paths) -> Iterator[Store]:
    """A migrated, empty store (a copy of the session's template database, opened for real); closed after the
    test."""
    helpers_store.seed_database(paths.data_dir)
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
