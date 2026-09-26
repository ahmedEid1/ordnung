"""Exclusive data-directory lock for the CLI and the server (SPEC §15).

Only one process writes to a data directory at a time: ``ordnung serve`` holds :class:`DataDirLock`
for as long as it runs, and in-process CLI commands (``add``, ``brief``, ``ask``) take it for their
duration. When a server is running the CLI talks to its API instead (see ``server.json``).

The lock is an OS file lock on ``<data>/.ordnung.lock`` (``fcntl.flock`` on POSIX, ``msvcrt.locking``
on Windows): the operating system releases it when the holder exits, even after a crash, so a stale
lock can never block anyone. ``flock`` locks belong to the open file, so two locks taken inside one
process conflict too.
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

if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
    import msvcrt

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
        note = f"pid {os.getpid()}: {self.purpose}".encode()
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
        os.lseek(fd, 0, os.SEEK_SET)
        text = os.read(fd, 512).decode("utf-8", "replace").strip()
    except OSError:
        return None
    return text or None
