"""The final run's recording mechanics (``evals/run.py``, ``evals/harness.py``): its recording-day rule.

A final split's letters were written for a planned day and are valid through the last day of their window
(``final_day`` and ``valid_until`` in the manifest). Each unit — one letter in one read with all its conditions — is
told the UTC day it is recorded on as its today and keeps that day: a read may span several days of the window, and
the day index beside the recordings (``final-days.json``) says each unit's day and ``claude`` version, so a replay, the
gates and ``make eval-reproduce`` give each letter its own day again. A stop file or ``--stop-at`` stops a run at a
unit boundary (exit 4); an incomplete unit of another day is refused until ``python -m evals.harness retake`` moved
its cassettes aside. Nothing here calls a model: the live runs go through ``tests/fake_claude.py`` or a stand-in.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import harness, reproduce  # noqa: E402
from evals import run as eval_run  # noqa: E402
from evals.records import Prediction, load_manifest  # noqa: E402

from ordnung.llm.base import LLMRequest  # noqa: E402
from ordnung.llm.fake import FakeBackend  # noqa: E402
from test_evals_run import Responder  # noqa: E402

DATASET = ROOT / "evals" / "dataset"
MANIFEST = DATASET / "manifest.json"
FAKE = ROOT / "tests" / "fake_claude.py"
MODEL = eval_run.DEFAULT_MODEL
SPLIT = "holdout4"
D0 = date(2026, 12, 8)  # the planned day (a Tuesday)
L = D0 + timedelta(days=7)  # the last valid day
D1, D2 = D0, D0 + timedelta(days=1)
#: Three one-page text letters of the development split, copied as a synthetic final split: the same bytes and truth,
#: new ids, the final split's window.
SOURCES = ("dev-dunning_fixed-A1", "dev-invoice_relative-A1", "dev-tax_assessment-B1")
TRANSCRIPT = {"transcript": "extract_structured.jsonl"}
FAKE_VERSION = "2.1.5 (Claude Code)"


def _at(monkeypatch: pytest.MonkeyPatch, day: date, hour: int = 9, minute: int = 0) -> None:
    moment = datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)
    monkeypatch.setattr(harness, "_now", lambda: moment)


def final_split(tmp_path: Path, *, window: bool = True) -> Path:
    """A synthetic final split of three letters in ``tmp_path/dataset``; its manifest's path."""
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_id = {entry["id"]: entry for entry in raw["entries"]}
    dataset = tmp_path / "dataset"
    entries = []
    for number, source in enumerate(SOURCES, 1):
        entry = dict(by_id[source])
        entry.update(
            id=f"{SPLIT}-{entry['family']}-K{number}", split=SPLIT, variant="K", today=D0.isoformat()
        )
        if window:
            entry.update(final_day=D0.isoformat(), valid_until=L.isoformat())
        target = dataset / entry["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DATASET / entry["file"], target)
        entries.append(entry)
    path = dataset / "manifest.json"
    head = {key: value for key, value in raw.items() if key != "entries"}
    path.write_text(json.dumps({**head, "entries": entries}), encoding="utf-8")
    return path


def letters(manifest: Path) -> list[str]:
    return [entry.id for entry in load_manifest(manifest)]


class FinalResponder(Responder):
    """The benchmark tests' plausible model, for the synthetic final split's letters."""

    def __init__(self, manifest: Path) -> None:
        super().__init__()
        self.raw = {
            entry["id"]: entry for entry in json.loads(manifest.read_text(encoding="utf-8"))["entries"]
        }
        self.entries = {entry.id: entry for entry in load_manifest(manifest)}


def fake_claude(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    calls: list[dict[str, Any]] | None = None,
    name: str = "fake",
) -> Path:
    """``tests/fake_claude.py`` as the live ``claude`` (each call logged); the log's path."""
    log = tmp_path / f"{name}-calls.jsonl"
    scenario = tmp_path / f"{name}.json"
    scenario.write_text(json.dumps({"log": str(log), "calls": calls or [TRANSCRIPT]}), encoding="utf-8")
    monkeypatch.setenv("ORDNUNG_CLAUDE_BIN", str(FAKE))
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", str(scenario))
    return log


def stand_in(monkeypatch: pytest.MonkeyPatch, backend: Any) -> None:
    """``backend`` as the live ``claude`` of :mod:`evals.run` (the rest of the live stack is the real one)."""
    monkeypatch.setattr(eval_run, "ClaudeCLIBackend", lambda concurrency: backend)


def calls(log: Path) -> int:
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0


def run(tmp_path: Path, manifest: Path, *args: str) -> int:
    return eval_run.run_cli(
        [
            "--split", SPLIT, "--manifest", str(manifest), "--recorded-dir", str(tmp_path / "recorded"),
            "--results-dir", str(tmp_path / "results"), "--recorder-lock", str(tmp_path / "recording.lock"),
            "--date", D1.isoformat(), "--no-docs", "--quiet", "--resamples", "50", *args,
        ]
    )  # fmt: skip


def root(tmp_path: Path) -> Path:
    return tmp_path / "recorded" / MODEL


def day_index(tmp_path: Path) -> dict[str, Any]:
    path = root(tmp_path) / harness.DAY_INDEX_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def units(tmp_path: Path, repeat: int = 1) -> dict[str, Any]:
    return dict(day_index(tmp_path).get(SPLIT, {}).get(f"r{repeat}", {}))


def cassettes(folder: Path) -> list[Path]:
    return sorted(path for path in folder.rglob("*.json") if path.parent != folder)


def record_two_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest: Path) -> Path:
    """The read recorded on two days by a stand-in: the first two letters on D1, the third on D2. The results file."""
    first, second, _ = letters(manifest)
    stand_in(monkeypatch, FakeBackend(FinalResponder(manifest)))
    _at(monkeypatch, D1)
    assert run(tmp_path, manifest, "--live", "--today", D1.isoformat(), "--ids", first, second) == 0
    _at(monkeypatch, D2)
    assert run(tmp_path, manifest, "--live", "--today", D2.isoformat()) == 0
    return tmp_path / "results" / f"{D1.isoformat()}-{MODEL}-{SPLIT}.json"


