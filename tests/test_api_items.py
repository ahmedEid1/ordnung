"""To-dos & dates over HTTP: manual dates (kept on reprocess), status changes, adding by hand,
"Yes, that's right", deleting, and the calendar files."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER
from helpers_secretary import add_doc, add_item
from ordnung import clock
from test_api_support import TODAY, Api, ApiRouter, api_for


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def _items_of(api: Api, data: bytes) -> list[dict[str, Any]]:
    body = await api.upload(("letter.pdf", data))
    await api.read_all()
    doc_id = body["documents"][0]["id"]
    return list((await api.client.get("/api/items", params={"doc_id": doc_id})).json())


def _by_kind(items: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(item for item in items if item["kind"] == kind)


async def test_manual_due_date_is_marked_and_survives_reprocess(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        payment = _by_kind(await _items_of(api, TAX_LETTER.pdf()), "payment")
        response = await api.client.patch(f"/api/items/{payment['id']}", json={"due_date": "2026-10-30"})
        assert response.status_code == 200
        item = response.json()
        assert item["due_date"] == "2026-10-30"
        assert item["due_date_source"] == "manual" and item["user_modified"] is True
        assert item["grounding"] == "user"
        assert item["send_by"] is not None and item["send_by"] < "2026-10-30"
        assert item["computation"]["summary"] == "You set this date yourself."

        await api.client.post(f"/api/documents/{item['doc_id']}/reprocess")
        await api.read_all()
        kept = (
            await api.client.get("/api/items", params={"doc_id": item["doc_id"], "kind": "payment"})
        ).json()
        assert kept[0]["due_date"] == "2026-10-30"

        cleared = (await api.client.patch(f"/api/items/{payment['id']}", json={"due_date": None})).json()
        assert cleared["due_date"] is None and cleared["due_date_source"] == "none"


async def test_status_changes_are_explicit(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        payment = _by_kind(await _items_of(api, TAX_LETTER.pdf()), "payment")
        url = f"/api/items/{payment['id']}"
        done = (await api.client.patch(url, json={"status": "done"})).json()
        assert done["status"] == "done" and done["completed_at"] is not None
        assert done["user_modified"] is False  # a status is not an edit of the letter's facts

        reopened = (await api.client.patch(url, json={"status": "open"})).json()
        assert reopened["status"] == "open" and reopened["completed_at"] is None

        snoozed = (await api.client.patch(url, json={"snoozed_until": "2026-10-01"})).json()
        assert (snoozed["status"], snoozed["snoozed_until"]) == ("snoozed", "2026-10-01")
        default = (await api.client.patch(url, json={"status": "snoozed"})).json()
        assert default["snoozed_until"] == "2026-10-02"

        renamed = (await api.client.patch(url, json={"title": "Pay the tax", "notes": "From savings"})).json()
        assert (renamed["title"], renamed["description"]) == ("Pay the tax", "From savings")
        assert renamed["user_modified"] is True

        for bad in ({"status": "gone"}, {"title": ""}, {"due_date": "tomorrow"}, {"id": "itm_x"}):
            assert (await api.client.patch(url, json=bad)).status_code == 422, bad
        assert (await api.client.patch("/api/items/itm_unknown", json={"status": "done"})).status_code == 404


async def test_add_list_and_delete_by_hand(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        created = await api.client.post(
            "/api/items",
            json={"kind": "payment", "title": "Pay the rent", "due_date": "2026-10-01", "amount": 650.0},
        )
        assert created.status_code == 201
        item = created.json()
        assert (item["origin"], item["grounding"], item["due_date_source"]) == ("manual", "user", "manual")
        assert item["filed_on"] == TODAY and item["send_by"] is not None
        task = (await api.client.post("/api/items", json={"kind": "task", "title": "Sort the drawer"})).json()
        assert task["due_date"] is None and task["due_date_source"] == "none"

        everything = (await api.client.get("/api/items")).json()
        assert {entry["id"] for entry in everything} == {item["id"], task["id"]}
        ranged = (
            await api.client.get("/api/items", params={"from": "2026-09-01", "to": "2026-12-31"})
        ).json()
        assert [entry["id"] for entry in ranged] == [item["id"]]
        with_undated = await api.client.get(
            "/api/items", params={"from": "2026-09-01", "include_undated": "true"}
        )
        assert len(with_undated.json()) == 2

        bad_link = await api.client.post(
            "/api/items", json={"kind": "task", "title": "x", "party_id": "pty_x"}
        )
        assert bad_link.status_code == 404
        assert (await api.client.post("/api/items", json={"kind": "task"})).status_code == 422

        fetched = await api.client.get(f"/api/items/{item['id']}")
        assert fetched.status_code == 200 and fetched.json() == item
        assert (await api.client.get("/api/items/itm_unknown")).status_code == 404

        deleted = await api.client.delete(f"/api/items/{task['id']}")
        assert deleted.status_code == 204 and deleted.content == b""
        assert [entry["id"] for entry in (await api.client.get("/api/items")).json()] == [item["id"]]
        assert (await api.client.delete(f"/api/items/{task['id']}")).status_code == 404
        assert (await api.client.get("/api/activity", params={"limit": 1})).json()[0][
            "kind"
        ] == "item.deleted"


async def test_the_list_says_which_to_dos_are_set_aside(data_dir: Path) -> None:
    """UI audit R2-inbox-timeline-contracts-2: the Inbox counted an invoice payment its payment reminder took
    over as "1 to-do" and showed it as the letter's next step, "25 days overdue" — the list said nothing of
    what Today, the verdict and the party drawer set aside. Each listed to-do now says so (``aside``)."""
    async with api_for(data_dir) as api:
        store = api.ctx.store
        party = store.add_party(name="TechMarkt Online GmbH", kind="retailer").id
        case = store.add_case(title="Invoice TM-4711", party_id=party, reference="TM-4711").id
        refs = [{"label": "Rechnungsnummer", "value": "TM-4711"}]
        letter = {"party_id": party, "case_id": case, "references": refs}
        invoice = add_doc(store, "invoice", kind="invoice", doc_date="2026-08-20", **letter)
        reminder = add_doc(store, "reminder", kind="dunning", doc_date="2026-09-10", **letter)
        money = {"kind": "payment", "direction": "out", "party_id": party}
        replaced = add_item(
            store,
            title="Pay the invoice",
            due_date="2026-09-03",
            filed_on="2026-08-21",
            doc_id=invoice,
            **money,
        )
        due = add_item(
            store,
            title="Pay the reminder",
            due_date="2026-09-30",
            filed_on="2026-09-11",
            doc_id=reminder,
            **money,
        )
        lease = add_doc(store, "lease", kind="rent_lease", doc_date="2025-09-15", party_id=party)
        history = add_item(
            store, title="Security deposit", due_date="2025-10-01", filed_on=TODAY, doc_id=lease, **money
        )

        listed = {
            item["id"]: item
            for item in (await api.client.get("/api/items", params={"status": "open"})).json()
        }
        assert listed[replaced]["aside"] == {
            "item_id": replaced,
            "reason": "replaced",
            "replaced_by": reminder,
        }
        assert listed[history]["aside"] == {"item_id": history, "reason": "history", "replaced_by": None}
        assert listed[due]["aside"] is None
        assert (
            "aside" not in (await api.client.get(f"/api/items/{replaced}")).json()
        )  # worked out for the list


async def test_confirming_the_last_unchecked_date_clears_please_check(data_dir: Path) -> None:
    router = ApiRouter()
    router.payloads["Ihre Rechnung"]["items"][0]["quote"] = "Zahlen Sie bis zum 15.09.2026 an uns."
    async with api_for(data_dir, router=router) as api:
        (payment,) = await _items_of(api, INVOICE_LETTER.pdf())
        assert payment["grounding"] == "unverified"
        doc_url = f"/api/documents/{payment['doc_id']}"
        assert (await api.client.get(doc_url)).json()["document"]["status"] == "needs_review"

        confirmed = await api.client.post(f"/api/items/{payment['id']}/confirm")
        assert confirmed.status_code == 200
        assert confirmed.json()["grounding"] == "user" and confirmed.json()["user_modified"] is True
        assert (await api.client.get(doc_url)).json()["document"]["status"] == "processed"
        assert (await api.client.post("/api/items/itm_unknown/confirm")).status_code == 404


async def test_calendar_files(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        payment = _by_kind(await _items_of(api, TAX_LETTER.pdf()), "payment")
        single = await api.client.get(f"/api/items/{payment['id']}.ics")
        assert single.status_code == 200
        assert single.headers["content-type"] == "text/calendar; charset=utf-8"
        assert single.headers["content-disposition"].startswith("attachment")
        assert "BEGIN:VCALENDAR" in single.text and "Pay the income tax" in single.text

        task = (await api.client.post("/api/items", json={"kind": "task", "title": "Undated"})).json()
        assert (await api.client.get(f"/api/items/{task['id']}.ics")).status_code == 422
        assert (await api.client.get("/api/items/itm_unknown.ics")).status_code == 404

        feed = await api.client.get("/api/calendar.ics")
        assert feed.status_code == 200
        assert feed.headers["content-type"] == "text/calendar; charset=utf-8"
        assert feed.text.count("BEGIN:VEVENT") >= 2

        exported = await api.client.post("/api/calendar/exported")
        assert exported.status_code == 200
        assert exported.json()["last_calendar_export_at"].endswith("Z")
