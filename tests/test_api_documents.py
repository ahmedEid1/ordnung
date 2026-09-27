"""Letters over HTTP: upload → reading with the FakeBackend → Today, detail shapes, files, edits,
the confirmed arrival date recomputing to-dos, reprocess, trash and purge, and error mapping."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI

from fixtures_llm import INVOICE_LETTER, TAX_LETTER
from helpers_docs import photo
from ordnung import clock
from ordnung.llm.base import ClaudeAuthError, ClaudeRateLimited
from ordnung.models import DocumentDetail
from test_api_support import FINE_LETTER, TODAY, Api, api_for, lifespan

TEXT_LETTER = (
    "Liebe Sam,\n\nhier ist die Einladung zum Sommerfest am 12.10.2026.\n\nViele Grüße\nAlex\n".encode()
)


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def _read_letter(api: Api, data: bytes, name: str = "letter.pdf") -> str:
    body = await api.upload((name, data))
    await api.read_all()
    return str(body["documents"][0]["id"])


# --------------------------------------------------------------------------------------------------
# upload → reading → Today
# --------------------------------------------------------------------------------------------------


async def test_upload_is_read_and_shows_up_on_today(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        body = await api.upload(("bescheid.pdf", TAX_LETTER.pdf()))
        assert body["duplicates"] == [] and body["errors"] == []
        (document,) = body["documents"]
        assert document["status"] == "queued" and document["filename"] == "bescheid.pdf"
        (job,) = body["jobs"]
        assert job["doc_id"] == document["id"] and job["kind"] == "ingest"

        assert await api.read_all() == 1
        detail = (await api.client.get(f"/api/documents/{document['id']}")).json()
        assert detail["document"]["status"] == "processed"
        assert detail["document"]["title"] == "Income tax assessment 2025"
        item_ids = {item["id"] for item in detail["items"]}
        assert {item["kind"] for item in detail["items"]} == {"deadline", "payment"}

        dashboard = (await api.client.get("/api/dashboard")).json()
        shown = {item["id"] for item in dashboard["attention"] + dashboard["upcoming"]}
        assert item_ids <= shown
        assert dashboard["today"] == TODAY
        assert dashboard["stats"]["documents"] == 1 and dashboard["stats"]["open_items"] == 2
        assert [doc["id"] for doc in dashboard["recent_documents"]] == [document["id"]]
        assert [doc["id"] for doc in (await api.client.get("/api/documents")).json()] == [document["id"]]
        found = (await api.client.get("/api/documents", params={"q": "Einkommensteuer"})).json()
        assert [doc["id"] for doc in found] == [document["id"]]


async def test_the_running_worker_reads_uploads_by_itself(data_dir: Path) -> None:
    async with api_for(data_dir) as api, lifespan(api.app):
        body = await api.upload(("rechnung.pdf", INVOICE_LETTER.pdf()))
        doc_id = body["documents"][0]["id"]
        for _ in range(200):
            status = (await api.client.get(f"/api/documents/{doc_id}")).json()["document"]["status"]
            if status in ("processed", "needs_review", "failed"):
                break
            await asyncio.sleep(0.05)
        assert status == "processed"


async def test_duplicates_rejections_and_partial_uploads(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await _read_letter(api, TAX_LETTER.pdf())
        again = await api.upload(("copy.pdf", TAX_LETTER.pdf()))
        assert again["documents"] == [] and again["jobs"] == []
        assert again["duplicates"] == [doc_id]

        rejected = await api.client.post(
            "/api/documents", files=[("files", ("x.bin", b"\x00\x01\x02binary"))]
        )
        assert rejected.status_code == 422
        assert "x.bin" in rejected.json()["detail"] and "not supported" in rejected.json()["detail"]

        mixed = await api.upload(("x.bin", b"\x00\x01\x02binary"), ("rechnung.pdf", INVOICE_LETTER.pdf()))
        assert len(mixed["documents"]) == 1
        assert mixed["errors"][0]["filename"] == "x.bin"

        nothing = await api.client.post("/api/documents", data={"combine": "false"})
        assert nothing.status_code == 422


async def test_combine_makes_one_letter_of_the_photos(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        body = await api.upload(
            ("page1.jpg", photo("JPEG")),
            ("page2.png", photo("PNG", size=(220, 110))),
            ("other.pdf", INVOICE_LETTER.pdf()),
            combine=True,
            private=True,
        )
        assert len(body["documents"]) == 2
        combined, other = body["documents"]
        assert combined["filename"] == "page1.pdf" and combined["pages"] == 2
        assert combined["mime"] == "application/pdf" and combined["ai_private"] is True
        assert other["filename"] == "other.pdf"
        await api.read_all()
        assert api.backend.calls == []  # private letters are never sent to a model


# --------------------------------------------------------------------------------------------------
# detail and files
# --------------------------------------------------------------------------------------------------


async def test_document_detail_and_files(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await _read_letter(api, TAX_LETTER.pdf())
        response = await api.client.get(f"/api/documents/{doc_id}")
        detail = DocumentDetail.model_validate(response.json())
        assert set(response.json()) == set(DocumentDetail.model_fields)
        assert [(page.page, page.text_source) for page in detail.pages] == [(1, "text"), (2, "text")]
        assert detail.party is not None and detail.party.name == "Finanzamt Musterstadt"
        assert detail.case is not None and detail.document.case_id == detail.case.id
        assert detail.related == [] and detail.drafts == []
        assert all(item.doc_id == doc_id for item in detail.items)

        original = await api.client.get(f"/api/documents/{doc_id}/file")
        assert original.status_code == 200
        assert original.headers["content-type"] == "application/pdf"
        assert original.headers["content-disposition"].startswith("inline")
        assert original.headers["x-content-type-options"] == "nosniff"
        assert original.content == TAX_LETTER.pdf()

        page = await api.client.get(f"/api/documents/{doc_id}/pages/2.jpg")
        assert page.status_code == 200 and page.headers["content-type"] == "image/jpeg"
        assert "max-age" in page.headers["cache-control"]
        thumb = await api.client.get(f"/api/documents/{doc_id}/thumbnail.jpg")
        assert thumb.status_code == 200 and thumb.content[:3] == b"\xff\xd8\xff"

        assert (await api.client.get(f"/api/documents/{doc_id}/pages/9.jpg")).status_code == 404
        missing = await api.client.get("/api/documents/doc_nothinghere")
        assert missing.status_code == 404 and "exist" in missing.json()["detail"]


async def test_other_originals_are_downloads(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        body = await api.upload(("einladung.txt", TEXT_LETTER), private=True)
        doc_id = body["documents"][0]["id"]
        await api.read_all()
        original = await api.client.get(f"/api/documents/{doc_id}/file")
        assert original.status_code == 200
        assert original.headers["content-disposition"].startswith("attachment")
        assert original.headers["content-type"].startswith("text/plain")
        assert original.headers["x-content-type-options"] == "nosniff"


# --------------------------------------------------------------------------------------------------
# edits
# --------------------------------------------------------------------------------------------------


async def test_patch_document_fields(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await _read_letter(api, INVOICE_LETTER.pdf())
        response = await api.client.patch(
            f"/api/documents/{doc_id}",
            json={"title": "Phone bill", "kind": "invoice", "area": "money", "tags": ["phone"]},
        )
        assert response.status_code == 200
        document = response.json()
        assert (document["title"], document["area"], document["tags"]) == ("Phone bill", "money", ["phone"])

        for bad in ({"colour": "red"}, {"doc_date": "15.09.2026"}, {"kind": "spaceship"}):
            assert (await api.client.patch(f"/api/documents/{doc_id}", json=bad)).status_code == 422, bad
        unknown_party = await api.client.patch(f"/api/documents/{doc_id}", json={"party_id": "pty_nobody"})
        assert unknown_party.status_code == 404
        assert (await api.client.patch("/api/documents/doc_nothing", json={"title": "x"})).status_code == 404


async def test_a_reminders_pay_once_warning_follows_the_kind_it_is_filed_as(data_dir: Path) -> None:
    """Review round 4 of phase 2: a reminder re-filed as a court order still said "This is a payment reminder
    about …" in its Please-check card: the warning is said of the kind the letter is filed as, or dropped."""
    from ordnung.ingest.link import reminder_warning

    async with api_for(data_dir) as api:
        doc_id = await _read_letter(api, INVOICE_LETTER.pdf())
        other = "Keep the envelope."
        api.ctx.store.update_document(
            doc_id,
            kind="dunning",
            warnings=[reminder_warning("TechMarkt invoice 2026-118", "dunning"), other],
        )
        filed = await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "court_payment_order"})
        warnings = filed.json()["warnings"]
        assert warnings == [
            "This court order is about “TechMarkt invoice 2026-118”, which is still open. If you pay, pay the amount "
            "this order asks once — not the invoice as well.",
            other,
        ]
        back = await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "dunning"})
        assert back.json()["warnings"][0].startswith(
            "This is a payment reminder about “TechMarkt invoice 2026-118”"
        )
        gone = await api.client.patch(f"/api/documents/{doc_id}", json={"kind": "landlord_notice"})
        assert gone.json()["warnings"] == [other]


