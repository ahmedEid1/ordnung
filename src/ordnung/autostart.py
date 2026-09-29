"""Start Ordnung when the person logs in (``ordnung autostart enable|disable|status``).

Reminders only reach someone whose Ordnung is running: the daily tick, the morning desktop
notification (:mod:`ordnung.notify.desktop`) and the watched folder all live in ``ordnung serve``.

Written policy (ADR 0007):

* **One entry, the system's own mechanism, nothing run.** Linux: a systemd *user* unit
  ``$XDG_CONFIG_HOME/systemd/user/ordnung.service`` (default ``~/.config``) and the
  ``default.target.wants/ordnung.service`` link that ``systemctl --user enable`` would make.
  macOS: a LaunchAgent ``~/Library/LaunchAgents/local.ordnung.serve.plist`` that runs at load.
  Windows: ``Ordnung.cmd`` in the Startup folder (``%APPDATA%\\Microsoft\\Windows\\Start
  Menu\\Programs\\Startup``) that starts it in a minimised window. Ordnung writes these files itself
  and runs no service manager: ``enable`` prints exactly what it wrote where, and the command that
  starts it now without logging in again.
* **What runs.** ``<this Python> -m ordnung --data-dir <the data folder> serve --no-browser`` (and
  ``--port`` when it isn't the default) — absolute paths, so the login environment's ``PATH`` does
  not matter for Ordnung itself; the ``PATH`` of the terminal that ran ``enable`` is recorded
  (Linux, macOS) so the service finds the same ``claude`` command. A crash is restarted (systemd:
  after 30 s; launchd: on an unsuccessful exit); a clean stop stays stopped.
* **The sign-in link stays private.** ``serve`` prints its link with the session token on standard
  output, so the service discards standard output (systemd ``StandardOutput=null``, launchd
  ``/dev/null``): the token never lands in the system journal or a log file. Errors go to the
  journal (Linux) or ``~/Library/Logs/ordnung.log`` (macOS). On Windows the minimised window is the
  person's own. The web app is opened with ``ordnung serve``: it finds the running server and opens
  the browser.
* **Only Ordnung's own entry.** ``enable`` writes the entry (``0600``, atomically) and replaces an
  earlier one — one Ordnung starts at login, the last folder enabled wins; an identical entry is
  left as it is. ``disable`` removes the entry and the link, nothing else, and says so when there is
  none. ``status`` says whether there is an entry, which data folder it starts, and whether it is
  what ``enable`` would write now (a moved Python or data folder makes it stale).
* **Not for the demo.** The demo is started with ``ordnung demo`` (the CLI refuses a demo folder).
* **Quoting.** systemd: every ``ExecStart`` argument in double quotes with ``\\`` and ``"``
  escaped, ``%`` doubled (specifiers) and ``$`` doubled (variables); ``Environment=`` the same
  without ``$``. The plist is written by :mod:`plistlib`. Windows ``.cmd``: every argument in double
  quotes with ``%`` doubled (a Windows path can't contain ``"``). A line break in any value is
  refused.
* **Encoding.** Every entry is UTF-8. cmd.exe reads a batch file in the console's code page (850 on
  a German Windows), so the ``.cmd`` switches to UTF-8 (``chcp 65001``) on its second line, before
  any character outside ASCII — a user folder like ``C:\\Users\\Jürgen`` is read as written.
"""

from __future__ import annotations

import contextlib
import os
import plistlib
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ordnung.server import DEFAULT_PORT

System = Literal["linux", "macos", "windows"]
WriteStatus = Literal["added", "updated", "unchanged"]

UNIT_NAME = "ordnung.service"
LAUNCH_LABEL = "local.ordnung.serve"
STARTUP_NAME = "Ordnung.cmd"
RESTART_AFTER_S = 30
ENTRY_MODE = 0o600
HEADER = "Written by `ordnung autostart enable`; `ordnung autostart disable` removes it."
KINDS: dict[System, str] = {
    "linux": "systemd user service",
    "macos": "LaunchAgent",
    "windows": "Startup folder",
}


class AutostartError(RuntimeError):
    """The entry can't be written as asked; the message says why and nothing was changed."""


@dataclass(frozen=True)
class Entry:
    """What ``ordnung autostart enable`` writes, where, and how to start or stop it by hand."""

    system: System
    path: Path
    content: str
    argv: tuple[str, ...]
    link: Path | None = None
    start_now: str = ""
    stop_now: str = ""

    @property
    def kind(self) -> str:
        return KINDS[self.system]


@dataclass(frozen=True)
class State:
    """What ``ordnung autostart status`` reports."""

    system: System
    path: Path
    enabled: bool
    #: the data folder the entry starts (``None`` when there is no entry or it can't be read)
    data_dir: Path | None = None
    #: the entry is exactly what ``enable`` would write now
    current: bool = False

    @property
    def kind(self) -> str:
        return KINDS[self.system]


def system_of(platform: str | None = None) -> System:
    """``linux``, ``macos`` or ``windows`` for a ``sys.platform`` value (other Unixes use systemd's layout)."""
    value = platform or sys.platform
    if value == "darwin":
        return "macos"
    if value.startswith(("win", "cygwin")):
        return "windows"
    return "linux"


