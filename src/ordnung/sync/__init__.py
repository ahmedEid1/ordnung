"""Hand-off sync between the person's own computers, through a folder their sync tool already keeps in
step (ADR 0018; Settings → Your computers, ``ordnung sync``).

Written policy (ADR 0007 style)
-------------------------------

* **In use on one computer at a time.** The other computers are *standing by*: they change no person
  data — every write outside :data:`API_PATH` and :data:`ALLOWED_IN_STANDBY` answers 409 ``standby``
  before any handler runs, on the computer's listener and the phone's — and they run no background
  work (readings, the day change, the brief, the watched folder, calendar sync, desktop reminders).
  "Use Ordnung here" brings everything over and makes that computer the one in use. It is never
  refused for the other computer's sake and never asks "are you sure?": a take-over loses nothing.
* **The folder holds only ciphertext, under names that say nothing.** The computer in use saves an
  encrypted copy a few seconds after a change (:data:`PUSH_PERSON_QUIET_S` after the person's,
  :data:`PUSH_QUIET_S` after background work) and when Ordnung stops. Every file is AES-256-GCM STREAM
  under keys derived from a random vault key; scrypt of the passphrase (:data:`SYNC_KDF`: 2^18, r 8,
  256 MiB) wraps that key in the :data:`KEY_FILE_BYTES`-byte key file, which carries no plaintext byte.
  Names are keyed hashes; sizes are rounded up by Padmé (at most 12 %, at least :data:`MIN_PADDED`
  bytes). Whoever sees the folder learns that it is an encrypted object store, how many computers take
  part, when files change and — from bursts of new objects — roughly how many letters and pages are
  added; never names, dates, senders, content, file types or the computers' names. The sync tool's own
  history and trash may keep old ciphertext.
* **The passphrase lives in each computer's password store** (the OS keyring, service
  :data:`SYNC_SERVICE`, account :data:`KEYRING_ACCOUNT`), typed once per computer. It is never in the
  folder, the database, ``sync/state.json``, a log, an API answer or a backup; the status never reads
  it. A computer without a usable password store can't sync (there is no file fallback). A *new*
  folder's passphrase must pass :func:`passphrase_problem` (about :data:`MIN_PASSPHRASE_BITS` bits of
  estimated entropy); setup suggests :data:`SUGGESTED_WORDS` random words.
* **Nothing is merged, and no change of the person's is lost silently.** A version records which
  *person changes* it contains; background work never makes a version newer, so it never causes a
  question. Local data is replaced only when the incoming version contains every person change it has,
  when the person chose, or when the local database went back in time — and in the last two cases an
  encrypted *kept copy* of the local data is written first. When two computers both changed something,
  the person is asked once which computer's Ordnung to keep.
* **Nothing unverified is applied.** A take-over waits until every object of the version has arrived
  and authenticated with its expected SHA-256 (an online-only placeholder, a short or unreadable file
  is "not arrived yet", never damage), stages and verifies it outside the live data, and only then
  replaces the database in one SQLite transaction.
* **Per-computer state never leaves and is never overwritten:** :data:`LOCAL_META` (paired phones, the
  calendar connection, the watched folder's memory, the Claude pause, desktop-reminder bookkeeping,
  :data:`SYNC_MARK_KEY`, :data:`PERSON_META_KEY`), :data:`LOCAL_SETTINGS`, the privacy-log rows of
  :data:`LOCAL_ACTIVITY_KINDS` / :data:`LOCAL_ACTIVITY_PREFIXES`, and every data-folder entry but
  :data:`SYNCED_DIRS` (``inbox/``, ``phone/``, ``sync/``, the lock, ``server.json``, the WAL …).
  :data:`MERGED_META` is synced as a union and is left out of the state digest.
* **Ordnung deletes only what it named.** In the folder it removes its own temp files, and objects that
  stayed unreferenced for :data:`GC_GRACE_S` of its own clock *and* :data:`GC_GRACE_RUNTIME_S` of its
  own running time. It never touches a name that doesn't match :data:`KEY_FILE_RE`, :data:`HEAD_RE`,
  :data:`SHARD_RE`, :data:`OBJECT_RE` or :data:`TEMP_RE`.
* **Kept copies** are ordinary encrypted backups (format v1, the sync passphrase) in
  ``<data>/sync/kept/`` (:data:`KEPT_RE`): never synced, never pruned by themselves, and lost with this
  computer's disk and with Delete everything.
* **The demo never syncs** (:data:`DEMO_MESSAGE`).

Refusals answer ``{"detail": <words for the person>, "code": <SyncErrorKind>}`` with the status
:data:`ERROR_STATUS` gives that code; :class:`SyncError` (a :class:`~ordnung.backup.BackupError`)
carries the same ``kind``.

Every name here is part of the contract the sync packages share (design §27, with the binding
amendments): changing a value changes what the docs promise.
"""

