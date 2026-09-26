"""High-stakes letters end to end: reading → the kind code files → routed dates → the deadlines the
law adds → the "get advice" card, corrections of the kind and the arrival day, and re-reading.

The letters are SPECIMEN texts with the extraction a model would return; the extraction prompt is
unchanged, so every high-stakes signal comes from the model's ordinary reading (ADR 0002).
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import Letter, Router
from ordnung import clock
from ordnung.ingest.plan import corrections, filed_kind, needs_check, with_corrections
from ordnung.models import DocumentExtraction, Item
from test_api_support import TODAY, Api, ApiRouter, api_for

MB_QUOTE = "Sie können binnen zwei Wochen seit der Zustellung dieses Bescheids Widerspruch erheben."
#: The warning every Mahnbescheid carries (§ 692 Abs. 1 Nr. 4 ZPO); a reading quotes it as a matter of course.
MB_WARNING = (
    "Nach Ablauf dieser Frist kann der Antragsteller einen Vollstreckungsbescheid erwirken und aus diesem "
    "die Zwangsvollstreckung betreiben."
)
MAHNBESCHEID = Letter(
    marker="Mahnbescheid",
    pages=(
        (
            "Amtsgericht Hagen - Zentrales Mahngericht - 58084 Hagen",
            "SPECIMEN",
            "Mahnbescheid vom 21.09.2026",
            "Geschäftsnummer: 26-1234567-0-8",
            "Antragsteller: Inkasso Nord GmbH, Hauptforderung 480,00 EUR",
            MB_QUOTE,
            MB_WARNING,
        ),
    ),
    payload={
        "kind": "authority_letter",
        "area": "money",
        "title": "Mahnbescheid (court payment order)",
        "sender": {"name": "Amtsgericht Hagen - Zentrales Mahngericht", "kind": "authority"},
        "document_date": "2026-09-21",
        "references": [{"label": "Geschäftsnummer", "value": "26-1234567-0-8"}],
        "summary": (
            "A court payment order for 480 EUR claimed by Inkasso Nord GmbH; without an objection the claimant "
            "can apply for an enforcement order (Vollstreckungsbescheid)."
        ),
        "key_facts": [{"label": "If you don't object", "value": "Enforcement order", "quote": MB_WARNING}],
        "explanation": "Pay or object within two weeks.",
        "items": [
            {
                "kind": "deadline",
                "title": "Object or pay",
                "date": {
                    "type": "relative",
                    "anchor": "receipt",
                    "amount": 2,
                    "unit": "weeks",
                    "nature": "objection",
                    "text": "binnen zwei Wochen seit der Zustellung dieses Bescheids",
                },
                "quote": MB_QUOTE,
            }
        ],
        "remedy": {"type": "widerspruch", "addressee": "Amtsgericht Hagen", "quote": MB_QUOTE},
        "urgency": "critical",
    },
)

DISMISSAL_QUOTE = "hiermit kündigen wir das Arbeitsverhältnis fristgerecht zum 31.12.2026."
DISMISSAL = Letter(
    marker="Kündigung Arbeitsverhältnis",
    pages=(
        (
            "Café Kranz GmbH · Marktplatz 3 · 12345 Musterstadt",
            "SPECIMEN",
            "Musterstadt, 24.09.2026",
            "Kündigung Arbeitsverhältnis",
            "Sehr geehrte Frau Rivera,",
            DISMISSAL_QUOTE,
        ),
    ),
    payload={
        "kind": "employment",
        "area": "work",
        "title": "Dismissal by Café Kranz",
        "sender": {"name": "Café Kranz GmbH", "kind": "employer"},
        "document_date": "2026-09-24",
        "summary": "Your employer ends your job on 31 Dec 2026.",
        "explanation": "Your job ends.",
        "items": [],
        "change": {
            "type": "termination_by_provider",
            "effective_date": "2026-12-31",
            "quote": DISMISSAL_QUOTE,
        },
        "urgency": "high",
    },
)

STATEMENT_QUOTE = "Abrechnungszeitraum: 01.01.2025 - 31.12.2025"
STATEMENT = Letter(
    marker="Betriebskostenabrechnung",
    pages=(
        (
            "Wohnbau Muster GmbH",
            "SPECIMEN",
            "Betriebskostenabrechnung",
            STATEMENT_QUOTE,
            "Nachzahlung 120,00 EUR",
        ),
    ),
    payload={
        "kind": "utility_bill",
        "area": "home",
        "title": "Operating-cost statement 2025",
        "sender": {"name": "Wohnbau Muster GmbH", "kind": "landlord"},
        "document_date": "2026-09-10",
        "summary": "Betriebskostenabrechnung 2025 with a back-payment of 120 EUR.",
        "explanation": "Check it.",
        "items": [],
        "key_facts": [{"label": "Billing period", "value": "2025", "quote": STATEMENT_QUOTE}],
    },
)

LETTERS = (MAHNBESCHEID, DISMISSAL, STATEMENT)


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


def _router() -> ApiRouter:
    router = ApiRouter()
    Router.__init__(router, letters=LETTERS)
    return router


async def _read(api: Api, letter: Letter) -> str:
    body = await api.upload((f"{letter.marker}.pdf", letter.pdf()))
    await api.read_all()
    return str(body["documents"][0]["id"])


def _by_origin(api: Api, doc_id: str) -> dict[str, list[Item]]:
    found: dict[str, list[Item]] = {}
    for item in api.ctx.store.list_items(doc_id=doc_id):
        found.setdefault(item.origin, []).append(item)
    return found


async def test_a_court_payment_order_is_filed_routed_and_carries_the_advice_card(data_dir: Path) -> None:
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, MAHNBESCHEID)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "court_payment_order"
        [objection] = detail["items"]  # the letter's own deadline follows the court rule: no duplicate
        assert objection["origin"] == "extracted"
        assert (
            objection["due_date"] == "2026-10-05"
        )  # from the letter's date until the envelope date is known
        assert "zpo_692" in objection["computation"]["rule_ids"]
        assert objection["computation"]["confidence"] == "low"
        advice = detail["advice"]
        assert advice["kind"] == "court_payment_order" and advice["urgent"] is True
        assert advice["help"][0]["name"].startswith("Rechtsantragstelle")
        assert any(
            "may be time-barred" in fact["title"].lower() or "may be time-barred" in fact["text"]
            for fact in advice["facts"]
        )

        # the envelope date: two weeks from Thu 24 Sep
        response = await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-24"})
        assert response.status_code == 200
        [objection_item] = api.ctx.store.list_items(doc_id=doc_id)
        assert objection_item.due_date == "2026-10-08"
        assert objection_item.computation is not None and objection_item.computation.confidence == "medium"

        filtered = (await api.client.get("/api/documents", params={"kind": "court_payment_order"})).json()
        assert [doc["id"] for doc in filtered] == [doc_id]


async def test_correcting_the_kind_reroutes_the_dates(data_dir: Path) -> None:
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, MAHNBESCHEID)
        response = await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "authority_letter"})
        assert response.status_code == 200
        [item] = api.ctx.store.list_items(doc_id=doc_id)
        assert item.computation is not None and "zpo_692" not in item.computation.rule_ids
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["advice"] is None

        activity = (await api.client.get("/api/activity")).json()
        assert any(
            entry["kind"] == "document.kind" and entry["data"]["kind"] == "authority_letter"
            for entry in activity
        )

        # re-reading keeps the person's correction, although it is the model's own kind
        await api.client.post(f"/api/documents/{doc_id}/reprocess")
        await api.read_all()
        assert (api.ctx.store.get_document(doc_id) or pytest.fail()).kind == "authority_letter"


async def test_a_letter_filed_before_ordnung_knew_its_kind_gets_it_when_read_again(data_dir: Path) -> None:
    """An older Ordnung filed a Mahnbescheid under the model's kind. That is no correction by the
    person, so "Read again" files it as a court order with its card and its rule to-do."""
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, MAHNBESCHEID)
        api.ctx.store.update_document(doc_id, kind="authority_letter")  # as an older version stored it
        await api.client.post(f"/api/documents/{doc_id}/reprocess")
        await api.read_all()
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "court_payment_order"
        assert detail["advice"] is not None and detail["advice"]["urgent"]


async def test_a_dismissal_gets_the_deadlines_the_law_adds(data_dir: Path) -> None:
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, DISMISSAL)
        document = api.ctx.store.get_document(doc_id)
        assert document is not None and document.kind == "dismissal"
        assert document.status == "processed"  # a deadline set by law has no quote to check
        rules = {item.slot_key: item for item in _by_origin(api, doc_id)["rule"]}
        court, register = rules["rule:kschg_4"], rules["rule:sgb3_38"]
        assert (
            court.due_date == "2026-10-15" and court.priority == "critical"
        )  # 3 weeks from the letter's date
        assert court.computation is not None and court.computation.confidence == "low"
        assert register.due_date == "2026-09-30"  # three months before 31 Dec
        assert not needs_check(court) and court.grounding == "model_read" and court.evidence == []
        assert court.date_spec is not None and court.date_spec.anchor == "receipt"

        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["advice"]["kind"] == "dismissal" and detail["advice"]["urgent"]

        # the person confirms the arrival: the rule to-dos follow
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-25"})
        court_after = api.ctx.store.get_item(court.id)
        assert court_after is not None and court_after.due_date == "2026-10-16"
        assert court_after.computation is not None and court_after.computation.confidence == "medium"


async def test_rule_to_dos_survive_re_reading_and_leave_when_the_kind_is_corrected(data_dir: Path) -> None:
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, DISMISSAL)
        rules = {item.slot_key: item for item in _by_origin(api, doc_id)["rule"]}
        api.ctx.store.update_item(rules["rule:sgb3_38"].id, status="done")

        await api.client.post(f"/api/documents/{doc_id}/reprocess")
        await api.read_all()
        again = {item.slot_key: item for item in _by_origin(api, doc_id)["rule"]}
        assert {item.id for item in again.values()} == {item.id for item in rules.values()}
        assert again["rule:sgb3_38"].status == "done"

        await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "employment"})
        left = _by_origin(api, doc_id).get("rule", [])
        assert [item.slot_key for item in left] == ["rule:sgb3_38"]  # done: kept; open: removed


async def test_an_operating_cost_statement_keeps_its_kind_and_gets_its_card_on_read(data_dir: Path) -> None:
    async with api_for(data_dir, router=_router()) as api:
        doc_id = await _read(api, STATEMENT)
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["kind"] == "utility_bill"
        assert detail["items"] == []
        advice = detail["advice"]
        assert advice["kind"] == "operating_costs" and not advice["urgent"]
        assert advice["facts"][0]["title"] == "Probably on time"


# ------------------------------------------------------------------------------------ corrections


def _reading(letter: Letter, **update: Any) -> DocumentExtraction:
    payload = copy.deepcopy(letter.payload)
    payload.update(update)
    return DocumentExtraction.model_validate(payload)


def test_the_filed_kind_is_the_persons_correction_else_the_kind_code_reads() -> None:
    reading = _reading(MAHNBESCHEID)
    assert filed_kind(reading, {}) == "court_payment_order"
    assert filed_kind(reading, {"kind": "dunning"}) == "dunning"
    # a high-stakes correction stays out of the reading (which keeps the model's vocabulary)
    assert with_corrections(reading, {"kind": "enforcement_order"}).kind == "authority_letter"
    assert with_corrections(reading, {"kind": "dunning"}).kind == "dunning"
    assert with_corrections(reading, {}) is reading


def test_a_kind_the_person_chose_is_a_correction() -> None:
    from ordnung.models import Document

    reading = _reading(MAHNBESCHEID)
    base = {
        "id": "doc_x",
        "sha256": "x",
        "filename": "x.pdf",
        "mime": "application/pdf",
        "created_at": "",
        "updated_at": "",
    }
    filed = Document(
        **base, kind="court_payment_order", title=reading.title, area="money", doc_date="2026-09-21"
    )
    assert corrections(filed, reading) == {}
    # the person's choice wins, even when it is the model's own kind
    for chosen in ("dunning", "authority_letter"):
        kind_set = filed.model_copy(update={"kind": chosen})
        assert corrections(kind_set, reading, chosen_kind=chosen) == {"kind": chosen}
    # a kind that is neither Ordnung's nor the model's was set by the person (an older API call)
    assert corrections(filed.model_copy(update={"kind": "dunning"}), reading) == {"kind": "dunning"}
    # the model's own kind, filed by an older Ordnung, is no correction: reading again reclassifies
    old = filed.model_copy(update={"kind": "authority_letter"})
    assert corrections(old, reading) == {}
    assert corrections(old, reading, chosen_kind="dismissal") == {}  # an earlier choice, since changed
