"""``ordnung doctor``: zero-token checks against a fake ``claude`` executable on PATH."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

from ordnung import doctor
from ordnung.api import deps
from ordnung.config import Paths
from ordnung.db.migrate import latest_version
from ordnung.db.store import Store
from ordnung.doctor import DoctorReport, parse_version, run_doctor, run_doctor_sync
from ordnung.llm.base import ClaudeNotInstalled, LLMRequest
from ordnung.llm.claude_cli import ClaudeCLIBackend, ProbeResult


def fake_claude(bin_dir: Path, *, version: str = "2.1.5 (Claude Code)", auth: object | None = None) -> Path:
    """A tiny ``claude`` that answers ``--version`` and ``auth status`` (and nothing else)."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    status = json.dumps(auth if auth is not None else {"loggedIn": True, "authMethod": "claude.ai"})
    script = bin_dir / "claude"
    script.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "--version" ]; then echo "{version}"; exit 0; fi\n'
        f'if [ "$1" = "auth" ] && [ "$2" = "status" ]; then echo \'{status}\'; exit 0; fi\n'
        'echo "unexpected call: $*" >&2; exit 2\n',
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


@pytest.fixture
def isolated_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """PATH = only a fresh bin folder (plus /bin for ``sh``); no API key, no binary override."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}/bin{os.pathsep}/usr/bin")
    monkeypatch.delenv("ORDNUNG_CLAUDE_BIN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return bin_dir


LLM_REQUEST = LLMRequest(purpose="doctor", prompt="Reply with exactly: OK", system="", model="haiku")


def statuses(report: DoctorReport) -> dict[str, str]:
    return {check.id: check.status for check in report.checks}


def test_parse_version() -> None:
    assert parse_version("2.1.3 (Claude Code)") == (2, 1, 3)
    assert parse_version("claude 10.0.12") == (10, 0, 12)
    assert parse_version("unknown") is None
    assert parse_version(None) is None


def test_a_healthy_setup(isolated_path: Path, data_dir: Path) -> None:
    script = fake_claude(isolated_path)
    report = run_doctor_sync(data_dir)
    found = statuses(report)
    assert found["claude_cli"] == "ok"
    assert found["claude_version"] == "ok"
    assert found["claude_auth"] == "ok"
    assert found["api_key"] == "ok"
    assert found["sqlite_fts"] == "ok"
    assert found["data_dir"] == "ok"
    assert found["fonts"] == "ok"
    assert "claude_probe" not in found  # zero tokens unless asked
    assert report.ok
    assert report.claude.installed and report.claude.ok
    assert report.claude.version == "2.1.5" and report.claude.path == str(script)
    assert report.claude.detail == "Signed in (claude.ai)"


def test_claude_missing(isolated_path: Path, data_dir: Path) -> None:
    report = run_doctor_sync(data_dir)
    missing = report.check("claude_cli")
    assert missing is not None and missing.status == "fail"
    assert missing.fix is not None and doctor.CLAUDE_CODE_URL in missing.fix
    assert report.check("claude_auth") is None
    assert not report.ok
    assert not report.claude.installed and report.claude.ok is False


def test_one_install_hint_everywhere(isolated_path: Path) -> None:
    """The doctor, the health check and a letter that couldn't be read name the same place to get
    Claude Code."""
    assert doctor.CLAUDE_CODE_URL in doctor.INSTALL_HINT
    assert doctor.CLAUDE_CODE_URL in deps._status_detail(False, None)
    with pytest.raises(ClaudeNotInstalled) as raised:
        ClaudeCLIBackend().build_args(LLM_REQUEST)
    assert doctor.CLAUDE_CODE_URL in str(raised.value)


def test_the_install_hint_names_the_installer_for_this_system() -> None:
    """The installer Anthropic's setup page recommends (no Node.js needed), and that the free plan won't do."""
    installer = "install.ps1" if sys.platform == "win32" else "install.sh"
    assert f"https://claude.ai/{installer}" in doctor.INSTALL_HINT
    assert "npm" not in doctor.INSTALL_HINT and "paid Claude plan" in doctor.INSTALL_HINT


def test_the_windows_install_hint_says_where_to_run_it() -> None:
    """Audit: ``irm … | iex`` is PowerShell's; pasted into cmd.exe it fails with "'irm' is not recognized"."""
    assert "`irm https://claude.ai/install.ps1 | iex` in PowerShell" in doctor.install_hint("win32")
    assert "PowerShell" not in doctor.install_hint("linux") + doctor.install_hint("darwin")
    assert doctor.install_hint() == doctor.INSTALL_HINT


