"""The decision function, row by row, on hand-built views (design §9; F22; review blockers 2-3, findings
13, 31)."""

from __future__ import annotations

import pytest

from ordnung.sync import lineage as lin
from ordnung.sync.decide import (
    Action,
    AlreadyInUse,
    Arriving,
    BecomeStandby,
    BringIn,
    Choice,
    ChooseOther,
    ChooseThis,
    Claim,
    Idle,
    LatePush,
    LocalView,
    NoChoice,
    NotYet,
    Paused,
    Pull,
    Push,
    Standby,
    Wait,
    decide,
    others_have,
)
from ordnung.sync.model import Head, Lineage, VersionId, VersionRef
from ordnung.sync.scan import Completeness, FolderView, HeadView, Problem

ME, A, B = ("e" * 32, "a" * 32, "b" * 32)
DIGEST = "d" * 64


def L(
    content: dict[str, list[tuple[int, int]]] | None = None,
    dropped: dict[str, list[tuple[int, int]]] | None = None,
) -> Lineage:
    return lin.make(content or {}, dropped or {})


def ref(computer: str, seq: int, lineage: Lineage, digest: str = DIGEST) -> VersionRef:
    return VersionRef(
        id=VersionId(computer=computer, seq=seq),
        lineage=lineage,
        digest=digest,
        manifest="0" * 32,
        manifest_size=10,
        manifest_sha256="0" * 64,
    )


def head(
    computer: str,
    key: int,
    lineage: Lineage | None,
    *,
    epoch: int = 1,
    state: str = "standing_by",
    complete: bool = True,
    digest: str = DIGEST,
    this: bool = False,
    newer: bool = False,
    has: VersionId | None = None,
    pnum: int = 99,
) -> HeadView:
    h = Head(
        format=1,
        vault="0" * 32,
        computer=computer,
        name=f"computer-{key}",
        written=1,
        state=state,  # type: ignore[arg-type]
        epoch=epoch,
        version=ref(computer, 1, lineage, digest) if lineage is not None else None,
        has=has,
        pnum=pnum,
        app_version="1",
        schema_version=5,
    )
    return HeadView(
        file=computer,
        head=h,
        key=key,
        this=this,
        newer=newer,
        completeness=Completeness(complete) if not this else None,
    )


def view(*heads: HeadView, holder: str | None = None, problem: Problem | None = None) -> FolderView:
    live = [h for h in heads if not h.left]
    if holder is None and live:
        holder = max(live, key=lambda h: (h.head.epoch, h.computer)).computer
    return FolderView(
        heads=heads, holder=holder, problem=problem, max_epoch=max((h.head.epoch for h in heads), default=0)
    )


def local(
    lineage: Lineage | None,
    *,
    mode: str = "in_use",
    pending: bool = False,
    digest: str = DIGEST,
    data: bool = True,
) -> LocalView:
    return LocalView(
        computer=ME,
        mode=mode,  # type: ignore[arg-type]
        base=ref(ME, 1, lineage) if lineage is not None else None,
        pending=pending,
        next_pnum=5,
        digest=digest,
        has_person_data=data,
        key=1,
    )


BASE = L({ME: [(1, 1)]})
AHEAD = L({ME: [(1, 1)], A: [(1, 1)]})
OTHER = L({A: [(1, 1)]})
ME_HEAD = head(ME, 1, BASE, epoch=3, state="in_use", this=True)


# --------------------------------------------------------------------------------------------------
# in use
# --------------------------------------------------------------------------------------------------


def test_r1_a_folder_problem_pauses() -> None:
    decision = decide(local(BASE), view(ME_HEAD, problem=Problem("folder_missing")))
    assert isinstance(decision, Paused) and decision.problem.code == "folder_missing"


def test_r3_another_holder_means_standing_by() -> None:
    other = head(A, 2, BASE, epoch=4, state="in_use")
    assert decide(local(BASE), view(ME_HEAD, other)) == BecomeStandby(late_push=False)
    assert decide(local(BASE, pending=True), view(ME_HEAD, other)) == BecomeStandby(late_push=True)


