"""The benchmark's plumbing for the check for incomplete readings (``ingest/gaps.py``), round 2 of its review:
the code's own to-dos count apart from the reading's (benchmark N1, N2; tests R2T-7), P5's signal is emitted
(R2T-6), and the command line refuses only what it should (R2T-8, benchmark N3). Replay only: no model call,
nothing written to ``evals/results``."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import report  # noqa: E402
from evals import run as eval_run  # noqa: E402
from evals.conditions import CallLog, MeteredBackend, prepare_document, run_ordnung  # noqa: E402
from evals.metrics import score_document, summarise_condition, taxonomy  # noqa: E402
from evals.records import PredictedItem, Prediction, load_manifest  # noqa: E402

from ordnung.llm.fake import FakeBackend  # noqa: E402
from ordnung.llm.runtime import LLMService  # noqa: E402

MANIFEST = ROOT / "evals" / "dataset" / "manifest.json"
EMPTY_READING = "holdout2-adversarial-injection_visible-1"


def _entry(entry_id: str) -> Any:
    return {e.id: e for e in load_manifest(MANIFEST)}[entry_id]


def test_an_unmatched_code_made_to_do_is_counted_as_the_check_s_false_alarm_never_the_reading_s() -> None:
    """N1, R2T-7: no false positive of the reading's — a false alarm of the check's, counted apart."""
    entry = _entry("dev-contract_confirmation-A1")
    code = PredictedItem(kind="deadline", title="Deadline to object", due_date="2031-01-01", origin="code")
    model = code.model_copy(update={"origin": "model"})
    by_code = score_document(
        entry, Prediction(entry_id=entry.id, condition="ordnung", model="m", items=[code])
    )
    by_model = score_document(
        entry, Prediction(entry_id=entry.id, condition="ordnung", model="m", items=[model])
    )
    assert (by_model.false_positives, by_code.false_positives) == (1, 0)
    assert (by_code.check_filed, by_code.check_false_alarms) == (1, 1)
    assert (by_model.check_filed, by_model.check_false_alarms) == (0, 0)
    assert summarise_condition([by_code], resamples=50)["reading_check"] == {
        "filed": 1,
        "unmatched": 1,
        "letters": 0,
    }


def test_only_dated_unmatched_code_items_are_the_check_s_false_alarms() -> None:
    """R3T-10: a matched dated code item, an undated one (the placeholder) and a stray dated one: two filed, one
    unmatched."""
    entry = _entry("dev-municipal_decision-A1")
    [truth] = entry.truth.items[:1]
    matched = PredictedItem(kind=truth.kind, title=truth.title, due_date=truth.expected_due, origin="code")
    undated = PredictedItem(kind="task", title="Read this letter yourself", origin="code")
    stray = PredictedItem(kind="deadline", title="Deadline to object", due_date="2031-01-01", origin="code")
    score = score_document(
        entry, Prediction(entry_id=entry.id, condition="ordnung", model="m", items=[matched, undated, stray])
    )
    assert (score.check_filed, score.check_false_alarms) == (2, 1)
    assert summarise_condition([score], resamples=50)["reading_check"] == {
        "filed": 2,
        "unmatched": 1,
        "letters": 0,
    }


def test_the_check_s_to_do_never_takes_the_match_from_the_reading_s_own() -> None:
    """Benchmark review 3, R3B-1: a reading's objection to-do whose date doesn't compute (no letter date read)
    beside the check's dated one: the reading's recall, false positives and grounding are as without the check;
    the letter's date is the check's, correct."""
    entry = _entry("dev-municipal_decision-A1")
    truth = entry.truth.items[0]
    spec = {
        "type": "relative",
        "amount": 1,
        "unit": "months",
        "anchor": "document_date",
        "nature": "objection",
    }
    model = PredictedItem(kind=truth.kind, title=truth.title, due_date=None, spec=spec, origin="model")
    code = PredictedItem(
        kind="deadline",
        title="Deadline to object",
        due_date=truth.expected_due,
        spec=spec,
        origin="code",
        needs_check=True,
        confidence="low",
    )

    def scored(*items: PredictedItem) -> Any:
        return score_document(
            entry, Prediction(entry_id=entry.id, condition="ordnung", model="m", items=list(items))
        )

    alone, beside = scored(model), scored(model, code)
    reading = lambda s: (s.matched_required, s.false_positives, s.false_grounded, s.grounding)  # noqa: E731
    assert reading(beside) == reading(alone)
    assert beside.items[0].outcome == "correct"
    assert (beside.check_filed, beside.check_false_alarms) == (1, 0)


def test_the_letters_the_check_fired_on_are_counted_dated_or_not() -> None:
    """R3B-3: an undated to-do of the check's is never scored; the letters with its signal are counted."""
    entry = _entry("dev-contract_confirmation-A1")
    signalled = Prediction(
        entry_id=entry.id, condition="ordnung", model="m", items=[], signals=["reading_incomplete"]
    )
    quiet = Prediction(entry_id=entry.id, condition="ordnung", model="m", items=[])
    summary = summarise_condition(
        [score_document(entry, signalled), score_document(entry, quiet)], resamples=50
    )
    assert summary["reading_check"] == {"filed": 0, "unmatched": 0, "letters": 1}


