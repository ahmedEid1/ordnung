"""File systems that fail on purpose, for hand-off sync's crash, power-cut and hang tests (design §23.2).

* :class:`CrashingFs` writes exactly ``after_bytes`` bytes in all, or performs ``after_ops`` metadata
  operations, then raises :class:`SimulatedCrash` — and keeps raising: a crashed process cleans
  nothing up.
* :class:`PowerCutFs` keeps a durable shadow of the folders it watches: a file's durable content is what
  it held at its last ``fsync``; a new name, a rename or an unlink is durable once its folder was
  ``fsync``-ed. :meth:`PowerCutFs.cut` rebuilds the real folders from the shadow, dropping every write
  and rename that never reached the disk. SQLite's own files are left alone (their durability is
  SQLite's).
* :class:`CountingFs` counts what was written, by folder.
* :class:`HangingFs` blocks on chosen operations (a dead network share) until released.
"""

from __future__ import annotations

import errno
import itertools
import os
import shutil
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, BinaryIO

from ordnung.sync.folder import FsOps, RealFs


class SimulatedCrash(BaseException):
    """The process died here (a ``BaseException``: nothing handles it, as nothing would)."""


# --------------------------------------------------------------------------------------------------
# crashing
# --------------------------------------------------------------------------------------------------


class _CountingHandle:
    def __init__(self, handle: BinaryIO, owner: CrashingFs) -> None:
        self._handle = handle
        self._owner = owner

    def write(self, data: bytes) -> int:
        owner = self._owner
        owner._alive()
        if owner.after_bytes is not None and owner.bytes + len(data) > owner.after_bytes:
            room = owner.after_bytes - owner.bytes
            if room > 0:
                self._handle.write(data[:room])
                self._handle.flush()
            owner.bytes = owner.after_bytes
            owner.crashed = True
            raise SimulatedCrash(f"crash after {owner.after_bytes} bytes")
        owner.bytes += len(data)
        return self._handle.write(data)

    def read(self, size: int = -1) -> bytes:
        return self._handle.read(size)

    def flush(self) -> None:
        self._handle.flush()

    def fileno(self) -> int:
        return self._handle.fileno()

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> _CountingHandle:
        return self

    def __exit__(self, *exc: object) -> None:
        self._handle.close()

    @property
    def raw(self) -> BinaryIO:
        return self._handle


class CrashingFs:
    """:class:`~ordnung.sync.folder.FsOps` that crashes after ``after_bytes`` written or ``after_ops``
    metadata operations (``None``: never). ``ops`` and ``bytes`` count what happened (a dry run with
    neither limit tells how many there are to sample)."""

    def __init__(
        self, *, after_bytes: int | None = None, after_ops: int | None = None, inner: FsOps | None = None
    ) -> None:
        self.inner: FsOps = inner or RealFs()
        self.after_bytes = after_bytes
        self.after_ops = after_ops
        self.bytes = 0
        self.ops = 0
        self.crashed = False

    def _alive(self) -> None:
        if self.crashed:
            raise SimulatedCrash("the process is gone")

    def _op(self) -> None:
        self._alive()
        if self.after_ops is not None and self.ops >= self.after_ops:
            self.crashed = True
            raise SimulatedCrash(f"crash before operation {self.ops + 1}")
        self.ops += 1

    def open_new(self, path: Path) -> BinaryIO:
        self._op()
        return _CountingHandle(self.inner.open_new(path), self)  # type: ignore[return-value]

    def open_read(self, path: Path) -> BinaryIO:
        self._alive()
        return self.inner.open_read(path)

    def fsync(self, handle: BinaryIO) -> None:
        self._op()
        self.inner.fsync(handle.raw if isinstance(handle, _CountingHandle) else handle)

    def replace(self, src: Path, dst: Path) -> None:
        self._op()
        self.inner.replace(src, dst)

    def unlink(self, path: Path) -> None:
        self._op()
        self.inner.unlink(path)

    def fsync_dir(self, path: Path) -> None:
        self._op()
        self.inner.fsync_dir(path)

    def mkdir(self, path: Path) -> None:
        self._op()
        self.inner.mkdir(path)

    def rmdir(self, path: Path) -> None:
        self._op()
        self.inner.rmdir(path)

    def listdir(self, path: Path) -> list[str]:
        self._alive()
        return self.inner.listdir(path)

    def stat(self, path: Path) -> os.stat_result:
        self._alive()
        return self.inner.stat(path)


# --------------------------------------------------------------------------------------------------
# power cut
# --------------------------------------------------------------------------------------------------

_DIR = -1


def sqlite_file(path: Path) -> bool:
    return path.name.startswith("ordnung.db")


