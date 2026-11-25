"""Page text for the ingestion pipeline (SPEC §8 stage 2, §21 injection defences).

* **PDF text layers** — pdfplumber characters are assembled into words and lines in their own reading
  direction, with word boxes relative (0..1) to the page image rendered by pypdfium2 (effective
  CropBox and ``/Rotate`` handled). Invisible characters (white, tiny or off-page) are kept out of
  the page text and reported separately as ``hidden_text``. So is text drawn *invisibly* — text render
  mode 3 or 7, which PDFium reports for each character's text object (:func:`_invisible_chars`) — with
  one exception: a page whose invisible text is at least a text layer's worth and no less than its
  visible text is a scan with an OCR layer (a searchable PDF from a scanner or a phone app). Its OCR
  text is somebody's reading of the picture, not the letter's own text: the page counts as having no
  text layer and is read from its image like a photo (so its values are compared with the paper, ADR
  0012), and the OCR text is neither the page text nor reported as hidden: it is returned apart, as
  :attr:`PdfText.scan_text`, for search only (ADR 0020). Text that puts no ink on the page counts as
  hidden too, however it is hidden (covered by a shape or an image, drawn fully transparent, clipped
  away, in an optional layer that is off, black on black …): PDFium renders each page twice, as it is
  and with its text objects removed, and a character whose box is the same in both renders was never
  seen (:func:`_drawn_chars`). Characters PDFium can't be matched to (the same character within a
  fraction of its size) count as visible. The text layer is
  read with a pdfminer document that gives up after :data:`MAX_REFERENCE_LOOKUPS` lookups answering
  with another reference: an object that refers to itself (``5 0 obj 5 0 R endobj``, in the document
  information, a page's contents or resources …) would otherwise be resolved forever. Such a PDF's pages
  are read from their images, like a photo. A PDF protected with RC4 is decrypted with :func:`rc4`,
  which returns what pdfminer's own cipher does in linear time (pdfminer's slows down with the square of
  a stream's length: over a minute for a page of 1.5 MB).
* **Plain-text and e-mail documents** — decoded, laid out on A4 page images with a bundled font, and
  returned with exact word boxes so quotes from them can be highlighted like PDF text. Layout is
  lazy (it stops once a page limit is passed) and wrapping measures at most one row at a time, so
  a huge one-line file costs linear time. Text an HTML e-mail certainly hides from every reader
  (``display:none``, a tiny font, text the colour of its background …) is kept out of the text and
  reported as hidden; the short policy that decides it is in :func:`~ordnung.ingest.email_text.html_to_text`.
* **Prompt helpers** — ``page_delimited`` for the extraction prompt and ``detect_injection_phrases``.
"""

from __future__ import annotations

import codecs
import ctypes
import email
import email.parser
import email.policy
import functools
import hashlib
import itertools
import logging
import re
import struct
import threading
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from io import BufferedReader
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, NamedTuple

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from pdfminer.pdfdocument import PDFDocument, PDFStandardSecurityHandler, PDFStandardSecurityHandlerV4
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfparser import PDFParser, PDFSyntaxError
from pdfminer.pdftypes import PDFObjRef
from pdfplumber.pdf import PDF
from PIL import Image, ImageChops, ImageFont

from ordnung.config import PACKAGE_DIR
from ordnung.ingest.email_text import _email_body
from ordnung.ingest.email_text import email_heading as email_heading
from ordnung.ingest.email_text import html_to_text as html_to_text

if TYPE_CHECKING:
    from pdfplumber.page import Page

    from ordnung.ingest.intake import RenderedPage

log = logging.getLogger(__name__)

PDFIUM_LOCK = threading.Lock()
"""PDFium is not thread-safe: every pypdfium2 call in the app holds this lock (it lives here, the lowest
module that calls PDFium; :mod:`ordnung.ingest.intake` re-exports it)."""

TextSource = Literal["text", "transcript", "none"]
Direction = Literal["ltr", "rtl", "ttb", "btt"]

MIN_TEXT_CHARS = 40  # meaningful (alphanumeric) characters for a page to count as having a text layer
#: The most of a page's scanner text that is kept (:attr:`PdfText.scan_text`); a dense A4 page has about 5,000.
MAX_SCAN_TEXT_CHARS = 20_000
MIN_VISIBLE_FONT_SIZE = 3.0  # points; smaller glyphs are treated as hidden
NEAR_WHITE = 0.95  # every RGB component at or above this is "white"

FONT_PATH = PACKAGE_DIR / "drafts" / "fonts" / "DejaVuSans.ttf"
TEXT_PAGE_SIZE = (1131, 1600)  # A4 portrait with a 1600 px long side
_TEXT_MARGIN = 96
_TEXT_FONT_SIZE = 24
_TEXT_LINE_HEIGHT = 34
_MAX_ROW_CHARS = 400  # no row of a text page is longer (a full row holds ~90 characters)

_LIGATURES = frozenset("ﬀﬁﬂﬃﬄﬅﬆ")
_SOFT_HYPHEN = "­"
_ZERO_WIDTH = str.maketrans("", "", "​‌‍⁠﻿")
_WORD_GAP = 0.15  # gap between glyphs (in font sizes) that starts a new word
_COLUMN_GAP = 1.5  # gap (in font sizes) rendered as a wide separator between words of one line
_LINE_TOLERANCE = 0.4  # max distance of glyph centres (in font sizes) on one line
_PARAGRAPH_GAP = 0.8  # vertical gap (in font sizes) that inserts a blank line


