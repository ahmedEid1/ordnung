"""*For taxes* on any letter (D3, ``secretary.tax_choice``): the person's own choice counts over Claude's
mark, both ways, survives *Read again*, and changes nothing Claude is asked — neither the reading, nor Ask's
inputs (its fingerprint, its ledger token, its tools), nor the weekly review's snapshot.

The store's side (set, clear, unchanged writes nothing, unreadable rows, the purge and the trash) is in
``tests/test_store_choices.py``; the route's refusals and the phone in ``tests/test_api_documents.py``.
"""

from __future__ import annotations

import csv
import io
import shutil
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER
from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.assistant.ask import ledger_fingerprint
from ordnung.assistant.mcp_server import TOOL_NAMES, LedgerTools
from ordnung.config import Paths
from ordnung.db.store import TAX_CHOICES_META_KEY, Store
from ordnung.letters_zip import INDEX_NAME
from ordnung.llm.base import LLMRequest
from ordnung.secretary.review import build_snapshot
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
# Ask and the weekly review keep Claude's own mark: their inputs are recorded
# --------------------------------------------------------------------------------------------------


def test_a_tax_choice_leaves_asks_fingerprint_and_ledger_token_as_they_were(tmp_path: Path) -> None:
    """On a copy of the demo's database (its letters, 6 of them marked by Claude): marking, unmarking and
    clearing moves neither Ask's ledger fingerprint nor its ledger token."""
    data = tmp_path / "demo"
    data.mkdir()
    shutil.copy2(DEMO_DB, data / "ordnung.db")
    store = Store.open(Paths(data))
    try:
        letters = store.list_documents()
        marked = next(doc for doc in letters if doc.tax_relevant)
        unmarked = next(doc for doc in letters if not doc.tax_relevant)
        fingerprint, token = ledger_fingerprint(store), store.ledger_token()
        for doc_id, choice in ((marked.id, False), (unmarked.id, True), (marked.id, None)):
            assert store.set_tax_choice(doc_id, choice) is True
            assert store.ledger_token() == token, (doc_id, choice)
            assert ledger_fingerprint(store) == fingerprint, (doc_id, choice)
        assert store.tax_choices() == {unmarked.id: True}
    finally:
        store.close()


#: One call of every Ask tool (``TOOL_NAMES``) over the seeded ledger.
def _every_tool(tools: LedgerTools, ids: dict[str, str]) -> dict[str, Any]:
    return {
        "search": tools.search("tax assessment"),
        "get_document": tools.get_document(ids["doc_tax"]),
        "list_items": tools.list_items(status="all"),
        "list_contracts": tools.list_contracts(status="all"),
        "get_party": tools.get_party(ids["finanzamt"]),
        "timeline": tools.timeline("2025-10-01", "2027-09-30"),
        "money_summary": tools.money_summary(),
        "explain_date": tools.explain_date(ids["tax_objection"]),
        "get_profile": tools.get_profile(),
        "today": tools.today(),
        "get_my_numbers": tools.get_my_numbers(),
    }


def test_asks_tools_never_read_the_tax_choices(store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every Ask tool answers the same with the person's choices as without, and none of them reads the
    row: ``Store.tax_choices`` and a read of the row raise while they run (``Ledger.tax_choices`` is lazy)."""
    ids = seed_ledger(store)
    tools = LedgerTools(store, today=TODAY)
    before = _every_tool(tools, ids)
    assert set(before) == set(TOOL_NAMES)
    store.set_tax_choice(ids["doc_tax"], False)
    store.set_tax_choice(ids["doc_invoice"], True)

    def never(*_args: object) -> dict[str, bool]:
        raise AssertionError("Ask read the person's tax choices")

    get_meta = Store.get_meta

    def guarded_get_meta(self: Store, key: str) -> str | None:
        if key == TAX_CHOICES_META_KEY:
            raise AssertionError("Ask read the person's tax choices")
        return get_meta(self, key)

    monkeypatch.setattr(Store, "tax_choices", never)
    monkeypatch.setattr(Store, "get_meta", guarded_get_meta)
    after = _every_tool(LedgerTools(store, today=TODAY), ids)
    assert after == before
    assert ledger_fingerprint(store)


def test_the_weekly_review_snapshot_keeps_claudes_own_mark(store: Store) -> None:
    """The review's per-letter snapshot keeps ``tax_relevant`` as Claude read it: the person's choice would
    change the review's input and its recordings (plan §11)."""
    ids = seed_ledger(store)
    before = build_snapshot(store, TODAY)
    assert any(row["tax_relevant"] for row in before.data["recent_documents"])
    store.set_tax_choice(ids["doc_tax"], False)
    store.set_tax_choice(ids["doc_payslip"], False)
    store.set_tax_choice(ids["doc_invoice"], True)
    after = build_snapshot(store, TODAY)
    assert after.data == before.data
    assert after.cache_key == before.cache_key
