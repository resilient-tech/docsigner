"""Programs that can hold a token's single PKCS#11 session.

ePass/ProxKey-class drivers allow one process on the token at a time; a
vendor utility, another browser's host, or a competing signing host silently makes
every scan come back empty. Naming the culprit beats "replug and retry".
Tolerant like pcsc.py: any failure means "nothing found", never an error.
"""

import os
import subprocess
import sys

# lowercase needle in the process name -> what to tell the user to close.
_KNOWN = (
    ("opensigner-host", "another OpenSigner host"),
    ("webpki", "a competing signing host"),
    ("epass", "the ePass token manager"),
    ("proxkey", "the ProxKey token tool"),
    ("wdtoken", "the WatchData token tool"),
    ("etoken", "SafeNet Authentication Client"),
    ("safenet", "SafeNet Authentication Client"),
    ("cryptoida", "the mToken CryptoID tool"),
    ("trustkey", "the TrustKey tool"),
)


def _process_list():
    """(pid, lowercased process name) for every visible process; [] on failure."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/fo", "csv", "/nh"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            rows = []
            for line in out.splitlines():
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2 and parts[1].isdigit():
                    rows.append((int(parts[1]), parts[0].lower()))
            return rows
        out = subprocess.run(
            ["ps", "-A", "-o", "pid=,comm="],
            capture_output=True, text=True, timeout=10,
        ).stdout
        rows = []
        for line in out.splitlines():
            pid, _, name = line.strip().partition(" ")
            if pid.isdigit() and name:
                rows.append((int(pid), os.path.basename(name.strip()).lower()))
        return rows
    except Exception:
        return []


def competing():
    """Display names of running programs likely holding the token, deduplicated.

    Our own process tree is excluded. ponytail: self = pid + ppid, which
    covers PyInstaller's one-file parent/child pair; a third opensigner-host
    of our own tree would be a real finding anyway.
    """
    own = {os.getpid(), os.getppid()}
    found = []
    for pid, name in _process_list():
        if pid in own:
            continue
        for needle, label in _KNOWN:
            if needle in name and label not in found:
                found.append(label)
    return found
