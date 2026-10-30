"""Whose a letter is (``ordnung.secretary.household`` point 10, ADR 0023): the letters filed for someone still in the
household (:func:`~ordnung.secretary.household.filed`), what Ask may see of the household
(:func:`~ordnung.secretary.household.ask_view`), the possessive the Ideas use
(:func:`~ordnung.secretary.household.possessive`, vectors in ``test_household_vectors.py``) and the two cached
parts of a :class:`~ordnung.secretary.triggers.Ledger` the household and the repeating dates share."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from helpers_secretary import TODAY, seed_ledger
from ordnung.db.store import HOUSEHOLD_META_KEY, Store
from ordnung.ingest.plan import item_context
from ordnung.secretary import household
from ordnung.secretary.household import MINE, HouseholdMember, StoredHousehold, ask_view, filed, possessive
from ordnung.secretary.triggers import Ledger

ALEX = HouseholdMember(id="hhm_alex00000000", name="Alex Rivera", signs=True)
MIA = HouseholdMember(id="hhm_mia000000000", name="Mia Rivera", signs=False)
GONE = "hhm_gone00000000"


@dataclass(frozen=True)
class Person:
    """A person as a PUT sends them (``MemberIn``)."""

    name: str
    id: str | None = None
    signs: bool = True


def _stored(**links: str) -> StoredHousehold:
    return StoredHousehold(members=[ALEX, MIA], links=links)


# --------------------------------------------------------------------------------------------------
# filed: the filing the person pressed, nothing else
# --------------------------------------------------------------------------------------------------


def test_a_letter_is_a_member_s_only_when_filed_for_someone_still_there() -> None:
    stored = _stored(
        doc_alex="hhm_alex00000000",
        doc_mia="hhm_mia000000000",
        doc_mine=MINE,
        doc_gone=GONE,
        doc_trash=ALEX.id,
    )
    live = {"doc_alex", "doc_mia", "doc_mine", "doc_gone", "doc_unfiled"}
    assert filed(stored, live) == {"doc_alex": ALEX, "doc_mia": MIA}


def test_nothing_is_filed_without_people_or_live_letters() -> None:
    assert filed(StoredHousehold(), {"doc_a"}) == {}
    assert filed(StoredHousehold(links={"doc_a": MINE}), {"doc_a"}) == {}
    assert filed(_stored(doc_a=ALEX.id), set()) == {}


# --------------------------------------------------------------------------------------------------
# ask_view: what Ask may see
# --------------------------------------------------------------------------------------------------


def _save(store: Store, stored: StoredHousehold) -> None:
    store.set_meta(
        HOUSEHOLD_META_KEY,
        json.dumps(
            {
                "format": 1,
                "members": [member.model_dump() for member in stored.members],
                "links": stored.links,
            }
        ),
    )


def test_ask_sees_nothing_without_people(store: Store) -> None:
    assert ask_view(store, {"doc_a"}) is None
    _save(store, StoredHousehold(links={"doc_a": MINE}))  # "mine" answers only, and no one in the list
    assert ask_view(store, {"doc_a"}) is None


def test_ask_sees_names_and_filings_never_signs_mine_or_suggestions(store: Store) -> None:
    _save(store, _stored(doc_b=MIA.id, doc_a=ALEX.id, doc_mine=MINE, doc_gone=GONE, doc_trash=ALEX.id))
    seen = ask_view(store, {"doc_a", "doc_b", "doc_mine", "doc_gone", "doc_new"})
    assert seen == {
        "members": [[ALEX.id, "Alex Rivera"], [MIA.id, "Mia Rivera"]],
        "filed": {"doc_a": ALEX.id, "doc_b": MIA.id},
    }
    assert list(seen["filed"]) == ["doc_a", "doc_b"]  # in one order, whatever order the links were written in


def test_ask_sees_the_people_before_anything_is_filed(store: Store) -> None:
    _save(store, StoredHousehold(members=[ALEX]))
    assert ask_view(store, set()) == {"members": [[ALEX.id, "Alex Rivera"]], "filed": {}}


def test_a_letter_in_the_trash_leaves_ask_s_view_and_comes_back_with_it(store: Store) -> None:
    ids = seed_ledger(store)
    letter = ids["doc_passport"]
    household.change(store, base=household.version([]), members=[Person("Alex Rivera")], also_file=[letter])

    def live() -> set[str]:
        return {doc.id for doc in store.list_documents()}

    (alex,) = household.load(store).members
    seen = ask_view(store, live())
    assert seen is not None and seen["filed"] == {letter: alex.id}
    store.trash_document(letter)
    seen = ask_view(store, live())
    assert seen is not None and seen["filed"] == {}
    store.restore_document(letter)
    seen = ask_view(store, live())
    assert seen is not None and seen["filed"] == {letter: alex.id}


# --------------------------------------------------------------------------------------------------
# possessive
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Alex Rivera", "Alex Rivera's"),
        ("Hans", "Hans's"),
        ("Kim 2", None),
        ("Alex (Sohn)", None),
        ("", None),
    ],
)
def test_possessive_adds_s_after_a_letter_only(name: str, expected: str | None) -> None:
    assert possessive(name) == expected


# --------------------------------------------------------------------------------------------------
# the Ledger's cached parts
# --------------------------------------------------------------------------------------------------


def test_a_ledger_knows_whose_each_live_letter_is(store: Store) -> None:
    ids = seed_ledger(store)
    passport, permit = ids["doc_passport"], ids["doc_permit"]
    household.change(store, base=household.version([]), members=[Person("Alex Rivera")], also_file=[passport])
    (alex,) = household.load(store).members
    household.file(store, {permit: MINE})
    today = TODAY
    assert Ledger(store, today).household_filed == {passport: alex}
    store.trash_document(passport)
    assert Ledger(store, today).household_filed == {}


def test_a_ledger_reads_the_household_on_first_use_only(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_ledger(store)
    reads: list[str] = []
    load = household.load

    def counted(read_from: Store) -> StoredHousehold:
        reads.append("household")
        return load(read_from)

    monkeypatch.setattr(household, "load", counted)
    ledger = Ledger(store, TODAY)
    assert reads == []
    assert ledger.household_filed == {}
    assert ledger.household_filed == {}
    assert reads == ["household"]


def test_a_ledger_works_out_its_to_dos_date_contexts_once(store: Store) -> None:
    seed_ledger(store)
    today = TODAY
    ledger = Ledger(store, today)
    contexts = ledger.item_contexts
    assert ledger.item_contexts is contexts
    assert ledger.items
    for item in ledger.items:
        assert contexts(store, item, today) == item_context(store, item, today)
