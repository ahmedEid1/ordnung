"""Versions by what the *person* changed (design §7; pure: no I/O, no clocks).

Every push that carries a change the person made gets a **person number** of its computer. A version's
:class:`~ordnung.sync.model.Lineage` holds, per computer, the ranges of person numbers whose changes it
*contains* (``content``) and those a choice deliberately left out (``dropped``). Background work — a
reading finished, the day rolled forward, a calendar run — never adds a number, so two computers that
differ only by background work have the same content and are never in conflict.

Between this computer's lineage ``L`` and another version's ``H`` (:func:`relation`):

* ``same`` — the same content;
* ``ahead`` — ``H`` contains everything of ``L`` and more (bringing it in loses nothing);
* ``behind`` — ``L`` accounts for everything in ``H``, keeping or dropping it (blocker 3 of the review:
  ``covers``, not ``contains`` — the winner of "keep this one" is not asked again);
* ``decided`` — ``H`` saw all of ``L`` and a person chose against some of it (bring ``H`` in, but keep
  a copy of this computer's data first);
* ``diverged`` — anything else: both have changes the other lacks, or two answers to one choice
  contradict each other. The person is asked.

Ranges are inclusive ``(first, last)`` pairs, merged and sorted after every operation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal

from ordnung.sync import LINEAGE_RANGES_MAX, SyncError
from ordnung.sync.model import Lineage, Range

Relation = Literal["same", "ahead", "behind", "decided", "diverged"]
Ranges = dict[str, list[Range]]

TOO_LONG_MESSAGE = (
    "This sync folder's history is too long. Set up a new sync folder (Settings → Your computers: "
    "Disconnect, then set up again)."
)

# --------------------------------------------------------------------------------------------------
# range sets
# --------------------------------------------------------------------------------------------------


def merge_ranges(ranges: Iterable[Range]) -> list[Range]:
    """Sorted, non-overlapping, non-adjacent ranges covering exactly the numbers of ``ranges``."""
    merged: list[Range] = []
    for first, last in sorted(ranges):
        if first > last:
            continue
        if merged and first <= merged[-1][1] + 1:
            if last > merged[-1][1]:
                merged[-1] = (merged[-1][0], last)
        else:
            merged.append((first, last))
    return merged


def _normal(sets: Mapping[str, Iterable[Range]]) -> Ranges:
    out: Ranges = {}
    for computer, ranges in sets.items():
        merged = merge_ranges(ranges)
        if merged:
            out[computer] = merged
    return dict(sorted(out.items()))


def union(*sets: Mapping[str, Iterable[Range]]) -> Ranges:
    combined: dict[str, list[Range]] = {}
    for one in sets:
        for computer, ranges in one.items():
            combined.setdefault(computer, []).extend(ranges)
    return _normal(combined)


def _subtract_one(ranges: list[Range], removed: list[Range]) -> list[Range]:
    out: list[Range] = []
    for first, last in ranges:
        pieces = [(first, last)]
        for r_first, r_last in removed:
            next_pieces: list[Range] = []
            for p_first, p_last in pieces:
                if r_last < p_first or r_first > p_last:
                    next_pieces.append((p_first, p_last))
                    continue
                if p_first < r_first:
                    next_pieces.append((p_first, r_first - 1))
                if r_last < p_last:
                    next_pieces.append((r_last + 1, p_last))
            pieces = next_pieces
        out.extend(pieces)
    return merge_ranges(out)


def difference(a: Mapping[str, Iterable[Range]], b: Mapping[str, Iterable[Range]]) -> Ranges:
    """The numbers in ``a`` that are not in ``b``."""
    out: Ranges = {}
    for computer, ranges in a.items():
        left = _subtract_one(merge_ranges(ranges), merge_ranges(b.get(computer, [])))
        if left:
            out[computer] = left
    return dict(sorted(out.items()))


def intersection(a: Mapping[str, Iterable[Range]], b: Mapping[str, Iterable[Range]]) -> Ranges:
    return difference(a, difference(a, b))


def subset(a: Mapping[str, Iterable[Range]], b: Mapping[str, Iterable[Range]]) -> bool:
    """Every number of ``a`` is in ``b``."""
    return not difference(a, b)


def empty(a: Mapping[str, Iterable[Range]]) -> bool:
    return not any(merge_ranges(ranges) for ranges in a.values())


def highest(a: Mapping[str, Iterable[Range]], computer: str) -> int:
    """The highest number of ``computer`` in ``a`` (0: none)."""
    ranges = merge_ranges(a.get(computer, []))
    return ranges[-1][1] if ranges else 0


def range_count(lineage: Lineage) -> int:
    return sum(len(r) for r in lineage.content.values()) + sum(len(r) for r in lineage.dropped.values())


# --------------------------------------------------------------------------------------------------
# lineages
# --------------------------------------------------------------------------------------------------


def make(
    content: Mapping[str, Iterable[Range]] | None = None, dropped: Mapping[str, Iterable[Range]] | None = None
) -> Lineage:
    """A lineage, normalised: ranges merged, nothing dropped that is kept, within the size limit."""
    kept = union(content or {})
    gone = difference(union(dropped or {}), kept)
    lineage = Lineage(content=kept, dropped=gone)
    if range_count(lineage) > LINEAGE_RANGES_MAX:
        raise SyncError("folder_problem", TOO_LONG_MESSAGE)
    return lineage


def knowledge(lineage: Lineage) -> Ranges:
    """Everything a version accounted for: kept or dropped."""
    return union(lineage.content, lineage.dropped)


def same(a: Lineage, b: Lineage) -> bool:
    return union(a.content) == union(b.content)


def contains(a: Lineage, b: Lineage) -> bool:
    """Nothing the person did in ``b`` is missing from ``a``."""
    return subset(b.content, a.content)


def covers(a: Lineage, b: Lineage) -> bool:
    """``a`` accounted for everything in ``b``, keeping or dropping it."""
    return subset(b.content, knowledge(a))


def bump(lineage: Lineage, computer: str, pnum: int) -> Lineage:
    """``lineage`` plus the person change ``pnum`` of ``computer``."""
    return make(union(lineage.content, {computer: [(pnum, pnum)]}), lineage.dropped)


def keep_this(mine: Lineage, others: Iterable[Lineage]) -> Lineage:
    """The person kept this computer's version over ``others``: everything they had that this one
    hasn't is dropped."""
    others = list(others)
    seen = union(mine.dropped, *(knowledge(o) for o in others))
    return make(mine.content, difference(seen, mine.content))


