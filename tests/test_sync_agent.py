"""Hand-off sync inside a running server (:mod:`ordnung.sync.agent`), against the fake engine: the
lifespan and the mode, background work following it, the person counter, saving soon after a change,
the two-phase replace (fence, drain, decide again), waiting take-overs, timeouts and shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from fake_caldav import MemorySecrets
from ordnung.app_context import build_context
from ordnung.config import Paths
from ordnung.db.store import PERSON_META_KEY, Store, person_write
from ordnung.ingest import watcher as watcher_module
from ordnung.llm.fake import FakeBackend
from ordnung.models import ClaudeStatus
from ordnung.sync import agent as agent_module
from ordnung.sync.push import LocalDamaged, TryAgain
from sync_fake_engine import FakeEngine, counter, deliver, head_of, withhold
from sync_support import PASSPHRASE, agent_of, computer, connect, eventually, fast_sync, state_of, status
from test_api_support import Api

pytestmark = pytest.mark.usefixtures("fast")


@pytest.fixture
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    fast_sync(monkeypatch)


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return tmp_path / "Nextcloud" / "Ordnung"


@pytest.fixture
def secrets() -> MemorySecrets:
    return MemorySecrets()


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "Nextcloud").mkdir(exist_ok=True)
    return tmp_path / "desk", tmp_path / "lap"


async def _add_todo(api: Api, title: str) -> Any:
    return await api.client.post("/api/items", json={"kind": "task", "title": title})


async def _switch(a: Api, b: Api, folder: Path) -> None:
    """desktop sets up, laptop joins and changes something: desktop stands by (and taking over there
    brings laptop's change)."""
    await connect(a, folder, "desktop")
    await connect(b, folder, "laptop")
    assert (await _add_todo(b, "Written on the laptop")).status_code == 201
    await agent_of(b).save()
    await eventually(lambda: agent_of(a).mode == "standing_by")


async def _connected_pair(tmp_path: Path, folder: Path, engine: FakeEngine) -> tuple[Path, Path]:
    """desktop sets up (in use, with one to-do saved), and laptop's data folder exists."""
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as api:
        await connect(api, folder, "desktop")
        assert (await _add_todo(api, "Pay the gym")).status_code == 201
        await agent_of(api).save()
    return desk, lap


# --------------------------------------------------------------------------------------------------
# the store's side: the person counter and durable commits
# --------------------------------------------------------------------------------------------------


def test_the_person_counter_moves_in_the_same_transaction_and_only_for_real_writes(store: Store) -> None:
    with person_write():
        store.set_meta("weekly_session_at", "2026-10-07")
        assert counter(store) == 1
        with store.tx():  # a transaction that changes nothing counts nothing
            store.get_meta("weekly_session_at")
        assert counter(store) == 1
        with store.tx():  # nested writes are one transaction: one count
            store.set_meta("last_review_at", "2026-10-07")
            store.set_meta("weekly_prompt_dismissed_at", "2026-10-07")
        assert counter(store) == 2
        with contextlib.suppress(RuntimeError), store.tx():  # rolled back: not counted either
            store.set_meta("last_review_at", "2026-10-08")
            raise RuntimeError
        assert counter(store) == 2
    store.set_meta("last_review_at", "2026-10-09")  # background work
    assert counter(store) == 2


def test_a_durable_store_commits_with_synchronous_full(paths: Paths) -> None:
    def synchronous(store: Store) -> int:
        return int(store._conn().execute("PRAGMA synchronous").fetchone()[0])

    with Store.open(paths) as store:
        assert synchronous(store) == 1  # NORMAL
        store.set_durable(True)  # sync connected while the server runs
        store.set_meta("x", "1")
        assert synchronous(store) == 2  # FULL, from this thread's next transaction on
        store.set_durable(False)
        store.set_meta("x", "2")
        assert synchronous(store) == 1
    with Store.open(paths, durable=True) as store:
        assert synchronous(store) == 2
    (paths.data_dir / "sync").mkdir()
    (paths.data_dir / "sync" / "state.json").write_text("{}")
    context = build_context(paths.data_dir, backend_obj=FakeBackend())
    try:
        assert context.store.durable is True
    finally:
        context.close()


# --------------------------------------------------------------------------------------------------
# the mode at start, and background work following it
# --------------------------------------------------------------------------------------------------


async def test_without_a_connection_sync_is_off_and_background_work_runs(data_dir: Path) -> None:
    async with computer(data_dir) as api:
        agent, state = agent_of(api), state_of(api)
        assert (agent.mode, agent.connected) == ("off", False)
        assert state.background_on and api.ctx.worker.running
        assert agent._task is None  # no loop without a connection
        found = await status(api)
        assert (found["mode"], found["connected"], found["available"]) == ("off", False, True)


async def test_without_an_engine_sync_is_unavailable_and_writes_say_so(data_dir: Path) -> None:
    async with computer(data_dir) as api:
        agent_of(api).engine = None
        found = await status(api)
        assert found["available"] is False and found["unavailable"] == agent_module.NO_ENGINE_MESSAGE
        refused = await api.client.post("/api/sync/use-here", json={})
        assert refused.status_code == 409 and refused.json()["code"] == "unavailable"


async def test_setting_up_saves_at_once_and_the_store_turns_durable(tmp_path: Path, folder: Path) -> None:
    desk, _ = _dirs(tmp_path)
    engine = FakeEngine()
    async with computer(desk, engine=engine) as api:
        answer = await connect(api, folder, "desktop")
        assert answer["choice"] is None
        found = answer["status"]
        assert (found["connected"], found["mode"], found["this_computer"]) == (True, "in_use", "desktop")
        assert "push:first" in engine.calls
        assert api.ctx.store.durable is True
        assert head_of(folder, "desktop")["version"]
        assert agent_of(api)._task is not None  # the loop runs from now on
        rows = api.ctx.store.list_activity(limit=20) if hasattr(api.ctx.store, "list_activity") else []
        assert rows is not None


async def test_last_known_mode_standing_by_starts_no_background_work(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    desk, lap = await _connected_pair(tmp_path, folder, engine)
    async with computer(lap, engine=engine) as api:
        await connect(api, folder, "laptop")  # joins and takes over
        assert agent_of(api).mode == "in_use"
    async with computer(desk, engine=engine) as api:  # desktop starts again: laptop is in use
        state = state_of(api)
        await eventually(lambda: agent_of(api).mode == "standing_by")
        assert not state.background_on
        assert not api.ctx.worker.running and not state.folder.running
        assert state.tick._task is None or state.tick._task.done()
        assert api.ctx.store.durable is True


# --------------------------------------------------------------------------------------------------
# a take-over: two computers
# --------------------------------------------------------------------------------------------------


async def test_joining_brings_everything_over_and_the_other_computer_stands_by(
    tmp_path: Path, folder: Path
) -> None:
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await connect(a, folder, "desktop")
        assert (await _add_todo(a, "Pay the gym")).status_code == 201
        await agent_of(a).save()
        answer = await connect(b, folder, "laptop")
        assert answer["status"]["mode"] == "in_use", answer
        titles = [item["title"] for item in (await b.client.get("/api/items")).json()]
        assert "Pay the gym" in titles
        assert state_of(b).background_on and b.ctx.worker.running
        # desktop learns it was replaced: background work stops, writes are refused
        await eventually(lambda: agent_of(a).mode == "standing_by")
        await eventually(lambda: not state_of(a).background_on and not a.ctx.worker.running)
        refused = await _add_todo(a, "Too late")
        assert refused.status_code == 409
        assert refused.json() == {
            "detail": "Ordnung is in use on laptop. Use it here first (Settings → Your computers).",
            "code": "standby",
        }
        await eventually(lambda: head_of(folder, "desktop")["state"] == "standing_by")
        # and takes over again with one click
        taken = await a.client.post("/api/sync/use-here", json={})
        assert taken.status_code == 200 and taken.json()["mode"] == "in_use", taken.text
        assert (await _add_todo(a, "Back on the desktop")).status_code == 201
        await eventually(lambda: agent_of(b).mode == "standing_by")


async def test_a_take_over_recovers_the_pulled_database_s_interrupted_readings(
    tmp_path: Path, folder: Path
) -> None:
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        requeued: list[int] = []
        original = a.ctx.store.requeue_running_jobs
        a.ctx.store.requeue_running_jobs = lambda: requeued.append(1) or original()  # type: ignore[method-assign]
        assert (await a.client.post("/api/sync/use-here", json={})).status_code == 200
        assert requeued, "the worker recovers the replaced database's jobs when it starts again"


async def test_the_person_counter_counts_requests_and_the_watched_folder_not_readings(
    tmp_path: Path, folder: Path
) -> None:
    desk, _ = _dirs(tmp_path)
    async with computer(desk) as api:
        await connect(api, folder, "desktop")
        before = counter(api.ctx.store)
        assert (await _add_todo(api, "Pay the gym")).status_code == 201
        assert counter(api.ctx.store) == before + 1
        # a background write (a reading's, the tick's) never counts
        await asyncio.to_thread(api.ctx.store.set_meta, "last_review_at", "2026-10-07")
        assert counter(api.ctx.store) == before + 1
        # hand-off sync's own writes and the exempt ones don't either
        assert (await api.client.post("/api/sync/save", json={})).status_code == 200
        assert counter(api.ctx.store) == before + 1
        # the counter row is this computer's, never the person's data
        assert api.ctx.store.get_meta(PERSON_META_KEY) == str(before + 1)


async def test_nothing_is_counted_while_sync_is_off(data_dir: Path) -> None:
    async with computer(data_dir) as api:
        assert (await _add_todo(api, "Pay the gym")).status_code == 201
        assert api.ctx.store.get_meta(PERSON_META_KEY) is None


async def test_a_person_s_change_is_saved_within_seconds(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    desk, _ = _dirs(tmp_path)
    async with computer(desk, engine=engine) as api:
        await connect(api, folder, "desktop")
        first = head_of(folder, "desktop")["version"]
        assert (await _add_todo(api, "Pay the gym")).status_code == 201
        await eventually(lambda: head_of(folder, "desktop")["version"] != first)
        assert "push:change" in engine.calls
        assert (await status(api))["pending_changes"] is False


async def test_a_change_shows_as_unsaved_from_the_moment_it_is_made(tmp_path: Path, folder: Path) -> None:
    """Integration finding: right after a change the status said "saved" (the last look found nothing
    unsaved), though the change wasn't in the folder yet."""
    engine = FakeEngine()
    desk, _ = _dirs(tmp_path)
    async with computer(desk, engine=engine) as api:
        await connect(api, folder, "desktop")
        agent = agent_of(api)
        await agent.save()
        assert agent.local is not None and not agent.local.pending, "the last look found everything saved"
        assert not agent.status().pending_changes
        agent.person_wrote()  # a request of the person's finished: its save is moments away
        assert agent.status().pending_changes
        await eventually(lambda: not agent.status().pending_changes)


async def test_files_changing_while_saving_wait_and_a_damaged_original_shows_at_once(
    tmp_path: Path, folder: Path
) -> None:
    """Integration finding: both fell back to "the folder can't be reached"."""
    engine = FakeEngine()
    desk, _ = _dirs(tmp_path)
    async with computer(desk, engine=engine) as api:
        await connect(api, folder, "desktop")
        agent = agent_of(api)
        engine.calls.clear()
        engine.fail_push = TryAgain()
        try:
            assert (await _add_todo(api, "Pay the gym")).status_code == 201
            await eventually(lambda: sum(call.startswith("push:") for call in engine.calls) >= 2)
            assert agent.problem is None, "shown only when saving keeps failing (save_failing)"
            engine.fail_push = LocalDamaged("letters/2026/letter.pdf")
            found = await eventually(lambda: agent.problem, within=5)
            assert found.code == "local_damaged"
            assert (await status(api))["problem"]["code"] == "local_damaged"
        finally:
            engine.fail_push = None


async def test_the_watched_folder_s_letters_are_the_person_s_and_remembered_across_computers(
    tmp_path: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desk, _ = _dirs(tmp_path)
    async with computer(desk) as api:
        await connect(api, folder, "desktop")
        watched = state_of(api).folder
        heard: list[int] = []
        watched.on_added = lambda: heard.append(1)
        before = counter(api.ctx.store)
        data = b"%PDF-1.4 a scan"
        monkeypatch.setattr(watcher_module, "is_own_file", lambda store, body: False)

        async def added(ctx: Any, body: bytes, name: str, **kwargs: Any) -> Any:
            await asyncio.to_thread(ctx.store.set_meta, "weekly_session_at", "2026-10-07")

            class Added:
                new = True

                class document:
                    id = "doc_x"
                    status = "held"

            return Added()

        monkeypatch.setattr(watcher_module, "add_file_result", added)
        await watched._add(data, "scan.pdf", hold=True)
        assert counter(api.ctx.store) > before, "the scan counts as the person's change"
        assert heard == [1]
        taken = json.loads(api.ctx.store.get_meta(watcher_module.FOLDER_TAKEN_META_KEY) or "[]")
        assert len(taken) == 1
        # the same content again (here, or on the other computer after a switch) is skipped quietly
        await watched._add(data, "scan (copy).pdf", hold=True)
        assert heard == [1]


async def test_a_computer_standing_by_never_releases_letters_waiting_for_claude(data_dir: Path) -> None:
    async with computer(data_dir, start=False) as api:
        released: list[int] = []
        api.ctx.worker.claude_ready = lambda: released.append(1)  # type: ignore[method-assign]
        state_of(api)._claude_seen(ClaudeStatus(installed=True, ok=True))
        assert released == [1]  # sync off: as ever
        agent = agent_of(api)
        agent.connected, agent.mode = True, "standing_by"
        state_of(api)._claude_seen(ClaudeStatus(installed=True, ok=True))
        assert released == [1], "a computer standing by writes nothing (the health check would)"
        agent.mode, agent._fenced = "in_use", True
        state_of(api)._claude_seen(ClaudeStatus(installed=True, ok=True))
        assert released == [1], "nor while the data is replaced"
        agent._fenced = False
        state_of(api)._claude_seen(ClaudeStatus(installed=True, ok=True))
        assert released == [1, 1]


# --------------------------------------------------------------------------------------------------
# replacing the data: the fence, the drain, deciding again
# --------------------------------------------------------------------------------------------------


async def test_writes_admitted_before_the_fence_finish_first_and_new_ones_are_refused(
    tmp_path: Path, folder: Path
) -> None:
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        agent = agent_of(a)
        order: list[str] = []
        engine.on_apply = lambda: order.append("apply")
        with agent.admitted():  # a write the gate let through is still running
            taking = asyncio.create_task(agent.use_here())
            await eventually(lambda: agent._fenced)
            assert (
                agent.write_refusal(("POST", "/api/items"))
                == "Bringing over changes from laptop — one moment."
            )
            await asyncio.sleep(0.1)
            assert order == [], "nothing is applied while a write runs"
            order.append("write done")
        await taking
        assert order == ["write done", "apply"]
        assert not agent._fenced and agent.mode == "in_use"


async def test_a_write_that_never_finishes_lifts_the_fence_and_nothing_is_replaced(
    tmp_path: Path, folder: Path
) -> None:
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        agent = agent_of(a)
        with agent.admitted():
            await agent.use_here()
        assert "apply" not in engine.calls
        assert not agent._fenced
        assert agent.mode == "standing_by" and (await status(a))["take_over_waiting"] is True


async def test_background_threads_drain_before_the_data_is_replaced(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        release = threading.Event()
        order: list[str] = []
        engine.on_apply = lambda: order.append("apply")

        def lingering() -> None:  # a cancelled reading's thread, still running
            release.wait(5)
            order.append("thread done")

        lingering_future = asyncio.get_running_loop().run_in_executor(a.ctx.executor, lingering)
        taking = asyncio.create_task(agent_of(a).use_here())
        await asyncio.sleep(0.2)
        assert order == []
        release.set()
        await taking
        await lingering_future
        assert order == ["thread done", "apply"]


async def test_a_change_made_while_staging_stops_a_quiet_pull(tmp_path: Path, folder: Path) -> None:
    """Critique finding 1: a write between the decision and the apply is never overwritten — the
    decision is taken again behind the fence, and the staging is discarded."""
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        original_stage = type(agent_of(a)._session).stage  # type: ignore[arg-type]

        def stage_then_write(session: Any, target: Any) -> Any:
            staged = original_stage(session, target)
            with person_write():  # the person's write lands while the version is staged
                a.ctx.store.set_meta("weekly_session_at", "2026-10-07")
            return staged

        from sync_fake_engine import FakeSession

        FakeSession.stage = stage_then_write  # type: ignore[method-assign]
        try:
            await agent_of(a).use_here()
        finally:
            FakeSession.stage = original_stage  # type: ignore[method-assign]
        assert "apply" not in engine.calls and "discard" in engine.calls
        assert a.ctx.store.get_meta("weekly_session_at") == "2026-10-07"


# --------------------------------------------------------------------------------------------------
# waiting for the sync tool
# --------------------------------------------------------------------------------------------------


async def test_a_take_over_waits_for_what_hasn_t_arrived_and_finishes_by_itself(
    tmp_path: Path, folder: Path
) -> None:
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        assert (await _add_todo(b, "Arrives late")).status_code == 201
        await agent_of(b).save()
        withhold(folder)
        waiting = await a.client.post("/api/sync/use-here", json={})
        assert waiting.json()["take_over_waiting"] is True and waiting.json()["mode"] == "standing_by"
        assert waiting.json()["activity"] == "waiting"
        deliver(folder)
        await eventually(lambda: agent_of(a).mode == "in_use")
        titles = [item["title"] for item in (await a.client.get("/api/items")).json()]
        assert "Arrives late" in titles


async def test_after_taking_over_this_computer_is_the_one_in_use_at_once(
    tmp_path: Path, folder: Path
) -> None:
    """Integration finding: the last look still named the other computer until the next one."""
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        assert (await status(a))["in_use_on"] == "laptop"
        taken = await a.client.post("/api/sync/use-here", json={})
        assert taken.status_code == 200, taken.text
        assert taken.json()["mode"] == "in_use" and taken.json()["in_use_on"] == "desktop"


async def test_a_waiting_take_over_gives_up_after_its_time(
    tmp_path: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_module, "TAKE_OVER_WAIT_MAX_S", 0.3)
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        withhold(folder)
        assert (await a.client.post("/api/sync/use-here", json={})).json()["take_over_waiting"] is True
        found = await eventually(lambda: agent_of(a)._waiting is None and agent_of(a).summary)
        notices = [notice["code"] for notice in found.notices]
        assert "take_over_cancelled" in notices
        assert agent_of(a).mode == "standing_by"


async def test_a_waiting_take_over_gives_up_when_the_other_computer_changes_more(
    tmp_path: Path, folder: Path
) -> None:
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        assert (await _add_todo(b, "First")).status_code == 201
        await agent_of(b).save()
        withhold(folder)
        assert (await a.client.post("/api/sync/use-here", json={})).json()["take_over_waiting"] is True
        assert (await _add_todo(b, "Second")).status_code == 201
        await agent_of(b).save()
        withhold(folder)
        await eventually(lambda: agent_of(a)._waiting is None)
        assert agent_of(a).mode == "standing_by"
        assert any(n["code"] == "take_over_cancelled" for n in agent_of(a).summary.notices)  # type: ignore[union-attr]


async def test_cancel_stops_a_waiting_take_over(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        withhold(folder)
        assert (await a.client.post("/api/sync/use-here", json={})).json()["take_over_waiting"] is True
        cancelled = await a.client.post("/api/sync/use-here", json={"cancel": True})
        assert cancelled.json()["take_over_waiting"] is False


# --------------------------------------------------------------------------------------------------
# the password store, timeouts, shutdown
# --------------------------------------------------------------------------------------------------


async def test_a_lost_passphrase_is_a_problem_and_typing_it_again_resumes(
    tmp_path: Path, folder: Path
) -> None:
    secrets = MemorySecrets()
    desk, _ = _dirs(tmp_path)
    async with computer(desk, secrets=secrets) as api:
        await connect(api, folder, "desktop")
    secrets.saved.clear()
    async with computer(desk, secrets=secrets) as api:
        found = await eventually(lambda: agent_of(api).problem)
        assert found.code == "passphrase_needed" and found.actions == ["passphrase"]
        assert agent_of(api).mode == "in_use", "the computer keeps working meanwhile"
        wrong = await api.client.post("/api/sync/passphrase", json={"passphrase": "not it at all, no"})
        assert wrong.status_code == 422 and wrong.json()["code"] == "wrong_passphrase"
        assert "not it at all" not in wrong.text
        right = await api.client.post("/api/sync/passphrase", json={"passphrase": PASSPHRASE})
        assert right.status_code == 200 and right.json()["problem"] is None


async def test_a_locked_password_store_with_the_older_copy_uses_it_here_and_claims_later(
    tmp_path: Path, folder: Path
) -> None:
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    secrets = MemorySecrets()
    async with computer(desk, engine=engine, secrets=secrets) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        agent = agent_of(a)
        saved = dict(secrets.saved)
        secrets.saved.clear()
        agent._session = None  # the password store is locked from now on
        refused = await a.client.post("/api/sync/use-here", json={})
        assert refused.status_code == 409 and refused.json()["code"] == "passphrase_needed"
        anyway = await a.client.post("/api/sync/use-here", json={"older_copy": True})
        assert anyway.json()["mode"] == "in_use" and state_of(a).background_on
        secrets.saved.update(saved)
        await eventually(lambda: head_of(folder, "desktop")["state"] == "in_use" and "claim" in engine.calls)


async def test_a_hanging_folder_is_unreachable_and_the_status_still_answers(
    tmp_path: Path, folder: Path
) -> None:
    engine = FakeEngine()
    desk, _ = _dirs(tmp_path)
    async with computer(desk, engine=engine) as api:
        await connect(api, folder, "desktop")
        engine.hang = threading.Event()
        try:
            found = await eventually(lambda: agent_of(api).problem, within=5)
            assert found.code == "folder_unreachable"
            assert (await status(api))["problem"]["code"] == "folder_unreachable"  # from memory
            busy = await api.client.post("/api/sync/save", json={})
            assert busy.status_code == 409 and busy.json()["code"] == "folder_problem"
            assert (await _add_todo(api, "Still works")).status_code == 201
        finally:
            engine.hang.set()
            engine.hang = None


async def test_shutdown_saves_and_says_the_computer_was_closed(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    desk, _ = _dirs(tmp_path)
    async with computer(desk, engine=engine) as api:
        await connect(api, folder, "desktop")
        engine.calls.clear()
        assert (await _add_todo(api, "Last thing")).status_code == 201
    assert head_of(folder, "desktop")["state"] == "closed"
    pushes = [call for call in engine.calls if call.startswith("push:")]
    assert pushes[-1] == "push:shutdown"
    assert "push:change" in pushes, "the person's change is saved before readings get their grace period"


async def test_a_hanging_folder_never_holds_up_shutdown(tmp_path: Path, folder: Path) -> None:
    engine = FakeEngine()
    desk, _ = _dirs(tmp_path)
    started = 0.0
    async with computer(desk, engine=engine) as api:
        await connect(api, folder, "desktop")
        engine.hang = threading.Event()
        started = asyncio.get_running_loop().time()
    elapsed = asyncio.get_running_loop().time() - started
    engine.hang.set()
    assert elapsed < 4 * agent_module.SHUTDOWN_PUSH_S + 1


# --------------------------------------------------------------------------------------------------
# both changed, problems with their actions
# --------------------------------------------------------------------------------------------------


async def test_both_computers_changed_gives_a_choice_and_either_answer_ends_it(
    tmp_path: Path, folder: Path
) -> None:
    engine = FakeEngine()
    desk, lap = _dirs(tmp_path)
    async with computer(desk, engine=engine) as a, computer(lap, engine=engine) as b:
        await _switch(a, b, folder)
        # desktop changes something after all (written straight into its database, as the person)
        with person_write():
            await asyncio.to_thread(a.ctx.store.set_meta, "weekly_session_at", "2026-10-07")
        assert (await _add_todo(b, "On the laptop")).status_code == 201
        await agent_of(b).save()
        answer = (await a.client.post("/api/sync/use-here", json={})).json()
        if answer["choice"] is None:  # the late push made laptop's view diverge first
            answer = (await a.client.post("/api/sync/use-here", json={})).json()
        assert answer["choice"] is not None, answer
        sides = answer["choice"]["sides"]
        laptop = next(side for side in sides if not side["this"])
        chosen = await a.client.post("/api/sync/choose", json={"keep": laptop["key"]})
        assert chosen.status_code == 200, chosen.text
        found = chosen.json()
        assert found["mode"] == "in_use" and found["choice"] is None
        assert found["kept"] and found["kept"][0]["name"].startswith("ordnung-kept-")
        nothing = await a.client.post("/api/sync/choose", json={"keep": laptop["key"]})
        assert nothing.status_code == 409 and nothing.json()["code"] == "no_choice"


async def test_a_copied_data_folder_pauses_with_two_actions(tmp_path: Path, folder: Path) -> None:
    from sync_fake_engine import Decision, Problem

    engine = FakeEngine()
    engine.decide = lambda local, view, action: Decision("paused", problem=Problem("copied_folder"))  # type: ignore[method-assign]
    desk, _ = _dirs(tmp_path)
    async with computer(desk, engine=engine) as api:
        await connect(api, folder, "desktop")
        found = await eventually(lambda: agent_of(api).problem)
        assert found.code == "copied_folder" and found.actions == ["same_computer", "new_computer"]
        engine.decide = lambda local, view, action: Decision("idle")  # type: ignore[method-assign]
        confirmed = await api.client.patch("/api/sync", json={"confirm_same_computer": True})
        assert confirmed.status_code == 200 and confirmed.json()["problem"] is None
        again = await api.client.patch("/api/sync", json={"confirm_same_computer": True})
        assert again.status_code == 409 and again.json()["code"] == "not_needed"
