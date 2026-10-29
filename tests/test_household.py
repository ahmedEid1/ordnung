"""Your household (``ordnung.secretary.household``, ADR 0023): who a letter is suggested for, the checks on
the list of people, renames and removals, dormant links, the trash, deleting for good, the daily check and a
row written by a newer Ordnung. Store level; the routes are in ``test_api_household.py``."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from ordnung import clock
from ordnung.config import Paths
from ordnung.db.store import HOUSEHOLD_META_KEY, PERSON_META_KEY, Store
from ordnung.ids import prefix_of
from ordnung.models import PROOF_SOURCE, Direction, DocumentExtraction, Profile
from ordnung.secretary import household
from ordnung.secretary.household import (
    MINE,
    HouseholdError,
    HouseholdMember,
    LetterFor,
    StoredHousehold,
    member_for,
)
from ordnung.tick import LAST_TICK_KEY, DailyTick

SAM = "Sam Rivera"
ALEX = "Alex Rivera"
MIA = "Mia Rivera"
ROOT = Path(__file__).resolve().parents[1]
_REACHES_HOUSEHOLD = re.compile(
    r"secretary\.household|secretary import household|HOUSEHOLD_META_KEY|[\"']household[\"']|\.household\b"
)


@dataclass(frozen=True)
class Person:
    """A person as a PUT sends them (``MemberIn``)."""

    name: str
    id: str | None = None
    signs: bool = True


@pytest.fixture
def sam(store: Store) -> Store:
    """The store of a person called Sam Rivera."""
    store.save_profile(Profile(name=SAM, onboarded=True).model_dump())
    return store


def _letter(
    store: Store,
    name: str,
    recipient: str | None = None,
    *,
    read: bool = True,
    direction: Direction = "incoming",
    source: str = "upload",
) -> str:
    """A letter (no file on disk); with ``read`` a reading that names ``recipient``."""
    document = store.add_document(
        sha256=name.encode().hex().ljust(64, "0")[:64],
        filename=f"{name}.pdf",
        mime="application/pdf",
        file_path=f"files/{name}.pdf",
        direction=direction,
        source=source,
        status="processed",
    )
    if read:
        extraction = DocumentExtraction(
            kind="invoice", title=name, summary="s", explanation="e", recipient_name=recipient
        )
        store.update_document(document.id, extraction=extraction)
    return document.id


def _members(*names: str) -> list[HouseholdMember]:
    return [HouseholdMember(id=f"hhm_{n:012d}", name=name) for n, name in enumerate(names)]


def _save(store: Store, *people: Person, also_file: list[str] | None = None) -> household.HouseholdView:
    """PUT the list of people, from the version stored now."""
    base = household.version(household.load(store).members)
    return household.change(store, base=base, members=list(people), also_file=also_file or [])


def _add(store: Store, *names: str) -> list[str]:
    """Add people to the household; their ids, in order."""
    kept = [Person(m.name, m.id, m.signs) for m in household.load(store).members]
    view = _save(store, *kept, *(Person(name) for name in names))
    return [m["id"] for m in view["members"]][len(kept) :]


def _keep(store: Store) -> list[Person]:
    return [Person(m.name, m.id, m.signs) for m in household.load(store).members]


def _refused(error: pytest.ExceptionInfo[HouseholdError]) -> tuple[int, str]:
    return error.value.status, error.value.detail


def _row(store: Store) -> dict[str, Any] | None:
    raw = store.get_meta(HOUSEHOLD_META_KEY)
    return None if raw is None else json.loads(raw)


def _for(store: Store, doc_id: str) -> LetterFor:
    document = store.get_document(doc_id)
    assert document is not None
    return household.letter_for(store, document)


# --------------------------------------------------------------------------------------------------
# who a letter is suggested for (points 1–4)
# --------------------------------------------------------------------------------------------------


def test_a_member_is_suggested_only_when_the_addressee_names_them_alone(sam: Store) -> None:
    alex, mia = _add(sam, ALEX, MIA)
    for_alex = _letter(sam, "alex", "Frau Alex Rivera")
    for_mia = _letter(sam, "mia", "Mia Rivera c/o Sam Rivera")
    for_sam = _letter(sam, "sam", "Herrn Sam Rivera")
    for_kim = _letter(sam, "kim", "Kim Rivera")
    view = household.view(sam)
    assert view["suggested"] == {for_alex: alex, for_mia: mia}
    assert view["filed"] == {} and view["mine"] == []
    assert _for(sam, for_alex).suggested == HouseholdMember(id=alex, name=ALEX)
    assert _for(sam, for_sam) == LetterFor()
    assert _for(sam, for_kim) == LetterFor(add="Kim Rivera")
    # a suggestion is only a question: nothing is filed by reading or working it out
    assert _row(sam) == {
        "format": 1,
        "members": [m.model_dump() for m in household.load(sam).members],
        "links": {},
    }


def test_two_members_the_addressee_could_name_get_no_suggestion() -> None:
    members = _members("Alex Rivera", "Alexandra Rivera", "A. Rivera")
    assert member_for("Alex Rivera", members) is None  # Alex Rivera and A. Rivera both could be
    assert member_for("Alexandra Rivera", members) is None
    assert member_for("Alex Rivera", _members("Alex Rivera", "Alexandra Rivera")) == members[0]


@pytest.mark.parametrize(
    "addressee",
    ["ALEX RIVERA", "alex rivera", "Rivera, Alex", "Dr. Alex Rivera", "A. Rivera", "Herrn Prof. Alex Rivera"],
)
def test_umlauts_case_accents_titles_and_initials_do_not_count(addressee: str) -> None:
    assert member_for(addressee, _members(ALEX, "Jürgen Müller")) == _members(ALEX)[0]
    juergen = _members(ALEX, "Jürgen Müller")[1]
    for spelled in ("Juergen Mueller", "Jurgen Muller", "J. Müller", "Müller, Jürgen", "JÜRGEN MÜLLER"):
        assert member_for(spelled, _members(ALEX, "Jürgen Müller")) == juergen, spelled
    assert member_for("José Núñez", _members("Jose Nunez")) is not None


@pytest.mark.parametrize(
    "addressee",
    ["Alex und Mia Rivera", "Alex & Mia Rivera", "Familie Rivera", "Eheleute Rivera", "Alex u. Mia Rivera"],
)
def test_an_addressee_naming_several_people_names_no_member(addressee: str) -> None:
    assert member_for(addressee, _members(ALEX)) is None
    stored = StoredHousehold(members=_members(ALEX))
    assert household.answer("doc_x", addressee, SAM, stored) == LetterFor()  # and offers no one to add


def test_nothing_is_suggested_for_the_person_or_without_a_profile_name(sam: Store) -> None:
    _add(sam, ALEX)
    stored = household.load(sam)
    assert household.answer("doc_x", "Sam Rivera", SAM, stored) == LetterFor()
    assert household.answer("doc_x", "Herrn Rivera", SAM, stored) == LetterFor()  # could be the person
    assert household.answer("doc_x", ALEX, "", stored) == LetterFor()
    assert household.answer("doc_x", None, SAM, stored) == LetterFor()
    assert household.answer("doc_x", "  ", SAM, stored) == LetterFor()
    sent = _letter(sam, "sent", ALEX, direction="outgoing")
    unread = _letter(sam, "unread", read=False)
    assert _for(sam, sent) == LetterFor() and _for(sam, unread) == LetterFor()
    assert household.view(sam)["suggested"] == {}
    sam.save_profile(Profile(name="", onboarded=True).model_dump())
    letter = _letter(sam, "alex", ALEX)
    assert _for(sam, letter) == LetterFor()
    assert household.view(sam)["suggested"] == {}


def test_an_answered_letter_is_never_suggested_again(sam: Store) -> None:
    (alex,) = _add(sam, ALEX)
    filed, mine, open_ = (_letter(sam, name, ALEX) for name in ("filed", "mine", "open"))
    household.file(sam, {filed: alex, mine: MINE})
    view = household.view(sam)
    assert view["filed"] == {filed: alex} and view["mine"] == [mine]
    assert view["suggested"] == {open_: alex}
    assert _for(sam, filed) == LetterFor(filed_for=HouseholdMember(id=alex, name=ALEX))
    assert _for(sam, mine) == LetterFor(mine=True)
    assert [p["letters"] for p in view["members"]] == [1]


def test_add_is_offered_only_for_one_unknown_person_with_room_left(sam: Store) -> None:
    letter = _letter(sam, "kim", "Frau Dr. Kim Rivera")
    assert _for(sam, letter) == LetterFor(add="Dr. Kim Rivera")  # as shown: courtesy words left out
    family = _letter(sam, "family", "Familie Rivera")
    assert _for(sam, family) == LetterFor()
    _add(sam, ALEX)
    assert _for(sam, letter).add == "Dr. Kim Rivera"
    household.file(sam, {letter: MINE})
    assert _for(sam, letter) == LetterFor(mine=True)  # answered: nothing to add
    household.file(sam, {letter: None})
    _add(sam, "Kim")  # could be her: suggested, never offered to add
    assert _for(sam, letter) == LetterFor(suggested=household.load(sam).members[1])
    stored = StoredHousehold(members=_members(*(f"Person {chr(65 + n)}" for n in range(12))))
    assert household.answer("doc_x", "Kim Rivera", SAM, stored) == LetterFor()  # the household is full
    stored = StoredHousehold(members=_members(*(f"Person {chr(65 + n)}" for n in range(11))))
    assert household.answer("doc_x", "Kim Rivera", SAM, stored) == LetterFor(add="Kim Rivera")


# --------------------------------------------------------------------------------------------------
# the list of people (point 5)
# --------------------------------------------------------------------------------------------------


def test_a_name_is_kept_as_typed_on_one_line(sam: Store) -> None:
    view = _save(sam, Person("  alex\n RIVERA​ \t"), Person("Dr. Mia Rivera-López", signs=False))
    assert [(m["name"], m["signs"], m["letters"]) for m in view["members"]] == [
        ("alex RIVERA", True, 0),
        ("Dr. Mia Rivera-López", False, 0),
    ]


@pytest.mark.parametrize(
    ("name", "refusal"),
    [
        ("", "Type a name."),
        (" \n\t​", "Type a name."),
        ("A" * 121, "Use at most 120 characters."),
        ("12345", "Type a name with letters in it."),
        ("-- !", "Type a name with letters in it."),
    ],
)
def test_empty_long_and_letterless_names_are_refused(sam: Store, name: str, refusal: str) -> None:
    with pytest.raises(HouseholdError) as refused:
        _save(sam, Person(name))
    assert _refused(refused) == (422, refusal)
    assert _row(sam) is None
    assert _save(sam, Person("A" * 120))["members"][0]["name"] == "A" * 120


@pytest.mark.parametrize("name", ["Sam Rivera", "sam rivera", "Herrn Sam Rivera", "S. Rivera", "Rivera, Sam"])
def test_your_own_name_is_refused(sam: Store, name: str) -> None:
    with pytest.raises(HouseholdError) as refused:
        _save(sam, Person(name))
    assert _refused(refused) == (
        422,
        "That's your own name. Your household is the other people your letters come for.",
    )


@pytest.mark.parametrize("name", ["Alex und Mia Rivera", "Alex & Mia", "Familie Rivera", "Alex + Mia"])
def test_several_people_in_one_name_are_refused(sam: Store, name: str) -> None:
    with pytest.raises(HouseholdError) as refused:
        _save(sam, Person(name))
    assert _refused(refused) == (422, "Add one person at a time.")


@pytest.mark.parametrize(
    "spelled", ["Juergen Mueller", "jurgen muller", "Müller Jürgen", "J. Müller", "Herrn Jürgen Müller"]
)
def test_the_same_name_spelled_otherwise_is_refused(sam: Store, spelled: str) -> None:
    _add(sam, "Jürgen Müller")
    with pytest.raises(HouseholdError) as refused:
        _save(sam, *_keep(sam), Person(spelled))
    assert _refused(refused) == (422, "Jürgen Müller is already in your household.")
    # a rename to the same name, spelled otherwise, of the person themselves is no duplicate
    (juergen,) = _keep(sam)
    assert _save(sam, Person(spelled, juergen.id))["members"][0]["name"] == " ".join(spelled.split())


def test_similar_names_are_kept_but_not_suggested(sam: Store) -> None:
    kim, kim_rivera = _add(sam, "Kim", "Kim Rivera")
    for_kim_rivera = _letter(sam, "kim-rivera", "Kim Rivera")
    for_k = _letter(sam, "kim", "Frau Kim")
    view = household.view(sam)
    assert [m["name"] for m in view["members"]] == ["Kim", "Kim Rivera"]
    assert for_kim_rivera not in view["suggested"]  # either could be meant: no suggestion
    assert view["suggested"].get(for_k) is None  # "Kim" is within both names too
    assert _for(sam, for_kim_rivera) == LetterFor()
    assert kim != kim_rivera


def test_at_most_twelve_people(sam: Store) -> None:
    names = [f"Person {chr(65 + n)}" for n in range(12)]
    assert len(_save(sam, *(Person(name) for name in names))["members"]) == 12
    with pytest.raises(HouseholdError) as refused:
        _save(sam, *_keep(sam), Person("One More"))
    assert _refused(refused) == (422, "Your household can have at most 12 people.")


def test_ids_must_be_household_ids_and_each_one_once(sam: Store) -> None:
    (alex,) = _add(sam, ALEX)
    for bad in ("me", "doc_k3j9x0a1b2c4", "hhm_SHOUTING0000", "hhm_short"):
        with pytest.raises(HouseholdError) as refused:
            _save(sam, Person(ALEX, alex), Person(MIA, bad))
        assert refused.value.status == 422, bad
    with pytest.raises(HouseholdError) as refused:
        _save(sam, Person(ALEX, alex), Person(MIA, alex))
    assert refused.value.status == 422


def test_new_people_get_hhm_ids(sam: Store) -> None:
    ids = _add(sam, ALEX, MIA)
    assert [prefix_of(i) for i in ids] == ["hhm", "hhm"] and len(set(ids)) == 2
    assert all(re.fullmatch(r"hhm_[0-9a-z]{12}", i) for i in ids)


def test_an_unchanged_list_writes_nothing(sam: Store) -> None:
    _add(sam, ALEX)
    conn = sam._conn()
    before = conn.total_changes
    _save(sam, *_keep(sam))
    assert conn.total_changes == before


def test_a_stale_base_is_refused(sam: Store) -> None:
    stale = household.version([])
    _add(sam, ALEX)
    with pytest.raises(HouseholdError) as refused:
        household.change(sam, base=stale, members=[Person(MIA)], also_file=[])
    assert _refused(refused) == (
        409,
        "Your household changed in another window. Look again, then try once more.",
    )


# --------------------------------------------------------------------------------------------------
# renames, removals and dormant links (points 6 and 7)
# --------------------------------------------------------------------------------------------------


def test_a_rename_keeps_the_filed_letters(sam: Store) -> None:
    (alex,) = _add(sam, ALEX)
    filed = _letter(sam, "filed", ALEX)
    household.file(sam, {filed: alex})
    for_alexa = _letter(sam, "alexa", "Alexa Rivera-Smith")
    view = _save(sam, Person("Alexa Rivera-Smith", alex, signs=False))
    assert view["members"] == [{"id": alex, "name": "Alexa Rivera-Smith", "signs": False, "letters": 1}]
    assert view["filed"] == {filed: alex}
    assert view["suggested"] == {for_alexa: alex}  # suggestions follow the new name


def test_a_removal_leaves_links_dormant_and_undo_revives_them(sam: Store) -> None:
    alex, mia = _add(sam, ALEX, MIA)
    filed = _letter(sam, "filed", ALEX)
    other = _letter(sam, "other", MIA)
    household.file(sam, {filed: alex, other: mia})
    view = _save(sam, Person(MIA, mia))
    assert view["filed"] == {other: mia}  # the removed person's letter counts as the person's again
    assert view["suggested"] == {}  # and no member is named on it
    assert _for(sam, filed) == LetterFor(add="Alex Rivera")
    assert _row(sam)["links"] == {filed: alex, other: mia}  # dormant, not forgotten
    # filing another letter meanwhile leaves the dormant link alone
    third = _letter(sam, "third", "Somebody Else")
    household.file(sam, {third: MINE})
    view = _save(sam, Person(MIA, mia), Person(ALEX, alex))  # Undo: the same person, the same id
    assert view["filed"] == {filed: alex, other: mia}
    assert [m["id"] for m in view["members"]] == [mia, alex]


def test_dormant_links_go_with_any_other_next_change(sam: Store) -> None:
    alex, mia = _add(sam, ALEX, MIA)
    filed = _letter(sam, "filed", ALEX)
    household.file(sam, {filed: alex})
    _save(sam, Person(MIA, mia))
    _save(sam, Person(MIA, mia, signs=False))  # any other change to the list
    assert _row(sam)["links"] == {}
    view = _save(sam, Person(MIA, mia, signs=False), Person(ALEX, alex))  # too late: back, but nothing filed
    assert view["filed"] == {} and view["suggested"] == {filed: alex}


def test_removing_everyone_leaves_no_row_once_nothing_is_filed(sam: Store) -> None:
    (alex,) = _add(sam, ALEX)
    assert _row(sam) is not None
    _save(sam)
    assert _row(sam) is None
    assert household.view(sam) == {
        "members": [],
        "filed": {},
        "mine": [],
        "suggested": {},
        "version": household.version([]),
    }
    assert alex


# --------------------------------------------------------------------------------------------------
# filing (point 1) and the letters (point 8)
# --------------------------------------------------------------------------------------------------


def test_filing_sets_says_mine_and_forgets_in_one_change(sam: Store) -> None:
    alex, mia = _add(sam, ALEX, MIA)
    first, second, third = (_letter(sam, name, ALEX) for name in ("first", "second", "third"))
    household.file(sam, {first: alex, second: MINE, third: mia})
    view = household.file(sam, {first: mia, second: None, third: MINE})
    assert view["filed"] == {first: mia} and view["mine"] == [third]
    assert view["suggested"] == {second: alex}
    conn = sam._conn()
    before = conn.total_changes
    household.file(sam, {first: mia})  # the same answer again writes nothing
    assert conn.total_changes == before


@pytest.mark.parametrize("trashed", [False, True])
def test_filing_refuses_letters_gone_unknown_people_and_proof_files(sam: Store, trashed: bool) -> None:
    (alex,) = _add(sam, ALEX)
    letter = _letter(sam, "letter", ALEX)
    proof = _letter(sam, "proof", ALEX, source=PROOF_SOURCE)
    gone = _letter(sam, "gone", ALEX)
    if trashed:
        sam.trash_document(gone)
    else:
        sam.delete_document(gone)
    cases = [
        ({letter: alex, gone: alex}, 404),
        ({letter: "hhm_000000000000"}, 422),
        ({letter: "Alex Rivera"}, 422),
        ({proof: MINE}, 422),
    ]
    for letters, status in cases:
        with pytest.raises(HouseholdError) as refused:
            household.file(sam, letters)
        assert refused.value.status == status, letters
    assert _row(sam)["links"] == {}  # nothing of a refused change is kept


def test_a_letter_in_the_trash_keeps_its_link_and_brings_it_back(sam: Store) -> None:
    (alex,) = _add(sam, ALEX)
    filed = _letter(sam, "filed", ALEX)
    household.file(sam, {filed: alex})
    sam.trash_document(filed)
    view = household.view(sam)
    assert view["filed"] == {} and view["members"][0]["letters"] == 0
    assert _for(sam, filed) == LetterFor()
    _save(sam, Person(ALEX, alex, signs=False))  # a change meanwhile keeps the trashed letter's link
    assert _row(sam)["links"] == {filed: alex}
    sam.restore_document(filed)
    assert household.view(sam)["filed"] == {filed: alex}


def test_a_letter_deleted_for_good_leaves_no_trace_in_the_household(sam: Store, paths: Paths) -> None:
    (alex,) = _add(sam, ALEX)
    gone = _letter(sam, "gone", ALEX)
    kept = _letter(sam, "kept", ALEX)
    household.file(sam, {gone: alex, kept: MINE})
    assert sam.delete_document(gone)
    assert gone not in (sam.get_meta(HOUSEHOLD_META_KEY) or "")
    assert household.view(sam)["mine"] == [kept]
    assert sam._conn().execute("PRAGMA secure_delete").fetchone()[0] == 1
    sam.close()
    files = [paths.db, paths.db.with_name("ordnung.db-wal")]
    assert gone.encode() not in b"".join(path.read_bytes() for path in files if path.exists())


def test_the_daily_check_forgets_letters_that_are_gone(sam: Store) -> None:
    (alex,) = _add(sam, ALEX)
    kept = _letter(sam, "kept", ALEX)
    trashed = _letter(sam, "trashed", ALEX)
    household.file(sam, {kept: alex, trashed: MINE})
    sam.trash_document(trashed)
    # left by a computer still on 0.2.0, which deletes a letter without touching the row
    row = _row(sam)
    assert row is not None
    row["links"]["doc_gone00000000"] = alex
    sam.set_meta(HOUSEHOLD_META_KEY, json.dumps(row))
    conn = sam._conn()
    before = conn.total_changes
    assert household.prune_gone(sam) == 1
    assert _row(sam)["links"] == {kept: alex, trashed: MINE}  # the trash keeps its own
    after = conn.total_changes
    assert household.prune_gone(sam) == 0
    assert conn.total_changes == after > before  # nothing to forget: nothing written


@dataclass
class _TickCtx:
    store: Store
    llm: None = None
    bus: None = None


async def test_the_daily_tick_runs_the_check_on_a_new_day(sam: Store) -> None:
    """The check runs with the day's work (``tick.py``) as background work: it is never a person change."""
    (alex,) = _add(sam, ALEX)
    row = _row(sam)
    assert row is not None
    row["links"]["doc_gone00000000"] = alex
    sam.set_meta(HOUSEHOLD_META_KEY, json.dumps(row))
    sam.set_meta(LAST_TICK_KEY, "2026-09-30")
    clock.set_today("2026-10-01")
    try:
        result = await DailyTick(_TickCtx(sam)).check()
    finally:
        clock.set_today(None)
    assert result.day_changed
    assert _row(sam)["links"] == {}
    assert sam.get_meta(PERSON_META_KEY) is None


