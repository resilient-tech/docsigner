"""PIN acquisition chain: env var (CLI and tests), then a tkinter dialog.

PINs never cross the native messaging protocol; the host prompts locally.
"""

import os

from .errors import HostError

ENV_VAR = "OPENSIGNER_PIN"


def get_pin(token_label=""):
    """Return the token PIN. Raises HostError(USER_CANCELLED) when none is available."""
    pin = os.environ.get(ENV_VAR)
    if pin:
        return pin
    pin = _prompt_tk(token_label)
    if not pin:
        raise HostError("USER_CANCELLED", "PIN entry was cancelled")
    return pin


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
