"""Crashes and power cuts in the middle of a push, a pull and a claim (design §3, §10.4, §11.5; F1-F10,
F29, F30; acceptance checks 2-3).

Each case starts from the same template (two computers, a letter, A in use with unsaved changes), copied
back into place, so the data folders keep their paths. A crash is a :class:`sync_faults.SimulatedCrash`
at a chosen file operation or byte; a power cut also throws away whatever never reached the disk
(:class:`sync_faults.PowerCutFs`). After each, the computer restarts from disk — the pull journal
resumed, :meth:`Session.start`, one round — and the invariants are checked: I1 (the data folder is
usable: ``integrity_check`` and every stored path), I3 (no change of the person's is lost), I4 (a head
never names a version that isn't whole) and I5 (per-computer state is never overwritten).
"""

from __future__ import annotations

import os
import random
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from fakes import use_fast_keys
from ordnung.db.store import Store
from ordnung.sync import SYNC_MARK_KEY, SyncError
from ordnung.sync.folder import FsOps, RealFs
from sync_faults import CrashingFs, FullFs, PowerCutFs, SimulatedCrash
from sync_harness import Computer, FakeClock
from sync_sim import SyncToolSim, listing


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)


class Scene:
    """The template: A in use with a letter and unsaved changes; B standing by, up to date."""

    def __init__(self, tmp: Path) -> None:
        self.work = tmp / "work"
        self.template = tmp / "template"
        a = Computer("anna-laptop", self.work / "a", self.work / "a-sync")
        b = Computer("desktop", self.work / "b", self.work / "b-sync")
        sim = SyncToolSim(a.folder, b.folder, random.Random(0))
        a.add_letter("first")
        a.connect()
        sim.settle()
        b.connect()
        sim.settle()
        a.round()
        a.use_here()
        sim.settle()
        b.round()
        b.db.set_meta("inbox_seen", '["b-only"]')  # per-computer state of B (I5)
        self.pending_letter = a.add_letter("unsaved letter")
        a.person_edit("unsaved note")
        self.secrets = {"a": dict(a.secrets.saved), "b": dict(b.secrets.saved)}
        self.machines = {"a": a.machine, "b": b.machine}
        a.close()
        b.close()
        shutil.copytree(self.work, self.template, symlinks=True)

    def fresh(self, template: Path | None = None, **fs: FsOps) -> tuple[Computer, Computer, SyncToolSim]:
        shutil.rmtree(self.work)
        shutil.copytree(template or self.template, self.work, symlinks=True)

        computers = []
        for key, name in (("a", "anna-laptop"), ("b", "desktop")):
            computer = Computer(
                name,
                self.work / key,
                self.work / f"{key}-sync",
                clock=FakeClock(),
                machine=self.machines[key],
            )
            computer.secrets.saved.update(self.secrets[key])
            computer.restart(
                folder_fs=fs.get(f"{key}_folder", RealFs()), data_fs=fs.get(f"{key}_data", RealFs())
            )
            computers.append(computer)
        sim = SyncToolSim(computers[0].folder, computers[1].folder, random.Random(0))
        sim.known = {"a": listing(computers[0].folder), "b": listing(computers[1].folder)}
        return computers[0], computers[1], sim


def use(computer: Computer, fs: FsOps) -> None:
    """From now on every file operation of ``computer``'s sync goes through ``fs``."""
    session = computer.s
    session.folder.fs = fs
    session.data_fs = fs
    session.local.fs = fs


