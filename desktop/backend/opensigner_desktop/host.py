"""Reach the DSC token through the OpenSigner host, run as a fresh subprocess
per call (the same model the browser extension uses).

Running the host fresh each time sidesteps the per-process slot state some token
drivers cache, which otherwise wedges a long-lived scan. The host's CLI already
merges PKCS#11 tokens with the OS keychain and handles the PIN dialog, so this
is a thin wrapper over its `list` and `sign` commands.
"""

import base64
import json
import os
import subprocess
import sys


class TokenError(Exception):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code


def _run(args: list[str], timeout: float, env: dict | None = None) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "signer_host.cli", *args],
        capture_output=True, text=True, timeout=timeout, env=env,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise TokenError(proc.stderr.strip() or "the signing host did not respond")
    if "error" in payload:
        err = payload["error"]
        raise TokenError(err.get("message", "token error"), err.get("code"))
    return payload.get("result", {})


def list_certificates() -> list[dict]:
    """Token + keychain certificates, or [] if the host or a token is absent."""
    try:
        return _run(["list"], timeout=30).get("certificates", [])
    except Exception:
        return []


def sign_hashes(thumbprint: str, digests: list[bytes], algorithm: str = "sha256",
                pin: str | None = None) -> list[bytes]:
    """Sign every digest in one login (one PIN for the batch). Raises TokenError.

    A PIN passed here is handed to the host through the environment, so it never
    touches a file or the network; without one the host shows its own dialog.
    """
    args = ["sign", "--thumbprint", thumbprint, "--alg", algorithm]
    for d in digests:
        args += ["--hash", base64.b64encode(d).decode("ascii")]
    env = {**os.environ, "OPENSIGNER_PIN": pin} if pin else None
    result = _run(args, timeout=300, env=env)
    return [base64.b64decode(s) for s in result.get("signatures", [])]
