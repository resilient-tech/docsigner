"""Request dispatch per CONTRACTS.md section 2.

{id, command, params} in, {id, result} or {id, error: {code, message}} out.
Dispatch never raises: every failure becomes an error response.
"""

import base64
import binascii
import json
import logging

from . import __version__, pkcs11_ops
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
    return {"certificates": pkcs11_ops.list_certificates()}


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
    signatures = pkcs11_ops.sign_hashes(thumbprint, digests, algorithm)
    return {"signatures": [base64.b64encode(s).decode("ascii") for s in signatures]}


_HANDLERS = {
    "getVersion": _get_version,
    "listCertificates": _list_certificates,
    "signHash": _sign_hash,
}
