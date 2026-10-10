"""The API behind Settings → Reminders (desktop notification preview and test, start at login) and
Settings → Data (the encrypted backup download), and the new settings fields."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from fakes import use_fast_keys
from helpers_secretary import TODAY, seed_ledger
from ordnung import autostart, clock, shortcut
from ordnung import backup as backups
from ordnung.api.routes import backup as backup_route
from ordnung.api.routes import reminders
from ordnung.backup.archive import BackupStream, check_backup
from ordnung.backup.container import DamagedBackup
from ordnung.notify import desktop
from ordnung.notify.desktop import Notification, SendResult
from test_api_support import api_for, client_for

PASS = "orbit velvet canyon maple thunder"


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def fast_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cheap scrypt for the backups made here (the real costs: ``tests/test_backup_container.py``)."""
    use_fast_keys(monkeypatch)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A Linux desktop with notify-send and an empty home folder."""
    folder = tmp_path / "home"
    folder.mkdir()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: folder))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(
        desktop.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "notify-send" else None
    )
    return folder


@pytest.fixture
def shown(monkeypatch: pytest.MonkeyPatch) -> list[Notification]:
    notes: list[Notification] = []

    def fake_send(note: Notification, **_kwargs: Any) -> SendResult:
        notes.append(note)
        return SendResult(sent=True, mechanism="notify-send")

    monkeypatch.setattr(desktop, "send", fake_send)
    return notes


# --------------------------------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------------------------------


async def test_the_new_settings_default_off_and_are_validated(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        settings = (await api.client.get("/api/settings")).json()
        assert settings["desktop_notifications"] == "off" and settings["desktop_notify_time"] == "08:00"
        saved = await api.client.put(
            "/api/settings", json={"desktop_notifications": "discreet", "desktop_notify_time": "07:45"}
        )
        assert saved.status_code == 200, saved.text
        assert (
            saved.json()["desktop_notifications"] == "discreet"
            and saved.json()["desktop_notify_time"] == "07:45"
        )
        for bad in (
            {"desktop_notifications": "loud"},
            {"desktop_notify_time": "7:45"},
            {"desktop_notify_time": "24:00"},
            {"desktop_notify_time": "07:45 "},
        ):
            refused = await api.client.put("/api/settings", json=bad)
            assert refused.status_code == 422, bad
        assert api.ctx.store.get_settings().desktop_notify_time == "07:45"


# --------------------------------------------------------------------------------------------------
# desktop notifications
# --------------------------------------------------------------------------------------------------


async def test_the_status_previews_both_modes(data_dir: Path, home: Path) -> None:
    async with api_for(data_dir) as api:
        seed_ledger(api.ctx.store)
        body = (await api.client.get("/api/reminders/desktop")).json()
        assert body["system"] == "linux" and body["tool"] == "notify-send" and body["missing"] is None
        assert body["preview"]["discreet"] == {"title": "Ordnung", "body": "1 overdue · 3 due this week"}
        assert body["preview"]["full"]["title"] == "Ordnung · 1 overdue · 3 due this week"
        assert body["preview"]["full"]["body"].startswith("Return library books — overdue")
        assert body["last_shown_on"] is None and body["last_failure"] is None and not body["demo"]
        assert body["autostart"] == {
            "enabled": False,
            "kind": "systemd user service",
            "path": str(home / ".config" / "systemd" / "user" / "ordnung.service"),
            "points_here": False,
            # this data folder is not the default one: the command sets up this one
            "command": f"ordnung autostart enable --data-dir {data_dir}",
        }
        assert body["shortcut"] == {
            "added": False,
            "kind": "app menu entry",
            "path": str(home / ".local" / "share" / "applications" / "ordnung.desktop"),
            "points_here": False,
            "current": False,
            "foreign": False,
            "command": f"ordnung shortcut --data-dir {data_dir}",
        }


async def test_the_status_without_the_preview_builds_no_agenda(
    data_dir: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``?preview=false`` — the check for background problems on every page — leaves the texts out,
    and with them the agenda they are written from."""
    async with api_for(data_dir) as api:
        seed_ledger(api.ctx.store)
        full = (await api.client.get("/api/reminders/desktop")).json()

        def no_agenda(*_: object) -> None:
            raise AssertionError("the agenda was built")

        monkeypatch.setattr(reminders.desktop, "preview", no_agenda)
        body = (await api.client.get("/api/reminders/desktop", params={"preview": "false"})).json()
        assert body["preview"] == {"discreet": None, "full": None}
        assert {key: value for key, value in body.items() if key != "preview"} == {
            key: value for key, value in full.items() if key != "preview"
        }


