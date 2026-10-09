"""``ordnung doctor``: zero-token checks against a fake ``claude`` executable on PATH."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers_secretary import add_doc
from ordnung import doctor
from ordnung.api import deps
from ordnung.config import Paths
from ordnung.db.migrate import latest_version
from ordnung.db.store import Store
from ordnung.doctor import DoctorReport, parse_version, run_doctor, run_doctor_sync
from ordnung.encryption import Encryption
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


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0, reason="root (and Windows: no folder modes) writes anywhere"
)
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
    found = {check.id: check for check in doctor.local_checks(data_dir)}
    assert found["database"] == healthy


def test_this_computers_checks_end_with_disk_backup_and_encryption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    with Store.open(Paths(data_dir)) as store:
        add_doc(store, "letter")
    monkeypatch.setattr(doctor.encryption, "disk_encryption", lambda path: Encryption("on", "LUKS"))
    ids = [check.id for check in doctor.local_checks(data_dir)]
    assert ids[-4:] == ["database", "disk", "backup", "disk_encryption"]
    # where Ordnung can't tell, there is no row at all
    monkeypatch.setattr(doctor.encryption, "disk_encryption", lambda path: None)
    assert [check.id for check in doctor.local_checks(data_dir)][-1] == "backup"


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


# --------------------------------------------------------------------------------------------------
# the last backup and disk encryption (warn only)
# --------------------------------------------------------------------------------------------------


def _folder_with_a_letter(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    with Store.open(Paths(data_dir)) as store:
        add_doc(store, "letter")
    return data_dir


def _note(data_dir: Path, kind: str, ts: str, data: str = "{}") -> None:
    with contextlib.closing(sqlite3.connect(Paths(data_dir).db)) as conn, conn:
        conn.execute(
            "INSERT INTO activity (ts, kind, message, data) VALUES (?, ?, ?, ?)", (ts, kind, "note", data)
        )


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_no_backup_row_without_a_database_or_in_the_demo(tmp_path: Path) -> None:
    assert doctor.backup_check(tmp_path / "nothing") is None
    data_dir = _folder_with_a_letter(tmp_path)
    (data_dir / ".ordnung-demo").write_text(json.dumps({"kind": "ordnung-demo", "version": "1"}))
    assert doctor.backup_check(data_dir) is None
    (data_dir / ".ordnung-demo").unlink()
    with Store.open(Paths(data_dir)) as store:
        store.save_settings(store.get_settings().model_copy(update={"demo": True}))
    assert doctor.backup_check(data_dir) is None


def test_nothing_to_back_up_yet(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    with Store.open(Paths(data_dir)):
        pass
    check = doctor.backup_check(data_dir)
    assert check is not None and check.id == "backup" and check.label == "Backup"
    assert check.status == "ok" and check.detail == "Nothing to back up yet"


def test_letters_and_no_backup_warn_with_the_command(tmp_path: Path) -> None:
    check = doctor.backup_check(_folder_with_a_letter(tmp_path))
    assert check is not None and check.status == "warn"
    assert check.detail == "Ordnung has no record of a backup made on this computer"
    assert check.fix is not None and "`ordnung backup --to FOLDER`" in check.fix
    assert "Settings → Data → Download encrypted backup" in check.fix and "can't see them" in check.fix


def test_a_recent_backup_is_fine_and_an_old_one_warns(tmp_path: Path) -> None:
    data_dir = _folder_with_a_letter(tmp_path)
    _note(data_dir, "backup.created", _iso(40))
    old = doctor.backup_check(data_dir)
    assert old is not None and old.status == "warn" and old.detail.startswith("Last backup 40 days ago (")
    assert old.fix is not None and "ordnung backup" in old.fix
    _note(data_dir, "backup.created", _iso(3))
    recent = doctor.backup_check(data_dir)
    assert recent is not None and recent.status == "ok" and recent.fix is None
    day = (datetime.now(UTC) - timedelta(days=3)).astimezone().date().isoformat()
    assert recent.detail == f"Last backup 3 days ago ({day})"


def test_the_backup_a_copy_was_restored_from_counts(tmp_path: Path) -> None:
    data_dir = _folder_with_a_letter(tmp_path)
    _note(data_dir, "backup.restored", _iso(0), json.dumps({"made_at": _iso(1)}))
    check = doctor.backup_check(data_dir)
    assert check is not None and check.status == "ok"
    assert check.detail.startswith("Last backup yesterday (")
    assert check.detail.endswith("), the one this copy was restored from")


def _connected(monkeypatch: pytest.MonkeyPatch, mode: str, saved_at: str | None) -> None:
    from ordnung import app_context
    from ordnung.sync import agent

    summary = SimpleNamespace(mode=mode, last_saved_at=saved_at)
    monkeypatch.setattr(app_context, "sync_connected", lambda paths: True)
    monkeypatch.setattr(agent, "load_engine", lambda: SimpleNamespace(local_summary=lambda paths: summary))


def test_hand_off_syncs_recent_save_counts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = _folder_with_a_letter(tmp_path)
    _connected(monkeypatch, "in_use", datetime.now().astimezone().isoformat(timespec="seconds"))
    check = doctor.backup_check(data_dir)
    assert check is not None and check.status == "ok"
    assert check.detail == "Hand-off sync saved an encrypted copy today"


def test_standing_by_the_computer_in_use_keeps_the_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = _folder_with_a_letter(tmp_path)
    _connected(monkeypatch, "standing_by", None)
    check = doctor.backup_check(data_dir)
    assert check is not None and check.status == "ok"
    assert check.detail == "Hand-off sync: the computer in use keeps an encrypted copy in the sync folder"


def test_a_sync_state_that_cant_be_read_is_no_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ordnung import app_context
    from ordnung.sync import agent

    def unreadable(paths: Paths) -> None:
        raise OSError("state.json is gone")

    monkeypatch.setattr(app_context, "sync_connected", lambda paths: True)
    monkeypatch.setattr(agent, "load_engine", lambda: SimpleNamespace(local_summary=unreadable))
    check = doctor.backup_check(_folder_with_a_letter(tmp_path))
    assert check is not None and check.status == "warn"


def test_a_database_that_cant_be_read_has_no_backup_row(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    Paths(data_dir).db.write_bytes(b"not a database at all" * 100)
    assert doctor.backup_check(data_dir) is None  # the database check says what is wrong


@pytest.mark.parametrize(
    ("found", "status", "detail", "fix"),
    [
        (Encryption("on", "FileVault"), "ok", "FileVault is on", None),
        (Encryption("on", "LUKS"), "ok", "The disk under the data folder is encrypted (LUKS)", None),
        (
            Encryption("on", "eCryptfs"),
            "ok",
            "The data folder is on an encrypted file system (eCryptfs)",
            None,
        ),
        (
            Encryption("off", "FileVault"),
            "warn",
            "FileVault is off: whoever has this Mac can read your letters, tax ID and IBANs.",
            "System Settings → Privacy & Security → FileVault",
        ),
        (
            Encryption("off", "LUKS"),
            "warn",
            "Ordnung found no disk encryption (LUKS) under the data folder.",
            "Encrypted another way (fscrypt, ZFS)? Then this is fine.",
        ),
        (
            Encryption("unknown", "FileVault", "`fdesetup status` didn't answer"),
            "warn",
            "Ordnung couldn't tell whether FileVault is on: `fdesetup status` didn't answer.",
            "System Settings → Privacy & Security → FileVault",
        ),
        (
            Encryption("unknown", "LUKS", "lsblk isn't installed"),
            "warn",
            "Ordnung couldn't tell whether the disk under the data folder is encrypted: lsblk isn't installed.",
            "Encrypted another way (fscrypt, ZFS)? Then this is fine.",
        ),
    ],
)
def test_disk_encryption_only_ever_warns(
    tmp_path: Path, found: Encryption, status: str, detail: str, fix: str | None
) -> None:
    check = doctor.disk_encryption_check(tmp_path, probe=lambda path: found)
    assert check is not None and check.id == "disk_encryption" and check.label == "Disk encryption"
    assert check.status == status and check.detail == detail
    if fix is None:
        assert check.fix is None
    else:
        assert check.fix is not None and fix in check.fix


def test_no_disk_encryption_row_where_ordnung_cant_tell(tmp_path: Path) -> None:
    assert doctor.disk_encryption_check(tmp_path, probe=lambda path: None) is None


def test_the_disk_encryption_probe_looks_at_the_data_folder(tmp_path: Path) -> None:
    seen: list[Path] = []

    def probe(path: Path) -> Encryption:
        seen.append(path)
        return Encryption("on", "LUKS")

    doctor.disk_encryption_check(tmp_path / "data", probe=probe)
    assert seen == [tmp_path / "data"]
