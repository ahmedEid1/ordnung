"""What the completeness re-ask shows and keeps around it (ADR 0016): the letter's warning when its answer was used
(never a scam sign, never a hedge the benchmark reads as one), the trace (no repair counted, compared between
readings), no further call once the letter was trashed or deleted, and the benchmark's honesty about a re-ask it
has no recording of (never cached, said loudly, kept in the results, allowed for one letter only).

Synthetic letters (``tests/test_reading_reask.py``); the one benchmark letter named by its entry id only; nothing
calls a model.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import TODAY
from ordnung import clock
from ordnung.app_context import build_context
from ordnung.ingest.extract import REASK_WARNING, reask_warning
from ordnung.ingest.pipeline import TRASHED_AGAIN_ERROR, add_file, ingest_document
from ordnung.llm.base import LLMRequest, ReplayMiss
from ordnung.llm.fake import FakeBackend
from ordnung.llm.replay import ReplayBackend
from ordnung.llm.runtime import LLMService
from ordnung.secretary.triggers import _NOT_A_SIGN
from ordnung.trace.compare import compare_traces
from ordnung.trace.otel import to_otlp
from ordnung.trace.runs import FAILURES
from ordnung.trace.view import document_trace
from test_reading_reask import (
    BLANK,
    COMPLETE,
    DECISION,
    EMPTY_READING,
    INJECTED,
    MANIFEST,
    RECORDED,
    WithoutReask,
    as_first_recorded,
    ingest,
    pipeline_backend,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import run as eval_run  # noqa: E402
from evals.conditions import (  # noqa: E402
    REASK_MISSING,
    CallLog,
    MeteredBackend,
    prepare_document,
    run_ordnung,
)
from evals.metrics import INJECTION_RE, SCAM_RE, UNCERTAINTY_RE  # noqa: E402
from evals.records import Prediction, load_manifest  # noqa: E402


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


# --------------------------------------------------------------------------------------------------
# The letter's warning
# --------------------------------------------------------------------------------------------------


async def test_an_accepted_re_ask_is_said_on_the_letter_and_counts_as_no_repair(data_dir: Path) -> None:
    ctx, doc_id = await ingest(data_dir, DECISION, pipeline_backend(DECISION, BLANK, COMPLETE))
    try:
        document = ctx.store.get_document(doc_id)
        trace = document_trace(ctx.store, doc_id)
    finally:
        ctx.close()
    assert document is not None and reask_warning("empty") in document.warnings
    assert trace.run is not None and (trace.run.model_calls, trace.run.repairs) == (2, 0)


async def test_the_open_telemetry_export_names_the_re_ask_s_link_as_no_repair(data_dir: Path) -> None:
    ctx, doc_id = await ingest(data_dir, DECISION, pipeline_backend(DECISION, BLANK, COMPLETE))
    try:
        trace = document_trace(ctx.store, doc_id)
    finally:
        ctx.close()
    exported = to_otlp(trace, key=b"k")
    spans = exported["resourceSpans"][0]["scopeSpans"][0]["spans"]

    def step_name(span: dict[str, Any]) -> str:
        return next(a["value"]["stringValue"] for a in span["attributes"] if a["key"] == "ordnung.step.name")

    names = {step_name(span): {a["key"] for a in span["attributes"]} for span in spans}
    again = names["Extract · complete"]
    assert "ordnung.llm.completes" in again and "ordnung.llm.repair_of" not in again
    assert "ordnung.llm.completes" not in names["Extract"]


async def test_a_rejected_re_ask_adds_no_warning_of_its_own(data_dir: Path) -> None:
    ctx, doc_id = await ingest(data_dir, INJECTED, pipeline_backend(INJECTED, BLANK, BLANK))
    try:
        document = ctx.store.get_document(doc_id)
    finally:
        ctx.close()
    assert document is not None
    assert not any(REASK_WARNING.match(warning) for warning in document.warnings)


@pytest.mark.parametrize("gap", ["empty", "remedy_left_out"])
@pytest.mark.parametrize("injected", [False, True])
def test_the_warning_is_no_scam_sign_and_no_hedge(gap: str, injected: bool) -> None:
    warning = reask_warning(gap, injected=injected)  # type: ignore[arg-type]
    assert REASK_WARNING.match(warning) and _NOT_A_SIGN.search(warning)
    for pattern in (SCAM_RE, UNCERTAINTY_RE, INJECTION_RE):
        assert not pattern.search(warning), (pattern.pattern[:40], warning)


# --------------------------------------------------------------------------------------------------
# No further call once the letter was trashed or deleted (ux F2)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("first", [BLANK, {"kind": "other"}], ids=["re-ask", "repair"])
@pytest.mark.parametrize("how", ["trash", "delete"])
async def test_a_letter_trashed_or_deleted_during_the_extraction_is_not_sent_again(
    data_dir: Path, first: dict[str, Any], how: str
) -> None:
    held: dict[str, Any] = {}

    def respond(request: LLMRequest) -> Any:
        if request.prompt_name == "extract":
            store, doc_id = held["ctx"].store, held["doc_id"]
            if how == "trash":
                store.trash_document(doc_id)
            else:
                store.delete_document(doc_id)
            return first
        return COMPLETE

    backend = FakeBackend(respond)
    ctx = build_context(data_dir, backend_obj=backend)
    held["ctx"] = ctx
    try:
        document = await add_file(ctx, DECISION.pdf(), "bescheid.pdf")
        held["doc_id"] = document.id
        await ctx.worker.run_until_idle()
        trace = document_trace(ctx.store, document.id) if how == "trash" else None
    finally:
        ctx.close()
    assert [request.prompt_name for request in backend.calls] == ["extract"]
    if trace is not None:  # its own words: it was sent once, never again
        assert trace.run is not None and trace.run.error == FAILURES["trashed_meanwhile"]
        assert "again" in TRASHED_AGAIN_ERROR and "again" in FAILURES["trashed_meanwhile"]


# --------------------------------------------------------------------------------------------------
# Read again and compared (ux F7)
# --------------------------------------------------------------------------------------------------


async def test_read_again_and_compare_says_whether_the_re_ask_s_answer_was_used(data_dir: Path) -> None:
    answers = [BLANK, COMPLETE, BLANK, BLANK]
    ctx, doc_id = await ingest(data_dir, DECISION, FakeBackend(lambda _request: answers.pop(0)))
    try:
        first = document_trace(ctx.store, doc_id)
        await ingest_document(ctx, doc_id, force=True)
        head = document_trace(ctx.store, doc_id)
        assert first.run is not None
        base = document_trace(ctx.store, doc_id, first.run.trace_id)
    finally:
        ctx.close()
    changes = {(change.key, change.field): change for change in compare_traces(base, head).changes}
    used = changes[("run/model:extract_complete", "accepted")]
    assert (used.before, used.after) == (True, False)


# --------------------------------------------------------------------------------------------------
# The benchmark: a missing re-ask recording is never cached, said loudly, and allowed for one letter only
# --------------------------------------------------------------------------------------------------


def test_a_prediction_made_without_the_re_ask_s_recording_is_never_served_from_the_cache(
    tmp_path: Path,
) -> None:
    """Benchmark review H1: a recording made since (no fingerprint covers it) must be replayed, and a live run
    must make the call."""
    path = tmp_path / "cached.json"
    missing = Prediction(
        entry_id=EMPTY_READING, condition="ordnung", model="m", fingerprint="f", signals=[REASK_MISSING]
    )
    eval_run.save_cached(path, missing)
    assert eval_run.load_cached(path, "f") is None
    eval_run.save_cached(path, missing.model_copy(update={"signals": ["reading_reask:accepted"]}))
    assert eval_run.load_cached(path, "f") is not None


async def test_a_replay_without_the_re_ask_s_recording_says_so_and_keeps_it_in_the_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Benchmark review H3: the warning, ``meta.reading_reask_missing``, and nothing cached for the letter."""
    as_first_recorded(monkeypatch)
    said: list[str] = []
    config = eval_run.RunConfig(
        split="holdout2",
        ids=[EMPTY_READING],
        conditions=["ordnung"],
        results_dir=tmp_path / "results",
        recorded_dir=RECORDED.parent,
        docs_path=tmp_path / "evals.md",
        chart_path=tmp_path / "chart.png",
        resamples=20,
        write_docs=False,
        run_date="2026-10-02",
    )
    backend = WithoutReask(eval_run.RecordedFailures(ReplayBackend(RECORDED), RECORDED, record=False))
    outcome = await eval_run.run_benchmark(config, backend=backend, progress=said.append)
    [run] = outcome.runs
    assert run.results is not None and run.results["meta"]["reading_reask_missing"] == [EMPTY_READING]
    assert any(
        "without their completeness re-ask's recording" in line and EMPTY_READING in line for line in said
    )
    assert not list((tmp_path / "results" / "cache").rglob("*.json"))


