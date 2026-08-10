import base64

import pytest

from signer_host import os_store, pcsc, pkcs11_ops, procs, protocol
from signer_host.errors import HostError


@pytest.fixture(autouse=True)
def no_real_hardware(monkeypatch):
    """Keep the dispatch tests off this machine's actual devices.

    protocol._list_certificates merges three sources. Tests stub the PKCS#11
    one, but the reader scan and the OS store answer from real hardware: with
    a DSC token plugged in, an empty-scan test sees a device and asserts
    against diagnostics that now carry hostWillRestart and a live keychain
    count. That passes in CI, which has no token, and fails on the desk where
    the hardware testing happens. Stub both; a test that wants readers or
    store entries overrides this.
    """
    monkeypatch.setattr(pcsc, "detect_readers", lambda: [])
    monkeypatch.setattr(os_store, "list_certificates", lambda: [])


def test_get_version_echoes_id():
    response = protocol.handle_message({"id": "a1", "command": "getVersion", "params": {}})
    assert response["id"] == "a1"
    result = response["result"]
    assert result["version"] == protocol.VERSION
    assert result["protocolVersion"] == 1
    assert result["logPath"].endswith("host.log")


def test_unknown_command_is_unsupported():
    response = protocol.handle_message({"id": "a2", "command": "formatDisk", "params": {}})
    assert response["id"] == "a2"
    assert response["error"]["code"] == "UNSUPPORTED"


def test_missing_command_is_unsupported():
    response = protocol.handle_message({"id": "a3"})
    assert response["id"] == "a3"
    assert response["error"]["code"] == "UNSUPPORTED"


def test_malformed_json_is_internal():
    response = protocol.handle_raw(b"this is not json")
    assert response["id"] is None
    assert response["error"]["code"] == "INTERNAL"


def test_non_object_request_is_internal():
    response = protocol.handle_raw(b"[1, 2, 3]")
    assert response["error"]["code"] == "INTERNAL"


def test_host_error_code_surfaces(monkeypatch):
    def boom(*args, **kwargs):
        raise HostError("PIN_LOCKED", "locked")

    monkeypatch.setattr(pkcs11_ops, "sign_hashes", boom)
    digest = base64.b64encode(b"\x00" * 32).decode("ascii")
    response = protocol.handle_message({
        "id": "a4", "command": "signHash",
        "params": {"thumbprint": "ab", "hashes": [digest]},
    })
    assert response["id"] == "a4"
    assert response["error"] == {"code": "PIN_LOCKED", "message": "locked"}


def test_broken_discovery_source_yields_empty_list(monkeypatch):
    """One failing discovery source (here pkcs11) must not error the whole
    listing; protocol._safe logs it and the other sources still answer."""
    def boom(stats=None):
        raise ValueError("surprise")

    monkeypatch.setattr(pkcs11_ops, "list_certificates", boom)
    response = protocol.handle_message({"id": "a5", "command": "listCertificates", "params": {}})
    assert response["id"] == "a5"
    assert response["result"]["certificates"] == []


def test_list_certificates_reports_diagnostics(monkeypatch):
    """An empty list must come with counters saying where the scan stopped."""
    def fake_list(stats=None):
        if stats is not None:
            stats.update(configured=2, loaded=1, tokens=0)
        return []

    monkeypatch.setattr(pkcs11_ops, "list_certificates", fake_list)
    monkeypatch.setattr(procs, "competing", lambda: [])
    response = protocol.handle_message({"id": "a5b", "command": "listCertificates", "params": {}})
    assert response["result"]["diagnostics"] == {
        "modulesConfigured": 2,
        "modulesLoaded": 1,
        "tokens": 0,
        "pkcs11Certificates": 0,
        "osStoreCertificates": 0,
    }


def test_diagnostics_name_stuck_modules_and_competitors(monkeypatch):
    def fake_list(stats=None):
        if stats is not None:
            stats.update(configured=1, loaded=0, tokens=0, stuck=["wdpkcs.dll"])
        return []

    monkeypatch.setattr(pkcs11_ops, "list_certificates", fake_list)
    monkeypatch.setattr(procs, "competing", lambda: ["a competing signing host"])
    response = protocol.handle_message({"id": "a5c", "command": "listCertificates", "params": {}})
    diagnostics = response["result"]["diagnostics"]
    assert diagnostics["stuckModules"] == ["wdpkcs.dll"]
    assert diagnostics["competingProcesses"] == ["a competing signing host"]


