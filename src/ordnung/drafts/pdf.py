"""DIN 5008 Form B business letter on A4 (SPEC §11), rendered with fpdf2 and the bundled DejaVu fonts.

Layout (mm from the top-left corner):

* address field at x 20, y 45, 85 × 45 (fits a DL/C6 window envelope): the sender line
  (Rücksendeangabe, 7 pt) on the last line of the 17.7 mm notes zone, the recipient in the 27.3 mm
  address zone below it;
* sender block (information block) at x 125, y 50;
* place and date right-aligned under the address field, then the bold subject;
* body from x 25 to x 190, paragraphs separated by one blank line;
* closing formula, ~15 mm signature space, printed name, then the enclosures ("Anlage");
* fold marks at y 105 and 210 and the hole mark at y 148.5 at the left edge;
* "Seite n von m" in the footer only when the letter runs over more than one page.

The letter carries no software branding. Output is deterministic: the PDF creation date is the
draft's ``created_at``, so the same draft always gives the same bytes.

:func:`render_preview` draws the same PDF as one PNG, page under page, for the web app's print
preview (browsers on phones show no PDF inline, and a PDF viewer in a frame can't follow the theme).
"""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime
from pathlib import Path

import pypdfium2 as pdfium
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from PIL import Image

from ordnung.drafts.templates import closing
from ordnung.ingest.intake import PDFIUM_LOCK
from ordnung.models import Draft, Profile

FONT_DIR = Path(__file__).resolve().parent / "fonts"
FONT = "DejaVu"

PAGE_WIDTH = 210.0
LEFT = 25.0
RIGHT = 20.0
TEXT_WIDTH = PAGE_WIDTH - LEFT - RIGHT
TOP = 20.0
BOTTOM = 25.0

ADDRESS_X = 20.0
ADDRESS_Y = 45.0
ADDRESS_WIDTH = 85.0
ADDRESS_HEIGHT = 45.0
ADDRESS_INSET = 5.0
NOTES_ZONE = 17.7
ADDRESS_LINE = 4.23
RETURN_LINE_Y = ADDRESS_Y + NOTES_ZONE - 4.5

INFO_X = 125.0
INFO_Y = 50.0
INFO_WIDTH = 75.0
INFO_LINE = 4.0

PLACE_DATE_Y = ADDRESS_Y + ADDRESS_HEIGHT + 5.0
SUBJECT_Y = PLACE_DATE_Y + 8.5
LINE = 5.0
SIGNATURE_SPACE = 15.0

FOLD_MARKS = (105.0, 210.0)
HOLE_MARK = 148.5
MARK_X = 4.0
FOLD_MARK_LENGTH = 5.0
HOLE_MARK_LENGTH = 7.0

BODY_SIZE = 11.0
ADDRESS_SIZE = 10.0
INFO_SIZE = 9.0
RETURN_SIZE = 7.0
MIN_RETURN_SIZE = 5.5
FOOTER_SIZE = 8.0

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


class _LetterPDF(FPDF):
    """A4 page with fold and hole marks and, when asked, page numbers."""

    def __init__(self, language: str, total_pages: int) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.language = language
        self.total_pages = total_pages

    def header(self) -> None:
        self.set_draw_color(0, 0, 0)
        self.set_line_width(0.2)
        for y in FOLD_MARKS:
            self.line(MARK_X, y, MARK_X + FOLD_MARK_LENGTH, y)
        self.line(MARK_X, HOLE_MARK, MARK_X + HOLE_MARK_LENGTH, HOLE_MARK)

    def footer(self) -> None:
        if self.total_pages <= 1:
            return
        self.set_y(-15)
        self.set_font(FONT, "", FOOTER_SIZE)
        word, joiner = ("Seite", "von") if self.language == "de" else ("Page", "of")
        self.cell(0, 4, f"{word} {self.page_no()} {joiner} {self.total_pages}", align="R")


def _lines(block: str) -> list[str]:
    return [line.strip() for line in block.splitlines() if line.strip()]


def _paragraphs(body: str) -> list[str]:
    return [part.strip("\n") for part in _PARAGRAPH_BREAK.split(body.strip()) if part.strip()]