def test_r4_diverged_or_decided_is_a_choice() -> None:
    diverged = head(A, 2, OTHER, epoch=1)
    decision = decide(local(BASE), view(ME_HEAD, diverged))
    assert isinstance(decision, Choice) and {s.key for s in decision.sides} == {1, 2}
    decided = head(A, 2, L({A: [(1, 1)]}, {ME: [(1, 1)]}), epoch=1)
    assert isinstance(decide(local(BASE), view(ME_HEAD, decided)), Choice)


def test_r5_ahead_is_brought_in_quietly_or_waited_for() -> None:
    late = head(A, 2, AHEAD, epoch=1)
    decision = decide(local(BASE), view(ME_HEAD, late))
    assert isinstance(decision, BringIn) and decision.target.computer == A
    arriving = head(A, 2, AHEAD, epoch=1, complete=False)
    assert isinstance(decide(local(BASE), view(ME_HEAD, arriving)), Arriving)
    # with changes pending here it is no longer "ahead": the person is asked
    assert isinstance(decide(local(BASE, pending=True), view(ME_HEAD, late)), Choice)


def test_r6_changes_push_and_r7_idle() -> None:
    behind = head(A, 2, BASE, epoch=1)
    assert isinstance(decide(local(BASE, digest="1" * 64), view(ME_HEAD, behind)), Push)
    assert isinstance(decide(local(BASE, pending=True), view(ME_HEAD, behind)), Push)
    assert isinstance(decide(local(BASE), view(ME_HEAD, behind)), Idle)


def test_background_only_differences_never_ask() -> None:  # F19, F20
    other_background = head(A, 2, BASE, epoch=1, digest="2" * 64)
    assert isinstance(decide(local(BASE, digest="1" * 64), view(ME_HEAD, other_background)), Push)


def test_a_newer_head_blocks_pulling_not_pushing() -> None:  # finding 13
    newer = head(A, 2, AHEAD, epoch=1, newer=True)
    decision = decide(local(BASE, pending=True), view(ME_HEAD, newer, problem=Problem("newer_ordnung")))
    assert isinstance(decision, Push)
    assert isinstance(decide(local(BASE), view(ME_HEAD, newer, problem=Problem("newer_ordnung"))), Paused)


# --------------------------------------------------------------------------------------------------
# standing by
# --------------------------------------------------------------------------------------------------


def test_standing_by_reports_and_acknowledges() -> None:
    me = head(ME, 1, BASE, epoch=1, this=True)
    holder = head(A, 2, AHEAD, epoch=4, state="in_use")
    decision = decide(local(BASE, mode="standing_by"), view(me, holder))
    assert isinstance(decision, Standby) and decision.up_to_date and decision.has == holder.head.version.id  # type: ignore[union-attr]
    arriving = head(A, 2, AHEAD, epoch=4, state="in_use", complete=False)
    decision = decide(local(BASE, mode="standing_by"), view(me, arriving))
    assert isinstance(decision, Standby) and not decision.up_to_date and decision.arriving is not None
    assert decision.has is None
    late = decide(local(BASE, mode="standing_by", pending=True), view(me, holder))
    assert isinstance(late, Standby) and late.late_push


# --------------------------------------------------------------------------------------------------
# use Ordnung here
# --------------------------------------------------------------------------------------------------


def use(lv: LocalView, fv: FolderView, *, older: bool = False) -> object:
    return decide(lv, fv, Action("use_here", older_copy=older))


def test_u0_u1() -> None:
    assert isinstance(use(local(BASE), view(ME_HEAD)), AlreadyInUse)
    me = head(ME, 1, BASE, epoch=1, this=True)
    holder = head(A, 2, BASE, epoch=4, state="in_use")
    assert isinstance(use(local(BASE, mode="standing_by", pending=True), view(me, holder)), LatePush)


def test_u2_claims_or_pulls_background_results() -> None:
    me = head(ME, 1, BASE, epoch=1, this=True)
    same = head(A, 2, BASE, epoch=4, state="in_use")
    assert isinstance(use(local(BASE, mode="standing_by"), view(me, same)), Claim)
    background = head(A, 2, BASE, epoch=4, state="in_use", digest="7" * 64)
    decision = use(local(BASE, mode="standing_by"), view(me, background))
    assert isinstance(decision, Pull) and not decision.keep


