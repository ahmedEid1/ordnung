"""Keys, names and sealing for the sync folder, format 1 (design §4.1-4.3, review findings 8, 17, 26).

**The key file** ``<K>`` (``K`` = 32 lowercase hex = its own scrypt salt) holds exactly
:data:`~ordnung.sync.KEY_FILE_BYTES` bytes: ``nonce (12) ‖ AES-256-GCM(KEK, body, aad = b"ordnung-sync/1
key" ‖ K)``, where ``body = format (1) ‖ vault_id (16) ‖ vault_key (32) ‖ 15 zero bytes`` and ``KEK =
scrypt(passphrase, K)`` with :data:`~ordnung.sync.SYNC_KDF` (2^18, r 8, p 1: 256 MiB, 0.93 s measured
here). No byte of it is plaintext; the KDF is fixed for format 1. A key file of another size has not
fully arrived yet; one that doesn't authenticate is the wrong passphrase.

**Subkeys** of the random vault key: ``names_key`` and ``objects_key`` (HKDF-SHA256). **Names** are
keyed: an object of kind ``k`` and content SHA-256 ``s`` is ``HMAC(names_key, k ‖ 0x00 ‖ s)[:16]`` in
hex, a head ``HMAC(names_key, "h" ‖ 0x00 ‖ computer)[:16]``, a writer's temp-file tag
``HMAC(names_key, "t" ‖ 0x00 ‖ computer)[:4]``. So the same content gets the same name on every
computer of a folder and another name in any other folder, and a name tells nothing about the content.

**Sealed files** (every file but the key file)::

    sealed    = salt (16) ‖ prefix (7) ‖ STREAM chunks (backup.container's KeyedWriter, 1 MiB each)
    key       = HKDF-SHA256(objects_key, salt = salt, info = b"ordnung-sync v1 " ‖ kind)
    aad       = b"ordnung-sync/1" ‖ vault_id ‖ kind ‖ name ‖ salt ‖ prefix
    plaintext = length (8) ‖ content ‖ zero bytes, P = padme(max(8 + length, MIN_PADDED)) bytes in all

* ``sealed_size(P) = 23 + P + 16 · max(1, ⌈P / CHUNK⌉)`` (finding 8: a full last chunk is one chunk),
  so "has it fully arrived?" is a ``stat``.
* Padmé: with ``E = ⌊log2 L⌋`` and ``S = ⌊log2 E⌋ + 1``, the low ``E − S`` bits are cleared, rounding
  up (``padme(1,000,000) = 1,015,808``); at most 12 % more, and at least 4 KiB hides small files.
* For a head (rewritten in place) salt and prefix are random. For the content-named kinds they come
  from ``HMAC(objects_key, "seal" ‖ name)`` (finding 26): two computers writing the same object write
  the very same bytes, so a sync tool never makes a conflict copy of it. That reveals nothing new — the
  name already says that the content is equal — and a nonce is never reused for other plaintext,
  because the name is bound to the content's SHA-256.
* The reader authenticates every chunk (a changed byte, swapped or cut chunks, a renamed file, another
  kind or vault all fail), then checks the length, the zero padding and the exact padded size, and the
  caller checks the content's SHA-256 against the name or the record that referenced it.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import math
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ordnung.backup.container import (
    CHUNK_SIZE,
    DamagedBackup,
    KeyedReader,
    KeyedWriter,
    Sink,
    derive_master,
    expand,
    normalize_passphrase,
)
from ordnung.sync import (
    CHUNK,
    CONTENT_NAMED_KINDS,
    FOLDER_FORMAT,
    KEY_FILE_BYTES,
    MIN_PADDED,
    SEAL_HEADER_BYTES,
    SEAL_TAG_BYTES,
    SYNC_KDF,
    NewerSyncFolder,
    NotArrived,
    ObjectKind,
    SyncError,
    WrongSyncPassphrase,
)

SALT_BYTES = 16
PREFIX_BYTES = 7
LENGTH_BYTES = 8
VAULT_ID_BYTES = 16
VAULT_KEY_BYTES = 32
_KEY_NONCE_BYTES = 12
_KEY_BODY_BYTES = 64
_KEY_AAD = b"ordnung-sync/1 key"
_AAD = b"ordnung-sync/1"
_NAMES_INFO = b"ordnung-sync v1 names"
_OBJECTS_INFO = b"ordnung-sync v1 objects"
_KIND_INFO = b"ordnung-sync v1 "
_SEAL_LABEL = b"seal"

assert CHUNK == CHUNK_SIZE  # the sealed chunk is the container's
assert SEAL_HEADER_BYTES == SALT_BYTES + PREFIX_BYTES


class Damaged(SyncError):
    """A sealed file of the expected size that fails authentication or its checks (retried; reported
    damaged only after :data:`~ordnung.sync.DAMAGED_AFTER_S`)."""

    def __init__(self, message: str = "A file in the sync folder is damaged.") -> None:
        super().__init__("folder_problem", message)


# --------------------------------------------------------------------------------------------------
# sizes
# --------------------------------------------------------------------------------------------------


def padme(length: int) -> int:
    """``length`` rounded up by Padmé (module doc): the low ``E − S`` bits cleared."""
    if length < 2:
        return length
    e = length.bit_length() - 1
    s = e.bit_length()  # ⌊log2 E⌋ + 1
    low = e - s
    if low <= 0:
        return length
    mask = (1 << low) - 1
    return (length + mask) & ~mask


def padded_size(length: int) -> int:
    """The plaintext size ``P`` of a sealed file whose content is ``length`` bytes."""
    return padme(max(LENGTH_BYTES + length, MIN_PADDED))


def sealed_size(padded: int) -> int:
    """The size of a sealed file whose plaintext is ``padded`` bytes (finding 8)."""
    return SEAL_HEADER_BYTES + padded + SEAL_TAG_BYTES * max(1, math.ceil(padded / CHUNK))


def sealed_size_of(length: int) -> int:
    """The size of a sealed file of ``length`` content bytes: what "fully arrived" means."""
    return sealed_size(padded_size(length))


# --------------------------------------------------------------------------------------------------
# the vault and the key file
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Vault:
    """The unlocked keys of a sync folder (in memory only)."""

    vault_id: bytes
    vault_key: bytes = field(repr=False)
    names_key: bytes = field(init=False, repr=False)
    objects_key: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "names_key", expand(self.vault_key, _NAMES_INFO))
        object.__setattr__(self, "objects_key", expand(self.vault_key, _OBJECTS_INFO))

    @property
    def id(self) -> str:
        return self.vault_id.hex()

    def _name(self, label: bytes, value: bytes, hex_chars: int) -> str:
        return hmac.new(self.names_key, label + b"\x00" + value, hashlib.sha256).hexdigest()[:hex_chars]

    def object_name(self, kind: ObjectKind, sha256_hex: str) -> str:
        """The keyed name of the object of ``kind`` whose content has SHA-256 ``sha256_hex``."""
        return self._name(kind.encode("ascii"), bytes.fromhex(sha256_hex), 32)

    def head_name(self, computer: str) -> str:
        return self._name(b"h", bytes.fromhex(computer), 32)

    def temp_tag(self, computer: str) -> str:
        return self._name(b"t", bytes.fromhex(computer), 8)

    # ---- sealing ---------------------------------------------------------------------------------

    def _aad(self, kind: ObjectKind, name: str, salt: bytes, prefix: bytes) -> bytes:
        return _AAD + self.vault_id + kind.encode("ascii") + name.encode("ascii") + salt + prefix

    def _key(self, kind: ObjectKind, salt: bytes) -> bytes:
        return expand(self.objects_key, _KIND_INFO + kind.encode("ascii"), salt=salt)

    def _salt_prefix(self, kind: ObjectKind, name: str, random_bytes: Callable[[int], bytes]) -> bytes:
        if kind in CONTENT_NAMED_KINDS:
            mac = hmac.new(self.objects_key, _SEAL_LABEL + name.encode("ascii"), hashlib.sha256).digest()
            return mac[: SALT_BYTES + PREFIX_BYTES]
        return random_bytes(SALT_BYTES + PREFIX_BYTES)

    def seal_to(
        self,
        out: Sink,
        kind: ObjectKind,
        name: str,
        length: int,
        chunks: Iterable[bytes],
        *,
        random_bytes: Callable[[int], bytes] = os.urandom,
    ) -> str:
        """Seal ``length`` content bytes (given as ``chunks``) into ``out``; returns the SHA-256 of what
        was sealed (the caller compares it with what it expected: a file changed underneath)."""
        head = self._salt_prefix(kind, name, random_bytes)
        salt, prefix = head[:SALT_BYTES], head[SALT_BYTES:]
        out.write(head)
        writer = KeyedWriter(
            out, self._key(kind, salt), prefix=prefix, aad=self._aad(kind, name, salt, prefix)
        )
        digest, written = hashlib.sha256(), 0
        try:
            writer.write(length.to_bytes(LENGTH_BYTES, "big"))
            for chunk in chunks:
                written += len(chunk)
                if written > length:
                    raise SyncError("folder_problem", "A file changed while it was saved.")
                digest.update(chunk)
                writer.write(chunk)
            if written != length:
                raise SyncError("folder_problem", "A file changed while it was saved.")
            pad = padded_size(length) - LENGTH_BYTES - length
            zeros = bytes(min(pad, CHUNK))
            while pad > 0:
                writer.write(zeros[: min(pad, CHUNK)])
                pad -= min(pad, CHUNK)
        except BaseException:
            writer.abort()
            raise
        writer.close()
        return digest.hexdigest()

    def seal(self, kind: ObjectKind, name: str, content: bytes) -> bytes:
        """``content`` sealed as the file ``name`` of ``kind`` (records: heads, manifests, buckets)."""
        out = io.BytesIO()
        self.seal_to(out, kind, name, len(content), [content])
        return out.getvalue()

    def open_to(
        self,
        src: BinaryIO,
        kind: ObjectKind,
        name: str,
        size: int,
        sink: Callable[[bytes], object] | None = None,
        *,
        max_length: int | None = None,
    ) -> tuple[int, str]:
        """Open the sealed file in ``src`` (``size`` bytes in all): its content goes to ``sink`` as it
        is authenticated; returns ``(length, sha256)``. :class:`Damaged` when anything doesn't hold —
        the sink may then have received part of it, which the caller throws away."""
        head = _read_exactly(src, SALT_BYTES + PREFIX_BYTES)
        if len(head) < SALT_BYTES + PREFIX_BYTES:
            raise Damaged()
        salt, prefix = head[:SALT_BYTES], head[SALT_BYTES:]
        reader = KeyedReader(
            src, self._key(kind, salt), prefix=prefix, aad=self._aad(kind, name, salt, prefix)
        )
        digest = hashlib.sha256()
        try:
            raw = _read_exactly(reader, LENGTH_BYTES)
            if len(raw) < LENGTH_BYTES:
                raise Damaged()
            length = int.from_bytes(raw, "big")
            if (max_length is not None and length > max_length) or sealed_size_of(length) != size:
                raise Damaged()
            left = length
            while left > 0:
                block = reader.read(min(left, CHUNK))
                if not block:
                    raise Damaged()
                left -= len(block)
                digest.update(block)
                if sink is not None:
                    sink(block)
            padding = padded_size(length) - LENGTH_BYTES - length
            while padding > 0:
                block = reader.read(min(padding, CHUNK))
                if not block or block.count(0) != len(block):
                    raise Damaged()
                padding -= len(block)
            if reader.read(1):
                raise Damaged()
        except DamagedBackup:
            raise Damaged() from None
        return length, digest.hexdigest()

    def open(self, kind: ObjectKind, name: str, data: bytes, *, max_length: int | None = None) -> bytes:
        """The content of the sealed file ``data`` (a record), :class:`Damaged` when it doesn't open."""
        parts: list[bytes] = []
        self.open_to(io.BytesIO(data), kind, name, len(data), parts.append, max_length=max_length)
        return b"".join(parts)


