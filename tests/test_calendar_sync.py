"""Calendar sync over CalDAV (:mod:`ordnung.calendar.caldav`) against a tiny fake CalDAV server.

What the calendar provider gets (discreet: nothing but dates, times and alarms; full: the calendar
file's events), that sending is idempotent (stable resource names, only what changed, only Ordnung's
own resources removed), how every kind of refusal reads, that the password stays out of the
database, the pause after a refused password, the keyring adapter, the tick hook, and one run over a
real loopback socket.
"""

from __future__ import annotations

import contextlib
import sqlite3
import ssl
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import keyring
import keyring.backend
import keyring.backends.fail
import keyring.backends.null
import keyring.errors
import pytest
from icalendar import Calendar

from fake_caldav import (
    CALENDAR_PATH,
    HOME_PATH,
    PASSWORD,
    PRINCIPAL_PATH,
    USERNAME,
    FakeCalDav,
    MemorySecrets,
    calendar_props,
    multistatus,
    response,
    serve_on_loopback,
)
from helpers_secretary import TODAY, seed_ledger
from ordnung import clock
from ordnung.calendar import caldav, ics
from ordnung.calendar.caldav import CalDavError
from ordnung.calendar.secrets import (
    SERVICE,
    KeyringSecrets,
    SecretsUnavailable,
    account_name,
    install_command,
)
from ordnung.db.store import Store
from ordnung.tick import DailyTick

URL = "https://cal.example.org" + CALENDAR_PATH


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def ids(store: Store) -> dict[str, str]:
    return seed_ledger(store)


@pytest.fixture
def server() -> FakeCalDav:
    return FakeCalDav()


@pytest.fixture
def secrets() -> MemorySecrets:
    return MemorySecrets()


def connect(store: Store, secrets: MemorySecrets, server: FakeCalDav, **kwargs: Any) -> Any:
    options: dict[str, Any] = {"url": URL, "username": USERNAME, "password": PASSWORD, "mode": "discreet"}
    options.update(kwargs)
    return caldav.connect(store, secrets, transport=server.transport(), **options)


def discreet_href(store: Store, stable_uid: str) -> str:
    """The resource name a discreet event of the calendar file's ``stable_uid`` is sent under."""
    return caldav.resource_name(caldav.discreet_uid(stable_uid, caldav.uid_key(store)))


def private_words(store: Store) -> set[str]:
    """Titles, names, amounts and letter words of the seeded ledger (none may reach a discreet calendar)."""
    words = {item.title for item in store.list_items()} | {party.name for party in store.list_parties()}
    words |= {"€", "Musterstadt", "With:", "Amount", "check:"}
    return {word for word in words if word}


# --------------------------------------------------------------------------------------------------
# the address
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://Cloud.Example.org/remote.php/dav/calendars/sam/ordnung",
            "https://cloud.example.org/remote.php/dav/calendars/sam/ordnung/",
        ),
        (
            "  https://caldav.icloud.com/123/calendars/home/  ",
            "https://caldav.icloud.com/123/calendars/home/",
        ),
        ("http://127.0.0.1:5232/sam/ordnung/", "http://127.0.0.1:5232/sam/ordnung/"),
        ("http://localhost:5232/sam/ordnung", "http://localhost:5232/sam/ordnung/"),
        ("http://[::1]:5232/sam/", "http://[::1]:5232/sam/"),
    ],
)
def test_calendar_addresses_are_normalised(raw: str, expected: str) -> None:
    assert caldav.check_url(raw) == expected


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ("", "https://"),
        ("cloud.example.org/dav", "https://"),
        ("ftp://cloud.example.org/dav/", "https://"),
        ("http://cloud.example.org/dav/", "unencrypted"),
        ("http://192.168.1.10/dav/", "unencrypted"),
        ("https://sam:secret@cloud.example.org/dav/", "own fields"),
        ("https://cloud.example.org/dav/#x", "#"),
        ("https://cloud.example.org/da v/", "https://"),
        ("https://cloud.example.org/d\nav/", "https://"),
        ("https://" + "a" * 3000 + ".org/", "https://"),
        ("https://[cloud.example.org/dav/", "can't be read"),
        ("https://cloud.example.org:dav/", "can't be read"),
    ],
)
def test_unusable_addresses_are_refused_with_a_reason(raw: str, why: str) -> None:
    with pytest.raises(CalDavError) as refused:
        caldav.check_url(raw)
    assert refused.value.kind == "address" and why in str(refused.value)


def test_user_names_are_trimmed_and_checked() -> None:
    assert caldav.check_username("  sam@example.org ") == "sam@example.org"
    for bad in ("", "   ", "sam\nroot", "x" * 300):
        with pytest.raises(CalDavError):
            caldav.check_username(bad)


# --------------------------------------------------------------------------------------------------
# the events
# --------------------------------------------------------------------------------------------------


def test_resource_names_come_from_the_stable_uids() -> None:
    assert caldav.resource_name("itm_4gs57j8955hw@ordnung.local") == "ordnung-itm_4gs57j8955hw.ics"
    assert caldav.resource_name("ctr_1-send-by@ordnung.local") == "ordnung-ctr_1-send-by.ics"
    odd = caldav.resource_name("../x y@ordnung.local")
    assert odd.startswith("ordnung-___x_y-") and odd.endswith(".ics") and "/" not in odd
    assert odd == caldav.resource_name("../x y@ordnung.local") != caldav.resource_name("../x_y@ordnung.local")


def test_full_mode_sends_the_calendar_files_events_one_per_resource(
    store: Store, ids: dict[str, str]
) -> None:
    exported = Calendar.from_ical(ics.build_ics(store)).events
    events = caldav.build_events(store, "full")
    assert [event.uid for event in events] == [str(e.get("uid")) for e in exported]
    for event, original in zip(events, exported, strict=True):
        resource = Calendar.from_ical(event.body)
        assert "METHOD" not in resource and len(resource.events) == 1
        sent = resource.events[0]
        for name in ("summary", "description", "dtstart", "location"):
            assert sent.get(name) == original.get(name)
        assert [a.decoded("trigger") for a in sent.walk("VALARM")] == [
            a.decoded("trigger") for a in original.walk("VALARM")
        ]
        assert event.href == caldav.resource_name(event.uid)
    # the timed appointment carries its time zone
    appointment = next(e for e in events if e.uid.startswith(ids["abh_appointment"]))
    assert b"BEGIN:VTIMEZONE" in appointment.body and b"TZID=Europe/Berlin" in appointment.body


