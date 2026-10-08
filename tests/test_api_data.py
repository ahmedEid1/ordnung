"""“Delete everything” (``DELETE /api/data``): the typed confirmation, a data folder wiped down to the
lock and ``server.json`` (entries Ordnung did not create are left alone), an empty database that
keeps working, and the demo's refusal."""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import TAX_LETTER, record_events
from ordnung import clock
from ordnung.api.routes.data import DEMO_MESSAGE
from ordnung.config import Paths
from ordnung.db.migrate import latest_version
from ordnung.db.store import Store
from ordnung.locking import LOCK_NAME
from ordnung.server import SERVER_FILE
from test_api_support import TODAY, api_for

PROFILE = {"name": "Sam Rivera", "address": "Musterweg 1\n12345 Musterstadt", "email": "sam@example.org"}
CONFIRM = {"confirm": "DELETE"}


def _names(folder: Path) -> set[str]:
    return {path.name for path in folder.iterdir()}


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def test_delete_everything_wipes_the_data_folder(data_dir: Path) -> None:
    (data_dir / LOCK_NAME).write_text("pid 1", encoding="utf-8")
    (data_dir / SERVER_FILE).write_text('{"port": 8765}', encoding="utf-8")
    (data_dir / "notes-of-mine.txt").write_text("not Ordnung's", encoding="utf-8")
    async with api_for(data_dir) as api:
        client = api.client
        assert (await client.put("/api/profile", json=PROFILE)).status_code == 200
        await api.upload(("letter.pdf", TAX_LETTER.pdf()))
        await api.read_all()
        doc_id = (await client.get("/api/documents")).json()[0]["id"]
        assert (
            await client.post("/api/drafts", json={"kind": "objection", "doc_id": doc_id})
        ).status_code == 201
        (data_dir / "inbox").mkdir()
        (data_dir / "inbox" / "scan.pdf").write_bytes(b"%PDF-1.4")
        assert any(api.ctx.paths.files.rglob("*")) and any(api.ctx.paths.derived.rglob("*"))

        # the typed confirmation is required
        for body in (None, {}, {"confirm": "delete"}, {"confirm": "DELETE", "also": 1}):
            refused = await client.request("DELETE", "/api/data", json=body)
            assert refused.status_code == 422, body
            assert "clear-site-data" not in refused.headers
        assert (await client.get("/api/documents")).json()

        events = record_events(api.ctx.bus)
        response = await client.request("DELETE", "/api/data", json=CONFIRM)

        assert response.status_code == 200, response.text
        assert response.headers["clear-site-data"] == '"cache"'  # the browser drops what it cached
        result = response.json()
        assert result["kept"] == ["notes-of-mine.txt"]
        assert {"files", "derived", "drafts", "inbox", "ordnung.db"} <= set(result["removed"])
        assert {name for name, _ in events} == {"profile.updated", "item.updated", "suggestions.updated"}
        # only the lock, server.json, the foreign file, an empty database and empty folders are left
        left = _names(data_dir)
        assert left - {"ordnung.db-wal", "ordnung.db-shm"} == {
            LOCK_NAME,
            SERVER_FILE,
            "notes-of-mine.txt",
            "ordnung.db",
            "files",
            "derived",
            "drafts",
        }
        assert (data_dir / LOCK_NAME).read_text(encoding="utf-8") == "pid 1"
        assert not any(_names(data_dir / name) for name in ("files", "derived", "drafts"))
        # nothing deleted is left behind in the database file or its write-ahead log
        for name in ("ordnung.db", "ordnung.db-wal"):
            raw_bytes = (data_dir / name).read_bytes() if (data_dir / name).exists() else b""
            assert b"Sam Rivera" not in raw_bytes and TAX_LETTER.marker.encode() not in raw_bytes, name
        with contextlib.closing(sqlite3.connect(api.ctx.paths.db)) as raw, raw:
            assert raw.execute("PRAGMA user_version").fetchone()[0] == latest_version()
            assert raw.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
            assert raw.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0

        # the app starts over — and keeps working
        assert (await client.get("/api/documents")).json() == []
        assert (await client.get("/api/drafts")).json() == []
        assert (await client.get("/api/items")).json() == []
        assert (await client.get("/api/activity")).json() == []
        profile = (await client.get("/api/profile")).json()
        assert profile["name"] == "" and profile["onboarded"] is False
        await api.upload(("letter.pdf", TAX_LETTER.pdf()))
        await api.read_all()
        assert len((await client.get("/api/documents")).json()) == 1


async def test_the_demo_cannot_be_deleted(data_dir: Path) -> None:
    async with api_for(data_dir, demo=True) as api:
        await api.upload(("letter.pdf", TAX_LETTER.pdf()))
        refused = await api.client.request("DELETE", "/api/data", json=CONFIRM)
        assert refused.status_code == 409
        assert refused.json()["detail"] == DEMO_MESSAGE
        # the reset doesn't touch a demo that runs, so the message says to stop it first
        assert "stop the demo (Ctrl+C where it runs), then run “ordnung demo --reset”." in DEMO_MESSAGE
        assert len((await api.client.get("/api/documents")).json()) == 1


