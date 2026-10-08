"""The engine façade the sync agent drives (:class:`ordnung.sync.agent.Engine`, design §24.3 I2), built
on the sync core (:mod:`ordnung.sync.engine` and the modules under it).

The core's :class:`~ordnung.sync.engine.Session` carries out whole steps (a round, "Use Ordnung here",
a choice) in one blocking call. The server needs them in pieces: a version is staged while writes are
still allowed, then the agent puts the fence up, drains background work, decides again and only then
keeps a copy and applies (review blocker 1). So this façade hands the agent the core's pieces — scan,
local view, decision, stage, kept copy, apply, claim, push — and does around them what the core's whole
steps do around the same pieces:

* a quiet pull that would remove letters keeps a copy first (Rule K, extended by finding 18);
* a version brought in while in use is written into this computer's head;
* a choice saves the chosen lineage (:func:`~ordnung.sync.lineage.keep_this` /
  :func:`~ordnung.sync.lineage.keep_other`) with a new claim;
* standing by after another computer took over writes ``standing_by`` (``closed`` for "save and hand
  over"), shutting down writes ``closed``;
* the person-change counter read with the last local view guards the apply (``expect_person``: a
  person's write in between gives the pull up, :class:`~ordnung.sync.pull.PullAborted`);
* the core's start runs at the first look and again at every look until it completes (it waits while
  the folder can't be read, and nothing is saved meanwhile: a ``paused`` decision); a local rollback it
  finds is repaired by the agent like any other replacement — the version to put back is the local
  view's ``repair``, and the decision ``repair`` (review: the repair is fenced like the rest).

The privacy-log rows of these pieces are the agent's; :func:`connect` and :func:`disconnect` are the
core's whole steps and write their own.

**One session per data folder.** The agent may drop its session and open a new one (the folder chosen
again, the passphrase typed again); settings changes (:meth:`RealEngine.change`) go through the live
session when there is one, so its state in memory never overwrites them.

**The local digest** needs an in-memory copy of the database (:func:`~ordnung.sync.push.take_snapshot`).
A look takes one only when the database files changed since the last one (size and mtime of the
database and its WAL); otherwise the last digest stands.
"""

from __future__ import annotations

import contextlib
import dataclasses
import secrets as tokens
import shutil
import threading
import weakref
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ordnung import __version__
from ordnung.calendar import caldav
from ordnung.calendar.secrets import SecretStore
from ordnung.config import Paths
from ordnung.db.store import Store
from ordnung.models import AppSettings
from ordnung.sync import (
    KEPT_DIR,
    KEPT_RE,
    NOT_CONNECTED_MESSAGE,
    ROLLBACK_WHY,
    SyncError,
    SyncNoticeCode,
    WrongSyncPassphrase,
)
from ordnung.sync import engine as core
from ordnung.sync import lineage as lin
from ordnung.sync.crypto import open_key_file
from ordnung.sync.decide import (
    Action,
    AlreadyInUse,
    Arriving,
    BecomeStandby,
    BringIn,
    Choice,
    ChooseOther,
    ChooseThis,
    Claim,
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
)
from ordnung.sync.folder import data_folder_synced
from ordnung.sync.kept import delete_kept as delete_kept_copy
from ordnung.sync.kept import kept_copies, write_index
from ordnung.sync.local import Local, clean_name, in_use_on, keyring_account, load_state, machine_id
from ordnung.sync.model import Lineage, Notice, Summary
from ordnung.sync.pull import Staged, abandon, removed_letters, resume_interrupted, unfinished
from ordnung.sync.scan import Completeness, FolderView, HeadView, Problem
from ordnung.sync.scrub import summary as live_summary
from ordnung.sync.status import (
    SyncArriving,
    SyncChoice,
    SyncComputer,
    SyncKept,
    SyncLetter,
    SyncNotice,
    SyncSide,
    SyncSideChange,
)

