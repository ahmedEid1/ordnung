"""The application context: everything a request handler, CLI command or background task needs.

``build_context`` opens the data directory, applies a simulated "today" (settings or the
``simulated_today`` meta key shared with the MCP subprocess), picks the model backend (the live one
reads the chosen model from the settings) and wires the LLM service to the store (cache + accounting)
and the event bus. The ingest worker is created with
the context but only runs once started (``await ctx.worker.start()``) or driven with
``await ctx.worker.run_until_idle()``. While hand-off sync is connected (``<data>/sync/state.json``
exists) the store commits durably (``synchronous=FULL``), so a save to the sync folder never carries a
change the disk could still lose.

The context also owns the server's thread pool (:class:`DrainableExecutor`, installed as the event
loop's default executor by the server): before hand-off sync replaces the data under a running server
it waits until no background thread — a reading, the Ideas, calendar sync — is still writing.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from ordnung import clock
from ordnung.config import Paths, resolve_paths
from ordnung.db.store import Store
from ordnung.events import EventBus
from ordnung.llm.base import LLMBackend
from ordnung.llm.runtime import LLMService, make_backend
from ordnung.models import AppSettings

if TYPE_CHECKING:
    from ordnung.ingest.worker import IngestWorker

SIMULATED_TODAY_KEY = "simulated_today"
#: ``<data>/sync/state.json``: hand-off sync is connected (``ordnung.sync``; its state lives there).
SYNC_STATE = ("sync", "state.json")

T = TypeVar("T")


class DrainableExecutor(ThreadPoolExecutor):
    """A thread pool that knows how many of its calls are still running (:attr:`busy`): the server's
    default executor, so every ``asyncio.to_thread`` call counts. A task that was cancelled leaves its
    thread running to the end; this is how hand-off sync waits for such threads before it replaces
    the data. The event loop that runs it shuts it down."""

    def __init__(self) -> None:
        super().__init__(thread_name_prefix="ordnung")
        self._busy = 0
        self._count_lock = threading.Lock()

    @property
    def busy(self) -> int:
        """Calls submitted that haven't finished."""
        return self._busy

    def submit(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> Future[T]:
        with self._count_lock:
            self._busy += 1
        try:
            future = super().submit(fn, *args, **kwargs)
        except BaseException:
            with self._count_lock:
                self._busy -= 1
            raise
        future.add_done_callback(self._finished)
        return future

    def _finished(self, _future: Future[Any]) -> None:
        with self._count_lock:
            self._busy -= 1


def sync_connected(paths: Paths) -> bool:
    """Hand-off sync is connected for this data folder (its state file exists)."""
    return paths.data_dir.joinpath(*SYNC_STATE).is_file()


@dataclass(eq=False)
class AppContext:
    """Shared services of one running Ordnung instance (one data directory)."""

    paths: Paths
    store: Store
    llm: LLMService
    bus: EventBus
    settings: AppSettings
    worker: IngestWorker = field(init=False)
    executor: DrainableExecutor = field(init=False)

    def __post_init__(self) -> None:
        from ordnung.ingest.worker import IngestWorker

        self.worker = IngestWorker(self)
        self.executor = DrainableExecutor()

    @property
    def backend_name(self) -> str:
        """Name of the model backend (``claude``, ``replay``, ``fake`` …)."""
        return self.llm.backend_name

    def reload_settings(self) -> AppSettings:
        """Re-read the settings (after the person saved them) and re-apply the simulated today."""
        self.settings = self.store.get_settings()
        apply_simulated_today(self.store, self.settings)
        return self.settings

    async def aclose(self) -> None:
        """Stop the worker and close the database."""
        await self.worker.stop()
        self.close()

    def close(self) -> None:
        """Close the database (the worker must not be running)."""
        self.store.close()


def apply_simulated_today(store: Store, settings: AppSettings) -> str | None:
    """Pin :func:`ordnung.clock.today` to ``settings.simulated_today`` or the meta key, if set."""
    simulated = settings.simulated_today or store.get_meta(SIMULATED_TODAY_KEY)
    if simulated:
        clock.set_today(simulated)
    # the demo dates what happens while exploring it on its simulated day ("Read on Mon 28 Sep")
    clock.stamp_simulated_day(bool(simulated) and settings.demo, store.get_profile().timezone)
    return simulated


def build_context(
    data_dir: str | Path | None = None,
    *,
    backend: str | None = None,
    backend_obj: LLMBackend | None = None,
) -> AppContext:
    """Open (creating if needed) a data directory and wire up store, model service, bus and worker.

    ``backend`` names the model backend (``claude`` by default, ``replay``, ``replay+claude``,
    ``fake``; ``ORDNUNG_BACKEND`` overrides the default); ``backend_obj`` supplies a ready one
    (tests pass a ``FakeBackend``).
    """
    paths = resolve_paths(data_dir)
    store = Store.open(paths, durable=sync_connected(paths))
    try:
        settings = store.get_settings()
        apply_simulated_today(store, settings)
        # the live backend reads the chosen model from the store at each call: a save counts at once
        chosen = backend_obj or make_backend(
            backend, concurrency=settings.concurrency, model_setting=lambda: store.get_settings().model
        )
    except BaseException:
        store.close()
        raise
    bus = EventBus()
    return AppContext(
        paths=paths, store=store, llm=LLMService(chosen, store, bus), bus=bus, settings=settings
    )
