"""The morning desktop notification: its text in discreet and full mode (from the deterministic
agenda, never a model), the tools that show it on each system (argument lists, never a shell), the
once-a-day policy, and the daily tick that calls it."""

from __future__ import annotations

import base64
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from time import monotonic
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.db.store import Store
from ordnung.llm.runtime import LLMService
from ordnung.models import RefLink
from ordnung.notify import desktop
from ordnung.notify.desktop import (
    LAST_SHOWN_KEY,
    Notification,
    SendResult,
    clean,
    command,
    compose,
    detect,
    is_due,
    morning_notification,
    notify_time,
    send,
    short_day,
    summary,
    things_due,
)
from ordnung.secretary.brief import Agenda, AgendaEntry, build_agenda
from ordnung.tick import DailyTick

MON = TODAY  # Mon 28 Sep 2026


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


def entry(
    title: str, day: date | None, kind: str = "payment", amount: float | None = None, **extra: Any
) -> AgendaEntry:
    return AgendaEntry(
        id=f"itm_{abs(hash(title)) % 10_000}",
        ref=RefLink(type="item", id="itm_x"),
        title=title,
        kind=kind,
        date=day.isoformat() if day else None,
        amount=amount,
        **extra,
    )


def agenda(**sections: list[AgendaEntry]) -> Agenda:
    return Agenda(date=MON.isoformat(), **sections)


# --------------------------------------------------------------------------------------------------
# the text
# --------------------------------------------------------------------------------------------------


def test_the_example_from_the_brief() -> None:
    week = agenda(
        next_7_days=[entry("Pay the parking fine", MON + timedelta(days=3), amount=30.0)],
        decisions=[entry("FitWell membership", MON + timedelta(days=3), kind="contract", amount=24.9)],
    )
    assert compose(week, "discreet") == Notification("Ordnung", "2 things due this week")
    assert compose(week, "full") == Notification(
        "Ordnung · 2 things due this week",
        "Pay the parking fine €30 by Thu · Decide on FitWell membership: cancel by Thu",
    )


def test_full_lists_today_then_overdue_then_by_day_and_counts_the_rest() -> None:
    week = agenda(
        overdue=[entry("Return library books", MON - timedelta(days=8), kind="task")],
        today=[entry("Call the Ausländerbehörde", MON, kind="task")],
        next_7_days=[
            entry("Semester fee", MON + timedelta(days=4), amount=320.5),
            entry("Pay TechMarkt reminder", MON + timedelta(days=1), amount=94.99),
            entry("Invoice in dollars", MON + timedelta(days=6), amount=50.0, currency="USD"),
        ],
    )
    note = compose(week, "full")
    assert note is not None
    assert note.title == "Ordnung · 1 due today · 1 overdue · 3 more this week"
    assert note.body == (
        "Call the Ausländerbehörde today · Return library books — overdue · "
        "Pay TechMarkt reminder €94.99 by tomorrow · and 2 more"
    )
    assert compose(week, "discreet") == Notification("Ordnung", "1 due today · 1 overdue · 3 more this week")


def test_what_ends_today_comes_before_old_small_payments() -> None:
    """The live demo on Thu 8 Oct: a legal objection's last day and a contract's last posting day
    must not hide behind a €4.50 library fee that is a week overdue."""
    thu = MON + timedelta(days=10)
    week = Agenda(
        date=thu.isoformat(),
        overdue=[
            entry("Pay outstanding invoice plus reminder fee", thu - timedelta(days=2), amount=94.99),
            entry("Pay accumulated library fees", thu - timedelta(days=7), amount=4.5),
            entry("Pay Verwarnungsgeld (traffic fine)", thu - timedelta(days=1), amount=30.0),
        ],
        today=[
            entry("Pay the rent", thu, amount=750.0),
            entry("Buy stamps", thu, kind="task"),
            entry("Object to contribution notice (Widerspruch)", thu, kind="deadline"),
        ],
        decisions=[entry("FunkNetz Smart M", thu, kind="contract")],
    )
    note = compose(week, "full")
    assert note is not None
    assert note.body == (
        "Object to contribution notice (Widerspruch) today · Decide on FunkNetz Smart M: cancel today · "
        "Buy stamps today · and 4 more"
    )
    assert compose(week, "discreet") == Notification("Ordnung", "4 due today · 3 overdue")


