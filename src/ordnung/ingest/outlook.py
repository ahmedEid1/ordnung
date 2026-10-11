"""Outlook ``.msg`` files (SPEC § 8): an e-mail Outlook saved ("Save as", or dragged to the desktop) is
opened on this computer and stored as the ``.eml`` copy Ordnung already reads: its sender, date, subject
and text, and every attached PDF or photo as a letter of its own (:mod:`ordnung.ingest.attachments`). The
conversion runs before intake looks at the bytes (:func:`~ordnung.ingest.intake.sniff_mime`) at every way
in: upload and the phone, the watched folder, ``ordnung add`` and proof of a sent letter. So an Outlook
file whose first bytes hold an attached PDF is never called a broken PDF.

The policy, which decides every case:

* **Which files.** An OLE compound file (its first 8 bytes are :data:`OLE_MAGIC`), whatever its name.
  Every other file passes through unchanged (:func:`as_email`).
* **Opened from memory, strictly.** olefile reads it from a ``BytesIO`` (it takes ``bytes`` shorter than
  1,536 for a file *path*), read-only, and every defect from ``DEFECT_INCORRECT`` up is an error: a
  stream larger than the file, an incomplete stream, an entry or a stream referenced twice.
* **Only e-mails.** Message class ``IPM.Note`` or ``IPM.Note.*``. A signed or encrypted one
  (``…SMIME…``) is refused, and so are calendar entries, contacts and tasks, older Word, Excel and
  PowerPoint files and any other OLE file, each with its reason.
* **Bounded.** The file is at most 50 MB (:data:`~ordnung.ingest.intake.MAX_BYTES`) and has at most
  :data:`MAX_ENTRIES` directory entries, counted before olefile builds them. No stream is larger than the
  file, and at most :data:`READ_BUDGET_FACTOR` times the file's size is read in all (entries may share
  sectors). At most :data:`MAX_WITH_BYTES` attachments keep their bytes; later ones keep only their
  names, so the e-mail still lists them. At most :data:`MAX_RECIPIENTS` recipients. A header value loses
  its control characters and is at most :data:`MAX_HEADER_CHARS` long. Outlook's copy of the original
  headers is read up to :data:`MAX_TRANSPORT_HEADERS`. The result is at most 50 MB. A tree too deep for
  the parser (``RecursionError``), or any other parser error, is "damaged".
* **The same file, the same e-mail.** No Date or Message-ID is made up, and the MIME boundaries come from
  the file's SHA-256, so adding a ``.msg`` twice finds the letter already in Ordnung.
* **Headers.** From, To, Cc, Date, Subject, Message-ID, In-Reply-To, References and Reply-To: from the
  original internet headers when Outlook kept them, else from the message's properties. Nothing else of
  the original headers is copied (no ``Content-*``, ``Received`` or ``X-*``). Bcc is left out. An
  Exchange-only address (an X.500 name, not an e-mail address) is dropped and the name stays.
* **Text.** The plain text and the HTML when there are both (``multipart/alternative``), else the one
  there is. A text kept only as RTF is not converted: the e-mail comes in without text, and its
  attachments are still listed and read. No sentence is added (Claude would read it as the sender's).
* **Attachments**, in their order. One kept by value keeps its bytes, name, type and Content-ID (inline
  when Outlook hid it or it has a Content-ID); a declared text type becomes ``application/octet-stream``,
  so an attachment never passes for the e-mail's text. An attached e-mail is an empty
  ``application/vnd.ms-outlook`` part named ``<name>.msg``: listed, never opened, like a forwarded e-mail
  in an ``.eml``. An OLE object or a link keeps only its name.
* **Kept.** The ``.eml`` copy, named like the file (``Rechnung.msg`` → ``Rechnung.eml``); the ``.msg``
  itself is not kept, so what only Outlook has (categories, flags, read state, RTF formatting) is lost.

olefile is imported only when an Outlook file arrives.
"""

from __future__ import annotations

import codecs
import email.parser
import email.policy
import functools
import hashlib
import io
import re
import struct
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage, MIMEPart
from email.utils import format_datetime, formataddr
from pathlib import PurePosixPath
from typing import Any, cast

from ordnung.ingest import intake
from ordnung.ingest.intake import IntakeError, check_size

OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
MAX_BYTES = intake.MAX_BYTES
MAX_ENTRIES = 20_000
READ_BUDGET_FACTOR = 2
MAX_WITH_BYTES = 50
MAX_RECIPIENTS = 500
MAX_HEADER_CHARS = 998
MAX_NAME_CHARS = 200
MAX_ADDRESS_CHARS = 320
MAX_TRANSPORT_HEADERS = 256 * 1024
SAFE_HEADERS = ("From", "To", "Cc", "Date", "Subject", "Message-ID", "In-Reply-To", "References", "Reply-To")

DAMAGED = (
    "This Outlook file can't be opened. It may be damaged. Save the e-mail again from Outlook, "
    "or save its attachments and add those."
)
NOT_AN_EMAIL = (
    "This Outlook file is a calendar entry, contact or task, not an e-mail. "
    "Ordnung only opens e-mails saved from Outlook."
)
OFFICE_FILE = (
    "This is an older Office file (Word, Excel or PowerPoint), not a letter. Save it as a PDF and add that."
)
ENCRYPTED = "This Outlook e-mail is signed or encrypted, so Ordnung can't open it. Save its attachments and add those."
TOO_LARGE = (
    "This Outlook e-mail is larger than 50 MB once opened. Save its attachments and add them one by one."
)
NOT_OUTLOOK = (
    "This file type is not supported. Please upload a PDF, a photo (JPEG, PNG, WEBP, HEIC) "
    "or a text or e-mail file (.txt, .eml, .msg)."
)

_POLICY = email.policy.SMTP
_OFFICE_STREAMS = frozenset({"WORDDOCUMENT", "WORKBOOK", "BOOK", "POWERPOINT DOCUMENT"})
# entry names, upper-cased ([MS-OXMSG] 2.2)
_PROPERTIES = "__PROPERTIES_VERSION1.0"
_RECIPIENT = "__RECIP_VERSION1.0_#"
_ATTACHMENT = "__ATTACH_VERSION1.0_#"
_OBJECT = "__SUBSTG1.0_3701000D"  # an attachment's object: an attached e-mail, or an OLE object
# property types and the properties read ([MS-OXPROPS])
_PT_LONG, _PT_BOOLEAN, _PT_SYSTIME, _PT_STRING8, _PT_UNICODE, _PT_BINARY = 0x3, 0xB, 0x40, 0x1E, 0x1F, 0x102
_MESSAGE_CLASS, _SUBJECT, _SENT_REPRESENTING_NAME, _TRANSPORT_HEADERS = 0x001A, 0x0037, 0x0042, 0x007D
_SENDER_NAME, _SENDER_ADDRTYPE, _SENDER_EMAIL, _RECIPIENT_TYPE = 0x0C1A, 0x0C1E, 0x0C1F, 0x0C15
_SUBMIT_TIME, _DELIVERY_TIME, _BODY, _BODY_HTML = 0x0039, 0x0E06, 0x1000, 0x1013
_MESSAGE_ID, _REFERENCES, _IN_REPLY_TO = 0x1035, 0x1039, 0x1042
_DISPLAY_NAME, _ADDRTYPE, _EMAIL_ADDRESS, _SMTP_ADDRESS = 0x3001, 0x3002, 0x3003, 0x39FE
_SENDER_SMTP, _SENT_REPRESENTING_SMTP = 0x5D01, 0x5D02
_ATTACH_DATA, _ATTACH_FILENAME, _ATTACH_METHOD, _ATTACH_LONG_FILENAME = 0x3701, 0x3704, 0x3705, 0x3707
_ATTACH_MIME_TAG, _ATTACH_CONTENT_ID, _ATTACHMENT_HIDDEN = 0x370E, 0x3712, 0x7FFE
_INTERNET_CPID, _MESSAGE_CODEPAGE = 0x3FDE, 0x3FFD
_FIXED = frozenset(
    {_SUBMIT_TIME, _DELIVERY_TIME, _RECIPIENT_TYPE, _ATTACH_METHOD, _ATTACHMENT_HIDDEN, _INTERNET_CPID}
    | {_MESSAGE_CODEPAGE}
)
_BY_VALUE, _ATTACHED_EMAIL = 1, 5
_TO, _CC = 1, 2
_CODE_PAGES = {
    65001: "utf-8",
    20127: "ascii",
    1200: "utf-16-le",
    20866: "koi8-r",
    21866: "koi8-u",
    50220: "iso2022-jp",
    50221: "iso2022-jp",
    50222: "iso2022-jp",
    51932: "euc-jp",
} | {28590 + n: f"iso8859-{n}" for n in range(1, 16)}
_ADDRESS = re.compile(r"[^\s@<>()\[\],;:\"\\]+@[^\s@<>()\[\],;:\"\\]+")
_TOKEN = re.compile(r"[a-z0-9!#$&^_.+-]{1,100}")
_CONTENT_ID = re.compile(r"[!-;=?-~]{1,200}")  # printable ASCII without spaces and angle brackets
_ATTACHMENT_TYPES = frozenset({"application", "image", "audio", "video", "font", "model"})


