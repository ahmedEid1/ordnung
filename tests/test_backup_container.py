"""The encrypted backup container: round trips, the header, and every way a file can be wrong
(wrong passphrase, changed bytes, cut short, reordered, grown, newer format, hostile parameters)."""

from __future__ import annotations

import io
import struct

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ordnung.backup import container
from ordnung.backup.container import (
    FORMAT_VERSION,
    HEADER_BYTES,
    MAGIC,
    MIN_CHUNK_SIZE,
    TAG_BYTES,
    DamagedBackup,
    EncryptedReader,
    EncryptedWriter,
    KdfParams,
    NewerBackupFormat,
    NotABackup,
    WrongPassphrase,
    read_header,
)

FAST = KdfParams(log2_n=10, r=8, p=1)
CHUNK = MIN_CHUNK_SIZE
PASS = "correct horse battery staple"


def seal(data: bytes, passphrase: str = PASS, *, chunk_size: int = CHUNK, kdf: KdfParams = FAST) -> bytes:
    out = io.BytesIO()
    writer = EncryptedWriter(out, passphrase, kdf=kdf, chunk_size=chunk_size)
    # uneven writes: chunking must not depend on how the caller slices the data
    for start in range(0, len(data), 1000):
        writer.write(data[start : start + 1000])
    writer.close()
    return out.getvalue()


def open_all(sealed: bytes, passphrase: str = PASS) -> bytes:
    reader = EncryptedReader(io.BytesIO(sealed), passphrase)
    return reader.read()


def chunks_of(sealed: bytes, chunk_size: int = CHUNK) -> list[bytes]:
    body = sealed[HEADER_BYTES:]
    size = chunk_size + TAG_BYTES
    return [body[i : i + size] for i in range(0, len(body), size)]


