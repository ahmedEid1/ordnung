"""Time source for the whole app.

Everything that needs "today" goes through here so demo mode (and tests) can pin the date with
``ORDNUNG_TODAY=YYYY-MM-DD`` or :func:`set_today`.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

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


def stamp_simulated_day(enabled: bool) -> None:
    """Demo mode: date new records on the simulated day (keeping the real time of day).

    Without it a letter read in the demo would say "Read on 25 Sep" while the app says today is
    Mon 28 Sep. Only the demo turns this on (see ``app_context.apply_simulated_today``).
    """
    global _stamp_simulated_day
    _stamp_simulated_day = enabled


def real_now_iso() -> str:
    """The real UTC time, for machine deadlines (job back-off, server start) — never simulated."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    """UTC timestamp for created_at/updated_at columns: real time, except that in the demo the date
    is the simulated day (:func:`stamp_simulated_day`)."""
    now = datetime.now(UTC)
    if _stamp_simulated_day and simulated():
        day = today()
        now = datetime.combine(day, now.timetz())
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")
