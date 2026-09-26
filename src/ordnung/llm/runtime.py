"""LLMService — the one entry point the rest of the app uses for model calls.

Adds, on top of any backend: a persistent response cache (so re-processing is free), per-call usage
accounting (tokens, API-equivalent cost, latency, cache hits) and backend selection.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ordnung.llm.base import LLMBackend, LLMError, LLMRequest, LLMResponse, StreamEvent, Usage

if TYPE_CHECKING:
    from ordnung.events import EventBus

log = logging.getLogger(__name__)


class UsageSink(Protocol):
    """The subset of :class:`ordnung.db.store.Store` the service needs."""

    def cache_get(self, key: str) -> dict[str, Any] | None: ...

    def cache_put(
        self, key: str, purpose: str, model: str, response: dict[str, Any], doc_sha: str | None = None
    ) -> None: ...

    def log_llm_call(
        self,
        purpose: str,
        model: str,
        backend: str,
        usage: Usage,
        ok: bool = True,
        error: str | None = None,
        cache_hit: bool = False,
        doc_ids: list[str] | None = None,
        pages_sent: int = 0,
        bytes_sent: int = 0,
    ) -> None: ...


def _bytes_sent(req: LLMRequest) -> int:
    total = len(req.prompt.encode("utf-8"))
    for att in req.attachments:
        with contextlib.suppress(OSError):
            total += Path(att.path).stat().st_size
    return total


def request_key(req: LLMRequest) -> str:
    """Stable key for cache + replay. Callers set ``cache_key`` to identify the *input*."""
    basis = req.cache_key if req.cache_key is not None else req.prompt
    raw = f"{req.purpose}|{req.prompt_version}|{req.model}|{basis}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LLMService:
    def __init__(
        self, backend: LLMBackend, sink: UsageSink | None = None, bus: EventBus | None = None
    ) -> None:
        self.backend = backend
        self.sink = sink
        self.bus = bus

    @property
    def backend_name(self) -> str:
        return self.backend.name

    def _cache_doc_sha(self, req: LLMRequest) -> str | None:
        # cache rows are tagged with every document the call carried ("doc_a|doc_b"), so deleting any
        # of them purges the cached output (a brief or review built from several letters included)
        return "|".join(sorted(set(req.doc_ids))) or None

    def _cache_get(self, key: str) -> LLMResponse | None:
        if self.sink is None:
            return None
        try:
            hit = self.sink.cache_get(key)
        except Exception:  # cache must never break a call
            log.warning("llm cache read failed", exc_info=True)
            return None
        if hit is None:
            return None
        try:
            resp = LLMResponse.model_validate(hit)
        except Exception:
            return None
        resp.cache_hit = True
        return resp

    def _record(self, req: LLMRequest, resp: LLMResponse | None, error: str | None = None) -> None:
        if self.sink is None:
            return
        try:
            self.sink.log_llm_call(
                purpose=req.purpose,
                model=(resp.model if resp else req.model) or req.model,
                backend=(resp.backend if resp else self.backend.name) or self.backend.name,
                usage=(resp.usage if resp and not resp.cache_hit else Usage()),
                ok=error is None,
                error=error,
                cache_hit=bool(resp and resp.cache_hit),
                doc_ids=list(req.doc_ids),
                pages_sent=0 if (resp and resp.cache_hit) else len(req.attachments),
                bytes_sent=0 if (resp and resp.cache_hit) else _bytes_sent(req),
            )
        except Exception:
            log.warning("llm usage logging failed", exc_info=True)

    async def complete(self, req: LLMRequest, *, use_cache: bool = True) -> LLMResponse:
        """Run a request through cache → backend → accounting. ``use_cache=False`` forces a fresh call
        (still written to the cache), used by *reprocess*."""
        key = request_key(req)
        if use_cache and req.cache_key is not None:
            cached = self._cache_get(key)
            if cached is not None:
                self._record(req, cached)
                return cached
        try:
            resp = await self.backend.complete(req)
        except LLMError as exc:
            self._record(req, None, error=str(exc))
            raise
        self._record(req, resp)
        if req.cache_key is not None and self.sink is not None:
            try:
                self.sink.cache_put(
                    key,
                    req.purpose,
                    resp.model or req.model,
                    resp.model_dump(),
                    doc_sha=self._cache_doc_sha(req),
                )
            except Exception:
                log.warning("llm cache write failed", exc_info=True)
        return resp

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        final: LLMResponse | None = None
        error: str | None = None
        async for ev in self.backend.stream(req):
            if ev.type == "done":
                final = ev.response
            elif ev.type == "error":
                error = ev.error
            yield ev
        self._record(req, final, error=error if final is None else None)


def make_backend(
    kind: str | None = None, *, concurrency: int = 2, fixtures: Path | None = None
) -> LLMBackend:
    """Create a backend by name: ``claude`` (default), ``replay``, ``replay+claude``, ``fake``.

    ``ORDNUNG_BACKEND`` overrides the default. Recording is done by the demo loader only.
    """
    from ordnung.config import fixtures_dir
    from ordnung.llm.claude_cli import ClaudeCLIBackend
    from ordnung.llm.fake import FakeBackend
    from ordnung.llm.replay import ReplayBackend

    kind = (kind or os.environ.get("ORDNUNG_BACKEND") or "claude").lower()
    root = fixtures or fixtures_dir()
    if kind == "fake":
        return FakeBackend()
    if kind == "replay":
        return ReplayBackend(root)
    live = ClaudeCLIBackend(concurrency=concurrency)
    if kind in ("replay+claude", "replay-then-claude"):
        return ReplayBackend(root, fallback=live)
    if kind == "record":
        raise ValueError("use ordnung.demo.loader to record fixtures (it supplies the sample manifest)")
    return live
