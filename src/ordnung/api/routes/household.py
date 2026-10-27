"""Your household: the people whose letters come to the person too, and which letters are filed for them
(policy: :mod:`ordnung.secretary.household`, ADR 0023).

``GET /api/household`` answers the list with each person's letters, the letters filed for each, the ones the
person said are theirs and the suggestions. ``PUT`` replaces the list of people (computer only, like the
profile); ``PATCH`` files letters (the phone too, logged "Changed who a letter is for"). Both are person
changes and publish ``profile.updated``. Nothing here is ever given to Claude.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import StoreDep, require_computer
from ordnung.secretary import household
from ordnung.secretary.household import HouseholdMember

router = APIRouter(tags=["household"])

NOT_BUILT = "Your household isn't built yet."


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


@router.put("/household", response_model=Household, dependencies=[Depends(require_computer)])
async def save_household(change: HouseholdChange) -> Household:
    """Replace the list of people (kept ids keep their letters; ``id: null`` adds a person)."""
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_BUILT)


@router.patch("/household", response_model=Household)
async def file_letters(filing: HouseholdFiling) -> Household:
    """File letters for a person, as the person's own, or forget the answer."""
    raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, NOT_BUILT)
