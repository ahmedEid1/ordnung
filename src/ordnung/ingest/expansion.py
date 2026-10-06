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

Streams are found the way PDFium reads them. After every ``N G obj`` — also one inside another object's
bytes, where a cross-reference table may point — the dictionary is lexed as PDF syntax (strings,
comments, ``#xx`` escapes in names, nesting, any length up to :data:`_MAX_DICTIONARY`), and a ``stream``
keyword after it starts the data; an indirect ``/Filter`` is looked up. For damaged files the
``stream`` keyword with the dictionary in front of it counts too (up to :data:`_MAX_LOOSE_STREAMS`
of them without any ``N G obj`` in front). The expanding filters Flate, LZW (with either
``/EarlyChange``) and RunLength — also chained, or behind ASCII85/ASCIIHex — are measured; each filter
ends at its own end-of-data marker, so no ``/Length`` or ``endstream`` has to be trusted. A filter chain
counts up to its first other filter, so chains that differ only after it are measured once. Image codecs
(DCT, JPX, JBIG2, CCITT) are bounded by the pixel check. A PDF whose structure can't be read within
those bounds is rejected.

Encrypted PDFs that open without a password (banks and insurers often send edit-protected ones) are
decrypted by PDFium before it decodes them, so their streams are measured both as stored and as
pdfminer's security handler decrypts them with the empty password (RC4 with
:func:`ordnung.ingest.text.rc4`, in linear time). A stream is decrypted with each number its object may
have, once for all its filter chains: first a piece (a wrong key's data fails the filters within it),
then up to the next ``endstream``, then in growing windows while the filters want more. The bytes
decrypted count against the same budget as the bytes read. pdfminer goes first because PDFium, when it
loads a PDF, already unpacks the object stream that holds the catalog. A PDF that PDFium would decrypt
in a way pdfminer can't reproduce is rejected.
"""

from __future__ import annotations

import base64
import binascii
import bisect
import functools
import hashlib
import io
import re
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import NamedTuple, Protocol

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from pdfminer.pdfdocument import PDFDocument, PDFStandardSecurityHandler, PDFStandardSecurityHandlerV4
from pdfminer.pdfparser import PDFParser, PDFSyntaxError

from ordnung.ingest.text import PDFIUM_LOCK, rc4

MAX_STREAM_BYTES = 256 * 1024 * 1024
MAX_CONTENT_BYTES = 256 * 1024 * 1024
MAX_IMAGE_PIXELS = 150_000_000

# the patterns that scan the whole file start with a literal (the regex engine then skips ahead fast)
_STREAM_RE = re.compile(rb"stream(?<![A-Za-z]stream)(?:\r\n|\n|\r)")
# ``N G obj`` as a whole word, searched in the reversed bytes
_REVERSED_OBJECT_RE = re.compile(
    rb"jbo(?<![^\x00\t\n\x0c\r ()<>\[\]{}/%]jbo)[\x00\t\n\x0c\r ]+(\d+)[\x00\t\n\x0c\r ]+(\d+)(?![0-9])"
)
# the /Encrypt key, also with letters written as #xx escapes (PDF 7.3.5). PDFium finds it only in a
# trailer or a cross-reference stream's dictionary, and neither is ever compressed or encrypted.
_ENCRYPT_RE = re.compile(rb"/(?:E|#45)(?:n|#6[Ee])(?:c|#63)(?:r|#72)(?:y|#79)(?:p|#70)(?:t|#74)")
_FILTER_RE = re.compile(rb"/Filter\s*(\[[^\]]*\]|/[^\s/\[\]<>()%]+)")
_NAME_RE = re.compile(rb"/([^\s/\[\]<>()%]+)")
_IMAGE_RE = re.compile(rb"/Subtype\s*/Image\b")
_SIZE_RE = re.compile(rb"/(Width|Height)\s+(\d+)\b(?!\s+\d+\s+R)")
_ESCAPE_RE = re.compile(rb"#([0-9A-Fa-f]{2})")
_SPACE_RE = re.compile(rb"(?:[\x00\t\n\x0c\r ]+|%[^\r\n]*)*")  # whitespace and comments
_REGULAR_RE = re.compile(rb"[^\x00\t\n\x0c\r ()<>\[\]{}/%]*")
_STRING_RE = re.compile(rb"[()\\]")
_INTEGER_RE = re.compile(rb"[+-]?\d+")
_LINE_END_RE = re.compile(rb"\r\n|\n|\r")
_DICT_WINDOW = 64 * 1024
_MAX_DICTIONARY = 8 * 1024 * 1024  # a stream's dictionary is a few hundred bytes in a real PDF
_MAX_DEPTH = 64
_MAX_OBJECTS = 200_000  # objects outside object streams (a letter of 60 pages has a few thousand)
_MAX_LOOSE_STREAMS = 4096  # ``stream`` keywords with no ``N G obj`` in the window in front of them
_LEX_SLACK = 1024 * 1024  # bytes lexing may read beyond twice the file size
_MAX_NUMBER_DIGITS = 10
_READ_CHUNK = 16 * 1024
_READ_SLACK = 64 * 1024 * 1024  # bytes measuring may read and decrypt beyond four times the file size
_OUT_CHUNK = 1024 * 1024
_WINDOW_SLACK = 64  # bytes decrypted past ``endstream``: room for an end of line and an AES block
_PROBE = 1024  # bytes of a stream decrypted first: a wrong key's data fails its filters within them
_MAX_LOOKUPS = 1000  # pdfminer object lookups while it reads the trailer (a handful in real PDFs)

_FLATE = frozenset({b"FlateDecode", b"Fl"})
_LZW = frozenset({b"LZWDecode", b"LZW"})
_RUN_LENGTH = frozenset({b"RunLengthDecode", b"RL"})
_ASCII85 = frozenset({b"ASCII85Decode", b"A85"})
_ASCII_HEX = frozenset({b"ASCIIHexDecode", b"AHx"})
_EXPANDING = _FLATE | _LZW | _RUN_LENGTH
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
_UNREADABLE = (
    "This PDF is built in a way that can't be checked safely, so it isn't processed. "
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


# --------------------------------------------------------------------------------------------------
# Finding the streams
# --------------------------------------------------------------------------------------------------


class _Name(bytes):
    """A PDF name, its ``#xx`` escapes decoded."""


class _Ref(NamedTuple):
    number: int
    generation: int


class _Unreadable(Exception):
    """The structure can't be read within the bounds: more than :data:`_MAX_OBJECTS` objects, a
    dictionary longer than :data:`_MAX_DICTIONARY` or nested deeper than :data:`_MAX_DEPTH`, lexing far
    more than the file holds, or a ``/Filter`` whose object isn't in the file's own bytes."""


class _Lexer:
    """Reads PDF objects as PDFium does, leniently: a stray token where a key or a value belongs is
    skipped. Strings and keywords other than references come back as ``None``."""

    def __init__(self, data: bytes, at: int) -> None:
        self.data = data
        self.at = at
        self.stop = min(len(data), at + _MAX_DICTIONARY)

    def skip_space(self) -> None:
        found = _SPACE_RE.match(self.data, self.at, self.stop)
        self.at = found.end() if found else self.at

    def word(self) -> bytes:
        found = _REGULAR_RE.match(self.data, self.at, self.stop)
        word = found.group() if found else b""
        self.at += len(word)
        return word

    def _at_end(self) -> bool:
        """At the lexing limit: past the dictionary limit (raises), or at the end of the file."""
        if self.at < self.stop:
            return False
        if self.stop < len(self.data):
            raise _Unreadable
        return True

    def value(self, depth: int = 0) -> object:
        if depth > _MAX_DEPTH:
            raise _Unreadable
        self.skip_space()
        if self._at_end() or self.data.startswith(b">>", self.at):
            return None
        char = self.data[self.at : self.at + 1]
        if self.data.startswith(b"<<", self.at):
            self.at += 2
            return self._dictionary(depth)
        self.at += 1
        if char == b"[":
            return self._array(depth)
        if char == b"(":
            self._string()
            return None
        if char == b"<":
            end = self.data.find(b">", self.at, self.stop)
            self.at = end + 1 if end != -1 else self.stop
            return None
        if char == b"/":
            return _Name(_ESCAPE_RE.sub(lambda escape: bytes([int(escape[1], 16)]), self.word()))
        if char in b")>]{}":
            return None  # a stray delimiter
        self.at -= 1
        word = self.word()
        if not _INTEGER_RE.fullmatch(word):
            return None  # a real number, true, false, null or another keyword
        mark = self.at
        self.skip_space()
        generation = self.word()
        self.skip_space()
        if _INTEGER_RE.fullmatch(generation) and self.word() == b"R":
            return _Ref(_number(word), _number(generation))
        self.at = mark
        return _number(word)

    def _dictionary(self, depth: int) -> dict[bytes, list[object]]:
        """The entries up to ``>>`` (every value of a key that appears more than once)."""
        entries: dict[bytes, list[object]] = {}
        while True:
            self.skip_space()
            if self._at_end():
                return entries
            if self.data.startswith(b">>", self.at):
                self.at += 2
                return entries
            key = self.value(depth + 1)
            if isinstance(key, _Name):
                entries.setdefault(bytes(key), []).append(self.value(depth + 1))

    def _array(self, depth: int) -> list[object]:
        items: list[object] = []
        while True:
            self.skip_space()
            if self._at_end() or self.data.startswith(b">>", self.at):
                return items
            if self.data.startswith(b"]", self.at):
                self.at += 1
                return items
            items.append(self.value(depth + 1))

    def _string(self) -> None:
        """Past a literal string: balanced parentheses, a backslash escapes the next character."""
        depth = 1
        while depth:
            found = _STRING_RE.search(self.data, self.at, self.stop)
            if found is None:
                self.at = self.stop
                self._at_end()
                return
            self.at = found.end() + (found.group() == b"\\")
            depth += {b"(": 1, b")": -1}.get(found.group(), 0)


_Definitions = dict[tuple[int, int], list[int]]
"""Where each object's value starts, by ``(number, generation)``."""

_Object = tuple[bytes, int, int]
"""An ``N G obj`` in the file: the object number as written, the generation and where ``obj`` ends."""


@dataclass
class _Stream:
    """A stream PDFium may decode: where its data starts, the objects it may belong to (their numbers
    make its key when it is encrypted), the filter chains its dictionary may mean, and its image size."""

    start: int
    refs: set[tuple[int, int]] = field(default_factory=set)
    chains: set[tuple[bytes, ...]] = field(default_factory=set)
    image: bool = False
    pixels: int = 0

    def merge(self, other: _Stream) -> None:
        self.refs |= other.refs
        self.chains |= other.chains
        self.image, self.pixels = self.image or other.image, max(self.pixels, other.pixels)


def _number(digits: bytes) -> int:
    """An integer as written; one of more digits than any real PDF number counts as huge."""
    return int(digits) if len(digits) <= _MAX_NUMBER_DIGITS else 10**18


def _objects(data: bytes) -> Iterator[_Object]:
    """Every ``N G obj`` in the file, the last one first."""
    reversed_data = data[::-1]
    for found in _REVERSED_OBJECT_RE.finditer(reversed_data):
        yield found[2][::-1], _number(found[1][::-1]), len(data) - found.start()


def _numbers(written: bytes) -> set[int]:
    """The object numbers ``written`` may stand for: itself and its shorter endings, since a
    cross-reference table may point at any of its digits ("9912 0 obj" read from its "12")."""
    digits = written[-_MAX_NUMBER_DIGITS:]
    return {int(digits[index:]) for index in range(len(digits))}


def _resolver(definitions: _Definitions, data: bytes) -> Callable[[object], list[object]]:
    """Resolves a value: itself, or for a reference every value its object is defined with in the
    file's own bytes (none for an object inside an object stream). Each object is lexed once."""

    @functools.cache
    def values_of(ref: _Ref) -> tuple[object, ...]:
        return tuple(_Lexer(data, at).value() for at in definitions.get(ref, []))

    return lambda value: list(values_of(value)) if isinstance(value, _Ref) else [value]


def _chains(values: list[object], resolve: Callable[[object], list[object]]) -> set[tuple[bytes, ...]]:
    """The filter chains ``/Filter`` may mean (several when it is given more than once or its object
    is defined more than once). Raises :class:`_Unreadable` for one that can't be looked up."""
    chains: set[tuple[bytes, ...]] = set()
    for value in values:
        resolved = resolve(value)
        if not resolved:
            raise _Unreadable
        for chain in resolved:
            names: list[bytes] = []
            for item in chain if isinstance(chain, list) else [chain]:
                found = resolve(item)
                if not found:
                    raise _Unreadable
                names += [bytes(name) for name in found if isinstance(name, _Name) and name != _CRYPT]
            chains.add(tuple(names))
    return chains


def _integer(values: list[object], resolve: Callable[[object], list[object]]) -> int:
    """The largest integer ``values`` may mean (0 if none)."""
    found = [item for value in values for item in resolve(value)]
    return max((item for item in found if isinstance(item, int)), default=0)


def _lexed_streams(data: bytes, objects: list[_Object]) -> Iterator[_Stream]:
    """The streams after every ``N G obj`` (``objects``) whose dictionary is followed by the ``stream``
    keyword."""
    exact: _Definitions = {}  # an image's size is looked up as written: a near miss would inflate it
    endings: _Definitions = {}  # a filter also where a cross-reference table may point instead
    for written, generation, end in objects:
        exact.setdefault((_number(written), generation), []).append(end)
        for number in _numbers(written):
            endings.setdefault((number, generation), []).append(end)
    as_written, anywhere = _resolver(exact, data), _resolver(endings, data)
    budget = 2 * len(data) + _LEX_SLACK
    for written, generation, end in objects:
        lexer = _Lexer(data, end)
        entries = lexer.value()
        budget -= lexer.at - end
        if budget < 0:
            raise _Unreadable
        if not isinstance(entries, dict):
            continue
        lexer.skip_space()
        if lexer.word() != b"stream":
            continue
        line_end = _LINE_END_RE.search(data, lexer.at, lexer.stop)  # PDFium reads on after that line
        if line_end is None:
            raise _Unreadable
        subtypes = [item for value in entries.get(b"Subtype", []) for item in as_written(value)]
        yield _Stream(
            start=line_end.end(),
            refs={(number, generation) for number in _numbers(written)},
            chains=_chains(entries.get(b"Filter", []), anywhere) or {()},
            image=b"Image" in subtypes,
            pixels=_integer(entries.get(b"Width", []), as_written)
            * _integer(entries.get(b"Height", []), as_written),
        )


def _keyword_streams(data: bytes, objects: list[_Object]) -> Iterator[_Stream]:
    """The streams after every ``stream`` keyword, with the dictionary in the bytes in front of it
    (damaged files whose objects can't be lexed): from the last ``N G obj`` (``objects``) in the
    :data:`_DICT_WINDOW` bytes in front, else all of them. Past :data:`_MAX_LOOSE_STREAMS` keywords with
    no ``N G obj`` there, or once the dictionaries behind an ``N G obj`` add up to far more than the file
    holds (many keywords behind one), the file is :class:`_Unreadable`."""
    headers = sorted(objects, key=lambda found: found[2])
    ends = [end for _, _, end in headers]
    loose = 0
    budget = 2 * len(data) + _LEX_SLACK
    for match in _STREAM_RE.finditer(data):
        before = bisect.bisect_right(ends, match.start()) - 1
        if before >= 0 and ends[before] >= match.start() - _DICT_WINDOW:
            written, generation, end = headers[before]
            header = data[end : match.start()]
            refs = {(number, generation) for number in _numbers(written)}
            budget -= len(header)
        else:
            loose += 1
            header = data[max(0, match.start() - _DICT_WINDOW) : match.start()]
            refs = set()
        if loose > _MAX_LOOSE_STREAMS or budget < 0:
            raise _Unreadable
        header = _ESCAPE_RE.sub(lambda escape: bytes([int(escape[1], 16)]), header)
        filter_list = _FILTER_RE.search(header)
        names = _NAME_RE.findall(filter_list.group(1)) if filter_list else []
        yield _Stream(
            start=match.end(),
            refs=refs,
            chains={tuple(name for name in names if name != _CRYPT)},
            image=bool(_IMAGE_RE.search(header)),
            pixels=_pixels(header),
        )


def _streams(data: bytes) -> list[_Stream]:
    """Every stream, once per place its data starts, with all that lexing and the ``stream`` keywords
    say about it (every filter chain and object it may have, the larger image size)."""
    streams: dict[int, _Stream] = {}
    try:
        objects = list(_objects(data))
        if len(objects) > _MAX_OBJECTS:
            raise _Unreadable
        found = [*_lexed_streams(data, objects), *_keyword_streams(data, objects)]
    except _Unreadable:
        raise ExpansionError(_UNREADABLE) from None
    for stream in found:
        known = streams.setdefault(stream.start, stream)
        if known is not stream:
            known.merge(stream)
    return [streams[start] for start in sorted(streams)]


def _pixels(header: bytes) -> int:
    sizes = {key: _number(value) for key, value in _SIZE_RE.findall(header)}
    width = sizes.get(b"Width", sizes.get(b"W", 0))
    height = sizes.get(b"Height", sizes.get(b"H", 0))
    return width * height


# --------------------------------------------------------------------------------------------------
# Measuring a stream
# --------------------------------------------------------------------------------------------------


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


def _stages(filters: list[bytes], early_change: int) -> list[_Stage]:
    stages: list[_Stage] = []
    for name in filters:
        if name in _FLATE:
            stages.append(_Inflate())
        elif name in _LZW:
            stages.append(_Lzw(early_change))
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
    data: bytes, start: int, filters: list[bytes], limit: int = 0, early_change: int = 1
) -> tuple[int, int]:
    """``(expanded, read)``: bytes the stream whose data begins at ``start`` expands to through its
    filters — counted without keeping them, and only until ``limit`` (if given) is passed — and how
    many input bytes that took. Damaged data counts as far as it can be decoded (readers stop there)."""
    expanded, read, _ = _measured(data, start, filters, limit, early_change)
    return expanded, read


