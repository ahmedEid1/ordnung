"""Settings → Phone through the API: turning phone access on and off (never in the demo or without a
session token), pairing (one use, tries, a reused code, the check words), removing and starting over,
an address change, the network watcher, sign-in rotation, what a phone sees of the person's numbers,
uploads from a phone and the refusals that hold even if the allow-list were wrong."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ordnung.api.deps import ApiState
from ordnung.phone import access as access_module
from ordnung.phone import pairing as pairing_module
from ordnung.phone import record as record_module
from ordnung.phone import scope as phone_scope
from ordnung.phone.access import DEVICE_IDLE_DAYS, PREVIOUS_GRACE_S, ROTATE_EVERY_S, PhoneAccess
from ordnung.phone.net import Candidate
from ordnung.phone.record import META_KEY, PhoneRecord, load_record
from phone_support import (
    ADDRESS,
    COOKIE,
    OTHER_PHONE_IP,
    PHONE_IP,
    TOKEN,
    FakeNetwork,
    fake_phone_access,
    onboard,
    pair,
    phone_app,
    phone_client,
    phone_of,
)
from test_api_support import FINE_LETTER, api_for, lifespan

SAMPLES = Path(__file__).resolve().parents[1] / "src" / "ordnung" / "demo" / "samples"
SECOND = "192.168.0.40"


def _two_networks() -> FakeNetwork:
    return FakeNetwork(
        candidates_now=[
            Candidate(ADDRESS, "en0", "192.168.1.0/24", recommended=True),
            Candidate(SECOND, "en7", "192.168.0.0/24"),
        ],
        local={ADDRESS, SECOND},
    )


def _database_bytes(folder: Path) -> bytes:
    return b"".join(p.read_bytes() for p in sorted(folder.glob("ordnung.db*")) if p.is_file())


def _kinds(api: Any, kind: str) -> list[Any]:
    return api.ctx.store.list_activity(limit=None, kinds=[kind])


# --------------------------------------------------------------------------------------------------
# on and off
# --------------------------------------------------------------------------------------------------


async def test_phone_access_is_off_until_turned_on(data_dir: Path) -> None:
    async with phone_app(data_dir, on=False) as (api, _net, servers):
        status = (await api.client.get("/api/phone")).json()
        assert status["available"] is True and status["enabled"] is False and status["listening"] is False
        assert status["devices"] == [] and status["pairing"] is None and status["url"] is None
        assert status["addresses"] == [
            {"address": ADDRESS, "interface": "en0", "subnet": "192.168.1.0/24", "recommended": True}
        ]
        assert servers.made == [] and not api.ctx.paths.phone.exists()
        assert api.ctx.store.get_meta(META_KEY) is None  # reading the status writes nothing


async def test_turning_on_and_off_is_logged_and_saved(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, servers):
        status = (await api.client.get("/api/phone")).json()
        assert status["url"] == f"https://{ADDRESS}:8767" and status["subnet"] == "192.168.1.0/24"
        assert status["fingerprint"] and status["ca_fingerprint"] and status["certificate_until"]
        assert load_record(api.ctx.store).enabled is True
        off = await api.client.put("/api/phone", json={"enabled": False})
        assert off.json()["enabled"] is False and off.json()["listening"] is False
        assert servers.made[-1].stopped == 1
        kinds = [entry.kind for entry in api.ctx.store.list_activity(limit=None)]
        assert "phone.enabled" in kinds and "phone.disabled" in kinds
        assert _kinds(api, "phone.enabled")[0].message == f"Phone access turned on at https://{ADDRESS}:8767"


async def test_turning_on_needs_set_up_a_network_and_a_known_address(data_dir: Path) -> None:
    async with api_for(data_dir, token=TOKEN) as api:
        api.client.headers["Authorization"] = f"Bearer {TOKEN}"
        net, _servers = fake_phone_access(api)
        refused = await api.client.put("/api/phone", json={"enabled": True})
        assert (refused.status_code, refused.json()["code"]) == (409, "not_set_up")
        await onboard(api)
        net.local = set()
        refused = await api.client.put("/api/phone", json={"enabled": True})
        assert (refused.status_code, refused.json()["code"]) == (409, "no_network")
        net.local = {ADDRESS}
        refused = await api.client.put("/api/phone", json={"enabled": True, "address": "192.168.9.9"})
        assert (refused.status_code, refused.json()["code"]) == (422, "invalid")
        refused = await api.client.put("/api/phone", json={"enabled": True, "port": 80})
        assert refused.status_code == 422
        refused = await api.client.put("/api/phone", json={"enabled": True, "token": "x"})
        assert refused.status_code == 422  # unknown fields are refused
        await phone_of(api).stop()


async def test_the_first_free_port_is_chosen_and_a_busy_one_is_a_problem(data_dir: Path) -> None:
    network = FakeNetwork(busy={(ADDRESS, 8767), (ADDRESS, 8768)})
    async with phone_app(data_dir, network=network, on=False) as (api, net, _servers):
        on = (await api.client.put("/api/phone", json={"enabled": True})).json()
        assert on["port"] == 8769 and on["listening"] is True
        await api.client.put("/api/phone", json={"enabled": False})
        net.busy.add((ADDRESS, 8769))
        busy = (await api.client.put("/api/phone", json={"enabled": True})).json()
        assert busy["enabled"] is True and busy["listening"] is False
        assert busy["problem"] == {"code": "port_busy", "detail": "Another program uses port 8769."}


async def test_without_a_session_token_phone_access_can_t_be_turned_on(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        fake_phone_access(api)
        await onboard(api)
        status = (await api.client.get("/api/phone")).json()
        assert status["available"] is False and "--no-token" in status["unavailable_reason"]
        for method, path, body in (
            ("PUT", "/api/phone", {"enabled": True}),
            ("POST", "/api/phone/pairing", None),
        ):
            refused = await api.client.request(method, path, json=body)
            assert (refused.status_code, refused.json()["code"]) == (409, "unavailable")
        phone_of(api).allow_without_token = True  # the tests' hook
        assert (await api.client.put("/api/phone", json={"enabled": True})).json()["listening"] is True
        await phone_of(api).stop()


@pytest.mark.parametrize("how", ["serve", "settings"])
async def test_the_demo_never_listens(data_dir: Path, how: str) -> None:
    async with api_for(data_dir, token=TOKEN, demo=how == "serve") as api:
        api.client.headers["Authorization"] = f"Bearer {TOKEN}"
        if how == "settings":
            api.ctx.store.save_settings(api.ctx.store.get_settings().model_copy(update={"demo": True}))
            api.ctx.reload_settings()
        _net, servers = fake_phone_access(api)
        await onboard(api)
        api.ctx.store.set_meta(META_KEY, PhoneRecord(enabled=True, address=ADDRESS).model_dump_json())
        async with lifespan(api.app):
            assert servers.made == []
            status = (await api.client.get("/api/phone")).json()
            assert status["available"] is False and status["enabled"] is False
            assert status["unavailable_reason"] == access_module.DEMO_MESSAGE
            for method, path in (
                ("PUT", "/api/phone"),
                ("POST", "/api/phone/pairing"),
                ("POST", "/api/phone/reset"),
            ):
                refused = await api.client.request(
                    method, path, json={"enabled": True} if method == "PUT" else None
                )
                assert (refused.status_code, refused.json()["code"]) == (409, "unavailable")
        assert servers.made == []


async def test_the_lifespan_starts_and_stops_phone_access_left_on(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, servers):
        await phone_of(api).stop()
        assert servers.made[-1].stopped == 1
        async with lifespan(api.app):
            assert servers.made[-1].started == 1 and phone_of(api).listening
        assert servers.made[-1].stopped == 1 and not phone_of(api).listening


# --------------------------------------------------------------------------------------------------
# pairing
# --------------------------------------------------------------------------------------------------


async def test_a_pairing_code_is_shown_once_and_its_progress_is_polled(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        made = (await api.client.post("/api/phone/pairing")).json()
        assert made["url"] == f"https://{ADDRESS}:8767/pair#{made['code']}"
        assert len(made["code"]) == 10 and set(made["code"]) <= set(pairing_module.CODE_ALPHABET)
        status = (await api.client.get("/api/phone")).json()
        assert status["pairing"]["opened_at"] is None and made["code"] not in str(status)
        await phone.get("/pair", headers={"Sec-Fetch-Dest": "empty"})  # a preview fetch isn't the phone
        assert (await api.client.get("/api/phone")).json()["pairing"]["opened_at"] is None
        await phone.get("/pair", headers={"Sec-Fetch-Dest": "document"})
        pairing = (await api.client.get("/api/phone")).json()["pairing"]
        assert pairing["opened_at"] and pairing["opened_from"] == PHONE_IP
        answer = await phone.post(
            "/api/phone/pair",
            json={"code": made["code"].lower()[:5] + "-" + made["code"][5:], "name": "Sam's iPhone"},
        )
        assert answer.status_code == 200
        status = (await api.client.get("/api/phone")).json()
        assert status["pairing"] is None
        (device,) = status["devices"]
        assert device["name"] == "Sam's iPhone" and device["platform"] == "iPhone · Safari"
        assert device["check_words"] == answer.json()["check_words"] and device["last_address"] == PHONE_IP
        assert "token" not in str(status) and answer.cookies.get(COOKIE) not in str(status)
        assert (
            _kinds(api, "phone.paired")[0].message == f"Paired Sam's iPhone (iPhone · Safari) from {PHONE_IP}"
        )


async def test_pairing_is_refused_on_the_computer_s_listener(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        code = (await api.client.post("/api/phone/pairing")).json()["code"]
        refused = await api.client.post("/api/phone/pair", json={"code": code, "name": "x"})
        assert (refused.status_code, refused.json()["code"]) == (404, "not_phone")


async def test_no_code_while_phone_access_isn_t_listening_and_at_most_ten_phones(data_dir: Path) -> None:
    async with phone_app(data_dir, on=False) as (api, _net, _servers):
        refused = await api.client.post("/api/phone/pairing")
        assert (refused.status_code, refused.json()["code"]) == (409, "not_listening")
        await api.client.put("/api/phone", json={"enabled": True})
        for index in range(access_module.MAX_PHONES):
            async with phone_client(api, f"192.168.1.{100 + index}") as phone:
                await pair(api, phone, f"Phone {index}")
        refused = await api.client.post("/api/phone/pairing")
        assert (refused.status_code, refused.json()["code"]) == (409, "too_many_phones")


async def test_wrong_expired_and_missing_codes_get_one_answer(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        now = [time.time()]
        phone_of(api).clock = lambda: now[0]
        missing = await phone.post("/api/phone/pair", json={"code": "K7QM2XD9PA", "name": "x"})
        code = (await api.client.post("/api/phone/pairing")).json()["code"]
        wrong = await phone.post("/api/phone/pair", json={"code": "K7QM2XD9PA", "name": "x"})
        now[0] += pairing_module.PAIRING_TTL_S + 1
        expired = await phone.post("/api/phone/pair", json={"code": code, "name": "x"})
        bodies = {(r.status_code, r.text) for r in (missing, wrong, expired)}
        assert bodies == {
            (422, '{"detail":"That code didn\'t match, or it has expired.","code":"wrong_code"}')
        }


async def test_one_device_gets_five_tries_and_the_network_a_hundred(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        code = (await api.client.post("/api/phone/pairing")).json()["code"]
        async with phone_client(api) as guesser:
            tries = [
                await guesser.post("/api/phone/pair", json={"code": "WRONGCODE1", "name": "x"})
                for _ in range(5)
            ]
            assert [t.status_code for t in tries] == [422] * 5
            locked = await guesser.post("/api/phone/pair", json={"code": code, "name": "x"})
            assert (locked.status_code, locked.json()["code"]) == (
                429,
                "too_many",
            )  # even with the right code
        pairing = (await api.client.get("/api/phone")).json()["pairing"]
        assert pairing["wrong_tries"] == 5 and pairing["wrong_from"] == [PHONE_IP]
        async with phone_client(api, OTHER_PHONE_IP) as owner:
            assert (
                await owner.post("/api/phone/pair", json={"code": code, "name": "Mine"})
            ).status_code == 200
        monkeypatch.setattr(pairing_module, "PAIRING_TRIES_TOTAL", 6)
        await api.client.post("/api/phone/pairing")
        for client in ("192.168.1.70", "192.168.1.71"):
            async with phone_client(api, client) as guesser:
                for _ in range(3):
                    await guesser.post("/api/phone/pair", json={"code": "WRONGCODE1", "name": "x"})
        status = (await api.client.get("/api/phone")).json()
        assert status["pairing"] is None
        assert status["notice"]["code"] == "pairing_stopped"
        assert status["notice"]["addresses"] == ["192.168.1.70", "192.168.1.71"]
        assert "192.168.1.70, 192.168.1.71" in status["notice"]["detail"]
        assert _kinds(api, "phone.pairing_stopped")


async def test_a_code_used_twice_pairs_nobody(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        code = (await api.client.post("/api/phone/pairing")).json()["code"]
        async with phone_client(api, OTHER_PHONE_IP) as stranger:
            first = await stranger.post("/api/phone/pair", json={"code": code, "name": "iPhone"})
            assert first.status_code == 200
            stranger.cookies.set(COOKIE, first.cookies[COOKIE], domain=ADDRESS)
            again = await stranger.post("/api/phone/pair", json={"code": code, "name": "iPhone"})
            assert again.status_code == 200 and "set-cookie" not in again.headers  # the same phone, again
            assert len(phone_of(api).devices) == 1
            async with phone_client(api) as mine:
                used = await mine.post("/api/phone/pair", json={"code": code, "name": "iPhone"})
            assert (used.status_code, used.json()["code"]) == (409, "code_used")
            assert (await stranger.get("/api/documents")).status_code == 401
        status = (await api.client.get("/api/phone")).json()
        assert status["devices"] == []
        assert status["notice"]["code"] == "code_reused"
        assert status["notice"]["detail"] == (
            "Two devices used the same code, so neither is paired. Someone else may have seen your screen."
        )
        assert set(status["notice"]["addresses"]) == {PHONE_IP, OTHER_PHONE_IP}
        (removed,) = _kinds(api, "phone.removed")
        assert removed.data["by"] == "code_reused"


async def test_two_requests_with_the_right_code_can_t_both_pair(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        code = (await api.client.post("/api/phone/pairing")).json()["code"]
        async with phone_client(api) as one, phone_client(api, OTHER_PHONE_IP) as two:
            answers = await asyncio.gather(
                one.post("/api/phone/pair", json={"code": code, "name": "A"}),
                two.post("/api/phone/pair", json={"code": code, "name": "B"}),
            )
        assert sorted(a.status_code for a in answers) == [200, 409]
        assert phone_of(api).devices == []


async def test_a_phone_s_name_loses_invisible_characters_and_duplicates_are_numbered(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        async with phone_client(api) as phone:
            assert (await pair(api, phone, "Sam‮'s​ iPhone\x07"))["name"] == "Sam's iPhone"
        async with phone_client(api, OTHER_PHONE_IP) as other:
            assert (await pair(api, other, "sam's iphone"))["name"] == "sam's iphone (2)"


async def test_only_the_token_s_hash_is_in_the_database(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        code = (await api.client.post("/api/phone/pairing")).json()["code"]
        answer = await phone.post("/api/phone/pair", json={"code": code, "name": "Sam's iPhone"})
        token = answer.cookies[COOKIE]
        stored = await asyncio.to_thread(_database_bytes, data_dir)
        assert token.encode() not in stored and code.encode() not in stored
        assert access_module.token_hash(token).encode() in stored


# --------------------------------------------------------------------------------------------------
# removing, starting over, a new address
# --------------------------------------------------------------------------------------------------


async def test_removing_a_phone_signs_it_out_and_is_saved_first(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        device = phone_of(api).devices[0].id
        removed = await api.client.delete(f"/api/phone/devices/{device}")
        assert removed.status_code == 200 and removed.json()["devices"] == []
        assert load_record(api.ctx.store).devices == []  # saved before the answer
        assert (await phone.get("/api/documents")).status_code == 401
        assert (await api.client.delete(f"/api/phone/devices/{device}")).status_code == 404
        (entry,) = _kinds(api, "phone.removed")
        assert (entry.message, entry.data) == ("Removed Sam's iPhone", {"device": device, "by": "computer"})


async def test_starting_over_removes_phones_and_the_certificates(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        before = (await api.client.get("/api/phone")).json()["ca_fingerprint"]
        reset = (await api.client.post("/api/phone/reset")).json()
        assert reset["enabled"] is False and reset["devices"] == [] and reset["fingerprint"] is None
        assert not api.ctx.paths.phone.exists() and load_record(api.ctx.store) == PhoneRecord()
        assert {e.data["by"] for e in _kinds(api, "phone.removed")} == {"reset"}
        again = (await api.client.put("/api/phone", json={"enabled": True})).json()
        assert again["ca_fingerprint"] != before


async def test_a_new_address_forgets_the_phones_and_makes_a_new_authority(data_dir: Path) -> None:
    async with (
        phone_app(data_dir, network=_two_networks()) as (api, _net, servers),
        phone_client(api) as phone,
    ):
        await pair(api, phone)
        before = (await api.client.get("/api/phone")).json()
        moved = (await api.client.put("/api/phone", json={"enabled": True, "address": SECOND})).json()
        assert (
            moved["address"] == SECOND and moved["url"] == f"https://{SECOND}:8767" and moved["devices"] == []
        )
        assert moved["ca_fingerprint"] != before["ca_fingerprint"] and moved["ca_made_at"]
        assert servers.made[0].stopped == 1 and servers.made[-1].started == 1
        assert {e.data["by"] for e in _kinds(api, "phone.removed")} == {"address_changed"}
        made = {e.data["made"] for e in _kinds(api, "phone.certificate")}
        assert made == {"ca"}
        port = (await api.client.put("/api/phone", json={"enabled": True, "port": 9000})).json()
        assert port["url"] == f"https://{SECOND}:9000" and port["ca_fingerprint"] == moved["ca_fingerprint"]


# --------------------------------------------------------------------------------------------------
# the network watcher
# --------------------------------------------------------------------------------------------------


async def test_a_missing_address_pauses_and_its_return_resumes(data_dir: Path) -> None:
    async with phone_app(data_dir, network=_two_networks()) as (api, net, servers):
        access = phone_of(api)
        net.local = {SECOND}
        await access.check()
        status = (await api.client.get("/api/phone")).json()
        assert status["listening"] is False
        assert status["problem"] == {
            "code": "address_gone",
            "detail": f"Paused: this computer isn't on {ADDRESS} any more.",
        }
        await access.check()
        assert len(_kinds(api, "phone.paused")) == 1  # once per episode
        net.local = {ADDRESS, SECOND}
        await access.check()
        assert access.listening and servers.made[-1].started == 1
        assert _kinds(api, "phone.resumed")


async def test_the_same_address_behind_another_router_pauses_until_confirmed(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, net, _servers):
        access = phone_of(api)
        net.router = "192.168.1.1 11:22:33:44:55:66"
        await access.check()
        status = (await api.client.get("/api/phone")).json()
        assert status["listening"] is False and status["problem"]["code"] == "other_network"
        net.router = None  # unreadable: nothing is compared, and nothing changes
        await access.check()
        assert access.listening
        net.router = "192.168.1.1 11:22:33:44:55:66"
        await access.check()
        assert not access.listening
        home = (await api.client.put("/api/phone", json={"enabled": True, "home_network": True})).json()
        assert home["listening"] is True and home["problem"] is None
        assert load_record(api.ctx.store).gateway == "192.168.1.1 11:22:33:44:55:66"


async def test_phones_unused_for_thirty_days_are_forgotten(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        access = phone_of(api)
        device = access.devices[0]
        idle = datetime.now(UTC) - timedelta(days=DEVICE_IDLE_DAYS + 1)
        device.last_seen_at = idle.strftime("%Y-%m-%dT%H:%M:%SZ")
        await access.check()
        assert access.devices == []
        assert _kinds(api, "phone.removed")[0].data["by"] == "unused"


async def test_a_flush_of_when_phones_were_seen_never_brings_one_back(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        access = phone_of(api)
        started, release = asyncio.Event(), asyncio.Event()
        loop = asyncio.get_running_loop()
        original = record_module.save_record
        calls: list[int] = []

        def slow_save(store: Any, record: PhoneRecord) -> None:
            calls.append(len(record.devices))
            if len(calls) == 1:
                loop.call_soon_threadsafe(started.set)
                asyncio.run_coroutine_threadsafe(release.wait(), loop).result(5)
            original(store, record)

        monkeypatch.setattr(access_module, "save_record", slow_save)
        flush = asyncio.create_task(access._save())  # snapshot with the phone
        await started.wait()
        removal = asyncio.create_task(access.remove(access.devices[0].id))
        await asyncio.sleep(0.05)
        release.set()
        await asyncio.gather(flush, removal)
        assert load_record(api.ctx.store).devices == []


# --------------------------------------------------------------------------------------------------
# sign-in rotation (H1)
# --------------------------------------------------------------------------------------------------


async def test_the_sign_in_changes_hourly_and_an_old_one_coming_back_signs_the_phone_out(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ordnung.api import app as app_module
    from test_api_support import fake_web_dist

    built = fake_web_dist(tmp_path)
    monkeypatch.setattr(app_module, "web_dist_dir", lambda: built)
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        access = phone_of(api)
        now = [time.time()]
        access.clock = lambda: now[0]
        first = (await pair(api, phone))["token"]
        now[0] += ROTATE_EVERY_S + 1
        page = await phone.get("/", headers={"Cookie": f"{COOKIE}={first}"})
        second = page.cookies[COOKIE]
        assert second != first
        assert (await phone.get("/api/items", headers={"Cookie": f"{COOKIE}={first}"})).status_code == 200
        assert (await phone.get("/api/items", headers={"Cookie": f"{COOKIE}={second}"})).status_code == 200
        now[0] += PREVIOUS_GRACE_S - 10
        assert (await phone.get("/api/items", headers={"Cookie": f"{COOKIE}={first}"})).status_code == 200
        now[0] += 20
        reused = await phone.get("/api/items", headers={"Cookie": f"{COOKIE}={first}"})
        assert reused.status_code == 401
        assert (await phone.get("/api/items", headers={"Cookie": f"{COOKIE}={second}"})).status_code == 401
        status = (await api.client.get("/api/phone")).json()
        assert status["devices"] == [] and status["notice"]["code"] == "token_reuse"
        assert "signed out because its sign-in was used from two places" in status["notice"]["detail"]
        assert _kinds(api, "phone.removed")[0].data["by"] == "token_reuse"


async def test_a_phone_that_missed_its_new_sign_in_gets_another(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ordnung.api import app as app_module
    from test_api_support import fake_web_dist

    built = fake_web_dist(tmp_path)
    monkeypatch.setattr(app_module, "web_dist_dir", lambda: built)
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        access = phone_of(api)
        now = [time.time()]
        access.clock = lambda: now[0]
        first = (await pair(api, phone))["token"]
        now[0] += ROTATE_EVERY_S + 1
        lost = (await phone.get("/", headers={"Cookie": f"{COOKIE}={first}"})).cookies[COOKIE]
        now[0] += 3600  # the answer never arrived: the phone keeps its first sign-in
        again = await phone.get("/", headers={"Cookie": f"{COOKIE}={first}"})
        third = again.cookies[COOKIE]
        assert third not in (first, lost)
        assert (await phone.get("/api/items", headers={"Cookie": f"{COOKIE}={third}"})).status_code == 200
        assert access.devices, "a lost answer is not a copied sign-in"


# --------------------------------------------------------------------------------------------------
# what a phone sees (M6) and does
# --------------------------------------------------------------------------------------------------


async def test_a_phone_sees_the_profile_s_iban_masked(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        profile = api.ctx.store.get_profile()
        api.ctx.store.save_profile(profile.model_copy(update={"iban": "DE89370400440532013000"}))
        await pair(api, phone)
        assert (await phone.get("/api/profile")).json()["iban"] == "•••• 3000"
        assert (await api.client.get("/api/profile")).json()["iban"] == "DE89370400440532013000"
        numbers = (await phone.get("/api/numbers")).json()
        assert numbers["masked"] is True
        assert (await api.client.get("/api/numbers")).json()["masked"] is False


async def test_uploads_from_a_phone_are_filed_as_the_phone_s(data_dir: Path) -> None:
    pages = [(SAMPLES / f"23_steuerbescheid_2025_p{n}.jpg").read_bytes() for n in (1, 2)]
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        answer = await phone.post(
            "/api/documents",
            files=[("files", (f"photo-p{n}.jpg", data)) for n, data in enumerate(pages, start=1)],
            data={"combine": "true"},
        )
        assert answer.status_code == 201, answer.text
        (document,) = answer.json()["documents"]
        assert document["source"] == "phone" and document["filename"].endswith(".pdf")
        assert document["pages"] == 2  # two photos, one letter
        (added,) = _kinds(api, "document.added")
        assert (
            added.message.endswith("from your phone") and added.data["device"] == phone_of(api).devices[0].id
        )


async def test_a_phone_can_t_let_claude_read_a_private_letter(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        doc_id = (await api.upload(("fine.pdf", FINE_LETTER.pdf()), private=True))["documents"][0]["id"]
        refused = await phone.patch(f"/api/documents/{doc_id}", json={"ai_private": False})
        assert (refused.status_code, refused.json()["code"]) == (403, "computer_only")
        assert (await phone.patch(f"/api/documents/{doc_id}", json={"ai_private": True})).status_code == 200
        assert (
            await api.client.patch(f"/api/documents/{doc_id}", json={"ai_private": False})
        ).status_code == 200


async def test_computer_routes_refuse_a_phone_even_if_the_allow_list_let_it_through(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second, independent check: with the allow-list wrongly letting everything through, the admin
    routes still refuse a phone's request."""
    real = phone_scope.match

    def everything(method: str, path: str) -> Any:
        return real(method, path) or ((method, path), {})

    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        monkeypatch.setattr(phone_scope, "match", everything)
        for method, path, body in (
            ("PUT", "/api/settings", {"llm_brief": False}),
            ("GET", "/api/backup", None),
            ("POST", "/api/backup", {"passphrase": "a long enough passphrase"}),
            ("DELETE", "/api/data", {"confirm": "DELETE"}),
            ("GET", "/api/phone", None),
            ("PUT", "/api/phone", {"enabled": False}),
            ("POST", "/api/phone/pairing", None),
            ("DELETE", "/api/phone/pairing", None),
            ("POST", "/api/phone/reset", None),
            ("DELETE", "/api/phone/devices/phn_000000000000", None),
        ):
            refused = await phone.request(method, path, json=body)
            assert (refused.status_code, refused.json().get("code")) == (403, "computer_only"), (method, path)
        assert phone_of(api).listening and api.ctx.store.get_settings().llm_brief is True


