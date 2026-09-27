"""Calendar sync: Ordnung's dates in the person's own calendar over CalDAV (SPEC §12, ADR 0013).

Written policy (ADR 0007):

* **Opt-in, into one calendar the person names.** Nothing is sent until the person connects a
  calendar in Settings → Calendar: its CalDAV address, their user name and an app password
  (Nextcloud, iCloud, mailbox.org, Radicale, …); a calendar of its own, named "Ordnung", is
  recommended. The address must be ``https://`` — ``http://`` only to this computer (a local
  Radicale) — and carries no user name or password. Connecting first asks the server whether the
  address is a calendar that takes events (``PROPFIND``); only then is the app password stored, in
  the OS keyring (:mod:`ordnung.calendar.secrets`), never in the database. Never in the demo.
* **What is sent: the calendar file's events.** Exactly the events of the ``.ics`` export
  (:func:`ordnung.calendar.ics.build_ics`: open dated to-dos and contract decision days with their
  alarms; letters with scam signs are left out), each as its own resource ``ordnung-<id>.ics``.
  *Discreet* (the default) keeps the date, the time and the alarms and replaces everything else: the
  title becomes "Ordnung: deadline" ("… payment", "… appointment", "… money in" for money coming
  in), the description a pointer to Ordnung; no location, no categories — no names, organisations,
  amounts or letter text reach the calendar provider. A date Ordnung couldn't confirm in the letter
  says so in either mode ("Ordnung: deadline — check the date"): the doubt travels with the alarm.
  *With details* sends the events as the calendar file has them. Settings shows every event in the
  chosen mode before anything is sent (:func:`preview`).
* **Idempotent, and only Ordnung's own events.** An event's resource name comes from its stable UID,
  so sending it again replaces it instead of adding a copy. Ordnung remembers a SHA-256 of each event
  it sent (meta ``calendar_sync``, :class:`~ordnung.models.CalendarSyncState`): an unchanged event is
  not sent again, a changed one is replaced, and one that left the export (done, dismissed, deleted)
  is removed. Only resources Ordnung itself put there are ever replaced or removed; nothing else in
  the calendar is read. An event edited in the calendar app is overwritten by the next change made
  in Ordnung — Ordnung's dates are changed in Ordnung.
* **When.** On connecting, on "Sync now", and at every check of the daily tick while ``ordnung
  serve`` runs (every 15 minutes) — sending only what changed, so an unchanged ledger sends nothing
  and doesn't even read the app password from the keyring (a locked keyring would ask to be
  unlocked). After the server refused the user name or password, automatic syncing pauses (repeated
  failed logins can lock an account) until the person syncs by hand or connects again. A sync that
  couldn't reach the server, or that the server failed, says it is tried again later — the answers
  to finding, connecting and disconnecting don't, as nothing retries those.
* **How.** ``httpx`` with TLS verification (``SSL_CERT_FILE`` is honoured for a private CA), Basic
  authentication, no redirects followed for the calendar itself (a moved calendar is reported with
  its new address) and a :data:`TIMEOUT_S` second timeout. Finding calendars follows redirects on
  the same host only (a server's web root often redirects to its login page). A server's XML
  answer is read up to :data:`MAX_RESPONSE_BYTES` and refused if it declares a DTD. Errors are words for people (:class:`CalDavError`) and never
  contain the password; one event the server refuses doesn't stop the others.
"""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import logging
import re
import ssl
import threading
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from icalendar import Alarm, Calendar, Event
from icalendar.cal import Component
from pydantic import ValidationError

from ordnung import __version__
from ordnung.calendar import ics
from ordnung.calendar.secrets import SecretStore, SecretsUnavailable, account_name
from ordnung.clock import real_now_iso
from ordnung.db.store import Store
from ordnung.models import (
    CalendarEventPreview,
    CalendarSyncErrorKind,
    CalendarSyncMode,
    CalendarSyncReport,
    CalendarSyncState,
)

log = logging.getLogger(__name__)

