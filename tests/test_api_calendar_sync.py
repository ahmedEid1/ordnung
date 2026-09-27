"""The API behind Settings → Calendar → "Sync to your own calendar" (CalDAV), against the fake server.

Status (available, connected, the saved password), the preview in both modes, connecting with the
refusals the web app places next to a field (``code``), syncing now, disconnecting, the demo's
refusal, and that the app password never comes back in any answer. Also what calendar sync means
for the rest of Ordnung: no "import the calendar file" Idea while connected, and "Delete everything"
takes Ordnung's events and the app password out of the calendar and the keyring first.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from fake_caldav import CALENDAR_PATH, PASSWORD, USERNAME, FakeCalDav, MemorySecrets
from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.api.routes import calendar_sync
from ordnung.api.routes.data import wipe_data_dir
from ordnung.calendar import caldav
from ordnung.calendar.secrets import SecretsUnavailable, account_name, install_command
from ordnung.ingest.pipeline import run_triggers
from test_api_support import Api, api_for

URL = "https://cal.example.org" + CALENDAR_PATH
CONNECT = {"url": URL, "username": USERNAME, "password": PASSWORD, "mode": "discreet"}


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@asynccontextmanager
async def calendar_api(
    data_dir: Path, server: FakeCalDav, secrets: MemorySecrets, *, demo: bool = False
) -> AsyncIterator[Api]:
    async with api_for(data_dir, demo=demo) as api:
        seed_ledger(api.ctx.store)
        api.app.dependency_overrides[calendar_sync.get_secrets] = lambda: secrets
        api.app.dependency_overrides[calendar_sync.get_transport] = server.transport
        yield api


async def test_status_before_and_after_connecting(data_dir: Path) -> None:
    server, secrets = FakeCalDav(), MemorySecrets()
    async with calendar_api(data_dir, server, secrets) as api:
        before = (await api.client.get("/api/calendar/sync")).json()
        assert before["available"] and before["unavailable"] is None and before["install_command"] is None
        assert not before["connected"] and before["url"] is None and before["mode"] == "discreet"
        assert before["events"] > 5 and before["synced"] == 0 and before["last_sync"] is None

        connected = await api.client.put("/api/calendar/sync", json=CONNECT)
        assert connected.status_code == 200, connected.text
        body = connected.json()
        assert body["connected"] and body["url"] == URL and body["username"] == USERNAME
        assert body["calendar_name"] == "Ordnung" and body["password_saved"] and not body["paused"]
        assert body["synced"] == body["events"] == len(server.resources)
        assert body["last_sync"]["sent"] == body["events"] and body["last_sync"]["error"] is None
        assert PASSWORD not in connected.text
        assert (await api.client.get("/api/calendar/sync")).json() == body


async def test_the_preview_shows_each_event_in_the_chosen_mode(data_dir: Path) -> None:
    async with calendar_api(data_dir, FakeCalDav(), MemorySecrets()) as api:
        discreet = (await api.client.get("/api/calendar/sync/preview")).json()
        full = (await api.client.get("/api/calendar/sync/preview", params={"mode": "full"})).json()
        assert discreet["mode"] == "discreet" and full["mode"] == "full"
        assert [e["uid"] for e in discreet["events"]] == [e["uid"] for e in full["events"]]
        plain = {"Ordnung: deadline", "Ordnung: payment", "Ordnung: appointment", "Ordnung: money in"}
        assert {e["summary"] for e in discreet["events"]} <= plain | {f"{t} — check the date" for t in plain}
        assert "Musterstadt" not in json.dumps(discreet) and "Musterstadt" in json.dumps(full)
        appointment = next(e for e in full["events"] if not e["all_day"])
        assert appointment["start"] == "2026-10-14T10:00:00+02:00"
        assert (
            await api.client.get("/api/calendar/sync/preview", params={"mode": "loud"})
        ).status_code == 422


@pytest.mark.parametrize(
    ("change", "server_change", "status", "code"),
    [
        ({"url": "http://cal.example.org/dav/"}, {}, 422, "address"),
        ({"url": "not a url"}, {}, 422, "address"),
        ({"username": "  "}, {}, 422, "auth"),
        ({"password": "wrong"}, {}, 422, "auth"),
        ({"password": ""}, {}, 422, "auth"),
        ({}, {"calendar": False}, 422, "not_calendar"),
        ({}, {"path": "/elsewhere/"}, 422, "not_found"),
        ({}, {"override": (503, {}, b"")}, 502, "server"),
    ],
)
async def test_refusals_carry_a_code_for_the_field_and_store_nothing(
    data_dir: Path, change: dict[str, str], server_change: dict[str, object], status: int, code: str
) -> None:
    server, secrets = FakeCalDav(**server_change), MemorySecrets()  # type: ignore[arg-type]
    async with calendar_api(data_dir, server, secrets) as api:
        refused = await api.client.put("/api/calendar/sync", json={**CONNECT, **change})
        assert refused.status_code == status and refused.json()["code"] == code, refused.text
        assert PASSWORD not in refused.text and "wrong" not in refused.text
        assert caldav.load_state(api.ctx.store) is None and secrets.saved == {}


async def test_finding_the_calendars_of_an_account(data_dir: Path) -> None:
    server, secrets = FakeCalDav(), MemorySecrets()
    async with calendar_api(data_dir, server, secrets) as api:
        find = {"url": "https://cal.example.org/", "username": USERNAME, "password": PASSWORD}
        body = (await api.client.post("/api/calendar/sync/discover", json=find)).json()
        assert body == {
            "calendars": [
                {"url": URL, "name": "Ordnung"},
                {"url": "https://cal.example.org/dav/calendars/sam/personal/", "name": "Personal"},
            ]
        }
        assert (
            "PUT" not in server.methods() and secrets.saved == {} and caldav.load_state(api.ctx.store) is None
        )
        wrong = await api.client.post("/api/calendar/sync/discover", json={**find, "password": "wrong"})
        assert wrong.status_code == 422 and wrong.json()["code"] == "auth" and "wrong" not in wrong.text
        assert (await api.client.post("/api/calendar/sync/discover", json={"url": URL})).status_code == 422


async def test_the_request_is_checked(data_dir: Path) -> None:
    async with calendar_api(data_dir, FakeCalDav(), MemorySecrets()) as api:
        for bad in ({**CONNECT, "extra": 1}, {**CONNECT, "mode": "loud"}, {"url": URL}):
            assert (await api.client.put("/api/calendar/sync", json=bad)).status_code == 422, bad


async def test_changing_the_mode_keeps_the_saved_password(data_dir: Path) -> None:
    server, secrets = FakeCalDav(), MemorySecrets()
    async with calendar_api(data_dir, server, secrets) as api:
        await api.client.put("/api/calendar/sync", json=CONNECT)
        full = await api.client.put("/api/calendar/sync", json={**CONNECT, "password": None, "mode": "full"})
        assert full.status_code == 200 and full.json()["mode"] == "full"
        assert full.json()["last_sync"]["sent"] == len(server.resources)
        assert any(b"Musterstadt" in body for body in server.resources.values())
        elsewhere = await api.client.put(
            "/api/calendar/sync", json={**CONNECT, "url": "https://other.example.org/cal/"}
        )
        assert elsewhere.status_code == 409 and elsewhere.json()["code"] == "conflict"


async def test_sync_now_sends_what_changed_and_says_when_nothing_is_connected(data_dir: Path) -> None:
    server, secrets = FakeCalDav(), MemorySecrets()
    async with calendar_api(data_dir, server, secrets) as api:
        idle = await api.client.post("/api/calendar/sync/run")
        assert idle.status_code == 409 and idle.json()["code"] == "not_connected"
        await api.client.put("/api/calendar/sync", json=CONNECT)
        items = [i for i in api.ctx.store.list_items() if i.status == "open" and i.due_date]
        api.ctx.store.update_item(items[0].id, status="done")
        ran = (await api.client.post("/api/calendar/sync/run")).json()
        assert ran["last_sync"]["removed"] == 1 and ran["synced"] == len(server.resources)
        # the server refuses the password now: reported, and automatic syncing pauses
        server.password = "rotated"
        api.ctx.store.update_item(items[1].id, status="done")
        failed = (await api.client.post("/api/calendar/sync/run")).json()
        assert failed["paused"] and failed["last_sync"]["error_kind"] == "auth"


async def test_disconnecting_with_and_without_removing_the_events(data_dir: Path) -> None:
    server, secrets = FakeCalDav(), MemorySecrets()
    async with calendar_api(data_dir, server, secrets) as api:
        await api.client.put("/api/calendar/sync", json=CONNECT)
        count = len(server.resources)
        gone = await api.client.post("/api/calendar/sync/disconnect", json={"remove_events": True})
        assert gone.status_code == 200 and gone.json() == {"removed": count}
        assert server.resources == {} and secrets.saved == {}
        assert not (await api.client.get("/api/calendar/sync")).json()["connected"]

        await api.client.put("/api/calendar/sync", json=CONNECT)
        kept = await api.client.post("/api/calendar/sync/disconnect", json={"remove_events": False})
        assert kept.json() == {"removed": 0} and len(server.resources) == count


async def test_a_calendar_that_cant_be_reached_keeps_the_connection_on_disconnect(data_dir: Path) -> None:
    server, secrets = FakeCalDav(), MemorySecrets()
    async with calendar_api(data_dir, server, secrets) as api:
        await api.client.put("/api/calendar/sync", json=CONNECT)
        server.raises = httpx.ConnectError("down")
        refused = await api.client.post("/api/calendar/sync/disconnect", json={"remove_events": True})
        assert refused.status_code == 502 and refused.json()["code"] == "network"
        assert (await api.client.get("/api/calendar/sync")).json()["connected"]
        kept = await api.client.post("/api/calendar/sync/disconnect", json={"remove_events": False})
        assert kept.status_code == 200 and secrets.saved == {}


async def test_without_a_password_store_it_says_what_to_install(data_dir: Path) -> None:
    secrets = MemorySecrets(SecretsUnavailable("Needs an extra package.", install=install_command()))
    async with calendar_api(data_dir, FakeCalDav(), secrets) as api:
        body = (await api.client.get("/api/calendar/sync")).json()
        assert not body["available"] and body["unavailable"] == "Needs an extra package."
        assert body["install_command"] == install_command()
        refused = await api.client.put("/api/calendar/sync", json=CONNECT)
        assert refused.status_code == 409 and refused.json()["code"] == "unavailable"


async def test_a_password_not_on_this_computer_is_shown(data_dir: Path) -> None:
    server, secrets = FakeCalDav(), MemorySecrets()
    async with calendar_api(data_dir, server, secrets) as api:
        await api.client.put("/api/calendar/sync", json=CONNECT)
        secrets.saved.pop(account_name(USERNAME, URL))
        body = (await api.client.get("/api/calendar/sync")).json()
        assert body["connected"] and not body["password_saved"]


async def test_the_demo_never_connects(data_dir: Path) -> None:
    server, secrets = FakeCalDav(), MemorySecrets()
    async with calendar_api(data_dir, server, secrets, demo=True) as api:
        body = (await api.client.get("/api/calendar/sync")).json()
        assert not body["available"] and "demo" in body["unavailable"]
        for method, path, payload in (
            ("PUT", "/api/calendar/sync", CONNECT),
            ("POST", "/api/calendar/sync/run", None),
            ("POST", "/api/calendar/sync/discover", {"url": URL, "username": USERNAME, "password": PASSWORD}),
        ):
            refused = await api.client.request(method, path, json=payload)
            assert refused.status_code == 409 and refused.json()["code"] == "unavailable"
        assert server.requests == [] and secrets.saved == {}
        assert (await api.client.get("/api/calendar/sync/preview")).status_code == 200


# --------------------------------------------------------------------------------------------------
# calendar sync and the rest of Ordnung
# --------------------------------------------------------------------------------------------------


def calendar_ideas(api: Api) -> list[str]:
    return [s.title for s in api.ctx.store.list_suggestions(status="new") if s.rule_id == "calendar_outdated"]


async def test_a_connected_calendar_is_not_told_to_import_the_calendar_file(data_dir: Path) -> None:
    server, secrets = FakeCalDav(), MemorySecrets()
    async with calendar_api(data_dir, server, secrets) as api:
        api.ctx.store.set_meta("last_calendar_export_at", None)  # never exported: "Add your N dates…"
        await run_triggers(api.ctx)
        assert calendar_ideas(api)  # the calendar file is the way to a calendar
        assert (await api.client.put("/api/calendar/sync", json=CONNECT)).status_code == 200
        assert calendar_ideas(api) == []  # the dates go there by themselves: importing would clash
        api.ctx.store.update_item(
            next(i.id for i in api.ctx.store.list_items() if i.status == "open" and i.due_date),
            title="Renamed",
        )
        await run_triggers(api.ctx)
        assert calendar_ideas(api) == []  # a new or changed date is synced, not a reason to import
        await api.client.post("/api/calendar/sync/disconnect", json={"remove_events": True})
        assert calendar_ideas(api)  # without sync the file is the way again


async def test_delete_everything_takes_ordnungs_events_and_password_out_of_the_calendar_first(
    data_dir: Path,
) -> None:
    server, secrets = FakeCalDav(), MemorySecrets()
    async with calendar_api(data_dir, server, secrets) as api:
        await api.client.put("/api/calendar/sync", json=CONNECT)
        theirs = CALENDAR_PATH + "dentist.ics"
        server.resources[theirs] = b"not Ordnung's"
        ordnungs = len(server.resources) - 1
        assert ordnungs > 5 and secrets.saved

        # the calendar can't be reached: nothing is deleted, and the answer says how to go on
        server.raises = httpx.ConnectError("down")
        refused = await api.client.request("DELETE", "/api/data", json={"confirm": "DELETE"})
        assert refused.status_code == 409
        detail = refused.json()["detail"]
        assert (
            "nothing was deleted" in detail and "Settings → Calendar" in detail and "Couldn't reach" in detail
        )
        assert api.ctx.store.list_items() and caldav.load_state(api.ctx.store) is not None and secrets.saved

        server.raises = None
        done = await api.client.request("DELETE", "/api/data", json={"confirm": "DELETE"})
        assert done.status_code == 200 and done.json()["calendar_events_removed"] == ordnungs
        assert list(server.resources) == [theirs]  # only Ordnung's own left the calendar
        assert secrets.saved == {}  # the app password is not left in the keyring
        assert caldav.load_state(api.ctx.store) is None and api.ctx.store.list_items() == []

        # nothing connected: nothing to remove, and no password store is asked
        again = await api.client.request("DELETE", "/api/data", json={"confirm": "DELETE"})
        assert again.status_code == 200 and again.json()["calendar_events_removed"] is None


async def test_a_sync_running_while_everything_is_deleted_cant_write_its_record_back(data_dir: Path) -> None:
    server, secrets = FakeCalDav(), MemorySecrets()
    async with calendar_api(data_dir, server, secrets) as api:
        store = api.ctx.store
        await api.client.put("/api/calendar/sync", json=CONNECT)
        started, release = threading.Event(), threading.Event()

        def slow_sync() -> None:  # what a sync of the tick does, slowly: read the record, write it back
            with caldav.exclusive():
                state = caldav.load_state(store)
                started.set()
                release.wait(10)
                caldav.save_state(store, state)

        syncing = threading.Thread(target=slow_sync)
        syncing.start()
        assert started.wait(10)
        wiping = threading.Thread(target=wipe_data_dir, args=(api.ctx, secrets, server.transport()))
        wiping.start()
        await asyncio.sleep(0.3)
        assert wiping.is_alive()  # it waits for the sync
        release.set()
        syncing.join(10)
        wiping.join(30)
        assert caldav.load_state(store) is None and secrets.saved == {}