from __future__ import annotations

import math
import re
import unicodedata
from typing import Literal

from ordnung.backup import BackupError, KdfParams
from ordnung.backup import passphrase_problem as _length_problem
from ordnung.backup.archive import _LEFT_OUT_META
from ordnung.calendar.caldav import STATE_KEY as _CALENDAR_STATE_KEY
from ordnung.calendar.caldav import UID_KEY_META as _CALENDAR_UID_KEY
from ordnung.ingest.own_files import MAX_OWN_FILES, OWN_FILES_META_KEY
from ordnung.ingest.watcher import BASELINE_META_KEY, SEEN_META_KEY
from ordnung.ingest.worker import PAUSE_META_KEY
from ordnung.notify.desktop import FAILED_KEY as _DESKTOP_FAILED_KEY
from ordnung.notify.desktop import LAST_SHOWN_KEY as _DESKTOP_SHOWN_KEY

_KIB = 1024
_MIB = 1024 * _KIB
_GIB = 1024 * _MIB
_DAY_S = 24 * 3600

# --------------------------------------------------------------------------------------------------
# the folder, format 1
# --------------------------------------------------------------------------------------------------

#: The sync folder's format (the key file's ``format`` byte; heads, manifests and buckets say it too).
FOLDER_FORMAT = 1
#: scrypt for the key file: 2^18, r 8, p 1 — 256 MiB, the most a backup reader allows. Fixed for
#: format 1, so the folder stores no parameter byte.
SYNC_KDF = KdfParams(log2_n=18, r=8, p=1)
#: nonce (12) ‖ AES-256-GCM(64-byte body) with its tag (16): no plaintext field at all.
KEY_FILE_BYTES = 92
#: Plaintext bytes per sealed chunk; every chunk but the last is full, and the last always exists.
CHUNK = 1 * _MIB
#: The database snapshot is cut into slices of this size (a multiple of every SQLite page size).
DB_SLICE = 1 * _MIB
#: The smallest padded plaintext (hides small files).
MIN_PADDED = 4096
#: salt (16) ‖ nonce prefix (7) before the first chunk; each chunk adds a 16-byte tag, so
#: ``sealed_size(P) = SEAL_HEADER_BYTES + P + SEAL_TAG_BYTES · max(1, ⌈P / CHUNK⌉)``.
SEAL_HEADER_BYTES = 23
SEAL_TAG_BYTES = 16
#: Caps checked before allocating: heads, manifests and buckets; one data file; files per version.
MAX_RECORD_BYTES = 64 * _MIB
MAX_FILE_BYTES = 4 * _GIB
MAX_FILES = 1_000_000
#: Computers per folder (a UI and scan-cost guard, not a format limit).
MAX_COMPUTERS = 8
#: Ranges per lineage; beyond it a push fails ("set up a new sync folder").
LINEAGE_RANGES_MAX = 4096
#: Object names a head may ask other computers to write again (damaged or long missing).
WANTS_MAX = 64

#: The kinds of sealed file: head, manifest, bucket, database slice, data file.
ObjectKind = Literal["h", "m", "b", "d", "f"]
OBJECT_KINDS: tuple[ObjectKind, ...] = ("h", "m", "b", "d", "f")
#: Content-named kinds: the same content gets the same name and — salt and nonce prefix derived from
#: the name — the same bytes on every computer, so two writers never make a sync-tool conflict copy.
CONTENT_NAMED_KINDS: frozenset[ObjectKind] = frozenset({"m", "b", "d", "f"})

#: Folder layout: ``<K>`` key file, ``h/<H>`` heads, ``o/<xx>/<rest>`` objects, ``.<t><r>.tmp`` writes in
#: progress. Readers recognise only these names; everything else is ignored and never deleted.
HEADS_DIR = "h"
OBJECTS_DIR = "o"
KEY_FILE_RE = re.compile(r"^[0-9a-f]{32}\Z")
HEAD_RE = re.compile(r"^[0-9a-f]{32}\Z")
SHARD_RE = re.compile(r"^[0-9a-f]{2}\Z")
OBJECT_RE = re.compile(r"^[0-9a-f]{30}\Z")
TEMP_RE = re.compile(r"^\.[0-9a-f]{16}\.tmp\Z")

