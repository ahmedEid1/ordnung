"""Localhost defences for the HTTP API (SPEC §13, §21).

Ordnung listens on 127.0.0.1 only, but any web page the person visits can try to talk to it. The
:class:`SecurityMiddleware` (plain ASGI, so streamed responses pass through untouched) therefore:

* accepts only ``Host: localhost | 127.0.0.1 | [::1]`` (with an optional port) — DNS rebinding;
* rejects requests whose ``Sec-Fetch-Site`` is present and not ``same-origin``/``none``, and
  requests whose ``Origin`` is present and differs from the ``Host`` — cross-site requests;
* requires the header ``X-Ordnung-Client`` on every non-GET request — a simple form post from
  another site cannot set it;
* checks the session token (Jupyter style): ``GET /?token=…`` stores it in an HttpOnly,
  SameSite=Strict cookie ``ordnung_token_<port>`` and redirects to ``/``; every ``/api`` request needs
  that cookie or ``Authorization: Bearer <token>``. The cookie is named per port because browsers send
  a cookie to every port of a host: the demo and the real app would otherwise sign each other out (the
  cookie still reaches other servers on localhost; only a token kept out of cookies would not).
  ``ordnung serve`` opens the browser with a one-time link instead, ``GET /?open=<code>``
  (:meth:`ordnung.server.ServerInfo.open_url`), so the token is never on a command line: each code is
  taken once, within a minute (:class:`OneTimeCodes`), and signs the browser in with a session of its
  own, never the token. The code is on the browser's command line until the browser uses it, where
  another account can read it: its second use ends the session its first use made, and says so. Both
  are taken only on a top-level page load. A link opened from another site is a cross-site page load:
  one carrying a *valid* token or code is accepted from anywhere and answered with a same-origin forward
  instead of a redirect (knowing the token is already full access). A browser that is signed in already
  and loads a spent link opens the page. ``/api/health`` answers without it (with minimal information).
  Neither is ever accepted in an API URL, where it would end up in other programs.
  ``token=None`` turns the token check off (tests, ``--no-token``);
* refuses an ``/api`` request whose body has no stated length (``Transfer-Encoding``, 411), so the
  200 MB cap holds before anything is read.

It also adds ``X-Content-Type-Options: nosniff`` and ``Referrer-Policy: no-referrer`` to every
response. HTML pages carry the strict Content Security Policy built by :func:`content_security_policy`.

Phone access (:mod:`ordnung.phone`) adds a second listener on the home network. Its requests carry
:data:`LISTENER_KEY` in their ASGI scope — set by that listener's own app, never by a client — and go to
the phone listener's gate (``phone=``, :mod:`ordnung.api.phone_gate`) instead of the checks above; without
a gate they get 421. Nothing above changes for the computer: a request without the key that came from
the network fails the ``Host`` check.
"""

from __future__ import annotations

import base64
import hashlib
import html
import logging
import re
import secrets
import time
from collections.abc import Callable, Iterable, Sequence
from typing import Literal, NamedTuple, Protocol
from urllib.parse import urlencode, urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ordnung.server import OPEN_LINK_S, OPEN_QUERY, TOKEN_BYTES, open_code_mac

logger = logging.getLogger(__name__)

TOKEN_COOKIE = "ordnung_token"
TOKEN_QUERY = "token"
#: The query parameters that sign a page load in: the session token, or a one-time code.
SIGN_IN_QUERIES = (TOKEN_QUERY, OPEN_QUERY)
CLIENT_HEADER = "x-ordnung-client"
AUTH_STATE_KEY = "ordnung_authenticated"
#: Set in the ASGI scope by the phone listener's app (``phone_gate.PhoneListener``); no client can set it.
LISTENER_KEY = "ordnung.listener"
PHONE_LISTENER = "phone"
#: The paired phone a phone request comes from (``ordnung.phone.actor.DeviceRef``), set by its gate.
DEVICE_KEY = "ordnung.device"
COOKIE_MAX_AGE_S = 30 * 24 * 3600
#: Largest request body: 200 MB of letters at once plus the form around them. A larger one is refused
#: by its ``Content-Length``, before the form parser writes it to the temp folder (and an API request
#: without one, 411).
MAX_REQUEST_BYTES = 210 * 1024 * 1024

ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})
ALLOWED_FETCH_SITES = frozenset({"same-origin", "none"})
SAFE_METHODS = frozenset({"GET", "HEAD"})
API_PREFIX = "/api"
PUBLIC_API_PATHS = frozenset({"/api/health"})

