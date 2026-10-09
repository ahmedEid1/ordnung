"""Hand-off sync: regression tests for the review of the merged phone companion and sync (each test fails
without its fix). Two data folders and a simulated sync tool (:mod:`sync_harness`), or running servers
with the real engine (:mod:`sync_support`)."""

from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from fakes import use_fast_keys
from ordnung.backup import restore_backup
from ordnung.config import Paths
from ordnung.db.store import Store, person_write
from ordnung.sync import SyncError, engine
from ordnung.sync.decide import Choice, Paused
from ordnung.sync.local import machine_id
from sync_faults import copy_tree
from sync_harness import PASSPHRASE, Computer
from sync_sim import SyncToolSim


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)


class Pair:
    def __init__(self, tmp: Path) -> None:
        self.a = Computer("anna-laptop", tmp / "a", tmp / "a-sync")
        self.b = Computer("desktop", tmp / "b", tmp / "b-sync")
        self.sim = SyncToolSim(self.a.folder, self.b.folder, random.Random(1))

    def settle(self) -> None:
        self.sim.settle()

    def close(self) -> None:
        self.a.close()
        self.b.close()

    def joined(self) -> None:
        """A set up with a letter; B joined; then A is in use again and B stands by, up to date."""
        a, b = self.a, self.b
        a.add_letter("Stadtwerke Abschlag 2027")
        a.connect()
        self.settle()
        assert b.connect().connected
        self.settle()
        a.round()
        a.use_here()
        a.round()
        self.settle()
        b.round()
        self.settle()
        assert a.mode == "in_use" and b.mode == "standing_by"


@pytest.fixture
def pair(tmp_path: Path):  # type: ignore[no-untyped-def]
    made = Pair(tmp_path)
    yield made
    made.close()


def _two_saves_after_a_backup(pair: Pair, backup: Path) -> None:
    """A (in use) is copied away by an OS backup, then saves E1 and E2; B receives them."""
    a, b = pair.a, pair.b
    a.close()
    copy_tree(a.paths.data_dir, backup)
    a.restart()
    a.person_edit("E1 before the restore")
    a.round()
    a.person_edit("E2 before the restore")
    a.round()
    pair.settle()
    b.round()
    pair.settle()


def _kept_notes(computer: Computer, name: str, target: Path) -> set[str]:
    restore_backup(computer.s.local.kept_dir / name, PASSPHRASE, target)
    with Store.open(Paths(target)) as copy:
        return {row["text"] for row in copy._conn().execute("SELECT text FROM notes")}


def test_a_restored_data_folder_started_while_the_sync_folder_is_away(pair: Pair, tmp_path: Path) -> None:
    """Blocker 4 again: the start waits until the folder shows this computer's own head — never the
    counters and the rollback check from the restored ``sync/heads.json`` alone."""
    a, b = pair.a, pair.b
    pair.joined()
    _two_saves_after_a_backup(pair, tmp_path / "os-backup")
    seq, pnum, written = a.s.state.seq, a.s.state.pnum, a.s.state.written
    a.close()
    copy_tree(tmp_path / "os-backup", a.paths.data_dir)
    os.rename(a.folder, tmp_path / "away")  # the share isn't mounted yet

    problem = a.restart()
    assert problem is not None and problem.code == "folder_missing"
    assert not a.s.started
    paused = a.round().decision
    assert isinstance(paused, Paused) and paused.problem.code == "folder_missing"
    a.person_edit("E3 typed while the folder was away")
    with pytest.raises(SyncError):
        a.s.push(a.db)  # nothing is saved from counters the folder hasn't confirmed

    os.rename(tmp_path / "away", a.folder)  # the folder is back: the start completes now
    paused = a.round().decision
    assert isinstance(paused, Paused) and paused.problem.code == "local_rollback"
    assert (a.s.state.seq, a.s.state.pnum, a.s.state.written) >= (seq, pnum, written)
    outcome = a.s.repair_rollback(a.db)
    assert outcome.kept is not None
    assert {"E1 before the restore", "E2 before the restore"} <= a.notes()
    assert "E3 typed while the folder was away" in _kept_notes(a, outcome.kept.name, tmp_path / "kept")

    a.person_edit("E4 after the repair")
    a.round()
    pair.settle()
    b.round()
    taken = b.use_here()
    assert not isinstance(taken.decision, Choice)
    assert {"E1 before the restore", "E2 before the restore", "E4 after the repair"} <= b.notes()


