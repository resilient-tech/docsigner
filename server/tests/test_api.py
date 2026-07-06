import base64
import os
import time
from pathlib import Path

from helpers_server import sign_hash


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _start_session(client, signer, blank_pdf, options=None):
    _, cert_der = signer
    response = client.post(
        "/api/signatures",
        json={
            "document": b64(blank_pdf),
            "certificate": b64(cert_der),
            "options": options or {"profile": "B-B"},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_full_token_flow(client, signer, blank_pdf):
    key, _ = signer
    started = _start_session(client, signer, blank_pdf)
    assert started["digest_algorithm"] == "sha256"
    assert len(started["session_id"]) == 32
    assert started["expires_at"].endswith("Z")

    to_sign_hash = base64.b64decode(started["to_sign_hash"])
    signature = sign_hash(key, to_sign_hash)

    completed = client.post(
        f"/api/signatures/{started['session_id']}/complete",
        json={"signature": b64(signature)},
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["download_url"] == f"/api/documents/{body['document_id']}"

    download = client.get(body["download_url"])
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    signed_pdf = download.content

    validated = client.post("/api/validate", json={"document": b64(signed_pdf)})
    assert validated.status_code == 200
    signatures = validated.json()["signatures"]
    assert len(signatures) == 1
    assert signatures[0]["intact"] is True
    assert signatures[0]["valid"] is True
    assert signatures[0]["trusted"] is False
    assert "Token Signer" in signatures[0]["signer"]

    # Sessions are single-use.
    replay = client.post(
        f"/api/signatures/{started['session_id']}/complete",
        json={"signature": b64(signature)},
    )
    assert replay.status_code == 404
    assert replay.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_session_not_found(client):
    response = client.post(
        "/api/signatures/no-such-session/complete",
        json={"signature": b64(b"\x00" * 256)},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_session_expired(client, signer, blank_pdf):
    key, _ = signer
    started = _start_session(client, signer, blank_pdf)
    session_file = Path(os.environ["SESSION_DIR"]) / started["session_id"]
    stale = time.time() - 10_000
    os.utime(session_file, (stale, stale))

    signature = sign_hash(key, base64.b64decode(started["to_sign_hash"]))
    response = client.post(
        f"/api/signatures/{started['session_id']}/complete",
        json={"signature": b64(signature)},
    )
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "SESSION_EXPIRED"


def test_garbage_signature_then_retry(client, signer, blank_pdf):
    key, _ = signer
    started = _start_session(client, signer, blank_pdf)

    bad = client.post(
        f"/api/signatures/{started['session_id']}/complete",
        json={"signature": b64(b"\x00" * 256)},
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "SIGNATURE_INVALID"

    # A failed attempt does not burn the session.
    signature = sign_hash(key, base64.b64decode(started["to_sign_hash"]))
    retry = client.post(
        f"/api/signatures/{started['session_id']}/complete",
        json={"signature": b64(signature)},
    )
    assert retry.status_code == 200


def test_document_invalid(client, signer):
    _, cert_der = signer
    response = client.post(
        "/api/signatures",
        json={"document": "!!! not base64 !!!", "certificate": b64(cert_der)},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DOCUMENT_INVALID"


def test_cert_invalid(client, blank_pdf):
    response = client.post(
        "/api/signatures",
        json={"document": b64(blank_pdf), "certificate": b64(b"junk cert")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CERT_INVALID"


def test_profile_unsupported(client, signer, blank_pdf):
    _, cert_der = signer
    # B-T needs a TSA and the test config has none.
    response = client.post(
        "/api/signatures",
        json={
            "document": b64(blank_pdf),
            "certificate": b64(cert_der),
            "options": {"profile": "B-T"},
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PROFILE_UNSUPPORTED"


def test_lt_completion_failure_maps_to_500(client, signer, blank_pdf, monkeypatch):
    """LTV augmentation that cannot certify the signer chain surfaces as INTERNAL."""
    from helpers_server import make_dummy_timestamper
    from pyhanko_certvalidator import ValidationContext

    import signer_server.app as app_module

    dummy_tsa = make_dummy_timestamper()
    # A TSA and trust anchors are configured, so the session starts; but the
    # self-signed token cert has no path to the configured root, so the
    # revocation-data step at completion must fail.
    monkeypatch.setattr(app_module, "make_timestamper", lambda url: dummy_tsa)
    monkeypatch.setattr(
        app_module,
        "_signing_validation_context",
        lambda: ValidationContext(
            trust_roots=[dummy_tsa.tsa_cert], allow_fetching=False
        ),
    )

    key, _ = signer
    started = _start_session(client, signer, blank_pdf, options={"profile": "B-LT"})
    signature = sign_hash(key, base64.b64decode(started["to_sign_hash"]))
    completed = client.post(
        f"/api/signatures/{started['session_id']}/complete",
        json={"signature": b64(signature)},
    )
    assert completed.status_code == 500
    assert completed.json()["error"]["code"] == "INTERNAL"


def test_document_not_found(client):
    response = client.get("/api/documents/no-such-document")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_server_side_flow(client, blank_pdf):
    response = client.post(
        "/api/sign-server-side",
        json={"document": b64(blank_pdf), "options": {"reason": "server test"}},
    )
    assert response.status_code == 200, response.text
    body = response.json()

    download = client.get(body["download_url"])
    assert download.status_code == 200

    validated = client.post("/api/validate", json={"document": b64(download.content)})
    signatures = validated.json()["signatures"]
    assert signatures[0]["intact"] is True
    assert signatures[0]["valid"] is True
    assert "Server P12 Signer" in signatures[0]["signer"]
