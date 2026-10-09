"""When Ordnung stops, hand-off sync lets go of the database: no engine call still reads it and no
connection of the agent's stays open. Windows can't delete or replace a file that is open, so in the
Windows CI job copying a data folder back over one whose app had just stopped failed ("being used by
another process"), and on Python 3.13 the connections only the garbage collector closed showed as
``ResourceWarning: unclosed database``.

Every SQLite connection a test opens is tracked (:func:`connections`); one never closed counts as open,
as it would until the garbage collector came by. On Linux the process's open files are checked too.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname

import pytest
from typer.testing import CliRunner

from fake_caldav import MemorySecrets
from fixtures_llm import fake_backend
from ordnung import cli, sync
from ordnung.app_context import build_context
from ordnung.cli import app
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.sync import agent as agent_module
from sync_fake_engine import FakeEngine, FakeSession
from sync_support import PASSPHRASE, agent_of, computer, connect, eventually, fast_sync
from test_api_support import lifespan

STILL_RUNNING = "sync: an operation was still running when Ordnung stopped"
runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    # no save on the loop's own timing: the engine calls a test arranges are the only ones it waits for
    fast_sync(monkeypatch, PUSH_PERSON_QUIET_S=60.0, PUSH_QUIET_S=60.0, PUSH_MAX_WAIT_S=60.0)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / "Nextcloud").mkdir()
    return tmp_path / "Nextcloud" / "Ordnung"


class _Tracked(sqlite3.Connection):
    """A connection that remembers whether it was closed."""

    closed = False

    def close(self) -> None:
        self.closed = True
        super().close()


def _file_of(database: Any) -> Path:
    target = str(database)
    if target.startswith("file:"):
        return Path(url2pathname(urlsplit(target).path))
    return Path(target)


@pytest.fixture
def connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[Path], list[str]]]:
    """Track every SQLite connection opened from now on; the function lists the ones on a database file
    that are still open, with the thread that opened each."""
    opened: list[tuple[Path, str, _Tracked]] = []
    real_connect = sqlite3.connect

    def connect(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        kwargs.setdefault("factory", _Tracked)
        conn = real_connect(database, *args, **kwargs)
        opened.append((_file_of(database), threading.current_thread().name, conn))
        return conn

    def still_open(db: Path) -> list[str]:
        wanted = db.resolve()
        return [
            f"{file.name} (opened on {thread})"
            for file, thread, conn in opened
            if not conn.closed and file.resolve() == wanted
        ]

    monkeypatch.setattr(sqlite3, "connect", connect)
    yield still_open
    for _file, _thread, conn in opened:  # none leaks into the next test
        if not conn.closed:
            with contextlib.suppress(sqlite3.Error):  # one of another thread's may refuse
                conn.close()


def _open_files(db: Path) -> list[str]:
    """This process's open files that are ``db`` or its ``-wal``/``-shm`` (Linux; elsewhere none)."""
    fds = Path("/proc/self/fd")
    if not fds.is_dir():
        return []
    found = []
    for fd in fds.iterdir():
        with contextlib.suppress(OSError):
            target = os.readlink(fd)
            if target.startswith(str(db.resolve())):
                found.append(Path(target).name)
    return sorted(found)


# --------------------------------------------------------------------------------------------------
# the app stops
# --------------------------------------------------------------------------------------------------


