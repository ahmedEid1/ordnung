"""Versions by the person's changes (design §7.1, §9; review blockers 2 and 3, finding 18).

The unit tests pin the algebra; the generated histories run the pure decision function over two or three
computers that change, push, deliver late, take over and choose — with a model of the data that knows
which person changes each computer holds — and check the properties of design §9: nothing the person did
is lost without a kept copy or a recorded choice, background work never asks, nothing a choice answered
is asked again (blocker 3), and once every head has arrived all computers agree who is in use.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from ordnung.sync import lineage as lin
from ordnung.sync.decide import (
    Action,
    BecomeStandby,
    BringIn,
    Choice,
    ChooseOther,
    ChooseThis,
    Claim,
    LatePush,
    LocalView,
    Pull,
    Push,
    Standby,
    decide,
)
from ordnung.sync.model import Head, Lineage, VersionId, VersionRef
from ordnung.sync.scan import Completeness, FolderView, HeadView

A, B, C = ("a" * 32, "b" * 32, "c" * 32)


def L(
    content: dict[str, list[tuple[int, int]]] | None = None,
    dropped: dict[str, list[tuple[int, int]]] | None = None,
) -> Lineage:
    return lin.make(content or {}, dropped or {})


# --------------------------------------------------------------------------------------------------
# the algebra
# --------------------------------------------------------------------------------------------------


def test_ranges_merge() -> None:
    assert lin.merge_ranges([(5, 6), (1, 2), (3, 4), (9, 9), (8, 8)]) == [(1, 6), (8, 9)]
    assert lin.merge_ranges([(5, 6), (1, 2), (3, 3)]) == [(1, 3), (5, 6)]
    assert lin.difference({A: [(1, 10)]}, {A: [(3, 4), (8, 8)]}) == {A: [(1, 2), (5, 7), (9, 10)]}
    assert lin.subset({A: [(2, 3)]}, {A: [(1, 5)]}) and not lin.subset({A: [(2, 6)]}, {A: [(1, 5)]})


def test_contains_and_covers() -> None:
    one = L({A: [(1, 2)]})
    two = L({A: [(1, 3)]})
    assert lin.contains(two, one) and not lin.contains(one, two)
    chose = L({A: [(1, 2)]}, {B: [(1, 1)]})
    other = L({B: [(1, 1)]})
    assert lin.covers(chose, other) and not lin.contains(chose, other)


def test_bump_keep_this_keep_other() -> None:
    base = L({A: [(1, 1)]})
    mine = lin.bump(base, A, 2)
    theirs = lin.bump(base, B, 1)
    kept = lin.keep_this(mine, [theirs])
    assert kept.content == {A: [(1, 2)]} and kept.dropped == {B: [(1, 1)]}
    other = lin.keep_other(theirs, mine, [theirs])
    assert other.content == {A: [(1, 1)], B: [(1, 1)]} and other.dropped == {A: [(2, 2)]}


@pytest.mark.parametrize(
    ("local", "other", "expected"),
    [
        (L({A: [(1, 1)]}), L({A: [(1, 1)]}), "same"),
        (L({A: [(1, 1)]}), L({A: [(1, 2)]}), "ahead"),
        (L({A: [(1, 2)]}), L({A: [(1, 1)]}), "behind"),
        (L({A: [(1, 1)]}), L({B: [(1, 1)]}), "diverged"),
        # blocker 3: the winner of "keep this one" sees the loser as behind, never as diverged
        (L({A: [(1, 2)]}, {B: [(1, 1)]}), L({A: [(1, 1)], B: [(1, 1)]}), "behind"),
        # … and the loser sees the winner as having decided
        (L({A: [(1, 1)], B: [(1, 1)]}), L({A: [(1, 2)]}, {B: [(1, 1)]}), "decided"),
        # two answers to one choice, given apart: asked once more
        (L({A: [(1, 1)]}, {B: [(1, 1)]}), L({B: [(1, 1)]}, {A: [(1, 1)]}), "diverged"),
    ],
)
def test_relation(local: Lineage, other: Lineage, expected: str) -> None:
    assert lin.relation(local, other) == expected


def test_a_lineage_may_not_claim_beyond_what_a_computer_published() -> None:  # finding 18
    claims_all = L({A: [(1, 1000)], B: [(1, 1)]})
    assert not lin.claims_within(claims_all, {A: 3, B: 1})
    assert lin.claims_within(L({A: [(1, 3)]}), {A: 3, B: 0})
    assert not lin.claims_within(L({}, {B: [(1, 5)]}), {B: 2})


def test_the_history_limit() -> None:
    ranges = {A: [(i * 2, i * 2) for i in range(1, 5000)]}
    with pytest.raises(Exception, match="history is too long"):
        L(ranges)


# --------------------------------------------------------------------------------------------------
# a model of computers, heads and data (pure)
# --------------------------------------------------------------------------------------------------


@dataclass
class Version:
    id: VersionId
    lineage: Lineage
    data: frozenset[str]  # the person changes (tokens) this version's data holds
    background: int  # background work done in it (changes the digest only)

    @property
    def digest(self) -> str:
        return f"{sorted(self.data)}|{self.background}".encode().hex()[:64].ljust(64, "0")

    def ref(self) -> VersionRef:
        return VersionRef(
            id=self.id,
            lineage=self.lineage,
            digest=self.digest,
            manifest="0" * 32,
            manifest_size=1,
            manifest_sha256="0" * 64,
        )


@dataclass
class Machine:
    computer: str
    key: int
    data: set[str] = field(default_factory=set)
    background: int = 0
    base: Version | None = None
    pending: list[str] = field(default_factory=list)  # person changes not pushed
    mode: str = "standing_by"
    head_state: str = "standing_by"
    epoch: int = 0
    seq: int = 0
    pnum: int = 0
    written: int = 0
    kept: list[frozenset[str]] = field(default_factory=list)
    #: what this computer sees of the others' heads (delivered by the "sync tool")
    seen: dict[str, tuple[Head, Version | None]] = field(default_factory=dict)

    def head(self) -> Head:
        return Head(
            format=1,
            vault="0" * 32,
            computer=self.computer,
            name=f"computer-{self.key}",
            written=max(1, self.written),
            state=self.head_state,  # type: ignore[arg-type]
            epoch=self.epoch,
            version=self.base.ref() if self.base else None,
            has=None,
            pnum=self.pnum,
            app_version="test",
            schema_version=5,
        )


class World:
    """Computers that only know each other's heads through deliveries."""

    def __init__(self, names: int) -> None:
        self.machines = {c: Machine(c, i + 1) for i, c in enumerate((A, B, C)[:names])}
        self.versions: dict[str, Version] = {}
        self.tokens = itertools.count(1)
        self.made: set[str] = set()
        self.choices: list[tuple[str, frozenset[str]]] = []  # (chooser, tokens it decided to drop)
        self.asked_after_choice = False
        self.choice_settled = False
        #: two answers given on two computers before either saw the other's: asked once more (§9)
        self.conflicting = False
        self.changed_since_choice = False
        self.choice_versions: dict[str, str] = {}

    # ---- the views decide() sees ---------------------------------------------------------------

    def view(self, m: Machine) -> FolderView:
        heads = [HeadView(file=m.computer, head=m.head(), key=m.key, this=True)]
        for computer, (head, version) in m.seen.items():
            heads.append(
                HeadView(
                    file=computer,
                    head=head,
                    key=self.machines[computer].key,
                    this=False,
                    completeness=Completeness(True),
                )
            )
        live = [h for h in heads if h.head.state != "left"]
        holder = max(live, key=lambda h: (h.head.epoch, h.computer)).computer if live else None
        return FolderView(heads=tuple(heads), holder=holder, max_epoch=max(h.head.epoch for h in heads))

    def local(self, m: Machine) -> LocalView:
        base = m.base
        digest = Version(
            VersionId(computer=m.computer, seq=1), Lineage(), frozenset(m.data), m.background
        ).digest
        return LocalView(
            computer=m.computer,
            mode=m.mode,  # type: ignore[arg-type]
            base=base.ref() if base else None,
            pending=bool(m.pending) and m.base is not None,
            next_pnum=m.pnum + 1,
            digest=digest,
            has_person_data=bool(m.data),
            key=m.key,
        )

    # ---- actions -----------------------------------------------------------------------------------

    def person(self, m: Machine) -> None:
        token = f"t{next(self.tokens)}"
        m.data.add(token)
        m.pending.append(token)
        self.made.add(token)

    def push(self, m: Machine, lineage: Lineage | None = None, state: str | None = None) -> None:
        m.seq += 1
        person = bool(m.pending)
        if person:
            m.pnum += 1
        base = m.base.lineage if m.base else Lineage()
        computed = lin.bump(base, m.computer, m.pnum) if person else base
        if lineage is not None:
            computed = lin.make(
                lin.union(lineage.content, {m.computer: [(m.pnum, m.pnum)]}) if person else lineage.content,
                lineage.dropped,
            )
        version = Version(
            VersionId(computer=m.computer, seq=m.seq), computed, frozenset(m.data), m.background
        )
        self.versions[version.id.key()] = version
        m.base = version
        m.pending = []
        if state:
            m.head_state = state
        m.written += 1

    def pull(self, m: Machine, target: Version, *, keep: bool) -> None:
        if keep:
            m.kept.append(frozenset(m.data))
        m.data = set(target.data)
        m.background = target.background
        m.base = target
        m.pending = []

    def claim(self, m: Machine) -> None:
        m.epoch = max([m.epoch, *(h.epoch for h, _v in m.seen.values())]) + 1
        m.mode = m.head_state = "in_use"
        m.written += 1

    def deliver(self, source: Machine, target: Machine) -> None:
        if source.base is None:
            return  # not connected yet: it has no head
        target.seen[source.computer] = (source.head(), source.base)

    def target_version(self, head: HeadView) -> Version:
        assert head.head.version is not None
        return self.versions[head.head.version.id.key()]

    # ---- the engine's loop, on the model -----------------------------------------------------------

    def round(self, m: Machine) -> object:
        decision = decide(self.local(m), self.view(m))
        if isinstance(decision, BecomeStandby):
            if decision.late_push:
                self.push(m, state="standing_by")
            m.mode = m.head_state = "standing_by"
            m.written += 1
        elif isinstance(decision, BringIn):
            self.pull(m, self.target_version(decision.target), keep=False)
        elif isinstance(decision, Push):
            self.push(m)
        elif isinstance(decision, Standby) and decision.late_push:
            self.push(m, state="standing_by")
        if isinstance(decision, Choice) and self.choice_settled:
            self.asked_after_choice = True
        return decision

    def use_here(self, m: Machine, *, older_copy: bool = False) -> object:
        for _ in range(3):
            decision = decide(self.local(m), self.view(m), Action("use_here", older_copy=older_copy))
            if isinstance(decision, LatePush):
                self.push(m)
                continue
            if isinstance(decision, Claim):
                self.claim(m)
            elif isinstance(decision, Pull):
                self.pull(m, self.target_version(decision.target), keep=decision.keep)
                self.claim(m)
            if isinstance(decision, Choice) and self.choice_settled:
                self.asked_after_choice = True
            return decision
        return None

    def choose(self, m: Machine, key: int) -> object:
        decision = decide(self.local(m), self.view(m), Action("choose", key=key))
        base = m.base.lineage if m.base else Lineage()
        if isinstance(decision, ChooseThis | ChooseOther):
            unseen = [
                computer
                for computer, version in self.choice_versions.items()
                if computer != m.computer
                and (m.seen.get(computer, (None, None))[1] is None or m.seen[computer][1].id.key() != version)  # type: ignore[union-attr]
            ]
            self.conflicting = bool(unseen)
        if isinstance(decision, ChooseThis):
            dropped = frozenset().union(*(v.data for _h, v in m.seen.values() if v is not None)) - frozenset(
                m.data
            )
            self.choices.append((m.computer, dropped))
            self.push(m, lineage=lin.keep_this(base, decision.others), state="in_use")
            self.claim(m)
        elif isinstance(decision, ChooseOther):
            target = self.target_version(decision.target)
            self.choices.append((m.computer, frozenset(m.data) - target.data))
            self.pull(m, target, keep=True)
            self.push(m, lineage=lin.keep_other(target.lineage, base, decision.others), state="in_use")
            self.claim(m)
        if isinstance(decision, ChooseThis | ChooseOther) and m.base is not None:
            self.choice_versions[m.computer] = m.base.id.key()
            self.changed_since_choice = False
        return decision

    def everything_kept(self) -> set[str]:
        found: set[str] = set()
        for m in self.machines.values():
            found |= m.data
            for copy in m.kept:
                found |= copy
        return found


