"""The ingest worker: concurrency, rate-limit pause, waiting for Claude, readable failures, recovery and
the triggers hook."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER, TODAY, Router, fake_backend, record_events
from ordnung import clock
from ordnung.api import deps
from ordnung.api.app import create_app
from ordnung.app_context import AppContext, build_context
from ordnung.db.store import Store
from ordnung.ingest import pipeline, worker
from ordnung.ingest.pipeline import add_file
from ordnung.ingest.worker import DEFAULT_PAUSE, PAUSE_META_KEY, IngestWorker, parse_reset, pause_until
from ordnung.llm.base import ClaudeAuthError, ClaudeNotInstalled, ClaudeRateLimited, ClaudeTimeout
from ordnung.llm.claude_cli import ClaudeCLIBackend
from ordnung.models import ClaudeStatus
from test_api_support import client_for

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
# Waiting for Claude
# --------------------------------------------------------------------------------------------------


def refusing(router: Router, error: Exception) -> list[str]:
    """Make every reading raise ``error``; returns the list each attempt is noted in."""
    attempts: list[str] = []

    def refuse() -> Exception:
        attempts.append("extract")
        return error

    router.errors["extract"] = refuse
    return attempts


async def test_signed_out_claude_keeps_the_letters_waiting(ctx: AppContext, router: Router) -> None:
    """Not signed in: the letter goes back to the queue, waiting for Claude (not failed), the app hears
    ``llm.paused`` without an end, and no other letter is sent to Claude until it is ready."""
    attempts = refusing(router, ClaudeAuthError("Claude Code is not signed in."))
    events = record_events(ctx.bus)
    first = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    second = await add_file(ctx, INVOICE_LETTER.pdf(), "invoice.pdf")
    ctx.settings.concurrency = 1
    await ctx.worker.run_until_idle()
    assert attempts == ["extract"]  # the second letter was put back without trying Claude

    assert ctx.worker.waiting_for_claude == worker.NOT_SIGNED_IN_REASON
    for doc_id in (first.id, second.id):
        document = ctx.store.get_document(doc_id)
        assert document is not None and document.status == "queued" and document.error is None
        job = next(job for job in ctx.store.list_jobs() if job.doc_id == doc_id)
        assert job.status == "queued" and job.error is None
        assert job.waiting_reason is not None
        assert job.waiting_reason.startswith(f"{worker.WAITING_FOR_CLAUDE}: Claude Code isn't signed in.")
    assert [data for kind, data in events if kind == "llm.paused"] == [
        {"until": "", "reason": worker.NOT_SIGNED_IN_REASON}
    ]
    last = [data for kind, data in events if kind == "job.progress" and data["doc_id"] == first.id][-1]
    assert last["status"] == "queued" and last["waiting_reason"].startswith(worker.WAITING_FOR_CLAUDE)
    assert "document.processed" not in [kind for kind, _ in events]
    assert await ctx.worker.run_until_idle() == 0  # still waiting: nothing is due

    del router.errors["extract"]
    ctx.worker.claude_ready()
    assert ("llm.resumed", {}) in events and ctx.worker.waiting_for_claude is None
    assert await ctx.worker.run_until_idle() == 2
    for doc_id in (first.id, second.id):
        document = ctx.store.get_document(doc_id)
        assert document is not None and document.status == "processed"
        job = next(job for job in ctx.store.list_jobs() if job.doc_id == doc_id)
        assert job.status == "done" and job.waiting_reason is None


async def test_missing_claude_keeps_new_letters_waiting_too(ctx: AppContext, router: Router) -> None:
    attempts = refusing(router, ClaudeNotInstalled("The “claude” command was not found."))
    await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await ctx.worker.run_until_idle()
    assert ctx.worker.waiting_for_claude == worker.NOT_INSTALLED_REASON

    later = await add_file(ctx, INVOICE_LETTER.pdf(), "invoice.pdf")
    await ctx.worker.run_until_idle()
    assert attempts == ["extract"]
    job = next(job for job in ctx.store.list_jobs() if job.doc_id == later.id)
    assert job.status == "queued" and job.waiting_reason is not None and job.not_before is not None
    assert "isn't installed on this computer yet" in job.waiting_reason
    document = ctx.store.get_document(later.id)
    assert document is not None and document.status == "queued"


async def test_private_letters_are_read_while_claude_isnt_ready(ctx: AppContext, router: Router) -> None:
    """A private letter never goes to Claude, so it doesn't wait for it."""
    refusing(router, ClaudeNotInstalled("The “claude” command was not found."))
    waiting = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await ctx.worker.run_until_idle()
    private = await add_file(ctx, INVOICE_LETTER.pdf(), "invoice.pdf", private=True)
    assert await ctx.worker.run_until_idle() == 1
    stored = ctx.store.get_document(private.id)
    assert stored is not None and stored.status == "processed" and stored.ai_private
    still = ctx.store.get_document(waiting.id)
    assert still is not None and still.status == "queued"


