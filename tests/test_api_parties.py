"""The People & organisations drawer's data: which open to-dos are set aside instead of listed as due, and the
Land (Bundesland) the person tells Ordnung a sender is in, which dates that sender's letters — and which the
postcode on their letter may suggest, as a question (ADR 0019)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import Letter
from helpers_secretary import TODAY, add_doc, add_item
from ordnung import clock
from ordnung.api.routes.parties import get_party
from ordnung.db.store import Store
from ordnung.models import Item
from ordnung.rules import normalize_region
from ordnung.rules.calendar_de import NATIONWIDE_LABEL, REGION_NAMES
from ordnung.rules.deadlines import REGION_UNKNOWN
from ordnung.secretary import triggers
from ordnung.secretary.sender_land import idea_id
from test_api_support import Api, ApiRouter, api_for


def _party(store: Store) -> str:
    return store.add_party(name="TechMarkt Online GmbH", kind="retailer").id


def test_a_party_sets_aside_the_invoice_payment_its_reminder_took_over(store: Store) -> None:
    party = _party(store)
    case = store.add_case(title="Invoice TM-4711", party_id=party, reference="TM-4711")
    refs = [{"label": "Rechnungsnummer", "value": "TM-4711"}]
    invoice = add_doc(
        store,
        "invoice",
        kind="invoice",
        doc_date="2026-08-20",
        party_id=party,
        case_id=case.id,
        references=refs,
    )
    reminder = add_doc(
        store,
        "reminder",
        kind="dunning",
        doc_date="2026-09-10",
        party_id=party,
        case_id=case.id,
        references=refs,
    )
    old = add_item(
        store,
        kind="payment",
        title="Pay the invoice",
        due_date="2026-09-03",
        filed_on="2026-08-21",
        amount=89.99,
        direction="out",
        party_id=party,
        doc_id=invoice,
    )
    new = add_item(
        store,
        kind="payment",
        title="Pay the reminder",
        due_date="2026-09-30",
        filed_on="2026-09-11",
        amount=94.99,
        direction="out",
        party_id=party,
        doc_id=reminder,
    )

    detail = get_party(party, store, TODAY)

    assert {item.id for item in detail.items} == {old, new}  # the list stays complete
    assert [(a.item_id, a.reason, a.replaced_by) for a in detail.set_aside] == [(old, "replaced", reminder)]

    store.trash_document(reminder)  # the reminder is gone: the invoice payment is due again
    assert get_party(party, store, TODAY).set_aside == []


def test_dates_that_were_history_when_the_letter_was_read_are_set_aside(store: Store) -> None:
    party = _party(store)
    lease = add_doc(store, "lease", kind="rent_lease", doc_date="2025-09-15", party_id=party)
    deposit = add_item(
        store,
        kind="payment",
        title="Security deposit (Kaution)",
        due_date="2025-10-01",
        filed_on=TODAY.isoformat(),
        amount=1560.0,
        direction="out",
        party_id=party,
        doc_id=lease,
    )
    rent = add_item(
        store,
        kind="payment",
        title="Monthly rent",
        due_date="2025-10-01",
        filed_on=TODAY.isoformat(),
        amount=640.0,
        direction="out",
        recurrence={"interval": 1, "unit": "months"},
        party_id=party,
        doc_id=lease,
    )
    late = add_item(
        store,
        kind="deadline",
        title="Return the books",
        due_date="2026-09-25",
        filed_on="2026-09-20",
        party_id=party,
        doc_id=lease,
    )
    done = add_item(
        store,
        kind="task",
        title="Sign the lease",
        due_date="2025-09-01",
        filed_on=TODAY.isoformat(),
        status="done",
        party_id=party,
        doc_id=lease,
    )

    detail = get_party(party, store, TODAY)

    assert [(a.item_id, a.reason) for a in detail.set_aside] == [(deposit, "history")]
    shown = {item.id for item in detail.items}
    assert {rent, late, done} <= shown  # a schedule, a really overdue date and a done one stay as they are


def test_to_dos_of_a_letter_with_scam_signs_are_set_aside(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    party = _party(store)
    letter = add_doc(
        store, "fake", kind="invoice", doc_date="2026-09-20", party_id=party, direction="incoming"
    )
    pay = add_item(
        store,
        kind="payment",
        title="Pay now",
        due_date="2026-10-01",
        filed_on="2026-09-21",
        amount=499.0,
        direction="out",
        party_id=party,
        doc_id=letter,
    )
    monkeypatch.setattr(
        triggers, "_scam_reasons", lambda _store, doc, _party: ["new IBAN"] if doc.id == letter else []
    )

    assert [(a.item_id, a.reason) for a in get_party(party, store, TODAY).set_aside] == [(pay, "suspicious")]


# --------------------------------------------------------------------------------------------------
# the Land a sender is in: only the person sets it
# --------------------------------------------------------------------------------------------------

NOTICE = "Gegen diesen Bescheid können Sie binnen eines Monats nach seiner Bekanntgabe Widerspruch einlegen."


#: The city's address on its letters: a Leipzig postcode, so a Saxon one.
CITY_ADDRESS = "Rathausplatz 1, 04109 Beispielhausen"


def _decision(marker: str, sender: str) -> Letter:
    """A city's fee decision dated Wed 14 Oct 2026 with a one-month objection; nothing on it names its Land,
    only its postcode suggests one."""
    return Letter(
        marker=marker,
        pages=(
            (
                f"{sender} · Ordnungsamt · Rathausplatz 1 · 04109 Beispielhausen",
                f"SPECIMEN {marker}",
                "Datum: 14.10.2026",
                "Bescheid über eine Sondernutzungsgebühr",
                "Sehr geehrte Frau Probe,",
                "für die Nutzung der Gehwegfläche setzen wir eine Gebühr von 85,00 EUR fest.",
                "Rechtsbehelfsbelehrung",
                "Gegen diesen Bescheid können Sie binnen eines Monats",
                "nach seiner Bekanntgabe Widerspruch einlegen.",
            ),
        ),
        payload={
            "kind": "authority_letter",
            "title": "Fee decision",
            "summary": "A fee for using the pavement.",
            "explanation": "You can object within a month.",
            "sender": {"name": sender, "kind": "authority", "address": CITY_ADDRESS},
            "document_date": "2026-10-14",
            "remedy": {"type": "widerspruch", "quote": NOTICE},
            "items": [
                {
                    "kind": "deadline",
                    "title": "Objection (Widerspruch)",
                    "date": {
                        "type": "relative",
                        "amount": 1,
                        "unit": "months",
                        "anchor": "deemed_delivery",
                        "delivery_rule": "de_admin_post",
                        "nature": "objection",
                        "text": "binnen eines Monats nach seiner Bekanntgabe",
                    },
                    "quote": NOTICE,
                }
            ],
        },
    )


CITY = _decision("Gehwegbescheid", "Stadt Beispielhausen")
OTHER_CITY = _decision("Plakatbescheid", "Stadt Anderswo")


def _router(*letters: Letter) -> ApiRouter:
    router = ApiRouter()
    router.letters = (*letters, *router.letters)
    for letter in letters:
        router.payloads[letter.marker] = letter.extraction()
    return router


@pytest.fixture
def mid_october() -> Iterator[None]:
    clock.set_today("2026-10-15")
    yield
    clock.set_today(None)


async def _read(api: Api, letter: Letter) -> tuple[str, str]:
    """Read ``letter``; its id and its sender's."""
    doc_id = (await api.upload((f"{letter.marker}.pdf", letter.pdf())))["documents"][0]["id"]
    await api.read_all()
    document = api.ctx.store.get_document(doc_id)
    assert document is not None and document.party_id is not None
    return doc_id, document.party_id


