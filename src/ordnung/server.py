"""The running server's discovery file ``<data>/server.json`` (SPEC §13, §15).

``ordnung serve`` writes ``{port, token, pid, host, started_at, version}`` (readable by the owner
only — it holds the session token) and removes it on exit. CLI commands find a live server with
:func:`running_server` and talk to its API (bearer token) instead of opening the database
themselves. The file doubles as the pidfile: a stale file (its process is gone) counts as no server.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from ordnung import __version__
from ordnung.clock import real_now_iso
from ordnung.durable import write_atomic

SERVER_FILE = "server.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
TOKEN_BYTES = 32


class ServerInfo(BaseModel):
    """What ``server.json`` records about a running server."""

    port: int
    token: str | None = None
    pid: int
    host: str = DEFAULT_HOST
    started_at: str = ""
    version: str = __version__

    @property
    def base_url(self) -> str:
        """``http://127.0.0.1:<port>``."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    @property
    def login_url(self) -> str:
        """The link that signs a browser in (``/?token=…``; plain ``/`` without a token)."""
        return f"{self.base_url}/?token={quote(self.token)}" if self.token else f"{self.base_url}/"

    def api_url(self, path: str) -> str:
        """Absolute URL of an API path (``/documents`` → ``http://…/api/documents``)."""
        return f"{self.base_url}/api/{path.lstrip('/')}"

    def auth_headers(self) -> dict[str, str]:
        """Headers a CLI client sends: the bearer token and the client marker for writes."""
        headers = {"X-Ordnung-Client": "cli"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers


def generate_token() -> str:
    """A fresh random session token (URL-safe)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def server_file(data_dir: str | Path) -> Path:
    """Where ``server.json`` lives for a data directory."""
    return Path(data_dir) / SERVER_FILE


def write_server_info(data_dir: str | Path, info: ServerInfo) -> Path:
    """Write ``server.json`` atomically with owner-only permissions (0600)."""
    path = server_file(data_dir)
    write_atomic(path, info.model_dump_json(indent=2).encode("utf-8"), sync=False)
    return path


def read_server_info(data_dir: str | Path) -> ServerInfo | None:
    """The recorded server (``None`` if there is no readable ``server.json``)."""
    try:
        raw = server_file(data_dir).read_text(encoding="utf-8")
        return ServerInfo.model_validate(json.loads(raw))
    except (OSError, ValueError, ValidationError):
        return None


def pid_alive(pid: int) -> bool:
    """Whether a process with this id exists (without disturbing it)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_pid_alive(pid: int) -> bool:
    if sys.platform != "win32":  # keeps type checkers on other platforms quiet
        return False
    import ctypes

    query_limited_information, still_active = 0x1000, 259
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def running_server(data_dir: str | Path) -> ServerInfo | None:
    """The server recorded for ``data_dir`` if its process is still alive."""
    info = read_server_info(data_dir)
    return info if info is not None and pid_alive(info.pid) else None


def clear_server_info(data_dir: str | Path, pid: int | None = None) -> bool:
    """Remove ``server.json`` (only if it belongs to ``pid``, when given); ``True`` if removed."""
    path = server_file(data_dir)
    if pid is not None:
        info = read_server_info(data_dir)
        if info is not None and info.pid != pid:
            return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


@contextlib.contextmanager
def advertise(
    data_dir: str | Path, *, port: int, token: str | None, host: str = DEFAULT_HOST
) -> Iterator[ServerInfo]:
    """Record this process as the data directory's server while the block runs."""
    info = ServerInfo(port=port, token=token, pid=os.getpid(), host=host, started_at=real_now_iso())
    write_server_info(data_dir, info)
    try:
        yield info
    finally:
        clear_server_info(data_dir, pid=info.pid)
