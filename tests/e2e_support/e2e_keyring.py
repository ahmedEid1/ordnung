"""A password store for the end-to-end tests only, so the real app's hand-off sync and calendar sync can
keep a secret on a CI machine without a desktop session (headless Linux has no Secret Service, and
Ordnung refuses keyring's ``null`` and ``fail`` backends and ``keyrings.alt``).

``web/playwright.config.ts`` starts each real server with::

    PYTHON_KEYRING_BACKEND=e2e_keyring.FileKeyring
    PYTHONPATH=<repo>/tests/e2e_support
    ORDNUNG_E2E_KEYRING_FILE=<that computer's own file next to its data folder>

so the real :class:`ordnung.calendar.secrets.KeyringSecrets` path runs, the policy check included: this
module is none of the refused ones, and its priority is 1 — the lowest Ordnung accepts. Without
``ORDNUNG_E2E_KEYRING_FILE`` the backend isn't viable at all (its priority raises keyring's
``InitError``): ``keyring`` never picks it by itself, in a test process that merely imported it, and
Ordnung answers as on a computer without a password store.

The secrets are kept **in plain text** (a JSON object ``{service: {account: secret}}``, ``0600``,
replaced atomically): never point it at anything but a test's throw-away file. Each computer of the
two-computer test gets its own file, as each real computer has its own password store.
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path

from jaraco.classes import properties
from keyring.backend import KeyringBackend
from keyring.errors import InitError, PasswordDeleteError

#: The file the secrets are kept in (the backend is refused without it).
FILE_ENV = "ORDNUNG_E2E_KEYRING_FILE"

_lock = threading.Lock()


def _file() -> Path:
    name = os.environ.get(FILE_ENV, "")
    if not name:
        raise InitError(f"{FILE_ENV} is not set: the e2e password store has no file")
    return Path(name)


def _read(path: Path) -> dict[str, dict[str, str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    return {str(service): {str(k): str(v) for k, v in accounts.items()} for service, accounts in data.items()}


def _write(path: Path, data: dict[str, dict[str, str]]) -> None:
    partial = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.part")
    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=1, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        partial.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            partial.unlink()
        raise


class FileKeyring(KeyringBackend):
    """``keyring``'s backend interface over one JSON file (module docstring): tests only."""

    @properties.classproperty
    def priority(cls) -> float:
        """1, the lowest priority Ordnung accepts — with a file to keep secrets in; else not viable."""
        _file()
        return 1.0

    def get_password(self, service: str, username: str) -> str | None:
        with _lock:
            return _read(_file()).get(service, {}).get(username)

    def set_password(self, service: str, username: str, password: str) -> None:
        with _lock:
            path = _file()
            data = _read(path)
            data.setdefault(service, {})[username] = password
            _write(path, data)

    def delete_password(self, service: str, username: str) -> None:
        with _lock:
            path = _file()
            data = _read(path)
            accounts = data.get(service, {})
            if username not in accounts:
                raise PasswordDeleteError(f"no secret for {username!r} in {service!r}")
            del accounts[username]
            if not accounts:
                del data[service]
            _write(path, data)
