"""``Store.ledger_token``: a change token moved only by what Ask's ledger fingerprint can read.

It moves on this connection's writes to the letters, pages, to-dos, contracts, senders, cases and the
profile (counted by temporary triggers that live in the open connection only), on any other connection's
commit and on a schema change; Ask's own writes (usage log, chat, activity, settings) leave it as it was.
Plain SQLite only, no Linux paths: meant for CI's other-systems job too, since the Pythons on macOS and
Windows bundle other SQLite builds.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from helpers_secretary import add_doc, seed_ledger
from ordnung.config import Paths
from ordnung.db.store import LEDGER_TABLES, Store
from ordnung.demo.loader import canonical_dump
from ordnung.llm.base import Usage
from ordnung.models import PaymentDetails


def _pages(store: Store, doc_id: str) -> None:
    store.set_pages(
        doc_id,
        [
            {"page": 1, "width": 595, "height": 842, "image_path": "derived/p1.png", "text": "Seite eins"},
            {"page": 2, "width": 595, "height": 842, "image_path": "derived/p2.png", "text": "Seite zwei"},
        ],
    )


def _ledger_objects(conn: sqlite3.Connection, schema: str) -> list[str]:
    rows = conn.execute(f"SELECT name FROM {schema}.sqlite_master WHERE name GLOB 'ordnung_ledger_*'")
    return sorted(row[0] for row in rows)


def test_the_watched_tables_are_what_the_fingerprint_reads_and_cases() -> None:
    assert LEDGER_TABLES == ("documents", "pages", "items", "contracts", "parties", "cases")


def test_ledger_token_stays_while_nothing_changes(store: Store) -> None:
    seed_ledger(store)
    first = store.ledger_token()
    assert first is not None
    store.list_documents()
    store.get_profile()
    assert store.ledger_token() == first == store.ledger_token()


def test_ledger_token_ignores_chat_activity_usage_and_settings(store: Store) -> None:
    seed_ledger(store)
    token, changes = store.ledger_token(), store.change_token()
    store.add_chat_message("thr_a", "user", "What is due?")
    store.add_chat_message("thr_a", "assistant", "Nothing.")
    store.log_activity("ask.checked", "Ask's answer was checked")
    store.log_llm_call(
        "ask", "test-model", "fake", Usage(input_tokens=1, output_tokens=1), request_key="ask:x"
    )
    store.set_meta("tour", "done")
    store.save_settings(store.get_settings())
    store.set_meta("last_calendar_export_at", None)
    assert store.change_token() != changes  # every one of them wrote
    assert store.ledger_token() == token


def _write_cases() -> dict[str, Callable[[Store, dict[str, str]], object]]:
    def merge(store: Store, ids: dict[str, str]) -> object:
        return store.merge_parties(ids["beitrag"], ids["fake_beitrag"])

    return {
        "update_document warning": lambda s, ids: s.update_document(
            ids["doc_invoice"], warnings=["Check the IBAN"]
        ),
        "update_document payment": lambda s, ids: s.update_document(
            ids["doc_invoice"], payment=PaymentDetails(iban="DE89370400440532013000", iban_valid=True)
        ),
        "update_document title": lambda s, ids: s.update_document(ids["doc_invoice"], title="Renamed"),
        "set_pages": lambda s, ids: _pages(s, ids["doc_invoice"]),
        "set_page_text": lambda s, ids: s.set_page_text(ids["doc_tax"], 1, "Neuer Text", "text"),
        "add_item": lambda s, ids: s.add_item(kind="task", title="A new to-do"),
        "update_item": lambda s, ids: s.update_item(ids["dunning_payment"], status="done"),
        "delete_item": lambda s, ids: s.delete_item(ids["library_task"]),
        "upsert_item_by_slot": lambda s, ids: s.upsert_item_by_slot(
            ids["doc_invoice"], "pay", kind="payment", title="Pay"
        ),
        "add_contract": lambda s, ids: s.add_contract(name="Gym", category="gym", party_id=ids["gym"]),
        "update_contract": lambda s, ids: s.update_contract(ids["phone"], cost_amount=31.99),
        "update_party identifiers": lambda s, ids: s.update_party(
            ids["funknetz"], identifiers=[{"label": "Kundennummer", "value": "FN-1"}]
        ),
        "update_party shared field": lambda s, ids: s.update_party(ids["funknetz"], phone="+49 30 123456"),
        "update_party notes": lambda s, ids: s.update_party(ids["funknetz"], notes="only the notes"),
        "merge_parties": merge,
        "save_profile": lambda s, ids: s.save_profile(
            s.get_profile().model_copy(update={"name": "Alex Rivera"})
        ),
        "trash a letter": lambda s, ids: s.trash_document(ids["doc_invoice"]),
        "delete a letter": lambda s, ids: s.delete_document(ids["doc_invoice"], purge_files=False),
    }


@pytest.mark.parametrize("write", sorted(_write_cases()))
def test_ledger_token_moves_on_every_input_write(store: Store, write: str) -> None:
    ids = seed_ledger(store)
    _pages(store, ids["doc_tax"])
    before = store.ledger_token()
    _write_cases()[write](store, ids)
    after = store.ledger_token()
    assert after is not None and after != before
    assert store.ledger_token() == after  # and stays until the next change


def test_ledger_token_moves_when_a_case_is_deleted(store: Store) -> None:
    ids = seed_ledger(store)
    case = store.add_case(title="Phone", party_id=ids["funknetz"])
    store.update_document(ids["doc_phone"], case_id=case.id)
    store.update_item(ids["followup"], case_id=case.id)
    store.update_contract(ids["phone"], case_id=case.id)
    before = store.ledger_token()
    assert store.delete_case(case.id)
    assert store.ledger_token() != before
    assert store.get_document(ids["doc_phone"]).case_id is None  # type: ignore[union-attr]


def test_ledger_token_moves_on_another_connections_commit(store: Store) -> None:
    ids = seed_ledger(store)
    before = store.ledger_token()
    with sqlite3.connect(store.db_path, isolation_level=None) as other:
        other.execute("UPDATE documents SET title = 'Changed elsewhere' WHERE id = ?", (ids["doc_tax"],))
    other.close()
    after = store.ledger_token()
    assert after != before

    worker = threading.Thread(target=lambda: store.update_item(ids["dunning_payment"], status="done"))
    worker.start()
    worker.join()
    assert store.ledger_token() != after


def test_ledger_token_ignores_a_rolled_back_write(store: Store) -> None:
    ids = seed_ledger(store)
    before = store.ledger_token()

    class Rollback(Exception):
        pass

    with pytest.raises(Rollback), store.tx():
        store.update_document(ids["doc_tax"], title="Never committed")
        raise Rollback
    assert store.ledger_token() == before


def test_ledger_token_is_none_inside_a_transaction(store: Store) -> None:
    seed_ledger(store)
    assert store.ledger_token() is not None
    with store.tx():
        assert store.ledger_token() is None
    with store.snapshot():
        assert store.ledger_token() is None
    assert store.ledger_token() is not None


def test_ledger_token_survives_delete_everything(store: Store) -> None:
    seed_ledger(store)
    elsewhere: list[tuple[int, int, int] | None] = []
    ready, wiped, done = threading.Event(), threading.Event(), threading.Event()

    def other_thread() -> None:
        elsewhere.append(store.ledger_token())
        ready.set()
        wiped.wait(10)
        elsewhere.append(store.ledger_token())
        store.save_profile({"name": "Other thread"})
        elsewhere.append(store.ledger_token())
        done.set()

    worker = threading.Thread(target=other_thread)
    worker.start()
    ready.wait(10)
    before = store.ledger_token()
    store.wipe()
    wiped_token = store.ledger_token()
    assert wiped_token is not None and wiped_token != before
    ids = seed_ledger(store)
    seeded = store.ledger_token()
    assert seeded != wiped_token
    store.update_item(ids["dunning_payment"], status="done")
    assert store.ledger_token() != seeded
    wiped.set()
    done.wait(10)
    worker.join()
    first, after_wipe, after_write = elsewhere
    assert first != after_wipe != after_write  # the other connection's watch keeps counting


def test_ledger_token_reinstalls_a_watch_that_went_missing(store: Store) -> None:
    ids = seed_ledger(store)
    before = store.ledger_token()
    conn = store._conn()
    conn.execute("DROP TRIGGER temp.ordnung_ledger_items_update")
    store.update_item(ids["dunning_payment"], status="done")  # not counted: its trigger is gone
    after = store.ledger_token()
    assert after != before  # a reinstalled watch moves the token by itself
    assert "ordnung_ledger_items_update" in _ledger_objects(conn, "temp")
    store.update_item(ids["dunning_payment"], status="open")
    assert store.ledger_token() != after


def test_ledger_token_leaves_the_database_file_alone(paths: Paths, tmp_path: Path) -> None:
    with Store.open(paths) as store:
        ids = seed_ledger(store)
        schema = store._conn().execute("PRAGMA schema_version").fetchone()[0]
    dump = canonical_dump(paths.db)
    with Store.open(paths) as store:
        assert store.ledger_token() is not None
        store.update_item(ids["dunning_payment"], status="done")
        store.update_item(ids["dunning_payment"], status="open")
        assert _ledger_objects(store._conn(), "temp")
    with sqlite3.connect(paths.db) as fresh:
        assert _ledger_objects(fresh, "main") == []
        assert fresh.execute("PRAGMA schema_version").fetchone()[0] == schema
    fresh.close()
    assert canonical_dump(paths.db) == dump


def test_ledger_token_first_read_is_not_a_write(store: Store) -> None:
    seed_ledger(store)
    conn = store._conn()
    token, changes = store.change_token(), conn.total_changes
    assert store.ledger_token() is not None
    assert store.change_token() == token
    assert conn.total_changes == changes


def test_ledger_token_of_a_read_only_store(paths: Paths) -> None:
    with Store.open(paths) as writer:
        ids = seed_ledger(writer)
        with Store.open(paths, read_only=True) as reader:
            before = reader.ledger_token()
            assert before is not None and reader.ledger_token() == before
            writer.update_item(ids["dunning_payment"], status="done")
            assert reader.ledger_token() != before


def test_a_new_letter_moves_the_token(store: Store) -> None:
    seed_ledger(store)
    before = store.ledger_token()
    add_doc(store, "new-letter", title="A new letter")
    assert store.ledger_token() != before
