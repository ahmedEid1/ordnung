"""The ingestion pipeline (SPEC § 8, § 21): intake → text → transcribe → extract → verify →
compute → link → plan → done. A stage that doesn't happen isn't reported: a photo has no "text"
stage, a PDF whose every page has its own text no "transcribe".

* :func:`add_file` validates an upload, stores the original content-addressed (the document id is
  derived from its SHA-256, so a re-upload is a no-op), renders the pages and queues an ingest job.
* :func:`ingest_document` runs the stages for one document, keeping the job row and the event bus
  up to date (``job.progress`` {job_id, doc_id, stage, progress, status}, then
  ``document.processed`` {doc_id, status}). CPU work runs in ``asyncio.to_thread``. Compute, link and
  plan share **one** ``store.tx()`` under the process-wide :func:`ledger_lock`; their stage events
  are published once that transaction has committed.
* Private documents ("Keep private — no AI") stop after the text layer: no model call ever sees them.
  So do *held* ones (``hold=True``: files from the watched folder, :mod:`ordnung.ingest.held`), which
  end ``held`` instead of ``processed`` and publish no stage events (nothing is being read) until the
  person says they may be read.
* A proof file (``source="proof"``, :mod:`ordnung.drafts.sent`) is stored like a private letter, but no
  ``job.progress`` about it is ever published — not queued, not a stage, not a failure: it is no letter
  and nothing of it is read, so it never shows in the web app's "letters being read" corner (adding it
  says so itself).
* An e-mail's attachments (PDFs and photos) are added as documents of their own right after it, with
  its privacy choice (:mod:`ordnung.ingest.attachments`); what became of each is logged on the e-mail.
* Letters moved to the trash while they waited in the queue (or while being read) are never sent to
  the model: the job fails with :data:`TRASHED_ERROR`; uploading the file again restores and reads it.
* "Today" is the person's (profile time zone or the pinned demo date, :func:`ordnung.tick.local_today`),
  never the computer's clock.
"""

from __future__ import annotations

import asyncio
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
from ordnung.ingest import held as consent
from ordnung.ingest.attachments import (
    ATTACHMENTS_ACTIVITY,
    EMAIL_MIME,
    OUTCOME_DETAIL,
    Attachment,
    email_attachments,
    email_parent,
    email_source,
)
from ordnung.ingest.extract import (
    ExtractionError,
    ExtractionInput,
    prompt_pages,
    read_document,
    reask_warning,
)
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
from ordnung.ingest.own_files import OWN_LETTER, is_own_file
from ordnung.ingest.plan import (
    KIND_CHOSEN,
    ComputedDate,
    PaymentNote,
    PlanResult,
    Verification,
    VerifiedItem,
    compute_item,
    corrections,
    filed_kind,
    for_item,
    law_deadlines,
    needs_check,
    payment_details,
    payment_note,
    remedy_warnings,
    rule_context,
    verify_extraction,
    with_corrections,
    with_payment_note,
    write_plan,
)
from ordnung.ingest.text import (
    PageText,
    detect_injection_phrases,
    email_heading,
    extract_pdf_pages,
    text_file_pages,
)
from ordnung.ingest.transcribe import pages_to_transcribe, transcribe_pages
from ordnung.llm.base import ClaudeAuthError, ClaudeNotInstalled, ClaudeRateLimited, ClaudeTimeout, LLMError
from ordnung.models import (
    PROOF_SOURCE,
    Direction,
    Document,
    DocumentExtraction,
    EmailAttachment,
    Job,
    Page,
    Party,
)
from ordnung.rules.deadlines import POSTAL_BUFFER_DAYS, RuleContext, parse_date
from ordnung.secretary.triggers import is_scam_warning, run_and_reconcile
from ordnung.trace import facts
from ordnung.trace.runs import finish_trace, start_trace
from ordnung.trace.spans import NO_SPAN, Span

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
#: How the warning about text addressed to an AI starts (:func:`injection_warnings`).
INJECTION_WARNING = "This document contains text addressed to an AI"
NO_TEXT_ERROR = "We couldn't find any readable text in this document."
UNEXPECTED_ERROR = "Something went wrong while reading this letter. Press “Try again”; if it keeps failing, please report it."
TRASHED_ERROR = "This letter was deleted before it was read, so it was not sent to Claude."
#: The letter was put in the trash (or deleted) while Claude was reading it: no further call sends it again (the
#: repair, the completeness re-ask) — it was sent once, so the message says so.
TRASHED_AGAIN_ERROR = (
    "This letter was deleted while Claude was reading it, so it was not sent to Claude again."
)

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
        #: A held letter is only stored, not read: its stages are not announced (a failure still is).
        self.quiet = False
        #: A proof file is no letter (:func:`unannounced`): nothing of its job is announced, not even a failure.
        self.silent = False

    async def stage(self, name: Stage, *, status: Literal["running", "done"] = "running") -> None:
        """Enter stage ``name``."""
        self.current = name
        progress = STAGE_PROGRESS[name]
        if self.job_id is not None:
            self.ctx.store.update_job(self.job_id, stage=name, progress=progress, status=status)
        if not (self.quiet or self.silent):
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
        if self.silent:
            return
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