def is_ole(data: bytes) -> bool:
    """Whether ``data`` is an OLE compound file (an Outlook ``.msg``, or an older Office file)."""
    return data[:8] == OLE_MAGIC


def as_email(data: bytes, filename: str) -> tuple[bytes, str]:
    """``(data, filename)`` unchanged unless ``data`` is an OLE compound file; an Outlook e-mail becomes its
    ``.eml`` copy named like the file (``C:\\Mail\\Rechnung.msg`` → ``Rechnung.eml``). Raises
    :class:`~ordnung.ingest.intake.IntakeError` for any other OLE file, with the reason."""
    if not is_ole(data):
        return data, filename
    name = PurePosixPath(filename.replace("\\", "/")).name.strip()
    stem = name[: -len(".msg")] if name.lower().endswith(".msg") else PurePosixPath(name).stem
    return msg_to_eml(data), f"{stem.strip() or 'e-mail'}.eml"


def msg_to_eml(data: bytes) -> bytes:
    """The ``.eml`` copy of an Outlook e-mail (see the module docstring); raises
    :class:`~ordnung.ingest.intake.IntakeError` with the reason for anything else."""
    check_size(data)  # empty, or larger than 50 MB: intake's own words
    if not is_ole(data):
        raise IntakeError(DAMAGED)
    try:
        ole = _open(data)
    except IntakeError:
        raise
    except Exception:  # olefile's errors (OSError, OleFileError, struct.error …), RecursionError
        raise IntakeError(DAMAGED) from None
    try:
        eml = _convert(ole, data)
    except IntakeError:
        raise
    except Exception:  # a defect found while reading, a tree too deep for the parser
        raise IntakeError(DAMAGED) from None
    finally:
        ole.close()
    if len(eml) > MAX_BYTES:
        raise IntakeError(TOO_LARGE)
    return eml


# --------------------------------------------------------------------------------------------------
# Reading the compound file
# --------------------------------------------------------------------------------------------------


@functools.cache
def _ole_class() -> Any:
    """olefile's reader with two changes: it counts the directory before building it (a 50 MB file could
    hold 400,000 entries), and it finds an entry by its path in a dictionary (olefile scans every entry of
    each storage on the way, which is quadratic for a file with many entries)."""
    import olefile

    class BoundedOleFile(olefile.OleFileIO):  # type: ignore[misc]
        _paths: dict[tuple[str, ...], int] | None = None

        def _load_direntry(self, sid: int) -> Any:
            if len(self.direntries) > MAX_ENTRIES:
                raise IntakeError(DAMAGED)
            return super()._load_direntry(sid)

        def _find(self, filename: str | Sequence[str]) -> int:
            if self._paths is None:
                self._paths = _index(self.root)
            parts = filename.split("/") if isinstance(filename, str) else filename
            try:
                return self._paths[tuple(part.lower() for part in parts)]
            except KeyError:
                raise OSError("file not found") from None

    return BoundedOleFile


def _open(data: bytes) -> Any:
    import olefile

    # always a file object: olefile would take bytes shorter than 1,536 for the name of a file to open
    return _ole_class()(io.BytesIO(data), raise_defects=olefile.DEFECT_INCORRECT)


