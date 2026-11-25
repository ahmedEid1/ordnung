"""Model-written text made plain for display: no control characters and no bidirectional overrides."""

from __future__ import annotations

import re

#: C0/C1 control characters (NUL, escape sequences …), bidirectional overrides and invisible spaces (zero
#: width space, word joiner, byte order mark), line breaks and tabs aside: RFC 5545 forbids control
#: characters in a calendar's text, a NUL can break an import, an override reorders a title on screen and
#: an invisible space splits a word no reader sees split. The zero-width (non-)joiners stay: Persian and
#: Indic scripts and emoji sequences need them.
_DISPLAY_CONTROLS = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f؜​‎‏‪-‮⁠⁦-⁩﻿]")
#: Unicode's line and paragraph separators: line breaks no calendar file or one-line title expects.
_SEPARATORS = re.compile("[  ]")


def clean_display_text(text: str, *, lines: bool = False) -> str:
    """``text`` without control characters, bidirectional overrides and invisible spaces; a tab becomes a
    space, and so does a line break (a line or paragraph separator included) unless ``lines`` (a long
    field keeps its lines, as line breaks)."""
    text = _SEPARATORS.sub("\n", text.replace("\r\n", "\n")).replace("\t", " ")
    if not lines:
        text = text.replace("\n", " ")
    return _DISPLAY_CONTROLS.sub("", text)
