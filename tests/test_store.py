from __future__ import annotations

import hashlib
import inspect
import random
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import ValidationError

from ordnung.config import Paths
from ordnung.db import store as store_module
from ordnung.db.migrate import latest_version
from ordnung.db.store import NotFoundError, Store, normalize_identifier, search_tokens
from ordnung.ids import PREFIXES, content_id, doc_id_for_sha, new_id, prefix_of
from ordnung.llm.base import LLMRequest, Usage
from ordnung.llm.fake import FakeBackend
from ordnung.llm.runtime import LLMService, UsageSink
from ordnung.models import (
    AppSettings,
    ComputationReceipt,
    ComputationStep,
    ContractComputation,
    DateSpec,
    Document,
    DocumentExtraction,
    DraftCheck,
    Evidence,
    Identifier,
    KeyFact,
    PaymentDetails,
    Profile,
    Recurrence,
    Remedy,
    SendChannel,
    SendGuidance,
    Suggestion,
    SuggestionAction,
    SuggestionRef,
)

T = TypeVar("T")

# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------


class Clock:
    """Deterministic ``now_iso`` replacement: every call is one second later."""

    def __init__(self) -> None:
        self.moment = datetime(2026, 9, 1, 8, 0, 0, tzinfo=UTC)

    def __call__(self) -> str:
        self.moment += timedelta(seconds=1)
        return self.moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    ticking = Clock()
    monkeypatch.setattr(store_module, "now_iso", ticking)
    return ticking


def must(value: T | None) -> T:
    assert value is not None
    return value


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def add_doc(
    store: Store, content: bytes = b"letter", *, filename: str = "letter.pdf", **fields: Any
) -> Document:
    """Add a document with a real original under files/ (and optional updates)."""
    digest = sha(content)
    relative = Path("files") / digest[:2] / f"{digest}.pdf"
    target = store.data_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    document = store.add_document(
        sha256=digest, filename=filename, mime="application/pdf", file_path=relative
    )
    return store.update_document(document.id, **fields) if fields else document


def page(n: int, text: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "page": n,
        "width": 1240,
        "height": 1754,
        "image_path": f"derived/p{n}.jpg",
        "text": text,
        **extra,
    }


def add_text_doc(store: Store, text: str, **fields: Any) -> Document:
    document = add_doc(store, text.encode(), **fields)
    store.set_pages(document.id, [page(1, text, text_source="text")])
    return document


def raw(store: Store, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in store._conn().execute(sql, params).fetchall()]


def item_fields(**overrides: Any) -> dict[str, Any]:
    return {"kind": "deadline", "title": "Pay the invoice", **overrides}


def evidence(doc_id: str = "doc_x", quote: str = "zahlbar bis 15.10.2026") -> Evidence:
    return Evidence(doc_id=doc_id, page=1, quote=quote, grounding="verified", score=97.5)


