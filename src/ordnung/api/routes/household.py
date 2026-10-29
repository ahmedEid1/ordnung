"""Your household: the people whose letters come to the person too, and which letters are filed for them
(policy: :mod:`ordnung.secretary.household`, ADR 0023).

``GET /api/household`` answers the list with each person's letters, the letters filed for each, the ones the
person said are theirs and the suggestions. ``PUT`` replaces the list of people (computer only, like the
profile); ``PATCH`` files letters (the phone too, logged "Changed who a letter is for"). Both are person
changes: they publish ``profile.updated`` and refresh the Ideas, whose titles say whose a letter is (the policy's
points 9 and 10). The routes give Claude nothing themselves.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import CtxDep, StoreDep, require_computer
from ordnung.secretary import household
from ordnung.secretary.household import HouseholdError, HouseholdMember, HouseholdView

router = APIRouter(tags=["household"])


class HouseholdPerson(HouseholdMember):
    """A person of the household with the number of letters filed for them."""

    letters: int = Field(description="Letters filed for them, outside the trash")


class Household(BaseModel):
    """``GET``, ``PUT`` and ``PATCH /api/household``: the people and who each letter is for."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    members: list[HouseholdPerson] = Field(default_factory=list)
    filed: dict[str, str] = Field(default_factory=dict, description="Letter id → the person it is filed for")
    mine: list[str] = Field(default_factory=list, description="Letters the person said are theirs (sorted)")
    suggested: dict[str, str] = Field(
        default_factory=dict, description="Unanswered letter id → the one person its addressee names"
    )
    version: str = Field(description="The list of people's version: a PUT's base")


class MemberIn(BaseModel):
    """A person as a ``PUT`` sends them: a new one has no id."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str = Field(max_length=1000)
    signs: bool = True


class HouseholdChange(BaseModel):
    """``PUT /api/household``: the whole list of people, from the version the page saw (``base``)."""

    model_config = ConfigDict(extra="forbid")

    base: str
    members: list[MemberIn] = Field(max_length=50)
    also_file: list[str] = Field(
        default_factory=list, max_length=1, description="Letters to file for the one new person, at once"
    )


class HouseholdFiling(BaseModel):
    """``PATCH /api/household``: who each letter is for — a person's id, ``"me"``, or ``null`` (not
    answered)."""

    model_config = ConfigDict(extra="forbid")

    letters: dict[str, str | None] = Field(min_length=1, max_length=1000)


@router.get("/household", response_model=Household)
def get_household(store: StoreDep) -> Household:
    """The household: its people, the letters filed for each, the ones that are the person's and the
    suggestions."""
    return Household.model_validate(household.view(store))


async def _written(ctx: CtxDep, write: Callable[[], HouseholdView]) -> Household:
    """Run a household change in a worker thread (one transaction), answer the household after it and
    announce it as ``profile.updated`` (no event of its own: the events are in ``models.py``), then refresh the
    Ideas in the background so their titles follow whose a letter is at once (they publish
    ``suggestions.updated``). A refusal is the policy's status and words; nothing is announced then."""
    try:
        answer = await asyncio.to_thread(write)
    except HouseholdError as refused:
        raise HTTPException(refused.status, refused.detail) from None
    ctx.bus.publish("profile.updated")
    ctx.worker.refresh_ideas()
    return Household.model_validate(answer)


@router.put("/household", response_model=Household, dependencies=[Depends(require_computer)])
async def save_household(change: HouseholdChange, ctx: CtxDep) -> Household:
    """Replace the list of people (kept ids keep their letters; ``id: null`` adds a person)."""
    # from the version the page saw (409 when it changed since); ``also_file`` files a letter for the one new
    # person at once; 422 with the reason for a name that can't be one person of the household
    return await _written(
        ctx,
        lambda: household.change(
            ctx.store, base=change.base, members=change.members, also_file=change.also_file
        ),
    )


@router.patch("/household", response_model=Household)
async def file_letters(filing: HouseholdFiling, ctx: CtxDep) -> Household:
    """File letters for a person, as the person's own, or forget the answer."""
    # 404 for a letter that doesn't exist or is in the trash, 422 for a proof file or someone not in the household
    return await _written(ctx, lambda: household.file(ctx.store, filing.letters))
