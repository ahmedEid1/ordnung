"""evals/export.py and evals/results/items.csv: every scored item of every published run as ids, dates, outcomes,
cost and latency, with no free text (plan EV4; the per-item table an analyst reads instead of 1.4 MB JSON files)."""

from __future__ import annotations

import copy
import csv
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest
from evals import export
from evals.run import DEFAULT_MODEL, RESULTS_DIR

ITEMS_CSV = RESULTS_DIR / "items.csv"
HELD_OUT_LIVE = (
    "2026-09-30-claude-sonnet-5-holdout.json",
    "2026-10-01-claude-sonnet-5-holdout2.json",
    "2026-10-06-claude-sonnet-5-holdout3.json",
)
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
#: Columns whose values are a closed set (anything else would be free text getting through).
ENUMS = {
    "condition": {"ordnung", "llm_only", "llm_rules_text", "llm_rules_tool"},
    "modality": {"text", "photo"},
    "required": {"true", "false", ""},
    "kind": {"deadline", "payment", "appointment", "task", ""},
    "outcome": {"correct", "wrong", "missed", "declined", "unscored", ""},
    "direction": {"late", "early", ""},
    "confidence": {"high", "medium", "low", ""},
    "flagged": {"true", "false", ""},
    "cause": {"reading", "computing", "check", ""},
}


@pytest.fixture(scope="module")
def committed() -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(ITEMS_CSV.read_text(encoding="utf-8"))))


def test_items_csv_is_what_the_results_files_give() -> None:
    """Generated, never edited: a fresh export of the committed results files is the committed file, byte for byte
    (``python -m evals.export --write`` rewrites it; ``make eval-reproduce`` checks it)."""
    assert ITEMS_CSV.read_text(encoding="utf-8") == export.render(RESULTS_DIR)
    assert export.check(RESULTS_DIR, ITEMS_CSV) == []


def test_the_columns_are_the_whitelist(committed: list[dict[str, str]]) -> None:
    header = ITEMS_CSV.read_text(encoding="utf-8").splitlines()[0]
    assert header == ",".join(export.COLUMNS)
    assert (
        "title" not in export.COLUMNS
        and "quote" not in export.COLUMNS
        and "explanation" not in export.COLUMNS
    )
    assert committed and set(committed[0]) == set(export.COLUMNS)


def test_no_cell_holds_free_text(committed: list[dict[str, str]]) -> None:
    """Ids, dates, enums and numbers only: no cell over 64 characters, none with a space, every enum column in its
    set, every date an ISO date and every number a number."""
    for row in committed:
        for column, value in row.items():
            assert len(value) <= 64 and not re.search(r"\s", value), (column, len(value))
        for column, values in ENUMS.items():
            assert row[column] in values, (column, row[column])
        for column in ("today", "expected", "predicted"):
            # an ambiguous numeric date's label is the word "ambiguous" (evals.metrics: no confident date is right)
            allowed = ("", "ambiguous") if column == "expected" else ("",)
            assert row[column] in allowed or ISO_DATE.fullmatch(row[column]), column
        for column in ("repeat", "item", "days_off", "latency_ms", "calls"):
            assert row[column] == "" or row[column].lstrip("-").isdigit(), column
        float(row["cost_usd"])
        assert row["file"].endswith(".json") and row["entry_id"].startswith(row["split"] + "-")


def test_no_title_or_quote_of_a_results_file_reaches_the_csv() -> None:
    text = ITEMS_CSV.read_text(encoding="utf-8")
    leaked = 0
    for path in export.run_files(RESULTS_DIR):
        for entry in json.loads(path.read_text(encoding="utf-8"))["entries"]:
            for item in entry["expected"]:
                leaked += len(item["title"]) > 3 and item["title"] in text
            for condition in entry["conditions"].values():
                for predicted in (condition["prediction"] or {}).get("items", []):
                    for key in ("title", "quote", "explanation"):
                        value = predicted.get(key)
                        leaked += bool(value) and len(value) > 3 and value in text
    assert leaked == 0


def test_only_the_pinned_models_per_letter_runs_are_exported(committed: list[dict[str, str]]) -> None:
    """The archived runs of an earlier model are left out (their recordings are not in the repository), and so are
    the summaries (Ask, without the Land, the ablation, end to end, the analysis): one row per item of the rest."""
    files = export.run_files(RESULTS_DIR)
    names = {path.name for path in files}
    assert names == {row["file"] for row in committed}
    for path in RESULTS_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        is_run = isinstance(data.get("entries"), list) and bool(meta.get("split"))
        assert (path.name in names) == (is_run and meta.get("model") == DEFAULT_MODEL), path.name
    expected_rows = 0
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data["entries"]:
            for condition in data["meta"]["conditions"]:
                score = entry["conditions"][condition]["score"]
                expected_rows += max(1, len(score["items"]))
    assert len(committed) == expected_rows


