"""A small DIN 5008 (Form B) letter engine on top of fpdf2.

Page geometry (A4, millimetres): letterhead 0–45, address field 45–90 at x = 20–105 (text from x = 25;
return line in the Zusatz- und Vermerkzone, recipient from y ≈ 63), information block from x = 125,
y = 50, subject at ≈ 98.5, left margin 25, right margin 20, fold marks at 105/210 and the hole mark at
148.5. Each :class:`~samplelife.orgs.Org` picks one of several letterhead styles so the senders do
not all look alike. Documents are composed by a callback; :func:`render` runs it twice when the
letter needs "Seite 1 von 2" page numbers.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import MethodReturnValue
from fpdf.fonts import FontFace

from samplelife.logos import bezier_path, draw_logo
from samplelife.orgs import RGB, Org

SPECIMEN = "SPECIMEN — fictional sample for the Ordnung demo"
GENERATOR = "Ordnung sample-life generator (scripts/make_sample_life.py)"
FONT_DIR = Path(__file__).resolve().parents[2] / "src" / "ordnung" / "drafts" / "fonts"
FAMILY = "dejavu"

TEXT: RGB = (28, 28, 30)
GREY: RGB = (92, 92, 96)
LIGHT: RGB = (150, 150, 155)
INK_BLUE: RGB = (26, 46, 128)
WHITE: RGB = (255, 255, 255)

LEFT = 25.0
RIGHT = 20.0
WIDTH = 210.0 - LEFT - RIGHT
INFO_X = 125.0


def keep_together(text: str) -> str:
    """Glue "§ 573c", "§§ 187" and "Abs. 3" with no-break spaces so they never wrap apart."""
    for token in ("§§ ", "§ ", "Abs. ", "Nr. "):
        text = text.replace(token, token[:-1] + "\u00a0")
    return text


def tint(color: RGB, strength: float) -> RGB:
    """Mix ``color`` with white; ``strength`` 1.0 = the colour itself, 0.0 = white."""
    r, g, b = (round(255 - (255 - c) * strength) for c in color)
    return (r, g, b)


@dataclass(frozen=True)
class Meta:
    """Per-document PDF settings."""

    created: datetime
    lang: str = "de"
    follow_ref: str = ""
    fold_marks: bool = True
    page_numbers_label: str = "Seite {n} von {nb}"


class _PDF(FPDF):
    def __init__(self, letter: Letter, page_format: str | tuple[float, float]) -> None:
        super().__init__(orientation="P", unit="mm", format=page_format)
        self.letter = letter

    def header(self) -> None:
        self.letter.draw_header()

    def footer(self) -> None:
        self.letter.draw_footer()


class Letter:
    """One document being composed; methods append blocks at the current position."""

    def __init__(
        self,
        org: Org,
        meta: Meta,
        *,
        number_pages: bool,
        page_format: str | tuple[float, float] = "A4",
        plain_pages: bool = False,
    ) -> None:
        self.org = org
        self.meta = meta
        self.number_pages = number_pages
        self.plain_pages = plain_pages
        self.size = org.body_size
        self.lh = self.size * 0.47
        pdf = _PDF(self, page_format)
        pdf.add_font(FAMILY, "", str(FONT_DIR / "DejaVuSans.ttf"))
        pdf.add_font(FAMILY, "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        pdf.set_title(SPECIMEN)
        pdf.set_subject(SPECIMEN)
        pdf.set_author(org.name)
        pdf.set_creator(GENERATOR)
        pdf.set_producer(GENERATOR)
        pdf.set_keywords("SPECIMEN fictional sample Ordnung demo")
        pdf.set_lang("en-GB" if meta.lang == "en" else "de-DE")
        pdf.set_creation_date(meta.created)
        pdf.set_margins(LEFT, 20, RIGHT)
        pdf.set_auto_page_break(True, margin=0 if plain_pages else 27.5)
        pdf.set_text_color(*TEXT)
        pdf.c_margin = 0
        self.pdf = pdf
        self._info_bottom = 0.0
        self._address_bottom = 0.0
        if not plain_pages:
            pdf.add_page()
            pdf.set_top_margin(27)

    # ---------------------------------------------------------------------------------------------
    # page furniture
    # ---------------------------------------------------------------------------------------------

    def draw_header(self) -> None:
        """Letterhead on page 1, a slim running head on the following pages."""
        if self.plain_pages:
            return
        pdf = self.pdf
        with pdf.local_context():
            if pdf.page_no() == 1:
                _HEADS[self.org.style](self)
                if self.meta.fold_marks and self.org.style not in ("sidebar", "cheap"):
                    self._fold_marks()
            else:
                self._follow_head()
            if self.org.style == "sidebar":
                pdf.set_fill_color(*self.org.color)
                pdf.rect(0, 0, 8, 297, style="F")
                pdf.set_fill_color(*self.org.accent)
                pdf.rect(8, 0, 1.4, 62, style="F")
        pdf.set_xy(LEFT, pdf.t_margin)

    def draw_footer(self) -> None:
        """Company/authority footer plus optional ``Seite x von y``."""
        if self.plain_pages:
            return
        pdf = self.pdf
        org = self.org
        with pdf.local_context():
            if self.number_pages:
                pdf.set_font(FAMILY, "", 7.5)
                pdf.set_text_color(*GREY)
                label = self.meta.page_numbers_label.format(n=pdf.page_no(), nb="{nb}")
                pdf.set_xy(LEFT, 271.0)
                pdf.cell(WIDTH, 4, label, align="R")
            if not org.footer:
                return
            if org.style == "cheap":
                pdf.set_font(FAMILY, "", 6.5)
                pdf.set_text_color(*LIGHT)
                pdf.set_xy(LEFT, 283)
                pdf.cell(WIDTH, 3, " ".join(org.footer[0]), align="C")
                return
            rule_color = tint(org.color, 0.55) if org.style in ("band", "modern", "sidebar") else LIGHT
            pdf.set_draw_color(*rule_color)
            pdf.set_line_width(0.25)
            pdf.line(LEFT, 275.5, 210 - RIGHT, 275.5)
            pdf.set_font(FAMILY, "", 6.2)
            pdf.set_text_color(*GREY)
            if org.style == "centered":
                for i, col in enumerate(org.footer):
                    pdf.set_xy(LEFT, 277.5 + i * 3.2)
                    pdf.cell(WIDTH, 3, "  ·  ".join(col), align="C")
                return
            size, widths = _fit_columns(pdf, org.footer)
            gap = (WIDTH - sum(widths)) / max(len(widths) - 1, 1)
            x = LEFT
            for column, width in zip(org.footer, widths, strict=True):
                for row, line in enumerate(column):
                    pdf.set_font(FAMILY, "B" if row == 0 else "", size)
                    pdf.set_xy(x, 277 + row * 2.75)
                    pdf.cell(width, 2.75, line)
                x += width + gap

    def _fold_marks(self) -> None:
        pdf = self.pdf
        pdf.set_draw_color(*LIGHT)
        pdf.set_line_width(0.2)
        pdf.line(4, 105, 8.5, 105)
        pdf.line(4, 210, 8.5, 210)
        pdf.line(4, 148.5, 10, 148.5)

    def _follow_head(self) -> None:
        pdf = self.pdf
        org = self.org
        if org.logo != "none":
            draw_logo(pdf, org.logo, LEFT, 9.5, 6.5, org.color, org.accent)
            x = LEFT + (11.5 if org.logo == "tram" else 8.5)
        else:
            x = LEFT
        pdf.set_font(FAMILY, "B", 8.2)
        pdf.set_text_color(*org.text_color)
        pdf.set_xy(x, 10.2)
        pdf.cell(80, 4, org.name)
        pdf.set_font(FAMILY, "", 7.5)
        pdf.set_text_color(*GREY)
        pdf.set_xy(110, 10.2)
        pdf.cell(80, 4, self.meta.follow_ref, align="R")
        pdf.set_draw_color(*tint(org.color, 0.45))
        pdf.set_line_width(0.2)
        pdf.line(LEFT, 18, 210 - RIGHT, 18)

    # ---------------------------------------------------------------------------------------------
    # first-page blocks
    # ---------------------------------------------------------------------------------------------

    def address(
        self, lines: Sequence[str], *, note: str | None = None, return_line: str | None = None
    ) -> None:
        """Return line and recipient in the DIN 5008 Form B address field."""
        pdf = self.pdf
        with pdf.local_context():
            if note:
                pdf.set_font(FAMILY, "B", 8)
                pdf.set_text_color(*TEXT)
                pdf.set_xy(LEFT, 52)
                pdf.cell(80, 4, note)
            pdf.set_font(FAMILY, "", 6.4)
            pdf.set_text_color(*GREY)
            sender = return_line if return_line is not None else self.org.sender_line
            pdf.set_xy(LEFT, 57.6)
            pdf.cell(80, 3, sender)
            width = pdf.get_string_width(sender)
            pdf.set_draw_color(*LIGHT)
            pdf.set_line_width(0.15)
            pdf.line(LEFT, 61, LEFT + min(width, 80), 61)
            pdf.set_font(FAMILY, "", 9.6)
            pdf.set_text_color(*TEXT)
            y = 64.0
            for line in lines:
                pdf.set_xy(LEFT, y)
                pdf.cell(80, 4.3, line)
                y += 4.3
            self._address_bottom = y

    def info(
        self,
        rows: Sequence[tuple[str, str]],
        *,
        x: float = INFO_X - 3,
        y: float = 50.0,
        label_w: float = 22.5,
        stacked: bool = False,
        title: str | None = None,
    ) -> None:
        """Information block (Ihr Zeichen, Unser Zeichen, Kundennummer, Datum …) right of the window."""
        pdf = self.pdf
        width = 210 - RIGHT - x
        with pdf.local_context():
            if title:
                pdf.set_font(FAMILY, "B", 8.2)
                pdf.set_text_color(*self.org.text_color)
                pdf.set_xy(x, y)
                pdf.cell(width, 4, title)
                y += 5.2
            for label, value in rows:
                if stacked:
                    pdf.set_font(FAMILY, "", 6.4)
                    pdf.set_text_color(*GREY)
                    pdf.set_xy(x, y)
                    pdf.cell(width, 2.8, label)
                    pdf.set_font(FAMILY, "", 8.4)
                    pdf.set_text_color(*TEXT)
                    pdf.set_xy(x, y + 2.8)
                    pdf.multi_cell(width, 3.6, value, align="L")
                    y = pdf.get_y() + 1.3
                else:
                    pdf.set_font(FAMILY, "", 6.8)
                    pdf.set_text_color(*GREY)
                    pdf.set_xy(x, y + 0.25)
                    pdf.cell(label_w, 3.6, label)
                    pdf.set_font(FAMILY, "", 8.1)
                    pdf.set_text_color(*TEXT)
                    pdf.set_xy(x + label_w, y)
                    pdf.multi_cell(width - label_w, 3.8, value, align="L")
                    y = max(pdf.get_y(), y + 3.8) + 0.35
        self._info_bottom = y

    def subject(self, text: str, *, sub: str | None = None, y: float = 98.5) -> None:
        """Bold subject line; the body starts two lines below."""
        pdf = self.pdf
        top = max(y, self._info_bottom + 5, self._address_bottom + 8)
        pdf.set_xy(LEFT, top)
        pdf.set_font(FAMILY, "B", self.size + 1.0)
        pdf.set_text_color(*TEXT)
        pdf.multi_cell(WIDTH, self.lh + 0.4, text, align="L", new_x="LMARGIN", new_y="NEXT")
        if sub:
            pdf.set_font(FAMILY, "", self.size - 0.5)
            pdf.set_text_color(*GREY)
            pdf.multi_cell(WIDTH, self.lh, sub, align="L", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(*TEXT)
        pdf.ln(self.lh * 1.3)

    def title(
        self,
        text: str,
        *,
        sub: str | None = None,
        y: float | None = None,
        size: float = 15,
        align: str = "L",
        color: RGB | None = None,
    ) -> None:
        """Large document title (contracts, certificates, payslips)."""
        pdf = self.pdf
        if y is not None:
            pdf.set_y(y)
        pdf.set_x(LEFT)
        pdf.set_font(FAMILY, "B", size)
        pdf.set_text_color(*(color or self.org.text_color))
        pdf.multi_cell(WIDTH, size * 0.5, text, align=align, new_x="LMARGIN", new_y="NEXT")
        if sub:
            pdf.ln(0.8)
            pdf.set_font(FAMILY, "", self.size)
            pdf.set_text_color(*GREY)
            pdf.multi_cell(WIDTH, self.lh, sub, align=align, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*TEXT)
        pdf.ln(self.lh)

    # ---------------------------------------------------------------------------------------------
    # body blocks
    # ---------------------------------------------------------------------------------------------

    def para(
        self,
        text: str,
        *,
        size: float | None = None,
        bold: bool = False,
        color: RGB | None = None,
        gap: float | None = None,
        align: str = "L",
        indent: float = 0.0,
        width: float | None = None,
    ) -> None:
        """A paragraph (``**bold**`` spans allowed) followed by a blank line."""
        pdf = self.pdf
        fsize = size or self.size
        pdf.set_font(FAMILY, "B" if bold else "", fsize)
        pdf.set_text_color(*(color or TEXT))
        pdf.set_x(LEFT + indent)
        text = keep_together(text)
        pdf.multi_cell(
            width or WIDTH - indent,
            fsize * 0.47,
            text,
            align=align,
            markdown="**" in text,
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.set_text_color(*TEXT)
        pdf.ln(self.lh * 0.85 if gap is None else gap)

    def small(
        self, text: str, *, gap: float | None = None, color: RGB = GREY, size: float = 7.6, align: str = "L"
    ) -> None:
        """Small print (legal notes, hints)."""
        self.para(text, size=size, color=color, gap=self.lh * 0.6 if gap is None else gap, align=align)

    def heading(
        self, text: str, *, size: float | None = None, color: RGB | None = None, gap: float = 1.0
    ) -> None:
        """Bold section heading kept together with the following two lines."""
        self.ensure_space(self.lh * 3.2)
        pdf = self.pdf
        pdf.set_font(FAMILY, "B", size or self.size + 0.3)
        pdf.set_text_color(*(color or self.org.text_color))
        pdf.set_x(LEFT)
        pdf.multi_cell(WIDTH, self.lh + 0.2, text, align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*TEXT)
        pdf.ln(gap)

    def bullets(
        self,
        items: Sequence[str],
        *,
        indent: float = 1.5,
        marker: str = "•",
        gap: float | None = None,
        size: float | None = None,
        numbered: bool = False,
    ) -> None:
        """Bulleted (or numbered) list with hanging indent."""
        pdf = self.pdf
        fsize = size or self.size
        for index, item in enumerate(items, start=1):
            self.ensure_space(self.lh * 1.2)
            label = f"{index}." if numbered else marker
            pdf.set_font(FAMILY, "", fsize)
            pdf.set_text_color(*TEXT)
            y = pdf.get_y()
            pdf.set_xy(LEFT + indent, y)
            pdf.cell(5, fsize * 0.47, label)
            pdf.set_xy(LEFT + indent + 5.5, y)
            pdf.multi_cell(
                WIDTH - indent - 5.5,
                fsize * 0.47,
                item,
                align="L",
                markdown="**" in item,
                new_x="LMARGIN",
                new_y="NEXT",
            )
            pdf.ln(0.9)
        pdf.ln(self.lh * 0.5 if gap is None else gap)

    def table(
        self,
        rows: Sequence[Sequence[str]],
        widths: Sequence[float],
        *,
        aligns: Sequence[str] | None = None,
        header: bool = True,
        bold_rows: Sequence[int] = (),
        size: float | None = None,
        borders: str = "HORIZONTAL_LINES",
        head_fill: RGB | None = None,
        head_text: RGB | None = None,
        zebra: bool = False,
        gap: float | None = None,
        padding: tuple[float, float] = (0.9, 1.3),
        indent: float = 0.0,
    ) -> None:
        """A table via fpdf2's table API (``**bold**`` spans allowed in cells)."""
        pdf = self.pdf
        fsize = size or self.size - 0.4
        count = len(rows)
        bold = {i % count for i in bold_rows}
        pdf.set_font(FAMILY, "", fsize)
        pdf.set_text_color(*TEXT)
        pdf.set_draw_color(*tint(self.org.color, 0.38))
        pdf.set_line_width(0.2)
        head_style = FontFace(
            emphasis="BOLD", color=head_text or (WHITE if head_fill else TEXT), fill_color=head_fill
        )
        old_margin = pdf.l_margin
        pdf.set_left_margin(LEFT + indent)
        pdf.set_x(LEFT + indent)
        with pdf.table(
            col_widths=tuple(widths),
            width=sum(widths),
            align="LEFT",
            text_align=tuple(aligns) if aligns else "LEFT",
            first_row_as_headings=header,
            headings_style=head_style,
            borders_layout=borders,
            line_height=fsize * 0.46,
            padding=padding,
            markdown=True,
            cell_fill_color=tint(self.org.color, 0.06) if zebra else None,
            cell_fill_mode="ROWS" if zebra else "NONE",
            v_align="TOP",
        ) as table:
            for index, values in enumerate(rows):
                row = table.row()
                style = FontFace(emphasis="BOLD") if index in bold else None
                for value in values:
                    row.cell(value, style=style)
        pdf.set_left_margin(old_margin)
        pdf.ln(self.lh * 0.9 if gap is None else gap)

    def kv(
        self,
        rows: Sequence[tuple[str, str]],
        *,
        key_w: float = 52.0,
        size: float | None = None,
        borders: str = "NONE",
        gap: float | None = None,
        bold_keys: bool = False,
        zebra: bool = False,
        indent: float = 0.0,
    ) -> None:
        """Two-column key/value table."""
        body = [(f"**{k}**" if bold_keys and k else k, v) for k, v in rows]
        self.table(
            body,
            (key_w, WIDTH - key_w - indent),
            header=False,
            size=size,
            borders=borders,
            gap=gap,
            zebra=zebra,
            padding=(0.7, 1.2),
            indent=indent,
        )

    def box(
        self,
        lines: Sequence[str],
        *,
        title: str | None = None,
        fill: RGB | None = None,
        border: RGB | None = None,
        size: float | None = None,
        width: float = WIDTH,
        gap: float | None = None,
        title_color: RGB | None = None,
        line_gap: float = 0.8,
    ) -> None:
        """Highlighted rounded box (appointments, amounts due, payment details)."""
        pdf = self.pdf
        fsize = size or self.size
        pad = 3.2
        inner = width - 2 * pad
        pdf.set_font(FAMILY, "", fsize)
        heights: list[float] = []
        for line in lines:
            pdf.set_font(FAMILY, "", fsize)
            height = pdf.multi_cell(
                inner,
                fsize * 0.47,
                line,
                align="L",
                markdown="**" in line,
                dry_run=True,
                output=MethodReturnValue.HEIGHT,
            )
            heights.append(float(height))  # type: ignore[arg-type]
        total = sum(heights) + line_gap * max(len(lines) - 1, 0) + 2 * pad - 0.6
        if title:
            total += fsize * 0.5 + 1.6
        self.ensure_space(total + 1)
        x, y = LEFT, pdf.get_y()
        with pdf.local_context():
            pdf.set_fill_color(*(fill or tint(self.org.color, 0.07)))
            pdf.set_draw_color(*(border or tint(self.org.color, 0.55)))
            pdf.set_line_width(0.3)
            pdf.rect(x, y, width, total, style="DF", round_corners=True, corner_radius=1.6)
        pdf.set_xy(x + pad, y + pad - 0.3)
        if title:
            pdf.set_font(FAMILY, "B", fsize + 0.2)
            pdf.set_text_color(*(title_color or self.org.text_color))
            pdf.cell(inner, fsize * 0.5, title)
            pdf.set_xy(x + pad, pdf.get_y() + fsize * 0.5 + 1.6)
        pdf.set_text_color(*TEXT)
        for line in lines:
            pdf.set_font(FAMILY, "", fsize)
            pdf.set_x(x + pad)
            pdf.multi_cell(
                inner, fsize * 0.47, line, align="L", markdown="**" in line, new_x="LEFT", new_y="NEXT"
            )
            pdf.set_y(pdf.get_y() + line_gap)
        pdf.set_xy(LEFT, y + total)
        pdf.ln(self.lh * 0.9 if gap is None else gap)

    def rule(self, *, color: RGB | None = None, gap: float = 2.0) -> None:
        """Thin horizontal line across the text width."""
        pdf = self.pdf
        y = pdf.get_y()
        with pdf.local_context():
            pdf.set_draw_color(*(color or tint(self.org.color, 0.4)))
            pdf.set_line_width(0.2)
            pdf.line(LEFT, y, 210 - RIGHT, y)
        pdf.ln(gap)

    def space(self, mm: float) -> None:
        """Vertical space."""
        self.pdf.ln(mm)

    def ensure_space(self, mm: float) -> None:
        """Start a new page unless ``mm`` millimetres fit on the current one."""
        if self.pdf.get_y() + mm > self.pdf.page_break_trigger:
            self.pdf.add_page()

    def new_page(self) -> None:
        """Force a page break."""
        self.pdf.add_page()

    def closing(
        self,
        greeting: str,
        *,
        org_line: str | None = None,
        signers: Sequence[tuple[str, str]] = (),
        scribble: bool = True,
        note: str | None = None,
        ia: str | None = None,
    ) -> None:
        """Complimentary close, optional hand signatures and typed names."""
        lines = 1 + greeting.count("\n") + (1 if org_line else 0) + (1 if ia else 0)
        need = self.lh * lines + (12.5 if scribble and signers else 1.0) + (8.0 if signers else 0.0) + 3.0
        self.ensure_space(need + (4.0 if note else 0.0))
        pdf = self.pdf
        self.para(greeting, gap=0.6)
        if org_line:
            self.para(org_line, gap=0.4)
        if ia:
            self.para(ia, gap=0.2)
        y = pdf.get_y()
        for index, (name, _role) in enumerate(signers):
            if scribble:
                draw_scribble(pdf, LEFT + index * 62, y + 0.8, 34, 8.5, seed=f"{self.org.key}:{name}")
        pdf.set_y(y + (11.5 if scribble and signers else 1.0))
        for index, (name, _role) in enumerate(signers):
            pdf.set_xy(LEFT + index * 62, pdf.get_y())
            pdf.set_font(FAMILY, "", self.size - 0.4)
            pdf.set_text_color(*TEXT)
            pdf.cell(60, 4, name)
        if signers:
            pdf.ln(4)
        if any(role for _n, role in signers):
            for index, (_name, role) in enumerate(signers):
                pdf.set_xy(LEFT + index * 62, pdf.get_y())
                pdf.set_font(FAMILY, "", 7.6)
                pdf.set_text_color(*GREY)
                pdf.cell(60, 3.5, role)
            pdf.ln(3.5)
        pdf.set_text_color(*TEXT)
        pdf.ln(self.lh * 0.8)
        if note:
            self.small(note)

    def signature_fields(
        self,
        left: tuple[str, str, str | None],
        right: tuple[str, str, str | None],
        *,
        stamp_left: Sequence[str] = (),
    ) -> None:
        """Two signature lines (place/date, role, optional scribble seed) as on contracts."""
        self.ensure_space(34)
        pdf = self.pdf
        y = pdf.get_y() + 2
        for index, (place_date, role, seed) in enumerate((left, right)):
            x = LEFT + index * 88
            pdf.set_font(FAMILY, "", self.size - 0.3)
            pdf.set_text_color(*TEXT)
            pdf.set_xy(x, y)
            pdf.cell(75, 4, place_date)
            if seed:
                draw_scribble(pdf, x + 6, y + 7, 40, 10, seed=seed)
            with pdf.local_context():
                pdf.set_draw_color(*GREY)
                pdf.set_line_width(0.2)
                pdf.line(x, y + 19, x + 75, y + 19)
            pdf.set_font(FAMILY, "", 7.4)
            pdf.set_text_color(*GREY)
            pdf.set_xy(x, y + 19.8)
            pdf.cell(75, 3.4, role)
        if stamp_left:
            draw_stamp(pdf, LEFT + 36, y + 5, stamp_left, color=(58, 70, 168), angle=-7)
        pdf.set_text_color(*TEXT)
        pdf.set_y(y + 27)

    def enclosures(self, items: Sequence[str], *, label: str = "Anlagen") -> None:
        """Enclosure note after the signature block: ``Anlagen: A, B`` in small type."""
        self.ensure_space(self.lh * 2)
        self.para(f"**{label}:** " + " · ".join(items), size=self.size - 0.8, gap=self.lh * 0.6)

    def hidden_text(self, text: str, *, x: float, y: float) -> None:
        """Invisible 1 pt white text (used only by the scam sample for the hidden-text detector)."""
        pdf = self.pdf
        with pdf.local_context():
            pdf.set_font(FAMILY, "", 1)
            pdf.set_text_color(255, 255, 255)
            pdf.text(x, y, text)

    def output(self) -> bytes:
        """Serialise the PDF."""
        return bytes(self.pdf.output())


