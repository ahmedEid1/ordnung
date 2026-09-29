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
from ordnung.api.routes import data as data_routes
from ordnung.ingest.intake import TOO_DEEP
from ordnung.ingest.pipeline import add_file
from ordnung.llm.replay import ReplayBackend
from ordnung.secretary.brief import brief_key
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


async def test_a_folder_chosen_again_counts_as_chosen_now(data_dir: Path, tmp_path: Path) -> None:
    """*Stop watching*, then choosing the same folder again with "read new files" on: what landed in it
    meanwhile was already there when it was chosen, so it waits (the switch promises that); files that
    arrive afterwards are read at once."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    async with api_for(data_dir) as api, lifespan(api.app):
        api.app.state.ordnung.folder.settle_s = 0.2
        api.app.state.ordnung.folder.tick_ms = 50
        chosen = {"inbox_dir": str(downloads), "inbox_auto_read": True}
        assert (await api.client.put("/api/settings", json=chosen)).status_code == 200
        await eventually_json(api, "/api/folder", lambda body: body["state"] == "watching")
        await api.client.put("/api/settings", json={"inbox_dir": None})  # Stop watching
        assert (await api.client.get("/api/folder")).json()["state"] == "off"

        (downloads / "kontoauszug.pdf").write_bytes(TAX_LETTER.pdf())  # downloaded while not watched
        assert (await api.client.put("/api/settings", json=chosen)).status_code == 200
        status = await eventually_json(api, "/api/folder", lambda body: body["waiting"] == 1)
        assert [pickup["filename"] for pickup in status["recent"]] == ["kontoauszug.pdf"]

        (downloads / "rechnung.pdf").write_bytes(INVOICE_LETTER.pdf())  # arrives now: read at once
        status = await eventually_json(api, "/api/folder", lambda body: len(body["recent"]) == 2)
        by_name = {pickup["filename"]: pickup["status"] for pickup in status["recent"]}
        assert by_name["kontoauszug.pdf"] == "held" and by_name["rechnung.pdf"] != "held"


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
        assert response.json()["code"] == "demo_replay"  # the app says it as the demo's limit, not a failure
        kept = await api.client.post("/api/documents/held/keep-private", json={"doc_ids": [doc_id]})
        assert kept.status_code == 200


async def test_a_waiting_letter_is_not_read_again_or_made_public_behind_the_person(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        doc_id = await waiting_letter(api, INVOICE_LETTER.pdf(), "rechnung.pdf")
        response = await api.client.post(f"/api/documents/{doc_id}/reprocess")
        assert response.status_code == 409 and "isn't read yet" in response.json()["detail"]
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


async def test_when_delete_everything_fails_the_folder_is_watched_again(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scans = tmp_path / "Scans"
    scans.mkdir()

    def locked(ctx: Any, *args: Any) -> None:
        raise OSError("a file is locked")

    async with api_for(data_dir) as api, lifespan(api.app):
        await api.client.put("/api/settings", json={"inbox_dir": str(scans)})
        await eventually_json(api, "/api/folder", lambda body: body["state"] == "watching")
        monkeypatch.setattr(data_routes, "wipe_data_dir", locked)
        with pytest.raises(OSError, match="locked"):
            await api.client.request("DELETE", "/api/data", json={"confirm": "DELETE"})
        status = await eventually_json(api, "/api/folder", lambda body: body["state"] == "watching")
        assert status["folder"] == str(scans.resolve())


async def test_when_the_calendar_keeps_everything_the_folder_is_watched_again(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration of the watched folder with calendar sync: "Delete everything" answers 409 and deletes
    nothing when a connected calendar's events can't be removed first — the folder is watched again."""
    scans = tmp_path / "Scans"
    scans.mkdir()

    def calendar_unreachable(ctx: Any, *args: Any) -> None:
        raise data_routes.CalendarNotCleared("The calendar couldn't be reached, so nothing was deleted.")

    async with api_for(data_dir) as api, lifespan(api.app):
        await api.client.put("/api/settings", json={"inbox_dir": str(scans)})
        await eventually_json(api, "/api/folder", lambda body: body["state"] == "watching")
        monkeypatch.setattr(data_routes, "wipe_data_dir", calendar_unreachable)
        refused = await api.client.request("DELETE", "/api/data", json={"confirm": "DELETE"})
        assert refused.status_code == 409 and "nothing was deleted" in refused.json()["detail"]
        status = await eventually_json(api, "/api/folder", lambda body: body["state"] == "watching")
        assert status["folder"] == str(scans.resolve())


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


async def test_the_code_written_note_is_never_all_clear_while_letters_wait(data_dir: Path) -> None:
    """A fresh install whose folder brought two scans: Ordnung's own note says nothing is due from what
    was read — not "all clear" — and it follows each pickup and answer, even once one was stored."""
    async with api_for(data_dir) as api:
        stored = (await api.client.post("/api/brief")).json()  # the morning's note, nothing waiting yet
        assert stored["source"] == "template" and stored["text"].startswith("All clear")
        assert (await api.client.get("/api/brief")).json() == stored  # still the same: kept, with its time

        first = await waiting_letter(api, TAX_LETTER.pdf(), "scan-1.pdf")
        await waiting_letter(api, INVOICE_LETTER.pdf(), "scan-2.pdf")
        note = (await api.client.get("/api/brief")).json()
        assert note["text"] == "Nothing is due in the next 7 days from the letters that were read."
        assert "All clear" not in note["text"] and note["generated_at"] is None
        assert api.ctx.store.get_meta(brief_key(clock.today())) is not None  # GET stored nothing new

        await api.client.post("/api/documents/held/keep-private", json={"doc_ids": [first]})
        assert "All clear" not in (await api.client.get("/api/brief")).json()["text"]  # one still waits
        waiting = (await api.client.get("/api/folder")).json()["waiting"]
        assert waiting == 1


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


async def test_answers_run_their_transactions_off_the_event_loop(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Up to 500 letters with their e-mails' attachments and activity entries: "Read these", "Keep
    private" and "Undo" must not hold up every other request and the live updates meanwhile."""
    import threading

    from ordnung.ingest import held

    loop_thread = threading.get_ident()
    seen: list[int] = []
    for name in ("release", "keep_private", "back_to_waiting"):
        real = getattr(held, name)

        def recording(*args: Any, _real: Any = real, **kwargs: Any) -> Any:
            seen.append(threading.get_ident())
            return _real(*args, **kwargs)

        monkeypatch.setattr(held, name, recording)
    async with api_for(data_dir) as api:
        doc_id = await waiting_letter(api, INVOICE_LETTER.pdf(), "rechnung.pdf")
        for path in ("keep-private", "wait", "read"):
            assert (
                await api.client.post(f"/api/documents/held/{path}", json={"doc_ids": [doc_id]})
            ).status_code == 200
    assert len(seen) == 3 and loop_thread not in seen
