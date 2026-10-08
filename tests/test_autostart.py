"""``ordnung autostart``: the entry per operating system (written into a temporary home), quoting of
awkward paths, rewriting and removing only Ordnung's own entry, the status, and the commands."""

from __future__ import annotations

import os
import plistlib
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from ordnung import autostart
from ordnung.autostart import (
    LAUNCH_LABEL,
    STARTUP_NAME,
    TELEMETRY_OPT_OUT,
    UNIT_NAME,
    AutostartError,
    cmd_quote,
    disable,
    enable,
    entry_argv,
    plan,
    state,
    systemd_quote,
    systemd_unquote,
)
from ordnung.cli import app

PY = "/opt/ordnung/venv/bin/python3"
PATH_ENV = "/home/sam/.local/bin:/usr/local/bin:/usr/bin:/bin"
runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


def linux_env(home: Path) -> dict[str, str]:
    return {"PATH": PATH_ENV, "HOME": str(home)}


# --------------------------------------------------------------------------------------------------
# Linux
# --------------------------------------------------------------------------------------------------


def test_linux_writes_a_systemd_user_unit_and_the_enable_link(tmp_path: Path) -> None:
    home = tmp_path / "home"
    entry = plan(
        Path("/home/sam/.local/share/ordnung"), platform="linux", env=linux_env(home), home=home, python=PY
    )
    assert entry.path == home / ".config" / "systemd" / "user" / UNIT_NAME
    assert entry.link == home / ".config" / "systemd" / "user" / "default.target.wants" / UNIT_NAME
    assert enable(entry) == "added"
    text = entry.path.read_text()
    assert text == entry.content
    lines = text.splitlines()
    assert lines[0].startswith("# Written by `ordnung autostart enable`")
    assert (
        'ExecStart="/opt/ordnung/venv/bin/python3" "-m" "ordnung" "--data-dir" '
        '"/home/sam/.local/share/ordnung" "serve" "--no-browser"'
    ) in lines
    assert f'Environment="PATH={PATH_ENV}"' in lines
    for line in (
        "Restart=on-failure",
        "RestartSec=30",
        "StandardOutput=null",
        "StandardError=journal",
        "WantedBy=default.target",
    ):
        assert line in lines
    assert entry.link.is_symlink() and entry.link.readlink() == entry.path
    if os.name == "posix":  # Windows has no such modes
        assert entry.path.stat().st_mode & 0o777 == 0o600
    assert entry.start_now == "systemctl --user daemon-reload && systemctl --user restart ordnung.service"
    assert entry.stop_now == "systemctl --user stop ordnung.service"


def test_linux_honours_xdg_config_home_and_a_port(tmp_path: Path) -> None:
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "PATH": PATH_ENV}
    entry = plan(Path("/data"), port=8899, platform="linux", env=env, home=tmp_path, python=PY)
    assert entry.path == tmp_path / "cfg" / "systemd" / "user" / UNIT_NAME
    assert entry.argv[-2:] == ("--port", "8899")
    default_port = plan(Path("/data"), port=8765, platform="linux", env=env, home=tmp_path, python=PY)
    assert "--port" not in default_port.argv


def test_other_unixes_use_the_systemd_layout(tmp_path: Path) -> None:
    assert plan(Path("/d"), platform="freebsd14", env={}, home=tmp_path, python=PY).system == "linux"


@pytest.mark.parametrize(
    "path",
    [
        "/home/sam/My Documents/ordnung",
        "/home/sam/100%/ordnung",
        "/home/sam/$HOME/ordnung",
        '/home/sam/"quoted"/ordnung',
        "/home/sam/back\\slash/ordnung",
        "/home/sam/Ordnung – Größe/ordnung",
    ],
)
def test_systemd_quoting_round_trips_awkward_paths(tmp_path: Path, path: str) -> None:
    entry = plan(Path(path), platform="linux", env={"PATH": "/usr/bin"}, home=tmp_path, python=PY)
    exec_line = next(line for line in entry.content.splitlines() if line.startswith("ExecStart="))
    assert systemd_unquote(exec_line.removeprefix("ExecStart=")) == list(entry.argv)
    assert "%" not in exec_line.replace("%%", "") and "$" not in exec_line.replace("$$", "")


