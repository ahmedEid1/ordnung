"""Simple vector logos and wordmarks drawn with fpdf2 primitives (all shapes are invented)."""

from __future__ import annotations

import math
from collections.abc import Sequence

from fpdf import FPDF

from samplelife.orgs import RGB, LogoKind

WHITE: RGB = (255, 255, 255)


def bezier_path(points: Sequence[tuple[float, float]], steps: int = 14) -> list[tuple[float, float]]:
    """Flatten a chain of cubic Bézier segments (``p0, c1, c2, p1, c1, c2, p2 …``) into a polyline."""
    path = [points[0]]
    for start in range(0, len(points) - 3, 3):
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = points[start : start + 4]
        for step in range(1, steps + 1):
            t = step / steps
            u = 1 - t
            path.append(
                (
                    u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                    u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3,
                )
            )
    return path


def _fill(pdf: FPDF, color: RGB) -> None:
    pdf.set_fill_color(*color)


def _disc(pdf: FPDF, cx: float, cy: float, r: float, style: str | None = None) -> None:
    """Circle by centre and radius (explicit, independent of fpdf2's ``circle`` conventions)."""
    pdf.ellipse(cx - r, cy - r, 2 * r, 2 * r, style=style)


def _draw(pdf: FPDF, color: RGB, width: float) -> None:
    pdf.set_draw_color(*color)
    pdf.set_line_width(width)


def draw_logo(
    pdf: FPDF, kind: LogoKind, x: float, y: float, s: float, color: RGB, accent: RGB, *, on_dark: bool = False
) -> None:
    """Draw logo ``kind`` into the ``s`` × ``s`` mm square with top-left corner ``(x, y)``."""
    main = WHITE if on_dark else color
    with pdf.local_context():
        {
            "house": _house,
            "signal": _signal,
            "pulse": _pulse,
            "bolt": _bolt,
            "shield": _shield,
            "cross": _cross,
            "wave": _wave,
            "crest": _crest,
            "book": _book,
            "grid": _grid,
            "hexagon": _hexagon,
            "bag": _bag,
            "tram": _tram,
            "star": _star,
            "bank": _bank,
            "tooth": _tooth,
            "scam": _scam,
            "none": _none,
        }[kind](pdf, x, y, s, main, accent, on_dark)


