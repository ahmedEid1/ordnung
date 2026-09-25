"""Ideas: the list, the person's answer to one (accept, dismiss, snooze, done, undo) and an on-demand
review. The review runs in the background (``202 Accepted``); its Ideas arrive with the
``suggestions.updated`` event, a failure with ``review.failed``."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from ordnung.api.deps import StateDep, StoreDep, TodayDep
from ordnung.api.routes.common import IsoDate, require
from ordnung.app_context import AppContext
from ordnung.db.store import Store
from ordnung.llm.base import LLMError
from ordnung.models import Suggestion, SuggestionStatus
from ordnung.secretary.review import run_review
from ordnung.tick import replay_miss_prone

log = logging.getLogger(__name__)

router = APIRouter(tags=["suggestions"])

REVIEW_TASK = "review"
DEFAULT_SNOOZE_DAYS = 7
VISIBLE_STATUSES: tuple[SuggestionStatus, ...] = ("new", "accepted", "dismissed", "snoozed", "done")
PersonStatus = Literal["new", "accepted", "dismissed", "snoozed", "done"]


class SuggestionPatch(BaseModel):
    """The person's answer to an Idea (``new`` undoes an earlier answer)."""

    model_config = ConfigDict(extra="forbid")

    status: PersonStatus | None = None
    snoozed_until: IsoDate | None = None


class ReviewStarted(BaseModel):
    """``POST /api/suggestions/review``: whether a review was started or one is already running."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    started: bool
    running: bool = True


@router.get("/suggestions", response_model=list[Suggestion])
def list_suggestions(
    store: StoreDep,
    status_: Annotated[SuggestionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
) -> list[Suggestion]:
    """Ideas by priority (expired ones only when asked for with ``status=expired``)."""
    return store.list_suggestions(status=status_ or VISIBLE_STATUSES, limit=limit)


def _answer(store: Store, suggestion_id: str, patch: SuggestionPatch, today: date) -> Suggestion:
    idea = require(store.get_suggestion(suggestion_id), "Unknown Idea.")
    changes = patch.model_dump(exclude_unset=True)
    wanted = changes.get("status") or ("snoozed" if changes.get("snoozed_until") else None)
    if wanted is None:
        return idea
    until = None
    if wanted == "snoozed":
        until = changes.get("snoozed_until") or (today + timedelta(days=DEFAULT_SNOOZE_DAYS)).isoformat()
    with store.tx():
        updated = store.update_suggestion(suggestion_id, status=wanted, snoozed_until=until)
        store.log_activity(
            "suggestion.answered",
            f"Idea “{idea.title}”: {wanted}",
            ref_type="suggestion",
            ref_id=suggestion_id,
            data={"status": wanted, "snoozed_until": until},
        )
    return updated


@router.patch("/suggestions/{suggestion_id}", response_model=Suggestion)
async def update_suggestion(
    suggestion_id: str, patch: SuggestionPatch, state: StateDep, today: TodayDep
) -> Suggestion:
    """Accept, dismiss ("Not relevant"), snooze ("Remind me in a week"), mark done — or undo."""
    idea = await asyncio.to_thread(_answer, state.ctx.store, suggestion_id, patch, today)
    state.ctx.bus.publish("suggestions.updated", reason="answered", suggestion_id=suggestion_id)
    return idea


async def _review(ctx: AppContext, today: date) -> None:
    try:
        ideas = await run_review(ctx.store, ctx.llm, today, settings=ctx.settings)
    except LLMError as exc:
        log.warning("review failed: %s", exc)
        ctx.bus.publish("review.failed", error=str(exc))
        return
    ctx.bus.publish("suggestions.updated", reason="review", created=len(ideas))


@router.post("/suggestions/review", response_model=ReviewStarted, status_code=status.HTTP_202_ACCEPTED)
async def start_review(state: StateDep, today: TodayDep) -> ReviewStarted:
    """Ask Claude to look over the ledger for new Ideas (in the background)."""
    ctx = state.ctx
    if replay_miss_prone(ctx.llm):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The demo uses recorded answers, so a new review isn't available here.",
        )
    started = state.background.start(REVIEW_TASK, _review(ctx, today))
    return ReviewStarted(started=started)
