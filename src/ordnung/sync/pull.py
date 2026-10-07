"""Bringing a version over (design §11; review findings 1, 10, 11, 12, 32).

**Stage and verify, live data untouched** (:func:`stage`): the space is checked first (staged database +
the live database × 1.1 + the files needed + a kept copy's estimate + 64 MiB, finding 12); the manifest
and buckets are authenticated and checked (names, caps); the database slices are decrypted into
``sync/incoming/ordnung.db``, each and the whole file SHA-checked, then ``integrity_check``, schema and
row counts, a demo database refused, an older schema migrated *here*, a page size made the live one's;
every path the database names must be among the version's files (finding 10). A local file is reused
only when its size matches and its cached (or freshly computed) SHA-256 is the version's (finding 11c);
every other file is decrypted into ``incoming/`` (``O_EXCL``, ``0600``), checked and ``fsync``-ed.
Anything that hasn't arrived raises :class:`~ordnung.sync.NotArrived` and the staging is removed.

**The journal is the commit point** (:func:`apply`): ``sync/pull.json`` names the target and every staged
file. Before it nothing live has changed; after it the pull finishes — without the key — even across a
crash (:func:`resume_interrupted`, run before the Store opens): the files are moved into place, then the
database is replaced in **one** SQLite transaction (:meth:`ordnung.db.store.Store.replace_with`) with
this computer's own state carried over (:func:`ordnung.sync.scrub.merge_local`) and ``sync_mark``
naming the target in that same transaction, then files nothing names any more are pruned (last: a crash
leaves extra files, never missing ones), then ``state.json``.

If the person changed something after the pull was decided (the counter moved — review blocker 1), the
pull is given up before the database changes: what was placed is only extra files. A database step
that fails (no space, a file held) leaves the journal; the next start tries again, and the person may
give it up (``abandon``) while ``sync_mark`` doesn't name the target.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from ordnung.backup.archive import (
    FOLDERS,
    checked_name,
    estimate,
    iter_data_files,
    table_counts,
)
from ordnung.backup.container import DamagedBackup
from ordnung.config import Paths
from ordnung.db.migrate import latest_version, migrate
from ordnung.db.store import PERSON_WRITE, Store
from ordnung.sync import (
    MAX_FILE_BYTES,
    RECENT_BASES,
    SYNC_MARK_KEY,
    NewerSyncFolder,
    NotArrived,
    SyncError,
    SyncRefused,
)
from ordnung.sync.crypto import Damaged, sealed_size_of
from ordnung.sync.folder import FsOps, RealFs
from ordnung.sync.local import Local
from ordnung.sync.model import BaseInfo, FileEntry, FilesCacheEntry, Journal, Manifest, VersionRef
from ordnung.sync.scrub import PersonChanged, document_ids, is_demo, merge_local, referenced_paths

if TYPE_CHECKING:
    from ordnung.sync.engine import Session
    from ordnung.sync.scan import HeadView

_MIB = 1024 * 1024
SPACE_MARGIN = 64 * _MIB
NO_SPACE_MESSAGE = "This computer needs {size} free to take over (on the drive that holds Ordnung's data)."
UNFINISHED_MESSAGE = (
    "Bringing Ordnung over didn't finish ({reason}). Ordnung tries again at its next start; you can also "
    "give it up (this computer then stands by)."
)
ABANDONED = "Gave up an unfinished take-over."


def human_size(size: int) -> str:
    units = ["bytes", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1000 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{size} bytes"


class PullUnfinished(SyncError):
    """The journal's database step failed: the pull waits for the next try (or the person gives up)."""

    def __init__(self, reason: str) -> None:
        super().__init__("pull_unfinished", UNFINISHED_MESSAGE.format(reason=reason))


class PullAborted(SyncError):
    """The person changed something after the pull was decided (blocker 1): it was given up."""

    def __init__(self) -> None:
        super().__init__("not_needed", "Something changed here meanwhile, so nothing was brought over.")


@dataclass
class Staged:
    """A verified version in ``sync/incoming/``, ready to apply."""

    target: VersionRef
    computer: str
    from_name: str
    manifest: Manifest
    entries: list[FileEntry]
    db_path: Path
    staged_files: list[str]
    doc_ids: set[str]


@dataclass
class Applied:
    person: int | None
    removed_letters: int = 0
    pruned: int = 0


