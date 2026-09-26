"""End-to-end tests for the benchmark runner (``evals/run.py``) without any network.

A ``FakeBackend`` answers like a plausible model: transcripts are the letter's own text, the
extraction and the baseline answers are built from the truth (the ``llm_only`` answer is one day
late on purpose). The tests run all three conditions on three real dataset entries (a tax
assessment, a phone photo of an invoice and a contract confirmation) and check the results JSON,
``docs/evals.md``, the chart, resuming from the cache, recording and replaying, and replay misses.
"""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pdfplumber
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import report  # noqa: E402
from evals import run as eval_run  # noqa: E402
from evals.conditions import TOOL_PREFIX  # noqa: E402
from evals.records import Entry, TruthItem, load_manifest  # noqa: E402

from ordnung.assistant.rules_tools import RulesTools, render  # noqa: E402
from ordnung.llm.base import (  # noqa: E402
    ClaudeBadOutput,
    LLMError,
    LLMRequest,
    LLMResponse,
    ReplayMiss,
    StreamEvent,
    ToolCall,
    Usage,
)
from ordnung.llm.fake import FakeBackend  # noqa: E402
from ordnung.llm.replay import RecordingBackend, ReplayBackend  # noqa: E402

MANIFEST = ROOT / "evals" / "dataset" / "manifest.json"
IDS = ["dev-contract_confirmation-A1", "dev-invoice_relative-A1-photo", "dev-tax_assessment-A1"]
PARTY_KIND_BY_SCOPE = {"ao": "tax_office", "sgbx": "health_insurer", "vwvfg": "authority"}
PARTY_KIND_BY_FAMILY = {
    "fine_bussgeld": "authority",
    "appointment": "authority",
    "contract_confirmation": "gym",
}
PERIOD_WORDS = {"months": "Monat", "days": "Tagen", "weeks": "Wochen"}


# --------------------------------------------------------------------------------------------------
# A plausible fake model
# --------------------------------------------------------------------------------------------------


def _german(value: str | None) -> str:
    return "" if not value else f"{value[8:10]}.{value[5:7]}.{value[:4]}"


class Responder:
    """Answers transcribe, extract and eval_baseline requests for the benchmark's own letters."""

    def __init__(self) -> None:
        raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.raw = {entry["id"]: entry for entry in raw["entries"]}
        self.entries = {entry.id: entry for entry in load_manifest(MANIFEST)}
        self.texts: dict[str, str] = {}

    def text(self, entry: Entry) -> str:
        source = self.entries[entry.source_id] if entry.source_id else entry
        if source.id not in self.texts:
            with pdfplumber.open(source.path(MANIFEST.parent)) as pdf:
                self.texts[source.id] = "\n".join(page.extract_text() or "" for page in pdf.pages)
        return self.texts[source.id]

    def quote(self, entry: Entry, *needles: str) -> str:
        lines = [line.strip() for line in self.text(entry).splitlines() if line.strip()]
        return next((line for line in lines if any(n and n in line for n in needles)), lines[0])

    def __call__(self, req: LLMRequest) -> dict[str, Any] | LLMResponse:
        entry = self.entries[req.doc_ids[0]]
        if req.purpose == "transcribe":
            return {"text": self.text(entry), "language": "de", "legible": True}
        if req.purpose == "extract":
            return self.extraction(entry)
        assert req.purpose == "eval_baseline"
        condition = req.prompt_version.split(".", 1)[0]
        if condition == "llm_rules_tool":
            return self.with_tools(entry)
        return self.baseline(entry, late=condition == "llm_only")

    def with_tools(self, entry: Entry) -> LLMResponse:
        """An agent with a calculator: it asks the real rules tools for every date and answers with
        their dates — except on the photo, where it overrides the tool by a day. On the tax letter it
        first sends a misspelt spec, which the tool refuses."""
        tools = RulesTools(today=lambda: entry.today_date)
        truth = entry.truth
        calls: list[ToolCall] = []
        if entry.family == "tax_assessment":
            calls.append(
                ToolCall(
                    name=f"{TOOL_PREFIX}compute_deadline",
                    input={"spec": {"type": "relative", "amout": 1}},
                    result="Error executing tool compute_deadline: invalid spec — spec.amout: unknown field",
                )
            )
        answer = self.baseline(entry, late=False)
        for index, item in enumerate(truth.items):
            if item.spec.type == "none":
                continue
            arguments = {
                "spec": self.spec(item, truth.document_date),
                "document_date": truth.document_date,
                "sender_kind": self.party_kind(entry),
                "region": entry.authority_region,
                "recipient_region": entry.recipient_region or "NW",
            }
            result = tools.compute_deadline(**arguments)
            calls.append(
                ToolCall(name=f"{TOOL_PREFIX}compute_deadline", input=arguments, result=render(result))
            )
            due = result["due_date"]
            if due is not None and entry.photo:
                due = (date.fromisoformat(due) + timedelta(days=1)).isoformat()
            answer["items"][index]["due_date"] = due
        usage = Usage(input_tokens=300, output_tokens=90, cost_usd=0.003, duration_ms=9, turns=len(calls) + 1)
        return LLMResponse(data=answer, usage=usage, model="sonnet", backend="fake", tool_calls=calls)

    def spec(self, item: TruthItem, document_date: str | None) -> dict[str, Any]:
        spec = item.spec
        if spec.type == "fixed":
            return {
                "type": "fixed",
                "date": spec.date,
                "time": spec.time,
                "nature": item.nature,
                "text": _german(spec.date),
            }
        result: dict[str, Any] = {
            "type": "relative",
            "anchor": spec.anchor,
            "amount": spec.amount,
            "unit": spec.unit,
            "nature": item.nature,
            "text": f"{spec.amount} {spec.unit}",
        }
        if spec.anchor == "deemed_delivery":
            result["delivery_rule"] = "de_admin_post"
            if spec.posted_on and spec.posted_on != document_date:
                result["anchor_date"] = spec.posted_on
        if spec.anchor == "explicit_date":
            result["anchor_date"] = spec.anchor_date
        return result

    @staticmethod
    def party_kind(entry: Entry) -> str:
        """The sender's kind that selects the delivery law the truth expects."""
        for item in entry.truth.items:
            scope = item.spec.delivery_scope
            if scope in PARTY_KIND_BY_SCOPE:
                return PARTY_KIND_BY_SCOPE[scope]
        return PARTY_KIND_BY_FAMILY.get(entry.family, "company")

    def extraction(self, entry: Entry) -> dict[str, Any]:
        truth = entry.truth
        items = [
            {
                "kind": item.kind,
                "title": item.title,
                "date": self.spec(item, truth.document_date),
                "amount": item.amount,
                "currency": "EUR" if item.amount is not None else None,
                "quote": self.quote(
                    entry, _german(item.spec.date), PERIOD_WORDS.get(item.spec.unit or "", "")
                ),
            }
            for item in truth.items
        ]
        payload: dict[str, Any] = {
            "kind": truth.kind,
            "title": f"Letter from {truth.sender_name}",
            "language": "de",
            "sender": {"name": truth.sender_name, "kind": self.party_kind(entry)},
            "document_date": truth.document_date,
            "references": [ref.model_dump() for ref in truth.references],
            "summary": "A letter.",
            "explanation": "What it means.",
            "items": items,
            "key_facts": [
                {
                    "label": "Amount",
                    "value": f"{amount:.2f} €".replace(".", ","),
                    "quote": self.quote(entry, f"{amount:.2f}".replace(".", ",")),
                }
                for amount in truth.amounts
            ],
            "remedy": {"type": truth.remedy_type},
        }
        contract = self.raw[entry.id]["truth"].get("contract")
        if contract:
            payload["contract"] = {
                "name": "Mitgliedschaft",
                "category": contract["category"],
                "concluded_date": contract["concluded_date"],
                "start_date": contract["start_date"],
                "initial_term_months": contract["initial_term_months"],
                "renewal_term_months": 0,
                "notice_value": contract["notice_value"],
                "notice_unit": contract["notice_unit"],
                "notice_basis": contract["notice_basis"],
                "cost_amount": contract["price"],
                "cost_interval": contract["price_interval"],
                "is_consumer": True,
                "quotes": [self.quote(entry, "Mindestlaufzeit")],
            }
        return payload

    def baseline(self, entry: Entry, *, late: bool) -> dict[str, Any]:
        truth = entry.truth
        items = []
        for index, item in enumerate(truth.items):
            due = item.expected_date
            if due is not None and late and index == 0:
                due += timedelta(days=1)
            items.append(
                {
                    "kind": item.kind,
                    "title": item.title,
                    "quote": self.quote(entry, PERIOD_WORDS.get(item.spec.unit or "", "")),
                    "computation": "Counted as the law says.",
                    "due_date": due.isoformat() if due else None,
                    "confidence": "high",
                    "amount": item.amount,
                }
            )
        contract = truth.contract
        return {
            "kind": truth.kind,
            "sender_name": truth.sender_name,
            "document_date": truth.document_date,
            "references": [ref.model_dump() for ref in truth.references],
            "amounts": truth.amounts,
            "items": items,
            "remedy_type": truth.remedy_type,
            "contract": {
                "current_term_end": contract.expected_current_term_end,
                "cancel_by": contract.expected_cancel_by,
            }
            if contract
            else None,
            "warnings": [],
        }


