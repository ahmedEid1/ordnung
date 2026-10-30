"""The evaluation's charts as hand-written SVG (standard library only): byte-identical on every build.

Every chart comes in a wide layout (740 px, for the README and the report on a computer) and a narrow one (320 px,
for a phone: panels stacked, text at 14 px so it stays at 12 px or more on a 288 px column), in light and dark
(the committed files) and with CSS variables (inlined in the report page, which sets them per theme).

Rules, for every chart: dots with intervals for rates (bars never; an axis may start above 0, at the lower interval
end rounded down to 10, and its range is printed); one row order, the page's (``presentation.json``'s ``order``);
each condition's colour *and* shape, and its name on every row; text in text colours only; a ``<title>`` and a
``<desc>`` naming every value, a ``<title>`` on every mark (the native tooltip) and a table with the same numbers
(:func:`table`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from xml.sax.saxutils import escape

from evals.present import fmt, palette

#: The charts, in the order the report shows them.
NAMES = ("held-out", "timeline", "differences", "risk-coverage", "cost")
#: Committed as ``docs/assets/eval-<name>-{light,dark}.svg`` (``docs/evals.md`` shows each; the README the first).
COMMITTED = NAMES
WIDE, NARROW = 740, 320
#: The protocol of each split, in a few words, for the timeline.
SPLIT_SHORT = {
    "dev": "prompts tuned on it",
    "test": "iterated on",
    "holdout": "held out, code fixed after",
    "holdout2": "held out, code fixed after",
    "holdout3": "frozen code, blind labels",
    "holdout4": "final run: not yet written, to be pre-registered",
}


def _attr(value: float) -> str:
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


class Canvas:
    """One SVG document: its colours (a theme, or CSS variables) and its parts, in drawing order."""

    def __init__(self, width: int, height: int, theme: str, ident: str, title: str, description: str) -> None:
        self.width, self.height = width, height
        self.colours = palette.CSS if theme == "css" else palette.THEMES[theme]
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} '
            f'{height}" role="img" aria-labelledby="{ident}-t {ident}-d" font-family="{palette.FONT}">',
            f'<title id="{ident}-t">{escape(title)}</title>',
            f'<desc id="{ident}-d">{escape(description)}</desc>',
            f'<rect width="{width}" height="{height}" style="fill:{self.colours["surface"]}"/>',
        ]

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        size: float = 12,
        role: str = "text",
        anchor: str = "start",
        weight: int = 400,
    ) -> None:
        self.parts.append(
            f'<text x="{_attr(x)}" y="{_attr(y)}" style="fill:{self.colours[role]}" font-size="{_attr(size)}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{escape(value)}</text>'
        )

    def lines(
        self, x: float, y: float, values: Sequence[str], *, size: float, gap: float, **kwargs: Any
    ) -> float:
        """Several lines of text from ``y`` down; returns the next free baseline."""
        for value in values:
            self.text(x, y, value, size=size, **kwargs)
            y += gap
        return y

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        role: str = "grid",
        width: float = 1,
        cap: bool = False,
    ) -> None:
        extra = ";stroke-linecap:round" if cap else ""
        self.parts.append(
            f'<line x1="{_attr(x1)}" y1="{_attr(y1)}" x2="{_attr(x2)}" y2="{_attr(y2)}" '
            f'style="stroke:{self.colours[role]};stroke-width:{_attr(width)}{extra}"/>'
        )

    def path(self, points: Sequence[tuple[float, float]], role: str) -> None:
        commands = " ".join(
            f"{'M' if i == 0 else 'L'}{_attr(x)},{_attr(y)}" for i, (x, y) in enumerate(points)
        )
        self.parts.append(
            f'<path d="{commands}" style="fill:none;stroke:{self.colours[role]};stroke-width:2;'
            'stroke-linejoin:round"/>'
        )

    def marker(self, condition: str, x: float, y: float, tip: str, *, r: float = 5.5) -> None:
        """The condition's shape in its colour, with a 2 px ring of the surface and a tooltip."""
        style = f'style="fill:{self.colours[condition]};stroke:{self.colours["surface"]};stroke-width:2"'
        title = f"<title>{escape(tip)}</title>"
        shape = palette.SHAPES[condition]
        if shape == "circle":
            self.parts.append(
                f'<circle cx="{_attr(x)}" cy="{_attr(y)}" r="{_attr(r)}" {style}>{title}</circle>'
            )
        elif shape == "square":
            side = r * 1.75
            self.parts.append(
                f'<rect x="{_attr(x - side / 2)}" y="{_attr(y - side / 2)}" width="{_attr(side)}" '
                f'height="{_attr(side)}" rx="1" {style}>{title}</rect>'
            )
        else:
            d = r * (1.4 if shape == "diamond" else 1.35)
            corners = (
                [(x, y - d), (x + d, y), (x, y + d), (x - d, y)]
                if shape == "diamond"
                else [(x, y - d), (x + d, y + d * 0.8), (x - d, y + d * 0.8)]
            )
            joined = " ".join(f"{_attr(px)},{_attr(py)}" for px, py in corners)
            self.parts.append(f'<polygon points="{joined}" {style}>{title}</polygon>')

    def ring(
        self, x: float, y: float, tip: str, *, r: float = 3.5, role: str = "text2", filled: bool = False
    ) -> None:
        fill = self.colours[role] if filled else "none"
        self.parts.append(
            f'<circle cx="{_attr(x)}" cy="{_attr(y)}" r="{_attr(r)}" style="fill:{fill};stroke:{self.colours[role]};'
            f'stroke-width:1.5"><title>{escape(tip)}</title></circle>'
        )

    def render(self) -> str:
        return "\n".join([*self.parts, "</svg>"]) + "\n"