def run_threads(count: int, target: Callable[[int], None]) -> list[BaseException]:
    errors: list[BaseException] = []
    barrier = threading.Barrier(count)

    def runner(index: int) -> None:
        try:
            barrier.wait()
            target(index)
        except BaseException as exc:  # collected and asserted by the test
            errors.append(exc)

    threads = [threading.Thread(target=runner, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


# --------------------------------------------------------------------------------------------------
# deterministic ids
# --------------------------------------------------------------------------------------------------


def test_content_id_is_deterministic_and_well_formed() -> None:
    first = content_id("itm", "doc_abc", "deadline|zahlbar bis")
    assert first == content_id("itm", "doc_abc", "deadline|zahlbar bis")
    assert first != content_id("itm", "doc_abc", "deadline|other")
    prefix, body = first.split("_")
    assert prefix == "itm" and len(body) == 12
    assert set(body) <= set("0123456789abcdefghjkmnpqrstvwxyz")


def test_content_id_matches_the_spec_formula() -> None:
    digest = hashlib.sha1(b"a|b").digest()
    bits = bin(int.from_bytes(digest, "big"))[2:].zfill(160)[:60]
    alphabet = "0123456789abcdefghjkmnpqrstvwxyz"
    expected = "".join(alphabet[int(bits[i : i + 5], 2)] for i in range(0, 60, 5))
    assert content_id("sug", "a", "b") == f"sug_{expected}"


def test_doc_id_for_sha() -> None:
    digest = sha(b"file bytes")
    doc_id = doc_id_for_sha(digest)
    assert doc_id.startswith("doc_") and len(doc_id) == 16
    assert doc_id == doc_id_for_sha(digest.upper())
    with pytest.raises(ValueError):
        doc_id_for_sha("not-hex")
    with pytest.raises(ValueError):
        doc_id_for_sha("abcd")


def test_id_prefixes_are_checked() -> None:
    with pytest.raises(ValueError):
        content_id("xyz", "a")
    with pytest.raises(ValueError):
        new_id("xyz")
    assert all(new_id(prefix).startswith(prefix + "_") for prefix in PREFIXES)
    assert prefix_of(content_id("ctr", "x")) == "ctr"


# --------------------------------------------------------------------------------------------------
# opening, connections, transactions
# --------------------------------------------------------------------------------------------------


def test_open_creates_layout_migrates_and_sets_pragmas(tmp_path: Path) -> None:
    paths = Paths(tmp_path / "fresh")
    with Store.open(paths) as opened:
        assert paths.db.exists() and paths.derived.is_dir() and paths.files.is_dir()
        assert opened.schema_version == latest_version()
        conn = opened._conn()
        assert conn.isolation_level is None
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL


def test_store_from_a_db_path_uses_its_folder_as_data_dir(tmp_path: Path) -> None:
    with Store(tmp_path / "nested" / "x.db") as opened:
        assert opened.data_dir == tmp_path / "nested"
        opened.set_meta("k", "v")
    with Store(tmp_path / "nested" / "x.db") as reopened:
        assert reopened.get_meta("k") == "v"


def test_close_closes_every_threads_connection(store: Store) -> None:
    connections: list[sqlite3.Connection] = []
    errors = run_threads(3, lambda _: connections.append(store._conn()))
    assert not errors and len({id(c) for c in connections}) == 3
    store.close()
    with pytest.raises(RuntimeError, match="closed"):
        store.get_meta("x")
    for conn in connections:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_one_connection_per_thread(store: Store) -> None:
    assert store._conn() is store._conn()
    other: list[sqlite3.Connection] = []
    run_threads(1, lambda _: other.append(store._conn()))
    assert other[0] is not store._conn()


def test_tx_commits(store: Store) -> None:
    with store.tx() as conn:
        assert conn.in_transaction
        store.set_meta("a", "1")
        store.add_party(name="Stadtwerke Musterstadt")
    assert store.get_meta("a") == "1"
    assert len(store.list_parties()) == 1


def test_tx_rolls_back_on_exception(store: Store) -> None:
    with pytest.raises(RuntimeError, match="boom"), store.tx():
        store.set_meta("a", "1")
        store.add_party(name="Muster Mobil")
        raise RuntimeError("boom")
    assert store.get_meta("a") is None
    assert store.list_parties() == []
    assert not store._conn().in_transaction


def test_nested_tx_joins_the_outer_transaction(store: Store) -> None:
    with pytest.raises(KeyError), store.tx():
        with store.tx():
            store.set_meta("inner", "1")
        assert store.get_meta("inner") == "1"  # visible inside the outer transaction
        raise KeyError("outer fails")
    assert store.get_meta("inner") is None  # the inner block was part of the outer transaction


def test_failed_nested_tx_undoes_only_its_own_writes(store: Store) -> None:
    with store.tx():
        store.set_meta("outer", "1")
        with pytest.raises(ValueError), store.tx():
            store.set_meta("inner", "1")
            raise ValueError("inner fails")
        store.set_meta("after", "1")
    assert store.get_meta("outer") == "1"
    assert store.get_meta("inner") is None
    assert store.get_meta("after") == "1"


def test_failed_write_inside_caller_tx_leaves_no_partial_row(store: Store) -> None:
    party = store.add_party(name="Muster Bank")
    with store.tx():
        with pytest.raises(ValidationError):
            store.update_party(party.id, kind="not-a-kind")
        store.update_party(party.id, email="info@musterbank.example")
    reloaded = store.get_party(party.id)
    assert reloaded is not None and reloaded.kind == "other" and reloaded.email == "info@musterbank.example"


def test_uncommitted_writes_are_invisible_to_other_threads(store: Store) -> None:
    seen: list[str | None] = []
    with store.tx():
        store.set_meta("pending", "yes")
        run_threads(1, lambda _: seen.append(store.get_meta("pending")))
    run_threads(1, lambda _: seen.append(store.get_meta("pending")))
    assert seen == [None, "yes"]


def test_read_only_store_reads_but_never_writes(store: Store, paths: Paths) -> None:
    document = add_text_doc(store, "Einkommensteuerbescheid 2025")
    with Store.open(paths, read_only=True) as reader:
        assert reader.read_only and reader.schema_version == latest_version()
        assert [h.doc_id for h in reader.search("steuerbescheid")] == [document.id]
        assert [d.id for d in reader.list_documents()] == [document.id]
        assert reader.get_profile() == Profile()
        with pytest.raises(PermissionError):
            reader.set_meta("k", "v")
        with pytest.raises(PermissionError):
            reader.add_party(name="x")
        with pytest.raises(sqlite3.OperationalError):
            reader._conn().execute("DELETE FROM documents")
        store.set_meta("written", "later")  # the writer keeps working; the reader sees commits
        assert reader.get_meta("written") == "later"
    assert store.get_document(document.id) is not None


def test_read_only_store_needs_an_existing_current_database(tmp_path: Path) -> None:
    with pytest.raises(sqlite3.OperationalError):
        Store(tmp_path / "missing.db", read_only=True)
    assert not (tmp_path / "missing.db").exists()
    sqlite3.connect(tmp_path / "old.db").close()  # an empty file at schema version 0
    with pytest.raises(RuntimeError, match="version 0"):
        Store(tmp_path / "old.db", read_only=True)


def test_opening_a_newer_database_fails_cleanly(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "future.db")
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(RuntimeError, match="newer"):
        Store(tmp_path / "future.db")


# --------------------------------------------------------------------------------------------------
# meta / profile / settings
# --------------------------------------------------------------------------------------------------


def test_meta_set_overwrite_and_delete(store: Store) -> None:
    assert store.get_meta("simulated_today") is None
    store.set_meta("simulated_today", "2026-09-28")
    store.set_meta("simulated_today", "2026-09-29")
    assert store.get_meta("simulated_today") == "2026-09-29"
    store.set_meta("simulated_today", None)
    assert store.get_meta("simulated_today") is None


def test_profile_defaults_and_round_trip(store: Store) -> None:
    assert store.get_profile() == Profile()
    saved = store.save_profile(Profile(name="Sam Rivera", region="BY", reminder_days={"deadline": [5]}))
    assert store.get_profile() == saved
    assert store.save_profile({"name": "Sam", "onboarded": True}).onboarded is True
    assert store.get_profile().name == "Sam"


def test_settings_defaults_and_round_trip(store: Store) -> None:
    assert store.get_settings() == AppSettings()
    settings = AppSettings(concurrency=4, demo=True, simulated_today="2026-09-28")
    settings.models.extract = "opus"
    store.save_settings(settings)
    loaded = store.get_settings()
    assert loaded == settings and loaded.models.extract == "opus"


# --------------------------------------------------------------------------------------------------
# documents
# --------------------------------------------------------------------------------------------------


def test_add_document_uses_the_content_id(store: Store) -> None:
    document = add_doc(store, b"steuerbescheid")
    assert document.id == doc_id_for_sha(sha(b"steuerbescheid"))
    assert document.status == "queued" and document.pages == 1 and document.deleted_at is None
    assert store.get_document(document.id) == document
    assert store.get_document_by_sha(document.sha256) == document
    assert store.get_document("doc_missing") is None
    assert store.get_document_by_sha("0" * 64) is None


def test_add_document_with_explicit_id_and_options(store: Store) -> None:
    document = store.add_document(
        id="doc_manual000001",
        sha256=sha(b"x"),
        filename="note.txt",
        mime="text/plain",
        file_path="/abs/elsewhere/note.txt",
        pages=3,
        source="capture",
        direction="note",
        received_date="2026-09-20",
        status="processed",
        ai_private=True,
    )
    stored = store.get_document("doc_manual000001")
    assert stored == document
    assert (stored.pages, stored.source, stored.direction, stored.ai_private) == (3, "capture", "note", True)
    assert store.get_document_file(document.id) == Path("/abs/elsewhere/note.txt")


def test_duplicate_sha_is_rejected(store: Store) -> None:
    add_doc(store, b"same")
    with pytest.raises(sqlite3.IntegrityError):
        store.add_document(id="doc_other", sha256=sha(b"same"), filename="b", mime="x", file_path="b")


def test_get_document_file_resolves_relative_paths(store: Store) -> None:
    document = add_doc(store, b"abc")
    path = store.get_document_file(document.id)
    assert path is not None and path.is_absolute() and path.read_bytes() == b"abc"
    assert store.get_document_file("doc_missing") is None


def test_update_document_round_trips_nested_json(store: Store, clock: Clock) -> None:
    document = add_doc(store)
    remedy = Remedy(type="einspruch", addressee="Finanzamt Musterstadt", period_text="innerhalb eines Monats")
    updated = store.update_document(
        document.id,
        kind="tax_assessment",
        title="Einkommensteuerbescheid 2025",
        doc_date=date(2026, 9, 15),
        key_facts=[KeyFact(label="Amount", value="1.234,56 €", evidence=evidence(document.id))],
        references=[{"label": "Steuernummer", "value": "123/456/78901"}],
        warnings=["Hidden text found"],
        tags=["tax"],
        remedy=remedy,
        payment={"iban": "DE89370400440532013000", "payee": "Finanzamt", "iban_valid": True},
        tax_relevant=True,
        hidden_text=True,
    )
    loaded = store.get_document(document.id)
    assert loaded == updated
    assert loaded.doc_date == "2026-09-15"
    assert loaded.remedy == remedy
    assert loaded.payment == PaymentDetails(iban="DE89370400440532013000", payee="Finanzamt", iban_valid=True)
    assert loaded.key_facts[0].evidence == evidence(document.id)
    assert loaded.references == [Identifier(label="Steuernummer", value="123/456/78901")]
    assert loaded.updated_at > document.updated_at
    # model field ``references`` lives in column ``refs``; booleans are stored as 0/1
    (refs, tax_relevant, hidden_text, ai_private) = raw(
        store, "SELECT refs, tax_relevant, hidden_text, ai_private FROM documents WHERE id = ?", document.id
    )[0]
    assert "123/456/78901" in refs
    assert (tax_relevant, hidden_text, ai_private) == (1, 1, 0)


def test_update_document_rejects_unknown_and_read_only_fields(store: Store) -> None:
    document = add_doc(store)
    for bad in ({"colour": "red"}, {"created_at": "x"}, {"updated_at": "x"}, {"sha256": "x", "size": 1}):
        with pytest.raises(ValueError, match="unknown or read-only"):
            store.update_document(document.id, **bad)
    with pytest.raises(NotFoundError):
        store.update_document("doc_missing", title="x")


def test_invalid_values_are_rejected_before_writing(store: Store) -> None:
    document = add_doc(store)
    with pytest.raises(ValidationError):
        store.update_document(document.id, status="lost")
    with pytest.raises(ValidationError):
        store.update_document(document.id, remedy={"type": "appeal-to-the-king"})
    assert store.get_document(document.id) == document


def test_noop_update_keeps_updated_at(store: Store, clock: Clock) -> None:
    document = add_doc(store, title="Rechnung")
    again = store.update_document(document.id, title="Rechnung")
    assert again.updated_at == document.updated_at
    assert store.update_document(document.id) == document


def test_extraction_round_trip(store: Store) -> None:
    document = add_doc(store)
    assert store.get_extraction(document.id) is None
    assert store.get_extraction("doc_missing") is None
    extraction = {
        "kind": "invoice",
        "title": "Stromrechnung",
        "summary": "Electricity bill",
        "explanation": "Pay by 15 Oct",
        "items": [
            {
                "kind": "payment",
                "title": "Pay",
                "date": {"type": "fixed", "date": "2026-10-15", "nature": "payment"},
                "quote": "zahlbar bis 15.10.2026",
            }
        ],
    }
    store.update_document(document.id, extraction=extraction, text="all text", file_path="files/moved.pdf")
    loaded = store.get_extraction(document.id)
    assert isinstance(loaded, DocumentExtraction)
    assert loaded.items[0].date == DateSpec(type="fixed", date="2026-10-15", nature="payment")
    assert store.get_document_file(document.id) == store.data_dir / "files" / "moved.pdf"
    with pytest.raises(ValidationError):
        store.update_document(document.id, extraction={"kind": "invoice"})  # missing required fields
    store.update_document(document.id, extraction=None)
    assert store.get_extraction(document.id) is None


def test_list_documents_filters_and_order(store: Store, clock: Clock) -> None:
    party = store.add_party(name="Finanzamt Musterstadt", kind="tax_office")
    case = store.add_case(title="Steuer 2025")
    old = add_doc(store, b"1", kind="invoice", doc_date="2026-01-10", status="processed")
    new = add_doc(
        store, b"2", kind="tax_assessment", doc_date="2026-09-15", party_id=party.id, case_id=case.id
    )
    undated = add_doc(
        store, b"3", kind="contract", status="needs_review", direction="outgoing", ai_private=True
    )
    # undated falls back to created_at (2026-09-01T08:...), which sorts before 2026-09-15
    assert [d.id for d in store.list_documents()] == [new.id, undated.id, old.id]
    assert [d.id for d in store.list_documents(kind="invoice")] == [old.id]
    assert [d.id for d in store.list_documents(kind=["invoice", "contract"])] == [undated.id, old.id]
    assert store.list_documents(kind=[]) == []
    assert [d.id for d in store.list_documents(party_id=party.id)] == [new.id]
    assert [d.id for d in store.list_documents(case_id=case.id)] == [new.id]
    assert [d.id for d in store.list_documents(status="needs_review")] == [undated.id]
    assert [d.id for d in store.list_documents(direction="outgoing")] == [undated.id]
    assert [d.id for d in store.list_documents(ai_private=True)] == [undated.id]
    assert [d.id for d in store.list_documents(limit=1, offset=1)] == [undated.id]
    assert [d.id for d in store.list_documents(offset=2)] == [old.id]


def test_list_documents_text_query(store: Store) -> None:
    tax = add_text_doc(store, "Einkommensteuerbescheid für 2025", title="Bescheid")
    add_text_doc(store, "Stromrechnung September", title="Rechnung")
    assert [d.id for d in store.list_documents(q="steuerbescheid")] == [tax.id]
    assert [d.id for d in store.list_documents(q="Bescheid")] == [tax.id]
    assert len(store.list_documents(q="   ")) == 2
    assert store.list_documents(q='"( *') == []


def test_trash_and_restore(store: Store, clock: Clock) -> None:
    document = add_text_doc(store, "Kündigung des Handyvertrags")
    store.add_item(**item_fields(doc_id=document.id, due_date="2026-10-01"))
    trashed = store.trash_document(document.id)
    assert trashed.deleted_at is not None
    assert store.list_documents() == []
    assert [d.id for d in store.list_documents(include_deleted=True)] == [document.id]
    assert store.search("Kündigung") == []
    assert store.list_items() == []
    assert store.get_document(document.id) is not None  # still retrievable directly
    counts = store.counts()
    assert (counts["documents"], counts["trashed_documents"], counts["items"]) == (0, 1, 0)

    restored = store.restore_document(document.id)
    assert restored.deleted_at is None
    assert [h.doc_id for h in store.search("Kündigung")] == [document.id]
    assert len(store.list_items()) == 1
    with pytest.raises(NotFoundError):
        store.trash_document("doc_missing")


def test_delete_document_purges_everything(store: Store) -> None:
    document = add_text_doc(store, "Einkommensteuerbescheid", title="Bescheid")
    keep = add_text_doc(store, "Stromrechnung", title="Rechnung")
    derived = store.paths.derived / document.id
    derived.mkdir(parents=True)
    (derived / "page-1.jpg").write_bytes(b"jpeg")
    original = store.get_document_file(document.id)
    assert original is not None and original.exists()

    store.add_item(**item_fields(doc_id=document.id))
    store.upsert_item_by_slot(document.id, "slot-1", kind="payment", title="Pay")
    store.enqueue_job("ingest", document.id)
    contract = store.add_contract(name="Mobile", source_doc_id=document.id)
    draft = store.add_draft(kind="objection", doc_id=document.id)
    for key, tag in (("k1", document.id), ("k2", document.sha256), ("k3", keep.id), ("k4", None)):
        store.cache_put(key, "extract", "sonnet", {"text": key}, doc_sha=tag)

    assert store.delete_document(document.id) is True

    assert store.get_document(document.id) is None
    assert not original.exists() and not derived.exists()
    assert store.list_pages(document.id) == []
    assert store.list_items(doc_id=document.id) == []
    assert store.list_jobs() == []
    assert raw(store, "SELECT COUNT(*) FROM documents_fts WHERE doc_id = ?", document.id) == [(0,)]
    assert raw(store, "SELECT COUNT(*) FROM documents_trigram WHERE doc_id = ?", document.id) == [(0,)]
    assert store.cache_get("k1") is None and store.cache_get("k2") is None
    assert store.cache_get("k3") is not None and store.cache_get("k4") is not None
    assert store.search("steuerbescheid") == []
    # linked rows survive, unlinked
    assert must(store.get_contract(contract.id)).source_doc_id is None
    assert must(store.get_draft(draft.id)).doc_id is None
    # the other document is untouched
    assert [h.doc_id for h in store.search("Stromrechnung")] == [keep.id]
    assert must(store.get_document_file(keep.id)).exists()
    assert store.delete_document(document.id) is False


def test_delete_document_keeps_files_until_commit_and_on_rollback(store: Store) -> None:
    document = add_doc(store, b"precious")
    original = store.get_document_file(document.id)
    assert original is not None
    with pytest.raises(RuntimeError), store.tx():
        store.delete_document(document.id)
        assert original.exists()  # purge waits for the commit
        raise RuntimeError("abort")
    assert original.exists() and store.get_document(document.id) is not None


def test_delete_document_never_touches_files_outside_the_data_dir(store: Store, tmp_path: Path) -> None:
    outside = tmp_path / "Downloads" / "letter.pdf"
    outside.parent.mkdir()
    outside.write_bytes(b"user file")
    document = store.add_document(
        sha256=sha(b"user file"), filename="letter.pdf", mime="x", file_path=outside
    )
    store.delete_document(document.id)
    assert outside.exists()

    database_as_original = store.add_document(
        sha256=sha(b"db"), filename="db", mime="x", file_path="ordnung.db"
    )
    store.delete_document(database_as_original.id)
    assert store.db_path.exists()


def test_delete_document_without_purging_files(store: Store) -> None:
    document = add_doc(store, b"keep the file")
    original = store.get_document_file(document.id)
    assert store.delete_document(document.id, purge_files=False) is True
    assert original is not None and original.exists()


def test_file_purge_errors_are_logged_not_raised(
    store: Store, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    document = add_doc(store, b"locked")
    (store.paths.derived / document.id).mkdir(parents=True)

    def refuse(path: Path) -> None:
        raise PermissionError(f"busy: {path}")

    monkeypatch.setattr(store_module.shutil, "rmtree", refuse)
    assert store.delete_document(document.id) is True
    assert store.get_document(document.id) is None  # the database purge stands
    assert "could not remove the files" in caplog.text


# --------------------------------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------------------------------


def test_set_pages_replaces_and_round_trips(store: Store) -> None:
    document = add_doc(store)
    words = [("Sehr", 0.1, 0.1, 0.15, 0.12), ("geehrte", 0.16, 0.1, 0.25, 0.12)]
    stored = store.set_pages(
        document.id,
        [page(2, "Seite zwei", text_source="text"), page(1, "Sehr geehrte", words=words, hidden="secret")],
    )
    assert [p.page for p in stored] == [1, 2]
    pages = store.list_pages(document.id)
    assert pages == stored
    assert pages[0].words == words and pages[0].hidden == "secret" and pages[0].doc_id == document.id
    assert must(store.get_page(document.id, 2)).text == "Seite zwei"
    assert store.get_page(document.id, 9) is None

    store.set_pages(document.id, [page(1, "neu")])
    assert [(p.page, p.text) for p in store.list_pages(document.id)] == [(1, "neu")]
    store.set_pages(document.id, [])
    assert store.list_pages(document.id) == []


def test_set_pages_validation(store: Store) -> None:
    document = add_doc(store)
    with pytest.raises(NotFoundError):
        store.set_pages("doc_missing", [page(1)])
    with pytest.raises(ValueError, match="duplicate"):
        store.set_pages(document.id, [page(1), page(1)])
    with pytest.raises(ValueError, match="unknown"):
        store.set_pages(document.id, [page(1, colour="red")])
    with pytest.raises(ValueError, match="belongs to"):
        store.set_pages(document.id, [page(1, doc_id="doc_other")])
    with pytest.raises(ValidationError):
        store.set_pages(document.id, [{"page": 1}])


def test_set_page_text_and_document_text(store: Store) -> None:
    document = add_doc(store)
    store.set_pages(document.id, [page(1, "Erste Seite"), page(2), page(3, "Dritte Seite")])
    assert (
        store.get_document_text(document.id) == "=== Page 1 ===\nErste Seite\n\n=== Page 3 ===\nDritte Seite"
    )

    updated = store.set_page_text(document.id, 2, "Transkribierter Mahnbescheid", "transcript")
    assert updated.text_source == "transcript"
    assert store.get_page(document.id, 2) == updated
    assert "=== Page 2 ===\nTranskribierter Mahnbescheid" in store.get_document_text(document.id)
    assert [h.doc_id for h in store.search("mahnbescheid")] == [document.id]  # re-indexed

    with pytest.raises(NotFoundError):
        store.set_page_text(document.id, 7, "x", "text")
    with pytest.raises(ValidationError):
        store.set_page_text(document.id, 1, "x", "ocr")
    assert store.get_document_text("doc_missing") == ""


# --------------------------------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------------------------------


def test_search_finds_words_with_snippet(store: Store) -> None:
    document = add_text_doc(
        store, "Sehr geehrte Frau Rivera, Ihre Stromrechnung für September ist zahlbar bis 15.10.2026."
    )
    hits = store.search("Stromrechnung")
    assert [h.doc_id for h in hits] == [document.id]
    assert "Stromrechnung" in hits[0].snippet
    assert hits[0].title == "letter.pdf"  # falls back to the filename
    assert hits[0].score >= 1.0


def test_search_finds_substrings_in_german_compounds(store: Store) -> None:
    document = add_text_doc(
        store, "Ihr Einkommensteuerbescheid für 2025 liegt bei.", title="Post vom Finanzamt"
    )
    hits = store.search("steuerbescheid")
    assert [h.doc_id for h in hits] == [document.id]
    assert 0.0 < hits[0].score < 1.0  # substring-only hit
    assert "Einkommensteuerbescheid" in hits[0].snippet


@pytest.mark.parametrize(
    "query", ["Kündigung", "KÜNDIGUNG", "kundigung", "Kuendigung", "kündigung zum 31.12."]
)
def test_search_matches_umlaut_variants(store: Store, query: str) -> None:
    document = add_text_doc(store, "Bestätigung Ihrer Kündigung zum 31.12.2026")
    assert [h.doc_id for h in store.search(query)] == [document.id]


def test_search_matches_transliterated_text_and_sharp_s(store: Store) -> None:
    transliterated = add_text_doc(store, "Bestaetigung der Kuendigung")
    street = add_text_doc(store, "Musterstraße 12, 12345 Musterstadt")
    assert [h.doc_id for h in store.search("Kündigung")] == [transliterated.id]
    assert [h.doc_id for h in store.search("Musterstrasse")] == [street.id]
    assert [h.doc_id for h in store.search("musterstraße")] == [street.id]


HOSTILE_QUERIES = [
    '"foo AND ( bar',
    "Kündigung zum 31.12.",
    '"',
    '""',
    "*",
    "(",
    ")",
    "AND",
    "OR NOT AND",
    "NEAR(foo bar, 2)",
    "title:foo",
    "-foo",
    "^start",
    "{title summary}: x",
    "foo*",
    "'; DROP TABLE documents; --",
    "\x00",
    "§ 193 BGB",
    "€ 1.234,56",
    "🙂 Rechnung",
    "a" * 5000,
    "   ",
    "",
]


@pytest.mark.parametrize("query", HOSTILE_QUERIES)
def test_hostile_queries_never_raise(store: Store, query: str) -> None:
    add_text_doc(store, "Kündigung zum 31.12.2026 — foo and bar")
    assert isinstance(store.search(query), list)
    assert isinstance(store.list_documents(q=query), list)
    assert raw(store, "SELECT COUNT(*) FROM documents") == [(1,)]


def test_random_queries_never_raise(store: Store) -> None:
    add_text_doc(store, "Kündigung zum 31.12.2026 — Einkommensteuerbescheid")
    rng = random.Random(1234)
    alphabet = "abcäöüßABC 012\"*^():{}[]+-.,;'`\\/|!?&%$#@~<>=NEARANDORNOT§€\t\n"
    for _ in range(300):
        query = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))
        store.search(query)
        store.list_documents(q=query)


def test_search_tokens_drop_syntax() -> None:
    assert search_tokens('"foo AND ( bar') == ["foo", "bar"]
    assert search_tokens("Kündigung zum 31.12.") == ["Kündigung", "zum", "31.12"]
    assert search_tokens("( * ) ^ :") == []
    assert search_tokens("and or") == ["and", "or"]  # only upper-case words are operators
    assert search_tokens("foo foo") == ["foo"]


def test_search_ranking_and_dedupe(store: Store) -> None:
    in_title = add_text_doc(store, "Bitte zahlen Sie den Betrag.", title="Mahnung")
    in_text = add_text_doc(store, "Dies ist eine Mahnung wegen offener Beträge.", title="Brief")
    compound_only = add_text_doc(store, "Letzte Zahlungsmahnung vor Inkasso.", title="Inkasso")
    hits = store.search("Mahnung")
    assert [h.doc_id for h in hits] == [in_title.id, in_text.id, compound_only.id]
    assert len({h.doc_id for h in hits}) == len(hits)
    assert hits[0].score > hits[1].score >= 1.0 > hits[2].score > 0.0  # word hits outrank substring hits
    assert [h.doc_id for h in store.search("Mahnung", limit=1)] == [in_title.id]


def test_search_covers_summary_explanation_and_party(store: Store) -> None:
    party = store.add_party(name="Muster Mobilfunk GmbH", aliases=["MuMo"])
    document = add_text_doc(store, "Vertragsbestätigung")
    store.update_document(document.id, summary="Phone contract", explanation="Cancel before March")
    assert [h.doc_id for h in store.search("phone")] == [document.id]
    assert [h.doc_id for h in store.search("March")] == [document.id]
    assert store.search("MuMo") == []
    store.update_document(document.id, party_id=party.id)
    assert [h.doc_id for h in store.search("MuMo")] == [document.id]
    store.update_party(party.id, name="Beispiel Telekom", aliases=[])
    assert store.search("MuMo") == []
    assert [h.doc_id for h in store.search("Beispiel Telekom")] == [document.id]


def test_reindex_document_repairs_the_index(store: Store) -> None:
    document = add_text_doc(store, "Wohngeldbescheid")
    store._conn().execute("DELETE FROM documents_fts")
    store._conn().execute("DELETE FROM documents_trigram")
    assert store.search("Wohngeldbescheid") == []
    store.reindex_document(document.id)
    assert [h.doc_id for h in store.search("Wohngeldbescheid")] == [document.id]
    store.reindex_document("doc_missing")  # no-op


def test_search_ignores_short_terms_for_substrings(store: Store) -> None:
    add_text_doc(store, "Ab sofort gilt der neue Tarif")
    assert store.search("xy") == []
    assert len(store.search("Ab")) == 1  # a whole-word hit still works


def test_substring_snippet_falls_back_to_the_start_when_it_cannot_locate_the_match(store: Store) -> None:
    # Python lower-cases a word-final Σ to ς only in context, so the per-character snippet
    # locator cannot find "οδος" although the index (folded as a whole) matches it.
    document = add_text_doc(store, "ΚΕΝΤΡΙΚΗΟΔΟΣ 5", title="Adresse")
    hits = store.search("οδος")
    assert [h.doc_id for h in hits] == [document.id]
    assert hits[0].snippet.startswith("Adresse")


# --------------------------------------------------------------------------------------------------
# parties / cases / contracts
# --------------------------------------------------------------------------------------------------


def test_party_crud(store: Store, clock: Clock) -> None:
    party = store.add_party(
        name="Finanzamt Musterstadt",
        kind="tax_office",
        aliases=["FA Musterstadt"],
        identifiers=[Identifier(label="Steuernummer", value="123/456/78901")],
        ibans=["DE89 3704 0044 0532 0130 00"],
        region="NW",
    )
    assert party.id.startswith("pty_")
    assert store.get_party(party.id) == party
    updated = store.update_party(
        party.id, email="post@fa.example", identifiers=[{"label": "X", "value": "1"}]
    )
    assert store.get_party(party.id) == updated
    assert updated.identifiers == [Identifier(label="X", value="1")]
    assert updated.updated_at > party.updated_at
    store.add_party(name="apotheke am markt")
    assert [p.name for p in store.list_parties()] == ["apotheke am markt", "Finanzamt Musterstadt"]
    assert store.get_party("pty_missing") is None
    with pytest.raises(ValueError, match="unknown"):
        store.add_party(name="x", colour="red")
    explicit = store.add_party(id="pty_fixed0000001", name="Fixed")
    assert store.get_party("pty_fixed0000001") == explicit


def test_find_party_by_identifier_normalises(store: Store) -> None:
    party = store.add_party(
        name="Finanzamt", identifiers=[{"label": "Steuernummer", "value": "123/456/78901"}]
    )
    store.add_party(name="Other", identifiers=[{"label": "Kundennummer", "value": "KD-99.01"}])
    for probe in ("123/456/78901", "123 456 78901", "123-456.78901", "12345678901"):
        assert store.find_party_by_identifier(probe) == party
    assert must(store.find_party_by_identifier("kd 9901")).name == "Other"
    assert store.find_party_by_identifier("999") is None
    assert store.find_party_by_identifier(" / - . ") is None
    assert normalize_identifier("DE 12–34/ab.C") == "de1234abc"


def test_find_parties_by_name(store: Store) -> None:
    city = store.add_party(name="Stadt München", aliases=["Landeshauptstadt  München"])
    store.add_party(name="Stadtwerke München")
    assert store.find_parties_by_name("stadt münchen") == [city]
    assert store.find_parties_by_name("STADT MÜNCHEN") == [city]
    assert store.find_parties_by_name(" landeshauptstadt münchen ") == [city]
    assert store.find_parties_by_name("München") == []
    assert store.find_parties_by_name("") == []


def test_merge_parties(store: Store) -> None:
    keep = store.add_party(
        name="Muster Mobil GmbH",
        identifiers=[{"label": "Kundennummer", "value": "123-45"}],
        ibans=["DE89370400440532013000"],
    )
    drop = store.add_party(
        name="MusterMobil",
        kind="telecom",
        aliases=["Muster Mobil GmbH", "MM"],
        identifiers=[{"label": "KdNr", "value": "12345"}, {"label": "Vertrag", "value": "V-1"}],
        ibans=["DE89 3704 0044 0532 0130 00", "DE02120300000000202051"],
        email="kontakt@mustermobil.example",
    )
    document = add_text_doc(store, "Rechnung", party_id=drop.id)
    case = store.add_case(title="Mobile", party_id=drop.id)
    contract = store.add_contract(name="Tarif M", party_id=drop.id)
    item = store.add_item(**item_fields(party_id=drop.id))
    draft = store.add_draft(kind="cancellation", party_id=drop.id)

    merged = store.merge_parties(keep.id, drop.id)

    assert store.get_party(drop.id) is None
    assert merged == store.get_party(keep.id)
    assert merged.aliases == ["MusterMobil", "MM"]
    assert [i.value for i in merged.identifiers] == ["123-45", "V-1"]
    assert merged.ibans == ["DE89370400440532013000", "DE02120300000000202051"]
    assert merged.email == "kontakt@mustermobil.example" and merged.kind == "telecom"
    for loaded in (
        store.get_document(document.id),
        store.get_case(case.id),
        store.get_contract(contract.id),
        store.get_item(item.id),
        store.get_draft(draft.id),
    ):
        assert loaded is not None and loaded.party_id == keep.id
    assert [h.doc_id for h in store.search("MusterMobil")] == [document.id]
    with pytest.raises(ValueError):
        store.merge_parties(keep.id, keep.id)
    with pytest.raises(NotFoundError):
        store.merge_parties(keep.id, drop.id)


def test_case_crud_and_reference_lookup(store: Store, clock: Clock) -> None:
    party = store.add_party(name="Ausländerbehörde")
    case = store.add_case(
        title="Aufenthaltstitel", party_id=party.id, reference="AZ 12/345-6", area="residence"
    )
    other = store.add_case(title="Steuer", reference="St.-Nr. 1")
    assert store.get_case(case.id) == case
    closed = store.update_case(case.id, status="closed", summary="done")
    assert store.get_case(case.id) == closed
    assert [c.id for c in store.list_cases()] == [case.id, other.id]  # most recently updated first
    assert [c.id for c in store.list_cases(party_id=party.id)] == [case.id]
    assert store.find_case_by_reference("az 12 345 6") == closed
    assert store.find_case_by_reference("St Nr 1") == other
    assert store.find_case_by_reference("nope") is None
    assert store.find_case_by_reference("--") is None


def test_contract_crud_with_computation_and_evidence(store: Store) -> None:
    computed = ContractComputation(
        regime="bgb309_new",
        cancel_by="2026-10-31",
        send_by="2026-10-26",
        confidence="high",
        steps=[
            ComputationStep(label="Notice 1 month", date="2026-10-31", rule_id="bgb309", citation="§ 309 BGB")
        ],
        rule_ids=["bgb309"],
    )
    contract = store.add_contract(
        name="Fitnessstudio",
        category="gym",
        cost_amount=29.9,
        cost_interval="monthly",
        is_consumer=True,
        computed=computed,
        evidence=[evidence()],
    )
    loaded = store.get_contract(contract.id)
    assert loaded == contract and loaded.computed == computed and loaded.evidence == [evidence()]
    assert raw(store, "SELECT is_consumer, is_basic_supply FROM contracts") == [(1, 0)]
    updated = store.update_contract(contract.id, status="cancelled", computed=None)
    assert store.get_contract(contract.id) == updated and updated.computed is None


def test_list_and_find_contracts(store: Store) -> None:
    party = store.add_party(name="Stadtwerke")
    power = store.add_contract(name="Strom", party_id=party.id, category="energy", customer_number="KD 100-1")
    gas = store.add_contract(name="Gas", party_id=party.id, category="gas")
    store.add_contract(
        name="Old", party_id=party.id, category="energy", customer_number="999", status="ended"
    )
    assert [c.name for c in store.list_contracts()] == ["Gas", "Old", "Strom"]
    assert [c.name for c in store.list_contracts(status="active")] == ["Gas", "Strom"]
    assert [c.name for c in store.list_contracts(status=["ended"], party_id=party.id)] == ["Old"]

    assert store.find_contract(party.id, "kd1001") == power
    assert store.find_contract(party.id, "KD 100-1", "gas") == power  # the number wins
    assert store.find_contract(party.id, None, "gas") == gas
    assert store.find_contract(party.id, "777", "gas") == gas  # stored contract has no number
    assert store.find_contract(party.id, "777", "energy") is None  # different number never matches
    assert store.find_contract(party.id, None, "energy") == power  # active first
    assert store.find_contract(party.id) is None
    assert store.find_contract("pty_other", "kd1001") is None


# --------------------------------------------------------------------------------------------------
# items
# --------------------------------------------------------------------------------------------------


def test_item_crud_with_nested_models(store: Store, clock: Clock) -> None:
    receipt = ComputationReceipt(
        due_date="2026-10-19",
        summary="Letter dated 15 Sep counts as delivered on 19 Sep; one month later is 19 Oct.",
        steps=[ComputationStep(label="Deemed delivery", date="2026-09-19", rule_id="ao122")],
        rule_ids=["ao122"],
        warnings=["Regional holidays ignored"],
        confidence="medium",
    )
    item = store.add_item(
        kind="deadline",
        title="Einspruch einlegen",
        due_date="2026-10-19",
        date_spec={"type": "relative", "anchor": "deemed_delivery", "amount": 1, "unit": "months"},
        computation=receipt,
        recurrence=Recurrence(interval=1, unit="years"),
        evidence=[evidence()],
        grounding="verified",
        user_modified=True,
    )
    loaded = store.get_item(item.id)
    assert loaded == item
    assert loaded.date_spec == DateSpec(type="relative", anchor="deemed_delivery", amount=1, unit="months")
    assert loaded.computation == receipt and loaded.recurrence == Recurrence(interval=1, unit="years")
    assert raw(store, "SELECT user_modified FROM items") == [(1,)]
    updated = store.update_item(
        item.id, status="done", completed_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC) + timedelta(hours=-2)
    )
    assert updated.completed_at == "2026-10-01T10:00:00Z"
    assert store.get_item(item.id) == updated and updated.status == "done"
    assert store.delete_item(item.id) is True
    assert store.delete_item(item.id) is False
    assert store.get_item(item.id) is None
    with pytest.raises(ValidationError):
        store.add_item(title="no kind")


