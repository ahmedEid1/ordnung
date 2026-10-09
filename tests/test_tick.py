"""The daily tick: day-change detection, triggers, brief, weekly review and bus events."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.db.store import Store
from ordnung.llm.base import ClaudeTimeout, LLMRequest
from ordnung.llm.fake import FakeBackend
from ordnung.llm.replay import ReplayBackend
from ordnung.llm.runtime import LLMService
from ordnung.secretary.brief import get_brief
from ordnung.tick import DailyTick, local_today, replay_miss_prone, simulated_day

NOTE = "Good morning, Sam! The TechMarkt reminder of €94.99 is due on Wed 30 Sep."


@dataclass
class RecordingBus:
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def publish(self, type: str, **data: Any) -> None:
        self.events.append((type, data))

    def types(self) -> list[str]:
        return [event for event, _ in self.events]


@dataclass
class Ctx:
    store: Store
    llm: LLMService | None
    bus: RecordingBus = field(default_factory=RecordingBus)


def review_answer(ticket_id: str) -> dict[str, Any]:
    return {
        "suggestions": [
            {
                "kind": "saving",
                "title": "Check whether your semester ticket covers the Deutschlandticket",
                "body": "You pay €63 a month for the Deutschlandticket.",
                "rationale": "An active Deutschlandticket contract.",
                "refs": [{"type": "contract", "id": ticket_id}],
            }
        ]
    }


@pytest.fixture(autouse=True)
def pinned_today(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("ORDNUNG_TODAY", raising=False)
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def ids(store: Store) -> dict[str, str]:
    return seed_ledger(store)


@pytest.fixture
def backend(ids: dict[str, str]) -> FakeBackend:
    return FakeBackend({"brief": {"text": NOTE}, "review": review_answer(ids["ticket"])})


@pytest.fixture
def ctx(store: Store, backend: FakeBackend) -> Ctx:
    return Ctx(store=store, llm=LLMService(backend, sink=store))


async def test_first_tick_runs_the_whole_day(ctx: Ctx, backend: FakeBackend) -> None:
    tick = DailyTick(ctx)
    result = await tick.check()
    assert result.day_changed and result.today == TODAY
    assert result.triggers is not None and result.triggers.new > 0
    assert ctx.store.get_meta("last_tick_date") == "2026-09-28"
    assert ctx.bus.types()[:2] == ["day.changed", "suggestions.updated"]
    day_changed = ctx.bus.events[0][1]
    assert day_changed == {"date": "2026-09-28", "previous": None}
    assert ctx.bus.events[1][1]["new"] == result.triggers.new
    assert result.brief is not None and result.brief.source == "llm"
    brief = get_brief(ctx.store, TODAY)
    assert brief is not None and brief.text == NOTE
    assert result.review_started and tick.review_task is not None
    await tick.review_task
    assert ctx.store.get_meta("last_review_at") == "2026-09-28"
    assert ("suggestions.updated", {"reason": "review", "created": 1}) in ctx.bus.events
    assert [call.purpose for call in backend.calls] == ["brief", "review"]


async def test_a_failed_weekly_review_is_reported_like_one_asked_for(ctx: Ctx, backend: FakeBackend) -> None:
    """The weekly review publishes ``review.failed``, as the review asked for in the app does."""

    def busy(_: LLMRequest) -> dict[str, Any]:
        raise ClaudeTimeout("Claude didn't answer in time.")

    assert isinstance(backend.responses, dict)
    backend.responses["review"] = busy
    tick = DailyTick(ctx)
    result = await tick.check()
    assert result.review_started and tick.review_task is not None
    await tick.review_task

    assert ("review.failed", {"error": "Claude didn't answer in time."}) in ctx.bus.events
    assert ctx.store.get_meta("last_review_at") is None  # it is tried again on the next check


async def test_same_day_tick_does_nothing(ctx: Ctx, backend: FakeBackend) -> None:
    tick = DailyTick(ctx)
    await tick.check()
    if tick.review_task:
        await tick.review_task
    events, calls = len(ctx.bus.events), len(backend.calls)
    result = await tick.check()
    assert not result.day_changed and result.triggers is None
    assert len(ctx.bus.events) == events and len(backend.calls) == calls


async def test_day_change_reruns_triggers_but_review_is_weekly(ctx: Ctx) -> None:
    tick = DailyTick(ctx)
    await tick.check()
    assert tick.review_task is not None
    await tick.review_task
    clock.set_today(TODAY + timedelta(days=1))
    result = await tick.check()
    assert result.day_changed and not result.review_started
    assert ("day.changed", {"date": "2026-09-29", "previous": "2026-09-28"}) in ctx.bus.events
    clock.set_today(TODAY + timedelta(days=8))
    result = await tick.check()
    assert result.review_started


async def test_tick_never_changes_item_statuses(ctx: Ctx, ids: dict[str, str]) -> None:
    before = {item.id: item.status for item in ctx.store.list_items()}
    tick = DailyTick(ctx)
    await tick.check()
    clock.set_today(date(2027, 6, 1))  # everything is long overdue now
    await tick.check()
    await tick.stop()
    assert {item.id: item.status for item in ctx.store.list_items()} == before


async def test_strict_replay_backend_is_not_asked(store: Store, ids: dict[str, str], tmp_path: Path) -> None:
    llm = LLMService(ReplayBackend(tmp_path / "fixtures"), sink=store)
    assert replay_miss_prone(llm)
    tick = DailyTick(Ctx(store=store, llm=llm))
    result = await tick.check()
    assert result.brief is not None and result.brief.source == "template"
    assert not result.review_started
    assert store.usage_stats().calls == 0


async def test_llm_brief_can_be_switched_off(ctx: Ctx, backend: FakeBackend) -> None:
    ctx.store.save_settings(ctx.store.get_settings().model_copy(update={"llm_brief": False}))
    tick = DailyTick(ctx)
    result = await tick.check()
    await tick.stop()
    assert result.brief is not None and result.brief.source == "template"
    assert "brief" not in [call.purpose for call in backend.calls]


async def test_tick_without_ai(store: Store, ids: dict[str, str]) -> None:
    tick = DailyTick(Ctx(store=store, llm=None))
    result = await tick.check()
    assert result.day_changed and result.brief is not None and result.brief.source == "template"
    assert not result.review_started


async def test_run_forever_ticks_and_stops(ctx: Ctx) -> None:
    tick = DailyTick(ctx, interval_s=0.01)
    task = tick.start()
    assert tick.start() is task  # idempotent
    for _ in range(200):
        if ctx.store.get_meta("last_tick_date"):
            break
        await asyncio.sleep(0.01)
    await tick.stop()
    assert task.done()
    assert ctx.store.get_meta("last_tick_date") == "2026-09-28"


def test_local_today_honours_simulation_and_time_zone(store: Store) -> None:
    assert local_today(store) == TODAY  # clock override
    clock.set_today(None)
    store.save_settings(store.get_settings().model_copy(update={"simulated_today": "2026-10-01"}))
    assert simulated_day(store) == date(2026, 10, 1) == local_today(store)
    store.save_settings(store.get_settings().model_copy(update={"simulated_today": None}))
    store.set_meta("simulated_today", "2026-10-02")
    assert local_today(store) == date(2026, 10, 2)
    store.set_meta("simulated_today", None)
    assert simulated_day(store) is None
    store.save_profile(store.get_profile().model_copy(update={"timezone": "Pacific/Kiritimati"}))
    assert local_today(store) == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    store.save_profile(store.get_profile().model_copy(update={"timezone": "Mars/Olympus_Mons"}))
    assert local_today(store) == clock.today()