# --------------------------------------------------------------------------------------------------
# Public data types
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Word:
    """A word on a page with its box relative (0..1) to the rendered page image."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    def to_row(self) -> list[str | float]:
        """Compact JSON form stored in ``pages.words``: ``[text, x0, y0, x1, y1]``."""
        return [self.text, round(self.x0, 5), round(self.y0, 5), round(self.x1, 5), round(self.y1, 5)]

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> Word:
        """Inverse of :meth:`to_row`."""
        text, x0, y0, x1, y1 = row
        return cls(str(text), float(x0), float(y0), float(x1), float(y1))


@dataclass(frozen=True, slots=True)
class PageText:
    """The readable text of one page, in reading order, with word boxes."""

    page: int
    text: str
    words: list[Word] = field(default_factory=list)
    hidden_text: str = ""
    has_text_layer: bool = False

    @property
    def source(self) -> TextSource:
        """``text`` when the page text comes from the document itself, else ``none``."""
        return "text" if self.has_text_layer else "none"


class PdfText(NamedTuple):
    """A PDF's page texts and, apart from them, the text a scanner drew invisibly over its picture (page →
    text, at most :data:`MAX_SCAN_TEXT_CHARS` each). The scanner's text is somebody's reading of the
    picture: for search only — never a page's text, never evidence, never in a prompt (ADR 0020)."""

    pages: list[PageText]
    scan_text: dict[int, str]


class TextDocument(NamedTuple):
    """Decoded content of a plain-text or e-mail document."""

    text: str
    hidden_text: str = ""


# --------------------------------------------------------------------------------------------------
# PDF text layer
# --------------------------------------------------------------------------------------------------

Rect = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class _Glyph:
    text: str
    box: Rect  # display box in points, relative to the top-left corner of the visible page area
    frame: Rect  # the same box in the glyph's upright reading frame (u along the text, v across lines)
    direction: Direction

    @property
    def size(self) -> float:
        return self.frame[3] - self.frame[1]

    @property
    def middle(self) -> float:
        return (self.frame[1] + self.frame[3]) / 2

    @property
    def is_space(self) -> bool:
        return self.text.isspace()


@dataclass(frozen=True, slots=True)
class _PageFrame:
    """The visible page area (MediaBox ∩ CropBox, rotated) in pdfplumber's coordinate space."""

    left: float
    top: float
    width: float
    height: float

    @classmethod
    def of(cls, page: Page) -> _PageFrame:
        media = _ordered(page.page_obj.mediabox)
        crop = _intersection(_ordered(page.page_obj.cropbox), media) or media
        rotation = page.page_obj.rotate
        ax, ay = _device_point(crop[0], crop[1], media, rotation)
        bx, by = _device_point(crop[2], crop[3], media, rotation)
        # pdfplumber: x = device x + mediabox x0; top = mediabox top + (mediabox height - device y)
        plumber_x0, plumber_top, _, plumber_bottom = page.mediabox
        frame = cls(
            left=min(ax, bx) + plumber_x0,
            top=plumber_top + (plumber_bottom - plumber_top) - max(ay, by),
            width=abs(bx - ax),
            height=abs(by - ay),
        )
        if frame.width <= 0 or frame.height <= 0:
            raise ValueError("page has an empty visible area")
        return frame

    def place(self, obj: dict[str, Any]) -> Rect:
        """Box of a pdfplumber object relative to the visible area's top-left corner (points)."""
        return (
            float(obj["x0"]) - self.left,
            float(obj["top"]) - self.top,
            float(obj["x1"]) - self.left,
            float(obj["bottom"]) - self.top,
        )

    def contains(self, box: Rect, tolerance: float = 1.0) -> bool:
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        return -tolerance <= cx <= self.width + tolerance and -tolerance <= cy <= self.height + tolerance

    def relative(self, box: Rect) -> Rect:
        return (
            _clamp(box[0] / self.width),
            _clamp(box[1] / self.height),
            _clamp(box[2] / self.width),
            _clamp(box[3] / self.height),
        )


#: Object lookups answering with another reference that a PDF's text layer may take (module docstring).
#: Real PDFs hardly ever store a reference as an object of its own; resolving one to itself never ends.
MAX_REFERENCE_LOOKUPS = 1000


def rc4(key: bytes, data: bytes) -> bytes:
    """``data`` encrypted or decrypted with RC4 under ``key``: byte for byte what pdfminer's ``Arcfour``
    returns, in linear time (``Arcfour`` appends each byte to a new ``bytes``: 74 s for 1 MB)."""
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) & 255
        state[i], state[j] = state[j], state[i]
    keystream = bytearray(len(data))
    i = j = 0
    for at in range(len(data)):
        i = (i + 1) & 255
        x = state[i]
        j = (j + x) & 255
        y = state[j]
        state[i] = y
        state[j] = x
        keystream[at] = state[(x + y) & 255]
    sealed = int.from_bytes(data, "little") ^ int.from_bytes(keystream, "little")
    return sealed.to_bytes(len(data), "little")


class _LinearRC4:
    """pdfminer's RC4 decryption of an object's strings and streams (PDF 7.6.2), with :func:`rc4`."""

    key: bytes | None

    def decrypt_rc4(self, objid: int, genno: int, data: bytes) -> bytes:
        key = (self.key or b"") + struct.pack("<L", objid)[:3] + struct.pack("<L", genno)[:2]
        return rc4(hashlib.md5(key, usedforsecurity=False).digest()[: min(len(key), 16)], data)


class _SecurityHandler(_LinearRC4, PDFStandardSecurityHandler):
    """pdfminer's handler for RC4 (``/V`` 1 and 2)."""


class _SecurityHandlerV4(_LinearRC4, PDFStandardSecurityHandlerV4):
    """pdfminer's handler for crypt filters (``/V`` 4: RC4 or AES-128)."""


class _Document(PDFDocument):
    """pdfminer's document, giving up after :data:`MAX_REFERENCE_LOOKUPS` lookups answering with another
    reference: resolving a reference to itself (``5 0 obj 5 0 R endobj``) would loop forever. RC4 is
    decrypted with :func:`rc4`."""

    security_handler_registry: ClassVar[dict[int, type[PDFStandardSecurityHandler]]] = {
        **PDFDocument.security_handler_registry,
        1: _SecurityHandler,
        2: _SecurityHandler,
        4: _SecurityHandlerV4,
    }
    references = 0

    def getobj(self, objid: int) -> object:
        found = super().getobj(objid)
        if isinstance(found, PDFObjRef):
            self.references += 1
            if self.references > MAX_REFERENCE_LOOKUPS:
                raise PDFSyntaxError("Too many references to references")
        return found