def predictions(results: dict[str, Any]) -> dict[str, Any]:
    """Every prediction of a results file, without what a replay measures itself (wall time, the backend's name)."""
    out: dict[str, Any] = {}
    for entry in results["entries"]:
        for condition, outcome in entry["conditions"].items():
            prediction = json.loads(json.dumps(outcome["prediction"]))
            for call in prediction.get("calls", []):
                call.pop("wall_ms", None)
                call.pop("backend", None)
            out[f"{entry['id']}/{condition}"] = prediction
    return out


# --------------------------------------------------------------------------------------------------
# (a) live today: the UTC day, inside the window, final splits only
# --------------------------------------------------------------------------------------------------


def test_a_final_split_is_recorded_live_only_on_the_utc_day_inside_its_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = final_split(tmp_path)
    log = fake_claude(monkeypatch, tmp_path)
    # --today another day than the UTC day: two todays
    _at(monkeypatch, D2)
    assert run(tmp_path, manifest, "--live", "--today", D1.isoformat()) == 1
    assert "two todays" in capsys.readouterr().err
    # the UTC day and --today agree, but outside the window the manifest names
    for day in (L + timedelta(days=1), D0 - timedelta(days=1)):
        _at(monkeypatch, day)
        assert run(tmp_path, manifest, "--live", "--today", day.isoformat()) == 1
        err = capsys.readouterr().err
        assert "window" in err and D0.isoformat() in err and L.isoformat() in err
    # without --today the letters' planned day is the day: on another day the refusal names --today
    _at(monkeypatch, D2)
    assert run(tmp_path, manifest, "--live") == 1
    assert "--today" in capsys.readouterr().err
    # letters whose manifest names no window are never recorded live
    bare = final_split(tmp_path / "bare", window=False)
    assert run(tmp_path, bare, "--live", "--today", D2.isoformat()) == 1
    assert "window" in capsys.readouterr().err
    assert calls(log) == 0
    assert not (tmp_path / "recorded").exists() and not (tmp_path / "recording.lock").exists()


