"""The daily tick: the secretary's heartbeat (SPEC §9, §21).

On startup and every 15 minutes :class:`DailyTick` checks the person's local date (their profile's
time zone, or the simulated demo date). When it changed since meta ``last_tick_date`` it moves
recurring to-dos whose date has passed on to their current occurrence (:mod:`ordnung.recurrence`),
runs the triggers and expires stale Ideas, rebuilds the agenda and the brief (model-written only when
``settings.llm_brief`` is on and the backend can answer), starts the weekly review in the background
if the last one is more than 7 days old, and announces ``day.changed`` and ``suggestions.updated``.

It never changes an item's status: overdue is computed on read.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ordnung import clock
from ordnung.db.store import Store
from ordnung.ingest.pipeline import ledger_lock
from ordnung.ingest.plan import item_context
from ordnung.llm.base import LLMError
from ordnung.llm.runtime import LLMService
from ordnung.recurrence import roll_forward
from ordnung.secretary.brief import Brief, generate_brief
from ordnung.secretary.review import LAST_REVIEW_KEY, run_review
from ordnung.secretary.triggers import TriggerRun, parse_day, run_and_reconcile

log = logging.getLogger(__name__)

TICK_INTERVAL_S = 15 * 60.0
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


class DailyTick:
    """Runs the secretary once per local day (checked on startup and every ``interval_s`` seconds)."""

    def __init__(self, ctx: TickContext, *, interval_s: float = TICK_INTERVAL_S) -> None:
        self.ctx = ctx
        self.interval_s = interval_s
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
        """Run the day's work if the local date changed since the last tick."""
        store = self.ctx.store
        today = local_today(store)
        previous = store.get_meta(LAST_TICK_KEY)
        if previous == today.isoformat():
            return TickResult(today=today, day_changed=False)
        async with ledger_lock():  # the pipeline links and reconciles under the same lock
            await asyncio.to_thread(roll_forward, store, today, item_context)
            run = await asyncio.to_thread(run_and_reconcile, store, today)
        store.set_meta(LAST_TICK_KEY, today.isoformat())
        self._publish("day.changed", date=today.isoformat(), previous=previous)
        self._publish("suggestions.updated", reason="tick", **run.as_dict())
        brief = await self._refresh_brief(today)
        started = self._start_review(today)
        return TickResult(today=today, day_changed=True, triggers=run, brief=brief, review_started=started)

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
        self._review = asyncio.create_task(self._run_review(llm, today), name="ordnung-weekly-review")
        return True

    async def _run_review(self, llm: LLMService, today: date) -> None:
        try:
            ideas = await run_review(self.ctx.store, llm, today)
        except LLMError as exc:
            log.warning("weekly review failed: %s", exc)
            return
        self._publish("suggestions.updated", reason="review", created=len(ideas))

    async def run_forever(self) -> None:
        """Check now, then every ``interval_s`` seconds; errors are logged, never fatal."""
        while True:
            try:
                await self.check()
            except Exception:
                log.exception("daily tick failed")
            await asyncio.sleep(self.interval_s)

    def start(self) -> asyncio.Task[None]:
        """Start :meth:`run_forever` on the running loop (idempotent)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run_forever(), name="ordnung-daily-tick")
        return self._task

    async def stop(self) -> None:
        """Cancel the loop and any running review."""
        for task in (self._task, self._review):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._task = None
