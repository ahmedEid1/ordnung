"""Backup and restore of a whole data folder: byte-for-byte round trips with row counts, the restore
policy (free folders, --force moves aside, never under a running Ordnung, all or nothing), hostile
archives inside a validly encrypted file, and the ``ordnung backup`` / ``ordnung restore`` commands."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import tarfile
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from helpers_secretary import seed_ledger
from ordnung import backup as backups
from ordnung import clock
from ordnung.backup import archive
from ordnung.backup.archive import DB_NAME, MANIFEST_NAME, Manifest, ManifestFile, check_backup, write_backup
from ordnung.backup.container import (
    DamagedBackup,
    EncryptedWriter,
    KdfParams,
    NewerBackupFormat,
    NotABackup,
    WrongPassphrase,
)
from ordnung.backup.restore import TargetInUse, TargetNotFree, existing_data, restore_backup
from ordnung.cli import app
from ordnung.config import PACKAGE_DIR, Paths
from ordnung.db.migrate import latest_version
from ordnung.db.store import Store
from ordnung.locking import LOCK_NAME, DataDirLock

FAST = KdfParams(log2_n=10)
PASS = "a long enough passphrase"
STAMP = datetime(2026, 9, 28, 9, 30, 0)
runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


@pytest.fixture(autouse=True)
def fast_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every backup in these tests uses cheap scrypt settings (the header records them)."""
    monkeypatch.setattr(backups, "DEFAULT_KDF", FAST)
    monkeypatch.setattr(archive, "DEFAULT_KDF", FAST)
    monkeypatch.setattr(archive.write_backup, "__kwdefaults__", {"kdf": FAST, "created_at": None})
    monkeypatch.setattr(backups.write_backup_file, "__kwdefaults__", {"kdf": FAST})


@pytest.fixture
def life(tmp_path: Path) -> Path:
    """A data folder with a seeded ledger, originals, page images, a letter PDF and uncheckpointed WAL."""
    folder = tmp_path / "life"
    paths = Paths(folder).ensure()
    store = Store.open(paths)
    try:
        seed_ledger(store)
        (paths.files / "ab").mkdir()
        (paths.files / "ab" / "abcdef.pdf").write_bytes(b"%PDF-1.7\n" + os.urandom(20_000))
        (paths.files / "cd").mkdir()
        (paths.files / "cd" / "Mietvertrag Größe & Co.jpg").write_bytes(os.urandom(5_000))
        (paths.derived / "doc_1").mkdir()
        (paths.derived / "doc_1" / "page-1.jpg").write_bytes(os.urandom(3_000))
        (paths.derived / "doc_1" / "thumb.jpg").write_bytes(b"")
        (paths.drafts / "drf_1.pdf").write_bytes(b"%PDF-1.4 letter")
        # a row that is only in the WAL (no checkpoint): the snapshot must still carry it
        store.set_meta("written_last", "yes")
    finally:
        store.close()
    return folder


def file_digests(folder: Path) -> dict[str, str]:
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for sub in ("files", "derived", "drafts")
        for path in sorted((folder / sub).rglob("*"))
        if path.is_file()
    }


def row_counts(folder: Path) -> dict[str, int]:
    conn = sqlite3.connect(folder / DB_NAME)
    try:
        return archive.table_counts(conn)
    finally:
        conn.close()


def make_backup(folder: Path, out: Path, passphrase: str = PASS) -> Path:
    backups.write_backup_file(folder, out, passphrase, kdf=FAST)
    return out


# --------------------------------------------------------------------------------------------------
# round trips
# --------------------------------------------------------------------------------------------------


def test_round_trip_is_byte_for_byte_with_the_same_rows(life: Path, tmp_path: Path) -> None:
    before_files, before_rows = file_digests(life), row_counts(life)
    backup = make_backup(life, tmp_path / "b.ordnung-backup")
    result = restore_backup(backup, PASS, tmp_path / "restored")
    restored = result.target
    assert restored == tmp_path / "restored" and result.moved_aside is None
    assert file_digests(restored) == before_files
    assert row_counts(restored) == before_rows
    assert result.contents.manifest.tables == before_rows
    assert result.contents.files == len(before_files) == 5
    # the restored folder is a working Ordnung data folder
    store = Store.open(Paths(restored))
    try:
        assert store.get_meta("written_last") == "yes"
        assert store.get_profile().name == "Sam Rivera"
        assert len(store.list_items()) == before_rows["items"]
    finally:
        store.close()


