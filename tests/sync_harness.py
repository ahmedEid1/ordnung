"""Computers for hand-off sync's tests (design §23.2): a data folder each, an in-memory password store,
clocks of their own, and the real engine; plus :class:`FakeEngine`, a small stand-in for the engine's
façade that the server's tests (P2) can drive without a folder.

A :class:`Computer` writes the person's changes (:meth:`Computer.person_edit`, :meth:`Computer.add_letter`
— inside :func:`ordnung.db.store.person_write`, as the server's gate does) and background changes
(:meth:`Computer.background_edit`: a cache row, the day rolled forward — outside it). Each computer's
view of the sync folder is its own directory; :class:`sync_sim.SyncToolSim` moves files between them.
"""

from __future__ import annotations

import hashlib
import os
import secrets as tokens
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fakes import MemorySecrets
from ordnung.config import Paths
from ordnung.db.store import Store, person_write
from ordnung.sync import engine
from ordnung.sync.engine import Clock, ConnectResult, Outcome, Session
from ordnung.sync.folder import FsOps, RealFs

#: A passphrase that passes a new folder's rule (five unrelated words).
PASSPHRASE = "orbit velvet canyon maple thunder"


class FakeClock:
    """A wall clock (shown only) and a monotonic clock (patience, running time), moved by hand."""

    def __init__(self, start: datetime | None = None, *, skew: timedelta = timedelta()) -> None:
        self.now = (start or datetime(2026, 10, 7, 9, 0, tzinfo=timezone(timedelta(hours=2)))) + skew
        self.mono = 1000.0

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        self.mono += seconds

    def jump_wall(self, delta: timedelta) -> None:
        """The wall clock jumps (NTP, a person setting it); the monotonic clock doesn't."""
        self.now += delta

    def clock(self) -> Clock:
        return Clock(wall=lambda: self.now, monotonic=lambda: self.mono)


def write_original(paths: Paths, data: bytes, ext: str = "pdf") -> tuple[str, str]:
    """An original under ``files/`` named by its SHA-256, as intake stores it."""
    sha = hashlib.sha256(data).hexdigest()
    relative = f"files/{sha[:2]}/{sha}.{ext}"
    target = paths.data_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return sha, relative