def unannounced(document: Document) -> bool:
    """Whether no ``job.progress`` of ``document`` is ever published: a proof of a sent letter's own file
    (see the module docstring)."""
    return document.source == PROOF_SOURCE


def announce_job(ctx: AppContext, job: Job, *, quiet: bool = False) -> None:
    """Tell listeners (unless ``quiet``: a held letter is only stored, a proof file is no letter) and the
    worker that a job waits."""
    if not quiet:
        ctx.bus.publish(
            "job.progress", job_id=job.id, doc_id=job.doc_id, stage="intake", progress=0.0, status="queued"
        )
    ctx.worker.notify()


@dataclass(frozen=True)
class Added:
    """What :func:`add_file_result` did: the document, and whether this call created it."""

    document: Document
    new: bool


async def add_file(
    ctx: AppContext,
    data: bytes,
    filename: str,
    *,
    combine_with: Sequence[bytes] | None = None,
    private: bool = False,
    hold: bool = False,
    answer_held: bool = False,
    received_date: str | date | None = None,
    source: str = "upload",
    restore_trashed: bool = True,
    direction: Direction = "incoming",
    with_attachments: bool = True,
) -> Document:
    """Store an upload and queue it for reading; returns the (new or already known) document.

    ``combine_with`` holds more photos of the same letter (one multi-page PDF is made). The same
    bytes always give the same document id, so uploading a file again returns the existing
    document (restored from the trash if needed, unless ``restore_trashed`` is off). ``hold`` keeps
    it private and ``held`` until the person says it may be read (:mod:`ordnung.ingest.held`).
    ``answer_held`` says the person added this file by hand (an upload, the command line): adding a
    held file again then answers its question (``private``: keep it private, else read it). Nothing
    else ever answers for the person — a copy of a waiting file arriving in the watched folder leaves
    it waiting, whatever ``inbox_auto_read`` says. ``received_date`` is the day the person says the
    letter arrived; ``direction`` is ``outgoing`` for what the person sent (proof of a
    letter). An e-mail's attachments are added right after it, with its ``hold``, ``private``
    and ``answer_held`` (:mod:`ordnung.ingest.attachments`) — unless ``with_attachments`` is off:
    a sent e-mail kept as proof is one file, and its attachments never become letters received.
    Raises :class:`~ordnung.ingest.intake.IntakeError` for rejected files.
    """
    added = await add_file_result(
        ctx,
        data,
        filename,
        combine_with=combine_with,
        private=private,
        hold=hold,
        answer_held=answer_held,
        received_date=received_date,
        source=source,
        restore_trashed=restore_trashed,
        direction=direction,
        with_attachments=with_attachments,
    )
    return added.document


