"""The phone listener's gate: who it answers (home network, exact Host, same origin), what it lets a
phone do before and after pairing, that the computer's session token means nothing there, its headers,
body limits before and after sign-in, per-phone limits, attribution and lock-safe removal."""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from ordnung.api import app as app_module
from ordnung.api.phone_gate import MESSAGES, PERMISSIONS_POLICY, PhoneListener, bad_path, page_load
from ordnung.api.routes import documents as documents_route
from ordnung.api.security import MAX_REQUEST_BYTES
from ordnung.api.sse import PING_SECONDS
from ordnung.phone import access as access_module
from ordnung.phone import scope as phone_scope
from ordnung.phone.pairing import PAIR_MAX_BYTES, SlidingLimit
from ordnung.phone.scope import COMPUTER_ONLY
from phone_support import (
    ADDRESS,
    COOKIE,
    OTHER_PHONE_IP,
    PHONE_HEADERS,
    PHONE_IP,
    PHONE_URL,
    PORT,
    TOKEN,
    drive,
    pair,
    phone_app,
    phone_client,
    phone_of,
)
from test_api_support import FINE_LETTER, fake_web_dist

_PARAM = re.compile(r"\{[^}]+\}")
MB = 1024 * 1024
#: A removed phone's live stream ends at once, long before the next ping (the margin is a slow runner's)
STREAM_ENDS_S = PING_SECONDS / 3


@pytest.fixture(autouse=True)
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    built = fake_web_dist(tmp_path)
    (built / "build-info.json").write_text('{"sourceHash": "abc"}', encoding="utf-8")
    monkeypatch.setattr(app_module, "web_dist_dir", lambda: built)
    return built


def _example(template: str) -> str:
    return _PARAM.sub("x1", template)


# --------------------------------------------------------------------------------------------------
# who the listener answers
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        ADDRESS,
        "localhost:8767",
        "127.0.0.1:8767",
        "ordnung.local:8767",
        f"{ADDRESS}:8768",
        "evil.example",
        "",
    ],
)
async def test_only_the_exact_address_and_port_is_answered(data_dir: Path, host: str) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        response = await phone.get("/api/health", headers={"Host": host})
        assert response.status_code == 400
        assert response.json()["code"] == "wrong_host"


async def test_another_scheme_or_listener_is_misdirected(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        plain = await drive(PhoneListener(api.app), "GET", "/api/health", scheme="http")
        other_port = await drive(PhoneListener(api.app), "GET", "/api/health", server=(ADDRESS, 9999))
        assert (plain.status, other_port.status) == (421, 421)
        phone_of(api).bound = None  # turned off: a request still in a connection is not answered
        assert (await drive(PhoneListener(api.app), "GET", "/api/health")).status == 421


@pytest.mark.parametrize("client", ["8.8.8.8", "100.64.0.7", "172.17.0.2", "10.8.0.6", "192.168.2.20", "::1"])
async def test_only_the_home_network_s_devices_are_answered(data_dir: Path, client: str) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api, client_ip=client) as phone:
        response = await phone.get("/api/health")
        assert response.status_code == 403
        assert response.json()["code"] == "not_home_network"


async def test_a_device_on_the_subnet_reaches_the_pairing_answer(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api, "192.168.1.200") as phone:
        assert (await phone.get("/api/health")).json()["code"] == "phone_not_paired"


# --------------------------------------------------------------------------------------------------
# another site's requests
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "headers"),
    [
        ("POST", {"Origin": ""}),
        ("POST", {"Origin": f"http://{ADDRESS}:{PORT}"}),
        ("POST", {"Origin": "https://evil.example"}),
        ("POST", {"Origin": f"https://{ADDRESS}:8768"}),
        ("GET", {"Origin": "https://evil.example"}),
        ("GET", {"Sec-Fetch-Site": "cross-site"}),
        ("GET", {"Sec-Fetch-Site": "same-site"}),  # another port of the same address is the same site
        ("POST", {"Sec-Fetch-Site": "none"}),
        ("POST", {"X-Ordnung-Client": ""}),
    ],
)
async def test_another_site_s_requests_are_refused(
    data_dir: Path, method: str, headers: dict[str, str]
) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        for name, value in headers.items():
            if value:
                phone.headers[name] = value
            else:
                del phone.headers[name]
        path, body = ("/api/items", {}) if method == "POST" else ("/api/health", None)
        response = await phone.request(method, path, json=body)
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "cross_site"