@dataclass
class Computer:
    """One computer: its data folder, password store, clocks and (once connected) its session."""

    name: str
    root: Path
    folder: Path
    clock: FakeClock = field(default_factory=FakeClock)
    secrets: MemorySecrets = field(default_factory=MemorySecrets)
    machine: str = field(default_factory=lambda: tokens.token_hex(16))
    folder_fs: FsOps = field(default_factory=RealFs)
    data_fs: FsOps = field(default_factory=RealFs)
    session: Session | None = None
    store: Store | None = None

    def __post_init__(self) -> None:
        self.paths = Paths(self.root / "data").ensure()
        self.store = Store.open(self.paths)

    # ---- lifecycle ----------------------------------------------------------------------------------

    @property
    def db(self) -> Store:
        assert self.store is not None
        return self.store

    @property
    def s(self) -> Session:
        assert self.session is not None, f"{self.name} isn't connected"
        return self.session

    def close(self) -> None:
        if self.store is not None:
            self.store.close()
            self.store = None

    def connect(
        self, passphrase: str = PASSPHRASE, *, keep: Any = None, name: str | None = None
    ) -> ConnectResult:
        result = engine.connect(
            self.paths,
            self.folder,
            name or self.name,
            passphrase,
            secrets=self.secrets,
            store=self.db,
            keep=keep,
            clock=self.clock.clock(),
            folder_fs=self.folder_fs,
            data_fs=self.data_fs,
            machine=lambda: self.machine,
        )
        if result.session is not None:
            self.session = result.session
        return result

    def restart(
        self, *, folder_fs: FsOps | None = None, data_fs: FsOps | None = None
    ) -> engine.Problem | None:
        """Ordnung stops and starts again here: a fresh Store and session from disk, a resumed pull."""
        self.close()
        if folder_fs is not None:
            self.folder_fs = folder_fs
        if data_fs is not None:
            self.data_fs = data_fs
        engine.resume_interrupted(self.paths, fs=self.data_fs)
        self.store = Store.open(self.paths)
        self.session = Session.open(
            self.paths,
            self.secrets,
            clock=self.clock.clock(),
            folder_fs=self.folder_fs,
            data_fs=self.data_fs,
            machine=lambda: self.machine,
        )
        return self.session.start(self.db)

    # ---- writes -------------------------------------------------------------------------------------

    def person_edit(self, text: str | None = None) -> str:
        """A change the person made (a note), counted as one."""
        with person_write():
            note = self.db.add_note(text or f"note {tokens.token_hex(4)}")
        return note.id

    def add_letter(self, title: str | None = None, *, size: int = 6000) -> str:
        """The person adds a letter: its original, one page image, a thumbnail, its rows."""
        data = b"%PDF-1.7\n" + os.urandom(size)
        sha, relative = write_original(self.paths, data)
        with person_write():
            document = self.db.add_document(
                sha256=sha, filename=f"{title or 'letter'}.pdf", mime="application/pdf", file_path=relative
            )
            self.db.update_document(document.id, title=title or f"Letter {sha[:6]}")
        derived = self.paths.derived / document.id
        derived.mkdir(parents=True, exist_ok=True)
        (derived / "page-1.jpg").write_bytes(b"\xff\xd8" + os.urandom(3000))
        (derived / "thumb.jpg").write_bytes(b"\xff\xd8" + os.urandom(800))
        with person_write():
            self.db.set_pages(
                document.id,
                [
                    {
                        "page": 1,
                        "width": 800,
                        "height": 1131,
                        "image_path": f"derived/{document.id}/page-1.jpg",
                        "text": "Sehr geehrte",
                    }
                ],
            )
        return document.id

    def delete_letter(self, doc_id: str) -> None:
        with person_write():
            self.db.delete_document(doc_id, purge_files=True)

    def background_edit(self, tag: str | None = None) -> None:
        """Work the computer did by itself (a cache row, the day rolled forward): not the person's."""
        self.db.set_meta("last_tick_date", tag or f"2026-10-{tokens.randbelow(28) + 1:02d}")
        self.db.cache_put(f"key-{tokens.token_hex(4)}", "extract", "model", {"ok": True})

    def notes(self) -> set[str]:
        return {row["text"] for row in self.db._conn().execute("SELECT text FROM notes")}

    def letters(self) -> set[str]:
        return {row["id"] for row in self.db._conn().execute("SELECT id FROM documents")}

    # ---- sync ---------------------------------------------------------------------------------------

    def round(self) -> Outcome:
        return self.s.round(self.db)

    def use_here(self, **options: Any) -> Outcome:
        return self.s.use_here(self.db, **options)

    def choose(self, key: int) -> Outcome:
        return self.s.choose(self.db, key)

    def key_of(self, other: Computer) -> int:
        view = self.s.scan()
        head = view.by_computer(other.s.state.computer)
        assert head is not None, f"{self.name} doesn't see {other.name}"
        return head.key

    @property
    def mode(self) -> str:
        return self.s.state.mode


# --------------------------------------------------------------------------------------------------
# FakeEngine: the façade without a folder (for the server's tests)
# --------------------------------------------------------------------------------------------------


@dataclass
class FakeEngine:
    """A stand-in for :mod:`ordnung.sync.engine` that keeps everything in memory and records calls.

    It implements the façade's shape (I2): ``connect``, ``round``, ``use_here``, ``choose``, ``save``,
    ``leave``, ``close``; ``mode`` and ``problem`` steer what it answers, ``calls`` records what was
    asked. Nothing unverified is ever "applied": :meth:`use_here` only switches the mode when
    ``arrived`` is set (I2)."""

    mode: str = "off"
    problem: str | None = None
    arrived: bool = True
    choice: list[str] | None = None
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    saved: int = 0

    def _call(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))

    def connect(self, folder: str, name: str, passphrase: str, keep: str | None = None) -> str:
        self._call("connect", folder=folder, name=name, keep=keep)
        if self.choice and keep is None:
            return "choice"
        self.mode = "in_use"
        return self.mode

    def round(self) -> str:
        self._call("round")
        return self.mode

    def use_here(self, older_copy: bool = False) -> str:
        self._call("use_here", older_copy=older_copy)
        if self.choice:
            return "choice"
        if not self.arrived and not older_copy:
            return "waiting"
        self.mode = "in_use"
        return self.mode

    def choose(self, key: int) -> str:
        self._call("choose", key=key)
        self.choice = None
        self.mode = "in_use"
        return self.mode

    def save(self, hand_over: bool = False) -> str:
        self._call("save", hand_over=hand_over)
        self.saved += 1
        if hand_over:
            self.mode = "standing_by"
        return self.mode

    def leave(self, unreceived_ok: bool = False) -> str:
        self._call("leave", unreceived_ok=unreceived_ok)
        self.mode = "off"
        return self.mode

    def close(self) -> None:
        self._call("close")


@contextmanager
def computers(tmp: Path, *names: str) -> Iterator[list[Computer]]:
    made = [Computer(name, tmp / name, tmp / f"{name}-sync") for name in names]
    try:
        yield made
    finally:
        for computer in made:
            computer.close()
