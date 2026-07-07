"""Best-effort desktop notification. Never raises, never blocks the caller.

A notification on every token signature makes a silent/headless signing
attempt visible to the user, whose only other UI is the PIN dialog (and the
PIN cache means some signatures happen with no prompt at all). Set
OPENSIGNER_NO_NOTIFY to turn it off.

macOS uses osascript, Linux uses notify-send. Windows is a no-op for now.
ponytail: no Windows toast; add a PowerShell toast only if someone wants it.
"""

import os
import subprocess
import sys

ENV_DISABLE = "OPENSIGNER_NO_NOTIFY"


def _applescript_string(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title, body):
    """Show a desktop notification if possible. Swallows every failure."""
    if os.environ.get(ENV_DISABLE):
        return
    try:
        if sys.platform == "darwin":
            script = "display notification %s with title %s" % (
                _applescript_string(body), _applescript_string(title))
            subprocess.run(["osascript", "-e", script],
                           capture_output=True, timeout=5)
        elif sys.platform.startswith("linux"):
            subprocess.run(["notify-send", title, body],
                           capture_output=True, timeout=5)
        # Windows: no-op (see module docstring).
    except (OSError, subprocess.SubprocessError):
        pass
