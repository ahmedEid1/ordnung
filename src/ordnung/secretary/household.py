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
   change of the list drops them. Filing letters meanwhile leaves them as they are.
8. **Letters:** a link to a letter in the trash is dormant and returns with it; deleting a letter for good
   removes its link in the same transaction (:meth:`ordnung.db.store.Store.delete_document`); the daily check
   removes links to letters that no longer exist (left by a computer still on 0.2.0); a letter just added
   starts unfiled, even when a link was left under its id (:meth:`ordnung.db.store.Store.add_document`).
9. **Never seen by Claude:** nothing here goes into a prompt, a draft request, Ask or a notification. Dates,
   reminders, numbers, Ask and Ideas keep treating every letter as the person's.

Storage: one ``meta`` row (:data:`ordnung.db.store.HOUSEHOLD_META_KEY`, :class:`StoredHousehold`), synced like
the profile; no migration; no people and nothing filed: no row. Changes publish ``profile.updated``.

Every change is read, checked and written in one :meth:`~ordnung.db.store.Store.tx` (``BEGIN IMMEDIATE``),
all or nothing; the same household again writes nothing. A change of the list names the version it was made
from (:func:`version`), so a tab that saw an older list can't drop a person silently. A row written by a newer
Ordnung (``format`` above :data:`FORMAT`) is read as far as it parses and never written over.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from typing import Protocol, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from ordnung.db.store import HOUSEHOLD_META_KEY, Store
from ordnung.ids import new_id
from ordnung.ingest.link import party_name
from ordnung.models import PROOF_SOURCE, Document
from ordnung.secretary.addressee import is_the_person, names_alone, names_others, same_name, shown_name

#: At most this many people in the household (the API's schema allows more; the policy says it in words).
MAX_PEOPLE = 12
#: A member's name, as typed, has at most this many characters (as a letter's ``sender_name``).
MAX_NAME_CHARS = 120
#: What a link says when the person answered "No, it's mine".
MINE = "me"
#: The format of the stored row this version writes (a newer one is read, never overwritten).
FORMAT = 1
#: A household person's id, as :func:`ordnung.ids.new_id` makes it.
_MEMBER_ID = re.compile(r"hhm_[0-9a-z]{12}")

# the words for the person (Settings, the letter's page): the API answers them as they are
TYPE_A_NAME = "Type a name."
TOO_LONG = f"Use at most {MAX_NAME_CHARS} characters."
NO_LETTERS = "Type a name with letters in it."
OWN_NAME = "That's your own name. Your household is the other people your letters come for."
ONE_AT_A_TIME = "Add one person at a time."
ALREADY_THERE = "{name} is already in your household."
TOO_MANY = f"Your household can have at most {MAX_PEOPLE} people."
CHANGED_ELSEWHERE = "Your household changed in another window. Look again, then try once more."
NEWER_VERSION = "Your household was saved by a newer version of Ordnung. Update Ordnung on this computer."
NOT_IN_HOUSEHOLD = "That person isn't in your household any more."
NO_LETTER = "This letter doesn't exist (any more)."
PROOF_FILE = "A proof file belongs to the letter it proves, not to a person."
ALSO_FILE_ALONE = "A letter can be filed only for the one person you add with it."


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


class MemberLike(Protocol):
    """A person as a change of the list sends them (``api.routes.household.MemberIn``): no id for a new one."""

    @property
    def id(self) -> str | None: ...
    @property
    def name(self) -> str: ...
    @property
    def signs(self) -> bool: ...


