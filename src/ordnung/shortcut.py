"""Open Ordnung without a terminal (``ordnung shortcut [--remove] [--dry-run]``).

Written policy (ADR 0007):

* **One launcher, the system's own kind, nothing run.** Linux: an app-menu entry
  ``$XDG_DATA_HOME/applications/ordnung.desktop`` (default ``~/.local/share``). macOS:
  ``~/Applications/Ordnung.app``, a bundle of a property list, two short ``sh`` scripts and an icon.
  Windows: ``Ordnung.lnk`` in the per-user Start menu (``%APPDATA%\\Microsoft\\Windows\\Start
  Menu\\Programs``), with its icon in ``%LOCALAPPDATA%\\Programs\\Ordnung\\Ordnung.ico``. Ordnung
  writes every file itself, the ``.lnk`` too: its bytes follow the shell link format (MS-SHLLINK), a
  header, the target as a Unicode local path in its LinkInfo, and the arguments, working folder, icon
  and description as Unicode strings. No COM, no PowerShell, no other tool runs, and no admin rights
  are needed. ``ordnung shortcut`` prints what it writes, and where, before writing anything.
* **What it runs.** ``<this Python> -m ordnung --data-dir <the data folder> serve --from-shortcut``
  (and ``--port`` when it isn't the default): absolute paths, and the last folder set up wins, as for
  autostart. Linux and macOS record this terminal's ``PATH``, so Ordnung finds the same ``claude``,
  and also Claude Code's telemetry opt-out ``CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`` when it is set
  here. A Windows shortcut can't carry variables: the command says how to set the opt-out for the
  account (``setx``).
* **Never started unseen.** ``serve --from-shortcut`` opens a running Ordnung in the browser.
  Otherwise it starts Ordnung only when it has a terminal window to run in, and that window is
  Ordnung: closing it stops Ordnung. Linux asks the desktop for a terminal (``Terminal=true``) and
  Windows opens a console; the sign-in link is printed only in that window, never into a log or the
  system journal (ADR 0013). Without a terminal it exits with :data:`NO_WINDOW_EXIT` and starts
  nothing; the Mac bundle then opens Terminal with the bundle's own ``Ordnung.command`` (its first,
  windowless step throws its output away). A failed start waits for Enter so the person can read why,
  and a second click while the first start is under way waits for the starting server and opens it.
* **Only Ordnung's own launcher.** Each launcher carries a mark: the ``.desktop`` key
  ``X-Ordnung-Shortcut``, the ``OrdnungShortcut`` key in ``Info.plist``, or the ``.lnk``
  description's "(added by ordnung shortcut)"; the Windows icon, which lives outside the launcher,
  has :data:`MARK` in its pictures. A file at that place without the mark (or a link to one) is never
  replaced or removed. ``--remove`` deletes exactly the files the shortcut writes, and a bundle folder
  only once it is empty. An identical launcher is left as it is.
* **Not for the demo.** The demo opens with ``ordnung demo`` (the CLI refuses a demo folder).
* **Quoting.** ``.desktop`` ``Exec``: every argument in double quotes, with ``"``, the backtick, ``$``
  and ``\\`` backslash-escaped and ``%`` doubled; then every backslash is doubled again, because the
  string-escape rule applies first (Desktop Entry Specification, "The Exec key"). ``sh``: single
  quotes, with ``'`` written as ``'\\''``. ``.lnk`` arguments: :func:`subprocess.list2cmdline`, the
  MS C runtime rules ``python.exe`` parses. A line break in any value is refused.
* **Limits.** On Windows a data folder whose path holds ``%NAME%`` for a defined variable may be
  expanded by the shell. On a Linux desktop without a terminal it knows, the entry opens nothing.

Reading a launcher back (:func:`state`, asked on every page of the web app) is a file check and a
small read: no icon is drawn and Pillow isn't imported; icons are drawn only by :func:`write`.
"""

from __future__ import annotations

import contextlib
import io
import os
import plistlib
import re
import shlex
import struct
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from xml.parsers.expat import ExpatError

from ordnung import autostart
from ordnung.config import web_dist_dir
from ordnung.durable import write_atomic
from ordnung.server import DEFAULT_PORT

if TYPE_CHECKING:
    from PIL import Image

System = autostart.System
WriteStatus = autostart.WriteStatus

