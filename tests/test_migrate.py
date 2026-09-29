from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from ordnung.db.migrate import (
    LEDGER,
    MIGRATIONS_DIR,
    Migration,
    _apply,
    applied_versions,
    current_version,
    discover,
    latest_version,
    migrate,
    pending,
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
    "proofs",
    "call_notes",
    LEDGER,
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


def test_a_lower_number_merged_after_a_higher_one_still_runs(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    """0004 reached a database first; 0003 arrives later: it runs (it is not below "the version")."""
    directory = _write(
        tmp_path / "m",
        {
            "0001_a.sql": "CREATE TABLE log (step TEXT);",
            "0004_d.sql": "INSERT INTO log (step) VALUES ('four');",
        },
    )
    assert migrate(conn, directory=directory) == 4
    _write(
        directory, {"0003_c.sql": "CREATE TABLE three (x INTEGER); INSERT INTO log (step) VALUES ('three');"}
    )
    assert [m.version for m in pending(conn, directory=directory)] == [3]
    assert migrate(conn, directory=directory) == 4
    assert [r[0] for r in conn.execute("SELECT step FROM log ORDER BY rowid")] == ["four", "three"]
    assert "three" in _tables(conn)
    assert applied_versions(conn) == {1, 3, 4}
    assert migrate(conn, directory=directory) == 4  # and never again
    assert conn.execute("SELECT COUNT(*) FROM log").fetchone() == (2,)


def test_0002_runs_on_a_database_that_already_ran_a_later_migration(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    """The shipped 0002 merged after the shipped 0003 reached a database: both run, in either order."""
    directory = tmp_path / "m"
    _shipped(directory, "0001_initial.sql", TRACE_MIGRATION)
    assert migrate(conn, directory=directory) == 3
    _shipped(directory, PROOF_MIGRATION)
    assert migrate(conn, directory=directory) == 3
    assert "tracking_number" in _columns(conn, "drafts")
    assert {"proofs", "call_notes", "trace_spans"} <= _tables(conn)
    assert applied_versions(conn) == {1, 2, 3}


def test_a_database_from_before_the_ledger_ran_0001(tmp_path: Path, conn: sqlite3.Connection) -> None:
    directory = _write(tmp_path / "m", {"0001_a.sql": "CREATE TABLE log (step TEXT);"})
    conn.execute("CREATE TABLE log (step TEXT)")  # as the old runner left it: version 1, no ledger
    conn.execute("PRAGMA user_version = 1")
    _write(directory, {"0003_c.sql": "INSERT INTO log (step) VALUES ('three');"})
    assert migrate(conn, directory=directory) == 3
    assert applied_versions(conn) == {1, 3}
    assert conn.execute(f"SELECT version, name FROM {LEDGER} ORDER BY version").fetchall() == [
        (1, "a"),
        (3, "c"),
    ]


def test_a_database_past_0001_without_a_ledger_is_refused(tmp_path: Path, conn: sqlite3.Connection) -> None:
    """A development build may have skipped a lower number: say so instead of guessing."""
    directory = _write(tmp_path / "m", {"0001_a.sql": "", "0003_c.sql": "", "0004_d.sql": ""})
    conn.execute("PRAGMA user_version = 4")
    with pytest.raises(RuntimeError, match="no record of which migrations ran"):
        migrate(conn, directory=directory)
    assert LEDGER not in _tables(conn)


def test_a_migration_this_code_does_not_have_is_refused(tmp_path: Path, conn: sqlite3.Connection) -> None:
    directory = _write(tmp_path / "m", {"0001_a.sql": "", "0002_b.sql": "", "0004_d.sql": ""})
    migrate(conn, directory=directory)
    (directory / "0002_b.sql").unlink()
    _write(directory, {"0003_c.sql": ""})
    with pytest.raises(RuntimeError, match="0002, which this version of Ordnung doesn't have"):
        migrate(conn, directory=directory)


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


# --- the shipped migrations: numbered without a gap, and every database migrates -------------------


def test_the_shipped_migrations_are_numbered_without_a_gap() -> None:
    """Numbers may be handed out ahead on branches, but what ships runs 0001, 0002, 0003, … (the
    runner's policy); the integration of wave 2 of phase 2 made proof 0002 and traces 0003."""
    found = discover(MIGRATIONS_DIR)
    assert [m.version for m in found] == list(range(1, len(found) + 1))
    assert [m.name for m in found[:4]] == ["initial", "proof_and_calls", "traces", "contract_notice_terms"]


def test_an_existing_database_at_version_1_gets_every_later_migration(conn: sqlite3.Connection) -> None:
    """A database written by the released Ordnung (0001 only, no ledger) migrates to the latest."""
    conn.executescript((MIGRATIONS_DIR / "0001_initial.sql").read_text(encoding="utf-8"))
    conn.execute("PRAGMA user_version = 1")
    now = "2026-09-01T10:00:00Z"
    conn.execute(
        "INSERT INTO drafts (id, kind, status, created_at, updated_at) VALUES ('drf_1', 'cancellation', 'draft', ?, ?)",
        (now, now),
    )
    assert migrate(conn) == latest_version()
    assert applied_versions(conn) == set(range(1, latest_version() + 1))
    assert {"proofs", "call_notes", "trace_spans"} <= _tables(conn)
    assert "request_key" in _columns(conn, "llm_calls") and "tracking_number" in _columns(conn, "drafts")
    assert conn.execute("SELECT id FROM drafts").fetchall() == [("drf_1",)]


def test_a_database_that_ran_a_migration_under_another_number_is_refused(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    """A development build ran proof as 0003 before it was renumbered 0002: running 0002 again would
    fail halfway and 0003 (traces) would be skipped — so it is refused, and nothing changes."""
    directory = tmp_path / "m"
    _shipped(directory, "0001_initial.sql")
    (directory / "0003_proof_and_calls.sql").write_text(
        (MIGRATIONS_DIR / PROOF_MIGRATION).read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert migrate(conn, directory=directory) == 3
    before = _schema(conn)
    with pytest.raises(RuntimeError, match="ran migration 0003 as “proof_and_calls”"):
        migrate(conn)
    assert _schema(conn) == before


# --- 0002: proof of sending and call notes ----------------------------------------------------------


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _shipped(directory: Path, *names: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text((MIGRATIONS_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")


PROOF_MIGRATION = "0002_proof_and_calls.sql"
TRACE_MIGRATION = "0003_traces.sql"
NOTICE_MIGRATION = "0004_contract_notice_terms.sql"
#: What 0004 adds to the contracts: the day of the month for notice, and a fixed-term job's early notice.
NEW_CONTRACT_COLUMNS = ("notice_day", "notice_before_end")
NEW_DRAFT_COLUMNS = ("tracking_number", "sent_profile", "answered_on", "answer_doc_id")
#: What 0003 (the traces) adds to the usage log.
NEW_CALL_COLUMNS = (
    "request_key",
    "prompt_name",
    "prompt_version",
    "served_model",
    "job_id",
    "stage",
    "span_id",
    "repair_of",
    "outcome",
)


def test_0002_adds_proofs_call_notes_and_the_tracking_number(conn: sqlite3.Connection) -> None:
    migrate(conn)
    assert set(NEW_DRAFT_COLUMNS) <= _columns(conn, "drafts")
    assert {"draft_id", "kind", "doc_id", "on_date", "note"} <= _columns(conn, "proofs")
    assert {"party_id", "case_id", "called_on", "promise", "promise_due", "promise_kept_on"} <= _columns(
        conn, "call_notes"
    )


@pytest.mark.parametrize(
    "second",
    [
        None,  # nothing between 0001 and it
        "CREATE TABLE inbox_watch (path TEXT);",  # a new table
        "ALTER TABLE documents ADD COLUMN held INTEGER NOT NULL DEFAULT 0;",  # a new column elsewhere
        "ALTER TABLE drafts ADD COLUMN reminder_at TEXT; CREATE INDEX drafts_status ON drafts(status);",
    ],
)
def test_0002_applies_after_any_other_migration(
    tmp_path: Path, conn: sqlite3.Connection, second: str | None
) -> None:
    """It only adds: numbered after whatever another piece of work adds (or nothing), it still applies."""
    directory = tmp_path / "m"
    _shipped(directory, "0001_initial.sql")
    (directory / "0003_proof_and_calls.sql").write_text(
        (MIGRATIONS_DIR / PROOF_MIGRATION).read_text(encoding="utf-8"), encoding="utf-8"
    )
    if second is not None:
        (directory / "0002_other.sql").write_text(second, encoding="utf-8")
    assert migrate(conn, directory=directory) == 3
    assert "tracking_number" in _columns(conn, "drafts")
    assert {"proofs", "call_notes"} <= _tables(conn)


def test_0002_keeps_existing_letters_and_deletes_proofs_with_their_letter(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    directory = tmp_path / "m"
    _shipped(directory, "0001_initial.sql")
    migrate(conn, directory=directory)
    now = "2026-09-01T10:00:00Z"
    conn.execute(
        "INSERT INTO drafts (id, kind, status, sent_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("drf_1", "cancellation", "sent", "2026-09-01", now, now),
    )
    _shipped(directory, PROOF_MIGRATION)
    migrate(conn, directory=directory)
    assert conn.execute("SELECT id, status, tracking_number FROM drafts").fetchall() == [
        ("drf_1", "sent", None)
    ]
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO proofs (id, draft_id, kind, created_at, updated_at) VALUES ('prf_1', 'drf_1', 'other', ?, ?)",
        (now, now),
    )
    conn.execute("DELETE FROM drafts WHERE id = 'drf_1'")
    assert conn.execute("SELECT COUNT(*) FROM proofs").fetchone() == (0,)


def test_0002_to_0004_migrate_the_demo_database(tmp_path: Path) -> None:
    """The shipped demo snapshot (or one built at an older version) opens and migrates with its data."""
    from ordnung.demo.loader import snapshot_dir

    source = snapshot_dir() / "ordnung.db"
    copy = tmp_path / "demo.db"
    copy.write_bytes(source.read_bytes())
    demo = sqlite3.connect(copy, isolation_level=None)
    try:
        before = demo.execute("SELECT COUNT(*) FROM documents").fetchone()
        demo.execute("PRAGMA user_version = 1")  # as it was before this migration (and the ledger)
        demo.execute(f"DROP TABLE IF EXISTS {LEDGER}")
        for column in NEW_DRAFT_COLUMNS:  # a snapshot already built at 0002: undo it
            if column in _columns(demo, "drafts"):
                demo.execute(f"ALTER TABLE drafts DROP COLUMN {column}")
        demo.execute("DROP TABLE IF EXISTS proofs")
        demo.execute("DROP TABLE IF EXISTS call_notes")
        # … and at 0003 (the traces): the spans' table, and the columns it added to the usage log
        demo.execute("DROP TABLE IF EXISTS trace_spans")
        demo.execute("DROP INDEX IF EXISTS llm_calls_span")
        for column in NEW_CALL_COLUMNS:
            if column in _columns(demo, "llm_calls"):
                demo.execute(f"ALTER TABLE llm_calls DROP COLUMN {column}")
        # … and at 0004 (the contracts' notice terms)
        for column in NEW_CONTRACT_COLUMNS:
            if column in _columns(demo, "contracts"):
                demo.execute(f"ALTER TABLE contracts DROP COLUMN {column}")
        calls = demo.execute("SELECT COUNT(*) FROM llm_calls").fetchone()
        contracts = demo.execute("SELECT COUNT(*) FROM contracts").fetchone()
        assert migrate(demo) == latest_version()
        assert demo.execute("SELECT COUNT(*) FROM documents").fetchone() == before
        assert demo.execute("SELECT COUNT(*) FROM llm_calls").fetchone() == calls
        assert set(NEW_DRAFT_COLUMNS) <= _columns(demo, "drafts")
        assert set(NEW_CALL_COLUMNS) <= _columns(demo, "llm_calls")
        assert set(NEW_CONTRACT_COLUMNS) <= _columns(demo, "contracts")
        assert demo.execute("SELECT COUNT(*) FROM contracts").fetchone() == contracts
        assert {"proofs", "call_notes", "trace_spans"} <= _tables(demo)
        assert applied_versions(demo) == set(range(1, latest_version() + 1))
    finally:
        demo.close()


# --- 0004: the notice terms a notice period can't say -------------------------------------------------


def test_0004_adds_the_notice_terms_and_existing_contracts_state_none(
    tmp_path: Path, conn: sqlite3.Connection
) -> None:
    """A contract stored before 0004 reads as "not stated": no day of the month, no early notice."""
    directory = tmp_path / "m"
    _shipped(directory, "0001_initial.sql", PROOF_MIGRATION, TRACE_MIGRATION)
    assert migrate(conn, directory=directory) == 3
    now = "2026-09-01T10:00:00Z"
    conn.execute(
        "INSERT INTO contracts (id, name, notice_basis, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("ctr_1", "Deutschlandticket", "end_of_month", now, now),
    )
    _shipped(directory, NOTICE_MIGRATION)
    assert migrate(conn, directory=directory) == 4
    rows = conn.execute("SELECT id, notice_day, notice_before_end FROM contracts").fetchall()
    assert rows == [("ctr_1", None, 0)]
    assert applied_versions(conn) == {1, 2, 3, 4}


def test_0004_applies_before_the_others(tmp_path: Path, conn: sqlite3.Connection) -> None:
    """It only adds columns to the contracts, which no other migration touches."""
    directory = tmp_path / "m"
    _shipped(directory, "0001_initial.sql", NOTICE_MIGRATION)
    assert migrate(conn, directory=directory) == 4
    _shipped(directory, PROOF_MIGRATION, TRACE_MIGRATION)
    assert migrate(conn, directory=directory) == 4
    assert set(NEW_CONTRACT_COLUMNS) <= _columns(conn, "contracts")
    assert applied_versions(conn) == {1, 2, 3, 4}