def _fit_columns(pdf: FPDF, columns: Sequence[Sequence[str]]) -> tuple[float, list[float]]:
    """Largest footer font size (≤ 6.2 pt) at which the columns fit side by side with 4 mm gaps."""
    size = 6.2
    while True:
        widths = []
        for column in columns:
            width = 0.0
            for row, line in enumerate(column):
                pdf.set_font(FAMILY, "B" if row == 0 else "", size)
                width = max(width, pdf.get_string_width(line))
            widths.append(width + 0.5)
        if sum(widths) + 4 * (len(widths) - 1) <= WIDTH or size <= 4.8:
            return size, widths
        size -= 0.2


# --------------------------------------------------------------------------------------------------
# letterhead styles
# --------------------------------------------------------------------------------------------------


def _logo_width(org: Org, size: float) -> float:
    return 1.6 * size if org.logo == "tram" else (0 if org.logo == "none" else size)


def _head_band(letter: Letter) -> None:
    pdf, org = letter.pdf, letter.org
    pdf.set_fill_color(*org.color)
    pdf.rect(0, 0, 210, 27, style="F")
    pdf.set_fill_color(*org.accent)
    pdf.rect(0, 27, 210, 1.3, style="F")
    draw_logo(pdf, org.logo, LEFT, 7.2, 12.5, org.color, org.accent, on_dark=True)
    x = LEFT + _logo_width(org, 12.5) + 4.5
    pdf.set_text_color(*WHITE)
    pdf.set_font(FAMILY, "B", 19)
    pdf.set_xy(x, 8.2)
    bold, light = org.wordmark
    pdf.cell(pdf.get_string_width(bold) + 1, 9, bold)
    pdf.set_font(FAMILY, "", 11)
    pdf.set_char_spacing(1.2)
    pdf.set_xy(pdf.get_x(), 10.6)
    pdf.cell(60, 6, light)
    pdf.set_char_spacing(0)
    pdf.set_font(FAMILY, "", 8)
    pdf.set_xy(110, 9.5)
    pdf.cell(80, 4, org.tagline, align="R")
    pdf.set_font(FAMILY, "", 7)
    pdf.set_xy(110, 14.2)
    pdf.cell(80, 3.5, f"{org.web}  ·  {org.phone}", align="R")
    pdf.set_text_color(*TEXT)


