"""E2E fixtures: load .env.e2e, boot a real docsigner-server subprocess, and
hand tests a base URL + HTTP client. Nothing is mocked here — this is the
actual server over a real socket.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(__file__).resolve().parent / ".env.e2e"


def _load_env():
    """Minimal .env loader (no python-dotenv dependency); existing env wins."""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env()

# Drop the SOCKS proxy vars. The HTTP client prefers them even for localhost,
# and the library that would handle them is not installed. The plain HTTP proxy
# stays, because the server needs it to reach the timestamp authority.
for _v in ("ALL_PROXY", "all_proxy", "GRPC_PROXY", "grpc_proxy", "FTP_PROXY",
           "ftp_proxy", "RSYNC_PROXY"):
    os.environ.pop(_v, None)


def _free_or_configured_port(env_name, default):
    want = int(os.environ.get(env_name, default))
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", want))
            return want
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def _make_server_p12(path: Path, passphrase: str):
    from cryptography.hazmat.primitives.serialization import BestAvailableEncryption
    from cryptography.hazmat.primitives.serialization.pkcs12 import (
        serialize_key_and_certificates,
    )
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import datetime

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, os.environ.get("E2E_SIGNER_ORG", "DocSigner Tests")),
        x509.NameAttribute(NameOID.COMMON_NAME, os.environ.get("E2E_SIGNER_CN", "Server Key") + " (server)"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(serialize_key_and_certificates(
        b"server", key, cert, None, BestAvailableEncryption(passphrase.encode())))


@pytest.fixture(scope="session")
def server_base_url():
    tmp = Path(tempfile.mkdtemp(prefix="docsigner-e2e-"))
    port = _free_or_configured_port("E2E_SERVER_PORT", "8899")
    passphrase = os.environ.get("E2E_P12_PASSPHRASE", "admin@123")
    p12 = tmp / "server.p12"
    _make_server_p12(p12, passphrase)

    trust_dir = os.environ.get("E2E_TRUST_DIR", "./trust")

    env = os.environ.copy()
    env.update({
        "PORT": str(port),
        "SESSION_DIR": str(tmp / "sessions"),
        "DOCUMENT_DIR": str(tmp / "documents"),
        "P12_PATH": str(p12),
        "P12_PASSPHRASE": passphrase,
        "TSA_URL": os.environ.get("TSA_URL", "http://timestamp.digicert.com"),
        "TRUST_DIR": trust_dir,
        "MAX_PDF_MB": "50",
    })

    proc = subprocess.Popen(
        [sys.executable, "-m", "docsigner_server"],
        cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("server exited early:\n" + proc.stdout.read())
        try:
            httpx.get(base + "/api/documents/nope", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.3)
    else:
        proc.terminate()
        raise RuntimeError("server did not come up in time")

    yield base

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture(scope="session")
def api(server_base_url):
    with httpx.Client(base_url=server_base_url + "/api", timeout=60) as client:
        yield client


@pytest.fixture(scope="session")
def tsa_reachable(api):
    """True only when the live server can actually mint a timestamp, probed
    through its real code path (one B-T server-side sign). Timestamped profiles
    skip when it can't — e.g. a proxy that blocks the RFC 3161 POST."""
    import base64

    from helpers import make_blank_pdf

    try:
        r = api.post("/sign-server-side", json={
            "document": base64.b64encode(make_blank_pdf()).decode(),
            "options": {"profile": "B-T"}})
        return r.status_code == 200
    except httpx.HTTPError:
        return False
