"""Real file and folder dialogs, so nobody has to paste a path.

macOS gets a proper picker. Elsewhere the UI falls back to a text box.
"""

import subprocess
import sys
from pathlib import Path


def _osascript(script: str) -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=180)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None  # non-zero = cancelled


def pick_folder() -> str | None:
    return _osascript('POSIX path of (choose folder with prompt "Choose a folder of PDFs")') or None


def pick_files() -> list[dict]:
    script = (
        'set out to ""\n'
        'set chosen to choose file with prompt "Choose PDFs" of type {"pdf"} with multiple selections allowed\n'
        "repeat with f in chosen\n"
        "set out to out & POSIX path of f & linefeed\n"
        "end repeat\n"
        "return out"
    )
    result = _osascript(script)
    if not result:
        return []
    entries = []
    for line in result.splitlines():
        p = Path(line.strip())
        if p.suffix.lower() == ".pdf" and p.is_file():
            entries.append({"path": str(p), "name": p.name, "size": p.stat().st_size})
    return entries
