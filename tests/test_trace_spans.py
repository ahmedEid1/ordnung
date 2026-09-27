"""The tracer (ordnung.trace.spans), what spans may hold (facts), and the model layer's usage-log rows,
outcomes and span descriptions (LLMService)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.llm.base import ClaudeTimeout, LLMRequest, LLMResponse, Usage
from ordnung.llm.fake import FakeBackend
from ordnung.llm.runtime import LLMService, call_outcome, request_key
from ordnung.models import ComputationReceipt, DateSpec, Evidence, TraceSpan
from ordnung.trace import facts
from ordnung.trace.compare import compare_spans
from ordnung.trace.spans import NO_SPAN, Tracer, span_id, trace_id_for

START = datetime(2026, 9, 28, 8, 0, tzinfo=UTC)


def recorded(**attributes: object) -> Tracer:
    return Tracer(
        doc_id="doc_1", trace_id="trc_1", job_id="job_1", timing="recorded", started_at=START, **attributes
    )


def by_key(tracer: Tracer) -> dict[str, dict[str, object]]:
    return {record.key: record.model_dump() for record in tracer.records()}


# --------------------------------------------------------------------------------------------------
# keys, ids and the tree
# --------------------------------------------------------------------------------------------------


def test_keys_are_paths_and_ids_hash_trace_and_key() -> None:
    tracer = recorded()
    with tracer.root.span("verify", "Check quotes", key="quotes") as stage:
        with stage.span("verify", "Quote", key="item:abc") as quote:
            assert quote.key == "run/verify:quotes/verify:item:abc"
            assert quote.id == span_id("trc_1", quote.key)
        with stage.span("verify", "Quote", key="item:abc") as repeat:
            assert repeat.key == "run/verify:quotes/verify:item:abc#2"
    records = tracer.records()
    assert [r.key for r in records] == [
        "run",
        "run/verify:quotes",
        "run/verify:quotes/verify:item:abc",
        "run/verify:quotes/verify:item:abc#2",
    ]
    assert [r.seq for r in records] == [0, 1, 2, 3]
    assert records[2].parent_id == records[1].id and records[1].parent_id == records[0].id
    assert records[0].parent_id is None and records[0].kind == "run"
    assert {r.trace_id for r in records} == {"trc_1"} and {r.job_id for r in records} == {"job_1"}
    assert trace_id_for("doc_1", 2) != trace_id_for("doc_1", 1) == trace_id_for("doc_1", 1)


def test_stage_is_inherited_unless_given() -> None:
    tracer = recorded()
    with tracer.root.span("rules", "Compute dates", key="dates", stage="compute") as stage:
        with stage.span("rules", "Date", key="item:x") as child:
            assert child.stage == "compute"
        with stage.span("plan", "Other", key="y", stage="plan") as other:
            assert other.stage == "plan"
    assert tracer.root.stage is None


def test_an_exception_marks_the_step_with_its_class_name_only() -> None:
    tracer = recorded()
    with pytest.raises(ValueError, match="Musterstraße 5"):
        with tracer.root.span("link", "Sender", key="sender"):
            raise ValueError("the letter says Musterstraße 5")
    record = by_key(tracer)["run/link:sender"]
    assert record["status"] == "error" and record["error"] == "ValueError"
    tracer.finish(error="Something went wrong while reading this document.")
    root = by_key(tracer)["run"]
    assert root["status"] == "error" and root["error"].startswith("Something went wrong")


def test_the_inactive_span_records_nothing() -> None:
    assert not NO_SPAN.active and NO_SPAN.id is None and NO_SPAN.job_id is None
    with NO_SPAN.span("model", "Extract", key="extract", stage="extract") as child:
        assert child is NO_SPAN
        child.set(secret="x")
        child.record_call(recorded_ms=5, call_id=1)
        child.fail("boom")
    assert NO_SPAN.attributes == {} and NO_SPAN.status == "ok" and NO_SPAN.recorded_ms is None


# --------------------------------------------------------------------------------------------------
# time
# --------------------------------------------------------------------------------------------------


def test_recorded_timing_lays_out_from_recorded_latencies() -> None:
    tracer = recorded(reading=1)
    with tracer.root.span("ocr", "Text layer", key="text"):
        pass
    with tracer.root.span("model", "Extract", key="extract") as model:
        model.record_call(recorded_ms=41_080)
    with tracer.root.span("verify", "Check quotes", key="quotes"):
        pass
    tracer.finish()
    rows = by_key(tracer)
    assert (
        rows["run/ocr:text"]["started_at"]
        == rows["run/ocr:text"]["ended_at"]
        == "2026-09-28T08:00:00.000000Z"
    )
    assert rows["run/model:extract"]["ended_at"] == "2026-09-28T08:00:41.080000Z"
    assert rows["run/verify:quotes"]["started_at"] == "2026-09-28T08:00:41.080000Z"
    assert rows["run"]["ended_at"] == "2026-09-28T08:00:41.080000Z"
    assert rows["run"]["attributes"]["timing"] == "recorded"


def test_parallel_children_start_together_and_are_ordered_by_key_whatever_finished_first() -> None:
    def build(order: list[int]) -> list[dict[str, object]]:
        tracer = recorded()
        with tracer.root.span("ocr", "Transcribe", key="transcribe", parallel=True) as group:
            for page in order:
                with group.span("model", f"Page {page}", key=f"page:{page}") as step:
                    step.record_call(recorded_ms=1000 * page)
        with tracer.root.span("model", "Extract", key="extract") as model:
            model.record_call(recorded_ms=500)
        return [record.model_dump() for record in tracer.records()]

    first, second = build([1, 2, 3]), build([3, 1, 2])
    assert first == second
    rows = {row["key"]: row for row in first}
    pages = [rows[f"run/ocr:transcribe/model:page:{n}"] for n in (1, 2, 3)]
    assert {row["started_at"] for row in pages} == {"2026-09-28T08:00:00.000000Z"}
    assert rows["run/ocr:transcribe"]["ended_at"] == "2026-09-28T08:00:03.000000Z"  # the slowest page
    assert rows["run/model:extract"]["started_at"] == "2026-09-28T08:00:03.000000Z"
    assert [row["seq"] for row in pages] == [2, 3, 4]


async def test_measured_timing_nests_children_inside_their_parents() -> None:
    tracer = Tracer(doc_id="doc_1", trace_id="trc_1")
    with tracer.root.span("model", "Extract", key="extract"):
        await asyncio.sleep(0.01)
    tracer.finish()
    rows = by_key(tracer)
    root, extract = rows["run"], rows["run/model:extract"]
    assert root["started_at"] <= extract["started_at"] <= extract["ended_at"] <= root["ended_at"]
    assert extract["ended_at"] > extract["started_at"]
    assert root["attributes"]["timing"] == "measured"


# --------------------------------------------------------------------------------------------------
# facts: never letter text
# --------------------------------------------------------------------------------------------------


def test_a_date_spec_is_kept_without_its_wording_or_legal_basis() -> None:
    spec = DateSpec(
        type="relative",
        amount=1,
        unit="months",
        anchor="deemed_delivery",
        text="innerhalb eines Monats nach Bekanntgabe",
        legal_basis="§ 355 AO",
    )
    receipt = ComputationReceipt(due_date="2026-10-21", send_by="2026-10-16", rule_ids=["ao_122_2_1"])
    kept = facts.dated(spec, receipt, source="computed", index=0, slot_key="s1")
    assert set(kept["spec"]) == set(facts.SPEC_FIELDS)
    assert "innerhalb" not in json.dumps(kept) and "355" not in json.dumps(kept)
    assert (kept["due_date"], kept["send_by"], kept["rule_ids"]) == (
        "2026-10-21",
        "2026-10-16",
        ["ao_122_2_1"],
    )


def test_a_quote_is_described_never_copied() -> None:
    from ordnung.ingest.verify import QuoteCheck

    evidence = Evidence(
        doc_id="doc_1", quote="Zahlen Sie 1.234,56 EUR bis zum 15.10.2026", grounding="verified", score=97.5
    )
    described = facts.quote(
        "item", evidence, QuoteCheck(97.5, 2, True), index=0, reasons=["amount_not_in_quote"]
    )
    assert "Zahlen" not in json.dumps(described) and "1.234" not in json.dumps(described)
    assert described["digit_groups"] == 2 and described["digits_matched"] is True
    assert described["consistent"] is False and described["reasons"] == ["amount_not_in_quote"]


# --------------------------------------------------------------------------------------------------
# the model layer
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failed", "valid", "repair", "outcome"),
    [
        (False, True, False, "ok"),
        (False, False, False, "invalid"),
        (False, True, True, "repaired"),
        (False, False, True, "failed"),
        (True, True, False, "failed"),
        (True, False, True, "failed"),
    ],
)
def test_call_outcome_policy(failed: bool, valid: bool, repair: bool, outcome: str) -> None:
    assert call_outcome(failed=failed, valid=valid, repair=repair) == outcome


class _Answer(BaseModel):
    answer: str


def _check(response: LLMResponse) -> _Answer:
    return _Answer.model_validate(response.data)


def _request(**overrides: object) -> LLMRequest:
    fields: dict[str, object] = {
        "purpose": "extract",
        "prompt": "p",
        "system": "s",
        "doc_ids": ["doc_1"],
        "cache_key": "k",
        "prompt_version": "8.7.1",
        "prompt_name": "extract",
    }
    return LLMRequest.model_validate(fields | overrides)


@pytest.fixture
def usage_store(tmp_path: Path) -> Store:
    return Store.open(Paths(tmp_path / "data"))


async def test_a_traced_call_writes_its_row_and_describes_its_step(usage_store: Store) -> None:
    served = LLMResponse(
        data={"answer": "x"}, model="model-that-answered", usage=Usage(input_tokens=7, duration_ms=1234)
    )
    llm = LLMService(FakeBackend({"extract": served}), usage_store)
    tracer = recorded()
    with tracer.root.span("model", "Extract", key="extract", stage="extract") as step:
        response = await llm.complete(_request(), trace=step, validate=_check)
    [row] = usage_store.usage_stats().recent
    assert response.call_id == row.id
    assert (row.request_key, row.prompt_name, row.prompt_version) == (
        request_key(_request()),
        "extract",
        "8.7.1",
    )
    assert (row.served_model, row.job_id, row.stage, row.outcome) == (
        "model-that-answered",
        "job_1",
        "extract",
        "ok",
    )
    assert row.span_id == step.id and row.repair_of is None
    assert step.recorded_ms == 1234
    assert step.attributes["call_id"] == row.id and step.attributes["outcome"] == "ok"
    assert (
        step.attributes["request_model"] == "sonnet"
        and step.attributes["served_model"] == "model-that-answered"
    )
    assert "call_id" not in response.model_dump(), "the log id never reaches the cache or a recording"


async def test_an_invalid_answer_then_its_repair(usage_store: Store) -> None:
    answers = iter([{"wrong": 1}, {"answer": "ok"}])
    llm = LLMService(FakeBackend(lambda req: next(answers)), usage_store)
    first = await llm.complete(_request(), validate=_check)
    second = await llm.complete(_request(cache_key="k2"), validate=_check, repair_of=first.call_id)
    rows = {row.id: row for row in usage_store.usage_stats().recent}
    assert rows[first.call_id or 0].outcome == "invalid"
    assert (
        rows[second.call_id or 0].outcome == "repaired"
        and rows[second.call_id or 0].repair_of == first.call_id
    )


async def test_a_repair_that_is_still_invalid_failed(usage_store: Store) -> None:
    llm = LLMService(FakeBackend({"extract": {"wrong": 1}}), usage_store)
    first = await llm.complete(_request(), validate=_check)
    second = await llm.complete(_request(cache_key="k2"), validate=_check, repair_of=first.call_id)
    outcomes = {row.id: row.outcome for row in usage_store.usage_stats().recent}
    assert (outcomes[first.call_id or 0], outcomes[second.call_id or 0]) == ("invalid", "failed")


async def test_an_erroring_call_is_logged_as_failed_on_its_step(usage_store: Store) -> None:
    def fail(req: LLMRequest) -> LLMResponse:
        raise ClaudeTimeout("Claude took too long.")

    llm = LLMService(FakeBackend(fail), usage_store)
    tracer = recorded()
    with pytest.raises(ClaudeTimeout), tracer.root.span("model", "Extract", key="extract") as step:
        await llm.complete(_request(), trace=step)
    [row] = usage_store.usage_stats().recent
    assert (row.ok, row.outcome, row.error, row.span_id) == (
        False,
        "failed",
        "Claude took too long.",
        step.id,
    )
    assert step.status == "error" and step.error == "ClaudeTimeout" and step.attributes["outcome"] == "failed"


async def test_a_cache_hit_is_logged_with_the_same_key_and_takes_no_recorded_time(usage_store: Store) -> None:
    served = LLMResponse(data={"answer": "x"}, model="model-that-answered", usage=Usage(duration_ms=900))
    llm = LLMService(FakeBackend({"extract": served}), usage_store)
    await llm.complete(_request())
    tracer = recorded()
    with tracer.root.span("model", "Extract", key="extract") as step:
        again = await llm.complete(_request(), trace=step)
    assert again.cache_hit and step.recorded_ms == 0 and step.attributes["cache_hit"] is True
    rows = usage_store.usage_stats().recent
    assert rows[0].cache_hit and rows[0].request_key == rows[1].request_key
    assert rows[0].served_model == "model-that-answered"


async def test_without_a_trace_or_a_log_nothing_breaks() -> None:
    llm = LLMService(FakeBackend({"extract": {"answer": "x"}}))
    response = await llm.complete(_request(), validate=_check)
    assert response.call_id is None and response.data == {"answer": "x"}


# --------------------------------------------------------------------------------------------------
# comparing two readings
# --------------------------------------------------------------------------------------------------


def _step(key: str, kind: str, **attributes: object) -> TraceSpan:
    return TraceSpan.model_validate(
        {"id": key, "key": key, "kind": kind, "name": key, "attributes": attributes}
    )


def test_a_reading_finding_its_own_earlier_work_is_no_change() -> None:
    before = [
        _step("run/link:sender", "link", decision="new", party_id="pty_1"),
        _step("run/plan:plan/plan:item:a", "plan", action="created", item_id="itm_a", due_date="2026-10-15"),
    ]
    after = [
        _step("run/link:sender", "link", decision="name", party_id="pty_1"),
        _step("run/plan:plan/plan:item:a", "plan", action="updated", item_id="itm_a", due_date="2026-10-15"),
    ]
    assert compare_spans(before, after) == []


def test_changed_decisions_and_steps_in_one_reading_only() -> None:
    before = [
        _step("run/model:extract", "model", outcome="invalid", cache_hit=False, duration=5),
        _step("run/model:extract_repair", "model", outcome="repaired"),
        _step("run/verify:quotes/verify:item:a", "verify", grounding="unverified", score=71.0),
        _step("run/plan:plan/plan:item:a", "plan", action="updated", item_id="itm_a", due_date="2026-10-15"),
    ]
    after = [
        _step("run/model:extract", "model", outcome="ok", cache_hit=False, duration=9),
        _step("run/verify:quotes/verify:item:a", "verify", grounding="verified", score=98.0),
        _step(
            "run/plan:plan/plan:item:a", "plan", action="kept_edited", item_id="itm_a", due_date="2026-10-15"
        ),
        _step("run/link:links/link:reminder", "link", invoices=1),
    ]
    changes = [
        (change.key.rsplit("/", 1)[-1], change.field, change.before, change.after)
        for change in compare_spans(before, after)
    ]
    assert changes == [
        ("model:extract", "outcome", "invalid", "ok"),
        ("verify:item:a", "grounding", "unverified", "verified"),
        ("plan:item:a", "action", "updated", "kept_edited"),
        ("link:reminder", "present", False, True),
        ("model:extract_repair", "present", True, False),
    ]
