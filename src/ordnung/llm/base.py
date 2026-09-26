"""LLM abstraction. Every model call in Ordnung goes through an :class:`LLMBackend`.

Backends:
* ``ClaudeCLIBackend`` — runs the user's own ``claude`` CLI in headless mode (``claude -p``).
* ``ReplayBackend`` / ``RecordingBackend`` — recorded fixtures for demo mode and CI.
* ``FakeBackend`` — programmable responses for unit tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

LLMPurpose = Literal[
    "transcribe", "extract", "review", "brief", "ask", "draft", "capture", "eval_baseline", "doctor", "test"
]
INTERACTIVE_PURPOSES: frozenset[str] = frozenset({"ask", "draft", "capture", "brief", "doctor"})


class Attachment(BaseModel):
    """A file sent to the model as a content block (image or PDF) — never via a tool."""

    path: Path
    media_type: Literal["image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"]


class LLMRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    purpose: LLMPurpose
    prompt: str
    system: str
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    attachments: list[Attachment] = Field(default_factory=list)
    doc_ids: list[str] = Field(default_factory=list)  # accounting: which documents this call carries
    model: str = "sonnet"
    tools: list[str] = Field(default_factory=list)
    mcp_config: dict[str, Any] | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    timeout_s: float = 240.0
    cache_key: str | None = None
    max_budget_usd: float | None = None
    prompt_version: str = "1"


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    turns: int = 0


class LLMResponse(BaseModel):
    text: str = ""
    data: dict[str, Any] | None = None
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    cache_hit: bool = False
    backend: str = ""


class StreamEvent(BaseModel):
    type: Literal["text", "tool_use", "tool_result", "done", "error"]
    text: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    response: LLMResponse | None = None
    error: str | None = None


class LLMError(RuntimeError):
    """Base class for model-call failures (message is user-presentable)."""


class ClaudeNotInstalled(LLMError):
    pass


class ClaudeAuthError(LLMError):
    pass


class ClaudeRateLimited(LLMError):
    def __init__(self, message: str, reset_at: str | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class ClaudeTimeout(LLMError):
    pass


class ClaudeBadOutput(LLMError):
    pass


class ReplayMiss(LLMError):
    pass


@runtime_checkable
class LLMBackend(Protocol):
    name: str

    async def complete(self, req: LLMRequest) -> LLMResponse: ...

    def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]: ...