def test_u3_ahead_pulls_without_a_copy() -> None:
    me = head(ME, 1, BASE, epoch=1, this=True)
    ahead = head(A, 2, AHEAD, epoch=4, state="closed")
    decision = use(local(BASE, mode="standing_by"), view(me, ahead))
    assert isinstance(decision, Pull) and not decision.keep and decision.target.computer == A
    waiting = head(A, 2, AHEAD, epoch=4, complete=False)
    assert isinstance(use(local(BASE, mode="standing_by"), view(me, waiting)), Wait)
    assert isinstance(use(local(BASE, mode="standing_by"), view(me, waiting), older=True), Claim)


def test_u4_decided_against_pulls_with_a_copy() -> None:
    me = head(ME, 1, BASE, epoch=1, this=True)
    decided = head(A, 2, L({A: [(1, 1)]}, {ME: [(1, 1)]}), epoch=4, state="in_use")
    decision = use(local(BASE, mode="standing_by"), view(me, decided))
    assert isinstance(decision, Pull) and decision.keep


def test_u5_otherwise_a_choice() -> None:
    me = head(ME, 1, BASE, epoch=1, this=True)
    diverged = head(A, 2, OTHER, epoch=4, state="in_use")
    decision = use(local(BASE, mode="standing_by"), view(me, diverged))
    assert isinstance(decision, Choice) and len(decision.sides) == 2


def test_simultaneous_claims_pick_the_higher_epoch_then_id() -> None:  # F22
    me = head(ME, 1, BASE, epoch=5, state="in_use", this=True)
    a = head(A, 2, BASE, epoch=5, state="in_use")
    assert view(me, a).holder == ME  # "e…" > "a…": the same answer on every computer
    b = head(A, 2, BASE, epoch=6, state="in_use")
    assert view(me, b).holder == A


def test_joining() -> None:
    folder = head(A, 2, OTHER, epoch=2, state="in_use")
    decision = use(local(None, mode="standing_by", data=True, digest="e" * 64), view(folder))
    assert isinstance(decision, Choice) and decision.joining
    # the folder holds exactly this computer's data already (it joins again after leaving): nothing to ask
    again = use(local(None, mode="standing_by", data=True, digest=DIGEST), view(folder))
    assert isinstance(again, Pull) and not again.keep
    empty = use(local(None, mode="standing_by", data=False), view(folder))
    assert isinstance(empty, Pull) and not empty.keep
    assert isinstance(use(local(None, mode="standing_by", data=False), view()), NotYet)


def test_joining_while_the_others_diverge_asks() -> None:  # finding 31
    one = head(A, 2, OTHER, epoch=2, state="in_use")
    two = head(B, 3, L({B: [(1, 1)]}), epoch=1)
    decision = use(local(None, mode="standing_by", data=False), view(one, two))
    assert isinstance(decision, Choice) and decision.joining and len(decision.sides) == 2


def test_a_left_head_counts_for_content_not_for_the_lease() -> None:  # blocker 2
    me = head(ME, 1, BASE, epoch=1, this=True)
    left = head(A, 2, AHEAD, epoch=9, state="left")
    fv = view(me, left)
    assert fv.holder == ME
    decision = use(local(BASE, mode="standing_by"), fv)
    assert isinstance(decision, Pull) and decision.target.computer == A


# --------------------------------------------------------------------------------------------------
# choose
# --------------------------------------------------------------------------------------------------


def test_choose_this_other_waiting_or_none() -> None:
    other = head(A, 2, OTHER, epoch=2, state="in_use")
    fv = view(ME_HEAD, other)
    assert isinstance(decide(local(BASE), fv, Action("choose", key=1)), ChooseThis)
    assert isinstance(decide(local(BASE), fv, Action("choose", key=2)), ChooseOther)
    assert isinstance(decide(local(BASE), fv, Action("choose", key=7)), NoChoice)
    arriving = view(ME_HEAD, head(A, 2, OTHER, epoch=2, complete=False))
    assert isinstance(decide(local(BASE), arriving, Action("choose", key=2)), Wait)


@pytest.mark.parametrize("has_it", [True, False])
def test_others_have_the_latest(has_it: bool) -> None:  # blocker 2's second confirmation
    mine = ref(ME, 1, BASE)
    other = head(A, 2, AHEAD if has_it else OTHER, epoch=1)
    assert others_have(view(ME_HEAD, other), mine) is has_it
    acknowledged = head(A, 2, OTHER, epoch=1, has=mine.id)
    assert others_have(view(ME_HEAD, acknowledged), mine)
