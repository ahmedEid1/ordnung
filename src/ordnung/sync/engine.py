"""The sync engine: everything hand-off sync does, as blocking calls (design §24.3, interface I2).

The agent (server) calls these in threads, the CLI calls them directly under ``DataDirLock``; both only
carry out what :func:`ordnung.sync.decide.decide` returns. A :class:`Session` is one unlocked folder:
the vault key (scrypt ran once, at :meth:`Session.open`), the folder, this computer's state, and the
scanner's caches.

* :func:`connect` sets up a new folder or joins one; :func:`disconnect` leaves it.
* :meth:`Session.start` runs at every start, once the Store is open: the copied-folder check (F32), the
  counters raised to what the folder shows, and the local-rollback check (review finding 4, F10).
* :meth:`Session.round` is one periodic step (push, bring in, stand by, acknowledge what arrived);
  :meth:`Session.use_here`, :meth:`Session.choose`, :meth:`Session.forget`, :meth:`Session.refill`,
  :meth:`Session.leave` and :meth:`Session.close` are the person's actions and shutdown.
* :func:`resume_interrupted` finishes a pull past its commit point (no key needed);
  :func:`writes_refused` answers from ``state.json`` alone.

The engine's own database writes (``sync_mark``, the privacy-log rows of :data:`~ordnung.sync.SyncActivityKind`)
are never person changes. The privacy-log rows are written here, so the agent and the CLI log alike.

The agent adds the two-phase apply of review blocker 1 around :meth:`Session.stage` and
:meth:`Session.apply`: writes are fenced and background work drained, then the counter is read again and
the decision made again before the kept copy and the journal; :meth:`Session.apply` itself gives the
pull up (``PullAborted``) when the counter moved after ``expect_person`` was read, inside the very
transaction that would replace the database.
"""

from __future__ import annotations

import contextlib
import dataclasses
import secrets as tokens
import shutil
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Literal

from ordnung import __version__
from ordnung.calendar.secrets import SecretsLocked, SecretStore, SecretsUnavailable
from ordnung.config import Paths
from ordnung.db.migrate import latest_version
from ordnung.db.store import PERSON_META_KEY, PERSON_WRITE, Store
from ordnung.demo.loader import is_demo_dir
from ordnung.models import AppSettings, CalendarSyncState
from ordnung.sync import (
    DEMO_MESSAGE,
    FOLDER_FORMAT,
    GC_EVERY_S,
    GC_GRACE_RUNTIME_S,
    GC_GRACE_S,
    MAX_COMPUTERS,
    NOT_CONNECTED_MESSAGE,
    SELF_HEAL_EVERY_S,
    SUPERSEDED_SLICE_GRACE_S,
    SYNC_MARK_KEY,
    TAKE_OVER_WAIT_MAX_S,
    NotArrived,
    SyncError,
    SyncNoticeCode,
    passphrase_problem,
)
from ordnung.sync import lineage as lin
from ordnung.sync.crypto import Vault, new_key_file, open_key_file, sealed_size_of
from ordnung.sync.decide import (
    Action,
    AlreadyInUse,
    BecomeStandby,
    BringIn,
    Choice,
    ChooseOther,
    ChooseThis,
    Claim,
    Decision,
    Idle,
    LatePush,
    LocalView,
    NoChoice,
    NotYet,
    Paused,
    Pull,
    Push,
    Standby,
    Wait,
    decide,
    others_have,
)
from ordnung.sync.folder import FolderInfo, FsOps, RealFs, SyncFolder, TimedFs, folder_problem, inspect
from ordnung.sync.kept import keep_local, keep_staged
from ordnung.sync.local import (
    Local,
    clean_name,
    keyring_account,
    machine_id,
    name_problem,
    unique_name,
    writes_refused,
)
from ordnung.sync.model import (
    BaseInfo,
    Bucket,
    BucketRef,
    FilesCacheEntry,
    Garbage,
    Head,
    KeptInfo,
    Lineage,
    LocalState,
    Notice,
    VersionId,
    VersionRef,
    Waiting,
)
from ordnung.sync.pull import (
    Applied,
    PullAborted,
    PullUnfinished,
    Staged,
    apply,
    removed_letters,
    resume_interrupted,
    stage,
    unfinished,
)
from ordnung.sync.push import PushResult, Snapshot, chunks_of, file_sha, push, take_snapshot
from ordnung.sync.scan import Completeness, FolderView, HeadView, Problem, Scanner
from ordnung.sync.scrub import calendar_state, calendar_target, has_person_data

__all__ = [
    "Clock",
    "ConnectResult",
    "Outcome",
    "Session",
    "connect",
    "decide",
    "disconnect",
    "inspect_folder",
    "push_once",
    "resume_interrupted",
    "writes_refused",
]

PASSPHRASE_NEEDED_MESSAGE = (
    "Ordnung needs the sync passphrase again on this computer (its password store doesn't have it)."
)
NOT_RECEIVED_MESSAGE = (
    "Your other computers haven't received this computer's latest changes yet. If you go on, they stay "
    "only in the sync folder until another computer brings them in."
)
FULL_MESSAGE = f"This folder already serves {MAX_COMPUTERS} computers. Forget one first."


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class Clock:
    """This computer's clocks (tests inject both): the wall clock is only shown and compared with itself,
    the monotonic one times patience and accumulates running time (it stops while the computer sleeps)."""

    wall: Callable[[], datetime] = field(default=lambda: datetime.now().astimezone())
    monotonic: Callable[[], float] = time.monotonic

    def iso(self) -> str:
        return self.wall().isoformat(timespec="seconds")


@contextmanager
def _bookkeeping() -> Iterator[None]:
    """Sync's own writes are never the person's (the counter doesn't move)."""
    token = PERSON_WRITE.set(False)
    try:
        yield
    finally:
        PERSON_WRITE.reset(token)


def _counter(store: Store) -> int | None:
    raw = store.get_meta(PERSON_META_KEY)
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


@dataclass
class Outcome:
    """What a step did (the agent turns it into the status and its events)."""

    decision: Decision
    pushed: PushResult | None = None
    applied: Applied | None = None
    kept: KeptInfo | None = None
    replaced: bool = False
    waiting: bool = False
    notice: Notice | None = None


@dataclass
class ConnectResult:
    """``choice``: joining while this computer has letters (nothing connected yet; answer with ``keep``)."""

    connected: bool
    created: bool = False
    choice: Choice | None = None
    outcome: Outcome | None = None
    session: Session | None = None


# --------------------------------------------------------------------------------------------------
# the session
# --------------------------------------------------------------------------------------------------


