"""Build, snapshot, open and check the demo database (SPEC §16, §21 privacy).

* :func:`build_demo` creates a fresh demo data directory: the persona's profile, ``settings.demo``,
  the simulated today (meta ``simulated_today``), then every sample that is *not* in the tray, read
  one by one in manifest order through the real pipeline with the manifest's received dates; then
  the day's triggers, the weekly review and the brief. Backends: ``replay`` — strict replay of the
  recorded fixtures; ``record`` — replay what exists and record the rest with the live ``claude``
  CLI, refusing any document that is not a sample. Recording also plays every combination of opened
  tray letters and asks the suggested questions in each, so the demo can answer them whichever
  letters the visitor opened. ``rebuild=True`` then writes the ``demo_db`` snapshot.
* :func:`prepare_demo` is what ``ordnung demo`` runs: keep a current demo folder, else copy the
  snapshot (instant), else rebuild from the fixtures.
* :func:`check_demo` (``ordnung demo --check``, CI) rebuilds twice with strict replay and checks:
  zero misses, identical canonical dumps, fixtures valid against the current output models and
  referencing sample documents only, every Idea reference and recorded citation resolves, and every
  recorded Ask answer's tool results are what Ordnung's tools give on that ledger today.
"""

from __future__ import annotations

import asyncio
import contextlib
import difflib
import hashlib
import itertools
import json
import logging
import os
import shutil
import sqlite3
import tempfile
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from platformdirs import user_data_dir
from pydantic import BaseModel, ValidationError

from ordnung import __version__, clock
from ordnung.app_context import AppContext, build_context
from ordnung.assistant.ask import ask_stream, record_label
from ordnung.assistant.citations import parse_citations
from ordnung.config import PACKAGE_DIR, Paths, fixtures_dir
from ordnung.db.migrate import latest_version
from ordnung.db.store import Store
from ordnung.demo import MANIFEST_NAME, DemoError, Manifest, SampleDocument, load_manifest, samples_root
from ordnung.demo.tour import (
    ASKS_FILE,
    REPLAY_MISS_PREFIX,
    add_sample,
    open_tray_item,
    read_sample,
    reset_demo_state,
    suggested_questions,
)
from ordnung.ingest.pipeline import describe_error
from ordnung.llm.base import LLMBackend, LLMError, LLMRequest, LLMResponse, ReplayMiss, StreamEvent
from ordnung.llm.claude_cli import extract_json
from ordnung.llm.replay import RecordingBackend, ReplayBackend, fixture_path
from ordnung.locking import LOCK_NAME
from ordnung.models import (
    AppSettings,
    BriefOutput,
    CaptureOutput,
    DocumentExtraction,
    DraftOutput,
    Profile,
    ReviewOutput,
    TranscriptionOutput,
)
from ordnung.secretary.brief import generate_brief
from ordnung.secretary.review import run_review
from ordnung.tick import SIMULATED_TODAY_KEY, DailyTick, local_today

log = logging.getLogger(__name__)

BackendKind = Literal["replay", "record"]

MARKER_NAME = ".ordnung-demo"
VERSION_NAME = "VERSION"
DB_NAME = "ordnung.db"
COPIED_DIRS = ("files", "derived")
DEFAULT_SNAPSHOT = PACKAGE_DIR / "demo" / "demo_db"
OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "extract": DocumentExtraction,
    "transcribe": TranscriptionOutput,
    "review": ReviewOutput,
    "brief": BriefOutput,
    "draft": DraftOutput,
    "capture": CaptureOutput,
}
DUMP_TABLES = (
    "meta",
    "parties",
    "cases",
    "documents",
    "pages",
    "contracts",
    "items",
    "suggestions",
    "activity",
    "llm_calls",
    "llm_cache",
    "trace_spans",
)
VOLATILE_FIELDS = frozenset(
    {
        "ts",
        "created_at",
        "updated_at",
        "processed_at",
        "ai_processed_at",
        "generated_at",
        "completed_at",
        "sent_at",
        "job_id",  # jobs get random ids; a trace's own ids and times are the demo's (ordnung.trace.runs)
    }
)
MAX_DIFF_LINES = 12


