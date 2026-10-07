"""The person-change counter (review finding 5a, which replaces design §7.3's marks): moved inside the very
transaction of each write the person made, read by a push from its own snapshot — so a version holds
exactly the person changes it counts, in every interleaving, and nothing is ever under-counted."""

from __future__ import annotations

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


def counted(store: Store) -> int:
    return int(store.get_meta(PERSON_META_KEY) or 0)


def test_only_writes_inside_the_context_count(store: Store) -> None:
    store.add_note("background")
    assert counted(store) == 0
    with person_write():
        store.add_note("mine")
        assert PERSON_WRITE.get()
    assert not PERSON_WRITE.get()
    assert counted(store) == 1


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


def test_the_context_follows_the_request_into_threads() -> None:
    """``asyncio.to_thread`` copies the context: a route's blocking work still counts."""
    import asyncio

    async def route() -> bool:
        with person_write():
            return await asyncio.to_thread(PERSON_WRITE.get)

    assert asyncio.run(route())


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
