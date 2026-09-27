"""E-mail attachments (SPEC § 8 intake): which parts of an ``.eml`` become letters of their own.

Bills from phone, energy and insurance companies mostly arrive as a PDF attached to an e-mail, so an
e-mail's attachments are read like letters dropped in. The policy, which decides every case:

* **What is an attachment** — every part of the message except the multipart containers and its body
  text (a ``text/plain`` or ``text/html`` part without a file name that is not marked as an
  attachment), in the order of the message. A forwarded e-mail (``message/rfc822``) is one part: it
  is listed, never opened.
* **What is read** — PDFs and photos (JPEG, PNG, WEBP, HEIC/HEIF), decided by the bytes like any
  upload (:func:`~ordnung.ingest.intake.sniff_mime`), never by the declared type or the file name.
  Everything else — a zip, a Word file, a calendar invite, a text file, a forwarded e-mail — is
  listed and not read.
* **Pictures inside the e-mail are skipped** — an image the HTML body shows through a ``cid:`` link,
  or an image not marked as an attachment that is smaller than :data:`INLINE_IMAGE_MAX_BYTES`, is part
  of the e-mail's design (a logo, a tracking pixel). PDFs are never skipped this way.
* **At most** :data:`MAX_ATTACHMENTS` attachments of one e-mail are read, the first ones in the
  message; later ones are listed. At most :data:`MAX_LISTED` parts are listed at all.
* Each attachment that is read goes through the normal intake with every limit (size, pages, pixels,
  PDF stream expansion) as its own document with ``source="email:<the e-mail's id>"``; it inherits
  the e-mail's privacy choice ("Keep private", or waiting for the person) and its arrival date, and
  joins the e-mail's thread (:func:`ordnung.ingest.link.email_family_case`). The e-mail itself is
  bounded by the intake's size limit before it is parsed, and parsing is linear in its size.

Not decided here (documented limitations): an e-mail whose body repeats what its attached bill says
("39,99 EUR due on 15 Oct") gives both letters a to-do; a photo the sender pasted into the text (shown
through ``cid:``) is listed as a picture inside the e-mail, not read — it can be added by hand.
"""

from __future__ import annotations

import email
import email.policy
import re
from collections.abc import Iterator
from dataclasses import dataclass
from email.message import EmailMessage, Message
from pathlib import PurePosixPath
from typing import Literal, cast
from urllib.parse import unquote

from ordnung.db.store import Store
from ordnung.ingest.intake import IMAGE_TYPES, IntakeError, safe_filename, sniff_mime
from ordnung.models import AttachmentOutcome, Document, EmailAttachment

MAX_ATTACHMENTS = 10
MAX_LISTED = 50
INLINE_IMAGE_MAX_BYTES = 64 * 1024
MAX_NAME_CHARS = 200
EMAIL_SOURCE_PREFIX = "email:"
EMAIL_MIME = "message/rfc822"
#: The activity entry that records what became of an e-mail's attachments (its ``data``).
ATTACHMENTS_ACTIVITY = "email.attachments"

READ_TYPES = frozenset({"application/pdf", *IMAGE_TYPES})
_BODY_SUBTYPES = frozenset({"plain", "html"})
_CID_RE = re.compile(r"""cid:([^"'\s<>()]+)""", re.IGNORECASE)
_EXTENSIONS = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
}

Decision = Literal["read", "inline", "not_read", "over_limit"]

#: What the person reads next to each attachment (``refused`` carries the intake's own reason).
OUTCOME_DETAIL: dict[AttachmentOutcome, str] = {
    "added": "Added as its own letter",
    "known": "Already in Ordnung",
    "inline": "A picture inside the e-mail (a logo or similar) — not read",
    "not_read": "Ordnung reads PDFs and photos from e-mails — this file is listed only",
    "refused": "Not added",
    "over_limit": f"Only the first {MAX_ATTACHMENTS} attachments of an e-mail are read",
}


@dataclass(frozen=True, slots=True)
class Attachment:
    """One attachment and the policy's decision (``data`` is empty unless it is to be read)."""

    filename: str
    decision: Decision
    data: bytes = b""


@dataclass(frozen=True, slots=True)
class EmailParts:
    """The attachments of an e-mail in message order, and how many more were not listed."""

    attachments: tuple[Attachment, ...]
    more: int = 0


# --------------------------------------------------------------------------------------------------
# The policy (pure)
# --------------------------------------------------------------------------------------------------


def email_attachments(data: bytes) -> EmailParts:
    """Split an e-mail's bytes into its attachments and decide what becomes of each (see the module)."""
    message = cast(EmailMessage, email.message_from_bytes(data, policy=email.policy.default))
    leaves = list(_leaves(message))
    cids = _cid_links(part for part in leaves if _is_body_text(part) and part.get_content_subtype() == "html")
    listed: list[Attachment] = []
    more = read = 0
    for part in leaves:
        if _is_body_text(part):
            continue
        if len(listed) >= MAX_LISTED:
            more += 1
            continue
        attachment = _decide(part, len(listed) + 1, cids, room=read < MAX_ATTACHMENTS)
        read += attachment.decision == "read"
        listed.append(attachment)
    return EmailParts(tuple(listed), more)


