"""SQLite persistence — the only module that talks SQL (SPEC §5, contract in Appendix A).

Connections: one per thread (``threading.local``, closed when the thread ends), autocommit mode (``isolation_level=None``) with
``journal_mode=WAL``, ``busy_timeout=5000``, ``synchronous=NORMAL`` and ``foreign_keys=ON``. Reads
run directly; every write goes through :meth:`Store.tx` (``BEGIN IMMEDIATE`` … ``COMMIT``), which is
re-entrant per thread and serialised process-wide by one ``RLock`` so threads never race for the
SQLite write lock.

Rows map to the Pydantic models in :mod:`ordnung.models`: list/dict/nested-model fields are stored
as JSON text, booleans as 0/1. ``update_*`` methods take model field names with Python values
(models or plain dicts), validate the result against the model before writing, and bump
``updated_at``; unknown or read-only fields raise ``ValueError``, missing rows ``NotFoundError``.

Search keeps two FTS5 indexes per document in sync on every document write: ``documents_fts``
(word index, diacritics removed, bm25 ranking) and ``documents_trigram`` (substring index over a
lower-cased, diacritic-folded copy, so "steuerbescheid" finds "Einkommensteuerbescheid" and
"Kuendigung" finds "Kündigung").
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import re
import shutil
import sqlite3
import sys
import threading
import types
import unicodedata
import weakref
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Generic, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from ordnung.clock import now_iso, real_now_iso
from ordnung.config import Paths
from ordnung.db.migrate import current_version, latest_version, migrate, pending
from ordnung.ids import content_id, doc_id_for_sha, new_id
from ordnung.llm.base import Usage
from ordnung.models import (
    PROOF_SOURCE,
    Activity,
    AppSettings,
    CallNote,
    Case,
    ChatMessage,
    Contract,
    Direction,
    Document,
    DocumentExtraction,
    DocumentStatus,
    Draft,
    Identifier,
    Item,
    Job,
    LLMCallRecord,
    Note,
    Page,
    Party,
    Profile,
    Proof,
    PurposeUsage,
    SearchHit,
    SentSigner,
    SpanKind,
    Suggestion,
    TraceSpanRecord,
    UsageStats,
)
from ordnung.phone.actor import attribute

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)
T = TypeVar("T")
Filter = str | Iterable[str] | None  # one value or several (``IN``); ``None`` = no filter

# Serialises writers across all threads and Store instances of this process.
_WRITE_LOCK = threading.RLock()

_PRAGMAS: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA secure_delete=ON",  # deleted rows are overwritten, not left in free pages ("Delete means delete")
)
_READ_ONLY_PRAGMAS: tuple[str, ...] = ("PRAGMA busy_timeout=5000", "PRAGMA query_only=ON")
#: While hand-off sync is on, every commit is on disk before a save to the sync folder can carry it.
_DURABLE_PRAGMAS: tuple[str, ...] = (
    ("PRAGMA synchronous=FULL", "PRAGMA fullfsync=ON", "PRAGMA checkpoint_fullfsync=ON")
    if sys.platform == "darwin"  # fsync alone doesn't flush the drive's cache there
    else ("PRAGMA synchronous=FULL",)
)
_NORMAL_PRAGMAS: tuple[str, ...] = (
    ("PRAGMA synchronous=NORMAL", "PRAGMA fullfsync=OFF", "PRAGMA checkpoint_fullfsync=OFF")
    if sys.platform == "darwin"
    else ("PRAGMA synchronous=NORMAL",)
)
_READ_ONLY = frozenset({"id", "created_at", "updated_at"})
_ACTIVE_JOB_STATUSES = ("queued", "running", "waiting")
#: A job interrupted this often (the process died while reading it) is failed, not queued again.
MAX_JOB_ATTEMPTS = 3
_INTERRUPTIONS_KEY = "job_interruptions"  # meta: job id → how often the process died while reading it
INTERRUPTED_JOB_ERROR = (
    "Reading this letter stopped Ordnung several times, so it won't be tried again. "
    "If it is a genuine letter, print it to a new PDF or take photos of it and add those."
)
PRIVATE_FILE_MODE = 0o600
_CACHE_TAG_SEP = "|"  # llm_cache.doc_sha of a call carrying several documents: "doc_a|doc_b"
_PROFILE_KEY = "profile"
_SETTINGS_KEY = "settings"
#: The ``meta`` row that holds the app settings (JSON of :class:`~ordnung.models.AppSettings`).
SETTINGS_META_KEY = _SETTINGS_KEY


class NotFoundError(LookupError):
    """An update or lookup that requires an existing row found none."""


# --------------------------------------------------------------------------------------------------
# The person's writes (hand-off sync, ``ordnung.sync``)
# --------------------------------------------------------------------------------------------------

#: The ``meta`` row counting the person's own writes (``ordnung.sync.PERSON_META_KEY``; per computer,
#: never synced): bumped inside the very transaction of every write made while :data:`PERSON_WRITE` is
#: set, so a save to the sync folder that reads it from its snapshot never counts a change it lacks.
PERSON_META_KEY = "sync_person"
#: Set while the person's own write runs (hand-off sync's gate for a request, the watched folder for a
#: file it adds, the command line for ``add``/``brief``/``ask``); background work (readings, the day
#: change, calendar sync) never sets it. Only set while sync is connected, so the counter row exists
#: only then.
PERSON_WRITE: contextvars.ContextVar[bool] = contextvars.ContextVar("ordnung_person_write", default=False)


@contextmanager
def person_write(on: bool = True) -> Iterator[None]:
    """Count the writes in the block as the person's (``on``), or as background work (``False``)."""
    token = PERSON_WRITE.set(on)
    try:
        yield
    finally:
        PERSON_WRITE.reset(token)


def background_context() -> contextvars.Context:
    """A copy of the current context for a task that does background work on its own (a reading, the
    Ideas refresh): its writes are never the person's, even when a request of theirs started it."""
    context = contextvars.copy_context()
    context.run(PERSON_WRITE.set, False)
    return context


# --------------------------------------------------------------------------------------------------
# Row <-> model mapping
# --------------------------------------------------------------------------------------------------


def _is_json_type(annotation: Any) -> bool:
    """True for field types stored as JSON text: lists, tuples, dicts and nested models."""
    origin = get_origin(annotation)
    if origin in (list, tuple, dict):
        return True
    if origin in (Union, types.UnionType):
        return any(_is_json_type(arg) for arg in get_args(annotation) if arg is not type(None))
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


class _Table(Generic[M]):
    """How one table maps to its model.

    ``renames`` maps model field → column where they differ; ``extras`` are writable columns that
    are not on the model (value: the model that validates their JSON, or ``None`` for plain values);
    ``on_read`` are model fields the API works out on read — never stored, never writable (rows
    decode with their defaults).
    """

    def __init__(
        self,
        name: str,
        model: type[M],
        prefix: str | None = None,
        *,
        renames: Mapping[str, str] | None = None,
        extras: Mapping[str, type[BaseModel] | None] | None = None,
        on_read: Iterable[str] = (),
    ) -> None:
        self.name = name
        self.model = model
        self.prefix = prefix
        self.extras: dict[str, type[BaseModel] | None] = dict(extras or {})
        renamed = dict(renames or {})
        skipped = frozenset(on_read)
        self.column_of = {
            field: renamed.get(field, field) for field in model.model_fields if field not in skipped
        }
        self.field_of = {column: field for field, column in self.column_of.items()}
        self.json_columns = frozenset(
            [
                column
                for field, column in self.column_of.items()
                if _is_json_type(model.model_fields[field].annotation)
            ]
            + [column for column, extra_model in self.extras.items() if extra_model is not None]
        )
        self.insertable = frozenset(self.column_of) | frozenset(self.extras)
        self.writable = self.insertable - _READ_ONLY
        self.has_updated_at = "updated_at" in model.model_fields

    def columns(self, alias: str | None = None) -> str:
        """The model's columns for a ``SELECT`` list (optionally qualified by a table alias)."""
        prefix = f"{alias}." if alias else ""
        return ", ".join(prefix + column for column in self.column_of.values())

    def check(self, names: Iterable[str], allowed: frozenset[str]) -> None:
        """Raise ``ValueError`` for field names that are not in ``allowed``."""
        unknown = sorted(set(names) - allowed)
        if unknown:
            raise ValueError(f"unknown or read-only {self.name} field(s): {', '.join(unknown)}")

    def decode(self, row: sqlite3.Row | Mapping[str, Any]) -> M:
        """Row (or column → value mapping) → model (JSON columns parsed, columns renamed to fields)."""
        data: dict[str, Any] = {}
        for column in row.keys():  # noqa: SIM118 - sqlite3.Row is not iterable by key
            value = row[column]
            if column in self.json_columns and isinstance(value, str):
                value = json.loads(value)
            data[self.field_of[column]] = value
        return self.model.model_validate(data)

    def encode(self, column: str, value: Any) -> Any:
        """Python value → SQL value (JSON text for JSON columns)."""
        if value is None or column not in self.json_columns:
            return value
        return json.dumps(to_jsonable_python(value), ensure_ascii=False)

    def validate_extra(self, column: str, value: Any) -> Any:
        """Validate a non-model column value with its model, if it has one."""
        extra_model = self.extras[column]
        if value is None or extra_model is None:
            return value
        return extra_model.model_validate(value)

    def row(self, model: M) -> dict[str, Any]:
        """Column → SQL value for every model field."""
        return {
            self.column_of[field]: self.encode(self.column_of[field], value)
            for field, value in model.model_dump().items()
            if field in self.column_of
        }


_PARTIES = _Table("parties", Party, "pty")
_CASES = _Table("cases", Case, "cas")
_DOCUMENTS = _Table(
    "documents",
    Document,
    "doc",
    renames={"references": "refs"},
    extras={"file_path": None, "text": None, "extraction": DocumentExtraction},
)
_PAGES = _Table("pages", Page)
_CONTRACTS = _Table("contracts", Contract, "ctr", on_read=("cancellable", "cancel_hint", "cancellation_sent"))
_ITEMS = _Table("items", Item, "itm")
_SUGGESTIONS = _Table("suggestions", Suggestion, "sug")
_DRAFTS = _Table("drafts", Draft, "drf", extras={"sent_profile": SentSigner})
_NOTES = _Table("notes", Note, "nte")
_PROOFS = _Table("proofs", Proof, "prf")
_CALL_NOTES = _Table("call_notes", CallNote, "cal")
_CHAT = _Table("chat_messages", ChatMessage, "msg")
_JOBS = _Table("jobs", Job, "job")
_ACTIVITY = _Table("activity", Activity)
_LLM_CALLS = _Table("llm_calls", LLMCallRecord)
_TRACE_SPANS = _Table("trace_spans", TraceSpanRecord)

_INDEXED_DOCUMENT_FIELDS = frozenset({"title", "filename", "summary", "explanation", "party_id"})
_INDEXED_PARTY_FIELDS = frozenset({"name", "aliases"})
_SUGGESTION_TEXT_FIELDS = (
    "title",
    "body",
    "rationale",
    "priority",
    "refs",
    "action",
    "savings_estimate",
    "due_date",
)


class _Where:
    """Accumulates ``AND``-ed SQL conditions and their parameters."""

    def __init__(self) -> None:
        self.clauses: list[str] = []
        self.params: list[Any] = []

    def add(self, clause: str, *params: Any) -> None:
        self.clauses.append(clause)
        self.params.extend(params)

    def equals(self, column: str, value: Any) -> None:
        if value is not None:
            self.add(f"{column} = ?", value)

    def within(self, column: str, values: Filter) -> None:
        if values is None:
            return
        wanted = [values] if isinstance(values, str) else list(values)
        if not wanted:
            self.clauses.append("0")  # an empty choice matches nothing
            return
        self.add(f"{column} IN ({', '.join('?' * len(wanted))})", *wanted)

    def sql(self) -> str:
        return "WHERE " + " AND ".join(self.clauses) if self.clauses else ""


