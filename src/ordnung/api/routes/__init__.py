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
    items,
    overview,
    parties,
    privacy,
    profile,
    proofs,
    suggestions,
    system,
    waiting,
)

ROUTERS: tuple[APIRouter, ...] = (
    system.router,
    profile.router,
    data.router,
    privacy.router,
    documents.router,
    items.router,
    contracts.router,
    parties.router,
    cases.router,
    overview.router,
    suggestions.router,
    brief.router,
    ask.router,
    drafts.router,
    proofs.router,
    waiting.router,
    calendar.router,
    events.router,
    demo.router,
)
