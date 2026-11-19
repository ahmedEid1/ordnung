"""The person-change counter (SPEC §12c): moved inside the very
transaction of each write the person made, read by a push from its own snapshot — so a version holds
exactly the person changes it counts, in every interleaving, and nothing is ever under-counted."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from fakes import use_fast_keys
from ordnung.backup.archive import database_copy
from ordnung.db.store import PERSON_META_KEY, PERSON_WRITE, Store, person_write
from ordnung.sync.scrub import person_count
from sync_harness import Computer


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)
    monkeypatch.setattr(os, "fsync", lambda fd: None)  # no test here is about durability: skip the disk flush


def counted(store: Store) -> int:
    return int(store.get_meta(PERSON_META_KEY) or 0)


def test_only_writes_inside_the_context_count(store: Store) -> None:
    store.add_note("background")
    assert store.get_meta(PERSON_META_KEY) is None
    with person_write():
        store.add_note("mine")
        assert PERSON_WRITE.get()
    assert not PERSON_WRITE.get()
    assert counted(store) == 1
    before = counted(store)
    with person_write():
        store.add_note("mine")
        store.add_note("mine too")
        store.set_meta("profile", store.get_meta("profile") or "{}")  # changes nothing: still counted once
    assert counted(store) >= before + 2
    count = counted(store)
    with person_write():
        store.list_notes()
    assert counted(store) == count  # reading counts nothing


def test_a_rolled_back_write_counts_nothing(store: Store) -> None:
    with person_write(), pytest.raises(RuntimeError), store.tx():
        store.add_note("undone")
        raise RuntimeError("the request failed")
    assert counted(store) == 0


def test_a_transaction_that_changed_nothing_counts_nothing(store: Store) -> None:
    with person_write(), store.tx() as conn:
        conn.execute("SELECT 1")
    assert counted(store) == 0


def test_nested_transactions_count_once(store: Store) -> None:
    with person_write(), store.tx():
        store.add_note("one")
        store.add_note("two")
    assert counted(store) == 1


def test_every_snapshot_holds_exactly_the_changes_it_counts(store: Store) -> None:
    """Every interleaving of the person's commits and a push's snapshot: the counter in a snapshot is
    always the number of person changes that snapshot contains (never fewer, never more)."""
    stop = threading.Event()
    written = 0

    def person() -> None:
        nonlocal written
        while not stop.is_set() and written < 400:
            with person_write():
                store.add_note(f"person {written}")
            written += 1

    def background() -> None:
        n = 0
        while not stop.is_set() and n < 400:
            store.add_note(f"background {n}")
            n += 1

    threads = [threading.Thread(target=person), threading.Thread(target=background)]
    for thread in threads:
        thread.start()
    checks = 0
    while any(t.is_alive() for t in threads):
        copy = database_copy(store.db_path)
        try:
            notes = copy.execute("SELECT count(*) FROM notes WHERE text LIKE 'person %'").fetchone()[0]
            assert (person_count(copy) or 0) == notes
        finally:
            copy.close()
        checks += 1
    stop.set()
    for thread in threads:
        thread.join()
    assert checks > 3 and counted(store) == written


def test_changes_made_while_no_server_ran_count(tmp_path: Path) -> None:
    a = Computer("a", tmp_path / "a", tmp_path / "sync")
    try:
        a.connect()
        pnum = a.s.state.pnum
        a.close()
        offline = Store.open(a.paths)
        with person_write():  # `ordnung add` in process: cli._in_process sets the context
            offline.add_note("added from the command line")
        offline.close()
        a.restart()
        assert a.s.pending(a.db)
        outcome = a.round()
        assert outcome.pushed is not None and outcome.pushed.person and a.s.state.pnum == pnum + 1
    finally:
        a.close()


def test_a_missing_counter_counts_as_a_change(tmp_path: Path) -> None:
    a = Computer("a", tmp_path / "a", tmp_path / "sync")
    try:
        a.connect()
        a.db.set_meta(PERSON_META_KEY, None)  # a database put back by hand
        assert a.s.pending(a.db)
        outcome = a.round()
        assert outcome.pushed is not None and outcome.pushed.outcome in ("pushed", "accounted")
        assert a.db.get_meta(PERSON_META_KEY) is not None and not a.s.pending(a.db)
    finally:
        a.close()


def test_sync_bookkeeping_is_never_a_person_change(tmp_path: Path) -> None:
    a = Computer("a", tmp_path / "a", tmp_path / "sync")
    try:
        with person_write():  # even when the caller is inside a person's request
            a.connect()
            before = counted(a.db)
            a.s.log(a.db, "sync.connected", "x")
            a.s.mark(a.db, a.s.state.base.ref.id)  # type: ignore[union-attr]
        assert counted(a.db) == before
    finally:
        a.close()


async def test_background_work_a_request_starts_is_never_the_persons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The watched folder, the day change, the weekly review, the phone's address watcher and the check
    for Claude run as background work even when a request of the person's starts them (a settings
    save): their writes never move the person counter (they used to inherit ``PERSON_WRITE``)."""
    import asyncio
    from datetime import date
    from typing import Any

    from fixtures_llm import fake_backend
    from ordnung.app_context import build_context
    from ordnung.db.store import PERSON_WRITE
    from ordnung.ingest.watcher import FolderWatcher
    from ordnung.ingest.worker import IngestWorker
    from ordnung.phone.access import PhoneAccess
    from ordnung.tick import DailyTick

    seen: dict[str, bool] = {}

    def capture(name: str) -> Any:
        async def run(*_args: Any, **_kwargs: Any) -> None:
            seen[name] = PERSON_WRITE.get()

        return lambda *_args, **_kwargs: run()

    monkeypatch.setattr(DailyTick, "run_forever", capture("day change"))
    monkeypatch.setattr(DailyTick, "_run_review", capture("weekly review"))
    monkeypatch.setattr(DailyTick, "_usable_llm", lambda self: object())
    monkeypatch.setattr(DailyTick, "_review_due", lambda self, today: True)
    monkeypatch.setattr(FolderWatcher, "_run", capture("watched folder"))
    monkeypatch.setattr(PhoneAccess, "_watch", capture("phone's address watcher"))
    ctx = build_context(tmp_path / "data", backend_obj=fake_backend())
    try:
        (tmp_path / "Scans").mkdir()
        ctx.store.save_settings({"inbox_dir": str(tmp_path / "Scans"), "llm_review": True})
        ctx.reload_settings()
        tick, watcher = DailyTick(ctx), FolderWatcher(ctx)
        phone = PhoneAccess(ctx, demo=False, token_on=True)
        worker = ctx.worker
        assert isinstance(worker, IngestWorker)
        checks: list[bool] = []

        async def check() -> bool:
            checks.append(PERSON_WRITE.get())
            return False

        with person_write():  # a request of the person's starts them
            tasks: list[Any] = [tick.start()]
            assert tick._start_review(date(2026, 10, 7))
            tasks.append(tick._review)
            await watcher._start_task()
            tasks.append(watcher._task)
            phone._start_watcher()
            tasks.append(phone._watcher)
            worker.claude_check, worker._wake, worker._checked_claude_at = check, asyncio.Event(), None
            worker._check_claude()
            tasks.append(worker._claude_checking)
        await asyncio.gather(*tasks)
        seen["the check for Claude"] = checks == [True]
        assert seen == {
            "day change": False,
            "weekly review": False,
            "watched folder": False,
            "phone's address watcher": False,
            "the check for Claude": False,
        }
    finally:
        ctx.close()


async def test_a_settings_save_of_this_computer_s_own_settings_is_not_a_person_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Critique 14: saving only per-computer settings (notifications, the watched folder) never counts
    as the person's change — with unsaved background work it made a person version (a false choice)."""
    from sync_fake_engine import counter
    from sync_support import computer, connect, fast_sync

    fast_sync(monkeypatch)
    (tmp_path / "Nextcloud").mkdir()
    (tmp_path / "Scans").mkdir()
    async with computer(tmp_path / "desk") as api:
        await connect(api, tmp_path / "Nextcloud" / "Vault", "desktop")
        before = counter(api.ctx.store)
        for local in (
            {"desktop_notifications": "full"},
            {"desktop_notify_time": "07:30", "concurrency": 3},
            {"inbox_dir": str(tmp_path / "Scans")},
        ):
            saved = await api.client.put("/api/settings", json=local)
            assert saved.status_code == 200, saved.text
            assert counter(api.ctx.store) == before, local
        synced = await api.client.put("/api/settings", json={"llm_review": False})
        assert synced.status_code == 200 and counter(api.ctx.store) == before + 1
