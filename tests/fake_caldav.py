"""A tiny CalDAV server for the calendar-sync tests: one account's calendars behind Basic auth.

It answers what calendar sync asks — ``PROPFIND`` for discovery (``/.well-known/caldav`` → the
principal → the calendar home, depth 1 listing its calendars) and for the calendar itself (depth
0), ``PUT`` and ``DELETE`` of ``.ics`` resources in the calendar Ordnung writes into, a
``calendar-multiget`` ``REPORT`` of named resources (200 with an ETag, or 404, per name; switched off
with :attr:`FakeCalDav.multiget`), and ``GET`` for the tests — and checks what a real server checks: the password, that a resource holds exactly one
event and no ``METHOD`` (RFC 4791 §4.1), and that no two resources share a UID
(``no-uid-conflict`` — answered as Nextcloud does with :attr:`FakeCalDav.uid_clash`). Tests switch on
failures (a refused event, the server down, a redirect, odd answers, a web root that redirects to a
login page). :meth:`FakeCalDav.transport` serves it in-process to ``httpx``; :func:`serve_on_loopback`
serves the same object over a real socket.
"""

from __future__ import annotations

import base64
import hashlib
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from icalendar import Calendar

from ordnung.calendar.secrets import SecretsUnavailable

CALENDAR_PATH = "/dav/calendars/sam/ordnung/"
HOME_PATH = "/dav/calendars/sam/"
PRINCIPAL_PATH = "/principals/sam/"
USERNAME = "sam@example.org"
PASSWORD = "abcd-efgh-ijkl-mnop"
#: the account's other calendars: path → (name, components)
OTHER_CALENDARS: dict[str, tuple[str, tuple[str, ...] | None]] = {
    HOME_PATH + "personal/": ("Personal", ("VEVENT", "VTODO")),
    HOME_PATH + "tasks/": ("Tasks", ("VTODO",)),
}
XML = {"Content-Type": "application/xml; charset=utf-8"}


def response(href: str, props: str) -> str:
    return (
        f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>{props}</d:prop>"
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    )


def calendar_props(
    *, calendar: bool = True, components: tuple[str, ...] | None = ("VEVENT",), name: str = "Ordnung"
) -> str:
    kind = "<d:collection/><c:calendar/>" if calendar else "<d:collection/>"
    comps = (
        "<c:supported-calendar-component-set>"
        + "".join(f'<c:comp name="{comp}"/>' for comp in components)
        + "</c:supported-calendar-component-set>"
        if components is not None
        else ""
    )
    return f"<d:resourcetype>{kind}</d:resourcetype><d:displayname>{name}</d:displayname>{comps}"


def multistatus(*responses: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        + "".join(responses)
        + "</d:multistatus>"
    ).encode()


