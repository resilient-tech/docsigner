import base64
import io

import pytest
from helpers_core import sign_hash
from pyhanko.pdf_utils.reader import PdfFileReader

from signer_core import SessionState, SignerError, SigningSession, validate


def _round_trip(key, cert_der, pdf_bytes, options, timestamper=None):
    state, to_sign_hash, md = SigningSession.start(
        pdf_bytes, cert_der, options, timestamper=timestamper
    )
    assert md == "sha256"
    assert len(to_sign_hash) == 32
    # State must survive a trip to disk between the two calls.
    restored = SessionState.from_bytes(state.to_bytes())
    return SigningSession.complete(
        restored, sign_hash(key, to_sign_hash), timestamper=timestamper
    )


def test_invisible_signature_round_trip(signer, blank_pdf, tmp_path):
    key, cert_der = signer
    signed_pdf = _round_trip(key, cert_der, blank_pdf, {"profile": "B-B"})

    emb = PdfFileReader(io.BytesIO(signed_pdf)).embedded_signatures[0]
    assert str(emb.sig_object["/SubFilter"]) == "/ETSI.CAdES.detached"

    results = validate(signed_pdf)
    assert len(results) == 1
    r = results[0]
    assert r["intact"] is True
    assert r["valid"] is True
    assert r["trusted"] is False
    assert "Test Signer" in r["signer"]

    # trusted flips once our cert is a trust anchor
    trust_dir = tmp_path / "trust"
    trust_dir.mkdir()
    (trust_dir / "signer.crt").write_bytes(cert_der)
    assert validate(signed_pdf, str(trust_dir))[0]["trusted"] is True


def test_visible_signature_with_image(signer, blank_pdf):
    from PIL import Image

    key, cert_der = signer
    png = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(png, format="PNG")
    options = {
        "field_name": "VisibleSig",
        "reason": "approval",
        "location": "test suite",
        "appearance": {
            "page": 0,
            "box": [72, 72, 272, 122],
            "text": "Signed by {signer}\n{ts}",
            "image": base64.b64encode(png.getvalue()).decode("ascii"),
        },
    }
    signed_pdf = _round_trip(key, cert_der, blank_pdf, options)

    emb = PdfFileReader(io.BytesIO(signed_pdf)).embedded_signatures[0]
    assert emb.field_name == "VisibleSig"
    assert [round(float(v)) for v in emb.sig_field["/Rect"]] == [72, 72, 272, 122]

    r = validate(signed_pdf)[0]
    assert r["intact"] and r["valid"]


def test_bt_profile_embeds_timestamp(signer, blank_pdf, dummy_timestamper):
    key, cert_der = signer
    signed_pdf = _round_trip(
        key, cert_der, blank_pdf, {"profile": "B-T"}, timestamper=dummy_timestamper
    )

    emb = PdfFileReader(io.BytesIO(signed_pdf)).embedded_signatures[0]
    unsigned_attrs = emb.signer_info["unsigned_attrs"]
    assert any(
        attr["type"].native == "signature_time_stamp_token" for attr in unsigned_attrs
    )
    r = validate(signed_pdf)[0]
    assert r["intact"] and r["valid"]


def test_bt_without_timestamper_is_rejected(signer, blank_pdf):
    _, cert_der = signer
    with pytest.raises(SignerError) as err:
        SigningSession.start(blank_pdf, cert_der, {"profile": "B-T"})
    assert err.value.code == "PROFILE_UNSUPPORTED"


def test_garbage_signature_is_rejected(signer, blank_pdf):
    _, cert_der = signer
    state, _, _ = SigningSession.start(blank_pdf, cert_der, {})
    with pytest.raises(SignerError) as err:
        SigningSession.complete(state, b"\x00" * 256)
    assert err.value.code == "SIGNATURE_INVALID"


def test_unknown_profile_is_rejected(signer, blank_pdf):
    _, cert_der = signer
    with pytest.raises(SignerError) as err:
        SigningSession.start(blank_pdf, cert_der, {"profile": "B-X"})
    assert err.value.code == "PROFILE_UNSUPPORTED"


def test_bad_document_and_cert(signer, blank_pdf):
    _, cert_der = signer
    with pytest.raises(SignerError) as err:
        SigningSession.start(b"not a pdf", cert_der, {})
    assert err.value.code == "DOCUMENT_INVALID"

    with pytest.raises(SignerError) as err:
        SigningSession.start(blank_pdf, b"\x00\x01junk", {})
    assert err.value.code == "CERT_INVALID"
