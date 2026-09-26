"""The ingestion pipeline (SPEC § 8, § 21): intake → text → transcribe → extract → verify →
compute → link → plan → done.

* :func:`add_file` validates an upload, stores the original content-addressed (the document id is
  derived from its SHA-256, so a re-upload is a no-op), renders the pages and queues an ingest job.
* :func:`ingest_document` runs the stages for one document, keeping the job row and the event bus
  up to date (``job.progress`` {job_id, doc_id, stage, progress, status}, then
  ``document.processed`` {doc_id, status}). CPU work runs in ``asyncio.to_thread``. Compute, link and
  plan share **one** ``store.tx()`` under the process-wide :func:`ledger_lock`; their stage events
  are published once that transaction has committed.
* Private documents ("Keep private — no AI") stop after the text layer: no model call ever sees them.
* Letters moved to the trash while they waited in the queue (or while being read) are never sent to
  the model: the job fails with :data:`TRASHED_ERROR`; uploading the file again restores and reads it.
* "Today" is the person's (profile time zone or the pinned demo date, :func:`ordnung.tick.local_today`),
  never the computer's clock.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import sqlite3
import weakref
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from ordnung import clock
from ordnung.clock import now_iso
from ordnung.db.store import NotFoundError, Store
from ordnung.ids import doc_id_for_sha
from ordnung.ingest.extract import ExtractionError, ExtractionInput, extract_document, prompt_pages
from ordnung.ingest.intake import (
    TEXT_TYPES,
    IntakeError,
    RenderedPage,
    combine_images_to_pdf,
    normalise_upload,
    render_pages,
    store_original,
)
from ordnung.ingest.link import ensure_party, link_document
from ordnung.ingest.plan import (
    PlanResult,
    Verification,
    compute_item,
    corrections,
    filed_kind,
    payment_details,
    remedy_warnings,
    rule_context,
    verify_extraction,
    with_corrections,
    write_plan,
)
from ordnung.ingest.text import PageText, detect_injection_phrases, extract_pdf_pages, text_file_pages
from ordnung.ingest.transcribe import transcribe_pages
from ordnung.llm.base import ClaudeRateLimited, LLMError
from ordnung.models import Document, DocumentExtraction, Job, Page
from ordnung.rules.deadlines import POSTAL_BUFFER_DAYS
from ordnung.rules.routing import derived_deadlines

if TYPE_CHECKING:
    from ordnung.app_context import AppContext

log = logging.getLogger(__name__)

Stage = Literal["intake", "text", "transcribe", "extract", "verify", "compute", "link", "plan", "done"]
StageCallback = Callable[[str, float], Awaitable[None] | None]

STAGES: tuple[Stage, ...] = (
    "intake",
    "text",
    "transcribe",
    "extract",
    "verify",
    "compute",
    "link",
    "plan",
    "done",
)
STAGE_PROGRESS: dict[str, float] = {
    "intake": 0.05,
    "text": 0.15,
    "transcribe": 0.3,
    "extract": 0.5,
    "verify": 0.7,
    "compute": 0.8,
    "link": 0.87,
    "plan": 0.94,
    "done": 1.0,
}
MAX_KNOWN_PARTIES = 200
HIDDEN_TEXT_WARNING = (
    "This document contains invisible text (white, tiny or off-page letters). It was not sent to Claude — "
    "hidden text is a common trick in scams, so be careful."
)
NO_TEXT_ERROR = "We couldn't find any readable text in this document."
UNEXPECTED_ERROR = "Something went wrong while reading this document. Try “Reprocess”; if it keeps failing, please report it."
TRASHED_ERROR = "This letter was deleted before it was read, so it was not sent to Claude."

_LEDGER_LOCKS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


def ledger_lock() -> asyncio.Lock:
    """The process-wide lock serialising ledger writes (one per running event loop)."""
    loop = asyncio.get_running_loop()
    lock = _LEDGER_LOCKS.get(loop)
    if lock is None:
        lock = _LEDGER_LOCKS[loop] = asyncio.Lock()
    return lock


# --------------------------------------------------------------------------------------------------
# Progress reporting
# --------------------------------------------------------------------------------------------------


class StageReporter:
    """Writes stage/progress to the job row, publishes ``job.progress`` and calls ``on_stage``."""

    def __init__(
        self, ctx: AppContext, doc_id: str, job_id: str | None, on_stage: StageCallback | None
    ) -> None:
        self.ctx = ctx
        self.doc_id = doc_id
        self.job_id = job_id
        self.on_stage = on_stage
        self.current: str = "intake"

    async def stage(self, name: Stage, *, status: Literal["running", "done"] = "running") -> None:
        """Enter stage ``name``."""
        self.current = name
        progress = STAGE_PROGRESS[name]
        if self.job_id is not None:
            self.ctx.store.update_job(self.job_id, stage=name, progress=progress, status=status)
        self.ctx.bus.publish(
            "job.progress",
            job_id=self.job_id,
            doc_id=self.doc_id,
            stage=name,
            progress=progress,
            status=status,
        )
        if self.on_stage is not None:
            result = self.on_stage(name, progress)
            if inspect.isawaitable(result):
                await result

    async def done(self) -> None:
        """The document is finished."""
        await self.stage("done", status="done")

    def failed(self, message: str) -> None:
        """Record a failure on the job and publish it."""
        if self.job_id is not None:
            try:
                self.ctx.store.update_job(self.job_id, status="failed", error=message)
            except NotFoundError:
                log.warning("job %s vanished while failing", self.job_id)
        self.ctx.bus.publish(
            "job.progress",
            job_id=self.job_id,
            doc_id=self.doc_id,
            stage=self.current,
            progress=STAGE_PROGRESS[self.current],
            status="failed",
            error=message,
        )


# --------------------------------------------------------------------------------------------------
# Intake
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Upload:
    data: bytes
    mime: str
    filename: str


def _prepare_upload(data: bytes, filename: str, combine_with: Sequence[bytes] | None) -> _Upload:
    if combine_with:
        combined = combine_images_to_pdf([data, *combine_with])
        filename = f"{Path(filename).stem or 'photos'}.pdf"
        data = combined
    body, mime, name = normalise_upload(data, filename)
    return _Upload(body, mime, name)


def _relative(store: Store, path: Path) -> str:
    try:
        return str(path.relative_to(store.data_dir))
    except ValueError:
        return str(path)


def _page_rows(store: Store, rendered: Sequence[RenderedPage]) -> list[dict[str, object]]:
    return [
        {
            "page": page.page,
            "width": page.width,
            "height": page.height,
            "image_path": _relative(store, page.image_path),
        }
        for page in rendered
    ]


def _iso(value: str | date | None) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise IntakeError(f"“{value}” is not a date — please use the form 2026-09-25.") from exc


def _announce(ctx: AppContext, job: Job) -> None:
    """Tell listeners and the worker that a job is waiting."""
    ctx.bus.publish(
        "job.progress", job_id=job.id, doc_id=job.doc_id, stage="intake", progress=0.0, status="queued"
    )
    ctx.worker.notify()


async def add_file(
    ctx: AppContext,
    data: bytes,
    filename: str,
    *,
    combine_with: Sequence[bytes] | None = None,
    private: bool = False,
    received_date: str | date | None = None,
    source: str = "upload",
) -> Document:
    """Store an upload and queue it for reading; returns the (new or already known) document.

    ``combine_with`` holds more photos of the same letter (one multi-page PDF is made). The same
    bytes always give the same document id, so uploading a file again returns the existing
    document (restored from the trash if needed). ``received_date`` is the day the person says
    the letter arrived. Raises :class:`~ordnung.ingest.intake.IntakeError` for rejected files.
    """
    store = ctx.store
    received = _iso(received_date)
    upload = await asyncio.to_thread(_prepare_upload, data, filename, combine_with)
    stored = await asyncio.to_thread(store_original, store.paths.files, upload.data, upload.filename)
    existing = store.get_document_by_sha(stored.sha256)
    if existing is not None:
        return _known_upload(ctx, existing)
    doc_id = doc_id_for_sha(stored.sha256)
    rendered = await asyncio.to_thread(render_pages, stored.path, stored.mime, store.paths.derived, doc_id)
    try:
        with store.tx():
            document = store.add_document(
                id=doc_id,
                sha256=stored.sha256,
                filename=upload.filename,
                mime=stored.mime,
                file_path=_relative(store, stored.path),
                pages=len(rendered),
                source=source,
                received_date=received,
                ai_private=private,
            )
            store.set_pages(doc_id, _page_rows(store, rendered))
            job = store.enqueue_job("ingest", doc_id)
    except sqlite3.IntegrityError:  # the same file was added concurrently
        concurrent = store.get_document_by_sha(stored.sha256)
        if concurrent is None:
            raise
        return concurrent
    store.log_activity("document.added", f"Added “{upload.filename}”", ref_type="document", ref_id=doc_id)
    _announce(ctx, job)
    return document


def _known_upload(ctx: AppContext, document: Document) -> Document:
    """A re-upload: restore it from the trash, and retry it if reading it failed before."""
    if document.deleted_at:
        document = ctx.store.restore_document(document.id)
    if document.status == "failed":
        document = ctx.store.update_document(document.id, status="queued", error=None)
        _announce(ctx, ctx.store.enqueue_job("ingest", document.id))
    return document


def reprocess(ctx: AppContext, doc_id: str) -> Job:
    """Queue a document to be read again, bypassing the model cache (items the person edited stay)."""
    ctx.store.update_document(doc_id, status="queued", error=None)
    job = ctx.store.enqueue_job("reprocess", doc_id, force=True)
    _announce(ctx, job)
    return job


async def _ensure_pages(store: Store, document: Document) -> list[Page]:
    """The stored pages; re-rendered from the original if they or their images are missing."""
    pages = store.list_pages(document.id)
    if pages and all((store.data_dir / page.image_path).is_file() for page in pages):
        return pages
    original = store.get_document_file(document.id)
    if original is None or not original.is_file():
        raise IntakeError("The original file of this document is missing, so it can't be read again.")
    rendered = await asyncio.to_thread(
        render_pages, original, document.mime, store.paths.derived, document.id
    )
    store.set_pages(document.id, _page_rows(store, rendered))
    store.update_document(document.id, pages=len(rendered))
    return store.list_pages(document.id)


# --------------------------------------------------------------------------------------------------
# Text layer
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TextLayer:
    """Pages after the text stage and what was noticed on them."""

    pages: list[Page]
    hidden: bool
    warnings: list[str]


def _page_texts(store: Store, document: Document, pages: Sequence[Page]) -> list[PageText]:
    original = store.get_document_file(document.id)
    if original is None:
        return []
    if document.mime == "application/pdf":
        rendered = [RenderedPage(p.page, p.width, p.height, store.data_dir / p.image_path) for p in pages]
        return extract_pdf_pages(original, rendered)
    if document.mime in TEXT_TYPES:
        return text_file_pages(original, document.mime)
    return []


def _with_text(page: Page, text: PageText | None) -> Page:
    if text is None:
        return page.model_copy(update={"text": "", "text_source": "none", "words": [], "hidden": ""})
    return page.model_copy(
        update={
            "text": text.text,
            "text_source": text.source,
            "words": [tuple(word.to_row()) for word in text.words],
            "hidden": text.hidden_text,
        }
    )


def read_text_layer(store: Store, document: Document, pages: Sequence[Page]) -> TextLayer:
    """Stage 2: text, words and hidden text of every page from the document's own text layer.

    Pages without enough text get ``text_source="none"`` and are left for transcription.
    """
    texts = {text.page: text for text in _page_texts(store, document, pages)}
    records = store.set_pages(document.id, [_with_text(page, texts.get(page.page)) for page in pages])
    hidden = any(page.hidden.strip() for page in records)
    return TextLayer(pages=records, hidden=hidden, warnings=[HIDDEN_TEXT_WARNING] if hidden else [])


def injection_warnings(pages: Sequence[Page]) -> list[str]:
    """A warning if the (visible or hidden) text addresses an AI system."""
    phrases = detect_injection_phrases("\n".join(f"{page.text}\n{page.hidden}" for page in pages))
    if not phrases:
        return []
    shown = "; ".join(f"“{phrase}”" for phrase in phrases[:3])
    return [
        f"This document contains text addressed to an AI ({shown}). Ordnung treated it as ordinary "
        "content and ignored it — be careful with this document."
    ]


# --------------------------------------------------------------------------------------------------
# Ledger (compute → link → plan in one transaction)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerInput:
    """Everything the ledger transaction needs."""

    document: Document
    extraction: DocumentExtraction
    verification: Verification
    warnings: list[str]
    text_mode: Literal["text", "vision"]
    hidden_text: bool
    today: date
    postal_buffer_days: int
    recipient_region: str | None = None
    country: str = "DE"


def commit_ledger(store: Store, data: LedgerInput) -> PlanResult:
    """Compute dates, link party/case/contract and write the plan — all in one transaction.

    Letter facts the person corrected (title, kind, area, letter date) win over a new reading. The
    payment's IBAN is the one printed on the page when the model misread it
    (:func:`~ordnung.ingest.plan.payment_details`), so the scam check and the sender's known IBANs
    see the account the letter shows.
    """
    with store.tx():
        full_text = store.get_document_text(data.document.id)
        corrected = corrections(data.document, store.get_extraction(data.document.id))
        reading = with_corrections(data.extraction, corrected)
        reading = reading.model_copy(update={"payment": payment_details(reading.payment, full_text)})
        kind = filed_kind(reading, corrected)
        party = ensure_party(store, reading)
        ctx = rule_context(
            party,
            data.document,
            reading,
            data.today,
            recipient_region=data.recipient_region,
            country=data.country,
            filed_as=kind,
        )
        computed = [
            compute_item(verified, ctx, postal_buffer_days=data.postal_buffer_days)
            for verified in data.verification.items
        ]
        links = link_document(
            store,
            document=data.document,
            extraction=reading,
            party=party,
            contract_evidence=data.verification.contract_evidence,
            rule_ctx=ctx,
            postal_buffer_days=data.postal_buffer_days,
        )
        warnings = [
            *data.warnings,
            *data.verification.warnings,
            *remedy_warnings(reading.remedy),
            *links.warnings,
        ]
        return write_plan(
            store,
            document=data.document,
            extraction=reading,
            model_reading=data.extraction,
            today=data.today,
            ctx=ctx,
            postal_buffer_days=data.postal_buffer_days,
            verification=data.verification,
            computed=computed,
            links=links,
            warnings=warnings,
            text_mode=data.text_mode,
            hidden_text=data.hidden_text,
            full_text=full_text,
            kind=kind,
            derived=derived_deadlines(kind, end=ctx.end_date),
        )


# --------------------------------------------------------------------------------------------------
# The stages
# --------------------------------------------------------------------------------------------------


def person_today(store: Store) -> date:
    """The person's today (their time zone, or the pinned demo date) — not the computer's date."""
    from ordnung.tick import local_today  # the tick imports this module

    return local_today(store)


def _refuse_trashed(store: Store, doc_id: str) -> None:
    """A letter in the trash is never sent to the model (it may have been queued before)."""
    current = store.get_document(doc_id)
    if current is not None and current.deleted_at is not None:
        raise IntakeError(TRASHED_ERROR)


def _extraction_input(ctx: AppContext, document: Document, pages: Sequence[Page]) -> ExtractionInput:
    profile = ctx.store.get_profile()
    today = person_today(ctx.store).isoformat()
    return ExtractionInput(
        doc_id=document.id,
        sha256=document.sha256,
        pages=list(pages),
        today=today,
        language=profile.language,
        region=profile.region,
        country=profile.country,
        person_name=profile.name,
        known_parties=ctx.store.list_parties()[:MAX_KNOWN_PARTIES],
        simulated_today=today if clock.simulated() else None,
    )


async def _finish_private(
    ctx: AppContext, document: Document, layer: TextLayer, progress: StageReporter
) -> Document:
    """Private documents: keep the text layer for search; no model ever sees them."""
    await progress.stage("plan")
    title = document.title or document.filename
    updated = ctx.store.update_document(
        document.id,
        title=title,
        status="processed",
        error=None,
        text_mode="text",
        hidden_text=layer.hidden,
        warnings=layer.warnings,
        text=ctx.store.get_document_text(document.id),
        processed_at=now_iso(),
    )
    ctx.store.log_activity(
        "document.private",
        f"Stored “{title}” privately · not sent to AI",
        ref_type="document",
        ref_id=document.id,
    )
    await progress.done()
    return updated


async def _run_stages(
    ctx: AppContext, document: Document, progress: StageReporter, *, force: bool
) -> Document:
    store, models = ctx.store, ctx.settings.models
    await progress.stage("intake")
    pages = await _ensure_pages(store, document)
    await progress.stage("text")
    layer = await asyncio.to_thread(read_text_layer, store, document, pages)
    if document.ai_private:
        return await _finish_private(ctx, document, layer, progress)
    _refuse_trashed(store, document.id)
    await progress.stage("transcribe")
    warnings = [*layer.warnings]
    warnings += await transcribe_pages(
        ctx.llm, store, document.id, layer.pages, model=models.transcribe, use_cache=not force
    )
    pages = store.list_pages(document.id)
    if not prompt_pages(pages):
        raise ExtractionError(NO_TEXT_ERROR)
    warnings += injection_warnings(pages)
    _refuse_trashed(store, document.id)
    await progress.stage("extract")
    extraction = await extract_document(
        ctx.llm, _extraction_input(ctx, document, pages), model=models.extract, use_cache=not force
    )
    await progress.stage("verify")
    verification = await asyncio.to_thread(verify_extraction, document.id, extraction, pages)
    await progress.stage("compute")
    profile = store.get_profile()
    data = LedgerInput(
        document=store.get_document(document.id) or document,
        extraction=extraction,
        verification=verification,
        warnings=warnings,
        text_mode="vision" if any(page.text_source == "transcript" for page in pages) else "text",
        hidden_text=layer.hidden,
        today=person_today(store),
        postal_buffer_days=max(profile.postal_buffer_days, POSTAL_BUFFER_DAYS),
        recipient_region=profile.known_region,
        country=profile.country,
    )
    async with ledger_lock():
        result = await asyncio.to_thread(commit_ledger, store, data)
    await progress.stage("link")
    await progress.stage("plan")
    await progress.done()
    return result.document


def describe_error(exc: BaseException) -> str:
    """A message for the person: the error's own text when it is written for people."""
    if isinstance(exc, IntakeError | LLMError | ExtractionError) and str(exc):
        return str(exc)
    if isinstance(exc, NotFoundError):
        return "This document no longer exists."
    return UNEXPECTED_ERROR


