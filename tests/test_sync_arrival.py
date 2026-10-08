"""Waiting for the sync tool: late, partial, out of order, placeholders, damage, replays, conflict copies
(design §13; F11-F17; review findings 6, 7, 9)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from fakes import use_fast_keys
from ordnung.sync import DAMAGED_AFTER_S, OBJECT_RE
from ordnung.sync.decide import Pull, Wait
from sync_faults import DatalessFs
from sync_harness import Computer
from sync_sim import MODES, SyncToolSim


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)


class Pair:
    """A in use with a letter; B joined then stood by (A took over again); B's view of the folder can
    be made to hold dataless files."""

    def __init__(self, tmp: Path, seed: int = 1) -> None:
        self.dataless: set[Path] = set()
        self.a = Computer("anna-laptop", tmp / "a", tmp / "a-sync")
        self.b = Computer("desktop", tmp / "b", tmp / "b-sync", folder_fs=DatalessFs(self.dataless))
        self.sim = SyncToolSim(self.a.folder, self.b.folder, random.Random(seed))
        self.sim.dataless = self.dataless
        a, b = self.a, self.b
        a.add_letter("first")
        a.connect()
        self.sim.settle()
        b.connect()
        self.sim.settle()
        a.round()
        a.use_here()
        self.sim.settle()
        b.round()
        assert a.mode == "in_use" and b.mode == "standing_by"

    def close(self) -> None:
        self.a.close()
        self.b.close()

    def a_changes(self) -> str:
        letter = self.a.add_letter("second")
        self.a.person_edit("note")
        self.a.round()
        return letter


@pytest.fixture
def pair(tmp_path: Path):  # type: ignore[no-untyped-def]
    made = Pair(tmp_path)
    yield made
    made.close()


def b_objects(pair: Pair) -> list[Path]:
    return [p for p in (pair.b.folder / "o").rglob("*") if p.is_file() and OBJECT_RE.match(p.name)]


def test_a_head_before_its_objects_waits(pair: Pair) -> None:  # F11
    letter = pair.a_changes()
    pair.sim.poll()
    heads = [i for i, c in enumerate(pair.sim.pending) if c.path.startswith("h/") and c.source == "a"]
    pair.sim.step("whole", pick=heads[0])
    outcome = pair.b.use_here()
    assert isinstance(outcome.decision, Wait) and outcome.waiting
    completeness = outcome.decision.target.completeness
    assert completeness is not None and completeness.have < completeness.need
    assert letter not in pair.b.letters() and pair.b.mode == "standing_by"
    pair.sim.settle()
    finished = pair.b.round()  # the waiting take-over finishes by itself
    assert finished.replaced and letter in pair.b.letters() and pair.b.mode == "in_use"


@pytest.mark.parametrize("mode", ["pieces", "placeholder", "dataless"])
def test_partial_or_placeholder_objects_wait_never_damage(pair: Pair, mode: str) -> None:  # F12, finding 6
    letter = pair.a_changes()
    pair.sim.poll()
    head = next(i for i, c in enumerate(pair.sim.pending) if c.path.startswith("h/") and c.source == "a")
    pair.sim.step("whole", pick=head)  # the head whole (a head cut short is F14), the objects not
    for change in list(pair.sim.pending):
        if change.source == "a":
            pair.sim.step(mode, pick=pair.sim.pending.index(change))
    outcome = pair.b.use_here()
    assert isinstance(outcome.decision, Wait), outcome
    if mode in ("placeholder", "dataless"):
        assert outcome.decision.target.completeness.online_only > 0  # type: ignore[union-attr]
    assert pair.b.s.view is not None and pair.b.s.view.problem is None
    pair.sim.settle()
    outcome = pair.b.round()
    assert outcome.replaced and letter in pair.b.letters()


def object_of(pair: Pair, kind: str, sha: str) -> Path:
    name = pair.a.s.vault.object_name(kind, sha)  # type: ignore[arg-type]
    return pair.b.folder / "o" / name[:2] / name[2:]


@pytest.mark.parametrize("kind", ["f", "d"])
def test_a_damaged_object_is_asked_for_and_written_again(pair: Pair, kind: str) -> None:  # F13, finding 7
    letter = pair.a_changes()
    pair.sim.settle()
    if kind == "f":
        stored = pair.a.db._conn().execute("SELECT sha256 FROM documents WHERE id=?", (letter,)).fetchone()[0]
        victim = object_of(pair, "f", stored)
    else:
        manifest = pair.a.s.scanner.manifest(pair.a.s.state.base.ref)  # type: ignore[union-attr]
        assert manifest is not None
        victim = object_of(pair, "d", manifest.db.slices[0].sha256)
    size = victim.stat().st_size
    victim.write_bytes(b"\x00" * size)  # the right size, damaged in place
    pair.sim.settle()  # and the sync tool carries the damage to the other copy too
    assert isinstance(pair.b.use_here().decision, Wait)
    pair.b.clock.advance(DAMAGED_AFTER_S + 1)
    pair.b.round()
    name = victim.parent.name + victim.name
    assert name in pair.b.s.state.wants
    pair.sim.settle()  # B's head (with its wants) reaches A
    pair.a.round()  # A writes it again, forced
    pair.sim.settle()
    assert victim.read_bytes() != b"\x00" * size
    outcome = pair.b.round()
    assert outcome.replaced


def test_an_unreadable_head_uses_its_last_good_copy(pair: Pair) -> None:  # F14
    head = next(p for p in (pair.b.folder / "h").iterdir() if p.name != pair.b.s.head_file)
    head.write_bytes(head.read_bytes()[:100])  # cut short (written in place)
    view = pair.b.s.scan()
    other = view.by_computer(pair.a.s.state.computer)
    assert other is not None and not other.readable and other.head.version is not None
    assert view.holder == pair.a.s.state.computer and view.problem is None
    pair.b.clock.advance(DAMAGED_AFTER_S + 1)
    assert pair.b.s.scan().problem.code == "damaged"  # type: ignore[union-attr]


def test_a_replayed_head_is_ignored(pair: Pair) -> None:  # F15
    head = next(p for p in (pair.b.folder / "h").iterdir() if p.name != pair.b.s.head_file)
    old = head.read_bytes()
    letter = pair.a_changes()
    pair.sim.settle()
    pair.b.round()
    head.write_bytes(old)  # the sync tool's history put an older copy back
    view = pair.b.s.scan()
    other = view.by_computer(pair.a.s.state.computer)
    assert other is not None and not other.readable
    assert other.head.version is not None and other.head.written > 1  # the newer, last good copy
    outcome = pair.b.use_here()
    assert isinstance(outcome.decision, Pull) and letter in pair.b.letters()


def test_conflict_copies_and_foreign_files_are_ignored_and_kept(pair: Pair) -> None:  # F16
    pair.a_changes()
    pair.sim.settle()
    copies = []
    for path in [*b_objects(pair)[:2], *(pair.b.folder / "h").iterdir()][:3]:
        copy = path.with_name(f"{path.name} (conflicted copy 2026-10-07)")
        copy.write_bytes(path.read_bytes())
        copies.append(copy)
    sync_conflict = pair.b.folder / "h" / "abc.sync-conflict-20261007-120000-ABCDEF"
    sync_conflict.write_bytes(b"x")
    copies.append(sync_conflict)
    pair.b.use_here()
    pair.b.round()
    for copy in copies:
        assert copy.exists()


def test_random_delivery_never_applies_an_incomplete_version(tmp_path: Path) -> None:  # acceptance 4
    for seed in range(6):
        pair = Pair(tmp_path / str(seed), seed)
        try:
            letter = pair.a_changes()
            expected = pair.a.notes()
            pair.sim.poll()
            rng = random.Random(seed)
            for _ in range(60):
                if not pair.sim.step(rng.choice(MODES)):
                    break
                outcome = pair.b.round() if pair.b.s.state.waiting else pair.b.use_here()
                if outcome.replaced:
                    assert letter in pair.b.letters() and pair.b.notes() == expected
                    break
            for _ in range(3):  # everything arrives; both computers look again
                pair.sim.settle()
                if pair.b.mode != "in_use":
                    pair.b.round() if pair.b.s.state.waiting else pair.b.use_here()
                pair.b.round()
                pair.a.round()
            pair.sim.settle()
            pair.b.round()
            assert pair.b.mode == "in_use" and pair.a.mode == "standing_by"
            assert letter in pair.b.letters() and pair.b.notes() == expected
        finally:
            pair.close()