def _wrap(value: str, width: int) -> list[str]:
    """``value`` in lines of at most ``width`` characters, broken at spaces."""
    lines: list[str] = []
    words: list[str] = []
    for word in value.split():
        if word == "%" and words:  # "95 %" stays on one line
            words[-1] += " %"
        else:
            words.append(word)
    for word in words:
        if lines and len(lines[-1]) + 1 + len(word) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def _floor(value: float, step: float) -> float:
    return math.floor(round(value / step, 9)) * step


def _ceil(value: float, step: float) -> float:
    return math.ceil(round(value / step, 9)) * step


def _percent(value: float) -> str:
    return f"{value * 100:.0f} %"


def _signed_points(value: float) -> str:
    return "0" if abs(value) < 1e-9 else f"{value * 100:+.0f}".replace("-", fmt.MINUS)


def _dollars(value: float) -> str:
    return f"${value:.2f}"


def _label(condition: str) -> str:
    return palette.LABELS[condition]


def _headline(doc: Mapping[str, Any]) -> Mapping[str, Any]:
    headline: Mapping[str, Any] = doc["headline"]
    return headline


def _subtitle(doc: Mapping[str, Any]) -> str:
    headline = _headline(doc)
    return (
        f"{headline['items']} deadlines in {headline['letters']} synthetic letters · {len(headline['splits'])} "
        f"held-out splits, each as recorded once · {doc['model']}"
    )


# --------------------------------------------------------------------------------------------------
# A panel of dots with intervals (the hero, the differences and the cost)
# --------------------------------------------------------------------------------------------------


class Row:
    """One condition's row in a dot panel: its value, interval, the text in the value column and the tooltip."""

    def __init__(
        self,
        condition: str,
        value: float,
        interval: tuple[float, float] | None,
        shown: str,
        tip: str,
        rings: Sequence[tuple[float, str]] = (),
    ) -> None:
        self.condition, self.value, self.interval, self.shown, self.tip, self.rings = (
            condition,
            value,
            interval,
            shown,
            tip,
            rings,
        )


#: Tick steps an axis may use, finest first: the finest whose labels stay apart is taken.
_STEPS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5)


def ticks(low: float, high: float, pixels: float, gap: float) -> list[float]:
    """The ticks of an axis from ``low`` to ``high`` drawn ``pixels`` wide, at least ``gap`` pixels apart."""
    span = high - low
    step = next((s for s in _STEPS if s / span * pixels >= gap), span)
    first = math.ceil(round(low / step, 9))
    last = math.floor(round(high / step, 9))
    return [round(step * i, 9) for i in range(first, last + 1)]


class Panel:
    """A dot panel: its heading, axis range, how a tick is written, its rows and whether it has a zero line."""

    def __init__(
        self,
        heading: str,
        low: float,
        high: float,
        tick: Callable[[float], str],
        rows: Sequence[Row],
        zero: bool = False,
    ) -> None:
        self.heading, self.low, self.high, self.tick, self.rows, self.zero = (
            heading,
            low,
            high,
            tick,
            rows,
            zero,
        )

    def x(self, value: float, x0: float, x1: float) -> float:
        return x0 + (value - self.low) / (self.high - self.low) * (x1 - x0)


