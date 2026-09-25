"""Text normalisation with an offset map back to the original string.

Quote verification compares the model's quote with the page text in a canonical form — NFKC,
casefolded, unified quotes/dashes/apostrophes, whitespace collapsed to single spaces, hyphenated
line breaks joined — while every normalised character remembers the index it came from in the
original text, so a match can be mapped back to words and highlighted on the page image.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator

# Typographic variants folded to one ASCII form (see fold_punctuation).
_PUNCTUATION = str.maketrans(
    {
        "‘": "'",  # ‘
        "’": "'",  # ’
        "‚": "'",  # ‚
        "‛": "'",  # ‛
        "′": "'",  # ′
        "´": "'",  # ´
        "`": "'",
        "“": '"',  # “
        "”": '"',  # ”
        "„": '"',  # „
        "‟": '"',  # ‟
        "«": '"',  # «
        "»": '"',  # »
        "″": '"',  # ″
        "‐": "-",  # hyphen
        "‑": "-",  # non-breaking hyphen
        "‒": "-",  # figure dash
        "–": "-",  # en dash
        "—": "-",  # em dash
        "―": "-",  # horizontal bar
        "−": "-",  # minus sign
    }
)
# Invisible characters that carry no content (soft hyphen, zero-width space/joiners, BOM).
_INVISIBLE = frozenset("­​‌‍⁠﻿")
# A hyphen (or soft hyphen) at the end of a line between two letters: "Einkommen-\nsteuer".
_HYPHEN_BREAK = re.compile(r"(?<=[^\W\d_])[-­‐‑][^\S\n]*\n\s*(?=[^\W\d_])")
# Digit groups with their inner separators: 15.10.2026, 1.234,56, 123/456/78901, 10:30, 2026-10-15.
_DIGIT_TOKEN = re.compile(r"[0-9]+(?:[.,/:-][0-9]+)*")


def normalise_with_map(text: str) -> tuple[str, list[int]]:
    """Normalise ``text`` for fuzzy matching and map every output character back to the input.

    Returns ``(norm, offsets)`` with ``len(offsets) == len(norm)``; ``offsets[i]`` is the index in
    ``text`` of the character that produced ``norm[i]`` (a collapsed whitespace run maps to its
    first character). Leading and trailing whitespace is dropped.
    """
    skipped = _hyphen_break_indices(text)
    chars: list[str] = []
    offsets: list[int] = []
    space_at: int | None = None
    for index, cluster in _clusters(text):
        if index in skipped:
            continue
        for char in fold_punctuation(cluster).casefold():
            if char in _INVISIBLE:
                continue
            if char.isspace():
                if space_at is None:
                    space_at = index
                continue
            if space_at is not None and chars:
                chars.append(" ")
                offsets.append(space_at)
            space_at = None
            chars.append(char)
            offsets.append(index)
    return "".join(chars), offsets


def fold_punctuation(text: str) -> str:
    """NFKC with typographic quotes, dashes and apostrophes folded to ASCII (case kept).

    Folded before NFKC too, which would otherwise decompose ``″`` into two primes and ``´`` into a
    space plus a combining accent.
    """
    return unicodedata.normalize("NFKC", text.translate(_PUNCTUATION)).translate(_PUNCTUATION)


def digits_in(text: str) -> list[str]:
    """Digit groups of ``text`` in order, separators kept (``["15.10.2026", "1.234,56"]``)."""
    return [token for token, _, _ in digit_tokens(fold_punctuation(text))]


def digit_tokens(text: str) -> list[tuple[str, int, int]]:
    """Digit groups of already-normalised ``text`` as ``(token, start, end)`` spans."""
    return [(m.group(), m.start(), m.end()) for m in _DIGIT_TOKEN.finditer(text)]


def _clusters(text: str) -> Iterator[tuple[int, str]]:
    """Yield ``(index, base character + following combining marks)`` so NFKC can compose them."""
    start = 0
    for index in range(1, len(text) + 1):
        if index == len(text) or not unicodedata.combining(text[index]):
            yield start, text[start:index]
            start = index


def _hyphen_break_indices(text: str) -> set[int]:
    """Indices of hyphen + line-break runs that split one word across lines."""
    skipped: set[int] = set()
    for match in _HYPHEN_BREAK.finditer(text):
        if text[match.end()].islower():
            skipped.update(range(match.start(), match.end()))
    return skipped