def test_systemd_quote_rules() -> None:
    assert systemd_quote('a "b" \\ c %d $e') == '"a \\"b\\" \\\\ c %%d $$e"'
    assert systemd_quote("PATH=/a:$b%", exec_line=False) == '"PATH=/a:$b%%"'


def test_a_line_break_in_a_path_is_refused(tmp_path: Path) -> None:
    for platform in ("linux", "darwin", "win32"):
        with pytest.raises(AutostartError, match="line break"):
            plan(
                Path("/home/sam/evil\nExecStartPre=/bin/rm"),
                platform=platform,
                env={},
                home=tmp_path,
                python=PY,
            )
    with pytest.raises(AutostartError, match="line break"):
        plan(Path("/data"), platform="linux", env={"PATH": "/bin\n[Service]"}, home=tmp_path, python=PY)


def test_no_path_no_environment_line(tmp_path: Path) -> None:
    entry = plan(Path("/data"), platform="linux", env={}, home=tmp_path, python=PY)
    assert "Environment=" not in entry.content


# --------------------------------------------------------------------------------------------------
# macOS
# --------------------------------------------------------------------------------------------------


def test_macos_writes_a_launch_agent(tmp_path: Path) -> None:
    home = tmp_path / "Users" / "sam"
    entry = plan(
        Path("/Users/sam/Library/Application Support/ordnung"),
        platform="darwin",
        env={"PATH": PATH_ENV},
        home=home,
        python=PY,
    )
    assert entry.path == home / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"
    assert entry.link is None
    assert enable(entry) == "added"
    agent = plistlib.loads(entry.path.read_bytes())
    assert agent == {
        "Label": LAUNCH_LABEL,
        "ProgramArguments": [
            PY,
            "-m",
            "ordnung",
            "--data-dir",
            "/Users/sam/Library/Application Support/ordnung",
            "serve",
            "--no-browser",
        ],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": str(home / "Library" / "Logs" / "ordnung.log"),
        "EnvironmentVariables": {"PATH": PATH_ENV},
    }
    assert f"launchctl bootstrap gui/$(id -u) '{entry.path}'" in entry.start_now
    assert entry.stop_now == f"launchctl bootout gui/$(id -u)/{LAUNCH_LABEL}"


def test_macos_escapes_xml_in_paths(tmp_path: Path) -> None:
    entry = plan(Path("/Users/sam/<Ordnung & Co>"), platform="darwin", env={}, home=tmp_path, python=PY)
    assert "<Ordnung" not in entry.content and "&amp;" in entry.content
    assert entry_argv("macos", entry.content) == list(entry.argv)


# --------------------------------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------------------------------


def test_windows_writes_a_startup_cmd(tmp_path: Path) -> None:
    roaming = tmp_path / "AppData" / "Roaming"
    py = "C:\\Users\\Sam\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"
    entry = plan(
        Path("C:\\Users\\Sam\\AppData\\Local\\ordnung"),
        platform="win32",
        env={"APPDATA": str(roaming)},
        home=tmp_path,
        python=py,
    )
    assert (
        entry.path == roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / STARTUP_NAME
    )
    assert enable(entry) == "added"
    raw = entry.path.read_bytes()
    assert raw.count(b"\r\n") == 5 and b"\n" not in raw.replace(b"\r\n", b"")
    lines = raw.decode().split("\r\n")
    assert lines[:2] == ["@echo off", "chcp 65001 >nul"]
    assert lines[4].startswith('start "Ordnung" /min "C:\\Users\\Sam')
    assert lines[4].endswith('"serve" "--no-browser"')
    assert entry_argv("windows", entry.content) == list(entry.argv)
    assert "Close the minimised" in entry.stop_now