def test_list_items_order_and_filters(store: Store, clock: Clock) -> None:
    party = store.add_party(name="P")
    document = add_doc(store)
    contract = store.add_contract(name="C")
    case = store.add_case(title="K")
    low_early = store.add_item(**item_fields(title="a", due_date="2026-10-01", priority="low"))
    critical_early = store.add_item(**item_fields(title="b", due_date="2026-10-01", priority="critical"))
    later = store.add_item(**item_fields(title="c", due_date="2026-11-01", kind="payment", area="money"))
    undated_high = store.add_item(**item_fields(title="d", priority="high", party_id=party.id))
    undated_normal = store.add_item(**item_fields(title="e", doc_id=document.id, status="done"))
    linked = store.add_item(
        **item_fields(title="f", due_date="2026-12-24", contract_id=contract.id, case_id=case.id, kind="task")
    )

    def ids(**filters: Any) -> list[str]:
        return [i.id for i in store.list_items(**filters)]

    assert ids() == [critical_early.id, low_early.id, later.id, linked.id, undated_high.id, undated_normal.id]
    assert ids(status="done") == [undated_normal.id]
    assert ids(status=["open"], include_undated=False) == [
        critical_early.id,
        low_early.id,
        later.id,
        linked.id,
    ]
    assert ids(kind="payment") == [later.id]
    assert ids(kind=["payment", "task"]) == [later.id, linked.id]
    assert ids(from_date="2026-10-02", include_undated=False) == [later.id, linked.id]
    assert ids(to_date=date(2026, 10, 31)) == [
        critical_early.id,
        low_early.id,
        undated_high.id,
        undated_normal.id,
    ]
    assert ids(from_date=date(2026, 11, 1), to_date="2026-11-30", include_undated=False) == [later.id]
    assert ids(area="money") == [later.id]
    assert ids(party_id=party.id) == [undated_high.id]
    assert ids(doc_id=document.id) == [undated_normal.id]
    assert ids(contract_id=contract.id) == [linked.id] == ids(case_id=case.id)
    assert ids(limit=2) == [critical_early.id, low_early.id]
    assert ids(status=[]) == []


