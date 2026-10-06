"""Traces of real readings through the pipeline with the FakeBackend: the span tree of a text letter and
of a photo letter, the repair link, failed and paused readings, reading again and comparing, how many
readings are kept, delete-means-delete, and that no letter text ever reaches a span."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import (
    APPOINTMENT_LETTER,
    TAX_IBAN,
    TAX_LETTER,
    TAX_OBJECTION_QUOTE,
    TAX_PAYMENT_QUOTE,
    TODAY,
    Router,
    record_events,
)
from helpers_docs import photo
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.ingest.gaps import CHECK_SLOT
from ordnung.ingest.pipeline import add_file, ingest_document, reprocess
from ordnung.ingest.verify import READING_INCOMPLETE
from ordnung.llm.base import ClaudeAuthError, ClaudeNotInstalled, ClaudeRateLimited, LLMRequest
from ordnung.llm.fake import FakeBackend
from ordnung.models import DocumentTrace, TraceSpan
from ordnung.trace.compare import compare_traces
from ordnung.trace.runs import FAILURES, INTERRUPTIONS, KEPT_READINGS
from ordnung.trace.view import document_trace


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
    context = build_context(data_dir, backend_obj=FakeBackend(router))
    yield context
    context.close()


async def read(ctx: AppContext, data: bytes, name: str) -> str:
    document = await add_file(ctx, data, name)
    await ctx.worker.run_until_idle()
    return document.id


def steps(trace: DocumentTrace) -> dict[str, TraceSpan]:
    return {span.key: span for span in trace.spans}


def top_level(trace: DocumentTrace) -> list[str]:
    return [span.key for span in trace.spans if span.depth == 1]


# --------------------------------------------------------------------------------------------------
# a text letter
# --------------------------------------------------------------------------------------------------


async def test_a_text_letter_has_every_step_in_the_order_it_ran(ctx: AppContext) -> None:
    doc_id = await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    trace = document_trace(ctx.store, doc_id)
    assert trace.run is not None and trace.run.reading == 1 and trace.run.trigger == "read"
    assert trace.run.status == "ok" and trace.run.result == "processed" and trace.run.timing == "measured"
    assert top_level(trace) == [
        "run/ocr:text",
        "run/model:extract",
        "run/verify:quotes",
        "run/link:sender",
        "run/rules:dates",
        "run/link:links",
        "run/plan:plan",
    ]
    by_key = steps(trace)
    root = by_key["run"]
    outcome = {key: root.attributes[key] for key in ("pages", "items", "text_mode", "private")}
    assert outcome == {"pages": 2, "items": 2, "text_mode": "text", "private": False}
    assert by_key["run/ocr:text"].attributes["text_pages"] == 2
    assert by_key["run/ocr:text"].attributes["hidden_text"] is False
    # every step lies inside the reading
    for span in trace.spans:
        assert 0 <= span.start_ms and span.start_ms + span.duration_ms <= root.duration_ms + 0.01


async def test_a_model_step_is_joined_with_its_usage_log_row(ctx: AppContext) -> None:
    doc_id = await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    trace = document_trace(ctx.store, doc_id)
    extract = steps(trace)["run/model:extract"]
    call = extract.call
    assert call is not None and call.span_id == extract.id
    assert (call.purpose, call.prompt_name, call.stage, call.outcome) == (
        "extract",
        "extract",
        "extract",
        "ok",
    )
    assert trace.run is not None and call.job_id == trace.run.job_id is not None
    assert call.request_key and call.prompt_version
    assert call.served_model == "sonnet" and call.doc_ids == [doc_id]
    assert extract.attributes["call_id"] == call.id and extract.attributes["outcome"] == "ok"
    assert (
        trace.run is not None and trace.run.model_calls == 1 and trace.run.input_tokens == call.input_tokens
    )


async def test_quotes_dates_links_and_plan_describe_what_code_decided(ctx: AppContext) -> None:
    doc_id = await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    trace = document_trace(ctx.store, doc_id)
    items = {item.kind: item for item in ctx.store.list_items(doc_id=doc_id)}
    objection, payment = items["deadline"], items["payment"]
    by_key = steps(trace)

    quote = by_key[f"run/verify:quotes/verify:item:{objection.slot_key}"]
    assert quote.attributes["grounding"] == "verified" and quote.attributes["page"] == 2
    assert quote.attributes["score"] >= 90 and quote.attributes["consistent"] is True
    assert quote.ref is not None and quote.ref.id == objection.id and quote.label == objection.title
    paid = by_key[f"run/verify:quotes/verify:item:{payment.slot_key}"].attributes
    assert paid["digit_groups"] == 2 and paid["digits_matched"] is True  # 1.234,56 and 15.10.2026
    assert by_key["run/verify:quotes"].attributes["verified"] >= 3

    date = by_key[f"run/rules:dates/rules:item:{objection.slot_key}"]
    assert date.attributes["due_date"] == objection.due_date == "2026-10-21"
    assert "ao_122_2_1" in date.attributes["rule_ids"] and date.attributes["confidence"] == "high"
    assert date.attributes["spec"]["anchor"] == "deemed_delivery" and "text" not in date.attributes["spec"]
    assert date.ref is not None and date.ref.id == objection.id

    sender = by_key["run/link:sender"]
    assert sender.attributes["decision"] == "new" and sender.label == "Finanzamt Musterstadt"
    assert sender.ref is not None and sender.ref.type == "party"
    thread = by_key["run/link:links/link:thread"]
    assert thread.attributes["decision"] == "new" and thread.attributes["reference_kind"] == "steuernummer"
    assert by_key["run/link:links/link:payment"].attributes["iban_added"] is True

    planned = by_key[f"run/plan:plan/plan:item:{objection.slot_key}"]
    assert planned.attributes["action"] == "created" and planned.attributes["item_id"] == objection.id
    assert by_key["run/plan:plan"].attributes["status"] == "processed"


async def test_a_known_sender_is_matched_by_its_identifier(ctx: AppContext, router: Router) -> None:
    await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    payload = TAX_LETTER.extraction()
    payload["sender"]["name"] = "FA Musterstadt"
    router.payloads[TAX_LETTER.marker] = payload
    doc_id = (await add_file(ctx, TAX_LETTER.pdf() + b"\n%copy", "zweit.pdf")).id
    await ctx.worker.run_until_idle()
    sender = steps(document_trace(ctx.store, doc_id))["run/link:sender"].attributes
    assert sender["decision"] == "identifier" and sender["reference_kind"] == "steuernummer"


# --------------------------------------------------------------------------------------------------
# a photo letter
# --------------------------------------------------------------------------------------------------


async def test_a_photo_letter_is_transcribed_page_by_page_in_parallel(ctx: AppContext) -> None:
    document = await add_file(
        ctx, photo("JPEG", size=(600, 800)), "page1.jpg", combine_with=[photo("PNG", size=(640, 800))]
    )
    await ctx.worker.run_until_idle()
    trace = document_trace(ctx.store, document.id)
    by_key = steps(trace)
    assert top_level(trace)[:3] == ["run/ocr:text", "run/ocr:transcribe", "run/model:extract"]
    group = by_key["run/ocr:transcribe"]
    assert group.stage == "transcribe" and group.attributes["pages"] == 2
    pages = [by_key[f"run/ocr:transcribe/model:page:{n}"] for n in (1, 2)]
    for page, span in enumerate(pages, start=1):
        assert span.call is not None and span.call.stage == "transcribe" and span.call.purpose == "transcribe"
        assert span.attributes["page"] == page and span.attributes["legible"] is True
        assert span.attributes["chars"] == len(APPOINTMENT_LETTER.transcript())
        assert span.call.pages_sent == 1
    assert by_key["run/ocr:text"].attributes["to_transcribe"] == 2
    assert trace.run is not None and trace.run.model_calls == 3
    quotes = [s for s in trace.spans if s.kind == "verify" and s.attributes.get("target") == "item"]
    assert quotes and {s.attributes["grounding"] for s in quotes} == {"model_read"}


# --------------------------------------------------------------------------------------------------
# repairs and failures
# --------------------------------------------------------------------------------------------------


def invalid_first(router: Router, *, repair_valid: bool = True) -> Any:
    def respond(req: LLMRequest) -> Any:
        if req.purpose == "extract" and (req.prompt_name == "extract" or not repair_valid):
            return {"items": "not a list", "kind": 42}
        return router(req)

    return respond


async def test_a_repair_names_the_call_it_retried(data_dir: Path, router: Router) -> None:
    ctx = build_context(data_dir, backend_obj=FakeBackend(invalid_first(router)))
    try:
        doc_id = await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
        trace = document_trace(ctx.store, doc_id)
    finally:
        ctx.close()
    by_key = steps(trace)
    first, repair = by_key["run/model:extract"], by_key["run/model:extract_repair"]
    assert first.call is not None and repair.call is not None
    assert (first.call.outcome, repair.call.outcome) == ("invalid", "repaired")
    assert repair.call.repair_of == first.call.id and repair.attributes["repair_of"] == first.call.id
    assert repair.call.prompt_name == "extract_repair" and repair.call.prompt_version.endswith(".r1")
    assert first.attributes["problems"] >= 1
    assert {"items", "kind"} <= set(first.attributes["problem_fields"])  # where, never what the model wrote
    assert trace.run is not None and trace.run.repairs == 1 and trace.run.result == "processed"


async def test_a_reading_that_fails_keeps_its_trace_with_a_code_never_the_message(
    data_dir: Path, router: Router
) -> None:
    ctx = build_context(data_dir, backend_obj=FakeBackend(invalid_first(router, repair_valid=False)))
    try:
        doc_id = await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
        document = ctx.store.get_document(doc_id)
        trace = document_trace(ctx.store, doc_id)
        stored = stored_spans(ctx)
    finally:
        ctx.close()
    assert document is not None and document.status == "failed" and document.error
    assert trace.run is not None and trace.run.status == "error" and trace.run.ended == "failed"
    # the person's message quotes what the model answered; the trace keeps only the kind of failure
    assert trace.run.error == FAILURES["unusable_answer"]
    assert steps(trace)["run"].error == "unusable_answer" and document.error not in stored
    by_key = steps(trace)
    assert by_key["run/model:extract_repair"].status == "error"
    assert by_key["run/model:extract_repair"].error == "ExtractionError"
    assert by_key["run/model:extract_repair"].call is not None
    assert by_key["run/model:extract_repair"].call.outcome == "failed"
    assert "run/verify:quotes" not in by_key


async def test_a_paused_reading_says_so(ctx: AppContext, router: Router) -> None:
    router.errors["extract"] = lambda: ClaudeRateLimited("Usage limit reached", reset_at=None)
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    await ctx.worker.run_until_idle()
    trace = document_trace(ctx.store, document.id)
    assert (
        trace.run is not None and trace.run.error == INTERRUPTIONS["paused"] and trace.run.status == "error"
    )
    assert trace.run.ended == "paused" and steps(trace)["run"].error == "paused"
    assert steps(trace)["run/model:extract"].attributes["outcome"] == "failed"


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ClaudeNotInstalled("The “claude” command was not found."), "paused_not_installed"),
        (ClaudeAuthError("Claude Code is not signed in."), "paused_not_signed_in"),
    ],
    ids=["not-installed", "signed-out"],
)
async def test_a_reading_waiting_for_claude_is_paused_never_failed(
    ctx: AppContext, router: Router, error: Exception, code: str
) -> None:
    """Claude not installed or not signed in pauses the reading like a usage limit: the pipeline puts the
    letter back (``queued``, no error), announces no failure, and the trace ends ``paused`` with why — so the
    letter is never shown as failed while it waits."""
    router.errors["extract"] = lambda: error
    events = record_events(ctx.bus)
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    with pytest.raises(type(error)):
        await ingest_document(ctx, document.id)
    stored = ctx.store.get_document(document.id)
    assert stored is not None and (stored.status, stored.error) == ("queued", None)
    assert not [data for kind, data in events if kind == "job.progress" and data.get("status") == "failed"]
    trace = document_trace(ctx.store, document.id)
    assert trace.run is not None and trace.run.ended == "paused" and steps(trace)["run"].error == code
    assert trace.run.error == INTERRUPTIONS[code] and "read once Claude is ready" in trace.run.error


async def test_a_private_letter_has_no_model_step(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", private=True)
    await ctx.worker.run_until_idle()
    trace = document_trace(ctx.store, document.id)
    assert top_level(trace) == ["run/ocr:text"]
    assert trace.run is not None and trace.run.model_calls == 0
    assert steps(trace)["run"].attributes["private"] is True


async def test_a_letter_waiting_from_the_folder_ends_its_reading_held(ctx: AppContext) -> None:
    """Integration of the trace with the one inbox: a held letter is only stored on this computer — its
    reading has no model step and ends ``held`` (the letter page says it waits), never "processed"."""
    document = await add_file(ctx, TAX_LETTER.pdf(), "scan.pdf", hold=True)
    await ctx.worker.run_until_idle()
    trace = document_trace(ctx.store, document.id)
    assert top_level(trace) == ["run/ocr:text"]
    assert trace.run is not None and trace.run.model_calls == 0 and trace.run.result == "held"
    assert steps(trace)["run"].attributes["private"] is True


# --------------------------------------------------------------------------------------------------
# reading again
# --------------------------------------------------------------------------------------------------


async def test_reading_again_is_a_new_numbered_reading_and_compares_step_by_step(
    ctx: AppContext, router: Router
) -> None:
    doc_id = await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    first = document_trace(ctx.store, doc_id)
    payload = TAX_LETTER.extraction()
    payload["items"][1]["date"]["date"] = "2026-10-16"
    payload["items"][1]["date"]["text"] = "bis zum 16.10.2026"
    router.payloads[TAX_LETTER.marker] = payload
    reprocess(ctx, doc_id)
    await ctx.worker.run_until_idle()
    second = document_trace(ctx.store, doc_id)
    assert second.run is not None and first.run is not None
    assert (second.run.reading, second.run.trigger) == (2, "read_again")
    assert [run.reading for run in second.runs] == [2, 1]
    assert second.run.trace_id != first.run.trace_id

    comparison = compare_traces(document_trace(ctx.store, doc_id, first.run.trace_id), second)
    fields = {(change.key.rsplit("/", 1)[-1], change.field): change for change in comparison.changes}
    payment = next(item for item in ctx.store.list_items(doc_id=doc_id) if item.kind == "payment")
    change = fields[(f"rules:item:{payment.slot_key}", "due_date")]
    assert (change.before, change.after) == ("2026-10-15", "2026-10-16")
    assert change.label == payment.title
    # the payment's quote no longer states the date it now carries
    assert (f"verify:item:{payment.slot_key}", "consistent") in fields
    assert not any(change.field in ("duration_ms", "score") for change in comparison.changes)


async def test_the_newest_readings_are_kept(ctx: AppContext) -> None:
    doc_id = await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    for _ in range(KEPT_READINGS + 1):
        reprocess(ctx, doc_id)
        await ctx.worker.run_until_idle()
    trace = document_trace(ctx.store, doc_id)
    assert [run.reading for run in trace.runs] == list(range(KEPT_READINGS + 2, 1, -1))[:KEPT_READINGS]
    assert ctx.store.count_trace_runs() == KEPT_READINGS


# --------------------------------------------------------------------------------------------------
# privacy
# --------------------------------------------------------------------------------------------------


def stored_spans(ctx: AppContext) -> str:
    rows = ctx.store._conn().execute("SELECT * FROM trace_spans").fetchall()
    return json.dumps([dict(row) for row in rows], ensure_ascii=False)


async def test_no_letter_text_ever_reaches_a_span(ctx: AppContext) -> None:
    doc_id = await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    stored = stored_spans(ctx)
    document = ctx.store.get_document(doc_id)
    assert document is not None and document.title and stored
    secrets = [
        TAX_OBJECTION_QUOTE,
        TAX_PAYMENT_QUOTE,
        "innerhalb eines Monats",
        "Einkommensteuer",
        "Musterstadt",
        "Rivera",
        "123/456/78901",
        TAX_IBAN,
        document.title,
        "Pay the income tax",
        "§ 355 AO",
        "1.234,56",
    ]
    for secret in secrets:
        assert secret not in stored, secret


async def test_a_reading_that_came_back_incomplete_says_so_in_codes(ctx: AppContext, router: Router) -> None:
    """``ingest/gaps.py``: the "Check quotes" step says why the reading was incomplete and which to-do code filed
    for it; the to-do's own quote step lists its reason — codes only, never the notice it was worked out from."""
    router.payloads[TAX_LETTER.marker] = {
        "kind": "other",
        "title": "Letter",
        "summary": "s",
        "explanation": "e",
    }
    doc_id = await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    by_key = steps(document_trace(ctx.store, doc_id))
    checked = by_key["run/verify:quotes"].attributes
    assert (checked["reading_gap"], checked["check_item"]) == ("empty", "dated")
    assert checked["needs_check"] == 1
    quote = by_key[f"run/verify:quotes/verify:item:{CHECK_SLOT}"]
    assert READING_INCOMPLETE in quote.attributes["reasons"] and quote.attributes["consistent"] is False
    [check] = ctx.store.list_items(doc_id=doc_id)
    assert quote.ref is not None and quote.ref.id == check.id
    stored = stored_spans(ctx)
    for secret in (TAX_OBJECTION_QUOTE, "innerhalb eines Monats", "Musterstadt", check.title):
        assert secret not in stored, secret