def _draw_rows(
    canvas: Canvas, panel: Panel, x0: float, x1: float, ys: Sequence[float], axis_y: float, size: float
) -> None:
    for value in ticks(panel.low, panel.high, x1 - x0, size * 4.2):
        x = panel.x(value, x0, x1)
        canvas.line(x, ys[0] - 14, x, axis_y - size - 4, role="grid")
        canvas.text(x, axis_y, panel.tick(value), size=size, role="text2", anchor="middle")
    if panel.zero:
        x = panel.x(0.0, x0, x1)
        canvas.line(x, ys[0] - 16, x, axis_y - size - 4, role="axis", width=1.5)
    for row, y in zip(panel.rows, ys, strict=True):
        for ring_value, ring_tip in row.rings:
            canvas.ring(panel.x(ring_value, x0, x1), y, ring_tip)
        if row.interval is not None:
            low, high = row.interval
            canvas.line(
                panel.x(low, x0, x1), y, panel.x(high, x0, x1), y, role=row.condition, width=2, cap=True
            )
        canvas.marker(row.condition, panel.x(row.value, x0, x1), y, row.tip)


def _dot_chart(
    ident: str,
    theme: str,
    narrow: bool,
    title: str,
    subtitle: str,
    description: str,
    panels: Sequence[Panel],
    footnote: str,
) -> str:
    rows = len(panels[0].rows)
    if not narrow:
        sub = _wrap(subtitle, 112)
        top, gap = 104 + 17 * (len(sub) - 1), 34
        height = top + gap * (rows - 1) + 76
        canvas = Canvas(WIDE, height, theme, ident, title, description)
        canvas.text(16, 26, title, size=15, weight=600)
        canvas.lines(16, 46, sub, size=12, gap=17, role="text2")
        ys = [top + gap * i for i in range(rows)]
        axis_y = ys[-1] + 30
        for row, y in zip(panels[0].rows, ys, strict=True):
            canvas.marker(row.condition, 22, y, _label(row.condition))
            canvas.text(
                34, y + 4.5, _label(row.condition), size=13, weight=600 if row.condition == "ordnung" else 400
            )
        spans = (
            [(190.0, 440.0, 508.0), (560.0, 660.0, 728.0)] if len(panels) == 2 else [(190.0, 600.0, 728.0)]
        )
        for panel, (x0, x1, value_x) in zip(panels, spans, strict=True):
            canvas.text(x0, top - 30, panel.heading, size=12, weight=600)
            _draw_rows(canvas, panel, x0, x1, ys, axis_y, 11)
            for row, y in zip(panel.rows, ys, strict=True):
                canvas.text(value_x, y + 4.5, row.shown, size=12, anchor="end")
        canvas.text(16, height - 12, footnote, size=11, role="text2")
        return canvas.render()
    size, gap = 14.0, 46
    head = _wrap(subtitle, 38)
    title_lines = _wrap(title, 32)
    top_y = 24.0
    blocks = []
    y_after_head = 24 + 22 * len(title_lines) + 19 * len(head) + 8
    cursor = y_after_head
    for panel in panels:
        heading_y = cursor + 18
        first = heading_y + 30
        ys = [first + gap * i + 18 for i in range(rows)]
        axis_y = ys[-1] + 30
        blocks.append((panel, heading_y, ys, axis_y))
        cursor = axis_y + 14
    notes = _wrap(footnote, 38)
    height = int(cursor + 19 * len(notes) + 10)
    canvas = Canvas(NARROW, height, theme, ident, title, description)
    top_y = canvas.lines(12, top_y, title_lines, size=16, gap=22, weight=600)
    canvas.lines(12, top_y - 3, head, size=size, gap=19, role="text2")
    for panel, heading_y, ys, axis_y in blocks:
        canvas.text(12, heading_y, panel.heading, size=size, weight=600)
        for row, row_y in zip(panel.rows, ys, strict=True):
            canvas.marker(row.condition, 18, row_y - 22, _label(row.condition))
            canvas.text(
                30,
                row_y - 17,
                _label(row.condition),
                size=size,
                weight=600 if row.condition == "ordnung" else 400,
            )
        _draw_rows(canvas, panel, 24, 226, ys, axis_y, size)
        for row, row_y in zip(panel.rows, ys, strict=True):
            canvas.text(308, row_y + 5, row.shown, size=size, anchor="end")
    canvas.lines(12, cursor + 12, notes, size=size, gap=19, role="text2")
    return canvas.render()