#: Problems found at a session's start that stop saving and bringing over until the person answers.
_START_PROBLEMS = frozenset({"copied_folder", "pull_unfinished", "local_rollback"})
ABANDON_TOO_LATE = (
    "This take-over has already replaced the database, so it can't be given up. Restart Ordnung to finish it."
)
ABANDONED_MESSAGE = "The unfinished take-over was given up. This computer's data is as it was before."


def _now() -> str:
    return core.now_iso()


# --------------------------------------------------------------------------------------------------
# what the agent reads
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FoundProblem:
    """A problem the agent words (``message`` None: its usual words)."""

    code: str
    message: str | None = None


@dataclass(frozen=True)
class StateSummary:
    """``state.json`` as the agent shows it (:class:`ordnung.sync.agent.LocalSummary`)."""

    folder: str
    name: str
    mode: Literal["in_use", "standing_by"]
    in_use_on: str | None
    last_saved_at: str | None
    base_from: str | None
    base_arrived_at: str | None
    notices: Sequence[SyncNotice]
    kept: Sequence[SyncKept]
    data_folder_synced: bool
    journal: bool


@dataclass(frozen=True, eq=False)
class Target:
    """A version to bring over: another computer's head (compared by computer and version)."""

    head: HeadView
    keep: bool = False

    @property
    def lineage(self) -> Lineage | None:
        version = self.head.head.version
        return version.lineage if version is not None else None

    def _key(self) -> tuple[str, str | None]:
        version = self.head.head.version
        return (self.head.computer, version.id.key() if version is not None else None)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Target) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())


@dataclass(frozen=True)
class RealView:
    """One look at the folder (:class:`ordnung.sync.agent.FolderView`)."""

    inner: FolderView
    computers: list[SyncComputer]
    #: computer id → the summary of its head's version (letters, newest), when it could be read
    summaries: dict[str, Summary] = field(default_factory=dict)
    #: computer id → when it saved its head's version (its own clock), when the manifest could be read
    saved: dict[str, str] = field(default_factory=dict)

    @property
    def problem(self) -> FoundProblem | None:
        found = self.inner.problem
        return FoundProblem(found.code) if found is not None else None


@dataclass(frozen=True)
class RealLocal:
    """This computer's data as the decision sees it (:class:`ordnung.sync.agent.LocalView`)."""

    inner: LocalView
    #: changes not saved yet: the person's, or a digest that differs from the base's
    pending: bool
    name: str
    #: what this computer's data holds now (its side in a choice)
    here: Summary
    #: what its base held (letters "added" since the two last agreed)
    base: Summary
    #: a problem found at the session's start that stops sync until the person answers (or the folder's
    #: problem while the start waits for the folder)
    problem: Problem | None = None
    #: this computer's own last saved version, whole in the folder, to put back (a local rollback)
    repair: Target | None = None


@dataclass(frozen=True)
class AgentDecision:
    """:class:`ordnung.sync.agent.Decision`."""

    kind: str
    target: Target | None = None
    keep: bool = False
    why: str | None = None
    late_push: bool = False
    may_push: bool = False
    choice: SyncChoice | None = None
    arriving: SyncArriving | None = None
    problem: FoundProblem | None = None
    from_name: str | None = None


@dataclass(frozen=True)
class Connected:
    """:class:`ordnung.sync.agent.ConnectResult`."""

    created: bool
    choice: SyncChoice | None = None


@dataclass(frozen=True)
class Chosen:
    """:class:`ordnung.sync.agent.ChooseResult`."""

    pull: Target | None
    complete: bool = True
    arriving: SyncArriving | None = None
    why: str | None = None
    from_name: str | None = None


@dataclass(frozen=True)
class Applied:
    """What an apply did: ``kept``, a copy written by the façade itself (a quiet pull removing letters)."""

    kept: str | None = None


# --------------------------------------------------------------------------------------------------
# mapping the core's views and decisions
# --------------------------------------------------------------------------------------------------


