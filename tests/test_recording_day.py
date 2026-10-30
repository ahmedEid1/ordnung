"""A recording's simulated today is the day it is recorded (the orchestrator's addendum to the evaluation plan, item 8).

The ``claude`` CLI tells the model the machine's date in its own context, beside the today Ordnung gives it, and its
date override does not work in ``-p`` mode. E2 recorded the Ask benchmark, pinned to Mon 28 Sep 2026, on Fri 30 Oct
2026: the model saw two todays and called open deadlines passed. So every recording after the code freeze takes the
day it is recorded as its today. The tooling that exists checks it and takes the day as a parameter:

* the reading benchmark's harness (:mod:`evals.harness`, :mod:`evals.run`) writes each run's simulated today into its
  results' ``meta``, refuses a recording whose simulated today is not the UTC date at its start (the day the CLI
  tells the model), and stops starting calls once that day is over (a turn recorded on a later day is invalid);
* the held-out Ask set (:mod:`evals.ask.run`) builds its ledger, its turns and its scoring for a given day;
* the stress builder (:mod:`evals.perturb.build`) builds its cells for a given day.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import harness  # noqa: E402
from evals import run as eval_run  # noqa: E402
from evals.ask import heldout  # noqa: E402
from evals.ask import ledger as ask_ledger  # noqa: E402
from evals.ask.run import BenchmarkError, Config, run  # noqa: E402
from evals.perturb import build as stress  # noqa: E402
from evals.records import load_manifest  # noqa: E402

from ordnung.llm.base import LLMError, LLMRequest, LLMResponse, StreamEvent, Usage  # noqa: E402
from ordnung.llm.fake import FakeBackend  # noqa: E402
from test_evals_ask import StandInAgent  # noqa: E402
from test_evals_ask_heldout import VALID_QUESTIONS, _attack, _write  # noqa: E402
from test_evals_run import Responder, make_config  # noqa: E402

DAY = date(2026, 11, 20)


def _at(monkeypatch: pytest.MonkeyPatch, day: date, hour: int = 9) -> None:
    monkeypatch.setattr(harness, "_now", lambda: datetime(day.year, day.month, day.day, hour, tzinfo=UTC))


# --------------------------------------------------------------------------------------------------
# the harness
# --------------------------------------------------------------------------------------------------


def test_the_recording_day_is_the_utc_date_the_run_starts_on(monkeypatch: pytest.MonkeyPatch) -> None:
    _at(monkeypatch, DAY, hour=23)
    assert harness.utc_today() == DAY


def test_a_recording_whose_simulated_today_is_another_day_is_refused() -> None:
    harness.check_recording_day(["2026-11-20"], DAY)
    harness.check_recording_day([DAY, DAY], DAY)
    with pytest.raises(harness.HarnessError) as refused:
        harness.check_recording_day(["2026-09-28", "2026-11-20"], DAY)
    message = str(refused.value)
    assert "2026-09-28" in message and "2026-11-20" in message and "two todays" in message
    # a smoke into a scratch folder, thrown away, may record on another day; it says so
    harness.check_recording_day(["2026-09-28"], DAY, allow=True)


class _Answers(FakeBackend):
    def __init__(self) -> None:
        super().__init__(lambda req: "{}")

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        self.calls.append(req)
        yield StreamEvent(type="done", response=LLMResponse(text="ok", usage=Usage(cost_usd=0.01)))


async def test_no_call_starts_once_the_recording_day_is_over(monkeypatch: pytest.MonkeyPatch) -> None:
    inner = _Answers()
    calls = harness.LiveCalls(inner, day=DAY)
    request = LLMRequest(purpose="ask", prompt="p", system="s")
    _at(monkeypatch, DAY, hour=23)
    await calls.complete(request)
    assert len(inner.calls) == 1
    _at(monkeypatch, date(2026, 11, 21), hour=0)
    with pytest.raises(harness.RecordingDayOver) as over:
        await calls.complete(request)
    assert isinstance(over.value, LLMError) and "2026-11-20" in str(over.value)
    events = [event async for event in calls.stream(request)]
    assert [event.type for event in events] == ["error"] and "2026-11-20" in (events[0].error or "")
    assert len(inner.calls) == 1  # neither reached the model
    assert harness.RecordingDayOver in eval_run.FATAL_ERRORS  # the run stops scheduling, keeps what is done


# --------------------------------------------------------------------------------------------------
# the reading benchmark
# --------------------------------------------------------------------------------------------------


async def test_a_recording_with_the_real_claude_is_refused_on_another_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dev letters' simulated today is not today: with the real ``claude`` (no stand-in) the run is refused
    before any call, the recorder lock untouched."""
    _at(monkeypatch, DAY)
    lock = tmp_path / "recording.lock"
    with pytest.raises(harness.HarnessError, match="two todays"):
        await eval_run.run_benchmark(make_config(tmp_path, live=True, write_docs=False, recorder_lock=lock))
    assert not lock.exists() and not (tmp_path / "recorded").exists()


