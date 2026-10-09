"""When Ordnung reminds the person to back up (:mod:`ordnung.backup.reminder`): the newest copy kept
elsewhere — a backup made here, the one a restored copy came from, hand-off sync's last save — counted
in calendar days in the person's time zone. Pure: the day, the zone and the sync copy are given."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from helpers_secretary import add_doc
from ordnung.backup import reminder
from ordnung.backup.reminder import DUE_AFTER_DAYS, SyncCopy, backup_copy, for_store, newest_backup
from ordnung.db.store import Store

BERLIN = ZoneInfo("Europe/Berlin")
TODAY = date(2026, 10, 9)


def copy_of(
    last_backup: str | None = None,
    *,
    restored: bool = False,
    sync: SyncCopy | None = None,
    has_letters: bool = True,
    demo: bool = False,
    today: date = TODAY,
) -> reminder.BackupCopy:
    return backup_copy(
        last_backup=last_backup,
        restored=restored,
        sync=sync,
        has_letters=has_letters,
        demo=demo,
        zone=BERLIN,
        today=today,
    )


def test_letters_and_no_backup_ever_is_due() -> None:
    copy = copy_of()
    assert copy.due and copy.days is None and copy.last_backup_at is None
    assert copy.due_after_days == DUE_AFTER_DAYS == 30


def test_without_letters_or_in_the_demo_it_is_never_due() -> None:
    assert not copy_of(has_letters=False).due
    assert not copy_of(demo=True).due
    assert not copy_of("2020-01-01T10:00:00Z", demo=True).due


def test_a_backup_30_calendar_days_old_is_not_due_and_31_is() -> None:
    # 22:30 UTC on 8 Sep is already 9 Sep in Berlin: 30 days to 9 Oct there, not 31
    thirty = copy_of("2026-09-08T22:30:00Z")
    assert thirty.days == 30 and not thirty.due
    thirty_one = copy_of("2026-09-08T21:30:00Z")  # 23:30 on 8 Sep in Berlin
    assert thirty_one.days == 31 and thirty_one.due
    assert thirty_one.last_backup_at == "2026-09-08T21:30:00Z"


def test_a_recent_sync_save_counts_as_a_copy() -> None:
    saved = (datetime(2026, 10, 9, 9, 0, tzinfo=BERLIN) - timedelta(hours=1)).isoformat()
    copy = copy_of("2026-01-01T10:00:00Z", sync=SyncCopy(saved_at=saved, standing_by=False))
    assert not copy.due and copy.days == 0 and copy.sync_saved_at == saved
    assert copy.last_backup_at == "2026-01-01T10:00:00Z" and not copy.sync_standing_by


def test_an_old_sync_save_is_no_copy_to_rely_on() -> None:
    copy = copy_of(sync=SyncCopy(saved_at="2026-08-01T10:00:00+02:00", standing_by=False))
    assert copy.due and copy.days == 69


def test_standing_by_is_never_due_the_computer_in_use_saves() -> None:
    copy = copy_of(sync=SyncCopy(saved_at="2026-01-01T10:00:00+01:00", standing_by=True))
    assert not copy.due and copy.sync_standing_by
    assert not copy_of(sync=SyncCopy(saved_at=None, standing_by=True)).due


def test_a_backup_in_the_future_counts_as_today() -> None:
    copy = copy_of("2026-11-20T10:00:00Z")
    assert copy.days == 0 and not copy.due


def test_the_restored_flag_is_kept_only_with_its_backup() -> None:
    assert copy_of("2026-10-01T10:00:00Z", restored=True).last_backup_restored
    assert not copy_of(None, restored=True).last_backup_restored


def test_an_unreadable_moment_is_no_backup() -> None:
    copy = copy_of("last tuesday")
    assert copy.last_backup_at is None and copy.days is None and copy.due


def test_sync_copy_only_while_connected() -> None:
    assert SyncCopy.of(connected=False, mode="in_use", saved_at="2026-10-09T10:00:00+02:00") is None
    assert SyncCopy.of(connected=True, mode="in_use", saved_at=None) == SyncCopy(None, standing_by=False)
    assert SyncCopy.of(connected=True, mode="standing_by", saved_at="x") == SyncCopy("x", standing_by=True)


# --------------------------------------------------------------------------------------------------
# the newest backup a data folder knows
# --------------------------------------------------------------------------------------------------


def _row(store: Store, kind: str, ts: str, data: dict[str, str] | None = None) -> None:
    store._conn().execute(
        "INSERT INTO activity (ts, kind, message, data) VALUES (?, ?, ?, ?)",
        (ts, kind, "note", json.dumps(data or {})),
    )


def test_newest_backup_is_a_made_one_or_the_one_a_copy_was_restored_from(store: Store) -> None:
    assert newest_backup(store._conn()) == (None, False) == store.newest_backup()
    _row(store, "backup.created", "2026-10-01T10:00:00Z")
    _row(store, "backup.restored", "2026-10-05T10:00:00Z", {"made_at": "2026-09-20T08:00:00Z"})
    _row(store, "document.added", "2026-10-08T10:00:00Z")
    assert store.newest_backup() == ("2026-10-01T10:00:00Z", False)
    _row(store, "backup.restored", "2026-10-06T10:00:00Z", {"made_at": "2026-10-03T08:00:00Z"})
    assert store.newest_backup() == ("2026-10-03T08:00:00Z", True)


def test_a_privacy_log_row_with_broken_data_is_read_by_its_time(store: Store) -> None:
    store._conn().execute(
        "INSERT INTO activity (ts, kind, message, data) VALUES (?, ?, ?, ?)",
        ("2026-10-02T10:00:00Z", "backup.created", "note", "{not json"),
    )
    assert store.newest_backup() == ("2026-10-02T10:00:00Z", False)


def test_has_letters_counts_the_trash_too(store: Store) -> None:
    assert not store.has_letters()
    doc = add_doc(store, "letter")
    assert store.has_letters()
    store.trash_document(doc)
    assert store.has_letters()


def test_for_store_reads_the_folder_and_the_persons_zone(store: Store) -> None:
    copy = for_store(store, sync=None, demo=False, today=TODAY)
    assert not copy.due  # no letters yet
    add_doc(store, "letter")
    assert for_store(store, sync=None, demo=False, today=TODAY).due
    assert not for_store(store, sync=None, demo=True, today=TODAY).due
    store.log_activity("backup.created", "Made an encrypted backup (1 letter, 0 files)")
    made = for_store(store, sync=None, demo=False, today=datetime.now(UTC).date())
    assert not made.due and made.days == 0 and made.last_backup_at is not None


@pytest.mark.parametrize("zone", ["Mars/Olympus", ""])
def test_an_unknown_time_zone_uses_the_systems(store: Store, zone: str) -> None:
    profile = store.get_profile()
    store.save_profile(profile.model_copy(update={"timezone": zone}))
    add_doc(store, "letter")
    assert for_store(store, sync=None, demo=False, today=TODAY).due