class _ShadowHandle:
    def __init__(self, handle: BinaryIO, path: Path, inode: int) -> None:
        self._handle = handle
        self.path = path
        self.inode = inode

    def write(self, data: bytes) -> int:
        return self._handle.write(data)

    def read(self, size: int = -1) -> bytes:
        return self._handle.read(size)

    def flush(self) -> None:
        self._handle.flush()

    def fileno(self) -> int:
        return self._handle.fileno()

    def close(self) -> None:
        self._handle.close()

    def __enter__(self) -> _ShadowHandle:
        return self

    def __exit__(self, *exc: object) -> None:
        self._handle.close()

    @property
    def raw(self) -> BinaryIO:
        return self._handle


class PowerCutFs:
    """:class:`~ordnung.sync.folder.FsOps` with a durable shadow of ``roots`` (module doc)."""

    def __init__(
        self, roots: Iterable[Path], *, inner: FsOps | None = None, skip: Callable[[Path], bool] = sqlite_file
    ) -> None:
        self.inner: FsOps = inner or RealFs()
        self.roots = [root.resolve() for root in roots]
        self.skip = skip
        self._ids = itertools.count(1)
        self.content: dict[int, bytes] = {}
        self.real: dict[Path, int] = {}
        self.durable: dict[Path, int] = {}
        for root in self.roots:
            self._adopt_tree(root)

    def _adopt_tree(self, root: Path) -> None:
        if not root.exists():
            return
        for current, dirs, names in os.walk(root):
            here = Path(current)
            for name in dirs:
                self.durable[here / name] = _DIR
            for name in names:
                path = here / name
                if self.skip(path):
                    continue
                inode = next(self._ids)
                self.content[inode] = path.read_bytes()
                self.real[path] = inode
                self.durable[path] = inode

    def _inside(self, path: Path) -> bool:
        return any(path == root or root in path.parents for root in self.roots)

    def open_new(self, path: Path) -> BinaryIO:
        handle = self.inner.open_new(path)
        inode = next(self._ids)
        self.real[path.resolve()] = inode
        return _ShadowHandle(handle, path.resolve(), inode)  # type: ignore[return-value]

    def open_read(self, path: Path) -> BinaryIO:
        return self.inner.open_read(path)

    def fsync(self, handle: BinaryIO) -> None:
        raw = handle.raw if isinstance(handle, _ShadowHandle) else handle
        self.inner.fsync(raw)
        if isinstance(handle, _ShadowHandle):
            handle.flush()
            current = next((p for p, i in self.real.items() if i == handle.inode), handle.path)
            self.content[handle.inode] = current.read_bytes()

    def replace(self, src: Path, dst: Path) -> None:
        self.inner.replace(src, dst)
        inode = self.real.pop(src.resolve(), None)
        if inode is None:
            inode = next(self._ids)  # written outside this seam: as durable as its bytes are now
            self.content[inode] = dst.read_bytes()
        self.real[dst.resolve()] = inode

    def unlink(self, path: Path) -> None:
        self.inner.unlink(path)
        self.real.pop(path.resolve(), None)

    def fsync_dir(self, path: Path) -> None:
        self.inner.fsync_dir(path)
        folder = path.resolve()
        listing = {folder / name for name in os.listdir(folder)}
        for gone in [p for p in self.durable if p.parent == folder and p not in listing]:
            self._forget(gone)
        for child in listing:
            if self.skip(child):
                continue
            if child.is_dir() and not child.is_symlink():
                self.durable[child] = _DIR
                continue
            inode = self.real.get(child)
            if inode is None:  # written outside this seam (with its own fsync): durable as it is
                inode = next(self._ids)
                self.content[inode] = child.read_bytes()
                self.real[child] = inode
            self.durable[child] = inode

    def _forget(self, path: Path) -> None:
        for other in [p for p in self.durable if p == path or path in p.parents]:
            del self.durable[other]

    def mkdir(self, path: Path) -> None:
        self.inner.mkdir(path)

    def rmdir(self, path: Path) -> None:
        self.inner.rmdir(path)

    def listdir(self, path: Path) -> list[str]:
        return self.inner.listdir(path)

    def stat(self, path: Path) -> os.stat_result:
        return self.inner.stat(path)

    def cut(self) -> None:
        """The power went out: only what was durable is left."""
        for root in self.roots:
            if not root.exists():
                continue
            for entry in sorted(root.iterdir()):
                self._wipe(entry)
            survivors = sorted(
                (p for p in self.durable if root in p.parents and self._chain_durable(p, root)),
                key=lambda p: len(p.parts),
            )
            for path in survivors:
                inode = self.durable[path]
                if inode == _DIR:
                    path.mkdir(exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(self.content.get(inode, b""))
        self.real = {p: i for p, i in self.durable.items() if i != _DIR and p.exists()}

    def _chain_durable(self, path: Path, root: Path) -> bool:
        parent = path.parent
        while parent != root:
            if self.durable.get(parent) != _DIR:
                return False
            parent = parent.parent
        return True

    def _wipe(self, entry: Path) -> None:
        if self.skip(entry):
            return
        if entry.is_dir() and not entry.is_symlink():
            for child in sorted(entry.iterdir()):
                self._wipe(child)
            if not any(entry.iterdir()):
                entry.rmdir()
        else:
            entry.unlink()


# --------------------------------------------------------------------------------------------------
# counting and hanging
# --------------------------------------------------------------------------------------------------


class CountingFs:
    """:class:`~ordnung.sync.folder.FsOps` that counts the bytes written into each folder."""

    def __init__(self, inner: FsOps | None = None) -> None:
        self.inner: FsOps = inner or RealFs()
        self.written: dict[Path, int] = {}
        self.files: list[Path] = []

    def reset(self) -> None:
        self.written.clear()
        self.files.clear()

    def total(self) -> int:
        return sum(self.written.values())

    def open_new(self, path: Path) -> BinaryIO:
        handle = self.inner.open_new(path)
        self.files.append(path)
        owner = self

        class Counted:
            def write(self, data: bytes) -> int:
                owner.written[path.parent] = owner.written.get(path.parent, 0) + len(data)
                return handle.write(data)

            def flush(self) -> None:
                handle.flush()

            def fileno(self) -> int:
                return handle.fileno()

            def close(self) -> None:
                handle.close()

            def __enter__(self) -> Any:
                return self

            def __exit__(self, *exc: object) -> None:
                handle.close()

            raw = handle

        return Counted()  # type: ignore[return-value]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def fsync(self, handle: BinaryIO) -> None:
        self.inner.fsync(getattr(handle, "raw", handle))


class HangingFs:
    """:class:`~ordnung.sync.folder.FsOps` whose ``hang`` operations block until :meth:`release`."""

    def __init__(self, hang: Iterable[str] = ("stat", "listdir"), inner: FsOps | None = None) -> None:
        self.inner: FsOps = inner or RealFs()
        self.hang = set(hang)
        self.released = threading.Event()

    def release(self) -> None:
        self.released.set()

    def __getattr__(self, name: str) -> Any:
        method = getattr(self.inner, name)
        if name not in self.hang:
            return method

        def blocked(*args: Any) -> Any:
            self.released.wait()
            return method(*args)

        return blocked


class FullFs(CrashingFs):
    """Like :class:`CrashingFs`, but the disk is full: ``OSError(ENOSPC)`` instead of a crash, and the
    process goes on (cleanup runs)."""

    def _alive(self) -> None:
        pass

    def _op(self) -> None:
        if self.after_ops is not None and self.ops >= self.after_ops:
            raise OSError(errno.ENOSPC, "No space left on device")
        self.ops += 1

    def open_new(self, path: Path) -> BinaryIO:
        self._op()
        handle = self.inner.open_new(path)
        owner = self

        class Full(_CountingHandle):
            def write(self, data: bytes) -> int:
                if owner.after_bytes is not None and owner.bytes + len(data) > owner.after_bytes:
                    raise OSError(errno.ENOSPC, "No space left on device")
                owner.bytes += len(data)
                return self._handle.write(data)

        return Full(handle, self)  # type: ignore[return-value]


class _Stat:
    """A stat result with the flags a dataless file has (Linux can't make one)."""

    def __init__(self, real: os.stat_result, flags: int) -> None:
        for name in ("st_mode", "st_size", "st_mtime_ns", "st_ino", "st_ctime_ns", "st_mtime"):
            setattr(self, name, getattr(real, name))
        self.st_flags = flags
        self.st_file_attributes = 0


class DatalessFs:
    """:class:`~ordnung.sync.folder.FsOps` that reports the paths in ``dataless`` as macOS dataless files
    (``SF_DATALESS``): real name and size, no data here; reading one fails as it would offline."""

    def __init__(self, dataless: set[Path], inner: FsOps | None = None) -> None:
        self.inner: FsOps = inner or RealFs()
        self.dataless = dataless

    def stat(self, path: Path) -> os.stat_result:
        real = self.inner.stat(path)
        if path.resolve() in self.dataless:
            return _Stat(real, 0x40000000)  # type: ignore[return-value]
        return real

    def open_read(self, path: Path) -> BinaryIO:
        if path.resolve() in self.dataless:
            raise OSError(35, "Resource deadlock avoided (the provider can't fetch it now)")
        return self.inner.open_read(path)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def copy_tree(source: Path, target: Path) -> None:
    """A copy of a folder (the person copying a data folder away and back)."""
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, symlinks=True)
