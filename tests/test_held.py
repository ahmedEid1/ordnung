"""Letters waiting for the person (``ingest.held``): what "Read these" and "Keep private" change, that
an answer given while the file is still being stored stands, that nothing waiting reaches a model, that
a letter keeps waiting whatever happens to its reading on this computer, that "Keep private" can be
undone, and that only a file added by hand answers for a waiting copy."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER, TODAY, Router, fake_backend
from helpers_docs import Line, make_pdf
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.ingest import held, pipeline
from ordnung.ingest.pipeline import add_file, ingest_document, keep_held_private, release_held
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


def pdf_with(text: str) -> bytes:
    return make_pdf([[Line(72, 90, text)]])


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
    messages = [entry.message for entry in ctx.store.list_activity(5, kinds=[held.KEPT_PRIVATE])]
    assert messages == ["You kept “bescheid.pdf” private · not sent to Claude"]
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


async def test_a_waiting_letter_stopped_while_it_is_stored_keeps_waiting(ctx: AppContext) -> None:
    """Ordnung quits while the file is stored: it still waits, and is stored when Ordnung runs again
    — never finished as if the person had chosen "Keep private"."""
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", hold=True, source="folder")

    def quit_midway(stage: str, _progress: float) -> None:
        if stage == "text":
            raise asyncio.CancelledError

    local = ctx.store.claim_next_job()
    assert local is not None
    with pytest.raises(asyncio.CancelledError):
        await ingest_document(ctx, document.id, on_stage=quit_midway, job_id=local.id)
    stopped = ctx.store.get_document(document.id)
    assert stopped is not None and stopped.status == "held"
    assert [doc.id for doc in held.waiting(ctx.store)] == [document.id]
    ctx.store.update_job(local.id, status="queued")  # the worker puts it back (worker._requeue)
    await ctx.worker.run_until_idle()
    stored = ctx.store.get_document(document.id)
    assert stored is not None and (stored.status, stored.ai_private) == ("held", True)
    assert stored.processed_at is not None and calls(ctx) == 0


async def test_a_waiting_letter_whose_local_reading_failed_keeps_waiting(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", hold=True, source="folder")
    real = pipeline.read_text_layer

    def broken(*_args: object) -> object:
        raise ValueError("the text layer could not be read")

    monkeypatch.setattr(pipeline, "read_text_layer", broken)
    await ctx.worker.run_until_idle()
    failed = ctx.store.get_document(document.id)
    assert failed is not None and (failed.status, failed.ai_private) == ("held", True)
    assert failed.error and [doc.id for doc in held.waiting(ctx.store)] == [document.id]

    monkeypatch.setattr(pipeline, "read_text_layer", real)
    answer = keep_held_private(ctx, [document.id])  # "Keep private" stores it again, privately
    assert len(answer.jobs) == 1
    await ctx.worker.run_until_idle()
    kept = ctx.store.get_document(document.id)
    assert kept is not None and (kept.status, kept.ai_private, kept.error) == ("processed", True, None)
    assert "Einkommensteuer" in ctx.store.get_document_text(document.id) and calls(ctx) == 0


async def test_keep_private_can_be_undone_until_something_else_happened(ctx: AppContext) -> None:
    first = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", hold=True, source="folder")
    second = await add_file(ctx, INVOICE_LETTER.pdf(), "rechnung.pdf", hold=True, source="folder")
    await ctx.worker.run_until_idle()
    held.keep_private(ctx.store, [first.id, second.id])
    undone = held.back_to_waiting(ctx.store, [first.id, second.id])
    assert [doc.status for doc in undone.documents] == ["held", "held"]
    assert {doc.id for doc in held.waiting(ctx.store)} == {first.id, second.id}
    assert [entry.message for entry in ctx.store.list_activity(2, kinds=["document.waiting"])] == [
        "“rechnung.pdf” is back with the letters not read yet",
        "“bescheid.pdf” is back with the letters not read yet",
    ]
    again = held.back_to_waiting(ctx.store, [first.id])  # it waits already
    assert again.documents == [] and again.skipped == [first.id]

    release_held(ctx, [first.id])  # read: there is nothing to undo any more
    private = await add_file(ctx, pdf_with("privat"), "privat.pdf", private=True)  # never waited
    await ctx.worker.run_until_idle()
    refused = held.back_to_waiting(ctx.store, [first.id, private.id, "doc_gone"])
    assert refused.documents == [] and refused.skipped == [first.id, private.id, "doc_gone"]


async def test_a_copy_of_a_waiting_file_answers_only_when_added_by_hand(ctx: AppContext) -> None:
    """A copy arriving in the watched folder (even with auto-read on: ``hold=False``) or attached to an
    e-mail leaves the letter waiting; only an upload or the command line answer for it."""
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", hold=True, source="folder")
    copy = await add_file(ctx, TAX_LETTER.pdf(), "bescheid (1).pdf", source="folder")
    assert copy.id == document.id and copy.status == "held"
    assert ctx.store.list_activity(5, kinds=["document.released"]) == []
    await ctx.worker.run_until_idle()
    assert calls(ctx) == 0

    by_hand = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", answer_held=True)
    assert (by_hand.status, by_hand.ai_private) == ("queued", False)
    assert [entry.message for entry in ctx.store.list_activity(5, kinds=["document.released"])] == [
        "You let Claude read “bescheid.pdf”"
    ]


async def test_a_waiting_letter_put_in_the_trash_before_it_was_stored_still_waits_when_restored(
    ctx: AppContext,
) -> None:
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", hold=True, source="folder")
    ctx.store.trash_document(document.id)
    await ctx.worker.run_until_idle()  # its local job finds it in the trash
    trashed = ctx.store.get_document(document.id)
    assert trashed is not None and trashed.status == "held" and trashed.error
    ctx.store.restore_document(document.id)
    assert [doc.id for doc in held.waiting(ctx.store)] == [document.id]
    assert calls(ctx) == 0


async def test_read_these_while_the_letter_is_titled_on_this_computer_stands(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Race (review of wave 2): "Read these" while the held letter's local reading looks up its title.
    The reading must not put it back to ``held`` without being private — "Keep private" would then leave
    it not private while its release job reads it."""
    document = await add_file(ctx, TAX_LETTER.pdf(), "bescheid.pdf", hold=True, source="folder")
    real = pipeline._local_title

    def released_meanwhile(store: object, current: object) -> str | None:
        held.release(ctx.store, [document.id])  # the person answers while the title is looked up
        return real(store, current)  # type: ignore[arg-type]

    monkeypatch.setattr(pipeline, "_local_title", released_meanwhile)
    (local,) = ctx.store.list_jobs()
    await ingest_document(ctx, document.id)
    after = ctx.store.get_document(document.id)
    assert after is not None and (after.status, after.ai_private) == ("queued", False)
    assert local.id
