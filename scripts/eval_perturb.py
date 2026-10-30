"""Build, replay (or record) and score the stress cells of the 0.4.0 evaluation (plan EV11; ``evals/perturb``).

Two cells on 48 held-out text letters of holdout, holdout2 and holdout3 (never holdout4): I1, one paragraph addressed
to an AI (shift, drop or re-route a deadline), and D1, one legally inert sentence that names a date. Conditions:
Ordnung and LLM + rules tool (the strongest baseline). The clean reference is the same letters' own recordings
(``evals/recorded``) replayed on this code; the cells' recordings live in ``evals/recorded/stress`` (``--recorded-dir``).
The results go to ``<out>/<date>-<model>-stress.json``: ids, dates, outcomes and numbers, never a letter's words.

Run it from the repository root::

    .venv/bin/python -m scripts.eval_perturb --list-base                 # the base set and what each letter gets
    .venv/bin/python -m scripts.eval_perturb --clean-only --out DIR      # the clean reference alone (no templates)
    .venv/bin/python -m scripts.eval_perturb --build-only [--write-manifest]   # the files (needs the templates)
    .venv/bin/python -m scripts.eval_perturb --out DIR [--check PUBLISHED]     # replay both cells and score them
    ORDNUNG_CLAUDE_BIN=<wrapper> .venv/bin/python -m scripts.eval_perturb --cells I1,D1 --live \\
        --recorded-dir evals/recorded/stress --max-cost-usd 17 --concurrency 2   # record (plan §7, step R7)

A replay calls no model (a missing recording is an error) and needs ``--out``, so it never lands beside the published
file; ``--check`` compares it with the published file and fails on any difference. Recording needs the templates and
the committed stress manifest (both written blind in EV8's commit A, before the pre-registration), a budget
(``--max-cost-usd``) and the recording harness that enforces it (``evals/harness.py``, plan EV3). The builder never
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
from collections.abc import Iterator, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from evals import conditions, report
from evals.perturb import build, score
from evals.perturb import templates as tpl
from evals.records import Entry, Prediction, load_manifest
from evals.run import DEFAULT_MODEL, RECORDED_DIR, RESULTS_DIR, RunConfig, _commit, live_setup, run_benchmark

STRESS_RECORDED_DIR = RECORDED_DIR / "stress"
CONDITIONS = score.CONDITIONS
SCRIPT = "scripts/eval_perturb.py"


class StressError(RuntimeError):
    """The stress run cannot go on (said in one line, never with a letter's text)."""


def parse_cells(text: str) -> list[str]:
    cells = [cell.strip() for cell in text.split(",") if cell.strip()]
    unknown = [cell for cell in cells if cell not in build.CELLS]
    if unknown or not cells:
        raise argparse.ArgumentTypeError(f"cells are {', '.join(build.CELLS)}, not {text!r}")
    return [cell for cell in build.CELLS if cell in cells]


def harness_options(
    *, live: bool, max_cost_usd: float | None, wait_on_limit: float | None, config_type: Any = RunConfig
) -> dict[str, Any]:
    """The recording harness's options for :class:`evals.run.RunConfig` (budget, waiting, the shared recorder lock),
    refused when this checkout has no harness: a live stress run never records without its budget stop."""
    fields = {field.name for field in dataclasses.fields(config_type)}
    wanted: dict[str, Any] = {"max_cost_usd": max_cost_usd, "wait_on_limit_hours": wait_on_limit}
    missing = sorted(name for name, value in wanted.items() if value is not None and name not in fields)
    if missing:
        raise StressError(
            f"{', '.join(missing)} need the recording harness (evals/harness.py, plan EV3), which this checkout "
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
    if run.results is None:
        problems = "; ".join(f"{p.condition} {p.entry_id}: {(p.error or '')[:120]}" for p in run.errors[:5])
        raise StressError(f"the {config.split} run failed: {problems or run.fatal or 'no results'}")
    return run.predictions, dict(run.results["meta"])


async def clean_reference(
    base: Sequence[Entry], *, model: str, work: Path, quiet: bool = True
) -> tuple[dict[str, dict[str, Prediction]], dict[str, Any]]:
    """The base letters' own recordings replayed on this code, for both conditions (never recorded)."""
    predictions: dict[str, dict[str, Prediction]] = {condition: {} for condition in CONDITIONS}
    meta: dict[str, Any] = {}
    for split in build.BASE_SPLITS:
        ids = sorted(e.id for e in base if e.split == split)
        config = RunConfig(
            split=split,
            models=[model],
            conditions=list(CONDITIONS),
            ids=ids,
            resume=False,
            write_results=False,
            write_docs=False,
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
    clean_scores = {
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
) -> dict[str, Any]:
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
    parser.add_argument(
        "--noise-floor", type=Path, help="per-condition flip rate of holdout4's three reads (JSON)"
    )
    parser.add_argument("--date", dest="run_date", default=date.today().isoformat(), help="for the file name")
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="build the cells for this day, the day they are recorded: every letter's simulated today (letters it "
        "cannot be read on — written later, or with its deadline passed — are left out of the base set)",
    )
    parser.add_argument("--out", type=Path, help=f"results folder (a live run: default {RESULTS_DIR.name}/)")
    parser.add_argument(
        "--check", type=Path, metavar="PUBLISHED", help="fail unless the run equals this file"
    )
    parser.add_argument("--quiet", action="store_true", help="no per-letter progress lines")
    return parser


async def _run(args: argparse.Namespace) -> int:
    say = (
        (lambda _message: None)
        if args.quiet
        else (lambda message: print(message, file=sys.stderr, flush=True))
    )
    entries = load_manifest(build.DATASET_MANIFEST)
    base = build.base_set(entries, today=args.today)
    plan = build.assign_cells(base, cells=args.cells, today=args.today)
    if args.list_base:
        print(json.dumps({"base": [e.id for e in base], **build.plan_counts(plan, base)}, indent=1))
        return 0
    # every refusal before any work: no build, no replay, no call
    options = harness_options(
        live=args.live, max_cost_usd=args.max_cost_usd, wait_on_limit=args.wait_on_limit
    )
    if args.out is None and not args.live and not args.build_only:
        raise StressError("a replay needs --out <folder>, so it never lands beside the published file")
    if args.live and not (tpl.TEMPLATES_PATH.exists() and build.STRESS_MANIFEST.exists()):
        raise StressError(
            "recording needs the committed templates and stress manifest (evals/perturb/templates.json and "
            "manifest.json, EV8 commit A)"
        )
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
        ),
        base={key: counts[key] for key in ("letters", "scored_items", "by_split", "by_family")}
        | {"ids": [e.id for e in base]},
        clean=clean_scores,
        cells=cell_scores,
        noise_floor=read_noise_floor(args.noise_floor),
    )
    report.write_json(path, document)
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
        parser.error("--live needs --max-cost-usd (the run's stop, plan §7)")
    if args.live and (args.clean_only or args.build_only or args.check is not None):
        parser.error("--live records the cells: not with --clean-only, --build-only or --check")
    try:
        return asyncio.run(_run(args))
    except (StressError, tpl.TemplateError, build.BuildError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
