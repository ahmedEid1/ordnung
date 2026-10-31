"""Letters: upload, list, detail, edit, reprocess, delete, and their files (original, pages, thumbnail).

The list (``GET /api/documents``) answers :class:`DocumentRow`: each letter without what Claude read
from inside it in detail and the file hash (:data:`LEFT_OUT_OF_LIST`); the letter's own page
(``GET /api/documents/{id}``) has all of it. "Download a copy of your records" takes every letter whole
from ``GET /api/documents.json``, on the computer only.

What the person chose about a letter is kept apart from Claude's reading and added by the routes (models
outside ``models.py``): its "For taxes" choice (``tax_choice``, :mod:`ordnung.secretary.tax_choice`) on each
row, the letter's page (:class:`LetterDetail`) and the records (:class:`LetterRecord`), and who the letter
is for on its page (``household``, :mod:`ordnung.secretary.household`).

Uploads (``POST /api/documents``, multipart): ``files`` (``files[]`` is accepted too), ``combine``
(all photos of the upload become one multi-page letter; other files stay separate documents) and
``private`` ("Keep private — no AI"). The response lists the documents queued for reading with their
jobs; files that were already in Ordnung are reported by id in ``duplicates``, rejected files in
``errors``. Deleting moves a letter to the trash (``?purge=true`` deletes it and everything derived
from it for good).

Originals, page images and thumbnails are sent with ``no-store``, and deleting for good also tells the
browser to empty its cache (``Clear-Site-Data``), so no copy of a deleted letter stays in the browser.

From a paired phone (:mod:`ordnung.phone`) an upload is filed as ``source="phone"`` ("… from your
phone"), each letter it adds counts against the phone's hourly upload limit (the gate counted the
request; photos combined into one letter count once), and a letter kept private can't be given to
Claude: that is decided on the computer.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from datetime import date
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, create_model

from ordnung.api.deps import CtxDep, StateDep, StoreDep, TodayDep, is_phone, phone_device, require_computer
from ordnung.api.routes.common import IsoDate, contracts_with_computations, ledger_changed, require, set_aside
from ordnung.api.routes.dates import recompute_document_items, refresh_review_status
from ordnung.app_context import AppContext
from ordnung.config import picture_text_off
from ordnung.db.store import Store
from ordnung.drafts.proof import PROOF_SOURCE
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
from ordnung.ingest.layout_guard import text_layout_refused
from ordnung.ingest.link import ATTACHMENT_ITEM_NOTE, DUNNING_ITEM_NOTE, rewarn_for_kind
from ordnung.ingest.outlook import as_email
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
    ProofLink,
    Suggestion,
)
from ordnung.phone import PhoneRefusal
from ordnung.phone.access import LIMIT_MESSAGES, UPLOAD_TOO_MANY_MESSAGE
from ordnung.rules.advice import letter_advice, settles
from ordnung.rules.deadlines import parse_date
from ordnung.rules.routing import (
    alternative_notice,
    announced_end,
    is_labour_court,
    notice_without_period,
    short_notice,
)
from ordnung.secretary.addressee import addressed_to
from ordnung.secretary.girocode_gate import document_girocodes
from ordnung.secretary.household import LetterFor, letter_for
from ordnung.secretary.sender_land import region_suggestion
from ordnung.secretary.triggers import Ledger

router = APIRouter(tags=["documents"])

INLINE_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png", "image/webp"})
MAX_UPLOAD_FILES = 60
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
#: The furthest a letter list is paged (``offset``) and the highest page number asked for: past them is a 422.
MAX_OFFSET = 1_000_000
MAX_PAGE = 10_000
NO_STORE = "no-store"
CLEAR_CACHE = {"Clear-Site-Data": '"cache"'}
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
    tax_choice: bool | None = Field(
        default=None,
        description=(
            "For taxes: true or false is the person's own choice, over Claude's mark; null goes back to "
            "Claude's mark"
        ),
        strict=True,  # true, false or null: never "yes" or 1 (the published schema is the same)
    )


#: What the letter list leaves out: what Claude read from inside the letter in detail, and the file hash.
#: The letter's own page (``GET /api/documents/{id}``) and the copy of your records have all of it.
LEFT_OUT_OF_LIST = frozenset({"key_facts", "explanation", "references", "payment", "sha256"})
#: What the route adds to each row of the list: where a search found the letter, and the person's own
#: "For taxes" choice (``None``: none, Claude's mark counts).
ROUTE_FIELDS = frozenset({"found_in", "tax_choice"})
#: Where a search found a letter (route-local, like every field the list adds): ``letter`` — its own words
#: (title, file name, Claude's reading, page text, sender); ``scanner_text`` — only in the text a scanner added
#: (ADR 0020); ``picture_text`` — only in the text Ordnung read from the picture with Tesseract (ADR 0024).
LetterFoundIn = Literal["letter", "scanner_text", "picture_text"]

_ROW_FIELDS: dict[str, Any] = {
    name: (field.annotation, field)
    for name, field in Document.model_fields.items()
    if name not in LEFT_OUT_OF_LIST
}

DocumentRow = create_model(
    "DocumentRow",
    __config__=ConfigDict(json_schema_serialization_defaults_required=True),
    # the ROUTE_FIELDS are found_in (LetterFoundIn) and tax_choice, the person's own "For taxes" choice
    # (None: none, Claude's mark counts)
    __doc__=(
        "A letter as the list (``GET /api/documents``) returns it: every ``Document`` field but\n"
        "``LEFT_OUT_OF_LIST``, plus ``found_in``, where a search (``q``) found the letter\n"
        "(``LetterFoundIn``; ``None`` when the list wasn't searched). A view model made by the route,\n"
        "never stored: ``Document`` stays the table's model and what Ask's ledger fingerprint hashes.\n"
        "\n"
        "Its fields are copied from ``Document`` by name, so a field the letter gains reaches the list by\n"
        "itself."
    ),
    __module__=__name__,
    **_ROW_FIELDS,
    found_in=(LetterFoundIn | None, None),
    tax_choice=(bool | None, None),
)


class LetterDetail(DocumentDetail):
    """``GET /api/documents/{id}``: the letter's page (``models.DocumentDetail``) with what the person chose
    about the letter, kept apart from Claude's reading. Route-local, so ``models.py`` (a benchmark digest
    file) stays as it is; Ask never reads it."""

    tax_choice: bool | None = Field(
        default=None,
        description="The person's own For taxes choice; null: none, Claude's mark (document.tax_relevant) counts",
    )
    #: Who the letter is for (all empty without a household).
    household: LetterFor = Field(default_factory=LetterFor)
    picture_text_pages: list[int] = Field(
        default_factory=list,
        description=(
            "The pages (1-based) whose words Ordnung read itself from the picture (Tesseract), kept for search "
            "only: never shown, checked or sent to Claude."
        ),
    )


class LetterRecord(Document):
    """A letter in the copy of your records (``GET /api/documents.json``): the letter whole, as stored, with
    the person's own "For taxes" choice (``None``: none)."""

    tax_choice: bool | None = None


