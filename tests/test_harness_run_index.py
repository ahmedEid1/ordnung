"""The run index (``--repeat N``) and the split registry (``evals/harness.py``, ``evals/splits.py``).

A repeat is a fresh sample of the same request: run 1 keeps every replay key it ever had, runs 2 and 3 get keys of
their own (``cache_key|repeat=N``), and what the ``claude`` CLI is sent — its argv and its stdin — is byte for byte
the same in every run, because ``cache_key`` is never sent. A repeat can never be answered from run 1's
recordings, and its prediction cache, results file and ``meta`` say which run it is.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import harness, report, splits  # noqa: E402
from evals import run as eval_run  # noqa: E402
from evals.gen.common import SPLIT_VARIANTS  # noqa: E402
from evals.records import load_manifest  # noqa: E402

from ordnung.llm.base import LLMRequest, LLMResponse, StreamEvent  # noqa: E402
from ordnung.llm.claude_cli import ClaudeCLIBackend, build_user_message  # noqa: E402
from ordnung.llm.fake import FakeBackend  # noqa: E402
from ordnung.llm.runtime import request_key  # noqa: E402
from test_evals_run import Responder, make_config  # noqa: E402

FAKE_CLAUDE = ROOT / "tests" / "fake_claude.py"
#: A photo (transcribed by Ordnung, attached as an image for the baselines) and a text letter, both in dev.
REAL_IDS = ["dev-invoice_relative-A1-photo", "dev-tax_assessment-A1"]


def _request(**overrides: Any) -> LLMRequest:
    values: dict[str, Any] = {
        "purpose": "extract",
        "prompt": "p",
        "system": "s",
        "doc_ids": ["dev-tax_assessment-A1"],
        "cache_key": "doc|today",
        "prompt_version": "11.3",
    }
    values.update(overrides)
    return LLMRequest(**values)


# --------------------------------------------------------------------------------------------------
# The key of a repeat
# --------------------------------------------------------------------------------------------------


def test_run_one_keeps_its_request_and_its_key() -> None:
    req = _request()
    assert harness.repeat_request(req, 1) is req
    assert request_key(harness.repeat_request(req, 1)) == request_key(req)


def test_a_repeat_suffixes_the_cache_key_or_the_prompt_s_hash() -> None:
    req = _request()
    assert harness.repeat_request(req, 2).cache_key == "doc|today|repeat=2"
    bare = _request(cache_key=None, prompt="the whole prompt")
    digest = hashlib.sha256(b"the whole prompt").hexdigest()
    assert harness.repeat_request(bare, 3).cache_key == f"{digest}|repeat=3"
    keys = {request_key(harness.repeat_request(req, n)) for n in (1, 2, 3)}
    assert len(keys) == 3
    with pytest.raises(ValueError):
        harness.repeat_request(req, 0)


class _Recorder:
    name = "recorder"

    def __init__(self) -> None:
        self.seen: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.seen.append(req)
        return LLMResponse(text="ok", backend=self.name)

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        self.seen.append(req)
        yield StreamEvent(type="done", response=LLMResponse(text="ok", backend=self.name))


async def test_the_repeat_wrapper_keys_complete_and_stream_alike() -> None:
    inner = _Recorder()
    backend = harness.RepeatKey(inner, 2)
    await backend.complete(_request())
    events = [event async for event in backend.stream(_request(purpose="ask"))]
    assert [event.type for event in events] == ["done"]
    assert [req.cache_key for req in inner.seen] == ["doc|today|repeat=2", "doc|today|repeat=2"]
    assert backend.name == "recorder"


class _WireCapture:
    """Wraps the replay stack: for each request, what the CLI would get in runs 1, 2 and 3 (built while the
    rendered page images still exist)."""

    name = "replay"

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.cli = ClaudeCLIBackend()
        self.rows: list[dict[str, Any]] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        runs = [harness.repeat_request(req, n) for n in (1, 2, 3)]
        self.rows.append(
            {
                "keys": [request_key(r) for r in runs],
                "argv": [self.cli.build_args(r) for r in runs],
                "stdin": [build_user_message(r)[0] for r in runs],
                "unchanged": request_key(runs[0]) == request_key(req),
            }
        )
        response: LLMResponse = await self.inner.complete(req)
        return response

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:  # pragma: no cover
        raise AssertionError("the benchmark does not stream")
        yield


async def test_repeats_get_new_keys_and_send_the_cli_the_same_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORDNUNG_CLAUDE_BIN", str(FAKE_CLAUDE))  # build_args names a binary; nothing runs
    config = eval_run.RunConfig(
        split="dev",
        ids=list(REAL_IDS),
        results_dir=tmp_path,
        write_docs=False,
        resamples=20,
        run_date="2026-10-29",
    )
    allowed = {entry.id for entry in load_manifest(config.manifest_path)}
    capture = _WireCapture(eval_run.make_backend(config, eval_run.DEFAULT_MODEL, allowed))
    outcome = await eval_run.run_benchmark(config, backend=capture)
    assert outcome.ok
    rows = capture.rows
    assert len(rows) >= 9  # 2 letters × 3 baselines, plus Ordnung's transcription and extractions
    assert all(row["unchanged"] for row in rows)
    for index in range(3):
        keys = [row["keys"][index] for row in rows]
        assert len(set(keys)) == len(keys)
    first, second, third = ({row["keys"][n] for row in rows} for n in range(3))
    assert not first & second and not first & third and not second & third
    assert all(row["argv"][0] == row["argv"][1] == row["argv"][2] for row in rows)
    assert all(row["stdin"][0] == row["stdin"][1] == row["stdin"][2] for row in rows)


def test_a_repeat_is_never_answered_from_run_one_s_recordings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--split", "dev", "--ids", *REAL_IDS, "--results-dir", str(tmp_path), "--date", "2026-10-29"]
    args += ["--resamples", "20", "--no-docs", "--quiet"]
    assert eval_run.run_cli([*args, "--repeat", "2"]) == 1
    err = capsys.readouterr().err
    assert "no recorded response" in err and "prediction(s) failed to run" in err
    assert not list(tmp_path.glob("*.json"))
    # run 1 is the published run: it replays as before
    assert eval_run.run_cli(args) == 0
    assert [path.name for path in tmp_path.glob("*.json")] == ["2026-10-29-claude-sonnet-5-dev-partial.json"]


async def test_a_repeat_has_its_own_cache_results_file_recordings_and_meta(tmp_path: Path) -> None:
    fake = FakeBackend(Responder())
    config = make_config(tmp_path, live=True, write_docs=False, repeat=2, live_backend=fake)
    outcome = await eval_run.run_benchmark(config)
    assert outcome.ok
    run = outcome.runs[0]
    assert run.results_path is not None
    assert run.results_path.name == "2026-09-25-claude-sonnet-5-dev-r2-partial.json"
    assert run.results is not None and run.results["meta"]["repeat"] == 2
    cached = sorted((tmp_path / "results" / "cache").rglob("*.json"))
    assert cached and all("r2" in path.relative_to(tmp_path / "results" / "cache").parts for path in cached)
    # every call was run 2's (its key; the CLI never sends a cache key: see the wire test above)
    assert all((req.cache_key or "").endswith("|repeat=2") for req in fake.calls)
    root = tmp_path / "recorded" / eval_run.DEFAULT_MODEL
    cassettes = [p for p in root.rglob("*.json") if p.parent != root]  # not the prompts and request locks
    assert len(cassettes) == len(fake.calls)
    stored = [json.loads(p.read_text(encoding="utf-8"))["request"]["cache_key"] for p in cassettes]
    assert all(key.endswith("|repeat=2") for key in stored)
    # the request lock names each repeat's entry and the run-1 entry it repeats
    lock = json.loads((root / harness.LOCK_FILE).read_text(encoding="utf-8"))
    assert len(lock) == len(cassettes)
    for key, entry in lock.items():
        assert entry["repeat"] == 2
        assert entry["of"] != key and entry["of"].split("/")[0] == key.split("/")[0]
    # run 1 of the same letters is still to record: nothing of run 2 answers it
    again = await eval_run.run_benchmark(
        make_config(tmp_path, live=True, write_docs=False, live_backend=fake)
    )
    assert again.ok
    assert len(fake.calls) == 2 * len(cassettes)


def test_the_cli_checks_the_repeat_and_the_recording_options() -> None:
    for bad in (
        ["--repeat", "0"],
        ["--max-cost-usd", "5"],  # a replay spends nothing
        ["--wait-on-limit", "2"],
        ["--live", "--max-cost-usd", "-1"],
    ):
        with pytest.raises(SystemExit):
            eval_run.run_cli(bad)


# --------------------------------------------------------------------------------------------------
# The live smoke, dry-run against a fake claude that answers (no model)
# --------------------------------------------------------------------------------------------------


def _answering_claude(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the CLI at ``tests/fake_claude.py`` answering every call with a valid baseline record; its log."""
    record = {
        "kind": "tax_letter",
        "sender_name": "x",
        "document_date": None,
        "items": [],
        "remedy_type": "none",
    }
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "",
        "structured_output": record,
        "total_cost_usd": 0.001,
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "duration_ms": 5,
        "modelUsage": {eval_run.DEFAULT_MODEL: {}},
    }
    log = tmp_path / "calls.jsonl"
    scenario = tmp_path / "answer.json"
    scenario.write_text(
        json.dumps({"log": str(log), "calls": [{"lines": [json.dumps(result)]}]}), encoding="utf-8"
    )
    monkeypatch.setenv("ORDNUNG_CLAUDE_BIN", str(FAKE_CLAUDE))
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", str(scenario))
    return log


