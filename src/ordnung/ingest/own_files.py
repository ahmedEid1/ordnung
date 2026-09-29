"""Files Ordnung made for the person — a drafted letter's PDF, a sent letter's *Nachweis* — recognised by
their SHA-256 wherever they come back (SPEC § 8, § 21 privacy).

Such a file carries the profile's address and IBAN, which are never put into a prompt. So it is never
added as a letter received — not from the watched folder (:mod:`ordnung.ingest.watcher`), and not as an
attachment of an e-mail (a sent e-mail that carries the letter's PDF, saved into the folder or added by
hand, :func:`ordnung.ingest.pipeline.add_file`): it is reported as not added, with :data:`OWN_LETTER`.

The newest :data:`MAX_OWN_FILES` fingerprints are kept in ``meta``; remembering one is a read-modify-write
in one write transaction, so two PDFs made at once (the preview and a download) both stay remembered.
"""

from __future__ import annotations

import hashlib
import json

from ordnung.db.store import Store

OWN_FILES_META_KEY = "own_pdfs"
MAX_OWN_FILES = 200
OWN_LETTER = "This is a letter Ordnung drafted for you — it isn't added as a letter you received."


def _own_files(store: Store) -> list[str]:
    try:
        stored = json.loads(store.get_meta(OWN_FILES_META_KEY) or "[]")
    except ValueError:
        return []
    return [digest for digest in stored if isinstance(digest, str)] if isinstance(stored, list) else []


def remember_own_file(store: Store, data: bytes) -> None:
    """Remember a file Ordnung made for the person (by its SHA-256; the newest :data:`MAX_OWN_FILES`)."""
    digest = hashlib.sha256(data).hexdigest()
    with store.tx():  # read and write in one transaction: concurrent requests never drop a fingerprint
        known = [entry for entry in _own_files(store) if entry != digest]
        store.set_meta(OWN_FILES_META_KEY, json.dumps([*known, digest][-MAX_OWN_FILES:]))


def is_own_file(store: Store, data: bytes) -> bool:
    """Whether ``data`` is a file Ordnung made (:func:`remember_own_file`)."""
    return hashlib.sha256(data).hexdigest() in _own_files(store)