def test_an_old_claude_fails_with_an_update_hint(isolated_path: Path, data_dir: Path) -> None:
    fake_claude(isolated_path, version="2.0.9 (Claude Code)")
    report = run_doctor_sync(data_dir)
    old = report.check("claude_version")
    assert old is not None and old.status == "fail"
    assert "2.1.0" in old.detail and old.fix is not None and "claude update" in old.fix
    assert report.claude.ok is False


@pytest.mark.parametrize(
    ("version", "ready"),
    [("2.0.9 (Claude Code)", False), ("2.1.0 (Claude Code)", True), ("2.10.3 (Claude Code)", True)],
)
async def test_the_app_holds_claude_to_the_doctors_minimum(
    isolated_path: Path, version: str, ready: bool
) -> None:
    """The app's zero-token status check and ``ordnung doctor`` (also behind "Run check") count the same
    Claude Code as too old: it is not ready (letters wait), and the status names the version needed and the
    update command."""
    fake_claude(isolated_path, version=version)
    app, doctors = await deps.probe_claude_cli(), await doctor.claude_status()
    for status in (app, doctors):
        assert status.installed and status.ok is ready and deps.claude_ready(status) is ready
        assert status.needs_version == (None if ready else "2.1.0")
    if not ready:
        assert app.detail is not None
        assert "2.0.9" in app.detail and "2.1.0 or newer" in app.detail and "“claude update”" in app.detail


async def test_a_version_nobody_can_read_counts_as_the_doctor_says(
    isolated_path: Path, data_dir: Path
) -> None:
    """``ordnung doctor`` only warns about a ``claude --version`` it can't read; the app's status check
    doesn't hold letters back over it either."""
    fake_claude(isolated_path, version="nightly (Claude Code)")
    report = await run_doctor(data_dir)
    assert statuses(report)["claude_version"] == "warn" and report.claude.ok is True
    status = await deps.probe_claude_cli()
    assert status.ok is True and status.needs_version is None and deps.claude_ready(status)


def test_signed_out(isolated_path: Path, data_dir: Path) -> None:
    fake_claude(isolated_path, auth={"loggedIn": False})
    report = run_doctor_sync(data_dir)
    auth = report.check("claude_auth")
    assert auth is not None and auth.status == "fail"
    assert auth.fix is not None and "claude auth login" in auth.fix
    assert not report.ok


def test_unreadable_auth_status_is_a_warning(isolated_path: Path, data_dir: Path) -> None:
    fake_claude(isolated_path, auth=["not", "an", "object"])
    report = run_doctor_sync(data_dir)
    assert statuses(report)["claude_auth"] == "warn"
    assert report.ok


