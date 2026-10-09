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
from helpers_secretary import TODAY as TODAY_DATE
from helpers_secretary import add_doc, add_item
from helpers_sender_land import BACKWARDS, HOLIDAY, MUNICH, letter_from, to_do
from ordnung import clock
from ordnung.api.routes.documents import document_detail
from ordnung.db.store import Store
from ordnung.llm.base import ClaudeAuthError, ClaudeNotInstalled, ClaudeRateLimited
from ordnung.models import DocumentDetail
from test_api_support import FINE_LETTER, TODAY, Api, ApiRouter, api_for, lifespan

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


async def test_a_letter_says_whether_it_was_given_to_claude(data_dir: Path) -> None:
    """FEAT G4: with Claude not installed the letter waits and was never sent (``given_to_model`` false: the
    page says "Not sent to Claude"); once read it was."""
    router = ApiRouter()
    router.errors["extract"] = lambda: ClaudeNotInstalled("The “claude” command was not found.")
    async with api_for(data_dir, router=router) as api:
        doc_id = await _read_letter(api, TAX_LETTER.pdf())
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["status"] == "queued" and detail["given_to_model"] is False
        del router.errors["extract"]
        api.ctx.worker.claude_ready()
        assert await api.read_all() == 1
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["document"]["status"] == "processed" and detail["given_to_model"] is True


async def test_a_letter_addressed_to_someone_else_says_so(data_dir: Path) -> None:
    """Worked out on read from the reading's addressee and the profile's name (``secretary.addressee``):
    nothing is written, and the letter list doesn't carry it."""
    router = ApiRouter()
    router.payloads[TAX_LETTER.marker]["recipient_name"] = "Frau Alex Rivera"
    router.payloads[INVOICE_LETTER.marker]["recipient_name"] = "Herrn Sam Rivera"
    async with api_for(data_dir, router=router) as api:
        tax = await _read_letter(api, TAX_LETTER.pdf())
        invoice = await _read_letter(api, INVOICE_LETTER.pdf(), "rechnung.pdf")
        before = (await api.client.get(f"/api/documents/{tax}")).json()
        assert before["addressed_to"] is None  # the profile has no name yet: nothing to compare with
        profile = {"name": "Sam Rivera", "address": "Musterweg 1\n12345 Musterstadt"}
        assert (await api.client.put("/api/profile", json=profile)).status_code == 200

        detail = (await api.client.get(f"/api/documents/{tax}")).json()
        assert detail["addressed_to"] == "Alex Rivera"
        assert detail["document"]["updated_at"] == before["document"]["updated_at"]
        assert (await api.client.get(f"/api/documents/{invoice}")).json()["addressed_to"] is None
        assert all("addressed_to" not in row for row in (await api.client.get("/api/documents")).json())

        renamed = {**profile, "name": "Alex Rivera"}
        assert (await api.client.put("/api/profile", json=renamed)).status_code == 200
        assert (await api.client.get(f"/api/documents/{tax}")).json()["addressed_to"] is None
        assert (await api.client.get(f"/api/documents/{invoice}")).json()["addressed_to"] == "Sam Rivera"


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
        thumb = await api.client.get(f"/api/documents/{doc_id}/thumbnail.jpg")
        assert thumb.status_code == 200 and thumb.content[:3] == b"\xff\xd8\xff"
        # no copy may stay in the browser's cache once the letter is deleted
        assert {response.headers["cache-control"] for response in (original, page, thumb)} == {"no-store"}

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


async def test_read_again_while_a_reading_waits_or_runs_queues_no_second_one(data_dir: Path) -> None:
    """Two quick “Read again” (a double click, or the phone as well) get the same job back, also while it
    runs: Claude reads the letter once."""
    async with api_for(data_dir) as api:
        doc_id = await _read_letter(api, INVOICE_LETTER.pdf())
        url = f"/api/documents/{doc_id}/reprocess"
        first, second = await asyncio.gather(api.client.post(url), api.client.post(url))
        assert first.status_code == second.status_code == 202
        job = first.json()
        assert second.json() == job and (job["kind"], job["force"]) == ("reprocess", True)

        running = api.ctx.store.claim_next_job()
        assert running is not None and running.id == job["id"]
        third = await api.client.post(url)
        assert third.status_code == 202
        assert (third.json()["id"], third.json()["status"]) == (job["id"], "running")
        assert [j.id for j in api.ctx.store.list_jobs(active_only=True)] == [job["id"]]

        api.ctx.store.update_job(job["id"], status="queued")  # give it back to the worker
        assert await api.read_all() == 1
        assert [call.purpose for call in api.backend.calls] == ["extract", "extract"]