# --------------------------------------------------------------------------------------------------
# 1. The hero: exact dates and harmful ones, per condition
# --------------------------------------------------------------------------------------------------


def _hero_parts(doc: Mapping[str, Any]) -> tuple[list[str], list[list[str]], str]:
    headline = _headline(doc)
    header = ["Condition", "Exactly right", "Share", "95 % CI", "Late", "Missed", "Early", "Late or missed"]
    rows, said = [], []
    for condition in doc["order"]:
        c = headline["conditions"][condition]
        exact, harmful = c["exact"], c["harmful"]
        rows.append(
            [
                _label(condition),
                fmt.of(exact),
                fmt.pct(exact["value"]),
                fmt.ci(exact["ci"]),
                str(c["late"]["k"]),
                str(c["missed"]["k"]),
                str(c["early"]["k"]),
                fmt.of(harmful),
            ]
        )
        said.append(
            f"{_label(condition)}: {fmt.of(exact)} exactly right ({fmt.pct(exact['value'])}, 95 % CI "
            f"{fmt.ci(exact['ci'])}); {c['late']['k']} late, {c['missed']['k']} missed, {c['early']['k']} early: "
            f"{fmt.of(harmful)} late or missed"
        )
    description = (
        f"Dot plot of {headline['items']} held-out deadlines, with 95 % Clopper–Pearson intervals. "
        + "; ".join(said)
        + "."
    )
    return header, rows, description


def _hero(doc: Mapping[str, Any], theme: str, narrow: bool, ident: str) -> str:
    headline = _headline(doc)
    _, _, description = _hero_parts(doc)
    exact_rows, harm_rows = [], []
    lowest = 1.0
    highest_harm = 0.0
    for condition in doc["order"]:
        c = headline["conditions"][condition]
        exact, harmful = c["exact"], c["harmful"]
        rings = [
            (
                headline["by_split"][split]["conditions"][condition]["exact"]["value"],
                f"{_label(condition)}, {split} alone: "
                f"{fmt.of(headline['by_split'][split]['conditions'][condition]['exact'])}",
            )
            for split in headline["splits"]
        ]
        lowest = min([lowest, exact["ci"][0], *(value for value, _ in rings)])
        highest_harm = max(highest_harm, harmful["ci"][1])
        exact_rows.append(
            Row(
                condition,
                exact["value"],
                (exact["ci"][0], exact["ci"][1]),
                fmt.pct(exact["value"]),
                f"{_label(condition)}: {fmt.of(exact)} exactly right ({fmt.pct(exact['value'])}), 95 % CI "
                f"{fmt.ci(exact['ci'])}",
                rings,
            )
        )
        harm_rows.append(
            Row(
                condition,
                harmful["value"],
                (harmful["ci"][0], harmful["ci"][1]),
                fmt.of(harmful),
                f"{_label(condition)}: {fmt.of(harmful)} late or missed ({fmt.pct(harmful['value'])}), 95 % CI "
                f"{fmt.ci(harmful['ci'])}",
            )
        )
    low = min(_floor(lowest, 0.1), 0.9)
    high_harm = max(_ceil(highest_harm, 0.05), 0.05)
    panels = [
        Panel("Exact date right", low, 1.0, _percent, exact_rows),
        Panel("Late or missed (harmful)", 0.0, high_harm, _percent, harm_rows),
    ]
    return _dot_chart(
        ident,
        theme,
        narrow,
        "Held-out deadlines, read once: exact date and harm",
        _subtitle(doc) + " · 95 % CI (Clopper–Pearson)",
        description,
        panels,
        "Hollow rings: each held-out split alone. Harmful: the person would act too late, or never.",
    )


# --------------------------------------------------------------------------------------------------
# 2. The timeline: what was held out, and when
# --------------------------------------------------------------------------------------------------