async def test_confirmed_arrival_date_recomputes_the_to_dos(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await _read_letter(api, FINE_LETTER.pdf())
        (fine,) = (await api.client.get("/api/items", params={"doc_id": doc_id})).json()
        assert fine["due_date"] == "2026-09-21"  # counted from the letter's date until we know better
        assert fine["computation"]["confidence"] == "low"

        unconfirmed = await api.client.patch(
            f"/api/documents/{doc_id}", json={"received_date": "2026-09-18", "received_confirmed": False}
        )
        assert unconfirmed.status_code == 200
        (same,) = (await api.client.get("/api/items", params={"doc_id": doc_id})).json()
        assert same["due_date"] == "2026-09-21"

        confirmed = await api.client.patch(
            f"/api/documents/{doc_id}", json={"received_date": "2026-09-18", "received_confirmed": True}
        )
        assert confirmed.json()["received_date"] == "2026-09-18"
        (recomputed,) = (await api.client.get("/api/items", params={"doc_id": doc_id})).json()
        assert recomputed["due_date"] == "2026-09-25"  # one week after the day it arrived
        assert recomputed["due_date_source"] == "computed"
        assert any(step["date"] == "2026-09-18" for step in recomputed["computation"]["steps"])
        assert "document.received_date" in [
            entry["kind"] for entry in (await api.client.get("/api/activity")).json()
        ]


async def test_manual_dates_are_not_recomputed(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await _read_letter(api, FINE_LETTER.pdf())
        (fine,) = (await api.client.get("/api/items", params={"doc_id": doc_id})).json()
        await api.client.patch(f"/api/items/{fine['id']}", json={"due_date": "2026-10-01"})
        await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-18"})
        (kept,) = (await api.client.get("/api/items", params={"doc_id": doc_id})).json()
        assert kept["due_date"] == "2026-10-01" and kept["due_date_source"] == "manual"


# --------------------------------------------------------------------------------------------------
# reprocess, trash, purge
# --------------------------------------------------------------------------------------------------


async def test_reprocess_queues_a_forced_job(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await _read_letter(api, INVOICE_LETTER.pdf())
        response = await api.client.post(f"/api/documents/{doc_id}/reprocess")
        assert response.status_code == 202
        job = response.json()
        assert (job["kind"], job["force"], job["doc_id"]) == ("reprocess", True, doc_id)
        assert await api.read_all() == 1
        assert (await api.client.get(f"/api/documents/{doc_id}")).json()["document"]["status"] == "processed"
        assert [call.purpose for call in api.backend.calls] == ["extract", "extract"]  # cache bypassed


async def test_delete_moves_to_trash_or_purges(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        tax = await _read_letter(api, TAX_LETTER.pdf())
        trashed = await api.client.delete(f"/api/documents/{tax}")
        assert trashed.json() == {"id": tax, "purged": False, "removed_open_items": 2}
        assert (await api.client.get("/api/documents")).json() == []
        assert (await api.client.get("/api/items")).json() == []
        kept = (await api.client.get(f"/api/documents/{tax}")).json()["document"]
        assert kept["deleted_at"] is not None
        assert (await api.client.post(f"/api/documents/{tax}/reprocess")).status_code == 409

        invoice = await _read_letter(api, INVOICE_LETTER.pdf())
        derived = data_dir / "derived" / invoice
        assert derived.is_dir()
        purged = await api.client.delete(f"/api/documents/{invoice}", params={"purge": "true"})
        assert purged.json() == {"id": invoice, "purged": True, "removed_open_items": 1}
        assert (await api.client.get(f"/api/documents/{invoice}")).status_code == 404
        assert (await api.client.get(f"/api/documents/{invoice}/file")).status_code == 404
        assert not derived.exists()
        assert (await api.client.delete(f"/api/documents/{invoice}")).status_code == 404


# --------------------------------------------------------------------------------------------------
# error mapping
# --------------------------------------------------------------------------------------------------


def _failing_route(app: FastAPI, exc: Exception) -> None:
    async def boom() -> None:
        raise exc

    app.add_api_route("/api/test-boom", boom, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())  # before the web app's catch-all


async def test_model_failures_become_503_with_a_code(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        _failing_route(api.app, ClaudeAuthError("Claude is not signed in. Run `claude` and log in."))
        response = await api.client.get("/api/test-boom")
        assert response.status_code == 503
        assert response.json() == {
            "detail": "Claude is not signed in. Run `claude` and log in.",
            "code": "claude_auth",
        }

    async with api_for(data_dir) as api:
        _failing_route(api.app, ClaudeRateLimited("Usage limit reached", reset_at="3pm"))
        response = await api.client.get("/api/test-boom")
        assert response.status_code == 503
        assert response.json()["code"] == "llm_paused" and response.headers["retry-after"]


async def test_demo_refuses_uploads_that_would_need_claude(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """In the zero-token demo a new letter can't be read: a clear 409 instead of a failed document."""
    import httpx

    from ordnung.api.app import create_app
    from ordnung.app_context import build_context
    from ordnung.llm.replay import ReplayBackend

    ctx = build_context(tmp_path, backend_obj=ReplayBackend(tmp_path / "fixtures"))
    app = create_app(ctx, token=None, demo=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8765") as client:
        files = {"files": ("letter.txt", b"Hallo", "text/plain")}
        headers = {"X-Ordnung-Client": "web"}
        refused = await client.post("/api/documents", files=files, headers=headers)
        assert refused.status_code == 409
        assert "ordnung serve" in refused.json()["detail"]
        private = await client.post("/api/documents", files=files, data={"private": "true"}, headers=headers)
        assert private.status_code == 201
    ctx.close()