async def test_stopping_waits_for_a_running_engine_call(
    tmp_path: Path, folder: Path, connections: Callable[[Path], list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A look at a slow folder outlived its limit and still reads the database when Ordnung stops: the
    stop waits for it, so nothing holds the data folder once the app has stopped."""
    engine = FakeEngine()
    desk = tmp_path / "desk"
    db = Paths(desk).db
    slow, reading, release = threading.Event(), threading.Event(), threading.Event()
    local_view = FakeSession.local_view

    def slow_local_view(session: FakeSession, store: Store) -> Any:
        if slow.is_set():
            slow.clear()
            with contextlib.closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)) as conn:
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
                reading.set()
                release.wait(30)
        return local_view(session, store)

    monkeypatch.setattr(FakeSession, "local_view", slow_local_view)
    async with computer(desk, engine=engine, start=False) as api:
        agent = agent_of(api)
        close = agent.close

        async def close_and_answer_soon() -> None:
            threading.Timer(0.3, release.set).start()  # the slow call ends a moment after the stop began
            await close()

        agent.close = close_and_answer_soon  # type: ignore[method-assign]
        async with lifespan(api.app):
            await connect(api, folder, "desktop")
            slow.set()
            await eventually(reading.is_set)
            await eventually(lambda: agent.problem is not None)  # the look gave up; the call goes on
            assert agent._thread.busy
        assert not agent._thread.busy, "the app stopped while an engine call still read the database"
    assert connections(db) == []
    assert _open_files(db) == []


async def test_stopping_waits_no_longer_than_the_shutdown_limit(
    tmp_path: Path, folder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A folder that hangs for good never holds up the stop: it waits at most ``SHUTDOWN_PUSH_S``, says
    so in the log and leaves the hung call to its thread (a daemon: it never keeps Ordnung running)."""
    caplog.set_level(logging.WARNING, logger="ordnung.sync")
    engine = FakeEngine()
    desk = tmp_path / "desk"
    took: list[float] = []
    async with computer(desk, engine=engine, start=False) as api:
        agent = agent_of(api)
        close = agent.close

        async def timed_close() -> None:
            started = time.monotonic()
            await close()
            took.append(time.monotonic() - started)

        agent.close = timed_close  # type: ignore[method-assign]
        hang = threading.Event()
        try:
            async with lifespan(api.app):
                await connect(api, folder, "desktop")
                engine.hang = hang
                await eventually(lambda: agent.problem is not None)  # a look gave up; its call hangs
            assert agent._thread.busy
        finally:
            hang.set()
    assert took and took[0] <= agent_module.SHUTDOWN_PUSH_S + 1
    assert STILL_RUNNING in caplog.messages


async def test_a_computer_that_never_started_closes_its_agent(
    tmp_path: Path, folder: Path, connections: Callable[[Path], list[str]]
) -> None:
    """No lifespan ran (the API tests' ``start=False``): the agent still lets go of its read-only
    connection and its thread, without the last save a stop makes."""
    engine = FakeEngine()
    desk = tmp_path / "desk"
    async with computer(desk, engine=engine, start=False) as api:
        await connect(api, folder, "desktop")  # the first save opens the agent's read-only connection
        assert agent_of(api)._watch is not None
    assert connections(Paths(desk).db) == []
    assert "push:shutdown" not in engine.calls


async def test_a_read_only_connection_that_fails_is_closed_before_it_is_dropped(tmp_path: Path) -> None:
    class Broken:
        closed = False

        def execute(self, *_args: Any) -> Any:
            raise sqlite3.OperationalError("disk I/O error")

        def close(self) -> None:
            self.closed = True

    async with computer(tmp_path / "desk", start=False) as api:
        agent = agent_of(api)
        broken = Broken()
        agent._watch = broken  # type: ignore[assignment]
        assert agent._data_version_now() is None
        assert broken.closed and agent._watch is None


# --------------------------------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    """The fake engine for ``ordnung sync …`` in process (as in ``test_cli_sync.py``)."""
    fake = FakeEngine()
    keyring = MemorySecrets()
    monkeypatch.setattr(agent_module, "load_engine", lambda: fake)
    monkeypatch.setattr(agent_module, "default_secrets", lambda: keyring)
    monkeypatch.setattr(
        cli, "open_context", lambda data_dir: build_context(data_dir, backend_obj=fake_backend())
    )
    monkeypatch.setattr(cli, "reachable_server", lambda folder: None)
    monkeypatch.setenv(sync.PASSPHRASE_ENV, PASSPHRASE)
    return fake


def test_the_command_line_sync_closes_its_database_connections(
    engine: FakeEngine, data_dir: Path, folder: Path, connections: Callable[[Path], list[str]]
) -> None:
    """``ordnung sync`` lets go of the database before it gives the data folder's lock back: the agent's
    read-only connection was left to the garbage collector, after the lock."""
    db = Paths(data_dir).db
    for command in (["connect", str(folder), "--name", "desktop"], ["save"], ["status"]):
        result = runner.invoke(app, ["sync", *command, "--data-dir", str(data_dir)])
        assert result.exit_code == 0, result.output
        assert connections(db) == [], command
        assert _open_files(db) == [], command
