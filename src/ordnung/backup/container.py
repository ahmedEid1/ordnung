"""The encrypted container of a backup file (format version 1).

A backup is one file: a fixed header, then the archive encrypted in chunks. The construction is the
STREAM online authenticated encryption of Hoang, Reyhanitabar, Rogaway and Vizár (the one ``age``
and Tink use): every chunk is sealed with AES-256-GCM under a nonce made of a random prefix, the
chunk's number and a "last chunk" flag, and with the whole header as associated data. So a changed
byte anywhere, chunks swapped, removed or appended, a file cut short at a chunk boundary, or an
edited header all fail authentication — nothing of a changed file is ever trusted.

Layout (integers big-endian)::

    magic          15  b"ORDNUNG-BACKUP\\n"
    version         1  1
    kdf             1  1 = scrypt
    log2_n          1  scrypt cost N = 2**log2_n (17 when written; 10..20 read)
    r               1  scrypt block size (8 when written; 1..16 read)
    p               1  scrypt parallelism (1 when written; 1..2 read)
    salt           16  random
    nonce_prefix    7  random
    chunk_size      4  plaintext bytes per chunk (1 MiB when written; 4 KiB..16 MiB read)
    header_mac     32  HMAC-SHA256(header key, the 47 bytes above)
    chunks          …  AES-256-GCM(data key, nonce = prefix ‖ counter (4) ‖ last (1), aad = the 79 header bytes)

Every chunk but the last holds exactly ``chunk_size`` bytes; the last holds 0..``chunk_size``. The
reader also caps scrypt's memory, ``128 · r · N`` bytes, at :data:`MAX_SCRYPT_BYTES` (256 MiB; a
written backup uses 128 MiB), since the key is derived before the header MAC can be checked.

Keys: ``master = scrypt(passphrase)`` over the passphrase's UTF-8 bytes in Unicode NFC (so the same
passphrase typed on another system opens it), then the data key and the header key are derived
from it with HKDF-SHA256 under different labels. A header MAC that doesn't match means the
passphrase is wrong (or the header was changed) — the reader says so before decrypting anything.

What the reader refuses, and in which order: a file that doesn't start with the magic
(:class:`NotABackup`), a newer format version (:class:`NewerBackupFormat` — before asking for any
key), header parameters outside the ranges above (:class:`DamagedBackup`, so a crafted header can't
make scrypt use more than 256 MiB of memory, or more than four times the work of a written backup), a
wrong passphrase (:class:`WrongPassphrase`), and any chunk that fails authentication or a missing
last chunk (:class:`DamagedBackup`).

The STREAM core is shared: :class:`_Sealer` and :class:`_Opener` seal and open the chunks under a
given AEAD key, nonce prefix and associated data. :class:`EncryptedWriter` / :class:`EncryptedReader`
wrap them after deriving their keys from the v1 header (a v1 file's bytes are exactly what they were
before the split — ``tests/test_backup_container.py`` pins one byte for byte); :class:`KeyedWriter` /
:class:`KeyedReader` are the same streams without a header, for callers that derive their keys
themselves (hand-off sync, :mod:`ordnung.sync.crypto`). Key derivation is :func:`derive_master`
(scrypt) followed by :func:`expand` (HKDF-SHA256).
"""

from __future__ import annotations

import hmac
import io
import os
import struct
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, BinaryIO, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"ORDNUNG-BACKUP\n"
FORMAT_VERSION = 1
KDF_SCRYPT = 1
SALT_BYTES = 16
PREFIX_BYTES = 7
TAG_BYTES = 16
MAC_BYTES = 32
KEY_BYTES = 32
CHUNK_SIZE = 1024 * 1024
MIN_CHUNK_SIZE = 4 * 1024
MAX_CHUNK_SIZE = 16 * 1024 * 1024
_MAX_COUNTER = 2**32 - 1
#: the most memory a backup's key derivation may take (scrypt: 128 · r · N bytes)
MAX_SCRYPT_BYTES = 256 * 1024 * 1024
MAX_SCRYPT_P = 2
# everything after the version byte, up to the MAC
_PARAMS = struct.Struct(">BBBB16s7sI")
HEADER_BYTES = len(MAGIC) + 1 + _PARAMS.size + MAC_BYTES
_DATA_INFO = b"ordnung-backup v1 data key"
_HEADER_INFO = b"ordnung-backup v1 header key"


class Sink(Protocol):
    """Where :class:`EncryptedWriter` writes (a file, a buffer)."""

    def write(self, data: bytes, /) -> Any: ...

    def flush(self) -> Any: ...


class BackupError(RuntimeError):
    """A backup can't be written or read; the message is written for people."""


class NotABackup(BackupError):
    """The file is not an Ordnung backup."""


class NewerBackupFormat(BackupError):
    """The file was written by a newer version of Ordnung."""


