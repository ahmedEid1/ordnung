"""Localhost defences (host allow-list, token cookie, client header, Fetch-Metadata, Origin), the web
app with its CSP, the server discovery file and the cached Claude status."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import stat
import threading
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from ordnung import __version__, clock
from ordnung.api import app as app_module
from ordnung.api.deps import ClaudeStatusCache, probe_claude_cli
from ordnung.api.security import content_security_policy, host_allowed, inline_script_hashes
from ordnung.models import ClaudeStatus
from ordnung.server import (
    ServerInfo,
    advertise,
    clear_server_info,
    generate_token,
    pid_alive,
    read_server_info,
    running_server,
    server_file,
    write_server_info,
)
from test_api_support import BASE_URL, THEME_SCRIPT, TODAY, api_for, client_for, fake_web_dist, lifespan

TOKEN = "s3cret-token"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def web_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dist = fake_web_dist(tmp_path)
    monkeypatch.setattr(app_module, "web_dist_dir", lambda: dist)
    return dist


# --------------------------------------------------------------------------------------------------
# host, client header, Fetch-Metadata, Origin
# --------------------------------------------------------------------------------------------------


def test_host_allow_list() -> None:
    for host in ("localhost", "localhost:8765", "127.0.0.1:5173", "[::1]", "[::1]:8765"):
        assert host_allowed(host), host
    for host in (
        None,
        "",
        "evil.example",
        "evil.example:8765",
        "127.0.0.1.nip.io",
        "localhost:80a",
        "[::2]:1",
    ):
        assert not host_allowed(host), host


async def test_foreign_host_is_rejected(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        ok = await api.client.get("/api/profile")
        assert ok.status_code == 200
        async with client_for(api.app) as other:
            other.base_url = "http://attacker.example:8765"  # type: ignore[assignment]
            rejected = await other.get("/api/profile")
        assert rejected.status_code == 400
        assert "localhost" in rejected.json()["detail"]


async def test_writes_need_the_client_header(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.put(
            "/api/profile", json={"name": "Sam"}, headers={"X-Ordnung-Client": ""}
        )
        assert response.status_code == 403
        assert "X-Ordnung-Client" in response.json()["detail"]
        assert (await api.client.get("/api/profile")).json()["name"] == ""
        assert (await api.client.put("/api/profile", json={"name": "Sam"})).status_code == 200


@pytest.mark.parametrize(
    ("site", "allowed"), [("same-origin", True), ("none", True), ("same-site", False), ("cross-site", False)]
)
async def test_fetch_metadata(data_dir: Path, site: str, allowed: bool) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.put(
            "/api/profile", json={"name": "Sam"}, headers={"Sec-Fetch-Site": site}
        )
        assert (response.status_code == 200) is allowed
        if not allowed:
            assert response.status_code == 403


async def test_origin_must_match_host(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        same = await api.client.put("/api/profile", json={"name": "Sam"}, headers={"Origin": BASE_URL})
        assert same.status_code == 200
        for origin in ("http://evil.example", "null", "http://127.0.0.1:9999"):
            response = await api.client.put("/api/profile", json={"name": "X"}, headers={"Origin": origin})
            assert response.status_code == 403, origin
        assert (await api.client.get("/api/profile")).json()["name"] == "Sam"


async def test_every_response_is_nosniff_and_no_referrer(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.get("/api/rules")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"


# --------------------------------------------------------------------------------------------------
# session token
# --------------------------------------------------------------------------------------------------


async def test_token_login_sets_cookie_and_redirects(data_dir: Path, web_dist: Path) -> None:
    async with api_for(data_dir, token=TOKEN) as api:
        client = api.client
        assert (await client.get("/api/dashboard")).status_code == 401
        page = await client.get("/")
        assert page.status_code == 401 and "access link" in page.text
        assert not client.cookies

        wrong = await client.get("/?token=nope")
        assert wrong.status_code == 401 and "expired" in wrong.text

        login = await client.get(f"/?token={TOKEN}&tab=inbox")
        assert login.status_code == 303
        assert login.headers["location"] == "/?tab=inbox"
        cookie = login.headers["set-cookie"]
        assert cookie.startswith(f"ordnung_token_8765={TOKEN};")  # one cookie per port
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie.replace("Strict", "strict")

        assert (await client.get("/api/dashboard")).status_code == 200
        home = await client.get("/")
        assert home.status_code == 200 and '<div id="root">' in home.text


async def test_servers_on_two_ports_keep_their_own_sign_in(data_dir: Path, tmp_path: Path) -> None:
    """Browsers send a cookie to every port of a host: the demo and the real app (two servers on
    two ports) must not read, or overwrite, each other's session cookie."""
    async with api_for(data_dir, token=TOKEN) as real, api_for(tmp_path / "demo", token="demo-token") as demo:
        demo.client.base_url = httpx.URL("http://127.0.0.1:8766")
        assert (await real.client.get(f"/?token={TOKEN}")).status_code == 303
        assert (await demo.client.get("/?token=demo-token")).status_code == 303
        assert dict(real.client.cookies) == {"ordnung_token_8765": TOKEN}
        assert dict(demo.client.cookies) == {"ordnung_token_8766": "demo-token"}

        browser = {"Cookie": f"ordnung_token_8765={TOKEN}; ordnung_token_8766=demo-token"}  # sent to both
        swapped = {"Cookie": f"ordnung_token_8766={TOKEN}"}  # the real token under the demo's name
        async with client_for(real.app) as plain, client_for(demo.app) as plain_demo:
            plain_demo.base_url = httpx.URL("http://127.0.0.1:8766")
            assert (await plain.get("/api/profile", headers=browser)).status_code == 200
            assert (await plain_demo.get("/api/profile", headers=browser)).status_code == 200
            assert (await plain.get("/api/profile", headers=swapped)).status_code == 401


