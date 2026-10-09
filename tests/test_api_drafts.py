"""Letters over HTTP: compose an objection, edit it (checks re-run), the PDF, "I sent it" with its
follow-up to-do, a letter in someone else's name, refusals and deleting."""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pdfplumber
import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER
from ordnung import clock
from ordnung.ingest.watcher import is_own_file
from ordnung.llm.base import LLMRequest, LLMResponse
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
        assert is_own_file(api.ctx.store, pdf.content)  # saved into the watched folder: not a letter received
        preview = await api.client.get(f"/api/drafts/{draft['id']}/preview.png")
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/png"
        assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")

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
        assert (await api.client.get(f"/api/drafts/{draft['id']}/preview.png")).status_code == 404


async def test_a_letter_can_be_asked_for_in_a_name_of_one_short_line(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        assert (await api.client.put("/api/profile", json=PROFILE)).status_code == 200
        invoice = await _letter(api, INVOICE_LETTER.pdf())
        ask = {"kind": "general_reply", "doc_id": invoice}
        too_long = await api.client.post("/api/drafts", json={**ask, "sender_name": "A" * 121})
        assert too_long.status_code == 422
        yours = await api.client.post("/api/drafts", json={**ask, "sender_name": "Sam\nRivera"})
        assert yours.status_code == 201, yours.text
        assert yours.json()["sender_block"].startswith("Sam Rivera\n")


def _pdf_text(data: bytes) -> tuple[str, dict[str, Any]]:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages), dict(pdf.metadata)


ALEX = "Alex Rivera"
SIGNER_NOTE = "This letter goes out in the name of Alex Rivera, so Alex Rivera signs it."


async def test_a_letter_in_someone_elses_name(data_dir: Path) -> None:
    """The name the person chose goes into the sender block, the signature, the PDF's author and, once
    sent, the Nachweis — and stays as it went out when the profile changes later."""
    async with api_for(data_dir) as api:
        profile = {**PROFILE, "phone": "+49 170 1234567"}
        assert (await api.client.put("/api/profile", json=profile)).status_code == 200
        doc_id = await _letter(api, TAX_LETTER.pdf())
        created = await api.client.post(
            "/api/drafts", json={"kind": "objection", "doc_id": doc_id, "sender_name": f"  {ALEX} "}
        )
        assert created.status_code == 201, created.text
        draft = created.json()
        assert draft["sender_block"] == "Alex Rivera\nMusterweg 1\n12345 Musterstadt"
        assert SIGNER_NOTE in draft["notes_for_user"]
        assert draft["notes_for_user"][-1].startswith("Based on the law as of")

        text, metadata = _pdf_text((await api.client.get(f"/api/drafts/{draft['id']}/pdf")).content)
        assert ALEX in text.split("Mit freundlichen Grüßen", 1)[1]
        assert "Sam Rivera" not in text and metadata["Author"] == ALEX
        assert "sam@example.org" in text  # the contact lines stay the person's

        sent = await api.client.post(
            f"/api/drafts/{draft['id']}/sent", json={"channel": "letter", "date": TODAY}
        )
        assert sent.status_code == 200, sent.text
        proof, _ = _pdf_text((await api.client.get(f"/api/drafts/{draft['id']}/proof.pdf")).content)
        assert ALEX in proof and "Sam Rivera" not in proof
        assert "Das Schreiben wie versandt" in proof

        changed = {**profile, "name": "Sam R.", "phone": "+49 30 999999", "email": "new@example.org"}
        assert (await api.client.put("/api/profile", json=changed)).status_code == 200
        text, metadata = _pdf_text((await api.client.get(f"/api/drafts/{draft['id']}/pdf")).content)
        assert ALEX in text and metadata["Author"] == ALEX
        assert "sam@example.org" in text and "1234567" in text
        assert "new@example.org" not in text and "999999" not in text


async def test_an_unsent_letter_in_someone_elses_name_keeps_the_contact_lines_current(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        assert (await api.client.put("/api/profile", json=PROFILE)).status_code == 200
        invoice = await _letter(api, INVOICE_LETTER.pdf())
        draft = (
            await api.client.post(
                "/api/drafts", json={"kind": "general_reply", "doc_id": invoice, "sender_name": ALEX}
            )
        ).json()
        changed = {**PROFILE, "name": "Sam R.", "email": "new@example.org"}
        assert (await api.client.put("/api/profile", json=changed)).status_code == 200
        text, metadata = _pdf_text((await api.client.get(f"/api/drafts/{draft['id']}/pdf")).content)
        assert ALEX in text.split("Mit freundlichen Grüßen", 1)[1] and metadata["Author"] == ALEX
        assert "new@example.org" in text and "sam@example.org" not in text


async def test_the_name_a_letter_goes_out_in_never_reaches_claude(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The draft request — so its cache key and every recorded answer — is the same with and without a
    sender name, and holds neither that name nor the profile's: recordings replay unchanged."""
    async with api_for(data_dir) as api:
        assert (await api.client.put("/api/profile", json=PROFILE)).status_code == 200
        doc_id = await _letter(api, TAX_LETTER.pdf())
        requests: list[LLMRequest] = []
        complete = api.ctx.llm.complete

        async def spy(req: LLMRequest, **kwargs: Any) -> LLMResponse:
            requests.append(req)
            return await complete(req, **kwargs)

        monkeypatch.setattr(api.ctx.llm, "complete", spy)
        ask = {"kind": "objection", "doc_id": doc_id, "instructions": "Bitte schnell bearbeiten"}
        yours = await api.client.post("/api/drafts", json=ask)
        theirs = await api.client.post("/api/drafts", json={**ask, "sender_name": ALEX})
        assert yours.status_code == theirs.status_code == 201
        assert theirs.json()["sender_block"].startswith(ALEX)
        mine, other = (req for req in requests if req.purpose == "draft")
        assert (mine.cache_key, mine.prompt, mine.system) == (other.cache_key, other.prompt, other.system)
        for req in (mine, other):
            assert ALEX not in req.prompt and ALEX not in req.system
            assert "Sam Rivera" not in req.prompt and "Sam Rivera" not in req.system


@pytest.mark.parametrize("name", ["", "   ", "sam  RIVERA", "Sam\nRivera"])
async def test_a_sender_name_that_is_yours_changes_nothing(data_dir: Path, name: str) -> None:
    async with api_for(data_dir) as api:
        assert (await api.client.put("/api/profile", json=PROFILE)).status_code == 200
        doc_id = await _letter(api, TAX_LETTER.pdf())
        ask = {"kind": "objection", "doc_id": doc_id}
        plain = (await api.client.post("/api/drafts", json=ask)).json()
        named = await api.client.post("/api/drafts", json={**ask, "sender_name": name})
        assert named.status_code == 201, named.text
        unchanged = {"id", "created_at", "updated_at"}
        assert {k: v for k, v in named.json().items() if k not in unchanged} == {
            k: v for k, v in plain.items() if k not in unchanged
        }
        assert api.ctx.store.get_sent_signer(named.json()["id"]) is None


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
