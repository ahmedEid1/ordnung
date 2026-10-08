"""The sync folder on disk (design §4.1, §4.8-4.9, §13.2-13.4; I7, I9; F16, F26-F28; review findings 6, 22,
34)."""

from __future__ import annotations

import errno
import io
import os
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

import pytest

from fakes import use_fast_keys
from ordnung.config import Paths
from ordnung.models import AppSettings
from ordnung.sync import KEY_FILE_RE, SyncError
from ordnung.sync.folder import (
    MAX_STUCK,
    FileInfo,
    FolderUnreachable,
    RealFs,
    SyncFolder,
    TimedFs,
    data_folder_synced,
    folder_problem,
    inspect,
    online_only,
)
from sync_faults import HangingFs
from sync_harness import PASSPHRASE, Computer


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)


@pytest.fixture
def anna(tmp_path: Path):  # type: ignore[no-untyped-def]
    computer = Computer("anna-laptop", tmp_path / "a", tmp_path / "Nextcloud" / "Ordnung")
    (tmp_path / "Nextcloud").mkdir()
    yield computer
    computer.close()


# --------------------------------------------------------------------------------------------------
# choosing the folder
# --------------------------------------------------------------------------------------------------


def test_folder_rules(tmp_path: Path, paths: Paths) -> None:
    assert folder_problem("relative/path", paths) is not None
    assert folder_problem("/", paths) is not None
    assert folder_problem(str(Path.home()), paths) is not None
    assert folder_problem(str(paths.data_dir), paths) is not None
    assert folder_problem(str(paths.data_dir / "files" / "x"), paths) is not None
    assert folder_problem(str(paths.data_dir.parent), paths) is not None
    watched = tmp_path / "Scans"
    watched.mkdir()
    settings = AppSettings(inbox_dir=str(watched))
    assert folder_problem(str(watched / "sub"), paths, settings) is not None
    assert folder_problem(str(tmp_path / "missing" / "Ordnung"), paths) is not None
    afile = tmp_path / "file.txt"
    afile.write_text("x")
    assert folder_problem(str(afile), paths) is not None
    busy = tmp_path / "busy"
    busy.mkdir()
    for name in ("tax 2025.pdf", "b.txt", "c.txt", "d.txt", "e.txt"):
        (busy / name).write_text("x")
    problem = folder_problem(str(busy), paths)
    assert problem is not None and "“b.txt” and 4 more" in problem
    info = inspect(str(busy), paths)
    assert info.kind == "refused" and len(info.examples) == 3
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    for name in (".stfolder", "desktop.ini", ".DS_Store", ".dropbox"):
        (fresh / name).write_text("")
    assert folder_problem(str(fresh), paths) is None
    assert inspect(str(fresh), paths).kind == "new"
    assert inspect(str(tmp_path / "not-yet"), paths).kind == "new"


def test_a_folder_that_cant_be_written_is_refused(tmp_path: Path, paths: Paths) -> None:
    if os.geteuid() == 0:
        pytest.skip("root writes anywhere")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        assert "can't write" in (folder_problem(str(locked), paths) or "")
    finally:
        locked.chmod(0o700)


def test_the_data_folder_inside_a_synced_folder_is_a_warning(tmp_path: Path) -> None:
    synced = tmp_path / "Dropbox" / "stuff" / "data"
    synced.mkdir(parents=True)
    assert data_folder_synced(synced)
    marked = tmp_path / "plain" / "data"
    marked.mkdir(parents=True)
    assert not data_folder_synced(marked)
    (tmp_path / "plain" / ".stfolder").mkdir()
    assert data_folder_synced(marked)
    info = inspect(str(tmp_path / "Sync"), Paths(synced).ensure())
    assert info.kind == "new" and info.data_folder_synced


# --------------------------------------------------------------------------------------------------
# writing and reading
# --------------------------------------------------------------------------------------------------