class WrongPassphrase(BackupError):
    """The passphrase does not open this backup (or its header was changed)."""


class DamagedBackup(BackupError):
    """The file was changed, cut short or damaged after it was written."""


@dataclass(frozen=True)
class KdfParams:
    """scrypt's cost parameters (``N = 2**log2_n``). The default costs about 128 MiB and ~0.4 s."""

    log2_n: int = 17
    r: int = 8
    p: int = 1

    @property
    def memory(self) -> int:
        """Bytes of memory scrypt needs with these parameters."""
        return 128 * self.r * 2**self.log2_n

    def check(self) -> None:
        """Refuse parameters outside what a reader accepts (module doc: at most 256 MiB, ``p`` ≤ 2)."""
        in_range = 10 <= self.log2_n <= 20 and 1 <= self.r <= 16 and 1 <= self.p <= MAX_SCRYPT_P
        if not in_range or self.memory > MAX_SCRYPT_BYTES:
            raise DamagedBackup("This backup's header is damaged (unusual key settings).")


DEFAULT_KDF = KdfParams()


@dataclass(frozen=True)
class Header:
    """The parsed header of a backup file."""

    version: int
    kdf: KdfParams
    salt: bytes
    nonce_prefix: bytes
    chunk_size: int
    mac: bytes

    @property
    def signed(self) -> bytes:
        """The header bytes the MAC covers."""
        params = _PARAMS.pack(
            KDF_SCRYPT, self.kdf.log2_n, self.kdf.r, self.kdf.p, self.salt, self.nonce_prefix, self.chunk_size
        )
        return MAGIC + bytes([self.version]) + params

    @property
    def raw(self) -> bytes:
        """All header bytes (the associated data of every chunk)."""
        return self.signed + self.mac


@dataclass(frozen=True)
class _Keys:
    data: bytes
    header: bytes


def normalize_passphrase(passphrase: str) -> bytes:
    """The bytes a passphrase stands for: UTF-8 of its Unicode NFC form (nothing is trimmed)."""
    return unicodedata.normalize("NFC", passphrase).encode("utf-8")


def derive_master(passphrase: str, salt: bytes, kdf: KdfParams) -> bytes:
    """scrypt of the passphrase (:func:`normalize_passphrase`) under ``salt``: the 32-byte master key."""
    return Scrypt(salt=salt, length=KEY_BYTES, n=2**kdf.log2_n, r=kdf.r, p=kdf.p).derive(
        normalize_passphrase(passphrase)
    )


def expand(master: bytes, info: bytes, salt: bytes | None = None) -> bytes:
    """A 32-byte key for ``info`` from ``master`` (HKDF-SHA256, optionally salted)."""
    return HKDF(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=salt, info=info).derive(master)


def _derive(passphrase: str, salt: bytes, kdf: KdfParams) -> _Keys:
    master = derive_master(passphrase, salt, kdf)
    return _Keys(data=expand(master, _DATA_INFO), header=expand(master, _HEADER_INFO))


def _mac(key: bytes, signed: bytes) -> bytes:
    return hmac.new(key, signed, sha256).digest()


def _nonce(prefix: bytes, counter: int, last: bool) -> bytes:
    if counter > _MAX_COUNTER:
        raise BackupError("This backup is too large for one file.")
    return prefix + counter.to_bytes(4, "big") + (b"\x01" if last else b"\x00")


def _read_exactly(src: BinaryIO, size: int) -> bytes:
    """Up to ``size`` bytes (fewer only at the end of the file)."""
    parts: list[bytes] = []
    remaining = size
    while remaining > 0:
        part = src.read(remaining)
        if not part:
            break
        parts.append(part)
        remaining -= len(part)
    return b"".join(parts)


def read_header(src: BinaryIO) -> Header:
    """Parse the header at the start of ``src`` (nothing is decrypted, no key is derived).

    Raises :class:`NotABackup`, :class:`NewerBackupFormat` or :class:`DamagedBackup`.
    """
    magic = _read_exactly(src, len(MAGIC))
    if magic != MAGIC:
        raise NotABackup("This file is not an Ordnung backup.")
    version_byte = _read_exactly(src, 1)
    if not version_byte:
        raise DamagedBackup("This backup is cut short: its header is incomplete.")
    version = version_byte[0]
    if version > FORMAT_VERSION:
        raise NewerBackupFormat(
            f"This backup was made by a newer version of Ordnung (backup format {version}; this "
            f"version reads format {FORMAT_VERSION}). Update Ordnung, then restore it."
        )
    if version < 1:
        raise DamagedBackup("This backup's header is damaged (unknown format version).")
    rest = _read_exactly(src, _PARAMS.size + MAC_BYTES)
    if len(rest) < _PARAMS.size + MAC_BYTES:
        raise DamagedBackup("This backup is cut short: its header is incomplete.")
    kdf_id, log2_n, r, p, salt, prefix, chunk_size = _PARAMS.unpack(rest[: _PARAMS.size])
    if kdf_id != KDF_SCRYPT:
        raise DamagedBackup("This backup's header is damaged (unknown key derivation).")
    kdf = KdfParams(log2_n=log2_n, r=r, p=p)
    kdf.check()
    if not MIN_CHUNK_SIZE <= chunk_size <= MAX_CHUNK_SIZE:
        raise DamagedBackup("This backup's header is damaged (unusual chunk size).")
    return Header(
        version=version,
        kdf=kdf,
        salt=salt,
        nonce_prefix=prefix,
        chunk_size=chunk_size,
        mac=rest[_PARAMS.size :],
    )