def _head_classic(letter: Letter) -> None:
    pdf, org = letter.pdf, letter.org
    bold, light = org.wordmark
    pdf.set_font(FAMILY, "B", 15)
    w_bold = pdf.get_string_width(bold)
    pdf.set_font(FAMILY, "", 9.5)
    w_light = pdf.get_string_width(light)
    text_w = max(w_bold, w_light)
    x_text = 210 - RIGHT - text_w
    draw_logo(pdf, org.logo, x_text - 17, 13, 13.5, org.color, org.accent)
    pdf.set_text_color(*org.color)
    pdf.set_font(FAMILY, "B", 15)
    pdf.set_xy(x_text, 13.6)
    pdf.cell(text_w, 7, bold, align="L")
    pdf.set_font(FAMILY, "", 9.5)
    pdf.set_xy(x_text, 20.8)
    pdf.cell(text_w, 5, light, align="L")
    if org.tagline:
        pdf.set_font(FAMILY, "", 7)
        pdf.set_text_color(*GREY)
        pdf.set_xy(110, 29)
        pdf.cell(80, 3.5, org.tagline, align="R")
    pdf.set_draw_color(*org.accent)
    pdf.set_line_width(0.7)
    pdf.line(LEFT, 36.5, LEFT + 22, 36.5)
    pdf.set_draw_color(*tint(org.color, 0.35))
    pdf.set_line_width(0.2)
    pdf.line(LEFT + 22, 36.5, 210 - RIGHT, 36.5)
    pdf.set_text_color(*TEXT)