def serve_argv(data_dir: Path, *, port: int | None = None, python: str | None = None) -> tuple[str, ...]:
    """The command that starts Ordnung for ``data_dir`` without opening a browser."""
    argv = [python or sys.executable, "-m", "ordnung", "--data-dir", str(data_dir), "serve", "--no-browser"]
    if port is not None and port != DEFAULT_PORT:
        argv += ["--port", str(port)]
    return tuple(argv)


def _no_line_breaks(values: tuple[str, ...] | list[str]) -> None:
    if any("\n" in value or "\r" in value for value in values):
        raise AutostartError("A path with a line break can't be put into a start-up entry.")


# --------------------------------------------------------------------------------------------------
# Linux: a systemd user unit
# --------------------------------------------------------------------------------------------------


def systemd_quote(value: str, *, exec_line: bool = True) -> str:
    """``value`` as one double-quoted systemd word (module policy)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    if exec_line:
        escaped = escaped.replace("$", "$$")
    return f'"{escaped}"'


_SYSTEMD_WORD = re.compile(r'"((?:[^"\\]|\\.)*)"')


def systemd_unquote(line: str) -> list[str]:
    """The words of an ``ExecStart=`` value written by :func:`systemd_quote`."""
    words = []
    for match in _SYSTEMD_WORD.finditer(line):
        word = re.sub(r"\\(.)", r"\1", match[1])
        words.append(word.replace("%%", "%").replace("$$", "$"))
    return words


def _unit(argv: tuple[str, ...], path_env: str | None) -> str:
    lines = [
        f"# {HEADER}",
        "[Unit]",
        "Description=Ordnung, your paperwork secretary (the local web app, on this computer only)",
        "Documentation=https://github.com/ahmedEid1/ordnung",
        "",
        "[Service]",
        "Type=simple",
    ]
    if path_env:
        lines.append(f"Environment={systemd_quote('PATH=' + path_env, exec_line=False)}")
    lines += [
        "ExecStart=" + " ".join(systemd_quote(arg) for arg in argv),
        "Restart=on-failure",
        f"RestartSec={RESTART_AFTER_S}",
        "# the sign-in link (with the session token) goes to standard output: keep it out of the journal",
        "StandardOutput=null",
        "StandardError=journal",
        "",
        "[Install]",
        "WantedBy=default.target",
    ]
    return "\n".join(lines) + "\n"


def _linux(argv: tuple[str, ...], env: Mapping[str, str], home: Path) -> Entry:
    folder = Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "systemd" / "user"
    unit = folder / UNIT_NAME
    return Entry(
        system="linux",
        path=unit,
        content=_unit(argv, env.get("PATH")),
        argv=argv,
        link=folder / "default.target.wants" / UNIT_NAME,
        start_now=f"systemctl --user daemon-reload && systemctl --user restart {UNIT_NAME}",
        stop_now=f"systemctl --user stop {UNIT_NAME}",
    )


# --------------------------------------------------------------------------------------------------
# macOS: a LaunchAgent
# --------------------------------------------------------------------------------------------------


def _plist(argv: tuple[str, ...], path_env: str | None, home: Path) -> str:
    agent: dict[str, object] = {
        "Label": LAUNCH_LABEL,
        "ProgramArguments": list(argv),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": str(home / "Library" / "Logs" / "ordnung.log"),
    }
    if path_env:
        agent["EnvironmentVariables"] = {"PATH": path_env}
    return plistlib.dumps(agent, sort_keys=True).decode("utf-8")


def _macos(argv: tuple[str, ...], env: Mapping[str, str], home: Path) -> Entry:
    path = home / "Library" / "LaunchAgents" / f"{LAUNCH_LABEL}.plist"
    target = f"gui/$(id -u)/{LAUNCH_LABEL}"
    return Entry(
        system="macos",
        path=path,
        content=_plist(argv, env.get("PATH"), home),
        argv=argv,
        start_now=f"launchctl bootout {target} 2>/dev/null; launchctl bootstrap gui/$(id -u) '{path}'",
        stop_now=f"launchctl bootout {target}",
    )


# --------------------------------------------------------------------------------------------------
# Windows: a .cmd in the Startup folder
# --------------------------------------------------------------------------------------------------


def cmd_quote(value: str) -> str:
    """``value`` as one double-quoted ``.cmd`` argument (``%`` doubled)."""
    if '"' in value:
        raise AutostartError("A path with a \" can't be put into a start-up entry.")
    return '"' + value.replace("%", "%%") + '"'


#: cmd.exe reads what follows as UTF-8 (the file is UTF-8; everything before this line is ASCII)
UTF8_CODE_PAGE = "chcp 65001 >nul"


def _cmd(argv: tuple[str, ...]) -> str:
    lines = [
        "@echo off",
        UTF8_CODE_PAGE,
        f"rem {HEADER}",
        "rem Starts Ordnung (the local web app) in a minimised window when you sign in; closing it stops Ordnung.",
        'start "Ordnung" /min ' + " ".join(cmd_quote(arg) for arg in argv),
    ]
    return "\r\n".join(lines) + "\r\n"


def _windows(argv: tuple[str, ...], env: Mapping[str, str], home: Path) -> Entry:
    roaming = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
    path = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / STARTUP_NAME
    return Entry(
        system="windows",
        path=path,
        content=_cmd(argv),
        argv=argv,
        start_now=f'"{path}"',
        stop_now="Close the minimised “Ordnung” window.",
    )


# --------------------------------------------------------------------------------------------------
# plan, write, remove, read back
# --------------------------------------------------------------------------------------------------


def plan(
    data_dir: Path,
    *,
    port: int | None = None,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    python: str | None = None,
) -> Entry:
    """The entry that starts Ordnung for ``data_dir`` at login on this (or the given) platform."""
    system = system_of(platform)
    env = os.environ if env is None else env
    home = home or Path.home()
    argv = serve_argv(Path(data_dir).expanduser().absolute(), port=port, python=python)
    values = [*argv, env.get("PATH") or "", str(home)]
    _no_line_breaks(values)
    builders = {"linux": _linux, "macos": _macos, "windows": _windows}
    return builders[system](argv, env, home)


def location(
    *, platform: str | None = None, env: Mapping[str, str] | None = None, home: Path | None = None
) -> Entry:
    """Where the entry lives on this platform (its content is irrelevant here)."""
    return plan(Path("/"), platform=platform, env=env, home=home, python="python")


def _write_atomically(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.{os.getpid()}.part")
    # bytes through a binary descriptor: in text mode Windows would turn the .cmd's \r\n into \r\r\n
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0), ENTRY_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content.encode("utf-8"))
        partial.replace(path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()


def _read(path: Path) -> str:
    """An entry's text exactly as written (``\r\n`` kept: the Windows entry is compared byte for byte)."""
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _link_ok(link: Path, target: Path) -> bool:
    return link.is_symlink() and link.readlink() == target


