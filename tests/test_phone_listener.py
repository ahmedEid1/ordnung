"""The phone listener for real: a TLS uvicorn server on a loopback address next to the computer's own
listener, in one loop and one process — one lifespan, no signal handlers, sse-starlette left alone,
removal ending a phone's stream at once, turning off within the graceful stop, a busy port and a
missing address as problems, and the computer's listener answering throughout.

Not marked slow: the ``lowest`` CI job runs it on uvicorn's floor (0.31.1, the lowest mcp allows)."""

from __future__ import annotations

import asyncio
import signal
import socket
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from sse_starlette.sse import AppStatus

from ordnung.api.app import create_app
from ordnung.api.sse import PING_SECONDS
from ordnung.app_context import build_context
from ordnung.llm.fake import FakeBackend
from ordnung.phone import cookie_name
from ordnung.phone.access import GRACEFUL_STOP_S, PhoneAccess
from ordnung.phone.net import TEST_ADDRESS_ENV
from test_api_support import ApiRouter

TOKEN = "listener-test-token"
#: A phone's live stream ends at once when it is removed or phone access goes off, long before the next ping
STREAM_ENDS_S = PING_SECONDS / 3
#: What a slow runner may add to a stop that waits for uvicorn's graceful shutdown
SLOW_RUNNER_S = 3.0
LOOPBACK = "127.0.0.1"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((LOOPBACK, 0))
        return int(sock.getsockname()[1])


