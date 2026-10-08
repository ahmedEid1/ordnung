"""The data-folder lock with Windows' byte locks, run on Linux: ``locking.py`` imported as on Windows, with
a stand-in for ``msvcrt``.

``msvcrt.locking`` locks a byte range per handle, and the lock is mandatory: another handle's read or write
of a locked byte fails. Linux open-file-description locks (``F_OFD_SETLK``) are per handle too, so a fake
``msvcrt`` on top of them, and an ``os`` whose ``read``/``write`` refuse a range another handle locked,
behave the same. The lock stays on byte 0, the byte 0.2.0 locks, so either version keeps the other out; the
holder note starts at byte 1, so it can be read while the lock is held.

Windows itself runs the real code in the "Other systems" CI job (``tests/test_cli.py``'s lock tests and
``tests/test_backup.py``); there, and on macOS, the emulated tests here skip.
"""

from __future__ import annotations

import errno
import importlib.util
import os
import struct
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from ordnung import locking

fcntl: Any = pytest.importorskip("fcntl")

LK_UNLCK, LK_NBLCK = 0, 2


def _flock(kind: int, start: int, length: int) -> bytes:
    return struct.pack("hhqqi", kind, os.SEEK_SET, start, length, 0) + b"\0" * 4


def _locked_by_another_handle(fd: int, start: int, length: int) -> bool:
    found = fcntl.fcntl(fd, fcntl.F_OFD_GETLK, _flock(fcntl.F_WRLCK, start, max(length, 1)))
    return struct.unpack("hhqqi", found[:28])[0] != fcntl.F_UNLCK


def _locking(fd: int, mode: int, nbytes: int) -> None:
    """``msvcrt.locking``: ``nbytes`` from the current position, refused with EACCES when taken."""
    start = os.lseek(fd, 0, os.SEEK_CUR)
    kind = fcntl.F_UNLCK if mode == LK_UNLCK else fcntl.F_WRLCK
    try:
        fcntl.fcntl(fd, fcntl.F_OFD_SETLK, _flock(kind, start, nbytes))
    except OSError as exc:
        raise PermissionError(errno.EACCES, "Permission denied") from exc


FAKE_MSVCRT = types.SimpleNamespace(LK_UNLCK=LK_UNLCK, LK_NBLCK=LK_NBLCK, locking=_locking)


class MandatoryOs(types.ModuleType):
    """``os`` as the module under test sees it: ``read``/``write`` fail on a range another handle locked."""

    def __init__(self) -> None:
        super().__init__("os")

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)

    @staticmethod
    def read(fd: int, n: int) -> bytes:
        if _locked_by_another_handle(fd, os.lseek(fd, 0, os.SEEK_CUR), n):
            raise PermissionError(errno.EACCES, "Permission denied")
        return os.read(fd, n)

    @staticmethod
    def write(fd: int, data: bytes) -> int:
        if _locked_by_another_handle(fd, os.lseek(fd, 0, os.SEEK_CUR), len(data)):
            raise PermissionError(errno.EACCES, "Permission denied")
        return os.write(fd, data)


@pytest.fixture
def windows_locking(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``locking.py`` imported as on Windows: the ``msvcrt`` branch, the fake ``msvcrt``, mandatory locks."""
    if not hasattr(fcntl, "F_OFD_SETLK"):
        pytest.skip("needs Linux open-file-description locks")
    spec = importlib.util.spec_from_file_location("locking_as_on_windows", locking.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as windows:
        windows.setitem(sys.modules, "msvcrt", FAKE_MSVCRT)
        windows.setattr(sys, "platform", "win32")
        spec.loader.exec_module(module)
    module.os = MandatoryOs()
    return module


class OldLock:
    """A lock as 0.2.0 takes it on Windows: byte 0, with the note ``pid N: purpose`` written from byte 0."""

    def __init__(self, data_dir: Path, purpose: str) -> None:
        self.fd = os.open(data_dir / locking.LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
        self.purpose = purpose

    def acquire(self) -> bool:
        os.lseek(self.fd, 0, os.SEEK_SET)
        try:
            _locking(self.fd, LK_NBLCK, 1)
        except OSError:
            return False
        os.ftruncate(self.fd, 0)
        MandatoryOs.write(self.fd, f"pid {os.getpid()}: {self.purpose}".encode())
        return True

    def read_holder(self) -> str | None:
        try:
            os.lseek(self.fd, 0, os.SEEK_SET)
            return MandatoryOs.read(self.fd, 512).decode("utf-8", "replace").strip() or None
        except OSError:
            return None

    def close(self) -> None:
        os.close(self.fd)


def test_the_holder_is_named_while_the_lock_is_held(windows_locking: Any, tmp_path: Path) -> None:
    """Byte 0 is locked for every other handle: the note after it names who to stop."""
    lk = windows_locking
    with lk.DataDirLock(tmp_path, purpose="ordnung serve"):
        with pytest.raises(lk.DataDirLocked) as refused:
            lk.DataDirLock(tmp_path).acquire()
    assert refused.value.holder == f"pid {os.getpid()}: ordnung serve"
    assert f"(pid {os.getpid()}: ordnung serve)" in str(refused.value)
    with lk.DataDirLock(tmp_path) as again:
        assert again.locked


def test_a_held_lock_keeps_a_second_writer_out(windows_locking: Any, tmp_path: Path) -> None:
    lk = windows_locking
    first = lk.DataDirLock(tmp_path).acquire()
    try:
        with pytest.raises(lk.DataDirLocked):
            lk.DataDirLock(tmp_path, timeout=0.2).acquire()
    finally:
        first.release()
    with lk.DataDirLock(tmp_path) as second:
        assert second.locked


def test_a_lock_taken_by_0_2_0_keeps_this_version_out(windows_locking: Any, tmp_path: Path) -> None:
    """While computers update one at a time, an old ``serve`` and a new command never both write. The old
    note starts at the locked byte, so the rest of it is no holder: none is named."""
    lk = windows_locking
    old = OldLock(tmp_path, "ordnung serve")
    try:
        assert old.acquire()
        with pytest.raises(lk.DataDirLocked) as refused:
            lk.DataDirLock(tmp_path).acquire()
        assert refused.value.holder is None
    finally:
        old.close()
    with lk.DataDirLock(tmp_path) as mine:
        assert mine.locked


def test_this_version_s_lock_keeps_0_2_0_out(windows_locking: Any, tmp_path: Path) -> None:
    lk = windows_locking
    old = OldLock(tmp_path, "ordnung add")
    try:
        with lk.DataDirLock(tmp_path, purpose="ordnung serve"):
            assert not old.acquire()
            assert old.read_holder() is None  # 0.2.0 reads from the locked byte: it names no one, as before
        assert old.acquire()
    finally:
        old.close()


def test_a_note_0_2_0_wrote_still_names_its_holder_where_locks_are_advisory(tmp_path: Path) -> None:
    """``flock`` locks don't stop reads, so on Linux and macOS a note written from byte 0 reads as before."""
    fd = os.open(tmp_path / locking.LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(fd, b"pid 4242: ordnung serve")
        with pytest.raises(locking.DataDirLocked) as refused:
            locking.DataDirLock(tmp_path).acquire()
        assert refused.value.holder == "pid 4242: ordnung serve"
    finally:
        os.close(fd)
