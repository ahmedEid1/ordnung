"""Schema migrations: ``db/migrations/NNNN_name.sql``, each applied once and recorded.

Each migration runs in its own ``BEGIN IMMEDIATE`` transaction together with its record, so a failing
script leaves the database exactly as it was. Whether a migration ran is re-read inside the
transaction, which makes concurrent openers (two processes starting at once) safe: the second one sees
the record and skips the script.

Numbering policy: numbers are handed out to pieces of work before they are merged, so a number may be
unused for a while (0003 and 0004 without 0002), and a lower number may arrive after a database ran a
higher one. Numbers must start at 0001 and never repeat; gaps are allowed. So a database keeps a ledger
of what ran (the table :data:`LEDGER`: version and name) and every migration not in it is applied, in
number order, whatever the database's highest version — every migration must therefore be written to
apply after any other (add, never rewrite). ``PRAGMA user_version`` still holds the highest version
that ran, so an older Ordnung refuses a database a newer one wrote.

A database from before the ledger existed ran exactly 0001 (it was the only migration any release
shipped; its runner refused gaps), so ``user_version`` 1 is recorded as {1}. One at a higher version
without a ledger was written by a development build that could skip a lower number; which ones ran
can't be told, so it is refused with that reason rather than guessed.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
#: The table that records which migrations ran (created by the runner itself, never by a migration).
LEDGER = "schema_migrations"

_FILENAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)
_LEDGER_SQL = f"CREATE TABLE IF NOT EXISTS {LEDGER} (version INTEGER PRIMARY KEY, name TEXT NOT NULL)"
#: The highest ``user_version`` a database without a ledger can have reached with every migration run.
_LEGACY_VERSION = 1


@dataclass(frozen=True)
class Migration:
    """One migration script (``version`` is the number in its filename)."""

    version: int
    name: str
    path: Path


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Return the migrations in ``directory`` sorted by version.

    Raises ``ValueError`` for ``.sql`` files that do not follow ``NNNN_name.sql``, when the first
    number is not 1 or when two files share a number (gaps are allowed, see the module docstring).
    """
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME_RE.match(path.name)
        if match is None:
            raise ValueError(f"migration file name must look like 0001_name.sql: {path.name}")
        found.append(Migration(int(match.group(1)), match.group(2), path))
    found.sort(key=lambda m: m.version)
    versions = [m.version for m in found]
    if versions and (versions[0] != 1 or len(set(versions)) != len(versions)):
        names = ", ".join(m.path.name for m in found)
        raise ValueError(f"migrations must start at 0001 and never share a number: {names}")
    return found


def latest_version(directory: Path = MIGRATIONS_DIR) -> int:
    """The schema version this code migrates to (0 when there are no migrations)."""
    migrations = discover(directory)
    return migrations[-1].version if migrations else 0


def current_version(conn: sqlite3.Connection) -> int:
    """The highest schema version stored in the database header (0 for a new database)."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _has_ledger(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (LEDGER,)).fetchone()
    return row is not None


def _legacy_versions(version: int) -> set[int]:
    """What a database without a ledger ran (see the module docstring); refuses what can't be told."""
    if version > _LEGACY_VERSION:
        raise RuntimeError(
            f"This database is at schema version {version} but has no record of which migrations ran "
            "(a development build wrote it), so Ordnung can't tell whether a lower-numbered one was "
            "skipped. Rebuild it (for the demo: ordnung demo --reset), or restore a backup."
        )
    return set(range(1, version + 1))


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    """The migrations that ran on this database (read-only; a database without a ledger is read by
    the legacy rule of the module docstring)."""
    if _has_ledger(conn):
        return {int(row[0]) for row in conn.execute(f"SELECT version FROM {LEDGER}")}
    return _legacy_versions(current_version(conn))


