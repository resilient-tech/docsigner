"""Talk to the token, through the host binary, one fresh process per call.

Fresh each time on purpose: some token drivers cache state per process and a
long-lived one eventually wedges. The host already does the hard parts (finding
the token, the PIN dialog), so this is a thin wrapper over `list` and `sign`.
"""

import base64
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

ENV_HOST_BIN = "DOCSIGNER_HOST_BIN"

BINARY_NAME = "docsigner-host.exe" if sys.platform == "win32" else "docsigner-host"


class TokenError(Exception):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code


class HostNotFound(TokenError):
    """No host binary. That is a setup problem, not a token problem."""


def _candidates() -> list[Path]:
    """Where to look for the host binary, most specific first."""
    here = Path(__file__).resolve()
    if getattr(sys, "frozen", False):
        # Where a packaged build puts it: unpacked, or next to the executable.
        roots = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent]
        return [root / BINARY_NAME for root in roots if str(root)]

    # Running from source: wherever cargo built it.
    repo = here.parents[3]
    target = repo / "host" / "target"
    return [target / "release" / BINARY_NAME, target / "debug" / BINARY_NAME]


def host_binary() -> str:
    """Where the host binary is. DOCSIGNER_HOST_BIN wins over the search."""
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
        "`cargo build --release --manifest-path host/Cargo.toml`, or set "
        f"{ENV_HOST_BIN} to its path."
    )


# The host is a console program and this app has no console, so Windows gives it
# a fresh one: a black window flashes up on every certificate scan and signature.
_NO_CONSOLE = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def _run(args: list[str], timeout: float, env: dict | None = None) -> dict:
    proc = subprocess.run(
        [host_binary(), *args],
        capture_output=True, text=True, timeout=timeout, env=env, **_NO_CONSOLE,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise TokenError(proc.stderr.strip() or "the signing host did not respond")
    if "error" in payload:
        err = payload["error"]
        raise TokenError(err.get("message", "token error"), err.get("code"))
    return payload.get("result", {})


def scan() -> dict:
    """Everything the host can see. Empty dict if the host cannot be reached.

    `readers` is what separates "token in, driver missing" from "nothing
    plugged in". To the user both look like an empty list.
    """
    try:
        return _run(["list"], timeout=30)
    except Exception:
        return {}


def sign_hashes(thumbprint: str, digests: list[bytes], algorithm: str = "sha256",
                pin: str | None = None) -> list[bytes]:
    """Sign every hash on one login, so the user types the PIN once.

    A PIN given here reaches the host through the environment. It never touches
    a file or the network. Leave it out and the host asks for it itself.
    """
    args = ["sign", "--thumbprint", thumbprint, "--alg", algorithm]
    for d in digests:
        args += ["--hash", base64.b64encode(d).decode("ascii")]
    # The host announces a signature the moment the token produces one, which here
    # is only halfway: the timestamp and the revocation data still have to be
    # fetched and embedded, and that is what usually fails. We announce the
    # outcome ourselves once we know it — see notify() below.
    env = {**os.environ, "DOCSIGNER_NO_NOTIFY": "1"}
    if pin:
        env["DOCSIGNER_PIN"] = pin
    result = _run(args, timeout=300, env=env)
    return [base64.b64decode(s) for s in result.get("signatures", [])]


def notify(message: str) -> None:
    """Show a desktop popup, through the host. Best effort, never raises.

    The host owns this on all three platforms, and on Windows it also owns the
    registered name Windows credits the popup to. Reaching for a Python
    notification library would mean a second implementation of both.

    No DOCSIGNER_NO_NOTIFY here: if the user has set it themselves it is inherited
    and the host stays quiet, which is what they asked for.
    """
    try:
        subprocess.run(
            [host_binary(), "notify", message],
            capture_output=True, text=True, timeout=15, **_NO_CONSOLE,
        )
    except Exception as exc:  # noqa: BLE001 - a popup is never worth failing a run
        log.debug("could not show the popup: %s", exc)
