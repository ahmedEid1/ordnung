"""Compressed answers (SPEC §13): gzip for the API's JSON answers and the web app's files, on both listeners.

:class:`CompressMiddleware` is plain ASGI, added last in ``create_app``, so it is the outermost of Ordnung's
middlewares: it sees every header the routes, the phone's gate and the security middleware added, and they
keep seeing plain messages. It compresses an answer only when **all** of these hold:

* the request is a ``GET`` whose ``Accept-Encoding`` allows gzip (:func:`accepts_gzip`);
* the answer is ``200`` and ``application/json``;
* it has none of ``Content-Encoding``, ``Content-Range``, ``Content-Disposition`` (every download), ``ETag``
  or ``Accept-Ranges`` (every file) and ``Set-Cookie`` (signing in, pairing), and no
  ``Cache-Control: no-transform``;
* its body comes as one message of at least :data:`MIN_BYTES` (a streamed body passes as it is), and gzip
  makes it smaller.

Anything else passes at once, as it came: a live stream is never held back, a range request keeps its 206,
and writes, pages and downloads are never touched. Compression runs at :data:`GZIP_LEVEL`, in a thread from
:data:`THREAD_BYTES` on (``asyncio.to_thread``: the loop's default executor, which ``ApiState.drain`` waits
for). A JSON answer to a GET that could be compressed says ``Vary: Accept-Encoding``, compressed or not.
Request bodies are never decompressed.

Why not Starlette's ``GZipMiddleware``: at the oldest Starlette Ordnung supports, it compresses 206 answers,
PDFs and pictures, holds every answer's headers until its first body message (a live stream would wait for its
first ping), and its rules changed between versions. These rules are decided here, once.

:class:`GzipFiles` keeps the built web app's text files (:data:`FILE_TYPES`) gzipped in memory, compressed
once per file and version; ``app._mount_web_app`` answers with them (never ``index.html``, a range request or
``HEAD``).
"""

from __future__ import annotations

import asyncio
import gzip
from pathlib import Path

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

GZIP_LEVEL = 6
#: The web app's files are compressed once per process, so they get the smallest result.
FILE_GZIP_LEVEL = 9
#: Smaller answers and files stay as they are.
MIN_BYTES = 1024
#: Bigger answers are compressed in a thread, off the event loop.
THREAD_BYTES = 128 * 1024
COMPRESSIBLE = frozenset({"application/json"})
#: An answer with any of these is never compressed: already encoded, a range, a download, a file, a cookie.
NEVER_WITH = frozenset(
    {b"content-encoding", b"content-range", b"content-disposition", b"etag", b"accept-ranges", b"set-cookie"}
)
#: The web app's files that are sent gzipped, with their media type (never the system's registry, which can
#: map ``.js`` to ``text/plain`` on Windows).
FILE_TYPES: dict[str, str] = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
}
VARY_VALUE = "Accept-Encoding"


# --------------------------------------------------------------------------------------------------
# the rules
# --------------------------------------------------------------------------------------------------


def _quality(params: list[str]) -> float:
    """The ``q`` of one ``Accept-Encoding`` entry (1 without one; 0 when it isn't a number from 0 to 1)."""
    for param in params:
        name, _, value = param.partition("=")
        if name.strip().lower() != "q":
            continue
        try:
            quality = float(value.strip())
        except ValueError:
            return 0.0
        return quality if 0.0 <= quality <= 1.0 else 0.0
    return 1.0


def accepts_gzip(header: str) -> bool:
    """``Accept-Encoding`` allows gzip: ``gzip`` (or, when gzip isn't named, ``*``) with a ``q`` above 0
    (``gzip;q=0`` refuses it; ``identity`` alone never takes it)."""
    named: float | None = None
    wildcard: float | None = None
    for entry in header.split(","):
        coding, *params = entry.split(";")
        name = coding.strip().lower()
        if name == "gzip":
            named = max(named or 0.0, _quality(params))
        elif name == "*":
            wildcard = max(wildcard or 0.0, _quality(params))
    chosen = named if named is not None else wildcard
    return chosen is not None and chosen > 0


def _compressible(start: Message) -> bool:
    """A ``200`` JSON answer without any header of :data:`NEVER_WITH` or ``no-transform``."""
    if start.get("status") != 200 or start.get("trailers", False):
        return False
    media = ""
    for raw_name, raw_value in start.get("headers", ()):
        name = bytes(raw_name).lower()
        if name in NEVER_WITH:
            return False
        value = bytes(raw_value).decode("latin-1")
        if name == b"content-type":
            media = value.split(";", 1)[0].strip().lower()
        elif name == b"cache-control" and "no-transform" in value.lower():
            return False
    return media in COMPRESSIBLE