def _head_modern(letter: Letter) -> None:
    pdf, org = letter.pdf, letter.org
    size = 12.5
    draw_logo(pdf, org.logo, LEFT, 12.5, size, org.color, org.accent)
    x = LEFT + _logo_width(org, size) + 4
    bold, light = org.wordmark
    pdf.set_text_color(*org.text_color)
    if org.logo == "tram":
        pdf.set_font(FAMILY, "B", 11)
        pdf.set_xy(x, 13.2)
        pdf.cell(80, 5, light)
        pdf.set_font(FAMILY, "", 7.6)
        pdf.set_text_color(*GREY)
        pdf.set_xy(x, 18.8)
        pdf.cell(80, 4, org.tagline)
    else:
        pdf.set_font(FAMILY, "B", 16)
        pdf.set_xy(x, 12.6)
        pdf.cell(pdf.get_string_width(bold) + 1.2, 8, bold)
        pdf.set_font(FAMILY, "", 16)
        pdf.set_text_color(*(org.accent if org.key == "mustertech" else GREY))
        pdf.cell(60, 8, light)
        pdf.set_font(FAMILY, "", 7.4)
        pdf.set_text_color(*GREY)
        pdf.set_xy(x, 20.4)
        pdf.cell(80, 4, org.tagline)
    lines = [org.name, org.street, org.city, f"Telefon {org.phone}", org.web]
    if org.dept:
        lines = [*org.dept, org.street, org.city, org.web]
    pdf.set_font(FAMILY, "", 6.8)
    pdf.set_text_color(*GREY)
    for i, line in enumerate(lines):
        pdf.set_xy(130, 11.8 + i * 3.1)
        if i == 0:
            pdf.set_font(FAMILY, "B", 6.8)
        pdf.cell(60, 3.1, line, align="R")
        if i == 0:
            pdf.set_font(FAMILY, "", 6.8)
    pdf.set_fill_color(*org.color)
    pdf.rect(LEFT, 33.5, 165, 0.5, style="F")
    pdf.set_fill_color(*org.accent)
    pdf.rect(LEFT, 33.1, 18, 1.3, style="F")
    pdf.set_text_color(*TEXT)


