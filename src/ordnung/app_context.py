"""The application context: everything a request handler, CLI command or background task needs.

``build_context`` opens the data directory, applies a simulated "today" (settings or the
``simulated_today`` meta key shared with the MCP subprocess), picks the model backend (the live one
reads the chosen model from the settings) and wires the LLM service to the store (cache + accounting)
and the event bus. The ingest worker is created with
the context but only runs once started (``await ctx.worker.start()``) or driven with
``await ctx.worker.run_until_idle()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

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


@dataclass(eq=False)
class AppContext:
    """Shared services of one running Ordnung instance (one data directory)."""

    paths: Paths
    store: Store
    llm: LLMService
    bus: EventBus
    settings: AppSettings
    worker: IngestWorker = field(init=False)

    def __post_init__(self) -> None:
        from ordnung.ingest.worker import IngestWorker

        self.worker = IngestWorker(self)

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
        self.store.close()

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
    store = Store.open(paths)
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