@pytest.mark.slow  # replays or records a whole run: once, in backend-slow, without coverage
def test_the_live_smoke_checks_a_repeat_against_run_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _answering_claude(tmp_path, monkeypatch)
    scratch = tmp_path / "smoke"
    report = harness.run_smoke(
        scratch, ids=REAL_IDS, conditions=["llm_only"], cap=0.5, recorder_lock=tmp_path / "recording.lock"
    )
    assert report["recorder_lock_refuses_a_second_recording"] and report["zero_budget_stops_before_any_call"]
    assert report["recording_exit"] == 0 and report["ok"], report
    checks = report["benchmark"]
    assert checks["calls"] == checks["cassettes"] == checks["locked"] == checks["repeated"] == 2
    assert checks["keys_differ_from_run_1"] and checks["requests_identical_to_run_1"]
    assert checks["one_ledger_line_per_call"] and checks["within_budget"] and checks["spent_usd"] == 0.002
    assert checks["answers_compared"] == checks["answers_that_differ_from_run_1"] == 2  # a fake is not run 1
    assert report["ask"] == "not asked"
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2  # the refusals asked nothing
    assert json.loads((scratch / "smoke.json").read_text(encoding="utf-8")) == report
    with pytest.raises(harness.HarnessError):  # always into a fresh folder
        harness.run_smoke(scratch, ids=REAL_IDS, recorder_lock=tmp_path / "recording.lock")