# --------------------------------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DemoBuild:
    """Outcome of :func:`build_demo`."""

    data_dir: Path
    version: str
    documents: int
    asks: int
    snapshot: Path | None = None
    pruned: int = 0


@dataclass(frozen=True)
class DemoPrepared:
    """Outcome of :func:`prepare_demo`: where the demo is and where it came from."""

    data_dir: Path
    source: Literal["existing", "snapshot", "fixtures"]
    version: str


@dataclass
class DemoCheck:
    """Outcome of :func:`check_demo`; ``problems`` fail the check, ``warnings`` do not."""

    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    documents: int = 0
    fixtures: int = 0
    asks: int = 0
    ideas: int = 0

    @property
    def ok(self) -> bool:
        """Every check passed."""
        return not self.problems


# --------------------------------------------------------------------------------------------------
# locations, versions and markers
# --------------------------------------------------------------------------------------------------


def default_demo_dir() -> Path:
    """Where ``ordnung demo`` keeps its data: ``ORDNUNG_DEMO_HOME`` or the platform's ``ordnung-demo``.

    Never the person's own data directory (``ORDNUNG_HOME`` is ignored on purpose).
    """
    env = os.environ.get("ORDNUNG_DEMO_HOME")
    return Path(env).expanduser().resolve() if env else Path(user_data_dir("ordnung-demo", appauthor=False))


def snapshot_dir() -> Path:
    """The prebuilt demo database (``ORDNUNG_DEMO_DB`` overrides the packaged ``demo/demo_db``)."""
    env = os.environ.get("ORDNUNG_DEMO_DB")
    return Path(env).expanduser() if env else DEFAULT_SNAPSHOT


def _fixtures_root(fixtures: str | Path | None) -> Path:
    return Path(fixtures) if fixtures is not None else fixtures_dir()


def fixture_files(fixtures: str | Path | None = None) -> list[Path]:
    """Every recorded fixture file, sorted."""
    root = _fixtures_root(fixtures)
    return sorted(root.rglob("*.json")) if root.is_dir() else []


def demo_version(*, samples: str | Path | None = None, fixtures: str | Path | None = None) -> str:
    """Hash of everything a demo build depends on: code and schema version, manifest, questions, fixtures."""
    digest = hashlib.sha256(f"ordnung {__version__}; schema {latest_version()}\n".encode())
    for path in (samples_root(samples) / MANIFEST_NAME, ASKS_FILE):
        if path.is_file():
            digest.update(path.read_bytes())
    root = _fixtures_root(fixtures)
    for path in fixture_files(root):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()[:32]


