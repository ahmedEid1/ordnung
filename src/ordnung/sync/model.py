"""The records of hand-off sync: what the folder holds (heads, manifests, buckets — design §4.4-4.5, every
one sealed by :mod:`ordnung.sync.crypto`) and what stays in ``<data>/sync/`` (design §5).

Every record is strict (``extra="forbid"``): a field Ordnung never writes makes the record unreadable,
so a crafted manifest or head can't smuggle anything in. Counts, sizes and names are bounded before
anything is allocated (:data:`~ordnung.sync.MAX_RECORD_BYTES` caps the sealed record itself).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ordnung.sync import MAX_FILES, NAME_MAX_CHARS, WANTS_MAX, HeadState, SyncNoticeCode

Hex32 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ObjectName = Hex32
#: An inclusive range of person numbers, ``(first, last)`` with ``1 ≤ first ≤ last``.
Range = tuple[Annotated[int, Field(ge=1)], Annotated[int, Field(ge=1)]]
Count = Annotated[int, Field(ge=0)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Local(BaseModel):
    """This computer's own files: strict, but changed in place."""

    model_config = ConfigDict(extra="forbid", validate_assignment=False)


# --------------------------------------------------------------------------------------------------
# versions
# --------------------------------------------------------------------------------------------------


class VersionId(_Strict):
    """A version: the computer that pushed it and that computer's push number."""

    computer: Hex32
    seq: int = Field(ge=1)

    def key(self) -> str:
        return f"{self.computer}:{self.seq}"


class Lineage(_Strict):
    """The person changes a version contains, and those a choice left out (:mod:`ordnung.sync.lineage`)."""

    content: dict[Hex32, list[Range]] = Field(default_factory=dict)
    dropped: dict[Hex32, list[Range]] = Field(default_factory=dict)


class VersionRef(_Strict):
    """A version as a head names it: enough to find, size-check and authenticate its manifest."""

    id: VersionId
    lineage: Lineage
    #: the state digest (:func:`ordnung.sync.scrub.state_digest`): equal digests = equal synced data
    digest: Sha256Hex
    manifest: ObjectName
    #: the manifest's plaintext length and SHA-256 (its sealed size follows from the length)
    manifest_size: Count
    manifest_sha256: Sha256Hex


class Head(_Strict):
    """One computer's head (``h/<H>``): rewritten in place, only by that computer."""

    format: Literal[1]
    vault: Hex32
    computer: Hex32
    name: str = Field(min_length=1, max_length=NAME_MAX_CHARS)
    #: +1 on every rewrite: a head older than one already seen is a replay (F15)
    written: int = Field(ge=1)
    state: HeadState
    #: the lease epoch this computer last claimed (§8)
    epoch: int = Field(ge=0)
    #: the version this computer's data equals (its own, or one it pulled); kept when it left
    version: VersionRef | None
    #: the newest other version whose objects have all arrived *and verified* here (finding 6)
    has: VersionId | None
    #: the highest person number this computer ever published (finding 18)
    pnum: Count = 0
    #: objects this computer found damaged or long missing: whoever has the content writes them again
    wants: list[ObjectName] = Field(default_factory=list, max_length=WANTS_MAX)
    #: computers the person removed from this folder (§13.5)
    forgotten: list[Hex32] = Field(default_factory=list, max_length=4096)
    app_version: str = Field(max_length=64)
    schema_version: Count
    #: SHA-256 of this computer's calendar connection (address and user name), and its mode
    calendar_target: Sha256Hex | None = None
    calendar_mode: str | None = Field(default=None, max_length=32)


# --------------------------------------------------------------------------------------------------
# manifests and buckets
# --------------------------------------------------------------------------------------------------


class DbSlice(_Strict):
    sha256: Sha256Hex
    size: Count


class DbInfo(_Strict):
    size: Count
    sha256: Sha256Hex
    page_size: int = Field(ge=512, le=65536)
    tables: dict[str, Count]
    slices: list[DbSlice] = Field(max_length=1_000_000)


class BucketRef(_Strict):
    key: str = Field(max_length=64)
    sha256: Sha256Hex
    size: Count
    count: Count


class FileEntry(_Strict):
    path: str = Field(max_length=1024)
    sha256: Sha256Hex
    size: Count


class Bucket(_Strict):
    format: Literal[1]
    key: str = Field(max_length=64)
    entries: list[FileEntry] = Field(max_length=MAX_FILES)


class SummaryLetter(_Strict):
    label: str = Field(max_length=500)
    added_on: str = Field(max_length=10)


#: What a change in a summary was made to (a person's record).
ChangeKind = Literal["letter", "date", "to-do", "note", "contract"]


class SummaryChange(_Strict):
    """One of a version's latest changes: what it was made to, its title, the calendar date."""

    kind: ChangeKind
    label: str = Field(max_length=500)
    on: str = Field(max_length=10)


class Summary(_Strict):
    """What a version holds, for a choice between versions: its letters, the open and done dates and
    to-dos, the notes, and the latest changes (a choice whose sides differ in to-dos, done marks or
    edits is told apart by them — review)."""

    letters: Count = 0
    newest: list[SummaryLetter] = Field(default_factory=list, max_length=3)
    items: Count = 0
    done: Count = 0
    notes: Count = 0
    latest: list[SummaryChange] = Field(default_factory=list, max_length=3)


class CalendarHandover(_Strict):
    """What a computer sent to its calendar: travels with the data, under a hashed target (§6.4)."""

    target: Sha256Hex
    mode: str = Field(max_length=32)
    events: dict[str, str] = Field(default_factory=dict, max_length=200_000)
    checked_on: str | None = None