async def test_a_run_records_its_simulated_today_and_its_recording_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = next(e for e in load_manifest(eval_run.MANIFEST_PATH) if e.id == "dev-tax_assessment-A1")
    day = date.fromisoformat(entry.today)
    _at(monkeypatch, day)
    config = make_config(
        tmp_path, ids=[entry.id], live=True, write_docs=False, live_backend=FakeBackend(Responder())
    )
    live = await eval_run.run_benchmark(_with(config, recording_day=day))
    meta = live.runs[0].results["meta"]  # type: ignore[index]
    assert meta["simulated_today"] == [entry.today] and meta["recording_day"] == entry.today
    # a stand-in given another recording day is refused as the real claude would be
    with pytest.raises(harness.HarnessError, match="two todays"):
        await eval_run.run_benchmark(_with(config, recording_day=DAY, recorded_dir=tmp_path / "other"))
    # a replay names the letters' today and no recording day
    replay = await eval_run.run_benchmark(
        _with(config, live=False, live_backend=None, results_dir=tmp_path / "replayed")
    )
    meta = replay.runs[0].results["meta"]  # type: ignore[index]
    assert meta["simulated_today"] == [entry.today] and meta["recording_day"] is None


def _with(config: eval_run.RunConfig, **changes: Any) -> eval_run.RunConfig:
    return dataclasses.replace(config, **changes)


def test_the_command_line_says_when_another_today_is_allowed() -> None:
    def config(*args: str) -> eval_run.RunConfig:
        return eval_run.config_from_args(eval_run.build_parser().parse_args(list(args)))

    assert config("--live", "--allow-another-today").allow_another_today is True
    assert config("--live").allow_another_today is False
    from evals.ask.__main__ import parse_args as ask_args

    assert ask_args(["--live", "--allow-another-today"]).allow_another_today is True
    assert ask_args(["--set", "heldout", "--today", "2026-11-20"]).today == DAY


# --------------------------------------------------------------------------------------------------
# another today: a disclosed re-recording of a development set, or a smoke into a scratch folder
# --------------------------------------------------------------------------------------------------

COMMITTED = ROOT / "evals" / "recorded"


def test_another_today_records_into_the_checkout_only_a_development_set() -> None:
    """A development set is pinned to its own today and can only be recorded again on another day (E3 may change
    what Ask's tools return before the freeze): --allow-another-today is that re-recording, disclosed. A held-out
    or final set takes it only for a smoke into a scratch folder outside the checkout."""
    harness.check_another_today(COMMITTED, development=True)
    harness.check_another_today(Path("/tmp/scratch-smoke"), development=False)
    for folder in (COMMITTED, COMMITTED / "ask", ROOT / "anything"):
        with pytest.raises(harness.HarnessError, match="scratch folder"):
            harness.check_another_today(folder, development=False)


def _run_config(*args: str) -> eval_run.RunConfig:
    return eval_run.config_from_args(eval_run.build_parser().parse_args(list(args)))


