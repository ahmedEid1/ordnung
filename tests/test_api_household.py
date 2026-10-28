"""``/api/household``: who the person's letters are for (D3, ADR 0023). The policy is in
``test_household.py``; here the routes: their answers and refusals, the letter's page, the live event, hand-off
sync's gate, the phone, and Ask's ledger left alone."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import record_events
from ordnung.assistant.ask import ledger_fingerprint
from ordnung.db.store import HOUSEHOLD_META_KEY, PERSON_META_KEY, Store
from ordnung.models import PROOF_SOURCE, DocumentExtraction, Profile
from ordnung.secretary import household
from test_api_support import Api, api_for

EMPTY = {"members": [], "filed": {}, "mine": [], "suggested": {}, "version": "4f53cda18c2baa0c"}
SAM, ALEX, MIA = "Sam Rivera", "Alex Rivera", "Mia Rivera"
DEMO_DB = Path(__file__).resolve().parents[1] / "src" / "ordnung" / "demo" / "demo_db"
#: Ask's ledger fingerprint of the demo (plan §1): household writes never move it.
DEMO_FINGERPRINT = "6d63e0d2ead937a6c8e4fd974c537b368c20101035bd70fc8f1038096a550b08"


def _letter(store: Store, name: str, recipient: str | None, *, source: str = "upload") -> str:
    """A received letter with a reading addressed to ``recipient`` (no file on disk)."""
    document = store.add_document(
        sha256=name.encode().hex().ljust(64, "0")[:64],
        filename=f"{name}.pdf",
        mime="application/pdf",
        file_path=f"files/{name}.pdf",
        direction="incoming",
        source=source,
        status="processed",
    )
    extraction = DocumentExtraction(
        kind="invoice", title=name, summary="s", explanation="e", recipient_name=recipient
    )
    store.update_document(document.id, extraction=extraction, title=name)
    return document.id


def _as_sam(api: Api) -> None:
    api.ctx.store.save_profile(Profile(name=SAM, onboarded=True).model_dump())


async def _put(
    api: Api, *members: dict[str, Any], also_file: list[str] | None = None, base: str | None = None
) -> Any:
    if base is None:
        base = (await api.client.get("/api/household")).json()["version"]
    body: dict[str, Any] = {"base": base, "members": list(members)}
    if also_file is not None:
        body["also_file"] = also_file
    return await api.client.put("/api/household", json=body)


async def _ok(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


def _people(answer: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"id": m["id"], "name": m["name"], "signs": m["signs"]} for m in answer["members"]]


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


async def test_put_adds_renames_and_removes(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        _as_sam(api)
        added = await _ok(await _put(api, {"name": ALEX}, {"name": MIA, "signs": False}))
        alex, mia = (m["id"] for m in added["members"])
        assert added["members"] == [
            {"id": alex, "name": ALEX, "signs": True, "letters": 0},
            {"id": mia, "name": MIA, "signs": False, "letters": 0},
        ]
        assert added["version"] == household.version(household.load(api.ctx.store).members)
        renamed = await _ok(
            await _put(
                api, {"id": mia, "name": "Mia Rivera-Smith", "signs": True}, {"id": alex, "name": ALEX}
            )
        )
        assert _people(renamed) == [
            {"id": mia, "name": "Mia Rivera-Smith", "signs": True},
            {"id": alex, "name": ALEX, "signs": True},
        ]
        removed = await _ok(await _put(api, {"id": alex, "name": ALEX}))
        assert _people(removed) == [{"id": alex, "name": ALEX, "signs": True}]
        assert (await api.client.get("/api/household")).json() == removed
        refused = await _put(api, {"id": alex, "name": ALEX}, {"name": SAM})
        assert refused.status_code == 422
        assert (
            refused.json()["detail"]
            == "That's your own name. Your household is the other people your letters come for."
        )
        # the schema's own limits: an unknown field, too many people, more than one letter to file at once
        base = removed["version"]
        for body in (
            {"base": base, "members": [], "extra": 1},
            {"base": base, "members": [{"name": ALEX, "role": "child"}]},
            {"base": base, "members": [{"name": f"P {n}"} for n in range(51)]},
            {"base": base, "members": [{"name": MIA}], "also_file": ["doc_a", "doc_b"]},
            {"base": base, "members": [{"name": "x" * 1001}]},
        ):
            assert (await api.client.put("/api/household", json=body)).status_code == 422, body
        assert (await api.client.get("/api/household")).json() == removed


async def test_put_from_an_old_base_is_refused(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        _as_sam(api)
        await _ok(await _put(api, {"name": ALEX}))
        stale = await _put(api, {"name": MIA}, base=EMPTY["version"])
        assert stale.status_code == 409
        assert (
            stale.json()["detail"]
            == "Your household changed in another window. Look again, then try once more."
        )
        assert [m["name"] for m in (await api.client.get("/api/household")).json()["members"]] == [ALEX]


async def test_put_also_files_the_letter_for_the_one_new_person(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        _as_sam(api)
        letter = _letter(api.ctx.store, "alex", ALEX)
        answer = await _ok(await _put(api, {"name": ALEX}, also_file=[letter]))
        (alex,) = (m["id"] for m in answer["members"])
        assert answer["filed"] == {letter: alex} and answer["members"][0]["letters"] == 1
        trashed = _letter(api.ctx.store, "trashed", MIA)
        api.ctx.store.trash_document(trashed)
        refused = await _put(api, {"id": alex, "name": ALEX}, {"name": MIA}, also_file=[trashed])
        assert refused.status_code == 404
        assert [m["name"] for m in (await api.client.get("/api/household")).json()["members"]] == [ALEX]


async def test_patch_files_says_mine_and_forgets_in_one_change(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        _as_sam(api)
        alex, mia = (m["id"] for m in (await _ok(await _put(api, {"name": ALEX}, {"name": MIA})))["members"])
        first, second, third = (_letter(api.ctx.store, name, ALEX) for name in ("first", "second", "third"))
        before = await _ok(await api.client.get("/api/household"))
        assert before["suggested"] == {first: alex, second: alex, third: alex}
        filed = await _ok(
            await api.client.patch(
                "/api/household", json={"letters": {first: alex, second: "me", third: mia}}
            )
        )
        assert filed["filed"] == {first: alex, third: mia} and filed["mine"] == [second]
        assert filed["suggested"] == {}
        assert [m["letters"] for m in filed["members"]] == [1, 1]
        undone = await _ok(
            await api.client.patch(
                "/api/household", json={"letters": {first: None, second: None, third: "me"}}
            )
        )
        assert undone["filed"] == {} and undone["mine"] == [third]
        assert undone["suggested"] == {first: alex, second: alex}
        for body in (
            {"letters": {}},
            {"letters": {f"doc_{n}": None for n in range(1001)}},
            {"letters": {first: 1}},
            {"x": 1},
        ):
            assert (await api.client.patch("/api/household", json=body)).status_code == 422, str(body)[:60]


async def test_patch_refuses_unknown_people_trash_and_proof_files(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        _as_sam(api)
        (alex,) = (m["id"] for m in (await _ok(await _put(api, {"name": ALEX})))["members"])
        letter = _letter(api.ctx.store, "letter", ALEX)
        trashed = _letter(api.ctx.store, "trashed", ALEX)
        api.ctx.store.trash_document(trashed)
        proof = _letter(api.ctx.store, "proof", ALEX, source=PROOF_SOURCE)
        cases = [
            ({letter: "hhm_000000000000"}, 422, "That person isn't in your household any more."),
            ({letter: alex, trashed: alex}, 404, "This letter doesn't exist (any more)."),
            ({"doc_nothere": "me"}, 404, "This letter doesn't exist (any more)."),
            ({proof: "me"}, 422, "A proof file belongs to the letter it proves, not to a person."),
        ]
        for letters, status, detail in cases:
            refused = await api.client.patch("/api/household", json={"letters": letters})
            assert (refused.status_code, refused.json()["detail"]) == (status, detail), letters
        assert (await api.client.get("/api/household")).json()["filed"] == {}


async def test_a_letter_s_page_says_who_it_is_for(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        _as_sam(api)
        store = api.ctx.store
        for_alex = _letter(store, "alex", "Frau Alex Rivera")
        for_kim = _letter(store, "kim", "Herrn Kim Rivera")
        for_sam = _letter(store, "sam", SAM)
        family = _letter(store, "family", "Familie Rivera")

        async def page(doc_id: str) -> dict[str, Any]:
            answer = await _ok(await api.client.get(f"/api/documents/{doc_id}"))
            for_whom: dict[str, Any] = answer["household"]
            return for_whom

        nothing = {"filed_for": None, "mine": False, "suggested": None, "add": None}
        # no household yet: a letter for one other person offers to add them
        assert await page(for_alex) == {**nothing, "add": ALEX}
        assert await page(for_sam) == nothing and await page(family) == nothing
        (alex,) = (m["id"] for m in (await _ok(await _put(api, {"name": ALEX})))["members"])
        member = {"id": alex, "name": ALEX, "signs": True}
        assert await page(for_alex) == {**nothing, "suggested": member}
        assert await page(for_kim) == {**nothing, "add": "Kim Rivera"}
        await _ok(await api.client.patch("/api/household", json={"letters": {for_alex: alex, for_kim: "me"}}))
        assert await page(for_alex) == {**nothing, "filed_for": member}
        assert await page(for_kim) == {**nothing, "mine": True}
        store.trash_document(for_alex)
        assert await page(for_alex) == nothing  # in the trash: its filing is dormant


async def test_household_writes_announce_profile_updated(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        _as_sam(api)
        events = record_events(api.ctx.bus)
        (alex,) = (m["id"] for m in (await _ok(await _put(api, {"name": ALEX})))["members"])
        letter = _letter(api.ctx.store, "letter", ALEX)
        await _ok(await api.client.patch("/api/household", json={"letters": {letter: alex}}))
        assert [kind for kind, _ in events] == ["profile.updated", "profile.updated"]
        stale = await _put(api, {"name": MIA}, base=EMPTY["version"])
        mistake = await _put(api, {"id": alex, "name": ALEX}, {"name": SAM})
        assert (stale.status_code, mistake.status_code) == (409, 422)
        assert len(events) == 2  # refused: nothing changed, nothing announced


async def test_household_writes_are_person_changes_and_wait_while_standing_by(data_dir: Path) -> None:
    from sync_fake_engine import counter
    from sync_support import computer, connect
    from test_api_sync import _standby

    folder = data_dir.parent / "sync-folder"
    folder.mkdir()
    async with computer(data_dir) as api:
        _as_sam(api)
        await connect(api, folder, "desktop")
        before = counter(api.ctx.store)
        (alex,) = (m["id"] for m in (await _ok(await _put(api, {"name": ALEX})))["members"])
        assert counter(api.ctx.store) == before + 1
        letter = _letter(api.ctx.store, "letter", ALEX)
        await _ok(await api.client.patch("/api/household", json={"letters": {letter: alex}}))
        assert counter(api.ctx.store) == before + 2
        await _ok(await api.client.patch("/api/household", json={"letters": {letter: alex}}))
        assert counter(api.ctx.store) == before + 2  # the same answer again: no change, no new version
    async with computer(data_dir, start=False) as api:
        _standby(api)
        for method, body in (("PUT", {"base": "x", "members": []}), ("PATCH", {"letters": {letter: "me"}})):
            refused = await api.client.request(method, "/api/household", json=body)
            assert refused.status_code == 409 and refused.json()["code"] == "standby", method
        assert (await api.client.get("/api/household")).json()["filed"] == {letter: alex}


async def test_a_phone_reads_and_files_but_never_edits_the_household(data_dir: Path) -> None:
    from phone_support import pair, phone_app, phone_client, phone_of

    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        signed = await pair(api, phone)
        device = phone_of(api).devices[0].id
        (alex,) = (m["id"] for m in (await _ok(await _put(api, {"name": ALEX})))["members"])
        letter = _letter(api.ctx.store, "letter", ALEX)
        read = await _ok(await phone.get("/api/household"))
        assert read["suggested"] == {letter: alex}
        filed = await _ok(await phone.patch("/api/household", json={"letters": {letter: alex}}))
        assert filed["filed"] == {letter: alex}
        refused = await phone.put("/api/household", json={"base": read["version"], "members": []})
        assert refused.status_code == 403
        assert refused.json() == {"detail": "This works on your computer only.", "code": "computer_only"}
        assert [m["name"] for m in (await api.client.get("/api/household")).json()["members"]] == [ALEX]
        log = (await api.client.get("/api/activity", params={"device": device})).json()
        changes = [entry for entry in log if entry["kind"] == "phone.changed"]
        assert [entry["data"]["operation"] for entry in changes] == ["PATCH /api/household"]
        assert changes[0]["message"] == f"Changed who a letter is for on {signed['name']}"


async def test_household_writes_leave_ask_s_ledger_alone(data_dir: Path) -> None:
    """Ask's ledger fingerprint never reads the household, and the ledger token (moved by this connection's
    writes to what the fingerprint reads) stays where it was for household writes on the same connection."""
    async with api_for(data_dir) as api:
        _as_sam(api)
        store = api.ctx.store
        letter = _letter(store, "letter", ALEX)
        fingerprint = ledger_fingerprint(store)
        alex = (await _ok(await _put(api, {"name": ALEX}, also_file=[letter])))["members"][0]["id"]
        await _ok(await api.client.patch("/api/household", json={"letters": {letter: "me"}}))
        await _ok(await _put(api, {"id": alex, "name": "Alex Rivera-Smith"}))
        assert ledger_fingerprint(store) == fingerprint
        # the same writes on this thread's own connection: written, and the ledger token stays
        token, changes = store.ledger_token(), store.change_token()
        view = household.change(store, base=household.version(household.load(store).members), members=[])
        household.file(store, {letter: None})
        assert view["members"] == [] and store.change_token() != changes
        assert store.ledger_token() == token
        assert ledger_fingerprint(store) == fingerprint


@pytest.mark.parametrize("demo", [DEMO_DB])
async def test_household_writes_leave_the_demo_s_fingerprint_alone(tmp_path: Path, demo: Path) -> None:
    """On a copy of the demo: saving a household with one filed letter leaves Ask's fingerprint as it was
    (plan §1)."""
    data_dir = tmp_path / "demo"
    shutil.copytree(demo, data_dir)
    async with api_for(data_dir) as api:
        store = api.ctx.store
        assert store.get_meta(HOUSEHOLD_META_KEY) is None
        assert ledger_fingerprint(store) == DEMO_FINGERPRINT
        letter = store.list_documents()[0].id
        answer = await _ok(await _put(api, {"name": ALEX}, also_file=[letter]))
        await _ok(
            await api.client.patch("/api/household", json={"letters": {letter: answer["members"][0]["id"]}})
        )
        await _ok(await _put(api, {"id": answer["members"][0]["id"], "name": ALEX}, {"name": MIA}))
        assert store.get_meta(HOUSEHOLD_META_KEY) is not None
        assert ledger_fingerprint(store) == DEMO_FINGERPRINT
        assert store.get_meta(PERSON_META_KEY) is None  # sync off: no person counter either