def _objection(api: Api, doc_id: str) -> Item:
    [objection] = api.ctx.store.list_items(doc_id=doc_id)
    assert objection.computation is not None
    return objection


async def test_the_land_the_person_sets_for_a_sender_dates_its_letters(
    data_dir: Path, mid_october: None
) -> None:
    """M3: reading never sets a sender's Land, so the objection counts nationwide holidays and the 3-day rule:
    Tue 17 Nov 2026, at lower confidence. In Saxony (4-day rule) delivery is Sun 18 Oct and one month later is
    Wed 18 Nov, Buß- und Bettag there: Thu 19 Nov. In Hamburg, where it is no holiday: Wed 18 Nov. The date
    without the Land is never later than the law's in any Land, and "Don't know" brings it back."""
    async with api_for(data_dir, router=_router(CITY)) as api:
        doc_id, party_id = await _read(api, CITY)
        party = api.ctx.store.get_party(party_id)
        assert party is not None and party.region is None
        unknown = _objection(api, doc_id)
        assert unknown.due_date == "2026-11-17" and unknown.computation is not None
        assert unknown.computation.holiday_calendar == NATIONWIDE_LABEL
        assert unknown.computation.confidence != "high"
        # the words the letter page's "Choose their state" keys on (web/src/features/document/WhyThisDate.tsx)
        assert any("couldn't confirm this sender's" in w for w in unknown.computation.warnings)
        assert REGION_UNKNOWN == "Holiday region unknown"
        # its postcode suggests Saxony: a question, and the Land stays unset
        asked = (await api.client.get(f"/api/parties/{party_id}")).json()
        assert asked["party"]["region"] is None and asked["region_suggestion"]["region"] == "SN"

        async def set_land(region: str | None) -> Item:
            response = await api.client.patch(f"/api/parties/{party_id}", json={"region": region})
            assert response.status_code == 200, response.text
            assert response.json()["region"] == normalize_region(region)
            detail = (await api.client.get(f"/api/parties/{party_id}")).json()
            assert detail["party"]["region"] == normalize_region(region)
            assert (detail["region_suggestion"] is None) == (region is not None)
            return _objection(api, doc_id)

        saxony = await set_land("sn")
        assert saxony.due_date == "2026-11-19" and saxony.computation is not None
        assert saxony.computation.holiday_calendar == "Sachsen" and saxony.computation.confidence == "high"
        assert any("Buß- und Bettag" in step.label for step in saxony.computation.steps)
        assert (await set_land("Hamburg")).due_date == "2026-11-18"
        by_land = {code: (await set_land(code)).due_date for code in REGION_NAMES}
        assert all(due is not None and due >= "2026-11-17" for due in by_land.values()), by_land
        assert by_land["SN"] == "2026-11-19"
        assert (await set_land(None)).due_date == "2026-11-17"


