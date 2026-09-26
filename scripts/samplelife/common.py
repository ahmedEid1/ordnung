"""Helpers shared by the ``docs_*`` modules."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from samplelife.fmt import iso
from samplelife.letter import Letter, Meta, render
from samplelife.orgs import Org
from samplelife.photo import Surface, photo_of_pdf_page
from samplelife.truth import Rendered

BERLIN = ZoneInfo("Europe/Berlin")
SALUTE_DE = "Sehr geehrter Herr Rivera,"
SALUTE_EN = "Dear Mr Rivera,"


def created(day: str, hour: int = 7, minute: int = 42) -> datetime:
    """Fixed PDF creation timestamp: the letter date, early morning, Berlin time."""
    value = iso(day)
    return datetime(value.year, value.month, value.day, hour, minute, tzinfo=BERLIN)


def letter_pdf(
    org: Org,
    day: str,
    compose: Callable[[Letter], None],
    *,
    follow_ref: str = "",
    lang: str = "de",
    fold_marks: bool = True,
    page_format: str | tuple[float, float] = "A4",
    plain_pages: bool = False,
) -> tuple[bytes, int]:
    """Render a letter dated ``day`` (PDF bytes and page count)."""
    label = "Page {n} of {nb}" if lang == "en" else "Seite {n} von {nb}"
    meta = Meta(
        created=created(day),
        lang=lang,
        follow_ref=follow_ref,
        fold_marks=fold_marks,
        page_numbers_label=label,
    )
    return render(org, meta, compose, page_format=page_format, plain_pages=plain_pages)


def as_pdf(result: tuple[bytes, int]) -> Rendered:
    """Wrap a rendered PDF."""
    data, pages = result
    return Rendered(files=[data], extension="pdf", pages=pages)


def as_photos(
    result: tuple[bytes, int], shots: list[tuple[int, int, Surface, float]], *, folds: int = 2
) -> Rendered:
    """Photograph selected pages: ``shots`` = ``[(page_index, seed, surface, angle), …]``."""
    data, _pages = result
    files = [
        photo_of_pdf_page(data, index, seed=seed, surface=surface, folds=folds, angle=angle)
        for index, seed, surface, angle in shots
    ]
    return Rendered(files=files, extension="jpg", pages=len(files), source_pdf=data)