def test_today_is_the_final_splits_and_a_live_runs_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Other splits keep ``--allow-another-today``; a replay takes each letter's day from the day index."""
    manifest = final_split(tmp_path)
    fake_claude(monkeypatch, tmp_path)
    _at(monkeypatch, D2)
    with pytest.raises(SystemExit):
        eval_run.run_cli(
            ["--live", "--split", "dev", "--today", D2.isoformat(), "--recorded-dir", str(tmp_path)]
        )
    assert "--allow-another-today" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        run(tmp_path, manifest, "--today", D2.isoformat())
    assert "day index" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        run(tmp_path, manifest, "--live", "--today", D2.isoformat(), "--check", str(tmp_path / "x.json"))
    # a unit is a letter with all its conditions, and a final split's recordings are never refreshed
    assert run(tmp_path, manifest, "--live", "--today", D2.isoformat(), "--conditions", "ordnung") == 1
    assert "every condition" in capsys.readouterr().err
    assert run(tmp_path, manifest, "--live", "--refresh", "--today", D2.isoformat()) == 1
    assert "retake" in capsys.readouterr().err
    assert not (tmp_path / "recorded").exists()


# --------------------------------------------------------------------------------------------------
# (b) a read recorded on two days is one results file
# --------------------------------------------------------------------------------------------------


def test_a_read_recorded_on_two_days_through_the_fake_claude_is_one_results_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = final_split(tmp_path)
    first, second, third = letters(manifest)
    fake_claude(monkeypatch, tmp_path)
    _at(monkeypatch, D1)
    assert run(tmp_path, manifest, "--live", "--today", D1.isoformat(), "--ids", first, second) == 0
    assert {unit: (record["day"], record["cli"]) for unit, record in units(tmp_path).items()} == {
        first: (D1.isoformat(), FAKE_VERSION),
        second: (D1.isoformat(), FAKE_VERSION),
    }
    _at(monkeypatch, D2)
    assert run(tmp_path, manifest, "--live", "--today", D2.isoformat()) == 0
    assert {unit: record["day"] for unit, record in units(tmp_path).items()} == {
        first: D1.isoformat(),
        second: D1.isoformat(),
        third: D2.isoformat(),
    }
    # on D2 only the third letter's unit made calls: the first two replayed on their own day
    ledger = [json.loads(line) for line in (root(tmp_path) / harness.LEDGER_FILE).read_text().splitlines()]
    on_d2 = [row for row in ledger if row["at"].startswith(D2.isoformat())]
    assert on_d2 and all(row["docs"] == [third] for row in on_d2)
    assert all(row["docs"] in ([first], [second]) for row in ledger if row not in on_d2)
    results = sorted(path.name for path in (tmp_path / "results").glob("*.json"))
    assert results == [
        f"{D1.isoformat()}-{MODEL}-{SPLIT}-partial.json",
        f"{D1.isoformat()}-{MODEL}-{SPLIT}.json",
    ]
    data = json.loads((tmp_path / "results" / results[1]).read_text(encoding="utf-8"))
    meta = data["meta"]
    assert meta["recording_days"] == [D1.isoformat(), D2.isoformat()]
    assert meta["simulated_today"] == [D1.isoformat(), D2.isoformat()]
    assert meta["cli_versions"] == [FAKE_VERSION] and meta["recording_day"] == D2.isoformat()
    assert meta["partial"] is False and meta["entries"] == 3
    for entry in data["entries"]:
        day = D2.isoformat() if entry["id"] == third else D1.isoformat()
        assert entry["today"] == day
        for outcome in entry["conditions"].values():
            assert outcome["prediction"]["recorded_on"] == day
            assert outcome["prediction"]["cli_version"] == FAKE_VERSION
    reproduce._row(tmp_path / "results" / results[1], data, "run", "final")  # one today per letter: indexed


def test_the_day_index_beside_the_recordings_is_no_recording() -> None:
    """The committed recordings' checks read every ``*.json`` under ``evals/recorded`` but the files beside them."""
    from test_recordings import LOCKS

    assert harness.DAY_INDEX_FILE in LOCKS


