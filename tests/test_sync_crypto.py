"""The sync folder's keys, names and sealing (design §4.2-4.3; review findings 8, 17, 26; F24)."""

from __future__ import annotations

import hashlib
import io
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from fakes import use_fast_keys
from ordnung.backup.container import KeyedWriter
from ordnung.sync import (
    CHUNK,
    KEY_FILE_BYTES,
    MIN_PADDED,
    SYNC_KDF,
    NewerSyncFolder,
    NotArrived,
    WrongSyncPassphrase,
    crypto,
    passphrase_bits,
    passphrase_problem,
)
from ordnung.sync.crypto import (
    Damaged,
    Vault,
    derive_kek,
    new_key_file,
    open_key_file,
    padded_size,
    padme,
    sealed_size,
    sealed_size_of,
)

PASS = "orbit velvet canyon maple thunder"


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fast_keys(monkeypatch)


def vault() -> Vault:
    return Vault(os.urandom(16), os.urandom(32))


# --------------------------------------------------------------------------------------------------
# the key file
# --------------------------------------------------------------------------------------------------


def test_the_key_file_round_trips_and_holds_no_plaintext() -> None:
    made = new_key_file(PASS)
    assert len(made.data) == KEY_FILE_BYTES == 92
    assert len(made.name) == 32 and int(made.name, 16) >= 0
    opened = open_key_file(made.name, made.data, PASS)
    assert opened.vault_id == made.vault.vault_id and opened.vault_key == made.vault.vault_key
    for secret in (made.vault.vault_id, made.vault.vault_key, PASS.encode(), b"\x01" + made.vault.vault_id):
        assert secret not in made.data


def test_a_wrong_passphrase_is_refused_before_anything_is_stored() -> None:  # F24
    made = new_key_file(PASS)
    with pytest.raises(WrongSyncPassphrase, match="doesn't open this folder"):
        open_key_file(made.name, made.data, "orbit velvet canyon maple thundeR")


def test_the_key_file_name_is_its_salt() -> None:
    made = new_key_file(PASS)
    renamed = "0" * 32
    with pytest.raises(WrongSyncPassphrase):
        open_key_file(renamed, made.data, PASS)


@pytest.mark.parametrize("size", [0, 1, 91, 93, 200])
def test_a_key_file_of_another_size_has_not_arrived(size: int) -> None:
    made = new_key_file(PASS)
    data = (made.data * 3)[:size]
    with pytest.raises(NotArrived):
        open_key_file(made.name, data, PASS)


def test_a_newer_folder_format_says_update() -> None:
    made = new_key_file(PASS)
    nonce = os.urandom(12)
    body = bytes([2]) + os.urandom(48) + bytes(15)
    data = nonce + AESGCM(derive_kek(PASS, made.name)).encrypt(
        nonce, body, b"ordnung-sync/1 key" + made.name.encode()
    )
    with pytest.raises(NewerSyncFolder, match="Update Ordnung"):
        open_key_file(made.name, data, PASS)


def test_the_kdf_is_scrypt_2_18_r_8_within_the_readers_cap() -> None:  # finding 17
    assert (SYNC_KDF.log2_n, SYNC_KDF.r, SYNC_KDF.p) == (18, 8, 1)
    assert SYNC_KDF.memory == 256 * 1024 * 1024
    SYNC_KDF.check()


def test_passphrase_rule_for_a_new_folder() -> None:  # finding 17
    assert passphrase_problem(PASS) is None
    assert passphrase_bits(PASS) >= 70
    assert passphrase_problem("correct horse battery staple") is not None  # four words
    assert passphrase_problem("abcdefghijklmnopqrstuvwxyz") is not None  # one long run
    assert passphrase_problem("horse horse horse horse horse") is not None  # one word, repeated
    assert passphrase_problem("CorrectHorseBatteryStapleMoon") is None  # camel case splits


# --------------------------------------------------------------------------------------------------
# sizes (finding 8)
# --------------------------------------------------------------------------------------------------


def test_padme_clears_the_low_bits() -> None:
    assert padme(1_000_000) == 1_015_808
    assert padded_size(0) == MIN_PADDED == 4096
    previous = 0
    for length in [*range(4096, 70_000, 997), *range(1 << 20, 40 << 20, 1_234_567)]:
        padded = padme(length)
        assert padded >= length and padded >= previous
        assert padded - length <= 0.12 * length
        previous = padded