def test_the_start_at_login_command_names_a_folder_that_isnt_the_default(tmp_path: Path) -> None:
    default = tmp_path / "default"
    assert reminders.autostart_command(default, default=default) == "ordnung autostart enable"
    odd = tmp_path / "my data"
    assert reminders.autostart_command(odd, default=default) == f"ordnung autostart enable --data-dir '{odd}'"


async def test_the_demo_offers_no_start_at_login_or_shortcut_command(data_dir: Path, home: Path) -> None:
    async with api_for(data_dir, demo=True) as api:
        body = (await api.client.get("/api/reminders/desktop")).json()
        assert body["demo"] and body["autostart"]["command"] is None
        assert body["shortcut"]["command"] is None and not body["shortcut"]["added"]


@pytest.mark.parametrize(
    ("platform", "kind"),
    [
        ("linux", "app menu entry"),
        ("darwin", "app in your Applications folder"),
        ("win32", "Start menu shortcut"),
    ],
)
async def test_the_shortcut_is_named_as_this_system_names_it(
    data_dir: Path, home: Path, monkeypatch: pytest.MonkeyPatch, platform: str, kind: str
) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    async with api_for(data_dir) as api:
        body = (await api.client.get("/api/reminders/desktop", params={"preview": "false"})).json()
        assert body["shortcut"]["kind"] == kind


async def test_the_status_says_why_the_last_notification_wasnt_shown(data_dir: Path, home: Path) -> None:
    async with api_for(data_dir) as api:
        seed_ledger(api.ctx.store)
        store = api.ctx.store
        store.save_settings(store.get_settings().model_copy(update={"desktop_notifications": "discreet"}))

        def fails(_note: Notification) -> SendResult:
            return SendResult(sent=False, mechanism="notify-send", detail="notify-send failed (exit code 1).")

        desktop.morning_notification(store, TODAY, desktop.DEFAULT_TIME, sender=fails)
        body = (await api.client.get("/api/reminders/desktop")).json()
        assert body["last_failure"] == "notify-send failed (exit code 1)."
        assert body["last_failure_on"] == TODAY.isoformat() and body["last_shown_on"] is None


