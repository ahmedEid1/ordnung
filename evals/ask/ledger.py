"""The ledgers the Ask benchmark asks about: the demo's sample life, and copies with injected letters.

**The base ledger** is the zero-token demo exactly as a visitor sees it after opening all three
*New mail* letters: the committed demo snapshot (``src/ordnung/demo/demo_db``) copied, then the tray
letters read through the real pipeline on the demo's recorded extractions (strict replay, no model
call). It is the same ledger the demo's recorded Ask answers were made against, as of the simulated
today (Mon 28 Sep 2026).

**An attack ledger** is a copy of the base ledger's database in which one letter's page text (or its
summary) carries an injected sentence (:mod:`evals.ask.attacks`). Only the text changes — the
to-dos, dates and amounts Ordnung filed stay those of the real letter — which is exactly the
reviewer's finding: a date that appears *only* in letter text Ask reads at question time.

Ask's replay keys include a hash of everything its tools can read (including page texts, see
:func:`ordnung.assistant.ask.ledger_fingerprint`), so each ledger has its own recordings.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ordnung import clock
from ordnung.app_context import build_context
from ordnung.config import Paths, fixtures_dir
from ordnung.db.store import Store
from ordnung.demo import Manifest, load_manifest, samples_root
from ordnung.demo.loader import DB_NAME, copy_data, demo_version, snapshot_dir, snapshot_version
from ordnung.demo.tour import open_tray_item
from ordnung.llm.replay import ReplayBackend

TODAY = date(2026, 9, 28)
"""The sample life's simulated today (``manifest.json``: ``simulated_today``)."""


class LedgerError(RuntimeError):
    """The benchmark ledger cannot be built (the message says what to do)."""


@dataclass(frozen=True)
class SampleLife:
    """The manifest, the samples' folder and each sample's document id (content-addressed)."""

    manifest: Manifest
    root: Path
    doc_ids: dict[str, str]

    @classmethod
    def load(cls, samples: Path | None = None) -> SampleLife:
        root = samples_root(samples)
        manifest = load_manifest(root)
        if manifest.simulated_today != TODAY.isoformat():
            raise LedgerError(
                f"The sample life's today moved to {manifest.simulated_today}; update evals.ask."
            )
        return cls(manifest, root, manifest.document_ids(root))

    def slug_of(self, doc_id: str) -> str | None:
        """The sample a document id belongs to (``None`` for anything else)."""
        return next((slug for slug, known in self.doc_ids.items() if known == doc_id), None)


@contextlib.contextmanager
def pinned_today(day: date = TODAY) -> Iterator[None]:
    """Run with the process clock on the sample life's today (restored afterwards)."""
    prior = clock.today() if clock.simulated() else None
    clock.set_today(day.isoformat())
    try:
        yield
    finally:
        clock.set_today(prior)


def build_base(target: Path, life: SampleLife, *, snapshot: Path | None = None) -> Path:
    """Copy the demo snapshot into ``target`` and open every tray letter (strict replay)."""
    source = snapshot or snapshot_dir()
    current = demo_version(samples=life.root)
    if snapshot_version(source) != current:
        raise LedgerError(
            f"The demo snapshot in {source} is out of date: rebuild it first "
            "(ordnung demo --rebuild, or ORDNUNG_RECORD=1 ordnung demo --live --rebuild)."
        )
    copy_data(source, target)
    asyncio.run(_open_tray(target, life))
    _settle_stamps(target)
    return target


_STAMPED = ("documents", "items", "contracts", "parties", "cases")
"""Tables whose listings break ties by ``created_at`` or ``updated_at``."""


def _settle_stamps(target: Path) -> None:
    """Put every record's ``created_at`` and ``updated_at`` at the start of its day.

    The demo stamps records with the simulated day but the real time of day, and the tools break ties
    by creation time (two payments due on the same day). The snapshot's records carry the time of day
    it was built, the tray letters' the time the benchmark runs, so the order of such a pair — and with
    it a recorded tool result — depended on the hour of the run. At the start of the day, ties fall to
    insertion order: the snapshot's records, then the tray letters' in tray order, at any hour. No tool
    shows a time of day of these fields, and the ledger fingerprint reads none of them."""
    with contextlib.closing(sqlite3.connect(target / DB_NAME)) as db, db:
        for table in _STAMPED:
            db.execute(
                f"UPDATE {table} SET created_at = substr(created_at, 1, 10) || 'T00:00:00Z', "
                "updated_at = substr(updated_at, 1, 10) || 'T00:00:00Z'"
            )


async def _open_tray(target: Path, life: SampleLife) -> None:
    ctx = build_context(target, backend_obj=ReplayBackend(fixtures_dir()))
    try:
        for sample in life.manifest.tray:
            await open_tray_item(ctx, sample.slug, stage_delay=0, manifest=life.manifest, samples=life.root)
    finally:
        ctx.close()


def copy_database(source: Path, target: Path) -> Path:
    """A copy of ``source``'s database only (the tools read nothing else) in ``target``."""
    target.mkdir(parents=True, exist_ok=True)
    with (
        contextlib.closing(sqlite3.connect(source / DB_NAME)) as src,
        contextlib.closing(sqlite3.connect(target / DB_NAME)) as dst,
    ):
        src.backup(dst)
    return target


def inject(data_dir: Path, doc_id: str, text: str, *, channel: str) -> None:
    """Append ``text`` to a letter's first page (``page``) or to its summary (``summary``)."""
    store = Store.open(Paths(data_dir))
    try:
        document = store.get_document(doc_id)
        if document is None:
            raise LedgerError(f"The ledger has no document {doc_id} to inject into.")
        if channel == "summary":
            store.update_document(doc_id, summary=f"{document.summary or ''} {text}".strip())
            return
        page = store.get_page(doc_id, 1)
        if page is None:
            raise LedgerError(f"{doc_id} has no first page.")
        store.set_page_text(doc_id, 1, f"{page.text}\n\n{text}", page.text_source)
    finally:
        store.close()