def _with_vary(start: Message) -> Message:
    """``start`` saying ``Vary: Accept-Encoding`` (added to a ``Vary`` it has, once)."""
    headers = list(start.get("headers", ()))
    for index, (raw_name, raw_value) in enumerate(headers):
        if bytes(raw_name).lower() != b"vary":
            continue
        value = bytes(raw_value).decode("latin-1")
        tokens = {token.strip().lower() for token in value.split(",")}
        if VARY_VALUE.lower() in tokens or "*" in tokens:
            return start
        headers[index] = (raw_name, f"{value}, {VARY_VALUE}".encode("latin-1"))
        return {**start, "headers": headers}
    return {**start, "headers": [*headers, (b"vary", VARY_VALUE.encode("latin-1"))]}


def _gzipped(start: Message, length: int) -> Message:
    headers = [
        (name, value) for name, value in start.get("headers", ()) if bytes(name).lower() != b"content-length"
    ]
    headers += [(b"content-encoding", b"gzip"), (b"content-length", str(length).encode("latin-1"))]
    return {**start, "headers": headers}


def gzip_body(body: bytes) -> bytes:
    """An answer's body gzipped (no time stamp: the same body gives the same bytes)."""
    return gzip.compress(body, compresslevel=GZIP_LEVEL, mtime=0)


def gzip_file(data: bytes) -> bytes:
    """A web app file gzipped (no time stamp)."""
    return gzip.compress(data, compresslevel=FILE_GZIP_LEVEL, mtime=0)


# --------------------------------------------------------------------------------------------------
# the middleware
# --------------------------------------------------------------------------------------------------


class _Answer:
    """One answer on its way out: passed on as it comes, or — a JSON answer the client takes gzipped — its
    start held until its body shows whether gzip is worth it."""

    def __init__(self, send: Send, wants_gzip: bool) -> None:
        self._send = send
        self._wants_gzip = wants_gzip
        self._held: Message | None = None
        self._decided = False

    async def send(self, message: Message) -> None:
        if self._decided:
            await self._send(message)
        elif self._held is None:
            await self._started(message)
        else:
            held, self._held = self._held, None
            self._decided = True
            await self._first_after(held, message)

    async def _started(self, message: Message) -> None:
        if message["type"] != "http.response.start" or not _compressible(message):
            self._decided = True
            await self._send(message)
            return
        start = _with_vary(message)
        if self._wants_gzip:
            self._held = start  # until the body shows whether gzip is worth it
            return
        self._decided = True
        await self._send(start)

    async def _first_after(self, start: Message, message: Message) -> None:
        body = message.get("body", b"")
        whole = message["type"] == "http.response.body" and not message.get("more_body", False)
        if whole and len(body) >= MIN_BYTES:
            zipped = (
                await asyncio.to_thread(gzip_body, body) if len(body) >= THREAD_BYTES else gzip_body(body)
            )
            if len(zipped) < len(body):
                await self._send(_gzipped(start, len(zipped)))
                await self._send({"type": "http.response.body", "body": zipped, "more_body": False})
                return
        await self._send(start)
        await self._send(message)

    async def finish(self) -> None:
        """A start the app sent without any body after it still goes out."""
        if self._held is not None:
            start, self._held = self._held, None
            await self._send(start)


class CompressMiddleware:
    """Gzip for GET answers that are one JSON body, nothing else (the rules: the module's docstring)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "GET":
            await self.app(scope, receive, send)
            return
        wants = accepts_gzip(", ".join(Headers(scope=scope).getlist("accept-encoding")))
        answer = _Answer(send, wants)
        await self.app(scope, receive, answer.send)
        await answer.finish()


# --------------------------------------------------------------------------------------------------
# the web app's files
# --------------------------------------------------------------------------------------------------


def _packed(path: Path) -> bytes | None:
    data = path.read_bytes()
    zipped = gzip_file(data)
    return zipped if len(zipped) < len(data) else None


class GzipFiles:
    """The web app's files gzipped once and kept in memory, by file and version (its size and change time): a
    file rebuilt while Ordnung runs is compressed again, and only its newest version is kept (about 1.2 MB for
    the whole build). A file under :data:`MIN_BYTES`, or one gzip doesn't make smaller, is sent as it is."""

    def __init__(self) -> None:
        self._files: dict[Path, tuple[int, int, bytes | None]] = {}

    async def get(self, path: Path) -> bytes | None:
        """``path`` gzipped, or ``None`` when it goes as it is (looked up and compressed in a thread)."""
        return await asyncio.to_thread(self._get, path)

    def _get(self, path: Path) -> bytes | None:
        stat = path.stat()
        version = (stat.st_mtime_ns, stat.st_size)
        known = self._files.get(path)
        if known is not None and (known[0], known[1]) == version:
            return known[2]
        zipped = _packed(path) if stat.st_size >= MIN_BYTES else None
        self._files[path] = (*version, zipped)
        return zipped