@dataclass
class ResumeResult:
    outcome: Literal["nothing", "finished", "failed", "discarded"]
    message: str | None = None
    target: VersionRef | None = None
    removed: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------------------
# staging
# --------------------------------------------------------------------------------------------------


def _private_dirs(fs: FsOps, root: Path, relative: PurePosixPath) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        if not current.is_dir():
            with contextlib.suppress(FileExistsError):
                fs.mkdir(current)
    return current


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_MIB):
            digest.update(block)
    return digest.hexdigest()


def local_match(data_dir: Path, entry: FileEntry, cache: dict[str, FilesCacheEntry]) -> bool:
    """The data folder already holds ``entry`` (size, then cached or computed SHA-256; finding 11c)."""
    path = data_dir / entry.path
    try:
        info = path.stat()
    except OSError:
        return False
    if info.st_size != entry.size:
        return False
    cached = cache.get(entry.path)
    if cached is not None and (cached.size, cached.mtime_ns, cached.ino) == (
        info.st_size,
        info.st_mtime_ns,
        info.st_ino,
    ):
        return cached.sha256 == entry.sha256
    try:
        sha = _hash(path)
    except OSError:
        return False
    cache[entry.path] = FilesCacheEntry(
        size=info.st_size, mtime_ns=info.st_mtime_ns, ino=info.st_ino, sha256=sha
    )
    return sha == entry.sha256


def _live_page_size(db: Path) -> int | None:
    if not db.is_file():
        return None
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return int(conn.execute("PRAGMA page_size").fetchone()[0])
    finally:
        conn.close()


def check_space(paths: Paths, manifest: Manifest, needed_files: int, *, keep: bool) -> None:
    """Finding 12: room for the staged database, the database written into the live WAL, the files and
    a kept copy, with a margin."""
    live = paths.db.stat().st_size if paths.db.is_file() else 0
    kept = estimate(paths.data_dir)[1] if keep else 0
    need = manifest.db.size + int(live * 1.1) + manifest.db.size + needed_files + kept + SPACE_MARGIN
    free = shutil.disk_usage(paths.data_dir).free
    if free < need:
        raise SyncError("no_space", NO_SPACE_MESSAGE.format(size=human_size(need)))


def _clear(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)


def stage(session: Session, head: HeadView, *, keep: bool = False) -> Staged:
    """Stage and verify ``head``'s version (module doc). Raises :class:`~ordnung.sync.NotArrived`,
    :class:`~ordnung.sync.NewerSyncFolder`, :class:`~ordnung.sync.SyncRefused` or ``no_space``;
    the staging is removed then."""
    target = head.head.version
    assert target is not None
    paths, fs, scanner = session.paths, session.data_fs, session.scanner
    incoming = session.local.incoming
    try:
        manifest = scanner.manifest(target)
    except Damaged:
        raise NotArrived() from None
    if manifest is None:
        raise NotArrived()
    if manifest.schema_version > latest_version():
        raise NewerSyncFolder("Another computer runs a newer Ordnung. Update Ordnung on this computer.")
    entries: list[FileEntry] = []
    for ref in manifest.buckets:
        try:
            bucket = scanner.bucket(ref.sha256, ref.size, ref.key)
        except Damaged:
            raise NotArrived() from None
        if bucket is None:
            raise NotArrived()
        for entry in bucket.entries:
            try:
                checked_name(entry.path)
            except DamagedBackup:
                raise SyncError(
                    "folder_problem", "A version in the sync folder names a file Ordnung never writes."
                ) from None
            if entry.path.split("/", 1)[0] not in FOLDERS or entry.size > MAX_FILE_BYTES:
                raise SyncError(
                    "folder_problem", "A version in the sync folder names a file Ordnung never writes."
                )
            entries.append(entry)
    if len({e.path for e in entries}) != len(entries) or len(entries) != manifest.files_count:
        raise SyncError("folder_problem", "A version in the sync folder doesn't match its list of files.")
    needed = [e for e in entries if not local_match(paths.data_dir, e, session.files)]
    check_space(paths, manifest, sum(e.size for e in needed), keep=keep)

    _clear(incoming)
    session.local.ensure()
    fs.mkdir(incoming)
    try:
        db_path = incoming / "ordnung.db"
        _stage_database(session, manifest, db_path)
        staged_files: list[str] = []
        for entry in needed:
            relative = PurePosixPath(entry.path)
            folder = _private_dirs(fs, incoming, relative.parent)
            _stage_file(session, entry, folder / relative.name)
            staged_files.append(entry.path)
        for current, _dirs, _names in os.walk(incoming):
            fs.fsync_dir(Path(current))
        conn = sqlite3.connect(db_path)
        try:
            ids = document_ids(conn)
            named = {
                p for p in referenced_paths(conn) if not (p.startswith("/") or (len(p) > 1 and p[1] == ":"))
            }
        finally:
            conn.close()
        if not named <= {e.path for e in entries}:
            raise SyncError("folder_problem", "A version in the sync folder names files it doesn't hold.")
    except BaseException:
        _clear(incoming)
        raise
    return Staged(
        target=target,
        computer=head.computer,
        from_name=head.head.name,
        manifest=manifest,
        entries=entries,
        db_path=db_path,
        staged_files=staged_files,
        doc_ids=ids,
    )