async def add_file_result(
    ctx: AppContext,
    data: bytes,
    filename: str,
    *,
    combine_with: Sequence[bytes] | None = None,
    private: bool = False,
    hold: bool = False,
    answer_held: bool = False,
    received_date: str | date | None = None,
    source: str = "upload",
    restore_trashed: bool = True,
    direction: Direction = "incoming",
    with_attachments: bool = True,
) -> Added:
    """:func:`add_file`, telling a new document from one Ordnung already had."""
    store = ctx.store
    received = _iso(received_date)
    upload = await asyncio.to_thread(_prepare_upload, data, filename, combine_with)
    stored = await asyncio.to_thread(store_original, store.paths.files, upload.data, upload.filename)
    existing = store.get_document_by_sha(stored.sha256)
    if existing is not None:
        known = _known_upload(
            ctx, existing, private=private, answer=answer_held and not hold, restore_trashed=restore_trashed
        )
        if with_attachments and _attachments_unrecorded(store, known):  # stopped before its attachments
            waits = consent.is_held(known)
            await _add_attachments(
                ctx,
                known,
                upload.data,
                private=known.ai_private and not waits,
                hold=waits,
                answer_held=False,
                received=known.received_date,
                restore=restore_trashed,
            )
        return Added(known, new=False)
    doc_id = doc_id_for_sha(stored.sha256)
    try:
        rendered = await asyncio.to_thread(
            render_pages, stored.path, stored.mime, store.paths.derived, doc_id
        )
        with store.tx():
            document = store.add_document(
                id=doc_id,
                sha256=stored.sha256,
                filename=upload.filename,
                mime=stored.mime,
                file_path=_relative(store, stored.path),
                pages=len(rendered),
                source=source,
                direction=direction,
                received_date=received,
                status="held" if hold else "queued",
                ai_private=private or hold,
            )
            store.set_pages(doc_id, _page_rows(store, rendered))
            job = store.enqueue_job("ingest", doc_id)
    except Exception as exc:
        if isinstance(exc, sqlite3.IntegrityError):  # the same file was added concurrently
            concurrent = store.get_document_by_sha(stored.sha256)
            if concurrent is not None:
                return Added(concurrent, new=False)
        # refused (a page that can't be rendered …): its file and page images go too, unless a
        # document has that file
        store.discard_upload(stored.sha256, doc_id, stored.path)
        raise
    store.log_activity(
        "document.added",
        _added_message(store, upload.filename, source, hold),
        ref_type="document",
        ref_id=doc_id,
        data={"source": source, "held": hold, "filename": upload.filename},
    )
    announce_job(ctx, job, quiet=hold or unannounced(document))
    if with_attachments and stored.mime == EMAIL_MIME:
        await _add_attachments(
            ctx,
            document,
            upload.data,
            private=private,
            hold=hold,
            answer_held=answer_held,
            received=received,
            restore=restore_trashed,
        )
    return Added(document, new=True)


def _attachments_unrecorded(store: Store, document: Document) -> bool:
    """An e-mail (not in the trash) with no record of its attachments: adding it was stopped before
    they were added (an e-mail without attachments has none either; looking again adds nothing). Never
    an e-mail kept as proof of a sent letter: it was stored without its attachments on purpose — they
    are what the person sent, not letters received (``with_attachments``)."""
    return (
        document.mime == EMAIL_MIME
        and document.deleted_at is None
        and not consent.is_proof(store, document)
        and store.last_activity("document", document.id, [ATTACHMENTS_ACTIVITY]) is None
    )


def _added_message(store: Store, filename: str, source: str, hold: bool) -> str:
    """The activity line of a new document: where it came from, and whether it waits for the person."""
    parent_id = email_parent(source)
    parent = store.get_document(parent_id) if parent_id else None
    if source == "folder":
        origin = " from your watched folder"
    elif source == "phone":
        origin = " from your phone"
    elif parent is not None:
        origin = f" from the e-mail “{parent.title or parent.filename}”"
    else:
        origin = ""
    return f"Added “{filename}”{origin}" + (" · not read yet" if hold else "")


