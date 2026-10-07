"""Hand-off sync, whole stories: two (or three) data folders, each with its own view of the sync folder,
and a simulated sync tool between them (design §23.1; F18-F23; review blockers 2-4, findings 15, 16, 31)."""

from __future__ import annotations

import json
import random
from datetime import timedelta
from pathlib import Path

import pytest

from fakes import use_fast_keys
from ordnung.backup import restore_backup
from ordnung.db.store import Store, person_write
from ordnung.models import CalendarSyncState
from ordnung.sync import SyncError
from ordnung.sync.decide import BecomeStandby, BringIn, Choice, Pull, Standby
from sync_harness import PASSPHRASE, Computer, FakeClock
from sync_sim import SyncToolSim


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)


class Pair:
    def __init__(self, tmp: Path, *, skew: timedelta = timedelta()) -> None:
        self.a = Computer("anna-laptop", tmp / "a", tmp / "a-sync")
        self.b = Computer("desktop", tmp / "b", tmp / "b-sync", clock=FakeClock(skew=skew))
        self.sim = SyncToolSim(self.a.folder, self.b.folder, random.Random(1))

    def settle(self) -> None:
        self.sim.settle()

    def close(self) -> None:
        self.a.close()
        self.b.close()

    def joined(self) -> None:
        """A set up with a letter; B joined (and is in use); A stands by."""
        a, b = self.a, self.b
        a.add_letter("Stadtwerke Abschlag 2027")
        a.connect()
        self.settle()
        assert b.connect().connected
        self.settle()
        a.round()
        assert a.mode == "standing_by" and b.mode == "in_use"


@pytest.fixture
def pair(tmp_path: Path):  # type: ignore[no-untyped-def]
    made = Pair(tmp_path)
    yield made
    made.close()


def test_setup_join_and_switch_back_and_forth(pair: Pair) -> None:
    a, b = pair.a, pair.b
    pair.joined()
    assert a.letters() == b.letters()
    for round_ in range(3):
        b.person_edit(f"desktop {round_}")
        b.round()
        pair.settle()
        a.round()
        assert isinstance(a.round().decision, Standby)
        assert a.use_here().replaced
        assert a.mode == "in_use" and f"desktop {round_}" in a.notes()
        pair.settle()
        b.round()
        assert b.mode == "standing_by"
        a.person_edit(f"laptop {round_}")
        a.round()
        pair.settle()
        b.round()
        assert b.use_here().replaced and f"laptop {round_}" in b.notes()
        pair.settle()
        a.round()
        assert a.mode == "standing_by"


def test_standing_by_acknowledges_what_arrived(pair: Pair) -> None:  # "Saved · desktop has it"
    a, b = pair.a, pair.b
    pair.joined()
    b.person_edit("hello")
    b.round()
    pair.settle()
    a.round()
    assert a.s.state.has == b.s.state.base.ref.id  # type: ignore[union-attr]
    pair.settle()
    view = b.s.scan()
    from ordnung.sync.decide import others_have

    assert others_have(view, b.s.state.base.ref)  # type: ignore[union-attr]


def test_joining_with_letters_on_both_sides_asks(pair: Pair) -> None:
    a, b = pair.a, pair.b
    a.add_letter("A's letter")
    a.connect()
    pair.settle()
    mine = b.add_letter("B's own letter")
    asked = b.connect()
    assert not asked.connected and asked.choice is not None and asked.choice.joining
    assert not (b.paths.data_dir / "sync" / "state.json").exists()
    result = b.connect(keep="folder")
    assert result.connected and result.outcome is not None and result.outcome.kept is not None
    assert mine not in b.letters() and len(b.letters()) == 1
    kept = b.s.local.kept_dir / result.outcome.kept.name
    restored = restore_backup(kept, PASSPHRASE, b.root / "restored")
    assert restored.contents.letters == 1
    with Store.open(type(b.paths)(b.root / "restored")) as copy:
        assert mine in {row["id"] for row in copy._conn().execute("SELECT id FROM documents")}


def test_joining_and_keeping_this_computers_letters(pair: Pair) -> None:
    a, b = pair.a, pair.b
    theirs = a.add_letter("A's letter")
    a.connect()
    pair.settle()
    mine = b.add_letter("B's own letter")
    result = b.connect(keep="this")
    assert result.connected and mine in b.letters() and b.mode == "in_use"
    pair.settle()
    a.round()
    assert a.mode == "standing_by"
    outcome = a.use_here()  # U4: a chose against A's data on B — kept first
    assert isinstance(outcome.decision, Pull) and outcome.decision.keep and outcome.kept is not None
    assert mine in a.letters() and theirs not in a.letters()