async def test_a_sender_s_land_recomputes_only_its_own_letters(data_dir: Path, mid_october: None) -> None:
    async with api_for(data_dir, router=_router(CITY, OTHER_CITY)) as api:
        city, city_party = await _read(api, CITY)
        other, other_party = await _read(api, OTHER_CITY)
        assert city_party != other_party
        response = await api.client.patch(f"/api/parties/{city_party}", json={"region": "SN"})
        assert response.status_code == 200
        assert _objection(api, city).due_date == "2026-11-19"
        assert _objection(api, other).due_date == "2026-11-17"  # its sender's Land is still not known


async def test_a_sender_s_land_is_one_bundesland_or_not_known(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        party = api.ctx.store.add_party(name="Stadt Beispielhausen", kind="authority")
        url = f"/api/parties/{party.id}"
        for bad in ({"region": "Atlantis"}, {"region": "BY+NW"}, {}, {"region": "NW", "name": "Renamed"}):
            assert (await api.client.patch(url, json=bad)).status_code == 422, bad
        assert (await api.client.patch("/api/parties/pty_unknown", json={"region": "NW"})).status_code == 404
        first = await api.client.patch(url, json={"region": "Nordrhein-Westfalen"})
        assert first.status_code == 200 and first.json()["region"] == "NW"
        again = await api.client.patch(url, json={"region": "nw"})
        assert again.status_code == 200 and again.json() == first.json()  # unchanged: nothing recomputed
        assert (await api.client.patch(url, json={"region": None})).json()["region"] is None


async def test_the_postcode_on_their_letter_asks_and_never_sets_the_land(
    data_dir: Path, mid_october: None
) -> None:
    """The drawer and the letter carry the question, and reading them moves no date. "Don't know" in the State
    select of a sender without a Land records nothing (the question's own "Don't know" dismisses its Idea); Yes
    sets the Land, which recomputes the letter's dates and expires the Idea."""
    async with api_for(data_dir, router=_router(CITY)) as api:
        store = api.ctx.store
        doc_id, party_id = await _read(api, CITY)
        before = store.list_items()

        detail = (await api.client.get(f"/api/parties/{party_id}")).json()
        letter = (await api.client.get(f"/api/documents/{doc_id}")).json()

        question = {
            "region": "SN",
            "postcode": "04109",
            "doc_id": doc_id,
            "waiting": 1,  # Saxony's authorities count 4 days, Ordnung 3 until it is confirmed
            "may_be_late": False,
            "idea_id": idea_id(party_id, "SN"),
            "declined": False,
        }
        assert detail["party"]["region"] is None and letter["party"]["region"] is None
        assert detail["region_suggestion"] == letter["region_suggestion"] == question
        assert store.list_items() == before
        idea = store.get_suggestion(idea_id(party_id, "SN"))
        assert idea is not None and idea.status == "new"
        assert idea.title == "Is Stadt Beispielhausen in Saxony?"

        logged = store.list_activity(limit=None)
        unset = await api.client.patch(f"/api/parties/{party_id}", json={"region": None})
        assert unset.status_code == 200 and unset.json()["region"] is None
        assert store.list_items() == before and store.list_activity(limit=None) == logged
        idea = store.get_suggestion(idea_id(party_id, "SN"))
        assert idea is not None and idea.status == "new"

        assert (await api.client.patch(f"/api/parties/{party_id}", json={"region": "SN"})).status_code == 200
        assert _objection(api, doc_id).due_date == "2026-11-19"
        assert (await api.client.get(f"/api/parties/{party_id}")).json()["region_suggestion"] is None
        assert (await api.client.get(f"/api/documents/{doc_id}")).json()["region_suggestion"] is None
        idea = store.get_suggestion(idea_id(party_id, "SN"))
        assert idea is not None and idea.status == "expired"
