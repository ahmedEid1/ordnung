"""Background ingestion worker: claims jobs from the queue of record and reads documents.

* Up to ``settings.concurrency`` documents at once; ``start()`` first returns jobs a previous
  process left ``running`` to the queue.
* A rate limit pauses the worker globally until the reset time (or 15 minutes): the job goes back
  to ``queued`` with a ``waiting_reason``, ``llm.paused`` is published (``llm.resumed`` when it ends)
  and the pause survives restarts (meta ``llm_paused_until``).
* Claude not installed or not signed in pauses reading too, without an end (``llm.paused`` with an
  empty ``until``): the letter waits in the queue instead of failing, and so does every letter for
  Claude claimed meanwhile (put back for :data:`CLAUDE_RECHECK_S` seconds at a time; private letters
  are read as usual), and the API's cached Claude status is dropped (``claude_failed``). Reading goes
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
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ordnung.ingest.pipeline import ingest_document, run_triggers
from ordnung.llm.base import ClaudeAuthError, ClaudeNotInstalled, ClaudeRateLimited
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
#: How a job's ``waiting_reason`` starts while it waits for Claude (a usage limit, or Claude not ready).
WAITING_FOR_CLAUDE = "Waiting for Claude"
#: Seconds between the worker's own checks for Claude while letters wait for it (zero tokens).
CLAUDE_RECHECK_S = 30.0
#: The longest time between those checks after checks said "ready" and readings failed all the same.
CLAUDE_RECHECK_MAX_S = 30 * 60.0
NOT_INSTALLED_REASON = "Claude Code isn't installed on this computer yet."
NOT_SIGNED_IN_REASON = "Claude Code isn't signed in."
#: How the reason of a letter waiting because Claude is not installed or not signed in starts.
_NOT_READY = f"{WAITING_FOR_CLAUDE}: Claude Code isn't "


def _now() -> datetime:
    return datetime.now(UTC)


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


class IngestWorker:
    """Reads queued documents in the background (see the module docstring)."""

    POLL_SECONDS: ClassVar[float] = 1.0
    JOB_KINDS: ClassVar[tuple[str, ...]] = ("ingest", "reprocess")

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
        self._loop_task = asyncio.create_task(self._run(), name="ordnung-ingest-worker")

    async def stop(self, grace: float = 10.0) -> None:
        """Stop gracefully: documents in progress get ``grace`` seconds, then go back to the queue."""
        self._stopping = True
        self.notify()
        if self._loop_task is not None:
            await self._loop_task
            self._loop_task = None
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
        self._ideas = asyncio.create_task(self._refresh_ideas(), name="ordnung-ideas-refresh")

    async def _refresh_ideas(self) -> None:
        self._ideas_again = True
        while self._ideas_again:
            self._ideas_again = False
            await run_triggers(self.ctx)

    async def ideas_settled(self) -> None:
        """Wait until no background run of the triggers is under way or due."""
        while self._ideas is not None and not self._ideas.done():
            await asyncio.shield(self._ideas)

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
            task = asyncio.create_task(self._run_job(job), name=f"ordnung-ingest-{job.doc_id}")
            self._active.add(task)
            task.add_done_callback(self._job_finished)
            started += 1
        return started

    def _job_finished(self, task: asyncio.Task[None]) -> None:
        self._active.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("ingest task crashed", exc_info=task.exception())
        self.notify()

    async def _run_job(self, job: Job) -> None:
        store = self.ctx.store
        if job.doc_id is None:
            store.update_job(job.id, status="failed", error="This job has no document to read.")
            return
        if self.waiting_for_claude is not None and self._needs_claude(job.doc_id):
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
        local = self.paused_until.astimezone().strftime("%H:%M")
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
            job.kind in self.JOB_KINDS and job.status in ("queued", "running") and self._needs_claude(job.doc_id)
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

        self._claude_checking = asyncio.create_task(run(), name="ordnung-claude-check")

    def _maybe_resume(self) -> None:
        if self.paused_until is not None and not self.is_paused():
            self.paused_until = None
            self.ctx.store.set_meta(PAUSE_META_KEY, None)
            if self._told_waiting is None:
                self.ctx.bus.publish("llm.resumed")
