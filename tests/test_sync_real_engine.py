"""Hand-off sync inside running servers with the real engine — the façade over the sync core
(:mod:`ordnung.sync.facade`) instead of the fake the server's other tests use: two computers through the
API, sharing one folder, or two copies of it that a test brings in step the way a sync tool would."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from fakes import use_fast_keys
from ordnung.backup import restore_backup
from ordnung.config import Paths
from ordnung.db.store import PERSON_META_KEY, Store, person_write
from ordnung.sync.local import load_state
from sync_faults import copy_tree
from sync_support import (
    PASSPHRASE,
    RealEngine,
    agent_of,
    computer,
    connect,
    eventually,
    fast_sync,
    status,
)
from test_api_support import Api

pytestmark = pytest.mark.usefixtures("fast")


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    fast_sync(monkeypatch)
    use_fast_keys(monkeypatch)
    monkeypatch.setattr(os, "fsync", lambda fd: None)  # no test here is about durability: skip the disk flush


async def _add_todo(api: Api, title: str) -> Any:
    return await api.client.post("/api/items", json={"kind": "task", "title": title})


async def _titles(api: Api) -> set[str]:
    return {item["title"] for item in (await api.client.get("/api/items")).json()}


def _catch_up(source: Path, target: Path) -> None:
    """What a sync tool does: every file of ``source`` that ``target`` lacks or holds differently is
    copied over (nothing is deleted)."""
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        copy = target / path.relative_to(source)
        if copy.is_file() and copy.read_bytes() == path.read_bytes():
            continue
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, copy)


def _computer(found: dict[str, Any], name: str) -> dict[str, Any]:
    return next(entry for entry in found["computers"] if entry["name"] == name)


def _pushed(api: Api) -> int | None:
    """The person-change count this computer's last save accounted for (``state.json``)."""
    state = load_state(api.ctx.paths)
    return state.pushed if state is not None else None


async def _saved(api: Api) -> None:
    await agent_of(api).save()
    assert not agent_of(api).status().pending_changes


async def test_set_up_join_stand_by_take_over_and_leave(tmp_path: Path) -> None:
    engine = RealEngine()
    (tmp_path / "Nextcloud").mkdir()
    folder = tmp_path / "Nextcloud" / "Ordnung"
    async with (
        computer(tmp_path / "desk", engine=engine) as a,
        computer(tmp_path / "lap", engine=engine) as b,
    ):
        answer = await connect(a, folder, "desktop")
        assert answer["choice"] is None and answer["status"]["mode"] == "in_use"
        assert {entry.name for entry in folder.iterdir() if entry.is_dir()} == {"h", "o"}
        assert answer["status"]["last_saved_at"] is not None  # the first save, at once

        # a person's change is saved by itself within moments
        assert (await _add_todo(a, "Pay the gym")).status_code == 201
        changes = int(a.ctx.store.get_meta(PERSON_META_KEY) or 0)
        assert changes >= 1, "the request counted as the person's change"
        await eventually(lambda: _pushed(a) == changes, within=10)

        # laptop joins: everything comes over, laptop is in use, desktop stands by
        joined = await connect(b, folder, "laptop")
        assert joined["status"]["mode"] == "in_use", joined
        assert "Pay the gym" in await _titles(b)
        await eventually(lambda: agent_of(a).mode == "standing_by", within=10)
        refused = await _add_todo(a, "Too late")
        assert refused.status_code == 409 and refused.json() == {
            "detail": "Ordnung is in use on laptop. Use it here first (Settings → Your computers).",
            "code": "standby",
        }
        shown = await status(a)
        assert shown["in_use_on"] == "laptop" and _computer(shown, "laptop")["in_use"]

        # laptop changes something; desktop takes over with one click and brings it over
        assert (await _add_todo(b, "Written on the laptop")).status_code == 201
        await _saved(b)
        taken = await a.client.post("/api/sync/use-here", json={})
        assert taken.status_code == 200 and taken.json()["mode"] == "in_use", taken.text
        assert {"Pay the gym", "Written on the laptop"} <= await _titles(a)
        assert (await _add_todo(a, "Back on the desktop")).status_code == 201
        await eventually(lambda: agent_of(b).mode == "standing_by", within=10)
        await _saved(a)

        # laptop leaves: desktop has its latest, so one confirmation is enough
        await eventually(lambda: agent_of(b).status().others_have_latest, within=10)
        left = await b.client.request("DELETE", "/api/sync", json={})
        assert left.status_code == 200 and left.json()["connected"] is False, left.text
        assert not (tmp_path / "lap" / "sync" / "state.json").exists()
        assert (await _add_todo(b, "Alone again")).status_code == 201
        await eventually(lambda: _computer(agent_of(a).status().model_dump(), "laptop")["state"] == "left")

        # desktop deletes everything: no other computer has its latest any more, so it asks twice
        once = await a.client.request("DELETE", "/api/data", json={"confirm": "DELETE"})
        assert once.status_code == 409 and once.json()["code"] == "not_received", once.text
        twice = await a.client.request(
            "DELETE", "/api/data", json={"confirm": "DELETE", "unreceived_ok": True}
        )
        assert twice.status_code == 200, twice.text
        assert (await status(a))["connected"] is False
        assert not (tmp_path / "desk" / "sync").exists()
        assert any(path.name.startswith("o") for path in folder.iterdir())  # the folder keeps everything


