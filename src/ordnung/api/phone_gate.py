"""The phone listener's gate: every request a phone sends passes it before any route runs (policy:
:mod:`ordnung.phone`).

:class:`PhoneListener` is the only app the phone listener serves. It tags each request's ASGI scope as
the phone listener's (``security.LISTENER_KEY``, a key no client can set), and
:class:`~ordnung.api.security.SecurityMiddleware` hands tagged requests to :class:`PhoneGate` instead
of the computer's own checks. A request that isn't tagged never reaches this gate, so a request on the
network that somehow reached the computer's checks would fail their localhost ``Host`` check.

In order, the gate:

1. answers only on the phone listener it was started as (``https``, the bound address and port), 421
   otherwise;
2. answers only the home network: a client in the bound address's subnet, 403 ``not_home_network``
   otherwise;
3. wants ``Host`` to be exactly ``<address>:<port>`` (no names: DNS rebinding fails here), 400
   ``wrong_host``;
4. refuses a path with a ``.`` or ``..`` segment, ``//`` or ``\\`` (400 ``bad_path``), and any request
   body sent without a length (``Transfer-Encoding``, 411 ``length_required``);
5. refuses what another site sent: ``Sec-Fetch-Site`` other than ``same-origin``/``none`` (and only
   ``same-origin`` for a change), an ``Origin`` other than ``https://<address>:<port>`` — required on
   every change — or a change without ``X-Ordnung-Client`` (403 ``cross_site``); no cross-site preflight
   is ever approved;
6. looks up the phone's sign-in cookie (:func:`ordnung.phone.cookie_name`; the session token, a bearer
   header or ``?token=`` mean nothing here). Before a phone is paired only the pairing page (``/pair``),
   the built app's own files and ``POST /api/phone/pair`` pass: a GET with a body is refused (400
   ``unexpected_body``), the pairing request must state a length of at most
   :data:`~ordnung.phone.pairing.PAIR_MAX_BYTES` (411/413) and is limited per address and in all (429).
   Anything else gets 401 ``phone_not_paired`` (pages: a redirect to ``/pair``); a cookie this computer
   doesn't know (any more) is also told to clear the browser's cache and storage (not its cookies:
   another Ordnung on the same address keeps its own);
7. serves ``/ordnung-certificate.crt`` (the authority, for a phone that chooses to trust it) to a paired
   phone;
8. lets ``/api`` through only for the phone's operations (:mod:`ordnung.phone.scope`, before routing;
   403 ``computer_only`` otherwise, also ``/api/health?probe``), refuses a body larger than
   ``MAX_REQUEST_BYTES`` (413) and applies the phone's hourly limits (429 with ``Retry-After``);
9. runs the request as the phone's: the routes see :data:`~ordnung.api.security.DEVICE_KEY`, the privacy
   log attributes what it writes (:mod:`ordnung.phone.actor`), and each change the phone made is logged
   as ``phone.changed``. Request bodies are counted as they arrive and stopped at the allowed size (413).
   A page load refreshes the sign-in cookie (and changes the sign-in at most once an hour).

Every answer on the phone listener carries ``Cross-Origin-Resource-Policy: same-origin`` and a
``Permissions-Policy``; API answers that set no caching get ``no-store``. Refusals are logged to the
``ordnung.phone`` logger at most once a minute per reason, as a count — never a code, token, cookie or
fragment.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from starlette.datastructures import Headers, QueryParams
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ordnung.api.security import (
    ALLOWED_FETCH_SITES,
    AUTH_STATE_KEY,
    CLIENT_HEADER,
    DEVICE_KEY,
    LISTENER_KEY,
    MAX_REQUEST_BYTES,
    PHONE_LISTENER,
    SAFE_METHODS,
    html_page,
)
from ordnung.phone import COOKIE_MAX_AGE_S, ERROR_STATUS, PhoneErrorCode, cookie_name, net, tls
from ordnung.phone import scope as phone_scope
from ordnung.phone.access import LIMIT_MESSAGES, TOO_MANY_PAIRING_MESSAGE, PhoneAccess
from ordnung.phone.actor import DeviceRef, acting
from ordnung.phone.pairing import PAIR_MAX_BYTES

log = logging.getLogger("ordnung.phone")

PAIR_PATH = "/pair"
PAIR_API = ("POST", "/api/phone/pair")
CERTIFICATE_PATH = "/ordnung-certificate.crt"
CERTIFICATE_NAME = "Ordnung phone access.crt"
PERMISSIONS_POLICY = "geolocation=(), microphone=(), payment=(), usb=()"
REFUSAL_LOG_EVERY_S = 60.0

MESSAGES: dict[PhoneErrorCode, str] = {
    "misdirected": "Misdirected request.",
    "not_home_network": "Phone access only answers devices on your home network.",
    "wrong_host": "Open Ordnung on your phone with the address shown on your computer.",
    "bad_path": "That address isn't one Ordnung knows.",
    "unexpected_body": "This request can't carry a body.",
    "length_required": "This request must say how long it is.",
    "too_large": "This is more than Ordnung accepts at once.",
    "cross_site": "Requests from other websites are not allowed.",
    "phone_not_paired": (
        "This phone isn't paired with Ordnung any more. Pair it again from Settings → Phone on your computer."
    ),
    "computer_only": "This works on your computer only.",
}
MISSING_CLIENT = "This request must come from the Ordnung app (missing X-Ordnung-Client)."
PAIR_BODY_TOO_LARGE = "A pairing request is only a code and a name."
UPLOAD_TOO_LARGE = "Please add at most 200 MB at once."


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def bad_path(path: str) -> bool:
    """A path with a ``.`` or ``..`` segment, ``//`` or a backslash (never one Ordnung serves)."""
    if "//" in path or "\\" in path:
        return True
    return any(segment in (".", "..") for segment in path.split("/"))