class Session:
    """One unlocked sync folder for one data folder (module doc)."""

    def __init__(
        self,
        paths: Paths,
        state: LocalState,
        vault: Vault,
        *,
        secrets: SecretStore,
        clock: Clock | None = None,
        folder_fs: FsOps | None = None,
        data_fs: FsOps | None = None,
        machine: Callable[[], str] = machine_id,
        passphrase: str | None = None,
    ) -> None:
        self.paths = paths
        self.state = state
        self.vault = vault
        self.secrets = secrets
        self.clock = clock or Clock()
        self.data_fs: FsOps = data_fs or RealFs()
        self.local = Local(paths, self.data_fs)
        self.folder = SyncFolder(
            Path(state.folder), folder_fs or TimedFs(), tag=vault.temp_tag(state.computer)
        )
        self.machine = machine
        self._passphrase = passphrase
        self.heads: dict[str, Head] = self.local.load_heads()
        self.files: dict[str, FilesCacheEntry] = self.local.load_files()
        self.scanner = Scanner(self.folder, vault, self.clock.monotonic, self.clock.iso)
        self.view: FolderView | None = None
        self.problem: Problem | None = None
        self._ticked = self.clock.monotonic()
        self._healed_at: float | None = None
        #: own records by object name (the latest push's manifest and buckets), for self-heal
        self._own_records: dict[str, bytes] = {}
        #: :meth:`start` ran (or this session connected the folder): the counters are known
        self.started = False
        #: another computer wants a slice of this computer's version: the next round writes a new one
        self._heal_push = False

    # ---- opening ----------------------------------------------------------------------------------

    @classmethod
    def open(
        cls,
        paths: Paths,
        secrets: SecretStore,
        *,
        passphrase: str | None = None,
        clock: Clock | None = None,
        folder_fs: FsOps | None = None,
        data_fs: FsOps | None = None,
        machine: Callable[[], str] = machine_id,
    ) -> Session:
        """Unlock the folder of ``paths`` (the keyring, then scrypt): :class:`SyncError`
        ``not_connected`` or ``passphrase_needed`` (a locked or unusable keyring too)."""
        state = Local(paths, data_fs).load()
        if state is None or not state.complete:
            raise SyncError("not_connected", NOT_CONNECTED_MESSAGE)
        if passphrase is None:
            try:
                passphrase = secrets.get(keyring_account(state.computer))
            except SecretsLocked as exc:
                raise SyncError("passphrase_needed", str(exc)) from None
            except SecretsUnavailable as exc:
                raise SyncError("passphrase_needed", str(exc)) from None
        if not passphrase:
            raise SyncError("passphrase_needed", PASSPHRASE_NEEDED_MESSAGE)
        vault = open_key_file(state.key_file, bytes.fromhex(state.key_file_bytes), passphrase)
        if vault.id != state.vault:
            raise SyncError("passphrase_needed", PASSPHRASE_NEEDED_MESSAGE)
        return cls(
            paths,
            state,
            vault,
            secrets=secrets,
            clock=clock,
            folder_fs=folder_fs,
            data_fs=data_fs,
            machine=machine,
            passphrase=passphrase,
        )

    # ---- state ------------------------------------------------------------------------------------

    def save(self) -> None:
        self.local.save(self.state)

    def reload_state(self) -> None:
        loaded = self.local.load()
        if loaded is not None:
            self.state = loaded
        self.files = self.local.load_files() or self.files

    def tick(self) -> None:
        """Add the running time since the last call (GC's grace counts it, finding 20)."""
        now = self.clock.monotonic()
        elapsed = max(0.0, now - self._ticked)
        self._ticked = now
        self.state.runtime += min(elapsed, 86_400.0)  # a monotonic clock that jumped is not believed

    def passphrase_now(self) -> str:
        """The sync passphrase, read from the password store now (a kept copy is encrypted with it)."""
        try:
            value = self.secrets.get(keyring_account(self.state.computer))
        except SecretsUnavailable as exc:
            raise SyncError("passphrase_needed", str(exc)) from None
        if not value:
            raise SyncError("passphrase_needed", PASSPHRASE_NEEDED_MESSAGE)
        return value

    def notice(self, code: SyncNoticeCode, message: str, kept: str | None = None) -> Notice:
        notice = Notice(id=tokens.token_hex(6), code=code, message=message, kept=kept, at=self.clock.iso())
        self.state.notices = [*self.state.notices, notice][-20:]
        self.save()
        return notice

    def dismiss(self, notice_id: str) -> bool:
        before = len(self.state.notices)
        self.state.notices = [n for n in self.state.notices if n.id != notice_id]
        if len(self.state.notices) == before:
            return False
        self.save()
        return True

    def log(
        self, store: Store | None, kind: str, message: str, data: dict[str, object] | None = None
    ) -> None:
        """A privacy-log row (only the computer in use writes them; they travel with the data)."""
        if store is None:
            return
        with _bookkeeping():
            store.log_activity(kind, message, data=data or {})

    # ---- heads ------------------------------------------------------------------------------------

    @property
    def head_file(self) -> str:
        return self.vault.head_name(self.state.computer)

    @property
    def key(self) -> int:
        return self.state.keys.setdefault(self.head_file, max(self.state.keys.values(), default=0) + 1)

    def own_head(self, written: int, *, version: VersionRef | None = None) -> Head:
        state = self.state
        cal_target: str | None = None
        cal_mode: str | None = None
        calendar = self._calendar()
        if calendar is not None:
            cal_target, cal_mode = calendar_target(calendar.url, calendar.username), calendar.mode
        return Head(
            format=FOLDER_FORMAT,
            vault=self.vault.id,
            computer=state.computer,
            name=state.name,
            written=written,
            state=state.head_state,
            epoch=state.epoch,
            version=version if version is not None else (state.base.ref if state.base is not None else None),
            has=state.has,
            pnum=state.pnum,
            wants=list(state.wants)[:64],
            forgotten=list(state.forgotten),
            app_version=__version__,
            schema_version=latest_version(),
            calendar_target=cal_target,
            calendar_mode=cal_mode,
        )

    def _calendar(self) -> CalendarSyncState | None:
        """This computer's calendar connection (its head names the target, never the address)."""
        if not self.paths.db.is_file():
            return None
        conn = sqlite3.connect(f"{self.paths.db.resolve().as_uri()}?mode=ro", uri=True)
        try:
            return calendar_state(conn)
        except sqlite3.DatabaseError:
            return None
        finally:
            conn.close()

    def write_head(self, *, version: VersionRef | None = None, state: str | None = None) -> None:
        """Rewrite this computer's head (``written`` reserved in ``state.json`` first)."""
        if state is not None:
            self.state.head_state = state  # type: ignore[assignment]
        self.state.written += 1
        self.save()
        head = self.own_head(self.state.written, version=version)
        sealed = self.vault.seal("h", self.head_file, head.model_dump_json().encode("utf-8"))
        self.folder.write_head(self.head_file, sealed)
        self.heads[self.head_file] = head
        with contextlib.suppress(OSError):
            self.local.save_heads(self.heads)

    def max_epoch(self) -> int:
        epochs = [h.epoch for h in self.heads.values()]
        if self.view is not None:
            epochs.append(self.view.max_epoch)
        return max([self.state.epoch, *epochs])

    def claimed_elsewhere(self) -> bool:
        """The fence: a higher ``(epoch, computer)`` than this computer's claim is in ``h/`` now."""
        view, _heads = self.scanner.scan(self.state, self.heads)
        mine = (self.state.epoch, self.state.computer)
        return any(
            (h.head.epoch, h.computer) > mine
            for h in view.heads
            if not h.this and not h.left and not h.forgotten
        )

    def mark(self, store: Store, version: VersionId, *, person_row: bool = False) -> None:
        """``sync_mark`` names the version the database now equals (a local key: digest-neutral)."""
        with _bookkeeping():
            store.set_meta(SYNC_MARK_KEY, version.key())
            if person_row and store.get_meta(PERSON_META_KEY) is None:
                store.set_meta(PERSON_META_KEY, "0")

    def remember_records(
        self, ref: VersionRef, manifest: bytes, buckets: list[tuple[BucketRef, bytes]]
    ) -> None:
        self._own_records = {ref.manifest: manifest}
        for bucket_ref, content in buckets:
            self._own_records[self.vault.object_name("b", bucket_ref.sha256)] = content

    # ---- looking --------------------------------------------------------------------------------

    def scan(self) -> FolderView:
        """Read the folder (:mod:`ordnung.sync.scan`), with the completeness of every other version,
        and keep this computer's own head right: rewritten when it is missing, rolled back or not the
        last one written (finding 7); ``has`` and ``wants`` updated."""
        self.tick()
        view, heads = self.scanner.scan(self.state, self.heads)
        if heads != self.heads:
            self.heads = heads
            with contextlib.suppress(OSError):
                self.local.save_heads(heads)
        done: dict[str, Completeness] = {}
        final: list[HeadView] = []
        base = self.state.base.ref if self.state.base is not None else None
        for head in view.heads:
            version = head.head.version
            if not head.this and not head.forgotten and version is not None and not head.newer:
                key = version.id.key()
                if key not in done:
                    if base is not None and version.id == base.id:
                        done[key] = Completeness(True)
                    else:
                        done[key] = self.scanner.completeness(version, self.files)
                head = dataclasses.replace(head, completeness=done[key])
            final.append(head)
        view = dataclasses.replace(view, heads=tuple(final))
        if view.problem is None:
            damaged = sorted({n for c in done.values() for n in c.damaged})
            if damaged:
                view = dataclasses.replace(view, problem=Problem("damaged", damaged[0]))
        self.view = view
        if view.problem is None or view.problem.code in ("damaged", "newer_ordnung"):
            self._keep_own_head(view)
        self.save()
        return view

    def _keep_own_head(self, view: FolderView) -> None:
        state = self.state
        if not self.started or (state.written == 0 and state.base is None):
            return  # before start() raised the counters, this computer's head is never written
        rewrite = view.own_stale
        wants = self.scanner.wanted()
        if wants != state.wants:
            state.wants = wants
            rewrite = True
        if state.mode == "standing_by":
            holder = view.by_computer(view.holder) if view.holder else None
            has = None
            if holder is not None and not holder.this and holder.head.version is not None and holder.complete:
                has = holder.head.version.id
            if has is not None and has != state.has:
                state.has = has
                rewrite = True
        if rewrite:
            self.write_head()
        self._serve_wants(view)

    def _serve_wants(self, view: FolderView) -> None:
        """Write again, forced, what another computer can't read and this one has (finding 7)."""
        if not view.wants:
            return
        by_object = {self.vault.object_name("f", c.sha256): (path, c) for path, c in self.files.items()}
        base = self.state.base.ref if self.state.base is not None else None
        if base is not None and base.id.computer == self.state.computer and self.state.mode == "in_use":
            with contextlib.suppress(Exception):
                manifest = self.scanner.manifest(base)
                if manifest is not None:
                    slices = {self.vault.object_name("d", piece.sha256) for piece in manifest.db.slices}
                    # a slice can't be made again from a database that moved on: a new version instead
                    self._heal_push = self._heal_push or bool(slices & view.wants)
        for name in sorted(view.wants):
            with contextlib.suppress(OSError, SyncError):
                content = self._own_records.get(name)
                if content is not None:
                    is_manifest = self.state.base is not None and name == self.state.base.ref.manifest
                    self._rewrite_record("m" if is_manifest else "b", name, content)
                elif name in by_object:
                    path, cached = by_object[name]
                    self._rewrite_file(name, self.paths.data_dir / path, cached)
        self.folder.flush()

    def _rewrite_record(self, kind: Literal["m", "b"], name: str, content: bytes) -> None:
        sealed = self.vault.seal(kind, name, content)
        self.folder.write_object(
            name, sealed_size_of(len(content)), lambda out: out.write(sealed), force=True
        )

    def _rewrite_file(self, name: str, source: Path, cached: FilesCacheEntry) -> None:
        if file_sha(source) != cached.sha256:
            return  # it changed here: the next push carries the new content

        def produce(out: BinaryIO) -> None:
            self.vault.seal_to(out, "f", name, cached.size, chunks_of(source))

        self.folder.write_object(name, sealed_size_of(cached.size), produce, force=True)

    def counter(self, store: Store) -> int | None:
        return _counter(store)

    def pending(self, store: Store) -> bool:
        counter = _counter(store)
        return self.state.force_person or counter is None or counter > self.state.pushed

    def local_view(self, store: Store, *, snapshot: Snapshot | None = None) -> LocalView:
        state = self.state
        return LocalView(
            computer=state.computer,
            mode=state.mode,
            base=state.base.ref if state.base is not None else None,
            pending=self.pending(store) if state.base is not None else False,
            next_pnum=state.pnum + 1,
            digest=snapshot.digest
            if snapshot is not None
            else (state.base.ref.digest if state.base else None),
            has_person_data=snapshot.person_data if snapshot is not None else has_person_data(store._conn()),
            key=self.key,
            recent=frozenset(ref.id.key() for ref in state.recent),
        )

    def snapshot(self, *, demo: bool = False) -> Snapshot:
        return take_snapshot(self, demo=demo)

    # ---- start ------------------------------------------------------------------------------------

    def start(self, store: Store) -> Problem | None:
        """At every start, with the Store open: F32, the counters, F3 and the local-rollback check."""
        state = self.state
        if state.data_dir != str(self.paths.data_dir.resolve()) or state.machine != self.machine():
            self.problem = Problem("copied_folder")
            return self.problem
        journal = unfinished(self.paths)
        if journal is not None:
            self.problem = Problem("pull_unfinished", journal.failed or "")
            return self.problem
        view = self.scan()
        self._raise_counters(view)
        self.problem = self._check_mark(store, view)
        self.started = True
        self.save()
        return self.problem

    def _raise_counters(self, view: FolderView) -> None:
        """Finding 4: never reuse a number the folder already shows (a data folder put back from an OS
        backup has older counters)."""
        state, me = self.state, self.state.computer
        heads = [*self.heads.values(), *(h.head for h in view.heads)]
        for head in heads:
            if head.computer == me:
                state.written = max(state.written, head.written)
                state.epoch = max(state.epoch, head.epoch)
                state.pnum = max(state.pnum, head.pnum)
            for ref in (head.version,):
                if ref is not None:
                    state.pnum = max(state.pnum, lin.highest(lin.knowledge(ref.lineage), me))
                    if ref.id.computer == me:
                        state.seq = max(state.seq, ref.id.seq)
            if head.has is not None and head.has.computer == me:
                state.seq = max(state.seq, head.has.seq)
        for ref in state.recent:
            if ref.id.computer == me:
                state.seq = max(state.seq, ref.id.seq)

    def _own_version(self) -> VersionRef | None:
        head = self.heads.get(self.head_file)
        if (
            head is not None
            and head.computer == self.state.computer
            and head.version is not None
            and (self.state.base is None or head.written >= self.state.written)
        ):
            return head.version
        return self.state.base.ref if self.state.base is not None else None

    def _check_mark(self, store: Store, view: FolderView) -> Problem | None:
        state = self.state
        if state.base is None:
            return None
        mark = store.get_meta(SYNC_MARK_KEY)
        own = self._own_version()
        assert own is not None
        if mark != own.id.key() and own.id.computer == state.computer:
            # F3 again: the head was written and the process died before ``sync_mark`` — the database
            # then holds exactly that version (a database put back from an OS backup doesn't)
            with contextlib.suppress(Exception):
                if take_snapshot(self).digest == own.digest:
                    self.mark(store, own.id)
                    state.pushed = _counter(store) or 0
                    mark = own.id.key()
        if mark == own.id.key():
            if own.id != state.base.ref.id:  # F3: the head was written, state.json wasn't
                summary = state.base.summary
                with contextlib.suppress(Exception):
                    manifest = self.scanner.manifest(own)
                    if manifest is not None:
                        summary = manifest.summary
                state.base = BaseInfo(
                    ref=own, summary=summary, arrived_at=self.clock.iso(), from_name=state.name
                )
                state.recent = [*[r for r in state.recent if r.id != own.id], own][-16:]
            return None
        return Problem("local_rollback")

    def repair_rollback(self, store: Store) -> Outcome:
        """F10 / finding 4: the local database went back in time. Keep a copy of what is here, then
        bring this computer's own last saved version back (it is still its head)."""
        own = self._own_version()
        if own is None:
            raise SyncError("not_needed", "There is nothing to put back.")
        head = self.own_head(self.state.written, version=own)
        view = HeadView(file=self.head_file, head=head, key=self.key, this=True)
        completeness = self.scanner.completeness(own, self.files)
        if not completeness.ready:
            raise NotArrived()
        view = dataclasses.replace(view, completeness=completeness)
        kept = keep_local(self, "before this computer's last saved state was put back", digest=None)
        staged = self.stage(view, keep=True)
        applied = apply(self, staged, store, kept=kept.name, expect_person=_counter(store))
        self.problem = None
        notice = self.notice(
            "rolled_back",
            "This computer's data went back in time (a power cut?). Its last saved state was put back; "
            "what was found is kept as a copy.",
            kept.name,
        )
        return Outcome(Pull(view, keep=True), applied=applied, kept=kept, replaced=True, notice=notice)

    def keep_as_is(self, store: Store) -> None:
        """ "Keep this computer's data as it is": its data becomes a person change on top of the version
        the database says it holds (the others are asked if that conflicts — nothing is lost)."""
        if self.problem is None or self.problem.code != "local_rollback":
            raise SyncError("not_needed", "There's nothing to confirm now.")
        mark = store.get_meta(SYNC_MARK_KEY)
        found = next((r for r in self.state.recent if r.id.key() == mark), None)
        if found is not None and self.state.base is not None:
            self.state.base = BaseInfo(
                ref=found,
                summary=self.state.base.summary,
                arrived_at=self.clock.iso(),
                from_name=self.state.name,
            )
        self.state.force_person = True
        if self.state.base is not None:
            self.mark(store, self.state.base.ref.id)
        self.problem = None
        self.save()

    def confirm_same_computer(self) -> None:
        if self.problem is None or self.problem.code != "copied_folder":
            raise SyncError("not_needed", "There's nothing to confirm now.")
        self.state.data_dir = str(self.paths.data_dir.resolve())
        self.state.machine = self.machine()
        self.problem = None
        self.save()

    # ---- pushing ----------------------------------------------------------------------------------

    def push(self, store: Store | None, **options: object) -> PushResult:
        """:func:`ordnung.sync.push.push` (the folder must be usable)."""
        with _bookkeeping():
            return push(self, store, **options)  # type: ignore[arg-type]

    # ---- pulling ----------------------------------------------------------------------------------

    def stage(self, head: HeadView, *, keep: bool = False) -> Staged:
        return stage(self, head, keep=keep)

    def keep_local(self, why: str, *, digest: str | None = None) -> KeptInfo:
        return keep_local(self, why, digest=digest)

    def apply(
        self,
        staged: Staged,
        store: Store | None,
        *,
        kept: str | None = None,
        expect_person: int | None = None,
    ) -> Applied:
        with _bookkeeping():
            return apply(self, staged, store, kept=kept, expect_person=expect_person)

    def bring_over(
        self,
        store: Store,
        head: HeadView,
        *,
        keep: bool,
        why: str,
        digest: str | None,
        expect_person: int | None,
    ) -> tuple[Applied, KeptInfo | None]:
        """Stage ``head``'s version, keep a copy when needed (Rule K, extended by finding 18: a quiet pull
        that would remove letters keeps one too), then apply it."""
        staged = self.stage(head, keep=keep)
        try:
            if not keep and removed_letters(staged, store) > 0:
                keep, why = True, f"before bringing in {head.head.name}'s changes, which remove letters"
            kept = self.keep_local(why, digest=digest) if keep else None
        except BaseException:
            shutil.rmtree(self.local.incoming, ignore_errors=True)
            raise
        applied = self.apply(staged, store, kept=kept.name if kept else None, expect_person=expect_person)
        return applied, kept

    def claim(self, store: Store | None = None) -> None:
        """Make this computer the one in use: a new epoch, written into its head — nothing uploaded."""
        if self.view is None:
            self.scan()
        self.state.epoch = self.max_epoch() + 1
        self.state.mode = "in_use"
        self.state.has = None
        self.state.waiting = None
        self.write_head(state="in_use")

    def become_standby(self, store: Store | None, *, late_push: bool, demo: bool = False) -> Outcome:
        """R3: another computer is in use. Push late when changes are pending; then stand by."""
        pushed = None
        if late_push and store is not None:
            pushed = self.push(store, head_state="standing_by", demo=demo)
            if pushed.outcome != "pushed":
                self.write_head(state="standing_by")
        else:
            self.write_head(state="standing_by")
        self.state.mode = "standing_by"
        self.save()
        return Outcome(BecomeStandby(late_push), pushed=pushed)

    # ---- one round --------------------------------------------------------------------------------

    def round(self, store: Store, *, demo: bool = False) -> Outcome:
        """One periodic step (module doc): what :func:`~ordnung.sync.decide.decide` says, done."""
        if self.problem is not None and self.problem.code in (
            "copied_folder",
            "local_rollback",
            "pull_unfinished",
        ):
            return Outcome(Paused(self.problem))
        view = self.scan()
        if self.state.mode == "standing_by":
            return self._standing_by_round(store, view, demo=demo)
        snap = self.snapshot(demo=demo)
        local = self.local_view(store, snapshot=snap)
        decision = decide(local, view)
        if isinstance(decision, BecomeStandby):
            return self.become_standby(store, late_push=decision.late_push, demo=demo)
        if isinstance(decision, BringIn):
            applied, kept = self.bring_over(
                store,
                decision.target,
                keep=False,
                why=f"before bringing in {decision.target.head.name}'s changes",
                digest=snap.digest,
                expect_person=_counter(store),
            )
            notice = self.notice(
                "brought_in",
                f"Brought in a change from {decision.target.head.name} that arrived late.",
                kept.name if kept else None,
            )
            self.log(
                store,
                "sync.brought_in",
                f"Brought in a change from {decision.target.head.name} that arrived late.",
                {"from": decision.target.head.name},
            )
            self.write_head(state="in_use")
            return Outcome(decision, applied=applied, kept=kept, replaced=True, notice=notice)
        if isinstance(decision, Push) or (isinstance(decision, Idle) and self._heal_push):
            pushed = self.push(store, snapshot=snap, demo=demo, force=self._heal_push, rewrite=view.wants)
            self._heal_push = False
            self._after_push(store, view)
            return Outcome(decision, pushed=pushed)
        if isinstance(decision, Idle | Paused):
            if isinstance(decision, Paused) and decision.problem.code == "newer_ordnung":
                return Outcome(decision)
            self._after_push(store, view)
        return Outcome(decision)

    def _after_push(self, store: Store, view: FolderView) -> None:
        now = self.clock.monotonic()
        if self._healed_at is None or now - self._healed_at >= SELF_HEAL_EVERY_S:
            self._healed_at = now
            with contextlib.suppress(SyncError, OSError):
                self.self_heal(store)
        with contextlib.suppress(SyncError, OSError):
            self.gc()

    def _standing_by_round(self, store: Store, view: FolderView, *, demo: bool) -> Outcome:
        local = self.local_view(store)
        decision = decide(local, view)
        if isinstance(decision, Standby) and decision.late_push:
            pushed = self.push(store, head_state="standing_by", demo=demo)
            return Outcome(decision, pushed=pushed)
        waiting = self.state.waiting
        if waiting is not None:
            return self._waiting_round(store, view, waiting, demo=demo)
        return Outcome(decision)

    def _waiting_round(self, store: Store, view: FolderView, waiting: Waiting, *, demo: bool) -> Outcome:
        """Finding 23: a waiting take-over ends when its target saved a new person change, or after
        :data:`~ordnung.sync.TAKE_OVER_WAIT_MAX_S`; otherwise it finishes once everything arrived."""
        target = view.by_computer(waiting.head)
        expired = self.state.runtime - waiting.runtime >= TAKE_OVER_WAIT_MAX_S
        moved = target is not None and target.head.pnum > waiting.target_pnum
        if expired or moved or target is None:
            self.state.waiting = None
            why = (
                f"{target.head.name} saved a new change meanwhile"
                if moved and target is not None
                else "nothing more arrived for 30 minutes"
            )
            notice = self.notice("take_over_cancelled", f"Stopped waiting to use Ordnung here: {why}.")
            return Outcome(Paused(Problem("arrival_stalled")), notice=notice)
        if target.complete:
            if waiting.choose:
                return self.choose(store, target.key, demo=demo)
            return self.use_here(store, demo=demo)
        return Outcome(Wait(target, choose=waiting.choose), waiting=True)

    # ---- the person's actions ---------------------------------------------------------------------

    def use_here(self, store: Store, *, older_copy: bool = False, demo: bool = False) -> Outcome:
        """ "Use Ordnung here" (the U rows)."""
        self._refuse_demo(store, demo)
        if self.problem is not None and self.problem.code in ("copied_folder", "pull_unfinished"):
            raise SyncError(
                "folder_problem" if self.problem.code == "copied_folder" else "pull_unfinished",
                "This computer has to be sorted out first (Settings → Your computers).",
            )
        for _attempt in range(3):
            view = self.scan()
            snap = self.snapshot(demo=demo)
            local = self.local_view(store, snapshot=snap)
            decision = decide(local, view, Action("use_here", older_copy=older_copy))
            if isinstance(decision, AlreadyInUse):
                return Outcome(decision)
            if isinstance(decision, LatePush):
                self.push(store, snapshot=snap, demo=demo)
                continue
            if isinstance(decision, Claim):
                self._log_take_over(store, view, replaced=False)
                self.claim(store)
                return Outcome(decision)
            if isinstance(decision, Pull):
                why = f"before you used {decision.target.head.name}'s Ordnung here"
                applied, kept = self.bring_over(
                    store,
                    decision.target,
                    keep=decision.keep,
                    why=why,
                    digest=snap.digest,
                    expect_person=_counter(store),
                )
                notice = None
                if decision.keep and kept is not None:
                    notice = self.notice(
                        "chosen_elsewhere",
                        f"On {decision.target.head.name} you chose {decision.target.head.name}'s Ordnung. This "
                        f"computer's was saved as an encrypted copy: {kept.name}.",
                        kept.name,
                    )
                elif kept is not None:
                    notice = self.notice(
                        "kept", "Saved this computer's earlier data as an encrypted copy.", kept.name
                    )
                self.claim(store)
                self._log_take_over(store, view, replaced=True, source=decision.target)
                return Outcome(decision, applied=applied, kept=kept, replaced=True, notice=notice)
            if isinstance(decision, Wait):
                version = decision.target.head.version
                assert version is not None
                self.state.waiting = Waiting(
                    target=version.id,
                    head=decision.target.computer,
                    target_pnum=decision.target.head.pnum,
                    since=self.clock.iso(),
                    runtime=self.state.runtime,
                )
                self.save()
                return Outcome(decision, waiting=True)
            if isinstance(decision, Choice):
                return Outcome(decision)
            if isinstance(decision, Paused):
                raise _paused_error(decision.problem)
            return Outcome(decision)
        raise SyncError("folder_problem", "Ordnung couldn't save this computer's changes first. Try again.")

    def cancel_wait(self) -> None:
        self.state.waiting = None
        self.save()

    def _log_take_over(
        self, store: Store, view: FolderView, *, replaced: bool, source: HeadView | None = None
    ) -> None:
        about = source or (view.by_computer(view.holder) if view.holder else None)
        name = about.head.name if about is not None else "your other computer"
        self.log(
            store, "sync.taken_over", f"Ordnung moved here from {name}.", {"from": name, "replaced": replaced}
        )

    def choose(self, store: Store, key: int, *, demo: bool = False) -> Outcome:
        """Keep the side ``key`` (this computer's own key, or another computer's)."""
        self._refuse_demo(store, demo)
        view = self.scan()
        snap = self.snapshot(demo=demo)
        local = self.local_view(store, snapshot=snap)
        decision = decide(local, view, Action("choose", key=key))
        if isinstance(decision, NoChoice):
            raise SyncError("no_choice", "There's no such computer to choose.")
        if isinstance(decision, Paused):
            raise _paused_error(decision.problem)
        base = self.state.base.ref.lineage if self.state.base is not None else Lineage()
        if isinstance(decision, ChooseThis):
            chosen = lin.keep_this(base, decision.others)
            self.log(
                store,
                "sync.chosen",
                "You kept this computer's Ordnung. The other's stays on that computer as a kept copy once it next starts.",
                {"kept": self.state.name},
            )
            pushed = self.push(store, lineage=chosen, claim=True, head_state="in_use", force=True, demo=demo)
            self.state.mode = "in_use"
            self.state.waiting = None
            self.save()
            return Outcome(decision, pushed=pushed)
        if isinstance(decision, Wait):
            version = decision.target.head.version
            assert version is not None
            self.state.waiting = Waiting(
                target=version.id,
                head=decision.target.computer,
                target_pnum=decision.target.head.pnum,
                since=self.clock.iso(),
                runtime=self.state.runtime,
                choose=True,
            )
            self.save()
            return Outcome(decision, waiting=True)
        assert isinstance(decision, ChooseOther)
        target = decision.target
        assert target.head.version is not None
        why = f"before you kept {target.head.name}'s Ordnung"
        applied, kept = self.bring_over(
            store, target, keep=True, why=why, digest=snap.digest, expect_person=_counter(store)
        )
        chosen = lin.keep_other(target.head.version.lineage, base, decision.others)
        self.log(
            store,
            "sync.chosen",
            f"You kept {target.head.name}'s Ordnung. This computer's was saved as {kept.name if kept else 'a kept copy'}.",
            {"kept": target.head.name, "copy": kept.name if kept else None},
        )
        pushed = self.push(store, lineage=chosen, claim=True, head_state="in_use", force=True, demo=demo)
        self.state.mode = "in_use"
        self.state.waiting = None
        self.save()
        notice = self.notice(
            "kept",
            f"Kept {target.head.name}'s Ordnung. This computer's is saved as a backup (Settings → Your computers).",
            kept.name if kept else None,
        )
        return Outcome(decision, pushed=pushed, applied=applied, kept=kept, replaced=True, notice=notice)

    def forget(self, key: int) -> KeptInfo | None:
        """Forget a lost computer (§13.5): its changes found nowhere else are kept here first."""
        view = self.scan()
        target = view.by_key(key)
        if target is None or target.this:
            raise SyncError("not_found", "No other computer of this sync has that number.")
        if view.holder == target.computer:
            raise SyncError("in_use", f"{target.head.name} is the computer in use. Use Ordnung here first.")
        kept = None
        version = target.head.version
        base = self.state.base.ref.lineage if self.state.base is not None else Lineage()
        if version is not None and not lin.contains(base, version.lineage):
            if not target.complete:
                raise SyncError(
                    "not_arrived", f"{target.head.name}'s latest changes haven't arrived here yet."
                )
            staged = self.stage(target)
            try:
                kept = keep_staged(self, staged, f"{target.head.name}'s changes, before it was removed")
            finally:
                shutil.rmtree(self.local.incoming, ignore_errors=True)
        self.state.forgotten = sorted({*self.state.forgotten, target.computer})
        self.write_head()
        with contextlib.suppress(OSError, SyncError):
            self.folder.remove_temps(self.vault.temp_tag(target.computer))
        return kept

    def refill(self, store: Store) -> PushResult:
        """Fill an emptied folder again from this computer (§13.4): the same key file, then everything."""
        view = self.scan()
        if view.problem is None or view.problem.code != "folder_empty" or self.state.mode != "in_use":
            raise SyncError("not_needed", "The sync folder isn't empty, or another computer is in use.")
        self.folder.create_key_file(self.state.key_file, bytes.fromhex(self.state.key_file_bytes))
        self.state.present = {}
        self.state.garbage = {}
        self.save()
        return self.push(store, force=True, head_state="in_use")

    def self_heal(self, store: Store) -> int:
        """Finding 7: this computer's own version must be whole in the folder — one listing per shard;
        missing or short objects are written again (a new version when a slice can't be made again)."""
        base = self.state.base.ref if self.state.base is not None else None
        if base is None or base.id.computer != self.state.computer:
            return 0
        completeness = self.scanner.completeness(base, {})
        if completeness.ready:
            return 0
        missing = completeness.need - completeness.have
        # what failed to verify is there with the right size: written again, forced
        failing = frozenset(self.scanner.damaged_since) | frozenset(self.scanner.missing_since)
        self.state.present = {}
        self.push(store, force=True, rewrite=failing)
        return missing

    def gc(self) -> int:
        """Delete objects unreferenced for 7 days of wall clock and 7 × 24 h of running time (§10.7,
        finding 20) — superseded database slices after a day (finding 21, :meth:`_superseded`); at most
        once a day, only in use, never while a head is unreadable or replayed."""
        state = self.state
        now = self.clock.wall()
        if (
            state.mode != "in_use"
            or self.view is None
            or self.view.uncertain
            or self.view.problem is not None
        ):
            return 0
        if state.last_gc_at is not None:
            last = datetime.fromisoformat(state.last_gc_at)
            if (
                now - last
            ).total_seconds() < GC_EVERY_S and state.runtime - state.last_gc_runtime < GC_EVERY_S:
                return 0
        referenced = self._referenced()
        if referenced is None:
            return 0
        superseded = self._superseded(referenced)
        removed = 0
        for prefix in self.folder.shard_names():
            for name in self.folder.shard(prefix):
                if name in referenced:
                    state.garbage.pop(name, None)
                    continue
                seen = state.garbage.get(name)
                if seen is None:
                    state.garbage[name] = Garbage(
                        since=now.isoformat(timespec="seconds"), runtime=state.runtime
                    )
                    continue
                age = (now - datetime.fromisoformat(seen.since)).total_seconds()
                wall, running = (
                    (SUPERSEDED_SLICE_GRACE_S, SUPERSEDED_SLICE_GRACE_S)
                    if name in superseded
                    else (GC_GRACE_S, GC_GRACE_RUNTIME_S)
                )
                if age >= wall and state.runtime - seen.runtime >= running:
                    self.folder.delete_object(name)
                    state.garbage.pop(name, None)
                    state.present.pop(name, None)
                    removed += 1
        for name in list(state.garbage):
            if name in referenced:
                state.garbage.pop(name)
        self.folder.flush()
        state.last_gc_at = now.isoformat(timespec="seconds")
        state.last_gc_runtime = state.runtime
        self.save()
        return removed

    def _referenced(self) -> set[str] | None:
        """Every object a head names (left heads until a live head covers them; never forgotten ones),
        and what a waiting take-over needs. ``None``: some manifest can't be read now — no GC."""
        assert self.view is not None
        refs: list[VersionRef] = []
        live = [h for h in self.view.heads if not h.forgotten and not h.left]
        for head in self.view.heads:
            if head.forgotten or head.this or head.head.version is None:  # its own: from state, fresh
                continue
            version = head.head.version
            if head.left and any(
                other.head.version is not None and lin.covers(other.head.version.lineage, version.lineage)
                for other in live
            ):
                continue
            refs.append(version)
        if self.state.base is not None:
            refs.append(self.state.base.ref)
        has_ids = {h.head.has for h in self.view.heads if h.head.has is not None}
        refs.extend(r for r in self.state.recent if r.id in has_ids)
        names: set[str] = set()
        for ref in refs:
            try:
                manifest = self.scanner.manifest(ref)
            except Exception:
                return None
            if manifest is None:
                return None
            names.add(ref.manifest)
            for piece in manifest.db.slices:
                names.add(self.vault.object_name("d", piece.sha256))
            for bucket_ref in manifest.buckets:
                names.add(self.vault.object_name("b", bucket_ref.sha256))
                try:
                    bucket = self.scanner.bucket(bucket_ref.sha256, bucket_ref.size, bucket_ref.key)
                except Exception:
                    return None
                if bucket is None:
                    return None
                for entry in bucket.entries:
                    names.add(self.vault.object_name("f", entry.sha256))
        return names

    def _superseded(self, referenced: set[str]) -> set[str]:
        """Finding 21: the database slices of the versions this computer held lately (``recent``) that
        no head names any more and that every live head has moved past: the version it names or holds
        came later here, or (a version this computer never held) knows strictly more. They go after
        :data:`SUPERSEDED_SLICE_GRACE_S` instead of 7 days."""
        assert self.view is not None
        state = self.state
        if state.base is None:
            return set()
        order = {ref.id: index for index, ref in enumerate(state.recent)}
        if state.base.ref.id not in order:
            return set()
        live = [h for h in self.view.heads if not h.forgotten and not h.left and not h.this]
        if any(not h.readable for h in live):
            return set()

        def past(head: HeadView, ref: VersionRef) -> bool:
            version = head.head.version
            ids = [i for i in (head.head.has, version.id if version is not None else None) if i in order]
            if ids:
                return max(order[i] for i in ids) > order[ref.id]
            return (
                version is not None
                and lin.covers(version.lineage, ref.lineage)
                and not lin.same(version.lineage, ref.lineage)
            )

        names: set[str] = set()
        for ref in state.recent:
            if ref.manifest in referenced or order[ref.id] >= order[state.base.ref.id]:
                continue
            if not all(past(head, ref) for head in live):
                continue
            try:
                manifest = self.scanner.manifest(ref)
            except Exception:
                continue
            if manifest is not None:
                names.update(self.vault.object_name("d", piece.sha256) for piece in manifest.db.slices)
        return names - referenced

    # ---- leaving and stopping ---------------------------------------------------------------------

    def leave(
        self, store: Store, *, forget_passphrase: bool = True, unreceived_ok: bool = False, demo: bool = False
    ) -> None:
        """Stop syncing here (blocker 2): push what isn't saved, then write ``left`` with the version
        kept — it still counts for the others' content decisions. Refused (``not_received``) while no
        other computer has this one's latest, unless ``unreceived_ok``."""
        view = self.scan()
        needs_push = False
        if self.state.mode == "in_use" or self.pending(store):
            with contextlib.suppress(SyncError):
                snap = self.snapshot(demo=demo)
                needs_push = (
                    self.pending(store)
                    or self.state.base is None
                    or snap.digest != self.state.base.ref.digest
                )
        base = self.state.base.ref if self.state.base is not None else None
        if not unreceived_ok and (needs_push or not others_have(view, base)):
            raise SyncError("not_received", NOT_RECEIVED_MESSAGE)
        if self.state.mode == "in_use":
            self.log(store, "sync.disconnected", "This computer stopped syncing.")
            needs_push = True
        if needs_push:
            with contextlib.suppress(SyncError):
                self.push(store, demo=demo)
        self.write_head(state="left")
        if forget_passphrase:
            with contextlib.suppress(SecretsUnavailable):
                self.secrets.delete(keyring_account(self.state.computer))

    def save_now(self, store: Store, *, hand_over: bool = False, demo: bool = False) -> PushResult:
        """ "Save now" (``POST /api/sync/save``): push at once; ``hand_over`` then says ``closed`` and
        stands by, so another computer can take over (refused while standing by: ``standby``)."""
        if self.state.mode != "in_use":
            raise SyncError("standby", "Ordnung is in use on another computer.")
        pushed = self.push(store, head_state="closed" if hand_over else None, demo=demo)
        if hand_over:
            if pushed.outcome != "pushed":
                self.write_head(state="closed")
            self.state.mode = "standing_by"
            self.save()
        return pushed

    def close(self, store: Store, *, demo: bool = False) -> PushResult | None:
        """At shutdown: the computer in use saves and says it was closed."""
        if self.state.mode != "in_use":
            return None
        pushed = None
        with contextlib.suppress(SyncError):
            pushed = self.push(store, head_state="closed", demo=demo)
        if pushed is None or pushed.outcome != "pushed":
            self.write_head(state="closed")
        return pushed

    def _refuse_demo(self, store: Store, demo: bool) -> None:
        if demo or is_demo_dir(self.paths.data_dir) or store.get_settings().demo:
            raise SyncError("unavailable", DEMO_MESSAGE)


