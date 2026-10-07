"""One test (at least) for every finding of the sync review (``critique.md``) that the sync core carries:
blockers 1-4, highs 6-8, findings 9-12, 14-18, 20-21, 25-26, 30 and 34. Several are also covered in depth
elsewhere (named in each docstring); these pin the finding itself."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from fakes import use_fast_keys
from ordnung import durable
from ordnung.db.store import Store, person_write
from ordnung.models import CalendarSyncState
from ordnung.sync import (
    DAMAGED_AFTER_S,
    KEY_FILE_BYTES,
    SLICE_CHURN_LIMIT_BYTES,
    SYNC_KDF,
    SyncError,
    passphrase_problem,
)
from ordnung.sync import lineage as lin
from ordnung.sync.crypto import padme, sealed_size
from ordnung.sync.decide import BringIn, Choice, Pull
from ordnung.sync.model import Lineage
from sync_harness import Computer
from sync_sim import SyncToolSim, listing


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)


class Shared:
    """Two computers on one folder (delivery is instant); A set up with a letter, B joined and in use,
    A standing by."""

    def __init__(self, tmp: Path) -> None:
        self.a = Computer("anna-laptop", tmp / "a", tmp / "sync")
        self.b = Computer("desktop", tmp / "b", tmp / "sync")
        self.a.add_letter("first")
        self.a.connect()
        self.b.connect()
        self.a.round()

    def close(self) -> None:
        self.a.close()
        self.b.close()


@pytest.fixture
def shared(tmp_path: Path):  # type: ignore[no-untyped-def]
    made = Shared(tmp_path)
    yield made
    made.close()


# --------------------------------------------------------------------------------------------------
# blockers
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("point", ["after_decide", "after_stage", "after_kept", "in_transaction"])
def test_blocker_1_a_write_between_decision_and_journal_is_never_lost(
    shared: Shared, monkeypatch: pytest.MonkeyPatch, point: str
) -> None:
    a, b = shared.a, shared.b
    b.delete_letter(next(iter(b.letters())))  # so the pull keeps a copy first
    b.person_edit("from the desktop")
    b.round()
    from ordnung.sync import engine as engine_module
    from ordnung.sync import pull as pull_module
    from ordnung.sync import scrub as scrub_module

    def write() -> None:
        with person_write():
            a.db.add_note(f"written {point}")

    if point == "after_decide":
        real_stage = engine_module.Session.stage

        def stage(self, head, *, keep=False):  # type: ignore[no-untyped-def]
            write()
            return real_stage(self, head, keep=keep)

        monkeypatch.setattr(engine_module.Session, "stage", stage)
    elif point == "after_stage":
        real_removed = engine_module.removed_letters

        def removed(staged, store):  # type: ignore[no-untyped-def]
            write()
            return real_removed(staged, store)

        monkeypatch.setattr(engine_module, "removed_letters", removed)
    elif point == "after_kept":
        real_apply = engine_module.Session.apply

        def apply(self, staged, store, **kw):  # type: ignore[no-untyped-def]
            write()
            return real_apply(self, staged, store, **kw)

        monkeypatch.setattr(engine_module.Session, "apply", apply)
    else:
        real_merge = scrub_module.merge_local

        def merge(staged, live, **kw):  # type: ignore[no-untyped-def]
            # a write that commits just before the transaction that would replace the database
            write()
            return real_merge(staged, live, **kw)

        monkeypatch.setattr(pull_module, "merge_local", merge)
    try:
        outcome: Any = a.use_here()
    except SyncError as refused:
        outcome = refused
    kept_notes: set[str] = set()
    if not isinstance(outcome, SyncError) and outcome.kept is not None:
        from ordnung.backup import restore_backup

        restore_backup(
            a.s.local.kept_dir / outcome.kept.name, "orbit velvet canyon maple thunder", a.root / "copy"
        )
        with Store.open(type(a.paths)(a.root / "copy")) as copy:
            kept_notes = {row["text"] for row in copy._conn().execute("SELECT text FROM notes")}
    note = f"written {point}"
    assert note in a.notes() or note in kept_notes, (point, outcome)


def test_blocker_2_leave_pushes_and_a_left_head_still_counts(shared: Shared) -> None:
    a, b = shared.a, shared.b
    b.person_edit("last words")
    with pytest.raises(SyncError) as refused:
        b.s.leave(b.db)
    assert refused.value.kind == "not_received"
    b.s.leave(b.db, unreceived_ok=True)
    view = a.s.scan()
    left = view.by_computer(b.s.state.computer)
    assert left is not None and left.left and left.head.version is not None
    assert view.holder != b.s.state.computer  # out of the election …
    outcome = a.use_here()
    assert isinstance(outcome.decision, Pull) and "last words" in a.notes()  # … not out of the content


def test_blocker_3_behind_uses_covers() -> None:
    a, b = "a" * 32, "b" * 32
    winner = lin.keep_this(lin.make({a: [(1, 2)]}), [lin.make({a: [(1, 1)], b: [(1, 1)]})])
    loser = lin.make({a: [(1, 1)], b: [(1, 1)]})
    assert lin.relation(winner, loser) == "behind"
    assert lin.relation(loser, winner) == "decided"


def test_blocker_4_counters_are_raised_to_what_the_folder_shows(shared: Shared, tmp_path: Path) -> None:
    a = shared.a
    a.use_here()
    a.close()
    saved = tmp_path / "saved-state.json"
    saved.write_bytes((a.paths.data_dir / "sync" / "state.json").read_bytes())
    a.restart()
    for _ in range(3):
        a.person_edit("x")
        a.round()
    seq, pnum, written = a.s.state.seq, a.s.state.pnum, a.s.state.written
    a.close()
    (a.paths.data_dir / "sync" / "state.json").write_bytes(saved.read_bytes())  # put back from a backup
    a.restart()
    assert a.s.state.seq >= seq and a.s.state.pnum >= pnum and a.s.state.written >= written


# --------------------------------------------------------------------------------------------------
# highs
# --------------------------------------------------------------------------------------------------


def test_finding_6_has_is_written_only_for_a_verified_version(tmp_path: Path) -> None:
    a = Computer("a", tmp_path / "a", tmp_path / "a-sync")
    b = Computer("b", tmp_path / "b", tmp_path / "b-sync")
    sim = SyncToolSim(a.folder, b.folder)
    try:
        a.add_letter("x")
        a.connect()
        sim.settle()
        b.connect()
        sim.settle()
        a.round()
        a.use_here()
        sim.settle()
        b.round()
        letter = a.add_letter("y")
        a.round()
        sim.settle()
        sha = a.db._conn().execute("SELECT sha256 FROM documents WHERE id=?", (letter,)).fetchone()[0]
        name = a.s.vault.object_name("f", sha)
        damaged = b.folder / "o" / name[:2] / name[2:]  # an object b needs (it hasn't the letter)
        damaged.write_bytes(b"\x01" * damaged.stat().st_size)  # right size, wrong bytes
        sim.known["b"] = listing(b.folder)
        before = b.s.state.has
        b.round()
        assert b.s.state.has == before  # not acknowledged: it doesn't verify
    finally:
        a.close()
        b.close()


def test_finding_7_wants_reach_the_other_head(shared: Shared) -> None:
    a, b = shared.a, shared.b
    b.person_edit("x")
    b.round()
    manifest = b.s.scanner.manifest(b.s.state.base.ref)  # type: ignore[union-attr]
    assert manifest is not None
    name = a.s.vault.object_name("d", manifest.db.slices[0].sha256)
    path = a.folder / "o" / name[:2] / name[2:]
    path.write_bytes(b"\x00" * path.stat().st_size)
    a.use_here()  # waits: the slice doesn't verify
    a.clock.advance(DAMAGED_AFTER_S + 1)
    a.round()
    assert name in a.s.state.wants
    view = b.s.scan()
    assert name in view.wants
    b.round()  # a new version, the slice written again (forced)
    assert a.round().replaced or a.use_here().replaced


def test_finding_8_sizes() -> None:
    assert padme(1_000_000) == 1_015_808
    assert sealed_size(4096) == 23 + 4096 + 16
    assert sealed_size(1 << 20) == 23 + (1 << 20) + 16
    assert sealed_size((1 << 20) + 1) == 23 + (1 << 20) + 1 + 32


# --------------------------------------------------------------------------------------------------
# mediums
# --------------------------------------------------------------------------------------------------


def test_finding_9_every_head_is_read_on_every_scan(shared: Shared) -> None:
    a, b = shared.a, shared.b
    head = a.folder / "h" / b.s.head_file
    stat = head.stat()
    b.person_edit("same size, same mtime")
    b.round()
    os.utime(head, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # a cloud folder that keeps mtimes to the second
    view = a.s.scan()
    other = view.by_computer(b.s.state.computer)
    assert other is not None and other.head.version == b.s.state.base.ref  # type: ignore[union-attr]
    cached = json.loads((a.paths.data_dir / "sync" / "heads.json").read_text())
    assert b.s.head_file in cached  # the last good copy (F14, GC)


def test_finding_10_both_sides_check_the_files_the_database_names(shared: Shared) -> None:
    from ordnung.sync.push import TryAgain

    b = shared.b
    letter = b.add_letter("half gone")
    (b.paths.derived / letter / "thumb.jpg").unlink()
    b.db._conn().execute(
        "UPDATE pages SET image_path = ? WHERE doc_id = ?", (f"derived/{letter}/thumb.jpg", letter)
    )
    with pytest.raises(TryAgain):
        b.s.push(b.db)


def test_finding_11_durable_while_syncing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ordnung.config import Paths

    store = Store.open(Paths(tmp_path / "d").ensure(), durable=True)
    try:
        with store.tx() as conn:
            assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
        store.set_durable(False)
        with store.tx() as conn:
            assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL, at its next transaction
        store.set_durable(True)
        calls: list[int] = []
        monkeypatch.setattr(durable, "fsync", lambda fd: calls.append(fd))
        from ordnung.ingest import intake

        monkeypatch.setattr(intake, "fsync", lambda fd: calls.append(fd))
        intake._write_atomic(tmp_path / "d" / "files" / "x.bin", b"original")
        assert calls  # the file reached the disk before a row could name it
    finally:
        store.set_durable(False)
        store.close()


def test_finding_12_a_failed_database_step_can_be_given_up(
    shared: Shared, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ordnung.sync import pull as pull_module
    from ordnung.sync.pull import PullUnfinished, abandon, unfinished

    a, b = shared.a, shared.b
    b.person_edit("x")
    b.round()

    def full(self: Store, *_a: Any, **_k: Any) -> None:
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(pull_module.Store, "replace_with", full)
    with pytest.raises(PullUnfinished):
        a.use_here()
    monkeypatch.undo()
    use_fast_keys(monkeypatch)
    journal = unfinished(a.paths)
    assert journal is not None and journal.failed
    assert abandon(a.paths)
    assert unfinished(a.paths) is None and "x" not in a.notes()


def test_finding_14_no_version_for_nothing(shared: Shared) -> None:
    b = shared.b
    b.round()  # whatever was pending is saved
    seq = b.s.state.seq
    with person_write():
        b.db.set_meta("desktop_notified_on", "2026-10-07")
    assert b.round().pushed.outcome == "accounted"  # type: ignore[union-attr]
    assert b.s.state.seq == seq


def test_finding_15_the_last_hand_over_is_sent_on(shared: Shared) -> None:
    a, b = shared.a, shared.b
    a.use_here()
    state = CalendarSyncState(url="https://cal/", username="a", events={"e.ics": "h"})
    a.db.set_meta("calendar_sync", state.model_dump_json())
    a.round()
    b.round()
    b.use_here()  # b has no calendar connection of its own
    assert b.s.state.calendar_received is not None and b.s.state.calendar_received.events == {"e.ics": "h"}
    b.person_edit("x")
    pushed = b.round().pushed
    assert pushed is not None and pushed.version is not None
    manifest = b.s.scanner.manifest(pushed.version)
    assert (
        manifest is not None and manifest.calendar is not None and manifest.calendar.events == {"e.ics": "h"}
    )


def test_finding_16_a_shared_watched_folder(tmp_path: Path) -> None:
    from ordnung.ingest import watcher

    store = Store.open(__import__("ordnung.config").config.Paths(tmp_path / "d").ensure())
    try:
        data = b"%PDF a scan"
        watcher.remember_taken(store, data)
        assert not watcher._taken_elsewhere(store, data)  # sync off: no change in behaviour
        (tmp_path / "d" / "sync").mkdir()
        (tmp_path / "d" / "sync" / "state.json").write_text("{}")
        assert watcher._taken_elsewhere(store, data)
        assert hashlib.sha256(data).hexdigest() in json.loads(
            store.get_meta(watcher.FOLDER_TAKEN_META_KEY) or "[]"
        )
    finally:
        store.close()


def test_finding_17_the_key_file_is_expensive_to_guess() -> None:
    assert SYNC_KDF.log2_n == 18 and SYNC_KDF.r == 8 and KEY_FILE_BYTES == 92
    assert passphrase_problem("orbit velvet canyon maple thunder") is None
    assert passphrase_problem("a perfectly long sentence") is not None


def test_finding_18_a_lineage_that_claims_too_much_is_refused(shared: Shared) -> None:
    a, b = shared.a, shared.b
    b.person_edit("x")
    b.round()
    from test_sync_pull import forge

    greedy = lin.make({**b.s.state.base.ref.lineage.content, a.s.state.computer: [(1, 999)]})  # type: ignore[union-attr]
    forge(b, lineage=greedy)
    view = a.s.scan()
    head = view.by_computer(b.s.state.computer)
    assert (
        head is None or not head.readable or head.head.version is None or head.head.version.lineage != greedy
    )


def test_finding_20_gc_keeps_a_left_head_until_it_is_covered(shared: Shared) -> None:
    a, b = shared.a, shared.b
    b.person_edit("x")
    b.round()
    b.s.leave(b.db, unreceived_ok=True)
    a.use_here()  # a brings the left head's version in: covered now
    a.s.scan()
    referenced = a.s._referenced()
    assert referenced is not None
    left_version = a.s.view.by_computer(b.s.state.computer).head.version  # type: ignore[union-attr]
    assert left_version is not None
    assert left_version.manifest in referenced or lin.covers(a.s.state.base.ref.lineage, left_version.lineage)  # type: ignore[union-attr]


def _slices(computer: Computer, ref: Any) -> set[str]:
    manifest = computer.s.scanner.manifest(ref)
    assert manifest is not None
    return {computer.s.vault.object_name("d", piece.sha256) for piece in manifest.db.slices}


def _present(computer: Computer, names: set[str]) -> set[str]:
    return {name for name in names if computer.s.folder.object_info(name) is not None}


def _gc_after(computer: Computer, hours: float) -> int:
    for _ in range(int(hours // 12)):
        computer.clock.advance(12 * 3600)
        computer.s.tick()
    computer.s.scan()
    computer.s.state.last_gc_at = None
    return computer.s.gc()


def test_finding_21_superseded_database_slices_go_after_a_day_once_every_live_head_is_newer(
    shared: Shared,
) -> None:
    """Measured (P1, a generated 1,500-letter library, 80 MiB database): one reading rewrites 29 of the
    80 one-MiB slices (the search index merges), a note 1, a search-index optimize 44 — well above
    :data:`SLICE_CHURN_LIMIT_BYTES`. So the slices of a version every live head has moved past go after
    a day; the rest of the garbage keeps its 7 days."""
    assert SLICE_CHURN_LIMIT_BYTES == 5 * 2**20
    a, b = shared.a, shared.b
    user, other = (b, a) if b.s.state.mode == "in_use" else (a, b)
    assert user.s.state.mode == "in_use"
    user.person_edit("second")
    user.round()
    other.round()  # the other computer holds this version now
    user.person_edit("third")
    user.round()
    third = user.s.state.base.ref  # type: ignore[union-attr]
    user.person_edit("fourth")
    user.round()
    fourth = user.s.state.base.ref  # type: ignore[union-attr]
    superseded = _slices(user, third) - _slices(user, fourth)
    assert superseded and _present(user, superseded) == superseded
    _gc_after(user, 0)  # first seen unreferenced
    _gc_after(user, 36)
    assert _present(user, superseded) == superseded  # the other computer still holds an older version
    other.round()  # it brings the fourth in
    assert _gc_after(user, 0) >= len(superseded)
    assert not _present(user, superseded)
    assert user.s.folder.object_info(third.manifest) is not None  # not a slice: the 7 days still hold
    assert user.s.scanner.completeness(fourth, {}).ready


def test_finding_25_local_privacy_log_rows_stay_here(shared: Shared) -> None:
    a, b = shared.a, shared.b
    b.db.log_activity("phone.paired", "Paired a phone on the desktop")
    b.person_edit("x")
    b.round()
    a.db.log_activity("backup.created", "A backup on the laptop")
    a.use_here()
    kinds = [row.kind for row in a.db.list_activity(None)]
    assert "phone.paired" not in kinds and "backup.created" in kinds


def test_finding_26_two_writers_write_the_same_bytes(shared: Shared) -> None:
    a, b = shared.a, shared.b
    content = b"a bucket two computers write"
    name = a.s.vault.object_name("b", hashlib.sha256(content).hexdigest())
    assert a.s.vault.seal("b", name, content) == b.s.vault.seal("b", name, content)


def test_finding_30_the_machine_id_fallback_is_stored_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ordnung.sync import local

    monkeypatch.setattr(local, "_read_machine_id", lambda: None)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr("platformdirs.user_config_dir", lambda name: str(tmp_path / "config" / name))
    first = local.machine_id()
    assert first == local.machine_id() and len(first) == 32


def test_finding_34_an_interrupted_setup_is_recognised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ordnung.sync import engine as engine_module

    a = Computer("a", tmp_path / "a", tmp_path / "sync")
    try:
        real_push = engine_module.Session.push
        monkeypatch.setattr(
            engine_module.Session, "push", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cut"))
        )
        with pytest.raises(RuntimeError):
            a.connect()
        state = json.loads((a.paths.data_dir / "sync" / "state.json").read_text())
        assert state["complete"] is False and len(bytes.fromhex(state["key_file_bytes"])) == KEY_FILE_BYTES
        monkeypatch.setattr(engine_module.Session, "push", real_push)
        assert a.connect("lantern pebble violin harbor quiet").connected
    finally:
        a.close()


def test_r5_brings_in_quietly_and_r4_asks(shared: Shared) -> None:
    a, b = shared.a, shared.b
    a.use_here()
    b.round()
    b.s.state.mode = "in_use"  # b, in use too (it hadn't seen a's claim) — then a late change
    b.person_edit("late")
    b.s.push(b.db, head_state="standing_by")
    assert isinstance(a.round().decision, BringIn)
    a.person_edit("a's own")
    a.round()
    b.s.state.mode = "in_use"
    b.person_edit("later still")
    b.s.push(b.db, head_state="standing_by")
    assert isinstance(a.round().decision, Choice)


def test_lineage_empty_is_behind_everything() -> None:
    assert lin.relation(Lineage(), lin.make({"a" * 32: [(1, 1)]})) == "ahead"