def _arriving(head: HeadView) -> SyncArriving:
    found = head.completeness or Completeness(False)
    return SyncArriving(
        from_computer=head.head.name,
        have=found.have,
        need=found.need,
        have_bytes=found.have_bytes,
        need_bytes=found.need_bytes,
        since=head.arrived_at or _now(),
        stalled=False,
        online_only=found.online_only,
    )


def _letters(found: Summary) -> list[SyncLetter]:
    return [SyncLetter(label=letter.label, added_on=letter.added_on) for letter in found.newest]


def _contents(found: Summary) -> dict[str, Any]:
    """A side's counts and latest changes (what tells two sides apart besides their letters)."""
    return {
        "items": found.items,
        "done": found.done,
        "notes": found.notes,
        "latest": [
            SyncSideChange(kind=change.kind, label=change.label, on=change.on) for change in found.latest
        ],
    }


def _choice(choice: Choice, local: RealLocal, view: RealView) -> SyncChoice:
    sides: list[SyncSide] = []
    joining = choice.joining or local.inner.base is None
    for side in choice.sides:
        if side.this or side.head is None:
            here = local.here
            added = here.letters if joining else max(0, here.letters - local.base.letters)
            sides.append(
                SyncSide(
                    key=side.key,
                    computer=local.name,
                    this=True,
                    letters=here.letters,
                    added=added,
                    newest=_letters(here),
                    complete=True,
                    **_contents(here),
                )
            )
            continue
        head = side.head
        theirs = view.summaries.get(head.computer, Summary())
        added = theirs.letters if joining else max(0, theirs.letters - local.base.letters)
        sides.append(
            SyncSide(
                key=side.key,
                computer=head.head.name,
                this=False,
                letters=theirs.letters,
                added=added,
                newest=_letters(theirs),
                **_contents(theirs),
                saved_at=view.saved.get(head.computer),
                arrived_at=head.arrived_at,
                complete=head.complete,
                arriving=None if head.complete else _arriving(head),
            )
        )
    return SyncChoice(joining=choice.joining, sides=sides)


def _paused(problem: Problem) -> AgentDecision:
    return AgentDecision("paused", problem=FoundProblem(problem.code))


def map_decision(found: Any, local: RealLocal, view: RealView) -> AgentDecision:
    """The core's decision as the agent executes it (its kinds: :data:`ordnung.sync.agent.DecisionKind`)."""
    holder = view.inner.by_computer(view.inner.holder) if view.inner.holder else None
    holder_name = holder.head.name if holder is not None and not holder.this else None
    if isinstance(found, Paused):
        return _paused(found.problem)
    if isinstance(found, BecomeStandby):
        return AgentDecision("become_standby", late_push=found.late_push, from_name=holder_name)
    if isinstance(found, Choice):
        return AgentDecision("choice", choice=_choice(found, local, view))
    if isinstance(found, BringIn):
        name = found.target.head.name
        return AgentDecision(
            "bring_in",
            target=Target(found.target),
            why=f"before bringing in {name}'s changes",
            from_name=name,
        )
    if isinstance(found, Arriving):
        return AgentDecision(
            "arriving",
            target=Target(found.target),
            arriving=_arriving(found.target),
            from_name=found.target.head.name,
        )
    if isinstance(found, Push):
        return AgentDecision("push")
    if isinstance(found, Idle):
        return AgentDecision("idle")
    if isinstance(found, Standby):
        if found.late_push:  # the person's change made before this computer stood by (F21)
            return AgentDecision("late_push", late_push=True, from_name=holder_name)
        if found.problem is not None:
            return _paused(found.problem)
        if found.choice is not None:
            return AgentDecision("choice", choice=_choice(found.choice, local, view))
        if found.arriving is not None:
            return AgentDecision(
                "arriving",
                target=Target(found.arriving),
                arriving=_arriving(found.arriving),
                from_name=found.arriving.head.name,
            )
        # a digest that differs while standing by is background work: replaced at the next take-over
        return AgentDecision("up_to_date" if found.up_to_date else "idle", from_name=holder_name)
    if isinstance(found, AlreadyInUse):
        return AgentDecision("nothing")
    if isinstance(found, LatePush):
        return AgentDecision("late_push")
    if isinstance(found, Pull):
        name = found.target.head.name
        why = f"before you kept {name}'s Ordnung" if found.keep else f"before you used {name}'s Ordnung here"
        return AgentDecision(
            "pull", target=Target(found.target, keep=found.keep), keep=found.keep, why=why, from_name=name
        )
    if isinstance(found, Claim):
        return AgentDecision("claim", from_name=holder_name)
    if isinstance(found, Wait):
        return AgentDecision(
            "wait",
            target=Target(found.target),
            arriving=_arriving(found.target),
            from_name=found.target.head.name,
        )
    if isinstance(found, NotYet):  # joining: the other computers' heads haven't arrived yet
        return AgentDecision("wait")
    return AgentDecision("idle")