def test_both_changed_asks_once_and_either_answer_keeps_a_copy(pair: Pair) -> None:  # F18
    a, b = pair.a, pair.b
    pair.joined()
    a.use_here(older_copy=True)  # apart: A takes over with the copy it has
    a.person_edit("A's change")
    b.person_edit("B's change")
    a.round()
    b.round()
    pair.settle()
    ra, rb = a.round(), b.round()
    asked = [
        r
        for r in (ra, rb)
        if isinstance(r.decision, Choice) or (isinstance(r.decision, Standby) and r.decision.choice)
    ]
    assert asked, (ra, rb)
    holder = a if a.mode == "in_use" else b
    other = b if holder is a else a
    holder.choose(holder.key_of(holder))  # keep this one
    pair.settle()
    other.round()
    assert other.mode == "standing_by"
    outcome = other.use_here()
    assert outcome.kept is not None and isinstance(outcome.decision, Pull) and outcome.decision.keep
    assert other.notes() == holder.notes()
    pair.settle()
    for _ in range(2):  # blocker 3: nobody is asked again
        assert not isinstance(holder.round().decision, Choice)
        assert not isinstance(other.round().decision, Choice)
        pair.settle()


def test_choosing_the_other_computer(pair: Pair) -> None:
    a, b = pair.a, pair.b
    pair.joined()
    a.use_here(older_copy=True)
    a.person_edit("A's change")
    b.person_edit("B's change")
    a.round()
    b.round()
    pair.settle()
    a.round()
    outcome = a.choose(a.key_of(b))
    assert outcome.kept is not None and "B's change" in a.notes() and "A's change" not in a.notes()
    assert a.mode == "in_use"
    pair.settle()
    b.round()
    assert b.mode == "standing_by"
    assert not isinstance(b.use_here().decision, Choice)
    assert "B's change" in b.notes()


def test_lid_closed_mid_reading_is_no_question(pair: Pair) -> None:  # F19, F20
    a, b = pair.a, pair.b
    pair.joined()
    pair.settle()
    a.use_here()  # A takes over (B's claim arrives at B later)
    pair.settle()
    # B, asleep, wakes and finishes its background work before it sees A's claim
    b.background_edit("2026-10-08")
    pair.sim.poll()  # nothing delivered yet
    out = b.round()
    assert isinstance(out.decision, BecomeStandby) and not out.decision.late_push
    pair.settle()
    for _ in range(2):
        assert not isinstance(a.round().decision, Choice)
        pair.settle()


def test_a_late_change_is_brought_in_quietly(pair: Pair) -> None:  # F21, R5
    a, b = pair.a, pair.b
    pair.joined()
    # B is in use; A (standing by) takes over; B adds a scan before it notices
    pair.settle()
    a.use_here()
    b.person_edit("scanned on the desktop after the switch")
    pair.settle()
    out = b.round()
    assert isinstance(out.decision, BecomeStandby) and out.decision.late_push
    pair.settle()
    brought = a.round()
    assert isinstance(brought.decision, BringIn), brought
    assert "scanned on the desktop after the switch" in a.notes() and a.mode == "in_use"


def test_three_computers_and_forgetting_one(tmp_path: Path) -> None:
    a = Computer("a", tmp_path / "a", tmp_path / "sync")
    b = Computer("b", tmp_path / "b", tmp_path / "sync")
    c = Computer("c", tmp_path / "c", tmp_path / "sync")
    try:
        a.add_letter("one")
        a.connect()
        b.connect()
        c.connect()
        assert c.mode == "in_use"
        a.round()
        b.round()
        assert a.mode == b.mode == "standing_by"
        b.use_here()
        b.person_edit("only on b")
        b.round()
        c.round()
        with pytest.raises(SyncError) as refused:
            c.s.forget(c.key_of(b))
        assert refused.value.kind == "in_use"
        c.use_here()
        b.round()
        a.use_here()
        a.person_edit("a, then a forgets c")
        a.round()
        kept = a.s.forget(a.key_of(c))
        assert kept is None  # c's version holds nothing a doesn't have
        view = a.s.scan()
        assert view.by_computer(c.s.state.computer).forgotten  # type: ignore[union-attr]
        c.round()
        assert c.s.view is not None and c.s.view.problem is not None and c.s.view.problem.code == "forgotten"
    finally:
        for computer in (a, b, c):
            computer.close()


