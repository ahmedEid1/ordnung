"""Letters waiting for the person (SPEC § 8, § 21 privacy): files the watched folder brought in.

A file that arrives in the watched folder was not handed to Ordnung by a click, so by default it is
**held**: stored and read on this computer only (its text layer, for search and the page images), and
never sent to Claude until the person says so. The policy:

* A held letter is private (``ai_private``) *and* has the status ``held``. Being private keeps it
  away from every model call — reading, Ask, the weekly review, the daily note, drafting — through
  the same checks as "Keep private — no AI"; the status tells it apart from a letter the person chose
  to keep private, so the Inbox can ask ("From your folder — waiting for you").
* **Read** (:func:`release`) ends the wait: the letter is no longer private and is queued to be read
  like an upload. **Keep private** (:func:`keep_private`) ends it too: the letter stays private, as if
  it had been added with "Keep private — no AI".
* Either answer covers an e-mail's attachments: they inherit its choice, so answering for a held
  e-mail answers for its held attachments as well. Only letters that are still held change; any other
  id is reported back as skipped (it was answered already, deleted, or never waited).
* **Undo** (:func:`back_to_waiting`): letters kept private this way — and never read by Claude —
  can wait again, so one mis-tap on "Keep private" is not final.
* Adding a held file again **by hand** (an upload, the command line) answers the question the same
  way: an upload is "read", a "Keep private" upload is "keep private"
  (:func:`ordnung.ingest.pipeline.add_file`, ``answer_held``). A copy arriving in the watched folder,
  or attached to an e-mail from it, never answers — whatever ``inbox_auto_read`` says.
* Nothing is ever read because time passed: a held letter waits until the person answers, or is
  deleted. Turning on ``inbox_auto_read`` reads new files only; the ones already waiting still ask,
  and so do the files that were already in a folder when it was chosen (:mod:`ordnung.ingest.watcher`).
* A held letter keeps waiting whatever happens to its reading on this computer: stopped, it is
  stored when Ordnung runs again; failed, the reason is kept in ``error`` and "Read" or "Keep private"
  starts over.

Each change is one transaction per call and is written to the activity log.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ordnung.db.store import Store
from ordnung.ingest.attachments import attached_to, email_source, is_email
from ordnung.models import Document, Job

HELD = "held"


@dataclass
class ConsentResult:
    """What an answer changed: the letters, the reading jobs queued (Read only) and the ids skipped."""

    documents: list[Document] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def is_held(document: Document) -> bool:
    """Whether ``document`` waits for the person (and is not in the trash)."""
    return document.status == HELD and document.deleted_at is None


def waiting(store: Store) -> list[Document]:
    """Every letter waiting for the person, oldest first, an e-mail's attachments right after it."""
    held = store.list_documents(status=HELD)
    by_id = {document.id: document for document in held}

    def arrival(document: Document) -> tuple[str, str, bool, str, str]:
        parent = by_id.get(attached_to(document) or "")
        first = parent or document
        return (first.created_at, first.id, parent is not None, document.created_at, document.id)

    return sorted(held, key=arrival)


def answered_together(store: Store, doc_ids: Iterable[str]) -> tuple[list[Document], list[str]]:
    """The held letters among ``doc_ids`` plus the held attachments of held e-mails among them
    (each once, in the order given, attachments after their e-mail), and the ids that are not held."""
    chosen: dict[str, Document] = {}
    skipped: list[str] = []
    for doc_id in dict.fromkeys(doc_ids):
        document = store.get_document(doc_id)
        if document is None or not is_held(document):
            skipped.append(doc_id)
            continue
        chosen.setdefault(document.id, document)
        if is_email(document):
            attachments = store.list_documents(status=HELD, source=email_source(document.id))
            for attachment in sorted(attachments, key=lambda doc: (doc.created_at, doc.id)):
                chosen.setdefault(attachment.id, attachment)
    return list(chosen.values()), skipped


def _name(document: Document) -> str:
    return document.title or document.filename


def release(store: Store, doc_ids: Iterable[str]) -> ConsentResult:
    """“Read these”: the held letters (see :func:`answered_together`) may be sent to Claude — each is
    made not private and queued for reading. The caller announces the jobs to the worker."""
    with store.tx():
        documents, skipped = answered_together(store, doc_ids)
        result = ConsentResult(skipped=skipped)
        for document in documents:
            result.documents.append(
                store.update_document(document.id, ai_private=False, status="queued", error=None)
            )
            # a local reading that has not started yet now reads it in full; a running one ends
            # without touching it (``pipeline._finish_private``), so it needs a job of its own
            pending = store.latest_job(document.id)
            if pending is None or pending.status != "queued":
                pending = store.enqueue_job("ingest", document.id)
            result.jobs.append(pending)
            store.log_activity(
                "document.released",
                f"You let Claude read “{_name(document)}”",
                ref_type="document",
                ref_id=document.id,
            )
    return result


def _local_reading_pending(store: Store, document: Document) -> bool:
    """Whether the letter's reading on this computer is still to come or under way."""
    job = store.latest_job(document.id)
    return job is not None and job.status in ("queued", "running", "waiting")


def keep_private(store: Store, doc_ids: Iterable[str]) -> ConsentResult:
    """“Keep private”: the held letters stay on this computer, never sent to Claude — as if they had
    been added with "Keep private — no AI". One whose reading on this computer failed or never ran
    is queued for it again (``jobs``; the caller announces them)."""
    with store.tx():
        documents, skipped = answered_together(store, doc_ids)
        result = ConsentResult(skipped=skipped)
        for document in documents:
            redo = document.processed_at is None and not _local_reading_pending(store, document)
            result.documents.append(store.update_document(document.id, status="processed", error=None))
            if redo:
                result.jobs.append(store.enqueue_job("ingest", document.id))
            store.log_activity(
                KEPT_PRIVATE,
                f"You kept “{_name(document)}” private · not sent to AI",
                ref_type="document",
                ref_id=document.id,
            )
    return result


#: The activity of an answer (the newest one says how the person last answered a letter's wait).
KEPT_PRIVATE = "document.kept_private"
_ANSWERS = (KEPT_PRIVATE, "document.released", "document.waiting")


def was_kept_from_waiting(store: Store, document: Document) -> bool:
    """Whether ``document`` is private because the person answered its wait with "Keep private" (and
    nothing was read by Claude since): it may wait again (:func:`back_to_waiting`)."""
    if document.deleted_at is not None or not document.ai_private or document.ai_processed_at:
        return False
    if document.status not in ("processed", "failed"):
        return False
    entry = store.last_activity("document", document.id, _ANSWERS)
    return entry is not None and entry.kind == KEPT_PRIVATE


def back_to_waiting(store: Store, doc_ids: Iterable[str]) -> ConsentResult:
    """Undo "Keep private": letters kept private by answering their wait wait again (``held``), as
    they were. Any other id is skipped (never waited, read since, deleted)."""
    with store.tx():
        result = ConsentResult()
        for doc_id in dict.fromkeys(doc_ids):
            document = store.get_document(doc_id)
            if document is None or not was_kept_from_waiting(store, document):
                result.skipped.append(doc_id)
                continue
            result.documents.append(store.update_document(document.id, status=HELD))
            store.log_activity(
                "document.waiting",
                f"“{_name(document)}” waits for you again",
                ref_type="document",
                ref_id=document.id,
            )
    return result
