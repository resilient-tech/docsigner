"""PIN acquisition chain: env var (CLI and tests), then a local dialog.

PINs never cross the native messaging protocol; the host prompts locally.
On macOS the prompt is a native osascript dialog (no Tcl/Tk runtime needed);
other platforms use a tkinter dialog.
"""

import os
import subprocess
import sys

from .errors import HostError

ENV_VAR = "OPENSIGNER_PIN"


def get_pin(token_label=""):
    """Return the token PIN. Raises HostError(USER_CANCELLED) when none is available."""
    pin = os.environ.get(ENV_VAR)
    if pin:
        return pin
    pin = _prompt(token_label)
    if not pin:
        raise HostError("USER_CANCELLED", "PIN entry was cancelled")
    return pin


def _prompt(token_label):
    """Show the platform's masked PIN dialog. Returns None on cancel/unavailable."""
    if sys.platform == "darwin":
        return _prompt_mac(token_label)
    return _prompt_tk(token_label)


def _prompt_mac(token_label):
    """Masked PIN dialog via osascript, the native macOS route (no Tcl/Tk).

    Returns the entered PIN, or None if the user cancels or osascript is
    unavailable. AppleScript error -128 is the user pressing Cancel.
    """
    label = (token_label or "token").replace("\\", "\\\\").replace('"', '\\"')
    script = (
        "try\n"
        '  text returned of (display dialog "PIN for %s:" default answer "" '
        'with hidden answer with title "OpenSigner")\n'
        "on error number -128\n"
        '  ""\n'
        "end try" % label
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=300
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.rstrip("\n") or None


def _prompt_tk(token_label):
    """Masked PIN dialog. tkinter is imported lazily; headless setups degrade to USER_CANCELLED."""
    try:
        import tkinter
        import tkinter.simpledialog
    except ImportError:
        raise HostError(
            "USER_CANCELLED",
            "no PIN dialog available (tkinter missing) and OPENSIGNER_PIN is not set",
        )
    try:
        root = tkinter.Tk()
    except tkinter.TclError:
        raise HostError(
            "USER_CANCELLED",
            "no PIN dialog available (no display) and OPENSIGNER_PIN is not set",
        )
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        label = token_label or "token"
        return tkinter.simpledialog.askstring(
            "OpenSigner", "PIN for %s:" % label, show="*", parent=root
        )
    finally:
        root.destroy()
