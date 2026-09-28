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
  0012), and the OCR text is neither the page text nor reported as hidden. Characters PDFium can't be
  matched to (the same character within a fraction of its size) count as visible.
* **Plain-text and e-mail documents** — decoded, laid out on A4 page images with a bundled font, and
  returned with exact word boxes so quotes from them can be highlighted like PDF text. Layout is
  lazy (it stops once a page limit is passed) and wrapping measures at most one row at a time, so
  a huge one-line file costs linear time. Text an HTML e-mail certainly hides from every reader
  (``display:none``, a tiny font, text the colour of its background …) is kept out of the text and
  reported as hidden; the short policy that decides it is in :func:`html_to_text`.
* **Prompt helpers** — ``page_delimited`` for the extraction prompt and ``detect_injection_phrases``.
"""

from __future__ import annotations

import codecs
import ctypes
import email
import email.parser
import email.policy
import functools
import itertools
import logging
import math
import re
import sys
import threading
import unicodedata
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from email.message import EmailMessage, MIMEPart
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NamedTuple, cast

import pdfplumber
import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import ImageColor, ImageFont

from ordnung.config import PACKAGE_DIR

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


def extract_pdf_pages(pdf_path: Path, rendered: Sequence[RenderedPage]) -> list[PageText]:
    """Text, words and hidden text for every rendered page of a PDF.

    Word boxes are relative to the corresponding page image. A page whose text layer cannot be
    parsed comes back empty (``has_text_layer=False``) so the pipeline transcribes it instead.
    """
    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception:  # damaged text layer: every page falls back to transcription
        log.warning("could not read the text layer of %s", pdf_path, exc_info=True)
        return [PageText(page=r.page, text="") for r in rendered]
    invisible = _invisible_chars(pdf_path, [r.page for r in rendered])
    with pdf:
        return [_extract_page_safely(pdf.pages[r.page - 1], r.page, invisible.get(r.page)) for r in rendered]


class _DrawnChar(NamedTuple):
    """One character as PDFium reads it: its text, the centre of its box (PDF user space) and whether
    its text object draws it invisibly (text render mode 3 or 7)."""

    text: str
    x: float
    y: float
    invisible: bool


_INVISIBLE_MODES = frozenset({3, 7})  # FPDF_TEXTRENDERMODE_INVISIBLE, FPDF_TEXTRENDERMODE_CLIP


def _invisible_chars(pdf_path: Path, numbers: Sequence[int]) -> dict[int, dict[str, list[_DrawnChar]]]:
    """Page number → character → where PDFium draws it, for the pages that draw text invisibly (module
    docstring); empty when PDFium can't read the file (every character then counts as visible)."""
    with PDFIUM_LOCK:
        return _invisible_chars_locked(pdf_path, numbers)


def _invisible_chars_locked(pdf_path: Path, numbers: Sequence[int]) -> dict[int, dict[str, list[_DrawnChar]]]:
    found: dict[int, dict[str, list[_DrawnChar]]] = {}
    try:
        document = pdfium.PdfDocument(pdf_path)
    except Exception:
        log.warning("could not check %s for invisible text", pdf_path, exc_info=True)
        return found
    try:
        for number in numbers:
            page = document[number - 1]
            textpage = page.get_textpage()
            try:
                chars: dict[str, list[_DrawnChar]] = {}
                any_invisible = False
                box = raw.FS_RECTF()
                for index in range(raw.FPDFText_CountChars(textpage.raw)):
                    if raw.FPDFText_IsGenerated(textpage.raw, index):
                        continue
                    text = chr(raw.FPDFText_GetUnicode(textpage.raw, index))
                    if text.isspace() or not raw.FPDFText_GetLooseCharBox(
                        textpage.raw, index, ctypes.byref(box)
                    ):
                        continue
                    obj = raw.FPDFText_GetTextObject(textpage.raw, index)
                    hidden = bool(obj) and raw.FPDFTextObj_GetTextRenderMode(obj) in _INVISIBLE_MODES
                    any_invisible = any_invisible or hidden
                    drawn = _DrawnChar(text, (box.left + box.right) / 2, (box.top + box.bottom) / 2, hidden)
                    chars.setdefault(text, []).append(drawn)
                if any_invisible:
                    found[number] = chars
            finally:
                textpage.close()
                page.close()
    except Exception:
        log.warning("could not check %s for invisible text", pdf_path, exc_info=True)
    finally:
        document.close()
    return found


def _drawn_invisibly(char: dict[str, Any], drawn: dict[str, list[_DrawnChar]] | None) -> bool:
    """Whether PDFium draws this pdfplumber character only invisibly: every character of the same
    text within a fraction of its size of it is invisible (none visible), and there is one."""
    if not drawn:
        return False
    text = str(char.get("text", ""))
    size = float(char.get("size") or 0.0)
    x = (float(char["x0"]) + float(char["x1"])) / 2
    y = (float(char["y0"]) + float(char["y1"])) / 2
    near = [
        other
        for other in drawn.get(text, [])
        if abs(other.x - x) <= max(1.0, 0.25 * size) and abs(other.y - y) <= max(1.5, 0.5 * size)
    ]
    return bool(near) and all(other.invisible for other in near)


def is_near_white(color: object) -> bool:
    """Whether a pdfplumber colour (gray, RGB or CMYK tuple) is white or nearly so."""
    rgb = _rgb(color)
    return rgb is not None and min(rgb) >= NEAR_WHITE


