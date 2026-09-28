"""Intake (SPEC §8 stage 1): validate uploads, store originals, render page images.

Pure filesystem + computation — no database, no model calls. Every rejection raises
:class:`IntakeError` with a message that can be shown to the person as-is.

Untrusted files are bounded before anything decodes them: PDFs whose streams expand too far
(:mod:`ordnung.ingest.expansion`), photos with more than :data:`MAX_IMAGE_PIXELS` pixels (JPEGs are
decoded at a reduced scale) and text files longer than :data:`MAX_PAGES` pages (laid out lazily) are
rejected. Stored originals and page images are readable by their owner only.

PDFium is not thread-safe, so every pypdfium2 call in the app must hold :data:`PDFIUM_LOCK`.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import pillow_heif
import pypdfium2 as pdfium
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from ordnung.ingest.expansion import ExpansionError, check_pdf_expansion
from ordnung.ingest.text import (
    TEXT_PAGE_SIZE,
    decode_text_bytes,
    layout_text,
    read_text_document,
    text_document,
    text_font,
)

pillow_heif.register_heif_opener()

MAX_BYTES = 50 * 1024 * 1024
MAX_PAGES = 60
PAGE_LONG_SIDE = 1600  # rendered page images (also what vision calls receive)
PAGE_QUALITY = 85
PHOTO_LONG_SIDE = 2400  # converted photo originals
PHOTO_QUALITY = 88
THUMBNAIL_WIDTH = 320
THUMBNAIL_NAME = "thumbnail.jpg"
MAX_IMAGE_PIXELS = 89_478_485  # Pillow's own limit, enforced here as an error (not a warning)
PRIVATE_FILE_MODE = 0o600

PDFIUM_LOCK = threading.Lock()

IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"})
TEXT_TYPES = frozenset({"text/plain", "message/rfc822"})
_EXTENSIONS = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
    "text/plain": "txt",
    "message/rfc822": "eml",
}
_HEIC_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"hevm", b"hevs"})
_HEIF_BRANDS = frozenset({b"mif1", b"msf1", b"heif"})
_EMAIL_HEADER = re.compile(
    r"^(?:from|to|cc|subject|date|received|return-path|message-id|mime-version|delivered-to|reply-to"
    r"|content-type|x-[\w-]+):",
    re.IGNORECASE,
)
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)  # fixed PDF creation date: same photos → same bytes → same id
_A4_LONG_SIDE_PT = 841.89
_TEXT_COLOR = (25, 25, 25)

_UNSUPPORTED = (
    "This file type is not supported. Please upload a PDF, a photo (JPEG, PNG, WEBP, HEIC) "
    "or a text or e-mail file (.txt, .eml)."
)


_TOO_LARGE_IMAGE = "This image is too large to process safely."
_PHOTO_FORMATS = ("JPEG", "PNG", "WEBP", "HEIF")  # only these decoders ever see an upload
TOO_DEEP = "This e-mail is nested too deeply to be read. Save the letter inside it as a PDF and add that."


class IntakeError(ValueError):
    """An upload was rejected; the message is written for the person who uploaded it."""


@dataclass(frozen=True, slots=True)
class StoredFile:
    """An original stored content-addressed under ``files/<sha[:2]>/<sha>.<ext>``."""

    sha256: str
    path: Path
    mime: str
    size: int


@dataclass(frozen=True, slots=True)
class RenderedPage:
    """A page image in ``derived/<doc_id>/page-<n>.jpg`` (``width``/``height`` in pixels)."""

    page: int
    width: int
    height: int
    image_path: Path


# --------------------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------------------


def check_size(data: bytes) -> None:
    """Reject empty files and files over :data:`MAX_BYTES`."""
    if not data:
        raise IntakeError("This file is empty.")
    if len(data) > MAX_BYTES:
        raise IntakeError(
            f"This file is larger than {MAX_BYTES // (1024 * 1024)} MB. "
            "Please split it or reduce its size and upload it again."
        )


def sniff_mime(data: bytes, filename: str = "") -> str:
    """Detect the document type from its content (magic bytes); the filename only separates
    ``.eml`` e-mails from plain text.

    Returns one of ``application/pdf``, ``image/jpeg``, ``image/png``, ``image/webp``,
    ``image/heic``, ``image/heif``, ``text/plain``, ``message/rfc822``.
    """
    head = data[:64]
    if b"%PDF-" in data[:1024]:
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp":
        return _heif_type(data)
    text = decode_text_bytes(data)
    if text is not None:
        return "message/rfc822" if _looks_like_email(text, filename) else "text/plain"
    raise IntakeError(_UNSUPPORTED)


def _heif_type(data: bytes) -> str:
    """HEIC/HEIF from the ISO-BMFF ``ftyp`` box (major + compatible brands); AVIF is unsupported."""
    box_size = int.from_bytes(data[:4], "big")
    major = data[8:12]
    brands = {major} | {data[i : i + 4] for i in range(16, min(box_size, 256), 4)}
    if major not in (b"avif", b"avis"):
        if brands & _HEIC_BRANDS:
            return "image/heic"
        if brands & _HEIF_BRANDS:
            return "image/heif"
    raise IntakeError(_UNSUPPORTED)


def _looks_like_email(text: str, filename: str) -> bool:
    suffix = PurePosixPath(filename.lower()).suffix
    if suffix in (".eml", ".txt"):
        return suffix == ".eml"
    header_block = text.lstrip().split("\n\n", 1)[0].splitlines()[:20]
    return sum(bool(_EMAIL_HEADER.match(line)) for line in header_block) >= 2


# --------------------------------------------------------------------------------------------------
# Uploads
# --------------------------------------------------------------------------------------------------


def normalise_upload(data: bytes, filename: str) -> tuple[bytes, str, str]:
    """Validate an upload and bring it into a storable form: ``(bytes, mime, filename)``.

    PDFs (≤ :data:`MAX_PAGES` pages), JPEGs and text/e-mail files are kept byte-for-byte; PNG,
    WEBP, HEIC and HEIF photos become upright JPEGs (≤ 2400 px, quality 88, metadata removed).
    """
    check_size(data)
    name = safe_filename(filename)
    mime = sniff_mime(data, name)
    if mime == "application/pdf":
        _check_pdf(data)
        return data, mime, name
    if mime in TEXT_TYPES:
        try:
            text = text_document(data, mime).text
        except RecursionError:  # an e-mail nested thousands of levels deep (the parser recurses)
            raise IntakeError(TOO_DEEP) from None
        _check_text_pages(len(layout_text(text, max_pages=MAX_PAGES)))
        return data, mime, name
    image = _load_image(data)
    if mime == "image/jpeg":
        return data, mime, name
    image.thumbnail((PHOTO_LONG_SIDE, PHOTO_LONG_SIDE), Image.Resampling.LANCZOS)
    return _jpeg_bytes(image, PHOTO_QUALITY), "image/jpeg", str(PurePosixPath(name).with_suffix(".jpg"))


def safe_filename(filename: str) -> str:
    """The last path component of a client-supplied filename (``document`` if empty), without control
    characters or bidirectional overrides (they could spoof the name or reach a terminal)."""
    name = strip_control(filename).replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name if name not in ("", ".", "..") else "document"


_CONTROL_RE = re.compile("[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def strip_control(text: str) -> str:
    """``text`` without C0/C1 control characters (escape sequences) and bidirectional overrides."""
    return _CONTROL_RE.sub("", text)


def download_name(filename: str, mime: str) -> str:
    """The name an original is downloaded under: its extension always matches its real type, so a
    file uploaded as ``letter.html`` never opens as a web page."""
    extension = _EXTENSIONS.get(mime)
    if extension is None:
        return filename
    return f"{PurePosixPath(filename).stem or 'document'}.{extension}"


def store_original(files_dir: Path, data: bytes, filename: str) -> StoredFile:
    """Store ``data`` at ``files_dir/<sha[:2]>/<sha>.<ext>``; idempotent for identical content."""
    check_size(data)
    mime = sniff_mime(data, filename)
    sha = hashlib.sha256(data).hexdigest()
    path = Path(files_dir) / sha[:2] / f"{sha}.{_EXTENSIONS[mime]}"
    if not (path.is_file() and path.stat().st_size == len(data)):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _write_atomic(path, data)
    return StoredFile(sha256=sha, path=path, mime=mime, size=len(data))


def combine_images_to_pdf(images: Sequence[bytes]) -> bytes:
    """One PDF with one page per photo (upright, RGB, JPEG-compressed), for multi-photo letters.

    The output is deterministic, so combining the same photos again yields the same document.
    """
    if not images:
        raise IntakeError("There are no photos to combine.")
    if len(images) > MAX_PAGES:
        raise IntakeError(f"Please combine at most {MAX_PAGES} photos into one document.")
    pdf = FPDF(unit="pt")
    pdf.set_creation_date(_EPOCH)
    pdf.set_auto_page_break(False)
    for data in images:
        check_size(data)
        if sniff_mime(data) not in IMAGE_TYPES:
            raise IntakeError("Only photos can be combined into one document.")
        image = _load_image(data)
        image.thumbnail((PHOTO_LONG_SIDE, PHOTO_LONG_SIDE), Image.Resampling.LANCZOS)
        scale = _A4_LONG_SIDE_PT / max(image.size)
        width, height = image.width * scale, image.height * scale
        pdf.add_page(format=(width, height))
        pdf.image(io.BytesIO(_jpeg_bytes(image, PHOTO_QUALITY)), x=0, y=0, w=width, h=height)
    return bytes(pdf.output())


# --------------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------------


def render_pages(src_path: Path, mime: str, out_dir: Path, doc_id: str) -> list[RenderedPage]:
    """Render every page to ``out_dir/<doc_id>/page-<n>.jpg`` (long side ~1600 px) plus
    ``thumbnail.jpg`` (320 px wide) of page 1.

    PDFs are rendered with their ``/Rotate`` and CropBox; photos are turned upright (EXIF); text
    and e-mail documents are typeset onto A4 pages. The number of pages is ``len(result)``.
    """
    target = Path(out_dir) / doc_id
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    for stale in target.glob("page-*.jpg"):
        stale.unlink()
    if mime == "application/pdf":
        pages = _render_pdf(Path(src_path), target)
    elif mime in IMAGE_TYPES:
        pages = [_render_image(Path(src_path), target)]
    elif mime in TEXT_TYPES:
        pages = _render_text(Path(src_path), mime, target)
    else:
        raise IntakeError(_UNSUPPORTED)
    _write_thumbnail(pages[0].image_path, target / THUMBNAIL_NAME)
    return pages


def _render_pdf(src: Path, target: Path) -> list[RenderedPage]:
    with PDFIUM_LOCK:
        pdf = _open_pdf(src)
        try:
            _check_page_count(len(pdf))
            return [_render_pdf_page(pdf, index, target) for index in range(len(pdf))]
        finally:
            pdf.close()


def _render_pdf_page(pdf: pdfium.PdfDocument, index: int, target: Path) -> RenderedPage:
    try:
        image = _pdf_page_image(pdf, index)
    except pdfium.PdfiumError as exc:
        raise IntakeError(f"Page {index + 1} of this PDF could not be read. It may be damaged.") from exc
    return _save_page(image, target, index + 1)


def _pdf_page_image(pdf: pdfium.PdfDocument, index: int) -> Image.Image:
    page = pdf[index]
    try:
        width, height = page.get_size()  # already rotated by /Rotate, clipped to the CropBox
        bitmap = page.render(scale=PAGE_LONG_SIDE / max(width, height), may_draw_forms=True)
        try:
            return bitmap.to_pil().convert("RGB")
        finally:
            bitmap.close()
    finally:
        page.close()


def _render_image(src: Path, target: Path) -> RenderedPage:
    image = _load_image(src.read_bytes())
    image.thumbnail((PAGE_LONG_SIDE, PAGE_LONG_SIDE), Image.Resampling.LANCZOS)
    return _save_page(image, target, 1)


def _render_text(src: Path, mime: str, target: Path) -> list[RenderedPage]:
    layout = layout_text(read_text_document(src, mime).text, max_pages=MAX_PAGES)
    _check_text_pages(len(layout))
    font = text_font()
    pages: list[RenderedPage] = []
    for number, page in enumerate(layout, start=1):
        image = Image.new("RGB", TEXT_PAGE_SIZE, "white")
        draw = ImageDraw.Draw(image)
        for line in page.lines:
            draw.text((line.x, line.y), line.text, font=font, fill=_TEXT_COLOR)
        pages.append(_save_page(image, target, number))
    return pages


def _save_page(image: Image.Image, target: Path, number: int) -> RenderedPage:
    path = target / f"page-{number}.jpg"
    _write_atomic(path, _jpeg_bytes(image, PAGE_QUALITY))
    return RenderedPage(page=number, width=image.width, height=image.height, image_path=path)


def _write_thumbnail(page_image: Path, path: Path) -> None:
    with Image.open(page_image) as image:
        height = max(1, round(image.height * THUMBNAIL_WIDTH / image.width))
        thumbnail = image.resize((THUMBNAIL_WIDTH, height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    thumbnail.save(buffer, "JPEG", quality=PAGE_QUALITY)
    _write_atomic(path, buffer.getvalue())


# --------------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------------


def _check_pdf(data: bytes) -> None:
    try:
        check_pdf_expansion(data)
    except ExpansionError as exc:
        raise IntakeError(str(exc)) from exc
    with PDFIUM_LOCK:
        pdf = _open_pdf(data)
        try:
            _check_page_count(len(pdf))
        finally:
            pdf.close()


def _open_pdf(source: Path | bytes) -> pdfium.PdfDocument:
    """Open a PDF (caller holds :data:`PDFIUM_LOCK`) with form fields rendered."""
    try:
        pdf = pdfium.PdfDocument(source)
    except pdfium.PdfiumError as exc:
        raise IntakeError("This PDF could not be opened. It may be damaged or password-protected.") from exc
    pdf.init_forms()
    return pdf


def _check_page_count(pages: int) -> None:
    if pages > MAX_PAGES:
        raise IntakeError(f"This document has {pages} pages; the limit is {MAX_PAGES} pages per document.")


def _check_text_pages(pages: int) -> None:
    """Text is laid out only up to one page past the limit, so its real length isn't known."""
    if pages > MAX_PAGES:
        raise IntakeError(
            f"This text is longer than {MAX_PAGES} pages; the limit is {MAX_PAGES} pages per document."
        )


