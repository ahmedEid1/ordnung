"""The sync folder on disk: every file operation, the folder's layout and the rules for choosing one
(design §4.1, §4.8-4.9; review findings 6, 7, 11, 22, 32).

**One file-system seam.** Every call goes through :class:`FsOps` (``open_new``, ``open_read``,
``fsync``, ``replace``, ``unlink``, ``fsync_dir``, ``mkdir``, ``rmdir``, ``listdir``, ``stat``):
:class:`RealFs` by default, a crashing or power-cut file system in tests (``tests/sync_faults.py``), the
same seam for placing a pull's files into the data folder. :class:`TimedFs` puts a deadline on every
operation (:data:`~ordnung.sync.FOLDER_OP_TIMEOUT_S`): a hung network share or a File Provider read
raises :class:`FolderUnreachable` instead of holding everything behind it. The hung call keeps its
thread; until it returns, every operation is unreachable at once (no second thread is started), and
then the same thread goes on.

**Writing** (:meth:`SyncFolder.write_object`, :meth:`SyncFolder.write_head`): a new temp file of this
computer's own pattern ``.<tag><random>.tmp`` (``O_EXCL``, ``0600``), written, ``fsync``-ed (``F_FULLFSYNC``
on macOS), renamed into place; the folders touched are ``fsync``-ed before a head names what is in
them. An object whose final name already has the expected size is not written again — unless forced
(another computer *wants* it: damaged or long missing there). A rename the sync tool blocks (Windows:
``PermissionError``) is retried :data:`REPLACE_TRIES` times, waiting up to 2 s.

**Reading** never trusts a name: only :data:`~ordnung.sync.KEY_FILE_RE`, :data:`~ordnung.sync.HEAD_RE`,
:data:`~ordnung.sync.SHARD_RE`, :data:`~ordnung.sync.OBJECT_RE` and :data:`~ordnung.sync.TEMP_RE` are
looked at, regular files only (symbolic links are ignored); everything else is ignored and never
deleted (conflict copies, ``.stfolder``, ``desktop.ini``, the person's own files). Folders the same way:
``h/``, ``o/`` and each ``o/<xx>/`` must be real folders — one that is a link (someone who can write the
folder made it, or a sync tool that carries links) is never listed, read, written or deleted through, so
nothing Ordnung does reaches outside the sync folder (:class:`LinkedFolder` when it would write). A file the sync tool
keeps online-only (a dataless file on macOS, a Windows recall-on-access placeholder, an ``.icloud``
sibling) has not arrived (:func:`online_only`).

**Choosing the folder** (:func:`folder_problem`, :func:`inspect`) follows the watched folder's rules:
an absolute path whose parent exists; never a drive root, the home folder, the data folder or the
watched folder (or inside or around them); a folder that can be written; empty apart from sync-tool
files, or an Ordnung sync folder. The data folder itself inside a synced folder is a warning
(:func:`data_folder_synced`): the sync tool would upload it unencrypted.
"""

from __future__ import annotations

import contextlib
import errno
import os
import queue
import secrets
import stat as stat_module
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Literal, Protocol, TypeVar

from ordnung import durable
from ordnung.config import Paths
from ordnung.models import AppSettings
from ordnung.sync import (
    FOLDER_OP_TIMEOUT_S,
    HEAD_RE,
    HEADS_DIR,
    KEY_FILE_BYTES,
    KEY_FILE_RE,
    MAX_RECORD_BYTES,
    OBJECT_RE,
    OBJECTS_DIR,
    SHARD_RE,
    TEMP_RE,
    SyncError,
)

T = TypeVar("T")

PRIVATE_FILE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700
REPLACE_TRIES = 5
REPLACE_MAX_WAIT_S = 2.0
#: macOS ``SF_DATALESS``: an evicted iCloud Drive / File Provider file (real name and size, no data)
SF_DATALESS = 0x40000000
#: Windows: a cloud placeholder whose data comes on access, or an offline file
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
_PLACEHOLDER_ATTRIBUTES = (
    FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)