def _mark_failed(store: Store, doc_id: str, message: str) -> None:
    try:
        store.update_document(doc_id, status="failed", error=message)
    except NotFoundError:
        log.info("document %s was deleted while it was being read", doc_id)


async def ingest_document(
    ctx: AppContext,
    doc_id: str,
    *,
    force: bool = False,
    on_stage: StageCallback | None = None,
    job_id: str | None = None,
) -> Document:
    """Read one document end to end and return it (status ``processed`` or ``needs_review``).

    ``force`` bypasses the model cache (reprocess). ``on_stage(stage, progress)`` may be sync or
    async. With ``job_id`` the job row follows the stages and ends ``done`` or ``failed``.
    On failure the document becomes ``failed`` with a readable ``error`` and the exception is
    re-raised — except a rate limit, which puts the document back to ``queued`` for the worker.
    """
    store = ctx.store
    progress = StageReporter(ctx, doc_id, job_id, on_stage)
    try:
        document = store.get_document(doc_id)
        if document is None:
            raise NotFoundError(f"documents: no row with id {doc_id!r}")
        _refuse_trashed(store, doc_id)
        store.update_document(doc_id, status="processing", error=None)
        document = await _run_stages(ctx, document, progress, force=force)
    except (ClaudeRateLimited, asyncio.CancelledError):
        _set_status_quietly(store, doc_id, "queued")
        raise
    except Exception as exc:
        message = describe_error(exc)
        log.warning("reading document %s failed: %s", doc_id, message, exc_info=message == UNEXPECTED_ERROR)
        _mark_failed(store, doc_id, message)
        progress.failed(message)
        raise
    ctx.bus.publish("document.processed", doc_id=doc_id, status=document.status)
    return document


