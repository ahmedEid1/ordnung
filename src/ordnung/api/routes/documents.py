"""Letters: upload, list, detail, edit, reprocess, delete, and their files (original, pages, thumbnail).

Uploads (``POST /api/documents``, multipart): ``files`` (``files[]`` is accepted too), ``combine``
(all photos of the upload become one multi-page letter; other files stay separate documents) and
``private`` ("Keep private — no AI"). The response lists the documents queued for reading with their
jobs; files that were already in Ordnung are reported by id in ``duplicates``, rejected files in
``errors``. Deleting moves a letter to the trash (``?purge=true`` deletes it and everything derived
from it for good).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from datetime import date
from functools import partial
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import CtxDep, StateDep, StoreDep, TodayDep
from ordnung.api.routes.common import IsoDate, contracts_with_computations, ledger_changed, require, set_aside
from ordnung.api.routes.dates import recompute_document_items
from ordnung.app_context import AppContext
from ordnung.db.store import Store
from ordnung.ingest.attachments import attachment_listing, email_of, parts_not_listed
from ordnung.ingest.held import is_held, was_kept_from_waiting
from ordnung.ingest.intake import (
    IMAGE_TYPES,
    MAX_BYTES,
    THUMBNAIL_NAME,
    IntakeError,
    combine_images_to_pdf,
    download_name,
    normalise_upload,
    safe_filename,
    sniff_mime,
)
from ordnung.ingest.link import ATTACHMENT_ITEM_NOTE, DUNNING_ITEM_NOTE, rewarn_for_kind
from ordnung.ingest.pipeline import add_file, ledger_lock, reprocess
from ordnung.ingest.plan import KIND_CHOSEN, is_statement, kind_chosen
from ordnung.llm.replay import ReplayBackend
from ordnung.models import (
    HIGH_STAKES_KINDS,
    Area,
    Direction,
    Document,
    DocumentDetail,
    DocumentStatus,
    Item,
    Job,
    LetterAdvice,
    LetterKind,
    PageInfo,
    Suggestion,
)
from ordnung.rules.advice import letter_advice, settles
from ordnung.rules.deadlines import parse_date
from ordnung.rules.routing import (
    alternative_notice,
    announced_end,
    is_labour_court,
    notice_without_period,
    short_notice,
)
from ordnung.secretary.girocode_gate import document_girocodes
from ordnung.secretary.triggers import Ledger

router = APIRouter(tags=["documents"])

INLINE_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp"})
MAX_UPLOAD_FILES = 60
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
FILE_CACHE = "private, max-age=3600"
IMAGE_CACHE = "private, max-age=86400"
LIVE_IDEA_STATUSES = ("new", "accepted", "dismissed", "snoozed", "done")
NOT_FOUND = "This letter doesn't exist (any more)."


class UploadError(BaseModel):
    """A file that was not accepted, with the reason written for the person."""

    filename: str
    detail: str


class UploadResult(BaseModel):
    """``POST /api/documents``: letters queued for reading, their jobs, duplicates and rejections."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    documents: list[Document] = Field(default_factory=list)
    jobs: list[Job] = Field(default_factory=list)
    duplicates: list[str] = Field(
        default_factory=list, description="ids of letters that were already in Ordnung"
    )
    errors: list[UploadError] = Field(default_factory=list)


