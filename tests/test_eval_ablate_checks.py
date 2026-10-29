"""scripts/eval_ablate_checks.py: Ordnung's code checks switched off one at a time on the recorded readings
(defence in depth, zero tokens), and the published results file it writes."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ordnung.ingest import extract as extract_mod
from ordnung.ingest import plan as plan_mod
from ordnung.ingest.conflicts import CONFLICTING_DATES
from ordnung.ingest.plan import compute_item, verify_extraction
from ordnung.models import DocumentExtraction, ExtractedItem
from ordnung.rules import RuleContext

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import conditions  # noqa: E402
from evals.run import DEFAULT_MODEL, RESULTS_DIR  # noqa: E402
from scripts import eval_ablate_checks  # noqa: E402
from scripts.eval_ablate_checks import (  # noqa: E402
    ABLATIONS,
    SCHEMA,
    ablated,
    changed_items,
    counts,
    differences,
    letters_acted,
)

#: The published replay (``python -m scripts.eval_ablate_checks --date 2026-10-29``).
PUBLISHED = RESULTS_DIR / "2026-10-29-claude-sonnet-5-checks-ablated.json"
#: The functions the ablations swap, as (module, attribute).
TARGETS = {
    "settle": (plan_mod, "settle"),
    "notice": (plan_mod, "_notice_beside"),
    "reask": (extract_mod, "reading_gap_of"),
    "check": (conditions, "verify_extraction"),
}
#: What each ablation swaps (the plan's six, after the code as it ships).
SWAPPED = {
    "all_on": set(),
    "no_two_dates_check": {"settle"},
    "no_notice_guard": {"notice"},
    "no_reask": {"reask"},
    "no_reading_check": {"check"},
    "no_reask_no_reading_check": {"reask", "check"},
    "all_off": {"settle", "reask", "check"},
}


def _published() -> dict[str, Any]:
    return json.loads(PUBLISHED.read_text(encoding="utf-8"))


def test_the_ablations_are_the_shipped_code_and_the_plan_s_six() -> None:
    assert list(ABLATIONS) == list(SWAPPED)
    for name, ablation in ABLATIONS.items():
        assert ablation.name == name
        assert ablation.label and ablation.label[0].isupper()
        # every switched-off function is named in code terms, and only the shipped code switches nothing off
        assert bool(ablation.switches_off) == (name != "all_on")


@pytest.mark.parametrize("name", list(SWAPPED))
def test_each_ablation_swaps_only_its_functions_and_puts_them_back(name: str) -> None:
    before = {key: getattr(module, attr) for key, (module, attr) in TARGETS.items()}
    with ablated(name):
        swapped = {key for key, (module, attr) in TARGETS.items() if getattr(module, attr) is not before[key]}
    assert swapped == SWAPPED[name]
    assert all(getattr(module, attr) is before[key] for key, (module, attr) in TARGETS.items())


def test_an_ablation_puts_the_functions_back_after_an_error() -> None:
    original = plan_mod.settle
    with pytest.raises(RuntimeError, match="boom"), ablated("all_off"):
        raise RuntimeError("boom")
    assert plan_mod.settle is original and conditions.verify_extraction is verify_extraction


def test_the_replays_of_a_split_prepare_each_letter_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rendering pages and reading the text layer come before every check: one preparation serves them all."""
    from evals import run as run_mod

    prepared: list[tuple[str, Path]] = []

    def prepare(entry: Any, dataset_dir: Path, work_dir: Path) -> tuple[str, str]:
        prepared.append((entry.id, work_dir))
        return (entry.id, entry.sha256)

    monkeypatch.setattr(run_mod, "prepare_document", prepare)
    letter = type("Letter", (), {"id": "x-a", "sha256": "aa"})()
    regenerated = type("Letter", (), {"id": "x-a", "sha256": "bb"})()
    with eval_ablate_checks.documents_prepared_once(tmp_path):
        first = run_mod.prepare_document(letter, ROOT, tmp_path / "one")
        assert run_mod.prepare_document(letter, ROOT, tmp_path / "two") is first
        assert run_mod.prepare_document(regenerated, ROOT, tmp_path / "two") == ("x-a", "bb")
    assert prepared == [("x-a", tmp_path), ("x-a", tmp_path)]
    assert run_mod.prepare_document is prepare


