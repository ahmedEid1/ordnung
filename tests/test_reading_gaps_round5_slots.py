"""The round-5 limits review, RL-T3 / FA-2: code's to-dos for dates a reading left out are slotted by date and kind, so
a to-do the person dealt with never passes its status to another date when a later reading files another set, and a
paid one moves onto the new reading's payment for that day. Invented letters only."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import Letter, Router
from ordnung import clock
from test_api_support import api_for

MARKER = "Rechnung Wasser 2026 Probe"
PAY = "Bitte überweisen Sie den Betrag von 85,00 EUR bis zum 09.10.2026."
SEND = "Bitte reichen Sie den Zählerstand bis zum 23.10.2026 ein."
LETTER = Letter(
    marker=MARKER,
    pages=(
        (
            "Stadtwerke Beispielhausen GmbH, Werkstraße 1, 12345 Beispielhausen",
            "Frau Mara Probe",
            "Probeweg 2",
            "12345 Beispielhausen",
            "Datum: 21.09.2026",
            MARKER,
            "Sehr geehrte Frau Probe,",
            PAY,
            SEND,
        ),
    ),
    payload={
        "kind": "invoice",
        "title": "Water bill",
        "summary": "s",
        "explanation": "e",
        "sender": {"name": "Stadtwerke Beispielhausen GmbH", "kind": "utility"},
        "document_date": "2026-09-21",
    },
)


@pytest.fixture
def pinned_today() -> Iterator[None]:
    clock.set_today("2026-09-25")
    yield
    clock.set_today(None)


async def test_a_dealt_with_dropped_date_never_passes_its_status_to_another(
    data_dir: Path, pinned_today: None
) -> None:
    router = Router(letters=(LETTER,))
    async with api_for(data_dir, router=router) as api:
        body = await api.upload((f"{MARKER}.pdf", LETTER.pdf()))
        await api.read_all()
        doc_id = str(body["documents"][0]["id"])
        first = sorted(api.ctx.store.list_items(doc_id=doc_id), key=lambda i: i.slot_key)
        pay = next(i for i in first if i.due_date == "2026-10-09")
        assert (await api.client.patch(f"/api/items/{pay.id}", json={"status": "done"})).status_code == 200
        router.payloads[MARKER]["items"] = [
            {
                "kind": "payment",
                "title": "Pay the water bill",
                "quote": PAY,
                "amount": 85.0,
                "date": {"type": "fixed", "date": "2026-10-09", "nature": "payment"},
            }
        ]
        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        after = sorted(api.ctx.store.list_items(doc_id=doc_id), key=lambda i: i.slot_key)
        send = next(i for i in after if i.due_date == "2026-10-23")
        assert send.status == "open", "the send-by date the person never dealt with shows as done"
        pay2 = [i for i in after if i.due_date == "2026-10-09"]
        assert all(i.status == "done" for i in pay2), "the paid bill shows open again"
