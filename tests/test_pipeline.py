"""End-to-end ingestion with the FakeBackend: upload → text/transcribe → extract → verify → compute →
link → plan, on generated PDFs and photos."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from fixtures_llm import (
    APPOINTMENT_LETTER,
    TAX_IBAN,
    TAX_LETTER,
    TODAY,
    Letter,
    Router,
    fake_backend,
    record_events,
)
from helpers_docs import INJECTION, hidden_text_pdf, photo, scanned_pdf
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.ingest import pipeline
from ordnung.ingest.gaps import CHECK_SLOT, gap_warning
from ordnung.ingest.intake import IntakeError
from ordnung.ingest.pipeline import STAGES, add_file, ingest_document, reprocess
from ordnung.ingest.plan import needs_check
from ordnung.llm.fake import FakeBackend
from ordnung.models import Item
from ordnung.secretary.triggers import Ledger, please_check
from test_api_support import ApiRouter, api_for


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def router() -> Router:
    return Router(transcript=APPOINTMENT_LETTER.transcript())


@pytest.fixture
def ctx(data_dir: Path, router: Router) -> Iterator[AppContext]:
    context = build_context(data_dir, backend_obj=fake_backend(router))
    yield context
    context.close()


def backend(ctx: AppContext) -> FakeBackend:
    assert isinstance(ctx.llm.backend, FakeBackend)
    return ctx.llm.backend


def items_by_kind(ctx: AppContext, doc_id: str) -> dict[str, Item]:
    return {item.kind: item for item in ctx.store.list_items(doc_id=doc_id)}


# --------------------------------------------------------------------------------------------------
# Text PDF: the tax assessment hero case
# --------------------------------------------------------------------------------------------------


async def test_tax_assessment_objection_deadline_is_computed_and_grounded(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    assert document.status == "queued"
    assert document.id.startswith("doc_")

    assert await ctx.worker.run_until_idle() == 1

    document = ctx.store.get_document(document.id)
    assert document is not None
    assert document.status == "processed"
    assert document.kind == "tax_assessment"
    assert document.doc_date == "2026-09-15"
    assert document.text_mode == "text"
    assert document.ai_processed_at is not None
    objection = items_by_kind(ctx, document.id)["deadline"]
    assert objection.due_date == "2026-10-21"  # posted 15 Sep → delivered Sat 19 → Mon 21 Sep → +1 month
    assert objection.due_date_source == "computed"
    assert objection.grounding == "verified"
    assert objection.evidence[0].page == 2
    assert objection.evidence[0].boxes
    assert objection.computation is not None
    assert objection.computation.confidence == "high"
    assert "ao_122_2_1" in objection.computation.rule_ids
    assert objection.send_by is not None and objection.send_by < "2026-10-21"
    assert objection.slot_key and objection.id.startswith("itm_")


async def test_tax_payment_fixed_date_party_case_and_facts(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    await ctx.worker.run_until_idle()
    document = ctx.store.get_document(document.id)
    assert document is not None

    payment = items_by_kind(ctx, document.id)["payment"]
    assert payment.due_date == "2026-10-15"
    assert payment.due_date_source == "fixed"
    assert payment.amount == 1234.56
    assert payment.grounding == "verified"
    assert payment.evidence[0].value_consistent

    assert document.party_id is not None
    party = ctx.store.get_party(document.party_id)
    assert party is not None
    assert party.name == "Finanzamt Musterstadt"
    assert party.kind == "tax_office"
    assert [identifier.value for identifier in party.identifiers] == ["123/456/78901"]
    assert party.ibans == [TAX_IBAN]
    case = ctx.store.get_case(document.case_id or "")
    assert case is not None and case.reference == "123/456/78901"
    assert payment.party_id == party.id and payment.case_id == case.id

    assert document.key_facts[0].evidence is not None
    assert document.key_facts[0].evidence.grounding == "verified"
    assert document.payment is not None and document.payment.iban_valid is True
    assert ctx.store.search("Einkommensteuer")[0].doc_id == document.id
    activity = ctx.store.list_activity(limit=1)[0]
    assert activity.message == (
        "Read “Income tax assessment 2025” · 1 deadline, 1 payment · linked to Finanzamt Musterstadt"
    )
    assert [call.purpose for call in backend(ctx).calls] == ["extract"]


async def test_extract_request_carries_wrapped_text_and_context(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    await ctx.worker.run_until_idle()
    request = backend(ctx).calls[0]
    assert request.model == ctx.settings.models.extract
    assert request.doc_ids == [document.id]
    assert request.schema_ is not None
    assert "Today is 2026-09-25" in request.prompt
    body = request.prompt.split("<untrusted_document>", 1)[1]
    assert "=== Page 1 ===" in body and "=== Page 2 ===" in body
    assert "Einkommensteuer" in body
    assert "</untrusted_document>" in body
    assert "English" in request.system


# --------------------------------------------------------------------------------------------------
# Photo: transcribe + extract → model_read
# --------------------------------------------------------------------------------------------------


async def test_photo_is_transcribed_then_extracted_as_model_read(ctx: AppContext) -> None:
    document = await add_file(ctx, photo("JPEG", size=(600, 800)), "IMG_0001.jpg")
    await ctx.worker.run_until_idle()

    calls = backend(ctx).calls
    assert [call.purpose for call in calls] == ["transcribe", "extract"]
    transcribe = calls[0]
    assert transcribe.model == ctx.settings.models.transcribe
    assert transcribe.attachments[0].media_type == "image/jpeg"
    assert transcribe.cache_key is not None and len(transcribe.cache_key) == 64

    document = ctx.store.get_document(document.id)
    assert document is not None
    assert document.status == "processed"
    assert document.text_mode == "vision"
    page = ctx.store.get_page(document.id, 1)
    assert page is not None and page.text_source == "transcript"
    appointment = items_by_kind(ctx, document.id)["appointment"]
    assert appointment.grounding == "model_read"
    assert appointment.evidence[0].boxes == []
    assert appointment.due_date == "2026-10-12"
    assert appointment.due_time == "10:30"
    assert appointment.computation is not None
    assert appointment.computation.confidence != "high"
    assert any("photo" in warning for warning in appointment.computation.warnings)


async def test_several_photos_become_one_document(ctx: AppContext) -> None:
    first, second = photo("JPEG", size=(600, 800)), photo("PNG", size=(640, 800))
    document = await add_file(ctx, first, "page1.jpg", combine_with=[second])
    assert document.mime == "application/pdf"
    assert document.pages == 2
    await ctx.worker.run_until_idle()
    assert [call.purpose for call in backend(ctx).calls].count("transcribe") == 2


# --------------------------------------------------------------------------------------------------
# Dedupe, reprocess, private
# --------------------------------------------------------------------------------------------------


async def test_reupload_returns_the_same_document_without_a_new_job(ctx: AppContext) -> None:
    first = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    second = await add_file(ctx, TAX_LETTER.pdf(), "copy.pdf")
    assert second.id == first.id
    assert second.filename == "bescheid.pdf"
    assert len(ctx.store.list_jobs()) == 1
    assert ctx.store.counts()["documents"] == 1


async def test_reupload_restores_a_trashed_document(ctx: AppContext) -> None:
    first = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    ctx.store.trash_document(first.id)
    again = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    assert again.id == first.id and again.deleted_at is None


async def test_rejected_upload_raises_a_readable_error(ctx: AppContext) -> None:
    with pytest.raises(IntakeError, match="empty"):
        await add_file(ctx, b"", "nothing.pdf")


async def test_reprocess_keeps_user_modified_items_and_replaces_the_rest(
    ctx: AppContext, router: Router
) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    await ctx.worker.run_until_idle()
    items = items_by_kind(ctx, document.id)
    edited = ctx.store.update_item(items["payment"].id, title="Paid by standing order?", user_modified=True)

    changed = router.payloads[TAX_LETTER.marker]
    changed["items"] = [changed["items"][0] | {"title": "Einspruch deadline"}]
    reprocess(ctx, document.id)
    await ctx.worker.run_until_idle()

    after = {item.id: item for item in ctx.store.list_items(doc_id=document.id)}
    assert after[edited.id].title == "Paid by standing order?"
    assert after[items["deadline"].id].title == "Einspruch deadline"
    assert len(after) == 2
    assert [call.purpose for call in backend(ctx).calls] == ["extract", "extract"]


async def test_reprocess_drops_stale_items_that_nobody_edited(ctx: AppContext, router: Router) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    await ctx.worker.run_until_idle()
    router.payloads[TAX_LETTER.marker]["items"] = router.payloads[TAX_LETTER.marker]["items"][:1]
    await ingest_document(ctx, document.id, force=True)
    assert [item.kind for item in ctx.store.list_items(doc_id=document.id)] == ["deadline"]


async def test_second_read_uses_the_cache(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    await ctx.worker.run_until_idle()
    await ingest_document(ctx, document.id)
    assert len(backend(ctx).calls) == 1
    assert ctx.store.usage_stats().cache_hits == 1


async def test_a_new_model_choice_is_a_new_call_not_a_cache_hit(data_dir: Path, router: Router) -> None:
    """The cache is keyed by the model the backend runs a call on (Settings → Claude, an environment
    pin), not by the request's alias: a letter read again after the choice changed is read anew."""

    class Chosen(FakeBackend):
        choice = "claude-sonnet-5"

        def model_for(self, req: object) -> str:
            return self.choice

    backend = Chosen(router)
    ctx = build_context(data_dir, backend_obj=backend)
    try:
        document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
        await ctx.worker.run_until_idle()
        await ingest_document(ctx, document.id)
        assert len(backend.calls) == 1 and ctx.store.usage_stats().cache_hits == 1
        backend.choice = "claude-opus-5-5"
        await ingest_document(ctx, document.id)
        assert len(backend.calls) == 2 and ctx.store.usage_stats().cache_hits == 1
        await ingest_document(ctx, document.id)  # the new model's reading is cached in turn
        assert len(backend.calls) == 2 and ctx.store.usage_stats().cache_hits == 2
    finally:
        ctx.close()


