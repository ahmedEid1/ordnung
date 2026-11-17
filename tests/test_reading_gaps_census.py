"""Guard: on every recorded reading of the benchmark, the check for incomplete readings (``ingest/gaps.py``)
fires on exactly one letter — the empty reading it was written after —, the letter's own notice is never
set beside a reading's objection date (``gaps.notice_rival``: no recorded reading dates it weeks later), and no
reading left out a fixed date the letter sets (``gaps.deadline_items``: no ``check:deadline`` to-do).

The final run's readings (holdout4, newkinds) join once their first read is published, and are held to what that
read recorded: on each letter, replayed on its read's day with its re-ask as recorded, the check gives the verdicts
the published file holds (the same three signals, and whether the letter was read at all). Those readings were made
with the code they are replayed with, so a fire, a replaced notice or a left-out date there is a result of the run,
which the publication reports, not a defect of the check. A verdict that differs from the published one is a defect:
a replay on another day, a missing recording, a check that no longer gives what it gave.

Every manifest entry of a recorded split is read as the benchmark's Ordnung condition reads it, on replay only (no
model call): its pages rendered and their text layer read (``prepare_document``), photos transcribed from the
recorded transcripts, the recorded extraction, then the verification with the reading check. A new false positive on a
recorded letter — or a recording the current prompts no longer match — fails here. Only entry ids are compared.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import harness, splits  # noqa: E402
from evals.conditions import CallLog, MeteredBackend, prepare_document, run_ordnung  # noqa: E402
from evals.records import Entry, load_manifest  # noqa: E402
from evals.run import RecordedFailures  # noqa: E402

from ordnung.llm.replay import ReplayBackend  # noqa: E402
from ordnung.llm.runtime import LLMService  # noqa: E402
from test_final_gates import final_reads  # noqa: E402
from test_final_labels_unused import unrecorded_final_splits  # noqa: E402
from test_reading_reask import WithoutReask, as_first_recorded  # noqa: E402

DATASET = ROOT / "evals" / "dataset"
MODEL = "claude-sonnet-5"
RECORDED = ROOT / "evals" / "recorded" / MODEL
#: Replays every recorded reading (about 45 s; five times that under coverage): CI runs it once, in the job of
#: slow checks, without coverage (``.github/workflows/ci.yml``).
pytestmark = pytest.mark.slow
#: The one letter whose recorded reading came back incomplete (only its required fields).
EXPECTED = {"holdout2-adversarial-injection_visible-1"}
RESULTS = ROOT / "evals" / "results"
#: The signals the census reads (``evals/conditions.py`` adds them to a prediction).
SIGNALS = ("reading_incomplete", "objection_after_notice", "deadline_left_out")
#: One letter's verdicts: whether it was read, then each of :data:`SIGNALS`.
Verdict = tuple[bool, bool, bool, bool]


def recorded_letters(entries: Sequence[Entry], results_dir: Path = RESULTS) -> list[Entry]:
    """The letters whose readings the census replays: every split's but those of a final split whose live run is not
    published in ``results_dir`` yet (``tests/test_final_labels_unused.py``). Those stay unseen until their one
    recording, so the app is never run on them here; read from the results, a published final run joins the census
    with no edit here."""
    unrecorded = unrecorded_final_splits(results_dir)
    return [entry for entry in entries if entry.split not in unrecorded]


def on_their_days(entries: Sequence[Entry], recorded: Path = RECORDED) -> list[Entry]:
    """Each final split's letter on the day its first read recorded it (the day index, ``final-days.json``), as
    ``ordnung eval --split <split>`` replays it: a recording's request holds the day it was made on, and the final
    run's reads span several days. Every other letter keeps the manifest's day."""
    index = harness.DayIndex(recorded / "final-days.json")
    on_days = []
    for entry in entries:
        unit = index.attempted(entry.split, 1).get(entry.id) if splits.is_final(entry.split) else None
        on_days.append(entry.model_copy(update={"today": str(unit["day"])}) if unit else entry)
    return on_days


def published_first_reads(results_dir: Path = RESULTS) -> dict[str, dict[str, Any]]:
    """Each final split's letter in its published first read (``results_dir``): entry id → that read's entry (its
    day, and the ``ordnung`` condition's prediction)."""
    found: dict[str, dict[str, Any]] = {}
    for read in final_reads(results_dir):
        if read.kind == "benchmark" and read.repeat == 1:
            found.update({str(entry["id"]): entry for entry in read.data["entries"]})
    return found


def verdict(failed: object, signals: Sequence[str]) -> Verdict:
    """A prediction's verdicts (:data:`Verdict`) from its ``failed`` and ``signals``."""
    incomplete, notice, left_out = (signal in signals for signal in SIGNALS)
    return failed is None, incomplete, notice, left_out


def published_verdict(entry: dict[str, Any]) -> Verdict:
    """The verdicts a published read recorded for one letter (its ``ordnung`` condition's prediction)."""
    prediction = entry["conditions"]["ordnung"]["prediction"]
    return verdict(prediction["failed"], prediction["signals"])


async def _verdicts(entries: list[Entry], work: Path) -> dict[str, Verdict]:
    """Each entry's verdicts, its reading replayed as the benchmark's Ordnung condition reads it."""
    replay = RecordedFailures(ReplayBackend(RECORDED), RECORDED, record=False)
    # the check guards the readings as first recorded: a completeness re-ask recorded since is missed here; the
    # final run's readings are replayed as they were recorded, their re-asks with them
    first = WithoutReask(replay)
    limit = asyncio.Semaphore(8)

    async def one(entry: Entry) -> tuple[str, Verdict]:
        async with limit:
            document = await asyncio.to_thread(prepare_document, entry, DATASET, work)
            backend = replay if splits.is_final(entry.split) else first
            llm = LLMService(MeteredBackend(backend, CallLog(), timeout_s=60))
            prediction = await run_ordnung(entry, document, llm, model=MODEL)
            return entry.id, verdict(prediction.failed, prediction.signals)

    return dict(await asyncio.gather(*(one(entry) for entry in entries)))


async def test_the_reading_check_fires_on_exactly_the_one_empty_recorded_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    as_first_recorded(monkeypatch)  # the readings as first recorded: the empty one's re-ask is missed
    entries = on_their_days(recorded_letters(load_manifest(DATASET / "manifest.json")))
    verdicts = await _verdicts(entries, tmp_path)
    assert {entry.split for entry in entries} >= {"dev", "test", "holdout", "holdout2"}
    earlier = [entry.id for entry in entries if not splits.is_final(entry.split)]
    assert [entry_id for entry_id in earlier if not verdicts[entry_id][0]] == []  # none failed or missing
    assert {entry_id for entry_id in earlier if verdicts[entry_id][1]} == EXPECTED
    assert {entry_id for entry_id in earlier if verdicts[entry_id][2]} == set()
    assert {entry_id for entry_id in earlier if verdicts[entry_id][3]} == set()
    # the final run's letters, each on its first read's day: the verdicts that read recorded, letter by letter
    final = [entry for entry in entries if splits.is_final(entry.split)]
    published = published_first_reads()
    assert [entry.id for entry in final if published.get(entry.id, {}).get("today") != entry.today] == []
    recorded = {entry.id: published_verdict(published[entry.id]) for entry in final}
    assert {entry.id: verdicts[entry.id] for entry in final} == recorded
    unread = sum(not found[0] for found in recorded.values())
    counts = ", ".join(
        f"{sum(found[1 + at] for found in recorded.values())} {name}" for at, name in enumerate(SIGNALS)
    )
    print(f"the final run's first reads: {len(recorded)} letters, {unread} not read, {counts}")
