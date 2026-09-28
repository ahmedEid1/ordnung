"""The watched folder (``ingest.watcher``) with a real temporary folder: files are picked up once
their size and modification time stop changing, partial and temporary files, sub-folders and symbolic
links are ignored, files already there are picked up once (and never again, even once their letter is
deleted), files wait for the person by default and are read at once with ``inbox_auto_read``, the
watcher follows the setting, reports a missing folder, logs refused files and never changes the folder.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER, TODAY, Router, fake_backend, record_events
from helpers_docs import Line, make_pdf
from ordnung import clock
from ordnung.app_context import AppContext, build_context
from ordnung.ingest import held, intake, watcher
from ordnung.ingest.attachments import email_source
from ordnung.ingest.pipeline import release_held
from ordnung.ingest.watcher import (
    MISSING,
    NOT_A_FOLDER,
    SEEN_META_KEY,
    UNEXPECTED,
    FolderWatcher,
    SettleTracker,
    file_key,
    folder_problem,
    is_candidate,
    list_folder,
    read_file,
    recent_pickups,
)
from ordnung.llm.fake import FakeBackend
from ordnung.models import Document

FAST = {"settle_s": 0.25, "tick_ms": 50, "rescan_s": 0.4, "retry_s": 0.1}


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    folder = tmp_path / "scans"
    folder.mkdir()
    return folder


@pytest.fixture
def ctx(data_dir: Path, inbox: Path) -> Iterator[AppContext]:
    context = build_context(data_dir, backend_obj=fake_backend(Router()))
    use_folder(context, inbox)
    yield context
    context.close()


def use_folder(ctx: AppContext, folder: Path | None, **settings: Any) -> None:
    ctx.store.save_settings(
        ctx.store.get_settings().model_copy(update={"inbox_dir": str(folder) if folder else None, **settings})
    )
    ctx.reload_settings()


def backend(ctx: AppContext) -> FakeBackend:
    assert isinstance(ctx.llm.backend, FakeBackend)
    return ctx.llm.backend


async def eventually(check: Callable[[], Any], within: float = 15.0) -> Any:
    """Poll ``check`` until it returns something truthy (and return that)."""
    deadline = time.monotonic() + within
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() > deadline:
            raise AssertionError("gave up waiting")
        await asyncio.sleep(0.05)


@asynccontextmanager
async def watching(ctx: AppContext, **options: Any) -> AsyncIterator[FolderWatcher]:
    """A running watcher, once it listed the folder (files written after that *arrive*)."""
    folder_watcher = FolderWatcher(ctx, **{**FAST, **options})
    await folder_watcher.start()
    try:
        if ctx.settings.inbox_dir:
            await eventually(lambda: folder_watcher.state != "off")
        yield folder_watcher
    finally:
        await folder_watcher.stop()


def by_name(ctx: AppContext, filename: str) -> Document | None:
    return next(
        (doc for doc in ctx.store.list_documents(include_deleted=True) if doc.filename == filename), None
    )


def picked(ctx: AppContext, filename: str) -> Callable[[], Document | None]:
    return lambda: by_name(ctx, filename)


def pdf(text: str) -> bytes:
    return make_pdf([[Line(72, 90, text)]])


def logged(ctx: AppContext, kind: str) -> list[str]:
    return [entry.message for entry in ctx.store.list_activity(100, kinds=[kind])]


# --------------------------------------------------------------------------------------------------
# The policy (pure)
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "picked_up"),
    [
        ("Scan_2026-09-28.pdf", True),
        ("SCAN.PDF", True),
        ("IMG_0042.HEIC", True),
        ("foto.jpeg", True),
        ("mail.eml", True),
        ("notiz.txt", True),
        ("scan.pdf.part", False),
        ("scan.pdf.crdownload", False),
        ("scan.pdf.download", False),
        ("scan.pdf.partial", False),
        ("scan.pdf.tmp", False),
        ("scan.TEMP", False),
        ("~$brief.pdf", False),
        (".scan.pdf", False),
        (".DS_Store", False),
        ("scan.pdf~", False),
        ("brief.docx", False),
        ("Thumbs.db", False),
        ("archiv.zip", False),
        ("pdf", False),
        ("", False),
    ],
)
def test_which_files_are_picked_up(name: str, picked_up: bool) -> None:
    assert is_candidate(name) is picked_up


def test_a_file_counts_once_it_stopped_changing_and_has_content() -> None:
    tracker = SettleTracker(settle_s=2.0)
    tracker.observe({"a.pdf": (10, 1), "empty.pdf": (0, 1)}, now=100.0)
    assert tracker.ready(101.9) == [] and tracker.settling
    tracker.observe({"a.pdf": (20, 2), "empty.pdf": (0, 1)}, now=101.0)  # still being written
    assert tracker.ready(102.5) == []
    assert tracker.ready(103.0) == [("a.pdf", (20, 2))]
    tracker.done("a.pdf")
    assert tracker.ready(200.0) == [] and not tracker.settling  # an empty file waits for content
    tracker.observe({}, now=201.0)  # gone: forgotten
    tracker.observe({"empty.pdf": (5, 3)}, now=202.0)
    assert tracker.ready(203.9) == [] and tracker.ready(204.0) == [("empty.pdf", (5, 3))]


def test_files_are_remembered_without_their_names(tmp_path: Path) -> None:
    key = file_key(tmp_path, "Kündigung Müller.pdf", (10, 20))
    assert "Müller" not in key and len(key) == 24
    assert key != file_key(tmp_path, "Kündigung Müller.pdf", (10, 21))
    assert key != file_key(tmp_path / "other", "Kündigung Müller.pdf", (10, 20))


def test_folder_problems(tmp_path: Path) -> None:
    assert folder_problem(tmp_path) is None
    assert folder_problem(tmp_path / "nope") == MISSING
    (tmp_path / "file.pdf").write_bytes(b"x")
    assert folder_problem(tmp_path / "file.pdf") == NOT_A_FOLDER


def test_listing_skips_sub_folders_symlinks_and_other_files(inbox: Path, tmp_path: Path) -> None:
    (inbox / "brief.pdf").write_bytes(b"%PDF-1.4")
    (inbox / "sub").mkdir()
    (inbox / "sub" / "tief.pdf").write_bytes(b"%PDF-1.4")
    (inbox / "ordner.pdf").mkdir()  # a folder named like a file
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4 outside")
    (inbox / "link.pdf").symlink_to(outside)
    (inbox / "notes.docx").write_bytes(b"PK")
    assert list(list_folder(inbox)) == ["brief.pdf"]


def test_reading_a_file_never_follows_a_link_and_notices_changes(inbox: Path, tmp_path: Path) -> None:
    target = tmp_path / "outside.pdf"
    target.write_bytes(b"%PDF-1.4 secret")
    info = target.stat()
    (inbox / "link.pdf").symlink_to(target)
    assert read_file(inbox / "link.pdf", (info.st_size, info.st_mtime_ns)) is None
    assert read_file(target, (info.st_size, info.st_mtime_ns)) == b"%PDF-1.4 secret"
    assert read_file(target, (info.st_size + 1, info.st_mtime_ns)) is None  # changed since it settled
    assert read_file(inbox / "gone.pdf", (1, 1)) is None


def test_reading_stops_one_byte_past_the_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(watcher, "MAX_BYTES", 100)
    big = tmp_path / "big.pdf"
    big.write_bytes(b"x" * 10_000)
    info = big.stat()
    assert len(read_file(big, (info.st_size, info.st_mtime_ns)) or b"") == 101


# --------------------------------------------------------------------------------------------------
# Watching a real folder
# --------------------------------------------------------------------------------------------------


async def test_a_file_is_picked_up_once_it_stopped_changing(ctx: AppContext, inbox: Path) -> None:
    full = INVOICE_LETTER.pdf()
    async with watching(ctx, settle_s=1.0):
        target = inbox / "Scan_0001.pdf"
        with target.open("wb") as handle:  # a scanner writing in two goes
            handle.write(full[: len(full) // 2])
            handle.flush()
            await asyncio.sleep(0.2)
            handle.write(full[len(full) // 2 :])
        document = await eventually(picked(ctx, "Scan_0001.pdf"))
    assert document.sha256 == hashlib.sha256(full).hexdigest()
    assert len(ctx.store.list_documents()) == 1 and logged(ctx, "folder.refused") == []
    assert document.source == "folder"


async def test_partial_temporary_linked_and_nested_files_are_ignored(
    ctx: AppContext, inbox: Path, tmp_path: Path
) -> None:
    async with watching(ctx):
        for number, name in enumerate(
            ["a.pdf.part", "b.pdf.crdownload", "~$c.pdf", ".d.pdf", "e.pdf~", "f.tmp", "brief.docx"]
        ):
            (inbox / name).write_bytes(pdf(f"ignored {number}"))
        (inbox / "sub").mkdir()
        (inbox / "sub" / "nested.pdf").write_bytes(pdf("nested"))
        (tmp_path / "outside.pdf").write_bytes(pdf("outside"))
        (inbox / "link.pdf").symlink_to(tmp_path / "outside.pdf")
        await asyncio.sleep(0.6)
        (inbox / "real.pdf").write_bytes(pdf("real"))
        await eventually(picked(ctx, "real.pdf"))
        await asyncio.sleep(0.5)  # a few more listings
    assert [doc.filename for doc in ctx.store.list_documents()] == ["real.pdf"]


async def test_files_already_there_are_picked_up_once(ctx: AppContext, inbox: Path) -> None:
    (inbox / "while-closed.pdf").write_bytes(pdf("while closed"))
    async with watching(ctx):
        await eventually(picked(ctx, "while-closed.pdf"))
    async with watching(ctx):  # Ordnung restarts
        (inbox / "next.pdf").write_bytes(pdf("next"))
        await eventually(picked(ctx, "next.pdf"))
        await asyncio.sleep(0.5)
    assert len(ctx.store.list_documents()) == 2
    assert logged(ctx, "folder.known") == []
    assert len(logged(ctx, "document.added")) == 2


async def test_a_deleted_letter_does_not_come_back(ctx: AppContext, inbox: Path) -> None:
    (inbox / "brief.pdf").write_bytes(pdf("brief"))
    async with watching(ctx):
        document = await eventually(picked(ctx, "brief.pdf"))
    ctx.store.delete_document(document.id)  # deleted for good; the file stays in the folder
    async with watching(ctx):
        (inbox / "marker.pdf").write_bytes(pdf("marker"))
        await eventually(picked(ctx, "marker.pdf"))
        await asyncio.sleep(0.5)
    assert by_name(ctx, "brief.pdf") is None


async def test_a_letter_in_the_trash_stays_there(ctx: AppContext, inbox: Path) -> None:
    data = pdf("im Papierkorb")
    (inbox / "brief.pdf").write_bytes(data)
    async with watching(ctx):
        document = await eventually(picked(ctx, "brief.pdf"))
        ctx.store.trash_document(document.id)
        (inbox / "brief-kopie.pdf").write_bytes(data)  # the same content under another name
        await eventually(lambda: logged(ctx, "folder.known"))
    trashed = ctx.store.get_document(document.id)
    assert trashed is not None and trashed.deleted_at is not None
    assert logged(ctx, "folder.known") == ["“brief-kopie.pdf” in your watched folder is already in Ordnung"]


async def test_files_wait_for_the_person_and_are_never_sent(ctx: AppContext, inbox: Path) -> None:
    events = record_events(ctx.bus)
    async with watching(ctx):
        (inbox / "bescheid.pdf").write_bytes(TAX_LETTER.pdf())
        document = await eventually(picked(ctx, "bescheid.pdf"))
    assert (document.status, document.ai_private) == ("held", True)
    await ctx.worker.run_until_idle()  # stored and read on this computer only
    stored = ctx.store.get_document(document.id)
    assert stored is not None and stored.status == "held" and stored.processed_at is not None
    assert "Einkommensteuer" in ctx.store.get_document_text(document.id)  # searchable
    assert backend(ctx).calls == []
    assert not [data for kind, data in events if kind == "job.progress" and data.get("doc_id") == document.id]
    assert ("document.processed", {"doc_id": document.id, "status": "held"}) in events
    assert ("folder.updated", {"state": "watching", "doc_id": document.id, "held": True}) in events
    assert logged(ctx, "document.added") == [
        "Added “bescheid.pdf” from your watched folder · waiting for you"
    ]

    release_held(ctx, [document.id])
    await ctx.worker.run_until_idle()
    read = ctx.store.get_document(document.id)
    assert read is not None and read.status == "processed" and not read.ai_private
    assert read.kind == "tax_assessment" and backend(ctx).calls


async def test_with_auto_read_files_are_read_at_once(ctx: AppContext, inbox: Path) -> None:
    use_folder(ctx, inbox, inbox_auto_read=True)
    async with watching(ctx):
        (inbox / "bescheid.pdf").write_bytes(TAX_LETTER.pdf())
        document = await eventually(picked(ctx, "bescheid.pdf"))
    assert (document.status, document.ai_private) == ("queued", False)
    await ctx.worker.run_until_idle()
    read = ctx.store.get_document(document.id)
    assert read is not None and read.status == "processed"


async def test_where_nothing_can_be_read_files_always_wait(ctx: AppContext, inbox: Path) -> None:
    use_folder(ctx, inbox, inbox_auto_read=True)
    async with watching(ctx, can_read=False):  # the zero-token demo
        (inbox / "bescheid.pdf").write_bytes(TAX_LETTER.pdf())
        document = await eventually(picked(ctx, "bescheid.pdf"))
    assert document.status == "held"


async def test_the_watcher_follows_the_setting(ctx: AppContext, inbox: Path, tmp_path: Path) -> None:
    other = tmp_path / "downloads"
    other.mkdir()
    async with watching(ctx) as folder_watcher:
        await eventually(lambda: folder_watcher.state == "watching")
        use_folder(ctx, other)
        await folder_watcher.reconfigure()
        assert folder_watcher.folder == other
        (inbox / "old-folder.pdf").write_bytes(pdf("old"))
        (other / "new-folder.pdf").write_bytes(pdf("new"))
        await eventually(picked(ctx, "new-folder.pdf"))
        await asyncio.sleep(0.5)
        assert by_name(ctx, "old-folder.pdf") is None

        use_folder(ctx, None)
        await folder_watcher.reconfigure()
        assert (folder_watcher.state, folder_watcher.running) == ("off", False)


async def test_a_watcher_outside_the_server_does_not_follow_the_setting(ctx: AppContext) -> None:
    folder_watcher = FolderWatcher(ctx, **FAST)
    await folder_watcher.reconfigure()  # the settings route, without the server's lifespan
    assert not folder_watcher.running and folder_watcher.state == "off"


async def test_a_missing_folder_is_reported_and_watched_once_it_exists(
    ctx: AppContext, tmp_path: Path
) -> None:
    later = tmp_path / "not-yet"
    use_folder(ctx, later)
    async with watching(ctx) as folder_watcher:
        await eventually(lambda: folder_watcher.state == "problem")
        assert folder_watcher.problem == MISSING
        await asyncio.sleep(0.4)  # several retries: reported once
        assert logged(ctx, "folder.problem") == [f"Can't watch your folder: {MISSING}"]
        later.mkdir()
        (later / "brief.pdf").write_bytes(pdf("later"))
        await eventually(picked(ctx, "brief.pdf"))
        assert (folder_watcher.state, folder_watcher.problem) == ("watching", None)


async def test_refused_files_are_logged_with_the_reason(
    ctx: AppContext, inbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(intake, "MAX_BYTES", 60_000)
    monkeypatch.setattr(watcher, "MAX_BYTES", 60_000)
    async with watching(ctx):
        (inbox / "kaputt.pdf").write_bytes(b"%PDF-1.4 not really")
        (inbox / "gross.pdf").write_bytes(b"%PDF-1.4 " + b"0" * 70_000)
        await eventually(lambda: len(logged(ctx, "folder.refused")) == 2)
    assert ctx.store.list_documents() == []
    refused = {pickup.filename: pickup for pickup in recent_pickups(ctx.store)}
    assert (
        refused["kaputt.pdf"].outcome == "refused" and "could not be opened" in refused["kaputt.pdf"].detail
    )
    assert refused["gross.pdf"].detail.startswith("This file is larger than")
    assert refused["gross.pdf"].doc_id is None and refused["gross.pdf"].status is None


async def test_an_unexpected_error_is_logged_and_watching_goes_on(
    ctx: AppContext, inbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = watcher.add_file_result
    calls = 0

    async def flaky(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("disk on fire")
        return await real(*args, **kwargs)

    monkeypatch.setattr(watcher, "add_file_result", flaky)
    async with watching(ctx) as folder_watcher:
        (inbox / "first.pdf").write_bytes(pdf("first"))
        await eventually(lambda: logged(ctx, "folder.refused"))
        (inbox / "second.pdf").write_bytes(pdf("second"))
        await eventually(picked(ctx, "second.pdf"))
        assert folder_watcher.state == "watching"
    assert logged(ctx, "folder.refused") == [
        f"Couldn't add “first.pdf” from your watched folder: {UNEXPECTED}"
    ]


async def test_recent_pickups_list_what_became_of_each_file(ctx: AppContext, inbox: Path) -> None:
    data = pdf("zweimal")
    async with watching(ctx):
        (inbox / "a.pdf").write_bytes(data)
        document = await eventually(picked(ctx, "a.pdf"))
        (inbox / "a-kopie.pdf").write_bytes(data)
        await eventually(lambda: logged(ctx, "folder.known"))
        (inbox / "b.pdf").write_bytes(b"%PDF-1.4 broken")
        await eventually(lambda: logged(ctx, "folder.refused"))
    pickups = recent_pickups(ctx.store)
    assert [(p.filename, p.outcome, p.doc_id, p.status) for p in pickups] == [
        ("b.pdf", "refused", None, None),
        ("a-kopie.pdf", "known", document.id, "held"),
        ("a.pdf", "added", document.id, "held"),
    ]
    ctx.store.delete_document(document.id)
    assert [p.filename for p in recent_pickups(ctx.store)] == ["b.pdf"]  # nothing of the letter stays


async def test_the_folder_itself_is_never_changed(ctx: AppContext, inbox: Path) -> None:
    (inbox / "a.pdf").write_bytes(pdf("a"))
    (inbox / "b.txt").write_text("Liebe Sam, bis bald.\n", encoding="utf-8")
    (inbox / "c.pdf.part").write_bytes(b"partial")

    def snapshot() -> list[tuple[str, int, int, int]]:
        return sorted(
            (entry.name, entry.stat().st_size, entry.stat().st_mtime_ns, entry.stat().st_mode)
            for entry in os.scandir(inbox)
        )

    before = snapshot()
    async with watching(ctx):
        await eventually(lambda: len(ctx.store.list_documents()) == 2)
    await ctx.worker.run_until_idle()
    assert snapshot() == before


async def test_an_email_in_the_folder_waits_with_its_attachments(ctx: AppContext, inbox: Path) -> None:
    message = EmailMessage()
    message["From"] = "Muster Telecom <rechnung@muster-telecom.example>"
    message["Subject"] = "Ihre Rechnung"
    message.set_content("Im Anhang Ihre Rechnung.\n")
    message.add_attachment(
        INVOICE_LETTER.pdf(), maintype="application", subtype="pdf", filename="rechnung.pdf"
    )
    (inbox / "mail.eml").write_bytes(message.as_bytes())
    async with watching(ctx):
        parent = await eventually(picked(ctx, "mail.eml"))
        child = await eventually(picked(ctx, "rechnung.pdf"))
    assert child.source == email_source(parent.id)
    assert [doc.status for doc in (parent, child)] == ["held", "held"]
    assert [doc.id for doc in held.waiting(ctx.store)] == [parent.id, child.id]
    assert [p.filename for p in recent_pickups(ctx.store)] == ["mail.eml"]  # the folder brought one file


async def test_picked_up_files_are_remembered_in_the_database(ctx: AppContext, inbox: Path) -> None:
    (inbox / "a.pdf").write_bytes(pdf("a"))
    async with watching(ctx):
        await eventually(picked(ctx, "a.pdf"))
    stored = ctx.store.get_meta(SEEN_META_KEY)
    assert stored is not None and "a.pdf" not in stored
    info = (inbox / "a.pdf").stat()
    assert file_key(inbox, "a.pdf", (info.st_size, info.st_mtime_ns)) in stored


async def test_stopping_is_quick_and_can_be_repeated(ctx: AppContext) -> None:
    folder_watcher = FolderWatcher(ctx, **FAST)
    await folder_watcher.start()
    await eventually(lambda: folder_watcher.state == "watching")
    started = time.monotonic()
    await folder_watcher.stop()
    await folder_watcher.stop()
    assert time.monotonic() - started < 2.0
    assert (folder_watcher.state, folder_watcher.running) == ("off", False)


# --------------------------------------------------------------------------------------------------
# Review round 1: consent for files already there, copies, stops, odd names, access, size
# --------------------------------------------------------------------------------------------------


async def test_with_auto_read_the_files_already_there_still_wait(ctx: AppContext, inbox: Path) -> None:
    """Choosing ~/Downloads with auto-read on must not send every file in it to Claude: only files
    that arrive later are read at once — also after a restart."""
    (inbox / "old-tax.pdf").write_bytes(TAX_LETTER.pdf())
    (inbox / "old-bill.pdf").write_bytes(pdf("old bill"))
    use_folder(ctx, inbox, inbox_auto_read=True)  # the folder and the switch saved together
    async with watching(ctx):
        (inbox / "new.pdf").write_bytes(INVOICE_LETTER.pdf())
        old_tax = await eventually(picked(ctx, "old-tax.pdf"))
        old_bill = await eventually(picked(ctx, "old-bill.pdf"))
        new = await eventually(picked(ctx, "new.pdf"))
    assert [(doc.status, doc.ai_private) for doc in (old_tax, old_bill)] == [("held", True)] * 2
    assert (new.status, new.ai_private) == ("queued", False)
    (inbox / "while-closed.pdf").write_bytes(pdf("while closed"))  # arrives while Ordnung is closed
    async with watching(ctx):
        later = await eventually(picked(ctx, "while-closed.pdf"))
    assert later.status == "queued"  # the folder was watched before: it arrived
    await ctx.worker.run_until_idle()
    assert {doc.id for doc in held.waiting(ctx.store)} == {old_tax.id, old_bill.id}


async def test_the_files_already_there_wait_even_if_ordnung_stopped_before_them(
    ctx: AppContext, inbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for number in range(3):
        (inbox / f"old-{number}.pdf").write_bytes(pdf(f"old {number}"))
    use_folder(ctx, inbox, inbox_auto_read=True)
    real = watcher.add_file_result
    added = 0

    async def one_then_stop(*args: Any, **kwargs: Any) -> Any:
        nonlocal added
        added += 1
        if added > 1:
            await asyncio.sleep(30)  # Ordnung quits in the middle of the second file
        return await real(*args, **kwargs)

    monkeypatch.setattr(watcher, "add_file_result", one_then_stop)
    monkeypatch.setattr(watcher, "STOP_GRACE_S", 0.2)
    async with watching(ctx):
        await eventually(lambda: added == 2)
    monkeypatch.setattr(watcher, "add_file_result", real)
    async with watching(ctx):
        await eventually(lambda: len(ctx.store.list_documents()) == 3)
    assert {doc.status for doc in ctx.store.list_documents()} == {"held"}


async def test_a_copy_of_a_waiting_file_keeps_it_waiting_with_auto_read(ctx: AppContext, inbox: Path) -> None:
    async with watching(ctx):
        (inbox / "scan.pdf").write_bytes(TAX_LETTER.pdf())
        waiting = await eventually(picked(ctx, "scan.pdf"))
    use_folder(ctx, inbox, inbox_auto_read=True)
    async with watching(ctx):
        (inbox / "scan (1).pdf").write_bytes(TAX_LETTER.pdf())  # the browser saves it again
        await eventually(lambda: logged(ctx, "folder.known"))
    await ctx.worker.run_until_idle()
    still = ctx.store.get_document(waiting.id)
    assert still is not None and still.status == "held" and backend(ctx).calls == []
    assert logged(ctx, "document.released") == []


async def test_a_file_stopped_in_the_middle_is_picked_up_next_time(
    ctx: AppContext, inbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = watcher.add_file_result
    started = asyncio.Event()

    async def slow(*args: Any, **kwargs: Any) -> Any:
        started.set()
        await asyncio.sleep(30)  # a big scan being rendered
        return await real(*args, **kwargs)

    monkeypatch.setattr(watcher, "add_file_result", slow)
    monkeypatch.setattr(watcher, "STOP_GRACE_S", 0.2)
    async with watching(ctx):
        (inbox / "big-scan.pdf").write_bytes(TAX_LETTER.pdf())
        await asyncio.wait_for(started.wait(), 10)
    assert ctx.store.list_documents() == []  # stopped: nothing added, nothing remembered
    monkeypatch.setattr(watcher, "add_file_result", real)
    async with watching(ctx):
        document = await eventually(picked(ctx, "big-scan.pdf"))
    assert document.status == "held"


def test_names_that_are_not_utf8_are_shown_as_windows_1252() -> None:
    raw = os.fsdecode(b"Bescheid_M\xfcller.pdf")  # as os.scandir gives it on Linux
    assert watcher.display_name(raw) == "Bescheid_Müller.pdf"
    assert watcher.display_name("Kündigung.pdf") == "Kündigung.pdf"
    assert watcher.display_name(os.fsdecode(b"x\x81y.pdf")) == "x�y.pdf"


async def test_a_file_with_a_name_that_is_not_utf8_is_added(ctx: AppContext, inbox: Path) -> None:
    async with watching(ctx) as folder_watcher:
        (inbox / os.fsdecode(b"Bescheid_M\xfcller.pdf")).write_bytes(TAX_LETTER.pdf())  # Latin-1 bytes
        document = await eventually(picked(ctx, "Bescheid_Müller.pdf"))
        (inbox / "after.pdf").write_bytes(INVOICE_LETTER.pdf())
        await eventually(picked(ctx, "after.pdf"))  # the watching went on
        assert folder_watcher.state == "watching"
    assert document.status == "held"
    assert (
        logged(ctx, "document.added")[-1]
        == "Added “Bescheid_Müller.pdf” from your watched folder · waiting for you"
    )


def test_reading_a_file_ordnung_may_not_read_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    locked = tmp_path / "locked.pdf"
    locked.write_bytes(b"%PDF-1.4")

    def denied(*_args: Any, **_kwargs: Any) -> int:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(watcher.os, "open", denied)
    with pytest.raises(PermissionError):
        read_file(locked, (8, locked.stat().st_mtime_ns))


async def test_a_file_ordnung_may_not_read_is_reported_once(
    ctx: AppContext, inbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = watcher.read_file
    tries = 0

    def guarded(path: Path, expected: Any) -> bytes | None:
        nonlocal tries
        if path.name == "locked.pdf":
            tries += 1
            raise PermissionError(13, "Permission denied")
        return real(path, expected)

    monkeypatch.setattr(watcher, "read_file", guarded)
    async with watching(ctx):
        (inbox / "locked.pdf").write_bytes(pdf("locked"))
        await eventually(lambda: logged(ctx, "folder.refused"))
        await asyncio.sleep(1.0)  # several rescans
    assert tries == 1
    assert logged(ctx, "folder.refused") == [
        f"Couldn't add “locked.pdf” from your watched folder: {watcher.NOT_READABLE}"
    ]


async def test_what_is_remembered_follows_the_folder(ctx: AppContext, inbox: Path) -> None:
    """Files that left the folder are forgotten (it stays as small as the folder); one that comes
    back is picked up again and adds nothing."""
    async with watching(ctx):
        (inbox / "a.pdf").write_bytes(pdf("a"))
        (inbox / "b.pdf").write_bytes(pdf("b"))
        await eventually(lambda: len(ctx.store.list_documents()) == 2)
        info = (inbox / "a.pdf").stat()
        key = file_key(inbox, "a.pdf", (info.st_size, info.st_mtime_ns))
        moved = (inbox / "a.pdf").read_bytes()
        (inbox / "a.pdf").unlink()
        await eventually(lambda: key not in (ctx.store.get_meta(SEEN_META_KEY) or ""))
        (inbox / "a.pdf").write_bytes(moved)
        await eventually(lambda: logged(ctx, "folder.known"))
        await asyncio.sleep(1.0)  # several rescans: known once
    assert logged(ctx, "folder.known") == ["“a.pdf” in your watched folder is already in Ordnung"]
    assert len(ctx.store.list_documents()) == 2


async def test_a_folder_with_too_many_files_is_not_watched(
    ctx: AppContext, inbox: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watcher, "MAX_FILES", 3)
    for number in range(4):
        (inbox / f"{number}.pdf").write_bytes(pdf(str(number)))
    async with watching(ctx) as folder_watcher:
        await eventually(lambda: folder_watcher.state == "problem")
        assert folder_watcher.problem == watcher.TOO_MANY
        (inbox / "0.pdf").unlink()
        await eventually(lambda: folder_watcher.state == "watching")
        await eventually(lambda: len(ctx.store.list_documents()) == 3)


async def test_a_letter_ordnung_drafted_is_not_added_as_one_received(ctx: AppContext, inbox: Path) -> None:
    drafted = pdf("Kündigung · Sam Rivera · DE89 3704 0044 0532 0130 00")
    watcher.remember_own_file(ctx.store, drafted)
    assert watcher.is_own_file(ctx.store, drafted) and not watcher.is_own_file(ctx.store, pdf("other"))
    use_folder(ctx, inbox, inbox_auto_read=True)
    async with watching(ctx):
        (inbox / "kuendigung.pdf").write_bytes(drafted)
        await eventually(lambda: logged(ctx, "folder.refused"))
    assert ctx.store.list_documents() == [] and backend(ctx).calls == []
    (pickup,) = recent_pickups(ctx.store)
    assert (pickup.outcome, pickup.detail) == ("refused", watcher.OWN_LETTER)
