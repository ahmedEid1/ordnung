"""Recurring obligations in realistic histories, through the API and the daily tick (ordnung.recurrence).

Rent paid six months in a row, a direct debit nobody ever touches, a weekly appointment series, a
letter read again in between and a date set by hand. Ordnung cannot see payments, so each series
always shows its next occurrence and never turns overdue; the policy's points are pinned one by one
in ``test_recurrence.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER
from ordnung import clock
from ordnung.db.store import Store
from ordnung.llm.runtime import LLMService
from ordnung.tick import DailyTick
from test_api_support import Api, ApiRouter, api_for

MONTHLY = {"interval": 1, "unit": "months"}


@pytest.fixture(autouse=True)
def unpinned_after_test() -> Iterator[None]:
    yield
    clock.set_today(None)


@dataclass
class _TickContext:
    store: Store
    llm: LLMService | None = None
    bus: None = None


async def _tick(api: Api, day: str) -> None:
    """The day's tick, as the app runs it when the date changes (without the model)."""
    clock.set_today(day)
    assert (await DailyTick(_TickContext(api.ctx.store)).check()).day_changed


async def _items(api: Api, **params: str) -> list[dict[str, Any]]:
    response = await api.client.get("/api/items", params=params)
    assert response.status_code == 200, response.text
    return list(response.json())


async def _overdue_ideas(api: Api) -> list[str]:
    ideas = (await api.client.get("/api/suggestions", params={"status": "new"})).json()
    return [idea["title"] for idea in ideas if idea["rule_id"] == "overdue"]


async def _patch(api: Api, item_id: str, **patch: Any) -> dict[str, Any]:
    response = await api.client.patch(f"/api/items/{item_id}", json=patch)
    assert response.status_code == 200, response.text
    return dict(response.json())


def _done_messages(api: Api) -> list[str]:
    return [entry.message for entry in reversed(api.ctx.store.list_activity()) if entry.kind == "item.done"]


async def test_rent_paid_six_months_in_a_row(data_dir: Path) -> None:
    """Each "Mark as paid" moves the rent on by exactly one month; it stays open and never overdue."""
    clock.set_today("2026-09-25")
    async with api_for(data_dir) as api:
        created = await api.client.post(
            "/api/items",
            json={
                "kind": "payment",
                "title": "Rent",
                "due_date": "2026-10-01",
                "amount": 650.0,
                "recurrence": MONTHLY,
            },
        )
        assert created.status_code == 201, created.text
        rent = created.json()

        paid_on = ["2026-09-28", "2026-10-28", "2026-11-27", "2026-12-28", "2027-01-28", "2027-02-26"]
        for day, expected in zip(
            paid_on,
            ["2026-11-01", "2026-12-01", "2027-01-01", "2027-02-01", "2027-03-01", "2027-04-01"],
            strict=True,
        ):
            await _tick(api, day)
            after = await _patch(api, rent["id"], status="done")
            assert (after["status"], after["due_date"], after["completed_at"]) == ("open", expected, None)
            assert after["computation"]["summary"].startswith("Repeats every month since Thu 1 Oct 2026;")
            assert await _overdue_ideas(api) == []

        assert _done_messages(api) == [
            "Paid “Rent” (Thu 1 Oct 2026) — next on Sun 1 Nov 2026",
            "Paid “Rent” (Sun 1 Nov 2026) — next on Tue 1 Dec 2026",
            "Paid “Rent” (Tue 1 Dec 2026) — next on Fri 1 Jan 2027",
            "Paid “Rent” (Fri 1 Jan 2027) — next on Mon 1 Feb 2027",
            "Paid “Rent” (Mon 1 Feb 2027) — next on Mon 1 Mar 2027",
            "Paid “Rent” (Mon 1 Mar 2027) — next on Thu 1 Apr 2027",
        ]
        assert [item["id"] for item in await _items(api, status="open")] == [rent["id"]]  # one series


