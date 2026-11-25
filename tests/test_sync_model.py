"""The two-computer model: Hypothesis drives two real data folders, the real engine and a
simulated sync tool through random histories — the person's edits and background work on either
computer, saves, hand-overs, "Use Ordnung here" (plain or with the copy at hand), choices, deliveries in
any order and shape, restarts in the middle of a save, clock jumps and a full folder — and checks after
every step:

* **no change of the person's is lost:** every note ever written is in one computer's data or in a kept
  copy (opened with the sync passphrase);
* **the data folder is usable** on both computers (SQLite's ``quick_check``);
* **nothing incomplete is applied:** every pull's target had fully arrived and verified when applied;
* **local state stays local:** each computer's own ``inbox_seen`` is never overwritten;
* after everything is delivered and each computer looked twice, **at most one computer is in use**.

40 examples in the normal run; 400 under ``-m slow``.
"""

from __future__ import annotations

import random
import shutil
import sqlite3
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from fakes import use_fast_keys
from ordnung.backup import restore_backup
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.sync import SyncError
from ordnung.sync import engine as engine_module
from ordnung.sync.decide import Choice, Standby
from ordnung.sync.folder import RealFs
from sync_faults import CrashingFs, FullFs, SimulatedCrash
from sync_harness import PASSPHRASE, Computer
from sync_sim import MODES, SyncToolSim

APPLIED_INCOMPLETE: list[str] = []