def test_discreet_mode_keeps_dates_times_and_alarms_and_nothing_else(
    store: Store, ids: dict[str, str]
) -> None:
    full = {
        event.uid: Calendar.from_ical(event.body).events[0] for event in caldav.build_events(store, "full")
    }
    discreet = caldav.build_events(store, "discreet")
    assert {event.stable_uid for event in discreet} == set(full)
    words = private_words(store)
    for event in discreet:
        text = event.body.decode("utf-8")
        leaked = [word for word in words if word in text]
        assert not leaked, f"{event.uid} leaks {leaked}"
        # the UID and the resource name say nothing of what kind of date it is ("ctr_…-cancel-by")
        stable = event.stable_uid.split("@")[0]
        assert stable not in text and stable not in event.href and stable not in event.uid
        assert event.uid == caldav.discreet_uid(event.stable_uid, caldav.uid_key(store))
        sent = Calendar.from_ical(event.body).events[0]
        original = full[event.stable_uid]
        assert sent.decoded("dtstart") == original.decoded("dtstart")
        assert sent.get("dtend") == original.get("dtend")
        assert [a.decoded("trigger") for a in sent.walk("VALARM")] == [
            a.decoded("trigger") for a in original.walk("VALARM")
        ]
        assert all(str(a.get("description")) == str(sent.get("summary")) for a in sent.walk("VALARM"))
        assert "location" not in sent and "categories" not in sent
        assert str(sent.get("description")).startswith(caldav.DISCREET_DESCRIPTION)
    titles = {event.stable_uid.split("@")[0]: event.preview.summary for event in discreet}
    assert titles[ids["abh_appointment"]] == "Ordnung: appointment"
    assert titles[ids["semester_fee"]] == "Ordnung: payment"
    assert titles[ids["tax_refund"]] == "Ordnung: money in"  # money coming in is not a payment to make
    plain = {"Ordnung: deadline", "Ordnung: payment", "Ordnung: appointment", "Ordnung: money in"}
    assert set(titles.values()) <= plain | {title + caldav.DISCREET_CHECK_TITLE for title in plain}


def test_a_date_ordnung_couldnt_confirm_says_so_in_discreet_mode_too(
    store: Store, ids: dict[str, str]
) -> None:
    # the parking fine's date was read from the letter and not confirmed: "⚠ check:" in full mode
    full = {e.uid.split("@")[0]: e.preview for e in caldav.build_events(store, "full")}
    assert full[ids["parking_payment"]].summary.startswith(ics.CHECK_PREFIX)
    discreet = {e.stable_uid.split("@")[0]: e for e in caldav.build_events(store, "discreet")}
    parking = discreet[ids["parking_payment"]]
    assert parking.preview.summary == "Ordnung: payment — check the date"
    assert parking.preview.description == f"{caldav.DISCREET_DESCRIPTION} {caldav.DISCREET_CHECK}"
    sent = Calendar.from_ical(parking.body).events[0]
    assert all("check the date" in str(alarm.get("description")) for alarm in sent.walk("VALARM"))
    assert "Pay parking fine" not in parking.body.decode("utf-8")
    # a confirmed date doesn't
    assert discreet[ids["semester_fee"]].preview.summary == "Ordnung: payment"


def test_the_preview_says_what_each_event_holds_and_when_its_alarms_ring(
    store: Store, ids: dict[str, str]
) -> None:
    previews = {p.uid.split("@")[0]: p for p in caldav.preview(store, "full")}
    appointment = previews[ids["abh_appointment"]]
    assert appointment.summary.endswith("Appointment at the Ausländerbehörde")
    assert appointment.start == "2026-10-14T10:00:00+02:00" and not appointment.all_day
    parking = previews[ids["parking_payment"]]
    assert parking.all_day and parking.start == "2026-09-29"
    assert parking.alarms == ["7 days before at 09:00", "2 days before at 09:00"]
    # due tomorrow: both alarms fell before today (22 and 27 Sep) — the event has them, they won't ring
    assert parking.alarms_passed == 2
    assert appointment.alarms and appointment.alarms_passed == 0
    assert "Amount: €25" in parking.description
    assert caldav.preview(store, "discreet")[0].description == caldav.DISCREET_DESCRIPTION


@pytest.mark.parametrize(
    ("start", "trigger", "label"),
    [
        (date(2026, 10, 5), timedelta(hours=9), "on the day at 09:00"),
        (date(2026, 10, 5), timedelta(days=-1, hours=9), "the day before at 09:00"),
        (date(2026, 10, 5), timedelta(days=-3, hours=9), "3 days before at 09:00"),
    ],
)
def test_alarm_labels(start: date, trigger: timedelta, label: str) -> None:
    assert caldav._alarm_label(start, trigger) == label


# --------------------------------------------------------------------------------------------------
# connecting and syncing
# --------------------------------------------------------------------------------------------------


def test_connecting_checks_the_calendar_saves_the_password_in_the_keyring_and_sends_everything(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets, data_dir: Path
) -> None:
    report = connect(store, secrets, server)
    events = caldav.build_events(store, "discreet")
    assert report.sent == len(events) > 5 and not report.error and report.failed == 0
    assert server.methods()[0] == "PROPFIND" and server.methods().count("PUT") == len(events)
    assert set(server.events()) == {event.href for event in events}
    assert server.uids() == {event.uid for event in events}
    state = caldav.load_state(store)
    assert state is not None and state.calendar_name == "Ordnung" and state.mode == "discreet"
    # the password belongs to this data folder's connection
    assert len(state.connection) == 16 and state.password_saved
    assert secrets.saved == {account_name(USERNAME, URL, state.connection): PASSWORD}
    assert state.events == {event.href: event.digest for event in events}
    kinds = [entry.kind for entry in store.list_activity(20)]
    assert "calendar.connected" in kinds and "calendar.synced" in kinds
    # the password is nowhere in the database (the WAL folded in)
    store.close()
    with contextlib.closing(sqlite3.connect(data_dir / "ordnung.db")) as conn, conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert all(PASSWORD.encode() not in path.read_bytes() for path in data_dir.rglob("*") if path.is_file())


