"""Which readings of a letter a trace keeps, and what they may hold: a reading's number is reserved
when it starts (a lost trace or two readings at once never share one), interrupted attempts never
push out a good reading or become the default comparison, a letter deleted while its call is under
way leaves no key or cached answer, the time spent waiting for Claude counts parallel calls once, and
an older reading's key facts are not named after the newest one's."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import APPOINTMENT_LETTER, TAX_LETTER, TODAY, Router
from helpers_docs import photo
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.ingest import pipeline
from ordnung.ingest.pipeline import add_file, reprocess
from ordnung.llm.base import ClaudeRateLimited, LLMRequest, LLMResponse
from ordnung.llm.fake import FakeBackend
from ordnung.models import TraceSpanRecord
from ordnung.trace.compare import compare_base
from ordnung.trace.runs import INTERRUPTIONS, KEPT_READINGS, finish_trace, recover_readings, start_trace
from ordnung.trace.spans import trace_id_for
from ordnung.trace.view import busy_ms, document_trace


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


async def read(ctx: AppContext) -> str:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    await ctx.worker.run_until_idle()
    return document.id


async def read_again(ctx: AppContext, doc_id: str) -> None:
    reprocess(ctx, doc_id)
    await ctx.worker.run_until_idle()


# --------------------------------------------------------------------------------------------------
# a reading's number and id
# --------------------------------------------------------------------------------------------------


async def test_a_reading_whose_trace_was_lost_never_lends_its_calls_to_the_next(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    with monkeypatch.context() as patched:
        patched.setattr(ctx.store, "save_trace", _fail)
        await ctx.worker.run_until_idle()
    await read_again(ctx, document.id)
    trace = document_trace(ctx.store, document.id)
    assert trace.run is not None and [run.reading for run in trace.runs] == [2]
    assert (trace.run.model_calls, trace.run.cost_usd) == (1, 0.001), "only its own call"


def _fail(*args: object, **kwargs: object) -> int:
    raise RuntimeError("disk full")


async def test_a_reading_the_process_did_not_finish_is_stopped_at_the_next_start(ctx: AppContext) -> None:
    doc_id = await read(ctx)
    killed = start_trace(ctx.store, doc_id, job_id=None, again=True, recorded=False)
    assert [run.reading for run in document_trace(ctx.store, doc_id).runs] == [1], "running: not shown"
    assert recover_readings(ctx.store) == 1
    await read_again(ctx, doc_id)
    runs = document_trace(ctx.store, doc_id).runs
    assert [(run.reading, run.ended) for run in runs] == [(3, "done"), (2, "stopped"), (1, "done")]
    assert runs[1].trace_id == killed.trace_id and runs[1].error == INTERRUPTIONS["stopped"]
    assert runs[1].model_calls == 0 and runs[0].model_calls == 1


async def test_two_readings_of_one_letter_at_once_get_their_own_numbers(ctx: AppContext) -> None:
    doc_id = await read(ctx)
    # the worker never runs two readings of one letter at once (its jobs wait for each other): read directly
    await asyncio.gather(*(pipeline.ingest_document(ctx, doc_id, force=True) for _ in range(2)))
    runs = document_trace(ctx.store, doc_id).runs
    assert [run.reading for run in runs] == [3, 2, 1]
    assert [run.model_calls for run in runs] == [1, 1, 1]
    assert len({run.trace_id for run in runs}) == 3


async def test_measured_trace_ids_never_repeat_and_recorded_ones_do(ctx: AppContext) -> None:
    doc_id = await read(ctx)
    measured = [start_trace(ctx.store, doc_id, job_id=None, again=True, recorded=False) for _ in range(2)]
    assert measured[0].trace_id != measured[1].trace_id
    assert measured[0].trace_id != trace_id_for(doc_id, 2), "a measured id is not the letter's hash"
    recorded = start_trace(ctx.store, doc_id, job_id=None, again=True, recorded=True)
    assert recorded.trace_id == trace_id_for(doc_id, 4), "the demo rebuilds the same ids"


# --------------------------------------------------------------------------------------------------
# interrupted readings
# --------------------------------------------------------------------------------------------------


async def _paused(ctx: AppContext, doc_id: str, times: int) -> None:
    async def limited(req: LLMRequest) -> LLMResponse:
        raise ClaudeRateLimited("limit", reset_at=None)

    answer = ctx.llm.backend.complete
    ctx.llm.backend.complete = limited  # type: ignore[method-assign]
    try:
        for _ in range(times):
            with pytest.raises(ClaudeRateLimited):
                await pipeline.ingest_document(ctx, doc_id, force=True)
    finally:
        ctx.llm.backend.complete = answer  # type: ignore[method-assign]


async def test_pauses_never_push_out_a_good_reading(ctx: AppContext) -> None:
    doc_id = await read(ctx)
    await _paused(ctx, doc_id, KEPT_READINGS)
    runs = document_trace(ctx.store, doc_id).runs
    assert [(run.reading, run.ended) for run in runs] == [(KEPT_READINGS + 1, "paused"), (1, "done")]


async def test_only_the_newest_interrupted_attempt_is_kept_within_the_kept_readings(ctx: AppContext) -> None:
    doc_id = await read(ctx)
    await _paused(ctx, doc_id, 2)
    await read_again(ctx, doc_id)
    assert [(run.reading, run.ended) for run in document_trace(ctx.store, doc_id).runs] == [
        (4, "done"),
        (3, "paused"),
        (1, "done"),
    ]
    for _ in range(KEPT_READINGS - 1):
        await read_again(ctx, doc_id)
    runs = document_trace(ctx.store, doc_id).runs
    assert [run.reading for run in runs] == [8, 7, 6, 5, 4], "the pause is older than every kept reading"


async def test_a_reading_is_compared_with_the_newest_earlier_one_that_was_done(ctx: AppContext) -> None:
    doc_id = await read(ctx)
    await _paused(ctx, doc_id, 1)
    await read_again(ctx, doc_id)
    trace = document_trace(ctx.store, doc_id)
    assert trace.run is not None and [run.reading for run in trace.runs] == [3, 2, 1]
    base = compare_base(trace.runs, trace.run)
    assert base is not None and base.reading == 1
    paused = trace.runs[1]
    assert compare_base(trace.runs, paused) == trace.runs[2]
    assert compare_base(trace.runs, trace.runs[2]) is None


async def test_the_compare_route_defaults_to_the_newest_earlier_reading_that_was_done(data_dir: Path) -> None:
    from test_api_support import api_for

    async with api_for(data_dir) as api:
        upload = await api.client.post("/api/documents", files=[("files", ("b.pdf", TAX_LETTER.pdf()))])
        doc_id = upload.json()["documents"][0]["id"]
        await api.read_all()
        ctx = api.ctx
        await _paused(ctx, doc_id, 1)
        reprocess(ctx, doc_id)
        await api.read_all()
        comparison = (await api.client.get(f"/api/documents/{doc_id}/trace/compare")).json()
    assert (comparison["head"]["reading"], comparison["base"]["reading"]) == (3, 1)
    assert comparison["base"]["ended"] == "done"


def _store_a_reading(ctx: AppContext, doc_id: str) -> None:
    """A reading as the pipeline stores one: its model call is logged while it runs, its steps at its end."""
    tracer = start_trace(ctx.store, doc_id, job_id=None, again=True, recorded=False)
    with tracer.root.span("model", "Extract", key="extract") as step:
        ctx.store.log_llm_call(
            "extract", "sonnet", "fake", LLMResponse().usage, doc_ids=[doc_id], span_id=step.id
        )
    assert finish_trace(ctx.store, tracer)


@pytest.mark.parametrize("moment", range(1, 9))
async def test_a_reading_stored_while_the_trace_is_shown_is_wholly_in_the_view_or_not_at_all(
    ctx: AppContext, moment: int
) -> None:
    doc_id = await read(ctx)
    for _ in range(KEPT_READINGS - 1):
        await read_again(ctx, doc_id)  # five kept: the next one pushes the first out
    before = document_trace(ctx.store, doc_id)
    selects = 0

    def another_reading_ends(sql: str) -> None:
        # at the view's ``moment``-th query, another thread (its own connection) stores a reading
        nonlocal selects
        if sql.lstrip().upper().startswith("SELECT"):
            selects += 1
            if selects == moment:
                meanwhile = threading.Thread(target=_store_a_reading, args=(ctx, doc_id))
                meanwhile.start()
                meanwhile.join()

    conn = ctx.store._conn()
    conn.set_trace_callback(another_reading_ends)
    try:
        shown = document_trace(ctx.store, doc_id)
    finally:
        conn.set_trace_callback(None)
    after = document_trace(ctx.store, doc_id)
    assert selects >= moment and [run.reading for run in after.runs] == [6, 5, 4, 3, 2]
    assert shown in (before, after)


# --------------------------------------------------------------------------------------------------
# a letter deleted while its call is under way
# --------------------------------------------------------------------------------------------------


async def test_a_letter_deleted_while_its_call_is_in_flight_keeps_no_key_and_no_cached_answer(
    ctx: AppContext,
) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf")
    answer = ctx.llm.backend.complete

    async def delete_then_answer(req: LLMRequest) -> LLMResponse:
        response = await answer(req)
        ctx.store.delete_document(document.id)
        return response

    ctx.llm.backend.complete = delete_then_answer  # type: ignore[method-assign]
    await ctx.worker.run_until_idle()
    conn = ctx.store._conn()
    rows = conn.execute("SELECT doc_ids, request_key, span_id, job_id FROM llm_calls").fetchall()
    assert rows and [tuple(row) for row in rows] == [("[]", None, None, None)] * len(rows)
    assert conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM trace_spans").fetchone()[0] == 0


async def test_a_letter_in_the_trash_is_not_gone(ctx: AppContext) -> None:
    doc_id = await read(ctx)
    ctx.store.trash_document(doc_id)
    call = ctx.store.log_llm_call(
        "extract", "sonnet", "fake", LLMResponse().usage, doc_ids=[doc_id], request_key="k"
    )
    assert ctx.store.cache_put("k", "extract", "sonnet", {}, doc_ids=[doc_id])
    [row] = [row for row in ctx.store.usage_stats(recent=10).recent if row.id == call]
    assert (row.doc_ids, row.request_key) == ([doc_id], "k")


# --------------------------------------------------------------------------------------------------
# the view
# --------------------------------------------------------------------------------------------------


def _step(start: str, end: str) -> TraceSpanRecord:
    return TraceSpanRecord(
        id=f"spn_{start}",
        trace_id="trc_1",
        doc_id="doc_1",
        key=f"run/model:{start}",
        kind="model",
        name="Page",
        started_at=f"2026-09-28T08:00:{start}.000000Z",
        ended_at=f"2026-09-28T08:00:{end}.000000Z",
    )


def test_waiting_for_claude_counts_calls_under_way_at_once_once() -> None:
    # three pages read at the same time (12 s, 14 s, 13 s), then the extraction (25 s)
    pages = [_step("00", "12"), _step("00", "14"), _step("00", "13")]
    assert busy_ms(pages) == 14_000
    assert busy_ms([*pages, _step("14", "39")]) == 39_000
    assert busy_ms([_step("00", "05"), _step("10", "12")]) == 7_000
    assert busy_ms([]) == 0


async def test_a_photo_letters_waiting_time_is_never_longer_than_the_reading(ctx: AppContext) -> None:
    document = await add_file(
        ctx, photo("JPEG", size=(600, 800)), "page1.jpg", combine_with=[photo("PNG", size=(640, 800))]
    )
    await ctx.worker.run_until_idle()
    run = document_trace(ctx.store, document.id).run
    assert run is not None and run.model_calls == 3
    # the fake backend reports 5 ms a call; measured, the calls took less than the whole reading
    assert 0 < run.model_ms <= run.duration_ms


async def test_an_older_readings_key_facts_are_numbered_not_named_after_the_newest(
    ctx: AppContext, router: Router
) -> None:
    doc_id = await read(ctx)
    payload = TAX_LETTER.extraction()
    payload["key_facts"].insert(
        0, {"label": "Tax year", "value": "2025", "quote": "Einkommensteuerbescheid 2025"}
    )
    router.payloads[TAX_LETTER.marker] = payload
    await read_again(ctx, doc_id)
    newest = document_trace(ctx.store, doc_id)
    older = document_trace(ctx.store, doc_id, newest.runs[1].trace_id)

    def key_fact_labels(spans: list) -> list[str | None]:  # type: ignore[type-arg]
        return [span.label for span in spans if span.attributes.get("target") == "key_fact"]

    assert key_fact_labels(newest.spans) == ["Tax year", "Income tax"]
    assert key_fact_labels(older.spans) == ["Key fact 1"], "not the newest reading's first fact"
