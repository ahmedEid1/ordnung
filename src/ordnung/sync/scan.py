"""What the sync folder shows, as this computer sees it now (design §8, §13; review findings 6, 7, 9, 18, 20).

**Heads.** Every scan lists ``h/`` and decrypts every head (finding 9: at most 8 × a few KiB; a size or
mtime that didn't change says nothing on a cloud folder that keeps mtimes to the second). A head is
valid when it authenticates under this folder's vault, names the computer its file name is derived
from, and is not older than one already seen (``written``: a replayed or rolled-back head is ignored,
F15). The last good plaintext of each head is kept in ``sync/heads.json``: a head that can't be read
now (cut short, written in place, damaged) is taken from there (F14) and called ``damaged`` only after
:data:`~ordnung.sync.DAMAGED_AFTER_S` with an unchanged stat. A head of a newer format or schema is
``newer`` (nothing is pulled from it, F31). A lineage that claims a computer's person numbers beyond
the highest that computer published is refused (finding 18).

**The computer in use** is the valid head with the highest ``(epoch, computer)``, among heads that
didn't leave and weren't forgotten (the union of every head's ``forgotten``).

**Completeness** (:meth:`Scanner.completeness`): a version has arrived when its manifest, every bucket,
every database slice and every data file it needs (one this computer doesn't already have) are in the
folder with the expected sealed size *and* have authenticated with the expected SHA-256 (finding 6).
Verified objects are remembered by their stat (size, mtime_ns, inode, ctime_ns). A missing, short or
online-only object, a read error or a read that times out is "not arrived yet", never damage; a
right-size object that keeps failing is damaged after :data:`~ordnung.sync.DAMAGED_AFTER_S`, and one
missing past :data:`~ordnung.sync.ARRIVAL_PATIENCE_S` is asked for again (``Head.wants``, finding 7).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ordnung.db.migrate import latest_version
from ordnung.sync import (
    ARRIVAL_PATIENCE_S,
    DAMAGED_AFTER_S,
    FOLDER_FORMAT,
    KEY_FILE_BYTES,
    MAX_FILE_BYTES,
    MAX_RECORD_BYTES,
    WANTS_MAX,
    ObjectKind,
    SyncError,
    SyncProblemCode,
)
from ordnung.sync import lineage as lin
from ordnung.sync.crypto import Damaged, Vault, sealed_size_of
from ordnung.sync.folder import FileInfo, FolderUnreachable, SyncFolder
from ordnung.sync.model import Bucket, FileEntry, Head, LocalState, Manifest, SeenHead, VersionId, VersionRef

if TYPE_CHECKING:
    from ordnung.sync.model import FilesCacheEntry


@dataclass(frozen=True)
class Problem:
    """Why sync is paused or needs the person (the API words it)."""

    code: SyncProblemCode
    detail: str = ""


@dataclass(frozen=True)
class Completeness:
    """How much of a version has arrived (and verified) here."""

    ready: bool
    have: int = 0
    need: int = 0
    have_bytes: int = 0
    need_bytes: int = 0
    online_only: int = 0
    damaged: tuple[str, ...] = ()
    manifest: Manifest | None = None


@dataclass(frozen=True)
class HeadView:
    """One computer's head as this computer sees it."""

    file: str
    head: Head
    key: int
    this: bool
    #: read now (False: the last good copy, the current file can't be read)
    readable: bool = True
    newer: bool = False
    forgotten: bool = False
    #: this computer's clock: when that head's current version first arrived here
    arrived_at: str | None = None
    completeness: Completeness | None = None

    @property
    def computer(self) -> str:
        return self.head.computer

    @property
    def left(self) -> bool:
        return self.head.state == "left"

    @property
    def complete(self) -> bool:
        return self.completeness is not None and self.completeness.ready


