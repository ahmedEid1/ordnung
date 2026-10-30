"""Switch off Ordnung's code checks one at a time on the recorded readings, and publish what each one prevents.

Ordnung reads a letter with Claude, then code checks the reading before the rules engine computes a date
(defence in depth). This script replays the recorded Ordnung outputs of each split once as the benchmark runs
them (the code as it ships) and once per ablation, with one function swapped for the length of the replay:

* ``no_two_dates_check``: :func:`ordnung.ingest.plan.settle` gives nothing, so a to-do the letter gives a second
  date for keeps the reading's own (no "Please check"); this switches off the letter's-own-notice guard too,
  which settles through it;
* ``no_notice_guard``: :func:`ordnung.ingest.plan._notice_beside` gives nothing, so the letter's own remedy
  notice is never set beside a later objection date the reading gives;
* ``no_reask``: :func:`ordnung.ingest.extract.reading_gap_of` finds no gap, so an incomplete reading is never
  asked again (ADR 0016);
* ``no_reading_check``: the benchmark's ``verify_extraction`` runs with ``check_reading=False``: no to-do is filed
  for an incomplete reading or for a fixed date the reading left out, and no notice is set beside (ADR 0015);
* ``no_reask_no_reading_check``: both of the last two;
* ``all_off``: the two-dates check, the re-ask and the reading check.

It writes, per split and ablation, the right, early, late, missed and declined dates and the "Please check" flags
of the scored items, on how many letters each check acted, and every scored item whose date, outcome, flag or
confidence differs from the code as it ships, to ``evals/results/<date>-<model>-checks-ablated.json`` (``--out``:
another folder). ``--check FILE`` replays the splits FILE publishes and exits 1, naming each split and ablation,
when the replay doesn't give its numbers. It is a replay only: no model is called, and a missing recording is an
error. ``evals/conditions.py`` is not changed (it is part of the benchmark's fingerprint), and the per-letter
cache goes to a temporary folder. Only ids, families, dates, outcomes and counts are written: never a letter's
text, a reading or a quote.

Run it from the repository root::

    .venv/bin/python -m scripts.eval_ablate_checks [--date YYYY-MM-DD] [--splits test holdout …] [--out FOLDER]
    .venv/bin/python -m scripts.eval_ablate_checks --check evals/results/<date>-<model>-checks-ablated.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from evals import conditions, report
from evals import run as run_mod
from evals.conditions import PreparedDocument
from evals.records import Entry
from evals.run import DEFAULT_MODEL, RESULTS_DIR, RunConfig, _commit, run_benchmark

from ordnung.ingest import extract as extract_mod
from ordnung.ingest import plan as plan_mod
from ordnung.ingest.conflicts import CONFLICTING_DATES

SCHEMA = "ordnung-eval-checks-ablated/1"
SPLITS = ("test", "holdout", "holdout2", "holdout3", "dev")
#: The splits pooled as "held_out" in the totals.
HELD_OUT = ("holdout", "holdout2", "holdout3")
#: The headline metrics of each replay (as the benchmark computes them, with their intervals).
HEADLINE = ("due_date_accuracy", "dangerous_late_rate", "early_rate", "missed_rate")
#: What the file says of a changed item, in the code as it ships and in the ablation.
READING_FIELDS = ("predicted", "outcome", "direction", "days_off", "flagged", "confidence")
NOTE = (
    "The Ordnung condition's recorded outputs replayed with the checked-out code, once as it ships (all_on) and "
    "once per ablation, each switching one function off for the length of the replay (scripts/"
    "eval_ablate_checks.py). Counts are of the scored items (a required to-do with a due date); 'flagged' is a "
    "date the person is told to check (low confidence or 'Please check'). 'changed' lists every scored item whose "
    "date, outcome, flag or confidence differs from all_on. Not every split is out of sample for every check: "
    "the two-dates check was written after two holdout letters were read late, so on holdout it acts on the "
    "letters that motivated it, while holdout2 and holdout3 were written after it; the reading check and the "
    "re-ask were written after a holdout2 letter's empty reading (ADR 0015, 0016), so only holdout3 was written "
    "after them; the test and dev splits were seen while the checks were made. No model was called."
)


@contextlib.contextmanager
def _swapped(owner: Any, name: str, value: Any) -> Iterator[None]:
    original = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, original)


def _settle_nothing(*_args: Any, **_kwargs: Any) -> None:
    return None


def _no_notice(*_args: Any, **_kwargs: Any) -> tuple[()]:
    return ()


def _no_gap(*_args: Any, **_kwargs: Any) -> None:
    return None


def two_dates_check_off() -> contextlib.AbstractContextManager[None]:
    """Within the block, a to-do the letter gives a second date for keeps the reading's own (``plan.settle``)."""
    return _swapped(plan_mod, "settle", _settle_nothing)


