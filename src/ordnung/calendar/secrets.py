"""Where the calendar-sync password lives: the operating system's password store, never the database.

Written policy (ADR 0007):

* **The OS keyring only.** The app password for the person's calendar (CalDAV) is kept with the
  :mod:`keyring` package — macOS Keychain, Windows Credential Locker, the Secret Service (GNOME
  Keyring, KWallet) on Linux — under the service :data:`SERVICE` and the account
  ``<user name> @ <calendar address>``. It is never written to ``ordnung.db``, a log, a backup or
  an API answer.
* **An optional extra.** ``keyring`` is installed with ``ordnung[caldav]``; without it, or on a
  computer with no usable password store (a headless Linux without a Secret Service), calendar sync
  is unavailable and :func:`KeyringSecrets.problem` says why and what to install. Nothing falls back
  to a plain-text file.
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol

SERVICE = "Ordnung calendar sync"
INSTALL_COMMAND = "pip install 'ordnung[caldav]'"
_PROBE_ACCOUNT = "ordnung-probe"


class SecretsUnavailable(RuntimeError):
    """No password store can be used on this computer; the message says why, for people, and
    ``install`` is the command that fixes it when a package is missing."""

    def __init__(self, message: str, *, install: str | None = None) -> None:
        super().__init__(message)
        self.install = install


class SecretStore(Protocol):
    """A place to keep one password per account."""

    def problem(self) -> SecretsUnavailable | None:
        """Why passwords can't be kept here (``None``: they can)."""

    def get(self, account: str) -> str | None:
        """The password of ``account`` (``None`` if none is stored)."""

    def set(self, account: str, password: str) -> None:
        """Store ``password`` for ``account``, replacing an earlier one."""

    def delete(self, account: str) -> None:
        """Forget the password of ``account`` (no error when there is none)."""


def account_name(username: str, url: str) -> str:
    """The keyring account of a calendar connection: ``<user name> @ <calendar address>``."""
    return f"{username} @ {url}"


class KeyringSecrets:
    """:class:`SecretStore` backed by the :mod:`keyring` package (module policy)."""

    def _module(self) -> Any:
        try:
            return importlib.import_module("keyring")
        except ImportError:
            raise SecretsUnavailable(
                "Calendar sync keeps your app password in this computer's password store, and Ordnung "
                "needs an extra package for that.",
                install=INSTALL_COMMAND,
            ) from None

    def _call(self, name: str, *args: str) -> Any:
        keyring = self._module()
        errors = importlib.import_module("keyring.errors")
        try:
            return getattr(keyring, name)(*args)
        except errors.PasswordDeleteError:
            return None
        except errors.KeyringError:
            raise SecretsUnavailable(
                "This computer has no password store Ordnung can use (on Linux: GNOME Keyring or "
                "KWallet, unlocked), so it can't keep the app password safely."
            ) from None

    def problem(self) -> SecretsUnavailable | None:
        try:
            self._call("get_password", SERVICE, _PROBE_ACCOUNT)
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