#: What a head says about its computer.
HeadState = Literal["in_use", "standing_by", "closed", "left"]

# --------------------------------------------------------------------------------------------------
# this computer's sync state: <data>/sync/ (never synced, never in a backup)
# --------------------------------------------------------------------------------------------------

#: ``<data>/sync/`` and what it holds.
LOCAL_DIR = "sync"
STATE_FILE = "state.json"
FILES_CACHE_FILE = "files.json"
#: The last good plaintext of every head (each scan decrypts every head; F14's last good copy, GC's refs).
HEADS_FILE = "heads.json"
#: The pull journal: exists only while a pull is applied.
JOURNAL_FILE = "pull.json"
INCOMING_DIR = "incoming"
KEPT_DIR = "kept"
#: Bases remembered for the local-rollback check.
RECENT_BASES = 16
#: The keyring account of this computer's sync passphrase (per data folder, like calendar sync's).
KEYRING_ACCOUNT = "computer:{computer}"
SYNC_SERVICE = "Ordnung sync"
SYNC_FEATURE = "Sync between computers"
SYNC_SECRET = "the sync passphrase"
#: Feeds ``ordnung sync connect`` and ``ordnung sync passphrase`` without a prompt (still stored only in
#: the keyring).
PASSPHRASE_ENV = "ORDNUNG_SYNC_PASSPHRASE"
#: ``ordnung-kept-<local YYYY-MM-DD-HHMM>[-n].ordnung-backup``
KEPT_RE = re.compile(r"^ordnung-kept-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}(-[0-9]+)?\.ordnung-backup\Z")
#: Kept copies above this size in all get a warning.
KEPT_WARN_BYTES = 2 * _GIB
#: A computer's name, as the person gave it ("anna-thinkpad"; a taken name gets " (2)").
NAME_MAX_CHARS = 40

# --------------------------------------------------------------------------------------------------
# timing (this computer's own clocks only; nothing compares two computers' clocks)
# --------------------------------------------------------------------------------------------------

#: How often the computer in use looks at ``PRAGMA data_version``.
WATCH_S = 2.0
#: A save follows this long after the person's last write …
PUSH_PERSON_QUIET_S = 2.0
#: … and this long after background work's last write …
PUSH_QUIET_S = 10.0
#: … and at the latest this long after the first unsaved one.
PUSH_MAX_WAIT_S = 60.0
#: A failed save is tried again after these waits (the last one repeats) …
PUSH_RETRY_S: tuple[float, ...] = (30.0, 60.0, 120.0, 240.0, 480.0, 900.0)
#: … and becomes a problem (``save_failing``, ``folder_full``) after this long.
FAILING_AFTER_S = 1800.0
#: How often the folder's heads are read; while a take-over waits, how often arrival is checked.
SCAN_S = 15.0
WAIT_POLL_S = 5.0
#: At start, how long the first decision may take before the computer goes on in its last known mode.
START_DECIDE_S = 5.0
#: The last save when Ordnung stops, at most.
SHUTDOWN_PUSH_S = 20.0
#: Before data is replaced, how long writes already admitted may take to finish (else retried later).
FENCE_WAIT_S = 30.0
#: Every folder operation (stat, list, read, write) gives up after this long: ``folder_unreachable``.
FOLDER_OP_TIMEOUT_S = 30.0
#: Without progress for this long, waiting for the sync tool becomes a problem (``arrival_stalled``),
#: and a standing-by computer still without the latest gives the one in use ``not_received``.
ARRIVAL_PATIENCE_S = 1800.0
#: A waiting take-over is cancelled after this long (or when its target saves a new person change).
TAKE_OVER_WAIT_MAX_S = 1800.0
#: An object of the right size that keeps failing authentication is damaged after this long.
DAMAGED_AFTER_S = 600.0
#: The computer in use checks that its own version's objects are all there at most this often.
SELF_HEAL_EVERY_S = 600.0
#: Garbage collection: at most once a day; an object unreferenced for 7 days of wall clock *and* 7 × 24 h
#: of this computer's running time is deleted.
GC_EVERY_S = float(_DAY_S)
GC_GRACE_S = float(7 * _DAY_S)
GC_GRACE_RUNTIME_S = float(7 * _DAY_S)
#: Only if the measured database-slice churn exceeds :data:`SLICE_CHURN_LIMIT_BYTES` per save: superseded
#: database slices go after this long, once every live head is newer.
SLICE_CHURN_LIMIT_BYTES = 5 * _MIB
SUPERSEDED_SLICE_GRACE_S = float(_DAY_S)