def notice_guard_off() -> contextlib.AbstractContextManager[None]:
    """Within the block, the letter's own notice is never set beside a later objection date."""
    return _swapped(plan_mod, "_notice_beside", _no_notice)


def reask_off() -> contextlib.AbstractContextManager[None]:
    """Within the block, no reading is found incomplete before verify, so none is asked again."""
    return _swapped(extract_mod, "reading_gap_of", _no_gap)


@contextlib.contextmanager
def reading_check_off() -> Iterator[None]:
    """Within the block, the benchmark's Ordnung condition verifies a reading without the reading check."""
    original = conditions.verify_extraction

    def unchecked(*args: Any, **kwargs: Any) -> Any:
        return original(*args, **{**kwargs, "check_reading": False})

    with _swapped(conditions, "verify_extraction", unchecked):
        yield


@dataclass(frozen=True)
class Ablation:
    """One configuration of Ordnung's code checks: its name, its plain words, and what it switches off."""

    name: str
    label: str
    switches_off: tuple[str, ...]
    patches: tuple[Callable[[], contextlib.AbstractContextManager[None]], ...] = ()


TWO_DATES = "ordnung.ingest.plan.settle (the two-dates check and the letter's-own-notice guard)"
NOTICE = "ordnung.ingest.plan._notice_beside (the letter's-own-notice guard)"
REASK = "ordnung.ingest.extract.reading_gap_of (the completeness re-ask)"
CHECK = (
    "verify_extraction(check_reading=False) (the reading check, the dropped-date check and the notice beside)"
)

ABLATIONS: dict[str, Ablation] = {
    ablation.name: ablation
    for ablation in (
        Ablation("all_on", "As it ships", ()),
        Ablation("no_two_dates_check", "Two-dates check off", (TWO_DATES,), (two_dates_check_off,)),
        Ablation("no_notice_guard", "Notice guard off", (NOTICE,), (notice_guard_off,)),
        Ablation("no_reask", "Re-ask off", (REASK,), (reask_off,)),
        Ablation("no_reading_check", "Reading check off", (CHECK,), (reading_check_off,)),
        Ablation(
            "no_reask_no_reading_check",
            "Re-ask and reading check off",
            (REASK, CHECK),
            (reask_off, reading_check_off),
        ),
        Ablation(
            "all_off",
            "All code checks off",
            (TWO_DATES, REASK, CHECK),
            (two_dates_check_off, reask_off, reading_check_off),
        ),
    )
}


@contextlib.contextmanager
def ablated(name: str) -> Iterator[None]:
    """Within the block, the checks the ablation ``name`` switches off are off (``KeyError``: no such one)."""
    ablation = ABLATIONS[name]
    with contextlib.ExitStack() as stack:
        for patch in ablation.patches:
            stack.enter_context(patch())
        yield


async def replay(split: str, model: str, work: Path) -> dict[str, Any]:
    """The results document of one replay of the Ordnung condition on ``split`` (nothing is written)."""
    config = RunConfig(
        split=split,
        models=[model],
        conditions=["ordnung"],
        resume=False,  # the cache knows nothing of the checks switched off
        write_results=False,
        write_docs=False,
        results_dir=work,
    )
    outcome = await run_benchmark(config)
    (run,) = outcome.runs
    if run.results is None:
        problems = "; ".join(f"{p.entry_id}: {p.error}" for p in run.errors[:5]) or run.fatal or "no results"
        raise RuntimeError(f"the {split} replay failed: {problems}")
    return run.results