def version(members: Sequence[HouseholdMember]) -> str:
    """The list of people's version (a PUT's ``base``): 16 hex characters of the SHA-256 of their canonical
    JSON, so a tab that saw an older list can't drop a person silently."""
    canonical = json.dumps(
        [member.model_dump() for member in members], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------------------------------
# the stored row
# --------------------------------------------------------------------------------------------------


def parse(raw: str | None) -> StoredHousehold:
    """The household a ``household`` row holds, as far as it parses: an unreadable row is an empty household;
    a person or a link that isn't one is left out, and so are a newer Ordnung's own fields."""
    try:
        data = json.loads(raw) if raw is not None else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return StoredHousehold()
    found = data.get("format", FORMAT)
    stored_format = found if isinstance(found, int) and not isinstance(found, bool) and found >= 1 else FORMAT
    members: list[HouseholdMember] = []
    entries = data.get("members")
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        member_id, name, signs = entry.get("id"), entry.get("name"), entry.get("signs", True)
        if not (isinstance(member_id, str) and isinstance(name, str) and isinstance(signs, bool)):
            continue
        if member_id == MINE or any(member.id == member_id for member in members):
            continue
        members.append(HouseholdMember(id=member_id, name=name, signs=signs))
    raw_links = data.get("links")
    links = (
        {key: value for key, value in raw_links.items() if isinstance(value, str)}
        if isinstance(raw_links, dict)
        else {}
    )
    return StoredHousehold(format=stored_format, members=members, links=links)


def load(store: Store) -> StoredHousehold:
    """The stored household (:data:`~ordnung.db.store.HOUSEHOLD_META_KEY`; empty without a row)."""
    return parse(store.get_meta(HOUSEHOLD_META_KEY))


def _read(conn: sqlite3.Connection) -> StoredHousehold:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (HOUSEHOLD_META_KEY,)).fetchone()
    return parse(None if row is None else str(row["value"]))


def _write(conn: sqlite3.Connection, before: StoredHousehold, after: StoredHousehold) -> None:
    """Store ``after`` unless it is ``before`` (no person change, no new sync version); no people and
    nothing filed: no row."""
    if (after.members, after.links) == (before.members, before.links):
        return
    if not after.members and not after.links:
        conn.execute("DELETE FROM meta WHERE key = ?", (HOUSEHOLD_META_KEY,))
        return
    row = {
        "format": FORMAT,
        "members": [member.model_dump() for member in after.members],
        "links": after.links,
    }
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (HOUSEHOLD_META_KEY, json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False)),
    )


def _writable(stored: StoredHousehold) -> None:
    """A newer Ordnung's household is never written over (409)."""
    if stored.format > FORMAT:
        raise HouseholdError(409, NEWER_VERSION)


def _letters(conn: sqlite3.Connection, ids: Sequence[str]) -> dict[str, sqlite3.Row]:
    """The letters among ``ids`` that exist (in the trash too), by id: one JSON array, never one variable
    per id (SQLite's limit)."""
    return {
        row["id"]: row
        for row in conn.execute(
            "SELECT id, deleted_at, source FROM documents WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(list(ids)),),
        )
    }


def _without_gone(conn: sqlite3.Connection, links: Mapping[str, str]) -> dict[str, str]:
    """``links`` without the letters that no longer exist at all (the trash keeps its own)."""
    existing = _letters(conn, sorted(links))
    return {doc_id: link for doc_id, link in links.items() if doc_id in existing}


def _fileable(row: sqlite3.Row | None) -> None:
    """A letter may be filed: it exists outside the trash (404) and isn't a proof file (422)."""
    if row is None or row["deleted_at"] is not None:
        raise HouseholdError(404, NO_LETTER)
    if row["source"] == PROOF_SOURCE:
        raise HouseholdError(422, PROOF_FILE)


# --------------------------------------------------------------------------------------------------
# who a letter is for (points 2–4)
# --------------------------------------------------------------------------------------------------


def _matching(addressee: str, members: Sequence[HouseholdMember]) -> list[HouseholdMember]:
    """The people ``addressee`` (as read) could name alone (none for an addressee naming several)."""
    if names_others(addressee) or not same_name(addressee, addressee):  # several people, or no words
        return []
    return [member for member in members if names_alone(addressee, member.name)]


def member_for(addressee: str, members: Sequence[HouseholdMember]) -> HouseholdMember | None:
    """The one person of the household ``addressee`` (as read) names alone, by the rule the letter's page uses
    for the person themselves (:func:`ordnung.secretary.addressee.names_alone`): ``None`` when no one or
    several could be meant, or the addressee names several people ("Familie Rivera")."""
    matching = _matching(addressee, members)
    return matching[0] if len(matching) == 1 else None


