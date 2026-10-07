"""Settings → Phone: use Ordnung on a phone over the home network (policy: :mod:`ordnung.phone`).

On the computer (computer-only, :mod:`ordnung.phone.scope`):

* ``GET /api/phone`` — whether phone access can be used here, is on and listening, at which address,
  the certificate's fingerprints, the pairing code's progress (never the code) and the paired phones
  (never their sign-in). It re-checks this computer's addresses and writes nothing; the pairing
  dialog polls it.
* ``PUT /api/phone`` — turn phone access on or off, choose the address or port, or confirm that the
  network this computer is on now is the home network.
* ``POST /api/phone/pairing`` — a new pairing code (the only answer that contains it);
  ``DELETE /api/phone/pairing`` cancels it (closing the dialog).
* ``DELETE /api/phone/devices/{device_id}`` — remove a phone: it is signed out at once.
* ``POST /api/phone/reset`` — "Start over": off, every phone removed, a new certificate next time.

On a phone, before it is paired (the only operation a phone reaches without its sign-in):

* ``POST /api/phone/pair`` — the code and the phone's name; the answer sets the phone's sign-in cookie
  (:func:`ordnung.phone.cookie_name`) and names the two words both screens show.

A refusal answers ``{"detail": …, "code": <kind>}`` (:data:`ordnung.phone.PhoneErrorCode`). Never in
the demo.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import ApiState, CtxDep, StateDep
from ordnung.app_context import AppContext
from ordnung.phone import ERROR_STATUS, PhoneErrorCode

router = APIRouter(tags=["phone"])

DEFAULT_PORT = 8767
DEMO_MESSAGE = "The demo never opens itself to your network. Install Ordnung to use it from your phone."
NOT_FOUND = "This phone isn't paired (any more)."
NOT_PHONE_MESSAGE = "Pairing works from a phone: scan the code in Settings → Phone with your phone's camera."
_NOT_BUILT = "Phone access isn't part of this version of Ordnung yet."

_RESPONSE = ConfigDict(json_schema_serialization_defaults_required=True)

ProblemCode = Literal["no_network", "address_gone", "other_network", "port_busy", "failed"]
NoticeCode = Literal["pairing_stopped", "code_reused", "token_reuse"]

CHANGE_REFUSALS: dict[int | str, dict[str, Any]] = {
    409: {
        "description": "The demo or no session token (``unavailable``), Ordnung isn't set up yet "
        "(``not_set_up``), no home network (``no_network``) or the port is in use (``port_busy``)"
    },
    422: {
        "description": "The address isn't one of this computer's, or the port is out of range (``invalid``)"
    },
}
PAIRING_REFUSALS: dict[int | str, dict[str, Any]] = {
    409: {
        "description": "The demo or no session token (``unavailable``), phone access isn't listening "
        "(``not_listening``) or the most phones are paired (``too_many_phones``)"
    },
}
RESET_REFUSALS: dict[int | str, dict[str, Any]] = {409: {"description": "The demo (``unavailable``)"}}
PAIR_REFUSALS: dict[int | str, dict[str, Any]] = {
    404: {"description": "Sent to the computer's own listener, not a phone's (``not_phone``)"},
    409: {
        "description": "The code paired a phone already, so neither stays paired (``code_used``), the most "
        "phones are paired (``too_many_phones``) or phone access is off (``unavailable``)"
    },
    422: {"description": "The code didn't match, or it expired, or there is none (``wrong_code``)"},
    429: {
        "description": "Too many tries from this device or the network (``too_many``, see ``Retry-After``)"
    },
}


# --------------------------------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------------------------------


class PhoneProblem(BaseModel):
    """Why phone access is on but not listening, in words for the person (technical text only in logs)."""

    model_config = _RESPONSE

    code: ProblemCode = Field(
        description="``no_network``: no home network; ``address_gone``: this computer isn't on the saved "
        "address any more; ``other_network``: the same address on another network (the router differs); "
        "``port_busy``: another program uses the port; ``failed``: anything else"
    )
    detail: str


class AddressChoice(BaseModel):
    """An address of this computer on a home network that phone access could use."""

    model_config = _RESPONSE

    address: str = Field(description="The IPv4 address (“192.168.178.23”)")
    interface: str = Field(description="The network interface it belongs to (“en0”, “Wi-Fi”)")
    subnet: str = Field(description="Its network (“192.168.178.0/24”): only devices in it are answered")
    recommended: bool = Field(description="The address this computer reaches the internet from (never a VPN)")


class PhoneDevice(BaseModel):
    """A paired phone (never its sign-in)."""

    model_config = _RESPONSE

    id: str
    name: str = Field(description="The name given when it was paired (“Anna's iPhone”)")
    platform: str = Field(description="A summary of its browser (“iPhone · Safari”), never the User-Agent")
    check_words: str = Field(
        description="Two words the phone showed when it was paired (“amber tulip”): a phone that shows "
        "other words isn't this one"
    )
    paired_at: str
    last_seen_at: str | None = None
    last_address: str | None = Field(default=None, description="The address it was last used from")
    active: bool = Field(description="It has Ordnung open now (a live connection)")
    recent_changes: int = Field(
        description="Changes it made in the last 30 days (the privacy log, filtered by ``device``)"
    )


class PhonePairingState(BaseModel):
    """The pairing code's progress (never the code)."""

    model_config = _RESPONSE

    expires_at: str
    opened_at: str | None = Field(
        default=None, description="When a phone that isn't paired yet opened the pairing page"
    )
    opened_from: str | None = Field(default=None, description="The address that phone opened it from")
    wrong_tries: int = Field(description="Wrong codes typed on the network since this code was made")
    wrong_from: list[str] = Field(description="The addresses the wrong codes came from")


