"""Shared helpers for the phone-access tests (no tests here): a fake network and listener server, an app
with phone access on, a client that talks to it as a phone on the home network, and pairing."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ordnung.api.phone_gate import PhoneListener
from ordnung.phone import cookie_name
from ordnung.phone.access import PhoneAccess
from ordnung.phone.net import Candidate
from test_api_support import Api, api_for

TOKEN = "session-token-for-tests"
ADDRESS = "192.168.1.5"
SUBNET = "192.168.1.0/24"
PORT = 8767
PHONE_URL = f"https://{ADDRESS}:{PORT}"
PHONE_IP = "192.168.1.57"
OTHER_PHONE_IP = "192.168.1.58"
COOKIE = cookie_name(PORT)
IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.5 Mobile/15E148 Safari/604.1"
)
PHONE_HEADERS = {
    "X-Ordnung-Client": "web",
    "Origin": PHONE_URL,
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": IPHONE_UA,
}


@dataclass
class FakeNetwork:
    """The computer's network as a test sets it."""

    candidates_now: list[Candidate] = field(
        default_factory=lambda: [Candidate(ADDRESS, "en0", SUBNET, recommended=True)]
    )
    local: set[str] = field(default_factory=lambda: {ADDRESS})
    busy: set[tuple[str, int]] = field(default_factory=set)
    router: str | None = "192.168.1.1 aa:bb:cc:dd:ee:ff"

    def candidates(self) -> list[Candidate]:
        return [c for c in self.candidates_now if c.address in self.local]

    def is_local(self, address: str) -> bool:
        return address in self.local

    def port_free(self, address: str, port: int) -> bool:
        return (address, port) not in self.busy

    def gateway(self) -> str | None:
        return self.router


@dataclass
class FakeServer:
    """A listener server that binds nothing."""

    config: Any
    started: int = 0
    stopped: int = 0

    async def startup(self) -> None:
        self.started += 1

    async def shutdown(self) -> None:
        self.stopped += 1


@dataclass
class Servers:
    """Every fake server phone access made (``servers.made[-1]`` is the current one)."""

    made: list[FakeServer] = field(default_factory=list)

    def __call__(self, config: Any) -> FakeServer:
        server = FakeServer(config)
        self.made.append(server)
        return server


def phone_of(api: Api) -> PhoneAccess:
    access: PhoneAccess = api.app.state.ordnung.phone
    return access


def fake_phone_access(api: Api, network: FakeNetwork | None = None) -> tuple[FakeNetwork, Servers]:
    """Give the app's phone access a fake network and server factory."""
    access = phone_of(api)
    net = network or FakeNetwork()
    servers = Servers()
    access.network = net  # type: ignore[assignment]
    access.server_factory = servers
    return net, servers


def phone_client(api: Api, client_ip: str = PHONE_IP, **headers: str) -> httpx.AsyncClient:
    """A client that talks to the phone listener as a device on the home network."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=PhoneListener(api.app), client=(client_ip, 50000)),
        base_url=PHONE_URL,
        headers={**PHONE_HEADERS, **headers},
    )


async def onboard(api: Api) -> None:
    profile = api.ctx.store.get_profile()
    api.ctx.store.save_profile(profile.model_copy(update={"onboarded": True, "name": "Sam Rivera"}))


@asynccontextmanager
async def phone_app(
    data_dir: Path, *, network: FakeNetwork | None = None, on: bool = True, **kwargs: Any
) -> AsyncIterator[tuple[Api, FakeNetwork, Servers]]:
    """An app with a session token, onboarded, a fake network and server, and phone access on."""
    async with api_for(data_dir, token=TOKEN, **kwargs) as api:
        api.client.headers["Authorization"] = f"Bearer {TOKEN}"
        net, servers = fake_phone_access(api, network)
        await onboard(api)
        if on:
            response = await api.client.put("/api/phone", json={"enabled": True})
            assert response.status_code == 200, response.text
            assert response.json()["listening"] is True, response.json()
        try:
            yield api, net, servers
        finally:
            await phone_of(api).stop()


async def pair(api: Api, phone: httpx.AsyncClient, name: str = "Sam's iPhone") -> dict[str, Any]:
    """Pair ``phone`` with a fresh code; returns the answer and keeps the cookie in ``phone``."""
    made = await api.client.post("/api/phone/pairing")
    assert made.status_code == 200, made.text
    answer = await phone.post("/api/phone/pair", json={"code": made.json()["code"], "name": name})
    assert answer.status_code == 200, answer.text
    cookie = answer.cookies.get(COOKIE)
    assert cookie, answer.headers
    phone.cookies.set(COOKIE, cookie, domain=ADDRESS)
    return {**answer.json(), "token": cookie, "set_cookie": answer.headers["set-cookie"]}


# --------------------------------------------------------------------------------------------------
# raw ASGI: what an HTTP client library won't send (a lying length, an endless body, a live stream)
# --------------------------------------------------------------------------------------------------


@dataclass
class Exchange:
    """One request driven through the ASGI app by hand."""

    messages: list[dict[str, Any]] = field(default_factory=list)
    read: int = 0
    received: int = 0
    started: asyncio.Event = field(default_factory=asyncio.Event)
    left: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def status(self) -> int:
        return int(next(m["status"] for m in self.messages if m["type"] == "http.response.start"))

    @property
    def headers(self) -> dict[str, str]:
        start = next(m for m in self.messages if m["type"] == "http.response.start")
        return {bytes(k).decode().lower(): bytes(v).decode() for k, v in start.get("headers", [])}

    @property
    def body(self) -> bytes:
        return b"".join(m.get("body", b"") for m in self.messages if m["type"] == "http.response.body")

    @property
    def complete(self) -> bool:
        return any(m["type"] == "http.response.body" and not m.get("more_body") for m in self.messages)


async def drive(
    app: Any,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    chunks: Iterable[bytes] = (),
    client: str = PHONE_IP,
    server: tuple[str, int] = (ADDRESS, PORT),
    scheme: str = "https",
    query: str = "",
    exchange: Exchange | None = None,
    scope_type: str = "http",
) -> Exchange:
    """Run one request through ``app`` with a body made of ``chunks`` (read lazily; ``read`` counts the
    bytes the app took). After the body the client waits until ``exchange.left`` is set."""
    found = exchange or Exchange()
    pending = iter(chunks)
    upcoming = next(pending, None)
    sent = {**{"host": f"{ADDRESS}:{PORT}"}, **(headers or {})}

    async def receive() -> dict[str, Any]:
        nonlocal upcoming
        found.received += 1
        if scope_type == "websocket":
            return {"type": "websocket.connect"}
        if upcoming is not None:
            chunk, upcoming = upcoming, next(pending, None)
            found.read += len(chunk)
            return {"type": "http.request", "body": chunk, "more_body": upcoming is not None}
        if found.received == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await found.left.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        found.messages.append(message)
        if message["type"] == "http.response.start":
            found.started.set()

    scope = {
        "type": scope_type,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": scheme if scope_type == "http" else "wss",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in sent.items()],
        "client": (client, 50000),
        "server": server,
        "state": {},
    }
    await app(scope, receive, send)
    return found
