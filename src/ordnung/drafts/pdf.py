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

:func:`render_nachweis` puts the letter as sent together with a summary of its proof and the proof
files (the section at the end).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pypdfium2 as pdfium
from fpdf import FPDF
from fpdf.enums import XPos, YPos

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


# --------------------------------------------------------------------------------------------------
# The "Nachweis": the letter as sent, a summary with its timeline, and the proof files
# --------------------------------------------------------------------------------------------------
#
# One PDF to keep or hand over in a dispute: a summary page (the timeline in German with English below,
# the tracking number, what each enclosure shows and does not show, and the caveat), then the letter as
# sent (enclosure 1), then each proof file (enclosure 2 …): a PDF with its own pages, anything else as
# its rendered page images, one per A4 page under a caption. The summary carries no software branding
# and proves nothing by itself: it lists what the person recorded.

NACHWEIS_MARGIN = 20.0
NACHWEIS_WIDTH = PAGE_WIDTH - 2 * NACHWEIS_MARGIN
DATE_COLUMN = 26.0
FACT_COLUMN = 48.0
MUTED = (95, 95, 95)
INK = (20, 20, 20)
CAPTION_HEIGHT = 12.0
A4_HEIGHT = 297.0


@dataclass(frozen=True)
class NachweisLine:
    """One timeline line: the day (``01.09.2026``), German and English wording, an optional detail."""

    day: str
    german: str
    english: str
    detail: str | None = None


@dataclass(frozen=True)
class NachweisFile:
    """A proof to enclose: its name in both languages, what it shows, and the original PDF or page images."""

    german: str
    english: str
    shows: str
    does_not_show: str
    pdf: bytes | None = None
    images: tuple[Path, ...] = ()


@dataclass(frozen=True)
class NachweisFacts:
    """What the summary page says besides the timeline."""

    recipient: str
    sender: str
    sent: str | None
    tracking: str | None
    created: str
    caveat_de: str
    caveat_en: str


class _SummaryPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-15)
        self.set_font(FONT, "", FOOTER_SIZE)
        self.set_text_color(*MUTED)
        self.cell(0, 4, f"Versandnachweis · Seite {self.page_no()} / page {self.page_no()}", align="R")
        self.set_text_color(*INK)


