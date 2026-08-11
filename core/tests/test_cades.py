"""Detached CAdES round trips with the in-memory signer key."""

import hashlib

import pytest
from asn1crypto import cms
from helpers_core import sign_hash

from docsigner_core import SignerError
from docsigner_core.cades import CadesSession, CadesState

DATA = b"quarterly returns, attached as filed"


def _round_trip(signer, data, profile, timestamper=None):
    key, cert_der = signer
    state, to_sign_hash, _ = CadesSession.start(
        data, cert_der, {"profile": profile}, timestamper=timestamper
    )
    state = CadesState.from_bytes(state.to_bytes())  # survive the store
    return CadesSession.complete(state, sign_hash(key, to_sign_hash), timestamper=timestamper)


def _signer_info(p7s: bytes):
    content = cms.ContentInfo.load(p7s)
    assert content["content_type"].native == "signed_data"
    signed_data = content["content"]
    assert signed_data["encap_content_info"]["content"].native is None  # detached
    return signed_data["signer_infos"][0]


def test_cades_bb_round_trip(signer):
    p7s = _round_trip(signer, DATA, "B-B")
    info = _signer_info(p7s)
    attrs = {a["type"].native: a for a in info["signed_attrs"]}
    assert attrs["message_digest"]["values"][0].native == hashlib.sha256(DATA).digest()
    assert "signing_certificate_v2" in attrs  # the CAdES marker
    assert "signing_time" in attrs


def test_cades_bt_adds_timestamp(signer, dummy_timestamper):
    p7s = _round_trip(signer, DATA, "B-T", dummy_timestamper)
    unsigned = {a["type"].native for a in _signer_info(p7s)["unsigned_attrs"]}
    assert "signature_time_stamp_token" in unsigned


def test_cades_rejects_ltv_profiles(signer):
    with pytest.raises(SignerError) as err:
        CadesSession.start(DATA, signer[1], {"profile": "B-LTA"})
    assert err.value.code == "PROFILE_UNSUPPORTED"


def test_pdf_session_blob_is_not_a_cades_session():
    with pytest.raises(SignerError):
        CadesState.from_bytes(b'{"kind": "pdf", "whatever": 1}')
