"""scripts/eval_without_land.py: the benchmark's Ordnung condition replayed as the app runs it, without the
sender's Land (which only the person can set), and with the state the postcode on their letter suggests
confirmed; its published numbers are checked in test_docs_claims.py."""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, get_args

import pytest

from ordnung.models import DocumentExtraction, ExtractedParty, Page
from ordnung.rules.postcodes import Reason, suggest_land_why

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import conditions, report  # noqa: E402
from evals.records import load_manifest, select_entries  # noqa: E402
from evals.run import DEFAULT_MODEL, MANIFEST_PATH  # noqa: E402
from scripts.eval_without_land import (  # noqa: E402
    changed_dates,
    changed_with_suggestion,
    sender_land_suggested,
    sender_land_unknown,
    split_numbers,
    suggestion_counts,
)

#: The published replay (``python -m scripts.eval_without_land --date 2026-10-08``).
PUBLISHED = "2026-10-08-claude-sonnet-5-without-land.json"

#: Every reason a letter gets no suggestion, each counted (zero included).
NO_SUGGESTION = dict.fromkeys((reason for reason in get_args(Reason) if reason != "suggested"), 0)


def _extraction(
    address: str | None = None, *, email: str | None = None, sender: bool = True
) -> DocumentExtraction:
    return DocumentExtraction(
        kind="authority_letter",
        title="Bescheid",
        summary="A decision.",
        explanation="Object within a month.",
        sender=(
            ExtractedParty(name="Stadt Musterstadt", kind="authority", address=address, email=email)
            if sender
            else None
        ),
        document_date="2026-03-02",
    )


def _pages(*texts: str) -> list[Page]:
    return [
        Page(page=number, width=595, height=842, doc_id="doc_x", image_path="", text=text)
        for number, text in enumerate(texts, 1)
    ]


def _letterhead_entry(other_than: str) -> Any:
    return next(
        e
        for e in load_manifest(MANIFEST_PATH)
        if e.split == "test" and e.authority_region not in (None, other_than)
    )


def test_only_the_sender_s_land_is_taken_away() -> None:
    entry = next(e for e in load_manifest(MANIFEST_PATH) if e.split == "test" and e.authority_region)
    extraction = _extraction()
    with_land = conditions.ordnung_rule_context(entry, extraction)
    with sender_land_unknown():
        without = conditions.ordnung_rule_context(entry, extraction)
    assert with_land.region == entry.authority_region and without.region is None
    assert without.recipient_region == with_land.recipient_region is not None  # the person's own Land stays
    assert dataclasses.replace(without, region=with_land.region) == with_land  # nothing else changes
    assert conditions.ordnung_rule_context(entry, extraction).region == entry.authority_region  # put back


def test_the_suggested_state_confirmed_replaces_only_the_sender_s_land() -> None:
    """The person says Yes to every suggestion: the engine gets the Land the postcode on the sender's letter
    suggests instead of the letterhead's, and nothing else changes."""
    entry = _letterhead_entry(other_than="BY")
    extraction = _extraction("Rathausplatz 1, 80331 Musterstadt")
    pages = _pages("Stadt Musterstadt", "Rathausplatz 1\n80331 Musterstadt")
    with_land = conditions.ordnung_rule_context(entry, extraction, pages)
    with sender_land_suggested() as suggested:
        confirmed = conditions.ordnung_rule_context(entry, extraction, pages)
    assert confirmed.region == "BY" != with_land.region == entry.authority_region
    assert confirmed.recipient_region == with_land.recipient_region is not None  # the person's own Land stays
    assert dataclasses.replace(confirmed, region=with_land.region) == with_land  # nothing else changes
    assert suggested == {entry.id: ("BY", "suggested")}
    assert (
        conditions.ordnung_rule_context(entry, extraction, pages).region == entry.authority_region
    )  # put back