# --------------------------------------------------------------------------------------------------
# what travels and what stays (meta keys, settings fields, data-folder entries, privacy-log rows)
# --------------------------------------------------------------------------------------------------

#: The version the database holds (a ``VersionId``); written in the pull's own transaction.
SYNC_MARK_KEY = "sync_mark"
#: The person-change counter: bumped inside the same transaction as every write the person made
#: (``Store`` sees the ``PERSON_WRITE`` context set by the gate, the watched folder and the CLI).
PERSON_META_KEY = "sync_person"
#: The SHA-256 of every file brought in from any watched folder, so a folder both computers watch
#: doesn't bring deleted letters back (merged as a union, capped at :data:`FOLDER_TAKEN_MAX`).
FOLDER_TAKEN_META_KEY = "folder_taken"
FOLDER_TAKEN_MAX = 5000
#: The job-interruption counter's meta key (``db.store``).
INTERRUPTIONS_META_KEY = "job_interruptions"

#: Per computer: scrubbed from every push; on every pull this computer keeps its own value (or none).
LOCAL_META: frozenset[str] = frozenset(
    {
        *_LEFT_OUT_META,  # "phone_access": a paired phone belongs to its computer (shared with backups)
        _CALENDAR_STATE_KEY,  # "calendar_sync": the connection (its "already sent" record travels apart)
        SEEN_META_KEY,  # "inbox_seen"
        BASELINE_META_KEY,  # "inbox_baseline"
        INTERRUPTIONS_META_KEY,
        PAUSE_META_KEY,  # "llm_paused_until": this computer's Claude pause
        _DESKTOP_SHOWN_KEY,  # "desktop_notified_on"
        _DESKTOP_FAILED_KEY,  # "desktop_notify_failed"
        SYNC_MARK_KEY,
        PERSON_META_KEY,
    }
)
#: Synced, but merged on pull as a union (newest first, capped) and left out of the state digest.
MERGED_META: frozenset[str] = frozenset({OWN_FILES_META_KEY, FOLDER_TAKEN_META_KEY})
#: The caps of :data:`MERGED_META`.
MERGED_META_MAX: dict[str, int] = {OWN_FILES_META_KEY: MAX_OWN_FILES, FOLDER_TAKEN_META_KEY: FOLDER_TAKEN_MAX}
#: Demo only: scrubbed on push, and a database that arrives with one is refused.
DEMO_META: frozenset[str] = frozenset({"simulated_today", "demo_tray", "demo_tour"})
#: The person's Ordnung.
SYNCED_META: frozenset[str] = frozenset(
    {
        "profile",
        "settings",
        _CALENDAR_UID_KEY,  # "calendar_uid_key": both computers name a date's event alike
        "last_tick_date",
        "last_review_at",
        "weekly_session_at",
        "weekly_prompt_dismissed_at",
        "last_calendar_export_at",
    }
)
SYNCED_META_PREFIXES: tuple[str, ...] = ("brief:",)

#: ``AppSettings`` fields that stay on each computer (reset to their defaults in a pushed copy, kept from
#: the live settings on pull) …
LOCAL_SETTINGS: tuple[str, ...] = (
    "inbox_dir",
    "inbox_auto_read",
    "concurrency",
    "desktop_notifications",
    "desktop_notify_time",
    "demo",
    "simulated_today",
)
#: … and the ones that travel.
SYNCED_SETTINGS: tuple[str, ...] = ("models", "model", "llm_brief", "llm_review")

#: Privacy-log rows that stay on the computer that wrote them (scrubbed from pushes, left out of the
#: digest, carried over from the live database on pull): a backup made here, this computer's phone
#: access and its watched folder (which names a local path).
LOCAL_ACTIVITY_KINDS: frozenset[str] = frozenset({"backup.created"})
LOCAL_ACTIVITY_PREFIXES: tuple[str, ...] = ("phone.", "folder.")