def test_the_demo_life_round_trips(tmp_path: Path) -> None:
    demo = tmp_path / "demo"
    shutil.copytree(PACKAGE_DIR / "demo" / "demo_db", demo)
    backup = make_backup(demo, tmp_path / "demo.ordnung-backup")
    restored = restore_backup(backup, PASS, tmp_path / "back").target
    assert file_digests(restored) == file_digests(demo)
    assert row_counts(restored) == row_counts(demo)
    assert row_counts(restored)["documents"] > 20


def test_restored_files_and_folders_are_private(life: Path, tmp_path: Path) -> None:
    if os.name != "posix":
        pytest.skip("POSIX permissions")
    restored = restore_backup(make_backup(life, tmp_path / "b"), PASS, tmp_path / "r").target
    assert restored.stat().st_mode & 0o777 == 0o700
    for path in restored.rglob("*"):
        expected = 0o700 if path.is_dir() else 0o600
        assert path.stat().st_mode & 0o777 == expected, path
    assert not (restored / "ordnung.db-wal").exists()  # checking the database created nothing


def test_the_backup_file_is_private_and_holds_no_plaintext(life: Path, tmp_path: Path) -> None:
    backup = make_backup(life, tmp_path / "b.ordnung-backup")
    if os.name == "posix":
        assert backup.stat().st_mode & 0o777 == 0o600
    raw = backup.read_bytes()
    for needle in (b"Sam Rivera", b"SQLite format", b"%PDF", b"manifest", "Größe".encode()):
        assert needle not in raw
    assert not list(tmp_path.glob(".*.part"))


def test_symlinks_are_never_followed(life: Path, tmp_path: Path) -> None:
    secret = tmp_path / "outside.txt"
    secret.write_text("not Ordnung's")
    (life / "files" / "link.pdf").symlink_to(secret)
    (life / "derived" / "linked-folder").symlink_to(tmp_path)
    backup = make_backup(life, tmp_path / "b")
    contents = check_backup(backup, PASS)
    names = {entry.path for entry in contents.manifest.files}
    assert "files/link.pdf" not in names
    assert not any(name.startswith("derived/linked-folder") for name in names)


def test_runtime_files_and_the_watched_folder_stay_out(life: Path, tmp_path: Path) -> None:
    (life / "server.json").write_text('{"token": "secret"}')
    (life / LOCK_NAME).write_text("pid 1")
    (life / "inbox").mkdir()
    (life / "inbox" / "scan.pdf").write_bytes(b"%PDF")
    contents = check_backup(make_backup(life, tmp_path / "b"), PASS)
    names = {entry.path for entry in contents.manifest.files}
    assert all(name.split("/")[0] in ("files", "derived", "drafts") for name in names)


def test_the_manifest_describes_the_backup(life: Path) -> None:
    out = io.BytesIO()
    contents = write_backup(life, out, PASS, kdf=FAST, created_at="2026-09-28T07:30:00Z")
    manifest = contents.manifest
    assert manifest.format == 1 and manifest.app == "Ordnung"
    assert manifest.created_at == "2026-09-28T07:30:00Z"
    assert manifest.schema_version == latest_version()
    assert manifest.database.path == DB_NAME
    names = [entry.path for entry in manifest.files]
    # originals first, then page images, then letter PDFs; by name within each
    assert names == sorted(names, key=lambda name: (archive.FOLDERS.index(name.split("/")[0]), name))
    assert contents.letters == manifest.tables["documents"] > 0


def test_estimate_counts_files_and_the_database(life: Path) -> None:
    files, size = backups.estimate(life)
    assert files == 5
    assert (
        size
        == sum(p.stat().st_size for p in life.rglob("*") if p.is_file() and p.parent != life)
        + (life / DB_NAME).stat().st_size
    )


