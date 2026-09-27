"""Proof and waiting-for over HTTP: the tracking number (checked), proof files (private, outside the
Inbox, never read by AI), the Nachweis PDF, "Waiting for" and call notes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import helpers_proof
from helpers_docs import letter_pdf, photo
from ordnung import clock
from ordnung.drafts.proof import PROOF_SOURCE
from test_api_support import TODAY, Api, api_for

SENT_ON = "2026-09-10"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def _sent(api: Api, **extra: Any) -> tuple[str, helpers_proof.Gym]:
    gym = helpers_proof.gym(api.ctx)
    created = await api.client.post("/api/drafts", json={"kind": "cancellation", "contract_id": gym.contract})
    assert created.status_code == 201, created.text
    draft_id = str(created.json()["id"])
    sent = await api.client.post(
        f"/api/drafts/{draft_id}/sent", json={"channel": "registered_letter", "date": SENT_ON, **extra}
    )
    assert sent.status_code == 200, sent.text
    return draft_id, gym


async def _add(api: Api, draft_id: str, name: str, data: bytes, **form: str) -> Any:
    response = await api.client.post(
        f"/api/drafts/{draft_id}/proofs",
        files={"file": (name, data)},
        data={"kind": "posting_receipt", **form},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_marking_sent_with_a_tracking_number(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api, tracking_number="rt 123 456 785 de")
        assert (await api.client.get(f"/api/drafts/{draft_id}")).json()["tracking_number"] == "RT123456785DE"
        proof = (await api.client.get(f"/api/drafts/{draft_id}/proof")).json()
        assert proof["tracking"] == {
            "number": "RT123456785DE",
            "display": "RT 123 456 785 DE",
            "format": "s10",
            "checked": True,
            "note": None,
        }


async def test_a_mistyped_tracking_number_is_refused_with_the_reason(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        gym = helpers_proof.gym(api.ctx)
        draft = (
            await api.client.post("/api/drafts", json={"kind": "cancellation", "contract_id": gym.contract})
        ).json()
        refused = await api.client.post(
            f"/api/drafts/{draft['id']}/sent",
            json={"channel": "registered_letter", "date": SENT_ON, "tracking_number": "RT123456784DE"},
        )
        assert refused.status_code == 422 and "check digit" in refused.json()["detail"]
        assert (await api.client.get(f"/api/drafts/{draft['id']}")).json()["status"] == "draft"

        draft_id, _ = await _sent(api)
        bad = await api.client.put(
            f"/api/drafts/{draft_id}/tracking", json={"tracking_number": "RT12345678DE"}
        )
        assert bad.status_code == 422 and "two letters, nine digits" in bad.json()["detail"]
        good = await api.client.put(
            f"/api/drafts/{draft_id}/tracking", json={"tracking_number": "003404341234"}
        )
        assert good.status_code == 200 and good.json()["tracking"]["format"] == "domestic"
        cleared = await api.client.put(f"/api/drafts/{draft_id}/tracking", json={"tracking_number": None})
        assert cleared.json()["tracking"] is None
        too_long = await api.client.put(
            f"/api/drafts/{draft_id}/tracking", json={"tracking_number": "1" * 65}
        )
        assert too_long.status_code == 422


async def test_a_proof_upload_stays_private_and_out_of_the_inbox(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        calls_before = len(api.backend.calls)
        overview = await _add(
            api,
            draft_id,
            "einlieferungsbeleg.jpg",
            photo("JPEG", size=(300, 400)),
            on_date=SENT_ON,
            note="Filiale Mitte",
        )
        await api.read_all()
        assert len(api.backend.calls) == calls_before  # nothing about the proof reached a model
        (entry,) = overview["proofs"]
        assert entry["label"] == "Posting receipt" and entry["proof"]["note"] == "Filiale Mitte"
        document = entry["document"]
        assert (document["ai_private"], document["direction"], document["source"]) == (
            True,
            "outgoing",
            PROOF_SOURCE,
        )
        listed = (await api.client.get("/api/documents")).json()
        assert all(doc["id"] != document["id"] for doc in listed)
        assert all(
            doc["id"] != document["id"]
            for doc in (await api.client.get("/api/documents", params={"q": "einlieferungsbeleg"})).json()
        )
        # it opens like any file, from its letter
        assert (await api.client.get(f"/api/documents/{document['id']}")).status_code == 200
        assert (await api.client.get(f"/api/documents/{document['id']}/file")).status_code == 200


async def test_a_proof_upload_is_refused_like_any_bad_file(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        bad = await api.client.post(
            f"/api/drafts/{draft_id}/proofs",
            files={"file": ("a.zip", b"PK\x03\x04" + bytes(100))},
            data={"kind": "other"},
        )
        assert bad.status_code == 422 and "not supported" in bad.json()["detail"]
        future = await api.client.post(
            f"/api/drafts/{draft_id}/proofs",
            files={"file": ("a.jpg", photo("JPEG"))},
            data={"kind": "other", "on_date": "2027-01-01"},
        )
        assert future.status_code == 422 and "future" in future.json()["detail"]
        unknown = await api.client.post(
            f"/api/drafts/{draft_id}/proofs",
            files={"file": ("a.jpg", photo("JPEG"))},
            data={"kind": "selfie"},
        )
        assert unknown.status_code == 422
        assert (
            await api.client.post(
                "/api/drafts/drf_missing/proofs",
                files={"file": ("a.jpg", photo("JPEG"))},
                data={"kind": "other"},
            )
        ).status_code == 404


async def test_the_demo_takes_proof_files(data_dir: Path) -> None:
    """The zero-token demo refuses letters it can't read, but a proof is never read."""
    async with api_for(data_dir, demo=True) as api:
        draft_id, _ = await _sent(api)
        await _add(api, draft_id, "a.jpg", photo("JPEG"))


