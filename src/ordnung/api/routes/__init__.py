"""HTTP routes, one module per resource (SPEC §13). :data:`ROUTERS` are mounted under ``/api``."""

from __future__ import annotations

from fastapi import APIRouter

from ordnung.api.routes import (
    ask,
    brief,
    calendar,
    cases,
    contracts,
    data,
    demo,
    documents,
    drafts,
    events,
    folder,
    items,
    overview,
    parties,
    privacy,
    profile,
    suggestions,
    system,
)

ROUTERS: tuple[APIRouter, ...] = (
    system.router,
    profile.router,
    data.router,
    privacy.router,
    documents.router,
    folder.router,
    items.router,
    contracts.router,
    parties.router,
    cases.router,
    overview.router,
    suggestions.router,
    brief.router,
    ask.router,
    drafts.router,
    calendar.router,
    events.router,
    demo.router,
)