_ALWAYS_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
)
_INLINE_SCRIPT_RE = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.IGNORECASE | re.DOTALL)
_SRC_ATTR_RE = re.compile(r"\bsrc\s*=", re.IGNORECASE)
_PORT_RE = re.compile(r"^\d{1,5}$")
_OPEN_CODE_RE = re.compile(r"(\d{1,12})\.([A-Za-z0-9_-]{8,64})\.([0-9a-f]{64})", re.ASCII)


# --------------------------------------------------------------------------------------------------
# Content Security Policy and HTML pages
# --------------------------------------------------------------------------------------------------


def inline_script_hashes(index_html: str) -> list[str]:
    """``sha256-…`` sources for every inline ``<script>`` (no ``src``) of a built ``index.html``."""
    hashes = []
    for match in _INLINE_SCRIPT_RE.finditer(index_html):
        if _SRC_ATTR_RE.search(match["attrs"]):
            continue
        digest = hashlib.sha256(match["body"].encode("utf-8")).digest()
        hashes.append("sha256-" + base64.b64encode(digest).decode("ascii"))
    return hashes


def content_security_policy(script_hashes: Sequence[str] = ()) -> str:
    """The strict CSP for Ordnung's pages: same-origin everything, inline scripts only by hash."""
    scripts = " ".join(["'self'", *(f"'{value}'" for value in script_hashes)])
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src {scripts}",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "connect-src 'self'",
            "font-src 'self' data:",
            "frame-src 'self'",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "base-uri 'none'",
            "form-action 'none'",
        ]
    )


_PAGE_STYLE = (
    ":root{--canvas:#f7f5f0;--surface:#fff;--line:#e4dfd4;--ink:#1d1b16;--muted:#6b6558;--accent:#0f6e66;"
    "--soft:#e3f0ed;--code:#f1ede4}"
    "@media (prefers-color-scheme:dark){:root{--canvas:#12110e;--surface:#1b1a16;--line:#34312a;--ink:#f2efe7;"
    "--muted:#ada697;--accent:#3fb8ac;--soft:#173b37;--code:#26241f}}"
    "*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:1rem;"
    "font:15px/1.6 Inter,ui-sans-serif,system-ui,sans-serif;color:var(--ink);background:var(--canvas)}"
    "main{width:100%;max-width:28rem;background:var(--surface);border:1px solid var(--line);border-radius:18px;"
    "padding:2.5rem 2rem;text-align:center;box-shadow:0 1px 2px rgb(0 0 0/.04),0 8px 24px rgb(0 0 0/.05)}"
    ".mark{width:44px;height:44px;margin:0 auto 1.25rem;border-radius:12px;background:var(--accent);"
    "display:grid;place-items:center;color:var(--surface);font:600 22px/1 Georgia,serif}"
    "h1{margin:0;font:600 1.5rem/1.2 'Fraunces Variable',Fraunces,Georgia,serif}"
    "p{margin:.6rem 0 0;color:var(--muted);font-size:14px}"
    ".cmds{margin-top:1.25rem;display:flex;flex-wrap:wrap;gap:.5rem;justify-content:center}"
    "code{display:inline-block;background:var(--code);color:var(--ink);border-radius:8px;padding:.4rem .7rem;"
    "font:13px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace}"
)


def html_page(
    title: str, paragraphs: Iterable[str], *, status_code: int = 200, commands: Sequence[str] = ()
) -> HTMLResponse:
    """A small self-contained page styled like the app's own screens (no scripts, strict CSP);
    ``commands`` are shown as copyable terminal commands. All text is escaped."""
    body = "\n".join(f"<p>{html.escape(text)}</p>" for text in paragraphs)
    cmds = "".join(f"<code>{html.escape(command)}</code>" for command in commands)
    page = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta name='color-scheme' content='light dark'>"
        f"<title>{html.escape(title)} · Ordnung</title><style>{_PAGE_STYLE}</style></head>"
        f"<body><main><div class='mark' aria-hidden='true'>O</div><h1>{html.escape(title)}</h1>\n{body}"
        + (f"<div class='cmds'>{cmds}</div>" if cmds else "")
        + "</main></body></html>"
    )
    return HTMLResponse(
        page,
        status_code=status_code,
        headers={"Content-Security-Policy": content_security_policy(), "Cache-Control": "no-store"},
    )


# --------------------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------------------


