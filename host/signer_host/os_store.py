"""OS certificate store backend: macOS Keychain and Windows MY store.

another vendor's host reads the OS store first (docs/host.md): token
drivers usually register the token's certificate there on install, so the
certificate is found with no driver-path configuration, and the private-key
operation routes back through the same OS API, which forwards it to the token.
This module mirrors that. Linux has no universal OS store; there it lists
nothing and PKCS#11 stays the only path.

Same contract shape as pkcs11_ops: entries carry source="os-store",
moduleName="os-store", tokenLabel = store name. The OS shows its own
unlock/PIN dialog during signing, so pin.py is never involved here.
"""

import hashlib
import logging
import sys

from asn1crypto import x509

from .certs import DIGEST_ALGORITHMS, cert_info, ecdsa_raw_to_der
from .errors import HostError

log = logging.getLogger(__name__)


def _signing_capable(der):
    """Keep certificates whose key usage allows signing (or that carry no
    key-usage extension at all). The OS store holds encryption and
    authentication certs too; listing those would only confuse the picker."""
    cert = x509.Certificate.load(der)
    if cert.key_usage_value is None:
        return True
    return bool({"digital_signature", "non_repudiation"} & cert.key_usage_value.native)


def _entry(der, token_label):
    info = cert_info(der)
    info["tokenLabel"] = token_label
    info["moduleName"] = "os-store"
    info["source"] = "os-store"
    return info


# ---------------------------------------------------------------- macOS ----

if sys.platform == "darwin":
    import ctypes
    import ctypes.util
    from functools import lru_cache

    _errSecItemNotFound = -25300
    _errSecUserCanceled = -128

    # (keyType, digestAlgorithm) -> SecKeyAlgorithm constant. The "Digest"
    # algorithms take the digest bytes: Security wraps the DigestInfo for RSA
    # and returns DER ECDSA-Sig-Value for EC, exactly what the contract wants.
    _ALGORITHMS = {
        ("RSA", "sha256"): "kSecKeyAlgorithmRSASignatureDigestPKCS1v15SHA256",
        ("RSA", "sha384"): "kSecKeyAlgorithmRSASignatureDigestPKCS1v15SHA384",
        ("RSA", "sha512"): "kSecKeyAlgorithmRSASignatureDigestPKCS1v15SHA512",
        ("EC", "sha256"): "kSecKeyAlgorithmECDSASignatureDigestX962SHA256",
        ("EC", "sha384"): "kSecKeyAlgorithmECDSASignatureDigestX962SHA384",
        ("EC", "sha512"): "kSecKeyAlgorithmECDSASignatureDigestX962SHA512",
    }

    @lru_cache(maxsize=1)
    def _libs():
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        sec = ctypes.CDLL(ctypes.util.find_library("Security"))
        p = ctypes.c_void_p
        for lib, name, restype, argtypes in (
            (cf, "CFDataCreate", p, (p, ctypes.c_char_p, ctypes.c_long)),
            (cf, "CFDataGetLength", ctypes.c_long, (p,)),
            (cf, "CFDataGetBytePtr", p, (p,)),
            (cf, "CFDictionaryCreate", p,
             (p, ctypes.POINTER(p), ctypes.POINTER(p), ctypes.c_long, p, p)),
            (cf, "CFArrayGetCount", ctypes.c_long, (p,)),
            (cf, "CFArrayGetValueAtIndex", p, (p, ctypes.c_long)),
            (cf, "CFErrorGetCode", ctypes.c_long, (p,)),
            (sec, "SecItemCopyMatching", ctypes.c_int32, (p, ctypes.POINTER(p))),
            (sec, "SecIdentityCopyCertificate", ctypes.c_int32, (p, ctypes.POINTER(p))),
            (sec, "SecIdentityCopyPrivateKey", ctypes.c_int32, (p, ctypes.POINTER(p))),
            (sec, "SecCertificateCopyData", p, (p,)),
            (sec, "SecKeyCreateSignature", p, (p, p, p, ctypes.POINTER(p))),
        ):
            fn = getattr(lib, name)
            fn.restype = restype
            fn.argtypes = list(argtypes)
        return cf, sec

    def _const(lib, name):
        return ctypes.c_void_p.in_dll(lib, name).value

    def _struct_addr(lib, name):
        return ctypes.addressof(ctypes.c_char.in_dll(lib, name))

    def _cf_bytes(cf, data):
        return ctypes.string_at(cf.CFDataGetBytePtr(data), cf.CFDataGetLength(data))

    def _identities():
        """Yield (SecIdentityRef, DER bytes) for every identity in the user's
        keychains. ponytail: refs are never CFReleased; the host is a
        short-lived per-request process and the OS reclaims on exit."""
        cf, sec = _libs()
        pairs = [
            (_const(sec, "kSecClass"), _const(sec, "kSecClassIdentity")),
            (_const(sec, "kSecMatchLimit"), _const(sec, "kSecMatchLimitAll")),
            (_const(sec, "kSecReturnRef"), _const(cf, "kCFBooleanTrue")),
        ]
        keys = (ctypes.c_void_p * len(pairs))(*[k for k, _ in pairs])
        vals = (ctypes.c_void_p * len(pairs))(*[v for _, v in pairs])
        query = cf.CFDictionaryCreate(
            None, keys, vals, len(pairs),
            _struct_addr(cf, "kCFTypeDictionaryKeyCallBacks"),
            _struct_addr(cf, "kCFTypeDictionaryValueCallBacks"))
        result = ctypes.c_void_p()
        status = sec.SecItemCopyMatching(query, ctypes.byref(result))
        if status == _errSecItemNotFound:
            return
        if status != 0:
            raise HostError("INTERNAL", "Keychain query failed (OSStatus %d)" % status)
        for i in range(cf.CFArrayGetCount(result)):
            identity = cf.CFArrayGetValueAtIndex(result, i)
            cert = ctypes.c_void_p()
            if sec.SecIdentityCopyCertificate(identity, ctypes.byref(cert)) != 0:
                continue
            yield identity, _cf_bytes(cf, sec.SecCertificateCopyData(cert))

    def _list_impl():
        found = []
        for _identity, der in _identities():
            try:
                if _signing_capable(der):
                    found.append(_entry(der, "keychain"))
            except Exception as exc:
                log.warning("skipping unparseable Keychain certificate: %s", exc)
        return found

    def _sign_impl(thumbprint, hashes, digest_algorithm):
        cf, sec = _libs()
        for identity, der in _identities():
            if hashlib.sha1(der).hexdigest() == thumbprint:
                break
        else:
            raise HostError("CERT_NOT_FOUND",
                            "no certificate with thumbprint %s in the Keychain" % thumbprint)
        key_type = cert_info(der)["keyType"]
        alg_name = _ALGORITHMS.get((key_type, digest_algorithm))
        if alg_name is None:
            raise HostError("UNSUPPORTED", "unsupported key type: %s" % key_type)
        key = ctypes.c_void_p()
        if sec.SecIdentityCopyPrivateKey(identity, ctypes.byref(key)) != 0:
            raise HostError("CERT_NOT_FOUND",
                            "certificate found but its private key is not accessible")
        signatures = []
        for digest in hashes:
            data = cf.CFDataCreate(None, digest, len(digest))
            error = ctypes.c_void_p()
            sig = sec.SecKeyCreateSignature(key, _const(sec, alg_name), data,
                                            ctypes.byref(error))
            if not sig:
                code = cf.CFErrorGetCode(error) if error.value else 0
                if code == _errSecUserCanceled:
                    raise HostError("USER_CANCELLED", "Keychain access was cancelled")
                raise HostError("INTERNAL", "Keychain signing failed (CFError %d)" % code)
            signatures.append(_cf_bytes(cf, sig))
        return signatures