STATE_KEY = "calendar_sync"
TIMEOUT_S = 20.0
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_URL_CHARS = 2048
MAX_USERNAME_CHARS = 256
MAX_PASSWORD_CHARS = 1024
USER_AGENT = f"Ordnung/{__version__} (calendar sync)"
RESOURCE_PREFIX = "ordnung-"
DAV = "DAV:"
CALDAV = "urn:ietf:params:xml:ns:caldav"
DISCREET_DEFAULT = "Ordnung: deadline"
DISCREET_TITLES: dict[str, str] = {"payment": "Ordnung: payment", "appointment": "Ordnung: appointment"}
DISCREET_INCOMING = "Ordnung: money in"
DISCREET_DESCRIPTION = "Open Ordnung on your computer to see what this is — the details stay there."
DISCREET_CHECK_TITLE = " — check the date"
DISCREET_CHECK = "This date couldn't be confirmed in the letter: check it in Ordnung before you rely on it."
#: errors after which the rest of a run is pointless (every other request would fail the same way)
FATAL: frozenset[CalendarSyncErrorKind] = frozenset(
    {"address", "auth", "forbidden", "not_found", "network", "tls", "unavailable"}
)
#: errors the next sync of the tick may well get past (the report says it is tried again)
RETRIED: frozenset[CalendarSyncErrorKind] = frozenset({"network", "server"})
RETRY_NOTE = "Ordnung tries again later."
PROPFIND_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b'<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>'
    b"<d:resourcetype/><d:displayname/><c:supported-calendar-component-set/>"
    b"</d:prop></d:propfind>"
)
PRINCIPAL_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b'<d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/></d:prop></d:propfind>'
)
HOME_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>\n'
    b'<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop>'
    b"<c:calendar-home-set/></d:prop></d:propfind>"
)
MAX_REDIRECTS = 3
MAX_CALENDARS = 50
#: refusals that end a search for calendars (anything else — a redirect too — : look further)
_STOP_DISCOVERY: frozenset[CalendarSyncErrorKind] = frozenset({"auth", "forbidden", "network", "tls"})
CONFLICT_MESSAGE = (
    "The calendar refused an event, perhaps because it already holds a copy imported from Ordnung's "
    "calendar file. A calendar of its own for Ordnung avoids this."
)
#: a refusal that is about an event's UID (Nextcloud answers a UID clash with 400 and says so)
_UID_CLASH = re.compile(rb"\buid\b|no-uid-conflict", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")
_DTD = re.compile(rb"<!(DOCTYPE|ENTITY)", re.IGNORECASE)
# re-entrant: "Delete everything" disconnects while it holds it (see :func:`exclusive`)
_LOCK = threading.RLock()


class CalDavError(RuntimeError):
    """Calendar sync can't do what was asked; the message is written for people."""

    def __init__(self, kind: CalendarSyncErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: CalendarSyncErrorKind = kind


@dataclass(frozen=True)
class SyncEvent:
    """One event as it is sent: its resource name, bytes, digest and what the preview shows."""

    href: str
    uid: str
    body: bytes
    digest: str
    preview: CalendarEventPreview


@dataclass(frozen=True)
class FoundCalendar:
    """A calendar that takes events, as :func:`discover` found it."""

    url: str
    name: str | None


@dataclass(frozen=True)
class _Resource:
    """What one ``<d:response>`` of a ``PROPFIND`` answer says about a resource."""

    url: str
    is_calendar: bool = False
    takes_events: bool = True
    name: str | None = None
    principal: str | None = None
    home: str | None = None


# --------------------------------------------------------------------------------------------------
# the address and the connection's state
# --------------------------------------------------------------------------------------------------


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_url(raw: str) -> str:
    """The calendar's address as Ordnung uses it (a collection: ending in ``/``), or :class:`CalDavError`."""
    url = raw.strip()
    if not url or len(url) > MAX_URL_CHARS or _CONTROL.search(url) or " " in url:
        raise CalDavError("address", "Enter the calendar's address, starting with https://.")
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme not in ("https", "http") or not host:
        raise CalDavError("address", "Enter the calendar's address, starting with https://.")
    if parts.scheme == "http" and not _is_loopback(host):
        raise CalDavError(
            "address",
            "Use the https:// address: over http:// the app password and your dates would travel unencrypted.",
        )
    if parts.username is not None or parts.password is not None:
        raise CalDavError(
            "address", "Leave the user name and password out of the address — they have their own fields."
        )
    if parts.fragment:
        raise CalDavError("address", "The address can't contain a #.")
    path = parts.path if parts.path.endswith("/") else f"{parts.path}/"
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, parts.query, ""))


