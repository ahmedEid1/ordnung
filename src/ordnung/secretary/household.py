"""Who the person's letters are for: their household (module policy, ADR 0007; ADR 0023).

The person lists the people whose letters come to them too — a partner, their children — in Settings. Ordnung
then asks, for a letter addressed to one of them, whether it is for that person, and files it only when the
person says so.

1. **Suggest, never file.** A letter is filed for someone only by the person's press (``PUT /api/household``
   with ``also_file``, ``PATCH /api/household``). Readings, the daily check, sync and the phone file nothing.
2. **Who a letter could be for** is worked out only for a letter whose addressee isn't the person
   (:func:`ordnung.secretary.addressee.addressed_to`): the addressee's name is compared with each member's by
   the same rule as the person's own. Exactly one member who matches is suggested; none, or several, or an
   addressee naming several people ("Familie Rivera") give no suggestion.
3. **An answered letter** (filed for a member, or "mine") is never suggested again. A link to a removed
   member counts as unanswered.
4. **Add … to your household** is offered for an unanswered letter whose addressee names one person no
   member could be, while the household has fewer than :data:`MAX_PEOPLE` people.
5. **The list:** names as typed, on one line of at most :data:`MAX_NAME_CHARS` characters, with a letter in
   them; never the person's own name, several people in one, or a name already there (spelled otherwise).
   At most :data:`MAX_PEOPLE` people.
6. **A rename keeps the id**, so filed letters stay filed.
7. **A removal leaves the person's links dormant**: *Undo* (the same id) brings them back; any other next
   change drops them.
8. **Letters:** a link to a letter in the trash is dormant and returns with it; deleting a letter for good
   removes its link in the same transaction (:meth:`ordnung.db.store.Store.delete_document`); the daily check
   removes links to letters that no longer exist (left by a computer still on 0.2.0).
9. **Never seen by Claude:** nothing here goes into a prompt, a draft request, Ask or a notification. Dates,
   reminders, numbers, Ask and Ideas keep treating every letter as the person's.

Storage: one ``meta`` row (:data:`ordnung.db.store.HOUSEHOLD_META_KEY`, :class:`StoredHousehold`), synced like
the profile; no migration. Changes publish ``profile.updated``.

Built in two steps: the shapes and the empty answers here come first (d3-contract); :func:`load`,
:func:`view` and :func:`letter_for` answer an empty household until the policy is filled in
(d3-household-core).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import TypedDict

from pydantic import BaseModel, ConfigDict, Field

from ordnung.db.store import Store
from ordnung.models import Document

#: At most this many people in the household (the API's schema allows more; the policy says it in words).
MAX_PEOPLE = 12
#: A member's name, as typed, has at most this many characters (as a letter's ``sender_name``).
MAX_NAME_CHARS = 120
#: What a link says when the person answered "No, it's mine".
MINE = "me"
#: The format of the stored row this version writes (a newer one is read, never overwritten).
FORMAT = 1


class HouseholdMember(BaseModel):
    """A person of the household, as the person typed them in."""

    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)

    id: str = Field(description="hhm_…, kept across renames")
    name: str = Field(description="As typed in Settings, on one line")
    signs: bool = Field(default=True, description="Replies to their letters may go out in their name")


class StoredHousehold(BaseModel):
    """The ``household`` row of ``meta``: never an API body."""

    format: int = FORMAT
    members: list[HouseholdMember] = Field(default_factory=list)
    #: letter id → member id, or :data:`MINE`
    links: dict[str, str] = Field(default_factory=dict)


class LetterFor(BaseModel):
    """Who one letter is for, worked out on read for its page (all empty without a household)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    filed_for: HouseholdMember | None = Field(default=None, description="Filed for this person")
    mine: bool = Field(default=False, description="The person said the letter is theirs")
    suggested: HouseholdMember | None = Field(
        default=None, description="Not answered yet: the one person its addressee names"
    )
    add: str | None = Field(
        default=None, description="Not answered yet: the addressee to offer to add to the household"
    )


class PersonView(TypedDict):
    """A member with the number of letters filed for them (``api.routes.household.HouseholdPerson``)."""

    id: str
    name: str
    signs: bool
    letters: int


class HouseholdView(TypedDict):
    """What ``GET /api/household`` answers (``api.routes.household.Household``)."""

    members: list[PersonView]
    #: letter outside the trash → the member it is filed for
    filed: dict[str, str]
    #: letters outside the trash the person said are theirs, sorted
    mine: list[str]
    #: unanswered letters outside the trash → the one member their addressee names
    suggested: dict[str, str]
    version: str


class HouseholdError(Exception):
    """A household change refused: the HTTP status and the words for the person."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def version(members: Sequence[HouseholdMember]) -> str:
    """The list of people's version (a PUT's ``base``): 16 hex characters of the SHA-256 of their canonical
    JSON, so a tab that saw an older list can't drop a person silently."""
    canonical = json.dumps(
        [member.model_dump() for member in members], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def load(store: Store) -> StoredHousehold:
    """The stored household (empty until d3-household-core reads the row)."""
    return StoredHousehold()


def view(store: Store) -> HouseholdView:
    """The household as ``GET /api/household`` answers it. No people and no links: the empty answer, without
    reading any letter."""
    stored = load(store)
    return {"members": [], "filed": {}, "mine": [], "suggested": {}, "version": version(stored.members)}


def letter_for(store: Store, document: Document) -> LetterFor:
    """Who ``document`` is for (``LetterDetail.household``): empty until d3-household-core fills it."""
    return LetterFor()