def _head_sidebar(letter: Letter) -> None:
    pdf, org = letter.pdf, letter.org
    draw_logo(pdf, org.logo, LEFT, 12.5, 13.5, org.color, org.accent)
    x = LEFT + 18
    bold, light = org.wordmark
    pdf.set_text_color(*org.color)
    pdf.set_font(FAMILY, "B", 15)
    pdf.set_xy(x, 12.8)
    pdf.cell(90, 7, bold)
    tagline_y = 20.6
    if light:
        pdf.set_font(FAMILY, "", 11)
        pdf.set_xy(x, 19.4)
        pdf.cell(90, 5, light)
        tagline_y = 25.0
    if org.tagline:
        pdf.set_font(FAMILY, "", 7.4)
        pdf.set_text_color(*GREY)
        pdf.set_xy(x, tagline_y)
        pdf.cell(90, 3.5, org.tagline)
    for i, line in enumerate(org.dept):
        pdf.set_font(FAMILY, "B" if i == 0 else "", 8)
        pdf.set_text_color(*(org.color if i == 0 else GREY))
        pdf.set_xy(INFO_X, 14 + i * 4)
        pdf.cell(65, 4, line)
    pdf.set_text_color(*TEXT)


def _head_authority(letter: Letter) -> None:
    pdf, org = letter.pdf, letter.org
    draw_logo(pdf, org.logo, LEFT, 12, 16, org.color, org.accent)
    bold, light = org.wordmark
    pdf.set_text_color(*TEXT)
    pdf.set_font(FAMILY, "B", 16)
    pdf.set_xy(LEFT + 18, 12.6)
    pdf.cell(90, 7, bold)
    pdf.set_font(FAMILY, "", 9.2)
    pdf.set_text_color(*GREY)
    pdf.set_xy(LEFT + 18, 20)
    pdf.cell(90, 4.5, light)
    for i, line in enumerate(org.dept):
        pdf.set_font(FAMILY, "B" if i == len(org.dept) - 1 else "", 9)
        pdf.set_text_color(*(org.color if i == len(org.dept) - 1 else TEXT))
        pdf.set_xy(INFO_X, 13 + i * 4.6)
        pdf.cell(65, 4.6, line)
    pdf.set_draw_color(*org.color)
    pdf.set_line_width(0.45)
    pdf.line(LEFT, 33, 210 - RIGHT, 33)
    pdf.set_text_color(*TEXT)