class Refusing:
    """A backend that must not be called (everything should come from the cache)."""

    name = "refusing"

    async def complete(self, req: LLMRequest) -> LLMResponse:
        raise AssertionError(f"unexpected model call: {req.purpose}")

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:  # pragma: no cover
        raise AssertionError("unexpected stream")
        yield


def make_config(tmp_path: Path, **overrides: Any) -> eval_run.RunConfig:
    values: dict[str, Any] = {
        "split": "dev",
        "ids": list(IDS),
        "results_dir": tmp_path / "results",
        "recorded_dir": tmp_path / "recorded",
        "docs_path": tmp_path / "docs" / "evals.md",
        "chart_path": tmp_path / "docs" / "assets" / "eval-due-date-accuracy.png",
        "resamples": 200,
        "run_date": "2026-09-25",
        "write_docs": True,
    }
    values.update(overrides)
    return eval_run.RunConfig(**values)


# --------------------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------------------


async def test_all_four_conditions_end_to_end(tmp_path: Path) -> None:
    backend = FakeBackend(Responder())
    config = make_config(tmp_path)
    outcome = await eval_run.run_benchmark(config, backend=backend)

    assert outcome.ok
    purposes = sorted(req.purpose for req in backend.calls)
    assert purposes.count("transcribe") == 1  # only the photo
    assert purposes.count("extract") == 3
    assert purposes.count("eval_baseline") == 9
    tool_requests = [r for r in backend.calls if r.prompt_version.startswith("llm_rules_tool.")]
    assert len(tool_requests) == 3
    todays = {entry.id: entry.today for entry in load_manifest(MANIFEST)}
    for request in tool_requests:  # the rules-only server, nothing else, pinned to the letter's today
        (server,) = request.mcp_config["mcpServers"].values()  # type: ignore[index]
        assert server["args"] == ["-m", "ordnung", "mcp", "--rules-only"]
        # pinned: the claude CLI tells the model the real date, which must not replace the letter's
        assert server["env"] == {"ORDNUNG_TODAY": todays[request.doc_ids[0]], "ORDNUNG_PIN_TODAY": "1"}
        assert request.allowed_tools == ["mcp__ordnung_rules__*"] and request.tools == []
        assert request.max_budget_usd == 1.0
        assert "TOOLS: Ordnung's German deadline tools" in request.system
    others = [r for r in backend.calls if r.purpose == "eval_baseline" and r not in tool_requests]
    assert all(r.mcp_config is None and not r.allowed_tools and "TOOLS:" not in r.system for r in others)
    assert all(req.doc_ids and req.doc_ids[0] in IDS for req in backend.calls)
    photo_baseline = [
        r
        for r in backend.calls
        if r.purpose == "eval_baseline" and r.doc_ids == ["dev-invoice_relative-A1-photo"]
    ]
    assert all(r.attachments and r.attachments[0].media_type == "image/jpeg" for r in photo_baseline)

    path = tmp_path / "results" / "2026-09-25-sonnet-dev-partial.json"
    assert outcome.runs[0].results_path == path
    results = json.loads(path.read_text(encoding="utf-8"))
    assert set(results) == {"schema", "meta", "metrics", "comparisons", "gallery", "entries"}
    meta = results["meta"]
    assert (meta["model"], meta["split"], meta["entries"], meta["photos"], meta["scored_items"]) == (
        "sonnet",
        "dev",
        3,
        1,
        2,
    )
    assert meta["partial"] is True and meta["backend"] == "fake"
    assert set(meta["fingerprints"]) == {"ordnung", "llm_only", "llm_rules_text", "llm_rules_tool"}

    metrics = results["metrics"]
    assert list(metrics) == ["ordnung", "llm_only", "llm_rules_text", "llm_rules_tool"]
    for condition, m in metrics.items():
        acc = m["due_date_accuracy"]
        assert acc["n"] == 2 and acc["value"] is not None and len(acc["ci"]) == 2, condition
        assert m["calls"] > 0 and m["cost_usd"]["total"] > 0 and m["tokens"]["total"] > 0
        assert m["errors"] == 0 and m["failed"] == 0
        assert set(m["by_modality"]) == {"text", "photo"}
    assert metrics["llm_rules_text"]["due_date_accuracy"]["value"] == 1.0
    assert metrics["llm_only"]["dangerous_late_rate"]["value"] > 0
    assert metrics["llm_only"]["taxonomy"]["late"] >= 1
    assert metrics["llm_rules_text"]["extraction"]["contract_dates"]["value"] == 1.0

    grounding = metrics["ordnung"]["grounding"]
    assert grounding["counts"]["verified"] >= 1 and grounding["counts"]["model_read"] >= 1
    assert metrics["llm_only"]["grounding"] is None
    assert metrics["ordnung"]["extraction"]["contract_dates"]["n"] == 2
    assert "ordnung-vs-llm_only" in results["comparisons"]
    assert {"llm_rules_tool-vs-llm_only", "llm_rules_tool-vs-llm_rules_text"} <= set(results["comparisons"])

    # The agent with a calculator: its tool calls are recorded and compared with its final dates.
    assert all(metrics[c]["tool_use"] is None for c in ("ordnung", "llm_only", "llm_rules_text"))
    use = metrics["llm_rules_tool"]["tool_use"]
    assert use["letters_with_date_tool_call"]["k"] == 2 and use["letters_with_date_tool_call"]["n"] == 2
    assert use["calls_by_tool"] == {"compute_deadline": 3} and use["refused_calls"] == 1
    assert use["items_by_backing"] == {
        "tool_date": 1,
        "overrode_tool": 1,
        "other_obligation": 0,
        "no_tool_date": 0,
    }
    assert use["final_differs_from_tool"]["value"] == 0.5
    assert use["accuracy_by_backing"]["tool_date"]["value"] == 1.0
    assert use["late_by_backing"]["overrode_tool"]["value"] == 1.0
    assert use["tool_returned_the_right_date"]["value"] == 1.0
    assert use["overrides_breaking_a_right_tool_date"] == 1 and use["overrides_fixing_a_wrong_tool_date"] == 0
    assert metrics["llm_rules_tool"]["due_date_accuracy"]["k"] == 1  # the override made the photo late
    tool_prediction = {e["id"]: e for e in results["entries"]}["dev-tax_assessment-A1"]["conditions"][
        "llm_rules_tool"
    ]["prediction"]
    assert [(t["name"], t["ok"]) for t in tool_prediction["tools"]] == [
        ("compute_deadline", False),
        ("compute_deadline", True),
    ]
    assert tool_prediction["tools"][1]["due_date"] == tool_prediction["items"][0]["due_date"]
    assert "unknown field" in tool_prediction["tools"][0]["error"]
    tool_gallery = [g for g in results["gallery"] if g["condition"] == "llm_rules_tool"]
    assert tool_gallery and tool_gallery[0]["tool_dates"]  # what the tool had said, next to the error

    entries = {e["id"]: e for e in results["entries"]}
    assert set(entries) == set(IDS)
    photo = entries["dev-invoice_relative-A1-photo"]["conditions"]["ordnung"]
    assert [call["purpose"] for call in photo["prediction"]["calls"]] == ["transcribe", "extract"]
    assert photo["prediction"]["items"][0]["grounding"] == "model_read"
    tax = entries["dev-tax_assessment-A1"]["conditions"]["ordnung"]["prediction"]
    assert tax["delivery_scope"] == "ao" and tax["items"][0]["spec"]["anchor"] == "deemed_delivery"
    assert tax["items"][0]["explanation"]  # the rules engine's receipt summary

    gallery = results["gallery"]
    assert any(g["condition"] == "llm_only" and g["direction"] == "late" for g in gallery)

    docs = (tmp_path / "docs" / "evals.md").read_text(encoding="utf-8")
    for heading in (
        "# Benchmark",
        "## Headline",
        "## Error taxonomy",
        "## An agent with a calculator",
        "## Per family",
        "## Text vs photo",
        "## Evidence grounding",
        "## Cost and latency",
        "## Failure gallery",
        "## Method",
    ):
        assert heading in docs, heading
    assert "![Due-date accuracy" in docs and "assets/eval-due-date-accuracy." in docs
    assert "Partial run" in docs and "Dev split" in docs
    assert "three strong baselines" in docs and "**LLM + rules tool**" in docs
    assert "- LLM + rules tool − LLM only: accuracy" in docs
    assert "The date tools returned:" in docs  # the tool's answer in the failure gallery
    assert "0 failed (no valid answer after the repair attempt) and 0 not run" in docs  # n always shown
    assert "Incomplete run" not in docs
    assert outcome.chart_path is not None and outcome.chart_path.is_file()

    # The page can be re-rendered from the results JSON alone.
    rendered = tmp_path / "rerendered.md"
    assert report.main([str(path), "--docs", str(rendered), "--chart", str(tmp_path / "chart.png")]) == 0
    suffix = outcome.chart_path.suffix  # .png with matplotlib, else the SVG fallback
    assert rendered.read_text(encoding="utf-8") == docs.replace(
        f"assets/eval-due-date-accuracy{suffix}", f"chart{suffix}"
    )

    # A rerun resumes entirely from the per-letter cache and reproduces the metrics.
    again = await eval_run.run_benchmark(make_config(tmp_path, write_docs=False), backend=Refusing())
    assert again.ok
    assert again.runs[0].results is not None
    assert (
        again.runs[0].results["metrics"]["ordnung"]["due_date_accuracy"]
        == metrics["ordnung"]["due_date_accuracy"]
    )