#: Files sync tools keep in a folder they sync (a new sync folder may hold these).
TOOL_FILES: tuple[str, ...] = ("desktop.ini", ".DS_Store", "Icon\r", "Thumbs.db")
TOOL_PREFIXES: tuple[str, ...] = (
    ".stfolder",
    ".stignore",
    ".stversions",
    ".dropbox",
    ".sync",
    ".nextcloud",
    ".owncloud",
)
#: What says that a folder is synced (a marker in it, or its own name).
SYNCED_MARKERS: tuple[str, ...] = (
    ".stfolder",
    ".dropbox",
    ".dropbox.cache",
    ".nextcloudsync.log",
    ".owncloudsync.log",
)
SYNCED_NAMES: tuple[str, ...] = (
    "OneDrive",
    "Dropbox",
    "Nextcloud",
    "ownCloud",
    "iCloud Drive",
    "Google Drive",
)

UNREACHABLE_MESSAGE = (
    "The sync folder doesn't answer (a network drive or cloud folder that hangs). Ordnung keeps working "
    "here and tries again."
)


class FolderUnreachable(SyncError):
    """A folder operation didn't finish within :data:`~ordnung.sync.FOLDER_OP_TIMEOUT_S` (finding 22)."""

    def __init__(self, message: str = UNREACHABLE_MESSAGE) -> None:
        super().__init__("folder_problem", message)


# --------------------------------------------------------------------------------------------------
# the file-system seam
# --------------------------------------------------------------------------------------------------


class FsOps(Protocol):
    """Every file operation sync makes (design §4.8): the seam tests crash and cut power at."""

    def open_new(self, path: Path) -> BinaryIO:
        """A new file for writing bytes: exclusive create, ``0600``."""

    def open_read(self, path: Path) -> BinaryIO: ...

    def fsync(self, handle: BinaryIO) -> None: ...

    def replace(self, src: Path, dst: Path) -> None: ...

    def unlink(self, path: Path) -> None: ...

    def fsync_dir(self, path: Path) -> None: ...

    def mkdir(self, path: Path) -> None:
        """One folder, ``0700`` (its parent must exist)."""

    def rmdir(self, path: Path) -> None: ...

    def listdir(self, path: Path) -> list[str]: ...

    def stat(self, path: Path) -> os.stat_result:
        """``lstat``: a link is reported as a link, never followed."""


class RealFs:
    """:class:`FsOps` on the real file system."""

    def open_new(self, path: Path) -> BinaryIO:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        return os.fdopen(os.open(path, flags, PRIVATE_FILE_MODE), "wb")

    def open_read(self, path: Path) -> BinaryIO:
        return path.open("rb")

    def fsync(self, handle: BinaryIO) -> None:
        handle.flush()
        durable.fsync(handle.fileno())

    def replace(self, src: Path, dst: Path) -> None:
        wait = 0.1
        for attempt in range(REPLACE_TRIES):
            try:
                src.replace(dst)
                return
            except PermissionError:  # Windows: the sync tool (or a reader) holds the file — finding 32
                if attempt == REPLACE_TRIES - 1:
                    raise
                time.sleep(wait)
                wait = min(wait * 2, REPLACE_MAX_WAIT_S)

    def unlink(self, path: Path) -> None:
        path.unlink()

    def fsync_dir(self, path: Path) -> None:
        durable.fsync_dir(path)

    def mkdir(self, path: Path) -> None:
        path.mkdir(mode=PRIVATE_DIR_MODE)

    def rmdir(self, path: Path) -> None:
        path.rmdir()

    def listdir(self, path: Path) -> list[str]:
        return [entry.name for entry in path.iterdir()]

    def stat(self, path: Path) -> os.stat_result:
        return os.lstat(path)


class _Deadline:
    """Runs one call at a time on a worker thread and waits at most ``timeout`` for it. A call that
    hangs keeps the thread: until it returns, every call gives up at once, then the thread goes on."""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self._lock = threading.Lock()
        self._work: queue.Queue[tuple[Callable[[], Any], _Result]] | None = None
        self._stuck: _Result | None = None  # the call that timed out, until it returns

    def _worker(self) -> queue.Queue[tuple[Callable[[], Any], _Result]]:
        if self._work is None:
            work: queue.Queue[tuple[Callable[[], Any], _Result]] = queue.Queue()

            def loop() -> None:
                while True:
                    call, result = work.get()
                    try:
                        result.value = call()
                    except BaseException as exc:  # handed to the caller
                        result.error = exc
                    result.done.set()

            threading.Thread(target=loop, name="ordnung-sync-folder", daemon=True).start()
            self._work = work
        return self._work

    def run(self, call: Callable[[], T]) -> T:
        with self._lock:
            if self._stuck is not None:
                if not self._stuck.done.is_set():
                    raise FolderUnreachable()  # still hangs: nothing waits behind it, no second thread
                self._stuck = None
            result = _Result()
            self._worker().put((call, result))
            if not result.done.wait(self.timeout):
                self._stuck = result
                raise FolderUnreachable()
        if result.error is not None:
            raise result.error
        return result.value


