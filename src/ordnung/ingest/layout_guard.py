"""An e-mail whose text Pillow can't lay out is refused like any other file Ordnung can't take, not an error.

An e-mail's text becomes page images (:func:`ordnung.ingest.text.layout_text`). Where Pillow lays text out with
raqm, a paragraph separator in a line (such as U+2029, or the "…" a Windows mail program writes into a mail it
labels ISO-8859-1) made it fail with a bare ``RuntimeError`` from :mod:`PIL.ImageFont`. ``ingest/text.py`` now
turns those into line breaks and reads ISO-8859-1 as Windows-1252, so no character Ordnung knows of fails. Each
way a file comes in (the upload route, which the phone uses too, the watched folder, ``ordnung add`` and proof
of a sent letter) still wraps intake in :func:`text_layout_refused`: should Pillow's layout fail on something
else, the person gets :data:`UNLAID_TEXT`, not a server error.
"""

from __future__ import annotations

import contextlib
import traceback
from collections.abc import Iterator
from pathlib import Path

from PIL import ImageFont

from ordnung.ingest.intake import IntakeError

UNLAID_TEXT = "Ordnung can't put the text of this e-mail on a page. Save it as a PDF and add that instead."

_FONT_MODULE = Path(ImageFont.__file__).resolve()


def raised_by_text_layout(exc: BaseException) -> bool:
    """Whether ``exc`` is a ``RuntimeError`` raised in Pillow's font module (its text layout failing)."""
    if not isinstance(exc, RuntimeError) or exc.__traceback__ is None:
        return False
    innermost = traceback.extract_tb(exc.__traceback__)[-1]
    return Path(innermost.filename).resolve() == _FONT_MODULE  # a WindowsPath compares without case


@contextlib.contextmanager
def text_layout_refused() -> Iterator[None]:
    """Run intake; Pillow's text layout failing becomes an :class:`IntakeError` (any other error passes)."""
    try:
        yield
    except RuntimeError as exc:
        if raised_by_text_layout(exc):
            raise IntakeError(UNLAID_TEXT) from exc
        raise