def _index(root: Any) -> dict[tuple[str, ...], int]:
    """Every entry's directory number by its path (lower-cased, as olefile compares names)."""
    found: dict[tuple[str, ...], int] = {}
    stack: list[tuple[tuple[str, ...], Any]] = [((), root)]
    while stack:
        path, node = stack.pop()
        for kid in node.kids:
            kid_path = (*path, str(kid.name).lower())
            found.setdefault(kid_path, int(kid.sid))
            stack.append((kid_path, kid))
    return found


class _Reader:
    """The open file's tree (names upper-cased) and its streams, read within the budget."""

    def __init__(self, ole: Any, size: int) -> None:
        self._ole = ole
        self._largest = size
        self._budget = READ_BUDGET_FACTOR * size
        self._kids: dict[tuple[str, ...], list[str]] = {}
        for path in ole.listdir(streams=True, storages=True):
            names = tuple(str(name).upper() for name in path)
            self._kids.setdefault(names[:-1], []).append(names[-1])
        for kids in self._kids.values():
            kids.sort()

    def kids(self, path: tuple[str, ...]) -> list[str]:
        return self._kids.get(path, [])

    def read(self, path: tuple[str, ...]) -> bytes:
        size = int(self._ole.get_size(list(path)))
        if size > self._largest or size > self._budget:
            raise IntakeError(DAMAGED)
        self._budget -= size
        return bytes(self._ole.openstream(list(path)).read())


