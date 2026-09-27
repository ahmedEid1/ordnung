"""What goes into a backup and how it comes out again: a tar archive inside the encrypted container.

Written policy (ADR 0007):

* **Contents.** ``ordnung.db`` — a consistent snapshot taken with SQLite's online backup
  (:func:`snapshot_database`: one read transaction, so a server writing at the same time can't tear
  it; the WAL is folded in) — then every regular file under ``files/`` (the originals),
  ``derived/`` (page images, thumbnails) and ``drafts/`` (letter PDFs), in path order, and last
  ``manifest.json``: the format, the app and schema versions, the row count of every table and the
  size and SHA-256 of every file and of the database. Nothing else: not the lock, ``server.json``
  or the watched folder (its files are the person's own copies; what Ordnung took from it is in
  ``files/``). Symbolic links are never followed.
* **Plaintext never touches the disk.** The database snapshot is made in memory; the archive is
  encrypted as it is written. Each file is read whole (at most one file in memory at a time), so a
  file changed while it is read is in the backup either before or after the change, never torn. A
  file deleted while the backup runs is left out (the database snapshot is exact; files follow it
  as closely as a running app allows — a backup taken while Ordnung is closed is exact).
* **Restore trusts nothing until it is proven.** Entries are written into a staging folder only:
  regular files whose names are ``ordnung.db``, ``manifest.json`` or a plain relative path under
  one of the three folders (no ``..``, no absolute or empty parts, no backslashes, no duplicates);
  anything else refuses the backup. The whole encrypted file is read to its authenticated end even
  after the archive's end marker, then every file must match the manifest (no file missing, none
  extra, sizes and hashes equal), the database must pass ``PRAGMA integrity_check``, its schema
  must not be newer than this Ordnung's, and its row counts must equal the manifest's.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import sqlite3
import stat
import tarfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, BinaryIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ordnung import __version__
from ordnung.backup.container import (
    DEFAULT_KDF,
    BackupError,
    DamagedBackup,
    EncryptedReader,
    EncryptedWriter,
    KdfParams,
    NewerBackupFormat,
)
from ordnung.clock import real_now_iso
from ordnung.db.migrate import latest_version

DB_NAME = "ordnung.db"
MANIFEST_NAME = "manifest.json"
#: The folders of a data directory that a backup carries (originals, page images, letter PDFs).
FOLDERS = ("files", "derived", "drafts")
ARCHIVE_FORMAT = 1
MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_NAME_CHARS = 1024
PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700
#: SQLite header bytes 18 and 19: file format write and read versions (1 rollback journal, 2 WAL).
_FILE_FORMAT_BYTES = (18, 19)
_ROLLBACK_FORMAT, _WAL_FORMAT = 1, 2


class ManifestFile(BaseModel):
    """One file of the backup as the manifest records it."""

    model_config = ConfigDict(extra="forbid")

    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(BaseModel):
    """``manifest.json``: what the backup holds, written last and checked on restore."""

    model_config = ConfigDict(extra="forbid")

    format: int
    app: str = "Ordnung"
    app_version: str
    created_at: str
    schema_version: int
    database: ManifestFile
    tables: dict[str, int]
    files: list[ManifestFile]


@dataclass(frozen=True)
class BackupContents:
    """What a finished (or restored) backup holds."""

    manifest: Manifest

    @property
    def letters(self) -> int:
        return self.manifest.tables.get("documents", 0)

    @property
    def files(self) -> int:
        return len(self.manifest.files)

    @property
    def file_bytes(self) -> int:
        return sum(entry.size for entry in self.manifest.files)

    @property
    def total_bytes(self) -> int:
        return self.file_bytes + self.manifest.database.size


@dataclass
class _Snapshot:
    data: bytes
    schema_version: int
    tables: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------------------------------
# the database snapshot
# --------------------------------------------------------------------------------------------------


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Rows per ordinary table (virtual tables are counted through their shadow tables)."""
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "AND upper(coalesce(sql, '')) NOT LIKE 'CREATE VIRTUAL%' ORDER BY name"
        )
    ]
    return {name: int(conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]) for name in names}


def snapshot_database(db_path: Path) -> _Snapshot:
    """A consistent copy of the database, in memory (opened read-only; the WAL is folded in)."""
    if not db_path.is_file():
        raise BackupError(f"There is no Ordnung database in {db_path.parent}.")
    source = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    copy = sqlite3.connect(":memory:")
    try:
        source.backup(copy)
        version = int(copy.execute("PRAGMA user_version").fetchone()[0])
        data = bytearray(copy.serialize())
        tables = table_counts(copy)
    finally:
        copy.close()
        source.close()
    # a self-contained file: marked as a rollback-journal database, as `journal_mode=DELETE` would
    # leave it (the copy has no WAL); Ordnung switches it back to WAL when it opens it
    if len(data) > _FILE_FORMAT_BYTES[1] and data[_FILE_FORMAT_BYTES[0]] == _WAL_FORMAT:
        for offset in _FILE_FORMAT_BYTES:
            data[offset] = _ROLLBACK_FORMAT
    return _Snapshot(data=bytes(data), schema_version=version, tables=tables)