def answer(doc_id: str, addressee: str | None, profile_name: str, stored: StoredHousehold) -> LetterFor:
    """Who one letter is for (points 2–4), from the household, the reading's addressee (``None``: none, or the
    letter isn't one received with a reading) and the profile's name. Pure: the letter's page, the household's
    suggestions and the shared vectors (``web/src/mocks/householdVectors.json``) use it."""
    members = {member.id: member for member in stored.members}
    link = stored.links.get(doc_id)
    if link is not None and link in members:
        return LetterFor(filed_for=members[link])
    if link == MINE:
        return LetterFor(mine=True)
    text = (addressee or "").strip()
    # the addressee isn't the person (addressed_to's rule), and a page would show it
    if not text or not profile_name.strip() or is_the_person(text, profile_name) or not shown_name(text):
        return LetterFor()
    matching = _matching(text, stored.members)
    if len(matching) == 1:
        return LetterFor(suggested=matching[0])
    if not matching and not names_others(text) and len(stored.members) < MAX_PEOPLE:
        return LetterFor(add=shown_name(text))
    return LetterFor()


def letter_for(store: Store, document: Document) -> LetterFor:
    """Who ``document`` is for (``LetterDetail.household``): all empty for a letter in the trash or a proof
    file."""
    if document.deleted_at is not None or document.source == PROOF_SOURCE:
        return LetterFor()
    stored = load(store)
    extraction = store.get_extraction(document.id) if document.direction == "incoming" else None
    addressee = extraction.recipient_name if extraction is not None else None
    return answer(document.id, addressee, store.get_profile().name, stored)


def view(store: Store) -> HouseholdView:
    """The household as ``GET /api/household`` answers it: its people with their letters, the letters filed
    for each and the person's own (outside the trash, never a proof file), and the suggestions. No people and
    no links: the empty answer, without reading any letter."""
    stored = load(store)
    if not stored.members and not stored.links:
        return {"members": [], "filed": {}, "mine": [], "suggested": {}, "version": version([])}
    with store.snapshot():
        names = store.recipient_names()
        profile_name = store.get_profile().name
    ids = {member.id for member in stored.members}
    filed = {doc_id: link for doc_id, link in stored.links.items() if doc_id in names and link in ids}
    mine = sorted(doc_id for doc_id, link in stored.links.items() if doc_id in names and link == MINE)
    suggested: dict[str, str] = {}
    if stored.members:
        unanswered = StoredHousehold(members=stored.members)
        # the same addressee names the same person on every letter (most name the person themselves)
        by_addressee: dict[str, HouseholdMember | None] = {}
        for doc_id, addressee in names.items():
            if not addressee or doc_id in filed or stored.links.get(doc_id) == MINE:
                continue
            if addressee not in by_addressee:
                by_addressee[addressee] = answer(doc_id, addressee, profile_name, unanswered).suggested
            found = by_addressee[addressee]
            if found is not None:
                suggested[doc_id] = found.id
    letters = {member.id: 0 for member in stored.members}
    for link in filed.values():
        letters[link] += 1
    return {
        "members": [
            {"id": member.id, "name": member.name, "signs": member.signs, "letters": letters[member.id]}
            for member in stored.members
        ],
        "filed": filed,
        "mine": mine,
        "suggested": suggested,
        "version": version(stored.members),
    }


# --------------------------------------------------------------------------------------------------
# the list of people (points 5–7)
# --------------------------------------------------------------------------------------------------


def clean_name(name: str, profile_name: str) -> str:
    """A name as it is kept (one line, no control or format characters), or :class:`HouseholdError` 422 with
    the reason it can't be one person of the household (point 5; :func:`check_members` checks the
    duplicates). Its length counts as typed, before it is cut to one line."""
    kept = party_name(name)
    if not kept:
        raise HouseholdError(422, TYPE_A_NAME)
    if len(" ".join(name.split())) > MAX_NAME_CHARS:
        raise HouseholdError(422, TOO_LONG)
    if not any(char.isalpha() for char in kept) or not same_name(kept, kept):  # titles alone are no name
        raise HouseholdError(422, NO_LETTERS)
    if names_others(kept):
        raise HouseholdError(422, ONE_AT_A_TIME)
    if profile_name.strip() and names_alone(kept, profile_name):
        raise HouseholdError(422, OWN_NAME)
    return kept


