"""Hand-off sync inside running servers with the real engine — the façade over the sync core
(:mod:`ordnung.sync.facade`) instead of the fake the server's other tests use: two computers through the
API, sharing one folder, or two copies of it that a test brings in step the way a sync tool would."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from fakes import use_fast_keys
from ordnung.backup import restore_backup
from ordnung.config import Paths
from ordnung.db.store import PERSON_META_KEY, Store
from ordnung.sync.local import load_state
from sync_faults import copy_tree
from sync_support import (
    PASSPHRASE,
    REAL_ENGINE_TIMINGS,
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
    fast_sync(monkeypatch, **REAL_ENGINE_TIMINGS)  # the real engine: see REAL_ENGINE_TIMINGS
    use_fast_keys(monkeypatch)


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