def test_the_warning_is_said_under_quiet_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--quiet`` silences the per-letter progress, never the letter scored without its re-ask."""
    as_first_recorded(monkeypatch)
    args = [
        "--split",
        "holdout2",
        "--ids",
        EMPTY_READING,
        "--conditions",
        "ordnung",
        "--recorded-dir",
        str(RECORDED.parent),
        "--results-dir",
        str(tmp_path / "results"),
        "--date",
        "2026-10-02",
        "--resamples",
        "20",
        "--no-docs",
        "--quiet",
    ]
    backend = WithoutReask(eval_run.RecordedFailures(ReplayBackend(RECORDED), RECORDED, record=False))
    assert eval_run.run_cli(args, backend=backend) == 0
    err = capsys.readouterr().err
    assert err.count("without their completeness re-ask's recording") == 1 and EMPTY_READING in err


async def test_a_re_ask_miss_on_any_other_letter_is_a_replay_error(tmp_path: Path) -> None:
    """Benchmark review H3: only the letter recorded before the re-ask existed may miss it; a change that makes
    the check fire elsewhere must record that call, never score the first reading silently."""
    entry = {e.id: e for e in load_manifest(MANIFEST)}["dev-municipal_decision-A1"]
    document = prepare_document(entry, MANIFEST.parent, tmp_path)

    def respond(request: LLMRequest) -> Any:
        if request.prompt_name == "reading_gaps":
            raise ReplayMiss("no recorded response for extract")
        return dict(BLANK)

    llm = LLMService(MeteredBackend(FakeBackend(respond), CallLog(), timeout_s=60))
    with pytest.raises(ReplayMiss):
        await run_ordnung(entry, document, llm, model="claude-sonnet-5")