# --------------------------------------------------------------------------------------------------
# round trips
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("size", [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 3 * CHUNK, 3 * CHUNK + 17])
def test_round_trip_at_every_chunk_boundary(size: int) -> None:
    data = bytes(range(256)) * (size // 256 + 1)
    data = data[:size]
    sealed = seal(data)
    assert open_all(sealed) == data
    # every chunk but the last is full; the last holds 0..chunk bytes
    expected_chunks = max(1, -(-size // CHUNK))
    assert len(chunks_of(sealed)) == expected_chunks
    assert len(sealed) == HEADER_BYTES + size + TAG_BYTES * expected_chunks


def test_small_reads_return_the_same_bytes() -> None:
    data = b"ordnung " * 3000
    reader = EncryptedReader(io.BytesIO(seal(data)), PASS)
    got = bytearray()
    while piece := reader.read(7):
        got += piece
    assert bytes(got) == data
    assert reader.read() == b""


def test_the_header_records_the_parameters() -> None:
    sealed = seal(b"x", kdf=KdfParams(log2_n=11, r=4, p=2), chunk_size=8192)
    header = read_header(io.BytesIO(sealed))
    assert sealed.startswith(MAGIC + bytes([FORMAT_VERSION]))
    assert header.version == FORMAT_VERSION
    assert header.kdf == KdfParams(log2_n=11, r=4, p=2)
    assert header.chunk_size == 8192
    assert len(header.salt) == 16 and len(header.nonce_prefix) == 7
    assert open_all(sealed) == b"x"


def test_two_backups_of_the_same_data_differ() -> None:
    assert seal(b"same") != seal(b"same")  # a fresh salt and nonce prefix every time


def test_the_default_key_costs_are_the_documented_ones() -> None:
    assert container.DEFAULT_KDF == KdfParams(log2_n=17, r=8, p=1)
    assert container.CHUNK_SIZE == 1024 * 1024


def test_the_passphrase_is_read_in_unicode_nfc() -> None:
    composed, decomposed = "Café-Straße 12!", "Café-Straße 12!"
    assert composed != decomposed
    assert open_all(seal(b"data", composed), decomposed) == b"data"


def test_the_passphrase_is_not_trimmed() -> None:
    sealed = seal(b"data", "  spaces count  ")
    with pytest.raises(WrongPassphrase):
        open_all(sealed, "spaces count")


def test_an_empty_passphrase_is_refused() -> None:
    with pytest.raises(container.BackupError):
        EncryptedWriter(io.BytesIO(), "", kdf=FAST)


# --------------------------------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------------------------------


def test_a_wrong_passphrase_is_refused_before_anything_is_decrypted() -> None:
    with pytest.raises(WrongPassphrase):
        EncryptedReader(io.BytesIO(seal(b"secret")), "correct horse battery stapl")


@pytest.mark.parametrize("blob", [b"", b"%PDF-1.7\n", b"ORDNUNG-BACKUP", b"SQLite format 3\x00" * 4])
def test_other_files_are_not_backups(blob: bytes) -> None:
    with pytest.raises(NotABackup):
        EncryptedReader(io.BytesIO(blob), PASS)


def test_a_newer_format_is_refused_before_any_key_is_derived(monkeypatch: pytest.MonkeyPatch) -> None:
    sealed = bytearray(seal(b"x"))
    sealed[len(MAGIC)] = FORMAT_VERSION + 1

    def no_key(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("scrypt must not run for a newer format")

    monkeypatch.setattr(container, "_derive", no_key)
    with pytest.raises(NewerBackupFormat, match="newer version of Ordnung"):
        EncryptedReader(io.BytesIO(bytes(sealed)), PASS)


def _with_params(sealed: bytes, **fields: int) -> bytes:
    header = read_header(io.BytesIO(sealed))
    values = {
        "log2_n": header.kdf.log2_n,
        "r": header.kdf.r,
        "p": header.kdf.p,
        "chunk_size": header.chunk_size,
        "kdf": container.KDF_SCRYPT,
    } | fields
    params = struct.pack(
        ">BBBB16s7sI",
        values["kdf"],
        values["log2_n"],
        values["r"],
        values["p"],
        header.salt,
        header.nonce_prefix,
        values["chunk_size"],
    )
    return MAGIC + bytes([header.version]) + params + header.mac + sealed[HEADER_BYTES:]


@pytest.mark.parametrize(
    "fields",
    [
        {"log2_n": 30},  # 128 GiB of scrypt memory
        {"log2_n": 20, "r": 16},  # 2 GiB, inside the old per-field ranges
        {"log2_n": 19, "r": 8},  # 512 MiB
        {"log2_n": 18, "r": 9},  # just over 256 MiB
        {"log2_n": 9},
        {"r": 0},
        {"r": 200},
        {"p": 3},  # three times the work of p=1, before the MAC can say the passphrase is wrong
        {"p": 64},
        {"chunk_size": 16},
        {"chunk_size": 2**31},
        {"kdf": 2},
    ],
)
def test_hostile_header_parameters_are_refused_before_scrypt_runs(
    fields: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    crafted = _with_params(seal(b"x"), **fields)

    def no_key(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("scrypt must not run for a hostile header")

    monkeypatch.setattr(container, "_derive", no_key)
    with pytest.raises(DamagedBackup):
        EncryptedReader(io.BytesIO(crafted), PASS)


@pytest.mark.parametrize(("log2_n", "r", "p"), [(17, 8, 1), (18, 8, 2), (20, 2, 1), (10, 16, 2), (11, 4, 2)])
def test_key_settings_up_to_256_mib_and_p_2_are_read(log2_n: int, r: int, p: int) -> None:
    kdf = KdfParams(log2_n=log2_n, r=r, p=p)
    kdf.check()
    assert kdf.memory <= container.MAX_SCRYPT_BYTES == 256 * 1024 * 1024


def test_the_documented_bound_is_the_checked_one() -> None:
    assert container.DEFAULT_KDF.memory == 128 * 1024 * 1024  # what a written backup costs
    assert "256 MiB" in (container.__doc__ or "") and "gigabytes" not in (container.__doc__ or "")


def test_valid_but_different_header_parameters_fail_the_mac() -> None:
    crafted = _with_params(seal(b"x"), log2_n=11)
    with pytest.raises(WrongPassphrase):
        EncryptedReader(io.BytesIO(crafted), PASS)


@pytest.mark.parametrize("cut", [len(MAGIC), len(MAGIC) + 1, len(MAGIC) + 5, HEADER_BYTES - 1])
def test_a_cut_header_is_damaged(cut: int) -> None:
    with pytest.raises(DamagedBackup, match="cut short"):
        EncryptedReader(io.BytesIO(seal(b"x")[:cut]), PASS)


def test_changing_the_salt_or_nonce_prefix_reads_as_a_wrong_passphrase() -> None:
    sealed = seal(b"data")
    for offset in (len(MAGIC) + 6, len(MAGIC) + 1 + 4 + 16 + 1, HEADER_BYTES - 1):
        changed = bytearray(sealed)
        changed[offset] ^= 0x01
        with pytest.raises(WrongPassphrase):
            EncryptedReader(io.BytesIO(bytes(changed)), PASS)


# --------------------------------------------------------------------------------------------------
# tampering with the body
# --------------------------------------------------------------------------------------------------

DATA = bytes(range(251)) * 70  # ~17.5 KB: five chunks of 4 KiB


def test_a_changed_byte_in_any_chunk_is_detected() -> None:
    sealed = seal(DATA)
    for offset in range(HEADER_BYTES, len(sealed), 997):
        changed = bytearray(sealed)
        changed[offset] ^= 0x80
        with pytest.raises(DamagedBackup, match="changed or damaged"):
            open_all(bytes(changed))


def test_nothing_of_a_damaged_chunk_is_returned() -> None:
    sealed = bytearray(seal(DATA))
    sealed[HEADER_BYTES + CHUNK + TAG_BYTES + 3] ^= 1  # inside the second chunk
    reader = EncryptedReader(io.BytesIO(bytes(sealed)), PASS)
    assert reader.read(CHUNK) == DATA[:CHUNK]  # the first chunk is intact
    with pytest.raises(DamagedBackup):
        reader.read(1)


def test_cut_at_a_chunk_boundary_is_detected() -> None:
    sealed = seal(DATA)
    header, chunks = sealed[:HEADER_BYTES], chunks_of(sealed)
    for keep in range(1, len(chunks)):
        with pytest.raises(DamagedBackup):
            open_all(header + b"".join(chunks[:keep]))


def test_cut_inside_a_chunk_is_detected() -> None:
    sealed = seal(DATA)
    for cut in (HEADER_BYTES, HEADER_BYTES + 5, len(sealed) - 1, len(sealed) - TAG_BYTES):
        with pytest.raises(DamagedBackup):
            open_all(sealed[:cut])


def test_swapped_chunks_are_detected() -> None:
    sealed = seal(DATA)
    header, chunks = sealed[:HEADER_BYTES], chunks_of(sealed)
    swapped = [chunks[1], chunks[0], *chunks[2:]]
    with pytest.raises(DamagedBackup):
        open_all(header + b"".join(swapped))


def test_appended_bytes_or_chunks_are_detected() -> None:
    sealed = seal(DATA)
    chunks = chunks_of(sealed)
    for extra in (b"\x00", b"more data", chunks[0], chunks[-1]):
        with pytest.raises(DamagedBackup):
            open_all(sealed + extra)


def test_a_chunk_from_another_backup_is_detected() -> None:
    one, other = seal(DATA), seal(DATA)
    mixed = one[:HEADER_BYTES] + chunks_of(other)[0] + b"".join(chunks_of(one)[1:])
    with pytest.raises(DamagedBackup):
        open_all(mixed)


def test_the_same_body_under_another_header_fails() -> None:
    one, other = seal(DATA), seal(DATA)
    with pytest.raises(DamagedBackup):
        open_all(other[:HEADER_BYTES] + one[HEADER_BYTES:])


def test_an_aborted_writer_never_reads_as_complete() -> None:
    out = io.BytesIO()
    writer = EncryptedWriter(out, PASS, kdf=FAST, chunk_size=CHUNK)
    writer.write(DATA)
    writer.abort()
    reader = EncryptedReader(io.BytesIO(out.getvalue()), PASS)
    with pytest.raises(DamagedBackup):
        reader.read()


def test_writing_after_close_is_refused() -> None:
    writer = EncryptedWriter(io.BytesIO(), PASS, kdf=FAST, chunk_size=CHUNK)
    writer.close()
    with pytest.raises(ValueError):
        writer.write(b"late")


def test_read_to_end_counts_and_authenticates_the_rest() -> None:
    reader = EncryptedReader(io.BytesIO(seal(DATA)), PASS)
    reader.read(10)
    assert reader.read_to_end() == len(DATA) - 10


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(data=st.binary(max_size=3 * CHUNK + 50), where=st.integers(min_value=0), bit=st.integers(0, 7))
def test_property_round_trip_and_any_flipped_bit_is_caught(data: bytes, where: int, bit: int) -> None:
    sealed = seal(data)
    assert open_all(sealed) == data
    changed = bytearray(sealed)
    changed[where % len(sealed)] ^= 1 << bit
    with pytest.raises((DamagedBackup, WrongPassphrase, NotABackup, NewerBackupFormat)):
        open_all(bytes(changed))
