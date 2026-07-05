import pytest
from helpers_core import make_self_signed_cert
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption
from cryptography.hazmat.primitives.serialization.pkcs12 import (
    serialize_key_and_certificates,
)

from signer_core import SignerError, sign_with_p12, validate

PASSPHRASE = "p12-secret"


@pytest.fixture(scope="module")
def p12_path(tmp_path_factory):
    key, cert = make_self_signed_cert("P12 Signer")
    p12_bytes = serialize_key_and_certificates(
        b"p12-signer", key, cert, None, BestAvailableEncryption(PASSPHRASE.encode())
    )
    path = tmp_path_factory.mktemp("p12") / "signer.p12"
    path.write_bytes(p12_bytes)
    return str(path)


def test_sign_with_p12(p12_path, blank_pdf):
    signed_pdf = sign_with_p12(
        blank_pdf, p12_path, PASSPHRASE, {"profile": "B-B", "reason": "testing"}
    )
    r = validate(signed_pdf)[0]
    assert r["intact"] and r["valid"]
    assert "P12 Signer" in r["signer"]


def test_sign_with_p12_bt(p12_path, blank_pdf, dummy_timestamper):
    signed_pdf = sign_with_p12(
        blank_pdf, p12_path, PASSPHRASE, {"profile": "B-T"},
        timestamper=dummy_timestamper,
    )
    r = validate(signed_pdf)[0]
    assert r["intact"] and r["valid"]


def test_lt_without_trust_is_rejected(p12_path, blank_pdf, dummy_timestamper):
    with pytest.raises(SignerError) as err:
        sign_with_p12(
            blank_pdf, p12_path, PASSPHRASE, {"profile": "B-LT"},
            timestamper=dummy_timestamper,
        )
    assert err.value.code == "PROFILE_UNSUPPORTED"


def test_wrong_passphrase(p12_path, blank_pdf):
    with pytest.raises(SignerError) as err:
        sign_with_p12(blank_pdf, p12_path, "wrong", {})
    assert err.value.code == "INTERNAL"