def _known_upload(
    ctx: AppContext, document: Document, *, private: bool, answer: bool, restore_trashed: bool
) -> Document:
    """A re-upload: restore it from the trash (an e-mail with its attachments) unless that is not
    wanted, retry it if reading it failed before, and — ``answer``: added again by hand — answer a
    held letter's question (:mod:`ordnung.ingest.held`)."""
    store = ctx.store
    if document.deleted_at:
        if not restore_trashed:
            return document
        document = store.restore_document(document.id)
        for attachment in store.list_documents(source=email_source(document.id), include_deleted=True):
            if attachment.deleted_at:
                store.restore_document(attachment.id)
    if document.status == "failed":
        document = store.update_document(document.id, status="queued", error=None)
        announce_job(ctx, store.enqueue_job("ingest", document.id), quiet=unannounced(document))
    elif consent.is_held(document) and answer:
        reply = consent.keep_private if private else consent.release
        for job in reply(store, [document.id]).jobs:
            announce_job(ctx, job)
        document = store.get_document(document.id) or document
    return document


async def _add_attachments(
    ctx: AppContext,
    email_doc: Document,
    data: bytes,
    *,
    private: bool,
    hold: bool,
    answer_held: bool,
    received: str | None,
    restore: bool,
) -> None:
    """Add an e-mail's attachments as documents of their own and record what became of each."""
    parts = await asyncio.to_thread(email_attachments, data)
    if not parts.attachments:
        return
    rows = [
        await _add_attachment(
            ctx,
            email_doc,
            attachment,
            private=private,
            hold=hold,
            answer_held=answer_held,
            received=received,
            restore=restore,
        )
        for attachment in parts.attachments
    ]
    ctx.store.log_activity(
        ATTACHMENTS_ACTIVITY,
        _attachments_message(email_doc.filename, rows, parts.more),
        ref_type="document",
        ref_id=email_doc.id,
        data={"attachments": [row.model_dump() for row in rows], "more": parts.more},
    )


async def _add_attachment(
    ctx: AppContext,
    email_doc: Document,
    attachment: Attachment,
    *,
    private: bool,
    hold: bool,
    answer_held: bool,
    received: str | None,
    restore: bool,
) -> EmailAttachment:
    if attachment.decision != "read":
        return EmailAttachment(
            filename=attachment.filename,
            outcome=attachment.decision,
            detail=OUTCOME_DETAIL[attachment.decision],
        )
    # a letter Ordnung drafted (the profile's address and IBAN), attached to a sent e-mail: never a
    # letter received, never sent to Claude (:mod:`ordnung.ingest.own_files`)
    if await asyncio.to_thread(is_own_file, ctx.store, attachment.data):
        return EmailAttachment(filename=attachment.filename, outcome="refused", detail=OWN_LETTER)
    try:
        added = await add_file_result(
            ctx,
            attachment.data,
            attachment.filename,
            private=private,
            hold=hold,
            answer_held=answer_held,
            received_date=received,
            source=email_source(email_doc.id),
            restore_trashed=restore,
        )
    except IntakeError as exc:
        return EmailAttachment(filename=attachment.filename, outcome="refused", detail=str(exc))
    outcome: Literal["added", "known"] = "added" if added.new else "known"
    return EmailAttachment(
        filename=attachment.filename,
        outcome=outcome,
        detail=OUTCOME_DETAIL[outcome],
        doc_id=added.document.id,
    )


def _attachments_message(filename: str, rows: Sequence[EmailAttachment], more: int) -> str:
    """The activity line, e.g. “Attachments of x.eml: 1 added as its own letter, 2 not read”."""
    added = sum(row.outcome == "added" for row in rows)
    known = sum(row.outcome == "known" for row in rows)
    other = len(rows) - added - known + more
    parts = [
        f"{added} added as {'its own letter' if added == 1 else 'letters of their own'}" if added else "",
        f"{known} already in Ordnung" if known else "",
        f"{other} not read" if other else "",
    ]
    return f"Attachments of “{filename}”: " + ", ".join(part for part in parts if part)


def reprocess(ctx: AppContext, doc_id: str) -> Job:
    """Queue a document to be read again, bypassing the model cache (items the person edited stay)."""
    document = ctx.store.update_document(doc_id, status="queued", error=None)
    job = ctx.store.enqueue_job("reprocess", doc_id, force=True)
    announce_job(ctx, job, quiet=unannounced(document))
    return job


