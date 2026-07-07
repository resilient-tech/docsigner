"""Token identification via PC/SC smart-card reader names.

The trick learned from a vendor host (docs/host.md):
every USB token is a CCID device, and the OS smart-card service reads its
reader name from the USB descriptor with no vendor driver installed. So we
can tell WHICH token is plugged in even when its PKCS#11 driver is missing,
and say "install driver X" instead of showing an empty list.

PC/SC is the same C API on all three platforms: winscard.dll (Windows),
PCSC.framework (macOS), libpcsclite (Linux). Only integer widths differ.
Everything here is tolerant: any failure means "no readers", never an error.
"""

import ctypes
import ctypes.util
import logging
import os
import sys

from . import modules

log = logging.getLogger(__name__)

_SCARD_SCOPE_SYSTEM = 2

# (needles in lowercased reader name, token model, module-basename hints).
# Reader names harvested from a vendor host's maps plus vendor docs.
_KNOWN = (
    (("watchdata", "wdind", "proxkey"), "WatchData ProxKey",
     ("signaturep11", "wdpkcs", "proxkey")),
    (("epass", "feitian", "hypersecu", "fs usb", "ft usb"),
     "Feitian ePass2003 / Hypersecu HYP2003",
     ("eps2003", "ep3003", "castle", "hyperpki", "es2003", "shuttle")),
    (("aks ifdh", "safenet", "aladdin", "etoken"), "SafeNet eToken",
     ("etpkcs11", "etoken")),
    (("longmai", "cryptoid"), "Longmai mToken CryptoID", ("cryptoid",)),
    (("trustkey", "trust key"), "TrustKey", ("trustkey",)),
    (("bit4id",), "Bit4id tokenME", ("bit4",)),
    (("innait", "precision"), "Precision InnaITKey", ("innait",)),
    (("yubico", "yubikey"), "YubiKey", ("ykcs11",)),
    (("gemplus", "gemalto"), "Gemalto smartcard", ("opensc",)),
)


def identify(reader_name):
    """(token model, driver basename hints) for a reader name; (None, ()) if unknown."""
    low = reader_name.lower()
    for needles, token, hints in _KNOWN:
        if any(needle in low for needle in needles):
            return token, hints
    return None, ()


def _pcsc():
    """(lib, return type, context type, DWORD type) for this platform."""
    if sys.platform == "darwin":
        lib = ctypes.CDLL("/System/Library/Frameworks/PCSC.framework/PCSC")
        return lib, ctypes.c_int32, ctypes.c_uint32, ctypes.c_uint32
    if sys.platform == "win32":
        return ctypes.WinDLL("winscard"), ctypes.c_long, ctypes.c_void_p, ctypes.c_uint32
    lib = ctypes.CDLL(ctypes.util.find_library("pcsclite") or "libpcsclite.so.1")
    # pcsclite's DWORD is historically `unsigned long`: 64-bit on 64-bit Linux.
    return lib, ctypes.c_long, ctypes.c_long, ctypes.c_ulong


def reader_names():
    """Connected smart-card reader names; [] on any failure (no service, no lib)."""
    try:
        lib, ret_t, ctx_t, dword_t = _pcsc()
    except OSError:
        return []
    try:
        lib.SCardEstablishContext.restype = ret_t
        lib.SCardReleaseContext.restype = ret_t
        context = ctx_t()
        if lib.SCardEstablishContext(_SCARD_SCOPE_SYSTEM, None, None,
                                     ctypes.byref(context)) != 0:
            return []
        try:
            wide = sys.platform == "win32"
            list_readers = lib.SCardListReadersW if wide else lib.SCardListReaders
            list_readers.restype = ret_t
            count = dword_t(0)
            if list_readers(context, None, None, ctypes.byref(count)) != 0 or not count.value:
                return []
            if wide:
                buffer = (ctypes.c_wchar * count.value)()
                if list_readers(context, None, buffer, ctypes.byref(count)) != 0:
                    return []
                blob = "".join(buffer[:count.value])
            else:
                buffer = (ctypes.c_char * count.value)()
                if list_readers(context, None, buffer, ctypes.byref(count)) != 0:
                    return []
                blob = bytes(buffer[:count.value]).decode("utf-8", errors="replace")
            # Multistring: names separated by NUL, terminated by double NUL.
            return [name for name in blob.split("\0") if name]
        finally:
            lib.SCardReleaseContext(context)
    except Exception as exc:
        log.warning("PC/SC reader listing failed: %s", exc)
        return []


def detect_readers():
    """Contract-shaped reader entries: name, token model guess, driver status.

    driverFound means a module matching the token's known driver basenames is
    installed (per modules.discover_modules); false for unrecognised readers.
    """
    names = reader_names()
    if not names:
        return []
    installed = " ".join(os.path.basename(p).lower() for p in modules.discover_modules())
    detected = []
    for name in names:
        token, hints = identify(name)
        detected.append({
            "name": name,
            "token": token,
            "driverFound": any(hint in installed for hint in hints),
        })
    return detected