def test_a_command_line_write_after_an_os_backup_is_not_saved_over_the_newer_version(
    pair: Pair, tmp_path: Path
) -> None:
    """Blocker 4 through the command line: ``ordnung add`` saves (``push_once``) only after the start —
    the restored data never goes out under the folder's newer lineage."""
    a, b = pair.a, pair.b
    a.machine = machine_id()  # push_once opens its session as the command line does (this machine)
    pair.joined()
    _two_saves_after_a_backup(pair, tmp_path / "os-backup")
    a.close()
    copy_tree(tmp_path / "os-backup", a.paths.data_dir)
    heads_before = {path.name: path.read_bytes() for path in (a.folder / "h").iterdir()}

    a.store = Store.open(a.paths)
    with person_write():
        a.db.add_note("added with ordnung add")
    said = engine.push_once(a.paths, a.secrets, a.db)
    assert said.startswith("Not saved to the sync folder") and "back in time" in said, said
    assert {path.name: path.read_bytes() for path in (a.folder / "h").iterdir()} == heads_before

    problem = a.restart()  # the server starts: the rollback is found and the last saved state put back
    assert problem is not None and problem.code == "local_rollback"
    outcome = a.s.repair_rollback(a.db)
    assert outcome.kept is not None
    assert "added with ordnung add" in _kept_notes(a, outcome.kept.name, tmp_path / "kept")
    a.person_edit("E3 after the restore")
    a.round()
    pair.settle()
    b.round()
    taken = b.use_here()
    assert not isinstance(taken.decision, Choice)
    assert {"E1 before the restore", "E2 before the restore", "E3 after the restore"} <= b.notes()


# --------------------------------------------------------------------------------------------------
# running servers with the real engine
# --------------------------------------------------------------------------------------------------


def _notes(paths: Paths) -> set[str]:
    with Store.open(paths) as store:
        return {row["text"] for row in store._conn().execute("SELECT text FROM notes")}