def _leaves(message: Message) -> Iterator[Message]:
    """The message's parts that are not multipart containers, depth first in message order.

    Iterative, so a deeply nested message cannot exhaust the stack. A ``message/rfc822`` part is a
    leaf: an attached e-mail is never opened.
    """
    stack: list[Message] = [message]
    while stack:
        part = stack.pop()
        if part.get_content_maintype() == "multipart":
            children = part.get_payload()
            if isinstance(children, list):
                stack.extend(child for child in reversed(children) if isinstance(child, Message))
            continue
        yield part


def _is_body_text(part: Message) -> bool:
    return (
        part.get_content_maintype() == "text"
        and part.get_content_subtype() in _BODY_SUBTYPES
        and part.get_content_disposition() != "attachment"
        and not _filename(part)
    )


def _cid_links(html_parts: Iterator[Message]) -> frozenset[str]:
    """The Content-IDs the HTML body links to (``<img src="cid:logo@x">``), normalised."""
    found: set[str] = set()
    for part in html_parts:
        found.update(_cid_key(match) for match in _CID_RE.findall(_text_of(part)))
    return frozenset(found)


def _cid_key(value: str) -> str:
    return unquote(value).strip().strip("<>").casefold()


def _text_of(part: Message) -> str:
    try:
        return str(cast(EmailMessage, part).get_content())
    except (LookupError, UnicodeError, AttributeError):
        payload = part.get_payload(decode=True)
        return payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else ""


def _filename(part: Message) -> str:
    try:
        return part.get_filename() or ""
    except (ValueError, LookupError):  # a malformed RFC 2231 name
        return ""


def _payload(part: Message) -> bytes:
    if part.get_content_type() == EMAIL_MIME:
        return b""
    payload = part.get_payload(decode=True)
    return payload if isinstance(payload, bytes) else b""


def _decide(part: Message, number: int, cids: frozenset[str], *, room: bool) -> Attachment:
    data = _payload(part)
    mime = _readable_type(data, _filename(part))
    name = _display_name(_filename(part), mime, part.get_content_type(), number)
    if mime is None:
        return Attachment(name, "not_read")
    if mime in IMAGE_TYPES and _inside_the_email(part, data, cids):
        return Attachment(name, "inline")
    if not room:
        return Attachment(name, "over_limit")
    return Attachment(name, "read", data)


def _readable_type(data: bytes, filename: str) -> str | None:
    """The part's type when Ordnung reads it from e-mails (a PDF or a photo), by its bytes."""
    if not data:
        return None
    try:
        mime = sniff_mime(data, filename)
    except IntakeError:
        return None
    return mime if mime in READ_TYPES else None


def _inside_the_email(part: Message, data: bytes, cids: frozenset[str]) -> bool:
    """A picture that is part of the e-mail's design: linked from its HTML, or small and not attached."""
    content_id = part.get("Content-ID")
    if content_id and _cid_key(str(content_id)) in cids:
        return True
    return part.get_content_disposition() != "attachment" and len(data) < INLINE_IMAGE_MAX_BYTES


def _display_name(filename: str, mime: str | None, declared: str, number: int) -> str:
    """A safe, bounded name: the part's own (without path or control characters), else one made up."""
    name = safe_filename(filename) if filename.strip() else ""
    if not name or name == "document":
        extension = _EXTENSIONS.get(mime or "") or declared.rsplit("/", 1)[-1][:10] or "bin"
        return f"attachment-{number}.{extension}"
    if len(name) <= MAX_NAME_CHARS:
        return name
    suffix = PurePosixPath(name).suffix[:16]
    return name[: MAX_NAME_CHARS - len(suffix) - 1] + "…" + suffix


# --------------------------------------------------------------------------------------------------
# Sources and the stored listing
# --------------------------------------------------------------------------------------------------


def email_source(parent_id: str) -> str:
    """The ``source`` of a document that came attached to the e-mail ``parent_id``."""
    return f"{EMAIL_SOURCE_PREFIX}{parent_id}"


def email_parent(source: str) -> str | None:
    """The id of the e-mail a document of this ``source`` came attached to (``None``: none)."""
    return source.removeprefix(EMAIL_SOURCE_PREFIX) if source.startswith(EMAIL_SOURCE_PREFIX) else None


def attached_to(document: Document) -> str | None:
    """The id of the e-mail ``document`` came attached to (``None``: it did not)."""
    return email_parent(document.source)


def is_email(document: Document) -> bool:
    """Whether ``document`` is an e-mail (its attachments may be letters of their own)."""
    return document.mime == EMAIL_MIME


def attachment_listing(store: Store, document: Document) -> list[EmailAttachment]:
    """What became of an e-mail's attachments, as recorded when it was added.

    A letter an attachment became is linked only while it exists and is not in the trash.
    """
    if not is_email(document):
        return []
    entry = store.last_activity("document", document.id, [ATTACHMENTS_ACTIVITY])
    rows = entry.data.get("attachments", []) if entry is not None else []
    listing: list[EmailAttachment] = []
    for row in rows if isinstance(rows, list) else []:
        try:
            attachment = EmailAttachment.model_validate(row)
        except ValueError:
            continue
        linked = store.get_document(attachment.doc_id) if attachment.doc_id else None
        live = linked is not None and linked.deleted_at is None
        listing.append(attachment.model_copy(update={"doc_id": attachment.doc_id if live else None}))
    return listing


def email_of(store: Store, document: Document) -> Document | None:
    """The e-mail ``document`` came attached to, while it exists and is not in the trash."""
    parent_id = attached_to(document)
    parent = store.get_document(parent_id) if parent_id else None
    return parent if parent is not None and parent.deleted_at is None else None
