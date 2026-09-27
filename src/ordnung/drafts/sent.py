"""After a letter is sent: its tracking number, its proofs and their files, the proof overview and the
"Nachweis" PDF (SPEC § 11). What counts and what is said is :mod:`ordnung.drafts.proof`; this module
stores and reads.

* **Proof files are private.** They go through the normal intake (every size and expansion limit) as
  documents with direction ``outgoing``, ``source="proof"`` and "Keep private — no AI" on, so no model
  ever sees them. A file already in Ordnung (the same bytes) is linked as it is.
* **Only sent letters take proof**, at most :data:`~ordnung.drafts.proof.MAX_PROOFS` of them; a proof's
  day can't be in the future.
* **Delete means delete.** Removing a proof deletes its file for good when it was added as proof and no
  other proof uses it; deleting a letter deletes its proofs and their files the same way.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from ordnung.db.store import NotFoundError, Store
from ordnung.drafts.compose import DraftError
from ordnung.drafts.pdf import NachweisFacts, NachweisFile, NachweisLine, render_nachweis
from ordnung.drafts.proof import (
    CAVEAT,
    CAVEAT_DE,
    MAX_NOTE,
    MAX_PROOFS,
    PROOF_KINDS,
    PROOF_SOURCE,
    RecordedProof,
    channel_label,
    kind_info,
    missing,
    timeline,
)
from ordnung.drafts.templates import format_date
from ordnung.drafts.tracking import TrackingError, parse_tracking_number, tracking_info
from ordnung.ingest.pipeline import add_file
from ordnung.models import Document, Draft, Proof, ProofEntry, ProofOverview
from ordnung.secretary.triggers import Ledger, parse_day
from ordnung.secretary.waiting import letter_entry

if TYPE_CHECKING:
    from ordnung.app_context import AppContext

NOT_SENT = "Mark the letter as sent first — proof belongs to a letter that went out."
TOO_MANY = f"A letter can hold up to {MAX_PROOFS} proofs. Remove one you don't need first."
FUTURE_DAY = "The day a proof shows can't be in the future."
UNKNOWN_KIND = "Choose what the proof is (posting receipt, delivery record …)."


def _draft(store: Store, draft_id: str) -> Draft:
    draft = store.get_draft(draft_id)
    if draft is None:
        raise NotFoundError(f"drafts: no row with id {draft_id!r}")
    return draft


def _sent_draft(store: Store, draft_id: str) -> Draft:
    draft = _draft(store, draft_id)
    if draft.status != "sent":
        raise DraftError(NOT_SENT)
    return draft


def _proof(store: Store, draft_id: str, proof_id: str) -> Proof:
    proof = store.get_proof(proof_id)
    if proof is None or proof.draft_id != draft_id:
        raise NotFoundError(f"proofs: no row with id {proof_id!r} for this letter")
    return proof


def _checked(kind: str | None, on_date: str | None, note: str | None, today: date) -> date | None:
    """Refuse an unknown kind, a day that isn't one or lies in the future, and a long note; returns the day."""
    if kind is not None and kind not in PROOF_KINDS:
        raise DraftError(UNKNOWN_KIND)
    day = parse_day(on_date) if on_date else None
    if on_date and day is None:
        raise DraftError(f"“{on_date}” is not a date.")
    if day is not None and day > today:
        raise DraftError(FUTURE_DAY)
    if note is not None and len(note) > MAX_NOTE:
        raise DraftError(f"Keep the note under {MAX_NOTE} characters.")
    return day


# --------------------------------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------------------------------


def set_tracking(store: Store, draft_id: str, text: str | None) -> Draft:
    """Save (or with an empty ``text`` remove) a sent letter's tracking number; refused ones raise
    :class:`~ordnung.drafts.compose.DraftError` with the policy's message."""
    draft = _sent_draft(store, draft_id)
    number = None
    if text and text.strip():
        try:
            number = parse_tracking_number(text).number
        except TrackingError as exc:
            raise DraftError(str(exc)) from exc
    with store.tx():
        updated = store.update_draft(draft.id, tracking_number=number)
        store.log_activity(
            "draft.tracking",
            f"Tracking number {'saved' if number else 'removed'} for “{draft.subject}”",
            ref_type="draft",
            ref_id=draft.id,
        )
    return updated


