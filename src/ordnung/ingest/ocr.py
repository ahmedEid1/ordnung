"""Text in pictures (ADR 0024): the words in a photo or scan Claude isn't reading, read on this computer by
Tesseract, an optional program the person installs, for the letter search only.

Only letters Claude isn't reading qualify: kept private, held, waiting for Claude, or failed. What Tesseract reads
is kept in ``derived/<doc_id>/picture-text.json`` (:mod:`ordnung.db.scan_text`, through the store) under the
scanner text's rules (ADR 0020): never a page's text, never shown, checked or sent to Claude, never in Ask's
search or the ledger fingerprint, and removed once Claude reads that page.

This module is the engine and nothing else:

* :func:`find` looks for a usable Tesseract (4.1 or newer, with German and/or English) and remembers it;
* :func:`page_picture` draws one page as a grayscale PNG: at most :data:`PICTURE_LONG_SIDE` pixels on its long
  side and :data:`MAX_DPI`, never enlarged; Tesseract never sees the uploaded file itself;
* :func:`recognise` runs Tesseract on that PNG (stdin to stdout), one thread, at low priority, in a private
  temporary folder, with a time limit and a stop that kills it.

``ORDNUNG_OCR=off`` (:data:`OCR_SWITCH`, :func:`ordnung.config.ocr_turned_off`) turns it all off. Only the
worker (:mod:`ordnung.ingest.worker`) and the doctor (:mod:`ordnung.doctor`) import this module.

Not built yet: :func:`find` answers ``None``, as if Tesseract weren't installed, and :func:`candidates` names no
place, so nothing is read; :func:`look`, :func:`page_picture` and :func:`recognise` raise
``NotImplementedError``.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ordnung import config

#: The off switch (``ORDNUNG_OCR=off``; :func:`ordnung.config.ocr_turned_off`).
OCR_SWITCH = config.OCR_SWITCH
#: The oldest Tesseract Ordnung uses.
MIN_VERSION = (4, 1)
#: The languages Ordnung asks for, in this order (``-l deu+eng``), of those installed.
LANGUAGES = ("deu", "eng")
#: The long side of the picture Tesseract gets, in pixels (a photo is never enlarged to it).
PICTURE_LONG_SIDE = 2400
#: A PDF page is never drawn finer than this, so a small page (a receipt) stays small.
MAX_DPI = 300
#: The time limit of ``--version`` and ``--list-langs``.
LOOK_TIMEOUT_S = 10.0
#: The time limit of reading one page.
PAGE_TIMEOUT_S = 120.0
#: How often a reading checks whether Ordnung is stopping.
POLL_S = 0.25
#: The niceness Tesseract runs at on Linux and macOS (``BELOW_NORMAL_PRIORITY_CLASS`` on Windows).
NICENESS = 10


@dataclass(frozen=True, slots=True)
class Tesseract:
    """A Tesseract found on this computer: where, which version (``None``: it didn't answer) and which of
    :data:`LANGUAGES` it has, in that order. ``launcher`` is for tests only: what runs instead of ``path``
    (``(sys.executable, "tests/fake_tesseract.py")``)."""

    path: str
    version: tuple[int, int, int] | None
    languages: tuple[str, ...]
    launcher: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        """Whether Ordnung reads pictures with it: :data:`MIN_VERSION` or newer, with German or English."""
        return self.version is not None and self.version >= MIN_VERSION and bool(self.languages)

    @property
    def argv(self) -> tuple[str, ...]:
        """What runs it, before its arguments."""
        return self.launcher or (self.path,)


class RecognitionError(Exception):
    """A page's words couldn't be read. Its message never holds what Tesseract printed."""


class Stopped(RecognitionError):
    """Ordnung stopped while Tesseract was reading a page; Tesseract was killed and nothing is kept."""


def turned_off(env: Mapping[str, str] | None = None) -> bool:
    """Whether ``ORDNUNG_OCR`` turns text in pictures off (:func:`ordnung.config.ocr_turned_off`)."""
    return config.ocr_turned_off(env)


def candidates(platform: str = sys.platform, env: Mapping[str, str] | None = None) -> list[str]:
    """The Tesseract programs to look at on ``platform``, in order. Not built yet: none."""
    return []


def look(path: str, *, launcher: tuple[str, ...] = ()) -> Tesseract:
    """Ask the Tesseract at ``path`` for its version and languages. Not built yet."""
    raise NotImplementedError("Ordnung doesn't read pictures yet")


def find(
    *, refresh: bool = False, platform: str = sys.platform, env: Mapping[str, str] | None = None
) -> Tesseract | None:
    """The Tesseract Ordnung reads pictures with; ``None``: not installed, or turned off. Not built yet:
    ``None``, as if it weren't installed."""
    return None


def page_picture(original: Path, mime: str, page: int) -> bytes:
    """Page ``page`` (1-based) of the letter's file as the PNG Tesseract reads. Not built yet."""
    raise NotImplementedError("Ordnung doesn't read pictures yet")


def recognise(
    engine: Tesseract,
    png: bytes,
    *,
    stop: threading.Event | None = None,
    timeout_s: float = PAGE_TIMEOUT_S,
) -> str:
    """The words Tesseract reads in ``png``. Not built yet."""
    raise NotImplementedError("Ordnung doesn't read pictures yet")
