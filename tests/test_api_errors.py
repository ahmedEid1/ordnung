"""An unexpected error in a route: a JSON 500 the web app can word plainly (UX audit U9), never the plain-text
"Internal Server Error" that became a toast's sentence, and never the error's message, which may quote a letter."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ordnung.api.app import UNEXPECTED_MESSAGE
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
