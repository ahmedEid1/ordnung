"""``ordnung sync …`` and hand-off sync's place in the other commands, against the fake engine: every
command in process (under the data folder's lock) and through a running server's API, the passphrase
from ``ORDNUNG_SYNC_PASSPHRASE``, in-process writes refused while standing by and saved right after,
the demo refused, ``serve``'s interrupted take-over finished first, the doctor's row and restore's
note."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from fake_caldav import MemorySecrets
from fixtures_llm import TAX_LETTER, TODAY, fake_backend
from ordnung import cli, clock, doctor, sync
from ordnung.app_context import build_context
from ordnung.cli import app
from ordnung.config import Paths
from ordnung.db.store import PERSON_META_KEY, Store
from ordnung.demo.loader import MARKER_NAME
from ordnung.server import ServerInfo
from ordnung.sync import agent as agent_module
from sync_fake_engine import FakeEngine, head_of
from sync_support import PASSPHRASE

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


@pytest.fixture(autouse=True)
def pinned_today() -> Iterator[None]:
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    """The fake engine, one password store per data folder, the fake model, no running server."""
    fake = FakeEngine()
    keyrings: dict[str, MemorySecrets] = {}
    monkeypatch.setattr(agent_module, "load_engine", lambda: fake)
    monkeypatch.setattr(agent_module, "default_secrets", lambda: keyrings.setdefault("this", MemorySecrets()))
    monkeypatch.setattr(
        cli, "open_context", lambda data_dir: build_context(data_dir, backend_obj=fake_backend())
    )
    monkeypatch.setattr(cli, "reachable_server", lambda folder: None)
    monkeypatch.setenv(sync.PASSPHRASE_ENV, PASSPHRASE)
    return fake


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / "Nextcloud").mkdir()
    return tmp_path / "Nextcloud" / "Ordnung"


def invoke(*args: str, input: str | None = None) -> Any:
    return runner.invoke(app, list(args), input=input)


def _state(data_dir: Path) -> dict[str, Any]:
    found: dict[str, Any] = json.loads((data_dir / "sync" / "state.json").read_text())
    return found


# --------------------------------------------------------------------------------------------------
# in process
# --------------------------------------------------------------------------------------------------


def test_status_without_a_connection(engine: FakeEngine, data_dir: Path) -> None:
    result = invoke("sync", "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert "This computer doesn't sync" in result.output
    assert invoke("sync", "status", "--data-dir", str(data_dir)).exit_code == 0


def test_connect_with_the_passphrase_from_the_environment(
    engine: FakeEngine, data_dir: Path, folder: Path
) -> None:
    result = invoke("sync", "connect", str(folder), "--name", "desktop", "--data-dir", str(data_dir))
    assert result.exit_code == 0, result.output
    assert "Setting up a new sync" in result.output and "Started syncing." in result.output
    assert "In use here (desktop)" in result.output
    assert PASSPHRASE not in result.output
    assert head_of(folder, "desktop")["version"], "the first save"
    status = invoke("sync", "status", "--data-dir", str(data_dir))
    assert "In use here (desktop)" in status.output


def test_a_weak_passphrase_for_a_new_folder_is_refused(
    engine: FakeEngine, data_dir: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(sync.PASSPHRASE_ENV, "secret secret secret")
    result = invoke("sync", "connect", str(folder), "--data-dir", str(data_dir))
    assert result.exit_code == 1
    assert "ORDNUNG_SYNC_PASSPHRASE" in result.output and not (data_dir / "sync").exists()


def test_joining_with_letters_asks_which_to_keep(engine: FakeEngine, tmp_path: Path, folder: Path) -> None:
    desk, lap = tmp_path / "desk", tmp_path / "lap"
    assert invoke("sync", "connect", str(folder), "--name", "desktop", "--data-dir", str(desk)).exit_code == 0
    with Store.open(Paths(lap)) as store:
        store.add_item(kind="task", title="The laptop's own")
    asked = invoke("sync", "connect", str(folder), "--name", "laptop", "--data-dir", str(lap))
    assert asked.exit_code == 1, asked.output
    assert (
        "Which Ordnung do you want to keep?" in asked.output
        and "--keep this or --keep folder" in asked.output
    )
    assert not (lap / "sync" / "state.json").exists()
    joined = invoke(
        "sync", "connect", str(folder), "--name", "laptop", "--keep", "folder", "--data-dir", str(lap)
    )
    assert joined.exit_code == 0, joined.output
    assert "Joined." in joined.output and "In use here (laptop)" in joined.output


def test_use_here_takes_over_in_process(engine: FakeEngine, tmp_path: Path, folder: Path) -> None:
    desk, lap = tmp_path / "desk", tmp_path / "lap"
    assert invoke("sync", "connect", str(folder), "--name", "desktop", "--data-dir", str(desk)).exit_code == 0
    assert invoke("sync", "connect", str(folder), "--name", "laptop", "--data-dir", str(lap)).exit_code == 0
    state = _state(desk)
    state["mode"] = "standing_by"  # what desktop's agent writes once it sees laptop's claim
    (desk / "sync" / "state.json").write_text(json.dumps(state))
    taken = invoke("sync", "use-here", "--data-dir", str(desk))
    assert taken.exit_code == 0, taken.output
    assert "Ordnung is in use here now." in taken.output
    assert head_of(folder, "desktop")["state"] == "in_use"
    assert engine.resumed >= 1, "an interrupted take-over is finished first"


def test_writes_without_a_server_are_refused_while_standing_by(
    engine: FakeEngine, tmp_path: Path, folder: Path
) -> None:
    desk = tmp_path / "desk"
    assert invoke("sync", "connect", str(folder), "--name", "desktop", "--data-dir", str(desk)).exit_code == 0
    letter = tmp_path / "letter.pdf"
    letter.write_bytes(TAX_LETTER.pdf())
    added = invoke("--data-dir", str(desk), "add", str(letter))
    assert added.exit_code == 0, added.output
    assert "Saved to the sync folder." in added.output
    with Store.open(Paths(desk)) as store:
        assert int(store.get_meta(PERSON_META_KEY) or 0) >= 1, "the letter counts as the person's change"
    state = _state(desk)
    state["mode"] = "standing_by"
    (desk / "sync" / "state.json").write_text(json.dumps(state))
    refused = invoke("--data-dir", str(desk), "add", str(letter))
    assert refused.exit_code == 1
    assert "Ordnung is in use on" in refused.output and "ordnung sync use-here" in refused.output


def test_save_kept_forget_and_disconnect(engine: FakeEngine, tmp_path: Path, folder: Path) -> None:
    from sync_fake_engine import FakeSession

    desk, lap = tmp_path / "desk", tmp_path / "lap"
    assert invoke("sync", "connect", str(folder), "--name", "desktop", "--data-dir", str(desk)).exit_code == 0
    assert (
        invoke("sync", "save", "--data-dir", str(desk)).output.strip().endswith("Saved to the sync folder.")
    )
    kept = FakeSession(engine, Paths(desk)).keep_local(Paths(desk), "before you kept laptop's Ordnung")
    listed = invoke("sync", "kept", "--data-dir", str(desk))
    assert kept.name in listed.output and "ordnung restore" in listed.output
    deleted = invoke("sync", "kept", "--delete", kept.name, "--data-dir", str(desk))
    assert deleted.exit_code == 0 and not (desk / "sync" / "kept" / kept.name).exists()
    assert invoke("sync", "kept", "--delete", kept.name, "--data-dir", str(desk)).exit_code == 1

    assert invoke("sync", "connect", str(folder), "--name", "laptop", "--data-dir", str(lap)).exit_code == 0
    refused = invoke("sync", "forget", "laptop", "--yes", "--data-dir", str(desk))
    assert refused.exit_code == 1 and "the one in use" in refused.output
    forgotten = invoke("sync", "forget", "desktop", "--yes", "--data-dir", str(lap))
    assert forgotten.exit_code == 0, forgotten.output
    assert "still knows the passphrase" in forgotten.output

    declined = invoke("sync", "disconnect", "--data-dir", str(lap), input="n\n")
    assert declined.exit_code == 1 and (lap / "sync" / "state.json").exists()
    left = invoke("sync", "disconnect", "--data-dir", str(lap), input="y\n")
    assert left.exit_code == 0, left.output
    assert not (lap / "sync" / "state.json").exists() and head_of(folder, "laptop")["state"] == "left"


def test_the_demo_never_syncs(engine: FakeEngine, data_dir: Path) -> None:
    (data_dir / MARKER_NAME).write_text(json.dumps({"kind": "ordnung-demo", "version": "1"}))
    for command in (["sync"], ["sync", "status"], ["sync", "use-here"], ["sync", "save"]):
        result = invoke(*command, "--data-dir", str(data_dir))
        assert result.exit_code == 1 and sync.DEMO_MESSAGE in result.output, command


def test_serve_finishes_an_interrupted_take_over_first(
    engine: FakeEngine, data_dir: Path, folder: Path
) -> None:
    cli._finish_take_over(data_dir)
    assert engine.resumed == 0, "nothing to finish without a connection"
    assert invoke("sync", "connect", str(folder), "--data-dir", str(data_dir)).exit_code == 0
    before = engine.resumed
    cli._finish_take_over(data_dir)
    assert engine.resumed == before + 1

    def broken(paths: Paths) -> None:
        raise OSError("disk gone")

    engine.resume_interrupted = broken  # type: ignore[method-assign]
    cli._finish_take_over(data_dir)  # never raises: the server starts and shows the problem


def test_the_doctor_has_a_sync_row_only_while_connected(
    engine: FakeEngine, data_dir: Path, folder: Path
) -> None:
    assert "sync" not in {check.id for check in doctor.local_checks(data_dir)}
    assert (
        invoke("sync", "connect", str(folder), "--name", "desktop", "--data-dir", str(data_dir)).exit_code
        == 0
    )
    row = next(check for check in doctor.local_checks(data_dir) if check.id == "sync")
    assert row.status == "ok" and "desktop: in use here" in row.detail
    folder.rename(folder.parent / "elsewhere")
    row = next(check for check in doctor.local_checks(data_dir) if check.id == "sync")
    assert row.status == "warn" and "can't be reached" in row.detail


# --------------------------------------------------------------------------------------------------
# through a running server
# --------------------------------------------------------------------------------------------------


class _Server:
    """A running server's sync API as the command line sees it (records each request)."""

    def __init__(self, answers: dict[tuple[str, str], Any]) -> None:
        self.answers = answers
        self.requests: list[tuple[str, str, Any]] = []

    def __call__(self, info: ServerInfo, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        self.requests.append((method, path, dict(body) if body is not None else None))
        answer = self.answers[(method, path)]
        if isinstance(answer, list):
            answer = answer.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _status(**values: Any) -> dict[str, Any]:
    base = {
        "available": True,
        "connected": True,
        "mode": "in_use",
        "activity": "idle",
        "suggested_name": "desk",
        "this_computer": "desktop",
        "folder": "/sync",
        "computers": [],
    }
    return {**base, **values}


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch, engine: FakeEngine) -> Iterator[None]:
    info = ServerInfo(port=8765, token="t", pid=1, host="127.0.0.1", started_at="now", version="test")
    monkeypatch.setattr(cli, "reachable_server", lambda folder: info)
    yield


