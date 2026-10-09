"""Recorded model outputs for demo mode and CI.

Fixture layout: ``<fixtures>/<purpose>/<key[:24]>.json`` where ``key`` is
:func:`ordnung.llm.runtime.request_key` of the request as made (the cache keys it by the model the
call runs on instead: ``LLMService._cache_key``). Each file holds
``{"request": {...summary...}, "response": LLMResponse, "stream": [StreamEvent...]?}``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ordnung.llm.base import LLMBackend, LLMError, LLMRequest, LLMResponse, ReplayMiss, StreamEvent


def fixture_path(root: Path, req: LLMRequest) -> Path:
    from ordnung.llm.runtime import request_key

    return root / req.purpose / f"{request_key(req)[:24]}.json"


def _summary(req: LLMRequest) -> dict[str, Any]:
    return {
        "purpose": req.purpose,
        "model": req.model,
        "prompt_version": req.prompt_version,
        "cache_key": req.cache_key,
        "attachments": [Path(a.path).name for a in req.attachments],
        "doc_ids": req.doc_ids,
        "prompt_head": req.prompt[:400],
    }


class ReplayBackend:
    """Serves recorded responses; raises :class:`ReplayMiss` (or delegates to ``fallback``)."""

    name = "replay"

    def __init__(self, root: Path, fallback: LLMBackend | None = None) -> None:
        self.root = Path(root)
        self.fallback = fallback

    def _load(self, req: LLMRequest) -> dict[str, Any] | None:
        path = fixture_path(self.root, req)
        if not path.exists():
            return None
        recorded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return recorded

    async def complete(self, req: LLMRequest) -> LLMResponse:
        rec = self._load(req)
        if rec is None:
            if self.fallback is not None:
                return await self.fallback.complete(req)
            raise ReplayMiss(f"no recorded response for {req.purpose} ({req.cache_key})")
        resp = LLMResponse.model_validate(rec["response"])
        resp.backend = self.name
        return resp

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        rec = self._load(req)
        if rec is None:
            if self.fallback is not None:
                async for ev in self.fallback.stream(req):
                    yield ev
                return
            yield StreamEvent(type="error", error=f"no recorded response for {req.purpose} ({req.cache_key})")
            return
        events = rec.get("stream")
        if events:
            for raw in events:
                ev = StreamEvent.model_validate(raw)
                if ev.response is not None:
                    ev.response.backend = self.name
                yield ev
            return
        resp = LLMResponse.model_validate(rec["response"])
        resp.backend = self.name
        yield StreamEvent(type="text", text=resp.text)
        yield StreamEvent(type="done", response=resp)


class RecordingBackend:
    """Wraps a live backend and writes every response as a replay fixture.

    Privacy guard: fixtures ship in the repository, so the recorder refuses any request that carries a
    document outside ``allowed_doc_ids`` (the sample-life manifest). Personal documents can never end
    up in a fixture by accident.
    """

    def __init__(self, inner: LLMBackend, root: Path, allowed_doc_ids: set[str] | None = None) -> None:
        self.inner = inner
        self.root = Path(root)
        self.name = inner.name
        self.allowed_doc_ids = allowed_doc_ids

    def _guard(self, req: LLMRequest) -> None:
        if self.allowed_doc_ids is None:
            raise LLMError("recording is only allowed for the sample life (no manifest given)")
        foreign = [d for d in req.doc_ids if d not in self.allowed_doc_ids]
        if foreign:
            raise LLMError(f"refusing to record fixtures for non-sample documents: {foreign}")

    def _write(self, req: LLMRequest, payload: dict[str, Any]) -> None:
        path = fixture_path(self.root, req)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self._guard(req)
        resp = await self.inner.complete(req)
        self._write(req, {"request": _summary(req), "response": resp.model_dump()})
        return resp

    async def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]:
        self._guard(req)
        events: list[dict[str, Any]] = []
        final: LLMResponse | None = None
        async for ev in self.inner.stream(req):
            events.append(ev.model_dump(exclude_none=True))
            if ev.type == "done" and ev.response is not None:
                final = ev.response
            yield ev
        if final is not None:
            self._guard(req)  # Ask adds the documents it read while answering: check them again
            self._write(req, {"request": _summary(req), "response": final.model_dump(), "stream": events})
