"""Calendar export: every open dated to-do and contract decision as one ``.ics`` (with reminders),
and "I added them to my calendar" (clears the "calendar outdated" Idea)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Response
from pydantic import BaseModel

from ordnung.api.deps import CtxDep, StoreDep
from ordnung.calendar.ics import build_ics, mark_exported
from ordnung.db.store import Store
from ordnung.ingest.pipeline import run_triggers

router = APIRouter(tags=["calendar"])

ICS_TYPE = "text/calendar; charset=utf-8"


class CalendarExportResult(BaseModel):
    """When the person last exported their dates."""

    last_calendar_export_at: str


@router.get("/calendar.ics", response_class=Response, responses={200: {"content": {ICS_TYPE: {}}}})
def calendar_ics(store: StoreDep) -> Response:
    """All open dates as an iCalendar file."""
    return Response(
        build_ics(store),
        media_type=ICS_TYPE,
        headers={"Content-Disposition": 'attachment; filename="ordnung.ics"', "Cache-Control": "no-store"},
    )


def _exported(store: Store) -> str:
    stamp = mark_exported(store)
    store.log_activity("calendar.exported", "Exported your dates to your calendar")
    return stamp


@router.post("/calendar/exported", response_model=CalendarExportResult)
async def calendar_exported(ctx: CtxDep) -> CalendarExportResult:
    """Remember that the dates were just added to the person's calendar."""
    stamp = await asyncio.to_thread(_exported, ctx.store)
    await run_triggers(ctx)
    return CalendarExportResult(last_calendar_export_at=stamp)
