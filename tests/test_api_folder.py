"""The watched folder over HTTP: its status, the letters waiting for the person ("Read these" /
"Keep private"), the settings that start and restart the watcher, and the guards around waiting
letters (no reprocessing, no flipping "private" behind the person's back, uploads answer for them)."""

from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from fixtures_llm import INVOICE_LETTER, TAX_LETTER
from ordnung import clock
from ordnung.api.deps import ApiState
from ordnung.ingest.intake import TOO_DEEP
from ordnung.ingest.pipeline import add_file
from ordnung.llm.replay import ReplayBackend
from test_api_support import TODAY, Api, api_for, lifespan


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def eventually_json(api: Api, path: str, check: Any, within: float = 15.0) -> Any:
    """GET ``path`` until ``check(body)`` holds (and return the body)."""
    for _ in range(int(within / 0.05)):
        body = (await api.client.get(path)).json()
        if check(body):
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"{path} never matched: {body}")


async def waiting_letter(api: Api, data: bytes, name: str) -> str:
    document = await add_file(api.ctx, data, name, hold=True, source="folder")
    await api.read_all()
    return document.id


async def test_the_folder_status_without_a_folder(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        body = (await api.client.get("/api/folder")).json()
    assert body == {
        "folder": None,
        "state": "off",
        "problem": None,
        "auto_read": False,
        "can_read": True,
        "waiting": 0,
        "suggested": str((data_dir / "inbox").resolve()),
        "recent": [],
    }


async def test_a_folder_set_in_settings_is_watched_and_its_files_wait(data_dir: Path, tmp_path: Path) -> None:
    scans = tmp_path / "Scans"
    scans.mkdir()
    async with api_for(data_dir) as api, lifespan(api.app):
        api.app.state.ordnung.folder.settle_s = 0.2
        api.app.state.ordnung.folder.tick_ms = 50
        saved = await api.client.put("/api/settings", json={"inbox_dir": str(scans)})
        assert saved.status_code == 200 and saved.json()["inbox_auto_read"] is False
        await eventually_json(api, "/api/folder", lambda body: body["state"] == "watching")

        (scans / "scan.pdf").write_bytes(TAX_LETTER.pdf())
        status = await eventually_json(api, "/api/folder", lambda body: body["waiting"] == 1)
        (pickup,) = status["recent"]
        assert (pickup["filename"], pickup["outcome"]) == ("scan.pdf", "added")
        waiting = (await api.client.get("/api/documents", params={"status": "held"})).json()
        assert [doc["id"] for doc in waiting] == [pickup["doc_id"]] and waiting[0]["ai_private"] is True

        answer = await api.client.post("/api/documents/held/read", json={"doc_ids": [pickup["doc_id"]]})
        assert answer.status_code == 200
        body = answer.json()
        assert [doc["status"] for doc in body["documents"]] == ["queued"] and len(body["jobs"]) == 1
        assert body["skipped"] == []
        read = await eventually_json(
            api, f"/api/documents/{pickup['doc_id']}", lambda d: d["document"]["status"] == "processed"
        )
        assert read["document"]["kind"] == "tax_assessment" and read["document"]["ai_private"] is False

        cleared = await api.client.put("/api/settings", json={"inbox_dir": None})
        assert cleared.json()["inbox_dir"] is None
        assert (await api.client.get("/api/folder")).json()["state"] == "off"


async def test_keep_private_and_ids_that_no_longer_wait(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await waiting_letter(api, INVOICE_LETTER.pdf(), "rechnung.pdf")
        kept = await api.client.post(
            "/api/documents/held/keep-private", json={"doc_ids": [doc_id, "doc_unknown"]}
        )
        assert kept.status_code == 200
        body = kept.json()
        assert [(doc["id"], doc["status"], doc["ai_private"]) for doc in body["documents"]] == [
            (doc_id, "processed", True)
        ]
        assert body["jobs"] == [] and body["skipped"] == ["doc_unknown"]
        again = (await api.client.post("/api/documents/held/read", json={"doc_ids": [doc_id]})).json()
        assert again == {"documents": [], "jobs": [], "skipped": [doc_id]}  # answered already
        assert api.backend.calls == []
        assert (await api.client.get("/api/folder")).json()["waiting"] == 0


async def test_answers_need_ids(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        for bad in ({"doc_ids": []}, {}, {"doc_ids": ["x"], "all": True}, {"doc_ids": ["x"] * 501}):
            response = await api.client.post("/api/documents/held/read", json=bad)
            assert response.status_code == 422, bad


async def test_the_demo_that_only_replays_can_not_read_waiting_letters(
    data_dir: Path, tmp_path: Path
) -> None:
    async with api_for(data_dir, demo=True) as api:
        doc_id = await waiting_letter(api, INVOICE_LETTER.pdf(), "rechnung.pdf")
        api.ctx.llm.backend = ReplayBackend(tmp_path / "fixtures")
        state: ApiState = api.app.state.ordnung
        assert not state.reads_letters
        assert (await api.client.get("/api/folder")).json()["can_read"] is False  # files always wait
        response = await api.client.post("/api/documents/held/read", json={"doc_ids": [doc_id]})
        assert response.status_code == 409 and "recorded answers" in response.json()["detail"]
        kept = await api.client.post("/api/documents/held/keep-private", json={"doc_ids": [doc_id]})
        assert kept.status_code == 200


async def test_a_waiting_letter_is_not_read_again_or_made_public_behind_the_person(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await waiting_letter(api, INVOICE_LETTER.pdf(), "rechnung.pdf")
        response = await api.client.post(f"/api/documents/{doc_id}/reprocess")
        assert response.status_code == 409 and "waiting for you" in response.json()["detail"]
        response = await api.client.patch(f"/api/documents/{doc_id}", json={"ai_private": False})
        assert response.status_code == 409
        renamed = await api.client.patch(f"/api/documents/{doc_id}", json={"title": "Phone bill"})
        assert renamed.status_code == 200 and renamed.json()["status"] == "held"
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert (
            detail["document"]["ai_private"] is True
            and detail["attachments"] == []
            and detail["email"] is None
        )


async def test_uploading_a_waiting_file_answers_for_it(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await waiting_letter(api, INVOICE_LETTER.pdf(), "rechnung.pdf")
        body = await api.upload(("rechnung.pdf", INVOICE_LETTER.pdf()))  # added by hand, not private
        assert [doc["id"] for doc in body["documents"]] == [doc_id] and body["duplicates"] == []
        assert body["documents"][0]["status"] == "queued" and len(body["jobs"]) == 1
        await api.read_all()
        assert (await api.client.get(f"/api/documents/{doc_id}")).json()["document"]["status"] == "processed"

        other = await waiting_letter(api, TAX_LETTER.pdf(), "bescheid.pdf")
        body = await api.upload(("bescheid.pdf", TAX_LETTER.pdf()), private=True)
        assert body["duplicates"] == [other]
        kept = (await api.client.get(f"/api/documents/{other}")).json()["document"]
        assert (kept["status"], kept["ai_private"]) == ("processed", True)


def private_folder_mode(path: str) -> int:
    return stat.S_IMODE(os.stat(path).st_mode) if os.path.isdir(path) else -1


async def test_choosing_ordnungs_own_inbox_folder_creates_it(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        suggested = (await api.client.get("/api/folder")).json()["suggested"]
        response = await api.client.put(
            "/api/settings", json={"inbox_dir": suggested, "inbox_auto_read": True}
        )
        assert response.status_code == 200 and response.json()["inbox_auto_read"] is True
        assert private_folder_mode(suggested) == 0o700
        status = (await api.client.get("/api/folder")).json()
        assert status["folder"] == suggested and status["auto_read"] is True


async def test_delete_everything_stops_watching(data_dir: Path, tmp_path: Path) -> None:
    scans = tmp_path / "Scans"
    scans.mkdir()
    async with api_for(data_dir) as api, lifespan(api.app):
        await api.client.put("/api/settings", json={"inbox_dir": str(scans)})
        await eventually_json(api, "/api/folder", lambda body: body["state"] == "watching")
        response = await api.client.request("DELETE", "/api/data", json={"confirm": "DELETE"})
        assert response.status_code == 200
        status = (await api.client.get("/api/folder")).json()
        assert (status["folder"], status["state"]) == (None, "off")
        (scans / "after.pdf").write_bytes(INVOICE_LETTER.pdf())
        await asyncio.sleep(0.5)
        assert (await api.client.get("/api/documents")).json() == []


async def test_keep_private_can_be_undone(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await waiting_letter(api, INVOICE_LETTER.pdf(), "rechnung.pdf")
        await api.client.post("/api/documents/held/keep-private", json={"doc_ids": [doc_id]})
        undone = await api.client.post("/api/documents/held/wait", json={"doc_ids": [doc_id]})
        assert undone.status_code == 200
        assert [(doc["id"], doc["status"]) for doc in undone.json()["documents"]] == [(doc_id, "held")]
        assert (await api.client.get("/api/folder")).json()["waiting"] == 1
        again = (await api.client.post("/api/documents/held/wait", json={"doc_ids": [doc_id]})).json()
        assert again == {"documents": [], "jobs": [], "skipped": [doc_id]}  # it waits already


async def test_today_says_letters_wait_and_files_them_nowhere_else(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        await api.upload(("rechnung.pdf", INVOICE_LETTER.pdf()))
        await api.read_all()
        doc_id = await waiting_letter(api, TAX_LETTER.pdf(), "bescheid.pdf")
        today = (await api.client.get("/api/dashboard")).json()
        assert today["waiting"] == 1
        assert doc_id not in [doc["id"] for doc in today["recent_documents"]]
        assert "other" not in [area["area"] for area in today["areas"]]  # not filed as "Other"
        await api.client.post("/api/documents/held/keep-private", json={"doc_ids": [doc_id]})
        assert (await api.client.get("/api/dashboard")).json()["waiting"] == 0


async def test_an_email_nested_too_deeply_is_refused_with_a_reason(data_dir: Path) -> None:
    deep = b"From: a@example.org\r\nSubject: tief\r\nMIME-Version: 1.0\r\n" + b"".join(
        b'Content-Type: multipart/mixed; boundary="b%d"\r\n\r\n--b%d\r\n' % (n, n) for n in range(1000)
    )
    async with api_for(data_dir) as api:
        response = await api.client.post(
            "/api/documents", files=[("files", ("tief.eml", deep))], data={"combine": "false"}
        )
        assert response.status_code == 422
        assert response.json()["errors"] == [{"filename": "tief.eml", "detail": TOO_DEEP}]