def test_an_unknown_ablation_is_an_error() -> None:
    with pytest.raises(KeyError, match="no_such_check"), ablated("no_such_check"):
        pass


# --------------------------------------------------------------------------------------------------
# What each switch does to the code it switches off (synthetic letters, no benchmark text)
# --------------------------------------------------------------------------------------------------

#: An invoice with two dates for one payment: 14 days after its date (Mon 16 Mar 2026), and a box's date a week
#: later. The two-dates check keeps the earlier one and says "Please check".
TWO_DATES = (
    "Beispielstadt, 02.03.2026\n"
    "Rechnung Nr. AB-12\n"
    "Bitte zahlen Sie den Betrag von 80,00 EUR binnen 14 Tagen nach dem\n"
    "Rechnungsdatum.\n"
    "Zahlbar bis: 23.03.2026\n"
)
BOX = ExtractedItem.model_validate(
    {
        "kind": "payment",
        "title": "t",
        "quote": "Zahlbar bis: 23.03.2026",
        "amount": 80.0,
        "date": {
            "type": "fixed",
            "date": "2026-03-23",
            "nature": "payment",
            "text": "Zahlbar bis: 23.03.2026",
        },
    }
)


def _box_due() -> tuple[str | None, bool]:
    reading = DocumentExtraction(kind="invoice", title="Letter", summary="s", explanation="e", items=[BOX])
    [verified] = verify_extraction("doc_x", reading, [(1, TWO_DATES, [], "text")]).items
    ctx = RuleContext(
        today=date(2026, 3, 2), document_date=date(2026, 3, 2), private_sender=True, sender_kind="company"
    )
    result = compute_item(verified, ctx, postal_buffer_days=3)
    return result.due_date, result.conflict


def test_without_the_two_dates_check_the_reading_s_own_date_stands() -> None:
    assert _box_due() == ("2026-03-16", True)  # as it ships: the earlier date, "Please check"
    with ablated("no_two_dates_check"):
        assert _box_due() == ("2026-03-23", False)
    assert _box_due() == ("2026-03-16", True)


