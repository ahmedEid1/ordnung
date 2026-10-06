"""Publish the benchmark's Ordnung numbers without the sender's Land.

The benchmark gives Ordnung's rules engine the Land the letterhead names (``Entry.authority_region``,
``evals.conditions.ordnung_rule_context``). The app knows a sender's Land only once the person sets it for
that sender (the party drawer's "Which state is this sender in?"); until then the engine uses nationwide
holidays and, for a Land authority, the 3-day delivery rule, at lower confidence. This script replays the
recorded Ordnung outputs of each split twice — as the benchmark runs them, and with the sender's Land
taken away (``RuleContext.region`` is ``None``; the person's own Land stays) — and writes both numbers and
every date that differs to ``evals/results/<date>-<model>-without-land.json``. It is a replay only: no model
is called, and a missing recording is an error. ``evals/conditions.py`` is not changed (it is part of the
benchmark's fingerprint), and the per-letter cache goes to a temporary folder, never ``evals/results/cache``.

Run it from the repository root::

    .venv/bin/python -m scripts.eval_without_land [--date YYYY-MM-DD] [--splits test holdout holdout2 holdout3 dev]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from evals import conditions, report
from evals.records import Entry, load_manifest, select_entries
from evals.run import DEFAULT_MODEL, MANIFEST_PATH, RESULTS_DIR, RunConfig, _commit, run_benchmark

from ordnung.models import DocumentExtraction, Page
from ordnung.rules import RuleContext

SPLITS = ("test", "holdout", "holdout2", "holdout3", "dev")
NOTE = (
    "The Ordnung condition's recorded outputs replayed with the checked-out code, once as the benchmark runs "
    "it (the Land the letterhead names is the sender's holiday region) and once with the sender's Land unknown, "
    "as in the app until the person sets it for that sender: nationwide holidays and, for a Land authority, the "
    "3-day delivery rule. The person's own Land is kept. No model was called."
)


@contextlib.contextmanager
def sender_land_unknown() -> Iterator[None]:
    """Within the block, the Ordnung condition's rules engine never learns the sender's Land."""
    original = conditions.ordnung_rule_context

    def unknown(entry: Entry, extraction: DocumentExtraction, pages: Sequence[Page] = ()) -> RuleContext:
        return dataclasses.replace(original(entry, extraction, pages), region=None)

    conditions.ordnung_rule_context = unknown
    try:
        yield
    finally:
        conditions.ordnung_rule_context = original


async def replay(split: str, model: str, work: Path) -> dict[str, Any]:
    """The results document of one replay of the Ordnung condition on ``split`` (nothing is written)."""
    config = RunConfig(
        split=split,
        models=[model],
        conditions=["ordnung"],
        resume=False,  # the cache knows nothing of the Land taken away
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


def headline(results: Mapping[str, Any]) -> dict[str, Any]:
    """Ordnung's due-date accuracy and its dangerously late and early rates."""
    metrics = results["metrics"]["ordnung"]
    return {name: metrics[name] for name in ("due_date_accuracy", "dangerous_late_rate", "early_rate")}


def changed_dates(
    with_land: Mapping[str, Any], without: Mapping[str, Any], lands: Mapping[str, str | None]
) -> list[dict[str, Any]]:
    """Every required to-do whose predicted date differs between the two replays, with the letterhead's Land."""
    before = {entry["id"]: entry for entry in with_land["entries"]}
    changes: list[dict[str, Any]] = []
    for entry in without["entries"]:
        old = before[entry["id"]]["conditions"]["ordnung"]["score"]["items"]
        new = entry["conditions"]["ordnung"]["score"]["items"]
        for was, now in zip(old, new, strict=True):
            if not now["required"] or was["predicted"] == now["predicted"]:
                continue
            changes.append(
                {
                    "entry_id": entry["id"],
                    "family": entry["family"],
                    "letterhead_land": lands.get(entry["id"]),
                    "expected": now["expected"],
                    "with_land": was["predicted"],
                    "without_land": now["predicted"],
                    "outcome": now["outcome"],
                    "direction": now["direction"],
                    "days_off": now["days_off"],
                }
            )
    return changes


async def split_numbers(split: str, model: str, entries: Sequence[Entry]) -> dict[str, Any]:
    """Both replays of one split, side by side."""
    with tempfile.TemporaryDirectory(prefix="ordnung-without-land-") as work:
        with_land = await replay(split, model, Path(work) / "with")
        with sender_land_unknown():
            without = await replay(split, model, Path(work) / "without")
    return {
        "entries": len(entries),
        "letterhead_land": sum(1 for entry in entries if entry.authority_region),
        "with_land": headline(with_land),
        "without_land": headline(without),
        "changed": changed_dates(with_land, without, {entry.id: entry.authority_region for entry in entries}),
    }


async def build(splits: Sequence[str], model: str, run_date: str) -> dict[str, Any]:
    manifest = load_manifest(MANIFEST_PATH)
    numbers = {}
    for split in splits:
        print(f"{split}: replaying with and without the sender's Land …", file=sys.stderr, flush=True)
        numbers[split] = await split_numbers(split, model, select_entries(manifest, split=split))
    return {
        "schema": report.WITHOUT_LAND_SCHEMA,
        "meta": {
            "date": run_date,
            "model": model,
            "condition": "ordnung",
            "backend": "replay",
            "commit": _commit(),
            "fingerprint": conditions.fingerprint("ordnung", model),
            "script": "scripts/eval_without_land.py",
            "note": NOTE,
        },
        "splits": numbers,
    }


def results_path(run_date: str, model: str) -> Path:
    return RESULTS_DIR / report.results_filename(run_date, model, "without-land")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.eval_without_land", description=__doc__)
    parser.add_argument("--date", dest="run_date", default=date.today().isoformat(), help="for the file name")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"the recordings' model (default: {DEFAULT_MODEL})"
    )
    parser.add_argument("--splits", nargs="+", choices=SPLITS, default=list(SPLITS), help="splits to replay")
    args = parser.parse_args(argv)
    results = asyncio.run(build(args.splits, args.model, args.run_date))
    path = report.write_json(results_path(args.run_date, args.model), results)
    for split, numbers in results["splits"].items():
        print(
            f"{split:<9} with the Land {report.rate(numbers['with_land']['due_date_accuracy'], counts=True):<34} "
            f"without {report.rate(numbers['without_land']['due_date_accuracy'], counts=True):<34} "
            f"late {int(numbers['without_land']['dangerous_late_rate']['k'])}",
            file=sys.stderr,
        )
    print(f"results → {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
