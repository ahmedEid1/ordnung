"""What travels and what stays; what "the same data" means (design §6, §7.4; review findings 5, 15, 16,
19, 25; F34)."""

from __future__ import annotations

import ast
import contextlib
import importlib
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

import ordnung
from ordnung.backup.archive import database_copy
from ordnung.config import Paths
from ordnung.db.store import PERSON_META_KEY, Store, person_write
from ordnung.ingest import watcher
from ordnung.models import AppSettings, CalendarSyncState
from ordnung.sync import (
    DEMO_META,
    FOLDER_TAKEN_META_KEY,
    INTERRUPTIONS_META_KEY,
    LOCAL_META,
    LOCAL_SETTINGS,
    MERGED_META,
    SYNC_MARK_KEY,
    SYNCED_DIRS,
    SYNCED_META,
    SYNCED_META_PREFIXES,
    SYNCED_SETTINGS,
)
from ordnung.sync import PERSON_META_KEY as SYNC_PERSON_META_KEY
from ordnung.sync.model import CalendarHandover, VersionId
from ordnung.sync.scrub import (
    calendar_handover,
    calendar_target,
    merge_local,
    merged_events,
    scrub,
    state_digest,
)

SRC = Path(ordnung.__file__).parent
#: Module constants named like keys that are not meta keys (request state, prompt fields).
NOT_META = {"AUTH_STATE_KEY", "LISTENER_KEY", "DEVICE_KEY", "TODAY_KEY", "PAYMENT_NOTE_KEY"}


# --------------------------------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------------------------------


def _key_constants() -> dict[str, str]:
    """Every module-level string constant named like a meta key in ``src/ordnung``."""
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        if "web" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or not isinstance(node.value, ast.Constant):
                continue
            name, value = target.id, node.value.value
            if not isinstance(value, str) or name in NOT_META:
                continue
            if name.endswith(("_KEY", "_META_KEY", "_KEY_META")) or name == "META_KEY":
                found[f"{path.relative_to(SRC)}:{name}"] = value
    return found


def _classified(key: str) -> list[str]:
    homes = [
        name
        for name, keys in (
            ("local", LOCAL_META),
            ("merged", MERGED_META),
            ("demo", DEMO_META),
            ("synced", SYNCED_META),
        )
        if key in keys
    ]
    if key.startswith(SYNCED_META_PREFIXES):
        homes.append("prefix")
    return homes


def test_every_meta_key_is_classified() -> None:
    constants = _key_constants()
    assert len(constants) >= 20
    for where, key in constants.items():
        assert len(_classified(key)) == 1, f"{where} = {key!r} is classified {_classified(key)}"
    for key in ("profile", "settings", "brief:2026-10-07", SYNC_MARK_KEY, PERSON_META_KEY):
        assert len(_classified(key)) == 1, key


def test_every_meta_access_uses_a_known_constant() -> None:
    """A ``set_meta``/``get_meta`` with a literal or an unknown name would escape the classification."""
    names = {where.split(":")[1] for where in _key_constants()} | {
        "key",
        "_PROFILE_KEY",
        "_SETTINGS_KEY",
        "_INTERRUPTIONS_KEY",
    }
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr not in ("set_meta", "get_meta") or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Call) and getattr(first.func, "id", "") == "brief_key":
                continue
            label = first.attr if isinstance(first, ast.Attribute) else getattr(first, "id", None)
            assert label in names, (
                f"{path.relative_to(SRC)}:{node.lineno} reads or writes meta {ast.unparse(first)}"
            )


def test_the_shared_keys_are_the_same_strings() -> None:
    assert SYNC_PERSON_META_KEY == PERSON_META_KEY == "sync_person"
    assert FOLDER_TAKEN_META_KEY == watcher.FOLDER_TAKEN_META_KEY
    from ordnung.db import store

    assert INTERRUPTIONS_META_KEY == store.INTERRUPTIONS_KEY


def test_every_settings_field_is_classified() -> None:
    assert set(AppSettings.model_fields) == set(LOCAL_SETTINGS) | set(SYNCED_SETTINGS)
    assert not set(LOCAL_SETTINGS) & set(SYNCED_SETTINGS)


def test_every_data_folder_entry_is_classified(paths: Paths) -> None:
    """Every entry ``Paths`` and the root-file constants can create is synced or never walked."""
    from ordnung.demo.loader import MARKER_NAME
    from ordnung.locking import LOCK_NAME
    from ordnung.server import SERVER_FILE

    never = {
        "ordnung.db",
        "ordnung.db-wal",
        "ordnung.db-shm",
        LOCK_NAME,
        SERVER_FILE,
        MARKER_NAME,
        ".ordnung-open.html",
        "inbox",
        "phone",
        "sync",
    }
    made = {p.name for p in (paths.files, paths.derived, paths.drafts, paths.inbox, paths.db)}
    for attribute in dir(paths):
        value = getattr(paths, attribute, None)
        if isinstance(value, Path) and value.parent == paths.data_dir:
            made.add(value.name)
    for name in made:
        assert (name in SYNCED_DIRS) != (name in never), name