def test_without_the_reading_check_verify_is_asked_for_no_check(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[bool] = []

    def spy(*args: Any, check_reading: bool = False, **kwargs: Any) -> str:
        seen.append(check_reading)
        return "verified"

    monkeypatch.setattr(conditions, "verify_extraction", spy)
    with ablated("no_reading_check"):
        assert conditions.verify_extraction("doc", None, [], check_reading=True) == "verified"
    conditions.verify_extraction("doc", None, [], check_reading=True)
    assert seen == [False, True]


def test_without_the_reask_no_reading_has_a_gap() -> None:
    reading = DocumentExtraction(kind="authority_letter", title="Letter", summary="s", explanation="e")
    with ablated("no_reask"):
        assert extract_mod.reading_gap_of(reading, []) is None


def test_without_the_notice_guard_no_notice_is_set_beside() -> None:
    with ablated("no_notice_guard"):
        assert plan_mod._notice_beside(None, None, None, postal_buffer_days=3) == ()  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------------
# Counting and comparing replays (hand-made results documents)
# --------------------------------------------------------------------------------------------------


def _item(index: int, expected: str | None, predicted: str | None, **extra: Any) -> dict[str, Any]:
    outcome, direction, days_off = "unscored", None, None
    if expected is not None:
        if predicted is None:
            outcome = extra.pop("outcome", "missed")
        elif predicted == expected:
            outcome = "correct"
        else:
            outcome = "wrong"
            days_off = (date.fromisoformat(predicted) - date.fromisoformat(expected)).days
            direction = "late" if days_off > 0 else "early"
    return {
        "index": index,
        "expected": expected,
        "predicted": predicted,
        "outcome": outcome,
        "direction": direction,
        "days_off": days_off,
        "flagged": extra.get("flagged", False),
        "confidence": extra.get("confidence", "high"),
        "title": "never copied",
    }


def _entry(
    entry_id: str, items: list[dict[str, Any]], *, signals: list[str], rules: list[str]
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "family": "invoice_relative",
        "conditions": {
            "ordnung": {
                "prediction": {"signals": signals, "items": [{"rule_ids": rules, "quote": "never copied"}]},
                "score": {"items": items},
            }
        },
    }


def _results(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"entries": list(entries)}


ON = _results(
    _entry(
        "x-a",
        [
            _item(0, "2026-11-03", "2026-11-03", flagged=True, confidence="low"),
            _item(1, None, "2026-12-01"),  # optional: never scored
        ],
        signals=["reading_reask:accepted"],
        rules=[CONFLICTING_DATES],
    ),
    _entry("x-b", [_item(0, "2026-11-10", "2026-11-09")], signals=["reading_incomplete"], rules=[]),
    _entry(
        "x-c", [_item(0, "2026-11-12", None, outcome="declined")], signals=["deadline_left_out"], rules=[]
    ),
    _entry("x-d", [_item(0, "2026-11-20", "2026-11-20")], signals=["objection_after_notice"], rules=[]),
)
OFF = _results(
    _entry(
        "x-a",
        [_item(0, "2026-11-03", "2026-11-10"), _item(1, None, "2026-12-02")],
        signals=[],
        rules=[],
    ),
    _entry("x-b", [_item(0, "2026-11-10", "2026-11-09")], signals=[], rules=[]),
    _entry("x-c", [_item(0, "2026-11-12", None)], signals=[], rules=[]),
    _entry(
        "x-d", [_item(0, "2026-11-20", "2026-11-20", flagged=True, confidence="low")], signals=[], rules=[]
    ),
)


def test_the_counts_are_of_scored_items_and_the_letters_each_check_acted_on() -> None:
    assert counts(ON) == {
        "scored": 4,
        "right": 2,
        "early": 1,
        "late": 0,
        "missed": 0,
        "declined": 1,
        "flagged": 1,
        "flagged_wrong": 0,
    }
    assert counts(OFF) == {
        "scored": 4,
        "right": 1,
        "early": 1,
        "late": 1,
        "missed": 1,
        "declined": 0,
        "flagged": 1,
        "flagged_wrong": 0,
    }
    assert letters_acted(ON) == {
        "two_dates": 1,
        "notice_guard": 1,
        "reask": 1,
        "reading_check": 1,
        "deadline_check": 1,
    }
    assert letters_acted(OFF) == dict.fromkeys(letters_acted(ON), 0)


def test_the_changed_items_name_the_letter_the_item_and_both_readings_and_nothing_else() -> None:
    changed = changed_items(ON, OFF)
    assert changed == [
        {
            "entry_id": "x-a",
            "family": "invoice_relative",
            "item": 0,
            "expected": "2026-11-03",
            "all_on": {
                "predicted": "2026-11-03",
                "outcome": "correct",
                "direction": None,
                "days_off": None,
                "flagged": True,
                "confidence": "low",
            },
            "ablated": {
                "predicted": "2026-11-10",
                "outcome": "wrong",
                "direction": "late",
                "days_off": 7,
                "flagged": False,
                "confidence": "high",
            },
        },
        {
            "entry_id": "x-c",
            "family": "invoice_relative",
            "item": 0,
            "expected": "2026-11-12",
            "all_on": {
                "predicted": None,
                "outcome": "declined",
                "direction": None,
                "days_off": None,
                "flagged": False,
                "confidence": "high",
            },
            "ablated": {
                "predicted": None,
                "outcome": "missed",
                "direction": None,
                "days_off": None,
                "flagged": False,
                "confidence": "high",
            },
        },
        {
            "entry_id": "x-d",
            "family": "invoice_relative",
            "item": 0,
            "expected": "2026-11-20",
            "all_on": {
                "predicted": "2026-11-20",
                "outcome": "correct",
                "direction": None,
                "days_off": None,
                "flagged": False,
                "confidence": "high",
            },
            "ablated": {
                "predicted": "2026-11-20",
                "outcome": "correct",
                "direction": None,
                "days_off": None,
                "flagged": True,
                "confidence": "low",
            },
        },
    ]
    assert "never copied" not in json.dumps(changed)  # no title, no quote: ids, dates and outcomes only
    assert changed_items(ON, ON) == []


def test_a_replay_of_other_letters_cannot_be_compared() -> None:
    with pytest.raises(ValueError, match="x-b"):
        changed_items(ON, _results(*OFF["entries"][:1], *OFF["entries"][2:]))


def test_the_differences_name_each_split_and_ablation_and_ignore_the_meta() -> None:
    published = {
        "schema": SCHEMA,
        "meta": {"date": "2026-10-29", "commit": "abc"},
        "splits": {
            "test": {"ablations": {"all_on": {"right": 1}, "no_reask": {"right": 1}}},
            "dev": {"ablations": {"all_on": {"right": 2}}},
        },
        "totals": {"all": {"right": 3}},
    }
    replayed = json.loads(json.dumps(published))
    replayed["meta"]["commit"] = "def"
    assert differences(published, replayed) == []
    replayed["splits"]["test"]["ablations"]["no_reask"]["right"] = 0
    replayed["splits"]["holdout"] = {"ablations": {}}
    replayed["totals"]["all"]["right"] = 2
    assert differences(published, replayed) == ["holdout", "test/no_reask", "totals"]


def test_main_writes_the_results_file_to_the_folder_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_build(splits: list[str], model: str, run_date: str) -> dict[str, Any]:
        return {"schema": SCHEMA, "meta": {"date": run_date, "model": model}, "splits": {}, "totals": {}}

    monkeypatch.setattr(eval_ablate_checks, "build", fake_build)
    assert eval_ablate_checks.main(["--date", "2026-01-02", "--splits", "dev", "--out", str(tmp_path)]) == 0
    written = json.loads((tmp_path / f"2026-01-02-{DEFAULT_MODEL}-checks-ablated.json").read_text())
    assert written["meta"] == {"date": "2026-01-02", "model": DEFAULT_MODEL}


def test_check_replays_the_published_splits_and_fails_on_a_difference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    published = {
        "schema": SCHEMA,
        "meta": {"date": "2026-01-02", "model": DEFAULT_MODEL},
        "splits": {"dev": {"ablations": {"all_on": {"right": 2}}}},
        "totals": {},
    }
    path = tmp_path / "published.json"
    path.write_text(json.dumps(published), encoding="utf-8")
    asked: list[tuple[list[str], str, str]] = []
    replay_gives = json.dumps(published)

    async def fake_build(splits: list[str], model: str, run_date: str) -> dict[str, Any]:
        asked.append((list(splits), model, run_date))
        return json.loads(replay_gives)

    monkeypatch.setattr(eval_ablate_checks, "build", fake_build)
    assert eval_ablate_checks.main(["--check", str(path)]) == 0
    assert asked == [(["dev"], DEFAULT_MODEL, "2026-01-02")]
    published["splits"]["dev"]["ablations"]["all_on"]["right"] = 1
    path.write_text(json.dumps(published), encoding="utf-8")
    assert eval_ablate_checks.main(["--check", str(path)]) == 1
    assert "dev/all_on: the replay doesn't give the published numbers" in capsys.readouterr().err


# --------------------------------------------------------------------------------------------------
# The published file
# --------------------------------------------------------------------------------------------------


def test_the_published_file_is_a_replay_of_every_split_under_every_ablation() -> None:
    results = _published()
    meta = results["meta"]
    assert results["schema"] == SCHEMA
    assert meta["model"] == DEFAULT_MODEL and meta["condition"] == "ordnung" and meta["backend"] == "replay"
    assert meta["script"] == "scripts/eval_ablate_checks.py"
    # the code it ran on (evals.conditions.fingerprint now covers every source file, so any later change moves it:
    # the numbers are checked by replaying them, test_check_replays_the_published_file and make eval-reproduce)
    assert re.fullmatch(r"[0-9a-f]{16}", meta["fingerprint"])
    assert list(meta["ablations"]) == list(ABLATIONS)
    assert list(results["splits"]) == list(eval_ablate_checks.SPLITS)
    for numbers in results["splits"].values():
        assert list(numbers["ablations"]) == list(ABLATIONS)
        assert numbers["ablations"]["all_on"]["changed"] == []


def _moved(before: dict[str, int], changed: list[dict[str, Any]]) -> dict[str, int]:
    """``before``'s counts with each changed item's outcome and flag moved from its all-on reading to its
    ablated one."""
    after = dict(before)

    def keys(reading: dict[str, Any]) -> list[str]:
        found = ["right"] if reading["outcome"] == "correct" else []
        found += [reading["direction"]] if reading["outcome"] == "wrong" else []
        found += [reading["outcome"]] if reading["outcome"] in ("missed", "declined") else []
        found += ["flagged"] if reading["flagged"] else []
        found += ["flagged_wrong"] if reading["flagged"] and reading["outcome"] != "correct" else []
        return found

    for item in changed:
        for key in keys(item["all_on"]):
            after[key] -= 1
        for key in keys(item["ablated"]):
            after[key] += 1
    return after


def test_each_ablation_changes_exactly_the_items_its_results_file_lists() -> None:
    """Every count of an ablation is the shipped code's, moved by the items the file lists as changed (and
    an unchanged item is never listed)."""
    for split, numbers in _published()["splits"].items():
        on = numbers["ablations"]["all_on"]
        for name, ablation in numbers["ablations"].items():
            assert ablation["counts"] == _moved(on["counts"], ablation["changed"]), (split, name)
            for item in ablation["changed"]:
                assert item["all_on"] != item["ablated"], (split, name, item["entry_id"])


def test_no_switched_off_check_acts_in_its_ablation() -> None:
    """The proof that a switch took: with a check off, no letter shows that check's work."""
    off = {
        "no_two_dates_check": ("two_dates", "notice_guard"),
        "no_notice_guard": ("notice_guard",),
        "no_reask": ("reask",),
        "no_reading_check": ("reading_check", "deadline_check", "notice_guard"),
        "no_reask_no_reading_check": ("reask", "reading_check", "deadline_check", "notice_guard"),
        "all_off": ("two_dates", "notice_guard", "reask", "reading_check", "deadline_check"),
    }
    for split, numbers in _published()["splits"].items():
        for name, checks in off.items():
            acted = numbers["ablations"][name]["acted"]
            assert all(acted[check] == 0 for check in checks), (split, name, acted)


def test_the_totals_add_up_the_splits() -> None:
    results = _published()
    splits = results["splits"]
    for pool in results["totals"].values():
        for name in ABLATIONS:
            summed = {
                key: sum(splits[split]["ablations"][name]["counts"][key] for split in pool["splits"])
                for key in pool["ablations"][name]["counts"]
            }
            assert pool["ablations"][name]["counts"] == summed
            assert pool["ablations"][name]["changed"] == sum(
                len(splits[split]["ablations"][name]["changed"]) for split in pool["splits"]
            )
    assert results["totals"]["all"]["splits"] == list(splits)
    assert results["totals"]["held_out"]["splits"] == ["holdout", "holdout2", "holdout3"]


def test_the_shipped_code_is_the_replay_without_land_publishes_with_the_land() -> None:
    """The all-on replay of each split is the benchmark's replay of the code as it ships: the same numbers the
    without-Land file publishes "with the Land" (both are replays CI compares with their files)."""
    (without_land,) = sorted(RESULTS_DIR.glob("*-without-land.json"))[-1:]
    published = json.loads(without_land.read_text(encoding="utf-8"))["splits"]
    for split, numbers in _published()["splits"].items():
        headline = numbers["ablations"]["all_on"]["headline"]
        assert {key: headline[key] for key in published[split]["with_land"]} == published[split]["with_land"]


def test_the_file_holds_no_letter_text() -> None:
    """Ids, families, dates, outcomes and counts only: no field the scorer copies from a letter or reading."""
    text = PUBLISHED.read_text(encoding="utf-8")
    for field in ('"title"', '"quote"', '"explanation"', '"notes"', '"warnings"', '"sender_name"'):
        assert field not in text


@pytest.mark.slow
def test_a_replay_of_each_ablation_gives_the_published_split() -> None:
    """The holdout2 split replayed under every ablation (zero tokens) gives what the file publishes for it;
    ``python -m scripts.eval_ablate_checks --check`` does the same for every split."""
    published = _published()
    replayed = asyncio.run(eval_ablate_checks.build(["holdout2"], DEFAULT_MODEL, published["meta"]["date"]))
    assert replayed["splits"]["holdout2"] == published["splits"]["holdout2"]
