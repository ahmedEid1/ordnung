"""Intake: type sniffing, limits, content-addressed storage, photo normalisation and page rendering."""

from __future__ import annotations

import io
from pathlib import Path
from typing import cast

import pypdfium2 as pdfium
import pytest
from PIL import Image

from helpers_docs import A4, eml_bytes, letter_pdf, make_pdf, photo, scanned_pdf, set_page_boxes
from ordnung.ingest import intake
from ordnung.ingest.intake import (
    MAX_BYTES,
    PAGE_LONG_SIDE,
    PHOTO_LONG_SIDE,
    THUMBNAIL_NAME,
    THUMBNAIL_WIDTH,
    IntakeError,
    RenderedPage,
    StoredFile,
    check_size,
    combine_images_to_pdf,
    normalise_upload,
    render_pages,
    safe_filename,
    sniff_mime,
    store_original,
)


def _image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def _rgb(image: Image.Image, xy: tuple[int, int]) -> tuple[int, int, int]:
    red, green, blue = cast(tuple[int, int, int], image.convert("RGB").getpixel(xy))
    return red, green, blue


def _is_red(image: Image.Image, xy: tuple[int, int]) -> bool:
    red, green, blue = _rgb(image, xy)
    return red > 200 and green < 60 and blue < 60


def _pdf_pages(data: bytes) -> list[tuple[float, float]]:
    pdf = pdfium.PdfDocument(data)
    try:
        return [pdf.get_page_size(i) for i in range(len(pdf))]
    finally:
        pdf.close()


# --------------------------------------------------------------------------------------------------
# sniff_mime
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "filename", "expected"),
    [
        (b"%PDF-1.7\n%...", "x.bin", "application/pdf"),
        (b"\n\n   %PDF-1.4 junk before header", "", "application/pdf"),
        (b"\xff\xd8\xff\xe0\x00\x10JFIF", "photo.png", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n\x00\x00", "", "image/png"),
        (b"RIFF\x10\x00\x00\x00WEBPVP8 ", "", "image/webp"),
        (b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic", "", "image/heic"),
        (b"\x00\x00\x00\x18ftypmif1\x00\x00\x00\x00mif1heic", "", "image/heic"),
        (b"\x00\x00\x00\x14ftypmif1\x00\x00\x00\x00mif1", "", "image/heif"),
        (b"Hallo, bitte zahlen Sie bis zum 15.10.2026.\n", "note.txt", "text/plain"),
        ("Grüße aus Musterstadt".encode("cp1252"), "", "text/plain"),
        ("Grüße".encode("utf-16"), "", "text/plain"),
        (b"From: a@example.org\nTo: b@example.org\nSubject: Hi\n\nBody", "", "message/rfc822"),
        (b"From: a@example.org\nTo: b@example.org\n\nBody", "mail.txt", "text/plain"),
        (b"Just a note", "mail.eml", "message/rfc822"),
    ],
)
def test_sniff_mime_by_magic_bytes(data: bytes, filename: str, expected: str) -> None:
    assert sniff_mime(data, filename) == expected


def test_sniff_mime_real_files() -> None:
    assert sniff_mime(letter_pdf()) == "application/pdf"
    assert sniff_mime(photo("JPEG")) == "image/jpeg"
    assert sniff_mime(photo("PNG")) == "image/png"
    assert sniff_mime(photo("WEBP")) == "image/webp"
    assert sniff_mime(photo("HEIF")) == "image/heic"
    assert sniff_mime(eml_bytes(), "mail.eml") == "message/rfc822"
    assert sniff_mime(eml_bytes()) == "message/rfc822"  # recognised by its headers


@pytest.mark.parametrize(
    "data",
    [
        b"PK\x03\x04\x14\x00\x00\x00\x08\x00",  # zip / docx
        b"\x00\x01\x02\x03\x04\x05binary\x00\xff",
        b"GIF89a\x01\x00\x01\x00",
        b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf",  # AVIF is not supported
        b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2",  # MP4 video
    ],
)
def test_sniff_mime_rejects_unsupported(data: bytes) -> None:
    with pytest.raises(IntakeError, match="not supported"):
        sniff_mime(data, "file.bin")


# --------------------------------------------------------------------------------------------------
# Limits and filenames
# --------------------------------------------------------------------------------------------------


def test_check_size_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(IntakeError, match="empty"):
        check_size(b"")
    check_size(b"x" * 10)
    monkeypatch.setattr(intake, "MAX_BYTES", 10)
    with pytest.raises(IntakeError, match="larger than"):
        check_size(b"x" * 11)


def test_max_bytes_is_50_mb() -> None:
    assert MAX_BYTES == 50 * 1024 * 1024


def test_oversized_upload_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intake, "MAX_BYTES", 1000)
    with pytest.raises(IntakeError):
        normalise_upload(letter_pdf(), "big.pdf")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("letter.pdf", "letter.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\sam\\Scan 1.PDF", "Scan 1.PDF"),
        ("", "document"),
        ("..", "document"),
        ("dir/", "document"),
    ],
)
def test_safe_filename(raw: str, expected: str) -> None:
    assert safe_filename(raw) == expected