def _paused_error(problem: Problem) -> SyncError:
    code = problem.code
    if code == "passphrase_needed":
        return SyncError("passphrase_needed", PASSPHRASE_NEEDED_MESSAGE)
    if code == "newer_ordnung":
        return SyncError(
            "newer_ordnung", "Another computer runs a newer Ordnung. Update Ordnung on this computer."
        )
    if code == "pull_unfinished":
        return SyncError("pull_unfinished", "A take-over must finish (or be given up) first.")
    return SyncError("folder_problem", f"The sync folder can't be used now ({code.replace('_', ' ')}).")


# --------------------------------------------------------------------------------------------------
# connecting and disconnecting
# --------------------------------------------------------------------------------------------------


def inspect_folder(value: str, paths: Paths, settings: AppSettings | None = None) -> FolderInfo:
    return inspect(value, paths, settings)


def _base_state(
    paths: Paths,
    folder: Path,
    name: str,
    key_name: str,
    key_bytes: bytes,
    vault: Vault,
    machine: Callable[[], str],
) -> LocalState:
    computer = tokens.token_hex(16)
    return LocalState(
        complete=False,
        folder=str(folder),
        key_file=key_name,
        key_file_bytes=key_bytes.hex(),
        vault=vault.id,
        computer=computer,
        name=name,
        keyring_account=keyring_account(computer),
        data_dir=str(paths.data_dir.resolve()),
        machine=machine(),
    )


