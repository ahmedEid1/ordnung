"""Pushing (design §10; review findings 7, 10, 11c, 14, 19, 20, 21; F1-F2, F17)."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest

from fakes import use_fast_keys
from ordnung.db.store import PERSON_META_KEY, person_write
from ordnung.sync import OBJECT_RE, SYNC_MARK_KEY, SyncRefused
from ordnung.sync.push import LocalDamaged, TryAgain, bucket_key
from sync_faults import CountingFs
from sync_harness import Computer


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)


@pytest.fixture
def anna(tmp_path: Path):  # type: ignore[no-untyped-def]
    computer = Computer("anna-laptop", tmp_path / "a", tmp_path / "sync", folder_fs=CountingFs())
    yield computer
    computer.close()


def objects(folder: Path) -> dict[str, int]:
    found: dict[str, int] = {}
    root = folder / "o"
    if root.is_dir():
        for shard in root.iterdir():
            for item in shard.iterdir():
                if OBJECT_RE.match(item.name):
                    found[shard.name + item.name] = item.stat().st_size
    return found


def test_the_first_push_writes_everything_and_names_it_in_the_head(anna: Computer) -> None:
    anna.add_letter("Stadtwerke")
    result = anna.connect()
    assert result.outcome is not None and result.outcome.pushed is not None
    pushed = result.outcome.pushed
    assert pushed.outcome == "pushed" and pushed.person
    assert pushed.kinds_written.get("f", 0) == 3  # the original, the page image, the thumbnail
    assert pushed.kinds_written.get("d", 0) >= 1 and pushed.kinds_written.get("m") == 1
    assert anna.db.get_meta(SYNC_MARK_KEY) == pushed.version.id.key()  # type: ignore[union-attr]
    heads = list((anna.folder / "h").iterdir())
    assert len(heads) == 1


def test_incremental_bytes(anna: Computer) -> None:  # §10.3
    anna.add_letter("first")
    anna.connect()
    counting = anna.folder_fs
    assert isinstance(counting, CountingFs)
    # no change: nothing at all
    counting.reset()
    outcome = anna.round()
    assert counting.total() == 0, outcome
    # marking a date done (a database change): slices, the manifest, the head — no file, no bucket
    counting.reset()
    anna.person_edit("a note")
    outcome = anna.round()
    assert outcome.pushed is not None and outcome.pushed.outcome == "pushed"
    assert set(outcome.pushed.kinds_written) <= {"d", "m"}, outcome.pushed.kinds_written
    assert outcome.pushed.kinds_written.get("d", 0) <= 5
    # adding a letter: its three files, at most two buckets, slices, the manifest
    anna.add_letter("second")
    outcome = anna.round()
    assert outcome.pushed is not None
    kinds = outcome.pushed.kinds_written
    assert kinds.get("f") == 3 and kinds.get("b", 0) <= 2 and kinds.get("m") == 1, kinds


def test_background_work_pushes_without_a_person_number(anna: Computer) -> None:
    anna.add_letter("first")
    anna.connect()
    before = anna.s.state.pnum
    anna.background_edit()
    outcome = anna.round()
    assert outcome.pushed is not None and outcome.pushed.outcome == "pushed" and not outcome.pushed.person
    assert anna.s.state.pnum == before


def test_a_person_write_that_changes_nothing_synced_makes_no_version(anna: Computer) -> None:  # finding 14
    anna.connect()
    seq = anna.s.state.seq
    with person_write():
        anna.db.set_meta("inbox_seen", '["x"]')  # a local key: nothing synced changed
    outcome = anna.round()
    assert outcome.pushed is not None and outcome.pushed.outcome == "accounted"
    assert anna.s.state.seq == seq and not anna.s.pending(anna.db)


def test_the_demo_never_pushes(anna: Computer) -> None:  # finding 19, F38
    anna.connect()
    anna.db.save_settings(anna.db.get_settings().model_copy(update={"demo": True}))
    with pytest.raises(SyncRefused):
        anna.s.push(anna.db)
    with pytest.raises(SyncRefused):
        anna.s.push(anna.db, demo=True)


def test_a_file_the_snapshot_names_must_be_there(anna: Computer) -> None:  # finding 10
    anna.connect()
    doc = anna.add_letter("gone")
    (anna.paths.derived / doc / "page-1.jpg").unlink()
    with pytest.raises(TryAgain):
        anna.s.push(anna.db)


def test_a_damaged_original_is_never_sealed(anna: Computer) -> None:  # finding 11c
    anna.connect()
    anna.add_letter("rotting")
    original = next(p for p in anna.paths.files.rglob("*.pdf"))
    original.write_bytes(original.read_bytes()[:-1] + b"!")
    with pytest.raises(LocalDamaged):
        anna.s.push(anna.db)


def test_a_file_changed_while_sealed_writes_no_head(anna: Computer, monkeypatch: pytest.MonkeyPatch) -> None:
    anna.connect()
    doc = anna.add_letter("re-rendered")
    page = anna.paths.derived / doc / "page-1.jpg"
    written_before = anna.s.state.written
    from ordnung.sync import push as push_module

    real = push_module.chunks_of

    def changing(path: Path):  # type: ignore[no-untyped-def]
        if path == page:
            page.write_bytes(b"\xff\xd8" + os.urandom(3000))
        yield from real(path)

    monkeypatch.setattr(push_module, "chunks_of", changing)
    with pytest.raises(TryAgain):
        anna.s.push(anna.db)
    assert anna.s.state.written == written_before


def test_the_fence_stands_by_when_a_higher_claim_appeared(tmp_path: Path) -> None:
    a = Computer("a", tmp_path / "a", tmp_path / "sync")
    b = Computer("b", tmp_path / "b", tmp_path / "sync")  # the same folder: delivery is instant
    try:
        a.add_letter("x")
        a.connect()
        b.connect()
        assert b.mode == "in_use"
        a.person_edit("a writes on")
        pushed = a.s.push(a.db)
        assert pushed.head_state == "standing_by" and a.mode == "standing_by"
    finally:
        a.close()
        b.close()


def test_missing_objects_are_written_again(anna: Computer) -> None:  # F17, finding 7
    anna.add_letter("first")
    anna.connect()
    victims = sorted(objects(anna.folder))[:3]
    for name in victims:
        (anna.folder / "o" / name[:2] / name[2:]).unlink()
    healed = anna.s.self_heal(anna.db)
    assert healed >= 1
    assert anna.s.scanner.completeness(anna.s.state.base.ref, {}).ready  # type: ignore[union-attr]


def test_the_own_head_is_rewritten_when_it_goes_back(anna: Computer) -> None:  # F15, finding 7
    anna.connect()
    head = next((anna.folder / "h").iterdir())
    old = head.read_bytes()
    anna.person_edit("newer")
    anna.round()
    head.write_bytes(old)  # the sync tool put an older copy back
    anna.s.scan()
    assert head.read_bytes() != old
    view = anna.s.scan()
    assert not view.own_stale


def test_gc_waits_seven_days_of_wall_clock_and_running_time(anna: Computer) -> None:  # finding 20
    anna.add_letter("doomed")
    anna.connect()
    doc = next(iter(anna.letters()))
    anna.delete_letter(doc)
    anna.round()
    before = objects(anna.folder)
    assert anna.s.gc() == 0  # first seen unreferenced now
    anna.clock.jump_wall(timedelta(days=30))  # the wall clock jumps: not enough
    anna.s.state.last_gc_at = None
    assert anna.s.gc() == 0
    for _ in range(8):
        anna.clock.advance(86_400)
        anna.s.tick()
    anna.s.state.last_gc_at = None
    removed = anna.s.gc()
    assert removed >= 3
    after = objects(anna.folder)
    assert set(after) < set(before)
    assert anna.s.scanner.completeness(anna.s.state.base.ref, {}).ready  # type: ignore[union-attr]


def test_buckets_follow_the_data_folders_layout() -> None:
    assert bucket_key("files/ab/" + "a" * 64 + ".pdf") == "files/ab"
    assert bucket_key("derived/doc_1/page-1.jpg").startswith("derived/") and len(bucket_key("derived/x/y")) == 10
    assert bucket_key("drafts/x.pdf") == "drafts"


def test_the_counter_is_read_from_the_snapshot(anna: Computer) -> None:  # finding 5a
    anna.connect()
    with person_write():
        anna.db.add_note("one")
    counted = int(anna.db.get_meta(PERSON_META_KEY) or 0)
    anna.round()
    assert anna.s.state.pushed == counted