class PhoneNotice(BaseModel):
    """Something the person should know about at once (shown in the danger tone)."""

    model_config = _RESPONSE

    code: NoticeCode = Field(
        description="``pairing_stopped``: so many wrong codes were typed that the code was cancelled; "
        "``code_reused``: two devices used the same code, so neither is paired; ``token_reuse``: a phone's "
        "sign-in was used from two places, so it was signed out"
    )
    detail: str
    at: str
    addresses: list[str] = Field(description="The addresses involved")


class PhoneStatus(BaseModel):
    """What Settings → Phone shows."""

    model_config = _RESPONSE

    available: bool = Field(description="Phone access can be turned on here (never in the demo)")
    unavailable_reason: str | None = Field(default=None, description="Why not, in words")
    enabled: bool = Field(description="Phone access is turned on (the saved choice)")
    listening: bool = Field(description="Phones can reach it now")
    url: str | None = Field(default=None, description="“https://192.168.178.23:8767” while listening")
    address: str | None = Field(default=None, description="The address phone access uses")
    subnet: str | None = Field(default=None, description="The home network it answers (“192.168.178.0/24”)")
    port: int
    addresses: list[AddressChoice] = Field(description="This computer's addresses on home networks now")
    problem: PhoneProblem | None = None
    notice: PhoneNotice | None = None
    fingerprint: str | None = Field(
        default=None, description="The certificate's SHA-256 as upper-case byte pairs (“F2 08 81 E8 …”)"
    )
    ca_fingerprint: str | None = Field(
        default=None, description="The SHA-256 of the authority that issues it (what a phone may trust)"
    )
    ca_made_at: str | None = Field(
        default=None,
        description="When that authority was made: a new address makes a new one, and phones that "
        "trusted the old one should remove it",
    )
    certificate_until: str | None = Field(default=None, description="The certificate's last day")
    certificate_changed_at: str | None = Field(
        default=None, description="When the certificate last changed (phones that don't trust it warn again)"
    )
    pairing: PhonePairingState | None = Field(default=None, description="The open pairing code's progress")
    devices: list[PhoneDevice]


class PhonePairing(BaseModel):
    """A new pairing code: shown on the computer, valid once for a few minutes."""

    model_config = _RESPONSE

    url: str = Field(description="What the QR code opens: ``https://<address>:<port>/pair#<code>``")
    code: str = Field(description="The code to type instead (“K7QM2XD9PA”)")
    expires_at: str


