"""A small, explicit tracer for one reading of a letter.

Written policy (ADR 0007):

* **Explicit, no global state.** The pipeline creates one :class:`Tracer` per reading and hands
  spans down as a ``trace`` argument. Every function that takes one defaults to :data:`NO_SPAN`,
  which records nothing: no clock reads, no rows. Nothing is written while the letter is read; at
  the end :meth:`Tracer.records` turns the spans into rows and the store inserts them at once.
* **Identity.** A span's ``key`` is its path: the parent's key, then ``kind:label`` where the label
  is the key the caller gives (``extract``, a to-do's slot, ``page:2``); repeats of the same path get
  ``#2``, ``#3`` in creation order. The same step has the same key in every reading of a letter, so
  two readings compare step by step. Ids are ``spn_`` + a hash of the trace id and the key: a
  rebuild of the demo gives the same ids.
* **Time.** ``measured``: a monotonic clock, anchored at the wall-clock time (UTC) the reading
  started, to the microsecond. ``recorded`` (the demo, whose model calls replay recordings in
  milliseconds): no clock is read — the reading starts at the time it is given and
  :meth:`Tracer.records` lays the spans out from the latency the model backend reported for each
  call (:meth:`Span.record_call`); a step of code takes no time. Children follow one another in
  creation order, except under a span opened with ``parallel=True`` (the pages of a photo, read at
  the same time): its children all start with it and are ordered by key, so the layout never
  depends on which concurrent task happened to finish first.
* **What a span holds** is the caller's choice, written down in :mod:`ordnung.trace.facts`: counts,
  codes, scores, dates Ordnung computed and ids of records — never letter text.
* **Errors.** An exception leaving a span marks it ``error`` with the exception's class name only
  (its message may quote the letter); the pipeline gives the reading itself the message it showed
  the person.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from ordnung.models import SpanKind, SpanStatus, TraceSpanRecord

Timing = Literal["measured", "recorded"]
_NS_PER_MS = 1_000_000


def span_id(trace_id: str, key: str) -> str:
    """The id of the span ``key`` of the reading ``trace_id``."""
    return "spn_" + hashlib.sha1(f"{trace_id}|{key}".encode(), usedforsecurity=False).hexdigest()[:16]


def trace_id_for(doc_id: str, reading: int) -> str:
    """The id of a letter's ``reading``-th reading (1, 2, …)."""
    return "trc_" + hashlib.sha1(f"{doc_id}|{reading}".encode(), usedforsecurity=False).hexdigest()[:16]


def iso_utc(moment: datetime) -> str:
    """``2026-09-28T08:00:41.080000Z`` (UTC, microseconds)."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class Span:
    """One step of a reading. Open children with :meth:`span`; describe the step with :meth:`set`.

    :data:`NO_SPAN` is the inactive span: every method does nothing and :meth:`span` yields it again.
    """

    __slots__ = (
        "_tracer",
        "attributes",
        "children",
        "end_ns",
        "error",
        "key",
        "kind",
        "name",
        "order",
        "parallel",
        "parent",
        "recorded_ms",
        "stage",
        "start_ns",
        "status",
    )

    def __init__(
        self,
        tracer: Tracer | None,
        parent: Span | None,
        kind: SpanKind,
        name: str,
        key: str,
        stage: str | None,
        attributes: dict[str, Any],
        *,
        parallel: bool = False,
        order: int = 0,
        start_ns: int = 0,
    ) -> None:
        self._tracer = tracer
        self.parent = parent
        self.kind: SpanKind = kind
        self.name = name
        self.key = key
        self.stage = stage
        self.attributes = attributes
        self.parallel = parallel
        self.order = order
        self.start_ns = start_ns
        self.end_ns: int | None = None
        self.status: SpanStatus = "ok"
        self.error: str | None = None
        self.recorded_ms: float | None = None
        self.children: list[Span] = []

    @property
    def active(self) -> bool:
        """Whether this span records anything (``False`` for :data:`NO_SPAN`)."""
        return self._tracer is not None

    @property
    def id(self) -> str | None:
        """The span's id (``None`` when inactive)."""
        return span_id(self._tracer.trace_id, self.key) if self._tracer is not None else None

    @property
    def job_id(self) -> str | None:
        """The job of the reading this span belongs to."""
        return self._tracer.job_id if self._tracer is not None else None

    def set(self, **attributes: Any) -> None:
        """Add facts to the span (see :mod:`ordnung.trace.facts` for what may go in)."""
        if self._tracer is not None:
            self.attributes.update(attributes)

    def record_call(self, *, recorded_ms: float, **attributes: Any) -> None:
        """A model call answered in this span: the latency its backend reported (the layout of a
        ``recorded`` reading) and the facts about it."""
        if self._tracer is not None:
            self.recorded_ms = max(0.0, float(recorded_ms))
            self.attributes.update(attributes)

    def fail(self, error: str) -> None:
        """Mark the step as failed with ``error`` (a class name or a message written for people)."""
        if self._tracer is not None:
            self.status = "error"
            self.error = error

    @contextmanager
    def span(
        self,
        kind: SpanKind,
        name: str,
        *,
        key: str | None = None,
        stage: str | None = None,
        parallel: bool = False,
        **attributes: Any,
    ) -> Iterator[Span]:
        """Open a child step for the ``with`` block (``key`` defaults to ``name``; ``stage`` to the
        parent's). An exception leaving the block marks the step ``error`` with its class name."""
        if self._tracer is None:
            yield self
            return
        child = self._tracer.open(self, kind, name, key, stage, parallel, attributes)
        try:
            yield child
        except BaseException as exc:
            if child.status == "ok":
                child.fail(type(exc).__name__)
            raise
        finally:
            self._tracer.close(child)


