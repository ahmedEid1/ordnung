"""The same press sent twice (a double click, Enter twice, a retry, a second tab, the phone and the computer
at once) changes no more than one press: a repeating to-do marked done moves on one occurrence, not two, when
the page says which occurrence it saw (``seen_due_date``); a page that does not say is answered as before."""

from __future__ import annotations

import asyncio
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import helpers_proof
from helpers_docs import photo
from ordnung import clock
from ordnung.api.routes.items import MOVED_ON, UNCHANGED_HEADER
from test_api_proof import _sent
from test_api_support import TODAY, Api, api_for

MONTHLY = {"interval": 1, "unit": "months"}
DEMO_DB = Path(__file__).resolve().parents[1] / "src" / "ordnung" / "demo" / "demo_db"
BROADCASTING_FEE = "itm_xna048xewpad"  # the demo's quarterly fee, read from its letter: next on 15 Nov 2026


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)  # Fri 25 Sep 2026
    yield
    clock.set_today(None)


async def _patch(api: Api, item_id: str, **patch: Any) -> dict[str, Any]:
    response = await api.client.patch(f"/api/items/{item_id}", json=patch)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _club_fee(api: Api) -> dict[str, Any]:
    body = {
        "kind": "payment",
        "title": "Club fee",
        "due_date": "2026-10-01",
        "recurrence": MONTHLY,
        "amount": 20.0,
        "direction": "out",
    }
    response = await api.client.post("/api/items", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


def _log(api: Api, item_id: str) -> list[str]:
    return [entry.kind for entry in api.ctx.store.list_activity(None) if entry.ref_id == item_id]


async def test_done_twice_for_the_date_seen_moves_on_once(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        fee = await _club_fee(api)
        first = await _patch(api, fee["id"], status="done", seen_due_date="2026-10-01")
        assert (first["status"], first["due_date"]) == ("open", "2026-11-01")
        again = await _patch(api, fee["id"], status="done", seen_due_date="2026-10-01")
        # nothing more changes, and the answer is the to-do as it is: at the date the first press moved it to
        assert again == first
        assert _log(api, fee["id"]).count("item.done") == 1
        # its "Undo" brings back the occurrence paid, once
        undone = await _patch(api, fee["id"], status="open", seen_due_date="2026-11-01")
        assert undone["due_date"] == "2026-10-01"
        assert (await _patch(api, fee["id"], status="open", seen_due_date="2026-11-01"))[
            "due_date"
        ] == "2026-10-01"
        assert _log(api, fee["id"]).count("item.reopened") == 1


async def test_one_press_does_what_it_did_before(data_dir: Path) -> None:
    """The date sent with one honest press changes nothing about what it does; an older page sends none."""
    async with api_for(data_dir) as api:
        told = await _club_fee(api)
        untold = await _club_fee(api)
        seen = await _patch(api, told["id"], status="done", seen_due_date="2026-10-01")
        before = await _patch(api, untold["id"], status="done")
        keep = ("status", "due_date", "send_by", "completed_at", "computation")
        assert {k: seen[k] for k in keep} == {k: before[k] for k in keep}
        assert {
            k: (await _patch(api, told["id"], status="open", seen_due_date="2026-11-01"))[k] for k in keep
        } == {k: (await _patch(api, untold["id"], status="open"))[k] for k in keep}


async def test_an_older_page_that_sends_no_date_is_answered_as_before(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        fee = await _club_fee(api)
        await _patch(api, fee["id"], status="done")
        assert (await _patch(api, fee["id"], status="done"))["due_date"] == "2026-12-01"


async def test_the_answer_says_when_nothing_changed(data_dir: Path) -> None:
    """The second "done" is answered 200 with the to-do as it stands, as before, and says it changed nothing, so the
    page tells the person instead of "Marked as done" with an Undo that would take back the first one."""
    async with api_for(data_dir) as api:
        fee = await _club_fee(api)
        url = f"/api/items/{fee['id']}"
        first = await api.client.patch(url, json={"status": "done", "seen_due_date": "2026-10-01"})
        assert UNCHANGED_HEADER not in first.headers
        again = await api.client.patch(url, json={"status": "done", "seen_due_date": "2026-10-01"})
        assert again.status_code == 200 and again.headers[UNCHANGED_HEADER] == MOVED_ON
        assert again.json()["due_date"] == "2026-11-01"
        # a stale "open again" too, and a "done" for a date another tab changed: nothing was marked
        stale_undo = await api.client.patch(url, json={"status": "open", "seen_due_date": "2026-12-01"})
        assert stale_undo.headers[UNCHANGED_HEADER] == MOVED_ON
        await _patch(api, fee["id"], due_date="2026-11-20")
        moved = await api.client.patch(url, json={"status": "done", "seen_due_date": "2026-11-01"})
        assert moved.headers[UNCHANGED_HEADER] == MOVED_ON
        assert (moved.json()["status"], moved.json()["due_date"]) == ("open", "2026-11-20")
        # an honest press, and an older page that sends no date, are answered without it
        honest = await api.client.patch(url, json={"status": "done", "seen_due_date": "2026-11-20"})
        assert UNCHANGED_HEADER not in honest.headers
        assert UNCHANGED_HEADER not in (await api.client.patch(url, json={"status": "done"})).headers


async def test_done_twice_at_the_same_moment_moves_on_once(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The phone and the computer at once: read and written in one transaction, the second sees the first.

    The first two reads of the to-do wait for each other once they have read (briefly): read outside the
    transaction, both read it at 1 Oct and both move it on; read inside, the second can only read once the first
    has written, so the first goes on alone when the wait runs out."""
    async with api_for(data_dir) as api:
        fee = await _club_fee(api)
        store = api.ctx.store
        get_item = store.get_item
        meet = threading.Barrier(2, timeout=2)
        reads = iter(range(2))

        def read_together(item_id: str) -> Any:
            read = get_item(item_id)
            if item_id == fee["id"] and next(reads, None) is not None:
                try:
                    meet.wait()  # each has read before either goes on
                except threading.BrokenBarrierError:
                    pass  # the other read is behind the write lock (or came after the wait ran out)
            return read

        monkeypatch.setattr(store, "get_item", read_together)
        body = {"status": "done", "seen_due_date": "2026-10-01"}
        one, two = await asyncio.gather(
            api.client.patch(f"/api/items/{fee['id']}", json=body),
            api.client.patch(f"/api/items/{fee['id']}", json=body),
        )
        assert (one.status_code, two.status_code) == (200, 200)
        assert one.json()["due_date"] == two.json()["due_date"] == "2026-11-01"
        stored = api.ctx.store.get_item(fee["id"])
        assert stored is not None and stored.due_date == "2026-11-01"


async def test_a_quarterly_fee_read_from_its_letter_keeps_its_date(tmp_path: Path) -> None:
    """The demo's broadcasting fee went from 15 Nov 2026 to 15 May 2027 for a double press: 15 Feb now."""
    clock.set_today("2026-09-28")
    data = tmp_path / "data"
    shutil.copytree(DEMO_DB, data)
    async with api_for(data, demo=True) as api:
        seen = (await api.client.get(f"/api/items/{BROADCASTING_FEE}")).json()["due_date"]
        assert seen == "2026-11-15"
        first = await _patch(api, BROADCASTING_FEE, status="done", seen_due_date=seen)
        again = await _patch(api, BROADCASTING_FEE, status="done", seen_due_date=seen)
        assert first["due_date"] == again["due_date"] == "2027-02-15"
        assert (await _patch(api, BROADCASTING_FEE, status="open", seen_due_date="2027-02-15"))[
            "due_date"
        ] == seen


async def test_the_date_seen_counts_only_where_a_press_moves_a_schedule(data_dir: Path) -> None:
    """A to-do that does not repeat is done or open whatever date is sent with it, and a date edit or a snooze
    sent with one goes through: only a press that would move a repeating to-do on (or back) is checked."""
    async with api_for(data_dir) as api:
        created = await api.client.post(
            "/api/items", json={"kind": "reminder", "title": "Dentist", "due_date": "2026-10-07"}
        )
        once = created.json()
        done = await _patch(api, once["id"], status="done", seen_due_date="2026-01-01")
        assert done["status"] == "done"
        assert (await _patch(api, once["id"], status="open", seen_due_date="2026-01-01"))["status"] == "open"
        fee = await _club_fee(api)
        snoozed = await _patch(api, fee["id"], snoozed_until="2026-10-05", seen_due_date="2026-09-01")
        assert (snoozed["status"], snoozed["snoozed_until"]) == ("snoozed", "2026-10-05")


async def test_said_answered_twice_keeps_a_snoozed_follow_up_snoozed_after_undo(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        (followup,) = [
            i for i in api.ctx.store.list_items() if i.origin != "extracted" and i.kind != "appointment"
        ]
        await _patch(api, followup.id, snoozed_until="2026-10-30")
        for _ in range(2):
            answered = await api.client.post(f"/api/drafts/{draft_id}/answered", json={"doc_id": None})
            assert answered.status_code == 200, answered.text
        assert api.ctx.store.get_item(followup.id).status == "done"  # type: ignore[union-attr]
        assert [e.kind for e in api.ctx.store.list_activity(None)].count("draft.answered") == 1
        undone = await api.client.delete(f"/api/drafts/{draft_id}/answered")
        assert undone.status_code == 200, undone.text
        back = api.ctx.store.get_item(followup.id)
        assert back is not None and (back.status, back.snoozed_until) == ("snoozed", "2026-10-30")


async def test_said_answered_again_later_is_a_new_answer(data_dir: Path) -> None:
    """Only the same answer said twice changes nothing: another letter named later is the answer from that day, and
    a follow-up opened again since is closed again."""
    async with api_for(data_dir) as api:
        draft_id, gym = await _sent(api)
        url = f"/api/drafts/{draft_id}/answered"
        (followup,) = [
            i for i in api.ctx.store.list_items() if i.origin != "extracted" and i.kind != "appointment"
        ]
        assert (await api.client.post(url, json={"doc_id": None})).status_code == 200
        await _patch(api, followup.id, status="open")  # the answer didn't settle it after all
        clock.set_today("2026-10-02")
        assert (await api.client.post(url, json={"doc_id": None})).status_code == 200
        assert api.ctx.store.get_item(followup.id).status == "done"  # type: ignore[union-attr]
        clock.set_today("2026-10-09")
        letter = helpers_proof.incoming(
            api.ctx,
            "reply",
            kind="other",
            title="Kündigungsbestätigung",
            party_id=gym.party,
            case_id=gym.case,
        )
        assert (await api.client.post(url, json={"doc_id": letter})).status_code == 200
        (draft,) = [d for d in api.ctx.store.list_drafts() if d.id == draft_id]
        assert (draft.answered_on, draft.answer_doc_id) == ("2026-10-09", letter)


async def test_the_same_proof_sent_twice_at_once_is_added_once(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        url = f"/api/drafts/{draft_id}/proofs"
        before = len(api.ctx.store.list_proofs(draft_id))
        data = photo("PNG")
        one, two = await asyncio.gather(
            api.client.post(url, files={"file": ("receipt.png", data)}, data={"kind": "posting_receipt"}),
            api.client.post(url, files={"file": ("receipt.png", data)}, data={"kind": "posting_receipt"}),
        )
        assert sorted((one.status_code, two.status_code)) == [201, 422]
        assert len(api.ctx.store.list_proofs(draft_id)) == before + 1
