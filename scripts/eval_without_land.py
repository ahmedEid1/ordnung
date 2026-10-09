"""Publish the benchmark's Ordnung numbers without the sender's Land, and with the state the postcode suggests.

The benchmark gives Ordnung's rules engine the Land the letterhead names (``Entry.authority_region``,
``evals.conditions.ordnung_rule_context``). The app knows a sender's Land only once the person sets it for
that sender, or says Yes to the state Ordnung suggests from the postcode on their letter (ADR 0019); until
then the engine uses nationwide holidays and, for a Land authority, the 3-day delivery rule, at lower
confidence. This script replays the recorded Ordnung outputs of each split three times — as the benchmark runs
them; with the sender's Land taken away (``RuleContext.region`` is ``None``; the person's own Land stays); and
with the state the postcode suggests confirmed (``RuleContext.region`` is what
``ordnung.rules.postcodes.suggest_land_why`` gives for the reading's sender, as if the person said Yes to every
suggestion) — and writes the numbers, how the suggestions compare with the letterhead's Land, and every date
that differs to ``evals/results/<date>-<model>-without-land.json`` (``--out``: another folder, as CI does to
compare a replay with the published file). It is a replay only: no model is called, and a missing recording
is an error. ``evals/conditions.py`` is not changed (it is part of the benchmark's fingerprint), and the
per-letter cache goes to a temporary folder, never ``evals/results/cache``.

Run it from the repository root::

    .venv/bin/python -m scripts.eval_without_land [--date YYYY-MM-DD] [--splits test holdout holdout2 holdout3 dev]
        [--out FOLDER]
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
from typing import Any, get_args

from evals import conditions, report
from evals.records import Entry, load_manifest, select_entries
from evals.run import DEFAULT_MODEL, MANIFEST_PATH, RESULTS_DIR, RunConfig, _commit, run_benchmark

from ordnung.models import DocumentExtraction, Page
from ordnung.rules import RuleContext
from ordnung.rules.postcodes import Reason, suggest_land_why

SPLITS = ("test", "holdout", "holdout2", "holdout3", "dev")
#: Why a letter gets no suggestion: every reason of the app's policy but "suggested".
NO_SUGGESTION = tuple(reason for reason in get_args(Reason) if reason != "suggested")
NOTE = (
    "The Ordnung condition's recorded outputs replayed with the checked-out code three times: as the benchmark "
    "runs it (the Land the letterhead names is the sender's holiday region); with the sender's Land unknown, as "
    "in the app until the person sets it for that sender: nationwide holidays and, for a Land authority, the "
    "3-day delivery rule; and with the state the postcode on the sender's letter suggests confirmed, as if the "
    "person said Yes to every suggestion (ordnung.rules.postcodes.suggest_land_why on the reading's sender "
    "address and the letter's visible text; no own-Land check, as the benchmark has no profile address). The "
    "person's own Land is kept. No model was called."
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


@contextlib.contextmanager
def sender_land_suggested() -> Iterator[dict[str, tuple[str | None, Reason]]]:
    """Within the block, the Ordnung condition's rules engine is given the state the postcode on the sender's
    letter suggests as the sender's Land (none: nationwide holidays), as if the person said Yes to every
    suggestion. Yields each letter's suggested Land and the reason, by entry id, as the replay fills them in."""
    original = conditions.ordnung_rule_context
    suggested: dict[str, tuple[str | None, Reason]] = {}

    def confirmed(entry: Entry, extraction: DocumentExtraction, pages: Sequence[Page] = ()) -> RuleContext:
        sender = extraction.sender
        hit, reason = suggest_land_why(  # no own-Land check: the benchmark has no profile address
            sender.address if sender else None,
            email=sender.email if sender else None,
            website=sender.website if sender else None,
            visible_text="\n".join(page.text for page in pages),
        )
        region = hit.region if hit else None
        suggested[entry.id] = (region, reason)
        return dataclasses.replace(original(entry, extraction, pages), region=region)

    conditions.ordnung_rule_context = confirmed
    try:
        yield suggested
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


