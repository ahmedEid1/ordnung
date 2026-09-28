"""After a letter is sent: its tracking number, its proofs and their files, the proof overview and the
"Nachweis" PDF (SPEC § 11). What counts and what is said is :mod:`ordnung.drafts.proof`; this module
stores and reads.

* **Proof files are private.** They go through the normal intake (every size and expansion limit) as
  documents with direction ``outgoing``, ``source="proof"`` and "Keep private — no AI" on, so no model
  ever sees them. A file already in Ordnung (the same bytes) is linked as it is, and what is said about
  it is true of *that* file (:func:`add_proof`): one no model has had yet is made private now; one a
  model call ever carried — read, or failed or paused after the model had it — is said to have been
  given to AI, also when it was marked private later: "kept private" is never claimed for it. One that
  waits for the person's answer from the watched folder (:mod:`ordnung.ingest.held`) gets it now: *Keep
  private* — a proof is never offered to Claude with "Read these".
* **A proof e-mail's attachments are no letters.** A sent e-mail kept as proof is one file: its
  attachments are never added (also when the same ``.eml`` arrives again, :mod:`ordnung.ingest.pipeline`),
  and the ones it brought while it waited in the Inbox as a letter — still waiting, never read — are
  deleted for good when it becomes proof: the proof e-mail holds them itself. Attachments the person
  already answered for (read, or kept private) stay.
* **Only sent letters take proof**, at most :data:`~ordnung.drafts.proof.MAX_PROOFS` of them, each file
  once per letter; a proof's day can't be in the future, and a delivery can't be before the sending.
* **An answer is the person's word** (:func:`mark_answered`): the day, and the letter that answered if
  they name one; the follow-up to-do closes with it, and taking it back reopens the follow-up.
* **The letter as sent is what went out.** Marking a letter as sent keeps what its PDF showed of the
  sender (:class:`~ordnung.models.SentSigner`), so the PDF and the Nachweis show that even after the
  profile changed; the text of a sent letter can't be edited (the API refuses it). A letter "sent" by a
  cancel button, portal or e-mail went out as text, not as this letter — the Nachweis says so.
* **Delete means delete** (ADR 0014). Removing a proof deletes its file for good when it was added as
  proof and no other proof uses it; deleting a letter deletes its proofs and their files the same way,
  unless the person keeps the files (they become their own documents). The web app's confirmation
  names the file and offers to download it first.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ordnung.db.store import NotFoundError, Store
from ordnung.drafts.compose import NO_TRACKING, DraftError
from ordnung.drafts.pdf import NachweisFacts, NachweisFile, NachweisLine, render_nachweis
from ordnung.drafts.proof import (
    CAVEAT,
    CAVEAT_DE,
    DELIVERY_DAY_KINDS,
    MAX_NOTE,
    MAX_PROOFS,
    PROOF_KINDS,
    PROOF_SOURCE,
    RecordedProof,
    channel_label,
    conflicts,
    followup_item_id,
    kind_info,
    missing,
    sent_day,
    timeline,
)
from ordnung.drafts.templates import format_date
from ordnung.drafts.tracking import TrackingError, parse_tracking_number, tracking_info
from ordnung.ingest import held as consent
from ordnung.ingest.attachments import email_source, is_email
from ordnung.ingest.pipeline import add_file, keep_held_private
from ordnung.models import Document, Draft, Profile, Proof, ProofEntry, ProofOverview
from ordnung.secretary.triggers import Ledger, parse_day
from ordnung.secretary.waiting import letter_entry

if TYPE_CHECKING:
    from ordnung.app_context import AppContext

NOT_SENT = "Mark the letter as sent first — proof belongs to a letter that went out."
TOO_MANY = f"A letter can hold up to {MAX_PROOFS} proofs. Remove one you don't need first."
FUTURE_DAY = "The day a proof shows can't be in the future."
UNKNOWN_KIND = "Choose what the proof is (posting receipt, delivery record …)."
ALREADY_PROOF = "This file is already a proof of this letter."
UNKNOWN_ANSWER = "That letter isn't in Ordnung any more — close this without naming it."
#: How the letter's text went out, per channel: (German, English) caption of the Nachweis enclosure.
LETTER_AS_SENT = ("Das Schreiben wie versandt", "The letter as sent")
LETTER_AS_RECORDED = ("Das Schreiben, wie in Ordnung gespeichert", "The letter as recorded in Ordnung")
TEXT_ONLY = {
    "online_button": (
        "Text wie in Ordnung verfasst – nicht als Brief versandt (Kündigungsbutton)",
        "The text as written in Ordnung — not sent as a letter (the cancel button)",
    ),
    "portal": (
        "Text wie in Ordnung verfasst – nicht als Brief versandt (Online-Portal)",
        "The text as written in Ordnung — not sent as a letter (online portal)",
    ),
    "email": (
        "Text wie in Ordnung verfasst – per E-Mail versandt; was gesendet wurde, zeigt die E-Mail",
        "The text as written in Ordnung — sent by e-mail; the sent e-mail shows what went out",
    ),
}
PRIVATE = "kept private, not sent to AI"
MADE_PRIVATE_NOTICE = (
    "This file was already in Ordnung, not yet read. It is kept private from now on — AI won't read it."
)
READ_NOTICE = (
    "This file was already in Ordnung as a letter, and it was already given to AI to read. It is linked "
    "as proof and stays where it was."
)


def _delivery_before_sending(kind: str | None, day: date | None, draft: Draft) -> str | None:
    sent = sent_day(draft)
    if kind in DELIVERY_DAY_KINDS and day is not None and sent is not None and day < sent:
        return (
            f"A delivery can't be before the letter was sent ({format_date(sent, 'en')}) — check the day, "
            "or the day you marked the letter as sent."
        )
    return None


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


def _checked(
    kind: str | None, on_date: str | None, note: str | None, today: date, draft: Draft | None = None
) -> date | None:
    """Refuse an unknown kind, a day that isn't one, lies in the future or (for a delivery) before the
    sending, and a long note; returns the day."""
    if kind is not None and kind not in PROOF_KINDS:
        raise DraftError(UNKNOWN_KIND)
    day = parse_day(on_date) if on_date else None
    if on_date and day is None:
        raise DraftError(f"“{on_date}” is not a date.")
    if day is not None and day > today:
        raise DraftError(FUTURE_DAY)
    if draft is not None and (refused := _delivery_before_sending(kind, day, draft)):
        raise DraftError(refused)
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
        if draft.sent_channel != "registered_letter":
            raise DraftError(NO_TRACKING)
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


@dataclass(frozen=True)
class AddedProof:
    """A proof just added, and what to tell the person about its file when it was already in Ordnung
    (``notice``; ``None``: the file is private and was never sent to AI)."""

    proof: Proof
    notice: str | None = None

    @property
    def id(self) -> str:
        return self.proof.id

    @property
    def doc_id(self) -> str | None:
        return self.proof.doc_id


def _given_to_model(store: Store, document: Document) -> bool:
    """Whether a model had the file: it was read, or any model call carried it
    (:meth:`~ordnung.db.store.Store.given_to_model` — a reading that failed after the model transcribed
    it, or was queued again after a rate limit, did), whatever its "Keep private" says now."""
    return document.ai_processed_at is not None or store.given_to_model(document.id)


def _keep_private(store: Store, document: Document) -> tuple[Document, str | None, str]:
    """Make a file already in Ordnung private if no model had it yet and none is reading it now (it
    waits to be read, or failed before a model had it); returns it, the notice for the person and the
    words for the activity log (see the module docstring)."""
    given = _given_to_model(store, document)
    if document.ai_private and not given:
        return document, None, PRIVATE
    if not given and document.status in ("queued", "failed"):
        return (
            store.update_document(document.id, ai_private=True),
            MADE_PRIVATE_NOTICE,
            f"already in Ordnung, now {PRIVATE}",
        )
    return document, READ_NOTICE, "already in Ordnung as a letter that was given to AI"


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
) -> AddedProof:
    """Store a proof file privately and attach it to a sent letter (see the module docstring)."""
    store = ctx.store
    draft = _sent_draft(store, draft_id)
    day = _checked(kind, on_date, note, today, draft)
    proofs = store.list_proofs(draft.id)
    if len(proofs) >= MAX_PROOFS:
        raise DraftError(TOO_MANY)
    document = await add_file(
        ctx,
        data,
        filename,
        private=True,
        direction="outgoing",
        source=PROOF_SOURCE,
        with_attachments=False,  # a sent e-mail kept as proof is one file: no letters from its attachments
    )
    if any(proof.doc_id == document.id for proof in proofs):
        raise DraftError(ALREADY_PROOF)
    if is_email(document):
        _drop_waiting_attachments(store, document)
    if consent.is_held(document):  # from the watched folder, still waiting: proof is kept private
        kept = keep_held_private(ctx, [document.id]).documents  # an e-mail's held attachments with it
        document = next((doc for doc in kept if doc.id == document.id), document)
    document, notice, said = _keep_private(store, document)
    proof = store.add_proof(
        draft_id=draft.id,
        kind=kind,
        doc_id=document.id,
        on_date=day.isoformat() if day else None,
        note=(note or "").strip() or None,
    )
    store.log_activity(
        "draft.proof",
        f"Added proof to “{draft.subject}”: {kind_info(kind).label} · {said}",
        ref_type="draft",
        ref_id=draft.id,
        data={"proof_id": proof.id, "doc_id": document.id},
    )
    return AddedProof(proof, notice)


def _drop_waiting_attachments(store: Store, email_doc: Document) -> None:
    """Delete for good the attachments an e-mail brought that still wait for the person (module policy:
    a proof e-mail's attachments are no letters; the e-mail itself keeps them)."""
    waiting = store.list_documents(status=consent.HELD, source=email_source(email_doc.id))
    for attachment in waiting:
        store.delete_document(attachment.id)
    if waiting:
        store.log_activity(
            "document.deleted",
            f"Removed {len(waiting)} attachment{'s' if len(waiting) != 1 else ''} of “{email_doc.filename}” "
            "that waited: it is kept as proof, with its attachments in it",
            ref_type="document",
            ref_id=email_doc.id,
        )


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
    clear_note: bool = False,
) -> Proof:
    """Change a proof's kind, day or note (``clear_date`` removes the day, ``clear_note`` or an empty
    ``note`` the note)."""
    current = _proof(store, draft_id, proof_id)
    day = _checked(kind, on_date, note, today)
    kept_day = None if clear_date else (day or parse_day(current.on_date))
    if refused := _delivery_before_sending(kind or current.kind, kept_day, _draft(store, draft_id)):
        raise DraftError(refused)
    changes: dict[str, object] = {}
    if kind is not None:
        changes["kind"] = kind
    if clear_date:
        changes["on_date"] = None
    elif day is not None:
        changes["on_date"] = day.isoformat()
    if clear_note:
        changes["note"] = None
    elif note is not None:
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


