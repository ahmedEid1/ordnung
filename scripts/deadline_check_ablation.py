"""Measure the dropped-date check (``check:deadline``) on the benchmark letters with the readings' to-dos removed.

Every recorded reading of the manifest (every split) is replayed as the reading-gaps census replays it
(``tests/test_reading_gaps_census.py``): the pages rendered and their text layer read (``prepare_document``),
photos transcribed from the recorded transcripts, and the recorded extraction as first recorded (a completeness
re-ask recorded since is not replayed). Then the reading's to-dos are removed (``extraction.items = []``) and
``verify_extraction`` runs with the reading check, so every fixed date the letter sets in words the check reads
comes back as a ``check:deadline`` to-do of code's. Each filed date is compared with the letter's labelled due
dates (``evals.records.Truth``: a required or optional to-do's expected due date, its candidates, and its date
without the sender's Land): on one, it is a date the letter does set; off every one, a false alarm.

It is a replay only: no model is called, and a missing recording is an error. Only entry ids, dates and counts
are printed or written — never a letter's text, a reading or a quote.

Run it from the repository root::

    PYTHONPATH=src:. .venv/bin/python -m scripts.deadline_check_ablation --out PATH [--splits dev test …]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from evals.conditions import CallLog, MeteredBackend, prepare_document, transcribe_missing
from evals.records import PERSONA_LANGUAGE, Entry, Truth, load_manifest, parse_iso
from evals.run import RecordedFailures

from ordnung.ingest.extract import ExtractionInput, prompt_pages, read_document
from ordnung.ingest.gaps import DEADLINE_SLOT
from ordnung.ingest.pipeline import injection_warnings
from ordnung.ingest.plan import verify_extraction
from ordnung.llm.base import LLMRequest, ReplayMiss
from ordnung.llm.replay import ReplayBackend
from ordnung.llm.runtime import LLMService

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evals" / "dataset"
MODEL = "claude-sonnet-5"
RECORDED = ROOT / "evals" / "recorded" / MODEL
SPLITS = ("dev", "test", "holdout", "holdout2", "holdout3")


class WithoutReask:
    """The recordings as first recorded: a completeness re-ask's answer recorded since is missed (a replay miss,
    which :func:`read_document` takes as "no answer" and keeps the first reading)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name = inner.name

    async def complete(self, req: LLMRequest) -> Any:
        if req.prompt_name == "reading_gaps":
            raise ReplayMiss(f"no recorded response for {req.purpose} ({req.cache_key})")
        return await self.inner.complete(req)

    async def stream(self, req: LLMRequest) -> Any:  # pragma: no cover - an extraction never streams
        raise NotImplementedError


def labelled_dates(truth: Truth) -> set[date]:
    """Every due date the letter's labels give: each required or optional to-do's expected date, the dates it
    may also be (``candidates``) and its date without the sender's Land."""
    days: set[date] = set()
    for item in [*truth.items, *truth.optional_items]:
        for value in (item.expected_due, item.due_if_region_ignored, *item.candidates):
            day = parse_iso(value)
            if day is not None:
                days.add(day)
    return days


@dataclass
class Filed:
    entry_id: str
    split: str
    day: str
    nature: str
    on_label: bool


@dataclass
class Outcome:
    entry_id: str
    split: str
    read: bool
    filed: list[Filed] = field(default_factory=list)


async def one(entry: Entry, llm: LLMService, work: Path) -> Outcome:
    """The ``check:deadline`` to-dos of one letter whose reading's to-dos were removed."""
    document = await asyncio.to_thread(prepare_document, entry, DATASET, work)
    pages, _ = await transcribe_missing(llm, document.pages, doc_id=entry.id, model=MODEL)
    if not prompt_pages(pages):
        return Outcome(entry.id, entry.split, read=False)
    injected = bool(injection_warnings(pages))
    data = ExtractionInput(
        doc_id=entry.id,
        sha256=entry.sha256,
        pages=pages,
        today=entry.today,
        language=PERSONA_LANGUAGE,
        region=entry.region,
        country="DE",
        person_name="",
        known_parties=[],
        simulated_today=entry.today,
    )
    today = date.fromisoformat(entry.today)
    reading = await read_document(
        llm, data, model=MODEL, unrecorded=(ReplayMiss,), arrived=today, injected=injected
    )
    extraction = reading.extraction.model_copy(update={"items": []})
    verification = verify_extraction(
        entry.id, extraction, pages, check_reading=True, injected=injected, today=today
    )
    labelled = labelled_dates(entry.truth)
    filed = [
        Filed(
            entry.id,
            entry.split,
            verified.item.date.date or "",
            verified.item.date.nature,
            parse_iso(verified.item.date.date) in labelled,
        )
        for verified in verification.items
        if verified.slot_key.split("#")[0] == DEADLINE_SLOT
    ]
    return Outcome(entry.id, entry.split, read=True, filed=filed)


