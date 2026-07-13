"""Signing identities: DSC tokens (via the OpenSigner host, PKCS#11) and
server-held PKCS#12 keys. A self-signed test key is created on first run so
the app works without a token; plug a token in and its certificates appear.
"""

import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID


# ---- server-held PKCS#12 keys --------------------------------------------

def ensure_default_key(keys_dir: Path) -> Path:
    keys_dir.mkdir(parents=True, exist_ok=True)
    default = keys_dir / "local-test-key.p12"
    if not default.exists():
        _make_self_signed(default, "OpenSigner Local Test")
    return default


def _make_self_signed(path: Path, common_name: str) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )
    blob = pkcs12.serialize_key_and_certificates(
        name=common_name.encode(), key=key, cert=cert, cas=None,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.write_bytes(blob)


def _p12_identities(keys_dir: Path) -> list[dict]:
    ensure_default_key(keys_dir)
    out = []
    for p in sorted(keys_dir.glob("*.p12")):
        info = _read_p12(p)
        if info:
            out.append({"id": p.stem, "kind": "p12", "path": str(p), **info})
    return out


def _read_p12(path: Path) -> dict | None:
    try:
        _key, cert, _ca = pkcs12.load_key_and_certificates(path.read_bytes(), None)
    except Exception:
        return None  # passphrase-protected keys need a prompt (not in v1)
    if cert is None:
        return None
    not_after = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
    return {
        "name": _cn(cert.subject) or path.stem,
        "issuer": _cn(cert.issuer),
        "notAfter": not_after.date().isoformat(),
        "selfSigned": cert.subject == cert.issuer,
    }


def _cn(name: x509.Name) -> str:
    try:
        return name.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    except Exception:
        return ""


# ---- DSC token certificates (via the native host) -------------------------

def _token_identities() -> list[dict]:
    from . import host

    out: list[dict] = []
    for c in host.list_certificates():
        tp = c.get("thumbprint")
        if not tp:
            continue
        out.append({
            "id": f"token:{tp}",
            "kind": "token",
            "thumbprint": tp,
            "certificate": c.get("certificate"),
            "name": _cn_str(c.get("subject", "")) or c.get("subject", ""),
            "issuer": _cn_str(c.get("issuer", "")),
            "notAfter": (c.get("validTo") or "")[:10],
            "selfSigned": False,
        })
    return out


def _cn_str(subject: str) -> str:
    """Pull CN from a "CN=Name, O=..." string the host returns."""
    for part in subject.split(","):
        part = part.strip()
        if part.upper().startswith("CN="):
            return part[3:]
    return ""


# ---- lookup ---------------------------------------------------------------

def list_identities(keys_dir: Path) -> list[dict]:
    return _token_identities() + _p12_identities(keys_dir)


def find_identity(keys_dir: Path, identity_id: str) -> dict | None:
    if identity_id and identity_id.startswith("token:"):
        return next((t for t in _token_identities() if t["id"] == identity_id), None)
    p = keys_dir / f"{identity_id}.p12"
    if p.exists():
        return {"id": identity_id, "kind": "p12", "path": str(p), **(_read_p12(p) or {})}
    return None
