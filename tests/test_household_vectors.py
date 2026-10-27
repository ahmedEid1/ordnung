"""The household's shared vectors (``web/src/mocks/householdVectors.json``): who a letter is for and which names
the list of people takes, as the API's policy (``ordnung.secretary.household``) answers them. The static demo's
mock (``web/src/mocks/household.ts``) is held to the same file by ``household.test.ts``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ordnung.secretary import household
from ordnung.secretary.household import MINE, HouseholdError, HouseholdMember, StoredHousehold

VECTORS_FILE = Path(__file__).resolve().parents[1] / "web" / "src" / "mocks" / "householdVectors.json"
VECTORS: list[dict[str, Any]] = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))
DOC = "doc_vector00000"
REMOVED = "hhm_removed00000"


def _members(names: list[str]) -> list[HouseholdMember]:
    return [HouseholdMember(id=f"hhm_{n:012d}", name=name) for n, name in enumerate(names)]


def _name(member: HouseholdMember | None) -> str | None:
    return None if member is None else member.name


def _letter(vector: dict[str, Any]) -> dict[str, Any]:
    members = _members(vector["members"])
    link = vector["link"]
    links = {}
    if link == MINE:
        links[DOC] = MINE
    elif link == "removed":
        links[DOC] = REMOVED
    elif link is not None:
        links[DOC] = next(member.id for member in members if member.name == link)
    found = household.answer(
        DOC, vector["addressee"], vector["profile"], StoredHousehold(members=members, links=links)
    )
    return {
        "filed_for": _name(found.filed_for),
        "mine": found.mine,
        "suggested": _name(found.suggested),
        "add": found.add,
    }


def _added(vector: dict[str, Any]) -> dict[str, str]:
    """Add the vector's ``name`` to a household of its ``members`` (each kept as it is)."""

    class Person:
        def __init__(self, name: str, id: str | None = None) -> None:
            self.id, self.name, self.signs = id, name, True

    stored = StoredHousehold(members=_members(vector["members"]))
    people = [Person(member.name, member.id) for member in stored.members]
    try:
        checked = household.check_members([*people, Person(vector["name"])], stored, vector["profile"])
    except HouseholdError as refused:
        assert refused.status == 422
        return {"refused": refused.detail}
    return {"kept": checked[-1].name}


def test_the_vectors_cover_both_kinds() -> None:
    kinds = [vector["kind"] for vector in VECTORS]
    assert kinds.count("letter") >= 30 and kinds.count("name") >= 20
    assert len({vector["case"] for vector in VECTORS}) == len(VECTORS)


@pytest.mark.parametrize("vector", VECTORS, ids=[vector["case"] for vector in VECTORS])
def test_the_api_meets_every_vector(vector: dict[str, Any]) -> None:
    answer = _letter(vector) if vector["kind"] == "letter" else _added(vector)
    assert answer == vector["expect"]