@pytest.mark.parametrize(
    ("extraction", "pages"),
    [
        (_extraction("Rathausplatz 1, 80331 Musterstadt"), _pages("Rathausplatz 1, 80331 Musterstadt")),
        (_extraction("Rathausplatz 1, 80331 Musterstadt"), _pages("Rathausplatz 1, Musterstadt")),
        (_extraction("Rathausplatz 1, 80331 Musterstadt", email="post@musterstadt.fr"), _pages("80331")),
        (_extraction("Postfach 12345, Musterstadt"), _pages("Postfach 12345")),
        (_extraction(None), _pages("80331")),
        (_extraction(sender=False), _pages("80331")),
    ],
    ids=["suggested", "not_visible", "foreign", "no_postcode", "no_address", "no_sender"],
)
def test_the_suggestion_is_the_app_s_own_from_the_reading_and_the_visible_text(
    extraction: DocumentExtraction, pages: list[Page]
) -> None:
    """``suggest_land_why`` decides, given the reading's sender and the pages' text (no own-Land check: the
    benchmark has no profile address); a letter without a sender has no address."""
    entry = _letterhead_entry(other_than="BY")
    sender = extraction.sender
    hit, reason = suggest_land_why(
        sender.address if sender else None,
        email=sender.email if sender else None,
        website=sender.website if sender else None,
        visible_text="\n".join(page.text for page in pages),
    )
    with sender_land_suggested() as suggested:
        confirmed = conditions.ordnung_rule_context(entry, extraction, pages)
    region = hit.region if hit else None
    assert confirmed.region == region
    assert suggested == {entry.id: (region, reason)}


def test_the_suggestions_are_counted_against_the_letterhead_s_land_with_a_reason_for_each_none() -> None:
    lands = {"a": "BY", "b": "BY", "c": "NW", "d": None, "e": None, "f": None, "g": "SH"}
    suggested: dict[str, tuple[str | None, Reason]] = {
        "a": ("BY", "suggested"),
        "b": ("HE", "suggested"),
        "c": (None, "not_listed"),
        "d": ("BE", "suggested"),
        "e": (None, "foreign"),
        "f": (None, "foreign"),
        "g": ("SH", "suggested"),
    }
    assert suggestion_counts(lands, suggested) == {
        "letterhead_land": 4,
        "right": 2,
        "wrong": 1,
        "none": {**NO_SUGGESTION, "not_listed": 1},
        "suggested_without_letterhead_land": 1,
        "not_suggested_without_letterhead_land": {**NO_SUGGESTION, "foreign": 2},
    }
    # a letter the rules engine never saw is an error, not a letter without a suggestion
    with pytest.raises(RuntimeError, match="never reached the rules engine: g"):
        suggestion_counts(lands, {key: value for key, value in suggested.items() if key != "g"})


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


def test_the_dates_the_suggestion_changes_name_the_letter_both_lands_and_both_dates() -> None:
    with_land = _run({"test-a": "2026-11-03", "test-b": "2026-11-03"})
    suggested = _run({"test-a": "2026-11-02", "test-b": "2026-11-03"})
    lands = {"test-a": "SH", "test-b": None}
    assert changed_with_suggestion(with_land, suggested, lands, {"test-a": "HH", "test-b": "BE"}) == [
        {
            "entry_id": "test-a",
            "family": "municipal_decision",
            "letterhead_land": "SH",
            "suggested_land": "HH",
            "expected": "2026-11-03",
            "with_land": "2026-11-03",
            "with_suggestion": "2026-11-02",
            "outcome": "wrong",
            "direction": "early",
            "days_off": -1,
        }
    ]
    assert changed_with_suggestion(with_land, with_land, lands, {"test-a": "HH", "test-b": None}) == []


def _results(name: str) -> dict[str, Any]:
    return json.loads((ROOT / "evals" / "results" / name).read_text(encoding="utf-8"))