class DocumentPatch(BaseModel):
    """Corrections the person can make to a letter. ``received_date`` (when the letter arrived) and
    ``doc_date`` recompute the letter's to-dos with the rules engine unless ``received_confirmed`` is
    ``false``; so does ``kind``, which decides the rules of high-stakes letters (a court order, a
    dismissal …)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    kind: LetterKind | None = None
    area: Area | None = None
    tags: list[str] | None = None
    doc_date: IsoDate | None = None
    received_date: IsoDate | None = None
    received_confirmed: bool | None = None
    party_id: str | None = None
    case_id: str | None = None
    ai_private: bool | None = None
    direction: Direction | None = None


class DeleteResult(BaseModel):
    """What ``DELETE /api/documents/{id}`` did."""

    id: str
    purged: bool
    removed_open_items: int


# --------------------------------------------------------------------------------------------------
# list & detail
# --------------------------------------------------------------------------------------------------


@router.get("/documents", response_model=list[Document])
def list_documents(
    store: StoreDep,
    q: str | None = None,
    kind: LetterKind | None = None,
    party_id: str | None = None,
    case_id: str | None = None,
    status_: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    direction: Direction | None = None,
    private: bool | None = None,
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Document]:
    """Letters, newest first (trash excluded); ``q`` searches their text."""
    return store.list_documents(
        q=q,
        kind=kind,
        party_id=party_id,
        case_id=case_id,
        status=status_,
        direction=direction,
        limit=limit,
        offset=offset,
        ai_private=private,
    )


def _page_infos(store: Store, doc_id: str) -> list[PageInfo]:
    return [
        PageInfo(page=page.page, width=page.width, height=page.height, text_source=page.text_source)
        for page in store.list_pages(doc_id)
    ]


def _related(store: Store, document: Document) -> list[Document]:
    if document.case_id is None:
        return []
    return [doc for doc in store.list_documents(case_id=document.case_id) if doc.id != document.id]


def _ideas_about(store: Store, doc_id: str, items: Sequence[Item]) -> list[Suggestion]:
    item_ids = {item.id for item in items}
    return [
        idea
        for idea in store.list_suggestions(status=LIVE_IDEA_STATUSES)
        if any(
            (ref.type == "document" and ref.id == doc_id) or (ref.type == "item" and ref.id in item_ids)
            for ref in idea.refs
        )
    ]


def _with_reminder_notes(store: Store, items: list[Item], today: date) -> list[Item]:
    """Payments a live payment reminder took over carry the "pay once, not twice" note, and an
    e-mail's payment its attached bill repeats says so (worked out on read, like everywhere else; a
    note of the person's own is kept)."""
    if not any(item.kind == "payment" and not item.description for item in items):
        return items
    ledger = Ledger(store, today)

    def note(item: Item) -> str | None:
        if item.description:
            return None
        if ledger.is_superseded_by_reminder(item):
            return DUNNING_ITEM_NOTE
        return ATTACHMENT_ITEM_NOTE if ledger.is_covered_by_attachment(item) else None

    return [item.model_copy(update={"description": text}) if (text := note(item)) else item for item in items]


#: The tag a letter carries once the person said they dealt with a card no to-do can settle
#: (``LetterAdvice.closable``: a landlord's notice without notice period, or without an objection to-do).
DEALT_WITH_TAG = "dealt-with"


