"""The *Text in pictures* switch (Settings → Data, ADR 0024): the person's own on/off for reading the words in photos
and scans Claude isn't reading. Saved off, search and the letter's page leave those words out at once, a reading
under way stops (Tesseract is killed) and every word read is deleted; saved on, reading starts without the start
delay. ``ORDNUNG_OCR=off`` stays a hard off for one computer, whatever the switch says. ``GET /api/health`` says
what this computer does (``picture_text``, the doctor's row as a state; none for a phone). The switch is the
person's choice: a save is a person write, and it travels with hand-off sync.

The worker's loop itself is tested in ``test_worker_pictures.py``, the doctor's row in ``test_doctor_pictures.py``,
the 0.3.x round trip of the setting in ``test_sync_scrub.py``."""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from helpers_docs import photo
from ordnung import clock, doctor
from ordnung.config import OCR_SWITCH, picture_text_off
from ordnung.ingest import ocr
from ordnung.ingest.ocr import Tesseract
from test_api_support import TODAY, Api, api_for

FAKE_TESSERACT = Path(__file__).resolve().parent / "fake_tesseract.py"
#: A Tesseract as ``find`` answers for an installed 5.3.4 with German and English.
INSTALLED = Tesseract("/usr/bin/tesseract", (5, 3, 4), ("deu", "eng"))
WORDS = "Hausverwaltung Beispiel GmbH · Ihr Kellerabteil 7"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def ocr_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Text in pictures on (``tests/conftest.py`` turns it off for every test)."""
    monkeypatch.delenv(OCR_SWITCH)


async def wait_for(condition: Callable[[], bool], seconds: float = 10.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


async def private_photo(api: Api, name: str = "foto.jpg", width: int = 200) -> str:
    """A photo kept private, read on this computer (no model): its page has no text, so its picture is read."""
    upload = await api.upload((name, photo("JPEG", size=(width, 100))), private=True)
    await api.read_all()
    return str(upload["documents"][0]["id"])


async def save(api: Api, **changes: Any) -> dict[str, Any]:
    response = await api.client.put("/api/settings", json=changes)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def found(api: Api, query: str) -> dict[str, str | None]:
    rows = (await api.client.get("/api/documents", params={"q": query})).json()
    return {row["id"]: row["found_in"] for row in rows}


def picture_files(api: Api) -> list[Path]:
    return sorted(api.ctx.store.paths.derived.rglob("picture-text.json"))


def picture_loops() -> list[asyncio.Task[Any]]:
    """The worker's picture loops alive now (never more than one)."""
    return [task for task in asyncio.all_tasks() if task.get_name() == "ordnung-pictures" and not task.done()]


class StandIn:
    """Stands in for the engine: ``find`` counts its looks, a reading answers :data:`WORDS` for every picture."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, engine: Tesseract | None = INSTALLED) -> None:
        self.engine = engine
        self.found: list[str] = []
        self.read: list[str] = []
        monkeypatch.setattr(
            ocr, "page_picture", lambda original, mime, page: f"{original.name}:{page}".encode()
        )
        monkeypatch.setattr(ocr, "recognise", self.recognise)

    def find(self) -> Tesseract | None:
        self.found.append("find")
        return self.engine

    def recognise(
        self, engine: Tesseract, png: bytes, *, stop: threading.Event | None = None, **_: object
    ) -> str:
        self.read.append(png.decode())
        return WORDS


# --------------------------------------------------------------------------------------------------
# the setting and the routes
# --------------------------------------------------------------------------------------------------


def test_the_effective_switch_is_off_when_either_says_off() -> None:
    """Off in Settings, or ``ORDNUNG_OCR=off`` (which only ever turns it off): ``picture_text_off``."""
    assert picture_text_off(False, env={}) and picture_text_off(True, env={OCR_SWITCH: "off"})
    assert picture_text_off(False, env={OCR_SWITCH: "on"})
    assert not picture_text_off(True, env={}) and not picture_text_off(True, env={OCR_SWITCH: "on"})


async def test_settings_patch_takes_read_picture_text(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``PUT /api/settings`` saves the switch (on by default, the 0.3.0 behaviour), and has the worker follow it
    whenever a save names it, after the save; anything but a boolean is refused."""
    async with api_for(data_dir) as api:
        told: list[bool] = []

        async def changed() -> None:
            told.append(api.ctx.settings.read_picture_text)

        monkeypatch.setattr(api.ctx.worker, "picture_text_changed", changed)
        assert (await api.client.get("/api/settings")).json()["read_picture_text"] is True
        assert (await save(api, read_picture_text=False))["read_picture_text"] is False
        assert api.ctx.store.get_settings().read_picture_text is False and told == [False]
        await save(api, llm_review=False)  # another setting: the worker isn't told
        assert told == [False]
        assert (await save(api, read_picture_text=True))["read_picture_text"] is True and told == [
            False,
            True,
        ]
        refused = await api.client.put("/api/settings", json={"read_picture_text": "maybe"})
        assert refused.status_code == 422 and told == [False, True]