def _head_plain(letter: Letter) -> None:
    pdf, org = letter.pdf, letter.org
    x = LEFT
    if org.logo != "none":
        draw_logo(pdf, org.logo, LEFT, 13, 11, org.color, org.accent)
        x = LEFT + 14.5
    bold, light = org.wordmark
    pdf.set_text_color(*(org.color if org.logo != "none" else TEXT))
    pdf.set_font(FAMILY, "B", 13.5)
    pdf.set_xy(x, 13)
    pdf.cell(pdf.get_string_width(bold) + 1.5, 6.5, bold)
    if light:
        pdf.set_font(FAMILY, "", 13.5)
        pdf.cell(60, 6.5, light)
    pdf.set_font(FAMILY, "", 7.8)
    pdf.set_text_color(*GREY)
    pdf.set_xy(x, 19.8)
    pdf.cell(100, 4, org.tagline or f"{org.street} · {org.city}")
    pdf.set_text_color(*TEXT)


def _head_centered(letter: Letter) -> None:
    pdf, org = letter.pdf, letter.org
    draw_logo(pdf, org.logo, 105 - 7.5, 9, 15, org.color, org.accent)
    bold, light = org.wordmark
    pdf.set_text_color(*org.color)
    pdf.set_font(FAMILY, "B", 12.5)
    pdf.set_char_spacing(1.6)
    pdf.set_xy(LEFT, 26.2)
    pdf.cell(WIDTH, 5.5, bold, align="C")
    pdf.set_font(FAMILY, "", 7.2)
    pdf.set_char_spacing(2.2)
    pdf.set_text_color(*org.accent)
    pdf.set_xy(LEFT, 32.2)
    pdf.cell(WIDTH, 3.5, light, align="C")
    pdf.set_char_spacing(0)
    pdf.set_draw_color(*org.accent)
    pdf.set_line_width(0.35)
    pdf.line(88, 38, 122, 38)
    pdf.set_text_color(*TEXT)


