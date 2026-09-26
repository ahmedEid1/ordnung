"""Programmable backend for unit tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from ordnung.llm.base import LLMRequest, LLMResponse, StreamEvent, Usage

Responder = Callable[[LLMRequest], dict[str, Any] | str | LLMResponse]


class FakeBackend:
    """Returns canned responses chosen by ``purpose`` (or a callable).

    ``FakeBackend({"extract": {...structured...}, "brief": "Hello"})`` — dict values become
    ``data`` for schema calls, strings become ``text``. Every request is recorded in ``calls``.
    """

    name = "fake"

    def __init__(self, responses: dict[str, Any] | Responder | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[LLMRequest] = []

    def _resolve(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        value: Any
        if callable(self.responses):
            value = self.responses(req)
        else:
            if req.purpose not in self.responses:
                raise KeyError(f"FakeBackend has no response for purpose {req.purpose!r}")
            value = self.responses[req.purpose]
            if callable(value):
                value = value(req)
        if isinstance(value, LLMResponse):
            return value
        usage = Usage(input_tokens=100, output_tokens=50, cost_usd=0.001, duration_ms=5, turns=1)
        if isinstance(value, dict):
            return LLMResponse(text="", data=value, usage=usage, model=req.model, backend=self.name)
        return LLMResponse(text=str(value), data=None, usage=usage, model=req.model, backend=self.name)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        return self._resolve(req)

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        resp = self._resolve(req)
        for word in resp.text.split(" "):
            yield StreamEvent(type="text", text=word + " ")
        yield StreamEvent(type="done", response=resp)