def _calendar_match(
    head: HeadView, own: HeadView | None
) -> Literal["none", "same", "different_mode", "other"]:
    theirs = head.head.calendar_target
    if theirs is None:
        return "none"
    mine = own.head.calendar_target if own is not None else None
    if mine is None or mine != theirs:
        return "other"
    return (
        "same" if head.head.calendar_mode == (own.head.calendar_mode if own else None) else "different_mode"
    )


def _computers(view: FolderView, session: core.Session) -> list[SyncComputer]:
    state = session.state
    mine = state.base.ref if state.base is not None else None
    own = view.own()
    shown: list[SyncComputer] = []
    for head in sorted(view.heads, key=lambda h: h.key):
        if head.forgotten:
            continue
        has_latest: bool | None = None
        if not head.this and mine is not None:
            version = head.head.version
            has_latest = head.head.has == mine.id or (
                version is not None and (version.id == mine.id or lin.contains(version.lineage, mine.lineage))
            )
        shown.append(
            SyncComputer(
                key=head.key,
                name=head.head.name if not head.this else state.name,
                this=head.this,
                # this computer standing by is never the one in use — also when it is the last live head
                # (the computer in use left): then no computer is in use until it uses Ordnung here
                in_use=head.computer == view.holder and not (head.this and state.mode == "standing_by"),
                state=head.head.state if head.readable else "unknown",
                arrived_at=head.arrived_at,
                has_latest=has_latest,
                app_version=head.head.app_version,
                calendar="none" if head.this else _calendar_match(head, own),
            )
        )
    if own is None:  # its head isn't written yet (joining): this computer is still one of them
        shown.insert(
            0,
            SyncComputer(
                key=session.key,
                name=state.name,
                this=True,
                in_use=view.holder == state.computer and state.mode == "in_use",
                state=state.head_state,
                app_version=__version__,
                calendar="none",
            ),
        )
    return shown


# --------------------------------------------------------------------------------------------------
# the session
# --------------------------------------------------------------------------------------------------


def _db_stamp(paths: Paths) -> tuple[tuple[int, int], ...] | None:
    stamps: list[tuple[int, int]] = []
    for path in (paths.db, paths.db.with_name(paths.db.name + "-wal")):
        try:
            info = path.stat()
        except FileNotFoundError:
            stamps.append((-1, -1))
            continue
        except OSError:
            return None
        stamps.append((info.st_size, info.st_mtime_ns))
    return tuple(stamps)


