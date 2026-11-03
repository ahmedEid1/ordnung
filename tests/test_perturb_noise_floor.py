"""The stress cells' noise floor (``scripts/eval_perturb.py --noise-floor-from-runs``): per condition, how many of
holdout4's scored items do not get the same answer in every read, computed directly from the complete holdout4
results files — the same count as the final analysis's ``unstable`` (``evals/analysis.py``), with no mid-recording
analysis and no check of the reads' frozen inputs. With fewer than two reads there is no noise floor, and the
results file says so.

The results files here are made up (ids, outcomes and dates only): no letter text, no recording, no model.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals import analysis, stats  # noqa: E402
from scripts import eval_perturb  # noqa: E402

MODEL = "claude-sonnet-5"
ALL_CONDITIONS = ("ordnung", "llm_only", "llm_rules_text", "llm_rules_tool")
#: (letter, items): seven scored items on five letters.
LETTERS = (("L1", 1), ("L2", 2), ("L3", 1), ("L4", 1), ("L5", 2))
TRUE_DATE = "2027-03-10"


def _answer(condition: str, read: int, letter: str, index: int) -> str | None:
    """The date each condition gives, by hand: Ordnung's L3 moves in read 2 and its L5 #1 is undated in read 3; the
    agent's L2 #0 moves in reads 2 and 3 alike; the model alone's L4 moves in read 1."""
    if condition == "ordnung" and letter == "L3" and read == 2:
        return "2027-03-12"
    if condition == "ordnung" and letter == "L5" and index == 1 and read == 3:
        return None
    if condition == "llm_rules_tool" and letter == "L2" and index == 0 and read >= 2:
        return "2027-03-08"
    if condition == "llm_only" and letter == "L4" and read == 1:
        return "2027-03-17"
    return TRUE_DATE


def _item(index: int, predicted: str | None) -> dict[str, Any]:
    if predicted is None:
        outcome, direction = "missed", None
    elif predicted == TRUE_DATE:
        outcome, direction = "correct", None
    else:
        outcome, direction = "wrong", "late" if predicted > TRUE_DATE else "early"
    return {
        "index": index,
        "outcome": outcome,
        "direction": direction,
        "days_off": None,
        "predicted": predicted,
        "pred_index": None if predicted is None else index,
        "flagged": False,
        "confidence": None if predicted is None else "high",
        "cause": None,
    }


def results(
    read: int,
    *,
    split: str = "holdout4",
    model: str = MODEL,
    conditions: tuple[str, ...] = ALL_CONDITIONS,
    letters: tuple[tuple[str, int], ...] = LETTERS,
    answer: Callable[[str, int, str, int], str | None] = _answer,
    **meta: Any,
) -> dict[str, Any]:
    """A benchmark results document of one read, as ``evals.run`` writes it (the parts the analysis reads)."""
    entries = []
    for letter, count in letters:
        entries.append(
            {
                "id": f"{split}-{letter}",
                "family": "f",
                "modality": "text",
                "conditions": {
                    condition: {
                        "prediction": {"items": [], "document_date": None, "sender_kind": None},
                        "score": {
                            "cluster": letter,
                            "items": [_item(i, answer(condition, read, letter, i)) for i in range(count)],
                            "false_positives": 0,
                            "cost_usd": 0.01,
                            "latency_ms": 1000,
                            "calls": 1,
                            "kind_ok": True,
                            "tool_calls": None,
                        },
                    }
                    for condition in conditions
                },
            }
        )
    return {
        "schema": 1,
        "meta": {
            "date": f"2026-12-0{read}",
            "model": model,
            "split": split,
            "repeat": read,
            "backend": "live",
            "commit": "abc1234",
            "conditions": list(conditions),
            "partial": False,
            **meta,
        },
        "entries": entries,
    }


def write(folder: Path, read: int, doc: dict[str, Any] | None = None, *, name: str | None = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    suffix = "" if read == 1 else f"-r{read}"
    path = folder / (name or f"2026-12-0{read}-{MODEL}-holdout4{suffix}.json")
    path.write_text(json.dumps(doc if doc is not None else results(read)), encoding="utf-8")
    return path


def test_the_noise_floor_is_holdout4s_unstable_items_per_condition(tmp_path: Path) -> None:
    """Three reads: Ordnung's L3 and L5 #1 differ between reads (2 of 7), the agent's L2 #0 (1 of 7): an item counts
    once however many reads differ, and an undated answer is an answer of its own."""
    paths = [write(tmp_path, read) for read in (1, 2, 3)]
    floor, source = eval_perturb.noise_floor_from_runs(paths, model=MODEL)
    assert floor == {"ordnung": (2, 7), "llm_rules_tool": (1, 7)}
    assert source["split"] == "holdout4" and source["reads"] == [1, 2, 3]
    assert [row["file"] for row in source["files"]] == [path.name for path in paths]
    assert [row["sha256"] for row in source["files"]] == [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    ]
    assert "note" not in source
    # given in any order, the reads are taken in read order
    assert eval_perturb.noise_floor_from_runs(paths[::-1], model=MODEL) == (floor, source)


def test_the_noise_floor_equals_the_final_analysiss_unstable_count(tmp_path: Path) -> None:
    """The publish step compares the stress file's noise floor with the final analysis's: they are one count."""
    paths = [write(tmp_path, read) for read in (1, 2, 3)]
    runs = [analysis.read_run(path) for path in paths]
    floor, _ = eval_perturb.noise_floor_from_runs(paths, model=MODEL)
    for condition, (k, n) in (floor or {}).items():
        table: dict[tuple[str, str, int], list[analysis.Item]] = {}
        for run in runs:
            for item in run.items[condition]:
                table.setdefault(item.key, []).append(item)
        unstable = stats.flip_rate([[i.predicted for i in items] for items in table.values()])
        assert (k, n) == unstable, condition


def test_two_reads_give_a_noise_floor_and_one_read_says_there_is_none(tmp_path: Path) -> None:
    floor, source = eval_perturb.noise_floor_from_runs([write(tmp_path, 1), write(tmp_path, 2)], model=MODEL)
    assert floor == {"ordnung": (1, 7), "llm_rules_tool": (1, 7)} and source["reads"] == [1, 2]
    floor, source = eval_perturb.noise_floor_from_runs([write(tmp_path, 1)], model=MODEL)
    assert floor is None
    assert source["reads"] == [1] and len(source["files"]) == 1
    assert "no noise floor" in source["note"] and "two" in source["note"]


def test_the_reads_frozen_inputs_are_not_checked(tmp_path: Path) -> None:
    """No mid-recording check of fingerprints, commit, code or a dirty tree: the noise floor is a count over the
    files as they are (the analysis checks them after recording)."""
    docs = [
        results(read, commit=f"c{read}", dirty=["evals/x.py"], fingerprints={"ordnung": f"f{read}"})
        for read in (1, 2, 3)
    ]
    paths = [write(tmp_path, read, doc) for read, doc in zip((1, 2, 3), docs, strict=True)]
    floor, _ = eval_perturb.noise_floor_from_runs(paths, model=MODEL)
    assert floor == {"ordnung": (2, 7), "llm_rules_tool": (1, 7)}


@pytest.mark.parametrize(
    ("docs", "said"),
    [
        ([results(1), results(2, split="holdout3")], "holdout3"),
        ([results(1), results(2, model="another-model")], "another-model"),
        ([results(1), results(2, partial=True)], "complete"),
        ([results(1), results(1)], "read 1"),
        ([results(1), results(2, conditions=("ordnung", "llm_only"))], "llm_rules_tool"),
        ([results(1), results(2, letters=LETTERS[:-1])], "same items"),
        ([results(1), results(2), results(3), results(4)], "read 4"),
    ],
)
def test_reads_that_do_not_fit_are_refused(tmp_path: Path, docs: list[dict[str, Any]], said: str) -> None:
    paths = [write(tmp_path, n + 1, doc, name=f"read-{n}.json") for n, doc in enumerate(docs)]
    with pytest.raises(eval_perturb.StressError) as refused:
        eval_perturb.noise_floor_from_runs(paths, model=MODEL)
    assert said in str(refused.value)


def test_a_missing_read_is_refused_before_any_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A noise floor that cannot be computed stops the run before the letters are built, replayed or recorded."""

    def no_work(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("work started before the noise floor was read")

    monkeypatch.setattr(eval_perturb.build, "build", no_work)
    monkeypatch.setattr(eval_perturb, "clean_reference", no_work)
    code = eval_perturb.main(
        ["--out", str(tmp_path / "out"), "--quiet", "--noise-floor-from-runs", str(tmp_path / "absent.json")]
    )
    assert code == 1
    assert "absent.json" in capsys.readouterr().err
    with pytest.raises(SystemExit):  # one noise floor or the other, never both
        eval_perturb.main(
            ["--out", "x", "--noise-floor", "a.json", "--noise-floor-from-runs", str(tmp_path / "r1.json")]
        )


# --------------------------------------------------------------------------------------------------
# the results file: the noise floor beside the cells, its reads named, and a --check that finds them again
# --------------------------------------------------------------------------------------------------


@pytest.fixture()
def clean_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """holdout4's stand-in (tests/test_perturb_build.py) and a clean reference made up from the truth (no replay)."""
    from evals.records import PredictedItem, Prediction

    from test_perturb_build import final_manifest

    monkeypatch.setattr(
        eval_perturb.build, "DATASET_MANIFEST", final_manifest(tmp_path / "final" / "manifest.json")
    )

    async def clean(base: Any, *, model: str, work: Path, quiet: bool = True, **_: Any) -> Any:
        def answer(entry: Any, condition: str) -> Prediction:
            items = [
                PredictedItem(kind=item.kind, title=item.title, due_date=item.expected_due, confidence="high")
                for item in entry.truth.items
                if item.scored
            ]
            return Prediction(entry_id=entry.id, condition=condition, model=model, items=items)

        found = {c: {entry.id: answer(entry, c) for entry in base} for c in eval_perturb.CONDITIONS}
        return found, {"backend": "replay", "repeat": 1}

    monkeypatch.setattr(eval_perturb, "clean_reference", clean)
    return tmp_path


def _published(folder: Path) -> Path:
    return folder / f"2026-12-08-{MODEL}-stress.json"


def test_the_results_file_holds_the_noise_floor_and_names_its_reads(
    clean_only: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The value goes into the results file and to stdout only (the recording's log keeps stdout sealed)."""
    out = clean_only / "pending"
    paths = [write(out, read) for read in (1, 2, 3)]
    argv = ["--clean-only", "--out", str(out), "--quiet", "--date", "2026-12-08", "--noise-floor-from-runs"]
    assert eval_perturb.main([*argv, *map(str, paths)]) == 0
    said = capsys.readouterr()
    assert "noise floor" in said.out and "2/7" in said.out and "1/7" in said.out
    assert "noise floor" not in said.err
    doc = json.loads(_published(out).read_text(encoding="utf-8"))
    assert {c: (v["k"], v["n"]) for c, v in doc["noise_floor"].items()} == {
        "ordnung": (2, 7),
        "llm_rules_tool": (1, 7),
    }
    source = doc["meta"]["noise_floor_source"]
    assert source["reads"] == [1, 2, 3] and [f["file"] for f in source["files"]] == [p.name for p in paths]


def test_one_read_gives_a_results_file_that_says_there_is_no_noise_floor(
    clean_only: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = clean_only / "pending"
    read = write(out, 1)
    argv = ["--clean-only", "--out", str(out), "--quiet", "--date", "2026-12-08"]
    assert eval_perturb.main([*argv, "--noise-floor-from-runs", str(read)]) == 0
    doc = json.loads(_published(out).read_text(encoding="utf-8"))
    assert doc["noise_floor"] is None
    assert "no noise floor" in doc["meta"]["noise_floor_source"]["note"]
    assert "no noise floor" in capsys.readouterr().out


def test_a_check_finds_the_noise_floors_reads_beside_the_published_file(
    clean_only: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--check`` without a noise-floor option (as ``make eval-reproduce`` runs it) reads the holdout4 files the
    published file names, beside it, and refuses one that is missing or changed."""
    published_dir = clean_only / "results"
    paths = [write(published_dir, read) for read in (1, 2, 3)]
    argv = ["--clean-only", "--quiet", "--date", "2026-12-08"]
    assert (
        eval_perturb.main([*argv, "--out", str(published_dir), "--noise-floor-from-runs", *map(str, paths)])
        == 0
    )
    check = ["--check", str(_published(published_dir))]
    assert eval_perturb.main([*argv, "--out", str(clean_only / "replay"), *check]) == 0
    capsys.readouterr()
    changed = results(2, answer=lambda c, r, letter, i: "2027-03-12" if c == "llm_rules_tool" else TRUE_DATE)
    write(published_dir, 2, changed)
    assert eval_perturb.main([*argv, "--out", str(clean_only / "replay2"), *check]) == 1
    assert paths[1].name in capsys.readouterr().err
    write(published_dir, 2)
    paths[2].unlink()
    assert eval_perturb.main([*argv, "--out", str(clean_only / "replay3"), *check]) == 1
    assert paths[2].name in capsys.readouterr().err
