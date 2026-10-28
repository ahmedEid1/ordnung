"""The worker reads the words in the pictures of letters Claude isn't reading (ADR 0024): in the background,
after the start delay, one page at a time, woken after each reading, stopped with the worker; never with the
switch off, and at no cost without Tesseract. It writes no row of the database: only ``picture-text.json``.

The engine (:mod:`ordnung.ingest.ocr`) is stood in for here — ``find_tesseract`` is the worker's own hook, and
``ocr.page_picture`` and ``ocr.recognise`` are replaced on the module — so these tests prove the loop; the engine's
own tests (``test_ocr.py``) prove Tesseract is run at low priority and killed on a stop. The tests marked
"with the engine" run the real engine with the fake Tesseract (``tests/fake_tesseract.py``) once it is built."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PIL import Image

from fixtures_llm import TODAY, Router, fake_backend
from helpers_docs import photo, scanned_pdf
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.config import OCR_SWITCH
from ordnung.db.store import Store
from ordnung.ingest import ocr, worker
from ordnung.ingest.ocr import Tesseract
from ordnung.ingest.pipeline import add_file
from ordnung.ingest.worker import IngestWorker

FAKE_TESSERACT = Path(__file__).resolve().parent / "fake_tesseract.py"
#: A Tesseract as ``find`` answers for an installed 5.3.4 with German and English.
INSTALLED = Tesseract("/usr/bin/tesseract", (5, 3, 4), ("deu", "eng"))


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def ctx(data_dir: Path) -> Iterator[AppContext]:
    context = build_context(data_dir, backend_obj=fake_backend(Router()))
    context.worker.catch_up_delay_s = 0
    yield context
    context.close()


@pytest.fixture
def ocr_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text in pictures on (``tests/conftest.py`` turns it off for every test)."""
    monkeypatch.delenv(OCR_SWITCH)


