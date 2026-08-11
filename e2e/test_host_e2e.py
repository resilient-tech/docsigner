"""Live host e2e against the real binary, independent of the server.

Two layers:
  1. The shipped `docsigner-host` binary over its stdio framing — proves the
     actual process and the native messaging wire work, including request
     multiplexing and the error shape.
  2. A real-DSC path gated by DOCSIGNER_E2E_REAL_TOKEN=1 — plug the token in,
     run it on your own machine. Signatures are verified against the
     certificate's public key, so a wrong CMS wrapping fails here.

What used to sit between them was a fake PKCS#11 token driven through the
Python host's own modules, which verified signatures with no hardware. That
went with host/. The Rust host's `cargo test` covers dispatch, parameter
validation and the DigestInfo and ECDSA encodings, but nothing exercises a
token without hardware any more. Provisioning SoftHSM2 in CI and pointing
DOCSIGNER_PKCS11_MODULES at it would restore that layer; until then the
signature path is only proven on a real token.
"""

import base64
import json
import os
import secrets
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from cryptography.x509 import load_der_x509_certificate

REPO_ROOT = Path(__file__).resolve().parents[1]
BINARY_NAME = "docsigner-host.exe" if sys.platform == "win32" else "docsigner-host"
PIN = os.environ.get("DOCSIGNER_PIN", "admin@123")


def host_binary() -> Path:
    """The built host binary, release before debug."""
    override = os.environ.get("DOCSIGNER_HOST_BIN")
    if override:
        return Path(override)
    target = REPO_ROOT / "host-rs" / "target"
    for candidate in (target / "release" / BINARY_NAME, target / "debug" / BINARY_NAME):
        if candidate.is_file():
            return candidate
    pytest.skip(
        "host binary not built: cargo build --release --manifest-path host-rs/Cargo.toml"
    )


# Chrome native messaging framing, inlined: the host is no longer a Python
# package we can import a codec from, which is the point of this test.
def _send(proc, message: dict) -> None:
    payload = json.dumps(message).encode()
    proc.stdin.write(struct.pack("<I", len(payload)) + payload)
    proc.stdin.flush()


def _recv(proc) -> dict:
    header = proc.stdout.read(4)
    assert len(header) == 4, "host closed the pipe without a reply"
    (length,) = struct.unpack("<I", header)
    return json.loads(proc.stdout.read(length).decode())


class Host:
    """One host process, spoken to over real framing."""

    def __init__(self):
        self.proc = subprocess.Popen(
            [str(host_binary())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def ask(self, command: str, params: dict | None = None, request_id="1") -> dict:
        _send(self.proc, {"id": request_id, "command": command, "params": params or {}})
        return _recv(self.proc)

    def close(self, timeout=30):
        self.proc.stdin.close()
        self.proc.wait(timeout=timeout)


@pytest.fixture
def host():
    h = Host()
    try:
        yield h
    finally:
        try:
            h.close()
        except Exception:
            h.proc.kill()


# ------------------------------------------------------------ 1. the real binary

def test_host_process_getversion(host):
    response = host.ask("getVersion")
    assert response["id"] == "1"
    assert response["result"]["protocolVersion"] == 1
    assert response["result"]["version"]
    assert response["result"]["logPath"].endswith("host.log")


def test_host_unknown_command(host):
    response = host.ask("noSuchCommand", request_id="x")
    assert response["id"] == "x"
    assert response["error"]["code"] == "UNSUPPORTED"


def test_host_multiplexes_request_ids(host):
    """One process, several requests, replies matched by id, including a
    non-string id. The extension relies on this."""
    for request_id in ("a", 42, "c"):
        response = host.ask("getVersion", request_id=request_id)
        assert response["id"] == request_id


def test_host_list_certificates_always_answers(host):
    """With or without a token, listCertificates returns a shaped result and
    diagnostics that explain an empty list."""
    result = host.ask("listCertificates")["result"]
    assert isinstance(result["certificates"], list)
    for key in ("modulesConfigured", "modulesLoaded", "tokens",
                "pkcs11Certificates", "osStoreCertificates"):
        assert isinstance(result["diagnostics"][key], int), f"missing {key}"


def test_host_rejects_a_malformed_sign_request(host):
    response = host.ask("signHash", {"hashes": ["AA=="]})
    assert response["error"]["code"] == "INTERNAL"


# ------------------------------------------------------------ 2. real DSC (gated)

@pytest.mark.skipif(
    os.environ.get("DOCSIGNER_E2E_REAL_TOKEN") != "1",
    reason="real DSC token path: set DOCSIGNER_E2E_REAL_TOKEN=1 with the token plugged in",
)
def test_host_real_token(host):
    """Runs on your machine: lists the token's certificates and signs a digest
    with the real PIN, verifying the signature against the certificate."""
    certs = host.ask("listCertificates")["result"]["certificates"]
    assert certs, "no certificates on the token — is it plugged in and the driver installed?"

    cert = certs[0]
    digest = secrets.token_bytes(32)
    signed = host.ask("signHash", {
        "thumbprint": cert["thumbprint"],
        "hashes": [base64.b64encode(digest).decode()],
        "digestAlgorithm": "sha256",
        "pin": PIN,
    }, request_id="2")
    assert "error" not in signed, signed.get("error")
    sig = base64.b64decode(signed["result"]["signatures"][0])

    pub = load_der_x509_certificate(base64.b64decode(cert["certificate"])).public_key()
    if cert["keyType"] == "EC":
        pub.verify(sig, digest, ec.ECDSA(Prehashed(hashes.SHA256())))
    else:
        pub.verify(sig, digest, padding.PKCS1v15(), Prehashed(hashes.SHA256()))


@pytest.mark.skipif(
    os.environ.get("DOCSIGNER_E2E_REAL_TOKEN") != "1",
    reason="real DSC token path: set DOCSIGNER_E2E_REAL_TOKEN=1 with the token plugged in",
)
def test_host_real_token_signs_a_batch_in_one_login(host):
    """The one-PIN-per-batch promise: several digests, one signHash, each
    signature verifying against its own digest and not its neighbour's."""
    certs = host.ask("listCertificates")["result"]["certificates"]
    assert certs, "no certificates on the token"
    cert = certs[0]
    if cert["keyType"] != "RSA":
        pytest.skip("batch check is written for the RSA path")

    digests = [secrets.token_bytes(32) for _ in range(3)]
    signed = host.ask("signHash", {
        "thumbprint": cert["thumbprint"],
        "hashes": [base64.b64encode(d).decode() for d in digests],
        "digestAlgorithm": "sha256",
        "pin": PIN,
    }, request_id="batch")
    assert "error" not in signed, signed.get("error")
    sigs = [base64.b64decode(s) for s in signed["result"]["signatures"]]
    assert len(sigs) == len(digests)

    pub = load_der_x509_certificate(base64.b64decode(cert["certificate"])).public_key()
    for i, (sig, digest) in enumerate(zip(sigs, digests)):
        pub.verify(sig, digest, padding.PKCS1v15(), Prehashed(hashes.SHA256()))
        # Order matters: signature i must not verify against a different digest.
        with pytest.raises(Exception):
            pub.verify(sig, digests[(i + 1) % len(digests)],
                       padding.PKCS1v15(), Prehashed(hashes.SHA256()))
