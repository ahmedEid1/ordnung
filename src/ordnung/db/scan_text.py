"""A scan's scanner text: ``derived/<doc_id>/scan-text.json`` (ADR 0020), and the words Ordnung read in a picture
itself: ``derived/<doc_id>/picture-text.json`` (ADR 0024) — the file format, nothing else.

Many scanners and phone apps save a "searchable PDF": a picture of the page with the scanner's own reading
of it drawn as invisible text. That text is somebody's reading of a picture, not the letter's words, so
it is never a page's text (:mod:`ordnung.ingest.text` keeps it apart, as ``PdfText.scan_text``). It is
kept here only so the person's letter search can find a scan nobody has read yet:

* only :class:`~ordnung.db.store.Store` reads it (``scan_text_matches``, ``scan_text_pages``) and writes
  it (``write_scan_text``, which the text stage of :mod:`ordnung.ingest.pipeline` calls) — a test holds
  that no other module imports this one;
* it is never in the ``pages`` table, the search indexes, :class:`~ordnung.models.Document`, Ask's tools,
  a prompt or an evidence check, and never shown: the API says only *that* a search found a letter in it;
* it lives with the page images, so hand-off sync and backups carry it and deleting the letter for good
  deletes it (with ``derived/<doc_id>/``) — on older versions of Ordnung too, which ignore it otherwise.

Text in pictures (ADR 0024) follows the same rules in a file of its own, :data:`PICTURE_NAME` (every function
takes ``name=``; no other file can be named): what Tesseract, an optional program, read in the picture of a page
Claude isn't reading, kept for search until Claude reads that page. There a page that maps to ``""`` means
"looked, no words found".

Format: ``{"version": 1, "pages": {"<page>": "<text>"}}``, at most :data:`MAX_PAGE_CHARS` per page,
written atomically and private (``0600``). An empty ``pages`` map means "looked, nothing there". A file
that is missing, unreadable, malformed or of another version reads as nothing.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Mapping
from pathlib import Path

from ordnung.config import PRIVATE_DIR_MODE
from ordnung.durable import PRIVATE_FILE_MODE, write_atomic

log = logging.getLogger(__name__)

NAME = "scan-text.json"
#: The words Ordnung read in the picture of a page itself (Tesseract, ADR 0024): search only, like the scanner's.
PICTURE_NAME = "picture-text.json"
VERSION = 1
#: The most of one page's scanner text that is kept (a dense A4 page has about 5,000 characters).
MAX_PAGE_CHARS = 20_000


def _known(name: str) -> None:
    if name not in (NAME, PICTURE_NAME):
        raise ValueError(f"not a file of found text: {name!r}")


def path(derived: Path, doc_id: str, *, name: str = NAME) -> Path:
    """Where the scanner text (or with ``name=PICTURE_NAME`` the picture text) of letter ``doc_id`` lives under
    the data folder's ``derived/``; any other ``name`` is refused (``ValueError``)."""
    _known(name)
    if not doc_id or doc_id in (".", "..") or "/" in doc_id or "\\" in doc_id:
        raise ValueError(f"not a letter id: {doc_id!r}")
    return derived / doc_id / name


def read(derived: Path, doc_id: str, *, name: str = NAME) -> dict[int, str]:
    """Page → scanner text; ``{}`` when the file is missing, unreadable, malformed or of another version."""
    _known(name)
    try:
        data = json.loads(path(derived, doc_id, name=name).read_bytes())
    except (OSError, ValueError):
        return {}
    pages = data.get("pages") if isinstance(data, dict) and data.get("version") == VERSION else None
    if not isinstance(pages, dict):
        return {}
    found: dict[int, str] = {}
    for key, text in pages.items():
        if not (isinstance(key, str) and key.isdecimal() and isinstance(text, str)):
            return {}
        found[int(key)] = text[:MAX_PAGE_CHARS]
    return found


def write(derived: Path, doc_id: str, pages: Mapping[int, str], *, name: str = NAME) -> None:
    """Keep ``pages`` (page → scanner text, each cut at :data:`MAX_PAGE_CHARS`) as the letter's scanner text,
    atomically and private; durable while hand-off sync is on (:func:`ordnung.durable.write_atomic`)."""
    target = path(derived, doc_id, name=name)
    target.parent.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    body = {
        "version": VERSION,
        "pages": {str(page): text[:MAX_PAGE_CHARS] for page, text in sorted(pages.items())},
    }
    write_atomic(target, json.dumps(body, ensure_ascii=False).encode("utf-8"), mode=PRIVATE_FILE_MODE)


def remove(derived: Path, doc_id: str, *, name: str = NAME) -> None:
    """Forget the letter's scanner text (nothing to do when there is none)."""
    with contextlib.suppress(FileNotFoundError):
        path(derived, doc_id, name=name).unlink()


def present(derived: Path, doc_id: str, *, name: str = NAME) -> bool:
    """Whether the letter's scanner text was looked for and kept (an empty map counts)."""
    return path(derived, doc_id, name=name).is_file()
