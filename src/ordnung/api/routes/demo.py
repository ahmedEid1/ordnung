"""Demo mode only: the guided tour's state and the "New mail" tray (SPEC §16).

The work is done by the demo package; this module only needs these functions, looked up in
``ordnung.demo.tour`` (then ``ordnung.demo.tray``) — each may be sync or async:

* ``get_tour(store) -> TourState``
* ``update_tour(store, **changes) -> TourState`` (``changes`` ⊆ {active, step, completed})
* ``list_mail(ctx) -> list[MailTrayItem]``
* ``open_mail(ctx, mail_id) -> tuple[Document, Job]`` — ingests a tray letter; ``KeyError`` for an
  unknown id.
* ``suggested_questions() -> list[str]`` — the Ask chips (the recorded questions).

Optional, used in demo mode when present: ``demo_safe_stream(events, demo=True)`` (a friendly event
instead of a missing recording in Ask), ``paced_replay(events)`` (a recorded answer streamed at a
reading pace) and ``friendly_llm_error(exc, demo=True) -> str``.

Without the demo package the endpoints answer 503; outside demo mode they do not exist (404).
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ordnung.api.deps import ApiState, get_state
from ordnung.models import Document, Job, MailTrayItem, TourState

router = APIRouter(prefix="/demo", tags=["demo"])

DEMO_MODULES = ("ordnung.demo.tour", "ordnung.demo.tray")
UNAVAILABLE = "The guided demo isn't available in this installation."


def demo_state(state: Annotated[ApiState, Depends(get_state)]) -> ApiState:
    """The API state, only when the server runs in demo mode (else 404)."""
    if not state.demo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This is only available in the demo.")
    return state


DemoDep = Annotated[ApiState, Depends(demo_state)]


class TourPatch(BaseModel):
    """Progress through the guided tour."""

    model_config = ConfigDict(extra="forbid")

    active: bool | None = None
    step: int | None = Field(default=None, ge=0, le=20)
    completed: bool | None = None


class MailOpenRequest(BaseModel):
    """Which tray letter to open."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)


class MailOpenResult(BaseModel):
    """The letter being read live and its job."""

    document: Document
    job: Job


def _missing(exc: ModuleNotFoundError, module_name: str) -> bool:
    """Whether ``exc`` means ``module_name`` (or a package containing it) is not installed."""
    return exc.name is not None and (module_name == exc.name or module_name.startswith(f"{exc.name}."))


def optional_demo_function(name: str) -> Callable[..., Any] | None:
    """A function of the demo package, or ``None`` when the package or the function is missing."""
    for module_name in DEMO_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if not _missing(exc, module_name):
                raise
            continue
        function = getattr(module, name, None)
        if callable(function):
            return function
    return None


def demo_function(name: str) -> Callable[..., Any]:
    """A function of the demo package (503 when the package or the function is missing)."""
    function = optional_demo_function(name)
    if function is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, UNAVAILABLE)
    return function


async def _call(name: str, *args: Any, **kwargs: Any) -> Any:
    result = demo_function(name)(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


@router.get("/tour", response_model=TourState)
async def read_tour(state: DemoDep) -> TourState:
    """Where the person is in the guided tour."""
    return TourState.model_validate(await _call("get_tour", state.ctx.store))


@router.patch("/tour", response_model=TourState)
async def update_tour(patch: TourPatch, state: DemoDep) -> TourState:
    """Move through, skip or finish the tour."""
    changes = {
        name: value for name, value in patch.model_dump(exclude_unset=True).items() if value is not None
    }
    return TourState.model_validate(await _call("update_tour", state.ctx.store, **changes))


@router.get("/questions", response_model=list[str])
async def suggested_questions(state: DemoDep) -> list[str]:
    """The Ask page's suggested questions — word for word the ones the demo has recorded answers for."""
    return [str(question) for question in await _call("suggested_questions")]


@router.get("/mail", response_model=list[MailTrayItem])
async def mail_tray(state: DemoDep) -> list[MailTrayItem]:
    """The letters waiting in the "New mail" tray."""
    return [MailTrayItem.model_validate(entry) for entry in await _call("list_mail", state.ctx)]


@router.post("/mail", response_model=MailOpenResult)
async def open_mail(body: MailOpenRequest, state: DemoDep) -> MailOpenResult:
    """Open a tray letter: it is read live (replayed answers) with the usual progress events."""
    try:
        document, job = await _call("open_mail", state.ctx, body.id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That letter is no longer in the tray.") from exc
    return MailOpenResult(document=document, job=job)
