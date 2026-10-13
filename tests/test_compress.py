"""Compressed answers (SPEC §13): JSON answers to a GET and the web app's files go out gzip-compressed on
both listeners — the computer's (an httpx client over ASGI) and the phone's (``PhoneListener``, paired) —
while live streams, downloads, range requests, writes and anything that sets a cookie never are; the
phone's TLS has its own compression off."""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import ssl
import threading
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

import helpers_proof
from fixtures_llm import TAX_LETTER
from ordnung import clock, sync
from ordnung.api import app as app_module
from ordnung.api import compress
from ordnung.api.compress import CompressMiddleware, accepts_gzip
from ordnung.api.phone_gate import PERMISSIONS_POLICY, PhoneListener
from ordnung.phone import tls
from ordnung.phone.access import listener_config
from phone_support import (
    ADDRESS,
    COOKIE,
    PHONE_HEADERS,
    TOKEN,
    Exchange,
    drive,
    pair,
    phone_app,
    phone_client,
)
from sync_fake_engine import FakeEngine, FakeSession
from sync_support import agent_of, computer, connect, fast_sync
from test_api_support import INDEX_HTML, TODAY, Api, api_for, fake_web_dist

GZIP = {"Accept-Encoding": "gzip"}
PLAIN = {"Accept-Encoding": "identity"}
COMPUTER_HOST = {"host": "127.0.0.1:8765"}
#: a live stream's first message arrives at once, long before its first keep-alive ping (15 s)
STARTS_WITHIN_S = 3
#: index.html padded past the size a JSON answer would be compressed at
BIG_INDEX = INDEX_HTML.replace("</body>", f"<!-- {'padding ' * 400} --></body>")
BIG_JS = "export const words = [" + ",".join(f'"word{i}"' for i in range(3000)) + "];\n"
BIG_CSS = ".row { color: #1d1b16; padding: 0 1rem; }\n" * 400
PROFILE = {"name": "Sam Rivera", "address": "Musterweg 1\n12345 Musterstadt", "email": "sam@example.org"}


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture(autouse=True)
def dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    built = fake_web_dist(tmp_path)
    (built / "index.html").write_text(BIG_INDEX, encoding="utf-8")
    (built / "assets" / "app-big.js").write_text(BIG_JS, encoding="utf-8")
    (built / "assets" / "style-big.css").write_text(BIG_CSS, encoding="utf-8")
    (built / "build-info.json").write_text(json.dumps({"files": ["x" * 40] * 60}), encoding="utf-8")
    monkeypatch.setattr(app_module, "web_dist_dir", lambda: built)
    return built


async def raw(
    client: httpx.AsyncClient, method: str, path: str, **kwargs: Any
) -> tuple[httpx.Response, bytes]:
    """The answer and its bytes exactly as they came over the wire (never decoded)."""
    async with client.stream(method, path, **kwargs) as response:
        body = b"".join([chunk async for chunk in response.aiter_raw()])
    return response, body


def vary(response: httpx.Response | Exchange) -> set[str]:
    value = response.headers.get("vary", "")
    return {part.strip().lower() for part in value.split(",") if part.strip()}


async def _read_tax_letter(api: Api) -> str:
    body = await api.upload(("steuer.pdf", TAX_LETTER.pdf()))
    await api.read_all()
    return str(body["documents"][0]["id"])


# --------------------------------------------------------------------------------------------------
# the rule: when a client may get gzip
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "allowed"),
    [
        ("gzip", True),
        ("GZip", True),
        ("gzip, deflate, br, zstd", True),
        ("deflate, gzip;q=0.5", True),
        ("br, *;q=0.1", True),
        ("*", True),
        ("*;q=0, gzip", True),  # named outranks the wildcard
        ("gzip;q=0", False),
        ("gzip; q=0.000", False),
        ("gzip;q=0, *", False),
        ("*;q=0", False),
        ("identity", False),
        ("deflate, br", False),
        ("gzip;q=lots", False),
        ("", False),
    ],
)
def test_gzip_q0_and_identity_only_are_respected(header: str, allowed: bool) -> None:
    assert accepts_gzip(header) is allowed


