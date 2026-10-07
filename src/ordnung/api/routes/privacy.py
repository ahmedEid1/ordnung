"""Privacy & AI usage: the activity log and the per-call accounting of model use (never bodies)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ordnung.api.deps import StoreDep
from ordnung.models import Activity, UsageStats

router = APIRouter(tags=["privacy"])


@router.get("/activity", response_model=list[Activity])
def activity(
    store: StoreDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    device: Annotated[
        str | None, Query(max_length=40, description="Only what this paired phone did (its id)")
    ] = None,
) -> list[Activity]:
    """What Ordnung did, newest first (``device``: what one paired phone did)."""
    return store.list_activity(limit=limit, data={"device": device} if device else None)


@router.get("/usage", response_model=UsageStats)
def usage(store: StoreDep) -> UsageStats:
    """Model calls: tokens, API-equivalent cost, cache hits, per purpose, and the latest calls."""
    return store.usage_stats()
