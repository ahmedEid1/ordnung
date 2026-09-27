"""GiroCodes over HTTP: the document detail carries one per payment, a photo letter waits for the
person to compare it with the paper (``POST /api/items/{id}/girocode/confirm``), and a confirmation
never covers other values, another to-do or a refused code."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import DUNNING_LETTER, INVOICE_LETTER, TELECOM_IBAN, record_events
from helpers_docs import photo
from ordnung import clock
from test_api_support import FINE_LETTER, TODAY, Api, ApiRouter, api_for

INVOICE_PAYLOAD = f"BCD\n002\n1\nSCT\n\nMuster Telecom GmbH\n{TELECOM_IBAN}\nEUR49.99\n\n\nR-2026-0815"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def _read(api: Api, name: str, data: bytes) -> dict[str, Any]:
    body = await api.upload((name, data))
    await api.read_all()
    detail: dict[str, Any] = (await api.client.get(f"/api/documents/{body['documents'][0]['id']}")).json()
    return detail


def _payment(detail: dict[str, Any]) -> dict[str, Any]:
    (item,) = [item for item in detail["items"] if item["kind"] == "payment"]
    return dict(item)


async def test_a_text_letter_carries_its_code_in_the_detail(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        detail = await _read(api, "rechnung.pdf", INVOICE_LETTER.pdf())
        item = _payment(detail)
        assert detail["girocodes"] == [
            {"status": "ready", "item_id": item["id"], "payload": INVOICE_PAYLOAD, "checked": False}
        ]
        # UTF-8 bytes as the QR code stores them
        assert len(INVOICE_PAYLOAD.encode()) == 80


async def test_a_photo_letter_is_compared_with_the_paper_before_it_gets_a_code(data_dir: Path) -> None:
    router = ApiRouter()
    router.transcript = INVOICE_LETTER.transcript()
    async with api_for(data_dir, router=router) as api:
        detail = await _read(api, "rechnung.jpg", photo("JPEG"))
        item = _payment(detail)
        (code,) = detail["girocodes"]
        assert code["status"] == "blocked" and code["reason"] == "check_letter"
        assert code["to_check"] == ["amount", "iban", "reference"]
        assert code["message"] == (
            "No code yet: the amount, the IBAN and the reference were read by AI from a photo. Compare "
            "them with the paper letter, then confirm."
        )
        values = code["values"]
        assert values == {
            "payee": "Muster Telecom GmbH",
            "iban": TELECOM_IBAN,
            "reference": "R-2026-0815",
            "amount": 49.99,
        }
        url = f"/api/items/{item['id']}/girocode/confirm"

        changed = await api.client.post(url, json={**values, "iban": TELECOM_IBAN[:-2] + "00"})
        assert changed.status_code == 409
        assert (
            changed.json()["detail"]
            == "The payment details changed since you looked at them. Please compare them again."
        )
        assert (await api.client.post(url, json={**values, "bic": "MUSTDEXX"})).status_code == 422
        assert (await api.client.post("/api/items/itm_nope/girocode/confirm", json=values)).status_code == 404

        events = record_events(api.ctx.bus)
        confirmed = await api.client.post(url, json=values)
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json() == {
            "status": "ready",
            "item_id": item["id"],
            "payload": INVOICE_PAYLOAD,
            "checked": True,
        }
        assert ("document.updated", {"doc_id": detail["document"]["id"]}) in events

        again = (await api.client.get(f"/api/documents/{detail['document']['id']}")).json()
        assert again["girocodes"] == [confirmed.json()]
        activity = (await api.client.get("/api/activity")).json()
        assert activity[0]["kind"] == "payment.checked" and activity[0]["ref_id"] == item["id"]

        twice = await api.client.post(url, json=values)
        assert (
            twice.status_code == 409
            and twice.json()["detail"] == "There is nothing to compare for this payment."
        )

        # deleting the letter deletes what the person compared (docs/privacy.md)
        deleted = await api.client.delete(
            f"/api/documents/{detail['document']['id']}", params={"purge": "true"}
        )
        assert deleted.status_code == 200, deleted.text
        kinds = [entry["kind"] for entry in (await api.client.get("/api/activity")).json()]
        assert "payment.checked" not in kinds


async def test_a_reminder_takes_the_code_over_from_its_invoice(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        invoice = await _read(api, "rechnung.pdf", INVOICE_LETTER.pdf())
        reminder = await _read(api, "mahnung.pdf", DUNNING_LETTER.pdf())
        invoice = (await api.client.get(f"/api/documents/{invoice['document']['id']}")).json()
        (old,) = invoice["girocodes"]
        assert old["status"] == "blocked" and old["reason"] == "replaced"
        (new,) = reminder["girocodes"]
        assert new["status"] == "ready" and "\nEUR54.99\n" in new["payload"]
        refused = await api.client.post(
            f"/api/items/{old['item_id']}/girocode/confirm",
            json={
                "payee": "Muster Telecom GmbH",
                "iban": TELECOM_IBAN,
                "reference": "R-2026-0815",
                "amount": 49.99,
            },
        )
        assert refused.status_code == 409 and refused.json()["detail"].startswith(
            "No code: the payment reminder"
        )


async def test_a_letter_with_hidden_text_never_gets_a_code(data_dir: Path) -> None:
    """The fine's PDF carries invisible text: a scam sign, whatever else the letter lacks."""
    async with api_for(data_dir) as api:
        detail = await _read(api, "verwarnung.pdf", FINE_LETTER.pdf())
        assert detail["document"]["hidden_text"] is True
        (code,) = detail["girocodes"]
        assert code["reason"] == "scam"
        assert code["message"].startswith("No code: this letter shows signs of a scam.")
