"""The running demo: the *New mail* tray, the guided tour and friendly replay misses (SPEC §14.10, §16).

* The tray holds the manifest's tray letters. :func:`open_tray_item` reads one live through the real
  pipeline on the replay backend, pacing every stage (≥ 600 ms in demo mode) so the stepper is
  visible, then runs the triggers — which is how a new Idea arrives over SSE. It is split into
  :func:`start_tray_item` (fast) and :func:`finish_tray_item`; :func:`open_mail` answers the API
  right after the first and reads the letter in a background task.
* ``get_tour``/``update_tour``/``list_mail``/``open_mail`` are the functions ``/api/demo`` calls.
* Which letters were opened (meta ``demo_tray``) and the tour (meta ``demo_tour``) live in the
  database, so they survive restarts and are reset with the demo.
* A question the demo has no recording for must not look like a failure: :func:`demo_safe_stream`
  turns the replay miss into one friendly error event.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ordnung.assistant.ask import DEMO_MISS as ASK_DEMO_MISS
from ordnung.config import PACKAGE_DIR
from ordnung.db.store import Store
from ordnung.demo import DemoError, Manifest, SampleDocument, load_manifest, samples_root
from ordnung.ingest.pipeline import StageCallback, add_file, ingest_document, run_triggers
from ordnung.llm.base import LLMError, ReplayMiss, StreamEvent
from ordnung.models import Document, Job, MailTrayItem, TourState

if TYPE_CHECKING:
    from ordnung.app_context import AppContext

log = logging.getLogger(__name__)

DEMO_STAGE_DELAY_S = 0.6
TRAY_META_KEY = "demo_tray"
TOUR_META_KEY = "demo_tour"
ASKS_FILE = PACKAGE_DIR / "demo" / "asks.json"
REPLAY_MISS_PREFIX = "no recorded response"
DEMO_MISS_MESSAGE = (
    "The demo uses recorded answers — install Ordnung and connect Claude to ask your own questions."
)


class TrayItemNotFound(KeyError):
    """No tray letter has this id."""


@dataclass(frozen=True)
class TrayOpening:
    """A tray letter that was added: the document and — if it still has to be read — its job."""

    item: MailTrayItem
    document: Document
    job: Job | None


# --------------------------------------------------------------------------------------------------
# suggested questions & tour state
# --------------------------------------------------------------------------------------------------


def suggested_questions(path: Path | None = None) -> list[str]:
    """The Ask page's suggested questions (``demo/asks.json``); the demo has recorded answers for them."""
    source = path or ASKS_FILE
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DemoError(f"The suggested questions ({source}) cannot be read.") from exc
    if not isinstance(raw, list) or not all(isinstance(question, str) for question in raw):
        raise DemoError(f"{source} must be a JSON list of questions.")
    return [" ".join(question.split()) for question in raw if question.strip()]


def reset_demo_state(store: Store) -> None:
    """Every tray letter unopened and the tour at its first step."""
    with store.tx():
        store.set_meta(TRAY_META_KEY, json.dumps({}))
        store.set_meta(TOUR_META_KEY, TourState(active=True).model_dump_json())


def get_tour(store: Store) -> TourState:
    """The tour state (inactive until the demo sets it)."""
    raw = store.get_meta(TOUR_META_KEY)
    return TourState.model_validate_json(raw) if raw else TourState()


def set_tour(store: Store, update: TourState | Mapping[str, Any]) -> TourState:
    """Store a tour state (a mapping updates only the fields it names) and return it."""
    changes = update.model_dump() if isinstance(update, TourState) else dict(update)
    state = TourState.model_validate(get_tour(store).model_dump() | changes)
    store.set_meta(TOUR_META_KEY, state.model_dump_json())
    return state


def update_tour(store: Store, **changes: Any) -> TourState:
    """``PATCH /api/demo/tour``: change some of ``active``, ``step``, ``completed``."""
    return set_tour(store, changes)


# --------------------------------------------------------------------------------------------------
# the tray
# --------------------------------------------------------------------------------------------------


def _opened(store: Store) -> dict[str, str]:
    raw = store.get_meta(TRAY_META_KEY)
    value = json.loads(raw) if raw else {}
    return {str(key): str(doc_id) for key, doc_id in value.items()} if isinstance(value, dict) else {}