NO_SPAN = Span(None, None, "run", "", "", None, {})
"""The inactive span: tracing is off (the default of every ``trace`` argument)."""


class Tracer:
    """The spans of one reading of one letter, kept in memory until :meth:`records`.

    ``root`` is the reading itself (kind ``run``), open from the start; :meth:`finish` closes it.
    """

    def __init__(
        self,
        *,
        doc_id: str,
        trace_id: str,
        job_id: str | None = None,
        timing: Timing = "measured",
        started_at: datetime | None = None,
        name: str = "Read letter",
        **attributes: Any,
    ) -> None:
        self.doc_id = doc_id
        self.trace_id = trace_id
        self.job_id = job_id
        self.timing: Timing = timing
        self._lock = threading.Lock()
        self._order = 0
        self._paths: Counter[str] = Counter()
        self._started_at = started_at or datetime.now(UTC)
        self._perf0 = time.perf_counter_ns()
        self.root = self.open(None, "run", name, "run", None, False, {**attributes, "timing": timing})

    def _now(self) -> int:
        return time.perf_counter_ns() - self._perf0 if self.timing == "measured" else 0

    def open(
        self,
        parent: Span | None,
        kind: SpanKind,
        name: str,
        key: str | None,
        stage: str | None,
        parallel: bool,
        attributes: dict[str, Any],
    ) -> Span:
        """Create a span under ``parent`` (the root when ``parent`` is ``None``)."""
        label = key if key is not None else name
        path = label if parent is None else f"{parent.key}/{kind}:{label}"
        with self._lock:
            self._paths[path] += 1
            repeat = self._paths[path]
            self._order += 1
            span = Span(
                self,
                parent,
                kind,
                name,
                path if repeat == 1 else f"{path}#{repeat}",
                stage if stage is not None else (parent.stage if parent is not None else None),
                dict(attributes),
                parallel=parallel,
                order=self._order,
                start_ns=self._now(),
            )
            if parent is not None:
                parent.children.append(span)
        return span

    def close(self, span: Span) -> None:
        """End ``span`` now (a second close keeps the first end)."""
        if span.end_ns is None:
            span.end_ns = max(span.start_ns, self._now())

    def finish(self, *, error: str | None = None, **attributes: Any) -> None:
        """End the reading: its outcome's facts, and ``error`` (written for people) if it failed."""
        self.root.set(**attributes)
        if error is not None:
            self.root.fail(error)
        self.close(self.root)

    # ---------------------------------------------------------------------------------- rows

    def _children(self, span: Span) -> list[Span]:
        if self.timing == "recorded" and span.parallel:
            return sorted(span.children, key=lambda child: child.key)
        if self.timing == "recorded":
            return sorted(span.children, key=lambda child: child.order)
        return sorted(span.children, key=lambda child: (child.start_ns, child.order))

    def _layout(self, span: Span, start: int) -> int:
        """Place ``span`` at ``start`` (recorded timing) and return its end."""
        span.start_ns = start
        end = start + round((span.recorded_ms or 0.0) * _NS_PER_MS)
        cursor = start
        for child in self._children(span):
            child_end = self._layout(child, start if span.parallel else cursor)
            if not span.parallel:
                cursor = child_end
            end = max(end, child_end)
        span.end_ns = end
        return end

    def _walk(self, span: Span) -> Iterator[Span]:
        yield span
        for child in self._children(span):
            yield from self._walk(child)

    def records(self) -> list[TraceSpanRecord]:
        """The reading's spans as rows, depth-first in display order (``seq``)."""
        with self._lock:
            spans = list(self._walk(self.root))
            for span in spans:
                self.close(span)
            if self.timing == "recorded":
                self._layout(self.root, 0)
            return [self._record(seq, span) for seq, span in enumerate(spans)]

    def _record(self, seq: int, span: Span) -> TraceSpanRecord:
        return TraceSpanRecord(
            id=span_id(self.trace_id, span.key),
            trace_id=self.trace_id,
            doc_id=self.doc_id,
            job_id=self.job_id,
            parent_id=span_id(self.trace_id, span.parent.key) if span.parent is not None else None,
            key=span.key,
            seq=seq,
            kind=span.kind,
            name=span.name,
            stage=span.stage,
            started_at=iso_utc(self._started_at + timedelta(microseconds=span.start_ns // 1000)),
            ended_at=iso_utc(self._started_at + timedelta(microseconds=(span.end_ns or 0) // 1000)),
            status=span.status,
            error=span.error,
            attributes=span.attributes,
        )
