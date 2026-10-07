"""Hand-off sync's routes (``/api/sync``) and the standby gate, against the fake engine: every route and
its refusals, the passphrase never echoed or logged, the status from memory, 409 ``standby`` for every
write outside ``/api/sync`` (from the computer's listener and a paired phone's), GETs on a standing-by
computer that change nothing, the demo, kept copies, and disconnecting."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import pytest

from fake_caldav import MemorySecrets
from ordnung import sync
from ordnung.api.app import openapi_schema
from ordnung.calendar.secrets import SecretsUnavailable
from ordnung.phone import scope
from sync_fake_engine import (
    FOLDER_FILE,
    Decision,
    FakeEngine,
    FakeSession,
    Problem,
    Summary,
    _folder_data,
    _write_folder,
    counter,
    digest_of,
    head_of,
)
from sync_support import PASSPHRASE, agent_of, computer, connect, eventually, fast_sync, status
from test_api_support import Api

pytestmark = pytest.mark.usefixtures("fast")

_PARAM = re.compile(r"\{[^}]+\}")


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    fast_sync(monkeypatch)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / "Nextcloud").mkdir()
    return tmp_path / "Nextcloud" / "Ordnung"


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return openapi_schema()


class _NeverRead(MemorySecrets):
    def get(self, account: str) -> str | None:
        raise AssertionError("the status read the password store")


def _example(template: str) -> str:
    return _PARAM.sub("x1", template)


def _standby(api: Api, name: str = "laptop") -> None:
    """This computer stands by (as if it learned another took over), without a folder."""
    agent = agent_of(api)
    agent.connected, agent.mode = True, "standing_by"
    agent.summary = Summary(
        folder="/sync",
        name="desktop",
        mode="standing_by",
        in_use_on=name,
        last_saved_at=None,
        base_from=None,
        base_arrived_at=None,
        notices=[],
        kept=[],
        data_folder_synced=False,
        journal=False,
    )


def _fill(folder: Path, *names: str) -> None:
    folder.mkdir()
    for name in names:
        (folder / name).write_text("x")


def _move(folder: Path, to: Path) -> Path:
    return folder.rename(to)


def _code(response: Any) -> str | None:
    if not response.headers.get("content-type", "").startswith("application/json"):
        return None
    found = response.json()
    return found.get("code") if isinstance(found, dict) else None


WRITES = [
    ("PATCH", "/api/sync", {"name": "desk"}),
    ("POST", "/api/sync/use-here", {}),
    ("POST", "/api/sync/choose", {"keep": 1}),
    ("POST", "/api/sync/save", {}),
    ("POST", "/api/sync/passphrase", {"passphrase": PASSPHRASE}),
    ("POST", "/api/sync/refill", None),
    ("DELETE", "/api/sync/computers/2", None),
]


# --------------------------------------------------------------------------------------------------
# not connected, unavailable, the demo
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), WRITES)
async def test_writes_need_a_connection(data_dir: Path, method: str, path: str, body: Any) -> None:
    async with computer(data_dir, start=False) as api:
        response = await api.client.request(method, path, json=body)
        assert response.status_code == 409, response.text
        assert response.json() == {"detail": sync.NOT_CONNECTED_MESSAGE, "code": "not_connected"}


@pytest.mark.parametrize(
    ("method", "path", "body"), [*WRITES, ("PUT", "/api/sync", {}), ("DELETE", "/api/sync", None)]
)
async def test_the_demo_never_syncs(data_dir: Path, method: str, path: str, body: Any) -> None:
    payload = {"folder": "/tmp/x", "name": "x", "passphrase": PASSPHRASE} if method == "PUT" else body
    async with computer(data_dir, start=False, demo=True) as api:
        response = await api.client.request(method, path, json=payload)
        assert response.status_code == 409, response.text
        assert response.json() == {"detail": sync.DEMO_MESSAGE, "code": "unavailable"}
        kept = await api.client.delete("/api/sync/kept/ordnung-kept-2026-10-07-0912.ordnung-backup")
        assert kept.status_code == 409 and kept.json()["code"] == "unavailable"
        found = await status(api)
        assert (found["available"], found["unavailable"], found["mode"]) == (False, sync.DEMO_MESSAGE, "off")


async def test_the_demo_s_agent_never_starts(data_dir: Path) -> None:
    async with computer(data_dir, demo=True) as api:
        assert agent_of(api)._task is None and agent_of(api).mode == "off"


async def test_without_a_password_store_sync_is_unavailable(data_dir: Path, folder: Path) -> None:
    missing = SecretsUnavailable("No password store here.", install="pip install keyring")
    async with computer(data_dir, start=False, secrets=MemorySecrets(missing)) as api:
        found = await status(api)
        assert (found["available"], found["unavailable"], found["install_command"]) == (
            False,
            "No password store here.",
            "pip install keyring",
        )
        refused = await api.client.put(
            "/api/sync", json={"folder": str(folder), "name": "desk", "passphrase": PASSPHRASE}
        )
        assert refused.status_code == 409 and refused.json()["code"] == "unavailable"


async def test_the_status_reads_no_secret_and_lists_no_folder(
    tmp_path: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = FakeEngine()
    async with computer(tmp_path / "desk", engine=engine) as api:
        await connect(api, folder, "desktop")
        never = _NeverRead()
        api.app.dependency_overrides[__import__("ordnung.api.routes.sync", fromlist=["x"]).get_secrets] = (
            lambda: never
        )

        def no_listing(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("the status listed a folder")

        engine.calls.clear()
        monkeypatch.setattr(os, "scandir", no_listing)
        for _ in range(100):
            assert (await api.client.get("/api/sync")).status_code == 200
        monkeypatch.undo()
        fast_sync(monkeypatch)
        assert not [call for call in engine.calls if call in ("open_session", "inspect_folder")]


# --------------------------------------------------------------------------------------------------
# setting up and joining
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "code"),
    [("", "name"), ("   ", "name"), ("x" * 41, "name"), ("desk\x07", "name")],
)
async def test_a_computer_s_name_must_be_a_name(data_dir: Path, folder: Path, name: str, code: str) -> None:
    async with computer(data_dir, start=False) as api:
        refused = await api.client.put(
            "/api/sync", json={"folder": str(folder), "name": name, "passphrase": PASSPHRASE}
        )
        assert refused.status_code == 422 and refused.json()["code"] == code


async def test_a_new_folder_s_passphrase_must_be_strong_and_is_never_echoed_or_logged(
    data_dir: Path, folder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    weak = "secret secret secret secret"
    caplog.set_level(logging.DEBUG)
    async with computer(data_dir, start=False) as api:
        refused = await api.client.put(
            "/api/sync", json={"folder": str(folder), "name": "desk", "passphrase": weak}
        )
        assert refused.status_code == 422 and refused.json() == {
            "detail": sync.WEAK_PASSPHRASE_MESSAGE,
            "code": "passphrase",
        }
        typed = await api.client.put(
            "/api/sync", json={"folder": str(folder), "name": "desk", "passphrase": weak, "keep": "maybe"}
        )
        assert typed.status_code == 422 and weak not in typed.text  # another field's error never quotes it
        done = await api.client.put(
            "/api/sync", json={"folder": str(folder), "name": "desk", "passphrase": PASSPHRASE}
        )
        assert done.status_code == 200
        for text in (refused.text, done.text, (await api.client.get("/api/sync")).text, caplog.text):
            assert weak not in text and PASSPHRASE not in text
        assert PASSPHRASE not in (data_dir / "sync" / "state.json").read_text()


@pytest.mark.parametrize(
    ("value", "problem"),
    [("relative/folder", "full path"), ("/no/such/parent/Ordnung", "parent folder")],
)
async def test_a_folder_that_can_t_be_used_is_refused(data_dir: Path, value: str, problem: str) -> None:
    async with computer(data_dir, start=False) as api:
        info = await api.client.post("/api/sync/inspect", json={"folder": value})
        assert (
            info.status_code == 200 and info.json()["kind"] == "refused" and problem in info.json()["problem"]
        )
        refused = await api.client.put(
            "/api/sync", json={"folder": value, "name": "desk", "passphrase": PASSPHRASE}
        )
        assert refused.status_code == 422 and refused.json()["code"] == "folder"


async def test_a_folder_with_other_files_names_some_of_them(data_dir: Path, folder: Path) -> None:
    _fill(folder, "tax 2025.pdf", "notes.txt", "photo.jpg", "more.doc")
    async with computer(data_dir, start=False) as api:
        info = (await api.client.post("/api/sync/inspect", json={"folder": str(folder)})).json()
        assert info["kind"] == "refused" and len(info["examples"]) == 3


async def test_joining_with_the_wrong_passphrase_stores_nothing(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    async with (
        computer(tmp_path / "desk", engine=engine) as a,
        computer(tmp_path / "lap", engine=engine, start=False) as b,
    ):
        await connect(a, folder, "desktop")
        assert (await b.client.post("/api/sync/inspect", json={"folder": str(folder)})).json()[
            "kind"
        ] == "existing"
        wrong = await b.client.put(
            "/api/sync", json={"folder": str(folder), "name": "laptop", "passphrase": "not the one at all"}
        )
        assert wrong.status_code == 422 and wrong.json() == {
            "detail": sync.WRONG_PASSPHRASE_MESSAGE,
            "code": "wrong_passphrase",
        }
        assert not (tmp_path / "lap" / "sync").exists() and engine.keyring(tmp_path / "lap").saved == {}
        again = await a.client.put(
            "/api/sync", json={"folder": str(folder), "name": "desk", "passphrase": PASSPHRASE}
        )
        assert again.status_code == 409 and again.json()["code"] == "already_connected"


async def test_joining_with_letters_of_its_own_asks_first_and_keep_answers(
    tmp_path: Path, folder: Path
) -> None:
    engine = FakeEngine()
    async with (
        computer(tmp_path / "desk", engine=engine) as a,
        computer(tmp_path / "lap", engine=engine) as b,
    ):
        await connect(a, folder, "desktop")
        assert (
            await b.client.post("/api/items", json={"kind": "task", "title": "Laptop's own"})
        ).status_code == 201
        asked = await connect(b, folder, "laptop")
        assert asked["choice"]["joining"] is True and asked["status"]["connected"] is False
        assert not (tmp_path / "lap" / "sync").exists()
        kept = await connect(b, folder, "laptop", keep="folder")
        assert kept["choice"] is None and kept["status"]["mode"] == "in_use"
        assert kept["status"]["kept"], "laptop's own Ordnung was kept as a copy first"


async def test_a_taken_name_gets_a_number(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    async with (
        computer(tmp_path / "desk", engine=engine) as a,
        computer(tmp_path / "lap", engine=engine) as b,
    ):
        await connect(a, folder, "MacBook-Pro")
        joined = await connect(b, folder, "MacBook-Pro")
        assert joined["status"]["this_computer"] == "MacBook-Pro (2)"


# --------------------------------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------------------------------


def _writes(schema: dict[str, Any]) -> list[tuple[str, str]]:
    operations = scope.schema_operations(schema)
    return sorted(
        (method, path)
        for method, path in operations
        if method not in ("GET", "HEAD") and not path.startswith(sync.API_PATH)
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "write" in metafunc.fixturenames:
        metafunc.parametrize("write", _writes(openapi_schema()), ids=lambda op: f"{op[0]} {op[1]}")


async def test_every_write_outside_sync_is_refused_while_standing_by(
    data_dir: Path, write: tuple[str, str]
) -> None:
    method, template = write
    async with computer(data_dir, start=False) as api:
        _standby(api)
        response = await api.client.request(method, _example(template), json={})
        if write in sync.ALLOWED_IN_STANDBY:
            assert _code(response) != "standby", response.text
        else:
            assert response.status_code == 409, response.text
            assert response.json() == {
                "detail": "Ordnung is in use on laptop. Use it here first (Settings → Your computers).",
                "code": "standby",
            }


async def test_the_gate_matches_whole_path_segments(data_dir: Path) -> None:
    async with computer(data_dir, start=False) as api:
        _standby(api)
        assert (await api.client.post("/api/syncfoo", json={})).json()["code"] == "standby"
        assert (await api.client.post("/api/sync-x/1", json={})).json()["code"] == "standby"
        # hand-off sync's own routes pass the gate (saving then says, itself, that it stands by)
        own = await api.client.post("/api/sync/use-here", json={"cancel": True})
        assert own.status_code == 200, own.text


async def test_a_phone_s_write_is_refused_while_its_computer_stands_by(data_dir: Path) -> None:
    from phone_support import pair, phone_app, phone_client

    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        _standby(api)
        refused = await phone.post("/api/items", json={"kind": "task", "title": "From the phone"})
        assert refused.status_code == 409 and refused.json()["code"] == "standby"
        assert [row for row in api.ctx.store.list_activity() if row.kind == "phone.changed"] == []
        assert (await phone.get("/api/items")).status_code == 200


async def test_get_requests_on_a_standing_by_computer_change_nothing(
    data_dir: Path, schema: dict[str, Any]
) -> None:
    gets = sorted(
        path
        for method, path in scope.schema_operations(schema)
        if method == "GET" and "{" not in path and path not in ("/api/events",)
    )
    async with computer(data_dir, start=False) as api:
        assert (await api.client.post("/api/items", json={"kind": "task", "title": "Pay"})).status_code == 201
        # the one lazy write: the calendar's event-name key, made once by the first preview (it then
        # travels like the person's data; a pull brings the computer in use's own)
        await api.client.get("/api/calendar/sync/preview")
        _standby(api)
        before = (digest_of(api.ctx.paths.db), counter(api.ctx.store))
        for path in gets:
            await api.client.get(path)
        assert (digest_of(api.ctx.paths.db), counter(api.ctx.store)) == before


# --------------------------------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------------------------------


async def test_saving_and_handing_over(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    async with computer(tmp_path / "desk", engine=engine) as api:
        await connect(api, folder, "desktop")
        saved = await api.client.post("/api/sync/save")
        assert saved.status_code == 200 and saved.json()["last_saved_at"]
        handed = await api.client.post("/api/sync/save", json={"hand_over": True})
        assert handed.status_code == 200 and handed.json()["mode"] == "standing_by"
        assert head_of(folder, "desktop")["state"] == "standing_by"
        again = await api.client.post("/api/sync/save")
        assert again.status_code == 409 and again.json()["code"] == "standby"


async def test_a_newer_ordnung_elsewhere_refuses_the_take_over(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    async with computer(tmp_path / "desk", engine=engine) as api:
        await connect(api, folder, "desktop")
        _standby(api)
        engine.decide = lambda local, view, action: Decision(  # type: ignore[method-assign]
            "paused", problem=Problem("newer_ordnung")
        )
        refused = await api.client.post("/api/sync/use-here", json={})
        assert refused.status_code == 409 and refused.json()["code"] == "newer_ordnung"
        assert "Update Ordnung" in refused.json()["detail"]


async def test_refill_and_forget_refusals(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    async with (
        computer(tmp_path / "desk", engine=engine) as a,
        computer(tmp_path / "lap", engine=engine) as b,
    ):
        await connect(a, folder, "desktop")
        refill = await a.client.post("/api/sync/refill")
        assert refill.status_code == 409 and refill.json()["code"] == "not_needed"
        assert (await a.client.delete("/api/sync/computers/9")).json()["code"] == "not_found"
        await connect(b, folder, "laptop")
        await eventually(lambda: agent_of(a).mode == "standing_by")
        laptop = next(c for c in (await status(a))["computers"] if c["name"] == "laptop")
        in_use = await a.client.delete(f"/api/sync/computers/{laptop['key']}")
        assert in_use.status_code == 409 and in_use.json()["code"] == "in_use"
        desktop = next(c for c in (await status(b))["computers"] if c["name"] == "desktop")
        forgotten = await b.client.delete(f"/api/sync/computers/{desktop['key']}")
        assert forgotten.status_code == 200, forgotten.text
        assert [c["name"] for c in forgotten.json()["computers"]] == ["laptop"]


async def test_an_emptied_folder_is_filled_again_from_the_computer_in_use(
    tmp_path: Path, folder: Path
) -> None:
    engine = FakeEngine()
    async with computer(tmp_path / "desk", engine=engine) as api:
        await connect(api, folder, "desktop")
        (folder / FOLDER_FILE).unlink()
        found = await eventually(lambda: agent_of(api).problem)
        assert found.code == "folder_empty" and found.actions == ["refill"]
        filled = await api.client.post("/api/sync/refill")
        assert filled.status_code == 200 and filled.json()["problem"] is None
        assert (folder / FOLDER_FILE).is_file()


async def test_a_missing_folder_can_be_chosen_again(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    async with computer(tmp_path / "desk", engine=engine) as api:
        await connect(api, folder, "desktop")
        moved = _move(folder, folder.parent / "Moved")
        found = await eventually(lambda: agent_of(api).problem)
        assert found.code == "folder_missing" and found.actions == ["choose_folder"]
        again = await api.client.put(
            "/api/sync", json={"folder": str(moved), "name": "desktop", "passphrase": PASSPHRASE}
        )
        assert again.status_code == 200 and again.json()["status"]["folder"] == str(moved)
        await eventually(lambda: agent_of(api).problem is None)


async def test_rename_and_notices(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    async with computer(tmp_path / "desk", engine=engine) as api:
        await connect(api, folder, "desktop")
        bad = await api.client.patch("/api/sync", json={"name": ""})
        assert bad.status_code == 422 and bad.json()["code"] == "name"
        renamed = await api.client.patch("/api/sync", json={"name": "big desk"})
        assert renamed.json()["this_computer"] == "big desk"
        engine.change(api.ctx.paths, notice=("brought_in", "Brought in a change.", None))
        await agent_of(api).load()
        notices = (await status(api))["notices"]
        assert [notice["code"] for notice in notices] == ["brought_in"]
        dismissed = await api.client.patch("/api/sync", json={"dismiss_notice": notices[0]["id"]})
        assert dismissed.json()["notices"] == []
        nothing = await api.client.patch("/api/sync", json={"keep_as_is": True})
        assert nothing.status_code == 409 and nothing.json()["code"] == "not_needed"
        nothing = await api.client.patch("/api/sync", json={"abandon_pull": True})
        assert nothing.status_code == 409 and nothing.json()["code"] == "not_needed"


# --------------------------------------------------------------------------------------------------
# kept copies
# --------------------------------------------------------------------------------------------------


async def test_a_kept_copy_downloads_and_deletes(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    async with computer(tmp_path / "desk", engine=engine) as api:
        await connect(api, folder, "desktop")
        kept = FakeSession(engine, api.ctx.paths).keep_local(
            api.ctx.paths, "before you kept laptop's Ordnung"
        )
        await agent_of(api).load()
        listed = (await status(api))["kept"]
        assert [found["name"] for found in listed] == [kept.name]
        assert (
            listed[0]["path"].endswith(kept.name) and listed[0]["why"] == "before you kept laptop's Ordnung"
        )
        download = await api.client.get(f"/api/sync/kept/{kept.name}")
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/octet-stream"
        assert "attachment" in download.headers["content-disposition"]
        assert download.headers["cache-control"] == "no-store"
        for wrong in ("ordnung-kept-2026-01-01-0000.ordnung-backup", "state.json", "..%2Fstate.json"):
            missing = await api.client.get(f"/api/sync/kept/{wrong}")
            assert missing.status_code == 404, wrong
        assert (await api.client.delete(f"/api/sync/kept/{kept.name}")).status_code == 204
        assert (await api.client.delete(f"/api/sync/kept/{kept.name}")).status_code == 404
        assert (await status(api))["kept"] == []


# --------------------------------------------------------------------------------------------------
# disconnecting
# --------------------------------------------------------------------------------------------------


async def test_disconnecting_asks_twice_while_no_one_has_the_latest(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    async with computer(tmp_path / "desk", engine=engine) as api:
        await connect(api, folder, "desktop")
        FakeSession(engine, api.ctx.paths).keep_local(api.ctx.paths, "kept")
        assert (
            await api.client.post("/api/items", json={"kind": "task", "title": "Last one"})
        ).status_code == 201
        refused = await api.client.request("DELETE", "/api/sync", json={})
        assert refused.status_code == 409 and refused.json()["code"] == "not_received"
        done = await api.client.request("DELETE", "/api/sync", json={"unreceived_ok": True})
        assert done.status_code == 200, done.text
        assert (done.json()["connected"], done.json()["mode"]) == (False, "off")
        head = head_of(folder, "desktop")
        assert head["state"] == "left" and head["version"], "its last version stays for the others"
        assert engine.keyring(tmp_path / "desk").saved == {}
        assert [entry.name for entry in (tmp_path / "desk" / "sync").iterdir()] == ["kept"]
        assert (folder / FOLDER_FILE).is_file()
        assert api.ctx.store.durable is False
        assert (
            await api.client.post("/api/items", json={"kind": "task", "title": "Alone"})
        ).status_code == 201
        nothing = await api.client.request("DELETE", "/api/sync")
        assert nothing.status_code == 200 and nothing.json()["connected"] is False


async def test_disconnect_can_keep_the_passphrase(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    async with computer(tmp_path / "desk", engine=engine) as api:
        await connect(api, folder, "desktop")
        done = await api.client.request(
            "DELETE", "/api/sync", json={"unreceived_ok": True, "forget_passphrase": False}
        )
        assert done.status_code == 200 and engine.keyring(tmp_path / "desk").saved


def _add_head(folder: Path, name: str, **values: Any) -> None:
    data = _folder_data(folder)
    assert data is not None
    key = 1 + max(head["key"] for head in data["heads"].values())
    data["heads"]["f" * 32] = {
        "key": key,
        "name": name,
        "state": "standing_by",
        "epoch": 0,
        "version": None,
        "has": None,
        "forgotten": [],
        "calendar": "none",
        **values,
    }
    _write_folder(folder, data)


async def test_the_calendar_another_computer_shares_is_named(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    async with computer(tmp_path / "desk", engine=engine) as api:
        await connect(api, folder, "desktop")
        _add_head(folder, "laptop", calendar="same")
        await eventually(lambda: agent_of(api).calendar_shared_with() == "laptop")