def _extract_page_safely(
    page: Page, number: int, drawn: dict[str, list[_DrawnChar]] | None = None
) -> PageText:
    try:
        return _extract_page(page, number, drawn)
    except Exception:  # one broken page must not stop ingestion
        log.warning("could not read the text layer of page %d", number, exc_info=True)
        return PageText(page=number, text="")
    finally:
        page.close()


def _extract_page(page: Page, number: int, drawn: dict[str, list[_DrawnChar]] | None = None) -> PageText:
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
            _is_hidden(char, glyph, frame, backgrounds) or _drawn_invisibly(char, drawn)
        ):
            visible.append(glyph)
    for char in page.chars:
        glyph = _glyph(char, frame)
        if glyph is None or glyph.is_space:
            continue
        if _drawn_invisibly(char, drawn):
            invisible.append(glyph)
        elif _is_hidden(char, glyph, frame, backgrounds):
            hidden.append(glyph)
    text, words = _assemble(visible, frame)
    meaningful = sum(ch.isalnum() for ch in text)
    unseen = sum(ch.isalnum() for glyph in invisible for ch in glyph.text)
    if unseen >= MIN_TEXT_CHARS and unseen >= meaningful:
        # a scan's OCR layer (module docstring): read from the image, the OCR text left out
        hidden_text, _ = _assemble(hidden, frame)
        return PageText(page=number, text="", hidden_text=hidden_text, has_text_layer=False)
    hidden_text, _ = _assemble([*hidden, *invisible], frame)
    return PageText(
        page=number,
        text=text,
        words=words,
        hidden_text=hidden_text,
        has_text_layer=meaningful >= MIN_TEXT_CHARS,
    )


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
    rows = (wrapped for raw in text.split("\n") for wrapped in _wrap(raw.expandtabs(4).rstrip(), font, width))
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


def _clean_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n").strip("\n")


def _email_document(data: bytes) -> TextDocument:
    """Headers (From, To, Cc, Date, Subject), the body and attachment names of an e-mail."""
    message = cast(EmailMessage, email.message_from_bytes(data, policy=email.policy.default))
    lines = [
        f"{name}: {value}" for name in ("From", "To", "Cc", "Date", "Subject") if (value := message.get(name))
    ]
    body, hidden = _email_body(message)
    attachments = [name for part in message.iter_attachments() if (name := part.get_filename())]
    if attachments:
        lines.append("Attachments: " + ", ".join(attachments))
    text = "\n".join(lines) + ("\n\n" + body.strip() if body.strip() else "")
    return TextDocument(_clean_text(text), hidden)


EMAIL_HEADING_CHARS = 200


def email_heading(data: bytes) -> str | None:
    """“Subject · Sender” of an e-mail from its headers alone (no model, no body parsed), e.g. “Ihre
    Rechnung September · Muster Telecom” — what a letter nobody read yet is called. Control and
    formatting characters are dropped and the result is at most :data:`EMAIL_HEADING_CHARS` long;
    ``None`` without a subject or sender."""
    try:
        headers = email.parser.BytesHeaderParser(policy=email.policy.default).parsebytes(data)
        subject = _heading_text(str(headers.get("Subject") or ""))
        sender = _sender_name(headers.get("From"))
    except (ValueError, LookupError, TypeError, AttributeError, IndexError):  # a malformed header
        return None
    heading = " · ".join(part for part in (subject, sender) if part)
    if len(heading) > EMAIL_HEADING_CHARS:
        heading = heading[: EMAIL_HEADING_CHARS - 1].rstrip() + "…"
    return heading or None


def _heading_text(value: str) -> str:
    return " ".join("".join(ch if ch.isprintable() else " " for ch in value).split())


def _sender_name(header: Any) -> str:
    addresses = getattr(header, "addresses", ())
    if not addresses:
        return _heading_text(str(header or ""))
    first = addresses[0]
    return _heading_text(first.display_name or first.addr_spec or "")


def _email_body(message: EmailMessage) -> tuple[str, str]:
    """The text/plain body, or the visible text of the HTML body when there is no plain part or the
    plain part is empty (mail clients show the HTML part then, so its sender never notices)."""
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return "", ""
    content = _part_text(part)
    if part.get_content_type() == "text/plain" and not content.strip():
        html = message.get_body(preferencelist=("html",))
        if html is None:
            return content, ""
        part, content = html, _part_text(html)
    if part.get_content_type() == "text/html":
        return html_to_text(content)
    return content, ""


def _part_text(part: MIMEPart) -> str:
    try:
        return str(part.get_content())
    except (LookupError, UnicodeError):  # unknown or wrong charset
        payload = part.get_payload(decode=True)
        return payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else ""


# -- HTML → text -------------------------------------------------------------------------------------

_BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "caption", "center", "dd", "details", "dialog",
        "dir", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
        "h4", "h5", "h6", "header", "hgroup", "hr", "li", "main", "menu", "nav", "ol", "p", "pre", "search",
        "section", "summary", "table", "ul",
    }
)  # fmt: skip
_BREAKS = dict.fromkeys(_BLOCK_TAGS, "\n") | {"td": "\t", "th": "\t"}  # and a <tr> starts a line
_REMOVED_TAGS = frozenset({"head", "script", "style", "template", "noscript"})
_HEAD_TAGS = frozenset({"base", "link", "meta", "noscript", "script", "style", "template", "title"})
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)
#: Optional end tags (point 6). The elements whose end tag may be left out, in groups: a start tag
#: ends the nearest open element of each group it names (in this order), with all opened in it …
_P, _CELL, _ROW, _ROWS, _ITEM, _TERM, _OPTION, _CAPTION = range(8)
_GROUPS = {
    "p": _P, "td": _CELL, "th": _CELL, "tr": _ROW, "thead": _ROWS, "tbody": _ROWS, "tfoot": _ROWS,
    "li": _ITEM, "dt": _TERM, "dd": _TERM, "option": _OPTION, "caption": _CAPTION,
}  # fmt: skip
_ENDS: dict[str, tuple[int, ...]] = dict.fromkeys(_BLOCK_TAGS - {"br", "caption"}, (_P,)) | {
    "td": (_CAPTION, _CELL), "th": (_CAPTION, _CELL), "tr": (_CAPTION, _ROW, _CELL),
    "thead": (_CAPTION, _ROWS, _ROW, _CELL), "tbody": (_CAPTION, _ROWS, _ROW, _CELL),
    "tfoot": (_CAPTION, _ROWS, _ROW, _CELL), "caption": (_CAPTION,), "col": (_CAPTION,),
    "colgroup": (_CAPTION,), "li": (_ITEM, _P), "dt": (_TERM, _P), "dd": (_TERM, _P), "option": (_OPTION,),
}  # fmt: skip
#: … unless an element opened after it keeps it out of reach: a table has its own caption, rows and
#: cells, a cell its own paragraphs and lists, a list its own items (in a scope, -1: none in reach)
_ALL_GROUPS = frozenset(range(8))
_SCOPES: dict[str, frozenset[int]] = {
    **dict.fromkeys(_REMOVED_TAGS | {"table"}, _ALL_GROUPS),
    **dict.fromkeys(("td", "th", "caption"), frozenset({_P, _ITEM, _TERM, _OPTION})),
    **dict.fromkeys(("button", "object"), frozenset({_P})),
    **dict.fromkeys(("ul", "ol"), frozenset({_ITEM})),
    "dl": frozenset({_TERM}),
    "select": frozenset({_OPTION}),
}
_NO_SCOPE = (-1,) * len(_ALL_GROUPS)
MIN_TEXT_CONTRAST = 1.2  # WCAG contrast ratio; below it text is (nearly) the colour of its background
OFFSCREEN_PX = -1000.0  # an absolutely positioned box this far left or up is off the screen
_SPACES = str.maketrans("\t\n\r\f\v", "     ")  # in the output, "\n" ends a line and "\t" a table cell
_GRAPHEME_JOINER = "\u034f"  # &#847;, in preview-text spacers: no glyph, though not a format character
RGB = tuple[float, float, float]
RGBA = tuple[float, float, float, float]
_CSS_COMMENT_OR_STRING_RE = re.compile(r"""/\*.*?(?:\*/|\Z)|"[^"\n]*"?|'[^'\n]*'?""", re.DOTALL)
_CSS_TOKEN_RE = re.compile(r"""[{};]|"[^"\n]*"?|'[^'\n]*'?""")  # a string is one token: "a;b{"
_AT_RULE_RE = re.compile(r"@([\w-]*)(.*)", re.DOTALL)  # @media only screen and (max-width: 480px)
_SCREEN_MEDIA_RE = re.compile(r"(?:(?:only\s+)?(?:all|screen))?")
_SIMPLE_SELECTOR_RE = re.compile(r"(?:[a-z][a-z0-9-]*)?\.[\w-]+|#[\w-]+|[a-z][a-z0-9-]*")  # .x #x p p.x
_SELECTOR_ARGUMENTS_RE = re.compile(r"\[[^\][]*\]|\([^()]*\)")  # [type="x"], :not(.a); "[[" is scanned once
_NAME_RE = re.compile(r"^[a-z][\w-]*|[.#][\w-]+")  # the type, classes and id of a compound selector
_CSS_ESCAPE_RE = re.compile(r"\\(?:([0-9a-f]{1,6})\s?|(.))")  # \: → ":", \31 0 → "10" (a space ends hex)
_MARKED_ESCAPE_RE = re.compile(r"U([0-9A-F]+)U")  # an escaped character while _subject reads a selector
_LENGTH_RE = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)([a-z%]*)")  # one way to split "99…9"
_RGB_RE = re.compile(r"rgba?\(([^()]*)\)")  # rgb(0, 112, 192), rgba(0,0,0,.5), rgb(0 112 192 / 50%)
_BACKGROUND_WORD_RE = re.compile(r"[a-z-]+\([^()]*\)|#?[\w-]+")  # rgb(0, 0, 0), url(x.png), #fff, red
_IMPORTANT_RE = re.compile(r"!\s*important\s*$")  # "!important", "! important", "!/**/important"
#: font sizes relative to the parent's (point 4): never larger than it, and any other
_NO_LARGER_SIZES = frozenset({"inherit", "unset", "smaller"})
_RELATIVE_SIZES = frozenset({"larger", "revert", "revert-layer"})
_RELATIVE_UNITS = frozenset({"%", "em", "ex", "ch"})
#: an inline ``display`` that makes an element a block, or a table cell, breaks the line (point 7)
_DISPLAY_BREAKS = dict.fromkeys(
    ("block", "flex", "grid", "flow-root", "list-item", "table", "table-caption", "table-row"), "\n"
) | {"table-cell": "\t"}