@dataclass
class _Result:
    done: threading.Event = field(default_factory=threading.Event)
    value: Any = None
    error: BaseException | None = None


class _TimedHandle:
    """A file handle whose reads and writes go through a :class:`_Deadline`."""

    def __init__(self, handle: BinaryIO, deadline: _Deadline) -> None:
        self._handle = handle
        self._deadline = deadline

    def read(self, size: int = -1) -> bytes:
        return self._deadline.run(lambda: self._handle.read(size))

    def write(self, data: bytes) -> int:
        return self._deadline.run(lambda: self._handle.write(data))

    def flush(self) -> None:
        self._deadline.run(self._handle.flush)

    def fileno(self) -> int:
        return self._handle.fileno()

    def close(self) -> None:
        self._deadline.run(self._handle.close)

    def __enter__(self) -> _TimedHandle:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def raw(self) -> BinaryIO:
        return self._handle


class TimedFs:
    """:class:`FsOps` with a deadline on every operation (finding 22): :class:`FolderUnreachable`."""

    def __init__(self, inner: FsOps | None = None, timeout: float = FOLDER_OP_TIMEOUT_S) -> None:
        self.inner: FsOps = inner or RealFs()
        self._deadline = _Deadline(timeout)

    def open_new(self, path: Path) -> BinaryIO:
        handle = self._deadline.run(lambda: self.inner.open_new(path))
        return _TimedHandle(handle, self._deadline)  # type: ignore[return-value]

    def open_read(self, path: Path) -> BinaryIO:
        handle = self._deadline.run(lambda: self.inner.open_read(path))
        return _TimedHandle(handle, self._deadline)  # type: ignore[return-value]

    def fsync(self, handle: BinaryIO) -> None:
        inner = handle.raw if isinstance(handle, _TimedHandle) else handle
        self._deadline.run(lambda: self.inner.fsync(inner))

    def replace(self, src: Path, dst: Path) -> None:
        self._deadline.run(lambda: self.inner.replace(src, dst))

    def unlink(self, path: Path) -> None:
        self._deadline.run(lambda: self.inner.unlink(path))

    def fsync_dir(self, path: Path) -> None:
        self._deadline.run(lambda: self.inner.fsync_dir(path))

    def mkdir(self, path: Path) -> None:
        self._deadline.run(lambda: self.inner.mkdir(path))

    def rmdir(self, path: Path) -> None:
        self._deadline.run(lambda: self.inner.rmdir(path))

    def listdir(self, path: Path) -> list[str]:
        return self._deadline.run(lambda: self.inner.listdir(path))

    def stat(self, path: Path) -> os.stat_result:
        return self._deadline.run(lambda: self.inner.stat(path))


FULL_MESSAGE = "The sync folder (or the drive or account it is on) is full. Ordnung tries again later."


class FolderFull(SyncError):
    """ENOSPC or EDQUOT while writing into the sync folder (F30; the problem ``folder_full``)."""

    def __init__(self, message: str = FULL_MESSAGE) -> None:
        super().__init__("folder_problem", message)


LINKED_MESSAGE = (
    "Part of the sync folder (h/ or o/) is a link to another place, so Ordnung doesn't write through it. "
    "Remove that link from the sync folder."
)
#: How long a folder checked to be a real folder (not a link) is believed when only reading.
DIR_CHECK_S = 2.0


class LinkedFolder(SyncError):
    """A folder of the sync folder's layout is a link (module doc): nothing is written through it."""

    def __init__(self, message: str = LINKED_MESSAGE) -> None:
        super().__init__("folder_problem", message)


def _raise_if_full(exc: OSError) -> None:
    if exc.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)):
        raise FolderFull() from exc


