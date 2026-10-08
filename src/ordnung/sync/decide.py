"""The decision function (design §9, with the review's blockers 2-4 and findings 13, 31): pure — what this
computer should do, from what it knows of itself (:class:`LocalView`) and what the folder shows
(:class:`~ordnung.sync.scan.FolderView`). The engine and the CLI only execute what it returns.

``L`` is this computer's lineage: its base's, plus an unknown own person change when changes are
pending (so only ``behind`` and ``diverged`` are possible then). ``others`` are the other computers'
heads with a version — those that *left* too (blocker 2: their last version still counts, they only
leave the election of the computer in use), never forgotten ones. A head of a newer Ordnung is never
pulled from or claimed toward; pushing goes on (finding 13).

**In use, periodically:** R1 a folder problem pauses (work goes on here); R3 another computer is in
use → stand by (pushing late when changes are pending); R4 a head diverged or decided against this
one → a choice (a banner; work goes on); R5 a head ahead and nothing pending → bring it in quietly
when it has arrived; R6 changes → push; R7 idle.

**Standing by, periodically:** no pulls; what "Use Ordnung here" would do is reported (up to date,
arriving, a choice), and the holder's version is acknowledged in ``has`` once it fully arrived.

**Use Ordnung here:** U0 already in use; U1 changes pending → push them first; U2 every other is
behind or the same → pull a same-content version whose background work differs, else claim at the
local base; U3 one head ahead of this one and of every other → pull it; U4 one head decided against
this one and covers every other → keep a copy, pull it; U5 otherwise → a choice. Joining (no base):
with letters of its own, a choice — unless a version in the folder holds exactly this computer's data (it
joins again after leaving): then, as without letters, pull the newest (a choice when the others diverge,
finding 31).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from ordnung.sync import lineage as lin
from ordnung.sync.model import Lineage, VersionId, VersionRef
from ordnung.sync.scan import FolderView, HeadView, Problem


@dataclass(frozen=True)
class LocalView:
    """What this computer knows of itself."""

    computer: str
    mode: Literal["in_use", "standing_by"]
    base: VersionRef | None
    #: person changes not yet in a pushed version (the counter moved, or its row is missing)
    pending: bool
    #: this computer's next person number (the unknown own change when ``pending``)
    next_pnum: int
    #: the current state digest (``None``: not computed)
    digest: str | None = None
    #: the person's own records exist here (joining asks first then)
    has_person_data: bool = False
    #: this computer's small number in choices (``choose`` takes it)
    key: int = 0
    #: versions this computer's data equalled lately (their keys): never "news" again
    recent: frozenset[str] = frozenset()

    @property
    def lineage(self) -> Lineage:
        base = self.base.lineage if self.base is not None else Lineage()
        return lin.bump(base, self.computer, self.next_pnum) if self.pending else base


# --------------------------------------------------------------------------------------------------
# decisions
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Side:
    """One computer's Ordnung in a choice (``head`` None: this computer)."""

    key: int
    computer: str
    this: bool
    head: HeadView | None

    @property
    def complete(self) -> bool:
        return self.this or (self.head is not None and self.head.complete)


@dataclass(frozen=True)
class Paused:
    problem: Problem


@dataclass(frozen=True)
class BecomeStandby:
    late_push: bool


@dataclass(frozen=True)
class Choice:
    sides: tuple[Side, ...]
    joining: bool = False


@dataclass(frozen=True)
class BringIn:
    target: HeadView


@dataclass(frozen=True)
class Arriving:
    target: HeadView


@dataclass(frozen=True)
class Push:
    pass


@dataclass(frozen=True)
class Idle:
    pass


@dataclass(frozen=True)
class Standby:
    """Standing by: what "Use Ordnung here" would find."""

    up_to_date: bool
    arriving: HeadView | None = None
    choice: Choice | None = None
    #: the holder's version, fully arrived and verified here (``Head.has``)
    has: VersionId | None = None
    late_push: bool = False
    #: what would stop "Use Ordnung here" (a newer Ordnung in use)
    problem: Problem | None = None


@dataclass(frozen=True)
class AlreadyInUse:
    pass


@dataclass(frozen=True)
class LatePush:
    pass


@dataclass(frozen=True)
class Pull:
    target: HeadView
    keep: bool


@dataclass(frozen=True)
class Claim:
    """Claim at the local base: nothing to bring over."""


@dataclass(frozen=True)
class Wait:
    target: HeadView
    choose: bool = False


@dataclass(frozen=True)
class ChooseThis:
    others: tuple[Lineage, ...]


@dataclass(frozen=True)
class ChooseOther:
    target: HeadView
    others: tuple[Lineage, ...]


@dataclass(frozen=True)
class NoChoice:
    pass


@dataclass(frozen=True)
class NotYet:
    """Joining a folder whose computers haven't arrived yet (only its key file has): wait."""


