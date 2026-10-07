"""Kept copies — Rule K (design §11.4, §12.4; review findings 18, 35).

Before anything of the person's would be replaced — the other computer's Ordnung was chosen, this
computer's data went back in time, a joining computer had letters of its own, or bringing a version in
would remove letters this computer has (finding 18) — the live data is written as an ordinary encrypted
backup (format v1, :func:`ordnung.backup.write_backup_file`), encrypted with the **sync passphrase** read
from the password store at that moment: ``.part``, ``fsync``, rename, ``0600``, the folder ``fsync``-ed —
before the first local byte changes. It goes to ``<data>/sync/kept/ordnung-kept-<local
YYYY-MM-DD-HHMM>[-n].ordnung-backup`` (:data:`~ordnung.sync.KEPT_RE`), is opened with ``ordnung restore
<file> --data-dir <another folder>`` and the sync passphrase, is never synced and never pruned by
itself, and is lost with this computer's disk and with Delete everything. A copy of the same data (its
digest) is reused, not written again.

A forgotten computer's version that holds changes found nowhere else is kept the same way, from what
was staged (:func:`keep_staged`, ``BackupStream.from_parts``).
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

from ordnung.backup import write_backup_file
from ordnung.backup.archive import BackupStream
from ordnung.backup.container import BackupError
from ordnung.sync import KEPT_RE, KEPT_WARN_BYTES, SyncError
from ordnung.sync.folder import PRIVATE_FILE_MODE
from ordnung.sync.model import KeptInfo

if TYPE_CHECKING:
    from ordnung.sync.engine import Session
    from ordnung.sync.pull import Staged


def kept_name(folder: Path, stamp: str) -> str:
    """``ordnung-kept-<YYYY-MM-DD-HHMM>[-n].ordnung-backup``, the first free one."""
    base = f"ordnung-kept-{stamp}"
    name = f"{base}.ordnung-backup"
    number = 2
    while (folder / name).exists():
        name = f"{base}-{number}.ordnung-backup"
        number += 1
    assert KEPT_RE.match(name)
    return name


def _stamp(session: Session) -> str:
    return session.clock.wall().strftime("%Y-%m-%d-%H%M")


def keep_local(session: Session, why: str, *, digest: str | None = None) -> KeptInfo:
    """Write the kept copy of this computer's live data (module doc); reuse one of the same digest."""
    state = session.state
    if digest is not None:
        for info in state.kept:
            if info.digest == digest and (session.local.kept_dir / info.name).is_file():
                return info
    passphrase = session.passphrase_now()
    session.local.ensure()
    folder = session.local.kept_dir
    name = kept_name(folder, _stamp(session))
    try:
        write_backup_file(session.paths.data_dir, folder / name, passphrase)
    except BackupError as exc:
        raise SyncError(
            "folder_problem", f"Ordnung couldn't keep a copy of this computer's data: {exc}"
        ) from exc
    except OSError as exc:
        if exc.errno == 28:  # ENOSPC
            raise SyncError("no_space", "This computer has no room to keep a copy of its data.") from exc
        raise
    session.data_fs.fsync_dir(folder)
    info = KeptInfo(name=name, why=why, digest=digest, created_at=session.clock.iso())
    state.kept = [*state.kept, info]
    session.save()
    return info


def keep_staged(session: Session, staged: Staged, why: str) -> KeptInfo:
    """Keep the staged version (a forgotten computer's) as a copy here."""
    passphrase = session.passphrase_now()
    session.local.ensure()
    folder = session.local.kept_dir
    name = kept_name(folder, _stamp(session))
    incoming = session.local.incoming
    files = [
        (
            entry.path,
            incoming / entry.path
            if entry.path in staged.staged_files
            else session.paths.data_dir / entry.path,
        )
        for entry in staged.entries
    ]
    stream = BackupStream.from_parts(staged.db_path, files, passphrase)
    target = folder / name
    partial = target.with_name(f".{name}.{os.getpid()}.part")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(partial, flags, PRIVATE_FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as out:
            for chunk in stream:
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        partial.replace(target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
    session.data_fs.fsync_dir(folder)
    info = KeptInfo(name=name, why=why, digest=staged.target.digest, created_at=session.clock.iso())
    session.state.kept = [*session.state.kept, info]
    session.save()
    return info


def kept_total(session: Session) -> int:
    total = 0
    for path in session.local.kept_files():
        with contextlib.suppress(OSError):
            total += path.stat().st_size
    return total


def kept_warning(session: Session) -> bool:
    return kept_total(session) > KEPT_WARN_BYTES


def kept_path(session: Session, name: str) -> Path | None:
    """The kept copy ``name`` — only a name of the pattern that is there (never a path)."""
    if not KEPT_RE.match(name):
        return None
    path = session.local.kept_dir / name
    return path if path.is_file() else None


def delete_kept(session: Session, name: str) -> bool:
    path = kept_path(session, name)
    if path is None:
        return False
    path.unlink()
    session.data_fs.fsync_dir(path.parent)
    session.state.kept = [info for info in session.state.kept if info.name != name]
    session.save()
    return True
