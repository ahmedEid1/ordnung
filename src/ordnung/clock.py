"""Time source for the whole app.

Everything that needs "today" goes through here so demo mode (and tests) can pin the date with
``ORDNUNG_TODAY=YYYY-MM-DD`` or :func:`set_today`.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_override: date | None = None


def set_today(value: date | str | None) -> None:
    """Pin (or unpin with ``None``) the simulated current date."""
    global _override
    _override = date.fromisoformat(value) if isinstance(value, str) else value


def simulated() -> bool:
    return _override is not None or bool(os.environ.get("ORDNUNG_TODAY"))


def today() -> date:
    if _override is not None:
        return _override
    env = os.environ.get("ORDNUNG_TODAY")
    if env:
        return date.fromisoformat(env)
    return date.today()


_stamp_simulated_day = False
_stamp_zone: str | None = None


def stamp_simulated_day(enabled: bool, zone: str | None = None) -> None:
    """Demo mode: date new records on the simulated day (keeping the real time of day).

    Without it a letter read in the demo would say "Read on 25 Sep" while the app says today is
    Mon 28 Sep. Only the demo turns this on (see ``app_context.apply_simulated_today``). ``zone`` is
    the person's time zone: the simulated day is theirs, so a record stamped at 23:30 UTC — already
    the next day in Berlin — still falls on it there (it was stamped on the next local day).
    """
    global _stamp_simulated_day, _stamp_zone
    _stamp_simulated_day = enabled
    _stamp_zone = zone


def real_now_iso() -> str:
    """The real UTC time, for machine deadlines (job back-off, server start) — never simulated."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    """UTC timestamp for created_at/updated_at columns: real time, except that in the demo the date
    is the simulated day (:func:`stamp_simulated_day`)."""
    now = datetime.now(UTC)
    if _stamp_simulated_day and simulated():
        try:
            zone = ZoneInfo(_stamp_zone) if _stamp_zone else UTC
        except (ZoneInfoNotFoundError, ValueError):
            zone = UTC
        local = now.astimezone(zone)
        now = datetime.combine(today(), local.time(), tzinfo=zone).astimezone(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")
