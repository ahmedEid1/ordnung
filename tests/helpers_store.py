"""A migrated, empty database made once per test process and copied into each test's data folder.

Migrating a new database costs a test far more than copying one. ``tests/conftest.py`` builds the template at
the start of the session (each pytest-xdist worker its own, in its own temporary folder) with the real
``Store.open``; the ``store`` fixture and ``test_api_support.api_for`` then start a test's data folder from a copy
of it. The copy is the test's own file: nothing is shared, and the store opened on it still runs its real open
(``_make_private``, ``migrate()``, which finds nothing pending).

Tests about creating a database (migrations, the first start on an empty folder, the mode of a new file, older
or newer databases, locking) open their own folders without this and keep the real path.
"""

from __future__ import annotations

import gc
import shutil
import sqlite3
from pathlib import Path

from ordnung.config import Paths, resolve_paths
from ordnung.db.migrate import LEDGER, current_version, latest_version, pending
from ordnung.db.store import Store

#: The template database, set by ``tests/conftest.py`` for the session (``None``: no template, the real path).
TEMPLATE: Path | None = None

_SIDE_FILES = ("-wal", "-shm", "-journal")


def build_template(folder: Path) -> Path:
    """Migrate a new database in ``folder`` with the real ``Store.open``, close it and check it holds nothing
    but its schema; return its path."""
    store = Store.open(Paths(folder).ensure())
    store.close()
    del store
    gc.collect()  # the template store's per-thread finalizers run now, never inside a later test
    db = Paths(folder).db
    _check_closed(db)
    conn = sqlite3.connect(db)
    try:
        version, latest, todo = current_version(conn), latest_version(), pending(conn)
        assert version == latest and todo == [], (
            f"the template database is at version {version} with {len(todo)} pending (latest {latest})"
        )
        filled = {name: count for name, count in _row_counts(conn).items() if count and name != LEDGER}
        assert not filled, f"the template database holds rows besides its migration ledger: {filled}"
    finally:
        conn.close()
    _check_closed(db)
    return db


def seed_database(data_dir: Path | str) -> None:
    """Start the data folder ``data_dir`` from a copy of the template database, unless it already has a database
    (a test that prepared one keeps it) or there is no template."""
    paths = resolve_paths(data_dir)  # the folder build_context and the CLI would open
    if TEMPLATE is not None and not paths.db.exists():
        shutil.copyfile(TEMPLATE, paths.db)


def _check_closed(db: Path) -> None:
    """Only the closed database is there: no write-ahead log, shared memory or journal is left to copy."""
    files = {path.name for path in db.parent.iterdir() if path.is_file()}
    assert files == {db.name}, (
        f"the template folder must hold only the closed database, found {sorted(files)}"
    )
    assert not any(db.with_name(db.name + suffix).exists() for suffix in _SIDE_FILES)


def _row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Rows per table: every table and virtual table, without SQLite's own tables and the shadow tables of the
    virtual tables (FTS5 keeps its structure rows there in every new database)."""
    rows = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'").fetchall()
    virtual = [name for name, sql in rows if (sql or "").upper().startswith("CREATE VIRTUAL TABLE")]
    counted = [
        name
        for name, _sql in rows
        if not name.startswith("sqlite_") and not any(name.startswith(f"{v}_") for v in virtual)
    ]
    return {name: int(conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]) for name in counted}