def test_a_prediction_without_a_unit_keeps_the_shape_every_results_file_has() -> None:
    plain = Prediction(entry_id="x", condition="ordnung", model=MODEL)
    assert "recorded_on" not in plain.model_dump(mode="json") and "cli_version" not in plain.model_dump_json()
    unit = plain.model_copy(update={"recorded_on": D1.isoformat(), "cli_version": FAKE_VERSION})
    assert unit.model_dump(mode="json")["recorded_on"] == D1.isoformat()
    assert Prediction.model_validate_json(unit.model_dump_json()) == unit


# --------------------------------------------------------------------------------------------------
# (c) an incomplete unit of another day: refused, then retaken
# --------------------------------------------------------------------------------------------------


def test_an_incomplete_unit_of_another_day_is_refused_until_it_is_retaken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = final_split(tmp_path)
    first = letters(manifest)[0]
    # D1: the first call is answered, every later one fails: the unit is left incomplete
    broken = [TRANSCRIPT, {"exit": 1, "stderr": "the connection dropped"}]
    fake_claude(monkeypatch, tmp_path, broken, name="broken")
    _at(monkeypatch, D1)
    assert (
        run(tmp_path, manifest, "--live", "--today", D1.isoformat(), "--ids", first, "--concurrency", "1")
        == 1
    )
    assert first not in units(tmp_path)
    kept = cassettes(root(tmp_path))
    assert kept
    shas = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in kept}
    capsys.readouterr()
    # D2: refused before any call, naming the letter and its cassettes
    log = fake_claude(monkeypatch, tmp_path, name="healthy")
    _at(monkeypatch, D2)
    assert run(tmp_path, manifest, "--live", "--today", D2.isoformat(), "--ids", first) == 1
    err = capsys.readouterr().err
    assert first in err and "retake" in err and all(path.name in err for path in kept)
    assert calls(log) == 0
    # the retake moves the unit's cassettes aside and frees their lock entries, listing each one
    aside = tmp_path / "retakes" / D2.isoformat()
    code = harness.main(
        [
            "retake", "--split", SPLIT, "--repeat", "1", "--ids", first, "--to", str(aside),
            "--recorded-dir", str(tmp_path / "recorded"),
        ]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0
    assert all(sha in out for sha in shas.values()) and "$" in out
    assert any(word in out for word in (" ok ", " failed "))
    assert not any(path.exists() for path in kept)
    assert sorted(path.name for path in cassettes(aside)) == sorted(shas)
    lock = json.loads((root(tmp_path) / harness.LOCK_FILE).read_text(encoding="utf-8"))
    assert not any(first in entry["docs"] for entry in lock.values())
    # recorded whole on D2
    assert run(tmp_path, manifest, "--live", "--today", D2.isoformat(), "--ids", first) == 0
    assert units(tmp_path)[first]["day"] == D2.isoformat()
    assert calls(log) > 0


def test_a_complete_unit_never_reaches_the_model_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A complete unit replays from its recordings; were one of them gone, its call would record a valid answer
    again (on another day): it is refused, and the run fails instead."""
    manifest = final_split(tmp_path)
    record_two_days(tmp_path, monkeypatch, manifest)
    first = letters(manifest)[0]
    lock = json.loads((root(tmp_path) / harness.LOCK_FILE).read_text(encoding="utf-8"))
    key = next(key for key, entry in lock.items() if entry["docs"] == [first])
    (root(tmp_path) / f"{key}.json").unlink(missing_ok=True)
    (root(tmp_path) / f"{key}.failure.json").unlink(missing_ok=True)
    backend = FakeBackend(FinalResponder(manifest))
    stand_in(monkeypatch, backend)
    _at(monkeypatch, D2)
    assert (
        run(tmp_path, manifest, "--live", "--today", D2.isoformat(), "--results-dir", str(tmp_path / "again"))
        == 1
    )
    assert backend.calls == [] and "its unit is complete" in capsys.readouterr().err
    assert units(tmp_path)[first]["day"] == D1.isoformat()


async def test_the_live_calls_refuse_a_closed_unit_s_letter() -> None:
    inner = FakeBackend(lambda req: "{}")
    calls = harness.LiveCalls(inner, closed={"holdout4-x-K1"})
    request = LLMRequest(purpose="extract", prompt="p", system="s", doc_ids=["holdout4-x-K1"])
    with pytest.raises(harness.UnitClosed):
        await calls.complete(request)
    events = [event async for event in calls.stream(request)]
    assert [event.type for event in events] == ["error"] and "complete" in (events[0].error or "")
    assert inner.calls == []
    await calls.complete(request.model_copy(update={"doc_ids": ["holdout4-y-K2"]}))
    assert len(inner.calls) == 1


def test_retake_refuses_a_complete_unit_and_an_unknown_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = final_split(tmp_path)
    record_two_days(tmp_path, monkeypatch, manifest)
    first = letters(manifest)[0]
    before = cassettes(root(tmp_path))
    common = ["--split", SPLIT, "--repeat", "1", "--to", str(tmp_path / "aside")]
    common += ["--recorded-dir", str(tmp_path / "recorded")]
    assert harness.main(["retake", *common, "--ids", first]) == 2
    assert "complete" in capsys.readouterr().err
    assert harness.main(["retake", *common, "--ids", "holdout4-nothing-K9"]) == 1
    assert "no cassette" in capsys.readouterr().err
    assert harness.main(["retake", "--repeat", "1", "--to", str(tmp_path / "aside"), "--ids", first]) == 2
    assert cassettes(root(tmp_path)) == before and not (tmp_path / "aside").exists()


def test_retake_moves_a_whole_run_of_one_repeat(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An Ask run or a stress invocation is one unit: all its cassettes at that repeat move, the other runs stay."""
    folder = tmp_path / "ask-heldout" / MODEL
    lock = harness.RequestLock(folder / harness.LOCK_FILE)
    ledger = []
    for repeat, key in ((1, "a" * 24), (2, "b" * 24), (2, "c" * 24)):
        path = folder / "ask" / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"request": {}, "response": {"usage": {"cost_usd": 0.03}}}), encoding="utf-8"
        )
        entry: dict[str, Any] = {"docs": [], "content": key[:32], "fields": ""}
        if repeat > 1:
            entry.update(repeat=repeat, of=f"ask/{'a' * 24}")
        lock.entries[f"ask/{key}"] = entry
        ledger.append(
            {"purpose": "ask", "key": key, "docs": [], "repeat": repeat, "outcome": "ok", "cost_usd": 0.03}
        )
    ledger.append(
        {"purpose": "ask", "key": "d" * 24, "docs": [], "repeat": 2, "outcome": "timeout", "cost_usd": 0}
    )
    lock.save()
    (folder / harness.LEDGER_FILE).write_text(
        "".join(json.dumps(row) + "\n" for row in ledger), encoding="utf-8"
    )
    aside = tmp_path / "aside"
    code = harness.main(
        [
            "retake",
            "--recorded-dir",
            str(tmp_path / "ask-heldout"),
            "--repeat",
            "2",
            "--whole-run",
            "--to",
            str(aside),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0 and "timeout" in out and out.count(" ok ") == 2
    assert [path.name for path in cassettes(folder)] == [f"{'a' * 24}.json"]
    assert sorted(path.name for path in cassettes(aside)) == [f"{'b' * 24}.json", f"{'c' * 24}.json"]
    assert sorted(harness.RequestLock(folder / harness.LOCK_FILE).entries) == [f"ask/{'a' * 24}"]


# --------------------------------------------------------------------------------------------------
# (d) the stop file and --stop-at stop at a unit boundary
# --------------------------------------------------------------------------------------------------


def test_a_stop_file_stops_the_read_at_a_unit_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = final_split(tmp_path)
    ids = letters(manifest)
    stop = tmp_path / "stop"
    responder = FinalResponder(manifest)
    touched: list[str] = []

    def answer(req: LLMRequest) -> Any:
        if not touched:  # the watcher writes the stop file while the first unit is under way
            stop.touch()
            touched.append(req.doc_ids[0])
        return responder(req)

    backend = FakeBackend(answer)
    stand_in(monkeypatch, backend)
    _at(monkeypatch, D1)
    assert (
        run(tmp_path, manifest, "--live", "--today", D1.isoformat(), "--stop-file", str(stop))
        == harness.STOPPED
    )
    assert harness.STOPPED == 4
    assert "stopped at a unit boundary" in capsys.readouterr().err
    assert list(units(tmp_path)) == [ids[0]]  # the unit under way finished, with all its conditions
    assert {doc for req in backend.calls for doc in req.doc_ids} == {ids[0]}
    lock = json.loads((root(tmp_path) / harness.LOCK_FILE).read_text(encoding="utf-8"))
    assert {doc for entry in lock.values() for doc in entry["docs"]} == {ids[0]}  # no half unit
    assert not list((tmp_path / "results").glob("*.json"))
    # the same command again, once the stop file is gone: the rest of the read
    stop.unlink()
    assert run(tmp_path, manifest, "--live", "--today", D1.isoformat(), "--stop-file", str(stop)) == 0
    assert sorted(units(tmp_path)) == ids


def test_stop_at_starts_no_unit_once_the_clock_has_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = final_split(tmp_path)
    ids = letters(manifest)
    clock = {"now": datetime(D1.year, D1.month, D1.day, 22, 58, tzinfo=UTC)}
    monkeypatch.setattr(harness, "_now", lambda: clock["now"])
    responder = FinalResponder(manifest)

    def answer(req: LLMRequest) -> Any:
        # the clock passes 23:00 while the first unit is under way
        clock["now"] = datetime(D1.year, D1.month, D1.day, 23, 1, tzinfo=UTC)
        return responder(req)

    backend = FakeBackend(answer)
    stand_in(monkeypatch, backend)
    assert run(tmp_path, manifest, "--live", "--today", D1.isoformat(), "--stop-at", "23:00") == 4
    assert "23:00" in capsys.readouterr().err
    assert list(units(tmp_path)) == [ids[0]]
    made = len(backend.calls)
    # started after the time: no unit starts, no call is made
    clock["now"] = datetime(D1.year, D1.month, D1.day, 23, 30, tzinfo=UTC)
    assert run(tmp_path, manifest, "--live", "--today", D1.isoformat(), "--stop-at", "23:00") == 4
    assert len(backend.calls) == made and list(units(tmp_path)) == [ids[0]]


def test_the_stop_says_why(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _at(monkeypatch, D1, 22, 59)
    assert harness.Stop.of() is None
    stop = harness.Stop.of(file=tmp_path / "stop", at="23:00")
    assert stop is not None and stop.requested() is None
    (tmp_path / "stop").touch()
    assert "stop file" in (stop.requested() or "")
    (tmp_path / "stop").unlink()
    _at(monkeypatch, D1, 23, 0)
    assert "23:00" in (stop.requested() or "")
    for wrong in ("24:00", "23:60", "11pm", "2300"):
        with pytest.raises(ValueError):
            harness.Stop.of(at=wrong)


def test_an_ask_run_starts_no_new_turn_once_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from evals.ask import run as ask_run
    from evals.ask.__main__ import main as ask_main
    from evals.ask.ledger import TODAY

    from test_evals_ask import StandInAgent

    only = ["deadline-steuerbescheid_2025-0", "none-car-insurance", "cross-pay-this-week"]
    stop = tmp_path / "stop"
    stop.touch()
    agent = StandInAgent()
    config = ask_run.Config(
        live=True, only=only, recorded_dir=tmp_path / "ask", live_backend=agent, stop=harness.Stop(file=stop)
    )
    result = ask_run.run(config, work_dir=tmp_path)
    assert result.stopped and "stop file" in result.stopped and not agent.calls
    assert all("stopped" in (turn.error or "") for turn in result.turns.values())

    class StopsMeanwhile(StandInAgent):
        async def stream(self, req: LLMRequest) -> Any:
            stop.touch()  # while the first turn is under way
            async for event in super().stream(req):
                yield event

    stop.unlink()
    meanwhile = StopsMeanwhile()
    monkeypatch.setattr(ask_run, "ClaudeCLIBackend", lambda **_options: meanwhile)
    _at(monkeypatch, TODAY)  # the development set's own day
    code = ask_main(
        [
            "--live", "--only", ",".join(only), "--concurrency", "1", "--recorded-dir", str(tmp_path / "ask2"),
            "--recorder-lock", str(tmp_path / "recording.lock"), "--stop-file", str(stop), "--write",
            "--results-dir", str(tmp_path / "results"),
        ]
    )  # fmt: skip
    assert code == harness.STOPPED
    assert len(meanwhile.calls) == 1 and not (tmp_path / "results").exists()
    assert "stopped" in capsys.readouterr().err


def test_a_stress_invocation_stops_at_the_next_letter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import eval_perturb

    stop = tmp_path / "stop"
    stop.touch()
    backend = FakeBackend(Responder())
    config = eval_run.RunConfig(
        split="dev",
        ids=["dev-dunning_fixed-A1", "dev-invoice_relative-A1"],
        conditions=list(eval_perturb.CONDITIONS),
        live=True,
        live_backend=backend,
        recorded_dir=tmp_path / "stress",
        results_dir=tmp_path / "work",
        recorder_lock=tmp_path / "recording.lock",
        write_results=False,
        write_docs=False,
        stop=harness.Stop(file=stop),
    )
    with pytest.raises(eval_perturb.StressStopped):
        asyncio.run(eval_perturb._predictions(config, quiet=True))
    assert backend.calls == []
    # every cell's run takes the stop, and the command says it stopped with exit 4
    args = eval_perturb.build_parser().parse_args(["--stop-file", str(stop), "--stop-at", "23:00"])
    options = eval_perturb.harness_options(
        live=True, max_cost_usd=1.0, wait_on_limit=None, stop=harness.Stop.from_args(args)
    )
    assert isinstance(options["stop"], harness.Stop) and options["stop"].file == stop

    async def stopped(_args: Any) -> int:
        raise eval_perturb.StressStopped("stopped at a unit boundary: the stop file exists")

    monkeypatch.setattr(eval_perturb, "_run", stopped)
    assert eval_perturb.main([]) == harness.STOPPED


# --------------------------------------------------------------------------------------------------
# (e) the replay reads the day index; --check
# --------------------------------------------------------------------------------------------------


class _NoModel:
    """A replay asks no model."""

    name = "no-model"

    def __init__(self, concurrency: int = 1) -> None:
        pass

    async def complete(self, req: LLMRequest) -> Any:
        raise AssertionError(f"a replay called the model: {req.purpose}")

    async def stream(self, req: LLMRequest) -> Any:  # pragma: no cover
        raise AssertionError("a replay called the model")
        yield


def test_a_replay_gives_each_letter_its_unit_s_day_from_the_day_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = final_split(tmp_path)
    live = record_two_days(tmp_path, monkeypatch, manifest)
    monkeypatch.setattr(eval_run, "ClaudeCLIBackend", _NoModel)
    _at(monkeypatch, D2 + timedelta(days=30))  # any later day
    replayed = tmp_path / "replayed"
    assert run(tmp_path, manifest, "--results-dir", str(replayed)) == 0
    recorded = json.loads(live.read_text(encoding="utf-8"))
    again = json.loads((replayed / live.name).read_text(encoding="utf-8"))
    assert predictions(again) == predictions(recorded)  # every request replayed under the request lock
    assert [e["today"] for e in again["entries"]] == [e["today"] for e in recorded["entries"]]
    assert again["metrics"] == recorded["metrics"]
    assert again["meta"]["recording_days"] == recorded["meta"]["recording_days"]
    assert again["meta"]["recording_day"] is None
    # --check: the replay against the live file; the outcome on stdout only (its callers seal it)
    capsys.readouterr()
    assert run(tmp_path, manifest, "--check", str(live)) == 0
    out, err = capsys.readouterr()
    assert "equal" in out and err == ""
    text = live.read_text(encoding="utf-8")
    # the year's last digit of the first date a prediction gives
    at = text.index('"due_date": "', text.index('"entries": [')) + len('"due_date": "') + 3
    edited = tmp_path / "edited.json"
    edited.write_text(text[:at] + str((int(text[at]) + 1) % 10) + text[at + 1 :], encoding="utf-8")
    assert run(tmp_path, manifest, "--check", str(edited)) == 1
    out, err = capsys.readouterr()
    assert "differ" in out and err == ""
    # without the day index the letters take the planned day again, and the D2 unit has no recording for it
    index = root(tmp_path) / harness.DAY_INDEX_FILE
    index.rename(tmp_path / "set-aside.json")
    assert run(tmp_path, manifest, "--results-dir", str(tmp_path / "without")) == 1