def test_names_in_the_folder_follow_the_patterns(anna: Computer) -> None:
    anna.add_letter("x")
    anna.connect()
    root = anna.folder
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if path.is_dir():
            assert rel.name in ("h", "o") or (rel.parts[0] == "o" and len(rel.name) == 2), rel
            continue
        if len(rel.parts) == 1:
            assert KEY_FILE_RE.match(rel.name)
        elif rel.parts[0] == "h":
            assert len(rel.name) == 32
        else:
            assert len(rel.parts[1]) == 2 and len(rel.name) == 30
        assert os.stat(path).st_mode & 0o077 == 0


def test_own_temp_files_go_foreign_names_stay(anna: Computer) -> None:  # I7, I9, F16
    anna.connect()
    tag = anna.s.folder.tag
    mine = anna.folder / "o" / f".{tag}deadbeef.tmp"
    mine.parent.mkdir(exist_ok=True)
    mine.write_bytes(b"cut short")
    theirs = anna.folder / "h" / ".0123456789abcdef.tmp"
    theirs.write_bytes(b"another computer's")
    foreign = [
        anna.folder / "notes.txt",
        anna.folder / ".stfolder",
        anna.folder / "desktop.ini",
        anna.folder / "h" / "x (conflicted copy 2026-10-07)",
        anna.folder / "o" / "zz" / "not-ours.icloud",
    ]
    for path in foreign:
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text("keep me")
    anna.person_edit("push")
    anna.round()
    anna.s.state.last_gc_at = None
    for _ in range(10):
        anna.clock.advance(86_400)
        anna.s.tick()
    anna.s.gc()
    assert not mine.exists() and theirs.exists()
    for path in foreign:
        assert path.read_text() == "keep me"


def test_a_missing_folder_is_never_recreated(anna: Computer) -> None:  # F26
    anna.connect()
    moved = anna.folder.with_name("elsewhere")
    anna.folder.rename(moved)
    anna.person_edit("waits locally")
    outcome = anna.round()
    assert not anna.folder.exists()
    assert getattr(outcome.decision, "problem", None) is not None
    assert outcome.decision.problem.code == "folder_missing"  # type: ignore[attr-defined]


def test_an_emptied_folder_is_filled_again_only_when_asked(anna: Computer) -> None:  # F27
    anna.add_letter("x")
    anna.connect()
    for entry in list(anna.folder.iterdir()):
        if entry.is_dir():
            import shutil

            shutil.rmtree(entry)
        else:
            entry.unlink()
    outcome = anna.round()
    assert outcome.decision.problem.code == "folder_empty"  # type: ignore[attr-defined]
    assert not any(anna.folder.iterdir())
    anna.s.refill(anna.db)
    view = anna.s.scan()
    assert view.problem is None and anna.s.scanner.completeness(anna.s.state.base.ref, {}).ready  # type: ignore[union-attr]
    assert (anna.folder / anna.s.state.key_file).read_bytes().hex() == anna.s.state.key_file_bytes


def test_two_key_files_are_found(tmp_path: Path) -> None:  # F28
    a = Computer("a", tmp_path / "a", tmp_path / "sync")
    b = Computer("b", tmp_path / "b", tmp_path / "b-sync")
    try:
        a.connect()
        b.connect()
        keys = [p for p in (tmp_path / "b-sync").iterdir() if KEY_FILE_RE.match(p.name)]
        (tmp_path / "sync" / keys[0].name).write_bytes(keys[0].read_bytes())
        view = a.s.scan()
        assert view.other_key_file == keys[0].name
        info = inspect(str(tmp_path / "sync"), a.paths)
        assert info.kind == "refused" and "two separate" in (info.problem or "")
    finally:
        a.close()
        b.close()