def letter_card(store: Store, document: Document, today: date) -> LetterAdvice | None:
    """The "get advice" card of a high-stakes letter, worked out on read from its kind, its dates,
    the amounts read from it, its text and its to-dos (:func:`ordnung.rules.advice.letter_advice`).

    Whether a to-do carries a landlord's notice is read from the to-dos themselves: one computed under
    § 574b BGB (the law's to-do or the letter's own objection date), whatever the reading's end date.
    A letter is ``handled`` once the person closed every to-do that carries its legal deadline
    (:func:`ordnung.rules.advice.settles`): its card is then no longer urgent. A card no to-do can settle
    (``closable``) is handled once the person tagged the letter :data:`DEALT_WITH_TAG` ("I've dealt with
    this" on the card)."""
    extraction = store.get_extraction(document.id)
    kind: str | None = document.kind
    if kind not in HIGH_STAKES_KINDS:
        # an operating-cost statement's dates don't depend on its kind: recognised on read only
        kind = (
            "operating_costs" if is_statement(kind, extraction, chosen=kind_chosen(store, document)) else None
        )
    if kind is None:
        return None
    change = extraction.change if extraction is not None else None
    letter_date = parse_date(document.doc_date)
    arrived = parse_date(document.received_date) or letter_date
    notice = extraction if kind == "landlord_notice" else None
    end = announced_end(notice) if notice is not None else None
    without_period = notice_without_period(notice, letter_date) if notice is not None else None
    party = store.get_party(document.party_id) if document.party_id else None
    sender = party or (extraction.sender if extraction else None)
    items = store.list_items(doc_id=document.id)
    region = store.get_profile().known_region
    short = short_notice(
        end, letter_date=letter_date, arrived=parse_date(document.received_date), region=region
    )
    card = partial(
        letter_advice,
        kind,
        today=today,
        arrived=arrived,
        arrival_confirmed=document.received_date is not None,
        letter_date=letter_date,
        region=region,
        old_amount=change.old_amount if change is not None else None,
        new_amount=change.new_amount if change is not None else None,
        # the title may name the billing year ("Operating-cost statement 2025")
        text=f"{document.title or ''}\n{store.get_document_text(document.id)}",
        extraordinary=without_period is not None,
        alternative=notice is not None and alternative_notice(notice),
        probable=without_period == "probable",
        labour_court=sender is not None and is_labour_court(sender.name, sender.kind),
        objection_todo=any(
            item.computation is not None and "bgb_574b" in item.computation.rule_ids for item in items
        ),
        end_unknown=notice is not None and end is None,
        objection_passed=short == "passed",
        short_period=short == "short",
        dealt_with=DEALT_WITH_TAG in document.tags,
    )
    advice = card()
    # which to-dos carry the letter's deadline follows from the card's rules
    return card(handled=True) if advice is not None and settles(advice, items) else advice


def document_detail(store: Store, doc_id: str, today: date) -> DocumentDetail:
    """The document viewer's data: the letter, its pages, to-dos, contracts, sender, thread, related
    letters, Ideas, drafts, the to-dos that are not one to act on (``set_aside``, as on Today), a
    GiroCode (or why there is none) per payment, for a high-stakes letter its "get advice" card, and
    for an e-mail what became of its attachments (for an attachment: the e-mail it came with)."""
    document = require(store.get_document(doc_id), NOT_FOUND)
    items = _with_reminder_notes(store, store.list_items(doc_id=doc_id), today)
    linked = {item.contract_id for item in items if item.contract_id}
    contracts = [
        contract
        for contract in store.list_contracts()
        if contract.source_doc_id == doc_id
        or contract.id in linked
        or any(evidence.doc_id == doc_id for evidence in contract.evidence)
    ]
    return DocumentDetail(
        document=document,
        advice=letter_card(store, document, today),
        pages=_page_infos(store, doc_id),
        items=items,
        contracts=contracts_with_computations(store, contracts, today),
        party=store.get_party(document.party_id) if document.party_id else None,
        case=store.get_case(document.case_id) if document.case_id else None,
        related=_related(store, document),
        suggestions=_ideas_about(store, doc_id, items),
        drafts=store.list_drafts(doc_id=doc_id),
        set_aside=set_aside(store, items, today),
        girocodes=document_girocodes(store, document, items, today),
        attachments=attachment_listing(store, document),
        attachments_more=parts_not_listed(store, document),
        email=email_of(store, document),
        can_wait_again=was_kept_from_waiting(store, document),
    )