class Manifest(_Strict):
    """A version (``m`` object): its lineage, its database slices and its file buckets."""

    format: Literal[1]
    vault: Hex32
    version: VersionId
    base: VersionId | None
    lineage: Lineage
    epoch: Count
    #: the writer's clock; shown only, as "(anna-thinkpad's clock)"
    created_at: str = Field(max_length=40)
    app_version: str = Field(max_length=64)
    schema_version: Count
    db: DbInfo
    buckets: list[BucketRef] = Field(max_length=4096)
    files_count: int = Field(ge=0, le=MAX_FILES)
    files_bytes: Count
    digest: Sha256Hex
    summary: Summary
    calendar: CalendarHandover | None = None


# --------------------------------------------------------------------------------------------------
# <data>/sync/ (never synced, never in a backup)
# --------------------------------------------------------------------------------------------------


class BaseInfo(_Strict):
    """The version this computer's data equals: where it came from and when it arrived here."""

    ref: VersionRef
    summary: Summary = Field(default_factory=Summary)
    #: this computer's clock
    arrived_at: str
    from_name: str


class SeenHead(_Local):
    """What this computer last saw of a head (F15 replay guard; "arrived here" times)."""

    written: int
    computer: Hex32
    #: this computer's clock: when the head's current version first arrived here
    version_at: str | None = None
    version: str | None = None
    first_seen_at: str


class Notice(_Strict):
    id: str
    code: SyncNoticeCode
    message: str
    kept: str | None = None
    at: str


class KeptInfo(_Strict):
    """A kept copy in ``sync/kept/``: why it was written, and the digest of what it holds."""

    name: str
    why: str
    digest: str | None = None
    created_at: str


class Garbage(_Local):
    """An object first seen unreferenced: GC deletes it after 7 days of wall clock *and* running time."""

    since: str
    runtime: float


class Waiting(_Strict):
    """A take-over (or a chosen side) waiting until its version has arrived (finding 23)."""

    target: VersionId
    head: Hex32
    target_pnum: Count
    since: str
    runtime: float
    choose: bool = False


class LocalState(_Local):
    """``<data>/sync/state.json``: this computer's sync state (design §5, with the review's findings)."""

    format: Literal[1] = 1
    #: False while ``connect`` runs: a retry recognises its own key file (finding 34)
    complete: bool = True
    folder: str
    key_file: Hex32
    key_file_bytes: str
    vault: Hex32
    computer: Hex32
    name: str
    keyring_account: str
    data_dir: str
    machine: str
    mode: Literal["in_use", "standing_by"] = "in_use"
    #: what this computer's head says (``closed`` after Ordnung stopped here while in use)
    head_state: HeadState = "in_use"
    #: the newest other version that fully arrived and verified here (written into the head)
    has: VersionId | None = None
    #: computers the person removed from this folder here (written into the head)
    forgotten: list[Hex32] = Field(default_factory=list)
    #: this computer's counters, reserved before use (never reused, even after a crash)
    epoch: Count = 0
    seq: Count = 0
    pnum: Count = 0
    written: Count = 0
    base: BaseInfo | None = None
    #: the last bases (the local-rollback check; GC keeps what a waiting computer has of them)
    recent: list[VersionRef] = Field(default_factory=list)
    #: the next push counts as a person change whatever the counter says ("keep this data as it is")
    force_person: bool = False
    #: the person-change counter (meta ``sync_person``) the last push or pull accounted for
    pushed: int = 0
    #: head file name → what was last seen of it
    seen: dict[str, SeenHead] = Field(default_factory=dict)
    #: head file name → its small number for the UI
    keys: dict[str, int] = Field(default_factory=dict)
    garbage: dict[str, Garbage] = Field(default_factory=dict)
    #: objects known present in the folder → their sealed size
    present: dict[str, int] = Field(default_factory=dict)
    notices: list[Notice] = Field(default_factory=list)
    kept: list[KeptInfo] = Field(default_factory=list)
    waiting: Waiting | None = None
    #: this computer's accumulated running time (seconds), for GC's grace
    runtime: float = 0.0
    last_gc_at: str | None = None
    last_gc_runtime: float = 0.0
    last_saved_at: str | None = None
    #: the last calendar hand-over received, sent on while this computer has no such connection
    calendar_received: CalendarHandover | None = None
    #: objects this computer asks the others to write again (its head's ``wants``)
    wants: list[str] = Field(default_factory=list)
    #: the person confirmed this computer's data as it is after a rollback could not be repaired
    forgotten_by: str | None = None


class FilesCacheEntry(_Local):
    size: int
    mtime_ns: int
    ino: int
    sha256: str


class Journal(_Local):
    """``<data>/sync/pull.json``: a pull past its commit point (design §11.5)."""

    format: Literal[1] = 1
    target: VersionRef
    from_name: str
    summary: Summary
    kept: str | None = None
    #: staged files (relative to the data folder), each moved into place by the apply
    files: list[str] = Field(default_factory=list)
    #: every path the target's buckets hold (prune keeps these)
    keep_paths: list[str] = Field(default_factory=list)
    #: the target's files with their hashes (the files cache is updated from them)
    entries: list[FileEntry] = Field(default_factory=list)
    calendar: CalendarHandover | None = None
    stage: Literal["staged", "database"] = "staged"
    #: the database step failed (the person may abandon the pull: finding 12)
    failed: str | None = None
