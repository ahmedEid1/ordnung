"""Server-Sent Events helpers (sse-starlette).

* :func:`bus_response` streams the in-process :class:`~ordnung.events.EventBus` to ``GET /api/events``:
  one SSE event per bus event (``event:`` = its type, ``data:`` = JSON), after the events that say how
  things stand when the client connects (``current``), keep-alive comments every 15 seconds.
* :func:`model_stream_response` streams pydantic models (the Ask answer's
  :class:`~ordnung.llm.base.StreamEvent` s) as default ``message`` events whose JSON data carries a
  ``type`` field. When the client disconnects, sse-starlette cancels the response task: the
  cancellation reaches the model call (which kills the ``claude`` process group) and the source
  iterator is closed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any

import anyio
from pydantic import BaseModel
from sse_starlette import EventSourceResponse, ServerSentEvent

from ordnung.events import Event, EventBus

PING_SECONDS = 15


class EventStreamResponse(EventSourceResponse):
    """An SSE response whose media type is known on the class (so OpenAPI documents it)."""

    media_type = "text/event-stream"


async def close_iterator(iterator: AsyncIterator[Any]) -> None:
    """Close an async generator even while the surrounding task is being cancelled."""
    aclose: Callable[[], Any] | None = getattr(iterator, "aclose", None)
    if aclose is not None:
        with anyio.CancelScope(shield=True):
            await aclose()


async def bus_events(
    bus: EventBus, current: Callable[[], Iterable[Event]] | None = None
) -> AsyncIterator[ServerSentEvent]:
    """Every event published on ``bus`` from now on, after ``current()``'s, as SSE events."""
    subscription = bus.subscribe(current)
    try:
        async for event in subscription:
            yield ServerSentEvent(data=json.dumps(event.data, default=str), event=event.type)
    finally:
        await close_iterator(subscription)


def bus_response(
    bus: EventBus, *, ping: float = PING_SECONDS, current: Callable[[], Iterable[Event]] | None = None
) -> EventStreamResponse:
    """``GET /api/events``: how things stand (``current``), then live bus events, with keep-alive pings."""
    return EventStreamResponse(bus_events(bus, current), ping=ping)


async def model_events(events: AsyncIterator[BaseModel]) -> AsyncIterator[ServerSentEvent]:
    """Pydantic models as ``message`` events (JSON data without ``null`` fields)."""
    try:
        async for event in events:
            yield ServerSentEvent(data=event.model_dump_json(exclude_none=True))
    finally:
        await close_iterator(events)


def model_stream_response(
    events: AsyncIterator[BaseModel], *, ping: float = PING_SECONDS
) -> EventStreamResponse:
    """A streamed answer: one ``message`` event per model, keep-alive pings while tools run."""
    return EventStreamResponse(model_events(events), ping=ping)
