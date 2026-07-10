"""Request dispatch per CONTRACTS.md section 2.

{id, command, params} in, {id, result} or {id, error: {code, message}} out.
Dispatch never raises: every failure becomes an error response.
"""

import base64
import binascii
import json
import logging
import time

from . import __version__, notify, os_store, pcsc, pkcs11_ops, procs, update
from .errors import HostError
from .modules import config_dir

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
VERSION = __version__

# Set when a scan looked wedged: module loaded, reader or token present, zero
# certificates. main exits after the reply so the extension's next request
# spawns a fresh process (full C_Initialize). WatchData's driver caches its
# slot state per process; lib.reinitialize() and a replug do not clear it,
# only a fresh process does (live-tested: extension reload fixed what a
# replug could not).
restart_requested = False


def handle_raw(payload):
    """Dispatch raw request bytes. Always returns a response dict, never raises."""
    try:
        message = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _error(None, "INTERNAL", "request is not valid JSON")
    return handle_message(message)


def handle_message(message):
    """Dispatch a decoded request. Always returns a response dict, never raises."""
    message_id = message.get("id") if isinstance(message, dict) else None
    try:
        if not isinstance(message, dict):
            raise HostError("INTERNAL", "request must be a JSON object")
        command = message.get("command")
        handler = _HANDLERS.get(command)
        if handler is None:
            raise HostError("UNSUPPORTED", "unknown command: %r" % (command,))
        params = message.get("params") or {}
        if not isinstance(params, dict):
            raise HostError("INTERNAL", "params must be an object")
        return {"id": message_id, "result": handler(params)}
    except HostError as exc:
        return _error(message_id, exc.code, exc.message)
    except Exception as exc:
        log.exception("unhandled error dispatching %r", message)
        return _error(message_id, "INTERNAL", "%s: %s" % (type(exc).__name__, exc))


def _error(message_id, code, text):
    return {"id": message_id, "error": {"code": code, "message": text}}


def _get_version(params):
    return {"version": VERSION, "protocolVersion": PROTOCOL_VERSION,
            "logPath": str(config_dir() / "host.log")}


def _check_update(params):
    return update.check_update()


def _list_certificates(params):
    """PKCS#11 tokens plus the OS store, deduplicated by thumbprint.

    A token certificate its driver also registered in the OS store shows up
    once, as pkcs11, keeping today's behaviour for existing users.

    Each source is isolated: the Keychain and the PC/SC reader scan can behave
    differently when the browser spawns the host (session and permission
    context differ from a terminal), and a failure there must not hide the
    tokens PKCS#11 found. The per-source counts are logged so a browser-side
    empty result can be told apart from a host-side one.
    """
    started = time.monotonic()
    stats = {}
    certificates = _safe("pkcs11", lambda: pkcs11_ops.list_certificates(stats))
    pkcs11_count = len(certificates)
    seen = {c["thumbprint"] for c in certificates}
    os_certs = [c for c in _safe("os-store", os_store.list_certificates)
                if c["thumbprint"] not in seen]
    certificates += os_certs
    readers = _safe("pcsc", pcsc.detect_readers)
    diagnostics = {
        "modulesConfigured": stats.get("configured", 0),
        "modulesLoaded": stats.get("loaded", 0),
        "tokens": stats.get("tokens", 0),
        "pkcs11Certificates": pkcs11_count,
        "osStoreCertificates": len(os_certs),
    }
    if stats.get("stuck"):
        diagnostics["stuckModules"] = stats["stuck"]
    if not pkcs11_count:
        # Only when the scan came back empty: the ps call is pointless when
        # the token answered, and this keeps the happy path fast.
        competing = _safe("procs", procs.competing)
        if competing:
            diagnostics["competingProcesses"] = competing
    if not pkcs11_count and stats.get("loaded") and (readers or stats.get("tokens")):
        global restart_requested
        restart_requested = True
        diagnostics["hostWillRestart"] = True
        log.warning("wedged scan (driver loaded, device present, 0 certificates);"
                    " exiting after this reply so the next request gets a fresh process")
    log.info(
        "listCertificates -> %d certificates, %d readers, %r in %.1fs",
        len(certificates), len(readers), diagnostics, time.monotonic() - started,
    )
    result = {"certificates": certificates, "diagnostics": diagnostics}
    if readers:
        result["readers"] = readers
    return result


def _safe(source, fn):
    """Run a discovery source, logging and swallowing its failure as an empty
    list so one source never suppresses the others."""
    try:
        return fn()
    except Exception:
        log.exception("%s discovery failed", source)
        return []


def _sign_hash(params):
    thumbprint = params.get("thumbprint")
    hashes = params.get("hashes")
    algorithm = params.get("digestAlgorithm", "sha256")
    pin = params.get("pin")
    if not isinstance(thumbprint, str) or not thumbprint:
        raise HostError("INTERNAL", "signHash needs a thumbprint string")
    if not isinstance(hashes, list) or not hashes or not all(isinstance(h, str) for h in hashes):
        raise HostError("INTERNAL", "signHash needs a non-empty list of base64 hashes")
    if pin is not None and not isinstance(pin, str):
        raise HostError("INTERNAL", "pin must be a string when present")
    try:
        digests = [base64.b64decode(h, validate=True) for h in hashes]
    except (binascii.Error, ValueError):
        raise HostError("INTERNAL", "hashes must be valid base64")
    signatures = _sign_with_fallback(thumbprint, digests, algorithm, pin)
    count = len(signatures)
    notify.notify("OpenSigner", "Signed %d hash%s with certificate %s…"
                  % (count, "" if count == 1 else "es", thumbprint[:12]))
    return {"signatures": [base64.b64encode(s).decode("ascii") for s in signatures]}


def _sign_with_fallback(thumbprint, digests, algorithm, pin=None):
    """Tokens first (unchanged behaviour), then the OS store.

    Only not-found outcomes trigger the fallback; PIN and cancellation errors
    surface as-is. When neither side has the certificate, the PKCS#11 error
    wins: it distinguishes "no module", "no token" and "no certificate".

    A page-supplied pin (CONTRACTS.md section 2) replaces the native dialog on
    the PKCS#11 path; the os-store path always uses the OS's own dialog.
    """
    try:
        if pin:
            return pkcs11_ops.sign_hashes(thumbprint, digests, algorithm,
                                          pin_provider=lambda _label: pin)
        return pkcs11_ops.sign_hashes(thumbprint, digests, algorithm)
    except HostError as exc:
        if exc.code not in ("TOKEN_NOT_FOUND", "CERT_NOT_FOUND", "MODULE_ERROR"):
            raise
        try:
            return os_store.sign_hashes(thumbprint, digests, algorithm)
        except HostError as fallback:
            raise exc if fallback.code == "CERT_NOT_FOUND" else fallback


_HANDLERS = {
    "getVersion": _get_version,
    "checkUpdate": _check_update,
    "listCertificates": _list_certificates,
    "signHash": _sign_hash,
}