def test_a_wrong_code_made_date_is_the_check_s_never_the_reading_s_or_the_computing_s() -> None:
    """N2, R2T-7: its cause is "check", and the taxonomy page gets a row for it."""
    entry = _entry("dev-municipal_decision-A1")
    [truth] = entry.truth.items[:1]
    assert truth.expected_due is not None
    day = report.parse_iso(truth.expected_due)
    assert day is not None
    wrong = (day.replace(day=1) if day.day != 1 else day.replace(day=2)).isoformat()
    spec = {
        "type": "relative",
        "amount": 1,
        "unit": "months",
        "anchor": "explicit_date",
        "anchor_date": "2025-05-01",
    }
    item = PredictedItem(kind=truth.kind, title=truth.title, due_date=wrong, spec=spec, origin="code")
    score = score_document(entry, Prediction(entry_id=entry.id, condition="ordnung", model="m", items=[item]))
    outcome = next(o for o in score.items if o.outcome == "wrong")
    assert (outcome.cause, outcome.reading_diffs, outcome.grounding) == ("check", [], None)
    tax = taxonomy([score])
    assert (tax["check"], tax["reading"], tax["computing"]) == (1, 0, 0)


def test_the_taxonomy_page_names_the_check_s_wrong_dates_only_when_there_are_any() -> None:
    def results(check: int) -> dict[str, Any]:
        tax = {
            "n": 10, "correct": 9, "wrong": 1, "reading": 1 - check, "computing": 0, "declined": 0, "missed": 0,
            "late": 0, "early": 1, "flagged_wrong": 1, "region_ignored": 0, "lucky_reading": 0, "reading_fields": {},
            "check": check,
        }  # fmt: skip
        return {"metrics": {"ordnung": {"taxonomy": tax}}, "meta": {"conditions": ["ordnung"]}}

    row = "Wrong — date filed by the reading check"
    assert row in report._taxonomy_section(results(1))
    assert row not in report._taxonomy_section(results(0))


async def test_an_objection_date_long_after_the_letter_s_notice_is_signalled(tmp_path: Path) -> None:
    """R2T-6: the benchmark says when the letter's notice replaced a reading's objection date."""
    entry = _entry("dev-municipal_decision-A1")
    document = prepare_document(entry, MANIFEST.parent, tmp_path)
    reading = {
        "kind": "authority_letter",
        "title": "Decision",
        "summary": "A decision.",
        "explanation": "Read it.",
        "items": [
            {
                "kind": "deadline",
                "title": "Objection",
                "date": {"type": "fixed", "date": "2099-06-30", "nature": "objection"},
                "quote": "",
            }
        ],
    }
    llm = LLMService(MeteredBackend(FakeBackend(lambda request: reading), CallLog(), timeout_s=60))
    prediction = await run_ordnung(entry, document, llm, model="claude-sonnet-5")
    assert prediction.failed is None
    assert "objection_after_notice" in prediction.signals
    assert all(item.due_date is None or item.due_date < "2099-06-30" for item in prediction.items)