async def test_live_run_records_and_replay_reproduces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeBackend(Responder())
    monkeypatch.setattr(eval_run, "ClaudeCLIBackend", lambda concurrency: fake)
    ids = ["dev-invoice_relative-A1-photo", "dev-tax_assessment-A1"]
    live = await eval_run.run_benchmark(make_config(tmp_path, ids=ids, live=True, write_docs=False))
    assert live.ok
    recorded = sorted(p.parent.name for p in (tmp_path / "recorded" / "sonnet").rglob("*.json"))
    assert (
        recorded.count("eval_baseline") == 6
        and recorded.count("extract") == 2
        and recorded.count("transcribe") == 1
    )
    calls = len(fake.calls)

    replay = await eval_run.run_benchmark(make_config(tmp_path, ids=ids, resume=False, write_docs=False))
    assert replay.ok
    assert len(fake.calls) == calls  # nothing went live
    live_metrics = live.runs[0].results["metrics"]  # type: ignore[index]
    replay_metrics = replay.runs[0].results["metrics"]  # type: ignore[index]
    for condition in live_metrics:
        assert replay_metrics[condition]["due_date_accuracy"] == live_metrics[condition]["due_date_accuracy"]
        assert replay_metrics[condition]["cost_usd"] == live_metrics[condition]["cost_usd"]
    # The tool calls are part of the recording: a replay sees the same calls and tool answers.
    assert replay_metrics["llm_rules_tool"]["tool_use"] == live_metrics["llm_rules_tool"]["tool_use"]
    live_tools = live.runs[0].predictions["llm_rules_tool"]["dev-tax_assessment-A1"].tools
    replayed_tools = replay.runs[0].predictions["llm_rules_tool"]["dev-tax_assessment-A1"].tools
    assert live_tools and replayed_tools == live_tools


def test_replay_miss_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = [
        "--split",
        "dev",
        "--ids",
        "dev-tax_assessment-A1",
        "--conditions",
        "llm_only",
        "--recorded-dir",
        str(tmp_path / "empty"),
        "--results-dir",
        str(tmp_path / "results"),
        "--date",
        "2026-09-25",
        "--resamples",
        "50",
        "--no-docs",
    ]
    assert eval_run.run_cli(args) == 1
    assert not list((tmp_path / "results").glob("*.json"))
    err = capsys.readouterr().err
    assert "no recorded response" in err and "--live" in err

    assert eval_run.run_cli([*args, "--allow-errors", "--quiet"]) == 0
    results = json.loads(
        (tmp_path / "results" / "2026-09-25-sonnet-dev-partial.json").read_text(encoding="utf-8")
    )
    assert results["metrics"]["llm_only"]["errors"] == 1
    assert results["metrics"]["llm_only"]["taxonomy"]["missed"] == 1


#: Letters that state a posting day later than their date: the label counts from the stated posting
#: day (§ 122 Abs. 2 AO), Ordnung deliberately keeps the letter's date (earliest plausible date,
#: docs/deadline-rules.md § 5) — VERIFICATION.md predicts exactly these early deviations.
POSTING_DAY_POLICY = {"dev-tax_assessment-B1", "test-tax_assessment-D1"}