def test_the_page_takes_only_the_results_with_the_suggested_state() -> None:
    """The first version of the results (2026-10-06, two replays) stays as history; the page needs the third."""
    first = _results("2026-10-06-claude-sonnet-5-without-land.json")
    assert first["schema"] == "ordnung-eval-without-land/1"
    published = _results("2026-09-30-claude-sonnet-5-test.json")
    with pytest.raises(ValueError, match="ordnung-eval-without-land/2"):
        report.render_markdown([published], without_land=first)
    with pytest.raises(ValueError, match="eval_without_land"):
        report.render_markdown([published], without_land=published)


def _section(page: str) -> str:
    return page.split("## Without the sender's Land", 1)[1].split("\n## ", 1)[0]


def test_the_benchmark_page_shows_three_numbers_per_split() -> None:
    """docs/evals.md gets a section of its own from the results file (``evals.report --without-land``): with the
    letterhead's Land, without the sender's Land, and with the suggested state confirmed."""
    published = _results("2026-09-30-claude-sonnet-5-test.json")
    without_land = _results(PUBLISHED)
    assert "## Without the sender's Land" not in report.render_markdown([published])
    page = report.render_markdown([published], without_land=without_land)
    section = _section(page)
    for split, numbers in without_land["splits"].items():
        assert (
            f"| `{split}` | {report.rate(numbers['with_land']['due_date_accuracy'], counts=True)} "
            f"| {report.rate(numbers['without_land']['due_date_accuracy'], counts=True)} "
            f"| {report.rate(numbers['with_suggestion']['due_date_accuracy'], counts=True)} "
            f"| {report.rate(numbers['without_land']['dangerous_late_rate'], ci=False)} / "
            f"{report.rate(numbers['with_suggestion']['dangerous_late_rate'], ci=False)} "
            f"| {numbers['letterhead_land']} of {numbers['entries']} |"
        ) in section, split
    counts = [numbers["suggestion"] for numbers in without_land["splits"].values()]
    letterhead = sum(c["letterhead_land"] for c in counts)
    right, wrong = sum(c["right"] for c in counts), sum(c["wrong"] for c in counts)
    none = sum(sum(c["none"].values()) for c in counts)
    assert (
        f"The postcode on the sender's letter suggested the letterhead's state for {right} of the {letterhead} "
        f"letters that name one, another state for {wrong}, and none for {none}; with every suggestion "
        "confirmed, 0 required dates differ from the letterhead replay."
    ) in " ".join(section.split())
    assert "no date is late" in section and "`test-municipal_decision-D2` (NW)" in section
    assert "the rows “Without the sender's Land”" in page  # the method section points to them
    assert "python -m scripts.eval_without_land" in page.split("## Reproduce", 1)[1]


def _every_suggestion_right(first: dict[str, Any]) -> dict[str, Any]:
    """The first version's results as the second would read had the postcode suggested every letterhead's
    Land, and a state for every other letter, moving no date."""
    second = copy.deepcopy(first)
    second["schema"] = report.WITHOUT_LAND_SCHEMA
    for numbers in second["splits"].values():
        numbers["with_suggestion"] = numbers["with_land"]
        numbers["suggestion"] = {
            "letterhead_land": numbers["letterhead_land"],
            "right": numbers["letterhead_land"],
            "wrong": 0,
            "none": dict(NO_SUGGESTION),
            "suggested_without_letterhead_land": numbers["entries"] - numbers["letterhead_land"],
            "not_suggested_without_letterhead_land": dict(NO_SUGGESTION),
        }
        numbers["changed_with_suggestion"] = []
    return second


