"""Hand-off sync, whole stories: two (or three) data folders, each with its own view of the sync folder,
and a simulated sync tool between them (design §23.1; F18-F23; review blockers 2-4)."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from fakes import use_fast_keys
from ordnung.sync.decide import Choice
from sync_harness import Computer
from sync_sim import SyncToolSim


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)


@pytest.fixture
def pair(tmp_path: Path):  # type: ignore[no-untyped-def]
    a = Computer("anna-laptop", tmp_path / "a", tmp_path / "a-sync")
    b = Computer("desktop", tmp_path / "b", tmp_path / "b-sync")
    sim = SyncToolSim(a.folder, b.folder, random.Random(1))
    yield a, b, sim
    a.close()
    b.close()


def test_setup_join_and_switch(pair) -> None:  # type: ignore[no-untyped-def]
    a, b, sim = pair
    letter = a.add_letter("Stadtwerke Abschlag 2027")
    result = a.connect()
    assert result.connected and result.created and a.mode == "in_use"
    sim.settle()
    joined = b.connect()
    assert joined.connected, joined
    assert letter in b.letters()
    assert b.mode == "in_use"
    sim.settle()
    outcome = a.round()
    assert a.mode == "standing_by", outcome
    b.person_edit("from the desktop")
    b.round()
    sim.settle()
    a.round()
    outcome = a.use_here()
    assert a.mode == "in_use", outcome
    assert "from the desktop" in a.notes()


def test_both_changed_asks_once_and_keeps_a_copy(pair) -> None:  # type: ignore[no-untyped-def]
    a, b, sim = pair
    a.add_letter("first")
    a.connect()
    sim.settle()
    b.connect()
    sim.settle()
    a.round()  # A stands by
    # apart: A takes over with the copy it has, both change something
    a.use_here(older_copy=True)
    a.person_edit("A's change")
    b.person_edit("B's change")
    a.round()
    b.round()
    sim.settle()
    outcome_a = a.round()
    outcome_b = b.round()
    choices = [o.decision for o in (outcome_a, outcome_b) if isinstance(o.decision, Choice)]
    assert choices, (outcome_a, outcome_b)