def delete_letter(store: Store, draft_id: str, *, keep_files: bool = False) -> None:
    """Delete a letter with its proofs and — unless ``keep_files`` — their files. A kept proof file
    becomes a document of its own (still private and outgoing), so it is listed with the letters."""
    draft = _draft(store, draft_id)
    files = [proof.doc_id for proof in store.list_proofs(draft.id) if proof.doc_id]
    with store.tx():
        store.delete_draft(draft.id)  # its proofs go with it (ON DELETE CASCADE)
        for doc_id in dict.fromkeys(files):
            if not keep_files:
                _forget_file(store, doc_id)
                continue
            document = store.get_document(doc_id)
            if (
                document is not None
                and document.source == PROOF_SOURCE
                and not store.list_proofs(doc_id=doc_id)
            ):
                store.update_document(doc_id, source="upload")
        store.log_activity(
            "draft.deleted",
            f"Deleted the letter “{draft.subject}”"
            + (
                f" and its {len(files)} proof file{'s' if len(files) != 1 else ''}"
                if files and not keep_files
                else ""
            ),
            ref_type="draft",
            ref_id=draft.id,
        )


def mark_answered(store: Store, draft_id: str, today: date, *, doc_id: str | None = None) -> Draft:
    """The person says a sent letter was answered — by the letter ``doc_id``, or (``None``) by phone,
    e-mail or a letter they don't name. Closes its follow-up to-do (policy 3 of ``drafts.proof``)."""
    draft = _sent_draft(store, draft_id)
    if doc_id is not None:
        document = store.get_document(doc_id)
        if (
            document is None
            or document.deleted_at is not None
            or document.source == PROOF_SOURCE
            or document.direction != "incoming"
        ):
            raise DraftError(UNKNOWN_ANSWER)
    with store.tx():
        updated = store.update_draft(draft.id, answered_on=today.isoformat(), answer_doc_id=doc_id)
        followup = store.get_item(followup_item_id(draft.id))
        # a snoozed follow-up is closed too: snoozing put off the reminder, the answer ends the wait
        closed = followup is not None and followup.status in ("open", "snoozed")
        if closed:
            assert followup is not None
            store.update_item(followup.id, status="done")
        store.log_activity(
            "draft.answered",
            f"Marked “{draft.subject}” as answered",
            ref_type="draft",
            ref_id=draft.id,
            data={"followup_was": followup.status} if closed and followup is not None else None,
        )
    return updated


