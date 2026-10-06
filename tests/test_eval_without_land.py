"""scripts/eval_without_land.py: the benchmark's Ordnung condition replayed as the app runs it, without the
sender's Land (which only the person can set); its published numbers are checked in test_docs_claims.py."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from ordnung.models import DocumentExtraction, ExtractedParty

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import conditions, report  # noqa: E402
from evals.records import load_manifest  # noqa: E402
from evals.run import MANIFEST_PATH  # noqa: E402
from scripts.eval_without_land import changed_dates, sender_land_unknown  # noqa: E402


def test_only_the_sender_s_land_is_taken_away() -> None:
    entry = next(e for e in load_manifest(MANIFEST_PATH) if e.split == "test" and e.authority_region)
    extraction = DocumentExtraction(
        kind="authority_letter",
        title="Bescheid",
        summary="A decision.",
        explanation="Object within a month.",
        sender=ExtractedParty(name="Stadt Musterstadt", kind="authority"),
        document_date="2026-03-02",
    )
    with_land = conditions.ordnung_rule_context(entry, extraction)
    with sender_land_unknown():
        without = conditions.ordnung_rule_context(entry, extraction)
    assert with_land.region == entry.authority_region and without.region is None
    assert without.recipient_region == with_land.recipient_region is not None  # the person's own Land stays
    assert dataclasses.replace(without, region=with_land.region) == with_land  # nothing else changes
    assert conditions.ordnung_rule_context(entry, extraction).region == entry.authority_region  # put back


def _run(predicted: dict[str, str]) -> dict[str, Any]:
    def scored(date: str) -> dict[str, Any]:
        early = date < "2026-11-03"
        return {
            "required": True,
            "expected": "2026-11-03",
            "predicted": date,
            "outcome": "wrong" if early else "correct",
            "direction": "early" if early else None,
            "days_off": -1 if early else None,
        }

    return {
        "entries": [
            {
                "id": entry_id,
                "family": "municipal_decision",
                "conditions": {"ordnung": {"score": {"items": [scored(date)]}}},
            }
            for entry_id, date in predicted.items()
        ]
    }


def test_the_changed_dates_name_the_letter_its_land_and_both_dates() -> None:
    with_land = _run({"test-a": "2026-11-03", "test-b": "2026-11-03"})
    without = _run({"test-a": "2026-11-02", "test-b": "2026-11-03"})
    assert changed_dates(with_land, without, {"test-a": "SH", "test-b": None}) == [
        {
            "entry_id": "test-a",
            "family": "municipal_decision",
            "letterhead_land": "SH",
            "expected": "2026-11-03",
            "with_land": "2026-11-03",
            "without_land": "2026-11-02",
            "outcome": "wrong",
            "direction": "early",
            "days_off": -1,
        }
    ]


def _results(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "evals" / "results" / name).read_text(encoding="utf-8"))


def test_the_benchmark_page_shows_both_numbers_per_split() -> None:
    """docs/evals.md gets a section of its own from the results file (``evals.report --without-land``)."""
    published = _results("2026-09-30-claude-sonnet-5-test.json")
    without_land = _results("2026-10-06-claude-sonnet-5-without-land.json")
    assert "## Without the sender's Land" not in report.render_markdown([published])
    page = report.render_markdown([published], without_land=without_land)
    section = page.split("## Without the sender's Land", 1)[1].split("\n## ", 1)[0]
    test = without_land["splits"]["test"]
    with_rate = report.rate(test["with_land"]["due_date_accuracy"], counts=True)
    without_rate = report.rate(test["without_land"]["due_date_accuracy"], counts=True)
    assert (
        f"| `test` | {with_rate} | {without_rate} | 0.0 % | {test['letterhead_land']} of {test['entries']} |"
        in section
    )
    assert "no date is late" in section and "`test-municipal_decision-D2` (NW)" in section
    assert "the rows “Without the sender's Land”" in page  # the method section points to them
    assert "python -m scripts.eval_without_land" in page.split("## Reproduce", 1)[1]
    with pytest.raises(ValueError, match="eval_without_land"):
        report.render_markdown([published], without_land=published)
