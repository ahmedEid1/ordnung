"""What leaves this computer, what it keeps, and what "the same data" means (design §6, §7.4; review
findings 5, 15, 19, 25).

* :func:`scrub` turns an in-memory copy of the database into what a push carries: this computer's own
  meta keys (:data:`~ordnung.sync.LOCAL_META`), the demo's and the local privacy-log rows go — deleted
  with ``secure_delete`` on, so not even free pages keep them; the per-computer settings fields go back
  to their defaults (all but ``demo``, which stays so a receiver can refuse a demo database); a reading
  in progress is queued again (``running`` → ``queued``, F34); stored paths use ``/``.
* :func:`state_digest` is a SHA-256 over the scrubbed copy's rows (every ordinary table in name order,
  every row by its ``rowid``, canonical JSON, blobs as hex — the full-text tables left out, being
  derived; the merged keys of :data:`~ordnung.sync.MERGED_META` left out, being unions), the data
  files' ``(path, sha256)`` and the calendar hand-over. Page layout, a checkpoint, ``VACUUM``, a write
  of the same value and every local key leave it unchanged: equal digests mean equal synced data, so a
  computer can say "unchanged since its base" without trusting any clock.
  Measured (P1): a generated 157 MiB database digests in 1.27 s, and its in-memory copy and
  serialization take 0.41 s — so the digest is taken only after ``data_version`` moved and the
  debounce passed, never on a timer.
* :func:`merge_local` runs inside the pull's apply: the live database's local keys, local settings
  fields and local privacy-log rows are carried into the staged copy, the merged keys are united, and
  the calendar's "already sent" record is merged when this computer's own connection is to the same
  calendar in the same mode (finding 15); ``sync_mark`` names the version the database now holds.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import ValidationError

from ordnung.backup.archive import table_counts
from ordnung.calendar.caldav import STATE_KEY as CALENDAR_STATE_KEY
from ordnung.db.store import SETTINGS_META_KEY
from ordnung.models import AppSettings, CalendarSyncState
from ordnung.sync import (
    DEMO_META,
    LOCAL_ACTIVITY_KINDS,
    LOCAL_ACTIVITY_PREFIXES,
    LOCAL_META,
    LOCAL_SETTINGS,
    MERGED_META,
    MERGED_META_MAX,
    PERSON_META_KEY,
    SYNC_MARK_KEY,
)
from ordnung.sync.model import CalendarHandover, Summary, SummaryLetter, VersionId

#: Tables derived from others (the search indexes and their shadow tables): never digested.
DERIVED_TABLE_PREFIXES = ("documents_fts", "documents_trigram")
#: Tables whose rows are the person's own records (joining with any of them asks first).
PERSON_TABLES = (
    "documents",
    "items",
    "contracts",
    "drafts",
    "notes",
    "chat_messages",
    "call_notes",
    "proofs",
    "parties",
    "cases",
)
#: Settings fields scrubbed from a push: the local ones but ``demo`` (finding 19).
SCRUBBED_SETTINGS = tuple(name for name in LOCAL_SETTINGS if name != "demo")


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()
    return row is not None


def _marks(count: int) -> str:
    return ", ".join("?" for _ in range(count))


def _local_activity_where() -> tuple[str, list[str]]:
    clauses = [f"kind IN ({_marks(len(LOCAL_ACTIVITY_KINDS))})"]
    params = sorted(LOCAL_ACTIVITY_KINDS)
    for prefix in LOCAL_ACTIVITY_PREFIXES:
        clauses.append("substr(kind, 1, ?) = ?")
        params += [str(len(prefix)), prefix]
    return " OR ".join(clauses), params


def _posix(path: str) -> str:
    """A stored relative path with ``/`` (an absolute Windows path is left as it is)."""
    if "\\" not in path or path.startswith(("\\\\", "/")) or (len(path) > 1 and path[1] == ":"):
        return path
    return path.replace("\\", "/")


def person_count(conn: sqlite3.Connection) -> int | None:
    """The person-change counter in ``conn`` (``None``: there is none — a database put back by hand)."""
    if not _has_table(conn, "meta"):
        return None
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (PERSON_META_KEY,)).fetchone()
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def meta_value(conn: sqlite3.Connection, key: str) -> str | None:
    if not _has_table(conn, "meta"):
        return None
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row[0])


def settings_of(conn: sqlite3.Connection) -> AppSettings:
    raw = meta_value(conn, SETTINGS_META_KEY)
    if not raw:
        return AppSettings()
    try:
        return AppSettings.model_validate_json(raw)
    except ValidationError:
        return AppSettings()


def is_demo(conn: sqlite3.Connection) -> bool:
    """A demo database: ``settings.demo`` on, or any of the demo's own keys (the demo never syncs)."""
    if settings_of(conn).demo:
        return True
    if not _has_table(conn, "meta"):
        return False
    row = conn.execute(
        f"SELECT 1 FROM meta WHERE key IN ({_marks(len(DEMO_META))})", sorted(DEMO_META)
    ).fetchone()
    return row is not None


