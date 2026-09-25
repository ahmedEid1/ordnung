"""Privacy & AI usage: the activity log and the per-call accounting of model use (never bodies)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ordnung.api.deps import StoreDep
from ordnung.models import Activity, UsageStats

router = APIRouter(tags=["privacy"])


@router.get("/activity", response_model=list[Activity])
def activity(store: StoreDep, limit: Annotated[int, Query(ge=1, le=1000)] = 100) -> list[Activity]:
    """What Ordnung did, newest first."""
    return store.list_activity(limit=limit)


@router.get("/usage", response_model=UsageStats)
def usage(store: StoreDep) -> UsageStats:
    """Model calls: tokens, API-equivalent cost, cache hits, per purpose, and the latest calls."""
    return store.usage_stats()