def connect(
    paths: Paths,
    folder: Path | str,
    name: str,
    passphrase: str,
    *,
    secrets: SecretStore,
    store: Store,
    keep: Literal["this", "folder"] | None = None,
    clock: Clock | None = None,
    folder_fs: FsOps | None = None,
    data_fs: FsOps | None = None,
    machine: Callable[[], str] = machine_id,
    demo: bool = False,
    settings: AppSettings | None = None,
) -> ConnectResult:
    """Set up a new sync folder here, or join an existing one (design §17.2 ``PUT /api/sync``)."""
    if demo or is_demo_dir(paths.data_dir) or store.get_settings().demo:
        raise SyncError("unavailable", DEMO_MESSAGE)
    local = Local(paths, data_fs)
    previous = local.load() if local.connected() else None
    if previous is not None and previous.complete:
        raise SyncError("already_connected", "This computer already syncs. Disconnect it first.")
    problem = name_problem(name)
    if problem is not None:
        raise SyncError("name", problem)
    name = clean_name(name)
    root = Path(str(folder)).expanduser()
    refused = folder_problem(str(root), paths, settings or store.get_settings())
    if refused is not None:
        raise SyncError("folder", refused)
    root = root.resolve()
    sync_folder = SyncFolder(root, folder_fs or TimedFs())
    if previous is not None and Path(previous.folder) == root:
        _withdraw_unfinished(sync_folder, previous)
    keys = sync_folder.key_files() if root.is_dir() else {}
    if len(keys) > 1:
        raise SyncError(
            "folder", "This folder holds two separate Ordnung syncs. Wait a minute and try again."
        )
    if not keys:
        return _create(
            paths,
            root,
            name,
            passphrase,
            secrets=secrets,
            store=store,
            clock=clock,
            folder_fs=folder_fs,
            data_fs=data_fs,
            machine=machine,
        )
    key_name = next(iter(keys))
    return _join(
        paths,
        root,
        key_name,
        name,
        passphrase,
        secrets=secrets,
        store=store,
        keep=keep,
        clock=clock,
        folder_fs=folder_fs,
        data_fs=data_fs,
        machine=machine,
    )