def _timeline_parts(doc: Mapping[str, Any]) -> tuple[list[str], list[list[str]], str]:
    header = [
        "Split",
        "Recorded",
        "Letters (photos, adversarial)",
        "Dated deadlines",
        "Protocol",
        "Ordnung, as recorded",
    ]
    rows, said = [], []
    for split in doc["splits"]:
        recorded = split["recorded"] or "not yet"
        letters = (
            f"{split['entries']} ({split['photos']}, {split['adversarial']})"
            if split["recorded"]
            else "not yet"
        )
        deadlines = str(split["scored_items"]) if split["recorded"] else "not yet"
        score = fmt.of(split["ordnung"]) if split.get("ordnung") else "not a held-out number"
        short = SPLIT_SHORT.get(split["split"], split["role"])
        rows.append([split["split"], recorded, letters, deadlines, short, score])
        said.append(
            f"{split['split']}: {short}; recorded {recorded}; letters (photos, adversarial) {letters}; dated "
            f"deadlines {deadlines}; Ordnung {score}"
        )
    description = (
        "Timeline of the benchmark's splits, in the order they were written. " + "; ".join(said) + "."
    )
    return header, rows, description


def _timeline(doc: Mapping[str, Any], theme: str, narrow: bool, ident: str) -> str:
    _, rows, description = _timeline_parts(doc)
    splits = doc["splits"]
    title = "What was held out, and when"
    subtitle = "Each split in the order it was written; Ordnung's exact dates where it was held out"

    def tip(split: Mapping[str, Any], row: Sequence[str]) -> str:
        return f"{row[0]}: {row[4]}; recorded {row[1]}; Ordnung {row[5]}"

    if not narrow:
        step = (WIDE - 120) / max(len(splits) - 1, 1)
        height = 226
        canvas = Canvas(WIDE, height, theme, ident, title, description)
        canvas.text(16, 26, title, size=15, weight=600)
        canvas.text(16, 46, subtitle, size=12, role="text2")
        y: float = 88
        canvas.line(60, y, 60 + step * (len(splits) - 1), y, role="axis", width=2)
        for i, (split, row) in enumerate(zip(splits, rows, strict=True)):
            x = 60 + step * i
            canvas.ring(x, y, tip(split, row), r=7, role="text", filled=bool(split.get("ordnung")))
            canvas.text(x, y + 30, row[0], size=13, weight=600, anchor="middle")
            canvas.text(x, y + 47, row[1], size=11, role="text2", anchor="middle")
            below = canvas.lines(x, y + 64, _wrap(row[4], 18), size=11, gap=15, role="text2", anchor="middle")
            if split.get("ordnung"):
                canvas.text(x, below + 2, f"Ordnung {row[5]}", size=11, anchor="middle", weight=600)
        canvas.text(
            16,
            height - 10,
            "Filled: held out, recorded once. Hollow: tuned, iterated on, or not yet run.",
            size=11,
            role="text2",
        )
        return canvas.render()
    gap = 76
    title_lines, head = _wrap(title, 32), _wrap(subtitle, 38)
    top = 24 + 22 * len(title_lines) + 19 * len(head) + 20
    notes = _wrap("Filled: held out, recorded once. Hollow: tuned, iterated on, or not yet run.", 38)
    height = int(top + gap * len(splits) + 19 * len(notes))
    canvas = Canvas(NARROW, height, theme, ident, title, description)
    y = canvas.lines(12, 24, title_lines, size=16, gap=22, weight=600)
    canvas.lines(12, y - 3, head, size=14, gap=19, role="text2")
    canvas.line(20, top, 20, top + gap * (len(splits) - 1), role="axis", width=2)
    for i, (split, row) in enumerate(zip(splits, rows, strict=True)):
        y = top + gap * i
        canvas.ring(20, y, tip(split, row), r=7, role="text", filled=bool(split.get("ordnung")))
        canvas.text(40, y + 5, f"{row[0]} · {row[1]}", size=14, weight=600)
        canvas.text(40, y + 25, row[4], size=14, role="text2")
        if split.get("ordnung"):
            canvas.text(40, y + 45, f"Ordnung {row[5]}", size=14)
    canvas.lines(12, top + gap * len(splits) - 10, notes, size=14, gap=19, role="text2")
    return canvas.render()


# --------------------------------------------------------------------------------------------------
# 3. The paired differences (a forest plot)
# --------------------------------------------------------------------------------------------------


def _baselines(doc: Mapping[str, Any]) -> list[str]:
    return [c for c in doc["order"] if c != "ordnung"]


