"""The daily tick: the secretary's heartbeat (SPEC §9, §21).

On startup and every 15 minutes :class:`DailyTick` checks the person's local date (their profile's
time zone, or the simulated demo date). When it changed since meta ``last_tick_date`` it moves
recurring to-dos whose date has passed on to their current occurrence (:mod:`ordnung.recurrence`),
runs the triggers and expires stale Ideas, rebuilds the agenda and the brief (model-written only when
``settings.llm_brief`` is on and the backend can answer), starts the weekly review in the background
if the last one is more than 7 days old, and announces ``day.changed`` and ``suggestions.updated``.
On every check (not only when the day changed) it shows the morning desktop notification once it is
due (:mod:`ordnung.notify.desktop`: once a day, at the chosen time, only when switched on; not in
the first :data:`~ordnung.notify.desktop.STARTUP_GRACE_S` seconds after start-up), and — in
``ordnung serve``, which passes ``calendar_sync`` — sends what changed to the calendar the person
connected (:mod:`ordnung.calendar.caldav`; nothing when none is connected). While today's
notification waits for its first try, the loop wakes up for it instead of sleeping the whole
interval — a time like 23:50 is never skipped by a check at 23:48 and the next one after midnight.

It never changes an item's status: overdue is computed on read.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ordnung import clock
from ordnung.db.store import Store, background_context
from ordnung.ingest.pipeline import ledger_lock
from ordnung.ingest.plan import item_contexts
from ordnung.llm.base import LLMError
from ordnung.llm.runtime import LLMService
from ordnung.models import CalendarSyncReport
from ordnung.notify import desktop
from ordnung.recurrence import roll_forward
from ordnung.secretary.brief import Brief, generate_brief
from ordnung.secretary.review import LAST_REVIEW_KEY, run_review
from ordnung.secretary.triggers import TriggerRun, parse_day, run_and_reconcile

log = logging.getLogger(__name__)

TICK_INTERVAL_S = 15 * 60.0
#: the shortest sleep while waking up for the notification (a failing check never spins)
MIN_WAKE_S = 30.0
REVIEW_EVERY = timedelta(days=7)
LAST_TICK_KEY = "last_tick_date"
SIMULATED_TODAY_KEY = "simulated_today"


class Publisher(Protocol):
    """Anything with the :meth:`ordnung.events.EventBus.publish` signature."""

    def publish(self, type: str, **data: Any) -> None: ...


class TickContext(Protocol):
    """What the tick needs from the app context."""

    @property
    def store(self) -> Store: ...

    @property
    def llm(self) -> LLMService | None: ...

    @property
    def bus(self) -> Publisher | None: ...


def simulated_day(store: Store) -> date | None:
    """The pinned demo/test date, if any: ``clock`` override, then settings, then meta."""
    if clock.simulated():
        return clock.today()
    configured = store.get_settings().simulated_today
    return parse_day(configured) or parse_day(store.get_meta(SIMULATED_TODAY_KEY))


def local_today(store: Store) -> date:
    """Today in the person's time zone (``profile.timezone``), honouring a simulated date."""
    pinned = simulated_day(store)
    if pinned is not None:
        return pinned
    try:
        zone = ZoneInfo(store.get_profile().timezone)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("unknown time zone in the profile; using the system date")
        return clock.today()
    return datetime.now(zone).date()


def replay_miss_prone(llm: LLMService) -> bool:
    """A strict replay backend (no live fallback) cannot answer new prompts — don't ask it."""
    backend = llm.backend
    return backend.name == "replay" and getattr(backend, "fallback", None) is None


@dataclass(frozen=True)
class TickResult:
    """What one :meth:`DailyTick.check` did."""

    today: date
    day_changed: bool
    triggers: TriggerRun | None = None
    brief: Brief | None = None
    review_started: bool = False
    #: the morning desktop notification this check showed or tried (``None``: it wasn't due)
    desktop: desktop.Outcome | None = None
    #: what calendar sync did (``None``: no calendar connected, paused, or not run by this tick)
    calendar: CalendarSyncReport | None = None