class _PDF(PDF):
    """pdfplumber's PDF over :class:`_Document` (pdfplumber's own constructor makes an unbounded one),
    without the document information, which nothing reads."""

    def __init__(self, stream: BufferedReader, path: Path) -> None:
        self.stream = stream
        self.stream_is_external = False
        self.path = path
        self.pages_to_parse = None
        self.laparams = None
        self.password = ""
        self.unicode_norm = None
        self.raise_unicode_errors = True
        self.doc = _Document(PDFParser(stream))
        self.rsrcmgr = PDFResourceManager()
        self.metadata = {}


def open_pdf(path: Path) -> PDF:
    """The PDF at ``path`` for reading its text layer, on a lookup-bounded document (module docstring)."""
    stream = path.open("rb")
    try:
        return _PDF(stream, path)
    except BaseException:
        stream.close()
        raise


def extract_pdf_pages(pdf_path: Path, rendered: Sequence[RenderedPage]) -> list[PageText]:
    """Text, words and hidden text for every rendered page of a PDF.

    Word boxes are relative to the corresponding page image. A page whose text layer cannot be
    parsed comes back empty (``has_text_layer=False``) so the pipeline transcribes it instead.
    A scanner's text is left out (:func:`read_pdf_text` gives it apart).
    """
    return read_pdf_text(pdf_path, rendered).pages


def read_pdf_text(pdf_path: Path, rendered: Sequence[RenderedPage]) -> PdfText:
    """:func:`extract_pdf_pages`'s pages and, apart from them, the text a scanner drew invisibly over the
    picture of a page that has no text of its own (:class:`PdfText`; search only, ADR 0020)."""
    unread = PdfText([PageText(page=r.page, text="") for r in rendered], {})
    try:
        pdf = open_pdf(pdf_path)
    except Exception:  # damaged text layer: every page falls back to transcription
        log.warning("could not read the text layer of %s", pdf_path, exc_info=True)
        return unread
    try:
        pages = pdf.pages
    except Exception:  # a page tree pdfminer can't follow: every page falls back to transcription
        log.warning("could not read the pages of %s", pdf_path, exc_info=True)
        pdf.stream.close()  # closing the PDF would read its pages again, and fail again
        return unread
    invisible = _drawn_chars(pdf_path, [r.page for r in rendered])
    texts: list[PageText] = []
    scanned: dict[int, str] = {}
    with pdf:
        for r in rendered:
            text, scan = _extract_page_safely(pages[r.page - 1], r.page, invisible.get(r.page))
            texts.append(text)
            if scan:
                scanned[r.page] = scan
    return PdfText(texts, scanned)


class _DrawnChar(NamedTuple):
    """One character as PDFium reads it: its text, the centre of its box (PDF user space), whether its
    text object draws it invisibly (text render mode 3 or 7) and whether it puts ink on the rendered
    page (:func:`_drawn_chars`)."""

    text: str
    x: float
    y: float
    invisible: bool
    inked: bool = True


_INVISIBLE_MODES = frozenset({3, 7})  # FPDF_TEXTRENDERMODE_INVISIBLE, FPDF_TEXTRENDERMODE_CLIP
#: The long side, in pixels, of the two renders that tell inked text from text nobody can see: a glyph
#: of :data:`MIN_VISIBLE_FONT_SIZE` on A4 is still four pixels tall.
INK_RENDER_SIDE = 1200
#: The least difference (0..255, luminance of the per-channel difference) between the two renders
#: that counts as ink: the contrast of :data:`NEAR_WHITE` text on white.
INK_THRESHOLD = 16


def _drawn_chars(pdf_path: Path, numbers: Sequence[int]) -> dict[int, dict[str, list[_DrawnChar]]]:
    """Page number → character → where PDFium draws it, whether invisibly and whether with ink (module
    docstring); a page PDFium can't read is left out (its characters then count as visible, as they
    would on a text layer PDFium can't render either)."""
    with PDFIUM_LOCK:
        return _drawn_chars_locked(pdf_path, numbers)


def _drawn_chars_locked(pdf_path: Path, numbers: Sequence[int]) -> dict[int, dict[str, list[_DrawnChar]]]:
    found: dict[int, dict[str, list[_DrawnChar]]] = {}
    try:
        document = pdfium.PdfDocument(pdf_path)
    except Exception:
        log.warning("could not check %s for invisible text", pdf_path, exc_info=True)
        return found
    try:
        for number in numbers:
            page = document[number - 1]
            try:
                found[number] = _page_chars(page)
            except Exception:
                log.warning(
                    "could not check page %d of %s for invisible text", number, pdf_path, exc_info=True
                )
            finally:
                page.close()
    except Exception:
        log.warning("could not check %s for invisible text", pdf_path, exc_info=True)
    finally:
        document.close()
    return found


def _page_chars(page: pdfium.PdfPage) -> dict[str, list[_DrawnChar]]:
    """Every character of the page, read before its text objects are removed for the second render."""
    width, height = page.get_size()
    scale = INK_RENDER_SIDE / max(width, height, 1.0)
    size = (round(width * scale), round(height * scale))
    placed: list[tuple[_DrawnChar, tuple[int, int, int, int] | None]] = []
    textpage = page.get_textpage()
    try:
        loose = raw.FS_RECTF()
        edges = [ctypes.c_double() for _ in range(4)]
        for index in range(raw.FPDFText_CountChars(textpage.raw)):
            if raw.FPDFText_IsGenerated(textpage.raw, index):
                continue
            text = chr(raw.FPDFText_GetUnicode(textpage.raw, index))
            if text.isspace() or not raw.FPDFText_GetLooseCharBox(textpage.raw, index, ctypes.byref(loose)):
                continue
            obj = raw.FPDFText_GetTextObject(textpage.raw, index)
            hidden = bool(obj) and raw.FPDFTextObj_GetTextRenderMode(obj) in _INVISIBLE_MODES
            drawn = _DrawnChar(text, (loose.left + loose.right) / 2, (loose.top + loose.bottom) / 2, hidden)
            tight = raw.FPDFText_GetCharBox(textpage.raw, index, *(ctypes.byref(edge) for edge in edges))
            placed.append((drawn, _device_box(page, size, [e.value for e in edges]) if tight else None))
    finally:
        textpage.close()
    ink = _ink(page, scale) if placed else None
    chars: dict[str, list[_DrawnChar]] = {}
    for drawn, box in placed:
        inked = ink is None or box is None or ink.crop(box).getbbox() is not None
        chars.setdefault(drawn.text, []).append(drawn._replace(inked=inked))
    return chars