class DeleteResult(BaseModel):
    """What ``DELETE /api/documents/{id}`` did."""

    id: str
    purged: bool
    removed_open_items: int


# --------------------------------------------------------------------------------------------------
# list & detail
# --------------------------------------------------------------------------------------------------


@router.get("/documents", response_model=list[DocumentRow])
def list_documents(
    store: StoreDep,
    ctx: CtxDep,
    q: str | None = None,
    kind: LetterKind | None = None,
    party_id: str | None = None,
    case_id: str | None = None,
    status_: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    direction: Direction | None = None,
    private: bool | None = None,
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> list[DocumentRow]:
    """Letters, newest first (trash excluded); ``q`` searches their text, and each row then says where
    it was found (``found_in``: ``letter``, or ``scanner_text`` — only in the unchecked text a scanner
    added; ``null`` without a search). Each row leaves out the letter's explanation, key facts,
    references, bank details and file hash (``LEFT_OUT_OF_LIST``): the letter's own page has them. A
    letter's proof files (``source="proof"``) are listed with their letter, never here. The scanner's
    text counts only on pages without text of their own and is never returned (ADR 0020)."""
    # the published description stays as it was (D4's contract changes only found_in's values): found_in
    # is also ``picture_text`` — only in the unchecked text Ordnung read from the picture itself (ADR 0024),
    # which counts only on pages without text of their own, is never returned, and doesn't count while text in
    # pictures is off (in Settings, or ORDNUNG_OCR=off)
    query = q.strip() if q else ""
    # letters found in a scan's scanner text, or in the words Ordnung read in a picture: kept apart from the
    # indexes, ORed in here alone (the picture's not while text in pictures is off, from the moment it is saved)
    scanned = store.scan_text_matches(query) if query else set()
    pictures_off = picture_text_off(ctx.settings.read_picture_text)
    pictured = store.picture_text_matches(query) if query and not pictures_off else set()
    docs = store.list_documents(
        q=q,
        kind=kind,
        party_id=party_id,
        case_id=case_id,
        status=status_,
        direction=direction,
        limit=limit,
        offset=offset,
        ai_private=private,
        exclude_source=PROOF_SOURCE,
        also_ids=scanned | pictured,
    )
    listed = (scanned | pictured) & {doc.id for doc in docs}
    # of those, the ones its own words find too: a letter is "found in" the unchecked text only otherwise
    own = store.indexed_matches(query, listed) if listed else set()

    def found_in(doc: Document) -> LetterFoundIn | None:
        if not query:
            return None
        if doc.id not in listed or doc.id in own:
            return "letter"
        return "scanner_text" if doc.id in scanned else "picture_text"  # the scanner's text comes first

    choices = store.tax_choices()  # one read for every row
    return [
        DocumentRow.model_construct(
            **{name: value for name, value in dict(doc).items() if name not in LEFT_OUT_OF_LIST},
            found_in=found_in(doc),
            tax_choice=choices.get(doc.id),
        )
        for doc in docs
    ]


@router.get("/documents.json", response_model=list[LetterRecord], dependencies=[Depends(require_computer)])
def records_copy(store: StoreDep) -> list[LetterRecord]:
    """Every letter whole, as stored, newest first: the letters of "Download a copy of your records".
    Trash and proof files are left out, as in the list. Computer only (403 ``computer_only`` for a
    phone, also behind the phone listener's allow-list): records leave the computer."""
    # each with the person's own "For taxes" choice (LetterRecord), read once
    choices = store.tax_choices()
    return [
        LetterRecord.model_construct(**dict(doc), tax_choice=choices.get(doc.id))
        for doc in store.list_documents(exclude_source=PROOF_SOURCE)
    ]


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
    GiroCode (or why there is none) per payment, for a high-stakes letter its "get advice" card, for
    an e-mail what became of its attachments (for an attachment: the e-mail it came with), and while
    the sender has no Land the one the postcode on their letters suggests, with this letter's dates
    that may change (``region_suggestion``), and who the letter is addressed to when that isn't the
    profile's person (``addressed_to``, worked out on read: :mod:`ordnung.secretary.addressee`)."""
    document = require(store.get_document(doc_id), NOT_FOUND)
    ledger = Ledger(store, today)
    party = store.get_party(document.party_id) if document.party_id else None
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
        party=party,
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
        proof_of=_proof_of(store, doc_id),
        scam_signs=ledger.scam_signs(document) if document.direction == "incoming" else [],
        given_to_model=store.given_to_model(doc_id),
        region_suggestion=region_suggestion(ledger, party, doc_id=doc_id) if party is not None else None,
        addressed_to=addressed_to(document, store.get_extraction(doc_id), store.get_profile().name),
        scan_text_pages=store.scan_text_pages(doc_id),
    )


