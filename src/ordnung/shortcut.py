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
  description's "(added by ordnung shortcut)". A file at that place without the mark is never
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
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ordnung import autostart

if TYPE_CHECKING:
    from PIL import Image

System = autostart.System
WriteStatus = autostart.WriteStatus

MARK = "Written by `ordnung shortcut`; `ordnung shortcut --remove` removes it."
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

_NOT_BUILT = "`ordnung shortcut` isn't built yet."


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
        raise NotImplementedError(_NOT_BUILT)


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
    raise NotImplementedError(_NOT_BUILT)


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
    raise NotImplementedError(_NOT_BUILT)


def location(
    *, platform: str | None = None, env: Mapping[str, str] | None = None, home: Path | None = None
) -> Shortcut:
    """Where the launcher lives on this platform (its content is irrelevant here)."""
    raise NotImplementedError(_NOT_BUILT)


def write(sc: Shortcut) -> WriteStatus:
    """Write ``sc``'s files (icons drawn here); an identical launcher is left as it is. Raises
    :class:`ShortcutError` for a launcher at that place that ``ordnung shortcut`` didn't write."""
    raise NotImplementedError(_NOT_BUILT)


def remove(sc: Shortcut) -> list[Path]:
    """Remove the launcher's own files at ``sc``'s location (a bundle folder once it is empty);
    returns what was removed. Raises :class:`ShortcutError` when the launcher there isn't ours."""
    raise NotImplementedError(_NOT_BUILT)


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
    raise NotImplementedError(_NOT_BUILT)


def desktop_quote(value: str) -> str:
    """``value`` as one argument of a ``.desktop`` ``Exec`` line (module policy)."""
    raise NotImplementedError(_NOT_BUILT)


def desktop_unquote(exec_value: str) -> list[str]:
    """The arguments of an ``Exec`` value written by :func:`desktop_quote`."""
    raise NotImplementedError(_NOT_BUILT)


def sh_quote(value: str) -> str:
    """``value`` as one ``sh`` word in single quotes (module policy)."""
    raise NotImplementedError(_NOT_BUILT)


def lnk_bytes(link: WindowsLink) -> bytes:
    """``link`` as a shell link file (MS-SHLLINK, Unicode strings), written without any Windows API."""
    raise NotImplementedError(_NOT_BUILT)


def read_lnk(data: bytes) -> WindowsLink | None:
    """The fields of a shell link written by :func:`lnk_bytes` (``None`` when ``data`` isn't one)."""
    raise NotImplementedError(_NOT_BUILT)


def draw_logo(size: int) -> Image.Image:
    """Ordnung's logo (``web/public/favicon.svg``) at ``size`` pixels, drawn with Pillow (imported here)."""
    raise NotImplementedError(_NOT_BUILT)
