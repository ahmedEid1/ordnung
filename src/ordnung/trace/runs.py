"""Starting and keeping the trace of a reading (the pipeline's side of :mod:`ordnung.trace`).

Written policy (ADR 0007):

* **One trace per reading.** Every run of the pipeline for a letter — read on arrival, or read
  again — is one trace: its number (``reading`` 1, 2, …), the job that ran it and whether it was
  a reading again. A letter keeps its newest :data:`KEPT_READINGS` readings; older ones are deleted
  when a new one is stored (their usage-log rows stay, as numbers).
* **Stored once, never in the way.** A trace is written when the reading ends — finished, failed,
  paused by a rate limit or stopped — in one insert. Storing it never raises: a trace that cannot
  be written is logged and dropped, and the letter's reading is not affected. A letter deleted while
  it was being read leaves no trace.
* **Time.** Readings are timed by the clock (``measured``), except in the demo (``settings.demo``),
  whose model calls replay recordings: there a reading starts at :data:`RECORDED_START` on the demo's
  day plus :data:`RECORDED_GAP` for each reading already kept, and is laid out from the recorded
  latencies (:mod:`ordnung.trace.spans`), so rebuilding the demo gives the same trace.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING

from ordnung import clock
from ordnung.trace.spans import Tracer, trace_id_for

if TYPE_CHECKING:
    from ordnung.db.store import Store

log = logging.getLogger(__name__)

KEPT_READINGS = 5
RECORDED_START = time(8, 0)
RECORDED_GAP = timedelta(minutes=2)


def recorded_start(store: Store) -> datetime:
    """When a demo reading starts: the demo's day at :data:`RECORDED_START` (UTC), one
    :data:`RECORDED_GAP` later for every reading already kept."""
    day = datetime.combine(clock.today(), RECORDED_START, tzinfo=UTC)
    return day + RECORDED_GAP * store.count_trace_runs()


def start_trace(store: Store, doc_id: str, *, job_id: str | None, again: bool, recorded: bool) -> Tracer:
    """The tracer of a new reading of ``doc_id`` (its root span is open)."""
    reading = store.next_trace_reading(doc_id)
    return Tracer(
        doc_id=doc_id,
        trace_id=trace_id_for(doc_id, reading),
        job_id=job_id,
        timing="recorded" if recorded else "measured",
        started_at=recorded_start(store) if recorded else None,
        reading=reading,
        trigger="read_again" if again else "read",
    )


def keep_trace(store: Store, tracer: Tracer) -> bool:
    """Store a finished reading (see the module docstring); ``False`` when it was not stored."""
    try:
        if store.get_document(tracer.doc_id) is None:
            return False
        store.save_trace(tracer.records(), keep=KEPT_READINGS)
    except Exception:
        log.warning("the trace of reading %s could not be stored", tracer.doc_id, exc_info=True)
        return False
    return True
