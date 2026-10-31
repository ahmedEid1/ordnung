"""``python -m evals.ask`` — the Ask benchmark (replay by default; see :mod:`evals.ask`)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from evals import harness
from evals.ask.report import (
    headline,
    recorded_on,
    replaces_a_recording,
    results_payload,
    stale_docs,
    strict_headline,
    write_docs,
    write_results,
)
from evals.ask.run import (
    DEFAULT_MODEL,
    HELDOUT_RECORDED_DIR,
    RECORDED_DIR,
    RESULTS_DIR,
    SETS,
    BenchmarkError,
    Config,
    RunResult,
    as_recorded,
    run,
)
from evals.ask.run import run as run_benchmark  # noqa: F401  (re-exported for tests)


def _record_flags(args: argparse.Namespace) -> str:
    """How this set is recorded: the development set on another day than its own, in the open; the held-out set on
    the day it is built for."""
    return (
        "--live --today <its day>"
        if getattr(args, "set", "dev") == "heldout"
        else "--live --allow-another-today"
    )


def gate_failures(result: RunResult, args: argparse.Namespace) -> list[str]:
    """The CI gate: what the replayed run must meet (empty when every threshold holds)."""
    s = result.summary
    problems = []
    if result.misses:
        problems.append(
            f"{len(result.misses)} question(s) have no recording ({', '.join(sorted(result.misses))}) "
            f"— record them with {_record_flags(args)}"
        )
    if result.stale:
        listed = "; ".join(f"{qid}: {', '.join(tools)}" for qid, (_, tools) in sorted(result.stale.items()))
        problems.append(
            f"{len(result.stale)} recording(s) have tool results the current tools no longer give ({listed}) "
            f"— delete them with --prune-stale and record them again with {_record_flags(args)}"
        )
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
    known = set(args.known_attack or ())
    unknown = sorted(
        score.id
        for score in result.scored
        if score.kind == "attack" and score.success_final and score.id not in known
    )
    if args.max_attack_success is not None and len(unknown) > args.max_attack_success:
        listed = f" besides the known {', '.join(sorted(known))}" if known else ""
        problems.append(
            f"{len(unknown)} successful attack(s){listed}: {', '.join(unknown)} (max {args.max_attack_success})"
        )
    household = s.get("household")
    if household and household["not_answered"]:
        problems.append(f"{household['not_answered']} household question(s) got no answer")
    if args.min_household is not None:
        attribution = household["attribution"]["value"] if household else None
        if attribution is None or attribution < args.min_household:
            problems.append(f"household attribution {attribution} is below {args.min_household}")
    return problems + strict_gate_failures(result, args)


def strict_gate_failures(result: RunResult, args: argparse.Namespace) -> list[str]:
    """The gates on the strict scores, the request lock and the budget (empty when every threshold holds)."""
    problems = []
    if result.drift:
        problems.append(
            f"{len(result.drift)} recording(s) differ from the request lock: {result.drift[0]} — see "
            "`python -m evals.harness diff-requests HEAD --ask`"
        )
    budget = next(
        (t.error for t in result.turns.values() if (t.error or "").startswith("budget reached")), None
    )
    if budget:
        problems.append(budget)
    strict = result.strict_summary
    value = strict.get("strict_accuracy", {}).get("value")
    if args.min_strict_accuracy is not None and (value is None or value < args.min_strict_accuracy):
        problems.append(f"strict answer accuracy {value} is below {args.min_strict_accuracy}")
    harmful = strict.get("harmful_answers", [])
    if args.max_harmful is not None and len(harmful) > args.max_harmful:
        problems.append(f"{len(harmful)} harmful answer(s): {', '.join(harmful)} (max {args.max_harmful})")
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
    parser.add_argument(
        "--prune-stale",
        action="store_true",
        help="delete the recordings whose tool results the current tools no longer give (then --live)",
    )
    parser.add_argument(
        "--check-docs",
        action="store_true",
        help="gate: docs/evals-ask.md and the newest results file are what --write would write (with its date)",
    )
    parser.add_argument("--date", default=None, help="date of the results file (default: today)")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument(
        "--recorded-dir",
        type=Path,
        default=None,
        help="the recordings folder (default: evals/recorded/ask, or evals/recorded/ask-heldout with --set heldout); "
        "a smoke records into a scratch one",
    )
    parser.add_argument("--recorder-lock", type=Path, default=None, help=argparse.SUPPRESS)
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
    parser.add_argument(
        "--max-attack-success",
        type=int,
        default=None,
        help="gate: successful attacks, not counting the --known-attack ids",
    )
    parser.add_argument(
        "--known-attack",
        action="append",
        default=[],
        metavar="ID",
        help="an attack known to succeed for a documented reason (repeatable); any other success fails the gate",
    )
    parser.add_argument(
        "--min-household",
        type=float,
        default=None,
        help="gate: minimum share of household questions whose answer says whose each number is",
    )
    add_heldout_arguments(parser)
    return parser.parse_args(argv)


def add_heldout_arguments(parser: argparse.ArgumentParser) -> None:
    """The held-out set, repeated runs, the recording's budget and waiting, and the strict gates."""
    parser.add_argument(
        "--set",
        choices=SETS,
        default="dev",
        help="dev: the development set (default); heldout: the held-out set of evals/ask/heldout/, written after "
        "the code freeze (recordings in evals/recorded/ask-heldout/, results …-ask-heldout.json, no page)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="run N of the same questions (default 1, the recorded run): run N ≥ 2 is recorded and replayed under "
        "keys of its own, with the same request; its results file ends in -rN",
    )
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        default=None,
        metavar="USD",
        help="with --live: start no new call once this set's calls at this --repeat cost this much, counting what "
        "its ledger says earlier runs spent (what is recorded is kept)",
    )
    parser.add_argument(
        "--wait-on-limit",
        type=float,
        default=None,
        metavar="HOURS",
        help="with --live: on a usage limit, wait for its reset (no call is made) and go on, until HOURS after the "
        "start",
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="the held-out set's day: its ledger is built, its turns asked and its answers scored for it — the day it "
        "is recorded (default: the sample life's, 2026-09-28; the development set is asked on no other)",
    )
    parser.add_argument(
        "--allow-another-today",
        action="store_true",
        help="with --live: record on another day than the set's — the development set, pinned to 2026-09-28, recorded "
        "again in the open (the model sees two todays, and the results say both days); the held-out set only as a "
        "smoke into a scratch --recorded-dir outside the checkout",
    )
    parser.add_argument(
        "--min-strict-accuracy",
        type=float,
        default=None,
        help="gate: minimum strict answer accuracy (every gold value, nothing harmful, no false inclusion)",
    )
    parser.add_argument(
        "--max-harmful", type=int, default=None, help="gate: answers stating a harmful value (a later date …)"
    )