def _mark_opened(store: Store, item_id: str, doc_id: str) -> None:
    with store.tx():
        opened = _opened(store) | {item_id: doc_id}
        store.set_meta(TRAY_META_KEY, json.dumps(opened, sort_keys=True))


def _tray_item(sample: SampleDocument, opened: Mapping[str, str]) -> MailTrayItem:
    return MailTrayItem(
        id=sample.slug,
        filename=sample.filenames[0] if sample.filenames else sample.slug,
        sender=sample.sender,
        subject=sample.subject or sample.title,
        kind_hint=sample.kind_hint,
        photo=sample.photo,
        opened=sample.slug in opened,
        doc_id=opened.get(sample.slug),
    )


def tray_items(store: Store, manifest: Manifest | None = None) -> list[MailTrayItem]:
    """The *New mail* tray with the opened flags of this demo database."""
    opened = _opened(store)
    return [_tray_item(sample, opened) for sample in (manifest or load_manifest()).tray]


def list_mail(ctx: AppContext) -> list[MailTrayItem]:
    """``GET /api/demo/mail``: the tray of the running demo."""
    return tray_items(ctx.store)


def claim_document_job(store: Store, doc_id: str) -> Job | None:
    """Take the queued job of a just-added document so that no background worker reads it too.

    Must run right after ``add_file`` returns, before the event loop can run the worker.
    """
    for job in store.list_jobs(active_only=True):
        if job.doc_id == doc_id and job.status == "queued":
            return store.update_job(job.id, status="running", attempts=job.attempts + 1)
    return None


async def add_sample(
    ctx: AppContext, sample: SampleDocument, samples: str | Path | None = None
) -> tuple[Document, Job | None]:
    """Upload a sample through the real intake (with its received date) and claim its job."""
    upload = sample.upload(samples_root(samples))
    document = await add_file(
        ctx,
        upload.data,
        upload.filename,
        combine_with=upload.combine_with or None,
        received_date=sample.received_date,
        source="demo",
    )
    return document, claim_document_job(ctx.store, document.id)


def paced(delay: float) -> StageCallback | None:
    """An ``on_stage`` hook that keeps every stage on screen for ``delay`` seconds (``None`` if 0)."""
    if delay <= 0:
        return None

    async def pause(stage: str, progress: float) -> None:
        if stage != "done":
            await asyncio.sleep(delay)

    return pause


async def read_sample(
    ctx: AppContext, document: Document, job: Job | None, *, stage_delay: float = 0.0
) -> Document:
    """Run the pipeline for an added sample (``job`` from :func:`add_sample`; ``None``: already read)."""
    if job is None:
        return ctx.store.get_document(document.id) or document
    return await ingest_document(ctx, document.id, job_id=job.id, on_stage=paced(stage_delay))


def _tray_sample(manifest: Manifest, item_id: str) -> SampleDocument:
    sample = manifest.document(item_id)
    if sample is None or not sample.tray:
        raise TrayItemNotFound(f"There is no letter {item_id!r} in the New-mail tray.")
    return sample


async def start_tray_item(
    ctx: AppContext,
    item_id: str,
    *,
    manifest: Manifest | None = None,
    samples: str | Path | None = None,
) -> TrayOpening:
    """Take a letter out of the tray: add it, claim its job and mark it opened (fast)."""
    chosen = manifest or load_manifest(samples)
    sample = _tray_sample(chosen, item_id)
    known = _opened(ctx.store).get(item_id)
    existing = ctx.store.get_document(known) if known else None
    if existing is not None and existing.deleted_at is None:
        return TrayOpening(_tray_item(sample, _opened(ctx.store)), existing, None)
    document, job = await add_sample(ctx, sample, samples)
    _mark_opened(ctx.store, item_id, document.id)
    ctx.bus.publish("demo.mail", id=item_id, doc_id=document.id, opened=True)
    return TrayOpening(_tray_item(sample, _opened(ctx.store)), document, job)