def scrub(conn: sqlite3.Connection) -> None:
    """Make the in-memory copy ``conn`` what a push carries (module doc)."""
    conn.execute("PRAGMA secure_delete=ON")
    with conn:
        if _has_table(conn, "meta"):
            gone = sorted(LOCAL_META | DEMO_META)
            conn.execute(f"DELETE FROM meta WHERE key IN ({_marks(len(gone))})", gone)
            raw = meta_value(conn, SETTINGS_META_KEY)
            if raw:
                current = settings_of(conn)
                defaults = AppSettings()
                reset = current.model_copy(
                    update={name: getattr(defaults, name) for name in SCRUBBED_SETTINGS}
                )
                conn.execute(
                    "UPDATE meta SET value = ? WHERE key = ?", (reset.model_dump_json(), SETTINGS_META_KEY)
                )
        if _has_table(conn, "activity"):
            where, params = _local_activity_where()
            conn.execute(f"DELETE FROM activity WHERE {where}", params)
        if _has_table(conn, "jobs"):
            conn.execute("UPDATE jobs SET status = 'queued' WHERE status = 'running'")
        for table, column in (("documents", "file_path"), ("pages", "image_path")):
            if not _has_table(conn, table):
                continue
            rows = conn.execute(
                f"SELECT rowid, {column} FROM {table} WHERE instr({column}, '\\') > 0"
            ).fetchall()
            for rowid, value in rows:
                fixed = _posix(str(value))
                if fixed != value:
                    conn.execute(f"UPDATE {table} SET {column} = ? WHERE rowid = ?", (fixed, rowid))


# --------------------------------------------------------------------------------------------------
# the digest
# --------------------------------------------------------------------------------------------------


def _canonical(value: Any) -> Any:
    if isinstance(value, bytes | bytearray | memoryview):
        return {"hex": bytes(value).hex()}
    if isinstance(value, float) and value.is_integer():
        return {"real": repr(value)}
    return value


def digested_tables(conn: sqlite3.Connection) -> list[str]:
    return [name for name in table_counts(conn) if not name.startswith(DERIVED_TABLE_PREFIXES)]


def _row_order(conn: sqlite3.Connection, table: str) -> str:
    quoted = table.replace('"', '""')
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    if sql is not None and "WITHOUT ROWID" in str(sql[0]).upper():
        columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{quoted}")') if row[5]]
        return ", ".join(f'"{c}"' for c in columns) or "1"
    return "rowid"


def state_digest(
    conn: sqlite3.Connection, files: Iterable[tuple[str, str]], calendar: CalendarHandover | None
) -> str:
    """The state digest of the scrubbed copy ``conn`` with the data files ``(path, sha256)`` and the
    calendar hand-over (module doc)."""
    digest = hashlib.sha256()
    digest.update(b"ordnung-sync digest 1\n")
    digest.update(str(int(conn.execute("PRAGMA user_version").fetchone()[0])).encode() + b"\n")
    merged = sorted(MERGED_META)
    for table in digested_tables(conn):
        quoted = table.replace('"', '""')
        digest.update(b"T" + table.encode("utf-8") + b"\n")
        where, params = "", list[str]()
        if table == "meta":
            where, params = f" WHERE key NOT IN ({_marks(len(merged))})", merged
        cursor = conn.execute(f'SELECT * FROM "{quoted}"{where} ORDER BY {_row_order(conn, table)}', params)
        names = [column[0] for column in cursor.description]
        digest.update(json.dumps(names).encode("utf-8") + b"\n")
        for row in cursor:
            line = json.dumps([_canonical(v) for v in row], ensure_ascii=False, separators=(",", ":"))
            digest.update(line.encode("utf-8") + b"\n")
    digest.update(b"F\n")
    for path, sha in sorted(files):
        digest.update(f"{path}\0{sha}\n".encode())
    digest.update(b"C\n")
    if calendar is not None:
        digest.update(calendar.model_dump_json().encode("utf-8"))
    return digest.hexdigest()