def unmark_answered(store: Store, draft_id: str) -> Draft:
    """Take back :func:`mark_answered`: the letter waits again and its follow-up to-do is back as it was
    (open, or snoozed until the day it was snoozed to)."""
    draft = _sent_draft(store, draft_id)
    with store.tx():
        marked = store.last_activity("draft", draft.id, ["draft.answered"])
        was = marked.data.get("followup_was") if marked is not None and marked.data else None
        updated = store.update_draft(draft.id, answered_on=None, answer_doc_id=None)
        followup = store.get_item(followup_item_id(draft.id))
        if followup is not None and followup.status == "done":
            store.update_item(followup.id, status="snoozed" if was == "snoozed" else "open")
        store.log_activity(
            "draft.answered",
            f"“{draft.subject}” is waiting for an answer again",
            ref_type="draft",
            ref_id=draft.id,
        )
    return updated


def letter_profile(store: Store, draft: Draft) -> Profile:
    """The profile the letter's PDF uses: today's, with what the letter showed of the sender when it was
    marked as sent (name, e-mail, phone) — so a sent letter prints as it went out."""
    profile = store.get_profile()
    signer = store.get_sent_signer(draft.id) if draft.status == "sent" else None
    return profile.model_copy(update=signer.model_dump()) if signer is not None else profile


