"""An e-mail whose text Pillow can't lay out is refused like any other file Ordnung can't take, not an error.

An e-mail's text becomes page images (:func:`ordnung.ingest.text.layout_text`). Where Pillow lays text out
with raqm, a control character such as U+001C in the body makes it fail with a bare ``RuntimeError`` from
:mod:`PIL.ImageFont`. (A ``.txt`` file with one is already refused as not text.) The fix belongs in
``ingest/text.py``, but that file is part of the benchmark's code digest (``evals/conditions.py``), so changing
it invalidates every recorded benchmark answer. It waits for the next recording. Until then, each way a file
comes in (the upload route, which the phone uses too, the watched folder, ``ordnung add`` and proof of a sent
letter) wraps intake in :func:`text_layout_refused`, which turns exactly that error into an
:class:`~ordnung.ingest.intake.IntakeError` with :data:`UNLAID_TEXT`.
"""

from __future__ import annotations

import contextlib
import traceback
from collections.abc import Iterator
from pathlib import Path

from PIL import ImageFont

from ordnung.ingest.intake import IntakeError

UNLAID_TEXT = (
    "This e-mail has characters Ordnung can't put on a page, such as control characters. "
    "Save it as a PDF and add that instead."
)

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