def test_appointments_say_their_day_and_time() -> None:
    week = agenda(
        today=[entry("Dental appointment", MON, kind="appointment")],
        next_7_days=[
            entry("Ausländerbehörde", MON + timedelta(days=1), kind="appointment"),
            entry("Bürgeramt", MON + timedelta(days=2), kind="appointment"),
            entry("Doctor", MON + timedelta(days=3), kind="appointment"),
        ],
    )
    times = {
        e.id: t for e, t in zip(week.today + week.next_7_days, ["09:15", "10:30", "08:00"], strict=False)
    }
    note = compose(week, "full", times)
    assert note is not None
    assert note.body == (
        "Dental appointment today 09:15 · Ausländerbehörde tomorrow 10:30 · Bürgeramt on Wed 08:00 · and 1 more"
    )
    doctor = things_due(week, times)[-1]
    assert doctor.text == "Doctor on Thu"  # no time known: the day only


def test_an_appointments_time_comes_from_its_to_do(store: Store) -> None:
    ids = seed_ledger(store)
    store.update_item(ids["abh_appointment"], due_date=(MON + timedelta(days=2)).isoformat())
    texts = desktop.preview(store, MON)
    assert (
        texts["full"] is not None and "Appointment at the Ausländerbehörde on Wed 10:00" in texts["full"].body
    )
    assert texts["discreet"] is not None and "10:00" not in texts["discreet"].body


def test_discreet_never_says_a_title_a_name_or_an_amount(store: Store) -> None:
    seed_ledger(store)
    week = build_agenda(store, MON)
    note = compose(week, "discreet")
    assert note is not None and note.title == "Ordnung"
    text = f"{note.title} {note.body}"
    assert all(ch.isdigit() or ch.isalpha() or ch in " ·" for ch in text)
    for item in week.entries():
        for secret in (item.title, item.party, str(item.amount) if item.amount else None):
            if secret:
                assert secret not in text
    assert "€" not in text


def test_the_seeded_week_in_both_modes(store: Store) -> None:
    seed_ledger(store)
    week = build_agenda(store, MON)
    assert compose(week, "discreet") == Notification("Ordnung", "1 overdue · 3 due this week")
    full = compose(week, "full")
    assert full is not None
    assert full.body.startswith("Return library books — overdue · Pay parking fine €25 by tomorrow")
    assert "broadcasting" not in full.body  # the scam letter's demand is never on the agenda


def test_nothing_due_or_switched_off_says_nothing() -> None:
    assert compose(agenda(), "full") is None
    assert compose(agenda(), "discreet") is None
    week = agenda(next_7_days=[entry("Pay rent", MON + timedelta(days=2), amount=700.0)])
    assert compose(week, "off") is None


def test_contract_decisions_count_only_within_the_week() -> None:
    week = agenda(
        decisions=[
            entry("Phone contract", MON + timedelta(days=7), kind="contract"),
            entry("Gym", MON + timedelta(days=8), kind="contract"),
            entry("Missed send-by", MON - timedelta(days=2), kind="contract"),
        ]
    )
    note = compose(week, "full")
    assert note is not None and note.title == "Ordnung · 1 due today · 1 more this week"
    assert (
        note.body == "Decide on Missed send-by: cancel today · Decide on Phone contract: cancel by Mon 5 Oct"
    )


@pytest.mark.parametrize(
    ("count", "overdue", "expected"),
    [
        (1, 0, "1 thing due this week"),
        (3, 0, "3 things due this week"),
        (1, 1, "1 thing overdue"),
        (2, 2, "2 things overdue"),
        (3, 1, "1 overdue · 2 due this week"),
    ],
)
def test_summary_wording(count: int, overdue: int, expected: str) -> None:
    things = [
        entry(f"t{i}", MON - timedelta(days=1) if i < overdue else MON + timedelta(days=1))
        for i in range(count)
    ]
    week = agenda(overdue=things[:overdue], next_7_days=things[overdue:])
    assert summary(things_due(week)) == expected


@pytest.mark.parametrize(
    ("today", "overdue", "later", "expected"),
    [
        (1, 0, 0, "1 thing due today"),
        (2, 0, 0, "2 things due today"),
        (2, 1, 0, "2 due today · 1 overdue"),
        (2, 0, 3, "2 due today · 3 more this week"),
        (3, 4, 5, "3 due today · 4 overdue · 5 more this week"),
    ],
)
def test_what_ends_today_is_counted_apart(today: int, overdue: int, later: int, expected: str) -> None:
    week = agenda(
        overdue=[entry(f"o{i}", MON - timedelta(days=1)) for i in range(overdue)],
        today=[entry(f"t{i}", MON) for i in range(today)],
        next_7_days=[entry(f"l{i}", MON + timedelta(days=2)) for i in range(later)],
    )
    assert summary(things_due(week)) == expected
    assert compose(week, "discreet") == Notification("Ordnung", expected)