def _pair(doc: Mapping[str, Any], family: str, baseline: str) -> Mapping[str, Any]:
    pair: Mapping[str, Any] = _headline(doc)["paired"][family][f"ordnung-vs-{baseline}"]
    return pair


def _differences_parts(doc: Mapping[str, Any]) -> tuple[list[str], list[list[str]], str]:
    header = [
        "Ordnung minus",
        "Exact: points [95 % CI]",
        "Exact: discordant",
        "Exact: p",
        "Harmful: points [95 % CI]",
        "Harmful: discordant",
        "Harmful: p",
    ]
    rows, said = [], []
    for baseline in _baselines(doc):
        cells = [_label(baseline)]
        parts = []
        for family, name in (("accuracy", "exact dates"), ("harmful", "harmful dates")):
            pair = _pair(doc, family, baseline)
            low, high = pair["bootstrap"]
            shown = f"{fmt.points(pair['diff'])} [{fmt.points(low)}, {fmt.points(high)}]"
            discordant = f"{pair['b']} vs {pair['c']}"
            p_text = fmt.p_value(pair["exact_p"])
            cells += [shown, discordant, p_text]
            parts.append(f"{name} {shown} points, {discordant} discordant, exact p {p_text}")
        rows.append(cells)
        said.append(f"Ordnung minus {_label(baseline)}: " + "; ".join(parts))
    description = (
        "Forest plot of paired differences on the same held-out deadlines, Ordnung minus each baseline, in "
        "percentage points with 95 % paired letter-cluster bootstrap intervals. " + ". ".join(said) + "."
    )
    return header, rows, description


def _differences(doc: Mapping[str, Any], theme: str, narrow: bool, ident: str) -> str:
    _, _, description = _differences_parts(doc)
    panels = []
    for family, heading in (
        ("accuracy", "Exact dates: Ordnung minus"),
        ("harmful", "Harmful dates: Ordnung minus"),
    ):
        rows = []
        lows, highs = [0.0], [0.0]
        for baseline in _baselines(doc):
            pair = _pair(doc, family, baseline)
            low, high = pair["bootstrap"]
            lows.append(low)
            highs.append(high)
            rows.append(
                Row(
                    baseline,
                    pair["diff"],
                    (low, high),
                    fmt.points(pair["diff"]),
                    f"Ordnung minus {_label(baseline)}, {heading.split(':')[0].lower()}: {fmt.points(pair['diff'])} "
                    f"points, 95 % CI {fmt.interval_points((low, high))}",
                )
            )
        low_axis, high_axis = _floor(min(lows), 0.05), _ceil(max(highs), 0.05)
        panels.append(Panel(heading, low_axis, high_axis, _signed_points, rows, zero=True))
    return _dot_chart(
        ident,
        theme,
        narrow,
        "Is Ordnung clearly better than each baseline?",
        _subtitle(doc) + " · points, 95 % letter-cluster bootstrap",
        description,
        panels,
        "Right of the line: Ordnung has more exact dates, or more harmful ones. An interval across it is no "
        "clear difference.",
    )


# --------------------------------------------------------------------------------------------------
# 4. Risk and coverage: does "Please check" catch the wrong dates?
# --------------------------------------------------------------------------------------------------

_SHOWN = (
    ("none", "No flag"),
    ("second_look", "No flag or “worth a second look”"),
    ("please_check", "Every date"),
)


def _coverage_points(doc: Mapping[str, Any], condition: str) -> list[tuple[str, int, int, int]]:
    """``(label, shown, wrong among them, n)`` from the most confident tier down."""
    tiers = _headline(doc)["conditions"][condition]["selective"]["tiers"]
    n = sum(tiers[tier]["items"] for tier, _ in _SHOWN)
    shown = wrong = 0
    points = []
    for tier, label in _SHOWN:
        shown += tiers[tier]["items"]
        wrong += tiers[tier]["wrong"]
        points.append((label, shown, wrong, n))
    return points


