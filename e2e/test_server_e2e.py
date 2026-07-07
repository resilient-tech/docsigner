"""Live server e2e: the full profile x flow x algorithm x format matrix, run
against a real signer-server over HTTP, each signed output verified through the
server's own /api/validate plus structural checks on the returned bytes.

What runs where:
  - B-B and B-T sign with a self-signed test cert, so they run anywhere
    (B-T needs the TSA reachable; skips if offline).
  - B-LT, B-LTA, CCA-LTV, CCA-LTA embed revocation fetched from the signer
    cert's CA, which a self-signed cert cannot provide. They are exercised by
    the real-DSC combined path (see test_host_e2e.py, real-token gate) and
    skip here with a clear reason.
"""

import pytest

from helpers import (
    b64,
    has_cca_revinfo,
    has_signature_timestamp,
    make_blank_pdf,
    make_signer_cert,
    make_xml,
    read_dss,
    sign_hash,
    unb64,
)

BASELINE = ["B-B"]
NEEDS_TSA = ["B-T"]
NEEDS_CA_OCSP = ["B-LT", "B-LTA", "CCA-LTV", "CCA-LTA"]
ALL_PDF_PROFILES = BASELINE + NEEDS_TSA + NEEDS_CA_OCSP


def _skip_if_unrunnable(profile, tsa_reachable):
    if profile in NEEDS_TSA and not tsa_reachable:
        pytest.skip("TSA unreachable (offline sandbox); run where DigiCert TSA is reachable")
    if profile in NEEDS_CA_OCSP:
        pytest.skip("needs a CA-issued cert with reachable OCSP/CRL; run via the real DSC token path")


def _token_flow(api, profile, pdf, key_type="rsa", digest="sha256", options=None):
    """browser+token round trip: start -> sign hash -> complete -> download."""
    key, cert_der = make_signer_cert(key_type)
    opts = {"profile": profile, "digest_algorithm": digest}
    if options:
        opts.update(options)
    r = api.post("/signatures", json={
        "document": b64(pdf), "certificate": b64(cert_der), "options": opts})
    r.raise_for_status()
    start = r.json()
    assert start["digest_algorithm"] == digest
    sig = sign_hash(key, start["to_sign_hash"], digest)
    r = api.post(f"/signatures/{start['session_id']}/complete", json={"signature": sig})
    r.raise_for_status()
    done = r.json()
    signed = _download(api, done["download_url"])
    return signed, done["audit"]


def _download(api, url):
    r = api.get(url.replace("/api", "", 1) if url.startswith("/api") else url)
    r.raise_for_status()
    return r.content


def _validate(api, doc_bytes):
    r = api.post("/validate", json={"document": b64(doc_bytes)})
    r.raise_for_status()
    return r.json()


def _assert_valid(api, signed, field_hint=None):
    report = _validate(api, signed)
    assert report["signatures"], "validator found no signatures"
    sig = report["signatures"][0]
    assert sig["valid"] is True, f"signature not valid: {sig}"
    assert sig["intact"] is True, f"signature not intact: {sig}"
    return report


# ---------------------------------------------------------------- PDF matrix

@pytest.mark.parametrize("profile", ALL_PDF_PROFILES)
def test_pdf_token_flow(api, tsa_reachable, profile):
    _skip_if_unrunnable(profile, tsa_reachable)
    signed, audit = _token_flow(api, profile, make_blank_pdf())
    assert signed[:5] == b"%PDF-"
    assert audit["profile"] == profile
    report = _assert_valid(api, signed)
    # Structural expectations per profile (checked on the real-DSC path):
    if profile in ("B-T", "B-LTA", "CCA-LTA"):
        assert has_signature_timestamp(signed)
    if profile in ("B-LT", "B-LTA"):
        certs, ocsps, crls = read_dss(signed)
        assert certs and (ocsps or crls), "LTV signature lacks a populated DSS"
    if profile in ("CCA-LTV", "CCA-LTA"):
        assert has_cca_revinfo(signed), "CCA signature lacks pdfRevocationInfoArchival"


@pytest.mark.parametrize("profile", ALL_PDF_PROFILES)
def test_pdf_server_side(api, tsa_reachable, profile):
    _skip_if_unrunnable(profile, tsa_reachable)
    r = api.post("/sign-server-side", json={
        "document": b64(make_blank_pdf()), "options": {"profile": profile}})
    r.raise_for_status()
    signed = _download(api, r.json()["download_url"])
    assert signed[:5] == b"%PDF-"
    _assert_valid(api, signed)


@pytest.mark.parametrize("digest", ["sha256", "sha384", "sha512"])
def test_pdf_digest_algorithms(api, digest):
    signed, _ = _token_flow(api, "B-B", make_blank_pdf(), digest=digest)
    _assert_valid(api, signed)


@pytest.mark.parametrize("key_type", ["rsa", "ec"])
def test_pdf_key_types(api, key_type):
    signed, _ = _token_flow(api, "B-B", make_blank_pdf(), key_type=key_type)
    _assert_valid(api, signed)


