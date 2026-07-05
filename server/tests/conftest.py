"""Server test setup. The env vars must be in place before signer_server.app
is imported, so the temp dirs and the server p12 are created at import time.

The plain helper functions live in helpers_server.py; see the note there.
"""

import os
import sys
import tempfile
from pathlib import Path

# Make signer_server importable when pytest runs from the tests directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption
from cryptography.hazmat.primitives.serialization.pkcs12 import (
    serialize_key_and_certificates,
)
from helpers_server import make_blank_pdf, make_self_signed_cert

TMP_DIR = Path(tempfile.mkdtemp(prefix="signer-server-tests-"))
P12_PASSPHRASE = "test-passphrase"


def _write_server_p12():
    key, cert = make_self_signed_cert("Server P12 Signer")
    p12_bytes = serialize_key_and_certificates(
        b"server", key, cert, None, BestAvailableEncryption(P12_PASSPHRASE.encode())
    )
    path = TMP_DIR / "server.p12"
    path.write_bytes(p12_bytes)
    return path


os.environ["SESSION_DIR"] = str(TMP_DIR / "sessions")
os.environ["DOCUMENT_DIR"] = str(TMP_DIR / "documents")
os.environ["P12_PATH"] = str(_write_server_p12())
os.environ["P12_PASSPHRASE"] = P12_PASSPHRASE
os.environ.pop("TSA_URL", None)
os.environ.pop("TRUST_DIR", None)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from signer_server.app import app

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def signer():
    key, cert = make_self_signed_cert("Token Signer")
    return key, cert.public_bytes(serialization.Encoding.DER)


@pytest.fixture(scope="session")
def blank_pdf():
    return make_blank_pdf()