def _risk_parts(doc: Mapping[str, Any]) -> tuple[list[str], list[list[str]], str]:
    header = ["Condition", *(f"{label}: wrong of kept" for _, label in _SHOWN)]
    rows, said = [], []
    for condition in doc["order"]:
        cells = [
            f"{wrong} of {shown} ({fmt.pct(wrong / shown if shown else None)}; {fmt.pct(shown / n)} kept)"
            for _, shown, wrong, n in _coverage_points(doc, condition)
        ]
        rows.append([_label(condition), *cells])
        said.append(
            f"{_label(condition)}: "
            + ", ".join(f"{label.lower()} {cell}" for (_, label), cell in zip(_SHOWN, cells, strict=True))
        )
    description = (
        "Risk against coverage: of the deadlines a condition would keep if it held back the flagged ones, the share "
        "that is wrong (a missed deadline has no flag, so it is kept). " + "; ".join(said) + "."
    )
    return header, rows, description


def _risk_coverage(doc: Mapping[str, Any], theme: str, narrow: bool, ident: str) -> str:
    _, _, description = _risk_parts(doc)
    series = {c: _coverage_points(doc, c) for c in doc["order"]}
    coverages = [shown / n for points in series.values() for _, shown, _, n in points]
    risks = [wrong / shown for points in series.values() for _, shown, wrong, _ in points if shown]
    x_low = min(_floor(min(coverages), 0.1), 0.9)
    y_high = max(_ceil(max(risks), 0.05), 0.05)
    title = "Does “Please check” catch the wrong dates?"
    subtitle = (
        "Wrong among the deadlines kept, flagged ones held back first; a missed deadline has no flag, so it is kept · "
        + _subtitle(doc)
    )
    size = 12.0 if not narrow else 14.0
    title_lines = _wrap(title, 80 if not narrow else 32)
    sub_lines = _wrap(subtitle, 110 if not narrow else 38)
    # the plot starts below the title and subtitle, however many lines they take
    y1 = (26 if not narrow else 24) + 22 * len(title_lines) - 2 + (size + 5) * len(sub_lines) + 18
    if not narrow:
        width, x0, x1, y0 = WIDE, 80.0, 560.0, y1 + 168
        height = int(y0 + 52)
    else:
        width, x0, x1, y0 = NARROW, 56.0, 300.0, y1 + 180
        height = int(y0 + 64 + 22 * len(doc["order"]))
    canvas = Canvas(width, height, theme, ident, title, description)
    y = canvas.lines(
        16 if not narrow else 12,
        26 if not narrow else 24,
        title_lines,
        size=15 if not narrow else 16,
        gap=22,
        weight=600,
    )
    canvas.lines(16 if not narrow else 12, y - 2, sub_lines, size=size, gap=size + 5, role="text2")

    def x(value: float) -> float:
        return x0 + (value - x_low) / (1 - x_low) * (x1 - x0)

    def yv(value: float) -> float:
        return y0 - value / y_high * (y0 - y1)

    tick = 11.0 if not narrow else 14.0
    step = 0.05 if y_high <= 0.2 else 0.1
    for i in range(round(y_high / step) + 1):
        value = step * i
        canvas.line(x0, yv(value), x1, yv(value))
        canvas.text(x0 - 8, yv(value) + 4, f"{value * 100:.0f} %", size=tick, role="text2", anchor="end")
    for i in range(round((1 - x_low) / 0.1) + 1):
        value = x_low + 0.1 * i
        canvas.text(x(value), y0 + 18, f"{value * 100:.0f} %", size=tick, role="text2", anchor="middle")
    canvas.text((x0 + x1) / 2, y0 + 38, "share of deadlines kept", size=tick, role="text2", anchor="middle")
    ends = []
    for condition, points in series.items():
        coords = [(x(shown / n), yv(wrong / shown)) for _, shown, wrong, n in points if shown]
        canvas.path(coords, condition)
        for (label, shown, wrong, n), (px, py) in zip(points, coords, strict=True):
            canvas.marker(
                condition,
                px,
                py,
                f"{_label(condition)}, {label.lower()}: {wrong} of {shown} wrong ({fmt.pct(wrong / shown)}), "
                f"{fmt.pct(shown / n)} of deadlines kept",
            )
        ends.append((coords[-1][1], condition, points[-1]))
    if not narrow:
        # direct labels at the right end, pushed apart so they never overlap
        placed: list[float] = []
        for end_y, condition, (_, shown, wrong, _) in sorted(ends):
            label_y = max(end_y + 4, placed[-1] + 16) if placed else end_y + 4
            placed.append(label_y)
            canvas.text(x1 + 14, label_y, f"{_label(condition)} · {fmt.pct(wrong / shown)}", size=12)
    else:
        legend_y = y0 + 64
        for i, condition in enumerate(doc["order"]):
            row_y = legend_y + 22 * i
            canvas.marker(condition, 20, row_y - 5, _label(condition))
            _, shown, wrong, _ = series[condition][-1]
            canvas.text(
                34, row_y, f"{_label(condition)} · every date {fmt.pct(wrong / shown)} wrong", size=size
            )
    return canvas.render()