MARK = "Written by `ordnung shortcut`; `ordnung shortcut --remove` removes it."
#: the command that writes the launcher (:func:`command` adds the data folder)
COMMAND = "ordnung shortcut"
DESKTOP_FILE = "ordnung.desktop"
BUNDLE = "Ordnung.app"
LNK = "Ordnung.lnk"
ICO = "Ordnung.ico"
#: the mark of each kind of launcher (module policy): a ``.desktop`` key, an ``Info.plist`` key, the
#: end of the ``.lnk`` description
DESKTOP_MARK = "X-Ordnung-Shortcut"
PLIST_MARK = "OrdnungShortcut"
LNK_MARK = "(added by ordnung shortcut)"
FILE_MODE = 0o600
SCRIPT_MODE = 0o700
#: ``serve --from-shortcut`` when Ordnung isn't running and there is no terminal to run it in
NO_WINDOW_EXIT = 3
KINDS: dict[System, str] = {
    "linux": "app menu entry",
    "macos": "app in your Applications folder",
    "windows": "Start menu shortcut",
}
#: where the launcher shows up, as the person knows it
WHERE: dict[System, str] = {
    "linux": "your app menu",
    "macos": "your Applications folder",
    "windows": "your Start menu",
}
#: Claude Code's telemetry opt-out, recorded as autostart records it (docs/privacy.md)
TELEMETRY_OPT_OUT = autostart.TELEMETRY_OPT_OUT
DESCRIPTION = f"Ordnung, your paperwork secretary {LNK_MARK}"
#: the variables that say where the launcher goes (``location`` needs no others)
PLACE_VARIABLES = ("XDG_DATA_HOME", "APPDATA", "LOCALAPPDATA")
#: the pictures of each icon: the ``.ico``'s sizes, and the ``.icns`` entries (PNG) with their sizes
ICO_SIZES = (16, 24, 32, 48, 256)
ICNS_ENTRIES = (("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128), ("ic08", 256), ("ic09", 512))
#: a launcher file bigger than this isn't one Ordnung wrote (they are a few kB): not even read
_MAX_READ = 1 << 20

Owner = Literal["none", "ours", "other"]


class ShortcutError(RuntimeError):
    """The launcher can't be written or removed as asked; the message says why and nothing was changed."""


@dataclass(frozen=True)
class File:
    """One file of the launcher."""

    path: Path
    #: ``None``: an icon, drawn by :func:`write` (a dry run needs no Pillow)
    content: bytes | None
    mode: int = FILE_MODE


@dataclass(frozen=True)
class WindowsLink:
    """What the ``.lnk`` holds (written by :func:`lnk_bytes`, read back by :func:`read_lnk`)."""

    target: str
    arguments: str
    working_dir: str
    icon: str
    description: str
    #: ``SW_SHOWNORMAL``: a normal window, so errors stay visible
    show: int = 1


@dataclass(frozen=True)
class Shortcut:
    """What ``ordnung shortcut`` writes, and where."""

    system: System
    #: the ``.desktop``, the ``Ordnung.app`` folder or the ``.lnk``
    path: Path
    argv: tuple[str, ...]
    files: tuple[File, ...]
    link: WindowsLink | None = None

    @property
    def kind(self) -> str:
        return KINDS[self.system]

    def shown(self) -> str:
        """What ``ordnung shortcut`` prints: each file's text, or the link's fields."""
        drawn = "Ordnung's logo, drawn when it is written"
        if self.link is not None:
            link = self.link
            return "\n".join(
                [
                    f"Target: {link.target}",
                    f"Arguments: {link.arguments}",
                    f"Start in: {link.working_dir}",
                    f"Icon: {link.icon} ({drawn})",
                    f"Comment: {link.description}",
                    "Run: Normal window",
                ]
            )
        parts = []
        for file in self.files:
            name = None if file.path == self.path else file.path.relative_to(self.path).as_posix()
            if file.content is None:
                parts.append(f"{name}: {drawn}")
                continue
            text = file.content.decode("utf-8").rstrip("\n")
            parts.append(text if name is None else f"{name}:\n{text}")
        return "\n".join(parts)


@dataclass(frozen=True)
class State:
    """What Settings → Reminders reports about the launcher."""

    system: System
    path: Path
    #: a launcher is there
    added: bool
    #: it carries the mark
    ours: bool = True
    #: the data folder it opens (``None`` when there is none or it can't be read)
    data_dir: Path | None = None
    #: it is exactly what :func:`plan` would write now (the command, and every file present)
    current: bool = False

    @property
    def kind(self) -> str:
        return KINDS[self.system]


def shortcut_argv(data_dir: Path, *, port: int | None = None, python: str | None = None) -> tuple[str, ...]:
    """The command the launcher runs for ``data_dir``: ``serve --from-shortcut`` (module policy)."""
    argv = [
        python or sys.executable,
        "-m",
        "ordnung",
        "--data-dir",
        str(data_dir),
        "serve",
        "--from-shortcut",
    ]
    if port is not None and port != DEFAULT_PORT:
        argv += ["--port", str(port)]
    return tuple(argv)


def _no_line_breaks(values: list[str]) -> None:
    if any("\n" in value or "\r" in value for value in values):
        raise ShortcutError("A path or setting with a line break can't be put into a shortcut.")


# --------------------------------------------------------------------------------------------------
# Linux: an app-menu entry
# --------------------------------------------------------------------------------------------------

_DESKTOP_RESERVED = re.compile(r'(["`$\\])')
_DESKTOP_ESCAPE = re.compile(r"\\(.)")
_DESKTOP_ESCAPES = {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
_EXEC_WORD = re.compile(r'"((?:[^"\\]|\\.)*)"|(\S+)')
_QUOTED_ESCAPE = re.compile(r'\\(["`$\\])')
_VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def desktop_quote(value: str) -> str:
    """``value`` as one argument of a ``.desktop`` ``Exec`` line (module policy)."""
    quoted = _DESKTOP_RESERVED.sub(r"\\\1", value).replace("%", "%%")
    return '"' + quoted.replace("\\", "\\\\") + '"'


def desktop_unquote(exec_value: str) -> list[str]:
    """The arguments of an ``Exec`` value written by :func:`desktop_quote`."""
    text = _DESKTOP_ESCAPE.sub(lambda m: _DESKTOP_ESCAPES.get(m[1], m[0]), exec_value)
    words = []
    for match in _EXEC_WORD.finditer(text):
        word = _QUOTED_ESCAPE.sub(r"\1", match[1]) if match[1] is not None else match[2]
        words.append(word.replace("%%", "%"))
    return words


def _desktop(argv: tuple[str, ...], environment: Mapping[str, str], icon: Path | None) -> str:
    command = list(argv)
    if environment:
        command = ["/usr/bin/env", *(f"{name}={value}" for name, value in environment.items()), *command]
    lines = [
        f"# {MARK}",
        "[Desktop Entry]",
        "Type=Application",
        "Version=1.5",
        "Name=Ordnung",
        "GenericName=Paperwork secretary",
        "Comment=Opens Ordnung in your browser; starts it in a window of its own when it isn't running",
        "Exec=" + " ".join(desktop_quote(arg) for arg in command),
    ]
    if icon is not None:
        lines.append("Icon=" + str(icon).replace("\\", "\\\\"))
    lines += [
        "Terminal=true",
        "Categories=Office;",
        "Keywords=letters;paperwork;deadlines;bills;contracts;",
        "StartupNotify=false",
        f"{DESKTOP_MARK}=1",
    ]
    return "\n".join(lines) + "\n"


def _linux(argv: tuple[str, ...], env: Mapping[str, str], home: Path) -> Shortcut:
    path = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share") / "applications" / DESKTOP_FILE
    svg = web_dist_dir() / "favicon.svg"
    icon = svg if svg.is_file() else None
    environment = autostart._recorded(env, "PATH", TELEMETRY_OPT_OUT)
    content = _desktop(argv, environment, icon).encode("utf-8")
    return Shortcut(system="linux", path=path, argv=argv, files=(File(path, content),))


def _desktop_argv(path: Path) -> tuple[Owner, list[str] | None]:
    lines = _read_text(path).splitlines()
    if not any(line.startswith(f"{DESKTOP_MARK}=") for line in lines):
        return "other", None
    line = next((line for line in lines if line.startswith("Exec=")), None)
    if line is None:
        return "ours", None
    words = desktop_unquote(line.removeprefix("Exec="))
    if words[:1] == ["/usr/bin/env"]:
        words = words[1:]
        while words and _VARIABLE.match(words[0]):
            words = words[1:]
    return "ours", words


# --------------------------------------------------------------------------------------------------
# macOS: an app bundle
# --------------------------------------------------------------------------------------------------


def sh_quote(value: str) -> str:
    """``value`` as one ``sh`` word in single quotes (module policy)."""
    return "'" + value.replace("'", "'\\''") + "'"


def _script(comment: str, exports: list[str], *commands: str) -> bytes:
    return "\n".join(["#!/bin/sh", f"# {MARK}", f"# {comment}", *exports, *commands, ""]).encode("utf-8")


def _macos(argv: tuple[str, ...], env: Mapping[str, str], home: Path) -> Shortcut:
    bundle = home / "Applications" / BUNDLE
    contents = bundle / "Contents"
    exports = [
        f"export {name}={sh_quote(value)}"
        for name, value in autostart._recorded(env, "PATH", TELEMETRY_OPT_OUT).items()
    ]
    command = " ".join(sh_quote(arg) for arg in argv)
    info = {
        "CFBundleExecutable": "Ordnung",
        "CFBundleIdentifier": "local.ordnung.shortcut",
        "CFBundleName": "Ordnung",
        "CFBundleDisplayName": "Ordnung",
        "CFBundlePackageType": "APPL",
        "CFBundleIconFile": "Ordnung",
        # the check is over within a second: no Dock icon bouncing for it
        "LSUIElement": True,
        PLIST_MARK: MARK,
    }
    check = _script(
        "Opens the running Ordnung in your browser; when it isn't running, starts it in a Terminal window.",
        exports,
        f"{command} >/dev/null 2>&1 && exit 0",
        'exec /usr/bin/open -a Terminal "$(dirname "$0")/../Resources/Ordnung.command"',
    )
    window = _script(
        "Runs Ordnung in this Terminal window: closing the window stops Ordnung.", exports, f"exec {command}"
    )
    files = (
        # first: once it is there, the bundle is Ordnung's own, even if the rest isn't written yet
        File(contents / "Info.plist", plistlib.dumps(info, sort_keys=True)),
        File(contents / "MacOS" / "Ordnung", check, SCRIPT_MODE),
        File(contents / "Resources" / "Ordnung.command", window, SCRIPT_MODE),
        File(contents / "Resources" / "Ordnung.icns", None),
    )
    return Shortcut(system="macos", path=bundle, argv=argv, files=files)


def _bundle_argv(sc: Shortcut) -> tuple[Owner, list[str] | None]:
    bundle = sc.path
    info_path = bundle / "Contents" / "Info.plist"
    if not bundle.is_dir():
        return "other", None
    if not (info_path.is_symlink() or info_path.exists()):
        # a folder without the property list isn't an app: it is Ordnung's to fill unless it holds
        # one of the files the shortcut writes (whose they are, nothing says)
        held = any(file.path.is_symlink() or file.path.exists() for file in sc.files)
        return ("other" if held else "none"), None
    if info_path.is_symlink() or not info_path.is_file():
        return "other", None
    info = plistlib.loads(_read_bytes(info_path))
    if not isinstance(info, dict) or PLIST_MARK not in info:
        return "other", None
    window = bundle / "Contents" / "Resources" / "Ordnung.command"
    try:
        line = next(line for line in _read_text(window).splitlines() if line.startswith("exec "))
        return "ours", shlex.split(line)[1:]
    except (OSError, UnicodeDecodeError, ValueError, StopIteration):
        return "ours", None


# --------------------------------------------------------------------------------------------------
# Windows: a Start-menu shortcut (the shell link format, MS-SHLLINK)
# --------------------------------------------------------------------------------------------------

#: ShellLinkHeader: size, LinkCLSID, LinkFlags, FileAttributes, three FILETIMEs, FileSize, IconIndex,
#: ShowCommand, HotKey and three reserved fields (76 bytes)
_HEADER = struct.Struct("<I16sIIQQQIiIHHII")
_HEADER_SIZE = 0x4C
_LINK_CLSID = bytes.fromhex("0114020000000000C000000000000046")
_HAS_ID_LIST, _HAS_LINK_INFO, _HAS_NAME, _HAS_RELATIVE_PATH = 0x1, 0x2, 0x4, 0x8
_HAS_WORKING_DIR, _HAS_ARGUMENTS, _HAS_ICON_LOCATION, _IS_UNICODE = 0x10, 0x20, 0x40, 0x80
_LINK_FLAGS = (
    _HAS_LINK_INFO | _HAS_NAME | _HAS_WORKING_DIR | _HAS_ARGUMENTS | _HAS_ICON_LOCATION | _IS_UNICODE
)
#: the StringData fields, in the order the format keeps them
_STRINGS = (_HAS_NAME, _HAS_RELATIVE_PATH, _HAS_WORKING_DIR, _HAS_ARGUMENTS, _HAS_ICON_LOCATION)
#: LinkInfo's header with the offsets of the Unicode paths; VolumeIDAndLocalBasePath; DRIVE_FIXED
_INFO_HEADER_SIZE, _VOLUME_AND_LOCAL_PATH, _DRIVE_FIXED = 0x24, 0x1, 3
#: the system code page of a German (and any Western) Windows, for the ANSI copy of the target
_ANSI = "cp1252"


def _counted(value: str) -> bytes:
    """A StringData field: the count of UTF-16 code units, then the string (no NUL)."""
    data = value.encode("utf-16-le")
    if len(data) // 2 > 0xFFFF:
        raise ShortcutError("A path or setting this long can't be put into a shortcut.")
    return struct.pack("<H", len(data) // 2) + data


def _link_info(target: str) -> bytes:
    """LinkInfo: the target as a local path on a fixed drive, in the ANSI code page and in Unicode."""
    volume = struct.pack("<4I", 0x11, _DRIVE_FIXED, 0, 0x10) + b"\0"  # no serial number, no label
    ansi = target.encode(_ANSI, "replace") + b"\0"
    wide = target.encode("utf-16-le") + b"\0\0"
    base_at = _INFO_HEADER_SIZE + len(volume)
    suffix_at = base_at + len(ansi)
    wide_at = suffix_at + 1
    wide_suffix_at = wide_at + len(wide)
    size = wide_suffix_at + 2
    offsets = (size, _INFO_HEADER_SIZE, _VOLUME_AND_LOCAL_PATH, _INFO_HEADER_SIZE, base_at, 0, suffix_at)
    head = struct.pack("<9I", *offsets, wide_at, wide_suffix_at)
    # the common path suffixes are empty: the base paths are the whole target
    return head + volume + ansi + b"\0" + wide + b"\0\0"


def lnk_bytes(link: WindowsLink) -> bytes:
    """``link`` as a shell link file (MS-SHLLINK, Unicode strings), written without any Windows API."""
    header = _HEADER.pack(_HEADER_SIZE, _LINK_CLSID, _LINK_FLAGS, 0, 0, 0, 0, 0, 0, link.show, 0, 0, 0, 0)
    strings = (link.description, link.working_dir, link.arguments, link.icon)
    # the extra data is only its terminal block
    return header + _link_info(link.target) + b"".join(_counted(value) for value in strings) + b"\0\0\0\0"


def _nul_terminated(data: bytes, start: int, width: int) -> bytes:
    end = start
    while data[end : end + width] != b"\0" * width:
        end += width
        if end + width > len(data):
            raise ValueError("a string runs past the end of the link")
    return data[start:end]


def _target(info: bytes) -> str:
    _size, header_size, flags, _volume_at, base_at, _network_at, suffix_at = struct.unpack_from("<7I", info)
    if not flags & _VOLUME_AND_LOCAL_PATH:
        return ""
    if header_size >= _INFO_HEADER_SIZE:
        wide_at, wide_suffix_at = struct.unpack_from("<2I", info, 28)
        parts = (_nul_terminated(info, wide_at, 2), _nul_terminated(info, wide_suffix_at, 2))
        return "".join(part.decode("utf-16-le") for part in parts)
    parts = (_nul_terminated(info, base_at, 1), _nul_terminated(info, suffix_at, 1))
    return "".join(part.decode(_ANSI, "replace") for part in parts)


def _parse_lnk(data: bytes) -> WindowsLink | None:
    fields = _HEADER.unpack_from(data)
    if fields[0] != _HEADER_SIZE or fields[1] != _LINK_CLSID:
        return None
    flags, show = fields[2], fields[9]
    at = _HEADER_SIZE
    if flags & _HAS_ID_LIST:
        (size,) = struct.unpack_from("<H", data, at)
        at += 2 + size
    target = ""
    if flags & _HAS_LINK_INFO:
        (size,) = struct.unpack_from("<I", data, at)
        if at + size > len(data):
            raise ValueError("the LinkInfo runs past the end of the link")
        target = _target(data[at : at + size])
        at += size
    strings: dict[int, str] = {}
    for flag in _STRINGS:
        if flags & flag:
            (count,) = struct.unpack_from("<H", data, at)
            width = 2 if flags & _IS_UNICODE else 1
            end = at + 2 + count * width
            if end > len(data):
                raise ValueError("a string runs past the end of the link")
            raw = data[at + 2 : end]
            strings[flag] = raw.decode("utf-16-le") if width == 2 else raw.decode(_ANSI, "replace")
            at = end
    if len(data) < at + 4:
        raise ValueError("the link has no terminal block")
    return WindowsLink(
        target=target,
        arguments=strings.get(_HAS_ARGUMENTS, ""),
        working_dir=strings.get(_HAS_WORKING_DIR, ""),
        icon=strings.get(_HAS_ICON_LOCATION, ""),
        description=strings.get(_HAS_NAME, ""),
        show=show,
    )


def read_lnk(data: bytes) -> WindowsLink | None:
    """The fields of a shell link written by :func:`lnk_bytes` (``None`` when ``data`` isn't one)."""
    try:
        return _parse_lnk(data)
    except (struct.error, ValueError):
        return None


def split_cmdline(line: str) -> list[str]:
    """The arguments ``python.exe`` reads from a Windows command line (MS C runtime rules): the
    inverse of :func:`subprocess.list2cmdline`."""
    args: list[str] = []
    word: list[str] = []
    started = quoted = False
    at = 0
    while at < len(line):
        char = line[at]
        if char == "\\":
            end = at
            while end < len(line) and line[end] == "\\":
                end += 1
            count = end - at
            if end < len(line) and line[end] == '"':
                # 2n backslashes and a quote: n backslashes, and the quote opens or closes;
                # 2n+1: n backslashes and a literal quote
                word.append("\\" * (count // 2) + ('"' if count % 2 else ""))
                end += count % 2
            else:
                word.append("\\" * count)
            started, at = True, end
            continue
        if char == '"':
            quoted, started = not quoted, True
        elif char in " \t" and not quoted:
            if started:
                args.append("".join(word))
                word, started = [], False
        else:
            word.append(char)
            started = True
        at += 1
    if started:
        args.append("".join(word))
    return args


def _windows(argv: tuple[str, ...], env: Mapping[str, str], home: Path) -> Shortcut:
    roaming = Path(env.get("APPDATA") or home / "AppData" / "Roaming")
    local = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
    path = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / LNK
    icon = local / "Programs" / "Ordnung" / ICO
    link = WindowsLink(
        target=argv[0],
        arguments=subprocess.list2cmdline(argv[1:]),
        working_dir=str(home),
        icon=str(icon),
        description=DESCRIPTION,
    )
    # the icon first: the link is written once it has its icon
    files = (File(icon, None), File(path, lnk_bytes(link)))
    return Shortcut(system="windows", path=path, argv=argv, files=files, link=link)


def _link_argv(path: Path) -> tuple[Owner, list[str] | None]:
    link = read_lnk(_read_bytes(path))
    if link is None or not link.description.endswith(LNK_MARK):
        return "other", None
    return "ours", [link.target, *split_cmdline(link.arguments)]


# --------------------------------------------------------------------------------------------------
# icons (drawn only by write)
# --------------------------------------------------------------------------------------------------

_TEAL, _PAPER, _DISC, _CHECK = (0x0F, 0x6E, 0x66), (0xF7, 0xF5, 0xF0), (0xFC, 0xD3, 0x4D), (0x0B, 0x4F, 0x49)
#: the bars' opacity in the favicon (on the paper)
_FADED = 0.55
#: drawn this many times larger, then scaled down: smooth edges
_SUPERSAMPLE = 4


def draw_logo(size: int) -> Image.Image:
    """Ordnung's logo (``web/public/favicon.svg``) at ``size`` pixels, drawn with Pillow (imported here)."""
    from PIL import Image, ImageDraw

    unit = size * _SUPERSAMPLE / 64  # the favicon is 64 units wide
    canvas = Image.new("RGBA", (size * _SUPERSAMPLE, size * _SUPERSAMPLE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    def box(x: float, y: float, width: float, height: float) -> tuple[float, float, float, float]:
        return (x * unit, y * unit, (x + width) * unit - 1, (y + height) * unit - 1)

    faded = tuple(round(t * _FADED + p * (1 - _FADED)) for t, p in zip(_TEAL, _PAPER, strict=True))
    draw.rounded_rectangle(box(0, 0, 64, 64), radius=14 * unit, fill=_TEAL)
    draw.rounded_rectangle(box(16, 14, 32, 38), radius=4 * unit, fill=_PAPER)
    for y, width, colour in ((22, 20, _TEAL), (29, 14, faded), (36, 17, faded)):
        draw.rounded_rectangle(box(22, y, width, 3), radius=1.5 * unit, fill=colour)
    draw.ellipse(box(35, 37, 18, 18), fill=_DISC)
    check = [(40 * unit, 46 * unit), (43 * unit, 49 * unit), (48 * unit, 43 * unit)]
    stroke = 2.6 * unit
    draw.line(check, fill=_CHECK, width=round(stroke), joint="curve")
    for cx, cy in (check[0], check[-1]):  # round caps
        draw.ellipse((cx - stroke / 2, cy - stroke / 2, cx + stroke / 2, cy + stroke / 2), fill=_CHECK)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def _png(size: int) -> bytes:
    """The logo as a PNG that carries :data:`MARK` (so an icon outside the launcher is known as ours)."""
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("Comment", MARK)
    out = io.BytesIO()
    draw_logo(size).save(out, "PNG", pnginfo=info)
    return out.getvalue()


def _ico() -> bytes:
    """A Windows icon of PNG pictures (Windows Vista and later read them at every size)."""
    pictures = [(size, _png(size)) for size in ICO_SIZES]
    at = 6 + 16 * len(pictures)
    entries = []
    for size, picture in pictures:
        # width and height 0 mean 256; no palette; one plane; 32 bits per pixel
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(picture), at))
        at += len(picture)
    return struct.pack("<HHH", 0, 1, len(pictures)) + b"".join(entries) + b"".join(p for _, p in pictures)


def _icns() -> bytes:
    """A macOS icon of PNG pictures."""
    entries = b"".join(
        kind.encode("ascii") + struct.pack(">I", 8 + len(picture)) + picture
        for kind, picture in ((kind, _png(size)) for kind, size in ICNS_ENTRIES)
    )
    return b"icns" + struct.pack(">I", 8 + len(entries)) + entries


def _icon_bytes(path: Path) -> bytes:
    return _icns() if path.suffix == ".icns" else _ico()


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
) -> Shortcut:
    """The launcher that opens Ordnung for ``data_dir`` on this (or the given) platform. Raises
    :class:`ShortcutError` for a value with a line break."""
    system = autostart.system_of(platform)
    env = os.environ if env is None else env
    home = home or Path.home()
    argv = shortcut_argv(Path(data_dir).expanduser().absolute(), port=port, python=python)
    recorded = autostart._recorded(env, "PATH", TELEMETRY_OPT_OUT)
    _no_line_breaks([*argv, *recorded.values(), str(home)])
    builders = {"linux": _linux, "macos": _macos, "windows": _windows}
    sc = builders[system](argv, env, home)
    _no_line_breaks([str(file.path) for file in sc.files])
    return sc


def location(
    *, platform: str | None = None, env: Mapping[str, str] | None = None, home: Path | None = None
) -> Shortcut:
    """Where the launcher lives on this platform (its content is irrelevant here)."""
    env = os.environ if env is None else env
    place = {name: env[name] for name in PLACE_VARIABLES if name in env}
    return plan(Path("/"), platform=platform, env=place, home=home, python="python")


def command(data_dir: Path, *, default: Path | None = None) -> str:
    """``ordnung shortcut`` for ``data_dir`` (``--data-dir`` unless it is the default folder): what Settings
    and the CLI's hints offer."""
    return autostart.folder_command(COMMAND, data_dir, default=default)


def _read_bytes(path: Path) -> bytes:
    if path.stat().st_size > _MAX_READ:
        raise ValueError(f"{path} is too big to be a launcher Ordnung wrote")
    return path.read_bytes()


def _read_text(path: Path) -> str:
    return _read_bytes(path).decode("utf-8")


def _inspect(sc: Shortcut) -> tuple[Owner, list[str] | None]:
    """Whose launcher is at ``sc``'s place (nobody's, Ordnung's or someone else's), and what it runs."""
    if sc.path.is_symlink():
        return "other", None  # Ordnung writes no links: never follow one
    if not sc.path.exists():
        return "none", None
    try:
        if sc.system == "macos":
            return _bundle_argv(sc)
        if not sc.path.is_file():
            return "other", None
        return _desktop_argv(sc.path) if sc.system == "linux" else _link_argv(sc.path)
    except (OSError, UnicodeDecodeError, ValueError, plistlib.InvalidFileException, ExpatError):
        return "other", None  # a property list cut short (XML) raises ExpatError


def _marked_icon(path: Path) -> bool:
    """An icon outside the launcher (Windows) that Ordnung drew: it carries :data:`MARK`."""
    try:
        return not path.is_symlink() and MARK.encode("utf-8") in _read_bytes(path)
    except (OSError, ValueError):
        return False


def _not_ours(path: Path) -> ShortcutError:
    return ShortcutError(f"{path} wasn't written by `ordnung shortcut`, so it was left as it is.")


def _outside(sc: Shortcut, file: File) -> bool:
    """A file of the launcher that isn't inside its own place (the Windows icon)."""
    return file.path != sc.path and sc.path not in file.path.parents


def check(sc: Shortcut) -> Owner:
    """Whose launcher is at ``sc``'s place, after the checks :func:`write` starts with (a dry run makes them
    too, so it refuses what the real run would). Raises :class:`ShortcutError` for a launcher there, or a
    file of it outside its place (the Windows icon), that ``ordnung shortcut`` didn't write."""
    owner, _argv = _inspect(sc)
    if owner == "other":
        raise _not_ours(sc.path)
    for file in sc.files:
        there = file.path.is_symlink() or file.path.exists()
        if there and _outside(sc, file) and not _marked_icon(file.path):
            raise _not_ours(file.path)
    return owner


def write(sc: Shortcut) -> WriteStatus:
    """Write ``sc``'s files (icons drawn here); an identical launcher is left as it is. Raises
    :class:`ShortcutError` for a launcher at that place that ``ordnung shortcut`` didn't write."""
    owner = check(sc)

    def same(file: File) -> bool:
        if file.content is None:  # an icon: only that it is there
            return file.path.is_file()
        try:
            return file.path.is_file() and _read_bytes(file.path) == file.content
        except (OSError, ValueError):
            return False

    if owner == "ours" and all(same(file) for file in sc.files):
        return "unchanged"
    for file in sc.files:
        if same(file):
            continue
        content = _icon_bytes(file.path) if file.content is None else file.content
        file.path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(file.path, content, mode=file.mode, sync=False)
    return "added" if owner == "none" else "updated"


def removable(sc: Shortcut) -> list[Path]:
    """The files :func:`remove` would delete at ``sc``'s place: the launcher's own, and an icon Ordnung drew
    outside it (Windows) even when the launcher itself was deleted by hand. Raises :class:`ShortcutError`
    when the launcher there isn't ours."""
    owner, _argv = _inspect(sc)
    if owner == "other":
        raise _not_ours(sc.path)
    outside = [
        file.path
        for file in sc.files
        if _outside(sc, file) and file.path.is_file() and _marked_icon(file.path)
    ]
    if owner == "none":
        return outside
    # the mark last: a launcher that is half removed is still known as Ordnung's own
    inside = [
        file.path
        for file in reversed(sc.files)
        if not _outside(sc, file) and not file.path.is_symlink() and file.path.is_file()
    ]
    return outside + inside


def remove(sc: Shortcut) -> list[Path]:
    """Remove the launcher's own files at ``sc``'s location (a bundle folder once it is empty);
    returns what was removed. Raises :class:`ShortcutError` when the launcher there isn't ours."""
    going = removable(sc)
    for path in going:
        path.unlink()
    if going:
        folders = {file.path.parent for file in sc.files if file.path.parent != sc.path.parent}
        if sc.system == "macos":
            folders |= {sc.path / "Contents", sc.path}
        for folder in sorted(folders, key=lambda path: len(path.parts), reverse=True):
            with contextlib.suppress(OSError):  # not empty: it holds files that aren't Ordnung's
                folder.rmdir()
    return going


def state(
    data_dir: Path | None = None,
    *,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
    python: str | None = None,
) -> State:
    """Is there a launcher, is it ours, which data folder does it open, and is it what :func:`plan`
    would write now for ``data_dir`` (default: its own folder)? The recorded variables are not
    compared, as for autostart. Draws no icon."""
    where = location(platform=platform, env=env, home=home)
    owner, found = _inspect(where)
    if owner == "none":
        return State(system=where.system, path=where.path, added=False)
    if owner == "other":
        return State(system=where.system, path=where.path, added=True, ours=False)
    argv = found or []
    folder = Path(argv[argv.index("--data-dir") + 1]) if "--data-dir" in argv[:-1] else None
    wanted = Path(data_dir).expanduser().absolute() if data_dir is not None else folder
    current = (
        wanted is not None
        and argv == list(shortcut_argv(wanted, port=autostart._port_of(argv), python=python))
        and all(file.path.is_file() for file in where.files)
    )
    return State(system=where.system, path=where.path, added=True, data_dir=folder, current=current)