@router.get("/documents/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: str, store: StoreDep, today: TodayDep) -> DocumentDetail:
    """One letter with everything the viewer shows."""
    return document_detail(store, doc_id, today)


# --------------------------------------------------------------------------------------------------
# upload
# --------------------------------------------------------------------------------------------------


def _normalised(data: bytes, filename: str, combine_with: Sequence[bytes]) -> tuple[bytes, str]:
    """The bytes and name Ordnung stores for an upload (photos combined into one PDF if asked)."""
    if combine_with:
        data = combine_images_to_pdf([data, *combine_with])
        filename = f"{Path(safe_filename(filename)).stem or 'photos'}.pdf"
    body, _mime, name = normalise_upload(data, filename)
    return body, name


def _is_photo(data: bytes, filename: str) -> bool:
    try:
        return sniff_mime(data, filename) in IMAGE_TYPES
    except IntakeError:
        return False


def _groups(files: Sequence[tuple[str, bytes]], combine: bool) -> list[list[tuple[str, bytes]]]:
    """One group per document: with ``combine`` all photos form one letter; everything else is alone."""
    if not combine:
        return [[entry] for entry in files]
    photos = [entry for entry in files if _is_photo(entry[1], entry[0])]
    others = [[entry] for entry in files if not _is_photo(entry[1], entry[0])]
    return ([photos] if photos else []) + others


async def _add_group(
    ctx: AppContext, group: list[tuple[str, bytes]], private: bool, result: UploadResult
) -> None:
    (filename, data), rest = group[0], [entry[1] for entry in group[1:]]
    store = ctx.store
    try:
        body, name = await asyncio.to_thread(_normalised, data, filename, rest)
        existing = store.get_document_by_sha(hashlib.sha256(body).hexdigest())
        document = await add_file(ctx, body, name, private=private, answer_held=True)
    except IntakeError as exc:
        result.errors.append(UploadError(filename=safe_filename(filename), detail=str(exc)))
        return
    # a letter that failed, or one waiting for the person that this upload lets Claude read, is read now
    read_again = existing is not None and (
        existing.status == "failed" or (existing.status == "held" and not private)
    )
    if existing is not None and not read_again:
        result.duplicates.append(document.id)
        return
    result.documents.append(document)
    job = store.latest_job(document.id)
    if job is not None:
        result.jobs.append(job)


async def _read(upload: UploadFile) -> tuple[str, bytes]:
    return upload.filename or "document", await upload.read(MAX_BYTES + 1)


DEMO_UPLOAD_MESSAGE = (
    "The demo uses recorded answers for Sam's sample letters, so it can't read new ones. "
    "Run “ordnung serve” (with Claude Code signed in) to use Ordnung with your own letters."
)


def _replay_only(ctx: AppContext) -> bool:
    """The model backend only replays recordings (the zero-token demo): new letters can't be read."""
    backend = ctx.llm.backend
    return isinstance(backend, ReplayBackend) and backend.fallback is None


@router.post("/documents", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_documents(
    state: StateDep,
    ctx: CtxDep,
    files: Annotated[
        list[UploadFile] | None, File(description="The letters (PDF, photos, .txt/.eml)")
    ] = None,
    files_array: Annotated[list[UploadFile] | None, File(alias="files[]", include_in_schema=False)] = None,
    combine: Annotated[bool, Form(description="Photos of this upload are pages of one letter")] = False,
    private: Annotated[bool, Form(description="Keep private — never sent to AI")] = False,
) -> UploadResult | JSONResponse:
    """Store the uploaded letters and queue them for reading."""
    uploads = [*(files or []), *(files_array or [])]
    if not uploads:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No files were uploaded.")
    if state.demo and not private and _replay_only(ctx):
        raise HTTPException(status.HTTP_409_CONFLICT, DEMO_UPLOAD_MESSAGE)
    if len(uploads) > MAX_UPLOAD_FILES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"Please add at most {MAX_UPLOAD_FILES} files at once."
        )
    entries: list[tuple[str, bytes]] = []
    for upload in uploads:
        entries.append(await _read(upload))
        if sum(len(data) for _, data in entries) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"Please add at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB at once.",
            )
    result = UploadResult()
    for group in _groups(entries, combine):
        await _add_group(ctx, group, private, result)
    if result.errors and not (result.documents or result.duplicates):
        detail = "; ".join(f"{error.filename}: {error.detail}" for error in result.errors)
        return JSONResponse({"detail": detail, "errors": [e.model_dump() for e in result.errors]}, 422)
    return result