def release_held(ctx: AppContext, doc_ids: Sequence[str]) -> consent.ConsentResult:
    """“Read these”: the held letters (and a held e-mail's held attachments) are queued for reading."""
    result = consent.release(ctx.store, doc_ids)
    for job in result.jobs:
        announce_job(ctx, job)
    return result


def keep_held_private(ctx: AppContext, doc_ids: Sequence[str]) -> consent.ConsentResult:
    """“Keep private”: the held letters stay on this computer (one whose reading here failed is
    stored again)."""
    result = consent.keep_private(ctx.store, doc_ids)
    for job in result.jobs:
        announce_job(ctx, job)
    return result


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


def has_text_layer(document: Document) -> bool:
    """A PDF or a text/e-mail file may carry its own text; a photo never does."""
    return document.mime == "application/pdf" or document.mime in TEXT_TYPES


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
        f"{INJECTION_WARNING} ({shown}). Ordnung treated it as ordinary content and ignored it — be careful "
        "with this document."
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


def compute_dates(
    verified_items: Sequence[VerifiedItem],
    ctx: RuleContext,
    *,
    postal_buffer_days: int,
    note: PaymentNote | None,
    trace: Span = NO_SPAN,
) -> list[ComputedDate]:
    """The rules engine's dates for a reading's items (with the letter's payment note); ``trace`` gets
    a ``rules`` step with one step per dated to-do (:func:`ordnung.trace.facts.dated`)."""
    computed = []
    with trace.span("rules", "Compute dates", key="dates", stage="compute") as step:
        for index, verified in enumerate(verified_items):
            item_step = step if verified.dated else NO_SPAN
            with item_step.span("rules", "Date", key=f"item:{verified.slot_key}") as date_step:
                result = with_payment_note(
                    compute_item(
                        verified, for_item(ctx, verified.item, note), postal_buffer_days=postal_buffer_days
                    ),
                    verified.item,
                    note,
                )
                date_step.set(
                    **facts.dated(
                        verified.item.date,
                        result.receipt,
                        source=result.source,
                        index=index,
                        slot_key=verified.slot_key,
                    )
                )
            computed.append(result)
        step.set(items=len(computed), dated=sum(verified.dated for verified in verified_items))
    return computed


def commit_ledger(store: Store, data: LedgerInput, *, trace: Span = NO_SPAN) -> PlanResult:
    """Compute dates, link party/case/contract and write the plan — all in one transaction.

    Letter facts the person corrected (title, kind, area, letter date) win over a new reading. The
    payment's IBAN is the one printed on the page when the model misread it
    (:func:`~ordnung.ingest.plan.payment_details`), so the scam check and the sender's known IBANs
    see the account the letter shows. The letter is read again inside the transaction (the caller
    holds :func:`ledger_lock`): a kind the person chose while it was being read — the patch and its
    :data:`KIND_CHOSEN` entry are written together under the same lock — is kept. ``trace`` gets the
    steps in the order they run: the sender, the dates, the links, the plan.
    """
    with store.tx():
        document = store.get_document(data.document.id) or data.document
        full_text = store.get_document_text(document.id)
        chosen = store.last_activity("document", document.id, [KIND_CHOSEN])
        corrected = corrections(
            document,
            store.get_extraction(document.id),
            chosen_kind=chosen.data.get("kind") if chosen else None,
        )
        reading = with_corrections(data.extraction, corrected)
        reading = reading.model_copy(update={"payment": payment_details(reading.payment, full_text)})
        kind = filed_kind(reading, corrected)
        with trace.span("link", "Sender", key="sender", stage="link") as step:
            party = ensure_party(store, reading, trace=step)
        ctx = rule_context(
            party,
            document,
            reading,
            data.today,
            recipient_region=data.recipient_region,
            country=data.country,
            filed_as=kind,
            pages=store.list_pages(document.id),
        )
        chosen_as_filed = chosen is not None and chosen.data.get("kind") == kind
        note = payment_note(kind, reading, reading.title, full_text, ctx, chosen=chosen_as_filed)
        computed = compute_dates(
            data.verification.items, ctx, postal_buffer_days=data.postal_buffer_days, note=note, trace=trace
        )
        links = link_document(
            store,
            document=document,
            extraction=reading,
            party=party,
            contract_evidence=data.verification.contract_evidence,
            rule_ctx=ctx,
            postal_buffer_days=data.postal_buffer_days,
            trace=trace,
        )
        warnings = [
            *data.warnings,
            *data.verification.warnings,
            *remedy_warnings(reading.remedy),
            *links.warnings,
        ]
        return write_plan(
            store,
            document=document,
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
            derived=law_deadlines(kind, reading, ctx),
            trace=trace,
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


def _refuse_gone(store: Store, doc_id: str) -> None:
    """Before a further call sends the letter again (the repair, the completeness re-ask): never once it was
    deleted for good or put in the trash while the call before it ran."""
    current = store.get_document(doc_id)
    if current is None:
        raise NotFoundError(f"documents: no row with id {doc_id!r}")
    if current.deleted_at is not None:
        raise IntakeError(TRASHED_AGAIN_ERROR)


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
        known_parties=_known_parties(ctx.store),
        simulated_today=today if clock.simulated() else None,
    )


