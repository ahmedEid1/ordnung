"""``durable.write_atomic``: Ordnung's one atomic file write (a temporary file in the same folder, then a
rename), with the file and its folder flushed to the disk when asked, and never a ``.part`` left behind."""

from __future__ import annotations

import errno
import os
import stat
import threading
from pathlib import Path

import pytest

from ordnung import durable


def _leftovers(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.glob(".*.part"))


def _partial(path: Path) -> Path:
    """Where the temporary file goes (one per process and thread)."""
    return path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.part")


def test_a_write_replaces_the_file_whole(tmp_path: Path) -> None:
    path = tmp_path / "server.json"
    durable.write_atomic(path, b"first")
    durable.write_atomic(path, b"second, longer than the first")
    assert path.read_bytes() == b"second, longer than the first"
    assert _leftovers(tmp_path) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_the_file_is_made_with_the_mode_asked_for(tmp_path: Path) -> None:
    durable.write_atomic(tmp_path / "private", b"x")
    durable.write_atomic(tmp_path / "read-only", b"x", mode=0o400)
    assert stat.S_IMODE((tmp_path / "private").stat().st_mode) == 0o600  # by default: the owner's only
    assert stat.S_IMODE((tmp_path / "read-only").stat().st_mode) == 0o400


def test_a_rename_that_fails_leaves_the_old_file_and_no_part_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "record.json"
    durable.write_atomic(path, b"old")

    def refused(self: Path, target: Path) -> Path:
        raise PermissionError(errno.EACCES, "held by another program")

    monkeypatch.setattr(Path, "replace", refused)
    with pytest.raises(PermissionError):
        durable.write_atomic(path, b"new")
    monkeypatch.undo()
    assert path.read_bytes() == b"old"
    assert _leftovers(tmp_path) == []


def test_a_flush_that_fails_leaves_the_old_file_and_no_part_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "record.json"
    durable.write_atomic(path, b"old")

    def full(fd: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(durable, "fsync", full)
    with pytest.raises(OSError, match="No space"):
        durable.write_atomic(path, b"new", sync=True)
    assert path.read_bytes() == b"old"
    assert _leftovers(tmp_path) == []


def test_the_file_and_then_its_folder_reach_the_disk_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    done: list[str] = []
    monkeypatch.setattr(durable, "fsync", lambda fd: done.append("file"))
    monkeypatch.setattr(durable, "fsync_dir", lambda folder: done.append(f"folder {folder.name}"))
    path = tmp_path / "files" / "letter.pdf"
    path.parent.mkdir()

    durable.write_atomic(path, b"%PDF", sync=True)
    assert done == ["file", "folder files"]

    done.clear()
    durable.write_atomic(path, b"%PDF", sync=False)
    assert done == []


def test_by_default_the_write_is_flushed_while_ordnung_insists_on_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    done: list[str] = []
    monkeypatch.setattr(durable, "fsync", lambda fd: done.append("file"))
    monkeypatch.setattr(durable, "fsync_dir", lambda folder: done.append("folder"))
    durable.write_atomic(tmp_path / "a", b"x")
    assert done == []
    durable.set_durable(True)
    try:
        durable.write_atomic(tmp_path / "b", b"x")
    finally:
        durable.set_durable(False)
    assert done == ["file", "folder"]


def test_a_part_file_a_crash_left_behind_is_written_over(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    _partial(path).write_bytes(b"half a file from a crash")
    durable.write_atomic(path, b"whole")
    assert path.read_bytes() == b"whole"
    assert _leftovers(tmp_path) == []


@pytest.mark.skipif(os.name == "nt", reason="symbolic links need extra rights on Windows")
def test_a_link_where_the_temporary_file_goes_is_never_written_through(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.write_bytes(b"someone else's file")
    folder = tmp_path / "data"
    folder.mkdir()
    path = folder / "server.json"
    _partial(path).symlink_to(outside)
    durable.write_atomic(path, b"ours")
    assert outside.read_bytes() == b"someone else's file"
    assert path.read_bytes() == b"ours" and not path.is_symlink()
    assert _leftovers(folder) == []