def test_windows_reads_a_user_folder_with_umlauts_as_written(tmp_path: Path) -> None:
    """cmd.exe reads a batch file in the console's code page (850 on a German Windows): the UTF-8 file
    switches it to UTF-8 before the first character outside ASCII, or "Jürgen" becomes "J├╝rgen"."""
    py = "C:\\Users\\Jürgen\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"
    folder = tmp_path / "Jürgen" / "AppData" / "Local" / "ordnung"
    entry = plan(folder, platform="win32", env={"APPDATA": str(tmp_path)}, home=tmp_path, python=py)
    enable(entry)
    raw = entry.path.read_bytes()
    switch = raw.index(b"chcp 65001 >nul\r\n")
    assert raw[:switch].isascii()  # read in the console's code page, whatever it is
    assert raw.decode("utf-8").count("Jürgen") == 2  # the Python and the data folder
    assert "J├╝rgen" in raw.decode("cp850")  # what cmd.exe would have run without the switch
    assert entry_argv("windows", entry.content) == list(entry.argv)
    assert state(folder, platform="win32", env={"APPDATA": str(tmp_path)}, home=tmp_path, python=py).current


def test_the_entry_is_written_through_a_binary_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On Windows ``os.open`` without ``O_BINARY`` opens in text mode: the .cmd's ``\r\n`` would be
    written as ``\r\r\n`` and ``enable`` would never find the entry unchanged."""
    binary = 0x40000000  # stands in for Windows' O_BINARY (removed again before the real open)
    monkeypatch.setattr(os, "O_BINARY", binary, raising=False)
    real_open, flags_seen = os.open, []

    def recording_open(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        flags_seen.append(flags)
        return real_open(path, flags & ~binary, mode, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    entry = plan(
        Path("C:\\d"), platform="win32", env={"APPDATA": str(tmp_path)}, home=tmp_path, python="py.exe"
    )
    assert enable(entry) == "added"
    assert flags_seen and all(flags & binary for flags in flags_seen)
    assert entry.path.read_bytes() == entry.content.encode("utf-8")
    assert enable(entry) == "unchanged"


def test_windows_doubles_percent_signs_and_refuses_quotes() -> None:
    assert cmd_quote("C:\\100%\\x") == '"C:\\100%%\\x"'
    with pytest.raises(AutostartError):
        cmd_quote('C:\\a"b')


def test_windows_without_appdata_uses_the_home_folder(tmp_path: Path) -> None:
    entry = plan(Path("C:\\d"), platform="win32", env={}, home=tmp_path, python="python.exe")
    assert entry.path.is_relative_to(tmp_path / "AppData" / "Roaming")


# --------------------------------------------------------------------------------------------------
# Claude Code's telemetry opt-out
# --------------------------------------------------------------------------------------------------


def test_the_telemetry_opt_out_set_at_enable_goes_into_the_entry(tmp_path: Path) -> None:
    """docs/privacy.md: set it in the environment Ordnung starts from. At login that is the entry's
    environment, which the terminal's variables never reach unless they are written into it."""
    env = {"PATH": PATH_ENV, "APPDATA": str(tmp_path), TELEMETRY_OPT_OUT: "1"}
    unit = plan(Path("/data"), platform="linux", env=env, home=tmp_path, python=PY)
    assert f'Environment="{TELEMETRY_OPT_OUT}=1"' in unit.content.splitlines()
    assert entry_argv("linux", unit.content) == list(unit.argv)
    agent = plistlib.loads(
        plan(Path("/data"), platform="darwin", env=env, home=tmp_path, python=PY).content.encode()
    )
    assert agent["EnvironmentVariables"] == {"PATH": PATH_ENV, TELEMETRY_OPT_OUT: "1"}
    cmd = plan(Path("C:\\d"), platform="win32", env=env, home=tmp_path, python="py.exe")
    lines = cmd.content.split("\r\n")
    assert lines[4] == f'set "{TELEMETRY_OPT_OUT}=1"' and lines[5].startswith('start "Ordnung" /min')
    assert entry_argv("windows", cmd.content) == list(cmd.argv)

    unset = {"PATH": PATH_ENV, "APPDATA": str(tmp_path), TELEMETRY_OPT_OUT: ""}
    for platform in ("linux", "darwin", "win32"):
        entry = plan(Path("/data"), platform=platform, env=unset, home=tmp_path, python=PY)
        assert TELEMETRY_OPT_OUT not in entry.content
    with pytest.raises(AutostartError, match="line break"):
        plan(Path("/data"), platform="linux", env={TELEMETRY_OPT_OUT: "1\n[Service]"}, home=tmp_path)