def test_short_days() -> None:
    assert short_day(MON, MON) == "today"
    assert short_day(MON + timedelta(days=1), MON) == "tomorrow"
    assert short_day(MON + timedelta(days=2), MON) == "Wed"
    assert short_day(MON + timedelta(days=6), MON) == "Sun"
    assert short_day(MON + timedelta(days=7), MON) == "Mon 5 Oct"
    assert short_day(date(2027, 1, 2), date(2026, 12, 20)) == "Sat 2 Jan 2027"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Pay\nthe\tfine", "Pay the fine"),
        ("\u202eenif eht yaP", "enif eht yaP"),  # a right-to-left override can't reverse the text
        ("Pay\x1b]52;c;ZWNobw==\x07 now", "Pay ]52;c;ZWNobw== now"),  # no terminal/escape sequences
        ("-- --help", "help"),
        ("— Pay it", "Pay it"),
        ("x" * 80, "x" * 59 + "…"),
    ],
)
def test_letters_words_are_cleaned(raw: str, expected: str) -> None:
    assert clean(raw) == expected


def test_a_hostile_title_cannot_become_an_option_or_markup() -> None:
    week = agenda(
        next_7_days=[entry('--version <a href="https://evil">click</a> & "pay"', MON + timedelta(days=2))]
    )
    note = compose(week, "full")
    assert note is not None and not note.body.startswith("-")
    argv, _env = command("notify-send", "/usr/bin/notify-send", note)
    assert argv[:3] == ["/usr/bin/notify-send", "--app-name=Ordnung", "--"]
    assert "<a href" not in argv[-1] and "&lt;a href" in argv[-1] and "&amp;" in argv[-1]


# --------------------------------------------------------------------------------------------------
# showing it
# --------------------------------------------------------------------------------------------------

NOTE = Notification("Ordnung · 1 thing due this week", 'Pay "Rundfunkbeitrag" €18.36 by Thu $(rm -rf ~)')


def which_of(*present: str) -> Any:
    return lambda name: f"/usr/bin/{name}" if name in present else None


def test_detect_per_system() -> None:
    assert detect("linux", which_of("notify-send")) == ("notify-send", "/usr/bin/notify-send")
    assert detect("linux", which_of()) is None
    assert detect("freebsd14", which_of("notify-send")) == ("notify-send", "/usr/bin/notify-send")
    assert detect("darwin", which_of("osascript")) == ("osascript", "/usr/bin/osascript")
    assert detect("win32", which_of("powershell.exe")) == ("powershell", "/usr/bin/powershell.exe")
    assert detect("win32", which_of("pwsh")) is None  # PowerShell 7 can't load the toast API


def test_osascript_gets_the_texts_as_arguments_of_a_fixed_script() -> None:
    argv, env = command("osascript", "/usr/bin/osascript", NOTE)
    assert argv == [
        "/usr/bin/osascript",
        "-e",
        "on run argv",
        "-e",
        "display notification (item 2 of argv) with title (item 1 of argv)",
        "-e",
        "end run",
        NOTE.title,
        NOTE.body,
    ]
    assert env == {}


def test_powershell_gets_the_texts_in_the_environment_of_a_fixed_script() -> None:
    argv, env = command("powershell", "C:/Windows/powershell.exe", NOTE)
    assert argv[:6] == [
        "C:/Windows/powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-EncodedCommand",
    ]
    script = base64.b64decode(argv[6]).decode("utf-16-le")
    assert script == desktop._TOAST_SCRIPT
    assert "Rundfunkbeitrag" not in script and "$env:ORDNUNG_NOTIFY_BODY" in script
    assert "SecurityElement]::Escape" in script
    assert env == {"ORDNUNG_NOTIFY_TITLE": NOTE.title, "ORDNUNG_NOTIFY_BODY": NOTE.body}


@dataclass
class FakeRun:
    returncode: int = 0
    raises: BaseException | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, argv: list[str], **kwargs: Any) -> Any:
        self.calls.append({"argv": argv, **kwargs})
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, b"", b"")


