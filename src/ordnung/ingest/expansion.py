"""Decompression-bomb checks for uploaded PDFs (SPEC §21: untrusted input must not exhaust the machine).

A PDF of a few hundred kilobytes can hold streams that expand to gigabytes; PDFium (rendering) and
pdfminer (text) decode them in memory. :func:`check_pdf_expansion` measures, before anything else
reads the file, what every stream expands to — without keeping the output, and stopping as soon as a
limit is passed — and rejects the PDF when

* one stream expands beyond :data:`MAX_STREAM_BYTES` (images included: a 600 dpi A4 colour scan is
  about 105 MB),
* the streams other than images (page content, fonts, object streams) together expand beyond
  :data:`MAX_CONTENT_BYTES`, or
* an image declares more than :data:`MAX_IMAGE_PIXELS` pixels, or
* measuring would read far more than the file holds (streams crafted never to end).

Streams are found in the raw bytes (``stream`` keyword, dictionary in front of it), which also covers
object and cross-reference streams. The expanding filters Flate, LZW and RunLength — also chained, or
behind ASCII85/ASCIIHex — are measured; each filter ends at its own end-of-data marker, so no
``/Length`` has to be trusted. Image codecs (DCT, JPX, JBIG2, CCITT) are bounded by the pixel check.

Encrypted PDFs that open without a password (banks and insurers often send edit-protected ones) are
decrypted by PDFium before it decodes them, so their streams are measured both as stored and as
pdfminer's security handler decrypts them with the empty password. Decryption runs up to the next
``endstream`` and then in growing windows while the filters want more, so ``endstream`` isn't trusted
either. pdfminer goes first because PDFium, when it loads a PDF, already unpacks the object stream that
holds the catalog. A PDF that PDFium would decrypt in a way pdfminer can't reproduce is rejected.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
import zlib
from collections.abc import Callable, Iterable, Iterator
from typing import Protocol

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from pdfminer.arcfour import Arcfour
from pdfminer.pdfdocument import PDFDocument, PDFStandardSecurityHandler, PDFStandardSecurityHandlerV4
from pdfminer.pdfparser import PDFParser, PDFSyntaxError

from ordnung.ingest.text import PDFIUM_LOCK

MAX_STREAM_BYTES = 256 * 1024 * 1024
MAX_CONTENT_BYTES = 256 * 1024 * 1024
MAX_IMAGE_PIXELS = 150_000_000

_STREAM_RE = re.compile(rb"(?<![A-Za-z])stream(?:\r\n|\n|\r)")
_OBJECT_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
# the /Encrypt key, also with letters written as #xx escapes (PDF 7.3.5). PDFium finds it only in a
# trailer or a cross-reference stream's dictionary, and neither is ever compressed or encrypted.
_ENCRYPT_RE = re.compile(rb"/(?:E|#45)(?:n|#6[Ee])(?:c|#63)(?:r|#72)(?:y|#79)(?:p|#70)(?:t|#74)")
_FILTER_RE = re.compile(rb"/Filter\s*(\[[^\]]*\]|/[^\s/\[\]<>()%]+)")
_NAME_RE = re.compile(rb"/([^\s/\[\]<>()%]+)")
_IMAGE_RE = re.compile(rb"/Subtype\s*/Image\b")
_SIZE_RE = re.compile(rb"/(Width|Height)\s+(\d+)\b(?!\s+\d+\s+R)")
_EARLY_CHANGE_RE = re.compile(rb"/EarlyChange\s+0\b")
_DICT_WINDOW = 64 * 1024
_READ_CHUNK = 16 * 1024
_READ_SLACK = 64 * 1024 * 1024  # bytes measuring may read beyond four times the file size
_OUT_CHUNK = 1024 * 1024
_WINDOW_SLACK = 64  # bytes decrypted past ``endstream``: room for an end of line and an AES block
_RC4_PIECE = 4096  # one call of pdfminer's RC4 slows down with the square of its length
_MAX_LOOKUPS = 1000  # pdfminer object lookups while it reads the trailer (a handful in real PDFs)

_FLATE = frozenset({b"FlateDecode", b"Fl"})
_LZW = frozenset({b"LZWDecode", b"LZW"})
_RUN_LENGTH = frozenset({b"RunLengthDecode", b"RL"})
_ASCII85 = frozenset({b"ASCII85Decode", b"A85"})
_ASCII_HEX = frozenset({b"ASCIIHexDecode", b"AHx"})
_CRYPT = b"Crypt"  # decryption by the security handler (Identity: the data as stored); both are measured

_TOO_LARGE = (
    "This PDF expands to far more data than a letter needs, so it isn't processed "
    "(it may be a decompression bomb). If it is a genuine letter, print it to a new PDF "
    "or take photos of it."
)
_UNCHECKABLE = (
    "This PDF is protected in a way that can't be checked safely, so it isn't processed. "
    "If it is a genuine letter, print it to a new PDF or take photos of it."
)

_Decrypt = Callable[[int, int, bytes], bytes]
"""Decrypts the start of a stream's data, given its object and generation numbers."""


