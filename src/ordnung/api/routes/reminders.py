"""Reminders outside the browser (Settings → Reminders): the morning desktop notification, whether
Ordnung starts at login, and whether it opens from the app menu.

``GET /api/reminders/desktop`` says which tool this computer shows notifications with, exactly what
today's notification would say in each mode (built by code from the agenda — the text the daily tick
shows, :mod:`ordnung.notify.desktop`), the day it was last shown, the last one the system couldn't
show, and whether ``ordnung autostart`` starts this data folder at login (:mod:`ordnung.autostart`;
read only — the web app never writes it). The command it offers sets up *this* data folder
(``--data-dir`` when it isn't the default one); the demo offers none — it doesn't start at login.
It also says whether ``ordnung shortcut`` put Ordnung in this computer's app menu, and for which data
folder (:mod:`ordnung.shortcut`; read only as well).
``?preview=false`` leaves today's texts out (they are built from the agenda): the app's check for
background problems on every page needs only the last day shown and the last failure.
``POST /api/reminders/desktop/test`` shows today's notification now in the mode asked for — or a
sample, when nothing is due — without using the day up.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from platformdirs import user_data_dir
from pydantic import BaseModel, ConfigDict, Field

from ordnung import autostart, shortcut
from ordnung.api.deps import CtxDep, StateDep
from ordnung.app_context import AppContext
from ordnung.assistant.mcp_install import shell_join
from ordnung.notify import desktop
from ordnung.tick import local_today

router = APIRouter(tags=["reminders"])

AUTOSTART_COMMAND = "ordnung autostart enable"
SHORTCUT_COMMAND = "ordnung shortcut"
SAMPLE = desktop.Notification(
    title="Ordnung", body="Nothing is due this week. This is how Ordnung will tell you."
)


class NotificationText(BaseModel):
    """What a desktop notification says."""

    title: str
    body: str


class DesktopPreview(BaseModel):
    """Today's notification in each mode (``null``: nothing is due, so none would be shown)."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    discreet: NotificationText | None = None
    full: NotificationText | None = None


class AutostartInfo(BaseModel):
    """Whether ``ordnung autostart`` starts Ordnung at login, and for which data folder."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    enabled: bool
    kind: str = Field(description="systemd user service, LaunchAgent or Startup folder")
    path: str = Field(description="The entry's file")
    points_here: bool = Field(description="The entry starts this data folder")
    command: str | None = Field(
        default=AUTOSTART_COMMAND,
        description="The command that starts this data folder at login (null: the demo, which doesn't)",
    )


class ShortcutInfo(BaseModel):
    """Whether ``ordnung shortcut`` put Ordnung in this computer's app menu, and for which data folder."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    added: bool
    kind: str = Field(description="app menu entry, app in your Applications folder or Start menu shortcut")
    path: str = Field(description="The launcher's file (or the Ordnung.app folder)")
    points_here: bool = Field(description="The launcher opens this data folder")
    command: str | None = Field(
        default=SHORTCUT_COMMAND,
        description="The command that adds it for this data folder (null: the demo, which isn't added)",
    )


class DesktopReminders(BaseModel):
    """What Settings shows about the morning desktop notification and how Ordnung starts on this computer."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    system: Literal["linux", "macos", "windows"]
    tool: str | None = Field(
        default=None, description="notify-send, osascript or powershell (null: none found)"
    )
    missing: str | None = Field(default=None, description="Why no notification can be shown, if so")
    preview: DesktopPreview
    last_shown_on: str | None = Field(
        default=None, description="The last day the morning notification was shown (or done with)"
    )
    last_failure: str | None = Field(
        default=None, description="Why the system couldn't show the last notification (null: it could)"
    )
    last_failure_on: str | None = Field(default=None, description="The day of that failure")
    demo: bool = Field(default=False, description="The demo: it never notifies on its own")
    autostart: AutostartInfo
    shortcut: ShortcutInfo


class DesktopTestRequest(BaseModel):
    """Which mode to show the test notification in."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["discreet", "full"] = "discreet"