def read_demo_version(data_dir: Path) -> str | None:
    """The version recorded in a demo folder's marker (``None``: not a demo folder)."""
    try:
        marker = json.loads((data_dir / MARKER_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return str(marker.get("version") or "") if isinstance(marker, dict) else None


def is_demo_dir(data_dir: Path) -> bool:
    """Whether ``data_dir`` is a demo folder (made by :func:`build_demo` or :func:`prepare_demo`)."""
    return read_demo_version(data_dir) is not None


def _write_marker(data_dir: Path, version: str) -> None:
    payload = {"kind": "ordnung-demo", "version": version}
    (data_dir / MARKER_NAME).write_text(json.dumps(payload) + "\n", encoding="utf-8")


def snapshot_version(snapshot: Path) -> str | None:
    """The version of a demo snapshot (``None`` if there is none)."""
    try:
        return (snapshot / VERSION_NAME).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _is_empty(path: Path) -> bool:
    return not path.exists() or all(child.name == LOCK_NAME for child in path.iterdir())


def _clear(data_dir: Path) -> None:
    """Empty a demo folder for a rebuild (keeping the lock file of the process that holds it)."""
    if not _is_empty(data_dir) and not is_demo_dir(data_dir):
        raise DemoError(
            f"{data_dir} holds other data, not the demo — refusing to overwrite it. "
            "Choose an empty folder with --data-dir."
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    for child in data_dir.iterdir():
        if child.name == LOCK_NAME:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


# --------------------------------------------------------------------------------------------------
# copying data folders (sqlite backup, so a WAL is never lost)
# --------------------------------------------------------------------------------------------------


def _backup_db(source: Path, target: Path, *, compact: bool) -> None:
    read_only = not os.access(source, os.W_OK)
    uri = f"{source.resolve().as_uri()}?mode=ro" if read_only else str(source)
    with (
        contextlib.closing(sqlite3.connect(uri, uri=read_only)) as src,
        contextlib.closing(sqlite3.connect(target)) as dst,
    ):
        src.backup(dst)
        if compact:
            dst.execute("PRAGMA journal_mode=DELETE")
            dst.execute("VACUUM")


def copy_data(source: Path, target: Path, *, compact: bool = False) -> None:
    """Copy a data folder's database, originals and page images into ``target``.

    ``compact`` writes a single-file database (no WAL) — the form the committed snapshot has.
    """
    database = source / DB_NAME
    if not database.is_file():
        raise DemoError(f"There is no demo database in {source}.")
    target.mkdir(parents=True, exist_ok=True)
    _backup_db(database, target / DB_NAME, compact=compact)
    for name in COPIED_DIRS:
        if (source / name).is_dir():
            shutil.copytree(source / name, target / name, dirs_exist_ok=True)


def write_snapshot(data_dir: Path, snapshot: Path, version: str) -> Path:
    """Replace the demo snapshot with a copy of ``data_dir`` and stamp it with ``version``."""
    snapshot.mkdir(parents=True, exist_ok=True)
    for name in (DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm", VERSION_NAME, *COPIED_DIRS):
        path = snapshot / name
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    copy_data(data_dir, snapshot, compact=True)
    (snapshot / VERSION_NAME).write_text(version + "\n", encoding="utf-8")
    return snapshot


# --------------------------------------------------------------------------------------------------
# backends
# --------------------------------------------------------------------------------------------------


def _describe(req: LLMRequest) -> str:
    docs = f" · documents {', '.join(req.doc_ids)}" if req.doc_ids else ""
    return f"{req.purpose} ({(req.cache_key or req.prompt)[:120]}){docs}"


class _Tracked:
    """Wraps the build's backend: remembers replay misses, every fixture file the build used and the
    tool calls of each Ask turn (``asks``: fixture file → its tool events)."""

    def __init__(self, inner: LLMBackend, fixtures: Path) -> None:
        self.inner = inner
        self.fixtures = fixtures
        self.name = inner.name
        self.misses: list[str] = []
        self.used: set[Path] = set()
        self.asks: list[tuple[Path, list[StreamEvent]]] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.used.add(fixture_path(self.fixtures, req))
        try:
            return await self.inner.complete(req)
        except ReplayMiss:
            self.misses.append(_describe(req))
            raise

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        path = fixture_path(self.fixtures, req)
        self.used.add(path)
        events: list[StreamEvent] = []
        if req.purpose == "ask":
            self.asks.append((path, events))
        async for event in self.inner.stream(req):
            if event.type == "error" and (event.error or "").startswith(REPLAY_MISS_PREFIX):
                self.misses.append(_describe(req))
            if event.type in ("tool_use", "tool_result"):
                events.append(event)
            yield event


@dataclass
class _BuildRun:
    """What one build produced; problems are collected (not raised) so a check can list them all."""

    backend: _Tracked
    failures: list[str] = field(default_factory=list)
    documents: int = 0
    asks: int = 0

    @property
    def problems(self) -> list[str]:
        return [*(f"replay miss: {miss}" for miss in self.backend.misses), *self.failures]


def recording_backend(
    data_dir: Path, fixtures: Path, allowed_doc_ids: set[str], live: LLMBackend | None = None
) -> LLMBackend:
    """Replay what is recorded; record the rest with ``live`` (default: the ``claude`` CLI).

    Refuses unless ``data_dir`` is a demo folder; the recorder itself refuses every request that
    carries a document outside ``allowed_doc_ids`` (the sample life).
    """
    if not is_demo_dir(data_dir):
        raise DemoError(f"Recording is only allowed into a demo folder, and {data_dir} is not one.")
    if live is None:
        from ordnung.llm.claude_cli import ClaudeCLIBackend

        live = ClaudeCLIBackend(concurrency=1)
    recorder = RecordingBackend(live, fixtures, allowed_doc_ids=set(allowed_doc_ids))
    return ReplayBackend(fixtures, fallback=recorder)


def _tracked_backend(
    kind: BackendKind,
    fixtures: Path,
    allowed: set[str],
    data_dir: Path | None = None,
    live: LLMBackend | None = None,
) -> _Tracked:
    """The build's backend: strict replay, or replay-then-record into ``data_dir`` (a demo folder)."""
    if kind == "record" and data_dir is not None:
        return _Tracked(recording_backend(data_dir, fixtures, allowed, live), fixtures)
    if kind != "replay":
        raise DemoError(f"Unknown demo backend {kind!r} (use 'replay' or 'record' with a data folder).")
    return _Tracked(ReplayBackend(fixtures), fixtures)


# --------------------------------------------------------------------------------------------------
# building
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Plan:
    """The inputs of a build: the manifest, where samples and fixtures live, the sample doc ids."""

    manifest: Manifest
    samples: Path
    fixtures: Path
    allowed: set[str]


def _plan(samples: str | Path | None, fixtures: str | Path | None) -> _Plan:
    root = samples_root(samples)
    manifest = load_manifest(root)
    return _Plan(manifest, root, _fixtures_root(fixtures), set(manifest.document_ids(root).values()))


def _start_dir(target: Path) -> None:
    """An empty demo folder, marked as one from the start (so an interrupted build can be reset)."""
    _clear(target)
    _write_marker(target, "")


@contextlib.contextmanager
def _pinned_today(day: str) -> Iterator[None]:
    prior = clock.today() if clock.simulated() else None
    clock.set_today(day)
    try:
        yield
    finally:
        clock.set_today(prior)


@dataclass(frozen=True)
class OfflineTickContext:
    """A tick context without a model: the brief and the review are made explicitly afterwards."""

    store: Store
    llm: None = None
    bus: None = None


def _seed(ctx: AppContext, manifest: Manifest) -> None:
    persona = manifest.persona
    profile = Profile.model_validate(persona.model_dump() | {"onboarded": True})
    settings = AppSettings(demo=True, simulated_today=manifest.simulated_today, concurrency=1)
    with ctx.store.tx():
        ctx.store.save_profile(profile)
        ctx.store.save_settings(settings)
        ctx.store.set_meta(SIMULATED_TODAY_KEY, manifest.simulated_today)
        reset_demo_state(ctx.store)
    ctx.reload_settings()


def _note(run: _BuildRun, label: str, exc: BaseException) -> None:
    if not isinstance(exc, ReplayMiss):  # misses are listed by the backend already
        run.failures.append(f"{label}: {describe_error(exc)}")


async def _read_library(ctx: AppContext, plan: _Plan, run: _BuildRun) -> None:
    for sample in plan.manifest.library:
        try:
            document, job = await add_sample(ctx, sample, plan.samples)
            document = await read_sample(ctx, document, job)
        except Exception as exc:  # collect every problem of the build, not just the first
            _note(run, sample.slug, exc)
            continue
        if document.status == "failed":
            run.failures.append(f"{sample.slug}: {document.error}")
        run.documents += 1


async def _secretary(ctx: AppContext, run: _BuildRun) -> None:
    """The day's triggers (as the daily tick runs them), then the weekly review and the brief."""
    store = ctx.store
    await DailyTick(OfflineTickContext(store)).check()
    today = local_today(store)
    try:
        await run_review(store, ctx.llm, today)
    except LLMError as exc:
        _note(run, "review", exc)
    await generate_brief(store, ctx.llm, today)


async def _build_base(target: Path, plan: _Plan, run: _BuildRun) -> None:
    ctx = build_context(target, backend_obj=run.backend)
    try:
        _seed(ctx, plan.manifest)
        await _read_library(ctx, plan, run)
        await _secretary(ctx, run)
    finally:
        ctx.close()


def tray_states(manifest: Manifest) -> list[tuple[SampleDocument, ...]]:
    """Every combination of opened tray letters (in manifest order), from none to all."""
    tray = manifest.tray
    return [combo for size in range(len(tray) + 1) for combo in itertools.combinations(tray, size)]


async def _ask_all(ctx: AppContext, questions: Sequence[str]) -> int:
    for question in questions:
        async for _ in ask_stream(ctx, question):
            pass
    return len(questions)


async def _exercise_asks(
    base: Path, plan: _Plan, questions: Sequence[str], work_dir: Path, run: _BuildRun
) -> list[Path]:
    """Ask every question once per combination of opened tray letters; returns the state folders.

    Answers depend on the ledger, so each combination has its own recording; the last state has
    every tray letter opened.
    """
    states = []
    for index, opened in enumerate(tray_states(plan.manifest)):
        state = work_dir / f"state-{index}"
        await asyncio.to_thread(copy_data, base, state)
        ctx = build_context(state, backend_obj=run.backend)
        try:
            for sample in opened:
                await open_tray_item(
                    ctx, sample.slug, stage_delay=0, manifest=plan.manifest, samples=plan.samples
                )
            first = len(run.backend.asks)
            run.asks += await _ask_all(ctx, questions)
            run.failures += _stale_asks(ctx.store, run.backend.asks[first:], index)
        except Exception as exc:  # collect every problem of the build, not just the first
            _note(run, f"tray state {index}", exc)
        finally:
            ctx.close()
        states.append(state)
    return states


def _stale_asks(store: Store, asks: Sequence[tuple[Path, list[StreamEvent]]], state: int) -> list[str]:
    """Recorded Ask answers whose tool results Ordnung's tools no longer give on this ledger: a change
    to the MCP output (ADR 0008) must be recorded again, or the replay checks answers against stale
    evidence."""
    from ordnung.assistant.mcp_server import LedgerTools, stale_tool_results

    tools = LedgerTools(store)
    problems = []
    for path, events in asks:
        stale = stale_tool_results(tools, events)
        if stale:
            problems.append(
                f"tray state {state}: the recorded Ask answer {path.name} has tool results the current "
                f"tools no longer give ({', '.join(stale)}) — delete it and record it again"
            )
    return problems


async def _build_and_ask(
    target: Path, plan: _Plan, run: _BuildRun, questions: Sequence[str] | None, work_dir: Path
) -> None:
    await _build_base(target, plan, run)
    if questions is not None and not run.problems:
        await _exercise_asks(target, plan, questions, work_dir, run)


def _prune(fixtures: Path, used: set[Path]) -> int:
    """Delete fixture files the recording did not use (stale prompt versions); returns how many."""
    stale = [path for path in fixture_files(fixtures) if path not in used]
    for path in stale:
        path.unlink()
    return len(stale)


def _raise_problems(problems: Sequence[str]) -> None:
    if problems:
        listed = "\n".join(f"  - {problem}" for problem in problems[:MAX_DIFF_LINES])
        more = f"\n  … and {len(problems) - MAX_DIFF_LINES} more" if len(problems) > MAX_DIFF_LINES else ""
        raise DemoError(f"The demo could not be built:\n{listed}{more}")


def build_demo(
    data_dir: str | Path,
    *,
    backend: BackendKind = "replay",
    rebuild: bool = False,
    samples: str | Path | None = None,
    fixtures: str | Path | None = None,
    snapshot: str | Path | None = None,
    live: LLMBackend | None = None,
    record_asks: bool = True,
    questions: Sequence[str] | None = None,
) -> DemoBuild:
    """Create a fresh demo data directory from the sample life (see the module docstring).

    ``backend="replay"`` replays the fixtures strictly (any miss raises :class:`DemoError`);
    ``"record"`` records missing answers with ``live`` (default: the ``claude`` CLI), asks the
    suggested ``questions`` in every tray state (unless ``record_asks`` is off) and removes fixtures
    the recording no longer uses. ``rebuild`` writes the snapshot (maintainers only).
    ``samples``/``fixtures``/``snapshot`` override the packaged locations. Refuses to overwrite a
    folder that is not a demo folder. Runs its own event loop.
    """
    plan = _plan(samples, fixtures)
    target = Path(data_dir).expanduser().resolve()
    _start_dir(target)
    run = _BuildRun(_tracked_backend(backend, plan.fixtures, plan.allowed, target, live))
    asking = backend == "record" and record_asks
    chosen = (questions if questions is not None else suggested_questions()) if asking else None
    with (
        _pinned_today(plan.manifest.simulated_today),
        tempfile.TemporaryDirectory(prefix="ordnung-demo-") as work,
    ):
        asyncio.run(_build_and_ask(target, plan, run, chosen, Path(work)))
    _raise_problems(run.problems)
    pruned = _prune(plan.fixtures, run.backend.used) if asking else 0
    version = demo_version(samples=plan.samples, fixtures=plan.fixtures)
    _write_marker(target, version)
    written = (
        write_snapshot(target, Path(snapshot) if snapshot else snapshot_dir(), version) if rebuild else None
    )
    return DemoBuild(
        data_dir=target,
        version=version,
        documents=run.documents,
        asks=run.asks,
        snapshot=written,
        pruned=pruned,
    )


# --------------------------------------------------------------------------------------------------
# opening the demo
# --------------------------------------------------------------------------------------------------


def refresh_ideas(data_dir: Path) -> None:
    """Re-run the secretary's rules on a copied snapshot for its simulated day.

    The snapshot is rebuilt only when the samples or recordings change; rule Ideas are code, so this
    keeps them current (a rule that no longer fires expires its Idea; the person's choices stay).
    """
    from ordnung.secretary.triggers import run_and_reconcile

    store = Store.open(Paths(data_dir))
    try:
        run_and_reconcile(store, local_today(store))
    finally:
        store.close()


async def _draft_example(data_dir: Path) -> None:
    from ordnung.drafts.compose import compose

    ctx = build_context(data_dir, backend="replay")
    try:
        if ctx.store.list_drafts():
            return
        phone = next(
            (c for c in ctx.store.list_contracts() if c.category == "mobile" and c.status == "active"), None
        )
        if phone is not None:
            await compose(ctx, "cancellation", contract_id=phone.id)
    finally:
        ctx.close()


def draft_example(data_dir: Path) -> None:
    """Give the demo's *Letters* page one letter to look at: the phone contract's cancellation,
    drafted by the real composer (the fixed sentences; the zero-token demo adds no model text).
    Best effort — the demo works without it (and is skipped when called from running async code)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        return
    try:
        asyncio.run(_draft_example(data_dir))
    except Exception:  # pragma: no cover - never let a nicety stop the demo
        log.warning("could not draft the demo's example letter", exc_info=True)


def prepare_demo(
    data_dir: str | Path | None = None,
    *,
    reset: bool = False,
    samples: str | Path | None = None,
    fixtures: str | Path | None = None,
    snapshot: str | Path | None = None,
) -> DemoPrepared:
    """Make sure a current demo folder exists: keep it, copy the snapshot, or rebuild from fixtures.

    ``reset`` starts over (tray unopened, tour at step 1). Refuses folders that hold other data.
    """
    target = Path(data_dir).expanduser().resolve() if data_dir is not None else default_demo_dir()
    version = demo_version(samples=samples, fixtures=fixtures)
    if not reset and read_demo_version(target) == version:
        return DemoPrepared(target, "existing", version)
    source = Path(snapshot) if snapshot is not None else snapshot_dir()
    if snapshot_version(source) == version:
        _clear(target)
        copy_data(source, target)
        refresh_ideas(target)
        draft_example(target)
        _write_marker(target, version)
        return DemoPrepared(target, "snapshot", version)
    if not fixture_files(fixtures):
        raise DemoError(
            "The demo's recorded answers are missing, so the demo cannot be built. "
            "Reinstall Ordnung, or record them with ORDNUNG_RECORD=1 ordnung demo --live --rebuild."
        )
    built = build_demo(target, samples=samples, fixtures=fixtures)
    return DemoPrepared(built.data_dir, "fixtures", built.version)


# --------------------------------------------------------------------------------------------------
# checking
# --------------------------------------------------------------------------------------------------


def _strip_volatile(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_volatile(item) for key, item in value.items() if key not in VOLATILE_FIELDS}
    if isinstance(value, list):
        return [_strip_volatile(item) for item in value]
    if isinstance(value, str) and value[:1] in ("{", "["):
        try:
            return _strip_volatile(json.loads(value))
        except ValueError:
            return value
    return value


def canonical_dump(db_path: Path) -> list[str]:
    """The database as sorted JSON lines, without timestamps (``table<TAB>row``)."""
    lines: list[str] = []
    with contextlib.closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        for table in DUMP_TABLES:
            rows = [
                json.dumps(_strip_volatile(dict(row)), sort_keys=True, ensure_ascii=False, default=str)
                for row in conn.execute(f"SELECT * FROM {table}")
            ]
            lines.extend(f"{table}\t{row}" for row in sorted(rows))
    return lines


def dump_differences(first: list[str], second: list[str]) -> list[str]:
    """The first differing lines of two canonical dumps (empty if identical)."""
    if first == second:
        return []
    diff = difflib.unified_diff(first, second, "first build", "second build", lineterm="", n=0)
    changed = [line for line in diff if line[:1] in "+-" and not line.startswith(("+++", "---"))]
    return [line[:300] for line in changed[:MAX_DIFF_LINES]]


def _schema_problem(purpose: str, record: dict[str, Any]) -> str | None:
    try:
        response = LLMResponse.model_validate(record["response"])
        for event in record.get("stream") or []:
            StreamEvent.model_validate(event)
    except (KeyError, TypeError, ValidationError) as exc:
        return f"not a recorded response ({str(exc).splitlines()[0]})"
    model = OUTPUT_MODELS.get(purpose)
    if model is None:
        return None
    payload = response.data if response.data is not None else extract_json(response.text)
    if payload is None:
        return None if purpose == "brief" and response.text.strip() else "no structured output"
    try:
        model.model_validate(payload)
    except ValidationError as exc:
        return f"does not match {model.__name__}: {exc.error_count()} error(s)"
    return None


def fixture_problems(fixtures: str | Path | None, allowed_doc_ids: set[str]) -> list[str]:
    """Fixtures that are unreadable, invalid for today's output models or carry non-sample documents."""
    root = _fixtures_root(fixtures)
    problems = []
    for path in fixture_files(root):
        name = path.relative_to(root).as_posix()
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"fixture {name}: unreadable ({exc})")
            continue
        request = record.get("request") if isinstance(record, dict) else None
        request = request if isinstance(request, dict) else {}
        foreign = sorted(set(request.get("doc_ids") or []) - allowed_doc_ids)
        if foreign:
            problems.append(f"fixture {name}: references non-sample documents {', '.join(foreign)}")
        problem = _schema_problem(str(request.get("purpose") or path.parent.name), record)
        if problem:
            problems.append(f"fixture {name}: {problem}")
    return problems


def _ref_lookups(store: Store) -> dict[str, Callable[[str], object | None]]:
    return {
        "document": store.get_document,
        "item": store.get_item,
        "contract": store.get_contract,
        "party": store.get_party,
        "case": store.get_case,
        "draft": store.get_draft,
    }


def unresolved_refs(store: Store) -> list[str]:
    """Idea references (and action targets) that point at records which do not exist."""
    lookups = _ref_lookups(store)
    problems: list[str] = []
    for idea in store.list_suggestions():
        targets: list[tuple[str, str]] = [(ref.type, ref.id) for ref in idea.refs]
        if idea.action and idea.action.target_type in lookups and idea.action.target_id:
            targets.append((idea.action.target_type, idea.action.target_id))
        problems.extend(
            f"Idea “{idea.title}” refers to a missing {kind} {ref_id}"
            for kind, ref_id in targets
            if lookups[kind](ref_id) is None
        )
    return problems


def citation_problems(fixtures: str | Path | None, store: Store) -> list[str]:
    """Citations in recorded Ask answers that do not resolve in ``store`` (all tray letters opened)."""
    problems: list[str] = []
    root = _fixtures_root(fixtures)
    for path in fixture_files(root / "ask"):
        try:
            text = LLMResponse.model_validate(json.loads(path.read_text(encoding="utf-8"))["response"]).text
        except (OSError, ValueError, KeyError, ValidationError):
            continue  # reported by fixture_problems
        problems.extend(
            f"fixture {path.relative_to(root).as_posix()}: cites a missing record {citation.id}"
            for citation in parse_citations(text)
            if record_label(store, citation.id) is None
        )
    return problems


def _inspect(data_dir: Path, fixtures: Path | None) -> tuple[list[str], int]:
    """Unresolved Idea refs (and, with ``fixtures``, recorded citations) plus the Idea count."""
    store = Store.open(Paths(data_dir))
    try:
        problems = unresolved_refs(store)
        if fixtures is not None:
            problems += citation_problems(fixtures, store)
        return problems, len(store.list_suggestions())
    finally:
        store.close()


async def _check_builds(
    work: Path, plan: _Plan, questions: Sequence[str], runs: Sequence[_BuildRun]
) -> list[Path]:
    """Build twice (asking every question in every tray state after the first); returns the states."""
    first, second = runs
    await _build_base(work / "first", plan, first)
    states = await _exercise_asks(work / "first", plan, questions, work / "asks", first)
    await _build_base(work / "second", plan, second)
    return states


def _check_snapshot(report: DemoCheck, snapshot: Path, plan: _Plan) -> None:
    current = demo_version(samples=plan.samples, fixtures=plan.fixtures)
    found = snapshot_version(snapshot)
    if found is None:
        report.warnings.append(
            f"No demo snapshot in {snapshot}: `ordnung demo` will build from the fixtures."
        )
    elif found != current:
        report.problems.append(
            f"The demo snapshot in {snapshot} is out of date — rebuild it with `ordnung demo --rebuild`."
        )


def check_demo(
    *,
    samples: str | Path | None = None,
    fixtures: str | Path | None = None,
    snapshot: str | Path | None = None,
    questions: Sequence[str] | None = None,
    work_dir: str | Path | None = None,
) -> DemoCheck:
    """Rebuild the demo twice with strict replay (in temporary folders) and verify it.

    Problems: replay misses (also for the suggested questions in every tray state), builds that
    differ, fixtures that are invalid or carry non-sample documents, Idea references or recorded
    citations that do not resolve, a stale snapshot. Runs its own event loop.
    """
    plan = _plan(samples, fixtures)
    report = DemoCheck(fixtures=len(fixture_files(plan.fixtures)))
    if not report.fixtures:
        report.problems.append(
            f"There are no recorded answers in {plan.fixtures} — record them with "
            "ORDNUNG_RECORD=1 ordnung demo --live --rebuild."
        )
        return report
    report.problems += fixture_problems(plan.fixtures, plan.allowed)
    asked = list(questions) if questions is not None else suggested_questions()
    runs = [_BuildRun(_tracked_backend("replay", plan.fixtures, plan.allowed)) for _ in range(2)]
    with (
        tempfile.TemporaryDirectory(prefix="ordnung-demo-check-", dir=work_dir) as tmp,
        _pinned_today(plan.manifest.simulated_today),
    ):
        work = Path(tmp)
        for name in ("first", "second"):
            _start_dir(work / name)
        states = asyncio.run(_check_builds(work, plan, asked, runs))
        first = runs[0]
        report.documents, report.asks = first.documents, first.asks
        report.problems += first.problems
        differences = dump_differences(
            canonical_dump(work / "first" / DB_NAME), canonical_dump(work / "second" / DB_NAME)
        )
        report.problems += [f"builds differ: {line}" for line in differences]
        base_problems, report.ideas = _inspect(work / "first", None)
        report.problems += base_problems + _inspect(states[-1], plan.fixtures)[0]
    _check_snapshot(report, Path(snapshot) if snapshot is not None else snapshot_dir(), plan)
    return report