async def _both_changed(tmp_path: Path, a: Api, b: Api) -> None:
    """desktop sets up, laptop joins through its own copy of the folder before the sync tool brings
    the claim back, and each saves a change the other lacks: desktop stands by, laptop is asked."""
    here, there = tmp_path / "desk-view" / "Ordnung", tmp_path / "lap-view" / "Ordnung"
    here.parent.mkdir()
    there.parent.mkdir()
    await connect(a, here, "desktop")
    assert (await _add_todo(a, "Common")).status_code == 201
    await _saved(a)
    there.mkdir()
    _catch_up(here, there)
    await connect(b, there, "laptop")  # the sync tool doesn't bring laptop's claim back yet
    assert agent_of(a).mode == "in_use" and agent_of(b).mode == "in_use"
    assert (await _add_todo(a, "Only on the desktop")).status_code == 201
    assert (await _add_todo(b, "Only on the laptop")).status_code == 201
    await _saved(a)
    await _saved(b)

    _catch_up(here, there)
    _catch_up(there, here)
    # laptop claimed last: desktop stands by; laptop, in use, is asked which Ordnung to keep
    await eventually(lambda: agent_of(a).mode == "standing_by", within=10)
    await eventually(lambda: agent_of(b).choice is not None, within=10)


async def test_both_changed_the_person_chooses_and_this_computer_s_data_is_kept(tmp_path: Path) -> None:
    engine = RealEngine()
    async with (
        computer(tmp_path / "desk", engine=engine) as a,
        computer(tmp_path / "lap", engine=engine) as b,
    ):
        await _both_changed(tmp_path, a, b)
        sides = {side["computer"]: side for side in (await status(b))["choice"]["sides"]}
        assert set(sides) == {"desktop", "laptop"} and sides["laptop"]["this"]
        assert sides["desktop"]["complete"]

        chosen = await b.client.post("/api/sync/choose", json={"keep": sides["desktop"]["key"]})
        assert chosen.status_code == 200, chosen.text
        found = chosen.json()
        assert found["mode"] == "in_use" and found["choice"] is None and found["problem"] is None
        titles = await _titles(b)
        assert {"Common", "Only on the desktop"} <= titles and "Only on the laptop" not in titles
        assert [kept["name"] for kept in found["kept"]], "laptop's own data was kept as a copy"
        kept = found["kept"][0]
        kept_path = tmp_path / "lap" / "sync" / "kept" / kept["name"]
        assert kept["path"] == str(kept_path) and kept_path.is_file()
        download = await b.client.get(f"/api/sync/kept/{kept['name']}")
        assert download.status_code == 200 and download.content.startswith(b"ORDNUNG")