class Histories(RuleBasedStateMachine):
    """Random histories over the model (two or three computers)."""

    def __init__(self) -> None:
        super().__init__()
        self.world = World(2)
        self.background_only = True
        first = self.world.machines[A]
        self.world.person(first)
        self.world.push(first)
        self.world.claim(first)

    @rule(names=st.sampled_from([2, 3]))
    @precondition(
        lambda self: (
            len(self.world.machines) == 2 and not any(m.base for m in list(self.world.machines.values())[1:])
        )
    )
    def three(self, names: int) -> None:
        if names == 3:
            world = self.world
            world.machines[C] = Machine(C, 3)

    def _m(self, index: int) -> Machine:
        machines = list(self.world.machines.values())
        return machines[index % len(machines)]

    @rule(index=st.integers(0, 2))
    def person_change(self, index: int) -> None:
        m = self._m(index)
        if m.mode == "in_use" or m.base is None:
            self.world.person(m)
            self.background_only = False
            self.world.choice_settled = False
            self.world.changed_since_choice = True

    @rule(index=st.integers(0, 2))
    def background(self, index: int) -> None:
        m = self._m(index)
        if m.mode == "in_use":
            m.background += 1

    @rule(index=st.integers(0, 2))
    def round(self, index: int) -> None:
        m = self._m(index)
        if m.base is not None:
            decision = self.world.round(m)
            if self.background_only:
                assert not isinstance(decision, Choice), "background work asked a question"

    @rule(src=st.integers(0, 2), dst=st.integers(0, 2))
    def deliver(self, src: int, dst: int) -> None:
        a, b = self._m(src), self._m(dst)
        if a is not b:
            self.world.deliver(a, b)

    @rule(index=st.integers(0, 2), older=st.booleans())
    def use_here(self, index: int, older: bool) -> None:
        m = self._m(index)
        decision = self.world.use_here(m, older_copy=older and m.base is not None)
        if self.background_only:
            assert not isinstance(decision, Choice) or (m.base is None and m.data), decision

    @rule(index=st.integers(0, 2), pick=st.integers(0, 3))
    def choose(self, index: int, pick: int) -> None:
        m = self._m(index)
        if m.base is None:
            return
        decision = decide(self.world.local(m), self.world.view(m))
        if not isinstance(decision, Choice) and not (
            isinstance(decision, Standby) and decision.choice is not None
        ):
            return
        choice = decision if isinstance(decision, Choice) else decision.choice
        assert choice is not None
        side = choice.sides[pick % len(choice.sides)]
        self.world.choose(m, side.key)
        self.settle_after_choice = True

    @rule()
    def settle(self) -> None:
        """Every head delivered everywhere, then one round each: the questions a choice answered stay
        answered (blocker 3), and all computers agree who is in use."""
        world = self.world
        machines = [m for m in world.machines.values() if m.base is not None]
        settled_choice = bool(world.choices) and not world.changed_since_choice and not world.conflicting
        world.choice_settled = settled_choice
        for _ in range(3):
            for a in machines:
                for b in machines:
                    if a is not b:
                        world.deliver(a, b)
            for m in machines:
                world.round(m)
        holders = {world.view(m).holder for m in machines}
        assert len(holders) == 1, holders
        world.choice_settled = False

    @invariant()
    def nothing_lost(self) -> None:
        world = self.world
        dropped = frozenset().union(*(d for _c, d in world.choices)) if world.choices else frozenset()
        missing = world.made - world.everything_kept() - dropped
        assert not missing, f"lost person changes: {sorted(missing)}"

    @invariant()
    def nothing_asked_again(self) -> None:
        assert not self.world.asked_after_choice, "a choice already answered was asked again"


