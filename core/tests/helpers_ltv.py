"""A two-cert test PKI for the LTV tests: root CA, leaf signer, CRL, OCSP.

Everything lives in memory. The CRL is empty (nothing revoked) and the OCSP
response reports the leaf as good, which is exactly what a validation context
needs to certify a chain offline through either source.
"""

import dataclasses
import datetime

from asn1crypto import crl as asn1_crl
from asn1crypto import ocsp as asn1_ocsp
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509 import ocsp as x509_ocsp
from cryptography.x509.oid import (
    AuthorityInformationAccessOID,
    ExtendedKeyUsageOID,
    NameOID,
)

# URLs nobody fetches: they only mark the leaf as CRL- and OCSP-capable so
# validators consult the revocation data preloaded into the validation context.
CRL_DP_URL = "http://crl.invalid/root.crl"
AIA_OCSP_URL = "http://ocsp.invalid/root"


@dataclasses.dataclass
class TestPki:
    root_cert: asn1_x509.Certificate
    leaf_key: rsa.RSAPrivateKey
    leaf_cert_der: bytes
    crl: asn1_crl.CertificateList
    ocsp: asn1_ocsp.OCSPResponse


def _name(common_name):
    return x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OpenSigner Tests"),
        ]
    )


def make_test_pki(delegated_ocsp: bool = False) -> TestPki:
    """A root CA, a leaf signer, an empty CRL, and a 'good' OCSP response.

    With ``delegated_ocsp`` the OCSP response is signed by a separate responder
    certificate that carries the OCSP-signing usage but not id-pkix-ocsp-nocheck,
    the way the CCA India and Capricorn responders do. A validator that re-checks
    the responder's own revocation then needs the CRL, so once OCSP-first sizing
    drops it the DSS can only be built by embedding the gathered revinfo directly.
    """
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
        .add_extension(
            x509.AuthorityInformationAccess(
                [
                    x509.AccessDescription(
                        AuthorityInformationAccessOID.OCSP,
                        x509.UniformResourceIdentifier(AIA_OCSP_URL),
                    )
                ]
            ),
            critical=False,
        )
        .sign(root_key, hashes.SHA256())
    )

    ocsp_builder = x509_ocsp.OCSPResponseBuilder().add_response(
        cert=leaf_cert,
        issuer=root_cert,
        algorithm=hashes.SHA1(),
        cert_status=x509_ocsp.OCSPCertStatus.GOOD,
        this_update=now - datetime.timedelta(minutes=5),
        next_update=now + datetime.timedelta(days=7),
        revocation_time=None,
        revocation_reason=None,
    )
    if delegated_ocsp:
        responder_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        responder_cert = (
            x509.CertificateBuilder()
            .subject_name(_name("LTV Test OCSP Responder"))
            .issuer_name(root_name)
            .public_key(responder_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.OCSP_SIGNING]), critical=False
            )
            .sign(root_key, hashes.SHA256())
        )
        ocsp_response = (
            ocsp_builder.certificates([responder_cert])
            .responder_id(x509_ocsp.OCSPResponderEncoding.HASH, responder_cert)
            .sign(responder_key, hashes.SHA256())
        )
    else:
        ocsp_response = ocsp_builder.responder_id(
            x509_ocsp.OCSPResponderEncoding.NAME, root_cert
        ).sign(root_key, hashes.SHA256())

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
        ocsp=asn1_ocsp.OCSPResponse.load(
            ocsp_response.public_bytes(serialization.Encoding.DER)
        ),
    )
