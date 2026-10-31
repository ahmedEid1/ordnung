"""Settings → Claude → *Run check* (``GET /api/health?probe=1``) when the ``claude`` program dies at start.

The check exists for a broken install, so it must answer with the failed row, never a server error.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ordnung.api.routes import system
from test_api_support import api_for
from test_doctor import broken_claude

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the fake CLI is started through /bin/sh")


async def test_run_check_answers_with_the_failed_live_call(
    data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, claude_exits_first: None
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    broken_claude(bin_dir, tmp_path, monkeypatch)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/bin{os.pathsep}/usr/bin")
    monkeypatch.setattr(system, "backend_uses_cli", lambda ctx: True)
    async with api_for(data_dir) as api:
        response = await api.client.get("/api/health", params={"probe": "1"})
        assert response.status_code == 200, response.text
        body = response.json()
        checks = {check["id"]: check for check in body["checks"]}
        probe = checks["claude_probe"]
        assert probe["status"] == "fail" and probe["label"] == "Live test call"
        assert probe["detail"].startswith("env: node: No such file or directory (on ")
        expected = {"claude_cli", "claude_version", "claude_auth", "sqlite_fts", "data_dir", "disk"}
        assert expected <= set(checks)
        assert body["claude"]["ok"] is False and body["claude"]["detail"] == probe["detail"]
        # the fresh status is the one the app shows from now on
        assert (await api.client.get("/api/health")).json()["claude"]["ok"] is False