def test_upsert_item_by_slot(store: Store, clock: Clock) -> None:
    document = add_doc(store)
    created = store.upsert_item_by_slot(
        document.id, "payment|zahlbar bis", kind="payment", title="Pay", amount=42.0
    )
    assert created.id == content_id("itm", document.id, "payment|zahlbar bis")
    assert (created.doc_id, created.slot_key, created.origin) == (
        document.id,
        "payment|zahlbar bis",
        "extracted",
    )

    refreshed = store.upsert_item_by_slot(document.id, "payment|zahlbar bis", title="Pay now", amount=43.0)
    assert refreshed.id == created.id and refreshed.title == "Pay now" and refreshed.amount == 43.0
    assert refreshed.updated_at > created.updated_at
    assert refreshed.created_at == created.created_at

    edited = store.update_item(
        created.id, due_date="2026-10-20", user_modified=True, due_date_source="manual"
    )
    untouched = store.upsert_item_by_slot(
        document.id, "payment|zahlbar bis", title="Model says", due_date=None
    )
    assert untouched == edited and store.get_item(created.id) == edited

    assert store.upsert_item_by_slot(document.id, "payment|zahlbar bis") == edited
    with pytest.raises(ValueError):
        store.upsert_item_by_slot(document.id, "x", id="itm_mine", kind="task", title="t")
    with pytest.raises(ValueError):
        store.upsert_item_by_slot(document.id, "x", colour="red")
    assert len(store.list_items(doc_id=document.id)) == 1


