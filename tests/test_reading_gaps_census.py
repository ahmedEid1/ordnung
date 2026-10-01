"""Guard: on every recorded reading of the benchmark, the check for incomplete readings (``ingest/gaps.py``)
fires on exactly one letter — the empty reading it was written after.

Every manifest entry is read as the benchmark's Ordnung condition reads it, on replay only (no model call):
its pages rendered and their text layer read (``prepare_document``), photos transcribed from the recorded
transcripts, the recorded extraction, then the verification with the reading check. A new false positive on a
recorded letter — or a recording the current prompts no longer match — fails here. Only entry ids are compared.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.conditions import CallLog, MeteredBackend, prepare_document, run_ordnung  # noqa: E402
from evals.records import Entry, load_manifest  # noqa: E402
from evals.run import RecordedFailures  # noqa: E402

from ordnung.llm.replay import ReplayBackend  # noqa: E402
from ordnung.llm.runtime import LLMService  # noqa: E402

DATASET = ROOT / "evals" / "dataset"
MODEL = "claude-sonnet-5"
RECORDED = ROOT / "evals" / "recorded" / MODEL
#: Replays every recorded reading (about 45 s; five times that under coverage): CI runs it once, in the 3.12
#: job without coverage (``.github/workflows/ci.yml``).
pytestmark = pytest.mark.slow
#: The one letter whose recorded reading came back incomplete (only its required fields).
EXPECTED = {"holdout2-adversarial-injection_visible-1"}


async def _fires(entries: list[Entry], work: Path) -> tuple[set[str], int]:
    """The entries whose reading the check finds incomplete, and how many readings were checked."""
    backend = RecordedFailures(ReplayBackend(RECORDED), RECORDED, record=False)
    limit = asyncio.Semaphore(8)

    async def one(entry: Entry) -> tuple[str, bool, bool]:
        async with limit:
            document = await asyncio.to_thread(prepare_document, entry, DATASET, work)
            llm = LLMService(MeteredBackend(backend, CallLog(), timeout_s=60))
            prediction = await run_ordnung(entry, document, llm, model=MODEL)
            return entry.id, prediction.failed is None, "reading_incomplete" in prediction.signals

    results = await asyncio.gather(*(one(entry) for entry in entries))
    return {entry_id for entry_id, _, fired in results if fired}, sum(read for _, read, _ in results)


async def test_the_reading_check_fires_on_exactly_the_one_empty_recorded_reading(tmp_path: Path) -> None:
    entries = load_manifest(DATASET / "manifest.json")
    fired, read = await _fires(entries, tmp_path)
    splits = {entry.split for entry in entries}
    assert splits >= {"dev", "test", "holdout", "holdout2"}
    assert read == len(entries)  # every letter's reading replayed: none failed or missing
    assert fired == EXPECTED
