"""An unexpected error in a route: a JSON 500 the web app can word plainly (UX audit U9), never the plain-text
"Internal Server Error" that became a toast's sentence, and never the error's message, which may quote a letter.
Input at the edges (a date on the calendar's last day, an offset or page number far out of range, a time zone that is
none, a repeat interval out of range) gets a clear answer instead of a 500."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ordnung.api.app import UNEXPECTED_MESSAGE
from ordnung.api.routes.items import REPEAT_INTERVAL_MESSAGE
from ordnung.calendar.ics import TOO_FAR_AHEAD
from ordnung.ingest.worker import DEFAULT_PAUSE
from ordnung.llm.base import ClaudeRateLimited
from test_api_support import BASE_URL, CLIENT_HEADERS, api_for


async def test_an_unexpected_error_is_a_json_500_with_a_plain_sentence(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with api_for(data_dir) as api:

        def broken(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("Mietvertrag Musterstraße 1, Kaltmiete 650 EUR")

        monkeypatch.setattr(api.ctx.store, "list_items", broken)
        # as the server runs it: the error is answered, not raised into the caller
        transport = httpx.ASGITransport(app=api.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(
            transport=transport, base_url=BASE_URL, headers=CLIENT_HEADERS
        ) as client:
            response = await client.get("/api/items")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "detail": UNEXPECTED_MESSAGE,
        "code": "internal_error",
        "error": "RuntimeError",
    }
    assert "Mietvertrag" not in response.text


async def test_known_errors_keep_their_own_answers(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        missing = await api.client.get("/api/items/itm_nope")
        refused = await api.client.post("/api/items", json={"kind": "reminder", "title": ""})
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Unknown to-do."}
    assert refused.status_code == 422
    assert "code" not in refused.json()


@pytest.mark.parametrize("due_time", [None, "23:50"])
async def test_a_date_on_the_calendars_last_day_leaves_the_calendar_working(
    data_dir: Path, due_time: str | None
) -> None:
    """A to-do on 31 Dec 9999 (a misread year, a typo): all day it ends the day after, at 23:50 an hour later, past
    the last day a calendar holds. It is left out of the calendar file and of calendar sync's preview, which answer
    as before, and its own calendar file is refused with a plain sentence."""
    async with api_for(data_dir) as api:
        body = {"kind": "deadline", "title": "Kept", "due_date": "2026-10-19"}
        kept = await api.client.post("/api/items", json=body)
        far = await api.client.post(
            "/api/items", json={**body, "title": "Far", "due_date": "9999-12-31", "due_time": due_time}
        )
        assert kept.status_code == far.status_code == 201
        feed = await api.client.get("/api/calendar.ics")
        preview = await api.client.get("/api/calendar/sync/preview")
        single = await api.client.get(f"/api/items/{far.json()['id']}.ics")
    assert feed.status_code == 200
    assert f"{kept.json()['id']}@ordnung.local" in feed.text and far.json()["id"] not in feed.text
    assert preview.status_code == 200 and len(preview.json()["events"]) == 1
    assert single.status_code == 422
    assert single.json() == {"detail": TOO_FAR_AHEAD}


@pytest.mark.parametrize(
    "path",
    [
        "/api/documents?offset=100000000000000000000",
        "/api/documents?offset=1000001",
        "/api/documents/doc_x/pages/100000000000000000000.jpg",
        "/api/documents/doc_x/pages/10001.jpg",
    ],
)
async def test_an_offset_or_page_number_out_of_range_is_a_422(data_dir: Path, path: str) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.get(path)
    assert response.status_code == 422, response.text


async def test_a_page_number_below_one_is_no_page(data_dir: Path) -> None:
    async with api_for(data_dir) as api:
        for page in ("0", "-1", "-100000000000000000000"):
            response = await api.client.get(f"/api/documents/doc_x/pages/{page}.jpg")
            assert response.status_code == 404, page
            assert response.json() == {"detail": "This page doesn't exist."}


@pytest.mark.parametrize("zone", ["Europe", "x" * 300, "Europe/", "Mars/Olympus"])
async def test_a_time_zone_that_is_none_is_a_422(data_dir: Path, zone: str) -> None:
    async with api_for(data_dir) as api:
        response = await api.client.put("/api/profile", json={"timezone": zone})
        kept = (await api.client.get("/api/profile")).json()["timezone"]
    assert response.status_code == 422, response.text
    assert "is not a known time zone (e.g. Europe/Berlin)." in response.text
    assert kept != zone


@pytest.mark.parametrize(
    "recurrence",
    [
        {"interval": 1_000_000_000, "unit": "years"},
        {"interval": 121, "unit": "days"},
        {"interval": 0, "unit": "months"},
    ],
)
async def test_a_repeat_interval_out_of_range_is_a_422(data_dir: Path, recurrence: dict[str, object]) -> None:
    """Every 1 to 120 days, weeks, months or years, checked where a to-do is added or changed by hand; the rule a
    letter is read with stays as it is."""
    async with api_for(data_dir) as api:
        body = {"kind": "reminder", "title": "UStVA", "due_date": "2026-10-10"}
        created = await api.client.post("/api/items", json={**body, "recurrence": recurrence})
        item = await api.client.post(
            "/api/items", json={**body, "recurrence": {"interval": 120, "unit": "years"}}
        )
        assert item.status_code == 201, item.text
        patched = await api.client.patch(f"/api/items/{item.json()['id']}", json={"recurrence": recurrence})
        stored = (await api.client.get(f"/api/items/{item.json()['id']}")).json()
    assert created.status_code == patched.status_code == 422
    assert REPEAT_INTERVAL_MESSAGE in created.text and REPEAT_INTERVAL_MESSAGE in patched.text
    assert stored["recurrence"]["interval"] == 120


async def test_a_usage_limit_hint_with_no_real_time_zone_waits_the_usual_pause(data_dir: Path) -> None:
    """Claude's hint "3pm (Europe)" names no time zone: the 503 still answers, after the usual pause."""
    async with api_for(data_dir) as api:

        async def limited() -> None:
            raise ClaudeRateLimited("Usage limit reached", reset_at="3pm (Europe)")

        api.app.add_api_route("/api/test-limited", limited, methods=["GET"])
        api.app.router.routes.insert(0, api.app.router.routes.pop())  # before the web app's catch-all
        response = await api.client.get("/api/test-limited")
    assert response.status_code == 503
    assert response.json()["code"] == "llm_paused"
    assert int(response.headers["retry-after"]) == int(DEFAULT_PAUSE.total_seconds())
