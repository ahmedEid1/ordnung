"""*For taxes* on any letter (D3, ``secretary.tax_choice``): the person's own choice counts over Claude's
mark, both ways, and survives *Read again*, which asks Claude exactly what it asked without the choice. Ask's
get_document and the weekly review follow the choice for the letters they may read (point 4, ADR 0025), so a
choice moves Ask's fingerprint and ledger token; without a choice, both read exactly as before.

The store's side (set, clear, unchanged writes nothing, unreadable rows, the purge and the trash) is in
``tests/test_store_choices.py``; the route's refusals and the phone in ``tests/test_api_documents.py``.
"""

from __future__ import annotations

import csv
import io
import shutil
import zipfile
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER
from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.assistant.ask import ledger_fingerprint
from ordnung.assistant.channels import parse_tool_result
from ordnung.assistant.mcp_server import (
    TAX_MARKED_BY_PERSON,
    TAX_UNMARKED_BY_PERSON,
    TOOL_NAMES,
    LedgerTools,
    render_result,
)
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.letters_zip import INDEX_NAME
from ordnung.llm.base import LLMRequest
from ordnung.secretary.review import build_snapshot
from ordnung.secretary.triggers import run_and_reconcile
from test_api_support import TODAY as API_TODAY
from test_api_support import Api, ApiRouter, api_for

DEMO_DB = Path(__file__).resolve().parents[1] / "src" / "ordnung" / "demo" / "demo_db" / "ordnung.db"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(API_TODAY)
    yield
    clock.set_today(None)


async def _read(api: Api, data: bytes, name: str) -> str:
    body = await api.upload((name, data))
    await api.read_all()
    return str(body["documents"][0]["id"])


async def _read_again(api: Api, doc_id: str) -> list[LLMRequest]:
    """*Read again* (``POST …/reprocess``) to the end; the model calls it made."""
    before = len(api.backend.calls)
    response = await api.client.post(f"/api/documents/{doc_id}/reprocess")
    assert response.status_code == 202, response.text
    await api.read_all()
    return api.backend.calls[before:]


async def _choose(api: Api, doc_id: str, choice: bool | None) -> None:
    response = await api.client.patch(f"/api/documents/{doc_id}", json={"tax_choice": choice})
    assert response.status_code == 200, response.text


async def _page(api: Api, doc_id: str) -> tuple[bool, bool | None]:
    """Claude's mark and the person's choice, as the letter's page has them."""
    detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
    return detail["document"]["tax_relevant"], detail["tax_choice"]


async def _tax_zip(api: Api) -> dict[str, dict[str, str]]:
    """*Export letters* with *Only letters for taxes*: ``index.csv``'s rows by letter id."""
    response = await api.client.get("/api/documents.zip", params={"tax": "true"})
    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    text = archive.read(INDEX_NAME).decode("utf-8-sig")
    return {row["ordnung_id"]: row for row in csv.DictReader(io.StringIO(text, newline=""), delimiter=";")}


# --------------------------------------------------------------------------------------------------
# the policy, over HTTP
# --------------------------------------------------------------------------------------------------