@dataclass
class FakeCalDav:
    """The server's state and switches (see the module doc)."""

    path: str = CALENDAR_PATH
    username: str = USERNAME
    password: str = PASSWORD
    calendar: bool = True
    components: tuple[str, ...] | None = ("VEVENT",)
    name: str = "Ordnung"
    #: the account's other calendars (discovery lists them next to the one above)
    others: dict[str, tuple[str, tuple[str, ...] | None]] = field(
        default_factory=lambda: dict(OTHER_CALENDARS)
    )
    #: the calendar home as the principal names it: a path, or an absolute URL on another host
    home_href: str = HOME_PATH
    resources: dict[str, bytes] = field(default_factory=dict)
    requests: list[tuple[str, str]] = field(default_factory=list)
    #: path → status for a PUT or DELETE of that resource
    refuse: dict[str, int] = field(default_factory=dict)
    #: every request gets this answer instead (status, headers, body)
    override: tuple[int, dict[str, str], bytes] | None = None
    #: path → the answer every request to that path gets (a web app's root, its login page)
    answers: dict[str, tuple[int, dict[str, str], bytes]] = field(default_factory=dict)
    #: how a PUT whose UID is already in another resource is refused (status, body)
    uid_clash: tuple[int, bytes] = (409, b"no-uid-conflict")
    #: raise this from the transport (the network failing)
    raises: Exception | None = None
    #: the server answers a ``calendar-multiget`` (else 501, as a server without it might)
    multiget: bool = True
    lock: threading.Lock = field(default_factory=threading.Lock)

    # -- what the tests read ----------------------------------------------------------------------

    def events(self) -> dict[str, Calendar]:
        """Resource name → the calendar object stored there."""
        return {path.rsplit("/", 1)[1]: Calendar.from_ical(body) for path, body in self.resources.items()}

    def uids(self) -> set[str]:
        return {str(event.get("uid")) for cal in self.events().values() for event in cal.events}

    def methods(self) -> list[str]:
        return [method for method, _ in self.requests]

    # -- serving ------------------------------------------------------------------------------------

    def _authorised(self, header: str | None) -> bool:
        expected = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
        return header == f"Basic {expected}"

    def handle(
        self, method: str, path: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, dict[str, str], bytes]:
        with self.lock:
            self.requests.append((method, path))
            if self.override is not None:
                return self.override
            if path in self.answers:
                return self.answers[path]
            if not self._authorised(headers.get("authorization")):
                return 401, {"WWW-Authenticate": 'Basic realm="fake"'}, b"Unauthorized"
            if method == "PROPFIND":
                return self._propfind(path, headers.get("depth", ""), body)
            if method == "REPORT":
                return self._multiget(path, body)
            if not path.startswith(self.path) or not path.endswith(".ics") or "/" in path[len(self.path) :]:
                return 403, {}, b"not in the calendar"
            if path in self.refuse and method in ("PUT", "DELETE"):
                return self.refuse[path], {}, b""
            if method == "GET":
                return (
                    (200, {"Content-Type": "text/calendar"}, self.resources[path])
                    if path in self.resources
                    else (404, {}, b"")
                )
            if method == "DELETE":
                if path not in self.resources:
                    return 404, {}, b""
                del self.resources[path]
                return 204, {}, b""
            if method == "PUT":
                cal = Calendar.from_ical(body)
                events = cal.events
                if (
                    len(events) != 1
                    or "METHOD" in cal
                    or not headers.get("content-type", "").startswith("text/calendar")
                ):
                    return 415, {}, b"one event, no METHOD"
                uid = str(events[0].get("uid"))
                for other, stored in self.resources.items():
                    if other != path and any(
                        str(e.get("uid")) == uid for e in Calendar.from_ical(stored).events
                    ):
                        return self.uid_clash[0], {}, self.uid_clash[1]
                new = path not in self.resources
                self.resources[path] = body
                return (201 if new else 204), {}, b""
            return 405, {}, b""

    def _calendars(self) -> dict[str, str]:
        """Path → the properties of every calendar of the account (Ordnung's first)."""
        mine = calendar_props(calendar=self.calendar, components=self.components, name=self.name)
        others = {
            path: calendar_props(components=comps, name=name) for path, (name, comps) in self.others.items()
        }
        return {self.path: mine, **others}

    def _propfind(self, path: str, depth: str, body: bytes) -> tuple[int, dict[str, str], bytes]:
        if path == "/.well-known/caldav":
            return 301, {"Location": "/dav/"}, b""
        calendars = self._calendars()
        known = {"/", "/dav/", HOME_PATH, PRINCIPAL_PATH, *calendars}
        if path not in known:
            return 404, {}, b""
        if b"current-user-principal" in body:
            principal = (
                f"<d:current-user-principal><d:href>{PRINCIPAL_PATH}</d:href></d:current-user-principal>"
            )
            return 207, XML, multistatus(response(path, principal))
        if b"calendar-home-set" in body:
            if path != PRINCIPAL_PATH:
                return (
                    207,
                    XML,
                    multistatus(response(path, "<d:resourcetype><d:collection/></d:resourcetype>")),
                )
            home = f"<c:calendar-home-set><d:href>{self.home_href}</d:href></c:calendar-home-set>"
            return 207, XML, multistatus(response(path, home))
        collection = "<d:resourcetype><d:collection/></d:resourcetype>"
        here = response(path, calendars.get(path, collection))
        if depth == "0":
            return 207, XML, multistatus(here)
        if depth != "1":
            return 400, {}, b"depth 0 or 1"
        inside = [
            response(p, props)
            for p, props in calendars.items()
            if p != path and p.startswith(path) and p.count("/") == path.count("/") + 1
        ]
        return 207, XML, multistatus(here, *inside)

    def _multiget(self, path: str, body: bytes) -> tuple[int, dict[str, str], bytes]:
        if not self.multiget:
            return 501, {}, b"not implemented"
        if path != self.path or b"calendar-multiget" not in body:
            return 403, {}, b"no such report here"
        answers = []
        for href in re.findall(rb"<d:href>([^<]*)</d:href>", body):
            name = href.decode()
            if name in self.resources:
                etag = hashlib.sha256(self.resources[name]).hexdigest()[:16]
                answers.append(response(name, f'<d:getetag>"{etag}"</d:getetag>'))
            else:
                answers.append(
                    f"<d:response><d:href>{name}</d:href><d:status>HTTP/1.1 404 Not Found</d:status></d:response>"
                )
        return 207, XML, multistatus(*answers)

    def _httpx(self, request: httpx.Request) -> httpx.Response:
        if self.raises is not None:
            raise self.raises
        headers = {key.lower(): value for key, value in request.headers.items()}
        status, extra, body = self.handle(request.method, request.url.path, headers, request.read())
        return httpx.Response(status, headers=extra, content=body)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._httpx)

    def url(self, base: str = "https://cal.example.org") -> str:
        return base + self.path


def _handler(fake: FakeCalDav) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            headers = {key.lower(): value for key, value in self.headers.items()}
            status, extra, answer = fake.handle(self.command, self.path, headers, body)
            self.send_response(status)
            for key, value in extra.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(answer)))
            self.end_headers()
            self.wfile.write(answer)

        do_GET = do_PUT = do_DELETE = do_PROPFIND = do_REPORT = _serve

        def log_message(self, *_args: object) -> None:
            pass

    return Handler


@contextmanager
def serve_on_loopback(fake: FakeCalDav) -> Iterator[str]:
    """Serve ``fake`` on ``http://127.0.0.1:<free port>``; yields the calendar's address."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}{fake.path}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class MemorySecrets:
    """A :class:`~ordnung.calendar.secrets.SecretStore` in memory (``unavailable``: none usable)."""

    def __init__(self, unavailable: SecretsUnavailable | None = None) -> None:
        self.saved: dict[str, str] = {}
        self.unavailable = unavailable

    def problem(self) -> SecretsUnavailable | None:
        return self.unavailable

    def _check(self) -> None:
        if self.unavailable is not None:
            raise self.unavailable

    def get(self, account: str) -> str | None:
        self._check()
        return self.saved.get(account)

    def set(self, account: str, password: str) -> None:
        self._check()
        self.saved[account] = password

    def delete(self, account: str) -> None:
        self._check()
        self.saved.pop(account, None)