async def test_deleting_the_letter_deletes_its_traces_and_its_calls_keys(ctx: AppContext) -> None:
    doc_id = await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    other = await read(ctx, APPOINTMENT_LETTER.pdf(), "termin.pdf")
    assert ctx.store.trace_runs(doc_id) and ctx.store.trace_runs(other)
    assert ctx.store.delete_document(doc_id)
    assert ctx.store.trace_runs(doc_id) == []
    assert (
        ctx.store._conn()
        .execute("SELECT COUNT(*) FROM trace_spans WHERE doc_id = ?", (doc_id,))
        .fetchone()[0]
        == 0
    )
    calls = ctx.store.usage_stats().recent
    mine = [call for call in calls if call.doc_ids == [] and call.purpose == "extract"]
    assert mine and all(
        call.request_key is None and call.span_id is None and call.job_id is None for call in mine
    )
    kept = [call for call in calls if call.doc_ids == [other]]
    assert kept and all(call.request_key and call.span_id for call in kept)
    assert ctx.store.trace_runs(other), "another letter's trace stays"


async def test_a_trashed_letter_keeps_its_trace_until_it_is_deleted(ctx: AppContext) -> None:
    doc_id = await read(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    ctx.store.trash_document(doc_id)
    assert document_trace(ctx.store, doc_id).run is not None
    spans, _ = ctx.store.export_traces()
    assert spans == [], "the export leaves out letters in the trash"
