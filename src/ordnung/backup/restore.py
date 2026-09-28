"""Putting a backup back: where it goes, and what happens to a data folder that is already there.

Written policy (ADR 0007):

* **Never over existing data without ``force``.** The target data folder is *free* when it does not
  exist, or holds nothing but the lock file and Ordnung's own folders (``files/``, ``derived/``,
  ``drafts/``, ``inbox/``) with nothing in them. Anything else — a database, a letter, a file
  Ordnung did not create — is existing data, and restoring is refused unless ``force`` is given.
* **Nothing is deleted.** With ``force`` the whole old folder is renamed to
  ``<folder>.before-restore-<YYYYmmdd-HHMMSS>`` next to it (``-2``, ``-3`` … when that name is
  taken); the person deletes it when they are sure.
* **Never under a running Ordnung.** A folder whose lock is held (``ordnung serve``, a command still
  running) is refused, with or without ``force`` — checked before and again right before the swap.
* **All or nothing.** The backup is decrypted into a private staging folder next to the target
  (``.<name>.restoring-<random>``) and proven complete there (:func:`~ordnung.backup.archive.extract_backup`);
  only then is the old folder moved aside and the staging folder renamed into place (one rename on
  the same file system). Any failure removes the staging folder and leaves the target as it was; a
  failed final rename moves the old folder back.
* **A restored copy doesn't act as the original.** The Ordnung the backup came from may still be
  running, with the same calendar connected. So a restored calendar-sync connection starts detached
  (:func:`ordnung.calendar.caldav.detached`, changed in the staged database once it is proven): the
  calendar's address and mode stay, but it has no password on this computer, no claim on the events
  the original sent, and syncs nothing until the person enters the app password in Settings →
  Calendar. Nothing else in the database is changed.
"""

from __future__ import annotations

import os
import secrets
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ordnung.backup.archive import DB_NAME, BackupContents, extract_backup
from ordnung.backup.container import BackupError
from ordnung.calendar import caldav
from ordnung.locking import LOCK_NAME, DataDirLock, DataDirLocked
from ordnung.models import CalendarSyncState

#: Ordnung's own folders that may exist (empty) in a data folder that still counts as free.
EMPTY_OK = frozenset({"files", "derived", "drafts", "inbox"})
ASIDE_SUFFIX = ".before-restore-"
PRIVATE_DIR_MODE = 0o700


class TargetNotFree(BackupError):
    """The target data folder holds data and ``force`` was not given."""


class TargetInUse(BackupError):
    """Ordnung (or one of its commands) is running for the target data folder."""


@dataclass(frozen=True)
class RestoreResult:
    """Where the backup went and what happened to the folder that was there."""

    target: Path
    contents: BackupContents
    moved_aside: Path | None = None
    #: the calendar whose sync connection was restored detached (its host or name), if there was one
    calendar: str | None = None


def _is_empty_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and not any(path.iterdir())


def existing_data(target: Path) -> list[str]:
    """Names in ``target`` that count as existing data (empty when the folder is free)."""
    if not target.exists():
        return []
    if not target.is_dir():
        return [target.name]
    found = []
    for entry in sorted(target.iterdir(), key=lambda path: path.name):
        if entry.name == LOCK_NAME or (entry.name in EMPTY_OK and _is_empty_dir(entry)):
            continue
        found.append(entry.name)
    return found


def check_not_running(target: Path) -> None:
    """Refuse when a process holds the target's data-folder lock (only a folder with a lock file can
    have one — a folder Ordnung never used gets no lock file from this check)."""
    if not (target / LOCK_NAME).is_file():
        return
    try:
        with DataDirLock(target, purpose="ordnung restore"):
            pass
    except DataDirLocked as exc:
        raise TargetInUse(
            f"Ordnung is running for {target} ({exc.holder or 'another process'}). Stop it first, then restore."
        ) from None


def check_target(target: Path, *, force: bool) -> list[str]:
    """Refuse a target in use, or one with data unless ``force``; returns the data found."""
    check_not_running(target)
    found = existing_data(target)
    if found and not force:
        shown = ", ".join(found[:5]) + (" …" if len(found) > 5 else "")
        raise TargetNotFree(
            f"{target} already holds Ordnung data ({shown}). Restoring would replace it: add --force "
            "to move it aside first (nothing is deleted), or restore into another folder with --data-dir."
        )
    return found


def aside_path(target: Path, now: datetime) -> Path:
    """``<target>.before-restore-<stamp>`` (with ``-2``, ``-3`` … when taken)."""
    base = f"{target.name}{ASIDE_SUFFIX}{now:%Y%m%d-%H%M%S}"
    candidate, n = target.with_name(base), 2
    while candidate.exists():
        candidate = target.with_name(f"{base}-{n}")
        n += 1
    return candidate


def _remove_free(target: Path) -> None:
    """Remove a free data folder: its lock file and empty folders only (``rmdir`` refuses anything else)."""
    (target / LOCK_NAME).unlink(missing_ok=True)
    for name in sorted(EMPTY_OK):
        folder = target / name
        if folder.is_dir() and not folder.is_symlink():
            folder.rmdir()
    target.rmdir()


def detach_calendar_sync(db_path: Path) -> str | None:
    """Detach the restored calendar-sync connection in ``db_path`` (module policy); returns the
    calendar's name or host, ``None`` when none was connected."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (caldav.STATE_KEY,)).fetchone()
        if row is None:
            return None
        try:
            state = CalendarSyncState.model_validate_json(row[0])
        except ValueError:  # unreadable: Ordnung treats it as not connected (and so does this)
            conn.execute("DELETE FROM meta WHERE key = ?", (caldav.STATE_KEY,))
            conn.commit()
            return None
        conn.execute(
            "UPDATE meta SET value = ? WHERE key = ?",
            (caldav.detached(state).model_dump_json(), caldav.STATE_KEY),
        )
        conn.commit()
        return state.calendar_name or caldav.host_of(state.url)
    finally:
        conn.close()


def _staging_dir(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f".{target.name}.restoring-{secrets.token_hex(4)}")
    staging.mkdir(mode=PRIVATE_DIR_MODE)
    return staging


def restore_backup(
    backup: Path,
    passphrase: str,
    target: Path,
    *,
    force: bool = False,
    now: Callable[[], datetime] = datetime.now,
) -> RestoreResult:
    """Restore ``backup`` into the data folder ``target`` (module policy)."""
    target = target.expanduser().absolute()
    check_target(target, force=force)
    staging = _staging_dir(target)
    try:
        with backup.open("rb") as src:
            contents = extract_backup(src, passphrase, staging)
        calendar = detach_calendar_sync(staging / DB_NAME)
        for folder in ("files", "derived", "drafts"):
            (staging / folder).mkdir(mode=PRIVATE_DIR_MODE, exist_ok=True)
        # the folder may have filled or a server started while the backup was decrypted
        found = check_target(target, force=force)
        moved = aside_path(target, now()) if found else None
        if moved is not None:
            target.rename(moved)
        elif target.exists():
            _remove_free(target)
        try:
            staging.rename(target)
        except OSError:
            if moved is not None:
                moved.rename(target)
            raise
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if os.name == "posix":
        target.chmod(PRIVATE_DIR_MODE)
    return RestoreResult(target=target, contents=contents, moved_aside=moved, calendar=calendar)