@pytest.mark.parametrize(
    "skew", [timedelta(days=-3), timedelta(minutes=-5), timedelta(), timedelta(minutes=5), timedelta(days=3)]
)
def test_clock_skew_changes_nothing(tmp_path: Path, skew: timedelta) -> None:  # F23
    pair = Pair(tmp_path, skew=skew)
    try:
        a, b = pair.a, pair.b
        pair.joined()
        b.person_edit("x")
        b.round()
        pair.settle()
        a.round()
        assert isinstance(a.use_here().decision, Pull)
        b.clock.jump_wall(timedelta(days=-10))  # and a jump backwards
        pair.settle()
        assert isinstance(b.round().decision, BecomeStandby)
        a.person_edit("y")
        a.round()
        pair.settle()
        assert isinstance(b.use_here().decision, Pull) and "y" in b.notes()
    finally:
        pair.close()


def test_windows_style_paths_travel(pair: Pair) -> None:
    a, b = pair.a, pair.b
    a.connect()
    pair.settle()
    b.connect()
    letter = b.add_letter("from windows")
    stored = b.db._conn().execute("SELECT file_path FROM documents WHERE id=?", (letter,)).fetchone()[0]
    b.db._conn().execute("UPDATE documents SET file_path=? WHERE id=?", (stored.replace("/", "\\"), letter))
    b.round()
    pair.settle()
    a.round()
    a.use_here()
    path = a.db._conn().execute("SELECT file_path FROM documents WHERE id=?", (letter,)).fetchone()[0]
    assert "\\" not in path and (a.paths.data_dir / path).is_file()


def test_delete_everything_on_the_computer_in_use_hands_its_last_version_on(pair: Pair) -> None:  # blocker 2
    a, b = pair.a, pair.b
    pair.joined()
    b.person_edit("made just before deleting everything")
    with pytest.raises(SyncError) as refused:
        b.s.leave(b.db)
    assert refused.value.kind == "not_received"  # the second confirmation
    b.s.leave(b.db, unreceived_ok=True)
    pair.settle()
    outcome = a.use_here()
    assert isinstance(outcome.decision, Pull) and "made just before deleting everything" in a.notes()


def test_a_data_folder_put_back_from_an_os_backup(pair: Pair, tmp_path: Path) -> None:  # blocker 4
    from sync_faults import copy_tree

    a, b = pair.a, pair.b
    pair.joined()
    pair.settle()
    a.use_here()
    a.person_edit("before the backup")
    a.round()
    a.close()
    copy_tree(a.paths.data_dir, tmp_path / "os-backup")
    a.restart()
    a.person_edit("after the backup: 1")
    a.round()
    a.person_edit("after the backup: 2")
    a.round()
    pushed_seq = a.s.state.seq
    a.close()
    copy_tree(tmp_path / "os-backup", a.paths.data_dir)
    problem = a.restart()
    assert problem is not None and problem.code == "local_rollback"
    assert a.s.state.seq >= pushed_seq  # finding 4: the counters were raised to what the folder shows
    outcome = a.s.repair_rollback(a.db)
    assert outcome.kept is not None
    assert {"after the backup: 1", "after the backup: 2"} <= a.notes()
    pair.settle()
    b.round()
    assert not isinstance(b.round().decision, Choice)


def test_the_calendar_record_travels_for_the_same_calendar(pair: Pair) -> None:  # finding 15
    a, b = pair.a, pair.b
    state = CalendarSyncState(
        url="https://cal.example/", username="anna", connection="aa", events={"x.ics": "1"}
    )
    a.db.set_meta("calendar_sync", state.model_dump_json())
    b.db.set_meta(
        "calendar_sync",
        state.model_copy(update={"connection": "bb", "events": {"y.ics": "2"}}).model_dump_json(),
    )
    pair.joined()
    merged = CalendarSyncState.model_validate_json(b.db.get_meta("calendar_sync") or "")
    assert merged.connection == "bb"  # the connection stays
    assert merged.events == {"x.ics": "", "y.ics": ""}  # both records, checked again
    view = a.s.scan()
    head = view.by_computer(b.s.state.computer)
    assert (
        head is not None and head.head.calendar_target is not None and head.head.calendar_mode == "discreet"
    )


def test_a_watched_folder_both_computers_share(pair: Pair) -> None:  # finding 16
    from ordnung.ingest import watcher

    a, b = pair.a, pair.b
    pair.joined()
    data = b"%PDF-1.7 a scanned letter"
    with person_write():
        watcher.remember_taken(b.db, data)
    b.person_edit("taken from the shared Scans folder")
    b.round()
    pair.settle()
    a.round()
    a.use_here()
    taken = json.loads(a.db.get_meta(watcher.FOLDER_TAKEN_META_KEY) or "[]")
    import hashlib

    assert hashlib.sha256(data).hexdigest() in taken
    assert watcher.was_taken(a.db, data)