def check_members(
    members: Sequence[MemberLike], stored: StoredHousehold, profile_name: str
) -> list[HouseholdMember]:
    """The new list of people, checked (point 5). A new person gets an id; a name new or changed is checked,
    one kept as it was stays (even if the profile's name changed since); no two people have the same name,
    spelled otherwise; at most :data:`MAX_PEOPLE`. A person sent with an id keeps it — one still in the list,
    or one the last change removed and *Undo* puts back — and ids are household ids, each once."""
    if len(members) > MAX_PEOPLE:
        raise HouseholdError(422, TOO_MANY)
    before = {member.id: member for member in stored.members}
    seen: set[str] = set()
    names: list[tuple[str, bool]] = []  # each person's name as kept, and whether it is new or changed
    for member in members:
        if member.id is not None:
            if not _MEMBER_ID.fullmatch(member.id) or member.id in seen:
                raise HouseholdError(422, NOT_IN_HOUSEHOLD)
            seen.add(member.id)
        kept = before.get(member.id) if member.id is not None else None
        if kept is not None and party_name(member.name) == kept.name:
            names.append((kept.name, False))
        else:
            names.append((clean_name(member.name, profile_name), True))
    for index, (name, fresh) in enumerate(names):
        others = (other for at, (other, _) in enumerate(names) if at != index)
        if fresh and (same := next((other for other in others if same_name(name, other)), None)):
            raise HouseholdError(422, ALREADY_THERE.format(name=same))
    return [
        HouseholdMember(id=member.id or new_id("hhm"), name=name, signs=member.signs)
        for member, (name, _) in zip(members, names, strict=True)
    ]


def change(
    store: Store, *, base: str, members: Sequence[MemberLike], also_file: Sequence[str] = ()
) -> HouseholdView:
    """``PUT /api/household``: replace the list of people, from the version ``base`` the page saw (409 when
    the list changed since). A kept id keeps its letters; a person left out leaves their letters dormant until
    the next change of the list (point 7); ``also_file`` files those letters for the one new person, at once.
    One transaction: :class:`HouseholdError` says why a change is refused, and nothing of it is kept."""
    profile_name = store.get_profile().name
    with store.tx() as conn:
        stored = _read(conn)
        _writable(stored)
        if base != version(stored.members):
            raise HouseholdError(409, CHANGED_ELSEWHERE)
        checked = check_members(members, stored, profile_name)
        added = [person.id for person, sent in zip(checked, members, strict=True) if sent.id is None]
        # a person removed now keeps their links one change longer (Undo); one removed before loses them
        known = {member.id for member in stored.members} | {member.id for member in checked}
        links = _without_gone(
            conn, {doc_id: link for doc_id, link in stored.links.items() if link == MINE or link in known}
        )
        if also_file:
            if len(added) != 1:
                raise HouseholdError(422, ALSO_FILE_ALONE)
            found = _letters(conn, also_file)
            for doc_id in also_file:
                _fileable(found.get(doc_id))
                links[doc_id] = added[0]
        _write(conn, stored, StoredHousehold(members=checked, links=links))
    return view(store)


# --------------------------------------------------------------------------------------------------
# filing letters (point 1) and the letters gone (point 8)
# --------------------------------------------------------------------------------------------------


def file(store: Store, letters: Mapping[str, str | None]) -> HouseholdView:
    """``PATCH /api/household``: who each letter is for — a person's id, :data:`MINE`, or ``None`` (not
    answered: the Undo of a first answer). Only a press files (point 1). The letters exist outside the trash
    and aren't proof files; the people are in the household. One transaction, all or nothing; the same
    answers again write nothing."""
    with store.tx() as conn:
        stored = _read(conn)
        _writable(stored)
        ids = {member.id for member in stored.members}
        found = _letters(conn, list(letters))
        links = dict(stored.links)
        for doc_id, link in letters.items():
            _fileable(found.get(doc_id))
            if link is not None and link != MINE and link not in ids:
                raise HouseholdError(422, NOT_IN_HOUSEHOLD)
            if link is None:
                links.pop(doc_id, None)
            else:
                links[doc_id] = link
        _write(conn, stored, StoredHousehold(members=stored.members, links=_without_gone(conn, links)))
    return view(store)


def prune_gone(store: Store) -> int:
    """The daily check (point 8): forget the links of letters that no longer exist at all — deleted for good
    on a computer still on 0.2.0, which leaves the row as it was. Writes only when there is one; a newer
    Ordnung's row is left alone. Returns how many were forgotten."""
    with store.tx() as conn:
        stored = _read(conn)
        if stored.format > FORMAT or not stored.links:
            return 0
        links = _without_gone(conn, stored.links)
        _write(conn, stored, stored.model_copy(update={"links": links}))
    return len(stored.links) - len(links)
