"""A compact DIN 5008 (Form B) letter renderer on fpdf2 for the benchmark documents.

Geometry (A4, mm): letterhead 0–42; return line ≈ 59 and recipient from 64 in the address field
(x = 20–105, text from the left margin); information block from x = 125, y = 50; subject ≈ 100;
footer from 272; fold marks at 105/210 and the hole mark at 148.5. Each organisation picks one of
four letterhead styles and each variant its own margins/sizes so the families do not look alike.

All visible text is dark and at least 6.5 pt; white text only appears on dark filled rectangles
(Ordnung's hidden-text detector treats white-on-white and < 3 pt text as hidden, SPEC §21) — except
in the deliberately adversarial ``Hidden`` block. Output is byte-deterministic: fixed creation date
and metadata, no randomness here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import cast

from fpdf import FPDF
from fpdf.enums import XPos, YPos

FONT_DIR = Path(__file__).resolve().parents[2] / "src" / "ordnung" / "drafts" / "fonts"
FAMILY = "dejavu"
GENERATOR = "Ordnung eval generator (evals/generate.py)"
SUBJECT = "Fiktives Testdokument für den Ordnung-Benchmark – keine echte Behörde oder Firma"

RGB = tuple[int, int, int]
TEXT: RGB = (25, 25, 28)
GREY: RGB = (88, 88, 94)
RULE: RGB = (170, 170, 176)


def luminance(color: RGB) -> float:
    r, g, b = (c / 255 for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# --------------------------------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Org:
    """A fictional sender. ``head`` lines appear in the letterhead (e.g. the Land's administration)."""

    name: str
    kind: str
    street: str
    postcode: str
    city: str
    region: str | None = None
    head: tuple[str, ...] = ()
    phone: str = ""
    email: str = ""
    web: str = ""
    bank: str = ""
    iban: str = ""
    bic: str = ""
    style: str = "authority"  # authority | band | logo | minimal
    accent: RGB = (30, 60, 120)
    monogram: str = ""
    hours: tuple[str, ...] = ()
    legal: tuple[str, ...] = ()
    country: str = ""  # printed after the city for foreign senders

    @property
    def return_line(self) -> str:
        city = f"{self.postcode} {self.city}".strip()
        return f"{self.name} · {self.street} · {city}" + (f" · {self.country}" if self.country else "")


@dataclass(frozen=True)
class Person:
    name: str
    street: str
    postcode: str
    city: str
    extra: str = ""  # e.g. "c/o" line
    country: str = ""


@dataclass(frozen=True)
class Style:
    body_pt: float = 10.0
    left: float = 25.0
    right: float = 20.0
    leading: float = 1.38  # line height as a multiple of the font size
    para_gap: float = 2.2
    info_label_pt: float = 7.3
    info_value_pt: float = 8.6
    subject_pt: float = 10.8
    align: str = "J"  # body paragraphs: J (justified) or L


# blocks ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class P:
    """A paragraph; ``**bold**`` markup is allowed (fpdf2 markdown; never use ``--`` or ``__``)."""

    text: str
    size: float | None = None
    bold: bool = False
    indent: float = 0.0
    color: RGB = TEXT
    gap: float | None = None


@dataclass(frozen=True)
class H:
    text: str
    size: float | None = None


@dataclass(frozen=True)
class Table:
    rows: tuple[tuple[str, str], ...]
    header: tuple[str, str] | None = None
    value_width: float = 38.0
    bold_rows: tuple[int, ...] = ()
    rule_before: tuple[int, ...] = ()
    size: float | None = None
    value_align: str = "R"  # "L" for key/value tables with text values


@dataclass(frozen=True)
class Box:
    """Light-grey framed box (e.g. a payment summary)."""

    lines: tuple[str, ...]
    fill: RGB = (238, 240, 243)
    bold_first: bool = True


@dataclass(frozen=True)
class Space:
    mm: float


@dataclass(frozen=True)
class Hidden:
    """ADVERSARIAL: white 1 pt text at the current position (does not advance the cursor)."""

    text: str
    size: float = 1.0


@dataclass(frozen=True)
class Sign:
    closing: str
    lines: tuple[str, ...] = ()
    signature: bool = False  # draw a pen squiggle above the name


@dataclass(frozen=True)
class PageBreak:
    pass


@dataclass(frozen=True)
class Envelope:
    """A new page showing the front of a yellow formal-service envelope (Zustellungsumschlag)."""

    sender: str
    recipient: Person
    reference: str
    note: str  # the carrier's handwritten note, e.g. "zugestellt am 17.09.2026"
    initials: str = "Kr."


Block = P | H | Table | Box | Space | Hidden | Sign | PageBreak | Envelope


@dataclass
class Letter:
    org: Org
    recipient: Person | None
    info: list[tuple[str, str]]
    subject: str
    blocks: list[Block]
    style: Style = field(default_factory=Style)
    lang: str = "de"
    subject_extra: tuple[str, ...] = ()
    created: datetime = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    title: str = ""
    salutation: str | None = None
    date_line: str | None = None  # "Musterstadt, 02.01.2026" right-aligned above the subject
    running_ref: str = ""  # reference shown in the running head of pages 2+


# --------------------------------------------------------------------------------------------------
# renderer
# --------------------------------------------------------------------------------------------------


class _PDF(FPDF):
    def __init__(self, renderer: _Renderer) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.renderer = renderer

    def header(self) -> None:
        self.renderer.draw_header()

    def footer(self) -> None:
        self.renderer.draw_footer()


class _Renderer:
    def __init__(self, letter: Letter, total_pages: int) -> None:
        self.letter = letter
        self.total = total_pages
        self.s = letter.style
        pdf = _PDF(self)
        pdf.add_font(FAMILY, "", str(FONT_DIR / "DejaVuSans.ttf"))
        pdf.add_font(FAMILY, "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        pdf.set_title(letter.title or letter.subject)
        pdf.set_subject(SUBJECT)
        pdf.set_author(letter.org.name)
        pdf.set_creator(GENERATOR)
        pdf.set_producer(GENERATOR)
        pdf.set_keywords("Ordnung benchmark fictional test document")
        pdf.set_lang("en-GB" if letter.lang == "en" else "de-DE")
        pdf.set_creation_date(letter.created)
        pdf.set_margins(self.s.left, 22, self.s.right)
        pdf.set_auto_page_break(True, margin=30)
        pdf.c_margin = 0
        self.pdf = pdf
        self.width = 210 - self.s.left - self.s.right

    # -- helpers ---------------------------------------------------------------------------------

    def font(self, size: float, bold: bool = False, color: RGB = TEXT) -> None:
        self.pdf.set_font(FAMILY, "B" if bold else "", size)
        self.pdf.set_text_color(*color)

    def lh(self, size: float) -> float:
        return size * 0.3528 * self.s.leading

    # -- page furniture --------------------------------------------------------------------------

    def draw_header(self) -> None:
        pdf = self.pdf
        if pdf.page_no() == 1:
            self.letterhead()
            return
        self.font(7.5, color=GREY)
        pdf.set_xy(self.s.left, 10)
        pdf.cell(self.width / 2, 4, self.letter.org.name)
        label = "Page" if self.letter.lang == "en" else "Seite"
        of = "of" if self.letter.lang == "en" else "von"
        pdf.set_xy(self.s.left + self.width / 2, 10)
        pdf.cell(self.width / 2, 4, f"{label} {pdf.page_no()} {of} {self.total}", align="R")
        if self.letter.running_ref:
            pdf.set_xy(self.s.left, 14)
            pdf.cell(self.width, 4, self.letter.running_ref)
        pdf.set_draw_color(*RULE)
        pdf.set_line_width(0.2)
        pdf.line(self.s.left, 19, 210 - self.s.right, 19)
        pdf.set_y(24)

    def draw_footer(self) -> None:
        pdf = self.pdf
        org = self.letter.org
        if pdf.page_no() == 1:  # fold and hole marks (DIN 5008)
            pdf.set_draw_color(*RULE)
            pdf.set_line_width(0.2)
            for y, length in ((105, 5), (148.5, 7), (210, 5)):
                pdf.line(0, y, length, y)
        if getattr(self, "_envelope_page", 0) == pdf.page_no():
            return
        columns: list[list[str]] = []
        first = [org.name, org.street, f"{org.postcode} {org.city}".strip()]
        if org.country:
            first.append(org.country)
        columns.append(first)
        contact = [line for line in (org.phone, org.email, org.web) if line]
        if contact:
            columns.append(contact)
        if org.iban:
            bank = [org.bank, f"IBAN {_group(org.iban)}"]
            if org.bic:
                bank.append(f"BIC {org.bic}")
            columns.append([b for b in bank if b])
        if org.hours:
            columns.append(list(org.hours))
        if org.legal:
            columns.append(list(org.legal))
        top = 273.0
        pdf.set_draw_color(*RULE)
        pdf.set_line_width(0.2)
        pdf.line(self.s.left, top - 1.5, 210 - self.s.right, top - 1.5)
        gap = 4.0
        size = 6.6
        while True:  # shrink the footer font until every column fits side by side
            widths = []
            for i, lines in enumerate(columns):
                w = 0.0
                for j, line in enumerate(lines[:5]):
                    self.font(size, bold=(j == 0 and i == 0), color=GREY)
                    w = max(w, pdf.get_string_width(line))
                widths.append(w)
            if sum(widths) + gap * (len(columns) - 1) <= self.width or size <= 5.0:
                break
            size -= 0.2
        spare = max(0.0, self.width - sum(widths) - gap * (len(columns) - 1))
        extra = spare / max(len(columns) - 1, 1) if len(columns) > 1 else 0.0
        x = self.s.left
        for i, lines in enumerate(columns):
            for j, line in enumerate(lines[:5]):
                self.font(size, bold=(j == 0 and i == 0), color=GREY)
                pdf.set_xy(x, top + j * 3.0)
                pdf.cell(widths[i], 3, line)
            x += widths[i] + gap + extra
        if self.total > 1:
            label = "Page" if self.letter.lang == "en" else "Seite"
            of = "of" if self.letter.lang == "en" else "von"
            self.font(7, color=GREY)
            pdf.set_xy(self.s.left, 289)
            pdf.cell(self.width, 3, f"{label} {pdf.page_no()} {of} {self.total}", align="R")

    def letterhead(self) -> None:
        pdf = self.pdf
        org = self.letter.org
        left = self.s.left
        right_edge = 210 - self.s.right
        if org.style == "band":
            assert luminance(org.accent) < 0.5, "white letterhead text needs a dark band"
            pdf.set_fill_color(*org.accent)
            pdf.rect(0, 0, 210, 21, style="F")
            self.font(15, bold=True, color=(255, 255, 255))
            pdf.set_xy(left, 6.5)
            pdf.cell(self.width, 8, org.name)
            y = 25.0
            for line in org.head:
                self.font(8, color=GREY)
                pdf.set_xy(left, y)
                pdf.cell(self.width, 3.8, line)
                y += 3.8
        elif org.style == "logo":
            assert luminance(org.accent) < 0.5
            size = 16.0
            x0 = right_edge - size
            pdf.set_fill_color(*org.accent)
            pdf.rect(x0, 11, size, size, style="F")
            self.font(10.5, bold=True, color=(255, 255, 255))
            pdf.set_xy(x0, 11 + size / 2 - 2.5)
            pdf.cell(size, 5, org.monogram or org.name[:2].upper(), align="C")
            self.font(14, bold=True, color=org.accent)
            pdf.set_xy(left, 12)
            pdf.cell(x0 - left - 4, 7, org.name)
            y = 20.0
            for line in org.head:
                self.font(8, color=GREY)
                pdf.set_xy(left, y)
                pdf.cell(x0 - left - 4, 3.8, line)
                y += 3.8
            pdf.set_draw_color(*org.accent)
            pdf.set_line_width(0.5)
            pdf.line(left, 36, right_edge, 36)
        elif org.style == "minimal":
            self.font(13, bold=True, color=org.accent)
            pdf.set_xy(left, 13)
            pdf.cell(self.width, 6, org.name, align="R")
            y = 20.0
            for line in (*org.head, f"{org.street} · {org.postcode} {org.city}".strip(" ·")):
                self.font(7.8, color=GREY)
                pdf.set_xy(left, y)
                pdf.cell(self.width, 3.6, line, align="R")
                y += 3.6
        else:  # authority: an emblem (shield) + name block, thin rule
            x, y = left, 12.0
            pdf.set_fill_color(*org.accent)
            pdf.set_draw_color(*org.accent)
            pdf.polygon([(x, y), (x + 11, y), (x + 11, y + 8), (x + 5.5, y + 13.5), (x, y + 8)], style="F")
            pdf.set_fill_color(255, 255, 255)
            pdf.rect(x + 2, y + 3.2, 7, 1.6, style="F")
            pdf.rect(x + 4.7, y + 1.5, 1.6, 8.5, style="F")
            tx = x + 15
            yy = y - 0.5
            for line in org.head[:1]:
                self.font(7.8, color=GREY)
                pdf.set_xy(tx, yy)
                pdf.cell(120, 3.6, line)
                yy += 3.8
            self.font(12.5, bold=True, color=TEXT)
            pdf.set_xy(tx, yy)
            pdf.cell(120, 6, org.name)
            yy += 6.2
            for line in org.head[1:]:
                self.font(7.8, color=GREY)
                pdf.set_xy(tx, yy)
                pdf.cell(120, 3.6, line)
                yy += 3.8
            pdf.set_draw_color(*RULE)
            pdf.set_line_width(0.25)
            pdf.line(left, 38, right_edge, 38)

    # -- first-page blocks -------------------------------------------------------------------------

    def address_and_info(self) -> float:
        pdf = self.pdf
        letter = self.letter
        left = self.s.left
        bottom = 64.0
        if letter.recipient is not None:
            avail = 125.0 - left - 4
            size = 6.6
            self.font(size, color=GREY)
            while pdf.get_string_width(letter.org.return_line) > avail and size > 5.2:
                size -= 0.2
                self.font(size, color=GREY)
            line = letter.org.return_line
            while pdf.get_string_width(line) > avail:
                line = line[:-2] + "…"
            pdf.set_xy(left, 57.5)
            pdf.cell(avail, 3, line)
            pdf.set_draw_color(*RULE)
            pdf.set_line_width(0.15)
            pdf.line(left, 61, left + min(avail, 85), 61)
            r = letter.recipient
            lines = [r.name, *([r.extra] if r.extra else []), r.street, f"{r.postcode} {r.city}".strip()]
            if r.country:
                lines.append(r.country)
            y = 64.0
            for line in lines:
                self.font(9.8)
                pdf.set_xy(left, y)
                pdf.cell(80, 4.4, line)
                y += 4.4
            bottom = y
        x = 125.0
        y = 50.0
        for label, value in letter.info:
            self.font(self.s.info_label_pt, color=GREY)
            pdf.set_xy(x, y)
            pdf.cell(65, 3.2, label)
            y += 3.2
            self.font(self.s.info_value_pt)
            pdf.set_xy(x, y)
            pdf.cell(65, 3.9, value)
            y += 4.9
        return max(bottom, y)

    # -- body --------------------------------------------------------------------------------------

    def body(self) -> None:
        pdf = self.pdf
        letter = self.letter
        s = self.s
        y = max(self.address_and_info() + 6, 97.0)
        if letter.date_line:
            self.font(s.body_pt)
            pdf.set_xy(s.left, y)
            pdf.cell(self.width, 5, letter.date_line, align="R")
            y += 7
        self.font(s.subject_pt, bold=True)
        pdf.set_xy(s.left, y)
        pdf.multi_cell(
            self.width, self.lh(s.subject_pt), letter.subject, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        for line in letter.subject_extra:
            self.font(s.body_pt - 0.6)
            pdf.multi_cell(
                self.width, self.lh(s.body_pt - 0.6), line, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT
            )
        pdf.ln(5)
        if letter.salutation:
            self.font(s.body_pt)
            pdf.multi_cell(
                self.width, self.lh(s.body_pt), letter.salutation, new_x=XPos.LMARGIN, new_y=YPos.NEXT
            )
            pdf.ln(s.para_gap)
        for block in letter.blocks:
            self.block(block)

    def block(self, block: Block) -> None:
        pdf = self.pdf
        s = self.s
        if isinstance(block, P):
            size = block.size or s.body_pt
            self.font(size, bold=block.bold, color=block.color)
            pdf.set_x(s.left + block.indent)
            pdf.multi_cell(
                self.width - block.indent,
                self.lh(size),
                block.text,
                markdown=True,
                align=s.align,
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
            pdf.ln(s.para_gap if block.gap is None else block.gap)
        elif isinstance(block, H):
            size = block.size or s.body_pt
            if pdf.get_y() > 250:
                pdf.add_page()
            self.font(size, bold=True)
            pdf.multi_cell(self.width, self.lh(size), block.text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(0.8)
        elif isinstance(block, Table):
            size = block.size or (s.body_pt - 0.8)
            row_h = self.lh(size) + 0.6
            label_w = self.width - block.value_width
            if block.header:
                self.font(size - 0.6, bold=True, color=GREY)
                pdf.cell(label_w, row_h, block.header[0])
                pdf.cell(
                    block.value_width,
                    row_h,
                    block.header[1],
                    align=block.value_align,
                    new_x=XPos.LMARGIN,
                    new_y=YPos.NEXT,
                )
                pdf.set_draw_color(*RULE)
                pdf.line(s.left, pdf.get_y(), s.left + self.width, pdf.get_y())
            for i, (label, value) in enumerate(block.rows):
                if i in block.rule_before:
                    pdf.set_draw_color(*RULE)
                    pdf.set_line_width(0.2)
                    pdf.line(s.left, pdf.get_y() + 0.3, s.left + self.width, pdf.get_y() + 0.3)
                    pdf.ln(0.8)
                self.font(size, bold=i in block.bold_rows)
                assert pdf.get_string_width(label) <= label_w - 1, f"table label too wide: {label!r}"
                assert pdf.get_string_width(value) <= block.value_width, f"table value too wide: {value!r}"
                pdf.cell(label_w, row_h, label)
                pdf.cell(
                    block.value_width,
                    row_h,
                    value,
                    align=block.value_align,
                    new_x=XPos.LMARGIN,
                    new_y=YPos.NEXT,
                )
            pdf.ln(s.para_gap + 0.5)
        elif isinstance(block, Box):
            size = s.body_pt - 0.3
            line_h = self.lh(size)
            inner = self.width - 6
            wrapped: list[tuple[bool, list[str]]] = []
            for i, line in enumerate(block.lines):
                bold = block.bold_first and i == 0
                self.font(size, bold=bold)
                parts = cast("list[str]", pdf.multi_cell(inner, line_h, line, dry_run=True, output="LINES"))
                wrapped.append((bold, list(parts)))
            height = line_h * sum(len(parts) for _, parts in wrapped) + 4
            if pdf.get_y() + height > 265:
                pdf.add_page()
            y0 = pdf.get_y()
            pdf.set_fill_color(*block.fill)
            pdf.set_draw_color(*RULE)
            pdf.set_line_width(0.25)
            pdf.rect(s.left, y0, self.width, height, style="DF")
            y = y0 + 2
            for bold, parts in wrapped:
                self.font(size, bold=bold)
                for part in parts:
                    pdf.set_xy(s.left + 3, y)
                    pdf.cell(inner, line_h, part)
                    y += line_h
            pdf.set_y(y0 + height + s.para_gap + 1)
        elif isinstance(block, Space):
            pdf.ln(block.mm)
        elif isinstance(block, Hidden):
            # White 1 pt text in its own 4 mm gap between paragraphs: invisible on paper, but on a separate
            # text line so it never interleaves with the visible lines around it.
            y = pdf.get_y()
            pdf.set_font(FAMILY, "", block.size)
            pdf.set_text_color(255, 255, 255)
            pdf.text(s.left, y + 1.6, block.text)
            pdf.set_xy(s.left, y + 4.0)
        elif isinstance(block, Sign):
            if pdf.get_y() > 245:
                pdf.add_page()
            self.font(s.body_pt)
            pdf.multi_cell(self.width, self.lh(s.body_pt), block.closing, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            if block.signature:
                x, y = s.left + 2, pdf.get_y() + 2
                pdf.set_draw_color(26, 46, 128)
                pdf.set_line_width(0.45)
                pts = [
                    (x, y + 6),
                    (x + 4, y + 1),
                    (x + 7, y + 7),
                    (x + 11, y + 2),
                    (x + 15, y + 6),
                    (x + 24, y + 3),
                ]
                for a, b in pairwise(pts):
                    pdf.line(a[0], a[1], b[0], b[1])
                pdf.ln(10)
            else:
                pdf.ln(3)
            for line in block.lines:
                self.font(s.body_pt)
                pdf.multi_cell(self.width, self.lh(s.body_pt), line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(s.para_gap)
        elif isinstance(block, PageBreak):
            pdf.add_page()
        elif isinstance(block, Envelope):
            self.envelope(block)
        else:  # pragma: no cover
            raise TypeError(block)

    def envelope(self, env: Envelope) -> None:
        pdf = self.pdf
        pdf.add_page()
        self._envelope_page = pdf.page_no()
        self.font(8, color=GREY)
        pdf.set_xy(20, 26)
        pdf.cell(170, 4, "Kopie / Scan: Vorderseite des Briefumschlags (Zustellungsumschlag)")
        x0, y0, w, h = 20.0, 34.0, 170.0, 112.0
        pdf.set_fill_color(250, 214, 74)
        pdf.set_draw_color(150, 120, 30)
        pdf.set_line_width(0.4)
        pdf.rect(x0, y0, w, h, style="DF")
        self.font(11, bold=True)
        pdf.set_xy(x0 + 6, y0 + 6)
        pdf.cell(80, 5, "Förmliche Zustellung")
        self.font(7.5)
        pdf.set_xy(x0 + 6, y0 + 12)
        pdf.cell(80, 3.5, "Zustellungsauftrag – bitte sofort vorlegen")
        pdf.set_xy(x0 + 6, y0 + 16)
        pdf.cell(80, 3.5, f"Absender: {_fit(env.sender, 70)}")
        pdf.set_xy(x0 + 6, y0 + 20)
        pdf.cell(80, 3.5, f"Aktenzeichen: {env.reference}")
        # window with the recipient
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(x0 + 6, y0 + 32, 88, 36, style="DF")
        y = y0 + 38
        r = env.recipient
        for line in (r.name, r.street, f"{r.postcode} {r.city}"):
            self.font(10)
            pdf.set_xy(x0 + 10, y)
            pdf.cell(80, 4.5, line)
            y += 4.8
        # carrier's box
        bx, by = x0 + 104, y0 + 32
        pdf.set_fill_color(255, 244, 196)
        pdf.rect(bx, by, 60, 56, style="DF")
        self.font(7.2)
        for i, line in enumerate(
            (
                "Vom Zusteller auszufüllen:",
                "Bei der Zustellung ist auf der",
                "Sendung das Datum der",
                "Zustellung zu vermerken.",
            )
        ):
            pdf.set_xy(bx + 3, by + 3 + i * 3.4)
            pdf.cell(55, 3.2, line)
        with pdf.rotation(4, bx + 30, by + 36):
            self.font(12.5, color=(26, 46, 128))
            pdf.set_xy(bx + 3, by + 22)
            pdf.cell(56, 6, env.note)
            self.font(11, color=(26, 46, 128))
            pdf.set_xy(bx + 20, by + 32)
            pdf.cell(30, 6, env.initials)
        # postage imprint
        pdf.set_draw_color(60, 60, 60)
        pdf.rect(x0 + w - 36, y0 + 6, 30, 16)
        self.font(6.8)
        pdf.set_xy(x0 + w - 35, y0 + 9)
        pdf.cell(28, 3, "Entgelt bezahlt", align="C")
        pdf.set_xy(x0 + w - 35, y0 + 13)
        pdf.cell(28, 3, "Postzustellung", align="C")
        self.font(7.5, color=GREY)
        pdf.set_xy(x0 + 6, y0 + h - 12)
        pdf.cell(150, 3.5, "Zustellungsurkunde wird an den Absender zurückgesandt (§ 182 ZPO).")
        pdf.set_y(y0 + h + 8)

    def render(self) -> bytes:
        self.pdf.add_page()
        self.body()
        return bytes(self.pdf.output())


def _group(value: str) -> str:
    compact = value.replace(" ", "")
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def _fit(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_letter(letter: Letter) -> tuple[bytes, int]:
    """Render twice when needed so "Seite n von N" is right; returns ``(pdf bytes, page count)``."""
    first = _Renderer(letter, total_pages=1)
    data = first.render()
    pages = first.pdf.page_no()
    if pages > 1:
        second = _Renderer(letter, total_pages=pages)
        data = second.render()
        assert second.pdf.page_no() == pages
    return data, pages
