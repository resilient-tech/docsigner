"""Signing identities: DSC tokens (via the DocSigner host, PKCS#11) and
server-held PKCS#12 keys. A self-signed test key is created on first run so
the app works without a token; plug a token in and its certificates appear.
"""

import datetime
import threading
import time
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
        _make_self_signed(default, "DocSigner Local Test")
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

# One scan costs a host subprocess plus a PKCS#11 walk that slow drivers drag
# out for seconds, and both list_identities and find_identity need one, so a
# single sign used to pay for two. Cache the found set briefly.
#
# Only non-empty results are cached: someone who just plugged a token in must
# see it on the next look, and an empty scan is exactly the case where they
# are about to. A stale entry after an unplug costs one failed sign, which
# invalidates the cache and reports TOKEN_NOT_FOUND.
_TOKEN_CACHE_TTL_SECONDS = 30
# (expiry, identities, readers). Readers ride along so the "driver missing"
# hint comes from the same scan the certificate list did, and the two cannot
# disagree.
_token_cache: tuple[float, list[dict], list[dict]] | None = None
_token_lock = threading.Lock()


def _token_scan() -> tuple[list[dict], list[dict]]:
    """(identities, readers), cached briefly. The lock also collapses the
    concurrent calls FastAPI's threadpool allows into one scan."""
    global _token_cache
    with _token_lock:
        if _token_cache is not None and _token_cache[0] > time.monotonic():
            return _token_cache[1], _token_cache[2]
        found, readers = _scan_token_identities()
        # Only a productive scan is cached: someone who just plugged a token in,
        # or just installed its driver, must see it on the next look, and an
        # empty scan is exactly when they are about to.
        _token_cache = (
            (time.monotonic() + _TOKEN_CACHE_TTL_SECONDS, found, readers) if found else None
        )
        return found, readers


def _token_identities() -> list[dict]:
    return _token_scan()[0]


def invalidate_token_cache() -> None:
    """Drop the cached scan, so the next look re-reads the device."""
    global _token_cache
    with _token_lock:
        _token_cache = None


def _scan_token_identities() -> tuple[list[dict], list[dict]]:
    from . import host

    result = host.scan()
    out: list[dict] = []
    for c in result.get("certificates", []):
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
    return out, result.get("readers", [])


def token_hint() -> dict | None:
    """"Your token is plugged in, its driver is not installed", when that is
    what happened.

    The host sees readers through the OS smart-card service, which reports a
    USB token's name from its descriptor with no vendor driver present. So an
    empty certificate list can be told apart: nothing plugged in, or plugged in
    and unusable. Only the second is worth interrupting someone about, and it
    is the single most common reason signing does not work on a fresh machine.

    None when there is nothing to say: certificates were found, no reader is
    connected, or a driver is installed and the token is simply not readable
    (a different problem, already covered by the error the sign attempt gives).
    """
    identities, readers = _token_scan()
    if identities:
        return None
    missing = [r for r in readers if not r.get("driverFound")]
    if not missing:
        return None

    named = [r["token"] for r in missing if r.get("token")]
    return {
        "token": named[0] if named else None,
        "readers": [r.get("name", "") for r in missing],
        # No vendor URL: an Indian DSC's driver comes from the CA that issued
        # it, not from whoever made the hardware, and a wrong link for security
        # middleware is worse than no link.
        "message": (
            f"{named[0]} detected, but its driver is not installed."
            if named
            else "A token is connected, but no matching driver is installed."
        ),
        "action": "Install the token driver from the CA that issued your DSC, then refresh.",
    }


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