async def test_the_status_says_when_no_tool_is_found_and_nothing_is_due(
    data_dir: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(desktop.shutil, "which", lambda _name: None)
    async with api_for(data_dir) as api:
        body = (await api.client.get("/api/reminders/desktop")).json()
        assert body["tool"] is None and "notify-send" in body["missing"]
        assert body["preview"] == {"discreet": None, "full": None}


async def test_the_status_knows_whether_autostart_starts_this_folder(data_dir: Path, home: Path) -> None:
    async with api_for(data_dir) as api:
        autostart.enable(autostart.plan(data_dir, env={"PATH": "/usr/bin"}, home=home))
        body = (await api.client.get("/api/reminders/desktop")).json()
        assert body["autostart"]["enabled"] and body["autostart"]["points_here"]
        autostart.enable(autostart.plan(data_dir.parent / "other", env={"PATH": "/usr/bin"}, home=home))
        body = (await api.client.get("/api/reminders/desktop")).json()
        assert body["autostart"]["enabled"] and not body["autostart"]["points_here"]


def write_foreign_launcher(path: str) -> None:
    Path(path).write_text("[Desktop Entry]\nName=Ordnung\n", encoding="utf-8")


async def test_the_status_knows_whether_the_shortcut_opens_this_folder(data_dir: Path, home: Path) -> None:
    async with api_for(data_dir) as api:
        shortcut.write(shortcut.plan(data_dir, env={"PATH": "/usr/bin"}, home=home))
        body = (await api.client.get("/api/reminders/desktop", params={"preview": "false"})).json()
        assert body["shortcut"]["added"] and body["shortcut"]["points_here"] and body["shortcut"]["current"]
        assert not body["shortcut"]["foreign"]
        assert body["shortcut"]["path"] == str(home / ".local" / "share" / "applications" / "ordnung.desktop")
        shortcut.write(shortcut.plan(data_dir.parent / "other", env={"PATH": "/usr/bin"}, home=home))
        body = (await api.client.get("/api/reminders/desktop")).json()
        assert body["shortcut"]["added"] and not body["shortcut"]["points_here"]
        # a launcher Ordnung didn't write isn't reported as Ordnung's, but as one in the way
        write_foreign_launcher(body["shortcut"]["path"])
        body = (await api.client.get("/api/reminders/desktop")).json()
        assert not body["shortcut"]["added"] and not body["shortcut"]["points_here"]
        assert body["shortcut"]["foreign"] and not body["shortcut"]["current"]


async def test_a_launcher_that_runs_another_installation_is_not_current(data_dir: Path, home: Path) -> None:
    """Ordnung reinstalled elsewhere and the old Python gone: the launcher opens nothing, and Settings says to
    run the command again."""
    gone = str(home / "old-venv" / "bin" / "python")
    async with api_for(data_dir) as api:
        shortcut.write(shortcut.plan(data_dir, env={"PATH": "/usr/bin"}, home=home, python=gone))
        found = (await api.client.get("/api/reminders/desktop", params={"preview": "false"})).json()[
            "shortcut"
        ]
        assert found["added"] and found["points_here"] and not found["current"] and not found["foreign"]
        shortcut.write(shortcut.plan(data_dir, env={"PATH": "/usr/bin"}, home=home))
        found = (await api.client.get("/api/reminders/desktop", params={"preview": "false"})).json()[
            "shortcut"
        ]
        assert found["current"]


async def test_a_launcher_that_can_t_be_read_never_fails_the_status(
    data_dir: Path, home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    info = home / "Applications" / "Ordnung.app" / "Contents" / "Info.plist"
    info.parent.mkdir(parents=True)
    info.write_bytes(b"<?xml version='1.0'?><plist version='1.0'><dict><key>CFBundleName</key>")  # cut short
    async with api_for(data_dir) as api:
        answer = await api.client.get("/api/reminders/desktop", params={"preview": "false"})
        assert answer.status_code == 200 and answer.json()["shortcut"]["foreign"]

        def unreadable(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("no home folder")

        monkeypatch.setattr(shortcut, "state", unreadable)
        answer = await api.client.get("/api/reminders/desktop", params={"preview": "false"})
        assert answer.status_code == 200 and not answer.json()["shortcut"]["added"]
        assert answer.json()["autostart"]["command"]  # the rest of the status is all there


def test_the_shortcut_command_names_a_folder_that_isnt_the_default(tmp_path: Path) -> None:
    default = tmp_path / "ordnung"
    assert reminders.shortcut_command(default, default=default) == "ordnung shortcut"
    odd = tmp_path / "my letters"
    assert reminders.shortcut_command(odd, default=default) == f"ordnung shortcut --data-dir '{odd}'"


async def test_the_test_notification_shows_today_or_a_sample(
    data_dir: Path, home: Path, shown: list[Notification]
) -> None:
    async with api_for(data_dir) as api:
        sample = (await api.client.post("/api/reminders/desktop/test", json={})).json()
        assert sample["shown"] and sample["notification"] == {
            "title": reminders.SAMPLE.title,
            "body": reminders.SAMPLE.body,
        }
        seed_ledger(api.ctx.store)
        full = (await api.client.post("/api/reminders/desktop/test", json={"mode": "full"})).json()
        assert full["notification"]["body"].startswith("Return library books")
        discreet = (await api.client.post("/api/reminders/desktop/test", json={"mode": "discreet"})).json()
        assert discreet["notification"] == {"title": "Ordnung", "body": "1 overdue · 3 due this week"}
        assert [note.body for note in shown][1:] == [
            full["notification"]["body"],
            "1 overdue · 3 due this week",
        ]
        # testing never uses the day up
        assert api.ctx.store.get_meta(desktop.LAST_SHOWN_KEY) is None
        for bad in ({"mode": "off"}, {"mode": "loud"}, {"mode": "full", "extra": 1}):
            assert (await api.client.post("/api/reminders/desktop/test", json=bad)).status_code == 422


async def test_a_failed_test_says_why(data_dir: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(desktop.shutil, "which", lambda _name: None)
    async with api_for(data_dir) as api:
        body = (await api.client.post("/api/reminders/desktop/test", json={})).json()
        assert body == {
            "shown": False,
            "tool": None,
            "notification": {"title": reminders.SAMPLE.title, "body": reminders.SAMPLE.body},
            "detail": desktop.MISSING_TOOL["linux"],
        }


async def test_writes_need_the_client_header(data_dir: Path, home: Path, shown: list[Notification]) -> None:
    async with api_for(data_dir) as api:
        async with client_for(api.app, **{"X-Ordnung-Client": ""}) as bare:
            bare.headers.pop("X-Ordnung-Client", None)
            assert (await bare.post("/api/reminders/desktop/test", json={})).status_code == 403
            assert (await bare.post("/api/backup", json={"passphrase": PASS})).status_code == 403
        assert shown == []


# --------------------------------------------------------------------------------------------------
# the backup download
# --------------------------------------------------------------------------------------------------


async def test_backup_info(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        seed_ledger(api.ctx.store)
        (api.ctx.paths.files / "a.pdf").write_bytes(b"%PDF" * 100)
        info = (await api.client.get("/api/backup")).json()
        counts = api.ctx.store.counts()
        assert info["letters"] == counts["documents"] > 0
        api.ctx.store.trash_document(api.ctx.store.list_documents()[0].id)
        # the trash is in the backup too: the same count `ordnung backup` prints
        info = (await api.client.get("/api/backup")).json()
        after = api.ctx.store.counts()
        assert info["letters"] == counts["documents"] == after["documents"] + after["trashed_documents"]
        assert info["files"] == 1 and info["bytes"] > 400
        assert info["file_name"] == "ordnung-backup-2026-09-28.ordnung-backup"
        assert info["min_passphrase"] == 12 and info["format_version"] == 1
        assert info["left_out"] == []
        # letters and no backup made yet: time for one
        copy = info["last_copy"]
        assert copy["last_backup_at"] is None and copy["days"] is None
        assert copy["due"] is True and copy["due_after_days"] == 30
        assert copy["sync_saved_at"] is None and copy["sync_standing_by"] is False
        # a link is never followed — and Settings says what that leaves out
        (api.ctx.paths.drafts / "elsewhere").symlink_to(data_dir.parent)
        assert (await api.client.get("/api/backup")).json()["left_out"] == ["drafts/elsewhere"]


async def test_the_backup_download_restores(data_dir: Path, tmp_path: Path, fast_keys: None) -> None:
    async with api_for(data_dir) as api:
        seed_ledger(api.ctx.store)
        (api.ctx.paths.files / "ab").mkdir()
        (api.ctx.paths.files / "ab" / "letter.pdf").write_bytes(b"%PDF-1.7 letter")
        response = await api.client.post("/api/backup", json={"passphrase": PASS})
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"
        assert (
            response.headers["content-disposition"]
            == 'attachment; filename="ordnung-backup-2026-09-28.ordnung-backup"'
        )
        assert response.headers["cache-control"] == "no-store"
        saved = tmp_path / "download.ordnung-backup"
        saved.write_bytes(response.content)
        contents = check_backup(saved, PASS)
        assert contents.manifest.tables["documents"] == api.ctx.store.counts()[
            "documents"
        ] + api.ctx.store.counts().get("trashed", 0)
        assert [entry.path for entry in contents.manifest.files] == ["files/ab/letter.pdf"]
        logged = [a for a in api.ctx.store.list_activity(limit=10) if a.kind == "backup.created"]
        assert logged and "letters" in logged[0].message
        assert logged[0].message == backups.backup_message(contents)
        # Settings now says when: today, and no reminder
        copy = (await api.client.get("/api/backup")).json()["last_copy"]
        assert copy["last_backup_at"] == logged[0].ts and copy["last_backup_restored"] is False
        assert copy["days"] == 0 and copy["due"] is False


async def test_the_demo_never_says_a_backup_is_due(data_dir: Path) -> None:
    async with api_for(data_dir, demo=True) as api:
        seed_ledger(api.ctx.store)
        copy = (await api.client.get("/api/backup")).json()["last_copy"]
        assert copy["last_backup_at"] is None and copy["due"] is False


async def test_hand_off_syncs_recent_save_counts_as_a_copy(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        seed_ledger(api.ctx.store)
        agent = api.app.state.ordnung.sync
        saved = datetime.now().astimezone().isoformat(timespec="seconds")
        agent.connected, agent.mode = True, "in_use"
        agent.summary = SimpleNamespace(last_saved_at=saved)
        copy = (await api.client.get("/api/backup")).json()["last_copy"]
        assert copy["sync_saved_at"] == saved and copy["sync_standing_by"] is False
        assert copy["last_backup_at"] is None and copy["due"] is False
        agent.mode, agent.summary = "standing_by", SimpleNamespace(last_saved_at=None)
        copy = (await api.client.get("/api/backup")).json()["last_copy"]
        assert copy["sync_standing_by"] is True and copy["due"] is False
        agent.connected = False  # disconnected: its old saves count no more
        assert (await api.client.get("/api/backup")).json()["last_copy"]["due"] is True


async def test_a_weak_passphrase_is_refused_without_echoing_it(
    data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    async with api_for(data_dir) as api:
        for secret in ("hunter2", "x" * 2000):
            response = await api.client.post("/api/backup", json={"passphrase": secret})
            assert response.status_code == 422
            assert secret not in response.text and "characters" in response.json()["detail"]
        wrong_type = await api.client.post("/api/backup", json={"passphrase": 12345678901234})
        assert wrong_type.status_code == 422
        assert (await api.client.post("/api/backup", json={})).status_code == 422
    assert "hunter2" not in caplog.text


async def test_a_guessable_passphrase_is_refused_with_the_rule(
    data_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A new backup's passphrase meets the rule of a new sync folder: long enough isn't enough."""
    caplog.set_level(logging.DEBUG)
    async with api_for(data_dir) as api:
        for secret in ("a long enough passphrase", "correct horse battery staple"):
            response = await api.client.post("/api/backup", json={"passphrase": secret})
            assert response.status_code == 422
            assert response.json()["detail"] == backups.WEAK_PASSPHRASE_MESSAGE
            assert secret not in response.text
        assert not [a for a in api.ctx.store.list_activity(limit=10) if a.kind == "backup.created"]
    assert "a long enough passphrase" not in caplog.text


async def test_a_client_that_goes_away_stops_the_backup(
    data_dir: Path, tmp_path: Path, fast_keys: None
) -> None:
    """The response body is a generator: closed early (the browser went away), nothing is sealed and
    nothing is logged as made; what was sent is refused on restore."""
    async with api_for(data_dir) as api:
        seed_ledger(api.ctx.store)
        for index in range(5):
            (api.ctx.paths.derived / f"page-{index}.jpg").write_bytes(bytes(200_000))
        stream = BackupStream(api.ctx.paths.data_dir, PASS)
        body = backup_route._stream(api.ctx, stream)
        received = next(body) + next(body)
        body.close()
        assert stream.contents is None
        assert not [a for a in api.ctx.store.list_activity(limit=10) if a.kind == "backup.created"]
        partial = tmp_path / "partial.ordnung-backup"
        partial.write_bytes(received)
        with pytest.raises(DamagedBackup):
            check_backup(partial, PASS)


async def test_backup_answers_over_http_only_to_this_computer(data_dir: Path) -> None:
    async with api_for(data_dir, token="t0ken") as api:
        transport = httpx.ASGITransport(app=api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://evil.example") as other:
            refused = await other.post(
                "/api/backup", json={"passphrase": PASS}, headers={"X-Ordnung-Client": "x"}
            )
            assert refused.status_code in (400, 403)