class _Sealer:
    """Seals what is written to it into STREAM chunks of ``chunk_size`` plaintext bytes (module doc):
    nonce ``prefix ‖ counter ‖ last``, associated data ``aad``. Up to a whole chunk is kept back,
    because only :meth:`close` knows which chunk is the last (a full last chunk is sealed as last)."""

    def __init__(self, aead: AESGCM, prefix: bytes, aad: bytes, chunk_size: int, out: Sink) -> None:
        self._aead = aead
        self._prefix = prefix
        self._aad = aad
        self._chunk_size = chunk_size
        self._out = out
        self._buffer = bytearray()
        self._counter = 0

    def _seal(self, plaintext: bytes, *, last: bool) -> None:
        nonce = _nonce(self._prefix, self._counter, last)
        self._out.write(self._aead.encrypt(nonce, plaintext, self._aad))
        self._counter += 1

    def write(self, data: bytes | bytearray | memoryview) -> int:
        self._buffer += data
        # keep up to a whole chunk back: the last chunk may be full, and only close() knows it is last
        while len(self._buffer) > self._chunk_size:
            self._seal(bytes(self._buffer[: self._chunk_size]), last=False)
            del self._buffer[: self._chunk_size]
        return len(data)

    def close(self) -> None:
        self._seal(bytes(self._buffer), last=True)
        self._buffer.clear()
        self._out.flush()

    def drop(self) -> None:
        self._buffer.clear()


class _Opener:
    """Opens the chunks :class:`_Sealer` wrote, one at a time, authenticating each before any of its
    bytes are returned; :attr:`done` only after the last chunk authenticated."""

    def __init__(self, aead: AESGCM, prefix: bytes, aad: bytes, chunk_size: int, src: BinaryIO) -> None:
        self._aead = aead
        self._prefix = prefix
        self._aad = aad
        self._src = src
        self._sealed_size = chunk_size + TAG_BYTES
        self._pending = b""  # one byte read ahead to learn whether a chunk is the last one
        self._counter = 0
        self.done = False

    def next_chunk(self) -> bytes:
        """The next chunk's plaintext (:class:`DamagedBackup` when it fails authentication)."""
        sealed = self._pending + _read_exactly(self._src, self._sealed_size - len(self._pending))
        self._pending = b""
        last = len(sealed) < self._sealed_size
        if not last:
            self._pending = _read_exactly(self._src, 1)
            last = not self._pending
        if len(sealed) < TAG_BYTES:
            raise DamagedBackup("This backup is cut short: its end is missing.")
        try:
            plain = self._aead.decrypt(_nonce(self._prefix, self._counter, last), sealed, self._aad)
        except InvalidTag:
            raise DamagedBackup(
                "This backup was changed or damaged after it was made (or it is cut short), so it can't be trusted."
            ) from None
        self._counter += 1
        self.done = last
        return plain


class _ChunkWriter(io.RawIOBase):
    """A write-only stream into a :class:`_Sealer`: :meth:`close` seals the last chunk (``out`` itself
    is not closed); :meth:`abort` stops without it, so what was written reads as incomplete."""

    _sealer: _Sealer | None = None

    def __init__(self) -> None:
        super().__init__()
        self._sealed = True  # nothing to seal until set up: a refused writer closes quietly

    def writable(self) -> bool:
        return True

    def write(self, data: bytes | bytearray | memoryview) -> int:  # type: ignore[override]
        if self._sealed or self._sealer is None:
            raise ValueError("write to a closed backup")
        return self._sealer.write(data)

    def close(self) -> None:
        if not self._sealed and not self.closed and self._sealer is not None:
            self._sealer.close()
            self._sealed = True
        super().close()

    def abort(self) -> None:
        """Stop without sealing the last chunk: what was written reads as incomplete, never as whole."""
        self._sealed = True
        if self._sealer is not None:
            self._sealer.drop()
        super().close()


