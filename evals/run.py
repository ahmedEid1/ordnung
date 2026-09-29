"""Run the benchmark: ``python -m evals.run [--live] [--split test] [--models sonnet …]``.

By default every model call is **replayed** from ``evals/recorded/<model>/`` (fixtures keyed by
:func:`ordnung.llm.runtime.request_key`, like the app's demo fixtures); a missing recording is an
error, so a replay run recomputes the published numbers exactly and costs no tokens. ``--live``
calls the user's ``claude`` CLI and records every answer there (recordings are only allowed for the
benchmark's own SPECIMEN letters); calls already recorded are replayed, so an interrupted live run
resumes where it stopped (``--refresh`` records everything anew).

Replay is exact: a model failure (no structured output) is recorded and replayed as that failure,
and ``prompts.lock.json`` next to the recordings stores the digest of every app prompt they were
made with — the app's replay keys hold only prompt *versions*, so a run refuses to replay after a
prompt's text changed under the same version (the baselines' keys include their prompts' text).

Each (letter, condition) prediction is also cached in ``evals/results/cache/<run_id>/`` together
with a fingerprint of the prompts (full text) and code it depends on, under a name that includes the
letter's inputs (file hash, today, regions), so a rerun only redoes what changed or failed. Results go to ``evals/results/<YYYY-MM-DD>-<model>-<split>.json``; a complete,
error-free live run of every condition on the test split also regenerates ``docs/evals.md`` and its
chart. A run of some conditions never does (the page would lose the others' published rows): a
condition recorded again after the published run (``llm_rules_tool``, :data:`RECORD_AGAIN`) joins it
with ``python -m evals.report … --add-condition``, which keeps the held-out run's own conditions as
they were.

``ordnung eval`` delegates here via :func:`run_cli`.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from evals import __version__, report
from evals.conditions import (
    TOOLS_CONDITION,
    CallLog,
    MeteredBackend,
    PreparedDocument,
    fingerprint,
    ordnung_prompt_hashes,
    prepare_document,
    run_condition,
)
from evals.metrics import DEFAULT_RESAMPLES, DEFAULT_SEED, evaluate, scored_item_count
from evals.records import (
    CONDITIONS,
    SHORT_LABELS,
    ConditionName,
    Entry,
    Prediction,
    load_manifest,
    select_entries,
)
from ordnung.llm.base import (
    ClaudeAuthError,
    ClaudeBadOutput,
    ClaudeNotInstalled,
    ClaudeRateLimited,
    LLMBackend,
    LLMError,
    LLMRequest,
    LLMResponse,
    StreamEvent,
)
from ordnung.llm.claude_cli import ClaudeCLIBackend
from ordnung.llm.replay import RecordingBackend, ReplayBackend, fixture_path
from ordnung.llm.runtime import LLMService

EVALS_DIR = Path(__file__).resolve().parent
ROOT = EVALS_DIR.parent
DATASET_DIR = EVALS_DIR / "dataset"
MANIFEST_PATH = DATASET_DIR / "manifest.json"
RECORDED_DIR = EVALS_DIR / "recorded"
RESULTS_DIR = EVALS_DIR / "results"

DEFAULT_MODEL = "sonnet"
DEFAULT_SPLIT = "test"
DEFAULT_CONCURRENCY = 3
DEFAULT_TIMEOUT_S = 300.0

#: Errors after which further calls cannot succeed: stop scheduling, keep what is done.
FATAL_ERRORS = (ClaudeNotInstalled, ClaudeAuthError, ClaudeRateLimited)

Progress = Callable[[str], None]


@dataclass
class RunConfig:
    """Everything a benchmark run depends on (see ``python -m evals.run --help``)."""

    split: str = DEFAULT_SPLIT
    models: list[str] = field(default_factory=lambda: [DEFAULT_MODEL])
    conditions: list[ConditionName] = field(default_factory=lambda: list(CONDITIONS))
    families: list[str] | None = None
    ids: list[str] | None = None
    limit: int | None = None
    live: bool = False
    refresh: bool = False
    resume: bool = True
    concurrency: int = DEFAULT_CONCURRENCY
    timeout_s: float = DEFAULT_TIMEOUT_S
    run_id: str | None = None
    run_date: str | None = None
    write_docs: bool | None = None  # None: only for a complete test-split run without errors
    allow_errors: bool = False
    #: The CI gate checks Ordnung: the tool condition, whose recorded answers go missing on replay when
    #: the rules tools' descriptions change in code, is then left out with a warning (see
    #: :data:`GATE_MAY_LEAVE_OUT`); every other condition must still replay.
    gate_ordnung_only: bool = False
    #: Whether the results file is written: the CI gate's replay (thresholds, no ``--live``) only checks and
    #: writes nothing unless ``--results-dir`` is given (review round 3 of phase 2: running the gate locally
    #: left an untracked ``evals/results/<today>-sonnet-test.json`` in the tree).
    write_results: bool = True
    seed: int = DEFAULT_SEED
    resamples: int = DEFAULT_RESAMPLES
    manifest_path: Path = MANIFEST_PATH
    recorded_dir: Path = RECORDED_DIR
    results_dir: Path = RESULTS_DIR
    docs_path: Path = report.DOCS_PATH
    chart_path: Path = report.CHART_PATH

    @property
    def dataset_dir(self) -> Path:
        return self.manifest_path.parent

    @property
    def partial(self) -> bool:
        """Entries were filtered: the run is not the whole split."""
        return bool(self.families or self.ids or self.limit is not None)

    @property
    def every_condition(self) -> bool:
        """Every benchmark condition runs: a published page from fewer would drop the others' rows."""
        return set(CONDITIONS) <= set(self.conditions)

    @property
    def date(self) -> str:
        return self.run_date or date.today().isoformat()

    @property
    def effective_run_id(self) -> str:
        return self.run_id or f"{self.date}-{self.split}"


