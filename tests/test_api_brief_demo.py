"""*Write a new note* where Claude is only replayed (the demo): its recorded note stays while the agenda it was
written from is unchanged, and the code writes the note once the agenda changes — never a model call."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from fixtures_llm import TAX_LETTER
from ordnung import clock
from ordnung.llm.replay import ReplayBackend
from test_api_support import TODAY, Api, api_for


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


async def _recorded_note(api: Api, recordings: Path) -> dict[str, object]:
    """A letter read and a note by Claude stored, then Claude replaced by replays that hold no new note."""
    await api.upload(("letter.pdf", TAX_LETTER.pdf()))
    await api.read_all()
    note = (await api.client.post("/api/brief")).json()
    assert note["source"] == "llm"
    api.ctx.llm.backend = ReplayBackend(recordings)
    return note


async def test_a_new_note_keeps_the_recorded_one_while_the_agenda_is_unchanged(
    data_dir: Path, tmp_path: Path
) -> None:
    async with api_for(data_dir) as api:
        recorded = await _recorded_note(api, tmp_path / "recordings")
        again = await api.client.post("/api/brief")
        assert again.status_code == 200 and again.json() == recorded
        assert (await api.client.get("/api/brief")).json() == recorded
        # the agenda changes: the recorded note no longer fits, so the code writes the new one
        added = await api.client.post(
            "/api/items", json={"kind": "task", "title": "Call the landlord", "due_date": "2026-09-28"}
        )
        assert added.status_code == 201, added.text
        written = (await api.client.post("/api/brief")).json()
        assert written["source"] == "template" and "Call the landlord" in written["text"]
        assert (await api.client.get("/api/brief")).json() == written


@pytest.mark.parametrize("ask", ["code only", "AI note off"])
async def test_a_note_from_the_records_is_still_written_when_asked_for(
    data_dir: Path, tmp_path: Path, ask: str
) -> None:
    """``llm=false`` (``ordnung brief --no-llm``) and *AI note* off mean the code's note, replays or not."""
    async with api_for(data_dir) as api:
        await _recorded_note(api, tmp_path / "recordings")
        params = {}
        if ask == "code only":
            params["llm"] = "false"
        else:
            saved = await api.client.put("/api/settings", json={"llm_brief": False})
            assert saved.status_code == 200, saved.text
        written = (await api.client.post("/api/brief", params=params)).json()
        assert written["source"] == "template"
        assert (await api.client.get("/api/brief")).json() == written
