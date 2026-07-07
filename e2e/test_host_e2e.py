"""Live host e2e, independent of the server.

Three layers:
  1. The real host binary over its stdio framing (getVersion) — proves the
     actual process + native-messaging wire works.
  2. listCertificates / signHash driven through the real framing codec and
     protocol dispatcher against a fake PKCS#11 token, PIN = OPENSIGNER_PIN.
     Signatures are verified against the certificate's public key, so a wrong
     CMS wrapping fails here.
  3. A real-DSC path gated by OPENSIGNER_E2E_REAL_TOKEN=1 — plug the token in,
     point OPENSIGNER_PKCS11_MODULES at its driver, run on your own machine.
"""

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST_TESTS = REPO_ROOT / "host" / "tests"
sys.path.insert(0, str(HOST_TESTS))
sys.path.insert(0, str(REPO_ROOT / "host"))

from signer_host import framing, modules, pkcs11_ops, protocol  # noqa: E402
# Reuse the fake PKCS#11 stack the host unit tests already ship.
from test_pkcs11_ops import ec_token, make_cert, rsa_token  # noqa: E402

PIN = os.environ.get("OPENSIGNER_PIN", "admin@123")


def _roundtrip(message: dict) -> dict:
    """Encode a request as a frame, decode it, dispatch it, encode the response
    as a frame, decode it back — the full wire path, in process."""
    out = io.BytesIO()
    framing.write_message(out, message)
    out.seek(0)
    request = framing.read_message(out)
    response = protocol.handle_message(request)
    back = io.BytesIO()
    framing.write_message(back, response)
    back.seek(0)
    return framing.read_message(back)


@pytest.fixture(autouse=True)
def _clear_pin_cache():
    """The PIN cache is process-wide; keep tests independent of order."""
    pkcs11_ops.clear_pin_cache()
    yield
    pkcs11_ops.clear_pin_cache()


@pytest.fixture
def fake_token(monkeypatch):
    """Install a fake token behind a fake module path; PIN = OPENSIGNER_PIN."""
    def install(kind="rsa"):
        if kind == "ec":
            key = ec.generate_private_key(ec.SECP256R1())
            der = make_cert(key, os.environ.get("E2E_SIGNER_CN", "EC Signer"))
            token = ec_token(key, der)
        else:
            from cryptography.hazmat.primitives.asymmetric import rsa
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            der = make_cert(key, os.environ.get("E2E_SIGNER_CN", "RSA Signer"))
            token = rsa_token(key, der)
        token.expected_pin = PIN
        from test_pkcs11_ops import FakeLib
        lib = FakeLib([token])
        monkeypatch.setattr(modules, "discover_modules", lambda: ["/fake/pkcs11.so"])
        monkeypatch.setattr(pkcs11_ops, "load_library", lambda path: lib)
        return key, der
    return install


# ------------------------------------------------------------ 1. real process

def test_host_process_getversion():
    proc = subprocess.Popen(
        [sys.executable, "-m", "signer_host"],
        cwd=str(REPO_ROOT / "host"),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        framing.write_message(proc.stdin, {"id": "1", "command": "getVersion"})
        response = framing.read_message(proc.stdout)
    finally:
        proc.stdin.close()
        proc.wait(timeout=5)
    assert response["id"] == "1"
    assert response["result"]["protocolVersion"] == 1
    assert response["result"]["version"]


# ------------------------------------------------------------ 2. wire + fake token

def test_host_list_certificates_wire(fake_token):
    key, der = fake_token("rsa")
    resp = _roundtrip({"id": "L", "command": "listCertificates", "params": {}})
    certs = resp["result"]["certificates"]
    assert len(certs) == 1
    import base64
    import hashlib
    assert certs[0]["thumbprint"] == hashlib.sha1(der).hexdigest()
    assert base64.b64decode(certs[0]["certificate"]) == der
    assert certs[0]["keyType"] == "RSA"
    assert os.environ.get("E2E_SIGNER_CN", "RSA Signer") in certs[0]["subject"]


@pytest.mark.parametrize("kind", ["rsa", "ec"])
def test_host_sign_hash_wire(fake_token, kind):
    import base64
    import hashlib
    import secrets

    key, der = fake_token(kind)
    thumbprint = hashlib.sha1(der).hexdigest()
    digest = secrets.token_bytes(32)  # a fake sha256 message imprint
    resp = _roundtrip({"id": "S", "command": "signHash", "params": {
        "thumbprint": thumbprint,
        "hashes": [base64.b64encode(digest).decode()],
        "digestAlgorithm": "sha256",
        "pin": PIN,
    }})
    sig = base64.b64decode(resp["result"]["signatures"][0])
    pub = key.public_key()
    if kind == "ec":
        pub.verify(sig, digest, ec.ECDSA(Prehashed(hashes.SHA256())))  # DER Sig-Value
    else:
        pub.verify(sig, digest, padding.PKCS1v15(), Prehashed(hashes.SHA256()))


def test_host_wrong_pin_rejected(fake_token):
    import base64
    import hashlib
    import secrets

    key, der = fake_token("rsa")
    resp = _roundtrip({"id": "W", "command": "signHash", "params": {
        "thumbprint": hashlib.sha1(der).hexdigest(),
        "hashes": [base64.b64encode(secrets.token_bytes(32)).decode()],
        "pin": "wrong-pin",
    }})
    assert resp["error"]["code"] == "PIN_INCORRECT"


def test_host_unknown_command():
    resp = _roundtrip({"id": "U", "command": "frobnicate", "params": {}})
    assert resp["error"]["code"] == "UNSUPPORTED"


# ------------------------------------------------------------ 3. real DSC (gated)

@pytest.mark.skipif(
    os.environ.get("OPENSIGNER_E2E_REAL_TOKEN") != "1",
    reason="real DSC token path: set OPENSIGNER_E2E_REAL_TOKEN=1 with the token plugged in",
)
def test_host_real_token():
    """Runs on your machine: lists the token's certs and signs a digest with
    the real PIN, verifying the signature against the certificate."""
    import base64
    import hashlib
    import secrets

    from cryptography.x509 import load_der_x509_certificate

    def send(proc, msg):
        framing.write_message(proc.stdin, msg)
        return framing.read_message(proc.stdout)

    proc = subprocess.Popen(
        [sys.executable, "-m", "signer_host"], cwd=str(REPO_ROOT / "host"),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        listed = send(proc, {"id": "1", "command": "listCertificates", "params": {}})
        certs = listed["result"]["certificates"]
        assert certs, "no certificates on the token — is it plugged in and the driver installed?"
        cert = certs[0]
        digest = secrets.token_bytes(32)
        signed = send(proc, {"id": "2", "command": "signHash", "params": {
            "thumbprint": cert["thumbprint"],
            "hashes": [base64.b64encode(digest).decode()],
            "digestAlgorithm": "sha256",
            "pin": PIN,
        }})
        sig = base64.b64decode(signed["result"]["signatures"][0])
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)

    pub = load_der_x509_certificate(base64.b64decode(cert["certificate"])).public_key()
    if cert["keyType"] == "EC":
        pub.verify(sig, digest, ec.ECDSA(Prehashed(hashes.SHA256())))
    else:
        pub.verify(sig, digest, padding.PKCS1v15(), Prehashed(hashes.SHA256()))
