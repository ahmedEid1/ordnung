"""“Delete everything” (``DELETE /api/data``): the typed confirmation, a data folder wiped down to the
lock and ``server.json`` (entries Ordnung did not create are left alone), an empty database that
keeps working, and the demo's refusal."""

from __future__ import annotations

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
        with sqlite3.connect(api.ctx.paths.db) as raw:
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
        assert refused.json()["detail"] == DEMO_MESSAGE and "ordnung demo --reset" in DEMO_MESSAGE
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