# --------------------------------------------------------------------------------------------------
# edit, reprocess, delete
# --------------------------------------------------------------------------------------------------


def _check_links(store: Store, changes: dict[str, object]) -> None:
    party_id, case_id = changes.get("party_id"), changes.get("case_id")
    if isinstance(party_id, str):
        require(store.get_party(party_id), "Unknown person or organisation.")
    if isinstance(case_id, str):
        require(store.get_case(case_id), "Unknown thread.")


HELD_MESSAGE = (
    "This letter is waiting for you: choose “Read” or “Keep private” for it first (Inbox → From your folder)."
)


def _apply_patch(store: Store, doc_id: str, changes: dict[str, object]) -> Document:
    document = require(store.get_document(doc_id), NOT_FOUND)
    if "ai_private" in changes and is_held(document):
        # a waiting letter is private until the person answers (ingest.held): only an answer changes that
        raise HTTPException(status.HTTP_409_CONFLICT, HELD_MESSAGE)
    _check_links(store, changes)
    if changes.get("tags", ...) is None:
        changes["tags"] = []
    return store.update_document(document.id, **changes) if changes else document


def _patch(
    store: Store, doc_id: str, changes: dict[str, object], confirmed: bool | None, today: date
) -> tuple[Document, list[Item] | None]:
    """Apply a patch and, when it changes the kind or confirms a date, recompute the letter's to-dos —
    in one transaction, with the :data:`KIND_CHOSEN` entry written with the kind, so a re-read that
    commits before or after (both under :func:`ledger_lock`) sees the person's choice and keeps it.
    Returns the letter and the to-dos that changed (``None``: nothing to recompute)."""
    with store.tx():
        before = require(store.get_document(doc_id), NOT_FOUND)
        document = _apply_patch(store, doc_id, changes)
        # any kind the person sends is their choice, also the one it is filed as (a statement recognised on
        # read and filed as a utility bill stays one only until the person says so — review round 2)
        kind_changed = "kind" in changes and (before.kind != document.kind or not kind_chosen(store, before))
        dates_changed = bool({"received_date", "doc_date"} & changes.keys()) or confirmed is True
        if kind_changed:
            # a warning said of the old kind ("This is a payment reminder about …") is said of the new one
            warnings = rewarn_for_kind(document.warnings, document.kind)
            if warnings != document.warnings:
                document = store.update_document(doc_id, warnings=warnings)
            # a kind the person chose is kept when the letter is read again (ingest.plan.corrections)
            store.log_activity(
                KIND_CHOSEN,
                f"You filed “{document.title or document.filename}” as “{(document.kind or 'other').replace('_', ' ')}”",
                ref_type="document",
                ref_id=doc_id,
                data={"kind": document.kind, "was": before.kind},
            )
        # a chosen kind always re-routes the dates; ``received_confirmed: false`` only holds back a date change
        if not (kind_changed or (dates_changed and confirmed is not False)):
            return document, None
        changed = recompute_document_items(store, document, today, refile_rules=kind_changed)
        if "received_date" in changes and document.received_date:
            store.log_activity(
                "document.received_date",
                f"You confirmed that “{document.title or document.filename}” arrived on {document.received_date}",
                ref_type="document",
                ref_id=doc_id,
                data={"recomputed_items": [item.id for item in changed]},
            )
        return document, changed


@router.patch("/documents/{doc_id}", response_model=Document)
async def update_document(doc_id: str, patch: DocumentPatch, ctx: CtxDep, today: TodayDep) -> Document:
    """Correct a letter's facts; a confirmed arrival date or corrected letter date recomputes its to-dos."""
    changes = patch.model_dump(exclude_unset=True)
    confirmed = changes.pop("received_confirmed", None)
    async with ledger_lock():
        document, changed = await asyncio.to_thread(_patch, ctx.store, doc_id, changes, confirmed, today)
    if changed is None:
        if changes:
            ctx.bus.publish("document.updated", doc_id=doc_id)
        return document
    ctx.bus.publish("document.updated", doc_id=doc_id)
    await ledger_changed(ctx)
    return require(ctx.store.get_document(doc_id), NOT_FOUND)