async def finish_tray_item(
    ctx: AppContext, opening: TrayOpening, *, stage_delay: float | None = None
) -> Document:
    """Read an opened tray letter (stages paced in demo mode), then run the triggers (new Ideas)."""
    delay = (DEMO_STAGE_DELAY_S if ctx.settings.demo else 0.0) if stage_delay is None else stage_delay
    document = await read_sample(ctx, opening.document, opening.job, stage_delay=delay)
    if opening.job is not None:
        await run_triggers(ctx)
    return document


_READING: set[asyncio.Task[Document]] = set()


def _finished(task: asyncio.Task[Document]) -> None:
    _READING.discard(task)
    if not task.cancelled() and task.exception() is not None:
        log.warning("reading a tray letter failed", exc_info=task.exception())


def _latest_job(store: Store, doc_id: str) -> Job:
    job = next((job for job in store.list_jobs() if job.doc_id == doc_id), None)
    if job is None:
        raise RuntimeError(f"The tray letter {doc_id} has no reading job.")
    return job


async def open_mail(ctx: AppContext, mail_id: str) -> tuple[Document, Job]:
    """``POST /api/demo/mail``: take a letter out of the tray and read it in the background.

    Returns at once with the document and its job; the stages arrive as ``job.progress`` events.
    Raises :class:`TrayItemNotFound` (a ``KeyError``) for an unknown id.
    """
    opening = await start_tray_item(ctx, mail_id)
    if opening.job is None:
        return opening.document, _latest_job(ctx.store, opening.document.id)
    task = asyncio.create_task(finish_tray_item(ctx, opening), name=f"ordnung-demo-mail-{mail_id}")
    _READING.add(task)
    task.add_done_callback(_finished)
    return opening.document, opening.job


async def open_tray_item(
    ctx: AppContext,
    item_id: str,
    *,
    stage_delay: float | None = None,
    manifest: Manifest | None = None,
    samples: str | Path | None = None,
) -> str:
    """Open a tray letter and read it live; returns its document id."""
    opening = await start_tray_item(ctx, item_id, manifest=manifest, samples=samples)
    document = await finish_tray_item(ctx, opening, stage_delay=stage_delay)
    return document.id


# --------------------------------------------------------------------------------------------------
# friendly replay misses
# --------------------------------------------------------------------------------------------------


def is_replay_miss(event: StreamEvent) -> bool:
    """Whether a stream event reports that the demo has no recording for this request."""
    if event.type == "error":
        return (event.error or "").startswith(REPLAY_MISS_PREFIX)
    return event.type == "done" and event.text == ASK_DEMO_MISS


def demo_miss_event() -> StreamEvent:
    """The one event shown instead of an answer the demo has no recording for."""
    return StreamEvent(type="error", error=DEMO_MISS_MESSAGE, text=DEMO_MISS_MESSAGE)


async def demo_safe_stream(events: AsyncIterator[StreamEvent], *, demo: bool) -> AsyncIterator[StreamEvent]:
    """Pass ``events`` through; in demo mode a replay miss ends the stream with :func:`demo_miss_event`."""
    async for event in events:
        if demo and is_replay_miss(event):
            yield demo_miss_event()
            return
        yield event


#: Pauses of the paced replay: after each tool step, and per piece of answer text.
REPLAY_TOOL_PAUSE_S = 0.45
REPLAY_TEXT_PAUSE_S = 0.018


async def paced_replay(
    events: AsyncIterator[StreamEvent],
    *,
    tool_pause: float = REPLAY_TOOL_PAUSE_S,
    text_pause: float = REPLAY_TEXT_PAUSE_S,
) -> AsyncIterator[StreamEvent]:
    """A recorded Ask answer at the pace a live one arrives: the tool steps one by one, then the
    text in small pieces (the recording is replayed in milliseconds otherwise)."""
    async for event in events:
        yield event
        if event.type in ("tool_use", "tool_result"):
            await asyncio.sleep(tool_pause)
        elif event.type == "text":
            await asyncio.sleep(text_pause)


def friendly_llm_error(exc: LLMError, *, demo: bool) -> str:
    """The message to show for a failed model call (the demo explains missing recordings kindly)."""
    if demo and (isinstance(exc, ReplayMiss) or str(exc).startswith(REPLAY_MISS_PREFIX)):
        return DEMO_MISS_MESSAGE
    return str(exc)
