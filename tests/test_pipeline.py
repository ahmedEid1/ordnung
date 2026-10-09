"""End-to-end ingestion with the FakeBackend: upload → text/transcribe → extract → verify → compute →
link → plan, on generated PDFs and photos."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

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
from ordnung.ingest.gaps import CHECK_SLOT, DEADLINE_SLOT, GAP_WARNING, gap_warning, is_check_slot
from ordnung.ingest.intake import IntakeError
from ordnung.ingest.pipeline import STAGES, add_file, ingest_document, reprocess
from ordnung.ingest.plan import needs_check
from ordnung.ingest.verify import READING_INCOMPLETE, REASON_TEXT
from ordnung.llm.fake import FakeBackend
from ordnung.models import Item
from ordnung.secretary.triggers import Ledger, please_check
from test_api_support import Api, ApiRouter, api_for


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


async def test_an_upload_refused_while_its_pages_render_leaves_no_files(ctx: AppContext) -> None:
    """ROB G2: the original was stored before its pages were rendered; refused there (a page that can't be
    read), neither it nor its page folder stays on disk (where backups would copy them)."""
    broken = (
        b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Font >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
    )
    with pytest.raises(IntakeError, match="could not be read"):
        await add_file(ctx, broken, "odd.pdf")
    assert ctx.store.counts()["documents"] == 0
    assert [path for path in ctx.paths.files.rglob("*") if path.is_file()] == []
    assert list(ctx.paths.derived.iterdir()) == []
    kept = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")  # others are untouched
    assert ctx.store.get_document_file(kept.id) is not None and (ctx.paths.derived / kept.id).is_dir()


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
    paid = next(item for item in ctx.store.list_items(doc_id=document.id) if item.kind == "payment")
    router.payloads[TAX_LETTER.marker]["items"] = router.payloads[TAX_LETTER.marker]["items"][:1]
    await ingest_document(ctx, document.id, force=True)
    after = ctx.store.list_items(doc_id=document.id)
    assert [item.kind for item in after if not is_check_slot(item.slot_key)] == ["deadline"]
    assert paid.id not in {item.id for item in after}  # the stale to-do nobody edited is gone
    # the payment date the letter sets in so many words, left out by this reading, comes back as Ordnung's own
    # "Please check" to-do (ADR 0015, check:deadline) — never as the old to-do
    [check] = [item for item in after if is_check_slot(item.slot_key)]
    assert check.slot_key.split("#")[0] == DEADLINE_SLOT and check.kind == "payment" and needs_check(check)


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
# A scan's scanner text: search only (ADR 0020)
# --------------------------------------------------------------------------------------------------

#: A scanner's reading of the picture with a word the picture (and Claude's transcript) doesn't have
ODD_SCAN = ["Zebrafinkenweg 7 Quittungsnummer 0815", "Ablesung des Wasserzählers zum Jahresende"]


def _scan_file(ctx: AppContext, doc_id: str) -> Path:
    return ctx.store.paths.derived / doc_id / "scan-text.json"


async def test_a_private_scan_is_found_by_its_scanner_text(ctx: AppContext) -> None:
    """A searchable PDF kept private: no model sees it, its pages stay without text (the scanner's text
    is not the letter's words), yet the letter search finds it by that text — Ask's search doesn't."""
    document = await add_file(ctx, scanned_pdf(ocr=True), "scan.pdf", private=True)
    await ctx.worker.run_until_idle()
    assert backend(ctx).calls == []
    assert [page.text for page in ctx.store.list_pages(document.id)] == [""]
    assert ctx.store.scan_text_matches("Einkommensteuer") == {document.id}
    assert ctx.store.scan_text_pages(document.id) == [1]
    assert ctx.store.search("Einkommensteuer") == []
    stored = ctx.store.get_document(document.id)
    assert stored is not None and stored.status == "processed"
    assert ctx.store.get_document_text(document.id) == ""
    assert not stored.hidden_text and stored.warnings == []
    assert _scan_file(ctx, document.id).is_file()


async def test_the_scanner_text_never_reaches_a_prompt(ctx: AppContext) -> None:
    """A scan sent to Claude is read from its picture: no request carries the scanner's text, and once
    the transcript fills the page the scanner's text no longer counts for search."""
    document = await add_file(ctx, scanned_pdf(ocr=True, ocr_text=ODD_SCAN), "scan.pdf")
    assert await ctx.worker.run_until_idle() == 1
    calls = backend(ctx).calls
    assert [call.purpose for call in calls] == ["transcribe", "extract"]
    for call in calls:
        sent = f"{call.system}\n{call.prompt}\n" + "\n".join(str(item) for item in call.attachments)
        assert "Zebrafinken" not in sent and "Quittungsnummer" not in sent
    assert ctx.store.scan_text_pages(document.id) == []
    assert ctx.store.scan_text_matches("Zebrafinkenweg") == set()
    page = ctx.store.get_page(document.id, 1)
    assert page is not None and page.text_source == "transcript"


async def test_reading_again_keeps_the_scanner_text_current(ctx: AppContext) -> None:
    """Reading a letter again writes its scanner text afresh from the original; a letter whose pages
    all have text of their own keeps none (a stale file is removed)."""
    scan = await add_file(ctx, scanned_pdf(ocr=True), "scan.pdf", private=True)
    letter = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", private=True)
    await ctx.worker.run_until_idle()
    _scan_file(ctx, scan.id).write_text('{"version": 1, "pages": {"1": "veraltet"}}', "utf-8")
    _scan_file(ctx, letter.id).write_text('{"version": 1, "pages": {"1": "veraltet"}}', "utf-8")
    assert ctx.store.scan_text_matches("veraltet") == {scan.id}
    reprocess(ctx, scan.id)
    reprocess(ctx, letter.id)
    await ctx.worker.run_until_idle()
    assert ctx.store.scan_text_matches("veraltet") == set()
    assert ctx.store.scan_text_matches("Einkommensteuer") == {scan.id}
    assert not _scan_file(ctx, letter.id).exists()


async def test_older_scans_catch_up_without_touching_the_database(ctx: AppContext) -> None:
    """A scan stored before Ordnung kept a scanner's text gets it from its original: no model, no page
    row or letter changed; a letter in the trash or deleted meanwhile is skipped."""
    scan = await add_file(ctx, scanned_pdf(ocr=True), "scan.pdf", private=True)
    await ctx.worker.run_until_idle()
    _scan_file(ctx, scan.id).unlink()
    assert ctx.store.scan_text_missing() == [scan.id]
    before = (ctx.store.get_document(scan.id), ctx.store.list_pages(scan.id))
    pipeline.catch_up_scan_text(ctx.store, scan.id)
    assert ctx.store.scan_text_matches("Einkommensteuer") == {scan.id}
    assert ctx.store.scan_text_missing() == []
    assert (ctx.store.get_document(scan.id), ctx.store.list_pages(scan.id)) == before
    assert backend(ctx).calls == []
    _scan_file(ctx, scan.id).unlink()
    ctx.store.trash_document(scan.id)
    pipeline.catch_up_scan_text(ctx.store, scan.id)
    assert not _scan_file(ctx, scan.id).exists() and ctx.store.scan_text_missing() == []
    ctx.store.delete_document(scan.id)
    pipeline.catch_up_scan_text(ctx.store, scan.id)  # gone: nothing to do
    assert not (ctx.store.paths.derived / scan.id).exists()


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

OWN_NOTE = REASON_TEXT[READING_INCOMPLETE]
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


def gap_api_router(letter: Letter = GAP_LETTER) -> ApiRouter:
    router = ApiRouter()
    router.letters = (*router.letters, letter)
    router.payloads[letter.marker] = letter.extraction()
    return router


#: A notice that states the letter's date and its period: its quote leaves the engine nothing to doubt, so only
#: Ordnung's own grade keeps the to-do "Please check".
SERVED_LETTER = Letter(
    marker="Abfallgebühr",
    pages=(
        (
            "Landkreis Beispielhausen · Kreiskasse · Am Markt 2 · 12345 Beispielhausen",
            "SPECIMEN",
            "Beispielhausen, 15.09.2026",
            "Festsetzung der Abfallgebühr",
            "Sehr geehrter Herr Probe,",
            "wir setzen die Abfallgebühr für das Jahr 2026 auf 120,00 EUR fest.",
            "Rechtsbehelfsbelehrung",
            "Gegen den Bescheid vom 15.09.2026 kann innerhalb von zwei Wochen",
            "nach Zustellung Widerspruch erhoben werden.",
        ),
    ),
    payload={"kind": "other", "title": "Waste fee", "summary": "A fee.", "explanation": "Pay it."},
)


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


async def _served_check(api: Api) -> tuple[str, Item]:
    doc_id = (await api.upload(("abfall.pdf", SERVED_LETTER.pdf())))["documents"][0]["id"]
    await api.read_all()
    [check] = api.ctx.store.list_items(doc_id=doc_id)
    assert check.slot_key == CHECK_SLOT
    return doc_id, check


def _graded_as_ordnung_s_own(check: Item) -> bool:
    receipt = check.computation
    return receipt is not None and receipt.confidence == "low" and OWN_NOTE in receipt.warnings


async def test_a_recompute_keeps_ordnung_s_own_grade_until_the_person_confirms(data_dir: Path) -> None:
    """Review (tests 1): only Ordnung's own reason keeps the to-do ``low`` — its quote states the letter's date
    and the period. A recompute keeps it; once the person confirmed the date, a recompute no longer adds it."""
    async with api_for(data_dir, router=gap_api_router(SERVED_LETTER)) as api:
        doc_id, check = await _served_check(api)
        # served (Zustellung): from the letter's date with no delivery days — Tue 29 Sep
        assert check.due_date == "2026-09-29" and _graded_as_ordnung_s_own(check)
        assert (
            await api.client.put("/api/profile", json={"region": "HH", "onboarded": True})
        ).status_code == 200
        [check] = api.ctx.store.list_items(doc_id=doc_id)
        assert check.due_date == "2026-09-29" and _graded_as_ordnung_s_own(check) and needs_check(check)

        assert (await api.client.post(f"/api/items/{check.id}/confirm")).status_code == 200
        assert (
            await api.client.put("/api/profile", json={"region": "BE", "onboarded": True})
        ).status_code == 200
        [check] = api.ctx.store.list_items(doc_id=doc_id)
        assert check.due_date == "2026-09-29" and not needs_check(check)
        assert check.computation is not None and OWN_NOTE not in check.computation.warnings


@pytest.mark.parametrize(
    ("corrected", "due"),
    [
        ("2026-09-25", "2026-09-29"),  # later than the letter gives for itself: never later
        ("2026-10-20", "2026-09-29"),
        ("2026-09-10", "2026-09-24"),  # earlier: earlier
    ],
)
async def test_a_corrected_letter_date_never_moves_the_check_to_do_later(
    data_dir: Path, corrected: str, due: str
) -> None:
    """Review (A3): the person's letter date moves the to-do only earlier; a later one gets a note."""
    async with api_for(data_dir, router=gap_api_router(SERVED_LETTER)) as api:
        doc_id, check = await _served_check(api)
        response = await api.client.patch(f"/api/documents/{doc_id}", json={"doc_date": corrected})
        assert response.status_code == 200
        [check] = api.ctx.store.list_items(doc_id=doc_id)
        assert check.due_date == due and check.due_date <= "2026-09-29"
        assert check.computation is not None
        earlier_note = any(note.startswith("The letter gives") for note in check.computation.warnings)
        assert earlier_note == (corrected > "2026-09-15")


def _later_objection_router() -> ApiRouter:
    """The fee decision read with its sender and date, and an objection "three months" after notification."""
    router = gap_api_router()
    router.payloads[GAP_LETTER.marker] = {
        **copy.deepcopy(GAP_COMPLETE),
        "items": [
            {
                "kind": "deadline",
                "title": "Objection (Widerspruch)",
                "date": {
                    "type": "relative",
                    "amount": 3,
                    "unit": "months",
                    "anchor": "deemed_delivery",
                    "delivery_rule": "de_admin_post",
                    "nature": "objection",
                    "text": "three months after notification",
                },
                "quote": GAP_NOTICE,
            }
        ],
    }
    return router


async def test_an_objection_date_weeks_after_the_letter_s_notice_keeps_the_notice_s_date(
    data_dir: Path,
) -> None:
    """Spec 3.9(b): the reading's objection (Fri 18 Dec) is weeks after the letter's own one month (Mon 19 Oct):
    the earlier is kept and "Please check" — when read, recomputed, and after the person confirmed it."""
    async with api_for(data_dir, router=_later_objection_router()) as api:
        doc_id = (await api.upload(("bescheid.pdf", GAP_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        [objection] = api.ctx.store.list_items(doc_id=doc_id)
        assert (
            objection.slot_key != CHECK_SLOT and objection.due_date == "2026-10-19" and needs_check(objection)
        )
        assert objection.computation is not None and objection.computation.confidence == "low"
        document = api.ctx.store.get_document(doc_id)
        assert document is not None and document.status == "needs_review"
        assert (
            await api.client.put("/api/profile", json={"region": "HH", "onboarded": True})
        ).status_code == 200
        [objection] = api.ctx.store.list_items(doc_id=doc_id)
        assert objection.due_date == "2026-10-19" and needs_check(objection)
        assert (await api.client.post(f"/api/items/{objection.id}/confirm")).status_code == 200
        assert (
            await api.client.put("/api/profile", json={"region": "BE", "onboarded": True})
        ).status_code == 200
        [objection] = api.ctx.store.list_items(doc_id=doc_id)
        assert objection.due_date == "2026-10-19" and not needs_check(objection)


def _letter(marker: str, *lines: str, payload: dict[str, Any] | None = None) -> Letter:
    """A synthetic letter dated 15.09.2026 (or as its lines say) with ``payload`` as its reading."""
    return Letter(
        marker=marker,
        pages=(lines,),
        payload=payload
        or {"kind": "other", "title": "Letter", "summary": "A letter.", "explanation": "Read it."},
    )


def _router(*letters: Letter) -> ApiRouter:
    router = ApiRouter()
    router.letters = (*letters, *router.letters)
    for letter in letters:
        router.payloads[letter.marker] = letter.extraction()
    return router


#: Two dates for one payment (review round 2, R2UX-2): the earlier is kept, and stays once confirmed.
TWO_PAY = _letter(
    "Zweifachzahlung",
    "Stadt Beispielhausen · Stadtkasse · Rathausplatz 1 · 12345 Beispielhausen",
    "SPECIMEN Zweifachzahlung",
    "Datum: 15.09.2026",
    "Gebührenbescheid",
    "Sehr geehrte Frau Probe,",
    "Die Gebühr von 85,00 EUR ist bis zum 20.10.2026 zu zahlen.",
    "Zahlbar bis 13.10.2026.",
    payload={
        "kind": "authority_letter",
        "title": "Fee",
        "summary": "A fee.",
        "explanation": "Pay it.",
        "sender": {"name": "Stadt Beispielhausen", "kind": "authority"},
        "document_date": "2026-09-15",
        "items": [
            {
                "kind": "payment",
                "title": "Pay the fee",
                "amount": 85.0,
                "date": {"type": "fixed", "date": "2026-10-20", "nature": "payment"},
                "quote": "Die Gebühr von 85,00 EUR ist bis zum 20.10.2026 zu zahlen.",
            }
        ],
    },
)


async def test_a_confirmed_to_do_keeps_the_earlier_of_its_two_dates_when_recomputed(data_dir: Path) -> None:
    """UX review 2, R2UX-2 (older than the reading check): confirming the earlier date, then changing the region
    or entering the arrival, never moves it to the later one."""
    async with api_for(data_dir, router=_router(TWO_PAY)) as api:
        doc_id = (await api.upload(("gebuehr.pdf", TWO_PAY.pdf())))["documents"][0]["id"]
        await api.read_all()
        [pay] = api.ctx.store.list_items(doc_id=doc_id)
        assert pay.due_date == "2026-10-13"
        assert (await api.client.post(f"/api/items/{pay.id}/confirm")).status_code == 200
        assert (
            await api.client.put("/api/profile", json={"region": "HH", "onboarded": True})
        ).status_code == 200
        [pay] = api.ctx.store.list_items(doc_id=doc_id)
        assert pay.due_date == "2026-10-13" and not needs_check(pay)
        response = await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-18"})
        assert response.status_code == 200
        [pay] = api.ctx.store.list_items(doc_id=doc_id)
        assert pay.due_date == "2026-10-13" and not needs_check(pay)


#: A decision without any date of its own: the check to-do is undated until the person enters the date.
UNDATED_DECISION = _letter(
    "Ohnedatum",
    "Stadt Beispielhausen · Ordnungsamt · Rathausplatz 1 · 12345 Beispielhausen",
    "SPECIMEN Ohnedatum",
    "Bescheid über eine Sondernutzungsgebühr",
    "Sehr geehrte Frau Probe,",
    "für die Nutzung der Gehwegfläche setzen wir eine Gebühr von 85,00 EUR fest.",
    "Rechtsbehelfsbelehrung",
    "Gegen diesen Gebührenbescheid können Sie binnen eines Monats",
    "nach seiner Bekanntgabe Widerspruch einlegen.",
)


async def test_the_incomplete_reading_s_warning_follows_its_to_do(data_dir: Path) -> None:
    """UX review 2, R2UX-3 and R2UX-4: once the person enters the letter's date the warning says the deadline was
    added (not "couldn't work it out"); once they confirm the to-do, the warning goes."""
    async with api_for(data_dir, router=_router(UNDATED_DECISION)) as api:
        doc_id = (await api.upload(("ohnedatum.pdf", UNDATED_DECISION.pdf())))["documents"][0]["id"]
        await api.read_all()
        [check] = api.ctx.store.list_items(doc_id=doc_id)
        assert check.slot_key == CHECK_SLOT and check.due_date is None
        document = api.ctx.store.get_document(doc_id)
        assert document is not None and gap_warning("empty", "undated") in document.warnings
        assert (
            await api.client.patch(f"/api/documents/{doc_id}", json={"doc_date": "2026-09-15"})
        ).status_code == 200
        [check] = api.ctx.store.list_items(doc_id=doc_id)
        assert check.due_date is not None and check.due_date <= "2026-10-19"
        document = api.ctx.store.get_document(doc_id)
        assert document is not None and gap_warning("empty", "dated") in document.warnings
        assert gap_warning("empty", "undated") not in document.warnings
        assert (await api.client.post(f"/api/items/{check.id}/confirm")).status_code == 200
        document = api.ctx.store.get_document(doc_id)
        assert document is not None and document.status == "processed"
        assert not any(GAP_WARNING.match(warning) for warning in document.warnings)


FINE_NOTICE = (
    "Gegen diesen Bußgeldbescheid können Sie innerhalb von zwei Wochen nach Zustellung schriftlich oder zur "
    "Niederschrift bei der Bußgeldstelle Einspruch einlegen."
)


def _fine(months: int | None) -> Letter:
    """A fine dated 01.09.2026 and a complete reading of it (two weeks after service, or a planted period)."""
    spec = (
        {"type": "relative", "amount": 2, "unit": "weeks", "anchor": "receipt", "delivery_rule": "none"}
        if months is None
        else {
            "type": "relative",
            "amount": months,
            "unit": "months",
            "anchor": "receipt",
            "delivery_rule": "none",
        }
    )
    return _letter(
        f"Bussgeldprobe{months or 0}",
        "Stadt Beispielhausen · Bußgeldstelle · Rathausplatz 1 · 12345 Beispielhausen",
        f"SPECIMEN Bussgeldprobe{months or 0}",
        "Datum: 01.09.2026",
        "Bußgeldbescheid",
        "Sehr geehrter Herr Probe,",
        "wegen Überschreitung der zulässigen Höchstgeschwindigkeit wird gegen Sie eine Geldbuße von 70,00 EUR festgesetzt.",
        "Rechtsbehelfsbelehrung",
        "Gegen diesen Bußgeldbescheid können Sie innerhalb von zwei Wochen nach Zustellung schriftlich oder zur",
        "Niederschrift bei der Bußgeldstelle Einspruch einlegen.",
        payload={
            "kind": "fine",
            "title": "Speeding fine",
            "summary": "s",
            "explanation": "e",
            "sender": {"name": "Stadt Beispielhausen – Bußgeldstelle", "kind": "authority"},
            "document_date": "2026-09-01",
            "remedy": {"type": "einspruch", "quote": FINE_NOTICE},
            "items": [
                {
                    "kind": "deadline",
                    "title": "Objection (Einspruch)",
                    "date": {**spec, "nature": "objection"},
                    "quote": FINE_NOTICE,
                }
            ],
        },
    )


@pytest.mark.parametrize(("months", "due", "flagged"), [(None, "2026-10-05", False), (3, "2026-10-05", True)])
async def test_the_letter_s_notice_never_overrides_the_service_date_the_person_entered(
    data_dir: Path, months: int | None, due: str, flagged: bool
) -> None:
    """False positives F1: the person enters the yellow envelope's date (20.09, 19 days after the letter's): two
    weeks from service is Mon 5 Oct, never the letter's date's passed 15 Sep — and a planted three months is still
    pulled to 5 Oct, with "Please check" on the letter."""
    letter = _fine(months)
    async with api_for(data_dir, router=_router(letter)) as api:
        doc_id = (await api.upload(("fine.pdf", letter.pdf())))["documents"][0]["id"]
        await api.read_all()
        response = await api.client.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-20"})
        assert response.status_code == 200
        [objection] = api.ctx.store.list_items(doc_id=doc_id)
        assert objection.due_date == due and needs_check(objection) is flagged
        document = api.ctx.store.get_document(doc_id)
        assert document is not None and (document.status == "needs_review") is flagged


async def test_the_check_s_own_to_do_never_gets_the_notice_beside_it_when_recomputed(data_dir: Path) -> None:
    """R2T-9: the check to-do is stored as read, so a recompute meets it with the reading's to-dos; it gets no
    second date. (Its own date is the notice's, so this can't tell whether ``with_notice`` skips it: the
    ``CHECK_SLOT`` filter there is defensive — tests review 3, R3T-11.)"""
    async with api_for(data_dir, router=gap_api_router()) as api:
        doc_id = (await api.upload(("bescheid.pdf", GAP_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        assert (
            await api.client.put("/api/profile", json={"region": "HH", "onboarded": True})
        ).status_code == 200
        [check] = api.ctx.store.list_items(doc_id=doc_id)
        assert check.slot_key == CHECK_SLOT and check.computation is not None
        assert not any("two dates" in note for note in check.computation.warnings)


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


#: A decision whose only date is months before the day it is read (the pinned 25.09.2026).
OLD_DECISION = Letter(
    marker="Altbescheid",
    pages=(
        (
            "Stadt Beispielhausen · Ordnungsamt · Rathausplatz 1 · 12345 Beispielhausen",
            "SPECIMEN Altbescheid",
            "Datum: 02.06.2026",
            "Bescheid über eine Sondernutzungsgebühr",
            "Sehr geehrte Frau Probe,",
            "für die Nutzung der Gehwegfläche setzen wir eine Gebühr von 85,00 EUR fest.",
            "Rechtsbehelfsbelehrung",
            "Gegen diesen Gebührenbescheid können Sie binnen eines Monats",
            "nach seiner Bekanntgabe Widerspruch einlegen.",
        ),
    ),
    payload={"kind": "other", "title": "Letter", "summary": "A letter.", "explanation": "Read it."},
)


async def test_a_letter_read_months_after_its_only_date_gets_an_undated_check(data_dir: Path) -> None:
    """Tests review 3, R3T-8: the pipeline hands the check the day the letter is read, so a start resting on one
    date months before it is none — never an overdue to-do."""
    async with api_for(data_dir, router=gap_api_router(OLD_DECISION)) as api:
        doc_id = (await api.upload(("alt.pdf", OLD_DECISION.pdf())))["documents"][0]["id"]
        await api.read_all()
        [check] = api.ctx.store.list_items(doc_id=doc_id)
        assert check.slot_key == CHECK_SLOT and check.due_date is None


async def test_reading_again_after_the_person_confirmed_the_check_brings_no_warning_back(
    data_dir: Path,
) -> None:
    """UX review 3, R3UX-3(b): "Read again" after the person confirmed Ordnung's own to-do: its warning stays
    gone (a first read still says it)."""
    async with api_for(data_dir, router=gap_api_router()) as api:
        doc_id = (await api.upload(("bescheid.pdf", GAP_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        document = api.ctx.store.get_document(doc_id)
        assert document is not None and any(GAP_WARNING.match(w) for w in document.warnings)
        [check] = api.ctx.store.list_items(doc_id=doc_id)
        assert (await api.client.post(f"/api/items/{check.id}/confirm")).status_code == 200
        assert (await api.client.post(f"/api/documents/{doc_id}/reprocess")).status_code == 202
        await api.read_all()
        document = api.ctx.store.get_document(doc_id)
        assert document is not None and not any(GAP_WARNING.match(w) for w in document.warnings)


async def test_a_confirmed_to_do_is_never_listed_as_unsure_in_the_please_check_idea(data_dir: Path) -> None:
    """R3UX-4: once the person confirmed the check to-do, the Idea no longer says the reading came back
    incomplete nor lists it (the letter's other unsure to-do keeps it in review)."""
    pay = {
        "kind": "payment",
        "title": "Pay the fee",
        "amount": 85.0,
        "date": {"type": "fixed", "date": "2026-10-13", "nature": "payment"},
        "quote": "Die Gebühr ist bis zum 13.10.2026 zu zahlen.",
    }
    lines = tuple("SPECIMEN Zweitesprobe" if line == "SPECIMEN" else line for line in GAP_LETTER.pages[0])
    letter = Letter(
        marker="Zweitesprobe",
        pages=(lines,),
        payload={**GAP_LETTER.payload, "kind": "authority_letter", "items": [pay]},
    )
    async with api_for(data_dir, router=gap_api_router(letter)) as api:
        doc_id = (await api.upload(("bescheid.pdf", letter.pdf())))["documents"][0]["id"]
        await api.read_all()
        check = next(item for item in api.ctx.store.list_items(doc_id=doc_id) if item.slot_key == CHECK_SLOT)
        assert (await api.client.post(f"/api/items/{check.id}/confirm")).status_code == 200
        ideas = [
            idea for idea in please_check(Ledger(api.ctx.store, clock.today())) if idea.refs[0].id == doc_id
        ]
        assert ideas and "came back incomplete" not in ideas[0].body
        assert check.id not in {ref.id for ref in ideas[0].refs}