def check_i1(computer: Computer) -> None:
    conn = sqlite3.connect(f"{computer.paths.db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        for (path,) in conn.execute("SELECT file_path FROM documents UNION SELECT image_path FROM pages"):
            assert (computer.paths.data_dir / path).is_file(), path
    finally:
        conn.close()


def check_i4(computer: Computer) -> None:
    """Every head in this computer's view of the folder names a version that is whole."""
    view = computer.s.scan()
    for head in view.heads:
        version = head.head.version
        if version is not None and head.readable:
            assert computer.s.scanner.completeness(version, {}).ready, (
                f"{head.head.name}'s head names a partial version"
            )


@pytest.fixture(scope="module")
def scene(tmp_path_factory: pytest.TempPathFactory) -> Scene:
    patch = pytest.MonkeyPatch()
    use_fast_keys(patch)
    made = Scene(tmp_path_factory.mktemp("crash"))
    patch.undo()
    return made


def finish_push_and_hand_over(scene: Scene, a: Computer, b: Computer, sim: SyncToolSim) -> None:
    """After A's restart: one round saves what is pending; B then takes over and has all of it (I3)."""
    a.round()
    a.round()
    sim.settle()
    b.round()
    outcome = b.use_here()
    assert b.mode == "in_use", outcome
    assert scene.pending_letter in b.letters() and "unsaved note" in b.notes()
    check_i1(b)


def finish_push(scene: Scene, a: Computer) -> None:
    """After A's restart: one round saves what is pending, and its head names a whole version (the
    lighter check; every fifth case hands over to B as well)."""
    a.round()
    check_i4(a)
    assert a.s.state.base is not None and a.s.scanner.completeness(a.s.state.base.ref, {}).ready
    assert scene.pending_letter in a.letters() and not a.s.pending(a.db)


def count(operation: Any) -> CrashingFs:
    """A dry run: how many operations and bytes ``operation`` makes."""
    counter = CrashingFs()
    operation(counter)
    return counter


# --------------------------------------------------------------------------------------------------
# push (F1-F4, F30)
# --------------------------------------------------------------------------------------------------


def _push(scene: Scene, crash: CrashingFs) -> tuple[Computer, Computer, SyncToolSim, bool]:
    a, b, sim = scene.fresh()
    use(a, crash)
    try:
        a.s.push(a.db)
        done = True
    except SimulatedCrash:
        done = False
    return a, b, sim, done


def test_push_crash_at_every_operation(scene: Scene) -> None:  # F1, F2, F3
    def dry(fs: CrashingFs) -> None:
        a, b, _sim = scene.fresh()
        use(a, fs)
        a.s.push(a.db)
        a.close()
        b.close()

    total = count(dry)
    assert total.ops > 10
    for k in range(total.ops + 1):
        a, b, sim, _done = _push(scene, CrashingFs(after_ops=k))
        try:
            a.restart()
            check_i1(a)
            check_i4(a)
            assert scene.pending_letter in a.letters() and "unsaved note" in a.notes()
            if k % 5 == 0 or k == total.ops:
                finish_push_and_hand_over(scene, a, b, sim)
            else:
                finish_push(scene, a)
            leftovers = [p for p in a.folder.rglob(f".{a.s.folder.tag}*.tmp")]
            assert not leftovers, leftovers  # its own temp files go at the next push (I7)
        finally:
            a.close()
            b.close()


def test_push_crash_at_sampled_bytes(scene: Scene) -> None:  # F1
    def dry(fs: CrashingFs) -> None:
        a, b, _sim = scene.fresh()
        use(a, fs)
        a.s.push(a.db)
        a.close()
        b.close()

    total = count(dry)
    rng = random.Random(3)
    for offset in sorted({0, 1, 22, 23, 24, total.bytes - 1, *rng.sample(range(total.bytes), 6)}):
        a, b, sim, _done = _push(scene, CrashingFs(after_bytes=offset))
        try:
            a.restart()
            check_i1(a)
            check_i4(a)
            finish_push_and_hand_over(scene, a, b, sim)
        finally:
            a.close()
            b.close()


def test_push_power_cut(scene: Scene) -> None:  # F4: a head is never durable without its objects
    def dry(fs: CrashingFs) -> None:
        a, b, _sim = scene.fresh()
        use(a, fs)
        a.s.push(a.db)
        a.close()
        b.close()

    total = count(dry)
    for k in range(0, total.ops + 1, max(1, total.ops // 12)):
        a, b, sim = scene.fresh()
        power = PowerCutFs([a.folder, a.paths.data_dir])
        crash = CrashingFs(after_ops=k, inner=power)
        use(a, crash)
        try:
            a.s.push(a.db)
        except SimulatedCrash:
            pass
        a.close()
        power.cut()
        try:
            a.restart()
            check_i1(a)
            check_i4(a)
            finish_push_and_hand_over(scene, a, b, sim)
        finally:
            a.close()
            b.close()


def test_push_folder_full(scene: Scene) -> None:  # F30
    a, b, sim = scene.fresh()
    try:
        use(a, FullFs(after_bytes=2000))
        with pytest.raises(SyncError):
            a.s.push(a.db)
        written = a.s.state.written
        use(a, RealFs())
        assert a.s.state.written == written
        a.restart()
        finish_push_and_hand_over(scene, a, b, sim)
    finally:
        a.close()
        b.close()


# --------------------------------------------------------------------------------------------------
# pull and claim (F5-F9, F29)
# --------------------------------------------------------------------------------------------------


def _pull_scene(scene: Scene, **fs: FsOps) -> tuple[Computer, Computer, SyncToolSim]:
    """A saved its changes and B saw them (made once, then copied back into place)."""
    template = scene.template.with_name("template-pull")
    if not template.exists():
        a, b, sim = scene.fresh()
        a.round()  # A saves its changes
        sim.settle()
        b.round()
        a.close()
        b.close()
        shutil.copytree(scene.work, template, symlinks=True)
    return scene.fresh(template, **fs)


def test_pull_crash_at_every_operation(scene: Scene) -> None:  # F5, F7, F9
    def dry(fs: CrashingFs) -> None:
        a, b, _sim = _pull_scene(scene)
        use(b, fs)
        b.use_here()
        a.close()
        b.close()

    total = count(dry)
    assert total.ops > 10
    for k in range(total.ops + 1):
        a, b, _sim = _pull_scene(scene)
        use(b, CrashingFs(after_ops=k))
        try:
            try:
                b.use_here()
            except SimulatedCrash:
                pass
            b.restart()  # resumes a journal, discards a staging
            check_i1(b)
            assert b.db.get_meta("inbox_seen") == '["b-only"]'  # I5
            if b.mode != "in_use":
                b.use_here()
            assert b.mode == "in_use"
            assert scene.pending_letter in b.letters() and "unsaved note" in b.notes()
            check_i1(b)
            assert not (b.paths.data_dir / "sync" / "incoming").exists()
            assert not (b.paths.data_dir / "sync" / "pull.json").exists()
        finally:
            a.close()
            b.close()


def test_pull_power_cut(scene: Scene) -> None:
    def dry(fs: CrashingFs) -> None:
        a, b, _sim = _pull_scene(scene)
        use(b, fs)
        b.use_here()
        a.close()
        b.close()

    total = count(dry)
    for k in range(0, total.ops + 1, max(1, total.ops // 12)):
        a, b, _sim = _pull_scene(scene)
        power = PowerCutFs([b.paths.data_dir])
        use(b, CrashingFs(after_ops=k, inner=power))
        try:
            try:
                b.use_here()
            except SimulatedCrash:
                pass
            b.close()
            power.cut()
            b.restart()
            check_i1(b)
            if b.mode != "in_use":
                b.use_here()
            assert scene.pending_letter in b.letters() and "unsaved note" in b.notes()
        finally:
            a.close()
            b.close()


def test_kill_during_the_database_apply_keeps_one_database(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:  # F8 (in process)
    a, b, _sim = _pull_scene(scene)
    try:
        real = Store.replace_with

        def interrupted(self: Store, staged: Path, merge: Any, **_options: Any) -> None:
            calls = {"n": 0}

            def progress(_status: int, _remaining: int, _total: int) -> None:
                calls["n"] += 1
                raise SimulatedCrash("killed inside the backup")

            real(self, staged, merge, pages=1, progress=progress)

        monkeypatch.setattr(Store, "replace_with", interrupted)
        with pytest.raises(SimulatedCrash):
            b.use_here()
        monkeypatch.undo()
        use_fast_keys(monkeypatch)
        check_i1(b)
        assert scene.pending_letter not in b.letters()  # the old database, whole
        b.restart()  # the journal finishes the pull
        assert scene.pending_letter in b.letters() and "unsaved note" in b.notes()
        check_i1(b)
    finally:
        a.close()
        b.close()


def test_a_crash_while_keeping_a_copy(scene: Scene, monkeypatch: pytest.MonkeyPatch) -> None:  # F6
    a, b, sim = scene.fresh()
    try:
        a.delete_letter(next(x for x in a.letters() if x != scene.pending_letter))
        a.round()
        sim.settle()
        b.round()
        from ordnung.sync import kept

        def crash(data_dir: Path, target: Path, passphrase: str, **_kw: Any) -> None:
            partial = target.with_name(f".{target.name}.{os.getpid()}.part")
            partial.write_bytes(b"half a backup")
            raise SimulatedCrash("killed while keeping")

        monkeypatch.setattr(kept, "write_backup_file", crash)
        before = b.letters()
        with pytest.raises(SimulatedCrash):
            b.use_here()
        monkeypatch.undo()
        use_fast_keys(monkeypatch)
        assert b.letters() == before
        b.restart()
        assert not list((b.paths.data_dir / "sync" / "kept").glob(".*.part"))
        outcome = b.use_here()
        assert outcome.kept is not None and scene.pending_letter in b.letters()
    finally:
        a.close()
        b.close()


def test_pull_disk_full_leaves_everything_as_it_was(scene: Scene) -> None:  # F29
    a, b, _sim = _pull_scene(scene)
    try:
        before = b.letters()
        use(b, FullFs(after_bytes=4000))
        with pytest.raises((OSError, SyncError)):
            b.use_here()
        use(b, RealFs())
        assert b.letters() == before and b.mode == "standing_by"
        assert not (b.paths.data_dir / "sync" / "incoming").exists()
        check_i1(b)
        b.use_here()
        assert scene.pending_letter in b.letters()
    finally:
        a.close()
        b.close()


def test_claim_crash_at_every_operation(scene: Scene) -> None:
    def dry(fs: CrashingFs) -> None:
        a, b, _sim = _pull_scene(scene)
        b.use_here()
        use(b, fs)
        b.s.claim(b.db)
        a.close()
        b.close()

    total = count(dry)
    for k in range(total.ops + 1):
        a, b, sim = _pull_scene(scene)
        try:
            b.use_here()
            use(b, CrashingFs(after_ops=k))
            try:
                b.s.claim(b.db)
            except SimulatedCrash:
                pass
            b.restart()
            check_i1(b)
            b.round()
            sim.settle()
            a.round()
            assert {a.mode, b.mode} == {"in_use", "standing_by"}
        finally:
            a.close()
            b.close()


# --------------------------------------------------------------------------------------------------
# the local database went back in time (F10)
# --------------------------------------------------------------------------------------------------


def test_local_rollback_restored(scene: Scene) -> None:  # F10
    a, b, _sim = scene.fresh()
    try:
        a.close()
        saved = a.paths.db.read_bytes()
        a.restart()
        a.round()  # pushes the unsaved changes
        a.person_edit("after the backup")
        a.round()
        a.close()
        a.paths.db.write_bytes(saved)  # the disk lost what was committed after
        for suffix in ("-wal", "-shm"):
            Path(str(a.paths.db) + suffix).unlink(missing_ok=True)
        problem = a.restart()
        assert problem is not None and problem.code == "local_rollback"
        outcome = a.s.repair_rollback(a.db)
        assert (
            outcome.kept is not None and outcome.notice is not None and outcome.notice.code == "rolled_back"
        )
        assert scene.pending_letter in a.letters() and "unsaved note" in a.notes()
        assert "after the backup" in a.notes()
        check_i1(a)
    finally:
        a.close()
        b.close()


def test_a_database_that_holds_the_heads_version_is_adopted(scene: Scene) -> None:  # F3
    """Put back from a copy taken before the push, but holding exactly what the head names (the process
    died between the head and ``sync_mark``): nothing to repair, the head is adopted."""
    a, b, _sim = scene.fresh()
    try:
        a.close()
        saved = a.paths.db.read_bytes()
        a.restart()
        a.round()
        a.close()
        a.paths.db.write_bytes(saved)
        for suffix in ("-wal", "-shm"):
            Path(str(a.paths.db) + suffix).unlink(missing_ok=True)
        assert a.restart() is None
        assert a.s.state.base is not None and a.db.get_meta(SYNC_MARK_KEY) == a.s.state.base.ref.id.key()
        assert not a.s.pending(a.db)
    finally:
        a.close()
        b.close()
