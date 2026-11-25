"""Model-written text made plain for display: no control characters and no invisible format characters."""

from __future__ import annotations

import re
import unicodedata

#: C0/C1 control characters (NUL, escape sequences …), line breaks and tabs aside: RFC 5545 forbids
#: control characters in a calendar's text, and a NUL can break an import.
_CONTROLS = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")
#: Unicode's line and paragraph separators: line breaks no calendar file or one-line title expects.
_SEPARATORS = re.compile("[\u2028\u2029]")
#: The format characters (Unicode category Cf) that stay: the zero-width non-joiner and joiner, which
#: Persian and Indic spelling and emoji sequences need, and which reorder nothing. Every other one goes:
#: a bidirectional override or isolate reorders a title on screen, and an invisible space, joiner, tag or
#: byte order mark splits or marks a word no reader sees split or marked. The tag characters go too, so
#: the subdivision flags (England, Scotland, Wales) show as a plain black flag: tags can spell out a
#: whole hidden text after one, and no name or address needs them.
_KEPT_FORMATS = frozenset("\u200c\u200d")


def clean_display_text(text: str, *, lines: bool = False) -> str:
    """``text`` without control characters and format characters (:data:`_KEPT_FORMATS` aside); a tab
    becomes a space, and so does a line break (a line or paragraph separator included) unless ``lines``
    (a long field keeps its lines, as line breaks)."""
    text = _SEPARATORS.sub("\n", text.replace("\r\n", "\n")).replace("\t", " ")
    if not lines:
        text = text.replace("\n", " ")
    text = _CONTROLS.sub("", text)
    return "".join(ch for ch in text if ch in _KEPT_FORMATS or unicodedata.category(ch) != "Cf")
