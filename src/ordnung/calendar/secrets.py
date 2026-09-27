"""Where the calendar-sync password lives: the operating system's password store, never the database.

Written policy (ADR 0007):

* **The OS keyring only.** The app password for the person's calendar (CalDAV) is kept with the
  :mod:`keyring` package — macOS Keychain, Windows Credential Locker, the Secret Service (GNOME
  Keyring, KWallet) on Linux — under the service :data:`SERVICE` and the account
  ``<user name> @ <calendar address>``. It is never written to ``ordnung.db``, a log, a backup or
  an API answer.
* **A real password store, or none.** ``keyring`` is one of Ordnung's dependencies. A backend that
  doesn't keep passwords safely is refused, not used: the ``null`` and ``fail`` backends (a
  ``PYTHON_KEYRING_BACKEND`` set to silence pip, or a headless Linux without a Secret Service),
  anything from ``keyrings.alt`` (plain-text or home-made encrypted files) and any backend whose
  priority is below 1 — :func:`KeyringSecrets.problem` then says why. Nothing falls back to a
  plain-text file. Should ``keyring`` itself be missing (a broken install), the problem names the
  command that adds it to *this* installation (pipx, uv tool, or this Python's pip).
* **Asking is not reading.** :func:`KeyringSecrets.problem` only looks at which backend ``keyring``
  chose; it never reads a secret, so opening Settings doesn't make a locked keyring ask to be
  unlocked. Passwords are read only to connect, to send a change and to disconnect.
"""

from __future__ import annotations

import importlib
import shlex
import sys
from typing import Any, Protocol

SERVICE = "Ordnung calendar sync"
KEYRING_REQUIREMENT = "keyring>=25"
SOURCE = "git+https://github.com/ahmedEid1/ordnung"
#: the priority of a real password store (the OS ones are 4.9–5; plain-text files 0.5, null -1)
MIN_PRIORITY = 1.0
_REFUSED_MODULES = ("keyring.backends.null", "keyring.backends.fail", "keyrings.alt")
NO_STORE = (
    "This computer has no password store Ordnung can use (on Linux: GNOME Keyring or KWallet, "
    "unlocked), so it can't keep the app password safely."
)


class SecretsUnavailable(RuntimeError):
    """No password store can be used on this computer; the message says why, for people, and
    ``install`` is the command that fixes it when a package is missing."""

    def __init__(self, message: str, *, install: str | None = None) -> None:
        super().__init__(message)
        self.install = install


class SecretStore(Protocol):
    """A place to keep one password per account."""

    def problem(self) -> SecretsUnavailable | None:
        """Why passwords can't be kept here (``None``: they can) — without reading one."""

    def get(self, account: str) -> str | None:
        """The password of ``account`` (``None`` if none is stored)."""

    def set(self, account: str, password: str) -> None:
        """Store ``password`` for ``account``, replacing an earlier one."""

    def delete(self, account: str) -> None:
        """Forget the password of ``account`` (no error when there is none)."""


def account_name(username: str, url: str) -> str:
    """The keyring account of a calendar connection: ``<user name> @ <calendar address>``."""
    return f"{username} @ {url}"


def install_command(prefix: str | None = None, executable: str | None = None) -> str:
    """The command that adds ``keyring`` to the installation running Ordnung (module policy)."""
    where = (prefix or sys.prefix).replace("\\", "/")
    if "/pipx/venvs/" in where:
        return "pipx inject ordnung keyring"
    if "/uv/tools/" in where:
        return f"uv tool install --reinstall --with '{KEYRING_REQUIREMENT}' {SOURCE}"
    python = executable or sys.executable
    return f"{shlex.quote(python)} -m pip install '{KEYRING_REQUIREMENT}'"


def backend_problem(backend: Any) -> str | None:
    """Why the ``keyring`` backend ``backend`` can't keep the app password (``None``: it can)."""
    chained = getattr(backend, "backends", None)
    if type(backend).__name__ == "ChainerBackend" and isinstance(chained, list):
        # a chain stores into its first backend that takes passwords
        return backend_problem(chained[0]) if chained else NO_STORE
    module = type(backend).__module__
    name = f"{module}.{type(backend).__name__}"
    try:
        priority = float(backend.priority)
    except Exception:  # a backend that can't say is not one to trust with a password
        priority = -1.0
    if module.startswith("keyring.backends.fail"):  # keyring found no password store at all
        return NO_STORE
    if module.startswith(_REFUSED_MODULES) or priority < MIN_PRIORITY:
        return (
            f"Python's keyring package is set to use {name}, which doesn't keep passwords safely, so "
            "Ordnung won't store the app password with it. Use the system's password store (unset "
            "PYTHON_KEYRING_BACKEND, or change keyring's configuration)."
        )
    return None


class KeyringSecrets:
    """:class:`SecretStore` backed by the :mod:`keyring` package (module policy)."""

    def _module(self) -> Any:
        try:
            return importlib.import_module("keyring")
        except ImportError:
            raise SecretsUnavailable(
                "Calendar sync keeps your app password in this computer's password store, and this "
                "installation of Ordnung is missing the package for that.",
                install=install_command(),
            ) from None

    def _backend(self) -> Any:
        keyring = self._module()
        errors = importlib.import_module("keyring.errors")
        try:
            backend = keyring.get_keyring()
        except errors.KeyringError:
            raise SecretsUnavailable(NO_STORE) from None
        problem = backend_problem(backend)
        if problem is not None:
            raise SecretsUnavailable(problem)
        return backend

    def _call(self, name: str, *args: str) -> Any:
        backend = self._backend()
        errors = importlib.import_module("keyring.errors")
        try:
            return getattr(backend, name)(*args)
        except errors.PasswordDeleteError:
            return None
        except errors.KeyringError:
            raise SecretsUnavailable(NO_STORE) from None

    def problem(self) -> SecretsUnavailable | None:
        try:
            self._backend()
        except SecretsUnavailable as exc:
            return exc
        return None

    def get(self, account: str) -> str | None:
        value = self._call("get_password", SERVICE, account)
        return value if isinstance(value, str) and value else None

    def set(self, account: str, password: str) -> None:
        self._call("set_password", SERVICE, account, password)

    def delete(self, account: str) -> None:
        self._call("delete_password", SERVICE, account)