async def test_private_documents_never_reach_a_model(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", private=True)
    await ctx.worker.run_until_idle()
    document = ctx.store.get_document(document.id)
    assert document is not None
    assert document.ai_private
    assert document.status == "processed"
    assert document.title == "bescheid.pdf"
    assert document.ai_processed_at is None
    assert backend(ctx).calls == []
    assert ctx.store.list_items(doc_id=document.id) == []
    assert ctx.store.search("Einkommensteuer")[0].doc_id == document.id
    # the privacy statement names who doesn't read it, as the letter's footer and badge do
    logged = [entry.message for entry in ctx.store.list_activity(5, kinds=["document.private"])]
    assert logged == ["Stored “bescheid.pdf” privately · not sent to Claude"]


async def test_private_photo_is_not_transcribed(ctx: AppContext) -> None:
    await add_file(ctx, photo("JPEG", size=(600, 800)), "IMG.jpg", private=True)
    await ctx.worker.run_until_idle()
    assert backend(ctx).calls == []


# --------------------------------------------------------------------------------------------------
# Please check, hidden text, events
# --------------------------------------------------------------------------------------------------


async def test_unfound_quote_puts_the_document_in_please_check(ctx: AppContext, router: Router) -> None:
    payload = router.payloads[TAX_LETTER.marker]
    payload["items"][0]["quote"] = "Der Einspruch ist innerhalb von zwei Wochen einzulegen."
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    await ctx.worker.run_until_idle()
    document = ctx.store.get_document(document.id)
    assert document is not None and document.status == "needs_review"
    objection = items_by_kind(ctx, document.id)["deadline"]
    assert objection.grounding == "unverified"
    assert objection.computation is not None and objection.computation.confidence != "high"
    assert "1 date could not be confirmed against the letter's text." in document.warnings


async def test_hidden_text_stays_out_of_the_prompt_and_raises_a_warning(
    ctx: AppContext, router: Router
) -> None:
    router.letters = (TAX_LETTER,)
    router.payloads = {TAX_LETTER.marker: {**TAX_LETTER.extraction(), "items": [], "key_facts": []}}
    backend(ctx).responses = lambda req: {**router.payloads[TAX_LETTER.marker], "title": "Invoice"}
    document = await add_file(ctx, hidden_text_pdf(), "invoice.pdf")
    await ctx.worker.run_until_idle()
    prompt = backend(ctx).calls[0].prompt
    assert INJECTION not in prompt
    assert "Rechnung Nr. 2026-0042" in prompt
    document = ctx.store.get_document(document.id)
    assert document is not None and document.hidden_text
    assert any("invisible text" in warning for warning in document.warnings)
    assert any("addressed to an AI" in warning for warning in document.warnings)


async def test_job_events_are_published_in_stage_order(ctx: AppContext) -> None:
    events = record_events(ctx.bus)
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    await ctx.worker.run_until_idle()

    progress = [data for kind, data in events if kind == "job.progress"]
    assert progress[0]["status"] == "queued"
    assert [data["stage"] for data in progress[1:]] == [stage for stage in STAGES if stage != "transcribe"]
    assert [data["progress"] for data in progress[1:]] == sorted(data["progress"] for data in progress[1:])
    assert progress[-1]["status"] == "done"
    assert {data["job_id"] for data in progress} == {ctx.store.list_jobs()[0].id}
    assert all(data["doc_id"] == document.id for data in progress)
    kinds = [kind for kind, _ in events]
    assert kinds.index("document.processed") > max(
        i for i, kind in enumerate(kinds) if kind == "job.progress"
    )
    job = ctx.store.list_jobs()[0]
    assert job.status == "done" and job.stage == "done" and job.progress == 1.0


async def _stages_seen(ctx: AppContext, content: bytes, filename: str) -> list[str]:
    document = await add_file(ctx, content, filename)
    seen: list[str] = []

    async def on_stage(stage: str, progress: float) -> None:
        seen.append(stage)

    await ingest_document(ctx, document.id, on_stage=on_stage)
    return seen


async def test_on_stage_callback_sees_every_stage_that_happens(ctx: AppContext) -> None:
    """UI audit R1-backend-5: the stepper said "Reading the photo" for a PDF with text and "Reading the
    text" for a phone photo. Only the stages that happen are reported: a PDF's text layer is read, a photo
    and a PDF page without text are transcribed."""
    after = ["extract", "verify", "compute", "link", "plan", "done"]
    assert await _stages_seen(ctx, TAX_LETTER.pdf(), "bescheid.pdf") == ["intake", "text", *after]
    photo_stages = await _stages_seen(ctx, photo("JPEG", size=(600, 800)), "IMG_0001.jpg")
    assert photo_stages == ["intake", "transcribe", *after]
    assert await _stages_seen(ctx, scanned_pdf(), "scan.pdf") == ["intake", "text", "transcribe", *after]
    assert set(photo_stages) | {"text"} == set(STAGES)


async def test_blank_scan_fails_with_a_readable_error(ctx: AppContext, router: Router) -> None:
    router.transcript = ""
    document = await add_file(ctx, photo("JPEG", size=(600, 800)), "blank.jpg")
    await ctx.worker.run_until_idle()
    document = ctx.store.get_document(document.id)
    assert document is not None
    assert document.status == "failed"
    assert document.error == "We couldn't find any readable text in this document."
    assert ctx.store.list_jobs()[0].status == "failed"


async def test_missing_original_fails_readably(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    original = ctx.store.get_document_file(document.id)
    assert original is not None
    original.unlink()
    for page in ctx.store.list_pages(document.id):
        (ctx.store.data_dir / page.image_path).unlink()
    with pytest.raises(IntakeError):
        await ingest_document(ctx, document.id)
    failed = ctx.store.get_document(document.id)
    assert failed is not None and failed.status == "failed"
    assert failed.error is not None and "original file" in failed.error


async def test_unreadable_transcription_answer_fails_readably(ctx: AppContext, router: Router) -> None:
    backend(ctx).responses = lambda req: {"notes": "?"} if req.purpose == "transcribe" else router(req)
    document = await add_file(ctx, photo("JPEG", size=(600, 800)), "IMG.jpg")
    await ctx.worker.run_until_idle()
    failed = ctx.store.get_document(document.id)
    assert failed is not None and failed.status == "failed"
    assert failed.error == "Claude's transcription of page 1 could not be read."


async def test_received_date_must_be_a_date(ctx: AppContext) -> None:
    with pytest.raises(IntakeError, match="not a date"):
        await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", received_date="yesterday")
    assert ctx.store.counts()["documents"] == 0


async def test_received_date_from_the_person_counts_as_confirmed(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", received_date=date(2026, 9, 22))
    assert document.received_date == "2026-09-22"
    await ctx.worker.run_until_idle()
    objection = items_by_kind(ctx, document.id)["deadline"]
    assert objection.due_date == "2026-10-21"  # the earlier, safe date is kept …
    assert objection.computation is not None
    assert any("22 Sep" in warning for warning in objection.computation.warnings)  # … with a note


async def test_letters_use_the_person_s_country_and_only_a_chosen_region(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit B integration: ``Profile.country`` reaches letter dates, and ``Profile.region`` counts as the
    person's Land only once they chose it (onboarding) — the default ``NW`` must not move payments."""
    seen: list[dict[str, object]] = []
    real = pipeline.rule_context

    def spy(*args: object, **kwargs: object) -> object:
        seen.append(kwargs)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pipeline, "rule_context", spy)
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    await ctx.worker.run_until_idle()
    assert seen[-1]["recipient_region"] is None and seen[-1]["country"] == "DE"

    ctx.store.save_profile({"region": "BY", "country": "AT", "onboarded": True})
    await ingest_document(ctx, document.id, force=True)
    assert seen[-1]["recipient_region"] == "BY" and seen[-1]["country"] == "AT"
    objection = items_by_kind(ctx, document.id)["deadline"]
    assert objection.computation is not None and objection.computation.confidence == "low"
    assert any("only knows German rules" in w for w in objection.computation.warnings)


# --------------------------------------------------------------------------------------------------
# A reading that came back incomplete (ingest/gaps.py): one "Please check" to-do written by code
# --------------------------------------------------------------------------------------------------

GAP_NOTICE = "Gegen diesen Gebührenbescheid können Sie binnen eines Monats nach seiner Bekanntgabe Widerspruch einlegen."
GAP_LETTER = Letter(
    marker="Sondernutzungsgebühr",
    pages=(
        (
            "Stadt Beispielhausen · Ordnungsamt · Rathausplatz 1 · 12345 Beispielhausen",
            "SPECIMEN",
            "Datum: 15.09.2026",
            "Bescheid über eine Sondernutzungsgebühr",
            "Sehr geehrte Frau Probe,",
            "für die Nutzung der Gehwegfläche setzen wir eine Gebühr von 85,00 EUR fest.",
            "Rechtsbehelfsbelehrung",
            # the notice wraps onto a second line, as printed letters do
            "Gegen diesen Gebührenbescheid können Sie binnen eines Monats",
            "nach seiner Bekanntgabe Widerspruch einlegen.",
        ),
    ),
    payload={"kind": "other", "title": "Fee decision", "summary": "A fee.", "explanation": "Pay it."},
)
GAP_COMPLETE = {
    **GAP_LETTER.payload,
    "kind": "authority_letter",
    "sender": {"name": "Stadt Beispielhausen", "kind": "authority"},
    "document_date": "2026-09-15",
    "remedy": {"type": "widerspruch", "quote": GAP_NOTICE},
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
                "text": "one month after notification",
            },
            "quote": GAP_NOTICE,
        }
    ],
}