def _head_cheap(letter: Letter) -> None:
    pdf, org = letter.pdf, letter.org
    draw_logo(pdf, org.logo, 22, 10.5, 13, org.color, org.accent)
    bold, light = org.wordmark
    pdf.set_text_color(*org.color)
    pdf.set_font(FAMILY, "B", 15.5)
    pdf.set_xy(38, 11.2)
    pdf.cell(150, 7, bold)
    pdf.set_font(FAMILY, "B", 9.5)
    pdf.set_text_color(*org.accent)
    pdf.set_xy(38.6, 18.6)
    pdf.cell(150, 4.5, f"{light} • Abteilung Forderungsmanagement • Vollstreckung")
    pdf.set_fill_color(*org.accent)
    pdf.rect(20, 27.5, 172, 1.6, style="F")
    pdf.set_text_color(*TEXT)


_HEADS: dict[str, Callable[[Letter], None]] = {
    "band": _head_band,
    "classic": _head_classic,
    "modern": _head_modern,
    "sidebar": _head_sidebar,
    "authority": _head_authority,
    "plain": _head_plain,
    "centered": _head_centered,
    "cheap": _head_cheap,
}


# --------------------------------------------------------------------------------------------------
# hand-made marks
# --------------------------------------------------------------------------------------------------


def scribble_strokes(x: float, y: float, w: float, h: float, *, seed: str) -> list[list[tuple[float, float]]]:
    """Polylines of a deterministic handwritten-looking signature (looped capital, cursive loops, underline)."""
    rng = random.Random(seed)
    base = y + 0.78 * h
    small = 0.34 * h
    slant = 0.32

    def pt(px: float, py: float) -> tuple[float, float]:
        rise = (px - x) / w * 0.12 * h
        return (px + (base - py) * slant, py - rise)

    cap_w = 0.16 * w
    points = [
        pt(x, base - 0.1 * h),
        pt(x - 0.02 * w, y - 0.05 * h),
        pt(x + cap_w, y - 0.1 * h),
        pt(x + 0.45 * cap_w, base),
    ]
    points += [
        pt(x + 0.2 * cap_w, base + 0.1 * h),
        pt(x + 1.3 * cap_w, base - 0.2 * h),
        pt(x + 1.1 * cap_w, base),
    ]
    cursor = x + 1.1 * cap_w
    letters = rng.randint(6, 9)
    step = (w - 1.1 * cap_w) / letters
    for _ in range(letters):
        shape = rng.choices(("loop", "arch", "hump", "descender"), weights=(4, 2, 2, 1.5))[0]
        d = step * rng.uniform(0.75, 1.2)
        if shape == "loop":
            top = base - rng.uniform(0.75, 1.0) * h
            ctrl = [pt(cursor + 0.95 * d, top), pt(cursor - 0.15 * d, top)]
        elif shape == "arch":
            ctrl = [pt(cursor + 0.05 * d, base - 1.4 * small), pt(cursor + 0.95 * d, base - 1.4 * small)]
        elif shape == "hump":
            ctrl = [pt(cursor + 0.7 * d, base - 1.1 * small), pt(cursor + 0.1 * d, base - 0.9 * small)]
        else:
            ctrl = [pt(cursor + 0.9 * d, base + 1.6 * small), pt(cursor + 0.05 * d, base + 1.6 * small)]
        cursor += d
        points += [*ctrl, pt(cursor, base - rng.uniform(0.0, 0.15) * h)]
    tail = rng.uniform(0.85, 1.05)
    underline = [
        pt(x + 0.1 * w, base + 0.32 * h),
        pt(x + 0.45 * w, base + 0.45 * h),
        pt(x + 0.8 * w, base + 0.12 * h),
        pt(x + tail * w, base + 0.22 * h),
    ]
    return [bezier_path(points), bezier_path(underline)]


