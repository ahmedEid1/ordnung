"""Phone access at run time: the second listener, the paired phones and the pairing code (policy:
:mod:`ordnung.phone`).

One :class:`PhoneAccess` lives on the API's state, next to the watched folder. It owns the saved
record (:mod:`ordnung.phone.record`), the paired phones' sign-ins (hashes only), the pairing desk
(:mod:`ordnung.phone.pairing`), the certificates (:mod:`ordnung.phone.tls`), a watcher and the phone
listener itself.

**The listener** is a second ``uvicorn.Server`` on the same event loop and the same app as
``ordnung serve``'s, bound to one home-network address and a saved port, never ``0.0.0.0``. It is
started with ``startup()`` and stopped with ``shutdown()``, never ``serve()`` or ``run()`` (they would
take over Ctrl+C and SIGTERM, and sse-starlette's process-wide shutdown watcher could then bind to it);
``sse_starlette``'s ``AppStatus.should_exit`` is never touched (it would end the computer's streams
too). Its config: lifespan off (one worker, one daily tick, one folder watcher per process — the
computer listener's), no proxy headers, no uvicorn log config or access log, no ``server`` header, no
websockets, at most :data:`LIMIT_CONCURRENCY` connections and :data:`GRACEFUL_STOP_S` seconds for a
stop. Starting and stopping are serialised; certificate work, address discovery and record writes run
in a thread. A busy port, a missing address or anything else that keeps it from starting is a
*problem* shown in Settings, never an exit.

**Turning it off, removing a phone** never cuts a request that writes: only live streams
(``/api/events``, Ask) are cancelled and an upload whose body is still arriving is stopped (told the
phone was removed, or that phone access stopped); an upload that arrived in full is filed and answered,
every other request that was running finishes, and the next one is refused — so is one the gate had
admitted but not yet handed on. Cancelling a request that waits inside the ledger lock would let a
second writer in while the first one's thread is still writing. Requests count as in flight from the
moment the gate admits them (:meth:`PhoneAccess.admit`), so a stop waits for each of them (at most
:data:`DRAIN_S` seconds) before the listener closes; one that runs longer is never cut by the
listener's own stop either (the gate shields it), it just can't answer any more.

**The watcher** runs while phone access is on. Every :data:`WATCH_INTERVAL_S` seconds it checks that
this computer still has the address and is still behind the same router: if not, phone access pauses
(``address_gone``, ``other_network``) and resumes when both are back — it never moves to another address
by itself, it can't tell a café's network from home. A router that couldn't be read when phone access
was turned on is saved the first time it can be (never over a saved one). Once a day it renews the
certificate when due and forgets phones unused for :data:`DEVICE_IDLE_DAYS` days; every
:data:`SEEN_WRITE_EVERY_S` seconds it saves when phones were last used. A phone unused for that long is
also refused (and forgotten) when it comes back — after a restart, or with phone access turned on
again, before the watcher's first round — and the paired phones are swept when phone access starts.

**A phone's sign-in** (a 256-bit token in its cookie; only its SHA-256 is saved) changes at most once an
hour, on a page load. The previous one stays valid for :data:`PREVIOUS_GRACE_S` seconds after the phone
first uses the new one (a phone that never got the new one keeps the previous); one of its earlier
sign-ins coming back means it was copied, and the phone is signed out with a notice on the computer.
Two page loads that cross the change make one new sign-in between them: the one that came with the
previous sign-in leaves the cookie alone while the new one is in use or just made.

**Limits per phone**: :data:`DEVICE_LIMITS` (Ask, the everyday actions that ask Claude, letters added)
per hour; more gets 429 with ``Retry-After``. An upload counts each letter it adds (photos combined into
one letter count once), so one request can't queue more readings than the hour allows. At most
:data:`MAX_PHONES` phones are paired.

**Why a phone was signed out** is kept in memory for each of its sign-ins (:data:`RemovedBy`), so its
next request — the copy's or the phone's own — can say so (``?removed=token_reuse`` on the pairing
page); after a restart a phone the computer doesn't know is just "removed".

Record writes go through one writer: each takes its snapshot on the event loop and a newer snapshot
always wins, so a write of when a phone was last seen can never bring back a phone removed meanwhile;
removing a phone is saved before its answer.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

import anyio
from starlette.types import ASGIApp

from ordnung.app_context import AppContext
from ordnung.db.store import background_context
from ordnung.ids import new_id
from ordnung.phone import PhoneRefusal, tls
from ordnung.phone.net import Candidate, Network, subnet_of
from ordnung.phone.pairing import (
    PAIR_POSTS_PER_CLIENT_PER_MINUTE,
    PAIR_POSTS_PER_MINUTE,
    PAIRING_TRIES_TOTAL,
    PairingDesk,
    SlidingLimit,
    check_words,
    clean_name,
    new_check_key,
    platform_label,
    unique_name,
)
from ordnung.phone.record import (
    DEFAULT_PORT,
    RETIRED_KEPT,
    PhoneDeviceRecord,
    PhoneRecord,
    load_record,
    save_record,
)

log = logging.getLogger("ordnung.phone")

LIMIT_CONCURRENCY = 128
GRACEFUL_STOP_S = 2
KEEP_ALIVE_S = 5
DRAIN_S = 30.0
WATCH_INTERVAL_S = 30.0
DAILY_S = 24 * 3600.0
SEEN_WRITE_EVERY_S = 600.0
DEVICE_IDLE_DAYS = 30
MAX_PHONES = 10
NOTICE_S = 600.0
ROTATE_EVERY_S = 3600.0
PREVIOUS_GRACE_S = 120.0
RECENT_DAYS = 30
PORTS = range(DEFAULT_PORT, DEFAULT_PORT + 9)
#: Per phone and hour: ``(limit, window seconds)`` for Ask, the everyday actions that ask Claude
#: (read again, translate, write a letter, the daily note) and uploads (each letter an upload adds, each
#: proof of sending).
DEVICE_LIMITS: dict[str, tuple[int, float]] = {
    "ask": (30, 3600.0),
    "model": (20, 3600.0),
    "upload": (30, 3600.0),
}

DEMO_MESSAGE = "The demo never opens itself to your network. Install Ordnung to use it from your phone."
NO_TOKEN_MESSAGE = (
    "Phone access needs Ordnung's sign-in link: start Ordnung without “--no-token” to use it from your phone."
)
NOT_SET_UP_MESSAGE = "Finish setting up Ordnung first, then turn on phone access."
NO_NETWORK_MESSAGE = "This computer isn't on a home network right now."
INVALID_ADDRESS_MESSAGE = (
    "That address isn't one of this computer's on a home network. Choose one of the addresses listed."
)
NOT_LISTENING_MESSAGE = "Phone access is off or paused, so no phone can pair now."
PHONE_OFF_MESSAGE = "Phone access is turned off on your computer."
PHONE_STOPPED_MESSAGE = (
    "Phone access stopped on your computer while this was on its way, so it didn't arrive. "
    "Try again when phone access is back."
)
TOO_MANY_PHONES_MESSAGE = (
    f"Ordnung already has {MAX_PHONES} phones paired. Remove one in Settings → Phone on your computer."
)
WRONG_CODE_MESSAGE = "That code didn't match, or it has expired."
CODE_USED_MESSAGE = (
    "This code was already used, so neither phone is paired. Make a new code on your computer and pair again."
)
TOO_MANY_TRIES_MESSAGE = (
    "Too many wrong codes from this phone. Make a new code on your computer and try again."
)
TOO_MANY_PAIRING_MESSAGE = "Too many pairing tries on your network just now. Wait a minute and try again."
LIMIT_MESSAGES = {
    "ask": "This phone asked a lot of questions in the last hour. Ask again later, or on your computer.",
    "model": "This phone asked Claude for a lot in the last hour. Try again later, or on your computer.",
    "upload": "This phone added a lot of letters in the last hour. Try again later, or on your computer.",
}
UPLOAD_TOO_MANY_MESSAGE = (
    "A phone can add up to {limit} letters an hour. Add fewer at once, or add these on your computer."
)

ProblemCode = Literal["no_network", "address_gone", "other_network", "port_busy", "failed"]
NoticeCode = Literal["pairing_stopped", "code_reused", "token_reuse"]
RemovedBy = Literal["computer", "unused", "address_changed", "reset", "code_reused", "token_reuse"]
LiveKind = Literal["events", "ask", "upload", "other"]
#: Why a request in flight was revoked: the phone was removed (:data:`RemovedBy`) or the listener stops.
RevokedBy = RemovedBy | Literal["stopped"]
#: How many sign-ins of removed phones keep their reason (see the module docstring).
SIGNED_OUT_KEPT = 256

_REMOVED_WHY: dict[RemovedBy, str] = {
    "computer": "",
    "unused": f": not used for {DEVICE_IDLE_DAYS} days",
    "address_changed": ": the computer's address changed",
    "reset": ": phone access started over",
    "code_reused": ": two devices used its pairing code",
    "token_reuse": ": its sign-in was used from two places",
}


def problem_detail(code: ProblemCode, address: str | None, port: int) -> str:
    """Why phone access is on but not listening, in words for the person."""
    where = address or "its address"
    return {
        "no_network": "Waiting for a home network.",
        "address_gone": f"Paused: this computer isn't on {where} any more.",
        "other_network": f"Paused: this computer is on {where}, but on a different network than before.",
        "port_busy": f"Another program uses port {port}.",
        "failed": "Phone access couldn't start.",
    }[code]


def notice_detail(code: NoticeCode, addresses: list[str], name: str | None = None) -> str:
    """A notice for the computer, in words for the person."""
    if code == "pairing_stopped":
        where = ", ".join(addresses) or "an unknown address"
        return (
            f"{PAIRING_TRIES_TOTAL} wrong pairing codes were typed on your network, so the code was "
            f"cancelled. They came from {where}."
        )
    if code == "code_reused":
        return "Two devices used the same code, so neither is paired. Someone else may have seen your screen."
    return (
        f"{name or 'A phone'} was signed out because its sign-in was used from two places. "
        "Pair it again if it's yours."
    )


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seconds(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def _unused(device: PhoneDeviceRecord, now: float) -> bool:
    """Not used for :data:`DEVICE_IDLE_DAYS` days (since it was last seen, or paired)."""
    used = _seconds(device.last_seen_at) or _seconds(device.paired_at) or now
    return used < now - DEVICE_IDLE_DAYS * 86400


def token_hash(token: str) -> str:
    """The SHA-256 (hex) a phone's sign-in is saved as."""
    return hashlib.sha256(token.encode("utf-8", "replace")).hexdigest()


