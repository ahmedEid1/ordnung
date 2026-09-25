"""The read models of the main pages: Today (dashboard), the timeline and the life lanes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from ordnung import views
from ordnung.api.deps import StoreDep, TodayDep
from ordnung.api.routes.common import IsoDate
from ordnung.models import Dashboard, Lane, TimelineEntry

router = APIRouter(tags=["overview"])

LANES_BEFORE = timedelta(days=30)
LANES_AFTER = timedelta(days=365)
FromDate = Annotated[IsoDate | None, Query(alias="from", description="First day (YYYY-MM-DD)")]
ToDate = Annotated[IsoDate | None, Query(description="Last day (YYYY-MM-DD)")]


def _range(start: str | None, end: str | None, default_start: date, default_end: date) -> tuple[date, date]:
    first = date.fromisoformat(start) if start else default_start
    last = date.fromisoformat(end) if end else default_end
    if last < first:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "“to” must not be before “from”.")
    return first, last


@router.get("/dashboard", response_model=Dashboard)
def dashboard(store: StoreDep, today: TodayDep) -> Dashboard:
    """Today: what needs attention, what is coming up, decisions, money, life areas and Ideas."""
    return views.dashboard(store, today)


@router.get("/timeline", response_model=list[TimelineEntry])
def timeline(
    store: StoreDep, today: TodayDep, from_: FromDate = None, to: ToDate = None
) -> list[TimelineEntry]:
    """Everything dated between ``from`` and ``to`` (default: all), in date order."""
    first, last = _range(from_, to, date.min, date.max)
    return views.timeline(store, first, last, today=today)


@router.get("/lanes", response_model=list[Lane])
def lanes(store: StoreDep, today: TodayDep, from_: FromDate = None, to: ToDate = None) -> list[Lane]:
    """Life lanes between ``from`` and ``to`` (default: a month back to a year ahead)."""
    first, last = _range(from_, to, today - LANES_BEFORE, today + LANES_AFTER)
    return views.lanes(store, first, last, today=today)
