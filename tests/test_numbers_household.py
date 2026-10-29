"""My numbers per person (:mod:`ordnung.numbers`, ``secretary.household`` point 10, ADR 0023): a number on a letter
the person filed for someone of their household is about that person; every other letter's is the person's own.

The filing decides, never a suggestion or the addressee; a label naming someone else still keeps a number out of
every *About* group; call sheets stay one per organisation and say whose a number or case is only when all its
letters are one person's; without a household the page is what it always was."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ordnung import clock
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.models import DocumentExtraction, Identifier, NumbersPage
from ordnung.numbers import (
    ME,
    MEMBER_RESIDENCE_EXPIRED_NOTE,
    MEMBER_RESIDENCE_EXTENSION_NOTE,
    RESIDENCE_EXPIRED_NOTE,
    RESIDENCE_EXTENSION_NOTE,
    entry_letters,
)
from ordnung.secretary import household
from ordnung.secretary.household import MINE, HouseholdMember
from ordnung.views import my_numbers, numbers_input
from test_api_support import api_for

TODAY = date(2026, 9, 28)
ROOT = Path(__file__).resolve().parents[1]
DEMO_DB = ROOT / "src" / "ordnung" / "demo" / "demo_db"
STAMP = "2026-01-01T08:00:00Z"
#: What :class:`~ordnung.models.MyNumbers` holds (the page before the household parts).
MY_NUMBERS_FIELDS = ("today", "about_you", "documents", "organisations", "open_cases", "masked")
#: The demo's *My numbers* page (its MyNumbers fields, as sorted JSON) at the E2 base commit 3d99de42, before
#: the household parts: a demo without a household must keep it byte for byte.
DEMO_PAGE_SHA256 = "8dbf8cbcbdcfc1c66c38591fab788862486351f896d0a77ddbae1877b27ef9c1"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@dataclass(frozen=True)
class Person:
    """A person as ``PUT /api/household`` sends them (``MemberIn``)."""

    name: str
    id: str | None = None
    signs: bool = True


def _party(store: Store, pid: str, name: str, kind: str) -> str:
    return store.add_party(id=pid, name=name, kind=kind, created_at=STAMP, updated_at=STAMP).id


def _letter(
    store: Store, label: str, *refs: tuple[str, str], addressee: str | None = None, **fields: Any
) -> str:
    doc = store.add_document(
        sha256=hashlib.sha256(label.encode()).hexdigest(),
        filename=f"{label}.pdf",
        mime="application/pdf",
        file_path=f"files/{label}.pdf",
        direction="incoming",
    )
    fields.setdefault("status", "processed")
    fields.setdefault("title", label)
    fields["references"] = [Identifier(label=name, value=value) for name, value in refs]
    if addressee is not None:
        fields["extraction"] = DocumentExtraction(
            kind=fields.get("kind", "other"),
            title=label,
            summary="s",
            explanation="e",
            recipient_name=addressee,
        )
    store.update_document(doc.id, **fields)
    return doc.id


def _people(store: Store, *names: str) -> list[HouseholdMember]:
    """Add ``names`` to the household (in this order) and answer its people."""
    household.change(store, base=household.version([]), members=[Person(name) for name in names])
    return list(household.load(store).members)


def _page(store: Store, **kw: Any) -> NumbersPage:
    return my_numbers(store, TODAY, **kw)


def _mine(page: NumbersPage) -> dict[str, Any]:
    return page.model_dump(mode="json", include=set(MY_NUMBERS_FIELDS))


def _about(page: NumbersPage, member: HouseholdMember) -> dict[str, Any]:
    (found,) = [person for person in page.household if person.id == member.id]
    return {number.kind: number for number in found.about}


@pytest.fixture
def ledger(store: Store) -> dict[str, str]:
    """Sam's letters, and two more of the kind a partner's or child's could be."""
    store.save_profile({"name": "Sam Rivera", "onboarded": True})
    ids: dict[str, str] = {}
    ids["employer"] = _party(store, "pty_employer", "Muster Tech GmbH", "employer")
    ids["bkk"] = _party(store, "pty_bkk", "Muster BKK", "health_insurer")
    ids["gym"] = _party(store, "pty_gym", "FitWell", "gym")
    ids["ministry"] = _party(store, "pty_ministry", "Ministry of Interior", "authority")
    ids["city"] = _party(store, "pty_city", "Ordnungsamt", "authority")
    ids["payslip"] = _letter(
        store,
        "payslip",
        ("Steuer-ID", "57 216 480 354"),
        ("SV-Nummer", "65 140300 R 005"),
        kind="payslip",
        party_id=ids["employer"],
        doc_date="2026-08-31",
    )
    ids["bkk_sam"] = _letter(
        store,
        "bkk-sam",
        ("Krankenversichertennummer", "R482019379"),
        kind="health_insurance",
        party_id=ids["bkk"],
        doc_date="2026-05-04",
    )
    ids["bkk_alex"] = _letter(
        store,
        "bkk-alex",
        ("Krankenversichertennummer", "A123456780"),
        kind="health_insurance",
        party_id=ids["bkk"],
        doc_date="2026-06-10",
    )
    ids["passport"] = _letter(
        store,
        "passport",
        ("Passport No.", "C01X00T47"),
        kind="identity_document",
        party_id=ids["ministry"],
        doc_date="2026-02-01",
    )
    ids["passport_expiry"] = store.add_item(
        kind="expiry", title="Passport expires", due_date="2027-03-03", doc_id=ids["passport"]
    ).id
    ids["gym_contract"] = _letter(
        store,
        "gym-contract",
        ("Mitgliedsnummer", "FW-10457"),
        kind="contract",
        party_id=ids["gym"],
        doc_date="2025-01-02",
    )
    ids["gym_price"] = _letter(
        store,
        "gym-price",
        ("Mitgliedsnummer", "FW-10457"),
        kind="price_increase",
        party_id=ids["gym"],
        doc_date="2026-08-01",
    )
    ids["fine"] = _letter(
        store,
        "fine",
        ("Aktenzeichen", "32.4-VW-2026-0184512"),
        ("Kassenzeichen", "5126 0184 5122"),
        kind="fine",
        party_id=ids["city"],
        doc_date="2026-09-23",
    )
    ids["fine_payment"] = store.add_item(
        kind="payment", title="Pay the fine", due_date="2026-10-02", amount=30.0, doc_id=ids["fine"]
    ).id
    return ids