def page_load(path: str, headers: Headers) -> bool:
    """A navigation that gets the app's page (not an API call, a script or a picture)."""
    if _is_api(path):
        return False
    dest = headers.get("sec-fetch-dest")
    if dest is not None:
        return dest.lower() == "document"
    return not path.startswith("/assets/") and "." not in path.rsplit("/", 1)[-1]


def _content_length(headers: Headers) -> int | None:
    value = headers.get("content-length")
    if value is None:
        return None
    return int(value) if value.strip().isdigit() else -1


def sign_in_cookie(port: int, token: str) -> str:
    """The ``Set-Cookie`` value of a phone's sign-in (``__Host-``: Secure, ``Path=/``, no Domain)."""
    return (
        f"{cookie_name(port)}={token}; HttpOnly; Max-Age={COOKIE_MAX_AGE_S}; Path=/; SameSite=strict; Secure"
    )


class PhoneListener:
    """The phone listener's app: every request is tagged as the phone listener's, then ``app`` runs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, LISTENER_KEY: PHONE_LISTENER}
        await self.app(scope, receive, send)


class _RefusalLog:
    """Refusals as a count per reason and address, at most once a minute per reason."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, str], int] = {}
        self._last: dict[str, float] = {}

    def note(self, reason: str, client: str) -> None:
        key = (reason, client)
        self._counts[key] = self._counts.get(key, 0) + 1
        now = time.monotonic()
        if now - self._last.get(reason, -REFUSAL_LOG_EVERY_S) < REFUSAL_LOG_EVERY_S:
            return
        self._last[reason] = now
        for (kind, address), count in list(self._counts.items()):
            if kind == reason:
                del self._counts[(kind, address)]
                log.warning("%d requests refused (%s) from %s in the last minute", count, reason, address)


def _phone_headers(send: Send, *, api: bool) -> Send:
    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = list(message.get("headers", []))
            present = {name.lower() for name, _ in headers}
            extra = [
                (b"cross-origin-resource-policy", b"same-origin"),
                (b"permissions-policy", PERMISSIONS_POLICY.encode()),
            ]
            if api:
                extra.append((b"cache-control", b"no-store"))
            headers.extend(header for header in extra if header[0] not in present)
            message = {**message, "headers": headers}
        await send(message)

    return wrapped