def _strip_css_comments(css: str) -> str:
    return _CSS_COMMENT_OR_STRING_RE.sub(lambda found: " " if found[0].startswith("/*") else found[0], css)


def _declarations(style: str) -> dict[str, str]:
    """``color: Red; FONT-SIZE: 1px ! important`` → ``{"color": "red", "font-size": "1px"}`` (CSS allows
    spaces and comments after the "!"). A shorthand counts where it stands among them: ``font`` sets
    the font size too (:func:`_shorthand_size`), and ``background`` resets a ``background-color`` or
    ``background-image`` written before it (one written after it is kept next to it)."""
    declarations: dict[str, str] = {}
    for name, _, value in (part.partition(":") for part in _strip_css_comments(style).split(";")):
        name, value = name.strip().lower(), _IMPORTANT_RE.sub("", value.lower()).strip()
        if name == "background":
            declarations.pop("background-color", None)
            declarations.pop("background-image", None)
        declarations[name] = value
        if name == "font":
            declarations["font-size"] = _shorthand_size(value)
    return declarations


def _shorthand_size(font: str) -> str:
    """The size in a ``font`` shorthand: the word before the optional ``/line-height``, else the last
    number (before the family): ``bold 15px/20px Arial`` → ``15px``; ``""`` if there is none
    (``caption``), which is not tiny."""
    if font in ("inherit", "unset", "revert", "revert-layer"):  # the size too
        return font
    before, slash, _ = font.partition("/")
    words = before.split()
    if slash:
        return words[-1] if words else ""
    return next((word for word in reversed(words) if not math.isnan(_length(word)[0])), "")


def _length(value: str | None) -> tuple[float, str]:
    """``"-9999px"`` → ``(-9999.0, "px")``; the number is NaN for anything but a number and a unit."""
    found = _LENGTH_RE.fullmatch((value or "").strip())
    return (float(found[1]), found[2]) if found else (math.nan, "")


def _tiny(font_size: str | None) -> bool:
    """Whether a font size is 0 or at most 1px/1pt."""
    size, unit = _length(font_size)
    return size == 0 or (unit in ("px", "pt") and 0 <= size <= 1)


def _font_size(value: str, parent_tiny: bool, parent_zero: bool) -> tuple[bool, bool]:
    """``(tiny, zero)``: whether an element's font size set to ``value`` is at most 1px/1pt, and
    whether it is 0 (point 4). A size of its own counts (``14px``, ``1rem``, ``small``); one relative
    to the parent's is 0 in a 0, and tiny in a tiny one when it is no larger (``100%``, ``1em``,
    ``smaller``, ``inherit``)."""
    size, unit = _length(value)
    if size == 0:
        return True, True
    if value in _NO_LARGER_SIZES or (unit == "%" and size <= 100) or (unit == "em" and size <= 1):
        return parent_tiny, parent_zero
    if unit in _RELATIVE_UNITS or value in _RELATIVE_SIZES:
        return parent_zero, parent_zero
    return _tiny(value), False


def _hides(style: dict[str, str]) -> bool:
    """Whether declarations hide an element with all it holds: ``display:none``, ``opacity:0``, a zero
    height with ``overflow:hidden``, an absolute position far off to the left or top."""
    opacity, unit = _length(style.get("opacity"))
    heights = (_length(style.get("height"))[0], _length(style.get("max-height"))[0])
    offsets = (_length(style.get("left")), _length(style.get("top")))
    return (
        style.get("display") == "none"
        or (opacity <= 0 and unit in ("", "%"))
        or (style.get("overflow") == "hidden" and 0 in heights)
        or (
            style.get("position") in ("absolute", "fixed")
            and any(u == "px" and n <= OFFSCREEN_PX for n, u in offsets)
        )
    )


def _color(value: str, *, legacy: bool = False) -> RGBA | None:
    """A CSS colour (a name, ``#hex``, ``rgb()``/``rgba()``, ``hsl()``, ``transparent``) as RGBA 0..1;
    ``None`` if it can't be read. ``legacy``: an HTML attribute, whose hex digits may lack the "#"."""
    value = value.strip().lower()
    if legacy and re.fullmatch(r"[0-9a-f]{3}|[0-9a-f]{6}", value):
        value = "#" + value
    if value == "transparent":
        return (0.0, 0.0, 0.0, 0.0)
    if (function := _RGB_RE.fullmatch(value)) is not None:
        parts = [_length(part) for part in re.split(r"[\s,/]+", function[1].strip())]
        if len(parts) not in (3, 4) or any(math.isnan(n) or u not in ("", "%") for n, u in parts):
            return None
        red, green, blue = (min(max(n * (2.55 if u == "%" else 1) / 255, 0.0), 1.0) for n, u in parts[:3])
        alpha = parts[3][0] / (100 if parts[3][1] == "%" else 1) if len(parts) == 4 else 1.0
        return red, green, blue, min(max(alpha, 0.0), 1.0)
    if value in ImageColor.colormap or value.startswith(("#", "hsl(")):
        try:
            red_byte, green_byte, blue_byte, *alpha_byte = ImageColor.getrgb(value)
        except ValueError:
            return None
        return red_byte / 255, green_byte / 255, blue_byte / 255, alpha_byte[0] / 255 if alpha_byte else 1.0
    return None