def test_a_held_out_replay_into_its_own_results_dir_runs(tmp_path: Path) -> None:
    """R2T-8: the documented held-out replay (with its own --results-dir) still runs."""
    out = tmp_path / "replayed"
    code = eval_run.run_cli(
        [
            "--split", "holdout2", "--model", "claude-sonnet-5", "--conditions", "ordnung", "--no-docs",
            "--no-resume", "--ids", EMPTY_READING, "--results-dir", str(out), "--quiet", "--allow-errors",
        ]
    )  # fmt: skip
    assert code == 0
    assert list(out.glob("*-holdout2-partial.json"))


def test_the_gate_may_replay_a_held_out_split_where_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N3: the threshold gate writes no results file, so it needs no --results-dir (its cache goes to a scratch
    folder here, never evals/results)."""
    monkeypatch.setattr(eval_run, "RESULTS_DIR", tmp_path / "results")
    code = eval_run.run_cli(
        [
            "--split", "holdout2", "--model", "claude-sonnet-5", "--conditions", "ordnung", "--no-resume",
            "--ids", EMPTY_READING, "--min-accuracy", "0", "--max-dangerous-late", "1", "--quiet",
        ]
    )  # fmt: skip
    assert code == 0
    assert not list((tmp_path / "results").glob("*.json"))


def test_a_live_held_out_recording_needs_no_results_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2T-8: only a replay of a held-out split is held to its own folder; a live recording is the held-out run
    (the model is faked here)."""
    monkeypatch.setattr(eval_run, "RESULTS_DIR", tmp_path / "results")
    reading = {"kind": "other", "title": "Letter", "summary": "A letter.", "explanation": "Read it."}
    code = eval_run.run_cli(
        [
            "--split", "holdout2", "--live", "--model", "claude-sonnet-5", "--conditions", "ordnung", "--no-docs",
            "--no-resume", "--ids", EMPTY_READING, "--quiet", "--allow-errors",
            "--recorded-dir", str(tmp_path / "recorded"),
        ],
        backend=FakeBackend(lambda request: reading),
    )  # fmt: skip
    assert code == 0


def test_a_partial_replay_never_overwrites_a_live_partial_recording(tmp_path: Path) -> None:
    """R2T-8: the refusal holds for a partial results file too, and says what to do."""
    results = tmp_path / "results"
    results.mkdir()
    name = report.results_filename("2026-09-25", "claude-sonnet-5", "holdout2", partial=True)
    (results / name).write_text(json.dumps({"meta": {"backend": "live"}}), encoding="utf-8")
    config = eval_run.RunConfig(
        split="holdout2",
        ids=[EMPTY_READING],
        conditions=["ordnung"],
        results_dir=results,
        run_date="2026-09-25",
        write_docs=False,
        resamples=50,
    )
    with pytest.raises(
        ValueError, match=r"holds a live recording.*pass a different --results-dir \(or --date\)"
    ):
        import asyncio

        asyncio.run(eval_run.run_benchmark(config))
    assert json.loads((results / name).read_text(encoding="utf-8"))["meta"]["backend"] == "live"


def test_the_re_scored_row_is_said_to_be_informed_by_the_held_out_run_not_its_errors() -> None:
    held = report.load_results(ROOT / "evals" / "results" / "2026-10-01-claude-sonnet-5-holdout2.json")
    rescored = {**held, "meta": {**held["meta"], "commit": "abc1234", "note": ""}}
    text = report._holdout_rescored_note(held, rescored)
    assert "informed by it," in text and "informed by its errors" not in text
