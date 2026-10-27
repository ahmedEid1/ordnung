"""``/api/household``: who the person's letters are for (D3, ADR 0023). Made by d3-contract with the
routes' contract; d3-household-core builds the policy and the writes."""

from __future__ import annotations

from pathlib import Path

from ordnung.db.store import HOUSEHOLD_META_KEY
from ordnung.secretary import household
from test_api_support import api_for

EMPTY = {"members": [], "filed": {}, "mine": [], "suggested": {}, "version": "4f53cda18c2baa0c"}


async def test_an_empty_household(data_dir: Path) -> None:
    """No row yet: nobody in the household, nothing filed, nothing suggested; the version is the one of
    an empty list of people (a PUT's base)."""
    async with api_for(data_dir) as api:
        answer = await api.client.get("/api/household")
        assert answer.status_code == 200
        assert answer.json() == EMPTY
        assert household.version([]) == EMPTY["version"]
        assert api.ctx.store.get_meta(HOUSEHOLD_META_KEY) is None


def test_the_stored_row_and_a_refusal_have_their_shapes() -> None:
    stored = household.StoredHousehold()
    assert (stored.format, stored.members, stored.links) == (1, [], {})
    member = household.HouseholdMember(id="hhm_0123456789ab", name="Alex Rivera")
    assert member.signs is True
    assert household.version([member]) != household.version([])
    refused = household.HouseholdError(422, "Type a name.")
    assert (refused.status, refused.detail, str(refused)) == (422, "Type a name.", "Type a name.")
    assert household.LetterFor() == household.LetterFor(filed_for=None, mine=False, suggested=None, add=None)


async def test_household_writes_answer_501_until_they_are_built(data_dir: Path) -> None:
    """D3's contract (d3-contract): PUT and PATCH take their bodies and answer 501 until
    d3-household-core builds them; nothing is written."""
    async with api_for(data_dir) as api:
        change = {"base": EMPTY["version"], "members": [{"name": "Alex Rivera", "signs": True}]}
        for method, body in (("PUT", change), ("PATCH", {"letters": {"doc_x": "me"}})):
            answer = await api.client.request(method, "/api/household", json=body)
            assert answer.status_code == 501, method
            assert answer.json()["detail"] == "Your household isn't built yet."
        assert api.ctx.store.get_meta(HOUSEHOLD_META_KEY) is None
        assert (await api.client.get("/api/household")).json() == EMPTY
