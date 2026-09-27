"""Letters waiting for the person (``ingest.held``): what "Read these" and "Keep private" change, that
an answer given while the file is still being stored stands, and that nothing waiting reaches a model."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER, TODAY, Router, fake_backend
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.ingest import held
from ordnung.ingest.pipeline import add_file, ingest_document, release_held
from ordnung.llm.fake import FakeBackend


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def ctx(data_dir: Path) -> Iterator[AppContext]:
    context = build_context(data_dir, backend_obj=fake_backend(Router()))
    yield context
    context.close()


def calls(ctx: AppContext) -> int:
    assert isinstance(ctx.llm.backend, FakeBackend)
    return len(ctx.llm.backend.calls)


async def test_a_held_letter_is_private_and_waits(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", hold=True, source="folder")
    assert (document.status, document.ai_private, document.source) == ("held", True, "folder")
    assert held.is_held(document)
    assert [doc.id for doc in held.waiting(ctx.store)] == [document.id]
    ctx.store.trash_document(document.id)
    assert held.waiting(ctx.store) == []
    trashed = ctx.store.get_document(document.id)
    assert trashed is not None and not held.is_held(trashed)


async def test_read_reuses_the_local_job_that_has_not_started(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", hold=True, source="folder")
    (local,) = ctx.store.list_jobs()
    answer = release_held(ctx, [document.id])
    assert [job.id for job in answer.jobs] == [local.id] and len(ctx.store.list_jobs()) == 1
    assert await ctx.worker.run_until_idle() == 1
    read = ctx.store.get_document(document.id)
    assert read is not None and read.status == "processed" and read.kind == "tax_assessment"


async def test_read_given_while_the_file_is_stored_is_kept(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", hold=True, source="folder")
    answered: list[str] = []

    def answer_midway(stage: str, _progress: float) -> None:
        if stage == "text" and not answered:
            answered.append(stage)
            held.release(ctx.store, [document.id])  # the person clicks "Read" meanwhile

    local = ctx.store.claim_next_job()  # the worker is storing it right now
    assert local is not None
    stored = await ingest_document(ctx, document.id, on_stage=answer_midway, job_id=local.id)
    assert (stored.status, stored.ai_private) == ("queued", False)  # left to its reading job
    assert calls(ctx) == 0
    jobs = {job.id: job.status for job in ctx.store.list_jobs()}
    assert jobs.pop(local.id) == "done" and list(jobs.values()) == ["queued"]  # a job of its own
    await ctx.worker.run_until_idle()
    read = ctx.store.get_document(document.id)
    assert read is not None and read.status == "processed" and calls(ctx) > 0


async def test_keep_private_given_while_the_file_is_stored_is_kept(ctx: AppContext) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", hold=True, source="folder")

    def answer_midway(stage: str, _progress: float) -> None:
        if stage == "text":
            held.keep_private(ctx.store, [document.id])

    stored = await ingest_document(ctx, document.id, on_stage=answer_midway)
    assert (stored.status, stored.ai_private) == ("processed", True)
    assert held.waiting(ctx.store) == [] and calls(ctx) == 0


async def test_answers_are_logged_and_only_change_waiting_letters(ctx: AppContext) -> None:
    waiting = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", hold=True, source="folder")
    ordinary = await add_file(ctx, INVOICE_LETTER.pdf(), "rechnung.pdf")
    answer = held.keep_private(ctx.store, [waiting.id, ordinary.id, waiting.id, "doc_gone"])
    assert [doc.id for doc in answer.documents] == [waiting.id]
    assert answer.skipped == [ordinary.id, "doc_gone"]
    unchanged = ctx.store.get_document(ordinary.id)
    assert unchanged is not None and (unchanged.status, unchanged.ai_private) == ("queued", False)
    messages = [entry.message for entry in ctx.store.list_activity(5, kinds=["document.private"])]
    assert messages == ["You kept “bescheid.pdf” private · not sent to AI"]
    release = release_held(ctx, [waiting.id])
    assert release.documents == [] and release.skipped == [waiting.id]


async def test_nothing_waiting_is_read_by_the_worker(ctx: AppContext) -> None:
    for letter, name in ((TAX_LETTER, "a.pdf"), (INVOICE_LETTER, "b.pdf")):
        await add_file(ctx, letter.pdf(), name, hold=True, source="folder")
    assert await ctx.worker.run_until_idle() == 2
    assert calls(ctx) == 0
    assert {doc.status for doc in ctx.store.list_documents()} == {"held"}
    kinds = {entry.kind for entry in ctx.store.list_activity(20)}
    assert "document.held" in kinds and "document.private" not in kinds