async def test_keeping_this_side_then_forgetting_the_other_computer_keeps_its_changes_here(
    tmp_path: Path,
) -> None:
    """The choice kept this computer's own side; the other computer is then lost: forgetting it keeps
    its changes, found nowhere else, as a copy here — and the copy can be opened, then deleted."""
    engine = RealEngine()
    async with (
        computer(tmp_path / "desk", engine=engine) as a,
        computer(tmp_path / "lap", engine=engine) as b,
    ):
        await _both_changed(tmp_path, a, b)
        sides = {side["computer"]: side for side in (await status(b))["choice"]["sides"]}
        chosen = await b.client.post("/api/sync/choose", json={"keep": sides["laptop"]["key"]})
        assert chosen.status_code == 200, chosen.text
        found = chosen.json()
        assert found["mode"] == "in_use" and found["choice"] is None and found["problem"] is None
        assert found["kept"] == [], "laptop's own data stays: nothing of it was replaced"
        titles = await _titles(b)
        assert {"Common", "Only on the laptop"} <= titles and "Only on the desktop" not in titles

        forgotten = await b.client.delete(f"/api/sync/computers/{_computer(found, 'desktop')['key']}")
        assert forgotten.status_code == 200, forgotten.text
        shown = forgotten.json()
        assert [entry["name"] for entry in shown["computers"]] == ["laptop"]
        (kept,) = shown["kept"]
        assert kept["why"] == "desktop's changes, before it was removed"
        download = await b.client.get(f"/api/sync/kept/{kept['name']}")
        assert download.status_code == 200
        copy = tmp_path / "copy.ordnung-backup"
        copy.write_bytes(download.content)
        restore_backup(copy, PASSPHRASE, tmp_path / "opened")
        with Store.open(Paths(tmp_path / "opened")) as opened:
            restored = {row["title"] for row in opened._conn().execute("SELECT title FROM items")}
        assert "Only on the desktop" in restored

        assert (await b.client.delete(f"/api/sync/kept/{kept['name']}")).status_code == 204
        assert (await status(b))["kept"] == []
        assert not (tmp_path / "lap" / "sync" / "kept" / kept["name"]).exists()
        assert (await b.client.delete(f"/api/sync/kept/{kept['name']}")).status_code == 404


async def test_data_that_went_back_in_time_is_kept_as_it_is_when_its_saved_state_is_gone(
    tmp_path: Path,
) -> None:
    """A local rollback is put back from this computer's last saved state; when that isn't in the folder
    any more, the person is asked, and keeping the data as it is ends the pause."""
    engine = RealEngine()
    (tmp_path / "Nextcloud").mkdir()
    folder, desk = tmp_path / "Nextcloud" / "Ordnung", tmp_path / "desk"
    async with computer(desk, engine=engine) as a:
        await connect(a, folder, "desktop")
        assert (await _add_todo(a, "Before the backup")).status_code == 201
        await _saved(a)
    copy_tree(desk, tmp_path / "os-backup")
    async with computer(desk, engine=engine) as a:
        assert (await _add_todo(a, "After the backup")).status_code == 201
        await _saved(a)
    copy_tree(tmp_path / "os-backup", desk)  # the data folder is put back from the OS backup
    shutil.rmtree(folder / "o")  # and the last saved state is gone from the folder
    async with computer(desk, engine=engine) as a:
        found = await eventually(lambda: agent_of(a).problem, within=10)
        assert found.code == "local_rollback" and found.actions == ["keep_as_is"]
        kept = await a.client.patch("/api/sync", json={"keep_as_is": True})
        assert kept.status_code == 200, kept.text
        assert kept.json()["problem"] is None and kept.json()["mode"] == "in_use"
        titles = await _titles(a)
        assert "Before the backup" in titles and "After the backup" not in titles
        again = await a.client.patch("/api/sync", json={"keep_as_is": True})
        assert again.status_code == 409 and again.json()["code"] == "not_needed"