def host_allowed(host: str | None) -> bool:
    """``localhost``, ``127.0.0.1`` or ``[::1]``, optionally with a numeric port."""
    if not host:
        return False
    value = host.strip().lower()
    if value.startswith("["):
        end = value.find("]")
        name, rest = (value[: end + 1], value[end + 1 :]) if end != -1 else (value, "")
    else:
        name, _, port = value.partition(":")
        rest = f":{port}" if port else ""
    if rest and not (rest.startswith(":") and _PORT_RE.match(rest[1:])):
        return False
    return name in ALLOWED_HOSTS


def origin_matches(origin: str, host: str) -> bool:
    """Whether an ``Origin`` header names this server (``http(s)://<Host>``)."""
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and parts.netloc.lower() == host.strip().lower()


def token_matches(candidate: str | None, token: str) -> bool:
    """Constant-time token comparison."""
    return bool(candidate) and secrets.compare_digest(str(candidate).encode(), token.encode())


#: What presenting a one-time code did (:meth:`OneTimeCodes.redeem`): it signed in (a new session); the browser
#: it signed in came back to it (``again``); it had been used by someone else, whose session has now ended
#: (``used``); or it is not a code of this server's, or it has expired (``refused``).
RedeemOutcome = Literal["signed_in", "again", "used", "refused"]


class Redemption(NamedTuple):
    """What presenting a one-time code did, and the session it made."""

    outcome: RedeemOutcome
    #: the browser session a code that ``signed_in`` made (the cookie's value)
    session: str | None = None


class OneTimeCodes:
    """The one-time sign-in codes a server takes (:func:`ordnung.server.open_code`): made with its token,
    not expired, and each only once. A code signs in with a browser session of its own, never the token,
    which is also the API's bearer and lasts until the server stops.

    Until the browser uses it, the code is on the browser's command line, where another account on the
    computer can read it and use it first. Its second use (the person's browser, then, or the other
    program after the browser) ends the session its first use made: whoever got in that way is signed
    out again, and the second page says the link was used already. So the codes taken are kept, with
    their sessions, for as long as the server runs: one per browser Ordnung opened."""

    def __init__(self, token: str, *, clock: Callable[[], float] = time.time) -> None:
        self.token = token
        self.clock = clock
        #: nonce → the session its code made ("" once ended)
        self._taken: dict[str, str] = {}

    def redeem(self, code: str | None, *, cookie: str | None = None) -> Redemption:
        """What ``code`` does, presented by a browser whose session cookie is ``cookie``."""
        match = _OPEN_CODE_RE.fullmatch(code or "")
        if match is None:
            return Redemption("refused")
        expires, nonce, mac = int(match[1]), match[2], match[3]
        if not secrets.compare_digest(mac, open_code_mac(self.token, expires, nonce)):
            return Redemption("refused")
        if nonce in self._taken:
            session = self._taken[nonce]
            if session and token_matches(cookie, session):
                return Redemption("again")
            self._taken[nonce] = ""
            return Redemption("used")
        now = self.clock()
        if not now <= expires <= now + OPEN_LINK_S:  # expired, or made to last longer than a link does
            return Redemption("refused")
        session = secrets.token_urlsafe(TOKEN_BYTES)
        self._taken[nonce] = session
        return Redemption("signed_in", session)

    def is_session(self, cookie: str | None) -> bool:
        """Whether ``cookie`` is a session a code made that hasn't ended."""
        return bool(cookie) and any(
            token_matches(cookie, session) for session in self._taken.values() if session
        )


def bearer_token(request: Request) -> str | None:
    """The token of an ``Authorization: Bearer …`` header."""
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


def token_cookie(request: Request) -> str:
    """The session cookie's name for the port this server listens on (``ordnung_token_8765``)."""
    server = request.scope.get("server")
    return f"{TOKEN_COOKIE}_{server[1]}" if server and server[1] else TOKEN_COOKIE


def is_authenticated(request: Request, token: str | None, codes: OneTimeCodes | None = None) -> bool:
    """The session cookie or a bearer header carries the session token, or the cookie a browser session a
    one-time code made (``codes``)."""
    if token is None:
        return True
    cookie = request.cookies.get(token_cookie(request))
    if codes is not None and codes.is_session(cookie):
        return True
    return any(token_matches(candidate, token) for candidate in (cookie, bearer_token(request)))


def _is_api(path: str) -> bool:
    return path == API_PREFIX or path.startswith(API_PREFIX + "/")


