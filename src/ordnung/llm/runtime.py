"""LLMService — the one entry point the rest of the app uses for model calls.

Adds, on top of any backend: a persistent response cache (so re-processing is free), per-call usage
accounting (tokens, API-equivalent cost, latency, cache hits) and backend selection.

Every call writes one row of the usage log (never the prompt or the answer): besides the accounting,
its replay/cache key, the prompt template and version, the model that answered and — when the caller
passes the step it belongs to (``trace``, :mod:`ordnung.trace`) — the job, pipeline stage and span.
The row's ``outcome`` is decided here, by one policy (:func:`call_outcome`): the caller may pass a
``validate`` function (it raises when the answer is unusable) and, for a repair, the usage-log id of
the call it retries (``repair_of``, from :attr:`~ordnung.llm.base.LLMResponse.call_id`).

A letter deleted while a call that carried it was under way is treated as deleted after the call: the
sink writes the call's row without the letter's id, replay key, span or job, and caches nothing.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ordnung.llm.base import LLMBackend, LLMError, LLMRequest, LLMResponse, StreamEvent, Usage
from ordnung.models import CallOutcome
from ordnung.trace.facts import model_call
from ordnung.trace.spans import NO_SPAN, Span

if TYPE_CHECKING:
    from ordnung.events import EventBus

log = logging.getLogger(__name__)


class UsageSink(Protocol):
    """The subset of :class:`ordnung.db.store.Store` the service needs."""

    def cache_get(self, key: str) -> dict[str, Any] | None: ...

    def cache_put(
        self,
        key: str,
        purpose: str,
        model: str,
        response: dict[str, Any],
        doc_sha: str | None = None,
        *,
        doc_ids: Sequence[str] = (),
    ) -> bool: ...

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
        *,
        request_key: str | None = None,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        served_model: str | None = None,
        job_id: str | None = None,
        stage: str | None = None,
        span_id: str | None = None,
        repair_of: int | None = None,
        outcome: CallOutcome = "ok",
    ) -> int | None: ...


#: Checks a model answer: raises (``ValueError``, pydantic's ``ValidationError`` …) when it is unusable.
Validator = Callable[[LLMResponse], object]


def call_outcome(*, failed: bool, valid: bool, repair: bool) -> CallOutcome:
    """How a call turned out: ``failed`` when it errored or a repair's answer was unusable too,
    ``invalid`` when a first answer was unusable (a repair may follow), ``repaired`` when a repair's
    answer was usable, else ``ok`` (a call nobody validates counts as usable)."""
    if failed:
        return "failed"
    if not valid:
        return "failed" if repair else "invalid"
    return "repaired" if repair else "ok"


def _valid(validate: Validator | None, response: LLMResponse) -> bool:
    if validate is None:
        return True
    try:
        validate(response)
    except Exception:  # whatever the caller's check raises means "unusable"; the caller raises its own error
        return False
    return True


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

    def _record(
        self,
        req: LLMRequest,
        resp: LLMResponse | None,
        error: str | None = None,
        *,
        outcome: CallOutcome | None = None,
        trace: Span = NO_SPAN,
        repair_of: int | None = None,
    ) -> int | None:
        """Write the usage-log row of a call; returns its id (``None`` without a log, or when writing
        failed — accounting never breaks a call)."""
        if self.sink is None:
            return None
        try:
            return self.sink.log_llm_call(
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
                request_key=request_key(req),
                prompt_name=req.prompt_name or req.purpose,
                prompt_version=req.prompt_version,
                served_model=(resp.model or None) if resp else None,
                job_id=trace.job_id,
                stage=trace.stage if trace.active else None,
                span_id=trace.id,
                repair_of=repair_of,
                outcome=outcome or call_outcome(failed=error is not None, valid=True, repair=False),
            )
        except Exception:
            log.warning("llm usage logging failed", exc_info=True)
            return None

    def _describe(
        self,
        trace: Span,
        req: LLMRequest,
        resp: LLMResponse | None,
        *,
        call_id: int | None,
        outcome: CallOutcome,
        repair_of: int | None,
    ) -> None:
        """Describe the call on its model step (the latency its backend reported lays out the demo's)."""
        trace.record_call(
            recorded_ms=0 if resp is None or resp.cache_hit else resp.usage.duration_ms,
            **model_call(
                call_id=call_id,
                purpose=req.purpose,
                prompt_name=req.prompt_name or req.purpose,
                prompt_version=req.prompt_version,
                request_model=req.model,
                served_model=(resp.model or None) if resp else None,
                cache_hit=bool(resp and resp.cache_hit),
                outcome=outcome,
                repair_of=repair_of,
            ),
        )

    def _settle(
        self,
        req: LLMRequest,
        resp: LLMResponse,
        *,
        trace: Span,
        validate: Validator | None,
        repair_of: int | None,
    ) -> LLMResponse:
        """Judge an answer, log the call and describe it on its step; the answer carries its log id."""
        outcome = call_outcome(failed=False, valid=_valid(validate, resp), repair=repair_of is not None)
        call_id = self._record(req, resp, outcome=outcome, trace=trace, repair_of=repair_of)
        self._describe(trace, req, resp, call_id=call_id, outcome=outcome, repair_of=repair_of)
        return resp.model_copy(update={"call_id": call_id})

    async def complete(
        self,
        req: LLMRequest,
        *,
        use_cache: bool = True,
        trace: Span = NO_SPAN,
        validate: Validator | None = None,
        repair_of: int | None = None,
    ) -> LLMResponse:
        """Run a request through cache → backend → accounting. ``use_cache=False`` forces a fresh call
        (still written to the cache), used by *reprocess*.

        ``trace`` is the model step this call is (described with the call); ``validate`` judges the
        answer for the log's ``outcome`` (the caller still parses it and raises its own error);
        ``repair_of`` is the log id of the call a repair retries. The answer's
        :attr:`~ordnung.llm.base.LLMResponse.call_id` is its usage-log row.
        """
        key = request_key(req)
        if use_cache and req.cache_key is not None:
            cached = self._cache_get(key)
            if cached is not None:
                return self._settle(req, cached, trace=trace, validate=validate, repair_of=repair_of)
        try:
            resp = await self.backend.complete(req)
        except LLMError as exc:
            call_id = self._record(req, None, str(exc), outcome="failed", trace=trace, repair_of=repair_of)
            self._describe(trace, req, None, call_id=call_id, outcome="failed", repair_of=repair_of)
            raise
        resp = self._settle(req, resp, trace=trace, validate=validate, repair_of=repair_of)
        if req.cache_key is not None and self.sink is not None:
            try:
                self.sink.cache_put(
                    key,
                    req.purpose,
                    resp.model or req.model,
                    resp.model_dump(),
                    doc_sha=self._cache_doc_sha(req),
                    doc_ids=list(req.doc_ids),
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