def test_the_command_line_takes_over_saves_and_refuses_with_the_real_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from fake_caldav import MemorySecrets
    from fixtures_llm import TAX_LETTER, TODAY, fake_backend
    from ordnung import cli, clock, sync
    from ordnung.app_context import build_context
    from ordnung.sync import agent as agent_module

    engine, keyring = RealEngine(), MemorySecrets()
    monkeypatch.setattr(agent_module, "load_engine", lambda: engine)
    monkeypatch.setattr(agent_module, "default_secrets", lambda: keyring)
    monkeypatch.setattr(
        cli, "open_context", lambda data_dir: build_context(data_dir, backend_obj=fake_backend())
    )
    monkeypatch.setattr(cli, "reachable_server", lambda folder: None)
    monkeypatch.setenv(sync.PASSPHRASE_ENV, PASSPHRASE)
    clock.set_today(TODAY)
    runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})

    def invoke(*args: str) -> Any:
        return runner.invoke(cli.app, list(args))

    try:
        (tmp_path / "Nextcloud").mkdir()
        folder, desk, lap = tmp_path / "Nextcloud" / "Ordnung", tmp_path / "desk", tmp_path / "lap"
        made = invoke("sync", "connect", str(folder), "--name", "desktop", "--data-dir", str(desk))
        assert made.exit_code == 0 and "In use here (desktop)" in made.output, made.output
        joined = invoke("sync", "connect", str(folder), "--name", "laptop", "--data-dir", str(lap))
        assert joined.exit_code == 0 and "In use here (laptop)" in joined.output, joined.output
        taken = invoke("sync", "use-here", "--data-dir", str(desk))
        assert taken.exit_code == 0 and "Ordnung is in use here now." in taken.output, taken.output

        # laptop hasn't looked since: its write is made and saved, and the save finds desktop's claim
        letter = tmp_path / "letter.pdf"
        letter.write_bytes(TAX_LETTER.pdf())
        added = invoke("--data-dir", str(lap), "add", str(letter))
        assert added.exit_code == 0 and "Saved to the sync folder." in added.output, added.output
        refused = invoke("--data-dir", str(lap), "add", str(letter))
        assert refused.exit_code == 1 and "in use on desktop" in refused.output, refused.output
        shown = invoke("sync", "status", "--data-dir", str(lap))
        assert shown.exit_code == 0 and "desktop" in shown.output, shown.output
    finally:
        clock.set_today(None)


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
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
    )

    fast_sync(monkeypatch)
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
    finishes even later is pushed from standing by: the computer in use brings it in."""
    import asyncio

    from sync_support import (
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
    )

    late = finishes == "after the fence gave up"
    fast_sync(monkeypatch, FENCE_WAIT_S=0.2 if late else 2.0)
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


async def test_after_a_save_the_other_computer_has_it_only_once_it_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The top bar's "has it" and the second confirmation of Disconnect and Delete everything are worked
    out against the version just saved (they used to read the last look's, made before the save)."""
    from sync_support import (
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
    )

    fast_sync(monkeypatch, SCAN_S=60.0, WATCH_S=60.0)  # no look of its own between the steps below
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
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
    )

    fast_sync(monkeypatch, SCAN_S=60.0, WATCH_S=60.0)
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
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
    )

    fast_sync(monkeypatch, PUSH_PERSON_QUIET_S=30.0, PUSH_QUIET_S=30.0, PUSH_MAX_WAIT_S=60.0)
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
    from sync_support import RealEngine, agent_of, computer, connect, fast_sync, status

    fast_sync(monkeypatch)
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
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
        status,
    )

    fast_sync(monkeypatch)
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


async def test_after_the_computer_in_use_leaves_no_computer_is_in_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The standing-by computer used to say Ordnung was in use on itself once the other one left."""
    from sync_support import (
        RealEngine,
        agent_of,
        computer,
        connect,
        eventually,
        fast_sync,
        status,
    )

    fast_sync(monkeypatch)
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


async def test_a_full_sync_folder_is_told_as_full_not_as_one_that_doesn_t_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A save into a full folder was shown as "doesn't answer" at once, then as "keeps failing": the
    folder's own error (``FolderFull``) named no problem, so it fell back to an unreachable folder. A full
    folder is told after FAILING_AFTER_S, like a save that keeps failing, and the next save ends it."""
    from ordnung.sync import agent as agent_module
    from ordnung.sync.folder import RealFs
    from sync_faults import FullFs

    monkeypatch.setattr(agent_module, "FAILING_AFTER_S", 0.5)
    (tmp_path / "Nextcloud").mkdir()
    async with computer(tmp_path / "desk", engine=RealEngine()) as api:
        await connect(api, tmp_path / "Nextcloud" / "Vault", "desktop")
        agent = agent_of(api)
        await _saved(api)
        shown: list[str] = []
        set_problem = agent._set_problem

        def record(code: Any, exc: BaseException | None = None) -> None:
            shown.append(code)
            set_problem(code, exc)

        monkeypatch.setattr(agent, "_set_problem", record)
        session = agent._session
        assert session is not None
        session.inner.folder.fs = FullFs(after_bytes=0)  # no byte more fits
        assert (await _add_todo(api, "Pay the gym")).status_code == 201
        found = await eventually(lambda: agent.problem, within=15)
        assert found.code == "folder_full"
        assert "folder_unreachable" not in shown and "save_failing" not in shown, shown
        told = (await status(api))["problem"]
        assert told["code"] == "folder_full" and told["title"] == "The sync folder is full"

        session.inner.folder.fs = RealFs()  # room again
        await _saved(api)
        assert agent.problem is None