class Engine:
    """Stands in for the engine: ``page_picture`` names the file and page, ``recognise`` answers ``words`` for
    it (``None``: fails), and both say when they ran and whether two readings ever overlapped."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.read: list[tuple[str, int]] = []
        self.words: dict[str, str | None] = {}
        self.found: list[str] = []
        self.at_once = 0
        self.most_at_once = 0
        self._lock = threading.Lock()
        monkeypatch.setattr(ocr, "page_picture", self.page_picture)
        monkeypatch.setattr(ocr, "recognise", self.recognise)

    def find(self) -> Tesseract:
        self.found.append("find")
        return INSTALLED

    def page_picture(self, original: Path, mime: str, page: int) -> bytes:
        return f"{original.name}:{page}".encode()

    def recognise(
        self,
        engine: Tesseract,
        png: bytes,
        *,
        stop: threading.Event | None = None,
        timeout_s: float = ocr.PAGE_TIMEOUT_S,
    ) -> str:
        assert engine == INSTALLED and stop is not None
        name, _, page = png.decode().partition(":")
        with self._lock:
            self.at_once += 1
            self.most_at_once = max(self.most_at_once, self.at_once)
        try:
            time.sleep(0.02)
            self.read.append((name, int(page)))
            words = self.words.get(name, "")
            if words is None:
                raise ocr.RecognitionError("Tesseract stopped with exit code 1")
            return words
        finally:
            with self._lock:
                self.at_once -= 1


@pytest.fixture
def engine(ctx: AppContext, monkeypatch: pytest.MonkeyPatch) -> Engine:
    stand_in = Engine(monkeypatch)
    ctx.worker.find_tesseract = stand_in.find
    return stand_in


async def wait_for(condition: Callable[[], bool], seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def file_name(store: Store, doc_id: str) -> str:
    original = store.get_document_file(doc_id)
    assert original is not None
    return original.name


def database(store: Store) -> list[str]:
    """Every row of the database, to show the loop wrote none."""
    return list(store._conn().iterdump())


async def private_photo(ctx: AppContext, name: str, width: int = 200) -> str:
    """A photo kept private, read on this computer (no model): its page has no text."""
    document = await add_file(ctx, photo("JPEG", size=(width, 100)), name, private=True)
    await ctx.worker.run_until_idle()
    return document.id


async def started(ctx: AppContext, until: Callable[[], bool]) -> None:
    await ctx.worker.start()
    try:
        await wait_for(until)
    finally:
        await ctx.worker.stop()


def picture_file(store: Store, doc_id: str) -> Path:
    return store.paths.derived / doc_id / "picture-text.json"


# --------------------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------------------


async def test_the_worker_reads_pictures_after_the_start_delay_one_page_at_a_time(
    ctx: AppContext, engine: Engine, ocr_on: None
) -> None:
    """After the start delay the worker looks for Tesseract once and reads every due page, newest letter first,
    one page at a time; what it read is kept for search only, and no row of the database changes."""
    assert worker.PICTURES_POLL_S == 300 and ctx.worker.pictures_poll_s == 300
    store = ctx.store
    old = await private_photo(ctx, "alt.jpg")
    scan = await add_file(ctx, scanned_pdf(blank_back=True), "scan.pdf", private=True)
    await ctx.worker.run_until_idle()
    with store.tx() as conn:  # the scan came later
        conn.execute("UPDATE documents SET created_at = '2030-01-01T00:00:00Z' WHERE id = ?", (scan.id,))
    engine.words = {file_name(store, old): "Ihr Kellerabteil 7", file_name(store, scan.id): "Gebäude Süd"}
    before = database(store)

    ctx.worker.catch_up_delay_s = 0.4
    await ctx.worker.start()
    await asyncio.sleep(0.2)
    assert engine.found == [] and engine.read == []  # still waiting out the start delay
    await wait_for(lambda: len(engine.read) == 3)
    await wait_for(lambda: store.picture_text_due() == [])
    await ctx.worker.stop()

    assert engine.read == [
        (file_name(store, scan.id), 1),
        (file_name(store, scan.id), 2),
        (file_name(store, old), 1),
    ]
    assert engine.found == ["find"] and engine.most_at_once == 1
    assert store.picture_text_matches("Kellerabteil") == {old}
    assert store.picture_text_matches("Gebaude") == {scan.id}
    assert store.picture_text_pages(scan.id) == [1, 2]
    assert database(store) == before
    assert ctx.llm.backend.calls == []  # type: ignore[attr-defined]


async def test_the_worker_is_woken_after_each_reading(ctx: AppContext, engine: Engine, ocr_on: None) -> None:
    """A photo kept private while Ordnung runs is read as soon as its own reading ends, not at the next look an
    hour later."""
    ctx.worker.pictures_poll_s = 3600
    await ctx.worker.start()
    try:
        await wait_for(lambda: engine.found == ["find"])
        await asyncio.sleep(0.1)  # the loop has found nothing to read and waits
        assert engine.read == []
        document = await add_file(ctx, photo("JPEG"), "neu.jpg", private=True)
        engine.words = {file_name(ctx.store, document.id): "Ihr Kellerabteil 7"}
        await wait_for(lambda: ctx.store.picture_text_matches("Kellerabteil") == {document.id}, seconds=5)
    finally:
        await ctx.worker.stop()
    assert engine.read == [(file_name(ctx.store, document.id), 1)]


async def test_out_of_date_picture_text_is_tidied_when_the_worker_starts(
    ctx: AppContext, engine: Engine, ocr_on: None
) -> None:
    """Words read in a page Claude has read since (on a computer without text in pictures) go."""
    doc_id = await private_photo(ctx, "foto.jpg")
    assert ctx.store.write_picture_text(doc_id, 1, "Ihr Kellerabteil 7")
    ctx.store.set_page_text(doc_id, 1, "Was Claude las", "transcript")
    await started(ctx, lambda: not picture_file(ctx.store, doc_id).exists())
    assert engine.read == []


# --------------------------------------------------------------------------------------------------
# stopping, failing, turned off, not installed
# --------------------------------------------------------------------------------------------------


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("L", (40, 20), 255).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.mark.parametrize("how", ["stand-in", "with the engine"])
async def test_stop_kills_a_recognition_under_way_and_writes_nothing(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch, ocr_on: None, tmp_path: Path, how: str
) -> None:
    """Ordnung stops (or hand-off sync stands this computer by) while Tesseract reads a page: the reading is
    stopped within a poll, nothing is kept, and the worker's stop returns well within its grace."""
    doc_id = await private_photo(ctx, "foto.jpg")
    before = database(ctx.store)
    monkeypatch.setattr(ocr, "page_picture", lambda original, mime, page: _png())
    report = tmp_path / "report.json"  # the fake Tesseract writes it once it has the picture
    if how == "stand-in":

        def hangs(engine: Tesseract, png: bytes, *, stop: threading.Event | None = None, **_: object) -> str:
            assert stop is not None
            report.write_text("{}", "utf-8")
            if stop.wait(30):
                raise ocr.Stopped("Ordnung is stopping")
            raise AssertionError("never stopped")

        monkeypatch.setattr(ocr, "recognise", hangs)
        ctx.worker.find_tesseract = lambda: INSTALLED
    else:
        monkeypatch.setenv("FAKE_TESSERACT_MODE", "hang")
        monkeypatch.setenv("FAKE_TESSERACT_REPORT", str(report))
        fake = Tesseract(
            str(FAKE_TESSERACT), (5, 3, 4), ("deu", "eng"), launcher=(sys.executable, str(FAKE_TESSERACT))
        )
        ctx.worker.find_tesseract = lambda: fake

    await ctx.worker.start()
    await wait_for(report.exists)
    await asyncio.sleep(0.1)
    stopping = time.monotonic()
    await ctx.worker.stop(grace=2)
    assert time.monotonic() - stopping < 2
    assert not picture_file(ctx.store, doc_id).exists()
    assert ctx.store.picture_text_due() == [(doc_id, 1)]  # read at the next start
    assert database(ctx.store) == before
    if how == "with the engine" and sys.platform != "win32":  # Tesseract is gone (signal 0 only asks)
        pid = json.loads(report.read_text("utf-8"))["pid"]
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