def test_delete_stale_extracted_items(store: Store) -> None:
    document = add_doc(store, b"a")
    other = add_doc(store, b"b")
    kept = store.upsert_item_by_slot(document.id, "keep", **item_fields())
    stale = store.upsert_item_by_slot(document.id, "stale", **item_fields())
    edited = store.upsert_item_by_slot(document.id, "edited", **item_fields())
    store.update_item(edited.id, user_modified=True)
    paid = store.upsert_item_by_slot(document.id, "paid", **item_fields())
    store.update_item(paid.id, status="done")  # a status click: the person acted on it
    manual = store.add_item(**item_fields(doc_id=document.id, origin="manual"))
    no_slot = store.add_item(**item_fields(doc_id=document.id))
    foreign = store.upsert_item_by_slot(other.id, "stale", **item_fields())

    assert store.delete_stale_extracted_items(document.id, ["keep"]) == 2
    remaining = {i.id for i in store.list_items()}
    assert remaining == {kept.id, edited.id, paid.id, manual.id, foreign.id}
    assert stale.id not in remaining and no_slot.id not in remaining
    assert store.delete_stale_extracted_items(document.id, iter(["keep"])) == 0
    assert store.delete_stale_extracted_items(document.id, []) == 1  # only the unedited extracted one
    assert {i.id for i in store.list_items()} == {edited.id, paid.id, manual.id, foreign.id}