# --------------------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------------------


def _local_days(store: Store, today: date) -> Callable[[str], str]:
    """The day of a stored UTC timestamp in the person's time zone — a letter drafted or a proof added
    at 00:30 in Berlin is of that day, not the day before, in the Nachweis too — never after ``today``
    (the demo stamps its pinned day with the time of day it is run)."""
    try:
        zone = ZoneInfo(store.get_profile().timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = None

    def day(stamp: str) -> str:
        try:
            moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            return stamp[:10]
        if zone is None or moment.tzinfo is None:
            return stamp[:10]
        return min(moment.astimezone(zone).date(), today).isoformat()

    return day


def _recorded(
    proofs: list[Proof], documents: dict[str, Document], local_day: Callable[[str], str]
) -> list[RecordedProof]:
    return [
        RecordedProof(
            kind=proof.kind,
            on_date=proof.on_date,
            created_day=local_day(proof.created_at),
            note=proof.note,
            document=documents.get(proof.doc_id or ""),
        )
        for proof in proofs
    ]


def _files(store: Store, proofs: list[Proof]) -> dict[str, Document]:
    found = (store.get_document(proof.doc_id) for proof in proofs if proof.doc_id)
    return {doc.id: doc for doc in found if doc is not None and doc.deleted_at is None}


def overview(store: Store, draft_id: str, today: date) -> ProofOverview:
    """A letter's tracking number, proofs (with what each shows), timeline, what's missing, days that
    contradict each other and what it waits for."""
    draft = _draft(store, draft_id)
    ledger = Ledger(store, today)
    proofs = ledger.proofs_of(draft.id)
    documents = _files(store, proofs)
    tracking = tracking_info(draft.tracking_number)
    answer = ledger.answer_of(draft)
    local_day = _local_days(store, today)
    recorded = _recorded(proofs, documents, local_day)
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
    events = timeline(
        draft, tracking, recorded, answer, ledger.reply_to(draft), created_day=local_day(draft.created_at)
    )
    return ProofOverview(
        draft_id=draft.id,
        sent=draft.status == "sent",
        channel=draft.sent_channel,
        tracking=tracking,
        proofs=entries,
        timeline=[event.event() for event in events],
        missing=missing(draft, recorded, answer=answer, today=today),
        conflicts=conflicts(draft, recorded),
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


def _enclosed_letter(store: Store, draft: Draft) -> tuple[str, str]:
    """How the Nachweis names the letter it encloses (see the module docstring)."""
    if draft.sent_channel in TEXT_ONLY:
        return TEXT_ONLY[draft.sent_channel]
    return LETTER_AS_SENT if store.get_sent_signer(draft.id) is not None else LETTER_AS_RECORDED


def _nachweis_day(day: str | None) -> str:
    parsed = parse_day(day) if day else None
    return format_date(parsed, "de") if parsed else (day or "")


def nachweis_file_name(draft: Draft) -> str:
    """``Nachweis Kündigung Mitgliedschaft FW-4711 2026-09-10.pdf``: the letter's subject (without
    characters file systems refuse, at most 80) and its sending day."""
    subject = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", draft.subject or "Schreiben")
    words = " ".join(subject.split())[:80].strip() or "Schreiben"
    day = (draft.sent_at or draft.created_at)[:10]
    return f"Nachweis {words} {day}.pdf"


def nachweis_pdf(store: Store, draft_id: str, today: date) -> bytes:
    """The Nachweis PDF of a sent letter: summary and timeline, the letter (as sent), the proof files.
    A possible answer the person hasn't confirmed is left out; proofs without a day are listed apart."""
    draft = _sent_draft(store, draft_id)
    ledger = Ledger(store, today)
    proofs = ledger.proofs_of(draft.id)
    documents = _files(store, proofs)
    tracking = tracking_info(draft.tracking_number)
    local_day = _local_days(store, today)
    recorded = _recorded(proofs, documents, local_day)
    answer = ledger.answer_of(draft)
    events = [
        event
        for event in timeline(draft, tracking, recorded, answer, created_day=local_day(draft.created_at))
        if event.in_nachweis
    ]
    lines = [
        NachweisLine(
            day=_nachweis_day(event.date), german=event.german, english=event.english, detail=event.detail
        )
        for event in events
        if event.date is not None
    ]
    undated = [
        NachweisLine(
            day="ohne Datum",
            german=f"{event.german} – Tag nicht angegeben, hinzugefügt am {_nachweis_day(event.added_on)}",
            english=f"{event.english} — no day given, added on {_nachweis_day(event.added_on)}",
            detail=event.detail,
        )
        for event in events
        if event.date is None
    ]
    files = [
        enclosed
        for proof in proofs
        if (enclosed := _enclosure(store, proof, documents.get(proof.doc_id or ""))) is not None
    ]
    sent_on = parse_day(draft.sent_at)
    sent = (
        f"{format_date(sent_on, 'de')} · {channel_label(draft.sent_channel, german=True)}"
        if sent_on
        else None
    )
    checked = " (Prüfziffer korrekt)" if tracking is not None and tracking.checked else ""
    profile = letter_profile(store, draft)
    facts = NachweisFacts(
        recipient=", ".join(line.strip() for line in draft.recipient_block.splitlines() if line.strip()),
        sender=profile.name,
        sent=sent,
        tracking=f"{tracking.display}{checked}" if tracking else None,
        created=format_date(today, "de"),
        caveat_de=CAVEAT_DE,
        caveat_en=CAVEAT,
        letter=_enclosed_letter(store, draft),
    )
    return render_nachweis(draft, profile, facts, lines, files, undated=undated)