async def test_the_automatic_rollback_repair_is_fenced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The repair of a local rollback runs the two phases of any replacement: a write that lands while
    the version to put back is staged is in the kept copy (it used to be in neither)."""
    from ordnung.sync import engine as core
    from sync_support import PASSPHRASE as SERVER_PASSPHRASE
    from sync_support import (
        REAL_ENGINE_TIMINGS,
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
    )

    fast_sync(monkeypatch, **REAL_ENGINE_TIMINGS)
    real = RealEngine()
    (tmp_path / "Nextcloud").mkdir()
    folder, desk = tmp_path / "Nextcloud" / "Vault", tmp_path / "desk"
    async with computer(desk, engine=real) as a:
        await connect(a, folder, "desktop")
        with person_write():
            a.ctx.store.add_note("E1 before the backup")
        await agent_of(a).save()
    copy_tree(desk, tmp_path / "os-backup")
    async with computer(desk, engine=real) as a:
        with person_write():
            a.ctx.store.add_note("E2 after the backup")
        await agent_of(a).save()
    copy_tree(tmp_path / "os-backup", desk)

    staged_once: list[str] = []
    real_stage = core.Session.stage

    def stage_while_the_person_types(self: core.Session, head: object, *, keep: bool = False) -> object:
        staged = real_stage(self, head, keep=keep)  # type: ignore[arg-type]
        if not staged_once:  # a request admitted before the fence commits now
            staged_once.append("typed")
            with Store.open(Paths(desk)) as other, person_write():
                other.add_note("typed while Ordnung was starting")
        return staged

    monkeypatch.setattr(core.Session, "stage", stage_while_the_person_types)
    async with computer(desk, engine=real) as a:
        agent = agent_of(a)
        await eventually(lambda: any(n.code == "rolled_back" for n in agent.status().notices), within=10)
        assert staged_once, "the version to put back was staged"
        found = agent.status()
        assert found.problem is None and found.mode == "in_use"
        notice = next(n for n in found.notices if n.code == "rolled_back")
        assert notice.kept is not None
        live = _notes(a.ctx.paths)
        assert {"E1 before the backup", "E2 after the backup"} <= live
        restore_backup(desk / "sync" / "kept" / notice.kept, SERVER_PASSPHRASE, tmp_path / "kept")
        kept = _notes(Paths(tmp_path / "kept"))
    assert "typed while Ordnung was starting" in live | kept, "a write the server took is never lost"


async def _desktop_in_use_laptop_standing_by(tmp_path: Path, real: object) -> tuple[Path, Path, Path]:
    (tmp_path / "Nextcloud").mkdir()
    return tmp_path / "Nextcloud" / "Vault", tmp_path / "desk", tmp_path / "lap"


def _look_now(agent: object) -> bool:
    """Have the agent's loop look at the folder at its next step (the test's timings never do)."""
    agent._next_scan = 0.0  # type: ignore[attr-defined]
    agent.notify()  # type: ignore[attr-defined]
    return True


@pytest.mark.parametrize("finishes", ["before the fence gives up", "after the fence gave up"])
async def test_a_write_admitted_when_another_computer_takes_over_goes_out_as_a_late_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, finishes: str
) -> None:
    """R3 waits for the writes already admitted (a phone upload, a body still arriving), and one that
    finishes even later is pushed from standing by: the computer in use brings it in (F21)."""
    import asyncio

    from sync_support import (
        REAL_ENGINE_TIMINGS,
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
    )

    late = finishes == "after the fence gave up"
    fast_sync(monkeypatch, **REAL_ENGINE_TIMINGS, FENCE_WAIT_S=0.2 if late else 2.0)
    real = RealEngine()
    folder, desk, lap = await _desktop_in_use_laptop_standing_by(tmp_path, real)
    async with computer(desk, engine=real) as a, computer(lap, engine=real) as b:
        await connect(a, folder, "desktop")
        await connect(b, folder, "laptop")
        await eventually(lambda: agent_of(a).mode == "standing_by", within=10)
        assert (await a.client.post("/api/sync/use-here", json={})).status_code == 200
        await eventually(lambda: agent_of(b).mode == "standing_by", within=10)
        desktop = agent_of(a)
        with desktop.admitted():  # a request the gate let through on the desktop, still running
            taken = await b.client.post("/api/sync/use-here", json={})
            assert taken.status_code == 200 and taken.json()["mode"] == "in_use", taken.text
            await eventually(lambda: desktop.mode == "standing_by", within=10)
            if late:
                await asyncio.sleep(0.6)  # the late save went out without it
            with person_write():
                a.ctx.store.add_note("typed on the desktop as the laptop took over")
        await eventually(
            lambda: "typed on the desktop as the laptop took over" in _notes(b.ctx.paths), within=10
        )
        assert agent_of(b).choice is None, "brought in quietly: nothing changed on the laptop since"


async def test_background_work_a_request_starts_is_never_the_persons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The watched folder, the day change, the weekly review, the phone's address watcher and the check
    for Claude run as background work even when a request of the person's starts them (a settings
    save): their writes never move the person counter (they used to inherit ``PERSON_WRITE``)."""
    import asyncio
    from datetime import date
    from typing import Any

    from fixtures_llm import fake_backend
    from ordnung.app_context import build_context
    from ordnung.db.store import PERSON_WRITE
    from ordnung.ingest.watcher import FolderWatcher
    from ordnung.ingest.worker import IngestWorker
    from ordnung.phone.access import PhoneAccess
    from ordnung.tick import DailyTick

    seen: dict[str, bool] = {}

    def capture(name: str) -> Any:
        async def run(*_args: Any, **_kwargs: Any) -> None:
            seen[name] = PERSON_WRITE.get()

        return lambda *_args, **_kwargs: run()

    monkeypatch.setattr(DailyTick, "run_forever", capture("day change"))
    monkeypatch.setattr(DailyTick, "_run_review", capture("weekly review"))
    monkeypatch.setattr(DailyTick, "_usable_llm", lambda self: object())
    monkeypatch.setattr(DailyTick, "_review_due", lambda self, today: True)
    monkeypatch.setattr(FolderWatcher, "_run", capture("watched folder"))
    monkeypatch.setattr(PhoneAccess, "_watch", capture("phone's address watcher"))
    ctx = build_context(tmp_path / "data", backend_obj=fake_backend())
    try:
        (tmp_path / "Scans").mkdir()
        ctx.store.save_settings({"inbox_dir": str(tmp_path / "Scans"), "llm_review": True})
        ctx.reload_settings()
        tick, watcher = DailyTick(ctx), FolderWatcher(ctx)
        phone = PhoneAccess(ctx, demo=False, token_on=True)
        worker = ctx.worker
        assert isinstance(worker, IngestWorker)
        checks: list[bool] = []

        async def check() -> bool:
            checks.append(PERSON_WRITE.get())
            return False

        with person_write():  # a request of the person's starts them
            tasks: list[Any] = [tick.start()]
            assert tick._start_review(date(2026, 10, 7))
            tasks.append(tick._review)
            await watcher._start_task()
            tasks.append(watcher._task)
            phone._start_watcher()
            tasks.append(phone._watcher)
            worker.claude_check, worker._wake, worker._checked_claude_at = check, asyncio.Event(), None
            worker._check_claude()
            tasks.append(worker._claude_checking)
        await asyncio.gather(*tasks)
        seen["the check for Claude"] = checks == [True]
        assert seen == {
            "day change": False,
            "weekly review": False,
            "watched folder": False,
            "phone's address watcher": False,
            "the check for Claude": False,
        }
    finally:
        ctx.close()