def _withdraw_unfinished(sync_folder: SyncFolder, previous: LocalState) -> None:
    """Finding 34: an interrupted setup left its key file (named in ``state.json``) and nothing else of
    another computer: take it back, so a retry with another passphrase isn't stranded."""
    keys = sync_folder.key_files()
    if previous.key_file not in keys:
        return
    data = sync_folder.read_key_file(previous.key_file)
    if data is None or data.hex() != previous.key_file_bytes:
        return
    if sync_folder.head_files():
        return
    sync_folder.unlink_key_file(previous.key_file)


def _store_passphrase(secrets: SecretStore, account: str, passphrase: str) -> None:
    try:
        secrets.set(account, passphrase)
    except SecretsUnavailable as exc:
        raise SyncError("unavailable", str(exc)) from None


def _create(
    paths: Paths,
    root: Path,
    name: str,
    passphrase: str,
    *,
    secrets: SecretStore,
    store: Store,
    clock: Clock | None,
    folder_fs: FsOps | None,
    data_fs: FsOps | None,
    machine: Callable[[], str],
) -> ConnectResult:
    problem = passphrase_problem(passphrase)
    if problem is not None:
        raise SyncError("passphrase", problem)
    if secrets.problem() is not None:
        raise SyncError("unavailable", str(secrets.problem()))
    made = new_key_file(passphrase)
    state = _base_state(paths, root, name, made.name, made.data, made.vault, machine)
    local = Local(paths, data_fs)
    local.save(state)  # finding 34: state.json (with the key file's bytes) first
    if not root.exists():
        (folder_fs or RealFs()).mkdir(root)
    session = Session(
        paths,
        state,
        made.vault,
        secrets=secrets,
        clock=clock,
        folder_fs=folder_fs,
        data_fs=data_fs,
        machine=machine,
        passphrase=passphrase,
    )
    session.started = True  # a new folder: nothing to reconcile
    session.folder.create_key_file(made.name, made.data)
    _store_passphrase(secrets, state.keyring_account, passphrase)
    with _bookkeeping():
        if store.get_meta(PERSON_META_KEY) is None:
            store.set_meta(PERSON_META_KEY, "0")
    state.mode = "in_use"
    state.head_state = "in_use"
    session.save()
    session.log(store, "sync.connected", f"Started syncing through {root} as {name}.", {"computer": name})
    pushed = session.push(store, claim=True, head_state="in_use", force=True)
    # only now (its head written) is the setup complete: an interrupted one is taken back on retry
    session.state.complete = True
    session.save()
    store.set_durable(True)
    return ConnectResult(True, created=True, outcome=Outcome(Push(), pushed=pushed), session=session)


