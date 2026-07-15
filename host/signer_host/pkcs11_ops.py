"""PKCS#11 operations: certificate listing and hash signing via python-pkcs11."""

import base64
import hashlib
import logging
import os
import threading
import time
from datetime import timezone

import pkcs11
from asn1crypto import algos, x509
from pkcs11 import Attribute, Mechanism, ObjectClass
from pkcs11 import exceptions as p11ex

from . import modules
from .errors import HostError

log = logging.getLogger(__name__)

DIGEST_ALGORITHMS = ("sha256", "sha384", "sha512")

# A hung driver call (stuck C_Initialize, dead USB state) must not cost the
# browser its 120 s native timeout. ponytail: flat per-module budget; the
# abandoned thread stays alive holding the module — the process-level fix is
# the user replugging or the host restarting on reconnect.
SCAN_TIMEOUT_SECONDS = 20

# Successful PINs, cached per token label so a batch of separate signHash
# calls costs one prompt. Memory-only: the cache lives exactly as long as the
# host process, i.e. as long as the extension keeps its native messaging port
# open. ponytail: flat 10-minute TTL, make it configurable if anyone asks.
PIN_CACHE_TTL_SECONDS = 600
_pin_cache = {}  # token label -> (pin, monotonic expiry)


def _cached_pin(label):
    entry = _pin_cache.get(label)
    if entry and entry[1] > time.monotonic():
        return entry[0]
    _pin_cache.pop(label, None)
    return None


def clear_pin_cache():
    _pin_cache.clear()

# OID friendly-name -> short attribute name, CN first ordering handled in _name_to_string.
_NAME_SHORT = {
    "common_name": "CN",
    "organization_name": "O",
    "organizational_unit_name": "OU",
    "country_name": "C",
    "state_or_province_name": "ST",
    "locality_name": "L",
    "email_address": "E",
    "serial_number": "SERIALNUMBER",
    "domain_component": "DC",
    "title": "T",
    "given_name": "G",
    "surname": "SN",
    "pseudonym": "PSEUDONYM",
    "street_address": "STREET",
    "postal_code": "POSTALCODE",
}

_KEY_TYPES = {"rsa": "RSA", "rsassa_pss": "RSA", "ec": "EC"}


def load_library(path):
    """Load a PKCS#11 module, forcing a fresh slot enumeration each scan.

    The browser keeps one host process alive for the whole session, so
    python-pkcs11 runs C_Initialize once and caches the module. Some drivers
    (WatchData ProxKey) enumerate the token only at C_Initialize: after a
    replug or a USB sleep the cached handle reports the token gone, and every
    listCertificates returns empty until the process dies. reinitialize()
    re-runs C_Initialize so a long-lived host scans like a fresh one. Best
    effort: an older python-pkcs11 without it, or a driver that refuses, leaves
    the already-loaded module in place. Kept as a seam so tests fake it.
    """
    lib = pkcs11.lib(path)
    try:
        lib.reinitialize()
    except Exception as exc:
        log.warning("could not reinitialize %s, using the cached handle: %s", path, exc)
    return lib


def _module_tokens(path, stats):
    """Yield each token on one module's slots, counting loaded modules and
    tokens into ``stats``. A module that will not load is logged and yields
    nothing. Shared by the listing scan and the by-thumbprint lookup so both
    walk modules and slots identically."""
    try:
        lib = load_library(path)
    except Exception as exc:
        log.warning("cannot load PKCS#11 module %s: %s", path, exc)
        return
    stats["loaded"] += 1
    for token in _tokens_on(lib, path):
        stats["tokens"] += 1
        yield token


def _iter_tokens(stats):
    """Yield (module_path, token) across all discovered modules.

    stats collects counters so callers can tell "no module loaded" apart from
    "modules loaded but no token present".
    """
    stats.update(configured=0, loaded=0, tokens=0)
    for path in modules.discover_modules():
        stats["configured"] += 1
        for token in _module_tokens(path, stats):
            yield path, token