def test_a_household_from_a_newer_ordnung_is_never_overwritten(sam: Store) -> None:
    letter = _letter(sam, "letter", ALEX)
    newer = {
        "format": 2,
        "members": [{"id": "hhm_000000000001", "name": ALEX, "signs": True, "birthday": "2015-03-01"}],
        "links": {letter: "hhm_000000000001"},
        "groups": ["children"],
    }
    raw = json.dumps(newer)
    sam.set_meta(HOUSEHOLD_META_KEY, raw)
    view = household.view(sam)  # read what parses
    assert [(m["name"], m["letters"]) for m in view["members"]] == [(ALEX, 1)]
    assert view["filed"] == {letter: "hhm_000000000001"}
    refusal = (
        409,
        "Your household was saved by a newer version of Ordnung. Update Ordnung on this computer.",
    )
    with pytest.raises(HouseholdError) as refused:
        _save(sam, Person(MIA))
    assert _refused(refused) == refusal
    with pytest.raises(HouseholdError) as refused:
        household.file(sam, {letter: MINE})
    assert _refused(refused) == refusal
    newer["links"]["doc_gone00000000"] = "hhm_000000000001"
    raw = json.dumps(newer)
    sam.set_meta(HOUSEHOLD_META_KEY, raw)
    assert household.prune_gone(sam) == 0
    assert sam.get_meta(HOUSEHOLD_META_KEY) == raw