#: The data-folder entries that travel; nothing else of the data folder is ever walked.
SYNCED_DIRS: tuple[str, ...] = ("files", "derived", "drafts")

# --------------------------------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------------------------------

#: Operation = ``(METHOD, OpenAPI path template)``, as in :mod:`ordnung.phone.scope`.
Operation = tuple[str, str]
#: Hand-off sync's own routes: ``/api/sync`` and ``/api/sync/…``, matched by whole path segments
#: (``/api/syncfoo`` is not one). Always allowed, and never a person change.
API_PATH = "/api/sync"
#: Writes a standing-by computer still allows (besides :data:`API_PATH`): a backup only reads (its
#: privacy-log row is local), and phone access belongs to this computer.
ALLOWED_IN_STANDBY: frozenset[Operation] = frozenset(
    {
        ("POST", "/api/backup"),
        ("PUT", "/api/phone"),
        ("POST", "/api/phone/pairing"),
        ("DELETE", "/api/phone/pairing"),
        ("DELETE", "/api/phone/devices/{device_id}"),
        ("POST", "/api/phone/reset"),
        ("POST", "/api/phone/pair"),
    }
)
#: Writes that are not the person's changes (besides :data:`API_PATH`): they write only bookkeeping or
#: per-computer state, so they don't count toward the person-change counter.
NOT_PERSON_CHANGES: frozenset[Operation] = ALLOWED_IN_STANDBY | {("POST", "/api/calendar/sync/run")}

# --------------------------------------------------------------------------------------------------
# kinds: modes, problems, notices, privacy-log rows, refusals
# --------------------------------------------------------------------------------------------------

#: ``off``: not connected (or unavailable, or the demo); ``starting``: the first look at the folder;
#: ``in_use``: this computer is the one in use; ``standing_by``: another computer is.
SyncMode = Literal["off", "starting", "in_use", "standing_by"]
#: What sync is busy with now.
SyncActivity = Literal["idle", "saving", "waiting", "bringing_over", "keeping"]
#: A computer as this one sees it (``unknown``: its head can't be read now).
ComputerState = Literal["in_use", "standing_by", "closed", "left", "unknown"]
#: Calendar sync on another computer compared with this one's: ``none`` there; ``same`` calendar and
#: mode; ``different_mode`` (the same calendar, another mode: each switch rewrites the events);
#: ``other`` (another calendar, or none here).
CalendarMatch = Literal["none", "same", "different_mode", "other"]

#: Why sync is paused or needs the person (the web shows ``title`` and ``message``, never the code).
SyncProblemCode = Literal[
    "folder_missing",  # no key file, the folder is missing or not a folder (never recreated)
    "folder_empty",  # the folder exists but holds none of Ordnung's names (never refilled by itself)
    "folder_other",  # the folder now holds a different sync (another vault)
    "folder_full",  # ENOSPC / EDQUOT while writing into the folder
    "folder_unreachable",  # a folder operation timed out (a hung network share, a File Provider read)
    "online_only",  # files are online-only placeholders here: make the folder available offline
    "two_setups",  # another computer started a separate sync in this folder
    "passphrase_needed",  # the password store lost the passphrase (or it no longer opens the folder)
    "keyring_unavailable",  # no usable password store on this computer any more
    "keyring_locked",  # the password store is locked
    "newer_ordnung",  # another computer runs a newer Ordnung (format or schema)
    "arrival_stalled",  # waiting for the sync tool without progress for ARRIVAL_PATIENCE_S
    "not_received",  # a standing-by computer hasn't received this one's latest for ARRIVAL_PATIENCE_S
    "pull_unfinished",  # a take-over couldn't finish placing the data
    "no_space",  # this computer lacks the space to take over
    "damaged",  # an object in the folder stays damaged
    "local_damaged",  # a local original no longer matches its name's SHA-256 (it is not saved)
    "copied_folder",  # the data folder was copied or moved (another path or machine)
    "local_rollback",  # the local data went back in time and the last saved state isn't there to restore
    "save_failing",  # saving has failed for FAILING_AFTER_S
    "forgotten",  # another computer removed this one from sync
]
#: What the person can do about a problem (first: the main action).
SyncProblemAction = Literal[
    "passphrase",  # type the passphrase again (POST /api/sync/passphrase)
    "choose_folder",  # choose the folder again (PUT /api/sync with the same vault)
    "refill",  # fill it again from this computer (POST /api/sync/refill)
    "same_computer",  # "This is the same computer" (PATCH /api/sync {confirm_same_computer})
    "new_computer",  # "Set up as a new computer" (DELETE /api/sync, then set up again)
    "keep_as_is",  # "Keep this computer's data as it is" (PATCH /api/sync {keep_as_is})
    "abandon",  # give up an unfinished take-over (PATCH /api/sync {abandon_pull})
]
#: Things the person should know about once (dismissed with PATCH /api/sync {dismiss_notice}).
SyncNoticeCode = Literal[
    "chosen_elsewhere",  # another computer's Ordnung was chosen there; this one's was kept as a copy
    "kept",  # this computer's earlier data was saved as a kept copy
    "rolled_back",  # the local data went back in time; the last saved state was put back
    "take_over_cancelled",  # a waiting take-over was cancelled (the other computer changed, or 30 min)
    "brought_in",  # a change that arrived late was brought in
    "pull_abandoned",  # an unfinished take-over was given up
]
#: The privacy-log rows sync writes (only the computer in use writes them; they travel with the data).
SyncActivityKind = Literal[
    "sync.connected",
    "sync.joined",
    "sync.taken_over",
    "sync.brought_in",
    "sync.chosen",
    "sync.kept",
    "sync.forgot",
    "sync.disconnected",
]