# --------------------------------------------------------------------------------------------------
# the scrub
# --------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def _copy(store: Store) -> Iterator[sqlite3.Connection]:
    """The in-memory copy a save scrubs, closed after the block."""
    with contextlib.closing(database_copy(store.db_path)) as copy:
        yield copy


def test_scrub_removes_what_stays_here(store: Store) -> None:
    store.set_meta("phone_access", '{"devices": ["Anna\'s iPhone"]}')
    store.set_meta("inbox_seen", "[]")
    store.set_meta(
        "calendar_sync", CalendarSyncState(url="https://cal.example/", username="anna").model_dump_json()
    )
    store.set_meta(SYNC_MARK_KEY, "x")
    store.set_meta("simulated_today", "2026-01-01")
    store.set_meta("profile", "{}")
    store.save_settings(
        AppSettings(inbox_dir="/home/anna/Scans", inbox_auto_read=True, concurrency=4, model="opus")
    )
    store.log_activity("backup.created", "Made a backup")
    store.log_activity("phone.paired", "Paired Anna's iPhone at 192.168.1.20")
    store.log_activity("folder.problem", "Ordnung can't read /home/anna/Scans")
    store.log_activity("document.added", "Added “Rechnung”")
    with _copy(store) as copy:
        scrub(copy)
        keys = {row[0] for row in copy.execute("SELECT key FROM meta")}
        assert not keys & (LOCAL_META | DEMO_META)
        assert "profile" in keys
        settings = AppSettings.model_validate_json(
            copy.execute("SELECT value FROM meta WHERE key='settings'").fetchone()[0]
        )
        assert settings.inbox_dir is None and not settings.inbox_auto_read and settings.concurrency == 2
        assert settings.model == "opus"  # travels
        kinds = [row[0] for row in copy.execute("SELECT kind FROM activity")]
        assert kinds == ["document.added"]  # finding 25: backups, phone and folder rows stay here
        assert b"/home/anna/Scans" not in copy.serialize() and b"192.168.1.20" not in copy.serialize()


def test_the_demo_flag_is_not_reset(store: Store) -> None:  # finding 19
    store.save_settings(AppSettings(demo=True))
    with _copy(store) as copy:
        scrub(copy)
        settings = AppSettings.model_validate_json(
            copy.execute("SELECT value FROM meta WHERE key='settings'").fetchone()[0]
        )
        assert settings.demo


def test_running_jobs_travel_as_queued(store: Store) -> None:  # F34
    doc = store.add_document(
        sha256="a" * 64, filename="x.pdf", mime="application/pdf", file_path="files/aa/x.pdf"
    )
    job = store.enqueue_job("ingest", doc.id)
    store._conn().execute("UPDATE jobs SET status='running' WHERE id=?", (job.id,))
    with _copy(store) as copy:
        scrub(copy)
        assert copy.execute("SELECT status FROM jobs").fetchone()[0] == "queued"


def test_stored_paths_travel_with_slashes(store: Store) -> None:
    store.add_document(
        sha256="b" * 64, filename="x.pdf", mime="application/pdf", file_path="files\\bb\\x.pdf"
    )
    store.add_document(
        sha256="c" * 64, filename="y.pdf", mime="application/pdf", file_path="C:\\Users\\x.pdf"
    )
    with _copy(store) as copy:
        scrub(copy)
        paths = sorted(row[0] for row in copy.execute("SELECT file_path FROM documents"))
        assert paths == ["C:\\Users\\x.pdf", "files/bb/x.pdf"]


# --------------------------------------------------------------------------------------------------
# the digest
# --------------------------------------------------------------------------------------------------


def _digest(
    store: Store, files: list[tuple[str, str]] | None = None, calendar: CalendarHandover | None = None
) -> str:
    with _copy(store) as copy:
        scrub(copy)
        return state_digest(copy, files or [], calendar)


def test_the_digest_ignores_noise_and_sees_real_edits(store: Store) -> None:
    store.add_note("first")
    store.set_meta("profile", "{}")
    before = _digest(store)
    store.set_meta("calendar_sync", CalendarSyncState(url="https://x/", username="a").model_dump_json())
    store.set_meta("desktop_notified_on", "2026-10-07")
    store.set_meta("inbox_seen", '["a"]')
    store.set_meta(SYNC_MARK_KEY, "abc:1")
    store.set_meta("own_pdfs", json.dumps(["f" * 64]))  # finding 5b: merged keys aren't digested
    with person_write():
        store.set_meta("profile", store.get_meta("profile") or "{}")  # a write of the same value
    store.log_activity("backup.created", "Made a backup")  # finding 5c
    conn = store._conn()
    conn.execute("VACUUM")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert _digest(store) == before
    store.add_note("second")
    assert _digest(store) != before


def test_the_digest_covers_files_and_the_calendar(store: Store) -> None:
    base = _digest(store, [("files/aa/x.pdf", "1" * 64)])
    assert _digest(store, [("files/aa/x.pdf", "2" * 64)]) != base
    handover = CalendarHandover(target="3" * 64, mode="discreet", events={"a.ics": "x"})
    assert _digest(store, [("files/aa/x.pdf", "1" * 64)], handover) != base