def _tokens_on(lib, path):
    """Yield the tokens across a module's slots, one slot at a time.

    Some drivers (e.g. WatchData ProxKey) expose several reader slots and
    return CKR_DEVICE_REMOVED for the empty ones. python-pkcs11's get_tokens()
    aborts the whole scan on the first such slot, which hides a real token
    sitting in another slot. Walk the present slots individually and skip the
    ones that raise, so one bad slot never masks a good token.
    """
    try:
        slots = lib.get_slots(token_present=True)
    except Exception as exc:
        log.warning("cannot list slots for %s: %s", path, exc)
        return
    for slot in slots:
        try:
            yield slot.get_token()
        except Exception as exc:
            log.warning("skipping slot %s on %s: %s", getattr(slot, "slot_id", "?"), path, exc)


def _token_label(token):
    label = getattr(token, "label", "") or ""
    return label.strip()


def _attr(obj, attribute):
    """Read one PKCS#11 attribute, returning None when absent or unreadable."""
    try:
        value = obj[attribute]
    except Exception:
        return None
    return value or None


def _iso_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _name_to_string(name):
    """Render an asn1crypto Name as 'CN=..., O=..., C=...' (most specific first)."""
    parts = []
    for rdn in reversed(list(name.chosen)):
        for type_value in rdn:
            key = type_value["type"].native
            value = type_value["value"].native
            if not isinstance(value, str):
                value = str(value)
            parts.append("%s=%s" % (_NAME_SHORT.get(key, key), value))
    return ", ".join(parts)


# X.509 key usage flag -> contract field name (mirrors another vendor's KeyUsagesModel,
# so pages can filter signing certificates on multi-cert tokens).
_KEY_USAGE_FIELDS = {
    "digital_signature": "digitalSignature",
    "non_repudiation": "nonRepudiation",
    "key_encipherment": "keyEncipherment",
    "data_encipherment": "dataEncipherment",
    "key_agreement": "keyAgreement",
    "key_cert_sign": "keyCertSign",
    "crl_sign": "crlSign",
}


def _key_usage(cert):
    """Key usage booleans; all false when the extension is absent or unreadable."""
    try:
        usage_set = cert.key_usage_value.native if cert.key_usage_value else set()
    except Exception:
        usage_set = set()
    return {field: flag in usage_set for flag, field in _KEY_USAGE_FIELDS.items()}


def _cert_info(der):
    """Contract fields for one DER certificate (tokenLabel/moduleName added by callers)."""
    cert = x509.Certificate.load(der)
    validity = cert["tbs_certificate"]["validity"]
    algorithm = cert.public_key.algorithm
    return {
        "thumbprint": hashlib.sha1(der).hexdigest(),
        "certificate": base64.b64encode(der).decode("ascii"),
        "subject": _name_to_string(cert.subject),
        "issuer": _name_to_string(cert.issuer),
        "validFrom": _iso_utc(validity["not_before"].native),
        "validTo": _iso_utc(validity["not_after"].native),
        "keyType": _KEY_TYPES.get(algorithm, algorithm.upper()),
        "keyUsage": _key_usage(cert),
    }


def _map_error(exc):
    """Translate a PKCS#11 exception into a HostError with a contract code."""
    if isinstance(exc, p11ex.PinIncorrect):
        return HostError("PIN_INCORRECT", "the PIN is incorrect")
    if isinstance(exc, p11ex.PinLocked):
        return HostError("PIN_LOCKED", "the PIN is locked; unlock it with the token vendor tool")
    if isinstance(exc, (p11ex.TokenNotPresent, p11ex.TokenNotRecognised,
                        p11ex.NoSuchToken, p11ex.DeviceRemoved)):
        return HostError("TOKEN_NOT_FOUND", "the token is not present")
    return HostError("INTERNAL", "PKCS#11 error: %s" % type(exc).__name__)


