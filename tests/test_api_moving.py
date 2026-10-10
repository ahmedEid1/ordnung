"""A move over HTTP: the profile keeps the day the person said they moved in and the address before, only a
move in the last six months or the next three is taken, and saving one lists who needs the new address."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from helpers_secretary import seed_ledger
from ordnung import clock
from ordnung.secretary.moving import RULE_ID
from test_api_support import TODAY, api_for

OLD_ADDRESS = "Alte Straße 1\n12345 Musterstadt"
NEW_ADDRESS = "Neue Allee 7\n54321 Beispielstadt"
#: Why a day outside the window is refused.
WINDOW = "Ordnung's moving checklist is for a move in the last six months or the next three — check the day."


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def test_no_move_is_told_until_the_person_says_so(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        profile = (await api.client.get("/api/profile")).json()
        assert (profile["moved_on"], profile["old_address"]) == (None, "")


async def test_a_move_is_saved_and_cleared(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        saved = await api.client.put(
            "/api/profile", json={"moved_on": "2026-09-21", "old_address": OLD_ADDRESS}
        )
        assert saved.status_code == 200, saved.text
        assert (saved.json()["moved_on"], saved.json()["old_address"]) == ("2026-09-21", OLD_ADDRESS)
        # other fields leave it alone
        renamed = (await api.client.put("/api/profile", json={"name": "Sam Rivera"})).json()
        assert (renamed["moved_on"], renamed["old_address"]) == ("2026-09-21", OLD_ADDRESS)
        cleared = await api.client.put("/api/profile", json={"moved_on": "", "old_address": ""})
        assert cleared.status_code == 200, cleared.text
        assert (cleared.json()["moved_on"], cleared.json()["old_address"]) == (None, "")
        assert (await api.client.get("/api/profile")).json()["moved_on"] is None


@pytest.mark.parametrize(
    "bad", [{"moved_on": "2026-13-01"}, {"moved_on": "soon"}, {"old_address": "x" * 1001}]
)
async def test_a_move_that_isnt_a_day_or_an_address_is_refused(data_dir: Path, bad: dict[str, str]) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.put("/api/profile", json=bad)
        assert response.status_code == 422, response.text
        assert (await api.client.get("/api/profile")).json()["moved_on"] is None


# --------------------------------------------------------------------------------------------------
# the window a move may be told in, and the checklist it starts
# --------------------------------------------------------------------------------------------------


def _rows(ideas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The moving checklist's rows among Ideas."""
    return [idea for idea in ideas if idea["rule_id"] == RULE_ID]


@pytest.mark.parametrize(
    ("moved_on", "allowed"),
    [("2026-03-29", True), ("2026-12-24", True), ("2026-03-28", False), ("2026-12-25", False)],
)
async def test_a_move_is_told_from_six_months_back_to_three_ahead(
    data_dir: Path, moved_on: str, allowed: bool
) -> None:
    """Today is Fri 25 Sep 2026: 29 Mar is 180 days back, 24 Dec 90 days ahead."""
    async with api_for(data_dir) as api:
        response = await api.client.put(
            "/api/profile", json={"moved_on": moved_on, "old_address": OLD_ADDRESS}
        )
        assert (response.status_code == 200) is allowed, response.text
        if not allowed:
            assert response.json()["detail"] == WINDOW
            profile = (await api.client.get("/api/profile")).json()
            assert (profile["moved_on"], profile["old_address"]) == (None, "")  # nothing of it is saved


async def test_onboarding_checks_the_day_of_a_move_too(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.post(
            "/api/onboarding", json={"profile": {"name": "Sam Rivera", "moved_on": "2025-01-01"}}
        )
        assert response.status_code == 422 and response.json()["detail"] == WINDOW
        assert (await api.client.get("/api/profile")).json()["onboarded"] is False


async def test_a_move_lists_who_to_tell_and_stopping_it_clears_the_list(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        seed_ledger(api.ctx.store)
        saved = await api.client.put(
            "/api/profile",
            json={"address": NEW_ADDRESS, "moved_on": "2026-09-21", "old_address": OLD_ADDRESS},
        )
        assert saved.status_code == 200, saved.text
        await api.ctx.worker.ideas_settled()
        listed = _rows((await api.client.get("/api/suggestions")).json())
        titles = {row["title"] for row in listed}
        assert "Register your new address by Mon 5 Oct" in titles
        assert "Tell FunkNetz Mobile your new address" in titles
        dashboard = (await api.client.get("/api/dashboard")).json()
        assert {row["id"] for row in _rows(dashboard["suggestions"])} == {row["id"] for row in listed}

        stopped = await api.client.put("/api/profile", json={"moved_on": "", "old_address": ""})
        assert stopped.status_code == 200, stopped.text
        await api.ctx.worker.ideas_settled()
        assert _rows((await api.client.get("/api/suggestions")).json()) == []
        assert _rows((await api.client.get("/api/dashboard")).json()["suggestions"]) == []
        expired = _rows((await api.client.get("/api/suggestions", params={"status": "expired"})).json())
        assert {row["id"] for row in expired} == {row["id"] for row in listed}


async def test_only_a_change_of_the_move_refreshes_the_ideas(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with api_for(data_dir) as api:
        refreshes: list[None] = []
        monkeypatch.setattr(api.ctx.worker, "refresh_ideas", lambda: refreshes.append(None))
        for body, more in (
            ({"name": "Sam Rivera"}, 0),
            ({"moved_on": "2026-09-21", "old_address": OLD_ADDRESS}, 1),
            ({"moved_on": "2026-09-21"}, 0),  # the same day again
            ({"old_address": "Somewhere else 2"}, 0),  # no row carries an address
            ({"moved_on": "2026-09-14"}, 1),
            ({"moved_on": ""}, 1),
        ):
            before = len(refreshes)
            assert (await api.client.put("/api/profile", json=body)).status_code == 200
            assert len(refreshes) - before == more, body


async def test_a_new_address_letter_marked_sent_takes_its_row_away(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        ids = seed_ledger(api.ctx.store)
        await api.client.put("/api/profile", json={"moved_on": "2026-09-21", "old_address": OLD_ADDRESS})
        await api.ctx.worker.ideas_settled()
        row = next(
            row
            for row in _rows((await api.client.get("/api/suggestions")).json())
            if row["action"]["target_id"] == ids["funknetz"]
        )
        letter = api.ctx.store.add_draft(kind="address_change", party_id=ids["funknetz"], status="final")
        sent = await api.client.post(
            f"/api/drafts/{letter.id}/sent", json={"channel": "letter", "date": TODAY}
        )
        assert sent.status_code == 200, sent.text
        await api.ctx.worker.ideas_settled()
        assert row["id"] not in {idea["id"] for idea in (await api.client.get("/api/suggestions")).json()}
        stored = api.ctx.store.get_suggestion(row["id"])
        assert stored is not None and stored.status == "expired"
