"""Ask: a question streamed back as Server-Sent Events, and the stored conversation of a thread.

``POST /api/ask`` answers with ``text/event-stream``: one default ``message`` event per
:class:`StreamEvent` (JSON with a ``type``) — ``tool_use``/``tool_result`` for the visible tool trace,
one ``text`` event without text when the answer is being written (its words are never sent before
the check, ADR 0008), then ``done`` (the checked answer's text, the check's note, validated
citations, message and thread ids) or ``error``. Closing the connection stops the answer and the
``claude`` process behind it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import ApiState, StateDep, StoreDep
from ordnung.api.routes.demo import optional_demo_function
from ordnung.api.sse import EventStreamResponse, close_iterator, model_stream_response
from ordnung.assistant.ask import ask_stream, stored_answer
from ordnung.assistant.citations import CitationRef
from ordnung.llm.base import StreamEvent as LLMStreamEvent
from ordnung.models import ChatMessage

router = APIRouter(tags=["ask"])

MAX_QUESTION_CHARS = 4000


class AskRequest(BaseModel):
    """A question, optionally continuing an earlier thread."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    thread_id: str | None = None


class StreamEvent(BaseModel):
    """One event of the streamed answer (the JSON data of an SSE ``message`` event)."""

    type: Literal["text", "tool_use", "tool_result", "done", "error"]
    text: str | None = Field(
        default=None,
        description="tool label/summary or the checked answer (done); none on the text event that says the "
        "answer is being written",
    )
    name: str | None = Field(default=None, description="tool name (tool_use / tool_result)")
    input: dict[str, Any] | None = Field(default=None, description="tool input (tool_use)")
    error: str | None = None
    note: str | None = Field(
        default=None, description="what the answer check left out or quoted (done); shown apart from the text"
    )
    citations: list[CitationRef] | None = Field(default=None, description="validated citations (done)")
    message_id: str | None = None
    thread_id: str | None = None


def _service_stream(state: ApiState, question: str, thread_id: str | None) -> AsyncIterator[LLMStreamEvent]:
    """The Ask service's events; in the demo a missing recording becomes one friendly event."""
    events = ask_stream(state.ctx, question, thread_id)
    friendly = optional_demo_function("demo_safe_stream") if state.demo else None
    if friendly is None:
        return events
    # a replayed answer would appear all at once: stream it at a reading pace, like the real thing
    paced = optional_demo_function("paced_replay")
    safe = friendly(events, demo=True)
    return paced(safe) if paced is not None else safe


async def answer_events(state: ApiState, question: str, thread_id: str | None) -> AsyncIterator[StreamEvent]:
    """The Ask service's events in the API's shape (model usage and raw responses left out)."""
    stream = _service_stream(state, question, thread_id)
    try:
        async for event in stream:
            yield StreamEvent.model_validate(event.model_dump(exclude={"response"}))
    finally:
        await close_iterator(stream)


@router.post(
    "/ask",
    response_class=EventStreamResponse,
    responses={200: {"model": StreamEvent, "description": "A stream of StreamEvent messages (SSE)."}},
)
async def ask(body: AskRequest, state: StateDep) -> EventStreamResponse:
    """Answer a question about the person's records, streamed."""
    return model_stream_response(answer_events(state, body.question, body.thread_id))


class ThreadMessage(ChatMessage):
    """A stored question or answer; an answer's check note is split off its text into ``note``."""

    note: str | None = Field(
        default=None, description="what the answer check left out or quoted; shown apart from the text"
    )


@router.get("/chat/{thread_id}", response_model=list[ThreadMessage])
def chat_thread(thread_id: str, store: StoreDep) -> list[ThreadMessage]:
    """The questions and answers of a thread, oldest first."""
    messages = []
    for message in store.list_chat_messages(thread_id):
        body, note = stored_answer(message)
        messages.append(ThreadMessage.model_validate({**message.model_dump(), "content": body, "note": note}))
    return messages