def _known_parties(store: Store) -> list[Party]:
    """The senders a reading's prompt names (at most :data:`MAX_KNOWN_PARTIES`): never one first seen on a
    letter with scam signs or text addressed to an AI — that letter may have planted the name (SPEC § 21)."""
    first: dict[str, Document] = {}
    for document in store.list_documents(include_deleted=True):
        seen = first.get(document.party_id or "")
        if document.party_id and (
            seen is None or (document.created_at, document.id) < (seen.created_at, seen.id)
        ):
            first[document.party_id] = document
    planted = {party_id for party_id, document in first.items() if _suspicious(document)}
    return [party for party in store.list_parties() if party.id not in planted][:MAX_KNOWN_PARTIES]


def _suspicious(document: Document) -> bool:
    """A letter with scam signs in its reading (hidden text, a scam-like warning) or text addressed to an AI."""
    return document.hidden_text or any(
        is_scam_warning(warning) or warning.startswith(INJECTION_WARNING) for warning in document.warnings
    )


def _local_title(store: Store, document: Document) -> str | None:
    """A title found without any model: an e-mail's subject and sender, as the mail program showed
    them (so the person knows what they are asked about); ``None`` for other files."""
    if document.mime != EMAIL_MIME:
        return None
    original = store.get_document_file(document.id)
    return email_heading(original.read_bytes()) if original is not None else None


async def _finish_private(
    ctx: AppContext, document: Document, layer: TextLayer, progress: StageReporter, trace: Span = NO_SPAN
) -> Document:
    """Private and held documents: keep the text layer for search; no model ever sees them. An
    e-mail is titled by its subject and sender (:func:`~ordnung.ingest.text.email_heading`).

    The letter is read again first, so an answer the person gave while this ran stands: one they let
    Claude read is left to its reading job, one they kept private ends private.
    """
    await progress.stage("plan")
    store = ctx.store
    current = store.get_document(document.id) or document
    # the title first (it reads the file, outside the transaction): the answer is checked after it
    title = current.title
    if current.ai_private and not title:
        title = await asyncio.to_thread(_local_title, store, current)
    with store.tx():
        latest = store.get_document(document.id)
        if latest is None:  # deleted while it was stored: nothing to write
            await progress.done()
            return current
        held = latest.status == "held"
        # how this reading ended: the letter's status (a held one keeps waiting; one let through is read next)
        ended = ("held" if held else "processed") if latest.ai_private else latest.status
        if latest.ai_private:  # never after "Read these" (not private any more): its reading job reads it
            name = latest.title or title or latest.filename
            latest = store.update_document(
                document.id,
                title=name,
                status="held" if held else "processed",
                error=None,
                text_mode="text",
                hidden_text=layer.hidden,
                warnings=layer.warnings,
                text=store.get_document_text(document.id),
                processed_at=now_iso(),
            )
            store.log_activity(
                "document.held" if held else "document.private",
                f"Stored “{name}” on this computer · not read yet"
                if held
                else f"Stored “{name}” privately · not sent to Claude",
                ref_type="document",
                ref_id=document.id,
            )
    trace.set(**_outcome(ended, "text", layer.pages, items=0, needs_review=0, warnings=layer.warnings))
    await progress.done()
    return latest