def test_the_counter_moves_only_for_the_persons_writes(store: Store) -> None:  # finding 5a
    store.add_note("background")
    assert store.get_meta(PERSON_META_KEY) is None
    with person_write():
        store.add_note("mine")
        store.add_note("mine too")
        store.set_meta("profile", store.get_meta("profile") or "{}")  # changes nothing: still counted once
    assert int(store.get_meta(PERSON_META_KEY) or 0) >= 2
    count = int(store.get_meta(PERSON_META_KEY) or 0)
    with person_write():
        store.list_notes() if hasattr(store, "list_notes") else None
    assert int(store.get_meta(PERSON_META_KEY) or 0) == count  # reading counts nothing


# --------------------------------------------------------------------------------------------------
# merging on pull
# --------------------------------------------------------------------------------------------------


def _staged_from(store: Store, tmp: Path) -> sqlite3.Connection:
    with _copy(store) as copy:
        scrub(copy)
        target = tmp / "staged.db"
        disk = sqlite3.connect(target, isolation_level=None)
        copy.backup(disk)
    return disk


def test_merge_keeps_this_computers_own_state(tmp_path: Path) -> None:
    them = Store.open(Paths(tmp_path / "them").ensure())
    here = Store.open(Paths(tmp_path / "here").ensure())
    try:
        them.save_settings(AppSettings(model="opus", inbox_dir="/them/Scans", concurrency=5))
        them.set_meta("own_pdfs", json.dumps(["a" * 64]))
        them.log_activity("document.added", "Added a letter there")
        here.save_settings(AppSettings(model="sonnet", inbox_dir="/here/Scans", inbox_auto_read=True))
        here.set_meta("phone_access", "{}")
        here.set_meta("inbox_seen", '["k"]')
        here.set_meta("own_pdfs", json.dumps(["b" * 64]))
        here.log_activity("phone.paired", "Paired a phone here")
        with person_write():
            here.add_note("counted")
        staged = _staged_from(them, tmp_path)
        live = sqlite3.connect(here.db_path, isolation_level=None)
        counter = merge_local(staged, live, target=VersionId(computer="a" * 32, seq=3), calendar=None)
        assert counter == int(here.get_meta(PERSON_META_KEY) or -1)
        meta = dict(staged.execute("SELECT key, value FROM meta"))
        settings = AppSettings.model_validate_json(meta["settings"])
        assert settings.model == "opus" and settings.inbox_dir == "/here/Scans" and settings.inbox_auto_read
        assert meta["phone_access"] == "{}" and meta["inbox_seen"] == '["k"]'
        assert set(json.loads(meta["own_pdfs"])) == {"a" * 64, "b" * 64}
        assert meta[SYNC_MARK_KEY] == "a" * 32 + ":3"
        kinds = sorted(row[0] for row in staged.execute("SELECT kind FROM activity"))
        assert kinds == ["document.added", "phone.paired"]
        live.close()
        staged.close()
    finally:
        them.close()
        here.close()


def test_calendar_hand_over_only_for_the_same_calendar_and_mode(tmp_path: Path) -> None:  # finding 15
    state = CalendarSyncState(
        url="https://cal.example/", username="anna", events={"a.ics": "1", "b.ics": "2"}
    )
    store = Store.open(Paths(tmp_path / "s").ensure())
    try:
        store.set_meta("calendar_sync", state.model_dump_json())
        handover = calendar_handover(store._conn())
        assert handover is not None and handover.target == calendar_target("https://cal.example/", "anna")
        assert handover.mode == "discreet"
    finally:
        store.close()
    assert merged_events({"a": "1", "b": "2"}, {"a": "1", "b": "9", "c": "3"}) == {"a": "1", "b": "", "c": ""}


def test_merge_gives_up_when_the_person_changed_something(tmp_path: Path) -> None:  # blocker 1
    from ordnung.sync.scrub import PersonChanged

    them = Store.open(Paths(tmp_path / "them").ensure())
    here = Store.open(Paths(tmp_path / "here").ensure())
    try:
        with person_write():
            here.add_note("one")
        expected = int(here.get_meta(PERSON_META_KEY) or 0)
        with person_write():
            here.add_note("after the decision")
        staged = _staged_from(them, tmp_path)
        live = sqlite3.connect(here.db_path, isolation_level=None)
        with pytest.raises(PersonChanged):
            merge_local(
                staged,
                live,
                target=VersionId(computer="a" * 32, seq=1),
                calendar=None,
                expect_person=expected,
            )
        live.close()
        staged.close()
    finally:
        them.close()
        here.close()


def test_scrub_module_imports_nothing_that_imports_sync() -> None:
    """``ordnung.sync`` imports backup, caldav, the watcher and the worker: none of them may import it
    back (the person counter lives in ``db.store`` for that reason)."""
    for name in (
        "ordnung.db.store",
        "ordnung.backup",
        "ordnung.ingest.watcher",
        "ordnung.ingest.worker",
        "ordnung.calendar.caldav",
    ):
        module = importlib.import_module(name)
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        assert "from ordnung.sync" not in source and "import ordnung.sync" not in source, name