async def test_the_token_is_accepted_in_no_api_url(data_dir: Path) -> None:
    async with api_for(data_dir, token=TOKEN) as api:
        bearer = await api.client.get("/api/profile", headers={"Authorization": f"Bearer {TOKEN}"})
        assert bearer.status_code == 200
        wrong = await api.client.get("/api/profile", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401
        # it would sit in a calendar app's settings, and the token changes at every start anyway
        assert (await api.client.get(f"/api/calendar.ics?token={TOKEN}")).status_code == 401
        assert (await api.client.get(f"/api/profile?token={TOKEN}")).status_code == 401
        feed = await api.client.get("/api/calendar.ics", headers={"Authorization": f"Bearer {TOKEN}"})
        assert feed.status_code == 200 and feed.headers["content-type"].startswith("text/calendar")


async def test_health_without_token_is_minimal(data_dir: Path) -> None:
    async with api_for(data_dir, token=TOKEN) as api:
        public = await api.client.get("/api/health")
        assert public.status_code == 200
        assert public.json() == {"version": __version__, "authenticated": False}

        full = await api.client.get("/api/health", headers={"Authorization": f"Bearer {TOKEN}"})
        body = full.json()
        assert body["version"] == __version__
        assert body["data_dir"] == str(api.ctx.paths.data_dir)
        assert body["today"] == TODAY
        assert body["backend"] == "fake"
        assert body["demo"] is False
        assert body["claude"]["installed"] is False  # the fake backend never probes the CLI


# --------------------------------------------------------------------------------------------------
# web app and CSP
# --------------------------------------------------------------------------------------------------


def test_inline_script_hash_matches_the_theme_script() -> None:
    expected = "sha256-" + base64.b64encode(hashlib.sha256(THEME_SCRIPT.encode()).digest()).decode()
    html = f'<script>{THEME_SCRIPT}</script><script type="module" src="/a.js"></script>'
    assert inline_script_hashes(html) == [expected]
    policy = content_security_policy([expected])
    assert f"script-src 'self' '{expected}'" in policy
    for directive in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'none'", "base-uri 'none'"):
        assert directive in policy


async def test_spa_fallback_serves_index_with_csp(data_dir: Path, web_dist: Path) -> None:
    async with api_for(data_dir) as api:
        home = await api.client.get("/")
        deep = await api.client.get("/documents/doc_abc?tab=facts")
        for page in (home, deep):
            assert page.status_code == 200
            assert page.headers["content-type"].startswith("text/html")
            csp = page.headers["content-security-policy"]
            assert inline_script_hashes(page.text)[0] in csp
            assert "connect-src 'self'" in csp and "img-src 'self' data: blob:" in csp
            assert page.headers["x-frame-options"] == "DENY"

        asset = await api.client.get("/assets/index-abc.js")
        assert asset.status_code == 200
        assert "immutable" in asset.headers["cache-control"]
        assert "content-security-policy" not in asset.headers

        missing_api = await api.client.get("/api/does-not-exist")
        assert missing_api.status_code == 404
        assert missing_api.json() == {"detail": "Not Found"}


def test_static_files_never_leave_the_build(tmp_path: Path) -> None:
    dist = fake_web_dist(tmp_path)
    (tmp_path / "secret.txt").write_text("x")
    assert app_module._static_file(dist, "../secret.txt") is None
    assert app_module._static_file(dist, "assets/index-abc.js") == (dist / "assets/index-abc.js").resolve()
    assert app_module._static_file(dist, "") is None


async def test_friendly_page_when_the_web_app_is_not_built(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text("{}")
    (tmp_path / "Makefile").write_text("build-web:\n")
    monkeypatch.setattr(app_module, "web_dist_dir", lambda: tmp_path / "src" / "ordnung" / "web" / "dist")
    async with api_for(data_dir) as api:
        page = await api.client.get("/")
        assert page.status_code == 503
        assert "make build-web" in page.text  # a source checkout: build it
        assert "content-security-policy" in page.headers
        assert (await api.client.get("/api/rules")).status_code == 200


# --------------------------------------------------------------------------------------------------
# lifespan
# --------------------------------------------------------------------------------------------------


async def test_lifespan_starts_and_stops_background_work(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        async with lifespan(api.app):
            assert api.ctx.worker.running
            assert api.ctx.bus._loop is not None
        assert not api.ctx.worker.running


async def test_shutdown_waits_for_a_server_thread_still_running(data_dir: Path) -> None:
    """Integration finding: a cancelled tick's calendar sync thread could still read the Store after
    the lifespan ended (the Store closes then), and sqlite crashed once at a test's teardown."""
    order: list[str] = []
    release = threading.Event()

    def lingering() -> None:  # a cancelled task's thread, still running
        release.wait(5)
        order.append("thread done")

    async with api_for(data_dir) as api:
        loop = asyncio.get_running_loop()
        async with lifespan(api.app):
            thread = loop.run_in_executor(api.ctx.executor, lingering)
            loop.call_later(0.3, release.set)
        order.append("stopped")
        await thread
    assert order == ["thread done", "stopped"]


# --------------------------------------------------------------------------------------------------
# server.json
# --------------------------------------------------------------------------------------------------


def test_server_file_round_trip_is_private(data_dir: Path) -> None:
    token = generate_token()
    assert len(token) >= 40
    info = ServerInfo(port=8765, token=token, pid=os.getpid())
    path = write_server_info(data_dir, info)
    assert path == server_file(data_dir)
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_server_info(data_dir) == info
    assert running_server(data_dir) == info
    assert info.login_url == f"http://127.0.0.1:8765/?token={token}"
    assert info.api_url("/documents") == "http://127.0.0.1:8765/api/documents"
    assert info.auth_headers() == {"X-Ordnung-Client": "cli", "Authorization": f"Bearer {token}"}


def test_stale_and_foreign_server_files(data_dir: Path) -> None:
    assert read_server_info(data_dir) is None
    server_file(data_dir).write_text("not json")
    assert read_server_info(data_dir) is None
    dead = ServerInfo(port=1, token=None, pid=2**22 + 12345)
    write_server_info(data_dir, dead)
    assert not pid_alive(dead.pid)
    assert running_server(data_dir) is None
    assert not clear_server_info(data_dir, pid=os.getpid())  # belongs to another process
    assert clear_server_info(data_dir, pid=dead.pid)
    assert not clear_server_info(data_dir)


def test_advertise_removes_the_file_afterwards(data_dir: Path) -> None:
    with advertise(data_dir, port=9000, token=None) as info:
        assert running_server(data_dir) == info
        assert info.login_url == "http://127.0.0.1:9000/"
        assert info.auth_headers() == {"X-Ordnung-Client": "cli"}
    assert not server_file(data_dir).exists()


# --------------------------------------------------------------------------------------------------
# Claude status (zero-token, cached)
# --------------------------------------------------------------------------------------------------


async def test_claude_status_is_cached_and_skipped_for_other_backends() -> None:
    calls = 0

    async def probe() -> ClaudeStatus:
        nonlocal calls
        calls += 1
        return ClaudeStatus(installed=True, version="2.1.4", ok=True)

    cache = ClaudeStatusCache(probe, ttl_s=600)
    first = await cache.get("claude", uses_cli=True)
    second = await cache.get("claude", uses_cli=True)
    assert first == second and first.version == "2.1.4"
    assert calls == 1
    skipped = await cache.get("replay", uses_cli=False)
    assert skipped.installed is False and "replay" in (skipped.detail or "")
    assert calls == 1
    expired = ClaudeStatusCache(probe, ttl_s=0)
    await expired.get("claude", uses_cli=True)
    await expired.get("claude", uses_cli=True)
    assert calls == 3


async def test_probe_reports_a_missing_or_signed_out_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from ordnung.llm import claude_cli

    monkeypatch.setattr(claude_cli, "find_claude", lambda binary=None: None)
    missing = await probe_claude_cli()
    assert missing.installed is False and "not found" in (missing.detail or "")

    async def version(path: str | None = None) -> str:
        return "2.1.4 (Claude Code)"

    async def auth_status(path: str | None = None) -> dict[str, object]:
        return {"loggedIn": False}

    monkeypatch.setattr(claude_cli, "find_claude", lambda binary=None: "/usr/bin/claude")
    monkeypatch.setattr(claude_cli, "version", version)
    monkeypatch.setattr(claude_cli, "auth_status", auth_status)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    signed_out = await probe_claude_cli()
    assert signed_out.installed and signed_out.ok is False
    assert signed_out.version == "2.1.4 (Claude Code)" and "not signed in" in (signed_out.detail or "")


# --------------------------------------------------------------------------------------------------
# phone access: the computer's listener never takes a phone's sign-in, and no request can claim the
# phone listener (ordnung.phone)
# --------------------------------------------------------------------------------------------------


async def test_the_computer_ignores_phone_cookies(data_dir: Path) -> None:
    from phone_support import COOKIE, pair, phone_app, phone_client

    async with phone_app(data_dir) as (api, _net, _servers), phone_client(api) as phone:
        signed = await pair(api, phone)
        async with client_for(api.app) as computer:
            for name in (COOKIE, "__Host-ordnung_phone_8765", "ordnung_token_8765"):
                response = await computer.get("/api/profile", headers={"Cookie": f"{name}={signed['token']}"})
                assert response.status_code == 401, name
            health = await computer.get("/api/health", headers={"Cookie": f"{COOKIE}={signed['token']}"})
            assert health.json() == {"version": __version__, "authenticated": False}


async def test_a_request_cannot_claim_the_phone_listener(data_dir: Path) -> None:
    claims = {
        "ordnung.listener": "phone",
        "x-ordnung-listener": "phone",
        "ordnung.device": "phn_000000000000",
        "X-Forwarded-Proto": "https",
    }
    async with api_for(data_dir, token=TOKEN) as api:
        assert (await api.client.get("/api/profile", headers=claims)).status_code == 401
        signed_in = {**claims, "Authorization": f"Bearer {TOKEN}"}
        health = (await api.client.get("/api/health", headers=signed_in)).json()
        assert health["client"] == "computer" and health["data_dir"] == str(api.ctx.paths.data_dir)
        pairing = await api.client.post("/api/phone/pair", headers=signed_in, json={"code": "x", "name": "y"})
        assert (pairing.status_code, pairing.json()["code"]) == (404, "not_phone")