def _join_inner(
    paths: Paths,
    root: Path,
    key_name: str,
    name: str,
    passphrase: str,
    *,
    secrets: SecretStore,
    store: Store,
    keep: Literal["this", "folder"] | None,
    clock: Clock | None,
    folder_fs: FsOps | None,
    data_fs: FsOps | None,
    machine: Callable[[], str],
) -> ConnectResult:
    sync_folder = SyncFolder(root, folder_fs or TimedFs())
    data = sync_folder.read_key_file(key_name)
    if data is None:
        raise NotArrived(
            "The sync folder's key file hasn't fully arrived yet. Wait until your sync tool has copied everything."
        )
    vault = open_key_file(key_name, data, passphrase)  # WrongSyncPassphrase / NewerSyncFolder / NotArrived
    if secrets.problem() is not None:
        raise SyncError("unavailable", str(secrets.problem()))
    state = _base_state(paths, root, name, key_name, data, vault, machine)
    session = Session(
        paths,
        state,
        vault,
        secrets=secrets,
        clock=clock,
        folder_fs=folder_fs,
        data_fs=data_fs,
        machine=machine,
        passphrase=passphrase,
    )
    view = session.scan()
    live = [h for h in view.heads if not h.left and not h.forgotten]
    if len(live) >= MAX_COMPUTERS:
        raise SyncError("full", FULL_MESSAGE)
    state.name = unique_name(name, {h.head.name for h in view.heads if not h.forgotten})
    snap = session.snapshot()
    local_view = LocalView(
        computer=state.computer,
        mode="standing_by",
        base=None,
        pending=False,
        next_pnum=1,
        digest=snap.digest,
        has_person_data=snap.person_data,
        key=session.key,
    )
    decision = decide(local_view, view, Action("use_here"))
    if isinstance(decision, NotYet):
        raise NotArrived(
            "This sync folder's computers haven't arrived here yet. Wait until your sync tool has copied "
            "everything, then try again."
        )
    if isinstance(decision, Paused):
        raise _paused_error(decision.problem)
    if isinstance(decision, Choice) and keep is None:
        return ConnectResult(False, choice=decision, session=None)
    # from here on this computer is connected
    state.mode = "standing_by"
    state.head_state = "standing_by"
    session.local.save(state)
    _store_passphrase(secrets, state.keyring_account, passphrase)
    with _bookkeeping():
        if store.get_meta(PERSON_META_KEY) is None:
            store.set_meta(PERSON_META_KEY, "0")
    state.complete = True
    session.started = True
    state.pushed = _counter(store) or 0
    session.save()
    store.set_durable(True)
    if isinstance(decision, Choice):
        assert keep is not None
        heads = [s.head for s in decision.sides if s.head is not None]
        others = tuple(h.head.version.lineage for h in heads if h.head.version is not None)
        if keep == "this":
            chosen = lin.keep_this(Lineage(), others)
            session.log(
                store, "sync.joined", "Started syncing and kept this computer's Ordnung.", {"from": None}
            )
            pushed = session.push(store, lineage=chosen, claim=True, head_state="in_use", force=True)
            session.state.mode = "in_use"
            session.save()
            return ConnectResult(True, outcome=Outcome(decision, pushed=pushed), session=session)
        target = max(heads, key=lambda h: (h.head.epoch, h.computer))
        target_version = target.head.version
        assert target_version is not None
        if not target.complete:
            session.state.waiting = Waiting(
                target=target_version.id,
                head=target.computer,
                target_pnum=target.head.pnum,
                since=session.clock.iso(),
                runtime=session.state.runtime,
                choose=True,
            )
            session.write_head(state="standing_by")
            return ConnectResult(
                True, outcome=Outcome(Wait(target, choose=True), waiting=True), session=session
            )
        applied, kept = session.bring_over(
            store,
            target,
            keep=True,
            why=f"before you joined {target.head.name}'s Ordnung",
            digest=snap.digest,
            expect_person=_counter(store),
        )
        chosen = lin.keep_other(target_version.lineage, Lineage(), others)
        session.claim(store)
        session.log(
            store,
            "sync.joined",
            f"Brought Ordnung over from {target.head.name} and started syncing.",
            {"from": target.head.name},
        )
        pushed = session.push(store, lineage=chosen, claim=False, head_state="in_use", force=True)
        return ConnectResult(
            True,
            outcome=Outcome(decision, pushed=pushed, applied=applied, kept=kept, replaced=True),
            session=session,
        )
    session.write_head(state="standing_by")
    if isinstance(decision, Pull):
        applied, kept = session.bring_over(
            store,
            decision.target,
            keep=decision.keep or snap.person_data,
            why=f"before you joined {decision.target.head.name}'s Ordnung",
            digest=snap.digest,
            expect_person=_counter(store),
        )
        session.claim(store)
        session.log(
            store,
            "sync.joined",
            f"Brought Ordnung over from {decision.target.head.name} and started syncing.",
            {"from": decision.target.head.name},
        )
        return ConnectResult(
            True, outcome=Outcome(decision, applied=applied, kept=kept, replaced=True), session=session
        )
    if isinstance(decision, Wait):
        version = decision.target.head.version
        assert version is not None
        session.state.waiting = Waiting(
            target=version.id,
            head=decision.target.computer,
            target_pnum=decision.target.head.pnum,
            since=session.clock.iso(),
            runtime=session.state.runtime,
        )
        session.save()
        return ConnectResult(True, outcome=Outcome(decision, waiting=True), session=session)
    # an empty folder of an existing sync (every other computer left): this one starts it again
    session.claim(store)
    pushed = session.push(store, head_state="in_use", force=True)
    return ConnectResult(True, outcome=Outcome(decision, pushed=pushed), session=session)


