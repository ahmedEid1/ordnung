"""Exclusive data-directory lock for the CLI and the server (SPEC §15).

Only one process writes to a data directory at a time: ``ordnung serve`` holds :class:`DataDirLock`
for as long as it runs, and in-process CLI commands (``add``, ``brief``, ``ask``) take it for their
duration. When a server is running the CLI talks to its API instead (see ``server.json``).

The lock is an OS file lock on ``<data>/.ordnung.lock`` (``fcntl.flock`` on POSIX, ``msvcrt.locking``
on Windows): the operating system releases it when the holder exits, even after a crash, so a stale
lock can never block anyone. ``flock`` locks belong to the open file, so two locks taken inside one
process conflict too.

On Windows the lock is a byte lock on byte 0, and no other handle may read a locked byte, so the holder
note (``pid N: command``) starts at byte 1. Byte 0 is the byte 0.2.0 locks too, so either version keeps
the other out.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path
from types import TracebackType

LOCK_NAME = ".ordnung.lock"
_POLL_S = 0.1
_HOLDER_MAX = 512
#: where the holder note starts: after byte 0, the byte Windows locks
_NOTE_AT = 1

if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
    import msvcrt

    _READ_AT = _NOTE_AT  # byte 0 is locked for every other handle

    def _try_lock(fd: int) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    _READ_AT = 0  # advisory locks: a note an earlier version wrote from byte 0 reads too

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


class DataDirLocked(RuntimeError):
    """Another process (or another lock in this process) holds the data directory."""

    def __init__(self, data_dir: Path, holder: str | None) -> None:
        self.data_dir = data_dir
        self.holder = holder
        who = f" ({holder})" if holder else ""
        super().__init__(
            f"Another Ordnung process{who} is using {data_dir}. Wait for it to finish, stop it, or "
            "use the running app."
        )


class DataDirLock:
    """An exclusive, non-blocking lock on a data directory (use as a context manager).

    ``timeout`` waits up to that many seconds for the holder to finish before giving up with
    :class:`DataDirLocked`. The holder's pid and command are written into the lock file, so the
    error can name who holds it.
    """

    def __init__(self, data_dir: str | Path, *, timeout: float = 0.0, purpose: str = "") -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / LOCK_NAME
        self.timeout = timeout
        self.purpose = purpose or " ".join(Path(arg).name for arg in sys.argv[:2])
        self._fd: int | None = None

    @property
    def locked(self) -> bool:
        """Whether this object currently holds the lock."""
        return self._fd is not None

    def acquire(self) -> DataDirLock:
        """Take the lock (waiting up to ``timeout`` seconds) or raise :class:`DataDirLocked`."""
        if self._fd is not None:
            return self
        self.data_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + self.timeout
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                holder = _read_holder(fd)
                os.close(fd)
                raise DataDirLocked(self.data_dir, holder)
            time.sleep(_POLL_S)
        self._fd = fd
        self._write_holder(fd)
        return self

    def release(self) -> None:
        """Give the lock back (no-op if not held)."""
        fd, self._fd = self._fd, None
        if fd is None:
            return
        with contextlib.suppress(OSError):
            _unlock(fd)
        os.close(fd)

    def _write_holder(self, fd: int) -> None:
        # the line break fills byte 0, the locked byte on Windows; stripped, the note reads as before
        note = f"\npid {os.getpid()}: {self.purpose}".encode()[: _NOTE_AT + _HOLDER_MAX]
        with contextlib.suppress(OSError):
            os.ftruncate(fd, 0)
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, note)

    def __enter__(self) -> DataDirLock:
        return self.acquire()

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.release()


def _read_holder(fd: int) -> str | None:
    """The holder note (``pid N: command``) of a lock file, if it can be read."""
    try:
        os.lseek(fd, _READ_AT, os.SEEK_SET)
        text = os.read(fd, _HOLDER_MAX).decode("utf-8", "replace").strip()
    except OSError:
        return None
    # read from byte 1, 0.2.0's note (written from byte 0) is cut: no holder rather than a wrong one
    return text if text.startswith("pid ") else None