# --------------------------------------------------------------------------------------------------
# store_original
# --------------------------------------------------------------------------------------------------


def test_store_original_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    data = letter_pdf()
    first = store_original(tmp_path / "files", data, "letter.pdf")
    assert isinstance(first, StoredFile)
    assert first.mime == "application/pdf"
    assert first.size == len(data)
    assert first.path == tmp_path / "files" / first.sha256[:2] / f"{first.sha256}.pdf"
    assert first.path.read_bytes() == data
    mtime = first.path.stat().st_mtime_ns

    second = store_original(tmp_path / "files", data, "renamed.pdf")
    assert second == first
    assert first.path.stat().st_mtime_ns == mtime  # not rewritten
    assert [p.name for p in first.path.parent.iterdir()] == [first.path.name]  # no temp files left


def test_store_original_repairs_a_truncated_file(tmp_path: Path) -> None:
    data = letter_pdf()
    stored = store_original(tmp_path, data, "a.pdf")
    stored.path.write_bytes(data[:10])
    assert store_original(tmp_path, data, "a.pdf").path.read_bytes() == data


@pytest.mark.parametrize(
    ("data", "filename", "extension"),
    [
        (photo("JPEG"), "a.jpg", "jpg"),
        (photo("PNG"), "a.png", "png"),
        (photo("WEBP"), "a.webp", "webp"),
        (photo("HEIF"), "a.heic", "heic"),
        (b"plain text body", "a.txt", "txt"),
        (b"From: x@example.org\nSubject: y\n\nz", "a.eml", "eml"),
    ],
)
def test_store_original_extension_follows_content(
    tmp_path: Path, data: bytes, filename: str, extension: str
) -> None:
    stored = store_original(tmp_path, data, filename)
    assert stored.path.suffix == f".{extension}"


def test_store_original_rejects_empty_and_unknown(tmp_path: Path) -> None:
    with pytest.raises(IntakeError):
        store_original(tmp_path, b"", "a.pdf")
    with pytest.raises(IntakeError):
        store_original(tmp_path, b"PK\x03\x04zip", "a.zip")


# --------------------------------------------------------------------------------------------------
# normalise_upload
# --------------------------------------------------------------------------------------------------


def test_pdf_jpeg_and_text_uploads_are_kept_byte_for_byte() -> None:
    pdf = letter_pdf()
    assert normalise_upload(pdf, "Brief.pdf") == (pdf, "application/pdf", "Brief.pdf")
    jpeg = photo("JPEG", orientation=6)
    assert normalise_upload(jpeg, "IMG_1.JPG") == (jpeg, "image/jpeg", "IMG_1.JPG")
    text = b"Termin am 03.11.2026"
    assert normalise_upload(text, "notes.txt") == (text, "text/plain", "notes.txt")
    mail = eml_bytes()
    assert normalise_upload(mail, "mail.eml") == (mail, "message/rfc822", "mail.eml")


@pytest.mark.parametrize(
    ("fmt", "name"), [("PNG", "scan.png"), ("WEBP", "scan.webp"), ("HEIF", "IMG_0001.HEIC")]
)
def test_photos_become_upright_jpegs(fmt: str, name: str) -> None:
    data, mime, filename = normalise_upload(photo(fmt, orientation=6), f"uploads/{name}")
    assert mime == "image/jpeg"
    assert filename == name.rsplit(".", 1)[0] + ".jpg"
    image = _image(data)
    assert image.format == "JPEG"
    assert image.size == (100, 200)  # rotated upright
    assert _is_red(image, (50, 10))  # the red band is now at the top
    assert not _is_red(image, (50, 190))
    assert image.getexif().get(0x0112) in (None, 1)  # no orientation left to apply twice