def _with_timeout(fn, seconds):
    """Run fn on a daemon thread. Raises TimeoutError if it outlives the budget;
    otherwise returns its result or re-raises its exception."""
    box = {}

    def run():
        try:
            box["result"] = fn()
        except Exception as exc:  # re-raised on the caller's thread below
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise TimeoutError
    if "error" in box:
        raise box["error"]
    return box["result"]


def _scan_module(path, stats):
    """Contract entries for every certificate on one module's tokens.

    Runs on a watchdog thread; after a timeout its late stats mutations may
    still land. ponytail: the counters are diagnostics, not billing.
    """
    found = []
    for token in _module_tokens(path, stats):
        try:
            with token.open() as session:
                ders = [
                    bytes(obj[Attribute.VALUE])
                    for obj in session.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE})
                ]
        except Exception as exc:
            log.warning("cannot read certificates from token on %s: %s", path, exc)
            continue
        for der in ders:
            try:
                info = _cert_info(der)
            except Exception as exc:
                log.warning("skipping unparseable certificate on %s: %s", path, exc)
                continue
            info["tokenLabel"] = _token_label(token)
            info["moduleName"] = os.path.basename(path)
            info["source"] = "pkcs11"
            found.append(info)
    return found


def list_certificates(stats=None):
    """Scan all configured modules and return contract-shaped certificate entries.

    Broken modules and unreadable tokens are logged and skipped so one bad
    driver does not hide certificates on a healthy token. Each module scan
    runs under SCAN_TIMEOUT_SECONDS; a stuck driver is abandoned and named in
    ``stats["stuck"]``. ``stats`` (a dict, when given) also receives the
    configured/loaded/tokens counters, so callers can report WHY a list came
    back empty.
    """
    stats = stats if stats is not None else {}
    stats.update(configured=0, loaded=0, tokens=0)
    found = []
    seen = set()
    stuck = []
    for path in modules.discover_modules():
        stats["configured"] += 1
        started = time.monotonic()
        try:
            infos = _with_timeout(lambda p=path: _scan_module(p, stats),
                                  SCAN_TIMEOUT_SECONDS)
        except TimeoutError:
            stuck.append(os.path.basename(path))
            log.warning("PKCS#11 module %s still scanning after %ss; abandoned",
                        path, SCAN_TIMEOUT_SECONDS)
            continue
        elapsed = time.monotonic() - started
        if elapsed > 2:
            log.info("slow PKCS#11 module %s: %.1fs", path, elapsed)
        for info in infos:
            if info["thumbprint"] in seen:
                continue
            seen.add(info["thumbprint"])
            found.append(info)
    if stuck:
        stats["stuck"] = stuck
    return found


def _find_certificate(thumbprint):
    """Locate a certificate by thumbprint. Returns (path, token, der, cka_id, cka_label)."""
    stats = {}
    for path, token in _iter_tokens(stats):
        try:
            with token.open() as session:
                for obj in session.get_objects({Attribute.CLASS: ObjectClass.CERTIFICATE}):
                    der = bytes(obj[Attribute.VALUE])
                    if hashlib.sha1(der).hexdigest() == thumbprint:
                        return path, token, der, _attr(obj, Attribute.ID), _attr(obj, Attribute.LABEL)
        except Exception as exc:
            log.warning("cannot scan token on %s: %s", path, exc)
            continue

    if stats["configured"] and not stats["loaded"]:
        raise HostError("MODULE_ERROR", "no PKCS#11 module could be loaded")
    if not stats["tokens"]:
        raise HostError("TOKEN_NOT_FOUND", "no token is present; plug in the device and retry")
    raise HostError("CERT_NOT_FOUND", "no certificate with thumbprint %s on any present token" % thumbprint)


