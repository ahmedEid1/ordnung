"""How a letter was read: its traces (:mod:`ordnung.trace`).

``GET /api/documents/{doc_id}/trace`` returns one reading (``?run=<trace id>``; default the newest kept)
with its steps and the list of kept readings; ``…/trace/compare`` what a later reading decided
differently (``head`` default: the newest; ``base`` default: the newest earlier reading that was done —
a paused or stopped attempt, or a failed one, only when there is no such reading);
``GET /api/traces`` every kept reading as stored, for "Download your records". All side-effect free.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from ordnung.api.deps import StoreDep
from ordnung.api.routes.common import require
from ordnung.db.store import Store
from ordnung.models import DocumentTrace, TraceComparison, TraceExport
from ordnung.trace.compare import compare_base, compare_traces
from ordnung.trace.view import TraceNotFound, document_trace

router = APIRouter(tags=["traces"])

NOT_FOUND = "This letter doesn't exist (any more)."
READING_GONE = "That reading of the letter isn't kept any more — Ordnung keeps the last five."
NOTHING_TO_COMPARE = "There is nothing to compare yet: this letter has been read only once."

RunQuery = Annotated[
    str | None, Query(max_length=40, pattern=r"^trc_[0-9a-f]{1,32}$", description="A reading's trace id")
]


def _trace(store: Store, doc_id: str, trace_id: str | None) -> DocumentTrace:
    require(store.get_document(doc_id), NOT_FOUND)
    try:
        return document_trace(store, doc_id, trace_id)
    except TraceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, READING_GONE) from None


@router.get("/documents/{doc_id}/trace", response_model=DocumentTrace)
def get_trace(doc_id: str, store: StoreDep, run: RunQuery = None) -> DocumentTrace:
    """How the letter was read: every step of one reading, with its model calls, and the kept readings."""
    return _trace(store, doc_id, run)


@router.get(
    "/documents/{doc_id}/trace/compare",
    response_model=TraceComparison,
    responses={404: {"description": "No such letter or reading, or only one reading is kept."}},
)
def compare_trace(
    doc_id: str, store: StoreDep, base: RunQuery = None, head: RunQuery = None
) -> TraceComparison:
    """What a later reading of the letter decided differently from an earlier one."""
    later = _trace(store, doc_id, head)
    if later.run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOTHING_TO_COMPARE)
    if base is None:
        older = compare_base(later.runs, later.run)
        if older is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, NOTHING_TO_COMPARE)
        base = older.trace_id
    return compare_traces(_trace(store, doc_id, base), later)


@router.get("/traces", response_model=TraceExport)
def export_traces(store: StoreDep) -> TraceExport:
    """Every kept reading of the letters not in the trash, as stored (no letter text)."""
    spans, calls = store.export_traces()
    return TraceExport(spans=spans, calls=calls)