def _background(style: dict[str, str], values: dict[str, str]) -> tuple[bool, RGBA | None]:
    """Whether an element sets a background inline, and its colour (``None``: an image, or unread). A
    ``background-color`` next to the ``background`` shorthand was written after it (:func:`_declarations`):
    its colour counts, but an image in the shorthand still covers it."""
    if style.get("background-image", "none") != "none" or "background" in values:  # <td background=…>
        return True, None
    given = [value for name in ("background", "background-color") if (value := style.get(name)) is not None]
    if not given:
        return "bgcolor" in values, _color(values.get("bgcolor", ""), legacy=True)
    words = [_BACKGROUND_WORD_RE.findall(value) for value in given]  # none repeat scroll 0% 0% rgb(192, 0, 0)
    if any(word.endswith(")") and not word.startswith(("rgb", "hsl")) for word in itertools.chain(*words)):
        return True, None  # url(), linear-gradient(), var() …
    colors = [color for word in words[-1] if (color := _color(word)) is not None]
    return True, colors[0] if len(colors) == 1 else None


def _painted(color: RGBA | None, below: RGB | None) -> RGB | None:
    """What a (semi-transparent) colour looks like on what is below it; ``None`` if that's unknown."""
    if color is None or (below is None and color[3] < 1):
        return None
    if below is None or color[3] == 1:
        return color[:3]
    red, green, blue = (color[3] * c + (1 - color[3]) * b for c, b in zip(color[:3], below, strict=False))
    return red, green, blue


def _contrast(first: RGB, second: RGB) -> float:
    """WCAG contrast ratio of two colours (1 = identical, 21 = black on white)."""

    def luminance(rgb: RGB) -> float:
        red, green, blue = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _screen_media(query_list: str) -> bool:
    """Whether a media query list names the media types all/screen only (``only screen``, ``all``)."""
    return all(_SCREEN_MEDIA_RE.fullmatch(query.strip()) for query in query_list.lower().split(","))


def _css_rules(css: str, *, on_screen: bool) -> Iterator[tuple[str, str, bool]]:
    """``(selectors, declarations, on screens)`` of each style rule of a style sheet, nested ones too
    (without recursion). A rule's declarations are the text directly in its block, around the rules
    nested in it (so each character is read once). An at-rule nested in a style rule (CSS Nesting:
    ``.x { @media (…) { display: block } }``) is a rule of the same selectors, never on screens. *On
    screens*: at the top level of an on-screen sheet, or inside ``@media`` blocks of the media types
    all/screen only."""
    css = _strip_css_comments(css).replace("<!--", " ").replace("-->", " ")
    #: the open blocks: a rule's selectors (None: an at-rule outside style rules), the text directly
    #: in its body so far, and whether the rules in it are on screens
    blocks: list[tuple[str | None, list[str], bool]] = []
    statement = 0  # where the current at-rule, list of selectors or declaration starts
    body = 0  # where the text directly in the innermost open block continues
    for token in _CSS_TOKEN_RE.finditer(css):
        position = token.start()
        if token[0] == "{":
            prelude, screen = css[statement:position].strip(), blocks[-1][2] if blocks else on_screen
            if blocks:
                blocks[-1][1].append(css[body:statement])  # up to the prelude of the nested block
            if (at_rule := _AT_RULE_RE.match(prelude.lower())) is not None:
                screen = screen and at_rule[1] == "media" and _screen_media(at_rule[2])
                blocks.append((blocks[-1][0] if blocks else None, [], screen))  # in a rule: its selectors
            else:
                blocks.append((prelude, [], False))
            body = position + 1
        elif token[0] == "}" and blocks:
            selectors, texts, _ = blocks.pop()
            if selectors is not None:
                texts.append(css[body:position])
                yield selectors, ";".join(texts), blocks[-1][2] if blocks else on_screen
            body = position + 1
        if token[0] in "{};":
            statement = position + 1


def _subject(selector: str) -> set[str]:
    """The lower-case names of the elements a selector styles: ``.a > p.note:hover`` → ``{"p",
    ".note"}``, ``.sm\\:block`` → ``{".sm:block"}`` (an escaped character is part of the name);
    ``{"*"}`` (any element) for ``*``, ``[class=x]``, ``:root`` …"""
    # while the selector is taken apart, an escaped character is "U<code point>U", name characters
    # that a lower-case selector has nowhere else
    plain = _CSS_ESCAPE_RE.sub(_marked_escape, selector.strip().lower())
    plain = _SELECTOR_ARGUMENTS_RE.sub(lambda found: found[0][0], plain)  # [x] → [
    compound = re.split(r"[\s>+~]+", plain)[-1]
    names = {_MARKED_ESCAPE_RE.sub(_unmarked_escape, name) for name in _NAME_RE.findall(compound)}
    return names or ({"*"} if compound[:1] in ("*", "[", ":", "&") else set())


def _marked_escape(found: re.Match[str]) -> str:
    code = int(found[1], 16) if found[1] else ord(found[2])
    return f"U{code if 0 < code <= sys.maxunicode else 0xFFFD:X}U"  # CSS reads \0 as U+FFFD


def _unmarked_escape(found: re.Match[str]) -> str:
    return chr(int(found[1], 16)).lower()