async def test_correcting_and_removing_a_proof(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        overview = await _add(api, draft_id, "a.pdf", letter_pdf(), on_date=SENT_ON)
        proof_id = overview["proofs"][0]["proof"]["id"]
        doc_id = overview["proofs"][0]["document"]["id"]
        patched = await api.client.patch(
            f"/api/drafts/{draft_id}/proofs/{proof_id}",
            json={"kind": "delivery_record", "on_date": "2026-09-12"},
        )
        assert patched.status_code == 200
        assert [e["kind"] for e in patched.json()["timeline"]][-1] == "delivered"
        cleared = await api.client.patch(f"/api/drafts/{draft_id}/proofs/{proof_id}", json={"on_date": None})
        assert cleared.json()["proofs"][0]["proof"]["on_date"] is None
        assert (
            await api.client.patch(f"/api/drafts/{draft_id}/proofs/{proof_id}", json={"colour": "red"})
        ).status_code == 422
        removed = await api.client.delete(f"/api/drafts/{draft_id}/proofs/{proof_id}")
        assert removed.status_code == 200 and removed.json()["proofs"] == []
        assert (await api.client.get(f"/api/documents/{doc_id}")).status_code == 404
        assert (await api.client.delete(f"/api/drafts/{draft_id}/proofs/{proof_id}")).status_code == 404


async def test_the_nachweis_pdf(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, gym = await _sent(api, tracking_number="RT123456785DE")
        await _add(api, draft_id, "a.jpg", photo("JPEG"), on_date=SENT_ON)
        response = await api.client.get(f"/api/drafts/{draft_id}/proof.pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"] == f'attachment; filename="nachweis-{draft_id}.pdf"'
        assert response.content.startswith(b"%PDF-")
        unsent = (
            await api.client.post("/api/drafts", json={"kind": "cancellation", "contract_id": gym.contract})
        ).json()
        refused = await api.client.get(f"/api/drafts/{unsent['id']}/proof.pdf")
        assert refused.status_code == 422 and "Mark the letter as sent first" in refused.json()["detail"]


async def test_deleting_a_letter_deletes_its_proof_files(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        overview = await _add(api, draft_id, "a.jpg", photo("JPEG"))
        doc_id = overview["proofs"][0]["document"]["id"]
        assert (await api.client.delete(f"/api/drafts/{draft_id}")).status_code == 204
        assert (await api.client.get(f"/api/documents/{doc_id}")).status_code == 404


async def test_waiting_for_and_call_notes(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, gym = await _sent(api)
        waiting = (await api.client.get("/api/waiting")).json()
        assert [(e["source"], e["status"], e["ref"]) for e in waiting] == [
            ("letter", "waiting", {"type": "draft", "id": draft_id})
        ]
        created = await api.client.post(
            "/api/calls",
            json={
                "party_id": gym.party,
                "called_on": "2026-09-20",
                "contact": "Frau Weber",
                "summary": "She said the refund is on its way.",
                "promise": "Refund of the September fee",
                "promise_due": "2026-10-05",
                "promise_amount": 29.9,
            },
        )
        assert created.status_code == 201, created.text
        call = created.json()
        assert call["promise_amount"] == 29.9 and call["promise_kept_on"] is None
        listed = (await api.client.get("/api/calls", params={"party_id": gym.party})).json()
        assert [c["id"] for c in listed] == [call["id"]]
        assert (await api.client.get("/api/calls", params={"case_id": gym.case})).json() == []
        entries = (await api.client.get("/api/waiting")).json()
        assert {e["source"] for e in entries} == {"letter", "call"}

        kept = await api.client.patch(f"/api/calls/{call['id']}", json={"kept": True})
        assert kept.status_code == 200 and kept.json()["promise_kept_on"] == TODAY
        assert {e["source"] for e in (await api.client.get("/api/waiting")).json()} == {"letter"}

        refused = await api.client.post("/api/calls", json={"called_on": "2026-09-20", "summary": "Hi"})
        assert refused.status_code == 422 and "Choose who you spoke to" in refused.json()["detail"]
        future = await api.client.post(
            "/api/calls", json={"party_id": gym.party, "called_on": "2026-12-01", "summary": "Hi"}
        )
        assert future.status_code == 422 and "future" in future.json()["detail"]
        assert (
            await api.client.post(
                "/api/calls", json={"party_id": gym.party, "called_on": "2026-09-20", "summary": ""}
            )
        ).status_code == 422

        assert (await api.client.delete(f"/api/calls/{call['id']}")).status_code == 204
        assert (await api.client.delete(f"/api/calls/{call['id']}")).status_code == 404
        assert (await api.client.patch(f"/api/calls/{call['id']}", json={"kept": True})).status_code == 404