def _read_exactly(src: BinaryIO | io.RawIOBase, size: int) -> bytes:
    parts: list[bytes] = []
    left = size
    while left > 0:
        part = src.read(left)
        if not part:
            break
        parts.append(part)
        left -= len(part)
    return b"".join(parts)


def derive_kek(passphrase: str, key_file: str) -> bytes:
    """The key that wraps the vault key: scrypt of the passphrase, salted with the key file's name."""
    return derive_master(passphrase, bytes.fromhex(key_file), SYNC_KDF)


@dataclass(frozen=True)
class NewKeyFile:
    name: str
    data: bytes
    vault: Vault


def new_key_file(passphrase: str, *, random_bytes: Callable[[int], bytes] = os.urandom) -> NewKeyFile:
    """A new folder's key file and its vault (random vault id and key, wrapped by the passphrase)."""
    if not passphrase:
        raise SyncError("passphrase", "A sync folder needs a passphrase.")
    salt = random_bytes(SALT_BYTES)
    name = salt.hex()
    vault = Vault(random_bytes(VAULT_ID_BYTES), random_bytes(VAULT_KEY_BYTES))
    body = bytes([FOLDER_FORMAT]) + vault.vault_id + vault.vault_key
    body += bytes(_KEY_BODY_BYTES - len(body))
    nonce = random_bytes(_KEY_NONCE_BYTES)
    data = nonce + AESGCM(derive_kek(passphrase, name)).encrypt(nonce, body, _KEY_AAD + name.encode("ascii"))
    assert len(data) == KEY_FILE_BYTES
    return NewKeyFile(name=name, data=data, vault=vault)