class RealSession:
    """:class:`ordnung.sync.agent.Session` over one :class:`ordnung.sync.engine.Session`."""

    def __init__(self, inner: core.Session) -> None:
        self.inner = inner
        self._stamp: tuple[tuple[int, int], ...] | None = None
        self._digest: str | None = None
        self._person_data: bool | None = None
        #: the person-change counter as the last local view read it (the apply's guard)
        self._expect: int | None = None
        #: the kept copy written for the version being brought over
        self._kept: str | None = None
        #: the lineage a choice saves with its next push (``reason="choice"``)
        self._choice: Lineage | None = None

    @property
    def paths(self) -> Paths:
        return self.inner.paths

    # ---- looking -------------------------------------------------------------------------------

    def _start(self, store: Store) -> Problem | None:
        """The core's start, until it completes (F32, the counters, F3, the local rollback): the folder's
        problem while it waits for the folder. A local rollback isn't repaired here — the agent does it,
        behind the fence (:attr:`RealLocal.repair`)."""
        inner = self.inner
        if inner.started:
            return None
        found = inner.start(store)
        if inner.started:
            return None
        return found or Problem("folder_unreachable")

    def scan(self) -> RealView:
        view = self.inner.scan()
        summaries: dict[str, Summary] = {}
        saved: dict[str, str] = {}
        for head in view.heads:
            version = head.head.version
            if head.this or version is None or head.newer:
                continue
            manifest = head.completeness.manifest if head.completeness is not None else None
            if manifest is None:
                with contextlib.suppress(Exception):
                    manifest = self.inner.scanner.manifest(version)
            if manifest is not None:
                summaries[head.computer] = manifest.summary
                saved[head.computer] = manifest.created_at
        return RealView(view, _computers(view, self.inner), summaries, saved)

    def local_view(self, store: Store) -> RealLocal:
        inner = self.inner
        waiting = self._start(store)
        stamp = _db_stamp(self.paths)
        if stamp is None or stamp != self._stamp or self._digest is None:
            try:
                snap = inner.snapshot()
            except (SyncError, OSError):
                self._stamp, self._digest, self._person_data = None, None, None
            else:
                self._stamp, self._digest, self._person_data = stamp, snap.digest, snap.person_data
        found = inner.local_view(store)
        if self._digest is not None:
            found = dataclasses.replace(found, digest=self._digest, has_person_data=bool(self._person_data))
        self._expect = inner.counter(store)
        base = inner.state.base
        differs = found.digest is not None and (base is None or found.digest != base.ref.digest)
        problem = inner.problem
        if problem is not None and problem.code == "pull_unfinished" and unfinished(self.paths) is None:
            inner.problem = problem = None  # given up meanwhile
        if problem is None or problem.code not in _START_PROBLEMS:
            problem = waiting  # the start waits for the folder: nothing is saved meanwhile
        repair: Target | None = None
        if problem is not None and problem.code == "local_rollback":
            with contextlib.suppress(SyncError, OSError):
                own = inner.rollback_target()
                if own is not None:
                    repair = Target(own, keep=True)
        return RealLocal(
            inner=found,
            pending=bool(found.pending or (base is not None and differs) or inner._heal_push),
            name=inner.state.name,
            here=live_summary(store._conn()),
            base=base.summary if base is not None else Summary(),
            problem=problem,
            repair=repair,
        )

    # ---- saving --------------------------------------------------------------------------------

    def _held_elsewhere(self) -> bool:
        view = self.inner.view
        return view is not None and view.holder is not None and view.holder != self.inner.state.computer

    def push(self, store: Store, *, reason: str, hand_over: bool = False) -> core.PushResult | None:
        inner = self.inner
        state = inner.state
        if not inner.started and reason != "shutdown":
            self._start(store)  # a save before the first look starts the session first (it may refuse)
        if reason == "choice":
            chosen, self._choice = self._choice, None
            pushed = inner.push(store, lineage=chosen, claim=True, head_state="in_use", force=True)
            state.mode = "in_use"
            state.waiting = None
            inner.save()
            return pushed
        if reason == "shutdown":
            if state.mode != "in_use":
                return None
            return inner.close(store)
        if hand_over:
            if self._held_elsewhere():
                # another computer took over (R3): stand by whatever happens to the late save
                late: core.PushResult | None = None
                try:
                    late = inner.push(store, head_state="standing_by")
                finally:
                    if late is None or late.outcome != "pushed":
                        with contextlib.suppress(SyncError, OSError):
                            inner.write_head(state="standing_by")
                    state.mode = "standing_by"
                    inner.save()
                return late
            return inner.save_now(store, hand_over=True)  # "save and hand over": closed, standing by
        view = inner.view
        heal = inner._heal_push
        pushed = inner.push(store, force=heal, rewrite=view.wants if view is not None else frozenset())
        inner._heal_push = False
        if reason in ("change", "save", "first") and state.mode == "in_use" and inner.view is not None:
            inner._after_push(store, inner.view)  # self-heal and GC, each at most as often as they may
        return pushed

    # ---- bringing a version over --------------------------------------------------------------

    def stage(self, target: Target) -> Staged:
        self._kept = None
        return self.inner.stage(target.head, keep=target.keep)

    def discard(self, staged: Staged) -> None:
        self._kept = None
        shutil.rmtree(self.inner.local.incoming, ignore_errors=True)

    def keep_local(self, paths: Paths, why: str) -> Any:
        kept = self.inner.keep_local(why, digest=self._digest)
        self._kept = kept.name
        return kept

    def apply(self, staged: Staged, store: Store) -> Applied:
        inner = self.inner
        kept, made = self._kept, None
        try:
            if kept is None and removed_letters(staged, store) > 0:
                # a quiet pull that would remove letters keeps a copy first (finding 18)
                made = kept = inner.keep_local(
                    f"before bringing in {staged.from_name}'s changes, which remove letters",
                    digest=self._digest,
                ).name
            inner.apply(staged, store, kept=kept, expect_person=self._expect)
        except BaseException:
            shutil.rmtree(inner.local.incoming, ignore_errors=True)
            raise
        finally:
            self._kept = None
        self._stamp = None
        if (
            inner.problem is not None
            and inner.problem.code == "local_rollback"
            and staged.target.id.computer == inner.state.computer
        ):
            inner.problem = None  # its own last saved state is back (the agent says so)
        if inner.state.mode == "in_use":
            inner.write_head(state="in_use")  # brought in while in use: the head names the new version
        return Applied(kept=made)

    def claim(self) -> None:
        self.inner.claim()

    # ---- the person's actions ----------------------------------------------------------------

    def choose(self, store: Store, key: int) -> Chosen:
        inner = self.inner
        view = inner.scan()
        local = self.local_view(store).inner
        found = decide(local, view, Action("choose", key=key))
        if isinstance(found, NoChoice):
            raise SyncError("no_choice", "There's no such computer to choose.")
        if isinstance(found, Paused):
            raise core._paused_error(found.problem)
        base = inner.state.base.ref.lineage if inner.state.base is not None else Lineage()
        if isinstance(found, ChooseThis):
            self._choice = lin.keep_this(base, found.others)
            return Chosen(pull=None)
        if isinstance(found, Wait):
            return Chosen(
                pull=Target(found.target, keep=True),
                complete=False,
                arriving=_arriving(found.target),
                from_name=found.target.head.name,
            )
        assert isinstance(found, ChooseOther)
        version = found.target.head.version
        assert version is not None
        self._choice = lin.keep_other(version.lineage, base, found.others)
        name = found.target.head.name
        return Chosen(
            pull=Target(found.target, keep=True),
            why=f"before you kept {name}'s Ordnung",
            from_name=name,
        )

    def forget(self, key: int) -> None:
        self.inner.forget(key)

    def refill(self, store: Store) -> None:
        self.inner.refill(store)

    def gc(self) -> None:
        self.inner.gc()

    def keep_as_is(self, store: Store) -> None:
        self.inner.keep_as_is(store)
        self._stamp = None