class ExpansionError(ValueError):
    """The PDF expands beyond the limits; the message is written for the person who uploaded it."""


class _Stage(Protocol):
    @property
    def finished(self) -> bool: ...

    def feed(self, chunk: bytes) -> Iterator[bytes]: ...


class _Inflate:
    """FlateDecode, fed in pieces; output in chunks of at most :data:`_OUT_CHUNK` bytes."""

    def __init__(self) -> None:
        self._inflater = zlib.decompressobj()

    @property
    def finished(self) -> bool:
        return self._inflater.eof

    def feed(self, chunk: bytes) -> Iterator[bytes]:
        data = chunk
        while data and not self._inflater.eof:
            yield self._inflater.decompress(data, _OUT_CHUNK)
            data = self._inflater.unconsumed_tail


class _RunLength:
    """RunLengthDecode (PDF 7.4.5): a length byte, then literal bytes or one repeated byte; 128 ends."""

    def __init__(self) -> None:
        self.finished = False
        self._pending = b""

    def feed(self, chunk: bytes) -> Iterator[bytes]:
        data, index, out = self._pending + chunk, 0, bytearray()
        while index < len(data) and not self.finished:
            length = data[index]
            if length == 128:
                self.finished = True
            elif length < 128:
                if index + length + 2 > len(data):
                    break
                out += data[index + 1 : index + length + 2]
                index += length + 2
                continue
            elif index + 1 < len(data):
                out += data[index + 1 : index + 2] * (257 - length)
                index += 2
            else:
                break
            if len(out) >= _OUT_CHUNK:
                yield bytes(out)
                out.clear()
        self._pending = data[index:]
        if out:
            yield bytes(out)


class _Lzw:
    """LZWDecode (PDF 7.4.4): 9–12 bit codes, 256 clears the table, 257 ends the data."""

    def __init__(self, early_change: int = 1) -> None:
        self.finished = False
        self._early = early_change
        self._buffer = 0
        self._bits = 0
        self._reset()

    def _reset(self) -> None:
        self._table: list[bytes] = [bytes([value]) for value in range(256)] + [b"", b""]
        self._width = 9
        self._previous: bytes | None = None

    def feed(self, chunk: bytes) -> Iterator[bytes]:
        out = bytearray()
        for byte in chunk:
            self._buffer = (self._buffer << 8) | byte
            self._bits += 8
            while self._bits >= self._width and not self.finished:
                self._bits -= self._width
                code = self._buffer >> self._bits
                self._buffer &= (1 << self._bits) - 1
                out += self._code(code)
            if self.finished:
                break
            if len(out) >= _OUT_CHUNK:
                yield bytes(out)
                out.clear()
        if out:
            yield bytes(out)

    def _code(self, code: int) -> bytes:
        if code == 256:
            self._reset()
            return b""
        if code == 257:
            self.finished = True
            return b""
        previous = self._previous
        if code < len(self._table):
            entry = self._table[code]
        elif previous is not None:
            entry = previous + previous[:1]  # the code being defined right now (KwKwK)
        else:
            self.finished = True  # damaged data: decoders stop here
            return b""
        if previous is not None and len(self._table) < 4096:
            self._table.append(previous + entry[:1])
        self._previous = entry
        if len(self._table) + self._early >= 1 << self._width and self._width < 12:
            self._width += 1
        return entry


def _filters(header: bytes) -> list[bytes]:
    found = _FILTER_RE.search(header)
    names = _NAME_RE.findall(found.group(1)) if found else []
    return [name for name in names if name != _CRYPT]


