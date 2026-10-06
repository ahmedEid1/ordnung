"""Live updates: ``GET /api/events`` streams the event bus as Server-Sent Events.

Event types include ``job.progress`` {job_id, doc_id, stage, progress, status, error?},
``document.processed`` {doc_id, status}, ``suggestions.updated``, ``item.updated`` {item_id?},
``day.changed`` {date, previous}, ``brief.updated``, ``llm.paused`` {until, reason} and
``llm.resumed``. A pause under way is sent first, so a page opened (or reloaded) during one shows it:
it is announced only when it starts. A keep-alive comment is sent every 15 seconds.
"""

from __future__ import annotations

from fastapi import APIRouter

from ordnung.api.deps import CtxDep
from ordnung.api.sse import EventStreamResponse, bus_response
from ordnung.events import Event

router = APIRouter(tags=["events"])


@router.get("/events", response_class=EventStreamResponse)
async def events(ctx: CtxDep) -> EventStreamResponse:
    """Subscribe to live updates (job progress, new Ideas, day change, rate-limit pauses)."""
    worker = ctx.worker

    def current() -> list[Event]:
        pause = worker.current_pause()
        return [Event("llm.paused", pause)] if pause is not None else []

    return bus_response(ctx.bus, current=current)