@dataclass(frozen=True)
class FolderView:
    """The heads of the folder and what is wrong with it (``problem``) — one scan."""

    heads: tuple[HeadView, ...] = ()
    problem: Problem | None = None
    #: the computer in use (its id), if any
    holder: str | None = None
    max_epoch: int = 0
    #: this computer's own head is missing, unreadable or not the last one written (rewrite it)
    own_stale: bool = False
    #: some head can't be read or was replayed (GC waits)
    uncertain: bool = False
    #: the other computers' wants (objects to write again)
    wants: frozenset[str] = frozenset()
    #: another key file sits next to this folder's (F28)
    other_key_file: str | None = None

    @property
    def others(self) -> tuple[HeadView, ...]:
        """Every other computer's head with a version, but forgotten ones (left heads included:
        blocker 2 — their last version still counts for content decisions)."""
        return tuple(h for h in self.heads if not h.this and not h.forgotten)

    def own(self) -> HeadView | None:
        return next((h for h in self.heads if h.this), None)

    def by_computer(self, computer: str) -> HeadView | None:
        return next((h for h in self.heads if h.computer == computer), None)

    def by_key(self, key: int) -> HeadView | None:
        return next((h for h in self.heads if h.key == key), None)


@dataclass
class _Tracked:
    signature: tuple[int, int, int, int]
    since: float