@pytest.mark.parametrize("appearance", [
    None,  # invisible
    {"page": 0, "box": [72, 72, 272, 122]},
    {"page": 0, "position": "bottom-right", "size": [200, 50]},
])
def test_pdf_appearance_variants(api, appearance):
    opts = {"reason": "e2e", "location": "sandbox"}
    if appearance is not None:
        opts["appearance"] = appearance
    signed, _ = _token_flow(api, "B-B", make_blank_pdf(), options=opts)
    _assert_valid(api, signed)


def test_validate_reports_no_pdfa_for_plain_pdf(api):
    signed, _ = _token_flow(api, "B-B", make_blank_pdf())
    assert _validate(api, signed).get("pdfa") is None


# ---------------------------------------------------------------- batch

def test_batch_flow(api):
    key, cert_der = make_signer_cert("rsa")
    docs = [make_blank_pdf(), make_blank_pdf()]
    r = api.post("/signatures/batch", json={
        "documents": [b64(d) for d in docs], "certificate": b64(cert_der),
        "options": {"profile": "B-B"}})
    r.raise_for_status()
    batch = r.json()
    assert len(batch["sessions"]) == 2
    items = [{"session_id": s["session_id"], "signature": sign_hash(key, s["to_sign_hash"])}
             for s in batch["sessions"]]
    r = api.post("/signatures/batch-complete", json={"items": items})
    r.raise_for_status()
    for out in r.json()["documents"]:
        _assert_valid(api, _download(api, out["download_url"]))


# ---------------------------------------------------------------- CAdES / XAdES

@pytest.mark.parametrize("profile", ["B-B", "B-T"])
def test_cades_token_flow(api, tsa_reachable, profile):
    if profile == "B-T" and not tsa_reachable:
        pytest.skip("TSA unreachable")
    key, cert_der = make_signer_cert("rsa")
    blob = b"any bytes, not a pdf, detached CAdES over this"
    r = api.post("/cades/signatures", json={
        "document": b64(blob), "certificate": b64(cert_der),
        "options": {"profile": profile}})
    r.raise_for_status()
    start = r.json()
    sig = sign_hash(key, start["to_sign_hash"])
    r = api.post(f"/cades/signatures/{start['session_id']}/complete", json={"signature": sig})
    r.raise_for_status()
    p7s = _download(api, r.json()["download_url"])
    assert p7s and len(p7s) > 100  # a real detached CMS came back


def test_cades_server_side(api):
    r = api.post("/cades/sign-server-side", json={
        "document": b64(b"detached over these bytes"), "options": {"profile": "B-B"}})
    r.raise_for_status()
    assert _download(api, r.json()["download_url"])


def test_xades_server_side(api):
    r = api.post("/xades/sign-server-side", json={"document": b64(make_xml()), "options": {}})
    r.raise_for_status()
    signed = _download(api, r.json()["download_url"])
    assert b"Signature" in signed and signed.lstrip().startswith(b"<")


# ---------------------------------------------------------------- error paths

def test_unknown_profile_rejected(api):
    key, cert_der = make_signer_cert("rsa")
    r = api.post("/signatures", json={
        "document": b64(make_blank_pdf()), "certificate": b64(cert_der),
        "options": {"profile": "B-NOPE"}})
    assert r.status_code >= 400
    assert r.json()["error"]["code"] == "PROFILE_UNSUPPORTED"


def test_garbage_document_rejected(api):
    key, cert_der = make_signer_cert("rsa")
    r = api.post("/signatures", json={
        "document": b64(b"not a pdf"), "certificate": b64(cert_der),
        "options": {"profile": "B-B"}})
    assert r.status_code >= 400
    assert r.json()["error"]["code"] == "DOCUMENT_INVALID"


def test_complete_unknown_session(api):
    r = api.post("/signatures/does-not-exist/complete", json={"signature": b64(b"x")})
    assert r.status_code >= 400
    assert r.json()["error"]["code"] in ("SESSION_NOT_FOUND", "SESSION_EXPIRED")


def test_bad_signature_rejected(api):
    key, cert_der = make_signer_cert("rsa")
    r = api.post("/signatures", json={
        "document": b64(make_blank_pdf()), "certificate": b64(cert_der),
        "options": {"profile": "B-B"}})
    r.raise_for_status()
    session_id = r.json()["session_id"]
    r = api.post(f"/signatures/{session_id}/complete", json={"signature": b64(b"\x00" * 256)})
    assert r.status_code >= 400
    assert r.json()["error"]["code"] in ("SIGNATURE_INVALID", "INTERNAL")


def test_oversized_document_rejected(api):
    key, cert_der = make_signer_cert("rsa")
    big = b"%PDF-1.7\n" + b"0" * (51 * 1024 * 1024)
    r = api.post("/signatures", json={
        "document": b64(big), "certificate": b64(cert_der),
        "options": {"profile": "B-B"}})
    assert r.status_code >= 400