class _StyleSheet:
    """What the ``<style>`` blocks of an e-mail say, as far as the policy asks (point 5)."""

    def __init__(self) -> None:
        #: the context-free declarations of the hiding simple rules on screens, by selector (".x", "#x",
        #: "p", "p.x"; class names and ids are case-sensitive)
        self.hiding: dict[str, dict[str, str]] = {}
        #: the names (".x", "#x", "p" in lower case; "*": any) of elements some rule may show (display
        #: other than none, visibility:visible, a font size above 1px), colour or give a background
        self.showing: set[str] = set()
        self.coloring: set[str] = set()
        self.backgrounding: set[str] = set()

    def add(self, css: str, *, on_screen: bool) -> None:
        for selectors, body, rule_on_screen in _css_rules(css, on_screen=on_screen):
            declarations = _declarations(body)
            context_free: dict[str, str] = {
                name: declarations[name]
                for name in ("display", "visibility", "opacity", "font-size")
                if name in declarations
            }
            hides = _hides(context_free) or context_free.get("visibility") == "hidden"
            hides = hides or _tiny(context_free.get("font-size"))
            # a display other than none shows whatever else the rule sets (a fade-in starts at
            # opacity:0); a font size only where the rule doesn't also take the element away
            shows = (
                context_free.get("display", "none") != "none"
                or context_free.get("visibility") == "visible"
                or (
                    "font-size" in context_free
                    and not _tiny(context_free["font-size"])
                    and context_free.get("display") != "none"
                    and context_free.get("visibility") != "hidden"
                )
            )
            for selector in selectors.split(","):
                if hides and rule_on_screen and _SIMPLE_SELECTOR_RE.fullmatch(selector.strip()):
                    self.hiding.setdefault(selector.strip(), {}).update(context_free)
                subject = _subject(selector)
                if shows:
                    self.showing |= subject
                if "color" in declarations:
                    self.coloring |= subject
                if any(name.startswith("background") for name in declarations):
                    self.backgrounding |= subject


class _Box(NamedTuple):
    """An open element, and how the text in it looks."""

    tag: str
    removed: bool = False  # in <head>, <script>, <style>, <template> or <noscript>
    hides: bool = False  # the text in it is hidden (by one of the next three, or by its colours)
    hidden: bool = False  # display:none, opacity:0 … on it or further out: nothing inside shows
    invisible: bool = False  # visibility:hidden in effect
    tiny: bool = False  # a font size of at most 1px in effect
    zero: bool = False  # a font size of 0 in effect (a relative size in it is 0 too)
    color: RGBA | None = None  # the text colour given inline (None: not given, or a rule may set it)
    background: RGB | None = None  # the background colour given inline (the same)
    breaks: str = ""  # the line break or cell break its inline display makes ("\n", "\t")


_ROOT = _Box("")