# --------------------------------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------------------------------


def iter_data_files(data_dir: Path) -> Iterator[tuple[str, Path]]:
    """``(archive name, path)`` of every regular file under the backed-up folders, in name order.

    Symbolic links (to files or folders) are skipped, never followed.
    """
    for folder in FOLDERS:
        root = data_dir / folder
        if not root.is_dir() or root.is_symlink():
            continue
        found: list[tuple[str, Path]] = []
        for current, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(current) / name).is_symlink()]
            for name in names:
                path = Path(current) / name
                with contextlib.suppress(OSError):
                    if stat.S_ISREG(path.lstat().st_mode):
                        found.append((path.relative_to(data_dir).as_posix(), path))
        yield from sorted(found)


def _tar_info(name: str, size: int, mtime: float) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mtime = int(mtime)
    info.mode = PRIVATE_FILE_MODE
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def _add(tar: tarfile.TarFile, name: str, data: bytes, mtime: float) -> ManifestFile:
    tar.addfile(_tar_info(name, len(data), mtime), io.BytesIO(data))
    return ManifestFile(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())


def write_backup(
    data_dir: Path,
    out: BinaryIO,
    passphrase: str,
    *,
    kdf: KdfParams = DEFAULT_KDF,
    created_at: str | None = None,
) -> BackupContents:
    """Write an encrypted backup of ``data_dir`` to ``out`` (see the module policy).

    If anything fails, the last chunk is never sealed, so what was written reads as incomplete.
    """
    snapshot = snapshot_database(data_dir / DB_NAME)
    stamp = created_at or real_now_iso()
    writer = EncryptedWriter(out, passphrase, kdf=kdf)
    try:
        with tarfile.open(fileobj=writer, mode="w|", format=tarfile.PAX_FORMAT) as tar:
            database = _add(tar, DB_NAME, snapshot.data, time.time())
            entries: list[ManifestFile] = []
            for name, path in iter_data_files(data_dir):
                try:
                    data, mtime = path.read_bytes(), path.stat().st_mtime
                except FileNotFoundError:
                    continue  # deleted while the backup ran
                entries.append(_add(tar, name, data, mtime))
            manifest = Manifest(
                format=ARCHIVE_FORMAT,
                app_version=__version__,
                created_at=stamp,
                schema_version=snapshot.schema_version,
                database=database,
                tables=snapshot.tables,
                files=entries,
            )
            text = manifest.model_dump_json(indent=2).encode("utf-8")
            tar.addfile(_tar_info(MANIFEST_NAME, len(text), time.time()), io.BytesIO(text))
    except BaseException:
        writer.abort()
        raise
    writer.close()
    return BackupContents(manifest)


def estimate(data_dir: Path) -> tuple[int, int]:
    """``(files, bytes)`` a backup of ``data_dir`` would hold now (database included in the bytes)."""
    total, count = 0, 0
    for _name, path in iter_data_files(data_dir):
        with contextlib.suppress(OSError):
            total += path.stat().st_size
            count += 1
    with contextlib.suppress(OSError):
        total += (data_dir / DB_NAME).stat().st_size
    return count, total


# --------------------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------------------


def checked_name(name: str) -> str:
    """``name`` if it is a name a backup may contain (module policy), else :class:`DamagedBackup`."""
    refused = DamagedBackup("This backup contains an entry Ordnung never writes, so it is not restored.")
    if not name or len(name) > MAX_NAME_CHARS or "\\" in name or "\x00" in name:
        raise refused
    if name in (DB_NAME, MANIFEST_NAME):
        return name
    pure = PurePosixPath(name)
    parts = name.split("/")
    if pure.is_absolute() or len(parts) < 2 or parts[0] not in FOLDERS:
        raise refused
    if any(part in ("", ".", "..") for part in parts) or ":" in parts[0]:
        raise refused
    return name


def _private_dirs(root: Path, relative: PurePosixPath) -> Path:
    """Create ``root/relative`` one level at a time, each folder private to its owner."""
    current = root
    for part in relative.parts:
        current = current / part
        if not current.is_dir():
            current.mkdir(mode=PRIVATE_DIR_MODE)
    return current


def _copy_member(
    stream: IO[bytes], target: Path | None, mtime: float, keep: bool = False
) -> tuple[ManifestFile, bytes]:
    """Hash ``stream`` and write it to ``target`` (``None``: only hash it). ``keep`` returns its bytes too."""
    digest, size, kept = hashlib.sha256(), 0, bytearray()
    handle = None
    if target is not None:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
        handle = os.fdopen(fd, "wb")
    try:
        while block := stream.read(1024 * 1024):
            if handle is not None:
                handle.write(block)
            if keep:
                kept += block
            digest.update(block)
            size += len(block)
    finally:
        if handle is not None:
            handle.close()
    if target is not None:
        with contextlib.suppress(OSError):
            os.utime(target, (mtime, mtime))
    return ManifestFile(path="", size=size, sha256=digest.hexdigest()), bytes(kept)


