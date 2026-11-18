"""Hand-off sync: regression tests (each fails without its fix) for the calendar preview, and for the
sync folder's links and suggested name with two data folders (:mod:`sync_harness`)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from fakes import use_fast_keys
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.sync import SyncError


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)
    monkeypatch.setattr(os, "fsync", lambda fd: None)  # no test here is about durability: skip the disk flush


def test_the_calendar_preview_only_reads(tmp_path: Path) -> None:
    """The rule: a standing-by computer's digest never changes — the preview of the calendar
    events used to make the synced ``calendar_uid_key`` (pending changes, a false second confirmation)."""
    from helpers_secretary import TODAY, seed_ledger
    from ordnung import clock
    from ordnung.calendar import caldav

    clock.set_today(TODAY)
    try:
        with Store.open(Paths(tmp_path / "data").ensure()) as store:
            seed_ledger(store)
            writes = store._conn().total_changes
            shown = caldav.preview(store, "discreet")
            assert shown and all(event.uid.endswith("@ordnung.local") for event in shown)
            assert store.get_meta(caldav.UID_KEY_META) is None
            assert store._conn().total_changes == writes, "the preview wrote nothing"
            sent = caldav.build_events(store, "discreet")  # the first sync makes the key that stays
            assert store.get_meta(caldav.UID_KEY_META) and [e.preview.summary for e in sent] == [
                event.summary for event in shown
            ]
    finally:
        clock.set_today(None)


# --------------------------------------------------------------------------------------------------
# the sync folder's layout: a folder that is a link is never gone through
# --------------------------------------------------------------------------------------------------


def _outside(tmp_path: Path) -> Path:
    outside = tmp_path / "home-anna-Documents"
    outside.mkdir()
    (outside / "tax-2025.pdf").write_bytes(b"%PDF the person's own file")
    return outside


def test_objects_are_never_written_through_a_linked_o(tmp_path: Path) -> None:
    """Links are ignored (:mod:`ordnung.sync.folder`, ADR 0018), folders too: someone who can write the sync folder
    turns ``o/`` into a link to the person's Documents — the next save writes nothing there."""
    import shutil

    from sync_harness import computers

    outside = _outside(tmp_path)
    with computers(tmp_path, "anna") as (a,):
        a.connect()
        a.add_letter("first")
        a.round()
        shutil.move(str(a.folder / "o"), tmp_path / "o-moved")
        os.symlink(outside, a.folder / "o")
        a.add_letter("second")
        with pytest.raises(SyncError):
            a.s.push(a.db)
        assert sorted(path.name for path in outside.rglob("*")) == ["tax-2025.pdf"]


def test_a_head_is_never_written_through_a_linked_h(tmp_path: Path) -> None:
    import shutil

    from sync_harness import computers

    outside = _outside(tmp_path)
    with computers(tmp_path, "anna") as (a,):
        a.connect()
        a.round()
        heads = tmp_path / "heads-moved"
        shutil.move(str(a.folder / "h"), heads)
        os.symlink(outside, a.folder / "h")
        a.person_edit("a new note")
        with pytest.raises(SyncError):
            a.s.push(a.db)
        assert sorted(path.name for path in outside.iterdir()) == ["tax-2025.pdf"]


def test_gc_never_deletes_through_a_linked_shard(tmp_path: Path) -> None:
    """A shard ``o/<xx>`` turned into a link to another vault's shard: nine days of GC delete nothing
    there (they used to delete that vault's objects)."""
    import shutil

    from sync_harness import computers

    with computers(tmp_path, "anna", "other") as (a, other):
        other.connect()
        other.add_letter("kept elsewhere")
        other.round()
        victim = sorted(path for path in (other.folder / "o").iterdir() if path.is_dir())[0]
        before = sorted(path.name for path in victim.iterdir())
        a.connect()
        a.add_letter("first")
        a.round()
        link = a.folder / "o" / victim.name
        if link.exists():
            shutil.rmtree(link)
        os.symlink(victim, link)
        for _ in range(9):
            a.clock.advance(86_400.0)
            a.s.scan()
            a.s.gc()
            a.s.folder.remove_temps()
        assert sorted(path.name for path in victim.iterdir()) == before


def test_the_suggested_sync_folder_name_doesn_t_say_which_app_wrote_it(tmp_path: Path) -> None:
    """The provider sees the folder's name: Ordnung's suggestions are neutral ("Vault"), never "Ordnung"."""
    from ordnung.sync.folder import folder_problem

    paths = Paths(tmp_path / "data").ensure()
    relative = folder_problem("Nextcloud/x", paths)
    assert relative is not None and relative.endswith("/home/you/Nextcloud/Vault.")
    taken = tmp_path / "Nextcloud" / "Shared"
    taken.mkdir(parents=True)
    (taken / "notes.txt").write_text("the person's own file")
    crowded = folder_problem(str(taken), paths)
    assert crowded is not None and crowded.endswith(f"like {taken.parent / 'Vault'}.")
    root = Path(__file__).resolve().parents[1]
    for shown in (
        "src/ordnung/sync/folder.py",
        "web/src/features/settings/SyncSetupCard.tsx",
        "web/src/features/settings/sync.ts",
        "README.md",
        "docs/guide.md",
    ):
        text = (root / shown).read_text(encoding="utf-8")
        assert "Nextcloud/Ordnung" not in text and "/ 'Ordnung'" not in text, shown