def _new_summary(draft: Draft, profile: Profile) -> _SummaryPDF:
    pdf = _SummaryPDF(orientation="P", unit="mm", format="A4")
    pdf.set_creation_date(_creation_date(draft))
    pdf.set_title(f"Versandnachweis: {draft.subject}")
    if profile.name:
        pdf.set_author(profile.name)
    pdf.set_lang("de-DE")
    pdf.add_font(FONT, "", str(FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font(FONT, "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.set_margins(NACHWEIS_MARGIN, NACHWEIS_MARGIN, NACHWEIS_MARGIN)
    pdf.set_auto_page_break(auto=True, margin=BOTTOM)
    pdf.add_page()
    return pdf


def _say(
    pdf: FPDF, text: str, *, size: float = 10.0, bold: bool = False, muted: bool = False, height: float = 5.0
) -> None:
    pdf.set_font(FONT, "B" if bold else "", size)
    pdf.set_text_color(*(MUTED if muted else INK))
    pdf.multi_cell(0, height, text, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)


def _section(pdf: FPDF, german: str, english: str) -> None:
    pdf.ln(4)
    _say(pdf, german, size=12, bold=True, height=6)
    _say(pdf, english, size=8.5, muted=True, height=4)
    pdf.ln(1.5)


def _fact(pdf: FPDF, german: str, english: str, value: str) -> None:
    top = pdf.get_y()
    pdf.set_font(FONT, "B", 9.5)
    pdf.cell(FACT_COLUMN, 5, german, new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.set_font(FONT, "", 10)
    pdf.multi_cell(NACHWEIS_WIDTH - FACT_COLUMN, 5, value, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    after = pdf.get_y()
    pdf.set_xy(NACHWEIS_MARGIN, top + 5)
    pdf.set_font(FONT, "", 7.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(FACT_COLUMN, 3.5, english, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)
    pdf.set_y(max(after, top + 8.5) + 1)


def _timeline_row(pdf: FPDF, line: NachweisLine) -> None:
    if pdf.will_page_break(14):
        pdf.add_page()
    pdf.set_font(FONT, "", 10)
    pdf.cell(DATE_COLUMN, 5, line.day, new_x=XPos.RIGHT, new_y=YPos.TOP)
    width = NACHWEIS_WIDTH - DATE_COLUMN
    pdf.set_font(FONT, "B", 10)
    pdf.multi_cell(width, 5, line.german, align="L", new_x=XPos.LEFT, new_y=YPos.NEXT)
    pdf.set_font(FONT, "", 8.5)
    pdf.set_text_color(*MUTED)
    english = f"{line.english} — {line.detail}" if line.detail else line.english
    pdf.multi_cell(width, 4, english, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(*INK)
    pdf.ln(1.5)


def _summary(
    draft: Draft,
    profile: Profile,
    facts: NachweisFacts,
    lines: list[NachweisLine],
    files: list[NachweisFile],
    letter_pages: int,
) -> bytes:
    pdf = _new_summary(draft, profile)
    _say(pdf, "Versandnachweis", size=18, bold=True, height=8)
    _say(pdf, "Proof of sending — a summary of what the sender recorded", size=9.5, muted=True)
    pdf.ln(4)
    _fact(pdf, "Schreiben", "Letter", draft.subject or "—")
    _fact(pdf, "Empfänger", "To", facts.recipient or "—")
    _fact(pdf, "Absender", "From", facts.sender or "—")
    if facts.sent:
        _fact(pdf, "Versandt", "Sent", facts.sent)
    if facts.tracking:
        _fact(pdf, "Sendungsnummer", "Tracking number", facts.tracking)

    _section(pdf, "Verlauf", "Timeline")
    for line in lines:
        _timeline_row(pdf, line)

    _section(pdf, "Anlagen", "Enclosures")
    pages = f"{letter_pages} {'Seite' if letter_pages == 1 else 'Seiten'}"
    _say(pdf, f"1. Das Schreiben wie versandt ({pages})", bold=True)
    _say(pdf, "The letter as sent", size=8.5, muted=True, height=4)
    pdf.ln(1.5)
    for number, enclosed in enumerate(files, start=2):
        if pdf.will_page_break(22):
            pdf.add_page()
        _say(pdf, f"{number}. {enclosed.german}", bold=True)
        explained = f"{enclosed.english}. Shows: {enclosed.shows} Does not show: {enclosed.does_not_show}"
        _say(pdf, explained, size=8.5, muted=True, height=4)
        pdf.ln(1.5)

    _section(pdf, "Hinweis", "Note")
    _say(pdf, facts.caveat_de, size=9.5)
    pdf.ln(1)
    _say(pdf, facts.caveat_en, size=8.5, muted=True, height=4)
    pdf.ln(3)
    made = (
        f"Erstellt am {facts.created} aus den eigenen Angaben des Absenders. "
        f"Made on {facts.created} from the sender's own records."
    )
    _say(pdf, made, size=8, muted=True, height=4)
    return bytes(pdf.output())


def _image_pages(draft: Draft, number: int, enclosed: NachweisFile) -> bytes:
    """The page images of an enclosure, each on its own A4 page under a caption."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_creation_date(_creation_date(draft))
    pdf.add_font(FONT, "", str(FONT_DIR / "DejaVuSans.ttf"))
    pdf.set_margins(NACHWEIS_MARGIN, NACHWEIS_MARGIN, NACHWEIS_MARGIN)
    pdf.set_auto_page_break(auto=False)
    box_height = A4_HEIGHT - 2 * NACHWEIS_MARGIN - CAPTION_HEIGHT
    count = len(enclosed.images)
    for index, image in enumerate(enclosed.images, start=1):
        pdf.add_page()
        pdf.set_font(FONT, "", 9)
        pdf.set_text_color(*MUTED)
        part = f" · {index}/{count}" if count > 1 else ""
        pdf.cell(0, 5, f"Anlage {number}: {enclosed.german} / {enclosed.english}{part}")
        pdf.set_text_color(*INK)
        pdf.image(
            str(image),
            x=NACHWEIS_MARGIN,
            y=NACHWEIS_MARGIN + CAPTION_HEIGHT,
            w=NACHWEIS_WIDTH,
            h=box_height,
            keep_aspect_ratio=True,
        )
    return bytes(pdf.output())


def _page_count(data: bytes) -> int:
    with PDFIUM_LOCK:
        document = pdfium.PdfDocument(data)
        try:
            return len(document)
        finally:
            document.close()


def _merge(parts: list[bytes]) -> bytes:
    """One PDF of all ``parts`` in order (PDFium, under the app-wide lock)."""
    with PDFIUM_LOCK:
        merged = pdfium.PdfDocument.new()
        try:
            for part in parts:
                source = pdfium.PdfDocument(part)
                try:
                    merged.import_pages(source)
                finally:
                    source.close()
            buffer = io.BytesIO()
            merged.save(buffer)
            return buffer.getvalue()
        finally:
            merged.close()


def render_nachweis(
    draft: Draft,
    profile: Profile,
    facts: NachweisFacts,
    lines: list[NachweisLine],
    files: list[NachweisFile],
) -> bytes:
    """The Nachweis PDF: summary, the letter as sent, then every proof file (see the section comment)."""
    letter = render(draft, profile)
    parts = [_summary(draft, profile, facts, lines, files, _page_count(letter)), letter]
    for number, enclosed in enumerate(files, start=2):
        if enclosed.pdf is not None:
            parts.append(enclosed.pdf)
        elif enclosed.images:
            parts.append(_image_pages(draft, number, enclosed))
    return _merge(parts)
