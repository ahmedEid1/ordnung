"""The phone listener's certificates: a small authority for one address, and the server certificate it
issues (policy: :mod:`ordnung.phone`).

* **An authority for exactly one address.** The authority's name constraints permit only the bound
  address (``IPAddress(<address>/32)``) and the reserved DNS name ``invalid`` (so no DNS name at all):
  a phone that trusts it can't be fooled into trusting any other device on the network — the router,
  a NAS — nor any website, even by someone who copies ``ca.key`` from a backup of the computer. A new
  address therefore makes a new authority (the person is told to install it and remove the old one);
  renewing the server certificate at the same address keeps it, so a phone that trusts it notices
  nothing.
* **Nothing in a name says what this is.** The certificates are sent to anyone on the network who opens
  a connection, so their names are neutral (“Home network certificate 7K3M”), with no host, person or
  product in them. A certificate's common name must not look like a host either: OpenSSL checks a
  dotted name against the DNS constraint and refuses it.
* **Files, private.** ``<data>/phone/`` (``0700``) holds ``ca.pem``, ``ca.key``, ``server.pem`` (the
  server certificate followed by the authority's) and ``server.key``, each ``0600`` and written
  atomically; never in the database or a backup, so a restored copy never presents the original's
  identity. Keys are EC P-256.
* **Renewal.** The server certificate lasts :data:`LEAF_DAYS` (within what phones accept) and is made
  again :data:`RENEW_BEFORE_DAYS` before it ends, or at once when its files are unreadable, its key
  doesn't match, it names another address or another authority issued it.
* **Fingerprints** are SHA-256 as upper-case byte pairs (``F2 08 81 E8 …``); the computer shows them
  so a person can compare what the phone shows. No HSTS, ever (it would make the one warning
  impossible to pass, and browsers ignore it for addresses anyway).
"""

from __future__ import annotations

import contextlib
import ipaddress
import os
import secrets
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from ordnung.config import private_dir

CA_DAYS = 3650
LEAF_DAYS = 397
RENEW_BEFORE_DAYS = 30
CA_FILE = "ca.pem"
CA_KEY_FILE = "ca.key"
SERVER_FILE = "server.pem"
SERVER_KEY_FILE = "server.key"
CA_NAME_PREFIX = "Home network certificate"
SERVER_NAME_PREFIX = "Home network server"
_TAG_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_BACKDATE = timedelta(hours=1)
_FILE_MODE = 0o600


@dataclass(frozen=True)
class Certificates:
    """What Settings → Phone shows of the certificates (and what the listener loads)."""

    fingerprint: str
    ca_fingerprint: str
    ca_made_at: str
    until: str
    server_pem: Path
    server_key: Path
    made_ca: bool = False
    made_server: bool = False


def fingerprint(cert: x509.Certificate) -> str:
    """SHA-256 of the certificate as upper-case byte pairs (``F2 08 81 E8 …``)."""
    return " ".join(f"{byte:02X}" for byte in cert.fingerprint(hashes.SHA256()))


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tag() -> str:
    return "".join(secrets.choice(_TAG_ALPHABET) for _ in range(4))