def _ordnung(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    result: Mapping[str, Any] = entry["conditions"]["ordnung"]
    return result


def _scored(entry: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in _ordnung(entry)["score"]["items"] if item["outcome"] != "unscored"]


def counts(results: Mapping[str, Any]) -> dict[str, int]:
    """Ordnung's scored items: right, early, late, missed (no to-do), declined (a to-do without a date), and the
    flagged ones (low confidence or "Please check"), all of them and the wrong ones."""
    found = dict.fromkeys(
        ("scored", "right", "early", "late", "missed", "declined", "flagged", "flagged_wrong"), 0
    )
    for entry in results["entries"]:
        for item in _scored(entry):
            outcome = item["outcome"]
            found["scored"] += 1
            if outcome == "correct":
                found["right"] += 1
            elif outcome == "wrong":
                found[item["direction"]] += 1
            else:
                found[outcome] += 1
            found["flagged"] += bool(item["flagged"])
            found["flagged_wrong"] += bool(item["flagged"]) and outcome != "correct"
    return found


def letters_acted(results: Mapping[str, Any]) -> dict[str, int]:
    """On how many letters each check acted: a to-do settled between two dates (rule ``conflicting_dates``), the
    letter's own notice kept (``objection_after_notice``), the re-ask answered, a to-do filed for an incomplete
    reading (``reading_incomplete``) or for a fixed date the reading left out (``deadline_left_out``)."""
    acted = dict.fromkeys(("two_dates", "notice_guard", "reask", "reading_check", "deadline_check"), 0)
    for entry in results["entries"]:
        prediction = _ordnung(entry)["prediction"]
        signals = set(prediction["signals"])
        acted["two_dates"] += any(CONFLICTING_DATES in item["rule_ids"] for item in prediction["items"])
        acted["notice_guard"] += "objection_after_notice" in signals
        acted["reask"] += any(signal.startswith("reading_reask:") for signal in signals)
        acted["reading_check"] += "reading_incomplete" in signals
        acted["deadline_check"] += "deadline_left_out" in signals
    return acted


def headline(results: Mapping[str, Any]) -> dict[str, Any]:
    """Ordnung's due-date accuracy and its dangerously late, early and missed rates, with their intervals."""
    metrics = results["metrics"]["ordnung"]
    return {name: metrics[name] for name in HEADLINE}


def _reading(item: Mapping[str, Any]) -> dict[str, Any]:
    return {name: item[name] for name in READING_FIELDS}


def changed_items(all_on: Mapping[str, Any], ablated_run: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every scored item whose date, outcome, flag or confidence differs between the code as it ships
    (``all_on``) and an ablation's replay, with the letter's id and family and both readings."""
    shipped = {entry["id"]: entry for entry in all_on["entries"]}
    other = {entry["id"]: entry for entry in ablated_run["entries"]}
    if shipped.keys() != other.keys():
        raise ValueError(
            f"the replays are of other letters: {', '.join(sorted(shipped.keys() ^ other.keys()))}"
        )
    changed = []
    for entry_id, entry in shipped.items():
        for was, now in zip(_scored(entry), _scored(other[entry_id]), strict=True):
            if was["index"] != now["index"]:
                raise ValueError(f"{entry_id}: the replays score other items")
            if _reading(was) != _reading(now):
                changed.append(
                    {
                        "entry_id": entry_id,
                        "family": entry["family"],
                        "item": was["index"],
                        "expected": was["expected"],
                        "all_on": _reading(was),
                        "ablated": _reading(now),
                    }
                )
    return changed


@contextlib.contextmanager
def documents_prepared_once(work: Path) -> Iterator[None]:
    """Within the block, the benchmark prepares each letter (renders its pages and reads its text layer,
    :func:`evals.conditions.prepare_document`) once into ``work`` and every replay shares it: no check this
    script switches off runs before the text stage, and preparing is most of a replay's time."""
    original = run_mod.prepare_document
    prepared: dict[tuple[str, str], PreparedDocument] = {}

    def once(entry: Entry, dataset_dir: Path, _work_dir: Path) -> PreparedDocument:
        key = (entry.id, entry.sha256)
        if key not in prepared:
            prepared[key] = original(entry, dataset_dir, work)
        return prepared[key]

    with _swapped(run_mod, "prepare_document", once):
        yield


async def split_numbers(split: str, model: str) -> dict[str, Any]:
    """The split replayed as it ships and under every ablation, side by side."""
    runs: dict[str, dict[str, Any]] = {}
    with (
        tempfile.TemporaryDirectory(prefix="ordnung-ablate-checks-") as work,
        documents_prepared_once(Path(work) / "pages"),
    ):
        for name in ABLATIONS:
            with ablated(name):
                runs[name] = await replay(split, model, Path(work) / name)
    shipped = runs["all_on"]
    return {
        "entries": len(shipped["entries"]),
        "ablations": {
            name: {
                "headline": headline(run),
                "counts": counts(run),
                "acted": letters_acted(run),
                "changed": changed_items(shipped, run),
            }
            for name, run in runs.items()
        },
    }


def pooled(numbers: Mapping[str, Mapping[str, Any]], splits: Sequence[str]) -> dict[str, Any]:
    """The counts, the letters acted on and the number of changed items of each ablation, summed over
    ``splits``."""
    ablations: dict[str, Any] = {}
    for name in ABLATIONS:
        each = [numbers[split]["ablations"][name] for split in splits]
        ablations[name] = {
            "counts": {key: sum(one["counts"][key] for one in each) for key in each[0]["counts"]},
            "acted": {key: sum(one["acted"][key] for one in each) for key in each[0]["acted"]},
            "changed": sum(len(one["changed"]) for one in each),
        }
    return {"splits": list(splits), "ablations": ablations}


def totals(numbers: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Every split replayed pooled (``all``), and the held-out splits among them (``held_out``)."""
    found = {"all": pooled(numbers, list(numbers))}
    held_out = [split for split in numbers if split in HELD_OUT]
    if held_out:
        found["held_out"] = pooled(numbers, held_out)
    return found


async def build(splits: Sequence[str], model: str, run_date: str) -> dict[str, Any]:
    numbers: dict[str, Any] = {}
    for split in splits:
        print(f"{split}: replaying with each code check off …", file=sys.stderr, flush=True)
        numbers[split] = await split_numbers(split, model)
    return {
        "schema": SCHEMA,
        "meta": {
            "date": run_date,
            "model": model,
            "condition": "ordnung",
            "backend": "replay",
            "commit": _commit(),
            "fingerprint": conditions.fingerprint("ordnung", model),
            "script": "scripts/eval_ablate_checks.py",
            "note": NOTE,
            "ablations": {
                name: {"label": ablation.label, "switches_off": list(ablation.switches_off)}
                for name, ablation in ABLATIONS.items()
            },
        },
        "splits": numbers,
        "totals": totals(numbers),
    }


def differences(published: Mapping[str, Any], replayed: Mapping[str, Any]) -> list[str]:
    """What a replay gives differently from a published file: ``<split>`` (one side lacks it),
    ``<split>/<ablation>``, ``totals`` or ``schema`` (the meta is the run's own: date, commit)."""
    found: list[str] = []
    if published.get("schema") != replayed.get("schema"):
        found.append("schema")
    old, new = published.get("splits", {}), replayed.get("splits", {})
    for split in sorted(old.keys() | new.keys()):
        if split not in old or split not in new:
            found.append(split)
            continue
        before, after = old[split].get("ablations", {}), new[split].get("ablations", {})
        if {key: value for key, value in old[split].items() if key != "ablations"} != {
            key: value for key, value in new[split].items() if key != "ablations"
        }:
            found.append(split)
        found += [
            f"{split}/{name}"
            for name in sorted(before.keys() | after.keys())
            if before.get(name) != after.get(name)
        ]
    if published.get("totals") != replayed.get("totals"):
        found.append("totals")
    return sorted(found)


def results_path(run_date: str, model: str, folder: Path = RESULTS_DIR) -> Path:
    return folder / report.results_filename(run_date, model, "checks-ablated")


def _summary(results: Mapping[str, Any]) -> None:
    for pool, numbers in results["totals"].items():
        print(f"{pool} ({', '.join(numbers['splits'])}):", file=sys.stderr)
        for name, ablation in numbers["ablations"].items():
            found = ablation["counts"]
            print(
                f"  {name:<26} right {found['right']}/{found['scored']}  early {found['early']}  "
                f"late {found['late']}  missed {found['missed']}  declined {found['declined']}  "
                f"flagged {found['flagged']}  changed {ablation['changed']}",
                file=sys.stderr,
            )


def check(path: Path) -> int:
    """Replay the splits ``path`` publishes, with its date and model, and compare (1: a difference)."""
    published = json.loads(path.read_text(encoding="utf-8"))
    meta = published["meta"]
    replayed = asyncio.run(build(list(published["splits"]), meta["model"], meta["date"]))
    differ = differences(published, replayed)
    for name in differ:
        print(f"{name}: the replay doesn't give the published numbers", file=sys.stderr)
    return 1 if differ else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.eval_ablate_checks", description=__doc__)
    parser.add_argument("--date", dest="run_date", default=date.today().isoformat(), help="for the file name")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"the recordings' model (default: {DEFAULT_MODEL})"
    )
    parser.add_argument("--splits", nargs="+", choices=SPLITS, default=list(SPLITS), help="splits to replay")
    parser.add_argument(
        "--out",
        type=Path,
        default=RESULTS_DIR,
        metavar="FOLDER",
        help=f"folder for the results file (default: {RESULTS_DIR.parent.name}/{RESULTS_DIR.name})",
    )
    parser.add_argument(
        "--check",
        type=Path,
        metavar="FILE",
        help="replay the splits of this published file and exit 1 if the numbers differ (writes nothing)",
    )
    args = parser.parse_args(argv)
    if args.check is not None:
        return check(args.check)
    results = asyncio.run(build(args.splits, args.model, args.run_date))
    path = report.write_json(results_path(args.run_date, args.model, args.out), results)
    if results["totals"]:
        _summary(results)
    print(f"results → {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
