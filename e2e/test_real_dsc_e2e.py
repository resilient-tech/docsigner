"""Real DSC token + real server: the revocation-embedding profiles end to end.

Gated on OPENSIGNER_E2E_REAL_TOKEN=1 (plug the token in). The self-signed certs
the rest of the server matrix uses cannot answer OCSP, so B-LT/B-LTA/CCA-LTV/
CCA-LTA skip there; here the token's CA-issued DSC drives them through the real
server, and each signed output is checked to verify offline from its DSS alone,
which is the bar Adobe applies for "LTV enabled".
"""

import asyncio
import io
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "host"))
sys.path.insert(0, str(REPO_ROOT / "core"))

from helpers import b64, has_cca_revinfo, read_dss  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("OPENSIGNER_E2E_REAL_TOKEN") != "1",
    reason="real DSC path: set OPENSIGNER_E2E_REAL_TOKEN=1 with the token plugged in",
)

PIN = os.environ.get("OPENSIGNER_PIN", "admin@123")
LTV_PROFILES = ["B-LT", "B-LTA", "CCA-LTV", "CCA-LTA"]


def _signing_cert():
    """The token's first certificate that can sign (digitalSignature/nonRepudiation)."""
    from signer_host import protocol

    resp = protocol.handle_message({"id": "L", "command": "listCertificates", "params": {}})
    certs = resp.get("result", {}).get("certificates", [])
    assert certs, "no certificates on the token; plug it in and install the driver"
    for cert in certs:
        usage = cert.get("keyUsage") or {}
        if usage.get("digitalSignature") or usage.get("nonRepudiation"):
            return cert
    return certs[0]


def _token_sign(thumbprint, to_sign_hash_b64, digest):
    from signer_host import protocol

    resp = protocol.handle_message({"id": "S", "command": "signHash", "params": {
        "thumbprint": thumbprint, "hashes": [to_sign_hash_b64],
        "digestAlgorithm": digest, "pin": PIN}})
    assert "result" in resp, resp
    return resp["result"]["signatures"][0]


def _download(api, url):
    r = api.get(url.replace("/api", "", 1) if url.startswith("/api") else url)
    r.raise_for_status()
    return r.content


def _dss_verifies_offline(pdf_bytes, trust_dir):
    """The signer validates from trust roots + the DSS's own certs and revinfo,
    require mode, no fetching: the offline check that stands in for Adobe LTV."""
    from asn1crypto import crl as a_crl
    from asn1crypto import ocsp as a_ocsp
    from asn1crypto import x509 as a_x509
    from pyhanko.pdf_utils.generic import IndirectObject
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation.dss import DocumentSecurityStore
    from pyhanko_certvalidator import CertificateValidator, ValidationContext
    from signer_core.trust import load_trust_certs

    def der(o):
        if isinstance(o, IndirectObject):
            o = o.get_object()
        return o.data if hasattr(o, "data") else bytes(o)

    reader = PdfFileReader(io.BytesIO(pdf_bytes))
    dss = DocumentSecurityStore.read_dss(reader)
    emb = reader.embedded_regular_signatures[-1]
    roots = [c for c in load_trust_certs(trust_dir) if c.subject == c.issuer]
    inter = [c for c in (a_x509.Certificate.load(der(v)) for v in dss.certs.values())
             if c.subject != c.issuer]
    ocsps = [a_ocsp.OCSPResponse.load(der(o)) for o in dss.ocsps]
    crls = [a_crl.CertificateList.load(der(o)) for o in dss.crls]
    ctx = ValidationContext(trust_roots=roots, other_certs=inter, ocsps=ocsps, crls=crls,
                            allow_fetching=False, revocation_mode="require")

    async def go():
        await CertificateValidator(emb.signer_cert, validation_context=ctx).async_validate_usage(set())

    try:
        asyncio.run(go())
        return True
    except Exception:
        return False


@pytest.mark.parametrize("profile", LTV_PROFILES)
def test_real_dsc_ltv_through_server(api, tsa_reachable, profile):
    if not tsa_reachable:
        pytest.skip("TSA unreachable; run where the RFC 3161 endpoint answers")

    from helpers import make_blank_pdf

    cert = _signing_cert()
    r = api.post("/signatures", json={
        "document": b64(make_blank_pdf()),
        "certificate": cert["certificate"],  # already base64 DER from listCertificates
        "options": {"profile": profile},
    })
    r.raise_for_status()
    start = r.json()
    signature = _token_sign(cert["thumbprint"], start["to_sign_hash"], start["digest_algorithm"])
    r = api.post(f"/signatures/{start['session_id']}/complete", json={"signature": signature})
    r.raise_for_status()
    signed = _download(api, r.json()["download_url"])

    report = api.post("/validate", json={"document": b64(signed)}).json()
    sig = report["signatures"][0]
    assert sig["valid"] and sig["intact"] and sig["trusted"], sig

    certs, ocsps, crls = read_dss(signed)
    assert certs and (ocsps or crls), "LTV signature lacks a populated DSS"
    if profile in ("CCA-LTV", "CCA-LTA"):
        assert has_cca_revinfo(signed), "CCA signature lacks pdfRevocationInfoArchival"

    trust_dir = os.environ.get("E2E_TRUST_DIR", "./trust")
    assert _dss_verifies_offline(signed, trust_dir), (
        f"{profile} DSS does not verify offline (would read as not LTV enabled)")