# --------------------------------------------------------------------------------------------------
# suggestions
# --------------------------------------------------------------------------------------------------


def suggestion(fingerprint: str = "deadline_soon:itm_1:abc", **overrides: Any) -> dict[str, Any]:
    return {
        "kind": "deadline",
        "title": "Objection deadline in 5 days",
        "body": "Send the objection by Friday.",
        "fingerprint": fingerprint,
        "rule_id": "deadline_soon",
        "refs": [{"type": "item", "id": "itm_1"}],
        **overrides,
    }


def test_upsert_suggestion_inserts_with_content_id(store: Store) -> None:
    created = store.upsert_suggestion(suggestion(action={"type": "draft", "draft_kind": "objection"}))
    assert created.id == content_id("sug", "deadline_soon:itm_1:abc")
    assert created.status == "new" and created.source == "rule"
    assert created.refs == [SuggestionRef(type="item", id="itm_1")]
    assert created.action == SuggestionAction(type="draft", draft_kind="objection")
    assert store.get_suggestion(created.id) == created


def test_upsert_suggestion_refreshes_text_but_keeps_the_persons_status(store: Store, clock: Clock) -> None:
    created = store.upsert_suggestion(suggestion())
    store.update_suggestion(created.id, status="snoozed", snoozed_until="2026-10-01")
    refreshed = store.upsert_suggestion(
        suggestion(title="Objection deadline in 4 days", priority="high", savings_estimate=12.5, status="new")
    )
    assert refreshed.id == created.id
    assert refreshed.title == "Objection deadline in 4 days" and refreshed.priority == "high"
    assert refreshed.savings_estimate == 12.5
    assert (refreshed.status, refreshed.snoozed_until) == ("snoozed", "2026-10-01")
    same = store.upsert_suggestion(
        suggestion(title="Objection deadline in 4 days", priority="high", savings_estimate=12.5)
    )
    assert same.updated_at == refreshed.updated_at  # nothing changed, nothing written


def test_upsert_suggestion_revives_expired(store: Store) -> None:
    created = store.upsert_suggestion(suggestion())
    store.update_suggestion(created.id, status="expired", snoozed_until="2026-10-01")
    revived = store.upsert_suggestion(suggestion())
    assert (revived.status, revived.snoozed_until) == ("new", None)


