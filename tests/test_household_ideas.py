"""The Ideas say whose a letter is (``ordnung.secretary.household`` point 10, ADR 0023): a household write
refreshes them at once, and filing a letter renames its Ideas in place, keeping the person's choice."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.db.store import Store
from ordnung.secretary import household
from ordnung.secretary.household import MINE
from ordnung.secretary.triggers import run_and_reconcile
from test_api_support import Api, api_for

YOURS = "Your passport expires Wed 10 Feb 2027"
ALEXS = "Alex Rivera's passport expires Wed 10 Feb 2027"
PARKING = "Pay parking fine: pay by Tue 29 Sep"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@dataclass(frozen=True)
class _Person:
    name: str
    id: str | None = None
    signs: bool = True


async def _titles(api: Api) -> set[str]:
    rows: list[dict[str, Any]] = (await api.client.get("/api/suggestions")).json()
    return {row["title"] for row in rows}


async def _put(api: Api, members: list[dict[str, Any]], also_file: list[str] | None = None) -> dict[str, Any]:
    base = (await api.client.get("/api/household")).json()["version"]
    body: dict[str, Any] = {"base": base, "members": members}
    if also_file:
        body["also_file"] = also_file
    response = await api.client.put("/api/household", json=body)
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


async def _patch(api: Api, letters: dict[str, str | None]) -> None:
    response = await api.client.patch("/api/household", json={"letters": letters})
    assert response.status_code == 200, response.text


async def test_household_writes_refresh_the_ideas(data_dir: Path) -> None:
    """Adding someone with a letter, *No, it's mine*, filing again and removing the person: the Ideas follow each
    write at once, without waiting for the next refresh."""
    async with api_for(data_dir) as api:
        ids = seed_ledger(api.ctx.store)
        passport = ids["doc_passport"]
        run_and_reconcile(api.ctx.store, TODAY)
        assert YOURS in await _titles(api)

        added = await _put(api, [{"name": "Alex Rivera"}], also_file=[passport])
        alex = added["members"][0]
        assert ALEXS in await _titles(api) and YOURS not in await _titles(api)

        await _patch(api, {passport: MINE})
        assert YOURS in await _titles(api) and ALEXS not in await _titles(api)

        await _patch(api, {passport: alex["id"]})
        assert ALEXS in await _titles(api)

        await _put(api, [])  # Alex removed: their letters count as the person's again
        assert YOURS in await _titles(api) and ALEXS not in await _titles(api)


def test_filing_renames_an_idea_in_place_and_keeps_the_person_s_choice(store: Store) -> None:
    """The person isn't in an Idea's fingerprint: filing the letter renames the same Idea, and "Not relevant" or
    "Remind me in a week" stay; no Idea is new and none expires."""
    ids = seed_ledger(store)
    run_and_reconcile(store, TODAY)
    by_title = {idea.title: idea for idea in store.list_suggestions()}
    passport, parking = by_title[YOURS], by_title[PARKING]
    store.update_suggestion(passport.id, status="dismissed")
    store.update_suggestion(parking.id, status="snoozed", snoozed_until="2026-10-05")

    household.change(store, base=household.version([]), members=[_Person("Alex Rivera")])
    (alex,) = household.load(store).members
    # the permit too: a passport pairs only with a permit of the same person
    household.file(
        store, {ids["doc_passport"]: alex.id, ids["doc_permit"]: alex.id, ids["doc_parking"]: alex.id}
    )
    run = run_and_reconcile(store, TODAY)
    assert (run.new, run.expired) == (0, 0)
    renamed = store.get_suggestion(passport.id)
    assert renamed is not None
    assert (renamed.title, renamed.status, renamed.fingerprint) == (ALEXS, "dismissed", passport.fingerprint)
    later = store.get_suggestion(parking.id)
    assert later is not None
    assert (later.title, later.status, later.snoozed_until) == (
        f"For Alex Rivera: {PARKING}",
        "snoozed",
        "2026-10-05",
    )

    household.file(store, {ids["doc_passport"]: MINE, ids["doc_permit"]: MINE, ids["doc_parking"]: None})
    run = run_and_reconcile(store, TODAY)
    assert (run.new, run.expired) == (0, 0)
    back = store.get_suggestion(passport.id)
    assert back is not None and (back.title, back.status) == (YOURS, "dismissed")
    unfiled = store.get_suggestion(parking.id)
    assert unfiled is not None and (unfiled.title, unfiled.status) == (PARKING, "snoozed")
