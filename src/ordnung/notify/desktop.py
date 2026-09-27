"""The morning desktop notification: what Ordnung says outside the browser, once a day (SPEC §12).

Written policy (ADR 0007):

* **What.** The day's deterministic agenda (:func:`~ordnung.secretary.brief.build_agenda` — code,
  no model, zero tokens): what is overdue, what is due today or in the next 7 days, and contract
  decisions whose send-by day is in the next 7 days. Letters with scam signs are never in it (the
  agenda leaves them out). Nothing to report, no notification.
* **Discreet** (the mode the web app switches on): the title is "Ordnung" and the text a count only
  — "2 things due this week", "1 thing overdue", "1 overdue · 2 due this week" — never a title, a
  name, an organisation or an amount, so a lock screen or a shared screen shows nothing private.
* **Full**: the title carries that count ("Ordnung · 2 things due this week"), the text the first
  three things — overdue first, then by day — with the amount of a payment and the day to act:
  "Pay the parking fine €30 by Thu · Decide on FitWell: cancel by Thu 8 Oct · and 1 more". The
  titles are letters' words: control and bidirectional characters are removed, whitespace is
  collapsed, a leading dash is dropped and each is cut to :data:`MAX_TITLE_CHARS` characters.
* **When.** Once per local day (the profile's time zone), at the first check at or after the chosen
  time (``settings.desktop_notify_time``, default 08:00). The daily tick checks every 15 minutes,
  so it comes up to 15 minutes after that time — or as soon as Ordnung starts, when it wasn't
  running then. The day is used up by the attempt, shown or not: a missing tool is not retried every
  15 minutes. The demo never notifies on its own.
* **How.** The system's own tool, no new dependency and never through a shell: ``notify-send``
  (Linux and other Unix desktops; the text's ``& < >`` escaped, as the notification servers read
  markup), ``osascript`` (macOS; a fixed script, the texts as its arguments) and Windows
  PowerShell's toast API (a fixed script, the texts in environment variables). A missing tool, an
  error or no answer within :data:`SEND_TIMEOUT_S` seconds shows nothing and breaks nothing — the
  result says why, and the person's other reminders (the calendar file's alarms) are unaffected.
"""

from __future__ import annotations

import base64
import html
import logging
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ordnung import clock
from ordnung.db.store import Store
from ordnung.models import AppSettings
from ordnung.rules.explain import fmt_date
from ordnung.secretary.brief import Agenda, AgendaEntry, build_agenda
from ordnung.secretary.triggers import money, parse_day

log = logging.getLogger(__name__)

Mode = Literal["off", "discreet", "full"]
Mechanism = Literal["notify-send", "osascript", "powershell"]
SystemKind = Literal["linux", "macos", "windows"]

APP_NAME = "Ordnung"
WEEK_DAYS = 7
MAX_LISTED = 3
MAX_TITLE_CHARS = 60
SEND_TIMEOUT_S = 10.0
DEFAULT_TIME = time(8, 0)
LAST_SHOWN_KEY = "desktop_notified_on"
TITLE_ENV = "ORDNUNG_NOTIFY_TITLE"
BODY_ENV = "ORDNUNG_NOTIFY_BODY"
#: Windows PowerShell's own app id: a toast needs a registered app to be shown under.
POWERSHELL_APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"
_TOAST_SCRIPT = f"""$ErrorActionPreference = 'Stop'
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
$title = [Security.SecurityElement]::Escape($env:{TITLE_ENV})
$body = [Security.SecurityElement]::Escape($env:{BODY_ENV})
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{POWERSHELL_APP_ID}').Show($toast)
"""
_OSASCRIPT = ("on run argv", "display notification (item 2 of argv) with title (item 1 of argv)", "end run")
# C0/C1 controls and bidirectional overrides: a letter's words must not reorder or hide the text
_CONTROL_RE = re.compile("[\x00-\x1f\x7f-\x9f؜‎‏‪-‮⁦-⁩]")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_MECHANISMS: dict[SystemKind, Mechanism] = {
    "macos": "osascript",
    "windows": "powershell",
    "linux": "notify-send",
}
MISSING_TOOL: dict[SystemKind, str] = {
    "linux": "No notification tool was found: install notify-send (the libnotify-bin or libnotify package).",
    "macos": "macOS's osascript was not found.",
    "windows": "Windows PowerShell was not found.",
}


@dataclass(frozen=True)
class Notification:
    """What the notification says."""

    title: str
    body: str