def _join(
    paths: Paths, root: Path, key_name: str, name: str, passphrase: str, **options: Any
) -> ConnectResult:
    """Join (:func:`_join_inner`); a join that didn't connect leaves no ``<data>/sync/`` behind."""
    local = Local(paths, options.get("data_fs"))
    existed = local.dir.exists()

    def undo() -> None:
        state = None
        with contextlib.suppress(Exception):
            state = local.load()
        if not existed and (state is None or not state.complete):
            shutil.rmtree(local.dir, ignore_errors=True)

    try:
        result = _join_inner(paths, root, key_name, name, passphrase, **options)
    except BaseException:
        undo()
        raise
    if not result.connected:
        undo()
    return result


def disconnect(
    paths: Paths,
    secrets: SecretStore,
    store: Store,
    *,
    session: Session | None = None,
    forget_passphrase: bool = True,
    unreceived_ok: bool = False,
    remove_kept: bool = False,
) -> None:
    """Stop syncing on this computer (``DELETE /api/sync``): the head says it left, ``<data>/sync/``
    goes (kept copies stay unless ``remove_kept``). The folder and the other computers keep everything."""
    local = Local(paths)
    if not local.connected():
        return
    if session is None:
        with contextlib.suppress(SyncError):
            session = Session.open(paths, secrets)
    if session is not None:
        session.leave(store, forget_passphrase=forget_passphrase, unreceived_ok=unreceived_ok)
    elif forget_passphrase:
        state = local.load()
        if state is not None:
            with contextlib.suppress(SecretsUnavailable):
                secrets.delete(keyring_account(state.computer))
    for entry in sorted(local.dir.iterdir()):
        if entry.name == "kept" and not remove_kept:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            with contextlib.suppress(FileNotFoundError):
                entry.unlink()
    if remove_kept:
        shutil.rmtree(local.dir, ignore_errors=True)
    with _bookkeeping():
        store.set_meta(SYNC_MARK_KEY, None)
    store.set_durable(False)


def push_once(paths: Paths, secrets: SecretStore, store: Store) -> str:
    """After an in-process CLI write: save now, best effort (one line for the person)."""
    if not Local(paths).connected():
        return ""
    try:
        session = Session.open(paths, secrets)
        if session.state.mode != "in_use":
            return "Not saved to the sync folder: Ordnung is in use on another computer."
        result = session.push(store)
    except SyncError as exc:
        return f"Not saved to the sync folder: {exc}"
    return "Saved to the sync folder." if result.outcome == "pushed" else "The sync folder is up to date."


def bucket_of(content: bytes) -> Bucket:
    return Bucket.model_validate_json(content)


__all__ += ["Applied", "PullAborted", "PullUnfinished", "Staged", "VersionId", "unfinished"]