def test_syncing_again_sends_only_what_changed_and_removes_what_left(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    connect(store, secrets, server)
    server.requests.clear()
    again = caldav.sync(store, secrets, transport=server.transport(), automatic=True)
    assert again is not None and (again.sent, again.removed) == (0, 0) and again.unchanged > 5
    assert server.requests == []  # nothing changed (and checked today): no request at all

    store.update_item(ids["parking_payment"], title="Pay the parking fine (Parkverstoß)")
    store.update_item(ids["followup"], status="done")
    count = len(server.resources)
    report = caldav.sync(store, secrets, transport=server.transport(), automatic=True)
    # the renamed to-do is sent again (its last-modified stamp changed) without the new title; the
    # finished one leaves the calendar
    assert report is not None and (report.sent, report.removed) == (1, 1)
    assert sorted(server.methods()) == ["DELETE", "PUT"] and len(server.resources) == count - 1
    assert caldav.discreet_uid(f"{ids['followup']}@ordnung.local", caldav.uid_key(store)) not in server.uids()
    assert all("Parkverstoß".encode() not in body for body in server.resources.values())

    # switching the mode sends every event under its calendar file name and removes the discreet ones
    discreet_count = len(server.resources)
    full = connect(store, secrets, server, password=None, mode="full")
    assert full.sent == len(server.resources) and full.removed == discreet_count
    parking = next(cal for name, cal in server.events().items() if ids["parking_payment"] in name)
    assert "Parkverstoß" in str(parking.events[0].get("summary"))


def test_a_lost_record_resends_to_the_same_names_without_duplicates(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    connect(store, secrets, server)
    before = dict(server.resources)
    state = caldav.load_state(store)
    assert state is not None
    state.events.clear()
    caldav.save_state(store, state)
    report = caldav.sync(store, secrets, transport=server.transport())
    assert report is not None and report.sent == len(before)
    assert server.resources == before


def test_only_ordnungs_own_events_are_ever_touched(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    mine = CALENDAR_PATH + "dentist.ics"
    server.resources[mine] = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//x//x//EN\r\nBEGIN:VEVENT\r\nUID:dentist@example.org\r\n"
        b"DTSTAMP:20260101T000000Z\r\nDTSTART;VALUE=DATE:20261001\r\nSUMMARY:Dentist\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    connect(store, secrets, server)
    store.update_item(ids["followup"], status="done")
    caldav.sync(store, secrets, transport=server.transport())
    assert caldav.disconnect(store, secrets, remove_events=True, transport=server.transport()) > 0
    assert list(server.resources) == [mine]
    assert all(
        path.startswith(CALENDAR_PATH + "ordnung-")
        for method, path in server.requests
        if method in ("PUT", "DELETE")
    )


def test_one_refused_event_doesnt_stop_the_others_and_is_tried_again(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    refused = CALENDAR_PATH + discreet_href(store, f"{ids['parking_payment']}@ordnung.local")
    server.refuse[refused] = 409
    report = connect(store, secrets, server)
    total = len(caldav.build_events(store, "discreet"))
    assert report.failed == 1 and report.sent == total - 1 and report.error_kind == "conflict"
    assert "calendar of its own" in (report.error or "")
    del server.refuse[refused]
    server.requests.clear()
    again = caldav.sync(store, secrets, transport=server.transport(), automatic=True)
    assert again is not None and again.sent == 1 and again.error is None
    assert server.requests == [("PUT", refused)]


def test_a_refused_update_of_an_event_sent_before_is_still_ordnungs_to_remove(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    connect(store, secrets, server)
    href = discreet_href(store, f"{ids['parking_payment']}@ordnung.local")
    server.refuse[CALENDAR_PATH + href] = 412
    store.update_item(ids["parking_payment"], title="Pay the parking fine now")
    refused = caldav.sync(store, secrets, transport=server.transport())
    assert refused is not None and refused.failed == 1 and refused.error_kind == "conflict"
    state = caldav.load_state(store)
    assert state is not None and href in state.events  # still Ordnung's own
    del server.refuse[CALENDAR_PATH + href]
    store.update_item(ids["parking_payment"], status="done")
    gone = caldav.sync(store, secrets, transport=server.transport())
    assert gone is not None and gone.removed == 1 and CALENDAR_PATH + href not in server.resources


@pytest.mark.parametrize(
    "clash",
    [
        (409, b"no-uid-conflict"),
        # Nextcloud: a 400 that names the UID (and a server that says it with a 403)
        (400, b"Calendar object with uid already exists in this calendar collection."),
        (
            403,
            b'<d:error xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><c:no-uid-conflict/></d:error>',
        ),
    ],
)
def test_an_event_imported_by_hand_under_another_name_is_a_uid_conflict(
    store: Store, ids: dict[str, str], secrets: MemorySecrets, clash: tuple[int, bytes]
) -> None:
    server = FakeCalDav(uid_clash=clash)
    event = caldav.build_events(store, "full")[0]
    server.resources[CALENDAR_PATH + "imported.ics"] = event.body
    report = connect(store, secrets, server, mode="full")
    assert report.failed == 1 and report.error_kind == "conflict"
    assert "calendar of its own" in (report.error or "")
    assert report.sent == len(caldav.build_events(store, "full")) - 1  # the others still went


def test_a_refused_request_without_a_uid_is_not_a_conflict(
    store: Store, ids: dict[str, str], secrets: MemorySecrets
) -> None:
    server = FakeCalDav()
    refused = CALENDAR_PATH + discreet_href(store, f"{ids['parking_payment']}@ordnung.local")
    server.refuse[refused] = 400
    report = connect(store, secrets, server)
    assert report.failed == 1 and report.error_kind == "server" and "HTTP 400" in (report.error or "")


@pytest.mark.parametrize(
    ("change", "kind", "words"),
    [
        ({"password": "wrong"}, "auth", "refused the user name or app password"),
        ({"calendar": False}, "not_calendar", "not one calendar"),
        ({"components": ("VTODO",)}, "not_calendar", "only takes tasks"),
        ({"path": "/dav/calendars/sam/other/"}, "not_found", "no calendar at this address"),
    ],
)
def test_connecting_to_something_unusable_stores_nothing(
    store: Store, ids: dict[str, str], secrets: MemorySecrets, change: dict[str, Any], kind: str, words: str
) -> None:
    server = FakeCalDav(**change)
    with pytest.raises(CalDavError) as refused:
        connect(store, secrets, server)
    assert refused.value.kind == kind and words in str(refused.value)
    assert PASSWORD not in str(refused.value)
    assert caldav.load_state(store) is None and secrets.saved == {}
    assert "PUT" not in server.methods()


@pytest.mark.parametrize(
    ("answer", "kind", "words"),
    [
        (
            (301, {"Location": "https://cal.example.org/new/"}, b""),
            "address",
            "moved to https://cal.example.org/new/",
        ),
        ((302, {"Location": "http://evil.example/"}, b""), "address", "another address"),
        ((403, {}, b""), "forbidden", "read-only"),
        ((500, {}, b""), "server", "HTTP 500"),
        ((200, {}, b"<html>hi</html>"), "not_calendar", "doesn't speak CalDAV"),
        (
            (207, {}, b'<!DOCTYPE x [<!ENTITY a "aaaa">]><d:multistatus xmlns:d="DAV:">&a;</d:multistatus>'),
            "server",
            "couldn't be read",
        ),
        # the same in UTF-16: a byte search misses "<!DOCTYPE", the parser does not
        (
            (
                207,
                {},
                '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
                '<d:multistatus xmlns:d="DAV:">&a;</d:multistatus>'.encode("utf-16"),
            ),
            "server",
            "couldn't be read",
        ),
        ((207, {}, b"<d:multistatus xmlns:d='DAV:'><d:response>"), "server", "couldn't be read"),
        ((207, {}, b"x" * (caldav.MAX_RESPONSE_BYTES + 10)), "server", "too large"),
        ((207, {}, b"<d:multistatus xmlns:d='DAV:'/>"), "not_calendar", "not a calendar"),
        # an address in the answer that can't be read names nothing (never an unhandled error)
        (
            (207, {}, multistatus(response("http://[oops/", calendar_props()))),
            "not_calendar",
            "not a calendar",
        ),
        ((301, {"Location": "http://[oops/"}, b""), "address", "another address"),
    ],
)
def test_odd_answers_read_as_reasons(
    store: Store, secrets: MemorySecrets, answer: tuple[int, dict[str, str], bytes], kind: str, words: str
) -> None:
    server = FakeCalDav(override=answer)
    with pytest.raises(CalDavError) as refused:
        connect(store, secrets, server)
    assert refused.value.kind == kind and words in str(refused.value)
    assert caldav.load_state(store) is None


@pytest.mark.parametrize(
    ("error", "kind", "words"),
    [
        (httpx.ConnectError("refused"), "network", "Couldn't reach cal.example.org"),
        (httpx.ReadTimeout("slow"), "network", "didn't answer in time"),
    ],
)
def test_the_network_failing_reads_as_a_reason(
    store: Store, secrets: MemorySecrets, error: Exception, kind: str, words: str
) -> None:
    with pytest.raises(CalDavError) as refused:
        connect(store, secrets, FakeCalDav(raises=error))
    assert refused.value.kind == kind and words in str(refused.value)


def test_an_unverifiable_certificate_sends_nothing(store: Store, secrets: MemorySecrets) -> None:
    error = httpx.ConnectError("tls")
    error.__cause__ = ssl.SSLCertVerificationError("self-signed certificate")
    with pytest.raises(CalDavError) as refused:
        connect(store, secrets, FakeCalDav(raises=error))
    assert refused.value.kind == "tls" and "SSL_CERT_FILE" in str(refused.value)


def test_a_refused_password_pauses_automatic_syncing_until_synced_by_hand(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    connect(store, secrets, server)
    store.update_item(ids["followup"], status="done")
    server.password = "rotated"
    report = caldav.sync(store, secrets, transport=server.transport(), automatic=True)
    assert report is not None and report.error_kind == "auth" and report.failed == 1
    state = caldav.load_state(store)
    assert state is not None and state.paused and state.last == report
    server.requests.clear()
    assert caldav.sync(store, secrets, transport=server.transport(), automatic=True) is None
    assert server.requests == []  # no more failed logins
    # a new password (connecting again) resumes
    resumed = connect(store, secrets, server, password="rotated")
    assert resumed.removed == 1 and resumed.error is None
    state = caldav.load_state(store)
    assert state is not None and not state.paused


def test_a_password_missing_from_this_computer_is_reported(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    connect(store, secrets, server)
    store.update_item(ids["followup"], status="done")
    secrets.saved.clear()  # e.g. a restored backup on a new computer
    report = caldav.sync(store, secrets, transport=server.transport())
    assert (
        report is not None
        and report.error_kind == "auth"
        and "isn't saved on this computer" in (report.error or "")
    )
    with pytest.raises(CalDavError, match="isn't saved"):
        connect(store, secrets, server, password=None)


def test_a_second_calendar_needs_a_disconnect_first(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    connect(store, secrets, server)
    with pytest.raises(CalDavError) as refused:
        connect(store, secrets, server, url="https://other.example.org/cal/")
    assert refused.value.kind == "conflict" and "Disconnect" in str(refused.value)


def test_no_password_store_means_no_calendar_sync(store: Store, server: FakeCalDav) -> None:
    secrets = MemorySecrets(SecretsUnavailable("no store", install=install_command()))
    with pytest.raises(CalDavError) as refused:
        connect(store, secrets, server)
    assert refused.value.kind == "unavailable" and server.requests == []


def test_nothing_is_sent_without_a_connection_or_in_the_demo(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    assert caldav.sync(store, secrets, transport=server.transport()) is None
    connect(store, secrets, server)
    store.update_item(ids["followup"], status="done")
    store.save_settings({"demo": True})
    server.requests.clear()
    assert caldav.sync(store, secrets, transport=server.transport()) is None
    assert server.requests == []


def test_disconnecting_removes_only_ordnungs_events_when_asked_and_forgets_the_password(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    connect(store, secrets, server)
    count = len(server.resources)
    assert caldav.disconnect(store, secrets, remove_events=True, transport=server.transport()) == count
    assert server.resources == {} and secrets.saved == {} and caldav.load_state(store) is None
    assert caldav.disconnect(store, secrets, remove_events=True, transport=server.transport()) == 0

    connect(store, secrets, server)
    assert caldav.disconnect(store, secrets, remove_events=False, transport=server.transport()) == 0
    assert len(server.resources) == count and caldav.load_state(store) is None


class CountingSecrets(MemorySecrets):
    """Counts how often a password is read (a locked keyring asks to be unlocked each time)."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def get(self, account: str) -> str | None:
        self.reads += 1
        return super().get(account)


def test_an_unchanged_ledger_doesnt_read_the_password(
    store: Store, ids: dict[str, str], server: FakeCalDav
) -> None:
    secrets = CountingSecrets()
    connect(store, secrets, server)
    before = secrets.reads
    for _ in range(3):
        report = caldav.sync(store, secrets, transport=server.transport(), automatic=True)
        assert report is not None and report.sent == 0 and report.error is None
    assert secrets.reads == before  # nothing to send: the keyring stays shut
    store.update_item(ids["followup"], status="done")
    report = caldav.sync(store, secrets, transport=server.transport(), automatic=True)
    assert report is not None and report.removed == 1 and secrets.reads == before + 1


@pytest.mark.parametrize(
    ("error", "words"),
    [
        (httpx.ConnectError("refused"), "Couldn't reach cal.example.org."),
        (httpx.ReadTimeout("slow"), "didn't answer in time."),
    ],
)
def test_only_a_sync_says_it_is_tried_again(
    store: Store,
    ids: dict[str, str],
    server: FakeCalDav,
    secrets: MemorySecrets,
    error: Exception,
    words: str,
) -> None:
    # finding, connecting and disconnecting are not retried: their answers don't promise it
    for attempt in (
        lambda: caldav.discover(URL, USERNAME, PASSWORD, transport=FakeCalDav(raises=error).transport()),
        lambda: connect(store, secrets, FakeCalDav(raises=error)),
    ):
        with pytest.raises(CalDavError) as refused:
            attempt()
        assert words in str(refused.value) and caldav.RETRY_NOTE not in str(refused.value)
    connect(store, secrets, server)
    store.update_item(ids["followup"], status="done")
    server.raises = error
    with pytest.raises(CalDavError) as refused:
        caldav.disconnect(store, secrets, remove_events=True, transport=server.transport())
    assert caldav.RETRY_NOTE not in str(refused.value)
    # the tick's next check does send it again
    report = caldav.sync(store, secrets, transport=server.transport(), automatic=True)
    assert report is not None and (report.error or "").endswith(f"{words} {caldav.RETRY_NOTE}")
    server.raises = None
    server.override = (503, {}, b"")
    report = caldav.sync(store, secrets, transport=server.transport(), automatic=True)
    assert (
        report is not None
        and report.error == f"The calendar server had a problem (HTTP 503). {caldav.RETRY_NOTE}"
    )
    server.override = None
    server.password = "rotated"
    report = caldav.sync(store, secrets, transport=server.transport())
    assert (
        report is not None and report.error_kind == "auth" and caldav.RETRY_NOTE not in (report.error or "")
    )


def test_disconnecting_keeps_the_connection_when_the_events_cant_be_removed(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    connect(store, secrets, server)
    server.raises = httpx.ConnectError("down")
    with pytest.raises(CalDavError) as refused:
        caldav.disconnect(store, secrets, remove_events=True, transport=server.transport())
    assert refused.value.kind == "network"
    assert caldav.load_state(store) is not None and secrets.saved


# --------------------------------------------------------------------------------------------------
# finding the calendar
# --------------------------------------------------------------------------------------------------


def found(server: FakeCalDav, url: str) -> list[tuple[str, str | None]]:
    return [(c.url, c.name) for c in caldav.discover(url, USERNAME, PASSWORD, transport=server.transport())]


BASE = "https://cal.example.org"
ORDNUNG = (BASE + CALENDAR_PATH, "Ordnung")
PERSONAL = (BASE + HOME_PATH + "personal/", "Personal")


def test_a_calendars_own_address_finds_just_that_calendar(server: FakeCalDav) -> None:
    assert found(server, URL) == [ORDNUNG]
    assert server.methods() == ["PROPFIND"]


@pytest.mark.parametrize(
    "start",
    [
        BASE + HOME_PATH,  # the calendar home: the calendars in it
        BASE + "/",  # the server: its principal's calendar home
        BASE + PRINCIPAL_PATH,  # the account
        BASE + "/somewhere/else/",  # nothing there: the server's /.well-known/caldav
        "https://CAL.example.org",
    ],
)
def test_an_account_or_server_address_finds_the_calendars_that_take_events(
    server: FakeCalDav, start: str
) -> None:
    assert found(server, start) == [ORDNUNG, PERSONAL]  # not the tasks-only list


def test_a_calendar_home_on_another_https_host_is_followed(server: FakeCalDav) -> None:
    server.home_href = "https://p42-caldav.example.org:443" + HOME_PATH
    calendars = found(server, BASE + "/")
    assert calendars[0] == ("https://p42-caldav.example.org:443" + CALENDAR_PATH, "Ordnung")


def test_a_calendar_home_over_plain_http_is_not_followed(server: FakeCalDav) -> None:
    server.home_href = "http://p42-caldav.example.org" + HOME_PATH
    with pytest.raises(CalDavError, match="No calendar for events was found"):
        found(server, BASE + "/")


def test_finding_calendars_stops_at_a_refused_password(server: FakeCalDav) -> None:
    server.password = "rotated"
    with pytest.raises(CalDavError) as refused:
        found(server, BASE + "/")
    assert refused.value.kind == "auth" and server.methods() == ["PROPFIND"]


def test_an_account_without_event_calendars_says_what_to_do(server: FakeCalDav) -> None:
    server.calendar, server.others = False, {HOME_PATH + "tasks/": ("Tasks", ("VTODO",))}
    with pytest.raises(CalDavError) as refused:
        found(server, BASE + HOME_PATH)
    assert refused.value.kind == "not_calendar" and "named “Ordnung”" in str(refused.value)


@pytest.mark.parametrize("start", [BASE, BASE + "/", "https://cal.example.org/index.php/"])
def test_a_web_root_that_redirects_to_its_login_page_still_finds_the_calendars(
    server: FakeCalDav, start: str
) -> None:
    # Nextcloud answers a PROPFIND on its web root (and index.php) with a redirect to the login page
    login = (302, {"Location": "/login"}, b"")
    server.answers = {
        "/": login,
        "/index.php/": login,
        "/login": (200, {"Content-Type": "text/html"}, b"<html>Log in</html>"),
    }
    assert found(server, start) == [ORDNUNG, PERSONAL]  # via /.well-known/caldav
    assert ("PROPFIND", "/.well-known/caldav") in server.requests


def test_a_moved_calendar_on_the_same_host_is_found_where_it_is(server: FakeCalDav) -> None:
    server.answers = {"/dav/calendars/sam/old/": (301, {"Location": CALENDAR_PATH}, b"")}
    assert ORDNUNG in found(server, BASE + "/dav/calendars/sam/old/")


def test_a_well_known_redirect_to_another_host_is_named_not_followed(server: FakeCalDav) -> None:
    server.override = (301, {"Location": "https://caldav.elsewhere.example/dav/"}, b"")
    with pytest.raises(CalDavError) as refused:
        found(server, BASE + "/")
    assert refused.value.kind == "address" and "https://caldav.elsewhere.example/dav/" in str(refused.value)


@pytest.mark.parametrize("href", ["http://[oops/", "https://cal.example.org:x/dav/"])
def test_unreadable_addresses_in_the_servers_answers_are_skipped_while_finding(
    server: FakeCalDav, href: str
) -> None:
    """A server's answer is untrusted input: an address in it that can't be read is not followed."""
    broken = multistatus(
        response(href, calendar_props()),
        response(
            PRINCIPAL_PATH, f"<d:current-user-principal><d:href>{href}</d:href></d:current-user-principal>"
        ),
    )
    server.answers["/"] = (207, {"Content-Type": "application/xml"}, broken)
    # skipped, the search goes on at the server's /.well-known/caldav
    assert found(server, BASE + "/") == [ORDNUNG, PERSONAL]
    assert [r.url for r in caldav.read_resources(broken, BASE + "/")] == [BASE + PRINCIPAL_PATH]
    assert caldav.read_resources(broken, BASE + "/")[0].principal is None


def test_finding_needs_a_password_and_a_usable_address(server: FakeCalDav) -> None:
    for url, password in ((URL, ""), ("http://cal.example.org/", PASSWORD)):
        with pytest.raises(CalDavError):
            caldav.discover(url, USERNAME, password, transport=server.transport())
    assert server.requests == []


def test_a_real_socket_round_trip(store: Store, ids: dict[str, str], secrets: MemorySecrets) -> None:
    server = FakeCalDav()
    with serve_on_loopback(server) as url:
        report = caldav.connect(store, secrets, url=url, username=USERNAME, password=PASSWORD, mode="full")
        assert report.sent == len(server.resources) > 5 and report.error is None
        caldav.disconnect(store, secrets, remove_events=True)
    assert server.resources == {}


def test_an_unreadable_record_counts_as_not_connected(store: Store) -> None:
    store.set_meta(caldav.STATE_KEY, "{not json")
    assert caldav.load_state(store) is None


# --------------------------------------------------------------------------------------------------
# events that went missing, and copies of the data
# --------------------------------------------------------------------------------------------------


def test_sync_now_sends_back_events_that_went_missing_from_the_calendar(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    connect(store, secrets, server)
    total = len(server.resources)
    for path in sorted(server.resources)[:3]:  # deleted in the calendar app, or by another Ordnung
        del server.resources[path]
    server.requests.clear()
    quiet = caldav.sync(store, secrets, transport=server.transport(), automatic=True)
    assert quiet is not None and quiet.sent == 0 and server.requests == []  # checked today already
    report = caldav.sync(store, secrets, transport=server.transport())  # "Sync now" checks
    assert report is not None and (report.sent, report.missing, report.error) == (3, 3, None)
    assert server.methods() == ["REPORT", "PUT", "PUT", "PUT"] and len(server.resources) == total
    assert "3 were missing from the calendar" in store.list_activity(5)[0].message
    # the check asks only about Ordnung's own resources
    server.requests.clear()
    assert caldav.sync(store, secrets, transport=server.transport()).missing == 0  # type: ignore[union-attr]
    assert server.methods() == ["REPORT"]


def test_the_automatic_check_runs_once_a_day(store: Store, ids: dict[str, str], server: FakeCalDav) -> None:
    secrets = CountingSecrets()
    connect(store, secrets, server)
    total, reads = len(server.resources), secrets.reads
    server.resources.clear()
    clock.set_today(TODAY + timedelta(days=1))
    server.requests.clear()
    report = caldav.sync(store, secrets, transport=server.transport(), automatic=True)
    assert report is not None and report.missing == total and len(server.resources) == total
    assert server.methods()[0] == "REPORT" and secrets.reads == reads + 1
    state = caldav.load_state(store)
    assert state is not None and state.checked_on == (TODAY + timedelta(days=1)).isoformat()
    server.requests.clear()
    for _ in range(3):  # the rest of the day: nothing changed, nothing asked, the keyring stays shut
        assert caldav.sync(store, secrets, transport=server.transport(), automatic=True) is not None
    assert server.requests == [] and secrets.reads == reads + 1


def test_a_server_that_cant_say_which_are_there_is_simply_not_asked(
    store: Store, ids: dict[str, str], secrets: MemorySecrets
) -> None:
    server = FakeCalDav(multiget=False)
    connect(store, secrets, server)
    store.update_item(ids["followup"], status="done")
    report = caldav.sync(store, secrets, transport=server.transport())
    assert report is not None and report.error is None and report.removed == 1 and report.missing == 0
    assert caldav.present_names(b"<d:multistatus xmlns:d='DAV:'/>", URL) == set()


def test_a_refused_password_during_the_check_pauses_like_any_other(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    connect(store, secrets, server)
    server.password = "rotated"
    report = caldav.sync(store, secrets, transport=server.transport())
    assert report is not None and report.error_kind == "auth"
    state = caldav.load_state(store)
    assert state is not None and state.paused and len(state.events) == len(server.resources)


def test_entering_the_password_again_sends_every_event(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets
) -> None:
    connect(store, secrets, server)
    total = len(server.resources)
    server.resources.clear()
    report = connect(store, secrets, server)  # the person types the app password again
    assert report.sent == total and len(server.resources) == total
    kept = connect(store, secrets, server, password=None)  # the mode saved again: nothing new to send
    assert kept.sent == 0


def test_a_restored_copy_on_this_computer_leaves_the_originals_calendar_and_password_alone(
    store: Store, ids: dict[str, str], server: FakeCalDav, secrets: MemorySecrets, tmp_path: Path
) -> None:
    """``ordnung restore --data-dir`` next to the running Ordnung: one keyring, one calendar."""
    from ordnung import backup as backups
    from ordnung.backup.container import KdfParams
    from ordnung.config import Paths

    connect(store, secrets, server)
    total, live_account = len(server.resources), next(iter(secrets.saved))
    out = tmp_path / "b.ordnung-backup"
    backups.write_backup_file(store.db_path.parent, out, "a long enough passphrase", kdf=KdfParams(log2_n=10))
    copy_dir = backups.restore_backup(out, "a long enough passphrase", tmp_path / "copy").target
    copy = Store.open(Paths(copy_dir))
    try:
        state = caldav.load_state(copy)
        original = caldav.load_state(store)
        assert state is not None and original is not None
        assert (state.url, state.username, state.mode, state.calendar_name) == (
            URL,
            USERNAME,
            "discreet",
            "Ordnung",
        )
        assert state.connection != original.connection and state.events == {}
        assert state.paused and not state.password_saved and state.last is None
        # trying the copy out changes nothing in the calendar
        copy.update_item(
            next(i.id for i in copy.list_items() if i.due_date and i.status == "open"), status="done"
        )
        server.requests.clear()
        assert caldav.sync(copy, secrets, transport=server.transport(), automatic=True) is None
        by_hand = caldav.sync(copy, secrets, transport=server.transport())
        assert by_hand is not None and "isn't saved on this computer" in (by_hand.error or "")
        assert server.requests == []  # its password isn't the original's: nothing reached the server
        # its disconnect ("Delete everything" does the same) removes none of the original's events
        assert caldav.disconnect(copy, secrets, remove_events=True, transport=server.transport()) == 0
        assert len(server.resources) == total and live_account in secrets.saved
    finally:
        copy.close()
    # the original syncs on as before
    store.update_item(ids["followup"], status="done")
    report = caldav.sync(store, secrets, transport=server.transport())
    assert report is not None and report.error is None and report.removed == 1


def test_moving_to_a_new_computer_then_wiping_the_old_one_keeps_the_calendar_filled(
    store: Store, ids: dict[str, str], server: FakeCalDav, tmp_path: Path
) -> None:
    """The old Ordnung removes its events when it is wiped; the new one notices and sends them back."""
    from ordnung import backup as backups
    from ordnung.backup.container import KdfParams
    from ordnung.config import Paths

    old_keyring, new_keyring = MemorySecrets(), MemorySecrets()
    connect(store, old_keyring, server)
    total = len(server.resources)
    out = tmp_path / "move.ordnung-backup"
    backups.write_backup_file(store.db_path.parent, out, "a long enough passphrase", kdf=KdfParams(log2_n=10))
    new_dir = backups.restore_backup(out, "a long enough passphrase", tmp_path / "new").target
    new = Store.open(Paths(new_dir))
    try:
        again = connect(new, new_keyring, server)  # Settings asks for the app password: all sent again
        assert again.sent == total and again.error is None
        # the old computer is handed on: "Delete everything" takes Ordnung's events out first
        assert (
            caldav.disconnect(store, old_keyring, remove_events=True, transport=server.transport()) == total
        )
        assert server.resources == {}
        # the new one's first check of the next day (or "Sync now") puts them back
        clock.set_today(TODAY + timedelta(days=1))
        report = caldav.sync(new, new_keyring, transport=server.transport(), automatic=True)
        assert report is not None and report.missing == total and len(server.resources) == total
        state = caldav.load_state(new)
        assert state is not None and set(state.events) == {p.rsplit("/", 1)[1] for p in server.resources}
    finally:
        new.close()


# --------------------------------------------------------------------------------------------------
# the tick and the keyring
# --------------------------------------------------------------------------------------------------


async def test_the_server_tick_syncs_and_survives_a_failing_sync(store: Store) -> None:
    class Ctx:
        def __init__(self) -> None:
            self.store, self.llm, self.bus = store, None, None

    calls: list[Store] = []

    def fake_sync(s: Store) -> Any:
        calls.append(s)
        return None

    result = await DailyTick(Ctx(), calendar_sync=fake_sync).check()  # type: ignore[arg-type]
    assert calls == [store] and result.calendar is None
    assert (await DailyTick(Ctx()).check()).calendar is None  # type: ignore[arg-type]

    def broken(_s: Store) -> Any:
        raise RuntimeError("boom")

    assert (await DailyTick(Ctx(), calendar_sync=broken).check()).calendar is None  # type: ignore[arg-type]


def test_scheduled_sync_without_a_calendar_touches_no_keyring(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_keyring(*_args: Any) -> Any:
        raise AssertionError("the keyring was asked")

    monkeypatch.setattr("ordnung.calendar.secrets.KeyringSecrets.__init__", no_keyring)
    assert caldav.scheduled_sync(store) is None


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.data.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.data[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.data:
            raise keyring.errors.PasswordDeleteError("none")
        del self.data[(service, username)]


@pytest.fixture
def memory_keyring() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


def test_the_keyring_adapter_keeps_one_password_per_account(memory_keyring: MemoryKeyring) -> None:
    secrets = KeyringSecrets()
    account = account_name(USERNAME, URL)
    assert secrets.problem() is None and secrets.get(account) is None
    secrets.set(account, PASSWORD)
    assert memory_keyring.data == {(SERVICE, account): PASSWORD} and secrets.get(account) == PASSWORD
    secrets.delete(account)
    secrets.delete(account)  # nothing there: no error
    assert secrets.get(account) is None


class ShutKeyring(MemoryKeyring):
    """A password store that must not be read just to ask whether there is one (it would prompt)."""

    def get_password(self, service: str, username: str) -> str | None:
        raise AssertionError("a secret was read")


def test_asking_whether_there_is_a_password_store_reads_no_secret() -> None:
    previous = keyring.get_keyring()
    keyring.set_keyring(ShutKeyring())
    try:
        assert KeyringSecrets().problem() is None
    finally:
        keyring.set_keyring(previous)


class PlaintextKeyring(MemoryKeyring):
    """Stands in for ``keyrings.alt.file.PlaintextKeyring`` (a plain file in the home folder)."""

    priority = 0.5  # type: ignore[assignment]


PlaintextKeyring.__module__ = "keyrings.alt.file"


class HomeMadeKeyring(MemoryKeyring):
    """A third-party backend that says it is a good one, from ``keyrings.alt``."""

    priority = 3  # type: ignore[assignment]


HomeMadeKeyring.__module__ = "keyrings.alt.file"


@pytest.mark.parametrize(
    "backend",
    [keyring.backends.null.Keyring(), PlaintextKeyring(), HomeMadeKeyring()],
    ids=["null", "plaintext", "keyrings.alt"],
)
def test_a_password_store_that_isnt_one_is_refused(
    store: Store, server: FakeCalDav, backend: keyring.backend.KeyringBackend
) -> None:
    previous = keyring.get_keyring()
    keyring.set_keyring(backend)
    try:
        secrets = KeyringSecrets()
        problem = secrets.problem()
        assert problem is not None and "doesn't keep passwords safely" in str(problem)
        with pytest.raises(CalDavError) as refused:
            caldav.connect(
                store,
                secrets,
                url=URL,
                username=USERNAME,
                password=PASSWORD,
                mode="discreet",
                transport=server.transport(),
            )
        assert refused.value.kind == "unavailable" and server.requests == []
        with pytest.raises(SecretsUnavailable):
            secrets.set("a", "b")
        assert getattr(backend, "data", {}) == {}  # nothing was written to it
    finally:
        keyring.set_keyring(previous)


def test_a_chain_of_password_stores_is_judged_by_the_one_it_stores_into() -> None:
    from keyring.backends.chainer import ChainerBackend

    from ordnung.calendar.secrets import backend_problem

    class Chain(ChainerBackend):
        def __init__(self, backends: list[Any]) -> None:
            super().__init__()
            self._chain = backends

        @property
        def backends(self) -> list[Any]:  # type: ignore[override]
            return self._chain

    Chain.__name__ = "ChainerBackend"
    assert backend_problem(Chain([MemoryKeyring(), PlaintextKeyring()])) is None
    assert backend_problem(Chain([PlaintextKeyring()])) is not None
    assert backend_problem(Chain([])) is not None


def test_a_computer_without_a_password_store_is_told_so() -> None:
    previous = keyring.get_keyring()
    keyring.set_keyring(keyring.backends.fail.Keyring())
    try:
        problem = KeyringSecrets().problem()
        assert problem is not None and "no password store" in str(problem) and problem.install is None
        with pytest.raises(SecretsUnavailable):
            KeyringSecrets().set("a", "b")
    finally:
        keyring.set_keyring(previous)


def test_without_keyring_the_command_for_this_installation_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    real = importlib.import_module

    def missing(name: str, *args: Any) -> Any:
        if name.startswith("keyring"):
            raise ImportError(name)
        return real(name, *args)

    monkeypatch.setattr(importlib, "import_module", missing)
    problem = KeyringSecrets().problem()
    assert problem is not None and problem.install == install_command()


@pytest.mark.parametrize(
    ("prefix", "executable", "command"),
    [
        (
            "/home/sam/.local/share/pipx/venvs/ordnung",
            "/home/sam/.local/share/pipx/venvs/ordnung/bin/python",
            "pipx inject ordnung keyring",
        ),
        (
            "C:\\Users\\Jürgen\\pipx\\venvs\\ordnung",
            "C:\\Users\\Jürgen\\pipx\\venvs\\ordnung\\Scripts\\python.exe",
            "pipx inject ordnung keyring",
        ),
        (
            "/home/sam/.local/share/uv/tools/ordnung",
            "/home/sam/.local/share/uv/tools/ordnung/bin/python",
            "uv tool install --reinstall --with 'keyring>=25' git+https://github.com/ahmedEid1/ordnung",
        ),
        (
            "/home/sam/ordnung/.venv",
            "/home/sam/ordnung/.venv/bin/python",
            "/home/sam/ordnung/.venv/bin/python -m pip install 'keyring>=25'",
        ),
        ("/opt/my env", "/opt/my env/bin/python", "'/opt/my env/bin/python' -m pip install 'keyring>=25'"),
    ],
)
def test_the_install_command_fits_the_installation(prefix: str, executable: str, command: str) -> None:
    # never a package name on PyPI that isn't Ordnung's ("pip install ordnung[…]")
    assert install_command(prefix, executable) == command


def test_keyring_is_one_of_ordnungs_dependencies() -> None:
    import tomllib

    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]
    assert any(dep.startswith("keyring") for dep in project["dependencies"])
    assert "caldav" not in project.get("optional-dependencies", {})


def test_the_triggers_read_the_same_connection_record() -> None:
    from ordnung.secretary.triggers import CALENDAR_SYNC_META_KEY

    assert caldav.STATE_KEY == CALENDAR_SYNC_META_KEY


def test_an_emailed_bill_reaches_the_synced_calendar_once(store: Store) -> None:
    """The e-mail repeating its attached bill's payment is set aside: one event with alarms, not two, and
    none left once the bill is paid (it would remind of a bill already paid)."""
    from helpers_secretary import add_emailed_bill

    bill = add_emailed_bill(store, due="2026-10-15")
    for mode in ("full", "discreet"):
        uids = {event.stable_uid for event in caldav.build_events(store, mode)}
        assert f"{bill['bill_payment']}@ordnung.local" in uids
        assert f"{bill['email_payment']}@ordnung.local" not in uids
    store.update_item(bill["bill_payment"], status="done")
    assert not {event.stable_uid for event in caldav.build_events(store, "full")} & {
        f"{bill['bill_payment']}@ordnung.local",
        f"{bill['email_payment']}@ordnung.local",
    }


def test_a_discreet_events_name_is_the_same_in_a_restored_copy_and_another_folders_differs(
    store: Store, ids: dict[str, str], tmp_path: Path
) -> None:
    """The discreet UIDs are keyed by a secret of the data folder that a backup carries: a copy restored
    elsewhere sends each event under its old name (it replaces it, never a duplicate), while another
    data folder's names for the same dates tell the provider nothing it could link."""
    from ordnung import backup as backups
    from ordnung.backup.container import KdfParams
    from ordnung.config import Paths

    before = {event.stable_uid: event.href for event in caldav.build_events(store, "discreet")}
    out = tmp_path / "copy.ordnung-backup"
    backups.write_backup_file(store.db_path.parent, out, "a long enough passphrase", kdf=KdfParams(log2_n=10))
    restored = Store.open(
        Paths(backups.restore_backup(out, "a long enough passphrase", tmp_path / "r").target)
    )
    try:
        assert {event.stable_uid: event.href for event in caldav.build_events(restored, "discreet")} == before
    finally:
        restored.close()
    stable = f"{ids['parking_payment']}@ordnung.local"
    assert caldav.discreet_uid(stable, "another folder's key") != caldav.discreet_uid(
        stable, caldav.uid_key(store)
    )