async def ablate(entries: Sequence[Entry]) -> list[Outcome]:
    backend = WithoutReask(RecordedFailures(ReplayBackend(RECORDED), RECORDED, record=False))
    limit = asyncio.Semaphore(8)
    with tempfile.TemporaryDirectory(prefix="ordnung-deadline-ablation-") as work:

        async def run(entry: Entry) -> Outcome:
            async with limit:
                llm = LLMService(MeteredBackend(backend, CallLog(), timeout_s=60))
                return await one(entry, llm, Path(work))

        return list(await asyncio.gather(*(run(entry) for entry in entries)))


def summary(outcomes: Sequence[Outcome], splits: Sequence[str]) -> dict[str, Any]:
    per_split: dict[str, Any] = {}
    for split in splits:
        mine = [outcome for outcome in outcomes if outcome.split == split]
        filed = [item for outcome in mine for item in outcome.filed]
        per_split[split] = {
            "letters": len(mine),
            "read": sum(outcome.read for outcome in mine),
            "letters_with_filed": sum(bool(outcome.filed) for outcome in mine),
            "filed": len(filed),
            "on_labelled_date": sum(item.on_label for item in filed),
            "not_on_labelled_date": sum(not item.on_label for item in filed),
            "off_label": [
                {"entry_id": item.entry_id, "date": item.day, "nature": item.nature}
                for item in filed
                if not item.on_label
            ],
        }
    every = [item for outcome in outcomes for item in outcome.filed]
    return {
        "model": MODEL,
        "backend": "replay",
        "note": (
            "The recorded readings as first recorded, their to-dos removed, verified with the reading check: the "
            "check:deadline to-dos code files, each compared with the letter's labelled due dates. Ids and dates only."
        ),
        "splits": per_split,
        "total": {
            "letters": len(outcomes),
            "filed": len(every),
            "on_labelled_date": sum(item.on_label for item in every),
            "not_on_labelled_date": sum(not item.on_label for item in every),
        },
        "filed": [
            {
                "entry_id": item.entry_id,
                "split": item.split,
                "date": item.day,
                "nature": item.nature,
                "on_labelled_date": item.on_label,
            }
            for item in sorted(every, key=lambda item: (item.split, item.entry_id, item.day))
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.deadline_check_ablation", description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="where to write the JSON summary")
    parser.add_argument("--splits", nargs="+", choices=SPLITS, default=list(SPLITS), help="splits to replay")
    args = parser.parse_args(argv)
    entries = [entry for entry in load_manifest(DATASET / "manifest.json") if entry.split in args.splits]
    outcomes = asyncio.run(ablate(entries))
    result = summary(outcomes, args.splits)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for split, numbers in result["splits"].items():
        print(
            f"{split:<9} letters {numbers['letters']:>3}  filed {numbers['filed']:>3}  "
            f"on a labelled date {numbers['on_labelled_date']:>3}  not on one {numbers['not_on_labelled_date']:>3}"
        )
        for off in numbers["off_label"]:
            print(f"          not on a labelled date: {off['entry_id']} {off['date']} ({off['nature']})")
    total = result["total"]
    print(
        f"{'all':<9} letters {total['letters']:>3}  filed {total['filed']:>3}  "
        f"on a labelled date {total['on_labelled_date']:>3}  not on one {total['not_on_labelled_date']:>3}"
    )
    print(f"summary → {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