def online_only(info: os.stat_result) -> bool:
    """The sync tool keeps this file online-only here (its data isn't on this computer): a dataless
    file (macOS iCloud Drive and File Provider clouds) or a Windows placeholder (finding 6)."""
    if getattr(info, "st_flags", 0) & SF_DATALESS:
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _PLACEHOLDER_ATTRIBUTES)


def _missing(exc: OSError) -> bool:
    return isinstance(exc, FileNotFoundError | NotADirectoryError)


# --------------------------------------------------------------------------------------------------
# the folder
# --------------------------------------------------------------------------------------------------

#: What a sealed object looks like in its shard: its size, and whether its data is here at all.
ObjectState = Literal["here", "online_only"]


@dataclass(frozen=True)
class FileInfo:
    size: int
    mtime_ns: int
    ino: int
    ctime_ns: int
    online_only: bool

    @classmethod
    def of(cls, info: os.stat_result) -> FileInfo:
        return cls(info.st_size, info.st_mtime_ns, info.st_ino, info.st_ctime_ns, online_only(info))

    @property
    def signature(self) -> tuple[int, int, int, int]:
        """What says the file is unchanged (finding 9: the inode and ctime too)."""
        return (self.size, self.mtime_ns, self.ino, self.ctime_ns)


class SyncFolder:
    """The sync folder the person chose, as this computer sees it (module doc)."""

    def __init__(self, root: Path, fs: FsOps | None = None, *, tag: str = "00000000") -> None:
        self.root = root
        self.fs: FsOps = fs or RealFs()
        #: this computer's temp-file tag (``Vault.temp_tag``): the only temp files it ever removes
        self.tag = tag
        self._touched: set[Path] = set()
        #: folders checked to be real folders, until when (monotonic) — reading only
        self._real: dict[Path, float] = {}

    # ---- layout -----------------------------------------------------------------------------------

    @property
    def heads_dir(self) -> Path:
        return self.root / HEADS_DIR

    @property
    def objects_dir(self) -> Path:
        return self.root / OBJECTS_DIR

    def object_path(self, name: str) -> Path:
        return self.objects_dir / name[:2] / name[2:]

    def head_path(self, name: str) -> Path:
        return self.heads_dir / name

    def _temp_name(self) -> str:
        return f".{self.tag}{secrets.token_hex(4)}.tmp"

    def _regular(self, path: Path) -> FileInfo | None:
        try:
            info = self.fs.stat(path)
        except OSError as exc:
            if _missing(exc):
                return None
            raise
        if not stat_module.S_ISREG(info.st_mode):
            return None
        return FileInfo.of(info)

    def _is_real_dir(self, folder: Path) -> bool:
        try:
            info = self.fs.stat(folder)
        except OSError as exc:
            if _missing(exc):
                return False
            raise
        return stat_module.S_ISDIR(info.st_mode)

    def _inside(self, folder: Path, *, fresh: bool = False) -> bool:
        """``folder`` and every folder between it and the root are real folders, never links (module
        doc). ``fresh``: checked now (before writing or deleting); else a check of the last
        :data:`DIR_CHECK_S` stands (reading)."""
        try:
            parts = folder.relative_to(self.root).parts
        except ValueError:
            return False
        current = self.root
        now = time.monotonic()
        for part in parts:
            current = current / part
            if not fresh and self._real.get(current, 0.0) > now:
                continue
            if not self._is_real_dir(current):
                self._real.pop(current, None)
                return False
            self._real[current] = now + DIR_CHECK_S
        return True

    def _writable(self, folder: Path) -> None:
        if folder != self.root and not self._inside(folder, fresh=True):
            raise LinkedFolder()

    def is_dir(self) -> bool:
        try:
            info = self.fs.stat(self.root)
        except OSError as exc:
            if _missing(exc):
                return False
            raise
        return stat_module.S_ISDIR(info.st_mode)

    def _names(self, folder: Path) -> list[str]:
        if folder != self.root and not self._inside(folder):
            return []  # missing, or a link: never listed through
        try:
            return sorted(self.fs.listdir(folder))
        except OSError as exc:
            if _missing(exc):
                return []
            raise

    def key_files(self) -> dict[str, FileInfo]:
        """The key files at the root (regular files named like one), by name."""
        found: dict[str, FileInfo] = {}
        for name in self._names(self.root):
            if KEY_FILE_RE.match(name):
                info = self._regular(self.root / name)
                if info is not None:
                    found[name] = info
        return found

    def has_any_of_ours(self) -> bool:
        """Anything at the root that Ordnung writes (a key file, ``h/``, ``o/``, a temp file)."""
        return any(
            KEY_FILE_RE.match(name) or TEMP_RE.match(name) or name in (HEADS_DIR, OBJECTS_DIR)
            for name in self._names(self.root)
        )

    def read_bytes(self, path: Path, limit: int = MAX_RECORD_BYTES) -> bytes | None:
        """The bytes of ``path`` (``None``: missing, not a regular file, online-only or over ``limit``)."""
        if path.parent != self.root and not self._inside(path.parent):
            return None
        info = self._regular(path)
        if info is None or info.online_only or info.size > limit:
            return None
        try:
            with self.fs.open_read(path) as handle:
                data = handle.read(limit + 1)
        except OSError as exc:
            if _missing(exc):
                return None
            raise
        return None if len(data) > limit else data

    def read_key_file(self, name: str) -> bytes | None:
        return self.read_bytes(self.root / name, KEY_FILE_BYTES * 4)

    def create_key_file(self, name: str, data: bytes) -> None:
        """Write the key file (only when creating the folder or filling it again), then ``h/`` and ``o/``."""
        self._atomic(self.root, name, lambda out: out.write(data), replace_existing=False)
        self.fs.fsync_dir(self.root)
        self.make_dirs()

    def make_dirs(self) -> None:
        """``h/`` and ``o/`` — only next to a key file, and never under a missing folder (F26)."""
        for folder in (self.heads_dir, self.objects_dir):
            try:
                self.fs.mkdir(folder)
            except FileExistsError:
                self._writable(folder)  # there already: a real folder, never a link
                continue
        self.fs.fsync_dir(self.root)

    def _atomic(
        self, folder: Path, name: str, produce: Callable[[BinaryIO], object], *, replace_existing: bool = True
    ) -> None:
        self._writable(folder)
        temp = folder / self._temp_name()
        try:
            handle = self.fs.open_new(temp)
        except OSError as exc:
            _raise_if_full(exc)
            raise
        try:
            try:
                produce(handle)
                self.fs.fsync(handle)
            finally:
                handle.close()
            if not replace_existing and self._regular(folder / name) is not None:
                raise FileExistsError(folder / name)
            self.fs.replace(temp, folder / name)
        except BaseException as exc:
            with contextlib.suppress(OSError):
                self.fs.unlink(temp)
            if isinstance(exc, OSError):
                _raise_if_full(exc)
            raise
        self._touched.add(folder)

    # ---- heads ------------------------------------------------------------------------------------

    def head_files(self) -> dict[str, FileInfo]:
        found: dict[str, FileInfo] = {}
        for name in self._names(self.heads_dir):
            if HEAD_RE.match(name):
                info = self._regular(self.heads_dir / name)
                if info is not None:
                    found[name] = info
        return found

    def read_head(self, name: str) -> bytes | None:
        return self.read_bytes(self.head_path(name))

    def write_head(self, name: str, sealed: bytes) -> None:
        """Rewrite this computer's head: the commit point of a push (``h/`` is synced at once)."""
        self.flush()  # everything the head names is durable first (I4)
        self._atomic(self.heads_dir, name, lambda out: out.write(sealed))
        self.fs.fsync_dir(self.heads_dir)
        self._touched.discard(self.heads_dir)

    # ---- objects ----------------------------------------------------------------------------------

    def object_info(self, name: str) -> FileInfo | None:
        path = self.object_path(name)
        if not self._inside(path.parent):
            return None
        info = self._regular(path)
        if info is None and self._regular(path.with_name(f".{path.name}.icloud")) is not None:
            return FileInfo(0, 0, 0, 0, True)  # an older iCloud Drive placeholder
        return info

    def shard(self, prefix: str) -> dict[str, FileInfo]:
        """The objects of one shard ``o/<prefix>/`` by full name (one listing; finding 7). An older
        iCloud Drive placeholder (``.<rest>.icloud`` instead of the file) is listed as online-only."""
        found: dict[str, FileInfo] = {}
        folder = self.objects_dir / prefix
        for rest in self._names(folder):
            if OBJECT_RE.match(rest):
                info = self._regular(folder / rest)
                if info is not None:
                    found[prefix + rest] = info
            elif rest.startswith(".") and rest.endswith(".icloud") and OBJECT_RE.match(rest[1:-7]):
                found.setdefault(prefix + rest[1:-7], FileInfo(0, 0, 0, 0, True))
        return found

    def shard_names(self) -> list[str]:
        return [
            name
            for name in self._names(self.objects_dir)
            if SHARD_RE.match(name) and self._inside(self.objects_dir / name)
        ]

    def write_object(
        self, name: str, size: int, produce: Callable[[BinaryIO], object], *, force: bool = False
    ) -> bool:
        """Write the object ``name`` (``size`` sealed bytes) unless it is already there with that size
        (``force``: replace it anyway — it is damaged elsewhere). True when it was written."""
        if not force:
            info = self.object_info(name)
            if info is not None and info.size == size and not info.online_only:
                return False
        shard = self.objects_dir / name[:2]
        self._writable(self.objects_dir)  # never a shard made inside a link
        try:
            self.fs.mkdir(shard)
            self._touched.add(self.objects_dir)
        except FileExistsError:
            pass
        self._atomic(shard, name[2:], produce)
        return True

    def open_object(self, name: str) -> BinaryIO:
        path = self.object_path(name)
        if not self._inside(path.parent):
            raise FileNotFoundError(path)
        return self.fs.open_read(path)

    def delete_object(self, name: str) -> None:
        if not OBJECT_RE.match(name[2:]) or not SHARD_RE.match(name[:2]):
            raise ValueError("not an object name")
        path = self.object_path(name)
        if not self._inside(path.parent, fresh=True):
            return  # a link: nothing is deleted through it
        with contextlib.suppress(FileNotFoundError):
            self.fs.unlink(path)
            self._touched.add(path.parent)

    def flush(self) -> None:
        """``fsync`` every folder written into since the last flush (before a head names its content)."""
        for folder in sorted(self._touched, key=lambda p: len(p.parts), reverse=True):
            self.fs.fsync_dir(folder)
        self._touched.clear()

    # ---- temp files -------------------------------------------------------------------------------

    def temp_files(self) -> Iterator[Path]:
        """Every temp file of Ordnung's pattern in the folder (any writer's)."""
        shards = [self.objects_dir / s for s in self.shard_names()]
        folders = [self.root, self.heads_dir, self.objects_dir, *shards]
        for folder in folders:
            for name in self._names(folder):
                if TEMP_RE.match(name):
                    yield folder / name

    def remove_temps(self, tag: str | None = None) -> int:
        """Remove the temp files of writer ``tag`` (default: this computer's own; I7, I9)."""
        mine = tag or self.tag
        removed = 0
        for path in list(self.temp_files()):
            if path.name[1:9] == mine and (path.parent == self.root or self._inside(path.parent, fresh=True)):
                with contextlib.suppress(FileNotFoundError):
                    self.fs.unlink(path)
                    removed += 1
        return removed

    def unlink_head(self, name: str) -> None:
        if not self._inside(self.heads_dir, fresh=True):
            return
        with contextlib.suppress(FileNotFoundError):
            self.fs.unlink(self.head_path(name))
        self.fs.fsync_dir(self.heads_dir)

    def unlink_key_file(self, name: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.fs.unlink(self.root / name)
        self.fs.fsync_dir(self.root)


# --------------------------------------------------------------------------------------------------
# choosing the folder (§4.9)
# --------------------------------------------------------------------------------------------------


def _is_tool_file(name: str) -> bool:
    return name in TOOL_FILES or name.startswith(TOOL_PREFIXES)


def _is_ours(name: str) -> bool:
    return bool(KEY_FILE_RE.match(name) or TEMP_RE.match(name)) or name in (HEADS_DIR, OBJECTS_DIR)


@dataclass(frozen=True)
class FolderInfo:
    """What a folder would be for sync (design §4.9, ``POST /api/sync/inspect``)."""

    kind: Literal["new", "existing", "refused"]
    folder: str
    problem: str | None = None
    examples: tuple[str, ...] = ()
    data_folder_synced: bool = False
    links_left_out: tuple[str, ...] = ()
    key_file: str | None = None


def data_folder_synced(data_dir: Path) -> bool:
    """Ordnung's data folder itself sits inside a folder a sync tool uploads (it would go unencrypted)."""
    try:
        here = data_dir.resolve()
    except OSError:
        return False
    for folder in (here, *here.parents):
        if folder.name in SYNCED_NAMES or folder.name.startswith(("OneDrive -", "Dropbox (")):
            return True
        if folder.name == "Mobile Documents" and folder.parent.name == "Library":
            return True
        for marker in SYNCED_MARKERS:
            with contextlib.suppress(OSError):
                if (folder / marker).exists():
                    return True
    return False


def _resolved(value: str) -> Path | None:
    folder = Path(value).expanduser()
    if not folder.is_absolute():
        return None
    return folder.resolve()


def _around(folder: Path, other: Path) -> bool:
    """``folder`` is ``other``, inside it, or contains it."""
    return folder == other or folder.is_relative_to(other) or other.is_relative_to(folder)


def folder_problem(value: str, paths: Paths, settings: AppSettings | None = None) -> str | None:
    """Why ``value`` can't be the sync folder (``None``: it can). Nothing is written but one probe
    file of Ordnung's own temp pattern, removed at once."""
    folder = _resolved(value)
    if folder is None:
        return "Please choose a full folder path, like /home/you/Nextcloud/Vault."
    if folder == Path(folder.anchor):
        return "The sync folder can't be the root of a drive. Choose a new folder inside your synced folder."
    if folder == Path.home().resolve():
        return "The sync folder can't be your whole home folder. Choose a new, empty folder."
    if _around(folder, paths.data_dir.resolve()):
        return "The sync folder can't be Ordnung's data folder, a folder inside it, or a folder that contains it."
    watched = settings.inbox_dir if settings is not None else None
    if watched and _around(folder, Path(watched).expanduser().resolve()):
        return (
            "The sync folder can't be your watched folder, a folder inside it, or a folder that contains it."
        )
    if not folder.parent.is_dir():
        return f"The folder {folder.parent} doesn't exist — is the drive connected?"
    if folder.exists() and not folder.is_dir():
        return f"{folder} is a file, not a folder."
    if folder.is_dir():
        others = [
            name
            for name in sorted(entry.name for entry in folder.iterdir())
            if not (_is_tool_file(name) or _is_ours(name))
        ]
        if others:
            shown = ", ".join(f"“{name}”" for name in others[:1])
            more = f" and {len(others) - 1} more" if len(others) > 1 else ""
            return (
                f"This folder has other files in it ({shown}{more}). Choose a new, empty folder, like "
                f"{folder.parent / 'Vault'}."
            )
    probe_in = folder if folder.is_dir() else folder.parent
    probe = probe_in / f".{secrets.token_hex(8)}.tmp"
    try:
        os.close(os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE))
        probe.unlink()
    except OSError:
        return f"Ordnung can't write into {probe_in}."
    return None