class _Reader(HTMLParser):
    """Reads an HTML e-mail in two steps: :meth:`feed` records its tags and texts and collects its style
    sheets (they apply to the elements before them too); :meth:`read` then walks the recorded tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._events: list[tuple[str, str, list[tuple[str, str | None]]]] = []  # start/end: tag; text
        self._sheets: list[tuple[list[str], bool]] = []  # the text of each <style>, and if it's on screens
        self._text: list[str] = []  # the text since the last tag
        self._style: list[str] | None = None  # the text of the open <style>
        self._sheet = _StyleSheet()
        self._out: tuple[list[str], list[str]] = ([], [])  # visible and hidden text
        #: until the first visible text, hidden text is the preview text (point 4): written as visible
        self._leading = True
        self._previewed = False  # preview text with a glyph was written
        self._stack: list[_Box] = []
        self._open: Counter[str] = Counter()  # the tags of the open elements
        #: for each open element, where in the stack the nearest open element of each group is that a
        #: start tag in it may end (see _ENDS): kept per level, so no start tag walks the stack
        self._scopes: list[tuple[int, ...]] = []
        #: the box of an element by tag, attributes and parent: the same element in the same place (a
        #: newsletter's repeated blocks, a deep stack of <div>s) is worked out once
        self._boxes: dict[tuple[str, tuple[tuple[str, str | None], ...], _Box], _Box] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._text:
            self._flush()
        self._events.append(("start", tag, attrs))
        if tag == "style":
            self._style = []
            self._sheets.append((self._style, _screen_media(dict(attrs).get("media") or "")))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:  # <br/> is one line break
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._text:
            self._flush()
        self._events.append(("end", tag, []))
        if tag == "style":
            self._style = None

    def handle_data(self, data: str) -> None:
        (self._text if self._style is None else self._style).append(data)

    def _flush(self) -> None:
        self._events.append(("text", "".join(self._text), []))
        self._text = []

    def read(self) -> tuple[str, str]:
        """``(visible text, hidden text)`` of what was fed."""
        self.close()
        if self._text:
            self._flush()
        for texts, on_screen in self._sheets:
            self._sheet.add("".join(texts), on_screen=on_screen)
        for kind, value, attrs in self._events:
            if kind == "start":
                self._start(value, attrs)
            elif kind == "end":
                self._end(value)
            else:
                self._write(value)
        return _tidy_lines("".join(self._out[0])), _tidy_lines("".join(self._out[1]))

    def _start(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._open["head"] and tag not in _HEAD_TAGS:  # <body> (or body content) ends an open <head>
            self._end("head")
        for group in _ENDS.get(tag, ()):  # <td> ends the open cell of its row, <p> an open <p> …
            if self._scopes and (index := self._scopes[-1][group]) >= 0:
                self._end(self._stack[index].tag)
        key = (tag, tuple(attrs), self._stack[-1] if self._stack else _ROOT)
        if key not in self._boxes:
            self._boxes[key] = self._box(*key)
        box = self._boxes[key]
        self._break(_BREAKS.get(tag, "\n" if tag == "tr" else "") or box.breaks)
        if tag not in _VOID_TAGS:
            self._scopes.append(self._scope(tag))
            self._stack.append(box)
            self._open[tag] += 1

    def _scope(self, tag: str) -> tuple[int, ...]:
        """The scope of the elements in a new ``tag`` element: its parent's, with the groups it keeps out
        of reach emptied and its own group's entry the element itself."""
        scope = self._scopes[-1] if self._scopes else _NO_SCOPE
        hides, own = _SCOPES.get(tag, frozenset()), _GROUPS.get(tag)
        if not hides and own is None:
            return scope
        return tuple(
            len(self._stack) if group == own else -1 if group in hides else index
            for group, index in enumerate(scope)
        )

    def _end(self, tag: str) -> None:
        """Closes the nearest open element of the tag and all opened in it; a stray end tag is ignored
        (counting the open tags keeps both linear)."""
        separator = _BREAKS.get(tag, "")
        if self._open[tag]:
            while (box := self._stack.pop()).tag != tag:
                self._open[box.tag] -= 1
            self._open[tag] -= 1
            del self._scopes[len(self._stack) :]
            separator = separator or box.breaks
        self._break(separator)

    def _write(self, text: str) -> None:
        if self._stack and self._stack[-1].tag == "head" and not text.isspace():  # text ends <head>
            self._end("head")
        box = self._stack[-1] if self._stack else _ROOT
        if box.removed:
            return
        text = text.translate(_SPACES)
        if self._leading:  # no visible text yet: hidden text is the preview text, a paragraph of its own
            if box.hides:
                self._previewed = self._previewed or _has_glyph(text)
                self._out[0].append(text)
                return
            if _has_glyph(text):
                self._leading = False
                if self._previewed:
                    self._out[0].append("\n\n")
        self._out[box.hides].append(text)

    def _break(self, separator: str) -> None:
        self._out[0].append(separator)
        self._out[1].append(separator)

    def _box(self, tag: str, attrs: tuple[tuple[str, str | None], ...], parent: _Box) -> _Box:
        if parent.removed or tag in _REMOVED_TAGS:
            return _Box(tag, removed=True)
        values: dict[str, str] = {}
        for name, value in attrs:
            values.setdefault(name, value or "")  # of a repeated attribute, browsers keep the first
        classes, identifier = values.get("class", "").split(), values.get("id", "")
        style: dict[str, str] = {}
        for key in (tag, f"#{identifier}", *(f".{c}" for c in classes), *(f"{tag}.{c}" for c in classes)):
            style.update(self._sheet.hiding.get(key, {}))
        inline = _declarations(values.get("style", ""))
        style.update(inline)  # the style attribute wins over the rules (!important is not considered)
        names = {"*", tag, f"#{identifier.lower()}", *(f".{name.lower()}" for name in classes)}
        uncertain = not names.isdisjoint(self._sheet.showing)  # its own styles don't hide it
        hidden = parent.hidden or (not uncertain and ("hidden" in values or _hides(style)))
        visibility = "visible" if uncertain else style.get("visibility")
        invisible = visibility == "hidden" or (parent.invisible and visibility != "visible")
        if "font-size" in style:  # also set by the font shorthand (_declarations)
            tiny, zero = _font_size(style["font-size"], parent.tiny, parent.zero)
        elif tag == "font" and "size" in values:  # <font size="1"> is 10px: a size, and never a tiny one
            tiny = zero = False
        else:
            tiny, zero = parent.tiny, parent.zero
        tiny, zero = tiny and not uncertain, zero and not uncertain
        color = parent.color
        if not names.isdisjoint(self._sheet.coloring):
            color = None
        elif "color" in inline or (tag == "font" and "color" in values):
            color = _color(inline["color"]) if "color" in inline else _color(values["color"], legacy=True)
        elif tag == "a" and "href" in values:  # a link has the mail client's link colour
            color = None
        background = parent.background
        sets_background, paint = _background(inline, values)
        if not names.isdisjoint(self._sheet.backgrounding):
            background = None
        elif sets_background and (paint is None or paint[3] > 0):  # transparent: the parent's shows
            background = _painted(paint, background)
        faint = False
        if (text_color := _painted(color, background)) is not None and background is not None:
            faint = _contrast(text_color, background) < MIN_TEXT_CONTRAST
        hides = hidden or invisible or tiny or faint
        breaks = _DISPLAY_BREAKS.get(inline.get("display", ""), "")
        return _Box(tag, False, hides, hidden, invisible, tiny, zero, color, background, breaks)