def _forbidden(request: Request, message: str, status_code: int = 403) -> Response:
    if _is_api(request.url.path):
        return JSONResponse({"detail": message}, status_code=status_code)
    return html_page("Not allowed", [message], status_code=status_code)


def cross_site_rejection(request: Request) -> Response | None:
    """Host allow-list, Fetch-Metadata, Origin and client-header checks (``None`` = passed)."""
    host = request.headers.get("host")
    if not host_allowed(host):
        return _forbidden(request, "Ordnung only answers requests addressed to localhost.", 400)
    site = request.headers.get("sec-fetch-site")
    if site is not None and site.lower() not in ALLOWED_FETCH_SITES:
        return _forbidden(request, "Requests from other websites are not allowed.")
    origin = request.headers.get("origin")
    if origin is not None and not origin_matches(origin, host or ""):
        return _forbidden(request, "Requests from other websites are not allowed.")
    if request.method not in SAFE_METHODS and not request.headers.get(CLIENT_HEADER):
        return _forbidden(request, "This request must come from the Ordnung app (missing X-Ordnung-Client).")
    return None


def _without_token(request: Request) -> str:
    """The page's own path and query without the token or code (always one leading ``/``: never another
    host)."""
    kept = [(key, value) for key, value in request.query_params.multi_items() if key not in SIGN_IN_QUERIES]
    return "/" + request.url.path.lstrip("/\\") + (f"?{urlencode(kept)}" if kept else "")


def _forward_page(target: str) -> HTMLResponse:
    """A same-origin forward to ``target`` (a redirect would keep the cross-site context)."""
    location = html.escape(target, quote=True)
    page = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<meta http-equiv='refresh' content='0;url={location}'><title>Opening Ordnung</title></head>"
        f"<body><p><a href='{location}'>Open Ordnung</a></p></body></html>"
    )
    return HTMLResponse(
        page, headers={"Content-Security-Policy": content_security_policy(), "Cache-Control": "no-store"}
    )


def _used_link_page() -> Response:
    return html_page(
        "This link was used already",
        [
            "The link Ordnung opened your browser with works only once, and it was used before your browser "
            "got to it: perhaps by another program on this computer. Ordnung has signed that one out again.",
            "Start Ordnung again and open the link it prints:",
        ],
        status_code=401,
        commands=("ordnung serve", "ordnung demo"),
    )


def _open_page(request: Request) -> Response:
    """To the page, for a browser that is signed in already."""
    site = request.headers.get("sec-fetch-site")
    target = _without_token(request)
    return (
        RedirectResponse(target, status_code=303)
        if site is None or site.lower() in ALLOWED_FETCH_SITES
        else _forward_page(target)
    )


def login_response(
    request: Request, token: str, *, valid: bool | None = None, session: str | None = None
) -> Response:
    """``GET <page>?token=…`` (or a one-time ``?open=…`` the caller found ``valid``, with the browser
    ``session`` it made): set the session cookie and redirect to the page without it (a cross-site page
    load, e.g. a link opened from another site, gets a same-origin forward)."""
    if valid is None:
        valid = token_matches(request.query_params.get(TOKEN_QUERY), token)
    if not valid:
        return html_page(
            "This link has expired",
            [
                "The access link is not valid (any more). Ordnung creates a new one each time it starts, "
                "and the link it opens your browser with works only once.",
                "Start it again and open the link it prints:",
            ],
            status_code=401,
            commands=("ordnung serve", "ordnung demo"),
        )
    response = _open_page(request)
    response.set_cookie(
        token_cookie(request),
        session or token,
        max_age=COOKIE_MAX_AGE_S,
        path="/",
        httponly=True,
        samesite="strict",
    )
    return response


def is_token_login(request: Request) -> bool:
    """A top-level page load (not an API call, frame or fetch) carrying ``?token=`` or ``?open=``."""
    return (
        request.method in SAFE_METHODS
        and not _is_api(request.url.path)
        and any(name in request.query_params for name in SIGN_IN_QUERIES)
        and request.headers.get("sec-fetch-mode", "navigate").lower() == "navigate"
        and request.headers.get("sec-fetch-dest", "document").lower() == "document"
    )


