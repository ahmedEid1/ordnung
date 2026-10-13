"""Outlook ``.msg`` files for tests, built here without binary blobs (no tests here): a small writer of OLE
compound files ([MS-CFB] version 3, 512-byte sectors), synthetic messages on it ([MS-OXMSG]), a tiny PDF,
and helpers that damage a file on purpose (a directory entry's size, first sector or links). Everything is
invented test data. ``scripts/make_msg_fixture.py`` builds the e2e fixture with it.

The writer puts streams of 4096 bytes or more in regular sectors right after the header, in directory order
(so a large attachment's first bytes sit in the file's first kilobyte, as in real files), then the mini
stream, the MiniFAT, the directory (one run of sectors) and the FAT. The children of a storage form a
balanced binary tree ordered by name length, then upper-case name, as the format requires.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")
SECTOR = 512
MINI_SECTOR = 64
CUTOFF = 4096
ENTRY = 128
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF
STORAGE, STREAM, ROOT = 1, 2, 5
#: header fields: offset of the first directory sector, of the DIFAT (the FAT sectors' numbers)
HEADER_DIR_START, HEADER_FAT_COUNT, HEADER_DIFAT = 48, 44, 76


# --------------------------------------------------------------------------------------------------
# The compound file writer
# --------------------------------------------------------------------------------------------------


@dataclass
class Node:
    """A stream (``data`` is its bytes) or a storage (``data`` is ``None``, ``kids`` its children)."""

    name: str
    data: bytes | None = None
    kids: list[Node] = field(default_factory=list)

    @property
    def is_storage(self) -> bool:
        return self.data is None


def storage(name: str, *kids: Node) -> Node:
    return Node(name, None, list(kids))


def stream(name: str, data: bytes) -> Node:
    return Node(name, data)


def _key(node: Node) -> tuple[int, str]:
    return (len(node.name), node.name.upper())


def build(kids: Sequence[Node]) -> bytes:
    """An OLE compound file whose root storage holds ``kids``."""
    root = Node("Root Entry", None, list(kids))
    order: list[Node] = []
    stack = [root]
    while stack:  # depth first, children in their order: the directory's entry numbers
        node = stack.pop()
        order.append(node)
        stack.extend(reversed(node.kids))
    sid = {id(node): number for number, node in enumerate(order)}

    starts: dict[int, int] = {}
    mini = bytearray()
    minifat: list[int] = []
    big: list[Node] = []
    for node in order[1:]:
        if node.data is None:
            continue
        if not node.data:
            starts[id(node)] = ENDOFCHAIN
        elif len(node.data) < CUTOFF:
            first, count = len(minifat), -(-len(node.data) // MINI_SECTOR)
            starts[id(node)] = first
            minifat += [first + i + 1 for i in range(count - 1)] + [ENDOFCHAIN]
            mini += node.data.ljust(count * MINI_SECTOR, b"\0")
        else:
            big.append(node)

    sectors: list[bytes] = []
    chains: list[tuple[int, int]] = []

    def put(blob: bytes) -> int:
        start, count = len(sectors), max(1, -(-len(blob) // SECTOR))
        padded = blob.ljust(count * SECTOR, b"\0")
        sectors.extend(padded[i : i + SECTOR] for i in range(0, len(padded), SECTOR))
        chains.append((start, count))
        return start

    for node in big:
        starts[id(node)] = put(node.data or b"")
    mini_start = put(bytes(mini)) if mini else ENDOFCHAIN
    minifat_blob = b""
    if minifat:
        minifat += [FREESECT] * (-len(minifat) % (SECTOR // 4))
        minifat_blob = struct.pack(f"<{len(minifat)}I", *minifat)
    minifat_start = put(minifat_blob) if minifat_blob else ENDOFCHAIN

    links: dict[int, tuple[int, int]] = {}  # left and right sibling of each entry
    child: dict[int, int] = {}

    def tree(nodes: list[Node]) -> int:
        if not nodes:
            return NOSTREAM
        middle = len(nodes) // 2
        links[sid[id(nodes[middle])]] = (tree(nodes[:middle]), tree(nodes[middle + 1 :]))
        return sid[id(nodes[middle])]

    for node in order:
        if node.is_storage:
            child[sid[id(node)]] = tree(sorted(node.kids, key=_key))
    entries = []
    for number, node in enumerate(order):
        left, right = links.get(number, (NOSTREAM, NOSTREAM))
        if number == 0:
            entries.append(_entry(node.name, ROOT, left, right, child[0], mini_start, len(mini)))
        elif node.is_storage:
            entries.append(_entry(node.name, STORAGE, left, right, child[number], 0, 0))
        else:
            data = node.data or b""
            entries.append(_entry(node.name, STREAM, left, right, NOSTREAM, starts[id(node)], len(data)))
    unused = _entry("", 0, NOSTREAM, NOSTREAM, NOSTREAM, 0, 0)
    entries += [unused] * (-len(entries) % (SECTOR // ENTRY))
    dir_start = put(b"".join(entries))

    data_sectors = len(sectors)
    fat_count = 1
    while data_sectors + fat_count > fat_count * (SECTOR // 4):
        fat_count += 1
    assert fat_count <= 109, "too large for a file without DIFAT sectors"
    fat = [FREESECT] * (fat_count * (SECTOR // 4))
    for start, count in chains:
        for i in range(count):
            fat[start + i] = start + i + 1 if i < count - 1 else ENDOFCHAIN
    for i in range(fat_count):
        fat[data_sectors + i] = FATSECT
    fat_blob = struct.pack(f"<{len(fat)}I", *fat)
    sectors.extend(fat_blob[i : i + SECTOR] for i in range(0, len(fat_blob), SECTOR))

    difat = [data_sectors + i for i in range(fat_count)] + [FREESECT] * (109 - fat_count)
    header = (
        MAGIC
        + b"\0" * 16  # CLSID
        + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6)  # minor, major version, byte order, sector shifts
        + b"\0" * 6
        + struct.pack(
            "<IIIIIIIII",
            0,  # directory sectors (always 0 in version 3)
            fat_count,
            dir_start,
            0,  # transaction signature
            CUTOFF,
            minifat_start,
            len(minifat_blob) // SECTOR,
            ENDOFCHAIN,  # no DIFAT sectors
            0,
        )
        + struct.pack("<109I", *difat)
    )
    assert len(header) == SECTOR
    return header + b"".join(sectors)


def _entry(name: str, kind: int, left: int, right: int, child: int, start: int, size: int) -> bytes:
    encoded = name.encode("utf-16-le")
    assert len(encoded) <= 62, name
    return (
        encoded.ljust(64, b"\0")
        + struct.pack("<HBB", len(encoded) + 2 if name else 0, kind, 1)
        + struct.pack("<III", left, right, child)
        + b"\0" * 16  # CLSID
        + struct.pack("<I", 0)  # state bits
        + b"\0" * 16  # creation and modification time
        + struct.pack("<IQ", start, size)
    )


# --------------------------------------------------------------------------------------------------
# Damage on purpose
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    """A directory entry of a file as it is on disk (``offset``: where its 128 bytes start)."""

    sid: int
    offset: int
    name: str
    kind: int
    left: int
    right: int
    child: int
    start: int
    size: int


def directory(data: bytes) -> list[Entry]:
    """Every used directory entry of ``data`` (following the directory's chain through the FAT)."""
    fat_count = struct.unpack_from("<I", data, HEADER_FAT_COUNT)[0]
    fat_sectors = struct.unpack_from(f"<{fat_count}I", data, HEADER_DIFAT)
    fat: list[int] = []
    for number in fat_sectors:
        fat += struct.unpack_from(f"<{SECTOR // 4}I", data, SECTOR + number * SECTOR)
    found: list[Entry] = []
    sector, seen = struct.unpack_from("<I", data, HEADER_DIR_START)[0], 0
    while sector not in (ENDOFCHAIN, FREESECT):
        for slot in range(SECTOR // ENTRY):
            offset = SECTOR + sector * SECTOR + slot * ENTRY
            length, kind = struct.unpack_from("<HB", data, offset + 64)
            left, right, child = struct.unpack_from("<III", data, offset + 68)
            start, size = struct.unpack_from("<IQ", data, offset + 116)
            name = data[offset : offset + max(0, length - 2)].decode("utf-16-le")
            if kind:
                found.append(Entry(seen, offset, name, kind, left, right, child, start, size))
            seen += 1
        sector = fat[sector]
    return found


def entries_named(data: bytes, name: str) -> list[Entry]:
    return [entry for entry in directory(data) if entry.name == name]


def patched(data: bytes, entry: Entry, **fields: int) -> bytes:
    """``data`` with ``entry``'s ``left``, ``right``, ``child``, ``start`` or ``size`` changed."""
    return patched_all(data, [(entry, fields)])


def patched_all(data: bytes, changes: Sequence[tuple[Entry, dict[str, int]]]) -> bytes:
    """:func:`patched` for many entries at once."""
    out = bytearray(data)
    for entry, fields in changes:
        for name, value in fields.items():
            if name in ("left", "right", "child"):
                at = entry.offset + 68 + 4 * ("left", "right", "child").index(name)
                struct.pack_into("<I", out, at, value)
            elif name == "start":
                struct.pack_into("<I", out, entry.offset + 116, value)
            elif name == "size":
                struct.pack_into("<Q", out, entry.offset + 120, value)
            else:
                raise TypeError(name)
    return bytes(out)


# --------------------------------------------------------------------------------------------------
# Outlook messages
# --------------------------------------------------------------------------------------------------

PT_LONG, PT_BOOLEAN, PT_SYSTIME, PT_STRING8, PT_UNICODE, PT_BINARY = 0x3, 0xB, 0x40, 0x1E, 0x1F, 0x102


@dataclass
class Attachment:
    """``method``: 1 by value, 5 an attached e-mail, 6 an OLE object, 2–4 and 7 links (no bytes)."""

    filename: str
    data: bytes = b""
    mime: str | None = None
    method: int | None = 1  # None: no method property at all
    content_id: str | None = None
    hidden: bool = False


@dataclass
class Recipient:
    name: str
    smtp: str | None = None
    kind: int = 1  # 1 To, 2 Cc, 3 Bcc
    exchange: str | None = None  # an Exchange (X.500) address instead of an e-mail address


@dataclass
class Message:
    subject: str = "Ihre Rechnung September 2026"
    sender_name: str | None = "Stadtwerke Musterstadt"
    sender_smtp: str | None = "rechnung@stadtwerke-musterstadt.example"
    sender_exchange: str | None = None  # an X.500 address, Exchange's own (no SMTP address then)
    body: str | None = "Guten Tag,\nanbei Ihre Rechnung für September.\n"
    html: bytes | None = None
    html_cpid: int | None = None  # PR_INTERNET_CPID: the HTML's code page
    html_as_text: str | None = None  # the HTML as a string property (some writers)
    rtf: bytes | None = None
    transport_headers: str | None = None
    message_id: str | None = "<rechnung-2026-09@stadtwerke-musterstadt.example>"
    in_reply_to: str | None = None
    references: str | None = None
    sent: datetime | None = datetime(2026, 9, 27, 16, 2, tzinfo=UTC)
    delivered: datetime | None = None
    message_class: str | None = "IPM.Note"
    recipients: list[Recipient] = field(default_factory=lambda: [Recipient("Sam Rivera", "sam@example.org")])
    attachments: list[Attachment] = field(default_factory=list)
    string8: bool = False  # strings as 8-bit text in ``codepage`` instead of UTF-16
    codepage: int = 1252
    extra: list[Node] = field(default_factory=list)  # more entries at the message's top level


def _filetime(moment: datetime) -> int:
    return int((moment - datetime(1601, 1, 1, tzinfo=UTC)).total_seconds()) * 10_000_000


def _fixed(prop: int, ptype: int, value: int) -> bytes:
    raw = struct.pack("<Q", value) if ptype == PT_SYSTIME else struct.pack("<I", value) + b"\0" * 4
    return struct.pack("<II", (prop << 16) | ptype, 0x6) + raw


def _variable(prop: int, ptype: int, size: int) -> bytes:
    """The fixed-stream entry of a variable-length property (its size), as Outlook writes it."""
    return struct.pack("<IIII", (prop << 16) | ptype, 0x6, size, 0)


class _Props:
    """The streams and the fixed-length property stream of one message, recipient or attachment."""

    def __init__(self, string8: bool = False, codepage: int = 1252) -> None:
        self.nodes: list[Node] = []
        self.fixed = b""
        self.string8, self.codepage = string8, codepage

    def text(self, prop: int, value: str | None, *, unicode: bool | None = None) -> None:
        if value is None:
            return
        if unicode is False or (unicode is None and self.string8):
            data = value.encode(f"cp{self.codepage}", "replace") + b"\0"
            ptype = PT_STRING8
        else:
            data = value.encode("utf-16-le") + b"\0\0"
            ptype = PT_UNICODE
        self.binary(prop, data, ptype)

    def binary(self, prop: int, data: bytes | None, ptype: int = PT_BINARY) -> None:
        if data is None:
            return
        self.nodes.append(stream(f"__substg1.0_{prop:04X}{ptype:04X}", data))
        self.fixed += _variable(prop, ptype, len(data))

    def long(self, prop: int, value: int | None) -> None:
        if value is not None:
            self.fixed += _fixed(prop, PT_LONG, value)

    def boolean(self, prop: int, value: bool) -> None:
        if value:
            self.fixed += _fixed(prop, PT_BOOLEAN, 1)

    def time(self, prop: int, value: datetime | None) -> None:
        if value is not None:
            self.fixed += _fixed(prop, PT_SYSTIME, _filetime(value))

    def finish(self, header: bytes) -> list[Node]:
        return [*self.nodes, stream("__properties_version1.0", header + self.fixed)]


def message_nodes(m: Message, *, embedded: bool = False) -> list[Node]:
    """The entries of a message's storage (the root of a ``.msg`` file, or an attached e-mail's)."""
    props = _Props(m.string8, m.codepage)
    props.text(0x001A, m.message_class)
    props.text(0x0037, m.subject)
    props.text(0x0C1A, m.sender_name)
    props.text(0x0042, m.sender_name)
    if m.sender_smtp:
        props.text(0x5D01, m.sender_smtp)
        props.text(0x0C1E, "SMTP")
        props.text(0x0C1F, m.sender_smtp)
    if m.sender_exchange:
        props.text(0x0C1E, "EX")
        props.text(0x0C1F, m.sender_exchange)
    props.text(0x1000, m.body)
    props.binary(0x1013, m.html)
    props.text(0x1013, m.html_as_text)
    props.binary(0x1009, m.rtf)
    props.text(0x007D, m.transport_headers)
    props.text(0x1035, m.message_id)
    props.text(0x1042, m.in_reply_to)
    props.text(0x1039, m.references)
    props.text(0x0E04, "; ".join(r.name for r in m.recipients if r.kind == 1) or None)
    props.time(0x0039, m.sent)
    props.time(0x0E06, m.delivered)
    props.long(0x3FDE, m.html_cpid)
    if m.string8:
        props.long(0x3FFD, m.codepage)
    counts = struct.pack(
        "<IIII", len(m.recipients), len(m.attachments), len(m.recipients), len(m.attachments)
    )
    header = b"\0" * 8 + counts + (b"" if embedded else b"\0" * 8)
    nodes = [*props.finish(header), storage("__nameid_version1.0"), *m.extra]
    for number, recipient in enumerate(m.recipients):
        nodes.append(storage(f"__recip_version1.0_#{number:08X}", *_recipient_nodes(recipient, m)))
    for number, attachment in enumerate(m.attachments):
        nodes.append(storage(f"__attach_version1.0_#{number:08X}", *_attachment_nodes(attachment)))
    return nodes


def _recipient_nodes(recipient: Recipient, m: Message) -> list[Node]:
    props = _Props(m.string8, m.codepage)
    props.long(0x0C15, recipient.kind)
    props.text(0x3001, recipient.name)
    if recipient.smtp:
        props.text(0x39FE, recipient.smtp)
        props.text(0x3002, "SMTP")
        props.text(0x3003, recipient.smtp)
    if recipient.exchange:
        props.text(0x3002, "EX")
        props.text(0x3003, recipient.exchange)
    return props.finish(b"\0" * 8)


def _attachment_nodes(attachment: Attachment) -> list[Node]:
    props = _Props()
    props.long(0x3705, attachment.method)
    props.boolean(0x7FFE, attachment.hidden)
    props.text(0x3707, attachment.filename)
    props.text(0x3704, attachment.filename[:12])
    props.text(0x3001, attachment.filename)
    props.text(0x370E, attachment.mime)
    props.text(0x3712, attachment.content_id)
    nodes = props.finish(b"\0" * 8)
    if attachment.method == 5:  # the attached e-mail is a storage of its own
        inner = Message(subject="Weitergeleitet", body="Die ursprüngliche Nachricht.\n", attachments=[])
        nodes.append(storage("__substg1.0_3701000D", *message_nodes(inner, embedded=True)))
    elif attachment.method == 6:  # an OLE object: a storage with the object's own streams
        nodes.append(storage("__substg1.0_3701000D", stream("CONTENTS", attachment.data or b"ole")))
    elif attachment.method in (1, None):
        nodes.append(stream("__substg1.0_37010102", attachment.data))
    return nodes


def build_msg(m: Message) -> bytes:
    return build(message_nodes(m))


# --------------------------------------------------------------------------------------------------
# A PDF and a bill
# --------------------------------------------------------------------------------------------------


def simple_pdf(lines: Sequence[str], *, at_least: int = 0) -> bytes:
    """A one-page A4 PDF in Helvetica (Windows-1252 text), padded with comment lines to ``at_least`` bytes."""

    def escaped(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = "BT /F1 11 Tf 72 770 Td 15 TL " + " ".join(f"({escaped(line)}) '" for line in lines) + " ET"
    stream_bytes = content.encode("cp1252")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> "
        b"/Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n" % len(stream_bytes) + stream_bytes + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    while len(out) < at_least - 900:  # comment lines (ignored by readers) put the size where a test needs it
        out += b"% padding: a test needs this file to be large\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


BILL_LINES = (
    "Stadtwerke Musterstadt GmbH - SPECIMEN",
    "Sam Rivera, Musterweg 5, 12345 Musterstadt",
    "Rechnung Nr. 2026-0927 vom 27.09.2026",
    "Strom September 2026: 84,20 EUR",
    "Bitte zahlen Sie bis zum 15.10.2026.",
)


def bill_pdf() -> bytes:
    """A fictional electricity bill, large enough (> 4096 bytes) to sit right after a ``.msg``'s header."""
    return simple_pdf(BILL_LINES, at_least=6000)


def bill(**changes: object) -> Message:
    """The fictional bill e-mail: plain text, a PDF attached (its first bytes in the file's first kilobyte)."""
    message = Message(
        attachments=[Attachment("Rechnung_2026-09.pdf", bill_pdf(), "application/pdf")],
    )
    return replace(message, **changes)  # type: ignore[arg-type]
