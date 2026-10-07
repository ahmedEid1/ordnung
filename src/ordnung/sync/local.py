"""This computer's own sync state: ``<data>/sync/`` (design §5; never synced, never in a backup).

::

    <data>/sync/              0700
      state.json              0600  LocalState: written atomically (temp, fsync, replace, fsync folder)
      heads.json              0600  the last good plaintext of every head (finding 9; F14; GC's references)
      files.json              0600  hash cache: path → size, mtime_ns, inode, sha256 (finding 11)
      pull.json               0600  the pull journal: exists only while a pull is applied
      incoming/               0700  a pull's staging (the data folder's file system)
      kept/                   0700  kept copies (encrypted backups with the sync passphrase)

One writer at a time: every write of these files goes through one lock (the agent's threads, the CLI
under ``DataDirLock``). Every file operation goes through an :class:`~ordnung.sync.folder.FsOps`, so
the crash and power-cut tests cover this folder too.

The person-change counter is not here: it is the ``meta`` row :data:`~ordnung.sync.PERSON_META_KEY`,
moved inside the very transaction of each write the person made (:func:`ordnung.db.store.person_write`,
review finding 5a), so a snapshot of the database knows exactly which person changes it holds.
``state.json`` keeps the counter value the last push or pull accounted for (``pushed``).

The machine id (copied-folder check, F32) is ``/etc/machine-id`` (Linux), ``IOPlatformUUID`` (macOS) or
``MachineGuid`` (Windows); where none can be read, a random id stored once in the user's config folder
(finding 30 — ``uuid.getnode()`` may change at every start).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import unicodedata
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ordnung.calendar.secrets import KeyringSecrets
from ordnung.config import Paths
from ordnung.db.store import person_write
from ordnung.sync import (
    FILES_CACHE_FILE,
    HEADS_FILE,
    INCOMING_DIR,
    JOURNAL_FILE,
    KEPT_DIR,
    KEYRING_ACCOUNT,
    LOCAL_DIR,
    NAME_MAX_CHARS,
    STANDBY_MESSAGE,
    STATE_FILE,
    SYNC_FEATURE,
    SYNC_SECRET,
    SYNC_SERVICE,
)
from ordnung.sync.folder import PRIVATE_DIR_MODE, FsOps, RealFs
from ordnung.sync.model import FilesCacheEntry, Head, Journal, LocalState

#: The password store's "locked" answer for the sync passphrase (F25).
LOCKED_MESSAGE = "This computer's password store is locked. Unlock it, and Ordnung goes on by itself."
#: The keyring for the sync passphrase (``SecretStore``): service "Ordnung sync", sync's words.
SyncSecrets = partial(
    KeyringSecrets, service=SYNC_SERVICE, feature=SYNC_FEATURE, secret=SYNC_SECRET, locked=LOCKED_MESSAGE
)
#: Re-exported: the context in which a write counts as the person's (the gate, the watched folder, the CLI).
person_writes = person_write

STANDBY_HINT = "Run “ordnung sync use-here” to use it on this computer."
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_LOCK = threading.RLock()


def sync_dir(paths: Paths) -> Path:
    return paths.data_dir / LOCAL_DIR


def keyring_account(computer: str) -> str:
    return KEYRING_ACCOUNT.format(computer=computer)


def name_problem(name: str) -> str | None:
    """Why ``name`` can't be a computer's name (``None``: it can)."""
    cleaned = unicodedata.normalize("NFC", name).strip()
    if not cleaned:
        return "Give this computer a name, like “anna-laptop”."
    if len(cleaned) > NAME_MAX_CHARS:
        return f"Use a name of at most {NAME_MAX_CHARS} characters."
    if _CONTROL.search(cleaned):
        return "A computer's name can't contain control characters."
    return None


def clean_name(name: str) -> str:
    return unicodedata.normalize("NFC", name).strip()


def unique_name(name: str, taken: set[str]) -> str:
    """``name``, or ``name (2)``, ``name (3)`` … when another computer of the folder has it (finding 29)."""
    if name.casefold() not in {t.casefold() for t in taken}:
        return name
    number = 2
    while True:
        suffix = f" ({number})"
        candidate = name[: NAME_MAX_CHARS - len(suffix)] + suffix
        if candidate.casefold() not in {t.casefold() for t in taken}:
            return candidate
        number += 1


# --------------------------------------------------------------------------------------------------
# the machine id (F32, finding 30)
# --------------------------------------------------------------------------------------------------


def _read_machine_id() -> str | None:
    if sys.platform.startswith("linux"):
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            with contextlib.suppress(OSError):
                value = Path(path).read_text(encoding="ascii").strip()
                if value:
                    return value
    elif sys.platform == "darwin":
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            out = subprocess.run(
                ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            ).stdout
            match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
            if match:
                return match.group(1)
    elif sys.platform == "win32":
        with contextlib.suppress(OSError, ImportError):
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as key:  # type: ignore[attr-defined,unused-ignore]
                value, _kind = winreg.QueryValueEx(key, "MachineGuid")  # type: ignore[attr-defined,unused-ignore]
                if value:
                    return str(value)
    return None


def _stored_machine_id() -> str:
    from platformdirs import user_config_dir

    path = Path(user_config_dir("ordnung")) / "machine-id"
    with contextlib.suppress(OSError):
        value = path.read_text(encoding="ascii").strip()
        if re.fullmatch(r"[0-9a-f]{32}", value):
            return value
    value = secrets.token_hex(16)
    with contextlib.suppress(OSError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="ascii")
    return value


def machine_id() -> str:
    """This computer's id: the operating system's, else a random one stored once (finding 30)."""
    return _read_machine_id() or _stored_machine_id()


# --------------------------------------------------------------------------------------------------
# the files of <data>/sync/
# --------------------------------------------------------------------------------------------------


class Local:
    """``<data>/sync/`` of one data folder (module doc)."""

    def __init__(self, paths: Paths, fs: FsOps | None = None) -> None:
        self.paths = paths
        self.fs: FsOps = fs or RealFs()
        self.dir = sync_dir(paths)

    @property
    def state_path(self) -> Path:
        return self.dir / STATE_FILE

    @property
    def heads_path(self) -> Path:
        return self.dir / HEADS_FILE

    @property
    def files_path(self) -> Path:
        return self.dir / FILES_CACHE_FILE

    @property
    def journal_path(self) -> Path:
        return self.dir / JOURNAL_FILE

    @property
    def incoming(self) -> Path:
        return self.dir / INCOMING_DIR

    @property
    def kept_dir(self) -> Path:
        return self.dir / KEPT_DIR

    def ensure(self) -> None:
        for folder in (self.dir, self.kept_dir):
            with contextlib.suppress(FileExistsError):
                self.fs.mkdir(folder)
            if os.name == "posix":
                with contextlib.suppress(OSError):
                    folder.chmod(PRIVATE_DIR_MODE)

    def connected(self) -> bool:
        return self.state_path.is_file()

    # ---- reading and writing ---------------------------------------------------------------------

    def _read(self, path: Path) -> bytes | None:
        try:
            with self.fs.open_read(path) as handle:
                return handle.read()
        except FileNotFoundError:
            return None

    def write_atomic(self, path: Path, data: bytes) -> None:
        """``data`` into ``path``: a temp file, ``fsync``, rename, ``fsync`` of the folder."""
        with _LOCK:
            temp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.part")
            with contextlib.suppress(FileNotFoundError):
                self.fs.unlink(temp)
            handle = self.fs.open_new(temp)
            try:
                try:
                    handle.write(data)
                    self.fs.fsync(handle)
                finally:
                    handle.close()
                self.fs.replace(temp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    self.fs.unlink(temp)
                raise
            self.fs.fsync_dir(path.parent)

    def remove(self, path: Path) -> None:
        with _LOCK, contextlib.suppress(FileNotFoundError):
            self.fs.unlink(path)
            self.fs.fsync_dir(path.parent)

    def load(self) -> LocalState | None:
        raw = self._read(self.state_path)
        if raw is None:
            return None
        return LocalState.model_validate_json(raw)

    def save(self, state: LocalState) -> None:
        self.ensure()
        self.write_atomic(self.state_path, state.model_dump_json(indent=1).encode("utf-8"))

    def load_heads(self) -> dict[str, Head]:
        """The last good copy of every head (an unreadable cache counts as empty)."""
        raw = self._read(self.heads_path)
        if raw is None:
            return {}
        try:
            stored: dict[str, Any] = json.loads(raw)
            return {name: Head.model_validate(value) for name, value in stored.items()}
        except (ValueError, ValidationError):
            return {}

    def save_heads(self, heads: dict[str, Head]) -> None:
        payload = {name: head.model_dump(mode="json") for name, head in sorted(heads.items())}
        self.write_atomic(self.heads_path, json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def load_files(self) -> dict[str, FilesCacheEntry]:
        raw = self._read(self.files_path)
        if raw is None:
            return {}
        try:
            stored: dict[str, Any] = json.loads(raw)
            return {path: FilesCacheEntry.model_validate(value) for path, value in stored.items()}
        except (ValueError, ValidationError):
            return {}

    def save_files(self, files: dict[str, FilesCacheEntry]) -> None:
        payload = {path: entry.model_dump() for path, entry in sorted(files.items())}
        self.write_atomic(self.files_path, json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    def load_journal(self) -> Journal | None:
        raw = self._read(self.journal_path)
        if raw is None:
            return None
        return Journal.model_validate_json(raw)

    def save_journal(self, journal: Journal) -> None:
        self.write_atomic(self.journal_path, journal.model_dump_json().encode("utf-8"))

    def kept_files(self) -> Iterator[Path]:
        from ordnung.sync import KEPT_RE

        with contextlib.suppress(OSError):
            for name in sorted(self.fs.listdir(self.kept_dir)):
                if KEPT_RE.match(name):
                    yield self.kept_dir / name


# --------------------------------------------------------------------------------------------------
# for the CLI: refused while standing by (reads state.json only)
# --------------------------------------------------------------------------------------------------


def load_state(paths: Paths) -> LocalState | None:
    """``state.json`` of ``paths`` (``None``: not connected, or unreadable)."""
    try:
        return Local(paths).load()
    except (OSError, ValueError, ValidationError):
        return None


def writes_refused(paths: Paths) -> str | None:
    """Why a write on this computer must wait (``None``: it may go ahead): another computer is in use."""
    state = load_state(paths)
    if state is None or not state.complete or state.mode != "standing_by":
        return None
    return STANDBY_MESSAGE.format(name=in_use_on(paths, state) or "your other computer").replace(
        " Use it here first (Settings → Your computers).", ""
    )


def in_use_on(paths: Paths, state: LocalState) -> str | None:
    """The name of the computer in use, as this computer last saw it (from the heads cache)."""
    heads = Local(paths).load_heads()
    live = [h for h in heads.values() if h.state != "left" and h.computer != state.computer]
    if not live:
        return None
    holder = max(live, key=lambda h: (h.epoch, h.computer))
    return holder.name