def _device_box(
    page: pdfium.PdfPage, size: tuple[int, int], edges: Sequence[float]
) -> tuple[int, int, int, int]:
    """A character's box (left, right, bottom, top in PDF user space) in render pixels, one pixel wider
    on every side (so a thin glyph keeps at least one pixel)."""
    left, right, bottom, top = edges
    xs: list[int] = []
    ys: list[int] = []
    for x, y in ((left, top), (right, bottom)):
        dx, dy = ctypes.c_int(), ctypes.c_int()
        raw.FPDF_PageToDevice(page.raw, 0, 0, size[0], size[1], 0, x, y, ctypes.byref(dx), ctypes.byref(dy))
        xs.append(dx.value)
        ys.append(dy.value)
    return (min(xs) - 1, min(ys) - 1, max(xs) + 2, max(ys) + 2)


def _ink(page: pdfium.PdfPage, scale: float) -> Image.Image:
    """Where the page's text objects change its render: a mask (255 = ink) of the difference between the
    page rendered as it is and rendered again with every text object removed (in memory only; the file
    is never written). The page is left without its text: the caller closes it."""
    before = _render(page, scale)
    _remove_text(page.raw, raw.FPDFPage_CountObjects, raw.FPDFPage_GetObject, raw.FPDFPage_RemoveObject)
    after = _render(page, scale)
    difference = ImageChops.difference(before, after).convert("L")
    return difference.point(lambda value: 255 if value >= INK_THRESHOLD else 0)


def _render(page: pdfium.PdfPage, scale: float) -> Image.Image:
    bitmap = page.render(scale=scale, may_draw_forms=True)  # as the page images are rendered
    try:
        image: Image.Image = bitmap.to_pil().convert("RGB")
        return image
    finally:
        bitmap.close()


def _remove_text(holder: Any, count: Any, get: Any, remove: Any) -> None:
    """Remove every text object of a page or form XObject (forms in forms included)."""
    for index in reversed(range(count(holder))):
        obj = get(holder, index)
        kind = raw.FPDFPageObj_GetType(obj)
        if kind == raw.FPDF_PAGEOBJ_TEXT:
            if remove(holder, obj):
                raw.FPDFPageObj_Destroy(obj)
        elif kind == raw.FPDF_PAGEOBJ_FORM:
            _remove_text(
                obj, raw.FPDFFormObj_CountObjects, raw.FPDFFormObj_GetObject, raw.FPDFFormObj_RemoveObject
            )


def _near(char: dict[str, Any], drawn: dict[str, list[_DrawnChar]] | None) -> list[_DrawnChar]:
    """PDFium's characters of the same text within a fraction of this pdfplumber character's size."""
    if not drawn:
        return []
    text = str(char.get("text", ""))
    size = float(char.get("size") or 0.0)
    x = (float(char["x0"]) + float(char["x1"])) / 2
    y = (float(char["y0"]) + float(char["y1"])) / 2
    return [
        other
        for other in drawn.get(text, [])
        if abs(other.x - x) <= max(1.0, 0.25 * size) and abs(other.y - y) <= max(1.5, 0.5 * size)
    ]


def _drawn_invisibly(char: dict[str, Any], drawn: dict[str, list[_DrawnChar]] | None) -> bool:
    """Whether PDFium draws this pdfplumber character only invisibly: every character of the same
    text within a fraction of its size of it is invisible (none visible), and there is one."""
    near = _near(char, drawn)
    return bool(near) and all(other.invisible for other in near)


def _drawn_without_ink(char: dict[str, Any], drawn: dict[str, list[_DrawnChar]] | None) -> bool:
    """Whether this pdfplumber character leaves no ink on the rendered page: every PDFium character of
    the same text near it changes nothing in the render, and there is one."""
    near = _near(char, drawn)
    return bool(near) and not any(other.inked for other in near)


def is_near_white(color: object) -> bool:
    """Whether a pdfplumber colour (gray, RGB or CMYK tuple) is white or nearly so."""
    rgb = _rgb(color)
    return rgb is not None and min(rgb) >= NEAR_WHITE


def _extract_page_safely(
    page: Page, number: int, drawn: dict[str, list[_DrawnChar]] | None = None
) -> tuple[PageText, str]:
    try:
        return _extract_page(page, number, drawn)
    except Exception:  # one broken page must not stop ingestion
        log.warning("could not read the text layer of page %d", number, exc_info=True)
        return PageText(page=number, text=""), ""
    finally:
        page.close()


