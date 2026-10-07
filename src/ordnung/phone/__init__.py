"""Phone access over the home network: a paired phone uses Ordnung in its browser (ADR 0017).

Policy
------

* **Off until turned on, never in the demo.** Settings → Phone on the computer turns on a second
  listener inside ``ordnung serve``: HTTPS on one private IPv4 address of this computer and a saved
  port, never ``0.0.0.0``. The computer's own listener, its session token and the CLI don't change.
  Without a session token (``--no-token``) phone access can't be turned on.
* **Only phones paired here.** A one-time code shown on the computer (QR code or typed) pairs one
  phone. Each phone gets its own sign-in in the cookie :func:`cookie_name` names; only a hash of it is
  stored. The session token is never accepted on the phone listener, and a phone's cookie never on
  the computer's. Removing a phone on the computer signs it out at once.
* **On your phone you can look, add, write and tick off; settings, backups, phone access and deleting
  stay on your computer.** A phone may look at everything the everyday pages show, add letters
  (photos or files) and to-dos, write letters, answer Ideas, ask, and correct or tick off what exists.
  It may not delete anything, download files or records (originals, generated PDFs, exports), change
  settings, the profile, phone access, calendar sync, hand-off sync, the watched folder or backups,
  decide about held letters or let Claude read a letter kept private, or start background model work
  beyond those everyday actions. The exact list is :mod:`ordnung.phone.scope`, checked before routing
  and published in the OpenAPI schema (``x-ordnung-phone``); a route nobody classified is refused on a
  phone.
* **The letters stay on the computer.** The phone shows them; API answers carry ``no-store``, and on
  a phone the numbers of *My numbers* and the profile show only their last 4 characters
  (:mod:`ordnung.phone.mask`). What a phone changes is attributed to it in the privacy log
  (:mod:`ordnung.phone.actor`).
* **Home network only, and only this network.** The listener answers devices in its own subnet, never
  through a tunnel, VPN, container or virtual machine; it pauses when this computer leaves the address
  or the router changes (:mod:`ordnung.phone.net`). Its certificate authority may vouch for that one
  address only (:mod:`ordnung.phone.tls`).
* **The listener never takes over the process.** It is started with ``startup()`` and stopped with
  ``shutdown()``, never ``serve()`` or ``run()`` (they would take over Ctrl+C and SIGTERM, and
  sse-starlette's shutdown watcher could bind to it); sse-starlette's ``AppStatus.should_exit`` is never
  set (it would end the computer's streams); its lifespan is off. Removing a phone or turning phone
  access off ends live streams only — a request that writes always finishes (it may hold the ledger
  lock). See :mod:`ordnung.phone.access`.

Refusals answer ``{"detail": <words for the person>, "code": <PhoneErrorCode>}`` with the status
:data:`ERROR_STATUS` gives that code.
"""

from __future__ import annotations

from typing import Literal

#: Every ``code`` a phone-access refusal carries (the gate's before routing, the routes' after).
PhoneErrorCode = Literal[
    # the phone listener's gate, before routing
    "misdirected",  # 421: the request didn't come in on the phone listener it names
    "wrong_host",  # 400: Host isn't exactly <address>:<port>
    "bad_path",  # 400: a "." or ".." segment, "//" or "\" in the path
    "unexpected_body",  # 400: a GET or HEAD with a body before sign-in
    "length_required",  # 411: a body without Content-Length (Transfer-Encoding)
    "too_large",  # 413: more than the pairing request (before sign-in) or the upload limit allows
    "not_home_network",  # 403: the client isn't on the home network's subnet
    "cross_site",  # 403: Fetch-Metadata or Origin say another site sent it
    "phone_not_paired",  # 401: no device cookie, or one this computer doesn't know (any more)
    "computer_only",  # 403: the operation isn't on the phone's allow-list (or a field rule refuses it)
    "too_many",  # 429: too many pairing tries, or a phone's hourly limit (with Retry-After)
    # the routes
    "unavailable",  # 409: the demo, no session token (--no-token), or phone access is off
    "not_set_up",  # 409: Ordnung isn't set up yet (onboarding)
    "no_network",  # 409: this computer isn't on a home network
    "port_busy",  # 409: another program uses the port
    "not_listening",  # 409: phone access is paused or off, so no phone can pair now
    "too_many_phones",  # 409: the most phones Ordnung pairs are paired
    "code_used",  # 409: the code paired a phone already: neither device stays paired
    "wrong_code",  # 422: the code didn't match, or it expired, or there is none (one answer for all)
    "invalid",  # 422: the address isn't one of this computer's, or the port is out of range
    "not_phone",  # 404: pairing was sent to the computer's listener
]

ERROR_STATUS: dict[PhoneErrorCode, int] = {
    "misdirected": 421,
    "wrong_host": 400,
    "bad_path": 400,
    "unexpected_body": 400,
    "length_required": 411,
    "too_large": 413,
    "not_home_network": 403,
    "cross_site": 403,
    "phone_not_paired": 401,
    "computer_only": 403,
    "too_many": 429,
    "unavailable": 409,
    "not_set_up": 409,
    "no_network": 409,
    "port_busy": 409,
    "not_listening": 409,
    "too_many_phones": 409,
    "code_used": 409,
    "wrong_code": 422,
    "invalid": 422,
    "not_phone": 404,
}

#: ``__Host-`` makes the browser insist on ``Secure``, ``Path=/`` and no ``Domain``, so no plain-HTTP
#: page on the same address can set or shadow it.
COOKIE_PREFIX = "__Host-ordnung_phone_"
#: 400 days, the most browsers keep a cookie; re-set on every page load, so a phone in use keeps it.
COOKIE_MAX_AGE_S = 400 * 24 * 3600


def cookie_name(port: int) -> str:
    """The phone's sign-in cookie for the listener on ``port`` (``__Host-ordnung_phone_8767``).

    Browsers send a cookie to every port of an address, so the port in the name keeps two data
    folders' phone access apart on one computer.
    """
    return f"{COOKIE_PREFIX}{port}"


class PhoneRefusal(Exception):
    """A phone-access refusal: answered ``{"detail", "code"}`` with :data:`ERROR_STATUS`'s status (and
    ``Retry-After`` when ``retry_after`` is given)."""

    def __init__(self, code: PhoneErrorCode, detail: str, *, retry_after: int | None = None) -> None:
        super().__init__(detail)
        self.code: PhoneErrorCode = code
        self.detail = detail
        self.retry_after = retry_after

    @property
    def status(self) -> int:
        return ERROR_STATUS[self.code]

    def body(self) -> dict[str, str]:
        return {"detail": self.detail, "code": self.code}

    def headers(self) -> dict[str, str] | None:
        return {"Retry-After": str(self.retry_after)} if self.retry_after is not None else None