# --------------------------------------------------------------------------------------------------
# rewrite, remove, status
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_enable_is_idempotent_and_the_last_folder_wins(tmp_path: Path, platform: str) -> None:
    env = {"PATH": "/usr/bin", "APPDATA": str(tmp_path / "roaming")}
    first = plan(tmp_path / "one", platform=platform, env=env, home=tmp_path, python=PY)
    assert enable(first) == "added"
    assert enable(first) == "unchanged"
    second = plan(tmp_path / "two", platform=platform, env=env, home=tmp_path, python=PY)
    assert second.path == first.path
    assert enable(second) == "updated"
    assert str(tmp_path / "two") in "".join(entry_argv(second.system, second.path.read_text()) or [])
    found = state(tmp_path / "two", platform=platform, env=env, home=tmp_path, python=PY)
    assert found.enabled and found.current and found.data_dir == tmp_path / "two"
    stale = state(tmp_path / "one", platform=platform, env=env, home=tmp_path, python=PY)
    assert stale.enabled and not stale.current
    removed = disable(second)
    assert first.path in removed and not first.path.exists()
    if first.link is not None:
        assert first.link in removed and not first.link.is_symlink()
    assert disable(second) == []
    assert not state(tmp_path / "two", platform=platform, env=env, home=tmp_path).enabled