def test_wipe_keeps_other_threads_connections_usable(data_dir: Path) -> None:
    with Store.open(Paths(data_dir)) as store:
        store.add_party(name="Stadtwerke", kind="utility")
        store.set_meta("simulated_today", "2026-09-28")
        seen: list[int] = []

        def read_parties() -> None:
            seen.append(len(store.list_parties()))

        reader = threading.Thread(target=read_parties)
        reader.start()
        reader.join()
        store.wipe()
        again = threading.Thread(target=read_parties)
        again.start()
        again.join()

        assert seen == [1, 0]
        assert store.get_meta("simulated_today") is None
        assert store.schema_version == latest_version()
        assert store.add_party(name="Stadtwerke", kind="utility").name == "Stadtwerke"
        assert [hit.id for hit in store.search("Stadtwerke")] == []  # no documents: nothing to find


def test_wipe_refuses_a_read_only_store(data_dir: Path) -> None:
    Store.open(Paths(data_dir)).close()
    with Store.open(Paths(data_dir), read_only=True) as store, pytest.raises(PermissionError):
        store.wipe()


async def test_delete_everything_stops_phone_access_and_removes_its_certificates(data_dir: Path) -> None:
    from ordnung.phone.record import META_KEY
    from phone_support import pair, phone_app, phone_client

    async with phone_app(data_dir) as (api, _net, servers), phone_client(api) as phone:
        await pair(api, phone)
        (data_dir / "notes-of-mine.txt").write_text("mine", encoding="utf-8")
        assert (data_dir / "phone" / "ca.key").is_file()
        result = (await api.client.request("DELETE", "/api/data", json=CONFIRM)).json()
        assert "phone" in result["removed"] and result["kept"] == ["notes-of-mine.txt"]
        assert not (data_dir / "phone").exists()
        assert servers.made[-1].stopped == 1
        assert api.ctx.store.get_meta(META_KEY) is None
        status = (await api.client.get("/api/phone")).json()
        assert (status["enabled"], status["listening"], status["devices"]) == (False, False, [])
        assert (await phone.get("/api/documents")).json()["code"] in ("misdirected", "phone_not_paired")


# --------------------------------------------------------------------------------------------------
# with hand-off sync connected
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def sync_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from sync_support import fast_sync

    fast_sync(monkeypatch)
    (tmp_path / "Nextcloud").mkdir()
    return tmp_path / "Nextcloud" / "Ordnung"


async def test_delete_everything_leaves_sync_and_asks_twice_while_no_one_has_the_latest(
    tmp_path: Path, sync_folder: Path
) -> None:
    from sync_fake_engine import FOLDER_FILE, FakeEngine, FakeSession, head_of
    from sync_support import computer, connect

    engine = FakeEngine()
    data = tmp_path / "desk"
    async with computer(data, engine=engine) as api:
        await connect(api, sync_folder, "desktop")
        FakeSession(engine, api.ctx.paths).keep_local(api.ctx.paths, "kept")
        assert (await api.client.post("/api/items", json={"kind": "task", "title": "Pay"})).status_code == 201

        refused = await api.client.request("DELETE", "/api/data", json=CONFIRM)
        assert refused.status_code == 409 and refused.json()["code"] == "not_received"
        assert api.ctx.store.list_items(), "nothing was deleted"
        assert api.app.state.ordnung.background_on, "nothing was stopped either"

        done = await api.client.request("DELETE", "/api/data", json={**CONFIRM, "unreceived_ok": True})
        assert done.status_code == 200, done.text
        assert "sync" in done.json()["removed"] and not (data / "sync").exists(), "kept copies go too"
        head = head_of(sync_folder, "desktop")
        assert head["state"] == "left" and head["version"], "its last version stays for the others"
        assert "push:leave" in engine.calls
        assert engine.keyring(data).saved == {}
        assert (sync_folder / FOLDER_FILE).is_file(), "the folder and the other computers are untouched"
        status = (await api.client.get("/api/sync")).json()
        assert (status["connected"], status["mode"]) == (False, "off")
        assert api.app.state.ordnung.background_on and api.ctx.worker.running
        assert api.app.state.ordnung.tick._task is not None


async def test_delete_everything_leaves_a_calendar_another_computer_sends_to(
    tmp_path: Path, sync_folder: Path
) -> None:
    from fake_caldav import FakeCalDav, MemorySecrets
    from ordnung.api.routes import calendar_sync
    from ordnung.calendar import caldav
    from sync_fake_engine import FakeEngine, _folder_data, _write_folder
    from sync_support import computer, connect, eventually
    from test_api_calendar_sync import CONNECT

    engine, server, secrets = FakeEngine(), FakeCalDav(), MemorySecrets()
    async with computer(tmp_path / "desk", engine=engine) as api:
        api.app.dependency_overrides[calendar_sync.get_secrets] = lambda: secrets
        api.app.dependency_overrides[calendar_sync.get_transport] = server.transport
        assert (await api.client.put("/api/calendar/sync", json=CONNECT)).status_code == 200
        await connect(api, sync_folder, "desktop")
        found = _folder_data(sync_folder)
        assert found is not None
        found["heads"]["f" * 32] = {
            "key": 9,
            "name": "laptop",
            "state": "standing_by",
            "epoch": 0,
            "version": None,
            "has": None,
            "forgotten": [],
            "calendar": "same",
        }
        _write_folder(sync_folder, found)
        agent = api.app.state.ordnung.sync
        await eventually(lambda: agent.calendar_shared_with() == "laptop")
        events = dict(server.resources)
        done = await api.client.request("DELETE", "/api/data", json={**CONFIRM, "unreceived_ok": True})
        assert done.status_code == 200, done.text
        assert (done.json()["calendar_events_removed"], done.json()["calendar_shared_with"]) == (
            None,
            "laptop",
        )
        assert server.resources == events, "laptop keeps Ordnung's events current"
        assert caldav.load_state(api.ctx.store) is None and secrets.saved == {}