async def test_delete_moves_to_trash_or_purges(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        tax = await _read_letter(api, TAX_LETTER.pdf())
        trashed = await api.client.delete(f"/api/documents/{tax}")
        assert trashed.json() == {"id": tax, "purged": False, "removed_open_items": 2}
        assert "clear-site-data" not in trashed.headers  # the trash can be undone
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
        assert purged.headers["clear-site-data"] == '"cache"'  # the browser drops what it cached
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
        assert "ordnung serve" in refused.json()["detail"] and refused.json()["code"] == "demo_replay"
        private = await client.post("/api/documents", files=files, data={"private": "true"}, headers=headers)
        assert private.status_code == 201
    ctx.close()


# --------------------------------------------------------------------------------------------------
# to-dos set aside on the letter page (the same rules as Today and the party drawer)
# --------------------------------------------------------------------------------------------------


def test_the_letter_detail_sets_aside_what_is_not_to_act_on(store: Store) -> None:
    """The verdict never leads with an invoice its reminder replaced or a date that was history when the
    letter was read ("Pay €89.99 · 25 days overdue", "Pay €1,560 deposit · 362 days overdue")."""
    party = store.add_party(name="TechMarkt Online GmbH", kind="retailer").id
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
    by_reminder = add_item(
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
    add_item(
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
    lease = add_doc(store, "lease", kind="rent_lease", doc_date="2025-09-15", party_id=party)
    deposit = add_item(
        store,
        kind="payment",
        title="Security deposit (Kaution)",
        due_date="2025-10-01",
        filed_on=TODAY_DATE.isoformat(),
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
        filed_on=TODAY_DATE.isoformat(),
        amount=640.0,
        direction="out",
        recurrence={"interval": 1, "unit": "months"},
        party_id=party,
        doc_id=lease,
    )

    replaced = document_detail(store, invoice, TODAY_DATE)
    assert [(a.item_id, a.reason, a.replaced_by) for a in replaced.set_aside] == [
        (by_reminder, "replaced", reminder)
    ]
    assert [item.id for item in replaced.items] == [by_reminder]  # the list stays complete
    assert (
        document_detail(store, reminder, TODAY_DATE).set_aside == []
    )  # the reminder's payment is the one to act on

    archived = document_detail(store, lease, TODAY_DATE)
    assert [(a.item_id, a.reason) for a in archived.set_aside] == [(deposit, "history")]
    assert rent in {item.id for item in archived.items}  # a schedule shows its next date instead


def test_a_letters_page_lists_the_scam_signs_its_idea_counts(store: Store) -> None:
    """Walkthrough of phase 2: the letter said "the 3 strongest of 7 warning signs", its Idea "5 warning
    signs". The page gets the Idea's list (``scam_signs``); an ordinary letter's is empty."""
    fake = store.add_party(name="Beitrags Zahlungszentrale", kind="public_broadcaster").id
    scam = add_doc(
        store,
        "scam",
        kind="other",
        party_id=fake,
        hidden_text=True,
        warnings=["Foreign IBAN — possible scam.", "It threatens enforcement within 48 hours."],
    )
    signs = document_detail(store, scam, TODAY_DATE).scam_signs
    assert signs == [
        "The letter contains hidden text that you can't see on the page.",
        "Foreign IBAN — possible scam.",
        "It threatens enforcement within 48 hours.",
    ]
    plain = add_doc(store, "plain", kind="invoice", warnings=["It threatens enforcement within 48 hours."])
    assert document_detail(store, plain, TODAY_DATE).scam_signs == []


def test_a_letter_asks_about_its_sender_s_land_with_its_own_dates(store: Store) -> None:
    """The letter page carries the question the postcode on the sender's letters raises (ADR 0019), counting
    the dates of that letter that may change; the drawer counts all of the sender's. A letter with scam signs
    asks nothing, and neither does one from a sender whose Land is set."""
    party = store.add_party(name="Stadt München", kind="authority")
    first = letter_from(store, party, MUNICH, day="2026-08-01")
    second = letter_from(store, party, MUNICH, day="2026-09-20")
    to_do(store, party, first, HOLIDAY)
    to_do(store, party, second, HOLIDAY)
    to_do(store, party, second, BACKWARDS)
    scam = letter_from(store, party, MUNICH, day="2026-09-25", warnings=["Possible scam: an account abroad."])

    asked = document_detail(store, first, TODAY_DATE).region_suggestion
    assert asked is not None
    assert (asked.region, asked.postcode, asked.doc_id) == ("BY", "80331", second)
    assert (asked.waiting, asked.may_be_late) == (1, False)
    later = document_detail(store, second, TODAY_DATE).region_suggestion
    assert later is not None and (later.waiting, later.may_be_late) == (2, True)
    assert document_detail(store, scam, TODAY_DATE).region_suggestion is None

    store.update_party(party.id, region="BY")
    assert document_detail(store, first, TODAY_DATE).region_suggestion is None
