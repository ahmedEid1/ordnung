"""Shared helpers for the HTTP API tests (no tests here): an app on a throw-away data directory with
the FakeBackend, an httpx client over ASGITransport, a fake built web app and one more canned letter
whose deadline counts from the day it arrived."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

from fixtures_llm import ALL_LETTERS, Letter, Router
from ordnung.api.app import create_app
from ordnung.app_context import AppContext, build_context
from ordnung.llm.base import LLMRequest
from ordnung.llm.fake import FakeBackend

BASE_URL = "http://127.0.0.1:8765"
CLIENT_HEADERS = {"X-Ordnung-Client": "test"}
TODAY = "2026-09-25"
THEME_SCRIPT = '\n      document.documentElement.classList.add("dark");\n    '
INDEX_HTML = (
    "<!doctype html><html><head><title>Ordnung</title>"
    f"<script>{THEME_SCRIPT}</script>"
    '<script type="module" crossorigin src="/assets/index-abc.js"></script>'
    '</head><body><div id="root"></div></body></html>'
)

FINE_QUOTE = (
    "Bitte zahlen Sie das Verwarnungsgeld von 20,00 EUR innerhalb einer Woche nach Zugang dieses Schreibens."
)
FINE_LETTER = Letter(
    marker="Verwarnungsgeld",
    pages=(
        (
            "Stadt Musterstadt - Ordnungsamt",
            "SPECIMEN",
            "Musterstadt, 14.09.2026",
            "Verwarnungsgeld wegen Parkens im Halteverbot",
            FINE_QUOTE,
        ),
    ),
    payload={
        "kind": "fine",
        "area": "mobility",
        "title": "Parking fine",
        "sender": {"name": "Stadt Musterstadt - Ordnungsamt", "kind": "authority"},
        "document_date": "2026-09-14",
        "summary": "You were fined 20 EUR for parking.",
        "explanation": "Pay within a week of receiving the letter.",
        "items": [
            {
                "kind": "payment",
                "title": "Pay the parking fine",
                "date": {
                    "type": "relative",
                    "amount": 1,
                    "unit": "weeks",
                    "anchor": "receipt",
                    "nature": "payment",
                    "text": "innerhalb einer Woche nach Zugang",
                },
                "amount": 20.0,
                "currency": "EUR",
                "direction": "out",
                "quote": FINE_QUOTE,
            }
        ],
        "case_title": "Parking fine",
    },
)

DRAFT_ANSWER: dict[str, Any] = {
    "subject": "ignored",
    "body": "Sehr geehrte Damen und Herren,\n\nvielen Dank.\n\nMit freundlichen Grüßen",
    "body_translation": "Dear Sir or Madam,\n\nthank you.\n\nKind regards",
    "enclosures": [],
    "notes_for_user": ["Keep a copy of the letter."],
}
ASK_ANSWER = "Your letters are all filed and nothing needs you right now."


class ApiRouter(Router):
    """The canned letters plus answers for the other purposes the API triggers."""

    def __init__(self) -> None:
        super().__init__(letters=(*ALL_LETTERS, FINE_LETTER))
        self.answers: dict[str, Any] = {
            "brief": {"text": "Good morning. Nothing urgent today."},
            "review": {"suggestions": []},
            "draft": DRAFT_ANSWER,
            "ask": ASK_ANSWER,
        }

    def __call__(self, req: LLMRequest) -> Any:
        if req.purpose not in self.errors and req.purpose in self.answers:
            return copy.deepcopy(self.answers[req.purpose])
        return super().__call__(req)


@dataclass
class Api:
    """A test app: its context, the FastAPI app and a client."""

    ctx: AppContext
    app: FastAPI
    client: httpx.AsyncClient

    @property
    def backend(self) -> FakeBackend:
        backend = self.ctx.llm.backend
        assert isinstance(backend, FakeBackend)
        return backend

    async def upload(self, *files: tuple[str, bytes], combine: bool = False, private: bool = False) -> Any:
        """``POST /api/documents`` and return the JSON body (asserting 201)."""
        response = await self.client.post(
            "/api/documents",
            files=[("files", (name, data)) for name, data in files],
            data={"combine": str(combine).lower(), "private": str(private).lower()},
        )
        assert response.status_code == 201, response.text
        return response.json()

    async def read_all(self) -> int:
        """Let the ingest worker read every queued letter."""
        return await self.ctx.worker.run_until_idle()


def client_for(app: FastAPI, **headers: str) -> httpx.AsyncClient:
    """An httpx client talking to ``app`` in-process (Host 127.0.0.1:8765)."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE_URL, headers={**CLIENT_HEADERS, **headers}
    )


@asynccontextmanager
async def api_for(
    data_dir: Path, *, token: str | None = None, demo: bool = False, router: Router | None = None
) -> AsyncIterator[Api]:
    """An :class:`Api` without the lifespan (tests drive the worker themselves)."""
    ctx = build_context(data_dir, backend_obj=FakeBackend(router or ApiRouter()))
    app = create_app(ctx, token=token, demo=demo)
    try:
        async with client_for(app) as client:
            yield Api(ctx=ctx, app=app, client=client)
    finally:
        ctx.close()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the app's startup/shutdown around a block (ASGITransport doesn't send lifespan events)."""
    async with app.router.lifespan_context(app):
        yield


def fake_web_dist(root: Path) -> Path:
    """A minimal built web app: ``index.html`` with an inline theme script and one asset."""
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (dist / "assets" / "index-abc.js").write_text("console.log('ordnung');", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>", encoding="utf-8")
    return dist


def sse_messages(body: str) -> list[dict[str, str]]:
    """Parse an SSE body into ``{"event", "data"}`` dicts (comments skipped, data lines joined)."""
    messages = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        event, data = "message", []
        for line in block.split("\n"):
            if line.startswith(":") or not line:
                continue
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
        if data:
            messages.append({"event": event, "data": "\n".join(data)})
    return messages