def _set_status_quietly(store: Store, doc_id: str, status: Literal["queued"]) -> None:
    try:
        store.update_document(doc_id, status=status)
    except NotFoundError:
        log.info("document %s was deleted while it was being read", doc_id)


# --------------------------------------------------------------------------------------------------
# Triggers hook
# --------------------------------------------------------------------------------------------------

TriggersHook = Callable[[Store, date], object]


def triggers_hook() -> TriggersHook | None:
    """``ordnung.secretary.triggers.run_and_reconcile`` if that module exists (else ``None``)."""
    try:
        module = importlib.import_module("ordnung.secretary.triggers")
    except ModuleNotFoundError as exc:
        if exc.name != "ordnung.secretary.triggers":
            log.warning("the triggers module could not be imported", exc_info=True)
        return None
    except ImportError:
        log.warning("the triggers module could not be imported", exc_info=True)
        return None
    hook = getattr(module, "run_and_reconcile", None)
    return hook if callable(hook) else None


async def run_triggers(ctx: AppContext) -> bool:
    """Run the deterministic triggers (Ideas) after ledger changes; ``False`` if unavailable or failed.

    Never raises: a broken trigger must not fail the document that was just read.
    """
    hook = triggers_hook()
    if hook is None:
        return False
    try:
        async with ledger_lock():
            result = await asyncio.to_thread(hook, ctx.store, person_today(ctx.store))
            if inspect.isawaitable(result):
                await result
    except Exception:
        log.warning("running the triggers failed", exc_info=True)
        return False
    ctx.bus.publish("suggestions.updated")
    return True
