"""A move over HTTP: the profile keeps the day the person said they moved in and the address before."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from ordnung import clock
from test_api_support import TODAY, api_for

OLD_ADDRESS = "Alte Straße 1\n12345 Musterstadt"


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