def _proof_of(store: Store, doc_id: str) -> list[ProofLink]:
    links = []
    for proof in store.list_proofs(doc_id=doc_id):
        draft = store.get_draft(proof.draft_id)
        if draft is not None:
            links.append(
                ProofLink(draft_id=draft.id, subject=draft.subject, proof_id=proof.id, kind=proof.kind)
            )
    return links


@router.get("/documents/{doc_id}", response_model=LetterDetail)
def get_document(doc_id: str, store: StoreDep, ctx: CtxDep, today: TodayDep) -> LetterDetail:
    """One letter with everything the viewer shows."""
    # with the person's own "For taxes" choice, who the letter is for, and the pages whose words Ordnung read in
    # the picture (LetterDetail; none while text in pictures is off, in Settings or by ORDNUNG_OCR, ADR 0024)
    detail = document_detail(store, doc_id, today)
    pictures_off = picture_text_off(ctx.settings.read_picture_text)
    return LetterDetail.model_construct(
        **dict(detail),
        tax_choice=store.tax_choices().get(doc_id),
        household=letter_for(store, detail.document),
        picture_text_pages=[] if pictures_off else store.picture_text_pages(doc_id),
    )


# --------------------------------------------------------------------------------------------------
# upload
# --------------------------------------------------------------------------------------------------