def _measured(
    data: bytes, start: int, filters: list[bytes], limit: int, early_change: int
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
    stages = _stages(names, early_change)
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


def _measured_part(chain: tuple[bytes, ...]) -> tuple[bytes, ...]:
    """The part of a filter chain :func:`_measured` reads: a leading ASCII85 or ASCIIHex filter and the
    expanding filters after it, up to the first other one; empty when it has no expanding filter."""
    first = 1 if chain and (chain[0] in _ASCII85 or chain[0] in _ASCII_HEX) else 0
    end = first
    while end < len(chain) and chain[end] in _EXPANDING:
        end += 1
    return chain[:end] if end > first else ()


class _Decrypted:
    """The data of a stream as ``decrypt`` decrypts it for object ``ref``, from its start: first
    :data:`_PROBE` bytes, then up to the next ``endstream``, then in windows that double. Each window is
    decrypted once, whichever filter chain wants it."""

    def __init__(self, decrypt: _Decrypt, ref: tuple[int, int], data: bytes, start: int) -> None:
        self._decrypt = decrypt
        self._key = ref[0] & 0xFFFFFF, ref[1] & 0xFFFF  # the bytes the object's key is made from
        self._data = data
        self._start = start
        end = data.find(b"endstream", start)
        self._to_endstream = (end if end != -1 else len(data)) - start + _WINDOW_SLACK
        self._window = 0
        self._plain = b""
        self._at_end = False

    def _grow(self) -> int:
        """Decrypt the next window and return its length; 0 when the last one reached the end of the file."""
        if self._at_end:
            return 0
        if self._window:
            self._window = max(self._to_endstream, 2 * self._window)
        else:
            self._window = min(_PROBE, self._to_endstream)
        stop = min(len(self._data), self._start + self._window)
        self._plain = self._decrypt(*self._key, self._data[self._start : stop])
        self._at_end = stop == len(self._data)
        return stop - self._start

    def size(self, filters: list[bytes], limit: int, early_change: int) -> tuple[int, int]:
        """:func:`expanded_size` of the decrypted stream — measured in the largest window decrypted yet,
        then in the next ones while its filters want more data — and the bytes read and decrypted."""
        spent = 0 if self._window else self._grow()
        while True:
            expanded, read, more = _measured(self._plain, 0, filters, limit, early_change)
            spent += read
            grown = self._grow() if more else 0
            if not grown:
                return expanded, spent
            spent += grown


def _stream_size(
    data: bytes, stream: _Stream, decrypt: _Decrypt | None, limit: int, budget: int
) -> tuple[int, int]:
    """The most ``stream`` may expand to — through the measured part of each of its filter chains, LZW
    with either ``/EarlyChange``, as stored and decrypted as each object it may belong to — and the bytes
    read and decrypted for it, stopping once they pass ``budget``."""
    chains = sorted({part for chain in stream.chains if (part := _measured_part(chain))})
    sources: list[_Decrypted | None] = [None]  # as stored, then decrypted as each object
    if decrypt is not None and chains:
        sources += [_Decrypted(decrypt, ref, data, stream.start) for ref in sorted(stream.refs)]
    size = spent = 0
    for source in sources:
        for chain in chains:
            for early_change in (1, 0) if _LZW.intersection(chain) else (1,):
                if source is None:
                    measured, used = expanded_size(data, stream.start, list(chain), limit, early_change)
                else:
                    measured, used = source.size(list(chain), limit, early_change)
                size, spent = max(size, measured), spent + used
                if size > limit or spent > budget:
                    return size, spent
    return size, spent


# --------------------------------------------------------------------------------------------------
# Encrypted PDFs
# --------------------------------------------------------------------------------------------------


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
    same key and :func:`~ordnung.ingest.text.rc4`, since pdfminer's cipher slows down with the square of
    the length (a 1 MB stream took over a minute)."""
    if isinstance(handler, PDFStandardSecurityHandlerV4):
        method = handler.cfm[handler.stmf]
    else:
        method = handler.decrypt_rc4
    if method != handler.decrypt_rc4:
        return method
    file_key = handler.key or b""

    def decrypt(objid: int, genno: int, data: bytes) -> bytes:
        salted = file_key + objid.to_bytes(3, "little") + genno.to_bytes(2, "little")  # PDF 7.6.2
        return rc4(hashlib.md5(salted, usedforsecurity=False).digest()[: min(len(salted), 16)], data)

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


# --------------------------------------------------------------------------------------------------
# The check
# --------------------------------------------------------------------------------------------------


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
    """Measure every stream as stored and, with ``decrypt``, also decrypted; the larger size counts. The
    bytes read and decrypted share one budget."""
    content = 0
    budget = 4 * len(data) + _READ_SLACK
    for stream in _streams(data):
        if stream.image and stream.pixels > MAX_IMAGE_PIXELS:
            raise ExpansionError("This PDF contains an image that is too large to process safely.")
        remaining = MAX_STREAM_BYTES if stream.image else min(MAX_STREAM_BYTES, MAX_CONTENT_BYTES - content)
        size, spent = _stream_size(data, stream, decrypt, remaining, budget)
        budget -= spent
        if size > remaining or budget < 0:
            raise ExpansionError(_TOO_LARGE)
        if not stream.image:
            content += size