@pytest.mark.parametrize(
    "raw", ["not json", "[]", '{"format": 1, "members": "Alex"}', '{"members": [{"id": 3}]}']
)
def test_an_unreadable_row_reads_as_an_empty_household(sam: Store, raw: str) -> None:
    sam.set_meta(HOUSEHOLD_META_KEY, raw)
    assert household.load(sam) == StoredHousehold()
    assert household.view(sam)["members"] == []


def test_also_file_files_the_letter_for_the_one_new_person(sam: Store) -> None:
    letter = _letter(sam, "letter", ALEX)
    view = _save(sam, Person(ALEX), also_file=[letter])
    (alex,) = [m["id"] for m in view["members"]]
    assert view["filed"] == {letter: alex}
    with pytest.raises(HouseholdError) as refused:
        _save(sam, Person(ALEX, alex), also_file=[letter])  # no one new to file it for
    assert refused.value.status == 422
    with pytest.raises(HouseholdError) as refused:
        _save(sam, Person(ALEX, alex), Person(MIA), also_file=["doc_nothere00000"])
    assert refused.value.status == 404
    assert [m.name for m in household.load(sam).members] == [ALEX]  # nothing of a refused change is kept


# --------------------------------------------------------------------------------------------------
# what reaches Claude (point 9)
# --------------------------------------------------------------------------------------------------