def check_username(raw: str) -> str:
    """The user name (trimmed), or :class:`CalDavError`."""
    name = raw.strip()
    if not name or len(name) > MAX_USERNAME_CHARS or _CONTROL.search(name):
        raise CalDavError("auth", "Enter the user name you sign in to your calendar with.")
    return name


def load_state(store: Store) -> CalendarSyncState | None:
    """The connection, if the person connected a calendar (an unreadable record counts as none)."""
    raw = store.get_meta(STATE_KEY)
    if not raw:
        return None
    try:
        return CalendarSyncState.model_validate_json(raw)
    except ValidationError:
        log.warning("calendar sync: the stored connection can't be read; treating it as not connected")
        return None


def save_state(store: Store, state: CalendarSyncState | None) -> None:
    store.set_meta(STATE_KEY, state.model_dump_json() if state is not None else None)


def host_of(url: str) -> str:
    return urlsplit(url).hostname or url


# --------------------------------------------------------------------------------------------------
# the events
# --------------------------------------------------------------------------------------------------


def resource_name(uid: str) -> str:
    """``ordnung-<id>.ics`` for ``<id>@ordnung.local`` (other characters replaced, then a short hash)."""
    local = uid.split("@", 1)[0]
    safe = _UNSAFE_NAME.sub("_", local)
    if safe != local or not safe:
        safe = f"{safe}-{hashlib.sha256(uid.encode('utf-8')).hexdigest()[:10]}"
    return f"{RESOURCE_PREFIX}{safe}.ics"


def _kinds(event: Event) -> list[str]:
    value = event.get("categories")
    values = value if isinstance(value, list) else [value] if value is not None else []
    return [str(cat) for item in values for cat in getattr(item, "cats", [])]


def discreet_event(event: Event, *, incoming: bool = False) -> Event:
    """``event`` without anything but its date, time and alarms (module policy); ``incoming``: money
    coming in, not a payment to make."""
    kinds = _kinds(event)
    title = (
        DISCREET_INCOMING
        if incoming
        else next((DISCREET_TITLES[kind] for kind in kinds if kind in DISCREET_TITLES), DISCREET_DEFAULT)
    )
    description = DISCREET_DESCRIPTION
    if str(event.get("summary", "")).startswith(ics.CHECK_PREFIX):
        title += DISCREET_CHECK_TITLE
        description = f"{description} {DISCREET_CHECK}"
    quiet = Event()
    for name in ("uid", "dtstamp", "last-modified", "dtstart", "dtend", "transp"):
        if name in event:
            quiet[name] = event[name]
    quiet.add("summary", title)
    quiet.add("description", description)
    for alarm in event.walk("VALARM"):
        plain = Alarm()
        plain.add("action", "DISPLAY")
        plain.add("description", title)
        plain["trigger"] = alarm["trigger"]
        quiet.add_component(plain)
    return quiet


