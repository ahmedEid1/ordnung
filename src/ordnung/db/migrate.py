"""Schema migrations: ``db/migrations/NNNN_name.sql`` applied in order, tracked by ``PRAGMA user_version``.

Each migration runs in its own ``BEGIN IMMEDIATE`` transaction together with the ``user_version``
bump, so a failing script leaves the database exactly at the previous version. The version is
re-read inside the transaction, which makes concurrent openers (two processes starting at once)
safe: the second one sees the new version and skips the script.

Numbering policy: numbers are handed out to pieces of work before they are merged, so a number may
be unused (0003 without 0002). Numbers must start at 0001 and increase; gaps are allowed, duplicates
are not. A database stores only the highest version it ran, so a migration whose number is below a
database's version is never applied to it: a gap may only be filled before any database migrates past
it (ship every number up to the latest together, and rebuild the demo snapshot when one is added).
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_FILENAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_COMMENT_RE = re.compile(r"--[^\n]*|/\*.*?\*/", re.S)


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
    """The schema version stored in the database header (0 for a new database)."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


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


def _apply(conn: sqlite3.Connection, migration: Migration) -> None:
    statements = split_statements(migration.path.read_text(encoding="utf-8"))
    conn.execute("BEGIN IMMEDIATE")
    try:
        if current_version(conn) < migration.version:  # another process may have won the race
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {migration.version:d}")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:  # some errors (e.g. SQLITE_FULL) already rolled back
            conn.execute("ROLLBACK")
        raise


def migrate(conn: sqlite3.Connection, *, directory: Path = MIGRATIONS_DIR) -> int:
    """Apply all pending migrations and return the resulting schema version.

    Idempotent: calling it on an up-to-date database changes nothing. ``conn`` must not be inside a
    transaction. Raises ``RuntimeError`` if the database was written by a newer schema.
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
    for migration in migrations:
        if migration.version > version:
            _apply(conn, migration)
            version = current_version(conn)
    return version
