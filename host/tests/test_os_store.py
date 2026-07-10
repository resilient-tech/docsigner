"""OS-store merge and fallback logic. The platform backends (Keychain, CNG)
are ctypes over OS APIs and need real hardware; what's testable everywhere is
the dispatch: dedupe on listing, fallback order on signing, error selection.
"""

import base64
import sys

import pytest

from signer_host import os_store, pkcs11_ops, protocol
from signer_host.errors import HostError


def _cert(thumbprint, source):
    return {"thumbprint": thumbprint, "source": source}


def _sign_request(thumbprint="ab", alg="sha256"):
    digest = base64.b64encode(b"\x01" * 32).decode("ascii")
    return {"id": "t", "command": "signHash",
            "params": {"thumbprint": thumbprint, "hashes": [digest],
                       "digestAlgorithm": alg}}


# --- listing -----------------------------------------------------------

def test_list_merges_and_dedupes_pkcs11_first(monkeypatch):
    monkeypatch.setattr(pkcs11_ops, "list_certificates",
                        lambda stats=None: [_cert("aa", "pkcs11"), _cert("bb", "pkcs11")])
    monkeypatch.setattr(os_store, "list_certificates",
                        lambda: [_cert("bb", "os-store"), _cert("cc", "os-store")])
    response = protocol.handle_message({"id": "t", "command": "listCertificates", "params": {}})
    certs = response["result"]["certificates"]
    assert [(c["thumbprint"], c["source"]) for c in certs] == [
        ("aa", "pkcs11"), ("bb", "pkcs11"), ("cc", "os-store")]


def test_list_works_with_empty_os_store(monkeypatch):
    monkeypatch.setattr(pkcs11_ops, "list_certificates", lambda stats=None: [_cert("aa", "pkcs11")])
    monkeypatch.setattr(os_store, "list_certificates", lambda: [])
    response = protocol.handle_message({"id": "t", "command": "listCertificates", "params": {}})
    assert len(response["result"]["certificates"]) == 1


# --- signing fallback --------------------------------------------------

def test_sign_prefers_pkcs11(monkeypatch):
    monkeypatch.setattr(pkcs11_ops, "sign_hashes", lambda *a: [b"token-sig"])
    monkeypatch.setattr(os_store, "sign_hashes",
                        lambda *a: pytest.fail("os_store must not be tried"))
    response = protocol.handle_message(_sign_request())
    assert response["result"]["signatures"] == [base64.b64encode(b"token-sig").decode()]


def test_sign_falls_back_to_os_store_when_no_token(monkeypatch):
    def no_token(*a):
        raise HostError("TOKEN_NOT_FOUND", "no token")
    monkeypatch.setattr(pkcs11_ops, "sign_hashes", no_token)
    monkeypatch.setattr(os_store, "sign_hashes", lambda *a: [b"os-sig"])
    response = protocol.handle_message(_sign_request())
    assert response["result"]["signatures"] == [base64.b64encode(b"os-sig").decode()]


def test_sign_missing_everywhere_reports_pkcs11_error(monkeypatch):
    def no_token(*a):
        raise HostError("TOKEN_NOT_FOUND", "plug in the device")
    def not_in_store(*a):
        raise HostError("CERT_NOT_FOUND", "not in store")
    monkeypatch.setattr(pkcs11_ops, "sign_hashes", no_token)
    monkeypatch.setattr(os_store, "sign_hashes", not_in_store)
    response = protocol.handle_message(_sign_request())
    assert response["error"] == {"code": "TOKEN_NOT_FOUND", "message": "plug in the device"}


def test_sign_os_store_cancellation_surfaces(monkeypatch):
    def no_cert(*a):
        raise HostError("CERT_NOT_FOUND", "not on token")
    def cancelled(*a):
        raise HostError("USER_CANCELLED", "cancelled")
    monkeypatch.setattr(pkcs11_ops, "sign_hashes", no_cert)
    monkeypatch.setattr(os_store, "sign_hashes", cancelled)
    response = protocol.handle_message(_sign_request())
    assert response["error"]["code"] == "USER_CANCELLED"


def test_sign_pin_errors_do_not_fall_back(monkeypatch):
    def locked(*a):
        raise HostError("PIN_LOCKED", "locked")
    monkeypatch.setattr(pkcs11_ops, "sign_hashes", locked)
    monkeypatch.setattr(os_store, "sign_hashes",
                        lambda *a: pytest.fail("os_store must not be tried"))
    response = protocol.handle_message(_sign_request())
    assert response["error"]["code"] == "PIN_LOCKED"


# --- module-level guards ----------------------------------------------

def test_sign_rejects_bad_algorithm():
    with pytest.raises(HostError) as exc:
        os_store.sign_hashes("ab", [b"\x01" * 32], "md5")
    assert exc.value.code == "UNSUPPORTED"


def test_sign_rejects_empty_hashes():
    with pytest.raises(HostError) as exc:
        os_store.sign_hashes("ab", [])
    assert exc.value.code == "INTERNAL"


@pytest.mark.skipif(sys.platform in ("darwin", "win32"), reason="Linux/other only")
def test_unsupported_platform_lists_nothing_and_signs_nothing():
    assert os_store.list_certificates() == []
    with pytest.raises(HostError) as exc:
        os_store.sign_hashes("ab", [b"\x01" * 32])
    assert exc.value.code == "CERT_NOT_FOUND"
