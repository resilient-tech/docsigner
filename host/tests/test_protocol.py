import base64

from signer_host import pkcs11_ops, protocol
from signer_host.errors import HostError


def test_get_version_echoes_id():
    response = protocol.handle_message({"id": "a1", "command": "getVersion", "params": {}})
    assert response == {"id": "a1", "result": {"version": protocol.VERSION, "protocolVersion": 1}}


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
    def boom():
        raise ValueError("surprise")

    monkeypatch.setattr(pkcs11_ops, "list_certificates", boom)
    response = protocol.handle_message({"id": "a5", "command": "listCertificates", "params": {}})
    assert response["id"] == "a5"
    assert response["result"]["certificates"] == []


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