class DailyTick:
    """Runs the secretary once per local day (checked on startup and every ``interval_s`` seconds)."""

    def __init__(
        self,
        ctx: TickContext,
        *,
        interval_s: float = TICK_INTERVAL_S,
        now: Callable[[Store], datetime] = desktop.local_now,
        notifier: Callable[[desktop.Notification], desktop.SendResult] = desktop.send,
        calendar_sync: Callable[[Store], CalendarSyncReport | None] | None = None,
        startup_grace_s: float = desktop.STARTUP_GRACE_S,
    ) -> None:
        self.ctx = ctx
        self.interval_s = interval_s
        self.startup_grace_s = startup_grace_s
        self._now = now
        self._notifier = notifier
        self._calendar_sync = calendar_sync
        #: no desktop notification before this (monotonic) moment: set when the loop starts
        self._hold_until = 0.0
        self._task: asyncio.Task[None] | None = None
        self._review: asyncio.Task[None] | None = None

    @property
    def review_task(self) -> asyncio.Task[None] | None:
        """The background review started by the last day change (if any)."""
        return self._review

    def _publish(self, type_: str, **data: Any) -> None:
        bus = self.ctx.bus
        if bus is not None:
            bus.publish(type_, **data)

    def _usable_llm(self) -> LLMService | None:
        llm = self.ctx.llm
        return None if llm is None or replay_miss_prone(llm) else llm

    async def check(self) -> TickResult:
        """Run the day's work if the local date changed since the last tick, then the desktop
        notification if it is due and calendar sync."""
        store = self.ctx.store
        today = local_today(store)
        previous = store.get_meta(LAST_TICK_KEY)
        if previous == today.isoformat():
            result = TickResult(today=today, day_changed=False)
        else:
            result = await self._new_day(today, previous)
        return replace(result, desktop=await self._desktop(today), calendar=await self._calendar())

    async def _new_day(self, today: date, previous: str | None) -> TickResult:
        store = self.ctx.store
        async with ledger_lock():  # the pipeline links and reconciles under the same lock
            await asyncio.to_thread(roll_forward, store, today, item_contexts())
            run = await asyncio.to_thread(run_and_reconcile, store, today)
        store.set_meta(LAST_TICK_KEY, today.isoformat())
        self._publish("day.changed", date=today.isoformat(), previous=previous)
        self._publish("suggestions.updated", reason="tick", **run.as_dict())
        brief = await self._refresh_brief(today)
        started = self._start_review(today)
        return TickResult(today=today, day_changed=True, triggers=run, brief=brief, review_started=started)

    async def _desktop(self, today: date) -> desktop.Outcome | None:
        """The morning desktop notification, if due; a failure is logged, never fatal."""
        store = self.ctx.store
        if time.monotonic() < self._hold_until:  # just started: the desktop may not be ready yet
            return None
        try:
            clock_time = self._now(store).time()
            return await asyncio.to_thread(
                desktop.morning_notification, store, today, clock_time, sender=self._notifier
            )
        except Exception:
            log.exception("desktop notification failed")
            return None

    async def _calendar(self) -> CalendarSyncReport | None:
        """Calendar sync (only what changed); its own report says what went wrong, never fatal."""
        if self._calendar_sync is None:
            return None
        try:
            return await asyncio.to_thread(self._calendar_sync, self.ctx.store)
        except Exception:
            log.exception("calendar sync failed")
            return None

    async def _refresh_brief(self, today: date) -> Brief:
        store = self.ctx.store
        llm = self._usable_llm() if store.get_settings().llm_brief else None
        brief = await generate_brief(store, llm, today)
        self._publish("brief.updated", date=brief.date, source=brief.source)
        return brief

    def _review_due(self, today: date) -> bool:
        last = parse_day(self.ctx.store.get_meta(LAST_REVIEW_KEY))
        return last is None or today - last > REVIEW_EVERY

    def _start_review(self, today: date) -> bool:
        if not self.ctx.store.get_settings().llm_review:
            return False
        llm = self._usable_llm()
        running = self._review is not None and not self._review.done()
        if llm is None or running or not self._review_due(today):
            return False
        self._review = asyncio.create_task(
            self._run_review(llm, today), name="ordnung-weekly-review", context=background_context()
        )
        return True

    async def _run_review(self, llm: LLMService, today: date) -> None:
        try:
            ideas = await run_review(self.ctx.store, llm, today)
        except LLMError as exc:
            log.warning("weekly review failed: %s", exc)
            self._publish("review.failed", error=str(exc))  # as the review asked for in the app
            # no one waits for this one in the app: the activity log says it couldn't run
            reason = str(exc).strip() or "Claude didn't answer."
            reason += "" if reason.endswith((".", "!", "?")) else "."
            self.ctx.store.log_activity(
                "review.failed",
                f"The weekly review couldn't write Ideas: {reason} Ordnung tries again tomorrow.",
            )
            return
        self._publish("suggestions.updated", reason="review", created=len(ideas))

    def next_check_in(self) -> float:
        """Seconds until the next check: the interval — or sooner, when today's notification comes
        before it (its time, or the end of the start-up wait), never less than :data:`MIN_WAKE_S`."""
        store = self.ctx.store
        try:
            due_in = desktop.first_try_in(store, local_today(store), self._now(store))
        except Exception:
            log.exception("couldn't work out when the desktop notification is due")
            return self.interval_s
        if due_in is None:
            return self.interval_s
        held = max(0.0, self._hold_until - time.monotonic())
        return min(self.interval_s, max(MIN_WAKE_S, due_in + 1.0, held + 1.0))

    async def run_forever(self) -> None:
        """Check now, then every ``interval_s`` seconds (sooner for the notification, see
        :meth:`next_check_in`); errors are logged, never fatal."""
        self._hold_until = time.monotonic() + self.startup_grace_s
        while True:
            try:
                await self.check()
            except Exception:
                log.exception("daily tick failed")
            await asyncio.sleep(self.next_check_in())

    def start(self) -> asyncio.Task[None]:
        """Start :meth:`run_forever` on the running loop (idempotent)."""
        if self._task is None or self._task.done():
            # background work: the day change is never the person's, even when a request started it
            self._task = asyncio.create_task(
                self.run_forever(), name="ordnung-daily-tick", context=background_context()
            )
        return self._task

    async def stop(self) -> None:
        """Cancel the loop and any running review."""
        for task in (self._task, self._review):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._task = None
