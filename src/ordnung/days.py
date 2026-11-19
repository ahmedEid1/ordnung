"""The person's today, and the day and timestamp parsers the read models share.

:func:`local_today` is today in the person's time zone, or the pinned demo/test date
(:func:`simulated_day`). :func:`parse_day` reads a day off a stored value as it is, without stripping it;
:func:`ordnung.rules.deadlines.parse_date` strips surrounding spaces first.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ordnung import clock

if TYPE_CHECKING:
    from ordnung.db.store import Store

log = logging.getLogger(__name__)

SIMULATED_TODAY_KEY = "simulated_today"


def parse_day(value: str | None) -> date | None:
    """``YYYY-MM-DD`` (or an ISO timestamp) → date; ``None`` for missing or malformed values."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_timestamp(value: str | None) -> datetime | None:
    """ISO-8601 timestamp (``Z`` allowed) → aware datetime; ``None`` for missing or malformed values."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def simulated_day(store: Store) -> date | None:
    """The pinned demo/test date, if any: ``clock`` override, then settings, then meta."""
    if clock.simulated():
        return clock.today()
    configured = store.get_settings().simulated_today
    return parse_day(configured) or parse_day(store.get_meta(SIMULATED_TODAY_KEY))


def local_today(store: Store) -> date:
    """Today in the person's time zone (``profile.timezone``), honouring a simulated date."""
    pinned = simulated_day(store)
    if pinned is not None:
        return pinned
    try:
        zone = ZoneInfo(store.get_profile().timezone)
    except (ZoneInfoNotFoundError, ValueError):
        log.warning("unknown time zone in the profile; using the system date")
        return clock.today()
    return datetime.now(zone).date()