def test_the_page_names_a_wrong_suggestion_s_moved_date_and_why_letters_got_none() -> None:
    """Were a suggestion wrong and a date to move with it, the section would name the letter, both Länder and
    both dates; the letters without a suggestion are counted by reason."""
    published = _results("2026-09-30-claude-sonnet-5-test.json")
    without_land = _every_suggestion_right(_results("2026-10-06-claude-sonnet-5-without-land.json"))
    test = without_land["splits"]["test"]
    test["suggestion"]["right"] -= 2
    test["suggestion"]["wrong"] += 1
    test["suggestion"]["none"]["not_listed"] += 1
    test["suggestion"]["suggested_without_letterhead_land"] -= 3
    test["suggestion"]["not_suggested_without_letterhead_land"].update(foreign=2, no_postcode=1)
    test["changed_with_suggestion"] = [
        {
            "entry_id": "test-municipal_decision-D2",
            "family": "municipal_decision",
            "letterhead_land": "NW",
            "suggested_land": "NI",
            "expected": "2026-01-27",
            "with_land": "2026-01-27",
            "with_suggestion": "2026-01-28",
            "outcome": "wrong",
            "direction": "late",
            "days_off": 1,
        }
    ]
    section = " ".join(_section(report.render_markdown([published], without_land=without_land)).split())
    assert "| With the suggested state confirmed |" in section
    letterhead = sum(numbers["letterhead_land"] for numbers in without_land["splits"].values())
    others = sum(n["entries"] - n["letterhead_land"] for n in without_land["splits"].values())
    assert (
        f"suggested the letterhead's state for {letterhead - 2} of the {letterhead} letters that name one, another "
        "state for 1, and none for 1; with every suggestion confirmed, 1 required date differs from the "
        "letterhead replay."
    ) in section
    assert (
        "The dates the suggestion moves (with the letterhead's Land and the suggested one): "
        "- `test-municipal_decision-D2` (NW, suggested NI): Wed 28 Jan 2026 instead of Tue 27 Jan 2026"
    ) in section
    assert (
        "No suggestion for 1 (1 with a postcode GeoNames doesn't list) of the letters whose letterhead names a "
        f"state, and for 3 (2 with an address abroad, 1 without a postcode) of the {others} whose letterhead "
        f"names none; the other {others - 3} got one."
    ) in section


def test_the_published_replay_has_no_wrong_suggestion_and_moves_no_date() -> None:
    """The shipped file: no suggestion names another Land than the letterhead, no required date differs from
    the letterhead replay, none is late, and every letter is counted once."""
    results = _results(PUBLISHED)
    assert results["schema"] == report.WITHOUT_LAND_SCHEMA == "ordnung-eval-without-land/2"
    assert results["meta"]["backend"] == "replay" and results["meta"]["condition"] == "ordnung"
    assert set(results["splits"]) == {"test", "holdout", "holdout2", "holdout3", "dev"}
    for split, numbers in results["splits"].items():
        suggestion = numbers["suggestion"]
        assert suggestion["wrong"] == 0 and numbers["changed_with_suggestion"] == [], split
        assert numbers["with_suggestion"]["dangerous_late_rate"]["k"] == 0, split
        assert numbers["with_suggestion"] == numbers["with_land"], split
        assert suggestion["letterhead_land"] == numbers["letterhead_land"], split
        assert suggestion["right"] + sum(suggestion["none"].values()) == numbers["letterhead_land"], split
        assert (
            suggestion["suggested_without_letterhead_land"]
            + sum(suggestion["not_suggested_without_letterhead_land"].values())
            == numbers["entries"] - numbers["letterhead_land"]
        ), split
        assert set(suggestion["none"]) == set(NO_SUGGESTION), split


def test_the_published_replay_keeps_the_first_version_s_two_replays() -> None:
    """The letterhead and without-Land replays are the 2026-10-06 file's, number for number and date for date:
    only the third replay is new."""
    first = _results("2026-10-06-claude-sonnet-5-without-land.json")["splits"]
    second = _results(PUBLISHED)["splits"]
    assert set(first) == set(second)
    for split, numbers in first.items():
        for key in ("entries", "letterhead_land", "with_land", "without_land", "changed"):
            assert second[split][key] == numbers[key], (split, key)


@pytest.mark.slow
def test_replaying_the_dev_split_gives_the_published_numbers() -> None:
    """The shipped file is what the script writes: the dev split replayed three ways, from the recordings."""
    entries = select_entries(load_manifest(MANIFEST_PATH), split="dev")
    numbers = asyncio.run(split_numbers("dev", DEFAULT_MODEL, entries))
    assert numbers == _results(PUBLISHED)["splits"]["dev"]
