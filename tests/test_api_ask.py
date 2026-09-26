"""Streaming over HTTP: Ask as Server-Sent Events (with the stored thread), the client disconnect
cancelling the model call, and the live event bus on ``/api/events``."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from ordnung import clock
from ordnung.api.app import create_app
from ordnung.app_context import build_context
from ordnung.llm.base import LLMRequest, StreamEvent
from ordnung.llm.fake import FakeBackend
from ordnung.llm.replay import ReplayBackend
from test_api_support import ASK_ANSWER, CLIENT_HEADERS, TODAY, api_for, sse_messages


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def test_ask_streams_events_and_stores_the_thread(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.post("/api/ask", json={"question": "Is anything due?"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        messages = sse_messages(response.text)
        assert {message["event"] for message in messages} == {"message"}
        events = [json.loads(message["data"]) for message in messages]
        assert [event["type"] for event in events[:-1]] == ["text"] * (len(events) - 1)
        assert "".join(event["text"] for event in events[:-1]).strip() == ASK_ANSWER
        done = events[-1]
        assert done["type"] == "done" and done["text"] == ASK_ANSWER
        assert done["citations"] == [] and "response" not in done
        request = api.backend.calls[-1]
        assert request.purpose == "ask" and request.cache_key and request.prompt_version

        thread = (await api.client.get(f"/api/chat/{done['thread_id']}")).json()
        assert [(message["role"], message["content"]) for message in thread] == [
            ("user", "Is anything due?"),
            ("assistant", ASK_ANSWER),
        ]
        assert thread[1]["id"] == done["message_id"]

        again = await api.client.post(
            "/api/ask", json={"question": "And later?", "thread_id": done["thread_id"]}
        )
        assert json.loads(sse_messages(again.text)[-1]["data"])["thread_id"] == done["thread_id"]
        assert len((await api.client.get(f"/api/chat/{done['thread_id']}")).json()) == 4

        assert (await api.client.post("/api/ask", json={"question": ""})).status_code == 422
        assert (await api.client.get("/api/chat/thr_unknown")).json() == []


async def test_model_failure_arrives_as_an_error_event(data_dir: Path) -> None:
    async with api_for(data_dir) as api:

        class Failing(FakeBackend):
            async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
                yield StreamEvent(type="error", error="Claude is not signed in.")

        api.ctx.llm.backend = Failing()
        response = await api.client.post("/api/ask", json={"question": "Anything?"})
        events = [json.loads(message["data"]) for message in sse_messages(response.text)]
        assert events == [{"type": "error", "error": "Claude is not signed in."}]


# --------------------------------------------------------------------------------------------------
# raw ASGI: disconnects
# --------------------------------------------------------------------------------------------------


class HangingBackend(FakeBackend):
    """Streams one delta, then waits until it is cancelled (like a slow ``claude`` process)."""

    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        self.calls.append(req)
        yield StreamEvent(type="text", text="Thinking ")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def call_until(
    app: FastAPI, method: str, path: str, body: dict[str, Any] | None, stop: Callable[[bytes], bool]
) -> bytes:
    """Call the ASGI app directly and disconnect once ``stop(body_so_far)`` is true."""
    payload = json.dumps(body).encode() if body is not None else b""
    headers = [(b"host", b"127.0.0.1:8765"), (b"content-type", b"application/json")]
    headers += [(name.lower().encode(), value.encode()) for name, value in CLIENT_HEADERS.items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8765),
    }
    received = bytearray()
    gone = asyncio.Event()
    request_sent = False

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body":
            received.extend(message.get("body", b""))
            if stop(bytes(received)):
                gone.set()

    await asyncio.wait_for(app(scope, receive, send), timeout=10)
    return bytes(received)


async def test_disconnect_cancels_the_model_call(data_dir: Path) -> None:
    backend = HangingBackend()
    ctx = build_context(data_dir, backend_obj=backend)
    try:
        app = create_app(ctx, token=None)
        body = await call_until(
            app, "POST", "/api/ask", {"question": "Anything due?"}, lambda sent: b"Thinking" in sent
        )
        assert b'"type":"text"' in body
        assert backend.cancelled
        assert ctx.store.counts()["chat_messages"] == 0  # an interrupted answer is not stored
    finally:
        ctx.close()


async def test_events_stream_bus_events_until_the_client_leaves(data_dir: Path) -> None:
    ctx = build_context(data_dir, backend_obj=FakeBackend())
    try:
        app = create_app(ctx, token=None)

        async def publish_when_subscribed() -> None:
            while ctx.bus.subscriber_count == 0:  # noqa: ASYNC110 - the bus exposes a count, not an event
                await asyncio.sleep(0.01)
            ctx.bus.publish("item.updated", item_id="itm_123")

        publisher = asyncio.create_task(publish_when_subscribed())
        body = await call_until(app, "GET", "/api/events", None, lambda sent: b"itm_123" in sent)
        await publisher
        (message,) = sse_messages(body.decode())
        assert message["event"] == "item.updated"
        assert json.loads(message["data"]) == {"item_id": "itm_123"}
        assert ctx.bus.subscriber_count == 0
    finally:
        ctx.close()


async def test_demo_turns_a_missing_recording_into_a_friendly_event(data_dir: Path, tmp_path: Path) -> None:
    tour = pytest.importorskip("ordnung.demo.tour")
    async with api_for(data_dir, demo=True) as api:
        api.ctx.llm.backend = ReplayBackend(tmp_path / "no-fixtures")
        response = await api.client.post("/api/ask", json={"question": "Something never recorded?"})
        events = [json.loads(message["data"]) for message in sse_messages(response.text)]
        assert events == [{"type": "error", "text": tour.DEMO_MISS_MESSAGE, "error": tour.DEMO_MISS_MESSAGE}]
