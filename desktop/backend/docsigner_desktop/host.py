"""Reach the DSC token through the DocSigner host, run as a fresh subprocess
per call (the same model the browser extension uses).

Running the host fresh each time sidesteps the per-process slot state some token
drivers cache, which otherwise wedges a long-lived scan. The host's CLI already
merges PKCS#11 tokens with the OS keychain and handles the PIN dialog, so this
is a thin wrapper over its `list` and `sign` commands.

The host is `host-rs`, a self-contained Rust binary of about 1 MB. It ships
beside the app in a packaged build and is found in the cargo target directory
when running from source.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ENV_HOST_BIN = "DOCSIGNER_HOST_BIN"

BINARY_NAME = "docsigner-host.exe" if sys.platform == "win32" else "docsigner-host"


class TokenError(Exception):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code


class HostNotFound(TokenError):
    """The host binary is missing, which is a setup problem, not a token one."""


def _candidates() -> list[Path]:
    """Where to look for the host binary, most specific first."""
    here = Path(__file__).resolve()
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks bundled binaries into _MEIPASS; the onedir build
        # also leaves them beside the executable.
        roots = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent]
        return [root / BINARY_NAME for root in roots if str(root)]

    # From source: host-rs/target/{release,debug}/ relative to the repo root,
    # which is three parents up from desktop/backend/docsigner_desktop/.
    repo = here.parents[3]
    target = repo / "host-rs" / "target"
    return [target / "release" / BINARY_NAME, target / "debug" / BINARY_NAME]


def host_binary() -> str:
    """Absolute path to the host binary. Raises HostNotFound if there is none.

    DOCSIGNER_HOST_BIN overrides the search, which is how a build under test
    is pointed at a specific binary.
    """
    override = os.environ.get(ENV_HOST_BIN)
    if override:
        return override
    for candidate in _candidates():
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(BINARY_NAME)
    if found:
        return found
    raise HostNotFound(
        "the docsigner-host binary was not found. Build it with "
        "`cargo build --release --manifest-path host-rs/Cargo.toml`, or set "
        f"{ENV_HOST_BIN} to its path."
    )


def _host_argv() -> list[str]:
    """How to launch the signing host as a fresh process."""
    return [host_binary()]


def _run(args: list[str], timeout: float, env: dict | None = None) -> dict:
    proc = subprocess.run(
        [*_host_argv(), *args],
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
    env = {**os.environ, "DOCSIGNER_PIN": pin} if pin else None
    result = _run(args, timeout=300, env=env)
    return [base64.b64decode(s) for s in result.get("signatures", [])]