def test_upsert_suggestion_accepts_models_and_validates(store: Store) -> None:
    model = Suggestion(
        id="sug_ignored00000",
        kind="saving",
        title="Switch tariff",
        body="Cheaper",
        fingerprint="review:abc",
        source="review",
        created_at="x",
        updated_at="y",
    )
    stored = store.upsert_suggestion(model)
    assert stored.id == content_id("sug", "review:abc") and stored.created_at != "x"
    with pytest.raises(ValueError, match="fingerprint"):
        store.upsert_suggestion(suggestion(fingerprint=""))
    with pytest.raises(ValueError, match="unknown"):
        store.upsert_suggestion(suggestion(colour="red"))


def test_reconcile_suggestions(store: Store) -> None:
    live = store.upsert_suggestion(suggestion("r1:live"))
    gone = store.upsert_suggestion(suggestion("r1:gone"))
    snoozed_gone = store.upsert_suggestion(suggestion("r1:snoozed"))
    store.update_suggestion(snoozed_gone.id, status="snoozed")
    dismissed_gone = store.upsert_suggestion(suggestion("r1:dismissed"))
    store.update_suggestion(dismissed_gone.id, status="dismissed")
    other_rule = store.upsert_suggestion(suggestion("r2:gone", rule_id="expiry_soon"))
    review = store.upsert_suggestion(suggestion("review:x", source="review"))

    assert store.reconcile_suggestions(["deadline_soon"], ["r1:live"]) == 2

    def status(s: Suggestion) -> str:
        loaded = store.get_suggestion(s.id)
        assert loaded is not None
        return loaded.status

    assert status(live) == "new"
    assert status(gone) == "expired" and status(snoozed_gone) == "expired"
    assert status(dismissed_gone) == "dismissed"
    assert status(other_rule) == "new" and status(review) == "new"
    assert store.reconcile_suggestions([], []) == 0
    assert store.reconcile_suggestions(["deadline_soon"], ["r1:live"]) == 0  # already expired


def test_list_suggestions(store: Store, clock: Clock) -> None:
    normal = store.upsert_suggestion(suggestion("a"))
    critical = store.upsert_suggestion(suggestion("b", priority="critical"))
    dated = store.upsert_suggestion(suggestion("c", due_date="2026-10-01"))
    newest = store.upsert_suggestion(suggestion("d"))
    store.update_suggestion(normal.id, status="dismissed")
    assert [s.id for s in store.list_suggestions()] == [critical.id, dated.id, newest.id, normal.id]
    assert [s.id for s in store.list_suggestions(status="new", limit=2)] == [critical.id, dated.id]
    assert [s.id for s in store.list_suggestions(status=["dismissed"])] == [normal.id]


# --------------------------------------------------------------------------------------------------
# drafts / notes / chat
# --------------------------------------------------------------------------------------------------


def test_draft_crud(store: Store, clock: Clock) -> None:
    document = add_doc(store)
    guidance = SendGuidance(
        send_by="2026-10-26",
        form="written_form",
        channels=[SendChannel(channel="registered_letter", label="Einschreiben Einwurf", recommended=True)],
        tips=["Keep the receipt"],
    )
    draft = store.add_draft(
        kind="objection",
        doc_id=document.id,
        subject="Einspruch",
        body="…lege ich Einspruch ein.",
        body_translation="…I object.",
        enclosures=["Bescheid"],
        checks=[DraftCheck(id="has_reference", label="Reference", ok=True)],
        send_guidance=guidance,
    )
    assert draft.id.startswith("drf_")
    loaded = store.get_draft(draft.id)
    assert loaded == draft and loaded.send_guidance == guidance
    sent = store.update_draft(draft.id, status="sent", sent_at="2026-10-02T09:00:00Z", sent_channel="letter")
    other = store.add_draft(kind="cancellation")
    assert [d.id for d in store.list_drafts()] == [other.id, draft.id]
    assert store.list_drafts(doc_id=document.id) == [sent]
    assert [d.id for d in store.list_drafts(status="draft")] == [other.id]
    assert store.delete_draft(other.id) is True and store.delete_draft(other.id) is False
    assert store.get_draft(other.id) is None


def test_notes(store: Store, clock: Clock) -> None:
    first = store.add_note("Called the landlord", ["itm_1", "itm_2"])
    second = store.add_note("Asked for an extension", item_ids=["itm_2"], id="nte_fixed0000001")
    assert first.id.startswith("nte_") and second.id == "nte_fixed0000001"
    assert store.list_notes() == [second, first]
    assert store.list_notes(item_id="itm_1") == [first]
    assert store.list_notes(item_id="itm_2") == [second, first]
    assert store.list_notes(item_id="itm_9") == []


def test_chat_messages_keep_insertion_order(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module, "now_iso", lambda: "2026-09-25T10:00:00Z")  # same second
    thread = new_id("thr")
    messages = [
        store.add_chat_message(thread, "user", "When is my objection due?"),
        store.add_chat_message(
            thread,
            "assistant",
            "By 19 Oct [item:itm_1].",
            citations=[SuggestionRef(type="item", id="itm_1")],
            tool_calls=[{"name": "search", "input": {"query": "Einspruch"}}],
        ),
        store.add_chat_message(thread, "user", "Thanks"),
    ]
    store.add_chat_message(new_id("thr"), "user", "other thread")
    assert store.list_chat_messages(thread) == messages
    assert messages[1].citations[0].id == "itm_1"
    assert messages[1].tool_calls == [{"name": "search", "input": {"query": "Einspruch"}}]
    with pytest.raises(ValidationError):
        store.add_chat_message(thread, "system", "nope")


# --------------------------------------------------------------------------------------------------
# jobs
# --------------------------------------------------------------------------------------------------


def test_job_queue_lifecycle(store: Store, clock: Clock) -> None:
    document = add_doc(store)
    first = store.enqueue_job("ingest", document.id)
    second = store.enqueue_job("reprocess", document.id, force=True)
    review = store.enqueue_job("review")
    assert (first.status, first.attempts, second.force) == ("queued", 0, True)
    assert store.get_job(first.id) == first
    assert raw(store, "SELECT force FROM jobs WHERE id = ?", second.id) == [(1,)]

    claimed = store.claim_next_job(["ingest", "reprocess"])
    assert claimed is not None and claimed.id == first.id
    assert (claimed.status, claimed.attempts) == ("running", 1)
    assert must(store.claim_next_job(["review"])).id == review.id
    assert store.claim_next_job([]) is None
    assert must(store.claim_next_job()).id == second.id
    assert store.claim_next_job() is None

    store.update_job(first.id, status="done", progress=1.0, stage="done")
    assert [j.id for j in store.list_jobs(active_only=True)] == [review.id, second.id]
    assert [j.id for j in store.list_jobs()] == [review.id, second.id, first.id]
    assert [j.id for j in store.list_jobs(limit=1)] == [review.id]

    assert store.requeue_running_jobs() == 2
    assert {j.status for j in store.list_jobs(active_only=True)} == {"queued"}
    assert must(store.claim_next_job()).attempts == 2
    with pytest.raises(ValidationError):
        store.enqueue_job("bake")


def test_claim_respects_not_before(store: Store) -> None:
    future = datetime.now(UTC) + timedelta(hours=1)
    delayed = store.enqueue_job("ingest", not_before=future)
    assert delayed.not_before == future.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert store.claim_next_job() is None
    store.update_job(delayed.id, not_before="2020-01-01T02:00:00+02:00")
    assert must(store.get_job(delayed.id)).not_before == "2020-01-01T00:00:00Z"
    assert must(store.claim_next_job()).id == delayed.id
    store.update_job(delayed.id, status="queued", not_before=None)
    assert must(store.claim_next_job()).id == delayed.id
    naive = store.update_job(delayed.id, not_before="2020-01-01T02:00:00")  # naive = UTC
    assert naive.not_before == "2020-01-01T02:00:00Z"


def test_claim_next_job_never_hands_out_a_job_twice(store: Store) -> None:
    jobs = {store.enqueue_job("ingest").id for _ in range(80)}
    claimed: list[str] = []
    lock = threading.Lock()

    def worker(_: int) -> None:
        while (job := store.claim_next_job(["ingest"])) is not None:
            with lock:
                claimed.append(job.id)

    assert run_threads(4, worker) == []
    assert sorted(claimed) == sorted(jobs)
    assert len(claimed) == len(set(claimed))


