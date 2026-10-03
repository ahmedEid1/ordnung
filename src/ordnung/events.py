"""Tiny in-process pub/sub used to push live updates (job progress, new suggestions) to SSE clients."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    type: str  # "job.progress" | "document.processed" | "suggestions.updated" | "item.updated" | ...
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    """Fan-out broadcaster. Publishing never blocks; slow subscribers drop old events."""

    def __init__(self, max_queue: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._max_queue = max_queue
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, type: str, **data: Any) -> None:
        event = Event(type, data)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self._loop is not None and running is not self._loop:
            # called from a worker thread: hop onto the server loop
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._deliver, event)
            return
        self._deliver(event)

    def _deliver(self, event: Event) -> None:
        for q in list(self._subscribers):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(event)

    async def subscribe(self) -> AsyncIterator[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(self._max_queue)
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