def _open_into(
    session: Session, kind: Literal["d", "f"], sha256: str, size: int, out: Callable[[bytes], object]
) -> None:
    name = session.vault.object_name(kind, sha256)
    folder = session.folder
    info = folder.object_info(name)
    if info is None or info.online_only or info.size != sealed_size_of(size):
        raise NotArrived()
    try:
        with folder.open_object(name) as handle:
            length, got = session.vault.open_to(handle, kind, name, info.size, out, max_length=MAX_FILE_BYTES)
    except Damaged:
        raise NotArrived() from None
    except OSError:
        raise NotArrived() from None
    if length != size or got != sha256:
        raise NotArrived()


def _stage_database(session: Session, manifest: Manifest, db_path: Path) -> None:
    fs = session.data_fs
    digest = hashlib.sha256()
    total = 0
    handle = fs.open_new(db_path)
    try:
        for piece in manifest.db.slices:

            def write(block: bytes) -> None:
                nonlocal total
                digest.update(block)
                total += len(block)
                handle.write(block)

            _open_into(session, "d", piece.sha256, piece.size, write)
        fs.fsync(handle)
    finally:
        handle.close()
    if total != manifest.db.size or digest.hexdigest() != manifest.db.sha256:
        raise SyncError("folder_problem", "A version's database in the sync folder is damaged.")
    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        try:
            check = conn.execute("PRAGMA integrity_check").fetchall()
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            counts = table_counts(conn)
        except sqlite3.DatabaseError:
            raise SyncError("folder_problem", "A version's database in the sync folder is damaged.") from None
        if check != [("ok",)] or version != manifest.schema_version or counts != manifest.db.tables:
            raise SyncError("folder_problem", "A version's database in the sync folder is damaged.")
        if is_demo(conn):
            raise SyncRefused()
        if version < latest_version():
            migrate(conn)  # in staging: a migration never fails half-way inside the live database
        live = _live_page_size(session.paths.db)
        if live is not None and live != int(conn.execute("PRAGMA page_size").fetchone()[0]):
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute(f"PRAGMA page_size={int(live)}")
            conn.execute("VACUUM")
    finally:
        conn.close()


def _stage_file(session: Session, entry: FileEntry, target: Path) -> None:
    fs = session.data_fs
    handle = fs.open_new(target)
    try:
        _open_into(session, "f", entry.sha256, entry.size, handle.write)
        fs.fsync(handle)
    finally:
        handle.close()


def removed_letters(staged: Staged, store: Store) -> int:
    """How many letters the live data has that the staged version lacks (Rule K, finding 18)."""
    live = {str(row[0]) for row in store._conn().execute("SELECT id FROM documents")}
    return len(live - staged.doc_ids)


# --------------------------------------------------------------------------------------------------
# the journal and the apply
# --------------------------------------------------------------------------------------------------


