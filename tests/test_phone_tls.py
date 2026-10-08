"""Phone access's certificates: an authority for exactly one address (it can vouch for no other device
and no website), a neutral name, private files written atomically, renewal and fingerprints."""

from __future__ import annotations

import ipaddress
import os
import socket
import ssl
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID
from cryptography.x509.verification import PolicyBuilder, Store, VerificationError

from ordnung.phone import tls
from ordnung.phone.access import LIMIT_CONCURRENCY, listener_config

ADDRESS = "192.168.178.23"
NOW = datetime(2026, 10, 7, 8, 0, tzinfo=UTC)


def _load(path: Path) -> x509.Certificate:
    return x509.load_pem_x509_certificates(path.read_bytes())[0]


def _verify(ca: x509.Certificate, leaf: x509.Certificate, address: str) -> bool:
    verifier = (
        PolicyBuilder()
        .store(Store([ca]))
        .time(NOW + timedelta(days=1))
        .build_server_verifier(x509.verification.IPAddress(ipaddress.ip_address(address)))
    )
    try:
        verifier.verify(leaf, [])
    except VerificationError:
        return False
    return True


def _dns_leaf(ca_key: object, ca: x509.Certificate, name: str) -> x509.Certificate:
    key, leaf = tls.make_server_certificate(ca_key, ca, ADDRESS, NOW)  # type: ignore[arg-type]
    del key
    builder = (
        x509.CertificateBuilder()
        .subject_name(leaf.subject)
        .issuer_name(ca.subject)
        .public_key(leaf.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(NOW - timedelta(hours=1))
        .not_valid_after(NOW + timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
    )
    from cryptography.hazmat.primitives import hashes

    return builder.sign(ca_key, hashes.SHA256())  # type: ignore[arg-type]


def test_the_authority_may_vouch_for_one_address_only() -> None:
    ca_key, ca = tls.make_ca(ADDRESS, NOW)
    basic = ca.extensions.get_extension_for_class(x509.BasicConstraints)
    assert basic.critical and basic.value.ca and basic.value.path_length == 0
    usage = ca.extensions.get_extension_for_class(x509.KeyUsage)
    assert usage.critical and usage.value.key_cert_sign and usage.value.crl_sign
    constraints = ca.extensions.get_extension_for_class(x509.NameConstraints)
    assert constraints.critical
    assert constraints.value.permitted_subtrees == [
        x509.IPAddress(ipaddress.ip_network(f"{ADDRESS}/32")),
        x509.DNSName("invalid"),
    ]
    assert tls.permitted_address(ca) == ADDRESS
    for address in (ADDRESS, "192.168.178.1", "192.168.1.10", "10.0.0.2", "8.8.8.8"):
        _key, leaf = tls.make_server_certificate(ca_key, ca, address, NOW)
        assert _verify(ca, leaf, address) is (address == ADDRESS), address


def test_the_authority_vouches_for_no_website() -> None:
    ca_key, ca = tls.make_ca(ADDRESS, NOW)
    leaf = _dns_leaf(ca_key, ca, "bank.example")
    verifier = (
        PolicyBuilder()
        .store(Store([ca]))
        .time(NOW)
        .build_server_verifier(x509.verification.DNSName("bank.example"))
    )
    with pytest.raises(VerificationError):
        verifier.verify(leaf, [])


def test_names_are_neutral_and_never_look_like_a_host() -> None:
    ca_key, ca = tls.make_ca(ADDRESS, NOW)
    _key, leaf = tls.make_server_certificate(ca_key, ca, ADDRESS, NOW)
    for cert in (ca, leaf):
        (name,) = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        value = str(name.value)
        assert value.startswith(("Home network certificate ", "Home network server "))
        assert "." not in value and "Ordnung" not in value and ADDRESS not in value
    assert str(ca.subject.rfc4514_string()).split()[-1] == str(leaf.subject.rfc4514_string()).split()[-1]


def _handshake(ca_pem: Path, chain_pem: Path, key_pem: Path, address: str) -> str:
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(chain_pem, key_pem)
    listener = socket.socket()
    listener.bind((address, 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def accept() -> None:
        connection, _ = listener.accept()
        try:
            server.wrap_socket(connection, server_side=True).close()
        except (ssl.SSLError, OSError):
            connection.close()

    thread = threading.Thread(target=accept, daemon=True)
    thread.start()
    client = ssl.create_default_context(cafile=str(ca_pem))
    try:
        with (
            socket.create_connection((address, port), timeout=5) as raw,
            client.wrap_socket(raw, server_hostname=address),
        ):
            return "accepted"
    except ssl.SSLError as exc:
        return f"refused: {exc.verify_message or exc}"
    finally:
        listener.close()
        thread.join(5)


def test_openssl_accepts_the_address_and_refuses_an_authority_for_another(tmp_path: Path) -> None:
    good = tls.ensure(tmp_path / "good", "127.0.0.1")
    assert (
        _handshake(tmp_path / "good" / "ca.pem", good.server_pem, good.server_key, "127.0.0.1") == "accepted"
    )
    # an authority for another address that signed a certificate for this one anyway
    ca_key, ca = tls.make_ca("127.0.0.9", NOW)
    key, leaf = tls.make_server_certificate(ca_key, ca, "127.0.0.1", datetime.now(UTC))
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (folder / "chain.pem").write_bytes(
        leaf.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM)
    )
    (folder / "key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    outcome = _handshake(folder / "ca.pem", folder / "chain.pem", folder / "key.pem", "127.0.0.1")
    assert outcome.startswith("refused") and "subtree" in outcome


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_the_files_are_private_and_written_whole(tmp_path: Path) -> None:
    folder = tmp_path / "phone"
    tls.ensure(folder, ADDRESS)
    assert folder.stat().st_mode & 0o777 == 0o700
    assert sorted(p.name for p in folder.iterdir()) == ["ca.key", "ca.pem", "server.key", "server.pem"]
    for path in folder.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600, path
    chain = x509.load_pem_x509_certificates((folder / "server.pem").read_bytes())
    assert len(chain) == 2 and chain[1] == _load(folder / "ca.pem")


def test_a_link_where_a_file_goes_is_never_followed(tmp_path: Path) -> None:
    folder = tmp_path / "phone"
    folder.mkdir()
    target = tmp_path / "elsewhere.txt"
    target.write_text("keep me", encoding="utf-8")
    (folder / "ca.key").symlink_to(target)
    tls.ensure(folder, ADDRESS)
    assert target.read_text(encoding="utf-8") == "keep me"
    assert not (folder / "ca.key").is_symlink()


def test_renewal_keeps_the_authority_and_a_new_address_replaces_it(tmp_path: Path) -> None:
    folder = tmp_path / "phone"
    first = tls.ensure(folder, ADDRESS, now=NOW)
    assert first.made_ca and first.made_server
    again = tls.ensure(folder, ADDRESS, now=NOW + timedelta(days=100))
    assert not (again.made_ca or again.made_server) and again.fingerprint == first.fingerprint
    due = tls.ensure(folder, ADDRESS, now=NOW + timedelta(days=tls.LEAF_DAYS - tls.RENEW_BEFORE_DAYS + 1))
    assert due.made_server and not due.made_ca and due.ca_fingerprint == first.ca_fingerprint
    (folder / "server.key").write_text("broken", encoding="utf-8")
    broken = tls.ensure(folder, ADDRESS, now=NOW + timedelta(days=101))
    assert broken.made_server and not broken.made_ca
    moved = tls.ensure(folder, "192.168.178.40", now=NOW + timedelta(days=102))
    assert moved.made_ca and moved.ca_fingerprint != first.ca_fingerprint
    assert tls.read(folder, ADDRESS) is None and tls.read(folder, "192.168.178.40") is not None


def test_the_server_certificate_names_the_address_and_lasts_397_days(tmp_path: Path) -> None:
    made = tls.ensure(tmp_path / "phone", ADDRESS, now=NOW)
    leaf = _load(made.server_pem)
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert san.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address(ADDRESS)]
    assert san.get_values_for_type(x509.DNSName) == []
    assert leaf.not_valid_after_utc - leaf.not_valid_before_utc == timedelta(days=tls.LEAF_DAYS, hours=1)
    assert made.until == (NOW + timedelta(days=tls.LEAF_DAYS)).date().isoformat()
    assert not leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca


def test_fingerprints_are_upper_case_byte_pairs(tmp_path: Path) -> None:
    made = tls.ensure(tmp_path / "phone", ADDRESS)
    for value in (made.fingerprint, made.ca_fingerprint):
        pairs = value.split(" ")
        assert len(pairs) == 32 and all(len(p) == 2 and p == p.upper() for p in pairs)
        int(value.replace(" ", ""), 16)
    der = tls.authority_der(tmp_path / "phone")
    assert der is not None and tls.fingerprint(x509.load_der_x509_certificate(der)) == made.ca_fingerprint


def test_starting_over_removes_the_folder(tmp_path: Path) -> None:
    folder = tmp_path / "phone"
    tls.ensure(folder, ADDRESS)
    tls.remove(folder)
    assert not folder.exists() and tls.authority_der(folder) is None


def test_the_listener_config(tmp_path: Path) -> None:
    made = tls.ensure(tmp_path / "phone", "127.0.0.1")
    config = listener_config(lambda *a: None, "127.0.0.1", 8767, made)  # type: ignore[arg-type,return-value]
    assert (config.host, config.port, config.lifespan, config.proxy_headers) == (
        "127.0.0.1",
        8767,
        "off",
        False,
    )
    assert (config.access_log, config.server_header, config.ws, config.log_config) == (
        False,
        False,
        "none",
        None,
    )
    assert config.limit_concurrency == LIMIT_CONCURRENCY == 128
    assert config.timeout_graceful_shutdown == 2
    assert config.ssl is not None and config.ssl.minimum_version == ssl.TLSVersion.TLSv1_2