TestHistories = Histories.TestCase
TestHistories.settings = settings(
    max_examples=200, stateful_step_count=40, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


def test_background_only_histories_never_ask() -> None:
    """Exhaustive for short histories: two computers, background work and switches only."""
    for steps in itertools.product(
        ("bg_a", "bg_b", "round_a", "round_b", "deliver", "use_b", "use_a"), repeat=5
    ):
        world = World(2)
        a, b = world.machines[A], world.machines[B]
        world.person(a)
        world.push(a)
        world.claim(a)
        world.deliver(a, b)
        world.use_here(b)
        world.deliver(b, a)
        for step in steps:
            if step == "bg_a" and a.mode == "in_use":
                a.background += 1
            elif step == "bg_b" and b.mode == "in_use":
                b.background += 1
            elif step == "round_a":
                assert not isinstance(world.round(a), Choice)
            elif step == "round_b":
                assert not isinstance(world.round(b), Choice)
            elif step == "deliver":
                world.deliver(a, b)
                world.deliver(b, a)
            elif step == "use_a":
                assert not isinstance(world.use_here(a), Choice)
            elif step == "use_b":
                assert not isinstance(world.use_here(b), Choice)


def test_the_winner_is_not_asked_again() -> None:  # blocker 3
    world = World(2)
    a, b = world.machines[A], world.machines[B]
    world.person(a)
    world.push(a)
    world.claim(a)
    world.deliver(a, b)
    assert isinstance(world.use_here(b), Pull)
    world.deliver(b, a)
    world.round(a)  # a stands by
    world.use_here(a, older_copy=True)  # apart: both claim and change
    world.person(a)
    world.person(b)
    world.round(a)
    world.round(b)
    world.deliver(a, b)
    world.deliver(b, a)
    decision = world.round(a)
    assert isinstance(decision, Choice)
    world.choose(a, a.key)  # keep this one
    world.deliver(a, b)
    world.deliver(b, a)
    for _ in range(3):
        assert not isinstance(world.round(a), Choice)
        world.deliver(a, b)
        world.deliver(b, a)
    loser = world.use_here(b)
    assert isinstance(loser, Pull) and loser.keep  # U4: a copy of b's data first
    assert b.kept and world.everything_kept() >= world.made - world.choices[0][1]
    world.deliver(b, a)
    assert not isinstance(world.round(a), Choice)


def test_a_left_head_still_counts_for_content() -> None:  # blocker 2
    world = World(2)
    a, b = world.machines[A], world.machines[B]
    world.person(a)
    world.push(a)
    world.claim(a)
    world.deliver(a, b)
    world.use_here(b)
    world.deliver(b, a)
    world.round(a)  # a stands by with an old base
    world.person(b)
    world.push(b)
    b.head_state = "left"  # b deletes everything: its last version stays in its head
    b.mode = "standing_by"
    world.deliver(b, a)
    decision = world.use_here(a)
    assert isinstance(decision, Pull) and decision.target.computer == B
    assert world.everything_kept() >= world.made