def test_send_runs_the_tool_without_a_shell() -> None:
    run = FakeRun()
    result = send(NOTE, system="linux", which=which_of("notify-send"), run=run)
    assert result == SendResult(sent=True, mechanism="notify-send")
    call = run.calls[0]
    assert isinstance(call["argv"], list) and "shell" not in call
    assert call["argv"][-2] == NOTE.title
    assert call["argv"][-1] == 'Pay "Rundfunkbeitrag" €18.36 by Thu $(rm -rf ~)'  # passed as it is, never run
    assert call["timeout"] == desktop.SEND_TIMEOUT_S and call["stdin"] == subprocess.DEVNULL
    assert call["env"] is None


def test_send_on_windows_adds_the_texts_to_the_environment() -> None:
    run = FakeRun()
    assert send(NOTE, system="win32", which=which_of("powershell.exe"), run=run).sent
    env = run.calls[0]["env"]
    assert env["ORDNUNG_NOTIFY_BODY"] == NOTE.body and "PATH" in env


@pytest.mark.parametrize(
    ("run", "detail"),
    [
        (FakeRun(returncode=1), "failed (exit code 1)"),
        (FakeRun(raises=subprocess.TimeoutExpired("notify-send", 10)), "didn't answer within 10 seconds"),
        (FakeRun(raises=FileNotFoundError(2, "No such file")), "couldn't be started"),
    ],
)
def test_send_fails_quietly(run: FakeRun, detail: str) -> None:
    result = send(NOTE, system="linux", which=which_of("notify-send"), run=run)
    assert not result.sent and result.mechanism == "notify-send"
    assert result.detail is not None and detail in result.detail


def test_a_missing_tool_is_explained() -> None:
    result = send(NOTE, system="linux", which=which_of(), run=FakeRun())
    assert result == SendResult(sent=False, mechanism=None, detail=desktop.MISSING_TOOL["linux"])
    assert "notify-send" in (result.detail or "")


# --------------------------------------------------------------------------------------------------
# once a day
# --------------------------------------------------------------------------------------------------


@dataclass
class Sender:
    sent: bool = True
    notes: list[Notification] = field(default_factory=list)

    def __call__(self, note: Notification) -> SendResult:
        self.notes.append(note)
        return SendResult(sent=self.sent, mechanism="notify-send", detail=None if self.sent else "no tool")


def switch_on(store: Store, mode: str = "discreet", at: str = "08:00", **extra: Any) -> None:
    settings = store.get_settings().model_copy(
        update={"desktop_notifications": mode, "desktop_notify_time": at, **extra}
    )
    store.save_settings(settings)


def test_the_setting_is_off_by_default(store: Store) -> None:
    seed_ledger(store)
    settings = store.get_settings()
    assert settings.desktop_notifications == "off" and settings.desktop_notify_time == "08:00"
    assert morning_notification(store, MON, time(9, 0), sender=Sender()) is None
    assert store.get_meta(LAST_SHOWN_KEY) is None


def test_once_a_day_at_or_after_the_chosen_time(store: Store) -> None:
    seed_ledger(store)
    switch_on(store, at="07:30")
    sender = Sender()
    assert morning_notification(store, MON, time(7, 29), sender=sender) is None
    outcome = morning_notification(store, MON, time(7, 30), sender=sender)
    assert outcome is not None and outcome.result is not None and outcome.result.sent
    assert outcome.notification == Notification("Ordnung", "1 overdue · 3 due this week")
    assert outcome.count == "1 overdue · 3 due this week"
    assert store.get_meta(LAST_SHOWN_KEY) == MON.isoformat()
    assert morning_notification(store, MON, time(12, 0), sender=sender) is None  # already today
    tomorrow = MON + timedelta(days=1)
    assert morning_notification(store, tomorrow, time(6, 0), sender=sender) is None  # before the time
    assert morning_notification(store, tomorrow, time(23, 59), sender=sender) is not None  # started late
    assert len(sender.notes) == 2
    logged = [a for a in store.list_activity(limit=20) if a.kind == "notify.desktop"]
    assert logged and "1 due today · 1 overdue · 2 more this week" in logged[0].message  # Tuesday's
    assert "1 overdue · 3 due this week" in logged[1].message
    assert "library" not in logged[0].message.lower()
    # the tool took it; whether the system showed it is the system's call (macOS permissions, Focus)
    assert logged[0].message.startswith("Sent the morning notification to the system")


def test_full_mode_sends_the_details(store: Store) -> None:
    seed_ledger(store)
    switch_on(store, mode="full")
    sender = Sender()
    morning_notification(store, MON, time(8, 0), sender=sender)
    assert sender.notes[0].body.startswith("Return library books — overdue")