def test_a_held_out_split_is_never_recorded_into_the_checkout_on_another_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _at(monkeypatch, DAY)
    letters = [e for e in load_manifest(eval_run.MANIFEST_PATH) if e.split == "holdout3"][:1]
    config = _run_config("--live", "--split", "holdout3", "--allow-another-today")
    assert config.recorded_dir.resolve().is_relative_to(ROOT)
    with pytest.raises(harness.HarnessError, match="scratch folder"):
        eval_run.recording_day(config, letters)
    smoke = _run_config(
        "--live", "--split", "holdout3", "--allow-another-today", "--recorded-dir", "/tmp/smoke"
    )
    assert eval_run.recording_day(smoke, letters) == DAY  # a smoke still stops at midnight


def test_a_disclosed_re_recording_says_both_days(monkeypatch: pytest.MonkeyPatch) -> None:
    """The development letters re-recorded on another day: every new cassette says the day it was recorded on, and
    no "today" (the letters' today is in each request); a recording on its own day says both, the same."""
    _at(monkeypatch, DAY)
    letters = [e for e in load_manifest(eval_run.MANIFEST_PATH) if e.split == "dev"][:2]
    config = _run_config("--live", "--split", "dev", "--allow-another-today")
    live = eval_run.live_setup(config, lambda _message: None, letters)
    assert live.day == DAY  # a turn recorded after midnight is refused here too
    assert live.provenance["recorded_on"] == DAY.isoformat() and "today" not in live.provenance
    own = letters[0].model_copy(update={"today": DAY.isoformat()})
    live = eval_run.live_setup(_run_config("--live", "--split", "dev"), lambda _message: None, [own])
    assert (live.provenance["recorded_on"], live.provenance["today"]) == (DAY.isoformat(), DAY.isoformat())