def test_commands_ask_a_running_server(server: None, monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> None:
    api = _Server(
        {
            ("POST", "/api/sync/use-here"): _status(mode="in_use"),
            ("POST", "/api/sync/save"): _status(mode="standing_by"),
            ("GET", "/api/sync"): _status(),
            ("DELETE", "/api/sync"): [sync.SyncError("not_received", "No other computer has it."), _status()],
        }
    )
    monkeypatch.setattr(cli, "_sync_api", api)
    assert "Ordnung is in use here now." in invoke("sync", "use-here", "--data-dir", str(data_dir)).output
    handed = invoke("sync", "save", "--hand-over", "--data-dir", str(data_dir))
    assert "Handed over" in handed.output
    left = invoke("sync", "disconnect", "--data-dir", str(data_dir), input="y\n")
    assert left.exit_code == 0, left.output
    assert api.requests == [
        ("POST", "/api/sync/use-here", {"older_copy": False}),
        ("POST", "/api/sync/save", {"hand_over": True}),
        ("DELETE", "/api/sync", {"forget_passphrase": True, "unreceived_ok": False}),
        ("DELETE", "/api/sync", {"forget_passphrase": True, "unreceived_ok": True}),
    ]


def test_a_refusal_from_the_server_is_one_line(
    server: None, monkeypatch: pytest.MonkeyPatch, data_dir: Path
) -> None:
    api = _Server({("POST", "/api/sync/use-here"): sync.SyncError("newer_ordnung", sync.NEWER_MESSAGE)})
    monkeypatch.setattr(cli, "_sync_api", api)
    result = invoke("sync", "use-here", "--data-dir", str(data_dir))
    assert result.exit_code == 1 and sync.NEWER_MESSAGE in result.output and "Traceback" not in result.output


# --------------------------------------------------------------------------------------------------
# restore
# --------------------------------------------------------------------------------------------------


def test_restoring_over_a_connected_folder_says_the_copy_isn_t_connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ordnung import backup as backups
    from ordnung.backup import KdfParams, archive

    fast = KdfParams(log2_n=10)
    monkeypatch.setattr(backups, "DEFAULT_KDF", fast)
    monkeypatch.setattr(archive, "DEFAULT_KDF", fast)
    monkeypatch.setattr(backups.write_backup_file, "__kwdefaults__", {"kdf": fast})
    monkeypatch.setenv("ORDNUNG_BACKUP_PASSPHRASE", "a long enough passphrase")
    source, target = tmp_path / "source", tmp_path / "target"
    Store.open(Paths(source)).close()
    backup = tmp_path / "x.ordnung-backup"
    backups.write_backup_file(source, backup, "a long enough passphrase")
    Store.open(Paths(target)).close()
    (target / "sync").mkdir()
    (target / "sync" / "state.json").write_text("{}")
    result = invoke("restore", str(backup), "--data-dir", str(target), "--force")
    assert result.exit_code == 0, result.output
    assert "isn't connected to sync" in result.output
    assert not (target / "sync").exists()