def test_a_folder_without_a_database_is_refused(tmp_path: Path) -> None:
    with pytest.raises(backups.BackupError, match="no Ordnung database"):
        write_backup(tmp_path, io.BytesIO(), PASS, kdf=FAST)


# --------------------------------------------------------------------------------------------------
# where a backup file goes
# --------------------------------------------------------------------------------------------------


def test_destination_policy(life: Path, tmp_path: Path) -> None:
    day = date(2026, 9, 28)
    assert backups.destination(life, tmp_path, day) == tmp_path / "ordnung-backup-2026-09-28.ordnung-backup"
    assert backups.destination(life, tmp_path / "mine.bak", day) == tmp_path / "mine.bak"
    with pytest.raises(backups.BackupError, match="inside the data folder"):
        backups.destination(life, life / "files", day)
    (tmp_path / "taken").write_bytes(b"")
    with pytest.raises(backups.BackupError, match="already exists"):
        backups.destination(life, tmp_path / "taken", day)
    with pytest.raises(backups.BackupError, match="doesn't exist"):
        backups.destination(life, tmp_path / "nowhere" / "b.bak", day)


@pytest.mark.parametrize("passphrase", ["", "short", "x" * 11, "x" * 1025])
def test_weak_or_huge_passphrases_are_refused_for_new_backups(
    life: Path, tmp_path: Path, passphrase: str
) -> None:
    with pytest.raises(backups.BackupError, match="passphrase"):
        backups.write_backup_file(life, tmp_path / "b", passphrase, kdf=FAST)
    assert not list(tmp_path.iterdir()) or list(tmp_path.iterdir()) == [life]