def image_size(data: bytes) -> tuple[int, int] | None:
    """A photo's width and height from its header, without decoding it (``None``: not a photo Ordnung
    reads, or damaged)."""
    try:
        with Image.open(io.BytesIO(data), formats=_PHOTO_FORMATS) as image:
            return image.size
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


def _load_image(data: bytes) -> Image.Image:
    """Decode a photo, turned upright (EXIF orientation) and flattened to RGB on white.

    Nothing is decoded before the size is known: JPEGs are decoded at a reduced scale (no more than
    needed for :data:`PHOTO_LONG_SIDE`), and images with more than :data:`MAX_IMAGE_PIXELS` pixels
    after that are rejected — Pillow itself would only warn below twice its limit.
    """
    try:
        with Image.open(io.BytesIO(data), formats=_PHOTO_FORMATS) as image:
            if image.format == "JPEG":
                image.draft("RGB", (PHOTO_LONG_SIDE, PHOTO_LONG_SIDE))
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise IntakeError(_TOO_LARGE_IMAGE)
            upright = ImageOps.exif_transpose(image)
            return _flatten(upright)
    except IntakeError:
        raise
    except Image.DecompressionBombError as exc:
        raise IntakeError(_TOO_LARGE_IMAGE) from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise IntakeError("This image could not be read. It may be damaged.") from exc


def _flatten(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _jpeg_bytes(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def _write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically, readable by the owner only (``0600``)."""
    partial = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.part")
    try:
        fd = os.open(
            partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), PRIVATE_FILE_MODE
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)