def test_large_photos_are_downscaled_to_2400_px() -> None:
    data, _, _ = normalise_upload(photo("PNG", size=(3000, 1500)), "big.png")
    assert _image(data).size == (PHOTO_LONG_SIDE, 1200)


def test_transparent_png_is_flattened_on_white() -> None:
    data, _, _ = normalise_upload(photo("PNG", alpha=True), "logo.png")
    image = _image(data).convert("RGB")
    assert min(_rgb(image, (150, 50))) > 240  # transparent area became white, not black
    assert _is_red(image, (10, 50))


def test_pdf_with_too_many_pages_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intake, "MAX_PAGES", 2)
    with pytest.raises(IntakeError, match="3 pages; the limit is 2"):
        normalise_upload(letter_pdf(), "letter.pdf")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"%PDF-1.4\nthis is not really a pdf", "could not be opened"),
        (b"\xff\xd8\xff\xe0" + b"\x00" * 40, "could not be read"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40, "could not be read"),
    ],
)
def test_damaged_files_are_rejected(data: bytes, message: str) -> None:
    with pytest.raises(IntakeError, match=message):
        normalise_upload(data, "broken")


def test_decompression_bomb_guard_stays_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(IntakeError, match="too large"):
        normalise_upload(photo("PNG", size=(200, 100)), "bomb.png")


# --------------------------------------------------------------------------------------------------
# combine_images_to_pdf
# --------------------------------------------------------------------------------------------------


def test_combine_images_to_pdf_one_page_per_photo() -> None:
    images = [photo("JPEG"), photo("PNG", orientation=6), photo("HEIF", orientation=6), photo("WEBP")]
    data = combine_images_to_pdf(images)
    assert sniff_mime(data) == "application/pdf"
    sizes = _pdf_pages(data)
    assert len(sizes) == 4
    assert sizes[0][0] > sizes[0][1]  # landscape photo → landscape page
    assert sizes[1][0] < sizes[1][1]  # EXIF-rotated photo → portrait page
    assert sizes[2][0] < sizes[2][1]
    assert b"/DCTDecode" in data  # JPEG-compressed inside the PDF


def test_combine_images_to_pdf_is_deterministic() -> None:
    images = [photo("JPEG"), photo("PNG", orientation=3)]
    assert combine_images_to_pdf(images) == combine_images_to_pdf(images)