async def test_a_phone_s_question_masks_the_person_s_numbers(data_dir: Path) -> None:
    from ordnung.assistant.ask import ask_cache_key, build_request
    from ordnung.assistant.mcp_server import MASKED_NUMBERS_ENV
    from ordnung.tick import local_today

    async with api_for(data_dir) as api:
        today = local_today(api.ctx.store)
        computer = build_request(api.ctx, "What is my tax ID?", [], today)
        phone = build_request(api.ctx, "What is my tax ID?", [], today, masked_numbers=True)
        assert MASKED_NUMBERS_ENV not in str(computer.mcp_config)
        assert phone.mcp_config["mcpServers"]["ordnung"]["env"][MASKED_NUMBERS_ENV] == "1"  # type: ignore[index]
        assert phone.cache_key != computer.cache_key  # a computer's answer never reaches the phone
        assert computer.cache_key == ask_cache_key(api.ctx.store, "What is my tax ID?", [], today)


def test_the_api_state_owns_one_phone_access(data_dir: Path) -> None:
    from ordnung.app_context import build_context
    from ordnung.llm.fake import FakeBackend

    ctx = build_context(data_dir, backend_obj=FakeBackend())
    try:
        state = ApiState(ctx=ctx, token=TOKEN)
        assert isinstance(state.phone, PhoneAccess) and state.phone.available
        assert ApiState(ctx=ctx).phone.available is False
    finally:
        ctx.close()