class PhoneAccessChange(BaseModel):
    """Turn phone access on or off; choose the address or port; confirm the home network."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    address: str | None = Field(
        default=None, max_length=15, description="One of ``addresses`` (none: the saved or recommended one)"
    )
    port: int | None = Field(default=None, ge=1024, le=65535)
    home_network: bool = Field(
        default=False,
        description="“This is my home network”: the network this computer is on now is home (after "
        "``other_network``)",
    )


class PairRequest(BaseModel):
    """The code from the computer and the name this phone gets."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(max_length=32, description="As shown or typed; spaces, dashes and case don't matter")
    name: str = Field(min_length=1, max_length=40, description="This phone's name (“Anna's iPhone”)")


class PairResult(BaseModel):
    """The phone is paired: its sign-in cookie comes with this answer."""

    model_config = _RESPONSE

    name: str = Field(description="The name it got (“iPhone (2)” when the name was taken)")
    check_words: str = Field(description="Two words the computer shows next to this phone (“amber tulip”)")


# --------------------------------------------------------------------------------------------------
# helpers (contract stubs: the listener, pairing and devices come with phone access itself)
# --------------------------------------------------------------------------------------------------


def _refusal(code: PhoneErrorCode, detail: str) -> JSONResponse:
    return JSONResponse(status_code=ERROR_STATUS[code], content={"detail": detail, "code": code})


def _demo(state: ApiState, ctx: AppContext) -> bool:
    return state.demo or ctx.settings.demo


def _status(demo: bool) -> PhoneStatus:
    return PhoneStatus(
        available=not demo,
        unavailable_reason=DEMO_MESSAGE if demo else None,
        enabled=False,
        listening=False,
        port=DEFAULT_PORT,
        addresses=[],
        devices=[],
    )


def _not_built(demo: bool) -> JSONResponse:
    return _refusal("unavailable", DEMO_MESSAGE if demo else _NOT_BUILT)


# --------------------------------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------------------------------


@router.get("/phone", response_model=PhoneStatus)
async def phone_status(state: StateDep, ctx: CtxDep) -> PhoneStatus:
    """Whether phone access can be used here and is on, its address, certificate, pairing progress and
    the paired phones."""
    return _status(_demo(state, ctx))


@router.put("/phone", response_model=PhoneStatus, responses=CHANGE_REFUSALS)
async def change_phone_access(
    body: PhoneAccessChange, state: StateDep, ctx: CtxDep
) -> PhoneStatus | JSONResponse:
    """Turn phone access on (at the chosen or recommended address) or off; a new address or port means
    pairing phones again."""
    return _not_built(_demo(state, ctx))


@router.post("/phone/pairing", response_model=PhonePairing, responses=PAIRING_REFUSALS)
async def start_pairing(state: StateDep, ctx: CtxDep) -> PhonePairing | JSONResponse:
    """A new pairing code (replacing an open one): one phone, once, within minutes."""
    return _not_built(_demo(state, ctx))


@router.delete("/phone/pairing", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def cancel_pairing(state: StateDep) -> Response:
    """Cancel the open pairing code (the dialog closed)."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/phone/devices/{device_id}",
    response_model=PhoneStatus,
    responses={404: {"description": "No such phone is paired"}},
)
async def remove_phone(device_id: str, state: StateDep, ctx: CtxDep) -> PhoneStatus:
    """Remove a paired phone: it is signed out at once and its live connections end."""
    raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)


@router.post("/phone/reset", response_model=PhoneStatus, responses=RESET_REFUSALS)
async def reset_phone_access(state: StateDep, ctx: CtxDep) -> PhoneStatus | JSONResponse:
    """Start over: turn phone access off, remove every phone and its certificate (a new one is made
    when it is turned on again)."""
    return _not_built(_demo(state, ctx))


@router.post("/phone/pair", response_model=PairResult, responses=PAIR_REFUSALS)
async def pair_phone(body: PairRequest, request: Request, state: StateDep) -> PairResult | JSONResponse:
    """Pair this phone with the code shown on the computer; the answer sets its sign-in cookie."""
    return _refusal("not_phone", NOT_PHONE_MESSAGE)
