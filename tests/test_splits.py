"""The split registry's state comes from the data (``evals/splits.py``): a split's letters exist when the manifest has
entries of it, and it is recorded once a live results file of it is in ``evals/results/`` (not in a folder below it,
as ``pending/``). No constant in the code says either, so adding a split's letters or its recording never edits a
top-level ``evals/*.py`` file (each is in every condition's fingerprint)."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import splits  # noqa: E402

MODEL = "claude-sonnet-5"


def _results(folder: Path, name: str, **meta: Any) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    data = {"schema": 1, "meta": {"model": MODEL, "backend": "live", "partial": False, "repeat": 1, **meta}}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_no_constant_says_whether_a_split_is_recorded() -> None:
    assert "recorded" not in {field.name for field in dataclasses.fields(splits.Split)}
    assert splits.names() == ("dev", "test", "holdout", "holdout2", "holdout3", "holdout4", "newkinds")


def test_the_checked_out_results_record_the_five_earlier_splits() -> None:
    assert splits.recorded() == ("dev", "test", "holdout", "holdout2", "holdout3")


def test_a_split_is_recorded_once_a_live_results_file_of_it_is_published(tmp_path: Path) -> None:
    results = tmp_path / "results"
    results.mkdir()
    assert splits.recorded(results) == ()
    # a file in pending/ is not published, so it records nothing
    _results(results / "pending", f"2026-12-08-{MODEL}-holdout4.json", split="holdout4")
    # a replay, a partial recording and a re-scoring record nothing
    _results(results, f"2026-12-08-{MODEL}-newkinds.json", split="newkinds", backend="replay")
    _results(results, f"2026-12-08-{MODEL}-newkinds-partial.json", split="newkinds", partial=True)
    _results(results, f"2026-12-08-{MODEL}-holdout3-rescored.json", split="holdout3", backend="replay")
    assert splits.recorded(results) == ()
    assert not splits.is_recorded("holdout4", results)
    _results(results, f"2026-12-08-{MODEL}-holdout4-r2.json", split="holdout4", repeat=2)
    _results(results, f"2026-12-08-{MODEL}-holdout4.json", split="holdout4")
    assert splits.recorded(results) == ("holdout4",)
    assert splits.is_recorded("holdout4", results) and not splits.is_recorded("newkinds", results)
    # a file named for one split but holding another is read by what it holds
    _results(results, f"2026-12-09-{MODEL}-newkinds.json", split="dev")
    assert splits.recorded(results) == ("dev", "holdout4")


def test_letters_exist_when_the_manifest_has_entries_of_the_split(tmp_path: Path) -> None:
    assert splits.has_letters("holdout3") and splits.has_letters("dev")
    assert not splits.has_letters("holdout4") and not splits.has_letters("newkinds")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"entries": [{"id": "holdout4-x-K1", "split": "holdout4"}]}), encoding="utf-8"
    )
    assert splits.has_letters("holdout4", manifest) and not splits.has_letters("dev", manifest)


def test_the_final_splits_are_named_by_their_role() -> None:
    assert [name for name in splits.names() if splits.is_final(name)] == ["holdout4", "newkinds"]
    assert not splits.is_final("holdout3") and not splits.is_final("stress-I1")
