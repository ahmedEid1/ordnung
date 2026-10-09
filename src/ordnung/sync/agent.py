"""The sync agent: hand-off sync inside a running server — and, for one operation, on the command line
(policy: :mod:`ordnung.sync`; ADR 0018).

:class:`SyncAgent` is an :class:`~ordnung.api.deps.ApiState` field. It owns the loop that keeps this
computer in step with the sync folder, the lock that serialises every sync operation (a scan, a save, a
take-over, a choice, connecting), the unlocked session (keys in memory only) and the status that
``GET /api/sync`` answers from memory. Everything that touches the folder, the keyring or scrypt goes
through the engine (:mod:`ordnung.sync.engine`, the façade :class:`Engine`), in one daemon thread of the
agent's own (:class:`_EngineThread`): a call that hangs on a network share never holds up the event
loop, never keeps the process from exiting, and the next call waits behind it instead of racing it.

**Modes.** ``off`` (not connected, the demo, or no engine), ``starting`` (connected; the first look
hasn't happened), ``in_use`` and ``standing_by``. At start the computer takes its last known mode at
once (no keyring or scrypt on the critical path) and decides within :data:`~ordnung.sync.START_DECIDE_S`
when it can; the first decision may still move it to standing by later. Background work (readings, the
day change, the watched folder, calendar sync, desktop reminders) follows the mode: it runs when sync is
off or this computer is in use, never while it stands by (the host's ``start_background`` /
``stop_background``).

**The gate's side.** :mod:`ordnung.sync.gate` asks :meth:`SyncAgent.write_refusal` before a write runs
(409 ``standby`` while another computer is in use or while data is being brought over), counts the
writes in flight (:meth:`SyncAgent.admitted`) and marks the person's writes, whose transactions bump the
person counter (:data:`~ordnung.db.store.PERSON_WRITE`). :meth:`SyncAgent.person_wrote` only times the
next save (:data:`~ordnung.sync.PUSH_PERSON_QUIET_S` after the person's write,
:data:`~ordnung.sync.PUSH_QUIET_S` after background work's, :data:`~ordnung.sync.PUSH_MAX_WAIT_S` at
the latest); what a save counts as the person's comes from the counter in its own snapshot.

**Replacing the data: two phases** (critique finding 1). A take-over, a quiet bring-in, a choice:

1. the version is staged with writes still allowed;
2. the fence goes up — the gate refuses every write (``bringing_over``) — and the agent waits until the
   writes already admitted on both listeners finished (at most :data:`~ordnung.sync.FENCE_WAIT_S`,
   else it lifts the fence and tries again later);
3. background work stops and its threads drain (the server's
   :class:`~ordnung.app_context.DrainableExecutor`): a cancelled reading's thread can't commit into the
   replaced database;
4. the decision is taken again on a fresh local view: if a write moved anything, the staging is
   discarded and the next round decides afresh (a choice, typically);
5. only then: the kept copy (when the person's data would otherwise be lost), the apply (under
   ``ledger_lock`` and ``caldav.exclusive``), the claim, and the fence comes down.

The same two phases put this computer's own last saved state back when its data went back in time (a
power cut, a data folder put back from an OS backup: the decision ``repair``, review finding F10/4) —
a write made while that version is staged is in the kept copy, never in neither.

After a replace the settings are read again, the worker recovers the replaced database's jobs
(:meth:`~ordnung.ingest.worker.IngestWorker.reload`), background work starts fresh when this computer is
in use, and the app hears ``sync.updated {replaced: true}`` with the events that reload every page.

**Leaving.** Disconnect and Delete everything first save what isn't saved (behind the fence), then
write this computer's head as ``left`` with its version kept, so the other computers still bring that
version over (critique finding 2); both need a second confirmation (``not_received``) while no other
computer has this one's latest changes. Shutting down saves before background work gets its grace
period, then once more at the end (head ``closed``), each at most
:data:`~ordnung.sync.SHUTDOWN_PUSH_S`; within the last one's bound it also waits for an engine call that
outlived its limit, then for the engine's thread to end (its connection to the database closes with it),
so no thread of the agent's still uses or holds the database once Ordnung has stopped (Windows can't
delete or replace an open file).

**Never raises out of the loop.** Every failure becomes a :class:`~ordnung.sync.status.SyncProblem`
(logged with codes and counts only — never the passphrase, a letter's name or a path inside
``files/``), and the server keeps working. While the folder doesn't answer (``folder_unreachable``)
it is looked at every :data:`~ordnung.sync.UNREACHABLE_SCAN_S`. A waiting take-over gives up after
:data:`~ordnung.sync.TAKE_OVER_WAIT_MAX_S`, or when the computer it waits for saves a new change of
the person's, and says why.

Until the engine is part of this installation (``ordnung.sync.engine`` can't be imported), sync is
``off`` and unavailable.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import importlib
import logging
import queue
import sqlite3
import threading
import time
import unicodedata
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeVar, cast

from ordnung import clock
from ordnung.calendar import caldav
from ordnung.calendar.secrets import KeyringSecrets, SecretStore, SecretsUnavailable
from ordnung.config import Paths
from ordnung.db.store import background_context
from ordnung.demo.loader import is_demo_dir
from ordnung.ingest.pipeline import ledger_lock
from ordnung.models import AppSettings
from ordnung.sync import (
    ALLOWED_IN_STANDBY,
    ARRIVAL_PATIENCE_S,
    BRINGING_OVER_MESSAGE,
    DEMO_MESSAGE,
    FAILING_AFTER_S,
    FENCE_WAIT_S,
    FOLDER_OP_TIMEOUT_S,
    GC_EVERY_S,
    KEPT_DIR,
    KEPT_RE,
    KEPT_WARN_BYTES,
    NAME_MAX_CHARS,
    NOBODY_IN_USE_MESSAGE,
    NOT_CONNECTED_MESSAGE,
    PUSH_MAX_WAIT_S,
    PUSH_PERSON_QUIET_S,
    PUSH_QUIET_S,
    PUSH_RETRY_S,
    PUTTING_BACK_MESSAGE,
    ROLLBACK_NOTICE,
    SCAN_S,
    SHUTDOWN_PUSH_S,
    STANDBY_MESSAGE,
    START_DECIDE_S,
    TAKE_OVER_WAIT_MAX_S,
    UNREACHABLE_SCAN_S,
    WAIT_POLL_S,
    WATCH_S,
    NotArrived,
    Operation,
    SyncError,
    SyncErrorKind,
    SyncMode,
    SyncNoticeCode,
    SyncProblemCode,
    SyncRefused,
    passphrase_problem,
)
from ordnung.sync.status import (
    PROBLEMS,
    SyncArriving,
    SyncChoice,
    SyncComputer,
    SyncFolderInfo,
    SyncKept,
    SyncNotice,
    SyncProblem,
    SyncStatus,
    problem,
)

if TYPE_CHECKING:
    from ordnung.app_context import AppContext
    from ordnung.db.store import Store

log = logging.getLogger(__name__)

T = TypeVar("T")

NO_ENGINE_MESSAGE = "This installation of Ordnung can't sync between computers."
LOCK_POLL_S = 0.02
#: How often stopping looks whether the engine's thread is done (as the server's drain does).
ENGINE_POLL_S = 0.05
#: Stopping lets the engine's idle thread end and waits for that at most this long, looking every
#: ``THREAD_END_POLL_S``: the thread's connection to the database closes as it ends.
THREAD_END_WAIT_S = 1.0
THREAD_END_POLL_S = 0.005
BUSY_MESSAGE = "The sync folder doesn't answer yet. Try again in a moment."
NAME_MESSAGE = f"Give this computer a name of 1 to {NAME_MAX_CHARS} characters."
NO_CHOICE_MESSAGE = "There's nothing to choose (any more)."
NOT_RECEIVED_MESSAGE = (
    "No other computer has received this computer's latest changes yet. Confirm to go on anyway — they "
    "stay only in the sync folder (or nowhere, if they couldn't be saved)."
)
REFILL_NOT_NEEDED = "Only an emptied sync folder can be filled again, from the computer in use."
NOTHING_TO_CONFIRM = "There's nothing to confirm now."
NOTHING_TO_ABANDON = "No take-over is unfinished."
NO_COMPUTER_MESSAGE = "No other computer of this sync has that number."
IN_USE_MESSAGE = "That computer is the one in use: use Ordnung here first, then remove it."
CANT_OPEN_MESSAGE = "Ordnung can't open the sync folder right now."
SAVING_FIRST_MESSAGE = "Saving your changes to the sync folder first — one moment."
STILL_WRITING_MESSAGE = "Changes were still being made. Try again in a moment."
TOO_EARLY_MESSAGE = "Ordnung is still bringing your other computer's changes here."
WAIT_CANCELLED = {
    "expired": "Using Ordnung here was given up: your other computer's changes didn't arrive within 30 "
    "minutes. Try again once your sync tool has caught up.",
    "changed": "Using Ordnung here was given up: {name} saved new changes meanwhile. Use Ordnung here "
    "again to bring them over too.",
}
#: Problems while which this computer neither saves nor brings anything over.
_STOPPED: frozenset[SyncProblemCode] = frozenset(
    {"copied_folder", "forgotten", "folder_other", "two_setups", "pull_unfinished", "local_rollback"}
)
#: Problems a save reports (the folder filling up, saving failing for a while, a damaged original here): a look at
#: the folder that answers as it should doesn't end them; only a save that succeeds does.
_SAVE_PROBLEMS: tuple[SyncProblemCode, ...] = ("save_failing", "folder_full", "local_damaged")


# --------------------------------------------------------------------------------------------------
# the engine façade (sync/engine.py; design §24.3 I2): what the agent reads and calls
# --------------------------------------------------------------------------------------------------

#: What :func:`Engine.decide` answers (design §9): in use — ``paused`` (R1/R2; ``may_push`` while saving
#: goes on, finding 13), ``become_standby`` (R3), ``choice`` (R4), ``bring_in`` / ``arriving`` (R5),
#: ``push`` (R6), ``idle`` (R7); standing by — ``up_to_date``, ``arriving``, ``choice``, ``paused``;
#: for "Use Ordnung here" — ``nothing`` (U0), ``late_push`` (U1), ``pull`` (U2-U4, ``keep`` for Rule K),
#: ``claim`` (U2 at the local base, or the older copy), ``wait`` (the target hasn't arrived), ``choice``
#: (U5, joining with letters); in either mode — ``repair`` (this computer's data went back in time: its
#: own last saved version is put back, keeping a copy).
DecisionKind = Literal[
    "idle",
    "push",
    "paused",
    "become_standby",
    "choice",
    "bring_in",
    "arriving",
    "up_to_date",
    "late_push",
    "pull",
    "claim",
    "wait",
    "nothing",
    "repair",
]
#: Why a save runs; the head it writes says ``closed`` after ``shutdown``, ``left`` after ``leave``,
#: ``standing_by`` with ``hand_over``, and ``in_use`` otherwise.
PushReason = Literal["change", "save", "first", "late", "choice", "hand_over", "shutdown", "leave"]


@dataclass(frozen=True)
class UseHere:
    """The action "Use Ordnung here" (``older_copy``: claim at the copy this computer has)."""

    older_copy: bool = False


class Decision(Protocol):
    """A decision (``ordnung.sync.decide``). Unused fields are ``None``/``False``."""

    @property
    def kind(self) -> DecisionKind: ...
    @property
    def target(self) -> Any: ...  # the version to bring over (a VersionRef; compared with ==)
    @property
    def keep(self) -> bool: ...  # Rule K: keep a copy of the local data first
    @property
    def why(self) -> str | None: ...  # why a kept copy is written ("before you kept desktop's Ordnung")
    @property
    def late_push(self) -> bool: ...
    @property
    def may_push(self) -> bool: ...
    @property
    def choice(self) -> Any: ...  # SyncChoice-shaped
    @property
    def arriving(self) -> Any: ...  # SyncArriving-shaped
    @property
    def problem(self) -> Any: ...  # .code (SyncProblemCode), .message (str | None)
    @property
    def from_name(self) -> str | None: ...  # the computer the target comes from


class LocalSummary(Protocol):
    """``<data>/sync/state.json`` as the agent shows it — read without the keyring or the folder."""

    @property
    def folder(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def mode(self) -> Literal["in_use", "standing_by"]: ...
    @property
    def in_use_on(self) -> str | None: ...
    @property
    def last_saved_at(self) -> str | None: ...
    @property
    def base_from(self) -> str | None: ...
    @property
    def base_arrived_at(self) -> str | None: ...
    @property
    def notices(self) -> Sequence[Any]: ...  # SyncNotice-shaped
    @property
    def kept(self) -> Sequence[Any]: ...  # SyncKept-shaped
    @property
    def data_folder_synced(self) -> bool: ...
    @property
    def journal(self) -> bool: ...  # a pull journal exists (an unfinished take-over)


class FolderView(Protocol):
    """One look at the folder (``Session.scan``)."""

    @property
    def computers(self) -> Sequence[Any]: ...  # SyncComputer-shaped, this computer too
    @property
    def problem(self) -> Any: ...


class LocalView(Protocol):
    """This computer's data as the decision sees it (``Session.local_view``)."""

    @property
    def pending(self) -> bool: ...  # changes not saved yet (the person's, or a digest difference)


