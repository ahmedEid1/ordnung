"""The watched folder (SPEC § 8): files a scanner, a phone app or a download saves into one folder are
added like letters dropped into the app. :class:`FolderWatcher` runs in the server's lifespan next to
the ingest worker and the daily tick, only while a folder is set (``settings.inbox_dir``).

The policy, which decides every case:

* **Which files** — files directly in the folder whose names end in a type Ordnung reads
  (:data:`WATCHED_SUFFIXES`, in any case). Sub-folders are not entered, and symbolic links are never
  followed, not even to a file. Partial and temporary files are ignored: names starting with ``.``
  or ``~$``, ending in ``~``, or ending in a download or temporary suffix (:data:`PARTIAL_SUFFIXES`,
  whatever comes before it).
* **When** — once its size and modification time have not changed for :data:`SETTLE_S` seconds and
  it is not empty (an empty file waits for its content). The folder is listed again on every change
  notification (``watchfiles``) and every :data:`RESCAN_S` seconds, which also catches folders whose
  notifications get lost (network and cloud drives).
* **Once** — a file is remembered by its folder, name, size and modification time (a hash kept in the
  database, the newest :data:`MAX_SEEN`): the same file is never picked up twice, even after a
  restart or after its letter was deleted; a changed file counts as new. Files already in the folder
  when watching starts are picked up once as well (a scan may have arrived while Ordnung was closed).
  A file whose content Ordnung already has adds nothing — document ids come from the content — and a
  letter in the trash stays there.
* **Intake** — every file goes through the normal intake with all its limits
  (:func:`~ordnung.ingest.pipeline.add_file_result`), ``source="folder"``; at most 50 MB of a file is
  read, so a larger one is refused without being loaded whole.
* **Consent** — unless ``settings.inbox_auto_read`` is on, a file is *held*: stored and read on this
  computer only, never sent to Claude until the person answers (:mod:`ordnung.ingest.held`). With it
  on, the file is read at once. Where letters can't be read at all (the zero-token demo), files are
  always held.
* **Read-only** — the folder is only listed and read (``O_NOFOLLOW``): nothing in it is ever written,
  moved or deleted.
* **Errors never stop the server** — a refused file is written to the activity log with the reason;
  a folder that is missing or can't be read is reported (:attr:`FolderWatcher.problem`, once in the
  activity log) and checked again every :data:`RETRY_S` seconds; when change notifications fail,
  watching falls back to polling.

Changing the folder in Settings restarts the watcher (:meth:`FolderWatcher.reconfigure`).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import stat
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from watchfiles import awatch

from ordnung.db.store import Store
from ordnung.ingest.intake import MAX_BYTES, IntakeError
from ordnung.ingest.pipeline import add_file_result
from ordnung.models import FolderOutcome, FolderPickup, FolderState

if TYPE_CHECKING:
    from ordnung.app_context import AppContext

log = logging.getLogger(__name__)

SOURCE = "folder"
WATCHED_SUFFIXES = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".txt", ".eml"})
PARTIAL_SUFFIXES = (".part", ".partial", ".crdownload", ".download", ".tmp", ".temp")
SETTLE_S = 2.0
RESCAN_S = 60.0
RETRY_S = 30.0
TICK_MS = 500
STOP_GRACE_S = 5.0
SEEN_META_KEY = "inbox_seen"
MAX_SEEN = 5000
RECENT = 6
#: Activity kinds of files the folder brought in (``document.added`` with ``data.source == "folder"``).
_OUTCOMES: dict[str, FolderOutcome] = {
    "document.added": "added",
    "folder.known": "known",
    "folder.refused": "refused",
}
PICKUP_KINDS = tuple(_OUTCOMES)

MISSING = "Ordnung can't find this folder. Check the path, or create the folder — Ordnung looks again every 30 seconds."
NOT_A_FOLDER = "This path is a file, not a folder. Choose the folder your scanner saves into."
NOT_ALLOWED = "Ordnung isn't allowed to read this folder. Check its permissions."
WATCH_FAILED = "Ordnung couldn't watch this folder. It tries again every 30 seconds."
UNEXPECTED = "Something went wrong while adding it."

Signature = tuple[int, int]
"""A file's size and modification time (ns): unchanged for :data:`SETTLE_S`, it counts as complete."""