# --------------------------------------------------------------------------------------------------
# without a household
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def demo_store(tmp_path: Path) -> Iterator[Store]:
    data = tmp_path / "demo"
    shutil.copytree(DEMO_DB, data)
    opened = Store.open(Paths(data))
    yield opened
    opened.close()


def _digest(page: NumbersPage) -> str:
    return hashlib.sha256(json.dumps(_mine(page), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def test_without_a_household_the_page_is_as_before(
    demo_store: Store, store: Store, ledger: dict[str, str]
) -> None:
    """The demo's page is byte for byte the base commit's, and the household parts are empty. People in the list
    change nothing until a letter is filed for one of them: an unfiled, a suggested and a "mine" letter, and a
    letter filed for someone since removed, all stay the person's."""
    for shareable in (False, True):
        page = _page(demo_store, shareable_only=shareable)
        assert _digest(page) == DEMO_PAGE_SHA256
        assert (page.household, page.filed_for, page.also_for) == ([], {}, {})

    before = _page(store)
    assert (before.household, before.filed_for, before.also_for) == ([], {}, {})
    alex, mia = _people(store, "Alex Rivera", "Mia Rivera")
    household.file(store, {ledger["payslip"]: MINE, ledger["bkk_alex"]: mia.id})
    household.change(store, base=household.version([alex, mia]), members=[Person(alex.name, alex.id)])
    after = _page(store)
    assert _mine(after) == _mine(before)
    assert (after.household, after.filed_for, after.also_for) == ([], {}, {})


# --------------------------------------------------------------------------------------------------
# whose a number is
# --------------------------------------------------------------------------------------------------


def test_a_number_on_a_letter_filed_for_a_member_is_about_them(store: Store, ledger: dict[str, str]) -> None:
    alex, _mia = _people(store, "Alex Rivera", "Mia Rivera")
    household.file(store, {ledger["bkk_alex"]: alex.id})
    page = _page(store)
    mine = {n.kind: n.value for n in page.about_you}
    assert mine == {
        "tax_id": "57 216 480 354",
        "social_insurance": "65 140300 R 005",
        "health_insurance": "R482019379",
    }
    # only the people with a number on the page, in household order
    assert [(p.id, p.name) for p in page.household] == [(alex.id, "Alex Rivera")]
    about = _about(page, alex)
    assert set(about) == {"health_insurance"}
    number = about["health_insurance"]
    assert (number.value, number.letters, number.party_name) == ("A123456780", 1, "Muster BKK")
    assert number.letter is not None and number.letter.id == ledger["bkk_alex"]
    assert page.household[0].documents == []


def test_unfiled_suggested_mine_and_removed_member_letters_are_yours(
    store: Store, ledger: dict[str, str]
) -> None:
    alex, mia = _people(store, "Alex Rivera", "Mia Rivera")
    suggested = _letter(
        store,
        "bkk-addressed",
        ("Krankenversichertennummer", "B987654320"),
        addressee="Alex Rivera",
        kind="health_insurance",
        party_id=ledger["bkk"],
        doc_date="2026-07-01",
    )
    assert household.letter_for(store, store.get_document(suggested)).suggested == alex  # type: ignore[arg-type]
    household.file(store, {ledger["bkk_alex"]: MINE, ledger["passport"]: mia.id})
    household.change(store, base=household.version([alex, mia]), members=[Person(alex.name, alex.id)])
    page = _page(store)
    values = {n.value for n in page.about_you}
    assert {"B987654320", "A123456780", "R482019379"} <= values
    assert [d.kind for d in page.documents] == ["passport"]
    assert page.documents[0].number is not None and page.documents[0].number.value == "C01X00T47"
    assert (page.household, page.filed_for, page.also_for) == ([], {}, {})


def test_a_number_on_letters_of_two_people_is_listed_under_each_and_says_so(
    store: Store, ledger: dict[str, str]
) -> None:
    alex, mia = _people(store, "Alex Rivera", "Mia Rivera")
    # the same Steuer-ID on a letter filed for Alex and one for Mia (two readings that disagree, or a mix-up)
    for name, member in (("tax-alex", alex), ("tax-mia", mia)):
        letter = _letter(
            store,
            name,
            ("Steuer-ID", "57216480354"),
            kind="tax_letter",
            party_id=ledger["employer"],
            doc_date="2026-09-01",
        )
        household.file(store, {letter: member.id})
    page = _page(store)
    (yours,) = [n for n in page.about_you if n.kind == "tax_id"]
    alexs, mias = _about(page, alex)["tax_id"], _about(page, mia)["tax_id"]
    assert yours.letter is not None and yours.letter.id == ledger["payslip"] and yours.letters == 1
    assert len({yours.key, alexs.key, mias.key}) == 3
    assert page.also_for[yours.key] == [alex.id, mia.id]
    assert ME == MINE  # the person, in the household's own words
    assert page.also_for[alexs.key] == [MINE, mia.id]
    assert page.also_for[mias.key] == [MINE, alex.id]
    # a number only one person's letters show says nothing more
    (sv,) = [n for n in page.about_you if n.kind == "social_insurance"]
    assert sv.key not in page.also_for


def test_an_identity_document_follows_its_expiry_to_do_s_letter(store: Store, ledger: dict[str, str]) -> None:
    alex, _ = _people(store, "Alex Rivera", "Mia Rivera")
    # the person's own permit, an expiry to-do of no letter (the person's), and Alex's passport letter
    permit = _letter(
        store, "permit", kind="residence_permit", party_id=ledger["ministry"], doc_date="2026-09-16"
    )
    store.add_item(kind="expiry", title="Residence permit expires", due_date="2026-11-30", doc_id=permit)
    store.add_item(kind="expiry", title="ID card (Personalausweis) expires", due_date="2028-01-31")
    household.file(store, {ledger["passport"]: alex.id})
    page = _page(store)
    assert sorted(d.kind for d in page.documents) == ["id_card", "residence_permit"]
    (person,) = page.household
    assert person.id == alex.id
    (passport,) = person.documents
    assert (passport.kind, passport.valid_until, passport.item_id) == (
        "passport",
        "2027-03-03",
        ledger["passport_expiry"],
    )
    assert passport.number is not None and passport.number.value == "C01X00T47"
    assert passport.letter is not None and passport.letter.id == ledger["passport"]
    # the passport number is Alex's: no About group lists it, and the person's own documents never pair with it
    assert all(d.number is None for d in page.documents)
    assert _about(page, alex) == {}


def test_a_member_s_residence_permit_note_speaks_of_them(store: Store, ledger: dict[str, str]) -> None:
    alex, _ = _people(store, "Alex Rivera", "Mia Rivera")
    permits = {}
    for name, due in (("permit-ahead", "2026-11-30"), ("permit-past", "2026-09-01")):
        permits[name] = _letter(store, name, kind="residence_permit", party_id=ledger["ministry"])
        store.add_item(kind="expiry", title="Residence permit expires", due_date=due, doc_id=permits[name])
    household.file(store, {letter: alex.id for letter in permits.values()})
    (person,) = _page(store).household
    notes = {d.status: d.note for d in person.documents if d.kind == "residence_permit"}
    assert notes == {"renew_soon": MEMBER_RESIDENCE_EXTENSION_NOTE, "expired": MEMBER_RESIDENCE_EXPIRED_NOTE}
    assert "their permit" in MEMBER_RESIDENCE_EXTENSION_NOTE and "your" not in MEMBER_RESIDENCE_EXTENSION_NOTE
    assert "keep their Fiktionsbescheinigung" in MEMBER_RESIDENCE_EXPIRED_NOTE
    assert "your" not in MEMBER_RESIDENCE_EXPIRED_NOTE.replace("you", "")
    # the same law as the person's own notes
    for member, own in (
        (MEMBER_RESIDENCE_EXTENSION_NOTE, RESIDENCE_EXTENSION_NOTE),
        (MEMBER_RESIDENCE_EXPIRED_NOTE, RESIDENCE_EXPIRED_NOTE),
    ):
        assert re.findall(r"\(§[^)]*\)", member) == re.findall(r"\(§[^)]*\)", own)


def test_an_identity_number_of_a_member_without_an_expiry_is_a_document_of_theirs(
    store: Store, ledger: dict[str, str]
) -> None:
    alex, _ = _people(store, "Alex Rivera", "Mia Rivera")
    card = _letter(
        store,
        "id-card",
        ("Ausweisnummer", "L01X00T47"),
        kind="identity_document",
        party_id=ledger["ministry"],
    )
    household.file(store, {card: alex.id})
    page = _page(store)
    (person,) = page.household
    assert [(d.kind, d.number.value if d.number else None, d.valid_until) for d in person.documents] == [
        ("id_card", "L01X00T47", None)
    ]
    assert "L01X00T47" not in {d.number.value for d in page.documents if d.number}


def test_a_call_sheet_number_is_a_member_s_only_when_all_its_letters_are(
    store: Store, ledger: dict[str, str]
) -> None:
    alex, mia = _people(store, "Alex Rivera", "Mia Rivera")

    def member_number() -> tuple[str, NumbersPage]:
        page = _page(store)
        (sheet,) = [s for s in page.organisations if s.party_id == ledger["gym"]]
        (number,) = sheet.numbers
        return number.key, page

    key, page = member_number()
    assert page.filed_for == {}
    household.file(store, {ledger["gym_contract"]: alex.id})  # one of its two letters
    key, page = member_number()
    assert key not in page.filed_for
    household.file(store, {ledger["gym_price"]: alex.id})  # both
    key, page = member_number()
    assert page.filed_for == {key: alex.id}
    # one sheet per organisation still, the number listed once
    assert len([s for s in page.organisations if s.party_id == ledger["gym"]]) == 1
    household.file(store, {ledger["gym_price"]: mia.id})  # two people's
    key, page = member_number()
    assert key not in page.filed_for


def test_an_open_case_is_a_member_s_only_when_all_its_letters_are(
    store: Store, ledger: dict[str, str]
) -> None:
    alex, _ = _people(store, "Alex Rivera", "Mia Rivera")
    household.file(store, {ledger["fine"]: alex.id})
    page = _page(store)
    (case,) = page.open_cases
    assert page.filed_for[case.key] == alex.id
    for reference in case.references:
        assert page.filed_for[reference.key] == alex.id
    (sheet,) = [s for s in page.organisations if s.party_id == ledger["city"]]
    assert [c.key for c in sheet.open_cases] == [case.key]
    # a reminder of the same case, a letter of the person's own: the case is no longer only Alex's
    case_id = store.add_case(title="Parking fine", party_id=ledger["city"]).id
    reminder = _letter(store, "fine-reminder", kind="fine", party_id=ledger["city"], doc_date="2026-09-27")
    store.update_document(ledger["fine"], case_id=case_id)
    store.update_document(reminder, case_id=case_id)
    page = _page(store)
    (case,) = page.open_cases
    assert case.key not in page.filed_for
    # its references are still on Alex's letter only
    assert all(page.filed_for[reference.key] == alex.id for reference in case.references)


def test_a_label_naming_a_child_still_keeps_a_number_out_of_about(
    store: Store, ledger: dict[str, str]
) -> None:
    alex, _ = _people(store, "Alex Rivera", "Mia Rivera")
    child = _letter(
        store,
        "kindergeld",
        ("Identifikationsnummer des Kindes", "86095742719"),
        kind="tax_letter",
        party_id=ledger["employer"],
        doc_date="2026-09-10",
    )
    for link in (None, alex.id):
        if link is not None:
            household.file(store, {child: link})
        page = _page(store)
        about = [n.value for n in page.about_you] + [n.value for p in page.household for n in p.about]
        assert "86095742719" not in about, link


def test_trash_and_restore_move_the_numbers_with_their_filing(store: Store, ledger: dict[str, str]) -> None:
    alex, _ = _people(store, "Alex Rivera", "Mia Rivera")
    household.file(store, {ledger["bkk_alex"]: alex.id})
    assert "health_insurance" in _about(_page(store), alex)
    store.trash_document(ledger["bkk_alex"])
    page = _page(store)
    assert page.household == []
    assert "A123456780" not in {n.value for n in page.about_you}
    store.restore_document(ledger["bkk_alex"])
    page = _page(store)
    assert _about(page, alex)["health_insurance"].value == "A123456780"
    assert "A123456780" not in {n.value for n in page.about_you}


def test_member_entries_have_keys_of_their_own(store: Store, ledger: dict[str, str]) -> None:
    before = {n.kind: n.key for n in _page(store).about_you}
    alex, mia = _people(store, "Alex Rivera", "Mia Rivera")
    copies = []
    for name, member in (("payslip-alex", alex), ("payslip-mia", mia)):
        letter = _letter(
            store,
            name,
            ("Steuer-ID", "57 216 480 354"),
            kind="payslip",
            party_id=ledger["employer"],
            doc_date="2026-09-30",  # newer than the person's own payslip
        )
        household.file(store, {letter: member.id})
        copies.append(letter)
    page = _page(store)
    # the person's keys are what they were without a household
    assert {n.kind: n.key for n in page.about_you} == before
    keys = [before["tax_id"], _about(page, alex)["tax_id"].key, _about(page, mia)["tax_id"].key]
    assert len(set(keys)) == 3
    # and stay as they are while letters are filed back and forth
    household.file(store, {copies[0]: None})
    again = _page(store)
    assert {n.kind: n.key for n in again.about_you} == before
    assert _about(again, mia)["tax_id"].key == keys[2]


def test_numbers_never_read_the_addressee(store: Store, ledger: dict[str, str]) -> None:
    """The filing decides, never whom the letter is addressed to: a letter to Alex the person said is theirs stays
    theirs, and a letter to Sam filed for Alex is Alex's."""
    alex, _ = _people(store, "Alex Rivera", "Mia Rivera")
    to_alex = _letter(
        store,
        "to-alex",
        ("Matrikelnummer", "4711123"),
        addressee="Alex Rivera",
        kind="university",
        party_id=ledger["employer"],
    )
    to_sam = _letter(
        store,
        "to-sam",
        ("Matrikelnummer", "8800991"),
        addressee="Sam Rivera",
        kind="university",
        party_id=ledger["employer"],
    )
    household.file(store, {to_alex: MINE, to_sam: alex.id})
    page = _page(store)
    assert "4711123" in {n.value for n in page.about_you}
    assert _about(page, alex)["student"].value == "8800991"
    assert "recipient_name" not in (ROOT / "src/ordnung/numbers.py").read_text(encoding="utf-8")


def test_a_private_letter_s_numbers_stay_out_of_what_ask_is_given(
    store: Store, ledger: dict[str, str]
) -> None:
    """Ask's tool reads the page without the letters kept private (``shareable_only``), a member's too."""
    alex, _ = _people(store, "Alex Rivera", "Mia Rivera")
    household.file(store, {ledger["bkk_alex"]: alex.id})
    store.update_document(ledger["bkk_alex"], ai_private=True)
    assert _about(_page(store), alex)["health_insurance"].value == "A123456780"
    shared = _page(store, shareable_only=True)
    assert shared.household == []
    assert "A123456780" not in shared.model_dump_json()


def test_entry_letters_name_every_letter_of_each_number_newest_first(
    store: Store, ledger: dict[str, str]
) -> None:
    """What the static demo regroups by the visitor's filings (``scripts/gen_mock_numbers.py``): every letter that
    shows a number, newest first, by the key the page gives it."""
    page = _page(store)
    letters = entry_letters(numbers_input(store, TODAY))
    (member,) = [n for s in page.organisations if s.party_id == ledger["gym"] for n in s.numbers]
    assert letters[f"sheet:{member.key}"] == [ledger["gym_price"], ledger["gym_contract"]]
    (tax,) = [n for n in page.about_you if n.kind == "tax_id"]
    assert letters[f"you:{tax.key}"] == [ledger["payslip"]]
    (passport,) = page.documents
    assert passport.number is not None and letters[f"you:{passport.number.key}"] == [ledger["passport"]]
    (case,) = page.open_cases
    assert letters[f"case:{case.key}"] == [ledger["fine"]]
    assert all(letters[f"sheet:{reference.key}"] == [ledger["fine"]] for reference in case.references)


# --------------------------------------------------------------------------------------------------
# through the API
# --------------------------------------------------------------------------------------------------


async def test_filing_a_letter_regroups_my_numbers(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        store = api.ctx.store
        store.save_profile({"name": "Sam Rivera", "onboarded": True})
        bkk = _party(store, "pty_bkk", "Muster BKK", "health_insurer")
        letter = _letter(
            store, "bkk", ("Krankenversichertennummer", "A123456780"), kind="health_insurance", party_id=bkk
        )
        base = (await api.client.get("/api/household")).json()["version"]
        added = await api.client.put(
            "/api/household", json={"base": base, "members": [{"name": "Alex Rivera"}]}
        )
        assert added.status_code == 200, added.text
        (alex,) = added.json()["members"]

        def values(body: dict[str, Any]) -> tuple[list[str], dict[str, list[str]]]:
            return [n["value"] for n in body["about_you"]], {
                p["name"]: [n["value"] for n in p["about"]] for p in body["household"]
            }

        page = (await api.client.get("/api/numbers")).json()
        assert values(page) == (["A123456780"], {})
        filed = await api.client.patch("/api/household", json={"letters": {letter: alex["id"]}})
        assert filed.status_code == 200, filed.text
        page = (await api.client.get("/api/numbers")).json()
        assert values(page) == ([], {"Alex Rivera": ["A123456780"]})
        assert page["household"][0]["id"] == alex["id"]
        (sheet,) = page["organisations"]
        assert page["filed_for"] == {sheet["numbers"][0]["key"]: alex["id"]}
        # Undo: not answered again, so the person's
        undone = await api.client.patch("/api/household", json={"letters": {letter: None}})
        assert undone.status_code == 200, undone.text
        page = (await api.client.get("/api/numbers")).json()
        assert values(page) == (["A123456780"], {})
        assert (page["household"], page["filed_for"], page["also_for"]) == ([], {}, {})