#: Every ``code`` a refusal of hand-off sync carries, from its routes and from the gate.
SyncErrorKind = Literal[
    "unavailable",  # 409: the demo, or no usable password store on this computer
    "not_connected",  # 409: this computer isn't syncing
    "already_connected",  # 409: this computer already syncs (disconnect first)
    "folder",  # 422: the folder can't be used (the reason says why)
    "name",  # 422: the computer's name is empty, too long or has control characters
    "passphrase",  # 422: a new folder's passphrase is too short, too long or too easy to guess
    "wrong_passphrase",  # 422: the passphrase doesn't open this folder
    "newer_ordnung",  # 409: the folder or another computer needs a newer Ordnung
    "full",  # 409: the folder already serves MAX_COMPUTERS computers
    "folder_problem",  # 409: the folder (or this computer's setup) has a problem that blocks this
    "pull_unfinished",  # 409: a take-over must finish (or be abandoned) first
    "passphrase_needed",  # 409: the passphrase isn't in the password store (type it again)
    "no_space",  # 507: this computer lacks the space for it
    "no_choice",  # 409: nothing to choose (any more), or no such side
    "not_arrived",  # 409: what this needs hasn't arrived from the sync tool yet
    "standby",  # 409: another computer is in use (the gate, for any write)
    "in_use",  # 409: that computer is the one in use
    "not_received",  # 409: no other computer has this one's latest changes yet (confirm to go on)
    "not_needed",  # 409: there's nothing to confirm, abandon or refill now
    "not_found",  # 404: no such computer or kept copy
]

ERROR_STATUS: dict[SyncErrorKind, int] = {
    "unavailable": 409,
    "not_connected": 409,
    "already_connected": 409,
    "folder": 422,
    "name": 422,
    "passphrase": 422,
    "wrong_passphrase": 422,
    "newer_ordnung": 409,
    "full": 409,
    "folder_problem": 409,
    "pull_unfinished": 409,
    "passphrase_needed": 409,
    "no_space": 507,
    "no_choice": 409,
    "not_arrived": 409,
    "standby": 409,
    "in_use": 409,
    "not_received": 409,
    "not_needed": 409,
    "not_found": 404,
}

DEMO_MESSAGE = "This is the demo, so it doesn't sync. Your own Ordnung can."
NOT_CONNECTED_MESSAGE = "This computer isn't syncing. Set it up in Settings → Your computers."
#: The gate's refusal while another computer is in use, and while data is being brought over.
STANDBY_MESSAGE = "Ordnung is in use on {name}. Use it here first (Settings → Your computers)."
BRINGING_OVER_MESSAGE = "Bringing over changes from {name} — one moment."
WRONG_PASSPHRASE_MESSAGE = "That passphrase doesn't open this folder."
NEWER_MESSAGE = "This folder was set up by a newer version of Ordnung. Update Ordnung on this computer."
NOT_ARRIVED_MESSAGE = "Not everything has arrived from your sync tool yet."