def _changed(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> Iterator[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]:
    """Each required to-do whose predicted date differs between two replays: (entry, before, after)."""
    earlier = {entry["id"]: entry for entry in before["entries"]}
    for entry in after["entries"]:
        old = earlier[entry["id"]]["conditions"]["ordnung"]["score"]["items"]
        new = entry["conditions"]["ordnung"]["score"]["items"]
        for was, now in zip(old, new, strict=True):
            if now["required"] and was["predicted"] != now["predicted"]:
                yield entry, was, now


def _scored(now: Mapping[str, Any]) -> dict[str, Any]:
    return {name: now[name] for name in ("outcome", "direction", "days_off")}


def changed_dates(
    with_land: Mapping[str, Any], without: Mapping[str, Any], lands: Mapping[str, str | None]
) -> list[dict[str, Any]]:
    """Every required to-do whose predicted date differs between the two replays, with the letterhead's Land."""
    return [
        {
            "entry_id": entry["id"],
            "family": entry["family"],
            "letterhead_land": lands.get(entry["id"]),
            "expected": now["expected"],
            "with_land": was["predicted"],
            "without_land": now["predicted"],
            **_scored(now),
        }
        for entry, was, now in _changed(with_land, without)
    ]


def changed_with_suggestion(
    with_land: Mapping[str, Any],
    suggested: Mapping[str, Any],
    lands: Mapping[str, str | None],
    suggested_lands: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    """Every required to-do whose predicted date differs between the letterhead replay and the replay with the
    suggested state confirmed, with both Länder."""
    return [
        {
            "entry_id": entry["id"],
            "family": entry["family"],
            "letterhead_land": lands.get(entry["id"]),
            "suggested_land": suggested_lands.get(entry["id"]),
            "expected": now["expected"],
            "with_land": was["predicted"],
            "with_suggestion": now["predicted"],
            **_scored(now),
        }
        for entry, was, now in _changed(with_land, suggested)
    ]


def suggestion_counts(
    lands: Mapping[str, str | None], suggested: Mapping[str, tuple[str | None, Reason]]
) -> dict[str, Any]:
    """How the suggested states compare with the Land each letterhead names (``lands``, by entry id), and why a
    letter got none. A letter the rules engine never saw is an error, never counted as one without."""
    missing = [entry_id for entry_id in lands if entry_id not in suggested]
    if missing:
        raise RuntimeError(f"the replay never reached the rules engine: {', '.join(missing)}")
    none = dict.fromkeys(NO_SUGGESTION, 0)
    not_suggested = dict.fromkeys(NO_SUGGESTION, 0)
    right = wrong = suggested_without = 0
    for entry_id, letterhead in lands.items():
        region, reason = suggested[entry_id]
        if letterhead is None:
            if region is None:
                not_suggested[reason] += 1
            else:
                suggested_without += 1
        elif region is None:
            none[reason] += 1
        elif region == letterhead:
            right += 1
        else:
            wrong += 1
    return {
        "letterhead_land": sum(1 for land in lands.values() if land),
        "right": right,
        "wrong": wrong,
        "none": none,
        "suggested_without_letterhead_land": suggested_without,
        "not_suggested_without_letterhead_land": not_suggested,
    }


async def split_numbers(split: str, model: str, entries: Sequence[Entry]) -> dict[str, Any]:
    """The three replays of one split, side by side."""
    lands = {entry.id: entry.authority_region for entry in entries}
    with tempfile.TemporaryDirectory(prefix="ordnung-without-land-") as work:
        with_land = await replay(split, model, Path(work) / "with")
        with sender_land_unknown():
            without = await replay(split, model, Path(work) / "without")
        with sender_land_suggested() as suggestions:
            suggested = await replay(split, model, Path(work) / "suggested")
    suggested_lands = {entry_id: region for entry_id, (region, _) in suggestions.items()}
    return {
        "entries": len(entries),
        "letterhead_land": sum(1 for entry in entries if entry.authority_region),
        "with_land": headline(with_land),
        "without_land": headline(without),
        "with_suggestion": headline(suggested),
        "suggestion": suggestion_counts(lands, suggestions),
        "changed": changed_dates(with_land, without, lands),
        "changed_with_suggestion": changed_with_suggestion(with_land, suggested, lands, suggested_lands),
    }


async def build(splits: Sequence[str], model: str, run_date: str) -> dict[str, Any]:
    manifest = load_manifest(MANIFEST_PATH)
    numbers = {}
    for split in splits:
        print(
            f"{split}: replaying with, without and with the suggested sender's Land …",
            file=sys.stderr,
            flush=True,
        )
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


def results_path(run_date: str, model: str, folder: Path = RESULTS_DIR) -> Path:
    return folder / report.results_filename(run_date, model, "without-land")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.eval_without_land", description=__doc__)
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
    args = parser.parse_args(argv)
    results = asyncio.run(build(args.splits, args.model, args.run_date))
    path = report.write_json(results_path(args.run_date, args.model, args.out), results)
    for split, numbers in results["splits"].items():
        suggestion = numbers["suggestion"]
        print(
            f"{split:<9} with the Land {report.rate(numbers['with_land']['due_date_accuracy'], counts=True):<34} "
            f"without {report.rate(numbers['without_land']['due_date_accuracy'], counts=True):<34} "
            f"late {int(numbers['without_land']['dangerous_late_rate']['k'])}  "
            f"suggested {report.rate(numbers['with_suggestion']['due_date_accuracy'], counts=True):<34} "
            f"late {int(numbers['with_suggestion']['dangerous_late_rate']['k'])}  "
            f"right {suggestion['right']} wrong {suggestion['wrong']} of {suggestion['letterhead_land']}  "
            f"changed {len(numbers['changed_with_suggestion'])}",
            file=sys.stderr,
        )
    print(f"results → {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