def test_prompts_drafts_review_and_brief_never_read_the_household() -> None:
    """No prompt, draft request, weekly review or daily note reads the household itself (a person's name
    reaches the last two only inside the title of an Idea about their letters)."""
    places = [
        *sorted((ROOT / "src" / "ordnung" / "llm").rglob("*")),
        ROOT / "src" / "ordnung" / "drafts" / "compose.py",
        ROOT / "src" / "ordnung" / "secretary" / "review.py",
        ROOT / "src" / "ordnung" / "secretary" / "brief.py",
    ]
    for path in places:
        if path.is_file():
            # code that reaches the household: its module, its meta key or a letter page's field (the English
            # word itself may stand in a letter Claude helps with: "a hardship for you or your household")
            text = path.read_text(encoding="utf-8", errors="replace")
            assert not _REACHES_HOUSEHOLD.search(text), (path, _REACHES_HOUSEHOLD.search(text))


#: What Ask's code may use of the household module: what Ask may see (point 9), and its shape.
ASK_MAY_USE = {"ask_view", "AskView"}


def test_ask_reads_the_household_only_through_ask_view() -> None:
    """Ask (its tools and its ledger fingerprint) reads the household only as ``household.ask_view`` gives it
    and as ``Ledger.household_filed`` files the letters: never the stored row, its meta key, ``signs``, "mine"
    or a suggestion (point 9)."""
    import ast

    used: set[str] = set()
    for path in sorted((ROOT / "src" / "ordnung" / "assistant").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "ordnung.secretary.household":
                names = {alias.name for alias in node.names}
                assert names <= ASK_MAY_USE, (path, names - ASK_MAY_USE)
                used |= names
            elif isinstance(node, ast.ImportFrom) and node.module == "ordnung.secretary":
                aliases |= {alias.asname or alias.name for alias in node.names if alias.name == "household"}
            elif isinstance(node, ast.Import):
                assert not any(alias.name == "ordnung.secretary.household" for alias in node.names), path
            elif isinstance(node, ast.Name):
                assert node.id != "HOUSEHOLD_META_KEY", (path, node.lineno)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get_meta"
            ):
                keys = [arg.value for arg in node.args if isinstance(arg, ast.Constant)]
                assert "household" not in keys, (path, node.lineno)
            elif isinstance(node, ast.Attribute) and node.attr in ("signs", "links", "suggested", "mine"):
                raise AssertionError(f"{path.name}:{node.lineno} reads .{node.attr}")
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in aliases
            ):
                assert node.attr in ASK_MAY_USE, (path, node.lineno, node.attr)
                used.add(node.attr)
    assert "ask_view" in used  # the fingerprint and get_profile read what Ask may see, and nothing else
    mcp = (ROOT / "src" / "ordnung" / "assistant" / "mcp_server.py").read_text(encoding="utf-8")
    assert ".household_filed" in mcp  # get_document's filed_for
