"""Reader identification and the readers field. The PC/SC ctypes call itself
needs a running smart-card service; everything around it is testable anywhere.
"""

from signer_host import modules, pcsc, pkcs11_ops, protocol
from signer_host import os_store


# --- identify ----------------------------------------------------------

def test_identify_known_readers():
    cases = {
        "Watchdata WDIND USB CCID Key 0": "WatchData ProxKey",
        "FT ePass2003Auto 0": "Feitian ePass2003 / Hypersecu HYP2003",
        "HYPERSECU USB TOKEN 0": "Feitian ePass2003 / Hypersecu HYP2003",
        "AKS ifdh 0": "SafeNet eToken",
        "SafeNet Token JC 1": "SafeNet eToken",
        "Longmai mToken CryptoIDA 0": "Longmai mToken CryptoID",
        "Bit4id tokenME FIPS 0": "Bit4id tokenME",
        "Yubico YubiKey OTP+FIDO+CCID": "YubiKey",
        "Gemplus USB SmartCard Reader 0": "Gemalto smartcard",
    }
    for name, expected in cases.items():
        token, hints = pcsc.identify(name)
        assert token == expected, name
        assert hints


def test_identify_unknown_reader():
    assert pcsc.identify("ACME Mystery Reader 3000") == (None, ())


# --- detect_readers ----------------------------------------------------

def test_detect_readers_driver_found(monkeypatch):
    monkeypatch.setattr(pcsc, "reader_names",
                        lambda: ["Watchdata WDIND USB CCID Key 0"])
    monkeypatch.setattr(modules, "discover_modules",
                        lambda: ["/usr/local/lib/libwdpkcs_SignatureP11.dylib"])
    detected = pcsc.detect_readers()
    assert detected == [{"name": "Watchdata WDIND USB CCID Key 0",
                         "token": "WatchData ProxKey", "driverFound": True}]


def test_detect_readers_driver_missing(monkeypatch):
    monkeypatch.setattr(pcsc, "reader_names", lambda: ["AKS ifdh 0"])
    monkeypatch.setattr(modules, "discover_modules", lambda: [])
    detected = pcsc.detect_readers()
    assert detected == [{"name": "AKS ifdh 0", "token": "SafeNet eToken",
                         "driverFound": False}]


def test_detect_readers_empty_when_no_readers(monkeypatch):
    monkeypatch.setattr(pcsc, "reader_names", lambda: [])
    assert pcsc.detect_readers() == []


def test_reader_names_never_raises():
    # On machines without a smart-card service this returns []; it must not throw.
    assert isinstance(pcsc.reader_names(), list)


# --- protocol wiring ---------------------------------------------------

def test_list_includes_readers_when_present(monkeypatch):
    monkeypatch.setattr(pkcs11_ops, "list_certificates", lambda: [])
    monkeypatch.setattr(os_store, "list_certificates", lambda: [])
    monkeypatch.setattr(pcsc, "detect_readers",
                        lambda: [{"name": "AKS ifdh 0", "token": "SafeNet eToken",
                                  "driverFound": False}])
    response = protocol.handle_message({"id": "t", "command": "listCertificates", "params": {}})
    assert response["result"]["certificates"] == []
    assert response["result"]["readers"][0]["token"] == "SafeNet eToken"


def test_list_omits_readers_when_none(monkeypatch):
    monkeypatch.setattr(pkcs11_ops, "list_certificates", lambda: [])
    monkeypatch.setattr(os_store, "list_certificates", lambda: [])
    monkeypatch.setattr(pcsc, "detect_readers", lambda: [])
    response = protocol.handle_message({"id": "t", "command": "listCertificates", "params": {}})
    assert "readers" not in response["result"]
