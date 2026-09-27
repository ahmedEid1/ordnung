"""The FastAPI application (SPEC §13): the API under ``/api``, the built web app with a strict Content
Security Policy, the localhost security middleware and a lifespan that runs the background work.

``create_app(ctx, token=…, demo=…)`` wires one :class:`~ordnung.app_context.AppContext` into an app:

* **lifespan** — binds the event bus to the server loop, starts the ingest worker, the daily tick and
  the watched folder (when one is set, :mod:`ordnung.ingest.watcher`), and on shutdown stops them (and
  the API's own background tasks). The context itself stays open; whoever built it closes it.
* **errors** — model failures become ``503`` with a message the person can act on (and a ``code``),
  invalid input ``422``, unknown records ``404``.
* **web app** — files of ``config.web_dist_dir()`` are served as they are; a missing file (under
  ``assets/`` or with an extension) is a ``404``; any other non-API path gets ``index.html``
  (client-side routing) with the CSP, whose ``script-src`` allows exactly the inline theme script of
  the built ``index.html`` by hash. Without a build a friendly page explains how to get it.
* **OpenAPI** at ``/api/openapi.json`` lists every view model, the ``StreamEvent`` of ``/api/ask`` and
  ``ServerEvents`` (the payload of each live event of ``/api/events``, by event name). No interactive
  docs page is served (it would load scripts from a CDN). :func:`openapi_json` is what
  ``ordnung openapi`` prints; the web app's ``openapi.json`` and generated types come from it (a test
  fails when they are stale).
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ValidationError
from pydantic.json_schema import models_json_schema

from ordnung import __version__, models
from ordnung.api.deps import ApiState
from ordnung.api.routes import ROUTERS
from ordnung.api.routes.ask import StreamEvent
from ordnung.api.routes.demo import optional_demo_function
from ordnung.api.security import (
    API_PREFIX,
    SecurityMiddleware,
    content_security_policy,
    html_page,
    inline_script_hashes,
)
from ordnung.app_context import AppContext
from ordnung.config import web_dist_dir
from ordnung.db.store import NotFoundError
from ordnung.doctor import web_app_fix
from ordnung.drafts.compose import DraftError
from ordnung.ingest.intake import IntakeError
from ordnung.ingest.worker import pause_until
from ordnung.llm.base import (
    ClaudeAuthError,
    ClaudeBadOutput,
    ClaudeNotInstalled,
    ClaudeRateLimited,
    ClaudeTimeout,
    LLMError,
    ReplayMiss,
)
from ordnung.tick import DailyTick

log = logging.getLogger(__name__)

ASSET_CACHE = "public, max-age=31536000, immutable"
PAGE_HEADERS = {"Cross-Origin-Opener-Policy": "same-origin", "X-Frame-Options": "DENY"}
LLM_ERROR_CODES: tuple[tuple[type[LLMError], str], ...] = (
    (ClaudeNotInstalled, "claude_not_installed"),
    (ClaudeAuthError, "claude_auth"),
    (ClaudeRateLimited, "llm_paused"),
    (ClaudeTimeout, "llm_timeout"),
    (ClaudeBadOutput, "llm_bad_output"),
    (ReplayMiss, "replay_miss"),
)
LLM_FALLBACK_MESSAGE = "Claude couldn't answer right now. Please try again in a moment."
VIEW_MODELS: tuple[type[BaseModel], ...] = (
    models.RefLink,
    models.TimelineEntry,
    models.AreaStatus,
    models.MoneySummary,
    models.DashboardStats,
    models.Dashboard,
    models.PageInfo,
    models.DocumentDetail,
    models.PartyDetail,
    models.CaseDetail,
    models.UsageStats,
    models.ClaudeStatus,
    models.Health,
    models.RuleInfo,
    models.TimelineMarker,
    models.LaneBar,
    models.Lane,
    models.SearchHit,
    models.TourState,
    models.MailTrayItem,
    models.EmailAttachment,
    models.FolderPickup,
    models.FolderStatus,
    models.DoctorCheck,
    StreamEvent,
    models.ServerEvents,
)


# --------------------------------------------------------------------------------------------------
# lifespan
# --------------------------------------------------------------------------------------------------


def _lifespan(state: ApiState) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        ctx = state.ctx
        ctx.bus.bind_loop(asyncio.get_running_loop())
        tick = DailyTick(ctx)
        await ctx.worker.start()
        tick.start()
        await state.folder.start()
        try:
            yield
        finally:
            await state.folder.stop()
            await tick.stop()
            await state.background.stop()
            await ctx.worker.stop()

    return lifespan


# --------------------------------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------------------------------


def llm_error_code(exc: LLMError) -> str:
    """A machine-readable code for a model failure (``claude_auth``, ``llm_paused`` …)."""
    return next((code for kind, code in LLM_ERROR_CODES if isinstance(exc, kind)), "llm_error")


def llm_error_message(exc: Exception, *, demo: bool) -> str:
    """What to tell the person about a failed model call (kinder wording in the demo)."""
    friendly = optional_demo_function("friendly_llm_error") if demo else None
    if friendly is not None and isinstance(exc, LLMError):
        return str(friendly(exc, demo=True))
    return str(exc) or LLM_FALLBACK_MESSAGE


def retry_after_seconds(exc: ClaudeRateLimited) -> int:
    """Seconds until Claude's usage limit resets (its hint, else the worker's default pause)."""
    now = datetime.now(UTC)
    return max(1, int((pause_until(exc.reset_at, now) - now).total_seconds()))


async def _llm_error(request: Request, exc: Exception) -> Response:
    headers = {"Retry-After": str(retry_after_seconds(exc))} if isinstance(exc, ClaudeRateLimited) else None
    code = llm_error_code(exc) if isinstance(exc, LLMError) else "llm_error"
    state: ApiState = request.app.state.ordnung
    body = {"detail": llm_error_message(exc, demo=state.demo), "code": code}
    return JSONResponse(body, status_code=503, headers=headers)


async def _not_found(_request: Request, _exc: Exception) -> Response:
    return JSONResponse({"detail": "This record doesn't exist (any more)."}, status_code=404)


async def _unprocessable(_request: Request, exc: Exception) -> Response:
    if isinstance(exc, ValidationError):
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        return JSONResponse({"detail": errors}, status_code=422)
    return JSONResponse({"detail": str(exc)}, status_code=422)


def _add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(LLMError, _llm_error)
    app.add_exception_handler(NotFoundError, _not_found)
    for kind in (IntakeError, DraftError, ValidationError):
        app.add_exception_handler(kind, _unprocessable)


# --------------------------------------------------------------------------------------------------
# web app
# --------------------------------------------------------------------------------------------------


def _static_file(dist: Path, path: str) -> Path | None:
    """A file of the built web app for ``path`` (never outside ``dist``)."""
    if not path:
        return None
    candidate = (dist / path).resolve()
    root = dist.resolve()
    return candidate if candidate.is_relative_to(root) and candidate.is_file() else None


def _not_built(dist: Path) -> Response:
    return html_page(
        "Ordnung's web app is missing",
        [
            "The API is running, but the web pages are missing from this installation.",
            f"{web_app_fix(dist)} Then restart Ordnung and reload this page.",
        ],
        status_code=503,
    )


def _mount_web_app(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"
    hashes = inline_script_hashes(index.read_text(encoding="utf-8")) if index.is_file() else []
    page_headers = {**PAGE_HEADERS, "Content-Security-Policy": content_security_policy(hashes)}

    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def web_app(path: str) -> Response:
        if f"/{path}" == API_PREFIX or f"/{path}".startswith(API_PREFIX + "/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if not index.is_file():
            return _not_built(dist)
        found = _static_file(dist, path)
        if found is not None and found != index.resolve():
            cache = ASSET_CACHE if path.startswith("assets/") else "no-cache"
            return FileResponse(found, headers={"Cache-Control": cache})
        if found is None and (path.startswith("assets/") or PurePosixPath(path).suffix):
            # a file this build doesn't have (a tab left open across an upgrade asks for the old
            # version's page chunks): index.html would fail as a script with a MIME type error
            return Response("Not Found", status_code=404, media_type="text/plain")
        return FileResponse(
            index, media_type="text/html", headers={**page_headers, "Cache-Control": "no-cache"}
        )


# --------------------------------------------------------------------------------------------------
# OpenAPI
# --------------------------------------------------------------------------------------------------


_REF_PREFIX = "#/components/schemas/"


def _output_refs(value: Any, components: dict[str, Any]) -> Any:
    """``value`` with references to models FastAPI split into ``X-Input``/``X-Output`` pointing at
    ``X-Output`` (view models are response shapes)."""
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
            name = ref.removeprefix(_REF_PREFIX)
            if name not in components and f"{name}-Output" in components:
                return {**value, "$ref": f"{_REF_PREFIX}{name}-Output"}
        return {key: _output_refs(item, components) for key, item in value.items()}
    if isinstance(value, list):
        return [_output_refs(item, components) for item in value]
    return value


def _add_view_models(schema: dict[str, Any]) -> None:
    """Make every view model (and Ask's ``StreamEvent``) a named component."""
    _, extra = models_json_schema(
        [(model, "serialization") for model in VIEW_MODELS], ref_template=_REF_PREFIX + "{model}"
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for name, definition in extra.get("$defs", {}).items():
        if name in components or f"{name}-Output" in components:
            continue
        components[name] = _output_refs(definition, components)


def _tidy_event_streams(schema: dict[str, Any]) -> None:
    """``text/event-stream`` responses that name their event model reference just that model."""
    for operations in schema.get("paths", {}).values():
        for operation in operations.values():
            for response in operation.get("responses", {}).values():
                stream = response.get("content", {}).get("text/event-stream", {})
                if "$ref" in stream.get("schema", {}):
                    stream["schema"] = {"$ref": stream["schema"]["$ref"]}


def _openapi(app: FastAPI) -> Callable[[], dict[str, Any]]:
    def build() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title, version=app.version, description=app.description, routes=app.routes
            )
            _add_view_models(schema)
            _tidy_event_streams(schema)
            app.openapi_schema = schema
        return app.openapi_schema

    return build


def openapi_schema() -> dict[str, Any]:
    """The API's OpenAPI schema, built on a throw-away data folder (no model is ever called)."""
    from ordnung.app_context import build_context
    from ordnung.llm.fake import FakeBackend

    with tempfile.TemporaryDirectory(prefix="ordnung-openapi-") as tmp:
        context = build_context(tmp, backend_obj=FakeBackend())
        try:
            return create_app(context, token=None, demo=False).openapi()
        finally:
            context.close()


def openapi_json(schema: dict[str, Any] | None = None) -> str:
    """The schema as ``ordnung openapi`` prints it (and ``web/openapi.json`` stores it)."""
    return json.dumps(schema if schema is not None else openapi_schema(), indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------------------------------
# the app
# --------------------------------------------------------------------------------------------------


def create_app(ctx: AppContext, *, token: str | None, demo: bool = False) -> FastAPI:
    """The Ordnung web server for ``ctx``: API, web app, security and background work.

    ``token`` is the session token (``None`` turns the token check off — tests and ``--no-token``);
    ``demo`` enables the guided tour and the New-mail tray.
    """
    state = ApiState(ctx=ctx, demo=demo, token=token)
    app = FastAPI(
        title="Ordnung",
        version=__version__,
        description="Local API of Ordnung, the private AI secretary for life admin.",
        lifespan=_lifespan(state),
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=None,
        redoc_url=None,
    )
    app.state.ordnung = state
    api = APIRouter(prefix=API_PREFIX)
    for router in ROUTERS:
        api.include_router(router)
    app.include_router(api)
    _add_error_handlers(app)
    _mount_web_app(app, web_dist_dir())
    app.openapi = _openapi(app)  # type: ignore[method-assign]
    app.add_middleware(SecurityMiddleware, token=token)
    return app
