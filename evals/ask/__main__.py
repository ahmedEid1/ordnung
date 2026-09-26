"""``python -m evals.ask`` — the Ask benchmark (replay by default; see :mod:`evals.ask`)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from evals.ask.report import headline, results_payload, write_docs, write_results
from evals.ask.run import DEFAULT_MODEL, RESULTS_DIR, BenchmarkError, Config, RunResult, run
from evals.ask.run import run as run_benchmark  # noqa: F401  (re-exported for tests)


def gate_failures(result: RunResult, args: argparse.Namespace) -> list[str]:
    """The CI gate: what the replayed run must meet (empty when every threshold holds)."""
    s = result.summary
    problems = []
    if result.misses:
        problems.append(f"{len(result.misses)} question(s) have no recording — record them with --live")
    if s["not_answered"]:
        problems.append(f"{s['not_answered']} question(s) got no answer")
    accuracy = s["accuracy"]["value"]
    if args.min_accuracy is not None and (accuracy is None or accuracy < args.min_accuracy):
        problems.append(f"answer accuracy {accuracy} is below {args.min_accuracy}")
    abstention = s["abstention"]["value"]
    if args.min_abstention is not None and (abstention is None or abstention < args.min_abstention):
        problems.append(f"abstention {abstention} is below {args.min_abstention}")
    unsupported = s["guard"]["unsupported_in_final"]
    if args.max_unsupported is not None and unsupported > args.max_unsupported:
        problems.append(
            f"{unsupported} unsupported value(s) left in final answers (max {args.max_unsupported})"
        )
    successes = s["attack_success"]["k"]
    if args.max_attack_success is not None and successes > args.max_attack_success:
        problems.append(f"{successes:g} successful attack(s) (max {args.max_attack_success})")
    return problems


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m evals.ask",
        description="Ask benchmark: questions about the sample life, with gold answers from its truth, "
        "plus injected letters. Replays recorded answers unless --live.",
    )
    parser.add_argument("--live", action="store_true", help="record missing answers with the claude CLI")
    parser.add_argument("--refresh", action="store_true", help="with --live: record every answer anew")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"model alias (default {DEFAULT_MODEL})")
    parser.add_argument("--only", default="", help="comma-separated question or attack ids")
    parser.add_argument("--concurrency", type=int, default=3, help="questions asked at once when live")
    parser.add_argument(
        "--write", action="store_true", help="write evals/results/…-ask.json and docs/evals-ask.md"
    )
    parser.add_argument("--date", default=None, help="date of the results file (default: today)")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--min-accuracy", type=float, default=None, help="gate: minimum answer accuracy")
    parser.add_argument(
        "--min-abstention", type=float, default=None, help="gate: minimum abstention accuracy"
    )
    parser.add_argument(
        "--max-unsupported",
        type=int,
        default=None,
        help="gate: unsupported values in final answers (read by the scorer)",
    )
    parser.add_argument("--max-attack-success", type=int, default=None, help="gate: successful attacks")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    only = [part.strip() for part in args.only.split(",") if part.strip()] or None
    config = Config(
        model=args.model,
        live=args.live or args.refresh,
        refresh=args.refresh,
        only=only,
        concurrency=args.concurrency,
    )
    try:
        result = run(config)
    except BenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for line in headline(result.summary):
        print(line)
    if args.write:
        if only:
            print("error: --write needs the whole benchmark (no --only)", file=sys.stderr)
            return 2
        payload = results_payload(result, run_date=args.date or date.today().isoformat())
        print(f"wrote {write_results(payload, args.results_dir)} and {write_docs(payload)}")
    problems = gate_failures(result, args)
    for problem in problems:
        print(f"gate: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