@pytest.fixture
def gap_router() -> Router:
    return Router(letters=(GAP_LETTER,))


@pytest.fixture
def gap_ctx(data_dir: Path, gap_router: Router) -> Iterator[AppContext]:
    context = build_context(data_dir, backend_obj=fake_backend(gap_router))
    yield context
    context.close()


def gap_api_router() -> ApiRouter:
    router = ApiRouter()
    router.letters = (*router.letters, GAP_LETTER)
    router.payloads[GAP_LETTER.marker] = GAP_LETTER.extraction()
    return router


async def _read_gap_letter(ctx: AppContext) -> str:
    document = await add_file(ctx, GAP_LETTER.pdf(), "bescheid.pdf")
    await ctx.worker.run_until_idle()
    return document.id


async def test_an_empty_reading_of_a_decision_gets_a_dated_please_check_to_do(gap_ctx: AppContext) -> None:
    doc_id = await _read_gap_letter(gap_ctx)
    document = gap_ctx.store.get_document(doc_id)
    assert document is not None and document.status == "needs_review"
    assert gap_warning("empty", "dated") in document.warnings
    [check] = gap_ctx.store.list_items(doc_id=doc_id)
    assert check.slot_key == CHECK_SLOT and check.kind == "deadline" and check.priority == "high"
    # posted Tue 15 Sep, delivered on the 3rd day (Fri 18 Sep): one month is Sun 18 Oct → Mon 19 Oct
    assert check.due_date == "2026-10-19" and check.due_date_source == "computed"
    assert check.computation is not None and check.computation.confidence == "low"
    assert check.grounding == "verified" and not check.evidence[0].value_consistent
    assert needs_check(check)