class _ChunkReader(io.RawIOBase):
    """A read-only stream of an :class:`_Opener`'s plaintext."""

    def __init__(self) -> None:
        super().__init__()
        self._opener: _Opener | None = None
        self._plain = memoryview(b"")

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:  # type: ignore[override]
        assert self._opener is not None
        target = memoryview(buffer).cast("B")
        while not self._plain:
            if self._opener.done:
                return 0
            self._plain = memoryview(self._opener.next_chunk())
        size = min(len(target), len(self._plain))
        target[:size] = self._plain[:size]
        self._plain = self._plain[size:]
        return size

    def read_to_end(self) -> int:
        """Read (and authenticate) whatever is left; returns how many plaintext bytes that was."""
        total = 0
        while True:
            data = self.read(CHUNK_SIZE)
            if not data:
                return total
            total += len(data)


class EncryptedWriter(_ChunkWriter):
    """A write-only stream that encrypts everything written to it into ``out`` (see the module doc).

    The header is written at once; :meth:`close` seals the last chunk — a file whose writer was not
    closed has no last chunk and is refused as incomplete. ``out`` itself is not closed.
    """

    def __init__(
        self,
        out: Sink,
        passphrase: str,
        *,
        kdf: KdfParams = DEFAULT_KDF,
        chunk_size: int = CHUNK_SIZE,
        random_bytes: Callable[[int], bytes] = os.urandom,
    ) -> None:
        super().__init__()
        if not passphrase:
            raise BackupError("A backup needs a passphrase.")
        if not MIN_CHUNK_SIZE <= chunk_size <= MAX_CHUNK_SIZE:
            raise ValueError("chunk_size out of range")
        kdf.check()
        salt, prefix = random_bytes(SALT_BYTES), random_bytes(PREFIX_BYTES)
        keys = _derive(passphrase, salt, kdf)
        unsigned = Header(FORMAT_VERSION, kdf, salt, prefix, chunk_size, b"")
        self._header = Header(
            FORMAT_VERSION, kdf, salt, prefix, chunk_size, _mac(keys.header, unsigned.signed)
        )
        self._sealer = _Sealer(AESGCM(keys.data), prefix, self._header.raw, chunk_size, out)
        out.write(self._header.raw)
        self._sealed = False


class EncryptedReader(_ChunkReader):
    """A read-only stream of the decrypted content of the backup in ``src``.

    Opening checks the header and the passphrase (see :func:`read_header`, :class:`WrongPassphrase`).
    Reading authenticates every chunk before any of its bytes are returned; the end of the stream
    is reported only after the last chunk was authenticated, so :meth:`read_to_end` proves the
    whole file is intact.
    """

    def __init__(self, src: BinaryIO, passphrase: str, *, header: Header | None = None) -> None:
        super().__init__()
        self._src = src
        self._header = header or read_header(src)
        keys = _derive(passphrase, self._header.salt, self._header.kdf)
        if not hmac.compare_digest(_mac(keys.header, self._header.signed), self._header.mac):
            raise WrongPassphrase("Wrong passphrase — or this backup's first bytes were changed.")
        self._opener = _Opener(
            AESGCM(keys.data), self._header.nonce_prefix, self._header.raw, self._header.chunk_size, src
        )

    @property
    def header(self) -> Header:
        return self._header


def _check_keyed(key: bytes, prefix: bytes, chunk_size: int) -> None:
    if len(key) != KEY_BYTES or len(prefix) != PREFIX_BYTES:
        raise ValueError("a keyed stream takes a 32-byte key and a 7-byte nonce prefix")
    if not MIN_CHUNK_SIZE <= chunk_size <= MAX_CHUNK_SIZE:
        raise ValueError("chunk_size out of range")


class KeyedWriter(_ChunkWriter):
    """:class:`EncryptedWriter` without a header: the caller gives the AES-256-GCM ``key``, the 7-byte
    nonce ``prefix`` and the associated data (and keeps what it needs to open the stream again)."""

    def __init__(
        self, out: Sink, key: bytes, *, prefix: bytes, aad: bytes, chunk_size: int = CHUNK_SIZE
    ) -> None:
        super().__init__()
        _check_keyed(key, prefix, chunk_size)
        self._sealer = _Sealer(AESGCM(key), prefix, aad, chunk_size, out)
        self._sealed = False


class KeyedReader(_ChunkReader):
    """:class:`EncryptedReader` without a header (see :class:`KeyedWriter`): every chunk is
    authenticated before its bytes are returned, and a changed byte, a missing last chunk or a chunk
    cut short raises :class:`DamagedBackup`."""

    def __init__(
        self, src: BinaryIO, key: bytes, *, prefix: bytes, aad: bytes, chunk_size: int = CHUNK_SIZE
    ) -> None:
        super().__init__()
        _check_keyed(key, prefix, chunk_size)
        self._opener = _Opener(AESGCM(key), prefix, aad, chunk_size, src)