# --------------------------------------------------------------------------------------------------
# the listener server (replaced in tests)
# --------------------------------------------------------------------------------------------------


class ListenerServer(Protocol):
    """What phone access needs of a ``uvicorn.Server``."""

    async def startup(self) -> None: ...

    async def shutdown(self) -> None: ...


ServerFactory = Callable[[Any], ListenerServer]
"""``(uvicorn.Config) -> server``: the real one makes a ``uvicorn.Server``; tests pass a fake."""


def uvicorn_server(config: Any) -> ListenerServer:
    """A ``uvicorn.Server`` for ``config``, ready for ``startup()`` (which reads ``server.lifespan``;
    only ``serve()`` would set it)."""
    import uvicorn

    server = uvicorn.Server(config)
    server.lifespan = config.lifespan_class(config)
    return server


def listener_config(app: ASGIApp, address: str, port: int, certs: tls.Certificates) -> Any:
    """The phone listener's ``uvicorn.Config`` (loaded: its TLS context is built)."""
    import ssl

    import uvicorn

    config = uvicorn.Config(
        app,
        host=address,
        port=port,
        ssl_certfile=str(certs.server_pem),
        ssl_keyfile=str(certs.server_key),
        lifespan="off",  # one worker, tick and folder watcher per process: the computer listener's
        proxy_headers=False,  # X-Forwarded-* from the network is never trusted
        log_config=None,  # never re-apply uvicorn's logging config while Ordnung runs
        log_level="warning",
        access_log=False,
        server_header=False,
        ws="none",
        limit_concurrency=LIMIT_CONCURRENCY,
        timeout_keep_alive=KEEP_ALIVE_S,
        timeout_graceful_shutdown=GRACEFUL_STOP_S,
    )
    config.load()
    if config.ssl is not None:
        config.ssl.minimum_version = ssl.TLSVersion.TLSv1_2
    return config


