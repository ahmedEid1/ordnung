"""A sync tool, simulated: two copies of "the" sync folder, kept in step the way Nextcloud, Syncthing,
Dropbox or iCloud Drive would — late, in any order, in pieces, with conflict copies, online-only
placeholders and the odd rollback (design §23.2, review findings 6 and 7).

``SyncToolSim(a, b, rng)``: :meth:`poll` notices what changed on either side since the last look (what
the tool would upload); :meth:`step` delivers one pending change in a chosen or random ``mode``;
:meth:`settle` delivers everything, whole, until both sides agree.

Delivery modes:

* ``whole`` — through a temp name and a rename (most tools);
* ``pieces`` — written in place, first a part, the rest at a later step (Syncthing without temp files,
  a slow SMB copy);
* ``placeholder`` — an older iCloud Drive placeholder ``.<name>.icloud`` first, the file later;
* ``dataless`` — the file is there with its real name and size but no data yet: modelled as zeros of the
  right size until a later step (what a dataless file reads as when the provider can't fetch it);
* ``conflict`` — when the destination changed the same file too, its version is renamed to a conflict
  copy (``name (conflicted copy 2026-10-07)``, ``name.sync-conflict-…``) and the incoming one wins;
* ``rollback`` — an older version of the file is delivered first (the tool's history), the newest later;
* ``drop`` — a deletion is never delivered.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Mode = Literal["whole", "pieces", "placeholder", "dataless", "conflict", "rollback", "drop"]
MODES: tuple[Mode, ...] = ("whole", "pieces", "placeholder", "dataless", "conflict", "rollback", "drop")


def listing(root: Path) -> dict[str, bytes]:
    """Every regular file under ``root`` by its relative POSIX path (placeholders and conflict copies
    included: the tool syncs them like any file)."""
    found: dict[str, bytes] = {}
    if not root.exists():
        return found
    for current, _dirs, names in os.walk(root):
        for name in names:
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                continue
            found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


@dataclass
class Change:
    source: str
    target: str
    path: str
    content: bytes | None  # None: a deletion
    history: list[bytes] = field(default_factory=list)
    stage: int = 0


class SyncToolSim:
    """Two copies of the sync folder, synced on demand (module doc)."""

    def __init__(self, a: Path, b: Path, rng: random.Random | None = None) -> None:
        self.sides = {"a": a, "b": b}
        for root in self.sides.values():
            root.mkdir(parents=True, exist_ok=True)
        self.rng = rng or random.Random(0)
        #: what the tool last saw on each side (and delivered)
        self.known: dict[str, dict[str, bytes]] = {"a": {}, "b": {}}
        self.history: dict[str, list[bytes]] = {}
        self.pending: list[Change] = []
        self.delivered: list[tuple[str, str, Mode]] = []

    @staticmethod
    def _other(side: str) -> str:
        return "b" if side == "a" else "a"

    def poll(self) -> int:
        """Notice local changes on both sides; returns how many deliveries are pending."""
        for side, root in self.sides.items():
            now = listing(root)
            before = self.known[side]
            for path in sorted(set(now) | set(before)):
                if now.get(path) == before.get(path):
                    continue
                content = now.get(path)
                if content is not None:
                    self.history.setdefault(path, []).append(content)
                self.pending = [c for c in self.pending if not (c.source == side and c.path == path)]
                self.pending.append(
                    Change(
                        side, self._other(side), path, content, history=list(self.history.get(path, [])[:-1])
                    )
                )
            self.known[side] = now
        return len(self.pending)

    def _write(self, target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".~sim-{target.name}")
        temp.write_bytes(content)
        os.replace(temp, target)

    def step(self, mode: Mode | None = None, *, pick: int | None = None) -> bool:
        """Deliver one pending change (random unless ``pick``); False when nothing is pending."""
        if not self.pending:
            return False
        index = pick if pick is not None else self.rng.randrange(len(self.pending))
        change = self.pending[index]
        chosen: Mode = mode or self.rng.choice(MODES)
        root = self.sides[change.target]
        target = root / change.path
        done = True
        if change.content is None:
            if chosen != "drop" and target.exists():
                target.unlink()
        elif chosen == "pieces" and change.stage == 0 and len(change.content) > 1:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(change.content[: len(change.content) // 2])
            change.stage = 1
            done = False
        elif chosen == "placeholder" and change.stage == 0:
            target.parent.mkdir(parents=True, exist_ok=True)
            (target.parent / f".{target.name}.icloud").write_bytes(b"bplist00 placeholder")
            change.stage = 1
            done = False
        elif chosen == "dataless" and change.stage == 0:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bytes(len(change.content)))
            change.stage = 1
            done = False
        elif chosen == "rollback" and change.stage == 0 and change.history:
            self._write(target, change.history[-1])
            change.stage = 1
            done = False
        elif chosen == "conflict" and target.exists() and target.read_bytes() != change.content:
            copy = target.with_name(f"{target.name} (conflicted copy 2026-10-07)")
            os.replace(target, copy)
            self._write(target, change.content)
        else:
            placeholder = target.parent / f".{target.name}.icloud"
            if placeholder.exists():
                placeholder.unlink()
            self._write(target, change.content)
        self.delivered.append((change.target, change.path, chosen))
        if done:
            self.pending.pop(index)
            placeholder = target.parent / f".{target.name}.icloud"
            if placeholder.exists():
                placeholder.unlink()
        self.known[change.target] = listing(root)
        return True

    def deliver(self, source: str, *, mode: Mode = "whole") -> int:
        """Deliver everything pending from ``source`` (``"a"`` or ``"b"``) — the e2e ``deliver(a, b)``."""
        self.poll()
        count = 0
        while True:
            index = next((i for i, c in enumerate(self.pending) if c.source == source), None)
            if index is None:
                return count
            self.step(mode, pick=index)
            count += 1

    def settle(self, *, rounds: int = 10) -> None:
        """Deliver everything, whole, until nothing is pending on either side."""
        for _ in range(rounds):
            self.poll()
            if not self.pending:
                return
            while self.pending:
                self.step("whole", pick=0)
        self.poll()

    def conflict_copies(self) -> list[str]:
        return [
            path
            for side in self.sides.values()
            for path in listing(side)
            if "conflicted copy" in path or ".sync-conflict-" in path
        ]