def test_an_api_key_in_the_environment_is_flagged(
    isolated_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_claude(isolated_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    report = run_doctor_sync(data_dir)
    key = report.check("api_key")
    assert key is not None and key.status == "warn"
    assert "bill" in key.detail and key.fix is not None and "unset ANTHROPIC_API_KEY" in key.fix
    assert report.ok  # a warning, not a failure


async def test_the_probe_is_one_live_call_only_when_asked(
    isolated_path: Path, data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live call runs on the model the caller names (the one every call runs on) and the row says
    which; when it fails, the fix points at that model after the sign-in — a bare probe's at the
    sign-in alone."""
    fake_claude(isolated_path)
    calls: list[str | None] = []
    answer = {"ok": True}

    async def probe(
        binary: str | None = None, timeout_s: float = 60, *, model: str | None = None
    ) -> ProbeResult:
        calls.append(model)
        return ProbeResult(answer["ok"], "OK" if answer["ok"] else "No such model", model or "haiku")

    monkeypatch.setattr(doctor.claude_cli, "probe", probe)
    report = await run_doctor(data_dir, probe=True, model="claude-opus-5-5")
    probe_check = report.check("claude_probe")
    assert probe_check is not None and probe_check.status == "ok" and probe_check.fix is None
    assert probe_check.detail == "OK (on claude-opus-5-5)"
    assert calls == ["claude-opus-5-5"]
    await run_doctor(data_dir)
    assert len(calls) == 1

    answer["ok"] = False
    failed = (await run_doctor(data_dir, probe=True, model="claude-opus-5-5")).check("claude_probe")
    assert failed is not None and failed.status == "fail"
    assert failed.detail == "No such model (on claude-opus-5-5)"
    assert failed.fix is not None and failed.fix.startswith(doctor.LOGIN_HINT)
    assert "`claude-opus-5-5`" in failed.fix and "Settings → Claude connection" in failed.fix
    bare = (await run_doctor(data_dir, probe=True)).check("claude_probe")
    assert bare is not None and bare.fix == doctor.LOGIN_HINT and bare.detail == "No such model (on haiku)"


def test_a_data_folder_that_does_not_exist_yet_is_fine(tmp_path: Path) -> None:
    check = doctor.data_dir_check(tmp_path / "new" / "data")
    assert check.status == "ok" and "will be created" in check.detail
    assert not (tmp_path / "new").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_a_read_only_data_folder_fails(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        check = doctor.data_dir_check(locked)
    finally:
        locked.chmod(0o700)
    assert check.status == "fail" and check.fix is not None


def test_the_database_check(tmp_path: Path) -> None:
    """Opened read-only: none yet is fine, a healthy one names its schema version."""
    data_dir = tmp_path / "data"
    none_yet = doctor.database_check(data_dir)
    assert none_yet.status == "ok" and "None yet" in none_yet.detail and not data_dir.exists()
    with Store.open(Paths(data_dir)) as store:
        store.set_meta("probe", "1")
    healthy = doctor.database_check(data_dir)
    assert healthy.status == "ok" and healthy.detail == f"Schema version {latest_version()}"
    assert doctor.local_checks(data_dir)[-2] == healthy


def test_a_damaged_database_points_to_a_backup(tmp_path: Path) -> None:
    """``serve`` sends a damaged database to the doctor: it says so, and how to restore a backup."""
    data_dir = tmp_path / "data"
    with Store.open(Paths(data_dir)) as store:
        for n in range(300):
            store.set_meta(f"key-{n}", "x" * 200)
    db = Paths(data_dir).db
    db.write_bytes(db.read_bytes()[: db.stat().st_size // 3])
    check = doctor.database_check(data_dir)
    assert check.status == "fail" and str(db) in check.detail
    assert check.fix is not None and "ordnung restore FILE --force" in check.fix


def test_a_database_from_a_newer_ordnung(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    with Store.open(Paths(data_dir)):
        pass
    with contextlib.closing(sqlite3.connect(Paths(data_dir).db)) as conn, conn:
        conn.execute(f"PRAGMA user_version = {latest_version() + 1}")
    check = doctor.database_check(data_dir)
    assert check.status == "fail" and "newer version of Ordnung" in check.detail
    assert check.fix is not None and check.fix.startswith("Update Ordnung.") and "--force" in check.fix


def test_low_disk_space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    usage = type("Usage", (), {"free": 10 * 1024 * 1024})
    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda path: usage)
    assert doctor.disk_check(tmp_path).status == "fail"
    usage.free = 500 * 1024 * 1024
    assert doctor.disk_check(tmp_path).status == "warn"


def test_missing_sqlite_features_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_: str) -> sqlite3.Connection:
        raise sqlite3.OperationalError("no such module: fts5")

    monkeypatch.setattr(doctor.sqlite3, "connect", broken)
    check = doctor.sqlite_check()
    assert check.status == "fail" and "fts5" in check.detail


def test_web_ui_missing_is_a_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """In a source checkout the fix is to build the web app; an installed package is reinstalled."""
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package.json").write_text("{}")
    (tmp_path / "Makefile").write_text("build-web:\n")
    monkeypatch.setattr(doctor, "web_dist_dir", lambda: tmp_path / "src" / "ordnung" / "web" / "dist")
    check = doctor.web_ui_check()
    assert check.status == "warn" and check.fix is not None and "build-web" in check.fix
    monkeypatch.setattr(
        doctor, "web_dist_dir", lambda: tmp_path / "venv" / "site-packages" / "ordnung" / "web" / "dist"
    )
    check = doctor.web_ui_check()
    assert check.status == "warn" and check.fix is not None and "Reinstall Ordnung" in check.fix


async def test_claude_status_for_the_health_endpoint(isolated_path: Path) -> None:
    fake_claude(isolated_path)
    status = await doctor.claude_status()
    assert status.installed and status.ok and status.version == "2.1.5"
