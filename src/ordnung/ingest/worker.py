"""Background ingestion worker: claims jobs from the queue of record and reads documents.

* Up to ``settings.concurrency`` documents at once, never one document twice (a job of a letter being
  read waits); ``start()`` first returns jobs a previous process left ``running`` to the queue.
* A rate limit pauses the worker globally until the reset time (or 15 minutes): the job goes back
  to ``queued`` with a ``waiting_reason``, ``llm.paused`` is published (``llm.resumed`` when it ends)
  and the pause survives restarts (meta ``llm_paused_until``).
* Claude not installed, not signed in or too old pauses reading too, without an end (``llm.paused``
  with an empty ``until``): the letter waits in the queue instead of failing, and so does every letter
  for Claude claimed meanwhile (put back for :data:`CLAUDE_RECHECK_S` seconds at a time; private letters
  are read as usual), and the API's cached Claude status is dropped (``claude_failed``). A letter put back
  this way first gets its own text read on this computer (once per job in a run of Ordnung,
  :func:`~ordnung.ingest.pipeline.read_text_here`), so search finds it by its words while it waits. Reading goes
  on once a check sees Claude ready (:meth:`IngestWorker.claude_ready` — the API's Claude status
  check, and the worker's own every :data:`CLAUDE_RECHECK_S` seconds through ``claude_check``);
  ``llm.resumed`` follows once a letter gets past Claude. When a reading fails the same way right
  after a check said "ready" (a key Claude refuses), the worker waits twice as long before its next
  check, up to :data:`CLAUDE_RECHECK_MAX_S`. A new process simply tries again.
* A page that connects during a pause hears of it first (:meth:`IngestWorker.current_pause`).
* Other failures (unreadable answers, a timeout …) fail the job and the document with a readable
  message — the pipeline records them.
* After each processed document the triggers engine runs, and after an edit
  of the ledger it runs in the background (:meth:`IngestWorker.refresh_ideas`: one run at a time, a
  change made meanwhile gets one more run; :meth:`IngestWorker.stop` waits for it, so its thread is
  done with the database before anything closes or wipes it).

``run_until_idle()`` processes everything that is due and returns — used by the CLI and tests.

The scanner text of scans stored before Ordnung kept it (ADR 0020) is caught up in the background, and a
scanner text Claude's reading made out of date elsewhere (on a computer still on 0.2.0) is tidied:
:data:`CATCH_UP_DELAY_S` seconds after :meth:`IngestWorker.start`, one letter at a time, never a model —
and it stops with the worker, which runs only while background work is allowed (never while hand-off
sync stands this computer by).

The words in the pictures of letters Claude isn't reading (kept private, held, waiting for Claude, failed)
are read the same way when Tesseract is installed (ADR 0024, :mod:`ordnung.ingest.ocr`): after the same
delay the worker looks for Tesseract once, then reads one page at a time, newest letter first, at low
priority, and keeps the words for the letter search only (``picture-text.json``, through the store); no
row of the database changes and no model is called. It looks again after each reading ends and every
:data:`PICTURES_POLL_S` seconds; a page Tesseract fails on is left until Ordnung starts again. Stopping the
worker stops a reading under way (Tesseract is killed). Off — in Settings (*Text in pictures*) or by
``ORDNUNG_OCR=off``, which wins (:func:`~ordnung.config.picture_text_off`) — Tesseract is never looked for,
and the words read earlier are removed when the worker starts. Without a usable Tesseract the loop ends after
its one look. The switch counts while Ordnung runs (:meth:`IngestWorker.picture_text_changed`, one change at a
time): saved off, the reading under way stops, the loop ends and every word read is removed; saved on, the loop
starts at once and looks for Tesseract afresh. While the worker is stopped nothing happens: the next start
reads the switch.

Readings and the Ideas refresh are background work for hand-off sync: they run in a context where the
person's writes aren't counted (:func:`~ordnung.db.store.background_context`), even when a request of
theirs queued them. When sync replaces the data under a running server, :meth:`IngestWorker.reload`
makes the next :meth:`~IngestWorker.start` recover the replaced database's interrupted jobs and read its
Claude pause again.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import re
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# how a job's ``waiting_reason`` starts while it waits for Claude: the store's, re-exported (the CLI reads it)
from ordnung.config import picture_text_off
from ordnung.db.store import WAITING_FOR_CLAUDE as WAITING_FOR_CLAUDE
from ordnung.db.store import background_context, person_write
from ordnung.ingest import ocr, pipeline
from ordnung.ingest.ocr import Tesseract
from ordnung.ingest.pipeline import READING_JOBS, ingest_document, read_text_here, run_triggers
from ordnung.llm.base import ClaudeAuthError, ClaudeNotInstalled, ClaudeOutdated, ClaudeRateLimited
from ordnung.llm.claude_cli import MIN_CLAUDE_VERSION, version_text
from ordnung.models import Job
from ordnung.trace.runs import recover_readings

if TYPE_CHECKING:
    from ordnung.app_context import AppContext

log = logging.getLogger(__name__)

PAUSE_META_KEY = "llm_paused_until"
DEFAULT_PAUSE = timedelta(minutes=15)
MAX_PAUSE = timedelta(hours=24)
_CLOCK_RE = re.compile(
    r"^(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)?\s*(?:\((?P<tz>[\w/+-]+)\))?$", re.I
)
_RELATIVE_RE = re.compile(r"^(?P<n>\d+(?:\.\d+)?)\s*(?P<unit>h|hours?|m|min|mins|minutes?)$", re.I)
_EPOCH_RE = re.compile(r"^\d{9,11}(?:\.\d+)?$")
#: Seconds between the worker's own checks for Claude while letters wait for it (zero tokens).
CLAUDE_RECHECK_S = 30.0
#: The longest time between those checks after checks said "ready" and readings failed all the same.
CLAUDE_RECHECK_MAX_S = 30 * 60.0
NOT_INSTALLED_REASON = "Claude Code isn't installed on this computer yet."
NOT_SIGNED_IN_REASON = "Claude Code isn't signed in."
OUTDATED_REASON = (
    f"Claude Code isn't up to date — Ordnung needs version {version_text(MIN_CLAUDE_VERSION)} or newer. "
    "Run “claude update” in a terminal to update it."
)
#: How the reason of a letter waiting because Claude is not installed, not signed in or too old starts.
_NOT_READY = f"{WAITING_FOR_CLAUDE}: Claude Code isn't "
#: Seconds after the worker starts before it catches up the scanner text of older scans, and starts reading
#: the words in pictures (startup and the first readings go first).
CATCH_UP_DELAY_S = 30.0
#: Seconds between the worker's looks for pictures to read when no reading ended meanwhile (a letter kept
#: private on another computer, brought here by hand-off sync, is found this way).
PICTURES_POLL_S = 300.0


def _now() -> datetime:
    return datetime.now(UTC)


def _look_for_tesseract() -> Tesseract | None:
    """The Tesseract this start of the worker reads pictures with: looked for afresh (it may have been installed
    since Ordnung last started); ``None`` when there is none or text in pictures is turned off."""
    return ocr.find(refresh=True)


def _parse_clock(text: str, now: datetime) -> datetime | None:
    match = _CLOCK_RE.match(text)
    if match is None:
        return None
    hour, minute = int(match["h"]), int(match["m"] or 0)
    if match["ampm"]:
        hour = hour % 12 + (12 if match["ampm"].lower() == "pm" else 0)
    try:
        zone = ZoneInfo(match["tz"]) if match["tz"] else None
        local_now = now.astimezone(zone)
        moment = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return moment if moment > local_now else moment + timedelta(days=1)


def parse_reset(value: str | None, now: datetime) -> datetime | None:
    """When a usage limit resets, from Claude's hint: ISO time, epoch seconds, "3pm (Europe/Berlin)",
    "15:00" or "2 hours". ``None`` if it cannot be read."""
    text = (value or "").strip()
    if not text:
        return None
    if _EPOCH_RE.match(text):
        return datetime.fromtimestamp(float(text), UTC)
    relative = _RELATIVE_RE.match(text)
    if relative is not None:
        amount = float(relative["n"])
        return now + (
            timedelta(hours=amount) if relative["unit"].lower().startswith("h") else timedelta(minutes=amount)
        )
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return _parse_clock(text, now)
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def pause_until(reset_at: str | None, now: datetime) -> datetime:
    """The end of a rate-limit pause: the reset time if plausible (within 24 h), else 15 minutes."""
    parsed = parse_reset(reset_at, now)
    if parsed is None or parsed <= now or parsed - now > MAX_PAUSE:
        return now + DEFAULT_PAUSE
    return parsed.astimezone(UTC)


def clock_time(moment: datetime, zone: str) -> str:
    """``HH:MM`` of ``moment`` in the person's time zone (the computer's when the zone is unknown)."""
    try:
        return moment.astimezone(ZoneInfo(zone)).strftime("%H:%M")
    except (ZoneInfoNotFoundError, ValueError):
        return moment.astimezone().strftime("%H:%M")


class IngestWorker:
    """Reads queued documents in the background (see the module docstring)."""

    POLL_SECONDS: ClassVar[float] = 1.0
    JOB_KINDS: ClassVar[tuple[str, ...]] = READING_JOBS

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.paused_until: datetime | None = self._stored_pause()
        #: Why reading waits for Claude (not installed, not signed in); ``None`` while it doesn't.
        self.waiting_for_claude: str | None = None
        #: Checks whether Claude is ready now (zero tokens); set by the API, which owns that check.
        self.claude_check: Callable[[], Awaitable[bool]] | None = None
        #: Drops the API's cached Claude status after a reading found Claude not ready (set by the API).
        self.claude_failed: Callable[[], None] | None = None
        #: The wait for Claude the app was told of (``llm.paused``), until a letter gets past Claude.
        self._told_waiting: str | None = None
        #: Why letters waited when a check last said Claude was ready, until a reading shows whether it is.
        self._ready_after: str | None = None
        #: Seconds between the worker's own checks for Claude now (see :meth:`_wait_for_claude`).
        self.claude_recheck_s = CLAUDE_RECHECK_S
        self._pause_reason = ""
        self._checked_claude_at: float | None = None
        self._claude_checking: asyncio.Task[None] | None = None
        self._ideas: asyncio.Task[None] | None = None
        self._ideas_again = False
        self._active: set[asyncio.Task[None]] = set()
        self._loop_task: asyncio.Task[None] | None = None
        self._wake: asyncio.Event | None = None
        self._stopping = False
        self._recovered = False
        #: The jobs of letters waiting for Claude whose own text was read on this computer in this run of
        #: Ordnung (by job: a letter deleted for good and added again keeps its id, and is read again).
        self._text_read: set[str] = set()
        #: Seconds after :meth:`start` before the scanner text of older scans is caught up.
        self.catch_up_delay_s = CATCH_UP_DELAY_S
        self._catch_up: asyncio.Task[None] | None = None
        self._halt: asyncio.Event | None = None
        #: Looks for the Tesseract that reads pictures (ADR 0024), once per start; replaced in tests.
        self.find_tesseract: Callable[[], Tesseract | None] = _look_for_tesseract
        #: Seconds between looks for pictures to read when no reading ended meanwhile.
        self.pictures_poll_s = PICTURES_POLL_S
        self._pictures: asyncio.Task[None] | None = None
        #: Ends the pictures loop alone (the switch turned off), apart from the scanner text's catch-up.
        self._pictures_halt: asyncio.Event | None = None
        self._pictures_wake: asyncio.Event | None = None
        self._picture_stop: threading.Event | None = None
        #: One change of the *Text in pictures* switch at a time (:meth:`picture_text_changed`).
        self._pictures_switch = asyncio.Lock()
        #: (letter, page) Tesseract failed on in this run of Ordnung: left until Ordnung starts again.
        self._picture_failed: set[tuple[str, int]] = set()

    # ---------------------------------------------------------------------------------- state

    @property
    def running(self) -> bool:
        """Whether the background loop is running."""
        return self._loop_task is not None and not self._loop_task.done()

    @property
    def concurrency(self) -> int:
        """How many documents are read at the same time."""
        return max(1, self.ctx.settings.concurrency)

    def is_paused(self) -> bool:
        """Whether model calls are paused because of a rate limit."""
        return self.paused_until is not None and self.paused_until > _now()

    def notify(self) -> None:
        """Wake the background loop (a job was queued)."""
        if self._wake is not None:
            self._wake.set()

    def current_pause(self) -> dict[str, str] | None:
        """What a page that connects now hears first (``llm.paused``'s data): the wait for Claude the app was
        told of, else a usage limit that hasn't ended; ``None`` while reading goes on."""
        if self._told_waiting is not None and self._letter_waits_for_claude():
            return {"until": "", "reason": self._told_waiting}
        if self.paused_until is not None and self.is_paused():
            return {"until": self.paused_until.isoformat(), "reason": self._pause_reason}
        return None

    def claude_ready(self) -> None:
        """A check found Claude installed and signed in: the letters waiting for it are read now, and no longer
        say they wait. The app hears that reading goes on once one of them gets past Claude (or now, when
        none waits)."""
        if self.waiting_for_claude is None:
            return
        self._ready_after = self.waiting_for_claude
        self.waiting_for_claude = None
        self._checked_claude_at = None
        store = self.ctx.store
        released = 0
        for job in store.list_jobs(active_only=True):
            if job.status == "queued" and job.waiting_reason and job.waiting_reason.startswith(_NOT_READY):
                with contextlib.suppress(Exception):  # deleted meanwhile
                    store.update_job(job.id, not_before=None, waiting_reason=None)
                    released += 1
                    self.ctx.bus.publish(
                        "job.progress",
                        job_id=job.id,
                        doc_id=job.doc_id,
                        stage="intake",
                        progress=0.0,
                        status="queued",
                    )
        if not released:
            self._reading_goes_on()
        self.notify()

    def _reading_goes_on(self, *, seen: bool = False) -> None:
        """The wait for Claude is over: the app hears so (``llm.resumed``) when it was told of the wait — or may
        have seen it on a letter's job (``seen``) — and no usage limit still pauses reading."""
        if self._told_waiting is None and not seen:
            return
        self._claude_answered()
        if not self.is_paused():
            self.ctx.bus.publish("llm.resumed")

    def _claude_answered(self) -> None:
        """Claude answered a reading (or said its usage limit was reached): it is installed and signed in."""
        self._told_waiting = None
        self._ready_after = None
        self.claude_recheck_s = CLAUDE_RECHECK_S

    def _stored_pause(self) -> datetime | None:
        raw = self.ctx.store.get_meta(PAUSE_META_KEY)
        if not raw:
            return None
        try:
            moment = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return moment if moment > _now() else None

    # ---------------------------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Recover interrupted jobs and start the background loop (no-op if already running)."""
        if self.running:
            return
        self._recover()
        self._stopping = False
        self._wake = asyncio.Event()
        self._loop_task = asyncio.create_task(
            self._run(), name="ordnung-ingest-worker", context=background_context()
        )
        self._halt = asyncio.Event()
        self._catch_up = asyncio.create_task(
            self._catch_up_scan_text(self._halt), name="ordnung-scan-text", context=background_context()
        )
        self._start_pictures(self.catch_up_delay_s)

    def _start_pictures(self, delay: float) -> None:
        """Start the pictures loop (:meth:`_read_pictures`), with its own halt, wake and stop, after ``delay``."""
        self._pictures_halt = asyncio.Event()
        self._pictures_wake = asyncio.Event()
        self._picture_stop = threading.Event()
        self._pictures = asyncio.create_task(
            self._read_pictures(self._pictures_halt, self._pictures_wake, self._picture_stop, delay=delay),
            name="ordnung-pictures",
            context=background_context(),
        )

    async def picture_text_changed(self) -> None:
        """The *Text in pictures* switch was saved: do what it says now (Settings → Data; ``ORDNUNG_OCR=off`` wins).
        Off: a reading under way stops (Tesseract is killed within a poll), the loop ends, and every word read in
        pictures is removed. On, with no loop running: the loop starts without the start delay and looks for
        Tesseract afresh (it may have been installed since). One change at a time, so saves made together never
        leave two loops; nothing while the worker is stopped (the next :meth:`start` reads the switch)."""
        async with self._pictures_switch:
            if self._stopping or not self.running:
                return
            if picture_text_off(self.ctx.settings.read_picture_text):
                task = self._pictures
                if task is not None and not task.done():
                    for event in (self._pictures_halt, self._pictures_wake):
                        if event is not None:
                            event.set()
                    if self._picture_stop is not None:
                        self._picture_stop.set()
                    await asyncio.gather(task, return_exceptions=True)
                if self._pictures is task:
                    self._pictures = None
                await self._forget_picture_text()
            elif self._pictures is None or self._pictures.done():
                self._start_pictures(0)

    async def _forget_picture_text(self) -> None:
        """Text in pictures is off: remove every word read in pictures (a scanner's text stays)."""
        try:
            forgotten = await asyncio.to_thread(self.ctx.store.forget_all_picture_text)
        except Exception:
            log.warning("could not forget the words read in pictures", exc_info=True)
            return
        if forgotten:
            log.info("text in pictures is turned off: forgot the words read in %d letter(s)", forgotten)

    def reload(self) -> None:
        """The database was replaced (hand-off sync brought another computer's Ordnung here) while the
        worker was stopped: the next :meth:`start` recovers its interrupted jobs and readings, and the
        Claude pause is read again from it."""
        if self.running:
            raise RuntimeError("stop the worker before the database is replaced")
        self._recovered = False
        self._text_read.clear()  # its waiting letters' text is read again
        self._picture_failed.clear()  # and the pictures Tesseract failed on are tried again
        self.paused_until = self._stored_pause()

    async def stop(self, grace: float = 10.0) -> None:
        """Stop gracefully: documents in progress get ``grace`` seconds, then go back to the queue."""
        self._stopping = True
        self.notify()
        if self._loop_task is not None:
            await self._loop_task
            self._loop_task = None
        # held here: a stop running at the same time (hand-off sync standing by while Ordnung stops) may
        # clear the attributes while this one waits
        catch_up, pictures = self._catch_up, self._pictures
        background = {task for task in (catch_up, pictures) if task is not None}
        if background:  # the letter or page under way gets ``grace`` seconds too
            for halt in (self._halt, self._pictures_halt):
                if halt is not None:
                    halt.set()
            if self._picture_stop is not None:
                self._picture_stop.set()  # a reading under way stops (Tesseract is killed) within a poll
            if self._pictures_wake is not None:
                self._pictures_wake.set()
            _, unfinished = await asyncio.wait(background, timeout=grace)
            for task in unfinished:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            if catch_up is not None and self._catch_up is catch_up:
                self._catch_up = None
            if pictures is not None and self._pictures is pictures:
                self._pictures = None
        if self._claude_checking is not None:
            self._claude_checking.cancel()
            await asyncio.gather(self._claude_checking, return_exceptions=True)
            self._claude_checking = None
        if self._active:
            _, pending = await asyncio.wait(set(self._active), timeout=grace)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        await self.ideas_settled()
        self._wake = None

    async def run_until_idle(self) -> int:
        """Read every due job until the queue is empty (or paused); returns how many jobs ran."""
        with person_write(False):  # reading is background work, whoever asks for it
            self._recover()
            finished = 0
            while True:
                self._fill()
                if not self._active:
                    return finished
                done, _ = await asyncio.wait(set(self._active), return_when=asyncio.FIRST_COMPLETED)
                self._active.difference_update(done)
                finished += len(done)

    def refresh_ideas(self) -> None:
        """Run the triggers in the background after an edit of the ledger: now, or once more right after
        the run under way (which may have read the ledger before the edit)."""
        if self._ideas is not None and not self._ideas.done():
            self._ideas_again = True
            return
        self._ideas = asyncio.create_task(
            self._refresh_ideas(), name="ordnung-ideas-refresh", context=background_context()
        )

    async def _refresh_ideas(self) -> None:
        self._ideas_again = True
        while self._ideas_again:
            self._ideas_again = False
            await run_triggers(self.ctx)

    async def ideas_settled(self) -> None:
        """Wait until no background run of the triggers is under way or due."""
        while self._ideas is not None and not self._ideas.done():
            await asyncio.shield(self._ideas)

    async def _catch_up_scan_text(self, halt: asyncio.Event) -> None:
        """Keep the scanner text of the scans stored before Ordnung kept it (ADR 0020), then forget the out of
        date scanner text of pages Claude has read since: after :attr:`catch_up_delay_s`, one letter at a time
        in a thread, until done or the worker stops (``halt``; the letter under way is finished first). A
        letter that fails is logged and left for the next start."""
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(halt.wait(), self.catch_up_delay_s)
        if halt.is_set():
            return
        store = self.ctx.store
        try:
            missing = await asyncio.to_thread(store.scan_text_missing)
            stale = await asyncio.to_thread(store.scan_text_stale)
        except Exception:
            log.warning("could not list the scans whose scanner text is missing", exc_info=True)
            return
        work: list[tuple[str, Callable[[], None]]] = [
            *((doc_id, functools.partial(pipeline.catch_up_scan_text, store, doc_id)) for doc_id in missing),
            *((doc_id, functools.partial(store.forget_scan_text_once_read, doc_id)) for doc_id in stale),
        ]
        for doc_id, step in work:
            if halt.is_set():
                return
            try:
                await asyncio.to_thread(step)
            except Exception:
                log.warning("could not keep the scanner text of %s", doc_id, exc_info=True)

    async def _read_pictures(
        self, halt: asyncio.Event, wake: asyncio.Event, stop: threading.Event, *, delay: float
    ) -> None:
        """Read the words in the pictures of the letters Claude isn't reading (ADR 0024; the module docstring).
        Turned off (in Settings or by ``ORDNUNG_OCR``): forget what was read before, and end. Else after ``delay``
        seconds look for Tesseract once (none usable: end), then read the due pages one at a time until ``halt``,
        looking again whenever ``wake`` is set (a reading ended) or :attr:`pictures_poll_s` passed; ``stop`` stops
        a reading under way."""
        if picture_text_off(self.ctx.settings.read_picture_text):
            await self._forget_picture_text()
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(halt.wait(), delay)
        if halt.is_set():
            return
        try:
            engine = await asyncio.to_thread(self.find_tesseract)
        except Exception:
            log.warning("could not look for Tesseract", exc_info=True)
            return
        if engine is None or not engine.usable:
            return
        while not halt.is_set():
            wake.clear()
            try:
                due = await asyncio.to_thread(self._pictures_due)
            except Exception:
                log.warning("could not list the pictures to read", exc_info=True)
                due = []
            if not due:
                if halt.is_set():
                    return
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(wake.wait(), self.pictures_poll_s)
                continue
            for doc_id, page in due:
                if halt.is_set() or wake.is_set():
                    break  # stopping, or a reading ended: what is due first may have changed
                # nothing kept is no failure (the letter was let through to Claude meanwhile, or is gone): the
                # next look lists the page again only once it is due again
                try:
                    await asyncio.to_thread(self._read_picture, engine, doc_id, page, stop)
                except ocr.Stopped:
                    return
                except ocr.RecognitionError as exc:  # its message never holds what Tesseract printed
                    log.warning("could not read the words on page %d of %s: %s", page, doc_id, exc)
                    self._picture_failed.add((doc_id, page))
                except Exception:  # a file that can't be written too (OSError: the store logged it)
                    log.warning("could not read the words on page %d of %s", page, doc_id, exc_info=True)
                    self._picture_failed.add((doc_id, page))

    def _pictures_due(self) -> list[tuple[str, int]]:
        """Tidy the words read in pages Claude has read since, then list the pages to read (in a thread)."""
        store = self.ctx.store
        for doc_id in store.picture_text_stale():
            store.forget_scan_text_once_read(doc_id)
        return [pair for pair in store.picture_text_due() if pair not in self._picture_failed]

    def _read_picture(self, engine: Tesseract, doc_id: str, page: int, stop: threading.Event) -> bool:
        """Draw the page, have Tesseract read it and keep the words (in a thread); ``False``: nothing kept, as the
        letter is gone or no longer one whose pictures are read. Raises when the reading or the keeping failed."""
        store = self.ctx.store
        document = store.get_document(doc_id)
        original = store.get_document_file(doc_id)
        if document is None or original is None:
            return False
        picture = ocr.page_picture(original, document.mime, page)
        if stop.is_set():
            raise ocr.Stopped("Ordnung is stopping")
        return store.write_picture_text(doc_id, page, ocr.recognise(engine, picture, stop=stop))

    def _recover(self) -> None:
        if not self._recovered:
            requeued = self.ctx.store.requeue_running_jobs()
            if requeued:
                log.info("requeued %d interrupted job(s)", requeued)
            # the readings those jobs were in the middle of stopped with the previous process
            recover_readings(self.ctx.store)
            self._recovered = True

    async def _run(self) -> None:
        while not self._stopping:
            try:
                self._fill()
            except Exception:  # a broken queue read must not kill the worker
                log.exception("the ingest worker could not claim a job")
            await self._sleep()

    async def _sleep(self) -> None:
        if self._wake is None:
            return
        timeout = self.POLL_SECONDS
        if self.paused_until is not None and self.is_paused():
            timeout = min(max((self.paused_until - _now()).total_seconds(), 0.05), 60.0)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout)
        self._wake.clear()

    # ---------------------------------------------------------------------------------- jobs

    def _fill(self) -> int:
        """Claim due jobs up to the concurrency limit; returns how many were started."""
        self._maybe_resume()
        if self.waiting_for_claude is not None:
            self._check_claude()
        started = 0
        while not self._stopping and len(self._active) < self.concurrency and not self.is_paused():
            job = self.ctx.store.claim_next_job(self.JOB_KINDS)
            if job is None:
                break
            task = asyncio.create_task(
                self._run_job(job), name=f"ordnung-ingest-{job.doc_id}", context=background_context()
            )
            self._active.add(task)
            task.add_done_callback(self._job_finished)
            started += 1
        return started

    def _job_finished(self, task: asyncio.Task[None]) -> None:
        self._active.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("ingest task crashed", exc_info=task.exception())
        self.notify()
        if self._pictures_wake is not None:  # a letter may have become one whose pictures are read (ADR 0024)
            self._pictures_wake.set()

    async def _run_job(self, job: Job) -> None:
        store = self.ctx.store
        if job.doc_id is None:
            store.update_job(job.id, status="failed", error="This job has no document to read.")
            return
        why = self.waiting_for_claude
        if why is not None and self._needs_claude(job.doc_id):
            try:
                await self._read_text_here(job.id, job.doc_id)
            except asyncio.CancelledError:
                self._park(job, why, said=job.waiting_reason)
                raise
            if self.waiting_for_claude is not None:  # else Claude got ready meanwhile: read it now
                self._park(job, self.waiting_for_claude, said=job.waiting_reason)
                return
        # it waited for Claude in an earlier process: a page may have shown that wait from the job
        waited = bool(job.waiting_reason and job.waiting_reason.startswith(_NOT_READY))
        if job.waiting_reason or job.not_before:
            store.update_job(job.id, waiting_reason=None, not_before=None)
        try:
            await ingest_document(
                self.ctx, job.doc_id, force=job.force or job.kind == "reprocess", job_id=job.id
            )
        except ClaudeRateLimited as exc:
            self._pause(job, exc)
            return
        except (ClaudeNotInstalled, ClaudeAuthError) as exc:
            self._wait_for_claude(job, exc)
            return
        except asyncio.CancelledError:
            self._requeue(job, "Ordnung was stopped before this letter was finished; it will continue.")
            raise
        except Exception:
            # the pipeline recorded the failure on the job and the document; Claude was ready all the same
            self._got_past_claude(job, waited)
            return
        self._got_past_claude(job, waited)
        await run_triggers(self.ctx)

    async def _read_text_here(self, job_id: str, doc_id: str) -> None:
        """A letter waits for Claude: read its own text on this computer, once per job in a run of Ordnung, so
        search finds it while it waits (:func:`~ordnung.ingest.pipeline.read_text_here`). Remembered by job, not
        by letter: a letter deleted for good and added again has the same id (it is made from the file) but a new
        job, and is read again. A failure is logged: the letter waits all the same."""
        if job_id in self._text_read:
            return
        self._text_read.add(job_id)
        try:
            await read_text_here(self.ctx, doc_id)
        except Exception:
            log.warning("could not read the text of waiting letter %s", doc_id, exc_info=True)

    def _got_past_claude(self, job: Job, waited: bool) -> None:
        """A letter for Claude was read (or failed for a reason of its own): the wait for Claude is over."""
        if self.waiting_for_claude is not None or (self._told_waiting is None and not waited):
            return  # nothing waited, or another letter just found Claude not ready
        if self._needs_claude(job.doc_id):
            self._reading_goes_on(seen=waited)

    def _requeue(self, job: Job, reason: str, not_before: datetime | None = None) -> None:
        with contextlib.suppress(Exception):
            self.ctx.store.update_job(job.id, status="queued", waiting_reason=reason, not_before=not_before)

    def _pause(self, job: Job, exc: ClaudeRateLimited) -> None:
        until = pause_until(exc.reset_at, _now())
        if self.paused_until is None or until > self.paused_until:
            self.paused_until = until
            self.ctx.store.set_meta(PAUSE_META_KEY, until.isoformat())
        local = clock_time(self.paused_until, self.ctx.store.get_profile().timezone)
        reason = f"{WAITING_FOR_CLAUDE}: the usage limit was reached. Ordnung continues at about {local}."
        self._requeue(job, reason, not_before=self.paused_until)
        self._claude_answered()  # this pause replaces a wait for Claude the app heard of
        self._pause_reason = str(exc)
        self.ctx.bus.publish("llm.paused", until=self.paused_until.isoformat(), reason=self._pause_reason)
        self.ctx.bus.publish(
            "job.progress",
            job_id=job.id,
            doc_id=job.doc_id,
            stage="intake",
            progress=0.0,
            status="queued",
            waiting_reason=reason,
        )

    def _wait_for_claude(self, job: Job, exc: ClaudeNotInstalled | ClaudeAuthError) -> None:
        """The pipeline paused the letter because Claude isn't ready (it put it back to ``queued``; a held
        letter keeps the status its answer gave it): its job goes back to the queue, waiting, and so do the
        letters for Claude after it. The API's cached status is dropped, so its next check asks Claude again;
        when a check said "ready" just before this same failure, the next one waits twice as long."""
        if isinstance(exc, ClaudeOutdated):
            why = OUTDATED_REASON
        else:
            why = NOT_INSTALLED_REASON if isinstance(exc, ClaudeNotInstalled) else NOT_SIGNED_IN_REASON
        if self.claude_failed is not None:
            self.claude_failed()
        if self.waiting_for_claude is None:
            if self._ready_after is not None:
                again = why == self._ready_after
                self.claude_recheck_s = (
                    min(self.claude_recheck_s * 2, CLAUDE_RECHECK_MAX_S) if again else CLAUDE_RECHECK_S
                )
                self._ready_after = None
            self._checked_claude_at = time.monotonic()
        if why != self._told_waiting:
            self._told_waiting = why
            self.ctx.bus.publish("llm.paused", until="", reason=why)
        self.waiting_for_claude = why
        self._park(job, why, said=None)  # the app last heard the reading's stages

    def _letter_waits_for_claude(self) -> bool:
        """Whether a letter only Claude can read is still in the queue: one deleted or kept private meanwhile
        no longer keeps the wait announced to pages that connect."""
        return any(
            job.kind in self.JOB_KINDS
            and job.status in ("queued", "running")
            and self._needs_claude(job.doc_id)
            for job in self.ctx.store.list_jobs(active_only=True)
        )

    def _needs_claude(self, doc_id: str | None) -> bool:
        """A letter only Claude can read (a private one is read on this computer)."""
        document = self.ctx.store.get_document(doc_id) if doc_id else None
        return document is not None and not document.ai_private

    def _park(self, job: Job, why: str, *, said: str | None) -> None:
        """Back to the queue, waiting for Claude: tried again after :data:`CLAUDE_RECHECK_S` seconds (or as
        soon as :meth:`claude_ready`), so the letters behind it — private ones — go on being read. The
        app hears why, unless that is what it was told last (``said``)."""
        reason = (
            f"{WAITING_FOR_CLAUDE}: {why} Ordnung reads this letter as soon as Claude is connected "
            "(Settings → Claude connection)."
        )
        again = _now() + timedelta(seconds=CLAUDE_RECHECK_S)
        with contextlib.suppress(Exception):  # deleted meanwhile
            self.ctx.store.update_job(
                job.id, status="queued", error=None, waiting_reason=reason, not_before=again
            )
        if said == reason:
            return
        self.ctx.bus.publish(
            "job.progress",
            job_id=job.id,
            doc_id=job.doc_id,
            stage="intake",
            progress=0.0,
            status="queued",
            waiting_reason=reason,
        )

    def _check_claude(self) -> None:
        """Ask ``claude_check`` again, at most every :data:`CLAUDE_RECHECK_S` seconds (longer after a "ready" that
        wasn't, see :meth:`_wait_for_claude`), one check at a time."""
        check = self.claude_check
        if check is None or self._stopping or self._wake is None:
            return
        if self._claude_checking is not None and not self._claude_checking.done():
            return
        now = time.monotonic()
        if self._checked_claude_at is not None and now - self._checked_claude_at < self.claude_recheck_s:
            return
        self._checked_claude_at = now

        async def run() -> None:
            try:
                ready = await check()
            except Exception:
                log.warning("checking for Claude failed", exc_info=True)
                return
            if ready:
                self.claude_ready()

        self._claude_checking = asyncio.create_task(
            run(), name="ordnung-claude-check", context=background_context()
        )

    def _maybe_resume(self) -> None:
        if self.paused_until is not None and not self.is_paused():
            self.paused_until = None
            self.ctx.store.set_meta(PAUSE_META_KEY, None)
            if self._told_waiting is None:
                self.ctx.bus.publish("llm.resumed")
