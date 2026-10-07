"""Saving this computer's data into the sync folder (design §10; review findings 7, 10, 11, 14, 19, 21).

A push, in order:

1. **Snapshot.** The live demo is refused before anything is read (finding 19). An in-memory copy of
   the database (one read transaction, the WAL folded in) is taken; the person-change counter is read
   from that very copy, so the version holds exactly the person changes it counts (finding 5a). The copy
   is scrubbed (:mod:`ordnung.sync.scrub`); a demo database is refused again. The SQLite header's change
   counters (bytes 24-27 and 92-95) are zeroed in the serialized copy, so the first 1 MiB slice changes
   only when its pages do (measured: one row changed elsewhere then changes 1 slice of 157, not 2).
2. **Files.** Every data file is listed; only new files, or files whose size, mtime or inode changed,
   are hashed (``sync/files.json``). Every path the snapshot names must be among them — else a letter
   was deleted between the snapshot and the walk, and the push is tried again later (finding 10). An
   original under ``files/`` whose content no longer matches its name is never sealed
   (``local_damaged``, finding 11c).
3. **Nothing to do?** The digest equals the base's: no version is written. If the counter moved anyway
   (a person's write that changed nothing synced), it is accounted for without a version (finding 14).
4. **Upload what the folder lacks** — database slices, file-list buckets, data files — each sealed into
   a temp file, ``fsync``-ed and renamed. A data file is hashed again while it is sealed; if it changed
   underneath, the push is abandoned and no head is written.
5. **Reserve the counters** (``seq``, and ``pnum`` for a person change) in ``state.json`` before use.
6. **The manifest**, then the **fence** (a higher ``(epoch, computer)`` in ``h/`` makes the head
   ``standing_by``), then **the head — the commit point** — then ``sync_mark`` in the database, then
   ``state.json``.

A crash anywhere before the head leaves only unreferenced objects and this computer's temp files (removed
at its next push; GC frees the rest). After the head and before ``state.json``, the next start adopts the
head: its ``sync_mark`` names it, or — dead before ``sync_mark`` too — the database's digest equals the
head's (a database put back from an OS backup doesn't, and is a ``local_rollback``).

Churn (finding 21), measured in P1 on a generated library of 1,500 letters (each with two pages, three
cache rows, two dates, an activity row; an 80 MiB database, 80 slices): one more reading changed 29
slices (the search index merges its segments), one note 1, a search-index ``optimize`` 44. That is far
above :data:`ordnung.sync.SLICE_CHURN_LIMIT_BYTES`, so GC drops the superseded slices of a version every
live head has moved past after a day (:data:`ordnung.sync.SUPERSEDED_SLICE_GRACE_S`) rather than 7 days.
Cutting slices per table was not needed for that.
"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Literal

from ordnung import __version__
from ordnung.backup.archive import database_copy, iter_data_files, serialized, table_counts
from ordnung.demo.loader import is_demo_dir
from ordnung.sync import (
    DB_SLICE,
    FOLDER_FORMAT,
    MAX_FILES,
    PERSON_META_KEY,
    RECENT_BASES,
    SYNC_MARK_KEY,
    SyncError,
    SyncRefused,
)
from ordnung.sync import lineage as lin
from ordnung.sync.crypto import sealed_size_of
from ordnung.sync.model import (
    BaseInfo,
    Bucket,
    BucketRef,
    CalendarHandover,
    DbInfo,
    DbSlice,
    FileEntry,
    FilesCacheEntry,
    Lineage,
    Manifest,
    Summary,
    VersionId,
    VersionRef,
)
from ordnung.sync.scrub import (
    calendar_handover,
    document_ids,
    has_person_data,
    is_demo,
    person_count,
    referenced_paths,
    scrub,
    state_digest,
    summary,
)

if TYPE_CHECKING:
    from ordnung.db.store import Store
    from ordnung.sync.engine import Session

#: SQLite header bytes that change on every commit (file change counter, version-valid-for): zeroed in
#: a pushed copy, so the first slice changes only with its pages (probe: 2 of 157 slices → 1).
_COUNTER_BYTES = (range(24, 28), range(92, 96))
_READ_BLOCK = 1024 * 1024

LOCAL_DAMAGED_MESSAGE = (
    "A letter's original on this computer no longer matches what was stored (the disk may be failing), so "
    "it isn't saved to the sync folder. Run “ordnung doctor”."
)
CHANGED_MESSAGE = "Files changed while Ordnung was saving; it tries again in a moment."


class LocalDamaged(SyncError):
    """A local original whose content no longer matches its name (finding 11c)."""

    #: the problem the sync agent shows (:data:`ordnung.sync.SyncProblemCode`)
    problem = "local_damaged"

    def __init__(self, path: str) -> None:
        super().__init__("folder_problem", LOCAL_DAMAGED_MESSAGE)
        self.path = path


class TryAgain(SyncError):
    """The data changed while the push ran (a letter deleted between the snapshot and the walk, a file
    re-rendered while it was sealed): nothing was committed; the next push picks it up."""

    #: shown only when saving keeps failing (the agent tries again soon)
    problem = "save_failing"

    def __init__(self, message: str = CHANGED_MESSAGE) -> None:
        super().__init__("folder_problem", message)


@dataclass
class Snapshot:
    """What a push carries, made ready (step 1-2 of the module doc)."""

    data: bytes
    page_size: int
    tables: dict[str, int]
    schema_version: int
    #: the person-change counter the copy holds (``None``: no counter row — unexplained)
    person: int | None
    digest: str
    entries: list[FileEntry]
    sources: dict[str, Path]
    calendar: CalendarHandover | None
    summary: Summary
    doc_ids: set[str]
    person_data: bool


@dataclass
class PushResult:
    """What a push did."""

    outcome: Literal["pushed", "unchanged", "accounted"]
    version: VersionRef | None = None
    person: bool = False
    objects_written: int = 0
    bytes_written: int = 0
    kinds_written: dict[str, int] = field(default_factory=dict)
    head_state: str | None = None


# --------------------------------------------------------------------------------------------------
# the snapshot
# --------------------------------------------------------------------------------------------------


def _zero_counters(data: bytes) -> bytes:
    raw = bytearray(data)
    if len(raw) >= 100:
        for span in _COUNTER_BYTES:
            raw[span.start : span.stop] = bytes(len(span))
    return bytes(raw)


def file_sha(path: Path) -> str | None:
    """The SHA-256 of the file at ``path`` (``None``: it can't be read)."""
    try:
        return _hash_file(path)[0]
    except OSError:
        return None


def _hash_file(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as handle:
        while block := handle.read(_READ_BLOCK):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def walk_files(
    data_dir: Path, cache: dict[str, FilesCacheEntry]
) -> tuple[list[FileEntry], dict[str, Path], dict[str, FilesCacheEntry]]:
    """Every data file with its SHA-256: hashed only when new or changed (size, mtime, inode)."""
    entries: list[FileEntry] = []
    sources: dict[str, Path] = {}
    fresh: dict[str, FilesCacheEntry] = {}
    for name, path in iter_data_files(data_dir):
        try:
            info = path.stat()
        except FileNotFoundError:
            continue
        cached = cache.get(name)
        if cached is not None and (cached.size, cached.mtime_ns, cached.ino) == (
            info.st_size,
            info.st_mtime_ns,
            info.st_ino,
        ):
            sha = cached.sha256
        else:
            try:
                sha, size = _hash_file(path)
            except FileNotFoundError:
                continue
            if size != info.st_size:
                continue  # being written: the next push sees it whole
        fresh[name] = FilesCacheEntry(
            size=info.st_size, mtime_ns=info.st_mtime_ns, ino=info.st_ino, sha256=sha
        )
        entries.append(FileEntry(path=name, sha256=sha, size=info.st_size))
        sources[name] = path
    if len(entries) > MAX_FILES:
        raise SyncError("folder_problem", "This Ordnung holds more files than a sync folder can take.")
    return entries, sources, fresh


def _original_matches(entry: FileEntry) -> bool:
    """A ``files/xx/<sha>.<ext>`` original is named by its content's SHA-256."""
    parts = PurePosixPath(entry.path).parts
    if len(parts) != 3 or parts[0] != "files":
        return True
    stem = parts[2].split(".", 1)[0]
    if len(stem) != 64:
        return True
    return stem == entry.sha256


def take_snapshot(session: Session, *, demo: bool = False) -> Snapshot:
    """The scrubbed snapshot and the files (module doc, steps 1-2)."""
    paths = session.paths
    if demo or is_demo_dir(paths.data_dir):
        raise SyncRefused()
    copy = database_copy(paths.db)
    try:
        if is_demo(copy):
            raise SyncRefused()
        person = person_count(copy)
        own_calendar = calendar_handover(copy)
        scrub(copy)
        if is_demo(copy):
            raise SyncRefused()
        names = referenced_paths(copy)
        tables = table_counts(copy)
        schema_version = int(copy.execute("PRAGMA user_version").fetchone()[0])
        page_size = int(copy.execute("PRAGMA page_size").fetchone()[0])
        about = summary(copy)
        ids = document_ids(copy)
        person_data = has_person_data(copy)
        entries, sources, fresh = walk_files(paths.data_dir, session.files)
        walked = {entry.path for entry in entries}
        relative = {
            name for name in names if not (name.startswith("/") or (len(name) > 1 and name[1] == ":"))
        }
        if not relative <= walked:
            raise TryAgain()  # finding 10: a file the snapshot names is gone (deleted meanwhile)
        for entry in entries:
            if not _original_matches(entry):
                raise LocalDamaged(entry.path)
        calendar = own_calendar if own_calendar is not None else session.state.calendar_received
        digest = state_digest(copy, ((e.path, e.sha256) for e in entries), calendar)
        data = _zero_counters(serialized(copy))
    finally:
        copy.close()
    session.files = fresh
    return Snapshot(
        data=data,
        page_size=page_size,
        tables=tables,
        schema_version=schema_version,
        person=person,
        digest=digest,
        entries=entries,
        sources=sources,
        calendar=calendar,
        summary=about,
        doc_ids=ids,
        person_data=person_data,
    )


def current_digest(session: Session, *, demo: bool = False) -> str:
    return take_snapshot(session, demo=demo).digest


# --------------------------------------------------------------------------------------------------
# objects
# --------------------------------------------------------------------------------------------------


def bucket_key(path: str) -> str:
    """Buckets follow the data folder's layout: ``files/ab``, ``derived/<2 hex of the doc>``, ``drafts``."""
    parts = path.split("/")
    if parts[0] == "files" and len(parts) >= 3:
        return f"files/{parts[1][:2]}"
    if parts[0] == "derived" and len(parts) >= 3:
        return "derived/" + hashlib.sha256(parts[1].encode("utf-8")).hexdigest()[:2]
    return parts[0]


def buckets_of(entries: list[FileEntry]) -> list[tuple[BucketRef, bytes]]:
    grouped: dict[str, list[FileEntry]] = {}
    for entry in entries:
        grouped.setdefault(bucket_key(entry.path), []).append(entry)
    out: list[tuple[BucketRef, bytes]] = []
    for key in sorted(grouped):
        bucket = Bucket(format=1, key=key, entries=sorted(grouped[key], key=lambda e: e.path))
        content = bucket.model_dump_json().encode("utf-8")
        sha = hashlib.sha256(content).hexdigest()
        out.append((BucketRef(key=key, sha256=sha, size=len(content), count=len(bucket.entries)), content))
    return out


def slices_of(data: bytes) -> list[tuple[DbSlice, bytes]]:
    out: list[tuple[DbSlice, bytes]] = []
    for start in range(0, max(len(data), 1), DB_SLICE):
        piece = data[start : start + DB_SLICE]
        out.append((DbSlice(sha256=hashlib.sha256(piece).hexdigest(), size=len(piece)), piece))
    return out


def chunks_of(path: Path) -> Iterator[bytes]:
    with path.open("rb") as handle:
        while block := handle.read(_READ_BLOCK):
            yield block


class _Uploader:
    """Writes the objects a version needs that the folder lacks (one listing per shard)."""

    def __init__(self, session: Session, rewrite: frozenset[str] = frozenset()) -> None:
        self.rewrite = rewrite
        self.session = session
        self.listed: dict[str, dict[str, int]] = {}
        self.written = 0
        self.bytes = 0
        self.kinds: dict[str, int] = {}

    def _present(self, name: str, size: int) -> bool:
        state = self.session.state
        if state.present.get(name) == size:
            return True
        prefix = name[:2]
        if prefix not in self.listed:
            self.listed[prefix] = {
                full: info.size
                for full, info in self.session.folder.shard(prefix).items()
                if not info.online_only
            }
        if self.listed[prefix].get(name) == size:
            state.present[name] = size
            return True
        return False

    def record(self, kind: Literal["m", "b"], content: bytes, *, force: bool = False) -> str:
        sha = hashlib.sha256(content).hexdigest()
        name = self.session.vault.object_name(kind, sha)
        size = sealed_size_of(len(content))
        force = force or name in self.rewrite
        if force or not self._present(name, size):
            sealed = self.session.vault.seal(kind, name, content)
            self.session.folder.write_object(name, size, lambda out: out.write(sealed), force=force)
            self._wrote(kind, name, size)
        return name

    def slice(self, piece: DbSlice, content: bytes, *, force: bool = False) -> None:
        name = self.session.vault.object_name("d", piece.sha256)
        size = sealed_size_of(piece.size)
        force = force or name in self.rewrite
        if force or not self._present(name, size):
            sealed = self.session.vault.seal("d", name, content)
            self.session.folder.write_object(name, size, lambda out: out.write(sealed), force=force)
            self._wrote("d", name, size)

    def file(self, entry: FileEntry, source: Path, *, force: bool = False) -> None:
        name = self.session.vault.object_name("f", entry.sha256)
        size = sealed_size_of(entry.size)
        force = force or name in self.rewrite
        if not force and self._present(name, size):
            return
        vault = self.session.vault

        def produce(out: object) -> None:
            got = vault.seal_to(out, "f", name, entry.size, chunks_of(source))  # type: ignore[arg-type]
            if got != entry.sha256:
                raise TryAgain()  # re-rendered underneath: no head is written

        try:
            self.session.folder.write_object(name, size, produce, force=force)
        except FileNotFoundError as exc:
            if Path(exc.filename or "") == source:
                raise TryAgain() from None
            raise
        self._wrote("f", name, size)

    def _wrote(self, kind: str, name: str, size: int) -> None:
        self.session.state.present[name] = size
        self.written += 1
        self.bytes += size
        self.kinds[kind] = self.kinds.get(kind, 0) + 1


# --------------------------------------------------------------------------------------------------
# the push
# --------------------------------------------------------------------------------------------------


def push(
    session: Session,
    store: Store | None,
    *,
    lineage: Lineage | None = None,
    head_state: Literal["in_use", "standing_by", "closed", "left"] | None = None,
    claim: bool = False,
    force: bool = False,
    demo: bool = False,
    snapshot: Snapshot | None = None,
    rewrite: frozenset[str] = frozenset(),
) -> PushResult:
    """Save this computer's data as a new version (module doc). ``lineage`` replaces the computed one (a
    choice); ``head_state`` is what the head says afterwards (default: what it says now); ``claim``
    takes a new epoch; ``force`` writes a version even when nothing changed (refill, self-heal);
    ``rewrite`` names objects written again even when they are there (another computer wants them)."""
    state = session.state
    snap = snapshot or take_snapshot(session, demo=demo)
    base = state.base.ref if state.base is not None else None
    person = state.force_person or snap.person is None or snap.person > state.pushed or base is None
    wanted_state = head_state or state.head_state
    if base is not None and snap.digest == base.digest and lineage is None and not force:
        if person:
            # finding 14: a person's write that changed nothing synced makes no version
            if snap.person is None and store is not None:
                session.mark(store, base.id, person_row=True)  # the counter row, back
            state.pushed = snap.person if snap.person is not None else 0
            state.force_person = False
            session.save()
            return PushResult("accounted")
        return PushResult("unchanged")

    session.folder.remove_temps()
    upload = _Uploader(session, rewrite)
    slices = slices_of(snap.data)
    for piece, content in slices:
        upload.slice(piece, content)
    buckets = buckets_of(snap.entries)
    for _bucket, content in buckets:
        upload.record("b", content)
    for entry in snap.entries:
        upload.file(entry, snap.sources[entry.path])

    # reserve the numbers before they are used: never reused, even after a crash
    state.seq += 1
    if person:
        state.pnum += 1
    if claim:
        state.epoch = max(state.epoch, session.max_epoch()) + 1
    session.save()

    me = state.computer
    base_lineage = base.lineage if base is not None else lin.make()
    computed = lin.bump(base_lineage, me, state.pnum) if person else base_lineage
    if lineage is not None:
        chosen = (
            lin.union(lineage.content, {me: [(state.pnum, state.pnum)]}) if person else dict(lineage.content)
        )
        computed = lin.make(chosen, lineage.dropped)
    version = VersionId(computer=me, seq=state.seq)
    manifest = Manifest(
        format=FOLDER_FORMAT,
        vault=session.vault.id,
        version=version,
        base=base.id if base is not None else None,
        lineage=computed,
        epoch=state.epoch,
        created_at=session.clock.iso(),
        app_version=__version__,
        schema_version=snap.schema_version,
        db=DbInfo(
            size=len(snap.data),
            sha256=hashlib.sha256(snap.data).hexdigest(),
            page_size=snap.page_size,
            tables=snap.tables,
            slices=[piece for piece, _content in slices],
        ),
        buckets=[ref for ref, _content in buckets],
        files_count=len(snap.entries),
        files_bytes=sum(entry.size for entry in snap.entries),
        digest=snap.digest,
        summary=snap.summary,
        calendar=snap.calendar,
    )
    content = manifest.model_dump_json().encode("utf-8")
    manifest_name = upload.record("m", content)
    ref = VersionRef(
        id=version,
        lineage=computed,
        digest=snap.digest,
        manifest=manifest_name,
        manifest_size=len(content),
        manifest_sha256=hashlib.sha256(content).hexdigest(),
    )
    session.remember_records(ref, content, buckets)

    # the fence: a higher claim seen now makes this head stand by at once
    if wanted_state == "in_use" and session.claimed_elsewhere():
        wanted_state = "standing_by"
    session.write_head(version=ref, state=wanted_state)  # the commit point

    if store is not None:
        session.mark(store, version, person_row=snap.person is None)
    state.base = BaseInfo(ref=ref, summary=snap.summary, arrived_at=session.clock.iso(), from_name=state.name)
    state.recent = [*[r for r in state.recent if r.id != ref.id], ref][-RECENT_BASES:]
    state.pushed = snap.person if snap.person is not None else 0
    state.force_person = False
    state.last_saved_at = session.clock.iso()
    if wanted_state == "standing_by":
        state.mode = "standing_by"
    session.save()
    with contextlib.suppress(OSError):
        session.local.save_files(session.files)
    return PushResult(
        "pushed",
        version=ref,
        person=person,
        objects_written=upload.written,
        bytes_written=upload.bytes,
        kinds_written=upload.kinds,
        head_state=wanted_state,
    )


__all__ = [
    "PERSON_META_KEY",
    "SYNC_MARK_KEY",
    "LocalDamaged",
    "PushResult",
    "Snapshot",
    "TryAgain",
    "bucket_key",
    "buckets_of",
    "current_digest",
    "push",
    "slices_of",
    "take_snapshot",
    "walk_files",
]
