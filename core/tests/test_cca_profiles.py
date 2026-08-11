"""CCA India ESAIG profiles: PKCS#7 with pdfRevocationInfoArchival, offline.

CCA-LTV carries the chain's revocation data as a signed attribute
(OID 1.2.840.113583.1.1.8); CCA-LTA adds an RFC 3161 signature timestamp.
"""

import io

import pytest
from helpers_core import sign_hash
from helpers_ltv import make_test_pki
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation.dss import DocumentSecurityStore
from pyhanko_certvalidator import ValidationContext

from docsigner_core import SignerError, SigningSession, validate

REVINFO_OID = "1.2.840.113583.1.1.8"


@pytest.fixture(scope="module")
def pki():
    return make_test_pki()


def _offline_context(pki, dummy_timestamper):
    return ValidationContext(
        trust_roots=[pki.root_cert, dummy_timestamper.tsa_cert],
        crls=[pki.crl],
        allow_fetching=False,
        revocation_mode="require",
    )


def _round_trip(pki, blank_pdf, profile, timestamper, context):
    state, to_sign_hash, _ = SigningSession.start(
        blank_pdf,
        pki.leaf_cert_der,
        {"profile": profile},
        timestamper=timestamper,
        validation_context=context,
    )
    return SigningSession.complete(
        state, sign_hash(pki.leaf_key, to_sign_hash), timestamper=timestamper
    )


def _signed_attr_oids(embedded_sig):
    return {a["type"].dotted for a in embedded_sig.signer_info["signed_attrs"]}


def test_cca_ltv_embeds_revinfo_signed_attr(pki, blank_pdf, dummy_timestamper):
    signed_pdf = _round_trip(
        pki, blank_pdf, "CCA-LTV", None, _offline_context(pki, dummy_timestamper)
    )

    reader = PdfFileReader(io.BytesIO(signed_pdf), strict=False)
    emb = reader.embedded_signatures[0]
    assert str(emb.sig_object["/SubFilter"]) == "/adbe.pkcs7.detached"
    assert REVINFO_OID in _signed_attr_oids(emb)

    # A DSS mirrors the signed-attribute revocation so Adobe shows the file as
    # LTV enabled; the CRL from the offline PKI carries over.
    dss = DocumentSecurityStore.read_dss(reader)
    assert dss.crls, "the DSS must carry the chain's revocation data"
    # The signer's chain rides along too: the CMS holds only the leaf, so without
    # the extra certs a reader could not build the path (Adobe: not LTV enabled).
    assert len(dss.certs) >= 2, "the DSS must carry the chain, not just the signer"

    report = validate(signed_pdf, None)[0]
    assert report["valid"] and report["intact"]


def test_cca_lta_adds_timestamp(pki, blank_pdf, dummy_timestamper):
    signed_pdf = _round_trip(
        pki, blank_pdf, "CCA-LTA", dummy_timestamper,
        _offline_context(pki, dummy_timestamper),
    )

    emb = PdfFileReader(io.BytesIO(signed_pdf), strict=False).embedded_signatures[0]
    assert REVINFO_OID in _signed_attr_oids(emb)
    unsigned = {a["type"].native for a in emb.signer_info["unsigned_attrs"]}
    assert "signature_time_stamp_token" in unsigned


def test_cca_ltv_requires_trust_anchors(pki, blank_pdf):
    with pytest.raises(SignerError) as err:
        SigningSession.start(blank_pdf, pki.leaf_cert_der, {"profile": "CCA-LTV"})
    assert err.value.code == "PROFILE_UNSUPPORTED"
