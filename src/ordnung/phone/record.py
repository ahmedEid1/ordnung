"""Phone access's saved state: one JSON record in the meta key :data:`META_KEY` (policy:
:mod:`ordnung.phone`).

It holds whether phone access is on, the address, network and port it listens on, the router it was
turned on behind, and the paired phones — their names and a SHA-256 of each sign-in, never a sign-in
itself. The pairing code, notices and who is connected right now live in memory only. Backups leave the
record out (``backup.archive``), a restored copy starts without it (``backup.restore``) and Delete
everything drops it with the rest of the database. An unreadable record loads as the defaults (off, no
phones), with a warning in the log; :class:`~ordnung.phone.access.PhoneAccess` is its only writer.
"""

from __future__ import annotations

import logging

from pydantic import Field, ValidationError

from ordnung.db.store import Store
from ordnung.models import _Model

log = logging.getLogger("ordnung.phone")

META_KEY = "phone_access"
DEFAULT_PORT = 8767
#: How many earlier sign-ins of a phone are remembered: one of them coming back means it was copied.
RETIRED_KEPT = 8


class PhoneDeviceRecord(_Model):
    """A paired phone as saved: never its sign-in, only hashes of it."""

    id: str
    name: str
    platform: str = ""
    token_sha256: str = Field(description="SHA-256 (hex) of the phone's current sign-in")
    previous_sha256: str | None = Field(
        default=None, description="The sign-in it had before the last change (valid a little longer)"
    )
    rotated_at: str | None = Field(default=None, description="When its sign-in last changed")
    confirmed_at: str | None = Field(
        default=None, description="When the phone first used its current sign-in (none: not yet)"
    )
    retired: list[str] = Field(default_factory=list, description="Hashes of its earlier sign-ins")
    paired_at: str
    last_seen_at: str | None = None
    last_address: str | None = None


class PhoneRecord(_Model):
    """Phone access as saved."""

    enabled: bool = False
    address: str | None = None
    interface: str | None = None
    subnet: str | None = None
    port: int = DEFAULT_PORT
    enabled_at: str | None = None
    certificate_changed_at: str | None = None
    gateway: str | None = Field(default=None, description="The router's address and hardware address")
    check_key: str = Field(default="", description="The key the two check words are derived with")
    devices: list[PhoneDeviceRecord] = Field(default_factory=list)


def load_record(store: Store) -> PhoneRecord:
    """The saved record (the defaults when there is none or it can't be read)."""
    raw = store.get_meta(META_KEY)
    if raw is None:
        return PhoneRecord()
    try:
        return PhoneRecord.model_validate_json(raw)
    except (ValidationError, ValueError):
        log.warning("phone access: its saved record couldn't be read, so it starts off")
        return PhoneRecord()


def save_record(store: Store, record: PhoneRecord) -> None:
    """Save ``record`` (one write)."""
    with store.tx():
        store.set_meta(META_KEY, record.model_dump_json())
