"""Shared fixtures: in-memory certs and keys plus a minimal blank PDF.

The plain helper functions live in helpers_core.py; see the note there.
"""

import pytest
from cryptography.hazmat.primitives import serialization
from helpers_core import make_blank_pdf, make_self_signed_cert


@pytest.fixture(scope="session")
def signer():
    key, cert = make_self_signed_cert()
    return key, cert.public_bytes(serialization.Encoding.DER)


@pytest.fixture(scope="session")
def blank_pdf():
    return make_blank_pdf()


@pytest.fixture(scope="session")
def dummy_timestamper():
    from asn1crypto import keys as asn1_keys
    from asn1crypto import x509 as asn1_x509
    from pyhanko.sign.timestamps.dummy_client import DummyTimeStamper
    from pyhanko_certvalidator.registry import SimpleCertificateStore

    key, cert = make_self_signed_cert("Test TSA", timestamping=True)
    tsa_cert = asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))
    tsa_key = asn1_keys.PrivateKeyInfo.load(
        key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    store = SimpleCertificateStore()
    store.register(tsa_cert)
    return DummyTimeStamper(tsa_cert=tsa_cert, tsa_key=tsa_key, certs_to_embed=store)
