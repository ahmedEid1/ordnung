"""The weekly session (the "Weekly review" page): ``GET`` the seven steps (and whether Today should
suggest them); ``POST /week/done`` remembers that the person went through them, ``POST /week/dismiss``
that they said "Not now" to the prompt. Only these two moments are stored (``meta``); nothing is closed
or paid."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from ordnung import views
from ordnung.api.deps import StoreDep, TodayDep
from ordnung.models import WeeklySession
from ordnung.secretary.week import dismiss_prompt, record_session

router = APIRouter(tags=["week"])


@router.get("/week", response_model=WeeklySession)
def weekly_session(store: StoreDep, today: TodayDep) -> WeeklySession:
    """New letters, values to check, payments this week, letters to post, replies awaited, decisions in
    the next 30 days and what to file — and the next day to act ("All clear until …")."""
    return views.weekly_session(store, today)


@router.post("/week/done", response_model=WeeklySession)
async def week_done(store: StoreDep, today: TodayDep) -> WeeklySession:
    """Remember that the weekly session was done now; answers the session as it stands afterwards."""
    await asyncio.to_thread(record_session, store, today)
    return await asyncio.to_thread(views.weekly_session, store, today)


@router.post("/week/dismiss", response_model=WeeklySession)
async def week_dismiss(store: StoreDep, today: TodayDep) -> WeeklySession:
    """Say "Not now": Today stops suggesting the session until it is due again (a week, or a Sunday)."""
    await asyncio.to_thread(dismiss_prompt, store, today)
    return await asyncio.to_thread(views.weekly_session, store, today)