class SyncError(BackupError):
    """Hand-off sync can't do what was asked: the message is written for people, and ``kind`` is the
    API's refusal code (answered with :data:`ERROR_STATUS`'s status)."""

    def __init__(self, kind: SyncErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: SyncErrorKind = kind

    @property
    def status(self) -> int:
        return ERROR_STATUS[self.kind]

    def body(self) -> dict[str, str]:
        return {"detail": str(self), "code": self.kind}


class WrongSyncPassphrase(SyncError):
    """The passphrase doesn't open the folder's key file (refused before anything is stored)."""

    def __init__(self, message: str = WRONG_PASSPHRASE_MESSAGE) -> None:
        super().__init__("wrong_passphrase", message)


class NewerSyncFolder(SyncError):
    """The folder, a head or a version needs a newer Ordnung (format or schema)."""

    def __init__(self, message: str = NEWER_MESSAGE) -> None:
        super().__init__("newer_ordnung", message)


class NotArrived(SyncError):
    """Something a version needs is missing, short, a placeholder or unreadable: wait, never damage."""

    def __init__(self, message: str = NOT_ARRIVED_MESSAGE) -> None:
        super().__init__("not_arrived", message)


class SyncRefused(SyncError):
    """The demo never syncs: a push of a demo database, or a demo database arriving, is refused."""

    def __init__(self, message: str = DEMO_MESSAGE) -> None:
        super().__init__("unavailable", message)


# --------------------------------------------------------------------------------------------------
# the passphrase of a new folder
# --------------------------------------------------------------------------------------------------

#: A new folder's passphrase needs about this many bits by :func:`passphrase_bits` …
MIN_PASSPHRASE_BITS = 70.0
#: … and setup suggests this many random words (each counts :data:`TOKEN_BITS_MAX`).
SUGGESTED_WORDS = 5
#: The most one token (a word, a run of digits) counts: a word from a list of 16,384.
TOKEN_BITS_MAX = 14.0
LETTER_BITS = math.log2(26)
DIGIT_BITS = math.log2(10)
WEAK_PASSPHRASE_MESSAGE = (
    "This passphrase would be too easy to guess for a folder your sync provider keeps. Use five or more "
    "words that don't belong together, each of three letters or more — or take the suggested one."
)


def passphrase_tokens(passphrase: str) -> list[str]:
    """The tokens :func:`passphrase_bits` counts: the passphrase in Unicode NFC is cut into runs of
    letters and runs of digits (every other character only separates them), and a run of letters is
    cut again before an upper-case letter that follows a lower-case one ("CorrectHorse" is two)."""
    tokens: list[str] = []
    current = ""
    for char in unicodedata.normalize("NFC", passphrase):
        letter, digit = char.isalpha(), char.isdecimal()
        if not (letter or digit):
            if current:
                tokens.append(current)
            current = ""
            continue
        previous = current[-1] if current else ""
        same_kind = bool(previous) and (previous.isdecimal() == digit)
        camel = letter and char.isupper() and previous.islower()
        if same_kind and not camel:
            current += char
        else:
            if current:
                tokens.append(current)
            current = char
    if current:
        tokens.append(current)
    return tokens


def passphrase_bits(passphrase: str) -> float:
    """The estimated entropy of a passphrase, in bits — a simple estimator, no dictionary.

    Each *distinct* token (:func:`passphrase_tokens`, compared case-folded) counts its length times
    :data:`LETTER_BITS` (letters) or :data:`DIGIT_BITS` (digits), at most :data:`TOKEN_BITS_MAX`: a
    token is at best a word from a large list. So five unrelated words of three or more letters reach
    :data:`MIN_PASSPHRASE_BITS`; a repeated word, a long run of one kind or a short sentence doesn't.
    The web app counts the same way.
    """
    distinct = dict.fromkeys(token.casefold() for token in passphrase_tokens(passphrase))
    return sum(
        min(len(token) * (DIGIT_BITS if token[0].isdecimal() else LETTER_BITS), TOKEN_BITS_MAX)
        for token in distinct
    )


def passphrase_problem(passphrase: str) -> str | None:
    """Why ``passphrase`` can't protect a *new* sync folder (``None``: it can): the backup policy's
    length (12-1024 characters), then :data:`MIN_PASSPHRASE_BITS`. Joining an existing folder, or typing
    the passphrase again, checks only that it opens the folder."""
    problem = _length_problem(passphrase)
    if problem is not None:
        return problem
    if passphrase_bits(passphrase) < MIN_PASSPHRASE_BITS:
        return WEAK_PASSPHRASE_MESSAGE
    return None