@router.post("/documents/{doc_id}/reprocess", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
async def reprocess_document(doc_id: str, ctx: CtxDep) -> Job:
    """Read the letter again, bypassing the model cache (to-dos the person edited are kept)."""
    document = require(ctx.store.get_document(doc_id), NOT_FOUND)
    if document.deleted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This letter is in the trash.")
    if is_held(document):
        raise HTTPException(status.HTTP_409_CONFLICT, HELD_MESSAGE)
    return await asyncio.to_thread(reprocess, ctx, doc_id)


def _delete(store: Store, doc_id: str, purge: bool) -> DeleteResult:
    document = require(store.get_document(doc_id), NOT_FOUND)
    removed = len(store.list_items(doc_id=doc_id, status="open"))
    title = document.title or document.filename
    if purge:
        store.delete_document(doc_id)
        store.log_activity(  # no title, file name or id: nothing of the letter stays behind
            "document.deleted",
            "Deleted a letter and everything derived from it",
            data={"removed_open_items": removed},
        )
    else:
        store.trash_document(doc_id)
        store.log_activity(
            "document.trashed",
            f"Moved “{title}” to the trash",
            ref_type="document",
            ref_id=doc_id,
            data={"removed_open_items": removed},
        )
    return DeleteResult(id=doc_id, purged=purge, removed_open_items=removed)


@router.delete("/documents/{doc_id}", response_model=DeleteResult)
async def delete_document(
    doc_id: str, ctx: CtxDep, purge: Annotated[bool, Query(description="Delete for good")] = False
) -> DeleteResult:
    """Move a letter to the trash, or with ``purge`` delete it with its pages, to-dos and cache."""
    result = await asyncio.to_thread(_delete, ctx.store, doc_id, purge)
    ctx.bus.publish("document.deleted", doc_id=doc_id, purged=purge)
    await ledger_changed(ctx)
    return result


# --------------------------------------------------------------------------------------------------
# files
# --------------------------------------------------------------------------------------------------


def _inside(store: Store, path: Path | None) -> Path:
    """``path`` if it is an existing file inside the data directory, else 404."""
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing.")
    resolved = path.resolve()
    if not (resolved.is_file() and resolved.is_relative_to(store.data_dir.resolve())):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing.")
    return resolved


@router.get("/documents/{doc_id}/file", response_class=FileResponse)
def document_file(doc_id: str, store: StoreDep) -> FileResponse:
    """The original file: PDFs and common images inline, anything else as a download."""
    document = require(store.get_document(doc_id), NOT_FOUND)
    path = _inside(store, store.get_document_file(doc_id))
    inline = document.mime in INLINE_TYPES
    return FileResponse(
        path,
        media_type=document.mime,
        filename=download_name(document.filename, document.mime),
        content_disposition_type="inline" if inline else "attachment",
        headers={"Cache-Control": FILE_CACHE, "X-Content-Type-Options": "nosniff"},
    )


@router.get("/documents/{doc_id}/pages/{page}.jpg", response_class=FileResponse)
def page_image(doc_id: str, page: int, store: StoreDep) -> FileResponse:
    """A rendered page (JPEG, 1-based page number)."""
    stored = require(store.get_page(doc_id, page), "This page doesn't exist.")
    path = _inside(store, store.data_dir / stored.image_path)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": IMAGE_CACHE})


@router.get("/documents/{doc_id}/thumbnail.jpg", response_class=FileResponse)
def thumbnail(doc_id: str, store: StoreDep) -> FileResponse:
    """A small image of the first page."""
    require(store.get_document(doc_id), NOT_FOUND)
    path = _inside(store, store.paths.derived / doc_id / THUMBNAIL_NAME)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": IMAGE_CACHE})
