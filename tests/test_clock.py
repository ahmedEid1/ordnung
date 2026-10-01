"""The demo's clock: records are stamped on the simulated day in the person's time zone."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from ordnung import clock


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    yield
    clock.set_today(None)
    clock.stamp_simulated_day(False)


class _Frozen(datetime):
    """``datetime.now`` frozen at 30 Sep 2026, 22:44 UTC — already 1 Oct, 00:44, in Berlin."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[no-untyped-def,override]
        moment = datetime(2026, 9, 30, 22, 44, 5, tzinfo=UTC)
        return moment if tz is None else moment.astimezone(tz)


def test_a_late_evening_stamp_stays_on_the_simulated_day_in_the_persons_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Built at 22:44 UTC, the demo's brief said "Written Tue 29 Sep, 00:44" on its Mon 28 Sep: the stamp
    combined the simulated date with the UTC time of day, which is the next day in Berlin."""
    monkeypatch.setattr(clock, "datetime", _Frozen)
    clock.set_today("2026-09-28")
    clock.stamp_simulated_day(True, "Europe/Berlin")
    stamp = clock.now_iso()
    local = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Berlin"))
    assert (local.date().isoformat(), local.strftime("%H:%M")) == ("2026-09-28", "00:44")
    assert stamp == "2026-09-27T22:44:05Z"


def test_without_a_zone_or_with_an_unknown_one_the_day_is_utcs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "datetime", _Frozen)
    clock.set_today("2026-09-28")
    for zone in (None, "Not/AZone"):
        clock.stamp_simulated_day(True, zone)
        assert clock.now_iso() == "2026-09-28T22:44:05Z"


def test_outside_the_demo_the_stamp_is_the_real_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "datetime", _Frozen)
    clock.set_today("2026-09-28")
    clock.stamp_simulated_day(False, "Europe/Berlin")
    assert clock.now_iso() == "2026-09-30T22:44:05Z"