# --------------------------------------------------------------------------------------------------
# The policy (pure)
# --------------------------------------------------------------------------------------------------


def is_candidate(name: str) -> bool:
    """Whether a file of this name is picked up (a type Ordnung reads, not a partial or temporary file)."""
    lower = name.lower()
    if not lower or lower.startswith((".", "~$")) or lower.endswith("~") or lower.endswith(PARTIAL_SUFFIXES):
        return False
    return PurePosixPath(lower).suffix in WATCHED_SUFFIXES


@dataclass
class _Settling:
    signature: Signature
    since: float


class SettleTracker:
    """Files not picked up yet, and since when (monotonic seconds) each has kept its signature."""

    def __init__(self, settle_s: float = SETTLE_S) -> None:
        self.settle_s = settle_s
        self._files: dict[str, _Settling] = {}

    def observe(self, listing: Mapping[str, Signature], now: float) -> None:
        """A fresh listing: files that are gone are forgotten, new or changed ones start settling."""
        for name in self._files.keys() - listing.keys():
            del self._files[name]
        for name, signature in listing.items():
            known = self._files.get(name)
            if known is None or known.signature != signature:
                self._files[name] = _Settling(signature, now)

    def ready(self, now: float) -> list[tuple[str, Signature]]:
        """Files unchanged for ``settle_s`` that are not empty, by name."""
        return sorted(
            (name, entry.signature)
            for name, entry in self._files.items()
            if entry.signature[0] > 0 and now - entry.since >= self.settle_s
        )

    def done(self, name: str) -> None:
        """Stop tracking ``name`` (picked up, or to be seen afresh)."""
        self._files.pop(name, None)

    @property
    def settling(self) -> bool:
        """Whether a file with content is still settling (the folder is then listed on every tick)."""
        return any(entry.signature[0] > 0 for entry in self._files.values())


def file_key(folder: Path, name: str, signature: Signature) -> str:
    """What a picked-up file is remembered by (no file name is stored)."""
    raw = f"{folder}\0{name}\0{signature[0]}\0{signature[1]}".encode("utf-8", "surrogateescape")
    return hashlib.sha256(raw).hexdigest()[:24]


# --------------------------------------------------------------------------------------------------
# The folder (read-only)
# --------------------------------------------------------------------------------------------------


def folder_problem(folder: Path) -> str | None:
    """Why ``folder`` can't be watched right now (``None``: it can)."""
    try:
        info = folder.stat()
    except FileNotFoundError:
        return MISSING
    except OSError:
        return NOT_ALLOWED
    if not stat.S_ISDIR(info.st_mode):
        return NOT_A_FOLDER
    if not os.access(folder, os.R_OK | os.X_OK):
        return NOT_ALLOWED
    return None


def list_folder(folder: Path) -> dict[str, Signature]:
    """The candidate regular files directly in ``folder`` and their signatures (symlinks not followed)."""
    found: dict[str, Signature] = {}
    with os.scandir(folder) as entries:
        for entry in entries:
            if not is_candidate(entry.name):
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            found[entry.name] = (info.st_size, info.st_mtime_ns)
    return found


def read_file(path: Path, expected: Signature) -> bytes | None:
    """The file's bytes (at most one byte past the intake limit) if it is still the regular file that
    settled — never through a symbolic link; ``None`` if it changed, moved or can't be opened."""
    flags = (
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    )
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or (info.st_size, info.st_mtime_ns) != expected:
            return None
        return handle.read(MAX_BYTES + 1)


# --------------------------------------------------------------------------------------------------
# What the folder brought in (from the activity log)
# --------------------------------------------------------------------------------------------------