def html_to_text(markup: str) -> tuple[str, str]:
    """``(visible text, hidden text)`` of an HTML e-mail, following this policy (and nothing else;
    cases outside it are accepted limitations):

    1. The visible text is what the model reads. The hidden text is text Ordnung is *certain* no
       reader sees in any mail client; it is reported as hidden text (a scam sign) and never sent to
       the model.
    2. Never drop on uncertainty: when in doubt, text is visible. Other layers defend against
       injected instructions (untrusted wrapping, a tool-less extraction model, injection-phrase
       detection on the visible text, dates computed by code, grounding against the page).
    3. Removed, and not hidden text: ``<head>``, ``<script>``, ``<style>``, ``<template>``,
       ``<noscript>`` and comments, Outlook's conditional comments included (``<!--[if mso]>…
       <![endif]-->`` is an Outlook-only copy of content that other clients show from elsewhere).
    4. Certainly hidden, decided from the inline ``style`` and the ``hidden`` attribute of the
       element or an ancestor: ``display:none``; ``visibility:hidden`` (unless a descendant sets
       ``visibility:visible`` inline); ``opacity:0``; a font size of 0 or at most 1px/1pt (the
       nearest one set counts: a column sized inside a ``font-size:0`` wrapper is visible; the
       ``font`` shorthand sets one too, and ``<font size>`` one that is never tiny; a size relative
       to the parent's — ``%``, ``em``, ``ex``, ``ch``, ``smaller``, ``larger``, ``inherit`` — is 0
       in a 0, and tiny in a tiny one when it is no larger: ``100%``, ``1em``, ``smaller``);
       ``height:0`` or ``max-height:0`` together with ``overflow:hidden``;
       ``position:absolute``/``fixed`` with ``left`` or ``top`` at -1000px or less; a text
       colour and a background colour both given inline with a contrast ratio below 1.2. The text
       colour is the element's or an ancestor's (``<font color>`` too; a link has the client's
       link colour), the background the one of the nearest element that sets one (``bgcolor``
       too; an image or a colour that can't be read is unknown; of its declarations the later one
       counts: a ``background`` shorthand resets a ``background-color`` before it). ``mso-hide:all``
       is *not* hidden: it hides only in Outlook, every other client shows it. Hidden text before
       the first visible text is *not* hidden text either: it is the preview text (preheader) that
       every mail client shows in the inbox list next to the subject, so it is visible text, a
       paragraph of its own (the model reads it like the subject).
    5. ``<style>`` rules hide only when they are at the top level or inside ``@media`` blocks of the
       media types all/screen only (in a ``<style>`` whose ``media`` is unset or all/screen), have
       a simple selector (``.class``, ``#id``, ``tag``, ``tag.class``; comma lists allowed), and
       only by ``display:none``, ``visibility:hidden``, ``opacity:0`` or a font size of 0 or at
       most 1px/1pt. But a class, id or tag that any *other* rule may show — in any at-rule block
       (one nested in a style rule too) or style sheet (``media="print"`` too), with any selector
       (an escaped name such as Tailwind's ``.sm\\:block`` too) — by a display other than none or
       ``visibility:visible`` (whatever else the rule sets: a fade-in starts at ``opacity:0``), or by
       another font size in a rule without ``display:none`` or ``visibility:hidden``, is uncertain:
       its elements are not hidden, by rules or inline styles (the phone copy of a responsive e-mail
       and a dark-mode copy stay visible). A rule that may give an element a colour or a
       background makes that colour unknown (a stylesheet-coloured cell is visible). A rule whose
       last compound names no type, class or id (``*``, ``[class=x]``) may concern any element.
    6. Robust: linear time in the size of the e-mail, no recursion on the nesting depth, tolerant of
       broken HTML (``html.parser``): an end tag closes the nearest open element of its name and all
       opened in it, a stray end tag is ignored, void elements hold nothing. Left-out end tags are
       implied where every browser implies them, so a missing one can't remove or hide a letter:
       ``</head>`` at ``<body>`` or other body content; a caption at the next caption, row, cell,
       row group or column of its table; a cell at the next cell, row or row group of its table, a
       row at the next row or row group; a list item (``li``, ``dt``/``dd``, ``option``) at the next
       one of its list; a ``<p>`` at a block (``<table>`` too) outside the cells, captions and
       buttons opened in it. (HTML's other implied end tags are not.)
    7. Block elements and ``<br>`` break lines, as does an inline ``display`` that makes an element a
       block (``block``, ``flex``, ``grid``, ``list-item``, ``table``, ``table-row`` …); a table row
       is a line with its cells (``display:table-cell`` too) three spaces apart; whitespace is
       collapsed and entities are decoded. Characters without a glyph (format characters such as
       ``&zwnj;`` and ``&shy;``, and U+034F) are dropped: a preview-text spacer made of them is no
       hidden text.
    """
    reader = _Reader()
    reader.feed(markup)
    return reader.read()


def _tidy_lines(text: str) -> str:
    """A run of breaks becomes one line break or one blank line, cells are three spaces apart, and runs
    of spaces one space (:func:`_words`). (A run starts at a line break, so no text is scanned twice.)"""
    text = re.sub(r"\n[\n\t ]*", lambda run: "\n\n" if run[0].count("\n") > 1 else "\n", text)
    lines = (
        "   ".join(cell for part in line.split("\t") if (cell := _words(part))) for line in text.split("\n")
    )
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _words(text: str) -> str:
    """``text`` with runs of spaces as one space and without the characters that have no glyph: format
    characters (Unicode category Cf: zero-width spaces and joiners, the soft hyphen, the BOM, direction
    marks …) and the combining grapheme joiner U+034F."""
    words = " ".join(text.split())
    if words.isprintable() and _GRAPHEME_JOINER not in words:  # no format character (most text)
        return words
    kept = (char for char in words if char != _GRAPHEME_JOINER and unicodedata.category(char) != "Cf")
    return " ".join("".join(kept).split())


def _has_glyph(text: str) -> bool:
    """Whether ``text`` has a character a reader sees (not whitespace, and not one :func:`_words`
    drops)."""
    return any(
        not char.isspace() and char != _GRAPHEME_JOINER and unicodedata.category(char) != "Cf"
        for char in text
    )


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
