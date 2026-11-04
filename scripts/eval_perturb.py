"""Build, replay (or record) and score the stress cells of the 0.4.0 evaluation (``evals/perturb``).

Two cells on 48 standard text letters of holdout4, the final run's split (:mod:`evals.perturb.build`): I1, one
paragraph addressed to an AI (shift, drop or re-route a deadline), and D1, one legally inert sentence that names a
date. Conditions: Ordnung and LLM + rules tool (the strongest baseline). The clean reference is holdout4's read 1 of
the same letters, its recordings (``evals/recorded``) replayed by the benchmark runner on this code; the cells'
recordings live in ``evals/recorded/stress`` (``--recorded-dir``). The results go to ``<out>/<date>-<model>-stress.json``:
ids, dates, outcomes and numbers, never a letter's words.

The cells are built for the day they are recorded (``--today``, every letter's simulated today, so the model is never
shown two days); the stress manifest names no day, and a day outside the letters' window is refused.

**Noise floor** (``--noise-floor-from-runs R1 R2 R3``): per condition, how many of holdout4's scored items do not get
the same answer (a date, or none) in every read — the count the final analysis calls ``unstable`` — computed directly
from the complete holdout4 results files, with no analysis run and no check of their frozen inputs (the analysis
checks them after recording). It needs two reads or more; with one, the results file says there is none. The value
goes into the results file and to stdout only, and the results file names each read's file and sha256, so a
``--check`` without the option finds them again beside the published file. ``--noise-floor FILE`` reads
``{condition: {"k", "n"}}`` instead.

Run it from the repository root::

    .venv/bin/python -m scripts.eval_perturb --list-base                 # the base set and what each letter gets
    .venv/bin/python -m scripts.eval_perturb --clean-only --out DIR      # the clean reference alone (no templates)
    .venv/bin/python -m scripts.eval_perturb --build-only [--write-manifest]   # the files (needs the templates)
    .venv/bin/python -m scripts.eval_perturb --out DIR [--check PUBLISHED]     # replay both cells and score them
    ORDNUNG_CLAUDE_BIN=<wrapper> .venv/bin/python -m scripts.eval_perturb --cells I1,D1 --live --today <day> \\
        --max-cost-usd <cap> --noise-floor-from-runs <holdout4 r1> <r2> <r3>   # record

A replay calls no model (a missing recording is an error) and needs ``--out``, so it never lands beside the published
file; ``--check`` compares it with the published file and fails on any difference. Recording needs the templates and
the committed stress manifest (both written blind, before the pre-registration), a budget
(``--max-cost-usd``) and the recording harness that enforces it (``evals/harness.py``). The builder never
writes into ``evals/dataset``; the files go to ``--build-dir`` (git-ignored ``evals/perturb/build`` by default).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import hashlib
import importlib
import json
import sys
import tempfile
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, cast

from evals import analysis, conditions, report, stats
from evals.harness import STOPPED, Stop, add_stop_arguments, shown, stopped_message
from evals.perturb import build, score
from evals.perturb import templates as tpl
from evals.records import ConditionName, Entry, Prediction, load_manifest
from evals.run import DEFAULT_MODEL, RECORDED_DIR, RESULTS_DIR, RunConfig, _commit, live_setup, run_benchmark

STRESS_RECORDED_DIR = RECORDED_DIR / "stress"
#: the two conditions the stress run compares (evals/perturb/score.py), as the runner names them
CONDITIONS = cast("tuple[ConditionName, ...]", score.CONDITIONS)
SCRIPT = "scripts/eval_perturb.py"
#: The split whose reads give the noise floor: the cells' own base split, read three times.
NOISE_FLOOR_SPLIT = build.BASE_SPLITS[0]
NOISE_FLOOR_READS = 3


class StressError(RuntimeError):
    """The stress run cannot go on (said in one line, never with a letter's text)."""


class StressStopped(StressError):
    """The run's stop file or ``--stop-at`` asked, and no new letter started (exit 4). An invocation is one unit: it
    is recorded again whole."""


def parse_cells(text: str) -> list[str]:
    cells = [cell.strip() for cell in text.split(",") if cell.strip()]
    unknown = [cell for cell in cells if cell not in build.CELLS]
    if unknown or not cells:
        raise argparse.ArgumentTypeError(f"cells are {', '.join(build.CELLS)}, not {text!r}")
    return [cell for cell in build.CELLS if cell in cells]


def harness_options(
    *,
    live: bool,
    max_cost_usd: float | None,
    wait_on_limit: float | None,
    config_type: Any = RunConfig,
    stop: Stop | None = None,
) -> dict[str, Any]:
    """The recording harness's options for :class:`evals.run.RunConfig` (budget, waiting, the stop, the shared recorder
    lock), refused when this checkout has no harness: a live stress run never records without its budget stop."""
    fields = {field.name for field in dataclasses.fields(config_type)}
    wanted: dict[str, Any] = {
        "max_cost_usd": max_cost_usd,
        "wait_on_limit_hours": wait_on_limit,
        "stop": stop,
    }
    missing = sorted(name for name, value in wanted.items() if value is not None and name not in fields)
    if missing:
        raise StressError(
            f"{', '.join(missing)} need the recording harness (evals/harness.py), which this checkout "
            "does not have: nothing was recorded"
        )
    options = {name: value for name, value in wanted.items() if value is not None}
    if live and "recorder_lock" in fields:
        harness = importlib.import_module("evals.harness")
        options["recorder_lock"] = harness.RECORDER_LOCK
    return options


async def _predictions(
    config: RunConfig, *, quiet: bool
) -> tuple[dict[str, dict[str, Prediction]], dict[str, Any]]:
    """One benchmark run's predictions by condition and letter, and its results' ``meta``."""
    progress = None if quiet else (lambda message: print(message, file=sys.stderr, flush=True))
    outcome = await run_benchmark(config, progress=progress)
    (run,) = outcome.runs
    if outcome.stopped:
        raise StressStopped(
            f"{config.split}: {stopped_message(outcome.stopped)} — a stress invocation is one unit: move its recordings "
            f"aside with `python -m evals.harness retake --whole-run --recorded-dir {shown(config.recorded_dir)} "
            f"--repeat {config.repeat} --to <folder>` and record it again whole"
        )
    if run.results is None:
        problems = "; ".join(f"{p.condition} {p.entry_id}: {(p.error or '')[:120]}" for p in run.errors[:5])
        raise StressError(f"the {config.split} run failed: {problems or run.fatal or 'no results'}")
    return run.predictions, dict(run.results["meta"])


async def clean_reference(
    base: Sequence[Entry], *, model: str, work: Path, quiet: bool = True
) -> tuple[dict[str, dict[str, Prediction]], dict[str, Any]]:
    """The base letters' own recordings replayed on this code, for both conditions (never recorded): their split's
    read 1, as the benchmark runner replays it."""
    predictions: dict[str, dict[str, Prediction]] = {condition: {} for condition in CONDITIONS}
    meta: dict[str, Any] = {}
    for split in build.BASE_SPLITS:
        ids = sorted(e.id for e in base if e.split == split)
        config = RunConfig(
            split=split,
            models=[model],
            conditions=list(CONDITIONS),
            ids=ids,
            repeat=1,
            resume=False,
            write_results=False,
            write_docs=False,
            manifest_path=build.DATASET_MANIFEST,
            results_dir=work / f"clean-{split}",
        )
        found, meta = await _predictions(config, quiet=quiet)
        for condition in CONDITIONS:
            predictions[condition].update(found[condition])
    return predictions, meta


@contextlib.contextmanager
def recording_session(
    *,
    live: bool,
    options: Mapping[str, Any],
    model: str,
    recorded_dir: Path,
    entries: Sequence[Entry],
    say: Any = None,
) -> Iterator[Any]:
    """Around the cells' recording: the recorder lock, held from the first cell to the last, and one live setup for
    every cell (one budget for ``--max-cost-usd``, started from what the ledger says the cells' letters already cost;
    one waiting, one ledger). A replay shares nothing: ``None``."""
    if not live:
        yield None
        return
    harness = importlib.import_module("evals.harness")
    config = RunConfig(
        models=[model],
        live=True,
        recorded_dir=recorded_dir,
        **{key: value for key, value in options.items() if key != "recorder_lock"},
    )
    lock = options.get("recorder_lock") or recorded_dir / harness.RECORDER_LOCK_NAME
    with harness.RecorderLock(lock, command=" ".join(["scripts.eval_perturb", *sys.argv[1:]])):
        yield live_setup(
            config, say or (lambda message: print(message, file=sys.stderr, flush=True)), entries
        )


async def cell_predictions(
    cell: str,
    *,
    build_dir: Path,
    model: str,
    recorded_dir: Path,
    live: bool,
    concurrency: int,
    timeout_s: float,
    options: Mapping[str, Any],
    work: Path,
    quiet: bool = True,
    shared: Any = None,
) -> tuple[dict[str, dict[str, Prediction]], dict[str, Any]]:
    """One cell's predictions for both conditions: replayed from ``recorded_dir``, or recorded there (``live``), with
    the ``shared`` live setup of :func:`recording_session` (one budget and one lock for every cell)."""
    if live and shared is None:
        raise StressError(
            "a live cell records inside recording_session: one budget and one lock for every cell"
        )
    config = RunConfig(
        split=f"stress-{cell}",
        models=[model],
        conditions=list(CONDITIONS),
        live=live,
        resume=False,
        concurrency=concurrency,
        timeout_s=timeout_s,
        write_results=False,
        write_docs=False,
        manifest_path=build_dir / "manifest.json",
        recorded_dir=recorded_dir,
        results_dir=work / f"cell-{cell}",
        live_setup=shared,
        **options,
    )
    return await _predictions(config, quiet=quiet)


def score_all(
    base: Sequence[Entry],
    plan: Mapping[str, Sequence[build.Assignment]],
    clean: Mapping[str, Mapping[str, Prediction]],
    cells: Mapping[str, Mapping[str, Mapping[str, Prediction]]],
    perturbed: Mapping[str, Entry],
) -> tuple[dict[str, list[score.LetterScore]], dict[str, dict[str, list[score.LetterScore]]]]:
    """Every letter scored: the clean reference, then each cell against it."""
    by_id = {e.id: e for e in base}
    clean_scores: dict[str, list[score.LetterScore]] = {
        condition: [score.score_letter(by_id[i], clean[condition][i]) for i in sorted(by_id)]
        for condition in CONDITIONS
    }
    clean_of = {condition: {s.base_id: s for s in clean_scores[condition]} for condition in CONDITIONS}
    cell_scores: dict[str, dict[str, list[score.LetterScore]]] = {}
    for cell, by_condition in cells.items():
        cell_scores[cell] = {
            condition: [
                score.score_letter(
                    perturbed[a.id], by_condition[condition][a.id], a, clean=clean_of[condition][a.base_id]
                )
                for a in plan[cell]
            ]
            for condition in CONDITIONS
        }
    return clean_scores, cell_scores


def read_noise_floor(path: Path | None) -> dict[str, tuple[int, int]] | None:
    """``{condition: (flips, items)}`` from a JSON file of ``{condition: {"k": …, "n": …}}`` or ``[k, n]``."""
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    floor: dict[str, tuple[int, int]] = {}
    for condition, value in data.items():
        k, n = (value["k"], value["n"]) if isinstance(value, Mapping) else value
        floor[str(condition)] = (int(k), int(n))
    return floor


def _read(path: Path) -> analysis.Run:
    try:
        return analysis.read_run(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise StressError(f"the noise floor's read {path} cannot be read: {type(exc).__name__}") from None


def noise_floor_from_runs(
    paths: Sequence[Path], *, model: str
) -> tuple[dict[str, tuple[int, int]] | None, dict[str, Any]]:
    """Per stress condition, ``(items whose answer is not the same in every read, items)`` over holdout4's complete
    results files — the final analysis's ``unstable`` count (``evals/analysis.py``) — and where it comes from (each
    read's file name, read number and sha256). No analysis runs and no frozen input is checked. With fewer than two
    reads there is no noise floor (``None``), and the source says so."""
    runs = [_read(path) for path in paths]
    reads: dict[int, analysis.Run] = {}
    for path, run in zip(paths, runs, strict=True):
        label = path.name
        if run.split != NOISE_FLOOR_SPLIT:
            raise StressError(f"{label}: a read of {run.split or 'no split'}, not of {NOISE_FLOOR_SPLIT}")
        if run.model != model:
            raise StressError(f"{label}: model {run.model or 'none'}, not {model}")
        if run.meta.get("partial"):
            raise StressError(f"{label}: a filtered run, not a complete read of {NOISE_FLOOR_SPLIT}")
        if not 1 <= run.repeat <= NOISE_FLOOR_READS:
            raise StressError(
                f"{label}: read {run.repeat} is not one of {NOISE_FLOOR_SPLIT}'s {NOISE_FLOOR_READS}"
            )
        if run.repeat in reads:
            raise StressError(f"{label}: read {run.repeat} of {NOISE_FLOOR_SPLIT} is given twice")
        missing = [c for c in CONDITIONS if c not in run.conditions]
        letters = {letter.entry_id for c in CONDITIONS if c in run.conditions for letter in run.letters[c]}
        unscored = [c for c in CONDITIONS if c in run.conditions and len(run.letters[c]) != len(letters)]
        if missing or unscored:
            raise StressError(
                f"{label}: not a complete read: no answers of {', '.join(missing or unscored)} for every letter"
            )
        reads[run.repeat] = run
    ordered = [reads[read] for read in sorted(reads)]
    source: dict[str, Any] = {
        "split": NOISE_FLOOR_SPLIT,
        "reads": sorted(reads),
        "files": [{"file": run.name, "repeat": run.repeat, "sha256": run.sha256} for run in ordered],
    }
    keys = {c: sorted(item.key for item in ordered[0].items[c]) for c in CONDITIONS} if ordered else {}
    for run in ordered[1:]:
        if any(sorted(item.key for item in run.items[c]) != keys[c] for c in CONDITIONS):
            raise StressError(f"{run.name}: the reads of {NOISE_FLOOR_SPLIT} do not hold the same items")
    if len(ordered) < 2:
        source["note"] = (
            f"{len(ordered)} read of {NOISE_FLOOR_SPLIT}: no noise floor (it needs two reads or more of the same items)"
        )
        return None, source
    floor: dict[str, tuple[int, int]] = {}
    for condition in CONDITIONS:
        table: dict[tuple[str, str, int], list[str | None]] = defaultdict(list)
        for run in ordered:
            for item in run.items[condition]:
                table[item.key].append(item.predicted)
        floor[condition] = stats.flip_rate(list(table.values()))
    return floor, source


def noise_floor_of_published(
    published: Path, *, model: str
) -> tuple[dict[str, tuple[int, int]] | None, dict[str, Any] | None]:
    """The noise floor a published stress file was made with, from the holdout4 files it names, found beside it and
    refused unless each is the same file (sha256); ``(None, None)`` when it names none."""
    try:
        source = (json.loads(published.read_text(encoding="utf-8")).get("meta") or {}).get(
            "noise_floor_source"
        )
    except (OSError, ValueError, AttributeError):
        return None, None
    if not isinstance(source, Mapping):
        return None, None
    paths = []
    for row in source.get("files") or []:
        path = published.parent / str(row.get("file"))
        if not path.exists():
            raise StressError(
                f"{published.name} took its noise floor from {path.name}, which is not beside it"
            )
        if hashlib.sha256(path.read_bytes()).hexdigest() != row.get("sha256"):
            raise StressError(
                f"{path.name} is not the file {published.name} took its noise floor from (its sha256 differs)"
            )
        paths.append(path)
    return noise_floor_from_runs(paths, model=model)


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def run_meta(
    *,
    run_date: str,
    model: str,
    cells: Sequence[str],
    live: bool,
    recorded_dir: Path,
    stress_doc: Mapping[str, Any] | None,
    runs: Mapping[str, Mapping[str, Any]],
    today: date | None = None,
    noise_floor_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The results' ``meta``: ``today`` is the day the cells were built for and recorded on (a replay builds them
    again for it); ``noise_floor_source`` names the reads the noise floor comes from."""
    keep = ("backend", "commit", "fingerprints", "cli_version", "dirty", "repeat", "dataset")
    return {
        "date": run_date,
        "model": model,
        "conditions": list(CONDITIONS),
        "cells": list(cells),
        "backend": {"clean": "replay", **{cell: "live" if live else "replay" for cell in cells}},
        "commit": _commit(),
        "fingerprints": {condition: conditions.fingerprint(condition, model) for condition in CONDITIONS},
        "seed": build.SEED,
        "base_splits": list(build.BASE_SPLITS),
        "dataset_manifest_sha256": _sha(build.DATASET_MANIFEST),
        "stress_manifest_sha256": _sha(build.STRESS_MANIFEST),
        "templates_sha256": stress_doc.get("templates_sha256") if stress_doc else None,
        "recorded_dir": _relative(recorded_dir),
        # the day the cells were built for, the day they are recorded (``--today``): a replay builds them again for it
        **({"today": today.isoformat()} if today is not None else {}),
        **({"noise_floor_source": dict(noise_floor_source)} if noise_floor_source is not None else {}),
        "script": SCRIPT,
        "runs": {name: {key: meta.get(key) for key in keep if key in meta} for name, meta in runs.items()},
    }


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(build.EVALS_DIR.parent).as_posix()
    except ValueError:
        return path.name


def results_path(out: Path, run_date: str, model: str) -> Path:
    return out / report.results_filename(run_date, model, "stress")


def _refuse_to_replace_a_recording(path: Path, live: bool) -> None:
    if live or not path.exists():
        return
    try:
        backend = json.loads(path.read_text(encoding="utf-8")).get("meta", {}).get("backend", {})
    except (OSError, ValueError, AttributeError):
        return
    if isinstance(backend, Mapping) and "live" in backend.values():
        raise StressError(
            f"{path} holds a live recording, which a replay never overwrites: pass another --out"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.eval_perturb", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--cells", type=parse_cells, default=list(build.CELLS), help="I1, D1 or I1,D1 (default)"
    )
    parser.add_argument(
        "--list-base", action="store_true", help="print the base set and the assignment (counts)"
    )
    parser.add_argument("--clean-only", action="store_true", help="score the clean reference alone")
    parser.add_argument("--build-only", action="store_true", help="build the files and stop")
    parser.add_argument(
        "--write-manifest", action="store_true", help="write evals/perturb/manifest.json from this build"
    )
    parser.add_argument("--templates", type=Path, default=tpl.TEMPLATES_PATH, help="the templates file")
    parser.add_argument("--build-dir", type=Path, default=build.BUILD_DIR, help="where the files are built")
    parser.add_argument("--live", action="store_true", help="record the cells (never the clean reference)")
    parser.add_argument(
        "--recorded-dir", type=Path, default=STRESS_RECORDED_DIR, help="the cells' recordings"
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"the recordings' model (default: {DEFAULT_MODEL})"
    )
    parser.add_argument("--concurrency", type=int, default=2, help="letters in flight (default: 2)")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds per model call (default: 300)")
    parser.add_argument(
        "--max-cost-usd", type=float, help="stop starting calls at this cost (needs the harness)"
    )
    parser.add_argument("--wait-on-limit", type=float, metavar="HOURS", help="wait through a usage limit")
    floor = parser.add_mutually_exclusive_group()
    floor.add_argument(
        "--noise-floor",
        type=Path,
        help="per-condition flip rate of holdout4's three reads (JSON {condition: {k, n}})",
    )
    floor.add_argument(
        "--noise-floor-from-runs",
        type=Path,
        nargs="+",
        metavar="READ",
        help=f"the noise floor from {NOISE_FLOOR_SPLIT}'s complete results files (read 1, 2 and 3; two at least, "
        "else the results file says there is none); a --check without it reads the files the published file names",
    )
    parser.add_argument("--date", dest="run_date", default=date.today().isoformat(), help="for the file name")
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="build the cells for this day, the day they are recorded: every letter's simulated today (refused "
        "outside the days the letters are written for, or once a deadline has passed)",
    )
    parser.add_argument("--out", type=Path, help=f"results folder (a live run: default {RESULTS_DIR.name}/)")
    parser.add_argument(
        "--check", type=Path, metavar="PUBLISHED", help="fail unless the run equals this file"
    )
    parser.add_argument("--quiet", action="store_true", help="no per-letter progress lines")
    add_stop_arguments(parser)
    return parser


def _base_and_plan(cells: Sequence[str]) -> tuple[list[Entry], dict[str, list[build.Assignment]]]:
    """The base letters and what each gets: the same on every day (the stress manifest names none)."""
    base = build.base_set(load_manifest(build.DATASET_MANIFEST))
    return base, build.assign_cells(base, dataset_dir=build.DATASET_MANIFEST.parent, cells=cells)


async def _run(args: argparse.Namespace) -> int:
    say: Callable[[str], None] = (
        (lambda _message: None)
        if args.quiet
        else (lambda message: print(message, file=sys.stderr, flush=True))
    )
    floor: dict[str, tuple[int, int]] | None = None
    floor_source: dict[str, Any] | None = None
    if not args.list_base:
        # the noise floor first: a read that does not fit stops the run before anything is built or called
        if args.noise_floor_from_runs:
            floor, floor_source = noise_floor_from_runs(args.noise_floor_from_runs, model=args.model)
        elif args.noise_floor is not None:
            floor = read_noise_floor(args.noise_floor)
        elif args.check is not None:
            floor, floor_source = noise_floor_of_published(args.check, model=args.model)
    if args.list_base:
        base, plan = _base_and_plan(args.cells)
        print(json.dumps({"base": [e.id for e in base], **build.plan_counts(plan, base)}, indent=1))
        return 0
    # every refusal before any work: no build, no replay, no call
    options = harness_options(
        live=args.live,
        max_cost_usd=args.max_cost_usd,
        wait_on_limit=args.wait_on_limit,
        stop=Stop.from_args(args),
    )
    if args.out is None and not args.live and not args.build_only:
        raise StressError("a replay needs --out <folder>, so it never lands beside the published file")
    if args.live and not (tpl.TEMPLATES_PATH.exists() and build.STRESS_MANIFEST.exists()):
        raise StressError(
            "recording needs the committed templates and stress manifest (evals/perturb/templates.json and "
            "manifest.json, committed after the code freeze)"
        )
    base, plan = _base_and_plan(args.cells)
    if args.today is not None:
        build.check_day(base, args.today)
    stress_doc: dict[str, Any] | None = None
    if not args.clean_only:
        templates = tpl.load_templates(args.templates)
        say(f"building {len(base)} letters × {len(args.cells)} cell(s) into {args.build_dir} …")
        stress_doc = build.build(templates=templates, out=args.build_dir, cells=args.cells, today=args.today)
        if args.write_manifest:
            build.write_manifest(stress_doc)
            say(f"stress manifest → {build.STRESS_MANIFEST}")
        elif build.STRESS_MANIFEST.exists():
            differences = build.check_build(
                stress_doc, json.loads(build.STRESS_MANIFEST.read_text(encoding="utf-8"))
            )
            if differences:
                raise StressError(
                    f"the build differs from evals/perturb/manifest.json in {len(differences)} place(s), e.g. "
                    f"{differences[0]}"
                )
        if args.build_only:
            return 0
    out = args.out or RESULTS_DIR
    path = results_path(out, args.run_date, args.model)
    _refuse_to_replace_a_recording(path, args.live)
    runs: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="ordnung-stress-") as tmp:
        work = Path(tmp)
        say("clean reference: the base letters' own recordings, replayed …")
        clean, runs["clean"] = await clean_reference(base, model=args.model, work=work, quiet=args.quiet)
        cells: dict[str, dict[str, dict[str, Prediction]]] = {}
        if stress_doc is not None:
            recorded = [
                entry
                for entry in load_manifest(args.build_dir / "manifest.json")
                if entry.split in {f"stress-{cell}" for cell in args.cells}
            ]
            with recording_session(
                live=args.live,
                options=options,
                model=args.model,
                recorded_dir=args.recorded_dir,
                entries=recorded,
                say=say,
            ) as shared:
                for cell in args.cells:
                    say(f"{cell}: {'recording' if args.live else 'replaying'} …")
                    cells[cell], runs[cell] = await cell_predictions(
                        cell,
                        build_dir=args.build_dir,
                        model=args.model,
                        recorded_dir=args.recorded_dir,
                        live=args.live,
                        concurrency=args.concurrency,
                        timeout_s=args.timeout,
                        options=options,
                        work=work,
                        quiet=args.quiet,
                        shared=shared,
                    )
    perturbed = (
        {e.id: e for e in load_manifest(args.build_dir / "manifest.json")} if stress_doc is not None else {}
    )
    clean_scores, cell_scores = score_all(base, plan, clean, cells, perturbed)
    counts = build.plan_counts(plan, base)
    document = score.stress_results(
        meta=run_meta(
            run_date=args.run_date,
            model=args.model,
            cells=list(cells),
            live=args.live,
            recorded_dir=args.recorded_dir,
            stress_doc=stress_doc,
            runs=runs,
            today=args.today,
            noise_floor_source=floor_source,
        ),
        base={key: counts[key] for key in ("letters", "scored_items", "by_split", "by_family")}
        | {"ids": [e.id for e in base]},
        clean=clean_scores,
        cells=cell_scores,
        noise_floor=floor,
    )
    report.write_json(path, document)
    if floor is not None:  # stdout only: the recording's log seals it
        values = ", ".join(f"{condition} {k}/{n}" for condition, (k, n) in floor.items())
        print(f"noise floor (unstable items over {NOISE_FLOOR_SPLIT}'s reads): {values}")
    elif floor_source is not None:
        print(f"noise floor: none ({floor_source.get('note')})")
    for cell, by_condition in document["cells"].items():
        for condition, summary in by_condition.items():
            extra = "".join(
                f" {name} {summary[name]['k']}/{summary[name]['n']}"
                for name in ("targeted", "taken", "warned")
                if summary.get(name)
            )
            print(
                f"{cell:<6} {condition:<15} right {summary['right']['k']}/{summary['right']['n']} "
                f"harmful {summary['harmful']['k']}{extra}",
                file=sys.stderr,
            )
    print(f"results → {path}", file=sys.stderr)
    if args.check is not None:
        differences = score.compare(json.loads(args.check.read_text(encoding="utf-8")), document)
        for difference in differences[:10]:
            print(f"differs: {difference}", file=sys.stderr)
        if differences:
            print(f"the replay differs from {args.check} in {len(differences)} place(s)", file=sys.stderr)
            return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.live and args.max_cost_usd is None:
        parser.error("--live needs --max-cost-usd (the run's stop)")
    if args.live and (args.clean_only or args.build_only or args.check is not None):
        parser.error("--live records the cells: not with --clean-only, --build-only or --check")
    try:
        Stop.from_args(args)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        return asyncio.run(_run(args))
    except StressStopped as exc:
        print(f"{exc}", file=sys.stderr)
        return STOPPED
    except (StressError, tpl.TemplateError, build.BuildError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