def main(
    argv: Sequence[str] | None = None, *, recorded_dir: Path = RECORDED_DIR, heldout_dir: Path | None = None
) -> int:
    args = parse_args(argv)
    only = [part.strip() for part in args.only.split(",") if part.strip()] or None
    config = Config(
        model=args.model,
        live=args.live or args.refresh,
        refresh=args.refresh,
        only=only,
        concurrency=args.concurrency,
        recorded_dir=args.recorded_dir or (HELDOUT_RECORDED_DIR if args.set == "heldout" else recorded_dir),
        set_name=args.set,
        heldout_dir=heldout_dir,
        repeat=args.repeat,
        max_cost_usd=args.max_cost_usd,
        wait_on_limit_hours=args.wait_on_limit,
        today=args.today,
        allow_another_today=args.allow_another_today,
        recorder_lock=args.recorder_lock or harness.RECORDER_LOCK,  # one recorder for every benchmark
    )
    try:
        result = run(config)
    except BenchmarkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for line in [*headline(result.summary), *strict_headline(result.strict_summary)]:
        print(line)
    if args.prune_stale:
        for qid, (path, _) in sorted(result.stale.items()):
            if path is not None and path.exists():
                path.unlink()
                print(f"deleted the stale recording of {qid}: {path.name}")
    if args.write and result.stale:
        print("error: --write needs recordings that match the current tools (see the gate)", file=sys.stderr)
        args.write = False
    if args.write:
        if only:
            print("error: --write needs the whole benchmark (no --only)", file=sys.stderr)
            return 2
        try:
            payload = _payload(result, args, args.date or date.today().isoformat())
        except BenchmarkError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        recording = None if result.config.live else replaces_a_recording(args.results_dir, payload)
        if recording is not None:
            print(
                f"error: {recording.name} is a live run as recorded, which a re-scoring never replaces (a "
                "re-scoring is written as <date>-<model>-ask…-rescored.json, dated the day it is made)",
                file=sys.stderr,
            )
            return 2
        written = write_results(payload, args.results_dir)
        if _has_page(args):
            print(f"wrote {written} and {write_docs(payload)}")
        else:  # a held-out run or a repeat sits beside the page's run, never replaces it
            print(f"wrote {written}")
    problems = gate_failures(result, args)
    if args.check_docs:
        if only:
            print("error: --check-docs needs the whole benchmark (no --only)", file=sys.stderr)
            return 2
        try:
            stale = stale_docs(
                lambda day: _payload(result, args, day, rescoring=True),
                args.results_dir,
                args.model,
                as_recorded=lambda day, kept=None: results_payload(
                    as_recorded(result, kept), run_date=day, schema=1
                ),
                as_live=lambda day: results_payload(result, run_date=day),
                set_name=args.set,
                repeat=args.repeat,
            )
        except BenchmarkError as exc:
            stale = [str(exc)]
        problems += [f"{problem} — regenerate with --write --date <its date>" for problem in stale]
    for problem in problems:
        print(f"gate: {problem}", file=sys.stderr)
    return 1 if problems else 0


def _payload(
    result: RunResult, args: argparse.Namespace, day: str, *, rescoring: bool | None = None
) -> dict[str, Any]:
    """The results file of ``day``: a live run's own, or a replay's re-scoring (``-rescored``) of the live run it
    replays — the newest committed one made before that day's re-scoring, the same day's included."""
    if rescoring is None:
        rescoring = not result.config.live
    if not rescoring:
        return results_payload(result, run_date=day)
    recorded = recorded_on(args.results_dir, args.model, day, set_name=args.set, repeat=args.repeat)
    if recorded is None:
        raise BenchmarkError(
            f"a replay re-scores a live run, and {args.results_dir} has no results file of one on or before {day} "
            "for this set and run: record it with --live --write"
        )
    return results_payload(result, run_date=day, recorded=recorded)


def _has_page(args: argparse.Namespace) -> bool:
    """Only the development set's run 1 writes ``docs/evals-ask.md``."""
    return bool(args.set == "dev" and args.repeat == 1)


if __name__ == "__main__":
    sys.exit(main())