def enable(entry: Entry) -> WriteStatus:
    """Write ``entry`` (and its link); an identical entry is left untouched."""
    existing = _read(entry.path) if entry.path.is_file() else None
    link_ok = entry.link is None or _link_ok(entry.link, entry.path)
    if existing == entry.content and link_ok:
        return "unchanged"
    _write_atomically(entry.path, entry.content)
    if entry.link is not None and not link_ok:
        entry.link.parent.mkdir(parents=True, exist_ok=True)
        if entry.link.is_symlink() or entry.link.exists():
            entry.link.unlink()
        entry.link.symlink_to(entry.path)
    return "added" if existing is None else "updated"


def disable(entry: Entry) -> list[Path]:
    """Remove the entry at ``entry``'s location and its link; returns what was removed."""
    removed = []
    for path in (entry.link, entry.path):
        if path is not None and (path.is_symlink() or path.is_file()):
            path.unlink()
            removed.append(path)
    return removed


def entry_argv(system: System, content: str) -> list[str] | None:
    """The command an entry written by :func:`enable` runs (``None`` when it can't be read)."""
    if system == "linux":
        line = next((line for line in content.splitlines() if line.startswith("ExecStart=")), None)
        return systemd_unquote(line.removeprefix("ExecStart=")) if line else None
    if system == "macos":
        try:
            agent = plistlib.loads(content.encode("utf-8"))
        except (plistlib.InvalidFileException, ValueError, TypeError):
            return None
        args = agent.get("ProgramArguments") if isinstance(agent, dict) else None
        return [str(arg) for arg in args] if isinstance(args, list) else None
    line = next((line for line in content.splitlines() if line.startswith("start ")), None)
    if line is None:
        return None
    return [word.replace("%%", "%") for word in re.findall(r'"([^"]*)"', line)[1:]]


def _port_of(argv: list[str]) -> int | None:
    if "--port" not in argv[:-1]:
        return None
    try:
        return int(argv[argv.index("--port") + 1])
    except ValueError:
        return None


def state(
    data_dir: Path | None = None,
    *,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    python: str | None = None,
) -> State:
    """Is there an entry, which data folder does it start, and does it run what ``enable`` would
    write now for ``data_dir`` (default: its own folder) — this Python, that folder, its port?
    The recorded ``PATH`` is not compared: it differs between terminals without making anything stale."""
    where = location(platform=platform, env=env, home=home)
    if not where.path.is_file():
        return State(system=where.system, path=where.path, enabled=False)
    try:
        content = _read(where.path)
    except (OSError, UnicodeDecodeError):
        return State(system=where.system, path=where.path, enabled=True)
    argv = entry_argv(where.system, content) or []
    folder = Path(argv[argv.index("--data-dir") + 1]) if "--data-dir" in argv[:-1] else None
    wanted = Path(data_dir).expanduser().absolute() if data_dir is not None else folder
    current = (
        wanted is not None
        and argv == list(serve_argv(wanted, port=_port_of(argv), python=python))
        and (where.link is None or _link_ok(where.link, where.path))
    )
    return State(system=where.system, path=where.path, enabled=True, data_dir=folder, current=current)
