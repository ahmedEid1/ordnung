"""Which paired phone made a change, for the privacy log (policy: :mod:`ordnung.phone`).

The phone listener's gate runs every admitted phone request inside :func:`acting`. While it runs, every
entry the request writes to the activity log ("Privacy & AI usage") says “(on Anna's iPhone)” and
carries the phone's id as ``device`` in its data (:func:`attribute`, called by
``Store.log_activity``), so the privacy log can be filtered by phone. Work the request merely started
— a reading queued for the worker, the Ideas refreshed in the background — is not the phone's once
the request has ended: the attribution closes with the request.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DeviceRef:
    """The paired phone a request came from."""

    id: str
    name: str


@dataclass
class _Acting:
    device: DeviceRef
    open: bool = field(default=True)


_CURRENT: ContextVar[_Acting | None] = ContextVar("ordnung_phone_actor", default=None)


def current() -> DeviceRef | None:
    """The phone whose request is running here (``None``: the computer, or a request that ended)."""
    acting = _CURRENT.get()
    return acting.device if acting is not None and acting.open else None


@contextmanager
def acting(device: DeviceRef) -> Iterator[None]:
    """Attribute what runs inside (and only until it ends) to ``device``."""
    state = _Acting(device)
    token = _CURRENT.set(state)
    try:
        yield
    finally:
        state.open = False  # tasks the request started keep a copy of the context: close it for them too
        _CURRENT.reset(token)


def attribute(message: str, data: Mapping[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """An activity entry's message and data, attributed to the phone whose request writes it."""
    payload = dict(data or {})
    device = current()
    if device is None:
        return message, payload
    payload.setdefault("device", device.id)
    if payload.get("source") == "phone":  # "Added “…” from your phone" says so already
        return message, payload
    return f"{message} (on {device.name})", payload