def test_a_failed_backup_leaves_no_file(life: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(backups, "write_backup", broken)
    with pytest.raises(OSError):
        backups.write_backup_file(life, tmp_path / "b", PASS, kdf=FAST)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["life"]


# --------------------------------------------------------------------------------------------------
# refusals on restore
# --------------------------------------------------------------------------------------------------


def test_a_wrong_passphrase_leaves_everything_as_it_was(life: Path, tmp_path: Path) -> None:
    backup = make_backup(life, tmp_path / "b")
    with pytest.raises(WrongPassphrase):
        restore_backup(backup, PASS + "!", tmp_path / "r")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["b", "life"]


def test_a_tampered_backup_is_refused_and_nothing_is_left_behind(life: Path, tmp_path: Path) -> None:
    backup = make_backup(life, tmp_path / "b")
    raw = bytearray(backup.read_bytes())
    raw[len(raw) // 2] ^= 0x10
    backup.write_bytes(bytes(raw))
    with pytest.raises(DamagedBackup):
        restore_backup(backup, PASS, tmp_path / "r")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["b", "life"]


def test_the_end_of_the_file_is_checked_after_the_archive_ends(life: Path, tmp_path: Path) -> None:
    """tar stops reading at its end marker; the last encrypted chunk must still be authenticated."""
    backup = make_backup(life, tmp_path / "b")
    raw = bytearray(backup.read_bytes())
    raw[-3] ^= 0x01  # inside the last chunk's tag
    backup.write_bytes(bytes(raw))
    with pytest.raises(DamagedBackup):
        check_backup(backup, PASS)
    backup.write_bytes(bytes(raw[:-1]))
    with pytest.raises(DamagedBackup):
        check_backup(backup, PASS)


def test_not_a_backup_and_a_newer_format(life: Path, tmp_path: Path) -> None:
    other = tmp_path / "letter.pdf"
    other.write_bytes(b"%PDF-1.7 not a backup")
    with pytest.raises(NotABackup):
        restore_backup(other, PASS, tmp_path / "r")
    backup = make_backup(life, tmp_path / "b")
    raw = bytearray(backup.read_bytes())
    raw[15] = 2
    backup.write_bytes(bytes(raw))
    with pytest.raises(NewerBackupFormat):
        restore_backup(backup, PASS, tmp_path / "r")
    assert not (tmp_path / "r").exists()


# --------------------------------------------------------------------------------------------------
# hostile archives inside a validly encrypted file (someone who knows the passphrase)
# --------------------------------------------------------------------------------------------------


def _member(
    name: str, data: bytes, kind: bytes = tarfile.REGTYPE, link: str = ""
) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(name)
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    info.type = kind
    info.linkname = link
    return info, data


def craft(path: Path, members: list[tuple[tarfile.TarInfo, bytes]], passphrase: str = PASS) -> Path:
    with path.open("wb") as out:
        writer = EncryptedWriter(out, passphrase, kdf=FAST)
        with tarfile.open(fileobj=writer, mode="w|", format=tarfile.PAX_FORMAT) as tar:  # type: ignore[call-overload]
            for info, data in members:
                tar.addfile(info, io.BytesIO(data) if info.isreg() else None)
        writer.close()
    return path


def _db_bytes(tmp_path: Path, schema: int | None = None) -> bytes:
    folder = tmp_path / "db-source"
    store = Store.open(Paths(folder))
    store.close()
    conn = sqlite3.connect(folder / DB_NAME)
    if schema is not None:
        conn.execute(f"PRAGMA user_version = {schema}")
        conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")  # a self-contained file, as Ordnung's snapshots are
    conn.close()
    return (folder / DB_NAME).read_bytes()


def _manifest(
    db: bytes, files: dict[str, bytes], *, tables: dict[str, int] | None = None, **extra: Any
) -> bytes:
    conn = sqlite3.connect(":memory:")
    conn.deserialize(db)
    counts = archive.table_counts(conn)
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    conn.close()

    def entry(name: str, data: bytes) -> ManifestFile:
        return ManifestFile(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())

    manifest = Manifest(
        format=1,
        app_version="0.1.0",
        created_at="2026-09-28T07:30:00Z",
        schema_version=version,
        database=entry(DB_NAME, db),
        tables=tables if tables is not None else counts,
        files=[entry(name, data) for name, data in files.items()],
    )
    return json.dumps(manifest.model_dump() | extra).encode()


def test_a_crafted_but_honest_archive_restores(tmp_path: Path) -> None:
    db = _db_bytes(tmp_path)
    files = {"files/aa/x.pdf": b"%PDF"}
    members = [
        _member(DB_NAME, db),
        *(_member(n, d) for n, d in files.items()),
        _member(MANIFEST_NAME, _manifest(db, files)),
    ]
    result = restore_backup(craft(tmp_path / "ok", members), PASS, tmp_path / "r")
    assert (result.target / "files" / "aa" / "x.pdf").read_bytes() == b"%PDF"


@pytest.mark.parametrize(
    "name",
    [
        "../evil.txt",
        "files/../../evil.txt",
        "/etc/evil",
        "files//x",
        "files/./x",
        "files",
        "other/x.txt",
        "files\\..\\evil",
        "C:/evil",
        "ordnung.db-wal",
        "server.json",
        ".ordnung.lock",
    ],
)
def test_names_outside_the_policy_are_refused(tmp_path: Path, name: str) -> None:
    db = _db_bytes(tmp_path)
    members = [
        _member(DB_NAME, db),
        _member(name, b"payload"),
        _member(MANIFEST_NAME, _manifest(db, {name: b"payload"})),
    ]
    with pytest.raises(DamagedBackup):
        restore_backup(craft(tmp_path / "evil", members), PASS, tmp_path / "r")
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path.parent / "evil.txt").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["db-source", "evil"]


@pytest.mark.parametrize(
    "kind",
    [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE],
)
def test_only_regular_files_are_restored(tmp_path: Path, kind: bytes) -> None:
    db = _db_bytes(tmp_path)
    members = [
        _member(DB_NAME, db),
        _member("files/x", b"", kind, link="/etc/passwd"),
        _member(MANIFEST_NAME, _manifest(db, {})),
    ]
    with pytest.raises(DamagedBackup):
        restore_backup(craft(tmp_path / "evil", members), PASS, tmp_path / "r")
    assert not (tmp_path / "r").exists()


def test_duplicates_extras_and_mismatches_are_refused(tmp_path: Path) -> None:
    db = _db_bytes(tmp_path)
    good = {"files/a.pdf": b"one"}
    cases = {
        "duplicate": [
            _member(DB_NAME, db),
            _member("files/a.pdf", b"one"),
            _member("files/a.pdf", b"one"),
            _member(MANIFEST_NAME, _manifest(db, good)),
        ],
        "extra file": [
            _member(DB_NAME, db),
            _member("files/a.pdf", b"one"),
            _member("files/b.pdf", b"two"),
            _member(MANIFEST_NAME, _manifest(db, good)),
        ],
        "missing file": [_member(DB_NAME, db), _member(MANIFEST_NAME, _manifest(db, good))],
        "changed file": [
            _member(DB_NAME, db),
            _member("files/a.pdf", b"ONE"),
            _member(MANIFEST_NAME, _manifest(db, good)),
        ],
        "no manifest": [_member(DB_NAME, db), _member("files/a.pdf", b"one")],
        "two manifests": [
            _member(DB_NAME, db),
            _member("files/a.pdf", b"one"),
            _member(MANIFEST_NAME, _manifest(db, good)),
            _member(MANIFEST_NAME, _manifest(db, good)),
        ],
        "no database": [_member("files/a.pdf", b"one"), _member(MANIFEST_NAME, _manifest(db, good))],
        "wrong row counts": [
            _member(DB_NAME, db),
            _member("files/a.pdf", b"one"),
            _member(MANIFEST_NAME, _manifest(db, good, tables={"items": 99})),
        ],
        "unknown manifest field": [
            _member(DB_NAME, db),
            _member("files/a.pdf", b"one"),
            _member(MANIFEST_NAME, _manifest(db, good, surprise=True)),
        ],
        "manifest not json": [
            _member(DB_NAME, db),
            _member("files/a.pdf", b"one"),
            _member(MANIFEST_NAME, b"{not json"),
        ],
        "not a database": [_member(DB_NAME, b"garbage" * 100), _member(MANIFEST_NAME, _manifest(db, {}))],
    }
    for label, members in cases.items():
        with pytest.raises(DamagedBackup):
            restore_backup(craft(tmp_path / f"{label}.b", members), PASS, tmp_path / "r")
        assert not (tmp_path / "r").exists(), label
        assert not [p for p in tmp_path.iterdir() if ".restoring-" in p.name], label


def test_a_damaged_database_is_refused(tmp_path: Path) -> None:
    db = bytearray(_db_bytes(tmp_path))
    db[4096 + 200 : 4096 + 400] = b"\xff" * 200  # scribble over a b-tree page
    members = [
        _member(DB_NAME, bytes(db)),
        _member(MANIFEST_NAME, _manifest(_db_bytes(tmp_path / "again"), {})),
    ]
    with pytest.raises(DamagedBackup):
        restore_backup(craft(tmp_path / "b", members), PASS, tmp_path / "r")


def test_a_newer_schema_or_archive_format_is_refused(tmp_path: Path) -> None:
    newer = _db_bytes(tmp_path, schema=latest_version() + 1)
    members = [_member(DB_NAME, newer), _member(MANIFEST_NAME, _manifest(newer, {}))]
    with pytest.raises(NewerBackupFormat, match="newer version of Ordnung"):
        restore_backup(craft(tmp_path / "b1", members), PASS, tmp_path / "r")
    db = _db_bytes(tmp_path / "second")
    members = [_member(DB_NAME, db), _member(MANIFEST_NAME, _manifest(db, {}, format=2))]
    with pytest.raises(NewerBackupFormat):
        restore_backup(craft(tmp_path / "b2", members), PASS, tmp_path / "r")
    assert not (tmp_path / "r").exists()


def test_check_backup_writes_nothing(life: Path, tmp_path: Path) -> None:
    backup = make_backup(life, tmp_path / "b")
    letters = row_counts(life)["documents"]
    before = sorted(p for p in tmp_path.rglob("*"))
    contents = check_backup(backup, PASS)
    assert contents.letters == letters
    assert sorted(p for p in tmp_path.rglob("*")) == before


# --------------------------------------------------------------------------------------------------
# where a restore goes
# --------------------------------------------------------------------------------------------------


def test_a_free_folder_is_used_without_force(life: Path, tmp_path: Path) -> None:
    target = Paths(tmp_path / "fresh").ensure().data_dir  # empty files/, derived/, drafts/
    (target / "inbox").mkdir()
    (target / LOCK_NAME).write_text("")
    assert existing_data(target) == []
    result = restore_backup(make_backup(life, tmp_path / "b"), PASS, target)
    assert result.moved_aside is None
    assert file_digests(target) == file_digests(life)


def test_existing_data_is_never_replaced_without_force(life: Path, tmp_path: Path) -> None:
    backup = make_backup(life, tmp_path / "b")
    target = tmp_path / "mine"
    target.mkdir()
    (target / "notes.txt").write_text("keep me")
    with pytest.raises(TargetNotFree, match="--force"):
        restore_backup(backup, PASS, target)
    assert sorted(p.name for p in target.iterdir()) == ["notes.txt"]
    assert not [p for p in tmp_path.iterdir() if ".restoring-" in p.name]
    # a folder that is Ordnung's but has one letter in files/ holds data too
    (tmp_path / "other" / "files").mkdir(parents=True)
    (tmp_path / "other" / "files" / "a.pdf").write_bytes(b"%PDF")
    assert existing_data(tmp_path / "other") == ["files"]


def test_force_moves_the_old_folder_aside(life: Path, tmp_path: Path) -> None:
    backup = make_backup(life, tmp_path / "b")
    target = tmp_path / "mine"
    target.mkdir()
    (target / "notes.txt").write_text("keep me")
    result = restore_backup(backup, PASS, target, force=True, now=lambda: STAMP)
    assert result.moved_aside == tmp_path / "mine.before-restore-20260928-093000"
    assert (result.moved_aside / "notes.txt").read_text() == "keep me"
    assert file_digests(target) == file_digests(life)
    again = restore_backup(backup, PASS, target, force=True, now=lambda: STAMP)
    assert again.moved_aside == tmp_path / "mine.before-restore-20260928-093000-2"
    assert row_counts(again.moved_aside) == row_counts(life)


def test_never_under_a_running_ordnung(life: Path, tmp_path: Path) -> None:
    backup = make_backup(life, tmp_path / "b")
    target = tmp_path / "busy"
    target.mkdir()
    with DataDirLock(target, purpose="ordnung serve"):
        for force in (False, True):
            with pytest.raises(TargetInUse, match="ordnung serve"):
                restore_backup(backup, PASS, target, force=force)
    assert sorted(p.name for p in target.iterdir()) == [LOCK_NAME]


def test_a_failed_swap_puts_the_old_folder_back(
    life: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backup = make_backup(life, tmp_path / "b")
    target = tmp_path / "mine"
    target.mkdir()
    (target / "notes.txt").write_text("keep me")
    real_rename = Path.rename

    def rename(self: Path, other: Any) -> Any:
        if ".restoring-" in self.name:
            raise OSError("rename failed")
        return real_rename(self, other)

    monkeypatch.setattr(Path, "rename", rename)
    with pytest.raises(OSError, match="rename failed"):
        restore_backup(backup, PASS, target, force=True, now=lambda: STAMP)
    assert (target / "notes.txt").read_text() == "keep me"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["b", "life", "mine"]


# --------------------------------------------------------------------------------------------------
# the commands
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def pinned_today() -> Iterator[None]:
    clock.set_today("2026-09-28")
    yield
    clock.set_today(None)


def invoke(*args: str, passphrase: str | None = PASS, **kwargs: Any) -> Any:
    env = {"ORDNUNG_BACKUP_PASSPHRASE": passphrase} if passphrase is not None else {}
    return runner.invoke(app, list(args), env=env, **kwargs)


def test_backup_and_restore_commands(life: Path, tmp_path: Path, pinned_today: None) -> None:
    result = invoke("backup", "--data-dir", str(life), "--to", str(tmp_path))
    assert result.exit_code == 0, result.output
    backup = tmp_path / "ordnung-backup-2026-09-28.ordnung-backup"
    assert backup.is_file()
    letters = row_counts(life)["documents"]
    assert "Saved an encrypted backup" in result.output and f"{letters} letters" in result.output
    assert "ordnung restore" in result.output and "not even you" in result.output

    checked = invoke("restore", str(backup), "--check")
    assert checked.exit_code == 0, checked.output
    assert "complete and opens with this passphrase" in checked.output

    restored = invoke("restore", str(backup), "--data-dir", str(tmp_path / "back"))
    assert restored.exit_code == 0, restored.output
    assert f"Restored {letters} letters" in restored.output
    assert file_digests(tmp_path / "back") == file_digests(life)


def test_backup_prompts_twice_for_a_new_passphrase(life: Path, tmp_path: Path, pinned_today: None) -> None:
    typed = f"too short\n{PASS}\n{PASS}x\n{PASS}\n{PASS}\n"  # too short, then two that differ, then right
    result = invoke("backup", "--data-dir", str(life), "--to", str(tmp_path), passphrase=None, input=typed)
    assert result.exit_code == 0, result.output
    assert "at least 12 characters" in result.output and "differ" in result.output
    assert PASS not in result.output
    assert (
        check_backup(tmp_path / "ordnung-backup-2026-09-28.ordnung-backup", PASS).letters
        == row_counts(life)["documents"]
    )


def test_backup_gives_up_after_three_tries(life: Path, tmp_path: Path, pinned_today: None) -> None:
    result = invoke(
        "backup", "--data-dir", str(life), "--to", str(tmp_path), passphrase=None, input="a\nb\nc\n"
    )
    assert result.exit_code == 1 and "No passphrase" in result.output
    assert not list(tmp_path.glob("*.ordnung-backup"))


def test_backup_refusals_are_explained(life: Path, tmp_path: Path, pinned_today: None) -> None:
    inside = invoke("backup", "--data-dir", str(life), "--to", str(life / "drafts"))
    assert inside.exit_code == 1 and "inside the data folder" in inside.output
    weak = invoke("backup", "--data-dir", str(life), "--to", str(tmp_path), passphrase="short")
    assert weak.exit_code == 1 and "at least 12 characters" in weak.output
    empty = invoke("backup", "--data-dir", str(tmp_path / "nothing"), "--to", str(tmp_path))
    assert empty.exit_code == 1 and "no Ordnung database" in empty.output
    assert not list(tmp_path.glob("*.ordnung-backup"))


def test_backup_while_ordnung_runs_reads_alongside_it(life: Path, tmp_path: Path, pinned_today: None) -> None:
    with DataDirLock(life, purpose="ordnung serve"):
        result = invoke("backup", "--data-dir", str(life), "--to", str(tmp_path))
    assert result.exit_code == 0, result.output
    assert "taken alongside it" in result.output


def test_restore_refuses_existing_data_before_asking_for_the_passphrase(life: Path, tmp_path: Path) -> None:
    backup = make_backup(life, tmp_path / "b.ordnung-backup")
    result = invoke("restore", str(backup), "--data-dir", str(life), passphrase=None, input="")
    assert result.exit_code == 1
    assert "already holds Ordnung data" in result.output and "--force" in result.output
    assert "Passphrase" not in result.output


def test_restore_explains_a_wrong_passphrase_and_other_files(life: Path, tmp_path: Path) -> None:
    backup = make_backup(life, tmp_path / "b.ordnung-backup")
    wrong = invoke("restore", str(backup), "--data-dir", str(tmp_path / "r"), passphrase="not the passphrase")
    assert wrong.exit_code == 1 and "Wrong passphrase" in wrong.output
    assert not (tmp_path / "r").exists()
    pdf = tmp_path / "letter.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    other = invoke("restore", str(pdf), passphrase=None, input="")
    assert other.exit_code == 1 and "not an Ordnung backup" in other.output
    missing = invoke("restore", str(tmp_path / "nope"), passphrase=None)
    assert missing.exit_code == 1 and "There is no file" in missing.output


def test_restore_force_says_where_the_old_data_went(life: Path, tmp_path: Path) -> None:
    backup = make_backup(life, tmp_path / "b.ordnung-backup")
    target = tmp_path / "mine"
    shutil.copytree(life, target)
    result = invoke("restore", str(backup), "--data-dir", str(target), "--force")
    assert result.exit_code == 0, result.output
    assert "moved aside first" in result.output and "before-restore-" in result.output
    aside = [p for p in tmp_path.iterdir() if p.name.startswith("mine.before-restore-")]
    assert len(aside) == 1 and file_digests(aside[0]) == file_digests(life)
