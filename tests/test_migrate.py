from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from ordnung.db.migrate import (
    MIGRATIONS_DIR,
    Migration,
    _apply,
    current_version,
    discover,
    latest_version,
    migrate,
    split_statements,
)

EXPECTED_TABLES = {
    "meta",
    "parties",
    "cases",
    "documents",
    "documents_fts",
    "documents_trigram",
    "pages",
    "contracts",
    "items",
    "suggestions",
    "drafts",
    "notes",
    "activity",
    "llm_calls",
    "llm_cache",
    "jobs",
    "chat_messages",
}


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(tmp_path / "test.db", isolation_level=None)
    yield connection
    connection.close()


def _schema(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _write(directory: Path, files: dict[str, str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, sql in files.items():
        (directory / name).write_text(sql, encoding="utf-8")
    return directory


# --- the shipped schema ----------------------------------------------------------------------------


def test_fresh_database_gets_the_whole_schema(conn: sqlite3.Connection) -> None:
    assert current_version(conn) == 0
    assert migrate(conn) == latest_version()
    assert current_version(conn) == latest_version()
    assert EXPECTED_TABLES <= _tables(conn)


def test_migrate_is_idempotent(conn: sqlite3.Connection) -> None:
    migrate(conn)
    before = _schema(conn)
    conn.execute("INSERT INTO meta (key, value) VALUES ('k', 'v')")
    assert migrate(conn) == latest_version()
    assert migrate(conn) == latest_version()
    assert _schema(conn) == before
    assert conn.execute("SELECT value FROM meta WHERE key = 'k'").fetchone() == ("v",)


def test_shipped_migrations_are_discovered() -> None:
    found = discover(MIGRATIONS_DIR)
    versions = [m.version for m in found]
    assert versions == sorted(set(versions)) and versions[0] == 1
    assert found[0] == Migration(1, "initial", MIGRATIONS_DIR / "0001_initial.sql")
    assert latest_version() == found[-1].version


def test_refuses_to_run_inside_a_transaction(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN")
    with pytest.raises(RuntimeError, match="transaction"):
        migrate(conn)
    conn.execute("ROLLBACK")


def test_refuses_a_database_from_a_newer_version(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA user_version = 99")
    with pytest.raises(RuntimeError, match="newer"):
        migrate(conn)


# --- custom migration directories -------------------------------------------------------------------


def test_applies_pending_migrations_in_order(tmp_path: Path, conn: sqlite3.Connection) -> None:
    directory = _write(
        tmp_path / "m",
        {
            "0002_add_log.sql": "INSERT INTO log (step) VALUES ('two');",
            "0001_create.sql": "CREATE TABLE log (step TEXT); INSERT INTO log (step) VALUES ('one');",
        },
    )
    assert migrate(conn, directory=directory) == 2
    assert [r[0] for r in conn.execute("SELECT step FROM log ORDER BY rowid")] == ["one", "two"]

    _write(directory, {"0003_more.sql": "INSERT INTO log (step) VALUES ('three');"})
    assert migrate(conn, directory=directory) == 3
    # 0001 and 0002 were not re-run
    assert [r[0] for r in conn.execute("SELECT step FROM log ORDER BY rowid")] == ["one", "two", "three"]


def test_failed_migration_rolls_back_completely(tmp_path: Path, conn: sqlite3.Connection) -> None:
    directory = _write(
        tmp_path / "m",
        {
            "0001_ok.sql": "CREATE TABLE a (x INTEGER);",
            "0002_broken.sql": "CREATE TABLE b (y INTEGER);\nINSERT INTO a (x) VALUES (1);\nNOT VALID SQL;",
        },
    )
    with pytest.raises(sqlite3.OperationalError):
        migrate(conn, directory=directory)
    assert current_version(conn) == 1
    assert "b" not in _tables(conn)
    assert conn.execute("SELECT COUNT(*) FROM a").fetchone() == (0,)
    assert not conn.in_transaction


def test_migration_already_applied_by_someone_else_is_skipped(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    directory = _write(tmp_path / "m", {"0001_create.sql": "CREATE TABLE t (x INTEGER);"})
    migrate(conn, directory=directory)
    # a racing process sees version 0 before its transaction, 1 inside it: the script must not re-run
    _apply(conn, discover(directory)[0])
    assert current_version(conn) == 1


def test_empty_directory_means_version_zero(tmp_path: Path, conn: sqlite3.Connection) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert migrate(conn, directory=empty) == 0
    assert latest_version(empty) == 0


@pytest.mark.parametrize(
    "files",
    [
        {"0002_b.sql": ""},  # does not start at 1
        {"0001_a.sql": "", "0001_b.sql": ""},  # duplicate
        {"0001_a.sql": "", "0003_c.sql": "", "0003_d.sql": ""},  # duplicate after a gap
        {"1_a.sql": ""},  # bad name
        {"0001_Bad-Name.sql": ""},  # bad name
    ],
)
def test_discover_rejects_bad_numbering(tmp_path: Path, files: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        discover(_write(tmp_path / "m", files))


def test_a_gap_in_the_numbering_is_allowed(tmp_path: Path, conn: sqlite3.Connection) -> None:
    """Numbers are handed out per piece of work: 0003 may be merged before (or without) 0002."""
    directory = _write(
        tmp_path / "m",
        {
            "0001_a.sql": "CREATE TABLE log (step TEXT);",
            "0003_c.sql": "INSERT INTO log (step) VALUES ('three');",
        },
    )
    assert [m.version for m in discover(directory)] == [1, 3]
    assert migrate(conn, directory=directory) == 3
    assert conn.execute("SELECT step FROM log").fetchall() == [("three",)]


def test_discover_ignores_non_sql_files(tmp_path: Path) -> None:
    directory = _write(tmp_path / "m", {"0001_a.sql": "SELECT 1;", "README.md": "notes"})
    assert [m.name for m in discover(directory)] == ["a"]


def test_trigger_migration_runs(tmp_path: Path, conn: sqlite3.Connection) -> None:
    directory = _write(
        tmp_path / "m",
        {
            "0001_trigger.sql": """
                CREATE TABLE src (x INTEGER);
                CREATE TABLE audit (x INTEGER, note TEXT);
                CREATE TRIGGER src_audit AFTER INSERT ON src BEGIN
                  INSERT INTO audit (x, note) VALUES (new.x, 'a; b');
                  INSERT INTO audit (x, note) VALUES (new.x * 10, 'c');
                END;
            """
        },
    )
    migrate(conn, directory=directory)
    conn.execute("INSERT INTO src (x) VALUES (2)")
    assert conn.execute("SELECT x, note FROM audit ORDER BY x").fetchall() == [(2, "a; b"), (20, "c")]


# --- statement splitting ---------------------------------------------------------------------------


def test_split_statements_respects_strings_comments_and_triggers() -> None:
    script = """
    -- a comment; with a semicolon
    CREATE TABLE t (x TEXT DEFAULT 'a;b');  /* block; comment */
    INSERT INTO t (x) VALUES ('1;2'); INSERT INTO t (x) VALUES ('3');
    CREATE TRIGGER tr AFTER INSERT ON t BEGIN UPDATE t SET x = 'y;'; END;
    -- trailing comment
    """
    statements = split_statements(script)
    assert len(statements) == 4
    assert statements[0].endswith("DEFAULT 'a;b');")
    assert "block; comment" in statements[1]  # leading comment travels with the next statement
    assert statements[2] == "INSERT INTO t (x) VALUES ('3');"
    assert statements[3].startswith("CREATE TRIGGER") and statements[3].endswith("END;")


def test_split_statements_rejects_incomplete_tail() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        split_statements("CREATE TABLE t (x INTEGER); SELECT 1")


def test_split_statements_of_empty_script() -> None:
    assert split_statements("") == []
    assert split_statements("  -- nothing here\n /* at all */ ") == []