def _extract_page(
    page: Page, number: int, drawn: dict[str, list[_DrawnChar]] | None = None
) -> tuple[PageText, str]:
    """The page's text and its scanner text (``""`` unless the page is a scan with an OCR layer)."""
    frame = _PageFrame.of(page)
    backgrounds = _dark_backgrounds(page, frame)
    visible: list[_Glyph] = []
    hidden: list[_Glyph] = []
    invisible: list[_Glyph] = []
    # Visible text comes from the de-duplicated characters (fake-bold overprints collapse); hidden text
    # from the raw ones — at 1-2 pt, de-duplication would merge real double letters ("Assistant").
    for char in page.dedupe_chars().chars:
        glyph = _glyph(char, frame)
        if glyph is None:
            continue
        if glyph.is_space or not (
            _is_hidden(char, glyph, frame, backgrounds)
            or _drawn_invisibly(char, drawn)
            or _drawn_without_ink(char, drawn)
        ):
            visible.append(glyph)
    for char in page.chars:
        glyph = _glyph(char, frame)
        if glyph is None or glyph.is_space:
            continue
        if _drawn_invisibly(char, drawn):
            invisible.append(glyph)
        elif _is_hidden(char, glyph, frame, backgrounds) or _drawn_without_ink(char, drawn):
            hidden.append(glyph)
    text, words = _assemble(visible, frame)
    meaningful = sum(ch.isalnum() for ch in text)
    unseen = sum(ch.isalnum() for glyph in invisible for ch in glyph.text)
    if unseen >= MIN_TEXT_CHARS and unseen >= meaningful:
        # a scan's OCR layer (module docstring): read from the image, the OCR text kept apart for search
        hidden_text, _ = _assemble(hidden, frame)
        scanned, _ = _assemble(invisible, frame)
        page_text = PageText(page=number, text="", hidden_text=hidden_text, has_text_layer=False)
        return page_text, scanned[:MAX_SCAN_TEXT_CHARS]
    hidden_text, _ = _assemble([*hidden, *invisible], frame)
    page_text = PageText(
        page=number,
        text=text,
        words=words,
        hidden_text=hidden_text,
        has_text_layer=meaningful >= MIN_TEXT_CHARS,
    )
    return page_text, ""


def _glyph(char: dict[str, Any], frame: _PageFrame) -> _Glyph | None:
    text = _clean_char_text(str(char.get("text", "")))
    if not text:
        return None
    box = frame.place(char)
    direction = _direction(char["matrix"])
    return _Glyph(text, box, _reading_frame(box, direction, frame), direction)


def _clean_char_text(text: str) -> str:
    if text.startswith("(cid:"):  # glyph without a Unicode mapping
        return ""
    if any(ch in _LIGATURES for ch in text):
        text = unicodedata.normalize("NFKC", text)
    return text.translate(_ZERO_WIDTH)


def _direction(matrix: Sequence[float]) -> Direction:
    """Reading direction on the rendered page from the glyph's text-space → device matrix."""
    a, b = float(matrix[0]), float(matrix[1])
    if abs(a) >= abs(b):
        return "ltr" if a >= 0 else "rtl"
    return "btt" if b > 0 else "ttb"  # device y points up


def _reading_frame(box: Rect, direction: Direction, frame: _PageFrame) -> Rect:
    """Rotate a display box so text of ``direction`` reads left-to-right, lines top-to-bottom."""
    x0, y0, x1, y1 = box
    if direction == "rtl":
        return (frame.width - x1, frame.height - y1, frame.width - x0, frame.height - y0)
    if direction == "ttb":
        return (y0, frame.width - x1, y1, frame.width - x0)
    if direction == "btt":
        return (frame.height - y1, x0, frame.height - y0, x1)
    return box


def _is_hidden(char: dict[str, Any], glyph: _Glyph, frame: _PageFrame, backgrounds: list[Rect]) -> bool:
    """SPEC §21: tiny, off-page, or white text (unless it sits on a dark filled shape)."""
    if glyph.size < MIN_VISIBLE_FONT_SIZE or not frame.contains(glyph.box):
        return True
    return is_near_white(char.get("non_stroking_color")) and not _inside_any(glyph.box, backgrounds)


def _dark_backgrounds(page: Page, frame: _PageFrame) -> list[Rect]:
    """Filled shapes dark enough for white text on them to be readable."""
    shapes = [*page.rects, *page.curves]
    return [
        frame.place(shape)
        for shape in shapes
        if shape.get("fill") and (rgb := _rgb(shape.get("non_stroking_color"))) and _luminance(rgb) < 0.6
    ]


def _inside_any(box: Rect, areas: Iterable[Rect]) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(a[0] <= cx <= a[2] and a[1] <= cy <= a[3] for a in areas)