def unauthenticated_response(request: Request) -> Response:
    """401 for API calls and pages opened without the session token."""
    if _is_api(request.url.path):
        return JSONResponse(
            {"detail": "Open Ordnung with the link printed by “ordnung serve” to sign in to this window."},
            status_code=401,
        )
    return html_page(
        "Please open Ordnung from its link",
        [
            "For your privacy, Ordnung only talks to the browser tab it opened itself, with the access link "
            "it printed when it started.",
            # the launcher of `ordnung shortcut` opens Ordnung signed in (ordnung.shortcut)
            "If you added Ordnung to your apps with “ordnung shortcut”, open it from there. Otherwise run "
            "one of these in a terminal and use the link it prints (or opens):",
        ],
        status_code=401,
        commands=("ordnung serve", "ordnung demo"),
    )


# --------------------------------------------------------------------------------------------------
# Middleware
# --------------------------------------------------------------------------------------------------


class PhoneGateLike(Protocol):
    """The phone listener's gate (``ordnung.api.phone_gate.PhoneGate``)."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send, app: ASGIApp) -> None: ...


class SecurityMiddleware:
    """ASGI middleware applying the checks above to every HTTP request (and handing the phone
    listener's requests to its gate)."""

    def __init__(self, app: ASGIApp, *, token: str | None, phone: PhoneGateLike | None = None) -> None:
        self.app = app
        self.token = token
        self.phone = phone
        self.codes = OneTimeCodes(token) if token is not None else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":  # Ordnung has none: never let one past the checks
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope.get(LISTENER_KEY) == PHONE_LISTENER:  # never reaches the computer's checks
            if self.phone is None:
                misdirected = JSONResponse({"detail": "Misdirected request.", "code": "misdirected"}, 421)
                await misdirected(scope, receive, _with_headers(send))
                return
            await self.phone(scope, receive, _with_headers(send), self.app)
            return
        request = Request(scope)
        response = self._gate(request)
        if response is not None:
            await response(scope, receive, _with_headers(send))
            return
        await self.app(scope, receive, _with_headers(send))

    def _signs_in(self, request: Request) -> Redemption:
        """What the page load's token, or one-time code, does (a code is then used up; never by a HEAD, which
        shows no page)."""
        query = request.query_params
        if self.token is not None and token_matches(query.get(TOKEN_QUERY), self.token):
            return Redemption("signed_in")
        if self.codes is None or OPEN_QUERY not in query or request.method != "GET":
            return Redemption("refused")
        return self.codes.redeem(query.get(OPEN_QUERY), cookie=request.cookies.get(token_cookie(request)))

    def _sign_in(self, request: Request, token: str) -> Response | None:
        """A page load with a token or one-time code (:func:`is_token_login`)."""
        done = self._signs_in(request)
        if done.outcome == "used":
            logger.warning("A one-time sign-in link was used twice: the sign-in it made has been ended.")
        if done.outcome == "signed_in":
            return login_response(request, token, valid=True, session=done.session)
        if cross_site_rejection(request) is not None:
            return None
        if done.outcome == "again" or is_authenticated(request, token, self.codes):
            return _open_page(request)  # signed in already: a spent link opens the page
        return _used_link_page() if done.outcome == "used" else login_response(request, token, valid=False)

    def _gate(self, request: Request) -> Response | None:
        if self.token is not None and is_token_login(request) and host_allowed(request.headers.get("host")):
            signed_in = self._sign_in(request, self.token)
            if signed_in is not None:
                return signed_in
        rejection = cross_site_rejection(request)
        if rejection is not None:
            return rejection
        path = request.url.path
        if (
            self.token is not None
            and request.method in SAFE_METHODS
            and not _is_api(path)
            and TOKEN_QUERY in request.query_params
        ):
            return login_response(request, self.token)
        authenticated = is_authenticated(request, self.token, self.codes)
        request.scope.setdefault("state", {})[AUTH_STATE_KEY] = authenticated
        if not authenticated and path not in PUBLIC_API_PATHS:
            return unauthenticated_response(request)
        if _is_api(path) and "transfer-encoding" in request.headers:
            return JSONResponse({"detail": "This request must say how long it is."}, status_code=411)
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > MAX_REQUEST_BYTES:
            return JSONResponse({"detail": "Please add at most 200 MB at once."}, status_code=413)
        return None


def _with_headers(send: Send) -> Send:
    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = list(message.get("headers", []))
            present = {name.lower() for name, _ in headers}
            headers.extend(header for header in _ALWAYS_HEADERS if header[0] not in present)
            message = {**message, "headers": headers}
        await send(message)

    return wrapped


def request_authenticated(request: Request) -> bool:
    """Whether the middleware accepted this request's session token."""
    return bool(request.scope.get("state", {}).get(AUTH_STATE_KEY, False))