def _outcome(
    status: str,
    text_mode: str | None,
    pages: Sequence[Page],
    *,
    items: int,
    needs_review: int,
    warnings: Sequence[str],
) -> dict[str, object]:
    return facts.outcome(
        result=status,
        text_mode=text_mode,
        pages=len(pages),
        items=items,
        needs_check=needs_review,
        warnings=len(warnings),
    )


async def _run_stages(
    ctx: AppContext, document: Document, progress: StageReporter, *, force: bool, trace: Span = NO_SPAN
) -> Document:
    store, models = ctx.store, ctx.settings.models
    trace.set(private=document.ai_private)
    await progress.stage("intake")
    pages = await _ensure_pages(store, document)
    # the stepper says what really happens: a PDF's own text is read, a photo (or a page without text)
    # is transcribed — never "Reading the photo" for a PDF with text, nor "Reading the text" for a photo
    if has_text_layer(document):
        await progress.stage("text")
    with trace.span("ocr", "Text layer", key="text", stage="text") as step:
        layer = await asyncio.to_thread(read_text_layer, store, document, pages)
        step.set(**facts.text_layer(layer.pages, layer.hidden))
    if document.ai_private:
        return await _finish_private(ctx, document, layer, progress, trace)
    _refuse_trashed(store, document.id)
    if pages_to_transcribe(layer.pages):
        await progress.stage("transcribe")
    warnings = [*layer.warnings]
    warnings += await transcribe_pages(
        ctx.llm, store, document.id, layer.pages, model=models.transcribe, use_cache=not force, trace=trace
    )
    pages = store.list_pages(document.id)
    if not prompt_pages(pages):
        raise ExtractionError(NO_TEXT_ERROR)
    injected = injection_warnings(pages)
    warnings += injected
    _refuse_trashed(store, document.id)
    await progress.stage("extract")
    arrived = parse_date(document.received_date) or person_today(store)
    reading = await read_document(
        ctx.llm,
        _extraction_input(ctx, document, pages),
        model=models.extract,
        use_cache=not force,
        trace=trace,
        # a re-ask that gets no answer keeps the first reading and the check behind it: never a failed letter
        unanswered=(LLMError,),
        # the repair and the re-ask send the letter again: never once it was trashed or deleted meanwhile
        before_again=lambda: _refuse_gone(store, document.id),
        # judged against the very to-do the check at verify would file
        arrived=arrived,
        injected=bool(injected),
    )
    extraction = reading.extraction
    if reading.completion is not None and reading.completion.accepted:
        warnings.append(reask_warning(reading.completion.gap, injected=bool(injected)))
    await progress.stage("verify")
    verification = await asyncio.to_thread(
        verify_extraction,
        document.id,
        extraction,
        pages,
        trace=trace,
        check_reading=True,
        injected=bool(injected),
        today=arrived,
        cross_check=reading.cross_check,
    )
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
        result = await asyncio.to_thread(commit_ledger, store, data, trace=trace)
    trace.set(
        **_outcome(
            result.document.status,
            data.text_mode,
            pages,
            items=len(result.items),
            needs_review=sum(needs_check(item) for item in result.items),
            warnings=result.document.warnings,
        )
    )
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


def failure_code(exc: BaseException) -> str:
    """Why a reading failed, as the code its trace keeps (:data:`ordnung.trace.runs.FAILURES`) — an
    error's message may quote the letter or the model, so a trace never keeps it."""
    if isinstance(exc, IntakeError):
        return {TRASHED_ERROR: "trashed", TRASHED_AGAIN_ERROR: "trashed_meanwhile"}.get(str(exc), "file")
    if isinstance(exc, ExtractionError):
        return "no_text" if str(exc) == NO_TEXT_ERROR else "unusable_answer"
    if isinstance(exc, NotFoundError):
        return "gone"
    if isinstance(exc, ClaudeTimeout):
        return "timeout"
    return "claude_error" if isinstance(exc, LLMError) else "unexpected"


