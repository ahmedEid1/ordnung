"""The ingest worker: concurrency, rate-limit pause, readable failures, recovery and the triggers hook."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER, TODAY, Router, fake_backend, record_events
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.db.store import Store
from ordnung.ingest import pipeline
from ordnung.ingest.pipeline import add_file
from ordnung.ingest.worker import DEFAULT_PAUSE, PAUSE_META_KEY, IngestWorker, parse_reset, pause_until
from ordnung.llm.base import ClaudeAuthError, ClaudeNotInstalled, ClaudeRateLimited

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def router() -> Router:
    return Router()


@pytest.fixture
def ctx(data_dir: Path, router: Router) -> Iterator[AppContext]:
    context = build_context(data_dir, backend_obj=fake_backend(router))
    yield context
    context.close()


# --------------------------------------------------------------------------------------------------
# Reset times
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("2026-09-25T15:00:00+00:00", datetime(2026, 9, 25, 15, 0, tzinfo=UTC)),
        ("2026-09-25T15:00:00Z", datetime(2026, 9, 25, 15, 0, tzinfo=UTC)),
        ("1790341200", datetime.fromtimestamp(1790341200, UTC)),
        ("2 hours", NOW + timedelta(hours=2)),
        ("30 minutes", NOW + timedelta(minutes=30)),
        ("3pm (UTC)", datetime(2026, 9, 25, 15, 0, tzinfo=UTC)),
        ("11am (UTC)", datetime(2026, 9, 26, 11, 0, tzinfo=UTC)),  # already past today → tomorrow
        ("soon", None),
        (None, None),
    ],
)
def test_parse_reset(hint: str | None, expected: datetime | None) -> None:
    assert parse_reset(hint, NOW) == expected


def test_pause_until_falls_back_to_fifteen_minutes() -> None:
    assert pause_until(None, NOW) == NOW + DEFAULT_PAUSE
    assert pause_until("2026-09-24T10:00:00Z", NOW) == NOW + DEFAULT_PAUSE  # in the past
    assert pause_until("2026-10-30T10:00:00Z", NOW) == NOW + DEFAULT_PAUSE  # implausibly far
    assert pause_until("1 hour", NOW) == NOW + timedelta(hours=1)


# --------------------------------------------------------------------------------------------------
# Rate limits
# --------------------------------------------------------------------------------------------------


async def test_rate_limit_pauses_the_worker_and_keeps_the_job(ctx: AppContext, router: Router) -> None:
    router.errors["extract"] = lambda: ClaudeRateLimited("Usage limit reached.", reset_at="2 hours")
    events = record_events(ctx.bus)
    first = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await add_file(ctx, INVOICE_LETTER.pdf(), "invoice.pdf")

    ctx.settings.concurrency = 1
    assert await ctx.worker.run_until_idle() == 1  # paused after the first job: the second is not started

    assert ctx.worker.is_paused()
    assert ctx.worker.paused_until is not None
    assert timedelta(minutes=110) < ctx.worker.paused_until - datetime.now(UTC) <= timedelta(hours=2)
    job = next(job for job in ctx.store.list_jobs() if job.doc_id == first.id)
    assert job.status == "queued"
    assert job.waiting_reason is not None and "usage limit" in job.waiting_reason
    assert job.not_before is not None
    document = ctx.store.get_document(first.id)
    assert document is not None and document.status == "queued" and document.error is None
    assert ctx.store.get_meta(PAUSE_META_KEY) == ctx.worker.paused_until.isoformat()
    paused = [data for kind, data in events if kind == "llm.paused"]
    assert paused and paused[0]["until"] == ctx.worker.paused_until.isoformat()

    assert await ctx.worker.run_until_idle() == 0  # still paused: nothing is claimed


async def test_worker_resumes_after_the_pause(ctx: AppContext, router: Router) -> None:
    router.errors["extract"] = lambda: ClaudeRateLimited("Usage limit reached.")
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await ctx.worker.run_until_idle()
    assert ctx.worker.is_paused()

    del router.errors["extract"]
    events = record_events(ctx.bus)
    ctx.worker.paused_until = datetime.now(UTC) - timedelta(seconds=1)
    ctx.store.update_job(ctx.store.list_jobs()[0].id, not_before=datetime.now(UTC) - timedelta(seconds=1))
    assert await ctx.worker.run_until_idle() == 1

    assert ("llm.resumed", {}) in events
    assert ctx.store.get_meta(PAUSE_META_KEY) is None
    finished = ctx.store.get_document(document.id)
    assert finished is not None and finished.status == "processed"
    job = ctx.store.list_jobs()[0]
    assert job.status == "done" and job.waiting_reason is None and job.attempts == 2


async def test_pause_survives_a_restart(ctx: AppContext) -> None:
    until = datetime.now(UTC) + timedelta(minutes=5)
    ctx.store.set_meta(PAUSE_META_KEY, until.isoformat())
    assert IngestWorker(ctx).is_paused()
    ctx.store.set_meta(PAUSE_META_KEY, (datetime.now(UTC) - timedelta(minutes=5)).isoformat())
    assert not IngestWorker(ctx).is_paused()


# --------------------------------------------------------------------------------------------------
# Failures
# --------------------------------------------------------------------------------------------------


async def test_auth_error_fails_the_document_with_a_readable_message(ctx: AppContext, router: Router) -> None:
    message = (
        "Claude Code is not signed in (or the key is invalid). Run `claude` once in a terminal and log in."
    )
    router.errors["extract"] = lambda: ClaudeAuthError(message)
    events = record_events(ctx.bus)
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    assert await ctx.worker.run_until_idle() == 1

    failed = ctx.store.get_document(document.id)
    assert failed is not None and failed.status == "failed" and failed.error == message
    job = ctx.store.list_jobs()[0]
    assert job.status == "failed" and job.error == message
    assert not ctx.worker.is_paused()
    last = [data for kind, data in events if kind == "job.progress"][-1]
    assert last["status"] == "failed" and last["stage"] == "extract" and last["error"] == message
    assert "document.processed" not in [kind for kind, _ in events]


async def test_missing_claude_fails_readably(ctx: AppContext, router: Router) -> None:
    router.errors["extract"] = lambda: ClaudeNotInstalled("Claude Code is not installed.")
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await ctx.worker.run_until_idle()
    failed = ctx.store.get_document(document.id)
    assert failed is not None and failed.error == "Claude Code is not installed."


async def test_unexpected_errors_get_a_generic_message(ctx: AppContext, router: Router) -> None:
    router.errors["extract"] = lambda: ZeroDivisionError("boom")
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await ctx.worker.run_until_idle()
    failed = ctx.store.get_document(document.id)
    assert failed is not None and failed.error == pipeline.UNEXPECTED_ERROR


async def test_reuploading_a_failed_document_retries_it(ctx: AppContext, router: Router) -> None:
    router.errors["extract"] = lambda: ClaudeAuthError("not signed in")
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await ctx.worker.run_until_idle()
    del router.errors["extract"]
    again = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    assert again.status == "queued"
    await ctx.worker.run_until_idle()
    done = ctx.store.get_document(document.id)
    assert done is not None and done.status == "processed" and done.error is None


# --------------------------------------------------------------------------------------------------
# Background loop, recovery, concurrency, triggers
# --------------------------------------------------------------------------------------------------


async def wait_for(condition: Callable[[], bool], attempts: int = 500) -> None:
    for _ in range(attempts):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met in time")


async def test_background_loop_reads_new_uploads_and_stops(ctx: AppContext) -> None:
    await ctx.worker.start()
    assert ctx.worker.running
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")

    def processed() -> bool:
        stored = ctx.store.get_document(document.id)
        return stored is not None and stored.status == "processed"

    await wait_for(processed)
    await ctx.worker.stop()
    assert not ctx.worker.running


async def test_start_requeues_jobs_left_running(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    claimed = ctx.store.claim_next_job()
    assert claimed is not None and claimed.status == "running"
    fresh = IngestWorker(ctx)
    assert await fresh.run_until_idle() == 1
    stored = ctx.store.get_document(document.id)
    assert stored is not None and stored.status == "processed"


async def test_stop_puts_unfinished_documents_back_in_the_queue(ctx: AppContext, router: Router) -> None:
    gate = asyncio.Event()
    backend = ctx.llm.backend
    original = backend.complete

    async def slow(req):  # type: ignore[no-untyped-def]
        await gate.wait()
        return await original(req)

    backend.complete = slow  # type: ignore[method-assign]
    await ctx.worker.start()
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await wait_for(lambda: ctx.store.list_jobs()[0].status == "running")
    await ctx.worker.stop(grace=0.05)

    job = ctx.store.list_jobs()[0]
    assert job.status == "queued" and job.waiting_reason is not None
    stored = ctx.store.get_document(document.id)
    assert stored is not None and stored.status == "queued"


async def test_documents_are_read_concurrently(ctx: AppContext) -> None:
    ctx.settings.concurrency = 2
    backend = ctx.llm.backend
    original = backend.complete
    running = 0
    peak = 0

    async def tracked(req):  # type: ignore[no-untyped-def]
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return await original(req)

    backend.complete = tracked  # type: ignore[method-assign]
    await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await add_file(ctx, INVOICE_LETTER.pdf(), "invoice.pdf")
    assert await ctx.worker.run_until_idle() == 2
    assert peak == 2


async def test_triggers_run_after_each_document(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Store, date]] = []
    monkeypatch.setattr(pipeline, "triggers_hook", lambda: lambda store, today: calls.append((store, today)))
    events = record_events(ctx.bus)
    await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await add_file(ctx, INVOICE_LETTER.pdf(), "invoice.pdf")
    await ctx.worker.run_until_idle()
    assert calls == [(ctx.store, date(2026, 9, 25))] * 2
    assert [kind for kind, _ in events].count("suggestions.updated") == 2


async def test_a_broken_trigger_never_fails_the_document(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(store: Store, today: date) -> None:
        raise RuntimeError("bug in a trigger")

    monkeypatch.setattr(pipeline, "triggers_hook", lambda: broken)
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await ctx.worker.run_until_idle()
    stored = ctx.store.get_document(document.id)
    assert stored is not None and stored.status == "processed"


def test_missing_triggers_module_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> object:
        raise ModuleNotFoundError(name=name)

    monkeypatch.setattr(pipeline.importlib, "import_module", missing)
    assert pipeline.triggers_hook() is None
