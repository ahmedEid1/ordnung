"""Encrypted backup and restore of a whole data folder (SPEC §15, ``ordnung backup`` / ``ordnung restore``).

A backup is one file that holds everything needed to get Ordnung back on another computer: a
consistent snapshot of the database, the original letters, the page images and the letter PDFs
(:mod:`ordnung.backup.archive`), encrypted with a passphrase (:mod:`ordnung.backup.container`:
AES-256-GCM in authenticated chunks, a key from scrypt, a versioned header). Restoring never
replaces a data folder that holds data unless asked to, and then moves it aside instead of deleting
it (:mod:`ordnung.backup.restore`).

The passphrase policy for *new* backups: at least :data:`MIN_PASSPHRASE_CHARS` characters and at most
:data:`MAX_PASSPHRASE_CHARS`; nothing else is judged (a long sentence is a good passphrase).
Ordnung never stores it: without it the backup can't be opened, by anyone.

Where it goes (:func:`destination`): into a folder that exists (under the default name), or as a new
file with an extension (``mine.ordnung-backup``). A name that doesn't exist and reads as a folder —
written with a trailing ``/``, or without any extension (``--to /media/usb`` with the stick not
mounted) — is refused ("is the drive connected?") instead of becoming a file of that name on the
internal disk.

Writing a backup file (:func:`write_backup_file`): never inside the data folder it backs up, never
over an existing file; the file is written under a temporary name next to its destination, private
to its owner (``0600``), and renamed into place only once the last chunk is sealed.
"""

from __future__ import annotations

import contextlib
import os
from datetime import date
from pathlib import Path

from ordnung.backup.archive import BackupContents, check_backup, estimate, links_left_out, write_backup
from ordnung.backup.container import (
    DEFAULT_KDF,
    BackupError,
    DamagedBackup,
    KdfParams,
    NewerBackupFormat,
    NotABackup,
    WrongPassphrase,
    read_header,
)
from ordnung.backup.restore import RestoreResult, TargetInUse, TargetNotFree, restore_backup

__all__ = [
    "DEFAULT_KDF",
    "FILE_SUFFIX",
    "MAX_PASSPHRASE_CHARS",
    "MIN_PASSPHRASE_CHARS",
    "BackupContents",
    "BackupError",
    "DamagedBackup",
    "KdfParams",
    "NewerBackupFormat",
    "NotABackup",
    "RestoreResult",
    "TargetInUse",
    "TargetNotFree",
    "WrongPassphrase",
    "backup_file_name",
    "check_backup",
    "estimate",
    "links_left_out",
    "passphrase_problem",
    "read_header",
    "restore_backup",
    "write_backup",
    "write_backup_file",
]

MIN_PASSPHRASE_CHARS = 12
MAX_PASSPHRASE_CHARS = 1024
FILE_SUFFIX = ".ordnung-backup"
PRIVATE_FILE_MODE = 0o600


def backup_file_name(day: date) -> str:
    """``ordnung-backup-2026-09-28.ordnung-backup``."""
    return f"ordnung-backup-{day.isoformat()}{FILE_SUFFIX}"


def passphrase_problem(passphrase: str) -> str | None:
    """Why ``passphrase`` can't protect a new backup (``None`` if it can)."""
    if len(passphrase) < MIN_PASSPHRASE_CHARS:
        return (
            f"Use a passphrase of at least {MIN_PASSPHRASE_CHARS} characters — a short sentence works well."
        )
    if len(passphrase) > MAX_PASSPHRASE_CHARS:
        return f"Use a passphrase of at most {MAX_PASSPHRASE_CHARS} characters."
    return None


def _names_a_folder(to: str | Path) -> bool:
    """``to`` was written with a trailing separator (``/media/usb/``), so it means a folder."""
    return isinstance(to, str) and to.endswith(("/", os.sep))


def destination(data_dir: Path, to: str | Path | None, day: date) -> Path:
    """Where ``ordnung backup --to`` writes: a folder gets the default name; refuses the data folder
    and a folder that doesn't exist (see the module policy)."""
    target = (Path(to) if to is not None else Path.cwd()).expanduser().absolute()
    if target.is_dir():
        target = target / backup_file_name(day)
    elif not target.exists() and (_names_a_folder(to or "") or not target.suffix):
        raise BackupError(
            f"The folder {target} doesn't exist — is the drive connected? (To save the backup as a new "
            f"file, give its name with an extension, like {target.name}{FILE_SUFFIX}.)"
        )
    if target.resolve().is_relative_to(data_dir.resolve()):
        raise BackupError(
            "A backup can't be saved inside the data folder it backs up — choose another folder, "
            "ideally another drive."
        )
    if target.exists() or target.is_symlink():
        raise BackupError(f"{target} already exists. Choose another name, or move the old backup first.")
    if not target.parent.is_dir():
        raise BackupError(f"The folder {target.parent} doesn't exist.")
    return target


def write_backup_file(
    data_dir: Path, target: Path, passphrase: str, *, kdf: KdfParams = DEFAULT_KDF
) -> BackupContents:
    """Write the backup of ``data_dir`` to ``target`` atomically (see the module policy)."""
    problem = passphrase_problem(passphrase)
    if problem:
        raise BackupError(problem)
    partial = target.with_name(f".{target.name}.{os.getpid()}.part")
    # O_BINARY: without it Windows opens the file in text mode and writes every \n as \r\n
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(partial, flags, PRIVATE_FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as out:
            contents = write_backup(data_dir, out, passphrase, kdf=kdf)
            out.flush()
            os.fsync(out.fileno())
        if target.exists():  # appeared while the backup was written
            raise BackupError(f"{target} already exists. Choose another name, or move the old backup first.")
        partial.replace(target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
    return contents