def _parse_manifest(raw: bytes) -> Manifest:
    try:
        manifest = Manifest.model_validate_json(raw)
    except ValidationError:
        raise DamagedBackup("This backup's list of contents is unreadable.") from None
    if manifest.format > ARCHIVE_FORMAT:
        raise NewerBackupFormat(
            "This backup was made by a newer version of Ordnung. Update Ordnung, then restore it."
        )
    return manifest


def _verify_files(manifest: Manifest, written: dict[str, ManifestFile]) -> None:
    if manifest.database.path != DB_NAME:
        raise DamagedBackup("This backup's list of contents is unreadable.")
    expected = {entry.path: entry for entry in [manifest.database, *manifest.files]}
    if len(expected) != len(manifest.files) + 1 or set(expected) != set(written):
        raise DamagedBackup("This backup's files don't match its list of contents.")
    for name, entry in expected.items():
        got = written[name]
        if (got.size, got.sha256) != (entry.size, entry.sha256):
            raise DamagedBackup(f"A file in this backup doesn't match its list of contents: {name}")


def _open_database(data: bytes) -> sqlite3.Connection:
    """The backup's database, opened in memory from its bytes (nothing is created on disk)."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.deserialize(data)
    except sqlite3.DatabaseError:
        conn.close()
        raise
    return conn


def verify_database(conn: sqlite3.Connection, manifest: Manifest) -> None:
    """The restored database is intact, not newer than this Ordnung, and has the recorded rows."""
    if manifest.schema_version > latest_version():
        raise NewerBackupFormat(
            "This backup was made by a newer version of Ordnung (its database is newer than this "
            "version reads). Update Ordnung, then restore it."
        )
    try:
        check = conn.execute("PRAGMA integrity_check").fetchall()
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        counts = table_counts(conn)
    except sqlite3.DatabaseError:
        raise DamagedBackup("The database in this backup is damaged.") from None
    if check != [("ok",)]:
        raise DamagedBackup("The database in this backup is damaged.")
    if version != manifest.schema_version or counts != manifest.tables:
        raise DamagedBackup("The database in this backup doesn't match its list of contents.")


_UNEXPECTED = "This backup contains an entry Ordnung never writes, so it is not restored."


def extract_backup(src: BinaryIO, passphrase: str, staging: Path | None) -> BackupContents:
    """Decrypt ``src`` into the empty folder ``staging`` and prove it complete (module policy).

    ``staging=None`` only checks: every byte is decrypted, authenticated and verified, nothing is
    written. The database is checked in memory either way. Raises a
    :class:`~ordnung.backup.container.BackupError`; ``staging`` may then hold part of the backup —
    the caller removes it.
    """
    reader = EncryptedReader(src, passphrase)
    written: dict[str, ManifestFile] = {}
    raw_manifest: bytes | None = None
    database = b""
    try:
        with tarfile.open(fileobj=reader, mode="r|") as tar:
            for member in tar:
                name = checked_name(member.name)
                stream = tar.extractfile(member) if member.isreg() else None
                if stream is None or name in written or (name == MANIFEST_NAME and raw_manifest is not None):
                    raise DamagedBackup(_UNEXPECTED)
                if name == MANIFEST_NAME:
                    if member.size > MAX_MANIFEST_BYTES:
                        raise DamagedBackup("This backup's list of contents is unreadable.")
                    raw_manifest = stream.read()
                    continue
                target = None
                if staging is not None:
                    relative = PurePosixPath(name)
                    target = _private_dirs(staging, relative.parent) / relative.name
                keep = name == DB_NAME  # checked in memory below
                entry, data = _copy_member(stream, target, member.mtime, keep=keep)
                database = data if keep else database
                written[name] = entry.model_copy(update={"path": name})
        reader.read_to_end()  # authenticate the tail after the archive's end marker too
    except tarfile.TarError:
        raise DamagedBackup("This backup's archive is damaged.") from None
    if raw_manifest is None:
        raise DamagedBackup("This backup is incomplete: its list of contents is missing.")
    manifest = _parse_manifest(raw_manifest)
    _verify_files(manifest, written)
    try:
        conn = _open_database(database)
    except sqlite3.DatabaseError:
        raise DamagedBackup("The database in this backup is damaged.") from None
    try:
        verify_database(conn, manifest)
    finally:
        conn.close()
    return BackupContents(manifest)


def check_backup(path: Path, passphrase: str) -> BackupContents:
    """Check the backup at ``path`` completely without restoring anything (``ordnung restore --check``)."""
    with path.open("rb") as src:
        return extract_backup(src, passphrase, None)