@dataclass
class Scanner:
    """The scanning half of a session: caches what it verified, decrypted records and when objects
    started to be missing or failing (this computer's monotonic clock)."""

    folder: SyncFolder
    vault: Vault
    monotonic: Callable[[], float]
    wall: Callable[[], str]
    #: object name → the stat it verified at
    verified: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)
    #: content-named records already opened (write-once, so never stale)
    records: dict[str, bytes] = field(default_factory=dict)
    damaged_since: dict[str, _Tracked] = field(default_factory=dict)
    missing_since: dict[str, float] = field(default_factory=dict)
    head_failing: dict[str, _Tracked] = field(default_factory=dict)

    # ---- heads ------------------------------------------------------------------------------------

    def _open_head(self, file: str, data: bytes) -> Head | str | None:
        """The head in ``data`` (``None``: unreadable; ``"newer"``: a newer format)."""
        try:
            raw = self.vault.open("h", file, data, max_length=MAX_RECORD_BYTES)
        except Damaged:
            return None
        try:
            parsed = json.loads(raw)
        except ValueError:
            return None
        if (
            isinstance(parsed, dict)
            and isinstance(parsed.get("format"), int)
            and parsed["format"] > FOLDER_FORMAT
        ):
            return "newer"
        try:
            head = Head.model_validate(parsed)
        except ValidationError:
            return None
        if head.vault != self.vault.id or self.vault.head_name(head.computer) != file:
            return None
        return head

    def scan(self, state: LocalState, cache: dict[str, Head]) -> tuple[FolderView, dict[str, Head]]:
        """Read the folder (module doc). Returns the view and the updated last-good-heads cache."""
        try:
            return self._scan(state, cache)
        except FolderUnreachable:
            return FolderView(
                problem=Problem("folder_unreachable"), heads=self._cached_views(state, cache)
            ), cache
        except OSError as exc:
            return FolderView(problem=Problem("folder_unreachable", str(exc.strerror or exc))), cache

    def _cached_views(self, state: LocalState, cache: dict[str, Head]) -> tuple[HeadView, ...]:
        views = []
        for file, head in sorted(cache.items()):
            views.append(
                HeadView(file, head, state.keys.get(file, 0), head.computer == state.computer, readable=False)
            )
        return tuple(views)

    def _scan(self, state: LocalState, cache: dict[str, Head]) -> tuple[FolderView, dict[str, Head]]:
        folder = self.folder
        if not folder.is_dir():
            return FolderView(problem=Problem("folder_missing")), cache
        keys = folder.key_files()
        others = sorted(name for name in keys if name != state.key_file)
        if state.key_file not in keys:
            if others:
                return FolderView(problem=Problem("folder_other")), cache
            if folder.has_any_of_ours():
                return FolderView(problem=Problem("folder_missing")), cache
            return FolderView(problem=Problem("folder_empty")), cache
        ours = keys[state.key_file]
        if ours.size != KEY_FILE_BYTES or ours.online_only:
            return FolderView(problem=None, heads=self._cached_views(state, cache), uncertain=True), cache
        data = folder.read_key_file(state.key_file)
        if data is not None and data.hex() != state.key_file_bytes:
            return FolderView(problem=Problem("folder_other")), cache

        files = folder.head_files()
        updated = dict(cache)
        views: list[HeadView] = []
        uncertain = False
        own_stale = True
        newer_seen = False
        own_file = self.vault.head_name(state.computer)
        now = self.monotonic()
        for file in sorted(set(files) | set(cache)):
            info = files.get(file)
            head: Head | None = None
            readable = False
            newer = False
            if info is not None and not info.online_only:
                raw = folder.read_head(file)
                opened = self._open_head(file, raw) if raw is not None else None
                if opened == "newer":
                    newer = newer_seen = True
                elif isinstance(opened, Head):
                    head, readable = opened, True
                    self.head_failing.pop(file, None)
                if head is None and not newer:
                    tracked = self.head_failing.get(file)
                    if tracked is None or tracked.signature != info.signature:
                        self.head_failing[file] = _Tracked(info.signature, now)
            seen = state.seen.get(file)
            if head is not None and seen is not None and head.written < seen.written:
                head, readable = None, False  # a replayed or rolled-back copy (F15)
                uncertain = True
            if head is None:
                head = cache.get(file)
                if head is None:
                    continue
                if file != own_file:
                    uncertain = True
            if file == own_file:
                if readable and head.written == state.written and head.computer == state.computer:
                    own_stale = False
                if head.computer != state.computer:
                    continue
            if readable:
                updated[file] = head
                self._see(state, file, head)
            if head.schema_version > latest_version():
                newer = True
            views.append(
                HeadView(
                    file=file,
                    head=head,
                    key=self._key(state, file),
                    this=head.computer == state.computer,
                    readable=readable,
                    newer=newer,
                    arrived_at=state.seen[file].version_at if file in state.seen else None,
                )
            )
        forgotten: set[str] = set()
        for view in views:
            if view.head.state != "left":
                forgotten.update(view.head.forgotten)
        forgotten.update(state.forgotten)
        problem: Problem | None = None
        if state.computer in forgotten - set(state.forgotten):
            problem = Problem("forgotten")
        published = self._published(views, state)
        final: list[HeadView] = []
        for view in views:
            is_forgotten = view.computer in forgotten and not view.this
            if view.head.version is not None and not lin.claims_within(view.head.version.lineage, published):
                view = HeadView(**{**view.__dict__, "readable": False})  # finding 18: refused
                uncertain = True
                is_forgotten = is_forgotten or not view.this
                if not view.this:
                    continue
            final.append(HeadView(**{**view.__dict__, "forgotten": is_forgotten}))
        live = [v for v in final if not v.forgotten and not v.left]
        holder = max(live, key=lambda v: (v.head.epoch, v.computer)).computer if live else None
        max_epoch = max([v.head.epoch for v in final] + [state.epoch])
        wants: set[str] = set()
        for view in final:
            if not view.this and not view.forgotten:
                wants.update(view.head.wants)
        for file, tracked in self.head_failing.items():
            if file in files and now - tracked.since >= DAMAGED_AFTER_S and problem is None:
                problem = Problem("damaged", "head")
        if newer_seen and problem is None:
            problem = Problem("newer_ordnung")
        return (
            FolderView(
                heads=tuple(final),
                problem=problem,
                holder=holder,
                max_epoch=max_epoch,
                own_stale=own_stale,
                uncertain=uncertain,
                wants=frozenset(wants),
                other_key_file=others[0] if others else None,
            ),
            updated,
        )

    def _published(self, views: Iterable[HeadView], state: LocalState) -> dict[str, int]:
        published = {view.computer: view.head.pnum for view in views if not view.this}
        published[state.computer] = state.pnum
        return published

    def _key(self, state: LocalState, file: str) -> int:
        if file not in state.keys:
            state.keys[file] = max(state.keys.values(), default=0) + 1
        return state.keys[file]

    def _see(self, state: LocalState, file: str, head: Head) -> None:
        version = head.version.id.key() if head.version is not None else None
        seen = state.seen.get(file)
        now = self.wall()
        if seen is None:
            state.seen[file] = SeenHead(
                written=head.written,
                computer=head.computer,
                version=version,
                version_at=now,
                first_seen_at=now,
            )
            return
        seen.written = max(seen.written, head.written)
        if version != seen.version:
            seen.version = version
            seen.version_at = now

    # ---- records ----------------------------------------------------------------------------------

    def read_record(self, kind: ObjectKind, sha256: str, length: int) -> bytes | None:
        """The verified content of a record object (manifest or bucket); ``None``: not arrived yet.
        :class:`Damaged` when it is there with the right size and doesn't open."""
        name = self.vault.object_name(kind, sha256)
        if name in self.records:
            return self.records[name]
        if length > MAX_RECORD_BYTES:
            raise Damaged()
        info = self.folder.object_info(name)
        if info is None or info.online_only or info.size != sealed_size_of(length):
            return None
        try:
            data = self.folder.read_bytes(self.folder.object_path(name), MAX_RECORD_BYTES * 2)
        except (OSError, FolderUnreachable):
            return None
        if data is None or len(data) != info.size:
            return None
        try:
            content = self.vault.open(kind, name, data, max_length=MAX_RECORD_BYTES)
        except Damaged:
            self._failing(name, info)
            raise

        if hashlib.sha256(content).hexdigest() != sha256:
            self._failing(name, info)
            raise Damaged()
        self.records[name] = content
        self.verified[name] = info.signature
        self.damaged_since.pop(name, None)
        return content

    def manifest(self, ref: VersionRef) -> Manifest | None:
        content = self.read_record("m", ref.manifest_sha256, ref.manifest_size)
        if content is None:
            return None
        try:
            manifest = Manifest.model_validate_json(content)
        except ValidationError:
            raise Damaged() from None
        if (
            manifest.vault != self.vault.id
            or manifest.version != ref.id
            or manifest.digest != ref.digest
            or manifest.lineage != ref.lineage
            or self.vault.object_name("m", ref.manifest_sha256) != ref.manifest
        ):
            raise Damaged()
        return manifest

    def bucket(self, sha256: str, size: int, key: str) -> Bucket | None:
        content = self.read_record("b", sha256, size)
        if content is None:
            return None
        try:
            bucket = Bucket.model_validate_json(content)
        except ValidationError:
            raise Damaged() from None
        if bucket.key != key:
            raise Damaged()
        return bucket

    def _failing(self, name: str, info: FileInfo) -> None:
        tracked = self.damaged_since.get(name)
        if tracked is None or tracked.signature != info.signature:
            self.damaged_since[name] = _Tracked(info.signature, self.monotonic())

    def verify_object(self, kind: ObjectKind, sha256: str, size: int) -> FileInfo | bool | None:
        """``True`` when the object is here and verified; its :class:`FileInfo` when it is there but
        online-only; ``None`` when it hasn't arrived; ``False`` when it is there and fails."""
        name = self.vault.object_name(kind, sha256)
        expected = sealed_size_of(size)
        try:
            info = self.folder.object_info(name)
        except (OSError, FolderUnreachable):
            return None
        if info is None or info.size != expected:
            if info is not None and info.online_only:
                return info
            self.missing_since.setdefault(name, self.monotonic())
            return None
        if info.online_only:
            return info
        self.missing_since.pop(name, None)
        if self.verified.get(name) == info.signature:
            return True

        try:
            with self.folder.open_object(name) as handle:
                _length, got = self.vault.open_to(
                    handle, kind, name, info.size, None, max_length=MAX_FILE_BYTES
                )
        except Damaged:
            self._failing(name, info)
            return False
        except (OSError, FolderUnreachable):
            return None
        if got != sha256:
            self._failing(name, info)
            return False
        self.verified[name] = info.signature
        self.damaged_since.pop(name, None)
        return True

    def completeness(
        self, ref: VersionRef, local_files: dict[str, FilesCacheEntry] | None = None
    ) -> Completeness:
        """How much of the version ``ref`` has arrived and verified here (module doc)."""
        local_files = local_files or {}
        have = need = have_bytes = need_bytes = online = 0
        damaged: list[str] = []
        now = self.monotonic()

        def count(result: FileInfo | bool | None, name: str, size: int) -> None:
            nonlocal have, need, have_bytes, need_bytes, online
            need += 1
            need_bytes += size
            if result is True:
                have += 1
                have_bytes += size
            elif isinstance(result, FileInfo):
                online += 1
            elif result is False:
                tracked = self.damaged_since.get(name)
                if tracked is not None and now - tracked.since >= DAMAGED_AFTER_S:
                    damaged.append(name)

        try:
            manifest = self.manifest(ref)
        except Damaged:
            name = ref.manifest
            tracked = self.damaged_since.get(name)
            if tracked is not None and now - tracked.since >= DAMAGED_AFTER_S:
                damaged.append(name)
            return Completeness(False, 0, 1, 0, ref.manifest_size, damaged=tuple(damaged))
        except (OSError, FolderUnreachable):
            return Completeness(False, 0, 1, 0, ref.manifest_size)
        if manifest is None:
            info = None
            with contextlib.suppress(OSError, FolderUnreachable):
                info = self.folder.object_info(ref.manifest)
            return Completeness(
                False, 0, 1, 0, ref.manifest_size, online_only=int(bool(info and info.online_only))
            )
        have, need, have_bytes, need_bytes = 1, 1, ref.manifest_size, ref.manifest_size
        entries: list[FileEntry] = []
        for bucket_ref in manifest.buckets:
            name = self.vault.object_name("b", bucket_ref.sha256)
            need += 1
            need_bytes += bucket_ref.size
            try:
                bucket = self.bucket(bucket_ref.sha256, bucket_ref.size, bucket_ref.key)
            except Damaged:
                tracked = self.damaged_since.get(name)
                if tracked is not None and now - tracked.since >= DAMAGED_AFTER_S:
                    damaged.append(name)
                continue
            if bucket is None:
                self.missing_since.setdefault(name, now)
                continue
            have += 1
            have_bytes += bucket_ref.size
            entries.extend(bucket.entries)
        buckets_ready = have == need
        for piece in manifest.db.slices:
            name = self.vault.object_name("d", piece.sha256)
            count(self.verify_object("d", piece.sha256, piece.size), name, piece.size)
        for entry in entries:
            cached = local_files.get(entry.path)
            if cached is not None and cached.sha256 == entry.sha256 and cached.size == entry.size:
                continue  # already here (files/ are named by their content; others were hashed)
            name = self.vault.object_name("f", entry.sha256)
            count(self.verify_object("f", entry.sha256, entry.size), name, entry.size)
        ready = buckets_ready and have == need
        return Completeness(ready, have, need, have_bytes, need_bytes, online, tuple(damaged), manifest)

    def wanted(self) -> list[str]:
        """Objects to ask the others for again: damaged for long, or missing past the patience."""
        now = self.monotonic()
        names = [n for n, t in self.damaged_since.items() if now - t.since >= DAMAGED_AFTER_S]
        names += [n for n, since in self.missing_since.items() if now - since >= ARRIVAL_PATIENCE_S]
        return sorted(set(names))[:WANTS_MAX]

    def stalled(self) -> bool:
        now = self.monotonic()
        return any(now - since >= ARRIVAL_PATIENCE_S for since in self.missing_since.values())


def version_ids(view: FolderView) -> set[VersionId]:
    return {h.head.version.id for h in view.heads if h.head.version is not None}


__all__ = ["Completeness", "FolderView", "HeadView", "Problem", "Scanner", "SyncError", "version_ids"]
