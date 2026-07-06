"""A two-cert test PKI for the LTV tests: root CA, leaf signer, and a CRL.

Everything lives in memory and the CRL is empty (nothing revoked), which is
exactly what a validation context needs to certify a chain offline.
"""

import dataclasses
import datetime

from asn1crypto import crl as asn1_crl
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# A URL nobody fetches: it only marks the leaf as CRL-capable so validators
# consult the CRLs preloaded into the validation context.
CRL_DP_URL = "http://crl.invalid/root.crl"


@dataclasses.dataclass
class TestPki:
    root_cert: asn1_x509.Certificate
    leaf_key: rsa.RSAPrivateKey
    leaf_cert_der: bytes
    crl: asn1_crl.CertificateList


def _name(common_name):
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenSigner Tests"),
        ]
    )


def make_test_pki() -> TestPki:
    now = datetime.datetime.now(datetime.timezone.utc)
    root_name = _name("LTV Test Root CA")

    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_cert = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(root_key, hashes.SHA256())
    )

    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(_name("LTV Test Signer"))
        .issuer_name(root_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.CRLDistributionPoints(
                [
                    x509.DistributionPoint(
                        full_name=[x509.UniformResourceIdentifier(CRL_DP_URL)],
                        relative_name=None,
                        reasons=None,
                        crl_issuer=None,
                    )
                ]
            ),
            critical=False,
        )
        .sign(root_key, hashes.SHA256())
    )

    crl = (
        x509.CertificateRevocationListBuilder()
        .issuer_name(root_name)
        .last_update(now - datetime.timedelta(hours=1))
        .next_update(now + datetime.timedelta(days=7))
        .sign(root_key, hashes.SHA256())
    )

    return TestPki(
        root_cert=asn1_x509.Certificate.load(
            root_cert.public_bytes(serialization.Encoding.DER)
        ),
        leaf_key=leaf_key,
        leaf_cert_der=leaf_cert.public_bytes(serialization.Encoding.DER),
        crl=asn1_crl.CertificateList.load(crl.public_bytes(serialization.Encoding.DER)),
    )