def apply(
    session: Session,
    staged: Staged,
    store: Store | None,
    *,
    kept: str | None = None,
    expect_person: int | None = None,
    progress: Callable[[int, int, int], object] | None = None,
    pages: int = -1,
) -> Applied:
    """Write the journal (the commit point), then finish the pull (module doc)."""
    keep_paths = sorted({e.path for e in staged.entries})
    journal = Journal(
        target=staged.target,
        from_name=staged.from_name,
        summary=staged.manifest.summary,
        kept=kept,
        files=staged.staged_files,
        keep_paths=keep_paths,
        entries=staged.entries,
        calendar=staged.manifest.calendar,
    )
    session.local.save_journal(journal)
    result = finish(
        session.paths,
        journal,
        store,
        session.data_fs,
        expect_person=expect_person,
        progress=progress,
        pages=pages,
        cache=session.files,
        refetch=lambda entry, target: _stage_file(session, entry, target),
    )
    session.reload_state()
    return result


Refetch = Callable[[FileEntry, Path], None]


def _place(paths: Paths, journal: Journal, fs: FsOps, refetch: Refetch | None) -> None:
    incoming = paths.data_dir / "sync" / "incoming"
    entries = {entry.path: entry for entry in journal.entries}
    touched: set[Path] = set()
    for relative in journal.files:
        source = incoming / relative
        target = paths.data_dir / relative
        _private_dirs(fs, paths.data_dir, PurePosixPath(relative).parent)
        if source.exists():
            fs.replace(source, target)
        else:
            entry = entries.get(relative)
            if entry is not None and local_match(paths.data_dir, entry, {}):
                continue  # moved already (a resumed pull)
            if entry is None or refetch is None:
                raise PullUnfinished("a file waiting to be placed went missing")
            _private_dirs(fs, incoming, PurePosixPath(relative).parent)
            refetch(entry, source)  # finding 12: fetched again from the folder (the key is here)
            fs.replace(source, target)
        touched.add(target.parent)
    # every folder up to the data folder: a folder made for a new letter is a new name in its parent
    chain = {
        folder
        for parent in touched
        for folder in (parent, *parent.parents)
        if paths.data_dir in (folder, *folder.parents)
    }
    for folder in sorted(chain, key=lambda p: len(p.parts), reverse=True):
        fs.fsync_dir(folder)


def _mark(db: Path) -> str | None:
    if not db.is_file():
        return None
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (SYNC_MARK_KEY,)).fetchone()
    except sqlite3.DatabaseError:
        return None
    finally:
        conn.close()
    return None if row is None else str(row[0])


def _prune(paths: Paths, journal: Journal, store: Store, fs: FsOps) -> int:
    keep = set(journal.keep_paths)
    removed = 0
    referenced = {p for p in _referenced(store)}
    for name, path in list(iter_data_files(paths.data_dir)):
        if name in keep or name in referenced:
            continue
        if name not in {p for p in _referenced(store)}:  # checked twice
            with contextlib.suppress(FileNotFoundError):
                fs.unlink(path)
                removed += 1
    derived = paths.derived
    if derived.is_dir():
        for folder in sorted(derived.iterdir()):
            if folder.is_dir() and not folder.is_symlink():
                with contextlib.suppress(OSError):
                    if not any(folder.iterdir()):
                        fs.rmdir(folder)
    return removed


def _referenced(store: Store) -> set[str]:
    conn = store._conn()
    return referenced_paths(conn)


def finish(
    paths: Paths,
    journal: Journal,
    store: Store | None,
    fs: FsOps | None = None,
    *,
    expect_person: int | None = None,
    progress: Callable[[int, int, int], object] | None = None,
    pages: int = -1,
    cache: dict[str, FilesCacheEntry] | None = None,
    refetch: Refetch | None = None,
) -> Applied:
    """Steps 1-4 of the journal (also when resuming): place, database, prune, commit."""
    fs = fs or RealFs()
    local = Local(paths, fs)
    own_store = store is None
    live = store if store is not None else Store(paths.db, data_dir=paths.data_dir)
    token = PERSON_WRITE.set(False)
    try:
        person: int | None = None
        if journal.stage == "staged":
            if expect_person is not None and _counter(live) != expect_person:
                _give_up(local)
                raise PullAborted()
            _place(paths, journal, fs, refetch)
            if _mark(paths.db) != journal.target.id.key():
                staged_db = local.incoming / "ordnung.db"

                def merge(staged: sqlite3.Connection, live_conn: sqlite3.Connection) -> None:
                    nonlocal person
                    person = merge_local(
                        staged,
                        live_conn,
                        target=journal.target.id,
                        calendar=journal.calendar,
                        expect_person=expect_person,
                    )

                try:
                    live.replace_with(staged_db, merge, pages=pages, progress=progress)
                except PersonChanged:
                    _give_up(local)
                    raise PullAborted() from None
                except (sqlite3.Error, OSError) as exc:
                    journal.failed = str(exc) or type(exc).__name__
                    local.save_journal(journal)
                    raise PullUnfinished(journal.failed) from None
            journal.stage = "database"
            journal.failed = None
            local.save_journal(journal)
        if person is None:
            person = _counter(live)
        pruned = _prune(paths, journal, live, fs)
        _commit(paths, local, journal, person, cache)
        return Applied(person=person, pruned=pruned)
    finally:
        PERSON_WRITE.reset(token)
        if own_store:
            live.close()