@pytest.mark.parametrize("k", [1, 2, 3])
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_sealed_size_counts_a_full_last_chunk_once(k: int, delta: int) -> None:
    plain = k * CHUNK + delta
    out = io.BytesIO()
    writer = KeyedWriter(out, os.urandom(32), prefix=os.urandom(7), aad=b"")
    writer.write(bytes(plain))
    writer.close()
    assert 23 + len(out.getvalue()) == sealed_size(plain)
    assert sealed_size(plain) == 23 + plain + 16 * max(1, -(-plain // CHUNK))


@pytest.mark.parametrize("plain", [0, 1])
def test_sealed_size_of_tiny(plain: int) -> None:
    assert sealed_size(plain) == 23 + plain + 16


@pytest.mark.parametrize(
    "length", [0, 1, 4087, 4088, 4089, CHUNK - 9, CHUNK - 8, CHUNK - 7, CHUNK, CHUNK + 1, 3 * CHUNK]
)
def test_seal_and_open_round_trip_at_every_boundary(length: int) -> None:
    keys = vault()
    data = os.urandom(length)
    name = keys.object_name("f", hashlib.sha256(data).hexdigest())
    sealed = keys.seal("f", name, data)
    assert len(sealed) == sealed_size_of(length)
    assert keys.open("f", name, sealed) == data
    assert data[:64] not in sealed or length < 16


# --------------------------------------------------------------------------------------------------
# what authentication binds
# --------------------------------------------------------------------------------------------------


def test_every_changed_byte_fails() -> None:
    keys = vault()
    data = os.urandom(5000)
    name = keys.object_name("f", hashlib.sha256(data).hexdigest())
    sealed = keys.seal("f", name, data)
    rng = __import__("random").Random(7)
    positions = sorted({0, 15, 16, 22, 23, 24, len(sealed) - 1, *rng.sample(range(len(sealed)), 40)})
    for position in positions:
        tampered = bytearray(sealed)
        tampered[position] ^= 0x01
        with pytest.raises(Damaged):
            keys.open("f", name, bytes(tampered))


def test_cut_or_appended_files_fail() -> None:
    keys = vault()
    data = os.urandom(3 * CHUNK + 5)
    name = keys.object_name("d", hashlib.sha256(data).hexdigest())
    sealed = keys.seal("d", name, data)
    for cut in (len(sealed) - 1, len(sealed) - 16, CHUNK + 16 + 23, 100, 23):
        with pytest.raises(Damaged):
            keys.open("d", name, sealed[:cut])
    with pytest.raises(Damaged):
        keys.open("d", name, sealed + b"\x00")


def test_names_kinds_and_vaults_are_bound() -> None:
    keys, other = vault(), vault()
    data = b"a manifest"
    name = keys.object_name("m", hashlib.sha256(data).hexdigest())
    sealed = keys.seal("m", name, data)
    with pytest.raises(Damaged):
        keys.open("b", name, sealed)  # another kind
    with pytest.raises(Damaged):
        keys.open("m", "0" * 32, sealed)  # renamed
    with pytest.raises(Damaged):
        other.open("m", name, sealed)  # another folder


def test_names_are_keyed() -> None:
    a, b = vault(), vault()
    sha = hashlib.sha256(b"the same letter").hexdigest()
    assert a.object_name("f", sha) == a.object_name("f", sha)
    assert a.object_name("f", sha) != b.object_name("f", sha)
    assert a.object_name("f", sha) != a.object_name("d", sha)
    assert sha[:32] not in {a.object_name(k, sha) for k in ("f", "d", "b", "m")}
    computer = os.urandom(16).hex()
    assert a.head_name(computer) != b.head_name(computer) and len(a.temp_tag(computer)) == 8


def test_content_named_objects_seal_to_the_same_bytes_heads_do_not() -> None:  # finding 26
    keys = vault()
    data = os.urandom(10_000)
    name = keys.object_name("f", hashlib.sha256(data).hexdigest())
    assert keys.seal("f", name, data) == keys.seal("f", name, data)
    head = keys.head_name(os.urandom(16).hex())
    assert keys.seal("h", head, b"{}") != keys.seal("h", head, b"{}")


def test_a_damaged_padding_or_length_fails() -> None:
    keys = vault()
    data = b"x" * 100
    name = keys.object_name("b", hashlib.sha256(data).hexdigest())
    out = io.BytesIO()
    # a writer that pads with a non-zero byte
    salt_prefix = keys._salt_prefix("b", name, os.urandom)
    salt, prefix = salt_prefix[:16], salt_prefix[16:]
    out.write(salt_prefix)
    writer = KeyedWriter(out, keys._key("b", salt), prefix=prefix, aad=keys._aad("b", name, salt, prefix))
    writer.write((100).to_bytes(8, "big") + data + b"\x01" + bytes(padded_size(100) - 109))
    writer.close()
    with pytest.raises(Damaged):
        keys.open("b", name, out.getvalue())


def test_sync_kdf_is_patched_in_tests_only() -> None:
    assert crypto.SYNC_KDF.log2_n == 10  # the fixture; the real value is pinned above
