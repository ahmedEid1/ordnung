"""Kept copies (:mod:`ordnung.sync.kept`, Rule K): a staged version kept as a copy, deleting one, and the
record next to them — two data folders and a simulated sync tool (:mod:`sync_harness`, :mod:`sync_sim`)."""

from __future__ import annotations

import errno
import os
import random
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from fakes import use_fast_keys
from ordnung import durable
from ordnung.backup import restore_backup
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.sync import SyncError
from ordnung.sync import kept as kept_module
from ordnung.sync.kept import (
    KEPT_INDEX,
    delete_kept,
    keep_staged,
    kept_path,
    kept_total,
    kept_warning,
    read_index,
    write_index,
)
from ordnung.sync.model import KeptInfo
from ordnung.sync.pull import Staged
from sync_harness import PASSPHRASE, Computer
from sync_sim import SyncToolSim


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)


class Pair:
    """A set up with a letter, B joined and changed a note; it has arrived at A, which stands by."""

    def __init__(self, tmp: Path) -> None:
        self.a = Computer("anna-laptop", tmp / "a", tmp / "a-sync")
        self.b = Computer("desktop", tmp / "b", tmp / "b-sync")
        self.sim = SyncToolSim(self.a.folder, self.b.folder, random.Random(1))
        a, b = self.a, self.b
        a.add_letter("Stadtwerke Abschlag 2027")
        a.connect()
        self.sim.settle()
        assert b.connect().connected
        self.sim.settle()
        a.round()
        b.person_edit("only on the desktop")
        b.round()
        self.sim.settle()
        assert a.mode == "standing_by" and b.mode == "in_use"

    def stage_b(self) -> Staged:
        """B's version, staged on A."""
        head = self.a.s.scan().by_computer(self.b.s.state.computer)
        assert head is not None and head.complete
        return self.a.s.stage(head)

    def close(self) -> None:
        self.a.close()
        self.b.close()


@pytest.fixture
def pair(tmp_path: Path) -> Iterator[Pair]:
    made = Pair(tmp_path)
    yield made
    made.close()


def _notes_in(copy: Path, target: Path) -> set[str]:
    restore_backup(copy, PASSPHRASE, target)
    with Store.open(Paths(target)) as store:
        return {row["text"] for row in store._conn().execute("SELECT text FROM notes")}


def _leftovers(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.glob(".*.part"))


# --------------------------------------------------------------------------------------------------
# keeping a staged version
# --------------------------------------------------------------------------------------------------


def test_a_staged_version_is_kept_as_a_copy_that_opens_with_the_passphrase(
    pair: Pair, tmp_path: Path
) -> None:
    a = pair.a
    staged = pair.stage_b()
    try:
        info = keep_staged(a.s, staged, "desktop's changes, before it was removed")
    finally:
        shutil.rmtree(a.s.local.incoming, ignore_errors=True)
    folder = a.s.local.kept_dir
    copy = folder / info.name
    assert copy.is_file() and _leftovers(folder) == []
    if os.name == "posix":
        assert copy.stat().st_mode & 0o777 == 0o600
    assert info.why == "desktop's changes, before it was removed" and info.digest == staged.target.digest
    assert info in a.s.state.kept and read_index(folder)[info.name] == info
    assert "only on the desktop" in _notes_in(copy, tmp_path / "opened")
    assert "only on the desktop" not in a.notes(), "keeping a copy changes nothing here"


