"""Letters over HTTP: compose an objection, edit it (checks re-run), the PDF, "I sent it" with its
follow-up to-do, refusals and deleting."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER
from ordnung import clock
from test_api_support import TODAY, Api, api_for

PROFILE = {"name": "Sam Rivera", "address": "Musterweg 1\n12345 Musterstadt", "email": "sam@example.org"}


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def _letter(api: Api, data: bytes) -> str:
    body = await api.upload(("letter.pdf", data))
    await api.read_all()
    return str(body["documents"][0]["id"])


async def test_objection_draft_flow(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        assert (await api.client.put("/api/profile", json=PROFILE)).status_code == 200
        doc_id = await _letter(api, TAX_LETTER.pdf())

        created = await api.client.post("/api/drafts", json={"kind": "objection", "doc_id": doc_id})
        assert created.status_code == 201, created.text
        draft = created.json()
        assert draft["kind"] == "objection" and draft["status"] == "draft"
        assert "Einspruch" in draft["body"] and "Sam Rivera" in draft["sender_block"]
        assert draft["body_translation"] and draft["checks"]
        assert draft["send_guidance"]["channels"]
        assert [call.purpose for call in api.backend.calls][-1] == "draft"

        listed = (await api.client.get("/api/drafts")).json()
        assert [entry["id"] for entry in listed] == [draft["id"]]
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert [entry["id"] for entry in detail["drafts"]] == [draft["id"]]

        edited = await api.client.patch(
            f"/api/drafts/{draft['id']}", json={"body": draft["body"] + "\n\n[Ihre Begründung]"}
        )
        assert edited.status_code == 200
        checks = {check["id"]: check["ok"] for check in edited.json()["checks"]}
        assert checks["no_placeholders"] is False

        pdf = await api.client.get(f"/api/drafts/{draft['id']}/pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content.startswith(b"%PDF-") and len(pdf.content) > 1000

        sent = await api.client.post(
            f"/api/drafts/{draft['id']}/sent", json={"channel": "letter", "date": TODAY}
        )
        assert sent.status_code == 200
        assert (sent.json()["status"], sent.json()["sent_channel"]) == ("sent", "letter")
        followups = [
            item for item in (await api.client.get("/api/items")).json() if item["origin"] == "draft"
        ]
        assert len(followups) == 1 and followups[0]["due_date"] == "2026-10-16"

        assert (await api.client.delete(f"/api/drafts/{draft['id']}")).status_code == 204
        assert (await api.client.get(f"/api/drafts/{draft['id']}")).status_code == 404
        assert (await api.client.get(f"/api/drafts/{draft['id']}/pdf")).status_code == 404


async def test_letters_that_cannot_be_drafted_or_sent(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        invoice = await _letter(api, INVOICE_LETTER.pdf())
        refused = await api.client.post("/api/drafts", json={"kind": "objection", "doc_id": invoice})
        assert refused.status_code == 422
        assert isinstance(refused.json()["detail"], str)
        assert (await api.client.post("/api/drafts", json={"kind": "poem"})).status_code == 422
        missing = await api.client.post("/api/drafts", json={"kind": "general_reply", "doc_id": "doc_gone"})
        assert missing.status_code == 422

        reply = (
            await api.client.post("/api/drafts", json={"kind": "general_reply", "doc_id": invoice})
        ).json()
        url = f"/api/drafts/{reply['id']}/sent"
        assert (await api.client.post(url, json={"channel": "pigeon", "date": TODAY})).status_code == 422
        assert (
            await api.client.post(url, json={"channel": "email", "date": "2027-01-01"})
        ).status_code == 422
        assert (await api.client.post(url, json={"channel": "email", "date": "soon"})).status_code == 422
        assert (
            await api.client.patch(f"/api/drafts/{reply['id']}", json={"status": "sent"})
        ).status_code == 422
