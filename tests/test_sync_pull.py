"""Pulling: stage, verify, keep, apply (design §11; F29, F31, F33, F38; review findings 10, 11c, 12, 18)."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from fakes import use_fast_keys
from ordnung.db.migrate import MIGRATIONS_DIR, latest_version, migrate
from ordnung.db.store import Store, person_write
from ordnung.sync import NewerSyncFolder, NotArrived, SyncError, SyncRefused
from ordnung.sync.crypto import sealed_size_of
from ordnung.sync.decide import Pull
from ordnung.sync.model import Bucket, BucketRef, FileEntry, Manifest, VersionRef
from ordnung.sync.push import buckets_of
from sync_harness import Computer


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)


@pytest.fixture
def pair(tmp_path: Path):  # type: ignore[no-untyped-def]
    a = Computer("anna-laptop", tmp_path / "a", tmp_path / "sync")
    b = Computer("desktop", tmp_path / "b", tmp_path / "sync")  # one folder: delivery is instant
    yield a, b
    a.close()
    b.close()


def joined(a: Computer, b: Computer) -> None:
    a.add_letter("Stadtwerke")
    a.connect()
    b.connect()
    a.round()  # a stands by now
    assert a.mode == "standing_by" and b.mode == "in_use"


def forge(a: Computer, **changes: Any) -> None:
    """Rewrite ``a``'s latest version with ``changes`` to its manifest, properly sealed (a buggy or
    hostile computer that holds the key)."""
    session = a.s
    base = session.state.base
    assert base is not None
    manifest = session.scanner.manifest(base.ref)
    assert manifest is not None
    entries: list[FileEntry] | None = changes.pop("entries", None)
    update: dict[str, Any] = dict(changes)
    if entries is not None:
        buckets = buckets_of(entries) if entries else []
        for _ref, content in buckets:
            name = session.vault.object_name("b", hashlib.sha256(content).hexdigest())
            sealed = session.vault.seal("b", name, content)
            session.folder.write_object(name, len(sealed), lambda out, s=sealed: out.write(s))
        update["buckets"] = [ref for ref, _content in buckets]
        update["files_count"] = len(entries)
    forged = manifest.model_copy(update=update)
    content = forged.model_dump_json().encode()
    sha = hashlib.sha256(content).hexdigest()
    name = session.vault.object_name("m", sha)
    sealed = session.vault.seal("m", name, content)
    session.folder.write_object(name, sealed_size_of(len(content)), lambda out: out.write(sealed))
    ref = VersionRef(
        id=base.ref.id,
        lineage=forged.lineage,
        digest=forged.digest,
        manifest=name,
        manifest_size=len(content),
        manifest_sha256=sha,
    )
    session.state.base = base.model_copy(update={"ref": ref})
    session.write_head(version=ref)


def test_stage_and_apply_bring_everything_over(pair) -> None:  # type: ignore[no-untyped-def]
    a, b = pair
    joined(a, b)
    letter = b.add_letter("Vodafone Rechnung")
    b.person_edit("a note on the desktop")
    b.round()
    outcome = a.use_here()
    assert isinstance(outcome.decision, Pull) and outcome.replaced
    assert letter in a.letters() and "a note on the desktop" in a.notes()
    for name in ("page-1.jpg", "thumb.jpg"):
        assert (a.paths.derived / letter / name).is_file()
    assert not (a.paths.data_dir / "sync" / "incoming").exists()
    assert not (a.paths.data_dir / "sync" / "pull.json").exists()


def test_apply_with_open_connections_and_a_reader_mid_transaction(pair) -> None:  # type: ignore[no-untyped-def]
    a, b = pair
    joined(a, b)
    b.person_edit("new there")
    b.round()
    import threading

    seen: list[int] = []

    def thread_reader() -> None:
        seen.append(len(a.db.list_activity(None)))

    worker = threading.Thread(target=thread_reader)
    worker.start()
    worker.join()
    reader = sqlite3.connect(f"{a.paths.db.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None)
    reader.execute("BEGIN")
    before = reader.execute("SELECT count(*) FROM notes").fetchone()[0]
    a.use_here()
    assert reader.execute("SELECT count(*) FROM notes").fetchone()[0] == before  # its snapshot holds
    reader.execute("ROLLBACK")
    assert reader.execute("SELECT count(*) FROM notes").fetchone()[0] == before + 1
    assert reader.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    reader.close()
    assert "new there" in a.notes()


def test_prune_removes_only_what_nothing_names(pair) -> None:  # type: ignore[no-untyped-def]
    a, b = pair
    joined(a, b)
    gone = next(iter(b.letters()))
    b.delete_letter(gone)
    kept = b.add_letter("stays")
    b.round()
    stray = a.paths.files / "zz" / "not-a-letter.txt"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("the person's own file in Ordnung's folder")
    a.use_here()
    assert not (a.paths.derived / gone).exists()
    assert (a.paths.derived / kept / "page-1.jpg").exists()
    assert not stray.exists()  # in neither the version nor the database
    referenced = {row[0] for row in a.db._conn().execute("SELECT file_path FROM documents")}
    assert all((a.paths.data_dir / p).is_file() for p in referenced)


def test_rule_k_a_quiet_pull_that_removes_letters_keeps_a_copy(pair) -> None:  # finding 18
    a, b = pair
    joined(a, b)
    b.delete_letter(next(iter(b.letters())))
    b.round()
    outcome = a.use_here()
    assert outcome.kept is not None and (a.s.local.kept_dir / outcome.kept.name).is_file()


def test_hostile_manifests_are_refused(pair) -> None:  # type: ignore[no-untyped-def]  # F33
    a, b = pair
    joined(a, b)
    b.round()
    for bad in ("../outside.pdf", "files/../../x", "/etc/passwd", "inbox/x.pdf", "files/a\x00b", "sync/state.json"):
        forge(b, entries=[FileEntry(path=bad, sha256="0" * 64, size=1)])
        with pytest.raises(SyncError):
            a.s.stage(a.s.scan().by_computer(b.s.state.computer))  # type: ignore[arg-type]
        assert not (a.paths.data_dir / "outside.pdf").exists()
        assert not (a.paths.data_dir / "sync" / "incoming").exists()


def test_a_newer_schema_is_refused(pair) -> None:  # type: ignore[no-untyped-def]  # F31
    a, b = pair
    joined(a, b)
    forge(b, schema_version=latest_version() + 1)
    with pytest.raises((NewerSyncFolder, NotArrived)):
        a.s.stage(a.s.scan().by_computer(b.s.state.computer))  # type: ignore[arg-type]


def test_an_older_schema_is_migrated_in_staging(pair, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    a, b = pair
    joined(a, b)
    old = tmp_path / "old-migrations"
    old.mkdir()
    for path in sorted(MIGRATIONS_DIR.glob("*.sql"))[:-1]:
        shutil.copy(path, old / path.name)
    b.close()
    b.paths.db.unlink()
    for suffix in ("-wal", "-shm"):
        Path(str(b.paths.db) + suffix).unlink(missing_ok=True)
    conn = sqlite3.connect(b.paths.db, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    assert migrate(conn, directory=old) == latest_version() - 1
    conn.execute("INSERT INTO notes (id, text, item_ids, created_at) VALUES ('n1', 'old note', '[]', 'x')")
    conn.execute("INSERT INTO meta (key, value) VALUES ('sync_person', '99')")
    conn.close()
    pushed = b.s.push(None)
    assert pushed.outcome == "pushed"
    outcome = a.use_here()
    assert outcome.replaced and "old note" in a.notes()
    assert int(a.db._conn().execute("PRAGMA user_version").fetchone()[0]) == latest_version()


def test_a_page_size_mismatch_is_made_right_in_staging(tmp_path: Path) -> None:
    big = tmp_path / "b" / "data"
    big.mkdir(parents=True)
    conn = sqlite3.connect(big / "ordnung.db")
    conn.execute("PRAGMA page_size=8192")
    conn.execute("VACUUM")
    conn.close()
    a = Computer("a", tmp_path / "a", tmp_path / "sync")
    b = Computer("b", tmp_path / "b", tmp_path / "sync")
    try:
        assert b.db._conn().execute("PRAGMA page_size").fetchone()[0] == 8192
        b.add_letter("big pages")
        b.connect()
        result = a.connect()
        assert result.connected and len(a.letters()) == 1
        assert a.db._conn().execute("PRAGMA page_size").fetchone()[0] == 4096
    finally:
        a.close()
        b.close()


def test_a_demo_database_arriving_is_refused(pair, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]  # F38
    a, b = pair
    joined(a, b)
    from ordnung.sync import push as push_module

    b.db.save_settings(b.db.get_settings().model_copy(update={"demo": True}))
    monkeypatch.setattr(push_module, "is_demo", lambda conn: False)  # a broken pusher
    b.s.push(b.db)
    monkeypatch.undo()
    use_fast_keys(monkeypatch)
    with pytest.raises(SyncRefused):
        a.s.stage(a.s.scan().by_computer(b.s.state.computer))  # type: ignore[arg-type]


def test_no_space_is_checked_before_staging(pair, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]  # F29, finding 12
    a, b = pair
    joined(a, b)
    b.person_edit("x")
    b.round()
    from ordnung.sync import pull

    class Usage:
        free = 10

    monkeypatch.setattr(pull.shutil, "disk_usage", lambda _p: Usage())
    with pytest.raises(SyncError) as refused:
        a.use_here()
    assert refused.value.kind == "no_space" and "free" in str(refused.value)
    assert "x" not in a.notes()


def test_a_damaged_local_file_is_replaced_not_trusted(pair) -> None:  # type: ignore[no-untyped-def]  # finding 11c
    a, b = pair
    joined(a, b)
    letter = next(iter(a.letters()))
    page = a.paths.derived / letter / "page-1.jpg"
    page.write_bytes(b"\xff\xd8" + b"0" * (page.stat().st_size - 2))  # same size, rotten
    b.person_edit("anything")
    b.round()
    a.use_here()
    assert page.read_bytes() == (b.paths.derived / letter / "page-1.jpg").read_bytes()


def test_a_write_after_the_decision_gives_the_pull_up(pair, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]  # blocker 1
    a, b = pair
    joined(a, b)
    b.person_edit("from b")
    b.round()
    from ordnung.sync import engine as engine_module

    real = engine_module.Session.keep_local

    def write_meanwhile(self, why: str, *, digest: str | None = None):  # type: ignore[no-untyped-def]
        with person_write():
            a.db.add_note("written while the pull was decided")
        return real(self, why, digest=digest)

    monkeypatch.setattr(engine_module.Session, "keep_local", write_meanwhile)
    b.delete_letter(next(iter(b.letters())))  # so the pull keeps a copy first (Rule K)
    b.round()
    with pytest.raises(SyncError):
        a.use_here()
    assert "written while the pull was decided" in a.notes()  # never lost
    assert not (a.paths.data_dir / "sync" / "pull.json").exists()