class DesktopTestResult(BaseModel):
    """Whether the test notification was shown, and what it said."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    shown: bool
    tool: str | None = None
    notification: NotificationText
    detail: str | None = None


def _text(note: desktop.Notification | None) -> NotificationText | None:
    return NotificationText(title=note.title, body=note.body) if note is not None else None


def _command(command: str, data_dir: Path, default: Path | None) -> str:
    """``command`` for ``data_dir`` — with ``--data-dir`` unless it is the default folder (the
    platform's, not ``ORDNUNG_HOME``: the command runs in another terminal)."""
    folder = data_dir.expanduser().absolute()
    standard = (default or Path(user_data_dir("ordnung", appauthor=False))).expanduser().absolute()
    if folder.resolve() == standard.resolve():
        return command
    return shell_join([*command.split(), "--data-dir", str(folder)])


def autostart_command(data_dir: Path, *, default: Path | None = None) -> str:
    """``ordnung autostart enable`` for ``data_dir``."""
    return _command(AUTOSTART_COMMAND, data_dir, default)


def shortcut_command(data_dir: Path, *, default: Path | None = None) -> str:
    """``ordnung shortcut`` for ``data_dir``."""
    return _command(SHORTCUT_COMMAND, data_dir, default)


def _shortcut_info(ctx: AppContext, kind: desktop.SystemKind, demo: bool) -> ShortcutInfo:
    """The launcher as Settings shows it: a file check and a small read (:func:`ordnung.shortcut.state`).
    A launcher Ordnung didn't write isn't reported as added: ``ordnung shortcut`` would refuse to
    replace it."""
    here = ctx.paths.data_dir.expanduser().absolute()
    command = None if demo else shortcut_command(ctx.paths.data_dir)
    try:
        found = shortcut.state(ctx.paths.data_dir)
    except (shortcut.ShortcutError, OSError):
        return ShortcutInfo(
            added=False, kind=shortcut.KINDS[kind], path="", points_here=False, command=command
        )
    added = found.added and found.ours
    return ShortcutInfo(
        added=added,
        kind=found.kind,
        path=str(found.path),
        points_here=added and found.data_dir == here,
        command=command,
    )


def _status(ctx: AppContext, demo: bool, preview: bool) -> DesktopReminders:
    store = ctx.store
    texts = desktop.preview(store, local_today(store)) if preview else {"discreet": None, "full": None}
    found = desktop.detect()
    kind = desktop.system_kind()
    entry = autostart.state(ctx.paths.data_dir)
    here = ctx.paths.data_dir.expanduser().absolute()
    failure = desktop.last_failure(store)
    return DesktopReminders(
        system=kind,
        tool=found[0] if found else None,
        missing=None if found else desktop.MISSING_TOOL[kind],
        preview=DesktopPreview(discreet=_text(texts["discreet"]), full=_text(texts["full"])),
        last_shown_on=store.get_meta(desktop.LAST_SHOWN_KEY),
        last_failure=failure.detail if failure else None,
        last_failure_on=failure.day if failure else None,
        demo=demo,
        autostart=AutostartInfo(
            enabled=entry.enabled,
            kind=entry.kind,
            path=str(entry.path),
            points_here=entry.enabled and entry.data_dir == here,
            command=None if demo else autostart_command(ctx.paths.data_dir),
        ),
        shortcut=_shortcut_info(ctx, kind, demo),
    )


@router.get("/reminders/desktop", response_model=DesktopReminders)
async def desktop_reminders(
    state: StateDep,
    ctx: CtxDep,
    preview: Annotated[bool, Query(description="Include today's texts (built from the agenda)")] = True,
) -> DesktopReminders:
    """The desktop notification's tool, today's text in each mode (unless ``preview`` is false: both
    ``null``), the start-at-login entry and the app-menu shortcut."""
    demo = state.demo or ctx.store.get_settings().demo
    return await asyncio.to_thread(_status, ctx, demo, preview)


def _test(ctx: AppContext, mode: desktop.Mode) -> DesktopTestResult:
    store = ctx.store
    outcome = desktop.show(store, local_today(store), mode, sender=lambda note: desktop.send(note))
    note, result = outcome.notification, outcome.result
    if note is None or result is None:
        note, result = SAMPLE, desktop.send(SAMPLE)
    return DesktopTestResult(
        shown=result.sent,
        tool=result.mechanism,
        notification=NotificationText(title=note.title, body=note.body),
        detail=result.detail,
    )


@router.post("/reminders/desktop/test", response_model=DesktopTestResult)
async def desktop_test(body: DesktopTestRequest, ctx: CtxDep) -> DesktopTestResult:
    """Show today's notification now (a sample when nothing is due); the morning one still comes."""
    return await asyncio.to_thread(_test, ctx, body.mode)