class ConnectResult(Protocol):
    @property
    def created(self) -> bool: ...  # a new folder (else: joined)
    @property
    def choice(self) -> Any: ...  # joining with letters and no ``keep``: nothing is connected yet


class ChooseResult(Protocol):
    @property
    def pull(self) -> Any: ...  # the chosen side's version to bring over (None: this computer's)
    @property
    def complete(self) -> bool: ...
    @property
    def arriving(self) -> Any: ...
    @property
    def why(self) -> str | None: ...
    @property
    def from_name(self) -> str | None: ...


class Session(Protocol):
    """The unlocked folder (``Session.open``: keyring and scrypt). Every method blocks."""

    def scan(self) -> FolderView: ...
    def local_view(self, store: Store) -> LocalView: ...
    def push(self, store: Store, *, reason: PushReason, hand_over: bool = False) -> Any: ...
    def stage(self, target: Any) -> Any: ...  # raises NotArrived, NewerSyncFolder, SyncError(no_space)
    def discard(self, staged: Any) -> None: ...
    def keep_local(self, paths: Paths, why: str) -> Any: ...
    def apply(self, staged: Any, store: Store) -> Any: ...
    def claim(self) -> None: ...
    def choose(self, store: Store, key: int) -> ChooseResult: ...
    def forget(self, key: int) -> None: ...
    def refill(self, store: Store) -> None: ...
    def gc(self) -> None: ...
    def keep_as_is(self, store: Store) -> None: ...


class Engine(Protocol):
    """``ordnung.sync.engine``. Everything blocks; the agent calls it in its thread, the CLI directly."""

    def local_summary(self, paths: Paths) -> LocalSummary | None: ...
    def kept_copies(self, paths: Paths) -> Sequence[Any]: ...  # SyncKept-shaped, connected or not
    def writes_refused(self, paths: Paths) -> str | None: ...
    def resume_interrupted(self, paths: Paths) -> Any: ...
    def inspect_folder(self, value: str, paths: Paths, settings: AppSettings) -> Any: ...
    def connect(
        self,
        paths: Paths,
        folder: Path,
        name: str,
        passphrase: str,
        *,
        secrets: SecretStore,
        keep: Literal["this", "folder"] | None,
        store: Store,
    ) -> ConnectResult: ...
    def open_session(self, paths: Paths, secrets: SecretStore) -> Session: ...
    def decide(self, local: LocalView, view: FolderView, action: UseHere | None) -> Decision: ...
    def push_once(self, paths: Paths, secrets: SecretStore) -> str: ...
    def set_passphrase(self, paths: Paths, secrets: SecretStore, passphrase: str) -> None: ...
    def change(
        self,
        paths: Paths,
        *,
        name: str | None = None,
        folder: Path | None = None,
        confirm_same_computer: bool = False,
        abandon_pull: bool = False,
        dismiss_notice: str | None = None,
        notice: tuple[SyncNoticeCode, str, str | None] | None = None,
    ) -> None: ...
    def disconnect(
        self, paths: Paths, secrets: SecretStore, *, forget_passphrase: bool, store: Store
    ) -> None: ...
    def delete_kept(self, paths: Paths, name: str) -> bool: ...


def load_engine() -> Engine | None:
    """The engine of this installation: the façade over the sync core (:mod:`ordnung.sync.facade`;
    ``None`` while it isn't part of it)."""
    try:
        module = importlib.import_module("ordnung.sync.facade")
    except ImportError:
        return None
    return cast(Engine, module.ENGINE)


def default_secrets() -> SecretStore:
    """Where this computer keeps the sync passphrase: the OS keyring under hand-off sync's own service
    (:data:`ordnung.sync.local.SyncSecrets`)."""
    try:
        from ordnung.sync.local import SyncSecrets
    except ImportError:
        return KeyringSecrets()
    return cast(SecretStore, SyncSecrets())


def name_problem(name: str) -> str | None:
    """Why ``name`` can't name a computer (``None``: it can)."""
    shown = name.strip()
    if not shown or len(shown) > NAME_MAX_CHARS:
        return NAME_MESSAGE
    if any(unicodedata.category(char).startswith("C") for char in shown):
        return NAME_MESSAGE
    return None


# --------------------------------------------------------------------------------------------------
# the host: background work around the agent (the server's ApiState; nothing on the command line)
# --------------------------------------------------------------------------------------------------


class Host(Protocol):
    """Starts and stops the background work the mode allows, and waits for its threads to finish."""

    async def start_background(self) -> None: ...
    async def stop_background(self, *, final: bool = False) -> None: ...
    async def drain(self, within: float) -> bool: ...


class NoBackground:
    """The command line's host: no background work runs there."""

    async def start_background(self) -> None:
        return None

    async def stop_background(self, *, final: bool = False) -> None:
        return None

    async def drain(self, within: float) -> bool:
        return True


# --------------------------------------------------------------------------------------------------
# the engine's thread
# --------------------------------------------------------------------------------------------------


class _EngineThread:
    """One daemon thread that runs the engine's blocking calls in order.

    A call that times out keeps running there (a hung network share can't be interrupted), and the
    next call waits behind it — never two engine calls at once. Being a daemon, it never keeps the
    process from exiting. Its context is a fresh one: nothing it writes is the person's.
    """

    def __init__(self) -> None:
        self._queue: queue.SimpleQueue[
            tuple[Callable[[], Any], Callable[[Any, BaseException | None], None]] | None
        ]
        self._queue = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._pending = 0
        self._count = threading.Lock()

    @property
    def busy(self) -> bool:
        """A call is still running or waiting (perhaps one that timed out)."""
        return self._pending > 0

    def retire(self) -> threading.Thread | None:
        """Let the thread end (Ordnung stops); a later call starts a new one. A thread with a call
        still running is left to it: being a daemon, it never keeps the process from exiting. Returns
        the thread that ends (``None``: none was idle)."""
        with self._count:
            if self._pending == 0 and self._thread is not None:
                self._queue.put(None)  # the idle thread takes it first: still one call at a time
                ending, self._thread = self._thread, None
                return ending
        return None

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            work, done = item
            result: Any = None
            error: BaseException | None = None
            try:
                result = work()
            except BaseException as exc:
                error = exc
            with self._count:  # no longer busy before the caller hears the outcome
                self._pending -= 1
            done(result, error)

    async def call(self, fn: Callable[..., T], *args: Any, limit: float | None = None, **kwargs: Any) -> T:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()

        def settle(result: Any, error: BaseException | None) -> None:
            if future.done():
                return
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result)

        def done(result: Any, error: BaseException | None) -> None:
            with contextlib.suppress(RuntimeError):  # the loop closed meanwhile
                loop.call_soon_threadsafe(settle, result, error)

        with self._count:
            self._pending += 1
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="ordnung-sync", daemon=True)
                self._thread.start()
        self._queue.put((lambda: fn(*args, **kwargs), done))
        if limit is None:
            return await future
        # a call that times out finishes later: its outcome is dropped (its error isn't reported twice)
        future.add_done_callback(lambda finished: finished.cancelled() or finished.exception())
        async with asyncio.timeout(limit):  # never asyncio.wait_for: on 3.11 it can swallow a cancel
            return await asyncio.shield(future)


