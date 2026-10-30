"""Recording safely (``evals/harness.py`` through ``evals/run.py --live``), with an in-process fake model.

A usage limit in the middle of a recording keeps every answer already recorded, and the resume pays only for the
rest; ``--wait-on-limit`` sleeps through the window by itself; ``--max-cost-usd`` stops new calls at the cap; one
recorder runs at a time; a cassette is written whole or not at all, and a half one is named, then recorded again
by a live run; every live call leaves one line in ``ledger.jsonl``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import harness  # noqa: E402
from evals import run as eval_run  # noqa: E402

from ordnung.llm import replay as replay_module  # noqa: E402
from ordnung.llm.base import ClaudeRateLimited, LLMRequest, LLMResponse, StreamEvent, Usage  # noqa: E402
from ordnung.llm.fake import FakeBackend  # noqa: E402
from ordnung.llm.replay import RecordingBackend, ReplayBackend, fixture_path  # noqa: E402
from test_evals_run import IDS, Responder, make_config  # noqa: E402

LEDGER_FIELDS = {
    "at",
    "purpose",
    "key",
    "docs",
    "repeat",
    "outcome",
    "cost_usd",
    "duration_ms",
    "wall_ms",
    "served_model",
    "cli_version",
}


def _root(tmp_path: Path) -> Path:
    return tmp_path / "recorded" / eval_run.DEFAULT_MODEL


def _cassettes(tmp_path: Path) -> list[Path]:
    root = _root(tmp_path)
    return sorted(p for p in root.rglob("*.json") if p.parent != root)


def _files(folder: Path) -> list[Path]:
    return [path for path in folder.rglob("*") if path.is_file()]


def _ledger(tmp_path: Path) -> list[dict[str, Any]]:
    path = _root(tmp_path) / harness.LEDGER_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class Clock:
    """A clock the waiting reads and the fake sleep moves on."""

    def __init__(self, start: datetime) -> None:
        self.now = start
        self.slept: list[float] = []

    def read(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += timedelta(seconds=seconds)


class Limited:
    """Answers like the Responder; after ``after`` calls a usage limit, until ``clock`` passes ``until`` (never
    without a clock)."""

    name = "claude"

    def __init__(
        self,
        after: int | None,
        *,
        reset_at: str | None = "3pm (Europe/Berlin)",
        clock: Clock | None = None,
        until: datetime | None = None,
    ) -> None:
        self.inner = FakeBackend(Responder())
        self.after = after
        self.reset_at = reset_at
        self.clock = clock
        self.until = until
        self.calls = 0
        self.answered = 0

    def limited(self) -> bool:
        if self.after is None or self.calls <= self.after:
            return False
        return self.clock is None or self.until is None or self.clock.now < self.until

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.limited():
            raise ClaudeRateLimited("usage limit reached", reset_at=self.reset_at)
        self.answered += 1
        return await self.inner.complete(req)

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:  # pragma: no cover
        raise AssertionError("the benchmark does not stream")
        yield


async def _clean_run(tmp_path: Path) -> int:
    """How many calls a recording of the test letters makes when nothing goes wrong."""
    fake = FakeBackend(Responder())
    clean = make_config(tmp_path / "clean", live=True, write_docs=False, live_backend=fake)
    assert (await eval_run.run_benchmark(clean)).ok
    return len(fake.calls)


# --------------------------------------------------------------------------------------------------
# Interrupt and resume
# --------------------------------------------------------------------------------------------------


async def test_a_usage_limit_keeps_what_was_recorded_and_the_resume_pays_only_the_rest(
    tmp_path: Path,
) -> None:
    total = await _clean_run(tmp_path)
    model = Limited(after=5)
    config = make_config(tmp_path, live=True, write_docs=False, live_backend=model)
    first = await eval_run.run_benchmark(config)
    run = first.runs[0]
    assert run.fatal is not None and "usage limit" in run.fatal
    assert run.results_path is None and not list((tmp_path / "results").glob("*.json"))
    assert model.answered == 5 and len(_cassettes(tmp_path)) == 5
    assert [line["outcome"] for line in _ledger(tmp_path)].count("ok") == 5

    resumed = Limited(after=None)
    again = await eval_run.run_benchmark(
        make_config(tmp_path, live=True, write_docs=False, live_backend=resumed)
    )
    assert again.ok and again.runs[0].results_path is not None
    assert resumed.calls == total - 5  # nothing was paid twice
    assert len(_cassettes(tmp_path)) == total

    # the resumed recording replays to the same numbers
    replay = await eval_run.run_benchmark(
        make_config(tmp_path, write_docs=False, results_dir=tmp_path / "replayed")
    )
    assert replay.ok
    live_metrics = again.runs[0].results["metrics"]  # type: ignore[index]
    replay_metrics = replay.runs[0].results["metrics"]  # type: ignore[index]
    for condition, metrics in live_metrics.items():
        assert replay_metrics[condition]["due_date_accuracy"] == metrics["due_date_accuracy"]


async def test_wait_on_limit_sleeps_until_the_reset_and_carries_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock(datetime(2026, 10, 29, 10, 0, tzinfo=UTC))  # 11:00 in Berlin
    monkeypatch.setattr(harness, "_now", clock.read)
    monkeypatch.setattr(harness, "_sleep", clock.sleep)
    reset = datetime(2026, 10, 29, 14, 0, tzinfo=UTC)  # 3pm in Berlin
    model = Limited(after=4, clock=clock, until=reset)
    config = make_config(
        tmp_path, live=True, write_docs=False, live_backend=model, wait_on_limit_hours=12, concurrency=1
    )
    outcome = await eval_run.run_benchmark(config)
    assert outcome.ok and outcome.runs[0].results_path is not None
    assert clock.slept and clock.slept[0] == pytest.approx(
        (4 * 60 + 2) * 60
    )  # until the reset, plus 2 minutes
    assert clock.now >= reset
    outcomes = [line["outcome"] for line in _ledger(tmp_path)]
    assert "rate_limited" in outcomes and outcomes.count("ok") == model.answered


async def test_wait_on_limit_gives_up_when_the_reset_is_past_its_hours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock(datetime(2026, 10, 29, 10, 0, tzinfo=UTC))
    monkeypatch.setattr(harness, "_now", clock.read)
    monkeypatch.setattr(harness, "_sleep", clock.sleep)
    model = Limited(after=4, clock=clock, until=datetime(2026, 10, 29, 14, 0, tzinfo=UTC))
    config = make_config(tmp_path, live=True, write_docs=False, live_backend=model, wait_on_limit_hours=1)
    outcome = await eval_run.run_benchmark(config)
    assert outcome.runs[0].fatal is not None and "usage limit" in outcome.runs[0].fatal
    assert not clock.slept


async def test_a_limit_without_a_readable_reset_waits_half_an_hour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock(datetime(2026, 10, 29, 10, 0, tzinfo=UTC))
    monkeypatch.setattr(harness, "_now", clock.read)
    monkeypatch.setattr(harness, "_sleep", clock.sleep)
    model = Limited(after=2, reset_at=None, clock=clock, until=datetime(2026, 10, 29, 10, 20, tzinfo=UTC))
    config = make_config(
        tmp_path, live=True, write_docs=False, live_backend=model, wait_on_limit_hours=2, concurrency=1
    )
    assert (await eval_run.run_benchmark(config)).ok
    assert clock.slept[0] == pytest.approx(30 * 60)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3pm (Europe/Berlin)", datetime(2026, 10, 29, 14, 0, tzinfo=UTC)),
        ("3:30pm (Europe/Berlin)", datetime(2026, 10, 29, 14, 30, tzinfo=UTC)),
        ("9am (Europe/Berlin)", datetime(2026, 10, 30, 8, 0, tzinfo=UTC)),  # 9am today is past: tomorrow
        ("15:00 UTC", datetime(2026, 10, 29, 15, 0, tzinfo=UTC)),
        ("2 hours", datetime(2026, 10, 29, 12, 0, tzinfo=UTC)),
        ("1 hour 30 minutes", datetime(2026, 10, 29, 11, 30, tzinfo=UTC)),
        ("45 minutes", datetime(2026, 10, 29, 10, 45, tzinfo=UTC)),
        ("2026-10-29T18:00:00Z", datetime(2026, 10, 29, 18, 0, tzinfo=UTC)),
        ("1761768000", datetime(2025, 10, 29, 20, 0, tzinfo=UTC)),
        ("soon", None),
        (None, None),
    ],
)
def test_reset_times_the_cli_names(text: str | None, expected: datetime | None) -> None:
    now = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
    assert harness.parse_reset(text, now, local=UTC) == expected


# --------------------------------------------------------------------------------------------------
# The budget stop
# --------------------------------------------------------------------------------------------------


async def test_the_budget_stops_new_calls_and_a_higher_budget_resumes(tmp_path: Path) -> None:
    total = await _clean_run(tmp_path)
    model = Limited(after=None)
    config = make_config(
        tmp_path, live=True, write_docs=False, live_backend=model, max_cost_usd=0.004, concurrency=1
    )
    first = await eval_run.run_benchmark(config)
    run = first.runs[0]
    assert run.fatal is not None and "budget reached" in run.fatal and "--max-cost-usd" in run.fatal
    assert run.results_path is None
    spent = sum(line["cost_usd"] for line in _ledger(tmp_path))
    assert 0.004 <= spent < 0.004 + 0.003 + 1e-9  # at most one call past the cap (concurrency 1)
    assert model.calls == len(_cassettes(tmp_path)) == len(_ledger(tmp_path)) < total

    more = Limited(after=None)
    again = await eval_run.run_benchmark(
        make_config(tmp_path, live=True, write_docs=False, live_backend=more, max_cost_usd=1.0)
    )
    assert again.ok
    assert model.calls + more.calls == total == len(_cassettes(tmp_path))


async def test_the_same_cap_again_counts_what_the_ledger_says_was_spent(tmp_path: Path) -> None:
    """Resuming with the same command (the runbook's "run the same command again") must not get a whole new cap: the
    budget starts from what the ledger says this run already spent on these letters at this repeat."""
    model = Limited(after=None)
    cap = 0.004
    first = await eval_run.run_benchmark(
        make_config(
            tmp_path, live=True, write_docs=False, live_backend=model, max_cost_usd=cap, concurrency=1
        )
    )
    assert first.runs[0].fatal is not None and "budget reached" in first.runs[0].fatal
    spent = sum(line["cost_usd"] for line in _ledger(tmp_path))
    assert spent >= cap
    lines = len(_ledger(tmp_path))
    again = Limited(after=None)
    said: list[str] = []
    second = await eval_run.run_benchmark(
        make_config(
            tmp_path, live=True, write_docs=False, live_backend=again, max_cost_usd=cap, concurrency=1
        ),
        alert=said.append,
    )
    run = second.runs[0]
    assert run.fatal is not None and "budget reached" in run.fatal
    assert again.calls == 0 and len(_ledger(tmp_path)) == lines  # nothing new is recorded
    assert f"${spent:.4f}" in run.fatal
    assert any("already spent" in line and f"${spent:.4f}" in line for line in said)
    # another repeat of the same letters is another step: its own spend only
    repeat = Limited(after=None)
    third = await eval_run.run_benchmark(
        make_config(
            tmp_path,
            live=True,
            write_docs=False,
            live_backend=repeat,
            max_cost_usd=cap,
            concurrency=1,
            repeat=2,
        )
    )
    assert repeat.calls > 0 and third.runs[0].fatal is not None


async def test_runs_that_share_a_live_setup_share_one_budget(tmp_path: Path) -> None:
    """Two runs given one :class:`evals.harness.LiveSetup` (the stress cells) spend against one cap: once the first
    reached it, the second makes no call."""
    shared = harness.LiveSetup(budget=harness.Budget(0.004))
    first = Limited(after=None)
    one = await eval_run.run_benchmark(
        make_config(
            tmp_path,
            live=True,
            write_docs=False,
            live_backend=first,
            concurrency=1,
            ids=IDS[:1],
            live_setup=shared,
        )
    )
    assert first.calls > 0 and shared.budget is not None and shared.budget.reached
    assert one.runs[0].predictions  # the first letter's calls reached the cap
    second = Limited(after=None)
    two = await eval_run.run_benchmark(
        make_config(
            tmp_path,
            live=True,
            write_docs=False,
            live_backend=second,
            concurrency=1,
            ids=IDS[1:],
            live_setup=shared,
        )
    )
    assert second.calls == 0 and two.runs[0].fatal is not None and "budget reached" in two.runs[0].fatal


def test_the_budget_seed_counts_only_this_steps_lines(tmp_path: Path) -> None:
    ledger = tmp_path / harness.LEDGER_FILE
    rows = [
        {"docs": ["a"], "repeat": 1, "cost_usd": 0.5},
        {"docs": ["b", "a"], "repeat": 1, "cost_usd": 0.25},
        {"docs": ["a"], "repeat": 2, "cost_usd": 4.0},  # another repeat
        {"docs": ["c"], "repeat": 1, "cost_usd": 8.0},  # other letters
        {"docs": ["a"], "repeat": 1, "cost_usd": None},  # a failed call costs nothing
    ]
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows) + "\n", encoding="utf-8")
    assert harness.ledger_spent([ledger], docs={"a"}, repeat=1) == pytest.approx(0.75)
    assert harness.ledger_spent([ledger], docs={"a"}, repeat=2) == pytest.approx(4.0)
    assert harness.ledger_spent([tmp_path / "missing.jsonl"], docs={"a"}, repeat=1) == 0.0
    budget = harness.Budget(1.0, spent=0.75)
    assert not budget.reached and budget.spent == 0.75
    budget.add(0.25)
    assert budget.reached and "$1.0000 spent" in budget.message()


async def test_a_zero_budget_makes_no_call(tmp_path: Path) -> None:
    model = Limited(after=None)
    config = make_config(tmp_path, live=True, write_docs=False, live_backend=model, max_cost_usd=0)
    outcome = await eval_run.run_benchmark(config)
    assert outcome.runs[0].fatal is not None and "budget reached" in outcome.runs[0].fatal
    assert model.calls == 0 and not _cassettes(tmp_path) and not _ledger(tmp_path)


# --------------------------------------------------------------------------------------------------
# One recorder at a time
# --------------------------------------------------------------------------------------------------


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def test_one_recorder_at_a_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ORDNUNG_CLAUDE_BIN", str(tmp_path / "no-claude-here"))  # nothing may be called
    lock = tmp_path / "recording.lock"
    args = ["--live", "--split", "dev", "--ids", IDS[0], "--recorded-dir", str(tmp_path / "recorded")]
    args += ["--results-dir", str(tmp_path / "results"), "--no-docs", "--quiet", "--recorder-lock", str(lock)]
    args += ["--allow-another-today"]  # the dev letter's own today, so that the lock is what refuses
    with harness.RecorderLock(lock, command="the first recording"):
        assert eval_run.run_cli(args) == 1
        err = capsys.readouterr().err
        assert "another recording is running" in err and "the first recording" in err
        assert harness.main(["unlock", "--lock", str(lock)]) == 1  # its recorder is alive
        assert lock.exists()
    assert not lock.exists()

    # a recorder that died leaves its lock: refused until it is freed on purpose
    lock.write_text(json.dumps({"pid": _dead_pid(), "host": harness.HOST, "started": "x", "command": "old"}))
    assert eval_run.run_cli(args) == 1
    assert "python -m evals.harness unlock" in capsys.readouterr().err
    assert harness.main(["unlock", "--lock", str(lock)]) == 0
    assert not lock.exists()
    assert harness.main(["unlock", "--lock", str(lock)]) == 0  # nothing to free


async def test_a_live_run_takes_the_lock_and_frees_it(tmp_path: Path) -> None:
    seen: list[bool] = []
    lock = tmp_path / "recorded" / harness.RECORDER_LOCK_NAME

    class Watching(FakeBackend):
        async def complete(self, req: LLMRequest) -> LLMResponse:
            seen.append(lock.exists())
            return await super().complete(req)

    config = make_config(tmp_path, live=True, write_docs=False, live_backend=Watching(Responder()))
    assert config.recorder_lock is None  # beside the recordings unless the CLI names the shared one
    assert (await eval_run.run_benchmark(config)).ok
    assert seen and all(seen) and not lock.exists()


# --------------------------------------------------------------------------------------------------
# Whole cassettes
# --------------------------------------------------------------------------------------------------


async def test_a_crash_before_the_rename_leaves_no_half_cassette(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingBackend(FakeBackend({"test": {"ok": True}}), tmp_path, allowed_doc_ids={"d"})
    request = LLMRequest(purpose="test", prompt="p", system="s", doc_ids=["d"])

    def crash(*_args: Any) -> None:
        raise OSError("the disk is full")

    monkeypatch.setattr(replay_module.Path, "replace", crash)
    with pytest.raises(OSError):
        await recorder.complete(request)
    monkeypatch.undo()
    assert not _files(tmp_path)  # neither the cassette nor its temporary file
    await recorder.complete(request)
    assert json.loads(fixture_path(tmp_path, request).read_text(encoding="utf-8"))["response"]["data"] == {
        "ok": True
    }


async def test_a_half_cassette_is_named_on_replay_and_recorded_again_live(tmp_path: Path) -> None:
    fake = FakeBackend(Responder())
    ids = ["dev-tax_assessment-A1"]
    live = make_config(
        tmp_path, ids=ids, conditions=["llm_only"], live=True, write_docs=False, live_backend=fake
    )
    assert (await eval_run.run_benchmark(live)).ok
    (cassette,) = _cassettes(tmp_path)
    cassette.write_text(cassette.read_text(encoding="utf-8")[:120], encoding="utf-8")

    replay = await eval_run.run_benchmark(
        make_config(
            tmp_path, ids=ids, conditions=["llm_only"], write_docs=False, results_dir=tmp_path / "replayed"
        )
    )
    (error,) = replay.runs[0].errors
    assert "unreadable recording" in (error.error or "") and str(cassette) in (error.error or "")

    calls = len(fake.calls)
    fresh = make_config(
        tmp_path,
        ids=ids,
        conditions=["llm_only"],
        live=True,
        resume=False,
        write_docs=False,
        live_backend=fake,
    )
    again = await eval_run.run_benchmark(fresh)
    assert again.ok and len(fake.calls) == calls + 1
    assert json.loads(cassette.read_text(encoding="utf-8"))["response"]
    assert len(list(_root(tmp_path).rglob("*.bad"))) == 1  # moved aside, never committed (evals/.gitignore)


# --------------------------------------------------------------------------------------------------
# The ledger
# --------------------------------------------------------------------------------------------------


async def test_every_live_call_writes_one_ledger_line(tmp_path: Path) -> None:
    fake = FakeBackend(Responder())
    config = make_config(tmp_path, live=True, write_docs=False, live_backend=fake)
    assert (await eval_run.run_benchmark(config)).ok
    lines = _ledger(tmp_path)
    assert len(lines) == len(fake.calls) == len(_cassettes(tmp_path))
    assert all(set(line) == LEDGER_FIELDS for line in lines)
    assert all(line["outcome"] == "ok" and line["repeat"] == 1 for line in lines)
    lock = json.loads((_root(tmp_path) / harness.LOCK_FILE).read_text(encoding="utf-8"))
    assert {f"{line['purpose']}/{line['key']}" for line in lines} == set(lock)
    assert all(line["docs"] and line["docs"][0] in IDS for line in lines)
    assert sum(line["cost_usd"] for line in lines) == pytest.approx(
        sum(call.cost_usd for runs in config_calls(config) for call in runs)
    )
    # a resume replays what is recorded: no call, no line
    again = make_config(tmp_path, live=True, write_docs=False, live_backend=FakeBackend(Responder()))
    assert (await eval_run.run_benchmark(again)).ok
    assert len(_ledger(tmp_path)) == len(lines)


def config_calls(config: eval_run.RunConfig) -> list[list[Any]]:
    """The calls of every prediction in the run's results file (what the ledger must add up to)."""
    (path,) = sorted(config.results_dir.glob("*.json"))
    results = json.loads(path.read_text(encoding="utf-8"))

    class Call:
        def __init__(self, raw: dict[str, Any]) -> None:
            self.cost_usd = float(raw.get("cost_usd") or 0.0)

    return [
        [Call(raw) for raw in condition["prediction"].get("calls") or []]
        for entry in results["entries"]
        for condition in entry["conditions"].values()
    ]


# --------------------------------------------------------------------------------------------------
# A streamed call (Ask's): the same wrappers
# --------------------------------------------------------------------------------------------------


class Streaming:
    """A live CLI's stream: an error event for a usage limit (as ``ClaudeCLIBackend.stream`` yields it) for the
    first ``limited`` calls, else text and a done event."""

    name = "claude"

    def __init__(self, limited: int = 0, cost: float = 0.02) -> None:
        self.limited = limited
        self.cost = cost
        self.calls = 0

    async def complete(self, req: LLMRequest) -> LLMResponse:  # pragma: no cover
        raise AssertionError("Ask streams")

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        self.calls += 1
        if self.calls <= self.limited:
            yield StreamEvent(
                type="error",
                error="Your Claude usage limit or a rate limit was reached. Ordnung will continue when it resets.",
            )
            return
        yield StreamEvent(type="text", text="An answer.")
        usage = Usage(cost_usd=self.cost, duration_ms=7)
        yield StreamEvent(type="done", response=LLMResponse(text="An answer.", usage=usage, model="m"))


def _ask(question: str = "When is it due?") -> LLMRequest:
    return LLMRequest(purpose="ask", prompt=question, system="s", doc_ids=[], cache_key=f"ask:{question}")


async def _types(events: AsyncIterator[StreamEvent]) -> list[str]:
    return [event.type async for event in events]


async def test_a_streamed_call_waits_through_a_usage_limit_and_is_ledgered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock(datetime(2026, 10, 29, 10, 0, tzinfo=UTC))
    monkeypatch.setattr(harness, "_now", clock.read)
    monkeypatch.setattr(harness, "_sleep", clock.sleep)
    ledger = harness.Ledger(tmp_path / harness.LEDGER_FILE, repeat=2)
    live = harness.LiveCalls(Streaming(limited=1), ledger=ledger, waiter=harness.LimitWaiter(2))
    assert await _types(live.stream(_ask())) == ["text", "done"]  # the limit's error never reached the asker
    assert clock.slept == [pytest.approx(30 * 60)]  # a stream names no reset: half an hour
    lines = [json.loads(line) for line in ledger.path.read_text(encoding="utf-8").splitlines()]
    assert [line["outcome"] for line in lines] == ["rate_limited", "ok"]
    assert lines[1]["cost_usd"] == 0.02 and lines[1]["repeat"] == 2 and lines[1]["purpose"] == "ask"

    # without --wait-on-limit the limit is the answer, as before
    assert await _types(harness.LiveCalls(Streaming(limited=1)).stream(_ask())) == ["error"]


async def test_a_streamed_call_stops_at_the_budget() -> None:
    budget = harness.Budget(0.03)
    model = Streaming(cost=0.02)
    live = harness.LiveCalls(model, budget=budget)
    for _ in range(2):
        assert await _types(live.stream(_ask())) == ["text", "done"]
    refused = [event async for event in live.stream(_ask())]
    assert [event.type for event in refused] == ["error"] and "budget reached" in (refused[0].error or "")
    assert model.calls == 2 and budget.spent == pytest.approx(0.04)


async def test_a_streamed_recording_is_locked_and_checked(tmp_path: Path) -> None:
    root = tmp_path / "ask" / "model"
    recorder = RecordingBackend(Streaming(), root, allowed_doc_ids=set())
    live = harness.LockedRequests(
        ReplayBackend(root, fallback=recorder, set_aside=True),
        harness.RequestLock(root / harness.LOCK_FILE),
        root=root,
        record=True,
        repeat=2,
    )
    assert await _types(harness.RepeatKey(live, 2).stream(_ask())) == ["text", "done"]
    ((key, entry),) = harness.RequestLock(root / harness.LOCK_FILE).entries.items()
    assert key.startswith("ask/") and entry["repeat"] == 2 and entry["of"].startswith("ask/")

    # replayed with a request that changed under the same key: an error event, never the old answer
    lock = harness.RequestLock(root / harness.LOCK_FILE)
    replay = harness.RepeatKey(harness.LockedRequests(ReplayBackend(root), lock, root=root, repeat=2), 2)
    changed = _ask().model_copy(update={"system": "another system prompt"})
    events = [event async for event in replay.stream(changed)]
    assert [event.type for event in events] == ["error"] and "stale recording" in (events[0].error or "")
    assert (await _types(replay.stream(_ask())))[-1] == "done"