#: Three Ask questions of the development set, recorded at run 1.
ASK_IDS = ["deadline-steuerbescheid_2025-0", "cross-pay-this-week", "none-car-insurance"]


@pytest.mark.slow  # replays or records a whole run: once, in backend-slow, without coverage
def test_the_live_smoke_asks_its_ask_turns_and_judges_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With Ask turns, the smoke records them at run 2 into its scratch folder (``--recorded-dir``) and is ok only
    when Ask ran: every turn asked once, under keys of its own, with run 1's request, one ledger line per call."""
    log = _answering_claude(tmp_path, monkeypatch)
    scenario = json.loads(Path(tmp_path / "answer.json").read_text(encoding="utf-8"))
    benchmark = scenario["calls"][0]
    text = "I could not find that in your letters."  # an Ask answer that calls no tool
    said = {
        "type": "assistant",
        "message": {
            "model": eval_run.DEFAULT_MODEL,
            "id": "m",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "stop_reason": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    }
    done = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "duration_ms": 5,
        "num_turns": 1,
        "result": text,
        "total_cost_usd": 0.001,
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "modelUsage": {eval_run.DEFAULT_MODEL: {}},
    }
    scenario["calls"] = [benchmark, benchmark, {"lines": [json.dumps(said), json.dumps(done)]}]
    (tmp_path / "answer.json").write_text(json.dumps(scenario), encoding="utf-8")
    scratch = tmp_path / "smoke"
    report = harness.run_smoke(
        scratch,
        ids=REAL_IDS,
        conditions=["llm_only"],
        ask_only=ASK_IDS,
        cap=0.5,
        recorder_lock=tmp_path / "recording.lock",
    )
    assert report["ask_exit"] == 0, report
    ask = report["ask"]
    assert ask["calls"] == ask["cassettes"] == ask["locked"] == ask["repeated"] == len(ASK_IDS)
    assert ask["keys_differ_from_run_1"] and ask["requests_identical_to_run_1"]
    assert ask["one_ledger_line_per_call"] and report["ok"], report
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2 + len(ASK_IDS)
    assert (scratch / "ask" / eval_run.DEFAULT_MODEL).is_dir()  # recorded where the smoke said, nowhere else
    assert not (tmp_path / "recording.lock").exists()