def _counter(store: Store) -> int | None:
    from ordnung.sync import PERSON_META_KEY

    raw = store.get_meta(PERSON_META_KEY)
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def _give_up(local: Local) -> None:
    local.remove(local.journal_path)
    _clear(local.incoming)


def _commit(
    paths: Paths, local: Local, journal: Journal, person: int | None, cache: dict[str, FilesCacheEntry] | None
) -> None:
    from ordnung.sync.engine import now_iso

    state = local.load()
    if state is not None:
        state.base = BaseInfo(
            ref=journal.target, summary=journal.summary, arrived_at=now_iso(), from_name=journal.from_name
        )
        state.recent = [*[r for r in state.recent if r.id != journal.target.id], journal.target][
            -RECENT_BASES:
        ]
        state.pushed = person if person is not None else 0
        state.force_person = False
        if journal.calendar is not None:
            state.calendar_received = journal.calendar
        local.save(state)
    files = dict(cache) if cache is not None else local.load_files()
    for entry in journal.entries:
        path = paths.data_dir / entry.path
        with contextlib.suppress(OSError):
            info = path.stat()
            if info.st_size == entry.size:
                files[entry.path] = FilesCacheEntry(
                    size=info.st_size, mtime_ns=info.st_mtime_ns, ino=info.st_ino, sha256=entry.sha256
                )
    keep = set(journal.keep_paths)
    for name in list(files):
        if name not in keep and not (paths.data_dir / name).exists():
            files.pop(name)
    with contextlib.suppress(OSError):
        local.save_files(files)
    if cache is not None:
        cache.clear()
        cache.update(files)
    local.remove(local.journal_path)
    _clear(local.incoming)


# --------------------------------------------------------------------------------------------------
# resuming, giving up
# --------------------------------------------------------------------------------------------------


def resume_interrupted(paths: Paths, *, fs: FsOps | None = None) -> ResumeResult:
    """Finish a pull past its commit point, or discard one that was only staged; remove a kept copy's
    leftover ``.part``. No key is needed, and it never raises: a failure leaves the journal (the agent
    starts standing by with ``pull_unfinished``)."""
    local = Local(paths, fs)
    if not local.dir.is_dir():
        return ResumeResult("nothing")
    with contextlib.suppress(OSError):
        for leftover in local.kept_dir.glob(".ordnung-kept-*.part"):
            leftover.unlink()
    try:
        journal = local.load_journal()
    except Exception as exc:  # an unreadable journal: nothing can be resumed from it
        return ResumeResult("failed", f"the take-over's record can't be read ({type(exc).__name__})")
    if journal is None:
        if local.incoming.exists():
            _clear(local.incoming)
            return ResumeResult("discarded")
        return ResumeResult("nothing")
    try:
        finish(paths, journal, None, fs or RealFs())
    except SyncError as exc:
        return ResumeResult("failed", str(exc), journal.target)
    except Exception as exc:
        return ResumeResult("failed", f"{type(exc).__name__}: {exc}", journal.target)
    return ResumeResult("finished", None, journal.target)


def unfinished(paths: Paths) -> Journal | None:
    """The journal of a pull that hasn't finished (``None``: none)."""
    try:
        return Local(paths).load_journal()
    except Exception:
        return None


def abandon(paths: Paths) -> bool:
    """Give up a pull whose database step failed (finding 12): only while ``sync_mark`` doesn't name its
    target — once the database is replaced, the pull must finish instead. True when it was given up."""
    local = Local(paths)
    journal = unfinished(paths)
    if journal is None:
        return False
    if _mark(paths.db) == journal.target.id.key():
        return False
    _give_up(local)
    return True
