"""Model-written text made plain for display: no control characters and no bidirectional overrides."""

from __future__ import annotations

import re

#: C0/C1 control characters (NUL, escape sequences …) and bidirectional overrides, line breaks and tabs
#: aside: RFC 5545 forbids them in a calendar's text, a NUL can break an import, and an override reorders
#: a title on screen.
_DISPLAY_CONTROLS = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def clean_display_text(text: str, *, lines: bool = False) -> str:
    """``text`` without control characters and bidirectional overrides; a tab becomes a space, and so does
    a line break unless ``lines`` (a long field keeps its lines)."""
    text = text.replace("\r\n", "\n").replace("\t", " ")
    if not lines:
        text = text.replace("\n", " ")
    return _DISPLAY_CONTROLS.sub("", text)