async def test_a_settings_save_of_this_computer_s_own_settings_is_not_a_person_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Critique 14: saving only per-computer settings (notifications, the watched folder) never counts
    as the person's change — with unsaved background work it made a person version (a false choice)."""
    from sync_fake_engine import counter
    from sync_support import computer, connect, fast_sync

    fast_sync(monkeypatch)
    (tmp_path / "Nextcloud").mkdir()
    (tmp_path / "Scans").mkdir()
    async with computer(tmp_path / "desk") as api:
        await connect(api, tmp_path / "Nextcloud" / "Vault", "desktop")
        before = counter(api.ctx.store)
        for local in (
            {"desktop_notifications": "full"},
            {"desktop_notify_time": "07:30", "concurrency": 3},
            {"inbox_dir": str(tmp_path / "Scans")},
        ):
            saved = await api.client.put("/api/settings", json=local)
            assert saved.status_code == 200, saved.text
            assert counter(api.ctx.store) == before, local
        synced = await api.client.put("/api/settings", json={"llm_review": False})
        assert synced.status_code == 200 and counter(api.ctx.store) == before + 1


def test_the_calendar_preview_only_reads(tmp_path: Path) -> None:
    """Finding 5's rule: a standing-by computer's digest never changes — the preview of the calendar
    events used to make the synced ``calendar_uid_key`` (pending changes, a false second confirmation)."""
    from helpers_secretary import TODAY, seed_ledger
    from ordnung import clock
    from ordnung.calendar import caldav

    clock.set_today(TODAY)
    try:
        with Store.open(Paths(tmp_path / "data").ensure()) as store:
            seed_ledger(store)
            writes = store._conn().total_changes
            shown = caldav.preview(store, "discreet")
            assert shown and all(event.uid.endswith("@ordnung.local") for event in shown)
            assert store.get_meta(caldav.UID_KEY_META) is None
            assert store._conn().total_changes == writes, "the preview wrote nothing"
            sent = caldav.build_events(store, "discreet")  # the first sync makes the key that stays
            assert store.get_meta(caldav.UID_KEY_META) and [e.preview.summary for e in sent] == [
                event.summary for event in shown
            ]
    finally:
        clock.set_today(None)