def _header(data: bytes, start: int) -> tuple[tuple[int, int] | None, bytes]:
    """The stream's object and generation numbers (None if no ``N G obj`` is found) and its
    dictionary: the bytes between its ``N G obj`` and the ``stream`` keyword."""
    window = data[max(0, start - _DICT_WINDOW) : start]
    found = list(_OBJECT_RE.finditer(window))
    if not found:
        return None, window
    return (int(found[-1][1]), int(found[-1][2])), window[found[-1].end() :]


def _pre_decoded(data: bytes, start: int, name: bytes) -> tuple[bytes | None, bool]:
    """ASCII85/ASCIIHex data from ``start`` to its end marker, decoded (it only shrinks), and whether
    the marker was found."""
    end_marker = b"~>" if name in _ASCII85 else b">"
    end = data.find(end_marker, start)
    raw = data[start : end if end != -1 else len(data)]
    try:
        if name in _ASCII85:
            return base64.a85decode(raw.strip().removeprefix(b"<~")), end != -1
        digits = re.sub(rb"\s", b"", raw)
        return binascii.unhexlify(digits + b"0" * (len(digits) % 2)), end != -1
    except ValueError:
        return None, end != -1


def _stages(filters: list[bytes], header: bytes) -> list[_Stage]:
    stages: list[_Stage] = []
    for name in filters:
        if name in _FLATE:
            stages.append(_Inflate())
        elif name in _LZW:
            stages.append(_Lzw(0 if _EARLY_CHANGE_RE.search(header) else 1))
        elif name in _RUN_LENGTH:
            stages.append(_RunLength())
        else:
            break  # an image codec, or a filter that doesn't expand: the pixel check bounds it
    return stages


def _fed(stage: _Stage, pieces: Iterable[bytes]) -> Iterator[bytes]:
    for piece in pieces:
        yield from stage.feed(piece)


def _through(stages: list[_Stage], chunk: bytes) -> Iterator[bytes]:
    pieces: Iterable[bytes] = [chunk]
    for stage in stages:
        pieces = _fed(stage, pieces)
    return iter(pieces)


def expanded_size(
    data: bytes, start: int, filters: list[bytes], header: bytes = b"", limit: int = 0
) -> tuple[int, int]:
    """``(expanded, read)``: bytes the stream whose data begins at ``start`` expands to through its
    filters — counted without keeping them, and only until ``limit`` (if given) is passed — and how
    many input bytes that took. Damaged data counts as far as it can be decoded (readers stop there)."""
    expanded, read, _ = _measured(data, start, filters, header, limit)
    return expanded, read


def _measured(
    data: bytes, start: int, filters: list[bytes], header: bytes, limit: int
) -> tuple[int, int, bool]:
    """:func:`expanded_size`, and whether the data ran out before the filters reached their end."""
    source = data
    names = list(filters)
    bounded = False  # the data ends at an ASCII85/ASCIIHex end marker
    if names and (names[0] in _ASCII85 or names[0] in _ASCII_HEX):
        decoded, bounded = _pre_decoded(data, start, names.pop(0))
        if decoded is None:
            return 0, 0, not bounded
        source, start = decoded, 0
    stages = _stages(names, header)
    if not stages:
        return 0, 0, False
    total = 0
    position = start
    view = memoryview(source)
    try:
        while position < len(source) and not stages[0].finished:
            chunk = bytes(view[position : position + _READ_CHUNK])
            position += _READ_CHUNK
            for piece in _through(stages, chunk):
                total += len(piece)
                if limit and total > limit:
                    return total, position - start, False
    except zlib.error:
        return total, min(position, len(source)) - start, False
    return total, min(position, len(source)) - start, not stages[0].finished and not bounded


def _decrypted_size(
    decrypt: _Decrypt,
    ref: tuple[int, int],
    data: bytes,
    start: int,
    filters: list[bytes],
    header: bytes,
    limit: int,
) -> tuple[int, int]:
    """:func:`expanded_size` of the stream of object ``ref`` as ``decrypt`` decrypts it: up to the next
    ``endstream`` first, then in windows that double while its filters want more data."""
    end = data.find(b"endstream", start)
    window = (end - start if end != -1 else len(data)) + _WINDOW_SLACK
    objid, genno = ref[0] & 0xFFFFFF, ref[1] & 0xFFFF  # the bytes the object's key is made from
    while True:
        stop = min(len(data), start + window)
        expanded, read, more = _measured(decrypt(objid, genno, data[start:stop]), 0, filters, header, limit)
        if not more or stop == len(data):
            return expanded, read
        window *= 2


