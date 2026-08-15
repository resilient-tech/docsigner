"""Who can sign: USB tokens, and keys sitting on disk.

A throwaway test key is made on first run, so the app works with no token.
Plug a token in and its certificates show up alongside.
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

# A scan is slow (a subprocess, then a walk some drivers drag out for seconds)
# and one sign used to pay for two. So remember it for a moment.
_TOKEN_CACHE_TTL_SECONDS = 30
# Readers ride along with the certificates, from the same scan, so the list and
# the "driver missing" hint can never disagree.
_token_cache: tuple[float, list[dict], list[dict]] | None = None
_token_lock = threading.Lock()


def _token_scan() -> tuple[list[dict], list[dict]]:
    """What is plugged in, remembered briefly. The lock folds parallel calls
    into one scan."""
    global _token_cache
    with _token_lock:
        if _token_cache is not None and _token_cache[0] > time.monotonic():
            return _token_cache[1], _token_cache[2]
        found, readers = _scan_token_identities()
        # Never remember an empty scan. Someone who just plugged a token in has
        # to see it on the next look.
        _token_cache = (
            (time.monotonic() + _TOKEN_CACHE_TTL_SECONDS, found, readers) if found else None
        )
        return found, readers


def _token_identities() -> list[dict]:
    return _token_scan()[0]


def invalidate_token_cache() -> None:
    """Forget what we saw, so the next look asks the device again."""
    global _token_cache
    with _token_lock:
        _token_cache = None


def _scan_token_identities() -> tuple[list[dict], list[dict]]:
    from . import host

    result = host.scan()
    out: list[dict] = []
    for c in result.get("certificates", []):
        tp = c.get("thumbprint")
        # Only the token itself. A driver copies its certificates into the OS
        # store and leaves them there after the token is unplugged.
        if not tp or c.get("source") == "os-store":
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
    """"Your token is in, its driver is missing" when that is what happened.

    The OS can see the token even with no driver, so an empty list splits two
    ways: nothing plugged in, or plugged in and unusable. Only the second is
    worth interrupting someone about, and it is the top reason signing fails
    on a fresh machine.

    None when there is nothing useful to say.
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
        # No download link on purpose. An Indian token's driver comes from the
        # CA that issued it, not the hardware maker, and a wrong link here is
        # worse than none.
        "message": (
            f"{named[0]} detected, but its driver is not installed."
            if named
            else "A token is connected, but no matching driver is installed."
        ),
        "action": "Install the token driver from the CA that issued your DSC, then refresh.",
    }


def _cn_str(subject: str) -> str:
    """Pull the person's name out of the certificate's subject line."""
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