def test_a_failed_attempt_is_tried_again_up_to_three_times(store: Store) -> None:
    seed_ledger(store)
    switch_on(store)
    sender = Sender(sent=False)  # e.g. notify-send ran before the desktop's notification service
    for minute in (0, 15, 30):
        outcome = morning_notification(store, MON, time(9, minute), sender=sender)
        assert outcome is not None and outcome.result is not None and not outcome.result.sent
    assert morning_notification(store, MON, time(9, 45), sender=sender) is None  # given up for today
    assert len(sender.notes) == desktop.MAX_TRIES == 3
    assert store.get_meta(LAST_SHOWN_KEY) == MON.isoformat()
    failure = desktop.last_failure(store)
    assert failure is not None and failure.day == MON.isoformat() and failure.tries == 3
    assert failure.detail == "no tool"
    assert not [a for a in store.list_activity(limit=20) if a.kind == "notify.desktop"]
    # the next day starts afresh, and a shown notification clears the failure
    shown = morning_notification(store, MON + timedelta(days=1), time(9, 0), sender=Sender())
    assert shown is not None and shown.result is not None and shown.result.sent
    assert desktop.last_failure(store) is None


def test_a_retry_that_works_shows_it_once(store: Store) -> None:
    seed_ledger(store)
    switch_on(store)
    morning_notification(store, MON, time(9, 0), sender=Sender(sent=False))
    assert store.get_meta(LAST_SHOWN_KEY) is None and desktop.last_failure(store) is not None
    works = Sender()
    assert morning_notification(store, MON, time(9, 15), sender=works) is not None
    assert morning_notification(store, MON, time(9, 30), sender=works) is None
    assert len(works.notes) == 1 and desktop.last_failure(store) is None


def test_a_missing_tool_uses_the_day_up_at_once(store: Store) -> None:
    seed_ledger(store)
    switch_on(store)

    def missing(_note: Notification) -> SendResult:
        return SendResult(sent=False, mechanism=None, detail=desktop.MISSING_TOOL["linux"])

    assert morning_notification(store, MON, time(9, 0), sender=missing) is not None
    assert store.get_meta(LAST_SHOWN_KEY) == MON.isoformat()  # not tried every 15 minutes


def test_nothing_due_shows_nothing_but_uses_the_day(store: Store) -> None:
    switch_on(store)
    sender = Sender()
    outcome = morning_notification(store, MON, time(9, 0), sender=sender)
    assert outcome is not None and outcome.notification is None and outcome.result is None
    assert sender.notes == [] and store.get_meta(LAST_SHOWN_KEY) == MON.isoformat()


def test_the_demo_never_notifies_on_its_own(store: Store) -> None:
    seed_ledger(store)
    switch_on(store, demo=True)
    assert morning_notification(store, MON, time(9, 0), sender=Sender()) is None


def test_notify_time_parsing(store: Store) -> None:
    settings = store.get_settings()
    for raw, expected in [
        ("06:05", time(6, 5)),
        ("23:59", time(23, 59)),
        ("24:00", time(8, 0)),
        ("7:30", time(8, 0)),
        ("", time(8, 0)),
    ]:
        assert notify_time(settings.model_copy(update={"desktop_notify_time": raw})) == expected
    on = settings.model_copy(update={"desktop_notifications": "full"})
    assert is_due(on, MON, time(8, 0), None)
    assert not is_due(on, MON, time(8, 0), MON.isoformat())
    assert is_due(on, MON, time(8, 0), (MON - timedelta(days=1)).isoformat())


def test_local_now_uses_the_profile_time_zone(store: Store) -> None:
    store.save_profile(store.get_profile().model_copy(update={"timezone": "Asia/Tokyo"}))
    assert desktop.local_now(store).utcoffset() == ZoneInfo("Asia/Tokyo").utcoffset(datetime(2026, 9, 28))
    store.save_profile(store.get_profile().model_copy(update={"timezone": "Not/AZone"}))
    assert desktop.local_now(store).tzinfo is not None


# --------------------------------------------------------------------------------------------------
# the daily tick
# --------------------------------------------------------------------------------------------------


@dataclass
class Bus:
    events: list[str] = field(default_factory=list)

    def publish(self, type: str, **_data: Any) -> None:
        self.events.append(type)


@dataclass
class Ctx:
    store: Store
    llm: LLMService | None
    bus: Bus = field(default_factory=Bus)


