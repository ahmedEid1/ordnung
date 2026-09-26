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
from datetime import timedelta
from pathlib import Path
from typing import Any

import pdfplumber
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import report  # noqa: E402
from evals import run as eval_run  # noqa: E402
from evals.records import Entry, TruthItem, load_manifest  # noqa: E402

from ordnung.llm.base import ClaudeBadOutput, LLMError, LLMRequest, LLMResponse, StreamEvent  # noqa: E402
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

    def __call__(self, req: LLMRequest) -> dict[str, Any]:
        entry = self.entries[req.doc_ids[0]]
        if req.purpose == "transcribe":
            return {"text": self.text(entry), "language": "de", "legible": True}
        if req.purpose == "extract":
            return self.extraction(entry)
        assert req.purpose == "eval_baseline"
        condition = req.prompt_version.split(".", 1)[0]
        return self.baseline(entry, late=condition == "llm_only")

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


async def test_all_three_conditions_end_to_end(tmp_path: Path) -> None:
    backend = FakeBackend(Responder())
    config = make_config(tmp_path)
    outcome = await eval_run.run_benchmark(config, backend=backend)

    assert outcome.ok
    purposes = sorted(req.purpose for req in backend.calls)
    assert purposes.count("transcribe") == 1  # only the photo
    assert purposes.count("extract") == 3
    assert purposes.count("eval_baseline") == 6
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
    assert set(meta["fingerprints"]) == {"ordnung", "llm_only", "llm_rules_text"}

    metrics = results["metrics"]
    assert list(metrics) == ["ordnung", "llm_only", "llm_rules_text"]
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
        recorded.count("eval_baseline") == 4
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
        (c, "dev-tax_assessment-A1") for c in ("ordnung", "llm_only", "llm_rules_text")
    }
    assert all("unexpected RuntimeError: boom" in (p.error or "") for p in run.errors)
    invalid = run.predictions["llm_only"]["dev-contract_confirmation-A1"]
    assert invalid.failed and not invalid.error  # the system's own failure: scored, not an error
    assert run.predictions["ordnung"]["dev-invoice_relative-A1-photo"].items  # the others are fine

    allowed = await eval_run.run_benchmark(
        make_config(tmp_path, write_docs=False, allow_errors=True), backend=Flaky()
    )
    metrics = allowed.runs[0].results["metrics"]  # type: ignore[index]
    for condition in ("ordnung", "llm_only", "llm_rules_text"):
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
    assert len(list((tmp_path / "recorded" / "sonnet").rglob("*.failure.json"))) == 2  # both baselines
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


def test_the_benchmarks_rule_context_marks_court_letters_as_the_app_does() -> None:
    """Review round 4: like ``ingest.plan.rule_context``, a court's (or labour court's) letter is marked as
    one from the sender's name, and the end a termination announces is graded against the pages."""
    from evals.conditions import ordnung_rule_context

    from ordnung.models import DocumentExtraction, Page

    entry = next(iter(load_manifest(MANIFEST)))
    court = DocumentExtraction.model_validate(
        {
            "kind": "authority_letter",
            "title": "Mahnbescheid",
            "summary": "",
            "explanation": "",
            "sender": {"name": "Arbeitsgericht Berlin", "kind": "authority"},
        }
    )
    ctx = ordnung_rule_context(entry, court)
    assert ctx.court and ctx.labour_court
    other = court.model_copy(update={"sender": court.sender.model_copy(update={"name": "Stadtwerke"})})  # type: ignore[union-attr]
    assert not ordnung_rule_context(entry, other).court
    quote = "hiermit kündigen wir das Mietverhältnis fristgerecht zum 31.03.2027."
    notice = DocumentExtraction.model_validate(
        {
            **court.model_dump(),
            "change": {"type": "termination_by_provider", "effective_date": "2027-05-31", "quote": quote},
        }
    )
    page = Page(
        doc_id="x", page=1, width=1, height=1, text=quote, words=[], text_source="text", image_path=""
    )
    assert ordnung_rule_context(entry, notice, [page]).end_date_grounding == "none"  # misread end