def _write_private(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically, readable by its owner only (never through a link)."""
    partial = path.with_name(f".{path.name}.{secrets.token_hex(4)}.part")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(partial, flags, _FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        partial.replace(path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()


def _pem_key(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


def _usage(*, sign_certs: bool) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=not sign_certs,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=sign_certs,
        crl_sign=sign_certs,
        encipher_only=False,
        decipher_only=False,
    )


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def make_ca(address: str, now: datetime) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    """A new authority that may sign for ``address`` only (and for no DNS name)."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = _name(f"{CA_NAME_PREFIX} {_tag()}")
    permitted: list[x509.GeneralName] = [
        x509.IPAddress(ipaddress.ip_network(f"{address}/32")),
        x509.DNSName("invalid"),
    ]
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _BACKDATE)
        .not_valid_after(now + timedelta(days=CA_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(_usage(sign_certs=True), critical=True)
        .add_extension(
            x509.NameConstraints(permitted_subtrees=permitted, excluded_subtrees=None), critical=True
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def make_server_certificate(
    ca_key: ec.EllipticCurvePrivateKey, ca: x509.Certificate, address: str, now: datetime
) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    """A server certificate for ``address``, issued by ``ca`` (a new key every time)."""
    key = ec.generate_private_key(ec.SECP256R1())
    tag = str(ca.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value).rsplit(" ", 1)[-1]
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(f"{SERVER_NAME_PREFIX} {tag}"))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _BACKDATE)
        .not_valid_after(now + timedelta(days=LEAF_DAYS))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(_usage(sign_certs=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _read_cert(path: Path) -> x509.Certificate | None:
    try:
        return x509.load_pem_x509_certificate(path.read_bytes())
    except (OSError, ValueError):
        return None


def _read_key(path: Path) -> ec.EllipticCurvePrivateKey | None:
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError):
        return None
    return key if isinstance(key, ec.EllipticCurvePrivateKey) else None


def _same_key(key: ec.EllipticCurvePrivateKey, cert: x509.Certificate) -> bool:
    raw = serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    return key.public_key().public_bytes(*raw) == cert.public_key().public_bytes(*raw)


def permitted_address(ca: x509.Certificate) -> str | None:
    """The one address an authority made here may sign for (``None``: not one of ours)."""
    try:
        constraints = ca.extensions.get_extension_for_class(x509.NameConstraints).value
    except x509.ExtensionNotFound:
        return None
    networks = [
        name.value
        for name in constraints.permitted_subtrees or ()
        if isinstance(name, x509.IPAddress) and isinstance(name.value, ipaddress.IPv4Network)
    ]
    if len(networks) != 1 or networks[0].prefixlen != 32:
        return None
    return str(networks[0].network_address)


def _san_addresses(cert: x509.Certificate) -> list[str]:
    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return []
    return [str(value) for value in san.get_values_for_type(x509.IPAddress)]


def _server_is_good(
    key: ec.EllipticCurvePrivateKey | None,
    cert: x509.Certificate | None,
    ca: x509.Certificate,
    address: str,
    now: datetime,
) -> bool:
    if key is None or cert is None or not _same_key(key, cert):
        return False
    if cert.issuer != ca.subject or _san_addresses(cert) != [address]:
        return False
    try:
        cert.verify_directly_issued_by(ca)
    except (ValueError, TypeError, InvalidSignature):
        return False
    return cert.not_valid_after_utc - now > timedelta(days=RENEW_BEFORE_DAYS)


def ensure(folder: Path, address: str, *, now: datetime | None = None) -> Certificates:
    """The authority and server certificate for ``address`` in ``folder``, made or renewed as needed."""
    moment = now or datetime.now(UTC)
    private_dir(folder)
    ca_path, ca_key_path = folder / CA_FILE, folder / CA_KEY_FILE
    server_path, server_key_path = folder / SERVER_FILE, folder / SERVER_KEY_FILE
    ca, ca_key = _read_cert(ca_path), _read_key(ca_key_path)
    made_ca = (
        ca is None
        or ca_key is None
        or not _same_key(ca_key, ca)
        or permitted_address(ca) != address
        or ca.not_valid_after_utc - moment <= timedelta(days=LEAF_DAYS + RENEW_BEFORE_DAYS)
    )
    if made_ca or ca is None or ca_key is None:
        ca_key, ca = make_ca(address, moment)
        _write_private(ca_key_path, _pem_key(ca_key))
        _write_private(ca_path, ca.public_bytes(serialization.Encoding.PEM))
        made_ca = True
    server_key = _read_key(server_key_path)
    leaf_pem = _read_cert(server_path)
    made_server = made_ca or not _server_is_good(server_key, leaf_pem, ca, address, moment)
    if made_server or server_key is None or leaf_pem is None:
        server_key, leaf_pem = make_server_certificate(ca_key, ca, address, moment)
        chain = leaf_pem.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(
            serialization.Encoding.PEM
        )
        _write_private(server_key_path, _pem_key(server_key))
        _write_private(server_path, chain)
        made_server = True
    return Certificates(
        fingerprint=fingerprint(leaf_pem),
        ca_fingerprint=fingerprint(ca),
        ca_made_at=_iso(ca.not_valid_before_utc + _BACKDATE),
        until=leaf_pem.not_valid_after_utc.date().isoformat(),
        server_pem=server_path,
        server_key=server_key_path,
        made_ca=made_ca,
        made_server=made_server,
    )


def read(folder: Path, address: str | None) -> Certificates | None:
    """The certificates as they are (nothing is made; ``None`` when there are none for ``address``)."""
    if address is None:
        return None
    ca, leaf = _read_cert(folder / CA_FILE), _read_cert(folder / SERVER_FILE)
    if ca is None or leaf is None or permitted_address(ca) != address:
        return None
    return Certificates(
        fingerprint=fingerprint(leaf),
        ca_fingerprint=fingerprint(ca),
        ca_made_at=_iso(ca.not_valid_before_utc + _BACKDATE),
        until=leaf.not_valid_after_utc.date().isoformat(),
        server_pem=folder / SERVER_FILE,
        server_key=folder / SERVER_KEY_FILE,
    )


def authority_der(folder: Path) -> bytes | None:
    """The authority as DER, for a phone that chooses to trust it (``None``: there is none)."""
    ca = _read_cert(folder / CA_FILE)
    return None if ca is None else ca.public_bytes(serialization.Encoding.DER)


def remove(folder: Path) -> None:
    """Delete the certificates and keys ("Start over")."""
    if folder.is_dir() and not folder.is_symlink():
        shutil.rmtree(folder)
    elif folder.exists() or folder.is_symlink():
        folder.unlink()