# --------------------------------------------------------------------------------------------------
# the agent
# --------------------------------------------------------------------------------------------------


@dataclass
class _Waiting:
    """A take-over (or a choice) that waits until its version has arrived."""

    target: Any
    lineage: Any
    since: float  # monotonic
    since_at: str  # this computer's clock, shown
    choose: int | None = None  # the side chosen (None: "Use Ordnung here")
    action: UseHere = field(default_factory=UseHere)
    from_name: str | None = None


@dataclass(frozen=True)
class _Plan:
    """A data replacement the agent carries out (a pull of a decision, or a choice)."""

    target: Any
    keep: bool
    why: str | None
    from_name: str | None
    action: UseHere | None  # decided again behind the fence (None: no decision to repeat)
    claim: bool
    choice_push: bool = False
    note: Literal["taken_over", "brought_in", "chosen", "rolled_back"] = "taken_over"
    #: the gate's refusal while the fence is up (default: bringing over from ``from_name``)
    fence_message: str | None = None


def _same_plan(first: Decision, again: Decision) -> bool:
    return (first.kind, first.keep) == (again.kind, again.keep) and first.target == again.target


def _lineage(target: Any) -> Any:
    return getattr(target, "lineage", target)


class SyncAgent:
    """Hand-off sync for one running Ordnung (see the module docstring).

    ``host`` runs the background work (the server's :class:`~ordnung.api.deps.ApiState`; the command
    line has none); ``engine`` defaults to :func:`load_engine`, ``secrets`` to :func:`default_secrets`.
    """

    def __init__(
        self,
        ctx: AppContext,
        *,
        host: Host | None = None,
        demo: bool = False,
        engine: Engine | None = None,
        secrets: SecretStore | None = None,
    ) -> None:
        self.ctx = ctx
        self.host: Host = host or NoBackground()
        self.demo = demo
        self.engine: Engine | None = engine if engine is not None else load_engine()
        self.secrets: SecretStore = secrets if secrets is not None else default_secrets()
        self.mode: SyncMode = "off"
        self.connected = False
        self.activity: Literal["idle", "saving", "waiting", "bringing_over", "keeping"] = "idle"
        self.summary: LocalSummary | None = None
        self.view: FolderView | None = None
        self.local: LocalView | None = None
        self.decision: Decision | None = None
        self.problem: SyncProblem | None = None
        self.choice: SyncChoice | None = None
        self.arriving: SyncArriving | None = None
        self._session: Session | None = None
        self._thread = _EngineThread()
        self._lock: asyncio.Lock | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake: asyncio.Event | None = None
        self._first_look: asyncio.Event | None = None
        self._closing = False
        self._fenced = False
        self._fence_message = ""
        self._inflight = 0
        self._watch: sqlite3.Connection | None = None
        self._data_version: int | None = None
        self._dirty_since: float | None = None
        self._last_change: float | None = None
        self._person_since: float | None = None
        self._retry_at = 0.0
        self._failures = 0
        self._failing_since: float | None = None
        self._next_scan = 0.0
        self._last_gc: float | None = None
        self._waiting: _Waiting | None = None
        self._claim_when_unlocked = False
        self._joining = False
        self._published: dict[str, Any] | None = None
        #: the kept copies while this computer doesn't sync (they outlive Disconnect)
        self._kept_here: list[SyncKept] = []

    # ------------------------------------------------------------------------------ state

    @property
    def paths(self) -> Paths:
        return self.ctx.paths

    @property
    def store(self) -> Store:
        return self.ctx.store

    @property
    def is_demo(self) -> bool:
        """The demo never syncs (four layers; this is the server's)."""
        return self.demo or self.ctx.settings.demo or is_demo_dir(self.paths.data_dir)

    @property
    def allows_background(self) -> bool:
        """Background work may run: sync is off, or this computer is the one in use."""
        return not self.connected or self.mode in ("in_use", "starting")

    @property
    def fenced(self) -> bool:
        """Writes are refused for a moment: data is being brought over or saved first."""
        return self._fenced

    @property
    def counts_person_writes(self) -> bool:
        """The person's writes are counted (sync is connected and this computer is in use)."""
        return self.connected and self.mode in ("in_use", "starting")

    @property
    def in_use_on(self) -> str | None:
        """The name of the computer in use (as last seen; this one's own the moment it claims). ``None``
        while this computer stands by and no other is in use (the one in use left sync)."""
        if self.mode == "in_use" and self.summary is not None:
            return self.summary.name
        for computer in self.view.computers if self.view is not None else ():
            if getattr(computer, "in_use", False) and not getattr(computer, "this", False):
                return str(computer.name)
        if self.view is not None and self.view.computers:
            return None  # the folder was seen: no other computer is in use
        return self.summary.in_use_on if self.summary is not None else None

    def _lock_now(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ------------------------------------------------------------------------------ the gate's side

    def write_refusal(self, operation: Operation) -> str | None:
        """Why a write must be refused now (``None``: it may run): data is being brought over, or
        another computer is in use (except :data:`~ordnung.sync.ALLOWED_IN_STANDBY`)."""
        if self._fenced:
            return self._fence_message
        if self.mode == "standing_by" and operation not in ALLOWED_IN_STANDBY:
            return self._standby_message()
        return None

    def _standby_message(self) -> str:
        name = self.in_use_on
        if name is None and self.view is not None and self.view.computers:
            return NOBODY_IN_USE_MESSAGE
        return STANDBY_MESSAGE.format(name=name or "another computer")

    @contextlib.contextmanager
    def admitted(self) -> Iterator[None]:
        """A write the gate let through is running (the fence waits until none is)."""
        self._inflight += 1
        try:
            yield
        finally:
            self._inflight -= 1

    def person_wrote(self) -> None:
        """The person changed something (a request finished, the watched folder added a letter): the
        next save follows after :data:`~ordnung.sync.PUSH_PERSON_QUIET_S`."""
        if not self.counts_person_writes:
            return
        now = time.monotonic()
        fresh = self._dirty_since is None
        self._person_since = self._person_since or now
        self._dirty_since = self._dirty_since or now
        self._last_change = now
        if fresh:
            self._publish()  # the top bar says at once that a change isn't saved yet
        self.notify()

    def notify(self, *, look: bool = False) -> None:
        """Wake the loop (a change; ``look``: look at the folder soon, an operation finished)."""
        if look:
            self._next_scan = min(self._next_scan, time.monotonic() + WATCH_S)
        if self._wake is not None:
            self._wake.set()

    # ------------------------------------------------------------------------------ status

    def status(self, keyring: SecretsUnavailable | None = None) -> SyncStatus:
        """What ``GET /api/sync`` answers — from memory: never the folder, never a secret. ``keyring``
        is why this computer's password store can't be used (``SecretStore.problem()``, which only
        looks at which store there is)."""
        available, unavailable, install = True, None, None
        if self.is_demo:
            available, unavailable = False, DEMO_MESSAGE
        elif self.engine is None:
            available, unavailable = False, NO_ENGINE_MESSAGE
        elif keyring is not None:
            available, unavailable, install = False, str(keyring), keyring.install
        summary = self.summary if self.connected else None
        computers = [
            SyncComputer.model_validate(computer, from_attributes=True)
            for computer in (self.view.computers if self.view is not None and self.connected else ())
        ]
        kept = self._kept_list()
        notices = (
            [SyncNotice.model_validate(item, from_attributes=True) for item in summary.notices]
            if summary
            else []
        )
        # a commit seen since the last save, or what the last look found unsaved
        pending = self._dirty_since is not None or bool(self.local is not None and self.local.pending)
        others = [computer for computer in computers if not computer.this and computer.state != "left"]
        return SyncStatus(
            available=available,
            unavailable=unavailable,
            install_command=install,
            connected=self.connected,
            mode=self.mode,
            activity="waiting" if self._waiting is not None and self.activity == "idle" else self.activity,
            folder=summary.folder if summary else None,
            this_computer=summary.name if summary else None,
            suggested_name=suggested_name(),
            in_use_on=self.in_use_on if self.connected else None,
            computers=computers,
            last_saved_at=summary.last_saved_at if summary else None,
            pending_changes=self.connected and pending,
            others_have_latest=self.connected and not pending and any(c.has_latest for c in others),
            up_to_date=(
                self.mode == "standing_by"
                and self.decision is not None
                and self.decision.kind == "up_to_date"
            ),
            base_from=summary.base_from if summary else None,
            base_arrived_at=summary.base_arrived_at if summary else None,
            arriving=self.arriving if self.connected else None,
            take_over_waiting=self._waiting is not None,
            choice=self.choice if self.connected else None,
            problem=self.problem if self.connected else None,
            notices=notices,
            kept=kept,
            kept_warning=sum(item.size for item in kept) > KEPT_WARN_BYTES,
            data_folder_synced=bool(summary.data_folder_synced) if summary else False,
        )

    def _publish(self, *, replaced: bool = False) -> None:
        current = self.status().model_dump(exclude={"available", "unavailable", "install_command"})
        if replaced or current != self._published:
            self._published = current
            with contextlib.suppress(Exception):  # no loop bound (the command line)
                self.ctx.bus.publish("sync.updated", replaced=replaced)

    def calendar_shared_with(self) -> str | None:
        """Another computer that sends to the same calendar (Delete everything then leaves Ordnung's
        events there, critique finding 27)."""
        if not self.connected or self.view is None:
            return None
        for computer in self.view.computers:
            if not getattr(computer, "this", False) and getattr(computer, "calendar", "none") in (
                "same",
                "different_mode",
            ):
                return str(computer.name)
        return None

    def needs_second_confirmation(self) -> bool:
        """Disconnect and Delete everything ask twice: no other computer has this one's latest."""
        return self.connected and not self.status().others_have_latest

    def _kept_list(self) -> list[SyncKept]:
        """The kept copies the status lists: from the summary while connected, else the ones found here
        (Disconnect leaves them; they stay listed, downloadable and deletable)."""
        if self.connected and self.summary is not None:
            return [SyncKept.model_validate(item, from_attributes=True) for item in self.summary.kept]
        return list(self._kept_here) if not self.connected else []

    async def _load_kept(self) -> None:
        """The kept copies on this computer while it doesn't sync (no keyring, no folder)."""
        if self.engine is None or self.is_demo:
            self._kept_here = []
            return
        try:
            found = await self._thread.call(self.engine.kept_copies, self.paths, limit=FOLDER_OP_TIMEOUT_S)
        except Exception:
            return
        self._kept_here = [SyncKept.model_validate(item, from_attributes=True) for item in found]

    def kept_file(self, name: str) -> Path | None:
        """A kept copy listed in the status, by its name (``None``: no such one)."""
        if not KEPT_RE.fullmatch(name) or name not in {item.name for item in self._kept_list()}:
            return None
        path = self.paths.sync / KEPT_DIR / name
        return path if path.is_file() and not path.is_symlink() else None

    # ------------------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        """Take the last known mode at once and, when it can, decide within
        :data:`~ordnung.sync.START_DECIDE_S`. Never raises: the demo, no engine or no connection means
        ``off`` (background work runs as without sync)."""
        if self._task is not None or self.is_demo or self.engine is None:
            return
        self._closing = False
        try:
            summary = await self._thread.call(self.engine.local_summary, self.paths, limit=START_DECIDE_S)
        except Exception as exc:
            log.warning("sync: this computer's sync state can't be read (%s)", type(exc).__name__)
            return
        if summary is None:
            await self._load_kept()
            return
        self._adopt(summary)
        self._start_loop()
        assert self._first_look is not None
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(START_DECIDE_S):
                await asyncio.shield(self._first_look.wait())

    async def load(self, *, look: bool = False) -> None:
        """For one command-line operation (no loop, no background work): this computer's sync state —
        without the keyring — and, with ``look``, one look at the folder (keyring and scrypt), so a
        choice to make or a problem shows."""
        if self.is_demo or self.engine is None:
            return
        summary = await self._thread.call(self.engine.local_summary, self.paths)
        if summary is None:
            await self._load_kept()
            return
        self._adopt(summary)
        if not look or (self.problem is not None and self.problem.code in _STOPPED):
            return
        session = await self._ensure_session()
        if session is None:
            return
        decision = await self._look(session)
        if decision.kind == "repair":
            await self._repair(session, decision)
            decision = await self._look(session)
        if decision.kind == "paused":
            self._set_decided_problem(decision)
        elif decision.kind == "choice":
            self.choice = self._choice_of(decision)
        elif self.mode == "standing_by":
            again = await self._look(session, UseHere())
            if again.kind == "choice":
                self.choice = self._choice_of(again)

    async def wait_round(self) -> bool:
        """For the command line: one more look while a take-over waits (``True``: it still waits)."""
        async with self._operation():
            if self._waiting is None:
                return False
            session = await self._ensure_session()
            if session is not None:
                await self._continue_waiting(session)
            return self._waiting is not None

    def _in_use(self) -> bool:
        """Whether this computer is the one in use, read afresh (a step awaited just before may have changed it)."""
        return self.mode == "in_use"

    def _adopt(self, summary: LocalSummary) -> None:
        self.summary = summary
        self.connected = True
        self.store.set_durable(True)
        if summary.journal:  # while a take-over is unfinished, this computer is never in use
            self.mode = "standing_by"
            self.problem = problem("pull_unfinished", in_use=False)
        else:
            self.mode = summary.mode

    def _start_loop(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._wake = asyncio.Event()
        self._first_look = asyncio.Event()
        self._next_scan = 0.0
        # its own writes (privacy-log rows, a replaced database) are never the person's
        self._task = asyncio.create_task(self._loop(), name="ordnung-sync", context=background_context())

    async def save_before_stop(self) -> None:
        """Ordnung stops: save the person's changes now, before readings get their grace period
        (critique finding 33). At most :data:`~ordnung.sync.SHUTDOWN_PUSH_S`; never raises."""
        await self._shutdown_push("change")

    async def close(self) -> None:
        """Ordnung stops (background work already stopped): the last save, the head says ``closed``
        (at most :data:`~ordnung.sync.SHUTDOWN_PUSH_S`, waiting for a running operation at most as
        long); the loop ends, and an engine call still running is waited for until
        :data:`~ordnung.sync.SHUTDOWN_PUSH_S` after the start, then the engine's idle thread for
        :data:`THREAD_END_WAIT_S` at most. The store stays open. Never raises."""
        deadline = time.monotonic() + SHUTDOWN_PUSH_S
        self._closing = True
        self.notify()
        await self._shutdown_push("shutdown")
        await self._let_go(deadline)

    async def dispose(self) -> None:
        """Let go without a last save (the command line after its operation; an app whose lifespan never
        ran): the loop ends, the read-only connection closes and an engine call still running is waited
        for, at most :data:`~ordnung.sync.SHUTDOWN_PUSH_S`, then the engine's idle thread ends (as in
        :meth:`close`). The store stays open. Never raises."""
        self._closing = True
        await self._let_go(time.monotonic() + SHUTDOWN_PUSH_S)

    async def _let_go(self, deadline: float) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task})  # its outcome isn't ours; a cancel of close() itself still is
        self._close_watch()
        # a call that outlived its limit may still read the database, and the store closes next
        while self._thread.busy:
            if time.monotonic() >= deadline:  # a hung share: a daemon thread never keeps Ordnung running
                log.warning("sync: an operation was still running when Ordnung stopped")
                break
            await asyncio.sleep(ENGINE_POLL_S)
        ending = self._thread.retire()
        # its connection to the database closes as it ends, on its own thread: before the store closes,
        # never a moment after (Windows can't delete or replace a database that is still open)
        until = time.monotonic() + THREAD_END_WAIT_S
        while ending is not None and ending.is_alive():  # a thread's end can't set an asyncio event
            if time.monotonic() >= until:
                break
            await asyncio.sleep(THREAD_END_POLL_S)

    def _close_watch(self) -> None:
        watch, self._watch = self._watch, None
        if watch is not None:
            with contextlib.suppress(Exception):
                watch.close()

    async def _shutdown_push(self, reason: PushReason) -> None:
        if not self.connected or self.mode != "in_use" or self.engine is None:
            return
        lock = self._lock_now()
        if not await _acquire_within(lock, SHUTDOWN_PUSH_S):
            log.warning("sync: a running operation kept the last save from starting")
            return
        try:
            if self._session is None or self._thread.busy:
                return
            async with asyncio.timeout(SHUTDOWN_PUSH_S):
                await self._push(reason)
        except (TimeoutError, Exception) as exc:
            log.warning("sync: the last save didn't finish (%s)", type(exc).__name__)
        finally:
            lock.release()

    # ------------------------------------------------------------------------------ the loop

    async def _loop(self) -> None:
        while not self._closing:
            try:
                await self._step()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the loop never ends by an error
                log.warning("sync: a round failed (%s)", type(exc).__name__, exc_info=True)
            finally:
                if self._first_look is not None:
                    self._first_look.set()
            await self._sleep()

    async def _step(self) -> None:
        lock = self._lock_now()
        if not self.connected or lock.locked() or self._thread.busy:
            return  # not syncing, an operation runs, or a call hangs: the next step looks again
        async with lock:
            now = time.monotonic()
            if self.mode == "in_use":
                self._watch_changes(now)
                if self._push_due(now) and now >= self._retry_at and self._session is not None:
                    await self._push("change")
            if time.monotonic() >= self._next_scan:
                try:
                    await self._periodic()
                finally:
                    self._next_scan = time.monotonic() + self._look_again_in()

    def _look_again_in(self) -> float:
        """Seconds until the next look: less often while the folder doesn't answer (a hung share)."""
        if self.problem is not None and self.problem.code == "folder_unreachable":
            return UNREACHABLE_SCAN_S
        return WAIT_POLL_S if self._waiting else SCAN_S

    async def _sleep(self) -> None:
        assert self._wake is not None
        until_scan = max(0.05, self._next_scan - time.monotonic())
        delay = min(WATCH_S, until_scan) if self.mode == "in_use" else until_scan
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(delay):
                await self._wake.wait()
        self._wake.clear()

    def _data_version_now(self) -> int | None:
        """``PRAGMA data_version`` on the agent's own read-only connection: only real commits move it."""
        try:
            if self._watch is None:
                uri = f"{self.paths.db.resolve().as_uri()}?mode=ro"
                self._watch = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=1.0)
            return int(self._watch.execute("PRAGMA data_version").fetchone()[0])
        except sqlite3.Error:
            self._close_watch()
            return None

    def _watch_changes(self, now: float) -> None:
        """A commit since the last look at ``data_version`` is a change not saved yet (said at once)."""
        version = self._data_version_now()
        if version is None:
            return
        if self._data_version is not None and version != self._data_version:
            fresh = self._dirty_since is None
            self._dirty_since = self._dirty_since or now
            self._last_change = now
            if fresh:
                self._publish()
        self._data_version = version

    def _push_due(self, now: float) -> bool:
        if self._dirty_since is None or self._last_change is None:
            return False
        quiet = PUSH_PERSON_QUIET_S if self._person_since is not None else PUSH_QUIET_S
        return now - self._last_change >= quiet or now - self._dirty_since >= PUSH_MAX_WAIT_S

    # ------------------------------------------------------------------------------ one round

    async def _ensure_session(self) -> Session | None:
        """The unlocked session (keyring and scrypt the first time); ``None`` with a problem set."""
        if self._session is not None:
            return self._session
        assert self.engine is not None
        try:
            self._session = await self._thread.call(self.engine.open_session, self.paths, self.secrets)
        except Exception as exc:
            self._set_problem(self._problem_code(exc), exc)
            return None
        if self.problem is not None and self.problem.code in (
            "passphrase_needed",
            "keyring_locked",
            "keyring_unavailable",
        ):
            self.problem = None
        await self._claim_if_asked(self._session)
        return self._session

    async def _claim_if_asked(self, session: Session) -> None:
        """ "Use Ordnung here anyway" while the password store was locked (critique finding 31): the claim
        is made once the key is there — after the session's start (its counters known); tried again at
        the next look when the folder can't take it yet."""
        if not self._claim_when_unlocked:
            return
        with contextlib.suppress(Exception):
            await self._thread.call(session.local_view, self.store)  # the session's start
            await self._thread.call(session.claim)
            self._claim_when_unlocked = False

    async def _look(self, session: Session, action: UseHere | None = None) -> Decision:
        assert self.engine is not None
        view = await self._thread.call(session.scan, limit=FOLDER_OP_TIMEOUT_S)
        local = await self._thread.call(session.local_view, self.store, limit=FOLDER_OP_TIMEOUT_S)
        decision = self.engine.decide(local, view, action)
        self.view, self.local, self.decision = view, local, decision
        await self._refresh_summary()
        return decision

    async def _refresh_summary(self) -> None:
        assert self.engine is not None
        with contextlib.suppress(Exception):
            summary = await self._thread.call(
                self.engine.local_summary, self.paths, limit=FOLDER_OP_TIMEOUT_S
            )
            if summary is not None:
                self.summary = summary

    async def _periodic(self) -> None:
        if self.problem is not None and self.problem.code in _STOPPED:
            # nothing is saved or brought over until the person answers; still look at the folder (a
            # local rollback whose last saved state has arrived meanwhile is put back now)
            if self._session is not None:
                with contextlib.suppress(Exception):
                    decision = await self._look(self._session)
                    if decision.kind == "repair":
                        await self._repair(self._session, decision)
            self._publish()
            return
        session = await self._ensure_session()
        if session is None:
            self._publish()
            return
        await self._claim_if_asked(session)
        try:
            if self._waiting is not None:
                await self._continue_waiting(session)
            else:
                decision = await self._look(session)
                await self._execute(session, decision)
        except Exception as exc:
            self._set_problem(self._problem_code(exc), exc)
        self._check_patience()
        self._publish()

    async def _execute(self, session: Session, decision: Decision) -> None:
        kind = decision.kind
        self.choice = self._choice_of(decision) if kind == "choice" else None
        self.arriving = (
            SyncArriving.model_validate(decision.arriving, from_attributes=True)
            if kind == "arriving" and decision.arriving is not None
            else None
        )
        if kind == "repair":
            await self._repair(session, decision)
            return
        if kind == "paused":
            self._set_decided_problem(decision)
            if self.mode == "in_use" and decision.may_push and self._local_pending():
                await self._push("change")
            return
        if self.problem is not None and self.problem.code not in _SAVE_PROBLEMS:
            self.problem = None  # the folder answered as it should (a save's own problem waits for a save)
        await self._follow_standby()
        if self.mode != "in_use":
            if kind == "late_push" and self.mode == "standing_by" and self._waiting is None:
                # the person's change that finished after this computer stood by (F21): it goes out as
                # a late push; the computer in use brings it in quietly, or asks
                await self._push("late")
            return  # standing by: otherwise report only (up to date, arriving, a choice)
        if kind == "become_standby":
            await self._become_standby(late_push=decision.late_push)
        elif kind == "bring_in":
            plan = _Plan(
                target=decision.target,
                keep=decision.keep,
                why=decision.why,
                from_name=decision.from_name,
                action=None,
                claim=False,
                note="brought_in",
            )
            await self._replace(session, plan, decision)
        elif kind in ("push", "choice") and self._local_pending() and self._dirty_since is None:
            # found by a look, not by a commit seen here (written while no server ran): save soon
            due = time.monotonic() - PUSH_QUIET_S
            self._dirty_since = self._last_change = due

    def _local_pending(self) -> bool:
        return bool(self.local is not None and self.local.pending)

    def _choice_of(self, decision: Decision) -> SyncChoice | None:
        if decision.choice is None:
            return None
        choice = SyncChoice.model_validate(decision.choice, from_attributes=True)
        if self._waiting is not None and self._waiting.choose is not None:
            choice.chosen = self._waiting.choose
        return choice

    def _check_patience(self) -> None:
        """The holder's gentle line when a running standby hasn't received its latest for 30 minutes."""
        if self.mode != "in_use" or self.view is None or self.problem is not None:
            return
        for computer in self.view.computers:
            if computer.this or computer.state != "standing_by" or computer.has_latest is not False:
                continue
            if self._last_saved_since() >= ARRIVAL_PATIENCE_S:
                self.problem = problem("not_received", name=str(computer.name))
                return

    def _last_saved_since(self) -> float:
        """Seconds since this computer's last save (its own clock only)."""
        saved = self.summary.last_saved_at if self.summary is not None else None
        if not saved:
            return 0.0
        try:
            moment = datetime.fromisoformat(saved)
        except ValueError:
            return 0.0
        return (datetime.now(moment.tzinfo) - moment).total_seconds()

    # ------------------------------------------------------------------------------ problems

    def _problem_code(self, exc: BaseException) -> SyncProblemCode:
        stated = getattr(exc, "problem", None)
        if isinstance(stated, str) and stated in PROBLEMS:
            return stated
        if isinstance(exc, SecretsUnavailable):
            return "keyring_unavailable" if self.secrets.problem() is not None else "keyring_locked"
        if isinstance(exc, SyncError):
            kinds: dict[str, SyncProblemCode] = {
                "passphrase_needed": "passphrase_needed",
                "wrong_passphrase": "passphrase_needed",
                "newer_ordnung": "newer_ordnung",
                "no_space": "no_space",
                "pull_unfinished": "pull_unfinished",
                "full": "folder_full",
            }
            return kinds.get(exc.kind, "folder_unreachable")
        if isinstance(exc, TimeoutError):
            return "folder_unreachable"
        if isinstance(exc, FileNotFoundError):
            return "folder_missing"
        if isinstance(exc, OSError) and exc.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)):
            return "folder_full"
        if isinstance(exc, OSError):
            return "folder_unreachable"
        return "save_failing"

    def _set_problem(self, code: SyncProblemCode, exc: BaseException | None = None) -> None:
        if self.problem is None or self.problem.code != code:  # logged once, not at every look
            log.warning("sync: %s (%s)", code, type(exc).__name__ if exc is not None else "-")
        self.problem = problem(code, name=self._other_name(), in_use=self.mode == "in_use")

    def _set_decided_problem(self, decision: Decision) -> None:
        found = decision.problem
        code = getattr(found, "code", None)
        if not isinstance(code, str) or code not in PROBLEMS:
            return
        message = getattr(found, "message", None)
        self.problem = problem(
            code,
            name=decision.from_name or self._other_name(),
            message=message if isinstance(message, str) else None,
            in_use=self.mode == "in_use",
        )

    def _other_name(self) -> str | None:
        for computer in self.view.computers if self.view is not None else ():
            if not computer.this and computer.state != "left":
                return str(computer.name)
        return None

    def _raise_problem(self, kind: SyncErrorKind = "folder_problem") -> None:
        """Answer a request that can't go on because of the current problem."""
        shown = self.problem
        raise SyncError(kind, shown.message if shown is not None else CANT_OPEN_MESSAGE)

    # ------------------------------------------------------------------------------ saving

    async def _push(self, reason: PushReason, *, hand_over: bool = False, strict: bool = False) -> None:
        """Save into the folder now (``strict``: a failure is raised, for a request that asked)."""
        session = self._session
        if session is None:
            if strict:
                self._raise_problem()
            return
        if self.is_demo:  # checked on the live data before any snapshot (critique finding 19)
            raise SyncRefused()
        started = time.monotonic()
        self.activity = "saving"
        self._publish()
        try:
            await self._thread.call(session.push, self.store, reason=reason, hand_over=hand_over)
        except Exception as exc:
            self._failed_push(exc)
            if strict:
                raise SyncError(
                    "folder_problem", self.problem.message if self.problem else CANT_OPEN_MESSAGE
                ) from exc
            return
        finally:
            self.activity = "idle"
        self._failures = 0
        self._failing_since = None
        self._retry_at = 0.0
        if self.problem is not None and self.problem.code in (*_SAVE_PROBLEMS, "folder_unreachable"):
            self.problem = None
        if self._last_change is None or self._last_change <= started:
            self._dirty_since = self._last_change = self._person_since = None
        version = self._data_version_now() if self.mode == "in_use" else None
        with contextlib.suppress(Exception):  # what is pending now (not what the last look saw)
            self.local = await self._thread.call(session.local_view, self.store, limit=FOLDER_OP_TIMEOUT_S)
            if version is not None and self._dirty_since is None and not self._local_pending():
                # the save's own bookkeeping (``sync_mark``) committed: no change of the data, so the
                # top bar doesn't go back to "not saved" for it (commits after ``version`` still count)
                self._data_version = version
        with contextlib.suppress(Exception):
            # which computer has this computer's latest is worked out against the version just saved —
            # never the last look's (the top bar's "has it" and the second confirmation read it)
            self.view = await self._thread.call(session.scan, limit=FOLDER_OP_TIMEOUT_S)
        await self._refresh_summary()
        if self._last_gc is None or time.monotonic() - self._last_gc >= GC_EVERY_S:
            self._last_gc = time.monotonic()
            with contextlib.suppress(Exception):
                await self._thread.call(session.gc)
        if reason in ("change", "save", "first"):
            await self._follow_standby()
        self._publish()

    async def _follow_standby(self) -> None:
        """The engine stood this computer by on its own — a save met another computer's newer claim
        (the push's own fence): the agent follows at once (R3), so writes are refused from now on and
        none is left behind unsaved."""
        if (
            self.mode == "in_use"
            and not self._fenced
            and not self._claim_when_unlocked  # in use here on the person's word, claimed once it can be
            and self.summary is not None
            and self.summary.mode == "standing_by"
        ):
            await self._become_standby(late_push=False)

    def _failed_push(self, exc: BaseException) -> None:
        """A save failed: tried again after :data:`~ordnung.sync.PUSH_RETRY_S`; a full or failing folder
        becomes a problem after :data:`~ordnung.sync.FAILING_AFTER_S`, anything else at once."""
        now = time.monotonic()
        self._failing_since = self._failing_since or now
        delay = PUSH_RETRY_S[min(self._failures, len(PUSH_RETRY_S) - 1)]
        self._failures += 1
        self._retry_at = now + delay
        code = self._problem_code(exc)
        log.warning("sync: saving failed (%s, %s); trying again in %d s", code, type(exc).__name__, delay)
        failing_long = now - self._failing_since >= FAILING_AFTER_S
        if code in ("folder_full", "save_failing"):
            if failing_long:
                self._set_problem(code, exc)
        elif code == "folder_unreachable":
            self._set_problem("save_failing" if failing_long else code, exc)
        else:
            self._set_problem(code, exc)

    async def _become_standby(self, *, late_push: bool) -> None:
        """Another computer took over (R3): stop background work, wait for the writes already admitted
        (a phone upload, a request whose body is still arriving — the person's late changes too, F21:
        at most :data:`~ordnung.sync.FENCE_WAIT_S`), save the person's late changes, say so in this
        computer's head, stand by. A write that finishes even later goes out as a late push from
        standing by (:meth:`_execute`)."""
        self.mode = "standing_by"  # the gate refuses writes from now on
        self._publish()
        if not await self._settle_admitted():
            log.warning("sync: writes in flight didn't finish before standing by; saved once they do")
        await self.host.stop_background()
        await self._push("late" if late_push else "hand_over", hand_over=True)
        self._publish()

    async def _settle_admitted(self, *, own: int = 0) -> bool:
        """Wait until the writes the gate already let through finished (``own``: the caller's own
        request, not waited for) — at most :data:`~ordnung.sync.FENCE_WAIT_S` (``False``: they didn't)."""
        deadline = time.monotonic() + FENCE_WAIT_S
        while self._inflight > own:
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.02)
        return True

    async def _quiesce(self, message: str, *, own: int = 0) -> bool:
        """The fence (writes refused with ``message``), then background work stopped and drained
        (``False``: writes didn't finish in time; the fence is down again). ``own``: writes in flight
        that are the caller's own request (Delete everything), not waited for."""
        if not await self._fence(message, own=own):
            return False
        await self.host.stop_background()
        if not await self.host.drain(FENCE_WAIT_S):
            self._lift_fence()
            log.warning("sync: background work didn't finish in time")
            if self.allows_background:
                await self.host.start_background()
            return False
        return True

    async def _fence(self, message: str, *, own: int = 0) -> bool:
        self._fenced, self._fence_message = True, message
        self._publish()
        if not await self._settle_admitted(own=own):
            self._lift_fence()
            log.warning("sync: writes in flight didn't finish in time; trying again later")
            return False
        return True

    def _lift_fence(self) -> None:
        self._fenced = False

    # ------------------------------------------------------------------------------ replacing the data

    async def _replace(self, session: Session, plan: _Plan, decision: Decision | None = None) -> bool:
        """Two-phase replace (module docstring). ``True`` once the data was replaced."""
        from_name = plan.from_name or "your other computer"
        self.activity = "bringing_over"
        self._publish()
        try:
            staged = await self._thread.call(session.stage, plan.target)
        except NotArrived:
            self.activity = "idle"
            return False
        except BaseException:
            self.activity = "idle"
            raise
        was_running = self.mode in ("in_use", "starting") or not self.connected
        replaced = False
        kept_name: str | None = None
        try:
            if not await self._quiesce(plan.fence_message or BRINGING_OVER_MESSAGE.format(name=from_name)):
                with contextlib.suppress(Exception):
                    await self._thread.call(session.discard, staged)
                return False
            if decision is not None and self.engine is not None:
                local = await self._thread.call(session.local_view, self.store)
                assert self.view is not None
                again = self.engine.decide(local, self.view, plan.action)
                if not _same_plan(decision, again):  # a write landed meanwhile: decide afresh
                    log.info("sync: something changed before the data was replaced; deciding again")
                    with contextlib.suppress(Exception):
                        await self._thread.call(session.discard, staged)
                    return False
            if plan.keep:
                self.activity = "keeping"
                self._publish()
                kept = await self._thread.call(session.keep_local, self.paths, plan.why or "")
                kept_name = str(getattr(kept, "name", "")) or None
            self.activity = "bringing_over"
            try:
                async with ledger_lock():
                    applied = await self._thread.call(_apply, session, staged, self.store)
            except SyncError as exc:
                if exc.kind != "not_needed":
                    raise
                # the person's write landed after all (the apply's own guard): decide afresh
                log.info("sync: something changed before the data was replaced; deciding again")
                return False
            replaced = True
            kept_name = kept_name or (str(getattr(applied, "kept", None) or "") or None)
            self.ctx.reload_settings()
            self.ctx.worker.reload()
            if plan.choice_push:
                await self._push("choice")
            if plan.claim:
                await self._thread.call(session.claim)
                self.mode = "in_use"
                self._waiting = None
            await self._log_after(plan, from_name, kept_name)
            return True
        finally:
            self._lift_fence()
            self.activity = "idle"
            if replaced:
                await self._refresh_summary()
                self._announce_replaced()
            if self.mode == "in_use" or (was_running and self.mode != "standing_by"):
                await self.host.start_background()
            self._publish(replaced=replaced)

    async def _repair(self, session: Session, decision: Decision) -> bool:
        """F10 / review finding 4: this computer's data went back in time (a power cut, a data folder put
        back from an OS backup); its own last saved version is put back with the two phases of any
        replacement — what is here, a write made while the version was staged included, goes into the
        kept copy (``True`` once it is back; otherwise the next look tries again)."""
        plan = _Plan(
            target=decision.target,
            keep=True,
            why=decision.why,
            from_name=self.summary.name if self.summary is not None else None,
            action=None,
            claim=False,
            note="rolled_back",
            fence_message=PUTTING_BACK_MESSAGE,
        )
        if not await self._replace(session, plan, decision):
            return False
        if self.problem is not None and self.problem.code == "local_rollback":
            self.problem = None
        return True

    def _announce_replaced(self) -> None:
        bus = self.ctx.bus
        with contextlib.suppress(Exception):
            for event in ("profile.updated", "item.updated", "suggestions.updated"):
                bus.publish(event)
            bus.publish("day.changed", date=clock.today().isoformat(), previous=None)

    async def _log_after(self, plan: _Plan, from_name: str, kept: str | None) -> None:
        """The privacy-log rows (written into the data now here, so they travel with it) and notices."""
        if plan.note == "rolled_back":
            if kept is not None:
                await self._log_now(
                    "sync.kept",
                    "Saved this computer's earlier data as an encrypted copy.",
                    {"copy": kept, "why": plan.why or ""},
                )
            await self._notice("rolled_back", ROLLBACK_NOTICE, kept)
            return
        if kept is not None:
            await self._log_now(
                "sync.kept",
                "Saved this computer's earlier data as an encrypted copy.",
                {"copy": kept, "why": plan.why or ""},
            )
            await self._notice(
                "kept",
                f"This computer's earlier data was saved as an encrypted copy, {kept} ({plan.why or 'kept'}). "
                "Open it with “ordnung restore” and the sync passphrase.",
                kept,
            )
        if plan.note == "brought_in":
            await self._log_now(
                "sync.brought_in",
                f"Brought in a change from {from_name} that arrived late.",
                {"from": from_name},
            )
            await self._notice("brought_in", f"Brought in a change from {from_name} that arrived late.")
        elif plan.note == "chosen":
            await self._log_now(
                "sync.chosen",
                f"You kept {from_name}'s Ordnung. This computer's was saved as a copy here.",
                {"kept": from_name},
            )
        elif not self._joining:
            await self._log_now(
                "sync.taken_over", f"Ordnung moved here from {from_name}.", {"from": from_name}
            )

    async def _log_now(self, kind: str, message: str, data: dict[str, Any]) -> None:
        """A privacy-log row (only the computer in use writes them; they travel with the data)."""
        if self.mode != "in_use":
            return
        with contextlib.suppress(Exception):
            await self._thread.call(self.store.log_activity, kind, message, data=data)

    async def _notice(self, code: SyncNoticeCode, message: str, kept: str | None = None) -> None:
        assert self.engine is not None
        with contextlib.suppress(Exception):
            await self._thread.call(self.engine.change, self.paths, notice=(code, message, kept))

    async def _claim(self, session: Session, from_name: str | None = None) -> None:
        """This computer becomes the one in use, at the data it has (nothing is uploaded)."""
        await self._thread.call(session.claim)
        was = self.mode
        self.mode = "in_use"
        self._waiting = None
        if was != "in_use":
            await self.host.start_background()
            if from_name:
                await self._log_now(
                    "sync.taken_over", f"Ordnung moved here from {from_name}.", {"from": from_name}
                )
        await self._refresh_summary()
        self._publish()

    # ------------------------------------------------------------------------------ waiting

    async def _continue_waiting(self, session: Session) -> None:
        waiting = self._waiting
        assert waiting is not None
        if time.monotonic() - waiting.since >= TAKE_OVER_WAIT_MAX_S:
            await self._cancel_wait("expired")
            return
        if waiting.choose is not None:
            result = await self._thread.call(session.choose, self.store, waiting.choose)
            await self._after_choose(session, result, waiting.choose)
            return
        decision = await self._look(session, waiting.action)
        if decision.kind in ("wait", "pull") and _lineage(decision.target) != waiting.lineage:
            await self._cancel_wait("changed", decision.from_name or waiting.from_name)
            return
        await self._run_take_over(session, decision, waiting.action)

    async def _cancel_wait(self, why: Literal["expired", "changed"], name: str | None = None) -> None:
        """Give a waiting take-over up and say why (the notice is there once the wait is gone)."""
        await self._notice(
            "take_over_cancelled", WAIT_CANCELLED[why].format(name=name or "your other computer")
        )
        await self._refresh_summary()
        self._waiting = None
        self.arriving = None
        if self.choice is not None:
            self.choice.chosen = None

    def _wait_for(self, target: Any, action: UseHere, *, choose: int | None, from_name: str | None) -> None:
        """Wait for ``target`` (a wait already under way for the same goes on: its time keeps counting)."""
        waiting = self._waiting
        if waiting is not None and (waiting.choose, waiting.action) == (choose, action):
            waiting.target, waiting.from_name = target, from_name or waiting.from_name
            return
        self._waiting = _Waiting(
            target=target,
            lineage=_lineage(target),
            since=time.monotonic(),
            since_at=clock.real_now_iso(),
            choose=choose,
            action=action,
            from_name=from_name,
        )
        self._next_scan = time.monotonic() + WAIT_POLL_S

    # ------------------------------------------------------------------------------ operations

    @contextlib.asynccontextmanager
    async def _operation(self) -> Any:
        """One operation a request asked for: refused in the demo and without an engine; run under
        the agent's lock (waiting for a running round at most :data:`~ordnung.sync.FOLDER_OP_TIMEOUT_S`)."""
        if self.is_demo:
            raise SyncRefused()
        if self.engine is None:
            raise SyncError("unavailable", NO_ENGINE_MESSAGE)
        lock = self._lock_now()
        if not await _acquire_within(lock, FOLDER_OP_TIMEOUT_S):
            raise SyncError("folder_problem", BUSY_MESSAGE)
        try:
            if self._thread.busy:
                raise SyncError("folder_problem", BUSY_MESSAGE)
            yield
        finally:
            lock.release()
            self._publish()
            self.notify(look=True)

    def _connected(self) -> None:
        if not self.connected:
            raise SyncError("not_connected", NOT_CONNECTED_MESSAGE)

    async def inspect(self, folder: str) -> SyncFolderInfo:
        """What ``folder`` would be for sync (nothing is written)."""
        if self.is_demo:
            raise SyncRefused()
        if self.engine is None:
            raise SyncError("unavailable", NO_ENGINE_MESSAGE)
        info = await self._thread.call(
            self.engine.inspect_folder, folder, self.paths, self.ctx.settings, limit=FOLDER_OP_TIMEOUT_S
        )
        return SyncFolderInfo.model_validate(info, from_attributes=True)

    async def connect(
        self,
        folder: str,
        name: str,
        passphrase: str,
        *,
        keep: Literal["this", "folder"] | None,
        secrets: SecretStore,
    ) -> SyncChoice | None:
        """Set up a new sync folder, or join one (module docstring of :mod:`ordnung.api.routes.sync`).
        Joining while this computer has letters and without ``keep`` answers the choice to make
        (nothing is connected yet)."""
        async with self._operation():
            assert self.engine is not None
            if (
                self.connected
                and self.problem is not None
                and self.problem.code
                in (
                    "folder_missing",
                    "folder_other",
                )
            ):
                await self._choose_folder_again(folder)
                return None
            if self.connected:
                raise SyncError("already_connected", "This computer already syncs. Disconnect it first.")
            wrong_name = name_problem(name)
            if wrong_name is not None:
                raise SyncError("name", wrong_name)
            info = await self._thread.call(
                self.engine.inspect_folder, folder, self.paths, self.ctx.settings, limit=FOLDER_OP_TIMEOUT_S
            )
            if info.kind == "refused":
                raise SyncError("folder", str(info.problem or "This folder can't be used."))
            if info.kind == "new":
                weak = passphrase_problem(passphrase)
                if weak is not None:
                    raise SyncError("passphrase", weak)
            elif not passphrase:
                raise SyncError("passphrase", "Type the passphrase of this sync folder.")
            self.secrets = secrets
            joining = info.kind == "existing"
            # joining may bring the folder's data over at once: writes and background work wait
            if joining and not await self._quiesce(BRINGING_OVER_MESSAGE.format(name="your other computer")):
                raise SyncError("folder_problem", STILL_WRITING_MESSAGE)
            try:
                result = await self._thread.call(
                    self.engine.connect,
                    self.paths,
                    Path(str(info.folder)),
                    name.strip(),
                    passphrase,
                    secrets=secrets,
                    keep=keep,
                    store=self.store,
                )
                if result.choice is not None and keep is None:
                    choice = SyncChoice.model_validate(result.choice, from_attributes=True)
                    if joining:
                        self._lift_fence()
                        await self.host.start_background()
                    return choice
                summary = await self._thread.call(self.engine.local_summary, self.paths)
                if summary is None:
                    raise SyncError("folder_problem", CANT_OPEN_MESSAGE)
            except BaseException:
                if joining:
                    self._lift_fence()
                    await self.host.start_background()
                raise
            self._lift_fence()
            self._adopt(summary)
            if self._task is None and not isinstance(self.host, NoBackground):
                self._start_loop()  # it waits for this operation's lock, and goes on even if a step fails
            self._session = None
            self.problem = self.choice = None
            session = await self._ensure_session()
            if result.created:  # the engine saved into the new folder and logged it
                self.mode = "in_use"
                if session is not None:
                    await self._push("first")
            elif self.mode == "in_use":  # the engine brought the data over and claimed: in use here
                self.ctx.reload_settings()
                self.ctx.worker.reload()
                self._announce_replaced()
                await self.host.start_background()
                self._publish(replaced=True)
            else:  # standing by until the data can be brought over
                if session is not None:
                    self._joining = True
                    try:
                        await self._take_over(session, UseHere())
                    finally:
                        self._joining = False
                if self._in_use():  # taking over made it the one in use
                    await self._log_now(
                        "sync.joined",
                        f"Brought Ordnung over from {self._other_name() or 'your other computer'} and started "
                        "syncing.",
                        {"from": self._other_name() or ""},
                    )
            return None

    async def _choose_folder_again(self, folder: str) -> None:
        """The folder went missing or moved: the person points at it again (only a folder of this
        very sync is accepted; the engine checks its vault)."""
        assert self.engine is not None
        info = await self._thread.call(
            self.engine.inspect_folder, folder, self.paths, self.ctx.settings, limit=FOLDER_OP_TIMEOUT_S
        )
        if info.kind != "existing":
            raise SyncError("folder", str(info.problem or "This folder doesn't hold this sync."))
        await self._thread.call(self.engine.change, self.paths, folder=Path(str(info.folder)))
        self.problem = None
        self._session = None
        await self._refresh_summary()
        self._next_scan = 0.0

    async def use_here(self, *, older_copy: bool = False, cancel: bool = False) -> None:
        """ "Use Ordnung here": take over, wait, or the choice (module docstring)."""
        async with self._operation():
            self._connected()
            if cancel:
                if self._waiting is not None:
                    self._waiting = None
                    self.arriving = None
                    if self.choice is not None:
                        self.choice.chosen = None
                return
            if self.summary is not None and self.summary.journal:
                raise SyncError("pull_unfinished", TOO_EARLY_MESSAGE)
            session = await self._ensure_session()
            if session is None:
                if (
                    older_copy
                    and self.problem is not None
                    and self.problem.code
                    in (
                        "keyring_locked",
                        "passphrase_needed",
                    )
                ):
                    # in use locally; the claim is made once the key is there (critique finding 31)
                    self._claim_when_unlocked = True
                    if self.mode != "in_use":
                        self.mode = "in_use"
                        await self.host.start_background()
                    return
                code = self.problem.code if self.problem is not None else None
                self._raise_problem("passphrase_needed" if code == "passphrase_needed" else "folder_problem")
                return
            if self.problem is not None and self.problem.code in _STOPPED:
                self._raise_problem(
                    "pull_unfinished" if self.problem.code == "pull_unfinished" else "folder_problem"
                )
            await self._take_over(session, UseHere(older_copy=older_copy))

    async def _take_over(self, session: Session, action: UseHere, *, depth: int = 0) -> None:
        decision = await self._look(session, action)
        await self._run_take_over(session, decision, action, depth=depth)

    async def _run_take_over(
        self, session: Session, decision: Decision, action: UseHere, *, depth: int = 0
    ) -> None:
        kind = decision.kind
        if kind == "repair":  # this computer's last saved state goes back first, then the take-over
            if await self._repair(session, decision) and depth < 2:
                await self._take_over(session, action, depth=depth + 1)
                return
            self._raise_problem()
        if kind == "nothing":
            if self.mode != "in_use":
                await self._claim(session)
            return
        if kind == "late_push" and depth < 2:
            await self._push("late", strict=True)
            await self._take_over(session, action, depth=depth + 1)
            return
        if kind == "claim":
            await self._claim(session, decision.from_name)
            return
        if kind == "pull":
            plan = _Plan(
                target=decision.target,
                keep=decision.keep,
                why=decision.why,
                from_name=decision.from_name,
                action=action,
                claim=True,
            )
            replaced = await self._replace(session, plan, decision)
            if not replaced and self.mode != "in_use":  # not arrived after all, or a write came first: wait
                self._wait_for(decision.target, action, choose=None, from_name=decision.from_name)
            return
        if kind == "wait":
            self._wait_for(decision.target, action, choose=None, from_name=decision.from_name)
            self.arriving = (
                SyncArriving.model_validate(decision.arriving, from_attributes=True)
                if decision.arriving is not None
                else None
            )
            return
        if kind == "choice":
            self.choice = self._choice_of(decision)
            return
        if kind == "paused":
            self._set_decided_problem(decision)
            code = self.problem.code if self.problem is not None else None
            if code == "newer_ordnung":
                raise SyncError("newer_ordnung", self.problem.message if self.problem else "")
            if code == "no_space":
                raise SyncError("no_space", self.problem.message if self.problem else "")
            self._raise_problem()
        # anything else (idle, push…) means this computer is the one in use already
        if self.mode != "in_use":
            await self._claim(session)

    async def choose(self, key: int) -> None:
        """Keep the Ordnung of the side ``key`` (module docstring)."""
        async with self._operation():
            self._connected()
            if self.choice is None or key not in {side.key for side in self.choice.sides}:
                raise SyncError("no_choice", NO_CHOICE_MESSAGE)
            session = await self._ensure_session()
            if session is None:
                code = self.problem.code if self.problem is not None else None
                self._raise_problem("passphrase_needed" if code == "passphrase_needed" else "folder_problem")
                return
            result = await self._thread.call(session.choose, self.store, key)
            await self._after_choose(session, result, key)

    async def _after_choose(self, session: Session, result: ChooseResult, key: int) -> None:
        if result.pull is None:  # this computer's Ordnung: save the choice, claim
            await self._push("choice", strict=True)
            await self._claim(session)
            self.choice = None
            self._waiting = None
            await self._log_now("sync.chosen", "You kept this computer's Ordnung.", {"kept": "this"})
            return
        if not result.complete:
            if self._waiting is None:
                self._wait_for(result.pull, UseHere(), choose=key, from_name=result.from_name)
            if self.choice is not None:
                self.choice.chosen = key
            self.arriving = (
                SyncArriving.model_validate(result.arriving, from_attributes=True)
                if result.arriving is not None
                else None
            )
            return
        plan = _Plan(
            target=result.pull,
            keep=True,
            why=result.why,
            from_name=result.from_name,
            action=None,
            claim=True,
            choice_push=True,
            note="chosen",
        )
        if await self._replace(session, plan):
            self.choice = None
            self._waiting = None
            self.arriving = None

    async def save(self, *, hand_over: bool = False) -> None:
        """Save now; ``hand_over`` then stands by (behind the fence, so nothing is left behind)."""
        async with self._operation():
            self._connected()
            if self.mode == "standing_by":
                raise SyncError("standby", self._standby_message())
            if self._session is None and await self._ensure_session() is None:
                self._raise_problem()
            if not hand_over:
                await self._push("save", strict=True)
                return
            if not await self._quiesce(SAVING_FIRST_MESSAGE):
                raise SyncError("folder_problem", STILL_WRITING_MESSAGE)
            try:
                self.mode = "standing_by"
                await self._push("hand_over", hand_over=True, strict=True)
            except BaseException:
                self.mode = "in_use"
                await self.host.start_background()
                raise
            finally:
                self._lift_fence()

    async def set_passphrase(self, passphrase: str, *, secrets: SecretStore) -> None:
        """The passphrase typed again: checked against the folder, then kept in the password store."""
        async with self._operation():
            self._connected()
            assert self.engine is not None
            self.secrets = secrets
            await self._thread.call(self.engine.set_passphrase, self.paths, secrets, passphrase)
            self._session = None
            if self.problem is not None and self.problem.code in (
                "passphrase_needed",
                "keyring_locked",
                "keyring_unavailable",
            ):
                self.problem = None
            if await self._ensure_session() is not None:
                self._next_scan = 0.0

    async def refill(self) -> None:
        """Fill an emptied folder again from this computer (the one in use)."""
        async with self._operation():
            self._connected()
            if self.mode != "in_use" or self.problem is None or self.problem.code != "folder_empty":
                raise SyncError("not_needed", REFILL_NOT_NEEDED)
            session = self._session or await self._ensure_session()
            if session is None:
                self._raise_problem()
                return
            await self._thread.call(session.refill, self.store)
            self.problem = None
            await self._look(session)

    async def forget(self, key: int) -> None:
        """Remove a lost computer from sync (its changes that are nowhere else are kept here first)."""
        async with self._operation():
            self._connected()
            found = next(
                (c for c in (self.view.computers if self.view else ()) if c.key == key and not c.this), None
            )
            if found is None:
                raise SyncError("not_found", NO_COMPUTER_MESSAGE)
            if found.in_use:
                raise SyncError("in_use", IN_USE_MESSAGE)
            session = await self._ensure_session()
            if session is None:
                code = self.problem.code if self.problem is not None else None
                self._raise_problem("passphrase_needed" if code == "passphrase_needed" else "folder_problem")
                return
            await self._thread.call(session.forget, key)
            await self._log_now(
                "sync.forgot", f"Removed {found.name} from sync.", {"computer": str(found.name)}
            )
            await self._look(session)

    async def change(
        self,
        *,
        name: str | None = None,
        confirm_same_computer: bool = False,
        keep_as_is: bool = False,
        abandon_pull: bool = False,
        dismiss_notice: str | None = None,
    ) -> None:
        """Rename this computer, answer a problem, or dismiss a notice."""
        async with self._operation():
            self._connected()
            assert self.engine is not None
            code = self.problem.code if self.problem is not None else None
            if name is not None:
                wrong = name_problem(name)
                if wrong is not None:
                    raise SyncError("name", wrong)
            if confirm_same_computer and code != "copied_folder":
                raise SyncError("not_needed", NOTHING_TO_CONFIRM)
            if keep_as_is and code != "local_rollback":
                raise SyncError("not_needed", NOTHING_TO_CONFIRM)
            journal = self.summary is not None and self.summary.journal
            if abandon_pull and not journal and code != "pull_unfinished":
                raise SyncError("not_needed", NOTHING_TO_ABANDON)
            if keep_as_is:
                session = self._session or await self._ensure_session()
                if session is None:
                    self._raise_problem()
                    return
                await self._thread.call(session.keep_as_is, self.store)
            await self._thread.call(
                self.engine.change,
                self.paths,
                name=name.strip() if name is not None else None,
                confirm_same_computer=confirm_same_computer,
                abandon_pull=abandon_pull,
                dismiss_notice=dismiss_notice,
            )
            if confirm_same_computer or keep_as_is or abandon_pull:
                self.problem = None
                self._session = None if confirm_same_computer else self._session
                self._next_scan = 0.0
            if abandon_pull:
                self.mode = "standing_by"
            await self._refresh_summary()

    async def disconnect(self, *, forget_passphrase: bool = True, unreceived_ok: bool = False) -> None:
        """Disconnect this computer (its last changes are saved first; the folder and the other
        computers keep everything); background work runs as without sync afterwards."""
        if not self.connected:
            if self.is_demo:
                raise SyncRefused()
            return
        if not unreceived_ok and self.needs_second_confirmation():
            raise SyncError("not_received", NOT_RECEIVED_MESSAGE)
        async with self._operation():
            await self._leave(
                forget_passphrase=forget_passphrase, restart=True, own=0, unreceived_ok=unreceived_ok
            )

    async def leave(self, *, unreceived_ok: bool = True) -> None:
        """Delete everything: this computer leaves sync (its last changes saved first, its head says
        ``left``, its passphrase leaves the password store, the loop idles). The caller asked for the
        second confirmation (:meth:`needs_second_confirmation`), stopped the background work, and wipes
        the data next; its own request is the one write in flight not waited for. Without
        ``unreceived_ok`` the second confirmation is asked again once the last save is done."""
        if not self.connected:
            return
        async with self._operation():
            await self._leave(forget_passphrase=True, restart=False, own=1, unreceived_ok=unreceived_ok)

    async def _leave(
        self, *, forget_passphrase: bool, restart: bool, own: int, unreceived_ok: bool = True
    ) -> None:
        assert self.engine is not None
        session = self._session or await self._ensure_session()
        fenced = left = False
        try:
            if session is not None:
                fenced = await self._quiesce(SAVING_FIRST_MESSAGE, own=own)
                if not fenced:
                    raise SyncError("folder_problem", STILL_WRITING_MESSAGE)
                try:
                    await self._push("leave")
                except Exception as exc:  # the confirmation covered it; leave anyway
                    log.warning("sync: the last save before leaving failed (%s)", type(exc).__name__)
                if not unreceived_ok and self.needs_second_confirmation():
                    # the last save made a version no other computer has yet (a change the first
                    # check didn't see): the second confirmation after all
                    raise SyncError("not_received", NOT_RECEIVED_MESSAGE)
            # the engine logs "stopped syncing" into the data, saves it, and writes the head as left
            await self._thread.call(
                self.engine.disconnect,
                self.paths,
                self.secrets,
                forget_passphrase=forget_passphrase,
                store=self.store,
            )
            left = True
        finally:
            if fenced:
                self._lift_fence()
            if not left and restart and self.allows_background:
                await self.host.start_background()
        self._reset()
        await self._load_kept()  # kept copies stay (and stay listed)
        if restart:
            await self.host.start_background()

    def _reset(self) -> None:
        self.connected = False
        self.mode = "off"
        self.activity = "idle"
        self.summary = self.view = self.local = self.decision = None
        self.problem = self.choice = self.arriving = None
        self._session = None
        self._waiting = None
        self._dirty_since = self._last_change = self._person_since = None
        self._claim_when_unlocked = False
        self.store.set_durable(False)

    async def delete_kept(self, name: str) -> bool:
        """Delete a kept copy for good (``False``: there is no such one)."""
        async with self._operation():
            assert self.engine is not None
            if self.kept_file(name) is None:
                return False
            deleted = await self._thread.call(self.engine.delete_kept, self.paths, name)
            if self.connected:
                await self._refresh_summary()
            else:
                await self._load_kept()
            return bool(deleted)


async def _acquire_within(lock: asyncio.Lock, seconds: float) -> bool:
    """Take ``lock`` once it is free, waiting at most ``seconds`` (``False``: it stayed taken). Taking a
    free lock never yields, so no timeout can fire between taking it and returning."""
    deadline = time.monotonic() + seconds
    while lock.locked():
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(LOCK_POLL_S)
    await lock.acquire()
    return True


def _apply(session: Session, staged: Any, store: Store) -> Any:
    """Apply a staged version (no calendar sync writes its record meanwhile)."""
    with caldav.exclusive():
        return session.apply(staged, store)


def suggested_name() -> str:
    """This computer's host name without its domain ("anna-thinkpad"), as a computer's name."""
    import socket

    host = socket.gethostname().split(".", 1)[0].strip()
    return host[:NAME_MAX_CHARS] or "This computer"
