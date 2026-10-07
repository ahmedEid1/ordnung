"""F8: a process applying a pull is killed (SIGKILL) at random moments; every restart finds a usable data
folder (I1) holding either the old data, or the new data with ``sync_mark`` naming it — never a mix —
and finishing the pull brings the rest (design §23.3; slow: 200 kills)."""

from __future__ import annotations

import os
import random
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fakes import use_fast_keys
from ordnung.config import Paths
from ordnung.sync import SYNC_MARK_KEY
from ordnung.sync.engine import resume_interrupted
from sync_harness import PASSPHRASE, Computer
from sync_sim import SyncToolSim

ROOT = Path(__file__).resolve().parents[1]
CHILD = Path(__file__).with_name("sync_pull_child.py")

pytestmark = pytest.mark.slow


def _template(tmp: Path, patch: pytest.MonkeyPatch) -> tuple[Path, str, str, str]:
    use_fast_keys(patch)
    work = tmp / "work"
    a = Computer("anna-laptop", work / "a", work / "a-sync")
    b = Computer("desktop", work / "b", work / "b-sync")
    sim = SyncToolSim(a.folder, b.folder)
    a.add_letter("first")
    a.connect()
    sim.settle()
    b.connect()
    sim.settle()
    a.round()
    a.use_here()
    sim.settle()
    b.round()
    for i in range(30):
        a.add_letter(f"letter {i}", size=40_000)
    a.person_edit("the newest note")
    a.round()
    sim.settle()
    target = a.s.state.base.ref.id.key()  # type: ignore[union-attr]
    old_mark = b.db.get_meta(SYNC_MARK_KEY) or ""
    machine = b.machine
    a.close()
    b.close()
    template = tmp / "template"
    shutil.copytree(work, template, symlinks=True)
    return template, machine, target, old_mark


def test_kill_during_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    template, machine, target, old_mark = _template(tmp_path, monkeypatch)
    work = tmp_path / "work"
    data = work / "b" / "data"
    rng = random.Random(8)
    env = {
        **os.environ,
        "PYTHONPATH": f"{ROOT / 'src'}{os.pathsep}{ROOT}{os.pathsep}{ROOT / 'tests'}",
        "ORDNUNG_SYNC_PASSPHRASE": PASSPHRASE,
    }

    def launch() -> subprocess.Popen[str]:
        shutil.rmtree(work)
        shutil.copytree(template, work, symlinks=True)
        child = subprocess.Popen(
            [sys.executable, str(CHILD), str(work / "b"), machine], env=env, stdout=subprocess.PIPE, text=True
        )
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        return child

    # a run left alone: how long the take-over takes, so the kills spread over all of it
    child = launch()
    started = time.monotonic()
    assert child.stdout is not None and child.stdout.readline().strip() == "done"
    span = time.monotonic() - started
    assert child.wait() == 0
    conn = sqlite3.connect(f"{(data / 'ordnung.db').resolve().as_uri()}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT value FROM meta WHERE key = ?", (SYNC_MARK_KEY,)).fetchone()[0] == target
    finally:
        conn.close()
    outcomes = {"old": 0, "new": 0}
    for _run in range(200):
        child = launch()
        time.sleep(rng.uniform(0, span * 1.2))
        child.send_signal(signal.SIGKILL)
        child.wait()
        conn = sqlite3.connect(f"{(data / 'ordnung.db').resolve().as_uri()}?mode=ro", uri=True)
        try:
            assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            mark = conn.execute("SELECT value FROM meta WHERE key = ?", (SYNC_MARK_KEY,)).fetchone()[0]
            notes = {row[0] for row in conn.execute("SELECT text FROM notes")}
            for (path,) in conn.execute("SELECT file_path FROM documents UNION SELECT image_path FROM pages"):
                assert (data / path).is_file(), path
        finally:
            conn.close()
        assert mark in (old_mark, target)
        assert ("the newest note" in notes) == (mark == target)  # the old database or the new one, whole
        outcomes["new" if mark == target else "old"] += 1
        result = resume_interrupted(Paths(data))
        assert result.outcome in ("nothing", "finished", "discarded"), result
    assert outcomes["old"] and outcomes["new"], outcomes