def test_the_ask_development_set_is_re_recorded_in_the_open_and_the_held_out_set_never(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evals.ask import run as ask_run

    _at(monkeypatch, DAY)
    dev = Config(live=True, allow_another_today=True, recorded_dir=COMMITTED / "ask")
    assert ask_run.recording_day(dev) == DAY
    setup = ask_run.live_setup(dev)
    assert setup.provenance["recorded_on"] == DAY.isoformat() and "today" not in setup.provenance
    held = Config(set_name="heldout", live=True, allow_another_today=True, recorded_dir=COMMITTED / "ask")
    with pytest.raises(BenchmarkError, match="scratch folder"):
        ask_run.recording_day(held)
    own_day = Config(set_name="heldout", live=True, today=DAY, recorded_dir=COMMITTED / "ask")
    assert ask_run.live_setup(own_day).provenance["today"] == DAY.isoformat()


# --------------------------------------------------------------------------------------------------
# the held-out Ask set
# --------------------------------------------------------------------------------------------------


def test_the_development_set_is_asked_on_the_sample_life_s_own_day() -> None:
    with pytest.raises(BenchmarkError, match="2026-09-28"):
        run(Config(today=DAY))


def test_the_benchmark_today_follows_the_day_it_is_built_for() -> None:
    assert ask_ledger.benchmark_today() == ask_ledger.TODAY
    with ask_ledger.pinned_today(DAY):
        assert ask_ledger.benchmark_today() == DAY
    assert ask_ledger.benchmark_today() == ask_ledger.TODAY


def test_a_passed_today_attack_injects_the_day_it_is_asked_on(tmp_path: Path) -> None:
    passed = _attack("h-attack-today", kind="passed_today", injected_dates=[DAY.isoformat()])
    folder = _write(tmp_path / "heldout", [VALID_QUESTIONS[0]], [passed])
    with pytest.raises(heldout.HeldOutError, match="today"):
        heldout.load_attacks(folder / heldout.ATTACKS_NAME)
    with ask_ledger.pinned_today(DAY):
        assert [a.attack.id for a in heldout.load_attacks(folder / heldout.ATTACKS_NAME)] == [
            "h-attack-today"
        ]


@pytest.mark.slow  # replays or records a whole run: once, in backend-slow, without coverage
def test_a_held_out_run_is_built_asked_and_scored_on_its_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _write(tmp_path / "heldout", [VALID_QUESTIONS[0]], [])
    agent = StandInAgent()
    recorded = tmp_path / "recorded"
    config = Config(
        set_name="heldout",
        heldout_dir=folder,
        live=True,
        recorded_dir=recorded,
        live_backend=agent,
        today=DAY,
    )
    _at(monkeypatch, DAY)
    live = run(config, work_dir=tmp_path)
    [request] = agent.calls
    assert DAY.isoformat() in (request.system or "")  # Ask is told the day
    server = (request.mcp_config or {})["mcpServers"]["ordnung"]
    assert server["env"]["ORDNUNG_TODAY"] == DAY.isoformat()  # and so are its tools
    assert f'"today":"{DAY.isoformat()}"' in (request.cache_key or "")
    assert not live.misses
    from evals.ask.report import results_payload

    payload = results_payload(live, run_date=DAY.isoformat())
    assert payload["today"] == DAY.isoformat()
    replayed = run(
        Config(set_name="heldout", heldout_dir=folder, recorded_dir=recorded, today=DAY), work_dir=tmp_path
    )
    assert not replayed.misses and replayed.summary == live.summary
    # recorded on another day, the same set is refused before any turn
    with pytest.raises(BenchmarkError, match="two todays"):
        run(dataclasses.replace(config, recording_day=date(2026, 11, 21), recorded_dir=tmp_path / "x"))
    assert len(agent.calls) == 1


# --------------------------------------------------------------------------------------------------
# the stress builder
# --------------------------------------------------------------------------------------------------


def test_the_stress_cells_are_built_for_a_day(tmp_path: Path) -> None:
    """A stress letter is read on the day it is built for: its simulated today is that day, it was written by then
    and its deadline is still open. The held-out letters the cells perturb were written for their own days (2024 to
    2027), so on a recording day at the end of 2026 too few of them qualify and the builder says so."""
    entries = load_manifest(stress.DATASET_MANIFEST)
    by_id = {e.id: e for e in entries}
    letter = next(e for e in entries if e.split in stress.BASE_SPLITS and stress.eligible(e))
    own = date.fromisoformat(letter.today)
    target = min(item.expected_date for item in letter.truth.items if item.expected_date is not None)
    assert stress.eligible(letter, today=own)
    assert not stress.eligible(letter, today=date.fromordinal(own.toordinal() - 1))  # not written yet
    assert not stress.eligible(
        letter, today=date.fromordinal(target.toordinal() + 1)
    )  # its deadline has passed
    raw = json.loads(stress.DATASET_MANIFEST.read_text(encoding="utf-8"))
    base_raw = next(e for e in raw["entries"] if e["id"] == letter.id)
    row = {"id": f"stress-I1-{letter.id}", "cell": "D1", "file": "D1/x.pdf", "sha256": "0", "bytes": 1, "pages": 1,
           "base_id": letter.id, "kind": "service_hours", "claim": None, "target_index": 0}  # fmt: skip
    assert stress.runnable_entry(base_raw, row)["today"] == letter.today
    assert stress.runnable_entry(base_raw, row, today=target)["today"] == target.isoformat()
    with pytest.raises(stress.BuildError, match="2026-11-20"):
        stress.base_set(entries, today=DAY)
    assert by_id  # the default build (no day) is the one the tests of evals/perturb pin


def test_a_stress_run_says_the_day_its_cells_were_built_for(tmp_path: Path) -> None:
    """The results file names the day (``meta.today``), so its replay (``make eval-reproduce``) builds the same
    letters again; a build without a day (before item 8) writes none."""
    from scripts import eval_perturb

    def meta(stress_doc: dict[str, Any] | None) -> dict[str, Any]:
        return eval_perturb.run_meta(
            run_date=DAY.isoformat(),
            model="claude-sonnet-5",
            cells=["I1"],
            live=False,
            recorded_dir=tmp_path,
            stress_doc=stress_doc,
            runs={},
        )

    assert meta({"today": DAY.isoformat(), "templates_sha256": "0"})["today"] == DAY.isoformat()
    assert "today" not in meta({"templates_sha256": "0"}) and "today" not in meta(None)