class _Props:
    """The properties of a message, a recipient or an attachment: the fixed-length ones from its property
    stream (after a header of ``header`` bytes), the others from streams of their own."""

    def __init__(
        self, reader: _Reader, path: tuple[str, ...], header: int, codepage: int | None = None
    ) -> None:
        self.reader, self.path = reader, path
        self.ordered = reader.kids(path)
        self.names = frozenset(self.ordered)
        self._fixed: dict[int, tuple[int, bytes]] = {}
        if _PROPERTIES in self.names:
            raw = reader.read((*path, _PROPERTIES))
            usable = max(0, (len(raw) - header) // 16 * 16)
            for tag, _flags, value in struct.iter_unpack("<II8s", raw[header : header + usable]):
                if tag >> 16 in _FIXED:
                    self._fixed.setdefault(tag >> 16, (tag & 0xFFFF, value))
        self.codepage = codepage or self.long(_MESSAGE_CODEPAGE) or self.long(_INTERNET_CPID)

    def _value(self, prop: int, ptype: int) -> bytes | None:
        found = self._fixed.get(prop)
        return found[1] if found and found[0] == ptype else None

    def long(self, prop: int) -> int | None:
        value = self._value(prop, _PT_LONG)
        return int(struct.unpack_from("<I", value)[0]) if value else None

    def boolean(self, prop: int) -> bool:
        value = self._value(prop, _PT_BOOLEAN)
        return bool(value and value[:2] != b"\0\0")

    def time(self, prop: int) -> datetime | None:
        value = self._value(prop, _PT_SYSTIME)
        if not value:
            return None
        ticks = int(struct.unpack_from("<Q", value)[0])  # 100 ns since 1601
        try:
            return datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=ticks // 10)
        except OverflowError:
            return None

    def text(self, prop: int) -> str | None:
        unicode, string8 = (
            f"__SUBSTG1.0_{prop:04X}{_PT_UNICODE:04X}",
            f"__SUBSTG1.0_{prop:04X}{_PT_STRING8:04X}",
        )
        if unicode in self.names:
            raw = self.reader.read((*self.path, unicode))
            return raw.decode("utf-16-le", "replace").split("\0", 1)[0]
        if string8 in self.names:
            raw = self.reader.read((*self.path, string8))
            return raw.decode(_codec(self.codepage), "replace").split("\0", 1)[0]
        return None

    def binary(self, prop: int) -> bytes | None:
        name = f"__SUBSTG1.0_{prop:04X}{_PT_BINARY:04X}"
        return self.reader.read((*self.path, name)) if name in self.names else None


def _codec(codepage: int | None) -> str:
    """The Python codec of a Windows code page (Windows-1252 when there is none or it is unknown)."""
    name = _CODE_PAGES.get(codepage, f"cp{codepage}") if codepage else "cp1252"
    try:
        return codecs.lookup(name).name
    except LookupError:
        return "cp1252"


# --------------------------------------------------------------------------------------------------
# The e-mail
# --------------------------------------------------------------------------------------------------


def _convert(ole: Any, data: bytes) -> bytes:
    if len(ole.direntries) > MAX_ENTRIES:
        raise IntakeError(DAMAGED)
    reader = _Reader(ole, len(data))
    top = frozenset(reader.kids(()))
    if _PROPERTIES not in top:
        raise IntakeError(OFFICE_FILE if top & _OFFICE_STREAMS else NOT_OUTLOOK)
    message = _Props(reader, (), header=32)
    message_class = (message.text(_MESSAGE_CLASS) or "").strip().upper()
    if not message_class:
        raise IntakeError(DAMAGED)
    if message_class != "IPM.NOTE" and not message_class.startswith("IPM.NOTE."):
        raise IntakeError(NOT_AN_EMAIL)
    if "SMIME" in message_class:
        raise IntakeError(ENCRYPTED)

    root = EmailMessage(policy=_POLICY)
    values = _headers(reader, message) | _transport_headers(message)
    for name in SAFE_HEADERS:
        if value := values.get(name):
            _set_header(root, name, value)
    body, html = message.text(_BODY), _html(message)
    if body and body.strip():
        root.set_content(body, subtype="plain", charset="utf-8", cte="quoted-printable")
        if html and html.strip():
            root.add_alternative(html, subtype="html", charset="utf-8", cte="quoted-printable")
    elif html and html.strip():
        root.set_content(html, subtype="html", charset="utf-8", cte="quoted-printable")
    storages = [name for name in message.ordered if name.startswith(_ATTACHMENT)]
    if storages:
        root.make_mixed()
        for number, name in enumerate(storages, start=1):
            # (a MIMEPart, which typeshed's attach() doesn't take from an EmailMessage)
            root.attach(cast(EmailMessage, _attachment(message, name, number)))
    if "MIME-Version" not in root:
        root["MIME-Version"] = "1.0"
    digest = hashlib.sha256(data).hexdigest()[:24]
    for number, part in enumerate(part for part in root.walk() if part.is_multipart()):
        part.set_boundary(f"=_ordnung_{digest}_{number}")
    return root.as_bytes(policy=_POLICY)


def _headers(reader: _Reader, message: _Props) -> dict[str, str]:
    """The headers from the message's properties."""
    to: list[str] = []
    cc: list[str] = []
    for name in [name for name in message.ordered if name.startswith(_RECIPIENT)][:MAX_RECIPIENTS]:
        recipient = _Props(reader, (*message.path, name), header=8, codepage=message.codepage)
        kind = (recipient.long(_RECIPIENT_TYPE) or _TO) & 0x0FFFFFFF  # without the "submitted" flags
        address = recipient.text(_SMTP_ADDRESS)
        if not address and (recipient.text(_ADDRTYPE) or "").strip().upper() == "SMTP":
            address = recipient.text(_EMAIL_ADDRESS)
        shown = _mailbox(recipient.text(_DISPLAY_NAME), address)
        if shown and kind in (_TO, _CC):  # Bcc stays out, as in an e-mail received
            (to if kind == _TO else cc).append(shown)
    sender = message.text(_SENDER_SMTP) or message.text(_SENT_REPRESENTING_SMTP)
    if not sender and (message.text(_SENDER_ADDRTYPE) or "").strip().upper() == "SMTP":
        sender = message.text(_SENDER_EMAIL)
    moment = message.time(_SUBMIT_TIME) or message.time(_DELIVERY_TIME)
    found = {
        "From": _mailbox(message.text(_SENDER_NAME) or message.text(_SENT_REPRESENTING_NAME), sender),
        "To": ", ".join(to),
        "Cc": ", ".join(cc),
        "Date": format_datetime(moment) if moment else None,
        "Subject": _clean(message.text(_SUBJECT) or ""),
        "Message-ID": _clean(message.text(_MESSAGE_ID) or ""),
        "In-Reply-To": _clean(message.text(_IN_REPLY_TO) or ""),
        "References": _clean(message.text(_REFERENCES) or ""),
    }
    return {name: value for name, value in found.items() if value}


def _transport_headers(message: _Props) -> dict[str, str]:
    """The safe headers' values from Outlook's copy of the original internet headers."""
    raw = message.text(_TRANSPORT_HEADERS)
    if not raw:
        return {}
    parser = email.parser.Parser(policy=email.policy.compat32)
    original = parser.parsestr(raw[:MAX_TRANSPORT_HEADERS], headersonly=True)
    kept: dict[str, str] = {}
    for name in SAFE_HEADERS:
        value = original.get(name)
        if value is not None and (text := _clean(str(value))):
            kept[name] = text
    return kept


def _set_header(root: EmailMessage, name: str, value: str) -> None:
    """Set a header, leaving it out when the header parser can't take or write the value."""
    try:
        root[name] = value
        _POLICY.fold_binary(name, root[name])
    except Exception:
        del root[name]


def _html(message: _Props) -> str | None:
    """The HTML text: bytes in the message's internet code page (else UTF-8, else Windows-1252), or a string."""
    raw = message.binary(_BODY_HTML)
    if raw is None:
        return message.text(_BODY_HTML)
    codepage = message.long(_INTERNET_CPID)
    if codepage:
        text = raw.decode(_codec(codepage), "replace")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", "replace")
    return text.split("\0", 1)[0]


def _clean(value: str, limit: int = MAX_HEADER_CHARS) -> str:
    """A header value: control and formatting characters become spaces, runs of space one, at most ``limit``."""
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in value[: 4 * limit]).split())
    return text[:limit].rstrip()