def _examples(folder: Path) -> tuple[str, ...]:
    if not folder.is_dir():
        return ()
    return tuple(
        name
        for name in sorted(entry.name for entry in folder.iterdir())
        if not (_is_tool_file(name) or _is_ours(name))
    )[:3]


def inspect(value: str, paths: Paths, settings: AppSettings | None = None) -> FolderInfo:
    """``new`` (missing, or empty apart from sync-tool files), ``existing`` (one Ordnung key file) or
    ``refused`` (and why); plus the synced-data-folder warning and the links a sync leaves out."""
    from ordnung.backup.archive import links_left_out

    synced = data_folder_synced(paths.data_dir)
    links = tuple(links_left_out(paths.data_dir))
    resolved = _resolved(value)
    shown = str(resolved) if resolved is not None else value
    problem = folder_problem(value, paths, settings)
    if problem is not None or resolved is None:
        examples = _examples(resolved) if resolved is not None else ()
        return FolderInfo("refused", shown, problem, examples, synced, links)
    keys = sorted(SyncFolder(resolved).key_files()) if resolved.is_dir() else []
    if len(keys) > 1:
        return FolderInfo(
            "refused",
            shown,
            "This folder holds two separate Ordnung syncs (two computers set one up at the same moment). "
            "Wait a minute and try again.",
            (),
            synced,
            links,
        )
    if keys:
        return FolderInfo("existing", shown, None, (), synced, links, keys[0])
    return FolderInfo("new", shown, None, (), synced, links)
