"""Fakes shared by several test modules: an in-memory password store, and cheap key derivation.

``MemorySecrets`` lived in ``fake_caldav`` (calendar sync's tests); hand-off sync's tests use it too, so
it lives here and ``fake_caldav`` re-exports it.
"""

from __future__ import annotations

import pytest

from ordnung.backup.container import KdfParams
from ordnung.calendar.secrets import SecretsUnavailable

#: scrypt settings cheap enough for tests (the files record nothing of them for sync: the KDF is patched)
FAST_KDF = KdfParams(log2_n=10)


class MemorySecrets:
    """A :class:`~ordnung.calendar.secrets.SecretStore` in memory (``unavailable``: none usable)."""

    def __init__(self, unavailable: SecretsUnavailable | None = None) -> None:
        self.saved: dict[str, str] = {}
        self.unavailable = unavailable

    def problem(self) -> SecretsUnavailable | None:
        return self.unavailable

    def _check(self) -> None:
        if self.unavailable is not None:
            raise self.unavailable

    def get(self, account: str) -> str | None:
        self._check()
        return self.saved.get(account)

    def set(self, account: str, password: str) -> None:
        self._check()
        self.saved[account] = password

    def delete(self, account: str) -> None:
        self._check()
        self.saved.pop(account, None)


def use_fast_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cheap scrypt for backups (kept copies) and for the sync folder's key file."""
    from ordnung import backup as backups
    from ordnung.backup import archive
    from ordnung.sync import crypto

    monkeypatch.setattr(backups, "DEFAULT_KDF", FAST_KDF)
    monkeypatch.setattr(archive, "DEFAULT_KDF", FAST_KDF)
    monkeypatch.setattr(archive.write_backup, "__kwdefaults__", {"kdf": FAST_KDF, "created_at": None})
    monkeypatch.setattr(backups.write_backup_file, "__kwdefaults__", {"kdf": FAST_KDF})
    monkeypatch.setattr(
        archive.BackupStream.__init__,
        "__kwdefaults__",
        {"kdf": FAST_KDF, "created_at": None, "_snapshot": None, "_files": None},
    )
    monkeypatch.setattr(
        archive.BackupStream.from_parts.__func__, "__kwdefaults__", {"kdf": FAST_KDF, "created_at": None}
    )  # type: ignore[attr-defined]
    monkeypatch.setattr(crypto, "SYNC_KDF", FAST_KDF)