def _resource(event: Event, timezones: dict[str, Component]) -> bytes:
    """One event as a calendar object resource (RFC 4791 §4.1: one UID, no METHOD)."""
    calendar = Calendar()
    calendar.add("prodid", ics.PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    tzids: set[str] = set()
    for name in ("dtstart", "dtend"):
        prop = event.get(name)
        tzid = getattr(prop, "params", {}).get("TZID") if prop is not None else None
        if tzid:
            tzids.add(str(tzid))
    for tzid in sorted(tzids):
        if tzid in timezones:
            calendar.add_component(timezones[tzid])
    calendar.add_component(event)
    return bytes(calendar.to_ical())


def _alarm_label(start: date | datetime, trigger: timedelta) -> str:
    """When an alarm rings relative to its event: "on the day at 09:00", "3 days before at 09:00"."""
    begin = start if isinstance(start, datetime) else datetime.combine(start, time())
    moment = begin + trigger
    days = (begin.date() - moment.date()).days
    clock = moment.strftime("%H:%M")
    if days == 0:
        return f"on the day at {clock}"
    if days == 1:
        return f"the day before at {clock}"
    if days > 1:
        return f"{days} days before at {clock}"
    return f"{-days} day{'s' if days != -1 else ''} after at {clock}"


def _preview(event: Event) -> CalendarEventPreview:
    start = event.decoded("dtstart")
    all_day = not isinstance(start, datetime)
    alarms = [
        _alarm_label(start, trigger)
        for alarm in event.walk("VALARM")
        if isinstance(trigger := alarm.decoded("trigger"), timedelta)
    ]
    location = event.get("location")
    return CalendarEventPreview(
        uid=str(event.get("uid")),
        summary=str(event.get("summary", "")),
        start=start.isoformat(),
        all_day=all_day,
        description=str(event.get("description", "")),
        location=str(location) if location else None,
        alarms=alarms,
    )


def build_events(store: Store, mode: CalendarSyncMode) -> list[SyncEvent]:
    """Every event calendar sync sends in ``mode``, in the calendar file's order (module policy)."""
    parsed = Calendar.from_ical(ics.build_ics(store))
    timezones: dict[str, Component] = {str(tz.get("tzid")): tz for tz in parsed.timezones}
    incoming = {ics.item_uid(item.id) for item in store.list_items(kind="payment") if item.direction == "in"}
    events: list[SyncEvent] = []
    seen: set[str] = set()
    for original in parsed.events:
        if mode == "discreet":
            event = discreet_event(original, incoming=str(original.get("uid")) in incoming)
        else:
            event = original
        uid = str(event.get("uid"))
        href = resource_name(uid)
        if href in seen:  # never two events under one name
            continue
        seen.add(href)
        body = _resource(event, timezones)
        events.append(
            SyncEvent(
                href=href,
                uid=uid,
                body=body,
                digest=hashlib.sha256(body).hexdigest(),
                preview=_preview(event),
            )
        )
    return events


def preview(store: Store, mode: CalendarSyncMode) -> list[CalendarEventPreview]:
    """Exactly what each event would contain in ``mode`` (Settings → Calendar)."""
    return [event.preview for event in build_events(store, mode)]


# --------------------------------------------------------------------------------------------------
# talking to the server
# --------------------------------------------------------------------------------------------------


def _moved(url: str, response: httpx.Response) -> CalDavError:
    location = response.headers.get("location")
    if location:
        target = urljoin(url, location)
        parts = urlsplit(target)
        if parts.scheme == "https" or (parts.scheme == "http" and _is_loopback(parts.hostname or "")):
            return CalDavError("address", f"The calendar has moved to {target} — use that address.")
    return CalDavError("address", "The server sent Ordnung to another address. Check the calendar's address.")


def http_error(url: str, response: httpx.Response, action: str) -> CalDavError:
    """What an unsuccessful answer means, in words (``action``: "read the calendar", "add an event")."""
    code = response.status_code
    if 300 <= code < 400:
        return _moved(url, response)
    if code == 401:
        return CalDavError("auth", "The calendar server refused the user name or app password.")
    if code == 403:
        return CalDavError(
            "forbidden",
            f"The calendar server doesn't let this account {action} (is the calendar read-only?).",
        )
    if code == 404:
        return CalDavError("not_found", "There is no calendar at this address.")
    if code in (409, 412):
        return CalDavError("conflict", CONFLICT_MESSAGE)
    if code == 507:
        return CalDavError("server", "The calendar is full (the server has no space left).")
    if code >= 500:
        return CalDavError("server", f"The calendar server had a problem (HTTP {code}).")
    return CalDavError("server", f"The calendar server didn't {action} (HTTP {code}).")


def _network_error(url: str, exc: httpx.HTTPError) -> CalDavError:
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return CalDavError(
                "tls",
                f"The certificate of {host_of(url)} couldn't be verified, so nothing was sent. "
                "(For a server with its own certificate authority, point SSL_CERT_FILE at it.)",
            )
        cause = cause.__cause__ or cause.__context__
    if isinstance(exc, httpx.TimeoutException):
        return CalDavError("network", f"{host_of(url)} didn't answer in time.")
    return CalDavError("network", f"Couldn't reach {host_of(url)}.")


class CalDavClient:
    """The few requests calendar sync makes to one calendar collection (module policy)."""

    def __init__(
        self, url: str, username: str, password: str, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.url = url
        #: a redirect finding calendars didn't follow (another host): named when nothing is found
        self._moved: CalDavError | None = None
        self._http = httpx.Client(
            auth=httpx.BasicAuth(username, password),
            timeout=TIMEOUT_S,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> CalDavClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _send(self, method: str, url: str, **kwargs: Any) -> tuple[httpx.Response, bytes]:
        """One request; the answer's body is read up to :data:`MAX_RESPONSE_BYTES` (then refused)."""
        try:
            with self._http.stream(method, url, **kwargs) as response:
                body = bytearray()
                for block in response.iter_bytes():
                    body += block
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise CalDavError("server", "The calendar server's answer was too large to read.")
                return response, bytes(body)
        except httpx.HTTPError as exc:
            raise _network_error(url, exc) from None

    def _propfind(self, url: str, body: bytes, depth: str, *, follow: bool = False) -> list[_Resource]:
        """``PROPFIND`` ``url``: what the answer says about each resource. ``follow`` follows up to
        :data:`MAX_REDIRECTS` redirects on the same host (a server's ``/.well-known/caldav``)."""
        for _ in range(MAX_REDIRECTS + 1):
            response, answer = self._send(
                "PROPFIND",
                url,
                content=body,
                headers={"Depth": depth, "Content-Type": "application/xml; charset=utf-8"},
            )
            location = response.headers.get("location")
            if follow and response.is_redirect and location:
                target = urljoin(url, location)
                if urlsplit(target).netloc.lower() != urlsplit(url).netloc.lower() or not _allowed(target):
                    raise _moved(url, response)
                url = target
                continue
            if response.status_code != 207:
                if response.is_success:
                    raise CalDavError(
                        "not_calendar",
                        "This address doesn't speak CalDAV — use the calendar's CalDAV address.",
                    )
                raise http_error(url, response, "read the calendar")
            return read_resources(answer, url)
        raise CalDavError(
            "address", "The server sent Ordnung around in circles. Check the calendar's address."
        )

    def probe(self) -> str | None:
        """Check that the address is a calendar that takes events; returns its display name."""
        found = self._propfind(self.url, PROPFIND_BODY, "0")
        if not found:
            raise CalDavError("not_calendar", "This address is not a calendar Ordnung can write into.")
        return check_calendar(found[0])

    def _calendars(self, url: str) -> list[FoundCalendar]:
        """The calendars that take events directly inside ``url`` (depth 1)."""
        try:
            found = self._propfind(url, PROPFIND_BODY, "1")
        except CalDavError as exc:
            if exc.kind in _STOP_DISCOVERY:
                raise
            return []
        calendars = []
        for resource in found:
            if not (resource.is_calendar and resource.takes_events):
                continue
            try:
                calendars.append(FoundCalendar(url=check_url(resource.url), name=resource.name))
            except CalDavError:
                continue
        return calendars[:MAX_CALENDARS]

    def _pointer(self, url: str, body: bytes, field: str) -> str | None:
        """The principal or calendar-home URL ``url`` names (``None``: it names none)."""
        try:
            found = self._propfind(url, body, "0", follow=True)
        except CalDavError as exc:
            if exc.kind in _STOP_DISCOVERY:
                raise
            if exc.kind == "address" and self._moved is None:
                self._moved = exc
            return None
        for resource in found:
            target = getattr(resource, field)
            if target:
                return str(target)
        return None

    def discover(self) -> list[FoundCalendar]:
        """The calendars that take events at or under this address (see :func:`discover`).

        A redirect of the address itself is not the end: a web app's root (Nextcloud's) answers
        with its login page, and the account's calendars are then found from the principal or the
        server's ``/.well-known/caldav``. Only a redirect to another host, which isn't followed, is
        named — when nothing was found."""
        try:
            return [FoundCalendar(url=self.url, name=self.probe())]
        except CalDavError as exc:
            if exc.kind in _STOP_DISCOVERY:
                raise
        found = self._calendars(self.url)
        if found:
            return found
        for start in (self.url, urljoin(self.url, "/.well-known/caldav")):
            principal = self._pointer(start, PRINCIPAL_BODY, "principal")
            home = self._pointer(principal, HOME_BODY, "home") if principal else None
            found = self._calendars(home) if home else []
            if found:
                return found
        if self._moved is not None:
            raise self._moved
        raise CalDavError(
            "not_calendar",
            "No calendar for events was found at this address. Create a calendar named “Ordnung” in your "
            "calendar app (or copy a calendar's CalDAV address) and try again.",
        )

    def put(self, href: str, body: bytes) -> None:
        url = urljoin(self.url, href)
        response, answer = self._send(
            "PUT", url, content=body, headers={"Content-Type": "text/calendar; charset=utf-8"}
        )
        if response.is_success:
            return
        if response.status_code in (400, 403) and _UID_CLASH.search(answer):
            raise CalDavError("conflict", CONFLICT_MESSAGE)
        raise http_error(self.url, response, "add or change events")

    def delete(self, href: str) -> None:
        url = urljoin(self.url, href)
        response, _ = self._send("DELETE", url)
        if not response.is_success and response.status_code != 404:  # already gone is fine
            raise http_error(self.url, response, "remove events")


def _xml(body: bytes) -> ET.Element:
    if _DTD.search(body):
        raise CalDavError("server", "The calendar server's answer couldn't be read.")
    try:
        return ET.fromstring(body)
    except ET.ParseError:
        raise CalDavError("server", "The calendar server's answer couldn't be read.") from None


def _allowed(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" or (parts.scheme == "http" and _is_loopback(parts.hostname or ""))


def _href(base: str, element: ET.Element | None) -> str | None:
    """The absolute https (or loopback) URL in ``element``'s ``<d:href>`` (``None``: none usable)."""
    text = (element.findtext(f"{{{DAV}}}href") or "").strip() if element is not None else ""
    if not text:
        return None
    url = urljoin(base, text)
    return url if _allowed(url) else None


def read_resources(body: bytes, base: str) -> list[_Resource]:
    """What a ``PROPFIND`` answer says about each resource (only properties the server found)."""
    root = _xml(body)
    resources = []
    for response in root.iter(f"{{{DAV}}}response"):
        href = (response.findtext(f"{{{DAV}}}href") or "").strip()
        props: dict[str, Any] = {}
        for propstat in response.iter(f"{{{DAV}}}propstat"):
            status = propstat.findtext(f"{{{DAV}}}status") or ""
            prop = propstat.find(f"{{{DAV}}}prop")
            if prop is None or " 200 " not in f"{status} ":
                continue
            kinds = prop.find(f"{{{DAV}}}resourcetype")
            if kinds is not None:
                props["is_calendar"] = kinds.find(f"{{{CALDAV}}}calendar") is not None
            components = prop.find(f"{{{CALDAV}}}supported-calendar-component-set")
            if components is not None:
                names = {(comp.get("name") or "").upper() for comp in components.iter(f"{{{CALDAV}}}comp")}
                props["takes_events"] = not names or "VEVENT" in names
            name = (prop.findtext(f"{{{DAV}}}displayname") or "").strip()
            if name:
                props["name"] = name[:200]
            principal = _href(base, prop.find(f"{{{DAV}}}current-user-principal"))
            if principal:
                props["principal"] = principal
            home = _href(base, prop.find(f"{{{CALDAV}}}calendar-home-set"))
            if home:
                props["home"] = home
        resources.append(_Resource(url=urljoin(base, href) if href else base, **props))
    return resources


def check_calendar(resource: _Resource) -> str | None:
    """``resource``'s name if it is a calendar that takes events, else :class:`CalDavError`."""
    if not resource.is_calendar:
        raise CalDavError(
            "not_calendar",
            "This address is not one calendar (perhaps the list of all calendars) — use the address of the "
            "calendar Ordnung should write into.",
        )
    if not resource.takes_events:
        raise CalDavError(
            "not_calendar", "This calendar only takes tasks, not events — choose a calendar for events."
        )
    return resource.name


# --------------------------------------------------------------------------------------------------
# connect, sync, disconnect
# --------------------------------------------------------------------------------------------------


def exclusive() -> contextlib.AbstractContextManager[Any]:
    """Hold calendar sync's lock: no sync, connect or disconnect runs (or writes its record) meanwhile."""
    return _LOCK


def _report(**counts: Any) -> CalendarSyncReport:
    return CalendarSyncReport(at=real_now_iso(), **counts)


def _password(secrets: SecretStore, state: CalendarSyncState) -> str:
    try:
        password = secrets.get(account_name(state.username, state.url))
    except SecretsUnavailable as exc:
        raise CalDavError("unavailable", str(exc)) from None
    if password is None:
        raise CalDavError(
            "auth", "The app password isn't saved on this computer — enter it again in Settings → Calendar."
        )
    return password


def _push(
    state: CalendarSyncState,
    events: list[SyncEvent],
    password: Callable[[], str],
    transport: httpx.BaseTransport | None,
) -> CalendarSyncReport:
    """Send what changed and remove what left (module policy); updates ``state.events`` as it goes.
    ``password`` is asked for only when something is to be sent or removed."""
    wanted = {event.href for event in events}
    changed = [event for event in events if state.events.get(event.href) != event.digest]
    gone = sorted(href for href in state.events if href not in wanted)
    unchanged = len(events) - len(changed)
    if not changed and not gone:
        return _report(unchanged=unchanged)
    sent = removed = failed = 0
    error: CalDavError | None = None
    with CalDavClient(state.url, state.username, password(), transport=transport) as client:
        for event in changed:
            try:
                client.put(event.href, event.body)
            except CalDavError as exc:
                error = exc
                if exc.kind in FATAL:
                    break
                # its old digest (if it was sent before) stays: it is tried again, and still
                # removed should it leave the export
                failed += 1
                continue
            state.events[event.href] = event.digest
            sent += 1
        if error is None or error.kind not in FATAL:
            for href in gone:
                try:
                    client.delete(href)
                except CalDavError as exc:
                    error = exc
                    if exc.kind in FATAL:
                        break
                    failed += 1
                    continue
                state.events.pop(href, None)
                removed += 1
    if error is not None and error.kind in FATAL:
        failed = len(changed) + len(gone) - sent - removed
    return _report(
        sent=sent,
        removed=removed,
        unchanged=unchanged,
        failed=failed,
        error=str(error) if error else None,
        error_kind=error.kind if error else None,
    )


def _finish(store: Store, state: CalendarSyncState, report: CalendarSyncReport) -> CalendarSyncReport:
    if report.error and report.error_kind in RETRIED:  # the tick's next check sends it (module policy)
        report = report.model_copy(update={"error": f"{report.error} {RETRY_NOTE}"})
    state.last = report
    state.paused = report.error_kind == "auth"
    save_state(store, state)
    if report.sent or report.removed:
        store.log_activity(
            "calendar.synced",
            f"Calendar sync ({state.mode}) to {host_of(state.url)}: {report.sent} sent, {report.removed} removed",
        )
    if report.error:
        log.info("calendar sync: %s", report.error)
    return report


def _run(
    store: Store, state: CalendarSyncState, secrets: SecretStore, transport: httpx.BaseTransport | None
) -> CalendarSyncReport:
    try:
        report = _push(state, build_events(store, state.mode), lambda: _password(secrets, state), transport)
    except CalDavError as exc:
        report = _report(error=str(exc), error_kind=exc.kind)
    return _finish(store, state, report)


def sync(
    store: Store,
    secrets: SecretStore,
    *,
    transport: httpx.BaseTransport | None = None,
    automatic: bool = False,
) -> CalendarSyncReport | None:
    """Send what changed to the connected calendar (module policy).

    ``None`` when no calendar is connected, in the demo, or — for an ``automatic`` run — while
    syncing is paused after a refused password. Never raises for the server's or the network's
    problems: the report says what happened.
    """
    with _LOCK:
        state = load_state(store)
        if state is None or store.get_settings().demo or (automatic and state.paused):
            return None
        return _run(store, state, secrets, transport)


def scheduled_sync(store: Store) -> CalendarSyncReport | None:
    """The daily tick's sync (every check while connected; see :func:`sync`)."""
    from ordnung.calendar.secrets import KeyringSecrets

    if store.get_meta(STATE_KEY) is None:  # not connected: no keyring, no network
        return None
    return sync(store, KeyringSecrets(), automatic=True)


def discover(
    url: str, username: str, password: str, *, transport: httpx.BaseTransport | None = None
) -> list[FoundCalendar]:
    """The calendars that take events, found from a calendar's, an account's or a server's address.

    The address itself if it is a calendar; else the calendars inside it; else those of the
    account's calendar home (``current-user-principal`` → ``calendar-home-set``, RFC 4791 §6.2),
    from the address or the server's ``/.well-known/caldav`` (RFC 6764). Only https (or loopback)
    addresses the server names are followed. Nothing is stored and nothing is written.
    """
    url, username = check_url(url), check_username(username)
    if not password or len(password) > MAX_PASSWORD_CHARS:
        raise CalDavError("auth", "Enter the app password for this calendar.")
    with CalDavClient(url, username, password, transport=transport) as client:
        return client.discover()


def connect(
    store: Store,
    secrets: SecretStore,
    *,
    url: str,
    username: str,
    password: str | None,
    mode: CalendarSyncMode,
    transport: httpx.BaseTransport | None = None,
) -> CalendarSyncReport:
    """Connect (or update) the calendar and send the events (module policy).

    ``password=None`` keeps the saved one (to change the mode, or to retry). Raises
    :class:`CalDavError` when the calendar can't be used; nothing is stored then.
    """
    url, username = check_url(url), check_username(username)
    if password is not None and (not password or len(password) > MAX_PASSWORD_CHARS):
        raise CalDavError("auth", "Enter the app password for this calendar.")
    problem = secrets.problem()
    if problem is not None:
        raise CalDavError("unavailable", str(problem))
    with _LOCK:
        state = load_state(store)
        if state is not None and (state.url, state.username) != (url, username):
            raise CalDavError(
                "conflict",
                f"Ordnung is connected to {host_of(state.url)} already. Disconnect that calendar first.",
            )
        fresh = CalendarSyncState(url=url, username=username, mode=mode)
        use = password if password is not None else _password(secrets, fresh)
        with CalDavClient(url, username, use, transport=transport) as client:
            name = client.probe()
        try:
            if password is not None:
                secrets.set(account_name(username, url), password)
        except SecretsUnavailable as exc:
            raise CalDavError("unavailable", str(exc)) from None
        if state is None:
            store.log_activity(
                "calendar.connected", f"Connected the calendar at {host_of(url)} for calendar sync ({mode})"
            )
            state = fresh
        state.mode, state.calendar_name, state.paused = mode, name, False
        save_state(store, state)
        try:
            report = _push(state, build_events(store, state.mode), lambda: use, transport)
        except CalDavError as exc:
            report = _report(error=str(exc), error_kind=exc.kind)
        return _finish(store, state, report)


def disconnect(
    store: Store,
    secrets: SecretStore,
    *,
    remove_events: bool,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Forget the calendar and its password; with ``remove_events`` first remove every event Ordnung
    put there (only those). Returns how many were removed. Raises :class:`CalDavError` (and keeps
    the connection) when the events can't be removed."""
    with _LOCK:
        state = load_state(store)
        if state is None:
            return 0
        removed = 0
        if remove_events and state.events:
            password = _password(secrets, state)
            with CalDavClient(state.url, state.username, password, transport=transport) as client:
                for href in sorted(state.events):
                    client.delete(href)
                    state.events.pop(href)
                    removed += 1
                    save_state(store, state)
        with contextlib.suppress(SecretsUnavailable):  # then nothing could have been stored there
            secrets.delete(account_name(state.username, state.url))
        save_state(store, None)
        note = f", removed {removed} events" if remove_events else ", its events were left in the calendar"
        store.log_activity(
            "calendar.disconnected", f"Disconnected the calendar at {host_of(state.url)}{note}"
        )
        return removed