async def test_a_direct_debit_nobody_touches_always_shows_the_next_collection(data_dir: Path) -> None:
    """The sender collects it every month; the person never opens it. Each day's tick shows the next
    collection with the engine's dates; it is never overdue and never an Idea to act on."""
    clock.set_today("2026-09-10")
    router = ApiRouter()
    payment = router.payloads[INVOICE_LETTER.marker]["items"][0]
    payment |= {"recurrence": MONTHLY, "action": "Wird monatlich per Lastschrift von Ihrem Konto abgebucht"}
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("rechnung.pdf", INVOICE_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [debit] = await _items(api, doc_id=doc_id)
        assert debit["due_date"] == "2026-09-15"

        seen = []
        for day in ["2026-09-16", "2026-10-16", "2026-11-16", "2026-12-16", "2027-01-16", "2027-02-16"]:
            await _tick(api, day)
            [debit] = await _items(api, doc_id=doc_id)
            seen.append((debit["status"], debit["due_date"], debit["due_date_source"]))
            assert await _overdue_ideas(api) == []
            dashboard = (await api.client.get("/api/dashboard")).json()
            assert all(item["id"] != debit["id"] for item in dashboard["attention"])
        assert seen == [
            ("open", "2026-10-15", "fixed"),
            ("open", "2026-11-15", "fixed"),
            ("open", "2026-12-15", "fixed"),
            ("open", "2027-01-15", "fixed"),
            ("open", "2027-02-15", "fixed"),
            ("open", "2027-03-15", "fixed"),
        ]
        assert (
            debit["computation"]["summary"]
            == "Repeats every month since Tue 15 Sep 2026; next on Mon 15 Mar 2027."
        )


async def test_a_weekly_appointment_series_moves_on_attended_or_not(data_dir: Path) -> None:
    clock.set_today("2026-10-01")
    async with api_for(data_dir) as api:
        created = await api.client.post(
            "/api/items",
            json={
                "kind": "appointment",
                "title": "Physiotherapy",
                "due_date": "2026-10-05",
                "due_time": "17:00",
                "recurrence": {"interval": 1, "unit": "weeks"},
            },
        )
        series = created.json()

        await _tick(api, "2026-10-05")
        attended = await _patch(api, series["id"], status="done")
        assert (attended["status"], attended["due_date"]) == ("open", "2026-10-12")
        assert _done_messages(api) == ["Done “Physiotherapy” (Mon 5 Oct 2026) — next on Mon 12 Oct 2026"]

        await _tick(api, "2026-10-13")  # nobody ticked the 12th off: the series simply continues
        [item] = await _items(api, status="open")
        assert item["due_date"] == "2026-10-19"
        await _tick(api, "2026-10-27")
        [item] = await _items(api, status="open")
        assert (item["due_date"], item["due_time"]) == ("2026-11-02", "17:00")

        dismissed = await _patch(api, series["id"], status="dismissed")  # the treatment ended
        assert dismissed["status"] == "dismissed"
        await _tick(api, "2026-11-20")
        assert (await api.client.get(f"/api/items/{series['id']}")).json()["due_date"] == "2026-11-02"


async def test_reading_the_letter_again_in_between_never_moves_the_payment_back(data_dir: Path) -> None:
    """A monthly payment (15th, from 15 Oct): December is paid early, so it waits for January. Reading
    the letter again (also when the model quotes the sentence differently), confirming its arrival
    date and the next ticks all keep January."""
    clock.set_today("2026-11-20")
    router = ApiRouter()
    payment = next(item for item in router.payloads[TAX_LETTER.marker]["items"] if item["kind"] == "payment")
    payment["recurrence"] = MONTHLY
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("steuer.pdf", TAX_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [item] = await _items(api, doc_id=doc_id, kind="payment")
        assert (item["due_date"], item["send_by"]) == ("2026-12-15", "2026-12-14")
        paid = await _patch(api, item["id"], status="done")
        assert (paid["status"], paid["due_date"]) == ("open", "2027-01-15")

        async def january() -> None:
            [after] = await _items(api, doc_id=doc_id, kind="payment")
            assert (after["id"], after["status"], after["due_date"]) == (item["id"], "open", "2027-01-15")

        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        await january()

        payment["quote"] = "Bitte zahlen Sie den Betrag von 1.234,56 EUR"  # the same sentence, quoted shorter
        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        await january()

        confirmed = await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-17"})
        assert confirmed.status_code == 200
        await january()

        await _tick(api, "2026-12-16")
        await january()
        await _tick(api, "2027-01-16")  # January passed unpaid (Ordnung can't see it): February shows
        [after] = await _items(api, doc_id=doc_id, kind="payment")
        assert (after["status"], after["due_date"]) == ("open", "2027-02-15")


async def test_a_date_set_by_hand_is_kept_until_it_passes(data_dir: Path) -> None:
    """The letter's payment falls on Sunday 15 Nov; the person pays it on the 17th and says so. The
    17th stays until it has passed; then the letter's schedule (the 15th) applies again."""
    clock.set_today("2026-11-10")
    router = ApiRouter()
    payment = next(item for item in router.payloads[TAX_LETTER.marker]["items"] if item["kind"] == "payment")
    payment["recurrence"] = MONTHLY
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("steuer.pdf", TAX_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [item] = await _items(api, doc_id=doc_id, kind="payment")
        assert item["due_date"] == "2026-11-15"
        moved = await _patch(api, item["id"], due_date="2026-11-17")
        assert (moved["due_date"], moved["due_date_source"]) == ("2026-11-17", "manual")

        await _tick(api, "2026-11-17")
        [kept] = await _items(api, doc_id=doc_id, kind="payment")
        assert (kept["due_date"], kept["due_date_source"]) == ("2026-11-17", "manual")
        assert await _overdue_ideas(api) == []

        await _tick(api, "2026-11-18")
        [back] = await _items(api, doc_id=doc_id, kind="payment")
        assert (back["due_date"], back["send_by"], back["due_date_source"]) == (
            "2026-12-15",
            "2026-12-14",
            "fixed",
        )


async def test_a_to_do_added_by_hand_keeps_its_schedule_when_one_date_is_moved(data_dir: Path) -> None:
    """Rent on the 1st, this month moved to the 3rd by hand: December is on the 1st again."""
    clock.set_today("2026-10-20")
    async with api_for(data_dir) as api:
        created = await api.client.post(
            "/api/items",
            json={
                "kind": "payment",
                "title": "Rent",
                "due_date": "2026-11-01",
                "amount": 650.0,
                "recurrence": MONTHLY,
            },
        )
        rent = created.json()
        await _patch(api, rent["id"], due_date="2026-11-03")

        await _tick(api, "2026-11-03")
        assert (await api.client.get(f"/api/items/{rent['id']}")).json()["due_date"] == "2026-11-03"
        await _tick(api, "2026-11-04")
        after = (await api.client.get(f"/api/items/{rent['id']}")).json()
        assert after["due_date"] == "2026-12-01"
        assert (
            after["computation"]["summary"]
            == "Repeats every month since Sun 1 Nov 2026; next on Tue 1 Dec 2026."
        )


async def test_a_recurring_to_do_added_with_a_past_first_date_shows_its_next_occurrence(
    data_dir: Path,
) -> None:
    clock.set_today("2026-09-25")
    async with api_for(data_dir) as api:
        created = await api.client.post(
            "/api/items",
            json={
                "kind": "payment",
                "title": "Gym",
                "due_date": "2026-01-31",
                "amount": 30.0,
                "recurrence": MONTHLY,
            },
        )
        assert created.status_code == 201, created.text
        assert (created.json()["status"], created.json()["due_date"]) == ("open", "2026-09-30")


async def test_a_rent_its_letter_leaves_undated_keeps_the_date_the_person_gave_it(data_dir: Path) -> None:
    """The lease says the rent is due "jeweils zum Monatsende" (no date the engine can compute). The
    person dates October's rent 31 Oct: that is where the schedule starts, so November's is on the
    30th and December's on the 31st. Reading the lease again, with the sentence quoted differently,
    keeps that rent (no second, undated one)."""
    clock.set_today("2026-10-20")
    router = ApiRouter()
    payment = next(item for item in router.payloads[TAX_LETTER.marker]["items"] if item["kind"] == "payment")
    payment |= {
        "recurrence": MONTHLY,
        "date": {"type": "none", "nature": "payment", "text": "jeweils zum Monatsende"},
    }
    async with api_for(data_dir, router=router) as api:
        doc_id = (await api.upload(("mietvertrag.pdf", TAX_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [rent] = await _items(api, doc_id=doc_id, kind="payment")
        assert rent["due_date"] is None
        dated = await _patch(api, rent["id"], due_date="2026-10-31")
        assert (dated["date_spec"]["type"], dated["date_spec"]["date"]) == ("fixed", "2026-10-31")
        assert dated["date_spec"]["text"] == "jeweils zum Monatsende"  # the letter's words are kept

        await _tick(api, "2026-11-01")
        payment["quote"] = "Die Miete ist jeweils zum Monatsende fällig."
        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        [after] = await _items(api, doc_id=doc_id, kind="payment")
        assert (after["id"], after["due_date"]) == (rent["id"], "2026-11-30")
        await _tick(api, "2026-12-01")
        [december] = await _items(api, doc_id=doc_id, kind="payment")
        assert december["due_date"] == "2026-12-31"
