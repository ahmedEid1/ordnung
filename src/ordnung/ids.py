"""Short, sortable-enough, prefixed identifiers (e.g. ``doc_k3j9x0a1b2c4``).

Two flavours (SPEC §5):

* :func:`new_id` — random, for manual/user rows, drafts, chat and jobs.
* :func:`content_id` / :func:`doc_id_for_sha` — deterministic, derived from content, so recorded
  demo/replay references stay valid across rebuilds.
"""

from __future__ import annotations

import hashlib
import secrets

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford-ish base32, no i/l/o/u
_ID_CHARS = 12

PREFIXES = {"doc", "pty", "cas", "ctr", "itm", "sug", "drf", "nte", "txn", "rec", "job", "msg", "thr"}


def _check_prefix(prefix: str) -> None:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix!r}")


def _base32(data: bytes, length: int = _ID_CHARS) -> str:
    """First ``length`` base32 characters of ``data`` (most significant bits first)."""
    total_bits = len(data) * 8
    value = int.from_bytes(data, "big") >> (total_bits - length * 5)
    return "".join(_ALPHABET[(value >> (5 * (length - 1 - i))) & 31] for i in range(length))


def new_id(prefix: str) -> str:
    """Return ``<prefix>_<12 random base32 chars>``."""
    _check_prefix(prefix)
    return prefix + "_" + "".join(secrets.choice(_ALPHABET) for _ in range(_ID_CHARS))


def content_id(prefix: str, *parts: str) -> str:
    """Deterministic id: ``<prefix>_`` + 12 base32 chars of ``sha1("|".join(parts))``.

    Example: ``content_id("itm", doc_id, slot_key)``. The same parts always give the same id.
    """
    _check_prefix(prefix)
    digest = hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).digest()
    return prefix + "_" + _base32(digest)


def doc_id_for_sha(sha256_hex: str) -> str:
    """Document id for a file: ``doc_`` + the first 12 base32 chars of its SHA-256 digest."""
    try:
        raw = bytes.fromhex(sha256_hex)
    except ValueError as exc:
        raise ValueError(f"not a hex SHA-256 digest: {sha256_hex!r}") from exc
    if len(raw) != hashlib.sha256().digest_size:
        raise ValueError(f"not a SHA-256 digest (expected 64 hex chars): {sha256_hex!r}")
    return "doc_" + _base32(raw)


def prefix_of(identifier: str) -> str:
    return identifier.split("_", 1)[0]
