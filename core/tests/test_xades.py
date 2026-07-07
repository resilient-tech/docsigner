"""Server-side XAdES: sign with a P12, verify the XML-DSig, spot the XAdES marks."""

import pytest
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, Encoding
from cryptography.hazmat.primitives.serialization.pkcs12 import (
    serialize_key_and_certificates,
)
from helpers_core import make_self_signed_cert

from signer_core import SignerError
from signer_core.xades import sign_xml_with_p12

PASSPHRASE = "test-passphrase"


@pytest.fixture(scope="module")
def p12(tmp_path_factory):
    key, cert = make_self_signed_cert("XAdES Test Signer")
    path = tmp_path_factory.mktemp("xades") / "signer.p12"
    path.write_bytes(
        serialize_key_and_certificates(
            b"t", key, cert, None, BestAvailableEncryption(PASSPHRASE.encode())
        )
    )
    return path, cert


def test_xades_sign_and_verify(p12):
    from signxml import XMLVerifier

    path, cert = p12
    signed = sign_xml_with_p12(b"<invoice><total>100</total></invoice>", path, PASSPHRASE)

    assert b"QualifyingProperties" in signed  # XAdES qualifying block present
    # Three references: the document, the XAdES SignedProperties, and KeyInfo.
    XMLVerifier().verify(
        signed, x509_cert=cert.public_bytes(Encoding.PEM).decode(), expect_references=3
    )


def test_xades_rejects_malformed_xml(p12):
    path, _ = p12
    with pytest.raises(SignerError) as err:
        sign_xml_with_p12(b"not xml at all", path, PASSPHRASE)
    assert err.value.code == "DOCUMENT_INVALID"