def _normalised(data: bytes, filename: str, combine_with: Sequence[bytes]) -> tuple[bytes, str]:
    """The bytes and name Ordnung stores for an upload (photos combined into one PDF if asked; an Outlook
    ``.msg`` becomes its ``.eml`` copy before intake looks at it, :mod:`ordnung.ingest.outlook`)."""
    if combine_with:
        data = combine_images_to_pdf([data, *combine_with])
        filename = f"{Path(safe_filename(filename)).stem or 'photos'}.pdf"
    data, filename = as_email(data, filename)
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
    ctx: AppContext,
    group: list[tuple[str, bytes]],
    private: bool,
    result: UploadResult,
    source: str = "upload",
) -> None:
    (filename, data), rest = group[0], [entry[1] for entry in group[1:]]
    store = ctx.store
    try:
        with text_layout_refused():
            body, name = await asyncio.to_thread(_normalised, data, filename, rest)
            existing = store.get_document_by_sha(hashlib.sha256(body).hexdigest())
            document = await add_file(ctx, body, name, private=private, answer_held=True, source=source)
    except IntakeError as exc:
        result.errors.append(UploadError(filename=safe_filename(filename), detail=str(exc)))
        return
    if existing is not None and existing.source == PROOF_SOURCE:
        # a proof file is listed with its letter, never in the Inbox: say where it is instead
        links = _proof_of(store, existing.id)
        where = f" of your letter “{links[0].subject}”" if links else ""
        detail = f"This file is already in Ordnung as proof{where} — open it from that letter."
        result.errors.append(UploadError(filename=safe_filename(filename), detail=detail))
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
DEMO_REPLAY_CODE = "demo_replay"
"""``code`` of that refusal: the app says it as a limit of the demo (an info note), not as a failure."""


def demo_replay_refusal() -> JSONResponse:
    """409 for what the replay-only demo can't do (read a letter it has no recording for)."""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": DEMO_UPLOAD_MESSAGE, "code": DEMO_REPLAY_CODE},
    )


def _replay_only(ctx: AppContext) -> bool:
    """The model backend only replays recordings (the zero-token demo): new letters can't be read."""
    backend = ctx.llm.backend
    return isinstance(backend, ReplayBackend) and backend.fallback is None


@router.post("/documents", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_documents(
    request: Request,
    state: StateDep,
    ctx: CtxDep,
    files: Annotated[
        list[UploadFile] | None, File(description="The letters (PDF, photos, .txt/.eml/.msg)")
    ] = None,
    files_array: Annotated[list[UploadFile] | None, File(alias="files[]", include_in_schema=False)] = None,
    combine: Annotated[bool, Form(description="Photos of this upload are pages of one letter")] = False,
    private: Annotated[bool, Form(description="Keep private — never sent to Claude")] = False,
) -> UploadResult | JSONResponse:
    """Store the uploaded letters and queue them for reading."""
    uploads = [*(files or []), *(files_array or [])]
    if not uploads:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No files were uploaded.")
    if state.demo and not private and _replay_only(ctx):
        return demo_replay_refusal()
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
    source = "phone" if is_phone(request) else "upload"
    groups = _groups(entries, combine)
    device = phone_device(request)
    if device is not None:
        # each letter is a reading: the phone's hourly limit counts letters, not requests
        wait = state.phone.more_letters(device.id, len(groups))
        if wait < 0:
            limit = state.phone.upload_limit
            raise PhoneRefusal("too_many", UPLOAD_TOO_MANY_MESSAGE.format(limit=limit), retry_after=3600)
        if wait:
            raise PhoneRefusal("too_many", LIMIT_MESSAGES["upload"], retry_after=wait)
    for group in groups:
        await _add_group(ctx, group, private, result, source)
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


PRIVATE_ON_COMPUTER = "Let Claude read a private letter from your computer."

HELD_MESSAGE = (
    "This letter isn't read yet: choose “Read” or “Keep private” for it first (Inbox → From your folder)."
)
IN_TRASH = "This letter is in the trash."
PROOF_FOR_TAXES = "A proof file goes with its letter: mark that letter for taxes instead."


def _check_tax_choice(document: Document) -> None:
    """A "For taxes" choice is for a letter in the Inbox (the page shows the toggle only there): not one in
    the trash, one waiting for the person's answer, or a proof file. A letter being read may have one: it is
    kept apart from the reading and is still there when the reading ends."""
    if document.deleted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, IN_TRASH)
    if is_held(document):
        raise HTTPException(status.HTTP_409_CONFLICT, HELD_MESSAGE)
    if document.source == PROOF_SOURCE:
        raise HTTPException(status.HTTP_409_CONFLICT, PROOF_FOR_TAXES)


