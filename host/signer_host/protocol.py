"""Request dispatch per CONTRACTS.md section 2.

{id, command, params} in, {id, result} or {id, error: {code, message}} out.
Dispatch never raises: every failure becomes an error response.
"""

import base64
import binascii
import json
import logging

from . import __version__, os_store, pkcs11_ops
from .errors import HostError

log = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
VERSION = __version__


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
    return {"version": VERSION, "protocolVersion": PROTOCOL_VERSION}


def _list_certificates(params):
    """PKCS#11 tokens plus the OS store, deduplicated by thumbprint.

    A token certificate its driver also registered in the OS store shows up
    once, as pkcs11, keeping today's behaviour for existing users.
    """
    certificates = pkcs11_ops.list_certificates()
    seen = {c["thumbprint"] for c in certificates}
    certificates += [c for c in os_store.list_certificates()
                     if c["thumbprint"] not in seen]
    return {"certificates": certificates}


def _sign_hash(params):
    thumbprint = params.get("thumbprint")
    hashes = params.get("hashes")
    algorithm = params.get("digestAlgorithm", "sha256")
    if not isinstance(thumbprint, str) or not thumbprint:
        raise HostError("INTERNAL", "signHash needs a thumbprint string")
    if not isinstance(hashes, list) or not hashes or not all(isinstance(h, str) for h in hashes):
        raise HostError("INTERNAL", "signHash needs a non-empty list of base64 hashes")
    try:
        digests = [base64.b64decode(h, validate=True) for h in hashes]
    except (binascii.Error, ValueError):
        raise HostError("INTERNAL", "hashes must be valid base64")
    signatures = _sign_with_fallback(thumbprint, digests, algorithm)
    return {"signatures": [base64.b64encode(s).decode("ascii") for s in signatures]}


def _sign_with_fallback(thumbprint, digests, algorithm):
    """Tokens first (unchanged behaviour), then the OS store.

    Only not-found outcomes trigger the fallback; PIN and cancellation errors
    surface as-is. When neither side has the certificate, the PKCS#11 error
    wins: it distinguishes "no module", "no token" and "no certificate".
    """
    try:
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
    "listCertificates": _list_certificates,
    "signHash": _sign_hash,
}