def test_an_interrupted_setup_can_be_retried_with_another_passphrase(
    anna: Computer, monkeypatch: pytest.MonkeyPatch
) -> None:  # finding 34
    from ordnung.sync import engine as engine_module

    def crash(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("power cut while connecting")

    monkeypatch.setattr(engine_module.Session, "push", crash)
    with pytest.raises(RuntimeError):
        anna.connect()
    monkeypatch.undo()
    use_fast_keys(monkeypatch)
    assert any(KEY_FILE_RE.match(p.name) for p in anna.folder.iterdir())
    other = "lantern pebble violin harbor quiet"
    result = anna.connect(other)
    assert result.connected and result.created
    keys = [p for p in anna.folder.iterdir() if KEY_FILE_RE.match(p.name)]
    assert len(keys) == 1


def test_wrong_passphrase_when_joining(tmp_path: Path) -> None:  # F24
    a = Computer("a", tmp_path / "a", tmp_path / "sync")
    b = Computer("b", tmp_path / "b", tmp_path / "sync")
    try:
        a.connect()
        with pytest.raises(SyncError) as refused:
            b.connect("orbit velvet canyon maple thundeR")
        assert refused.value.kind == "wrong_passphrase"
        assert not (b.paths.data_dir / "sync" / "state.json").exists()
        assert b.secrets.saved == {}
    finally:
        a.close()
        b.close()


def test_a_weak_passphrase_for_a_new_folder(anna: Computer) -> None:  # finding 17
    with pytest.raises(SyncError) as refused:
        anna.connect("correct horse battery staple")
    assert refused.value.kind == "passphrase"
    assert not (anna.paths.data_dir / "sync" / "state.json").exists()
    assert PASSPHRASE not in str(refused.value)


# --------------------------------------------------------------------------------------------------
# what has arrived; what hangs
# --------------------------------------------------------------------------------------------------


def test_online_only_files_have_not_arrived() -> None:  # finding 6
    class Info:
        st_flags = 0x40000000
        st_file_attributes = 0

    assert online_only(Info())  # type: ignore[arg-type]
    Info.st_flags = 0
    Info.st_file_attributes = 0x400000
    assert online_only(Info())  # type: ignore[arg-type]
    Info.st_file_attributes = 0
    assert not online_only(Info())  # type: ignore[arg-type]


def test_an_icloud_placeholder_sibling_is_online_only(tmp_path: Path) -> None:
    folder = SyncFolder(tmp_path)
    shard = tmp_path / "o" / "ab"
    shard.mkdir(parents=True)
    name = "ab" + "c" * 30
    (shard / f".{'c' * 30}.icloud").write_bytes(b"bplist")
    info = folder.object_info(name)
    assert info == FileInfo(0, 0, 0, 0, True)
    assert folder.shard("ab")[name].online_only


def _folder_threads() -> int:
    return sum(thread.name == "ordnung-sync-folder" for thread in threading.enumerate())


def _problem_once_answered(computer: Computer) -> object:
    """A round's problem once the hung call returned (it ends on its own thread a moment after release)."""
    deadline = time.monotonic() + 2
    while True:
        found = getattr(computer.round().decision, "problem", None)
        if found is None or time.monotonic() > deadline:
            return found
        time.sleep(0.01)


def test_a_hung_folder_operation_gives_up(tmp_path: Path) -> None:  # finding 22
    hanging = HangingFs(hang=("stat",))
    timed = TimedFs(hanging, timeout=0.2)
    folder = SyncFolder(tmp_path, timed)
    started = time.monotonic()
    with pytest.raises(FolderUnreachable):
        folder.is_dir()
    assert time.monotonic() - started < 2
    hanging.release()
    deadline = time.monotonic() + 2
    while True:  # once the hung call returns, its thread answers again
        try:
            assert folder.is_dir()
            break
        except FolderUnreachable:
            assert time.monotonic() < deadline
            time.sleep(0.01)


def test_a_hung_folder_pauses_with_a_problem(anna: Computer) -> None:
    anna.connect()
    hanging = HangingFs(hang=("listdir", "stat"))
    anna.s.folder.fs = TimedFs(hanging, timeout=0.2)
    anna.s.scanner.folder = anna.s.folder
    try:
        outcome = anna.round()
        assert outcome.decision.problem.code == "folder_unreachable"  # type: ignore[attr-defined]
    finally:
        hanging.release()
    threading.Event().wait(0.05)


def test_a_hung_folder_leaves_few_threads_behind_however_often_it_is_read(anna: Computer) -> None:
    """Audit: every look at a hung folder used to leave one more thread stuck in it. A path whose call
    hangs is unreachable at once, at most MAX_STUCK calls hang, and once they return their threads go."""
    anna.connect()
    hanging = HangingFs(hang=("listdir", "stat"))
    anna.s.folder.fs = TimedFs(hanging, timeout=0.2)
    anna.s.scanner.folder = anna.s.folder
    before = _folder_threads()
    try:
        for _ in range(10):
            started = time.monotonic()
            outcome = anna.round()
            assert outcome.decision.problem.code == "folder_unreachable"  # type: ignore[attr-defined]
        assert time.monotonic() - started < 0.2, "unreachable at once, without waiting for a timeout"
        assert _folder_threads() <= before + MAX_STUCK
    finally:
        hanging.release()
    assert _problem_once_answered(anna) is None
    deadline = time.monotonic() + 2
    while _folder_threads() > before + 1:  # a released thread takes the next call, or ends
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_one_hung_file_holds_up_only_calls_on_that_file(tmp_path: Path) -> None:
    """Review: one read that hangs (an online-only file the provider doesn't bring) stopped every later
    call, this computer's own saves included. Calls on that file give up at once; others go on."""
    stalled = tmp_path / "stalled"
    stalled.write_bytes(b"x")
    hanging = HangingFs(hang=("open_read",), paths=[stalled])
    timed = TimedFs(hanging, timeout=0.2)
    before = _folder_threads()
    try:
        with pytest.raises(FolderUnreachable):
            timed.open_read(stalled)
        for _ in range(5):
            started = time.monotonic()
            with pytest.raises(FolderUnreachable):
                timed.open_read(stalled)
            assert time.monotonic() - started < 0.2, "the same file gives up at once"
        with timed.open_new(tmp_path / "saved") as handle:
            handle.write(b"saved")
            timed.fsync(handle)
        assert (tmp_path / "saved").read_bytes() == b"saved"
        assert _folder_threads() <= before + 2  # the hung call's, and the one that goes on
    finally:
        hanging.release()


def test_a_handle_left_behind_by_a_hung_call_doesn_t_hold_up_the_next_call(tmp_path: Path) -> None:
    """Review: a temp file's fsync hangs on a dead share and its handle is given up with bytes still
    buffered. Once the fsync returns, the handle's last flush must not run in front of the next call."""
    returned = threading.Event()

    class DeadShare(io.RawIOBase):
        writes = 0

        def writable(self) -> bool:
            return True

        def write(self, data: Any) -> int:
            DeadShare.writes += 1
            if DeadShare.writes == 1:
                returned.wait()  # hangs past the deadline, then the share fails
                raise OSError(errno.EIO, "I/O error")
            time.sleep(1.0)  # the given-up handle's last flush hangs too
            return len(data)

    class Fs(RealFs):
        def open_new(self, path: Path) -> BinaryIO:
            return io.BufferedWriter(DeadShare())  # type: ignore[return-value]

        def fsync(self, handle: BinaryIO) -> None:
            handle.flush()

    timed = TimedFs(Fs(), timeout=0.2)
    handle = timed.open_new(tmp_path / ".temp")
    handle.write(b"sealed head")
    with pytest.raises(FolderUnreachable):
        timed.fsync(handle)
    with pytest.raises(FolderUnreachable):
        handle.close()  # its path is stuck: given up at once
    del handle
    returned.set()
    time.sleep(0.05)
    started = time.monotonic()
    assert timed.stat(tmp_path).st_mode
    assert time.monotonic() - started < 0.2


def test_calls_hung_on_many_files_hold_a_bounded_number_of_threads(tmp_path: Path) -> None:
    hanging = HangingFs(hang=("stat",))
    timed = TimedFs(hanging, timeout=0.05)
    before = _folder_threads()
    try:
        for n in range(MAX_STUCK + 5):
            with pytest.raises(FolderUnreachable):
                timed.stat(tmp_path / f"file-{n}")
        assert _folder_threads() <= before + MAX_STUCK
    finally:
        hanging.release()


def test_sync_error_kinds_have_statuses() -> None:
    error = SyncError("no_space", "x")
    assert error.status == 507 and error.body() == {"detail": "x", "code": "no_space"}