@pytest.mark.parametrize("split", ["dev", "test"])
async def test_rules_engine_reproduces_the_labels_from_a_perfect_reading(tmp_path: Path, split: str) -> None:
    """If the model read every DateSpec exactly like the truth, which dates would still be wrong?

    Only the documented earliest-plausible-date policy may differ, and only early; everything else
    is a computing error in ``ordnung.rules`` (or a wrong label) and must be investigated.
    """
    config = make_config(
        tmp_path, split=split, ids=None, conditions=["ordnung"], resamples=20, write_docs=False
    )
    outcome = await eval_run.run_benchmark(config, backend=FakeBackend(Responder()))
    assert outcome.ok
    results = outcome.runs[0].results
    assert results is not None
    wrong = {
        entry["id"]: item
        for entry in results["entries"]
        for item in entry["conditions"]["ordnung"]["score"]["items"]
        if item["outcome"] not in ("correct", "unscored")
    }
    assert set(wrong) == POSTING_DAY_POLICY & {e["id"] for e in results["entries"]}
    assert all(item["cause"] == "computing" and item["direction"] == "early" for item in wrong.values())
    assert results["metrics"]["ordnung"]["taxonomy"]["reading"] == 0


def test_cli_rejects_bad_arguments() -> None:
    with pytest.raises(SystemExit):
        eval_run.run_cli(["--refresh"])
    with pytest.raises(SystemExit):
        eval_run.run_cli(["--conditions", "nope"])
    assert eval_run.run_cli(["--split", "dev", "--families", "no_such_family", "--quiet"]) == 1


