"""The weekly session (the "Weekly review" page): ``GET`` the seven steps (and whether Today should
suggest them); ``POST /week/done`` remembers that the person went through them, ``POST /week/dismiss``
that they said "Not now" to the prompt. Only these two moments are stored (``meta``); nothing is closed
or paid.

All three answer the session with ``backup`` set when it is time for a backup (no copy kept elsewhere
within 30 days, :mod:`ordnung.backup.reminder`), so the review's ending says so — code's words, never the
model's; it never makes the review due."""

from __future__ import annotations

import asyncio
from datetime import date

from fastapi import APIRouter

from ordnung import views
from ordnung.api.deps import ApiState, StateDep, TodayDep
from ordnung.api.routes.backup import last_copy
from ordnung.models import WeeklySession
from ordnung.secretary.week import dismiss_prompt, record_session

router = APIRouter(tags=["week"])


async def _with_backup(session: WeeklySession, state: ApiState, today: date) -> WeeklySession:
    """The session with the newest copy kept elsewhere, only when it is time for a backup."""
    copy = await last_copy(state, today)
    return session.model_copy(update={"backup": copy if copy.due else None})


@router.get("/week", response_model=WeeklySession)
async def weekly_session(state: StateDep, today: TodayDep) -> WeeklySession:
    """New letters, values to check, payments this week, letters to post, replies awaited, decisions in
    the next 30 days and what to file — and the next day to act ("All clear until …")."""
    session = await asyncio.to_thread(views.weekly_session, state.ctx.store, today)
    return await _with_backup(session, state, today)


@router.post("/week/done", response_model=WeeklySession)
async def week_done(state: StateDep, today: TodayDep) -> WeeklySession:
    """Remember that the weekly session was done now; answers the session as it stands afterwards."""
    store = state.ctx.store
    await asyncio.to_thread(record_session, store, today)
    session = await asyncio.to_thread(views.weekly_session, store, today)
    return await _with_backup(session, state, today)


@router.post("/week/dismiss", response_model=WeeklySession)
async def week_dismiss(state: StateDep, today: TodayDep) -> WeeklySession:
    """Say "Not now": Today stops suggesting the session until it is due again (a week, or a Sunday)."""
    store = state.ctx.store
    await asyncio.to_thread(dismiss_prompt, store, today)
    session = await asyncio.to_thread(views.weekly_session, store, today)
    return await _with_backup(session, state, today)