# --------------------------------------------------------------------------------------------------
# requests in flight
# --------------------------------------------------------------------------------------------------


@dataclass(eq=False)
class Live:
    """A request the phone listener admitted: from the gate's first check until its answer (or, for one
    the listener's stop cut off, until what it started has finished)."""

    device_id: str | None = None
    kind: LiveKind = "other"
    scope: anyio.CancelScope = field(default_factory=anyio.CancelScope)
    revoked: asyncio.Event = field(default_factory=asyncio.Event)
    #: Why it was revoked (the first reason wins).
    reason: RevokedBy | None = None
    #: The app's run of a request that isn't a stream (shielded from the listener's stop).
    running: asyncio.Future[None] | None = None

    @property
    def stream(self) -> bool:
        return self.kind in ("events", "ask")

    def revoke(self, reason: RevokedBy) -> None:
        """The phone was removed or the listener stops: a stream ends now, an upload whose body is still
        arriving is stopped; anything else that is running finishes (its answer still goes out). A request
        not yet handed to the app is refused."""
        if self.reason is None:
            self.reason = reason
        self.revoked.set()
        if self.stream:
            self.scope.cancel()

    def become(self, device_id: str | None, kind: LiveKind) -> None:
        """What the gate found out about the request (whose it is, what it does)."""
        self.device_id, self.kind = device_id, kind
        if self.revoked.is_set() and self.stream:
            self.scope.cancel()


@dataclass
class Notice:
    code: NoticeCode
    detail: str
    at: float
    addresses: list[str]


@dataclass(frozen=True)
class Auth:
    """What a request's cookie turned out to be (``removed``: why a sign-in this computer no longer knows
    was signed out, when it still remembers)."""

    device: PhoneDeviceRecord | None = None
    unknown: bool = False
    removed: RemovedBy | None = None


@dataclass(frozen=True)
class Paired:
    device: PhoneDeviceRecord
    token: str | None
    words: str


# --------------------------------------------------------------------------------------------------
# phone access
# --------------------------------------------------------------------------------------------------