# --------------------------------------------------------------------------------------------------
# concurrency
# --------------------------------------------------------------------------------------------------


def test_concurrent_writes_from_four_threads(store: Store, tmp_path: Path) -> None:
    second_store = Store(store.db_path)  # another Store on the same file shares the process lock
    document = add_doc(store)

    def writer(index: int) -> None:
        target = store if index % 2 else second_store
        for n in range(40):
            item = target.add_item(**item_fields(title=f"t{index}-{n}", doc_id=document.id))
            target.update_item(item.id, priority="high")
            with target.tx():
                target.set_meta(f"thread-{index}", str(n))
                target.log_activity("test", f"{index}-{n}")
            target.list_items(limit=5)

    try:
        assert run_threads(4, writer) == []
    finally:
        second_store.close()
    assert store.counts()["items"] == 160
    assert len(store.list_activity(limit=500)) == 160
    assert {store.get_meta(f"thread-{i}") for i in range(4)} == {"39"}


# --------------------------------------------------------------------------------------------------
# activity / accounting / cache / counts
# --------------------------------------------------------------------------------------------------


def test_activity_log(store: Store) -> None:
    first = store.log_activity(
        "document.processed", "Read your tax assessment", "document", "doc_1", {"pages": 2}
    )
    second = store.log_activity("llm.call", "Asked Claude")
    assert first.id < second.id and first.data == {"pages": 2}
    assert store.list_activity() == [second, first]
    assert store.list_activity(limit=1) == [second]


def test_log_llm_call_matches_the_usage_sink_protocol(store: Store) -> None:
    sink: UsageSink = store
    ours = inspect.signature(Store.log_llm_call).parameters
    theirs = inspect.signature(UsageSink.log_llm_call).parameters
    assert [(p.name, p.default) for p in ours.values()] == [(p.name, p.default) for p in theirs.values()]
    for name in ("cache_get", "cache_put"):
        assert list(inspect.signature(getattr(Store, name)).parameters) == list(
            inspect.signature(getattr(UsageSink, name)).parameters
        )
    assert sink is store


def test_usage_stats_aggregates(store: Store) -> None:
    assert store.usage_stats() == store.usage_stats(recent=0)
    store.add_document(id="doc_1", sha256="a" * 64, filename="a.pdf", mime="application/pdf", file_path="a")
    store.log_llm_call(
        "extract",
        "sonnet",
        "claude-cli",
        Usage(input_tokens=1000, output_tokens=200, cost_usd=0.012, duration_ms=900),
        doc_ids=["doc_1"],
        pages_sent=2,
        bytes_sent=4096,
    )
    store.log_llm_call("extract", "sonnet", "claude-cli", Usage(), cache_hit=True, doc_ids=["doc_1"])
    store.log_llm_call(
        "ask", "sonnet", "claude-cli", Usage(input_tokens=10, cost_usd=0.001), ok=False, error="429"
    )

    stats = store.usage_stats(recent=2)
    assert (stats.calls, stats.cache_hits, stats.input_tokens, stats.output_tokens) == (3, 1, 1010, 200)
    # prompt tokens read from or written to the cache count as "in" too, as a letter's trace counts them
    # (walkthrough of phase 2: Settings said "2 in" where "How it was read" said "20k in")
    store.log_llm_call(
        "review",
        "sonnet",
        "claude-cli",
        Usage(input_tokens=2, cache_read_tokens=15_000, cache_creation_tokens=5_000, output_tokens=8),
    )
    cached = store.usage_stats(recent=0)
    assert cached.input_tokens == 1010 + 20_002
    assert cached.by_purpose["review"].input_tokens == 20_002
    stats = store.usage_stats(recent=3)
    assert stats.cost_usd == pytest.approx(0.013)
    assert stats.by_purpose["extract"].model_dump() == {
        "calls": 2,
        "cache_hits": 1,
        "errors": 0,
        "input_tokens": 1000,
        "output_tokens": 200,
        "cost_usd": pytest.approx(0.012),
    }
    assert stats.by_purpose["ask"].errors == 1
    assert [r.purpose for r in stats.recent] == ["review", "ask", "extract"]
    assert stats.recent[1].ok is False and stats.recent[1].error == "429"
    assert stats.recent[2].cache_hit is True and stats.recent[2].doc_ids == ["doc_1"]
    first = store.usage_stats(recent=5).recent[-1]
    assert (first.pages_sent, first.bytes_sent, first.duration_ms) == (2, 4096, 900)


async def test_llm_service_uses_the_store_as_cache_and_ledger(store: Store) -> None:
    store.add_document(id="doc_1", sha256="a" * 64, filename="a.pdf", mime="application/pdf", file_path="a")
    service = LLMService(FakeBackend({"extract": {"kind": "invoice"}}), sink=store)
    request = LLMRequest(purpose="extract", prompt="p", system="s", cache_key="file-sha", doc_ids=["doc_1"])
    first = await service.complete(request)
    second = await service.complete(request)
    assert first.data == second.data == {"kind": "invoice"} and second.cache_hit
    stats = store.usage_stats()
    assert (stats.calls, stats.cache_hits) == (2, 1)
    assert store.purge_cache_for("doc_1") == 1


def test_cache_put_get_replace_and_purge(store: Store) -> None:
    assert store.cache_get("k") is None
    store.cache_put("k", "extract", "sonnet", {"text": "ä", "data": {"x": [1, 2]}}, doc_sha="sha-a")
    assert store.cache_get("k") == {"text": "ä", "data": {"x": [1, 2]}}
    store.cache_put("k", "extract", "sonnet", {"text": "new"}, doc_sha="sha-a")
    assert store.cache_get("k") == {"text": "new"}
    store.cache_put("k2", "transcribe", "sonnet", {"text": "t"}, doc_sha="sha-a")
    store.cache_put("k3", "brief", "haiku", {"text": "b"})
    assert store.purge_cache_for("sha-a") == 2
    assert store.cache_get("k2") is None and store.cache_get("k3") == {"text": "b"}
    assert store.purge_cache_for("sha-a") == 0


def test_counts(store: Store) -> None:
    empty = store.counts()
    assert set(empty.values()) == {0}
    document = add_text_doc(store, "x", status="needs_review")
    store.add_party(name="p")
    store.add_case(title="c")
    store.add_contract(name="c", status="ended")
    store.add_item(**item_fields(doc_id=document.id))
    store.add_item(**item_fields(status="done"))
    store.upsert_suggestion(suggestion())
    store.add_draft(kind="general_reply")
    store.add_note("n")
    store.add_chat_message("thr_1", "user", "hi")
    store.enqueue_job("review")
    store.log_llm_call("brief", "haiku", "fake", Usage())
    store.cache_put("k", "brief", "haiku", {})
    counts = store.counts()
    assert counts == {
        "documents": 1,
        "trashed_documents": 0,
        "needs_review": 1,
        "pages": 1,
        "parties": 1,
        "cases": 1,
        "contracts": 1,
        "active_contracts": 0,
        "items": 2,
        "open_items": 1,
        "suggestions": 1,
        "new_suggestions": 1,
        "drafts": 1,
        "notes": 1,
        "chat_messages": 1,
        "jobs": 1,
        "active_jobs": 1,
        "llm_calls": 1,
        "cache_entries": 1,
    }


# --------------------------------------------------------------------------------------------------
# schema <-> model drift guard
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    [
        store_module._PARTIES,
        store_module._CASES,
        store_module._DOCUMENTS,
        store_module._PAGES,
        store_module._CONTRACTS,
        store_module._ITEMS,
        store_module._SUGGESTIONS,
        store_module._DRAFTS,
        store_module._NOTES,
        store_module._CHAT,
        store_module._JOBS,
        store_module._ACTIVITY,
        store_module._LLM_CALLS,
    ],
    ids=lambda t: t.name,
)
def test_every_model_field_has_a_column(store: Store, table: Any) -> None:
    columns = {row[1] for row in raw(store, f"PRAGMA table_info({table.name})")}
    assert set(table.column_of.values()) <= columns
    assert set(table.extras) <= columns