def _rgb(color: object) -> tuple[float, float, float] | None:
    """Gray / RGB / CMYK components (0..1) as RGB; ``None`` for patterns or unknown values."""
    if not isinstance(color, tuple | list):
        return None
    try:
        values = [float(v) for v in color]
    except (TypeError, ValueError):
        return None
    if len(values) == 1:
        return (values[0], values[0], values[0])
    if len(values) == 3:
        return (values[0], values[1], values[2])
    if len(values) == 4:
        c, m, y, k = values
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _luminance(rgb: tuple[float, float, float]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


# -- assembling glyphs into lines and words ---------------------------------------------------------


def _assemble(glyphs: list[_Glyph], frame: _PageFrame) -> tuple[str, list[Word]]:
    """Reading-order text and its words; the text is built from exactly these words."""
    blocks: list[str] = []
    words: list[Word] = []
    for group in _by_direction(glyphs):
        lines = _cluster_lines(group)
        rendered_lines: list[str] = []
        for index, line in enumerate(lines):
            line_text, line_words = _render_line(line, frame)
            if not line_text:
                continue
            if rendered_lines and _paragraph_gap(lines[index - 1], line):
                rendered_lines.append("")
            rendered_lines.append(line_text)
            words.extend(line_words)
        if rendered_lines:
            blocks.append("\n".join(rendered_lines))
    return "\n\n".join(blocks), words


def _by_direction(glyphs: list[_Glyph]) -> list[list[_Glyph]]:
    """Glyphs grouped by reading direction, the dominant direction first."""
    groups: dict[Direction, list[_Glyph]] = {}
    for glyph in glyphs:
        groups.setdefault(glyph.direction, []).append(glyph)
    order: tuple[Direction, ...] = ("ltr", "ttb", "btt", "rtl")
    return sorted(groups.values(), key=lambda g: (-len(g), order.index(g[0].direction)))


def _cluster_lines(glyphs: list[_Glyph]) -> list[list[_Glyph]]:
    lines: list[list[_Glyph]] = []
    anchor = size = 0.0
    for glyph in sorted(glyphs, key=lambda g: (g.middle, g.frame[0])):
        if lines and abs(glyph.middle - anchor) <= _LINE_TOLERANCE * max(size, glyph.size):
            lines[-1].append(glyph)
            size = max(size, glyph.size)
        else:
            lines.append([glyph])
            anchor, size = glyph.middle, glyph.size
    return [sorted(line, key=lambda g: g.frame[0]) for line in lines]


def _paragraph_gap(previous: list[_Glyph], line: list[_Glyph]) -> bool:
    size = max(g.size for g in previous)
    gap = min(g.frame[1] for g in line) - max(g.frame[3] for g in previous)
    return gap > _PARAGRAPH_GAP * size


def _split_chunks(line: list[_Glyph]) -> list[tuple[list[_Glyph], bool]]:
    """Group the glyphs of a line into words; the flag marks a wide (column) gap before the word."""
    chunks: list[tuple[list[_Glyph], bool]] = []
    previous: _Glyph | None = None
    after_space = False
    for glyph in line:
        if glyph.is_space:
            after_space = True
            continue
        if previous is None:
            chunks.append(([glyph], False))
        else:
            gap = glyph.frame[0] - previous.frame[2]
            size = max(glyph.size, previous.size)
            if after_space or gap > _WORD_GAP * size:
                chunks.append(([glyph], gap > _COLUMN_GAP * size))
            else:
                chunks[-1][0].append(glyph)
        previous = glyph
        after_space = False
    return chunks


def _render_line(line: list[_Glyph], frame: _PageFrame) -> tuple[str, list[Word]]:
    """The text of one line and its words (split at space glyphs and gaps)."""
    chunks = _split_chunks(line)
    parts: list[str] = []
    words: list[Word] = []
    for index, (glyphs, wide) in enumerate(chunks):
        text = "".join(g.text for g in glyphs)
        if index == len(chunks) - 1 and text.endswith(_SOFT_HYPHEN):
            text = text[:-1] + "-"  # a soft hyphen at the end of a line is a visible hyphenation
        text = text.replace(_SOFT_HYPHEN, "")
        if not text:
            continue
        if parts:
            parts.append("   " if wide else " ")
        parts.append(text)
        box = (
            min(g.box[0] for g in glyphs),
            min(g.box[1] for g in glyphs),
            max(g.box[2] for g in glyphs),
            max(g.box[3] for g in glyphs),
        )
        words.append(Word(text, *frame.relative(box)))
    return "".join(parts), words


# -- geometry helpers --------------------------------------------------------------------------------


def _ordered(box: Sequence[float]) -> Rect:
    x0, y0, x1, y1 = (float(v) for v in box)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _intersection(a: Rect, b: Rect) -> Rect | None:
    box = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return box if box[0] < box[2] and box[1] < box[3] else None


def _device_point(x: float, y: float, media: Rect, rotation: int) -> tuple[float, float]:
    """PDF user space → pdfminer device space (the page CTM pdfminer applies for ``/Rotate``)."""
    mx0, my0, mx1, my1 = media
    if rotation == 90:
        return y - my0, mx1 - x
    if rotation == 180:
        return mx1 - x, my1 - y
    if rotation == 270:
        return my1 - y, x - mx0
    return x - mx0, y - my0


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


# --------------------------------------------------------------------------------------------------
# Prompt-injection phrases
# --------------------------------------------------------------------------------------------------

_END = r"(?![\w-])"
_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # English
        r"\b(?:ignore|disregard|forget|override)\s+(?:(?:all|any|the|your|of|these|those)\s+)*"
        r"(?:(?:previous|prior|above|earlier|preceding|former|existing|other)\s+)?"
        r"(?:instructions?|prompts?|rules|directions|guidelines|directives)" + _END,
        r"\byou\s+are\s+(?:now\s+|actually\s+)?(?:an?\s+|the\s+)?(?:\w+\s+){0,2}?"
        r"(?:ai|artificial\s+intelligence|language\s+model|llm|chatbot|assistant|model|claude|chatgpt)"
        r"(?=\s*(?:[.,;:!]|$|\b(?:that|who|which|and|designed|trained|tasked|reading|processing|with)\b))",
        r"\bas\s+an?\s+(?:ai|artificial\s+intelligence|(?:large\s+)?language\s+model|llm)" + _END,
        r"\bsystem[\s_-]*prompt\b",
        r"\b(?:system|developer)\s+(?:message|instructions?|mode)\b",
        r"\bjailbreak",
        r"\b(?:dear|hello|hi|hey)\s+(?:ai|a\.i\.|assistant|claude|chatgpt|gpt|model|language\s+model|llm|bot)"
        + _END,
        r"\b(?:note|message|instructions?|notice)\s+(?:to|for)\s+(?:the\s+|any\s+|all\s+)?"
        r"(?:ai\s+(?:systems?|assistants?|models?)|ai|a\.i\.|assistants?|language\s+models?|llms?|chatbots?)\b",
        r"\bmark\s+(?:\w+\s+){0,5}?as\s+(?:\w+\s+and\s+)?(?:paid|done|settled|legitimate|legit|genuine|safe|trusted|"
        r"resolved|completed?|verified|not\s+(?:a\s+)?(?:scam|fraud|phishing|spam))\b",
        r"\b(?:new|updated|revised|additional)\s+instructions?\s*:",
        r"\b(?:do\s+not|don't|never)\s+(?:tell|inform|alert|warn|notify)\s+the\s+(?:user|human|owner|recipient)\b",
        r"\b(?:do\s+not|don't|never)\s+(?:flag|classify|report|mark|treat)\s+(?:this|it|the\s+\w+)\s+as\s+"
        r"(?:an?\s+)?(?:scam|fraud|phishing|spam|suspicious)\b",
        r"\b(?:the\s+)?(?:ai|assistant|model|claude)\s+(?:must|should|shall|will)\s+(?:now\s+)?"
        r"(?:ignore|mark|treat|classify|output|respond|reply|say)\b",
        r"<\s*/?\s*(?:untrusted_document|system|instructions?|assistant|user|human)\s*>",
        # a line that speaks as the system/assistant ("SYSTEM: …", "Assistant instruction: …")
        r"(?:^|(?<=[.!?:;]\s)|(?<=\n))\s*(?:system|assistant|ai|ki|claude|chatgpt)"
        r"(?:\s+(?:instruction|instructions|note|message|prompt|override|anweisung|hinweis))?\s*:",
        # German
        r"\b(?:ignoriere|ignorieren\s+sie|ignoriert|vergiss|vergessen\s+sie|missachte|missachten\s+sie)\s+"
        r"(?:(?:alle|sämtliche|die|deine|ihre|eure)\s+)*"
        r"(?:(?:vorherigen|vorigen|bisherigen|obigen|früheren|vorangegangenen|vorstehenden|alten|andere[n]?)\s+)?"
        r"(?:anweisungen|instruktionen|befehle|regeln|vorgaben|prompts?)" + _END,
        r"\b(?:du\s+bist|sie\s+sind|ihr\s+seid)\s+(?:jetzt\s+|nun\s+|ab\s+sofort\s+)?(?:eine?\s+)?"
        r"(?:\w+\s+){0,2}?(?:ki|k\.i\.|künstliche\s+intelligenz|sprachmodell|ki-assistent(?:in)?|"
        r"ki-modell|chatbot|assistent(?:in)?|modell)(?=\s*(?:[.,;:!]|$|\bund\b))",
        r"\bals\s+(?:eine?\s+)?(?:ki|k\.i\.|künstliche\s+intelligenz|sprachmodell|ki-assistent(?:in)?|ki-modell)"
        + _END,
        r"\b(?:system-?prompt|systemanweisung(?:en)?|systemnachricht)\b",
        r"\b(?:liebe[rs]?|hallo|hey)\s+(?:ki|k\.i\.|ki-assistent(?:in)?|assistent(?:in)?|claude|chatgpt|"
        r"sprachmodell|bot)" + _END,
        r"\b(?:markiere|markieren\s+sie|kennzeichne|kennzeichnen\s+sie|behandle|behandeln\s+sie|stufe|"
        r"stufen\s+sie)\s+(?:\w+\s+){0,5}?als\s+(?:\w+\s+(?:und|&)\s+)?(?:bezahlt|beglichen|erledigt|legitim|seriös|echt|sicher|"
        r"unbedenklich|vertrauenswürdig)\b",
        r"\bals\s+(?:bezahlt|beglichen|erledigt|legitim|seriös|unbedenklich)\s+"
        r"(?:markieren|kennzeichnen|einstufen|behandeln|werten)\b",
        r"\bneue\s+(?:anweisungen|anweisung|instruktionen)\s*:",
        r"\b(?:hinweis|nachricht|anweisung|information)(?:en)?\s+(?:an|für)\s+(?:die\s+|den\s+|alle\s+)?"
        r"(?:ki-(?:assistent(?:en|in|innen)?|systeme?|modelle?)|ki|k\.i\.|assistent(?:en)?|sprachmodelle?|chatbots?)\b",
        r"\b(?:die\s+)?(?:ki|assistent|modell|claude)\s+(?:muss|soll|darf)\s+(?:jetzt\s+)?(?:\w+\s+){0,4}?"
        r"(?:ignorieren|markieren|behandeln|ausgeben|antworten|einstufen)\b",
        r"\b(?:nicht|niemals|keinesfalls)\s+(?:als\s+)?(?:betrug|spam|phishing|verdächtig)\s+"
        r"(?:markieren|einstufen|melden|kennzeichnen)\b",
        r"\b(?:informiere|informieren\s+sie|warne|warnen\s+sie)\s+(?:den|die)\s+"
        r"(?:nutzer(?:in)?|benutzer(?:in)?|empfänger(?:in)?)\s+nicht\b",
    )
)