async def test_gzip_q0_on_the_wire_gets_plain_bytes(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response, body = await raw(api.client, "GET", "/api/rules", headers={"Accept-Encoding": "gzip;q=0"})
        assert "content-encoding" not in response.headers
        assert json.loads(body) == (await api.client.get("/api/rules", headers=PLAIN)).json()


# --------------------------------------------------------------------------------------------------
# JSON answers
# --------------------------------------------------------------------------------------------------


async def test_a_large_json_answer_is_gzipped_when_the_client_asks(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        _plain, plain_body = await raw(api.client, "GET", "/api/rules", headers=PLAIN)
        zipped, zipped_body = await raw(api.client, "GET", "/api/rules", headers=GZIP)
        assert zipped.status_code == 200 and zipped.headers["content-encoding"] == "gzip"
        assert zipped.headers["content-type"] == "application/json"
        assert int(zipped.headers["content-length"]) == len(zipped_body)
        assert gzip.decompress(zipped_body) == plain_body
        assert len(zipped_body) < len(plain_body) / 3, (len(zipped_body), len(plain_body))
        # every header the answer had stays (the security middleware's too)
        assert zipped.headers["x-content-type-options"] == "nosniff"
        assert zipped.headers["referrer-policy"] == "no-referrer"
        # an ordinary client decodes it as it always did
        assert (await api.client.get("/api/rules")).json() == json.loads(plain_body)


async def test_small_answers_and_clients_without_gzip_get_plain_bytes(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        small, small_body = await raw(api.client, "GET", "/api/health", headers=GZIP)
        assert len(small_body) < compress.MIN_BYTES
        assert "content-encoding" not in small.headers and json.loads(small_body)["version"]
        plain, plain_body = await raw(api.client, "GET", "/api/rules", headers=PLAIN)
        assert "content-encoding" not in plain.headers
        assert int(plain.headers["content-length"]) == len(plain_body) > compress.MIN_BYTES
        # a client that says nothing about encodings (no Accept-Encoding at all)
        exchange = Exchange()
        exchange.left.set()
        await drive(
            api.app, "GET", "/api/rules", headers=COMPUTER_HOST, client="127.0.0.1",
            server=("127.0.0.1", 8765), scheme="http", exchange=exchange,
        )  # fmt: skip
        assert exchange.status == 200 and "content-encoding" not in exchange.headers
        assert exchange.body == plain_body


async def test_compressible_answers_say_they_vary_by_accept_encoding(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        for path, headers in (("/api/rules", GZIP), ("/api/rules", PLAIN), ("/api/health", GZIP)):
            response, _ = await raw(api.client, "GET", path, headers=headers)
            assert "accept-encoding" in vary(response), (path, headers, response.headers)
        # a cache that kept the plain answer never hands it to a client that asked for gzip, and back
        zipped, _ = await raw(api.client, "GET", "/api/rules", headers=GZIP)
        assert zipped.headers["vary"].lower().count("accept-encoding") == 1


async def test_big_answers_are_compressed_off_the_event_loop(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: list[int] = []
    real = compress.gzip_body

    def spy(body: bytes) -> bytes:
        threads.append(threading.get_ident())
        return real(body)

    monkeypatch.setattr(compress, "gzip_body", spy)
    loop_thread = threading.get_ident()
    async with api_for(data_dir) as api:
        rules = await api.client.get("/api/rules", headers=GZIP)  # about 40 KB: at once, on the loop
        assert rules.headers["content-encoding"] == "gzip"
        assert threads == [loop_thread]
        schema = await api.client.get("/api/openapi.json", headers=GZIP)  # above 128 KiB: in a thread
        assert len(schema.content) > compress.THREAD_BYTES
        assert schema.headers["content-encoding"] == "gzip" and len(threads) == 2
        assert threads[1] != loop_thread
        monkeypatch.setattr(compress, "THREAD_BYTES", 4096)
        await api.client.get("/api/rules", headers=GZIP)
        assert len(threads) == 3 and threads[2] != loop_thread


# --------------------------------------------------------------------------------------------------
# what is never compressed
# --------------------------------------------------------------------------------------------------


async def test_the_live_events_stream_starts_at_once_and_is_never_compressed(data_dir: Path) -> None:
    async def watch(app: Any, headers: dict[str, str], publish: Callable[[], None], **where: Any) -> Exchange:
        exchange = Exchange()
        task = asyncio.create_task(
            drive(app, "GET", "/api/events", headers=headers, exchange=exchange, **where)
        )
        try:
            await asyncio.wait_for(exchange.started.wait(), STARTS_WITHIN_S)  # before any event or ping
            assert exchange.body == b""
            publish()
            async with asyncio.timeout(STARTS_WITHIN_S):
                while b"itm_live" not in exchange.body:  # noqa: ASYNC110 - the exchange only collects
                    await asyncio.sleep(0.01)
        finally:
            exchange.left.set()
            await asyncio.wait_for(task, 5)
        return exchange

    async with phone_app(data_dir) as (api, _net, _servers):
        async with phone_client(api) as phone:
            signed = await pair(api, phone)

        def publish() -> None:
            api.ctx.bus.publish("item.updated", item_id="itm_live")

        computer_stream = await watch(
            api.app, {**COMPUTER_HOST, **GZIP, "authorization": f"Bearer {TOKEN}"}, publish,
            client="127.0.0.1", server=("127.0.0.1", 8765), scheme="http",
        )  # fmt: skip
        phone_headers = {**PHONE_HEADERS, **GZIP, "cookie": f"{COOKIE}={signed['token']}"}
        phone_stream = await watch(PhoneListener(api.app), phone_headers, publish)
        for exchange in (computer_stream, phone_stream):
            assert exchange.status == 200
            assert exchange.headers["content-type"].startswith("text/event-stream")
            assert "content-encoding" not in exchange.headers
            assert b"event: item.updated" in exchange.body  # plain text, as it was sent


async def test_ask_stream_is_never_compressed(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response, body = await raw(
            api.client, "POST", "/api/ask", json={"question": "Anything due?"}, headers=GZIP
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "content-encoding" not in response.headers
        assert b"data:" in body


async def test_file_downloads_are_never_compressed(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        assert (await api.client.put("/api/profile", json=PROFILE)).status_code == 200
        doc_id = await _read_tax_letter(api)
        items = (await api.client.get("/api/items")).json()
        payment = next(item for item in items if item["kind"] == "payment" and item["due_date"])
        objection = await api.client.post("/api/drafts", json={"kind": "objection", "doc_id": doc_id})
        assert objection.status_code == 201, objection.text
        gym = helpers_proof.gym(api.ctx)
        cancellation = (
            await api.client.post("/api/drafts", json={"kind": "cancellation", "contract_id": gym.contract})
        ).json()
        sent = await api.client.post(
            f"/api/drafts/{cancellation['id']}/sent", json={"channel": "registered_letter", "date": TODAY}
        )
        assert sent.status_code == 200, sent.text

        downloads: dict[str, tuple[str, str, dict[str, Any]]] = {
            "letter PDF": ("GET", f"/api/documents/{doc_id}/file", {}),
            "page picture": ("GET", f"/api/documents/{doc_id}/pages/1.jpg", {}),
            "thumbnail": ("GET", f"/api/documents/{doc_id}/thumbnail.jpg", {}),
            "calendar": ("GET", "/api/calendar.ics", {}),
            "one date": ("GET", f"/api/items/{payment['id']}.ics", {}),
            "letters ZIP": ("GET", "/api/documents.zip", {}),
            "drafted PDF": ("GET", f"/api/drafts/{objection.json()['id']}/pdf", {}),
            "Nachweis PDF": ("GET", f"/api/drafts/{cancellation['id']}/proof.pdf", {}),
            "backup": ("POST", "/api/backup", {"json": {"passphrase": "orbit velvet canyon maple thunder"}}),
        }
        for name, (method, path, extra) in downloads.items():
            response, body = await raw(api.client, method, path, headers=GZIP, **extra)
            assert response.status_code == 200, (name, response.status_code)
            assert "content-encoding" not in response.headers, name
            assert "accept-encoding" not in vary(response), name
            if "content-length" in response.headers:
                assert int(response.headers["content-length"]) == len(body), name
            # the same bytes a client that never asked for gzip gets (the others are made afresh each time)
            if name in ("letter PDF", "page picture", "thumbnail"):
                assert body == (await raw(api.client, method, path, headers=PLAIN, **extra))[1], name
        _letter, letter_body = await raw(api.client, "GET", f"/api/documents/{doc_id}/file", headers=GZIP)
        assert letter_body == TAX_LETTER.pdf()


async def test_a_kept_copy_download_is_never_compressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fast_sync(monkeypatch)
    (tmp_path / "Nextcloud").mkdir()
    engine = FakeEngine()
    async with computer(tmp_path / "desk", engine=engine) as api:
        await connect(api, tmp_path / "Nextcloud" / "Ordnung", "desktop")
        kept = FakeSession(engine, api.ctx.paths).keep_local(
            api.ctx.paths, "before you kept laptop's Ordnung"
        )
        await agent_of(api).load()
        response, body = await raw(api.client, "GET", f"/api/sync/kept/{kept.name}", headers=GZIP)
        assert response.status_code == 200 and "content-encoding" not in response.headers
        assert body == (api.ctx.paths.sync / sync.KEPT_DIR / kept.name).read_bytes()


async def test_a_range_request_gets_the_plain_206(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        doc_id = await _read_tax_letter(api)
        original = TAX_LETTER.pdf()
        response, body = await raw(
            api.client, "GET", f"/api/documents/{doc_id}/file", headers={**GZIP, "Range": "bytes=0-99"}
        )
        assert response.status_code == 206
        assert response.headers["content-range"] == f"bytes 0-99/{len(original)}"
        assert "content-encoding" not in response.headers
        assert body == original[:100]
        async with phone_client(api) as phone:
            await pair(api, phone)
            page = (await phone.get(f"/api/documents/{doc_id}/pages/1.jpg", headers=PLAIN)).content
            part, part_body = await raw(
                phone,
                "GET",
                f"/api/documents/{doc_id}/pages/1.jpg",
                headers={**GZIP, "Range": "bytes=10-209"},
            )
        assert part.status_code == 206 and "content-encoding" not in part.headers
        assert part_body == page[10:210]


async def test_answers_that_set_a_cookie_are_never_compressed(data_dir: Path, tmp_path: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        async with api_for(tmp_path / "other", token="s3cret") as signing_in:
            login = await signing_in.client.get(
                "/?token=s3cret", headers={**GZIP, "Sec-Fetch-Site": "none"}, follow_redirects=False
            )
            assert login.status_code == 303 and "set-cookie" in login.headers
            assert "content-encoding" not in login.headers
        async with phone_client(api) as phone:
            made = (await api.client.post("/api/phone/pairing")).json()["code"]
            paired, _ = await raw(
                phone, "POST", "/api/phone/pair", json={"code": made, "name": "Sam's iPhone"}, headers=GZIP
            )
            assert paired.status_code == 200 and "set-cookie" in paired.headers
            assert "content-encoding" not in paired.headers
            phone.cookies.set(COOKIE, paired.cookies[COOKIE], domain=ADDRESS)
            page, page_body = await raw(
                phone, "GET", "/inbox", headers={**GZIP, "Sec-Fetch-Dest": "document"}
            )
            assert page.status_code == 200 and "set-cookie" in page.headers
            assert "content-encoding" not in page.headers and page_body.startswith(b"<!doctype html>")


async def test_writes_are_never_compressed(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        assert (await api.client.put("/api/profile", json=PROFILE)).status_code == 200
        doc_id = await _read_tax_letter(api)
        writes: list[tuple[str, str, dict[str, Any]]] = [
            ("POST", "/api/drafts", {"json": {"kind": "objection", "doc_id": doc_id}}),
            ("PATCH", f"/api/documents/{doc_id}", {"json": {"title": "Income tax notice 2025"}}),
        ]
        for method, path, extra in writes:
            response, body = await raw(api.client, method, path, headers=GZIP, **extra)
            assert response.status_code in (200, 201), (path, response.text)
            assert len(body) > compress.MIN_BYTES, (path, len(body))
            assert "content-encoding" not in response.headers, path
            json.loads(body)


# --------------------------------------------------------------------------------------------------
# the phone listener
# --------------------------------------------------------------------------------------------------


async def test_phone_answers_are_compressed_and_keep_their_headers(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        await pair(api, phone)
        plain, plain_body = await raw(phone, "GET", "/api/rules", headers=PLAIN)
        zipped, zipped_body = await raw(phone, "GET", "/api/rules", headers=GZIP)
        assert zipped.status_code == 200 and zipped.headers["content-encoding"] == "gzip"
        assert gzip.decompress(zipped_body) == plain_body
        for response in (plain, zipped):
            assert response.headers["cross-origin-resource-policy"] == "same-origin"
            assert response.headers["permissions-policy"] == PERMISSIONS_POLICY
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert "accept-encoding" in vary(response)
        small, _ = await raw(phone, "GET", "/api/health", headers=GZIP)
        assert "content-encoding" not in small.headers


# --------------------------------------------------------------------------------------------------
# the web app's files
# --------------------------------------------------------------------------------------------------


async def test_web_app_files_are_served_gzipped_from_a_cache(
    data_dir: Path, dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[int] = []
    real = compress.gzip_file

    def counting(data: bytes) -> bytes:
        made.append(len(data))
        return real(data)

    monkeypatch.setattr(compress, "gzip_file", counting)

    async def check(client: httpx.AsyncClient) -> None:
        for path, media, source in (
            ("/assets/app-big.js", "text/javascript; charset=utf-8", BIG_JS),
            ("/assets/style-big.css", "text/css; charset=utf-8", BIG_CSS),
        ):
            response, body = await raw(client, "GET", path, headers=GZIP)
            assert response.status_code == 200, path
            assert response.headers["content-encoding"] == "gzip", path
            assert response.headers["content-type"] == media
            assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
            assert "accept-encoding" in vary(response)
            assert int(response.headers["content-length"]) == len(body)
            assert gzip.decompress(body) == source.encode()
        info, info_body = await raw(client, "GET", "/build-info.json", headers=GZIP)
        if info.status_code == 200:  # the computer's (a phone never loads it)
            assert info.headers["content-encoding"] == "gzip" and info.headers["cache-control"] == "no-cache"
            assert json.loads(gzip.decompress(info_body))["files"]
        # a file too small to be worth it goes as it is
        icon, icon_body = await raw(client, "GET", "/favicon.svg", headers=GZIP)
        assert "content-encoding" not in icon.headers and icon_body.startswith(b"<svg")
        assert "accept-encoding" in vary(icon)

    async with phone_app(data_dir) as (api, _net, _servers):
        await check(api.client)
        compressed_once = len(made)
        async with phone_client(api) as phone:  # an unpaired phone loads the app's own files
            await check(phone)
        await check(api.client)
        assert len(made) == compressed_once == 3  # js, css and build-info.json once: then from memory
        # a file that changed (a rebuild while Ordnung runs) is compressed again
        changed = BIG_JS.replace("word", "term")
        (dist / "assets" / "app-big.js").write_text(changed, encoding="utf-8")
        _response, body = await raw(api.client, "GET", "/assets/app-big.js", headers=GZIP)
        assert gzip.decompress(body) == changed.encode() and len(made) == compressed_once + 1


async def test_web_app_range_and_head_requests_stay_plain(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        part, part_body = await raw(
            api.client, "GET", "/assets/app-big.js", headers={**GZIP, "Range": "bytes=0-9"}
        )
        assert part.status_code == 206 and "content-encoding" not in part.headers
        assert part_body == BIG_JS.encode()[:10]
        head = await api.client.head("/assets/app-big.js", headers=GZIP)
        assert head.status_code == 200 and "content-encoding" not in head.headers
        assert int(head.headers["content-length"]) == len(BIG_JS.encode())
        plain, plain_body = await raw(api.client, "GET", "/assets/app-big.js", headers=PLAIN)
        assert plain.status_code == 200 and "content-encoding" not in plain.headers
        assert plain_body == BIG_JS.encode() and "accept-encoding" in vary(plain)
        assert plain.headers["content-type"] == "text/javascript; charset=utf-8"


async def test_index_html_is_never_compressed_and_keeps_its_csp(data_dir: Path) -> None:
    async with phone_app(data_dir) as (api, _net, _servers):
        for path in ("/", "/inbox", "/index.html"):
            page, body = await raw(api.client, "GET", path, headers=GZIP)
            assert page.status_code == 200, path
            assert len(body) > compress.MIN_BYTES and body.startswith(b"<!doctype html>")
            assert "content-encoding" not in page.headers, path
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
            assert page.headers["cache-control"] == "no-cache"
        async with phone_client(api) as phone:
            await pair(api, phone)
            page, body = await raw(phone, "GET", "/", headers=GZIP)
            assert "content-encoding" not in page.headers and body.startswith(b"<!doctype html>")
            assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


# --------------------------------------------------------------------------------------------------
# the middleware's rules, one at a time
# --------------------------------------------------------------------------------------------------

BIG_JSON = json.dumps({"rows": [{"id": i, "title": f"Letter {i}"} for i in range(200)]}).encode()


def _answer(
    *, status: int = 200, media: str = "application/json", headers: dict[str, str] | None = None,
    chunks: tuple[bytes, ...] = (BIG_JSON,),
) -> Callable[..., Awaitable[None]]:  # fmt: skip
    async def app(scope: Any, receive: Any, send: Any) -> None:
        sent = [
            (b"content-type", media.encode()),
            *((k.encode(), v.encode()) for k, v in (headers or {}).items()),
        ]
        if len(chunks) == 1:
            sent.append((b"content-length", str(len(chunks[0])).encode()))
        await send({"type": "http.response.start", "status": status, "headers": sent})
        for index, chunk in enumerate(chunks):
            await send({"type": "http.response.body", "body": chunk, "more_body": index < len(chunks) - 1})

    return app


async def _through(app: Any, method: str = "GET", accept: str = "gzip") -> Exchange:
    exchange = Exchange()
    exchange.left.set()
    headers = {**COMPUTER_HOST, "accept-encoding": accept}
    return await drive(
        CompressMiddleware(app), method, "/api/x", headers=headers, client="127.0.0.1",
        server=("127.0.0.1", 8765), scheme="http", exchange=exchange,
    )  # fmt: skip


async def test_a_whole_json_body_to_a_get_is_compressed() -> None:
    for media in ("application/json", "application/json; charset=utf-8"):
        zipped = await _through(_answer(media=media))
        assert zipped.headers["content-encoding"] == "gzip" and gzip.decompress(zipped.body) == BIG_JSON
        assert int(zipped.headers["content-length"]) == len(zipped.body)


RANDOM = os.urandom(4096)
#: Answers that pass exactly as they came: anything but a whole JSON body of 200 to a GET without the headers
#: of a download, a cookie or a range.
PASSED_AS_THEY_ARE: dict[str, dict[str, Any]] = {
    "partial": {"status": 206, "headers": {"content-range": "bytes 0-9/99"}},
    "created": {"status": 201},
    "not found": {"status": 404},
    "error": {"status": 500},
    **{
        media: {"media": media}
        for media in (
            "application/pdf", "image/jpeg", "image/png", "text/calendar; charset=utf-8", "application/zip",
            "text/html; charset=utf-8", "text/event-stream", "text/plain; charset=utf-8",
            "application/octet-stream", "application/problem+json",
        )
    },
    **{
        name: {"headers": {name: value}}
        for name, value in (
            ("set-cookie", "a=b; HttpOnly"),
            ("content-disposition", 'attachment; filename="records.json"'),
            ("etag", '"abc"'),
            ("accept-ranges", "bytes"),
            ("content-range", "bytes 0-9/99"),
            ("content-encoding", "br"),
        )
    },
    "no-transform": {"headers": {"cache-control": "private, No-Transform"}},
    "streamed": {"chunks": (BIG_JSON[:2000], BIG_JSON[2000:])},
    "worse when gzipped": {"chunks": (RANDOM,)},
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(PASSED_AS_THEY_ARE))
async def test_everything_else_passes_as_it_came(case: str) -> None:
    answer = PASSED_AS_THEY_ARE[case]
    exchange = await _through(_answer(**answer))
    assert exchange.status == answer.get("status", 200)
    assert exchange.headers.get("content-encoding") == answer.get("headers", {}).get("content-encoding")
    chunks = answer.get("chunks", (BIG_JSON,))
    bodies = [m for m in exchange.messages if m["type"] == "http.response.body"]
    assert [m["body"] for m in bodies] == list(chunks)  # message by message, as the app sent them
    assert exchange.complete


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "HEAD"])
async def test_only_a_get_is_compressed(method: str) -> None:
    exchange = await _through(_answer(), method)
    assert "content-encoding" not in exchange.headers and exchange.body == BIG_JSON


async def test_vary_is_added_once_and_keeps_what_the_answer_said() -> None:
    kept = await _through(_answer(headers={"vary": "Cookie"}))
    assert kept.headers["content-encoding"] == "gzip" and vary(kept) == {"cookie", "accept-encoding"}
    once = await _through(_answer(headers={"vary": "Accept-Encoding"}))
    assert once.headers["vary"] == "Accept-Encoding"
    plain = await _through(_answer(), accept="identity")
    assert vary(plain) == {"accept-encoding"}
    small = await _through(_answer(chunks=(b'{"ok": true}',)))
    assert "content-encoding" not in small.headers and vary(small) == {"accept-encoding"}
    pdf = await _through(_answer(media="application/pdf"))
    assert "vary" not in pdf.headers


async def test_a_stream_s_first_message_is_never_held_back() -> None:
    """A JSON answer that qualifies waits for its body; anything else starts at once."""
    release = asyncio.Event()

    async def slow_stream(scope: Any, receive: Any, send: Any) -> None:
        start = {
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/event-stream")],
        }
        await send(start)
        await release.wait()
        await send({"type": "http.response.body", "body": b"data: x\n\n", "more_body": False})

    exchange = Exchange()
    exchange.left.set()
    task = asyncio.create_task(
        drive(
            CompressMiddleware(slow_stream), "GET", "/api/events", headers={**COMPUTER_HOST, **GZIP},
            client="127.0.0.1", server=("127.0.0.1", 8765), scheme="http", exchange=exchange,
        )
    )  # fmt: skip
    await asyncio.wait_for(exchange.started.wait(), STARTS_WITHIN_S)
    assert exchange.body == b""
    release.set()
    await asyncio.wait_for(task, 5)
    assert exchange.body == b"data: x\n\n" and "content-encoding" not in exchange.headers


# --------------------------------------------------------------------------------------------------
# the phone's TLS
# --------------------------------------------------------------------------------------------------


def test_phone_tls_turns_off_tls_compression(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Python and OpenSSL already leave TLS compression off (CRIME); the listener says so itself, so an
    OpenSSL built otherwise can't turn it on."""
    import uvicorn.config

    made = uvicorn.config.create_ssl_context

    def permissive(*args: Any, **kwargs: Any) -> ssl.SSLContext:
        context = made(*args, **kwargs)
        context.options &= ~ssl.OP_NO_COMPRESSION
        return context

    monkeypatch.setattr(uvicorn.config, "create_ssl_context", permissive)
    certs = tls.ensure(tmp_path / "phone", "127.0.0.1")
    config = listener_config(lambda *a: None, "127.0.0.1", 8767, certs)  # type: ignore[arg-type,return-value]
    assert config.ssl is not None and config.ssl.options & ssl.OP_NO_COMPRESSION