def test_a_moved_python_makes_the_entry_stale(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin"}
    enable(plan(tmp_path / "d", platform="linux", env=env, home=tmp_path, python=PY))
    assert state(tmp_path / "d", platform="linux", env=env, home=tmp_path, python=PY).current
    assert not state(
        tmp_path / "d", platform="linux", env=env, home=tmp_path, python="/usr/bin/python3"
    ).current
    # another PATH in this terminal changes nothing
    assert state(tmp_path / "d", platform="linux", env={"PATH": "/x"}, home=tmp_path, python=PY).current


def test_a_custom_port_is_part_of_the_entry(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin"}
    enable(plan(tmp_path / "d", port=9001, platform="linux", env=env, home=tmp_path, python=PY))
    assert state(tmp_path / "d", platform="linux", env=env, home=tmp_path, python=PY).current


def test_a_missing_link_is_restored_and_disable_leaves_other_units(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin"}
    entry = plan(tmp_path / "d", platform="linux", env=env, home=tmp_path, python=PY)
    enable(entry)
    assert entry.link is not None
    entry.link.unlink()
    assert not state(tmp_path / "d", platform="linux", env=env, home=tmp_path, python=PY).current
    assert enable(entry) == "updated"
    assert entry.link.is_symlink()
    other = entry.path.with_name("syncthing.service")
    other.write_text("[Service]\n")
    disable(entry)
    assert other.read_text() == "[Service]\n"


def test_an_unreadable_entry_counts_as_enabled_but_not_current(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin"}
    where = plan(tmp_path / "d", platform="darwin", env=env, home=tmp_path, python=PY)
    where.path.parent.mkdir(parents=True)
    where.path.write_text("not a plist")
    found = state(tmp_path / "d", platform="darwin", env=env, home=tmp_path, python=PY)
    assert found.enabled and not found.current and found.data_dir is None


# --------------------------------------------------------------------------------------------------
# the commands
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def invoke(*args: str) -> Any:
    return runner.invoke(app, list(args))


def test_the_commands_print_what_they_write(fake_home: Path, tmp_path: Path) -> None:
    folder = tmp_path / "data"
    unit = fake_home / ".config" / "systemd" / "user" / UNIT_NAME

    dry = invoke("autostart", "enable", "--data-dir", str(folder), "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert str(unit) in dry.output and "ExecStart=" in dry.output and "Nothing was written" in dry.output
    assert not unit.exists()

    done = invoke("autostart", "enable", "--data-dir", str(folder))
    assert done.exit_code == 0, done.output
    assert unit.is_file() and "--no-browser" in unit.read_text()
    assert "systemd user service" in done.output and "Written." in done.output
    assert "systemctl --user daemon-reload && systemctl --user restart ordnung.service" in done.output
    assert "default.target.wants" in done.output

    again = invoke("autostart", "enable", "--data-dir", str(folder))
    assert "Already set up like this." in again.output

    status = invoke("autostart", "status", "--data-dir", str(folder))
    assert status.exit_code == 0
    assert "Starts at login: yes" in status.output and str(folder) in status.output
    assert "Running now: no" in status.output and "doesn't start this Ordnung" not in status.output

    other = invoke("autostart", "status", "--data-dir", str(tmp_path / "elsewhere"))
    assert "doesn't start this Ordnung" in other.output

    off = invoke("autostart", "disable")
    assert off.exit_code == 0 and "Removed" in off.output and "systemctl --user stop" in off.output
    assert not unit.exists()
    assert "there is no" in invoke("autostart", "disable").output
    assert "Starts at login: no" in invoke("autostart", "status", "--data-dir", str(folder)).output


def test_enable_says_when_the_morning_notification_is_still_off(fake_home: Path, tmp_path: Path) -> None:
    """Start at login alone tells the person nothing: the notification is off until switched on."""
    from ordnung.config import Paths
    from ordnung.db.store import Store

    fresh = invoke("autostart", "enable", "--data-dir", str(tmp_path / "fresh"))
    assert fresh.exit_code == 0 and "morning desktop notification is off" in fresh.output
    assert "Settings → Reminders" in fresh.output
    assert not (tmp_path / "fresh").exists()  # reading the setting created nothing

    folder = tmp_path / "data"
    store = Store.open(Paths(folder).ensure())
    try:
        store.save_settings(store.get_settings().model_copy(update={"desktop_notifications": "discreet"}))
    finally:
        store.close()
    on = invoke("autostart", "enable", "--data-dir", str(folder))
    assert on.exit_code == 0 and "notification is off" not in on.output


def test_enable_carries_the_telemetry_opt_out_of_this_terminal(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(TELEMETRY_OPT_OUT, "1")
    dry = invoke("autostart", "enable", "--data-dir", str(tmp_path / "data"), "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert f'Environment="{TELEMETRY_OPT_OUT}=1"' in dry.output.splitlines()


def test_the_demo_does_not_start_at_login(
    fake_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ordnung.demo.loader as loader

    monkeypatch.setattr(loader, "is_demo_dir", lambda _folder: True)
    result = invoke("autostart", "enable", "--data-dir", str(tmp_path / "demo"))
    assert result.exit_code == 1 and "demo doesn't start at login" in result.output


def test_autostart_help_lists_the_three_commands() -> None:
    result = invoke("autostart", "--help")
    assert result.exit_code == 0
    for command in ("enable", "disable", "status"):
        assert command in result.output


def test_location_matches_plan(tmp_path: Path) -> None:
    for platform in ("linux", "darwin", "win32"):
        env = {"APPDATA": str(tmp_path)}
        assert (
            autostart.location(platform=platform, env=env, home=tmp_path).path
            == plan(tmp_path, platform=platform, env=env, home=tmp_path).path
        )
