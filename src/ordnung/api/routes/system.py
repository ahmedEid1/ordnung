"""System status: health (with the zero-token Claude check), the rules catalog and the job queue.

``GET /api/health`` answers from the cached Claude status (refreshed at most every 10 minutes,
zero tokens). ``?probe=1`` is Settings' "Run check": every ``ordnung doctor`` check plus one tiny
live call to Claude — allowed once a minute (``429`` with ``Retry-After`` otherwise). Backends that
never run the ``claude`` CLI (the recorded demo, the test fake) get the local checks only.

A paired phone gets ``client: "phone"`` and no data folder, Claude path or checks (its gate refuses
``probe``, and answers before sign-in with 401, never this route's minimal answer).
"""

from __future__ import annotations

import asyncio
import os
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from ordnung import __version__
from ordnung.api.deps import ApiState, StateDep, StoreDep, backend_uses_cli, is_phone
from ordnung.api.security import request_authenticated
from ordnung.doctor import DoctorReport, local_checks
from ordnung.models import DoctorCheck, Health, Job, RuleInfo
from ordnung.rules import LAST_CHECKED, list_rules
from ordnung.tick import local_today, simulated_day

router = APIRouter(tags=["system"])


class PublicHealth(BaseModel):
    """What ``GET /api/health`` tells a caller that has not signed in with the session token."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    version: str
    authenticated: bool = False


async def _probe(state: ApiState, uses_cli: bool) -> list[DoctorCheck]:
    """Run the doctor for "Run check" (rate-limited) and remember the fresh Claude status."""
    wait = state.probe_limit.acquire()
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"The check just ran. Please try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )
    data_dir = state.ctx.paths.data_dir
    if not uses_cli:
        return DoctorReport(checks=await asyncio.to_thread(local_checks, data_dir)).checks
    # on the model every call runs on, so a name Claude Code refuses shows up here, next to the field
    report = await state.doctor(data_dir, probe=True, model=state.ctx.settings.model)
    state.claude.remember(report.claude)
    return report.checks


@router.get(
    "/health",
    response_model=Health | PublicHealth,
    responses={429: {"description": "“Run check” ran less than a minute ago (see ``Retry-After``)."}},
)
async def health(
    request: Request,
    state: StateDep,
    probe: Annotated[
        bool, Query(description="“Run check”: all doctor checks plus one tiny live call (once a minute)")
    ] = False,
) -> Health | PublicHealth:
    """Version, data folder, demo mode, the app's today, backend, Claude status (cached 10 min), the
    model ``ORDNUNG_CLAUDE_MODEL`` pins (if set) and the rules catalog's "law as of" date; with
    ``probe`` also the doctor's checks."""
    if not request_authenticated(request):
        return PublicHealth(version=__version__)
    ctx = state.ctx
    store = ctx.store
    phone = is_phone(request)
    uses_cli = backend_uses_cli(ctx)
    checks = await _probe(state, uses_cli) if probe and not phone else []
    pinned = simulated_day(store)
    claude = await state.claude.get(ctx.backend_name, uses_cli=uses_cli)
    return Health(
        version=__version__,
        data_dir="" if phone else str(ctx.paths.data_dir),
        demo=state.demo or ctx.settings.demo,
        simulated_today=pinned.isoformat() if pinned else None,
        today=local_today(store).isoformat(),
        backend=ctx.backend_name,
        claude=claude.model_copy(update={"path": None}) if phone else claude,
        model_pinned=os.environ.get("ORDNUNG_CLAUDE_MODEL") or None,
        rules_last_checked=LAST_CHECKED,
        checks=checks,
        client="phone" if phone else "computer",
    )


@router.get("/rules", response_model=list[RuleInfo])
def rules() -> list[RuleInfo]:
    """The legal rules the date engine uses ("How dates are computed"), with citations. The day they
    were last checked against the law is ``rules_last_checked`` of ``GET /api/health``."""
    return list_rules()


@router.get("/jobs", response_model=list[Job])
def jobs(
    store: StoreDep,
    active_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[Job]:
    """Reading jobs, newest first (``active_only``: queued, running and waiting ones)."""
    return store.list_jobs(active_only=active_only, limit=limit)