class TwoComputers(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.patch = pytest.MonkeyPatch()
        use_fast_keys(self.patch)
        real_apply = engine_module.Session.apply

        def checked_apply(session: Any, staged: Any, store: Any, **kw: Any) -> Any:
            ready = session.scanner.completeness(staged.target, {}).ready
            if not ready:
                APPLIED_INCOMPLETE.append(staged.target.id.key())
            return real_apply(session, staged, store, **kw)

        self.patch.setattr(engine_module.Session, "apply", checked_apply)
        self.tmp = Path(tempfile.mkdtemp(prefix="sync-model-"))
        self.a = Computer("anna-laptop", self.tmp / "a", self.tmp / "a-sync")
        self.b = Computer("desktop", self.tmp / "b", self.tmp / "b-sync")
        self.sim = SyncToolSim(self.a.folder, self.b.folder, random.Random(0))
        self.made: set[str] = set()
        self.counter = 0
        self.a.db.set_meta("inbox_seen", '["a"]')
        self.b.db.set_meta("inbox_seen", '["b"]')
        self.a.connect()
        self.sim.settle()
        self.b.connect()
        self.sim.settle()
        self.a.round()
        self.kept_seen: dict[tuple[str, str, int, int], set[str]] = {}

    def teardown(self) -> None:
        self.a.close()
        self.b.close()
        self.patch.undo()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _pick(self, which: int) -> Computer:
        return self.a if which == 0 else self.b

    # ---- the person and the computers ---------------------------------------------------------------

    @rule(which=st.integers(0, 1))
    def person_edit(self, which: int) -> None:
        computer = self._pick(which)
        if computer.mode == "in_use":
            self.counter += 1
            text = f"note {self.counter}"
            computer.person_edit(text)
            self.made.add(text)

    @rule(which=st.integers(0, 1))
    def background_edit(self, which: int) -> None:
        computer = self._pick(which)
        if computer.mode == "in_use":
            computer.background_edit()

    @rule(which=st.integers(0, 1))
    def round(self, which: int) -> None:
        try:
            self._pick(which).round()
        except SyncError:
            pass

    @rule(which=st.integers(0, 1), older=st.booleans())
    def use_here(self, which: int, older: bool) -> None:
        try:
            self._pick(which).use_here(older_copy=older)
        except SyncError:
            pass

    @rule(which=st.integers(0, 1))
    def hand_over(self, which: int) -> None:
        computer = self._pick(which)
        if computer.mode == "in_use":
            try:
                computer.s.save_now(computer.db, hand_over=True)
            except SyncError:
                pass

    @rule(which=st.integers(0, 1), this=st.booleans())
    def choose(self, which: int, this: bool) -> None:
        computer = self._pick(which)
        other = self.b if computer is self.a else self.a
        view = computer.s.scan()
        decision = engine_module.decide(
            computer.s.local_view(computer.db, snapshot=computer.s.snapshot()), view
        )
        choice = decision if isinstance(decision, Choice) else getattr(decision, "choice", None)
        if not isinstance(choice, Choice) and not (isinstance(decision, Standby) and decision.choice):
            return
        head = view.by_computer(other.s.state.computer)
        key = computer.s.key if this or head is None else head.key
        try:
            computer.choose(key)
        except SyncError:
            pass

    # ---- the sync tool ------------------------------------------------------------------------------

    @rule(mode=st.sampled_from(MODES), pick=st.integers(0, 50))
    def sim_step(self, mode: str, pick: int) -> None:
        self.sim.poll()
        if self.sim.pending:
            self.sim.step(mode, pick=pick % len(self.sim.pending))  # type: ignore[arg-type]

    @rule()
    def settle(self) -> None:
        self.sim.settle()

    # ---- trouble ------------------------------------------------------------------------------------

    @rule(which=st.integers(0, 1), after=st.integers(0, 40))
    def crash_while_saving(self, which: int, after: int) -> None:
        computer = self._pick(which)
        crash = CrashingFs(after_ops=after)
        session = computer.s
        session.folder.fs = crash
        session.data_fs = crash
        session.local.fs = crash
        try:
            computer.round()
        except (SimulatedCrash, SyncError):
            pass
        computer.restart(folder_fs=RealFs(), data_fs=RealFs())

    @rule(which=st.integers(0, 1))
    def folder_full_once(self, which: int) -> None:
        computer = self._pick(which)
        computer.s.folder.fs = FullFs(after_bytes=1000)
        try:
            computer.round()
        except (SyncError, OSError):
            pass
        computer.s.folder.fs = RealFs()

    @rule(which=st.integers(0, 1), days=st.integers(-3, 3))
    def clock_jump(self, which: int, days: int) -> None:
        self._pick(which).clock.jump_wall(timedelta(days=days))

    # ---- invariants ---------------------------------------------------------------------------------

    def _kept_notes(self, computer: Computer) -> set[str]:
        # A kept copy's name is unique only in its own computer's ``sync/kept/`` (it is the minute on
        # that computer's clock, and both fake clocks start at the same minute), so what was read is
        # remembered per computer and per file (name, size, time), never by the name alone: the other
        # computer's copy of the same name must not stand in for this one.
        found: set[str] = set()
        for path in computer.s.local.kept_files():
            info = path.stat()
            key = (computer.name, path.name, info.st_size, info.st_mtime_ns)
            if key not in self.kept_seen:
                target = self.tmp / "restored" / str(len(self.kept_seen))
                restore_backup(path, PASSPHRASE, target)
                with Store.open(Paths(target)) as copy:
                    self.kept_seen[key] = {r["text"] for r in copy._conn().execute("SELECT text FROM notes")}
            found |= self.kept_seen[key]
        return found

    @invariant()
    def nothing_lost(self) -> None:
        everywhere = self.a.notes() | self.b.notes() | self._kept_notes(self.a) | self._kept_notes(self.b)
        missing = self.made - everywhere
        assert not missing, f"lost: {sorted(missing)}"

    @invariant()
    def usable(self) -> None:
        for computer in (self.a, self.b):
            conn = sqlite3.connect(f"{computer.paths.db.resolve().as_uri()}?mode=ro", uri=True)
            try:
                assert conn.execute("PRAGMA quick_check").fetchall() == [("ok",)]
            finally:
                conn.close()

    @invariant()
    def local_state_stays(self) -> None:
        assert self.a.db.get_meta("inbox_seen") == '["a"]'
        assert self.b.db.get_meta("inbox_seen") == '["b"]'

    @invariant()
    def nothing_incomplete_applied(self) -> None:
        assert not APPLIED_INCOMPLETE, APPLIED_INCOMPLETE

    @precondition(lambda self: True)
    @rule()
    def converge(self) -> None:
        """Everything delivered, each computer looks twice: at most one is in use."""
        for _ in range(2):
            self.sim.settle()
            for computer in (self.a, self.b):
                try:
                    computer.round()
                except SyncError:
                    pass
        self.sim.settle()
        for computer in (self.a, self.b):
            try:
                computer.round()
            except SyncError:
                pass
        assert not (self.a.mode == "in_use" and self.b.mode == "in_use")


TestTwoComputers = pytest.mark.slow(TwoComputers.TestCase)  # 40 histories of 25 steps over real data folders
TestTwoComputers.settings = settings(
    max_examples=40, stateful_step_count=25, deadline=None, suppress_health_check=list(HealthCheck)
)


@pytest.mark.slow
def test_two_computers_many_histories() -> None:
    from hypothesis.stateful import run_state_machine_as_test

    run_state_machine_as_test(
        TwoComputers,
        settings=settings(
            max_examples=400, stateful_step_count=30, deadline=None, suppress_health_check=list(HealthCheck)
        ),
    )


# ---- a history the random runs once found -----------------------------------------------------------

_A, _B = 0, 1
#: Two choices answered on both computers before either answer arrived, at the same minute on both
#: clocks: each computer keeps a copy of its own data first (Rule K), and both copies get the same file
#: name, each in its own computer's ``sync/kept/``. The model once read one computer's copy for the
#: other's and reported "lost: ['note 3']" (seed 163907028463129181249818252614244187632 of
#: test_two_computers_many_histories); note 3 was in the kept copy all along. After each step: (mode,
#: notes, kept copies opened directly) of A, then of B; mode ``None`` at the end, where both computers
#: reach the same epoch and their random computer ids settle which one is in use.
_SAME_MINUTE_CHOICES = {
    "B's copy kept first": [
        # A: "Use Ordnung here"; B hasn't seen the claim yet, so both work at once.
        ("use_here", {"which": _A, "older": False}, ("in_use", [], []), ("in_use", [], [])),
        ("person_edit", {"which": _A}, ("in_use", ["note 1"], []), ("in_use", [], [])),
        ("person_edit", {"which": _B}, ("in_use", ["note 1"], []), ("in_use", ["note 2"], [])),
        # B sees A's claim, saves its note late and stands by: both computers show the choice.
        ("converge", {}, ("in_use", ["note 1"], []), ("standing_by", ["note 2"], [])),
        # Work goes on on A while the choice waits.
        ("person_edit", {"which": _A}, ("in_use", ["note 1", "note 3"], []), ("standing_by", ["note 2"], [])),
        # On B: keep A's Ordnung. B keeps a copy of note 2 first.
        (
            "choose",
            {"which": _B, "this": False},
            ("in_use", ["note 1", "note 3"], []),
            ("in_use", ["note 1"], [["note 2"]]),
        ),
        # On A, before B's answer arrived: keep B's. A keeps a copy of notes 1 and 3 first.
        (
            "choose",
            {"which": _A, "this": False},
            ("in_use", ["note 2"], [["note 1", "note 3"]]),
            ("in_use", ["note 1"], [["note 2"]]),
        ),
        # Both answers arrive; they contradict each other (checked after the loop).
        ("converge", {}, (None, ["note 2"], [["note 1", "note 3"]]), (None, ["note 1"], [["note 2"]])),
    ],
    "A's copy kept first": [
        ("use_here", {"which": _A, "older": False}, ("in_use", [], []), ("in_use", [], [])),
        ("converge", {}, ("in_use", [], []), ("standing_by", [], [])),
        ("use_here", {"which": _B, "older": False}, ("in_use", [], []), ("in_use", [], [])),
        ("person_edit", {"which": _B}, ("in_use", [], []), ("in_use", ["note 1"], [])),
        ("person_edit", {"which": _A}, ("in_use", ["note 2"], []), ("in_use", ["note 1"], [])),
        ("converge", {}, ("standing_by", ["note 2"], []), ("in_use", ["note 1"], [])),
        ("person_edit", {"which": _B}, ("standing_by", ["note 2"], []), ("in_use", ["note 1", "note 3"], [])),
        (
            "choose",
            {"which": _A, "this": False},
            ("in_use", ["note 1"], [["note 2"]]),
            ("in_use", ["note 1", "note 3"], []),
        ),
        (
            "choose",
            {"which": _B, "this": False},
            ("in_use", ["note 1"], [["note 2"]]),
            ("in_use", ["note 2"], [["note 1", "note 3"]]),
        ),
        ("converge", {}, (None, ["note 1"], [["note 2"]]), (None, ["note 2"], [["note 1", "note 3"]])),
    ],
}


def _opened(computer: Computer) -> list[list[str]]:
    """The notes in each of ``computer``'s kept copies, each opened afresh (nothing remembered)."""
    found = []
    for path in computer.s.local.kept_files():
        target = Path(tempfile.mkdtemp(dir=computer.root)) / "restored"
        restore_backup(path, PASSPHRASE, target)
        with Store.open(Paths(target)) as copy:
            found.append(sorted(r["text"] for r in copy._conn().execute("SELECT text FROM notes")))
    return found


@pytest.mark.parametrize("history", list(_SAME_MINUTE_CHOICES))
def test_kept_copies_of_the_same_minute_on_both_computers_are_each_counted(history: str) -> None:
    model = TwoComputers()
    try:
        for number, (rule_name, args, want_a, want_b) in enumerate(_SAME_MINUTE_CHOICES[history], 1):
            getattr(model, rule_name)(**args)
            for computer, want in ((model.a, want_a), (model.b, want_b)):
                got = (computer.mode if want[0] else None, sorted(computer.notes()), _opened(computer))
                assert got == want, f"step {number} ({rule_name}) on {computer.name}"
            model.nothing_lost()
        # Both kept copies have one name, each in its own computer's folder.
        names = [[path.name for path in c.s.local.kept_files()] for c in (model.a, model.b)]
        assert names[0] == names[1] and len(names[0]) == 1
        # The answers contradict each other: one computer is in use and puts the choice to the person again.
        assert sorted((model.a.mode, model.b.mode)) == ["in_use", "standing_by"]
        in_use = model.a if model.a.mode == "in_use" else model.b
        assert isinstance(engine_module.decide(in_use.s.local_view(in_use.db), in_use.s.scan()), Choice)
    finally:
        model.teardown()