def open_key_file(name: str, data: bytes, passphrase: str) -> Vault:
    """The vault of the key file ``name``: :class:`~ordnung.sync.NotArrived` (another size),
    :class:`~ordnung.sync.WrongSyncPassphrase`, :class:`~ordnung.sync.NewerSyncFolder`."""
    if len(data) != KEY_FILE_BYTES:
        raise NotArrived(
            "The sync folder's key file hasn't fully arrived yet. Wait until your sync tool has copied everything."
        )
    nonce, sealed = data[:_KEY_NONCE_BYTES], data[_KEY_NONCE_BYTES:]
    try:
        body = AESGCM(derive_kek(passphrase, name)).decrypt(nonce, sealed, _KEY_AAD + name.encode("ascii"))
    except InvalidTag:
        raise WrongSyncPassphrase() from None
    if body[0] > FOLDER_FORMAT:
        raise NewerSyncFolder()
    if body[0] != FOLDER_FORMAT or any(body[1 + VAULT_ID_BYTES + VAULT_KEY_BYTES :]):
        raise WrongSyncPassphrase()
    return Vault(
        body[1 : 1 + VAULT_ID_BYTES], body[1 + VAULT_ID_BYTES : 1 + VAULT_ID_BYTES + VAULT_KEY_BYTES]
    )


def passphrase_bytes(passphrase: str) -> list[bytes]:
    """The byte forms a passphrase could take (tests check none of them is written anywhere)."""
    return list(dict.fromkeys([passphrase.encode("utf-8"), normalize_passphrase(passphrase)]))
