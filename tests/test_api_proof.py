"""Proof and waiting-for over HTTP: the tracking number (checked), proof files (private, outside the
Inbox, never read by AI), the Nachweis PDF, "Waiting for" and call notes."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
import pytest

import helpers_proof
from helpers_docs import eml_bytes, letter_pdf, photo
from ordnung import clock
from ordnung.drafts.proof import PROOF_SOURCE
from ordnung.ingest.watcher import is_own_file
from ordnung.llm.base import ClaudeRateLimited
from test_api_support import TODAY, Api, ApiRouter, api_for

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


async def test_a_sent_e_mail_kept_as_proof_adds_no_letters_from_its_attachments(data_dir: Path) -> None:
    """Integration of proof with the one inbox: an ``.eml`` is read with its attachments as letters of
    their own, but a sent e-mail kept as proof is one private file — its attachment (the letter as sent)
    never becomes a letter received in the Inbox."""
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        before = {doc.id for doc in api.ctx.store.list_documents(include_deleted=True)}
        overview = await _add(api, draft_id, "gesendet.eml", eml_bytes(), kind="sent_email")
        await api.read_all()
        (entry,) = overview["proofs"]
        added = {doc.id for doc in api.ctx.store.list_documents(include_deleted=True)} - before
        assert added == {entry["document"]["id"]}
        assert api.ctx.store.list_documents(source=f"email:{entry['document']['id']}") == []


async def test_marking_sent_with_a_tracking_number(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api, tracking_number="rt 123 456 785 de")
        assert (await api.client.get(f"/api/drafts/{draft_id}")).json()["tracking_number"] == "RT123456785DE"
        proof = (await api.client.get(f"/api/drafts/{draft_id}/proof")).json()
        assert proof["tracking"] == {
            "number": "RT123456785DE",
            "display": "RT\u00a0123\u00a0456\u00a0785\u00a0DE",  # never breaks inside the number
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
        noted = await api.client.patch(
            f"/api/drafts/{draft_id}/proofs/{proof_id}", json={"note": "Post office Hauptstr."}
        )
        assert noted.json()["proofs"][0]["proof"]["note"] == "Post office Hauptstr."
        # the form sends null for an emptied note: it goes (as in the demo), it isn't kept
        unnoted = await api.client.patch(
            f"/api/drafts/{draft_id}/proofs/{proof_id}",
            json={"kind": "delivery_record", "on_date": "2026-09-12", "note": None},
        )
        assert unnoted.status_code == 200 and unnoted.json()["proofs"][0]["proof"]["note"] is None
        assert all(event["detail"] is None for event in unnoted.json()["timeline"])
        blank = await api.client.patch(f"/api/drafts/{draft_id}/proofs/{proof_id}", json={"note": "x"})
        assert blank.json()["proofs"][0]["proof"]["note"] == "x"
        blank = await api.client.patch(f"/api/drafts/{draft_id}/proofs/{proof_id}", json={"note": " "})
        assert blank.json()["proofs"][0]["proof"]["note"] is None
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
        disposition = response.headers["content-disposition"]
        # a readable name (the letter's subject and sending day), UTF-8 with an ASCII fallback
        assert disposition.startswith('attachment; filename="Nachweis Kundigung des Vertrags ')
        assert "2026-09-10.pdf\"; filename*=UTF-8''Nachweis%20K%C3%BCndigung" in disposition
        assert response.content.startswith(b"%PDF-")
        # saved into the watched folder, Ordnung's own Nachweis is never added as a letter received
        assert is_own_file(api.ctx.store, response.content)
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


def _about(ideas: list[Any], draft_id: str) -> list[str]:
    return [
        idea["title"]
        for idea in ideas
        if (idea.get("action") or {}).get("target_id") == draft_id
        or any(ref["id"] == draft_id for ref in idea.get("refs", []))
    ]


async def test_deleting_a_letter_takes_its_ideas_with_it(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)  # registered, no number, no proof: "Keep the proof …"
        before = _about((await api.client.get("/api/suggestions")).json(), draft_id)
        assert any("Keep the proof of your cancellation" in title for title in before)
        assert (await api.client.delete(f"/api/drafts/{draft_id}")).status_code == 204
        assert _about((await api.client.get("/api/suggestions")).json(), draft_id) == []


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


# --------------------------------------------------------------------------------------------------
# review round 1: what the Nachweis states, privacy of known files, answers, sent letters stay as sent
# --------------------------------------------------------------------------------------------------


def _text(data: bytes) -> str:
    document = pdfium.PdfDocument(data)
    try:
        text = "\n".join(document[i].get_textpage().get_text_range() for i in range(len(document)))
    finally:
        document.close()
    return text.replace(" ", " ")


async def _nachweis(api: Api, draft_id: str) -> str:
    response = await api.client.get(f"/api/drafts/{draft_id}/proof.pdf")
    assert response.status_code == 200, response.text
    return _text(response.content)


async def test_a_proof_without_a_day_is_never_dated_by_its_upload(data_dir: Path) -> None:
    """Sent 10 Sep, receipt added without a day on the 25th: nowhere dated the 25th as if posted then."""
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        overview = await _add(api, draft_id, "beleg.jpg", photo("JPEG"))
        dated = [event for event in overview["timeline"] if event["date"] is not None]
        assert all(event["date"] != TODAY for event in dated)
        (undated,) = [event for event in overview["timeline"] if event["date"] is None]
        # the day it was added, in the person's time zone and never after today (the clock is pinned)
        added = min(overview["proofs"][0]["proof"]["created_at"][:10], TODAY)
        assert (undated["label"], undated["added_on"]) == ("Posting receipt", added)
        assert all(event["date"] != added for event in dated)
        text = await _nachweis(api, draft_id)
        shown = ".".join(reversed(added.split("-")))
        assert f"{shown} Einlieferungsbeleg" not in text
        assert "ohne Datum" in text and f"Tag nicht angegeben, hinzugefügt am {shown}" in text
        before, _, after = text.partition("Nachweise ohne Datum")
        assert "Einlieferungsbeleg" not in before.split("Verlauf")[1] and "Einlieferungsbeleg" in after


async def test_a_letter_in_the_same_thread_is_no_answer_in_the_nachweis(data_dir: Path) -> None:
    """An ordinary invoice after a registered cancellation: no "Antwort erhalten", the advice stays."""
    async with api_for(data_dir) as api:
        draft_id, gym = await _sent(api)
        invoice = helpers_proof.incoming(
            api.ctx,
            "invoice",
            kind="invoice",
            title="Beitragsrechnung Oktober",
            doc_date="2026-09-15",
            party_id=gym.party,
            case_id=gym.case,
        )
        overview = (await api.client.get(f"/api/drafts/{draft_id}/proof")).json()
        assert any("delivery record" in line for line in overview["missing"])
        (possible,) = [event for event in overview["timeline"] if event["kind"] == "possible_answer"]
        assert possible["ref"] == {"type": "document", "id": invoice}
        assert overview["waiting"]["status"] == "answered"  # shown as a possible answer to check
        text = await _nachweis(api, draft_id)
        assert "Antwort erhalten" not in text and "Beitragsrechnung" not in text

        # the person says it is the answer: now it is one, and the follow-up closes (with Undo)
        answered = await api.client.post(f"/api/drafts/{draft_id}/answered", json={"doc_id": invoice})
        assert answered.status_code == 200, answered.text
        assert answered.json()["missing"] == [
            line for line in overview["missing"] if "delivery record" not in line
        ]
        assert answered.json()["waiting"]["status"] == "closed"
        assert "Antwort erhalten: „Beitragsrechnung Oktober“" in await _nachweis(api, draft_id)
        assert all(entry["source"] != "letter" for entry in (await api.client.get("/api/waiting")).json())
        undone = await api.client.delete(f"/api/drafts/{draft_id}/answered")
        assert undone.json()["waiting"]["status"] == "answered"
        followup = (await api.client.get("/api/drafts")).json()
        assert all(draft["answered_on"] is None for draft in followup)


async def test_it_is_answered_without_a_letter(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        answered = await api.client.post(f"/api/drafts/{draft_id}/answered", json={})
        assert answered.json()["waiting"]["status"] == "closed"
        # the person's word, on the day they said so: never "answered" as if a letter showed it
        assert answered.json()["timeline"][-1] == {
            "date": TODAY,
            "kind": "answered",
            "label": "You marked it as answered",
            "detail": None,
            "ref": None,
            "added_on": None,
        }
        assert any("Auslieferungsbeleg" in line for line in answered.json()["missing"])
        text = await _nachweis(api, draft_id)
        assert "Als beantwortet vermerkt (Angabe des Absenders)" in text and "Beantwortet (laut" not in text
        gone = await api.client.post(f"/api/drafts/{draft_id}/answered", json={"doc_id": "doc_missing"})
        assert gone.status_code == 422 and "isn't in Ordnung" in gone.json()["detail"]


async def test_a_known_unread_file_becomes_private_when_added_as_proof(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        data = photo("JPEG", size=(333, 444))
        uploaded = await api.client.post("/api/documents", files={"files": ("receipt.jpg", data)})
        assert uploaded.status_code == 201
        assert uploaded.json()["documents"][0]["ai_private"] is False
        added = await _add(api, draft_id, "receipt.jpg", data)
        assert added["notice"] and "kept private from now on" in added["notice"]
        assert added["proofs"][0]["document"]["ai_private"] is True
        calls_before = len(api.backend.calls)
        await api.read_all()
        assert len(api.backend.calls) == calls_before  # the queued job read it privately
        logged = [entry.message for entry in api.ctx.store.list_activity(20) if entry.kind == "draft.proof"]
        assert logged and "now kept private, not sent to AI" in logged[0]


async def test_a_known_file_ai_already_read_is_never_called_private(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        data = letter_pdf()
        await api.client.post("/api/documents", files={"files": ("letter.pdf", data)})
        await api.read_all()  # read by the model
        added = await _add(api, draft_id, "letter.pdf", data, kind="other")
        assert added["notice"] and "given to AI to read" in added["notice"]
        assert added["proofs"][0]["document"]["ai_private"] is False
        logged = [entry.message for entry in api.ctx.store.list_activity(20) if entry.kind == "draft.proof"]
        assert logged and "not sent to AI" not in logged[0] and "given to AI" in logged[0]


def _logged_proof(api: Api) -> str:
    return next(entry.message for entry in api.ctx.store.list_activity(20) if entry.kind == "draft.proof")


async def test_a_file_whose_reading_failed_after_the_model_had_it_is_never_called_unread(
    data_dir: Path,
) -> None:
    # the model transcribes the photo but finds no text: the reading fails, yet the photo went to AI
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        data = photo("JPEG", size=(336, 446))
        uploaded = (await api.client.post("/api/documents", files={"files": ("receipt.jpg", data)})).json()
        await api.read_all()
        doc_id = uploaded["documents"][0]["id"]
        failed = api.ctx.store.get_document(doc_id)
        assert failed is not None and failed.status == "failed" and failed.ai_processed_at is None
        added = await _add(api, draft_id, "receipt.jpg", data)
        assert added["notice"] and "given to AI to read" in added["notice"]
        assert "not yet read" not in added["notice"]
        assert added["proofs"][0]["document"]["ai_private"] is False
        assert "not sent to AI" not in _logged_proof(api)


async def test_a_file_paused_by_a_rate_limit_after_transcription_is_never_called_unread(
    data_dir: Path,
) -> None:
    router = ApiRouter()
    router.transcript = "Einlieferungsbeleg Deutsche Post RT 123 456 785 DE"
    router.errors["extract"] = lambda: ClaudeRateLimited("Usage limit reached", reset_at="3pm")
    async with api_for(data_dir, router=router) as api:
        draft_id, _ = await _sent(api)
        data = photo("JPEG", size=(337, 447))
        uploaded = (await api.client.post("/api/documents", files={"files": ("receipt.jpg", data)})).json()
        await api.read_all()
        doc_id = uploaded["documents"][0]["id"]
        paused = api.ctx.store.get_document(doc_id)
        assert paused is not None and paused.ai_processed_at is None
        assert [call.purpose for call in api.backend.calls if doc_id in call.doc_ids][:1] == ["transcribe"]
        added = await _add(api, draft_id, "receipt.jpg", data)
        assert added["notice"] and "given to AI to read" in added["notice"]
        assert added["proofs"][0]["document"]["ai_private"] is False
        assert "not sent to AI" not in _logged_proof(api)


async def test_a_letter_marked_private_after_ai_read_it_is_never_called_private(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        data = letter_pdf()
        uploaded = (await api.client.post("/api/documents", files={"files": ("letter.pdf", data)})).json()
        await api.read_all()
        doc_id = uploaded["documents"][0]["id"]
        patched = await api.client.patch(f"/api/documents/{doc_id}", json={"ai_private": True})
        assert patched.status_code == 200, patched.text
        added = await _add(api, draft_id, "letter.pdf", data, kind="other")
        assert added["notice"] and "given to AI to read" in added["notice"]
        assert "not sent to AI" not in _logged_proof(api)


async def test_a_proof_file_uploaded_to_the_inbox_says_where_it_is(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        data = photo("JPEG", size=(335, 445))
        await _add(api, draft_id, "receipt.jpg", data)
        again = await api.client.post("/api/documents", files={"files": ("receipt.jpg", data)})
        assert again.status_code == 422
        assert "already in Ordnung as proof of your letter" in again.json()["detail"]
        # the same file twice on one letter is refused, not listed twice
        twice = await api.client.post(
            f"/api/drafts/{draft_id}/proofs", files={"file": ("receipt.jpg", data)}, data={"kind": "other"}
        )
        assert twice.status_code == 422 and "already a proof of this letter" in twice.json()["detail"]


async def test_the_inbox_pages_in_sql_without_proof_files(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        for size in ((301, 401), (302, 402)):
            await _add(api, draft_id, "p.jpg", photo("JPEG", size=size), kind="other")
        for label in ("one", "two", "three"):
            helpers_proof.incoming(api.ctx, label, title=label, doc_date="2026-09-0" + str(len(label)))
        page = (await api.client.get("/api/documents", params={"limit": 2, "offset": 1})).json()
        # newest first (three; then two, one — added later first): the proof files never take a place
        assert [doc["title"] for doc in page] == ["two", "one"]
        assert (await api.client.get("/api/dashboard")).json()["stats"]["documents"] == 3


async def test_a_delivery_before_the_sending_is_refused_and_a_mismatch_said(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        early = await api.client.post(
            f"/api/drafts/{draft_id}/proofs",
            files={"file": ("d.jpg", photo("JPEG"))},
            data={"kind": "delivery_record", "on_date": "2026-09-09"},
        )
        assert early.status_code == 422 and "can't be before the letter was sent" in early.json()["detail"]
        overview = await _add(api, draft_id, "r.jpg", photo("JPEG", size=(310, 410)), on_date="2026-09-12")
        (conflict,) = overview["conflicts"]
        assert "Sat 12 Sep 2026" in conflict and "Thu 10 Sep 2026" in conflict
        proof_id = overview["proofs"][0]["proof"]["id"]
        moved = await api.client.patch(
            f"/api/drafts/{draft_id}/proofs/{proof_id}",
            json={"kind": "delivery_record", "on_date": "2026-09-01"},
        )
        assert moved.status_code == 422


async def test_the_sending_day_cant_move_past_a_recorded_delivery(data_dir: Path) -> None:
    """Changing how or when it was sent never makes the Nachweis show a delivery before the sending."""
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api, tracking_number="RT123456785DE")  # sent 10 Sep
        await _add(api, draft_id, "d.jpg", photo("JPEG"), kind="delivery_record", on_date="2026-09-12")
        later = await api.client.post(
            f"/api/drafts/{draft_id}/sent", json={"channel": "registered_letter", "date": "2026-09-14"}
        )
        assert later.status_code == 422
        assert "delivered on Sat 12 Sep 2026" in later.json()["detail"]
        draft = (await api.client.get(f"/api/drafts/{draft_id}")).json()
        assert draft["sent_at"].startswith(SENT_ON)
        same_day = await api.client.post(
            f"/api/drafts/{draft_id}/sent", json={"channel": "registered_letter", "date": "2026-09-12"}
        )
        assert same_day.status_code == 200
        assert (await api.client.get(f"/api/drafts/{draft_id}/proof")).json()["conflicts"] == []


async def test_emptying_the_number_when_changing_how_it_was_sent_removes_it(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api, tracking_number="RT123456785DE")
        kept = await api.client.post(
            f"/api/drafts/{draft_id}/sent", json={"channel": "registered_letter", "date": SENT_ON}
        )
        assert kept.json()["tracking_number"] == "RT123456785DE"  # not sent: the number stays
        emptied = await api.client.post(
            f"/api/drafts/{draft_id}/sent",
            json={"channel": "registered_letter", "date": SENT_ON, "tracking_number": ""},
        )
        assert emptied.status_code == 200 and emptied.json()["tracking_number"] is None
        assert (await api.client.get(f"/api/drafts/{draft_id}/proof")).json()["tracking"] is None


async def test_an_einschreiben_bought_online_is_recorded_with_its_stamps_number(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api, tracking_number="A0 0123 45D6 0000 123C EC")
        overview = (await api.client.get(f"/api/drafts/{draft_id}/proof")).json()
        assert overview["tracking"]["format"] == "online_stamp" and not overview["tracking"]["checked"]
        assert not any("photo of the posting receipt" in line for line in overview["missing"])
        assert any("printout or screenshot of the online stamp" in line for line in overview["missing"])
        text = await _nachweis(api, draft_id)
        assert "A0 0123 45D6 0000 123C EC" in text.replace("\u00a0", " ") and "Prüfziffer" not in text


async def test_a_sent_letter_stays_as_it_went_out(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api, tracking_number="RT123456785DE")
        edited = await api.client.patch(f"/api/drafts/{draft_id}", json={"body": "EDITED AFTER SENDING"})
        assert edited.status_code == 409 and "sent" in edited.json()["detail"]
        reopened = await api.client.patch(f"/api/drafts/{draft_id}", json={"status": "final"})
        assert reopened.status_code == 409
        profile = (await api.client.get("/api/profile")).json()
        changed = await api.client.put(
            "/api/profile", json={**profile, "name": "Someone Else", "phone": "+49 30 999999"}
        )
        assert changed.status_code == 200, changed.text
        text = await _nachweis(api, draft_id)
        assert "Someone Else" not in text and "999999" not in text and "Sam Rivera" in text
        assert "Das Schreiben wie versandt" in text
        letter = _text((await api.client.get(f"/api/drafts/{draft_id}/pdf")).content)
        assert "Sam Rivera" in letter and "Someone Else" not in letter


@pytest.mark.parametrize(
    ("channel", "caption"),
    [
        ("online_button", "nicht als Brief versandt (Kündigungsbutton)"),
        ("portal", "nicht als Brief versandt (Online-Portal)"),
        ("email", "per E-Mail versandt"),
    ],
)
async def test_a_letter_that_went_out_as_text_is_not_called_the_letter_as_sent(
    data_dir: Path, channel: str, caption: str
) -> None:
    async with api_for(data_dir) as api:
        gym = helpers_proof.gym(api.ctx)
        draft_id = (
            await api.client.post("/api/drafts", json={"kind": "cancellation", "contract_id": gym.contract})
        ).json()["id"]
        await api.client.post(f"/api/drafts/{draft_id}/sent", json={"channel": channel, "date": SENT_ON})
        text = await _nachweis(api, draft_id)
        assert caption in text and "Das Schreiben wie versandt" not in text


async def test_a_letter_sent_before_its_sender_was_kept_says_so(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        with api.ctx.store.tx() as conn:
            conn.execute("UPDATE drafts SET sent_profile = NULL WHERE id = ?", (draft_id,))
        assert "Das Schreiben, wie in Ordnung gespeichert" in await _nachweis(api, draft_id)


async def test_marking_again_with_another_channel_drops_the_tracking_number(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api, tracking_number="RT123456785DE")
        again = await api.client.post(
            f"/api/drafts/{draft_id}/sent", json={"channel": "email", "date": SENT_ON}
        )
        assert again.status_code == 200 and again.json()["tracking_number"] is None
        overview = (await api.client.get(f"/api/drafts/{draft_id}/proof")).json()
        assert overview["tracking"] is None
        assert all("Tracking number" not in event["label"] for event in overview["timeline"])
        refused = await api.client.put(
            f"/api/drafts/{draft_id}/tracking", json={"tracking_number": "RT123456785DE"}
        )
        assert refused.status_code == 422 and "Only a registered letter" in refused.json()["detail"]
        plain = await api.client.post(
            f"/api/drafts/{draft_id}/sent",
            json={"channel": "letter", "date": SENT_ON, "tracking_number": "RT123456785DE"},
        )
        assert plain.status_code == 422


async def test_deleting_a_letter_can_keep_its_proof_files(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        overview = await _add(api, draft_id, "a.jpg", photo("JPEG"))
        doc_id = overview["proofs"][0]["document"]["id"]
        deleted = await api.client.delete(f"/api/drafts/{draft_id}", params={"keep_proof_files": True})
        assert deleted.status_code == 204
        kept = (await api.client.get(f"/api/documents/{doc_id}")).json()["document"]
        assert (kept["source"], kept["ai_private"], kept["direction"]) == ("upload", True, "outgoing")
        assert doc_id in {doc["id"] for doc in (await api.client.get("/api/documents")).json()}


async def test_a_proof_file_knows_its_letter(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        draft_id, _ = await _sent(api)
        overview = await _add(api, draft_id, "a.jpg", photo("JPEG"))
        detail = (await api.client.get(f"/api/documents/{overview['proofs'][0]['document']['id']}")).json()
        (link,) = detail["proof_of"]
        assert (link["draft_id"], link["kind"]) == (draft_id, "posting_receipt")
        assert link["subject"].startswith("Kündigung")


async def test_a_promised_amount_has_an_upper_bound(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        gym = helpers_proof.gym(api.ctx)
        base = {"party_id": gym.party, "called_on": "2026-09-20", "summary": "Call", "promise": "Refund"}
        assert (
            await api.client.post("/api/calls", json={**base, "promise_amount": 1e308})
        ).status_code == 422
        assert (
            await api.client.post("/api/calls", json={**base, "promise_amount": 1_000_000})
        ).status_code == 201