def test_combine_images_to_pdf_validates_input(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(IntakeError, match="no photos"):
        combine_images_to_pdf([])
    with pytest.raises(IntakeError, match="Only photos"):
        combine_images_to_pdf([photo("JPEG"), letter_pdf()])
    with pytest.raises(IntakeError):
        combine_images_to_pdf([b""])
    monkeypatch.setattr(intake, "MAX_PAGES", 2)
    with pytest.raises(IntakeError, match="at most 2"):
        combine_images_to_pdf([photo("JPEG")] * 3)


def test_combined_pdf_renders_upright(tmp_path: Path) -> None:
    source = tmp_path / "combined.pdf"
    source.write_bytes(combine_images_to_pdf([photo("PNG", orientation=6)]))
    [page] = render_pages(source, "application/pdf", tmp_path / "derived", "doc_a")
    image = Image.open(page.image_path).convert("RGB")
    assert image.height == PAGE_LONG_SIDE
    assert _is_red(image, (image.width // 2, 20))


# --------------------------------------------------------------------------------------------------
# render_pages
# --------------------------------------------------------------------------------------------------


def _render(tmp_path: Path, data: bytes, mime: str, name: str = "src") -> list[RenderedPage]:
    source = tmp_path / name
    source.write_bytes(data)
    return render_pages(source, mime, tmp_path / "derived", "doc_test")


def test_render_pdf_pages_and_thumbnail(tmp_path: Path) -> None:
    pages = _render(tmp_path, letter_pdf(), "application/pdf")
    assert [p.page for p in pages] == [1, 2, 3]
    for page in pages:
        assert page.image_path == tmp_path / "derived" / "doc_test" / f"page-{page.page}.jpg"
        with Image.open(page.image_path) as image:
            assert image.format == "JPEG"
            assert image.size == (page.width, page.height)
        assert page.height == PAGE_LONG_SIDE
        assert page.width == pytest.approx(PAGE_LONG_SIDE * A4[0] / A4[1], abs=2)
    with Image.open(tmp_path / "derived" / "doc_test" / THUMBNAIL_NAME) as thumb:
        assert thumb.width == THUMBNAIL_WIDTH
        assert thumb.height == pytest.approx(THUMBNAIL_WIDTH * pages[0].height / pages[0].width, abs=1)


@pytest.mark.parametrize("rotation", [90, 270])
def test_render_respects_page_rotation(tmp_path: Path, rotation: int) -> None:
    data = set_page_boxes(letter_pdf(), 1, rotation=rotation)
    pages = _render(tmp_path, data, "application/pdf")
    assert pages[0].height > pages[0].width
    assert pages[1].width == PAGE_LONG_SIDE and pages[1].width > pages[1].height


def test_render_respects_cropbox(tmp_path: Path) -> None:
    data = set_page_boxes(letter_pdf(), 0, cropbox=(50, 300, 450, 700))  # 400 x 400 pt
    pages = _render(tmp_path, data, "application/pdf")
    assert pages[0].width == pages[0].height == PAGE_LONG_SIDE


def test_render_scanned_pdf(tmp_path: Path) -> None:
    [page] = _render(tmp_path, scanned_pdf(), "application/pdf")
    assert page.height == PAGE_LONG_SIDE


def test_render_photo_is_upright_and_resized(tmp_path: Path) -> None:
    [page] = _render(tmp_path, photo("JPEG", orientation=6, size=(4000, 2000)), "image/jpeg")
    assert (page.width, page.height) == (800, 1600)
    image = Image.open(page.image_path).convert("RGB")
    assert _is_red(image, (400, 50))
    assert not _is_red(image, (400, 1550))


def test_render_small_heic_photo_is_not_upscaled(tmp_path: Path) -> None:
    [page] = _render(tmp_path, photo("HEIF", orientation=6), "image/heic")
    assert (page.width, page.height) == (100, 200)


def test_render_text_document(tmp_path: Path) -> None:
    text = "Termin beim Bürgeramt am 03.11.2026 um 10:30 Uhr.\n" * 5
    [page] = _render(tmp_path, text.encode(), "text/plain")
    image = Image.open(page.image_path).convert("L")
    assert (page.width, page.height) == (1131, 1600)
    darkest, _ = cast(tuple[int, int], image.getextrema())
    assert darkest < 80  # dark text was drawn
    assert min(_rgb(image, (5, 5))) > 240  # on a white page


def test_render_long_text_paginates(tmp_path: Path) -> None:
    text = "\n".join(f"Zeile {n}" for n in range(1, 101))
    pages = _render(tmp_path, text.encode(), "text/plain")
    assert len(pages) == 3


def test_render_email(tmp_path: Path) -> None:
    pages = _render(tmp_path, eml_bytes(), "message/rfc822", "mail.eml")
    assert len(pages) == 1
    assert (tmp_path / "derived" / "doc_test" / THUMBNAIL_NAME).is_file()


def test_render_enforces_page_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intake, "MAX_PAGES", 2)
    with pytest.raises(IntakeError, match="limit is 2"):
        _render(tmp_path, letter_pdf(), "application/pdf")
    with pytest.raises(IntakeError, match="limit is 2"):
        _render(tmp_path, ("x\n" * 200).encode(), "text/plain")


def test_render_replaces_stale_pages(tmp_path: Path) -> None:
    _render(tmp_path, letter_pdf(), "application/pdf")
    pages = _render(tmp_path, make_pdf([[]]), "application/pdf")
    assert len(pages) == 1
    assert sorted(p.name for p in (tmp_path / "derived" / "doc_test").glob("page-*.jpg")) == ["page-1.jpg"]


def test_render_rejects_unknown_type_and_broken_pdf(tmp_path: Path) -> None:
    with pytest.raises(IntakeError):
        _render(tmp_path, b"whatever", "application/zip")
    with pytest.raises(IntakeError, match="could not be opened"):
        _render(tmp_path, b"%PDF-1.4 broken", "application/pdf")


BROKEN_PAGE_PDF = (
    b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    b"3 0 obj << /Type /Font >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
)


def test_render_pdf_with_an_unreadable_page(tmp_path: Path) -> None:
    normalise_upload(BROKEN_PAGE_PDF, "odd.pdf")  # the page tree itself is fine
    with pytest.raises(IntakeError, match="Page 1 of this PDF could not be read"):
        _render(tmp_path, BROKEN_PAGE_PDF, "application/pdf")


def test_pdf_without_pages_is_rejected() -> None:
    empty = b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"
    with pytest.raises(IntakeError, match="could not be opened"):
        normalise_upload(empty, "empty.pdf")
