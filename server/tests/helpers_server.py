"""Server-suite helpers: the dummy timestamper, plus the shared fixtures.

Kept out of conftest.py so tests can import them by a name that stays
unique when several test suites run in one pytest invocation.
"""

# The blank PDF, the self-signed cert and the token-style hash signature are the
# same three every suite needs, so they live once in core/tests (on the path via
# pytest.ini) and are re-exported here under the name this suite already imports.
from helpers_core import make_blank_pdf, make_self_signed_cert, sign_hash  # noqa: F401


def make_dummy_timestamper():
    from asn1crypto import keys as asn1_keys
    from asn1crypto import x509 as asn1_x509
    from cryptography.hazmat.primitives import serialization
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
