"""Ask never sees the words Ordnung read in a picture (ADR 0024), as it never sees a scanner's text (ADR 0020): its
search doesn't match them, and neither the ledger fingerprint every recorded answer replays against nor what its
tools say about a letter changes with them — so keeping them changes no recording. The demo has no letter whose
pictures would be read, and keeps its fingerprint."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import TODAY, Router, fake_backend
from helpers_docs import photo
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.assistant.ask import ledger_fingerprint
from ordnung.assistant.mcp_server import LedgerTools
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.ingest.pipeline import add_file
from ordnung.llm.base import ClaudeNotInstalled

DEMO_DB = Path(__file__).resolve().parents[1] / "src" / "ordnung" / "demo" / "demo_db"
#: The Ask fingerprint of the demo (plan §1), pinned: Ordnung's reading of pictures must never move it.
DEMO_FINGERPRINT = "6d63e0d2ead937a6c8e4fd974c537b368c20101035bd70fc8f1038096a550b08"
PICTURE_WORDS = "Hausverwaltung Beispiel GmbH · Ihr Kellerabteil 7 · Gebäude Süd"


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


async def _waiting_photo(ctx: AppContext) -> str:
    """A photo Claude may read but that waits for it (Claude isn't installed), with the words Ordnung read in it."""
    document = await add_file(ctx, photo("JPEG"), "foto.jpg")
    await ctx.worker.run_until_idle()
    stored = ctx.store.get_document(document.id)
    assert stored is not None and stored.status == "queued" and not stored.ai_private
    assert ctx.store.picture_text_due() == [(document.id, 1)]
    assert ctx.store.write_picture_text(document.id, 1, PICTURE_WORDS)
    assert ctx.store.picture_text_matches("Kellerabteil") == {document.id}
    return document.id


async def test_ask_search_never_matches_picture_text(ctx: AppContext) -> None:
    """A waiting letter Ask may see: the words Ordnung read in its picture are not the letter's words, so Ask's
    search doesn't find it by them (the person's letter search does, marked "not checked")."""
    await _waiting_photo(ctx)
    tools = LedgerTools(ctx.store, today=clock.today())
    for query in ("Kellerabteil", "Hausverwaltung Beispiel", "Gebäude Süd"):
        assert tools.search(query).record == {"hits": []}
        assert ctx.store.search(query) == []


async def test_the_ledger_fingerprint_and_get_document_ignore_picture_text(ctx: AppContext) -> None:
    """The fingerprint, and what Ask's tools say about the letter, stay the same whatever its picture text."""
    doc_id = await _waiting_photo(ctx)
    tools = LedgerTools(ctx.store, today=clock.today())
    kept, shown = ledger_fingerprint(ctx.store), tools.get_document(doc_id)
    assert "Kellerabteil" not in str(shown.record)
    picture = ctx.store.paths.derived / doc_id / "picture-text.json"
    picture.unlink()
    assert ctx.store.write_picture_text(doc_id, 1, "Ganz andere Wörter aus einem anderen Bild")
    assert ctx.store.picture_text_matches("anderen Bild") == {doc_id}
    assert ledger_fingerprint(ctx.store) == kept and tools.get_document(doc_id) == shown
    picture.unlink()
    assert ledger_fingerprint(ctx.store) == kept and tools.get_document(doc_id) == shown


def test_the_demo_has_nothing_to_read_and_keeps_its_fingerprint(tmp_path: Path) -> None:
    """The demo's letters are all read and have text of their own: no page is due, nothing is stale, nothing is
    found by picture text, no ``picture-text.json`` is written, and Ask's fingerprint is the pinned one."""
    data = tmp_path / "demo"
    shutil.copytree(DEMO_DB, data)
    store = Store.open(Paths(data))
    try:
        assert ledger_fingerprint(store) == DEMO_FINGERPRINT
        assert store.picture_text_due() == []
        assert store.picture_text_stale() == []
        assert store.picture_text_matches("Miete") == set()
        assert all(store.picture_text_pages(document.id) == [] for document in store.list_documents())
        assert store.forget_all_picture_text() == 0
        assert ledger_fingerprint(store) == DEMO_FINGERPRINT
    finally:
        store.close()
    assert list(data.rglob("picture-text.json")) == []