@dataclass(frozen=True)
class SendResult:
    """Whether the system showed it, with which tool, and why not."""

    sent: bool
    mechanism: Mechanism | None
    detail: str | None = None


@dataclass(frozen=True)
class Outcome:
    """What one morning check did (``None`` from :func:`morning_notification` when it wasn't time)."""

    day: date
    notification: Notification | None
    result: SendResult | None
    #: the discreet count ("2 things due this week"), ``None`` when nothing is due
    count: str | None = None


# --------------------------------------------------------------------------------------------------
# the text
# --------------------------------------------------------------------------------------------------


def clean(text: str, limit: int = MAX_TITLE_CHARS) -> str:
    """A letter's words fit for a notification (module policy)."""
    flat = " ".join(_CONTROL_RE.sub(" ", text).split()).lstrip("-–— ")
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def short_day(day: date, today: date) -> str:
    """``today`` / ``tomorrow`` / ``Thu`` (within the week) / ``Thu 8 Oct``."""
    days = (day - today).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    label = fmt_date(day, year=day.year != today.year)
    return label.split()[0] if 1 < days < WEEK_DAYS else label


def _plural(count: int, word: str = "thing") -> str:
    return f"{count} {word}{'s' if count != 1 else ''}"


@dataclass(frozen=True)
class _Thing:
    text: str
    day: date
    overdue: bool


def _amount(entry: AgendaEntry) -> str:
    return (
        f" {money(entry.amount, entry.currency)}"
        if entry.kind == "payment" and entry.amount is not None
        else ""
    )


def things_due(agenda: Agenda) -> list[_Thing]:
    """Everything the notification counts, in the order it lists them (overdue first, then by day)."""
    today = parse_day(agenda.date) or clock.today()
    found: list[_Thing] = []
    for entry in agenda.overdue:
        day = parse_day(entry.date) or today
        found.append(_Thing(f"{clean(entry.title)}{_amount(entry)} — overdue", day, True))
    for entry in [*agenda.today, *agenda.next_7_days]:
        day = parse_day(entry.date) or today
        when = "today" if day <= today else f"by {short_day(day, today)}"
        found.append(_Thing(f"{clean(entry.title)}{_amount(entry)} {when}", day, False))
    for entry in agenda.decisions:
        send_by = parse_day(entry.date)
        if send_by is not None and (send_by - today).days <= WEEK_DAYS:
            act = max(send_by, today)  # a missed send-by day means "act today", as on the agenda
            when = "today" if act == today else f"by {short_day(act, today)}"
            found.append(_Thing(f"Decide on {clean(entry.title)}: cancel {when}", act, False))
    return sorted(found, key=lambda thing: (not thing.overdue, thing.day))


def summary(things: Sequence[_Thing]) -> str:
    """The count, without any detail: ``2 things due this week`` / ``1 overdue · 2 due this week``."""
    overdue = sum(thing.overdue for thing in things)
    upcoming = len(things) - overdue
    if overdue and upcoming:
        return f"{overdue} overdue · {upcoming} due this week"
    if overdue:
        return f"{_plural(overdue)} overdue"
    return f"{_plural(upcoming)} due this week"


def _compose(things: Sequence[_Thing], mode: Mode) -> Notification | None:
    if mode == "off" or not things:
        return None
    count = summary(things)
    if mode == "discreet":
        return Notification(title=APP_NAME, body=count)
    listed = [thing.text for thing in things[:MAX_LISTED]]
    more = len(things) - len(listed)
    if more:
        listed.append(f"and {more} more")
    return Notification(title=f"{APP_NAME} · {count}", body=" · ".join(listed))


def compose(agenda: Agenda, mode: Mode) -> Notification | None:
    """The notification for ``agenda`` in ``mode`` (``None``: nothing to say, or switched off)."""
    return _compose(things_due(agenda), mode)


# --------------------------------------------------------------------------------------------------
# showing it
# --------------------------------------------------------------------------------------------------


def system_kind(system: str | None = None) -> SystemKind:
    """``macos``, ``windows`` or ``linux`` (every other Unix desktop counts as Linux here)."""
    platform = system or sys.platform
    if platform == "darwin":
        return "macos"
    if platform.startswith(("win", "cygwin")):
        return "windows"
    return "linux"