async def test_a_page_tesseract_fails_on_waits_for_the_next_start(
    ctx: AppContext, engine: Engine, ocr_on: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A page Tesseract fails on is logged (letter and page, never what Tesseract printed) and skipped: not
    tried again while Ordnung runs — not after a wake, not when the worker starts again (hand-off sync standing
    by and back) — but at the next start of Ordnung."""
    broken = await private_photo(ctx, "kaputt.jpg", width=201)
    fine = await private_photo(ctx, "gut.jpg", width=202)
    engine.words = {file_name(ctx.store, broken): None, file_name(ctx.store, fine): "Ihr Kellerabteil 7"}
    caplog.set_level(logging.WARNING, logger="ordnung.ingest.worker")
    failed = f"could not read the words on page 1 of {broken}"
    await started(
        ctx, lambda: ctx.store.picture_text_matches("Kellerabteil") == {fine} and failed in caplog.text
    )
    assert "exit code 1" in caplog.text and "Kellerabteil" not in caplog.text

    await ctx.worker.start()  # started again in the same run of Ordnung, and woken by a reading
    try:
        await wait_for(lambda: engine.found == ["find", "find"])
        added = await add_file(ctx, photo("JPEG", size=(203, 100)), "noch.jpg", private=True)
        engine.words[file_name(ctx.store, added.id)] = "Gebäude Süd"
        await wait_for(lambda: ctx.store.picture_text_matches("Gebaude") == {added.id})
    finally:
        await ctx.worker.stop()
    assert engine.read.count((file_name(ctx.store, broken), 1)) == 1
    assert ctx.store.picture_text_due() == [(broken, 1)]

    engine.words[file_name(ctx.store, broken)] = "Hausverwaltung Beispiel"
    later = IngestWorker(ctx)  # Ordnung started again
    later.catch_up_delay_s = 0
    later.find_tesseract = engine.find
    await later.start()
    try:
        await wait_for(lambda: ctx.store.picture_text_matches("Hausverwaltung") == {broken})
    finally:
        await later.stop()


async def test_a_reload_tries_failed_pages_again(ctx: AppContext, engine: Engine, ocr_on: None) -> None:
    """Hand-off sync brought another computer's data here (``reload``): pages that failed are tried again."""
    doc_id = await private_photo(ctx, "foto.jpg")
    engine.words = {file_name(ctx.store, doc_id): None}
    await started(ctx, lambda: len(engine.read) == 1)
    engine.words = {file_name(ctx.store, doc_id): "Ihr Kellerabteil 7"}
    ctx.worker.reload()
    await started(ctx, lambda: ctx.store.picture_text_matches("Kellerabteil") == {doc_id})
    assert len(engine.read) == 2


async def test_turned_off_never_starts_tesseract_and_forgets_kept_picture_text(
    ctx: AppContext, engine: Engine
) -> None:
    """``ORDNUNG_OCR=off`` (as in every test): Tesseract is never looked for or run, and what it read before is
    removed when the worker starts; a scanner's text stays."""
    doc_id = await private_photo(ctx, "foto.jpg")
    scan = await add_file(ctx, scanned_pdf(ocr=True, blank_back=True), "scan.pdf", private=True)
    await ctx.worker.run_until_idle()
    assert ctx.store.write_picture_text(doc_id, 1, "Ihr Kellerabteil 7")
    assert ctx.store.write_picture_text(scan.id, 2, "Rückseite")
    await started(ctx, lambda: list(ctx.store.paths.derived.rglob("picture-text.json")) == [])
    assert engine.found == [] and engine.read == []
    assert ctx.store.scan_text_matches("Einkommensteuer") == {scan.id}


@pytest.mark.parametrize(
    "found",
    [None, Tesseract("/usr/bin/tesseract", (4, 0, 0), ("deu",)), Tesseract("/usr/bin/tesseract", None, ())],
    ids=["not installed", "too old", "didn't answer"],
)
async def test_without_tesseract_the_worker_does_nothing_else(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch, ocr_on: None, found: Tesseract | None
) -> None:
    """Without a usable Tesseract the loop looks once and ends: nothing listed, read or removed."""
    doc_id = await private_photo(ctx, "foto.jpg")
    assert ctx.store.write_picture_text(doc_id, 1, "Ihr Kellerabteil 7")
    looked: list[str] = []

    def find() -> Tesseract | None:
        looked.append("find")
        return found

    def never(*_: object, **__: object) -> list[tuple[str, int]]:
        raise AssertionError("nothing is listed without Tesseract")

    ctx.worker.find_tesseract = find
    monkeypatch.setattr(ctx.store, "picture_text_due", never)
    monkeypatch.setattr(ctx.store, "picture_text_stale", never)
    monkeypatch.setattr(ocr, "page_picture", never)
    monkeypatch.setattr(ocr, "recognise", never)
    await ctx.worker.start()
    try:
        await wait_for(lambda: looked == ["find"])
        await wait_for(lambda: ctx.worker._pictures is not None and ctx.worker._pictures.done())
    finally:
        await ctx.worker.stop()
    assert picture_file(ctx.store, doc_id).is_file()


async def test_the_picture_loop_stops_with_the_worker_before_its_delay(
    ctx: AppContext, engine: Engine, ocr_on: None
) -> None:
    """Stopped while it waits out the start delay: it never looks for Tesseract."""
    await private_photo(ctx, "foto.jpg")
    ctx.worker.catch_up_delay_s = 30
    await ctx.worker.start()
    stopping = time.monotonic()
    await ctx.worker.stop(grace=5)
    assert time.monotonic() - stopping < 1 and engine.found == []


async def test_the_engine_reads_a_private_photo_with_the_fake_tesseract(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch, ocr_on: None
) -> None:
    """With the engine: the photo is drawn, read by (the fake) Tesseract and kept for search only."""
    from fake_tesseract import ECHO_TEXT

    monkeypatch.setenv("FAKE_TESSERACT_MODE", "echo")
    fake = Tesseract(
        str(FAKE_TESSERACT), (5, 3, 4), ("deu", "eng"), launcher=(sys.executable, str(FAKE_TESSERACT))
    )
    ctx.worker.find_tesseract = lambda: fake
    doc_id = await private_photo(ctx, "foto.jpg")
    await started(ctx, lambda: ctx.store.picture_text_pages(doc_id) == [1])
    assert ctx.store.picture_text_matches("Kellerabteil") == {doc_id}
    kept = json.loads(picture_file(ctx.store, doc_id).read_text("utf-8"))
    assert kept == {"version": 1, "pages": {"1": ECHO_TEXT}}