async def test_after_a_save_the_other_computer_has_it_only_once_it_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The top bar's "has it" and the second confirmation of Disconnect and Delete everything are worked
    out against the version just saved (they used to read the last look's, made before the save)."""
    from sync_support import (
        REAL_ENGINE_TIMINGS,
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
    )

    fast_sync(
        monkeypatch, **REAL_ENGINE_TIMINGS, SCAN_S=60.0, WATCH_S=60.0
    )  # no look of its own between the steps below
    real = RealEngine()
    folder, desk, lap = await _desktop_in_use_laptop_standing_by(tmp_path, real)
    async with computer(desk, engine=real) as a:
        desktop = agent_of(a)
        async with computer(lap, engine=real) as b:
            await connect(a, folder, "desktop")
            await connect(b, folder, "laptop")
            await eventually(lambda: _look_now(desktop) and desktop.mode == "standing_by", within=10)
            assert (await a.client.post("/api/sync/use-here", json={})).status_code == 200
            laptop = agent_of(b)

            def caught_up() -> bool:
                _look_now(laptop)
                _look_now(desktop)
                return laptop.mode == "standing_by" and desktop.status().others_have_latest

            await eventually(caught_up, within=10, step=0.1)
        # laptop is off now; desktop saves a change: laptop doesn't have it
        assert (
            await a.client.post("/api/items", json={"kind": "task", "title": "Only here"})
        ).status_code == 201
        await desktop.save()
        shown = desktop.status()
        assert not shown.pending_changes and not shown.others_have_latest
        laptop_row = next(c for c in shown.computers if c.name == "laptop")
        assert laptop_row.has_latest is False
        refused = await a.client.request("DELETE", "/api/sync", json={})
        assert refused.status_code == 409 and refused.json()["code"] == "not_received", refused.text


async def test_leaving_asks_twice_when_its_last_save_made_a_version_no_other_computer_has(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sync_support import (
        REAL_ENGINE_TIMINGS,
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
    )

    fast_sync(monkeypatch, **REAL_ENGINE_TIMINGS, SCAN_S=60.0, WATCH_S=60.0)
    real = RealEngine()
    folder, desk, lap = await _desktop_in_use_laptop_standing_by(tmp_path, real)
    async with computer(desk, engine=real) as a:
        desktop = agent_of(a)
        async with computer(lap, engine=real) as b:
            await connect(a, folder, "desktop")
            await connect(b, folder, "laptop")
            await eventually(lambda: _look_now(desktop) and desktop.mode == "standing_by", within=10)
            assert (await a.client.post("/api/sync/use-here", json={})).status_code == 200
            laptop = agent_of(b)

            def caught_up() -> bool:
                _look_now(laptop)
                _look_now(desktop)
                return laptop.mode == "standing_by" and desktop.status().others_have_latest

            await eventually(caught_up, within=10, step=0.1)
        # a change the agent hasn't seen yet (no commit noticed): the first check passes, the last save
        # before leaving makes a version laptop doesn't have — so it asks after all
        with person_write():
            a.ctx.store.add_note("committed just before Disconnect")
        assert desktop.status().others_have_latest
        refused = await a.client.request("DELETE", "/api/sync", json={})
        assert refused.status_code == 409 and refused.json()["code"] == "not_received", refused.text
        assert desktop.connected and not desktop.fenced
        twice = await a.client.request("DELETE", "/api/sync", json={"unreceived_ok": True})
        assert twice.status_code == 200, twice.text


async def test_a_change_shows_as_unsaved_at_once_and_a_save_s_own_commit_doesn_t(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The top bar hears at once that a change isn't saved yet (it said "Saved · … has it" for the
    seconds before the save), and the save's own bookkeeping commit doesn't make it "not saved" again."""
    import asyncio

    from sync_support import (
        REAL_ENGINE_TIMINGS,
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
    )

    fast_sync(
        monkeypatch, **REAL_ENGINE_TIMINGS, PUSH_PERSON_QUIET_S=30.0, PUSH_QUIET_S=30.0, PUSH_MAX_WAIT_S=60.0
    )
    (tmp_path / "Nextcloud").mkdir()
    async with computer(tmp_path / "desk", engine=RealEngine()) as api:
        await connect(api, tmp_path / "Nextcloud" / "Vault", "desktop")
        agent = agent_of(api)
        assert (
            await api.client.post("/api/items", json={"kind": "task", "title": "Rent"})
        ).status_code == 201
        await agent.save()
        await asyncio.sleep(0.3)  # several of the loop's looks at the database
        assert not agent.status().pending_changes, "the save's own commit is no change"
        heard: list[bool] = []
        publish = api.ctx.bus.publish

        def record(kind: str, **data: object) -> None:
            if kind == "sync.updated":
                heard.append(agent.status().pending_changes)
            publish(kind, **data)

        monkeypatch.setattr(api.ctx.bus, "publish", record)
        added = await api.client.post("/api/items", json={"kind": "task", "title": "Pay the gym"})
        assert added.status_code == 201
        assert heard and heard[-1] is True, "said as the request finished, not at the next save"
        await agent.save()
        await asyncio.sleep(0.3)
        assert not agent.status().pending_changes
        await eventually(lambda: heard[-1] is False)


async def test_kept_copies_stay_listed_after_disconnect_and_after_setting_sync_up_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disconnect leaves the kept copies on disk; the app and ``ordnung sync kept`` still find, download
    and delete them (they used to vanish from every list with ``state.json``)."""
    import asyncio

    from ordnung.sync import KEPT_DIR
    from sync_support import REAL_ENGINE_TIMINGS, RealEngine, agent_of, computer, connect, fast_sync, status

    fast_sync(monkeypatch, **REAL_ENGINE_TIMINGS)
    real = RealEngine()
    (tmp_path / "Nextcloud").mkdir()
    desk = tmp_path / "desk"
    async with computer(desk, engine=real) as api:
        await connect(api, tmp_path / "Nextcloud" / "Vault", "desktop")
        live = real._session_of(api.ctx.paths)
        assert live is not None
        first = await asyncio.to_thread(live.inner.keep_local, "before you kept laptop's Ordnung")
        second = await asyncio.to_thread(live.inner.keep_local, "before you used laptop's Ordnung here")
        await agent_of(api).save()
        await agent_of(api)._refresh_summary()
        assert {k["name"] for k in (await status(api))["kept"]} == {first.name, second.name}

        left = await api.client.request("DELETE", "/api/sync", json={"unreceived_ok": True})
        assert left.status_code == 200, left.text
        shown = left.json()
        assert shown["connected"] is False
        assert {(k["name"], k["why"]) for k in shown["kept"]} == {
            (first.name, "before you kept laptop's Ordnung"),
            (second.name, "before you used laptop's Ordnung here"),
        }
        download = await api.client.get(f"/api/sync/kept/{first.name}")
        assert download.status_code == 200 and download.content.startswith(b"ORDNUNG")
        assert (await api.client.delete(f"/api/sync/kept/{second.name}")).status_code == 204
        assert [k["name"] for k in (await status(api))["kept"]] == [first.name]
        assert not (desk / "sync" / KEPT_DIR / second.name).exists()

    async with computer(desk, engine=real) as api:  # Ordnung starts again, not syncing
        assert [k["name"] for k in (await status(api))["kept"]] == [first.name]
        await connect(api, tmp_path / "Nextcloud" / "Another", "desktop")  # set up again
        assert [k["name"] for k in (await status(api))["kept"]] == [first.name]


async def test_the_two_sides_of_a_choice_tell_their_to_dos_and_latest_changes_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both computers changed only to-dos (no new letter): each side says its open and done to-dos and
    its latest changes, so the person doesn't choose blind (both used to read "1 letter: …")."""
    from sync_support import (
        REAL_ENGINE_TIMINGS,
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
        status,
    )
    from test_sync_real_engine import _catch_up

    fast_sync(monkeypatch, **REAL_ENGINE_TIMINGS)
    real = RealEngine()
    here, there = tmp_path / "desk-view" / "Vault", tmp_path / "lap-view" / "Vault"
    here.parent.mkdir()
    there.parent.mkdir()
    async with (
        computer(tmp_path / "desk", engine=real) as a,
        computer(tmp_path / "lap", engine=real) as b,
    ):
        await connect(a, here, "desktop")
        made = await a.client.post("/api/items", json={"kind": "task", "title": "Common to-do"})
        assert made.status_code == 201
        await agent_of(a).save()
        there.mkdir()
        _catch_up(here, there)
        await connect(b, there, "laptop")
        common = made.json()["id"]
        done = await a.client.patch(f"/api/items/{common}", json={"status": "done"})
        assert done.status_code == 200, done.text
        assert (
            await a.client.post("/api/items", json={"kind": "task", "title": "Call the landlord"})
        ).status_code == 201
        assert (
            await b.client.post("/api/items", json={"kind": "task", "title": "Renew the passport"})
        ).status_code == 201
        await agent_of(a).save()
        await agent_of(b).save()
        _catch_up(here, there)
        _catch_up(there, here)
        await eventually(lambda: agent_of(b).choice is not None, within=10)
        sides = {side["computer"]: side for side in (await status(b))["choice"]["sides"]}
        mine, theirs = sides["laptop"], sides["desktop"]
        assert mine["this"] and (mine["items"], mine["done"]) == (2, 0)
        assert (theirs["items"], theirs["done"]) == (1, 1)
        assert mine["latest"][0] == {
            "kind": "to-do",
            "label": "Renew the passport",
            "on": mine["latest"][0]["on"],
        }
        assert {change["label"] for change in theirs["latest"]} >= {"Call the landlord", "Common to-do"}
        assert theirs["saved_at"] is not None and mine["saved_at"] is None


# --------------------------------------------------------------------------------------------------
# the sync folder's layout: a folder that is a link is never gone through
# --------------------------------------------------------------------------------------------------


def _outside(tmp_path: Path) -> Path:
    outside = tmp_path / "home-anna-Documents"
    outside.mkdir()
    (outside / "tax-2025.pdf").write_bytes(b"%PDF the person's own file")
    return outside


def test_objects_are_never_written_through_a_linked_o(tmp_path: Path) -> None:
    """Design §4.1 ("symlinks are ignored"), for folders too: someone who can write the sync folder turns
    ``o/`` into a link to the person's Documents — the next save writes nothing there."""
    import shutil

    from sync_harness import computers

    outside = _outside(tmp_path)
    with computers(tmp_path, "anna") as (a,):
        a.connect()
        a.add_letter("first")
        a.round()
        shutil.move(str(a.folder / "o"), tmp_path / "o-moved")
        os.symlink(outside, a.folder / "o")
        a.add_letter("second")
        with pytest.raises(SyncError):
            a.s.push(a.db)
        assert sorted(path.name for path in outside.rglob("*")) == ["tax-2025.pdf"]


def test_a_head_is_never_written_through_a_linked_h(tmp_path: Path) -> None:
    import shutil

    from sync_harness import computers

    outside = _outside(tmp_path)
    with computers(tmp_path, "anna") as (a,):
        a.connect()
        a.round()
        heads = tmp_path / "heads-moved"
        shutil.move(str(a.folder / "h"), heads)
        os.symlink(outside, a.folder / "h")
        a.person_edit("a new note")
        with pytest.raises(SyncError):
            a.s.push(a.db)
        assert sorted(path.name for path in outside.iterdir()) == ["tax-2025.pdf"]


def test_gc_never_deletes_through_a_linked_shard(tmp_path: Path) -> None:
    """A shard ``o/<xx>`` turned into a link to another vault's shard: nine days of GC delete nothing
    there (they used to delete that vault's objects)."""
    import shutil

    from sync_harness import computers

    with computers(tmp_path, "anna", "other") as (a, other):
        other.connect()
        other.add_letter("kept elsewhere")
        other.round()
        victim = sorted(path for path in (other.folder / "o").iterdir() if path.is_dir())[0]
        before = sorted(path.name for path in victim.iterdir())
        a.connect()
        a.add_letter("first")
        a.round()
        link = a.folder / "o" / victim.name
        if link.exists():
            shutil.rmtree(link)
        os.symlink(victim, link)
        for _ in range(9):
            a.clock.advance(86_400.0)
            a.s.scan()
            a.s.gc()
            a.s.folder.remove_temps()
        assert sorted(path.name for path in victim.iterdir()) == before


def test_the_suggested_sync_folder_name_doesn_t_say_which_app_wrote_it(tmp_path: Path) -> None:
    """The provider sees the folder's name: Ordnung's suggestions are neutral ("Vault"), never "Ordnung"."""
    from ordnung.sync.folder import folder_problem

    paths = Paths(tmp_path / "data").ensure()
    relative = folder_problem("Nextcloud/x", paths)
    assert relative is not None and relative.endswith("/home/you/Nextcloud/Vault.")
    taken = tmp_path / "Nextcloud" / "Shared"
    taken.mkdir(parents=True)
    (taken / "notes.txt").write_text("the person's own file")
    crowded = folder_problem(str(taken), paths)
    assert crowded is not None and crowded.endswith(f"like {taken.parent / 'Vault'}.")
    root = Path(__file__).resolve().parents[1]
    for shown in (
        "src/ordnung/sync/folder.py",
        "web/src/features/settings/SyncSetupCard.tsx",
        "web/src/features/settings/sync.ts",
        "README.md",
    ):
        text = (root / shown).read_text(encoding="utf-8")
        assert "Nextcloud/Ordnung" not in text and "/ 'Ordnung'" not in text, shown


# --------------------------------------------------------------------------------------------------
# the passphrase of a new folder
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "guessable",
    [
        "aaa bbb ccc ddd eee",
        "abc def ghi jkl mno",
        "12345 23456 34567 45678 56789",
        "one two three four five",
        "january february march april may",
        "qwerty asdfgh zxcvbn password letmein",
        "a b c d e f g h i j k l m n o",
        "the cat sat on the mat today",
    ],
)
def test_trivially_guessable_patterns_are_refused_for_a_new_folder(guessable: str) -> None:
    """Each used to reach 70 bits by the estimator (a character again and again, runs in order, keyboard
    walks, numbers and months, a short sentence of common words)."""
    from ordnung import sync

    assert sync.passphrase_bits(guessable) < sync.MIN_PASSPHRASE_BITS
    assert sync.passphrase_problem(guessable) == sync.WEAK_PASSPHRASE_MESSAGE


def test_the_command_line_suggests_a_strong_passphrase_when_it_sets_up_a_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io
    import re

    import typer
    from rich.console import Console

    from ordnung import cli, sync

    monkeypatch.delenv(sync.PASSPHRASE_ENV, raising=False)
    said = io.StringIO()
    monkeypatch.setattr(cli, "err_console", Console(file=said, width=200, no_color=True))
    shown: list[str] = []

    def prompt(text: str, **_options: object) -> str:
        found = re.search(r"\b([a-z]{5}(?:-[a-z]{5}){4})\b", said.getvalue())
        assert found is not None, said.getvalue()
        shown.append(found.group(1))
        return found.group(1)

    monkeypatch.setattr(typer, "prompt", prompt)
    chosen = cli._sync_passphrase(new=True)
    assert chosen == shown[0] and sync.passphrase_problem(chosen) is None
    assert sync.passphrase_bits(chosen) >= sync.MIN_PASSPHRASE_BITS
    for _ in range(50):
        assert sync.passphrase_problem(sync.suggested_passphrase()) is None


def test_setting_sync_up_again_after_disconnect_asks_nothing_and_keeps_the_name(pair: Pair) -> None:
    """A computer that left joins the same folder again with the data it left with: no choice between it
    and its own former self, no useless kept copy, its own name again — not "anna-laptop (2)" — and its
    former self is no longer listed."""
    a, b = pair.a, pair.b
    pair.joined()
    a.person_edit("the last change before leaving")
    engine.disconnect(a.paths, a.secrets, a.db, session=a.s, forget_passphrase=False, unreceived_ok=True)
    a.session = None
    pair.settle()
    joined = a.connect()
    assert joined.connected and joined.choice is None, joined
    assert joined.outcome is not None and joined.outcome.kept is None
    assert a.s.state.name == "anna-laptop" and a.mode == "in_use"
    assert "the last change before leaving" in a.notes()
    shown = [h for h in a.s.scan().heads if not h.forgotten]
    assert sorted(h.head.name for h in shown) == ["anna-laptop", "desktop"]
    pair.settle()
    b.round()
    seen = [h for h in b.s.scan().heads if not h.forgotten]
    assert sorted(h.head.name for h in seen) == ["anna-laptop", "desktop"]
    taken = b.use_here()
    assert not isinstance(taken.decision, Choice)
    assert "the last change before leaving" in b.notes()


async def test_after_the_computer_in_use_leaves_no_computer_is_in_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The standing-by computer used to say Ordnung was in use on itself once the other one left."""
    from sync_support import (
        REAL_ENGINE_TIMINGS,
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
        status,
    )

    fast_sync(monkeypatch, **REAL_ENGINE_TIMINGS)
    real = RealEngine()
    folder, desk, lap = await _desktop_in_use_laptop_standing_by(tmp_path, real)
    async with computer(desk, engine=real) as a, computer(lap, engine=real) as b:
        await connect(a, folder, "desktop")
        await connect(b, folder, "laptop")
        await eventually(lambda: agent_of(a).mode == "standing_by", within=10)
        left = await b.client.request("DELETE", "/api/sync", json={"unreceived_ok": True})
        assert left.status_code == 200, left.text

        def told() -> bool:
            _look_now(agent_of(a))
            shown = agent_of(a).status()
            return any(c.name == "laptop" and c.state == "left" for c in shown.computers)

        await eventually(told, within=10, step=0.1)
        shown = await status(a)
        assert shown["mode"] == "standing_by" and shown["in_use_on"] is None
        assert not any(c["in_use"] for c in shown["computers"]), shown["computers"]
        refused = await a.client.post("/api/items", json={"kind": "task", "title": "x"})
        assert refused.status_code == 409
        assert refused.json()["detail"] == (
            "No computer is using Ordnung now. Use it here first (Settings → Your computers)."
        )
        taken = await a.client.post("/api/sync/use-here", json={})
        assert taken.status_code == 200 and taken.json()["mode"] == "in_use", taken.text
        assert taken.json()["in_use_on"] == "desktop"
