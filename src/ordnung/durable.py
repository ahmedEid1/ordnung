"""Durable file writes: what "on disk" means, and whether Ordnung insists on it right now.

Ordnung's own files are written atomically (a temporary name, then a rename), which is enough to never
leave half a file — but not to survive a power cut: the bytes and the rename may still sit in the
operating system's cache. While hand-off sync is on (:mod:`ordnung.sync`), a letter's original that the
database already names must be on disk before a push can carry the database, so :func:`set_durable`
turns on :func:`fsync` of every such file and of its folder (:mod:`ordnung.ingest.intake`), and the
store commits with ``synchronous=FULL`` (:meth:`ordnung.db.store.Store.set_durable`).

Measured (hand-off sync P1, Linux, SQLite 3.45.1): 1,000 small commits take 0.51 s with
``synchronous=FULL`` against 0.02 s with ``NORMAL`` — half a millisecond per commit, which Ordnung (a
few writes per action) never notices.

On macOS ``fsync`` only hands the data to the drive, whose cache may still lose it: :func:`fsync` uses
``F_FULLFSYNC`` there (as SQLite's ``fullfsync`` pragma does). On Windows a folder can't be opened to be
synced (NTFS journals renames), so :func:`fsync_dir` does nothing.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from pathlib import Path

_DURABLE = threading.Event()


def set_durable(on: bool) -> None:
    """Insist (or not) that the files Ordnung writes reach the disk before it goes on (process-wide)."""
    if on:
        _DURABLE.set()
    else:
        _DURABLE.clear()


def is_durable() -> bool:
    """Whether :func:`set_durable` is on in this process."""
    return _DURABLE.is_set()


def fsync(fd: int) -> None:
    """Flush the open file ``fd`` to the disk itself (``F_FULLFSYNC`` on macOS)."""
    if sys.platform == "darwin":
        import fcntl  # where Python has F_FULLFSYNC (``os`` doesn't)

        full = getattr(fcntl, "F_FULLFSYNC", None)
        if full is not None:
            try:
                fcntl.fcntl(fd, full)
                return
            except OSError:  # not supported by this file system: an ordinary fsync is the best there is
                pass
    os.fsync(fd)


def fsync_dir(folder: Path) -> None:
    """Make the names in ``folder`` durable (a rename or a new file in it); nothing on Windows."""
    if os.name == "nt":
        return
    fd = os.open(folder, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        with contextlib.suppress(OSError):  # some file systems can't sync a folder; nothing more to do
            fsync(fd)
    finally:
        os.close(fd)