async def test_the_tick_shows_it_on_every_check_until_it_has(store: Store) -> None:
    seed_ledger(store)
    switch_on(store)
    now = {"value": datetime(2026, 9, 28, 7, 0, tzinfo=ZoneInfo("Europe/Berlin"))}
    sender = Sender()
    tick = DailyTick(Ctx(store=store, llm=None), now=lambda _s: now["value"], notifier=sender)
    first = await tick.check()
    assert first.day_changed and first.desktop is None  # 07:00: not yet
    now["value"] = now["value"].replace(hour=8, minute=10)
    second = await tick.check()
    assert not second.day_changed
    assert second.desktop is not None and second.desktop.result is not None and second.desktop.result.sent
    assert (await tick.check()).desktop is None
    assert sender.notes == [Notification("Ordnung", "1 overdue · 3 due this week")]


@pytest.mark.parametrize(
    ("at", "now", "sleep"),
    [
        ("23:50", (23, 48), 121.0),  # would be skipped: 23:48 is too early, the next check is tomorrow
        ("08:00", (7, 50), 601.0),
        ("08:00", (6, 0), 900.0),  # the usual interval
        ("08:00", (7, 59, 50), 30.0),  # never less than half a minute
    ],
)
def test_the_tick_wakes_up_for_the_notification(
    store: Store, at: str, now: tuple[int, ...], sleep: float
) -> None:
    seed_ledger(store)
    switch_on(store, at=at)
    moment = datetime(2026, 9, 28, *now, tzinfo=ZoneInfo("Europe/Berlin"))
    tick = DailyTick(Ctx(store=store, llm=None), now=lambda _s: moment)
    assert tick.next_check_in() == pytest.approx(sleep)


async def test_a_late_time_is_shown_on_the_day(store: Store) -> None:
    seed_ledger(store)
    switch_on(store, at="23:50")
    clock_now = {"value": datetime(2026, 9, 28, 23, 48, tzinfo=ZoneInfo("Europe/Berlin"))}
    sender = Sender()
    tick = DailyTick(Ctx(store=store, llm=None), now=lambda _s: clock_now["value"], notifier=sender)
    assert (await tick.check()).desktop is None
    clock_now["value"] += timedelta(seconds=tick.next_check_in())  # 23:50:01, not 00:03
    assert clock_now["value"].date() == MON
    assert (await tick.check()).desktop is not None and len(sender.notes) == 1


def test_nothing_to_wait_for_means_the_usual_interval(store: Store) -> None:
    seed_ledger(store)
    moment = datetime(2026, 9, 28, 7, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    tick = DailyTick(Ctx(store=store, llm=None), now=lambda _s: moment)
    assert tick.next_check_in() == tick.interval_s  # switched off
    switch_on(store)
    store.set_meta(LAST_SHOWN_KEY, MON.isoformat())
    assert tick.next_check_in() == tick.interval_s  # done for today
    store.set_meta(LAST_SHOWN_KEY, None)
    morning_notification(store, MON, time(8, 0), sender=Sender(sent=False))
    assert tick.next_check_in() == tick.interval_s  # a retry comes with the regular checks


async def test_right_after_start_up_the_notification_waits_a_minute(store: Store) -> None:
    seed_ledger(store)
    switch_on(store)
    sender = Sender()
    moment = datetime(2026, 9, 28, 9, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    tick = DailyTick(Ctx(store=store, llm=None), now=lambda _s: moment, notifier=sender)
    tick._hold_until = monotonic() + desktop.STARTUP_GRACE_S  # as run_forever does
    first = await tick.check()
    assert first.day_changed and first.desktop is None and sender.notes == []  # logged in at 09:00
    assert tick.next_check_in() == pytest.approx(desktop.STARTUP_GRACE_S + 1, abs=1)
    tick._hold_until = 0.0  # a minute later
    assert (await tick.check()).desktop is not None and len(sender.notes) == 1


async def test_a_broken_notifier_never_breaks_the_tick(store: Store) -> None:
    seed_ledger(store)
    switch_on(store)

    def broken(_note: Notification) -> SendResult:
        raise RuntimeError("boom")

    tick = DailyTick(
        Ctx(store=store, llm=None),
        now=lambda _s: datetime(2026, 9, 28, 9, 0, tzinfo=ZoneInfo("Europe/Berlin")),
        notifier=broken,
    )
    result = await tick.check()
    assert result.day_changed and result.desktop is None
