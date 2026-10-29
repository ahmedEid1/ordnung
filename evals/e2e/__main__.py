"""``python -m evals.e2e``: the benchmark's letters through the real app, checked from the file to the reminder.

A replay only (no model is called; a reading without its recording is an error, by id). Writes
``evals/results/<date>-<model>-e2e.json`` (``--out``: another folder; ``--no-write``: none) and prints one line per
split. The gates (``--exact-parity``, ``--max-late-reminders``, ``--known-set-aside``, ``--min-reminded``) and
``--compare FILE`` (a published file must equal the fresh run, its date and commit aside) exit 1 on a failure; a
letter the harness could not run always does.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from evals import __version__ as evals_version
from evals import conditions
from evals import report as benchmark_report
from evals.e2e import check, harness, metrics, report
from evals.metrics import DEFAULT_RESAMPLES, DEFAULT_SEED
from evals.records import PERSONA_LANGUAGE, PERSONA_REGION, Entry, load_manifest, select_entries
from evals.run import (
    DATASET_DIR,
    DEFAULT_MODEL,
    MANIFEST_PATH,
    RECORDED_DIR,
    RESULTS_DIR,
    SPLITS,
    _commit,
    _manifest_info,
)

CHECKER = Path(check.__file__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.e2e", description=__doc__)
    parser.add_argument(
        "--splits", nargs="+", choices=SPLITS, default=list(report.DEFAULT_SPLITS), help="splits to run"
    )
    parser.add_argument("--ids", nargs="+", metavar="ENTRY_ID", help="only these letters (a partial run)")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"the recordings' model (default: {DEFAULT_MODEL})"
    )
    parser.add_argument("--date", dest="run_date", default=date.today().isoformat(), help="for the file name")
    parser.add_argument(
        "--out", type=Path, default=RESULTS_DIR, metavar="FOLDER", help="folder for the results"
    )
    parser.add_argument("--no-write", action="store_true", help="write no results file")
    parser.add_argument(
        "--no-parity",
        action="store_true",
        help="skip the benchmark replay the stored dates are compared with",
    )
    parser.add_argument(
        "--exact-parity", action="store_true", help="fail when a stored date differs from the benchmark's"
    )
    parser.add_argument(
        "--max-late-reminders", type=int, metavar="N", help="fail above N obligations reminded late"
    )
    parser.add_argument(
        "--known-set-aside",
        nargs="*",
        metavar="ENTRY_ID",
        help="the letters whose genuine obligations the app is known to set aside: another one fails, and so does "
        "one of these that no longer is",
    )
    parser.add_argument(
        "--min-reminded", type=float, metavar="RATE", help="fail below this share reminded in time"
    )
    parser.add_argument("--compare", type=Path, metavar="FILE", help="fail unless FILE equals the fresh run")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--resamples", type=int, default=DEFAULT_RESAMPLES)
    return parser


def _entries(splits: Sequence[str], ids: Sequence[str] | None) -> list[Entry]:
    manifest = load_manifest(MANIFEST_PATH)
    chosen: list[Entry] = []
    for split in splits:
        chosen += select_entries(manifest, split=split, ids=ids)
    if ids:
        missing = sorted(set(ids) - {entry.id for entry in chosen})
        if missing:
            raise SystemExit(f"not in the splits {', '.join(splits)}: {', '.join(missing)}")
    return chosen


def _meta(
    args: argparse.Namespace, entries: Sequence[Entry], replay: dict[str, Any], parity: bool
) -> dict[str, Any]:
    splits = list(dict.fromkeys(entry.split for entry in entries))
    return {
        "date": args.run_date,
        "model": args.model,
        "backend": "replay",
        "mode": "nothing-confirmed",
        "splits": splits,
        "pooled": metrics.pooled_splits(splits),
        "partial": bool(args.ids),
        "ids": sorted(args.ids) if args.ids else None,
        "letters": len(entries),
        "commit": _commit(),
        "fingerprint": conditions.fingerprint("ordnung", args.model),
        "dataset": _manifest_info(MANIFEST_PATH),
        "evals_version": evals_version,
        "checker_sha256": hashlib.sha256(CHECKER.read_bytes()).hexdigest(),
        "parity_reference": "scripts/eval_without_land.py: the Ordnung condition without the sender's Land"
        if parity
        else None,
        "persona": {
            "language": PERSONA_LANGUAGE,
            "region": f"the letter's recipient Land, else {PERSONA_REGION}",
            "signer": harness.SIGNER,
        },
        "replay": replay,
        "seed": args.seed,
        "resamples": args.resamples,
        "script": "python -m evals.e2e",
        "note": report.NOTE,
    }


async def run(args: argparse.Namespace, entries: Sequence[Entry]) -> dict[str, Any]:
    """Observe, replay the benchmark, check and sum up: the results document."""
    observed = await harness.observe_all(
        entries, dataset_dir=DATASET_DIR, recorded_dir=RECORDED_DIR, model=args.model
    )
    bench = (
        None
        if args.no_parity
        else await harness.benchmark_dates(
            entries, model=args.model, manifest_path=MANIFEST_PATH, recorded_dir=RECORDED_DIR
        )
    )
    by_id = {entry.id: entry for entry in entries}
    verdicts = [
        check.check_letter(
            by_id[obs.entry_id], obs, bench=bench.get(obs.entry_id) if bench is not None else None
        )
        for obs in observed.observations
    ]
    summary = metrics.summarise(verdicts, seed=args.seed, resamples=args.resamples)
    return report.build_results(
        meta=_meta(args, entries, observed.replay, bench is not None),
        verdicts=verdicts,
        summary=summary,
        set_aside=metrics.set_aside(sorted(verdicts, key=lambda verdict: verdict.entry_id)),
        errors=observed.errors,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    entries = _entries(args.splits, args.ids)
    results = asyncio.run(run(args, entries))
    for line in report.summary_lines(results):
        print(line, file=sys.stderr)
    if not args.no_write:
        path = report.results_path(
            args.run_date, args.model, args.out, splits=args.splits, partial=bool(args.ids)
        )
        print(f"results → {benchmark_report.write_json(path, results)}", file=sys.stderr)
    failures = report.gate_failures(
        results,
        exact_parity=args.exact_parity,
        max_late_reminders=args.max_late_reminders,
        known_set_aside=args.known_set_aside,
        min_reminded=args.min_reminded,
    )
    if args.compare is not None:
        fresh = json.loads(json.dumps(results, ensure_ascii=False))  # as written: lists, not tuples
        differ = report.differences(fresh, benchmark_report.load_results(args.compare))
        if differ:
            failures.append(f"{args.compare.name} differs from the fresh run in: {', '.join(differ)}")
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