def _creation_date(draft: Draft) -> datetime:
    try:
        moment = datetime.fromisoformat(draft.created_at)
    except ValueError:
        return datetime(2000, 1, 1, tzinfo=UTC)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _new_pdf(draft: Draft, profile: Profile, total_pages: int) -> _LetterPDF:
    pdf = _LetterPDF(draft.language, total_pages)
    pdf.set_creation_date(_creation_date(draft))
    pdf.set_title(draft.subject)
    if profile.name:
        pdf.set_author(profile.name)
    pdf.set_lang("de-DE" if draft.language == "de" else draft.language)
    pdf.add_font(FONT, "", str(FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font(FONT, "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.set_margins(LEFT, TOP, RIGHT)
    pdf.set_auto_page_break(auto=True, margin=BOTTOM)
    pdf.add_page()
    return pdf


def _return_line(pdf: FPDF, sender_lines: list[str]) -> None:
    """The small sender line (Rücksendeangabe) at the top of the window."""
    if not sender_lines:
        return
    text = " · ".join(part.strip() for line in sender_lines for part in line.split(",") if part.strip())
    width = ADDRESS_WIDTH - 2 * ADDRESS_INSET
    size = RETURN_SIZE
    pdf.set_font(FONT, "", size)
    while pdf.get_string_width(text) > width and size > MIN_RETURN_SIZE:
        size -= 0.5
        pdf.set_font(FONT, "", size)
    pdf.set_xy(ADDRESS_X + ADDRESS_INSET, RETURN_LINE_Y)
    pdf.cell(width, 3.5, text)


def _address_field(pdf: FPDF, draft: Draft) -> None:
    _return_line(pdf, _lines(draft.sender_block))
    pdf.set_font(FONT, "", ADDRESS_SIZE)
    y = ADDRESS_Y + NOTES_ZONE
    for line in _lines(draft.recipient_block):
        pdf.set_xy(ADDRESS_X + ADDRESS_INSET, y)
        pdf.cell(ADDRESS_WIDTH - 2 * ADDRESS_INSET, ADDRESS_LINE, line)
        y += ADDRESS_LINE


def _sender_block(pdf: FPDF, draft: Draft, profile: Profile) -> None:
    lines = _lines(draft.sender_block)
    contact = []
    phone_label = "Telefon" if draft.language == "de" else "Phone"
    if profile.phone and profile.phone not in draft.sender_block:
        contact.append(f"{phone_label}: {profile.phone}")
    if profile.email and profile.email not in draft.sender_block:
        contact.append(f"E-Mail: {profile.email}")
    y = INFO_Y
    for index, line in enumerate(lines):
        pdf.set_font(FONT, "B" if index == 0 else "", INFO_SIZE)
        pdf.set_xy(INFO_X, y)
        pdf.cell(INFO_WIDTH, INFO_LINE, line)
        y += INFO_LINE
    if contact:
        y += INFO_LINE / 2
        pdf.set_font(FONT, "", INFO_SIZE)
        for line in contact:
            pdf.set_xy(INFO_X, y)
            pdf.cell(INFO_WIDTH, INFO_LINE, line)
            y += INFO_LINE


def _heading(pdf: FPDF, draft: Draft) -> None:
    if draft.place_date:
        pdf.set_font(FONT, "", BODY_SIZE)
        pdf.set_xy(LEFT, PLACE_DATE_Y)
        pdf.cell(TEXT_WIDTH, LINE, draft.place_date, align="R")
    pdf.set_xy(LEFT, SUBJECT_Y)
    if draft.subject:
        pdf.set_font(FONT, "B", BODY_SIZE)
        pdf.multi_cell(TEXT_WIDTH, LINE, draft.subject, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2 * LINE)


def _body(pdf: FPDF, draft: Draft) -> None:
    pdf.set_font(FONT, "", BODY_SIZE)
    for index, paragraph in enumerate(_paragraphs(draft.body)):
        if index:
            pdf.ln(LINE)
        pdf.multi_cell(TEXT_WIDTH, LINE, paragraph, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _signature(pdf: FPDF, draft: Draft, profile: Profile) -> None:
    """Closing formula, signature space and printed name — kept together on one page."""
    enclosure_height = (len(draft.enclosures) + 2) * LINE if draft.enclosures else 0.0
    needed = 2 * LINE + SIGNATURE_SPACE + LINE + enclosure_height
    if pdf.will_page_break(needed):
        pdf.add_page()
    else:
        pdf.ln(LINE)
    pdf.set_font(FONT, "", BODY_SIZE)
    pdf.cell(
        TEXT_WIDTH,
        LINE,
        closing("de" if draft.language == "de" else "en"),
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.ln(SIGNATURE_SPACE)
    if profile.name:
        pdf.cell(TEXT_WIDTH, LINE, profile.name, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _enclosures(pdf: FPDF, draft: Draft) -> None:
    if not draft.enclosures:
        return
    single = len(draft.enclosures) == 1
    if draft.language == "de":
        title = "Anlage" if single else "Anlagen"
    else:
        title = "Enclosure" if single else "Enclosures"
    pdf.ln(LINE)
    pdf.set_font(FONT, "B", BODY_SIZE)
    pdf.cell(TEXT_WIDTH, LINE, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font(FONT, "", BODY_SIZE)
    for enclosure in draft.enclosures:
        pdf.multi_cell(TEXT_WIDTH, LINE, enclosure, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _layout(draft: Draft, profile: Profile, total_pages: int) -> _LetterPDF:
    pdf = _new_pdf(draft, profile, total_pages)
    _address_field(pdf, draft)
    _sender_block(pdf, draft, profile)
    _heading(pdf, draft)
    _body(pdf, draft)
    _signature(pdf, draft, profile)
    _enclosures(pdf, draft)
    return pdf


def render(draft: Draft, profile: Profile) -> bytes:
    """The letter as PDF bytes (A4, DIN 5008 Form B; page numbers only on multi-page letters)."""
    pages = _layout(draft, profile, total_pages=1).pages_count
    return bytes(_layout(draft, profile, total_pages=pages).output())


#: Width of the print preview in pixels: twice the preview's widest CSS size (560 px), so it is sharp.
PREVIEW_WIDTH = 1120
#: Transparent gap between two pages of the preview, in pixels (the page's frame shows through).
PREVIEW_GAP = 32


def render_preview(draft: Draft, profile: Profile, *, width: int = PREVIEW_WIDTH) -> bytes:
    """The letter as it prints: every page of :func:`render`'s PDF, ``width`` pixels wide, one under
    the other with a transparent gap between them, as a PNG."""
    data = render(draft, profile)
    pages: list[Image.Image] = []
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(data)
        try:
            for index in range(len(pdf)):
                page = pdf[index]
                try:
                    page_width, _ = page.get_size()
                    bitmap = page.render(scale=width / page_width)
                    try:
                        pages.append(bitmap.to_pil().convert("RGB"))
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        finally:
            pdf.close()
    height = sum(image.height for image in pages) + PREVIEW_GAP * (len(pages) - 1)
    sheet = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    top = 0
    for image in pages:
        sheet.paste(image, (0, top))
        top += image.height + PREVIEW_GAP
    buffer = io.BytesIO()
    sheet.save(buffer, "PNG", optimize=False, compress_level=6)
    return buffer.getvalue()