Decision = (
    Paused
    | BecomeStandby
    | Choice
    | BringIn
    | Arriving
    | Push
    | Idle
    | Standby
    | AlreadyInUse
    | LatePush
    | Pull
    | Claim
    | Wait
    | ChooseThis
    | ChooseOther
    | NoChoice
    | NotYet
)


@dataclass(frozen=True)
class Action:
    """What the person asked: ``use_here`` (``older_copy``), or ``choose`` a side by ``key``."""

    kind: Literal["use_here", "choose"]
    older_copy: bool = False
    key: int | None = None


#: Problems that stop pulling and claiming (writing locally goes on).
BLOCKING = frozenset(
    {
        "folder_missing",
        "folder_empty",
        "folder_other",
        "folder_unreachable",
        "two_setups",
        "copied_folder",
        "forgotten",
        "pull_unfinished",
        "local_rollback",
        "passphrase_needed",
        "keyring_locked",
        "keyring_unavailable",
    }
)


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------


def _versioned(view: FolderView) -> list[HeadView]:
    return [h for h in view.others if h.head.version is not None and not h.newer]


def _relation(local: Lineage, head: HeadView) -> lin.Relation:
    assert head.head.version is not None
    return lin.relation(local, head.head.version.lineage)


def _rank(head: HeadView) -> tuple[int, str]:
    return (head.head.epoch, head.computer)


def _covers_all(candidate: HeadView, heads: Sequence[HeadView]) -> bool:
    """``candidate``'s version accounts for every other head's (each is behind it or the same)."""
    assert candidate.head.version is not None
    mine = candidate.head.version.lineage
    return all(
        _relation(mine, other) in ("same", "behind")
        for other in heads
        if other.computer != candidate.computer
    )


def _maximal(heads: Sequence[HeadView]) -> list[HeadView]:
    """One head per distinct content that no other head accounts for (highest ``(epoch, id)`` first)."""
    out: list[HeadView] = []
    for head in sorted(heads, key=_rank, reverse=True):
        assert head.head.version is not None
        mine = head.head.version.lineage
        dominated = False
        for other in heads:
            if other.computer == head.computer:
                continue
            assert other.head.version is not None
            rel = lin.relation(mine, other.head.version.lineage)
            if rel in ("ahead", "decided"):
                dominated = True
                break
        if dominated or any(lin.same(mine, kept.head.version.lineage) for kept in out if kept.head.version):
            continue
        out.append(head)
    return out


def _choice(local: LocalView, heads: Sequence[HeadView], *, joining: bool = False) -> Choice:
    """Every maximal head, and this computer when no other head contains its content."""
    mine = local.lineage
    sides: list[Side] = []
    contained = (
        any(h.head.version is not None and lin.contains(h.head.version.lineage, mine) for h in heads)
        and not local.pending
    )
    if joining or not contained:
        sides.append(Side(key=local.key, computer=local.computer, this=True, head=None))
    for head in _maximal(heads):
        sides.append(Side(key=head.key, computer=head.computer, this=False, head=head))
    return Choice(tuple(sides), joining=joining)


def _newer_matters(local: LocalView, view: FolderView) -> bool:
    """A head of a newer Ordnung has something this one would need."""
    for head in view.others:
        if not head.newer:
            continue
        if head.head.version is None:
            continue
        if _relation(local.lineage, head) not in ("same", "behind"):
            return True
    return False


# --------------------------------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------------------------------


def decide(local: LocalView, view: FolderView, action: Action | None = None) -> Decision:
    """What to do now (module doc)."""
    if action is not None and action.kind == "choose":
        return _choose(local, view, action.key)
    if action is not None:
        return _use_here(local, view, older_copy=action.older_copy)
    if local.mode == "standing_by":
        return _standing_by(local, view)
    return _in_use(local, view)


def _in_use(local: LocalView, view: FolderView) -> Decision:
    if view.problem is not None and view.problem.code in BLOCKING:
        return Paused(view.problem)
    if view.holder is not None and view.holder != local.computer:
        return BecomeStandby(late_push=local.pending)  # R3
    heads = _versioned(view)
    mine = local.lineage
    relations = {h.computer: _relation(mine, h) for h in heads}
    if any(r in ("diverged", "decided") for r in relations.values()):
        return _choice(local, heads)  # R4
    ahead = [h for h in heads if relations[h.computer] == "ahead"]
    if ahead and not local.pending:  # R5
        best = [h for h in ahead if _covers_all(h, heads)]
        if not best:
            return _choice(local, heads)
        target = max(best, key=_rank)
        return BringIn(target) if target.complete else Arriving(target)
    if view.problem is not None and view.problem.code == "newer_ordnung" and _newer_matters(local, view):
        if local.pending or (local.base is not None and local.digest not in (None, local.base.digest)):
            return Push()
        return Paused(view.problem)
    if local.pending or (
        local.digest is not None and (local.base is None or local.digest != local.base.digest)
    ):
        return Push()  # R6
    return Idle()


