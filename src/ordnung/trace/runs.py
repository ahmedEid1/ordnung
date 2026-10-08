"""Starting and keeping the trace of a reading (the pipeline's side of :mod:`ordnung.trace`).

Written policy (ADR 0007):

* **One trace per reading.** Every run of the pipeline for a letter — read on arrival, or read
  again — is one trace: its number (``reading`` 1, 2, …), the job that ran it and whether it was
  a reading again.
* **A reading's number is reserved when it starts.** :func:`start_trace` takes the letter's next
  number and stores the reading's root span as ``running`` in one transaction, so two readings of
  one letter at once get two numbers, and a reading whose trace is never stored (the process was
  killed, storing failed) still used its number. A reading left ``running`` by a previous process
  is marked stopped at the next start (:func:`recover_readings`). Running readings are not shown.
* **Trace ids never repeat.** A measured reading's trace id is random, so a model call logged by a
  reading whose trace was lost can never be joined to a later one. Only the demo's recorded
  readings hash the letter and the reading's number, so a rebuild gives the same ids.
* **How a reading ended** is a code, never a message that could quote the letter or the model:
  ``done``; ``failed`` with the kind of failure (:data:`FAILURES`); or interrupted — ``paused`` by a
  usage limit or by Claude not installed, not signed in or too old (:data:`INTERRUPTIONS` says which), or
  ``stopped`` by a shutdown — and read again later. The view turns codes into the
  sentences of :func:`ending_message`.
* **What is kept.** A letter keeps its newest :data:`KEPT_READINGS` readings that ran to the end
  (done or failed) and, of the interrupted ones, only the newest — and only while it is newer than
  the oldest reading kept — so retries after a usage limit never push a good reading out. Older
  ones are deleted when a new one is stored (their usage-log rows stay, as numbers).
* **Stored once, never in the way.** A trace is written when the reading ends, in one insert.
  Reserving or storing it never raises: a trace that cannot be written is logged and dropped, and
  the letter's reading is not affected. A letter deleted while it was being read leaves no trace.
* **Time.** Readings are timed by the clock (``measured``), except in the demo (``settings.demo``),
  whose model calls replay recordings: there a reading starts at :data:`RECORDED_START` on the demo's
  day plus :data:`RECORDED_GAP` for each reading already kept, and is laid out from the recorded
  latencies (:mod:`ordnung.trace.spans`), so rebuilding the demo gives the same trace.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING

from ordnung import clock
from ordnung.models import ReadingEnd
from ordnung.trace.spans import Tracer, trace_id_for

if TYPE_CHECKING:
    from ordnung.db.store import Store

log = logging.getLogger(__name__)

KEPT_READINGS = 5
RECORDED_START = time(8, 0)
RECORDED_GAP = timedelta(minutes=2)

#: Readings that did not run to the end: they are read again later and don't count towards
#: :data:`KEPT_READINGS`.
INTERRUPTED: frozenset[str] = frozenset({"paused", "stopped"})
#: Why a reading failed, as the code the root span stores, and the sentence the view shows
#: (``not_installed`` and ``not_signed_in``: readings stored before Claude not ready paused them instead).
FAILURES: dict[str, str] = {
    "no_text": "We couldn't find any readable text in this document.",
    "trashed": "The letter was deleted before it was read, so it was not sent to Claude.",
    "trashed_meanwhile": "The letter was deleted while it was being read, so it was not sent to Claude again.",
    "gone": "The letter no longer existed.",
    "file": "The file couldn't be read.",
    "not_installed": "Claude Code wasn't installed.",
    "not_signed_in": "Claude Code wasn't signed in.",
    "timeout": "Claude took too long to answer.",
    "claude_error": "Claude reported an error.",
    "unusable_answer": "Claude's answer couldn't be understood, even after a second try.",
    "unexpected": "Something went wrong while reading this letter.",
}
INTERRUPTIONS: dict[str, str] = {
    "paused": "Paused: Claude's usage limit was reached. The letter is read again when it resets.",
    "paused_not_installed": "Paused: Claude Code wasn't installed. The letter is read once Claude is ready.",
    "paused_not_signed_in": "Paused: Claude Code wasn't signed in. The letter is read once Claude is ready.",
    "paused_outdated": "Paused: Claude Code was too old. The letter is read once Claude is ready.",
    "stopped": "Stopped: Ordnung was closed before the letter was finished. It is read again at the next start.",
}


def ending_message(code: str | None) -> str | None:
    """The sentence for a reading's ending code (``None`` for a reading that was done)."""
    if code is None:
        return None
    return INTERRUPTIONS.get(code) or FAILURES.get(code) or FAILURES["unexpected"]


def recorded_start(store: Store) -> datetime:
    """When a demo reading starts: the demo's day at :data:`RECORDED_START` (UTC), one
    :data:`RECORDED_GAP` later for every reading already kept."""
    day = datetime.combine(clock.today(), RECORDED_START, tzinfo=UTC)
    return day + RECORDED_GAP * store.count_trace_runs()


def start_trace(store: Store, doc_id: str, *, job_id: str | None, again: bool, recorded: bool) -> Tracer:
    """The tracer of a new reading of ``doc_id`` (its root span is open and reserved as running)."""
    started_at = recorded_start(store) if recorded else None
    reading = 1
    try:
        with store.tx():
            reading = store.next_trace_reading(doc_id)
            tracer = _tracer(doc_id, reading, job_id=job_id, again=again, started_at=started_at)
            store.reserve_trace(tracer.reservation())
    except Exception:
        # the letter may be gone (the pipeline reports that); the reading goes on, unreserved
        log.warning("a reading of %s could not be reserved", doc_id, exc_info=True)
        return _tracer(doc_id, reading, job_id=job_id, again=again, started_at=started_at)
    return tracer


def _tracer(
    doc_id: str, reading: int, *, job_id: str | None, again: bool, started_at: datetime | None
) -> Tracer:
    recorded = started_at is not None
    return Tracer(
        doc_id=doc_id,
        trace_id=trace_id_for(doc_id, reading) if recorded else "trc_" + secrets.token_hex(8),
        job_id=job_id,
        timing="recorded" if recorded else "measured",
        started_at=started_at,
        reading=reading,
        trigger="read_again" if again else "read",
    )


def finish_trace(store: Store, tracer: Tracer, ended: ReadingEnd = "done", code: str | None = None) -> bool:
    """End a reading as ``ended`` (with the failure's ``code`` from :data:`FAILURES`, or why it paused
    from :data:`INTERRUPTIONS`) and store it; ``False`` when it was not stored (see the module docstring)."""
    if ended == "done":
        tracer.finish(ended=ended)
    elif ended == "failed":
        tracer.finish(error=code if code in FAILURES else "unexpected", ended=ended, result="failed")
    else:
        tracer.finish(error=code if code in INTERRUPTIONS else ended, ended=ended)
    try:
        if store.get_document(tracer.doc_id) is None:
            return False
        store.save_trace(tracer.records(), keep=KEPT_READINGS, interrupted=INTERRUPTED)
    except Exception:
        log.warning("the trace of reading %s could not be stored", tracer.doc_id, exc_info=True)
        return False
    return True


def recover_readings(store: Store) -> int:
    """Startup: readings a previous process left ``running`` were stopped with it; returns how many."""
    try:
        return store.end_running_traces(ended="stopped", error="stopped")
    except Exception:
        log.warning("readings left running could not be marked stopped", exc_info=True)
        return 0