# --------------------------------------------------------------------------------------------------
# 5. Cost
# --------------------------------------------------------------------------------------------------


def _cost_parts(doc: Mapping[str, Any]) -> tuple[list[str], list[list[str]], str]:
    headline = _headline(doc)
    header = ["Condition", "$ per letter", "$ per right date", "Latency p50", "Latency p95", "Exactly right"]
    rows, said = [], []
    for condition in doc["order"]:
        c = headline["conditions"][condition]
        cells = [
            _label(condition),
            fmt.usd(c["cost"]["usd_per_letter"]),
            fmt.usd(c["cost"]["usd_per_right_date"]),
            fmt.seconds(c["latency_ms"]["p50"]),
            fmt.seconds(c["latency_ms"]["p95"]),
            fmt.pct(c["exact"]["value"]),
        ]
        rows.append(cells)
        said.append(
            f"{cells[0]}: {cells[1]} per letter, {cells[2]} per right date, latency p50 {cells[3]}, p95 {cells[4]}, "
            f"{cells[5]} exactly right"
        )
    description = (
        f"Dot plot of the API-equivalent cost per letter and per right date over {headline['letters']} held-out "
        "letters. " + "; ".join(said) + "."
    )
    return header, rows, description


def _cost(doc: Mapping[str, Any], theme: str, narrow: bool, ident: str) -> str:
    headline = _headline(doc)
    _, _, description = _cost_parts(doc)
    panels = []
    for key, heading in (("usd_per_letter", "$ per letter"), ("usd_per_right_date", "$ per right date")):
        values = [headline["conditions"][c]["cost"][key] for c in doc["order"]]
        high = _ceil(max(values), 0.02)
        rows = [
            Row(c, value, None, fmt.usd(value), f"{_label(c)}: {fmt.usd(value)} {heading.removeprefix('$ ')}")
            for c, value in zip(doc["order"], values, strict=True)
        ]
        panels.append(Panel(heading, 0.0, high, _dollars, rows))
    return _dot_chart(
        ident,
        theme,
        narrow,
        "What each condition costs",
        f"API-equivalent $ from the Claude CLI's own accounting, mean over {headline['letters']} letters · "
        f"{doc['model']}",
        description,
        panels,
        "Cheaper to the left. Ordnung also writes a summary, key facts and a checked quote for every letter.",
    )


_CHARTS: dict[
    str,
    tuple[
        Callable[[Mapping[str, Any], str, bool, str], str],
        Callable[[Mapping[str, Any]], tuple[list[str], list[list[str]], str]],
        str,
    ],
] = {
    "held-out": (_hero, _hero_parts, "Held-out deadlines, read once: exact date and harm"),
    "timeline": (_timeline, _timeline_parts, "What was held out, and when"),
    "differences": (_differences, _differences_parts, "Is Ordnung clearly better than each baseline?"),
    "risk-coverage": (_risk_coverage, _risk_parts, "Does “Please check” catch the wrong dates?"),
    "cost": (_cost, _cost_parts, "What each condition costs"),
}


def svg(name: str, doc: Mapping[str, Any], theme: str = "light", *, narrow: bool = False) -> str:
    """Chart ``name`` of the presentation ``doc``: ``theme`` is ``light``, ``dark`` or ``css``."""
    draw, _, _ = _CHARTS[name]
    return draw(doc, theme, narrow, f"{name}-{theme}-{'n' if narrow else 'w'}")


def table(name: str, doc: Mapping[str, Any]) -> tuple[list[str], list[list[str]]]:
    """The chart's numbers as a table: its header and rows, in the page's row order."""
    header, rows, _ = _CHARTS[name][1](doc)
    return header, rows


def description(name: str, doc: Mapping[str, Any]) -> str:
    """Every value the chart shows, in words: its ``<desc>`` and the README picture's alt text."""
    return _CHARTS[name][1](doc)[2]


def title(name: str) -> str:
    return _CHARTS[name][2]