async def test_a_page_load_from_a_bookmark_passes(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        del phone.headers["Origin"]
        response = await phone.get("/", headers={"Sec-Fetch-Site": "none"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")


# --------------------------------------------------------------------------------------------------
# before pairing
# --------------------------------------------------------------------------------------------------


async def test_before_pairing_only_the_pairing_page_and_the_app_s_files_load(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        page = await phone.get("/pair")
        assert page.status_code == 200 and '<div id="root">' in page.text
        assert (await phone.get("/assets/index-abc.js")).status_code == 200
        assert (await phone.get("/favicon.svg")).status_code == 200
        for path in ("/", "/inbox", "/build-info.json", "/assets/missing.js", "/ordnung-certificate.crt"):
            response = await phone.get(path)
            assert (response.status_code, response.headers.get("location")) == (303, "/pair"), path
        api_call = await phone.get("/api/documents")
        assert api_call.status_code == 401
        assert api_call.json() == {
            "detail": "This phone isn't paired with Ordnung any more. Pair it again from Settings → Phone on "
            "your computer.",
            "code": "phone_not_paired",
        }
        assert (await phone.get("/api/health")).status_code == 401  # never the version before pairing


def test_public_files_are_exactly_the_build_s_assets_and_icon(dist: Path) -> None:
    assert app_module.public_files(dist) == frozenset({"/assets/index-abc.js", "/favicon.svg"})


@pytest.mark.parametrize(
    "path",
    ["/assets/../build-info.json", "/assets/./index-abc.js", "//favicon.svg", "/assets\\index-abc.js", "/.."],
)
async def test_paths_with_dot_segments_or_doubled_slashes_are_refused(data_dir: Path, path: str) -> None:
    assert bad_path(path)
    async with phone_app(data_dir) as (api, _net, _servers):
        exchange = await drive(PhoneListener(api.app), "GET", path)
        assert exchange.status == 400
        assert b"sourceHash" not in exchange.body


async def test_a_cookie_this_computer_doesn_t_know_clears_the_phone_s_storage(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        stale = {"Cookie": f"{COOKIE}=not-a-sign-in"}
        page = await phone.get("/today", headers=stale)
        assert (page.status_code, page.headers["location"]) == (303, "/pair?removed=1")
        for response in (page, await phone.get("/api/items", headers=stale)):
            assert response.headers["clear-site-data"] == '"cache", "storage"'  # not "cookies"
            assert f'{COOKIE}=""' in response.headers["set-cookie"]
            assert "Max-Age=0" in response.headers["set-cookie"]


@pytest.mark.parametrize(
    ("path", "headers"),
    [
        ("/api/health", {"Authorization": f"Bearer {TOKEN}"}),
        ("/api/health", {"Cookie": f"ordnung_token_{PORT}={TOKEN}"}),
        ("/api/health?token=" + TOKEN, {}),
        ("/?token=" + TOKEN, {}),
    ],
)
async def test_the_session_token_never_works_on_the_phone_listener(
    data_dir: Path, path: str, headers: dict[str, str]
) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        response = await phone.get(path, headers=headers)
        assert response.status_code in (401, 303)
        if response.status_code == 303:
            assert response.headers["location"] == "/pair"
        assert "set-cookie" not in response.headers


# --------------------------------------------------------------------------------------------------
# B1: bodies before sign-in
# --------------------------------------------------------------------------------------------------


def _endless(total_mb: int) -> Iterator[bytes]:
    chunk = b"x" * MB
    for _ in range(total_mb):
        yield chunk


async def test_a_chunked_pairing_request_is_refused_before_its_body_is_read(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        headers = {**PHONE_HEADERS, "transfer-encoding": "chunked", "content-type": "application/json"}
        exchange = await drive(
            PhoneListener(api.app), "POST", "/api/phone/pair", headers=headers, chunks=_endless(50)
        )
        assert exchange.status == 411 and exchange.read <= 1024
        assert b"length_required" in exchange.body


async def test_a_huge_pairing_request_is_refused_before_its_body_is_read(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        headers = {**PHONE_HEADERS, "content-length": str(200 * MB), "content-type": "application/json"}
        exchange = await drive(
            PhoneListener(api.app), "POST", "/api/phone/pair", headers=headers, chunks=_endless(200)
        )
        assert exchange.status == 413 and exchange.read <= 1024


async def test_a_pairing_request_without_a_length_is_refused(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        headers = {**PHONE_HEADERS, "content-type": "application/json"}
        exchange = await drive(
            PhoneListener(api.app), "POST", "/api/phone/pair", headers=headers, chunks=_endless(5)
        )
        assert exchange.status == 411 and exchange.read == 0


async def test_a_body_longer_than_it_said_is_stopped_at_the_limit(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        headers = {**PHONE_HEADERS, "content-length": "100", "content-type": "application/json"}
        chunks = [b'{"code":"' + b"x" * 2048, *_endless(20)]
        exchange = await drive(
            PhoneListener(api.app), "POST", "/api/phone/pair", headers=headers, chunks=chunks
        )
        assert exchange.status == 413
        assert exchange.read <= 2048 + 9 + PAIR_MAX_BYTES


async def test_a_get_with_a_body_before_sign_in_is_refused(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        exchange = await drive(
            PhoneListener(api.app), "GET", "/pair", headers={"content-length": "10"}, chunks=[b"x" * 10]
        )
        assert exchange.status == 400 and exchange.read == 0


async def test_after_sign_in_the_upload_limit_applies(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        signed = await pair(api, phone)
        headers = {
            **PHONE_HEADERS,
            "content-length": str(MAX_REQUEST_BYTES + 1),
            "content-type": "multipart/form-data; boundary=x",
            "cookie": f"{COOKIE}={signed['token']}",
        }
        exchange = await drive(
            PhoneListener(api.app), "POST", "/api/documents", headers=headers, chunks=_endless(300)
        )
        assert exchange.status == 413 and exchange.read == 0


# --------------------------------------------------------------------------------------------------
# a paired phone
# --------------------------------------------------------------------------------------------------


async def test_pairing_sets_the_phone_s_own_cookie(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        signed = await pair(api, phone)
        assert signed["set_cookie"] == (
            f"{COOKIE}={signed['token']}; HttpOnly; Max-Age=34560000; Path=/; SameSite=strict; Secure"
        )
        assert len(signed["token"]) >= 43  # 256 bits
        assert (await phone.get("/api/documents")).status_code == 200


@pytest.mark.parametrize("operation", sorted(COMPUTER_ONLY))
async def test_every_computer_only_operation_is_refused_to_a_phone(
    data_dir: Path, operation: tuple[str, str]
) -> None:
    method, template = operation
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        response = await phone.request(method, _example(template))
        assert response.status_code == 403, response.text
        assert response.json() == {"detail": "This works on your computer only.", "code": "computer_only"}


async def test_a_phone_downloads_no_calendar_file(data_dir: Path) -> None:
    """UX review: a paired phone downloaded ``ordnung.ics`` (to-do titles, amounts, what to do) while
    the docs say a phone keeps no copy and downloads no records. The calendar files stay on the
    computer, which still gets them."""
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        for method, path in (
            ("GET", "/api/calendar.ics"),
            ("HEAD", "/api/calendar.ics"),
            ("GET", "/api/items/itm_000000000000.ics"),
            ("POST", "/api/calendar/exported"),
        ):
            refused = await phone.request(method, path)
            assert refused.status_code == 403, (method, path)
            assert "text/calendar" not in refused.headers.get("content-type", "")
            if method != "HEAD":
                assert refused.json()["code"] == "computer_only"
        assert (await phone.get("/api/items")).status_code == 200  # the dates themselves it shows
        computer = await api.client.get("/api/calendar.ics")
        assert computer.status_code == 200 and computer.headers["content-type"].startswith("text/calendar")


async def test_unknown_api_paths_and_the_schema_are_refused(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        for path in ("/api/openapi.json", "/api/nothing-here", "/api"):
            assert (await phone.get(path)).json()["code"] == "computer_only", path


async def test_run_check_is_refused_and_health_is_trimmed(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        assert (await phone.get("/api/health", params={"probe": "1"})).json()["code"] == "computer_only"
        health = (await phone.get("/api/health")).json()
        assert health["client"] == "phone"
        assert (health["data_dir"], health["claude"]["path"], health["checks"]) == ("", None, [])
        computer = (await api.client.get("/api/health")).json()
        assert computer["client"] == "computer" and computer["data_dir"] == str(api.ctx.paths.data_dir)


async def test_phone_answers_carry_their_headers(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        for path in ("/api/documents", "/", "/api/settings"):
            response = await phone.get(path)
            assert response.headers["cross-origin-resource-policy"] == "same-origin"
            assert response.headers["permissions-policy"] == PERMISSIONS_POLICY
            assert response.headers["x-content-type-options"] == "nosniff"
            assert "strict-transport-security" not in response.headers
            assert "server" not in response.headers
        assert (await phone.get("/api/documents")).headers["cache-control"] == "no-store"
        page = await phone.get("/")
        assert (
            page.headers["cache-control"] == "no-cache"
            and "frame-ancestors 'none'" in page.headers["content-security-policy"]
        )


async def test_a_page_load_refreshes_the_sign_in_cookie(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        signed = await pair(api, phone)
        page = await phone.get("/inbox")
        assert page.headers["set-cookie"] == signed["set_cookie"]  # within the hour: the same sign-in
        assert "set-cookie" not in (await phone.get("/api/documents")).headers


async def test_websockets_close_on_the_phone_listener(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        exchange = await drive(PhoneListener(api.app), "GET", "/api/events", scope_type="websocket")
        assert exchange.messages == [{"type": "websocket.close", "code": 1008}]


async def test_the_certificate_download_is_for_paired_phones(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        assert (await phone.get("/ordnung-certificate.crt")).status_code == 303
        await pair(api, phone)
        response = await phone.get("/ordnung-certificate.crt")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-x509-ca-cert"
        authority = x509.load_pem_x509_certificate((api.ctx.paths.phone / "ca.pem").read_bytes())
        assert response.content == authority.public_bytes(serialization.Encoding.DER)


# --------------------------------------------------------------------------------------------------
# limits
# --------------------------------------------------------------------------------------------------


async def test_pairing_requests_are_limited_per_address_and_in_all(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        answers = [
            await phone.post("/api/phone/pair", json={"code": "WRONG", "name": "x"}) for _ in range(11)
        ]
        assert [a.status_code for a in answers[:10]] == [422] * 10  # no code is open: one answer for all
        assert answers[-1].status_code == 429 and int(answers[-1].headers["retry-after"]) >= 1
        assert answers[-1].json()["code"] == "too_many"
        access = phone_of(api)
        access.pair_limit_client = SlidingLimit(100, 60)
        access.pair_limit_all = SlidingLimit(2, 60)
        async with phone_client(api, OTHER_PHONE_IP) as other:
            codes = [
                (await other.post("/api/phone/pair", json={"code": "A", "name": "x"})).status_code
                for _ in range(3)
            ]
        assert codes[-1] == 429


async def test_each_phone_has_hourly_limits(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        access = phone_of(api)
        access._device_limits["model"] = SlidingLimit(1, 3600)
        assert (await phone.post("/api/brief", json={})).status_code < 400
        refused = await phone.post("/api/brief", json={})
        assert refused.status_code == 429 and refused.json()["code"] == "too_many"
        assert int(refused.headers["retry-after"]) > 0
        async with phone_client(api, OTHER_PHONE_IP) as other:
            await pair(api, other, "Other phone")
            assert (await other.post("/api/brief", json={})).status_code < 400  # each phone its own
        assert (await api.client.post("/api/brief", json={})).status_code < 400  # the computer has none


# --------------------------------------------------------------------------------------------------
# attribution (M4)
# --------------------------------------------------------------------------------------------------


async def test_a_phone_s_changes_are_attributed_in_the_privacy_log(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        signed = await pair(api, phone)
        device = phone_of(api).devices[0].id
        upload = await phone.post(
            "/api/documents", files=[("files", ("fine.pdf", FINE_LETTER.pdf()))], data={"combine": "false"}
        )
        assert upload.status_code == 201, upload.text
        doc_id = upload.json()["documents"][0]["id"]
        await api.read_all()
        fixed = await phone.patch(f"/api/documents/{doc_id}", json={"received_date": "2026-09-20"})
        assert fixed.status_code == 200, fixed.text
        log = (await api.client.get("/api/activity", params={"device": device})).json()
        kinds = [entry["kind"] for entry in log]
        assert "document.added" in kinds and "document.received_date" in kinds and "phone.changed" in kinds
        added = next(e for e in log if e["kind"] == "document.added")
        assert added["message"].endswith("from your phone") and added["data"]["source"] == "phone"
        dated = next(e for e in log if e["kind"] == "document.received_date")
        assert dated["message"].endswith(f"(on {signed['name']})")
        changes = [e for e in log if e["kind"] == "phone.changed"]
        assert {e["data"]["operation"] for e in changes} == {
            "POST /api/documents",
            "PATCH /api/documents/{doc_id}",
        }
        patched = next(e for e in changes if e["data"]["operation"].startswith("PATCH"))
        assert patched["data"]["refs"] == {"doc_id": doc_id}
        assert patched["message"] == f"Corrected a letter on {signed['name']}"
        processed = [e for e in api.ctx.store.list_activity(limit=None, kinds=["document.processed"])]
        assert all("device" not in e.data for e in processed)  # the computer's reading is its own
        status = (await api.client.get("/api/phone")).json()
        assert status["devices"][0]["recent_changes"] == 2


async def test_a_refused_change_is_not_logged(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        assert (await phone.patch("/api/items/itm_nothere", json={"status": "done"})).status_code == 404
        assert api.ctx.store.list_activity(kinds=["phone.changed"]) == []


# --------------------------------------------------------------------------------------------------
# removal (M1): streams end, writes finish, the next request is refused
# --------------------------------------------------------------------------------------------------


async def test_removing_a_phone_ends_its_live_stream_and_not_another_s(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        async with phone_client(api) as phone, phone_client(api, OTHER_PHONE_IP) as other:
            first = await pair(api, phone)
            second = await pair(api, other, "Other phone")
        listener = PhoneListener(api.app)
        streams = {}
        for client, signed in ((PHONE_IP, first), (OTHER_PHONE_IP, second)):
            headers = {
                **PHONE_HEADERS,
                "cookie": f"{COOKIE}={signed['token']}",
                "accept": "text/event-stream",
            }
            streams[client] = await _start(listener, "/api/events", headers, client)
        (mine, mine_task), (theirs, theirs_task) = streams[PHONE_IP], streams[OTHER_PHONE_IP]
        device = next(d.id for d in phone_of(api).devices if d.name == first["name"])
        assert (await api.client.get("/api/phone")).json()["devices"][0]["active"] is True
        assert (await api.client.delete(f"/api/phone/devices/{device}")).status_code == 200
        await asyncio.wait_for(mine_task, STREAM_ENDS_S)
        assert mine.complete and mine.status == 200
        assert not theirs_task.done()
        theirs.left.set()
        await asyncio.wait_for(theirs_task, 2)
        async with phone_client(api) as phone:
            phone.cookies.set(COOKIE, first["token"], domain=ADDRESS)
            assert (await phone.get("/api/documents")).status_code == 401


async def _start(
    listener: Any, path: str, headers: dict[str, str], client: str
) -> tuple[Any, asyncio.Task[Any]]:
    from phone_support import Exchange

    exchange = Exchange()
    task = asyncio.create_task(
        drive(listener, "GET", path, headers=headers, client=client, exchange=exchange)
    )
    await asyncio.wait_for(exchange.started.wait(), 2)
    return exchange, task


async def test_removing_a_phone_mid_write_lets_the_write_finish_alone(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A phone removed while its PATCH waits inside the ledger lock: the PATCH finishes (its answer goes
    out), no second writer enters the lock meanwhile, and the phone's next request is refused."""
    original = documents_route._patch
    guard = threading.Lock()
    inside, release = threading.Event(), threading.Event()
    state = {"active": 0, "overlap": False, "calls": 0}

    def slow_patch(*args: Any) -> Any:
        with guard:
            state["active"] += 1
            state["calls"] += 1
            state["overlap"] = state["overlap"] or state["active"] > 1
        inside.set()
        release.wait(5)
        try:
            return original(*args)
        finally:
            with guard:
                state["active"] -= 1

    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        first = await api.upload(("fine.pdf", FINE_LETTER.pdf()))
        doc_id = first["documents"][0]["id"]
        await api.read_all()
        monkeypatch.setattr(documents_route, "_patch", slow_patch)
        phone_write = asyncio.create_task(
            phone.patch(f"/api/documents/{doc_id}", json={"title": "From the phone"})
        )
        assert await asyncio.to_thread(inside.wait, 5)
        device = phone_of(api).devices[0].id
        assert (await api.client.delete(f"/api/phone/devices/{device}")).status_code == 200
        computer_write = asyncio.create_task(
            api.client.patch(f"/api/documents/{doc_id}", json={"title": "From the computer"})
        )
        await asyncio.sleep(0.2)
        assert state["calls"] == 1  # the computer waits for the lock
        release.set()
        phone_answer, computer_answer = await asyncio.gather(phone_write, computer_write)
        assert phone_answer.status_code == 200 and computer_answer.status_code == 200
        assert state["overlap"] is False
        assert api.ctx.store.get_document(doc_id).title == "From the computer"  # type: ignore[union-attr]
        assert (await phone.get("/api/documents")).status_code == 401


# --------------------------------------------------------------------------------------------------
# stopping and removing mid-request (lifecycle review): in flight from the gate's first check
# --------------------------------------------------------------------------------------------------


class _HeldSave:
    """The next save of the phone record waits in its thread until released — a slow disk, or another
    writer holding the database's write lock — as the phone's first request after pairing does while
    it saves when the phone first used its sign-in."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        loop = asyncio.get_running_loop()
        self.started = asyncio.Event()
        self.release = threading.Event()
        armed = [True]
        original = access_module.save_record

        def held(store: Any, record: Any) -> None:
            if armed[0]:
                armed[0] = False
                loop.call_soon_threadsafe(self.started.set)
                self.release.wait(5)
            original(store, record)

        monkeypatch.setattr(access_module, "save_record", held)


def _slow_patch(monkeypatch: pytest.MonkeyPatch) -> tuple[threading.Event, threading.Event, dict[str, Any]]:
    """``PATCH /api/documents/{id}``'s write waits inside the ledger lock until released; ``state``
    says whether two writers were ever in it at once."""
    original = documents_route._patch
    guard = threading.Lock()
    inside, release = threading.Event(), threading.Event()
    state: dict[str, Any] = {"active": 0, "overlap": False, "calls": 0}

    def slow_patch(*args: Any) -> Any:
        with guard:
            state["active"] += 1
            state["calls"] += 1
            state["overlap"] = state["overlap"] or state["active"] > 1
        if state["calls"] == 1:
            inside.set()
            release.wait(5)
        try:
            return original(*args)
        finally:
            with guard:
                state["active"] -= 1

    monkeypatch.setattr(documents_route, "_patch", slow_patch)
    return inside, release, state


async def test_turning_off_waits_for_a_request_still_signing_in_and_refuses_it(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lifecycle review: a request waiting for its sign-in to be saved wasn't counted yet, so turning
    phone access off closed the listener at once and uvicorn cancelled the write 2 s later, inside the
    ledger lock. It is counted from the gate's first check: the stop waits for it, and it is refused
    (phone access stopped — the phone stays paired) instead of writing."""
    async with phone_app(data_dir) as (api, _net, servers), phone_client(api) as phone:
        await pair(api, phone)
        doc_id = (await api.upload(("fine.pdf", FINE_LETTER.pdf())))["documents"][0]["id"]
        title = api.ctx.store.get_document(doc_id).title  # type: ignore[union-attr]
        held = _HeldSave(monkeypatch)
        write = asyncio.create_task(phone.patch(f"/api/documents/{doc_id}", json={"title": "From the phone"}))
        await asyncio.wait_for(held.started.wait(), 5)
        off = asyncio.create_task(api.client.put("/api/phone", json={"enabled": False}))
        await asyncio.sleep(0.2)
        server = servers.made[-1]
        assert server.stopped == 0 and not off.done()  # the stop waits for the request in flight
        held.release.set()
        answer = await asyncio.wait_for(write, 5)
        assert (answer.status_code, answer.json()["code"]) == (409, "unavailable")
        assert "stopped on your computer" in answer.json()["detail"]
        assert (await asyncio.wait_for(off, 5)).status_code == 200 and server.stopped == 1
        assert api.ctx.store.get_document(doc_id).title == title  # type: ignore[union-attr]
        assert [d.name for d in phone_of(api).devices] == ["Sam's iPhone"]
        assert api.ctx.store.list_activity(kinds=["phone.changed"]) == []


async def test_a_write_the_listener_s_stop_cuts_off_still_finishes_alone(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lifecycle review: what outlasts the stop's wait is cancelled by uvicorn (its graceful stop). A
    phone's write inside the ledger lock is shielded from that: it finishes, unanswered, before the
    computer's write gets the lock."""
    monkeypatch.setattr(access_module, "DRAIN_S", 0.2)
    async with phone_app(data_dir) as (api, _net, servers), phone_client(api) as phone:
        await pair(api, phone)
        doc_id = (await api.upload(("fine.pdf", FINE_LETTER.pdf())))["documents"][0]["id"]
        await api.read_all()
        assert (await phone.get("/api/documents")).status_code == 200  # signed in and saved
        inside, release, state = _slow_patch(monkeypatch)
        phone_write = asyncio.create_task(
            phone.patch(f"/api/documents/{doc_id}", json={"title": "From the phone"})
        )
        assert await asyncio.to_thread(inside.wait, 5)
        server = servers.made[-1]

        async def shutdown_like_uvicorn() -> None:
            server.stopped += 1
            phone_write.cancel()  # "Cancel 1 running task(s), timeout graceful shutdown exceeded"

        server.shutdown = shutdown_like_uvicorn  # type: ignore[method-assign]
        assert (await api.client.put("/api/phone", json={"enabled": False})).status_code == 200
        with pytest.raises(asyncio.CancelledError):
            await phone_write
        computer_write = asyncio.create_task(
            api.client.patch(f"/api/documents/{doc_id}", json={"title": "From the computer"})
        )
        await asyncio.sleep(0.2)
        assert state["calls"] == 1  # the computer waits for the lock the phone's write still holds
        release.set()
        assert (await asyncio.wait_for(computer_write, 5)).status_code == 200
        assert state["overlap"] is False
        assert api.ctx.store.get_document(doc_id).title == "From the computer"  # type: ignore[union-attr]
        for _ in range(50):
            if not phone_of(api)._live:
                break
            await asyncio.sleep(0.02)
        assert not phone_of(api)._live  # done, so no longer in flight


async def test_a_phone_removed_while_its_first_request_signs_in_gets_no_stream(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lifecycle review: a request between its sign-in and the gate's tracking missed the phone's
    removal, so the removed phone's live stream kept running. It is checked again once the sign-in is
    saved: the removed phone is refused (and told why)."""
    async with phone_app(data_dir) as (api, _net, _servers):
        async with phone_client(api) as phone:
            signed = await pair(api, phone)
        device = phone_of(api).devices[0].id
        held = _HeldSave(monkeypatch)
        headers = {**PHONE_HEADERS, "cookie": f"{COOKIE}={signed['token']}", "accept": "text/event-stream"}
        from phone_support import Exchange

        exchange = Exchange()
        stream = asyncio.create_task(
            drive(PhoneListener(api.app), "GET", "/api/events", headers=headers, exchange=exchange)
        )
        await asyncio.wait_for(held.started.wait(), 5)
        removal = asyncio.create_task(api.client.delete(f"/api/phone/devices/{device}"))
        # removed (in memory at once) before the sign-in's save goes on, however slow the runner
        for _ in range(500):
            if not phone_of(api).devices:
                break
            await asyncio.sleep(0.01)
        assert phone_of(api).devices == []
        held.release.set()
        assert (await asyncio.wait_for(removal, 5)).status_code == 200
        await asyncio.wait_for(stream, 5)
        assert exchange.status == 401
        assert json.loads(exchange.body) == {
            "detail": MESSAGES["phone_not_paired"],
            "code": "phone_not_paired",
            "removed": "1",
        }
        assert exchange.headers["clear-site-data"] == '"cache", "storage"'
        assert not phone_of(api)._live and phone_of(api).devices == []


async def _upload_with(api: Any, token: str, monkeypatch: pytest.MonkeyPatch, how: str) -> httpx.Response:
    """A phone's upload whose body has arrived and is being filed when phone access is turned off
    (``how="off"``) or the phone is removed."""
    entered, release = asyncio.Event(), asyncio.Event()
    original = documents_route._add_group

    async def waiting(*args: Any, **kwargs: Any) -> None:
        entered.set()
        await release.wait()
        await original(*args, **kwargs)

    monkeypatch.setattr(documents_route, "_add_group", waiting)
    async with phone_client(api) as phone:
        phone.cookies.set(COOKIE, token, domain=ADDRESS)
        upload = asyncio.create_task(
            phone.post("/api/documents", files=[("files", ("fine.pdf", FINE_LETTER.pdf()))])
        )
        await asyncio.wait_for(entered.wait(), 5)
        if how == "off":
            done = asyncio.create_task(api.client.put("/api/phone", json={"enabled": False}))
        else:
            device = phone_of(api).devices[0].id
            done = asyncio.create_task(api.client.delete(f"/api/phone/devices/{device}"))
        await asyncio.sleep(0.1)
        release.set()
        answer = await asyncio.wait_for(upload, 5)
        assert (await asyncio.wait_for(done, 5)).status_code == 200
    return answer


@pytest.mark.parametrize("how", ["off", "removed"])
async def test_an_upload_that_arrived_in_full_is_filed_and_answered(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """Lifecycle review: turning phone access off or removing the phone while an upload that had
    arrived was being filed answered 401 ``phone_not_paired`` — the phone left for the pairing page and
    dropped its photos while the letter was filed. It is answered as filed."""
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        signed = await pair(api, phone)
        answer = await _upload_with(api, signed["token"], monkeypatch, how)
        assert answer.status_code == 201, answer.text
        (document,) = answer.json()["documents"]
        filed = api.ctx.store.get_document(document["id"])
        assert filed is not None and filed.source == "phone"


@pytest.mark.parametrize(
    ("how", "status", "code"), [("off", 409, "unavailable"), ("removed", 401, "phone_not_paired")]
)
async def test_an_upload_still_arriving_is_told_why_it_stopped(
    data_dir: Path, how: str, status: int, code: str
) -> None:
    """Lifecycle review: an upload still arriving when phone access was turned off was told
    ``phone_not_paired`` (the phone then left for "This phone was removed"). Turned off, it is told phone
    access stopped (the phone stays paired and keeps its photos); removed, that it isn't paired."""
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        signed = await pair(api, phone)
        assert (await phone.get("/api/documents")).status_code == 200
        device = phone_of(api).devices[0].id
        start = (
            b'--x\r\nContent-Disposition: form-data; name="files"; filename="a.pdf"\r\n'
            b"Content-Type: application/pdf\r\n\r\n%PDF-1.4 "
        )
        headers = {
            **PHONE_HEADERS,
            "content-length": str(MB),
            "content-type": "multipart/form-data; boundary=x",
            "cookie": f"{COOKIE}={signed['token']}",
        }
        left = asyncio.Event()
        exchange_task = asyncio.create_task(
            drive(
                PhoneListener(api.app), "POST", "/api/documents", headers=headers, chunks=[start], stall=left
            )
        )
        for _ in range(100):
            if any(live.kind == "upload" for live in phone_of(api)._live):
                break
            await asyncio.sleep(0.01)
        if how == "off":
            assert (await api.client.put("/api/phone", json={"enabled": False})).status_code == 200
        else:
            assert (await api.client.delete(f"/api/phone/devices/{device}")).status_code == 200
        exchange = await asyncio.wait_for(exchange_task, 5)
        left.set()
        assert exchange.status == status
        body = json.loads(exchange.body)
        assert body["code"] == code
        assert api.ctx.store.list_documents() == []
        assert len(phone_of(api).devices) == (1 if how == "off" else 0)


def test_a_page_load_is_a_navigation() -> None:
    def headers(**values: str) -> Any:
        from starlette.datastructures import Headers

        return Headers(values)

    assert page_load("/", headers())
    assert page_load("/inbox", headers(**{"sec-fetch-dest": "document"}))
    assert not page_load("/inbox", headers(**{"sec-fetch-dest": "empty"}))
    assert not page_load("/assets/index-abc.js", headers())
    assert not page_load("/api/items", headers())
    assert not page_load("/favicon.svg", headers())


def test_every_change_a_phone_can_make_has_a_label() -> None:
    changes = {op for op in phone_scope.PHONE_ROUTES if op[0] != "GET"} - phone_scope.NOT_CHANGES
    assert changes == set(phone_scope.CHANGE_LABELS)
    assert set(phone_scope.LIMITED) <= phone_scope.PHONE_ROUTES
    assert set(phone_scope.STREAMS) | phone_scope.UPLOADS <= phone_scope.PHONE_ROUTES


async def test_a_phone_url_never_reaches_the_computer_s_cookie(data_dir: Path) -> None:
    """The client keeps the phone's cookie for the phone's origin only (``__Host-``, Secure)."""
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        signed = await pair(api, phone)
        assert signed["set_cookie"].startswith("__Host-") and "Domain" not in signed["set_cookie"]
        computer = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app),
            base_url="http://127.0.0.1:8765",
            headers={"Cookie": f"{COOKIE}={signed['token']}"},
        )
        async with computer:
            assert (await computer.get("/api/documents")).status_code == 401
        assert PHONE_URL.startswith("https://")


async def test_a_tagged_request_without_a_gate_is_misdirected() -> None:
    from ordnung.api.security import SecurityMiddleware

    reached: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        reached.append(scope["path"])

    exchange = await drive(PhoneListener(SecurityMiddleware(app, token=None)), "GET", "/api/health")
    assert exchange.status == 421 and reached == []
    assert exchange.headers["x-content-type-options"] == "nosniff"


async def test_refusals_are_logged_as_a_count_never_a_secret(
    data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api, "8.8.8.8") as stranger:
        with caplog.at_level("WARNING", logger="ordnung.phone"):
            for _ in range(5):
                await stranger.get("/api/health", headers={"Cookie": f"{COOKIE}=secret-cookie-value"})
        refusals = [r for r in caplog.records if "refused" in r.getMessage()]
        assert len(refusals) == 1  # at most once a minute per reason
        assert (
            refusals[0].getMessage()
            == "1 requests refused (not_home_network) from 8.8.8.8 in the last minute"
        )
        assert "secret-cookie-value" not in caplog.text and TOKEN not in caplog.text