def _find_private_key(session, cka_id, cka_label):
    """Match the private key to the certificate: by CKA_ID, then label, then only key."""
    if cka_id:
        for obj in session.get_objects({Attribute.CLASS: ObjectClass.PRIVATE_KEY,
                                        Attribute.ID: cka_id}):
            return obj
    if cka_label:
        for obj in session.get_objects({Attribute.CLASS: ObjectClass.PRIVATE_KEY,
                                        Attribute.LABEL: cka_label}):
            return obj
    # ponytail: last resort grabs the only private key; fine for single-cert DSC
    # tokens, revisit if multi-key tokens misbehave.
    keys = list(session.get_objects({Attribute.CLASS: ObjectClass.PRIVATE_KEY}))
    if len(keys) == 1:
        return keys[0]
    return None


def _sign_rsa(key, digest, digest_algorithm):
    """PKCS#1 v1.5: wrap the digest in a DigestInfo, sign with CKM_RSA_PKCS."""
    digest_info = algos.DigestInfo({
        "digest_algorithm": algos.DigestAlgorithm({"algorithm": digest_algorithm}),
        "digest": digest,
    })
    return bytes(key.sign(digest_info.dump(), mechanism=Mechanism.RSA_PKCS))


def _sign_ec(key, digest):
    """CKM_ECDSA over the raw digest, then raw r||s converted to DER."""
    return ecdsa_raw_to_der(bytes(key.sign(digest, mechanism=Mechanism.ECDSA)))


def ecdsa_raw_to_der(raw):
    """Convert a raw r||s ECDSA signature to a DER ECDSA-Sig-Value."""
    if not raw or len(raw) % 2:
        raise HostError("INTERNAL", "malformed raw ECDSA signature (%d bytes)" % len(raw))
    half = len(raw) // 2
    r = int.from_bytes(raw[:half], "big")
    s = int.from_bytes(raw[half:], "big")
    return algos.DSASignature({"r": r, "s": s}).dump()


def sign_hashes(thumbprint, hashes, digest_algorithm="sha256", pin_provider=None):
    """Sign raw digests with the private key matching a certificate thumbprint.

    All digests are signed inside one login session: one PIN prompt per batch.
    Returns raw signature bytes per digest, in order.
    """
    if digest_algorithm not in DIGEST_ALGORITHMS:
        raise HostError("UNSUPPORTED", "unsupported digest algorithm: %r" % digest_algorithm)
    if not hashes:
        raise HostError("INTERNAL", "hashes must be a non-empty list")

    path, token, der, cka_id, cka_label = _find_certificate(thumbprint.lower().strip())
    key_type = _cert_info(der)["keyType"]
    if key_type not in ("RSA", "EC"):
        raise HostError("UNSUPPORTED", "unsupported key type: %s" % key_type)

    if pin_provider is None:
        from . import pin as pin_module
        pin_provider = pin_module.get_pin
    label = _token_label(token)
    cached = _cached_pin(label)
    pin_value = cached or pin_provider(label)
    if not pin_value:
        raise HostError("USER_CANCELLED", "PIN entry was cancelled")

    try:
        session = token.open(user_pin=pin_value)
    except p11ex.PinIncorrect:
        _pin_cache.pop(label, None)
        if cached is None:
            raise _map_error(p11ex.PinIncorrect())
        # The cached PIN went stale (changed on the token): one proper retry.
        pin_value = pin_provider(label)
        if not pin_value:
            raise HostError("USER_CANCELLED", "PIN entry was cancelled")
        try:
            session = token.open(user_pin=pin_value)
        except p11ex.PKCS11Error as exc:
            raise _map_error(exc)
    except p11ex.PKCS11Error as exc:
        raise _map_error(exc)
    # Login succeeded, so the PIN is right: remember it for a while.
    _pin_cache[label] = (pin_value, time.monotonic() + PIN_CACHE_TTL_SECONDS)

    with session:
        key = _find_private_key(session, cka_id, cka_label)
        if key is None:
            raise HostError("CERT_NOT_FOUND",
                            "certificate found but its private key is not on the token")
        try:
            if key_type == "RSA":
                return [_sign_rsa(key, digest, digest_algorithm) for digest in hashes]
            return [_sign_ec(key, digest) for digest in hashes]
        except p11ex.PKCS11Error as exc:
            raise _map_error(exc)