@dataclass
class _Response:
    """What the app answered (as far as the gate needs to know)."""

    started: bool = False
    finished: bool = False
    status: int = 0
    held: bool = False


class _BodyLimit:
    """Counts a request's body as it arrives; past ``limit`` bytes the app is told the client left."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.read = 0
        self.exceeded = False

    def count(self, message: Message) -> Message:
        if message["type"] == "http.request":
            self.read += len(message.get("body", b""))
            if self.read > self.limit:
                self.exceeded = True
                return {"type": "http.disconnect"}
        return message


class PhoneGate:
    """The checks above, for one :class:`~ordnung.phone.access.PhoneAccess`."""

    def __init__(self, access: PhoneAccess) -> None:
        self.access = access
        self.refusals = _RefusalLog()

    # ------------------------------------------------------------------------------ answers

    async def _refuse(
        self,
        code: PhoneErrorCode,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        client = (scope.get("client") or ("?", 0))[0]
        self.refusals.note(code, str(client))
        message = detail or MESSAGES.get(code, "Not allowed.")
        status = ERROR_STATUS[code]
        response: Response
        if _is_api(scope["path"]) or scope["method"] not in SAFE_METHODS:
            response = JSONResponse({"detail": message, "code": code}, status_code=status, headers=headers)
        else:
            response = html_page("Not allowed", [message], status_code=status)
            response.headers.update(headers or {})
        await response(scope, receive, send)

    async def _not_paired(
        self, scope: Scope, receive: Receive, send: Send, *, unknown: bool, port: int
    ) -> None:
        path = scope["path"]
        response: Response
        if not _is_api(path) and scope["method"] in SAFE_METHODS:
            response = RedirectResponse(f"{PAIR_PATH}?removed=1" if unknown else PAIR_PATH, status_code=303)
        else:
            self.refusals.note("phone_not_paired", str((scope.get("client") or ("?", 0))[0]))
            response = JSONResponse(
                {"detail": MESSAGES["phone_not_paired"], "code": "phone_not_paired"}, status_code=401
            )
        if unknown:  # a removed phone empties what it kept; "cookies" would sign out another Ordnung too
            response.headers["Clear-Site-Data"] = '"cache", "storage"'
            response.delete_cookie(cookie_name(port), path="/", secure=True, httponly=True, samesite="strict")
        await response(scope, receive, send)

    # ------------------------------------------------------------------------------ the gate

    async def __call__(self, scope: Scope, receive: Receive, send: Send, app: ASGIApp) -> None:
        access = self.access
        path: str = scope["path"]
        method: str = scope["method"].upper()
        api = _is_api(path)
        send = _phone_headers(send, api=api)
        headers = Headers(scope=scope)
        client = str((scope.get("client") or ("", 0))[0])
        bound = access.bound
        server = tuple(scope.get("server") or ())[:2]
        if bound is None or scope.get("scheme") != "https" or server != bound:
            await self._refuse("misdirected", scope, receive, send)
            return
        address, port = bound
        origin_wanted = f"https://{address}:{port}"
        if not net.client_allowed(client, address, access.record.subnet):
            await self._refuse("not_home_network", scope, receive, send)
            return
        if headers.get("host", "").strip().lower() != f"{address}:{port}":
            await self._refuse("wrong_host", scope, receive, send)
            return
        if bad_path(path):
            await self._refuse("bad_path", scope, receive, send)
            return
        if "transfer-encoding" in headers:
            await self._refuse("length_required", scope, receive, send)
            return
        safe = method in SAFE_METHODS
        site = headers.get("sec-fetch-site")
        if site is not None and (
            site.lower() not in ALLOWED_FETCH_SITES or (not safe and site.lower() != "same-origin")
        ):
            await self._refuse("cross_site", scope, receive, send)
            return
        origin = headers.get("origin")
        if (origin is None and not safe) or (origin is not None and origin.strip().lower() != origin_wanted):
            await self._refuse("cross_site", scope, receive, send)
            return
        if not safe and not headers.get(CLIENT_HEADER):
            await self._refuse("cross_site", scope, receive, send, detail=MISSING_CLIENT)
            return
        length = _content_length(headers)
        if length == -1:
            await self._refuse("length_required", scope, receive, send)
            return
        cookies = _cookies(headers)
        auth = await access.authenticate(cookies.get(cookie_name(port)), client)
        device = auth.device
        if device is None:
            await self._before_sign_in(scope, receive, send, app, headers, client, length, auth.unknown, port)
            return
        if path == CERTIFICATE_PATH and safe:
            await self._certificate(scope, receive, send)
            return
        operation: phone_scope.Operation | None = None
        params: dict[str, str] = {}
        if api:
            matched = phone_scope.match(method, path)
            if matched is None:
                await self._refuse("computer_only", scope, receive, send)
                return
            operation, params = matched
            if operation == ("GET", "/api/health") and "probe" in QueryParams(scope.get("query_string", b"")):
                await self._refuse("computer_only", scope, receive, send)
                return
        if length is not None and length > MAX_REQUEST_BYTES:
            await self._refuse("too_large", scope, receive, send, detail=UPLOAD_TOO_LARGE)
            return
        limited = phone_scope.LIMITED.get(operation) if operation else None
        if limited is not None:
            wait = access.over_limit(device.id, limited)
            if wait:
                await self._refuse(
                    "too_many",
                    scope,
                    receive,
                    send,
                    detail=LIMIT_MESSAGES[limited],
                    headers={"Retry-After": str(wait)},
                )
                return
        token = cookies.get(cookie_name(port))
        refresh: str | None = None
        if safe and page_load(path, headers):
            refresh = await access.renew_sign_in(device, auth.via or "current") or token
        access.seen(device, client)
        if operation in phone_scope.STREAMS:
            kind = phone_scope.STREAMS[operation]
        else:
            kind = "upload" if operation in phone_scope.UPLOADS else "other"
        ref = scope[DEVICE_KEY] = DeviceRef(device.id, device.name)
        sign_in = (port, refresh) if refresh else None
        answer = await self._run(
            scope, receive, send, app, device=ref, limit=MAX_REQUEST_BYTES, kind=kind, cookie=sign_in
        )
        changed = operation is not None and not safe and operation not in phone_scope.NOT_CHANGES
        if changed and operation is not None and answer.status < 400:
            await self._changed(ref, operation, params)

    async def _before_sign_in(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        app: ASGIApp,
        headers: Headers,
        client: str,
        length: int | None,
        unknown: bool,
        port: int,
    ) -> None:
        access = self.access
        path, method = scope["path"], scope["method"].upper()
        safe = method in SAFE_METHODS
        if safe and (length or 0) > 0:
            await self._refuse("unexpected_body", scope, receive, send)
            return
        if (method, path) == PAIR_API:
            if length is None:
                await self._refuse("length_required", scope, receive, send)
                return
            if length > PAIR_MAX_BYTES:
                await self._refuse("too_large", scope, receive, send, detail=PAIR_BODY_TOO_LARGE)
                return
            wait = access.pair_limit_client.take(client) or access.pair_limit_all.take("all")
            if wait:
                await self._refuse(
                    "too_many",
                    scope,
                    receive,
                    send,
                    detail=TOO_MANY_PAIRING_MESSAGE,
                    headers={"Retry-After": str(wait)},
                )
                return
            await self._run(scope, receive, send, app, device=None, limit=PAIR_MAX_BYTES, kind="other")
            return
        if safe and path == PAIR_PATH:
            if headers.get("sec-fetch-dest", "").lower() == "document":
                access.opened(client)
            await self._run(scope, receive, send, app, device=None, limit=0, kind="other")
            return
        if safe and path in access.public_files:
            await self._run(scope, receive, send, app, device=None, limit=0, kind="other")
            return
        await self._not_paired(scope, receive, send, unknown=unknown, port=port)

    async def _certificate(self, scope: Scope, receive: Receive, send: Send) -> None:
        der = await asyncio.to_thread(tls.authority_der, self.access.folder)
        if der is None:
            await JSONResponse({"detail": "There is no certificate yet."}, status_code=404)(
                scope, receive, send
            )
            return
        response = Response(
            der,
            media_type="application/x-x509-ca-cert",
            headers={
                "Content-Disposition": f'attachment; filename="{CERTIFICATE_NAME}"',
                "Cache-Control": "no-store",
            },
        )
        await response(scope, receive, send)

    async def _changed(
        self, device: DeviceRef, operation: phone_scope.Operation, params: dict[str, str]
    ) -> None:
        label = phone_scope.CHANGE_LABELS.get(operation, "Changed something")
        data: dict[str, Any] = {"device": device.id, "operation": f"{operation[0]} {operation[1]}"}
        if params:
            data["refs"] = params
        try:
            await asyncio.to_thread(
                self.access.ctx.store.log_activity, "phone.changed", f"{label} on {device.name}", data=data
            )
        except Exception:  # the change is made; a log entry that can't be written must not undo the answer
            log.exception("phone access: a change couldn't be logged")

    # ------------------------------------------------------------------------------ running the app

    async def _run(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        app: ASGIApp,
        *,
        device: DeviceRef | None,
        limit: int,
        kind: Any,
        cookie: tuple[int, str] | None = None,
    ) -> _Response:
        access = self.access
        scope.setdefault("state", {})[AUTH_STATE_KEY] = device is not None
        answer = _Response()
        body = _BodyLimit(limit)
        with access.tracked(device.id if device else None, kind) as live:
            guard_receive = kind != "other"

            async def receive_counted() -> Message:
                if not guard_receive:
                    return body.count(await receive())
                if live.revoked.is_set():
                    return {"type": "http.disconnect"}
                arrived = asyncio.ensure_future(receive())
                stopped = asyncio.ensure_future(live.revoked.wait())
                done, pending = await asyncio.wait({arrived, stopped}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                if arrived in done:
                    return body.count(arrived.result())
                return {"type": "http.disconnect"}

            def cut() -> bool:
                return body.exceeded or (live.revoked.is_set() and kind != "other")

            async def send_tracked(message: Message) -> None:
                if message["type"] == "http.response.start":
                    if cut():
                        answer.held = True
                        return
                    answer.started, answer.status = True, int(message["status"])
                    if cookie is not None and _is_html(message):
                        message = {
                            **message,
                            "headers": [
                                *message.get("headers", []),
                                (b"set-cookie", sign_in_cookie(*cookie).encode("latin-1")),
                            ],
                        }
                elif message["type"] == "http.response.body":
                    if answer.held or not answer.started:
                        return
                    if not message.get("more_body", False):
                        answer.finished = True
                await send(message)

            try:
                with live.scope, _acting(device):
                    await app(scope, receive_counted, send_tracked)
            except Exception:
                if not cut():
                    raise
        if answer.started and not answer.finished:
            # a stream the phone's removal ended: close it cleanly (the client sees the end, not an error)
            with contextlib.suppress(Exception):
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            answer.finished = True
        elif not answer.started:
            if body.exceeded:
                answer.status = 413
                too_large = PAIR_BODY_TOO_LARGE if limit == PAIR_MAX_BYTES else UPLOAD_TOO_LARGE
                await self._refuse("too_large", scope, receive, send, detail=too_large)
            elif live.revoked.is_set():
                answer.status = 401
                response = JSONResponse(
                    {"detail": MESSAGES["phone_not_paired"], "code": "phone_not_paired"}, status_code=401
                )
                with contextlib.suppress(Exception):
                    await response(scope, receive, send)
        return answer


def _is_html(message: Message) -> bool:
    for name, value in message.get("headers", []):
        if name.lower() == b"content-type":
            return bytes(value).lower().startswith(b"text/html")
    return False


def _cookies(headers: Headers) -> dict[str, str]:
    found: dict[str, str] = {}
    for header in headers.getlist("cookie"):
        for part in header.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep and name and name not in found:
                found[name] = value.strip().strip('"')
    return found


@contextlib.contextmanager
def _acting(device: DeviceRef | None) -> Iterator[None]:
    if device is None:
        yield
        return
    with acting(device):
        yield