def _mailbox(name: str | None, address: str | None) -> str | None:
    """``Name <address>`` (quoted and encoded as needed); ``Name <>`` without a usable address."""
    shown = _clean(name or "", MAX_NAME_CHARS)
    found = _address(address)
    if not shown and not found:
        return None
    return formataddr((shown, found or ""))


def _address(value: str | None) -> str | None:
    """An e-mail address (ASCII, one ``@``, nothing that would end it), or ``None``: an Exchange X.500 name
    is no address."""
    text = _clean(value or "", MAX_ADDRESS_CHARS + 1)
    if len(text) > MAX_ADDRESS_CHARS or not text.isascii() or not _ADDRESS.fullmatch(text):
        return None
    return text


def _attachment(message: _Props, storage: str, number: int) -> MIMEPart:
    item = _Props(message.reader, (*message.path, storage), header=8, codepage=message.codepage)
    name = _file_name(item)
    method = item.long(_ATTACH_METHOD)
    if method is None:
        method = _ATTACHED_EMAIL if _OBJECT in item.names else _BY_VALUE
    part = MIMEPart(policy=_POLICY)
    if method == _ATTACHED_EMAIL:  # listed, never opened
        shown = name or f"attachment-{number}"
        filename = shown if shown.lower().endswith(".msg") else f"{shown}.msg"
        part.set_content(b"", "application", "vnd.ms-outlook", disposition="attachment", filename=filename)
        return part
    data = item.binary(_ATTACH_DATA) if method == _BY_VALUE and number <= MAX_WITH_BYTES else None
    maintype, subtype = _content_type(item.text(_ATTACH_MIME_TAG))
    content_id = _content_id(item.text(_ATTACH_CONTENT_ID))
    part.set_content(
        data or b"",
        maintype,
        subtype,
        disposition="inline" if content_id or item.boolean(_ATTACHMENT_HIDDEN) else "attachment",
        filename=name or f"attachment-{number}",
        cid=f"<{content_id}>" if content_id else None,
    )
    return part


def _file_name(item: _Props) -> str:
    raw = item.text(_ATTACH_LONG_FILENAME) or item.text(_ATTACH_FILENAME) or item.text(_DISPLAY_NAME) or ""
    return _clean(PurePosixPath(raw.replace("\\", "/")).name, MAX_NAME_CHARS)


def _content_type(declared: str | None) -> tuple[str, str]:
    """The declared type when it is a file's (never a text, an e-mail or a multipart), else octet-stream."""
    maintype, _, subtype = _clean(declared or "").split(";", 1)[0].strip().lower().partition("/")
    if maintype in _ATTACHMENT_TYPES and _TOKEN.fullmatch(subtype):
        return maintype, subtype
    return "application", "octet-stream"


def _content_id(value: str | None) -> str | None:
    text = (value or "").strip().strip("<>").strip()
    return text if _CONTENT_ID.fullmatch(text) else None