def draw_scribble(
    pdf: FPDF, x: float, y: float, w: float, h: float, *, seed: str, color: RGB = INK_BLUE
) -> None:
    """Draw :func:`scribble_strokes` in ballpoint blue."""
    stroke, underline = scribble_strokes(x, y, w, h, seed=seed)
    with pdf.local_context(stroke_cap_style="ROUND", stroke_join_style="ROUND"):
        pdf.set_draw_color(*color)
        pdf.set_line_width(0.34)
        pdf.polyline(stroke)
        pdf.set_line_width(0.26)
        pdf.polyline(underline)


def draw_stamp(pdf: FPDF, x: float, y: float, lines: Sequence[str], *, color: RGB, angle: float) -> None:
    """A rubber stamp (rounded double frame, rotated, slightly transparent)."""
    width, height = 44.0, 5.0 + 3.6 * len(lines)
    with (
        pdf.local_context(fill_opacity=0.85, stroke_opacity=0.85),
        pdf.rotation(angle, x + width / 2, y + height / 2),
    ):
        pdf.set_draw_color(*color)
        pdf.set_line_width(0.55)
        pdf.rect(x, y, width, height, round_corners=True, corner_radius=1.8)
        pdf.set_line_width(0.2)
        pdf.rect(x + 1, y + 1, width - 2, height - 2, round_corners=True, corner_radius=1.2)
        pdf.set_text_color(*color)
        for index, line in enumerate(lines):
            pdf.set_font(FAMILY, "B" if index == 0 else "", 7.4 if index == 0 else 6.4)
            pdf.set_xy(x, y + 2.3 + index * 3.6)
            pdf.cell(width, 3.4, line, align="C")


# --------------------------------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------------------------------


def render(
    org: Org,
    meta: Meta,
    compose: Callable[[Letter], None],
    *,
    page_format: str | tuple[float, float] = "A4",
    plain_pages: bool = False,
) -> tuple[bytes, int]:
    """Compose a document; re-run with page numbers if it spans more than one page."""
    first = Letter(org, meta, number_pages=False, page_format=page_format, plain_pages=plain_pages)
    compose(first)
    pages = first.pdf.pages_count
    if pages == 1 or plain_pages:
        return first.output(), pages
    second = Letter(org, meta, number_pages=True, page_format=page_format, plain_pages=plain_pages)
    compose(second)
    return second.output(), second.pdf.pages_count