# --------------------------------------------------------------------------------------------------
# what the scrubbed copy tells
# --------------------------------------------------------------------------------------------------


def summary(conn: sqlite3.Connection) -> Summary:
    """Letters in all and the three newest by date added (titles; calendar dates only)."""
    if not _has_table(conn, "documents"):
        return Summary()
    letters = int(conn.execute("SELECT count(*) FROM documents WHERE deleted_at IS NULL").fetchone()[0])
    newest = [
        SummaryLetter(label=str(title or filename)[:500], added_on=str(created)[:10])
        for title, filename, created in conn.execute(
            "SELECT title, filename, created_at FROM documents WHERE deleted_at IS NULL "
            "ORDER BY created_at DESC, id DESC LIMIT 3"
        )
    ]
    return Summary(letters=letters, newest=newest)


def has_person_data(conn: sqlite3.Connection) -> bool:
    """Any of the person's own records (a letter, a date, a contract, a draft, a note, a chat …)."""
    for table in PERSON_TABLES:
        if _has_table(conn, table) and conn.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone():
            return True
    return False


def referenced_paths(conn: sqlite3.Connection) -> set[str]:
    """Every data-folder path the database names (originals and page images)."""
    found: set[str] = set()
    for table, column in (("documents", "file_path"), ("pages", "image_path")):
        if _has_table(conn, table):
            found.update(_posix(str(row[0])) for row in conn.execute(f"SELECT {column} FROM {table}"))
    return found


def document_ids(conn: sqlite3.Connection) -> set[str]:
    if not _has_table(conn, "documents"):
        return set()
    return {str(row[0]) for row in conn.execute("SELECT id FROM documents")}


# --------------------------------------------------------------------------------------------------
# calendar sync's hand-over (§6.4, finding 15)
# --------------------------------------------------------------------------------------------------


def calendar_target(url: str, username: str) -> str:
    return hashlib.sha256(f"{url}\n{username}".encode()).hexdigest()


def calendar_state(conn: sqlite3.Connection) -> CalendarSyncState | None:
    raw = meta_value(conn, CALENDAR_STATE_KEY)
    if not raw:
        return None
    try:
        return CalendarSyncState.model_validate_json(raw)
    except ValidationError:
        return None


def calendar_handover(conn: sqlite3.Connection) -> CalendarHandover | None:
    """What this computer's calendar connection sent (``None``: no connection)."""
    state = calendar_state(conn)
    if state is None:
        return None
    return CalendarHandover(
        target=calendar_target(state.url, state.username),
        mode=state.mode,
        events=dict(state.events),
        checked_on=state.checked_on,
    )


def merged_events(mine: dict[str, str], theirs: dict[str, str]) -> dict[str, str]:
    """Both computers' "already sent" records of one calendar: an event both sent alike keeps its
    hash; any other is marked unknown (``""``), so the next calendar run checks it (finding 15)."""
    return {
        href: mine[href] if mine.get(href) == theirs.get(href) else "" for href in sorted({*mine, *theirs})
    }


# --------------------------------------------------------------------------------------------------
# merging on pull
# --------------------------------------------------------------------------------------------------


class PersonChanged(RuntimeError):
    """The person changed something here after the pull was decided: it is given up (blocker 1)."""


def _union(theirs: Sequence[str], mine: Sequence[str], cap: int) -> list[str]:
    merged = list(dict.fromkeys([*theirs, *mine]))
    return merged[-cap:]