async def test_a_letter_without_a_choice_goes_by_claudes_mark(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        tax = await _read(api, TAX_LETTER.pdf(), "bescheid.pdf")
        invoice = await _read(api, INVOICE_LETTER.pdf(), "rechnung.pdf")
        assert await _page(api, tax) == (True, None)
        assert await _page(api, invoice) == (False, None)
        assert set(await _tax_zip(api)) == {tax}


async def test_the_persons_choice_overrides_claudes_mark_both_ways(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        tax = await _read(api, TAX_LETTER.pdf(), "bescheid.pdf")
        invoice = await _read(api, INVOICE_LETTER.pdf(), "rechnung.pdf")
        await _choose(api, tax, False)
        await _choose(api, invoice, True)
        # Claude's own mark stays on each letter; what counts is the person's choice
        assert await _page(api, tax) == (True, False)
        assert await _page(api, invoice) == (False, True)
        rows = await _tax_zip(api)
        assert set(rows) == {invoice} and rows[invoice]["for_taxes"] == "yes"
        await _choose(api, tax, None)  # back to Claude's mark
        assert set(await _tax_zip(api)) == {tax, invoice}


async def test_the_trash_keeps_the_choice_and_deleting_for_good_drops_it(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        tax = await _read(api, TAX_LETTER.pdf(), "bescheid.pdf")
        invoice = await _read(api, INVOICE_LETTER.pdf(), "rechnung.pdf")
        await _choose(api, tax, False)
        await _choose(api, invoice, True)
        assert (await api.client.delete(f"/api/documents/{tax}")).json()["purged"] is False
        assert api.ctx.store.tax_choices() == {tax: False, invoice: True}
        assert (
            await api.client.delete(f"/api/documents/{invoice}", params={"purge": "true"})
        ).status_code == 200
        assert api.ctx.store.tax_choices() == {tax: False}


# --------------------------------------------------------------------------------------------------
# Read again: the choice stays, and Claude is asked exactly what it was asked before
# --------------------------------------------------------------------------------------------------


async def test_the_tax_choice_survives_read_again_both_ways(data_dir: Path) -> None:
    router = ApiRouter()
    async with api_for(data_dir, router=router) as api:
        doc_id = await _read(api, TAX_LETTER.pdf(), "bescheid.pdf")
        # Claude marked it; the person took it off: read again, Claude marks it again and the choice stays
        await _choose(api, doc_id, False)
        await _read_again(api, doc_id)
        assert await _page(api, doc_id) == (True, False)
        assert set(await _tax_zip(api)) == set()
        # the other way: this time Claude doesn't mark it, and the person did
        router.payloads[TAX_LETTER.marker]["tax_relevant"] = False
        await _choose(api, doc_id, True)
        await _read_again(api, doc_id)
        assert await _page(api, doc_id) == (False, True)
        assert set(await _tax_zip(api)) == {doc_id}
        assert api.ctx.store.tax_choices() == {doc_id: True}


def _asked(calls: list[LLMRequest]) -> list[dict[str, Any]]:
    return [call.model_dump(mode="json", by_alias=True) for call in calls]


async def test_read_again_asks_claude_the_same_with_or_without_a_choice(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await _read(api, TAX_LETTER.pdf(), "bescheid.pdf")
        without = await _read_again(api, doc_id)
        assert without and {call.purpose for call in without} >= {"extract"}
        for choice in (False, True):
            await _choose(api, doc_id, choice)
            assert _asked(await _read_again(api, doc_id)) == _asked(without), choice
        assert api.ctx.store.tax_choices() == {doc_id: True}


# --------------------------------------------------------------------------------------------------
# Ask and the weekly review follow the choice, for the letters they may read (point 4)
# --------------------------------------------------------------------------------------------------

#: Ask's ledger fingerprint of the demo without a choice (as at 0.3.0, before Ask read the choices).
DEMO_FINGERPRINT = "6d63e0d2ead937a6c8e4fd974c537b368c20101035bd70fc8f1038096a550b08"


@pytest.fixture
def demo_store(tmp_path: Path) -> Iterator[Store]:
    """A copy of the demo's database: its letters, 6 of them marked by Claude (each with a note), no choice."""
    data = tmp_path / "demo"
    data.mkdir()
    shutil.copy2(DEMO_DB, data / "ordnung.db")
    store = Store.open(Paths(data))
    yield store
    store.close()


def test_a_tax_choice_moves_asks_fingerprint_and_token_and_clearing_it_gives_the_old_hash_back(
    demo_store: Store,
) -> None:
    """Ask's get_document says what the person chose, so each choice moves Ask's ledger fingerprint and its
    ledger token (a question asked before is not answered from the cache); without any choice the fingerprint
    is the one every recording was made with."""
    from ordnung.assistant.ask import _LEDGER_MEMO

    store = demo_store
    letters = store.list_documents()
    marked = next(doc for doc in letters if doc.tax_relevant)
    unmarked = next(doc for doc in letters if not doc.tax_relevant)
    assert ledger_fingerprint(store) == DEMO_FINGERPRINT
    seen = {DEMO_FINGERPRINT}
    for doc_id, choice in ((marked.id, False), (unmarked.id, True), (marked.id, None)):
        token = store.ledger_token()
        assert store.set_tax_choice(doc_id, choice) is True
        assert store.ledger_token() != token, (doc_id, choice)
        fingerprint = ledger_fingerprint(store)
        assert fingerprint not in seen and _LEDGER_MEMO.fingerprint(store) == fingerprint, (doc_id, choice)
        seen.add(fingerprint)
    assert store.tax_choices() == {unmarked.id: True}
    assert store.set_tax_choice(unmarked.id, None) is True
    assert ledger_fingerprint(store) == _LEDGER_MEMO.fingerprint(store) == DEMO_FINGERPRINT


#: One call of every Ask tool (``TOOL_NAMES``) over the seeded ledger, but those ``leaving_out``.
def _every_tool(tools: LedgerTools, ids: dict[str, str], *leaving_out: str) -> dict[str, Any]:
    calls: dict[str, Callable[[], Any]] = {
        "search": lambda: tools.search("tax assessment"),
        "get_document": lambda: tools.get_document(ids["doc_tax"]),
        "list_items": lambda: tools.list_items(status="all"),
        "list_contracts": lambda: tools.list_contracts(status="all"),
        "get_party": lambda: tools.get_party(ids["finanzamt"]),
        "timeline": lambda: tools.timeline("2025-10-01", "2027-09-30"),
        "money_summary": tools.money_summary,
        "explain_date": lambda: tools.explain_date(ids["tax_objection"]),
        "get_profile": tools.get_profile,
        "today": tools.today,
        "get_my_numbers": tools.get_my_numbers,
    }
    return {name: call() for name, call in calls.items() if name not in leaving_out}


def test_get_document_says_for_taxes_as_the_person_chose(store: Store) -> None:
    """Ask's get_document goes by the person's choice (point 1), and says when they made one. Without a choice
    a letter reads as Claude marked it, with Claude's note; marked by the person, it counts and says so (no
    note: Claude wrote none); taken off by the person, it doesn't count, says so, and Claude's note on why it
    could matter is left out of the letter text."""
    ids = seed_ledger(store)
    note = "Keep it for the 2026 tax return"
    store.update_document(ids["doc_tax"], tax_note=note)
    tools = LedgerTools(store, today=TODAY)

    def facts(doc_id: str) -> tuple[Any, Any, Any]:
        answer = tools.get_document(doc_id)
        record = parse_tool_result(render_result(answer)).record
        return record.get("tax_relevant"), record.get("tax_choice"), answer.letters[doc_id].get("tax_note")

    assert facts(ids["doc_tax"]) == (True, None, note)  # no choice, Claude's mark
    assert facts(ids["doc_invoice"]) == (None, None, None)  # no choice, no mark
    store.set_tax_choice(ids["doc_invoice"], True)
    assert facts(ids["doc_invoice"]) == (True, TAX_MARKED_BY_PERSON, None)
    store.set_tax_choice(ids["doc_tax"], False)
    assert facts(ids["doc_tax"]) == (None, TAX_UNMARKED_BY_PERSON, None)
    assert note not in render_result(tools.get_document(ids["doc_tax"]))
    store.set_tax_choice(ids["doc_tax"], True)  # the same as Claude's mark: still the person's choice
    assert facts(ids["doc_tax"]) == (True, TAX_MARKED_BY_PERSON, note)
    assert TAX_MARKED_BY_PERSON == "The person marked this letter for taxes themselves."
    assert TAX_UNMARKED_BY_PERSON == "The person took this letter off their letters for taxes."


def test_no_other_ask_tool_reads_the_tax_choices(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every Ask tool but get_document answers the same with the person's choices as without, and none of
    them reads the row while it runs (``Ledger.tax_choices`` is lazy): ``Store.tax_choices`` counts no call."""
    ids = seed_ledger(store)
    tools = LedgerTools(store, today=TODAY)
    before = _every_tool(tools, ids)
    assert set(before) == set(TOOL_NAMES)
    store.set_tax_choice(ids["doc_tax"], False)
    store.set_tax_choice(ids["doc_invoice"], True)
    calls: list[str] = []
    read = Store.tax_choices

    def counted(self: Store) -> dict[str, bool]:
        calls.append("tax_choices")
        return read(self)

    monkeypatch.setattr(Store, "tax_choices", counted)
    after = _every_tool(LedgerTools(store, today=TODAY), ids, "get_document")
    del before["get_document"]
    assert after == before
    assert calls == []
    LedgerTools(store, today=TODAY).get_document(ids["doc_tax"])
    assert calls == ["tax_choices"]


def test_a_private_letters_choice_never_reaches_ask(store: Store) -> None:
    """A letter the person keeps private gives Ask nothing of it, their choice included: its short record is
    the same with and without one."""
    ids = seed_ledger(store)
    tools = LedgerTools(store, today=TODAY)
    before = render_result(tools.get_document(ids["doc_private"]))
    for choice in (True, False):
        store.set_tax_choice(ids["doc_private"], choice)
        assert render_result(tools.get_document(ids["doc_private"])) == before, choice
    assert "tax" not in before


def test_without_a_choice_get_document_is_as_before(
    demo_store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A letter the person made no choice on reads exactly as it did before Ask followed the choices, whatever
    they chose on other letters: every demo letter's get_document equals the one with no choice at all. That
    holds for a letter Claude gave a note but no mark (its note still reaches Ask)."""
    from ordnung.secretary.triggers import Ledger

    store = demo_store
    letters = store.list_documents()
    noted = next(doc for doc in letters if not doc.tax_relevant)
    note = "Possibly useful for the tax return"
    store.update_document(noted.id, tax_note=note)
    marked = [doc for doc in letters if doc.tax_relevant]
    chosen = {
        marked[0].id: False,
        next(d for d in letters if not d.tax_relevant and d.id != noted.id).id: True,
    }
    tools = LedgerTools(store, today=TODAY)
    with monkeypatch.context() as patch:
        patch.setattr(Ledger, "tax_choices", property(lambda self: {}))
        before = {doc.id: render_result(tools.get_document(doc.id)) for doc in letters}
    for doc_id, choice in chosen.items():
        store.set_tax_choice(doc_id, choice)
    after = {doc.id: render_result(tools.get_document(doc.id)) for doc in letters}
    assert {doc_id for doc_id in before if after[doc_id] != before[doc_id]} == set(chosen)
    assert note in after[noted.id]
    assert '"tax_relevant"' not in after[noted.id].split("<untrusted_document>")[0]


def test_the_weekly_review_snapshot_follows_the_persons_tax_choice(store: Store) -> None:
    """The review's row of each letter says whether it counts for taxes as the Tax year page does (point 1):
    the person's choice, else Claude's mark. Without a choice the snapshot and its cache key are what they
    were; a choice flips that letter's ``tax_relevant`` alone; a private letter's choice changes nothing (it is
    never in the snapshot). In tax season the tax-season Idea follows the choice too (point 3), and its title is
    among the open Ideas the review is given, like every Idea's."""
    ids = seed_ledger(store)
    season = date(2027, 2, 15)
    idea = "Your 2026 tax documents are ready to collect"
    run_and_reconcile(store, season)
    before = build_snapshot(store, season)
    rows = {row["id"]: row for row in before.data["recent_documents"]}
    assert rows[ids["doc_tax"]]["tax_relevant"] is True and ids["doc_private"] not in rows
    assert idea in before.data["existing_ideas"]["open"]
    store.set_tax_choice(ids["doc_private"], True)
    assert build_snapshot(store, season).cache_key == before.cache_key
    store.set_tax_choice(ids["doc_private"], None)
    store.set_tax_choice(ids["doc_tax"], False)
    store.set_tax_choice(ids["doc_payslip"], False)
    run_and_reconcile(store, season)
    after = build_snapshot(store, season)
    flipped = {
        row["id"]: row["tax_relevant"] for row in after.data["recent_documents"] if row != rows[row["id"]]
    }
    assert flipped == {ids["doc_tax"]: False}  # the payslip is older than the review's recent letters
    assert idea not in after.data["existing_ideas"]["open"]
    # and back: the person's own mark brings it back
    store.set_tax_choice(ids["doc_tax"], True)
    run_and_reconcile(store, season)
    again = build_snapshot(store, season)
    assert idea in again.data["existing_ideas"]["open"]
    assert {row["id"]: row["tax_relevant"] for row in again.data["recent_documents"]}[ids["doc_tax"]] is True
    # every choice cleared: the snapshot and its key as before
    for doc_id in (ids["doc_tax"], ids["doc_payslip"]):
        store.set_tax_choice(doc_id, None)
    run_and_reconcile(store, season)
    cleared = build_snapshot(store, season)
    assert (cleared.data, cleared.cache_key) == (before.data, before.cache_key)
