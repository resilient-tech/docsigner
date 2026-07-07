"""Token-session B-LT and B-LTA, fully offline against the test PKI."""

import io

import pytest
from helpers_core import sign_hash
from helpers_ltv import make_test_pki
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign.validation.dss import DocumentSecurityStore
from pyhanko_certvalidator import ValidationContext

from signer_core import SignerError, SigningSession, validate


@pytest.fixture(scope="module")
def pki():
    return make_test_pki()


def _offline_context(pki, dummy_timestamper):
    """Fresh per use: validation contexts accumulate state.

    The dummy TSA cert rides along as a trust root so the signature and
    archive timestamps validate too. revocation_mode="require" mirrors what
    a B-LT signature promises: no chain without revocation data.
    """
    return ValidationContext(
        trust_roots=[pki.root_cert, dummy_timestamper.tsa_cert],
        crls=[pki.crl],
        allow_fetching=False,
        revocation_mode="require",
    )


def _round_trip(pki, blank_pdf, profile, timestamper, context_factory):
    state, to_sign_hash, _ = SigningSession.start(
        blank_pdf,
        pki.leaf_cert_der,
        {"profile": profile},
        timestamper=timestamper,
        validation_context=context_factory(),
    )
    return SigningSession.complete(
        state,
        sign_hash(pki.leaf_key, to_sign_hash),
        timestamper=timestamper,
        validation_context=context_factory(),
    )


def test_blt_embeds_dss(pki, blank_pdf, dummy_timestamper):
    def ctx():
        return _offline_context(pki, dummy_timestamper)

    signed_pdf = _round_trip(pki, blank_pdf, "B-LT", dummy_timestamper, ctx)

    reader = PdfFileReader(io.BytesIO(signed_pdf), strict=False)
    dss = DocumentSecurityStore.read_dss(reader)
    assert dss.crls, "the DSS must carry the chain's revocation data"
    assert dss.certs, "the DSS must carry the chain's certificates"
    # Still one ordinary signature, no document timestamp at this level.
    assert len(reader.embedded_regular_signatures) == 1
    assert len(reader.embedded_timestamp_signatures) == 0

    result = validate(signed_pdf)[0]
    assert result["intact"] and result["valid"]


def test_blta_ocsp_only_dss_when_crl_not_needed(pki, blank_pdf, dummy_timestamper):
    """When OCSP alone verifies the chain, the DSS carries no CRL.

    The certvalidator fetcher is OCSP-first and pulls a CRL only when OCSP cannot
    answer. Here the responder is the issuer itself, so its OCSP response stands
    on its own and no CRL is gathered or embedded.
    """

    def ctx():
        return ValidationContext(
            trust_roots=[pki.root_cert, dummy_timestamper.tsa_cert],
            ocsps=[pki.ocsp],
            allow_fetching=False,
            revocation_mode="require",
        )

    signed_pdf = _round_trip(pki, blank_pdf, "B-LTA", dummy_timestamper, ctx)

    reader = PdfFileReader(io.BytesIO(signed_pdf), strict=False)
    dss = DocumentSecurityStore.read_dss(reader)
    assert dss.ocsps, "the DSS must carry the chain's OCSP responses"
    assert not dss.crls, "no CRL is needed when OCSP verifies the chain"
    assert len(reader.embedded_timestamp_signatures) == 1

    result = validate(signed_pdf)[0]
    assert result["intact"] and result["valid"]


def test_blt_keeps_crl_for_delegated_responder(blank_pdf, dummy_timestamper):
    """A delegated OCSP responder without ocsp-nocheck needs its CRL kept.

    The Capricorn and CCA India responders sign with a delegated certificate and
    omit id-pkix-ocsp-nocheck, so verifying their OCSP response means checking the
    responder's own revocation against a CRL. Dropping that CRL leaves the chain
    unverifiable offline, which Adobe reports as not LTV enabled, so the CRL the
    fetcher gathered has to survive into the DSS.
    """
    pki = make_test_pki(delegated_ocsp=True)

    def ctx():
        return ValidationContext(
            trust_roots=[pki.root_cert, dummy_timestamper.tsa_cert],
            crls=[pki.crl],
            ocsps=[pki.ocsp],
            allow_fetching=False,
            revocation_mode="require",
        )

    signed_pdf = _round_trip(pki, blank_pdf, "B-LT", dummy_timestamper, ctx)

    reader = PdfFileReader(io.BytesIO(signed_pdf), strict=False)
    dss = DocumentSecurityStore.read_dss(reader)
    assert dss.ocsps, "the DSS must carry the delegated OCSP response"
    assert dss.crls, "the responder's CRL must survive so its OCSP can be verified"

    result = validate(signed_pdf)[0]
    assert result["intact"] and result["valid"]


def test_blta_adds_archive_timestamp(pki, blank_pdf, dummy_timestamper):
    def ctx():
        return _offline_context(pki, dummy_timestamper)

    signed_pdf = _round_trip(pki, blank_pdf, "B-LTA", dummy_timestamper, ctx)

    reader = PdfFileReader(io.BytesIO(signed_pdf), strict=False)
    assert DocumentSecurityStore.read_dss(reader).crls
    assert len(reader.embedded_regular_signatures) == 1
    timestamps = reader.embedded_timestamp_signatures
    assert len(timestamps) == 1
    assert str(timestamps[0].sig_object["/Type"]) == "/DocTimeStamp"


def test_blt_with_untrusted_chain_fails(pki, blank_pdf, dummy_timestamper):
    # The TSA root alone cannot certify the signer chain.
    def ctx():
        return ValidationContext(
            trust_roots=[dummy_timestamper.tsa_cert],
            allow_fetching=False,
        )

    with pytest.raises(SignerError) as err:
        _round_trip(pki, blank_pdf, "B-LT", dummy_timestamper, ctx)
    assert err.value.code == "INTERNAL"
    assert "revocation" in err.value.message


def test_blt_start_requires_timestamper(pki, blank_pdf, dummy_timestamper):
    with pytest.raises(SignerError) as err:
        SigningSession.start(
            blank_pdf,
            pki.leaf_cert_der,
            {"profile": "B-LT"},
            validation_context=_offline_context(pki, dummy_timestamper),
        )
    assert err.value.code == "PROFILE_UNSUPPORTED"
    assert "TSA_URL" in err.value.message


def test_blt_start_requires_trust_anchors(pki, blank_pdf, dummy_timestamper):
    with pytest.raises(SignerError) as err:
        SigningSession.start(
            blank_pdf,
            pki.leaf_cert_der,
            {"profile": "B-LT"},
            timestamper=dummy_timestamper,
        )
    assert err.value.code == "PROFILE_UNSUPPORTED"
    assert "TRUST_DIR" in err.value.message


def test_profile_output_sizes(pki, blank_pdf, dummy_timestamper):
    """Each profile costs an incremental update; print what it adds up to."""

    def ctx():
        return _offline_context(pki, dummy_timestamper)

    sizes = {"input": len(blank_pdf)}
    for profile in ("B-T", "B-LT", "B-LTA"):
        signed_pdf = _round_trip(pki, blank_pdf, profile, dummy_timestamper, ctx)
        sizes[profile] = len(signed_pdf)

    print("\nblank-PDF output sizes:", sizes)
    assert sizes["B-T"] < sizes["B-LT"] < sizes["B-LTA"]