async def test_the_worker_looks_for_claude_while_letters_wait(
    ctx: AppContext, router: Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nobody has to open the app: the running worker asks its Claude check again by itself."""
    monkeypatch.setattr(worker, "CLAUDE_RECHECK_S", 0.0)
    router.errors["extract"] = lambda: ClaudeAuthError("Claude Code is not signed in.")
    answers = [False, True]
    asked: list[bool] = []

    async def check() -> bool:
        asked.append(answers[min(len(asked), len(answers) - 1)])
        if asked[-1]:
            router.errors.clear()
        return asked[-1]

    ctx.worker.claude_check = check
    await ctx.worker.start()
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")

    def processed() -> bool:
        stored = ctx.store.get_document(document.id)
        return stored is not None and stored.status == "processed"

    await wait_for(processed)
    await ctx.worker.stop()
    assert asked[:2] == [False, True]


async def test_claude_installed_while_ordnung_runs_reads_the_waiting_letter(
    tmp_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Started without ``claude`` on PATH: the letter waits. Installed meanwhile, the next status check
    finds it, the model backend runs it from then on and the waiting letter is read — no restart."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/bin{os.pathsep}/usr/bin")
    monkeypatch.delenv("ORDNUNG_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    context = build_context(data_dir, backend="claude")
    backend = context.llm.backend
    assert isinstance(backend, ClaudeCLIBackend) and backend.binary is None
    app = create_app(context, token=None)
    app.state.ordnung.claude.missing_ttl_s = 0.0
    try:
        async with client_for(app) as client:
            document = await add_file(context, TAX_LETTER.pdf(), "tax.pdf")
            await context.worker.run_until_idle()
            assert context.worker.waiting_for_claude == worker.NOT_INSTALLED_REASON
            assert (await client.get("/api/health")).json()["claude"]["installed"] is False

            claude = install_fake_claude(bin_dir, tmp_path, TAX_LETTER.extraction(), monkeypatch)
            status = (await client.get("/api/health")).json()["claude"]
            assert status["installed"] is True and status["path"] == str(claude)
            assert backend.binary == str(claude) and context.worker.waiting_for_claude is None

            assert await context.worker.run_until_idle() == 1
            read = context.store.get_document(document.id)
            assert read is not None and read.status in ("processed", "needs_review") and read.title
            calls = (tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()
            assert calls and TAX_LETTER.marker in json.loads(calls[0])["stdin"]
    finally:
        context.close()


async def test_a_missing_or_signed_out_claude_is_kept_only_briefly() -> None:
    """The API's status check: someone installing Claude (or signing in) while Ordnung runs is seen at
    the next check, not ten minutes later; every fresh status reaches the listener."""
    answers = [
        ClaudeStatus(installed=False, ok=False),
        ClaudeStatus(installed=True, path="/usr/bin/claude", ok=False),
        ClaudeStatus(installed=True, path="/usr/bin/claude", ok=True),
    ]
    heard: list[ClaudeStatus] = []

    async def probe() -> ClaudeStatus:
        return answers[min(len(heard), len(answers) - 1)]

    assert deps.CLAUDE_MISSING_TTL_S <= 30 < deps.CLAUDE_STATUS_TTL_S
    cache = deps.ClaudeStatusCache(probe, ttl_s=600, missing_ttl_s=0)
    cache.listener = heard.append
    seen = [await cache.get("claude", uses_cli=True) for _ in range(4)]
    assert seen == [answers[0], answers[1], answers[2], answers[2]]  # ready: cached from then on
    assert heard == answers


def install_fake_claude(
    bin_dir: Path, folder: Path, answer: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> Path:
    """``claude`` on PATH (``tests/fake_claude.py``): signed in, and every reading answers ``answer``."""
    result = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "Done.",
        "usage": {"input_tokens": 10, "output_tokens": 10},
        "structured_output": answer,
    }
    scenario = folder / "scenario.json"
    scenario.write_text(
        json.dumps({"log": str(folder / "calls.jsonl"), "calls": [{"lines": [json.dumps(result)]}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_CLAUDE_SCENARIO", str(scenario))
    claude = bin_dir / "claude"
    fake = Path(__file__).resolve().parent / "fake_claude.py"
    claude.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n', encoding="utf-8")
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return claude


# --------------------------------------------------------------------------------------------------
# Failures
# --------------------------------------------------------------------------------------------------


async def test_a_timeout_fails_the_document_with_a_readable_message(ctx: AppContext, router: Router) -> None:
    message = "Claude took too long to answer. Please try again in a moment."
    router.errors["extract"] = lambda: ClaudeTimeout(message)
    events = record_events(ctx.bus)
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    assert await ctx.worker.run_until_idle() == 1

    failed = ctx.store.get_document(document.id)
    assert failed is not None and failed.status == "failed" and failed.error == message
    job = ctx.store.list_jobs()[0]
    assert job.status == "failed" and job.error == message
    assert not ctx.worker.is_paused() and ctx.worker.waiting_for_claude is None
    last = [data for kind, data in events if kind == "job.progress"][-1]
    assert last["status"] == "failed" and last["stage"] == "extract" and last["error"] == message
    assert "document.processed" not in [kind for kind, _ in events]


async def test_unexpected_errors_get_a_generic_message(ctx: AppContext, router: Router) -> None:
    router.errors["extract"] = lambda: ZeroDivisionError("boom")
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await ctx.worker.run_until_idle()
    failed = ctx.store.get_document(document.id)
    assert failed is not None and failed.error == pipeline.UNEXPECTED_ERROR


async def test_reuploading_a_failed_document_retries_it(ctx: AppContext, router: Router) -> None:
    router.errors["extract"] = lambda: ClaudeTimeout("no answer")
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
    monkeypatch.setattr(pipeline, "run_and_reconcile", lambda store, today: calls.append((store, today)))
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

    monkeypatch.setattr(pipeline, "run_and_reconcile", broken)
    document = await add_file(ctx, TAX_LETTER.pdf(), "tax.pdf")
    await ctx.worker.run_until_idle()
    stored = ctx.store.get_document(document.id)
    assert stored is not None and stored.status == "processed"


async def test_stopping_waits_for_the_background_ideas(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An edit's Ideas run in a thread: stopping (before the database closes, or "Delete everything"
    wipes it) waits until that thread is done with it."""
    gate = threading.Event()
    ran: list[date] = []

    def slow(store: Store, today: date) -> None:
        gate.wait(5)
        ran.append(today)

    monkeypatch.setattr(pipeline, "run_and_reconcile", slow)
    ctx.worker.refresh_ideas()
    await asyncio.sleep(0.05)
    stopping = asyncio.create_task(ctx.worker.stop())
    await asyncio.sleep(0.05)
    assert not stopping.done()
    gate.set()
    await stopping
    assert ran == [date(2026, 9, 25)]