async def add_proof(
    ctx: AppContext,
    draft_id: str,
    data: bytes,
    filename: str,
    *,
    kind: str,
    on_date: str | None = None,
    note: str | None = None,
    today: date,
) -> Proof:
    """Store a proof file privately and attach it to a sent letter (see the module docstring)."""
    store = ctx.store
    draft = _sent_draft(store, draft_id)
    day = _checked(kind, on_date, note, today)
    if len(store.list_proofs(draft.id)) >= MAX_PROOFS:
        raise DraftError(TOO_MANY)
    document = await add_file(ctx, data, filename, private=True, direction="outgoing", source=PROOF_SOURCE)
    proof = store.add_proof(
        draft_id=draft.id,
        kind=kind,
        doc_id=document.id,
        on_date=day.isoformat() if day else None,
        note=(note or "").strip() or None,
    )
    store.log_activity(
        "draft.proof",
        f"Added proof to “{draft.subject}”: {kind_info(kind).label} · kept private, not sent to AI",
        ref_type="draft",
        ref_id=draft.id,
        data={"proof_id": proof.id, "doc_id": document.id},
    )
    return proof


def update_proof(
    store: Store,
    draft_id: str,
    proof_id: str,
    *,
    today: date,
    kind: str | None = None,
    on_date: str | None = None,
    note: str | None = None,
    clear_date: bool = False,
) -> Proof:
    """Change a proof's kind, day or note (``clear_date`` removes the day)."""
    _proof(store, draft_id, proof_id)
    day = _checked(kind, on_date, note, today)
    changes: dict[str, object] = {}
    if kind is not None:
        changes["kind"] = kind
    if clear_date:
        changes["on_date"] = None
    elif day is not None:
        changes["on_date"] = day.isoformat()
    if note is not None:
        changes["note"] = note.strip() or None
    return store.update_proof(proof_id, **changes) if changes else _proof(store, draft_id, proof_id)


def _forget_file(store: Store, doc_id: str | None, *, keep: str | None = None) -> None:
    """Delete a proof file for good when it was added as proof and no other proof uses it."""
    if doc_id is None:
        return
    document = store.get_document(doc_id)
    others = [proof for proof in store.list_proofs(doc_id=doc_id) if proof.id != keep]
    if document is not None and document.source == PROOF_SOURCE and not others:
        store.delete_document(doc_id)


def remove_proof(store: Store, draft_id: str, proof_id: str) -> None:
    """Remove a proof and, when nothing else uses it, its file (for good)."""
    proof = _proof(store, draft_id, proof_id)
    with store.tx():
        store.delete_proof(proof.id)
        _forget_file(store, proof.doc_id)
        store.log_activity(
            "draft.proof_removed", "Removed a proof and its file", ref_type="draft", ref_id=draft_id
        )


def delete_letter(store: Store, draft_id: str) -> None:
    """Delete a letter with its proofs and their files."""
    draft = _draft(store, draft_id)
    files = [proof.doc_id for proof in store.list_proofs(draft.id) if proof.doc_id]
    with store.tx():
        store.delete_draft(draft.id)  # its proofs go with it (ON DELETE CASCADE)
        for doc_id in dict.fromkeys(files):
            _forget_file(store, doc_id)


# --------------------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------------------


def _recorded(proofs: list[Proof], documents: dict[str, Document]) -> list[RecordedProof]:
    return [
        RecordedProof(
            kind=proof.kind,
            on_date=proof.on_date,
            created_day=proof.created_at[:10],
            note=proof.note,
            document=documents.get(proof.doc_id or ""),
        )
        for proof in proofs
    ]


