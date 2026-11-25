"""Ask never sees a scan's scanner text (ADR 0020): its search doesn't match it, and the ledger fingerprint
every recorded answer replays against ignores it — so keeping that text changes no recording."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import TODAY, Router, fake_backend
from helpers_docs import scanned_pdf
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.assistant.ask import ledger_fingerprint
from ordnung.assistant.mcp_server import LedgerTools
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.demo.loader import copy_snapshot
from ordnung.ingest import pipeline
from ordnung.ingest.pipeline import add_file
from ordnung.llm.base import ClaudeNotInstalled

DEMO_DB = Path(__file__).resolve().parents[1] / "src" / "ordnung" / "demo" / "demo_db"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def ctx(data_dir: Path) -> Iterator[AppContext]:
    router = Router()
    router.errors["transcribe"] = lambda: ClaudeNotInstalled("The “claude” command was not found.")
    context = build_context(data_dir, backend_obj=fake_backend(router))
    yield context
    context.close()


async def _waiting_scan(ctx: AppContext) -> str:
    """A searchable PDF that may be read by Claude but waits for it (Claude isn't installed)."""
    document = await add_file(ctx, scanned_pdf(ocr=True), "scan.pdf")
    await ctx.worker.run_until_idle()
    stored = ctx.store.get_document(document.id)
    assert stored is not None and stored.status == "queued" and not stored.ai_private
    assert ctx.store.scan_text_matches("Einkommensteuer") == {document.id}
    return document.id


async def test_ask_search_never_matches_scanner_text(ctx: AppContext) -> None:
    """A waiting letter Ask may see: its scanner text is not the letter's words, so Ask's search doesn't
    find it there (the person's letter search does, marked "not checked")."""
    await _waiting_scan(ctx)
    tools = LedgerTools(ctx.store, today=clock.today())
    assert tools.search("Einkommensteuer").record == {"hits": []}
    assert tools.search("Bescheid Einkommensteuer 2025").record == {"hits": []}
    assert ctx.store.search("Einkommensteuer") == []


async def test_the_ledger_fingerprint_ignores_scanner_text(ctx: AppContext) -> None:
    """The fingerprint, and what Ask's tools say about the letter, stay the same whatever its scanner text."""
    doc_id = await _waiting_scan(ctx)
    tools = LedgerTools(ctx.store, today=clock.today())
    kept, shown = ledger_fingerprint(ctx.store), tools.get_document(doc_id)
    ctx.store.write_scan_text(doc_id, {1: "Ganz andere Wörter eines anderen Scanners"})
    assert ctx.store.scan_text_matches("Scanners") == {doc_id}
    assert ledger_fingerprint(ctx.store) == kept and tools.get_document(doc_id) == shown
    (ctx.store.paths.derived / doc_id / "scan-text.json").unlink()
    assert ledger_fingerprint(ctx.store) == kept and tools.get_document(doc_id) == shown


def test_the_demo_keeps_no_scanner_text_and_its_fingerprint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The demo's letters all have text of their own: the catch-up reads each PDF letter's original, finds
    nothing to do there, writes no ``scan-text.json`` and leaves Ask's fingerprint as it was."""
    data = tmp_path / "demo"
    copy_snapshot(DEMO_DB, data)  # as the demo is prepared: the snapshot alone carries no originals
    read: list[Path] = []
    original_read = pipeline.read_pdf_text

    def counted(pdf_path: Path, *args: Any) -> Any:
        read.append(pdf_path)
        return original_read(pdf_path, *args)

    monkeypatch.setattr(pipeline, "read_pdf_text", counted)
    store = Store.open(Paths(data))
    try:
        pdfs = [document for document in store.list_documents() if document.mime == "application/pdf"]
        # an original missing would make the catch-up skip its letter, and this test check nothing
        assert pdfs and all((store.get_document_file(document.id) or data).is_file() for document in pdfs)
        before = ledger_fingerprint(store)
        assert store.scan_text_missing() == []
        for document in store.list_documents():
            pipeline.catch_up_scan_text(store, document.id)
            assert store.scan_text_pages(document.id) == []
        assert len(read) == len(pdfs)
        assert store.scan_text_matches("Miete") == set()
        assert ledger_fingerprint(store) == before
    finally:
        store.close()
    assert list(data.rglob("scan-text.json")) == []