class PhoneAccess:
    """Phone access of one running Ordnung (see the module docstring)."""

    def __init__(self, ctx: AppContext, *, demo: bool, token_on: bool) -> None:
        self.ctx = ctx
        self.demo = demo
        self.token_on = token_on
        #: Tests may turn phone access on although the server runs without a session token.
        self.allow_without_token = False
        self.network = Network()
        self.server_factory: ServerFactory = uvicorn_server
        self.clock: Callable[[], float] = time.time
        self.listener_app: ASGIApp | None = None
        self.public_files: frozenset[str] = frozenset()
        self.record = PhoneRecord()
        self.desk = PairingDesk()
        self.problem: ProblemCode | None = None
        self.notice: Notice | None = None
        self.bound: tuple[str, int] | None = None
        self.certificates: tls.Certificates | None = None
        self.pair_limit_client = SlidingLimit(PAIR_POSTS_PER_CLIENT_PER_MINUTE, 60.0)
        self.pair_limit_all = SlidingLimit(PAIR_POSTS_PER_MINUTE, 60.0)
        self._device_limits = {kind: SlidingLimit(n, window) for kind, (n, window) in DEVICE_LIMITS.items()}
        self._loaded = False
        self._index: dict[str, tuple[str, Literal["current", "previous", "retired"]]] = {}
        self._server: ListenerServer | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._lock: asyncio.Lock | None = None
        self._live: set[Live] = set()
        self._signed_out: dict[str, RemovedBy] = {}
        self._idle = asyncio.Event()  # set while no request is in flight
        self._idle.set()
        self._seen_dirty = False
        self._last_flush = 0.0
        self._last_daily = 0.0
        self._paused = False
        self._version = 0
        self._written = 0
        self._write_lock = threading.Lock()

    # ------------------------------------------------------------------------------ basics

    @property
    def folder(self) -> Path:
        return self.ctx.paths.phone

    @property
    def available(self) -> bool:
        """Phone access can be used here: never in the demo, never without a session token."""
        return self.unavailable_reason is None

    @property
    def unavailable_reason(self) -> str | None:
        if self.demo or self.ctx.settings.demo:
            return DEMO_MESSAGE
        if not (self.token_on or self.allow_without_token):
            return NO_TOKEN_MESSAGE
        return None

    @property
    def listening(self) -> bool:
        return self.bound is not None

    @property
    def url(self) -> str | None:
        return f"https://{self.bound[0]}:{self.bound[1]}" if self.bound else None

    @property
    def devices(self) -> list[PhoneDeviceRecord]:
        self._load()
        return self.record.devices

    def device(self, device_id: str) -> PhoneDeviceRecord | None:
        return next((d for d in self.devices if d.id == device_id), None)

    def bind_app(self, listener_app: ASGIApp, public_files: frozenset[str] = frozenset()) -> None:
        """The app the listener serves (the API's app behind the phone listener's tag) and the built
        web app's public files (what a phone may load before it is paired)."""
        self.listener_app = listener_app
        self.public_files = public_files

    def _guard(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _load(self, *, force: bool = False) -> None:
        if self._loaded and not force:
            return
        self.record = load_record(self.ctx.store)
        self._loaded = True
        self._reindex()

    def _reindex(self) -> None:
        index: dict[str, tuple[str, Literal["current", "previous", "retired"]]] = {}
        for device in self.record.devices:
            for digest in device.retired:
                index[digest] = (device.id, "retired")
            if device.previous_sha256:
                index[device.previous_sha256] = (device.id, "previous")
            index[device.token_sha256] = (device.id, "current")
        self._index = index

    def _require_available(self) -> None:
        reason = self.unavailable_reason
        if reason is not None:
            raise PhoneRefusal("unavailable", reason)

    async def _save(self) -> None:
        """Save the record as it is now (a newer snapshot always wins over an older one)."""
        self._version += 1
        version, snapshot = self._version, self.record.model_copy(deep=True)
        await asyncio.to_thread(self._write, version, snapshot)

    def _write(self, version: int, record: PhoneRecord) -> None:
        with self._write_lock:
            if version <= self._written:
                return
            save_record(self.ctx.store, record)
            self._written = version

    def _discard_pending_writes(self) -> None:
        with self._write_lock:
            self._version += 1
            self._written = self._version

    async def _log(self, kind: str, message: str, **data: Any) -> None:
        await asyncio.to_thread(self.ctx.store.log_activity, kind, message, data=data)

    # ------------------------------------------------------------------------------ status

    async def status(self) -> dict[str, Any]:
        """What Settings → Phone shows (``PhoneStatus``); re-checks the addresses, writes nothing."""
        self._load()
        reason = self.unavailable_reason
        now = self.clock()
        if reason is not None:
            return {
                "available": False,
                "unavailable_reason": reason,
                "enabled": False,
                "listening": False,
                "url": None,
                "address": None,
                "subnet": None,
                "port": self.record.port,
                "addresses": [],
                "problem": None,
                "notice": None,
                "fingerprint": None,
                "ca_fingerprint": None,
                "ca_made_at": None,
                "certificate_until": None,
                "certificate_changed_at": None,
                "pairing": None,
                "devices": [],
            }
        record = self.record
        candidates = await asyncio.to_thread(self.network.candidates)
        certs = self.certificates
        if certs is None and record.address:
            certs = await asyncio.to_thread(tls.read, self.folder, record.address)
        changes = await asyncio.to_thread(self._recent_changes, now)
        pairing = self.desk.current(now) if self.listening else None
        notice = self.notice if self.notice is not None and now - self.notice.at < NOTICE_S else None
        problem = self.problem if record.enabled else None
        return {
            "available": True,
            "unavailable_reason": None,
            "enabled": record.enabled,
            "listening": self.listening,
            "url": self.url,
            "address": record.address,
            "subnet": record.subnet,
            "port": record.port,
            "addresses": [_choice(c) for c in candidates],
            "problem": {"code": problem, "detail": problem_detail(problem, record.address, record.port)}
            if problem
            else None,
            "notice": {
                "code": notice.code,
                "detail": notice.detail,
                "at": _iso(notice.at),
                "addresses": list(notice.addresses),
            }
            if notice
            else None,
            "fingerprint": certs.fingerprint if certs else None,
            "ca_fingerprint": certs.ca_fingerprint if certs else None,
            "ca_made_at": certs.ca_made_at if certs else None,
            "certificate_until": certs.until if certs else None,
            "certificate_changed_at": record.certificate_changed_at,
            "pairing": {
                "expires_at": _iso(pairing.expires),
                "opened_at": pairing.opened_at,
                "opened_from": pairing.opened_from,
                "wrong_tries": pairing.wrong_tries,
                "wrong_from": list(pairing.wrong),
            }
            if pairing
            else None,
            "devices": [self._device_view(device, changes) for device in record.devices],
        }

    def _device_view(self, device: PhoneDeviceRecord, changes: dict[str, int]) -> dict[str, Any]:
        return {
            "id": device.id,
            "name": device.name,
            "platform": device.platform,
            "check_words": self.words(device.id),
            "paired_at": device.paired_at,
            "last_seen_at": device.last_seen_at,
            "last_address": device.last_address,
            "active": any(live.device_id == device.id and live.kind == "events" for live in self._live),
            "recent_changes": changes.get(device.id, 0),
        }

    def _recent_changes(self, now: float) -> dict[str, int]:
        since = _iso(now - RECENT_DAYS * 86400)
        return self.ctx.store.count_activity("phone.changed", "device", since=since)

    def words(self, device_id: str) -> str:
        """The two check words of a paired phone."""
        if not self.record.check_key:
            self.record.check_key = new_check_key()
        return check_words(self.record.check_key, device_id)

    # ------------------------------------------------------------------------------ on and off

    async def start_if_enabled(self) -> None:
        """At start: listen again when phone access was left on (never in the demo or without a token;
        a failure is a problem in Settings, never an error here)."""
        if not self.available:
            return
        try:
            async with self._guard():
                self._load(force=True)
                if not self.record.enabled:
                    return
                await self._forget_unused(self.clock())
                await self._bind()
                if self.problem in ("address_gone", "no_network", "other_network"):
                    await self._paused_now()
            self._start_watcher()
        except Exception:
            log.exception("phone access couldn't start")
            self.problem = "failed"

    async def stop(self) -> None:
        """Ordnung is stopping: phones' requests end, the listener closes (phone access stays on)."""
        await self._stop_watcher()
        async with self._guard():
            await self._unbind()
            if self._seen_dirty:
                self._seen_dirty = False
                await self._save()

    async def forget(self) -> None:
        """Delete everything is about to wipe the data folder: stop and forget all of it in memory (the
        wipe drops the record and the certificates)."""
        await self._stop_watcher()
        async with self._guard():
            await self._unbind()
            await asyncio.to_thread(self._discard_pending_writes)
            self.record = PhoneRecord()
            self._loaded = True
            self._reindex()
            self._signed_out.clear()
            self.desk.clear()
            self.problem = None
            self.notice = None
            self.certificates = None
            self._seen_dirty = False
            self._paused = False

    async def change(
        self,
        *,
        enabled: bool,
        address: str | None = None,
        port: int | None = None,
        home_network: bool = False,
    ) -> None:
        """``PUT /api/phone``: turn phone access on (at the chosen, saved or recommended address) or off."""
        self._require_available()
        await self._stop_watcher()
        try:
            async with self._guard():
                self._load()
                if enabled:
                    await self._turn_on(address, port, home_network)
                else:
                    await self._turn_off()
        finally:
            if self.record.enabled:
                self._start_watcher()

    async def _turn_off(self) -> None:
        self.desk.cancel()
        await self._unbind()
        self.problem = None
        self._paused = False
        if self.record.enabled:
            self.record.enabled = False
            await self._save()
            await self._log("phone.disabled", "Phone access turned off")

    async def _turn_on(self, address: str | None, port: int | None, home_network: bool) -> None:
        record = self.record
        if not self.ctx.store.get_profile().onboarded:
            raise PhoneRefusal("not_set_up", NOT_SET_UP_MESSAGE)
        candidates = await asyncio.to_thread(self.network.candidates)
        if not candidates:
            raise PhoneRefusal("no_network", NO_NETWORK_MESSAGE)
        by_address = {c.address: c for c in candidates}
        if address is not None and address not in by_address:
            raise PhoneRefusal("invalid", INVALID_ADDRESS_MESSAGE)
        chosen = (
            by_address.get(address or "")
            or by_address.get(record.address or "")
            or next((c for c in candidates if c.recommended), candidates[0])
        )
        if port is None:
            port = record.port if record.address else await self._free_port(chosen.address)
        moved = record.address is not None and (chosen.address != record.address or port != record.port)
        was_on = record.enabled
        if moved:
            self.desk.cancel()
            await self._unbind()
            await self._drop_all("address_changed")
        if moved or home_network or not was_on or record.gateway is None:
            record.gateway = await asyncio.to_thread(self.network.gateway)
        record.address, record.port = chosen.address, port
        record.interface, record.subnet = chosen.interface, chosen.subnet or subnet_of(chosen.address, None)
        record.enabled = True
        if not was_on or moved:
            record.enabled_at = _iso(self.clock())
        if not was_on:
            await self._forget_unused(self.clock())
        if not self.listening:
            await self._bind()
        await self._save()
        if not was_on or moved:
            url = f"https://{record.address}:{record.port}"
            await self._log(
                "phone.enabled", f"Phone access turned on at {url}", address=record.address, port=port
            )

    async def _free_port(self, address: str) -> int:
        for candidate in PORTS:
            if await asyncio.to_thread(self.network.port_free, address, candidate):
                return candidate
        return DEFAULT_PORT

    async def reset(self) -> None:
        """``POST /api/phone/reset`` ("Start over"): off, every phone removed, the certificates deleted."""
        if self.demo or self.ctx.settings.demo:
            raise PhoneRefusal("unavailable", DEMO_MESSAGE)
        await self._stop_watcher()
        async with self._guard():
            self._load()
            was_on = self.record.enabled
            self.desk.clear()
            await self._unbind()
            await self._drop_all("reset")
            self.record = PhoneRecord()
            self._reindex()
            self.problem = None
            self.notice = None
            self.certificates = None
            self._paused = False
            await asyncio.to_thread(tls.remove, self.folder)
            await self._save()
            if was_on:
                await self._log("phone.disabled", "Phone access turned off: it starts over")

    # ------------------------------------------------------------------------------ the listener

    async def _bind(self) -> bool:
        """Start listening at the saved address and port (``False``: a problem keeps it from it)."""
        record = self.record
        address, port = record.address, record.port
        if address is None:
            self.problem = "no_network"
            return False
        if not await asyncio.to_thread(self.network.is_local, address):
            others = await asyncio.to_thread(self.network.candidates)
            self.problem = "address_gone" if others else "no_network"
            return False
        if await self._other_network():
            self.problem = "other_network"
            return False
        try:
            certs = await asyncio.to_thread(tls.ensure, self.folder, address)
        except Exception:
            log.exception("phone access: the certificate couldn't be made")
            self.problem = "failed"
            return False
        await self._certificate_made(certs)
        if self.listener_app is None:
            log.error("phone access: no app to serve")
            self.problem = "failed"
            return False
        if not await asyncio.to_thread(self.network.port_free, address, port):
            self.problem = "port_busy"
            return False
        try:
            server = self.server_factory(listener_config(self.listener_app, address, port, certs))
            await server.startup()
        except SystemExit:  # uvicorn exits on a bind error (with 3 since 0.31; older ones with 1)
            self.problem = "port_busy"
            return False
        except Exception:
            log.exception("phone access couldn't start listening")
            self.problem = "failed"
            return False
        self._server, self.bound, self.certificates, self.problem = server, (address, port), certs, None
        return True

    async def _certificate_made(self, certs: tls.Certificates) -> None:
        if not (certs.made_ca or certs.made_server):
            return
        self.record.certificate_changed_at = _iso(self.clock())
        made = "ca" if certs.made_ca else "server"
        short = " ".join(certs.fingerprint.split()[:4])
        await self._log(
            "phone.certificate",
            f"New certificate for phone access ({short} …)",
            fingerprint=certs.fingerprint,
            made=made,
        )

    async def _unbind(self) -> None:
        """Stop listening: streams end, uploads still arriving are stopped, other requests that run
        finish, and admitted ones that don't run yet are refused."""
        server, self._server, self.bound = self._server, None, None
        if server is None:
            return
        for live in list(self._live):
            live.revoke("stopped")
        # shielded: a caller that is cancelled meanwhile (the watcher) never leaves the socket open
        await asyncio.shield(self._close(server))

    async def _close(self, server: ListenerServer) -> None:
        if self._live:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._idle.wait(), DRAIN_S)
        try:
            await server.shutdown()
        except Exception:
            log.exception("phone access: the listener didn't stop cleanly")

    async def _other_network(self) -> bool:
        """Whether this computer is behind another router than the saved one (only ever asked while it
        has the address). With none saved, the first one read is saved (trust on first read)."""
        saved = self.record.gateway
        current = await asyncio.to_thread(self.network.gateway)
        if not saved:
            if current is not None:
                self.record.gateway = current
                await self._save()
            return False
        return current is not None and current != saved

    async def _paused_now(self) -> None:
        if not self._paused:
            self._paused = True
            address = self.record.address
            why = (
                "on a different network"
                if self.problem == "other_network"
                else f"isn't on {address} any more"
            )
            await self._log("phone.paused", f"Phone access paused: this computer {why}", address=address)

    # ------------------------------------------------------------------------------ the watcher

    def _start_watcher(self) -> None:
        if self._watcher is None or self._watcher.done():
            # background work: never the person's change, even when a request of theirs started it
            self._watcher = asyncio.create_task(
                self._watch(), name="ordnung-phone-watcher", context=background_context()
            )

    async def _stop_watcher(self) -> None:
        task, self._watcher = self._watcher, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(WATCH_INTERVAL_S)
            try:
                await self.check()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("phone access: the network check failed")

    async def check(self) -> None:
        """One round of the watcher (also called by tests)."""
        async with self._guard():
            self._load()
            if not self.record.enabled or not self.available:
                return
            await self._check_network()
            now = self.clock()
            if now - self._last_daily >= DAILY_S:
                self._last_daily = now
                await self._daily(now)
            if self._seen_dirty and now - self._last_flush >= SEEN_WRITE_EVERY_S:
                self._seen_dirty = False
                self._last_flush = now
                await self._save()

    async def _check_network(self) -> None:
        address = self.record.address
        if self.listening and address is not None:
            here = await asyncio.to_thread(self.network.is_local, address)
            other = here and await self._other_network()
            if here and not other:
                return
            await self._unbind()
            if other:
                self.problem = "other_network"
            else:
                others = await asyncio.to_thread(self.network.candidates)
                self.problem = "address_gone" if others else "no_network"
            await self._paused_now()
            return
        if await self._bind():
            if self._paused:
                self._paused = False
                await self._log("phone.resumed", f"Phone access resumed at {self.url}", address=address)
        elif self.problem in ("address_gone", "no_network", "other_network"):
            await self._paused_now()

    async def _daily(self, now: float) -> None:
        if self.listening and self.record.address:
            certs = await asyncio.to_thread(tls.ensure, self.folder, self.record.address)
            if certs.made_server or certs.made_ca:
                await self._certificate_made(certs)
                self._reload_certificate(certs)
                self.certificates = certs
                await self._save()
        await self._forget_unused(now)

    async def _forget_unused(self, now: float) -> None:
        for device in list(self.record.devices):
            if _unused(device, now):
                await self.remove(device.id, by="unused")

    def _reload_certificate(self, certs: tls.Certificates) -> None:
        """New connections get the renewed certificate; open ones keep theirs."""
        context = getattr(getattr(self._server, "config", None), "ssl", None)
        if context is not None:
            context.load_cert_chain(str(certs.server_pem), str(certs.server_key))

    # ------------------------------------------------------------------------------ phones

    async def remove(self, device_id: str, *, by: RemovedBy = "computer") -> bool:
        """Remove a paired phone: signed out at once (saved before this returns)."""
        self._load()
        device = self.device(device_id)
        if device is None:
            return False
        self._drop_now(device, by)
        await self._save()
        await self._log_removed(device, by)
        return True

    def _drop_now(self, device: PhoneDeviceRecord, by: RemovedBy) -> None:
        self.record.devices = [d for d in self.record.devices if d.id != device.id]
        self._reindex()
        self.desk.used_by(device.id)
        for digest in (*device.retired, device.previous_sha256, device.token_sha256):
            if digest:
                self._signed_out.pop(digest, None)
                self._signed_out[digest] = by
        while len(self._signed_out) > SIGNED_OUT_KEPT:
            del self._signed_out[next(iter(self._signed_out))]
        for live in list(self._live):
            if live.device_id == device.id:
                live.revoke(by)

    async def _drop_all(self, by: RemovedBy) -> None:
        for device in list(self.record.devices):
            self._drop_now(device, by)
            await self._log_removed(device, by)
        await self._save()

    async def _log_removed(self, device: PhoneDeviceRecord, by: RemovedBy) -> None:
        await self._log("phone.removed", f"Removed {device.name}{_REMOVED_WHY[by]}", device=device.id, by=by)

    def _notify(self, code: NoticeCode, addresses: list[str], name: str | None = None) -> None:
        unique = list(dict.fromkeys(a for a in addresses if a))
        self.notice = Notice(code, notice_detail(code, unique, name), self.clock(), unique)

    async def authenticate(self, token: str | None, client: str = "") -> Auth:
        """Whose sign-in ``token`` is (one hash and a lookup; no database read). ``client``: the address
        it came from (named in the notice when an old sign-in comes back)."""
        if not token:
            return Auth()
        self._load()
        found = self._index.get(token_hash(token))
        if found is None:
            return Auth(unknown=True, removed=self.why_signed_out(token))
        device_id, which = found
        device = self.device(device_id)
        if device is None:
            return Auth(unknown=True)
        now = self.clock()
        if _unused(device, now):  # the watcher may not have run yet (a restart, phone access just on)
            await self.remove(device.id, by="unused")
            return Auth(unknown=True, removed="unused")
        if which == "current":
            if device.confirmed_at is None:
                device.confirmed_at = _iso(now)
                await self._save()
            return Auth(device)
        confirmed = _seconds(device.confirmed_at)
        if which == "previous" and (confirmed is None or now - confirmed <= PREVIOUS_GRACE_S):
            return Auth(device)
        # a sign-in the phone had before came back: it was copied, and both copies are signed out
        self._drop_now(device, "token_reuse")
        self._notify("token_reuse", [device.last_address or "", client], device.name)
        await self._save()
        await self._log_removed(device, "token_reuse")
        return Auth(unknown=True, removed="token_reuse")

    def why_signed_out(self, token: str | None) -> RemovedBy | None:
        """Why the phone whose sign-in ``token`` was is signed out, when this computer still knows."""
        return self._signed_out.get(token_hash(token)) if token else None

    async def renew_sign_in(self, device: PhoneDeviceRecord, token: str) -> str | None:
        """The sign-in the answer to a page load that came with ``token`` sets: ``token`` itself while it is
        current and under an hour old, else a new one (``None``: the phone's cookie is left as it is).

        ``token`` is looked up now, not as it was when the request was signed in: two page loads with the
        same cookie can cross the change. One that came with the previous sign-in gets a new one only when
        the phone never got the current one (unused and older than :data:`PREVIOUS_GRACE_S` seconds).
        While the current one is in use or that new, the other page load brings it: handing back the
        previous one (soon refused) or yet another one (the current one forgotten) could sign the phone
        out, whichever answer its browser applies last."""
        now = self.clock()
        digest = token_hash(token)
        if digest == device.token_sha256:
            since = _seconds(device.rotated_at) or _seconds(device.paired_at) or now
            if now - since < ROTATE_EVERY_S:
                return token
            if device.previous_sha256:
                device.retired = [*device.retired, device.previous_sha256][-RETIRED_KEPT:]
            device.previous_sha256 = device.token_sha256
        elif digest == device.previous_sha256:
            issued = _seconds(device.rotated_at) or 0.0
            if device.confirmed_at is not None or now - issued < PREVIOUS_GRACE_S:
                return None
        else:  # retired meanwhile
            return None
        renewed = secrets.token_urlsafe(32)
        device.token_sha256 = token_hash(renewed)
        device.rotated_at = _iso(now)
        device.confirmed_at = None
        self._reindex()
        await self._save()
        return renewed

    def seen(self, device: PhoneDeviceRecord, client: str) -> None:
        """A request from ``device`` (kept in memory; saved every few minutes)."""
        device.last_seen_at = _iso(self.clock())
        device.last_address = client
        self._seen_dirty = True

    def over_limit(self, device_id: str, kind: str) -> int:
        """``0``, or the seconds until ``device_id`` may do one more ``kind`` action this hour."""
        limit = self._device_limits.get(kind)
        return limit.take(device_id) if limit is not None else 0

    @property
    def upload_limit(self) -> int:
        """How many letters a phone may add an hour."""
        return self._device_limits["upload"].limit

    def more_letters(self, device_id: str, letters: int) -> int:
        """An upload from ``device_id`` adds ``letters`` letters, and the gate counted it as one. ``0``
        when they fit in the phone's hour (and count), else the seconds until they would (``-1``: more
        than an hour allows, never); a refused upload counts for nothing (the gate's one is given back)."""
        limit = self._device_limits["upload"]
        if letters <= 1:
            return 0
        wait = -1 if letters > limit.limit else limit.take(device_id, count=letters - 1)
        if wait:
            limit.give_back(device_id)
        return wait

    def admit(self) -> Live:
        """A request the gate starts to check: tracked until :meth:`release` (removal and stopping can
        end it, and a stop waits for it)."""
        live = Live()
        self._live.add(live)
        self._idle.clear()
        return live

    def release(self, live: Live) -> None:
        self._live.discard(live)
        if not self._live:
            self._idle.set()

    # ------------------------------------------------------------------------------ pairing

    async def start_pairing(self) -> tuple[str, str, str]:
        """``POST /api/phone/pairing``: ``(url, code, expires_at)`` of a new code (replacing an open one)."""
        self._require_available()
        self._load()
        if not self.listening or self.url is None:
            raise PhoneRefusal("not_listening", NOT_LISTENING_MESSAGE)
        if len(self.record.devices) >= MAX_PHONES:
            raise PhoneRefusal("too_many_phones", TOO_MANY_PHONES_MESSAGE)
        code, expires = self.desk.start(self.clock())
        return f"{self.url}/pair#{code}", code, _iso(expires)

    def cancel_pairing(self) -> None:
        """``DELETE /api/phone/pairing``: the dialog closed."""
        self.desk.cancel()

    def opened(self, client: str) -> None:
        """A phone that isn't paired opened the pairing page."""
        now = self.clock()
        self.desk.opened(client, now, _iso(now))

    async def pair(
        self, code: str, name: str, *, client: str, user_agent: str | None, current: str | None
    ) -> Paired:
        """``POST /api/phone/pair`` from a phone at ``client`` (``current``: the phone it is signed in as
        already, if any). Checking and spending the code happen before anything is awaited."""
        self._load()
        if not self.listening:
            raise PhoneRefusal("unavailable", PHONE_OFF_MESSAGE)
        now = self.clock()
        redeemed = self.desk.redeem(code, client, now)
        if redeemed.outcome == "reused":
            first = self.device(redeemed.device_id or "")
            if first is not None and current == first.id:  # the same phone sent it again
                return Paired(first, None, self.words(first.id))
            self.desk.forget_used(redeemed.digest)
            self._notify("code_reused", [(first.last_address or "") if first else "", client])
            if first is not None:
                self._drop_now(first, "code_reused")
                await self._save()
                await self._log_removed(first, "code_reused")
            raise PhoneRefusal("code_used", CODE_USED_MESSAGE)
        if redeemed.outcome == "locked":
            raise PhoneRefusal("too_many", TOO_MANY_TRIES_MESSAGE, retry_after=60)
        if redeemed.outcome == "stopped":
            self._notify("pairing_stopped", list(redeemed.addresses))
            await self._log(
                "phone.pairing_stopped",
                f"{PAIRING_TRIES_TOTAL} wrong pairing codes were typed on your network; the code was cancelled",
                addresses=list(redeemed.addresses),
            )
            raise PhoneRefusal("wrong_code", WRONG_CODE_MESSAGE)
        if redeemed.outcome == "wrong":
            raise PhoneRefusal("wrong_code", WRONG_CODE_MESSAGE)
        if len(self.record.devices) >= MAX_PHONES:
            raise PhoneRefusal("too_many_phones", TOO_MANY_PHONES_MESSAGE)
        token = secrets.token_urlsafe(32)
        stamp = _iso(now)
        device = PhoneDeviceRecord(
            id=new_id("phn"),
            name=unique_name(clean_name(name), {d.name for d in self.record.devices}),
            platform=platform_label(user_agent),
            token_sha256=token_hash(token),
            rotated_at=stamp,
            paired_at=stamp,
            last_seen_at=stamp,
            last_address=client,
        )
        self.desk.spend(device.id)
        self.record.devices.append(device)
        self._reindex()
        words = self.words(device.id)
        await self._save()
        await self._log(
            "phone.paired",
            f"Paired {device.name} ({device.platform}) from {client}",
            device=device.id,
            address=client,
        )
        return Paired(device, token, words)


def _choice(candidate: Candidate) -> dict[str, Any]:
    return {
        "address": candidate.address,
        "interface": candidate.interface,
        "subnet": candidate.subnet,
        "recommended": candidate.recommended,
    }
