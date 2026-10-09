"""Encrypted backup and restore of a whole data folder (SPEC §15, ``ordnung backup`` / ``ordnung restore``).

A backup is one file that holds everything needed to get Ordnung back on another computer: a
consistent snapshot of the database, the original letters, the page images and the letter PDFs
(:mod:`ordnung.backup.archive`), encrypted with a passphrase (:mod:`ordnung.backup.container`:
AES-256-GCM in authenticated chunks, a key from scrypt, a versioned header). Restoring never
replaces a data folder that holds data unless asked to, and then moves it aside instead of deleting
it (:mod:`ordnung.backup.restore`).

The passphrase policy for *new* backups (:func:`passphrase_problem`): at least
:data:`MIN_PASSPHRASE_CHARS` characters and at most :data:`MAX_PASSPHRASE_CHARS`, and about
:data:`~ordnung.passphrase.MIN_PASSPHRASE_BITS` bits by :func:`~ordnung.passphrase.passphrase_bits` — the
rule of a new sync folder, for the same reason: a backup on another drive or in a cloud folder can be
copied and guessed at offline for years. It is checked where a passphrase is chosen (``ordnung backup``,
the browser's download), and both of them suggest a strong one. The estimator counts words, or a
password manager's random characters by the alphabet they use; what Ordnung 0.1.0 suggested still
counts as strong (:func:`earlier_suggestion`), and a passphrase a script
gives in ``ORDNUNG_BACKUP_PASSPHRASE`` that falls short only gets a warning, so a scheduled backup is
still made (its length is checked as ever). Its key takes a sync folder's scrypt costs
(:data:`DEFAULT_KDF`); a backup made with the earlier, cheaper ones (2^17) opens as before, since the
header records them. Ordnung never stores the passphrase: without it the backup can't be opened, by anyone.

Where a backup you make goes (:func:`destination`: ``ordnung backup --to``; the browser downloads its
own): into a folder that exists (under the default name), or as a new file with an extension
(``mine.ordnung-backup``) — never inside the data folder it backs up, which a lost disk takes with it. A
name that doesn't exist and reads as a folder — written with a trailing ``/``, or without any extension
(``--to /media/usb`` with the stick not mounted) — is refused ("is the drive connected?") instead of
becoming a file of that name on the internal disk.

Writing a backup file (:func:`write_backup_file`): never over an existing file; the file is written under
a temporary name next to its destination, private to its owner (``0600``), and renamed into place only
once the last chunk is sealed. It checks only the passphrase's length (:func:`length_problem`), and
not where: the one backup file Ordnung writes inside the data folder is hand-off sync's *kept copy*
(:mod:`ordnung.sync.kept`, ADR 0018) — this computer's data saved in ``<data>/sync/kept/`` with the sync
passphrase before it is replaced (that passphrase was judged when its folder was set up, so a kept copy is
never refused for it). A kept copy undoes a replacement on this computer; it is never synced, and it is
lost with this computer's disk and with Delete everything.
"""

from __future__ import annotations

import contextlib
import os
import re
from datetime import date
from pathlib import Path

from ordnung import durable
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
from ordnung.passphrase import COMMON_WORDS, MIN_PASSPHRASE_BITS, is_run, passphrase_bits

__all__ = [
    "DEFAULT_KDF",
    "EARLIER_SUGGESTION",
    "FILE_SUFFIX",
    "MAX_PASSPHRASE_CHARS",
    "MIN_PASSPHRASE_CHARS",
    "WEAK_PASSPHRASE_MESSAGE",
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
    "earlier_suggestion",
    "estimate",
    "length_problem",
    "links_left_out",
    "passphrase_problem",
    "read_header",
    "restore_backup",
    "write_backup",
    "write_backup_file",
]

MIN_PASSPHRASE_CHARS = 12
MAX_PASSPHRASE_CHARS = 1024
WEAK_PASSPHRASE_MESSAGE = (
    "Ordnung can't count this passphrase as strong enough for a backup kept on another drive or in the "
    "cloud. Use five or more words that don't belong together, each of three letters or more, or a "
    "password manager's random password of 16 characters or more — or take the suggested one."
)
#: What Ordnung 0.1.0's backup dialog suggested: four groups of five of 31 letters and digits, drawn at
#: random (``k7qmx-3vxdp-9tawr-2emnb``: about 99 bits, though the estimator counts each group as a word).
EARLIER_SUGGESTION = re.compile(r"[a-hjkmnp-z2-9]{5}(?:-[a-hjkmnp-z2-9]{5}){3}")
FILE_SUFFIX = ".ordnung-backup"
PRIVATE_FILE_MODE = 0o600


def backup_file_name(day: date) -> str:
    """``ordnung-backup-2026-09-28.ordnung-backup``."""
    return f"ordnung-backup-{day.isoformat()}{FILE_SUFFIX}"


def length_problem(passphrase: str) -> str | None:
    """Why ``passphrase`` is too short or too long for any backup file (``None`` if it isn't)."""
    if len(passphrase) < MIN_PASSPHRASE_CHARS:
        return (
            f"Use a passphrase of at least {MIN_PASSPHRASE_CHARS} characters — five or more words that "
            "don't belong together work well."
        )
    if len(passphrase) > MAX_PASSPHRASE_CHARS:
        return f"Use a passphrase of at most {MAX_PASSPHRASE_CHARS} characters."
    return None


def earlier_suggestion(passphrase: str) -> bool:
    """``passphrase`` is one Ordnung 0.1.0 could have suggested (:data:`EARLIER_SUGGESTION`): four
    different groups, none a run, a keyboard walk or a common word."""
    if not EARLIER_SUGGESTION.fullmatch(passphrase):
        return False
    groups = passphrase.split("-")
    return len(set(groups)) == len(groups) and not any(is_run(g) or g in COMMON_WORDS for g in groups)


def passphrase_problem(passphrase: str) -> str | None:
    """Why ``passphrase`` can't protect a new backup (``None`` if it can): :func:`length_problem`, then
    about :data:`~ordnung.passphrase.MIN_PASSPHRASE_BITS` bits, or a suggestion of Ordnung 0.1.0's
    (:func:`earlier_suggestion`; see the module policy)."""
    problem = length_problem(passphrase)
    if problem is not None or earlier_suggestion(passphrase):
        return problem
    return WEAK_PASSPHRASE_MESSAGE if passphrase_bits(passphrase) < MIN_PASSPHRASE_BITS else None


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
    problem = length_problem(passphrase)
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
            durable.fsync(out.fileno())  # F_FULLFSYNC on macOS
        if target.exists():  # appeared while the backup was written
            raise BackupError(f"{target} already exists. Choose another name, or move the old backup first.")
        partial.replace(target)
    finally:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
    return contents
