"""Colours, shapes and labels of the evaluation's charts and pages: the single source (standard library only).

One colour and one shape per condition, on every chart and page. The four colours are the only four-colour subset
of the reference palette that passes the colour-vision checks with every pair side by side (dot plots whose order
follows the data, crossing lines) in both modes, run with the data-visualisation validator::

    validate_palette.js "#2a78d6,#e87ba4,#eda100,#008300" --mode light --pairs all
      [PASS] Lightness band, Chroma floor
      [PASS] CVD separation         worst all-pairs #e87ba4<->#2a78d6 dE 13.0 (protan)
      [PASS] Normal-vision floor    worst all-pairs #eda100<->#e87ba4 dE 19.6
      [WARN] Contrast vs surface    below 3:1: #e87ba4 2.62, #eda100 2.11 (relief: labels and a table)
    validate_palette.js "#3987e5,#d55181,#c98500,#008300" --mode dark --pairs all
      [PASS] Lightness band, Chroma floor, Normal-vision floor (worst dE 19.3), Contrast vs surface (all >= 3:1)
      [WARN] CVD separation         worst all-pairs #008300<->#c98500 dE 6.9 (protan): legal with a second channel

The light mode's two colours under 3:1 and the dark mode's CVD warning are why identity never rests on colour:
every mark has its condition's shape, every row its name, and every chart a table with the same numbers. Text is
always in the text colours, never in a series colour.
"""

from __future__ import annotations

#: The conditions, in the benchmark's fixed order (ties in a sort keep it).
CONDITIONS = ("ordnung", "llm_only", "llm_rules_text", "llm_rules_tool")
#: Display labels (the presenter's own: ``evals/records.py`` is in the recordings' code digest).
LABELS = {
    "ordnung": "Ordnung",
    "llm_only": "LLM only",
    "llm_rules_text": "LLM + rules text",
    "llm_rules_tool": "LLM + rules tool",
}
#: What each condition is, in a few words.
DESCRIPTIONS = {
    "ordnung": "the model reads, the engine computes",
    "llm_only": "the model computes the date itself",
    "llm_rules_text": "the same, with the rules pasted into the prompt",
    "llm_rules_tool": "the same, with Ordnung's engine as tools: an agent with a calculator",
}
SHAPES = {
    "ordnung": "circle",
    "llm_only": "triangle",
    "llm_rules_text": "square",
    "llm_rules_tool": "diamond",
}

#: Surfaces, ink and the four series colours, light mode (the reference palette's chart chrome).
LIGHT = {
    "surface": "#fcfcfb",
    "text": "#0b0b0b",
    "text2": "#52514e",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "link": "#1c5cab",
    "ordnung": "#2a78d6",
    "llm_only": "#e87ba4",
    "llm_rules_text": "#eda100",
    "llm_rules_tool": "#008300",
}
#: The same roles, dark mode: the same hues stepped for the dark surface, validated as a set.
DARK = {
    "surface": "#1a1a19",
    "text": "#f0efec",
    "text2": "#c3c2b7",
    "grid": "#2c2c2a",
    "axis": "#383835",
    "link": "#86b6ef",
    "ordnung": "#3987e5",
    "llm_only": "#d55181",
    "llm_rules_text": "#c98500",
    "llm_rules_tool": "#008300",
}
THEMES = {"light": LIGHT, "dark": DARK}
#: The roles as CSS variables, for charts inlined in the report page (its stylesheet sets them per theme).
CSS = {role: f"var(--{role.replace('_', '-')})" for role in LIGHT}

FONT = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(colour: str) -> float:
    """WCAG relative luminance of a ``#rrggbb`` colour."""
    red, green, blue = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast(first: str, second: str) -> float:
    """WCAG contrast ratio of two ``#rrggbb`` colours (1 to 21)."""
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)
