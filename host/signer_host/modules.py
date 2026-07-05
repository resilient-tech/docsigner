"""Discovery of PKCS#11 module paths.

Priority order: OPENSIGNER_PKCS11_MODULES env var, the user config file,
then a built-in list of well-known install paths for common tokens.
Only paths that exist on disk are returned.
"""

import json
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

ENV_VAR = "OPENSIGNER_PKCS11_MODULES"


def config_dir():
    """Per-user config directory: ~/.config/opensigner (POSIX), %APPDATA%/opensigner (Windows)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "opensigner"
    return Path.home() / ".config" / "opensigner"


def _win_well_known():
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    return [
        # OpenSC
        os.path.join(program_files, "OpenSC Project", "OpenSC", "pkcs11", "opensc-pkcs11.dll"),
        os.path.join(system32, "opensc-pkcs11.dll"),
        # Feitian ePass2003
        os.path.join(system32, "eps2003csp11.dll"),
        # SafeNet eToken
        os.path.join(system32, "eTPKCS11.dll"),
        # WatchData ProxKey
        os.path.join(system32, "SignatureP11.dll"),
        os.path.join(system32, "wdpkcs.dll"),
        # eMudhra variants (Trust Key, Longmai mToken CryptoID)
        os.path.join(system32, "TRUSTKEYP11.dll"),
        os.path.join(system32, "CryptoIDA_pkcs11.dll"),
    ]


_WELL_KNOWN_POSIX = {
    "linux": [
        # OpenSC (most EU smartcards)
        "/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so",
        "/usr/lib/opensc-pkcs11.so",
        "/usr/lib64/opensc-pkcs11.so",
        "/usr/lib/pkcs11/opensc-pkcs11.so",
        "/usr/local/lib/opensc-pkcs11.so",
        # Feitian ePass2003 (castle)
        "/usr/lib/libcastle.so",
        "/usr/lib/libcastle.so.1.0.0",
        "/usr/lib64/libcastle.so",
        "/usr/lib64/libcastle.so.1.0.0",
        "/usr/lib/x86_64-linux-gnu/libcastle.so.1.0.0",
        # WatchData ProxKey
        "/usr/lib/WatchData/ProxKey/lib/libwdpkcs_SignatureP11.so",
        "/usr/lib64/WatchData/ProxKey/lib/libwdpkcs_SignatureP11.so",
        "/usr/lib/libwdpkcs_SignatureP11.so",
        # SafeNet eToken
        "/usr/lib/libeToken.so",
        "/usr/lib64/libeToken.so",
        "/usr/lib/pkcs11/libeToken.so",
        # eMudhra variants (Trust Key, mToken)
        "/usr/lib/TRUSTKEY/libtrustkeyP11.so",
        "/usr/lib/libtrustkeyP11.so",
        "/usr/lib/libcryptoida_pkcs11.so",
    ],
    "darwin": [
        # OpenSC
        "/Library/OpenSC/lib/opensc-pkcs11.so",
        "/usr/local/lib/opensc-pkcs11.so",
        "/opt/homebrew/lib/opensc-pkcs11.so",
        "/usr/local/lib/pkcs11/opensc-pkcs11.so",
        # Feitian ePass2003
        "/usr/local/lib/libcastle.dylib",
        "/usr/local/lib/libcastle.1.0.0.dylib",
        # SafeNet eToken
        "/usr/local/lib/libeToken.dylib",
        "/Library/Frameworks/eToken.framework/Versions/A/libeToken.dylib",
        # WatchData ProxKey
        "/usr/local/lib/wdProxKeyUsbKeyTool/libwdpkcs_Proxkey.dylib",
        "/usr/local/lib/libwdpkcs_SignatureP11.dylib",
        "/Library/WatchData/ProxKey/lib/libwdpkcs_SignatureP11.dylib",
    ],
}


def _well_known():
    if sys.platform == "win32":
        return _win_well_known()
    if sys.platform == "darwin":
        return _WELL_KNOWN_POSIX["darwin"]
    return _WELL_KNOWN_POSIX["linux"]


def _config_modules():
    """Module paths from the user config file. Accepts a list or {"modules": [...]}."""
    path = config_dir() / "modules.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("ignoring invalid JSON in %s", path)
        return []
    if isinstance(data, dict):
        data = data.get("modules", [])
    if not isinstance(data, list):
        log.warning("ignoring %s: expected a list or an object with a 'modules' list", path)
        return []
    return [str(item) for item in data]


def discover_modules():
    """Return PKCS#11 module paths that exist on disk, deduplicated, in priority order."""
    candidates = []
    env = os.environ.get(ENV_VAR, "")
    candidates += [p for p in env.split(os.pathsep) if p]
    candidates += _config_modules()
    candidates += _well_known()

    seen = set()
    found = []
    for candidate in candidates:
        candidate = os.path.expanduser(candidate)
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.isfile(candidate):
            found.append(candidate)
    return found
