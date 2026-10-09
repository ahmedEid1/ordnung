"""When to remind the person to back up: the newest copy of this Ordnung kept elsewhere (ADR 0013).

Written policy:

* **What counts as a copy.** An encrypted backup this data folder knows: one made here (Settings → Data,
  ``ordnung backup``, a scheduled one too — a ``backup.created`` row of the privacy log), or the one this
  copy was restored from (a ``backup.restored`` row, its ``data.made_at``). And hand-off sync's last save
  into the sync folder, while this computer is connected and saves into it — or stands by while another
  computer does, which keeps the folder current.
* **What doesn't.** Sync's kept copies (they are on this disk), and backups of the whole computer (Time
  Machine, File History): Ordnung can't see them.
* **When it is time.** Letters exist, it isn't the demo, this computer isn't standing by, and no copy was
  made within :data:`DUE_AFTER_DAYS` calendar days — counted in the person's time zone up to the app's
  today. A copy "in the future" (another clock) counts as made today.
* **Only words.** The reminder is code's words on Settings → Data, the weekly review's ending and
  ``ordnung doctor``: never an Idea, never sent to a model, and nothing is backed up by itself.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ordnung.models import BackupCopy

if TYPE_CHECKING:
    from ordnung.db.store import Store

__all__ = [
    "BACKUP_KINDS",
    "DUE_AFTER_DAYS",
    "BackupCopy",
    "SyncCopy",
    "backup_copy",
    "for_store",
    "newest_backup",
    "parse_moment",
    "person_zone",
]

DUE_AFTER_DAYS = 30
#: The privacy-log rows that record a backup: made here, or the one a restored copy came from.
BACKUP_KINDS: tuple[str, str] = ("backup.created", "backup.restored")

# when the copy was made: a row's ``data.made_at`` when it has one (a restore's, the command line's), else
# when it was noted; every one is written as ``YYYY-MM-DDTHH:MM:SSZ``, so the newest sorts last
_NEWEST_SQL = (
    "SELECT kind, COALESCE(CASE WHEN json_valid(data) THEN json_extract(data, '$.made_at') END, ts) AS at "
    "FROM activity WHERE kind IN (?, ?) ORDER BY at DESC LIMIT 1"
)


@dataclass(frozen=True)
class SyncCopy:
    """Hand-off sync's copy in the sync folder, as this computer knows it."""

    #: this computer's last save into the sync folder (its own clock; ``None``: never yet)
    saved_at: str | None
    #: another computer is in use and keeps the folder current
    standing_by: bool = False

    @classmethod
    def of(cls, *, connected: bool, mode: str | None, saved_at: str | None) -> SyncCopy | None:
        """The copy while sync is connected (``None`` otherwise)."""
        if not connected:
            return None
        return cls(saved_at=saved_at, standing_by=mode == "standing_by")


def newest_backup(conn: sqlite3.Connection) -> tuple[str | None, bool]:
    """When the newest backup this data folder knows was made, and whether it is the one this copy was
    restored from (``(None, False)``: none)."""
    row = conn.execute(_NEWEST_SQL, BACKUP_KINDS).fetchone()
    if row is None or row[1] is None:
        return None, False
    return str(row[1]), row[0] == "backup.restored"


def parse_moment(value: str | None) -> datetime | None:
    """A stored time (ISO 8601; one without a zone counts as UTC), ``None`` when it can't be read."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def backup_copy(
    *,
    last_backup: str | None,
    restored: bool,
    sync: SyncCopy | None,
    has_letters: bool,
    demo: bool,
    zone: tzinfo,
    today: date,
) -> BackupCopy:
    """The newest copy and whether to remind (module policy). A time that can't be read counts as none."""
    made = parse_moment(last_backup)
    saved = parse_moment(sync.saved_at) if sync is not None else None
    newest = max((moment for moment in (made, saved) if moment is not None), default=None)
    days = None if newest is None else max(0, (today - newest.astimezone(zone).date()).days)
    standing_by = sync is not None and sync.standing_by
    due = not demo and has_letters and not standing_by and (days is None or days > DUE_AFTER_DAYS)
    return BackupCopy(
        last_backup_at=last_backup if made is not None else None,
        last_backup_restored=restored and made is not None,
        sync_saved_at=sync.saved_at if sync is not None else None,
        sync_standing_by=standing_by,
        days=days,
        due=due,
        due_after_days=DUE_AFTER_DAYS,
    )


def person_zone(store: Store) -> tzinfo:
    """The person's time zone (``profile.timezone``; the system's when it is unknown)."""
    try:
        return ZoneInfo(store.get_profile().timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now().astimezone().tzinfo or UTC


def for_store(store: Store, *, sync: SyncCopy | None, demo: bool, today: date) -> BackupCopy:
    """:func:`backup_copy` for a data folder: its newest backup and whether it holds letters, in the
    person's time zone up to ``today`` (the app's today)."""
    last_backup, restored = store.newest_backup()
    return backup_copy(
        last_backup=last_backup,
        restored=restored,
        sync=sync,
        has_letters=store.has_letters(),
        demo=demo,
        zone=person_zone(store),
        today=today,
    )