def test_wedged_scan_requests_restart(monkeypatch):
    """Driver loaded, device present, zero certificates: reply, then exit so
    the next request gets a fresh process (fresh C_Initialize)."""
    monkeypatch.setattr(protocol, "restart_requested", False)

    def fake_list(stats=None):
        stats.update(configured=1, loaded=1, tokens=1)
        return []

    monkeypatch.setattr(pkcs11_ops, "list_certificates", fake_list)
    monkeypatch.setattr(procs, "competing", lambda: [])
    response = protocol.handle_message({"id": "a5e", "command": "listCertificates", "params": {}})
    assert response["result"]["diagnostics"]["hostWillRestart"] is True
    assert protocol.restart_requested


def test_no_restart_when_no_device_seen(monkeypatch):
    monkeypatch.setattr(protocol, "restart_requested", False)

    def fake_list(stats=None):
        stats.update(configured=1, loaded=1, tokens=0)
        return []

    monkeypatch.setattr(pkcs11_ops, "list_certificates", fake_list)
    monkeypatch.setattr(procs, "competing", lambda: [])
    response = protocol.handle_message({"id": "a5f", "command": "listCertificates", "params": {}})
    assert "hostWillRestart" not in response["result"]["diagnostics"]
    assert not protocol.restart_requested


def test_no_process_scan_when_certificates_found(monkeypatch):
    monkeypatch.setattr(pkcs11_ops, "list_certificates",
                        lambda stats=None: [{"thumbprint": "aa", "source": "pkcs11"}])
    monkeypatch.setattr(procs, "competing",
                        lambda: pytest.fail("must not scan processes on a good listing"))
    response = protocol.handle_message({"id": "a5d", "command": "listCertificates", "params": {}})
    assert "competingProcesses" not in response["result"]["diagnostics"]


def test_sign_hash_rejects_bad_base64():
    response = protocol.handle_message({
        "id": "a6", "command": "signHash",
        "params": {"thumbprint": "ab", "hashes": ["not base64!!!"]},
    })
    assert response["error"]["code"] == "INTERNAL"


def test_sign_hash_requires_params():
    response = protocol.handle_message({"id": "a7", "command": "signHash", "params": {}})
    assert response["error"]["code"] == "INTERNAL"


def test_sign_hash_pin_param_replaces_prompt(monkeypatch):
    captured = {}

    def fake(thumbprint, hashes, algorithm, pin_provider=None):
        captured["pin"] = pin_provider("label") if pin_provider else None
        return [b"sig"]

    monkeypatch.setattr(pkcs11_ops, "sign_hashes", fake)
    digest = base64.b64encode(b"\x01" * 32).decode("ascii")

    protocol.handle_message({"id": "p1", "command": "signHash",
                             "params": {"thumbprint": "ab", "hashes": [digest], "pin": "1234"}})
    assert captured["pin"] == "1234"

    protocol.handle_message({"id": "p2", "command": "signHash",
                             "params": {"thumbprint": "ab", "hashes": [digest]}})
    assert captured["pin"] is None  # no pin -> native prompt path

    protocol.handle_message({"id": "p3", "command": "signHash",
                             "params": {"thumbprint": "ab", "hashes": [digest], "pin": ""}})
    assert captured["pin"] is None  # empty pin treated as absent

    response = protocol.handle_message({"id": "p4", "command": "signHash",
                                        "params": {"thumbprint": "ab", "hashes": [digest],
                                                   "pin": 1234}})
    assert response["error"]["code"] == "INTERNAL"


def test_sign_hash_encodes_signatures_as_base64(monkeypatch):
    monkeypatch.setattr(pkcs11_ops, "sign_hashes",
                        lambda thumbprint, hashes, algorithm: [b"sig-bytes"])
    digest = base64.b64encode(b"\x01" * 32).decode("ascii")
    response = protocol.handle_message({
        "id": "a8", "command": "signHash",
        "params": {"thumbprint": "ab", "hashes": [digest], "digestAlgorithm": "sha256"},
    })
    assert response["result"]["signatures"] == [base64.b64encode(b"sig-bytes").decode("ascii")]


def test_check_update_dispatches(monkeypatch):
    from signer_host import update
    monkeypatch.setattr(update, "check_update", lambda: {"updateAvailable": False})
    response = protocol.handle_message({"id": "u1", "command": "checkUpdate", "params": {}})
    assert response == {"id": "u1", "result": {"updateAvailable": False}}


def test_sign_hash_fires_notification(monkeypatch):
    from signer_host import notify
    calls = []
    monkeypatch.setattr(notify, "notify", lambda title, body: calls.append((title, body)))
    monkeypatch.setattr(pkcs11_ops, "sign_hashes",
                        lambda thumbprint, hashes, algorithm: [b"sig"])
    digest = base64.b64encode(b"\x01" * 32).decode("ascii")
    protocol.handle_message({"id": "n1", "command": "signHash",
                             "params": {"thumbprint": "abcdef123456789", "hashes": [digest]}})
    assert len(calls) == 1
    assert "abcdef123456" in calls[0][1]