# -------------------------------------------------------------- Windows ----

elif sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _CERT_KEY_PROV_INFO_PROP_ID = 2
    _CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG = 0x00040000
    _NCRYPT_PAD_PKCS1_FLAG = 0x00000002
    _SCARD_W_CANCELLED_BY_USER = 0x8010006E
    _WIDE_ALG = {"sha256": "SHA256", "sha384": "SHA384", "sha512": "SHA512"}

    class _CERT_CONTEXT(ctypes.Structure):
        _fields_ = [("dwCertEncodingType", wintypes.DWORD),
                    ("pbCertEncoded", ctypes.POINTER(ctypes.c_ubyte)),
                    ("cbCertEncoded", wintypes.DWORD),
                    ("pCertInfo", ctypes.c_void_p),
                    ("hCertStore", ctypes.c_void_p)]

    class _BCRYPT_PKCS1_PADDING_INFO(ctypes.Structure):
        _fields_ = [("pszAlgId", wintypes.LPCWSTR)]

    def _crypt32():
        lib = ctypes.WinDLL("crypt32", use_last_error=True)
        # Handles are pointer-sized: without explicit types ctypes truncates
        # them to 32-bit ints on 64-bit Windows.
        lib.CertOpenSystemStoreW.restype = ctypes.c_void_p
        lib.CertOpenSystemStoreW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        lib.CertEnumCertificatesInStore.restype = ctypes.POINTER(_CERT_CONTEXT)
        lib.CertEnumCertificatesInStore.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.CertCloseStore.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        return lib

    def _contexts(crypt32, store):
        ctx = None
        while True:
            ctx = crypt32.CertEnumCertificatesInStore(store, ctx)
            if not ctx:
                return
            yield ctx

    def _has_private_key(crypt32, ctx):
        size = wintypes.DWORD(0)
        return bool(crypt32.CertGetCertificateContextProperty(
            ctx, _CERT_KEY_PROV_INFO_PROP_ID, None, ctypes.byref(size)))

    def _der(ctx):
        return ctypes.string_at(ctx.contents.pbCertEncoded, ctx.contents.cbCertEncoded)

    def _list_impl():
        crypt32 = _crypt32()
        store = crypt32.CertOpenSystemStoreW(None, "MY")
        if not store:
            raise HostError("INTERNAL", "cannot open the Windows certificate store")
        found = []
        try:
            for ctx in _contexts(crypt32, store):
                try:
                    der = _der(ctx)
                    if _has_private_key(crypt32, ctx) and _signing_capable(der):
                        found.append(_entry(der, "MY"))
                except Exception as exc:
                    log.warning("skipping unreadable store certificate: %s", exc)
        finally:
            crypt32.CertCloseStore(store, 0)
        return found

    def _check(status, doing):
        if status == 0:
            return
        if status & 0xFFFFFFFF == _SCARD_W_CANCELLED_BY_USER:
            raise HostError("USER_CANCELLED", "signing was cancelled")
        raise HostError("INTERNAL", "%s failed (0x%08X)" % (doing, status & 0xFFFFFFFF))

    def _ncrypt_sign(ncrypt, key, padding, flags, digest):
        out_len = wintypes.DWORD(0)
        _check(ncrypt.NCryptSignHash(key, padding, digest, len(digest),
                                     None, 0, ctypes.byref(out_len), flags),
               "NCryptSignHash (size)")
        buf = (ctypes.c_ubyte * out_len.value)()
        _check(ncrypt.NCryptSignHash(key, padding, digest, len(digest),
                                     buf, out_len, ctypes.byref(out_len), flags),
               "NCryptSignHash")
        return bytes(buf[:out_len.value])

    def _sign_impl(thumbprint, hashes, digest_algorithm):
        crypt32 = _crypt32()
        ncrypt = ctypes.WinDLL("ncrypt")
        store = crypt32.CertOpenSystemStoreW(None, "MY")
        if not store:
            raise HostError("INTERNAL", "cannot open the Windows certificate store")
        try:
            for ctx in _contexts(crypt32, store):
                if hashlib.sha1(_der(ctx)).hexdigest() == thumbprint:
                    break
            else:
                raise HostError("CERT_NOT_FOUND",
                                "no certificate with thumbprint %s in the Windows store"
                                % thumbprint)
            key_type = cert_info(_der(ctx))["keyType"]
            if key_type not in ("RSA", "EC"):
                raise HostError("UNSUPPORTED", "unsupported key type: %s" % key_type)
            key = ctypes.c_void_p()
            key_spec = wintypes.DWORD(0)
            caller_free = wintypes.BOOL(False)
            if not crypt32.CryptAcquireCertificatePrivateKey(
                    ctx, _CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG, None,
                    ctypes.byref(key), ctypes.byref(key_spec), ctypes.byref(caller_free)):
                raise HostError("CERT_NOT_FOUND",
                                "certificate found but its private key is not accessible")
            try:
                if key_type == "RSA":
                    padding = _BCRYPT_PKCS1_PADDING_INFO(_WIDE_ALG[digest_algorithm])
                    return [_ncrypt_sign(ncrypt, key, ctypes.byref(padding),
                                         _NCRYPT_PAD_PKCS1_FLAG, digest)
                            for digest in hashes]
                # ECDSA: CNG returns raw r||s, convert like the PKCS#11 path.
                return [ecdsa_raw_to_der(_ncrypt_sign(ncrypt, key, None, 0, digest))
                        for digest in hashes]
            finally:
                if caller_free:
                    ncrypt.NCryptFreeObject(key)
        finally:
            crypt32.CertCloseStore(store, 0)


# ---------------------------------------------------------------- Linux ----

else:
    _list_impl = None  # no universal OS store; PKCS#11 is the only path
    _sign_impl = None


def list_certificates():
    """Contract-shaped entries from the OS store; [] where none exists.

    Tolerant like the PKCS#11 scan: a broken store read is logged and yields
    nothing rather than hiding certificates found on tokens.
    """
    if _list_impl is None:
        return []
    try:
        return _list_impl()
    except Exception as exc:
        log.warning("OS store listing failed: %s", exc)
        return []


def sign_hashes(thumbprint, hashes, digest_algorithm="sha256"):
    """Sign raw digests with the OS-store key matching the thumbprint.

    Raises CERT_NOT_FOUND when the platform has no OS store or the
    certificate is not in it, so callers can fall back or report cleanly.
    """
    if digest_algorithm not in DIGEST_ALGORITHMS:
        raise HostError("UNSUPPORTED", "unsupported digest algorithm: %r" % digest_algorithm)
    if not hashes:
        raise HostError("INTERNAL", "hashes must be a non-empty list")
    if _sign_impl is None:
        raise HostError("CERT_NOT_FOUND", "this platform has no OS certificate store")
    return _sign_impl(thumbprint.lower().strip(), hashes, digest_algorithm)
