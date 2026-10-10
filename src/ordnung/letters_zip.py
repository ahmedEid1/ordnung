"""Export letters: the letters' original files as one ZIP, made as it is sent (``GET /api/documents.zip``).

The policy:

* **Which letters.** Every letter that isn't in the trash, waiting for the person (held) or a proof file —
  private letters too, as they are the person's own files — narrowed by the :class:`Choice`: a year by
  the letter's day (:func:`ordnung.secretary.triggers.letter_day`: the date printed on it, else the day it
  arrived; undated letters belong to no year), ``until`` a day of the next year (the yearly statements that
  come early in it), only letters for taxes, one sender. The web app's export dialog counts the same way
  (``web/src/features/export/selection.ts``; both test suites read ``selection-cases.json``).
* **Names.** A file is ``<year>/<sender>/<date> <title>.<ext>`` (``Undated`` and ``Sender unknown`` when
  either isn't known), ``index.csv`` sits at the root. Every part comes from :func:`safe_component`, so a
  name a letter brought in never leaves its folder, works on Windows, macOS and Linux, and is unique in its
  folder whatever the case. The extension follows the file's real type, and the bytes are the original's:
  nothing is converted.
* **Only files inside the data folder.** An original that is missing, or a link out of the data folder, is
  never followed: ``index.csv`` lists the letter with an empty ``file`` and :data:`MISSING_NOTE`.
* **index.csv** opens in a German spreadsheet: UTF-8 with a BOM, semicolons, CRLF. A cell that would start
  a formula gets a leading ``'`` (:func:`csv_cell`) — titles and sender names come from letters.
* **Streaming.** :class:`LettersZip` yields the archive a chunk at a time (one chunk of a file in memory),
  with ZIP64 records where the sizes need them. A file that can't be read halfway stops the archive
  before its central directory, so a cut download never opens as complete.
* **It only reads.** Nothing is written anywhere — the person's browser saves the ZIP. The ZIP is not
  encrypted; the web app says so before the download.
"""

from __future__ import annotations

import csv
import io
import re
import stat
import unicodedata
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from ordnung.db.store import Store
from ordnung.ingest.held import is_held
from ordnung.ingest.intake import TEXT_TYPES, download_name, strip_control
from ordnung.models import PROOF_SOURCE, Document
from ordnung.secretary.triggers import letter_day, parse_day

SENDER_CHARS, SENDER_BYTES = 60, 80  # a sender's folder
STEM_CHARS, STEM_BYTES = 90, 150  # "<date> <title>", before a " (2)" and the extension
CHUNK = 1 << 20
INDEX_NAME = "index.csv"
INDEX_COLUMNS = (
    "file",
    "letter_date",
    "arrived",
    "sender",
    "title",
    "kind",
    "for_taxes",
    "tax_note",
    "direction",
    "private",
    "pages",
    "original_name",
    "ordnung_id",
    "note",
)
MISSING_NOTE = "The file is missing from Ordnung's data folder."
UNDATED = "Undated"
SENDER_UNKNOWN = "Sender unknown"
DIRECTIONS = {"incoming": "received", "outgoing": "sent", "note": "note"}
#: what a spreadsheet would read as the start of a formula (OWASP's list)
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")
#: owner-only, as the data folder keeps its files
FILE_ATTRIBUTES = (stat.S_IFREG | 0o600) << 16

_FORBIDDEN = re.compile(r'[<>:"/\\|?*]')
_WHITESPACE = re.compile(r"\s")
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,8}")
_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
)
_FIRST_DAY, _LAST_DAY = date(1980, 1, 1), date(2107, 12, 31)  # what a ZIP's timestamps can hold


@dataclass(frozen=True, slots=True)
class Choice:
    """Which letters go into the ZIP (see the module policy); the defaults: every letter."""

    year: int | None = None
    until: date | None = None
    tax: bool = False
    party_id: str | None = None


@dataclass(frozen=True, slots=True)
class Entry:
    """One letter of the export: its sender's name (``None``: unknown), its path inside the ZIP and its
    original (both ``None``: the file is missing, or outside the data folder)."""

    doc: Document
    sender: str | None
    name: str | None
    path: Path | None


# --------------------------------------------------------------------------------------------------
# which letters
# --------------------------------------------------------------------------------------------------


def exportable(doc: Document) -> bool:
    """Whether ``doc`` can be exported at all: not in the trash, not waiting for the person, not a proof."""
    return doc.deleted_at is None and not is_held(doc) and doc.source != PROOF_SOURCE