class _Document(PDFDocument):
    """pdfminer's document, giving up after :data:`_MAX_LOOKUPS` object lookups: resolving a
    reference to itself (``5 0 obj 5 0 R endobj``) would loop forever."""

    lookups = 0

    def getobj(self, objid: int) -> object:
        self.lookups += 1
        if self.lookups > _MAX_LOOKUPS:
            raise PDFSyntaxError("Too many object lookups")
        return super().getobj(objid)


def _security_handler(data: bytes) -> PDFStandardSecurityHandler | None:
    """pdfminer's security handler for the empty user password; None when the PDF isn't encrypted,
    needs a password or can't be read."""
    try:
        document = _Document(PDFParser(io.BytesIO(data)))
    except Exception:  # damaged, or protected in a way pdfminer doesn't support: PDFium is asked next
        return None
    handler = getattr(document.decipher, "__self__", None)
    return handler if isinstance(handler, PDFStandardSecurityHandler) else None


def _stream_decrypter(handler: PDFStandardSecurityHandler) -> _Decrypt:
    """How ``handler`` decrypts streams: pdfminer's own decryption for AES and Identity. RC4 uses the
    same key and pdfminer's cipher fed in pieces, since one call slows down with the square of its
    length (a 1 MB stream would take half a minute)."""
    if isinstance(handler, PDFStandardSecurityHandlerV4):
        method = handler.cfm[handler.stmf]
    else:
        method = handler.decrypt_rc4
    if method != handler.decrypt_rc4:
        return method
    file_key = handler.key or b""

    def decrypt(objid: int, genno: int, data: bytes) -> bytes:
        salted = file_key + objid.to_bytes(3, "little") + genno.to_bytes(2, "little")  # PDF 7.6.2
        cipher = Arcfour(hashlib.md5(salted, usedforsecurity=False).digest()[: min(len(salted), 16)])
        return b"".join(cipher.process(data[at : at + _RC4_PIECE]) for at in range(0, len(data), _RC4_PIECE))

    return decrypt


def _pdfium_revision(data: bytes) -> int:
    """The revision of the security handler PDFium decrypts the PDF with: -1 when it isn't encrypted,
    or when PDFium can't open it (it needs a password or is damaged; intake says so next)."""
    with PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError:
            return -1
        try:
            return int(pdfium_c.FPDF_GetSecurityHandlerRevision(pdf.raw))
        finally:
            pdf.close()


def _pixels(header: bytes) -> int:
    sizes = {key: int(value) for key, value in _SIZE_RE.findall(header)}
    width = sizes.get(b"Width", sizes.get(b"W", 0))
    height = sizes.get(b"Height", sizes.get(b"H", 0))
    return width * height


def check_pdf_expansion(data: bytes) -> None:
    """Raise :class:`ExpansionError` if the PDF's streams expand beyond the module's limits."""
    if not _ENCRYPT_RE.search(data):
        _check_streams(data, None)
        return
    handler = _security_handler(data)
    _check_streams(data, _stream_decrypter(handler) if handler else None)
    revision = _pdfium_revision(data)
    if revision != -1 and (handler is None or handler.r != revision):
        raise ExpansionError(_UNCHECKABLE)


def _check_streams(data: bytes, decrypt: _Decrypt | None) -> None:
    """Measure every stream as stored and, with ``decrypt``, also decrypted; the larger size counts."""
    content = 0
    resume = 0
    budget = 4 * len(data) + _READ_SLACK
    for match in _STREAM_RE.finditer(data):
        if match.start() < resume:
            continue  # inside the previous stream's data
        ref, header = _header(data, match.start())
        image = bool(_IMAGE_RE.search(header))
        if image and _pixels(header) > MAX_IMAGE_PIXELS:
            raise ExpansionError("This PDF contains an image that is too large to process safely.")
        remaining = MAX_STREAM_BYTES if image else min(MAX_STREAM_BYTES, MAX_CONTENT_BYTES - content)
        filters = _filters(header)
        size, read = expanded_size(data, match.end(), filters, header, limit=remaining)
        if decrypt is not None and ref is not None and size <= remaining:
            decrypted, decrypted_read = _decrypted_size(
                decrypt, ref, data, match.end(), filters, header, remaining
            )
            size, read = max(size, decrypted), read + decrypted_read
        budget -= read
        if size > remaining or budget < 0:
            raise ExpansionError(_TOO_LARGE)
        if not image:
            content += size
        end = data.find(b"endstream", match.end())
        resume = end if end != -1 else len(data)