def _priority_rank(column: str) -> str:
    return (
        f"CASE {column} WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 "
        f"WHEN 'low' THEN 3 ELSE 4 END"
    )


def _paging(limit: int | None, offset: int = 0) -> tuple[str, list[int]]:
    if limit is None and not offset:
        return "", []
    return " LIMIT ? OFFSET ?", [-1 if limit is None else limit, offset]


def _iso_day(value: str | date | None) -> str | None:
    return value.isoformat() if isinstance(value, date) else value


def _field_values(fields: Mapping[str, Any], skip: Iterable[str]) -> dict[str, Any]:
    """Model field values of ``fields`` (minus ``skip``); dates/datetimes become ISO strings."""
    skipped = set(skip)
    values: dict[str, Any] = {}
    for name, value in fields.items():
        if name in skipped:
            continue
        if isinstance(value, datetime):
            value = _utc_timestamp(value)
        elif isinstance(value, date):
            value = value.isoformat()
        values[name] = value
    return values


def _utc_timestamp(value: str | datetime) -> str:
    """Normalise a timestamp to the ``YYYY-MM-DDTHH:MM:SSZ`` form used by every column."""
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------------------------------
# Text normalisation (matching and search)
# --------------------------------------------------------------------------------------------------

_IDENTIFIER_NOISE_RE = re.compile(r"[\s/.\-‐‑‒–—]+")
_GERMAN_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"})
_FTS_SYNTAX_RE = re.compile(r'["*^():{}\[\]+]')
_FTS_OPERATORS = frozenset({"AND", "OR", "NOT", "NEAR"})
_TOKEN_EDGES = ".,;:!?'`´‘’‚“”„«»‹›<>|/\\-"
_TRIGRAM_MIN = 3
_SNIPPET_RADIUS = 60


def normalize_identifier(value: str) -> str:
    """Canonical form of a reference/customer number: no spaces, slashes, dots or dashes; casefolded.

    ``"123/456/78901"``, ``"123 456 78901"`` and ``"123-456.78901"`` all become ``"12345678901"``.
    """
    return _IDENTIFIER_NOISE_RE.sub("", value).casefold()


def _name_key(name: str) -> str:
    return " ".join(unicodedata.normalize("NFC", name).casefold().split())


def _fold(text: str, *, transliterate: bool = False) -> str:
    """Lower-case and strip diacritics (``Kündigung`` → ``kundigung``, ``ß`` → ``ss``).

    ``transliterate`` first spells umlauts with two letters (``Kündigung`` → ``kuendigung``).
    """
    low = unicodedata.normalize("NFC", text).lower().replace("ß", "ss")
    if transliterate:
        low = low.translate(_GERMAN_TRANSLIT)
    if low.isascii():
        return low
    return "".join(ch for ch in unicodedata.normalize("NFKD", low) if not unicodedata.combining(ch))


def _variants(token: str) -> list[str]:
    """The folded spellings of a query token that the trigram index is searched for."""
    return list(dict.fromkeys([_fold(token), _fold(token, transliterate=True)]))


def search_tokens(query: str) -> list[str]:
    """Split a user query into plain search terms.

    FTS5 syntax characters are dropped and bare ``AND``/``OR``/``NOT``/``NEAR`` operators ignored,
    so any input (``"foo AND ( bar``, ``Kündigung zum 31.12.``) becomes a safe list of terms.
    """
    tokens: list[str] = []
    for raw in _FTS_SYNTAX_RE.sub(" ", query).split():
        token = raw.strip(_TOKEN_EDGES)
        if raw in _FTS_OPERATORS or not any(ch.isalnum() for ch in token):
            continue
        tokens.append(token)
    return list(dict.fromkeys(tokens))


def _fts_expression(tokens: Sequence[str]) -> str | None:
    """All terms must occur (each quoted, so it is a literal phrase and never syntax)."""
    return " ".join(f'"{token}"' for token in tokens) or None


def _trigram_expression(tokens: Sequence[str]) -> str | None:
    """Every term of ≥ 3 characters must occur as a substring in one of its folded spellings."""
    clauses = []
    for token in tokens:
        spellings = [v for v in _variants(token) if len(v) >= _TRIGRAM_MIN]
        if spellings:
            clauses.append("(" + " OR ".join(f'"{v}"' for v in spellings) + ")")
    return " AND ".join(clauses) or None


def _fold_with_offsets(text: str, transliterate: bool) -> tuple[str, list[int]]:
    """Folded text plus, for every folded character, the index of its source character."""
    pieces: list[str] = []
    offsets: list[int] = []
    for index, char in enumerate(text):
        piece = _fold(char, transliterate=transliterate)
        pieces.append(piece)
        offsets.extend([index] * len(piece))
    return "".join(pieces), offsets


def _window(text: str, start: int, end: int) -> str:
    low = max(0, start - _SNIPPET_RADIUS)
    high = min(len(text), end + _SNIPPET_RADIUS)
    body = " ".join(text[low:high].split())
    return ("…" if low > 0 else "") + body + ("…" if high < len(text) else "")


def _snippet_for(parts: Sequence[str], needles: Sequence[str]) -> str:
    """A short window of text around the first occurrence of any needle (folded comparison)."""
    for part in parts:
        for transliterate in (False, True):
            folded, offsets = _fold_with_offsets(part, transliterate)
            found = [(pos, len(n)) for n in needles if (pos := folded.find(n)) >= 0]
            if found:
                pos, length = min(found)
                return _window(part, offsets[pos], offsets[pos + length - 1] + 1)
    first = next((part for part in parts if part.strip()), "")
    return _window(first, 0, 0)


@dataclass(frozen=True)
class _IndexedText:
    """The searchable text of one document, in the columns of ``documents_fts``."""

    title: str
    summary: str
    explanation: str
    pages: list[str]
    parties: str

    @property
    def text(self) -> str:
        return "\n\n".join(page for page in self.pages if page)

    def parts(self) -> list[str]:
        return [self.title, self.summary, self.explanation, *self.pages, self.parties]

    def trigram_body(self) -> str:
        combined = "\n".join(part for part in self.parts() if part)
        plain, spelled = _fold(combined), _fold(combined, transliterate=True)
        return plain if spelled == plain else plain + "\n" + spelled


# --------------------------------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------------------------------


class _ThreadState(threading.local):
    def __init__(self) -> None:
        self.conn: sqlite3.Connection | None = None
        #: the :attr:`Store.durable` setting this thread's connection was last given
        self.durable: bool | None = None
        self.depth = 0
        self.after_commit: list[Callable[[], None]] = []
        # Held only here: dropped with the thread's state when the thread ends, which closes ``conn``.
        self.closer: _ConnectionToken | None = None


class _ConnectionToken:
    """Lives as long as a thread's state in a store; its finalizer closes that thread's connection."""

    __slots__ = ("__weakref__",)


def _close_ended_thread_connection(store_ref: weakref.ref[Store], conn: sqlite3.Connection, pid: int) -> None:
    """Close the connection of a thread that ended and forget it (no-op once the store is closed).

    Threads come and go — anyio's worker threads (the web API's sync routes, an MCP server's sync
    tools) end after ten idle seconds or with their event loop — and each opened a connection that
    :meth:`Store.close` alone would close, so a long-running process kept two file descriptors per
    ended thread (Ask's replays, one event loop per tool call, ran out of them).

    Never in a forked child (``pid`` is the process that opened ``conn``): a fork that runs Python
    before its exec (uvloop's, starting ``claude``) drops the parent's other threads there, and
    closing their connections could wait forever on a SQLite mutex another thread held at the fork —
    and the parent, waiting for the exec, with it."""
    if os.getpid() != pid:
        return
    store = store_ref()
    if store is not None:
        with store._connections_lock, contextlib.suppress(ValueError):
            store._connections.remove(conn)
    conn.close()