# --------------------------------------------------------------------------------------------------
# the engine
# --------------------------------------------------------------------------------------------------


class RealEngine:
    """:class:`ordnung.sync.agent.Engine` (module docstring)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        #: data folder → the session an agent uses now (gone with the agent)
        self._live: weakref.WeakValueDictionary[Path, RealSession] = weakref.WeakValueDictionary()
        #: data folder → the session :func:`connect` left unlocked (the agent's next open takes it)
        self._fresh: dict[Path, core.Session] = {}

    @staticmethod
    def _key(paths: Paths) -> Path:
        return paths.data_dir.resolve()

    def _session_of(self, paths: Paths) -> RealSession | None:
        with self._lock:
            return self._live.get(self._key(paths))

    def _forget_session(self, paths: Paths) -> None:
        with self._lock:
            self._live.pop(self._key(paths), None)
            self._fresh.pop(self._key(paths), None)

    # ---- keyless ------------------------------------------------------------------------------

    def local_summary(self, paths: Paths) -> StateSummary | None:
        state = load_state(paths)  # the session saves it after every step; others may have since
        if state is None or not state.complete:
            return None
        kept = self.kept_copies(paths)
        return StateSummary(
            folder=state.folder,
            name=state.name,
            mode=state.mode,
            in_use_on=state.name if state.mode == "in_use" else in_use_on(paths, state),
            last_saved_at=state.last_saved_at,
            base_from=state.base.from_name if state.base is not None else None,
            base_arrived_at=state.base.arrived_at if state.base is not None else None,
            notices=[SyncNotice.model_validate(notice.model_dump()) for notice in state.notices],
            kept=kept,
            data_folder_synced=data_folder_synced(paths.data_dir),
            journal=unfinished(paths) is not None,
        )

    def kept_copies(self, paths: Paths) -> list[SyncKept]:
        """Every kept copy on this computer — connected or not (they outlive Disconnect)."""
        state = load_state(paths)
        return [
            SyncKept(name=info.name, path=str(path), size=size, created_at=info.created_at, why=info.why)
            for info, path, size in kept_copies(
                paths.sync / KEPT_DIR, state.kept if state is not None else ()
            )
        ]

    def writes_refused(self, paths: Paths) -> str | None:
        return core.writes_refused(paths)

    def resume_interrupted(self, paths: Paths) -> Any:
        return resume_interrupted(paths)

    def inspect_folder(self, value: str, paths: Paths, settings: AppSettings) -> Any:
        return core.inspect_folder(value, paths, settings)

    # ---- connecting -----------------------------------------------------------------------------

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
    ) -> Connected:
        """The core's :func:`~ordnung.sync.engine.connect`: a new folder is set up and saved into; joining
        brings the data over (or waits for it, standing by), or answers the choice (nothing connected)."""
        with caldav.exclusive():
            result = core.connect(paths, folder, name, passphrase, secrets=secrets, store=store, keep=keep)
        if result.choice is not None and not result.connected:
            local = RealLocal(
                inner=LocalView(computer="", mode="standing_by", base=None, pending=False, next_pnum=1),
                pending=False,
                name=clean_name(name),
                here=live_summary(store._conn()),
                base=Summary(),
            )
            summaries: dict[str, Summary] = {}
            saved: dict[str, str] = {}
            for side in result.choice.sides:
                manifest = side.head.completeness.manifest if side.head and side.head.completeness else None
                if side.head is not None and manifest is not None:
                    summaries[side.head.computer] = manifest.summary
                    saved[side.head.computer] = manifest.created_at
            view = RealView(FolderView(), [], summaries, saved)
            return Connected(created=False, choice=_choice(result.choice, local, view))
        if result.session is not None:
            with self._lock:
                self._fresh[self._key(paths)] = result.session
                self._live.pop(self._key(paths), None)
        return Connected(created=result.created)

    def open_session(self, paths: Paths, secrets: SecretStore) -> RealSession:
        """Unlock the folder: the password store (a locked one raises
        :class:`~ordnung.calendar.secrets.SecretsLocked`), then scrypt."""
        key = self._key(paths)
        with self._lock:
            fresh = self._fresh.pop(key, None)
        if fresh is not None:
            session = RealSession(fresh)
        else:
            state = load_state(paths)
            if state is None or not state.complete:
                raise SyncError("not_connected", NOT_CONNECTED_MESSAGE)
            passphrase = secrets.get(keyring_account(state.computer))  # SecretsUnavailable/-Locked
            if not passphrase:
                raise SyncError("passphrase_needed", core.PASSPHRASE_NEEDED_MESSAGE)
            session = RealSession(core.Session.open(paths, secrets, passphrase=passphrase))
        with self._lock:
            self._live[key] = session
        return session

    def decide(self, local: RealLocal, view: RealView, action: Any) -> AgentDecision:
        if local.problem is not None:
            if local.repair is not None:  # F10 / finding 4: put the last saved state back (fenced)
                return AgentDecision("repair", target=local.repair, keep=True, why=ROLLBACK_WHY)
            return _paused(local.problem)
        wanted = Action("use_here", older_copy=bool(action.older_copy)) if action is not None else None
        return map_decision(decide(local.inner, view.inner, wanted), local, view)

    def push_once(self, paths: Paths, secrets: SecretStore) -> str:
        with Store.open(paths, durable=True) as store:
            return core.push_once(paths, secrets, store)

    def set_passphrase(self, paths: Paths, secrets: SecretStore, passphrase: str) -> None:
        state = load_state(paths)
        if state is None:
            raise SyncError("not_connected", NOT_CONNECTED_MESSAGE)
        vault = open_key_file(state.key_file, bytes.fromhex(state.key_file_bytes), passphrase)
        if vault.id != state.vault:
            raise WrongSyncPassphrase()
        secrets.set(keyring_account(state.computer), passphrase)
        self._forget_session(paths)

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
    ) -> None:
        live = self._session_of(paths)
        local = Local(paths)
        state = live.inner.state if live is not None else local.load()
        if state is None:
            raise SyncError("not_connected", NOT_CONNECTED_MESSAGE)
        if abandon_pull and unfinished(paths) is not None:
            if not abandon(paths):
                raise SyncError("pull_unfinished", ABANDON_TOO_LATE)
            notice = notice or ("pull_abandoned", ABANDONED_MESSAGE, None)
            if live is not None and live.inner.problem is not None:
                live.inner.problem = None
        if name is not None:
            state.name = clean_name(name)
        if folder is not None:
            state.folder = str(folder)
        if confirm_same_computer:
            state.data_dir = str(paths.data_dir.resolve())
            state.machine = machine_id()
            if live is not None and live.inner.problem is not None:
                live.inner.problem = None
        if dismiss_notice is not None:
            state.notices = [found for found in state.notices if found.id != dismiss_notice]
        if notice is not None:
            code, message, kept = notice
            state.notices = [
                *state.notices,
                Notice(id=tokens.token_hex(6), code=code, message=message, kept=kept, at=_now()),
            ][-20:]
        if live is not None:
            live.inner.save()
            if name is not None:
                with contextlib.suppress(SyncError, OSError):
                    live.inner.write_head()
        else:
            local.save(state)
        if folder is not None:
            self._forget_session(paths)  # the next open uses the folder chosen again

    def disconnect(
        self, paths: Paths, secrets: SecretStore, *, forget_passphrase: bool, store: Store
    ) -> None:
        """The core's :func:`~ordnung.sync.engine.disconnect` (the agent asked for the second
        confirmation already): the head says ``left``; ``<data>/sync/`` goes, kept copies stay."""
        live = self._session_of(paths)
        self._forget_session(paths)
        core.disconnect(
            paths,
            secrets,
            store,
            session=live.inner if live is not None else None,
            forget_passphrase=forget_passphrase,
            unreceived_ok=True,
        )

    def delete_kept(self, paths: Paths, name: str) -> bool:
        live = self._session_of(paths)
        if live is not None:
            return delete_kept_copy(live.inner, name)
        if not KEPT_RE.fullmatch(name):
            return False
        path = paths.sync / KEPT_DIR / name
        if not path.is_file() or path.is_symlink():
            return False
        path.unlink()
        write_index(path.parent, (), gone=[name])
        local = Local(paths)
        state = local.load()
        if state is not None:
            state.kept = [info for info in state.kept if info.name != name]
            local.save(state)
        return True


#: The façade of this installation (:func:`ordnung.sync.agent.load_engine`).
ENGINE = RealEngine()
