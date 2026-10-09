"""Dates you add yourself that repeat (audit item 26): set when added, changed later, and where the next one
stands (ordnung.recurrence points 2, 4, 7, 8 and 10 for a to-do added by hand)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from helpers_secretary import add_item
from ordnung import clock
from ordnung.models import DateSpec, Recurrence
from test_api_support import TODAY, Api, api_for

MONTHLY = {"interval": 1, "unit": "months"}
QUARTERLY = {"interval": 3, "unit": "months"}
THIRD_WORKING_DAY = {"interval": 1, "unit": "months", "working_day": 3}


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)  # Fri 25 Sep 2026
    yield
    clock.set_today(None)


async def _add(api: Api, due: str, recurrence: dict[str, Any] | None, **fields: Any) -> dict[str, Any]:
    body = {"kind": "reminder", "title": "UStVA", "due_date": due, "recurrence": recurrence, **fields}
    response = await api.client.post("/api/items", json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _patch(api: Api, item: dict[str, Any], **patch: Any) -> dict[str, Any]:
    response = await api.client.patch(f"/api/items/{item['id']}", json=patch)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_a_working_day_dates_the_month_its_date_names(data_dir: Path) -> None:
    """Point 8 for a date added by hand: the 3rd working day (Mon–Sat, 3 Oct a holiday) of October, whichever
    October day was chosen — not the chosen day until it passes; September's has passed, so October's."""
    async with api_for(data_dir) as api:
        for chosen in ("2026-10-01", "2026-10-14", "2026-09-01"):
            item = await _add(api, chosen, THIRD_WORKING_DAY)
            assert item["due_date"] == "2026-10-05", chosen
            assert item["computation"]["summary"].startswith("Repeats every month on the 3rd working day")
        last = await _add(api, "2026-10-01", {**MONTHLY, "working_day": -1})
        assert last["due_date"] == "2026-10-30"


async def test_a_day_of_the_month_dates_the_first_such_day_on_or_after_the_date(data_dir: Path) -> None:
    """Point 10 for a date added by hand: the first 20th on or after the chosen day; a passed one moves on."""
    async with api_for(data_dir) as api:
        on_the_20th = {**MONTHLY, "day_of_month": 20}
        assert (await _add(api, "2026-10-14", on_the_20th))["due_date"] == "2026-10-20"
        assert (await _add(api, "2026-09-01", on_the_20th))["due_date"] == "2026-10-20"


async def test_a_working_day_payment_moves_on_when_paid_and_undo_brings_it_back(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        rent = await _add(
            api,
            "2026-10-01",
            THIRD_WORKING_DAY,
            kind="payment",
            direction="out",
            amount=50.0,
            description="Transfer it to the club.",
        )
        assert (rent["due_date"], rent["send_by"]) == ("2026-10-05", "2026-10-02")
        paid = await _patch(api, rent, status="done")
        assert (paid["status"], paid["due_date"], paid["send_by"]) == ("open", "2026-11-04", "2026-11-03")
        undone = await _patch(api, paid, status="open")
        assert undone["due_date"] == "2026-10-05"


async def test_starting_to_repeat_later_and_changing_the_rule(data_dir: Path) -> None:
    """Given a rule later: the schedule starts at its date (point 2); a working day dates that date's month."""
    async with api_for(data_dir) as api:
        plain = await _add(api, "2026-10-15", None)
        monthly = await _patch(api, plain, recurrence=MONTHLY)
        assert (monthly["due_date"], monthly["date_spec"]["date"]) == ("2026-10-15", "2026-10-15")
        by_working_day = await _patch(api, monthly, recurrence=THIRD_WORKING_DAY)
        assert by_working_day["due_date"] == "2026-10-05"
        quarterly = await _patch(api, by_working_day, recurrence=QUARTERLY)
        assert (quarterly["due_date"], quarterly["recurrence"]["interval"]) == ("2026-10-05", 3)
        assert (await _patch(api, quarterly, status="done"))["due_date"] == "2027-01-05"


async def test_stopping_a_repeat_keeps_its_date_and_done_is_done_for_good(data_dir: Path) -> None:
    """``{"recurrence": null}`` stops it repeating at the date it stands at; marked done, it stays done."""
    async with api_for(data_dir) as api:
        monthly = await _add(api, "2026-10-15", MONTHLY)
        stopped = await _patch(api, monthly, recurrence=None)
        assert (stopped["recurrence"], stopped["due_date"], stopped["status"]) == (None, "2026-10-15", "open")
        done = await _patch(api, stopped, status="done")
        assert (done["status"], done["due_date"]) == ("done", "2026-10-15")


async def test_a_date_sent_with_its_rule_moves_every_one_after_it(data_dir: Path) -> None:
    """Point 2 vs point 7: the date alone stands in for one occurrence (paid, the 10th again); sent with its
    rule, the schedule starts again there (paid, the 15th of the next month)."""
    async with api_for(data_dir) as api:
        once = await _add(api, "2026-10-10", MONTHLY)
        moved = await _patch(api, once, due_date="2026-10-12")
        assert (await _patch(api, moved, status="done"))["due_date"] == "2026-11-10"

        every = await _add(api, "2026-10-10", MONTHLY)
        restarted = await _patch(api, every, due_date="2026-10-15", recurrence=MONTHLY)
        assert (restarted["due_date"], restarted["date_spec"]["date"]) == ("2026-10-15", "2026-10-15")
        assert not any(step["label"] == "Moved by you from" for step in restarted["computation"]["steps"])
        assert (await _patch(api, restarted, status="done"))["due_date"] == "2026-11-15"


async def test_removing_a_repeating_date_ends_it_and_undo_brings_it_back(data_dir: Path) -> None:
    """Remove is ``status: dismissed`` (point 4: the series ends; a phone may do it, unlike DELETE); its Undo,
    ``status: open``, brings the date back where it stood."""
    async with api_for(data_dir) as api:
        item = await _add(api, "2026-10-01", THIRD_WORKING_DAY)
        removed = await _patch(api, item, status="dismissed")
        assert (removed["status"], removed["due_date"]) == ("dismissed", "2026-10-05")
        listed = (await api.client.get("/api/items", params={"status": "open"})).json()
        assert item["id"] not in {entry["id"] for entry in listed}
        back = await _patch(api, removed, status="open")
        assert (back["status"], back["due_date"]) == ("open", "2026-10-05")
        assert back["recurrence"]["working_day"] == 3


async def test_a_date_read_from_a_letter_keeps_its_schedule(data_dir: Path) -> None:
    """Only a to-do not read from a letter starts again: a letter's rule sent with a date is point 7."""
    async with api_for(data_dir) as api:
        spec = DateSpec(type="fixed", date="2026-10-01", nature="payment", shift_rule="none")
        item_id = add_item(
            api.ctx.store,
            kind="payment",
            title="Rent",
            due_date="2026-10-01",
            date_spec=spec,
            recurrence=Recurrence(**MONTHLY),
            origin="extracted",
        )
        moved = await _patch(api, {"id": item_id}, due_date="2026-10-03", recurrence=MONTHLY)
        assert any(step["label"] == "Moved by you from" for step in moved["computation"]["steps"])