def test_backends(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    wrapped = eval_run.make_backend(config, "claude-sonnet-4-5", {"a"})
    assert isinstance(wrapped, eval_run.RecordedFailures) and not wrapped.record
    replay = wrapped.inner
    assert isinstance(replay, ReplayBackend) and replay.fallback is None
    assert replay.root == tmp_path / "recorded" / "claude-sonnet-4-5"
    wrapped = eval_run.make_backend(make_config(tmp_path, live=True), "sonnet", {"a"})
    assert isinstance(wrapped, eval_run.RecordedFailures) and wrapped.record and wrapped.replay
    live = wrapped.inner
    assert isinstance(live, ReplayBackend) and isinstance(live.fallback, RecordingBackend)
    assert live.fallback.allowed_doc_ids == {"a"}
    wrapped = eval_run.make_backend(make_config(tmp_path, live=True, refresh=True), "sonnet", {"a"})
    assert isinstance(wrapped, eval_run.RecordedFailures) and not wrapped.replay
    assert isinstance(wrapped.inner, RecordingBackend)
    assert eval_run.safe_name("us.anthropic/claude:1") == "us.anthropic_claude_1"


async def test_recording_guard_accepts_only_benchmark_letters(tmp_path: Path) -> None:
    recorder = RecordingBackend(
        FakeBackend({"test": {"ok": True}}), tmp_path, allowed_doc_ids={"dev-tax_assessment-A1"}
    )
    await recorder.complete(
        LLMRequest(purpose="test", prompt="p", system="s", doc_ids=["dev-tax_assessment-A1"])
    )
    with pytest.raises(LLMError):
        await recorder.complete(
            LLMRequest(purpose="test", prompt="p", system="s", doc_ids=["someone-elses-letter"])
        )


def test_pending_page_and_svg_fallback(tmp_path: Path) -> None:
    docs = tmp_path / "evals.md"
    assert report.main(["--pending", "--docs", str(docs)]) == 0
    text = docs.read_text(encoding="utf-8")
    assert "Results pending" in text and "## Method" in text and "python -m evals.run --live" in text

    results = {
        "meta": {"model": "sonnet", "split": "test", "scored_items": 4, "entries": 3},
        "metrics": {
            condition: {
                "due_date_accuracy": {
                    "value": value,
                    "ci": [value - 0.1, min(1.0, value + 0.1)],
                    "k": 3,
                    "n": 4,
                },
                "by_modality": {
                    "text": {"due_date_accuracy": {"value": value, "ci": [0.5, 1.0], "k": 3, "n": 4}}
                },
            }
            for condition, value in (("ordnung", 0.75), ("llm_only", 0.5), ("llm_rules_text", 0.6))
        },
    }
    svg = report.svg_chart(results)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    for label in ("Ordnung", "LLM only", "LLM + rules text", "All letters", "Text PDFs", "75 %"):
        assert label in svg
    assert [label for label, _ in report.chart_groups(results)] == ["All letters", "Text PDFs"]


def test_manifest_views() -> None:
    entries = {entry.id: entry for entry in load_manifest(MANIFEST)}
    photo = entries["dev-invoice_relative-A1-photo"]
    assert photo.cluster == "dev-invoice_relative-A1" and photo.modality == "photo"
    assert photo.region == "NW"  # no Land in the letterhead → the persona's
    assert entries["dev-fine_bussgeld-A1"].region == "BY"
    selected = eval_run.select_entries(
        list(entries.values()), split="dev", families=["tax_assessment"], limit=1
    )
    assert [e.id for e in selected] == ["dev-tax_assessment-A1"]
    with pytest.raises(ValueError):
        eval_run.select_entries(list(entries.values()), ids=["nope"])


# --------------------------------------------------------------------------------------------------
# Review fixes: cache validity, stale recordings, failure isolation, docs only from complete runs
# --------------------------------------------------------------------------------------------------


def test_cache_file_depends_on_the_letter_inputs(tmp_path: Path) -> None:
    """A regenerated letter (or another "today") with the same id is never answered from the cache."""
    entry = {e.id: e for e in load_manifest(MANIFEST)}["dev-tax_assessment-A1"]
    config = make_config(tmp_path)
    path = eval_run.cache_path(config, "sonnet", "ordnung", entry)
    assert path.name.startswith("dev-tax_assessment-A1.") and path.suffix == ".json"
    assert eval_run.cache_path(config, "sonnet", "ordnung", entry) == path
    for change in ({"today": "2026-05-02"}, {"sha256": "1" * 64}, {"authority_region": "BY"}):
        assert eval_run.cache_path(config, "sonnet", "ordnung", entry.model_copy(update=change)) != path


def test_prompt_text_changed_without_a_version_bump_refuses_to_replay(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from evals.conditions import ordnung_prompt_hashes

    current = ordnung_prompt_hashes()
    root = tmp_path / "recorded" / "sonnet"
    eval_run.write_prompts_lock(root, current)
    assert eval_run.stale_prompts(root, current) == []
    version, _ = current["extract_system"]
    edited = {**current, "extract_system": (version, "0" * 16)}
    assert eval_run.stale_prompts(root, edited) == [f"extract_system (version {version})"]
    bumped = {**current, "extract_system": ("999", "0" * 16)}
    assert eval_run.stale_prompts(root, bumped) == []  # a new version gets new replay keys anyway
    eval_run.write_prompts_lock(root, bumped)
    assert set(eval_run.load_prompts_lock(root)["extract_system"]) == {version, "999"}

    # The lock says extract_system had other text under the current version → replay must refuse.
    lock = eval_run.load_prompts_lock(root)
    lock["extract_system"][version] = "f" * 16
    (root / eval_run.PROMPTS_LOCK).write_text(json.dumps(lock), encoding="utf-8")
    args = [
        "--split",
        "dev",
        "--ids",
        "dev-tax_assessment-A1",
        "--conditions",
        "ordnung",
        "--recorded-dir",
        str(tmp_path / "recorded"),
        "--results-dir",
        str(tmp_path / "results"),
        "--no-docs",
        "--quiet",
    ]
    assert eval_run.run_cli(args) == 1
    assert "extract_system" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()


def test_baseline_replay_key_changes_with_the_prompt_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evals import conditions

    from ordnung.llm.runtime import request_key

    entry = {e.id: e for e in load_manifest(MANIFEST)}["dev-tax_assessment-A1"]
    document = conditions.prepare_document(entry, MANIFEST.parent, tmp_path)
    before = conditions.baseline_request(entry, document, "llm_rules_text", model="sonnet")
    fingerprint_before = conditions.fingerprint("llm_rules_text", "sonnet")
    assert before.prompt_version.startswith("llm_rules_text.")
    original = conditions.load_prompt

    def edited(name: str) -> tuple[str, str]:
        version, body = original(name)
        return (version, body + "\nOne more rule.") if name == "rules_text" else (version, body)

    conditions.baseline_prompt_digest.cache_clear()
    monkeypatch.setattr(conditions, "load_prompt", edited)
    try:
        after = conditions.baseline_request(entry, document, "llm_rules_text", model="sonnet")
        assert request_key(after) != request_key(before)  # a replay miss, not a stale answer
        assert conditions.load_prompt("rules_text")[0] == original("rules_text")[0]  # same version header
        assert conditions.fingerprint("llm_rules_text", "sonnet") != fingerprint_before  # cache invalidated
    finally:
        monkeypatch.undo()
        conditions.baseline_prompt_digest.cache_clear()
    assert request_key(conditions.baseline_request(entry, document, "llm_rules_text", model="sonnet")) == (
        request_key(before)
    )


def test_baseline_refuses_pdf_pages_it_cannot_see(tmp_path: Path) -> None:
    from evals import conditions

    entry = {e.id: e for e in load_manifest(MANIFEST)}["dev-tax_assessment-A1"]
    document = conditions.prepare_document(entry, MANIFEST.parent, tmp_path)
    blank = conditions.PreparedDocument(
        entry=entry,
        file=document.file,
        pages=[
            *document.pages,
            document.pages[0].model_copy(update={"page": 2, "text": "", "text_source": "none"}),
        ],
    )
    with pytest.raises(ValueError, match="no text layer"):
        conditions.baseline_request(entry, blank, "llm_only", model="sonnet")


class Flaky:
    """Answers like the Responder, but one letter crashes and another gets unusable answers."""

    name = "flaky"

    def __init__(self) -> None:
        self.inner = FakeBackend(Responder())

    async def complete(self, req: LLMRequest) -> LLMResponse:
        if req.doc_ids == ["dev-tax_assessment-A1"]:
            raise RuntimeError("boom")
        if req.doc_ids == ["dev-contract_confirmation-A1"] and req.purpose == "eval_baseline":
            return LLMResponse(text="not json", data={"nonsense": True})
        return await self.inner.complete(req)

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:  # pragma: no cover
        raise AssertionError("unexpected stream")
        yield


async def test_one_failing_letter_does_not_crash_the_run(tmp_path: Path) -> None:
    config = make_config(tmp_path, write_docs=False)
    outcome = await eval_run.run_benchmark(config, backend=Flaky())
    run = outcome.runs[0]
    assert run.results is None and run.results_path is None  # errors → no results unless allowed
    assert {(p.condition, p.entry_id) for p in run.errors} == {
        (c, "dev-tax_assessment-A1") for c in ("ordnung", "llm_only", "llm_rules_text", "llm_rules_tool")
    }
    assert all("unexpected RuntimeError: boom" in (p.error or "") for p in run.errors)
    invalid = run.predictions["llm_only"]["dev-contract_confirmation-A1"]
    assert invalid.failed and not invalid.error  # the system's own failure: scored, not an error
    assert run.predictions["ordnung"]["dev-invoice_relative-A1-photo"].items  # the others are fine

    allowed = await eval_run.run_benchmark(
        make_config(tmp_path, write_docs=False, allow_errors=True), backend=Flaky()
    )
    metrics = allowed.runs[0].results["metrics"]  # type: ignore[index]
    for condition in ("ordnung", "llm_only", "llm_rules_text", "llm_rules_tool"):
        assert metrics[condition]["errors"] == 1 and metrics[condition]["documents"] == 3
        assert metrics[condition]["due_date_accuracy"]["n"] == 2  # the errored letter's item is missed
    assert metrics["llm_only"]["failed"] == 1
    # Only the answered photo earns remedy credit; the errored and the failed letter get none.
    assert metrics["llm_only"]["extraction"]["remedy_type"]["k"] == 1
    docs = report.render_markdown([allowed.runs[0].results])  # type: ignore[list-item]
    assert "Incomplete run" in docs and "1 not run (infrastructure errors) of 3" in docs


async def test_published_page_only_from_an_error_free_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--allow-errors`` scores missing answers as empty; that must never silently become docs/evals.md."""
    one = [e for e in load_manifest(MANIFEST) if e.id == "test-tax_assessment-C1"]
    monkeypatch.setattr(eval_run, "select_entries", lambda *args, **kwargs: list(one))
    config = make_config(tmp_path, split="test", ids=None, allow_errors=True, write_docs=None, live=True)
    outcome = await eval_run.run_benchmark(config, backend=Flaky())
    assert outcome.runs[0].results_path is not None and not outcome.runs[0].errors
    assert outcome.docs_path is not None  # complete and error-free: the page is regenerated

    # A replay recomputes the numbers but leaves the published page alone.
    replay_docs = tmp_path / "replay-docs" / "evals.md"
    config = make_config(
        tmp_path / "replay", split="test", ids=None, allow_errors=True, write_docs=None, docs_path=replay_docs
    )
    outcome = await eval_run.run_benchmark(config, backend=Flaky())
    assert outcome.runs[0].results_path is not None and not outcome.runs[0].errors
    assert outcome.docs_path is None and not replay_docs.exists()

    class Broken(Flaky):
        async def complete(self, req: LLMRequest) -> LLMResponse:
            if req.purpose == "eval_baseline":
                raise LLMError("CLI crashed")
            return await super().complete(req)

    docs = tmp_path / "docs2" / "evals.md"
    config = make_config(
        tmp_path / "second",
        split="test",
        ids=None,
        allow_errors=True,
        write_docs=None,
        docs_path=docs,
        live=True,
    )
    outcome = await eval_run.run_benchmark(config, backend=Broken())
    assert outcome.runs[0].results_path is not None and outcome.runs[0].errors
    assert outcome.docs_path is None and not docs.exists()


async def test_a_run_of_some_conditions_never_rewrites_the_published_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reviewer repro: re-recording the tool condition as documented (``--live --conditions
    llm_rules_tool``, test split) rendered docs/evals.md from that run alone — a one-row headline that
    replaced the held-out page. Only a run of every condition writes the page."""
    one = [e for e in load_manifest(MANIFEST) if e.id == "test-tax_assessment-C1"]
    monkeypatch.setattr(eval_run, "select_entries", lambda *args, **kwargs: list(one))
    docs = tmp_path / "docs" / "evals.md"
    config = make_config(
        tmp_path, split="test", ids=None, write_docs=None, live=True, conditions=["llm_rules_tool"]
    )
    assert not config.partial and not config.every_condition
    outcome = await eval_run.run_benchmark(config, backend=FakeBackend(Responder()))
    assert outcome.ok and outcome.runs[0].results_path is not None  # the results are written ...
    assert outcome.docs_path is None and not docs.exists()  # ... the page is not
    # the same run of every condition does write it
    everything = make_config(tmp_path / "all", split="test", ids=None, write_docs=None, live=True)
    assert everything.every_condition
    full = await eval_run.run_benchmark(everything, backend=FakeBackend(Responder()))
    assert full.docs_path is not None and full.docs_path.exists()


async def test_model_failures_are_recorded_and_replayed_as_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live "no structured output" must replay as the same scored failure, not as a missing recording."""

    class NoStructuredOutput(FakeBackend):
        async def complete(self, req: LLMRequest) -> LLMResponse:
            if req.purpose == "eval_baseline" and req.doc_ids == ["dev-tax_assessment-A1"]:
                self.calls.append(req)
                raise ClaudeBadOutput("Claude returned no structured output")
            return await super().complete(req)

    fake = NoStructuredOutput(Responder())
    monkeypatch.setattr(eval_run, "ClaudeCLIBackend", lambda concurrency: fake)
    ids = ["dev-tax_assessment-A1"]
    live = await eval_run.run_benchmark(make_config(tmp_path, ids=ids, live=True, write_docs=False))
    assert live.ok and not live.runs[0].errors
    failed = live.runs[0].predictions["llm_only"]["dev-tax_assessment-A1"]
    assert failed.failed and "no structured output" in failed.failed
    assert len(list((tmp_path / "recorded" / "sonnet").rglob("*.failure.json"))) == 3  # all baselines
    calls = len(fake.calls)

    replay = await eval_run.run_benchmark(make_config(tmp_path, ids=ids, resume=False, write_docs=False))
    assert replay.ok and not replay.runs[0].errors  # no "no recorded response"
    assert len(fake.calls) == calls
    again = replay.runs[0].predictions["llm_only"]["dev-tax_assessment-A1"]
    assert again.failed == failed.failed
    live_metrics = live.runs[0].results["metrics"]  # type: ignore[index]
    replay_metrics = replay.runs[0].results["metrics"]  # type: ignore[index]
    assert replay_metrics["llm_only"]["failed"] == live_metrics["llm_only"]["failed"] == 1
    assert replay_metrics["llm_only"]["due_date_accuracy"] == live_metrics["llm_only"]["due_date_accuracy"]

    # A successful re-recording replaces the stored failure.
    monkeypatch.setattr(eval_run, "ClaudeCLIBackend", lambda concurrency: FakeBackend(Responder()))
    fresh = make_config(tmp_path, ids=ids, live=True, refresh=True, resume=False, write_docs=False)
    assert (await eval_run.run_benchmark(fresh)).ok
    assert not list((tmp_path / "recorded" / "sonnet").rglob("*.failure.json"))


def _outcome(accuracy: float, late: float) -> eval_run.RunOutcome:
    metrics = {"ordnung": {"due_date_accuracy": {"value": accuracy}, "dangerous_late_rate": {"value": late}}}
    return eval_run.RunOutcome(
        runs=[eval_run.ModelRun(model="sonnet", predictions={}, results={"metrics": metrics})]
    )


def test_ci_gate_on_ordnung_accuracy_and_dangerous_late_rate() -> None:
    assert eval_run.gate_failures(_outcome(0.96, 0.0), min_accuracy=0.95, max_dangerous_late=0.0) == []
    assert eval_run.gate_failures(_outcome(0.96, 0.0)) == []  # no thresholds, no gate
    failures = eval_run.gate_failures(_outcome(0.90, 0.02), min_accuracy=0.95, max_dangerous_late=0.0)
    assert len(failures) == 2
    assert "accuracy 90.0 % < 95.0 %" in failures[0] and "dangerous-late rate 2.0 % > 0.0 %" in failures[1]


class MissingRecordings(FakeBackend):
    """A replay whose recordings for one condition are missing (its tool descriptions changed, say)."""

    def __init__(self, missing: str) -> None:
        super().__init__(Responder())
        self.missing = missing

    async def complete(self, req: LLMRequest) -> LLMResponse:
        condition = req.prompt_version.split(".", 1)[0] if req.purpose == "eval_baseline" else "ordnung"
        if condition == self.missing:
            raise ReplayMiss(f"no recorded response for {req.purpose} ({req.cache_key})")
        return await super().complete(req)


def test_the_ci_gate_leaves_out_a_baseline_without_recordings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate checks Ordnung: a changed tool description must not fail it until a live re-record."""
    args = [
        "--split",
        "dev",
        "--ids",
        "dev-tax_assessment-A1",
        "dev-invoice_relative-A1",
        "--results-dir",
        str(tmp_path / "results"),
        "--date",
        "2026-09-25",
        "--resamples",
        "50",
        "--no-docs",
        "--quiet",
    ]
    gate = [*args, "--min-accuracy", "0.95", "--max-dangerous-late", "0"]
    assert eval_run.run_cli(gate, backend=MissingRecordings("llm_rules_tool")) == 0
    err = capsys.readouterr().err
    assert "left out of the gate, recorded answers missing: llm_rules_tool" in err
    # the recipe records the condition without touching the page, then adds it to the published run
    flat = " ".join(err.split())
    assert "python -m evals.run --live --split dev --conditions llm_rules_tool" in flat
    assert "--add-condition llm_rules_tool=evals/results/<new run>.json" in flat
    results = json.loads(
        (tmp_path / "results" / "2026-09-25-sonnet-dev-partial.json").read_text(encoding="utf-8")
    )
    assert results["meta"]["conditions"] == ["ordnung", "llm_only", "llm_rules_text"]
    assert set(results["metrics"]) == {"ordnung", "llm_only", "llm_rules_text"}
    assert results["meta"]["left_out"] == {"llm_rules_tool": "recorded answers missing on replay"}
    assert "llm_rules_tool" not in results["meta"]["fingerprints"]

    # Ordnung's own recordings are what the gate is about; and without thresholds nothing is left out
    assert eval_run.run_cli([*gate, "--no-resume"], backend=MissingRecordings("ordnung")) == 1
    assert "left out" not in capsys.readouterr().err
    assert eval_run.run_cli([*args, "--no-resume"], backend=MissingRecordings("llm_rules_tool")) == 1
    loud = [arg for arg in gate if arg != "--quiet"]
    assert eval_run.run_cli([*loud, "--no-resume"], backend=MissingRecordings("llm_rules_tool")) == 0
    assert "llm_rules_tool has no recorded answer for 2 letter(s)" in capsys.readouterr().err


@pytest.mark.parametrize("condition", ["llm_only", "llm_rules_text"])
def test_the_ci_gate_fails_when_a_published_baseline_no_longer_replays(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], condition: str
) -> None:
    """A changed llm_only prompt or rules text must fail CI: their published numbers must keep replaying.
    Only the tool condition (whose replay key holds Python docstrings) may be left out."""
    gate = [
        "--split",
        "dev",
        "--ids",
        "dev-tax_assessment-A1",
        "--results-dir",
        str(tmp_path / "results"),
        "--date",
        "2026-09-25",
        "--resamples",
        "50",
        "--no-docs",
        "--min-accuracy",
        "0.95",
        "--max-dangerous-late",
        "0",
    ]
    assert eval_run.run_cli(gate, backend=MissingRecordings(condition)) == 1
    err = capsys.readouterr().err
    assert "left out" not in err and f"{condition} dev-tax_assessment-A1: " in err


async def test_rescored_run_is_shown_next_to_the_held_out_one(tmp_path: Path) -> None:
    held_out = (
        (
            await eval_run.run_benchmark(
                make_config(tmp_path, write_docs=False, allow_errors=True), backend=Flaky()
            )
        )
        .runs[0]
        .results
    )
    assert held_out is not None
    rescored = {
        **held_out,
        "meta": {
            **held_out["meta"],
            "note": "Social-law senders were read as authorities.",
            "commit": "abc1234",
        },
    }
    page = report.render_markdown([held_out], rescored=rescored)
    section = page.split("## After the held-out run", 1)[1].split("\n## ", 1)[0]
    assert "Social-law senders were read as authorities." in section and "`abc1234`" in section
    assert "no longer held-out" in section and "Held-out run (headline)" in section
    assert "## After the held-out run" not in report.render_markdown([held_out])


# --------------------------------------------------------------------------------------------------
# The fourth condition: an agent with a calculator
# --------------------------------------------------------------------------------------------------


def test_tool_condition_extends_the_llm_only_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from evals import conditions

    from ordnung.llm.runtime import request_key

    entry = {e.id: e for e in load_manifest(MANIFEST)}["dev-tax_assessment-A1"]
    document = conditions.prepare_document(entry, MANIFEST.parent, tmp_path)
    only = conditions.baseline_request(entry, document, "llm_only", model="sonnet")
    tool = conditions.baseline_request(entry, document, "llm_rules_tool", model="sonnet")
    assert only.mcp_config is None and not only.allowed_tools and only.max_budget_usd is None
    assert only.prompt_version.startswith("llm_only.s3.u2.d1.h")  # the recorded baselines keep their keys
    assert tool.prompt_version.startswith("llm_rules_tool.s3.t1.u2.d1.h")
    assert tool.prompt == only.prompt  # the same letter and question
    note = conditions.load_prompt("rules_tool")[1]
    assert tool.system == f"{only.system}\n\n{note}"  # the llm_only prompt plus one note on the tools
    assert json.loads(tool.cache_key or "")["condition"] == "llm_rules_tool"

    # A changed tool description is a changed prompt: the recorded answers must miss, not be replayed.
    conditions.baseline_prompt_digest.cache_clear()
    monkeypatch.setattr(conditions, "tool_definitions_digest", lambda: "another tool description")
    try:
        changed = conditions.baseline_request(entry, document, "llm_rules_tool", model="sonnet")
        assert request_key(changed) != request_key(tool)
        assert request_key(conditions.baseline_request(entry, document, "llm_only", model="sonnet")) == (
            request_key(only)
        )
    finally:
        monkeypatch.undo()
        conditions.baseline_prompt_digest.cache_clear()


def test_tool_uses_policy() -> None:
    from evals.conditions import tool_uses

    calls = [
        ToolCall(
            name=f"{TOOL_PREFIX}compute_deadline", input={"spec": {}}, result='{"due_date":"2026-10-21"}'
        ),
        ToolCall(
            name=f"{TOOL_PREFIX}compute_deadline", input={}, result='{"due_date":null,"summary":"No date"}'
        ),
        ToolCall(
            name=f"{TOOL_PREFIX}german_holidays", input={"year": 2026}, result='{"due_date":"2026-01-01"}'
        ),
        ToolCall(name=f"{TOOL_PREFIX}check_iban", input={"iban": "x"}, result="Error executing tool: nope"),
        ToolCall(name=f"{TOOL_PREFIX}compute_deadline", input={}, result=None),
        ToolCall(name=f"{TOOL_PREFIX}compute_deadline", input={}, result="[1, 2]"),
        ToolCall(
            name=f"{TOOL_PREFIX}add_working_days",
            input={"start": "2026-12-22", "days": 5},
            result='{"date":"2026-12-30","due_date":"2027-01-01"}',
        ),
    ]
    uses = tool_uses(calls)
    # the calculator's answer is a date too; compute_deadline's field is not read from other tools
    assert (uses[-1].name, uses[-1].date, uses[-1].due_date) == ("add_working_days", "2026-12-30", None)
    assert all(u.date is None for u in uses[:-1])
    uses = uses[:-1]
    assert [(u.name, u.ok, u.due_date) for u in uses] == [
        ("compute_deadline", True, "2026-10-21"),
        ("compute_deadline", True, None),
        ("german_holidays", True, None),  # only compute_deadline gives a due date
        ("check_iban", False, None),
        ("compute_deadline", False, None),
        ("compute_deadline", False, None),
    ]
    assert uses[3].error == "Error executing tool: nope" and uses[4].error == "no answer"


async def test_a_condition_added_later_keeps_the_published_numbers(tmp_path: Path) -> None:
    published = (
        await eval_run.run_benchmark(
            make_config(tmp_path, conditions=["ordnung", "llm_only", "llm_rules_text"], write_docs=False),
            backend=FakeBackend(Responder()),
        )
    ).runs[0]
    later = (
        await eval_run.run_benchmark(
            make_config(
                tmp_path / "later", conditions=["llm_rules_tool"], run_date="2026-09-26", write_docs=False
            ),
            backend=FakeBackend(Responder()),
        )
    ).runs[0]
    assert published.results is not None and later.results is not None and published.results_path is not None
    before = published.results

    merged = report.add_condition(before, later.results, "llm_rules_tool", note="The tool helped.")
    assert merged["meta"]["conditions"] == ["ordnung", "llm_only", "llm_rules_text", "llm_rules_tool"]
    for condition in ("ordnung", "llm_only", "llm_rules_text"):
        assert merged["metrics"][condition] == before["metrics"][condition]  # untouched
    for key, value in before["comparisons"].items():
        assert merged["comparisons"][key] == value
    assert "ordnung-vs-llm_rules_tool" in merged["comparisons"]
    assert merged["metrics"]["llm_rules_tool"] == later.results["metrics"]["llm_rules_tool"]
    added = merged["meta"]["added_conditions"]["llm_rules_tool"]
    assert (added["date"], added["backend"], added["note"]) == ("2026-09-26", "fake", "The tool helped.")
    page = report.render_markdown([merged])
    assert "LLM + rules tool was run on 2026-09-26 (fake" in page
    assert "**What this shows.** The tool helped." in page
    # a later run on changed code is marked, and never set against the held-out Ordnung as "a difference"
    assert "| **LLM + rules tool** † |" in page and "† LLM + rules tool ran on 2026-09-26" in page
    assert "Ordnung − LLM + rules tool" not in page and "LLM + rules tool − LLM only: accuracy" in page
    assert "Ordnung re-scored − LLM + rules tool" not in page  # no re-scored run to compare with
    with_rescored = report.render_markdown([merged], rescored=merged)
    assert "compare it with Ordnung re-scored after the fix" in with_rescored
    assert "Ordnung re-scored − LLM + rules tool: accuracy" in with_rescored
    assert "Compare it with Ordnung re-scored on that code" in with_rescored  # the headline's footnote
    # the chart puts the later run next to Ordnung re-scored on the same code, in a panel of its own
    held_out, fixed = report.chart_panels(merged, rescored=merged)
    assert (held_out.title, held_out.conditions) == (
        "Held-out run",
        ["ordnung", "llm_only", "llm_rules_text"],
    )
    assert (fixed.title, fixed.conditions) == (
        "After the engine fix (not held-out)",
        ["ordnung", "llm_rules_tool"],
    )
    assert fixed.groups[0][1]["ordnung"] == merged["metrics"]["ordnung"]["due_date_accuracy"]
    svg = report.svg_chart(merged, rescored=merged)
    assert "After the engine fix (not held-out)" in svg and "Held-out run" in svg
    assert "next to Ordnung's held-out outputs re-scored with it" in svg
    (alone,) = report.chart_panels(merged)  # without a re-scored run: one panel and a warning note
    assert alone.title is None and "not comparable with the held-out run" in report.svg_chart(merged)
    assert "ran later" not in report.svg_chart(before) and len(report.chart_panels(before)) == 1

    with pytest.raises(ValueError, match="differ in split"):
        report.add_condition(
            before, {**later.results, "meta": {**later.results["meta"], "split": "test"}}, "x"
        )
    partial = {**later.results, "entries": later.results["entries"][1:]}
    with pytest.raises(ValueError, match="no answer for 1 letter"):
        report.add_condition(before, partial, "llm_rules_tool")
    # the published conditions can't be swapped for another run's; a condition added later can
    for original in ("ordnung", "llm_only", "llm_rules_text"):
        with pytest.raises(ValueError, match=f"{original} is one of the run's own conditions"):
            report.add_condition(before, published.results, original)
        with pytest.raises(ValueError, match="one of the run's own conditions"):
            report.add_condition(merged, published.results, original)
    again = report.add_condition(merged, later.results, "llm_rules_tool", note="Recorded again.")
    assert again["meta"]["added_conditions"]["llm_rules_tool"]["note"] == "Recorded again."
    assert again["metrics"]["ordnung"] == before["metrics"]["ordnung"]
    # recording a condition again is never silent: the replaced recording's score stays next to the number
    first = merged["metrics"]["llm_rules_tool"]["due_date_accuracy"]
    (replaced,) = again["meta"]["added_conditions"]["llm_rules_tool"]["earlier_recordings"]
    assert (replaced["date"], replaced["k"], replaced["n"]) == ("2026-09-26", first["k"], first["n"])
    assert "earlier_recordings" not in merged["meta"]["added_conditions"]["llm_rules_tool"]
    score = f"{first['value'] * 100:.1f}".removesuffix(".0")
    page_again = report.render_markdown([again])
    footnote = next(line for line in page_again.splitlines() if line.startswith("† LLM + rules tool"))
    assert "This is the second recording of it on this split" in footnote and f"scored {score} %" in footnote
    assert f"LLM + rules tool: second recording; earlier: {score} %" in report.svg_chart(again)
    third = report.add_condition(again, later.results, "llm_rules_tool")
    assert len(third["meta"]["added_conditions"]["llm_rules_tool"]["earlier_recordings"]) == 2
    assert "This is the third recording" in report.render_markdown([third])
    # what every recording cost (both splits, kept by hand) is shown with it and survives a replacement
    assert "Recording it cost" not in report.render_markdown([third])
    third["meta"]["added_conditions"]["llm_rules_tool"]["recording_spend"] = [
        {"split": "dev", "commit": "a", "calls": 28, "cost_usd": 1.4477},
        {"split": "test", "commit": "a", "calls": 63, "cost_usd": 3.4003},
        {"split": "test", "commit": "b", "calls": 63, "cost_usd": 3.5036},
    ]
    fourth = report.add_condition(third, later.results, "llm_rules_tool")
    spent = next(
        line
        for line in report.render_markdown([fourth]).splitlines()
        if line.startswith("† LLM + rules tool")
    )
    assert (
        "Recording it cost at least $8.35 (API-equivalent): 3 live recordings, in order dev $1.45; test "
        "$3.40, $3.50, plus smoke runs of a few letters whose cost was not recorded." in spent
    )
    assert "budget" not in spent
    # the page says how to record the added condition again without replacing it (reviewer: only --help did)
    reproduce = report.render_markdown([fourth]).split("## Reproduce", 1)[1]
    assert "--conditions llm_rules_tool`, which never rewrites this page" in reproduce
    assert "--add-condition llm_rules_tool=evals/results/<new run>.json" in reproduce
    assert "--add-condition" not in report.render_markdown([before]).split("## Reproduce", 1)[1]
    # with the budget set for it, the page says plainly whether it was kept (reviewer: $14.91 of "well
    # under $15", smoke runs uncounted, was reported as "at the ceiling")
    fourth["meta"]["added_conditions"]["llm_rules_tool"]["recording_budget_usd"] = 9
    fifth = report.add_condition(fourth, later.results, "llm_rules_tool")
    assert fifth["meta"]["added_conditions"]["llm_rules_tool"]["recording_budget_usd"] == 9  # carried over
    over = report.recording_spend_text(fifth["meta"]["added_conditions"]["llm_rules_tool"])
    assert over.endswith(
        "The budget for recording it was $9.00, to stay well under: the counted spend alone came within a "
        "tenth of it, and the smoke runs come on top, so that budget was not kept."
    )
    fifth["meta"]["added_conditions"]["llm_rules_tool"]["recording_budget_usd"] = 15
    kept = report.recording_spend_text(fifth["meta"]["added_conditions"]["llm_rules_tool"])
    assert kept.endswith("The budget for recording it was $15.00.") and "not kept" not in kept
    # the re-scored table does not put a condition recorded after the fix under "held-out"
    rescored_section = report.render_markdown([again], rescored=again).split("## After the held-out run", 1)[
        1
    ]
    row = next(line for line in rescored_section.splitlines() if line.startswith("| **LLM + rules tool**"))
    assert "n/a (recorded after the fix)" in row
    ordnung_row = next(line for line in rescored_section.splitlines() if line.startswith("| **Ordnung**"))
    assert "n/a" not in ordnung_row

    # The same through the CLI, rewriting the published results file in place.
    later_path = tmp_path / "later.json"
    report.write_json(later_path, later.results)
    note = tmp_path / "note.md"
    note.write_text("Written after\nlooking at the data.\n", encoding="utf-8")
    docs = tmp_path / "evals.md"
    args = [
        str(published.results_path),
        "--add-condition",
        f"llm_rules_tool={later_path}",
        "--note",
        str(note),
    ]
    assert report.main([*args, "--docs", str(docs), "--chart", str(tmp_path / "chart.png")]) == 0
    rewritten = report.load_results(published.results_path)
    assert (
        rewritten["meta"]["added_conditions"]["llm_rules_tool"]["note"]
        == "Written after looking at the data."
    )
    assert "## An agent with a calculator" in docs.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        report.main([str(published.results_path), "--add-condition", "llm_rules_tool"])
    held_out = published.results_path.read_bytes()
    with pytest.raises(SystemExit):  # a usage error, not a traceback, and the file is untouched
        report.main([str(published.results_path), "--add-condition", f"ordnung={later_path}"])
    assert published.results_path.read_bytes() == held_out