def _standing_by(local: LocalView, view: FolderView) -> Decision:
    if view.problem is not None and view.problem.code in BLOCKING:
        return Paused(view.problem)
    if local.pending:
        return Standby(up_to_date=False, late_push=True)
    holder = view.by_computer(view.holder) if view.holder is not None else None
    has = None
    if holder is not None and not holder.this and holder.head.version is not None and holder.complete:
        has = holder.head.version.id
    hypothetical = _use_here(local, view, older_copy=False)
    if isinstance(hypothetical, Paused):
        return Standby(up_to_date=False, has=has, problem=hypothetical.problem)
    if isinstance(hypothetical, Choice):
        return Standby(up_to_date=all(s.complete for s in hypothetical.sides), choice=hypothetical, has=has)
    if isinstance(hypothetical, Wait):
        return Standby(up_to_date=False, arriving=hypothetical.target, has=has)
    return Standby(up_to_date=True, has=has)


def _use_here(local: LocalView, view: FolderView, *, older_copy: bool) -> Decision:
    if view.problem is not None and view.problem.code in BLOCKING:
        return Paused(view.problem)
    heads = _versioned(view)
    if local.base is None:
        return _joining(local, heads, view)
    if local.mode == "in_use" and view.holder in (None, local.computer):
        return AlreadyInUse()  # U0
    if local.pending:
        return LatePush()  # U1
    if older_copy:
        return Claim()
    mine = local.lineage
    relations = {h.computer: _relation(mine, h) for h in heads}
    if all(r in ("behind", "same") for r in relations.values()):  # U2
        same = [h for h in heads if relations[h.computer] == "same" and h.head.version is not None]
        # background results of the other computer (its digest is neither this data's nor the base's)
        assert local.base is not None
        known = (local.digest, local.base.digest)
        differing = [
            h
            for h in same
            if h.head.version is not None
            and h.head.version.digest not in known
            and h.head.version.id.key() not in local.recent  # a version this computer had already
        ]
        if differing and local.digest is not None:
            target = max(differing, key=_rank)
            return Pull(target, keep=False) if target.complete else Wait(target)
        return Claim()
    ahead = [h for h in heads if relations[h.computer] == "ahead" and _covers_all(h, heads)]
    if len({h.head.version.lineage.model_dump_json() for h in ahead if h.head.version}) == 1:  # U3
        target = max(ahead, key=_rank)
        if _newer_matters(local, view):
            return Paused(Problem("newer_ordnung"))
        return Pull(target, keep=False) if target.complete else Wait(target)
    decided = [h for h in heads if relations[h.computer] == "decided" and _covers_all(h, heads)]
    if len({h.head.version.lineage.model_dump_json() for h in decided if h.head.version}) == 1:  # U4
        target = max(decided, key=_rank)
        return Pull(target, keep=True) if target.complete else Wait(target)
    return _choice(local, heads)  # U5


def held_by(local: LocalView, heads: Sequence[HeadView]) -> list[HeadView]:
    """The heads whose version holds exactly this computer's data (the same digest): typically its own
    former self, left when it disconnected, when it joins again — its data is in the folder already."""
    if local.digest is None:
        return []
    return [h for h in heads if h.head.version is not None and h.head.version.digest == local.digest]


def _joining(local: LocalView, heads: Sequence[HeadView], view: FolderView) -> Decision:
    if not heads:
        return NotYet()  # a key file but no computer yet: its head is still on its way
    if local.has_person_data and not held_by(local, heads):
        return _choice(local, heads, joining=True)
    best = _maximal(heads)
    if len(best) != 1:
        choice = _choice(local, heads, joining=True)
        return Choice(tuple(s for s in choice.sides if not s.this), joining=True)
    target = best[0]
    return Pull(target, keep=False) if target.complete else Wait(target)


def _choose(local: LocalView, view: FolderView, key: int | None) -> Decision:
    if view.problem is not None and view.problem.code in BLOCKING:
        return Paused(view.problem)
    heads = _versioned(view)
    others = tuple(h.head.version.lineage for h in heads if h.head.version is not None)
    if key == local.key:
        return ChooseThis(others)
    target = next((h for h in heads if h.key == key), None)
    if target is None:
        return NoChoice()
    if not target.complete:
        return Wait(target, choose=True)
    return ChooseOther(target, others)


def others_have(view: FolderView, version: VersionRef | None) -> bool:
    """Another computer that is still syncing has this version (or everything of it) — blocker 2's
    second confirmation is not needed."""
    if version is None:
        return True
    for head in view.others:
        if head.left or head.newer:
            continue
        if head.head.has == version.id:
            return True
        theirs = head.head.version
        if theirs is not None and (theirs.id == version.id or lin.contains(theirs.lineage, version.lineage)):
            return True
    return False