@dataclass
class ModelRun:
    """The outcome for one model."""

    model: str
    predictions: dict[str, dict[str, Prediction]]
    results: dict[str, Any] | None = None
    results_path: Path | None = None
    errors: list[Prediction] = field(default_factory=list)
    fatal: str | None = None
    #: Conditions left out of a gated replay because their recorded answers are missing.
    left_out: list[str] = field(default_factory=list)


@dataclass
class RunOutcome:
    runs: list[ModelRun]
    docs_path: Path | None = None
    chart_path: Path | None = None

    @property
    def ok(self) -> bool:
        return all(run.results is not None and run.fatal is None for run in self.runs)


# --------------------------------------------------------------------------------------------------
# Backends and cache
# --------------------------------------------------------------------------------------------------


def safe_name(model: str) -> str:
    """A model name usable as a directory name."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model)


class RecordedFailures:
    """Makes the model's own failures (``ClaudeBadOutput``) part of the recording.

    ``RecordingBackend`` writes only answers, so a call on which the live model returned no
    structured output (even after the CLI's retry) would replay as a *missing recording* — an
    infrastructure error that blocks the results — instead of the scored failure it was live. This
    wrapper stores such a failure next to the answers (``<key>.failure.json``) and replays it, so a
    replay reproduces the live run exactly. Timeouts, rate limits and other errors are never stored.
    """

    def __init__(self, inner: LLMBackend, root: Path, *, record: bool, replay: bool = True) -> None:
        self.inner = inner
        self.root = Path(root)
        self.record = record
        self.replay = replay
        self.name = inner.name

    def failure_path(self, req: LLMRequest) -> Path:
        return fixture_path(self.root, req).with_suffix(".failure.json")

    def recorded_failure(self, path: Path) -> str | None:
        """The recorded failure message at ``path``, if there is a readable one."""
        try:
            return str(json.loads(path.read_text(encoding="utf-8"))["error"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    async def complete(self, req: LLMRequest) -> LLMResponse:
        path = self.failure_path(req)
        failure = self.recorded_failure(path) if self.replay else None
        if failure is not None:
            raise ClaudeBadOutput(failure)
        try:
            response = await self.inner.complete(req)
        except ClaudeBadOutput as exc:
            if self.record:
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = {"request": {"purpose": req.purpose, "doc_ids": req.doc_ids}, "error": str(exc)}
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            raise
        if self.record:
            path.unlink(missing_ok=True)  # re-recorded successfully
        return response

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        async for event in self.inner.stream(req):
            yield event


def make_backend(config: RunConfig, model: str, allowed_doc_ids: set[str]) -> LLMBackend:
    """Replay (default; a miss raises ``ReplayMiss``) or live recording (replay-first unless refresh).

    Either way wrapped in :class:`RecordedFailures`, so recorded model failures replay as failures.
    """
    root = config.recorded_dir / safe_name(model)
    if not config.live:
        return RecordedFailures(ReplayBackend(root), root, record=False)
    recorder = RecordingBackend(
        ClaudeCLIBackend(concurrency=config.concurrency), root, allowed_doc_ids=allowed_doc_ids
    )
    if config.refresh:
        return RecordedFailures(recorder, root, record=True, replay=False)
    return RecordedFailures(ReplayBackend(root, fallback=recorder), root, record=True)


def entry_inputs(entry: Entry) -> str:
    """Digest of everything a condition reads from the manifest entry: the file, today, the regions.

    Part of the cache file name, so a regenerated letter (or a changed "today") with the same id is
    never answered from the cache.
    """
    inputs = {
        "sha256": entry.sha256,
        "media_type": entry.media_type,
        "photo": entry.photo,
        "today": entry.today,
        "authority_region": entry.authority_region,
        "recipient_region": entry.recipient_region,
    }
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:12]


def cache_path(config: RunConfig, model: str, condition: str, entry: Entry) -> Path:
    return (
        config.results_dir
        / "cache"
        / config.effective_run_id
        / safe_name(model)
        / condition
        / f"{entry.id}.{entry_inputs(entry)}.json"
    )


def load_cached(path: Path, expected_fingerprint: str) -> Prediction | None:
    """A cached prediction if it exists, is valid and was made by the same prompts and code."""
    try:
        prediction = Prediction.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError):
        return None
    if prediction.fingerprint != expected_fingerprint or prediction.error:
        return None
    return prediction


def save_cached(path: Path, prediction: Prediction) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(prediction.model_dump_json(indent=1), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------------------------------
# Recorded outputs and the prompts they were made with
# --------------------------------------------------------------------------------------------------

PROMPTS_LOCK = "prompts.lock.json"


def load_prompts_lock(root: Path) -> dict[str, dict[str, str]]:
    """``name → {version: digest}`` of the prompts the recordings in ``root`` were made with."""
    try:
        data = json.loads((root / PROMPTS_LOCK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def stale_prompts(root: Path, current: dict[str, tuple[str, str]]) -> list[str]:
    """Prompts whose text changed since they were recorded under the same version (replay would lie).

    The app's replay keys (:func:`ordnung.llm.runtime.request_key`) contain the prompt *version*, not
    its text, so an edit without a version bump would silently replay answers to the old prompt.
    """
    recorded = load_prompts_lock(root)
    return sorted(
        f"{name} (version {version})"
        for name, (version, digest) in current.items()
        if recorded.get(name, {}).get(version, digest) != digest
    )


def write_prompts_lock(root: Path, current: dict[str, tuple[str, str]]) -> None:
    lock = load_prompts_lock(root)
    for name, (version, digest) in current.items():
        lock.setdefault(name, {})[version] = digest
    root.mkdir(parents=True, exist_ok=True)
    (root / PROMPTS_LOCK).write_text(json.dumps(lock, indent=1, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------------------
# Predicting
# --------------------------------------------------------------------------------------------------


def _stderr(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


class _Documents:
    """Prepares each letter once (in a worker thread) and shares it between conditions."""

    def __init__(self, config: RunConfig, work_dir: Path) -> None:
        self.config = config
        self.work_dir = work_dir
        self._tasks: dict[str, asyncio.Future[PreparedDocument]] = {}

    async def get(self, entry: Entry) -> PreparedDocument:
        if entry.id not in self._tasks:
            self._tasks[entry.id] = asyncio.ensure_future(
                asyncio.to_thread(prepare_document, entry, self.config.dataset_dir, self.work_dir)
            )
        return await self._tasks[entry.id]


async def predict_model(
    config: RunConfig,
    model: str,
    entries: Sequence[Entry],
    backend: LLMBackend,
    *,
    progress: Progress | None = None,
) -> ModelRun:
    """Every selected condition on every selected letter for one model (bounded concurrency)."""
    say = progress or (lambda _message: None)
    fingerprints = {condition: fingerprint(condition, model) for condition in config.conditions}
    semaphore = asyncio.Semaphore(max(1, config.concurrency))
    stop = asyncio.Event()
    fatal: list[str] = []
    total = len(entries) * len(config.conditions)
    done = 0
    predictions: dict[str, dict[str, Prediction]] = {condition: {} for condition in config.conditions}

    with tempfile.TemporaryDirectory(prefix="ordnung-eval-") as work:
        documents = _Documents(config, Path(work))

        async def one(condition: ConditionName, entry: Entry) -> None:
            nonlocal done
            path = cache_path(config, model, condition, entry)
            cached = (
                load_cached(path, fingerprints[condition]) if config.resume and not config.refresh else None
            )
            status = "cached"
            if cached is not None:
                prediction = cached
            else:
                prediction = await _predict(condition, entry)
                status = "error" if prediction.error else "failed" if prediction.failed else "ok"
                if not prediction.error:
                    try:
                        save_cached(path, prediction)
                    except OSError as exc:  # the prediction still counts; only resuming loses it
                        say(f"warning: could not cache {condition} {entry.id}: {exc}")
            predictions[condition][entry.id] = prediction
            done += 1
            detail = f" — {prediction.error or prediction.failed}" if status in ("error", "failed") else ""
            say(
                f"[{done:>3}/{total}] {model} {condition:<15} {entry.id:<44} {status:<6} "
                f"{prediction.latency_ms / 1000:6.1f}s ${prediction.cost_usd:.4f}{detail[:160]}"
            )

        async def _predict(condition: ConditionName, entry: Entry) -> Prediction:
            async with semaphore:
                if stop.is_set():
                    return Prediction(
                        entry_id=entry.id, condition=condition, model=model, error=f"not run: {fatal[0]}"
                    )
                log = CallLog()
                llm = LLMService(MeteredBackend(backend, log, timeout_s=config.timeout_s))
                try:
                    document = await documents.get(entry)
                    prediction = await run_condition(condition, entry, document, llm, model=model)
                except FATAL_ERRORS as exc:
                    if not stop.is_set():
                        fatal.append(str(exc))
                        stop.set()
                    prediction = Prediction(
                        entry_id=entry.id, condition=condition, model=model, error=str(exc)
                    )
                except LLMError as exc:
                    prediction = Prediction(
                        entry_id=entry.id, condition=condition, model=model, error=str(exc)
                    )
                except Exception as exc:  # a bug in the evaluated code or the runner: report, don't hide
                    error = f"unexpected {type(exc).__name__}: {exc}"
                    prediction = Prediction(entry_id=entry.id, condition=condition, model=model, error=error)
                return prediction.model_copy(
                    update={"calls": log.calls, "fingerprint": fingerprints[condition]}
                )

        await asyncio.gather(*(one(condition, entry) for entry in entries for condition in config.conditions))

    errors = [p for by_entry in predictions.values() for p in by_entry.values() if p.error]
    return ModelRun(model=model, predictions=predictions, errors=errors, fatal=fatal[0] if fatal else None)


# --------------------------------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------------------------------


def _manifest_info(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    data = json.loads(raw)
    return {
        "name": data.get("name"),
        "version": data.get("version"),
        "manifest_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _commit() -> str | None:
    """The checked-out commit (read-only ``git rev-parse``), if available."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    return None


def run_meta(
    config: RunConfig,
    model: str,
    entries: Sequence[Entry],
    backend_label: str,
    *,
    left_out: Sequence[str] = (),
) -> dict[str, Any]:
    conditions = [condition for condition in config.conditions if condition not in left_out]
    meta: dict[str, Any] = {
        "date": config.date,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "model": model,
        "split": config.split,
        "conditions": conditions,
        "backend": backend_label,
        "run_id": config.effective_run_id,
        "entries": len(entries),
        "photos": sum(1 for e in entries if e.photo),
        "adversarial": sum(1 for e in entries if e.adversarial),
        "families": sorted({e.family for e in entries}),
        "scored_items": scored_item_count(entries),
        "partial": config.partial,
        "filters": {"families": config.families, "ids": config.ids, "limit": config.limit},
        "seed": config.seed,
        "resamples": config.resamples,
        "evals_version": __version__,
        "fingerprints": {condition: fingerprint(condition, model) for condition in conditions},
        "dataset": _manifest_info(config.manifest_path),
        "commit": _commit(),
    }
    if left_out:
        meta["left_out"] = {condition: "recorded answers missing on replay" for condition in left_out}
    return meta


async def run_benchmark(
    config: RunConfig, *, backend: LLMBackend | None = None, progress: Progress | None = None
) -> RunOutcome:
    """Predict, score and report for every configured model.

    ``backend`` overrides the replay/live backend (tests pass a ``FakeBackend``). Results and docs
    are written only for models whose run had no errors, unless ``allow_errors`` is set.
    """
    say = progress or (lambda _message: None)
    manifest = load_manifest(config.manifest_path)
    entries = select_entries(
        manifest, split=config.split, families=config.families, ids=config.ids, limit=config.limit
    )
    if not entries:
        raise ValueError("no benchmark entries match the selection")
    allowed = {entry.id for entry in manifest}
    outcome = RunOutcome(runs=[])
    current_prompts = ordnung_prompt_hashes() if "ordnung" in config.conditions else {}
    for model in config.models:
        recorded_root = config.recorded_dir / safe_name(model)
        if backend is None and current_prompts and not (config.live and config.refresh):
            stale = stale_prompts(recorded_root, current_prompts)
            if stale:
                raise ValueError(
                    f"the text of {', '.join(stale)} changed since the outputs in {recorded_root} were "
                    "recorded, but its version header did not — replaying would score answers to the old "
                    "prompt. Bump the version (then record with --live), or re-record with --live --refresh."
                )
        model_backend = backend or make_backend(config, model, allowed)
        label = backend.name if backend is not None else ("live" if config.live else "replay")
        say(f"{model}: {len(entries)} letters × {len(config.conditions)} conditions ({label})")
        started = time.perf_counter()
        run = await predict_model(config, model, entries, model_backend, progress=say)
        say(f"{model}: predictions done in {time.perf_counter() - started:.1f}s")
        if backend is None and config.live and current_prompts:
            write_prompts_lock(recorded_root, current_prompts)
        outcome.runs.append(run)
        if run.fatal:
            say(f"{model}: stopped — {run.fatal}")
            continue
        if config.gate_ordnung_only and not config.live:
            _leave_out_unrecorded(run, say)
        if run.errors and not config.allow_errors:
            _report_errors(run, config, say)
            continue
        evaluation = evaluate(entries, run.predictions, seed=config.seed, resamples=config.resamples)
        run.results = report.build_results(
            meta=run_meta(config, model, entries, label, left_out=run.left_out),
            entries=entries,
            predictions=run.predictions,
            evaluation=evaluation,
        )
        if not config.write_results:
            say(f"{model}: results not written (the gate's replay; pass --results-dir to keep them)")
            continue
        name = report.results_filename(config.date, model, config.split, partial=config.partial)
        run.results_path = report.write_json(config.results_dir / name, run.results)
        say(f"{model}: results → {run.results_path}")
    finished = [run.results for run in outcome.runs if run.results is not None]
    write_docs = config.write_docs
    if write_docs is None:
        # The published page only from a complete, error-free live run of every condition
        # (--allow-errors scores missing answers as empty — fine for a look, not for docs/evals.md; a
        # run of some conditions joins the published run with evals.report --add-condition). A replay
        # recomputes the numbers without touching the page, which may also show a re-scored run
        # (evals.report --rescored); pass --docs to force it.
        write_docs = (
            config.live
            and config.split == "test"
            and not config.partial
            and config.every_condition
            and outcome.ok
            and not any(run.errors for run in outcome.runs)
        )
    if write_docs and finished:
        outcome.docs_path, outcome.chart_path = report.write_docs(
            finished, docs_path=config.docs_path, chart_path=config.chart_path
        )
        say(f"docs → {outcome.docs_path}" + (f", chart → {outcome.chart_path}" if outcome.chart_path else ""))
    return outcome


REPLAY_MISS = "no recorded response"
#: How to record a condition added after the published run again, and publish it (docs never change
#: on the recording itself: it runs one condition). Recording costs tokens: see ``docs/evals.md``.
RECORD_AGAIN = (
    "record it again with `python -m evals.run --live --split dev --conditions {condition}` and then "
    "`--split test` (neither rewrites docs/evals.md), then add the test run to the published one: "
    "`python -m evals.report evals/results/<run>.json --rescored evals/results/<run>-rescored.json "
    "--add-condition {condition}=evals/results/<new run>.json --note <finding>.md`"
)
#: The only condition a gated replay may leave out: its replay key includes the rules tools' Python
#: docstrings and schemas, which change with the code. The published baselines' prompts are files
#: that must not change unnoticed, so their misses still fail the gate.
GATE_MAY_LEAVE_OUT = frozenset({TOOLS_CONDITION})


def _leave_out_unrecorded(run: ModelRun, say: Progress) -> None:
    """Drop from ``run`` a :data:`GATE_MAY_LEAVE_OUT` condition that misses recorded answers (a gated replay).

    The gate checks Ordnung's numbers; the tool condition misses every answer on replay once a tool
    description or the ``DateSpec`` schema changed since it was recorded, and that must not fail the
    gate. It is named, loudly, instead. Ordnung's own misses, the other baselines' misses (a changed
    ``llm_only`` or rules-text prompt: their published numbers must keep replaying) and every other
    error still fail the run.
    """
    missing: dict[str, int] = {}
    for prediction in run.errors:
        if prediction.condition in GATE_MAY_LEAVE_OUT and REPLAY_MISS in (prediction.error or ""):
            missing[prediction.condition] = missing.get(prediction.condition, 0) + 1
    for condition, count in sorted(missing.items()):
        say(
            f"warning: {run.model}: {condition} has no recorded answer for {count} letter(s) — its prompt "
            "or tool definitions changed since it was recorded. It is left out of this gated run (the gate "
            f"checks Ordnung only); {RECORD_AGAIN.format(condition=condition)}."
        )
        del run.predictions[condition]
    run.left_out = sorted(missing)
    run.errors = [prediction for prediction in run.errors if prediction.condition not in missing]


def _report_errors(run: ModelRun, config: RunConfig, say: Progress) -> None:
    say(f"{run.model}: {len(run.errors)} prediction(s) failed to run — no results written:")
    for prediction in run.errors[:10]:
        say(f"  {prediction.condition} {prediction.entry_id}: {prediction.error}")
    if any(REPLAY_MISS in (p.error or "") for p in run.errors) and not config.live:
        say(
            f"  Recorded outputs are missing in {config.recorded_dir / safe_name(run.model)} — "
            "record them with --live, or pass --allow-errors to score the missing ones as empty."
        )


def summary_lines(outcome: RunOutcome) -> list[str]:
    """A short terminal summary of the headline metrics."""
    lines = []
    for run in outcome.runs:
        if run.results is None:
            continue
        lines.append(f"{run.model} — due-date accuracy [95 % CI], dangerous late, cost/letter:")
        for condition, metrics in run.results["metrics"].items():
            lines.append(
                f"  {SHORT_LABELS.get(condition, condition):<18} {report.rate(metrics['due_date_accuracy']):<26} "
                f"late {report.rate(metrics['dangerous_late_rate'], ci=False):<9} "
                f"{report.usd(metrics['cost_usd']['mean'])}"
            )
    return lines


def gate_failures(
    outcome: RunOutcome, *, min_accuracy: float | None = None, max_dangerous_late: float | None = None
) -> list[str]:
    """Why Ordnung's replayed numbers miss the CI thresholds (an empty list when they pass)."""
    failures = []
    for run in outcome.runs:
        metrics = (run.results or {}).get("metrics", {}).get("ordnung")
        if metrics is None:
            continue
        accuracy = metrics["due_date_accuracy"].get("value")
        late = metrics["dangerous_late_rate"].get("value")
        if min_accuracy is not None and (accuracy is None or accuracy < min_accuracy):
            failures.append(
                f"{run.model}: Ordnung due-date accuracy {report.pct(accuracy)} < {report.pct(min_accuracy)}"
            )
        if max_dangerous_late is not None and (late is None or late > max_dangerous_late):
            failures.append(
                f"{run.model}: Ordnung dangerous-late rate {report.pct(late)} > {report.pct(max_dangerous_late)}"
            )
    return failures


# --------------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run",
        description="Ordnung's deadline benchmark: Ordnung vs LLM only, LLM + rules text and LLM + rules tool "
        "(SPEC § 17).",
    )
    parser.add_argument("--live", action="store_true", help="call the claude CLI and record its answers")
    parser.add_argument("--refresh", action="store_true", help="with --live: record every call anew")
    parser.add_argument(
        "--split", choices=["dev", "test"], default=DEFAULT_SPLIT, help="dataset split (default: test)"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="model alias or id (default: sonnet)")
    parser.add_argument(
        "--models", nargs="+", metavar="MODEL", help="compare several models (overrides --model)"
    )
    parser.add_argument(
        "--conditions", nargs="+", choices=CONDITIONS, help="conditions to run (default: all)"
    )
    parser.add_argument("--families", nargs="+", metavar="FAMILY", help="only these template families")
    parser.add_argument("--ids", nargs="+", metavar="ENTRY", help="only these entry ids")
    parser.add_argument("--limit", type=int, help="only the first N selected letters")
    parser.add_argument(
        "--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="letters in flight (default: 3)"
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_S, help="seconds per model call (default: 300)"
    )
    parser.add_argument(
        "--run-id", help="cache directory name under evals/results/cache/ (default: <date>-<split>)"
    )
    parser.add_argument("--date", dest="run_date", help="date for the results file name (default: today)")
    parser.add_argument("--no-resume", dest="resume", action="store_false", help="ignore cached predictions")
    docs = parser.add_mutually_exclusive_group()
    docs.add_argument(
        "--docs", dest="write_docs", action="store_true", default=None, help="always regenerate docs/evals.md"
    )
    docs.add_argument(
        "--no-docs", dest="write_docs", action="store_false", help="never regenerate docs/evals.md"
    )
    parser.add_argument("--allow-errors", action="store_true", help="write results even if some calls failed")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="bootstrap seed")
    parser.add_argument(
        "--resamples", type=int, default=DEFAULT_RESAMPLES, help="bootstrap resamples (default: 2000)"
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--recorded-dir", type=Path, default=RECORDED_DIR, help="recorded outputs root")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help=f"results directory (default: {RESULTS_DIR.name}/; the gate's replay writes none unless given)",
    )
    parser.add_argument("--docs-path", type=Path, default=report.DOCS_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--chart-path", type=Path, default=report.CHART_PATH, help=argparse.SUPPRESS)
    parser.add_argument("--quiet", action="store_true", help="no per-letter progress lines")
    parser.add_argument(
        "--min-accuracy",
        type=float,
        metavar="RATE",
        help="fail unless Ordnung's due-date accuracy is at least RATE (a gate on Ordnung: on replay, the "
        "rules-tool condition without recorded answers is left out with a warning)",
    )
    parser.add_argument(
        "--max-dangerous-late",
        type=float,
        metavar="RATE",
        help="fail if Ordnung's dangerous-late rate is above RATE",
    )
    return parser


def config_from_args(ns: argparse.Namespace) -> RunConfig:
    if ns.run_date:
        date.fromisoformat(ns.run_date)
    return RunConfig(
        split=ns.split,
        models=list(ns.models or [ns.model]),
        conditions=list(ns.conditions or CONDITIONS),
        families=ns.families,
        ids=ns.ids,
        limit=ns.limit,
        live=ns.live,
        refresh=ns.refresh,
        resume=ns.resume,
        concurrency=ns.concurrency,
        timeout_s=ns.timeout,
        run_id=ns.run_id,
        run_date=ns.run_date,
        write_docs=ns.write_docs,
        allow_errors=ns.allow_errors,
        seed=ns.seed,
        resamples=ns.resamples,
        manifest_path=ns.manifest,
        recorded_dir=ns.recorded_dir,
        results_dir=ns.results_dir or RESULTS_DIR,
        docs_path=ns.docs_path,
        chart_path=ns.chart_path,
    )


def run_cli(args: Sequence[str] | None = None, *, backend: LLMBackend | None = None) -> int:
    """Entry point for ``python -m evals.run`` and ``ordnung eval`` (``args`` without the program name).

    Returns the exit code: 0 on success, 1 if predictions failed or the run stopped early.
    """
    parser = build_parser()
    ns = parser.parse_args(list(args) if args is not None else None)
    try:
        config = config_from_args(ns)
    except ValueError as exc:
        parser.error(str(exc))
    if config.refresh and not config.live:
        parser.error("--refresh needs --live")
    # With thresholds this is the CI gate, which checks Ordnung: the tool condition may lack recordings.
    config.gate_ordnung_only = ns.min_accuracy is not None or ns.max_dangerous_late is not None
    config.write_results = config.live or not config.gate_ordnung_only or ns.results_dir is not None
    progress: Progress = (lambda _message: None) if ns.quiet else _stderr
    try:
        outcome = asyncio.run(run_benchmark(config, backend=backend, progress=progress))
    except ValueError as exc:
        _stderr(f"error: {exc}")
        return 1
    for line in summary_lines(outcome):
        _stderr(line)
    failures = gate_failures(outcome, min_accuracy=ns.min_accuracy, max_dangerous_late=ns.max_dangerous_late)
    for run in outcome.runs:
        for condition in run.left_out:
            _stderr(
                f"warning: {run.model}: left out of the gate, recorded answers missing: {condition} — "
                f"{RECORD_AGAIN.format(condition=condition)}"
            )
    for line in failures:
        _stderr(f"threshold missed: {line}")
    return 0 if outcome.ok and not failures else 1


if __name__ == "__main__":
    raise SystemExit(run_cli())