async def test_saving_the_switch_off_hides_picture_text_from_search_and_the_page_at_once(
    data_dir: Path, ocr_on: None
) -> None:
    """Search and the letter's page leave the words read in pictures out from the moment the switch is saved off,
    before the worker has deleted them; on again, they count again."""
    async with api_for(data_dir) as api:
        doc_id = await private_photo(api)
        assert api.ctx.store.write_picture_text(doc_id, 1, WORDS)
        assert await found(api, "Kellerabteil") == {doc_id: "picture_text"}
        await save(api, read_picture_text=False)
        assert await found(api, "Kellerabteil") == {}
        assert await found(api, "foto") == {doc_id: "letter"}  # its own words still find it
        detail = (await api.client.get(f"/api/documents/{doc_id}")).json()
        assert detail["picture_text_pages"] == []
        await save(api, read_picture_text=True)  # the worker isn't running here: nothing was deleted yet
        assert await found(api, "Kellerabteil") == {doc_id: "picture_text"}
        assert (await api.client.get(f"/api/documents/{doc_id}")).json()["picture_text_pages"] == [1]


async def test_the_variable_forces_off_whatever_the_setting(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ORDNUNG_OCR=off`` (as in every test) wins: with the switch saved on, nothing is looked for or read, search
    ignores the words read before, the worker deletes them, and health says the variable turned it off."""
    async with api_for(data_dir) as api:
        stand_in = StandIn(monkeypatch)
        api.ctx.worker.find_tesseract = stand_in.find
        api.ctx.worker.catch_up_delay_s = 0
        doc_id = await private_photo(api)
        assert api.ctx.store.write_picture_text(doc_id, 1, WORDS)
        await save(api, read_picture_text=True)
        assert await found(api, "Kellerabteil") == {}
        await api.ctx.worker.start()
        try:
            await wait_for(lambda: picture_files(api) == [])
            await save(api, read_picture_text=False)
            await save(api, read_picture_text=True)
            await asyncio.sleep(0.2)
            assert stand_in.found == [] and stand_in.read == [] and picture_loops() == []
        finally:
            await api.ctx.worker.stop()
        health = (await api.client.get("/api/health")).json()
        assert health["picture_text"] == {
            "state": "off_by_variable",
            "detail": "Turned off (ORDNUNG_OCR=off)",
            "fix": None,
        }


# --------------------------------------------------------------------------------------------------
# the worker follows the switch
# --------------------------------------------------------------------------------------------------


async def test_switching_off_stops_a_reading_and_forgets_every_word(
    data_dir: Path, ocr_on: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Saved off while (the fake) Tesseract reads a page: the reading is stopped within a poll and Tesseract is
    killed, nothing of it is kept, every word read in pictures before is deleted, and the loop ends. The worker
    goes on reading letters."""
    async with api_for(data_dir) as api:
        kept = await private_photo(api, "alt.jpg", width=201)
        assert api.ctx.store.write_picture_text(kept, 1, WORDS)
        reading = await private_photo(api, "foto.jpg", width=202)
        report = tmp_path / "report.json"  # the fake Tesseract writes it once it has the picture
        monkeypatch.setenv("FAKE_TESSERACT_MODE", "hang")
        monkeypatch.setenv("FAKE_TESSERACT_REPORT", str(report))
        fake = Tesseract(
            str(FAKE_TESSERACT), (5, 3, 4), ("deu", "eng"), launcher=(sys.executable, str(FAKE_TESSERACT))
        )
        worker = api.ctx.worker
        worker.find_tesseract = lambda: fake
        worker.catch_up_delay_s = 0
        await worker.start()
        try:
            await wait_for(report.exists)
            assert len(picture_loops()) == 1
            saving = time.monotonic()
            await save(api, read_picture_text=False)
            assert time.monotonic() - saving < 5
            assert picture_files(api) == [] and picture_loops() == []
            assert api.ctx.store.picture_text_matches("Kellerabteil") == set()
            assert worker.running  # letters are still read
            if sys.platform != "win32":  # Tesseract is gone (signal 0 only asks)
                import os

                with pytest.raises(ProcessLookupError):
                    os.kill(json.loads(report.read_text("utf-8"))["pid"], 0)
        finally:
            await worker.stop()
        assert (reading, 1) in api.ctx.store.picture_text_due()  # read once the switch is on again


async def test_switching_on_starts_reading_without_the_startup_wait(
    data_dir: Path, ocr_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Started with the switch off, the worker looks for nothing. Saved on, it looks for Tesseract afresh (it may
    have been installed meanwhile) and reads at once, not after the start delay."""
    async with api_for(data_dir) as api:
        stand_in = StandIn(monkeypatch)
        worker = api.ctx.worker
        worker.find_tesseract = stand_in.find
        await save(api, read_picture_text=False)
        doc_id = await private_photo(api)
        worker.catch_up_delay_s = 3600  # the start delay would never end within the test
        await worker.start()
        try:
            await asyncio.sleep(0.2)
            assert stand_in.found == [] and picture_loops() == []
            await save(api, read_picture_text=True)
            await wait_for(lambda: api.ctx.store.picture_text_pages(doc_id) == [1], seconds=5)
            assert stand_in.found == ["find"] and len(picture_loops()) == 1
            assert await found(api, "Kellerabteil") == {doc_id: "picture_text"}
        finally:
            await worker.stop()
        assert picture_loops() == []


@pytest.mark.parametrize("last", [True, False], ids=["ends on", "ends off"])
async def test_switching_off_and_on_quickly_leaves_one_loop(
    data_dir: Path, ocr_on: None, monkeypatch: pytest.MonkeyPatch, last: bool
) -> None:
    """Saves of the switch made at the same time, off and on and off and on: each is handled in turn, never two
    loops at once, and the worker ends as the last save says — one loop reading when on, none and no word left
    when off."""
    async with api_for(data_dir) as api:
        stand_in = StandIn(monkeypatch)
        worker = api.ctx.worker
        worker.find_tesseract = stand_in.find
        worker.catch_up_delay_s = 0
        worker.pictures_poll_s = 3600
        doc_id = await private_photo(api)
        await worker.start()
        try:
            await wait_for(lambda: api.ctx.store.picture_text_pages(doc_id) == [1])
            most = 0

            async def watch() -> None:
                nonlocal most
                while True:
                    most = max(most, len(picture_loops()))
                    await asyncio.sleep(0)

            watcher = asyncio.create_task(watch())
            await asyncio.gather(
                *(save(api, read_picture_text=value) for value in (False, True, False, True))
            )
            # whichever save landed last, the worker does what is saved now
            assert bool(picture_loops()) is api.ctx.store.get_settings().read_picture_text
            await save(api, read_picture_text=not last)
            await save(api, read_picture_text=last)
            assert api.ctx.store.get_settings().read_picture_text is last
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            assert most <= 1
            if last:
                assert len(picture_loops()) == 1
                await wait_for(lambda: api.ctx.store.picture_text_pages(doc_id) == [1])
            else:
                assert picture_loops() == [] and picture_files(api) == []
        finally:
            await worker.stop()
        assert picture_loops() == []


async def test_a_stopped_worker_is_not_started_by_the_switch(
    data_dir: Path, ocr_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While the worker is stopped (hand-off sync standing this computer by) a save starts nothing and deletes
    nothing; the next start reads the switch: off, it deletes the words read before."""
    async with api_for(data_dir) as api:
        stand_in = StandIn(monkeypatch)
        api.ctx.worker.find_tesseract = stand_in.find
        doc_id = await private_photo(api)
        assert api.ctx.store.write_picture_text(doc_id, 1, WORDS)
        await save(api, read_picture_text=False)
        await save(api, read_picture_text=True)
        await save(api, read_picture_text=False)
        assert picture_loops() == [] and stand_in.found == [] and len(picture_files(api)) == 1
        await api.ctx.worker.start()
        try:
            await wait_for(lambda: picture_files(api) == [])
        finally:
            await api.ctx.worker.stop()
        assert stand_in.found == []


# --------------------------------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("read", "variable", "engine", "state"),
    [
        (True, None, INSTALLED, "reading"),
        (False, None, INSTALLED, "off"),
        (True, "off", INSTALLED, "off_by_variable"),
        (True, None, None, "not_installed"),
        (True, None, Tesseract("/usr/bin/tesseract", (4, 0, 0), ("deu", "eng")), "not_usable"),
    ],
)
async def test_health_says_each_state(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    read: bool,
    variable: str | None,
    engine: Tesseract | None,
    state: str,
) -> None:
    """``GET /api/health`` carries this computer's *Text in pictures* in the doctor's words (Settings' card shows
    them): what it found, or why it reads nothing and what to do."""
    monkeypatch.delenv(OCR_SWITCH)
    if variable is not None:
        monkeypatch.setenv(OCR_SWITCH, variable)
    monkeypatch.setattr(ocr, "find", lambda **_: engine)
    async with api_for(data_dir) as api:
        await save(api, read_picture_text=read)
        health = (await api.client.get("/api/health")).json()
        row = doctor.text_in_pictures_check(read_picture_text=read, find=lambda: engine)
        assert health["picture_text"] == {"state": state, "detail": row.detail, "fix": row.fix}


async def test_health_asks_for_tesseract_in_a_thread_and_never_looks_again(
    data_dir: Path, ocr_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain ``GET /api/health`` takes the answer the engine already has (never ``refresh``), off the event loop."""
    asked: list[tuple[dict[str, object], bool]] = []

    def find(**kwargs: object) -> Tesseract:
        asked.append((kwargs, threading.current_thread() is threading.main_thread()))
        return INSTALLED

    monkeypatch.setattr(ocr, "find", find)
    async with api_for(data_dir) as api:
        assert (await api.client.get("/api/health")).json()["picture_text"]["state"] == "reading"
    assert asked and all("refresh" not in kwargs and not on_main for kwargs, on_main in asked)


async def test_a_phone_s_health_has_no_picture_text(data_dir: Path) -> None:
    """A paired phone gets no Text in pictures (it has no Settings card; the computer's state is the computer's)."""
    from phone_support import pair, phone_app, phone_client

    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        assert (await phone.get("/api/health")).json()["picture_text"] is None
        computer = (await api.client.get("/api/health")).json()["picture_text"]
        assert computer["state"] == "off_by_variable"  # the tests' own ORDNUNG_OCR=off


# --------------------------------------------------------------------------------------------------
# the person's choice: it travels
# --------------------------------------------------------------------------------------------------


async def test_the_switch_is_a_person_write_and_travels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With hand-off sync connected, saving the switch is the person's change (a new version for the other
    computers), and a pushed copy keeps it: it is no per-computer setting."""
    from ordnung.backup.archive import database_copy
    from ordnung.sync import LOCAL_SETTINGS, SYNCED_SETTINGS
    from ordnung.sync.scrub import SCRUBBED_SETTINGS, scrub, settings_of
    from sync_fake_engine import counter
    from sync_support import computer, connect, fast_sync

    assert "read_picture_text" in SYNCED_SETTINGS and "read_picture_text" not in LOCAL_SETTINGS
    assert "read_picture_text" not in SCRUBBED_SETTINGS
    fast_sync(monkeypatch)
    (tmp_path / "Nextcloud").mkdir()
    async with computer(tmp_path / "desk") as api:
        await connect(api, tmp_path / "Nextcloud" / "Vault", "desktop")
        before = counter(api.ctx.store)
        await save(api, read_picture_text=False)
        assert counter(api.ctx.store) == before + 1
        await save(api, read_picture_text=False)  # the same value: no change
        assert counter(api.ctx.store) == before + 1
        with contextlib.closing(database_copy(api.ctx.store.db_path)) as copy:
            scrub(
                copy
            )  # what a push carries: the per-computer settings go back to their defaults, not this one
            assert settings_of(copy).read_picture_text is False