def pending(conn: sqlite3.Connection, *, directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """The migrations of ``directory`` this database has not run yet, in order (read-only)."""
    done = applied_versions(conn)
    return [m for m in discover(directory) if m.version not in done]


def split_statements(script: str) -> list[str]:
    """Split an SQL script into single statements (``sqlite3.complete_statement`` aware).

    Semicolons inside string literals, comments and ``CREATE TRIGGER … END`` bodies do not split.
    Raises ``ValueError`` if the script ends with an incomplete statement.
    """
    statements: list[str] = []
    buffer = ""
    *chunks, tail = script.split(";")
    for chunk in chunks:
        buffer += chunk + ";"
        if sqlite3.complete_statement(buffer):
            if _has_sql(buffer):
                statements.append(buffer.strip())
            buffer = ""
    if _has_sql(buffer + tail):
        raise ValueError(f"incomplete SQL statement at end of script: {(buffer + tail).strip()[:80]!r}")
    return statements


def _has_sql(text: str) -> bool:
    return bool(_COMMENT_RE.sub("", text).strip(" \t\r\n;"))


def _in_transaction(conn: sqlite3.Connection, work: Callable[[sqlite3.Connection], None]) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        work(conn)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:  # some errors (e.g. SQLITE_FULL) already rolled back
            conn.execute("ROLLBACK")
        raise


def _ensure_ledger(conn: sqlite3.Connection, migrations: list[Migration]) -> None:
    """Create the ledger, recording what a database from before it ran (the legacy rule)."""

    def create(conn: sqlite3.Connection) -> None:
        if _has_ledger(conn):  # another process created it meanwhile
            return
        done = _legacy_versions(current_version(conn))
        names = {m.version: m.name for m in migrations}
        conn.execute(_LEDGER_SQL)
        conn.executemany(
            f"INSERT INTO {LEDGER} (version, name) VALUES (?, ?)",
            [(version, names.get(version, "")) for version in sorted(done)],
        )

    if not _has_ledger(conn):
        _in_transaction(conn, create)


def _apply(conn: sqlite3.Connection, migration: Migration) -> None:
    statements = split_statements(migration.path.read_text(encoding="utf-8"))

    def run(conn: sqlite3.Connection) -> None:
        ran = conn.execute(f"SELECT 1 FROM {LEDGER} WHERE version = ?", (migration.version,)).fetchone()
        if ran is not None:  # another process may have won the race
            return
        for statement in statements:
            conn.execute(statement)
        conn.execute(
            f"INSERT INTO {LEDGER} (version, name) VALUES (?, ?)", (migration.version, migration.name)
        )
        conn.execute(f"PRAGMA user_version = {max(current_version(conn), migration.version):d}")

    _in_transaction(conn, run)


def migrate(conn: sqlite3.Connection, *, directory: Path = MIGRATIONS_DIR) -> int:
    """Apply every migration the database has not run (see the module docstring) and return the
    resulting schema version (the highest that ran).

    Idempotent: calling it on an up-to-date database changes nothing. ``conn`` must not be inside a
    transaction. Raises ``RuntimeError`` if the database was written by a newer schema (a higher
    version, or a migration this code doesn't have) or can't say which migrations it ran.
    """
    if conn.in_transaction:
        raise RuntimeError("migrate() must not run inside an open transaction")
    migrations = discover(directory)
    latest = migrations[-1].version if migrations else 0
    version = current_version(conn)
    if version > latest:
        raise RuntimeError(
            f"database schema version {version} is newer than this version of Ordnung supports ({latest})"
        )
    _ensure_ledger(conn, migrations)
    unknown = applied_versions(conn) - {m.version for m in migrations}
    if unknown:
        listed = ", ".join(f"{number:04d}" for number in sorted(unknown))
        raise RuntimeError(
            f"this database ran migration {listed}, which this version of Ordnung doesn't have — "
            "it was written by a newer version"
        )
    for migration in pending(conn, directory=directory):
        _apply(conn, migration)
    return current_version(conn)