async def test_the_please_check_idea_says_the_reading_came_back_incomplete(gap_ctx: AppContext) -> None:
    """Nothing was "not found" on the letter: the Idea says why the to-do is there (UX review)."""
    doc_id = await _read_gap_letter(gap_ctx)
    [idea] = please_check(Ledger(gap_ctx.store, clock.today()))
    assert idea.body.startswith(
        "Claude's reading of this letter came back incomplete, so Ordnung added a to-do"
    )
    assert "couldn't find" not in idea.body
    assert {ref.id for ref in idea.refs} >= {doc_id}


async def test_confirming_the_check_to_do_clears_please_check(data_dir: Path) -> None:
    async with api_for(data_dir, router=gap_api_router()) as api:
        doc_id = (await api.upload(("bescheid.pdf", GAP_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [check] = (await api.client.get("/api/items", params={"doc_id": doc_id})).json()
        assert check["slot_key"] == CHECK_SLOT
        assert (await api.client.get(f"/api/documents/{doc_id}")).json()["document"][
            "status"
        ] == "needs_review"
        assert (await api.client.post(f"/api/items/{check['id']}/confirm")).status_code == 200
        assert (await api.client.get(f"/api/documents/{doc_id}")).json()["document"]["status"] == "processed"


async def test_a_recompute_keeps_the_check_to_do_low_and_please_check(data_dir: Path) -> None:
    async with api_for(data_dir, router=gap_api_router()) as api:
        doc_id = (await api.upload(("bescheid.pdf", GAP_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        response = await api.client.put("/api/profile", json={"region": "HH", "onboarded": True})
        assert response.status_code == 200
        [check] = api.ctx.store.list_items(doc_id=doc_id)
        assert check.slot_key == CHECK_SLOT and check.due_date is not None
        assert check.computation is not None and check.computation.confidence == "low"
        assert needs_check(check)
        document = api.ctx.store.get_document(doc_id)
        assert document is not None and document.status == "needs_review"


async def test_reading_again_completely_removes_the_untouched_check_to_do(
    gap_ctx: AppContext, gap_router: Router
) -> None:
    doc_id = await _read_gap_letter(gap_ctx)
    assert [item.slot_key for item in gap_ctx.store.list_items(doc_id=doc_id)] == [CHECK_SLOT]
    gap_router.payloads[GAP_LETTER.marker] = copy.deepcopy(GAP_COMPLETE)
    await ingest_document(gap_ctx, doc_id, force=True)
    [objection] = gap_ctx.store.list_items(doc_id=doc_id)
    assert objection.slot_key != CHECK_SLOT and objection.title == "Objection (Widerspruch)"
    document = gap_ctx.store.get_document(doc_id)
    assert document is not None and document.status == "processed"
    assert not any("Claude's reading" in warning for warning in document.warnings)


async def test_a_complete_reading_gets_no_check_to_do(gap_ctx: AppContext, gap_router: Router) -> None:
    gap_router.payloads[GAP_LETTER.marker] = copy.deepcopy(GAP_COMPLETE)
    doc_id = await _read_gap_letter(gap_ctx)
    assert [item.slot_key == CHECK_SLOT for item in gap_ctx.store.list_items(doc_id=doc_id)] == [False]


async def test_a_reading_that_names_its_sender_of_a_letter_without_a_notice_files_nothing(
    ctx: AppContext, router: Router
) -> None:
    router.payloads[APPOINTMENT_LETTER.marker] = {
        "kind": "appointment",
        "title": "Appointment",
        "summary": "s",
        "explanation": "e",
        "sender": {"name": "Bürgeramt Musterstadt", "kind": "authority"},
    }
    document = await add_file(ctx, APPOINTMENT_LETTER.pdf(), "termin.pdf")
    await ctx.worker.run_until_idle()
    assert ctx.store.list_items(doc_id=document.id) == []
    stored = ctx.store.get_document(document.id)
    assert stored is not None and stored.status == "processed"