class Store:
    """All reads and writes of one Ordnung database. Safe to share between threads."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        data_dir: str | Path | None = None,
        read_only: bool = False,
        durable: bool = False,
    ) -> None:
        """Open (creating and migrating if needed) the database at ``db_path``.

        ``data_dir`` is where originals and ``derived/`` live (default: the database's folder); it
        is used to resolve relative file paths and to purge files in :meth:`delete_document`.
        ``read_only`` opens an existing, up-to-date database with ``mode=ro`` and
        ``PRAGMA query_only=ON`` (the MCP server's view); every write then raises ``PermissionError``.
        ``durable`` (hand-off sync is on) commits with ``synchronous=FULL`` (:meth:`set_durable`).
        """
        self.db_path = Path(db_path)
        self.paths = Paths(Path(data_dir) if data_dir is not None else self.db_path.parent)
        self.read_only = read_only
        self.durable = durable and not read_only
        self._local = _ThreadState()
        self._connections: list[sqlite3.Connection] = []
        # re-entrant: a thread's state may be dropped (closing its connection) wherever it is freed
        self._connections_lock = threading.RLock()
        self._closed = False
        try:
            self.schema_version = self._check_schema() if read_only else self._migrate()
        except BaseException:
            self.close()
            raise

    @classmethod
    def open(cls, paths: Paths, *, read_only: bool = False, durable: bool = False) -> Store:
        """Open the database of a data directory (creating the directory layout unless read-only)."""
        if not read_only:
            paths.ensure()
        return cls(paths.db, data_dir=paths.data_dir, read_only=read_only, durable=durable)

    def set_durable(self, durable: bool) -> None:
        """Commit with ``synchronous=FULL`` from now on (hand-off sync connected) or ``NORMAL`` again:
        every thread's connection takes it at its next write transaction."""
        if not self.read_only:
            self.durable = durable

    def _migrate(self) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._make_private()
        with _WRITE_LOCK:
            return migrate(self._conn())

    def _make_private(self) -> None:
        """Create the database file readable by its owner only (SQLite gives its WAL and shared-memory
        files the same mode) and tighten the modes of existing files."""
        if not self.db_path.exists():
            os.close(os.open(self.db_path, os.O_WRONLY | os.O_CREAT, PRIVATE_FILE_MODE))
        if os.name != "posix":
            return
        for path in (
            self.db_path,
            *(self.db_path.with_name(self.db_path.name + s) for s in ("-wal", "-shm")),
        ):
            with contextlib.suppress(OSError):
                if path.exists():
                    path.chmod(PRIVATE_FILE_MODE)

    def _check_schema(self) -> int:
        conn = self._conn()
        version = current_version(conn)
        latest = latest_version()
        if version != latest or pending(conn):
            raise RuntimeError(
                f"database schema is at version {version}, expected {latest}; open it writable first"
            )
        return version

    @property
    def data_dir(self) -> Path:
        """The data directory (originals, ``derived/``, drafts)."""
        return self.paths.data_dir

    def close(self) -> None:
        """Close every connection this store opened (in any thread). The store is unusable after."""
        with self._connections_lock:
            self._closed = True
            connections, self._connections = self._connections, []
        for conn in connections:
            conn.close()

    def wipe(self) -> None:
        """Start over with an empty database ("Delete everything").

        Every table is dropped and the schema created afresh; ``VACUUM`` then rewrites the file and
        the WAL is truncated, so no deleted data stays behind on disk. Runs under the process-wide
        write lock; connections of other threads stay usable (they see the empty database).
        """
        if self.read_only:
            raise PermissionError(f"{self.db_path} is opened read-only")
        with _WRITE_LOCK:
            conn = self._conn()
            rows = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            virtual = [row["name"] for row in rows if (row["sql"] or "").upper().startswith("CREATE VIRTUAL")]
            # virtual tables first: dropping one also drops its shadow tables
            names = [*virtual, *(row["name"] for row in rows if row["name"] not in virtual)]
            conn.execute("PRAGMA foreign_keys=OFF")
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for name in names:
                        conn.execute(f'DROP TABLE IF EXISTS "{name}"')
                    conn.execute("PRAGMA user_version = 0")
                    conn.execute("COMMIT")
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
            finally:
                conn.execute("PRAGMA foreign_keys=ON")
            self.schema_version = migrate(conn)
            conn.execute("VACUUM")
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------------------------------------
    # connections & transactions
    # ---------------------------------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("store is closed")
        conn = self._local.conn
        if conn is not None:
            return conn
        if self.read_only:
            target, pragmas = f"{self.db_path.resolve().as_uri()}?mode=ro", _READ_ONLY_PRAGMAS
        else:
            target, pragmas = str(self.db_path), _PRAGMAS
        conn = sqlite3.connect(
            target, uri=self.read_only, isolation_level=None, check_same_thread=False, timeout=5.0
        )
        conn.row_factory = sqlite3.Row
        for pragma in pragmas:
            conn.execute(pragma)
        if not self.read_only:
            for pragma in _DURABLE_PRAGMAS if self.durable else ():
                conn.execute(pragma)
            self._local.durable = self.durable
        with self._connections_lock:
            if self._closed:
                conn.close()
                raise RuntimeError("store is closed")
            self._connections.append(conn)
        self._local.conn = conn
        closer = self._local.closer = _ConnectionToken()
        ended = weakref.finalize(closer, _close_ended_thread_connection, weakref.ref(self), conn, os.getpid())
        # not at exit: a daemon thread may still be using its connection then
        ended.atexit = False  # type: ignore[misc, unused-ignore]  # older typeshed declares no atexit
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """One write transaction: ``BEGIN IMMEDIATE`` … ``COMMIT`` (``ROLLBACK`` on exception).

        Re-entrant per thread: a nested ``tx()`` joins the outer transaction through a savepoint,
        so an exception inside it undoes only its own writes (and still propagates). Writers are
        serialised by a process-wide lock.
        """
        if self.read_only:
            raise PermissionError(f"{self.db_path} is opened read-only")
        state = self._local
        conn = self._conn()
        if state.depth:
            with self._savepoint(conn, state):
                yield conn
        else:
            if state.durable is not self.durable:  # outside a transaction: synchronous can change
                for pragma in _DURABLE_PRAGMAS if self.durable else _NORMAL_PRAGMAS:
                    conn.execute(pragma)
                state.durable = self.durable
            with self._transaction(conn, state):
                yield conn

    @contextmanager
    def _transaction(self, conn: sqlite3.Connection, state: _ThreadState) -> Iterator[None]:
        with _WRITE_LOCK:
            conn.execute("BEGIN IMMEDIATE")
            state.depth = 1
            changes = conn.total_changes
            try:
                yield
                if PERSON_WRITE.get() and conn.total_changes != changes:
                    # the person's write: counted in its own transaction (hand-off sync, see PERSON_WRITE)
                    conn.execute(
                        "INSERT INTO meta (key, value) VALUES (?, '1') ON CONFLICT(key) DO UPDATE "
                        "SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)",
                        (PERSON_META_KEY,),
                    )
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                state.after_commit.clear()
                raise
            finally:
                state.depth = 0
        callbacks, state.after_commit = state.after_commit, []
        for callback in callbacks:
            callback()

    @contextmanager
    def _savepoint(self, conn: sqlite3.Connection, state: _ThreadState) -> Iterator[None]:
        name = f"ordnung_sp{state.depth}"
        pending = len(state.after_commit)
        conn.execute(f"SAVEPOINT {name}")
        state.depth += 1
        try:
            yield
        except BaseException:
            if conn.in_transaction:
                conn.execute(f"ROLLBACK TO {name}")
                conn.execute(f"RELEASE {name}")
            del state.after_commit[pending:]
            raise
        else:
            conn.execute(f"RELEASE {name}")
        finally:
            state.depth -= 1

    @contextmanager
    def snapshot(self) -> Iterator[None]:
        """Reads in the block see one state of the database: a read transaction (``BEGIN`` … end),
        so a write another thread commits meanwhile is not half seen. Inside a :meth:`tx` or another
        snapshot it joins that transaction. Only for reads: a :meth:`tx` inside it raises."""
        conn = self._conn()
        if conn.in_transaction:
            yield
            return
        conn.execute("BEGIN")
        try:
            yield
        finally:
            if conn.in_transaction:
                conn.execute("ROLLBACK")

    def change_token(self) -> tuple[int, int, int] | None:
        """A value that changes whenever this thread may read something else than before: another
        connection committed (``PRAGMA data_version``), this one wrote (``total_changes``) or the schema
        changed ("Delete everything"). Only values taken in the same thread compare; ``None`` inside a
        transaction, whose reads may not be committed."""
        conn = self._conn()
        if conn.in_transaction:
            return None
        data = conn.execute("PRAGMA data_version").fetchone()[0]
        schema = conn.execute("PRAGMA schema_version").fetchone()[0]
        return int(data), conn.total_changes, int(schema)

    def _after_commit(self, callback: Callable[[], None]) -> None:
        """Inside :meth:`tx`: run ``callback`` once the outermost transaction commits (never on rollback)."""
        self._local.after_commit.append(callback)

    # ---------------------------------------------------------------------------------------------
    # generic row helpers
    # ---------------------------------------------------------------------------------------------

    def _one(self, spec: _Table[M], where: str, params: Sequence[Any] = ()) -> M | None:
        sql = f"SELECT {spec.columns()} FROM {spec.name} WHERE {where}"
        row = self._conn().execute(sql, params).fetchone()
        return None if row is None else spec.decode(row)

    def _many(self, spec: _Table[M], tail: str = "", params: Sequence[Any] = ()) -> list[M]:
        rows = self._conn().execute(f"SELECT {spec.columns()} FROM {spec.name} {tail}", params).fetchall()
        return [spec.decode(row) for row in rows]

    def _require(self, spec: _Table[M], id: str) -> M:
        found = self._one(spec, "id = ?", (id,))
        if found is None:
            raise NotFoundError(f"{spec.name}: no row with id {id!r}")
        return found

    def _insert(self, spec: _Table[M], fields: Mapping[str, Any]) -> M:
        spec.check(fields, spec.insertable)
        values = _field_values(fields, skip=spec.extras)
        now = now_iso()
        for stamp in ("created_at", "updated_at"):
            if stamp in spec.model.model_fields and values.get(stamp) is None:
                values[stamp] = now
        if spec.prefix is not None and values.get("id") is None:
            values["id"] = new_id(spec.prefix)
        model = spec.model.model_validate(values)
        row = spec.row(model)
        for column in spec.extras.keys() & fields.keys():
            row[column] = spec.encode(column, spec.validate_extra(column, fields[column]))
        sql = f"INSERT INTO {spec.name} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})"
        with self.tx() as conn:
            conn.execute(sql, list(row.values()))
        return model

    def _update(self, spec: _Table[M], id: str, fields: Mapping[str, Any]) -> M:
        """Validate ``current + fields`` against the model and write the changed columns.

        A no-op update (nothing differs) writes nothing and keeps ``updated_at``.
        """
        spec.check(fields, spec.writable)
        with self.tx() as conn:
            current = self._require(spec, id)
            changes = _field_values(fields, skip=spec.extras)
            updated = spec.model.model_validate(current.model_dump() | changes)
            old_row, new_row = spec.row(current), spec.row(updated)
            columns = {
                column: new_row[column]
                for column in (spec.column_of[name] for name in changes)
                if new_row[column] != old_row[column]
            }
            for column in spec.extras.keys() & fields.keys():
                columns[column] = spec.encode(column, spec.validate_extra(column, fields[column]))
            if not columns:
                return current
            if spec.has_updated_at:
                columns["updated_at"] = now_iso()
                updated = updated.model_copy(update={"updated_at": columns["updated_at"]})
            assignments = ", ".join(f"{column} = ?" for column in columns)
            conn.execute(f"UPDATE {spec.name} SET {assignments} WHERE id = ?", [*columns.values(), id])
        return updated

    def _delete(self, spec: _Table[Any], id: str) -> bool:
        with self.tx() as conn:
            return conn.execute(f"DELETE FROM {spec.name} WHERE id = ?", (id,)).rowcount > 0

    # ---------------------------------------------------------------------------------------------
    # meta / profile / settings
    # ---------------------------------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        """Value stored under ``key`` in ``meta`` (``None`` if absent)."""
        row = self._conn().execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def set_meta(self, key: str, value: str | None) -> None:
        """Store ``value`` under ``key``; ``None`` removes the key."""
        with self.tx() as conn:
            if value is None:
                conn.execute("DELETE FROM meta WHERE key = ?", (key,))
            else:
                conn.execute(
                    "INSERT INTO meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )

    def get_profile(self) -> Profile:
        """The person's profile (defaults until one is saved)."""
        raw = self.get_meta(_PROFILE_KEY)
        return Profile() if raw is None else Profile.model_validate_json(raw)

    def save_profile(self, profile: Profile | Mapping[str, Any]) -> Profile:
        """Validate and store the profile; returns the stored model."""
        validated = Profile.model_validate(profile)
        self.set_meta(_PROFILE_KEY, validated.model_dump_json())
        return validated

    def get_settings(self) -> AppSettings:
        """App settings (defaults until saved)."""
        raw = self.get_meta(_SETTINGS_KEY)
        return AppSettings() if raw is None else AppSettings.model_validate_json(raw)

    def save_settings(self, settings: AppSettings | Mapping[str, Any]) -> AppSettings:
        """Validate and store the app settings; returns the stored model."""
        validated = AppSettings.model_validate(settings)
        self.set_meta(_SETTINGS_KEY, validated.model_dump_json())
        return validated

    # ---------------------------------------------------------------------------------------------
    # documents
    # ---------------------------------------------------------------------------------------------

    def add_document(
        self,
        *,
        sha256: str,
        filename: str,
        mime: str,
        file_path: str | Path,
        id: str | None = None,
        pages: int = 1,
        source: str = "upload",
        direction: Direction = "incoming",
        received_date: str | None = None,
        status: DocumentStatus = "queued",
        ai_private: bool = False,
    ) -> Document:
        """Insert a document. The id defaults to :func:`ordnung.ids.doc_id_for_sha` of ``sha256``.

        ``file_path`` is the original's location, absolute or relative to the data directory.
        """
        with self.tx():
            document = self._insert(
                _DOCUMENTS,
                {
                    "id": id or doc_id_for_sha(sha256),
                    "sha256": sha256,
                    "filename": filename,
                    "mime": mime,
                    "file_path": str(file_path),
                    "pages": pages,
                    "source": source,
                    "direction": direction,
                    "received_date": received_date,
                    "status": status,
                    "ai_private": ai_private,
                },
            )
            self.reindex_document(document.id)
        return document

    def get_document(self, id: str) -> Document | None:
        """A document by id (trashed documents included)."""
        return self._one(_DOCUMENTS, "id = ?", (id,))

    def get_document_by_sha(self, sha256: str) -> Document | None:
        """The document whose original has this SHA-256 (duplicate check at intake)."""
        return self._one(_DOCUMENTS, "sha256 = ?", (sha256,))

    def get_document_file(self, id: str) -> Path | None:
        """Absolute path of the document's original file (``None`` for an unknown document)."""
        row = self._conn().execute("SELECT file_path FROM documents WHERE id = ?", (id,)).fetchone()
        return None if row is None else self._data_path(row["file_path"])

    def update_document(self, id: str, **fields: Any) -> Document:
        """Update document fields (model names, plus ``file_path``, ``text`` and ``extraction``)."""
        with self.tx():
            document = self._update(_DOCUMENTS, id, fields)
            if _INDEXED_DOCUMENT_FIELDS & fields.keys():
                self.reindex_document(id)
        return document

    def list_documents(
        self,
        q: str | None = None,
        kind: Filter = None,
        party_id: str | None = None,
        case_id: str | None = None,
        status: Filter = None,
        direction: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        *,
        ai_private: bool | None = None,
        include_deleted: bool = False,
        source: str | None = None,
        exclude_source: str | None = None,
    ) -> list[Document]:
        """Documents, newest first by ``COALESCE(doc_date, created_at)``.

        ``q`` filters by the same full-text/substring matching as :meth:`search`. Trashed documents
        are left out unless ``include_deleted``. ``source`` keeps the documents of one source
        (``upload``, ``folder``, ``email:<id>`` …); ``exclude_source`` leaves out one source (the
        Inbox leaves out proof files).
        """
        where = _Where()
        if exclude_source is not None:
            where.add("source != ?", exclude_source)
        where.within("kind", kind)
        where.equals("party_id", party_id)
        where.equals("case_id", case_id)
        where.within("status", status)
        where.equals("direction", direction)
        where.equals("source", source)
        if ai_private is not None:
            where.add("ai_private = ?", int(ai_private))
        if not include_deleted:
            where.add("deleted_at IS NULL")
        if q is not None and q.strip() and not self._add_text_filter(where, q):
            return []
        paging, paging_params = _paging(limit, offset)
        tail = f"{where.sql()} ORDER BY COALESCE(doc_date, created_at) DESC, created_at DESC, id{paging}"
        return self._many(_DOCUMENTS, tail, [*where.params, *paging_params])

    def _add_text_filter(self, where: _Where, q: str) -> bool:
        tokens = search_tokens(q)
        fts, trigram = _fts_expression(tokens), _trigram_expression(tokens)
        subqueries: list[str] = []
        params: list[str] = []
        if fts:
            subqueries.append("id IN (SELECT doc_id FROM documents_fts WHERE documents_fts MATCH ?)")
            params.append(fts)
        if trigram:
            subqueries.append("id IN (SELECT doc_id FROM documents_trigram WHERE documents_trigram MATCH ?)")
            params.append(trigram)
        if not subqueries:
            return False
        where.add("(" + " OR ".join(subqueries) + ")", *params)
        return True

    def trash_document(self, id: str) -> Document:
        """Move a document to the trash (hidden from lists, search and to-dos; restorable)."""
        return self._update(_DOCUMENTS, id, {"deleted_at": now_iso()})

    def restore_document(self, id: str) -> Document:
        """Take a document out of the trash."""
        return self._update(_DOCUMENTS, id, {"deleted_at": None})

    def delete_document(self, id: str, purge_files: bool = True) -> bool:
        """Delete a document for good; returns ``False`` if it did not exist.

        In one transaction: its items, pages, jobs and search rows (the indexes are then optimised so
        none of its terms stays in them), ``llm_cache`` rows of calls that carried it (alone or with
        other documents), the Ideas and activity entries about it or its items, its quotes in the
        evidence of kept contracts, the traces of its readings, its id and its calls' replay keys,
        spans and jobs in the usage log, and the document row (contracts and drafts keep existing,
        unlinked). Deleted rows are overwritten (``secure_delete``). After the
        commit the WAL is truncated and, with ``purge_files``, the original file and
        ``derived/<id>/`` are removed. Files outside the data directory are never touched.
        """
        with self.tx() as conn:
            row = conn.execute("SELECT sha256, file_path FROM documents WHERE id = ?", (id,)).fetchone()
            if row is None:
                return False
            item_ids = [item["id"] for item in conn.execute("SELECT id FROM items WHERE doc_id = ?", (id,))]
            self._forget_document(conn, id, item_ids)
            for table in ("items", "pages", "jobs", "documents_fts", "documents_trigram"):
                conn.execute(f"DELETE FROM {table} WHERE doc_id = ?", (id,))
            for index in ("documents_fts", "documents_trigram"):
                conn.execute(f"INSERT INTO {index}({index}) VALUES ('optimize')")
            conn.execute(
                "DELETE FROM llm_cache WHERE doc_sha IN (?, ?) OR instr(? || doc_sha || ?, ?) > 0",
                (id, row["sha256"], _CACHE_TAG_SEP, _CACHE_TAG_SEP, f"{_CACHE_TAG_SEP}{id}{_CACHE_TAG_SEP}"),
            )
            conn.execute("DELETE FROM documents WHERE id = ?", (id,))
            self._after_commit(self._truncate_wal)
            if purge_files:
                original = self._data_path(row["file_path"])
                self._after_commit(lambda: self._purge_files(id, original))
        return True

    def _forget_document(self, conn: sqlite3.Connection, doc_id: str, item_ids: list[str]) -> None:
        """Remove what other records still hold of a document that is being deleted."""
        refs = {doc_id, *item_ids}
        conn.execute(
            "DELETE FROM activity WHERE (ref_type IN ('document', 'item') AND ref_id IN "
            f"({', '.join('?' * len(refs))})) OR json_extract(data, '$.doc_id') = ?",
            [*refs, doc_id],
        )
        for idea in self._many(_SUGGESTIONS):
            action = idea.action.target_id if idea.action else None
            if action in refs or any(ref.id in refs for ref in idea.refs):
                conn.execute("DELETE FROM suggestions WHERE id = ?", (idea.id,))
        for contract in self._many(_CONTRACTS):
            kept = [evidence for evidence in contract.evidence if evidence.doc_id != doc_id]
            if len(kept) != len(contract.evidence):
                self._update(_CONTRACTS, contract.id, {"evidence": kept})
        quoted = f'%"{doc_id}"%'
        for call in conn.execute(
            "SELECT id, doc_ids FROM llm_calls WHERE doc_ids LIKE ?", (quoted,)
        ).fetchall():
            others = [value for value in json.loads(call["doc_ids"]) if value != doc_id]
            # the replay key hashes the letter's content, the span and job point at its trace and an error
            # may quote Claude's answer: only the anonymous numbers stay (purpose, prompt, model, tokens,
            # cost, outcome)
            conn.execute(
                "UPDATE llm_calls SET doc_ids = ?, request_key = NULL, span_id = NULL, job_id = NULL, "
                "error = NULL WHERE id = ?",
                (json.dumps(others), call["id"]),
            )
        conn.execute("DELETE FROM trace_spans WHERE doc_id = ?", (doc_id,))

    def given_to_model(self, doc_id: str) -> bool:
        """Whether a model ever had the document: it was read, or a model call carried it — a logged
        call (a failed one too — the file may have reached the model before the call failed; never one
        whose CLI didn't start, :mod:`ordnung.llm.runtime`), a cached answer tagged with it, or a page a
        model transcribed. Used before telling the person a file was never read."""
        conn = self._conn()
        row = conn.execute("SELECT sha256, ai_processed_at FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if row is not None and row["ai_processed_at"] is not None:
            return True
        sha = row["sha256"] if row is not None else doc_id
        called = conn.execute(
            "SELECT 1 FROM llm_calls WHERE doc_ids LIKE ? LIMIT 1", (f'%"{doc_id}"%',)
        ).fetchone()
        cached = conn.execute(  # tagged as in delete_document: the id, the file's hash, or "doc_a|doc_b"
            "SELECT 1 FROM llm_cache WHERE doc_sha IN (?, ?) OR instr(? || doc_sha || ?, ?) > 0 LIMIT 1",
            (doc_id, sha, _CACHE_TAG_SEP, _CACHE_TAG_SEP, f"{_CACHE_TAG_SEP}{doc_id}{_CACHE_TAG_SEP}"),
        ).fetchone()
        transcribed = conn.execute(
            "SELECT 1 FROM pages WHERE doc_id = ? AND text_source = 'transcript' LIMIT 1", (doc_id,)
        ).fetchone()
        return any(row is not None for row in (called, cached, transcribed))

    def _truncate_wal(self) -> None:
        """Checkpoint and empty the write-ahead log, so deleted pages don't linger in it."""
        with contextlib.suppress(sqlite3.Error):
            self._conn().execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def _data_path(self, stored: str) -> Path:
        path = Path(stored)
        return path if path.is_absolute() else self.data_dir / path

    def discard_upload(self, sha256: str, doc_id: str, original: Path) -> bool:
        """Remove what an upload left when its document was never stored (it was refused while its pages
        were rendered …): the original and ``derived/<doc_id>`` — unless a document has this file (it was
        there before, or added meanwhile); ``True`` when they were removed."""
        if self.get_document_by_sha(sha256) is not None:
            return False
        self._purge_files(doc_id, original)
        return True

    def _purge_files(self, doc_id: str, original: Path) -> None:
        data_dir = self.data_dir.resolve()
        database = self.db_path.resolve()
        protected = {
            database,
            database.with_name(database.name + "-wal"),
            database.with_name(database.name + "-shm"),
        }
        derived_root = self.paths.derived.resolve()
        derived = (derived_root / doc_id).resolve()
        try:
            target = original.resolve()
            if target.is_file() and target.is_relative_to(data_dir) and target not in protected:
                target.unlink()
            if derived.parent == derived_root and derived.is_dir():
                shutil.rmtree(derived)
        except OSError:
            log.warning("could not remove the files of deleted document %s", doc_id, exc_info=True)

    # ---------------------------------------------------------------------------------------------
    # pages & text
    # ---------------------------------------------------------------------------------------------

    def set_pages(self, doc_id: str, pages: Sequence[Mapping[str, Any] | Page]) -> list[Page]:
        """Replace all pages of a document.

        Each page needs ``page``, ``width``, ``height``, ``image_path``; optional ``text``,
        ``text_source``, ``words`` (``[text, x0, y0, x1, y1]`` relative) and ``hidden``.
        """
        records = sorted((self._page_record(doc_id, page) for page in pages), key=lambda p: p.page)
        numbers = [record.page for record in records]
        if len(set(numbers)) != len(numbers):
            raise ValueError(f"duplicate page numbers for {doc_id}: {numbers}")
        with self.tx() as conn:
            self._require(_DOCUMENTS, doc_id)
            conn.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
            for record in records:
                row = _PAGES.row(record)
                conn.execute(
                    f"INSERT INTO pages ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                    list(row.values()),
                )
            self.reindex_document(doc_id)
        return records

    @staticmethod
    def _page_record(doc_id: str, page: Mapping[str, Any] | Page) -> Page:
        data = page.model_dump() if isinstance(page, Page) else dict(page)
        _PAGES.check(data, _PAGES.insertable)
        if data.setdefault("doc_id", doc_id) != doc_id:
            raise ValueError(f"page belongs to {data['doc_id']!r}, not {doc_id!r}")
        return Page.model_validate(data)

    def list_pages(self, doc_id: str) -> list[Page]:
        """All pages of a document in page order."""
        return self._many(_PAGES, "WHERE doc_id = ? ORDER BY page", (doc_id,))

    def get_page(self, doc_id: str, page: int) -> Page | None:
        """One page of a document (``None`` if it does not exist)."""
        return self._one(_PAGES, "doc_id = ? AND page = ?", (doc_id, page))

    def set_page_text(self, doc_id: str, page: int, text: str, text_source: str) -> Page:
        """Store a page's text (``text_source``: ``text`` | ``transcript`` | ``none``)."""
        with self.tx() as conn:
            current = self.get_page(doc_id, page)
            if current is None:
                raise NotFoundError(f"pages: {doc_id} has no page {page}")
            updated = Page.model_validate(current.model_dump() | {"text": text, "text_source": text_source})
            conn.execute(
                "UPDATE pages SET text = ?, text_source = ? WHERE doc_id = ? AND page = ?",
                (updated.text, updated.text_source, doc_id, page),
            )
            self.reindex_document(doc_id)
        return updated

    def get_document_text(self, doc_id: str) -> str:
        """Page-delimited text (``=== Page N ===`` blocks) of the pages that have text."""
        rows = self._conn().execute(
            "SELECT page, text FROM pages WHERE doc_id = ? AND trim(text) != '' ORDER BY page", (doc_id,)
        )
        return "\n\n".join(f"=== Page {row['page']} ===\n{row['text']}" for row in rows)

    def get_extraction(self, doc_id: str) -> DocumentExtraction | None:
        """The stored model extraction of a document (``None`` if not extracted yet)."""
        row = self._conn().execute("SELECT extraction FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if row is None or row["extraction"] is None:
            return None
        return DocumentExtraction.model_validate_json(row["extraction"])

    # ---------------------------------------------------------------------------------------------
    # search
    # ---------------------------------------------------------------------------------------------

    def reindex_document(self, doc_id: str) -> None:
        """Rewrite the document's rows in ``documents_fts`` and ``documents_trigram``.

        Called automatically on every document, page and party-name write; public for repairs.
        """
        with self.tx() as conn:
            conn.execute("DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM documents_trigram WHERE doc_id = ?", (doc_id,))
            indexed = self._indexed_text(doc_id)
            if indexed is None:
                return
            conn.execute(
                "INSERT INTO documents_fts (doc_id, title, summary, explanation, text, parties) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (doc_id, indexed.title, indexed.summary, indexed.explanation, indexed.text, indexed.parties),
            )
            conn.execute(
                "INSERT INTO documents_trigram (doc_id, body) VALUES (?, ?)", (doc_id, indexed.trigram_body())
            )

    def _indexed_text(self, doc_id: str) -> _IndexedText | None:
        conn = self._conn()
        doc = conn.execute(
            "SELECT title, filename, summary, explanation, party_id FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
        if doc is None:
            return None
        pages = conn.execute("SELECT text FROM pages WHERE doc_id = ? ORDER BY page", (doc_id,))
        party = self.get_party(doc["party_id"]) if doc["party_id"] else None
        return _IndexedText(
            title=" ".join(part for part in (doc["title"], doc["filename"]) if part),
            summary=doc["summary"] or "",
            explanation=doc["explanation"] or "",
            pages=[row["text"] for row in pages],
            parties=" ".join([party.name, *party.aliases]) if party else "",
        )

    def search(self, query: str, limit: int = 20) -> list[SearchHit]:
        """Full-text + substring search over non-trashed documents, best first.

        Word hits (bm25 over ``documents_fts``, all terms) score in ``[1, 2)``; a substring hit
        (trigram index, every term of ≥ 3 characters in any folded spelling) adds ``[0, 1)``. So
        word matches always outrank substring-only matches, and each document appears once. Any
        input is safe: terms are quoted and FTS syntax is dropped.
        """
        tokens = search_tokens(query)
        hits: dict[str, SearchHit] = {}
        fts = _fts_expression(tokens)
        if fts:
            for row in self._conn().execute(_FTS_SEARCH_SQL, (fts, limit)):
                hits[row["doc_id"]] = SearchHit(
                    doc_id=row["doc_id"],
                    title=row["title"],
                    snippet=" ".join(row["snippet"].split()),
                    score=1.0 + _squash(-row["rank"]),
                )
        trigram = _trigram_expression(tokens)
        if trigram:
            needles = [v for token in tokens for v in _variants(token) if len(v) >= _TRIGRAM_MIN]
            for row in self._conn().execute(_TRIGRAM_SEARCH_SQL, (trigram, limit)):
                hit = hits.get(row["doc_id"])
                if hit is None:
                    indexed = self._indexed_text(row["doc_id"])
                    snippet = _snippet_for(indexed.parts(), needles) if indexed else ""
                    hit = hits[row["doc_id"]] = SearchHit(
                        doc_id=row["doc_id"], title=row["title"], snippet=snippet, score=0.0
                    )
                hit.score += _squash(-row["rank"])
        return sorted(hits.values(), key=lambda h: (-h.score, h.doc_id))[:limit]

    # ---------------------------------------------------------------------------------------------
    # parties
    # ---------------------------------------------------------------------------------------------

    def add_party(self, **fields: Any) -> Party:
        """Insert a party (``id`` generated unless given); returns the stored model."""
        return self._insert(_PARTIES, fields)

    def get_party(self, id: str) -> Party | None:
        """A party by id."""
        return self._one(_PARTIES, "id = ?", (id,))

    def update_party(self, id: str, **fields: Any) -> Party:
        """Update a party; renaming re-indexes its documents for search."""
        with self.tx():
            party = self._update(_PARTIES, id, fields)
            if _INDEXED_PARTY_FIELDS & fields.keys():
                self._reindex_party_documents(id)
        return party

    def list_parties(self) -> list[Party]:
        """All parties by name."""
        return self._many(_PARTIES, "ORDER BY name COLLATE NOCASE, id")

    def find_party_by_identifier(self, value: str) -> Party | None:
        """The (oldest) party holding an identifier equal to ``value`` after normalisation.

        Spaces, slashes, dots, dashes and case are ignored (see :func:`normalize_identifier`).
        """
        wanted = normalize_identifier(value)
        if not wanted:
            return None
        for party in self._many(_PARTIES, "WHERE identifiers != '[]' ORDER BY created_at, id"):
            if any(normalize_identifier(identifier.value) == wanted for identifier in party.identifiers):
                return party
        return None

    def find_parties_by_name(self, name: str) -> list[Party]:
        """Parties whose name or an alias equals ``name`` (case- and whitespace-insensitive)."""
        wanted = _name_key(name)
        if not wanted:
            return []
        return [
            party
            for party in self.list_parties()
            if wanted in {_name_key(candidate) for candidate in (party.name, *party.aliases)}
        ]

    def merge_parties(self, keep_id: str, drop_id: str) -> Party:
        """Fold ``drop`` into ``keep`` and delete ``drop``.

        Documents, cases, contracts, items, drafts and call notes are re-pointed; names become aliases;
        identifiers and IBANs are united; empty contact fields of ``keep`` are filled from ``drop``.
        """
        if keep_id == drop_id:
            raise ValueError("cannot merge a party into itself")
        with self.tx() as conn:
            keep = self._require(_PARTIES, keep_id)
            drop = self._require(_PARTIES, drop_id)
            now = now_iso()
            for table in ("documents", "cases", "contracts", "items", "drafts", "call_notes"):
                conn.execute(
                    f"UPDATE {table} SET party_id = ?, updated_at = ? WHERE party_id = ?",
                    (keep_id, now, drop_id),
                )
            merged = self._update(_PARTIES, keep_id, _merged_party_fields(keep, drop))
            conn.execute("DELETE FROM parties WHERE id = ?", (drop_id,))
            self._reindex_party_documents(keep_id)
        return merged

    def _reindex_party_documents(self, party_id: str) -> None:
        rows = self._conn().execute("SELECT id FROM documents WHERE party_id = ?", (party_id,)).fetchall()
        for row in rows:
            self.reindex_document(row["id"])

    # ---------------------------------------------------------------------------------------------
    # cases
    # ---------------------------------------------------------------------------------------------

    def add_case(self, **fields: Any) -> Case:
        """Insert a case (thread); ``id`` generated unless given."""
        return self._insert(_CASES, fields)

    def get_case(self, id: str) -> Case | None:
        """A case by id."""
        return self._one(_CASES, "id = ?", (id,))

    def update_case(self, id: str, **fields: Any) -> Case:
        """Update case fields; returns the updated model."""
        return self._update(_CASES, id, fields)

    def delete_case(self, id: str) -> bool:
        """Delete a case (thread); ``False`` if it did not exist. Letters, to-dos, contracts and drafts
        still in it stay, unthreaded (``ON DELETE SET NULL``)."""
        return self._delete(_CASES, id)

    def list_cases(self, party_id: str | None = None) -> list[Case]:
        """Cases (threads), most recently updated first."""
        where = _Where()
        where.equals("party_id", party_id)
        return self._many(_CASES, f"{where.sql()} ORDER BY updated_at DESC, id", where.params)

    def find_case_by_reference(self, reference: str) -> Case | None:
        """The most recently updated case whose reference equals ``reference`` (normalised)."""
        wanted = normalize_identifier(reference)
        if not wanted:
            return None
        for case in self._many(_CASES, "WHERE reference IS NOT NULL ORDER BY updated_at DESC, id"):
            if case.reference and normalize_identifier(case.reference) == wanted:
                return case
        return None

    # ---------------------------------------------------------------------------------------------
    # contracts
    # ---------------------------------------------------------------------------------------------

    def add_contract(self, **fields: Any) -> Contract:
        """Insert a contract; ``id`` generated unless given."""
        return self._insert(_CONTRACTS, fields)

    def get_contract(self, id: str) -> Contract | None:
        """A contract by id."""
        return self._one(_CONTRACTS, "id = ?", (id,))

    def update_contract(self, id: str, **fields: Any) -> Contract:
        """Update contract fields; returns the updated model."""
        return self._update(_CONTRACTS, id, fields)

    def list_contracts(self, status: Filter = None, party_id: str | None = None) -> list[Contract]:
        """Contracts by name, optionally filtered by status and party."""
        where = _Where()
        where.within("status", status)
        where.equals("party_id", party_id)
        return self._many(_CONTRACTS, f"{where.sql()} ORDER BY name COLLATE NOCASE, id", where.params)

    def find_contract(
        self, party_id: str, customer_number: str | None = None, category: str | None = None
    ) -> Contract | None:
        """The party's contract a letter refers to.

        A matching customer number (normalised) wins. Otherwise a contract of the same ``category``
        matches if it has no customer number, or if the letter gave none. A contract with a
        *different* customer number never matches. Active and recently updated contracts first.
        """
        candidates = self._many(
            _CONTRACTS,
            "WHERE party_id = ? ORDER BY status = 'active' DESC, updated_at DESC, id",
            (party_id,),
        )
        number = normalize_identifier(customer_number or "")
        if number:
            for contract in candidates:
                if contract.customer_number and normalize_identifier(contract.customer_number) == number:
                    return contract
        if category is None:
            return None
        for contract in candidates:
            if contract.category == category and not (number and contract.customer_number):
                return contract
        return None

    # ---------------------------------------------------------------------------------------------
    # items
    # ---------------------------------------------------------------------------------------------

    def add_item(self, **fields: Any) -> Item:
        """Insert a to-do/date; ``id`` generated unless given."""
        return self._insert(_ITEMS, fields)

    def get_item(self, id: str) -> Item | None:
        """An item by id."""
        return self._one(_ITEMS, "id = ?", (id,))

    def update_item(self, id: str, **fields: Any) -> Item:
        """Update item fields; returns the updated model."""
        return self._update(_ITEMS, id, fields)

    def delete_item(self, id: str) -> bool:
        """Delete an item; ``False`` if it did not exist."""
        return self._delete(_ITEMS, id)

    def list_items(
        self,
        status: Filter = None,
        kind: Filter = None,
        from_date: str | date | None = None,
        to_date: str | date | None = None,
        area: Filter = None,
        party_id: str | None = None,
        doc_id: str | None = None,
        contract_id: str | None = None,
        case_id: str | None = None,
        include_undated: bool = True,
        limit: int | None = None,
    ) -> list[Item]:
        """To-dos & dates, soonest first (undated last), then by priority and age.

        ``from_date``/``to_date`` bound ``due_date`` (inclusive); ``include_undated`` keeps items
        without a due date regardless of the range. Items of trashed documents are left out.
        """
        where = _Where()
        where.add("d.deleted_at IS NULL")
        where.within("i.status", status)
        where.within("i.kind", kind)
        where.within("i.area", area)
        for column, value in (
            ("i.party_id", party_id),
            ("i.doc_id", doc_id),
            ("i.contract_id", contract_id),
            ("i.case_id", case_id),
        ):
            where.equals(column, value)
        _add_due_range(where, _iso_day(from_date), _iso_day(to_date), include_undated)
        paging, paging_params = _paging(limit)
        sql = (
            f"SELECT {_ITEMS.columns('i')} FROM items i LEFT JOIN documents d ON d.id = i.doc_id "
            f"{where.sql()} ORDER BY i.due_date ASC NULLS LAST, {_priority_rank('i.priority')}, "
            f"i.created_at, i.rowid{paging}"
        )
        rows = self._conn().execute(sql, [*where.params, *paging_params]).fetchall()
        return [_ITEMS.decode(row) for row in rows]

    def upsert_item_by_slot(self, doc_id: str, slot_key: str, **fields: Any) -> Item:
        """Insert or update the item occupying ``(doc_id, slot_key)``.

        New items get the deterministic id ``content_id("itm", doc_id, slot_key)``. An existing
        item the person has edited (``user_modified``) is returned unchanged.
        """
        _ITEMS.check(fields, _ITEMS.writable)
        with self.tx():
            existing = self._one(_ITEMS, "doc_id = ? AND slot_key = ?", (doc_id, slot_key))
            if existing is None:
                return self._insert(
                    _ITEMS,
                    {
                        **fields,
                        "id": content_id("itm", doc_id, slot_key),
                        "doc_id": doc_id,
                        "slot_key": slot_key,
                    },
                )
            if existing.user_modified:
                return existing
            fields = {
                key: value for key, value in fields.items() if key != "filed_on" or not existing.filed_on
            }
            return self._update(_ITEMS, existing.id, fields)

    def delete_stale_extracted_items(self, doc_id: str, keep_slot_keys: Iterable[str]) -> int:
        """Delete the document's extracted, unedited items whose slot is not in ``keep_slot_keys``.

        Items without a slot key count as stale. Manual/rule items, ``user_modified`` rows and items
        the person acted on (any status but ``open``: done, snoozed, dismissed …) are never touched.
        Returns the number of deleted items.
        """
        keep = set(keep_slot_keys)
        with self.tx() as conn:
            rows = conn.execute(
                "SELECT id, slot_key FROM items "
                "WHERE doc_id = ? AND origin = 'extracted' AND user_modified = 0 AND status = 'open'",
                (doc_id,),
            ).fetchall()
            stale = [(row["id"],) for row in rows if row["slot_key"] not in keep]
            conn.executemany("DELETE FROM items WHERE id = ?", stale)
        return len(stale)

    # ---------------------------------------------------------------------------------------------
    # suggestions
    # ---------------------------------------------------------------------------------------------

    def upsert_suggestion(self, suggestion: Suggestion | Mapping[str, Any]) -> Suggestion:
        """Insert or refresh a suggestion (Idea) identified by its ``fingerprint``.

        New: id ``content_id("sug", fingerprint)``. Existing: the text fields (title, body,
        rationale, priority, refs, action, savings_estimate, due_date) are refreshed while the
        person's status/snooze is kept — except an ``expired`` Idea, which becomes ``new`` again.
        ``id``, ``created_at`` and ``updated_at`` of the argument are ignored.
        """
        data = suggestion.model_dump() if isinstance(suggestion, Suggestion) else dict(suggestion)
        for ignored in _READ_ONLY:
            data.pop(ignored, None)
        _SUGGESTIONS.check(data, _SUGGESTIONS.writable)
        fingerprint = data.get("fingerprint")
        if not fingerprint:
            raise ValueError("a suggestion needs a fingerprint")
        with self.tx():
            existing = self._one(_SUGGESTIONS, "fingerprint = ?", (fingerprint,))
            if existing is None:
                return self._insert(_SUGGESTIONS, {**data, "id": content_id("sug", fingerprint)})
            changes = {name: data[name] for name in _SUGGESTION_TEXT_FIELDS if name in data}
            if existing.status == "expired":
                changes |= {"status": "new", "snoozed_until": None}
            return self._update(_SUGGESTIONS, existing.id, changes)

    def get_suggestion(self, id: str) -> Suggestion | None:
        """A suggestion (Idea) by id."""
        return self._one(_SUGGESTIONS, "id = ?", (id,))

    def update_suggestion(self, id: str, **fields: Any) -> Suggestion:
        """Update suggestion fields (e.g. status, snooze); returns the updated model."""
        return self._update(_SUGGESTIONS, id, fields)

    def list_suggestions(self, status: Filter = None, limit: int | None = None) -> list[Suggestion]:
        """Ideas by priority, then soonest due date, then newest."""
        where = _Where()
        where.within("status", status)
        paging, paging_params = _paging(limit)
        tail = (
            f"{where.sql()} ORDER BY {_priority_rank('priority')}, due_date ASC NULLS LAST, "
            f"created_at DESC, id{paging}"
        )
        return self._many(_SUGGESTIONS, tail, [*where.params, *paging_params])

    def reconcile_suggestions(self, rule_ids: Iterable[str], live_fingerprints: Iterable[str]) -> int:
        """Expire rule Ideas that their rule no longer produces.

        Rows with ``source='rule'``, ``rule_id`` in ``rule_ids`` and status ``new``/``snoozed`` whose
        fingerprint is not in ``live_fingerprints`` become ``expired``. Returns how many.
        """
        rules = list(dict.fromkeys(rule_ids))
        if not rules:
            return 0
        live = set(live_fingerprints)
        with self.tx() as conn:
            rows = conn.execute(
                "SELECT id, fingerprint FROM suggestions WHERE source = 'rule' "
                f"AND status IN ('new', 'snoozed') AND rule_id IN ({', '.join('?' * len(rules))})",
                rules,
            ).fetchall()
            now = now_iso()
            expired = [(now, row["id"]) for row in rows if row["fingerprint"] not in live]
            conn.executemany(
                "UPDATE suggestions SET status = 'expired', updated_at = ? WHERE id = ?", expired
            )
        return len(expired)

    # ---------------------------------------------------------------------------------------------
    # drafts / notes / chat
    # ---------------------------------------------------------------------------------------------

    def add_draft(self, **fields: Any) -> Draft:
        """Insert a letter draft; ``id`` generated unless given."""
        return self._insert(_DRAFTS, fields)

    def get_draft(self, id: str) -> Draft | None:
        """A draft by id."""
        return self._one(_DRAFTS, "id = ?", (id,))

    def update_draft(self, id: str, **fields: Any) -> Draft:
        """Update draft fields; returns the updated model."""
        return self._update(_DRAFTS, id, fields)

    def list_drafts(
        self,
        *,
        status: Filter = None,
        doc_id: str | None = None,
        case_id: str | None = None,
        party_id: str | None = None,
        contract_id: str | None = None,
    ) -> list[Draft]:
        """Letters, newest first."""
        where = _Where()
        where.within("status", status)
        for column, value in (
            ("doc_id", doc_id),
            ("case_id", case_id),
            ("party_id", party_id),
            ("contract_id", contract_id),
        ):
            where.equals(column, value)
        return self._many(_DRAFTS, f"{where.sql()} ORDER BY created_at DESC, rowid DESC", where.params)

    def delete_draft(self, id: str) -> bool:
        """Delete a draft; ``False`` if it did not exist."""
        return self._delete(_DRAFTS, id)

    def get_sent_signer(self, draft_id: str) -> SentSigner | None:
        """What the letter's PDF showed of the sender when it was marked as sent (``None``: not kept)."""
        row = self._conn().execute("SELECT sent_profile FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None or row["sent_profile"] is None:
            return None
        return SentSigner.model_validate_json(row["sent_profile"])

    def add_note(self, text: str, item_ids: Sequence[str] = (), *, id: str | None = None) -> Note:
        """Insert a note, optionally attached to items."""
        return self._insert(_NOTES, {"id": id, "text": text, "item_ids": list(item_ids)})

    def list_notes(self, item_id: str | None = None) -> list[Note]:
        """Notes, newest first (optionally only those attached to ``item_id``)."""
        where = _Where()
        if item_id is not None:
            where.add("EXISTS (SELECT 1 FROM json_each(notes.item_ids) WHERE value = ?)", item_id)
        return self._many(_NOTES, f"{where.sql()} ORDER BY created_at DESC, rowid DESC", where.params)

    # ---------------------------------------------------------------------------------------------
    # proofs of sent letters / call notes
    # ---------------------------------------------------------------------------------------------

    def add_proof(self, **fields: Any) -> Proof:
        """Insert a proof of a sent letter (``draft_id``, ``kind``, optional ``doc_id``/``on_date``/``note``)."""
        return self._insert(_PROOFS, fields)

    def get_proof(self, id: str) -> Proof | None:
        """A proof by id."""
        return self._one(_PROOFS, "id = ?", (id,))

    def update_proof(self, id: str, **fields: Any) -> Proof:
        """Update a proof's kind, day or note."""
        return self._update(_PROOFS, id, fields)

    def delete_proof(self, id: str) -> bool:
        """Delete a proof row (its file stays; the caller decides about it)."""
        return self._delete(_PROOFS, id)

    def list_proofs(self, draft_id: str | None = None, *, doc_id: str | None = None) -> list[Proof]:
        """Proofs, oldest first (optionally of one letter, or using one file). A proof whose file is in
        the trash is left out until the file is restored."""
        where = _Where()
        where.equals("draft_id", draft_id)
        where.equals("doc_id", doc_id)
        where.add("(doc_id IS NULL OR doc_id NOT IN (SELECT id FROM documents WHERE deleted_at IS NOT NULL))")
        return self._many(_PROOFS, f"{where.sql()} ORDER BY created_at, rowid", where.params)

    def add_call_note(self, **fields: Any) -> CallNote:
        """Insert a call note (``called_on`` and ``summary`` required)."""
        return self._insert(_CALL_NOTES, fields)

    def get_call_note(self, id: str) -> CallNote | None:
        """A call note by id."""
        return self._one(_CALL_NOTES, "id = ?", (id,))

    def update_call_note(self, id: str, **fields: Any) -> CallNote:
        """Update a call note (e.g. ``promise_kept_on``)."""
        return self._update(_CALL_NOTES, id, fields)

    def delete_call_note(self, id: str) -> bool:
        """Delete a call note; ``False`` if it did not exist."""
        return self._delete(_CALL_NOTES, id)

    def list_call_notes(self, *, party_id: str | None = None, case_id: str | None = None) -> list[CallNote]:
        """Call notes, newest call first (optionally of one party or thread)."""
        where = _Where()
        where.equals("party_id", party_id)
        where.equals("case_id", case_id)
        return self._many(
            _CALL_NOTES, f"{where.sql()} ORDER BY called_on DESC, created_at DESC, rowid DESC", where.params
        )

    def add_chat_message(
        self,
        thread_id: str,
        role: str,
        content: str,
        *,
        citations: Sequence[Any] = (),
        tool_calls: Sequence[Mapping[str, Any]] = (),
        id: str | None = None,
    ) -> ChatMessage:
        """Append a message to an Ask thread."""
        return self._insert(
            _CHAT,
            {
                "id": id,
                "thread_id": thread_id,
                "role": role,
                "content": content,
                "citations": list(citations),
                "tool_calls": [dict(call) for call in tool_calls],
            },
        )

    def list_chat_messages(self, thread_id: str) -> list[ChatMessage]:
        """A thread's messages in the order they were written."""
        return self._many(_CHAT, "WHERE thread_id = ? ORDER BY created_at, rowid", (thread_id,))

    # ---------------------------------------------------------------------------------------------
    # jobs (the queue of record)
    # ---------------------------------------------------------------------------------------------

    def enqueue_job(
        self,
        kind: str,
        doc_id: str | None = None,
        force: bool = False,
        *,
        not_before: str | datetime | None = None,
    ) -> Job:
        """Queue a job (``ingest`` | ``reprocess`` | ``review``); ``not_before`` delays it."""
        return self._insert(
            _JOBS,
            {
                "kind": kind,
                "doc_id": doc_id,
                "force": force,
                "not_before": None if not_before is None else _utc_timestamp(not_before),
            },
        )

    def claim_next_job(self, kinds: Iterable[str] | None = None) -> Job | None:
        """Atomically take the oldest due queued job (optionally of ``kinds``) and mark it running.

        Due means ``not_before`` is unset or has passed. ``attempts`` is incremented. Two workers can
        never claim the same job. Returns ``None`` when nothing is due.
        """
        where = _Where()
        where.add("status = 'queued'")
        where.add("(not_before IS NULL OR not_before <= ?)", real_now_iso())  # back-off is real time
        where.within("kind", None if kinds is None else list(kinds))
        with self.tx() as conn:
            row = conn.execute(
                f"SELECT id, attempts FROM jobs {where.sql()} ORDER BY created_at, rowid LIMIT 1",
                where.params,
            ).fetchone()
            if row is None:
                return None
            return self._update(_JOBS, row["id"], {"status": "running", "attempts": row["attempts"] + 1})

    def update_job(self, id: str, **fields: Any) -> Job:
        """Update a job (``not_before`` accepts ISO strings or datetimes and is stored in UTC)."""
        if fields.get("not_before") is not None:
            fields["not_before"] = _utc_timestamp(fields["not_before"])
        return self._update(_JOBS, id, fields)

    def get_job(self, id: str) -> Job | None:
        """A job by id."""
        return self._one(_JOBS, "id = ?", (id,))

    def latest_job(self, doc_id: str) -> Job | None:
        """The newest job of a document (``None`` if it never had one)."""
        return self._one(_JOBS, "doc_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (doc_id,))

    def list_jobs(self, active_only: bool = False, limit: int | None = None) -> list[Job]:
        """Jobs, newest first; ``active_only`` keeps queued, running and waiting ones."""
        where = _Where()
        if active_only:
            where.within("status", _ACTIVE_JOB_STATUSES)
        paging, paging_params = _paging(limit)
        tail = f"{where.sql()} ORDER BY created_at DESC, rowid DESC{paging}"
        return self._many(_JOBS, tail, [*where.params, *paging_params])

    def requeue_running_jobs(self) -> int:
        """Startup recovery: jobs left ``running`` by a previous process go back to ``queued`` —
        unless they were already interrupted :data:`MAX_JOB_ATTEMPTS` times (a letter that crashes
        the process, e.g. by exhausting memory, would otherwise crash every start): those fail, and
        so do their documents.

        Only these interruptions count, not ``attempts``: a job the worker gave back itself (a usage
        limit pause, a clean stop) was claimed without anything crashing.
        """
        now = now_iso()
        with self.tx() as conn:
            active = {job.id for job in self.list_jobs(active_only=True)}
            saved: dict[str, int] = json.loads(self.get_meta(_INTERRUPTIONS_KEY) or "{}")
            interrupted = {job_id: count for job_id, count in saved.items() if job_id in active}
            for job in conn.execute("SELECT id, doc_id FROM jobs WHERE status = 'running'").fetchall():
                interrupted[job["id"]] = interrupted.get(job["id"], 0) + 1
                if interrupted[job["id"]] < MAX_JOB_ATTEMPTS:
                    continue
                del interrupted[job["id"]]
                conn.execute(
                    "UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                    (INTERRUPTED_JOB_ERROR, now, job["id"]),
                )
                if job["doc_id"] is not None:
                    conn.execute(
                        "UPDATE documents SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                        (INTERRUPTED_JOB_ERROR, now, job["doc_id"]),
                    )
            self.set_meta(
                _INTERRUPTIONS_KEY, json.dumps(interrupted, sort_keys=True) if interrupted else None
            )
            return conn.execute(
                "UPDATE jobs SET status = 'queued', updated_at = ? WHERE status = 'running'", (now,)
            ).rowcount

    # ---------------------------------------------------------------------------------------------
    # activity / LLM accounting / cache
    # ---------------------------------------------------------------------------------------------

    def log_activity(
        self,
        kind: str,
        message: str,
        ref_type: str | None = None,
        ref_id: str | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> Activity:
        """Append an entry to the activity log ("Privacy & AI usage"); while a paired phone's request
        runs, the entry says so and carries the phone as ``device`` (:mod:`ordnung.phone.actor`)."""
        message, payload = attribute(message, data)
        ts = now_iso()
        with self.tx() as conn:
            cursor = conn.execute(
                "INSERT INTO activity (ts, kind, message, ref_type, ref_id, data) VALUES (?, ?, ?, ?, ?, ?)",
                (ts, kind, message, ref_type, ref_id, _ACTIVITY.encode("data", payload)),
            )
        return Activity(
            id=int(cursor.lastrowid or 0),
            ts=ts,
            kind=kind,
            message=message,
            ref_type=ref_type,
            ref_id=ref_id,
            data=payload,
        )

    def list_activity(
        self,
        limit: int | None = 50,
        *,
        kinds: Sequence[str] | None = None,
        data: Mapping[str, str] | None = None,
    ) -> list[Activity]:
        """The newest activity entries first (``limit`` ``None``: all); ``kinds`` keeps those kinds,
        ``data`` the entries whose data has these values (``{"source": "folder"}``; keys are plain names)."""
        where = _Where()
        where.within("kind", None if kinds is None else list(kinds))
        for key, value in (data or {}).items():
            if not key.isidentifier():
                raise ValueError(f"not a data key: {key!r}")
            where.add(f"json_extract(data, '$.{key}') = ?", value)
        paging, paging_params = _paging(limit)
        return self._many(
            _ACTIVITY, f"{where.sql()} ORDER BY id DESC{paging}", [*where.params, *paging_params]
        )

    def count_activity(self, kind: str, key: str, *, since: str) -> dict[str, int]:
        """How many ``kind`` entries since ``since`` (an ISO timestamp) there are per value of
        ``data.<key>`` (``key`` a plain name)."""
        if not key.isidentifier():
            raise ValueError(f"not a data key: {key!r}")
        rows = self._conn().execute(
            f"SELECT json_extract(data, '$.{key}') AS value, COUNT(*) AS n FROM activity "
            "WHERE kind = ? AND ts >= ? GROUP BY value",
            (kind, since),
        )
        return {str(row["value"]): int(row["n"]) for row in rows if row["value"] is not None}

    def activity_about(self, ref_type: str, ref_id: str, kinds: Sequence[str]) -> list[Activity]:
        """The activity entries of one of ``kinds`` about a row, newest first."""
        where = _Where()
        where.equals("ref_type", ref_type)
        where.equals("ref_id", ref_id)
        where.within("kind", kinds)
        return self._many(_ACTIVITY, f"{where.sql()} ORDER BY id DESC", where.params)

    def last_activity(self, ref_type: str, ref_id: str, kinds: Sequence[str]) -> Activity | None:
        """The newest activity entry of one of ``kinds`` about a row (``None``: there is none)."""
        where = _Where()
        where.equals("ref_type", ref_type)
        where.equals("ref_id", ref_id)
        where.within("kind", kinds)
        found = self._many(_ACTIVITY, f"{where.sql()} ORDER BY id DESC LIMIT 1", where.params)
        return found[0] if found else None

    def log_llm_call(
        self,
        purpose: str,
        model: str,
        backend: str,
        usage: Usage,
        ok: bool = True,
        error: str | None = None,
        cache_hit: bool = False,
        doc_ids: list[str] | None = None,
        pages_sent: int = 0,
        bytes_sent: int = 0,
        *,
        request_key: str | None = None,
        prompt_name: str | None = None,
        prompt_version: str | None = None,
        served_model: str | None = None,
        job_id: str | None = None,
        stage: str | None = None,
        span_id: str | None = None,
        repair_of: int | None = None,
        outcome: str = "ok",
    ) -> int:
        """Record one model call and return its id (never the prompt or the response — accounting data,
        the replay/cache key, the prompt's name and version, and where the call belongs).

        A letter the call carried that was deleted while the call ran is treated as if it had been
        deleted after the call (:meth:`delete_document`): its id, the replay key, span, job and error
        are left out, and only the anonymous numbers are written.
        """
        with self.tx() as conn:
            carried = list(doc_ids or [])
            gone = self._gone_documents(conn, carried)
            if gone:
                carried = [doc_id for doc_id in carried if doc_id not in gone]
                request_key = span_id = job_id = error = None
            cursor = conn.execute(
                "INSERT INTO llm_calls (ts, purpose, model, backend, duration_ms, input_tokens, "
                "output_tokens, cache_read_tokens, cache_creation_tokens, cost_usd, ok, error, cache_hit, "
                "doc_ids, pages_sent, bytes_sent, request_key, prompt_name, prompt_version, served_model, "
                "job_id, stage, span_id, repair_of, outcome) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    now_iso(),
                    purpose,
                    model,
                    backend,
                    usage.duration_ms,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cache_read_tokens,
                    usage.cache_creation_tokens,
                    usage.cost_usd,
                    ok,
                    error,
                    cache_hit,
                    _LLM_CALLS.encode("doc_ids", carried),
                    pages_sent,
                    bytes_sent,
                    request_key,
                    prompt_name,
                    prompt_version,
                    served_model,
                    job_id,
                    stage,
                    span_id,
                    repair_of,
                    outcome,
                ),
            )
        return int(cursor.lastrowid or 0)

    def usage_stats(self, recent: int = 20) -> UsageStats:
        """Totals, per-purpose totals and the ``recent`` newest calls."""
        conn = self._conn()
        totals = conn.execute(f"SELECT {_USAGE_AGGREGATES} FROM llm_calls").fetchone()
        by_purpose = {
            row["purpose"]: PurposeUsage(
                calls=row["calls"],
                cache_hits=row["cache_hits"],
                errors=row["errors"],
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                cost_usd=round(float(row["cost_usd"]), 6),
            )
            for row in conn.execute(
                f"SELECT purpose, {_USAGE_AGGREGATES} FROM llm_calls GROUP BY purpose ORDER BY purpose"
            )
        }
        return UsageStats(
            calls=totals["calls"],
            cache_hits=totals["cache_hits"],
            input_tokens=totals["input_tokens"],
            output_tokens=totals["output_tokens"],
            cost_usd=round(totals["cost_usd"], 6),
            by_purpose=by_purpose,
            recent=self._many(_LLM_CALLS, "ORDER BY id DESC LIMIT ?", (recent,)),
        )

    def cache_get(self, key: str) -> dict[str, Any] | None:
        """A cached model response (``None`` on a miss)."""
        row = self._conn().execute("SELECT response FROM llm_cache WHERE key = ?", (key,)).fetchone()
        return None if row is None else dict(json.loads(row["response"]))

    def cache_put(
        self,
        key: str,
        purpose: str,
        model: str,
        response: dict[str, Any],
        doc_sha: str | None = None,
        *,
        doc_ids: Sequence[str] = (),
    ) -> bool:
        """Store (or replace) a model response; ``doc_sha`` tags it for purging with its document
        (``doc_a|doc_b`` for a call that carried several — deleting any one of them purges it).
        Nothing is stored when one of ``doc_ids`` (the letters the call carried) was deleted while
        the call ran; returns whether it was stored."""
        with self.tx() as conn:
            if self._gone_documents(conn, doc_ids):
                return False
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (key, purpose, model, response, doc_sha, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (key, purpose, model, json.dumps(response, ensure_ascii=False), doc_sha, now_iso()),
            )
        return True

    @staticmethod
    def _gone_documents(conn: sqlite3.Connection, doc_ids: Sequence[str]) -> set[str]:
        """The ids among ``doc_ids`` with no document (deleted — the trash still has its letters)."""
        wanted = set(doc_ids)
        if not wanted:
            return set()
        found = conn.execute(
            f"SELECT id FROM documents WHERE id IN ({', '.join('?' * len(wanted))})", sorted(wanted)
        ).fetchall()
        return wanted - {row["id"] for row in found}

    def purge_cache_for(self, doc_sha: str) -> int:
        """Delete the cached responses tagged with ``doc_sha`` (alone or among others); returns how many."""
        sep = _CACHE_TAG_SEP
        with self.tx() as conn:
            return conn.execute(
                "DELETE FROM llm_cache WHERE doc_sha = ? OR instr(? || doc_sha || ?, ?) > 0",
                (doc_sha, sep, sep, f"{sep}{doc_sha}{sep}"),
            ).rowcount

    # ---------------------------------------------------------------------------------------------
    # traces: how a letter was read (ordnung.trace)
    # ---------------------------------------------------------------------------------------------

    def reserve_trace(self, root: TraceSpanRecord) -> None:
        """Keep a reading's root span as ``running`` while it is read: its number is taken (see
        :meth:`next_trace_reading`) but it is shown nowhere until :meth:`save_trace` replaces it."""
        row = _TRACE_SPANS.row(root) | {"status": _RUNNING}
        columns = list(row)
        with self.tx() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO trace_spans ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' * len(columns))})",
                [row[column] for column in columns],
            )

    def end_running_traces(self, *, ended: str, error: str) -> int:
        """Mark every reading still ``running`` as ended (``error`` code, ``ended`` attribute) — at
        startup, when no reading can be running; returns how many."""
        with self.tx() as conn:
            return conn.execute(
                "UPDATE trace_spans SET status = 'error', error = ?, "
                "attributes = json_set(attributes, '$.ended', ?) WHERE kind = 'run' AND status = ?",
                (error, ended, _RUNNING),
            ).rowcount

    def save_trace(
        self, spans: Sequence[TraceSpanRecord], *, keep: int, interrupted: Collection[str] = ()
    ) -> int:
        """Store the spans of one reading of one letter, then delete that letter's readings beyond
        what is kept: the newest ``keep`` that ran to the end and, of the readings whose ``ended``
        attribute is one of ``interrupted``, only the newest — while it is newer than the oldest
        reading kept. Readings still running are never deleted. Returns how many readings were
        deleted (their usage-log rows stay, with a span id that no longer resolves)."""
        if not spans:
            return 0
        rows = [_TRACE_SPANS.row(span) for span in spans]
        columns = list(rows[0])
        sql = (
            f"INSERT OR REPLACE INTO trace_spans ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' * len(columns))})"
        )
        with self.tx() as conn:
            conn.executemany(sql, [[row[column] for column in columns] for row in rows])
            readings = conn.execute(
                "SELECT trace_id, json_extract(attributes, '$.ended') AS ended, "
                f"CAST(json_extract(attributes, '$.reading') AS INTEGER) AS reading FROM trace_spans "
                f"{_TRACE_RUNS_TAIL}",
                (spans[0].doc_id,),
            ).fetchall()
            stale = [(trace_id,) for trace_id in _stale_readings(readings, keep, frozenset(interrupted))]
            conn.executemany("DELETE FROM trace_spans WHERE trace_id = ?", stale)
        return len(stale)

    def trace_runs(self, doc_id: str) -> list[TraceSpanRecord]:
        """The root spans of a letter's kept readings, newest first (not the ones still running)."""
        return self._many(_TRACE_SPANS, _TRACE_RUNS_TAIL, (doc_id,))

    def trace_spans(self, trace_id: str) -> list[TraceSpanRecord]:
        """Every span of one reading in display order."""
        return self._many(
            _TRACE_SPANS, "WHERE trace_id = ? AND status != ? ORDER BY seq", (trace_id, _RUNNING)
        )

    def trace_steps(self, doc_id: str, kind: SpanKind) -> list[TraceSpanRecord]:
        """The steps of ``kind`` of every kept reading of a letter (by reading, in display order)."""
        tail = "WHERE doc_id = ? AND kind = ? AND status != ? ORDER BY trace_id, seq"
        return self._many(_TRACE_SPANS, tail, (doc_id, kind, _RUNNING))

    def next_trace_reading(self, doc_id: str) -> int:
        """The number of a letter's next reading: one more than the highest kept or running (1 for
        the first). Call it in the transaction that reserves the number (:meth:`reserve_trace`)."""
        row = (
            self._conn()
            .execute(
                "SELECT MAX(CAST(json_extract(attributes, '$.reading') AS INTEGER)) FROM trace_spans "
                "WHERE doc_id = ? AND kind = 'run'",
                (doc_id,),
            )
            .fetchone()
        )
        return int(row[0] or 0) + 1

    def count_trace_runs(self) -> int:
        """How many readings are kept, of all letters (not the ones still running)."""
        return int(
            self._conn()
            .execute("SELECT COUNT(*) FROM trace_spans WHERE kind = 'run' AND status != ?", (_RUNNING,))
            .fetchone()[0]
        )

    def trace_calls(self, doc_id: str) -> dict[str, list[LLMCallRecord]]:
        """The usage-log rows of the model steps of a letter's kept readings, by trace id.

        One query joins each row to its step, so a reading stored meanwhile (its rows are logged
        while it runs, its steps at its end) is either wholly in the result or not at all."""
        rows = self._conn().execute(
            f"SELECT s.trace_id AS owner, {_LLM_CALLS.columns('c')} FROM llm_calls c "
            "JOIN trace_spans s ON s.id = c.span_id WHERE s.doc_id = ? AND s.kind = 'model' ORDER BY c.id",
            (doc_id,),
        )
        calls: dict[str, list[LLMCallRecord]] = {}
        for row in rows:
            fields = {column: row[column] for column in row.keys() if column != "owner"}  # noqa: SIM118
            calls.setdefault(row["owner"], []).append(_LLM_CALLS.decode(fields))
        return calls

    def export_traces(self) -> tuple[list[TraceSpanRecord], list[LLMCallRecord]]:
        """Every kept span of the letters not in the trash, and the usage-log rows of their model steps."""
        spans = self._many(
            _TRACE_SPANS,
            "WHERE doc_id IN (SELECT id FROM documents WHERE deleted_at IS NULL) "
            "AND trace_id NOT IN (SELECT trace_id FROM trace_spans WHERE status = ?) ORDER BY doc_id, trace_id, seq",
            (_RUNNING,),
        )
        calls = self._many(
            _LLM_CALLS,
            "WHERE span_id IN (SELECT s.id FROM trace_spans s JOIN documents d ON d.id = s.doc_id "
            "WHERE d.deleted_at IS NULL) ORDER BY id",
        )
        return spans, calls

    # ---------------------------------------------------------------------------------------------
    # counts
    # ---------------------------------------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        """Row counts for dashboards and health checks (trashed documents counted separately)."""
        conn = self._conn()
        return {name: int(conn.execute(sql).fetchone()[0]) for name, sql in _COUNT_QUERIES.items()}


# --------------------------------------------------------------------------------------------------
# module-level SQL and helpers used by Store
# --------------------------------------------------------------------------------------------------

_FTS_SEARCH_SQL = """
SELECT documents_fts.doc_id AS doc_id, COALESCE(d.title, d.filename) AS title,
       bm25(documents_fts, 0.0, 10.0, 4.0, 2.0, 1.0, 5.0) AS rank,
       snippet(documents_fts, -1, '', '', '…', 16) AS snippet
FROM documents_fts JOIN documents d ON d.id = documents_fts.doc_id
WHERE documents_fts MATCH ? AND d.deleted_at IS NULL
ORDER BY rank LIMIT ?
"""

_TRIGRAM_SEARCH_SQL = """
SELECT documents_trigram.doc_id AS doc_id, COALESCE(d.title, d.filename) AS title,
       bm25(documents_trigram) AS rank
FROM documents_trigram JOIN documents d ON d.id = documents_trigram.doc_id
WHERE documents_trigram MATCH ? AND d.deleted_at IS NULL
ORDER BY rank LIMIT ?
"""

_USAGE_AGGREGATES = (
    "COUNT(*) AS calls, COALESCE(SUM(cache_hit), 0) AS cache_hits, "
    "COALESCE(SUM(1 - ok), 0) AS errors, "
    # every prompt token counts as "in", those read from or written to the prompt cache too — as a letter's
    # "How it was read" counts them (walkthrough of phase 2: "2 in" beside the trace's "20k in")
    "COALESCE(SUM(input_tokens + cache_read_tokens + cache_creation_tokens), 0) AS input_tokens, "
    "COALESCE(SUM(output_tokens), 0) AS output_tokens, COALESCE(SUM(cost_usd), 0.0) AS cost_usd"
)

_LIVE_DOCUMENT_ITEMS = "FROM items i LEFT JOIN documents d ON d.id = i.doc_id WHERE d.deleted_at IS NULL"

#: The status of a reading's root span while the reading runs (never read into a ``TraceSpanRecord``).
_RUNNING = "running"
# a letter's kept readings, newest first: by the reading's number (its root span's ``reading``)
_TRACE_RUNS_TAIL = (
    f"WHERE doc_id = ? AND kind = 'run' AND status != '{_RUNNING}' "
    "ORDER BY CAST(json_extract(attributes, '$.reading') AS INTEGER) DESC, started_at DESC, id"
)


def _stale_readings(readings: Sequence[sqlite3.Row], keep: int, interrupted: frozenset[str]) -> list[str]:
    """The trace ids :meth:`Store.save_trace` deletes, of a letter's readings newest first."""
    finished = [row for row in readings if row["ended"] not in interrupted]
    stopped = [row for row in readings if row["ended"] in interrupted]
    kept = {row["trace_id"] for row in finished[:keep]}
    if stopped and (
        len(finished) < keep or (stopped[0]["reading"] or 0) > (finished[keep - 1]["reading"] or 0)
    ):
        kept.add(stopped[0]["trace_id"])
    return [row["trace_id"] for row in readings if row["trace_id"] not in kept]


_COUNT_QUERIES = {
    # letters only: a proof file belongs to its letter and is no letter of its own
    "documents": f"SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL AND source != '{PROOF_SOURCE}'",
    "trashed_documents": "SELECT COUNT(*) FROM documents WHERE deleted_at IS NOT NULL",
    "needs_review": (
        f"SELECT COUNT(*) FROM documents WHERE deleted_at IS NULL AND status = 'needs_review' "
        f"AND source != '{PROOF_SOURCE}'"
    ),
    "pages": "SELECT COUNT(*) FROM pages",
    "parties": "SELECT COUNT(*) FROM parties",
    "cases": "SELECT COUNT(*) FROM cases",
    "contracts": "SELECT COUNT(*) FROM contracts",
    "active_contracts": "SELECT COUNT(*) FROM contracts WHERE status = 'active'",
    "items": f"SELECT COUNT(*) {_LIVE_DOCUMENT_ITEMS}",
    "open_items": f"SELECT COUNT(*) {_LIVE_DOCUMENT_ITEMS} AND i.status = 'open'",
    "suggestions": "SELECT COUNT(*) FROM suggestions",
    "new_suggestions": "SELECT COUNT(*) FROM suggestions WHERE status = 'new'",
    "drafts": "SELECT COUNT(*) FROM drafts",
    "notes": "SELECT COUNT(*) FROM notes",
    "chat_messages": "SELECT COUNT(*) FROM chat_messages",
    "jobs": "SELECT COUNT(*) FROM jobs",
    "active_jobs": "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running', 'waiting')",
    "llm_calls": "SELECT COUNT(*) FROM llm_calls",
    "cache_entries": "SELECT COUNT(*) FROM llm_cache",
}


def _squash(value: float) -> float:
    """Map a non-negative relevance to ``[0, 1)`` keeping the order."""
    positive = max(0.0, float(value))
    return positive / (1.0 + positive)


def _add_due_range(where: _Where, start: str | None, end: str | None, include_undated: bool) -> None:
    bounds: list[str] = []
    params: list[str] = []
    if start is not None:
        bounds.append("i.due_date >= ?")
        params.append(start)
    if end is not None:
        bounds.append("i.due_date <= ?")
        params.append(end)
    if include_undated:
        if bounds:
            where.add(f"(i.due_date IS NULL OR ({' AND '.join(bounds)}))", *params)
        return
    where.add("i.due_date IS NOT NULL")
    for bound, param in zip(bounds, params, strict=True):
        where.add(bound, param)


def _unique(values: Iterable[T], key: Callable[[T], str]) -> list[T]:
    """``values`` without duplicates (and without empty keys), first occurrence wins."""
    seen: set[str] = set()
    result: list[T] = []
    for value in values:
        marker = key(value)
        if marker and marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _merged_party_fields(keep: Party, drop: Party) -> dict[str, Any]:
    keep_name = _name_key(keep.name)
    aliases = _unique(
        (alias for alias in (*keep.aliases, drop.name, *drop.aliases) if _name_key(alias) != keep_name),
        key=_name_key,
    )
    identifiers: list[Identifier] = _unique(
        (*keep.identifiers, *drop.identifiers), key=lambda identifier: normalize_identifier(identifier.value)
    )
    fields: dict[str, Any] = {
        "aliases": aliases,
        "identifiers": identifiers,
        "ibans": _unique((*keep.ibans, *drop.ibans), key=normalize_identifier),
    }
    for name in ("address", "email", "phone", "website", "notes", "region"):
        if getattr(keep, name) is None and getattr(drop, name) is not None:
            fields[name] = getattr(drop, name)
    if keep.kind == "other" and drop.kind != "other":
        fields["kind"] = drop.kind
    return fields