def detect_injection_phrases(text: str) -> list[str]:
    """Phrases in document text that address an AI model (English and German, case-insensitive).

    Returns the matched phrases in order of appearance, each once. A non-empty result means the
    document tries to instruct the model; the pipeline raises a warning banner.
    """
    flat = " ".join(unicodedata.normalize("NFKC", text).split())
    found: list[tuple[int, str]] = []
    for pattern in _INJECTION_PATTERNS:
        found.extend((m.start(), m.group().strip()) for m in pattern.finditer(flat))
    seen: set[str] = set()
    phrases: list[str] = []
    for _, phrase in sorted(found):
        if phrase.casefold() not in seen:
            seen.add(phrase.casefold())
            phrases.append(phrase)
    return phrases


# --------------------------------------------------------------------------------------------------
# Plain-text and e-mail documents
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextLine:
    """One line of a laid-out text page; ``x``/``y`` is its top-left corner in pixels."""

    text: str
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class TextLayoutPage:
    """A text page as drawn on its page image (``TEXT_PAGE_SIZE``)."""

    lines: list[TextLine]
    words: list[Word]


def decode_text_bytes(data: bytes) -> str | None:
    """Decode a text upload (UTF-16 with BOM, UTF-8, Windows-1252); ``None`` if it is not text."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encodings: tuple[str, ...] = ("utf-16",)
    else:
        encodings = ("utf-8-sig", "cp1252")
    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return text if _looks_like_text(text) else None
    return None


def text_document(data: bytes, mime: str) -> TextDocument:
    """Decoded content of ``text/plain`` or ``message/rfc822`` bytes."""
    if mime == "message/rfc822":
        return _email_document(data)
    text = decode_text_bytes(data) or data.decode("utf-8", errors="replace")
    return TextDocument(_clean_text(text))


def read_text_document(path: Path, mime: str) -> TextDocument:
    """Decoded content of a ``text/plain`` or ``message/rfc822`` file."""
    return text_document(Path(path).read_bytes(), mime)


def text_file_pages(path: Path, mime: str) -> list[PageText]:
    """Pages of a text/e-mail document, matching the page images ``render_pages`` draws for it."""
    document = read_text_document(path, mime)
    pages = layout_text(document.text)
    return [
        PageText(
            page=number,
            text="\n".join(line.text for line in page.lines),
            words=page.words,
            hidden_text=document.hidden_text if number == 1 else "",
            has_text_layer=True,
        )
        for number, page in enumerate(pages, start=1)
    ]


@functools.cache
def text_font() -> ImageFont.FreeTypeFont:
    """The font text pages are drawn with (bundled DejaVu Sans)."""
    return ImageFont.truetype(str(FONT_PATH), _TEXT_FONT_SIZE)


def layout_text(text: str, *, max_pages: int | None = None) -> list[TextLayoutPage]:
    """Wrap and paginate ``text`` onto A4 page images; always at least one (possibly empty) page.

    With ``max_pages`` the layout stops after ``max_pages + 1`` pages, so a caller can reject a text
    that is too long without laying out all of it.
    """
    font = text_font()
    width = TEXT_PAGE_SIZE[0] - 2 * _TEXT_MARGIN
    per_page = (TEXT_PAGE_SIZE[1] - 2 * _TEXT_MARGIN) // _TEXT_LINE_HEIGHT
    raws = _LINE_BREAKS_RE.sub("\n", text).split("\n")
    rows = (wrapped for raw in raws for wrapped in _wrap(raw.expandtabs(4).rstrip(), font, width))
    lines = list(rows if max_pages is None else itertools.islice(rows, per_page * max_pages + 1))
    chunks = [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[]]
    return [_layout_page(chunk, font) for chunk in chunks]


def _layout_page(lines: list[str], font: ImageFont.FreeTypeFont) -> TextLayoutPage:
    page_w, page_h = TEXT_PAGE_SIZE
    ascent, descent = font.getmetrics()
    placed: list[TextLine] = []
    words: list[Word] = []
    for row, line in enumerate(lines):
        y = _TEXT_MARGIN + row * _TEXT_LINE_HEIGHT
        placed.append(TextLine(line, _TEXT_MARGIN, y))
        for match in re.finditer(r"\S+", line):
            x0 = _TEXT_MARGIN + font.getlength(line[: match.start()])
            x1 = _TEXT_MARGIN + font.getlength(line[: match.end()])
            words.append(
                Word(match.group(), x0 / page_w, y / page_h, x1 / page_w, (y + ascent + descent) / page_h)
            )
    return TextLayoutPage(placed, words)


def _fits(text: str, font: ImageFont.FreeTypeFont, width: int) -> bool:
    """Whether ``text`` fits on one row (never more than :data:`_MAX_ROW_CHARS` characters)."""
    return len(text) <= _MAX_ROW_CHARS and font.getlength(text) <= width


def _wrap(line: str, font: ImageFont.FreeTypeFont, width: int) -> Iterator[str]:
    """Greedy word wrap (lazy); words wider than a line are split by characters.

    Only one row's worth of text is ever measured at a time, so a long line costs linear time.
    """
    if _fits(line, font, width):
        yield line
        return
    current = ""
    for match in re.finditer(r"\s*\S+", line):
        token = match.group()
        if _fits(current + token, font, width):
            current += token
            continue
        if current:
            yield current
        current = token.lstrip() if current else token
        start = 0
        while not _fits(current[start : start + _MAX_ROW_CHARS + 1], font, width):
            cut = _fitting_prefix(current[start : start + _MAX_ROW_CHARS], font, width)
            yield current[start : start + cut]
            start += cut
        current = current[start:]
    yield current


def _fitting_prefix(text: str, font: ImageFont.FreeTypeFont, width: int) -> int:
    """Length of the longest prefix of ``text`` that fits ``width`` (at least one character)."""
    low, high = 1, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if font.getlength(text[:middle]) <= width:
            low = middle
        else:
            high = middle - 1
    return low


def _looks_like_text(text: str) -> bool:
    if "\x00" in text:
        return False
    sample = text[:4096]
    printable = sum(ch.isprintable() or ch in "\n\r\t\f" for ch in sample)
    return printable >= 0.97 * len(sample)


#: Line ends and the characters Unicode counts as paragraph separators besides "\n" (bidi class B), and the form
#: feed. Each starts a new line: where Pillow lays text out with raqm, a line holding a separator made the layout
#: fail ("raqm_layout() failed").
_LINE_BREAKS_RE = re.compile("\r\n?|[\f\x1c-\x1e\x85\u2029]")


def _clean_text(text: str) -> str:
    return _LINE_BREAKS_RE.sub("\n", text).strip("\n")


def _email_document(data: bytes) -> TextDocument:
    """Headers (From, To, Cc, Date, Subject), the body and attachment names of an e-mail."""
    message = email.message_from_bytes(data, policy=email.policy.default)
    lines = [
        f"{name}: {value}" for name in ("From", "To", "Cc", "Date", "Subject") if (value := message.get(name))
    ]
    body, hidden = _email_body(message)
    attachments = [name for part in message.iter_attachments() if (name := part.get_filename())]
    if attachments:
        lines.append("Attachments: " + ", ".join(attachments))
    text = "\n".join(lines) + ("\n\n" + body.strip() if body.strip() else "")
    return TextDocument(_clean_text(text), hidden)


# --------------------------------------------------------------------------------------------------
# Prompt text
# --------------------------------------------------------------------------------------------------

_FAKE_DELIMITER = re.compile(r"^(\s*)===(?=\s*page\s+\d+\s*===)", re.IGNORECASE | re.MULTILINE)


def page_delimited(pages: Sequence[tuple[int, str]]) -> str:
    """``=== Page N ===`` blocks for the extraction prompt.

    Lines inside a page that imitate the delimiter are defused so a document cannot fake page
    boundaries.
    """
    return "\n\n".join(f"=== Page {number} ===\n{_defuse_delimiters(text.strip())}" for number, text in pages)


def _defuse_delimiters(text: str) -> str:
    return _FAKE_DELIMITER.sub(r"\1= = =", text)