def matches(doc: Document, choice: Choice) -> bool:
    """Whether ``doc`` belongs in the export ``choice`` describes."""
    if not exportable(doc):
        return False
    if choice.tax and not doc.tax_relevant:
        return False
    if choice.party_id is not None and doc.party_id != choice.party_id:
        return False
    if choice.year is None:
        return True
    day = letter_day(doc)
    if day is None:
        return False
    if day.year == choice.year:
        return True
    return choice.until is not None and day.year == choice.year + 1 and day <= choice.until


def select_documents(docs: Iterable[Document], choice: Choice) -> list[Document]:
    """The letters of ``docs`` that ``choice`` takes, in their order."""
    return [doc for doc in docs if matches(doc, choice)]


def zip_name(choice: Choice, today: date) -> str:
    """``ordnung-letters[-for-taxes][-<year>|-<today>].zip``."""
    taxes = "-for-taxes" if choice.tax else ""
    when = str(choice.year) if choice.year is not None else today.isoformat()
    return f"ordnung-letters{taxes}-{when}.zip"


# --------------------------------------------------------------------------------------------------
# names
# --------------------------------------------------------------------------------------------------


def safe_component(text: str, fallback: str, *, chars: int, max_bytes: int) -> str:
    """``text`` as one file or folder name that is safe everywhere: no control characters or bidirectional
    overrides, NFC, no ``<>:"/\\|?*``, single spaces, no leading or trailing spaces or dots, at most
    ``chars`` characters and ``max_bytes`` UTF-8 bytes, never empty, ``.`` or ``..`` (``fallback``
    instead), and a Windows device name (``CON``, ``LPT1.txt`` …) gets a leading ``_``."""
    name = strip_control(_WHITESPACE.sub(" ", text))
    name = _FORBIDDEN.sub("-", unicodedata.normalize("NFC", name))
    name = " ".join(name.split()).strip(" .")
    name = name[:chars].encode("utf-8")[:max_bytes].decode("utf-8", "ignore").strip(" .")
    if name in ("", ".", ".."):
        name = fallback
    if name.split(".", 1)[0].strip().upper() in _DEVICES:
        name = f"_{name}"
    return name


def _extension(doc: Document, path: Path) -> str:
    """The extension of the file's real type (``.pdf``, ``.jpg`` …), else the original's own if it is a
    plain one."""
    known = PurePosixPath(download_name("letter", doc.mime)).suffix
    if known:
        return known
    return path.suffix if _EXTENSION.fullmatch(path.suffix) else ""


def _sender_folder(sender: str | None) -> str:
    if not sender:
        return SENDER_UNKNOWN
    return safe_component(sender, SENDER_UNKNOWN, chars=SENDER_CHARS, max_bytes=SENDER_BYTES)


def _stem(doc: Document, day: date | None) -> str:
    title = doc.title or PurePosixPath(doc.filename).stem or "Letter"
    text = f"{day.isoformat()} {title}" if day is not None else title
    return safe_component(text, "Letter", chars=STEM_CHARS, max_bytes=STEM_BYTES)


def _original(store: Store, doc: Document, root: Path) -> Path | None:
    """The letter's original if it is a file inside the data folder (a link out of it is never followed)."""
    path = store.get_document_file(doc.id)
    if path is None:
        return None
    try:
        resolved = path.resolve()
        inside = resolved.is_relative_to(root) and resolved.is_file()
    except (OSError, RuntimeError):  # a loop of links
        return None
    return resolved if inside else None


def plan(store: Store, choice: Choice) -> list[Entry]:
    """Every letter of the export with its name in the ZIP, worked out before any byte is sent: ordered by
    year, sender and day, so the same letters always give the same archive."""
    docs = select_documents(store.list_documents(exclude_source=PROOF_SOURCE), choice)
    senders = {party.id: party.name for party in store.list_parties()}
    root = store.data_dir.resolve()

    def sender_of(doc: Document) -> str | None:
        return senders.get(doc.party_id) if doc.party_id else None

    def order(doc: Document) -> tuple[int, int, str, date, str, str]:
        day = letter_day(doc)
        return (
            day is None,
            day.year if day is not None else 0,
            _sender_folder(sender_of(doc)).casefold(),
            day or date.min,
            doc.created_at,
            doc.id,
        )

    folders: dict[str, str] = {}  # casefolded "year/sender" → the spelling it was first given
    taken: set[str] = set()  # casefolded paths in the ZIP
    entries: list[Entry] = []
    for doc in sorted(docs, key=order):
        sender = sender_of(doc)
        path = _original(store, doc, root)
        name: str | None = None
        if path is not None:
            day = letter_day(doc)
            folder = f"{day.year if day is not None else UNDATED}/{_sender_folder(sender)}"
            folder = folders.setdefault(folder.casefold(), folder)
            stem, extension = _stem(doc, day), _extension(doc, path)
            name, copy = f"{folder}/{stem}{extension}", 1
            while name.casefold() in taken:
                copy += 1
                name = f"{folder}/{stem} ({copy}){extension}"
            taken.add(name.casefold())
        entries.append(Entry(doc=doc, sender=sender, name=name, path=path))
    return entries


