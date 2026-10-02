"""Local HTTPS for phones on the same Wi-Fi (browsers allow the microphone only on https or localhost).

On first use the app makes its own certificate authority (CA) for this PC and
a server certificate for the PC's LAN addresses, signed by that CA — the same
idea as ``mkcert``.  A phone that installs the CA certificate (offered on the
connection page) trusts the app's https address without warnings; without it
the phone shows a warning once, which the connection page explains how to pass.

The CA's private key never leaves the PC's config folder.  The server
certificate is re-issued when the PC's LAN address changes.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import json
import socket
from pathlib import Path

from .settings import config_dir

CA_DAYS = 3650
SERVER_DAYS = 397  # Apple platforms reject TLS server certificates valid for longer than 398 days


def cert_dir() -> Path:
    return config_dir() / "certs"


def lan_addresses() -> list[str]:
    """IPv4 addresses a phone on the same network can reach (the default route's address first)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET address: no packet is sent for a UDP connect
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.append(info[4][0])
    except OSError:
        pass
    out = []
    for a in found:
        ip = ipaddress.ip_address(a)
        if ip.is_loopback or ip.is_link_local or a in out:
            continue
        out.append(a)
    return out


def _name(cn: str):
    from cryptography.x509.oid import NameOID
    from cryptography import x509

    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "gyeol studio (this PC only)"), x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _write_key(path: Path, key) -> None:
    from cryptography.hazmat.primitives import serialization

    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _load_ca(d: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key((d / "ca.key").read_bytes(), password=None)
    cert = x509.load_pem_x509_certificate((d / "ca.crt").read_bytes())
    return key, cert


def ensure_ca(d: Path | None = None):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    d = d or cert_dir()
    d.mkdir(parents=True, exist_ok=True)
    if (d / "ca.key").exists() and (d / "ca.crt").exists():
        key, cert = _load_ca(d)
        if cert.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30):
            return key, cert
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    name = _name(f"gyeol studio local CA ({socket.gethostname()[:30]})")
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=CA_DAYS))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    _write_key(d / "ca.key", key)
    from cryptography.hazmat.primitives import serialization

    (d / "ca.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (d / "server.json").unlink(missing_ok=True)  # a new CA invalidates the old server certificate
    return key, cert


def ensure_server_cert(addresses: list[str], d: Path | None = None) -> tuple[Path, Path]:
    """(cert, key) paths for a server certificate covering localhost and ``addresses``; re-issued when they change."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID

    d = d or cert_dir()
    ca_key, ca_cert = ensure_ca(d)
    names = sorted({"localhost", socket.gethostname().split(".")[0] + ".local"})
    ips = sorted({"127.0.0.1", *addresses})
    meta_p, crt_p, key_p = d / "server.json", d / "server.crt", d / "server.key"
    if meta_p.exists() and crt_p.exists() and key_p.exists():
        meta = json.loads(meta_p.read_text())
        cert = x509.load_pem_x509_certificate(crt_p.read_bytes())
        fresh = cert.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=14)
        if fresh and meta.get("ips") == ips and meta.get("names") == names:
            return crt_p, key_p
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.timezone.utc)
    san = [x509.DNSName(n) for n in names] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder().subject_name(_name("gyeol studio")).issuer_name(ca_cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=SERVER_DAYS))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    crt_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _write_key(key_p, key)
    meta_p.write_text(json.dumps({"ips": ips, "names": names}))
    return crt_p, key_p


def ca_pem() -> bytes:
    ensure_ca()
    return (cert_dir() / "ca.crt").read_bytes()


def ca_der() -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    return x509.load_pem_x509_certificate(ca_pem()).public_bytes(serialization.Encoding.DER)


def ca_fingerprint() -> str:
    import hashlib

    h = hashlib.sha256(ca_der()).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, 16, 2))  # first 8 bytes, enough to compare by eye