def test_a_kept_copy_that_can_t_be_written_leaves_no_part_file(
    pair: Pair, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = pair.a
    staged = pair.stage_b()
    folder = a.s.local.kept_dir
    before = (list(a.s.state.kept), read_index(folder), sorted(os.listdir(folder)) if folder.is_dir() else [])

    def full_disk(*_args: object) -> Iterator[bytes]:
        yield b"half a kept copy"
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(kept_module.BackupStream, "from_parts", full_disk)
    try:
        with pytest.raises(SyncError) as refused:
            keep_staged(a.s, staged, "desktop's changes, before it was removed")
    finally:
        shutil.rmtree(a.s.local.incoming, ignore_errors=True)
    assert refused.value.kind == "no_space"  # the forget route's refusal, not a server error
    assert _leftovers(folder) == []
    assert (list(a.s.state.kept), read_index(folder), sorted(os.listdir(folder))) == before


# --------------------------------------------------------------------------------------------------
# deleting one, and how much they take
# --------------------------------------------------------------------------------------------------


def test_deleting_a_kept_copy_takes_it_off_both_records(pair: Pair, monkeypatch: pytest.MonkeyPatch) -> None:
    a = pair.a
    first = a.s.keep_local("before you kept desktop's Ordnung")
    staged = pair.stage_b()
    try:
        second = keep_staged(a.s, staged, "desktop's changes, before it was removed")
    finally:
        shutil.rmtree(a.s.local.incoming, ignore_errors=True)
    folder = a.s.local.kept_dir
    sizes = [(folder / info.name).stat().st_size for info in (first, second)]
    assert kept_total(a.s) == sum(sizes)
    assert not kept_warning(a.s)
    monkeypatch.setattr(kept_module, "KEPT_WARN_BYTES", sum(sizes) - 1)
    assert kept_warning(a.s)
    assert kept_path(a.s, first.name) == folder / first.name

    synced: list[Path] = []
    real_fsync_dir = a.s.data_fs.fsync_dir
    monkeypatch.setattr(a.s.data_fs, "fsync_dir", lambda path: (synced.append(path), real_fsync_dir(path)))
    assert delete_kept(a.s, first.name)
    assert not (folder / first.name).exists() and folder in synced
    assert [info.name for info in a.s.state.kept] == [second.name]
    assert list(read_index(folder)) == [second.name]
    assert kept_total(a.s) == sizes[1]

    assert not delete_kept(a.s, first.name)  # gone already
    for name in (KEPT_INDEX, "../sync/state.json", f"../kept/{second.name}", "state.json"):
        assert kept_path(a.s, name) is None and not delete_kept(a.s, name), name
    assert (folder / second.name).is_file() and (folder / KEPT_INDEX).is_file()


# --------------------------------------------------------------------------------------------------
# the record next to them
# --------------------------------------------------------------------------------------------------


def _info(name: str = "ordnung-kept-2026-10-07-0912.ordnung-backup") -> KeptInfo:
    return KeptInfo(
        name=name, why="before you kept desktop's Ordnung", created_at="2026-10-07T09:12:00+02:00"
    )


def test_the_kept_record_reaches_the_disk_with_its_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit: the record was written with a plain ``os.fsync`` (not ``F_FULLFSYNC`` on macOS) and its
    folder was never synced, so the rename could be lost in a power cut."""
    folder = tmp_path / "kept"
    files: list[int] = []
    folders: list[Path] = []
    real_fsync, real_fsync_dir = durable.fsync, durable.fsync_dir
    monkeypatch.setattr(durable, "fsync", lambda fd: (files.append(fd), real_fsync(fd)))
    monkeypatch.setattr(durable, "fsync_dir", lambda path: (folders.append(path), real_fsync_dir(path)))
    write_index(folder, [_info()])
    assert files and folder in folders
    assert list(read_index(folder)) == [_info().name] and _leftovers(folder) == []


def test_a_kept_record_that_can_t_be_renamed_leaves_no_part_file_and_the_old_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "kept"
    write_index(folder, [_info()])

    def blocked(self: Path, target: Path) -> Path:
        raise PermissionError(errno.EACCES, "held by the sync tool")

    monkeypatch.setattr(Path, "replace", blocked)
    write_index(folder, [_info("ordnung-kept-2026-10-08-0800.ordnung-backup")])  # best effort: no raise
    monkeypatch.undo()
    assert _leftovers(folder) == []
    assert list(read_index(folder)) == [_info().name]