def test_the_smoke_is_not_ok_when_its_ask_turns_do_not_run() -> None:
    """A smoke asked for Ask turns is ok only with the Ask checks passed (never on the benchmark's alone)."""
    benchmark = {
        "keys_differ_from_run_1": True,
        "repeated": 2,
        "requests_identical_to_run_1": True,
        "one_ledger_line_per_call": True,
        "within_budget": True,
    }
    report = {
        "recorder_lock_refuses_a_second_recording": True,
        "zero_budget_stops_before_any_call": True,
        "recording_exit": 0,
        "benchmark": benchmark,
    }
    assert harness.smoke_ok(report, ids=["a", "b"], ask_only=[])
    failed = {
        **report,
        "ask_exit": 2,
        "ask": {**benchmark, "calls": 0, "repeated": 0, "keys_differ_from_run_1": False},
    }
    assert not harness.smoke_ok(failed, ids=["a", "b"], ask_only=["q1", "q2", "q3"])
    passed = {**report, "ask_exit": 0, "ask": {**benchmark, "calls": 3, "repeated": 3}}
    assert harness.smoke_ok(passed, ids=["a", "b"], ask_only=["q1", "q2", "q3"])
    assert not harness.smoke_ok({**report, "ask": "not run"}, ids=["a", "b"], ask_only=["q1"])


def test_the_ask_command_takes_a_recordings_folder(tmp_path: Path) -> None:
    from evals.ask.__main__ import parse_args

    args = parse_args(["--live", "--recorded-dir", str(tmp_path), "--recorder-lock", str(tmp_path / "lock")])
    assert args.recorded_dir == tmp_path and args.recorder_lock == tmp_path / "lock"


# --------------------------------------------------------------------------------------------------
# The split registry
# --------------------------------------------------------------------------------------------------


def test_the_registry_declares_every_split_and_the_final_ones_before_their_letters() -> None:
    assert splits.names() == ("dev", "test", "holdout", "holdout2", "holdout3", "holdout4", "newkinds")
    # a run over every split replays the recorded ones (E2's G1 guard iterates SPLITS); --split takes all
    assert eval_run.SPLITS == splits.recorded()
    split_option = next(a for a in eval_run.build_parser()._actions if a.dest == "split")
    assert tuple(split_option.choices or ()) == splits.names()
    assert splits.recorded() == ("dev", "test", "holdout", "holdout2", "holdout3")
    assert [s.name for s in splits.REGISTRY if s.role == "final"] == ["holdout4", "newkinds"]
    assert splits.get("holdout4").variants == ("K", "L", "M", "N")
    assert all(
        splits.is_held_out(name) for name in ("holdout", "holdout2", "holdout3", "holdout4", "newkinds")
    )
    assert not splits.is_held_out("dev") and not splits.is_held_out("test") and not splits.is_held_out("nope")


def test_the_registry_agrees_with_the_page_and_the_generator() -> None:
    assert report.HELD_OUT_SPLITS == tuple(s.name for s in splits.REGISTRY if s.role == "held-out")
    for name, variants in SPLIT_VARIANTS.items():
        assert splits.get(name).variants == variants
    assert set(SPLIT_VARIANTS) == set(splits.recorded())


def test_a_final_split_follows_the_held_out_rules_before_its_letters_exist(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):  # its replay must not land beside its recording
        eval_run.run_cli(["--split", "holdout4", "--quiet"])
    with pytest.raises(SystemExit):  # it never rewrites docs/evals.md
        eval_run.run_cli(["--split", "newkinds", "--docs", "--results-dir", str(tmp_path)])
    assert eval_run.run_cli(["--split", "holdout4", "--results-dir", str(tmp_path), "--quiet"]) == 1
    assert "holdout4 has no letters yet" in capsys.readouterr().err