def keep_other(chosen: Lineage, mine: Lineage, others: Iterable[Lineage]) -> Lineage:
    """The person kept ``chosen`` over this computer's version and ``others``."""
    others = list(others)
    seen = union(chosen.dropped, knowledge(mine), *(knowledge(o) for o in others))
    return make(chosen.content, difference(seen, chosen.content))


def relation(local: Lineage, other: Lineage) -> Relation:
    """How another version ``other`` stands to this computer's ``local`` (module doc)."""
    if same(local, other):
        return "same"
    local_k, other_k = knowledge(local), knowledge(other)
    local_news = not subset(local.content, other_k)  # this computer has changes the other never saw
    other_news = not subset(other.content, local_k)  # and the other way round
    other_decided = not empty(intersection(local.content, other.dropped))  # it chose against ours
    local_decided = not empty(intersection(other.content, local.dropped))  # we chose against its
    if other_decided and local_decided:
        return "diverged"  # two answers to one choice that contradict each other
    if other_decided and not local_news:
        return "decided"
    if not other_news and not other_decided:
        return "behind"
    if not local_news and not other_decided and not local_decided:
        return "ahead"
    return "diverged"


def claims_within(lineage: Lineage, published: Mapping[str, int]) -> bool:
    """No computer's person numbers are claimed beyond the highest that computer published (review
    finding 18: a lineage bug, or a forgotten computer, must not claim everything). Computers not in
    ``published`` aren't checked (nothing is known of them)."""
    for computer, limit in published.items():
        if max(highest(lineage.content, computer), highest(lineage.dropped, computer)) > limit:
            return False
    return True
