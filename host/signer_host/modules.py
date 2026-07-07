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


# Paths harvested from a reference project (config.go) and a vendor host (sdscript.js)
# in addition to our own research; see docs/host.md.
def _win_well_known():
    system32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    syswow64 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "SysWOW64")
    paths = [
        # OpenSC
        os.path.join(system32, "opensc-pkcs11.dll"),
        # Feitian ePass2003 / ePass3003 (eMudhra, Capricorn, Sify, (n)Code, Pantasign)
        os.path.join(system32, "eps2003csp11.dll"),
        os.path.join(system32, "eps2003csp11_v2.dll"),
        os.path.join(system32, "eps2003csp11v2.dll"),
        os.path.join(syswow64, "eps2003csp11v2.dll"),
        os.path.join(system32, "ShuttleCsp11_3000.dll"),
        os.path.join(system32, "ep3003csp11.dll"),
        # Feitian generic / Hypersecu HyperPKI (Castle)
        os.path.join(system32, "castle_v3.dll"),
        os.path.join(system32, "castle.dll"),
        os.path.join(system32, "HyperPKICsp11_2003.dll"),
        os.path.join(syswow64, "HyperPKICsp11_2003.dll"),
        # SafeNet / Aladdin / Thales eToken
        os.path.join(system32, "eTPKCS11.dll"),
        # WatchData ProxKey
        os.path.join(system32, "SignatureP11.dll"),
        os.path.join(system32, "wdpkcs.dll"),
        os.path.join(system32, "WDPKCS11.dll"),
        # eMudhra variants (Trust Key, Longmai mToken CryptoID)
        os.path.join(system32, "TRUSTKEYP11.dll"),
        os.path.join(system32, "CryptoIDA_pkcs11.dll"),
        os.path.join(system32, "mToken CryptoID PKCS11.dll"),
        # Bit4id tokenME
        os.path.join(system32, "bit4ipki.dll"),
        # Precision InnaITKey
        os.path.join(system32, "InnaITPKCS11Driver.dll"),
        # A.E.T. SafeSign / Athena IDProtect / YubiKey
        os.path.join(system32, "aetpkcs11.dll"),
        os.path.join(system32, "asepkcs.dll"),
        os.path.join(system32, "ykcs11.dll"),
    ]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            paths += [
                os.path.join(base, "OpenSC Project", "OpenSC", "pkcs11", "opensc-pkcs11.dll"),
                os.path.join(base, "HYP", "HYP PKI Manager", "pkcs11hw.dll"),
                os.path.join(base, "Hypersecu", "HyperPKI", "castle_v3.dll"),
                os.path.join(base, "Yubico", "Yubico PIV Tool", "bin", "libykcs11.dll"),
            ]
    return paths


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
        "/usr/lib/libcastle_v2.so.1.0.0",
        "/usr/lib64/libcastle.so",
        "/usr/lib64/libcastle.so.1.0.0",
        "/usr/lib/x86_64-linux-gnu/libcastle.so.1.0.0",
        "/usr/lib/libes2003.so",
        # WatchData ProxKey
        "/usr/lib/WatchData/ProxKey/lib/libwdpkcs_SignatureP11.so",
        "/usr/lib64/WatchData/ProxKey/lib/libwdpkcs_SignatureP11.so",
        "/usr/lib/libwdpkcs_SignatureP11.so",
        "/usr/lib/libwdpkcs.so",
        "/usr/lib/libProxKeyP11.so",
        # SafeNet eToken
        "/usr/lib/libeTPkcs11.so",
        "/usr/lib/x86_64-linux-gnu/libeTPkcs11.so",
        "/usr/lib64/libeTPkcs11.so",
        "/usr/lib/libeToken.so",
        "/usr/lib64/libeToken.so",
        "/usr/lib/pkcs11/libeToken.so",
        # eMudhra variants (Trust Key, Longmai mToken CryptoID)
        "/usr/lib/TRUSTKEY/libtrustkeyP11.so",
        "/usr/lib/libtrustkeyP11.so",
        "/usr/lib/libcryptoida_pkcs11.so",
        "/opt/CryptoIDATools/bin/lib/libcryptoid_pkcs11.so",
        # Precision InnaITKey
        "/opt/Precision_Biometric/InnaITDSC/libraries/libInnaITPKCS11Driver.so",
        # YubiKey
        "/usr/lib/x86_64-linux-gnu/libykcs11.so",
        "/usr/lib/libykcs11.so",
        "/usr/lib64/libykcs11.so",
    ],
    "darwin": [
        # OpenSC
        "/Library/OpenSC/lib/opensc-pkcs11.so",
        "/usr/local/lib/opensc-pkcs11.so",
        "/opt/homebrew/lib/opensc-pkcs11.so",
        "/usr/local/lib/pkcs11/opensc-pkcs11.so",
        # Feitian ePass2003 / Hypersecu HYP2003 (castle)
        "/usr/local/lib/libcastle.dylib",
        "/usr/local/lib/libcastle.1.0.0.dylib",
        "/usr/local/lib/libcastle_v2.1.0.0.dylib",
        # SafeNet eToken (libeTPkcs11 is the real basename; libeToken kept for old installs)
        "/usr/local/lib/libeTPkcs11.dylib",
        "/Library/Frameworks/eToken.framework/Versions/A/libeTPkcs11.dylib",
        "/usr/local/lib/libeToken.dylib",
        "/Library/Frameworks/eToken.framework/Versions/A/libeToken.dylib",
        # WatchData ProxKey
        "/usr/local/lib/wdProxKeyUsbKeyTool/libwdpkcs_Proxkey.dylib",
        "/usr/local/lib/libwdpkcs_SignatureP11.dylib",
        "/Library/WatchData/ProxKey/lib/libwdpkcs_SignatureP11.dylib",
        # Longmai mToken CryptoID (eMudhra)
        "/Applications/CryptoIDATools.app/Contents/MacOS/libcryptoid_pkcs11.dylib",
        # Precision InnaITKey
        "/opt/Precision_Biometric/InnaITDSC/libraries/libInnaITPKCS11Driver.dylib",
        # YubiKey
        "/usr/local/lib/libykcs11.dylib",
        "/opt/homebrew/lib/libykcs11.dylib",
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