def _apply_patch(store: Store, doc_id: str, changes: dict[str, object]) -> Document:
    document = require(store.get_document(doc_id), NOT_FOUND)
    # the person's "For taxes" choice is kept apart from the letter (secretary.tax_choice): its row, and
    # with it ``updated_at`` and Ask's ledger token, stay as they are
    tax_set = "tax_choice" in changes
    tax_choice = changes.pop("tax_choice", None)
    if tax_set:
        _check_tax_choice(document)
    if "ai_private" in changes and is_held(document):
        # a waiting letter is private until the person answers (ingest.held): only an answer changes that
        raise HTTPException(status.HTTP_409_CONFLICT, HELD_MESSAGE)
    _check_links(store, changes)
    if changes.get("tags", ...) is None:
        changes["tags"] = []
    if tax_set:
        store.set_tax_choice(document.id, tax_choice if isinstance(tax_choice, bool) else None)
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
        # a recompute can flag a to-do (two dates) or unflag one: the letter's "Please check" follows
        document = refresh_review_status(store, doc_id) or document
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
async def update_document(
    doc_id: str, patch: DocumentPatch, request: Request, ctx: CtxDep, today: TodayDep
) -> Document:
    """Correct a letter's facts; a confirmed arrival date or corrected letter date recomputes its to-dos."""
    # (the published description stays as it was.) ``tax_choice`` sets the person's own "For taxes" choice
    # (``null`` clears it), kept apart from the letter: the answer is the letter as stored, and its page
    # carries the choice; 409 for a letter in the trash, one waiting for the person, or a proof file
    changes = patch.model_dump(exclude_unset=True)
    tax_set = "tax_choice" in changes
    confirmed = changes.pop("received_confirmed", None)
    if changes.get("ai_private") is False and is_phone(request):
        document = require(ctx.store.get_document(doc_id), NOT_FOUND)
        if document.ai_private:  # who may read a private letter is decided on the computer
            raise PhoneRefusal("computer_only", PRIVATE_ON_COMPUTER)
    async with ledger_lock():
        document, changed = await asyncio.to_thread(_patch, ctx.store, doc_id, changes, confirmed, today)
    if tax_set or "ai_private" in changes:
        # the tax Idea counts the letters for taxes, and an Idea about a private letter names no one: both follow
        # at once (an Idea's title reaches Claude)
        ctx.worker.refresh_ideas()
    if changed is None:
        if changes or tax_set:
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
        raise HTTPException(status.HTTP_409_CONFLICT, IN_TRASH)
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
    doc_id: str,
    ctx: CtxDep,
    response: Response,
    purge: Annotated[bool, Query(description="Delete for good")] = False,
) -> DeleteResult:
    """Move a letter to the trash, or with ``purge`` delete it with its pages, to-dos and cache."""
    result = await asyncio.to_thread(_delete, ctx.store, doc_id, purge)
    if purge:
        response.headers.update(CLEAR_CACHE)
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
        headers={"Cache-Control": NO_STORE, "X-Content-Type-Options": "nosniff"},
    )


@router.get("/documents/{doc_id}/pages/{page}.jpg", response_class=FileResponse)
def page_image(doc_id: str, page: Annotated[int, PathParam(le=MAX_PAGE)], store: StoreDep) -> FileResponse:
    """A rendered page (JPEG, 1-based page number)."""
    # a number below 1 is no page, as one past the letter's last is
    stored = require(store.get_page(doc_id, page) if page >= 1 else None, "This page doesn't exist.")
    path = _inside(store, store.data_dir / stored.image_path)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": NO_STORE})


@router.get("/documents/{doc_id}/thumbnail.jpg", response_class=FileResponse)
def thumbnail(doc_id: str, store: StoreDep) -> FileResponse:
    """A small image of the first page."""
    require(store.get_document(doc_id), NOT_FOUND)
    path = _inside(store, store.paths.derived / doc_id / THUMBNAIL_NAME)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": NO_STORE})