@asynccontextmanager
async def _serving(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[dict[str, Any]]:
    """The computer's listener started like ``ordnung serve`` starts it (lifespan on), with a session
    token; yields its client, the app's phone access and how often the worker started."""
    monkeypatch.setenv(TEST_ADDRESS_ENV, LOOPBACK)
    ctx = build_context(data_dir, backend_obj=FakeBackend(ApiRouter()))
    profile = ctx.store.get_profile()
    ctx.store.save_profile(profile.model_copy(update={"onboarded": True}))
    app = create_app(ctx, token=TOKEN)
    starts: list[int] = []
    start = ctx.worker.start

    async def counted() -> None:
        starts.append(1)
        await start()

    monkeypatch.setattr(ctx.worker, "start", counted)
    port = _free_port()
    config = uvicorn.Config(app, host=LOOPBACK, port=port, log_level="warning", loop="asyncio")
    config.load()
    computer = uvicorn.Server(config)
    computer.lifespan = config.lifespan_class(config)
    await computer.startup()
    headers = {"Authorization": f"Bearer {TOKEN}", "X-Ordnung-Client": "test"}
    try:
        async with httpx.AsyncClient(
            base_url=f"http://{LOOPBACK}:{port}", headers=headers, trust_env=False
        ) as pc:
            yield {"pc": pc, "access": app.state.ordnung.phone, "starts": starts, "data_dir": data_dir}
    finally:
        await computer.shutdown()
        ctx.close()


def _phone(url: str, data_dir: Path) -> httpx.AsyncClient:
    trust = ssl.create_default_context(cafile=str(data_dir / "phone" / "ca.pem"))
    headers = {"Origin": url, "X-Ordnung-Client": "web", "Sec-Fetch-Site": "same-origin"}
    return httpx.AsyncClient(base_url=url, verify=trust, trust_env=False, headers=headers, timeout=10)


async def _pair(pc: httpx.AsyncClient, phone: httpx.AsyncClient, port: int) -> str:
    code = (await pc.post("/api/phone/pairing")).json()["code"]
    answer = await phone.post("/api/phone/pair", json={"code": code, "name": "Sam's iPhone"})
    assert answer.status_code == 200, answer.text
    token = answer.cookies[cookie_name(port)]
    phone.headers["Cookie"] = f"{cookie_name(port)}={token}"
    return token


async def _read_events(phone: httpx.AsyncClient) -> int:
    lines = 0
    async with phone.stream("GET", "/api/events") as stream:
        assert stream.status_code == 200
        async for _line in stream.aiter_lines():
            lines += 1
    return lines


async def _streaming(pc: httpx.AsyncClient, within: float = 10.0) -> dict[str, Any]:
    """The paired phone once its live stream is open (``active``), however slow the runner."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within
    while True:
        device: dict[str, Any] = (await pc.get("/api/phone")).json()["devices"][0]
        if device["active"]:
            return device
        assert loop.time() < deadline, "the phone's live stream never opened"
        await asyncio.sleep(0.05)


async def test_a_phone_listener_runs_next_to_the_computer_s(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handlers = (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM))
    async with _serving(data_dir, monkeypatch) as served:
        pc: httpx.AsyncClient = served["pc"]
        access: PhoneAccess = served["access"]
        port = _free_port()
        status = (await pc.put("/api/phone", json={"enabled": True, "port": port})).json()
        assert status["listening"] is True and status["url"] == f"https://{LOOPBACK}:{port}", status
        server = access._server
        bound = {sock.getsockname()[:2] for listener in server.servers for sock in listener.sockets}  # type: ignore[attr-defined]
        assert bound == {(LOOPBACK, port)}  # exactly this address, never 0.0.0.0
        assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == handlers
        assert served["starts"] == [1]  # one lifespan for both listeners

        async with _phone(status["url"], data_dir) as phone:
            health = await phone.get("/api/health")  # the certificate verifies against the authority
            assert health.status_code == 401 and health.json()["code"] == "phone_not_paired"
            await _pair(pc, phone, port)
            assert (await phone.get("/api/health")).json()["client"] == "phone"

            reader = asyncio.create_task(_read_events(phone))
            device = await _streaming(pc)
            assert not reader.done()
            assert (await pc.delete(f"/api/phone/devices/{device['id']}")).status_code == 200
            await asyncio.wait_for(reader, STREAM_ENDS_S)
            assert (await phone.get("/api/health")).status_code == 401
            assert (await pc.get("/api/health")).json()["client"] == "computer"

            await _pair(pc, phone, port)
            reader = asyncio.create_task(_read_events(phone))
            await _streaming(pc)
            off_at = asyncio.get_running_loop().time()
            assert (await pc.put("/api/phone", json={"enabled": False})).json()["listening"] is False
            assert asyncio.get_running_loop().time() - off_at <= GRACEFUL_STOP_S + SLOW_RUNNER_S
            await asyncio.wait_for(reader, STREAM_ENDS_S)
        async with _phone(status["url"], data_dir) as late:
            with pytest.raises(httpx.ConnectError):
                await late.get("/api/health")
        assert (await pc.get("/api/health")).status_code == 200
        assert AppStatus.should_exit is False
    assert AppStatus.should_exit is False
    assert (signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)) == handlers


async def test_a_busy_port_and_a_missing_address_are_problems(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _serving(data_dir, monkeypatch) as served:
        pc: httpx.AsyncClient = served["pc"]
        access: PhoneAccess = served["access"]
        with socket.socket() as taken:
            taken.bind((LOOPBACK, 0))
            taken.listen(1)
            busy = taken.getsockname()[1]
            status = (await pc.put("/api/phone", json={"enabled": True, "port": busy})).json()
            assert status["enabled"] is True and status["listening"] is False
            assert status["problem"]["code"] == "port_busy"
            assert (await pc.get("/api/health")).status_code == 200  # no exit
        port = _free_port()
        assert (await pc.put("/api/phone", json={"enabled": True, "port": port})).json()["listening"] is True
        monkeypatch.setattr(access.network, "is_local", lambda _address: False)
        await access.check()
        paused = (await pc.get("/api/phone")).json()
        assert paused["listening"] is False and paused["problem"]["code"] == "address_gone"
        monkeypatch.undo()
        monkeypatch.setenv(TEST_ADDRESS_ENV, LOOPBACK)
        await access.check()
        assert (await pc.get("/api/phone")).json()["listening"] is True
        async with _phone(f"https://{LOOPBACK}:{port}", data_dir) as phone:
            assert (await phone.get("/api/health")).status_code == 401