def detect(
    system: str | None = None, which: Callable[[str], str | None] | None = None
) -> tuple[Mechanism, str] | None:
    """The tool this system shows notifications with, and its path (``None`` when it is missing)."""
    which = which or shutil.which
    kind = system_kind(system)
    mechanism = _MECHANISMS[kind]
    path = which("powershell.exe" if kind == "windows" else mechanism)
    return (mechanism, path) if path else None


def command(mechanism: Mechanism, path: str, note: Notification) -> tuple[list[str], dict[str, str]]:
    """The argument list (never a shell line) and extra environment that show ``note``."""
    if mechanism == "notify-send":
        body = html.escape(note.body, quote=False)
        return [path, f"--app-name={APP_NAME}", "--", note.title, body], {}
    if mechanism == "osascript":
        script = [arg for line in _OSASCRIPT for arg in ("-e", line)]
        return [path, *script, note.title, note.body], {}
    encoded = base64.b64encode(_TOAST_SCRIPT.encode("utf-16-le")).decode("ascii")
    argv = [path, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]
    return argv, {TITLE_ENV: note.title, BODY_ENV: note.body}


Runner = Callable[..., Any]


def send(
    note: Notification,
    *,
    system: str | None = None,
    which: Callable[[str], str | None] | None = None,
    run: Runner | None = None,
) -> SendResult:
    """Show ``note`` with the system's tool (module policy); never raises."""
    found = detect(system, which)
    if found is None:
        return SendResult(sent=False, mechanism=None, detail=MISSING_TOOL[system_kind(system)])
    mechanism, path = found
    argv, extra = command(mechanism, path, note)
    run = run or subprocess.run
    try:
        done = run(
            argv,
            env={**os.environ, **extra} if extra else None,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=SEND_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SendResult(
            sent=False,
            mechanism=mechanism,
            detail=f"{mechanism} didn't answer within {SEND_TIMEOUT_S:.0f} seconds.",
        )
    except OSError as exc:
        return SendResult(
            sent=False, mechanism=mechanism, detail=f"{mechanism} couldn't be started: {exc.strerror or exc}"
        )
    code = getattr(done, "returncode", 0)
    if code != 0:
        return SendResult(sent=False, mechanism=mechanism, detail=f"{mechanism} failed (exit code {code}).")
    return SendResult(sent=True, mechanism=mechanism)


# --------------------------------------------------------------------------------------------------
# once a day
# --------------------------------------------------------------------------------------------------


def notify_time(settings: AppSettings) -> time:
    """The chosen time of day (``HH:MM``; 08:00 when unset or unreadable)."""
    match = _TIME_RE.match(settings.desktop_notify_time or "")
    return time(int(match[1]), int(match[2])) if match else DEFAULT_TIME


def local_now(store: Store) -> datetime:
    """Now in the person's time zone (``profile.timezone``; the system's zone when it is unknown)."""
    try:
        return datetime.now(ZoneInfo(store.get_profile().timezone))
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now().astimezone()


def is_due(settings: AppSettings, today: date, now: time, last_shown: str | None) -> bool:
    """Whether the morning notification is due now (module policy)."""
    if settings.desktop_notifications == "off" or settings.demo:
        return False
    return last_shown != today.isoformat() and now >= notify_time(settings)


def show(
    store: Store, today: date, mode: Mode, *, sender: Callable[[Notification], SendResult] = send
) -> Outcome:
    """Build today's notification in ``mode`` and show it now (the Settings test uses it too)."""
    things = things_due(build_agenda(store, today))
    note = _compose(things, mode)
    return Outcome(
        day=today,
        notification=note,
        result=sender(note) if note is not None else None,
        count=summary(things) if things else None,
    )


def morning_notification(
    store: Store,
    today: date,
    now: time,
    *,
    sender: Callable[[Notification], SendResult] = send,
) -> Outcome | None:
    """Show the day's notification if it is due (module policy); ``None`` when it wasn't time."""
    settings = store.get_settings()
    if not is_due(settings, today, now, store.get_meta(LAST_SHOWN_KEY)):
        return None
    store.set_meta(LAST_SHOWN_KEY, today.isoformat())  # the attempt uses the day up, whatever happens
    outcome = show(store, today, settings.desktop_notifications, sender=sender)
    if outcome.result is not None and outcome.result.sent:
        store.log_activity("notify.desktop", f"Showed the morning notification ({outcome.count})")
    elif outcome.result is not None:
        log.info("desktop notification not shown: %s", outcome.result.detail)
    return outcome