def _none(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    return None


def _house(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    _fill(pdf, accent)
    pdf.polygon(
        [
            (x - 0.04 * s, y + 0.48 * s),
            (x + 0.5 * s, y),
            (x + 1.04 * s, y + 0.48 * s),
            (x + 0.9 * s, y + 0.48 * s),
            (x + 0.5 * s, y + 0.13 * s),
            (x + 0.1 * s, y + 0.48 * s),
        ],
        style="F",
    )
    _fill(pdf, main)
    pdf.polygon(
        [
            (x + 0.14 * s, y + 0.5 * s),
            (x + 0.5 * s, y + 0.2 * s),
            (x + 0.86 * s, y + 0.5 * s),
            (x + 0.86 * s, y + s),
            (x + 0.14 * s, y + s),
        ],
        style="F",
    )
    _fill(pdf, WHITE)
    pdf.rect(x + 0.42 * s, y + 0.66 * s, 0.16 * s, 0.34 * s, style="F")
    pdf.rect(x + 0.24 * s, y + 0.56 * s, 0.12 * s, 0.12 * s, style="F")
    pdf.rect(x + 0.64 * s, y + 0.56 * s, 0.12 * s, 0.12 * s, style="F")


def _signal(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    cx, cy = x + 0.18 * s, y + 0.82 * s
    _fill(pdf, accent)
    _disc(pdf, cx, cy, 0.11 * s, style="F")
    for i, radius in enumerate((0.36 * s, 0.58 * s, 0.8 * s)):
        _draw(pdf, main if i else accent, 0.09 * s)
        pdf.arc(cx - radius, cy - radius, 2 * radius, 270, 360)


def _pulse(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    ring = WHITE if on_dark else main
    _draw(pdf, ring, 0.09 * s)
    _disc(pdf, x + 0.5 * s, y + 0.5 * s, 0.45 * s)
    _draw(pdf, ring, 0.08 * s)
    pts = [(0.12, 0.55), (0.34, 0.55), (0.42, 0.34), (0.52, 0.76), (0.6, 0.42), (0.66, 0.55), (0.88, 0.55)]
    pdf.polyline([(x + px * s, y + py * s) for px, py in pts])


def _bolt(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    _fill(pdf, main)
    pdf.rect(x, y, s, s, style="F", round_corners=True, corner_radius=0.22 * s)
    _fill(pdf, accent)
    pts = [(0.56, 0.12), (0.26, 0.56), (0.47, 0.56), (0.4, 0.9), (0.74, 0.42), (0.53, 0.42), (0.62, 0.12)]
    pdf.polygon([(x + px * s, y + py * s) for px, py in pts], style="F")


def _shield(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    outline = [(0.5, 0.0), (0.95, 0.14), (0.9, 0.58), (0.5, 1.0), (0.1, 0.58), (0.05, 0.14)]
    _fill(pdf, main)
    pdf.polygon([(x + px * s, y + py * s) for px, py in outline], style="F")
    _fill(pdf, accent)
    pdf.polygon(
        [
            (x + 0.5 * s, y + 0.1 * s),
            (x + 0.84 * s, y + 0.21 * s),
            (x + 0.8 * s, y + 0.56 * s),
            (x + 0.5 * s, y + 0.88 * s),
        ],
        style="F",
    )
    _fill(pdf, WHITE)
    pdf.rect(x + 0.2 * s, y + 0.44 * s, 0.6 * s, 0.07 * s, style="F")


def _cross(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    _fill(pdf, main)
    _disc(pdf, x + 0.5 * s, y + 0.5 * s, 0.5 * s, style="F")
    _fill(pdf, WHITE)
    pdf.rect(
        x + 0.4 * s, y + 0.2 * s, 0.2 * s, 0.6 * s, style="F", round_corners=True, corner_radius=0.03 * s
    )
    pdf.rect(
        x + 0.2 * s, y + 0.4 * s, 0.6 * s, 0.2 * s, style="F", round_corners=True, corner_radius=0.03 * s
    )
    _fill(pdf, accent)
    _disc(pdf, x + 0.88 * s, y + 0.12 * s, 0.12 * s, style="F")


def _wave(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    for row, color in enumerate((main, accent, main)):
        _draw(pdf, color, 0.09 * s)
        base = y + (0.25 + 0.25 * row) * s
        pts = [(x + i / 24 * s, base + 0.08 * s * math.sin(i / 24 * 2 * math.pi + row)) for i in range(25)]
        pdf.polyline(pts)


def _crest(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    w, h = 0.84 * s, s
    x0 = x + (s - w) / 2
    outline = [(0, 0), (1, 0), (1, 0.55), (0.5, 1.0), (0, 0.55)]
    _fill(pdf, main)
    pdf.polygon([(x0 + px * w, y + py * h) for px, py in outline], style="F")
    _fill(pdf, WHITE)
    tower = [
        (0.28, 0.72),
        (0.28, 0.3),
        (0.34, 0.3),
        (0.34, 0.22),
        (0.43, 0.22),
        (0.43, 0.3),
        (0.57, 0.3),
        (0.57, 0.22),
        (0.66, 0.22),
        (0.66, 0.3),
        (0.72, 0.3),
        (0.72, 0.72),
    ]
    pdf.polygon([(x0 + px * w, y + py * h) for px, py in tower], style="F")
    _fill(pdf, main)
    pdf.rect(x0 + 0.44 * w, y + 0.52 * h, 0.12 * w, 0.2 * h, style="F")
    _fill(pdf, accent)
    pdf.rect(x0 + 0.12 * w, y + 0.06 * h, 0.76 * w, 0.05 * h, style="F")


def _book(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    _fill(pdf, main)
    pdf.polygon(
        [(x, y + 0.2 * s), (x + 0.47 * s, y + 0.3 * s), (x + 0.47 * s, y + 0.95 * s), (x, y + 0.85 * s)],
        style="F",
    )
    pdf.polygon(
        [
            (x + s, y + 0.2 * s),
            (x + 0.53 * s, y + 0.3 * s),
            (x + 0.53 * s, y + 0.95 * s),
            (x + s, y + 0.85 * s),
        ],
        style="F",
    )
    _fill(pdf, accent)
    _disc(pdf, x + 0.5 * s, y + 0.08 * s, 0.1 * s, style="F")


def _grid(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    cell = s / 3
    pattern = ("MMA", "M.M", "AMM")
    for row, line in enumerate(pattern):
        for col, ch in enumerate(line):
            if ch == ".":
                continue
            _fill(pdf, main if ch == "M" else accent)
            pdf.rect(
                x + col * cell + 0.06 * cell,
                y + row * cell + 0.06 * cell,
                0.88 * cell,
                0.88 * cell,
                style="F",
            )


def _hexagon(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    cx, cy, r = x + s / 2, y + s / 2, s / 2
    pts = [
        (cx + r * math.cos(math.radians(60 * i + 30)), cy + r * math.sin(math.radians(60 * i + 30)))
        for i in range(6)
    ]
    _fill(pdf, main)
    pdf.polygon(pts, style="F")
    inner = [
        (
            cx + 0.55 * r * math.cos(math.radians(60 * i + 30)),
            cy + 0.55 * r * math.sin(math.radians(60 * i + 30)),
        )
        for i in range(6)
    ]
    _draw(pdf, accent, 0.1 * s)
    pdf.polygon(inner)


def _bag(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    body = WHITE if on_dark else main
    _draw(pdf, body, 0.08 * s)
    pdf.arc(x + 0.3 * s, y + 0.06 * s, 0.4 * s, 180, 360, b=0.5 * s)
    _fill(pdf, body)
    pdf.rect(
        x + 0.1 * s, y + 0.3 * s, 0.8 * s, 0.7 * s, style="F", round_corners=True, corner_radius=0.08 * s
    )
    _fill(pdf, accent)
    _disc(pdf, x + 0.5 * s, y + 0.62 * s, 0.1 * s, style="F")


def _tram(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    _fill(pdf, main)
    pdf.rect(x, y, 1.6 * s, s, style="F", round_corners=True, corner_radius=0.18 * s)
    pdf.set_text_color(*accent)
    pdf.set_font("dejavu", "B", s * 1.35)
    pdf.set_xy(x, y + 0.02 * s)
    pdf.cell(1.6 * s, 0.75 * s, "MVB", align="C")
    _fill(pdf, accent)
    pdf.rect(x + 0.18 * s, y + 0.8 * s, 1.24 * s, 0.05 * s, style="F")


def _star(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    _draw(pdf, accent, 0.05 * s)
    _disc(pdf, x + 0.5 * s, y + 0.5 * s, 0.5 * s)
    _disc(pdf, x + 0.5 * s, y + 0.5 * s, 0.42 * s)
    _fill(pdf, main)
    pdf.star(x + 0.5 * s, y + 0.5 * s, 0.14 * s, 0.34 * s, 5, rotate_degrees=-90, style="F")


def _bank(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    _fill(pdf, main)
    pdf.rect(x, y, s, s, style="F", round_corners=True, corner_radius=0.16 * s)
    _draw(pdf, WHITE, 0.11 * s)
    pdf.polyline(
        [
            (x + 0.2 * s, y + 0.78 * s),
            (x + 0.2 * s, y + 0.24 * s),
            (x + 0.5 * s, y + 0.56 * s),
            (x + 0.8 * s, y + 0.24 * s),
            (x + 0.8 * s, y + 0.78 * s),
        ]
    )
    _fill(pdf, accent)
    _disc(pdf, x + 0.8 * s, y + 0.8 * s, 0.08 * s, style="F")


def _tooth(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    _fill(pdf, main)
    pts = [
        (0.5, 0.18),
        (0.62, 0.02),
        (0.95, 0.0),
        (0.92, 0.35),
        (0.9, 0.6),
        (0.78, 0.7),
        (0.72, 1.0),
        (0.66, 0.9),
        (0.6, 0.62),
        (0.5, 0.62),
        (0.4, 0.62),
        (0.34, 0.9),
        (0.28, 1.0),
        (0.22, 0.7),
        (0.1, 0.6),
        (0.08, 0.35),
        (0.05, 0.0),
        (0.38, 0.02),
        (0.5, 0.18),
    ]
    pdf.polygon(bezier_path([(x + px * s, y + py * s) for px, py in pts]), style="F")
    _fill(pdf, accent)
    _disc(pdf, x + 0.3 * s, y + 0.22 * s, 0.07 * s, style="F")


def _scam(pdf: FPDF, x: float, y: float, s: float, main: RGB, accent: RGB, on_dark: bool) -> None:
    _fill(pdf, main)
    pdf.ellipse(x, y + 0.04 * s, 1.05 * s, 0.92 * s, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("dejavu", "B", s * 1.1)
    pdf.set_xy(x, y + 0.2 * s)
    pdf.cell(1.05 * s, 0.6 * s, "RBS", align="C")
    _draw(pdf, accent, 0.07 * s)
    pdf.line(x + 0.05 * s, y + 0.86 * s, x + 1.0 * s, y + 0.18 * s)