def recent_pickups(store: Store, limit: int = RECENT) -> list[FolderPickup]:
    """The last files the folder brought in, newest first, with their letters' status now."""
    pickups: list[FolderPickup] = []
    for entry in store.list_activity(limit, kinds=PICKUP_KINDS, data={"source": SOURCE}):
        outcome = _OUTCOMES[entry.kind]
        document = store.get_document(entry.ref_id) if entry.ref_id else None
        live = document is not None and document.deleted_at is None
        pickups.append(
            FolderPickup(
                at=entry.ts,
                filename=str(entry.data.get("filename") or (document.filename if document else "")),
                outcome=outcome,
                detail=str(entry.data.get("detail") or ""),
                doc_id=document.id if live and document else None,
                status=document.status if live and document else None,
            )
        )
    return pickups


# --------------------------------------------------------------------------------------------------
# The watcher
# --------------------------------------------------------------------------------------------------


class FolderWatcher:
    """Watches ``settings.inbox_dir`` while the server runs (see the module docstring).

    ``can_read`` is off where letters can't be read at all (the zero-token demo): files are then always
    held. The timings are parameters so tests can run in fractions of a second.
    """

    def __init__(
        self,
        ctx: AppContext,
        *,
        can_read: bool = True,
        settle_s: float = SETTLE_S,
        rescan_s: float = RESCAN_S,
        retry_s: float = RETRY_S,
        tick_ms: int = TICK_MS,
        force_polling: bool | None = None,
    ) -> None:
        self.ctx = ctx
        self.can_read = can_read
        self.settle_s = settle_s
        self.rescan_s = rescan_s
        self.retry_s = retry_s
        self.tick_ms = tick_ms
        self.force_polling = force_polling
        self.folder: Path | None = None
        self.state: FolderState = "off"
        self.problem: str | None = None
        self._enabled = False
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None
        self._seen: list[str] = []
        self._seen_set: set[str] = set()

    # ------------------------------------------------------------------------------ lifecycle

    @property
    def running(self) -> bool:
        """Whether the watcher's task is running."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Watch the folder from the settings from now on (the server's lifespan calls this): starts
        at once when one is set, and follows later changes (:meth:`reconfigure`)."""
        self._enabled = True
        await self._start_task()

    async def stop(self) -> None:
        """Stop watching for good (the server shuts down): later settings changes start nothing."""
        self._enabled = False
        await self.pause()

    async def pause(self) -> None:
        """Stop the watching task — the current file is finished (for up to a few seconds) — but keep
        following the settings (``Delete everything`` pauses while the data goes)."""
        task, self._task = self._task, None
        if self._stop is not None:
            self._stop.set()
        if task is not None and not task.done():
            done, _ = await asyncio.wait({task}, timeout=STOP_GRACE_S)
            if not done:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._set_state("off")

    async def reconfigure(self) -> None:
        """Follow the settings: restart when the folder changed, stop when it was cleared. Nothing
        happens outside the server's lifespan (tests, ``ordnung openapi``)."""
        if not self._enabled:
            return
        configured = self.ctx.settings.inbox_dir
        if self.running and configured and Path(configured) == self.folder:
            return
        await self.pause()
        await self._start_task()

    async def _start_task(self) -> None:
        if self.running:
            return
        configured = self.ctx.settings.inbox_dir
        if not configured:
            self.folder = None
            self._set_state("off")
            return
        self.folder = Path(configured)
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(self.folder, self._stop), name="ordnung-folder-watcher")

    # ------------------------------------------------------------------------------ state

    def _set_state(self, state: FolderState, problem: str | None = None) -> None:
        if (state, problem) == (self.state, self.problem):
            return
        self.state, self.problem = state, problem
        if problem is not None:
            self.ctx.store.log_activity(
                "folder.problem",
                f"Can't watch your folder: {problem}",
                data={"source": SOURCE, "folder": str(self.folder or "")},
            )
        self.ctx.bus.publish("folder.updated", state=state)

    async def _pause(self, seconds: float, stop: asyncio.Event) -> bool:
        """Wait ``seconds`` unless stopped first; ``True`` when stopped."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), seconds)
        return stop.is_set()

    # ------------------------------------------------------------------------------ the loop

    async def _run(self, folder: Path, stop: asyncio.Event) -> None:
        polling = self.force_polling
        while not stop.is_set():
            problem = await asyncio.to_thread(folder_problem, folder)
            if problem is not None:
                self._set_state("problem", problem)
                if await self._pause(self.retry_s, stop):
                    return
                continue
            try:
                await self._watch(folder, stop, polling)
            except Exception:
                if stop.is_set():
                    return
                log.warning("watching %s failed", folder, exc_info=True)
                if not polling and await asyncio.to_thread(folder_problem, folder) is None:
                    polling = True  # change notifications failed (a watch limit, a network drive): poll
                    continue
                self._set_state("problem", await asyncio.to_thread(folder_problem, folder) or WATCH_FAILED)
                if await self._pause(self.retry_s, stop):
                    return

    async def _watch(self, folder: Path, stop: asyncio.Event, polling: bool | None) -> None:
        """List the folder on changes, every tick while files settle and every ``rescan_s``; pick up
        what settled. Returns when stopped; raises when the folder can't be listed or watched."""
        self._load_seen()
        tracker = SettleTracker(self.settle_s)
        self._set_state("watching")
        last_listing = -self.rescan_s
        list_now = True  # once at the start: the files that came while Ordnung was closed
        async for changes in awatch(
            folder,
            watch_filter=None,
            step=50,
            rust_timeout=self.tick_ms,
            yield_on_timeout=True,
            stop_event=stop,
            recursive=False,
            force_polling=polling,
            poll_delay_ms=self.tick_ms,
        ):
            now = time.monotonic()
            if changes or list_now or tracker.settling or now - last_listing >= self.rescan_s:
                listing = await asyncio.to_thread(list_folder, folder)
                last_listing, list_now = now, False
                tracker.observe(
                    {
                        name: sig
                        for name, sig in listing.items()
                        if file_key(folder, name, sig) not in self._seen_set
                    },
                    now,
                )
            for name, signature in tracker.ready(now):
                tracker.done(name)
                if stop.is_set():
                    return
                await self._pick_up(folder, name, signature)

    # ------------------------------------------------------------------------------ one file

    async def _pick_up(self, folder: Path, name: str, signature: Signature) -> None:
        """Add one settled file (never raises: a refused file is logged, an unexpected error too)."""
        data = await asyncio.to_thread(read_file, folder / name, signature)
        if data is None:
            return  # it changed or went away; the next listing sees it again
        self._remember(file_key(folder, name, signature))
        store = self.ctx.store
        hold = not (self.can_read and self.ctx.settings.inbox_auto_read)
        try:
            added = await add_file_result(
                self.ctx, data, name, hold=hold, source=SOURCE, restore_trashed=False
            )
        except IntakeError as exc:
            self._refused(name, str(exc))
            return
        except Exception:
            log.exception("adding %s from the watched folder failed", name)
            self._refused(name, UNEXPECTED)
            return
        if not added.new:
            store.log_activity(
                "folder.known",
                f"“{name}” in your watched folder is already in Ordnung",
                ref_type="document",
                ref_id=added.document.id,
                data={"source": SOURCE, "filename": name},
            )
        self.ctx.bus.publish(
            "folder.updated", state=self.state, doc_id=added.document.id, held=added.document.status == "held"
        )

    def _refused(self, name: str, reason: str) -> None:
        self.ctx.store.log_activity(
            "folder.refused",
            f"Couldn't add “{name}” from your watched folder: {reason}",
            data={"source": SOURCE, "filename": name, "detail": reason},
        )
        self.ctx.bus.publish("folder.updated", state=self.state)

    # ------------------------------------------------------------------------------ remembered files

    def _load_seen(self) -> None:
        try:
            stored = json.loads(self.ctx.store.get_meta(SEEN_META_KEY) or "[]")
        except ValueError:
            stored = []
        self._seen = [key for key in stored if isinstance(key, str)][-MAX_SEEN:]
        self._seen_set = set(self._seen)

    def _remember(self, key: str) -> None:
        if key in self._seen_set:
            return
        self._seen.append(key)
        self._seen_set.add(key)
        if len(self._seen) > MAX_SEEN:
            dropped, self._seen = self._seen[:-MAX_SEEN], self._seen[-MAX_SEEN:]
            self._seen_set.difference_update(dropped)
        self.ctx.store.set_meta(SEEN_META_KEY, json.dumps(self._seen))