# --------------------------------------------------------------------------------------------------
# index.csv
# --------------------------------------------------------------------------------------------------


def csv_cell(value: object) -> str:
    """``value`` as a spreadsheet cell that is never a formula: a leading ``'`` where it would start one."""
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(FORMULA_STARTS) else text


def _yes(flag: bool) -> str:
    return "yes" if flag else "no"


def _row(entry: Entry, written: bool) -> list[str]:
    doc = entry.doc
    values: tuple[object, ...] = (
        entry.name if written else "",
        doc.doc_date,
        doc.received_date,
        entry.sender,
        doc.title,
        (doc.kind or "").replace("_", " "),
        _yes(doc.tax_relevant),
        doc.tax_note,
        DIRECTIONS.get(doc.direction, doc.direction),
        _yes(doc.ai_private),
        doc.pages,
        doc.filename,
        doc.id,
        "" if written else MISSING_NOTE,
    )
    return [csv_cell(value) for value in values]


def _index(rows: Sequence[Sequence[str]]) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.writer(text, delimiter=";", lineterminator="\r\n")
    writer.writerow(INDEX_COLUMNS)
    writer.writerows(rows)
    return text.getvalue().encode("utf-8-sig")


# --------------------------------------------------------------------------------------------------
# the archive
# --------------------------------------------------------------------------------------------------


class _Drain(io.RawIOBase):
    """Where the ZIP's bytes collect between two steps of :class:`LettersZip` (unseekable: zipfile writes
    each file's sizes after its data)."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        chunk = bytes(data)
        self._parts.append(chunk)
        return len(chunk)

    def take(self) -> bytes:
        taken, self._parts = b"".join(self._parts), []
        return taken


def _stamp(day: date | None) -> tuple[int, int, int, int, int, int]:
    """A ZIP timestamp: noon of ``day`` (1980-01-01 to 2107-12-31, what a ZIP can hold)."""
    day = min(max(day or _FIRST_DAY, _FIRST_DAY), _LAST_DAY)
    return (day.year, day.month, day.day, 12, 0, 0)


def _info(name: str, day: date | None, *, compress: int, size: int = 0) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=_stamp(day))
    info.create_system = 3  # Unix, on every system: the same bytes, and the mode below is read
    info.external_attr = FILE_ATTRIBUTES
    info.compress_type = compress
    info.file_size = size  # a file past the ZIP64 limit gets its records from the start
    return info


def _open(path: Path) -> tuple[BinaryIO, int] | None:
    """The original opened for reading, with its size (``None``: it went away since the plan)."""
    try:
        source = path.open("rb")
    except OSError:
        return None
    try:
        return source, path.stat().st_size
    except OSError:
        source.close()
        return None


class LettersZip:
    """The ZIP of :func:`plan`'s entries as an iterable of byte chunks (see the module policy).

    Pull-based: a web response sends each chunk as it is made, and a client that goes away closes the
    generator (every file it opened is closed).
    """

    def __init__(self, entries: Sequence[Entry], *, chunk: int = CHUNK) -> None:
        self.entries = list(entries)
        self.chunk = chunk

    def __iter__(self) -> Iterator[bytes]:
        drain = _Drain()
        rows: list[list[str]] = []
        newest: date | None = None
        with zipfile.ZipFile(drain, "w") as archive:
            for entry in self.entries:
                opened = _open(entry.path) if entry.name is not None and entry.path is not None else None
                if opened is not None and entry.name is not None:
                    source, size = opened
                    day = letter_day(entry.doc) or parse_day(entry.doc.created_at)
                    compress = zipfile.ZIP_DEFLATED if entry.doc.mime in TEXT_TYPES else zipfile.ZIP_STORED
                    with (
                        source,
                        archive.open(_info(entry.name, day, compress=compress, size=size), "w") as out,
                    ):
                        while block := source.read(self.chunk):
                            out.write(block)
                            if sent := drain.take():
                                yield sent
                    if day is not None and (newest is None or day > newest):
                        newest = day  # index.csv carries the newest letter's day
                rows.append(_row(entry, written=opened is not None))
            archive.writestr(_info(INDEX_NAME, newest, compress=zipfile.ZIP_DEFLATED), _index(rows))
        yield drain.take()  # index.csv and the central directory