def test_the_held_out_recordings_give_the_published_counts(committed: list[dict[str, str]]) -> None:
    """Known values: the three held-out splits as recorded, Ordnung 163 of 168 dates right (2 late, 1 missed), the
    model alone 136 of 168 (13 late): what the re-analysis and the README say."""
    for condition, right, late, missed in (("ordnung", 163, 2, 1), ("llm_only", 136, 13, 0)):
        rows = [
            row
            for row in committed
            if row["file"] in HELD_OUT_LIVE
            and row["condition"] == condition
            and row["required"] == "true"
            and row["outcome"] not in ("unscored", "")
        ]
        assert len(rows) == 168
        assert sum(row["outcome"] == "correct" for row in rows) == right
        assert sum(row["direction"] == "late" for row in rows) == late
        assert sum(row["outcome"] == "missed" for row in rows) == missed


def _results(entries: list[dict[str, Any]], *, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    return {
        "schema": 2,
        "meta": {"model": model, "split": "dev", "repeat": 2, "conditions": ["ordnung"]},
        "metrics": {},
        "entries": entries,
    }


def _entry(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "dev-invoice_relative-A1",
        "family": "invoice_relative",
        "variant": "A1",
        "modality": "text",
        "today": "2026-03-02",
        "region": "NW",
        "expected": [],
        "conditions": {
            "ordnung": {
                "prediction": {"items": []},
                "score": {"items": items, "cost_usd": 0.0412, "latency_ms": 31573, "calls": 1},
            }
        },
    }


ITEM = {
    "index": 0,
    "required": True,
    "kind": "payment",
    "title": "Pay the invoice",
    "expected": "2026-03-16",
    "predicted": "2026-03-17",
    "outcome": "wrong",
    "direction": "late",
    "days_off": 1,
    "confidence": "high",
    "flagged": False,
    "cause": "reading",
}


def test_a_row_holds_the_items_ids_dates_and_outcome_and_the_letters_cost(tmp_path: Path) -> None:
    (tmp_path / "2026-03-02-claude-sonnet-5-dev-r2.json").write_text(
        json.dumps(_results([_entry([ITEM])])), encoding="utf-8"
    )
    (row,) = csv.DictReader(io.StringIO(export.render(tmp_path)))
    assert row == {
        "file": "2026-03-02-claude-sonnet-5-dev-r2.json",
        "split": "dev",
        "repeat": "2",
        "condition": "ordnung",
        "entry_id": "dev-invoice_relative-A1",
        "family": "invoice_relative",
        "variant": "A1",
        "modality": "text",
        "region": "NW",
        "today": "2026-03-02",
        "item": "0",
        "required": "true",
        "kind": "payment",
        "expected": "2026-03-16",
        "predicted": "2026-03-17",
        "outcome": "wrong",
        "direction": "late",
        "days_off": "1",
        "confidence": "high",
        "flagged": "false",
        "cause": "reading",
        "cost_usd": "0.0412",
        "latency_ms": "31573",
        "calls": "1",
    }
    assert "Pay the invoice" not in export.render(tmp_path)


def test_a_letter_without_items_keeps_one_row_with_its_cost(tmp_path: Path) -> None:
    (tmp_path / "2026-03-02-claude-sonnet-5-dev.json").write_text(
        json.dumps(_results([_entry([])])), encoding="utf-8"
    )
    (row,) = csv.DictReader(io.StringIO(export.render(tmp_path)))
    assert row["item"] == row["outcome"] == row["expected"] == "" and row["cost_usd"] == "0.0412"
    assert row["repeat"] == "2"


def test_free_text_in_an_id_column_stops_the_export(tmp_path: Path) -> None:
    """The whitelist is enforced when writing, not only by this test: a value with a space never reaches the file."""
    entry = _entry([ITEM])
    entry["family"] = "a family with words"
    (tmp_path / "2026-03-02-claude-sonnet-5-dev.json").write_text(
        json.dumps(_results([entry])), encoding="utf-8"
    )
    with pytest.raises(export.ExportError, match="family"):
        export.render(tmp_path)


def test_another_models_run_and_the_summaries_are_left_out(tmp_path: Path) -> None:
    (tmp_path / "2026-03-02-other-dev.json").write_text(
        json.dumps(_results([_entry([ITEM])], model="other")), encoding="utf-8"
    )
    (tmp_path / "2026-03-02-claude-sonnet-5-ask.json").write_text(
        json.dumps({"benchmark": "ask", "model": DEFAULT_MODEL}), encoding="utf-8"
    )
    assert export.run_files(tmp_path) == []
    assert export.render(tmp_path) == ",".join(export.COLUMNS) + "\n"


def test_check_names_a_stale_file_and_write_fixes_it(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    (results / "2026-03-02-claude-sonnet-5-dev.json").write_text(
        json.dumps(_results([_entry([ITEM])])), encoding="utf-8"
    )
    out = results / "items.csv"
    assert export.check(results, out) == ["items.csv is missing: run python -m evals.export --write"]
    assert export.main(["--write", "--results-dir", str(results), "--out", str(out)]) == 0
    assert (
        export.check(results, out) == []
        and export.main(["--check", "--results-dir", str(results), "--out", str(out)]) == 0
    )
    changed = copy.deepcopy(_results([_entry([{**ITEM, "outcome": "correct", "direction": None}])]))
    (results / "2026-03-02-claude-sonnet-5-dev.json").write_text(json.dumps(changed), encoding="utf-8")
    assert export.check(results, out) == [
        "items.csv is not what the results files give: run python -m evals.export --write"
    ]
    assert export.main(["--check", "--results-dir", str(results), "--out", str(out)]) == 1
