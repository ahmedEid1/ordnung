"""Reminders outside the browser (Settings → Reminders): the morning desktop notification and whether
Ordnung starts at login.

``GET /api/reminders/desktop`` says which tool this computer shows notifications with, exactly what
today's notification would say in each mode (built by code from the agenda — the text the daily tick
shows, :mod:`ordnung.notify.desktop`), the day it was last shown, the last one the system couldn't
show, and whether ``ordnung autostart`` starts this data folder at login (:mod:`ordnung.autostart`;
read only — the web app never writes it). The command it offers sets up *this* data folder
(``--data-dir`` when it isn't the default one); the demo offers none — it doesn't start at login.
``POST /api/reminders/desktop/test`` shows today's notification now in the mode asked for — or a
sample, when nothing is due — without using the day up.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from fastapi import APIRouter
from platformdirs import user_data_dir
from pydantic import BaseModel, ConfigDict, Field

from ordnung import autostart
from ordnung.api.deps import CtxDep, StateDep
from ordnung.app_context import AppContext
from ordnung.assistant.mcp_install import shell_join
from ordnung.notify import desktop
from ordnung.tick import local_today

router = APIRouter(tags=["reminders"])

AUTOSTART_COMMAND = "ordnung autostart enable"
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


class DesktopReminders(BaseModel):
    """What Settings shows about the morning desktop notification."""

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


def autostart_command(data_dir: Path, *, default: Path | None = None) -> str:
    """``ordnung autostart enable`` for ``data_dir`` — with ``--data-dir`` unless it is the default
    folder (the platform's, not ``ORDNUNG_HOME``: the command runs in another terminal)."""
    folder = data_dir.expanduser().absolute()
    standard = (default or Path(user_data_dir("ordnung", appauthor=False))).expanduser().absolute()
    if folder.resolve() == standard.resolve():
        return AUTOSTART_COMMAND
    return shell_join(["ordnung", "autostart", "enable", "--data-dir", str(folder)])


def _status(ctx: AppContext, demo: bool) -> DesktopReminders:
    store = ctx.store
    today = local_today(store)
    texts = desktop.preview(store, today)
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
    )


@router.get("/reminders/desktop", response_model=DesktopReminders)
async def desktop_reminders(state: StateDep, ctx: CtxDep) -> DesktopReminders:
    """The desktop notification's tool, today's text in each mode, and the start-at-login entry."""
    demo = state.demo or ctx.store.get_settings().demo
    return await asyncio.to_thread(_status, ctx, demo)


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
