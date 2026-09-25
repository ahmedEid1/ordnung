"""Threads (cases): one thread with its letters in order, to-dos and drafts."""

from __future__ import annotations

from fastapi import APIRouter

from ordnung.api.deps import StoreDep
from ordnung.api.routes.common import require
from ordnung.models import CaseDetail, Document

router = APIRouter(tags=["cases"])


def _thread_order(document: Document) -> tuple[str, str, str]:
    return (
        document.doc_date or document.received_date or document.created_at[:10],
        document.created_at,
        document.id,
    )


@router.get("/cases/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, store: StoreDep) -> CaseDetail:
    """A thread: its party, letters (oldest first, like a conversation), to-dos and drafts."""
    case = require(store.get_case(case_id), "Unknown thread.")
    return CaseDetail(
        case=case,
        party=store.get_party(case.party_id) if case.party_id else None,
        documents=sorted(store.list_documents(case_id=case_id), key=_thread_order),
        items=store.list_items(case_id=case_id),
        drafts=store.list_drafts(case_id=case_id),
    )
