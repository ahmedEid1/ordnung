"""Settings saved at the same time (``PUT /api/settings``) take turns, so the settings the app runs with are the
ones saved last and no save loses another's change. Two windows make such saves, and so does the *Text in
pictures* switch clicked off and on quickly; the switch then does what the running settings say."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from ordnung.api.routes.profile import SettingsPatch, _merge_settings
from ordnung.app_context import AppContext
from ordnung.models import AppSettings
from test_api_support import api_for

#: How long the first save holds on while the second one could run (it can't once saves take turns).
HOLD_S = 1.0


def save_together(
    ctx: AppContext,
    monkeypatch: pytest.MonkeyPatch,
    first: SettingsPatch,
    second: SettingsPatch,
    *,
    hold_after_write: bool,
) -> None:
    """Save ``first`` and, while it holds at one read of the settings (its re-read after writing, or its read
    before), ``second``. The first save goes on once the second is done, or after :data:`HOLD_S` when the second
    waits its turn."""
    store = ctx.store
    read, write = store.get_settings, store.save_settings
    first_thread: list[int] = []
    wrote, held, second_done = threading.Event(), threading.Event(), threading.Event()

    def get_settings() -> AppSettings:
        settings = read()
        if threading.get_ident() in first_thread and not held.is_set() and wrote.is_set() is hold_after_write:
            held.set()
            second_done.wait(HOLD_S)
        return settings

    def save_settings(settings: AppSettings) -> AppSettings:
        if threading.get_ident() in first_thread:
            wrote.set()
        return write(settings)

    def first_save() -> None:
        first_thread.append(threading.get_ident())
        _merge_settings(ctx, first)

    def second_save() -> None:
        try:
            _merge_settings(ctx, second)
        finally:
            second_done.set()

    monkeypatch.setattr(store, "get_settings", get_settings)
    monkeypatch.setattr(store, "save_settings", save_settings)
    one = threading.Thread(target=first_save)
    one.start()
    assert held.wait(5)
    two = threading.Thread(target=second_save)
    two.start()
    for thread in (one, two):
        thread.join(10)
        assert not thread.is_alive()


async def test_the_running_settings_are_the_ones_saved_last(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Saved off, then on while the off save re-reads: the off save's re-read finishing late can't put the app
    back on the off settings."""
    async with api_for(data_dir) as api:
        off, on = SettingsPatch(read_picture_text=False), SettingsPatch(read_picture_text=True)
        save_together(api.ctx, monkeypatch, off, on, hold_after_write=True)
        assert api.ctx.store.get_settings().read_picture_text is True
        assert api.ctx.settings.read_picture_text is True


async def test_a_save_keeps_what_another_saved_at_the_same_time(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two saves of different settings at once: both changes stay (neither writes over the other's)."""
    async with api_for(data_dir) as api:
        pictures_off, brief_off = SettingsPatch(read_picture_text=False), SettingsPatch(llm_brief=False)
        save_together(api.ctx, monkeypatch, pictures_off, brief_off, hold_after_write=False)
        saved = api.ctx.store.get_settings()
        assert (saved.read_picture_text, saved.llm_brief) == (False, False)
        assert api.ctx.settings == saved