def _json_list(raw: str | None) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        return []
    return [entry for entry in value if isinstance(entry, str)] if isinstance(value, list) else []


def merge_local(
    staged: sqlite3.Connection,
    live: sqlite3.Connection,
    *,
    target: VersionId,
    calendar: CalendarHandover | None,
    expect_person: int | None = None,
) -> int | None:
    """Carry this computer's own state from ``live`` into ``staged`` (module doc); returns the person
    counter carried over. With ``expect_person``, :class:`PersonChanged` when the live counter moved
    since the pull was decided (nothing is changed then)."""
    live_meta = {str(k): str(v) for k, v in live.execute("SELECT key, value FROM meta")}
    carried = live_meta.get(PERSON_META_KEY)
    counter = int(carried) if carried is not None and carried.lstrip("-").isdigit() else None
    if expect_person is not None and counter != expect_person:
        raise PersonChanged
    staged.execute("BEGIN IMMEDIATE")
    try:
        for key in sorted(LOCAL_META):
            if key in live_meta:
                staged.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, live_meta[key]),
                )
            else:
                staged.execute("DELETE FROM meta WHERE key = ?", (key,))
        incoming = settings_of(staged)
        local_settings = AppSettings()
        if SETTINGS_META_KEY in live_meta:
            with contextlib.suppress(ValidationError):
                local_settings = AppSettings.model_validate_json(live_meta[SETTINGS_META_KEY])
        merged_settings = incoming.model_copy(update={f: getattr(local_settings, f) for f in LOCAL_SETTINGS})
        staged.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SETTINGS_META_KEY, merged_settings.model_dump_json()),
        )
        for key in sorted(MERGED_META):
            theirs = _json_list(meta_value(staged, key))
            mine = _json_list(live_meta.get(key))
            union = _union(theirs, mine, MERGED_META_MAX[key])
            if union:
                staged.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(union)),
                )
        _merge_calendar(staged, live_meta.get(CALENDAR_STATE_KEY), calendar)
        _carry_local_activity(staged, live)
        staged.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (SYNC_MARK_KEY, target.key()),
        )
        staged.execute("COMMIT")
    except BaseException:
        staged.execute("ROLLBACK")
        raise
    return counter


def _merge_calendar(
    staged: sqlite3.Connection, live_raw: str | None, handover: CalendarHandover | None
) -> None:
    """This computer keeps its own connection; its "already sent" record is merged with the hand-over
    when both are to the same calendar in the same mode (the row was carried over already)."""
    if live_raw is None or handover is None:
        return
    try:
        state = CalendarSyncState.model_validate_json(live_raw)
    except ValidationError:
        return
    if calendar_target(state.url, state.username) != handover.target or state.mode != handover.mode:
        return
    events = merged_events(state.events, handover.events)
    agreed = events == dict(state.events) == handover.events
    # the two records disagree: the next run also checks that the events are still there
    updated = state.model_copy(update={"events": events, "checked_on": state.checked_on if agreed else None})
    staged.execute("UPDATE meta SET value = ? WHERE key = ?", (updated.model_dump_json(), CALENDAR_STATE_KEY))


def _carry_local_activity(staged: sqlite3.Connection, live: sqlite3.Connection) -> None:
    """This computer's local privacy-log rows stay (finding 25): the same ids where they are free."""
    if not (_has_table(staged, "activity") and _has_table(live, "activity")):
        return
    where, params = _local_activity_where()
    staged.execute(f"DELETE FROM activity WHERE {where}", params)
    columns = "ts, kind, message, ref_type, ref_id, data"
    for row in live.execute(
        f"SELECT id, {columns} FROM activity WHERE {where} ORDER BY id", params
    ).fetchall():
        taken = staged.execute("SELECT 1 FROM activity WHERE id = ?", (row[0],)).fetchone()
        if taken is None:
            staged.execute(f"INSERT INTO activity (id, {columns}) VALUES (?, ?, ?, ?, ?, ?, ?)", tuple(row))
        else:
            staged.execute(f"INSERT INTO activity ({columns}) VALUES (?, ?, ?, ?, ?, ?)", tuple(row[1:]))