def pause_code(exc: ClaudeRateLimited | ClaudeNotInstalled | ClaudeAuthError) -> str:
    """Why a reading paused, as the code its trace keeps (:data:`ordnung.trace.runs.INTERRUPTIONS`)."""
    if isinstance(exc, ClaudeNotInstalled):
        return "paused_not_installed"
    if isinstance(exc, ClaudeAuthError):
        return "paused_not_signed_in"
    return "paused"


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
    re-raised — except a rate limit, Claude not installed or not signed in, or a stop, which put the
    document back to ``queued`` for the worker (no failure is announced; the reading's trace ends
    ``paused`` or ``stopped``) and re-raise. A held letter (:mod:`ordnung.ingest.held`) keeps waiting whatever happens to its local
    job: stopped or failed, its status stays as the person's answer left it (``held`` until they
    answer), and a failure is only written to ``error``. Every reading, however it ends, is kept as a
    trace (:mod:`ordnung.trace.runs`).
    """
    store = ctx.store
    progress = StageReporter(ctx, doc_id, job_id, on_stage)
    tracer = start_trace(store, doc_id, job_id=job_id, again=force, recorded=ctx.settings.demo)
    try:
        document = store.get_document(doc_id)
        if document is None:
            raise NotFoundError(f"documents: no row with id {doc_id!r}")
        # a held letter is only stored: it keeps waiting meanwhile — and whatever happens (even in the trash)
        progress.quiet = document.status == consent.HELD
        progress.silent = unannounced(document)
        _refuse_trashed(store, doc_id)
        if not progress.quiet:
            store.update_document(doc_id, status="processing", error=None)
        document = await _run_stages(ctx, document, progress, force=force, trace=tracer.root)
    except (ClaudeRateLimited, ClaudeNotInstalled, ClaudeAuthError) as exc:
        if not progress.quiet:
            _set_status_quietly(store, doc_id, "queued")
        finish_trace(store, tracer, "paused", pause_code(exc))
        raise
    except asyncio.CancelledError:
        if not progress.quiet:
            _set_status_quietly(store, doc_id, "queued")
        finish_trace(store, tracer, "stopped")
        raise
    except Exception as exc:
        message = describe_error(exc)
        log.warning("reading document %s failed: %s", doc_id, message, exc_info=message == UNEXPECTED_ERROR)
        if progress.quiet:
            _note_held_error(store, doc_id, message)
        else:
            _mark_failed(store, doc_id, message)
        progress.failed(message)
        finish_trace(store, tracer, "failed", failure_code(exc))
        raise
    finish_trace(store, tracer)
    ctx.bus.publish("document.processed", doc_id=doc_id, status=document.status)
    return document


def _note_held_error(store: Store, doc_id: str, message: str) -> None:
    """A held letter's local job failed: it keeps waiting (and the status its answer gave it, should
    the person have answered meanwhile) with the reason in ``error``."""
    try:
        store.update_document(doc_id, error=message)
    except NotFoundError:
        log.info("document %s was deleted while it was being read", doc_id)


def _set_status_quietly(store: Store, doc_id: str, status: Literal["queued"]) -> None:
    try:
        store.update_document(doc_id, status=status)
    except NotFoundError:
        log.info("document %s was deleted while it was being read", doc_id)


# --------------------------------------------------------------------------------------------------
# Triggers
# --------------------------------------------------------------------------------------------------


async def run_triggers(ctx: AppContext) -> bool:
    """Run the deterministic triggers (Ideas) after ledger changes; ``False`` if they failed.

    Never raises: a broken trigger must not fail the document that was just read.
    """
    try:
        async with ledger_lock():
            await asyncio.to_thread(run_and_reconcile, ctx.store, person_today(ctx.store))
    except Exception:
        log.warning("running the triggers failed", exc_info=True)
        return False
    ctx.bus.publish("suggestions.updated")
    return True