def _files(store: Store, proofs: list[Proof]) -> dict[str, Document]:
    found = (store.get_document(proof.doc_id) for proof in proofs if proof.doc_id)
    return {doc.id: doc for doc in found if doc is not None and doc.deleted_at is None}


def overview(store: Store, draft_id: str, today: date) -> ProofOverview:
    """A letter's tracking number, proofs (with what each shows), timeline, what's missing and what it
    waits for."""
    draft = _draft(store, draft_id)
    ledger = Ledger(store, today)
    proofs = ledger.proofs_of(draft.id)
    documents = _files(store, proofs)
    tracking = tracking_info(draft.tracking_number)
    reply = ledger.reply_to(draft)
    entries = [
        ProofEntry(
            proof=proof,
            document=documents.get(proof.doc_id or ""),
            label=kind_info(proof.kind).label,
            shows=kind_info(proof.kind).shows,
            does_not_show=kind_info(proof.kind).does_not_show,
        )
        for proof in proofs
    ]
    events = timeline(draft, tracking, _recorded(proofs, documents), reply)
    return ProofOverview(
        draft_id=draft.id,
        sent=draft.status == "sent",
        channel=draft.sent_channel,
        tracking=tracking,
        proofs=entries,
        timeline=[event.event() for event in events],
        missing=missing(draft, (proof.kind for proof in proofs), answered=reply is not None),
        waiting=letter_entry(ledger, draft),
        caveat=CAVEAT,
    )


def _enclosure(store: Store, proof: Proof, document: Document | None) -> NachweisFile | None:
    if document is None:
        return None
    info = kind_info(proof.kind)
    german, english = info.german, info.label
    if proof.on_date:
        day = parse_day(proof.on_date)
        if day is not None:
            german, english = (
                f"{german} vom {format_date(day, 'de')}",
                f"{english} of {format_date(day, 'en')}",
            )
    path = store.get_document_file(document.id)
    if document.mime == "application/pdf" and path is not None and path.is_file():
        return NachweisFile(german, english, info.shows, info.does_not_show, pdf=path.read_bytes())
    images = tuple(
        image
        for page in store.list_pages(document.id)
        if (image := store.data_dir / page.image_path).is_file()
    )
    return NachweisFile(german, english, info.shows, info.does_not_show, images=images) if images else None


def nachweis_pdf(store: Store, draft_id: str, today: date) -> bytes:
    """The Nachweis PDF of a sent letter: summary and timeline, the letter as sent, the proof files."""
    draft = _sent_draft(store, draft_id)
    ledger = Ledger(store, today)
    proofs = ledger.proofs_of(draft.id)
    documents = _files(store, proofs)
    tracking = tracking_info(draft.tracking_number)
    events = timeline(draft, tracking, _recorded(proofs, documents), ledger.reply_to(draft))
    lines = [
        NachweisLine(
            day=format_date(day, "de") if (day := parse_day(event.date)) else event.date,
            german=event.german,
            english=event.english,
            detail=event.detail,
        )
        for event in events
    ]
    files = [
        enclosed
        for proof in proofs
        if (enclosed := _enclosure(store, proof, documents.get(proof.doc_id or ""))) is not None
    ]
    sent_day = parse_day(draft.sent_at)
    sent = (
        f"{format_date(sent_day, 'de')} · {channel_label(draft.sent_channel, german=True)}"
        if sent_day
        else None
    )
    checked = " (Prüfziffer korrekt)" if tracking is not None and tracking.checked else ""
    facts = NachweisFacts(
        recipient=", ".join(line.strip() for line in draft.recipient_block.splitlines() if line.strip()),
        sender=store.get_profile().name,
        sent=sent,
        tracking=f"{tracking.display}{checked}" if tracking else None,
        created=format_date(today, "de"),
        caveat_de=CAVEAT_DE,
        caveat_en=CAVEAT,
    )
    return render_nachweis(draft, store.get_profile(), facts, lines, files)
